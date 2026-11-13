"""
LORE Enterprise — Isolated Visual Extraction Module
===================================================

Provides layout-aware visual region detection, deterministic vector/table/chart
extraction, cropped OCR inspection, and sovereignty-gated VLM extensibility
inside ``apps.ingestion.pipeline``.

Architectural Isolation Contract:
- Strictly lives inside ``apps/ingestion/pipeline/visual.py``.
- Reuses existing LORE extraction, OCR, chunking, validation, residency, and
  execution-mode services without modifying Governance (L0-L7), Hybrid Retrieval,
  or Settlement Layer (S1-S6) responsibilities.
- Emits canonical ``DocumentPage``-compatible page dictionaries while preserving
  word-level ``bounding_boxes`` untouched for existing UI viewers.
"""

import base64
import io
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from PIL import Image, UnidentifiedImageError

from apps.governance.modes import (
    ExecutionMode,
    ModelExecutionMetric,
    ModelTaskPurpose,
    acquire_remote_concurrency_slot,
    get_active_execution_mode,
    is_remote_model_allowed,
    release_remote_concurrency_slot,
    sanitize_sensitive_data,
)
from apps.identity.residency import DataResidencyService, DataResidencyViolation
from apps.knowledge.chunking import StructureAwareChunker
from apps.sources.services import ALLOWED_EXTENSIONS, StorageSecurityService

from .extractors import PresentationExtractor, UnifiedDocumentExtractor
from .ocr import (
    BaseOCRProvider,
    DigitalPDFExtractor,
    HAS_PDFPLUMBER,
    HAS_PYPDFIUM2,
    ImagePreprocessor,
    PDFPageRenderer,
    TesseractOCRProvider,
    bangla_to_arabic_digits,
    is_visual_encoded_document,
    repair_visual_bengali_document,
)

if HAS_PDFPLUMBER:
    import pdfplumber

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

logger = logging.getLogger(__name__)


# ==============================================================================
# CANONICAL ENUMS & VISUAL PROVENANCE CONTRACTS
# ==============================================================================
class VisualRegionType(str, Enum):
    """Semantic classification of detected visual regions."""
    TITLE_HEADING = "title_heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    CHART = "chart"
    DIAGRAM = "diagram"
    FIGURE = "figure"
    EMBEDDED_IMAGE = "embedded_image"
    SVG_GRAPHIC = "svg_graphic"
    STAMP_OR_SEAL = "stamp_or_seal"
    SIGNATURE = "signature"
    FORM_KV = "form_kv"
    HEADER_FOOTER = "header_footer"
    UNKNOWN = "unknown"
    PAGE_SNAPSHOT = "page_snapshot"


class VisualExtractionKind(str, Enum):
    """Epistemic provenance tagging how visual content was obtained."""
    VECTOR_TABLE = "vector_table"
    CHART_SERIES = "chart_series"
    EMBEDDED_ASSET = "embedded_asset"
    OCR_LAYOUT = "ocr_layout"
    HEURISTIC_LAYOUT = "heuristic_layout"
    VISUAL_CAPTION = "visual_caption"


@dataclass
class VisualRegion:
    """
    Structured provenance record for a visual element on a document page.
    Uses LORE's normalized 0-1000 [ymin, xmin, ymax, xmax] coordinate convention.
    """
    region_id: str
    region_type: str
    extraction_kind: str
    page_number: int
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (x, y, w, h) in page space
    normalized_box: List[int] = field(default_factory=lambda: [0, 0, 1000, 1000])
    text: str = ""
    markdown: str = ""
    confidence: float = 0.0
    engine: str = "deterministic_visual"
    engine_version: str = "1.0"
    is_inference: bool = False
    is_repaired: bool = False
    source_asset_name: str = ""
    word_boxes: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_id": self.region_id,
            "region_type": self.region_type,
            "extraction_kind": self.extraction_kind,
            "page_number": self.page_number,
            "bbox": list(self.bbox),
            "normalized_box": list(self.normalized_box),
            "text": self.text,
            "markdown": self.markdown,
            "confidence": round(float(self.confidence), 4),
            "engine": self.engine,
            "engine_version": self.engine_version,
            "is_inference": self.is_inference,
            "is_repaired": self.is_repaired,
            "source_asset_name": self.source_asset_name,
            "word_boxes": list(self.word_boxes),
            "metadata": dict(self.metadata),
        }


# ==============================================================================
# SHARED NORMALIZATION, TABLE & IMAGE CROP HELPERS
# ==============================================================================
def normalize_bbox(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    page_width: float,
    page_height: float,
) -> List[int]:
    """Converts page/pixel coordinates into clamped [ymin, xmin, ymax, xmax] (0-1000)."""
    pw = max(float(page_width or 1.0), 1.0)
    ph = max(float(page_height or 1.0), 1.0)
    ymin = max(0, min(1000, round((float(y0) / ph) * 1000)))
    xmin = max(0, min(1000, round((float(x0) / pw) * 1000)))
    ymax = max(ymin, min(1000, round((float(y1) / ph) * 1000)))
    xmax = max(xmin, min(1000, round((float(x1) / pw) * 1000)))
    return [ymin, xmin, ymax, xmax]


def apply_text_normalization(
    text: str,
    repair_bengali: bool = True,
    convert_bangla_digits: bool = False,
) -> Tuple[str, bool]:
    """Reuses LORE's Bengali visual-order repair and Bangla digit translation."""
    if not text:
        return "", False

    repaired = False
    out = text
    if repair_bengali and is_visual_encoded_document(out):
        fixed = repair_visual_bengali_document(out)
        if fixed != out:
            out = fixed
            repaired = True

    if convert_bangla_digits:
        converted = bangla_to_arabic_digits(out)
        if converted != out:
            out = converted
            repaired = True

    return out.strip(), repaired


def format_markdown_table(rows: Iterable[Iterable[Any]]) -> str:
    """
    Formats tabular rows into clean Markdown pipe syntax compatible with
    ``StructureAwareChunker._detect_table_header``.
    """
    cleaned_rows: List[List[str]] = []
    for row in rows:
        cells = [
            "" if cell is None else str(cell).replace("\n", " ").replace("|", "\\|").strip()
            for cell in row
        ]
        if any(cells):
            cleaned_rows.append(cells)

    if not cleaned_rows:
        return ""

    max_cols = max(len(r) for r in cleaned_rows)
    padded = [r + [""] * (max_cols - len(r)) for r in cleaned_rows]
    header = "| " + " | ".join(padded[0]) + " |"
    separator = "| " + " | ".join(["---"] * max_cols) + " |"
    body = ["| " + " | ".join(r) + " |" for r in padded[1:]]
    return "\n".join([header, separator] + body)


def format_visual_region_markdown(
    page_number: int,
    region_id: str,
    title: str,
    body: str,
) -> str:
    """
    Formats a single visual region as a self-contained section compatible with
    ``StructureAwareChunker._split_into_sections`` (avoiding empty wrapper headings).
    """
    clean_body = (body or "").strip()
    if not clean_body:
        return ""
    return f"### Visual Evidence (Page {page_number}) — {title} [{region_id}]\n[region_id={region_id}]\n{clean_body}"


def crop_image_safe(
    image: Image.Image,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    padding: int = 8,
    min_side: int = 16,
) -> Optional[Image.Image]:
    """
    Safely crops a visual region and pads thin strips onto a white canvas so
    ``ImagePreprocessor.preprocess`` never explodes memory during 1200px upscaling.
    """
    if image is None:
        return None

    img_w, img_h = image.size
    left = max(0, int(x0) - padding)
    top = max(0, int(y0) - padding)
    right = min(img_w, int(x1) + padding)
    bottom = min(img_h, int(y1) + padding)

    crop_w = right - left
    crop_h = bottom - top
    if crop_w < min_side or crop_h < min_side:
        return None

    crop = image.crop((left, top, right, bottom))

    # Protect ImagePreprocessor's min(w, h) < 1200 Lanczos scaler against ultra-thin banners
    aspect = max(crop_w / max(crop_h, 1), crop_h / max(crop_w, 1))
    if aspect > 8.0 or min(crop_w, crop_h) < 64:
        canvas_side = max(crop_w, crop_h, 96)
        rgb_crop = crop.convert("RGB")
        canvas = Image.new("RGB", (max(canvas_side, crop_w), max(canvas_side, crop_h)), (255, 255, 255))
        offset_x = (canvas.width - crop_w) // 2
        offset_y = (canvas.height - crop_h) // 2
        canvas.paste(rgb_crop, (offset_x, offset_y))
        return canvas

    return crop


