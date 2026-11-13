"""
LORE Enterprise — Optional CPU Document Layout Detection (PP-DocLayout-S)
========================================================================

Integrates ``PP-DocLayout-S`` (via ``paddleocr.LayoutDetection`` / PaddlePaddle)
as an optional CPU-based layout detection provider inside ``apps.ingestion.pipeline``.

Verified Artifact & Runtime Specification:
- Model identifier: ``PP-DocLayout-S`` (PicoDet-S backbone, ~4.83 MB, 23 classes)
- Official artifacts: Hugging Face ``PaddlePaddle/PP-DocLayout-S`` and PaddleX
  inference archive ``PP-DocLayout-S_infer.tar``
- Package requirements: ``paddleocr>=3.0.0`` + ``paddlepaddle>=3.0.0`` (CPU build)
- License: Apache License 2.0 (``Apache-2.0``)
- Runtime compatibility: CPU execution (x86_64 AVX recommended), Python 3.9-3.13
  with prebuilt binary wheels (aligns with container ``python:3.12-slim``); degrades
  gracefully to LORE's deterministic/OCR pipeline when unavailable or on error.

Architectural Isolation Guarantee:
- Emits structural layout regions, normalized coordinates, reading order, and
  per-region extraction routing metadata only.
- NEVER alters document authority, approval state, permissions, or evidence
  sufficiency verdicts (strictly downstream Governance L0-L7 / Settlement S1-S6).
"""

from __future__ import annotations

import inspect
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from PIL import Image

from apps.governance.modes import ModelExecutionMetric, ModelTaskPurpose, sanitize_sensitive_data

from .contracts import (
    VisualPipelineIntegrationAdapter,
    build_visual_region_provenance,
    rect_to_normalized_box,
    validate_normalized_box,
)
from .ocr import (
    BaseOCRProvider,
    ImagePreprocessor,
    TesseractOCRProvider,
)
from .visual import (
    BaseVisualProvider,
    VisualExtractionKind,
    VisualRegionType,
    _pad_for_ocr_if_needed,
    apply_text_normalization,
    crop_image_safe,
    format_markdown_table,
    format_visual_region_markdown,
)

logger = logging.getLogger(__name__)

# Optional NumPy array bridge for BGR OpenCV/PaddleX ndarray input
try:
    import numpy as np  # type: ignore

    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore
    HAS_NUMPY = False

# Optional PaddlePaddle / PaddleOCR runtime detection
try:
    import paddle  # type: ignore

    HAS_PADDLEPADDLE = True
    PADDLEPADDLE_VERSION = str(getattr(paddle, "__version__", "unknown"))
except ImportError:
    paddle = None  # type: ignore
    HAS_PADDLEPADDLE = False
    PADDLEPADDLE_VERSION = "unavailable"

try:
    from paddleocr import LayoutDetection as _PaddleOCRLayoutDetection  # type: ignore
    import paddleocr as _paddleocr_pkg  # type: ignore

    HAS_PADDLEOCR_LAYOUT = True
    PADDLEOCR_VERSION = str(getattr(_paddleocr_pkg, "__version__", "unknown"))
except ImportError:
    _PaddleOCRLayoutDetection = None  # type: ignore
    HAS_PADDLEOCR_LAYOUT = False
    PADDLEOCR_VERSION = "unavailable"


# ==============================================================================
# VERIFIED PP-DOCLAYOUT-S ARTIFACT METADATA & 23 OFFICIAL CLASSES
# ==============================================================================
PP_DOCLAYOUT_S_MODEL_NAME = "PP-DocLayout-S"
PP_DOCLAYOUT_S_BACKBONE = "PicoDet-S"
PP_DOCLAYOUT_S_LICENSE = "Apache-2.0"
PP_DOCLAYOUT_S_HF_REPO = "PaddlePaddle/PP-DocLayout-S"
PP_DOCLAYOUT_S_INFERENCE_ARCHIVE = "PP-DocLayout-S_infer.tar"
PP_DOCLAYOUT_S_BCEBOS_URL = (
    "https://paddle-model-ecology.bj.bcebos.com/"
    "paddlex/official_inference_model/paddle3.0.0/PP-DocLayout-S_infer.tar"
)
PP_DOCLAYOUT_S_MIN_PADDLEOCR_VERSION = "3.0.0"
PP_DOCLAYOUT_S_MIN_PADDLEPADDLE_VERSION = "3.0.0"
PP_DOCLAYOUT_S_SUPPORTED_PYTHON = ">=3.9,<3.14"
PP_DOCLAYOUT_S_INPUT_SIZE: Tuple[int, int] = (480, 480)

# Exact 23 layout classes defined in PP-DocLayout-S inference.yml (ID order 0..22)
PP_DOCLAYOUT_S_LABEL_LIST: Tuple[str, ...] = (
    "paragraph_title",
    "image",
    "text",
    "number",
    "abstract",
    "content",
    "figure_title",
    "formula",
    "table",
    "table_title",
    "reference",
    "doc_title",
    "footnote",
    "header",
    "algorithm",
    "footer",
    "seal",
    "chart_title",
    "chart",
    "formula_number",
    "header_image",
    "footer_image",
    "aside_text",
)

PP_DOCLAYOUT_S_ARTIFACT_METADATA: Dict[str, Any] = {
    "model_name": PP_DOCLAYOUT_S_MODEL_NAME,
    "backbone": PP_DOCLAYOUT_S_BACKBONE,
    "license": PP_DOCLAYOUT_S_LICENSE,
    "huggingface_repo": PP_DOCLAYOUT_S_HF_REPO,
    "inference_archive": PP_DOCLAYOUT_S_INFERENCE_ARCHIVE,
    "bcebos_url": PP_DOCLAYOUT_S_BCEBOS_URL,
    "min_paddleocr_version": PP_DOCLAYOUT_S_MIN_PADDLEOCR_VERSION,
    "min_paddlepaddle_version": PP_DOCLAYOUT_S_MIN_PADDLEPADDLE_VERSION,
    "supported_python": PP_DOCLAYOUT_S_SUPPORTED_PYTHON,
    "input_size": PP_DOCLAYOUT_S_INPUT_SIZE,
    "num_classes": len(PP_DOCLAYOUT_S_LABEL_LIST),
    "labels": PP_DOCLAYOUT_S_LABEL_LIST,
}


# ==============================================================================
# CANONICAL LAYOUT TAXONOMY & EXTRACTOR ROUTING
# ==============================================================================
class LayoutCategory(str, Enum):
    """Normalized 8-class layout taxonomy required across LORE Visual Extraction."""

    TITLE_HEADING = "title_heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    CHART = "chart"
    FIGURE_IMAGE = "figure_image"
    FORM = "form"
    HEADER_FOOTER = "header_footer"
    UNKNOWN = "unknown"


class LayoutExtractorRoute(str, Enum):
    """Downstream extraction handler selected for each layout category."""

    HEADING_TEXT_OR_OCR = "heading_text_or_ocr"
    BODY_TEXT_OR_OCR = "body_text_or_ocr"
    TABLE_EXTRACTOR = "table_extractor"
    CHART_VISUAL_EXTRACTOR = "chart_visual_extractor"
    FIGURE_VISUAL_EXTRACTOR = "figure_visual_extractor"
    FORM_KV_EXTRACTOR = "form_kv_extractor"
    HEADER_FOOTER_EXTRACTOR = "header_footer_extractor"
    UNKNOWN_FALLBACK_OCR = "unknown_fallback_ocr"


CATEGORY_TO_VISUAL_REGION_TYPE: Dict[LayoutCategory, VisualRegionType] = {
    LayoutCategory.TITLE_HEADING: VisualRegionType.TITLE_HEADING,
    LayoutCategory.PARAGRAPH: VisualRegionType.PARAGRAPH,
    LayoutCategory.TABLE: VisualRegionType.TABLE,
    LayoutCategory.CHART: VisualRegionType.CHART,
    LayoutCategory.FIGURE_IMAGE: VisualRegionType.FIGURE,
    LayoutCategory.FORM: VisualRegionType.FORM_KV,
    LayoutCategory.HEADER_FOOTER: VisualRegionType.HEADER_FOOTER,
    LayoutCategory.UNKNOWN: VisualRegionType.UNKNOWN,
}

CATEGORY_TO_ROUTE: Dict[LayoutCategory, LayoutExtractorRoute] = {
    LayoutCategory.TITLE_HEADING: LayoutExtractorRoute.HEADING_TEXT_OR_OCR,
    LayoutCategory.PARAGRAPH: LayoutExtractorRoute.BODY_TEXT_OR_OCR,
    LayoutCategory.TABLE: LayoutExtractorRoute.TABLE_EXTRACTOR,
    LayoutCategory.CHART: LayoutExtractorRoute.CHART_VISUAL_EXTRACTOR,
    LayoutCategory.FIGURE_IMAGE: LayoutExtractorRoute.FIGURE_VISUAL_EXTRACTOR,
    LayoutCategory.FORM: LayoutExtractorRoute.FORM_KV_EXTRACTOR,
    LayoutCategory.HEADER_FOOTER: LayoutExtractorRoute.HEADER_FOOTER_EXTRACTOR,
    LayoutCategory.UNKNOWN: LayoutExtractorRoute.UNKNOWN_FALLBACK_OCR,
}

