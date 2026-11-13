"""
LORE Chart Extraction Module using PyMuPDF, OpenCV, and Tesseract OCR.

Deterministic, local-first visual chart understanding integrated into LORE's
ingestion pipeline without invoking LLMs or touching Settlement/Knowledge
responsibilities.

Capabilities:
1. Detects and crops chart regions with exact affine rotation/scale coordinate
   tracking and content-addressed crop references.
2. Classifies source backing cleanly as ``vector``, ``raster``, or ``mixed``.
3. Extracts native PDF drawing paths (``get_drawings()``) and text spans/words
   (``get_text("dict")``) via PyMuPDF whenever available.
4. Analyzes raster/scanned/hybrid charts with OpenCV (axes, tick stubs,
   gridlines, legends, solid bars, stacked/grouped layers, polylines, pie
   wedges, and scatter markers).
5. Uses the existing LORE ``TesseractOCRProvider`` for raster, missing, or
   rotated axis/legend/slice text, preserving OCR confidence, engine, version,
   warnings, and Bengali/English normalization.
6. Calibrates numeric axes directly from visible tick marks without assuming
   zero origins or equal intervals.
7. Identifies ``vertical_bar``, ``horizontal_bar``, ``grouped_bar``,
   ``stacked_bar``, ``line``, ``pie``, ``scatter``, and ``unknown`` charts.
8. Preserves units, negative values, axis origins, and multiple (dual Y) axes.
9. Marks every extracted point deterministically as ``exact``, ``estimated``, or
   ``unavailable``; preserves image crop + metadata with ``review_required=True``
   whenever reliable reconstruction is impossible.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
import hashlib
import io
import logging
import math
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, cast

from PIL import Image

from apps.governance.modes import sanitize_sensitive_data

from .contracts import (
    VisualExtractionKind,
    VisualPipelineIntegrationAdapter,
    VisualRegionType,
    build_visual_region_provenance,
    rect_to_normalized_box,
    validate_normalized_box,
)
from .ocr import (
    BaseOCRProvider,
    ImagePreprocessor,
    TesseractOCRProvider,
    bangla_to_arabic_digits,
)
from .visual import (
    apply_text_normalization,
    format_visual_region_markdown,
)

logger = logging.getLogger(__name__)

# Optional runtime dependencies (all supported gracefully with availability probes)
try:
    import numpy as np  # type: ignore

    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore
    HAS_NUMPY = False

try:
    import cv2  # type: ignore

    HAS_OPENCV = True
    OPENCV_VERSION = str(getattr(cv2, "__version__", "unknown"))
except ImportError:
    cv2 = None  # type: ignore
    HAS_OPENCV = False
    OPENCV_VERSION = "unavailable"

try:
    import pymupdf  # type: ignore

    HAS_PYMUPDF = True
    PYMUPDF_VERSION = str(getattr(pymupdf, "__version__", "unknown"))
except ImportError:
    pymupdf = None  # type: ignore
    HAS_PYMUPDF = False
    PYMUPDF_VERSION = "unavailable"


# ==============================================================================
# CANONICAL ENUMS & CONFIG
# ==============================================================================
class ChartType(str, Enum):
    """Identifiable chart taxonomies emitted in structured metadata."""

    VERTICAL_BAR = "vertical_bar"
    HORIZONTAL_BAR = "horizontal_bar"
    GROUPED_BAR = "grouped_bar"
    STACKED_BAR = "stacked_bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    UNKNOWN = "unknown"


class ChartSourceMode(str, Enum):
    """Backing geometry source inside the cropped chart region."""

    VECTOR = "vector"
    RASTER = "raster"
    MIXED = "mixed"


class ValuePrecisionStatus(str, Enum):
    """Epistemic reliability classification required for every extracted value."""

    EXACT = "exact"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


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
        low = val.strip().lower()
        if low in ("true", "1", "yes", "on"):
            return True
        if low in ("false", "0", "no", "off"):
            return False
    return default


@dataclass
class ChartExtractorConfig:
    """Configuration for deterministic PyMuPDF + OpenCV + Tesseract chart extraction."""

    min_chart_width_px: int = 80
    min_chart_height_px: int = 80
    low_resolution_min_width_px: int = 160
    low_resolution_min_height_px: int = 120
    crop_padding_px: int = 10
    min_ocr_confidence_for_review: float = 0.45
    max_axis_linear_residual: float = 0.045
    min_axis_r2: float = 0.985
    preserve_crop_image: bool = True
    crop_output_dir: Optional[str] = None
    max_embedded_crop_bytes: int = 262_144

    def __post_init__(self) -> None:
        self.min_chart_width_px = max(24, self.min_chart_width_px)
        self.min_chart_height_px = max(24, self.min_chart_height_px)
        self.low_resolution_min_width_px = max(40, self.low_resolution_min_width_px)
        self.low_resolution_min_height_px = max(40, self.low_resolution_min_height_px)
        self.crop_padding_px = max(0, self.crop_padding_px)
        self.min_ocr_confidence_for_review = max(0.0, min(1.0, self.min_ocr_confidence_for_review))
        self.max_axis_linear_residual = max(0.005, min(0.25, self.max_axis_linear_residual))
        self.min_axis_r2 = max(0.80, min(0.9999, self.min_axis_r2))
        self.max_embedded_crop_bytes = max(16_384, self.max_embedded_crop_bytes)
        if self.crop_output_dir is not None:
            cleaned = self.crop_output_dir.strip()
            self.crop_output_dir = cleaned or None

    @classmethod
    def from_settings_or_env(cls) -> "ChartExtractorConfig":
        return cls(
            low_resolution_min_width_px=int(_read_setting_or_env("CHART_MIN_RESOLUTION_WIDTH", 160)),
            low_resolution_min_height_px=int(_read_setting_or_env("CHART_MIN_RESOLUTION_HEIGHT", 120)),
            preserve_crop_image=_coerce_bool(_read_setting_or_env("CHART_PRESERVE_CROP_IMAGE", True), True),
            crop_output_dir=_read_setting_or_env("CHART_CROP_OUTPUT_DIR", None),
            max_embedded_crop_bytes=int(_read_setting_or_env("CHART_MAX_EMBEDDED_CROP_BYTES", 262_144)),
        )


# ==============================================================================
# COORDINATE TRANSFORMATION & CROP REFERENCE HELPERS
# ==============================================================================
def _rotate_box_cw(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    space_w: float,
    space_h: float,
    rotation_deg: int,
) -> Tuple[Tuple[float, float, float, float], Tuple[float, float]]:
    rot = (rotation_deg or 0) % 360
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if rot == 90:
        mapped = [(space_h - y, x) for x, y in corners]
        dims = (space_h, space_w)
    elif rot == 180:
        mapped = [(space_w - x, space_h - y) for x, y in corners]
        dims = (space_w, space_h)
    elif rot == 270:
        mapped = [(y, space_w - x) for x, y in corners]
        dims = (space_h, space_w)
    else:
        mapped = corners
        dims = (space_w, space_h)
    xs = [p[0] for p in mapped]
    ys = [p[1] for p in mapped]
    return (min(xs), min(ys), max(xs), max(ys)), dims


def _transform_pdf_point_to_display(
    pt: Any,
    page: Any,
) -> Tuple[float, float]:
    """Converts a PyMuPDF unrotated page point into upright display coordinates."""
    if hasattr(pt, "x") and hasattr(pt, "y"):
        px, py = float(pt.x), float(pt.y)
    elif isinstance(pt, (tuple, list)) and len(pt) >= 2:
        px, py = float(pt[0]), float(pt[1])
    else:
        return (0.0, 0.0)

    rot = int(getattr(page, "rotation", 0) or 0) % 360
    if rot == 0 or not HAS_PYMUPDF or pymupdf is None or not hasattr(page, "rotation_matrix"):
        return (px, py)
    try:
        tp = pymupdf.Point(px, py) * page.rotation_matrix
        return (float(tp.x), float(tp.y))
    except Exception:
        return (px, py)


def _transform_pdf_rect_to_display(
    raw_rect: Any,
    page: Any,
) -> Optional[Tuple[float, float, float, float]]:
    if raw_rect is None:
        return None
    try:
        if hasattr(raw_rect, "x0"):
            rect = pymupdf.Rect(raw_rect) if (HAS_PYMUPDF and pymupdf is not None) else raw_rect
            x0, y0, x1, y1 = float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)
        elif isinstance(raw_rect, (tuple, list)) and len(raw_rect) >= 4:
            x0, y0, x1, y1 = float(raw_rect[0]), float(raw_rect[1]), float(raw_rect[2]), float(raw_rect[3])
        else:
            return None
        rot = int(getattr(page, "rotation", 0) or 0) % 360
        if rot != 0 and HAS_PYMUPDF and pymupdf is not None and hasattr(page, "rotation_matrix"):
            tr = pymupdf.Rect(x0, y0, x1, y1) * page.rotation_matrix
            return (float(min(tr.x0, tr.x1)), float(min(tr.y0, tr.y1)), float(max(tr.x0, tr.x1)), float(max(tr.y0, tr.y1)))
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    except Exception:
        return None


def resolve_chart_crop_geometry(
    *,
    page_image: Image.Image,
    chart_box: Optional[Sequence[float]],
    bbox_format: str = "normalized",
    page_width: Optional[float] = None,
    page_height: Optional[float] = None,
    source_rotation: int = 0,
    coords_in_unrotated_space: bool = False,
    padding_px: int = 10,
    pre_cropped_display_rect: Optional[Sequence[float]] = None,
) -> Tuple[Optional[Image.Image], Dict[str, Any]]:
    """
    Crops a chart region accurately from ``page_image`` and records an exact inverse
    affine transform from crop-local pixels back to upright page display
    coordinates and canonical ``[ymin, xmin, ymax, xmax]`` (0..1000) coordinates.

    When ``pre_cropped_display_rect`` ``[rx0, ry0, rx1, ry1]`` is supplied (in
    upright page display coordinates, e.g. from PyMuPDF clipped region rendering),
    ``page_image`` is treated directly as that region bitmap without requiring a
    full-page render while keeping all mapped coordinates page-accurate.
    """
    img_w, img_h = page_image.size
    eff_pw = float(page_width or img_w)
    eff_ph = float(page_height or img_h)
    if img_w <= 0 or img_h <= 0:
        return None, {}

    if pre_cropped_display_rect is not None and len(pre_cropped_display_rect) >= 4:
        rx0 = max(0.0, min(eff_pw, pre_cropped_display_rect[0]))
        ry0 = max(0.0, min(eff_ph, pre_cropped_display_rect[1]))
        rx1 = max(rx0 + 1.0, min(eff_pw, pre_cropped_display_rect[2]))
        ry1 = max(ry0 + 1.0, min(eff_ph, pre_cropped_display_rect[3]))
        disp_w = max(1e-6, rx1 - rx0)
        disp_h = max(1e-6, ry1 - ry0)
        scale_x = disp_w / max(float(img_w), 1.0)
        scale_y = disp_h / max(float(img_h), 1.0)
        cl = rx0 / max(scale_x, 1e-9)
        ct = ry0 / max(scale_y, 1e-9)
        crop = page_image.convert("RGB") if page_image.mode != "RGB" else page_image.copy()
        chart_norm = validate_normalized_box(
            rect_to_normalized_box(rx0, ry0, rx1, ry1, canvas_width=eff_pw, canvas_height=eff_ph)
        )
        geom = {
            "image_width": eff_pw / max(scale_x, 1e-9),
            "image_height": eff_ph / max(scale_y, 1e-9),
            "page_width": eff_pw,
            "page_height": eff_ph,
            "scale_x": scale_x,
            "scale_y": scale_y,
            "chart_pixel_box": [round(cl, 2), round(ct, 2), round(cl + img_w, 2), round(ct + img_h, 2)],
            "chart_display_rect": [round(rx0, 2), round(ry0, 2), round(rx1, 2), round(ry1, 2)],
            "chart_display_bbox": [
                round(rx0, 2),
                round(ry0, 2),
                round(disp_w, 2),
                round(disp_h, 2),
            ],
            "chart_normalized_box": chart_norm,
            "crop_rect_px": [round(cl), round(ct), round(cl + img_w), round(ct + img_h)],
            "crop_left": cl,
            "crop_top": ct,
            "crop_width": float(img_w),
            "crop_height": float(img_h),
            "source_rotation": (source_rotation or 0) % 360,
        }
        return crop, geom

    if chart_box is None:
        raw_x0, raw_y0, raw_x1, raw_y1 = 0.0, 0.0, float(img_w), float(img_h)
        raw_space_w, raw_space_h = float(img_w), float(img_h)
    else:
        if len(chart_box) < 4:
            return None, {}
        fmt = (bbox_format or "normalized").lower().strip()
        if fmt == "normalized":
            ymin_n, xmin_n, ymax_n, xmax_n = chart_box[0], chart_box[1], chart_box[2], chart_box[3]
            raw_x0 = (xmin_n / 1000.0) * img_w
            raw_y0 = (ymin_n / 1000.0) * img_h
            raw_x1 = (xmax_n / 1000.0) * img_w
            raw_y1 = (ymax_n / 1000.0) * img_h
            raw_space_w, raw_space_h = float(img_w), float(img_h)
        elif fmt == "xywh":
            bx, by, bw, bh = chart_box[0], chart_box[1], chart_box[2], chart_box[3]
            sx = img_w / max(eff_pw, 1.0)
            sy = img_h / max(eff_ph, 1.0)
            raw_x0, raw_y0 = bx * sx, by * sy
            raw_x1, raw_y1 = (bx + max(0.0, bw)) * sx, (by + max(0.0, bh)) * sy
            raw_space_w, raw_space_h = float(img_w), float(img_h)
        elif fmt == "display":
            dx0, dy0, dx1, dy1 = chart_box[0], chart_box[1], chart_box[2], chart_box[3]
            sx = img_w / max(eff_pw, 1.0)
            sy = img_h / max(eff_ph, 1.0)
            raw_x0, raw_y0, raw_x1, raw_y1 = dx0 * sx, dy0 * sy, dx1 * sx, dy1 * sy
            raw_space_w, raw_space_h = float(img_w), float(img_h)
        else:
            raw_x0, raw_y0, raw_x1, raw_y1 = chart_box[0], chart_box[1], chart_box[2], chart_box[3]
            if coords_in_unrotated_space and ((source_rotation or 0) % 360) in (90, 270):
                raw_space_w, raw_space_h = float(img_h), float(img_w)
            else:
                raw_space_w, raw_space_h = float(img_w), float(img_h)

    if chart_box is not None and coords_in_unrotated_space and ((source_rotation or 0) % 360) in (90, 180, 270):
        (px0, py0, px1, py1), _ = _rotate_box_cw(
            raw_x0, raw_y0, raw_x1, raw_y1, raw_space_w, raw_space_h, source_rotation
        )
    else:
        px0, px1 = min(raw_x0, raw_x1), max(raw_x0, raw_x1)
        py0, py1 = min(raw_y0, raw_y1), max(raw_y0, raw_y1)

    px0 = max(0.0, min(float(img_w), px0))
    py0 = max(0.0, min(float(img_h), py0))
    px1 = max(0.0, min(float(img_w), px1))
    py1 = max(0.0, min(float(img_h), py1))
    if (px1 - px0) < 8.0 or (py1 - py0) < 8.0:
        return None, {}

    pad = max(0, padding_px) if chart_box is not None else 0
    cl = max(0, int(px0) - pad)
    ct = max(0, int(py0) - pad)
    cr = min(img_w, round(px1) + pad)
    cb = min(img_h, round(py1) + pad)
    crop_w = cr - cl
    crop_h = cb - ct
    if crop_w < 8 or crop_h < 8:
        return None, {}

    crop = page_image.crop((cl, ct, cr, cb))
    if crop.mode != "RGB":
        rgb_crop = crop.convert("RGB")
        crop.close()
        crop = rgb_crop

    scale_x = eff_pw / max(float(img_w), 1.0)
    scale_y = eff_ph / max(float(img_h), 1.0)

    disp_x0 = px0 * scale_x
    disp_y0 = py0 * scale_y
    disp_x1 = px1 * scale_x
    disp_y1 = py1 * scale_y
    chart_norm = validate_normalized_box(
        rect_to_normalized_box(disp_x0, disp_y0, disp_x1, disp_y1, canvas_width=eff_pw, canvas_height=eff_ph)
    )

    geom = {
        "image_width": float(img_w),
        "image_height": float(img_h),
        "page_width": eff_pw,
        "page_height": eff_ph,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "chart_pixel_box": [round(px0, 2), round(py0, 2), round(px1, 2), round(py1, 2)],
        "chart_display_rect": [round(disp_x0, 2), round(disp_y0, 2), round(disp_x1, 2), round(disp_y1, 2)],
        "chart_display_bbox": [
            round(disp_x0, 2),
            round(disp_y0, 2),
            round(max(0.0, disp_x1 - disp_x0), 2),
            round(max(0.0, disp_y1 - disp_y0), 2),
        ],
        "chart_normalized_box": chart_norm,
        "crop_rect_px": [cl, ct, cr, cb],
        "crop_left": float(cl),
        "crop_top": float(ct),
        "crop_width": float(crop_w),
        "crop_height": float(crop_h),
        "source_rotation": (source_rotation or 0) % 360,
    }
    return crop, geom


def crop_box_to_page_coords(
    crop_box_xyxy: Sequence[float],
    crop_geom: Mapping[str, Any],
) -> Dict[str, Any]:
    """Maps a crop-local ``[cx0, cy0, cx1, cy1]`` box to original upright page coordinates."""
    cx0, cy0, cx1, cy1 = crop_box_xyxy[0], crop_box_xyxy[1], crop_box_xyxy[2], crop_box_xyxy[3]
    x0, x1 = min(cx0, cx1), max(cx0, cx1)
    y0, y1 = min(cy0, cy1), max(cy0, cy1)

    cw = max(1.0, float(crop_geom.get("crop_width", 1.0) or 1.0))
    ch = max(1.0, float(crop_geom.get("crop_height", 1.0) or 1.0))
    lx0 = max(0.0, min(cw, x0))
    ly0 = max(0.0, min(ch, y0))
    lx1 = max(0.0, min(cw, x1))
    ly1 = max(0.0, min(ch, y1))

    cl = float(crop_geom.get("crop_left", 0.0) or 0.0)
    ct = float(crop_geom.get("crop_top", 0.0) or 0.0)
    sx = float(crop_geom.get("scale_x", 1.0) or 1.0)
    sy = float(crop_geom.get("scale_y", 1.0) or 1.0)
    pw = max(1.0, float(crop_geom.get("page_width", 1.0) or 1.0))
    ph = max(1.0, float(crop_geom.get("page_height", 1.0) or 1.0))

    dx0 = (cl + lx0) * sx
    dy0 = (ct + ly0) * sy
    dx1 = (cl + lx1) * sx
    dy1 = (ct + ly1) * sy
    norm_box = rect_to_normalized_box(dx0, dy0, dx1, dy1, canvas_width=pw, canvas_height=ph)
    return {
        "local_box": [round(lx0, 2), round(ly0, 2), round(lx1, 2), round(ly1, 2)],
        "display_rect": [round(dx0, 2), round(dy0, 2), round(dx1, 2), round(dy1, 2)],
        "bbox": [
            round(dx0, 2),
            round(dy0, 2),
            round(max(0.0, dx1 - dx0), 2),
            round(max(0.0, dy1 - dy0), 2),
        ],
        "normalized_box": norm_box,
    }


def build_chart_crop_reference(
    *,
    crop_img: Image.Image,
    crop_geom: Mapping[str, Any],
    page_number: int,
    region_id: str,
    config: ChartExtractorConfig,
    source_asset_name: str = "",
) -> Dict[str, Any]:
    """Creates a content-addressed crop reference and optionally persists/embeds PNG bytes."""
    buf = io.BytesIO()
    crop_img.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    sha = hashlib.sha256(png_bytes).hexdigest()
    crop_id = f"p{page_number}-{region_id}-crop-{sha[:12]}"
    ref: Dict[str, Any] = {
        "crop_id": crop_id,
        "crop_ref": f"lore://charts/crops/{crop_id}.png",
        "mime_type": "image/png",
        "sha256": sha,
        "byte_size": len(png_bytes),
        "width_px": crop_img.width,
        "height_px": crop_img.height,
        "crop_rect_px": list(crop_geom.get("crop_rect_px") or []),
        "source_asset_name": source_asset_name or f"page_{page_number}:{region_id}",
    }

    if config.preserve_crop_image:
        if config.crop_output_dir:
            try:
                os.makedirs(config.crop_output_dir, exist_ok=True)
                safe_name = f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', crop_id)}.png"
                out_path = os.path.join(config.crop_output_dir, safe_name)
                with open(out_path, "wb") as fh:
                    fh.write(png_bytes)
                ref["crop_file_path"] = out_path
            except Exception as exc:
                logger.debug("Could not persist chart crop PNG: %s", sanitize_sensitive_data(str(exc)))
        if len(png_bytes) <= config.max_embedded_crop_bytes:
            ref["crop_image_base64"] = base64.b64encode(png_bytes).decode("ascii")
        else:
            # Store scaled review thumbnail cleanly inside budget when full crop exceeds byte cap
            thumb = crop_img.copy()
            thumb.thumbnail((480, 480))
            tbuf = io.BytesIO()
            thumb.save(tbuf, format="PNG")
            thumb.close()
            tbytes = tbuf.getvalue()
            if len(tbytes) <= config.max_embedded_crop_bytes:
                ref["crop_thumbnail_base64"] = base64.b64encode(tbytes).decode("ascii")

    return ref


# ==============================================================================
# NUMBER, UNIT & TEXT PARSING HELPERS
# ==============================================================================
_LEADING_CURRENCY_RE = re.compile(r"^\s*([$€£¥৳₹])\s*(.+)$")
_NUMERIC_CORE_RE = re.compile(
    r"^\s*([+\-\u2212\u2013]?)\s*([$€£¥৳₹]?)\s*(\d[\d,]*(?:\.\d+)?|\.\d+)\s*([kKmMbB]?)\s*(%?)\s*$"
)
_UNIT_WORD_RE = re.compile(
    r"^(USD|BDT|EUR|GBP|MWh|kWh|GWh|MW|kg|g|mg/dL|mg|ml|L|mm|cm|m|km|ms|s|min|hr|hrs|units?|pts?|°C|°F|%)$",
    re.IGNORECASE,
)
_AXIS_TITLE_UNIT_RE = re.compile(
    r"(?:\(([^()]{1,24})\)|\bin\s+(?:(millions?|billions?|thousands?|percent|USD|BDT|EUR|MWh|kg)\b|(%|°C|°F)))",
    re.IGNORECASE,
)


def parse_chart_numeric_token(raw_text: str) -> Optional[Dict[str, Any]]:
    """
    Parses a chart numeric label cleanly, preserving leading signs (including
    Unicode minus ``−``), units (currency, %, K/M/B suffix, degrees), and
    Bangla digits without hallucinating missing signs or magnitudes.
    """
    if not raw_text or not raw_text.strip():
        return None
    s = bangla_to_arabic_digits(raw_text.strip())
    # Guard against fusing two separate space-delimited numbers (e.g. "75 19") into "7519"
    if re.search(r"\d\s+\d", s) and not re.fullmatch(
        r"\s*[+\-\u2212\u2013]?[$€£¥৳₹]?\s*\d{1,3}(?:\s+\d{3})+\s*%?\s*",
        s,
    ):
        return None
    # Handle parenthetical negatives e.g. "(12.5%)" vs plain "(2024)"
    is_paren_neg = False
    if s.startswith("(") and s.endswith(")") and len(s) > 2:
        inner = s[1:-1].strip()
        if "%" in inner or "$" in inner or "." in inner or inner.startswith(("-", "\u2212")):
            s = inner
            is_paren_neg = True

    s_clean = s.replace("\u00a0", "").replace(" ", "")
    # Handle trailing unit words like "°C" or "USD" if glued
    trailing_unit = ""
    for suffix in ("°C", "°F"):
        if s_clean.endswith(suffix):
            trailing_unit = suffix
            s_clean = s_clean[: -len(suffix)]
            break

    m = _NUMERIC_CORE_RE.match(s_clean)
    if not m:
        return None

    sign_tok, curr_tok, num_tok, mag_tok, pct_tok = m.groups()
    try:
        val = float(num_tok.replace(",", ""))
    except ValueError:
        return None

    if is_paren_neg or sign_tok in ("-", "\u2212", "\u2013"):
        val = -abs(val)

    unit = curr_tok or pct_tok or trailing_unit
    scale_suffix = mag_tok.lower()
    if scale_suffix and not unit:
        unit = mag_tok
    elif scale_suffix and unit:
        unit = f"{unit} ({mag_tok})"

    return {
        "value": val,
        "unit": unit,
        "is_percent": bool(pct_tok),
        "scale_suffix": scale_suffix,
        "raw": raw_text.strip(),
    }


def _extract_unit_from_axis_title(title: str) -> str:
    if not title:
        return ""
    m = _AXIS_TITLE_UNIT_RE.search(title)
    if not m:
        return ""
    return str(m.group(1) or m.group(2) or m.group(3) or "").strip()


# ==============================================================================
# AXIS TICK CALIBRATION (NO ZERO ASSUMPTION, NO EQUAL-INTERVAL ASSUMPTION)
# ==============================================================================
def calibrate_numeric_axis(
    *,
    axis_name: str,
    orientation: str,
    tick_candidates: Sequence[Mapping[str, Any]],
    axis_origin_coord: Optional[float] = None,
    axis_title: str = "",
    max_linear_residual: float = 0.045,
    min_r2: float = 0.985,
) -> Dict[str, Any]:
    """
    Calibrates a numeric chart axis directly from visible tick marks and numeric
    tick labels.

    Strictly refuses to assume axes start at 0, refuses to assume equal spacing
    without verification, verifies monotonic ordering, tests linearity (and log10
    if non-linear), and marks uncalibratable / irregular axes invalid.
    """
    expected_coord_key = "tick_coord"
    parsed_ticks: List[Dict[str, Any]] = []
    unit_votes: List[str] = []
    scale_suffixes: List[str] = []

    for cand in tick_candidates:
        parsed = cand.get("parsed") or parse_chart_numeric_token(str(cand.get("text") or ""))
        if not parsed:
            continue
        coord_val = cand.get("tick_coord")
        if coord_val is None:
            coord_val = cand.get("coord")
        if coord_val is None:
            continue
        parsed_ticks.append({
            "coord": float(coord_val),
            "value": float(parsed["value"]),
            "text": str(cand.get("text") or parsed["raw"]),
            "unit": str(parsed.get("unit") or ""),
            "scale_suffix": str(parsed.get("scale_suffix") or ""),
            "confidence": float(cand.get("confidence", 0.9) or 0.9),
            "box": list(cand.get("box") or []),
            "stub_snapped": bool(cand.get("stub_snapped", False)),
        })
        if parsed.get("unit"):
            unit_votes.append(str(parsed["unit"]))
        if parsed.get("scale_suffix"):
            scale_suffixes.append(str(parsed["scale_suffix"]))

    # Handle mixed K / M suffixes only when uniform across all ticks
    title_unit = _extract_unit_from_axis_title(axis_title)
    detected_unit = unit_votes[0] if unit_votes else title_unit
    if len(set(u for u in unit_votes if u)) > 1:
        # Preserve ambiguity explicitly rather than silently mixing $ and % or K and M
        return {
            "axis": axis_name,
            "orientation": orientation,
            "is_valid": False,
            "reason": "conflicting_tick_units",
            "title": axis_title,
            "unit": detected_unit,
            "scale_type": "invalid",
            "ticks": parsed_ticks,
        }

    # Group near-duplicate coordinates (e.g. from redundant OCR/native pass)
    dedup_ticks: List[Dict[str, Any]] = []
    parsed_ticks.sort(key=lambda t: t["coord"])
    for tk in parsed_ticks:
        if dedup_ticks and abs(tk["coord"] - dedup_ticks[-1]["coord"]) <= 5.0 and abs(tk["value"] - dedup_ticks[-1]["value"]) < 1e-6:
            if tk["confidence"] > dedup_ticks[-1]["confidence"]:
                dedup_ticks[-1] = tk
        else:
            dedup_ticks.append(tk)

    # Disambiguate direction: vertical axis decreases in value as y increases downward;
    # horizontal axis increases in value as x increases rightward.
    if len(dedup_ticks) < 2:
        return {
            "axis": axis_name,
            "orientation": orientation,
            "is_valid": False,
            "reason": "insufficient_numeric_ticks",
            "title": axis_title,
            "unit": detected_unit,
            "scale_type": "unavailable",
            "ticks": dedup_ticks,
        }

    # Check strictly distinct pixel coords & monotonic value order
    coords = [t["coord"] for t in dedup_ticks]
    vals = [t["value"] for t in dedup_ticks]
    coord_span = max(coords) - min(coords)
    val_span = max(vals) - min(vals)
    if coord_span < 8.0 or val_span <= 1e-9:
        return {
            "axis": axis_name,
            "orientation": orientation,
            "is_valid": False,
            "reason": "degenerate_axis_span",
            "title": axis_title,
            "unit": detected_unit,
            "scale_type": "invalid",
            "ticks": dedup_ticks,
        }

    expected_dir = -1 if orientation == "vertical" else 1
    monotonic = True
    for i in range(len(dedup_ticks) - 1):
        dc = dedup_ticks[i + 1]["coord"] - dedup_ticks[i]["coord"]
        dv = dedup_ticks[i + 1]["value"] - dedup_ticks[i]["value"]
        if dc <= 1.0:
            monotonic = False
            break
        if dv * expected_dir <= 0:
            monotonic = False
            break

    if not monotonic:
        return {
            "axis": axis_name,
            "orientation": orientation,
            "is_valid": False,
            "reason": "non_monotonic_axis_ticks",
            "title": axis_title,
            "unit": detected_unit,
            "scale_type": "non_monotonic",
            "ticks": dedup_ticks,
        }

    # Inspect actual step ratios BEFORE assuming equal intervals
    val_steps = [abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1)]
    coord_steps = [abs(coords[i + 1] - coords[i]) for i in range(len(coords) - 1)]
    equal_val_intervals = (max(val_steps) / max(min(val_steps), 1e-9)) <= 1.08
    equal_coord_intervals = (max(coord_steps) / max(min(coord_steps), 1e-9)) <= 1.12

    # OLS linear regression: value = slope * coord + intercept
    n = float(len(coords))
    mean_c = sum(coords) / n
    mean_v = sum(vals) / n
    s_cc = sum((c - mean_c) ** 2 for c in coords)
    s_cv = sum((c - mean_c) * (v - mean_v) for c, v in zip(coords, vals))
    s_vv = sum((v - mean_v) ** 2 for v in vals)
    slope = s_cv / max(s_cc, 1e-12)
    intercept = mean_v - slope * mean_c
    preds = [slope * c + intercept for c in coords]
    ss_res = sum((v - p) ** 2 for v, p in zip(vals, preds))
    r2_linear = 1.0 - (ss_res / max(s_vv, 1e-12)) if len(vals) >= 3 else 1.0
    max_rel_res = max(abs(v - p) / val_span for v, p in zip(vals, preds))

    scale_type = "linear"
    log_slope = 0.0
    log_intercept = 0.0
    is_valid = (len(dedup_ticks) >= 2) and (r2_linear >= min_r2) and (max_rel_res <= max_linear_residual)

    if not is_valid and len(dedup_ticks) >= 3 and all(v > 0 for v in vals):
        log_vals = [math.log10(v) for v in vals]
        mean_lv = sum(log_vals) / n
        s_clv = sum((c - mean_c) * (lv - mean_lv) for c, lv in zip(coords, log_vals))
        s_lvlv = sum((lv - mean_lv) ** 2 for lv in log_vals)
        log_slope = s_clv / max(s_cc, 1e-12)
        log_intercept = mean_lv - log_slope * mean_c
        lpreds = [log_slope * c + log_intercept for c in coords]
        ss_lres = sum((lv - lp) ** 2 for lv, lp in zip(log_vals, lpreds))
        r2_log = 1.0 - (ss_lres / max(s_lvlv, 1e-12))
        log_span = max(log_vals) - min(log_vals)
        max_log_res = max(abs(lv - lp) / max(log_span, 1e-9) for lv, lp in zip(log_vals, lpreds))
        if r2_log >= min_r2 and max_log_res <= max_linear_residual:
            scale_type = "logarithmic"
            is_valid = True

    if not is_valid:
        return {
            "axis": axis_name,
            "orientation": orientation,
            "is_valid": False,
            "reason": "non_uniform_or_nonlinear_intervals",
            "title": axis_title,
            "unit": detected_unit,
            "scale_type": "irregular_non_uniform",
            "ticks": dedup_ticks,
            "r2_linear": round(r2_linear, 5),
            "max_rel_residual": round(max_rel_res, 5),
            "intervals_checked": len(dedup_ticks) >= 3,
            "equal_value_intervals": equal_val_intervals,
            "equal_pixel_intervals": equal_coord_intervals,
        }

    # Evaluate exact origin value at axis baseline without assuming 0!
    min_tick_val = min(vals)
    max_tick_val = max(vals)
    origin_coord = axis_origin_coord if axis_origin_coord is not None else (
        max(coords) if orientation == "vertical" else min(coords)
    )
    if scale_type == "linear":
        origin_val = slope * origin_coord + intercept
        zero_coord = (-intercept / slope) if abs(slope) > 1e-12 else None
        # Extend observed domain slightly to include axis baseline
        axis_min_val = min(min_tick_val, origin_val) if min_tick_val >= 0 or origin_val < min_tick_val else min_tick_val
        axis_max_val = max(max_tick_val, origin_val)
    else:
        origin_val = 10.0 ** (log_slope * origin_coord + log_intercept)
        zero_coord = None
        axis_min_val = min(min_tick_val, origin_val)
        axis_max_val = max(max_tick_val, origin_val)

    contains_zero = (axis_min_val - 1e-6) <= 0.0 <= (axis_max_val + 1e-6)
    starts_at_zero = abs(origin_val) <= max(1e-4, 0.015 * val_span)
    px_per_unit = abs(1.0 / slope) if scale_type == "linear" and abs(slope) > 1e-12 else 0.0
    base_uncertainty = round(max(abs(slope) * 1.5, max_rel_res * val_span), 4) if scale_type == "linear" else None

    return {
        "axis": axis_name,
        "orientation": orientation,
        "is_valid": True,
        "reason": "ok",
        "title": axis_title,
        "unit": detected_unit,
        "scale_type": scale_type,
        "ticks": dedup_ticks,
        "tick_count": len(dedup_ticks),
        "intervals_checked": len(dedup_ticks) >= 3,
        "equal_value_intervals": equal_val_intervals,
        "equal_pixel_intervals": equal_coord_intervals,
        "slope": slope,
        "intercept": intercept,
        "log_slope": log_slope,
        "log_intercept": log_intercept,
        "r2_linear": round(r2_linear, 5),
        "max_rel_residual": round(max_rel_res, 5),
        "origin_coord": round(origin_coord, 2),
        "origin_value": round(origin_val, 4),
        "axis_min_value": round(min_tick_val, 4),
        "axis_max_value": round(max_tick_val, 4),
        "starts_at_zero": starts_at_zero,
        "contains_zero": contains_zero,
        "zero_coord": round(zero_coord, 2) if zero_coord is not None and contains_zero else None,
        "pixels_per_unit": round(px_per_unit, 4),
        "estimated_uncertainty": base_uncertainty,
    }


def _coord_to_calibrated_value(coord: float, cal: Mapping[str, Any]) -> Optional[float]:
    if not cal or not cal.get("is_valid"):
        return None
    if cal.get("scale_type") == "logarithmic":
        val = 10.0 ** (float(cal["log_slope"]) * coord + float(cal["log_intercept"]))
        return val
    return float(cal["slope"]) * coord + float(cal["intercept"])


# ==============================================================================
# COLOR & PALETTE HELPERS
# ==============================================================================
def _rgb_to_hex(rgb: Sequence[int]) -> str:
    r, g, b = [max(0, min(255, v)) for v in rgb[:3]]
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgb_distance(c1: Sequence[float], c2: Sequence[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1[:3], c2[:3])))


def _is_neutral_gray_or_white(rgb: Sequence[float]) -> bool:
    r, g, b = rgb[0], rgb[1], rgb[2]
    if min(r, g, b) > 235:
        return True
    spread = max(r, g, b) - min(r, g, b)
    if spread <= 14 and max(r, g, b) > 175:
        return True
    return False


def _is_white_or_near_white(rgb: Optional[Sequence[float]]) -> bool:
    if not rgb or len(rgb) < 3:
        return True
    return min(rgb[0], rgb[1], rgb[2]) >= 244.0


# ==============================================================================
# PYMUPDF VECTOR PATH & NATIVE TEXT EXTRACTION
# ==============================================================================
def _drawing_rgb_to_255(raw_col: Any) -> Optional[Tuple[int, int, int]]:
    if raw_col is None or not isinstance(raw_col, (tuple, list)) or len(raw_col) < 3:
        return None
    try:
        vals = [float(v) for v in raw_col[:3]]
        if max(vals) <= 1.0:
            return (round(vals[0] * 255), round(vals[1] * 255), round(vals[2] * 255))
        return (round(vals[0]), round(vals[1]), round(vals[2]))
    except Exception:
        return None


def _box_intersection_area(b1: Sequence[float], b2: Sequence[float]) -> float:
    ix0 = max(b1[0], b2[0])
    iy0 = max(b1[1], b2[1])
    ix1 = min(b1[2], b2[2])
    iy1 = min(b1[3], b2[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return (ix1 - ix0) * (iy1 - iy0)


def _expand_box_with_adjacent_chart_text(
    base_disp_rect: Tuple[float, float, float, float],
    all_page_spans: Sequence[Mapping[str, Any]],
    page_w: float,
    page_h: float,
    excluded_rects: Sequence[Tuple[float, float, float, float]] = (),
) -> Tuple[float, float, float, float]:
    """
    Expands a tightly bounded vector drawing cluster to encompass nearby axis tick
    labels, axis titles, legend text, and chart title without crossing into
    unrelated tables or distant prose paragraphs.
    """
    x0, y0, x1, y1 = base_disp_rect
    pad_l, pad_r, pad_t, pad_b = 75.0, 75.0, 48.0, 48.0
    env = (max(0.0, x0 - pad_l), max(0.0, y0 - pad_t), min(page_w, x1 + pad_r), min(page_h, y1 + pad_b))

    nx0, ny0, nx1, ny1 = x0, y0, x1, y1
    for sp in all_page_spans:
        sb = sp["bbox"]
        sw = sb[2] - sb[0]
        sh = sb[3] - sb[1]
        if sw <= 0 or sh <= 0:
            continue
        if _box_intersection_area(sb, env) <= 0.0:
            continue
        if any(_box_intersection_area(sb, ex) > 0.25 * sw * sh for ex in excluded_rects):
            continue
        txt = str(sp.get("text") or "").strip()
        if not txt or len(txt) > 90:
            continue
        # Require reasonable alignment with chart vertical/horizontal bands
        aligned_h = (sb[2] >= x0 - pad_l and sb[0] <= x1 + pad_r and sb[3] >= y0 - 14.0 and sb[1] <= y1 + pad_b)
        aligned_top = (sb[0] >= x0 - 40.0 and sb[2] <= x1 + 40.0 and y0 - pad_t <= sb[1] <= y0 + 8.0 and len(txt.split()) <= 12)
        if aligned_h or aligned_top:
            nx0 = min(nx0, sb[0] - 4.0)
            ny0 = min(ny0, sb[1] - 4.0)
            nx1 = max(nx1, sb[2] + 4.0)
            ny1 = max(ny1, sb[3] + 4.0)

    return (max(0.0, nx0), max(0.0, ny0), min(page_w, nx1), min(page_h, ny1))


def _collect_pymupdf_text_spans(pymupdf_page: Any) -> List[Dict[str, Any]]:
    """Extracts structured native spans preserving direction vector (for rotated axes)."""
    spans_out: List[Dict[str, Any]] = []
    if pymupdf_page is None or not HAS_PYMUPDF:
        return spans_out
    try:
        tdict = pymupdf_page.get_text("dict") or {}
    except Exception:
        return spans_out

    rot = int(getattr(pymupdf_page, "rotation", 0) or 0) % 360
    for block in tdict.get("blocks") or []:
        if int(block.get("type", 0) or 0) != 0:
            continue
        for line in block.get("lines") or []:
            ldir = line.get("dir") or (1.0, 0.0)
            dx, dy = float(ldir[0]), float(ldir[1])
            # Rotate direction vector cleanly into display space
            if rot == 90:
                dx, dy = -dy, dx
            elif rot == 180:
                dx, dy = -dx, -dy
            elif rot == 270:
                dx, dy = dy, -dx
            is_vertical_text = abs(dy) > 0.65

            line_spans = line.get("spans") or []
            # If line holds short spaced words vs one unit token, keep span-level + line-level cleanly
            for sp in line_spans:
                txt = str(sp.get("text") or "").strip()
                if not txt:
                    continue
                disp_b = _transform_pdf_rect_to_display(sp.get("bbox"), pymupdf_page)
                if disp_b is None:
                    continue
                col_int = int(sp.get("color", 0) or 0)
                col_rgb = ((col_int >> 16) & 255, (col_int >> 8) & 255, col_int & 255)
                spans_out.append({
                    "text": txt,
                    "bbox": disp_b,
                    "font_size": float(sp.get("size", 10.0) or 10.0),
                    "color_rgb": col_rgb,
                    "is_vertical_text": is_vertical_text,
                    "confidence": 0.99,
                    "source": "native_pdf",
                })
    return spans_out


def extract_native_pdf_chart_primitives(
    *,
    pymupdf_page: Any,
    display_rect_xyxy: Sequence[float],
    crop_geom: Mapping[str, Any],
) -> Dict[str, Any]:
    """
    Extracts PyMuPDF vector drawings (rects, lines, curves/pie sectors, scatter blobs),
    embedded raster overlaps, and native PDF text spans inside ``display_rect_xyxy``,
    converted accurately into crop-local pixel coordinates.
    """
    out: Dict[str, Any] = {
        "has_pymupdf": bool(pymupdf_page is not None and HAS_PYMUPDF),
        "vector_primitive_count": 0,
        "rects": [],
        "lines": [],
        "curves": [],
        "pie_sectors": [],
        "scatter_markers": [],
        "native_tokens": [],
        "raster_image_overlaps": [],
    }
    if pymupdf_page is None or not HAS_PYMUPDF:
        return out

    rx0, ry0, rx1, ry1 = display_rect_xyxy[0], display_rect_xyxy[1], display_rect_xyxy[2], display_rect_xyxy[3]
    pw = max(1.0, float(crop_geom.get("page_width", 1.0) or 1.0))
    ph = max(1.0, float(crop_geom.get("page_height", 1.0) or 1.0))
    cl = float(crop_geom.get("crop_left", 0.0) or 0.0)
    ct = float(crop_geom.get("crop_top", 0.0) or 0.0)
    sx = float(crop_geom.get("scale_x", 1.0) or 1.0)
    sy = float(crop_geom.get("scale_y", 1.0) or 1.0)

    def _to_crop_x(dx: float) -> float:
        return (dx / sx) - cl

    def _to_crop_y(dy: float) -> float:
        return (dy / sy) - ct

    def _rect_to_crop(disp_b: Sequence[float]) -> Tuple[float, float, float, float]:
        cx0 = _to_crop_x(disp_b[0])
        cy0 = _to_crop_y(disp_b[1])
        cx1 = _to_crop_x(disp_b[2])
        cy1 = _to_crop_y(disp_b[3])
        return (min(cx0, cx1), min(cy0, cy1), max(cx0, cx1), max(cy0, cy1))

    region_box = (rx0 - 6.0, ry0 - 6.0, rx1 + 6.0, ry1 + 6.0)
    region_area = max(1.0, (rx1 - rx0) * (ry1 - ry0))

    # 1. Embedded raster images inside chart box
    try:
        for img_info in pymupdf_page.get_images(full=False) or []:
            xref = int(img_info[0]) if img_info else 0
            if xref <= 0:
                continue
            for r in pymupdf_page.get_image_rects(xref) or []:
                db = _transform_pdf_rect_to_display(r, pymupdf_page)
                if db is None:
                    continue
                inter = _box_intersection_area(db, region_box)
                if inter > 0.25 * region_area:
                    out["raster_image_overlaps"].append({
                        "xref": xref,
                        "display_rect": list(db),
                        "crop_box": list(_rect_to_crop(db)),
                        "coverage_ratio": round(inter / region_area, 3),
                    })
    except Exception:
        pass

    # 2. Vector drawing primitives
    try:
        drawings = pymupdf_page.get_drawings() or []
    except Exception:
        drawings = []

    for d in drawings:
        db = _transform_pdf_rect_to_display(d.get("rect"), pymupdf_page)
        if db is None:
            continue
        dw = db[2] - db[0]
        dh = db[3] - db[1]
        if dw > 0.94 * pw and dh > 0.94 * ph:
            continue
        if _box_intersection_area(db, region_box) <= 0.0 and not (
            db[0] >= region_box[0] - 12 and db[2] <= region_box[2] + 12 and db[1] >= region_box[1] - 12 and db[3] <= region_box[3] + 12
        ):
            continue

        fill_rgb = _drawing_rgb_to_255(d.get("fill"))
        stroke_rgb = _drawing_rgb_to_255(d.get("color"))
        lw = float(d.get("width", 1.0) or 1.0)
        items = list(d.get("items") or [])
        cbox = _rect_to_crop(db)
        cw = cbox[2] - cbox[0]
        ch = cbox[3] - cbox[1]

        out["vector_primitive_count"] += 1

        item_types = [it[0] for it in items if it]
        # Skip pure page/chart full background fill rectangle
        if cw > 0.85 * float(crop_geom.get("crop_width", 1.0)) and ch > 0.85 * float(crop_geom.get("crop_height", 1.0)) and _is_white_or_near_white(fill_rgb):
            continue

        # Detect filled/stroked pure rectangles (`re`) or closed 4-line rectangle
        if item_types == ["re"] or (len(items) == 1 and item_types[0] == "re"):
            out["rects"].append({
                "bbox_crop": cbox,
                "bbox_display": db,
                "fill_rgb": fill_rgb,
                "stroke_rgb": stroke_rgb,
                "linewidth": lw,
            })
            # Check small square scatter marker too
            if fill_rgb and not _is_white_or_near_white(fill_rgb) and 2.5 <= cw <= 18.0 and 2.5 <= ch <= 18.0 and abs(cw - ch) <= 3.0:
                out["scatter_markers"].append({
                    "cx": 0.5 * (cbox[0] + cbox[2]),
                    "cy": 0.5 * (cbox[1] + cbox[3]),
                    "bbox_crop": cbox,
                    "color_rgb": fill_rgb,
                    "shape": "square",
                })
            continue

        # Detect closed pie sector (`c` arc(s) + `l` radii)
        c_items = [it for it in items if it and it[0] == "c"]
        l_items = [it for it in items if it and it[0] == "l"]
        if fill_rgb and not _is_white_or_near_white(fill_rgb) and len(c_items) >= 1 and len(l_items) >= 2:
            # Find shared radial apex vertex among l_items: true pie center does NOT lie on curve endpoints
            pts_l: List[Tuple[float, float]] = []
            for lit in l_items:
                for pt in lit[1:3]:
                    dp = _transform_pdf_point_to_display(pt, pymupdf_page)
                    pts_l.append((_to_crop_x(dp[0]), _to_crop_y(dp[1])))

            curve_ep: List[Tuple[float, float]] = []
            for cit in c_items:
                for ep in (cit[1], cit[-1]):
                    dp = _transform_pdf_point_to_display(ep, pymupdf_page)
                    curve_ep.append((_to_crop_x(dp[0]), _to_crop_y(dp[1])))

            best_apex: Optional[Tuple[float, float]] = None
            best_score: Optional[Tuple[int, int, float]] = None
            for pt in pts_l:
                ep_hits = sum(1 for cp in curve_ep if math.hypot(pt[0] - cp[0], pt[1] - cp[1]) <= 3.0)
                l_hits = sum(1 for other in pts_l if math.hypot(pt[0] - other[0], pt[1] - other[1]) <= 2.5)
                min_ep_dist = min((math.hypot(pt[0] - cp[0], pt[1] - cp[1]) for cp in curve_ep), default=0.0)
                # Prefer vertex with 0 curve-endpoint matches, most l-hits, farthest from curve endpoints
                score = (-ep_hits, l_hits, min_ep_dist)
                if best_score is None or score > best_score:
                    best_score = score
                    best_apex = pt

            if best_apex is not None and best_score is not None and (-best_score[0]) == 0:
                apex_pt = best_apex
                arc_pts = [cp for cp in curve_ep if math.hypot(cp[0] - apex_pt[0], cp[1] - apex_pt[1]) > 8.0]
                if len(arc_pts) >= 2:
                    radii = [math.hypot(p[0] - apex_pt[0], p[1] - apex_pt[1]) for p in arc_pts]
                    r_est = sum(radii) / len(radii)
                    # Evaluate cubic Bezier midpoint at t=0.5 (0.125*p0 + 0.375*c1 + 0.375*c2 + 0.125*p3)
                    ordered_pts: List[Tuple[float, float]] = []
                    for cit in c_items:
                        dp0 = _transform_pdf_point_to_display(cit[1], pymupdf_page)
                        dpc1 = _transform_pdf_point_to_display(cit[2], pymupdf_page)
                        dpc2 = _transform_pdf_point_to_display(cit[3] if len(cit) > 3 else cit[2], pymupdf_page)
                        dp1 = _transform_pdf_point_to_display(cit[-1], pymupdf_page)
                        p0_c = (_to_crop_x(dp0[0]), _to_crop_y(dp0[1]))
                        c1_c = (_to_crop_x(dpc1[0]), _to_crop_y(dpc1[1]))
                        c2_c = (_to_crop_x(dpc2[0]), _to_crop_y(dpc2[1]))
                        p1_c = (_to_crop_x(dp1[0]), _to_crop_y(dp1[1]))
                        mid_c = (
                            0.125 * p0_c[0] + 0.375 * c1_c[0] + 0.375 * c2_c[0] + 0.125 * p1_c[0],
                            0.125 * p0_c[1] + 0.375 * c1_c[1] + 0.375 * c2_c[1] + 0.125 * p1_c[1],
                        )
                        if not ordered_pts or math.hypot(p0_c[0] - ordered_pts[-1][0], p0_c[1] - ordered_pts[-1][1]) > 1.5:
                            ordered_pts.append(p0_c)
                        ordered_pts.append(mid_c)
                        ordered_pts.append(p1_c)
                    total_signed = 0.0
                    for idx_p in range(len(ordered_pts) - 1):
                        a1 = math.atan2(ordered_pts[idx_p][1] - apex_pt[1], ordered_pts[idx_p][0] - apex_pt[0])
                        a2 = math.atan2(ordered_pts[idx_p + 1][1] - apex_pt[1], ordered_pts[idx_p + 1][0] - apex_pt[0])
                        delta = (math.degrees(a2 - a1) + 540.0) % 360.0 - 180.0
                        total_signed += delta
                    sweep_deg = abs(total_signed)
                    if 1.0 <= sweep_deg <= 360.0:
                        start_a = math.degrees(math.atan2(ordered_pts[0][1] - apex_pt[1], ordered_pts[0][0] - apex_pt[0])) % 360.0
                        end_a = math.degrees(math.atan2(ordered_pts[-1][1] - apex_pt[1], ordered_pts[-1][0] - apex_pt[0])) % 360.0
                        mid_a = (start_a + (sweep_deg * 0.5 if total_signed >= 0 else -sweep_deg * 0.5)) % 360.0
                        out["pie_sectors"].append({
                            "center_crop": list(apex_pt),
                            "radius_px": r_est,
                            "start_deg": start_a,
                            "end_deg": end_a,
                            "mid_deg": mid_a,
                            "sweep_deg": sweep_deg,
                            "bbox_crop": cbox,
                            "color_rgb": fill_rgb,
                        })
                        continue

        # Detect compact circle scatter marker (`draw_circle`: 4 curves, small radius <= 18px)
        if c_items and not l_items and 3.0 <= cw <= 22.0 and 3.0 <= ch <= 22.0 and abs(cw - ch) <= 4.0:
            col = fill_rgb or stroke_rgb
            if col and not _is_white_or_near_white(col):
                out["scatter_markers"].append({
                    "cx": 0.5 * (cbox[0] + cbox[2]),
                    "cy": 0.5 * (cbox[1] + cbox[3]),
                    "bbox_crop": cbox,
                    "color_rgb": col,
                    "shape": "circle",
                })
                continue

        # Extract connected polyline / straight line runs without jumping across disjoint tick stubs
        if l_items:
            raw_runs: List[List[Tuple[float, float]]] = []
            for lit in l_items:
                dp1 = _transform_pdf_point_to_display(lit[1], pymupdf_page)
                dp2 = _transform_pdf_point_to_display(lit[2], pymupdf_page)
                p1 = (_to_crop_x(dp1[0]), _to_crop_y(dp1[1]))
                p2 = (_to_crop_x(dp2[0]), _to_crop_y(dp2[1]))
                if math.hypot(p2[0] - p1[0], p2[1] - p1[1]) < 1.0:
                    continue
                if raw_runs and len(raw_runs[-1]) >= 2 and math.hypot(p1[0] - raw_runs[-1][-1][0], p1[1] - raw_runs[-1][-1][1]) <= 2.5:
                    # Skip immediate round-trip return line (draw_line emits forward + backward)
                    if math.hypot(p2[0] - raw_runs[-1][-2][0], p2[1] - raw_runs[-1][-2][1]) > 1.5:
                        raw_runs[-1].append(p2)
                else:
                    raw_runs.append([p1, p2])

            closed_frame = False
            if len(raw_runs) == 1:
                seg_pts = raw_runs[0]
                if len(seg_pts) >= 4 and math.hypot(seg_pts[0][0] - seg_pts[-1][0], seg_pts[0][1] - seg_pts[-1][1]) <= 2.0:
                    xs_r = [p[0] for p in seg_pts]
                    ys_r = [p[1] for p in seg_pts]
                    rbox = (min(xs_r), min(ys_r), max(xs_r), max(ys_r))
                    if (rbox[2] - rbox[0]) > 4 and (rbox[3] - rbox[1]) > 4:
                        closed_frame = True
                        out["rects"].append({
                            "bbox_crop": rbox,
                            "bbox_display": db,
                            "fill_rgb": fill_rgb,
                            "stroke_rgb": stroke_rgb,
                            "linewidth": lw,
                        })
                        for k in range(len(seg_pts) - 1):
                            out["lines"].append({
                                "p1": seg_pts[k],
                                "p2": seg_pts[k + 1],
                                "color_rgb": stroke_rgb or (0, 0, 0),
                                "linewidth": lw,
                            })
            if not closed_frame:
                for run in raw_runs:
                    if len(run) >= 2:
                        out["lines"].append({
                            "points": run,
                            "p1": run[0],
                            "p2": run[-1],
                            "color_rgb": stroke_rgb or fill_rgb or (0, 0, 0),
                            "linewidth": lw,
                        })

        if c_items:
            pts_c: List[Tuple[float, float]] = []
            for cit in c_items:
                dp0 = _transform_pdf_point_to_display(cit[1], pymupdf_page)
                dp1 = _transform_pdf_point_to_display(cit[-1], pymupdf_page)
                pts_c.append((_to_crop_x(dp0[0]), _to_crop_y(dp0[1])))
                pts_c.append((_to_crop_x(dp1[0]), _to_crop_y(dp1[1])))
            out["curves"].append({
                "bbox_crop": cbox,
                "points": pts_c,
                "color_rgb": stroke_rgb or fill_rgb or (0, 0, 0),
                "fill_rgb": fill_rgb,
            })

    # 3. Native PDF text spans inside chart box
    for sp in _collect_pymupdf_text_spans(pymupdf_page):
        sb = sp["bbox"]
        sw = max(1.0, sb[2] - sb[0])
        sh = max(1.0, sb[3] - sb[1])
        inter = _box_intersection_area(sb, region_box)
        if inter < 0.35 * sw * sh:
            continue
        cb = _rect_to_crop(sb)
        out["native_tokens"].append({
            "text": sp["text"],
            "bbox_crop": cb,
            "cx": 0.5 * (cb[0] + cb[2]),
            "cy": 0.5 * (cb[1] + cb[3]),
            "width": cb[2] - cb[0],
            "height": cb[3] - cb[1],
            "bbox_display": sb,
            "color_rgb": sp["color_rgb"],
            "font_size": sp["font_size"],
            "is_vertical_text": sp["is_vertical_text"],
            "confidence": sp["confidence"],
            "source": "native_pdf",
        })

    return out


# ==============================================================================
# OPENCV CHART REGION DETECTOR & RASTER PRIMITIVE INSPECTOR
# ==============================================================================
def _merge_boxes(
    boxes: Sequence[Tuple[float, float, float, float]],
    gap: float = 16.0,
) -> List[Tuple[float, float, float, float]]:
    if not boxes:
        return []
    merged: List[List[float]] = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        out: List[List[float]] = []
        while merged:
            cur = merged.pop(0)
            i = 0
            while i < len(merged):
                oth = merged[i]
                if not (
                    oth[2] + gap < cur[0]
                    or cur[2] + gap < oth[0]
                    or oth[3] + gap < cur[1]
                    or cur[3] + gap < oth[1]
                ):
                    cur[0] = min(cur[0], oth[0])
                    cur[1] = min(cur[1], oth[1])
                    cur[2] = max(cur[2], oth[2])
                    cur[3] = max(cur[3], oth[3])
                    merged.pop(i)
                    changed = True
                else:
                    i += 1
            out.append(cur)
        merged = out
    return [(b[0], b[1], b[2], b[3]) for b in merged]


def detect_chart_candidates_in_pdf_page(
    *,
    pymupdf_page: Any,
    page_number: int,
    table_rects_display: Sequence[Tuple[float, float, float, float]] = (),
    min_chart_pt: float = 48.0,
    min_vector_primitives: int = 4,
    ocr_check_raster: bool = True,
) -> List[Dict[str, Any]]:
    """
    Detects chart regions on a PyMuPDF page from vector drawing clusters (expanded
    to include adjacent axis labels/titles/legends) and chart-like embedded images.
    """
    if pymupdf_page is None or not HAS_PYMUPDF:
        return []

    tr_page = pymupdf_page.rect
    # page.rect in PyMuPDF is ALREADY in upright display dimensions (even when page.rotation != 0)
    pw = max(1.0, float(tr_page.width))
    ph = max(1.0, float(tr_page.height))
    all_spans = _collect_pymupdf_text_spans(pymupdf_page)

    def _inside_table(rect: Tuple[float, float, float, float]) -> bool:
        ra = max(1.0, (rect[2] - rect[0]) * (rect[3] - rect[1]))
        for tb in table_rects_display:
            if _box_intersection_area(rect, tb) >= 0.45 * ra:
                return True
        return False

    draw_boxes: List[Tuple[float, float, float, float]] = []
    prim_count = 0
    try:
        drawings = pymupdf_page.get_drawings() or []
    except Exception:
        drawings = []

    for d in drawings:
        db = _transform_pdf_rect_to_display(d.get("rect"), pymupdf_page)
        if db is None:
            continue
        dw, dh = db[2] - db[0], db[3] - db[1]
        if dw > 0.94 * pw and dh > 0.94 * ph:
            continue
        if _inside_table(db):
            continue
        fill_rgb = _drawing_rgb_to_255(d.get("fill"))
        if dw > 0.85 * pw and dh > 0.85 * ph and _is_white_or_near_white(fill_rgb):
            continue
        if max(dw, dh) >= 4.0:
            draw_boxes.append(db)
            prim_count += max(1, len(d.get("items") or []))

    candidates: List[Dict[str, Any]] = []
    if len(draw_boxes) >= 2 and prim_count >= min_vector_primitives:
        clusters = _merge_boxes(draw_boxes, gap=18.0)
        for idx, cl in enumerate(clusters, start=1):
            cw, ch = cl[2] - cl[0], cl[3] - cl[1]
            if cw >= min_chart_pt and ch >= min_chart_pt and not _inside_table(cl):
                expanded = _expand_box_with_adjacent_chart_text(
                    cl, all_spans, pw, ph, excluded_rects=table_rects_display
                )
                candidates.append({
                    "bbox_display": expanded,
                    "plot_cluster_display": cl,
                    "source_mode": ChartSourceMode.VECTOR.value,
                    "region_id": f"p{page_number}-chart-vec{idx}",
                    "source_asset_name": f"pdf:page_{page_number}:chart_vec_{idx}",
                })

    return candidates


def is_likely_chart_raster_opencv(image: Image.Image) -> bool:
    """Fast OpenCV test deciding if an image crop contains chart structure (axes/pie/series)."""
    if not HAS_OPENCV or not HAS_NUMPY or cv2 is None or np is None:
        return False
    if image.width < 48 or image.height < 48:
        return False
    bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    non_white = (gray < 215).astype(np.uint8) * 255

    # Horizontal & vertical axis-scale lines
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, int(w * 0.25)), 1))
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, int(h * 0.25))))
    h_lines = cv2.morphologyEx(non_white, cv2.MORPH_OPEN, kh)
    v_lines = cv2.morphologyEx(non_white, cv2.MORPH_OPEN, kv)
    has_axes = bool(np.any(h_lines > 0) and np.any(v_lines > 0))
    if has_axes:
        return True

    # Circular pie candidate check
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    color_mask = ((hsv[:, :, 1] > 45) & (hsv[:, :, 2] < 248)).astype(np.uint8) * 255
    contours, _ = cv2.findContours(color_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total_color_area = sum(cv2.contourArea(c) for c in contours)
    if total_color_area >= 0.08 * w * h:
        combined = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        c2, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in c2:
            area = cv2.contourArea(cnt)
            perim = cv2.arcLength(cnt, True)
            if area >= 0.05 * w * h and perim > 10.0:
                circ = 4.0 * math.pi * area / (perim * perim)
                if circ >= 0.58:
                    return True
    return False


def detect_chart_regions_opencv(
    page_image: Image.Image,
    *,
    min_width: int = 80,
    min_height: int = 80,
) -> List[Tuple[float, float, float, float]]:
    """
    Detects chart regions on a standalone raster image using OpenCV axis frame and
    circular pie segmentation, expanding margins to include tick/title labels.
    """
    if not HAS_OPENCV or not HAS_NUMPY or cv2 is None or np is None:
        return []
    w, h = page_image.size
    if w < min_width or h < min_height:
        return []

    bgr = cv2.cvtColor(np.asarray(page_image.convert("RGB")), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    fg = (gray < 218).astype(np.uint8) * 255

    # Detect intersection pairs of long horizontal + vertical axis lines
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (max(24, int(w * 0.22)), 1))
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(24, int(h * 0.22))))
    h_mask = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kh)
    v_mask = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kv)
    ax_union = cv2.dilate(cv2.bitwise_or(h_mask, v_mask), np.ones((9, 9), np.uint8))

    boxes: List[Tuple[float, float, float, float]] = []
    num_lbl, _, stats, _ = cv2.connectedComponentsWithStats(ax_union, connectivity=8)
    for lbl in range(1, num_lbl):
        bx, by, bw, bh, _ = [int(v) for v in stats[lbl]]
        if bw >= min_width and bh >= min_height:
            # Verify both H and V strokes sit inside this frame
            if np.any(h_mask[by : by + bh, bx : bx + bw] > 0) and np.any(v_mask[by : by + bh, bx : bx + bw] > 0):
                pad_l = min(bx, max(65, int(bw * 0.24)))
                pad_r = min(w - (bx + bw), max(55, int(bw * 0.20)))
                pad_t = min(by, max(45, int(bh * 0.18)))
                pad_b = min(h - (by + bh), max(50, int(bh * 0.20)))
                boxes.append((float(bx - pad_l), float(by - pad_t), float(bx + bw + pad_r), float(by + bh + pad_b)))

    # Detect colored pie circles outside already found axis boxes
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    color_mask = ((hsv[:, :, 1] > 45) & (hsv[:, :, 2] < 248)).astype(np.uint8) * 255
    pie_closed = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(pie_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        area = cv2.contourArea(cnt)
        perim = cv2.arcLength(cnt, True)
        if area < 900.0 or perim < 30.0:
            continue
        circ = 4.0 * math.pi * area / (perim * perim)
        if circ >= 0.62:
            cx, cy, cw, ch = cv2.boundingRect(cnt)
            cand = (float(max(0, cx - 75)), float(max(0, cy - 50)), float(min(w, cx + cw + 90)), float(min(h, cy + ch + 45)))
            if not any(_box_intersection_area(cand, eb) > 0.4 * ((cand[2] - cand[0]) * (cand[3] - cand[1])) for eb in boxes):
                boxes.append(cand)

    return _merge_boxes(boxes, gap=14.0)


def _detect_raster_plot_axes_opencv(
    crop_bgr: Any,
    crop_w: int,
    crop_h: int,
) -> Dict[str, Any]:
    """
    Detects chart axis lines, interior zero baseline, physical tick marks, and
    gridlines in an image crop using OpenCV morphological filters.
    """
    info: Dict[str, Any] = {
        "has_axes": False,
        "plot_box": (int(crop_w * 0.12), int(crop_h * 0.10), int(crop_w * 0.90), int(crop_h * 0.84)),
        "x_axis_y": None,
        "y_axis_x": None,
        "y2_axis_x": None,
        "top_border_y": None,
        "zero_hline_y": None,
        "h_lines": [],
        "v_lines": [],
        "h_grid_ys": [],
        "v_grid_xs": [],
        "y1_tick_stubs": [],
        "y2_tick_stubs": [],
        "x_tick_stubs": [],
        "is_dark_bg": False,
    }
    if not HAS_OPENCV or not HAS_NUMPY or cv2 is None or np is None:
        return info

    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    # Estimate canvas background from corners
    border_vals = np.concatenate([gray[:3, :].ravel(), gray[-3:, :].ravel(), gray[:, :3].ravel(), gray[:, -3:].ravel()])
    bg_med = float(np.median(border_vals)) if border_vals.size else 255.0
    is_dark = bg_med < 100.0
    info["is_dark_bg"] = is_dark
    diff = np.abs(gray.astype(np.int16) - round(bg_med))
    ink = (diff > 28).astype(np.uint8) * 255

    # Low-saturation mask captures black/gray axes/ticks without mistaking colored bars
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    neutral_ink = ((diff > 35) & (hsv[:, :, 1] < 75)).astype(np.uint8) * 255

    min_hlen = max(24, int(crop_w * 0.28))
    min_vlen = max(24, int(crop_h * 0.25))
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (min_hlen, 1))
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_vlen))

    h_morph = cv2.morphologyEx(neutral_ink, cv2.MORPH_OPEN, kh)
    v_morph = cv2.morphologyEx(neutral_ink, cv2.MORPH_OPEN, kv)

    # Scale axis thickness & tick stub tolerances proportionally so high-DPI PDFs (e.g. 300 DPI) detect cleanly
    scale_px = max(1.0, min(crop_w, crop_h) / 450.0)
    max_axis_thick = max(8, min(26, round(min(crop_w, crop_h) * 0.016)))

    # Extract merged horizontal line bands (y, x0, x1, thickness)
    h_comps, _, h_stats, _ = cv2.connectedComponentsWithStats(h_morph, connectivity=8)
    h_lines: List[Dict[str, Any]] = []
    for lbl in range(1, h_comps):
        x, y, ww, hh, _ = [int(v) for v in h_stats[lbl]]
        if ww >= min_hlen and hh <= max_axis_thick:
            h_lines.append({"y": y + 0.5 * (hh - 1), "x0": float(x), "x1": float(x + ww), "thickness": hh})

    v_comps, _, v_stats, _ = cv2.connectedComponentsWithStats(v_morph, connectivity=8)
    v_lines: List[Dict[str, Any]] = []
    for lbl in range(1, v_comps):
        x, y, ww, hh, _ = [int(v) for v in v_stats[lbl]]
        if hh >= min_vlen and ww <= max_axis_thick:
            v_lines.append({"x": x + 0.5 * (ww - 1), "y0": float(y), "y1": float(y + hh), "thickness": ww})

    # Fallback: include darker edge pixels if colored axes were used (e.g. blue/green axis)
    if not h_lines or not v_lines:
        h_morph2 = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kh)
        v_morph2 = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kv)
        if not h_lines:
            hc2, _, hs2, _ = cv2.connectedComponentsWithStats(h_morph2, connectivity=8)
            for lbl in range(1, hc2):
                x, y, ww, hh, _ = [int(v) for v in hs2[lbl]]
                if ww >= min_hlen and hh <= max_axis_thick:
                    h_lines.append({"y": y + 0.5 * (hh - 1), "x0": float(x), "x1": float(x + ww), "thickness": hh})
        if not v_lines:
            vc2, _, vs2, _ = cv2.connectedComponentsWithStats(v_morph2, connectivity=8)
            for lbl in range(1, vc2):
                x, y, ww, hh, _ = [int(v) for v in vs2[lbl]]
                if hh >= min_vlen and ww <= max_axis_thick:
                    v_lines.append({"x": x + 0.5 * (ww - 1), "y0": float(y), "y1": float(y + hh), "thickness": ww})

    h_lines.sort(key=lambda d: d["y"])
    v_lines.sort(key=lambda d: d["x"])
    info["h_lines"] = h_lines
    info["v_lines"] = v_lines

    if h_lines and v_lines:
        info["has_axes"] = True
        left_candidates = [vl for vl in v_lines if vl["x"] <= crop_w * 0.45]
        y_axis = min(left_candidates, key=lambda vl: vl["x"]) if left_candidates else v_lines[0]
        y_ax_x = float(y_axis["x"])
        info["y_axis_x"] = y_ax_x

        right_candidates = [vl for vl in v_lines if vl["x"] >= max(y_ax_x + crop_w * 0.25, crop_w * 0.55)]
        y2_ax_x = float(max(right_candidates, key=lambda vl: vl["x"])["x"]) if right_candidates else None
        info["y2_axis_x"] = y2_ax_x

        # Bottom-most long horizontal axis is X-axis (or internal zero line if bottom has no frame)
        bottom_cands = [hl for hl in h_lines if hl["y"] >= crop_h * 0.35]
        x_axis = max(bottom_cands, key=lambda hl: hl["y"]) if bottom_cands else h_lines[-1]
        x_ax_y = float(x_axis["y"])
        info["x_axis_y"] = x_ax_y

        top_cands = [hl for hl in h_lines if hl["y"] < min(y_axis["y0"] + 15.0, crop_h * 0.35)]
        if top_cands and top_cands[0]["y"] < x_ax_y - 25:
            info["top_border_y"] = float(top_cands[0]["y"])

        px0 = round(max(y_ax_x, float(x_axis["x0"])))
        px1 = round(y2_ax_x if y2_ax_x is not None else max(float(x_axis["x1"]), px0 + crop_w * 0.45))
        py0 = round(min(float(y_axis["y0"]), info["top_border_y"] or float(y_axis["y0"])))
        py1 = round(max(x_ax_y, float(y_axis["y1"])))
        px1 = min(crop_w - 2, max(px0 + 20, px1))
        py1 = min(crop_h - 2, max(py0 + 20, py1))
        info["plot_box"] = (px0, py0, px1, py1)

        # Interior thin grid lines
        for hl in h_lines:
            if py0 + 6 < hl["y"] < py1 - 6:
                info["h_grid_ys"].append(round(hl["y"], 2))
        for vl in v_lines:
            if px0 + 6 < vl["x"] < px1 - 6:
                info["v_grid_xs"].append(round(vl["x"], 2))

        # Tick stub projection along left Y1 axis, right Y2 axis, and bottom X axis
        # Start outside half-thickness of each axis spine so high-DPI spines never clip stubs
        max_stub_thick = max(5, round(6.0 * scale_px))
        stub_depth = max(8, round(9.0 * scale_px))
        stub_gap = max(1, round(0.8 * scale_px))
        y_pad = max(3, round(3.0 * scale_px))
        y_scan_0 = max(0, py0 - y_pad)
        y_scan_1 = min(crop_h, py1 + y_pad)

        y_half_t = 0.5 * float(y_axis.get("thickness", 2))
        y_strip_x1 = max(1, round(y_ax_x - y_half_t) - stub_gap)
        y_strip_x0 = max(0, y_strip_x1 - stub_depth)
        if y_strip_x1 > y_strip_x0 and y_scan_1 > y_scan_0:
            row_hits = np.mean(neutral_ink[y_scan_0:y_scan_1, y_strip_x0:y_strip_x1] > 0, axis=1)
            in_stub = False
            start_r = 0
            for r_idx, val in enumerate(row_hits):
                if val >= 0.35 and not in_stub:
                    in_stub = True
                    start_r = r_idx
                elif val < 0.35 and in_stub:
                    in_stub = False
                    if 1 <= (r_idx - start_r) <= max_stub_thick:
                        info["y1_tick_stubs"].append(y_scan_0 + 0.5 * (start_r + r_idx - 1))

        if y2_ax_x is not None:
            y2_axis = max(right_candidates, key=lambda vl: vl["x"])
            y2_half_t = 0.5 * float(y2_axis.get("thickness", 2))
            r_x0 = min(crop_w - 1, round(y2_ax_x + y2_half_t) + stub_gap)
            r_x1 = min(crop_w, r_x0 + stub_depth)
            if r_x1 > r_x0 and y_scan_1 > y_scan_0:
                row_hits2 = np.mean(neutral_ink[y_scan_0:y_scan_1, r_x0:r_x1] > 0, axis=1)
                in_stub = False
                start_r = 0
                for r_idx, val in enumerate(row_hits2):
                    if val >= 0.35 and not in_stub:
                        in_stub = True
                        start_r = r_idx
                    elif val < 0.35 and in_stub:
                        in_stub = False
                        if 1 <= (r_idx - start_r) <= max_stub_thick:
                            info["y2_tick_stubs"].append(y_scan_0 + 0.5 * (start_r + r_idx - 1))

        x_scan_0 = max(0, px0 - y_pad)
        x_scan_1 = min(crop_w, px1 + y_pad)
        x_half_t = 0.5 * float(x_axis.get("thickness", 2))
        x_strip_y0 = min(crop_h - 1, round(x_ax_y + x_half_t) + stub_gap)
        x_strip_y1 = min(crop_h, x_strip_y0 + stub_depth)
        if x_strip_y1 > x_strip_y0 and x_scan_1 > x_scan_0:
            col_hits = np.mean(neutral_ink[x_strip_y0:x_strip_y1, x_scan_0:x_scan_1] > 0, axis=0)
            in_stub = False
            start_c = 0
            for c_idx, val in enumerate(col_hits):
                if val >= 0.35 and not in_stub:
                    in_stub = True
                    start_c = c_idx
                elif val < 0.35 and in_stub:
                    in_stub = False
                    if 1 <= (c_idx - start_c) <= max_stub_thick:
                        info["x_tick_stubs"].append(x_scan_0 + 0.5 * (start_c + c_idx - 1))

    return info


# ==============================================================================
# TESSERACT OCR CHART TEXT EXTRACTOR (WHOLE + AXIS ZONES + ROTATED TITLES)
# ==============================================================================
def _map_band_ocr_word_boxes(
    ocr_res: Mapping[str, Any],
    band_rect_crop: Tuple[int, int, int, int],
    band_img_w: int,
    band_img_h: int,
    rotated_cw_deg: int = 0,
    repair_bengali: bool = True,
    convert_bangla_digits: bool = False,
) -> List[Dict[str, Any]]:
    """Maps OCR words from a padded/rotated margin strip back into chart-crop coordinates."""
    bx0, by0, bx1, by1 = band_rect_crop
    bw = max(1, bx1 - bx0)
    bh = max(1, by1 - by0)
    out: List[Dict[str, Any]] = []
    raw_boxes = ocr_res.get("bounding_boxes") or []
    res_w = float(ocr_res.get("width") or band_img_w or 1.0)
    res_h = float(ocr_res.get("height") or band_img_h or 1.0)

    for wb in raw_boxes:
        if not isinstance(wb, Mapping):
            continue
        raw_w = str(wb.get("word") or "").strip()
        if not raw_w:
            continue
        norm_txt, _ = apply_text_normalization(
            raw_w, repair_bengali=repair_bengali, convert_bangla_digits=convert_bangla_digits
        )
        if not norm_txt:
            continue

        nb = wb.get("normalized_box")
        if isinstance(nb, (list, tuple)) and len(nb) == 4:
            fx0 = max(0.0, min(1.0, float(nb[1]) / 1000.0))
            fy0 = max(0.0, min(1.0, float(nb[0]) / 1000.0))
            fx1 = max(0.0, min(1.0, float(nb[3]) / 1000.0))
            fy1 = max(0.0, min(1.0, float(nb[2]) / 1000.0))
        else:
            fx0 = float(wb.get("x", 0.0) or 0.0) / max(res_w, 1.0)
            fy0 = float(wb.get("y", 0.0) or 0.0) / max(res_h, 1.0)
            fx1 = fx0 + float(wb.get("w", 0.0) or 0.0) / max(res_w, 1.0)
            fy1 = fy0 + float(wb.get("h", 0.0) or 0.0) / max(res_h, 1.0)

        # Undo optional CW rotation used for vertical Y-axis title reading
        rot = rotated_cw_deg % 360
        if rot == 90:
            # Image was rotated 90 deg CW: original (u, v) -> rotated (1 - v, u)
            ox0, ox1 = min(fy0, fy1), max(fy0, fy1)
            oy0, oy1 = min(1.0 - fx1, 1.0 - fx0), max(1.0 - fx1, 1.0 - fx0)
            fx0, fy0, fx1, fy1 = ox0, oy0, ox1, oy1
        elif rot == 270:
            ox0, ox1 = min(1.0 - fy1, 1.0 - fy0), max(1.0 - fy1, 1.0 - fy0)
            oy0, oy1 = min(fx0, fx1), max(fx0, fx1)
            fx0, fy0, fx1, fy1 = ox0, oy0, ox1, oy1

        cx0 = bx0 + fx0 * bw
        cy0 = by0 + fy0 * bh
        cx1 = bx0 + fx1 * bw
        cy1 = by0 + fy1 * bh
        if (cx1 - cx0) < 1.0 or (cy1 - cy0) < 1.0:
            continue

        out.append({
            "text": norm_txt,
            "bbox_crop": (cx0, cy0, cx1, cy1),
            "cx": 0.5 * (cx0 + cx1),
            "cy": 0.5 * (cy0 + cy1),
            "width": cx1 - cx0,
            "height": cy1 - cy0,
            "confidence": float(wb.get("confidence", ocr_res.get("confidence", 0.5)) or 0.5),
            "is_vertical_text": rot in (90, 270),
            "source": "ocr_tesseract",
        })
    return out


def _run_upscaled_ocr_band(
    ocr_provider: BaseOCRProvider,
    crop_bgr: Any,
    rect_xyxy: Tuple[int, int, int, int],
    *,
    rotate_cw_deg: int = 0,
    upscale: float = 2.0,
    pad_px: int = 16,
    repair_bengali: bool = True,
    convert_bangla_digits: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    rx0, ry0, rx1, ry1 = rect_xyxy
    if (rx1 - rx0) < 6 or (ry1 - ry0) < 6:
        return [], {}
    band = crop_bgr[ry0:ry1, rx0:rx1]
    if HAS_OPENCV and cv2 is not None:
        if rotate_cw_deg == 90:
            band = cv2.rotate(band, cv2.ROTATE_90_CLOCKWISE)
        elif rotate_cw_deg == 270:
            band = cv2.rotate(band, cv2.ROTATE_90_COUNTERCLOCKWISE)
        bh, bw = band.shape[:2]
        if upscale > 1.05:
            band = cv2.resize(band, (max(32, int(round(bw * upscale))), max(32, int(round(bh * upscale)))), interpolation=cv2.INTER_CUBIC)
        rgb = cv2.cvtColor(band, cv2.COLOR_BGR2RGB)
        band_pil = Image.fromarray(rgb)
    else:
        band_pil = Image.fromarray(band[:, :, ::-1]) if HAS_NUMPY else Image.new("RGB", (max(32, rx1 - rx0), max(32, ry1 - ry0)), "white")
        if rotate_cw_deg == 90:
            band_pil = band_pil.rotate(-90, expand=True)
        elif rotate_cw_deg == 270:
            band_pil = band_pil.rotate(90, expand=True)

    # White padding improves Tesseract LSTM line segmentation on tight margin bands
    padded_w = max(48, band_pil.width + 2 * pad_px)
    padded_h = max(48, band_pil.height + 2 * pad_px)
    padded_img = Image.new("RGB", (padded_w, padded_h), (255, 255, 255))
    padded_img.paste(band_pil, (pad_px, pad_px))
    band_pil.close()

    try:
        ocr_res = ocr_provider.extract_image(padded_img)
    finally:
        padded_img.close()

    if str(ocr_res.get("status", "")) == "provider_unavailable":
        return [], dict(ocr_res)

    # Re-project normalized coords accounting for padding offset around pasted strip
    raw_boxes = list(ocr_res.get("bounding_boxes") or [])
    adjusted_boxes: List[Dict[str, Any]] = []
    inner_w = max(1.0, float(padded_w - 2 * pad_px))
    inner_h = max(1.0, float(padded_h - 2 * pad_px))
    for wb in raw_boxes:
        if not isinstance(wb, Mapping):
            continue
        nb = wb.get("normalized_box")
        if isinstance(nb, (list, tuple)) and len(nb) == 4:
            px0 = (float(nb[1]) / 1000.0) * padded_w - pad_px
            py0 = (float(nb[0]) / 1000.0) * padded_h - pad_px
            px1 = (float(nb[3]) / 1000.0) * padded_w - pad_px
            py1 = (float(nb[2]) / 1000.0) * padded_h - pad_px
            item = dict(wb)
            item["normalized_box"] = [
                max(0, min(1000, round((py0 / inner_h) * 1000))),
                max(0, min(1000, round((px0 / inner_w) * 1000))),
                max(0, min(1000, round((py1 / inner_h) * 1000))),
                max(0, min(1000, round((px1 / inner_w) * 1000))),
            ]
            adjusted_boxes.append(item)
        else:
            adjusted_boxes.append(dict(wb))

    ocr_adj = dict(ocr_res)
    ocr_adj["bounding_boxes"] = adjusted_boxes
    mapped = _map_band_ocr_word_boxes(
        ocr_adj,
        band_rect_crop=(rx0, ry0, rx1, ry1),
        band_img_w=int(inner_w),
        band_img_h=int(inner_h),
        rotated_cw_deg=rotate_cw_deg,
        repair_bengali=repair_bengali,
        convert_bangla_digits=convert_bangla_digits,
    )
    return mapped, dict(ocr_res)


def _group_ocr_words_into_lines(tokens: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Groups adjacent same-row OCR tokens into multi-word chart labels/titles."""
    if not tokens:
        return []
    ordered = sorted(tokens, key=lambda t: (round(float(t["cy"]) / 6.0), float(t["bbox_crop"][0])))
    grouped: List[Dict[str, Any]] = []
    for tk in ordered:
        b = tk["bbox_crop"]
        txt = str(tk["text"]).strip()
        if not txt:
            continue
        merged = False
        # Do not merge distinct purely numeric Y tick values across columns/rows
        is_pure_num = parse_chart_numeric_token(txt) is not None
        for g in reversed(grouped[-6:]):
            gb = g["bbox_crop"]
            if bool(g.get("is_vertical_text")) != bool(tk.get("is_vertical_text")):
                continue
            avg_h = max(8.0, 0.5 * ((gb[3] - gb[1]) + (b[3] - b[1])))
            same_row = abs(float(tk["cy"]) - float(g["cy"])) <= 0.55 * avg_h
            # Only merge left-to-right neighboring tokens, never overlapping duplicates at the same column
            close_x = (gb[2] - 2.0) <= b[0] <= (gb[2] + max(14.0, 1.35 * avg_h))
            # Never merge separate column ticks or separate numbers far apart
            g_is_num = parse_chart_numeric_token(g["text"]) is not None
            if is_pure_num and g_is_num and (b[0] - gb[2]) > 8.0:
                continue
            if same_row and close_x:
                nb = (min(gb[0], b[0]), min(gb[1], b[1]), max(gb[2], b[2]), max(gb[3], b[3]))
                g["text"] = f"{g['text']} {txt}".strip()
                g["bbox_crop"] = nb
                g["cx"] = 0.5 * (nb[0] + nb[2])
                g["cy"] = 0.5 * (nb[1] + nb[3])
                g["width"] = nb[2] - nb[0]
                g["height"] = nb[3] - nb[1]
                g["confidence"] = min(float(g["confidence"]), float(tk.get("confidence", 0.5)))
                merged = True
                break
        if not merged:
            item = dict(tk)
            item["text"] = txt
            grouped.append(item)
    return grouped