def _pad_for_ocr_if_needed(image: Image.Image) -> Image.Image:
    """Prevents extreme aspect-ratio enlargement before calling ImagePreprocessor.preprocess."""
    w, h = image.size
    if w <= 0 or h <= 0:
        return image
    aspect = max(w / h, h / w)
    if aspect > 8.0:
        side = max(w, h)
        canvas = Image.new("RGB", (max(side, w), max(side, h)), (255, 255, 255))
        canvas.paste(image.convert("RGB"), ((canvas.width - w) // 2, (canvas.height - h) // 2))
        return canvas
    return image


def _open_image_bytes_safe(raw_bytes: bytes, max_pixels: int = 40_000_000) -> Optional[Image.Image]:
    """Opens raster image bytes safely, guarding against corrupt payloads or pixel bombs."""
    if not raw_bytes:
        return None
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            w, h = img.size
            if w <= 0 or h <= 0 or (w * h) > max_pixels:
                logger.warning("Skipping visual asset with invalid dimensions (%sx%s).", w, h)
                return None
            return img.copy()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.debug("Could not decode raster image asset: %s", exc)
        return None


def _open_zip_safe(file_path_or_bytes: Any) -> Optional[zipfile.ZipFile]:
    """Safely opens an archive stream/path without mutating caller buffer positions."""
    try:
        if isinstance(file_path_or_bytes, (bytes, bytearray)):
            stream: Any = io.BytesIO(file_path_or_bytes)
        else:
            stream = file_path_or_bytes
        if not zipfile.is_zipfile(stream):
            return None
        if isinstance(stream, io.BytesIO):
            stream.seek(0)
        return zipfile.ZipFile(stream, "r")
    except Exception:
        return None


def _resolve_zip_rel_path(base_file: str, target: str) -> str:
    """Normalizes OOXML relative ZIP member paths (e.g. ../charts/chart1.xml -> xl/charts/chart1.xml)."""
    clean_target = (target or "").replace("\\", "/")
    if clean_target.startswith("/"):
        return clean_target.lstrip("/")
    base_dir = os.path.dirname(base_file.replace("\\", "/"))
    joined = os.path.normpath(os.path.join(base_dir, clean_target)).replace("\\", "/")
    return joined.lstrip("/")


def _merge_boxes(boxes: List[Tuple[float, float, float, float]], gap: float = 12.0) -> List[Tuple[float, float, float, float]]:
    """Aggregates nearby drawing rectangles/curves into coherent graphic region boxes."""
    if not boxes:
        return []

    pending = [list(b) for b in boxes]
    merged: List[List[float]] = []

    while pending:
        curr = pending.pop(0)
        changed = True
        while changed:
            changed = False
            rest = []
            for other in pending:
                overlaps_x = (curr[0] - gap) <= other[2] and (other[0] - gap) <= curr[2]
                overlaps_y = (curr[1] - gap) <= other[3] and (other[1] - gap) <= curr[3]
                if overlaps_x and overlaps_y:
                    curr = [
                        min(curr[0], other[0]),
                        min(curr[1], other[1]),
                        max(curr[2], other[2]),
                        max(curr[3], other[3]),
                    ]
                    changed = True
                else:
                    rest.append(other)
            pending = rest
        merged.append(curr)

    return [(b[0], b[1], b[2], b[3]) for b in merged]


# ==============================================================================
# VISUAL PROVIDER INTERFACE & DETERMINISTIC / SOVEREIGN IMPLEMENTATIONS
# ==============================================================================
class BaseVisualProvider:
    """
    Abstract interface for visual region analyzers (parallel to ``BaseOCRProvider``).
    Providers return region-level extractions with explicit confidence and
    ``is_inference`` flags so downstream consumers can separate OCR/vector data from captions.
    """
    provider_name: str = "base_visual"
    engine_version: str = "1.0"
    requires_remote_egress: bool = False

    def is_available(self) -> bool:
        return True

    def analyze_image(
        self,
        image: Image.Image,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError


class LocalDeterministicVisualProvider(BaseVisualProvider):
    """
    Offline deterministic visual analyzer built strictly on Pillow + LORE's OCR stack:
    - Reuses ``ImagePreprocessor`` (EXIF, OSD rotation, contrast/sharpness normalization)
      and injected ``BaseOCRProvider`` (defaults to ``TesseractOCRProvider``).
    - Performs pure-Pillow grid luminance segmentation to isolate non-empty figure/chart/
      diagram blocks even when OCR is unavailable or returns sparse labels.
    - Never performs external network requests.
    """
    provider_name = "local_deterministic_visual"
    engine_version = "1.0"
    requires_remote_egress = False

    def __init__(
        self,
        ocr_provider: Optional[BaseOCRProvider] = None,
        max_regions: int = 8,
        grid_size: int = 48,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
    ):
        self.ocr_provider = ocr_provider or TesseractOCRProvider()
        self.max_regions = max_regions
        self.grid_size = max(16, min(96, grid_size))
        self.repair_bengali = repair_bengali
        self.convert_bangla_digits = convert_bangla_digits

    def is_available(self) -> bool:
        # Grid layout detection via Pillow is always available; OCR sub-engine is optional.
        return True

    def _detect_foreground_blocks(self, image: Image.Image) -> List[Dict[str, Any]]:
        """
        Detects contiguous non-background visual blocks using a fixed grid downsample
        and connected-component BFS. Requires zero external ML/CV dependencies.
        """
        img_w, img_h = image.size
        if img_w <= 0 or img_h <= 0:
            return []

        gw = self.grid_size
        gh = self.grid_size
        thumb_gray = image.convert("L").resize((gw, gh), Image.Resampling.BILINEAR)
        thumb_rgb = image.convert("RGB").resize((gw, gh), Image.Resampling.BILINEAR)
        gray_px = thumb_gray.load()
        rgb_px = thumb_rgb.load()

        # Estimate background luminance from perimeter cells to handle off-white/tinted scans
        border_vals = []
        for gx in range(gw):
            border_vals.append(gray_px[gx, 0])
            border_vals.append(gray_px[gx, gh - 1])
        for gy in range(1, gh - 1):
            border_vals.append(gray_px[0, gy])
            border_vals.append(gray_px[gw - 1, gy])
        border_vals.sort()
        bg_luma = border_vals[len(border_vals) // 2] if border_vals else 255
        threshold = max(40, bg_luma - 18)

        active_cells = set()
        colored_cells = set()
        for gy in range(gh):
            for gx in range(gw):
                lum = gray_px[gx, gy]
                r, g, b = rgb_px[gx, gy]
                chroma = max(r, g, b) - min(r, g, b)
                if lum < threshold or chroma > 24:
                    active_cells.add((gx, gy))
                    if chroma > 24:
                        colored_cells.add((gx, gy))

        if not active_cells:
            return []

        visited = set()
        components: List[Dict[str, Any]] = []
        cell_w = img_w / gw
        cell_h = img_h / gh

        for start in sorted(active_cells):
            if start in visited:
                continue
            queue = deque([start])
            visited.add(start)
            comp_cells = []
            while queue:
                cx, cy = queue.popleft()
                comp_cells.append((cx, cy))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        nxt = (cx + dx, cy + dy)
                        if nxt in active_cells and nxt not in visited:
                            visited.add(nxt)
                            queue.append(nxt)

            # Skip single-cell speckle noise
            if len(comp_cells) < 2 and len(active_cells) > 4:
                continue

            min_gx = min(c[0] for c in comp_cells)
            max_gx = max(c[0] for c in comp_cells) + 1
            min_gy = min(c[1] for c in comp_cells)
            max_gy = max(c[1] for c in comp_cells) + 1

            x0 = int(min_gx * cell_w)
            y0 = int(min_gy * cell_h)
            x1 = min(img_w, int(max_gx * cell_w))
            y1 = min(img_h, int(max_gy * cell_h))
            bw = x1 - x0
            bh = y1 - y0
            area_ratio = (bw * bh) / max(img_w * img_h, 1)
            if area_ratio < 0.005:
                continue

            color_count = sum(1 for c in comp_cells if c in colored_cells)
            color_ratio = color_count / max(len(comp_cells), 1)
            density = len(comp_cells) / max((max_gx - min_gx) * (max_gy - min_gy), 1)

            components.append({
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "area_ratio": area_ratio,
                "color_ratio": color_ratio,
                "density": density,
            })

        components.sort(key=lambda c: c["area_ratio"], reverse=True)
        return components[: self.max_regions]

    def _classify_block_type(self, block: Dict[str, Any], words_count: int) -> str:
        """Deterministic heuristic separating charts/diagrams/figures from sparse layouts."""
        if block.get("color_ratio", 0.0) >= 0.25 and words_count <= 45:
            return VisualRegionType.CHART.value
        if block.get("density", 0.0) < 0.35 and words_count <= 30:
            return VisualRegionType.DIAGRAM.value
        if words_count == 0:
            return VisualRegionType.FIGURE.value
        return VisualRegionType.EMBEDDED_IMAGE.value

    def analyze_image(
        self,
        image: Image.Image,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        t0 = time.time()
        ctx = context or {}
        page_num = int(ctx.get("page_number", 1))
        asset_name = str(ctx.get("source_asset_name", ""))
        forced_type = ctx.get("region_type")
        parent_norm_box = ctx.get("parent_normalized_box")

        try:
            oriented_img, rotated_deg = ImagePreprocessor.detect_and_correct_rotation(image)
            img_w, img_h = oriented_img.size
            blocks = self._detect_foreground_blocks(oriented_img)

            # Run OCR on the preprocessed full image or crop once cleanly
            prep_img = ImagePreprocessor.preprocess(_pad_for_ocr_if_needed(oriented_img), auto_rotate=False)
            ocr_res = self.ocr_provider.extract_image(prep_img)
            ocr_status = ocr_res.get("status", "error")
            ocr_available = ocr_status != "provider_unavailable"

            raw_text = "" if ocr_status == "provider_unavailable" else (ocr_res.get("text") or "")
            norm_text, repaired = apply_text_normalization(
                raw_text,
                repair_bengali=self.repair_bengali,
                convert_bangla_digits=self.convert_bangla_digits,
            )
            word_boxes = ocr_res.get("bounding_boxes", []) if ocr_available else []
            ocr_conf = float(ocr_res.get("confidence", 0.0)) if ocr_available else 0.0

            regions: List[VisualRegion] = []
            if not blocks and not norm_text:
                elapsed_ms = round((time.time() - t0) * 1000.0, 2)
                return {
                    "status": "empty_visual",
                    "regions": [],
                    "text": "",
                    "confidence": 0.0,
                    "width": float(img_w),
                    "height": float(img_h),
                    "engine": self.provider_name,
                    "engine_version": self.engine_version,
                    "is_optional_skipped": not ocr_available,
                    "needs_review": False,
                    "rotated_degrees": rotated_deg,
                    "metrics": ModelExecutionMetric(
                        provider=self.provider_name,
                        model_name="pillow-grid-layout",
                        purpose=ModelTaskPurpose.OCR.value,
                        latency_ms=elapsed_ms,
                        was_deterministic=True,
                        reason="empty_canvas_no_visual_blocks",
                    ).to_dict(),
                }

            # If blocks detected, build region records cleanly; fall back to full asset box if text-only
            effective_blocks = blocks or [{
                "x0": 0, "y0": 0, "x1": img_w, "y1": img_h,
                "area_ratio": 1.0, "color_ratio": 0.0, "density": 0.5,
            }]

            for idx, blk in enumerate(effective_blocks, start=1):
                blk_norm = parent_norm_box or normalize_bbox(
                    blk["x0"], blk["y0"], blk["x1"], blk["y1"], img_w, img_h
                )
                r_type = str(forced_type or self._classify_block_type(blk, len(norm_text.split())))
                region_id = f"p{page_num}-vis{idx}-{r_type}"

                # Crop-level OCR when multiple sub-blocks exist and OCR is available
                region_text = norm_text
                region_boxes = word_boxes
                region_conf = ocr_conf
                region_repaired = repaired
                if ocr_available and len(effective_blocks) > 1:
                    crop = crop_image_safe(oriented_img, blk["x0"], blk["y0"], blk["x1"], blk["y1"])
                    if crop is not None:
                        crop_prep = ImagePreprocessor.preprocess(crop, auto_rotate=False)
                        crop_ocr = self.ocr_provider.extract_image(crop_prep)
                        c_raw = crop_ocr.get("text", "") if crop_ocr.get("status") != "provider_unavailable" else ""
                        c_text, c_rep = apply_text_normalization(
                            c_raw,
                            repair_bengali=self.repair_bengali,
                            convert_bangla_digits=self.convert_bangla_digits,
                        )
                        if c_text:
                            region_text = c_text
                            region_boxes = crop_ocr.get("bounding_boxes", [])
                            region_conf = float(crop_ocr.get("confidence", ocr_conf))
                            region_repaired = c_rep

                if region_text:
                    extraction_kind = VisualExtractionKind.OCR_LAYOUT.value
                    conf = region_conf
                    md = format_visual_region_markdown(page_num, region_id, f"Visual Region ({r_type})", region_text)
                else:
                    extraction_kind = VisualExtractionKind.HEURISTIC_LAYOUT.value
                    conf = 0.35 if ocr_available else 0.30
                    ocr_note = "" if ocr_available else " [OCR provider unavailable]"
                    md = format_visual_region_markdown(
                        page_num,
                        region_id,
                        f"Visual Region ({r_type})",
                        (
                            f"[Non-text visual region detected at normalized box {blk_norm}; "
                            f"area_ratio={blk['area_ratio']:.2f}, color_ratio={blk['color_ratio']:.2f}{ocr_note}]"
                        ),
                    )

                regions.append(VisualRegion(
                    region_id=region_id,
                    region_type=r_type,
                    extraction_kind=extraction_kind,
                    page_number=page_num,
                    bbox=(int(blk["x0"]), int(blk["y0"]), int(blk["x1"] - blk["x0"]), int(blk["y1"] - blk["y0"])),
                    normalized_box=blk_norm,
                    text=region_text,
                    markdown=md,
                    confidence=conf,
                    engine=self.provider_name if ocr_available else f"{self.provider_name}_no_ocr",
                    engine_version=self.engine_version,
                    is_inference=False,
                    is_repaired=region_repaired,
                    source_asset_name=asset_name,
                    word_boxes=region_boxes,
                    metadata={
                        "area_ratio": round(float(blk["area_ratio"]), 4),
                        "color_ratio": round(float(blk["color_ratio"]), 4),
                        "rotated_degrees": rotated_deg,
                        "ocr_available": ocr_available,
                    },
                ))

            avg_conf = sum(r.confidence for r in regions) / max(len(regions), 1)
            has_text = any(bool(r.text.strip()) for r in regions)
            status = "success"
            needs_review = False
            if not has_text or avg_conf < 0.70:
                needs_review = True
                if not has_text and not ocr_available:
                    status = "low_confidence"
                elif avg_conf < 0.40:
                    status = "low_confidence"

            elapsed_ms = round((time.time() - t0) * 1000.0, 2)
            combined_md = "\n\n".join(r.markdown for r in regions if r.markdown)
            return {
                "status": status,
                "regions": [r.to_dict() for r in regions],
                "text": combined_md,
                "confidence": round(avg_conf, 4),
                "width": float(img_w),
                "height": float(img_h),
                "engine": self.provider_name,
                "engine_version": self.engine_version,
                "is_optional_skipped": not ocr_available,
                "needs_review": needs_review,
                "rotated_degrees": rotated_deg,
                "metrics": ModelExecutionMetric(
                    provider=self.provider_name,
                    model_name="pillow+tesseract" if ocr_available else "pillow-grid-layout",
                    purpose=ModelTaskPurpose.OCR.value,
                    latency_ms=elapsed_ms,
                    was_deterministic=True,
                    reason="deterministic_local_visual_extraction",
                ).to_dict(),
            }
        except Exception as exc:
            elapsed_ms = round((time.time() - t0) * 1000.0, 2)
            clean_err = sanitize_sensitive_data(str(exc))
            logger.error("Local visual analysis failed: %s", clean_err)
            return {
                "status": "error",
                "regions": [],
                "text": "",
                "confidence": 0.0,
                "width": 0.0,
                "height": 0.0,
                "engine": self.provider_name,
                "engine_version": self.engine_version,
                "is_optional_skipped": True,
                "needs_review": True,
                "error": clean_err,
                "metrics": ModelExecutionMetric(
                    provider=self.provider_name,
                    model_name="pillow-grid-layout",
                    purpose=ModelTaskPurpose.OCR.value,
                    latency_ms=elapsed_ms,
                    was_deterministic=True,
                    reason=f"error:{clean_err}",
                ).to_dict(),
            }


class SovereigntyGatedRemoteVisualProvider(BaseVisualProvider):
    """
    Sovereignty-enforcing wrapper for optional remote VLM adapters.

    Guarantees (per ``apps.governance.modes`` and ``apps.identity.residency``):
    - ``LOCAL_ONLY`` strictly prohibits all remote calls (zero network egress).
    - Requires explicit tenant authorization AND ``allow_remote_vision != False``.
    - Verifies ``DataResidencyService.check_residency_compliance`` when region
      policy is present.
    - Guards calls with bounded concurrency (``acquire_remote_concurrency_slot``)
      and secret scrubbing (``sanitize_sensitive_data``).
    - Never performs silent fallback to another remote provider on error; falls
      back to ``LocalDeterministicVisualProvider`` with explicit telemetry.
    """
    provider_name = "sovereignty_remote_vlm"
    engine_version = "1.0"
    requires_remote_egress = True

    def __init__(
        self,
        remote_callable: Optional[Callable[[bytes, str, str, float], Dict[str, Any]]] = None,
        local_fallback: Optional[BaseVisualProvider] = None,
        model_name: str = "remote-vlm",
        timeout_seconds: float = 15.0,
        default_prompt: str = (
            "Extract visible tables (as Markdown), chart labels/values, and factual visual "
            "observations only. Do not infer policies or omit numeric labels."
        ),
    ):
        self.remote_callable = remote_callable
        self.local_fallback = local_fallback or LocalDeterministicVisualProvider()
        self.model_name = model_name
        self.timeout_seconds = float(timeout_seconds)
        self.default_prompt = default_prompt

    def is_available(self) -> bool:
        return self.remote_callable is not None

    def _fallback_with_reason(
        self,
        image: Image.Image,
        context: Optional[Dict[str, Any]],
        reason: str,
    ) -> Dict[str, Any]:
        local_res = self.local_fallback.analyze_image(image, context=context)
        metrics = dict(local_res.get("metrics") or {})
        metrics["was_deterministic"] = True
        metrics["remote_blocked_or_fallback_reason"] = sanitize_sensitive_data(reason)
        local_res["metrics"] = metrics
        local_res["fallback_used"] = True
        local_res["fallback_reason"] = sanitize_sensitive_data(reason)
        return local_res

    def analyze_image(
        self,
        image: Image.Image,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ctx = context or {}
        workspace = ctx.get("workspace")
        organization = ctx.get("organization") or (getattr(workspace, "organization", None) if workspace else None)
        policy_context = ctx.get("policy_context") or {}
        requested_mode = ctx.get("execution_mode")

        active_mode = get_active_execution_mode(
            workspace=workspace,
            policy_context=policy_context,
            requested_mode=requested_mode,
        )

        # 1. ExecutionMode & tenant authorization check (reuses governance.modes verbatim)
        allowed, auth_reason = is_remote_model_allowed(
            workspace=workspace,
            organization=organization,
            policy_context=policy_context,
            purpose=ModelTaskPurpose.OCR,
            mode=active_mode,
        )
        if not allowed:
            return self._fallback_with_reason(image, ctx, auth_reason)

        if policy_context.get("allow_remote_vision") is False:
            return self._fallback_with_reason(
                image,
                ctx,
                "Remote visual extraction explicitly disabled via policy_context.allow_remote_vision=False.",
            )

        # 2. Sovereign data residency check (reuses identity.residency verbatim)
        org_region = policy_context.get("organization_region") or getattr(organization, "data_region", None)
        target_region = policy_context.get("target_processing_region")
        if org_region or target_region:
            try:
                DataResidencyService.check_residency_compliance(
                    organization_region=org_region or "us",
                    target_processing_region=target_region or "us",
                    operation_name="visual_extraction",
                )
            except DataResidencyViolation as res_err:
                return self._fallback_with_reason(image, ctx, str(res_err))

        # 3. Verify remote callable exists
        if self.remote_callable is None:
            return self._fallback_with_reason(image, ctx, "No remote visual callable configured.")

        # 4. Acquire bounded concurrency slot
        if not acquire_remote_concurrency_slot(timeout=min(self.timeout_seconds, 10.0)):
            return self._fallback_with_reason(
                image,
                ctx,
                "Remote concurrency budget exhausted; executed deterministic local fallback.",
            )

        t0 = time.time()
        try:
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="PNG")
            img_bytes = buf.getvalue()
            prompt = sanitize_sensitive_data(str(ctx.get("prompt") or self.default_prompt))
            raw_resp = self.remote_callable(img_bytes, prompt, self.model_name, self.timeout_seconds) or {}
            elapsed_ms = round((time.time() - t0) * 1000.0, 2)

            page_num = int(ctx.get("page_number", 1))
            asset_name = str(ctx.get("source_asset_name", ""))
            img_w, img_h = image.size
            caption = str(raw_resp.get("caption") or raw_resp.get("text") or "").strip()
            region_type = str(raw_resp.get("region_type") or ctx.get("region_type") or VisualRegionType.FIGURE.value)
            confidence = float(raw_resp.get("confidence", 0.78 if caption else 0.0))

            markdown_body = caption
            if raw_resp.get("table_rows"):
                tbl_md = format_markdown_table(raw_resp["table_rows"])
                if tbl_md:
                    markdown_body = f"{caption}\n\n{tbl_md}".strip() if caption else tbl_md

            region_id = f"p{page_num}-vlm1-{region_type}"
            norm_box = list(raw_resp.get("normalized_box") or ctx.get("parent_normalized_box") or [0, 0, 1000, 1000])
            region = VisualRegion(
                region_id=region_id,
                region_type=region_type,
                extraction_kind=VisualExtractionKind.VISUAL_CAPTION.value,
                page_number=page_num,
                bbox=(0, 0, img_w, img_h),
                normalized_box=norm_box,
                text=caption,
                markdown=format_visual_region_markdown(
                    page_num, region_id, f"Visual Caption ({region_type})", markdown_body
                ) if markdown_body else "",
                confidence=confidence,
                engine=self.provider_name,
                engine_version=self.engine_version,
                is_inference=True,
                is_repaired=False,
                source_asset_name=asset_name,
                metadata={"model_name": self.model_name, "execution_mode": active_mode.value},
            )

            tokens_prompt = int(raw_resp.get("tokens_prompt", 0))
            tokens_comp = int(raw_resp.get("tokens_completion", 0))
            cost_usd = float(raw_resp.get("cost_usd", 0.0))
            return {
                "status": "success" if markdown_body else "empty_visual",
                "regions": [region.to_dict()] if markdown_body else [],
                "text": region.markdown,
                "confidence": round(confidence, 4),
                "width": float(img_w),
                "height": float(img_h),
                "engine": self.provider_name,
                "engine_version": self.engine_version,
                "is_optional_skipped": False,
                "needs_review": confidence < 0.70,
                "metrics": ModelExecutionMetric(
                    provider=self.provider_name,
                    model_name=self.model_name,
                    purpose=ModelTaskPurpose.OCR.value,
                    latency_ms=elapsed_ms,
                    tokens_prompt=tokens_prompt,
                    tokens_completion=tokens_comp,
                    tokens_total=tokens_prompt + tokens_comp,
                    cost_usd=cost_usd,
                    was_deterministic=False,
                    reason="approved_remote_vlm_invocation",
                ).to_dict(),
            }
        except Exception as exc:
            clean_err = sanitize_sensitive_data(str(exc))
            logger.warning("Remote visual provider error (%s); falling back locally.", clean_err)
            return self._fallback_with_reason(image, ctx, f"remote_vlm_failure:{clean_err}")
        finally:
            release_remote_concurrency_slot()


# ==============================================================================
# FORMAT-SPECIFIC VISUAL PROBES (PDF, OFFICE OOXML, HTML, RASTER IMAGE)
# ==============================================================================
class PDFVisualProbe:
    """
    Detects vector tables, embedded raster images, and graphic clusters in PDFs.
    Selectively renders mixed text+visual pages via ``PDFPageRenderer`` even when
    digital ``char_count > 20`` (avoiding changes to ``ocr.py``).
    """
    MIN_VECTOR_PRIMITIVES = 4
    MIN_GRAPHIC_SIZE_PT = 24.0

    @classmethod
    def _detect_vector_table_regions(
        cls,
        page,
        page_num: int,
        pw: float,
        ph: float,
        repair_bengali: bool,
        convert_bangla_digits: bool,
    ) -> List[VisualRegion]:
        regions: List[VisualRegion] = []
        try:
            found_tables = page.find_tables() or []
        except Exception:
            found_tables = []

        for idx, tbl in enumerate(found_tables, start=1):
            try:
                rows = tbl.extract() or []
            except Exception:
                rows = []
            md = format_markdown_table(rows)
            if not md:
                continue

            md, rep = apply_text_normalization(
                md,
                repair_bengali=repair_bengali,
                convert_bangla_digits=convert_bangla_digits,
            )
            x0, top, x1, bottom = getattr(tbl, "bbox", (0, 0, pw, ph))
            region_id = f"p{page_num}-tbl{idx}"
            regions.append(VisualRegion(
                region_id=region_id,
                region_type=VisualRegionType.TABLE.value,
                extraction_kind=VisualExtractionKind.VECTOR_TABLE.value,
                page_number=page_num,
                bbox=(int(x0), int(top), int(x1 - x0), int(bottom - top)),
                normalized_box=normalize_bbox(x0, top, x1, bottom, pw, ph),
                text=md,
                markdown=format_visual_region_markdown(page_num, region_id, "Visual Table", md),
                confidence=0.95,
                engine="pdfplumber_table",
                engine_version="0.11.9",
                is_inference=False,
                is_repaired=rep,
                source_asset_name=f"pdf:page_{page_num}:table_{idx}",
                metadata={"row_count": len(rows)},
            ))
        return regions

    @classmethod
    def _collect_pdf_visual_candidates(
        cls,
        page,
        pw: float,
        ph: float,
        table_bboxes: Optional[List[Tuple[float, float, float, float]]] = None,
    ) -> List[Dict[str, Any]]:
        """Collects embedded image boxes and clustered non-table vector graphic boxes."""
        candidates: List[Dict[str, Any]] = []
        tbl_boxes = table_bboxes or []

        def _inside_table(x0: float, top: float, x1: float, bottom: float) -> bool:
            for tx0, ttop, tx1, tbottom in tbl_boxes:
                if x0 >= (tx0 - 4.0) and top >= (ttop - 4.0) and x1 <= (tx1 + 4.0) and bottom <= (tbottom + 4.0):
                    return True
            return False

        # 1. Explicit embedded raster images inside PDF
        for idx, img_meta in enumerate(getattr(page, "images", []) or [], start=1):
            x0 = float(img_meta.get("x0", 0))
            top = float(img_meta.get("top", 0))
            x1 = float(img_meta.get("x1", 0))
            bottom = float(img_meta.get("bottom", 0))
            if (x1 - x0) >= cls.MIN_GRAPHIC_SIZE_PT and (bottom - top) >= cls.MIN_GRAPHIC_SIZE_PT:
                candidates.append({
                    "bbox_pt": (x0, top, x1, bottom),
                    "region_type": VisualRegionType.EMBEDDED_IMAGE.value,
                    "source_asset_name": f"pdf:image_{idx}",
                })

        # 2. Vector rects / curves indicative of charts or diagrams (excluding table grid borders)
        draw_boxes: List[Tuple[float, float, float, float]] = []
        for shape in (getattr(page, "rects", []) or []) + (getattr(page, "curves", []) or []):
            x0 = float(shape.get("x0", 0))
            top = float(shape.get("top", 0))
            x1 = float(shape.get("x1", 0))
            bottom = float(shape.get("bottom", 0))
            w = x1 - x0
            h = bottom - top
            is_page_frame = w > (0.95 * pw) and h > (0.95 * ph)
            if not is_page_frame and w >= 4.0 and h >= 4.0 and not _inside_table(x0, top, x1, bottom):
                draw_boxes.append((x0, top, x1, bottom))

        if len(draw_boxes) >= cls.MIN_VECTOR_PRIMITIVES:
            for c_idx, cluster in enumerate(_merge_boxes(draw_boxes, gap=16.0), start=1):
                cw = cluster[2] - cluster[0]
                ch = cluster[3] - cluster[1]
                if cw >= cls.MIN_GRAPHIC_SIZE_PT and ch >= cls.MIN_GRAPHIC_SIZE_PT:
                    candidates.append({
                        "bbox_pt": cluster,
                        "region_type": VisualRegionType.CHART.value,
                        "source_asset_name": f"pdf:vector_cluster_{c_idx}",
                    })

        return candidates

    @classmethod
    def extract_visuals_per_page(
        cls,
        file_path_or_bytes: Any,
        visual_provider: BaseVisualProvider,
        max_pages: int = 50,
        render_mixed_pages: bool = True,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
        provider_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[int, Dict[str, Any]]:
        results: Dict[int, Dict[str, Any]] = {}
        if not HAS_PDFPLUMBER:
            return results

        try:
            pdf_stream = (
                io.BytesIO(file_path_or_bytes)
                if isinstance(file_path_or_bytes, (bytes, bytearray))
                else file_path_or_bytes
            )
            with pdfplumber.open(pdf_stream) as pdf:
                total = min(len(pdf.pages), max_pages)
                for idx in range(total):
                    page_num = idx + 1
                    page = pdf.pages[idx]
                    pw = float(getattr(page, "width", 612.0) or 612.0)
                    ph = float(getattr(page, "height", 792.0) or 792.0)

                    page_regions: List[Dict[str, Any]] = []
                    metrics_list: List[Dict[str, Any]] = []

                    # 1. Deterministic PDF table extraction
                    tbl_regions = cls._detect_vector_table_regions(
                        page, page_num, pw, ph, repair_bengali, convert_bangla_digits
                    )
                    page_regions.extend(r.to_dict() for r in tbl_regions)
                    tbl_pt_bboxes = [
                        (r.bbox[0], r.bbox[1], r.bbox[0] + r.bbox[2], r.bbox[1] + r.bbox[3])
                        for r in tbl_regions
                    ]

                    # 2. Embedded raster images + vector chart clusters
                    candidates = cls._collect_pdf_visual_candidates(page, pw, ph, table_bboxes=tbl_pt_bboxes)
                    extracted_text_probe = (page.extract_text() or "").strip()
                    needs_full_page_visual = (len(extracted_text_probe) <= 20) or bool(candidates)

                    if needs_full_page_visual and render_mixed_pages and HAS_PYPDFIUM2:
                        raster_img = PDFPageRenderer.render_single_page(file_path_or_bytes, idx, dpi=300)
                        if raster_img is not None:
                            scale_x = raster_img.width / max(pw, 1.0)
                            scale_y = raster_img.height / max(ph, 1.0)

                            if candidates:
                                for cand in candidates[:6]:
                                    x0, top, x1, bottom = cand["bbox_pt"]
                                    crop = crop_image_safe(
                                        raster_img,
                                        x0 * scale_x,
                                        top * scale_y,
                                        x1 * scale_x,
                                        bottom * scale_y,
                                    )
                                    if crop is None:
                                        continue
                                    ctx = {
                                        **(provider_ctx or {}),
                                        "page_number": page_num,
                                        "region_type": cand["region_type"],
                                        "source_asset_name": cand["source_asset_name"],
                                        "parent_normalized_box": normalize_bbox(x0, top, x1, bottom, pw, ph),
                                    }
                                    vis_res = visual_provider.analyze_image(crop, context=ctx)
                                    page_regions.extend(vis_res.get("regions", []))
                                    if vis_res.get("metrics"):
                                        metrics_list.append(vis_res["metrics"])
                            elif len(extracted_text_probe) <= 20 and not tbl_regions:
                                # Pure scanned/image PDF page fallback visual analysis
                                ctx = {
                                    **(provider_ctx or {}),
                                    "page_number": page_num,
                                    "source_asset_name": f"pdf:page_{page_num}",
                                }
                                vis_res = visual_provider.analyze_image(raster_img, context=ctx)
                                page_regions.extend(vis_res.get("regions", []))
                                if vis_res.get("metrics"):
                                    metrics_list.append(vis_res["metrics"])

                    if page_regions or metrics_list:
                        results[page_num] = {
                            "regions": page_regions,
                            "metrics": metrics_list,
                        }
        except Exception as exc:
            logger.warning("PDFVisualProbe failed gracefully: %s", sanitize_sensitive_data(str(exc)))

        return results


class OfficeVisualProbe:
    """
    Extracts embedded OOXML charts (series + numeric categories) and media images
    from PPTX, DOCX, and XLSX ZIP packages without reimplementing text extractors.
    """
    IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp", ".bmp", ".gif")

    @classmethod
    def parse_ooxml_chart_xml(
        cls,
        xml_bytes: bytes,
        page_number: int,
        chart_path: str,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
    ) -> Optional[VisualRegion]:
        """Deterministically parses DrawingML <c:chartSpace> title, categories, and numeric values."""
        try:
            root = ET.fromstring(xml_bytes)
        except Exception:
            return None

        title_parts = []
        for elem in root.iter():
            if elem.tag.endswith("}title"):
                for tnode in elem.iter():
                    if (tnode.tag.endswith("}t") or tnode.tag.endswith("}v")) and tnode.text:
                        title_parts.append(tnode.text.strip())
                break
        chart_title = " ".join(title_parts).strip() or os.path.basename(chart_path)

        series_records: List[Tuple[str, List[str], List[str]]] = []
        for idx, ser in enumerate(root.iter(), start=1):
            if not ser.tag.endswith("}ser"):
                continue

            ser_name = f"Series {idx}"
            cats: List[str] = []
            vals: List[str] = []
            for child in ser:
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if ctag == "tx":
                    txt_nodes = [n.text.strip() for n in child.iter() if (n.tag.endswith("}t") or n.tag.endswith("}v")) and n.text]
                    if txt_nodes:
                        ser_name = " ".join(txt_nodes)
                elif ctag == "cat":
                    cats = [n.text.strip() for n in child.iter() if n.tag.endswith("}v") and n.text]
                elif ctag == "val":
                    vals = [n.text.strip() for n in child.iter() if n.tag.endswith("}v") and n.text]

            if vals or cats:
                series_records.append((ser_name, cats, vals))

        if not series_records and not title_parts:
            return None

        # Build Markdown table across series
        table_md = ""
        if series_records:
            max_pts = max(max(len(c), len(v)) for _, c, v in series_records)
            base_cats = next((c for _, c, _ in series_records if len(c) == max_pts), [])
            headers = ["Category"] + [name for name, _, _ in series_records]
            rows: List[List[str]] = [headers]
            for pt_idx in range(max_pts):
                cat_lbl = base_cats[pt_idx] if pt_idx < len(base_cats) else str(pt_idx + 1)
                row_vals = [val_list[pt_idx] if pt_idx < len(val_list) else "" for _, _, val_list in series_records]
                rows.append([cat_lbl] + row_vals)
            table_md = format_markdown_table(rows)

        norm_title, rep_t = apply_text_normalization(chart_title, repair_bengali, convert_bangla_digits)
        norm_tbl, rep_b = apply_text_normalization(table_md, repair_bengali, convert_bangla_digits)
        region_id = f"p{page_number}-chart-{os.path.splitext(os.path.basename(chart_path))[0]}"
        body_parts = [norm_tbl] if norm_tbl else [f"Chart title: {norm_title}"]
        markdown = format_visual_region_markdown(
            page_number,
            region_id,
            f"Embedded Chart: {norm_title}",
            "\n\n".join(body_parts),
        )

        return VisualRegion(
            region_id=region_id,
            region_type=VisualRegionType.CHART.value,
            extraction_kind=VisualExtractionKind.CHART_SERIES.value,
            page_number=page_number,
            bbox=(0, 0, 0, 0),
            normalized_box=[0, 0, 1000, 1000],
            text=markdown,
            markdown=markdown,
            confidence=0.98 if table_md else 0.85,
            engine="ooxml_chart_xml",
            engine_version="1.0",
            is_inference=False,
            is_repaired=(rep_t or rep_b),
            source_asset_name=chart_path,
            metadata={"chart_title": norm_title, "series_count": len(series_records)},
        )

    @classmethod
    def _analyze_media_asset(
        cls,
        zf: zipfile.ZipFile,
        asset_path: str,
        page_number: int,
        visual_provider: BaseVisualProvider,
        provider_ctx: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        if not asset_path.lower().endswith(cls.IMAGE_EXTENSIONS) or asset_path not in zf.namelist():
            return [], []
        img = _open_image_bytes_safe(zf.read(asset_path))
        if img is None:
            return [], []
        ctx = {
            **(provider_ctx or {}),
            "page_number": page_number,
            "region_type": VisualRegionType.EMBEDDED_IMAGE.value,
            "source_asset_name": asset_path,
        }
        res = visual_provider.analyze_image(img, context=ctx)
        metrics = [res["metrics"]] if res.get("metrics") else []
        return res.get("regions", []), metrics

    @classmethod
    def extract_pptx_visuals(
        cls,
        file_path_or_bytes: Any,
        visual_provider: BaseVisualProvider,
        max_assets: int = 25,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
        provider_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[int, Dict[str, Any]]:
        zf = _open_zip_safe(file_path_or_bytes)
        if zf is None:
            return {}

        results: Dict[int, Dict[str, Any]] = {}
        processed_assets = 0
        try:
            with zf:
                slides = PresentationExtractor._resolve_slide_order(zf)
                seen_slide_assets = set()
                for page_num, sname in enumerate(slides, start=1):
                    rels_path = f"{os.path.dirname(sname)}/_rels/{os.path.basename(sname)}.rels"
                    rels = PresentationExtractor._parse_rels(zf, rels_path)
                    page_regions: List[Dict[str, Any]] = []
                    metrics_list: List[Dict[str, Any]] = []

                    for rel in rels.values():
                        if processed_assets >= max_assets:
                            break
                        resolved = _resolve_zip_rel_path(sname, rel.get("target", ""))
                        if resolved in seen_slide_assets or resolved not in zf.namelist():
                            continue

                        if resolved.startswith("ppt/charts/") and resolved.endswith(".xml"):
                            seen_slide_assets.add(resolved)
                            processed_assets += 1
                            reg = cls.parse_ooxml_chart_xml(
                                zf.read(resolved), page_num, resolved, repair_bengali, convert_bangla_digits
                            )
                            if reg:
                                page_regions.append(reg.to_dict())
                        elif resolved.startswith("ppt/media/") and resolved.lower().endswith(cls.IMAGE_EXTENSIONS):
                            seen_slide_assets.add(resolved)
                            processed_assets += 1
                            regs, mets = cls._analyze_media_asset(zf, resolved, page_num, visual_provider, provider_ctx)
                            page_regions.extend(regs)
                            metrics_list.extend(mets)

                    if page_regions or metrics_list:
                        results[page_num] = {"regions": page_regions, "metrics": metrics_list}
        except Exception as exc:
            logger.warning("PPTX visual probe failed gracefully: %s", sanitize_sensitive_data(str(exc)))
        return results

    @classmethod
    def extract_docx_visuals(
        cls,
        file_path_or_bytes: Any,
        visual_provider: BaseVisualProvider,
        max_assets: int = 25,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
        provider_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[int, Dict[str, Any]]:
        zf = _open_zip_safe(file_path_or_bytes)
        if zf is None:
            return {}

        page_regions: List[Dict[str, Any]] = []
        metrics_list: List[Dict[str, Any]] = []
        processed = 0
        try:
            with zf:
                names = sorted(zf.namelist())
                for name in names:
                    if processed >= max_assets:
                        break
                    norm = name.replace("\\", "/")
                    if norm.startswith("word/charts/") and norm.endswith(".xml"):
                        processed += 1
                        reg = cls.parse_ooxml_chart_xml(
                            zf.read(name), 1, norm, repair_bengali, convert_bangla_digits
                        )
                        if reg:
                            page_regions.append(reg.to_dict())
                    elif norm.startswith("word/media/") and norm.lower().endswith(cls.IMAGE_EXTENSIONS):
                        processed += 1
                        regs, mets = cls._analyze_media_asset(zf, name, 1, visual_provider, provider_ctx)
                        page_regions.extend(regs)
                        metrics_list.extend(mets)
        except Exception as exc:
            logger.warning("DOCX visual probe failed gracefully: %s", sanitize_sensitive_data(str(exc)))

        return {1: {"regions": page_regions, "metrics": metrics_list}} if (page_regions or metrics_list) else {}

    @classmethod
    def extract_xlsx_visuals(
        cls,
        file_path_or_bytes: Any,
        visual_provider: BaseVisualProvider,
        max_assets: int = 25,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
        provider_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[int, Dict[str, Any]]:
        zf = _open_zip_safe(file_path_or_bytes)
        if zf is None:
            return {}

        results: Dict[int, Dict[str, Any]] = {}
        processed = 0
        try:
            with zf:
                sheet_targets: List[Tuple[int, str]] = []
                if "xl/workbook.xml" in zf.namelist() and "xl/_rels/workbook.xml.rels" in zf.namelist():
                    wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
                    wb_rels = PresentationExtractor._parse_rels(zf, "xl/_rels/workbook.xml.rels")
                    idx = 0
                    for elem in wb_root.iter():
                        if elem.tag.endswith("}sheet"):
                            idx += 1
                            rid = elem.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id") or elem.attrib.get("r:id")
                            if rid and rid in wb_rels:
                                s_target = _resolve_zip_rel_path("xl/workbook.xml", wb_rels[rid]["target"])
                                sheet_targets.append((idx, s_target))

                seen_assets = set()
                for page_num, s_path in sheet_targets:
                    s_rels_path = f"{os.path.dirname(s_path)}/_rels/{os.path.basename(s_path)}.rels"
                    s_rels = PresentationExtractor._parse_rels(zf, s_rels_path)
                    page_regions: List[Dict[str, Any]] = []
                    metrics_list: List[Dict[str, Any]] = []

                    for rel in s_rels.values():
                        if "drawing" not in rel.get("type", "").lower():
                            continue
                        drawing_path = _resolve_zip_rel_path(s_path, rel.get("target", ""))
                        d_rels_path = f"{os.path.dirname(drawing_path)}/_rels/{os.path.basename(drawing_path)}.rels"
                        d_rels = PresentationExtractor._parse_rels(zf, d_rels_path)

                        for d_rel in d_rels.values():
                            if processed >= max_assets:
                                break
                            asset_path = _resolve_zip_rel_path(drawing_path, d_rel.get("target", ""))
                            if asset_path in seen_assets or asset_path not in zf.namelist():
                                continue
                            if asset_path.startswith("xl/charts/") and asset_path.endswith(".xml"):
                                seen_assets.add(asset_path)
                                processed += 1
                                reg = cls.parse_ooxml_chart_xml(
                                    zf.read(asset_path), page_num, asset_path, repair_bengali, convert_bangla_digits
                                )
                                if reg:
                                    page_regions.append(reg.to_dict())
                            elif asset_path.startswith("xl/media/") and asset_path.lower().endswith(cls.IMAGE_EXTENSIONS):
                                seen_assets.add(asset_path)
                                processed += 1
                                regs, mets = cls._analyze_media_asset(zf, asset_path, page_num, visual_provider, provider_ctx)
                                page_regions.extend(regs)
                                metrics_list.extend(mets)

                    if page_regions or metrics_list:
                        results[page_num] = {"regions": page_regions, "metrics": metrics_list}
        except Exception as exc:
            logger.warning("XLSX visual probe failed gracefully: %s", sanitize_sensitive_data(str(exc)))
        return results


class HTMLVisualProbe:
    """
    Extracts structured SVG labels/titles and inline data-URI/<img> metadata that
    ``HTMLExtractor`` strips during text sanitization.
    """
    MAX_INLINE_IMAGE_BYTES = 5 * 1024 * 1024

    @classmethod
    def extract_visuals(
        cls,
        file_path_or_bytes: Any,
        visual_provider: BaseVisualProvider,
        max_assets: int = 15,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
        provider_ctx: Optional[Dict[str, Any]] = None,
    ) -> Dict[int, Dict[str, Any]]:
        if not HAS_BS4:
            return {}

        if isinstance(file_path_or_bytes, (bytes, bytearray)):
            raw_html = file_path_or_bytes.decode("utf-8", errors="replace")
        else:
            with open(file_path_or_bytes, "r", encoding="utf-8", errors="replace") as fh:
                raw_html = fh.read()

        soup = BeautifulSoup(raw_html, "html.parser")
        page_regions: List[Dict[str, Any]] = []
        metrics_list: List[Dict[str, Any]] = []
        count = 0

        # 1. Semantic <svg> tags (titles, descriptions, text nodes)
        for idx, svg in enumerate(soup.find_all("svg"), start=1):
            if count >= max_assets:
                break
            count += 1
            title_tag = svg.find("title")
            desc_tag = svg.find("desc")
            text_nodes = [t.get_text(" ", strip=True) for t in svg.find_all(["text", "tspan"]) if t.get_text(strip=True)]
            parts = []
            if title_tag and title_tag.get_text(strip=True):
                parts.append(f"Title: {title_tag.get_text(strip=True)}")
            if desc_tag and desc_tag.get_text(strip=True):
                parts.append(f"Description: {desc_tag.get_text(strip=True)}")
            if text_nodes:
                parts.append("Labels: " + " | ".join(dict.fromkeys(text_nodes)))
            svg_text, rep = apply_text_normalization(
                "\n".join(parts), repair_bengali, convert_bangla_digits
            )
            if not svg_text:
                continue

            region_id = f"p1-svg{idx}"
            page_regions.append(VisualRegion(
                region_id=region_id,
                region_type=VisualRegionType.SVG_GRAPHIC.value,
                extraction_kind=VisualExtractionKind.EMBEDDED_ASSET.value,
                page_number=1,
                text=svg_text,
                markdown=format_visual_region_markdown(1, region_id, "Embedded SVG", svg_text),
                confidence=0.92,
                engine="bs4_svg_probe",
                engine_version="1.0",
                is_inference=False,
                is_repaired=rep,
                source_asset_name=f"html:svg_{idx}",
            ).to_dict())

        # 2. <img> alt/title metadata + safe base64 inline images
        for idx, img_tag in enumerate(soup.find_all("img"), start=1):
            if count >= max_assets:
                break
            src = str(img_tag.get("src") or "").strip()
            alt = str(img_tag.get("alt") or img_tag.get("title") or "").strip()

            if src.startswith("data:image/") and ";base64," in src:
                b64_payload = re.sub(r"\s+", "", src.split(";base64,", 1)[1])
                try:
                    raw_img = base64.b64decode(b64_payload, validate=True)
                except Exception:
                    raw_img = b""
                if 0 < len(raw_img) <= cls.MAX_INLINE_IMAGE_BYTES:
                    pil_img = _open_image_bytes_safe(raw_img)
                    if pil_img is not None:
                        count += 1
                        ctx = {
                            **(provider_ctx or {}),
                            "page_number": 1,
                            "region_type": VisualRegionType.EMBEDDED_IMAGE.value,
                            "source_asset_name": f"html:inline_img_{idx}",
                        }
                        vis_res = visual_provider.analyze_image(pil_img, context=ctx)
                        page_regions.extend(vis_res.get("regions", []))
                        if vis_res.get("metrics"):
                            metrics_list.append(vis_res["metrics"])
                        continue

            if alt:
                count += 1
                norm_alt, rep = apply_text_normalization(alt, repair_bengali, convert_bangla_digits)
                region_id = f"p1-img{idx}"
                page_regions.append(VisualRegion(
                    region_id=region_id,
                    region_type=VisualRegionType.EMBEDDED_IMAGE.value,
                    extraction_kind=VisualExtractionKind.EMBEDDED_ASSET.value,
                    page_number=1,
                    text=norm_alt,
                    markdown=format_visual_region_markdown(1, region_id, "HTML Image Alt", norm_alt),
                    confidence=0.90,
                    engine="bs4_img_alt",
                    engine_version="1.0",
                    is_inference=False,
                    is_repaired=rep,
                    source_asset_name=src[:160] or f"html:img_{idx}",
                ).to_dict())

        return {1: {"regions": page_regions, "metrics": metrics_list}} if (page_regions or metrics_list) else {}


# ==============================================================================
# ISOLATED ORCHESTRATION FACADE (REUSES UNIFIED EXTRACTOR & CHUNKER)
# ==============================================================================
class VisualDocumentExtractor:
    """
    Isolated Visual Extraction entry point inside ``apps.ingestion.pipeline``.

    Reuses:
    - ``UnifiedDocumentExtractor`` for canonical text/OCR & word ``bounding_boxes``
    - ``StorageSecurityService`` when passed an uploaded Django ``File`` object
    - ``StructureAwareChunker`` via ``chunk_visual_pages`` helper
    - ``ExecutionMode`` / ``is_remote_model_allowed`` / ``DataResidencyService`` when
      evaluating sovereignty-gated remote visual providers
    """

    def __init__(
        self,
        ocr_provider: Optional[BaseOCRProvider] = None,
        visual_provider: Optional[BaseVisualProvider] = None,
        enable_baseline_text: bool = True,
        render_mixed_pdf_pages: bool = True,
        max_pages: int = 50,
        max_assets: int = 25,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
        use_pymupdf: bool = False,
        pdf_visual_adapter: Optional[Any] = None,
        chart_extractor: Optional[Any] = None,
        form_extractor: Optional[Any] = None,
    ):
        self.ocr_provider = ocr_provider or TesseractOCRProvider()
        self.visual_provider = visual_provider or LocalDeterministicVisualProvider(
            ocr_provider=self.ocr_provider,
            repair_bengali=repair_bengali,
            convert_bangla_digits=convert_bangla_digits,
        )
        self.chart_extractor = chart_extractor
        self.form_extractor = form_extractor
        if pdf_visual_adapter is None and use_pymupdf:
            from .pdf_visual import PDFSafetyLimits, PyMuPDFVisualPDFAdapter

            pdf_visual_adapter = PyMuPDFVisualPDFAdapter(
                ocr_provider=self.ocr_provider,
                visual_provider=self.visual_provider,
                chart_extractor=chart_extractor,
                form_extractor=form_extractor,
                render_mixed_regions_on_demand=render_mixed_pdf_pages,
                repair_bengali=repair_bengali,
                convert_bangla_digits=convert_bangla_digits,
                limits=PDFSafetyLimits(max_pages=max_pages),
            )
        self.pdf_visual_adapter = pdf_visual_adapter
        self.baseline_extractor = UnifiedDocumentExtractor(ocr_provider=self.ocr_provider)
        self.enable_baseline_text = enable_baseline_text
        self.render_mixed_pdf_pages = render_mixed_pdf_pages
        self.max_pages = max_pages
        self.max_assets = max_assets
        self.repair_bengali = repair_bengali
        self.convert_bangla_digits = convert_bangla_digits
        self.use_pymupdf = use_pymupdf or (pdf_visual_adapter is not None)

    @classmethod
    def with_chart_extractor(
        cls,
        ocr_provider: Optional[BaseOCRProvider] = None,
        chart_config: Optional[Any] = None,
        use_pymupdf: bool = True,
        **kwargs,
    ) -> "VisualDocumentExtractor":
        """
        Constructs a VisualDocumentExtractor with deterministic PyMuPDF + OpenCV +
        Tesseract chart extraction enabled on PDFs and standalone chart images.
        """
        from .charts import PyMuPDFOpenCVChartExtractor

        eff_ocr = ocr_provider or TesseractOCRProvider()
        repair_bengali = bool(kwargs.get("repair_bengali", True))
        convert_bangla = bool(kwargs.get("convert_bangla_digits", False))
        chart_extractor = kwargs.pop("chart_extractor", None) or PyMuPDFOpenCVChartExtractor(
            config=chart_config,
            ocr_provider=eff_ocr,
            repair_bengali=repair_bengali,
            convert_bangla_digits=convert_bangla,
        )
        return cls(
            ocr_provider=eff_ocr,
            use_pymupdf=use_pymupdf,
            chart_extractor=chart_extractor,
            **kwargs,
        )

    @classmethod
    def with_form_extractor(
        cls,
        ocr_provider: Optional[BaseOCRProvider] = None,
        form_config: Optional[Any] = None,
        use_pymupdf: bool = True,
        **kwargs,
    ) -> "VisualDocumentExtractor":
        """
        Constructs a VisualDocumentExtractor with deterministic PyMuPDF + OpenCV +
        Tesseract form extraction enabled on PDFs and standalone form images.
        """
        from .forms import FormKVExtractor

        eff_ocr = ocr_provider or TesseractOCRProvider()
        repair_bengali = bool(kwargs.get("repair_bengali", True))
        convert_bangla = bool(kwargs.get("convert_bangla_digits", False))
        form_extractor = kwargs.pop("form_extractor", None) or FormKVExtractor(
            config=form_config,
            ocr_provider=eff_ocr,
            repair_bengali=repair_bengali,
            convert_bangla_digits=convert_bangla,
        )
        return cls(
            ocr_provider=eff_ocr,
            use_pymupdf=use_pymupdf,
            form_extractor=form_extractor,
            **kwargs,
        )

    @classmethod
    def with_pp_doclayout_s(
        cls,
        ocr_provider: Optional[BaseOCRProvider] = None,
        layout_config: Optional[Any] = None,
        use_pymupdf: bool = True,
        **kwargs,
    ) -> "VisualDocumentExtractor":
        """Constructs a VisualDocumentExtractor using optional CPU PP-DocLayout-S layout detection."""
        from .layout import PPDocLayoutSProvider

        eff_ocr = ocr_provider or TesseractOCRProvider()
        repair_bengali = bool(kwargs.get("repair_bengali", True))
        convert_bangla = bool(kwargs.get("convert_bangla_digits", False))
        table_extractor = kwargs.pop("table_extractor", None)
        chart_extractor = kwargs.pop("chart_extractor", None)
        form_extractor = kwargs.pop("form_extractor", None)
        layout_prov = PPDocLayoutSProvider(
            config=layout_config,
            ocr_provider=eff_ocr,
            table_extractor=table_extractor,
            chart_extractor=chart_extractor,
            form_extractor=form_extractor,
            repair_bengali=repair_bengali,
            convert_bangla_digits=convert_bangla,
        )
        pdf_adapter = None
        if use_pymupdf:
            from .pdf_visual import PDFSafetyLimits, PyMuPDFVisualPDFAdapter

            pdf_adapter = PyMuPDFVisualPDFAdapter(
                ocr_provider=eff_ocr,
                visual_provider=layout_prov,
                layout_provider=layout_prov,
                table_extractor=table_extractor,
                chart_extractor=chart_extractor,
                form_extractor=form_extractor,
                render_mixed_regions_on_demand=bool(kwargs.get("render_mixed_pdf_pages", True)),
                repair_bengali=repair_bengali,
                convert_bangla_digits=convert_bangla,
                limits=PDFSafetyLimits(max_pages=int(kwargs.get("max_pages", 50))),
            )
        return cls(
            ocr_provider=eff_ocr,
            visual_provider=layout_prov,
            use_pymupdf=use_pymupdf,
            pdf_visual_adapter=pdf_adapter,
            chart_extractor=chart_extractor,
            form_extractor=form_extractor,
            **kwargs,
        )

    @classmethod
    def with_pp_doclayout_s_and_slanet_plus(
        cls,
        ocr_provider: Optional[BaseOCRProvider] = None,
        layout_config: Optional[Any] = None,
        slanet_config: Optional[Any] = None,
        use_pymupdf: bool = True,
        chart_config: Optional[Any] = None,
        enable_charts: bool = False,
        form_config: Optional[Any] = None,
        enable_forms: bool = False,
        **kwargs,
    ) -> "VisualDocumentExtractor":
        """
        Constructs a VisualDocumentExtractor wiring PP-DocLayout-S for layout
        detection, SLANet_plus for structure-validated table extraction, and
        optionally PyMuPDFOpenCVChartExtractor / FormKVExtractor.
        """
        from .tables import SLANetPlusTableExtractor

        eff_ocr = ocr_provider or TesseractOCRProvider()
        repair_bengali = bool(kwargs.get("repair_bengali", True))
        convert_bangla = bool(kwargs.get("convert_bangla_digits", False))
        table_extractor = SLANetPlusTableExtractor(
            config=slanet_config,
            ocr_provider=eff_ocr,
            repair_bengali=repair_bengali,
            convert_bangla_digits=convert_bangla,
        )
        chart_extractor = kwargs.pop("chart_extractor", None)
        if chart_extractor is None and (enable_charts or chart_config is not None):
            from .charts import PyMuPDFOpenCVChartExtractor

            chart_extractor = PyMuPDFOpenCVChartExtractor(
                config=chart_config,
                ocr_provider=eff_ocr,
                repair_bengali=repair_bengali,
                convert_bangla_digits=convert_bangla,
            )
        form_extractor = kwargs.pop("form_extractor", None)
        if form_extractor is None and (enable_forms or form_config is not None):
            from .forms import FormKVExtractor

            form_extractor = FormKVExtractor(
                config=form_config,
                ocr_provider=eff_ocr,
                repair_bengali=repair_bengali,
                convert_bangla_digits=convert_bangla,
            )
        return cls.with_pp_doclayout_s(
            ocr_provider=eff_ocr,
            layout_config=layout_config,
            use_pymupdf=use_pymupdf,
            table_extractor=table_extractor,
            chart_extractor=chart_extractor,
            form_extractor=form_extractor,
            **kwargs,
        )

    @staticmethod
    def _infer_doc_type_and_name(file_obj_or_bytes: Any, doc_type: str, filename: str) -> Tuple[str, str]:
        inferred_name = filename or str(getattr(file_obj_or_bytes, "name", "") or (file_obj_or_bytes if isinstance(file_obj_or_bytes, str) else ""))
        ext = os.path.splitext(inferred_name.lower())[1] if inferred_name else ""
        inferred_type = doc_type or ALLOWED_EXTENSIONS.get(ext, "")
        return inferred_type, inferred_name

    def extract_file_object(
        self,
        file_obj,
        workspace=None,
        organization=None,
        policy_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Validates a Django UploadedFile / File via ``StorageSecurityService`` before
        running visual extraction. Returns both validation metadata and page list.
        """
        security_meta = StorageSecurityService.inspect_and_validate(file_obj)
        file_obj.seek(0)
        file_bytes = file_obj.read()
        file_obj.seek(0)

        pages = self.extract_document(
            file_path_or_bytes=file_bytes,
            doc_type=security_meta["document_type"],
            filename=getattr(file_obj, "name", ""),
            workspace=workspace,
            organization=organization,
            policy_context=policy_context,
        )
        return {
            "validation": security_meta,
            "pages": pages,
        }

    def _extract_single_image_visuals(
        self,
        file_path_or_bytes: Any,
        provider_ctx: Dict[str, Any],
    ) -> Dict[int, Dict[str, Any]]:
        try:
            if isinstance(file_path_or_bytes, (bytes, bytearray)):
                img = _open_image_bytes_safe(bytes(file_path_or_bytes))
            else:
                with Image.open(file_path_or_bytes) as opened:
                    img = opened.copy()
        except Exception:
            img = None

        if img is None:
            return {}

        try:
            vis_res = self.visual_provider.analyze_image(img, context={**provider_ctx, "page_number": 1})
            regions = list(vis_res.get("regions", []) or [])
            metrics = [vis_res["metrics"]] if vis_res.get("metrics") else []

            def _drop_overlapping_regions(
                current: List[Dict[str, Any]],
                target_boxes: Sequence[Tuple[float, float, float, float]],
                drop_types: Tuple[str, ...],
            ) -> List[Dict[str, Any]]:
                out_list: List[Dict[str, Any]] = []
                for r in current:
                    rb = r.get("bbox") or []
                    if len(rb) >= 4 and r.get("region_type") in drop_types:
                        rx0, ry0 = float(rb[0]), float(rb[1])
                        rx1, ry1 = rx0 + float(rb[2]), ry0 + float(rb[3])
                        r_area = max(1.0, (rx1 - rx0) * (ry1 - ry0))
                        if any(
                            (
                                max(0.0, min(rx1, bx1) - max(rx0, bx0))
                                * max(0.0, min(ry1, by1) - max(ry0, by0))
                            )
                            / min(r_area, max(1.0, (bx1 - bx0) * (by1 - by0)))
                            >= 0.45
                            for bx0, by0, bx1, by1 in target_boxes
                        ):
                            continue
                    out_list.append(r)
                return out_list

            if self.chart_extractor is not None and not any(
                r.get("region_type") == VisualRegionType.CHART.value for r in regions
            ):
                from .charts import detect_chart_regions_opencv, is_likely_chart_raster_opencv

                cv_boxes = list(detect_chart_regions_opencv(img))
                if not cv_boxes and (
                    is_likely_chart_raster_opencv(img) or bool(provider_ctx.get("assume_chart_image"))
                ):
                    cv_boxes = [(0.0, 0.0, float(img.width), float(img.height))]

                if cv_boxes:
                    regions = _drop_overlapping_regions(
                        regions,
                        cv_boxes,
                        (
                            VisualRegionType.IMAGE.value,
                            VisualRegionType.FIGURE.value,
                            VisualRegionType.UNKNOWN.value,
                        ),
                    )
                    for c_idx, cbox in enumerate(cv_boxes, start=1):
                        chart_prov = self.chart_extractor.extract_chart_region(
                            page_image=img,
                            chart_box=cbox,
                            bbox_format="pixel",
                            page_number=1,
                            page_width=float(img.width),
                            page_height=float(img.height),
                            source_rotation=0,
                            coords_in_unrotated_space=False,
                            region_id=f"p1-chart{c_idx}",
                            layout_label="chart",
                            source_asset_name=str(
                                provider_ctx.get("source_asset_name") or f"image:chart_{c_idx}"
                            ),
                        )
                        regions.append(chart_prov)

            if self.form_extractor is not None and not any(
                r.get("region_type") == VisualRegionType.FORM_KV.value
                and bool((r.get("metadata") or {}).get("form"))
                for r in regions
            ):
                from .forms import detect_form_regions_opencv, is_likely_form_raster_opencv

                ocr_hint = "\n".join(str(r.get("text") or "") for r in regions if r.get("text"))
                fm_boxes = list(detect_form_regions_opencv(img, ocr_text_hint=ocr_hint))
                if not fm_boxes and (
                    is_likely_form_raster_opencv(img, ocr_text_hint=ocr_hint)
                    or bool(provider_ctx.get("assume_form_image"))
                ):
                    fm_boxes = [(0.0, 0.0, float(img.width), float(img.height))]

                if fm_boxes:
                    regions = _drop_overlapping_regions(
                        regions,
                        fm_boxes,
                        (
                            VisualRegionType.FORM_KV.value,
                            VisualRegionType.SIGNATURE.value,
                            VisualRegionType.IMAGE.value,
                            VisualRegionType.FIGURE.value,
                            VisualRegionType.UNKNOWN.value,
                        ),
                    )
                    for f_idx, fbox in enumerate(fm_boxes, start=1):
                        form_prov = self.form_extractor.extract_form_region(
                            page_image=img,
                            form_box=fbox,
                            bbox_format="pixel",
                            page_number=1,
                            page_width=float(img.width),
                            page_height=float(img.height),
                            source_rotation=0,
                            coords_in_unrotated_space=False,
                            region_id=f"p1-form{f_idx}",
                            layout_label="form",
                            source_asset_name=str(
                                provider_ctx.get("source_asset_name") or f"image:form_{f_idx}"
                            ),
                        )
                        regions.append(form_prov)

            return {
                1: {
                    "regions": regions,
                    "metrics": metrics,
                }
            }
        finally:
            try:
                img.close()
            except Exception:
                pass

    def extract_document(
        self,
        file_path_or_bytes: Any,
        doc_type: str = "",
        filename: str = "",
        workspace=None,
        organization=None,
        policy_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        t0 = time.time()
        eff_type, eff_name = self._infer_doc_type_and_name(file_path_or_bytes, doc_type, filename)
        ext = os.path.splitext(eff_name.lower())[1] if eff_name else ""

        # Materialize stream objects into bytes once so baseline + visual probes can share safely
        payload = file_path_or_bytes
        if not isinstance(payload, (str, bytes, bytearray, os.PathLike)) and hasattr(payload, "read"):
            if hasattr(payload, "seek"):
                payload.seek(0)
            payload = payload.read()

        provider_ctx = {
            "workspace": workspace,
            "organization": organization,
            "policy_context": policy_context or {},
            "execution_mode": (policy_context or {}).get("execution_mode"),
            "filename": eff_name,
        }

        if (eff_type == "pdf" or ext == ".pdf") and self.pdf_visual_adapter is not None:
            return self.pdf_visual_adapter.process_pdf(
                payload,
                max_pages=self.max_pages,
                policy_context=policy_context,
            )

        # 1. Baseline canonical page stream (reusing UnifiedDocumentExtractor)
        baseline_pages: List[Dict[str, Any]] = []
        if self.enable_baseline_text:
            baseline_pages = self.baseline_extractor.extract_document(
                file_path_or_bytes=payload,
                doc_type=eff_type,
                filename=eff_name,
            )

        # 2. Visual extraction per format
        visual_by_page: Dict[int, Dict[str, Any]] = {}
        if eff_type == "pdf" or ext == ".pdf":
            visual_by_page = PDFVisualProbe.extract_visuals_per_page(
                file_path_or_bytes=payload,
                visual_provider=self.visual_provider,
                max_pages=self.max_pages,
                render_mixed_pages=self.render_mixed_pdf_pages,
                repair_bengali=self.repair_bengali,
                convert_bangla_digits=self.convert_bangla_digits,
                provider_ctx=provider_ctx,
            )
        elif eff_type == "image" or ext in (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp"):
            visual_by_page = self._extract_single_image_visuals(payload, provider_ctx)
        elif eff_type == "presentation" or ext in (".pptx", ".ppt"):
            visual_by_page = OfficeVisualProbe.extract_pptx_visuals(
                file_path_or_bytes=payload,
                visual_provider=self.visual_provider,
                max_assets=self.max_assets,
                repair_bengali=self.repair_bengali,
                convert_bangla_digits=self.convert_bangla_digits,
                provider_ctx=provider_ctx,
            )
        elif eff_type == "docx" or ext == ".docx":
            visual_by_page = OfficeVisualProbe.extract_docx_visuals(
                file_path_or_bytes=payload,
                visual_provider=self.visual_provider,
                max_assets=self.max_assets,
                repair_bengali=self.repair_bengali,
                convert_bangla_digits=self.convert_bangla_digits,
                provider_ctx=provider_ctx,
            )
        elif eff_type == "spreadsheet" or ext in (".xlsx", ".xls"):
            visual_by_page = OfficeVisualProbe.extract_xlsx_visuals(
                file_path_or_bytes=payload,
                visual_provider=self.visual_provider,
                max_assets=self.max_assets,
                repair_bengali=self.repair_bengali,
                convert_bangla_digits=self.convert_bangla_digits,
                provider_ctx=provider_ctx,
            )
        elif ext in (".html", ".htm"):
            visual_by_page = HTMLVisualProbe.extract_visuals(
                file_path_or_bytes=payload,
                visual_provider=self.visual_provider,
                max_assets=self.max_assets,
                repair_bengali=self.repair_bengali,
                convert_bangla_digits=self.convert_bangla_digits,
                provider_ctx=provider_ctx,
            )

        # 3. Synthesize page records preserving word bounding_boxes untouched
        elapsed_ms = round((time.time() - t0) * 1000.0, 2)
        if not baseline_pages and not visual_by_page:
            return []

        pages_map: Dict[int, Dict[str, Any]] = {}
        for p in baseline_pages:
            p_num = int(p.get("page_number", 1))
            pages_map[p_num] = {**p, "bounding_boxes": list(p.get("bounding_boxes", []))}

        for p_num, vis_bundle in visual_by_page.items():
            if p_num not in pages_map:
                pages_map[p_num] = {
                    "page_number": p_num,
                    "text": "",
                    "confidence": 0.0,
                    "words_count": 0,
                    "width": 612.0,
                    "height": 792.0,
                    "extraction_type": "visual_extract",
                    "engine": self.visual_provider.provider_name,
                    "engine_version": self.visual_provider.engine_version,
                    "is_repaired": False,
                    "bounding_boxes": [],
                }

        merged_pages: List[Dict[str, Any]] = []
        for p_num in sorted(pages_map.keys()):
            page = pages_map[p_num]
            vis_bundle = visual_by_page.get(p_num, {})
            regions: List[Dict[str, Any]] = vis_bundle.get("regions", [])
            metrics: List[Dict[str, Any]] = vis_bundle.get("metrics", [])

            base_text = str(page.get("text", "") or "").strip()
            # Avoid injecting placeholder OCR warning banners as facts when visual regions exist
            if base_text.startswith("[OCR Engine Optional:") and regions:
                base_text = ""

            vis_markdown_blocks = [r["markdown"] for r in regions if r.get("markdown")]
            if vis_markdown_blocks:
                vis_section = "\n\n".join(vis_markdown_blocks)
                merged_text = f"{base_text}\n\n{vis_section}".strip() if base_text else vis_section
            else:
                merged_text = base_text

            vis_confs = [float(r.get("confidence", 0.0)) for r in regions]
            avg_vis_conf = round(sum(vis_confs) / len(vis_confs), 4) if vis_confs else 0.0
            inference_count = sum(1 for r in regions if r.get("is_inference"))
            engines_used = sorted({str(r.get("engine", "")) for r in regions if r.get("engine")})

            page["text"] = merged_text
            page["words_count"] = len(merged_text.split())
            page["is_repaired"] = bool(page.get("is_repaired")) or any(bool(r.get("is_repaired")) for r in regions)
            # Only fill page confidence from visual analysis if baseline produced no usable text/confidence
            if not base_text and vis_confs:
                page["confidence"] = avg_vis_conf
                page["needs_review"] = page.get("needs_review", False) or (avg_vis_conf < 0.70)

            for r in regions:
                rmeta = r.get("metadata") or {}
                rval = rmeta.get("table_validation") or {}
                rcval = rmeta.get("chart_validation") or {}
                rfval = rmeta.get("form_validation") or {}
                if (
                    rmeta.get("needs_review")
                    or rmeta.get("review_required")
                    or rval.get("needs_review")
                    or rcval.get("needs_review")
                    or rcval.get("review_required")
                    or rfval.get("needs_review")
                    or rfval.get("review_required")
                ):
                    page["needs_review"] = True
                    if (
                        rmeta.get("review_required")
                        or rcval.get("review_required")
                        or rfval.get("review_required")
                    ):
                        page["review_required"] = True

            page["visual_regions"] = regions
            page["visual_metadata"] = {
                "has_visual_content": bool(regions),
                "visual_region_count": len(regions),
                "visual_confidence": avg_vis_conf,
                "visual_engines": engines_used,
                "visual_inference_count": inference_count,
                "visual_timings_ms": elapsed_ms,
                "provider_metrics": metrics,
            }
            merged_pages.append(page)

        if len(merged_pages) >= 2 and any(
            r.get("region_type") == VisualRegionType.TABLE.value
            for p in merged_pages
            for r in (p.get("visual_regions") or [])
        ):
            from .tables import link_multipage_tables

            link_multipage_tables(merged_pages)

        return merged_pages

    @staticmethod
    def chunk_visual_pages(
        doc_id: str,
        doc_title: str,
        org_name: str,
        ws_name: str,
        authority_rank: int,
        pages_data: List[Dict[str, Any]],
        document_code: str = "",
        status: str = "ready",
    ) -> List[Dict[str, Any]]:
        """
        Delegates chunking to ``StructureAwareChunker.chunk_document_pages`` and annotates
        chunks whose page contains ``visual_regions`` without modifying ``chunking.py``.
        """
        chunks = StructureAwareChunker.chunk_document_pages(
            doc_id=doc_id,
            doc_title=doc_title,
            org_name=org_name,
            ws_name=ws_name,
            authority_rank=authority_rank,
            pages_data=pages_data,
            document_code=document_code,
            status=status,
        )

        regions_by_page = {
            int(p.get("page_number", 1)): p.get("visual_regions", [])
            for p in pages_data
            if p.get("visual_regions")
        }
        for chunk in chunks:
            p_num = int(chunk.get("page_number", 1))
            page_regions = regions_by_page.get(p_num, [])
            if not page_regions:
                continue

            chunk_text = chunk.get("text", "")
            haystack = f"{chunk.get('heading_path', '')}\n{chunk_text}"
            matched = [
                r for r in page_regions
                if r.get("region_id") and r["region_id"] in haystack
            ]
            if matched or "Visual Evidence" in chunk.get("heading_path", ""):
                target_regions = matched or page_regions
                meta = dict(chunk.get("metadata") or {})
                meta["has_visual_evidence"] = True
                meta["visual_region_ids"] = [r["region_id"] for r in target_regions]
                meta["visual_region_types"] = sorted({r.get("region_type", "") for r in target_regions})
                meta["visual_extraction_kinds"] = sorted({r.get("extraction_kind", "") for r in target_regions})
                meta["contains_visual_inference"] = any(bool(r.get("is_inference")) for r in target_regions)
                chunk["metadata"] = meta

        return chunks