# Explicit mapping from PP-DocLayout-S 23 labels + common aliases -> LayoutCategory
PP_DOCLAYOUT_S_LABEL_MAP: Dict[str, LayoutCategory] = {
    # Titles and headings
    "doc_title": LayoutCategory.TITLE_HEADING,
    "paragraph_title": LayoutCategory.TITLE_HEADING,
    "table_title": LayoutCategory.TITLE_HEADING,
    "figure_title": LayoutCategory.TITLE_HEADING,
    "chart_title": LayoutCategory.TITLE_HEADING,
    "title": LayoutCategory.TITLE_HEADING,
    "heading": LayoutCategory.TITLE_HEADING,
    "section_title": LayoutCategory.TITLE_HEADING,
    # Paragraphs & narrative text structures
    "text": LayoutCategory.PARAGRAPH,
    "paragraph": LayoutCategory.PARAGRAPH,
    "abstract": LayoutCategory.PARAGRAPH,
    "content": LayoutCategory.PARAGRAPH,
    "reference": LayoutCategory.PARAGRAPH,
    "footnote": LayoutCategory.PARAGRAPH,
    "aside_text": LayoutCategory.PARAGRAPH,
    "sidebar_text": LayoutCategory.PARAGRAPH,
    "algorithm": LayoutCategory.PARAGRAPH,
    "formula": LayoutCategory.PARAGRAPH,
    "formula_number": LayoutCategory.PARAGRAPH,
    # Tables
    "table": LayoutCategory.TABLE,
    # Charts
    "chart": LayoutCategory.CHART,
    "diagram": LayoutCategory.CHART,
    "plot": LayoutCategory.CHART,
    "graph": LayoutCategory.CHART,
    # Figures and images
    "image": LayoutCategory.FIGURE_IMAGE,
    "figure": LayoutCategory.FIGURE_IMAGE,
    "embedded_image": LayoutCategory.FIGURE_IMAGE,
    "svg_graphic": LayoutCategory.FIGURE_IMAGE,
    "photo": LayoutCategory.FIGURE_IMAGE,
    # Forms & official stamps/signatures
    "form": LayoutCategory.FORM,
    "form_kv": LayoutCategory.FORM,
    "key_value": LayoutCategory.FORM,
    "form_field": LayoutCategory.FORM,
    "checkbox": LayoutCategory.FORM,
    "signature": LayoutCategory.FORM,
    "seal": LayoutCategory.FORM,
    "stamp_or_seal": LayoutCategory.FORM,
    # Headers and footers
    "header": LayoutCategory.HEADER_FOOTER,
    "footer": LayoutCategory.HEADER_FOOTER,
    "header_image": LayoutCategory.HEADER_FOOTER,
    "footer_image": LayoutCategory.HEADER_FOOTER,
    "number": LayoutCategory.HEADER_FOOTER,
    "page_number": LayoutCategory.HEADER_FOOTER,
    # Explicit unknown markers
    "unknown": LayoutCategory.UNKNOWN,
    "other": LayoutCategory.UNKNOWN,
}

# Structural precedence used only to break ties on heavily overlapping duplicates
_CATEGORY_DEDUP_PRIORITY: Dict[LayoutCategory, int] = {
    LayoutCategory.TABLE: 8,
    LayoutCategory.CHART: 7,
    LayoutCategory.FORM: 6,
    LayoutCategory.FIGURE_IMAGE: 5,
    LayoutCategory.TITLE_HEADING: 4,
    LayoutCategory.PARAGRAPH: 3,
    LayoutCategory.HEADER_FOOTER: 2,
    LayoutCategory.UNKNOWN: 1,
}

_FORM_KV_LINE_RE = re.compile(
    r"^\s*([A-Za-z\u0980-\u09FF][A-Za-z0-9\u0980-\u09FF _/().#-]{1,34})\s*[:：]\s*(.+?)\s*$"
)
_FORM_CHECKBOX_RE = re.compile(r"(?:^|\s)(?:\[\s*[xX✓✔]?\s*\]|[☐☑☒])\s+\S+")


def _normalize_raw_label(label: Any) -> str:
    return re.sub(r"[\s\-]+", "_", str(label or "").strip().lower()).strip("_")


def classify_layout_label(raw_label: Any, cls_id: Optional[int] = None) -> Tuple[LayoutCategory, str]:
    """
    Maps a PP-DocLayout-S label (or class ID) to one of the 8 canonical categories.
    Unrecognized labels deterministically resolve to ``LayoutCategory.UNKNOWN``
    instead of being discarded.
    """
    norm = _normalize_raw_label(raw_label)
    if not norm and cls_id is not None:
        try:
            idx = int(cls_id)
            if 0 <= idx < len(PP_DOCLAYOUT_S_LABEL_LIST):
                norm = PP_DOCLAYOUT_S_LABEL_LIST[idx]
        except (TypeError, ValueError):
            norm = ""

    if norm in PP_DOCLAYOUT_S_LABEL_MAP:
        return PP_DOCLAYOUT_S_LABEL_MAP[norm], norm
    return LayoutCategory.UNKNOWN, (norm or "unknown")


def is_form_kv_text(text: str) -> bool:
    """
    Conservative structural detector for Key: Value / checkbox form blocks inside
    a localized region without misclassifying narrative prose or URLs.
    """
    if not text or not text.strip():
        return False
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False

    kv_hits = 0
    checkbox_hits = 0
    for ln in lines:
        low = ln.lower()
        if "http://" in low or "https://" in low:
            continue
        if _FORM_CHECKBOX_RE.search(ln):
            checkbox_hits += 1
        m = _FORM_KV_LINE_RE.match(ln)
        if m:
            key_part = m.group(1).strip()
            if len(key_part.split()) <= 5:
                kv_hits += 1
    return kv_hits >= 2 or (kv_hits >= 1 and checkbox_hits >= 1) or checkbox_hits >= 2


def extract_form_kv_pairs(text: str) -> List[Dict[str, str]]:
    """Extracts deterministic key-value entries from a form region without invention."""
    pairs: List[Dict[str, str]] = []
    if not text:
        return pairs
    for ln in text.splitlines():
        clean_ln = ln.strip()
        if not clean_ln or "http://" in clean_ln.lower() or "https://" in clean_ln.lower():
            continue
        m = _FORM_KV_LINE_RE.match(clean_ln)
        if m:
            k = m.group(1).strip()
            v = m.group(2).strip()
            if len(k.split()) <= 5:
                pairs.append({"field": k, "value": v})
    return pairs


def _resolve_header_footer_role(raw_label: str, normalized_box: Sequence[int]) -> str:
    norm = _normalize_raw_label(raw_label)
    if norm in ("header", "header_image"):
        return "header"
    if norm in ("footer", "footer_image"):
        return "footer"
    if norm in ("number", "page_number"):
        ymin = int(normalized_box[0]) if normalized_box else 500
        return "header" if ymin <= 220 else "footer"
    ymin = int(normalized_box[0]) if normalized_box else 500
    return "header" if ymin <= 300 else "footer"


# ==============================================================================
# ROTATION & CANONICAL COORDINATE GEOMETRY HELPERS
# ==============================================================================
def transform_box_for_rotation(
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
    src_width: float,
    src_height: float,
    rotation_cw_degrees: int,
) -> Tuple[Tuple[float, float, float, float], Tuple[float, float]]:
    """
    Transforms an unrotated rectangle ``(xmin, ymin, xmax, ymax)`` into upright
    display coordinates after clockwise rotation by ``0 | 90 | 180 | 270`` degrees.
    Matches PIL transpose / PyMuPDF ``page.rotation_matrix`` convention.
    """
    deg = int(rotation_cw_degrees or 0) % 360
    x0, x1 = min(float(xmin), float(xmax)), max(float(xmin), float(xmax))
    y0, y1 = min(float(ymin), float(ymax)), max(float(ymin), float(ymax))
    w = max(float(src_width or 1.0), 1.0)
    h = max(float(src_height or 1.0), 1.0)

    if deg == 90:
        box = (h - y1, x0, h - y0, x1)
        dims = (h, w)
    elif deg == 180:
        box = (w - x1, h - y1, w - x0, h - y0)
        dims = (w, h)
    elif deg == 270:
        box = (y0, w - x1, y1, w - x0)
        dims = (h, w)
    else:
        box = (x0, y0, x1, y1)
        dims = (w, h)

    clamped = (
        max(0.0, min(dims[0], box[0])),
        max(0.0, min(dims[1], box[1])),
        max(0.0, min(dims[0], box[2])),
        max(0.0, min(dims[1], box[3])),
    )
    nx0, ny0 = min(clamped[0], clamped[2]), min(clamped[1], clamped[3])
    nx1, ny1 = max(clamped[0], clamped[2]), max(clamped[1], clamped[3])
    return (nx0, ny0, nx1, ny1), dims