def extract_chart_text_with_tesseract(
    *,
    crop_img: Image.Image,
    ocr_provider: BaseOCRProvider,
    axes_info: Mapping[str, Any],
    repair_bengali: bool = True,
    convert_bangla_digits: bool = False,
) -> Dict[str, Any]:
    """
    Extracts chart text using the existing ``TesseractOCRProvider`` across both
    the full chart crop and clean axis/title/rotated-label margin zones.
    """
    cw, ch = crop_img.size
    warnings: List[str] = []

    if HAS_NUMPY and np is not None:
        rgb_arr = np.asarray(crop_img.convert("RGB"))
        crop_bgr = rgb_arr[:, :, ::-1].copy()
    else:
        crop_bgr = None

    # 1. Full chart crop OCR baseline pass
    padded_full = Image.new("RGB", (max(48, cw + 20), max(48, ch + 20)), (255, 255, 255))
    padded_full.paste(crop_img, (10, 10))
    try:
        full_res = ocr_provider.extract_image(padded_full)
    finally:
        padded_full.close()

    status = str(full_res.get("status", "success"))
    engine = str(full_res.get("engine") or "tesseract")
    engine_version = str(full_res.get("engine_version") or "unknown")
    language = str(full_res.get("language") or getattr(ocr_provider, "lang", "") or "")
    for w_msg in full_res.get("warnings") or []:
        w_str = str(w_msg or "").strip()
        if w_str and w_str not in warnings:
            warnings.append(w_str)
    if full_res.get("error_detail"):
        err_w = str(full_res["error_detail"])
        if err_w not in warnings:
            warnings.append(err_w)

    if status == "provider_unavailable":
        warnings.append("Tesseract OCR binary unavailable; chart text relies only on native PDF spans.")
        return {
            "tokens": [],
            "full_text": "",
            "ocr_available": False,
            "confidence": 0.0,
            "status": status,
            "engine": engine,
            "engine_version": engine_version,
            "language": language,
            "warnings": warnings,
        }

    raw_text_full = str(full_res.get("text") or "").strip()
    if VisualPipelineIntegrationAdapter.is_ocr_placeholder_text(raw_text_full):
        raw_text_full = ""
    base_conf = float(full_res.get("confidence", 0.0) or 0.0)

    # Map whole-crop word boxes accounting for 10px pad
    full_adj = dict(full_res)
    pw_f, ph_f = max(1, cw + 20), max(1, ch + 20)
    adj_f_boxes = []
    for wb in full_res.get("bounding_boxes") or []:
        if not isinstance(wb, Mapping):
            continue
        nb = wb.get("normalized_box")
        if isinstance(nb, (list, tuple)) and len(nb) == 4:
            px0 = (float(nb[1]) / 1000.0) * pw_f - 10.0
            py0 = (float(nb[0]) / 1000.0) * ph_f - 10.0
            px1 = (float(nb[3]) / 1000.0) * pw_f - 10.0
            py1 = (float(nb[2]) / 1000.0) * ph_f - 10.0
            item = dict(wb)
            item["normalized_box"] = [
                max(0, min(1000, round((py0 / max(1, ch)) * 1000))),
                max(0, min(1000, round((px0 / max(1, cw)) * 1000))),
                max(0, min(1000, round((py1 / max(1, ch)) * 1000))),
                max(0, min(1000, round((px1 / max(1, cw)) * 1000))),
            ]
            adj_f_boxes.append(item)
    full_adj["bounding_boxes"] = adj_f_boxes
    all_tokens = _map_band_ocr_word_boxes(
        full_adj,
        band_rect_crop=(0, 0, cw, ch),
        band_img_w=cw,
        band_img_h=ch,
        rotated_cw_deg=0,
        repair_bengali=repair_bengali,
        convert_bangla_digits=convert_bangla_digits,
    )

    # 2. Targeted margin bands (Y1 ticks, Y1 rotated title, Y2 ticks, X labels) when axes exist
    confs = [base_conf] if base_conf > 0 else []
    px0, py0, px1, py1 = axes_info.get("plot_box") or (0, 0, cw, ch)
    if crop_bgr is not None and axes_info.get("has_axes") and cw >= 90 and ch >= 90:
        bands: List[Tuple[Tuple[int, int, int, int], int, float]] = []
        # Left Y1 tick column + optional rotated vertical title slice
        y_line_x = round(axes_info.get("y_axis_x") or px0)
        if y_line_x >= 18:
            tick_left = max(0, y_line_x - max(52, int(cw * 0.16)))
            bands.append(((tick_left, max(0, py0 - 16), max(tick_left + 8, y_line_x - 3), min(ch, py1 + 16)), 0, 2.5))
            if tick_left >= 10:
                bands.append(((0, max(0, py0 - 8), tick_left + 6, min(ch, py1 + 8)), 90, 2.5))
        # Right Y2 tick column + optional rotated vertical title
        y2_x = axes_info.get("y2_axis_x")
        if y2_x is not None and (cw - int(round(y2_x))) >= 18:
            rx_start = min(cw - 8, int(round(y2_x)) + 3)
            rx_mid = min(cw, rx_start + max(48, int(cw * 0.14)))
            bands.append(((rx_start, max(0, py0 - 16), rx_mid, min(ch, py1 + 16)), 0, 2.5))
            if (cw - rx_mid) >= 10:
                bands.append(((max(0, rx_mid - 4), max(0, py0 - 8), cw, min(ch, py1 + 8)), 270, 2.5))
        # Bottom X labels + title
        x_line_y = round(axes_info.get("x_axis_y") or py1)
        if (ch - x_line_y) >= 16:
            bands.append(((0, min(ch - 8, x_line_y + 3), cw, ch), 0, 2.2))

        for rect_b, rot_deg, up_s in bands:
            btokens, bres = _run_upscaled_ocr_band(
                ocr_provider,
                crop_bgr,
                rect_b,
                rotate_cw_deg=rot_deg,
                upscale=up_s,
                repair_bengali=repair_bengali,
                convert_bangla_digits=convert_bangla_digits,
            )
            # Guard against static mock OCR returning identical text on sub-bands
            if btokens and bres.get("text") != raw_text_full:
                if float(bres.get("confidence", 0.0) or 0.0) > 0:
                    confs.append(float(bres["confidence"]))
                for bt in btokens:
                    overlap_idx: Optional[int] = None
                    for ex_i, ex in enumerate(all_tokens):
                        min_a = max(1.0, min(bt["width"] * bt["height"], ex["width"] * ex["height"]))
                        if _box_intersection_area(bt["bbox_crop"], ex["bbox_crop"]) >= 0.45 * min_a:
                            overlap_idx = ex_i
                            break
                    if overlap_idx is not None:
                        ex = all_tokens[overlap_idx]
                        ex_val = parse_chart_numeric_token(ex["text"])
                        bt_val = parse_chart_numeric_token(bt["text"])
                        ex_parsed = ex_val is not None
                        bt_parsed = bt_val is not None
                        same_num = ex_parsed and bt_parsed and float(ex_val["value"]) == float(bt_val["value"])
                        better_conf = float(bt.get("confidence", 0.0) or 0.0) > float(ex.get("confidence", 0.0) or 0.0) + 0.08
                        if (not ex_parsed and bt_parsed) or (not ex_parsed and not bt_parsed and better_conf) or (same_num and better_conf):
                            all_tokens[overlap_idx] = bt
                    else:
                        all_tokens.append(bt)

    # Filter isolated axis-spine/tick-stub punctuation before word->line grouping so
    # tick stubs like "-" never fuse with tick labels ("100 -") or axis titles.
    filtered_tokens: List[Dict[str, Any]] = []
    for idx_t, tk in enumerate(all_tokens):
        txt_s = str(tk.get("text") or "").strip()
        if txt_s in {"|", "_", "·", "•", "~"}:
            continue
        if txt_s in {"-", "—", "–"}:
            tb = tk["bbox_crop"]
            cy_v = tk.get("cy")
            t_cy = float(0.5 * (tb[1] + tb[3])) if cy_v is None else float(cy_v)
            has_num_right = any(
                j_t != idx_t
                and 0.0 <= float(other["bbox_crop"][0]) - float(tb[2]) <= 22.0
                and abs(
                    (float(0.5 * (other["bbox_crop"][1] + other["bbox_crop"][3])) if other.get("cy") is None else float(other["cy"]))
                    - t_cy
                ) <= 10.0
                and parse_chart_numeric_token(str(other.get("text") or "")) is not None
                for j_t, other in enumerate(all_tokens)
            )
            if not has_num_right:
                continue
        filtered_tokens.append(tk)

    grouped_tokens = _group_ocr_words_into_lines(filtered_tokens)
    norm_full, _ = apply_text_normalization(
        raw_text_full or " ".join(t["text"] for t in grouped_tokens),
        repair_bengali=repair_bengali,
        convert_bangla_digits=convert_bangla_digits,
    )
    eff_conf = round(sum(confs) / len(confs), 4) if confs else base_conf
    if norm_full == "" and not grouped_tokens:
        eff_conf = min(eff_conf, 0.25)

    return {
        "tokens": grouped_tokens,
        "raw_word_tokens": all_tokens,
        "full_text": norm_full,
        "ocr_available": True,
        "confidence": eff_conf,
        "status": status,
        "engine": engine,
        "engine_version": engine_version,
        "language": language,
        "warnings": warnings,
    }


