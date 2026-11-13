"""
PyMuPDF + Tesseract OCR PDF Integration Layer for LORE Visual Extraction.

Extends LORE's existing ingestion pipeline without replacing ``OCRRouter`` or
altering the canonical ``DocumentPage`` / ``UnifiedDocumentExtractor`` output
contract:
    - Uses PyMuPDF (``pymupdf`` / ``fitz``) for single-pass PDF page geometry,
      rotation transforms, table/image/drawing inspection, and on-demand page or
      selected-region rasterization.
    - Prefers LORE's existing native text extraction (``DigitalPDFExtractor`` /
      PyMuPDF native text stream with existing Bengali visual-order repair)
      before triggering OCR.
    - Delegates scanned and selected mixed-content region OCR to the existing
      ``TesseractOCRProvider`` (or injected ``BaseOCRProvider``), preserving
      original language config (``ben+eng`` / ``eng``), confidence, engine,
      version, status, and warnings.
    - Enforces page-at-a-time processing with explicit bitmap/image memory
      cleanup, safety guards for encrypted/malformed/empty/oversized PDFs, and
      graceful fallback to ``OCRRouter`` when PyMuPDF is unavailable.
"""

from __future__ import annotations

import gc
import io
import logging
import os
import time
from contextlib import nullcontext
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, cast

from PIL import Image

from apps.governance.modes import sanitize_sensitive_data
from apps.sources.services import MAX_FILE_SIZE_BYTES

from .contracts import (
    VISUAL_INTEGRATION_CONTRACT_VERSION,
    VisualFallbackReason,
    VisualPipelineIntegrationAdapter,
    build_visual_region_provenance,
    rect_to_normalized_box,
)
from .ocr import (
    HAS_PDFPLUMBER,
    BaseOCRProvider,
    DigitalPDFExtractor,
    OCRRouter,
    PDFPageRenderer,
    TesseractOCRProvider,
    bangla_to_arabic_digits,
    is_visual_encoded_document,
    repair_visual_bengali_document,
)
from .visual import (
    VisualExtractionKind,
    VisualRegionType,
    _merge_boxes,
    _open_image_bytes_safe,
    _pad_for_ocr_if_needed,
    apply_text_normalization,
    format_markdown_table,
    format_visual_region_markdown,
)

if HAS_PDFPLUMBER:
    import pdfplumber

try:
    import pymupdf  # Prefer modern import to avoid PyMuPDF 2.x fitz FutureWarning

    HAS_PYMUPDF = True
    PYMUPDF_VERSION = str(getattr(pymupdf, "__version__", getattr(pymupdf, "VersionBind", "unknown")))
except ImportError:
    try:
        import fitz as pymupdf  # Fallback for legacy PyMuPDF 1.x

        HAS_PYMUPDF = True
        PYMUPDF_VERSION = str(getattr(pymupdf, "__version__", getattr(pymupdf, "VersionBind", "unknown")))
    except ImportError:
        pymupdf = None  # type: ignore[assignment]
        HAS_PYMUPDF = False
        PYMUPDF_VERSION = "unavailable"

logger = logging.getLogger(__name__)


class PDFPageClassification(str, Enum):
    """Per-page content routing classification."""

    SEARCHABLE = "searchable"
    SCANNED = "scanned"
    MIXED_CONTENT = "mixed_content"
    EMPTY = "empty"
    ENCRYPTED = "encrypted"
    MALFORMED = "malformed"
    OVERSIZED = "oversized"


@dataclass
class PDFSafetyLimits:
    """Safety and memory boundaries for single-page PDF processing."""

    max_pages: int = 50
    max_file_bytes: int = MAX_FILE_SIZE_BYTES
    dpi: Optional[int] = None
    max_render_pixels: Optional[int] = None
    min_graphic_pt: float = 24.0
    min_vector_primitives: int = 4
    max_regions_per_page: int = 8
    digital_text_threshold_chars: int = 20

    def __post_init__(self) -> None:
        from .runtime import get_configured_max_render_pixels, get_configured_visual_dpi

        if self.dpi is None:
            self.dpi = get_configured_visual_dpi(default=PDFPageRenderer.DEFAULT_DPI)
        else:
            self.dpi = max(72, min(600, self.dpi))
        if self.max_render_pixels is None:
            self.max_render_pixels = get_configured_max_render_pixels(default=12_000_000)
        else:
            self.max_render_pixels = max(250_000, self.max_render_pixels)

    @classmethod
    def from_settings_or_env(cls, **overrides: Any) -> "PDFSafetyLimits":
        """Construct PDFSafetyLimits honoring configured DPI, pixel caps, and overrides."""
        return cls(**overrides)


def _close_image_quietly(image: Optional[Image.Image]) -> None:
    if image is None:
        return
    try:
        image.close()
    except Exception:
        pass


def _clamp_engine_str(value: Any, max_len: int = 50) -> str:
    return str(value or "")[:max_len]


def _stream_byte_size(stream: Any) -> Optional[int]:
    if not hasattr(stream, "seek") or not hasattr(stream, "tell"):
        return None
    try:
        cur = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = int(stream.tell())
        stream.seek(cur)
        return size
    except Exception:
        return None


def _materialize_pdf_input(
    file_path_or_bytes: Any,
    max_file_bytes: int,
) -> Tuple[Optional[bytes], Optional[str], List[str]]:
    """
    Safely loads PDF bytes after checking size caps before buffering large inputs.
    Returns ``(pdf_bytes, error_kind, warnings)`` where ``error_kind`` is one of
    ``None``, ``'empty'``, ``'oversized'``, or ``'malformed'``.
    """
    warnings: List[str] = []
    if file_path_or_bytes is None:
        return None, "empty", ["Empty PDF input (None)."]

    if isinstance(file_path_or_bytes, (bytes, bytearray)):
        raw = bytes(file_path_or_bytes)
        if not raw:
            return None, "empty", ["Empty PDF byte stream (0 bytes)."]
        if len(raw) > max_file_bytes:
            warnings.append(
                f"PDF exceeds maximum allowed size ({len(raw)} > {max_file_bytes} bytes)."
            )
            return None, "oversized", warnings
        return raw, None, warnings

    if isinstance(file_path_or_bytes, (str, os.PathLike)):
        path_str = os.fspath(file_path_or_bytes)
        try:
            size = os.path.getsize(path_str)
        except OSError as exc:
            return None, "malformed", [f"Unable to inspect PDF path: {sanitize_sensitive_data(str(exc))}"]
        if size <= 0:
            return None, "empty", ["Empty PDF file (0 bytes)."]
        if size > max_file_bytes:
            warnings.append(
                f"PDF file size ({size} bytes) exceeds limit ({max_file_bytes} bytes)."
            )
            return None, "oversized", warnings
        try:
            with open(path_str, "rb") as fh:
                return fh.read(), None, warnings
        except OSError as exc:
            return None, "malformed", [f"Unable to read PDF file: {sanitize_sensitive_data(str(exc))}"]

    if hasattr(file_path_or_bytes, "read"):
        stream_size = _stream_byte_size(file_path_or_bytes)
        if stream_size is not None:
            if stream_size <= 0:
                return None, "empty", ["Empty PDF stream (0 bytes)."]
            if stream_size > max_file_bytes:
                warnings.append(
                    f"PDF stream size ({stream_size} bytes) exceeds limit ({max_file_bytes} bytes)."
                )
                return None, "oversized", warnings
        try:
            if hasattr(file_path_or_bytes, "seek"):
                file_path_or_bytes.seek(0)
            chunk = file_path_or_bytes.read(max_file_bytes + 1)
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8", errors="ignore")
            raw = bytes(chunk or b"")
            if not raw:
                return None, "empty", ["Empty PDF stream (0 bytes)."]
            if len(raw) > max_file_bytes:
                warnings.append(
                    f"PDF stream exceeds maximum allowed size (> {max_file_bytes} bytes)."
                )
                return None, "oversized", warnings
            return raw, None, warnings
        except Exception as exc:
            return None, "malformed", [f"Unable to read PDF stream: {sanitize_sensitive_data(str(exc))}"]

    return None, "malformed", [f"Unsupported PDF input type: {type(file_path_or_bytes).__name__}"]


def get_page_geometry(page: Any) -> Dict[str, Any]:
    """Extracts display dimensions, rotation, MediaBox, and CropBox metadata from a PyMuPDF page."""
    rect = getattr(page, "rect", None)
    mediabox = getattr(page, "mediabox", rect)
    cropbox = getattr(page, "cropbox", rect)
    rotation = int(getattr(page, "rotation", 0) or 0) % 360

    x0 = float(getattr(rect, "x0", 0.0) or 0.0)
    y0 = float(getattr(rect, "y0", 0.0) or 0.0)
    width = max(float(getattr(rect, "width", 612.0) or 612.0), 1.0)
    height = max(float(getattr(rect, "height", 792.0) or 792.0), 1.0)

    return {
        "page_number": int(getattr(page, "number", 0)) + 1,
        "x0": x0,
        "y0": y0,
        "width": round(width, 4),
        "height": round(height, 4),
        "rotation": rotation,
        "display_rect": [round(x0, 2), round(y0, 2), round(x0 + width, 2), round(y0 + height, 2)],
        "mediabox": [
            round(float(getattr(mediabox, "x0", 0.0)), 2),
            round(float(getattr(mediabox, "y0", 0.0)), 2),
            round(float(getattr(mediabox, "x1", width)), 2),
            round(float(getattr(mediabox, "y1", height)), 2),
        ],
        "cropbox": [
            round(float(getattr(cropbox, "x0", x0)), 2),
            round(float(getattr(cropbox, "y0", y0)), 2),
            round(float(getattr(cropbox, "x1", x0 + width)), 2),
            round(float(getattr(cropbox, "y1", y0 + height)), 2),
        ],
    }


def transform_rect_to_display(
    rect_like: Any,
    page: Any,
    already_in_display_space: bool = False,
) -> Optional[Tuple[float, float, float, float]]:
    """
    Maps a PDF rectangle into page display coordinates ``(x0, y0, x1, y1)`` matching
    ``page.rect`` and ``page.get_pixmap(clip=...)``.

    PyMuPDF 2.x returns unrotated coordinates from ``get_text('words')``,
    ``get_image_rects()``, and ``get_drawings()`` when ``page.rotation != 0``, so
    those must be multiplied by ``page.rotation_matrix``. ``find_tables()``
    already operates in display coordinates.
    """
    if pymupdf is None or rect_like is None:
        return None

    r = pymupdf.Rect(rect_like)
    if not already_in_display_space:
        rotation = int(getattr(page, "rotation", 0) or 0) % 360
        rot_matrix = getattr(page, "rotation_matrix", None)
        if rotation != 0 and rot_matrix is not None:
            r = r * rot_matrix

    r.normalize()
    disp = getattr(page, "rect", None)
    if disp is not None:
        r = r & disp
    if r.is_empty or r.width <= 0.0 or r.height <= 0.0:
        return None
    return (float(r.x0), float(r.y0), float(r.x1), float(r.y1))


def display_rect_to_normalized_box(
    rect_display: Tuple[float, float, float, float],
    geometry: Dict[str, Any],
) -> List[int]:
    """Normalizes a display-space rectangle relative to CropBox origin into 0..1000."""
    origin_x = float(geometry.get("x0", 0.0) or 0.0)
    origin_y = float(geometry.get("y0", 0.0) or 0.0)
    pw = float(geometry.get("width", 612.0) or 612.0)
    ph = float(geometry.get("height", 792.0) or 792.0)
    x0, y0, x1, y1 = rect_display
    return rect_to_normalized_box(
        x0 - origin_x,
        y0 - origin_y,
        x1 - origin_x,
        y1 - origin_y,
        canvas_width=pw,
        canvas_height=ph,
    )