def compute_iou(box_a: Sequence[float], box_b: Sequence[float]) -> float:
    """Computes Intersection-over-Union for ``[xmin, ymin, xmax, ymax]`` boxes."""
    ax0, ay0, ax1, ay1 = float(box_a[0]), float(box_a[1]), float(box_a[2]), float(box_a[3])
    bx0, by0, bx1, by1 = float(box_b[0]), float(box_b[1]), float(box_b[2]), float(box_b[3])

    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = (area_a + area_b) - inter
    return (inter / union) if union > 0.0 else 0.0


def compute_containment(inner_or_a: Sequence[float], outer_or_b: Sequence[float]) -> float:
    """Returns intersection / area_of_smaller_box in ``[0.0, 1.0]``."""
    ax0, ay0, ax1, ay1 = [float(v) for v in inner_or_a[:4]]
    bx0, by0, bx1, by1 = [float(v) for v in outer_or_b[:4]]
    inter = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    smallest = min(area_a, area_b)
    return (inter / smallest) if smallest > 0.0 else 0.0


def _norm_box_to_xyxy(norm_box: Sequence[int]) -> Tuple[int, int, int, int]:
    """Converts canonical [ymin, xmin, ymax, xmax] -> [xmin, ymin, xmax, ymax]."""
    return (int(norm_box[1]), int(norm_box[0]), int(norm_box[3]), int(norm_box[2]))


# ==============================================================================
# DUPLICATE SUPPRESSION & MULTI-COLUMN READING-ORDER SORTER
# ==============================================================================
def deduplicate_layout_regions(
    detections: Sequence[Mapping[str, Any]],
    same_class_iou_threshold: float = 0.55,
    cross_class_iou_threshold: float = 0.65,
    containment_threshold: float = 0.82,
) -> List[Dict[str, Any]]:
    """
    Suppresses overlapping duplicate detections so the same document region is
    never extracted twice:
    1. Same-category overlaps (IoU >= ``same_class_iou_threshold`` or high
       containment): keeps higher score (ties broken by larger area).
    2. Cross-category overlaps:
       - Suppresses ``paragraph`` / ``title_heading`` / ``unknown`` nested
         inside an already-detected ``table``, ``chart``, or ``form`` container
         (while preserving table/figure/chart titles positioned OUTSIDE containers).
       - Suppresses identical-box cross-class duplicates (IoU >= ``cross_class_iou_threshold``)
         preferring higher structural precedence (table > chart > form > figure_image > ...).
    """
    if not detections:
        return []

    def _area(d: Mapping[str, Any]) -> float:
        nb = d.get("normalized_box") or [0, 0, 0, 0]
        return float(max(1, int(nb[2]) - int(nb[0])) * max(1, int(nb[3]) - int(nb[1])))

    def _sort_key(d: Mapping[str, Any]) -> Tuple[int, float, float]:
        cat_val = d.get("layout_category", LayoutCategory.UNKNOWN.value)
        try:
            cat_enum = LayoutCategory(cat_val)
        except ValueError:
            cat_enum = LayoutCategory.UNKNOWN
        return (
            _CATEGORY_DEDUP_PRIORITY.get(cat_enum, 1),
            float(d.get("score", 0.0) or 0.0),
            _area(d),
        )

    ranked = sorted((dict(item) for item in detections), key=_sort_key, reverse=True)
    kept: List[Dict[str, Any]] = []

    for cand in ranked:
        cand_xyxy = _norm_box_to_xyxy(cand["normalized_box"])
        cand_cat = str(cand.get("layout_category", LayoutCategory.UNKNOWN.value))
        cand_area = _area(cand)
        is_duplicate = False

        for prev in kept:
            prev_xyxy = _norm_box_to_xyxy(prev["normalized_box"])
            prev_cat = str(prev.get("layout_category", LayoutCategory.UNKNOWN.value))
            prev_area = _area(prev)

            iou = compute_iou(cand_xyxy, prev_xyxy)
            contain = compute_containment(cand_xyxy, prev_xyxy)

            if cand_cat == prev_cat:
                if iou >= same_class_iou_threshold or contain >= containment_threshold:
                    is_duplicate = True
                    break
            else:
                if iou >= cross_class_iou_threshold:
                    is_duplicate = True
                    break
                # Suppress inner child text/unknown fragments swallowed by Table/Chart/Form container
                if (
                    prev_cat in (LayoutCategory.TABLE.value, LayoutCategory.CHART.value, LayoutCategory.FORM.value)
                    and cand_cat in (
                        LayoutCategory.PARAGRAPH.value,
                        LayoutCategory.FIGURE_IMAGE.value,
                        LayoutCategory.UNKNOWN.value,
                    )
                    and cand_area <= prev_area
                    and contain >= containment_threshold
                ):
                    is_duplicate = True
                    break

        if not is_duplicate:
            kept.append(cand)

    return kept


def _split_x_columns(items: List[Dict[str, Any]], gap_tol: int = 8) -> List[List[Dict[str, Any]]]:
    """Partitions ``items`` into disjoint vertical X-columns using normalized [ymin, xmin, ymax, xmax]."""
    if len(items) <= 1:
        return [list(items)] if items else []
    by_x = sorted(items, key=lambda r: (int(r["normalized_box"][1]), int(r["normalized_box"][0])))
    x_cols: List[List[Dict[str, Any]]] = [[by_x[0]]]
    cur_xmax = int(by_x[0]["normalized_box"][3])
    for reg in by_x[1:]:
        r_xmin = int(reg["normalized_box"][1])
        r_xmax = int(reg["normalized_box"][3])
        if r_xmin >= (cur_xmax - gap_tol):
            x_cols.append([reg])
            cur_xmax = r_xmax
        else:
            x_cols[-1].append(reg)
            cur_xmax = max(cur_xmax, r_xmax)
    return x_cols


def _xy_cut_sort(items: List[Dict[str, Any]], gap_tol: int = 8) -> List[Dict[str, Any]]:
    """
    Column-preserving recursive XY-cut reading-order sorter using canonical
    [ymin, xmin, ymax, xmax] coordinates (0..1000). Handles full-width
    headings/banners followed by multi-column bodies (even when rows align
    across columns) and trailing full-width sections cleanly.
    """
    if len(items) <= 1:
        return list(items)

    # 1. Try vertical X-columns first when no spanning bridge element crosses columns.
    x_cols = _split_x_columns(items, gap_tol=gap_tol)
    if len(x_cols) > 1:
        out: List[Dict[str, Any]] = []
        for col in x_cols:
            out.extend(_xy_cut_sort(col, gap_tol=gap_tol))
        return out

    # 2. Split into horizontal Y-bands to separate full-width spanning elements
    # (doc_title, banners, wide tables) from column bodies.
    by_y = sorted(items, key=lambda r: (int(r["normalized_box"][0]), int(r["normalized_box"][1])))
    y_bands: List[List[Dict[str, Any]]] = [[by_y[0]]]
    cur_ymax = int(by_y[0]["normalized_box"][2])
    for reg in by_y[1:]:
        r_ymin = int(reg["normalized_box"][0])
        r_ymax = int(reg["normalized_box"][2])
        if r_ymin >= (cur_ymax - gap_tol):
            y_bands.append([reg])
            cur_ymax = r_ymax
        else:
            y_bands[-1].append(reg)
            cur_ymax = max(cur_ymax, r_ymax)

    if len(y_bands) > 1:
        # Merge consecutive multi-column Y-bands that remain cleanly X-separable
        # so vertically aligned rows inside a 2+ column section stay Left-col first,
        # then Right-col, instead of zigzagging row-by-row.
        grouped_bands: List[List[Dict[str, Any]]] = []
        for band in y_bands:
            band_is_multicol = len(_split_x_columns(band, gap_tol=gap_tol)) >= 2
            if grouped_bands and band_is_multicol:
                prev_is_multicol = len(_split_x_columns(grouped_bands[-1], gap_tol=gap_tol)) >= 2
                if prev_is_multicol:
                    candidate = grouped_bands[-1] + band
                    if len(_split_x_columns(candidate, gap_tol=gap_tol)) >= 2:
                        grouped_bands[-1] = candidate
                        continue
            grouped_bands.append(list(band))

        # Safeguard against non-shrinking recursion (always strictly fewer items when len > 1)
        recurse_groups = grouped_bands if len(grouped_bands) > 1 else y_bands
        out = []
        for grp in recurse_groups:
            if len(grp) == len(items):
                # Cannot partition further without risking infinite recursion -> base case below
                break
            out.extend(_xy_cut_sort(grp, gap_tol=gap_tol))
        else:
            return out

    # 3. Base case: inseparable overlapping cluster -> stable row-band sort
    return sorted(
        items,
        key=lambda r: (
            int(r["normalized_box"][0]) // 18,
            int(r["normalized_box"][1]),
            int(r["normalized_box"][0]),
            int(r["normalized_box"][2]),
            int(r["normalized_box"][3]),
        ),
    )