# ==============================================================================
# RASTER SERIES / PRIMITIVE EXTRACTION WITH OPENCV (BARS, LINES, PIE, SCATTER)
# ==============================================================================
def _quantize_dominant_colors_bgr(
    plot_bgr: Any,
    fg_mask: Any,
    max_colors: int = 8,
    min_pixels: int = 20,
) -> List[Tuple[Tuple[int, int, int], Any]]:
    """
    Separates colored/dark plot elements cleanly into color layers so touching
    stacked bars, grouped bars, and multi-colored lines do not merge into one blob.
    """
    if not HAS_OPENCV or not HAS_NUMPY or cv2 is None or np is None:
        return []
    ys, xs = np.where(fg_mask > 0)
    if xs.size < min_pixels:
        return []

    pts = plot_bgr[ys, xs].astype(np.int32)
    # Quantize BGR by bins of 28 to cluster anti-aliased renderings deterministically
    q = (pts // 28) * 28 + 14
    uniq, counts = np.unique(q, axis=0, return_counts=True)
    order = np.argsort(-counts)

    clusters: List[List[Any]] = []
    for idx in order:
        cnt = int(counts[idx])
        if cnt < min_pixels:
            continue
        bgr_c = tuple(int(v) for v in uniq[idx])
        # Ignore near-white or neutral light gray background noise
        rgb_c = (bgr_c[2], bgr_c[1], bgr_c[0])
        if _is_white_or_near_white(rgb_c) or (max(rgb_c) - min(rgb_c) < 16 and min(rgb_c) > 195):
            continue
        merged = False
        for cl in clusters:
            if _rgb_distance(rgb_c, cl[0]) <= 52.0:
                cl[1].append(bgr_c)
                cl[2] += cnt
                merged = True
                break
        if not merged:
            clusters.append([rgb_c, [bgr_c], cnt])
        if len(clusters) >= max_colors:
            break

    layers: List[Tuple[Tuple[int, int, int], Any]] = []
    h_p, w_p = plot_bgr.shape[:2]
    b_arr = plot_bgr.astype(np.int16)
    for rgb_rep, _, _ in clusters:
        target_bgr = np.array([rgb_rep[2], rgb_rep[1], rgb_rep[0]], dtype=np.int16)
        dist = np.linalg.norm(b_arr - target_bgr, axis=2)
        layer_mask = ((fg_mask > 0) & (dist <= 56.0)).astype(np.uint8) * 255
        if int(np.count_nonzero(layer_mask)) >= min_pixels:
            # Compute actual median foreground RGB for clean legend matching
            med = np.median(plot_bgr[layer_mask > 0], axis=0)
            med_rgb = (int(med[2]), int(med[1]), int(med[0]))
            layers.append((med_rgb, layer_mask))
    return layers


def _mask_tokens_in_plot(
    mask: Any,
    tokens: Sequence[Mapping[str, Any]],
    plot_offset_x: int,
    plot_offset_y: int,
    margin: int = 2,
) -> Any:
    cleaned = mask.copy()
    hp, wp = cleaned.shape[:2]
    for tk in tokens:
        b = tk["bbox_crop"]
        x0 = max(0, int(math.floor(b[0] - plot_offset_x)) - margin)
        y0 = max(0, int(math.floor(b[1] - plot_offset_y)) - margin)
        x1 = min(wp, int(math.ceil(b[2] - plot_offset_x)) + margin)
        y1 = min(hp, int(math.ceil(b[3] - plot_offset_y)) + margin)
        if x1 > x0 and y1 > y0:
            cleaned[y0:y1, x0:x1] = 0
    return cleaned


def _detect_raster_bars_opencv(
    *,
    crop_bgr: Any,
    plot_box: Tuple[int, int, int, int],
    tokens: Sequence[Mapping[str, Any]],
    is_dark_bg: bool,
) -> List[Dict[str, Any]]:
    """Extracts filled bar rectangles inside ``plot_box`` across color clusters."""
    if not HAS_OPENCV or not HAS_NUMPY or cv2 is None or np is None:
        return []
    px0, py0, px1, py1 = plot_box
    pad_in = max(2, int(round(min(crop_bgr.shape[1], crop_bgr.shape[0]) * 0.005)))
    in_x0 = min(crop_bgr.shape[1] - 4, px0 + pad_in)
    in_y0 = min(crop_bgr.shape[0] - 4, py0 + pad_in)
    in_x1 = max(in_x0 + 4, px1 - pad_in)
    in_y1 = max(in_y0 + 4, py1 - pad_in)
    plot_bgr = crop_bgr[in_y0:in_y1, in_x0:in_x1]
    ph_i, pw_i = plot_bgr.shape[:2]
    if pw_i < 12 or ph_i < 12:
        return []

    gray = cv2.cvtColor(plot_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(plot_bgr, cv2.COLOR_BGR2HSV)
    # Capture both colored bars and dark gray/black bars
    if is_dark_bg:
        fg = ((gray > 45) | (hsv[:, :, 1] > 35)).astype(np.uint8) * 255
    else:
        fg = ((hsv[:, :, 1] > 32) | (gray < 195)).astype(np.uint8) * 255

    # Remove thin 1-2px horizontal/vertical gridlines & text tokens
    k_hgrid = cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, int(pw_i * 0.45)), 1))
    k_vgrid = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, int(ph_i * 0.45))))
    neutral = ((hsv[:, :, 1] < 45) & (fg > 0)).astype(np.uint8) * 255
    grid_h = cv2.morphologyEx(neutral, cv2.MORPH_OPEN, k_hgrid)
    grid_v = cv2.morphologyEx(neutral, cv2.MORPH_OPEN, k_vgrid)
    fg = cv2.bitwise_and(fg, cv2.bitwise_not(cv2.bitwise_or(grid_h, grid_v)))
    fg = _mask_tokens_in_plot(fg, tokens, in_x0, in_y0, margin=1)

    # Open with small 4x4 kernel (or 3x3 on small plots) so thin lines/noise disappear cleanly
    k_sz = 3 if min(pw_i, ph_i) < 160 else 4
    solid_fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((k_sz, k_sz), np.uint8))

    bars: List[Dict[str, Any]] = []
    layers = _quantize_dominant_colors_bgr(plot_bgr, solid_fg, max_colors=8, min_pixels=18)
    for rgb_col, layer_mask in layers:
        # Close tiny 1px OCR knockout gaps ONLY vertically/horizontally inside matching color bar
        clean_layer = cv2.morphologyEx(layer_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(clean_layer, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            bx, by, bw, bh = cv2.boundingRect(cnt)
            if bw < 4 or bh < 4 or area < 16:
                continue
            if bw > 0.88 * pw_i and bh > 0.88 * ph_i:
                continue
            rect_area = float(bw * bh)
            fill_ratio = area / max(rect_area, 1.0)
            # Bar rectangles must be solidly filled rectangular blocks
            if fill_ratio < 0.68:
                continue
            # Ignore small equal-sided square scatter markers (<13x13) floating mid-plot
            if bw <= 13 and bh <= 13 and abs(bw - bh) <= 3:
                continue
            cbox = (float(in_x0 + bx), float(in_y0 + by), float(in_x0 + bx + bw), float(in_y0 + by + bh))
            bars.append({
                "bbox_crop": cbox,
                "color_rgb": rgb_col,
                "area": area,
                "fill_ratio": round(fill_ratio, 3),
                "source": "raster_opencv",
            })

    # Deduplicate overlapping rects from close color masks
    bars.sort(key=lambda b: b["area"], reverse=True)
    dedup_bars: List[Dict[str, Any]] = []
    for b in bars:
        bb = b["bbox_crop"]
        b_area = max(1.0, (bb[2] - bb[0]) * (bb[3] - bb[1]))
        if any(_box_intersection_area(bb, db["bbox_crop"]) >= 0.70 * min(b_area, (db["bbox_crop"][2] - db["bbox_crop"][0]) * (db["bbox_crop"][3] - db["bbox_crop"][1])) for db in dedup_bars):
            continue
        dedup_bars.append(b)
    return dedup_bars


def _detect_raster_pie_opencv(
    *,
    crop_bgr: Any,
    axes_info: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Detects circular pie charts using OpenCV contours / Hough circles and samples
    contiguous angular color slices cleanly around the annulus.
    """
    if not HAS_OPENCV or not HAS_NUMPY or cv2 is None or np is None:
        return None
    if axes_info.get("has_axes"):
        return None

    h, w = crop_bgr.shape[:2]
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    color_mask = ((hsv[:, :, 1] > 40) & (hsv[:, :, 2] < 248)).astype(np.uint8) * 255
    closed = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_circle = None
    best_area = 0.0
    for cnt in contours:
        area = cv2.contourArea(cnt)
        perim = cv2.arcLength(cnt, True)
        if area < 900.0 or perim < 30.0:
            continue
        circ = 4.0 * math.pi * area / (perim * perim)
        (cx, cy), rad = cv2.minEnclosingCircle(cnt)
        # Circle must cover >= 55% of its enclosing disk
        enclosing_area = math.pi * rad * rad
        if circ >= 0.58 and rad >= 0.14 * min(w, h) and area / max(enclosing_area, 1.0) >= 0.55:
            if area > best_area:
                best_area = area
                best_circle = (cx, cy, rad)

    if best_circle is None:
        return None

    cx, cy, rad = best_circle
    # Sample annulus radial median RGB at each degree theta in [0..359]
    radii_fracs = [0.38, 0.50, 0.62, 0.72]
    deg_colors: List[Optional[Tuple[int, int, int]]] = []
    for deg in range(360):
        th = math.radians(deg)
        samples: List[Tuple[int, int, int]] = []
        for rf in radii_fracs:
            sx = round(cx + rf * rad * math.cos(th))
            sy = round(cy + rf * rad * math.sin(th))
            if 0 <= sx < w and 0 <= sy < h:
                b, g, r = [int(v) for v in crop_bgr[sy, sx]]
                rgb = (r, g, b)
                if not _is_white_or_near_white(rgb) and not (max(rgb) < 45 and min(rgb) < 45):
                    samples.append(rgb)
        if samples:
            mr = int(np.median([s[0] for s in samples]))
            mg = int(np.median([s[1] for s in samples]))
            mb = int(np.median([s[2] for s in samples]))
            deg_colors.append((mr, mg, mb))
        else:
            deg_colors.append(None)

    valid_degs = sum(1 for c in deg_colors if c is not None)
    if valid_degs < 240:
        return None

    # Fill tiny divider/label gaps (<= 8 deg) cleanly from neighbors
    for _ in range(8):
        filled = list(deg_colors)
        for d in range(360):
            if filled[d] is None:
                prev_c = deg_colors[(d - 1) % 360]
                next_c = deg_colors[(d + 1) % 360]
                next2_c = deg_colors[(d + 2) % 360]
                if prev_c is not None and next_c is not None and _rgb_distance(prev_c, next_c) <= 45.0:
                    filled[d] = prev_c
                elif prev_c is not None and next2_c is not None and _rgb_distance(prev_c, next2_c) <= 45.0:
                    filled[d] = prev_c
        deg_colors = filled

    # Segment contiguous angular color runs
    runs: List[Dict[str, Any]] = []
    for d in range(360):
        col = deg_colors[d]
        if col is None:
            continue
        if runs and not runs[-1]["closed"] and _rgb_distance(col, runs[-1]["color_rgb"]) <= 42.0 and (d - runs[-1]["end_deg"]) <= 4:
            runs[-1]["colors"].append(col)
            runs[-1]["end_deg"] = d
            c_arr = np.array(runs[-1]["colors"])
            runs[-1]["color_rgb"] = (int(np.median(c_arr[:, 0])), int(np.median(c_arr[:, 1])), int(np.median(c_arr[:, 2])))
        else:
            if runs:
                runs[-1]["closed"] = True
            runs.append({"start_deg": d, "end_deg": d, "colors": [col], "color_rgb": col, "closed": False})

    # Merge wrap-around run at 359 -> 0 if same slice color
    if len(runs) >= 2 and runs[0]["start_deg"] <= 3 and runs[-1]["end_deg"] >= 355 and _rgb_distance(runs[0]["color_rgb"], runs[-1]["color_rgb"]) <= 42.0:
        first = runs.pop(0)
        runs[-1]["colors"].extend(first["colors"])
        c_arr = np.array(runs[-1]["colors"])
        runs[-1]["color_rgb"] = (int(np.median(c_arr[:, 0])), int(np.median(c_arr[:, 1])), int(np.median(c_arr[:, 2])))
        runs[-1]["end_deg"] = 360 + first["end_deg"]

    sectors: List[Dict[str, Any]] = []
    for rn in runs:
        sweep = float(rn["end_deg"] - rn["start_deg"] + 1)
        if sweep < 6.0:
            continue
        start_d = float(rn["start_deg"] % 360)
        mid_d = float((rn["start_deg"] + 0.5 * sweep) % 360)
        # Bounding box around slice arc + center
        pts_slice = [(cx, cy)]
        for a_deg in range(rn["start_deg"], rn["end_deg"] + 1, max(1, int(sweep // 8))):
            ar = math.radians(a_deg % 360)
            pts_slice.append((cx + rad * math.cos(ar), cy + rad * math.sin(ar)))
        xs_s = [p[0] for p in pts_slice]
        ys_s = [p[1] for p in pts_slice]
        sectors.append({
            "center_crop": [round(cx, 2), round(cy, 2)],
            "radius_px": round(rad, 2),
            "start_deg": start_d,
            "end_deg": float(rn["end_deg"] % 360),
            "mid_deg": mid_d,
            "sweep_deg": sweep,
            "bbox_crop": (min(xs_s), min(ys_s), max(xs_s), max(ys_s)),
            "color_rgb": rn["color_rgb"],
        })

    if len(sectors) < 2:
        return None
    return {
        "center": (cx, cy),
        "radius": rad,
        "sectors": sectors,
        "coverage_deg": sum(s["sweep_deg"] for s in sectors),
    }


def _detect_raster_lines_and_scatter_opencv(
    *,
    crop_bgr: Any,
    plot_box: Tuple[int, int, int, int],
    tokens: Sequence[Mapping[str, Any]],
    is_dark_bg: bool,
) -> Dict[str, Any]:
    """
    Detects polyline stroke series (line charts) vs compact isolated marker clusters
    (scatter plots) inside ``plot_box`` via OpenCV.
    """
    res: Dict[str, Any] = {"line_series": [], "scatter_points": []}
    if not HAS_OPENCV or not HAS_NUMPY or cv2 is None or np is None:
        return res

    px0, py0, px1, py1 = plot_box
    pad_in = max(3, int(round(min(crop_bgr.shape[1], crop_bgr.shape[0]) * 0.005)))
    in_x0 = min(crop_bgr.shape[1] - 4, px0 + pad_in)
    in_y0 = min(crop_bgr.shape[0] - 4, py0 + pad_in)
    in_x1 = max(in_x0 + 4, px1 - pad_in)
    in_y1 = max(in_y0 + 4, py1 - pad_in)
    plot_bgr = crop_bgr[in_y0:in_y1, in_x0:in_x1]
    ph_i, pw_i = plot_bgr.shape[:2]
    if pw_i < 16 or ph_i < 16:
        return res

    gray = cv2.cvtColor(plot_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(plot_bgr, cv2.COLOR_BGR2HSV)
    if is_dark_bg:
        fg = ((gray > 45) | (hsv[:, :, 1] > 35)).astype(np.uint8) * 255
    else:
        fg = ((hsv[:, :, 1] > 32) | (gray < 190)).astype(np.uint8) * 255

    # Strip full-span gridlines & axes
    k_hgrid = cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, int(pw_i * 0.45)), 1))
    k_vgrid = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, int(ph_i * 0.45))))
    neutral = ((hsv[:, :, 1] < 45) & (fg > 0)).astype(np.uint8) * 255
    fg = cv2.bitwise_and(
        fg,
        cv2.bitwise_not(cv2.bitwise_or(cv2.morphologyEx(neutral, cv2.MORPH_OPEN, k_hgrid), cv2.morphologyEx(neutral, cv2.MORPH_OPEN, k_vgrid))),
    )
    fg = _mask_tokens_in_plot(fg, tokens, in_x0, in_y0, margin=1)

    layers = _quantize_dominant_colors_bgr(plot_bgr, fg, max_colors=8, min_pixels=12)
    for rgb_col, layer_mask in layers:
        num_c, _, stats, centroids = cv2.connectedComponentsWithStats(layer_mask, connectivity=8)
        wide_span = False
        compact_pts: List[Dict[str, Any]] = []
        for lbl in range(1, num_c):
            bx, by, bw, bh, area = [int(v) for v in stats[lbl]]
            cx_l, cy_l = float(centroids[lbl][0]), float(centroids[lbl][1])
            if bw >= max(24, int(0.18 * pw_i)):
                wide_span = True
            elif 4 <= area <= 420 and 2 <= bw <= 26 and 2 <= bh <= 26:
                compact_pts.append({
                    "cx": in_x0 + cx_l,
                    "cy": in_y0 + cy_l,
                    "bbox_crop": (float(in_x0 + bx), float(in_y0 + by), float(in_x0 + bx + bw), float(in_y0 + by + bh)),
                    "color_rgb": rgb_col,
                    "source": "raster_opencv",
                })

        if wide_span:
            # Trace y-centroid per column where this series appears
            cols_x: List[Tuple[float, float]] = []
            for xc in range(pw_i):
                ys_col = np.where(layer_mask[:, xc] > 0)[0]
                if ys_col.size > 0 and ys_col.size <= max(20, int(0.18 * ph_i)):
                    cols_x.append((float(in_x0 + xc), in_y0 + float(np.median(ys_col))))
            if len(cols_x) >= 6:
                res["line_series"].append({
                    "color_rgb": rgb_col,
                    "samples_xy": cols_x,
                    "source": "raster_opencv",
                })
        elif len(compact_pts) >= 2:
            res["scatter_points"].extend(compact_pts)

    return res


# ==============================================================================
# LEGEND & AXIS / CATEGORY LABEL ASSOCIATION
# ==============================================================================
def _detect_legends(
    *,
    vector_prims: Mapping[str, Any],
    crop_bgr: Any,
    axes_info: Mapping[str, Any],
    tokens: Sequence[Mapping[str, Any]],
    crop_w: int,
    crop_h: int,
) -> List[Dict[str, Any]]:
    """
    Detects chart legends by matching small colored swatches or short colored line
    strokes with immediately adjacent text labels in non-axis margins or legend boxes.
    """
    legends: List[Dict[str, Any]] = []
    px0, py0, px1, py1 = axes_info.get("plot_box") or (0, 0, crop_w, crop_h)
    used_tokens = set()

    swatches: List[Tuple[Tuple[float, float, float, float], Tuple[int, int, int]]] = []
    max_swatch = max(38.0, 0.06 * float(min(crop_w, crop_h)))
    for r in vector_prims.get("rects") or []:
        rb = r["bbox_crop"]
        rw, rh = rb[2] - rb[0], rb[3] - rb[1]
        col = r.get("fill_rgb") or r.get("stroke_rgb")
        if col and not _is_white_or_near_white(col) and 3.0 <= rw <= max_swatch and 3.0 <= rh <= max_swatch:
            # Legend swatches typically sit outside plot center or in top/right legend band
            in_plot_interior = (px0 + 12 < rb[0] and rb[2] < px1 - 12 and py0 + 20 < rb[1] and rb[3] < py1 - 12)
            # Exception: legend boxes inside top-right / top-left corner right beside legend text
            if not in_plot_interior or (rb[1] < py0 + 0.35 * (py1 - py0)):
                swatches.append((rb, col))

    for ln in vector_prims.get("lines") or []:
        p1, p2 = ln["p1"], ln["p2"]
        lw_seg = abs(p2[0] - p1[0])
        lh_seg = abs(p2[1] - p1[1])
        col = ln.get("color_rgb")
        if col and not _is_neutral_gray_or_white(col) and 6.0 <= lw_seg <= max(32.0, max_swatch) and lh_seg <= 4.0:
            sb = (min(p1[0], p2[0]), min(p1[1], p2[1]) - 3.0, max(p1[0], p2[0]), max(p1[1], p2[1]) + 3.0)
            swatches.append((sb, col))

    # OpenCV fallback swatches when vector swatches unavailable
    if not swatches and crop_bgr is not None and HAS_OPENCV and HAS_NUMPY and cv2 is not None and np is not None:
        hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
        cmask = ((hsv[:, :, 1] > 45) & (hsv[:, :, 2] < 245)).astype(np.uint8) * 255
        n_c, _, stats, _ = cv2.connectedComponentsWithStats(cmask, connectivity=8)
        for lbl in range(1, n_c):
            bx, by, bw, bh, area = [int(v) for v in stats[lbl]]
            if 12 <= area <= int(max_swatch * max_swatch) and 4 <= bw <= int(max_swatch) and 3 <= bh <= int(max_swatch):
                if by <= py0 + 24 or bx >= px1 - 6 or by >= py1 + 24 or not axes_info.get("has_axes"):
                    med = np.median(crop_bgr[by : by + bh, bx : bx + bw], axis=(0, 1))
                    col_rgb = (int(med[2]), int(med[1]), int(med[0]))
                    swatches.append(((float(bx), float(by), float(bx + bw), float(by + bh)), col_rgb))

    # Pair each swatch with the closest text label immediately to its right
    y2_ax_x = axes_info.get("y2_axis_x")
    has_axes = bool(axes_info.get("has_axes"))
    dx_max = max(50.0, 0.08 * float(crop_w))
    for sb, col_rgb in swatches:
        s_cy = 0.5 * (sb[1] + sb[3])
        best_idx = None
        best_dist = 1e9
        for idx, tk in enumerate(tokens):
            if idx in used_tokens:
                continue
            tb = tk["bbox_crop"]
            txt = str(tk["text"] or "").strip()
            if not txt:
                continue
            # Do not steal numeric axis tick labels sitting in left/right/bottom tick margins;
            # allow numeric year labels (e.g. "2024", "2025") when adjacent to a legend swatch.
            is_num = parse_chart_numeric_token(txt) is not None
            if is_num and has_axes:
                if float(tk["cx"]) <= float(px0) + 4.0:
                    continue
                if y2_ax_x is not None and float(tk["cx"]) >= float(y2_ax_x) - 4.0:
                    continue
                if float(tk["cy"]) >= float(py1) - 4.0:
                    continue
            if abs(float(tk["cy"]) - s_cy) > max(16.0, (tb[3] - tb[1]) * 1.2):
                continue
            dx = tb[0] - sb[2]
            if -4.0 <= dx <= dx_max and dx < best_dist:
                best_dist = dx
                best_idx = idx
        if best_idx is not None:
            used_tokens.add(best_idx)
            tk = tokens[best_idx]
            legends.append({
                "label": tk["text"],
                "color_rgb": list(col_rgb),
                "color_hex": _rgb_to_hex(col_rgb),
                "swatch_box_crop": [round(v, 2) for v in sb],
                "label_box_crop": [round(v, 2) for v in tk["bbox_crop"]],
            })

    return legends


def _match_series_name_by_color(
    rgb: Optional[Sequence[int]],
    legends: Sequence[Mapping[str, Any]],
    fallback_idx: int,
) -> str:
    if rgb and legends:
        best_lbl = None
        best_d = 1e9
        for lg in legends:
            d = _rgb_distance(rgb, lg["color_rgb"])
            if d < best_d:
                best_d = d
                best_lbl = str(lg["label"])
        if best_lbl is not None and best_d <= 80.0:
            return best_lbl
    return f"Series {fallback_idx}"


# ==============================================================================
# STRUCTURE VALIDATION
# ==============================================================================
def validate_chart_extraction(
    *,
    chart_type: ChartType,
    axes: Mapping[str, Any],
    series: Sequence[Mapping[str, Any]],
    ocr_meta: Mapping[str, Any],
    source_mode: ChartSourceMode,
    crop_width_px: int,
    crop_height_px: int,
    config: ChartExtractorConfig,
    extra_issues: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """
    Audits extracted chart structures and flags ``review_required=True`` whenever
    axis calibration, text resolution, dual-axis attribution, or geometry is
    incomplete or unreliable. Never alters or fabricates numeric values.
    """
    issues: List[Dict[str, Any]] = list(extra_issues)

    if crop_width_px < config.low_resolution_min_width_px or crop_height_px < config.low_resolution_min_height_px:
        issues.append({
            "code": "low_resolution_chart",
            "severity": "high",
            "detail": f"Chart crop {crop_width_px}x{crop_height_px}px is below minimum reliable resolution ({config.low_resolution_min_width_px}x{config.low_resolution_min_height_px}px).",
        })

    if chart_type == ChartType.UNKNOWN:
        issues.append({
            "code": "unknown_or_ambiguous_chart_type",
            "severity": "high",
            "detail": "Chart geometry could not be reliably classified into a known chart type.",
        })

    # Inspect numeric calibration requirements per chart type
    y1 = axes.get("y_primary") or {}
    y2 = axes.get("y_secondary") or {}
    x_ax = axes.get("x") or {}

    if chart_type in (ChartType.VERTICAL_BAR, ChartType.GROUPED_BAR, ChartType.STACKED_BAR, ChartType.LINE):
        if not y1.get("is_valid"):
            issues.append({
                "code": f"y_axis_{y1.get('reason', 'uncalibrated')}",
                "severity": "high",
                "detail": f"Primary vertical numeric axis calibration failed ({y1.get('reason', 'missing_ticks')}).",
            })
    elif chart_type == ChartType.HORIZONTAL_BAR:
        if not x_ax.get("is_valid"):
            issues.append({
                "code": f"x_axis_{x_ax.get('reason', 'uncalibrated')}",
                "severity": "high",
                "detail": f"Horizontal numeric axis calibration failed ({x_ax.get('reason', 'missing_ticks')}).",
            })
    elif chart_type == ChartType.SCATTER:
        if not x_ax.get("is_valid"):
            issues.append({
                "code": f"x_axis_{x_ax.get('reason', 'uncalibrated')}",
                "severity": "high",
                "detail": "Scatter plot X numeric axis calibration failed.",
            })
        if not y1.get("is_valid"):
            issues.append({
                "code": f"y_axis_{y1.get('reason', 'uncalibrated')}",
                "severity": "high",
                "detail": "Scatter plot Y numeric axis calibration failed.",
            })

    if y2 and y2.get("present") and not y2.get("is_valid"):
        issues.append({
            "code": "secondary_y_axis_uncalibrated",
            "severity": "medium",
            "detail": f"Secondary right Y axis ticks could not be reliably calibrated ({y2.get('reason', 'missing')}).",
        })

    # OCR quality check on raster/mixed charts
    if source_mode in (ChartSourceMode.RASTER, ChartSourceMode.MIXED):
        if not ocr_meta.get("ocr_available", True) and not ocr_meta.get("has_native_fallback", False):
            issues.append({
                "code": "ocr_unavailable",
                "severity": "high",
                "detail": "Tesseract OCR was unavailable on raster chart text.",
            })
        elif float(ocr_meta.get("confidence", 0.0) or 0.0) < config.min_ocr_confidence_for_review:
            issues.append({
                "code": "low_ocr_confidence",
                "severity": "medium",
                "detail": f"OCR confidence ({float(ocr_meta.get('confidence', 0.0) or 0.0):.2f}) is below review threshold {config.min_ocr_confidence_for_review:.2f}.",
            })

    # Check point precision counts & missing category/value completeness
    counts = {
        ValuePrecisionStatus.EXACT.value: 0,
        ValuePrecisionStatus.ESTIMATED.value: 0,
        ValuePrecisionStatus.UNAVAILABLE.value: 0,
    }
    missing_label_count = 0
    for s in series:
        for dp in s.get("data_points") or []:
            st = str(dp.get("precision", ValuePrecisionStatus.UNAVAILABLE.value))
            counts[st] = counts.get(st, 0) + 1
            if chart_type in (ChartType.VERTICAL_BAR, ChartType.HORIZONTAL_BAR, ChartType.GROUPED_BAR, ChartType.STACKED_BAR, ChartType.PIE):
                if not str(dp.get("category") or "").strip():
                    missing_label_count += 1

    if missing_label_count > 0:
        issues.append({
            "code": "missing_category_or_slice_labels",
            "severity": "medium",
            "detail": f"{missing_label_count} chart element(s) lacked readable category/slice labels.",
        })

    if not series or sum(len(s.get("data_points") or []) for s in series) == 0:
        issues.append({
            "code": "no_chart_elements_reconstructed",
            "severity": "high",
            "detail": "No bar, line, slice, or scatter elements could be extracted.",
        })
    elif counts[ValuePrecisionStatus.UNAVAILABLE.value] > 0:
        issues.append({
            "code": "unavailable_data_point_values",
            "severity": "high",
            "detail": f"{counts[ValuePrecisionStatus.UNAVAILABLE.value]} data point(s) could not be numerically resolved without fabrication.",
        })

    # Deduplicate by code cleanly
    dedup_issues: List[Dict[str, Any]] = []
    seen_codes = set()
    for iss in issues:
        code = str(iss.get("code") or "issue")
        if code not in seen_codes:
            seen_codes.add(code)
            dedup_issues.append(iss)

    review_required = any(
        iss.get("severity") == "high"
        or iss.get("code") in ("missing_category_or_slice_labels", "low_ocr_confidence", "secondary_y_axis_uncalibrated")
        for iss in dedup_issues
    )
    return {
        "is_reliable": not review_required,
        "review_required": review_required,
        "needs_review": review_required,
        "issue_codes": sorted(seen_codes),
        "issues": dedup_issues,
        "value_counts_by_precision": counts,
    }


# ==============================================================================
# MAIN CHART EXTRACTOR SERVICE
# ==============================================================================
class PyMuPDFOpenCVChartExtractor:
    """
    Extracts structured chart representations using PyMuPDF (native vector paths
    & native text), OpenCV (axes, ticks, gridlines, bars, lines, pie wedges,
    scatter markers, legends), and existing LORE ``TesseractOCRProvider``.
    """

    provider_name = "pymupdf_opencv_chart"
    engine_version = f"pymupdf-{PYMUPDF_VERSION}_cv2-{OPENCV_VERSION}"
    requires_remote_egress = False

    def __init__(
        self,
        config: Optional[ChartExtractorConfig] = None,
        ocr_provider: Optional[BaseOCRProvider] = None,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
    ):
        self.config = config or ChartExtractorConfig.from_settings_or_env()
        self.ocr_provider: BaseOCRProvider = ocr_provider or TesseractOCRProvider()
        self.repair_bengali = repair_bengali
        self.convert_bangla_digits = convert_bangla_digits

    @staticmethod
    def is_available() -> bool:
        return True  # Degrades cleanly even if OpenCV/PyMuPDF optional

    def _merge_native_and_ocr_tokens(
        self,
        native_tokens: Sequence[Mapping[str, Any]],
        ocr_tokens: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = [dict(t) for t in native_tokens]
        for ot in ocr_tokens:
            ob = ot["bbox_crop"]
            oa = max(1.0, (ob[2] - ob[0]) * (ob[3] - ob[1]))
            overlaps_native = any(
                _box_intersection_area(ob, nt["bbox_crop"]) >= 0.30 * min(oa, max(1.0, (nt["bbox_crop"][2] - nt["bbox_crop"][0]) * (nt["bbox_crop"][3] - nt["bbox_crop"][1])))
                for nt in native_tokens
            )
            if not overlaps_native:
                merged.append(dict(ot))
        return merged

    def _detect_vector_axes(
        self,
        vector_prims: Mapping[str, Any],
        crop_w: int,
        crop_h: int,
    ) -> Dict[str, Any]:
        """Identifies vector axes, plot box, tick stubs, and gridlines from PyMuPDF lines/rects."""
        h_segs: List[Dict[str, Any]] = []
        v_segs: List[Dict[str, Any]] = []
        raw_lines = list(vector_prims.get("lines") or [])

        # Decompose any thin stroke-only plot frame rects into lines if needed
        for ln in raw_lines:
            pts = ln.get("points") or [ln["p1"], ln["p2"]]
            for i in range(len(pts) - 1):
                x0, y0 = float(pts[i][0]), float(pts[i][1])
                x1, y1 = float(pts[i + 1][0]), float(pts[i + 1][1])
                dx, dy = abs(x1 - x0), abs(y1 - y0)
                if dy <= 1.8 and dx >= max(24.0, crop_w * 0.28):
                    h_segs.append({"y": 0.5 * (y0 + y1), "x0": min(x0, x1), "x1": max(x0, x1), "color": ln.get("color_rgb")})
                elif dx <= 1.8 and dy >= max(24.0, crop_h * 0.25):
                    v_segs.append({"x": 0.5 * (x0 + x1), "y0": min(y0, y1), "y1": max(y0, y1), "color": ln.get("color_rgb")})

        if not h_segs or not v_segs:
            return {"has_axes": False, "plot_box": (int(crop_w * 0.12), int(crop_h * 0.10), int(crop_w * 0.90), int(crop_h * 0.84))}

        h_segs.sort(key=lambda s: s["y"])
        v_segs.sort(key=lambda s: s["x"])

        left_v = min([s for s in v_segs if s["x"] <= crop_w * 0.45] or v_segs, key=lambda s: s["x"])
        right_cands = [s for s in v_segs if s["x"] >= max(left_v["x"] + crop_w * 0.25, crop_w * 0.55)]
        right_v = max(right_cands, key=lambda s: s["x"]) if right_cands else None
        bot_h = max([s for s in h_segs if s["y"] >= crop_h * 0.35] or h_segs, key=lambda s: s["y"])
        top_cands = [s for s in h_segs if s["y"] < min(left_v["y0"] + 15.0, crop_h * 0.35)]
        top_y = float(top_cands[0]["y"]) if top_cands and top_cands[0]["y"] < bot_h["y"] - 20 else float(left_v["y0"])

        px0 = round(max(left_v["x"], bot_h["x0"]))
        px1 = round(right_v["x"] if right_v else max(bot_h["x1"], px0 + crop_w * 0.45))
        py0 = round(min(left_v["y0"], top_y))
        py1 = round(max(bot_h["y"], left_v["y1"]))

        # Vector tick stubs (short segments perpendicular touching axis spine)
        y1_stubs: List[float] = []
        y2_stubs: List[float] = []
        x_stubs: List[float] = []
        for ln in raw_lines:
            pts = ln.get("points") or [ln["p1"], ln["p2"]]
            if len(pts) != 2:
                continue
            (lx0, ly0), (lx1, ly1) = pts[0], pts[1]
            dx, dy = abs(lx1 - lx0), abs(ly1 - ly0)
            if dy <= 1.5 and 2.0 <= dx <= 12.0:
                if abs(max(lx0, lx1) - left_v["x"]) <= 4.0 or abs(min(lx0, lx1) - left_v["x"]) <= 4.0:
                    y1_stubs.append(0.5 * (ly0 + ly1))
                elif right_v and (abs(min(lx0, lx1) - right_v["x"]) <= 4.0 or abs(max(lx0, lx1) - right_v["x"]) <= 4.0):
                    y2_stubs.append(0.5 * (ly0 + ly1))
            elif dx <= 1.5 and 2.0 <= dy <= 12.0:
                if abs(min(ly0, ly1) - bot_h["y"]) <= 4.0 or abs(max(ly0, ly1) - bot_h["y"]) <= 4.0:
                    x_stubs.append(0.5 * (lx0 + lx1))

        return {
            "has_axes": True,
            "plot_box": (px0, py0, px1, py1),
            "x_axis_y": float(bot_h["y"]),
            "y_axis_x": float(left_v["x"]),
            "y2_axis_x": float(right_v["x"]) if right_v else None,
            "y1_axis_color": left_v.get("color"),
            "y2_axis_color": right_v.get("color") if right_v else None,
            "h_grid_ys": sorted({round(s["y"], 2) for s in h_segs if py0 + 6 < s["y"] < py1 - 6}),
            "v_grid_xs": sorted({round(s["x"], 2) for s in v_segs if px0 + 6 < s["x"] < px1 - 6}),
            "y1_tick_stubs": sorted(y1_stubs),
            "y2_tick_stubs": sorted(y2_stubs),
            "x_tick_stubs": sorted(x_stubs),
            "h_lines": h_segs,
            "v_lines": v_segs,
        }

    def _partition_tokens_by_role(
        self,
        *,
        tokens: Sequence[Mapping[str, Any]],
        axes_info: Mapping[str, Any],
        crop_w: int,
        crop_h: int,
        legends: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Separates chart tokens cleanly into Y1 ticks/title, Y2 ticks/title, X labels/title, plot labels, and chart title."""
        px0, py0, px1, py1 = axes_info.get("plot_box") or (int(crop_w * 0.12), int(crop_h * 0.10), int(crop_w * 0.90), int(crop_h * 0.84))
        y_ax = float(axes_info.get("y_axis_x") or px0)
        x_ax = float(axes_info.get("x_axis_y") or py1)
        y2_ax = axes_info.get("y2_axis_x")

        legend_boxes = [tuple(lg["label_box_crop"]) for lg in legends]

        def _is_legend(tk: Mapping[str, Any]) -> bool:
            return any(_box_intersection_area(tk["bbox_crop"], lb) >= 0.4 * max(1.0, tk["width"] * tk["height"]) for lb in legend_boxes)

        y1_tick_cands: List[Dict[str, Any]] = []
        y2_tick_cands: List[Dict[str, Any]] = []
        x_tick_cands: List[Dict[str, Any]] = []
        x_cat_labels: List[Dict[str, Any]] = []
        y_cat_labels: List[Dict[str, Any]] = []
        left_title_parts: List[Dict[str, Any]] = []
        right_title_parts: List[Dict[str, Any]] = []
        bottom_title_parts: List[Dict[str, Any]] = []
        top_title_parts: List[Dict[str, Any]] = []
        plot_interior_tokens: List[Dict[str, Any]] = []

        y1_stubs = list(axes_info.get("y1_tick_stubs") or []) + list(axes_info.get("h_grid_ys") or [])
        y2_stubs = list(axes_info.get("y2_tick_stubs") or []) + list(axes_info.get("h_grid_ys") or [])
        x_stubs = list(axes_info.get("x_tick_stubs") or []) + list(axes_info.get("v_grid_xs") or [])

        def _snap(coord: float, stubs: Sequence[float]) -> Tuple[float, bool]:
            if not stubs:
                return coord, False
            nearest = min(stubs, key=lambda s: abs(s - coord))
            if abs(nearest - coord) <= 8.0:
                return nearest, True
            return coord, False

        for tk in tokens:
            if _is_legend(tk):
                continue
            tb = tk["bbox_crop"]
            cx, cy = float(tk["cx"]), float(tk["cy"])
            txt = str(tk["text"] or "").strip()
            parsed = parse_chart_numeric_token(txt)

            # Left margin (left of Y1 spine within Y plot vertical range +- 20px)
            if tb[2] <= y_ax + 6.0 and (py0 - 20.0) <= cy <= (x_ax + 20.0):
                if tk.get("is_vertical_text"):
                    left_title_parts.append(dict(tk))
                elif parsed is not None:
                    snapped_y, sn = _snap(cy, y1_stubs)
                    item = dict(tk)
                    item["parsed"] = parsed
                    item["tick_coord"] = snapped_y
                    item["stub_snapped"] = sn
                    y1_tick_cands.append(item)
                else:
                    # Non-numeric left label could be horizontal bar category OR unrotated Y title piece
                    y_cat_labels.append(dict(tk))
                continue

            # Right margin (right of Y2 spine when Y2 exists)
            if y2_ax is not None and tb[0] >= float(y2_ax) - 4.0 and (py0 - 20.0) <= cy <= (x_ax + 20.0):
                if tk.get("is_vertical_text"):
                    right_title_parts.append(dict(tk))
                elif parsed is not None:
                    snapped_y, sn = _snap(cy, y2_stubs)
                    item = dict(tk)
                    item["parsed"] = parsed
                    item["tick_coord"] = snapped_y
                    item["stub_snapped"] = sn
                    y2_tick_cands.append(item)
                else:
                    right_title_parts.append(dict(tk))
                continue

            # Bottom margin (below X axis)
            if tb[1] >= x_ax - 4.0:
                # Separate tick row (close to x_ax) vs X-axis title row further down
                if parsed is not None and tb[1] <= x_ax + 34.0:
                    snapped_x, sn = _snap(cx, x_stubs)
                    item = dict(tk)
                    item["parsed"] = parsed
                    item["tick_coord"] = snapped_x
                    item["stub_snapped"] = sn
                    x_tick_cands.append(item)
                elif tb[1] <= x_ax + 34.0:
                    x_cat_labels.append(dict(tk))
                else:
                    bottom_title_parts.append(dict(tk))
                continue

            # Top margin above plot
            if tb[3] <= py0 + 4.0:
                top_title_parts.append(dict(tk))
                continue

            # Inside plot frame -> data labels / legend labels / pie wedge labels
            plot_interior_tokens.append(dict(tk))

        # Separate unrotated Y axis title on far left if multiple horizontal labels exist (vs horizontal bar categories)
        y1_title_parts: List[Dict[str, Any]] = list(left_title_parts)
        if y_cat_labels and not y1_tick_cands:
            # Horizontal bar categories sit immediately next to Y axis (`max cx`), whereas far-left text can be Y title
            y1_title_text = " ".join(p["text"] for p in sorted(y1_title_parts, key=lambda p: p["cy"]))
        else:
            # Since Y1 numeric ticks exist on left, any leftmost non-numeric text is Y1 axis title!
            y1_title_parts.extend(y_cat_labels)
            y_cat_labels = []
            y1_title_parts.sort(key=lambda p: (round(p["cx"] / 8.0), -p["cy"] if p.get("is_vertical_text") else p["cy"]))
            y1_title_text = " ".join(p["text"] for p in y1_title_parts)

        y2_title_text = " ".join(p["text"] for p in right_title_parts)
        # Disambiguate X-axis bottom title if bottom_title_parts empty vs multi-row below X labels
        if not bottom_title_parts and x_cat_labels:
            # If two distinct rows below X axis, lower centered row is X axis title
            min_y_x = min(t["cy"] for t in x_cat_labels)
            row1 = [t for t in x_cat_labels if t["cy"] <= min_y_x + 14.0]
            row2 = [t for t in x_cat_labels if t["cy"] > min_y_x + 14.0]
            if row2 and len(row1) >= 2:
                x_cat_labels = row1
                bottom_title_parts = row2

        x_title_text = " ".join(p["text"] for p in sorted(bottom_title_parts, key=lambda p: p["bbox_crop"][0]))
        top_title_parts.sort(key=lambda p: (round(p["cy"] / 8.0), p["bbox_crop"][0]))
        chart_title = " ".join(p["text"] for p in top_title_parts)

        return {
            "y1_tick_cands": y1_tick_cands,
            "y2_tick_cands": y2_tick_cands,
            "x_tick_cands": x_tick_cands,
            "x_cat_labels": sorted(x_cat_labels, key=lambda p: p["cx"]),
            "y_cat_labels": sorted(y_cat_labels, key=lambda p: p["cy"]),
            "y1_title": y1_title_text.strip(),
            "y2_title": y2_title_text.strip(),
            "x_title": x_title_text.strip(),
            "chart_title": chart_title.strip(),
            "plot_interior_tokens": plot_interior_tokens,
        }

    def _detect_dual_axis_binding(
        self,
        *,
        series_name: str,
        series_color: Optional[Sequence[int]],
        y1_cal: Mapping[str, Any],
        y2_cal: Mapping[str, Any],
        axes_info: Mapping[str, Any],
    ) -> Tuple[str, Optional[Mapping[str, Any]], bool]:
        """
        Deterministically binds a series to primary ``y1`` or secondary ``y2`` ONLY
        when explicit unit, label, or axis color evidence identifies the axis.
        Never guesses when binding is ambiguous.
        """
        if not y2_cal or not y2_cal.get("present"):
            return "y1", y1_cal if y1_cal.get("is_valid") else None, False

        low_name = series_name.lower()
        u1 = str(y1_cal.get("unit") or "").lower()
        u2 = str(y2_cal.get("unit") or "").lower()
        t1 = str(y1_cal.get("title") or "").lower()
        t2 = str(y2_cal.get("title") or "").lower()

        # 1. Explicit axis hints in legend/series label
        if any(tag in low_name for tag in ("(right)", "[right]", "(y2)", "y2")):
            return "y2", y2_cal if y2_cal.get("is_valid") else None, False
        if any(tag in low_name for tag in ("(left)", "[left]", "(y1)", "y1")):
            return "y1", y1_cal if y1_cal.get("is_valid") else None, False

        # 2. Exclusive unit match between series label and axis unit/title
        match_y1 = (bool(u1) and u1 in low_name) or any(w in low_name for w in t1.split() if len(w) >= 3)
        match_y2 = (bool(u2) and u2 in low_name) or any(w in low_name for w in t2.split() if len(w) >= 3)
        if match_y2 and not match_y1:
            return "y2", y2_cal if y2_cal.get("is_valid") else None, False
        if match_y1 and not match_y2:
            return "y1", y1_cal if y1_cal.get("is_valid") else None, False

        # 3. Color match against non-black Y1 vs Y2 spine/title colors
        c1 = axes_info.get("y1_axis_color")
        c2 = axes_info.get("y2_axis_color")
        if series_color and c1 and c2 and not (_is_neutral_gray_or_white(c1) and _is_neutral_gray_or_white(c2)):
            d1 = _rgb_distance(series_color, c1) if not _is_neutral_gray_or_white(c1) else 999.0
            d2 = _rgb_distance(series_color, c2) if not _is_neutral_gray_or_white(c2) else 999.0
            if d2 < 50.0 and d1 > 80.0:
                return "y2", y2_cal if y2_cal.get("is_valid") else None, False
            if d1 < 50.0 and d2 > 80.0:
                return "y1", y1_cal if y1_cal.get("is_valid") else None, False

        # Ambiguous dual-axis binding -> refuse to guess!
        return "ambiguous", None, True

    def _match_native_data_label(
        self,
        elem_box: Tuple[float, float, float, float],
        interior_tokens: Sequence[Mapping[str, Any]],
        max_dist_px: float = 22.0,
    ) -> Optional[Dict[str, Any]]:
        """Matches an explicit native PDF numeric data label directly bound to a chart element."""
        ecx = 0.5 * (elem_box[0] + elem_box[2])
        ecy = 0.5 * (elem_box[1] + elem_box[3])
        best = None
        best_score = 1e9
        for tk in interior_tokens:
            if tk.get("source") != "native_pdf":
                continue
            parsed = parse_chart_numeric_token(tk["text"])
            if not parsed:
                continue
            tb = tk["bbox_crop"]
            # Must either sit inside element OR immediately above/right within max_dist_px
            inside = elem_box[0] - 4 <= tk["cx"] <= elem_box[2] + 4 and elem_box[1] - 4 <= tk["cy"] <= elem_box[3] + 4
            above = abs(tk["cx"] - ecx) <= max(14.0, 0.7 * (elem_box[2] - elem_box[0])) and 0.0 <= (elem_box[1] - tb[3]) <= max_dist_px
            right_of = abs(tk["cy"] - ecy) <= max(12.0, 0.7 * (elem_box[3] - elem_box[1])) and 0.0 <= (tb[0] - elem_box[2]) <= max_dist_px
            if inside or above or right_of:
                d = math.hypot(tk["cx"] - ecx, tk["cy"] - ecy)
                if d < best_score:
                    best_score = d
                    best = {"parsed": parsed, "token": tk}
        return best

    def _reconstruct_bars(
        self,
        *,
        bar_rects: Sequence[Mapping[str, Any]],
        axes_info: Mapping[str, Any],
        y1_cal: Mapping[str, Any],
        y2_cal: Mapping[str, Any],
        x_cal: Mapping[str, Any],
        partitions: Mapping[str, Any],
        legends: Sequence[Mapping[str, Any]],
        crop_geom: Mapping[str, Any],
        source_mode: ChartSourceMode,
    ) -> Tuple[ChartType, List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Reconstructs vertical, horizontal, grouped, and stacked bars preserving exact baselines."""
        extra_issues: List[Dict[str, Any]] = []
        bars = list(bar_rects)
        px0, py0, px1, py1 = axes_info.get("plot_box") or (0, 0, 100, 100)
        x_ax_y = float(axes_info.get("x_axis_y") or py1)
        y_ax_x = float(axes_info.get("y_axis_x") or px0)

        # Distinguish vertical vs horizontal bars deterministically
        horiz_vote = sum(1 for b in bars if abs(b["bbox_crop"][0] - y_ax_x) <= 8.0 and (b["bbox_crop"][2] - b["bbox_crop"][0]) > (b["bbox_crop"][3] - b["bbox_crop"][1]))
        vert_vote = len(bars) - horiz_vote
        is_horizontal = (
            (len(partitions.get("y_cat_labels") or []) >= 2 and not y1_cal.get("is_valid") and x_cal.get("is_valid"))
            or (horiz_vote > vert_vote and x_cal.get("is_valid") and not y1_cal.get("is_valid"))
        )

        # Group bars sharing X slot (for vertical) or Y slot (for horizontal)
        slot_groups: List[List[Mapping[str, Any]]] = []
        ordered = sorted(bars, key=lambda b: b["bbox_crop"][1 if is_horizontal else 0])
        for b in ordered:
            bb = b["bbox_crop"]
            if is_horizontal:
                a0, a1 = bb[1], bb[3]
            else:
                a0, a1 = bb[0], bb[2]
            placed = False
            for grp in slot_groups:
                g0 = min(item["bbox_crop"][1 if is_horizontal else 0] for item in grp)
                g1 = max(item["bbox_crop"][3 if is_horizontal else 2] for item in grp)
                inter = max(0.0, min(a1, g1) - max(a0, g0))
                min_w = max(1.0, min(a1 - a0, g1 - g0))
                if inter >= 0.55 * min_w:
                    grp.append(b)
                    placed = True
                    break
            if not placed:
                slot_groups.append([b])

        is_stacked = any(len(g) >= 2 for g in slot_groups)
        distinct_colors = []
        for b in bars:
            col = b.get("color_rgb")
            if col and not any(_rgb_distance(col, ex) <= 45.0 for ex in distinct_colors):
                distinct_colors.append(col)

        if is_stacked:
            chart_type = ChartType.STACKED_BAR
        elif is_horizontal:
            chart_type = ChartType.HORIZONTAL_BAR
        else:
            # Check grouped bars: tight inner gaps + repeated multi-color pattern OR >=2 legend series with multiple bars
            x_centers = sorted(0.5 * (b["bbox_crop"][0] + b["bbox_crop"][2]) for b in bars)
            gaps = [x_centers[i + 1] - x_centers[i] for i in range(len(x_centers) - 1)]
            has_bimodal_gaps = len(gaps) >= 3 and (max(gaps) / max(min(gaps), 1.0)) >= 1.65
            has_multi_series = len(distinct_colors) >= 2 and (len(bars) % max(len(distinct_colors), 2) == 0 or len(legends) >= 2 or has_bimodal_gaps)
            chart_type = ChartType.GROUPED_BAR if (has_multi_series and (has_bimodal_gaps or len(legends) >= 2)) else ChartType.VERTICAL_BAR

        # Build series clusters for grouped vs single
        interior_tokens = partitions.get("plot_interior_tokens") or []
        if is_horizontal:
            cat_tokens = list(partitions.get("y_cat_labels") or [])
        else:
            cat_tokens = list(partitions.get("x_cat_labels") or []) or list(partitions.get("x_tick_cands") or [])
        cal = x_cal if is_horizontal else y1_cal
        if is_horizontal and y2_cal and y2_cal.get("present"):
            pass

        val_source_geom = (
            "vector_geometry_axis_projection" if source_mode == ChartSourceMode.VECTOR else "raster_pixel_axis_projection"
        )

        series_map: Dict[str, Dict[str, Any]] = {}
        series_palette_idx: List[Tuple[int, int, int]] = []

        def _series_for_color(rgb: Optional[Sequence[int]]) -> Tuple[str, Optional[Tuple[int, int, int]]]:
            if rgb is None:
                return "Series 1", None
            for idx, ex in enumerate(series_palette_idx, start=1):
                if _rgb_distance(rgb, ex) <= 50.0:
                    return _match_series_name_by_color(ex, legends, idx), ex
            col3 = (rgb[0], rgb[1], rgb[2]) if len(rgb) >= 3 else (0, 0, 0)
            series_palette_idx.append(col3)
            idx = len(series_palette_idx)
            return _match_series_name_by_color(rgb, legends, idx), col3

        # Re-cluster into logical categories when GROUPED_BAR using actual gap distribution
        if chart_type == ChartType.GROUPED_BAR:
            sorted_x = ordered
            edge_gaps = [
                max(0.0, sorted_x[i + 1]["bbox_crop"][0] - sorted_x[i]["bbox_crop"][2])
                for i in range(len(sorted_x) - 1)
            ]
            if len(edge_gaps) >= 2 and max(edge_gaps) > max(4.0, 1.45 * min(edge_gaps)):
                # Split at largest cluster-level jump between intra-group and inter-group gaps
                gaps_sorted = sorted(edge_gaps)
                best_split_gap = max(gaps_sorted) * 0.65
                max_jump = 0.0
                for g_i in range(len(gaps_sorted) - 1):
                    jump = gaps_sorted[g_i + 1] - gaps_sorted[g_i]
                    if jump > max_jump:
                        max_jump = jump
                        best_split_gap = 0.5 * (gaps_sorted[g_i] + gaps_sorted[g_i + 1])
            else:
                mean_bw = sum(b["bbox_crop"][2] - b["bbox_crop"][0] for b in sorted_x) / max(len(sorted_x), 1)
                best_split_gap = max(12.0, 0.7 * mean_bw)

            cat_groups: List[List[Mapping[str, Any]]] = []
            for b in sorted_x:
                bb = b["bbox_crop"]
                if not cat_groups:
                    cat_groups.append([b])
                else:
                    prev_r = cat_groups[-1][-1]["bbox_crop"][2]
                    if (bb[0] - prev_r) <= best_split_gap:
                        cat_groups[-1].append(b)
                    else:
                        cat_groups.append([b])
        else:
            cat_groups = slot_groups

        for grp in cat_groups:
            # Category coordinate is cluster centroid along category axis
            if is_horizontal:
                g_c = 0.5 * (min(b["bbox_crop"][1] for b in grp) + max(b["bbox_crop"][3] for b in grp))
            else:
                g_c = 0.5 * (min(b["bbox_crop"][0] for b in grp) + max(b["bbox_crop"][2] for b in grp))

            matched_cat = ""
            if cat_tokens:
                best_ct = min(cat_tokens, key=lambda ct: abs((ct["cy"] if is_horizontal else ct["cx"]) - g_c))
                if abs((best_ct["cy"] if is_horizontal else best_ct["cx"]) - g_c) <= max(42.0, 0.20 * (crop_geom["crop_height"] if is_horizontal else crop_geom["crop_width"])):
                    matched_cat = str(best_ct["text"])

            # Order stacked segments from baseline outward
            if is_stacked:
                grp_sorted = sorted(grp, key=lambda b: b["bbox_crop"][0] if is_horizontal else -b["bbox_crop"][3])
            else:
                grp_sorted = grp

            for seg_idx, b in enumerate(grp_sorted):
                bb = b["bbox_crop"]
                s_name, rep_col = _series_for_color(b.get("color_rgb"))
                axis_id, bound_cal, is_ambig_dual = self._detect_dual_axis_binding(
                    series_name=s_name,
                    series_color=rep_col,
                    y1_cal=cal,
                    y2_cal=y2_cal if not is_horizontal else {},
                    axes_info=axes_info,
                )
                if is_ambig_dual:
                    extra_issues.append({
                        "code": "ambiguous_dual_axis_binding",
                        "severity": "high",
                        "detail": f"Could not determine whether {s_name!r} maps to primary Y1 or secondary Y2 axis.",
                    })

                elem_page_coords = crop_box_to_page_coords(bb, crop_geom)
                native_lbl = self._match_native_data_label(bb, interior_tokens)

                unit = (bound_cal or cal).get("unit") or ""
                cum_val: Optional[float] = None
                if native_lbl is not None:
                    val = float(native_lbl["parsed"]["value"])
                    unit = native_lbl["parsed"].get("unit") or unit
                    precision = ValuePrecisionStatus.EXACT.value
                    v_source = "native_data_label"
                    uncertainty = 0.0
                elif bound_cal and bound_cal.get("is_valid") and not is_ambig_dual:
                    ref_coord = float(bound_cal["zero_coord"]) if bound_cal.get("zero_coord") is not None else float(bound_cal["origin_coord"])
                    if is_horizontal:
                        a0, a1 = bb[0], bb[2]
                    else:
                        a0, a1 = bb[1], bb[3]
                    far_c = a1 if abs(a1 - ref_coord) >= abs(a0 - ref_coord) else a0
                    near_c = a0 if far_c == a1 else a1

                    v_far = _coord_to_calibrated_value(far_c, bound_cal)
                    v_near = _coord_to_calibrated_value(near_c, bound_cal)
                    cum_val = round(v_far, 4) if v_far is not None else None
                    if is_stacked and seg_idx > 0 and v_far is not None and v_near is not None:
                        if is_horizontal:
                            val = abs(v_far - v_near) if far_c >= ref_coord else -abs(v_far - v_near)
                        else:
                            val = abs(v_far - v_near) if far_c <= ref_coord else -abs(v_far - v_near)
                    elif is_stacked and seg_idx == 0 and not bound_cal.get("contains_zero"):
                        extra_issues.append({
                            "code": "stacked_bar_nonzero_origin_ambiguous",
                            "severity": "high",
                            "detail": "Stacked bar chart on truncated non-zero axis cannot determine base segment magnitude without fabrication.",
                        })
                        val = None
                    else:
                        val = v_far

                    if val is not None:
                        precision = ValuePrecisionStatus.ESTIMATED.value
                        v_source = val_source_geom
                        uncertainty = bound_cal.get("estimated_uncertainty")
                        val = round(val, 4)
                    else:
                        precision = ValuePrecisionStatus.UNAVAILABLE.value
                        v_source = "unavailable"
                        uncertainty = None
                else:
                    val = None
                    precision = ValuePrecisionStatus.UNAVAILABLE.value
                    v_source = "unavailable"
                    uncertainty = None
                    cum_val = None

                s_entry = series_map.setdefault(
                    s_name,
                    {
                        "name": s_name,
                        "axis": axis_id,
                        "unit": unit,
                        "color_rgb": list(rep_col) if rep_col else None,
                        "color_hex": _rgb_to_hex(rep_col) if rep_col else "",
                        "data_points": [],
                    },
                )
                dp_item: Dict[str, Any] = {
                    "category": matched_cat,
                    "x": matched_cat or round(g_c, 2),
                    "value": val,
                    "precision": precision,
                    "unit": unit,
                    "uncertainty": uncertainty,
                    "source": v_source,
                    "axis": axis_id,
                    "bbox": elem_page_coords["bbox"],
                    "normalized_box": elem_page_coords["normalized_box"],
                }
                if is_stacked and cum_val is not None:
                    dp_item["cumulative_value"] = cum_val
                s_entry["data_points"].append(dp_item)

        return chart_type, list(series_map.values()), extra_issues

    def _reconstruct_pie(
        self,
        *,
        sectors: Sequence[Mapping[str, Any]],
        all_tokens: Sequence[Mapping[str, Any]],
        legends: Sequence[Mapping[str, Any]],
        crop_geom: Mapping[str, Any],
        source_mode: ChartSourceMode,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Reconstructs pie chart slice shares without fabricating unprinted absolute values."""
        extra_issues: List[Dict[str, Any]] = []
        total_sweep = sum(float(s["sweep_deg"]) for s in sectors)
        if abs(total_sweep - 360.0) > 25.0:
            extra_issues.append({
                "code": "incomplete_pie_angles",
                "severity": "high",
                "detail": f"Detected pie sectors cover {total_sweep:.1f} deg (expected ~360 deg).",
            })

        legend_boxes = [tuple(lg["label_box_crop"]) for lg in legends]
        candidate_tokens = [
            t
            for t in all_tokens
            if not any(_box_intersection_area(t["bbox_crop"], lb) >= 0.4 * max(1.0, t["width"] * t["height"]) for lb in legend_boxes)
        ]

        data_points: List[Dict[str, Any]] = []
        val_src_angle = "vector_pie_angle" if source_mode == ChartSourceMode.VECTOR else "raster_pie_angle"

        for idx, sec in enumerate(sectors, start=1):
            cx, cy = sec["center_crop"]
            rad = float(sec.get("radius_px") or 60.0)
            mid_rad = math.radians(float(sec["mid_deg"]))
            col = sec.get("color_rgb")
            lbl_from_legend = _match_series_name_by_color(col, legends, idx) if legends else ""
            if lbl_from_legend.startswith("Series "):
                lbl_from_legend = ""

            # Find label/value tokens aligned along slice mid-angle or inside slice box
            sec_box = sec["bbox_crop"]
            matched_tokens: List[Mapping[str, Any]] = []
            ray_x = cx + 0.65 * rad * math.cos(mid_rad)
            ray_y = cy + 0.65 * rad * math.sin(mid_rad)
            for tk in candidate_tokens:
                dx = float(tk["cx"]) - cx
                dy = float(tk["cy"]) - cy
                dist_c = math.hypot(dx, dy)
                if dist_c < 4.0 or dist_c > rad * 2.15:
                    continue
                tok_deg = math.degrees(math.atan2(dy, dx)) % 360.0
                ang_diff = abs((tok_deg - float(sec["mid_deg"]) + 540.0) % 360.0 - 180.0)
                if ang_diff <= max(18.0, 0.55 * float(sec["sweep_deg"])):
                    matched_tokens.append(tk)

            native_val = None
            cat_parts: List[str] = []
            for mt in sorted(matched_tokens, key=lambda t: math.hypot(t["cx"] - ray_x, t["cy"] - ray_y)):
                pnum = parse_chart_numeric_token(mt["text"])
                if pnum is not None and native_val is None and mt.get("source") == "native_pdf":
                    native_val = pnum
                elif pnum is None:
                    cat_parts.append(str(mt["text"]))
                else:
                    # Handle mixed string like "Cloud 40%" where entire token wasn't pure numeric
                    pass

            # Also parse trailing % or numeric inside combined slice labels like "Cloud 40%"
            cat_label = lbl_from_legend or " ".join(cat_parts).strip()
            if native_val is None and cat_label:
                m_pct = re.search(r"(-?\d+(?:\.\d+)?)\s*%", cat_label)
                if m_pct and any(mt.get("source") == "native_pdf" for mt in matched_tokens):
                    native_val = {"value": float(m_pct.group(1)), "unit": "%", "is_percent": True}
                    cat_label = re.sub(r"\s*-?\d+(?:\.\d+)?\s*%", "", cat_label).strip()

            geom_pct = round((float(sec["sweep_deg"]) / 360.0) * 100.0, 2)
            elem_coords = crop_box_to_page_coords(sec_box, crop_geom)

            if native_val is not None:
                val = float(native_val["value"])
                unit = str(native_val.get("unit") or "%")
                precision = ValuePrecisionStatus.EXACT.value
                v_src = "native_data_label"
                unc = 0.0
            elif abs(total_sweep - 360.0) <= 25.0:
                val = geom_pct
                unit = "%"
                precision = ValuePrecisionStatus.ESTIMATED.value
                v_src = val_src_angle
                unc = round(360.0 / max(24.0, 2 * math.pi * rad), 2)
            else:
                val = None
                unit = "%"
                precision = ValuePrecisionStatus.UNAVAILABLE.value
                v_src = "unavailable"
                unc = None

            data_points.append({
                "category": cat_label,
                "value": val,
                "precision": precision,
                "unit": unit,
                "estimated_angle_share_pct": geom_pct,
                "sweep_deg": round(float(sec["sweep_deg"]), 2),
                "uncertainty": unc,
                "source": v_src,
                "color_rgb": list(col) if col else None,
                "color_hex": _rgb_to_hex(col) if col else "",
                "bbox": elem_coords["bbox"],
                "normalized_box": elem_coords["normalized_box"],
            })

        return (
            [{"name": "Pie Distribution", "axis": "radial", "unit": "%", "data_points": data_points}],
            extra_issues,
        )

    def _reconstruct_lines(
        self,
        *,
        vector_polylines: Sequence[Mapping[str, Any]],
        raster_line_series: Sequence[Mapping[str, Any]],
        axes_info: Mapping[str, Any],
        y1_cal: Mapping[str, Any],
        y2_cal: Mapping[str, Any],
        x_cal: Mapping[str, Any],
        partitions: Mapping[str, Any],
        legends: Sequence[Mapping[str, Any]],
        crop_geom: Mapping[str, Any],
        source_mode: ChartSourceMode,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Reconstructs line chart vertices against X categories/numeric ticks & calibrated Y axes."""
        extra_issues: List[Dict[str, Any]] = []
        cat_tokens = list(partitions.get("x_cat_labels") or []) or list(partitions.get("x_tick_cands") or [])
        interior_tokens = partitions.get("plot_interior_tokens") or []
        series_out: List[Dict[str, Any]] = []

        raw_series: List[Dict[str, Any]] = []
        if vector_polylines:
            # Group continuous vector strokes by stroke color
            by_col: List[Dict[str, Any]] = []
            for pl in vector_polylines:
                col = pl.get("color_rgb") or (0, 0, 0)
                pts = list(pl.get("points") or [pl["p1"], pl["p2"]])
                merged = False
                for g in by_col:
                    if _rgb_distance(col, g["color_rgb"]) <= 45.0:
                        g["points"].extend(pts)
                        merged = True
                        break
                if not merged:
                    by_col.append({"color_rgb": col, "points": pts, "source": "vector_geometry_axis_projection"})
            raw_series = by_col
        else:
            for rs in raster_line_series:
                raw_series.append({"color_rgb": rs["color_rgb"], "points": rs["samples_xy"], "source": "raster_pixel_axis_projection"})

        for idx, rs in enumerate(raw_series, start=1):
            col = rs["color_rgb"]
            s_name = _match_series_name_by_color(col, legends, idx)
            axis_id, bound_cal, is_ambig_dual = self._detect_dual_axis_binding(
                series_name=s_name,
                series_color=col,
                y1_cal=y1_cal,
                y2_cal=y2_cal,
                axes_info=axes_info,
            )
            if is_ambig_dual:
                extra_issues.append({
                    "code": "ambiguous_dual_axis_binding",
                    "severity": "high",
                    "detail": f"Could not determine whether line {s_name!r} maps to primary Y1 or secondary Y2 axis.",
                })

            # Deduplicate vertices cleanly in left-to-right X order
            pts = sorted(rs["points"], key=lambda p: float(p[0]))
            sample_pts: List[Tuple[float, float]] = []
            if cat_tokens and rs["source"] == "raster_pixel_axis_projection":
                # Sample median curve y aligned tightly around each X category center
                for ct in cat_tokens:
                    near_ys = [p[1] for p in pts if abs(p[0] - ct["cx"]) <= 6.0]
                    if near_ys:
                        near_ys.sort()
                        sample_pts.append((float(ct["cx"]), float(near_ys[len(near_ys) // 2])))
            else:
                for p in pts:
                    if not sample_pts or abs(p[0] - sample_pts[-1][0]) > 2.0 or abs(p[1] - sample_pts[-1][1]) > 2.0:
                        sample_pts.append((float(p[0]), float(p[1])))

            # If continuous sampled raster pixels without discrete vertices, keep endpoints + X ticks + extrema corners
            if len(sample_pts) > 12 and not cat_tokens:
                step = max(1, len(sample_pts) // 8)
                sample_pts = sample_pts[::step]

            data_points: List[Dict[str, Any]] = []
            unit = (bound_cal or {}).get("unit") or ""
            for px_pt, py_pt in sample_pts:
                pt_box = (px_pt - 3.0, py_pt - 3.0, px_pt + 3.0, py_pt + 3.0)
                coords = crop_box_to_page_coords(pt_box, crop_geom)
                cat_lbl = ""
                if cat_tokens:
                    ct = min(cat_tokens, key=lambda c: abs(c["cx"] - px_pt))
                    if abs(ct["cx"] - px_pt) <= 32.0:
                        cat_lbl = str(ct["text"])
                x_num = _coord_to_calibrated_value(px_pt, x_cal) if x_cal.get("is_valid") else None

                native_lbl = self._match_native_data_label(pt_box, interior_tokens, max_dist_px=16.0)
                if native_lbl is not None:
                    val = float(native_lbl["parsed"]["value"])
                    precision = ValuePrecisionStatus.EXACT.value
                    v_src = "native_data_label"
                    unc = 0.0
                elif bound_cal and bound_cal.get("is_valid") and not is_ambig_dual:
                    val = _coord_to_calibrated_value(py_pt, bound_cal)
                    val = round(val, 4) if val is not None else None
                    precision = ValuePrecisionStatus.ESTIMATED.value if val is not None else ValuePrecisionStatus.UNAVAILABLE.value
                    v_src = rs["source"]
                    unc = bound_cal.get("estimated_uncertainty")
                else:
                    val = None
                    precision = ValuePrecisionStatus.UNAVAILABLE.value
                    v_src = "unavailable"
                    unc = None

                data_points.append({
                    "category": cat_lbl,
                    "x": round(x_num, 4) if x_num is not None else (cat_lbl or round(px_pt, 2)),
                    "value": val,
                    "precision": precision,
                    "unit": unit,
                    "uncertainty": unc,
                    "source": v_src,
                    "axis": axis_id,
                    "bbox": coords["bbox"],
                    "normalized_box": coords["normalized_box"],
                })

            series_out.append({
                "name": s_name,
                "axis": axis_id,
                "unit": unit,
                "color_rgb": list(col),
                "color_hex": _rgb_to_hex(col),
                "data_points": data_points,
            })

        return series_out, extra_issues

    def _reconstruct_scatter(
        self,
        *,
        markers: Sequence[Mapping[str, Any]],
        y1_cal: Mapping[str, Any],
        x_cal: Mapping[str, Any],
        legends: Sequence[Mapping[str, Any]],
        crop_geom: Mapping[str, Any],
        source_mode: ChartSourceMode,
        interior_tokens: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Reconstructs scatter markers onto calibrated numeric X and Y coordinates."""
        grouped: List[Dict[str, Any]] = []
        v_src = "vector_geometry_axis_projection" if source_mode == ChartSourceMode.VECTOR else "raster_pixel_axis_projection"

        for m in markers:
            col = m.get("color_rgb") or (0, 0, 0)
            target: Optional[Dict[str, Any]] = next((g for g in grouped if _rgb_distance(col, g["color_rgb"]) <= 50.0), None)
            if target is None:
                s_name = _match_series_name_by_color(col, legends, len(grouped) + 1)
                new_target: Dict[str, Any] = {
                    "name": s_name,
                    "axis": "x_y1",
                    "unit": str(y1_cal.get("unit") or ""),
                    "x_unit": str(x_cal.get("unit") or ""),
                    "color_rgb": list(col),
                    "color_hex": _rgb_to_hex(col),
                    "data_points": [],
                }
                grouped.append(new_target)
                target = new_target

            coords = crop_box_to_page_coords(m["bbox_crop"], crop_geom)
            xv = _coord_to_calibrated_value(m["cx"], x_cal)
            yv = _coord_to_calibrated_value(m["cy"], y1_cal)
            if xv is not None and yv is not None:
                x_out = round(xv, 4)
                y_out = round(yv, 4)
                prec = ValuePrecisionStatus.ESTIMATED.value
                src_out = v_src
                unc = y1_cal.get("estimated_uncertainty")
            else:
                x_out = None
                y_out = None
                prec = ValuePrecisionStatus.UNAVAILABLE.value
                src_out = "unavailable"
                unc = None

            target["data_points"].append({
                "x": x_out,
                "value": y_out,
                "precision": prec,
                "unit": str(y1_cal.get("unit") or ""),
                "x_unit": str(x_cal.get("unit") or ""),
                "uncertainty": unc,
                "source": src_out,
                "bbox": coords["bbox"],
                "normalized_box": coords["normalized_box"],
            })

        return grouped

    def extract_chart_region(
        self,
        *,
        page_image: Image.Image,
        chart_box: Optional[Sequence[float]] = None,
        bbox_format: str = "normalized",
        page_number: int = 1,
        page_width: Optional[float] = None,
        page_height: Optional[float] = None,
        source_rotation: int = 0,
        coords_in_unrotated_space: bool = False,
        region_id: Optional[str] = None,
        layout_score: Optional[float] = None,
        layout_label: str = "chart",
        pymupdf_page: Optional[Any] = None,
        source_mode_hint: Optional[str] = None,
        context_regions: Optional[Sequence[Mapping[str, Any]]] = None,
        source_asset_name: str = "",
        pre_cropped_display_rect: Optional[Sequence[float]] = None,
    ) -> Dict[str, Any]:
        """
        Full deterministic chart extraction entry point producing a contract-valid
        ``VisualRegionProvenanceContract`` record.
        """
        eff_region_id = region_id or f"p{page_number}-chart1"
        crop_img, crop_geom = resolve_chart_crop_geometry(
            page_image=page_image,
            chart_box=chart_box,
            bbox_format=bbox_format,
            page_width=page_width,
            page_height=page_height,
            source_rotation=source_rotation,
            coords_in_unrotated_space=coords_in_unrotated_space,
            padding_px=self.config.crop_padding_px,
            pre_cropped_display_rect=pre_cropped_display_rect,
        )

        if crop_img is None or not crop_geom:
            return cast(
                Dict[str, Any],
                build_visual_region_provenance(
                region_id=eff_region_id,
                region_type=VisualRegionType.CHART.value,
                extraction_kind=VisualExtractionKind.CHART_SERIES.value,
                page_number=page_number,
                bbox=[0.0, 0.0, float(page_width or page_image.width), float(page_height or page_image.height)],
                normalized_box=[0, 0, 1000, 1000],
                text="",
                markdown=format_visual_region_markdown(
                    page_number, eff_region_id, "Chart", "[Invalid or empty chart crop; flagged for review]"
                ),
                confidence=0.1,
                engine=self.provider_name,
                engine_version=self.engine_version,
                is_inference=False,
                is_repaired=False,
                source_asset_name=source_asset_name,
                metadata={
                    "review_required": True,
                    "needs_review": True,
                    "chart": {"chart_type": ChartType.UNKNOWN.value, "series": []},
                    "chart_validation": {"is_reliable": False, "review_required": True, "issue_codes": ["invalid_crop"]},
                },
                )
            )

        try:
            cw, ch = crop_img.size
            crop_bgr = cv2.cvtColor(np.asarray(crop_img), cv2.COLOR_RGB2BGR) if (HAS_OPENCV and HAS_NUMPY and cv2 is not None and np is not None) else None
            crop_ref = build_chart_crop_reference(
                crop_img=crop_img,
                crop_geom=crop_geom,
                page_number=page_number,
                region_id=eff_region_id,
                config=self.config,
                source_asset_name=source_asset_name,
            )

            # 1. Inspect native PDF vector primitives & text when PyMuPDF page is available
            vector_prims = extract_native_pdf_chart_primitives(
                pymupdf_page=pymupdf_page,
                display_rect_xyxy=crop_geom["chart_display_rect"],
                crop_geom=crop_geom,
            )
            native_tokens = list(vector_prims.get("native_tokens") or [])
            has_vector_geoms = vector_prims["vector_primitive_count"] >= 3 and not any(
                r["coverage_ratio"] > 0.70 for r in (vector_prims.get("raster_image_overlaps") or [])
            )

            # 2. Axis detection (vector first when rich primitives exist, supplemented by OpenCV)
            vec_axes: Dict[str, Any] = self._detect_vector_axes(vector_prims, cw, ch) if has_vector_geoms else {"has_axes": False}
            cv_axes: Dict[str, Any] = _detect_raster_plot_axes_opencv(crop_bgr, cw, ch) if crop_bgr is not None else {"has_axes": False}
            axes_info: Dict[str, Any] = vec_axes if vec_axes.get("has_axes") else cv_axes

            # 3. Determine source mode cleanly & trigger Tesseract OCR whenever raster / missing text
            need_ocr = (not has_vector_geoms) or (len(native_tokens) < 3)
            ocr_meta: Dict[str, Any] = {
                "ocr_available": True,
                "confidence": 0.99 if native_tokens else 0.0,
                "status": "native_skipped" if not need_ocr else "success",
                "engine": "pymupdf" if not need_ocr else "tesseract",
                "engine_version": PYMUPDF_VERSION if not need_ocr else "",
                "warnings": [],
                "has_native_fallback": bool(native_tokens),
                "ocr_triggered": need_ocr,
            }
            ocr_tokens: List[Dict[str, Any]] = []
            if need_ocr:
                ocr_out = extract_chart_text_with_tesseract(
                    crop_img=crop_img,
                    ocr_provider=self.ocr_provider,
                    axes_info=axes_info,
                    repair_bengali=self.repair_bengali,
                    convert_bangla_digits=self.convert_bangla_digits,
                )
                ocr_tokens = ocr_out["tokens"]
                ocr_meta.update({
                    "ocr_available": ocr_out["ocr_available"],
                    "confidence": ocr_out["confidence"] if ocr_out["ocr_available"] else (0.85 if native_tokens else 0.0),
                    "status": ocr_out["status"],
                    "engine": ocr_out["engine"],
                    "engine_version": ocr_out["engine_version"],
                    "language": ocr_out["language"],
                    "warnings": ocr_out["warnings"],
                    "full_text": ocr_out["full_text"],
                })

            if source_mode_hint in ("vector", "raster", "mixed"):
                source_mode = ChartSourceMode(source_mode_hint)
            elif has_vector_geoms and not ocr_tokens:
                source_mode = ChartSourceMode.VECTOR
            elif has_vector_geoms and ocr_tokens:
                source_mode = ChartSourceMode.MIXED
            elif not has_vector_geoms and native_tokens:
                source_mode = ChartSourceMode.MIXED
            else:
                source_mode = ChartSourceMode.RASTER

            all_tokens = self._merge_native_and_ocr_tokens(native_tokens, ocr_tokens)

            # 4. Detect legends and partition text tokens cleanly by axis / title role
            legends = _detect_legends(
                vector_prims=vector_prims,
                crop_bgr=crop_bgr,
                axes_info=axes_info,
                tokens=all_tokens,
                crop_w=cw,
                crop_h=ch,
            )
            partitions = self._partition_tokens_by_role(
                tokens=all_tokens,
                axes_info=axes_info,
                crop_w=cw,
                crop_h=ch,
                legends=legends,
            )

            # Attach adjacent layout chart_title if crop omitted title
            if not partitions["chart_title"] and context_regions:
                tbl_top_y = crop_geom["chart_normalized_box"][0]
                for creg in context_regions:
                    rlbl = str(creg.get("raw_label") or creg.get("metadata", {}).get("raw_label") or "").lower()
                    cbox = creg.get("normalized_box") or [1000, 0, 1000, 0]
                    if "chart_title" in rlbl or "title" in rlbl:
                        if abs(int(cbox[2]) - int(tbl_top_y)) <= 65 and str(creg.get("text") or "").strip():
                            partitions["chart_title"] = str(creg["text"]).strip()
                            break

            # 5. Calibrate numeric axes (no 0 assumption, no equal-interval assumption!)
            px0, py0, px1, py1 = axes_info.get("plot_box") or (int(cw * 0.12), int(ch * 0.10), int(cw * 0.90), int(ch * 0.84))
            y1_cal = calibrate_numeric_axis(
                axis_name="y_primary",
                orientation="vertical",
                tick_candidates=partitions["y1_tick_cands"],
                axis_origin_coord=axes_info.get("x_axis_y") or py1,
                axis_title=partitions["y1_title"],
                max_linear_residual=self.config.max_axis_linear_residual,
                min_r2=self.config.min_axis_r2,
            )
            has_y2 = bool(axes_info.get("y2_axis_x") is not None and (len(partitions["y2_tick_cands"]) >= 2 or bool(partitions["y2_title"])))
            y2_cal: Dict[str, Any] = {"axis": "y_secondary", "present": False, "is_valid": False}
            if has_y2:
                y2_cal = calibrate_numeric_axis(
                    axis_name="y_secondary",
                    orientation="vertical",
                    tick_candidates=partitions["y2_tick_cands"],
                    axis_origin_coord=axes_info.get("x_axis_y") or py1,
                    axis_title=partitions["y2_title"],
                    max_linear_residual=self.config.max_axis_linear_residual,
                    min_r2=self.config.min_axis_r2,
                )
                y2_cal["present"] = True

            x_cal = calibrate_numeric_axis(
                axis_name="x",
                orientation="horizontal",
                tick_candidates=partitions["x_tick_cands"],
                axis_origin_coord=axes_info.get("y_axis_x") or px0,
                axis_title=partitions["x_title"],
                max_linear_residual=self.config.max_axis_linear_residual,
                min_r2=self.config.min_axis_r2,
            )

            # Detect zero-crossing interior horizontal line when axis crosses 0
            if y1_cal.get("is_valid") and y1_cal.get("zero_coord") is None:
                y1_cal["zero_coord"] = None

            # 6. Identify geometry & classify chart type
            chart_type = ChartType.UNKNOWN
            series: List[Dict[str, Any]] = []
            extra_issues: List[Dict[str, Any]] = []

            def _is_legend_swatch_or_frame(r: Mapping[str, Any]) -> bool:
                rb = r["bbox_crop"]
                rw = float(rb[2] - rb[0])
                rh = float(rb[3] - rb[1])
                pw_box = max(1.0, float(px1 - px0))
                ph_box = max(1.0, float(py1 - py0))
                # Exclude full-plot background frames / outer panel boxes
                if rw >= 0.88 * pw_box and rh >= 0.88 * ph_box:
                    return True
                # Exclude any swatch already bound to a detected legend entry (must match both location and scale)
                for lg in legends:
                    sb = lg.get("swatch_box_crop")
                    if sb:
                        sb_area = max(1.0, (sb[2] - sb[0]) * (sb[3] - sb[1]))
                        if _box_intersection_area(rb, sb) >= 0.40 * max(rw * rh, sb_area):
                            return True
                # Exclude small near-square swatches outside plot or adjacent to legend text
                if max(rw, rh) <= 42.0 and 0.45 <= (rw / max(rh, 1.0)) <= 2.2:
                    if rb[1] < py0 + 28.0 or rb[2] > px1 - 5.0 or rb[3] < py0 or rb[0] > px1:
                        return True
                    r_cy = 0.5 * (rb[1] + rb[3])
                    for tk in all_tokens:
                        tb = tk.get("bbox_crop")
                        if not tb:
                            continue
                        tk_cy = 0.5 * (tb[1] + tb[3])
                        if abs(tk_cy - r_cy) <= 14.0 and -2.0 <= float(tb[0]) - float(rb[2]) <= 36.0:
                            if parse_chart_numeric_token(str(tk.get("text") or "")) is None:
                                return True
                return False

            vec_pie = list(vector_prims.get("pie_sectors") or [])
            vec_bars = [
                {
                    "bbox_crop": r["bbox_crop"],
                    "color_rgb": r.get("fill_rgb") or r.get("stroke_rgb"),
                    "source": "vector_pymupdf",
                }
                for r in (vector_prims.get("rects") or [])
                if (r["bbox_crop"][2] - r["bbox_crop"][0]) >= 4.0
                and (r["bbox_crop"][3] - r["bbox_crop"][1]) >= 4.0
                and r.get("fill_rgb") is not None
                and not _is_white_or_near_white(r.get("fill_rgb"))
                and not _is_legend_swatch_or_frame(r)
            ]
            # Vector polylines (strip axis spines, full-width baselines/gridlines, and tiny tick stubs per segment)
            vec_lines: List[Dict[str, Any]] = []
            _ax_y = axes_info.get("x_axis_y")
            _y1_x = axes_info.get("y_axis_x")
            _y2_x = axes_info.get("y2_axis_x")

            def _is_axis_grid_or_tick(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
                adx, ady = abs(b[0] - a[0]), abs(b[1] - a[1])
                if (ady <= 1.8 and adx <= 12.0) or (adx <= 1.8 and ady <= 12.0):
                    return True
                if ady <= 1.8:
                    my = 0.5 * (a[1] + b[1])
                    if (_ax_y is not None and abs(my - float(_ax_y)) <= 3.5) or adx >= (px1 - px0) * 0.80:
                        return True
                if adx <= 1.8:
                    mx = 0.5 * (a[0] + b[0])
                    if (
                        (_y1_x is not None and abs(mx - float(_y1_x)) <= 3.5)
                        or (_y2_x is not None and abs(mx - float(_y2_x)) <= 3.5)
                        or ady >= (py1 - py0) * 0.80
                    ):
                        return True
                return False

            for ln in (vector_prims.get("lines") or []):
                pts = list(ln.get("points") or [ln["p1"], ln["p2"]])
                if len(pts) < 2:
                    continue
                kept_segs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
                for s_i in range(len(pts) - 1):
                    pa = (float(pts[s_i][0]), float(pts[s_i][1]))
                    pb = (float(pts[s_i + 1][0]), float(pts[s_i + 1][1]))
                    if not _is_axis_grid_or_tick(pa, pb):
                        kept_segs.append((pa, pb))
                if not kept_segs:
                    continue
                sub_pts: List[Tuple[float, float]] = [kept_segs[0][0], kept_segs[0][1]]
                for pa, pb in kept_segs[1:]:
                    if math.hypot(pa[0] - sub_pts[-1][0], pa[1] - sub_pts[-1][1]) <= 2.5:
                        sub_pts.append(pb)
                    else:
                        if abs(sub_pts[-1][0] - sub_pts[0][0]) >= 6.0 or len(sub_pts) >= 3:
                            vec_lines.append({
                                "points": sub_pts,
                                "p1": sub_pts[0],
                                "p2": sub_pts[-1],
                                "color_rgb": ln.get("color_rgb"),
                                "linewidth": ln.get("linewidth", 1.0),
                            })
                        sub_pts = [pa, pb]
                if len(sub_pts) >= 2 and (abs(sub_pts[-1][0] - sub_pts[0][0]) >= 6.0 or len(sub_pts) >= 3):
                    vec_lines.append({
                        "points": sub_pts,
                        "p1": sub_pts[0],
                        "p2": sub_pts[-1],
                        "color_rgb": ln.get("color_rgb"),
                        "linewidth": ln.get("linewidth", 1.0),
                    })
            vec_scatter = list(vector_prims.get("scatter_markers") or [])

            raster_bars: List[Dict[str, Any]] = []
            raster_ls: Dict[str, Any] = {"line_series": [], "scatter_points": []}
            raster_pie: Optional[Dict[str, Any]] = None

            if crop_bgr is not None and not vec_pie and not vec_bars and not vec_lines and len(vec_scatter) < 3:
                raster_pie = _detect_raster_pie_opencv(crop_bgr=crop_bgr, axes_info=axes_info)
                if raster_pie is None and axes_info.get("has_axes"):
                    raster_bars = _detect_raster_bars_opencv(
                        crop_bgr=crop_bgr,
                        plot_box=(px0, py0, px1, py1),
                        tokens=all_tokens,
                        is_dark_bg=bool(axes_info.get("is_dark_bg", False)),
                    )
                    if len(raster_bars) < 2:
                        raster_ls = _detect_raster_lines_and_scatter_opencv(
                            crop_bgr=crop_bgr,
                            plot_box=(px0, py0, px1, py1),
                            tokens=all_tokens,
                            is_dark_bg=bool(axes_info.get("is_dark_bg", False)),
                        )

            eff_bars = vec_bars if len(vec_bars) >= 1 else raster_bars
            eff_pie = vec_pie if len(vec_pie) >= 2 else (raster_pie["sectors"] if raster_pie else [])
            eff_lines_vec = vec_lines if (vec_lines and len(eff_bars) < 2) else []
            eff_lines_ras = raster_ls.get("line_series") or []
            eff_scatter = vec_scatter if len(vec_scatter) >= 3 and not eff_lines_vec else (raster_ls.get("scatter_points") or [])

            if len(eff_pie) >= 2:
                chart_type = ChartType.PIE
                series, extra_issues = self._reconstruct_pie(
                    sectors=eff_pie,
                    all_tokens=all_tokens,
                    legends=legends,
                    crop_geom=crop_geom,
                    source_mode=source_mode,
                )
            elif len(eff_bars) >= 1 and axes_info.get("has_axes") and not eff_lines_vec and not eff_lines_ras and (len(eff_bars) >= 2 or not eff_scatter):
                chart_type, series, extra_issues = self._reconstruct_bars(
                    bar_rects=eff_bars,
                    axes_info=axes_info,
                    y1_cal=y1_cal,
                    y2_cal=y2_cal,
                    x_cal=x_cal,
                    partitions=partitions,
                    legends=legends,
                    crop_geom=crop_geom,
                    source_mode=source_mode,
                )
            elif (eff_lines_vec or eff_lines_ras) and axes_info.get("has_axes"):
                chart_type = ChartType.LINE
                series, extra_issues = self._reconstruct_lines(
                    vector_polylines=eff_lines_vec,
                    raster_line_series=eff_lines_ras,
                    axes_info=axes_info,
                    y1_cal=y1_cal,
                    y2_cal=y2_cal,
                    x_cal=x_cal,
                    partitions=partitions,
                    legends=legends,
                    crop_geom=crop_geom,
                    source_mode=source_mode,
                )
            elif len(eff_scatter) >= 2 and axes_info.get("has_axes"):
                chart_type = ChartType.SCATTER
                series = self._reconstruct_scatter(
                    markers=eff_scatter,
                    y1_cal=y1_cal,
                    x_cal=x_cal,
                    legends=legends,
                    crop_geom=crop_geom,
                    source_mode=source_mode,
                    interior_tokens=partitions["plot_interior_tokens"],
                )
            else:
                chart_type = ChartType.UNKNOWN

            # Reclaim low-res charts before trusting any raster pixel estimates
            is_low_res = cw < self.config.low_resolution_min_width_px or ch < self.config.low_resolution_min_height_px
            axes_bundle = {
                "x": x_cal,
                "y_primary": y1_cal,
                "y_secondary": y2_cal if y2_cal.get("present") else None,
                "gridlines_horizontal_count": len(axes_info.get("h_grid_ys") or []),
                "gridlines_vertical_count": len(axes_info.get("v_grid_xs") or []),
                "tick_stubs_detected": {
                    "y1": len(axes_info.get("y1_tick_stubs") or []),
                    "y2": len(axes_info.get("y2_tick_stubs") or []),
                    "x": len(axes_info.get("x_tick_stubs") or []),
                },
            }

            validation = validate_chart_extraction(
                chart_type=chart_type,
                axes=axes_bundle,
                series=series,
                ocr_meta=ocr_meta,
                source_mode=source_mode,
                crop_width_px=cw,
                crop_height_px=ch,
                config=self.config,
                extra_issues=extra_issues,
            )

            # Build factual summary text / markdown explicitly separating exact / estimated / unavailable
            lines_md: List[str] = []
            title_lbl = partitions["chart_title"] or f"Chart ({chart_type.value})"
            lines_md.append(f"Chart Type: {chart_type.value} | Source: {source_mode.value}")
            if partitions["chart_title"]:
                lines_md.append(f"Title: {partitions['chart_title']}")
            if y1_cal.get("is_valid"):
                lines_md.append(
                    f"Y-Axis Origin: {y1_cal['origin_value']} {y1_cal['unit']} "
                    f"(range {y1_cal['axis_min_value']}..{y1_cal['axis_max_value']}, scale={y1_cal['scale_type']})".strip()
                )
            if y2_cal.get("present") and y2_cal.get("is_valid"):
                lines_md.append(
                    f"Y2-Axis Origin: {y2_cal['origin_value']} {y2_cal['unit']} "
                    f"(range {y2_cal['axis_min_value']}..{y2_cal['axis_max_value']}, scale={y2_cal['scale_type']})".strip()
                )
            for s in series:
                lines_md.append(f"Series '{s['name']}' (axis={s['axis']}):")
                for dp in s.get("data_points") or []:
                    lbl_pt = dp.get("category") or dp.get("x") or "point"
                    if dp["value"] is None:
                        lines_md.append(f"  - {lbl_pt}: [unavailable]")
                    else:
                        u_sfx = f" {dp['unit']}".rstrip() if dp.get("unit") else ""
                        lines_md.append(f"  - {lbl_pt}: {dp['value']}{u_sfx} [{dp['precision']}]")
            if validation["review_required"]:
                lines_md.append(f"[Review Required: {', '.join(validation['issue_codes'])}]")

            body_text = "\n".join(lines_md).strip()
            body_text, repaired = apply_text_normalization(
                body_text, repair_bengali=self.repair_bengali, convert_bangla_digits=self.convert_bangla_digits
            )

            # Honest confidence reflects source mode + validation + OCR confidence
            base_c = float(ocr_meta.get("confidence", 0.0) or 0.0) if need_ocr else 0.94
            if layout_score is not None:
                base_c = min(base_c, layout_score) if base_c > 0 else layout_score * 0.8
            if validation["review_required"] or is_low_res:
                base_c = min(base_c, 0.52) if base_c > 0 else 0.25
            conf = round(max(0.0, min(1.0, base_c)), 4)

            source_coords = {
                "page_number": page_number,
                "page_width": crop_geom["page_width"],
                "page_height": crop_geom["page_height"],
                "source_rotation": crop_geom["source_rotation"],
                "display_bbox_xywh": crop_geom["chart_display_bbox"],
                "display_rect_xyxy": crop_geom["chart_display_rect"],
                "pixel_rect_xyxy": crop_geom["chart_pixel_box"],
                "normalized_box": crop_geom["chart_normalized_box"],
                "crop_rect_px": crop_geom["crop_rect_px"],
            }

            chart_payload = {
                "chart_type": chart_type.value,
                "source_mode": source_mode.value,
                "title": partitions["chart_title"],
                "axes": axes_bundle,
                "legends": legends,
                "categories": [c["text"] for c in (partitions["y_cat_labels"] if chart_type == ChartType.HORIZONTAL_BAR else partitions["x_cat_labels"])],
                "series": series,
                "ocr_text": ocr_meta.get("full_text", ""),
                "raw_tokens_count": len(all_tokens),
            }

            word_boxes_out: List[Dict[str, Any]] = []
            for tk in all_tokens:
                tc = crop_box_to_page_coords(tk["bbox_crop"], crop_geom)
                word_boxes_out.append({
                    "word": tk["text"],
                    "confidence": float(tk.get("confidence", 0.9) or 0.9),
                    "x": round(tc["bbox"][0]),
                    "y": round(tc["bbox"][1]),
                    "w": max(0, round(tc["bbox"][2])),
                    "h": max(0, round(tc["bbox"][3])),
                    "normalized_box": tc["normalized_box"],
                })

            return cast(
                Dict[str, Any],
                build_visual_region_provenance(
                region_id=eff_region_id,
                region_type=VisualRegionType.CHART.value,
                extraction_kind=VisualExtractionKind.CHART_SERIES.value,
                page_number=page_number,
                bbox=crop_geom["chart_display_bbox"],
                normalized_box=crop_geom["chart_normalized_box"],
                text=body_text,
                markdown=format_visual_region_markdown(
                    page_number,
                    eff_region_id,
                    f"Chart ({title_lbl})",
                    body_text,
                ),
                confidence=conf,
                engine=self.provider_name,
                engine_version=self.engine_version,
                is_inference=False,
                is_repaired=repaired,
                source_asset_name=crop_ref["source_asset_name"],
                word_boxes=cast(Any, word_boxes_out),
                metadata={
                    "review_required": validation["review_required"],
                    "needs_review": validation["needs_review"],
                    "chart": chart_payload,
                    "chart_validation": validation,
                    "chart_crop_reference": crop_ref,
                    "source_coordinates": source_coords,
                    "ocr_metadata": {
                        "ocr_triggered": ocr_meta.get("ocr_triggered", False),
                        "ocr_available": ocr_meta.get("ocr_available", True),
                        "engine": ocr_meta.get("engine", "tesseract"),
                        "engine_version": ocr_meta.get("engine_version", ""),
                        "language": ocr_meta.get("language", ""),
                        "status": ocr_meta.get("status", ""),
                        "confidence": ocr_meta.get("confidence", 0.0),
                        "warnings": ocr_meta.get("warnings", []),
                    },
                    "layout_label": layout_label,
                    "layout_score": layout_score,
                },
                )
            )
        finally:
            crop_bgr = None
            try:
                crop_img.close()
            except Exception:
                pass


# Ergonomic alias consistent with other pipeline extractors
ChartExtractor = PyMuPDFOpenCVChartExtractor

__all__ = [
    "HAS_NUMPY",
    "HAS_OPENCV",
    "HAS_PYMUPDF",
    "OPENCV_VERSION",
    "ChartExtractor",
    "ChartExtractorConfig",
    "ChartSourceMode",
    "ChartType",
    "PyMuPDFOpenCVChartExtractor",
    "ValuePrecisionStatus",
    "build_chart_crop_reference",
    "calibrate_numeric_axis",
    "crop_box_to_page_coords",
    "detect_chart_candidates_in_pdf_page",
    "detect_chart_regions_opencv",
    "extract_chart_text_with_tesseract",
    "extract_native_pdf_chart_primitives",
    "is_likely_chart_raster_opencv",
    "parse_chart_numeric_token",
    "resolve_chart_crop_geometry",
    "validate_chart_extraction",
]