def remap_crop_box_to_page_normalized(
    word_box: Dict[str, Any],
    crop_width: int,
    crop_height: int,
    region_display_rect: Tuple[float, float, float, float],
    geometry: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Remaps OCR word coordinates measured on a cropped region bitmap back into
    full-page display coordinates and canonical [ymin, xmin, ymax, xmax] (0..1000).
    """
    remapped = dict(word_box)
    cw = max(float(crop_width or 1), 1.0)
    ch = max(float(crop_height or 1), 1.0)
    rx0, ry0, rx1, ry1 = region_display_rect
    rw = max(rx1 - rx0, 1.0)
    rh = max(ry1 - ry0, 1.0)

    bx = float(word_box.get("x", 0.0) or 0.0)
    by = float(word_box.get("y", 0.0) or 0.0)
    bw = max(float(word_box.get("w", 0.0) or 0.0), 0.0)
    bh = max(float(word_box.get("h", 0.0) or 0.0), 0.0)

    # Prefer original normalized_box fractions when preprocessor upscaled the crop
    if isinstance(word_box.get("normalized_box"), (list, tuple)) and len(word_box["normalized_box"]) == 4:
        cy0, cx0, cy1, cx1 = word_box["normalized_box"]
        fx0, fx1 = float(cx0) / 1000.0, float(cx1) / 1000.0
        fy0, fy1 = float(cy0) / 1000.0, float(cy1) / 1000.0
    else:
        fx0, fx1 = bx / cw, (bx + bw) / cw
        fy0, fy1 = by / ch, (by + bh) / ch

    px0 = rx0 + (fx0 * rw)
    px1 = rx0 + (fx1 * rw)
    py0 = ry0 + (fy0 * rh)
    py1 = ry0 + (fy1 * rh)

    remapped["normalized_box"] = display_rect_to_normalized_box((px0, py0, px1, py1), geometry)
    origin_x = float(geometry.get("x0", 0.0) or 0.0)
    origin_y = float(geometry.get("y0", 0.0) or 0.0)
    remapped["x"] = round(px0 - origin_x)
    remapped["y"] = round(py0 - origin_y)
    remapped["w"] = max(0, round(px1 - px0))
    remapped["h"] = max(0, round(py1 - py0))
    return remapped


class PyMuPDFNativePDFExtractor:
    """
    Extracts digital text and word bounding boxes from a PyMuPDF page while
    preserving LORE's Bengali visual-order repair, Bangla digit conversion,
    and digital sufficiency thresholds (char_count > 20).
    """

    @classmethod
    def extract_page(
        cls,
        page: Any,
        geometry: Optional[Dict[str, Any]] = None,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
        digital_threshold: int = 20,
    ) -> Dict[str, Any]:
        geom = geometry or get_page_geometry(page)
        pw = float(geom["width"])
        ph = float(geom["height"])
        origin_x = float(geom.get("x0", 0.0) or 0.0)
        origin_y = float(geom.get("y0", 0.0) or 0.0)

        # Normalize NBSP emitted by some Unicode PDF fonts so Bengali pattern repair matches cleanly
        raw_text = (page.get_text("text", sort=True) or "").replace("\u00a0", " ").strip()
        raw_words = page.get_text("words") or []

        is_visual = repair_bengali and is_visual_encoded_document(raw_text)
        clean_text = repair_visual_bengali_document(raw_text) if is_visual else raw_text
        repaired_flag = is_visual and (clean_text != raw_text)
        if convert_bangla_digits and clean_text:
            converted = bangla_to_arabic_digits(clean_text)
            if converted != clean_text:
                clean_text = converted
                repaired_flag = True

        bboxes: List[Dict[str, Any]] = []
        for entry in raw_words:
            if len(entry) < 5:
                continue
            wx0, wy0, wx1, wy1, word_str = entry[:5]
            w_text = str(word_str or "").strip()
            if not w_text:
                continue
            if is_visual:
                w_text = repair_visual_bengali_document(w_text)
            if convert_bangla_digits:
                w_text = bangla_to_arabic_digits(w_text)

            disp = transform_rect_to_display((wx0, wy0, wx1, wy1), page, already_in_display_space=False)
            if disp is None:
                continue
            dx0, dy0, dx1, dy1 = disp
            bboxes.append({
                "word": w_text,
                "confidence": 0.96 if not is_visual else 0.93,
                "x": round(dx0 - origin_x),
                "y": round(dy0 - origin_y),
                "w": max(0, round(dx1 - dx0)),
                "h": max(0, round(dy1 - dy0)),
                "normalized_box": display_rect_to_normalized_box(disp, geom),
            })

        char_count = len(clean_text.strip())
        word_count = max(len(bboxes), len(clean_text.split())) if clean_text else 0

        if char_count > 100:
            confidence = 0.96
            is_digital = True
        elif char_count > digital_threshold:
            confidence = 0.88
            is_digital = True
        elif char_count > 0:
            confidence = 0.60
            is_digital = False
        else:
            confidence = 0.0
            is_digital = False

        return {
            "text": clean_text.strip(),
            "words_count": word_count,
            "confidence": confidence,
            "bounding_boxes": bboxes,
            "char_count": char_count,
            "is_digital": is_digital,
            "is_repaired": repaired_flag,
            "width": pw,
            "height": ph,
            "engine": "pymupdf",
            "engine_version": _clamp_engine_str(PYMUPDF_VERSION),
        }


class PyMuPDFPageRenderer:
    """
    On-demand single-page and selected-region PyMuPDF rasterizer with adaptive
    DPI scaling and explicit Pixmap memory release.
    """

    @staticmethod
    def compute_safe_dpi(
        width_pt: float,
        height_pt: float,
        target_dpi: int = 300,
        max_render_pixels: int = 24_000_000,
    ) -> Tuple[int, Optional[str]]:
        w_in = max(width_pt / 72.0, 0.1)
        h_in = max(height_pt / 72.0, 0.1)
        target_pixels = (w_in * target_dpi) * (h_in * target_dpi)
        if target_pixels <= max_render_pixels or target_pixels <= 0:
            return target_dpi, None

        scale = (max_render_pixels / target_pixels) ** 0.5
        safe_dpi = max(72, int(target_dpi * scale))
        warning = (
            f"Adaptive DPI clamped from {target_dpi} to {safe_dpi} DPI "
            f"to stay within {max_render_pixels:,} pixel render limit."
        )
        return safe_dpi, warning

    @classmethod
    def render_page_image(
        cls,
        page: Any,
        dpi: int = 300,
        max_render_pixels: int = 24_000_000,
    ) -> Tuple[Optional[Image.Image], int, List[str]]:
        warnings: List[str] = []
        rect = page.rect
        safe_dpi, dpi_warn = cls.compute_safe_dpi(rect.width, rect.height, dpi, max_render_pixels)
        if dpi_warn:
            warnings.append(dpi_warn)

        pix = None
        try:
            pix = page.get_pixmap(dpi=safe_dpi, alpha=False)
            pil_image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            return pil_image, safe_dpi, warnings
        except Exception as exc:
            warnings.append(f"PyMuPDF page render failed: {sanitize_sensitive_data(str(exc))}")
            return None, safe_dpi, warnings
        finally:
            if pix is not None:
                del pix

    @classmethod
    def extract_or_render_region_image(
        cls,
        doc: Any,
        page: Any,
        region_display_rect: Tuple[float, float, float, float],
        xref: Optional[int] = None,
        dpi: int = 300,
        max_render_pixels: int = 24_000_000,
    ) -> Tuple[Optional[Image.Image], str, List[str]]:
        """
        Obtains a single visual region bitmap on demand:
        1. Attempts raw image stream extraction via ``doc.extract_image(xref)`` when
           unrotated and non-masked.
        2. Falls back to clipped PyMuPDF rendering (``page.get_pixmap(clip=...)``),
           preserving rotation, crop boxes, color spaces, and vector overlays.
        """
        warnings: List[str] = []
        rotation = int(getattr(page, "rotation", 0) or 0) % 360

        # Direct embedded XObject extraction when rotation/mask doesn't alter display orientation
        if xref and xref > 0 and rotation == 0:
            try:
                img_dict = doc.extract_image(xref)
                smask = int(img_dict.get("smask", 0) or 0)
                img_bytes = img_dict.get("image")
                w = int(img_dict.get("width", 0) or 0)
                h = int(img_dict.get("height", 0) or 0)
                if smask == 0 and img_bytes and w >= 16 and h >= 16 and (w * h) <= max_render_pixels:
                    extracted = _open_image_bytes_safe(img_bytes, max_pixels=max_render_pixels)
                    if extracted is not None:
                        rgb_img = extracted.convert("RGB") if extracted.mode != "RGB" else extracted
                        if rgb_img is not extracted:
                            _close_image_quietly(extracted)
                        return rgb_img, "pymupdf_extract_image", warnings
            except Exception as exc:
                warnings.append(
                    f"Embedded image extraction fallback to clipped render for xref={xref}: "
                    f"{sanitize_sensitive_data(str(exc))}"
                )

        if pymupdf is None:
            return None, "unavailable", warnings

        rx0, ry0, rx1, ry1 = region_display_rect
        clip_rect = pymupdf.Rect(rx0, ry0, rx1, ry1) & page.rect
        if clip_rect.is_empty or clip_rect.width <= 1.0 or clip_rect.height <= 1.0:
            return None, "empty_clip", warnings

        safe_dpi, dpi_warn = cls.compute_safe_dpi(
            clip_rect.width, clip_rect.height, dpi, max_render_pixels
        )
        if dpi_warn:
            warnings.append(dpi_warn)

        pix = None
        try:
            pix = page.get_pixmap(dpi=safe_dpi, clip=clip_rect, alpha=False)
            pil_image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            return pil_image, "pymupdf_clip_render", warnings
        except Exception as exc:
            warnings.append(f"PyMuPDF clipped render failed: {sanitize_sensitive_data(str(exc))}")
            return None, "render_error", warnings
        finally:
            if pix is not None:
                del pix


class PyMuPDFVisualPDFAdapter:
    """
    Production adapter integrating PyMuPDF page inspection/rendering, native PDF
    text preservation, ``TesseractOCRProvider`` OCR, Bengali repair, and visual
    region extraction under the ``UnifiedDocumentExtractor`` / ``OCRRouter`` contract.
    """

    def __init__(
        self,
        ocr_provider: Optional[BaseOCRProvider] = None,
        visual_provider: Optional[Any] = None,
        layout_provider: Optional[Any] = None,
        table_extractor: Optional[Any] = None,
        chart_extractor: Optional[Any] = None,
        form_extractor: Optional[Any] = None,
        prefer_existing_native: bool = True,
        enable_visual_regions: bool = True,
        render_mixed_regions_on_demand: bool = True,
        analyze_searchable_with_layout: Optional[bool] = None,
        append_visual_text: bool = True,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
        limits: Optional[PDFSafetyLimits] = None,
        fallback_router: Optional[OCRRouter] = None,
    ):
        self.ocr_provider: BaseOCRProvider = ocr_provider or TesseractOCRProvider()
        self.visual_provider = visual_provider
        self.layout_provider = layout_provider
        self.table_extractor = (
            table_extractor
            if table_extractor is not None
            else getattr(layout_provider, "table_extractor", None)
        )
        self.chart_extractor = (
            chart_extractor
            if chart_extractor is not None
            else getattr(layout_provider, "chart_extractor", None)
        )
        self.form_extractor = (
            form_extractor
            if form_extractor is not None
            else getattr(layout_provider, "form_extractor", None)
        )
        self.prefer_existing_native = prefer_existing_native
        self.enable_visual_regions = enable_visual_regions
        self.render_mixed_regions_on_demand = render_mixed_regions_on_demand
        self.analyze_searchable_with_layout = (
            (self.table_extractor is not None)
            if analyze_searchable_with_layout is None
            else analyze_searchable_with_layout
        )
        self.append_visual_text = append_visual_text
        self.repair_bengali = repair_bengali
        self.convert_bangla_digits = convert_bangla_digits
        self.limits = limits or PDFSafetyLimits()
        self.fallback_router = fallback_router or OCRRouter(ocr_provider=self.ocr_provider)
        self.last_run_diagnostics: Dict[str, Any] = {}

    @staticmethod
    def _rect_inside_any(
        rect: Tuple[float, float, float, float],
        containers: Sequence[Tuple[float, float, float, float]],
        tolerance: float = 4.0,
    ) -> bool:
        x0, y0, x1, y1 = rect
        for cx0, cy0, cx1, cy1 in containers:
            if (
                x0 >= (cx0 - tolerance)
                and y0 >= (cy0 - tolerance)
                and x1 <= (cx1 + tolerance)
                and y1 <= (cy1 + tolerance)
            ):
                return True
        return False

    @staticmethod
    def _rect_overlaps_any(
        rect: Tuple[float, float, float, float],
        others: Sequence[Tuple[float, float, float, float]],
        min_ratio: float = 0.40,
    ) -> bool:
        """Return True if ``rect`` overlaps any box in ``others`` by >= ``min_ratio`` of min area."""
        rx0, ry0, rx1, ry1 = rect
        r_area = max(1.0, max(0.0, rx1 - rx0) * max(0.0, ry1 - ry0))
        for ox0, oy0, ox1, oy1 in others:
            inter = max(0.0, min(rx1, ox1) - max(rx0, ox0)) * max(0.0, min(ry1, oy1) - max(ry0, oy0))
            if inter <= 0.0:
                continue
            o_area = max(1.0, max(0.0, ox1 - ox0) * max(0.0, oy1 - oy0))
            if (inter / min(r_area, o_area)) >= min_ratio:
                return True
        return False

    def _build_diagnostic_page(
        self,
        *,
        page_number: int = 1,
        width: float = 0.0,
        height: float = 0.0,
        rotation: int = 0,
        extraction_type: str,
        status: str,
        classification: PDFPageClassification,
        engine: str = "pymupdf",
        engine_version: Optional[str] = None,
        warnings: Optional[Sequence[str]] = None,
        fallback_reason: VisualFallbackReason = VisualFallbackReason.NONE,
    ) -> Dict[str, Any]:
        clean_warnings = [w for w in (warnings or []) if w]
        fb_reasons = [fallback_reason.value] if fallback_reason != VisualFallbackReason.NONE else []
        page = {
            "page_number": page_number,
            "text": "",
            "confidence": 0.0,
            "words_count": 0,
            "width": width,
            "height": height,
            "extraction_type": _clamp_engine_str(extraction_type),
            "engine": _clamp_engine_str(engine),
            "engine_version": _clamp_engine_str(engine_version or PYMUPDF_VERSION),
            "is_repaired": False,
            "needs_review": True,
            "status": status,
            "rotation": rotation,
            "page_classification": classification.value,
            "warnings": clean_warnings,
            "bounding_boxes": [],
            "visual_regions": [],
            "visual_metadata": {
                "contract_version": VISUAL_INTEGRATION_CONTRACT_VERSION,
                "has_visual_content": False,
                "visual_region_count": 0,
                "visual_confidence": 0.0,
                "visual_engines": [],
                "visual_inference_count": 0,
                "visual_timings_ms": 0.0,
                "provider_metrics": [],
                "fallback_applied": bool(fb_reasons),
                "fallback_reasons": fb_reasons,
                "page_classification": classification.value,
                "rotation": rotation,
                "ocr_triggered": False,
                "render_count": 0,
                "warnings": clean_warnings,
            },
        }
        return page

    def _run_ocr_router_fallback(
        self,
        pdf_bytes: bytes,
        max_pages: int,
        reason: VisualFallbackReason,
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        """Falls back gracefully to LORE's existing OCRRouter when PyMuPDF cannot execute."""
        fallback_pages = self.fallback_router.process_pdf(pdf_bytes, max_pages=max_pages)
        if not fallback_pages:
            err_warns = list(warnings) + [
                "Malformed or unreadable PDF stream during OCRRouter fallback."
            ]
            self.last_run_diagnostics = {
                "status": "malformed_pdf",
                "fallback_reason": reason.value,
                "page_count": 1,
                "warnings": err_warns,
            }
            return [
                self._build_diagnostic_page(
                    extraction_type="pdf_malformed",
                    status="malformed_pdf",
                    classification=PDFPageClassification.MALFORMED,
                    warnings=err_warns,
                )
            ]

        annotated: List[Dict[str, Any]] = []
        for idx, p in enumerate(fallback_pages, start=1):
            base = dict(p)
            base.setdefault("page_number", idx)
            base.setdefault("bounding_boxes", [])
            page_warnings = list(warnings)
            if base.get("error_detail"):
                page_warnings.append(str(base["error_detail"]))
            enriched: Dict[str, Any] = cast(
                Dict[str, Any],
                VisualPipelineIntegrationAdapter.apply_fallback(
                    baseline_page=base,
                    reason=reason,
                    error_detail="; ".join(page_warnings),
                ),
            )
            is_digital = enriched.get("extraction_type") == "digital_pdf"
            page_cls = (
                PDFPageClassification.SEARCHABLE.value
                if is_digital
                else PDFPageClassification.SCANNED.value
            )
            enriched["warnings"] = page_warnings
            enriched["rotation"] = int(base.get("rotation", 0) or 0)
            enriched["page_classification"] = page_cls
            enriched["visual_metadata"]["warnings"] = page_warnings
            enriched["visual_metadata"]["fallback_applied"] = True
            enriched["visual_metadata"]["page_classification"] = page_cls
            enriched["visual_metadata"]["rotation"] = enriched["rotation"]
            enriched["visual_metadata"]["ocr_triggered"] = not is_digital
            enriched["visual_metadata"]["render_count"] = 0 if is_digital else 1
            if base.get("needs_review") is not None:
                enriched["needs_review"] = bool(base["needs_review"])
            if base.get("status"):
                enriched["status"] = base["status"]
            if base.get("language"):
                enriched["language"] = base["language"]
            annotated.append(enriched)

        self.last_run_diagnostics = {
            "status": "fallback_ocr_router",
            "fallback_reason": reason.value,
            "page_count": len(annotated),
            "warnings": list(warnings),
        }
        return annotated

    def _extract_native_first(
        self,
        pymupdf_page: Any,
        plumber_page: Any,
        geometry: Dict[str, Any],
        warnings: List[str],
    ) -> Dict[str, Any]:
        """
        Extracts native text before triggering any OCR. Prefers LORE's existing
        ``DigitalPDFExtractor`` when sufficient (> 20 chars), with PyMuPDF native
        text as a geometry/rotation-aware secondary native extractor.
        """
        threshold = self.limits.digital_text_threshold_chars

        if self.prefer_existing_native and plumber_page is not None:
            try:
                plumber_res = DigitalPDFExtractor.extract_page(plumber_page)
                if self.convert_bangla_digits and plumber_res.get("text"):
                    plumber_res["text"] = bangla_to_arabic_digits(plumber_res["text"])
                    for box in plumber_res.get("bounding_boxes", []):
                        box["word"] = bangla_to_arabic_digits(box.get("word", ""))
                    plumber_res["is_repaired"] = True
                if plumber_res.get("char_count", 0) > threshold and plumber_res.get("is_digital"):
                    plumber_res["engine"] = "pdfplumber"
                    plumber_res["engine_version"] = "0.11.9"
                    return plumber_res
            except Exception as exc:
                warnings.append(
                    f"Page {geometry['page_number']} pdfplumber native fallback to PyMuPDF: "
                    f"{sanitize_sensitive_data(str(exc))}"
                )
                plumber_res = None
        else:
            plumber_res = None

        pymupdf_res = PyMuPDFNativePDFExtractor.extract_page(
            pymupdf_page,
            geometry=geometry,
            repair_bengali=self.repair_bengali,
            convert_bangla_digits=self.convert_bangla_digits,
            digital_threshold=threshold,
        )
        if pymupdf_res.get("char_count", 0) > threshold and pymupdf_res.get("is_digital"):
            return pymupdf_res

        if plumber_res and plumber_res.get("char_count", 0) >= pymupdf_res.get("char_count", 0):
            plumber_res.setdefault("engine", "pdfplumber")
            plumber_res.setdefault("engine_version", "0.11.9")
            return plumber_res
        return pymupdf_res

    def _inspect_page_visuals(
        self,
        pymupdf_page: Any,
        plumber_page: Any,
        geometry: Dict[str, Any],
        native_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Inspects tables, embedded raster images, and vector graphic clusters via PyMuPDF."""
        page_num = geometry["page_number"]
        pw = float(geometry["width"])
        ph = float(geometry["height"])
        min_pt = self.limits.min_graphic_pt

        # 1. Vector tables via PyMuPDF (display coords) or pdfplumber fallback
        table_regions: List[Dict[str, Any]] = []
        table_rects: List[Tuple[float, float, float, float]] = []

        if self.enable_visual_regions and hasattr(pymupdf_page, "find_tables"):
            try:
                finder = pymupdf_page.find_tables()
                raw_tables = getattr(finder, "tables", None) or []
                for idx, tbl in enumerate(raw_tables, start=1):
                    rows = tbl.extract() or []
                    md = format_markdown_table(rows)
                    if not md:
                        continue
                    md, rep = apply_text_normalization(
                        md,
                        repair_bengali=self.repair_bengali,
                        convert_bangla_digits=self.convert_bangla_digits,
                    )
                    disp = transform_rect_to_display(tbl.bbox, pymupdf_page, already_in_display_space=True)
                    if disp is None:
                        disp = (geometry["x0"], geometry["y0"], geometry["x0"] + pw, geometry["y0"] + ph)
                    table_rects.append(disp)
                    dx0, dy0, dx1, dy1 = disp
                    region_id = f"p{page_num}-tbl{idx}"
                    table_regions.append(cast(Dict[str, Any], build_visual_region_provenance(
                        region_id=region_id,
                        region_type=VisualRegionType.TABLE,
                        extraction_kind=VisualExtractionKind.VECTOR_TABLE,
                        page_number=page_num,
                        bbox=[dx0, dy0, dx1 - dx0, dy1 - dy0],
                        normalized_box=display_rect_to_normalized_box(disp, geometry),
                        text=md,
                        markdown=format_visual_region_markdown(page_num, region_id, "Visual Table", md),
                        confidence=0.95,
                        engine="pymupdf_table",
                        engine_version=_clamp_engine_str(PYMUPDF_VERSION),
                        is_inference=False,
                        is_repaired=rep,
                        source_asset_name=f"pdf:page_{page_num}:table_{idx}",
                        metadata={"row_count": len(rows)},
                    )))
            except Exception as exc:
                logger.debug("PyMuPDF find_tables skipped on page %s: %s", page_num, exc)

        if not table_regions and self.enable_visual_regions and plumber_page is not None:
            try:
                for idx, tbl in enumerate(plumber_page.find_tables() or [], start=1):
                    rows = tbl.extract() or []
                    md = format_markdown_table(rows)
                    if not md:
                        continue
                    md, rep = apply_text_normalization(
                        md,
                        repair_bengali=self.repair_bengali,
                        convert_bangla_digits=self.convert_bangla_digits,
                    )
                    tx0, ttop, tx1, tbottom = getattr(tbl, "bbox", (0.0, 0.0, pw, ph))
                    disp = (
                        geometry["x0"] + float(tx0),
                        geometry["y0"] + float(ttop),
                        geometry["x0"] + float(tx1),
                        geometry["y0"] + float(tbottom),
                    )
                    table_rects.append(disp)
                    region_id = f"p{page_num}-tbl{idx}"
                    table_regions.append(cast(Dict[str, Any], build_visual_region_provenance(
                        region_id=region_id,
                        region_type=VisualRegionType.TABLE,
                        extraction_kind=VisualExtractionKind.VECTOR_TABLE,
                        page_number=page_num,
                        bbox=[disp[0], disp[1], disp[2] - disp[0], disp[3] - disp[1]],
                        normalized_box=display_rect_to_normalized_box(disp, geometry),
                        text=md,
                        markdown=format_visual_region_markdown(page_num, region_id, "Visual Table", md),
                        confidence=0.95,
                        engine="pdfplumber_table",
                        engine_version="0.11.9",
                        is_inference=False,
                        is_repaired=rep,
                        source_asset_name=f"pdf:page_{page_num}:table_{idx}",
                        metadata={"row_count": len(rows)},
                    )))
            except Exception:
                pass

        # 2. Embedded raster images transformed to display coords
        image_candidates: List[Dict[str, Any]] = []
        seen_rects: set[Tuple[int, int, int, int]] = set()
        try:
            raw_images = pymupdf_page.get_images(full=True) or []
        except Exception:
            raw_images = []

        for img_idx, info in enumerate(raw_images, start=1):
            xref = int(info[0]) if info else 0
            if xref <= 0:
                continue
            try:
                rects = pymupdf_page.get_image_rects(xref) or []
            except Exception:
                rects = []
            for r in rects:
                disp = transform_rect_to_display(r, pymupdf_page, already_in_display_space=False)
                if disp is None:
                    continue
                if (disp[2] - disp[0]) < min_pt or (disp[3] - disp[1]) < min_pt:
                    continue
                if self._rect_inside_any(disp, table_rects):
                    continue
                key = (round(disp[0]), round(disp[1]), round(disp[2]), round(disp[3]))
                if key in seen_rects:
                    continue
                seen_rects.add(key)
                image_candidates.append({
                    "bbox_display": disp,
                    "region_type": VisualRegionType.EMBEDDED_IMAGE.value,
                    "source_asset_name": f"pdf:page_{page_num}:image_{img_idx}_xref_{xref}",
                    "xref": xref,
                })

        # 3. Vector drawing clusters (charts / diagrams excluding page frames and table grids)
        draw_boxes: List[Tuple[float, float, float, float]] = []
        try:
            drawings = pymupdf_page.get_drawings() or []
        except Exception:
            drawings = []

        for d in drawings:
            raw_rect = d.get("rect")
            disp = transform_rect_to_display(raw_rect, pymupdf_page, already_in_display_space=False)
            if disp is None:
                continue
            dw = disp[2] - disp[0]
            dh = disp[3] - disp[1]
            is_page_frame = dw > (0.95 * pw) and dh > (0.95 * ph)
            if not is_page_frame and dw >= 4.0 and dh >= 4.0 and not self._rect_inside_any(disp, table_rects):
                draw_boxes.append(disp)

        vector_candidates: List[Dict[str, Any]] = []
        if len(draw_boxes) >= self.limits.min_vector_primitives:
            for c_idx, cluster in enumerate(_merge_boxes(draw_boxes, gap=16.0), start=1):
                cw = cluster[2] - cluster[0]
                ch = cluster[3] - cluster[1]
                if cw >= min_pt and ch >= min_pt and not self._rect_inside_any(cluster, [c["bbox_display"] for c in image_candidates]):
                    vector_candidates.append({
                        "bbox_display": cluster,
                        "region_type": VisualRegionType.CHART.value,
                        "source_asset_name": f"pdf:page_{page_num}:vector_cluster_{c_idx}",
                        "xref": None,
                    })

        # 4. Page classification
        has_images_or_vectors = bool(image_candidates or vector_candidates)
        if native_data["is_digital"] and native_data["char_count"] > self.limits.digital_text_threshold_chars:
            if has_images_or_vectors or table_regions:
                classification = PDFPageClassification.MIXED_CONTENT
            else:
                classification = PDFPageClassification.SEARCHABLE
        elif has_images_or_vectors or native_data["char_count"] > 0:
            classification = PDFPageClassification.SCANNED
        else:
            classification = PDFPageClassification.EMPTY

        return {
            "classification": classification,
            "table_regions": table_regions,
            "region_candidates": image_candidates + vector_candidates,
            "has_raster_or_vector_candidates": has_images_or_vectors,
        }

    def _run_region_ocr_or_visual(
        self,
        region_img: Image.Image,
        cand: Dict[str, Any],
        region_idx: int,
        geometry: Dict[str, Any],
        warnings: List[str],
        policy_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Analyzes one cropped/extracted visual region and remaps coordinates to full page."""
        page_num = geometry["page_number"]
        disp = cand["bbox_display"]
        region_id = f"p{page_num}-vis{region_idx}-{cand['region_type']}"
        norm_box = display_rect_to_normalized_box(disp, geometry)
        bbox_wh = [disp[0], disp[1], disp[2] - disp[0], disp[3] - disp[1]]

        # Use injected visual_provider when configured; otherwise use existing TesseractOCRProvider
        if self.visual_provider is not None:
            ctx = {
                "page_number": page_num,
                "region_type": cand["region_type"],
                "source_asset_name": cand["source_asset_name"],
                "parent_normalized_box": norm_box,
                "execution_mode": (policy_context or {}).get("execution_mode"),
                "policy_context": policy_context or {},
            }
            vis_res = self.visual_provider.analyze_image(region_img, context=ctx)
            text = str(vis_res.get("text") or "").strip()
            if VisualPipelineIntegrationAdapter.is_ocr_placeholder_text(text):
                text = ""
            conf = float(vis_res.get("confidence", 0.35) or 0.0)
            engine = str(vis_res.get("engine") or getattr(self.visual_provider, "provider_name", "visual"))
            engine_version = str(vis_res.get("engine_version") or "1.0")
            raw_regions = list(vis_res.get("regions") or [])
            word_boxes = []
            for rr in raw_regions:
                for wb in rr.get("word_boxes") or []:
                    word_boxes.append(
                        remap_crop_box_to_page_normalized(
                            wb, region_img.width, region_img.height, disp, geometry
                        )
                    )
            is_inference = any(bool(rr.get("is_inference")) for rr in raw_regions)
            is_repaired = any(bool(rr.get("is_repaired")) for rr in raw_regions)
            md_body = text or f"[Visual {cand['region_type']} region at normalized box {norm_box}]"
            return cast(Dict[str, Any], build_visual_region_provenance(
                region_id=region_id,
                region_type=cand["region_type"],
                extraction_kind=(
                    VisualExtractionKind.VISUAL_CAPTION
                    if is_inference
                    else (VisualExtractionKind.OCR_LAYOUT if text else VisualExtractionKind.HEURISTIC_LAYOUT)
                ),
                page_number=page_num,
                bbox=bbox_wh,
                normalized_box=norm_box,
                text=text,
                markdown=format_visual_region_markdown(
                    page_num, region_id, f"Visual {cand['region_type'].replace('_', ' ').title()}", md_body
                ),
                confidence=conf,
                engine=engine,
                engine_version=engine_version,
                is_inference=is_inference,
                is_repaired=is_repaired,
                source_asset_name=cand["source_asset_name"],
                word_boxes=cast(Any, word_boxes),
                metadata={"extraction_method": cand.get("extraction_method", "region")},
            ))

        padded = _pad_for_ocr_if_needed(region_img)
        try:
            ocr_res = self.ocr_provider.extract_image(padded)
        finally:
            if padded is not region_img:
                _close_image_quietly(padded)

        if ocr_res.get("error_detail"):
            warnings.append(f"Region {region_id} OCR error: {ocr_res['error_detail']}")

        raw_status = str(ocr_res.get("status", "success"))
        raw_text = str(ocr_res.get("text") or "").strip()
        is_placeholder = VisualPipelineIntegrationAdapter.is_ocr_placeholder_text(raw_text)
        clean_text = "" if (raw_status == "provider_unavailable" or is_placeholder) else raw_text
        if clean_text and self.convert_bangla_digits:
            clean_text = bangla_to_arabic_digits(clean_text)

        remapped_boxes = [
            remap_crop_box_to_page_normalized(wb, padded.width, padded.height, disp, geometry)
            for wb in (ocr_res.get("bounding_boxes") or [])
            if isinstance(wb, dict) and "word" in wb
        ]
        conf = float(ocr_res.get("confidence", 0.0) or 0.0)
        if not clean_text:
            conf = min(conf, 0.30) if conf > 0 else 0.30

        md_body = clean_text or f"[Non-text {cand['region_type']} region at normalized box {norm_box}]"
        return cast(Dict[str, Any], build_visual_region_provenance(
            region_id=region_id,
            region_type=cand["region_type"],
            extraction_kind=(
                VisualExtractionKind.OCR_LAYOUT if clean_text else VisualExtractionKind.HEURISTIC_LAYOUT
            ),
            page_number=page_num,
            bbox=bbox_wh,
            normalized_box=norm_box,
            text=clean_text,
            markdown=format_visual_region_markdown(
                page_num, region_id, f"Visual {cand['region_type'].replace('_', ' ').title()}", md_body
            ),
            confidence=conf,
            engine=str(ocr_res.get("engine") or "tesseract"),
            engine_version=str(ocr_res.get("engine_version") or "1.0"),
            is_inference=False,
            is_repaired=bool(clean_text),
            source_asset_name=cand["source_asset_name"],
            word_boxes=cast(Any, remapped_boxes),
            metadata={
                "ocr_status": raw_status,
                "language": ocr_res.get("language", ""),
                "extraction_method": cand.get("extraction_method", "region"),
            },
        ))

    @staticmethod
    def _build_layout_summary_entry(det: Mapping[str, Any], extracted_reg: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        meta = (extracted_reg or {}).get("metadata") or {}
        return {
            "region_id": str((extracted_reg or det).get("region_id", "")),
            "layout_category": str(meta.get("layout_category") or det.get("layout_category", "unknown")),
            "raw_label": str(meta.get("raw_label") or det.get("raw_label", "unknown")),
            "reading_order": int(meta.get("reading_order") or det.get("reading_order", 0) or 0),
            "normalized_box": list((extracted_reg or det).get("normalized_box") or [0, 0, 1000, 1000]),
            "score": float(det.get("score", (extracted_reg or {}).get("confidence", 0.0)) or 0.0),
            "extraction_route": str(meta.get("extraction_route") or det.get("extraction_route", "")),
        }

    def _apply_layout_to_scanned_page(
        self,
        *,
        raster_img: Image.Image,
        geometry: Dict[str, Any],
        baseline_page: Dict[str, Any],
        visual_regions: List[Dict[str, Any]],
        provider_metrics: List[Dict[str, Any]],
        page_warnings: List[str],
        extra_fallback_reasons: List[str],
        layout_telemetry: Dict[str, Any],
        pymupdf_page: Optional[Any] = None,
        policy_context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Runs optional layout detection on an already-rendered scanned page bitmap.
        Returns True on success or False to trigger clean full-page OCR fallback.
        """
        if self.layout_provider is None:
            return False

        page_num = geometry["page_number"]
        pw = float(geometry["width"])
        ph = float(geometry["height"])
        rotation = int(geometry["rotation"])

        try:
            if hasattr(self.layout_provider, "is_available") and not self.layout_provider.is_available():
                reason = getattr(self.layout_provider, "last_status_reason", "layout_provider_unavailable")
                page_warnings.append(
                    f"Page {page_num} layout detection skipped ({reason}); fell back to OCR pipeline."
                )
                extra_fallback_reasons.append(VisualFallbackReason.VISUAL_PROVIDER_UNAVAILABLE.value)
                return False

            vis_res = self.layout_provider.analyze_image(
                raster_img,
                context={
                    "page_number": page_num,
                    "page_width": pw,
                    "page_height": ph,
                    "source_rotation": rotation,
                    "apply_auto_rotate": False,
                    "table_extractor": self.table_extractor,
                    "chart_extractor": self.chart_extractor,
                    "form_extractor": self.form_extractor,
                    "pymupdf_page": pymupdf_page,
                    "source_asset_name": f"pdf:page_{page_num}",
                    "execution_mode": (policy_context or {}).get("execution_mode"),
                    "policy_context": policy_context or {},
                },
            )
            if vis_res.get("metrics"):
                provider_metrics.append(vis_res["metrics"])

            regions = list(vis_res.get("regions") or [])
            if vis_res.get("fallback_applied") or vis_res.get("status") != "success" or not regions:
                fb_reason = str(vis_res.get("fallback_reason") or vis_res.get("status") or "layout_fallback")
                page_warnings.append(
                    f"Page {page_num} layout detection fell back cleanly to full-page OCR ({fb_reason})."
                )
                extra_fallback_reasons.append(VisualFallbackReason.VISUAL_PROVIDER_UNAVAILABLE.value)
                return False

            collected_wbs: List[Dict[str, Any]] = []
            summary_list: List[Dict[str, Any]] = []
            for reg in regions:
                visual_regions.append(reg)
                summary_list.append(self._build_layout_summary_entry(reg, reg))
                for wb in reg.get("word_boxes") or []:
                    if isinstance(wb, dict) and "word" in wb:
                        collected_wbs.append(wb)

            raw_text = str(vis_res.get("text") or "")
            eff_text = "" if self.append_visual_text else raw_text
            baseline_page.update({
                "page_number": page_num,
                "text": eff_text,
                "confidence": round(max(0.0, min(1.0, float(vis_res.get("confidence", 0.0) or 0.0))), 4),
                "words_count": len(raw_text.split()),
                "width": pw,
                "height": ph,
                "extraction_type": "layout_pp_doclayout_s",
                "engine": _clamp_engine_str(vis_res.get("engine", "pp_doclayout_s")),
                "engine_version": _clamp_engine_str(vis_res.get("engine_version", "PP-DocLayout-S")),
                "is_repaired": any(bool(r.get("is_repaired")) for r in regions),
                "needs_review": bool(vis_res.get("needs_review", False)),
                "status": "success",
                "bounding_boxes": collected_wbs,
            })
            if getattr(self.ocr_provider, "lang", None):
                baseline_page["language"] = self.ocr_provider.lang

            layout_telemetry.update({
                "layout_provider": str(vis_res.get("engine") or "pp_doclayout_s"),
                "layout_model": str(vis_res.get("engine_version") or "PP-DocLayout-S"),
                "layout_regions_count": len(summary_list),
                "layout_regions": summary_list,
                "layout_timings_ms": float((vis_res.get("metrics") or {}).get("latency_ms", 0.0) or 0.0),
            })
            return True
        except Exception as exc:
            err = f"Page {page_num} layout provider error ({sanitize_sensitive_data(str(exc))}); falling back to OCR."
            logger.warning(err)
            page_warnings.append(err)
            extra_fallback_reasons.append(VisualFallbackReason.VISUAL_PROVIDER_UNAVAILABLE.value)
            return False

    def _apply_layout_to_digital_page(
        self,
        *,
        pymupdf_page: Any,
        geometry: Dict[str, Any],
        native_data: Dict[str, Any],
        visual_regions: List[Dict[str, Any]],
        table_regions: Sequence[Mapping[str, Any]],
        page_warnings: List[str],
        extra_fallback_reasons: List[str],
        layout_telemetry: Dict[str, Any],
    ) -> Tuple[bool, int, bool]:
        """
        Detects document layout on a searchable or mixed PDF page, deduplicating
        against already-extracted native tables/prose and routing only uncovered
        visual/form/table/unknown regions to crop/native extractors.
        """
        if self.layout_provider is None:
            return False, 0, False

        page_num = geometry["page_number"]
        pw = float(geometry["width"])
        ph = float(geometry["height"])
        rotation = int(geometry["rotation"])

        try:
            if hasattr(self.layout_provider, "is_available") and not self.layout_provider.is_available():
                reason = getattr(self.layout_provider, "last_status_reason", "layout_provider_unavailable")
                page_warnings.append(
                    f"Page {page_num} layout detection skipped ({reason}); using native+visual fallback."
                )
                extra_fallback_reasons.append(VisualFallbackReason.VISUAL_PROVIDER_UNAVAILABLE.value)
                return False, 0, False
        except Exception as avail_exc:
            page_warnings.append(f"Page {page_num} layout availability probe error: {sanitize_sensitive_data(str(avail_exc))}")
            extra_fallback_reasons.append(VisualFallbackReason.VISUAL_PROVIDER_UNAVAILABLE.value)
            return False, 0, False

        page_img = None
        renders_done = 0
        ocr_used = False
        try:
            page_img, _, render_warns = PyMuPDFPageRenderer.render_page_image(
                pymupdf_page,
                dpi=self.limits.dpi or 300,
                max_render_pixels=self.limits.max_render_pixels or 12_000_000,
            )
            page_warnings.extend(render_warns)
            if page_img is None:
                return False, 0, False
            renders_done = 1

            det_res = self.layout_provider.detect_layout(
                page_img,
                page_number=page_num,
                page_width=pw,
                page_height=ph,
                source_rotation=rotation,
                apply_auto_rotate=False,
            )
            dets = list(det_res.get("regions") or [])
            if not dets:
                return False, renders_done, False

            from .layout import (
                LayoutCategory,
                compute_containment,
                compute_iou,
                is_form_kv_text,
                route_and_extract_region,
            )

            scale_x = pw / max(float(page_img.width), 1.0)
            scale_y = ph / max(float(page_img.height), 1.0)
            native_boxes = list(native_data.get("bounding_boxes") or [])
            table_norm_boxes = [
                (tbl.get("normalized_box"), tbl.get("region_id", ""))
                for tbl in table_regions
                if tbl.get("normalized_box")
            ]

            def _to_xyxy(nb: Sequence[int]) -> Tuple[int, int, int, int]:
                return (nb[1], nb[0], nb[3], nb[2])

            def _native_words_inside(nb: Sequence[int]) -> Tuple[str, List[Dict[str, Any]]]:
                ymin, xmin, ymax, xmax = nb[0], nb[1], nb[2], nb[3]
                hits: List[Dict[str, Any]] = []
                for wb in native_boxes:
                    wnb = wb.get("normalized_box")
                    if not isinstance(wnb, (list, tuple)) or len(wnb) < 4:
                        continue
                    cx = (int(wnb[1]) + int(wnb[3])) / 2.0
                    cy = (int(wnb[0]) + int(wnb[2])) / 2.0
                    if (xmin - 5) <= cx <= (xmax + 5) and (ymin - 5) <= cy <= (ymax + 5):
                        hits.append(wb)
                text_out = " ".join(str(h.get("word", "")).strip() for h in hits if str(h.get("word", "")).strip())
                return text_out, hits

            summary_list: List[Dict[str, Any]] = []
            for det in dets:
                det_xyxy = _to_xyxy(det["normalized_box"])
                cat = str(det.get("layout_category", LayoutCategory.UNKNOWN.value))

                # Avoid duplicate extraction against already-extracted native vector tables
                matched_table_id = ""
                matched_vec_tbl: Optional[Dict[str, Any]] = None
                for tbl_nb, tbl_id in table_norm_boxes:
                    if tbl_nb is None:
                        continue
                    tbl_xyxy = _to_xyxy(tbl_nb)
                    if compute_iou(det_xyxy, tbl_xyxy) >= 0.45 or compute_containment(det_xyxy, tbl_xyxy) >= 0.70:
                        matched_table_id = str(tbl_id)
                        matched_vec_tbl = next(
                            (r for r in visual_regions if str(r.get("region_id")) == matched_table_id),
                            None,
                        )
                        break

                if matched_table_id and (self.table_extractor is None or cat != LayoutCategory.TABLE.value):
                    summary_entry = self._build_layout_summary_entry(det)
                    summary_entry["deduplicated_against"] = matched_table_id
                    summary_list.append(summary_entry)
                    continue

                native_text, native_hits = _native_words_inside(det["normalized_box"])
                needs_visual_emit = cat in (
                    LayoutCategory.TABLE.value,
                    LayoutCategory.CHART.value,
                    LayoutCategory.FIGURE_IMAGE.value,
                ) or (
                    cat == LayoutCategory.FORM.value
                ) or (
                    cat == LayoutCategory.UNKNOWN.value and not native_text
                ) or (
                    cat == LayoutCategory.PARAGRAPH.value and native_text and is_form_kv_text(native_text)
                )

                if needs_visual_emit:
                    if cat == LayoutCategory.TABLE.value and self.table_extractor is not None:
                        footnote_ctx = [
                            {
                                "raw_label": other.get("raw_label", ""),
                                "layout_category": other.get("layout_category", ""),
                                "normalized_box": other.get("normalized_box"),
                                "region_id": other.get("region_id", ""),
                                "text": _native_words_inside(other["normalized_box"])[0],
                            }
                            for other in dets
                            if other is not det
                            and other.get("normalized_box")
                            and (
                                "footnote" in str(other.get("raw_label", "")).lower()
                                or str(other.get("layout_category", "")) == LayoutCategory.PARAGRAPH.value
                            )
                        ]
                        extracted = self.table_extractor.extract_table_region(
                            page_image=page_img,
                            table_box=det["pixel_box"],
                            bbox_format="pixel",
                            page_number=page_num,
                            page_width=pw,
                            page_height=ph,
                            source_rotation=rotation,
                            coords_in_unrotated_space=False,
                            region_id=det.get("region_id"),
                            layout_score=det.get("score"),
                            layout_label=str(det.get("raw_label", "table")),
                            native_words=native_boxes,
                            context_regions=footnote_ctx,
                            fallback_vector_table=matched_vec_tbl,
                            source_asset_name=f"pdf:page_{page_num}",
                        )
                        if (extracted.get("metadata") or {}).get("ocr_triggered"):
                            ocr_used = True
                        if matched_vec_tbl is not None:
                            if not (extracted.get("metadata") or {}).get("structure_fallback_applied"):
                                # Upgrade vector table candidate with SLANet_plus cell grid without duplicating
                                visual_regions[:] = [
                                    r for r in visual_regions if str(r.get("region_id")) != matched_table_id
                                ]
                                visual_regions.append(extracted)
                            else:
                                # Retained existing matched_vec_tbl cleanly without adding duplicate
                                extracted = matched_vec_tbl
                        else:
                            visual_regions.append(extracted)
                        summary_entry = self._build_layout_summary_entry(det, extracted)
                        if matched_table_id:
                            summary_entry["upgraded_from_table_id"] = matched_table_id
                        summary_list.append(summary_entry)
                        continue

                    if cat == LayoutCategory.CHART.value and self.chart_extractor is not None:
                        title_ctx = [
                            {
                                "raw_label": other.get("raw_label", ""),
                                "layout_category": other.get("layout_category", ""),
                                "normalized_box": other.get("normalized_box"),
                                "region_id": other.get("region_id", ""),
                                "text": _native_words_inside(other["normalized_box"])[0],
                            }
                            for other in dets
                            if other is not det
                            and other.get("normalized_box")
                            and (
                                "title" in str(other.get("raw_label", "")).lower()
                                or str(other.get("layout_category", "")) == LayoutCategory.TITLE_HEADING.value
                            )
                        ]
                        extracted = self.chart_extractor.extract_chart_region(
                            page_image=page_img,
                            chart_box=det["pixel_box"],
                            bbox_format="pixel",
                            page_number=page_num,
                            page_width=pw,
                            page_height=ph,
                            source_rotation=rotation,
                            coords_in_unrotated_space=False,
                            region_id=det.get("region_id"),
                            layout_score=det.get("score"),
                            layout_label=str(det.get("raw_label", "chart")),
                            pymupdf_page=pymupdf_page,
                            context_regions=title_ctx,
                            source_asset_name=f"pdf:page_{page_num}",
                        )
                        if ((extracted.get("metadata") or {}).get("ocr_metadata") or {}).get("ocr_triggered"):
                            ocr_used = True
                        visual_regions.append(extracted)
                        summary_list.append(self._build_layout_summary_entry(det, extracted))
                        continue

                    if (
                        cat == LayoutCategory.FORM.value
                        and self.form_extractor is not None
                        and str(det.get("raw_label", "")).lower() != "seal"
                    ):
                        extracted = self.form_extractor.extract_form_region(
                            page_image=page_img,
                            form_box=det["pixel_box"],
                            bbox_format="pixel",
                            page_number=page_num,
                            page_width=pw,
                            page_height=ph,
                            source_rotation=rotation,
                            coords_in_unrotated_space=False,
                            region_id=det.get("region_id"),
                            layout_score=det.get("score"),
                            layout_label=str(det.get("raw_label", "form")),
                            pymupdf_page=pymupdf_page,
                            native_words=native_boxes,
                            source_asset_name=f"pdf:page_{page_num}",
                        )
                        if ((extracted.get("metadata") or {}).get("ocr_metadata") or {}).get("ocr_triggered"):
                            ocr_used = True
                        visual_regions.append(extracted)
                        summary_list.append(self._build_layout_summary_entry(det, extracted))
                        continue

                    use_native = (
                        native_text
                        if cat in (LayoutCategory.FORM.value, LayoutCategory.PARAGRAPH.value) and native_text
                        else None
                    )
                    if use_native is None and self.ocr_provider.is_available():
                        ocr_used = True
                    extracted = route_and_extract_region(
                        region_det=det,
                        source_image=page_img,
                        ocr_provider=self.ocr_provider,
                        page_number=page_num,
                        page_width=pw,
                        page_height=ph,
                        scale_x=scale_x,
                        scale_y=scale_y,
                        repair_bengali=self.repair_bengali,
                        convert_bangla_digits=self.convert_bangla_digits,
                        form_extractor=self.form_extractor,
                        pymupdf_page=pymupdf_page,
                        native_words_all=native_boxes,
                        native_text_override=use_native,
                        native_word_boxes_override=native_hits if use_native else None,
                        source_asset_name=f"pdf:page_{page_num}",
                    )
                    visual_regions.append(extracted)
                    summary_list.append(self._build_layout_summary_entry(det, extracted))
                else:
                    summary_entry = self._build_layout_summary_entry(det)
                    summary_entry["covered_by_native_text"] = bool(native_text)
                    summary_list.append(summary_entry)

            layout_telemetry.update({
                "layout_provider": str(getattr(self.layout_provider, "provider_name", "pp_doclayout_s")),
                "layout_model": str(getattr(self.layout_provider, "engine_version", "PP-DocLayout-S")),
                "layout_regions_count": len(summary_list),
                "layout_regions": summary_list,
                "layout_timings_ms": float(det_res.get("elapsed_ms", 0.0) or 0.0),
            })
            return True, renders_done, ocr_used
        except Exception as exc:
            err = f"Page {page_num} digital layout analysis failed cleanly ({sanitize_sensitive_data(str(exc))}); falling back."
            logger.warning(err)
            page_warnings.append(err)
            extra_fallback_reasons.append(VisualFallbackReason.VISUAL_PROVIDER_UNAVAILABLE.value)
            return False, renders_done, ocr_used
        finally:
            _close_image_quietly(page_img)

    def _process_single_page(
        self,
        doc: Any,
        idx: int,
        plumber_pdf: Any,
        policy_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Processes exactly one PDF page and releases all raster/pixmap buffers before return."""
        pymupdf_page = None
        page_warnings: List[str] = []
        render_count = 0
        ocr_triggered = False

        try:
            pymupdf_page = doc.load_page(idx)
            geometry = get_page_geometry(pymupdf_page)
            page_num = geometry["page_number"]
            pw = float(geometry["width"])
            ph = float(geometry["height"])
            rotation = int(geometry["rotation"])

            plumber_page = None
            if plumber_pdf is not None and idx < len(plumber_pdf.pages):
                plumber_page = plumber_pdf.pages[idx]

            # 1. Native text extraction FIRST (before any raster rendering or OCR)
            native_data = self._extract_native_first(pymupdf_page, plumber_page, geometry, page_warnings)

            # 2. Structural & visual candidate inspection + classification
            inspection = self._inspect_page_visuals(pymupdf_page, plumber_page, geometry, native_data)
            classification: PDFPageClassification = inspection["classification"]
            visual_regions: List[Dict[str, Any]] = list(inspection["table_regions"])
            candidates: List[Dict[str, Any]] = list(inspection["region_candidates"])
            provider_metrics: List[Dict[str, Any]] = []

            if len(candidates) > self.limits.max_regions_per_page:
                page_warnings.append(
                    f"Page {page_num} region cap applied ({self.limits.max_regions_per_page} of {len(candidates)})."
                )
                candidates = candidates[: self.limits.max_regions_per_page]

            baseline_page: Dict[str, Any] = {}
            extra_fallback_reasons: List[str] = []
            layout_telemetry: Dict[str, Any] = {}

            def _should_use_layout_on_digital() -> bool:
                return (
                    self.layout_provider is not None
                    and self.enable_visual_regions
                    and (
                        classification == PDFPageClassification.MIXED_CONTENT
                        or self.analyze_searchable_with_layout
                    )
                )

            # 3. Base page assembly (either searchable/mixed digital OR scanned OCR)
            if classification in (PDFPageClassification.SEARCHABLE, PDFPageClassification.MIXED_CONTENT):
                baseline_page = {
                    "page_number": page_num,
                    "text": native_data["text"],
                    "confidence": native_data["confidence"],
                    "words_count": native_data["words_count"],
                    "width": pw,
                    "height": ph,
                    "extraction_type": "digital_pdf",
                    "engine": _clamp_engine_str(native_data.get("engine", "pdfplumber")),
                    "engine_version": _clamp_engine_str(native_data.get("engine_version", "0.11.9")),
                    "is_repaired": bool(native_data.get("is_repaired", False)),
                    "needs_review": False,
                    "status": "digital",
                    "bounding_boxes": list(native_data.get("bounding_boxes", [])),
                }

                layout_handled_visuals = False
                if _should_use_layout_on_digital():
                    layout_handled_visuals, layout_renders, layout_ocr_used = self._apply_layout_to_digital_page(
                        pymupdf_page=pymupdf_page,
                        geometry=geometry,
                        native_data=native_data,
                        visual_regions=visual_regions,
                        table_regions=inspection["table_regions"],
                        page_warnings=page_warnings,
                        extra_fallback_reasons=extra_fallback_reasons,
                        layout_telemetry=layout_telemetry,
                    )
                    render_count += layout_renders
                    if layout_ocr_used:
                        ocr_triggered = True

                extracted_chart_rects: List[Tuple[float, float, float, float]] = []
                extracted_form_rects: List[Tuple[float, float, float, float]] = []
                region_clip_count = 0
                if (
                    not layout_handled_visuals
                    and self.enable_visual_regions
                    and self.chart_extractor is not None
                ):
                    from .charts import detect_chart_candidates_in_pdf_page

                    tbl_rects_disp: List[Tuple[float, float, float, float]] = []
                    for vr in visual_regions:
                        if vr.get("region_type") == VisualRegionType.TABLE.value:
                            vb = vr.get("bbox") or []
                            if len(vb) >= 4:
                                tbl_rects_disp.append(
                                    (float(vb[0]), float(vb[1]), float(vb[0]) + float(vb[2]), float(vb[1]) + float(vb[3]))
                                )

                    vec_chart_cands = detect_chart_candidates_in_pdf_page(
                        pymupdf_page=pymupdf_page,
                        page_number=page_num,
                        table_rects_display=tbl_rects_disp,
                    )
                    for c_idx, vc in enumerate(vec_chart_cands, start=1):
                        vb_disp = vc["bbox_display"]
                        reg_img = None
                        try:
                            reg_img, _, c_warns = PyMuPDFPageRenderer.extract_or_render_region_image(
                                doc=doc,
                                page=pymupdf_page,
                                region_display_rect=vb_disp,
                                xref=None,
                                dpi=self.limits.dpi or 300,
                                max_render_pixels=self.limits.max_render_pixels or 12_000_000,
                            )
                            page_warnings.extend(c_warns)
                            if reg_img is not None:
                                render_count += 1
                                region_clip_count += 1
                                chart_prov = self.chart_extractor.extract_chart_region(
                                    page_image=reg_img,
                                    chart_box=vb_disp,
                                    bbox_format="display",
                                    page_number=page_num,
                                    page_width=float(geometry["width"]),
                                    page_height=float(geometry["height"]),
                                    source_rotation=int(geometry.get("rotation", 0) or 0),
                                    coords_in_unrotated_space=False,
                                    region_id=vc.get("region_id") or f"p{page_num}-chart-vec{c_idx}",
                                    layout_label="chart",
                                    pymupdf_page=pymupdf_page,
                                    source_asset_name=vc.get("source_asset_name") or f"pdf:page_{page_num}:chart_vec_{c_idx}",
                                    pre_cropped_display_rect=vb_disp,
                                )
                                visual_regions.append(chart_prov)
                                extracted_chart_rects.append(
                                    (float(vb_disp[0]), float(vb_disp[1]), float(vb_disp[2]), float(vb_disp[3]))
                                )
                                if (chart_prov.get("metadata") or {}).get("ocr_metadata", {}).get("ocr_triggered"):
                                    ocr_triggered = True
                        finally:
                            _close_image_quietly(reg_img)

                # Vector/digital form detection when layout_provider is absent or skipped
                if (
                    not layout_handled_visuals
                    and self.enable_visual_regions
                    and self.form_extractor is not None
                ):
                    from .forms import detect_form_candidates_in_pdf_page

                    excl_tbl_rects: List[Tuple[float, float, float, float]] = []
                    for vr in visual_regions:
                        if vr.get("region_type") == VisualRegionType.TABLE.value:
                            vb = vr.get("bbox") or []
                            if len(vb) >= 4:
                                excl_tbl_rects.append(
                                    (float(vb[0]), float(vb[1]), float(vb[0]) + float(vb[2]), float(vb[1]) + float(vb[3]))
                                )

                    vec_form_cands = detect_form_candidates_in_pdf_page(
                        pymupdf_page=pymupdf_page,
                        page_number=page_num,
                        table_rects_display=excl_tbl_rects,
                        chart_rects_display=extracted_chart_rects,
                    )
                    for f_idx, vf in enumerate(vec_form_cands, start=1):
                        fb_disp = vf["bbox_display"]
                        reg_img = None
                        try:
                            reg_img, _, f_warns = PyMuPDFPageRenderer.extract_or_render_region_image(
                                doc=doc,
                                page=pymupdf_page,
                                region_display_rect=fb_disp,
                                xref=None,
                                dpi=self.limits.dpi or 300,
                                max_render_pixels=self.limits.max_render_pixels or 12_000_000,
                            )
                            page_warnings.extend(f_warns)
                            if reg_img is not None:
                                render_count += 1
                                region_clip_count += 1
                                form_prov = self.form_extractor.extract_form_region(
                                    page_image=reg_img,
                                    form_box=fb_disp,
                                    bbox_format="display",
                                    page_number=page_num,
                                    page_width=float(geometry["width"]),
                                    page_height=float(geometry["height"]),
                                    source_rotation=int(geometry.get("rotation", 0) or 0),
                                    coords_in_unrotated_space=False,
                                    region_id=vf.get("region_id") or f"p{page_num}-form-vec{f_idx}",
                                    layout_label="form",
                                    pymupdf_page=pymupdf_page,
                                    source_asset_name=vf.get("source_asset_name") or f"pdf:page_{page_num}:form_vec_{f_idx}",
                                    pre_cropped_display_rect=fb_disp,
                                )
                                visual_regions.append(form_prov)
                                extracted_form_rects.append(
                                    (float(fb_disp[0]), float(fb_disp[1]), float(fb_disp[2]), float(fb_disp[3]))
                                )
                                if (form_prov.get("metadata") or {}).get("ocr_metadata", {}).get("ocr_triggered"):
                                    ocr_triggered = True
                        finally:
                            _close_image_quietly(reg_img)

                # Selective ON-DEMAND rendering/OCR ONLY for visual candidates on mixed-content pages
                if (
                    not layout_handled_visuals
                    and self.enable_visual_regions
                    and self.render_mixed_regions_on_demand
                    and classification == PDFPageClassification.MIXED_CONTENT
                    and candidates
                ):
                    for r_idx, cand in enumerate(candidates, start=1):
                        cb = cand.get("bbox_display") or []
                        if len(cb) >= 4 and (extracted_chart_rects or extracted_form_rects):
                            c_rect = (float(cb[0]), float(cb[1]), float(cb[2]), float(cb[3]))
                            if self._rect_overlaps_any(c_rect, extracted_chart_rects + extracted_form_rects, min_ratio=0.45):
                                continue

                        reg_img = None
                        try:
                            reg_img, method, r_warns = PyMuPDFPageRenderer.extract_or_render_region_image(
                                doc=doc,
                                page=pymupdf_page,
                                region_display_rect=cand["bbox_display"],
                                xref=cand.get("xref"),
                                dpi=self.limits.dpi or 300,
                                max_render_pixels=self.limits.max_render_pixels or 12_000_000,
                            )
                            page_warnings.extend(r_warns)
                            if reg_img is not None:
                                render_count += 1
                                region_clip_count += 1
                                pre_rect = cb if len(cb) >= 4 else None
                                if self.chart_extractor is not None:
                                    from .charts import is_likely_chart_raster_opencv

                                    if is_likely_chart_raster_opencv(reg_img):
                                        chart_prov = self.chart_extractor.extract_chart_region(
                                            page_image=reg_img,
                                            chart_box=cb if pre_rect is not None else None,
                                            bbox_format="display" if pre_rect is not None else "pixel",
                                            page_number=page_num,
                                            page_width=float(geometry["width"]),
                                            page_height=float(geometry["height"]),
                                            source_rotation=int(geometry.get("rotation", 0) or 0),
                                            coords_in_unrotated_space=False,
                                            region_id=f"p{page_num}-chart-ras{r_idx}",
                                            layout_label="chart",
                                            pymupdf_page=pymupdf_page,
                                            source_asset_name=f"pdf:page_{page_num}:region_{r_idx}",
                                            pre_cropped_display_rect=pre_rect,
                                        )
                                        visual_regions.append(chart_prov)
                                        if len(cb) >= 4:
                                            extracted_chart_rects.append(
                                                (float(cb[0]), float(cb[1]), float(cb[2]), float(cb[3]))
                                            )
                                        if (chart_prov.get("metadata") or {}).get("ocr_metadata", {}).get("ocr_triggered"):
                                            ocr_triggered = True
                                        continue

                                if self.form_extractor is not None:
                                    from .forms import is_likely_form_raster_opencv

                                    if is_likely_form_raster_opencv(reg_img):
                                        form_prov = self.form_extractor.extract_form_region(
                                            page_image=reg_img,
                                            form_box=cb if pre_rect is not None else None,
                                            bbox_format="display" if pre_rect is not None else "pixel",
                                            page_number=page_num,
                                            page_width=float(geometry["width"]),
                                            page_height=float(geometry["height"]),
                                            source_rotation=int(geometry.get("rotation", 0) or 0),
                                            coords_in_unrotated_space=False,
                                            region_id=f"p{page_num}-form-ras{r_idx}",
                                            layout_label="form",
                                            pymupdf_page=pymupdf_page,
                                            source_asset_name=f"pdf:page_{page_num}:region_{r_idx}",
                                            pre_cropped_display_rect=pre_rect,
                                        )
                                        visual_regions.append(form_prov)
                                        if len(cb) >= 4:
                                            extracted_form_rects.append(
                                                (float(cb[0]), float(cb[1]), float(cb[2]), float(cb[3]))
                                            )
                                        if (form_prov.get("metadata") or {}).get("ocr_metadata", {}).get("ocr_triggered"):
                                            ocr_triggered = True
                                        continue

                                if self.visual_provider is None and self.ocr_provider.is_available():
                                    ocr_triggered = True
                                cand_with_method = {**cand, "extraction_method": method}
                                reg_prov = self._run_region_ocr_or_visual(
                                    reg_img,
                                    cand_with_method,
                                    r_idx,
                                    geometry,
                                    page_warnings,
                                    policy_context=policy_context,
                                )
                                if reg_prov is not None:
                                    visual_regions.append(reg_prov)
                        finally:
                            _close_image_quietly(reg_img)

            elif classification == PDFPageClassification.SCANNED:
                # Scanned page: render ONLY this page at adaptive/300 DPI and release immediately after OCR
                raster_img = None
                try:
                    raster_img, eff_dpi, render_warns = PyMuPDFPageRenderer.render_page_image(
                        pymupdf_page,
                        dpi=self.limits.dpi or 300,
                        max_render_pixels=self.limits.max_render_pixels or 12_000_000,
                    )
                    page_warnings.extend(render_warns)

                    if raster_img is not None:
                        render_count += 1
                        layout_succeeded = False

                        if self.layout_provider is not None:
                            layout_succeeded = self._apply_layout_to_scanned_page(
                                raster_img=raster_img,
                                geometry=geometry,
                                baseline_page=baseline_page,
                                visual_regions=visual_regions,
                                provider_metrics=provider_metrics,
                                page_warnings=page_warnings,
                                extra_fallback_reasons=extra_fallback_reasons,
                                layout_telemetry=layout_telemetry,
                                policy_context=policy_context,
                                pymupdf_page=pymupdf_page,
                            )
                            if layout_succeeded and self.ocr_provider.is_available():
                                ocr_triggered = True

                        if not layout_succeeded:
                            ocr_triggered = True
                            ocr_res = self.ocr_provider.extract_image(raster_img)
                            if ocr_res.get("error_detail"):
                                page_warnings.append(str(ocr_res["error_detail"]))
                            if ocr_res.get("status") == "provider_unavailable":
                                page_warnings.append(
                                    "Tesseract OCR binary unavailable; scanned page degraded safely."
                                )

                            # Match exact OCRRouter fallback semantics for scanned pages
                            if ocr_res.get("status") == "provider_unavailable" and str(native_data.get("text", "")).strip():
                                eff_text = str(native_data["text"]).strip()
                                eff_conf = max(0.50, float(native_data.get("confidence", 0.0)))
                                eff_type = "digital_stream_preserved_ocr_skipped"
                                eff_boxes = list(native_data.get("bounding_boxes", []))
                                eff_repaired = bool(native_data.get("is_repaired", False))
                                eff_words = int(native_data.get("words_count", len(eff_text.split())))
                            else:
                                eff_text = str(ocr_res.get("text") or "").replace("\u00a0", " ")
                                if (
                                    eff_text
                                    and self.repair_bengali
                                    and not VisualPipelineIntegrationAdapter.is_ocr_placeholder_text(eff_text)
                                    and is_visual_encoded_document(eff_text)
                                ):
                                    eff_text = repair_visual_bengali_document(eff_text)
                                if (
                                    eff_text
                                    and self.convert_bangla_digits
                                    and not VisualPipelineIntegrationAdapter.is_ocr_placeholder_text(eff_text)
                                ):
                                    eff_text = bangla_to_arabic_digits(eff_text)
                                eff_conf = float(ocr_res.get("confidence", 0.0) or 0.0)
                                eff_type = (
                                    "ocr_tesseract"
                                    if ocr_res.get("status") != "provider_unavailable"
                                    else "scanned_ocr_unavailable"
                                )
                                eff_boxes = list(ocr_res.get("bounding_boxes") or [])
                                eff_repaired = ocr_res.get("status") == "success"
                                eff_words = int(ocr_res.get("words_count", len(eff_text.split())))

                            baseline_page = {
                                "page_number": page_num,
                                "text": eff_text,
                                "confidence": eff_conf,
                                "words_count": eff_words,
                                "width": pw,
                                "height": ph,
                                "extraction_type": eff_type,
                                "engine": _clamp_engine_str(ocr_res.get("engine", "none")),
                                "engine_version": _clamp_engine_str(ocr_res.get("engine_version", "none")),
                                "is_repaired": eff_repaired,
                                "needs_review": bool(ocr_res.get("needs_review", False)),
                                "status": str(ocr_res.get("status", "success")),
                                "language": ocr_res.get("language"),
                                "bounding_boxes": eff_boxes,
                            }
                            if ocr_res.get("is_optional_skipped") is not None:
                                baseline_page["is_optional_skipped"] = bool(ocr_res["is_optional_skipped"])

                            # Deterministic chart extraction on scanned pages when no layout provider ran
                            sc_chart_rects: List[Tuple[float, float, float, float]] = []
                            if self.enable_visual_regions and self.chart_extractor is not None:
                                from .charts import (
                                    detect_chart_candidates_in_pdf_page,
                                    detect_chart_regions_opencv,
                                    is_likely_chart_raster_opencv,
                                )

                                sc_rot = int(geometry.get("rotation", 0) or 0)
                                sc_vec_cands = detect_chart_candidates_in_pdf_page(
                                    pymupdf_page=pymupdf_page,
                                    page_number=page_num,
                                    table_rects_display=[],
                                )
                                for vc_idx, vc in enumerate(sc_vec_cands, start=1):
                                    vb_disp = vc["bbox_display"]
                                    chart_prov = self.chart_extractor.extract_chart_region(
                                        page_image=raster_img,
                                        chart_box=vb_disp,
                                        bbox_format="display",
                                        page_number=page_num,
                                        page_width=pw,
                                        page_height=ph,
                                        source_rotation=sc_rot,
                                        coords_in_unrotated_space=False,
                                        region_id=vc.get("region_id") or f"p{page_num}-chart-vec{vc_idx}",
                                        layout_label="chart",
                                        pymupdf_page=pymupdf_page,
                                        source_asset_name=vc.get("source_asset_name") or f"pdf:page_{page_num}:chart_vec_{vc_idx}",
                                    )
                                    visual_regions.append(chart_prov)
                                    sc_chart_rects.append(
                                        (float(vb_disp[0]), float(vb_disp[1]), float(vb_disp[2]), float(vb_disp[3]))
                                    )
                                    if (chart_prov.get("metadata") or {}).get("ocr_metadata", {}).get("ocr_triggered"):
                                        ocr_triggered = True

                                cv_boxes = list(detect_chart_regions_opencv(raster_img))
                                if not sc_vec_cands and not cv_boxes and is_likely_chart_raster_opencv(raster_img):
                                    cv_boxes = [(0.0, 0.0, float(raster_img.width), float(raster_img.height))]

                                sx_px = pw / max(float(raster_img.width), 1.0)
                                sy_px = ph / max(float(raster_img.height), 1.0)
                                for cv_idx, cv_box in enumerate(cv_boxes, start=1):
                                    dx0, dy0, dx1, dy1 = (
                                        cv_box[0] * sx_px,
                                        cv_box[1] * sy_px,
                                        cv_box[2] * sx_px,
                                        cv_box[3] * sy_px,
                                    )
                                    if sc_chart_rects and self._rect_overlaps_any((dx0, dy0, dx1, dy1), sc_chart_rects, min_ratio=0.40):
                                        continue
                                    chart_prov = self.chart_extractor.extract_chart_region(
                                        page_image=raster_img,
                                        chart_box=cv_box,
                                        bbox_format="pixel",
                                        page_number=page_num,
                                        page_width=pw,
                                        page_height=ph,
                                        source_rotation=sc_rot,
                                        coords_in_unrotated_space=False,
                                        region_id=f"p{page_num}-chart-cv{cv_idx}",
                                        layout_label="chart",
                                        pymupdf_page=pymupdf_page,
                                        source_asset_name=f"pdf:page_{page_num}:chart_cv_{cv_idx}",
                                    )
                                    visual_regions.append(chart_prov)
                                    sc_chart_rects.append((dx0, dy0, dx1, dy1))
                                    if (chart_prov.get("metadata") or {}).get("ocr_metadata", {}).get("ocr_triggered"):
                                        ocr_triggered = True

                            sc_form_rects: List[Tuple[float, float, float, float]] = []
                            if self.enable_visual_regions and self.form_extractor is not None:
                                from .forms import (
                                    detect_form_candidates_in_pdf_page,
                                    detect_form_regions_opencv,
                                    is_likely_form_raster_opencv,
                                )

                                sc_form_rot = int(geometry.get("rotation", 0) or 0)
                                ocr_hint = str(baseline_page.get("text") or "")
                                sc_vec_form_cands = detect_form_candidates_in_pdf_page(
                                    pymupdf_page=pymupdf_page,
                                    page_number=page_num,
                                    chart_rects_display=sc_chart_rects,
                                )
                                for vf_idx, vf in enumerate(sc_vec_form_cands, start=1):
                                    vb_disp = vf["bbox_display"]
                                    v_rect = (float(vb_disp[0]), float(vb_disp[1]), float(vb_disp[2]), float(vb_disp[3]))
                                    if sc_chart_rects and self._rect_overlaps_any(v_rect, sc_chart_rects, min_ratio=0.40):
                                        continue
                                    form_prov = self.form_extractor.extract_form_region(
                                        page_image=raster_img,
                                        form_box=vb_disp,
                                        bbox_format="display",
                                        page_number=page_num,
                                        page_width=pw,
                                        page_height=ph,
                                        source_rotation=sc_form_rot,
                                        coords_in_unrotated_space=False,
                                        region_id=vf.get("region_id") or f"p{page_num}-form-vec{vf_idx}",
                                        layout_label="form",
                                        pymupdf_page=pymupdf_page,
                                        source_asset_name=vf.get("source_asset_name") or f"pdf:page_{page_num}:form_vec_{vf_idx}",
                                    )
                                    visual_regions.append(form_prov)
                                    sc_form_rects.append(v_rect)
                                    if (form_prov.get("metadata") or {}).get("ocr_metadata", {}).get("ocr_triggered"):
                                        ocr_triggered = True

                                cv_form_boxes = list(detect_form_regions_opencv(raster_img, ocr_text_hint=ocr_hint))
                                if (
                                    not sc_vec_form_cands
                                    and not cv_form_boxes
                                    and not sc_chart_rects
                                    and is_likely_form_raster_opencv(raster_img, ocr_text_hint=ocr_hint)
                                ):
                                    cv_form_boxes = [(0.0, 0.0, float(raster_img.width), float(raster_img.height))]

                                sx_fpx = pw / max(float(raster_img.width), 1.0)
                                sy_fpx = ph / max(float(raster_img.height), 1.0)
                                for fv_idx, fv_box in enumerate(cv_form_boxes, start=1):
                                    fx0 = fv_box[0] * sx_fpx
                                    fy0 = fv_box[1] * sy_fpx
                                    fx1 = fv_box[2] * sx_fpx
                                    fy1 = fv_box[3] * sy_fpx
                                    if (sc_chart_rects or sc_form_rects) and self._rect_overlaps_any(
                                        (fx0, fy0, fx1, fy1), sc_chart_rects + sc_form_rects, min_ratio=0.40
                                    ):
                                        continue
                                    form_prov = self.form_extractor.extract_form_region(
                                        page_image=raster_img,
                                        form_box=fv_box,
                                        bbox_format="pixel",
                                        page_number=page_num,
                                        page_width=pw,
                                        page_height=ph,
                                        source_rotation=sc_form_rot,
                                        coords_in_unrotated_space=False,
                                        region_id=f"p{page_num}-form-cv{fv_idx}",
                                        layout_label="form",
                                        pymupdf_page=pymupdf_page,
                                        source_asset_name=f"pdf:page_{page_num}:form_cv_{fv_idx}",
                                    )
                                    visual_regions.append(form_prov)
                                    sc_form_rects.append((fx0, fy0, fx1, fy1))
                                    if (form_prov.get("metadata") or {}).get("ocr_metadata", {}).get("ocr_triggered"):
                                        ocr_triggered = True

                            # Analyze already-rendered raster via visual_provider if configured (no re-render)
                            if self.enable_visual_regions and self.visual_provider is not None:
                                vis_res = self.visual_provider.analyze_image(
                                    raster_img,
                                    context={
                                        "page_number": page_num,
                                        "source_asset_name": f"pdf:page_{page_num}",
                                        "execution_mode": (policy_context or {}).get("execution_mode"),
                                        "policy_context": policy_context or {},
                                    },
                                )
                                for vr in (vis_res.get("regions") or []):
                                    vr_type = str(vr.get("region_type") or "")
                                    vnb = vr.get("normalized_box")
                                    if (
                                        isinstance(vnb, (list, tuple))
                                        and len(vnb) == 4
                                        and pw > 0
                                        and ph > 0
                                    ):
                                        v_rect = (
                                            (float(vnb[1]) / 1000.0) * pw,
                                            (float(vnb[0]) / 1000.0) * ph,
                                            (float(vnb[3]) / 1000.0) * pw,
                                            (float(vnb[2]) / 1000.0) * ph,
                                        )
                                        if sc_chart_rects and vr_type == VisualRegionType.CHART.value:
                                            if self._rect_overlaps_any(v_rect, sc_chart_rects, min_ratio=0.35):
                                                continue
                                        if sc_form_rects and vr_type in (
                                            VisualRegionType.FORM_KV.value,
                                            VisualRegionType.SIGNATURE.value,
                                            VisualRegionType.FIGURE.value,
                                            VisualRegionType.UNKNOWN.value,
                                        ):
                                            if self._rect_overlaps_any(v_rect, sc_form_rects, min_ratio=0.45):
                                                continue
                                    visual_regions.append(vr)
                                if vis_res.get("metrics"):
                                    provider_metrics.append(vis_res["metrics"])
                    else:
                        baseline_page = {
                            "page_number": page_num,
                            "text": native_data["text"],
                            "confidence": native_data["confidence"],
                            "words_count": native_data["words_count"],
                            "width": pw,
                            "height": ph,
                            "extraction_type": "digital_pdf_fallback",
                            "engine": _clamp_engine_str(native_data.get("engine", "pymupdf")),
                            "engine_version": _clamp_engine_str(native_data.get("engine_version", PYMUPDF_VERSION)),
                            "is_repaired": False,
                            "needs_review": True,
                            "status": "render_failed",
                            "bounding_boxes": list(native_data.get("bounding_boxes", [])),
                        }
                finally:
                    _close_image_quietly(raster_img)

            else:
                # EMPTY page (zero native chars, zero images, zero significant drawings)
                page_warnings.append(f"Page {page_num} has no extractable text or visual content.")
                baseline_page = {
                    "page_number": page_num,
                    "text": "",
                    "confidence": 0.0,
                    "words_count": 0,
                    "width": pw,
                    "height": ph,
                    "extraction_type": "pdf_empty_page",
                    "engine": "pymupdf",
                    "engine_version": _clamp_engine_str(PYMUPDF_VERSION),
                    "is_repaired": False,
                    "needs_review": True,
                    "status": "empty_page",
                    "bounding_boxes": [],
                }

            # 4. Assemble canonical merged page preserving word boxes & OCR provenance
            eff_region_clips = int(locals().get("region_clip_count", 0) or 0)
            eff_full_renders = max(0, render_count - eff_region_clips)
            render_telemetry = {
                "full_page_renders": eff_full_renders,
                "region_clip_renders": eff_region_clips,
                "ocr_calls": 1 if ocr_triggered else 0,
            }
            merged: Dict[str, Any]
            if self.append_visual_text or not str(baseline_page.get("text") or "").strip():
                merged = cast(Dict[str, Any], VisualPipelineIntegrationAdapter.merge_baseline_and_visual_page(
                    baseline_page=baseline_page,
                    visual_regions=cast(Any, visual_regions if self.enable_visual_regions else []),
                    visual_metadata={
                        "provider_metrics": provider_metrics,
                        "render_telemetry": render_telemetry,
                    },
                    extra_fallback_reasons=extra_fallback_reasons,
                ))
            else:
                # Strict text-parity mode: attach visual_regions & telemetry without mutating baseline text
                merged = cast(Dict[str, Any], VisualPipelineIntegrationAdapter.merge_baseline_and_visual_page(
                    baseline_page=baseline_page,
                    visual_regions=[],
                    visual_metadata={
                        "provider_metrics": provider_metrics,
                        "render_telemetry": render_telemetry,
                    },
                    extra_fallback_reasons=extra_fallback_reasons,
                ))
                if self.enable_visual_regions and visual_regions:
                    merged["visual_regions"] = visual_regions
                    merged["visual_metadata"]["has_visual_content"] = True
                    merged["visual_metadata"]["visual_region_count"] = len(visual_regions)
                    vis_confs = [float(r.get("confidence", 0.0) or 0.0) for r in visual_regions]
                    merged["visual_metadata"]["visual_confidence"] = round(sum(vis_confs) / len(vis_confs), 4)
                    merged["visual_metadata"]["visual_engines"] = sorted(
                        {str(r.get("engine", "")) for r in visual_regions if r.get("engine")}
                    )

            # Preserve exact OCR metadata fields & attach additive geometry/warning provenance
            for preserve_key in ("needs_review", "status", "language", "is_optional_skipped"):
                if preserve_key in baseline_page and baseline_page[preserve_key] is not None:
                    merged[preserve_key] = baseline_page[preserve_key]

            for vr in visual_regions:
                vr_meta = vr.get("metadata") or {}
                vr_tbl_val = vr_meta.get("table_validation") or {}
                vr_cht_val = vr_meta.get("chart_validation") or {}
                vr_frm_val = vr_meta.get("form_validation") or {}
                needs_rev = bool(
                    vr_meta.get("needs_review")
                    or vr_meta.get("review_required")
                    or vr_tbl_val.get("needs_review")
                    or vr_cht_val.get("needs_review")
                    or vr_cht_val.get("review_required")
                    or vr_frm_val.get("needs_review")
                    or vr_frm_val.get("review_required")
                )
                if needs_rev:
                    merged["needs_review"] = True
                    if (
                        vr_meta.get("review_required")
                        or vr_cht_val.get("review_required")
                        or vr_frm_val.get("review_required")
                    ):
                        merged["review_required"] = True
                    codes = (
                        list(vr_tbl_val.get("issue_codes") or [])
                        + list(vr_cht_val.get("issue_codes") or [])
                        + list(vr_frm_val.get("issue_codes") or [])
                    )
                    if codes:
                        page_warnings.append(
                            f"Page {page_num} region {vr.get('region_id', 'table')} flagged for review ({', '.join(codes)})."
                        )

            merged["rotation"] = rotation
            merged["page_classification"] = classification.value
            merged["warnings"] = list(dict.fromkeys(page_warnings))
            merged["visual_metadata"]["page_classification"] = classification.value
            merged["visual_metadata"]["rotation"] = rotation
            merged["visual_metadata"]["ocr_triggered"] = ocr_triggered
            merged["visual_metadata"]["render_count"] = render_count
            merged["visual_metadata"]["warnings"] = merged["warnings"]
            merged["visual_metadata"]["geometry"] = {
                "mediabox": geometry["mediabox"],
                "cropbox": geometry["cropbox"],
                "display_rect": geometry["display_rect"],
                "rotation": rotation,
            }
            if layout_telemetry:
                merged["visual_metadata"].update(layout_telemetry)
            merged["visual_metadata"]["render_telemetry"] = render_telemetry
            if getattr(self.ocr_provider, "lang", None) and "language" not in merged:
                merged["language"] = self.ocr_provider.lang

            VisualPipelineIntegrationAdapter.validate_page_payload(merged, strict=True)
            return merged
        finally:
            pymupdf_page = None
            gc.collect()

    def process_pdf(
        self,
        file_path_or_bytes: Any,
        max_pages: Optional[int] = None,
        password: Optional[str] = None,
        policy_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Inspects and extracts a PDF page-by-page using PyMuPDF + existing
        LORE native extraction and ``TesseractOCRProvider``.
        """
        from .runtime import (
            GLOBAL_VISUAL_METRICS,
            configure_visual_cpu_runtime,
            measure_memory_and_duration,
        )

        configure_visual_cpu_runtime()
        self.last_run_diagnostics = {}
        run_failed = False
        err_msg: Optional[str] = None
        pages_result: List[Dict[str, Any]] = []
        mem_stats: Dict[str, Any] = {
            "duration_ms": 0.0,
            "rss_before_mb": None,
            "rss_after_mb": None,
            "rss_delta_mb": None,
            "peak_rss_mb": None,
            "tracemalloc_peak_mb": None,
        }
        try:
            with measure_memory_and_duration(enable_tracemalloc=True) as mem_stats:
                pages_result = self._process_pdf_core(
                    file_path_or_bytes,
                    max_pages=max_pages,
                    password=password,
                    policy_context=policy_context,
                )
        except Exception as exc:
            run_failed = True
            err_msg = sanitize_sensitive_data(str(exc))
            raise
        finally:
            diag = dict(self.last_run_diagnostics or {})
            diag.update({
                "duration_ms": mem_stats["duration_ms"],
                "rss_before_mb": mem_stats["rss_before_mb"],
                "rss_after_mb": mem_stats["rss_after_mb"],
                "rss_delta_mb": mem_stats["rss_delta_mb"],
                "peak_rss_mb": mem_stats["peak_rss_mb"],
                "tracemalloc_peak_mb": mem_stats["tracemalloc_peak_mb"],
            })
            self.last_run_diagnostics = diag
            diag_status = str(diag.get("status") or "")
            is_failed = run_failed or diag_status in {
                "encrypted_pdf",
                "malformed_pdf",
                "oversized_pdf",
                "empty_pdf",
            }
            GLOBAL_VISUAL_METRICS.record_run(
                duration_ms=mem_stats["duration_ms"],
                pages_processed=int(diag.get("page_count", len(pages_result)) or 0),
                full_page_renders=int(diag.get("full_page_renders", 0) or 0),
                region_clip_renders=int(diag.get("region_clip_renders", 0) or 0),
                ocr_calls=int(diag.get("ocr_calls", 0) or 0),
                partial_failure_pages=int(diag.get("partial_failure_pages", 0) or 0),
                failed=is_failed,
                rss_before_mb=mem_stats["rss_before_mb"],
                rss_after_mb=mem_stats["rss_after_mb"],
                peak_rss_mb=mem_stats["peak_rss_mb"],
                tracemalloc_peak_mb=mem_stats["tracemalloc_peak_mb"],
                stage_timings_ms=diag.get("stage_timings_ms"),
                dpi=(self.limits.dpi or 300),
                error_reason=err_msg or (diag_status if is_failed else None),
            )
        return pages_result

    def _process_pdf_core(
        self,
        file_path_or_bytes: Any,
        max_pages: Optional[int] = None,
        password: Optional[str] = None,
        policy_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        t0 = time.time()
        eff_max_pages = max_pages if max_pages is not None else self.limits.max_pages

        pdf_bytes, err_kind, input_warnings = _materialize_pdf_input(
            file_path_or_bytes, max_file_bytes=self.limits.max_file_bytes
        )
        if err_kind == "empty":
            self.last_run_diagnostics = {"status": "empty_pdf", "warnings": input_warnings}
            return []
        if err_kind == "oversized":
            self.last_run_diagnostics = {"status": "oversized_pdf", "warnings": input_warnings}
            return [self._build_diagnostic_page(
                extraction_type="pdf_oversized",
                status="oversized_pdf",
                classification=PDFPageClassification.OVERSIZED,
                warnings=input_warnings,
            )]
        if err_kind == "malformed" or pdf_bytes is None:
            self.last_run_diagnostics = {"status": "malformed_pdf", "warnings": input_warnings}
            return [self._build_diagnostic_page(
                extraction_type="pdf_malformed",
                status="malformed_pdf",
                classification=PDFPageClassification.MALFORMED,
                warnings=input_warnings,
            )]

        if not HAS_PYMUPDF or pymupdf is None:
            fallback_warnings = input_warnings + [
                "PyMuPDF not installed; gracefully falling back to OCRRouter."
            ]
            return self._run_ocr_router_fallback(
                pdf_bytes=pdf_bytes,
                max_pages=eff_max_pages,
                reason=VisualFallbackReason.VISUAL_PROVIDER_UNAVAILABLE,
                warnings=fallback_warnings,
            )

        doc = None
        pages_out: List[Dict[str, Any]] = []
        run_warnings: List[str] = list(input_warnings)

        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            err_msg = f"Malformed PDF stream could not be opened: {sanitize_sensitive_data(str(exc))}"
            logger.warning(err_msg)
            run_warnings.append(err_msg)
            self.last_run_diagnostics = {"status": "malformed_pdf", "warnings": run_warnings}
            return [self._build_diagnostic_page(
                extraction_type="pdf_malformed",
                status="malformed_pdf",
                classification=PDFPageClassification.MALFORMED,
                warnings=run_warnings,
            )]

        try:
            if getattr(doc, "is_encrypted", False) and getattr(doc, "needs_pass", False):
                authed = False
                if password:
                    try:
                        authed = bool(doc.authenticate(password))
                    except Exception:
                        authed = False
                if not authed:
                    warn = "Encrypted PDF requires valid user password; extraction halted safely."
                    run_warnings.append(warn)
                    self.last_run_diagnostics = {"status": "encrypted_pdf", "warnings": run_warnings}
                    return [self._build_diagnostic_page(
                        extraction_type="pdf_encrypted",
                        status="encrypted_pdf",
                        classification=PDFPageClassification.ENCRYPTED,
                        warnings=run_warnings,
                    )]

            total_doc_pages = int(doc.page_count)
            if total_doc_pages <= 0:
                run_warnings.append("PDF opened cleanly but contains 0 pages.")
                self.last_run_diagnostics = {"status": "empty_pdf", "warnings": run_warnings}
                return []

            total_pages = min(total_doc_pages, max(1, eff_max_pages))
            if total_doc_pages > total_pages:
                run_warnings.append(
                    f"PDF page limit applied: processed {total_pages} of {total_doc_pages} pages."
                )

            plumber_cm = nullcontext(None)
            if self.prefer_existing_native and HAS_PDFPLUMBER:
                try:
                    plumber_cm = pdfplumber.open(io.BytesIO(pdf_bytes))
                except Exception as exc:
                    run_warnings.append(
                        f"pdfplumber secondary native handle skipped: {sanitize_sensitive_data(str(exc))}"
                    )
                    plumber_cm = nullcontext(None)

            page_failure_count = 0
            total_full_renders = 0
            total_region_renders = 0
            total_ocr_calls = 0
            stage_totals: Dict[str, float] = {}

            with plumber_cm as plumber_pdf:
                for idx in range(total_pages):
                    try:
                        page_res = self._process_single_page(
                            doc, idx, plumber_pdf, policy_context=policy_context
                        )
                    except Exception as page_exc:
                        err = (
                            f"Page {idx + 1} extraction failed gracefully: "
                            f"{sanitize_sensitive_data(str(page_exc))}"
                        )
                        logger.warning(err)
                        page_res = self._build_diagnostic_page(
                            page_number=idx + 1,
                            extraction_type="pdf_malformed",
                            status="page_error",
                            classification=PDFPageClassification.MALFORMED,
                            warnings=[err],
                        )
                        page_failure_count += 1
                    if run_warnings:
                        merged_warns = list(dict.fromkeys(list(page_res.get("warnings") or []) + run_warnings))
                        page_res["warnings"] = merged_warns
                        page_res["visual_metadata"]["warnings"] = merged_warns

                    rt = page_res.get("visual_metadata", {}).get("render_telemetry") or {}
                    p_full = int(rt.get("full_page_renders", 0) or 0)
                    p_reg = int(rt.get("region_clip_renders", 0) or 0)
                    total_full_renders += p_full
                    total_region_renders += p_reg
                    total_ocr_calls += int(rt.get("ocr_calls", 0) or 0)
                    for st_k, st_v in (rt.get("stage_timings_ms") or {}).items():
                        stage_totals[st_k] = round(stage_totals.get(st_k, 0.0) + float(st_v), 2)
                    if page_res.get("status") == "page_error":
                        page_failure_count = max(page_failure_count, 1)
                    pages_out.append(page_res)

            if pages_out and any(
                r.get("region_type") == VisualRegionType.TABLE.value
                for p in pages_out
                for r in (p.get("visual_regions") or [])
            ):
                from .tables import link_multipage_tables

                link_multipage_tables(pages_out)

            elapsed_ms = round((time.time() - t0) * 1000.0, 2)
            for p in pages_out:
                p["visual_metadata"]["visual_timings_ms"] = elapsed_ms
                p["visual_metadata"]["warnings"] = list(dict.fromkeys(p.get("warnings") or []))

            self.last_run_diagnostics = {
                "status": "completed",
                "page_count": len(pages_out),
                "total_doc_pages": total_doc_pages,
                "elapsed_ms": elapsed_ms,
                "dpi": (self.limits.dpi or 300),
                "full_page_renders": total_full_renders,
                "region_clip_renders": total_region_renders,
                "ocr_calls": total_ocr_calls,
                "partial_failure_pages": page_failure_count,
                "stage_timings_ms": stage_totals,
                "warnings": run_warnings,
            }
            return pages_out
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

    def process_image(self, file_path_or_bytes: Any) -> List[Dict[str, Any]]:
        """Maintains full OCRRouterProtocol compatibility for single raster images."""
        return self.fallback_router.process_image(file_path_or_bytes)

    def enrich_page(
        self,
        page_data: Dict[str, Any],
        page_image: Optional[Image.Image] = None,
        raw_file: Any = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Implements ``VisualExtensionHookProtocol`` so existing extractors can opt into
        visual page enrichment without duplicating file reads.
        """
        page_num = int(page_data.get("page_number", 1))
        if raw_file is not None and str((context or {}).get("doc_type", "")).lower() == "pdf":
            pdf_pages = self.process_pdf(raw_file, max_pages=max(page_num, 1))
            for candidate in pdf_pages:
                if int(candidate.get("page_number", 0)) == page_num:
                    return candidate

        if page_image is not None and self.visual_provider is not None:
            vis_res = self.visual_provider.analyze_image(page_image, context={"page_number": page_num})
            return cast(Dict[str, Any], VisualPipelineIntegrationAdapter.merge_baseline_and_visual_page(
                baseline_page=page_data,
                visual_regions=vis_res.get("regions") or [],
            ))

        return cast(Dict[str, Any], VisualPipelineIntegrationAdapter.merge_baseline_and_visual_page(
            baseline_page=page_data,
            visual_regions=list(page_data.get("visual_regions") or []),
        ))