def sort_regions_reading_order(detections: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """
    Orders layout regions deterministically in natural human reading order:
    Top headers -> column/XY-cut ordered body regions -> Bottom footers/page numbers.
    Assigns 1-based ``reading_order`` to every region.
    """
    if not detections:
        return []

    headers: List[Dict[str, Any]] = []
    body: List[Dict[str, Any]] = []
    footers: List[Dict[str, Any]] = []

    for raw in detections:
        reg = dict(raw)
        cat = str(reg.get("layout_category", ""))
        raw_label = str(reg.get("raw_label", ""))
        nb = reg["normalized_box"]
        if cat == LayoutCategory.HEADER_FOOTER.value:
            role = reg.get("sub_role") or _resolve_header_footer_role(raw_label, nb)
            reg["sub_role"] = role
            if role == "header":
                headers.append(reg)
            else:
                footers.append(reg)
        else:
            body.append(reg)

    ordered = (
        sorted(headers, key=lambda r: (int(r["normalized_box"][0]), int(r["normalized_box"][1])))
        + _xy_cut_sort(body)
        + sorted(footers, key=lambda r: (int(r["normalized_box"][0]), int(r["normalized_box"][1])))
    )
    for idx, reg in enumerate(ordered, start=1):
        reg["reading_order"] = idx
    return ordered


# ==============================================================================
# PER-REGION EXTRACTOR ROUTING (INCLUDES TABLE, FORM KV & UNKNOWN PRESERVATION)
# ==============================================================================
def _table_markdown_from_word_boxes(word_boxes: Sequence[Mapping[str, Any]], raw_text: str) -> str:
    """
    Reconstructs a Markdown pipe table from OCR word boxes grouped by visual rows
    and column X-gaps, falling back to plain ``raw_text`` when single-column.
    """
    words = [wb for wb in word_boxes if str(wb.get("word") or "").strip()]
    if len(words) < 2:
        return raw_text.strip()

    sorted_words = sorted(words, key=lambda w: (float(w.get("y", 0)) + float(w.get("h", 0)) / 2.0, float(w.get("x", 0))))
    avg_h = max(8.0, sum(float(w.get("h", 12) or 12) for w in sorted_words) / len(sorted_words))
    row_tol = max(6.0, avg_h * 0.65)

    rows_raw: List[List[Mapping[str, Any]]] = []
    current_row: List[Mapping[str, Any]] = []
    current_y: Optional[float] = None

    for wb in sorted_words:
        cy = float(wb.get("y", 0)) + float(wb.get("h", 0)) / 2.0
        if current_y is None or abs(cy - current_y) <= row_tol:
            current_row.append(wb)
            current_y = cy if current_y is None else ((current_y + cy) / 2.0)
        else:
            rows_raw.append(current_row)
            current_row = [wb]
            current_y = cy
    if current_row:
        rows_raw.append(current_row)

    if len(rows_raw) < 2:
        return raw_text.strip()

    # Estimate column anchors using gaps larger than typical inter-word space
    cell_gap_thresh = max(14.0, avg_h * 1.4)
    grid_rows: List[List[str]] = []
    for row in rows_raw:
        row_sorted = sorted(row, key=lambda w: float(w.get("x", 0)))
        cells: List[str] = []
        buf: List[str] = []
        prev_right: Optional[float] = None
        for wb in row_sorted:
            x = float(wb.get("x", 0))
            w = float(wb.get("w", 0))
            if prev_right is not None and (x - prev_right) > cell_gap_thresh and buf:
                cells.append(" ".join(buf))
                buf = [str(wb.get("word", "")).strip()]
            else:
                buf.append(str(wb.get("word", "")).strip())
            prev_right = x + w
        if buf:
            cells.append(" ".join(buf))
        if cells:
            grid_rows.append(cells)

    if any(len(r) >= 2 for r in grid_rows):
        md = format_markdown_table(grid_rows)
        if md:
            return md
    return raw_text.strip()


def _format_layout_region_markdown(
    *,
    category: LayoutCategory,
    raw_label: str,
    page_number: int,
    region_id: str,
    body_text: str,
    form_fields: Optional[List[Dict[str, str]]] = None,
    sub_role: str = "",
) -> str:
    clean_body = (body_text or "").strip()
    if category == LayoutCategory.TITLE_HEADING:
        heading_txt = clean_body or f"[{raw_label or 'heading'}]"
        return format_visual_region_markdown(
            page_number,
            region_id,
            f"Heading ({raw_label or 'title'})",
            f"## {heading_txt}",
        )
    if category == LayoutCategory.TABLE:
        return format_visual_region_markdown(
            page_number,
            region_id,
            "Layout Table",
            clean_body or f"[Non-text table region ({region_id})]",
        )
    if category == LayoutCategory.FORM:
        if form_fields:
            bullets = "\n".join(f"- **{item['field']}**: {item['value']}" for item in form_fields)
            body_out = f"{bullets}\n\n{clean_body}" if clean_body else bullets
        else:
            body_out = clean_body or f"[Form / {raw_label or 'seal'} region ({region_id})]"
        return format_visual_region_markdown(page_number, region_id, "Form Region", body_out)
    if category == LayoutCategory.CHART:
        return format_visual_region_markdown(
            page_number,
            region_id,
            "Chart",
            clean_body or f"[Visual chart region ({region_id})]",
        )
    if category == LayoutCategory.FIGURE_IMAGE:
        return format_visual_region_markdown(
            page_number,
            region_id,
            "Figure / Image",
            clean_body or f"[Visual figure/image region ({region_id})]",
        )
    if category == LayoutCategory.HEADER_FOOTER:
        role_title = (sub_role or raw_label or "header_footer").replace("_", " ").title()
        return format_visual_region_markdown(
            page_number,
            region_id,
            f"Page {role_title}",
            clean_body or f"[{role_title} region ({region_id})]",
        )
    if category == LayoutCategory.UNKNOWN:
        return format_visual_region_markdown(
            page_number,
            region_id,
            f"Unknown Region ({raw_label or 'unclassified'})",
            clean_body or f"[Preserved unknown layout region raw_label={raw_label!r} ({region_id})]",
        )
    return format_visual_region_markdown(
        page_number,
        region_id,
        f"Paragraph ({raw_label or 'text'})",
        clean_body or f"[Non-text paragraph region ({region_id})]",
    )


def _remap_crop_word_box(
    wb: Mapping[str, Any],
    crop_w: int,
    crop_h: int,
    region_px: Tuple[float, float, float, float],
    scale_x: float,
    scale_y: float,
    page_w: float,
    page_h: float,
) -> Optional[Dict[str, Any]]:
    """Remaps a single OCR word bbox on a region crop into page coordinates & 0..1000."""
    word = str(wb.get("word") or "").strip()
    if not word:
        return None
    rx0, ry0, rx1, ry1 = region_px
    rw = max(rx1 - rx0, 1.0)
    rh = max(ry1 - ry0, 1.0)

    if isinstance(wb.get("normalized_box"), (list, tuple)) and len(wb["normalized_box"]) == 4:
        cy0, cx0, cy1, cx1 = wb["normalized_box"]
        fx0, fx1 = float(cx0) / 1000.0, float(cx1) / 1000.0
        fy0, fy1 = float(cy0) / 1000.0, float(cy1) / 1000.0
    else:
        cw = max(float(crop_w or 1), 1.0)
        ch = max(float(crop_h or 1), 1.0)
        bx = float(wb.get("x", 0.0) or 0.0)
        by = float(wb.get("y", 0.0) or 0.0)
        bw = max(float(wb.get("w", 0.0) or 0.0), 0.0)
        bh = max(float(wb.get("h", 0.0) or 0.0), 0.0)
        fx0, fx1 = bx / cw, (bx + bw) / cw
        fy0, fy1 = by / ch, (by + bh) / ch

    px0 = (rx0 + fx0 * rw) * scale_x
    px1 = (rx0 + fx1 * rw) * scale_x
    py0 = (ry0 + fy0 * rh) * scale_y
    py1 = (ry0 + fy1 * rh) * scale_y

    out = dict(wb)
    out["word"] = word
    out["x"] = int(round(px0))
    out["y"] = int(round(py0))
    out["w"] = max(0, int(round(px1 - px0)))
    out["h"] = max(0, int(round(py1 - py0)))
    out["normalized_box"] = rect_to_normalized_box(px0, py0, px1, py1, canvas_width=page_w, canvas_height=page_h)
    return out


def route_and_extract_region(
    *,
    region_det: Mapping[str, Any],
    source_image: Image.Image,
    ocr_provider: BaseOCRProvider,
    page_number: int,
    page_width: float,
    page_height: float,
    scale_x: float,
    scale_y: float,
    repair_bengali: bool = True,
    convert_bangla_digits: bool = False,
    native_text_override: Optional[str] = None,
    native_word_boxes_override: Optional[List[Dict[str, Any]]] = None,
    vector_table_markdown: Optional[str] = None,
    table_extractor: Optional[Any] = None,
    chart_extractor: Optional[Any] = None,
    form_extractor: Optional[Any] = None,
    pymupdf_page: Optional[Any] = None,
    native_words_all: Optional[Sequence[Mapping[str, Any]]] = None,
    context_regions: Optional[Sequence[Mapping[str, Any]]] = None,
    fallback_vector_table: Optional[Mapping[str, Any]] = None,
    source_asset_name: str = "",
) -> Dict[str, Any]:
    """
    Routes a classified layout region to its designated extractor and builds a
    strictly contract-valid ``VisualRegionProvenanceContract`` record.
    """
    category = LayoutCategory(str(region_det.get("layout_category", LayoutCategory.UNKNOWN.value)))
    raw_label = str(region_det.get("raw_label", "unknown"))
    cls_id = region_det.get("cls_id")
    score = float(region_det.get("score", 0.5) or 0.0)
    reading_order = int(region_det.get("reading_order", 1) or 1)
    norm_box = list(region_det["normalized_box"])
    bbox_wh = list(region_det["bbox"])
    px_box = tuple(float(v) for v in region_det["pixel_box"][:4])
    region_id = str(region_det.get("region_id") or f"p{page_number}-lay{reading_order}-{category.value}")

    if category == LayoutCategory.TABLE and table_extractor is not None:
        tbl_region = table_extractor.extract_table_region(
            page_image=source_image,
            table_box=px_box,
            bbox_format="pixel",
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
            source_rotation=int(region_det.get("page_rotation", 0) or 0),
            coords_in_unrotated_space=False,
            region_id=region_id,
            layout_score=score,
            layout_label=raw_label,
            native_words=native_words_all,
            context_regions=context_regions,
            fallback_vector_table=fallback_vector_table,
            source_asset_name=source_asset_name,
        )
        t_meta = dict(tbl_region.get("metadata") or {})
        t_meta.setdefault("reading_order", reading_order)
        t_meta.setdefault("layout_model", PP_DOCLAYOUT_S_MODEL_NAME)
        tbl_region["metadata"] = t_meta
        return tbl_region

    if category == LayoutCategory.CHART and chart_extractor is not None:
        ch_region = chart_extractor.extract_chart_region(
            page_image=source_image,
            chart_box=px_box,
            bbox_format="pixel",
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
            source_rotation=int(region_det.get("page_rotation", 0) or 0),
            coords_in_unrotated_space=False,
            region_id=region_id,
            layout_score=score,
            layout_label=raw_label,
            pymupdf_page=pymupdf_page,
            context_regions=context_regions,
            source_asset_name=source_asset_name,
        )
        c_meta = dict(ch_region.get("metadata") or {})
        c_meta.setdefault("reading_order", reading_order)
        c_meta.setdefault("layout_model", PP_DOCLAYOUT_S_MODEL_NAME)
        c_meta.setdefault("layout_category", category.value)
        c_meta.setdefault("raw_label", raw_label)
        c_meta.setdefault("extraction_route", LayoutExtractorRoute.CHART_VISUAL_EXTRACTOR.value)
        ch_region["metadata"] = c_meta
        return ch_region

    def _delegate_to_form_extractor(resolved_cat: LayoutCategory, resolved_classified_by: str) -> Dict[str, Any]:
        assert form_extractor is not None
        fm_region = form_extractor.extract_form_region(
            page_image=source_image,
            form_box=px_box,
            bbox_format="pixel",
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
            source_rotation=int(region_det.get("page_rotation", 0) or 0),
            coords_in_unrotated_space=False,
            region_id=region_id,
            layout_score=score,
            layout_label=raw_label,
            pymupdf_page=pymupdf_page,
            native_words=native_words_all,
            source_asset_name=source_asset_name,
        )
        f_meta = dict(fm_region.get("metadata") or {})
        f_meta.setdefault("reading_order", reading_order)
        f_meta.setdefault("layout_model", PP_DOCLAYOUT_S_MODEL_NAME)
        f_meta.setdefault("layout_category", resolved_cat.value)
        f_meta.setdefault("raw_label", raw_label)
        f_meta.setdefault("classified_by", resolved_classified_by)
        f_meta.setdefault("extraction_route", LayoutExtractorRoute.FORM_KV_EXTRACTOR.value)
        fm_region["metadata"] = f_meta
        return fm_region

    if category == LayoutCategory.FORM and form_extractor is not None and raw_label != "seal":
        return _delegate_to_form_extractor(category, str(region_det.get("classified_by") or "model_label"))

    route = CATEGORY_TO_ROUTE[category]
    vis_type = CATEGORY_TO_VISUAL_REGION_TYPE[category]
    if raw_label == "seal":
        vis_type = VisualRegionType.STAMP_OR_SEAL
    elif raw_label == "signature":
        vis_type = VisualRegionType.SIGNATURE

    extracted_text = ""
    remapped_boxes: List[Dict[str, Any]] = []
    ocr_conf = 0.0
    ocr_available = False
    is_repaired = False
    ext_kind = VisualExtractionKind.HEURISTIC_LAYOUT
    sub_role = str(region_det.get("sub_role") or "")
    form_fields: List[Dict[str, str]] = []
    used_extractor = route.value

    if category == LayoutCategory.TABLE and vector_table_markdown:
        extracted_text = vector_table_markdown.strip()
        ext_kind = VisualExtractionKind.VECTOR_TABLE
        ocr_conf = 0.95
        used_extractor = "vector_table_extractor"
    elif native_text_override is not None and str(native_text_override).strip():
        extracted_text, is_repaired = apply_text_normalization(
            str(native_text_override),
            repair_bengali=repair_bengali,
            convert_bangla_digits=convert_bangla_digits,
        )
        remapped_boxes = list(native_word_boxes_override or [])
        ext_kind = VisualExtractionKind.OCR_LAYOUT
        ocr_conf = max(0.85, score)
        used_extractor = f"native_pdf_{route.value}"
    else:
        crop = crop_image_safe(source_image, px_box[0], px_box[1], px_box[2], px_box[3], padding=6)
        if crop is not None:
            padded = _pad_for_ocr_if_needed(crop)
            prep = None
            try:
                prep = ImagePreprocessor.preprocess(padded, auto_rotate=False)
                ocr_res = ocr_provider.extract_image(prep)
                status = str(ocr_res.get("status", "error"))
                ocr_available = status != "provider_unavailable"
                raw_ocr_text = "" if not ocr_available else str(ocr_res.get("text") or "")
                if VisualPipelineIntegrationAdapter.is_ocr_placeholder_text(raw_ocr_text):
                    raw_ocr_text = ""
                extracted_text, is_repaired = apply_text_normalization(
                    raw_ocr_text,
                    repair_bengali=repair_bengali,
                    convert_bangla_digits=convert_bangla_digits,
                )
                ocr_conf = float(ocr_res.get("confidence", 0.0) or 0.0) if ocr_available else 0.0

                raw_wbs = (ocr_res.get("bounding_boxes") or []) if ocr_available else []
                for wb in raw_wbs:
                    if isinstance(wb, dict):
                        mapped_wb = _remap_crop_word_box(
                            wb, prep.width, prep.height, px_box, scale_x, scale_y, page_width, page_height
                        )
                        if mapped_wb is not None:
                            remapped_boxes.append(mapped_wb)

                if category == LayoutCategory.TABLE and extracted_text:
                    extracted_text = _table_markdown_from_word_boxes(raw_wbs, extracted_text)
                    used_extractor = "table_ocr_extractor"

                if extracted_text:
                    ext_kind = VisualExtractionKind.OCR_LAYOUT
            finally:
                for tmp_img in (prep, padded, crop):
                    if tmp_img is not None and tmp_img is not source_image:
                        try:
                            tmp_img.close()
                        except Exception:
                            pass

    # Upgrade form_kv heuristics deterministically when model emitted generic text inside a KV block
    classified_by = str(region_det.get("classified_by") or "model_label")
    if category == LayoutCategory.PARAGRAPH and extracted_text and is_form_kv_text(extracted_text):
        category = LayoutCategory.FORM
        route = LayoutExtractorRoute.FORM_KV_EXTRACTOR
        vis_type = VisualRegionType.FORM_KV
        classified_by = "form_kv_heuristic"
        used_extractor = route.value
        if form_extractor is not None:
            return _delegate_to_form_extractor(category, classified_by)

    if category == LayoutCategory.FORM and extracted_text:
        form_fields = extract_form_kv_pairs(extracted_text)

    if category == LayoutCategory.HEADER_FOOTER and not sub_role:
        sub_role = _resolve_header_footer_role(raw_label, norm_box)

    final_conf = ocr_conf if extracted_text and ocr_conf > 0 else score
    final_conf = max(0.0, min(1.0, float(final_conf)))

    md = _format_layout_region_markdown(
        category=category,
        raw_label=raw_label,
        page_number=page_number,
        region_id=region_id,
        body_text=extracted_text,
        form_fields=form_fields,
        sub_role=sub_role,
    )

    return build_visual_region_provenance(
        region_id=region_id,
        region_type=vis_type,
        extraction_kind=ext_kind,
        page_number=page_number,
        bbox=bbox_wh,
        normalized_box=norm_box,
        text=extracted_text,
        markdown=md,
        confidence=final_conf,
        engine="pp_doclayout_s",
        engine_version=PP_DOCLAYOUT_S_MODEL_NAME,
        is_inference=False,
        is_repaired=is_repaired,
        source_asset_name=source_asset_name or f"page_{page_number}:{region_id}",
        word_boxes=remapped_boxes,
        metadata={
            "layout_category": category.value,
            "raw_label": raw_label,
            "cls_id": cls_id,
            "layout_score": round(score, 4),
            "reading_order": reading_order,
            "extraction_route": used_extractor,
            "classified_by": classified_by,
            "sub_role": sub_role,
            "form_fields": form_fields,
            "ocr_available": ocr_available,
            "layout_model": PP_DOCLAYOUT_S_MODEL_NAME,
        },
    )


# ==============================================================================
# CONFIGURATION & PER-WORKER MODEL CACHE
# ==============================================================================
def _read_setting_or_env(name: str, default: Any) -> Any:
    env_val = os.environ.get(name)
    if env_val is not None:
        return env_val
    try:
        from django.conf import settings as django_settings  # type: ignore

        if getattr(django_settings, "configured", False) and hasattr(django_settings, name):
            return getattr(django_settings, name)
    except Exception:
        pass
    return default


def _coerce_bool(val: Any, default: bool) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return default


@dataclass
class PPDocLayoutSConfig:
    """Configuration for optional CPU-based PP-DocLayout-S layout inference."""

    model_name: str = PP_DOCLAYOUT_S_MODEL_NAME
    model_dir: Optional[str] = None
    device: str = "cpu"
    cpu_threads: int = 4
    enable_mkldnn: bool = True
    threshold: float = 0.5
    layout_nms: bool = True
    layout_unclip_ratio: Optional[Any] = None
    layout_merge_bboxes_mode: Optional[Any] = None
    auto_rotate: bool = True
    reuse_worker_model: bool = True
    local_files_only: bool = False
    preserve_unknown_regions: bool = True
    iou_dedup_threshold: float = 0.55

    def __post_init__(self) -> None:
        # Enforce CPU execution cleanly for this CPU provider
        if str(self.device or "cpu").strip().lower() != "cpu":
            logger.warning(
                "PPDocLayoutSProvider is configured for CPU execution; overriding device=%r to 'cpu'.",
                self.device,
            )
            self.device = "cpu"
        else:
            self.device = "cpu"

        try:
            threads_int = int(self.cpu_threads)
        except (TypeError, ValueError):
            threads_int = 4
        if threads_int < 1:
            threads_int = 1
        self.cpu_threads = threads_int

        self.threshold = max(0.0, min(1.0, float(self.threshold)))
        self.iou_dedup_threshold = max(0.05, min(1.0, float(self.iou_dedup_threshold)))
        if self.model_dir is not None:
            cleaned = str(self.model_dir).strip()
            self.model_dir = cleaned or None

    @classmethod
    def from_settings_or_env(cls) -> "PPDocLayoutSConfig":
        return cls(
            model_name=str(_read_setting_or_env("PP_DOCLAYOUT_MODEL_NAME", PP_DOCLAYOUT_S_MODEL_NAME)),
            model_dir=_read_setting_or_env("PP_DOCLAYOUT_MODEL_DIR", None),
            device="cpu",
            cpu_threads=int(_read_setting_or_env("PP_DOCLAYOUT_CPU_THREADS", 4)),
            enable_mkldnn=_coerce_bool(_read_setting_or_env("PP_DOCLAYOUT_ENABLE_MKLDNN", True), True),
            threshold=float(_read_setting_or_env("PP_DOCLAYOUT_THRESHOLD", 0.5)),
            layout_nms=_coerce_bool(_read_setting_or_env("PP_DOCLAYOUT_NMS", True), True),
            local_files_only=_coerce_bool(_read_setting_or_env("PP_DOCLAYOUT_LOCAL_FILES_ONLY", False), False),
        )

    def cache_key(self) -> Tuple[Any, ...]:
        return (
            self.model_name,
            self.model_dir or "",
            self.device,
            self.cpu_threads,
            self.enable_mkldnn,
            round(self.threshold, 4),
            bool(self.layout_nms),
        )


class WorkerLayoutModelCache:
    """
    Thread-safe per-worker registry reusing loaded ``LayoutDetection`` models
    across pages and documents within a Django/Celery worker process.
    """

    _lock = threading.RLock()
    _models: Dict[Tuple[Any, ...], Any] = {}
    _load_count: int = 0
    _reuse_count: int = 0

    @classmethod
    def get_or_load(
        cls,
        config: PPDocLayoutSConfig,
        loader_fn: Callable[[PPDocLayoutSConfig], Any],
    ) -> Any:
        key = config.cache_key()
        with cls._lock:
            if key in cls._models:
                cls._reuse_count += 1
                return cls._models[key]
            model = loader_fn(config)
            cls._models[key] = model
            cls._load_count += 1
            return model

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._models.clear()
            cls._load_count = 0
            cls._reuse_count = 0

    @classmethod
    def stats(cls) -> Dict[str, Any]:
        with cls._lock:
            return {
                "cached_entries": len(cls._models),
                "load_count": cls._load_count,
                "reuse_count": cls._reuse_count,
                "cache_keys": [list(k) for k in cls._models.keys()],
            }


# ==============================================================================
# OPTIONAL CPU PP-DOCLAYOUT-S VISUAL PROVIDER
# ==============================================================================
class PPDocLayoutSProvider(BaseVisualProvider):
    """
    Optional CPU-based document layout detection provider powered by PaddleOCR's
    ``LayoutDetection(model_name="PP-DocLayout-S")``.

    Implements ``VisualProviderProtocol`` cleanly so it plugs into:
    - ``VisualDocumentExtractor(visual_provider=PPDocLayoutSProvider(...))``
    - ``PyMuPDFVisualPDFAdapter(layout_provider=PPDocLayoutSProvider(...))``

    Falls back cleanly to LORE's deterministic text/OCR stack when PaddleOCR,
    PaddlePaddle, or local model weights are unavailable or raise runtime errors.
    """

    provider_name = "pp_doclayout_s"
    engine_version = PP_DOCLAYOUT_S_MODEL_NAME
    requires_remote_egress = False

    def __init__(
        self,
        config: Optional[PPDocLayoutSConfig] = None,
        ocr_provider: Optional[BaseOCRProvider] = None,
        fallback_provider: Optional[BaseVisualProvider] = None,
        model_loader: Optional[Callable[[PPDocLayoutSConfig], Any]] = None,
        table_extractor: Optional[Any] = None,
        chart_extractor: Optional[Any] = None,
        form_extractor: Optional[Any] = None,
        enable_fallback: bool = True,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
    ):
        self.config = config or PPDocLayoutSConfig.from_settings_or_env()
        self.ocr_provider: BaseOCRProvider = ocr_provider or TesseractOCRProvider()
        self._fallback_provider = fallback_provider
        self._model_loader = model_loader
        self.table_extractor = table_extractor
        self.chart_extractor = chart_extractor
        self.form_extractor = form_extractor
        self._instance_model: Any = None
        self.enable_fallback = enable_fallback
        self.repair_bengali = repair_bengali
        self.convert_bangla_digits = convert_bangla_digits
        self.last_status_reason: str = ""

    def _get_fallback_provider(self) -> BaseVisualProvider:
        if self._fallback_provider is None:
            from .visual import LocalDeterministicVisualProvider

            self._fallback_provider = LocalDeterministicVisualProvider(
                ocr_provider=self.ocr_provider,
                repair_bengali=self.repair_bengali,
                convert_bangla_digits=self.convert_bangla_digits,
            )
        return self._fallback_provider

    def _default_model_loader(self, config: PPDocLayoutSConfig) -> Any:
        if not HAS_PADDLEOCR_LAYOUT or _PaddleOCRLayoutDetection is None:
            raise ImportError(
                "paddleocr>=3.0.0 with LayoutDetection is required for PP-DocLayout-S."
            )
        if not HAS_PADDLEPADDLE:
            raise ImportError(
                "paddlepaddle>=3.0.0 CPU package is required for PP-DocLayout-S inference."
            )

        kwargs: Dict[str, Any] = {
            "model_name": config.model_name,
            "device": "cpu",
            "cpu_threads": config.cpu_threads,
            "enable_mkldnn": config.enable_mkldnn,
            "threshold": config.threshold,
            "layout_nms": config.layout_nms,
        }
        if config.model_dir:
            kwargs["model_dir"] = config.model_dir

        try:
            sig = inspect.signature(_PaddleOCRLayoutDetection.__init__)
            accepts_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
            if not accepts_var_kw:
                kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
        except (TypeError, ValueError):
            pass

        return _PaddleOCRLayoutDetection(**kwargs)

    def _get_or_load_model(self) -> Any:
        if self.config.model_dir and not os.path.isdir(self.config.model_dir):
            raise FileNotFoundError(
                f"Configured PP-DocLayout-S model_dir does not exist: {self.config.model_dir}"
            )

        loader = self._model_loader or self._default_model_loader
        if self.config.reuse_worker_model:
            return WorkerLayoutModelCache.get_or_load(self.config, loader)
        if self._instance_model is None:
            self._instance_model = loader(self.config)
        return self._instance_model

    def is_available(self) -> bool:
        """
        Checks runtime availability cleanly without downloading weights:
        - Requires injected ``model_loader`` OR importable ``paddleocr`` + ``paddlepaddle``
        - Validates local ``model_dir`` existence when configured
        """
        if self.config.model_dir and not os.path.isdir(self.config.model_dir):
            self.last_status_reason = "model_dir_missing"
            return False

        if self._model_loader is not None:
            self.last_status_reason = "ready_custom_loader"
            return True

        if not (HAS_PADDLEOCR_LAYOUT and HAS_PADDLEPADDLE):
            self.last_status_reason = "paddle_packages_missing"
            return False

        if self.config.local_files_only and not self.config.model_dir:
            default_local = os.path.join(
                os.path.expanduser("~"), ".paddlex", "official_models", self.config.model_name
            )
            if not os.path.isdir(default_local):
                self.last_status_reason = "local_model_weights_missing"
                return False

        self.last_status_reason = "ready"
        return True

    @staticmethod
    def _prepare_model_input(image: Image.Image) -> Any:
        """
        Converts PIL image into BGR uint8 ``numpy.ndarray`` matching PaddleX
        ``ReadImage(format='BGR')`` + ``PP-DocLayout-S`` preprocessing expectations.
        """
        rgb_img = image if image.mode == "RGB" else image.convert("RGB")
        try:
            if HAS_NUMPY and np is not None:
                arr_rgb = np.asarray(rgb_img, dtype=np.uint8)
                # Convert RGB -> BGR (H, W, 3) contiguous array
                return np.ascontiguousarray(arr_rgb[:, :, ::-1])
            return rgb_img.copy()
        finally:
            if rgb_img is not image:
                try:
                    rgb_img.close()
                except Exception:
                    pass

    def _invoke_predict(self, model: Any, model_input: Any) -> Any:
        predict_fn = getattr(model, "predict", model)
        candidate_kwargs: Dict[str, Any] = {
            "batch_size": 1,
            "threshold": self.config.threshold,
            "layout_nms": self.config.layout_nms,
        }
        if self.config.layout_unclip_ratio is not None:
            candidate_kwargs["layout_unclip_ratio"] = self.config.layout_unclip_ratio
        if self.config.layout_merge_bboxes_mode is not None:
            candidate_kwargs["layout_merge_bboxes_mode"] = self.config.layout_merge_bboxes_mode

        try:
            sig = inspect.signature(predict_fn)
            accepts_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
            if not accepts_var_kw:
                candidate_kwargs = {k: v for k, v in candidate_kwargs.items() if k in sig.parameters}
        except (TypeError, ValueError):
            pass

        try:
            return predict_fn(model_input, **candidate_kwargs)
        except TypeError:
            # Compatibility fallback for minimal predict(img) callables
            return predict_fn(model_input)

    @staticmethod
    def _extract_raw_boxes(raw_output: Any) -> List[Dict[str, Any]]:
        """
        Parses PaddleOCR ``LayoutDetection.predict()`` return structures:
        - Iterable/list of Result objects (with ``res['boxes']``, ``res.get('boxes')``,
          or ``res.json['res']['boxes']``)
        - Dict containing ``boxes`` or ``res.boxes``
        """
        if raw_output is None:
            return []

        items = [raw_output] if isinstance(raw_output, Mapping) else list(raw_output)
        boxes: List[Dict[str, Any]] = []
        for item in items:
            if isinstance(item, Mapping):
                if isinstance(item.get("boxes"), list):
                    boxes.extend(b for b in item["boxes"] if isinstance(b, Mapping))
                elif isinstance(item.get("res"), Mapping) and isinstance(item["res"].get("boxes"), list):
                    boxes.extend(b for b in item["res"]["boxes"] if isinstance(b, Mapping))
                elif "coordinate" in item:
                    boxes.append(dict(item))
                continue

            item_json = getattr(item, "json", None)
            if callable(item_json):
                try:
                    item_json = item_json()
                except Exception:
                    item_json = None
            if isinstance(item_json, Mapping):
                res_node = item_json.get("res", item_json)
                if isinstance(res_node, Mapping) and isinstance(res_node.get("boxes"), list):
                    boxes.extend(dict(b) for b in res_node["boxes"] if isinstance(b, Mapping))
                    continue

            try:
                sub = item["boxes"]
                if isinstance(sub, list):
                    boxes.extend(dict(b) for b in sub if isinstance(b, Mapping))
            except Exception:
                pass
        return boxes

    def detect_layout(
        self,
        image: Image.Image,
        *,
        page_number: int = 1,
        page_width: Optional[float] = None,
        page_height: Optional[float] = None,
        source_rotation: int = 0,
        coords_in_unrotated_space: bool = False,
        apply_auto_rotate: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Runs PP-DocLayout-S layout prediction on ``image``, normalizes bounding boxes
        into LORE's canonical 0..1000 ``[ymin, xmin, ymax, xmax]`` display system,
        suppresses duplicate overlaps, and sorts in reading order.
        """
        t0 = time.time()
        should_auto_rotate = self.config.auto_rotate if apply_auto_rotate is None else apply_auto_rotate
        oriented_img = image
        rotated_deg = int(source_rotation or 0) % 360

        try:
            if should_auto_rotate:
                exif_deg = 0
                try:
                    exif_data = image.getexif()
                    orient = int(exif_data.get(274, 1) or 1) if exif_data else 1
                    exif_deg = {3: 180, 6: 270, 8: 90}.get(orient, 0)
                except Exception:
                    exif_deg = 0
                oriented_img, osd_deg = ImagePreprocessor.detect_and_correct_rotation(image)
                auto_deg = (exif_deg + int(osd_deg or 0)) % 360
                if auto_deg:
                    rotated_deg = (rotated_deg + auto_deg) % 360 if source_rotation else auto_deg

            img_w, img_h = oriented_img.size
            if img_w <= 0 or img_h <= 0:
                return {
                    "status": "empty_image",
                    "regions": [],
                    "width": 0.0,
                    "height": 0.0,
                    "rotated_degrees": rotated_deg,
                    "elapsed_ms": 0.0,
                }

            from .runtime import configure_visual_cpu_runtime

            configure_visual_cpu_runtime(cpu_threads=self.config.cpu_threads)
            model = self._get_or_load_model()
            model_input = self._prepare_model_input(oriented_img)
            try:
                raw_output = self._invoke_predict(model, model_input)
                raw_boxes = self._extract_raw_boxes(raw_output)
            finally:
                model_input = None
                raw_output = None

            eff_pw = float(page_width or img_w)
            eff_ph = float(page_height or img_h)

            if coords_in_unrotated_space and rotated_deg in (90, 270):
                raw_space_w, raw_space_h = float(img_h), float(img_w)
            else:
                raw_space_w, raw_space_h = float(img_w), float(img_h)

            normalized_detections: List[Dict[str, Any]] = []
            for box in raw_boxes:
                coords = box.get("coordinate") or box.get("bbox")
                if not isinstance(coords, (list, tuple)) or len(coords) < 4:
                    continue
                xmin, ymin, xmax, ymax = float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3])

                if coords_in_unrotated_space and rotated_deg in (90, 180, 270):
                    (xmin, ymin, xmax, ymax), _ = transform_box_for_rotation(
                        xmin, ymin, xmax, ymax, raw_space_w, raw_space_h, rotated_deg
                    )

                px0 = max(0.0, min(float(img_w), min(xmin, xmax)))
                py0 = max(0.0, min(float(img_h), min(ymin, ymax)))
                px1 = max(px0 + 1.0, min(float(img_w), max(xmin, xmax)))
                py1 = max(py0 + 1.0, min(float(img_h), max(ymin, ymax)))

                scale_x = eff_pw / max(float(img_w), 1.0)
                scale_y = eff_ph / max(float(img_h), 1.0)
                disp_x0 = px0 * scale_x
                disp_y0 = py0 * scale_y
                disp_x1 = px1 * scale_x
                disp_y1 = py1 * scale_y

                norm_box = validate_normalized_box(
                    rect_to_normalized_box(
                        disp_x0, disp_y0, disp_x1, disp_y1, canvas_width=eff_pw, canvas_height=eff_ph
                    )
                )
                score = max(0.0, min(1.0, float(box.get("score", 0.0) or 0.0)))
                cls_id = box.get("cls_id")
                category, norm_raw_label = classify_layout_label(box.get("label"), cls_id=cls_id)

                if not self.config.preserve_unknown_regions and category == LayoutCategory.UNKNOWN:
                    continue

                normalized_detections.append({
                    "layout_category": category.value,
                    "raw_label": norm_raw_label,
                    "cls_id": cls_id,
                    "score": round(score, 4),
                    "pixel_box": [round(px0, 2), round(py0, 2), round(px1, 2), round(py1, 2)],
                    "bbox": [
                        round(disp_x0, 2),
                        round(disp_y0, 2),
                        round(max(0.0, disp_x1 - disp_x0), 2),
                        round(max(0.0, disp_y1 - disp_y0), 2),
                    ],
                    "normalized_box": norm_box,
                    "page_number": page_number,
                    "page_rotation": rotated_deg,
                    "classified_by": "model_label" if category != LayoutCategory.UNKNOWN else "preserved_unknown",
                })

            deduped = deduplicate_layout_regions(
                normalized_detections,
                same_class_iou_threshold=self.config.iou_dedup_threshold,
            )
            ordered = sort_regions_reading_order(deduped)
            for idx, reg in enumerate(ordered, start=1):
                reg["region_id"] = f"p{page_number}-lay{idx}-{reg['layout_category']}"

            return {
                "status": "success",
                "regions": ordered,
                "oriented_image": oriented_img,
                "owns_oriented_image": oriented_img is not image,
                "width": eff_pw,
                "height": eff_ph,
                "image_width": img_w,
                "image_height": img_h,
                "rotated_degrees": rotated_deg,
                "elapsed_ms": round((time.time() - t0) * 1000.0, 2),
            }
        except Exception:
            if oriented_img is not None and oriented_img is not image:
                try:
                    oriented_img.close()
                except Exception:
                    pass
            raise

    def _build_fallback_result(
        self,
        *,
        image: Image.Image,
        context: Optional[Dict[str, Any]],
        reason: str,
        elapsed_ms: float,
    ) -> Dict[str, Any]:
        if self.enable_fallback:
            fb = self._get_fallback_provider()
            fb_res = dict(fb.analyze_image(image, context=context))
            fb_res["fallback_applied"] = True
            fb_res["fallback_reason"] = reason
            fb_res["is_optional_skipped"] = True
            if fb_res.get("status") == "success":
                fb_res["status"] = "fallback_deterministic"
            fb_metrics = dict(fb_res.get("metrics") or {})
            fb_metrics["fallback_from"] = self.provider_name
            fb_metrics["fallback_reason"] = reason
            fb_res["metrics"] = fb_metrics
            return fb_res

        img_w, img_h = image.size
        return {
            "status": "provider_unavailable",
            "regions": [],
            "text": "",
            "confidence": 0.0,
            "width": float(img_w),
            "height": float(img_h),
            "engine": self.provider_name,
            "engine_version": self.engine_version,
            "is_optional_skipped": True,
            "needs_review": False,
            "fallback_applied": True,
            "fallback_reason": reason,
            "rotated_degrees": 0,
            "metrics": ModelExecutionMetric(
                provider=self.provider_name,
                model_name=self.config.model_name,
                purpose=ModelTaskPurpose.OCR.value,
                latency_ms=elapsed_ms,
                was_deterministic=False,
                reason=reason,
            ).to_dict(),
        }

    def analyze_image(
        self,
        image: Image.Image,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Runs CPU PP-DocLayout-S layout analysis + per-region extractor routing on a
        PIL image, preserving unknown regions and falling back safely on unavailability
        or runtime failure.
        """
        t0 = time.time()
        ctx = context or {}
        page_num = int(ctx.get("page_number", 1) or 1)
        asset_name = str(ctx.get("source_asset_name", "") or "")
        page_width = ctx.get("page_width")
        page_height = ctx.get("page_height")
        source_rotation = int(ctx.get("source_rotation", 0) or 0)
        coords_unrotated = bool(ctx.get("coords_in_unrotated_space", False))
        apply_auto_rot = ctx.get("apply_auto_rotate")

        if not self.is_available():
            return self._build_fallback_result(
                image=image,
                context=ctx,
                reason=self.last_status_reason or "pp_doclayout_s_unavailable",
                elapsed_ms=round((time.time() - t0) * 1000.0, 2),
            )

        oriented_img: Optional[Image.Image] = None
        owns_oriented = False
        try:
            det_res = self.detect_layout(
                image,
                page_number=page_num,
                page_width=page_width,
                page_height=page_height,
                source_rotation=source_rotation,
                coords_in_unrotated_space=coords_unrotated,
                apply_auto_rotate=apply_auto_rot,
            )
            oriented_img = det_res.get("oriented_image", image)
            owns_oriented = bool(det_res.get("owns_oriented_image", False))
            img_w = int(det_res.get("image_width") or oriented_img.width)
            img_h = int(det_res.get("image_height") or oriented_img.height)
            eff_pw = float(det_res.get("width") or img_w)
            eff_ph = float(det_res.get("height") or img_h)
            scale_x = eff_pw / max(float(img_w), 1.0)
            scale_y = eff_ph / max(float(img_h), 1.0)
            rotated_deg = int(det_res.get("rotated_degrees", 0) or 0)
            ordered_dets = det_res.get("regions") or []

            if not ordered_dets:
                elapsed_ms = round((time.time() - t0) * 1000.0, 2)
                return self._build_fallback_result(
                    image=oriented_img,
                    context=ctx,
                    reason="no_layout_regions_detected",
                    elapsed_ms=elapsed_ms,
                )

            eff_table_extractor = ctx.get("table_extractor") or self.table_extractor
            eff_chart_extractor = ctx.get("chart_extractor") or self.chart_extractor
            eff_form_extractor = ctx.get("form_extractor") or self.form_extractor
            pymupdf_page_ctx = ctx.get("pymupdf_page")
            native_words_ctx = ctx.get("native_words")

            # Two-pass extraction when table_extractor, chart_extractor, or form_extractor is active so
            # non-table/chart context regions (footnotes, chart_title) are available first.
            regions_slot: List[Optional[Dict[str, Any]]] = [None] * len(ordered_dets)
            non_table_regions: List[Dict[str, Any]] = []
            for idx, det in enumerate(ordered_dets):
                cat_val = str(det.get("layout_category"))
                raw_lbl = str(det.get("raw_label") or "").lower()
                if (
                    (cat_val == LayoutCategory.TABLE.value and eff_table_extractor is not None)
                    or (cat_val == LayoutCategory.CHART.value and eff_chart_extractor is not None)
                    or (cat_val == LayoutCategory.FORM.value and eff_form_extractor is not None and raw_lbl != "seal")
                ):
                    continue
                reg = route_and_extract_region(
                    region_det=det,
                    source_image=oriented_img,
                    ocr_provider=self.ocr_provider,
                    page_number=page_num,
                    page_width=eff_pw,
                    page_height=eff_ph,
                    scale_x=scale_x,
                    scale_y=scale_y,
                    repair_bengali=self.repair_bengali,
                    convert_bangla_digits=self.convert_bangla_digits,
                    form_extractor=eff_form_extractor,
                    pymupdf_page=pymupdf_page_ctx,
                    native_words_all=native_words_ctx,
                    source_asset_name=asset_name,
                )
                regions_slot[idx] = reg
                non_table_regions.append(reg)

            for idx, det in enumerate(ordered_dets):
                if regions_slot[idx] is not None:
                    continue
                regions_slot[idx] = route_and_extract_region(
                    region_det=det,
                    source_image=oriented_img,
                    ocr_provider=self.ocr_provider,
                    page_number=page_num,
                    page_width=eff_pw,
                    page_height=eff_ph,
                    scale_x=scale_x,
                    scale_y=scale_y,
                    repair_bengali=self.repair_bengali,
                    convert_bangla_digits=self.convert_bangla_digits,
                    table_extractor=eff_table_extractor,
                    chart_extractor=eff_chart_extractor,
                    form_extractor=eff_form_extractor,
                    pymupdf_page=pymupdf_page_ctx,
                    native_words_all=native_words_ctx,
                    context_regions=non_table_regions,
                    source_asset_name=asset_name,
                )

            regions_out: List[Dict[str, Any]] = [r for r in regions_slot if r is not None]

            elapsed_ms = round((time.time() - t0) * 1000.0, 2)
            confs = [float(r.get("confidence", 0.0) or 0.0) for r in regions_out]
            avg_conf = round(sum(confs) / max(len(confs), 1), 4)
            any_region_review = any(
                bool((r.get("metadata") or {}).get("needs_review"))
                or bool((r.get("metadata") or {}).get("review_required"))
                or bool(((r.get("metadata") or {}).get("table_validation") or {}).get("needs_review"))
                or bool(((r.get("metadata") or {}).get("chart_validation") or {}).get("review_required"))
                or bool(((r.get("metadata") or {}).get("form_validation") or {}).get("needs_review"))
                or bool(((r.get("metadata") or {}).get("form_validation") or {}).get("review_required"))
                for r in regions_out
            )
            combined_text = "\n\n".join(
                str(r.get("text") or "").strip()
                for r in regions_out
                if str(r.get("text") or "").strip()
            )
            return {
                "status": "success",
                "regions": regions_out,
                "text": combined_text,
                "confidence": avg_conf,
                "width": eff_pw,
                "height": eff_ph,
                "engine": self.provider_name,
                "engine_version": self.engine_version,
                "is_optional_skipped": False,
                "needs_review": (avg_conf < 0.70) or any_region_review,
                "rotated_degrees": rotated_deg,
                "metrics": ModelExecutionMetric(
                    provider=self.provider_name,
                    model_name=self.config.model_name,
                    purpose=ModelTaskPurpose.OCR.value,
                    latency_ms=elapsed_ms,
                    was_deterministic=False,
                    reason=(
                        f"cpu_threads={self.config.cpu_threads},"
                        f"mkldnn={self.config.enable_mkldnn},"
                        f"regions={len(regions_out)}"
                    ),
                ).to_dict(),
            }
        except Exception as exc:
            safe_err = sanitize_sensitive_data(str(exc))
            logger.warning("PPDocLayoutSProvider failed cleanly; triggering fallback: %s", safe_err)
            return self._build_fallback_result(
                image=image,
                context=ctx,
                reason=f"layout_inference_error: {safe_err}",
                elapsed_ms=round((time.time() - t0) * 1000.0, 2),
            )
        finally:
            if owns_oriented and oriented_img is not None:
                try:
                    oriented_img.close()
                except Exception:
                    pass
