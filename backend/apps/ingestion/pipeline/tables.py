"""
LORE Enterprise — Table Extraction & Structure Recognition (PP-DocLayout-S + SLANet_plus)
========================================================================================

Integrates ``PP-DocLayout-S`` (table-region detection) with ``SLANet_plus``
(table structure recognition via ``paddleocr.TableStructureRecognition``) on CPU,
combining PyMuPDF native PDF text reuse and ``TesseractOCRProvider`` cell OCR.

Verified Artifact & Runtime Specification:
- Model identifier: ``SLANet_plus``
- Architecture: ``PP-LCNet`` backbone + ``CSP-PAN`` feature fusion + ``SLAHead``
- Official artifacts: Hugging Face ``PaddlePaddle/SLANet_plus`` and PaddleX
  inference archive ``SLANet_plus_infer.tar``
  (contains ``inference.json``, ``inference.pdiparams``, ``inference.yml``)
- Package requirements: ``paddleocr>=3.0.0`` + ``paddlepaddle>=3.0.0`` (CPU build)
- License: Apache License 2.0 (``Apache-2.0``)
- Runtime compatibility: CPU execution (``device="cpu"``, configurable ``cpu_threads``
  and ``enable_mkldnn``), Python 3.9-3.13 with prebuilt wheels (aligns with container
  ``python:3.12-slim``); degrades gracefully when unavailable or on error.

Epistemic & Governance Guarantees:
- Never shifts a value into another cell simply to complete a grid.
- Never invents a header, value, unit, or cross-table/cross-page relationship.
- Distinguishes ``populated``, ``empty``, ``unreadable``, and ``missing`` cells.
- Validates reconstructed table structure and flags uncertain tables with
  ``needs_review=True`` for human review.
- Never modifies Settlement Layer stages (S1-S6) or publishes directly to Knowledge Store.
"""

from __future__ import annotations

import inspect
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from html.parser import HTMLParser
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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
    TesseractOCRProvider,
)
from .visual import (
    apply_text_normalization,
    format_visual_region_markdown,
)

logger = logging.getLogger(__name__)

# Optional NumPy ndarray bridge for BGR PaddleX / OpenCV model input
try:
    import numpy as np  # type: ignore

    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore
    HAS_NUMPY = False

# Optional PaddlePaddle / PaddleOCR TableStructureRecognition runtime detection
try:
    import paddle  # type: ignore

    HAS_PADDLEPADDLE = True
    PADDLEPADDLE_VERSION = str(getattr(paddle, "__version__", "unknown"))
except ImportError:
    paddle = None  # type: ignore
    HAS_PADDLEPADDLE = False
    PADDLEPADDLE_VERSION = "unavailable"

try:
    from paddleocr import TableStructureRecognition as _PaddleOCRTableStructureRecognition  # type: ignore
    import paddleocr as _paddleocr_pkg  # type: ignore

    HAS_PADDLEOCR_TABLE_STRUCTURE = True
    PADDLEOCR_VERSION = str(getattr(_paddleocr_pkg, "__version__", "unknown"))
except ImportError:
    _PaddleOCRTableStructureRecognition = None  # type: ignore
    HAS_PADDLEOCR_TABLE_STRUCTURE = False
    PADDLEOCR_VERSION = "unavailable"


# ==============================================================================
# VERIFIED SLANET_PLUS ARTIFACT METADATA
# ==============================================================================
SLANET_PLUS_MODEL_NAME = "SLANet_plus"
SLANET_PLUS_ARCHITECTURE = "PP-LCNet + CSP-PAN + SLAHead"
SLANET_PLUS_LICENSE = "Apache-2.0"
SLANET_PLUS_HF_REPO = "PaddlePaddle/SLANet_plus"
SLANET_PLUS_INFERENCE_ARCHIVE = "SLANet_plus_infer.tar"
SLANET_PLUS_BCEBOS_URL = (
    "https://paddle-model-ecology.bj.bcebos.com/"
    "paddlex/official_inference_model/paddle3.0.0/SLANet_plus_infer.tar"
)
SLANET_PLUS_MIN_PADDLEOCR_VERSION = "3.0.0"
SLANET_PLUS_MIN_PADDLEPADDLE_VERSION = "3.0.0"
SLANET_PLUS_SUPPORTED_PYTHON = ">=3.9,<3.14"

SLANET_PLUS_ARTIFACT_METADATA: Dict[str, Any] = {
    "model_name": SLANET_PLUS_MODEL_NAME,
    "architecture": SLANET_PLUS_ARCHITECTURE,
    "license": SLANET_PLUS_LICENSE,
    "huggingface_repo": SLANET_PLUS_HF_REPO,
    "inference_archive": SLANET_PLUS_INFERENCE_ARCHIVE,
    "bcebos_url": SLANET_PLUS_BCEBOS_URL,
    "archive_files": ("inference.json", "inference.pdiparams", "inference.yml"),
    "min_paddleocr_version": SLANET_PLUS_MIN_PADDLEOCR_VERSION,
    "min_paddlepaddle_version": SLANET_PLUS_MIN_PADDLEPADDLE_VERSION,
    "supported_python": SLANET_PLUS_SUPPORTED_PYTHON,
    "supports_wireless_borderless_tables": True,
}


# ==============================================================================
# CANONICAL CELL STATUS & CONFIG
# ==============================================================================
class CellStatus(str, Enum):
    """Explicit epistemic status of every reconstructed table cell."""

    POPULATED = "populated"
    EMPTY = "empty"
    UNREADABLE = "unreadable"
    MISSING = "missing"


class CellSource(str, Enum):
    """Text provenance source inside an individual table cell."""

    NATIVE_PDF = "native_pdf"
    OCR_TESSERACT = "ocr_tesseract"
    VECTOR_FALLBACK = "vector_fallback"
    NONE = "none"


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
class SLANetPlusConfig:
    """CPU execution and validation configuration for SLANet_plus."""

    model_name: str = SLANET_PLUS_MODEL_NAME
    model_dir: Optional[str] = None
    device: str = "cpu"
    cpu_threads: int = 4
    enable_mkldnn: bool = True
    min_structure_score: float = 0.60
    min_cell_ocr_confidence: float = 0.45
    unreadable_ocr_confidence_cutoff: float = 0.35
    reuse_worker_model: bool = True
    local_files_only: bool = False
    crop_padding_px: int = 6

    def __post_init__(self) -> None:
        if str(self.device or "cpu").strip().lower() != "cpu":
            logger.warning(
                "SLANetPlusTableExtractor is CPU-configured; overriding device=%r to 'cpu'.",
                self.device,
            )
        self.device = "cpu"
        try:
            threads_int = int(self.cpu_threads)
        except (TypeError, ValueError):
            threads_int = 4
        self.cpu_threads = max(1, threads_int)
        self.min_structure_score = max(0.0, min(1.0, float(self.min_structure_score)))
        self.min_cell_ocr_confidence = max(0.0, min(1.0, float(self.min_cell_ocr_confidence)))
        self.unreadable_ocr_confidence_cutoff = max(
            0.0, min(self.min_cell_ocr_confidence, float(self.unreadable_ocr_confidence_cutoff))
        )
        self.crop_padding_px = max(0, int(self.crop_padding_px))
        if self.model_dir is not None:
            cleaned = str(self.model_dir).strip()
            self.model_dir = cleaned or None

    @classmethod
    def from_settings_or_env(cls) -> "SLANetPlusConfig":
        return cls(
            model_name=str(_read_setting_or_env("SLANET_PLUS_MODEL_NAME", SLANET_PLUS_MODEL_NAME)),
            model_dir=_read_setting_or_env("SLANET_PLUS_MODEL_DIR", None),
            device="cpu",
            cpu_threads=int(_read_setting_or_env("SLANET_PLUS_CPU_THREADS", 4)),
            enable_mkldnn=_coerce_bool(_read_setting_or_env("SLANET_PLUS_ENABLE_MKLDNN", True), True),
            min_structure_score=float(_read_setting_or_env("SLANET_PLUS_MIN_STRUCTURE_SCORE", 0.60)),
            min_cell_ocr_confidence=float(_read_setting_or_env("SLANET_PLUS_MIN_CELL_OCR_CONFIDENCE", 0.45)),
            local_files_only=_coerce_bool(_read_setting_or_env("SLANET_PLUS_LOCAL_FILES_ONLY", False), False),
        )

    def cache_key(self) -> Tuple[Any, ...]:
        return (
            self.model_name,
            self.model_dir or "",
            self.device,
            self.cpu_threads,
            self.enable_mkldnn,
        )


class WorkerTableStructureModelCache:
    """Thread-safe per-worker cache reusing loaded ``TableStructureRecognition`` instances."""

    _lock = threading.RLock()
    _models: Dict[Tuple[Any, ...], Any] = {}
    _load_count: int = 0
    _reuse_count: int = 0

    @classmethod
    def get_or_load(
        cls,
        config: SLANetPlusConfig,
        loader_fn: Callable[[SLANetPlusConfig], Any],
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
# PURE COORDINATE & CROP GEOMETRY TRANSFORM HELPERS
# ==============================================================================
def _rotate_box_cw(
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
    src_w: float,
    src_h: float,
    rotation_cw: int,
) -> Tuple[Tuple[float, float, float, float], Tuple[float, float]]:
    deg = int(rotation_cw or 0) % 360
    x0, x1 = min(float(xmin), float(xmax)), max(float(xmin), float(xmax))
    y0, y1 = min(float(ymin), float(ymax)), max(float(ymin), float(ymax))
    w = max(float(src_w or 1.0), 1.0)
    h = max(float(src_h or 1.0), 1.0)

    if deg == 90:
        box, dims = (h - y1, x0, h - y0, x1), (h, w)
    elif deg == 180:
        box, dims = (w - x1, h - y1, w - x0, h - y0), (w, h)
    elif deg == 270:
        box, dims = (y0, w - x1, y1, w - x0), (h, w)
    else:
        box, dims = (x0, y0, x1, y1), (w, h)

    cx0 = max(0.0, min(dims[0], box[0]))
    cy0 = max(0.0, min(dims[1], box[1]))
    cx1 = max(0.0, min(dims[0], box[2]))
    cy1 = max(0.0, min(dims[1], box[3]))
    return (min(cx0, cx1), min(cy0, cy1), max(cx0, cx1), max(cy0, cy1)), dims


def resolve_table_crop_geometry(
    *,
    page_image: Image.Image,
    table_box: Sequence[float],
    bbox_format: str = "normalized",
    page_width: Optional[float] = None,
    page_height: Optional[float] = None,
    source_rotation: int = 0,
    coords_in_unrotated_space: bool = False,
    padding_px: int = 6,
    min_model_side: int = 32,
) -> Tuple[Optional[Image.Image], Dict[str, Any]]:
    """
    Crops a table region accurately from ``page_image`` and records an exact affine
    inverse mapping from cropped/padded coordinates back to original page display
    pixels and canonical ``[ymin, xmin, ymax, xmax]`` (0..1000) coordinates.
    """
    img_w, img_h = page_image.size
    eff_pw = float(page_width or img_w)
    eff_ph = float(page_height or img_h)
    if img_w <= 0 or img_h <= 0 or len(table_box) < 4:
        return None, {}

    fmt = str(bbox_format or "normalized").lower().strip()
    if fmt == "normalized":
        ymin_n, xmin_n, ymax_n, xmax_n = [float(v) for v in table_box[:4]]
        raw_x0 = (xmin_n / 1000.0) * img_w
        raw_y0 = (ymin_n / 1000.0) * img_h
        raw_x1 = (xmax_n / 1000.0) * img_w
        raw_y1 = (ymax_n / 1000.0) * img_h
        raw_space_w, raw_space_h = float(img_w), float(img_h)
    elif fmt == "xywh":
        bx, by, bw, bh = [float(v) for v in table_box[:4]]
        sx = img_w / max(eff_pw, 1.0)
        sy = img_h / max(eff_ph, 1.0)
        raw_x0, raw_y0 = bx * sx, by * sy
        raw_x1, raw_y1 = (bx + max(0.0, bw)) * sx, (by + max(0.0, bh)) * sy
        raw_space_w, raw_space_h = float(img_w), float(img_h)
    elif fmt == "display":
        dx0, dy0, dx1, dy1 = [float(v) for v in table_box[:4]]
        sx = img_w / max(eff_pw, 1.0)
        sy = img_h / max(eff_ph, 1.0)
        raw_x0, raw_y0, raw_x1, raw_y1 = dx0 * sx, dy0 * sy, dx1 * sx, dy1 * sy
        raw_space_w, raw_space_h = float(img_w), float(img_h)
    else:
        # "pixel" [px0, py0, px1, py1]
        raw_x0, raw_y0, raw_x1, raw_y1 = [float(v) for v in table_box[:4]]
        if coords_in_unrotated_space and (int(source_rotation or 0) % 360) in (90, 270):
            raw_space_w, raw_space_h = float(img_h), float(img_w)
        else:
            raw_space_w, raw_space_h = float(img_w), float(img_h)

    if coords_in_unrotated_space and (int(source_rotation or 0) % 360) in (90, 180, 270):
        (px0, py0, px1, py1), _ = _rotate_box_cw(
            raw_x0, raw_y0, raw_x1, raw_y1, raw_space_w, raw_space_h, int(source_rotation)
        )
    else:
        px0, px1 = min(raw_x0, raw_x1), max(raw_x0, raw_x1)
        py0, py1 = min(raw_y0, raw_y1), max(raw_y0, raw_y1)

    px0 = max(0.0, min(float(img_w), px0))
    py0 = max(0.0, min(float(img_h), py0))
    px1 = max(0.0, min(float(img_w), px1))
    py1 = max(0.0, min(float(img_h), py1))
    if (px1 - px0) < 4.0 or (py1 - py0) < 4.0:
        return None, {}

    pad = max(0, int(padding_px))
    cl = max(0, int(px0) - pad)
    ct = max(0, int(py0) - pad)
    cr = min(img_w, int(round(px1)) + pad)
    cb = min(img_h, int(round(py1)) + pad)
    crop_w = cr - cl
    crop_h = cb - ct
    if crop_w < 4 or crop_h < 4:
        return None, {}

    crop = page_image.crop((cl, ct, cr, cb))
    if crop.mode != "RGB":
        rgb_crop = crop.convert("RGB")
        crop.close()
        crop = rgb_crop

    pad_offset_x = 0
    pad_offset_y = 0
    if crop_w < min_model_side or crop_h < min_model_side:
        canvas_w = max(crop_w, min_model_side)
        canvas_h = max(crop_h, min_model_side)
        pad_offset_x = (canvas_w - crop_w) // 2
        pad_offset_y = (canvas_h - crop_h) // 2
        padded = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
        padded.paste(crop, (pad_offset_x, pad_offset_y))
        crop.close()
        crop = padded

    scale_x = eff_pw / max(float(img_w), 1.0)
    scale_y = eff_ph / max(float(img_h), 1.0)

    tbl_disp_x0 = px0 * scale_x
    tbl_disp_y0 = py0 * scale_y
    tbl_disp_x1 = px1 * scale_x
    tbl_disp_y1 = py1 * scale_y

    table_norm_box = validate_normalized_box(
        rect_to_normalized_box(
            tbl_disp_x0, tbl_disp_y0, tbl_disp_x1, tbl_disp_y1, canvas_width=eff_pw, canvas_height=eff_ph
        )
    )

    geom = {
        "image_width": float(img_w),
        "image_height": float(img_h),
        "page_width": eff_pw,
        "page_height": eff_ph,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "table_pixel_box": [round(px0, 2), round(py0, 2), round(px1, 2), round(py1, 2)],
        "table_display_bbox": [
            round(tbl_disp_x0, 2),
            round(tbl_disp_y0, 2),
            round(max(0.0, tbl_disp_x1 - tbl_disp_x0), 2),
            round(max(0.0, tbl_disp_y1 - tbl_disp_y0), 2),
        ],
        "table_normalized_box": table_norm_box,
        "crop_rect": (cl, ct, cr, cb),
        "crop_left": float(cl),
        "crop_top": float(ct),
        "unpadded_crop_width": float(crop_w),
        "unpadded_crop_height": float(crop_h),
        "pad_offset_x": float(pad_offset_x),
        "pad_offset_y": float(pad_offset_y),
        "model_input_width": float(crop.width),
        "model_input_height": float(crop.height),
        "source_rotation": int(source_rotation or 0) % 360,
    }
    return crop, geom


def crop_box_to_page_coords(
    cell_crop_box: Sequence[float],
    crop_geom: Mapping[str, Any],
) -> Dict[str, Any]:
    """
    Transforms a crop-local ``[cx0, cy0, cx1, cy1]`` box into:
    - clipped local unpadded coordinates inside ``crop_img``
    - upright page display ``[x, y, w, h]``
    - canonical ``[ymin, xmin, ymax, xmax]`` (0..1000) normalized coordinates.
    """
    cx0, cy0, cx1, cy1 = [float(v) for v in cell_crop_box[:4]]
    x0, x1 = min(cx0, cx1), max(cx0, cx1)
    y0, y1 = min(cy0, cy1), max(cy0, cy1)

    # Remove optional padding canvas offset before mapping back to full page image
    pad_x = float(crop_geom.get("pad_offset_x", 0.0) or 0.0)
    pad_y = float(crop_geom.get("pad_offset_y", 0.0) or 0.0)
    ucw = max(1.0, float(crop_geom.get("unpadded_crop_width", 1.0) or 1.0))
    uch = max(1.0, float(crop_geom.get("unpadded_crop_height", 1.0) or 1.0))

    ux0 = max(0.0, min(ucw, x0 - pad_x))
    uy0 = max(0.0, min(uch, y0 - pad_y))
    ux1 = max(0.0, min(ucw, x1 - pad_x))
    uy1 = max(0.0, min(uch, y1 - pad_y))

    crop_left = float(crop_geom.get("crop_left", 0.0) or 0.0)
    crop_top = float(crop_geom.get("crop_top", 0.0) or 0.0)
    scale_x = float(crop_geom.get("scale_x", 1.0) or 1.0)
    scale_y = float(crop_geom.get("scale_y", 1.0) or 1.0)
    eff_pw = float(crop_geom.get("page_width", 1.0) or 1.0)
    eff_ph = float(crop_geom.get("page_height", 1.0) or 1.0)

    page_px0 = crop_left + ux0
    page_py0 = crop_top + uy0
    page_px1 = crop_left + ux1
    page_py1 = crop_top + uy1

    disp_x0 = page_px0 * scale_x
    disp_y0 = page_py0 * scale_y
    disp_x1 = page_px1 * scale_x
    disp_y1 = page_py1 * scale_y

    norm_box = validate_normalized_box(
        rect_to_normalized_box(
            disp_x0, disp_y0, disp_x1, disp_y1, canvas_width=eff_pw, canvas_height=eff_ph
        )
    )
    return {
        "model_crop_box": [
            round(ux0 + pad_x, 2),
            round(uy0 + pad_y, 2),
            round(ux1 + pad_x, 2),
            round(uy1 + pad_y, 2),
        ],
        "page_pixel_box": [round(page_px0, 2), round(page_py0, 2), round(page_px1, 2), round(page_py1, 2)],
        "bbox": [
            round(disp_x0, 2),
            round(disp_y0, 2),
            round(max(0.0, disp_x1 - disp_x0), 2),
            round(max(0.0, disp_y1 - disp_y0), 2),
        ],
        "normalized_box": norm_box,
        "is_clipped_empty": (ux1 - ux0) < 2.0 or (uy1 - uy0) < 2.0,
    }


def _normalize_raw_cell_box(raw_box: Any) -> Optional[Tuple[float, float, float, float]]:
    """
    Normalizes PaddleOCR ``SLANet_plus`` cell boxes from:
    - 4-float rectangle ``[x0, y0, x1, y1]``
    - 8-float quad ``[x1, y1, x2, y2, x3, y3, x4, y4]``
    - 4x2 polygon ``[[x1, y1], [x2, y2], [x3, y3], [x4, y4]]``
    Returns None if degenerate or zero-area.
    """
    if raw_box is None:
        return None
    if hasattr(raw_box, "tolist"):
        raw_box = raw_box.tolist()
    if not isinstance(raw_box, (list, tuple)) or not raw_box:
        return None

    try:
        if isinstance(raw_box[0], (list, tuple)):
            pts = [(float(p[0]), float(p[1])) for p in raw_box if isinstance(p, (list, tuple)) and len(p) >= 2]
            if not pts:
                return None
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        elif len(raw_box) >= 8:
            vals = [float(v) for v in raw_box[:8]]
            xs = vals[0::2]
            ys = vals[1::2]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        elif len(raw_box) >= 4:
            x0, y0, x1, y1 = float(raw_box[0]), float(raw_box[1]), float(raw_box[2]), float(raw_box[3])
            x0, x1 = min(x0, x1), max(x0, x1)
            y0, y1 = min(y0, y1), max(y0, y1)
        else:
            return None
    except (TypeError, ValueError):
        return None

    if (x1 - x0) < 2.0 or (y1 - y0) < 2.0:
        return None
    return (x0, y0, x1, y1)


# ==============================================================================
# SLANET_PLUS HTML STRUCTURE PARSER (OCCUPANCY GRID WITH ZERO SHIFTING)
# ==============================================================================
_ATTR_SPAN_RE = re.compile(r'\b(rowspan|colspan)\s*=\s*["\']?(\d+)["\']?', re.IGNORECASE)


class _HTMLTableStructureTokenizer(HTMLParser):
    """Fallback HTML parser turning raw HTML table strings into structural tokens."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        if t in ("thead", "tbody", "tr", "td", "th", "table"):
            if attrs:
                attr_str = " ".join(f'{k}="{v}"' for k, v in attrs if v is not None)
                self.tokens.append(f"<{t} {attr_str}>".strip())
            else:
                self.tokens.append(f"<{t}>")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("thead", "tbody", "tr", "td", "th", "table"):
            self.tokens.append(f"</{t}>")


def _extract_structure_tokens(res_dict: Mapping[str, Any]) -> List[str]:
    raw_struct = res_dict.get("structure")
    if isinstance(raw_struct, Mapping) and "tokens" in raw_struct:
        raw_struct = raw_struct.get("tokens")
    if isinstance(raw_struct, (list, tuple)) and raw_struct:
        return [str(tok) for tok in raw_struct]

    raw_html = res_dict.get("html") or res_dict.get("html_code")
    if isinstance(raw_html, Mapping):
        nested = (raw_html.get("structure") or {}).get("tokens")
        if isinstance(nested, (list, tuple)) and nested:
            return [str(tok) for tok in nested]
    if isinstance(raw_html, str) and raw_html.strip():
        parser = _HTMLTableStructureTokenizer()
        parser.feed(raw_html)
        parser.close()
        return parser.tokens

    return []


def _extract_structure_payload(raw_output: Any) -> Dict[str, Any]:
    """Extracts the primary dict payload from PaddleOCR 3.x TableStructureRecognition output."""
    candidate = raw_output
    if isinstance(candidate, (list, tuple)):
        if not candidate:
            return {}
        candidate = candidate[0]

    json_attr = getattr(candidate, "json", None)
    if isinstance(json_attr, Mapping):
        inner = json_attr.get("res", json_attr)
        if isinstance(inner, Mapping):
            return dict(inner)

    if isinstance(candidate, Mapping):
        inner = candidate.get("res", candidate)
        if isinstance(inner, Mapping):
            return dict(inner)

    extracted: Dict[str, Any] = {}
    for key in ("structure", "bbox", "cell_box", "cell_bbox", "structure_score", "html", "html_code"):
        try:
            val = candidate[key]
            extracted[key] = val
        except Exception:
            if hasattr(candidate, key):
                extracted[key] = getattr(candidate, key)
    return extracted


def _parse_cell_open_tag(tag_buffer: str) -> Tuple[bool, int, int, List[str]]:
    low = tag_buffer.strip().lower()
    is_th = low.startswith("<th")
    rowspan = 1
    colspan = 1
    issues: List[str] = []
    for attr_name, raw_val in _ATTR_SPAN_RE.findall(low):
        try:
            parsed_val = int(raw_val)
        except ValueError:
            parsed_val = 1
        if parsed_val < 1:
            issues.append(f"invalid_{attr_name}_nonpositive")
            parsed_val = 1
        if attr_name.lower() == "rowspan":
            rowspan = parsed_val
        elif attr_name.lower() == "colspan":
            colspan = parsed_val
    return is_th, rowspan, colspan, issues


def parse_slanet_structure_and_cells(raw_result: Any) -> Dict[str, Any]:
    """
    Decodes ``SLANet_plus`` HTML structural tokens + bounding boxes into a
    2D occupancy-mapped cell descriptor list WITHOUT ever shifting cells into
    occupied span coordinates or fabricating missing slots.
    """
    payload = _extract_structure_payload(raw_result)
    tokens = _extract_structure_tokens(payload)

    raw_boxes_obj = payload.get("bbox")
    if raw_boxes_obj is None:
        raw_boxes_obj = payload.get("cell_box")
    if raw_boxes_obj is None:
        raw_boxes_obj = payload.get("cell_bbox")
    if hasattr(raw_boxes_obj, "tolist"):
        raw_boxes_obj = raw_boxes_obj.tolist()
    raw_boxes: List[Any] = list(raw_boxes_obj) if isinstance(raw_boxes_obj, (list, tuple)) else []

    raw_score = payload.get("structure_score")
    try:
        structure_score = max(0.0, min(1.0, float(raw_score))) if raw_score is not None else 0.0
    except (TypeError, ValueError):
        structure_score = 0.0

    # Walk tokens with explicit tag buffering to support split PaddleX tokens like
    # ['<td', ' rowspan="2"', '>', '</td>'] AND merged ['<td></td>'] tokens.
    cells: List[Dict[str, Any]] = []
    occupied: Dict[Tuple[int, int], int] = {}
    span_collisions: List[Dict[str, int]] = []
    structural_issues: List[str] = []

    current_row = -1
    col_cursor = 0
    in_thead = False
    pending_open_tag: Optional[str] = None
    in_open_cell = False
    max_row_reached = -1
    max_col_reached = -1
    row_occupied_widths: Dict[int, int] = {}

    def _register_cell(is_th_tag: bool, rowspan: int, colspan: int, tag_issues: List[str]) -> None:
        nonlocal col_cursor, max_row_reached, max_col_reached, current_row
        if current_row < 0:
            current_row = 0
            col_cursor = 0
        while (current_row, col_cursor) in occupied:
            col_cursor += 1

        cell_idx = len(cells)
        cell_r = current_row
        cell_c = col_cursor

        for dr in range(rowspan):
            for dc in range(colspan):
                coord = (cell_r + dr, cell_c + dc)
                if coord in occupied:
                    span_collisions.append({"row": coord[0], "col": coord[1], "cell_index": cell_idx})
                else:
                    occupied[coord] = cell_idx
                max_row_reached = max(max_row_reached, coord[0])
                max_col_reached = max(max_col_reached, coord[1])
                row_occupied_widths[coord[0]] = max(row_occupied_widths.get(coord[0], 0), coord[1] + 1)

        raw_box_entry = raw_boxes[cell_idx] if cell_idx < len(raw_boxes) else None
        norm_raw_box = _normalize_raw_cell_box(raw_box_entry)

        cells.append({
            "cell_index": cell_idx,
            "row": cell_r,
            "col": cell_c,
            "rowspan": rowspan,
            "colspan": colspan,
            "is_header": bool(in_thead or is_th_tag),
            "raw_crop_box": list(norm_raw_box) if norm_raw_box is not None else None,
            "has_valid_box": norm_raw_box is not None,
            "missing_box_reason": (
                None
                if norm_raw_box is not None
                else ("missing_bbox_entry" if cell_idx >= len(raw_boxes) else "invalid_or_degenerate_bbox")
            ),
            "tag_issues": list(tag_issues),
        })
        col_cursor += colspan

    for tok in tokens:
        s = str(tok)
        low = s.strip().lower()
        if not low:
            continue

        if pending_open_tag is not None:
            pending_open_tag += s
            if ">" in s:
                is_th_tag, rs, cs, t_issues = _parse_cell_open_tag(pending_open_tag)
                structural_issues.extend(t_issues)
                _register_cell(is_th_tag, rs, cs, t_issues)
                if not low.endswith("</td>") and not low.endswith("</th>"):
                    in_open_cell = True
                pending_open_tag = None
            continue

        if low in ("<thead>", "<thead"):
            in_thead = True
        elif low == "</thead>":
            in_thead = False
        elif low in ("<tr>", "<tr"):
            current_row += 1
            col_cursor = 0
            row_occupied_widths.setdefault(current_row, 0)
        elif low == "</tr>":
            # Ensure even completely occupied rows are accounted for in row count
            row_occupied_widths.setdefault(max(0, current_row), 0)
        elif low in ("<td></td>", "<th></th>"):
            _register_cell(low.startswith("<th"), 1, 1, [])
            in_open_cell = False
        elif low in ("</td>", "</th>"):
            in_open_cell = False
        elif low.startswith("<td") or low.startswith("<th"):
            if ">" in s:
                # Handle combined '<td></td>' variations with spaces/attributes if any
                if low.endswith("</td>") or low.endswith("</th>"):
                    is_th_tag, rs, cs, t_issues = _parse_cell_open_tag(s)
                    structural_issues.extend(t_issues)
                    _register_cell(is_th_tag, rs, cs, t_issues)
                    in_open_cell = False
                else:
                    is_th_tag, rs, cs, t_issues = _parse_cell_open_tag(s)
                    structural_issues.extend(t_issues)
                    _register_cell(is_th_tag, rs, cs, t_issues)
                    in_open_cell = True
            else:
                pending_open_tag = s
        elif not in_open_cell:
            # Non-cell structural token
            continue

    num_rows = (max_row_reached + 1) if max_row_reached >= 0 else 0
    num_cols = (max_col_reached + 1) if max_col_reached >= 0 else 0

    # Include any trailing row widths that had existing rowspans filling full width
    distinct_widths = {w for r, w in row_occupied_widths.items() if r < num_rows and w > 0}
    ragged_rows = [
        {"row": r, "occupied_cols": row_occupied_widths.get(r, 0), "expected_cols": num_cols}
        for r in range(num_rows)
        if 0 < row_occupied_widths.get(r, 0) < num_cols
    ]

    return {
        "structure_score": structure_score,
        "structure_tokens": tokens,
        "cells": cells,
        "occupied": occupied,
        "num_rows": num_rows,
        "num_cols": num_cols,
        "raw_box_count": len(raw_boxes),
        "extra_box_count": max(0, len(raw_boxes) - len(cells)),
        "span_collisions": span_collisions,
        "ragged_rows": ragged_rows,
        "distinct_row_widths": sorted(distinct_widths),
        "structural_issues": structural_issues,
    }


# ==============================================================================
# CELL TEXT EXTRACTION (NATIVE REUSE + TESSERACT OCR + BLANK/UNREADABLE CHECK)
# ==============================================================================
def _box_intersection_area(a: Sequence[float], b: Sequence[float]) -> float:
    ax0, ay0, ax1, ay1 = float(a[0]), float(a[1]), float(a[2]), float(a[3])
    bx0, by0, bx1, by1 = float(b[0]), float(b[1]), float(b[2]), float(b[3])
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    return max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)


def _norm_box_to_xyxy(nb: Sequence[int]) -> Tuple[int, int, int, int]:
    return (int(nb[1]), int(nb[0]), int(nb[3]), int(nb[2]))


def _reconstruct_multiline_text(
    words: Sequence[Mapping[str, Any]],
    *,
    repair_bengali: bool = True,
    convert_bangla_digits: bool = False,
) -> Tuple[str, List[str], bool]:
    """
    Groups words cleanly into visual lines by vertical center proximity without
    collapsing genuine line breaks or altering numeric/unit formatting.
    """
    valid = [w for w in words if str(w.get("word") or "").strip()]
    if not valid:
        return "", [], False

    def _coord(wb: Mapping[str, Any]) -> Tuple[float, float, float, float]:
        nb = wb.get("normalized_box")
        if isinstance(nb, (list, tuple)) and len(nb) >= 4:
            return (float(nb[1]), float(nb[0]), float(nb[3]), float(nb[2]))
        x = float(wb.get("x", 0.0) or 0.0)
        y = float(wb.get("y", 0.0) or 0.0)
        w = max(1.0, float(wb.get("w", 1.0) or 1.0))
        h = max(1.0, float(wb.get("h", 1.0) or 1.0))
        return (x, y, x + w, y + h)

    entries: List[Tuple[Tuple[float, float, float, float], Mapping[str, Any]]] = [(_coord(w), w) for w in valid]
    heights = sorted(max(1.0, c[3] - c[1]) for c, _ in entries)
    median_h = heights[len(heights) // 2]
    line_tol = max(3.5, median_h * 0.58)

    entries.sort(key=lambda item: ((item[0][1] + item[0][3]) / 2.0, item[0][0]))
    lines_buckets: List[Tuple[float, List[Tuple[float, str]]]] = []

    for c, wb in entries:
        cy = (c[1] + c[3]) / 2.0
        txt = str(wb.get("word") or "").strip()
        if not lines_buckets or abs(cy - lines_buckets[-1][0]) > line_tol:
            lines_buckets.append((cy, [(c[0], txt)]))
        else:
            prev_cy, items = lines_buckets[-1]
            items.append((c[0], txt))
            new_cy = ((prev_cy * (len(items) - 1)) + cy) / len(items)
            lines_buckets[-1] = (new_cy, items)

    lines_out: List[str] = []
    any_repaired = False
    for _, items in lines_buckets:
        items.sort(key=lambda pair: pair[0])
        line_str = " ".join(tok for _, tok in items if tok).strip()
        if line_str:
            norm_line, rep = apply_text_normalization(
                line_str,
                repair_bengali=repair_bengali,
                convert_bangla_digits=convert_bangla_digits,
            )
            if rep:
                any_repaired = True
            if norm_line:
                lines_out.append(norm_line)

    joined = "\n".join(lines_out)
    return joined, lines_out, any_repaired


def _has_garbled_native_text(text: str) -> bool:
    if not text:
        return False
    if "\ufffd" in text:
        return True
    if "(cid:" in text.lower():
        return True
    return False


def _measure_cell_ink_profile(
    cell_img: Optional[Image.Image],
    inset_ratio: float = 0.14,
) -> Dict[str, Any]:
    """
    Measures interior stroke contrast inside a cell crop while ignoring border lines,
    accurately separating blank white/shaded cells from inked unreadable cells.
    """
    if cell_img is None or cell_img.width < 4 or cell_img.height < 4:
        return {"ink_ratio": 0.0, "is_uniform_blank": True, "median_gray": 255.0, "max_dev": 0.0}

    gray = cell_img.convert("L")
    try:
        w, h = gray.size
        pad_x = max(1, min(w // 4, int(round(w * inset_ratio))))
        pad_y = max(1, min(h // 4, int(round(h * inset_ratio))))
        if (w - 2 * pad_x) >= 3 and (h - 2 * pad_y) >= 3:
            interior = gray.crop((pad_x, pad_y, w - pad_x, h - pad_y))
        else:
            interior = gray

        try:
            raw_bytes = interior.tobytes()
            if not raw_bytes:
                return {"ink_ratio": 0.0, "is_uniform_blank": True, "median_gray": 255.0, "max_dev": 0.0}

            hist = interior.histogram()
            total = len(raw_bytes)
            # Median brightness from 256-bin histogram represents cell fill color cleanly
            acc = 0
            med = 255
            half = total // 2
            for val, cnt in enumerate(hist[:256]):
                acc += cnt
                if acc >= half:
                    med = val
                    break

            ink_count = 0
            max_dev = 0
            for val, cnt in enumerate(hist[:256]):
                if cnt:
                    dev = abs(val - med)
                    if dev > max_dev:
                        max_dev = dev
                    if dev >= 26:
                        ink_count += cnt

            ink_ratio = ink_count / max(total, 1)
            is_uniform_blank = (med >= 235 and max_dev <= 14 and ink_ratio < 0.002)
            return {
                "ink_ratio": round(ink_ratio, 5),
                "is_uniform_blank": bool(is_uniform_blank),
                "median_gray": float(med),
                "max_dev": float(max_dev),
            }
        finally:
            if interior is not gray:
                interior.close()
    finally:
        gray.close()


def _prepare_cell_crop_for_ocr(cell_crop: Image.Image) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
    """
    Safely pads small/thin cell crops with clean white margin for Tesseract stability.
    Returns ``(padded_image, (offset_x, offset_y, orig_w, orig_h))``.
    """
    cw, ch = cell_crop.size
    rgb = cell_crop if cell_crop.mode == "RGB" else cell_crop.convert("RGB")
    pad_x = max(12, min(24, cw // 3))
    pad_y = max(12, min(24, ch // 3))
    target_w = max(cw + 2 * pad_x, 64)
    target_h = max(ch + 2 * pad_y, 64)

    # Guard ultra-wide strip cells against extreme Lanczos scaling inside ImagePreprocessor
    aspect = target_w / max(target_h, 1)
    if aspect > 7.5:
        target_h = max(target_h, int(round(target_w / 7.5)))
    elif (1.0 / max(aspect, 1e-6)) > 7.5:
        target_w = max(target_w, int(round(target_h / 7.5)))

    canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
    ox = (target_w - cw) // 2
    oy = (target_h - ch) // 2
    canvas.paste(rgb, (ox, oy))
    if rgb is not cell_crop:
        rgb.close()
    return canvas, (ox, oy, cw, ch)


def _assign_native_words_exclusively(
    cells: Sequence[Dict[str, Any]],
    native_words: Sequence[Mapping[str, Any]],
    table_norm_box: Sequence[int],
) -> Tuple[Dict[int, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """
    Assigns each native PDF word to at most ONE table cell by highest box overlap,
    guaranteeing no duplicate cross-border shifting, and tracks unmapped table words.
    """
    ty0, tx0, ty1, tx1 = [int(v) for v in table_norm_box[:4]]
    cell_buckets: Dict[int, List[Dict[str, Any]]] = {c["cell_index"]: [] for c in cells}
    unmapped: List[Dict[str, Any]] = []

    valid_cell_boxes: List[Tuple[int, Tuple[int, int, int, int]]] = []
    for c in cells:
        nb = c.get("normalized_box")
        if c.get("has_valid_box") and isinstance(nb, (list, tuple)) and len(nb) >= 4:
            valid_cell_boxes.append((c["cell_index"], _norm_box_to_xyxy(nb)))

    for wb in native_words:
        if not isinstance(wb, Mapping):
            continue
        word_str = str(wb.get("word") or "").strip()
        wnb = wb.get("normalized_box")
        if not word_str or not isinstance(wnb, (list, tuple)) or len(wnb) < 4:
            continue

        wxy = _norm_box_to_xyxy(wnb)
        wcx = (wxy[0] + wxy[2]) / 2.0
        wcy = (wxy[1] + wxy[3]) / 2.0
        # Ignore page prose outside this table region
        if not ((tx0 - 4) <= wcx <= (tx1 + 4) and (ty0 - 4) <= wcy <= (ty1 + 4)):
            continue

        w_area = max(1.0, float((wxy[2] - wxy[0]) * (wxy[3] - wxy[1])))
        best_cell_idx: Optional[int] = None
        best_score = 0.0

        for cid, cxy in valid_cell_boxes:
            inter = _box_intersection_area(wxy, cxy)
            overlap_frac = inter / w_area
            strict_inside = cxy[0] <= wcx <= cxy[2] and cxy[1] <= wcy <= cxy[3]
            near_inside = (cxy[0] - 2) <= wcx <= (cxy[2] + 2) and (cxy[1] - 2) <= wcy <= (cxy[3] + 2)
            if overlap_frac >= 0.30 or near_inside:
                score = overlap_frac + (0.50 if strict_inside else (0.15 if near_inside else 0.0))
                if score > best_score:
                    best_score = score
                    best_cell_idx = cid

        if best_cell_idx is not None:
            cell_buckets[best_cell_idx].append(dict(wb))
        else:
            unmapped.append(dict(wb))

    return cell_buckets, unmapped


# ==============================================================================
# FOOTNOTES, HTML RECONSTRUCTION, MARKDOWN & VALIDATION
# ==============================================================================
_FOOTNOTE_PREFIX_RE = re.compile(
    r"^(?:\*+|†|‡|§|\[\d+\]|\d+\)|(?:notes?|source|footnote)\s*[:\-])\s*.+",
    re.IGNORECASE,
)


def _is_footnote_row(row_cells: Sequence[Mapping[str, Any]], num_cols: int, row_idx: int, num_rows: int) -> bool:
    if row_idx < max(1, num_rows - 1):
        return False
    populated = [c for c in row_cells if c.get("state") == CellStatus.POPULATED.value and c.get("text")]
    if len(populated) != 1:
        return False
    only_cell = populated[0]
    txt = str(only_cell.get("text") or "").strip()
    is_full_span = int(only_cell.get("colspan", 1)) >= max(2, num_cols)
    if is_full_span and _FOOTNOTE_PREFIX_RE.match(txt):
        return True
    if is_full_span and num_rows >= 3 and row_idx == num_rows - 1 and len(row_cells) == 1:
        # Check prefix or explanatory footnote sentence spanning whole table width
        return bool(_FOOTNOTE_PREFIX_RE.match(txt))
    return False


def _collect_adjacent_layout_footnotes(
    table_norm_box: Sequence[int],
    context_regions: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    if not context_regions or len(table_norm_box) < 4:
        return []
    ty0, tx0, ty1, tx1 = [int(v) for v in table_norm_box[:4]]
    tbl_w = max(1, tx1 - tx0)
    footnotes: List[Dict[str, Any]] = []

    for reg in context_regions:
        raw_label = str(reg.get("raw_label") or (reg.get("metadata") or {}).get("raw_label") or "").lower()
        cat = str(reg.get("layout_category") or (reg.get("metadata") or {}).get("layout_category") or "").lower()
        nb = reg.get("normalized_box")
        txt = str(reg.get("text") or "").strip()
        if not isinstance(nb, (list, tuple)) or len(nb) < 4 or not txt:
            continue
        is_footnote_label = ("footnote" in raw_label) or (cat == "paragraph" and _FOOTNOTE_PREFIX_RE.match(txt))
        if not is_footnote_label:
            continue
        ry0, rx0, ry1, rx1 = [int(v) for v in nb[:4]]
        gap_below = ry0 - ty1
        x_overlap = max(0, min(tx1, rx1) - max(tx0, rx0)) / float(tbl_w)
        if -12 <= gap_below <= 70 and x_overlap >= 0.45:
            footnotes.append({
                "text": txt,
                "normalized_box": list(nb[:4]),
                "source": "adjacent_layout_footnote",
                "region_id": str(reg.get("region_id") or ""),
            })
    return footnotes


def _build_grid_and_reconstructions(
    *,
    cells: List[Dict[str, Any]],
    occupied: Mapping[Tuple[int, int], int],
    num_rows: int,
    num_cols: int,
    structure_dict: Mapping[str, Any],
) -> Dict[str, Any]:
    """Builds exact rectangular display matrix, HTML reconstruction, and Markdown table."""
    if num_rows <= 0 or num_cols <= 0 or not cells:
        return {
            "headers": [],
            "header_source": "none",
            "header_row_indices": [],
            "rows_matrix": [],
            "body_rows": [],
            "footnotes": [],
            "html": "",
            "markdown": "",
        }

    cell_by_idx = {c["cell_index"]: c for c in cells}
    cells_by_row: Dict[int, List[Dict[str, Any]]] = {r: [] for r in range(num_rows)}
    for c in cells:
        cells_by_row.setdefault(int(c["row"]), []).append(c)

    # Identify explicit header row indices strictly from <thead> or <th> evidence
    explicit_header_rows = sorted({
        int(c["row"])
        for c in cells
        if c.get("is_header") and c.get("state") in (CellStatus.POPULATED.value, CellStatus.EMPTY.value, CellStatus.UNREADABLE.value)
    })
    # Contiguous leading <thead>/<th> rows form table headers without ever inventing header labels
    header_row_indices: List[int] = []
    if explicit_header_rows and explicit_header_rows[0] == 0:
        for r_idx in explicit_header_rows:
            if not header_row_indices or r_idx == header_row_indices[-1] + 1:
                header_row_indices.append(r_idx)
            else:
                break
        header_source = "slanet_thead"
    else:
        header_source = "none"

    # Extract bottom spanned footnotes without inventing or dropping text
    footnote_rows: set[int] = set()
    extracted_footnotes: List[Dict[str, Any]] = []
    if num_rows >= 2:
        last_r = num_rows - 1
        last_row_cells = cells_by_row.get(last_r, [])
        if last_r not in header_row_indices and _is_footnote_row(last_row_cells, num_cols, last_r, num_rows):
            footnote_rows.add(last_r)
            fn_cell = next(c for c in last_row_cells if c.get("text"))
            extracted_footnotes.append({
                "text": fn_cell["text"],
                "normalized_box": list(fn_cell.get("normalized_box") or [0, 0, 0, 0]),
                "source": "table_bottom_row",
            })

    # Reconstruct full rectangular matrix respecting spanned origins WITHOUT shifting values
    matrix_rows: List[List[str]] = []
    for r in range(num_rows):
        row_vals: List[str] = []
        for c_col in range(num_cols):
            origin_idx = occupied.get((r, c_col))
            if origin_idx is None:
                row_vals.append("")
                continue
            origin_cell = cell_by_idx[origin_idx]
            if origin_cell["row"] == r and origin_cell["col"] == c_col:
                row_vals.append(str(origin_cell.get("text") or ""))
            else:
                # Span continuation slot remains blank in tabular projection so column
                # coordinates stay strictly aligned and never duplicate sibling facts
                row_vals.append("")
        matrix_rows.append(row_vals)

    headers = [matrix_rows[r] for r in header_row_indices]
    body_rows = [matrix_rows[r] for r in range(num_rows) if r not in header_row_indices and r not in footnote_rows]

    # Build faithful HTML preserving thead/tbody/rowspan/colspan/exact cell text
    html_parts: List[str] = ["<table>"]
    thead_open = False
    tbody_open = False
    for r in range(num_rows):
        in_hdr = r in header_row_indices
        if in_hdr and not thead_open:
            html_parts.append("<thead>")
            thead_open = True
        elif not in_hdr and thead_open:
            html_parts.append("</thead><tbody>")
            thead_open = False
            tbody_open = True
        elif not in_hdr and not tbody_open:
            html_parts.append("<tbody>")
            tbody_open = True

        html_parts.append("<tr>")
        for cell in sorted(cells_by_row.get(r, []), key=lambda item: item["col"]):
            tag = "th" if in_hdr or cell.get("is_header") else "td"
            attrs: List[str] = []
            if int(cell.get("rowspan", 1)) > 1:
                attrs.append(f'rowspan="{int(cell["rowspan"])}"')
            if int(cell.get("colspan", 1)) > 1:
                attrs.append(f'colspan="{int(cell["colspan"])}"')
            attrs.append(f'data-state="{cell["state"]}"')
            attr_str = (" " + " ".join(attrs)) if attrs else ""
            escaped = (
                str(cell.get("text") or "")
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            html_parts.append(f"<{tag}{attr_str}>{escaped}</{tag}>")
        html_parts.append("</tr>")

    if thead_open:
        html_parts.append("</thead>")
    if tbody_open:
        html_parts.append("</tbody>")
    html_parts.append("</table>")

    # Build pipe Markdown preserving multi-line cell values (<br>) and blank slots
    md_rows: List[List[str]] = []
    for r in range(num_rows):
        if r in footnote_rows:
            continue
        formatted_row = [
            "" if not val else val.replace("\n", "<br>").replace("|", "\\|").strip()
            for val in matrix_rows[r]
        ]
        md_rows.append(formatted_row)

    md_lines: List[str] = []
    if md_rows:
        top = "| " + " | ".join(md_rows[0]) + " |"
        sep = "| " + " | ".join(["---"] * num_cols) + " |"
        md_lines.extend([top, sep])
        for row_vals in md_rows[1:]:
            md_lines.append("| " + " | ".join(row_vals) + " |")

    return {
        "headers": headers,
        "header_source": header_source,
        "header_row_indices": header_row_indices,
        "rows_matrix": matrix_rows,
        "body_rows": body_rows,
        "footnotes": extracted_footnotes,
        "html": "".join(html_parts),
        "markdown": "\n".join(md_lines),
    }


def validate_table_structure(
    *,
    parsed_structure: Mapping[str, Any],
    cells: Sequence[Mapping[str, Any]],
    unmapped_native_words: Sequence[Mapping[str, Any]] = (),
    min_structure_score: float = 0.60,
    min_cell_ocr_confidence: float = 0.45,
) -> Dict[str, Any]:
    """
    Validates reconstructed table integrity and decides whether the table must be
    returned with ``needs_review=True`` for human verification.
    Never shifts cell values or invents headers/units/numbers.
    """
    issues: List[Dict[str, Any]] = []
    score = float(parsed_structure.get("structure_score", 0.0) or 0.0)
    num_rows = int(parsed_structure.get("num_rows", 0) or 0)
    num_cols = int(parsed_structure.get("num_cols", 0) or 0)

    if num_rows == 0 or num_cols == 0 or not cells:
        issues.append({
            "code": "empty_or_invalid_structure",
            "severity": "high",
            "detail": f"Table structure decoded {num_rows} rows x {num_cols} cols ({len(cells)} cells).",
        })

    if score < min_structure_score:
        issues.append({
            "code": "low_structure_confidence",
            "severity": "medium",
            "detail": f"SLANet_plus structure_score={score:.3f} below threshold={min_structure_score:.2f}.",
        })

    ragged_rows = parsed_structure.get("ragged_rows") or []
    if ragged_rows:
        issues.append({
            "code": "ragged_row_lengths",
            "severity": "high",
            "detail": f"Detected {len(ragged_rows)} row(s) shorter than {num_cols} columns; cells kept in original column positions without shifting.",
            "rows": [r["row"] for r in ragged_rows],
        })

    extra_boxes = int(parsed_structure.get("extra_box_count", 0) or 0)
    missing_cells = [c for c in cells if c.get("state") == CellStatus.MISSING.value]
    if missing_cells or extra_boxes > 0:
        issues.append({
            "code": "cell_box_mismatch",
            "severity": "high",
            "detail": f"{len(missing_cells)} cell(s) missing valid bbox, {extra_boxes} extra unaligned box(es).",
            "missing_cell_ids": [c.get("cell_id") for c in missing_cells],
        })

    collisions = parsed_structure.get("span_collisions") or []
    if collisions:
        issues.append({
            "code": "span_collision",
            "severity": "high",
            "detail": f"Detected {len(collisions)} overlapping rowspan/colspan coordinate collision(s).",
        })

    unreadable_cells = [c for c in cells if c.get("state") == CellStatus.UNREADABLE.value]
    if unreadable_cells:
        issues.append({
            "code": "unreadable_cells_present",
            "severity": "high",
            "detail": f"{len(unreadable_cells)} non-blank cell(s) could not be reliably decoded.",
            "cell_ids": [c.get("cell_id") for c in unreadable_cells],
        })

    low_conf_cells = [
        c
        for c in cells
        if c.get("state") == CellStatus.POPULATED.value
        and c.get("source") == CellSource.OCR_TESSERACT.value
        and float(c.get("confidence", 0.0) or 0.0) < min_cell_ocr_confidence
    ]
    if low_conf_cells:
        issues.append({
            "code": "low_confidence_ocr_cells",
            "severity": "medium",
            "detail": f"{len(low_conf_cells)} OCR-populated cell(s) below confidence {min_cell_ocr_confidence:.2f}.",
            "cell_ids": [c.get("cell_id") for c in low_conf_cells],
        })

    if unmapped_native_words:
        issues.append({
            "code": "unmapped_table_text",
            "severity": "medium",
            "detail": f"{len(unmapped_native_words)} native PDF word(s) inside table region fell outside every detected cell box.",
            "sample_words": [str(w.get("word", "")) for w in unmapped_native_words[:6]],
        })

    for st_issue in parsed_structure.get("structural_issues") or []:
        issues.append({"code": str(st_issue), "severity": "medium", "detail": f"Structure parser note: {st_issue}"})

    state_counts = {
        CellStatus.POPULATED.value: sum(1 for c in cells if c.get("state") == CellStatus.POPULATED.value),
        CellStatus.EMPTY.value: sum(1 for c in cells if c.get("state") == CellStatus.EMPTY.value),
        CellStatus.UNREADABLE.value: len(unreadable_cells),
        CellStatus.MISSING.value: len(missing_cells),
    }
    needs_review = bool(issues)
    return {
        "is_valid": not needs_review,
        "needs_review": needs_review,
        "issue_codes": sorted({i["code"] for i in issues}),
        "issues": issues,
        "structure_score": round(score, 4),
        "cell_counts_by_state": state_counts,
        "unmapped_word_count": len(unmapped_native_words),
    }


# ==============================================================================
# MULTI-PAGE TABLE CONTINUATION LINKER (CONSERVATIVE, NON-MUTATING)
# ==============================================================================
def link_multipage_tables(pages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Links multi-page table continuations conservatively across consecutive pages
    based solely on geometry alignment and column structure. Never invents headers,
    never copies or shifts cells across pages, and flags ambiguous continuations
    for human review.
    """
    if len(pages) < 2:
        return list(pages)

    ordered_pages = sorted(pages, key=lambda p: int(p.get("page_number", 0) or 0))
    table_entries_by_page: Dict[int, List[Dict[str, Any]]] = {}

    for p in ordered_pages:
        p_num = int(p.get("page_number", 0) or 0)
        tbls = [
            reg
            for reg in (p.get("visual_regions") or [])
            if isinstance(reg, dict)
            and reg.get("region_type") == VisualRegionType.TABLE.value
            and isinstance((reg.get("metadata") or {}).get("table_structure"), Mapping)
        ]
        if tbls:
            tbls.sort(key=lambda r: int((r.get("normalized_box") or [0, 0, 0, 0])[0]))
            table_entries_by_page[p_num] = tbls

    group_counter = 0
    active_group_id_by_region: Dict[str, str] = {}
    group_headers_by_id: Dict[str, List[List[str]]] = {}

    for i in range(len(ordered_pages) - 1):
        p_curr = ordered_pages[i]
        p_next = ordered_pages[i + 1]
        num_curr = int(p_curr.get("page_number", 0) or 0)
        num_next = int(p_next.get("page_number", 0) or 0)
        if num_next != num_curr + 1:
            continue

        curr_tbls = table_entries_by_page.get(num_curr, [])
        next_tbls = table_entries_by_page.get(num_next, [])
        if not curr_tbls or not next_tbls:
            continue

        last_tbl = curr_tbls[-1]
        first_next_tbl = next_tbls[0]

        nb1 = last_tbl.get("normalized_box") or [0, 0, 0, 0]
        nb2 = first_next_tbl.get("normalized_box") or [0, 0, 0, 0]
        meta1 = last_tbl.setdefault("metadata", {})
        meta2 = first_next_tbl.setdefault("metadata", {})
        ts1 = meta1.get("table_structure") or {}
        ts2 = meta2.get("table_structure") or {}

        cols1 = int(ts1.get("num_cols", 0) or 0)
        cols2 = int(ts2.get("num_cols", 0) or 0)

        # Position check: page N table ends near bottom (>=650) OR nothing body-like below it,
        # and page N+1 table starts near top (<=340) without preceding title banner.
        ends_bottom = int(nb1[2]) >= 650
        starts_top = int(nb2[0]) <= 340
        has_title_above = any(
            reg.get("region_type") == VisualRegionType.TITLE_HEADING.value
            and int((reg.get("normalized_box") or [999, 0, 999, 0])[2]) <= int(nb2[0])
            for reg in (p_next.get("visual_regions") or [])
        )
        x_aligned = abs(int(nb1[1]) - int(nb2[1])) <= 70 and abs(int(nb1[3]) - int(nb2[3])) <= 70

        if not (ends_bottom and starts_top and not has_title_above and x_aligned):
            continue

        if cols1 >= 2 and cols1 == cols2:
            r1_id = str(last_tbl.get("region_id") or f"p{num_curr}-tbl")
            r2_id = str(first_next_tbl.get("region_id") or f"p{num_next}-tbl")
            if r1_id in active_group_id_by_region:
                gid = active_group_id_by_region[r1_id]
            else:
                group_counter += 1
                gid = f"tbl-group-{group_counter}"
                active_group_id_by_region[r1_id] = gid
            active_group_id_by_region[r2_id] = gid

            # Check whether header row literally repeated cleanly on next page
            # (preserve group's original header across multi-page continuations even if page N was headerless)
            h1 = ts1.get("headers") or []
            if h1 and gid not in group_headers_by_id:
                group_headers_by_id[gid] = h1
            ref_headers = group_headers_by_id.get(gid) or h1
            row0_next = (ts2.get("rows") or [None])[0]
            h2 = ts2.get("headers") or []
            if not ref_headers and h2:
                group_headers_by_id[gid] = h2
            header_repeated = bool(
                ref_headers
                and (
                    (h2 and [c.strip().lower() for c in ref_headers[0]] == [c.strip().lower() for c in h2[0]])
                    or (row0_next and [c.strip().lower() for c in ref_headers[0]] == [c.strip().lower() for c in row0_next])
                )
            )

            c1_meta = dict(meta1.get("continuation") or {})
            c1_meta.update({
                "continuation_group_id": gid,
                "role": "continuation" if c1_meta.get("previous_table_region_id") else "start",
                "next_table_region_id": r2_id,
                "next_page_number": num_next,
                "uncertain": False,
            })
            meta1["continuation"] = c1_meta

            meta2["continuation"] = {
                "continuation_group_id": gid,
                "role": "end",
                "previous_table_region_id": r1_id,
                "previous_page_number": num_curr,
                "header_repeated": header_repeated,
                "uncertain": False,
            }
            if meta1.get("needs_review") or meta2.get("needs_review"):
                meta1["continuation"]["uncertain"] = True
                meta2["continuation"]["uncertain"] = True
        elif cols1 >= 2 and cols2 >= 1 and abs(cols1 - cols2) == 1:
            # Ambiguous column count change -> do NOT link as matched continuation or shift; flag review
            group_counter += 1
            gid = f"tbl-uncertain-{group_counter}"
            meta1["continuation"] = {
                "continuation_group_id": gid,
                "role": "uncertain_end",
                "candidate_next_region_id": str(first_next_tbl.get("region_id") or ""),
                "uncertain": True,
                "reason": f"column_count_mismatch_{cols1}_vs_{cols2}",
            }
            meta2["continuation"] = {
                "continuation_group_id": gid,
                "role": "uncertain_continuation",
                "candidate_previous_region_id": str(last_tbl.get("region_id") or ""),
                "uncertain": True,
                "reason": f"column_count_mismatch_{cols1}_vs_{cols2}",
            }
            meta1["needs_review"] = True
            meta2["needs_review"] = True
            p_curr["needs_review"] = True
            p_next["needs_review"] = True
            for p_obj, other_num in ((p_curr, num_next), (p_next, num_curr)):
                warns = list(p_obj.get("warnings") or [])
                warns.append(
                    f"Multi-page table alignment between page {num_curr} ({cols1} cols) and "
                    f"page {other_num} ({cols2} cols) is uncertain; flagged for human review."
                )
                p_obj["warnings"] = list(dict.fromkeys(warns))

    return list(pages)


# ==============================================================================
# SLANET_PLUS TABLE EXTRACTOR SERVICE
# ==============================================================================
class SLANetPlusTableExtractor:
    """
    Extracts structured tables from layout-detected table regions using
    ``SLANet_plus`` (``paddleocr.TableStructureRecognition``) on CPU, combining:
    1. Accurate rotated/scaled table cropping from original page images.
    2. Reused native PDF cell text (when available & reliable).
    3. ``TesseractOCRProvider`` cell OCR for scanned/image/mixed cell text.
    4. Exact ``populated`` / ``empty`` / ``unreadable`` / ``missing`` cell status.
    5. Structure validation & ``needs_review`` propagation for human review.
    """

    provider_name = "slanet_plus"
    engine_version = SLANET_PLUS_MODEL_NAME
    requires_remote_egress = False

    def __init__(
        self,
        config: Optional[SLANetPlusConfig] = None,
        ocr_provider: Optional[BaseOCRProvider] = None,
        model_loader: Optional[Callable[[SLANetPlusConfig], Any]] = None,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
    ):
        self.config = config or SLANetPlusConfig.from_settings_or_env()
        self.ocr_provider: BaseOCRProvider = ocr_provider or TesseractOCRProvider()
        self._model_loader = model_loader
        self._instance_model: Any = None
        self.repair_bengali = repair_bengali
        self.convert_bangla_digits = convert_bangla_digits
        self.last_status_reason: str = ""

    def _default_model_loader(self, config: SLANetPlusConfig) -> Any:
        if not HAS_PADDLEOCR_TABLE_STRUCTURE or _PaddleOCRTableStructureRecognition is None:
            raise ImportError(
                "paddleocr>=3.0.0 with TableStructureRecognition is required for SLANet_plus."
            )
        if not HAS_PADDLEPADDLE:
            raise ImportError(
                "paddlepaddle>=3.0.0 CPU package is required for SLANet_plus inference."
            )

        kwargs: Dict[str, Any] = {
            "model_name": config.model_name,
            "device": "cpu",
            "cpu_threads": config.cpu_threads,
            "enable_mkldnn": config.enable_mkldnn,
        }
        if config.model_dir:
            kwargs["model_dir"] = config.model_dir

        try:
            sig = inspect.signature(_PaddleOCRTableStructureRecognition.__init__)
            accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if not accepts_var_kw:
                kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
        except (TypeError, ValueError):
            pass

        return _PaddleOCRTableStructureRecognition(**kwargs)

    def _get_or_load_model(self) -> Any:
        if self.config.model_dir and not os.path.isdir(self.config.model_dir):
            raise FileNotFoundError(
                f"Configured SLANet_plus model_dir does not exist: {self.config.model_dir}"
            )
        loader = self._model_loader or self._default_model_loader
        if self.config.reuse_worker_model:
            return WorkerTableStructureModelCache.get_or_load(self.config, loader)
        if self._instance_model is None:
            self._instance_model = loader(self.config)
        return self._instance_model

    def is_available(self) -> bool:
        """Checks runtime availability without performing remote weight downloads."""
        if self.config.model_dir and not os.path.isdir(self.config.model_dir):
            self.last_status_reason = "model_dir_missing"
            return False
        if self._model_loader is not None:
            self.last_status_reason = "ready_custom_loader"
            return True
        if not (HAS_PADDLEOCR_TABLE_STRUCTURE and HAS_PADDLEPADDLE):
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
    def _prepare_model_input(crop_image: Image.Image) -> Any:
        rgb = crop_image if crop_image.mode == "RGB" else crop_image.convert("RGB")
        try:
            if HAS_NUMPY and np is not None:
                arr = np.asarray(rgb, dtype=np.uint8)
                return np.ascontiguousarray(arr[:, :, ::-1])
            return rgb.copy()
        finally:
            if rgb is not crop_image:
                try:
                    rgb.close()
                except Exception:
                    pass

    @staticmethod
    def _invoke_predict(model: Any, model_input: Any) -> Any:
        try:
            sig = inspect.signature(model.predict)
            if "batch_size" in sig.parameters:
                return list(model.predict(model_input, batch_size=1))
        except (TypeError, ValueError):
            pass
        return list(model.predict(model_input))

    @staticmethod
    def _remap_cell_word_boxes(
        ocr_wbs: Sequence[Mapping[str, Any]],
        prep_size: Tuple[int, int],
        pad_box: Tuple[int, int, int, int],
        cell_page_box_xyxy: Tuple[float, float, float, float],
        page_w: float,
        page_h: float,
        *,
        repair_bengali: bool,
        convert_bangla_digits: bool,
    ) -> List[Dict[str, Any]]:
        pw_prep = max(1.0, float(prep_size[0]))
        ph_prep = max(1.0, float(prep_size[1]))
        pad_ox, pad_oy, orig_cw, orig_ch = pad_box
        orig_cw_f = max(1.0, float(orig_cw))
        orig_ch_f = max(1.0, float(orig_ch))
        rx0, ry0, rx1, ry1 = cell_page_box_xyxy
        rw = max(1.0, rx1 - rx0)
        rh = max(1.0, ry1 - ry0)
        out: List[Dict[str, Any]] = []

        for wb in ocr_wbs:
            if not isinstance(wb, Mapping):
                continue
            raw_word = str(wb.get("word") or "").strip()
            if not raw_word:
                continue
            word, _ = apply_text_normalization(
                raw_word,
                repair_bengali=repair_bengali,
                convert_bangla_digits=convert_bangla_digits,
            )
            if not word:
                continue

            nb = wb.get("normalized_box")
            if isinstance(nb, (list, tuple)) and len(nb) == 4:
                px_left = (float(nb[1]) / 1000.0) * pw_prep
                px_right = (float(nb[3]) / 1000.0) * pw_prep
                py_top = (float(nb[0]) / 1000.0) * ph_prep
                py_bot = (float(nb[2]) / 1000.0) * ph_prep
            else:
                bx = float(wb.get("x", 0.0) or 0.0)
                by = float(wb.get("y", 0.0) or 0.0)
                bw = max(0.0, float(wb.get("w", 0.0) or 0.0))
                bh = max(0.0, float(wb.get("h", 0.0) or 0.0))
                px_left, px_right = bx, bx + bw
                py_top, py_bot = by, by + bh

            fx0 = max(0.0, min(1.0, (px_left - pad_ox) / orig_cw_f))
            fx1 = max(fx0, min(1.0, (px_right - pad_ox) / orig_cw_f))
            fy0 = max(0.0, min(1.0, (py_top - pad_oy) / orig_ch_f))
            fy1 = max(fy0, min(1.0, (py_bot - pad_oy) / orig_ch_f))

            px0 = rx0 + fx0 * rw
            px1 = rx0 + fx1 * rw
            py0 = ry0 + fy0 * rh
            py1 = ry0 + fy1 * rh
            copied = dict(wb)
            copied["word"] = word
            copied["x"] = int(round(px0))
            copied["y"] = int(round(py0))
            copied["w"] = max(0, int(round(px1 - px0)))
            copied["h"] = max(0, int(round(py1 - py0)))
            copied["normalized_box"] = rect_to_normalized_box(px0, py0, px1, py1, canvas_width=page_w, canvas_height=page_h)
            out.append(copied)

        return out

    def extract_table_region(
        self,
        *,
        page_image: Image.Image,
        table_box: Sequence[float],
        bbox_format: str = "normalized",
        page_number: int = 1,
        page_width: Optional[float] = None,
        page_height: Optional[float] = None,
        source_rotation: int = 0,
        coords_in_unrotated_space: bool = False,
        region_id: Optional[str] = None,
        layout_score: Optional[float] = None,
        layout_label: str = "table",
        native_words: Optional[Sequence[Mapping[str, Any]]] = None,
        context_regions: Optional[Sequence[Mapping[str, Any]]] = None,
        fallback_vector_table: Optional[Mapping[str, Any]] = None,
        source_asset_name: str = "",
    ) -> Dict[str, Any]:
        """
        Extracts a full validated table structure from one detected table region.
        Reuses native PDF cell content where reliable, falls back per-cell to
        ``TesseractOCRProvider`` on scanned/image/mixed regions, and gracefully
        degrades when ``SLANet_plus`` is unavailable or uncertain.
        """
        t0 = time.time()
        eff_region_id = region_id or f"p{page_number}-tbl1-slanet_plus"

        crop_img, crop_geom = resolve_table_crop_geometry(
            page_image=page_image,
            table_box=table_box,
            bbox_format=bbox_format,
            page_width=page_width,
            page_height=page_height,
            source_rotation=source_rotation,
            coords_in_unrotated_space=coords_in_unrotated_space,
            padding_px=self.config.crop_padding_px,
        )
        if crop_img is None or not crop_geom:
            return self._build_fallback_table_region(
                region_id=eff_region_id,
                page_number=page_number,
                table_norm_box=[0, 0, 1000, 1000],
                table_bbox_wh=[0.0, 0.0, float(page_width or page_image.width), float(page_height or page_image.height)],
                page_image=page_image,
                native_words=native_words,
                fallback_vector_table=fallback_vector_table,
                source_asset_name=source_asset_name,
                reason="invalid_or_empty_table_crop",
                layout_score=layout_score,
                layout_label=layout_label,
                elapsed_ms=round((time.time() - t0) * 1000.0, 2),
            )

        try:
            if not self.is_available():
                return self._build_fallback_table_region(
                    region_id=eff_region_id,
                    page_number=page_number,
                    table_norm_box=crop_geom["table_normalized_box"],
                    table_bbox_wh=crop_geom["table_display_bbox"],
                    page_image=crop_img,
                    native_words=native_words,
                    fallback_vector_table=fallback_vector_table,
                    source_asset_name=source_asset_name,
                    reason=self.last_status_reason or "slanet_plus_unavailable",
                    layout_score=layout_score,
                    layout_label=layout_label,
                    crop_geom=crop_geom,
                    elapsed_ms=round((time.time() - t0) * 1000.0, 2),
                )

            try:
                from .runtime import configure_visual_cpu_runtime

                configure_visual_cpu_runtime(cpu_threads=self.config.cpu_threads)
                model = self._get_or_load_model()
                model_input = self._prepare_model_input(crop_img)
                try:
                    raw_output = self._invoke_predict(model, model_input)
                    parsed = parse_slanet_structure_and_cells(raw_output)
                finally:
                    model_input = None
                    raw_output = None
            except Exception as exc:
                safe_err = sanitize_sensitive_data(str(exc))
                logger.warning("SLANet_plus prediction failed on %s: %s", eff_region_id, safe_err)
                return self._build_fallback_table_region(
                    region_id=eff_region_id,
                    page_number=page_number,
                    table_norm_box=crop_geom["table_normalized_box"],
                    table_bbox_wh=crop_geom["table_display_bbox"],
                    page_image=crop_img,
                    native_words=native_words,
                    fallback_vector_table=fallback_vector_table,
                    source_asset_name=source_asset_name,
                    reason=f"slanet_plus_inference_error: {safe_err}",
                    layout_score=layout_score,
                    layout_label=layout_label,
                    crop_geom=crop_geom,
                    elapsed_ms=round((time.time() - t0) * 1000.0, 2),
                )

            if parsed["num_rows"] == 0 or parsed["num_cols"] == 0 or not parsed["cells"]:
                return self._build_fallback_table_region(
                    region_id=eff_region_id,
                    page_number=page_number,
                    table_norm_box=crop_geom["table_normalized_box"],
                    table_bbox_wh=crop_geom["table_display_bbox"],
                    page_image=crop_img,
                    native_words=native_words,
                    fallback_vector_table=fallback_vector_table,
                    source_asset_name=source_asset_name,
                    reason="slanet_plus_empty_structure",
                    layout_score=layout_score,
                    layout_label=layout_label,
                    crop_geom=crop_geom,
                    elapsed_ms=round((time.time() - t0) * 1000.0, 2),
                )

            # Project cell bboxes cleanly to page display & canonical normalized coordinates
            table_cells: List[Dict[str, Any]] = []
            for raw_cell in parsed["cells"]:
                c_record: Dict[str, Any] = {
                    "cell_id": f"{eff_region_id}-r{raw_cell['row']}c{raw_cell['col']}",
                    "cell_index": raw_cell["cell_index"],
                    "row": raw_cell["row"],
                    "col": raw_cell["col"],
                    "rowspan": raw_cell["rowspan"],
                    "colspan": raw_cell["colspan"],
                    "is_header": raw_cell["is_header"],
                    "has_valid_box": raw_cell["has_valid_box"],
                    "state": CellStatus.MISSING.value if not raw_cell["has_valid_box"] else CellStatus.EMPTY.value,
                    "text": "",
                    "lines": [],
                    "source": CellSource.NONE.value,
                    "confidence": 0.0,
                    "needs_review": not raw_cell["has_valid_box"],
                    "is_repaired": False,
                    "bbox": None,
                    "normalized_box": None,
                    "crop_bbox": raw_cell["raw_crop_box"],
                    "warnings": ([raw_cell["missing_box_reason"]] if raw_cell["missing_box_reason"] else []),
                }
                if raw_cell["has_valid_box"] and raw_cell["raw_crop_box"] is not None:
                    mapped = crop_box_to_page_coords(raw_cell["raw_crop_box"], crop_geom)
                    if mapped.get("is_clipped_empty"):
                        c_record["has_valid_box"] = False
                        c_record["state"] = CellStatus.MISSING.value
                        c_record["needs_review"] = True
                        c_record["warnings"].append("clipped_outside_table_bounds")
                    else:
                        c_record["bbox"] = mapped["bbox"]
                        c_record["normalized_box"] = mapped["normalized_box"]
                        c_record["model_crop_box"] = mapped["model_crop_box"]
                table_cells.append(c_record)

            # Explicitly record unoccupied grid coordinates on ragged rows as MISSING
            # without shifting neighboring values into them
            next_syn_idx = len(table_cells)
            for rr in parsed.get("ragged_rows") or []:
                r_idx = int(rr["row"])
                for c_col in range(parsed["num_cols"]):
                    if (r_idx, c_col) not in parsed["occupied"]:
                        table_cells.append({
                            "cell_id": f"{eff_region_id}-r{r_idx}c{c_col}",
                            "cell_index": next_syn_idx,
                            "row": r_idx,
                            "col": c_col,
                            "rowspan": 1,
                            "colspan": 1,
                            "is_header": False,
                            "has_valid_box": False,
                            "state": CellStatus.MISSING.value,
                            "text": "",
                            "lines": [],
                            "source": CellSource.NONE.value,
                            "confidence": 0.0,
                            "needs_review": True,
                            "is_repaired": False,
                            "bbox": None,
                            "normalized_box": None,
                            "crop_bbox": None,
                            "warnings": ["unoccupied_ragged_grid_slot"],
                        })
                        next_syn_idx += 1

            # Assign native PDF words exclusively to matching cells (no cross-cell shift)
            native_by_cell, unmapped_native = _assign_native_words_exclusively(
                table_cells,
                native_words or (),
                crop_geom["table_normalized_box"],
            )

            all_cell_word_boxes: List[Dict[str, Any]] = []
            any_cell_repaired = False
            any_ocr_used = False
            any_native_used = False

            eff_pw = float(crop_geom["page_width"])
            eff_ph = float(crop_geom["page_height"])

            for cell in table_cells:
                cid = cell["cell_index"]
                if not cell["has_valid_box"]:
                    cell["state"] = CellStatus.MISSING.value
                    cell["needs_review"] = True
                    continue

                assigned_native = native_by_cell.get(cid, [])
                native_text, native_lines, native_repaired = _reconstruct_multiline_text(
                    assigned_native,
                    repair_bengali=self.repair_bengali,
                    convert_bangla_digits=self.convert_bangla_digits,
                )

                # Use reliable native text if present and free of glyph-encoding corruption
                if native_text and not _has_garbled_native_text(native_text):
                    cell["text"] = native_text
                    cell["lines"] = native_lines
                    cell["state"] = CellStatus.POPULATED.value
                    cell["source"] = CellSource.NATIVE_PDF.value
                    confs = [float(w.get("confidence", 0.95) or 0.95) for w in assigned_native]
                    cell["confidence"] = round(sum(confs) / max(len(confs), 1), 4)
                    cell["needs_review"] = False
                    cell["is_repaired"] = native_repaired
                    if native_repaired:
                        any_cell_repaired = True
                    any_native_used = True
                    all_cell_word_boxes.extend(assigned_native)
                    continue

                if native_text and _has_garbled_native_text(native_text):
                    cell["warnings"].append("garbled_native_pdf_text_fallback_to_ocr")

                # Scanned / image-based / borderless raster or corrupted-font cell -> crop & inspect
                mcb = cell.get("model_crop_box") or cell.get("crop_bbox")
                x0, y0, x1, y1 = [float(v) for v in mcb[:4]]
                ix0 = max(0, min(crop_img.width - 1, int(round(x0))))
                iy0 = max(0, min(crop_img.height - 1, int(round(y0))))
                ix1 = max(ix0 + 1, min(crop_img.width, int(round(x1))))
                iy1 = max(iy0 + 1, min(crop_img.height, int(round(y1))))

                cell_patch = crop_img.crop((ix0, iy0, ix1, iy1))
                ink_profile = _measure_cell_ink_profile(cell_patch)
                cell["ink_ratio"] = ink_profile["ink_ratio"]

                if ink_profile["is_uniform_blank"] and not assigned_native:
                    cell_patch.close()
                    cell["state"] = CellStatus.EMPTY.value
                    cell["source"] = CellSource.NONE.value
                    cell["confidence"] = float(parsed["structure_score"])
                    cell["needs_review"] = False
                    continue

                prep_cell, pad_box = _prepare_cell_crop_for_ocr(cell_patch)
                cell_patch.close()
                prep_size = prep_cell.size
                try:
                    ocr_res = self.ocr_provider.extract_image(prep_cell)
                finally:
                    prep_cell.close()

                ocr_status = str(ocr_res.get("status", "error"))
                ocr_conf = float(ocr_res.get("confidence", 0.0) or 0.0)
                raw_ocr_text = str(ocr_res.get("text") or "")
                if ocr_status == "provider_unavailable" or VisualPipelineIntegrationAdapter.is_ocr_placeholder_text(raw_ocr_text):
                    raw_ocr_text = ""

                # Preserve multi-line values via word boxes if OCR returned word boxes, else splitlines()
                raw_ocr_wbs = list(ocr_res.get("bounding_boxes") or [])
                if raw_ocr_wbs:
                    bx, by, bw, bh = cell["bbox"]
                    remapped_wbs = self._remap_cell_word_boxes(
                        raw_ocr_wbs,
                        prep_size,
                        pad_box,
                        (bx, by, bx + bw, by + bh),
                        eff_pw,
                        eff_ph,
                        repair_bengali=self.repair_bengali,
                        convert_bangla_digits=self.convert_bangla_digits,
                    )
                    ocr_text, ocr_lines, ocr_repaired = _reconstruct_multiline_text(
                        remapped_wbs,
                        repair_bengali=self.repair_bengali,
                        convert_bangla_digits=self.convert_bangla_digits,
                    )
                else:
                    remapped_wbs = []
                    split_lines = [ln.strip() for ln in raw_ocr_text.splitlines() if ln.strip()]
                    norm_lines: List[str] = []
                    ocr_repaired = False
                    for ln in split_lines:
                        nl, rep = apply_text_normalization(
                            ln,
                            repair_bengali=self.repair_bengali,
                            convert_bangla_digits=self.convert_bangla_digits,
                        )
                        if rep:
                            ocr_repaired = True
                        if nl:
                            norm_lines.append(nl)
                    ocr_lines = norm_lines
                    ocr_text = "\n".join(norm_lines)

                if ocr_repaired:
                    any_cell_repaired = True

                has_ink = float(ink_profile["ink_ratio"]) >= 0.008
                if ocr_status == "provider_unavailable":
                    if has_ink:
                        cell["state"] = CellStatus.UNREADABLE.value
                        cell["needs_review"] = True
                        cell["warnings"].append("ocr_unavailable_on_nonblank_cell")
                    else:
                        cell["state"] = CellStatus.EMPTY.value
                        cell["needs_review"] = False
                    cell["source"] = CellSource.NONE.value
                elif ocr_status == "error" or (ocr_text and ocr_conf < self.config.unreadable_ocr_confidence_cutoff):
                    cell["state"] = CellStatus.UNREADABLE.value
                    cell["text"] = ""
                    cell["lines"] = []
                    cell["source"] = CellSource.OCR_TESSERACT.value
                    cell["confidence"] = round(ocr_conf, 4)
                    cell["needs_review"] = True
                    cell["warnings"].append(
                        f"unreadable_cell_ocr_{ocr_status}_conf_{ocr_conf:.2f}"
                    )
                    any_ocr_used = True
                elif not ocr_text:
                    if has_ink:
                        cell["state"] = CellStatus.UNREADABLE.value
                        cell["needs_review"] = True
                        cell["warnings"].append("inked_cell_empty_ocr_output")
                    else:
                        cell["state"] = CellStatus.EMPTY.value
                        cell["needs_review"] = False
                    cell["source"] = CellSource.OCR_TESSERACT.value if ocr_status != "provider_unavailable" else CellSource.NONE.value
                    cell["confidence"] = round(ocr_conf if has_ink else float(parsed["structure_score"]), 4)
                else:
                    cell["text"] = ocr_text
                    cell["lines"] = ocr_lines
                    cell["state"] = CellStatus.POPULATED.value
                    cell["source"] = CellSource.OCR_TESSERACT.value
                    cell["confidence"] = round(ocr_conf, 4)
                    cell["is_repaired"] = ocr_repaired
                    cell["needs_review"] = bool(
                        ocr_conf < self.config.min_cell_ocr_confidence or ocr_res.get("needs_review", False)
                    )
                    if cell["needs_review"]:
                        cell["warnings"].append(f"low_confidence_cell_ocr_{ocr_conf:.2f}")
                    any_ocr_used = True
                    all_cell_word_boxes.extend(remapped_wbs)

            # Reconstruct matrix, headers, footnotes, HTML, Markdown
            recon = _build_grid_and_reconstructions(
                cells=table_cells,
                occupied=parsed["occupied"],
                num_rows=parsed["num_rows"],
                num_cols=parsed["num_cols"],
                structure_dict=parsed,
            )
            adjacent_footnotes = _collect_adjacent_layout_footnotes(
                crop_geom["table_normalized_box"],
                context_regions or (),
            )
            all_footnotes = list(recon["footnotes"]) + adjacent_footnotes

            validation = validate_table_structure(
                parsed_structure=parsed,
                cells=table_cells,
                unmapped_native_words=unmapped_native,
                min_structure_score=self.config.min_structure_score,
                min_cell_ocr_confidence=self.config.min_cell_ocr_confidence,
            )

            ext_kind = (
                VisualExtractionKind.VECTOR_TABLE
                if (any_native_used and not any_ocr_used)
                else VisualExtractionKind.OCR_LAYOUT
            )
            pop_confs = [
                float(c["confidence"])
                for c in table_cells
                if c.get("state") == CellStatus.POPULATED.value and float(c.get("confidence", 0.0) or 0.0) > 0
            ]
            avg_cell_conf = (sum(pop_confs) / len(pop_confs)) if pop_confs else float(parsed["structure_score"])
            table_conf = max(0.0, min(1.0, round(0.45 * float(parsed["structure_score"]) + 0.55 * avg_cell_conf, 4)))

            md_text = recon["markdown"]
            if all_footnotes:
                fn_lines = "\n".join(f"- *{fn['text']}*" for fn in all_footnotes if fn.get("text"))
                if fn_lines:
                    md_text = f"{md_text}\n\nTable Footnotes:\n{fn_lines}".strip() if md_text else fn_lines

            section_md = format_visual_region_markdown(
                page_number,
                eff_region_id,
                f"Structured Table ({parsed['num_rows']}x{parsed['num_cols']})",
                md_text or f"[Structured table ({eff_region_id}) requires review: zero populated cells]",
            )
            has_merged = any(int(c["rowspan"]) > 1 or int(c["colspan"]) > 1 for c in table_cells)
            elapsed_ms = round((time.time() - t0) * 1000.0, 2)

            return build_visual_region_provenance(
                region_id=eff_region_id,
                region_type=VisualRegionType.TABLE,
                extraction_kind=ext_kind,
                page_number=page_number,
                bbox=crop_geom["table_display_bbox"],
                normalized_box=crop_geom["table_normalized_box"],
                text=md_text,
                markdown=section_md,
                confidence=table_conf,
                engine="slanet_plus",
                engine_version=SLANET_PLUS_MODEL_NAME,
                is_inference=False,
                is_repaired=any_cell_repaired,
                source_asset_name=source_asset_name or f"page_{page_number}:{eff_region_id}",
                word_boxes=all_cell_word_boxes,
                metadata={
                    "layout_category": "table",
                    "raw_label": layout_label,
                    "layout_score": round(float(layout_score), 4) if layout_score is not None else None,
                    "structure_engine": "slanet_plus",
                    "extraction_route": "slanet_plus_table_extractor",
                    "needs_review": bool(validation["needs_review"]),
                    "ocr_triggered": any_ocr_used,
                    "native_text_reused": any_native_used,
                    "elapsed_ms": elapsed_ms,
                    "crop_geometry": {
                        "table_pixel_box": crop_geom["table_pixel_box"],
                        "source_rotation": crop_geom["source_rotation"],
                    },
                    "table_structure": {
                        "num_rows": parsed["num_rows"],
                        "num_cols": parsed["num_cols"],
                        "has_merged_cells": has_merged,
                        "headers": recon["headers"],
                        "header_source": recon["header_source"],
                        "header_row_indices": recon["header_row_indices"],
                        "rows": recon["rows_matrix"],
                        "body_rows": recon["body_rows"],
                        "footnotes": all_footnotes,
                        "cells": table_cells,
                        "cell_counts_by_state": validation["cell_counts_by_state"],
                        "html_structure": recon["html"],
                        "structure_score": round(float(parsed["structure_score"]), 4),
                    },
                    "table_validation": validation,
                },
            )
        finally:
            try:
                crop_img.close()
            except Exception:
                pass

    def _build_fallback_table_region(
        self,
        *,
        region_id: str,
        page_number: int,
        table_norm_box: List[int],
        table_bbox_wh: List[float],
        page_image: Optional[Image.Image],
        native_words: Optional[Sequence[Mapping[str, Any]]],
        fallback_vector_table: Optional[Mapping[str, Any]],
        source_asset_name: str,
        reason: str,
        layout_score: Optional[float],
        layout_label: str,
        crop_geom: Optional[Mapping[str, Any]] = None,
        elapsed_ms: float = 0.0,
    ) -> Dict[str, Any]:
        """Degrades cleanly to vector table or crop OCR without silent invention."""
        if fallback_vector_table and str(fallback_vector_table.get("text") or "").strip():
            fb = dict(fallback_vector_table)
            meta = dict(fb.get("metadata") or {})
            meta.update({
                "structure_fallback_applied": True,
                "fallback_reason": reason,
                "needs_review": False,
            })
            fb["metadata"] = meta
            return fb

        # Check native words first even if SLANet_plus is unavailable
        words_in_table: List[Dict[str, Any]] = []
        ty0, tx0, ty1, tx1 = table_norm_box
        for wb in native_words or ():
            wnb = wb.get("normalized_box")
            if not isinstance(wnb, (list, tuple)) or len(wnb) < 4:
                continue
            cx = (int(wnb[1]) + int(wnb[3])) / 2.0
            cy = (int(wnb[0]) + int(wnb[2])) / 2.0
            if (tx0 - 4) <= cx <= (tx1 + 4) and (ty0 - 4) <= cy <= (ty1 + 4):
                words_in_table.append(dict(wb))

        if words_in_table:
            txt, _, repaired = _reconstruct_multiline_text(
                words_in_table,
                repair_bengali=self.repair_bengali,
                convert_bangla_digits=self.convert_bangla_digits,
            )
            conf = 0.72
            ext_kind = VisualExtractionKind.HEURISTIC_LAYOUT
        else:
            txt = ""
            repaired = False
            conf = 0.25
            ext_kind = VisualExtractionKind.HEURISTIC_LAYOUT
            if page_image is not None and self.ocr_provider.is_available():
                prep, _ = _prepare_cell_crop_for_ocr(page_image)
                try:
                    ocr_res = self.ocr_provider.extract_image(prep)
                finally:
                    prep.close()
                raw_txt = str(ocr_res.get("text") or "")
                if not VisualPipelineIntegrationAdapter.is_ocr_placeholder_text(raw_txt):
                    txt, repaired = apply_text_normalization(
                        raw_txt,
                        repair_bengali=self.repair_bengali,
                        convert_bangla_digits=self.convert_bangla_digits,
                    )
                    conf = max(0.0, min(1.0, float(ocr_res.get("confidence", 0.35) or 0.35)))

        md = format_visual_region_markdown(
            page_number,
            region_id,
            "Table Fallback (Needs Review)",
            txt or f"[Table structure unavailable ({reason}); flagged for human review]",
        )
        return build_visual_region_provenance(
            region_id=region_id,
            region_type=VisualRegionType.TABLE,
            extraction_kind=ext_kind,
            page_number=page_number,
            bbox=table_bbox_wh,
            normalized_box=table_norm_box,
            text=txt,
            markdown=md,
            confidence=conf,
            engine="slanet_plus_fallback",
            engine_version=SLANET_PLUS_MODEL_NAME,
            is_inference=False,
            is_repaired=repaired,
            source_asset_name=source_asset_name or f"page_{page_number}:{region_id}",
            word_boxes=words_in_table,
            metadata={
                "layout_category": "table",
                "raw_label": layout_label,
                "layout_score": round(float(layout_score), 4) if layout_score is not None else None,
                "structure_fallback_applied": True,
                "fallback_reason": reason,
                "needs_review": True,
                "elapsed_ms": elapsed_ms,
                "table_validation": {
                    "is_valid": False,
                    "needs_review": True,
                    "issue_codes": ["structure_recognition_fallback"],
                    "issues": [{"code": "structure_recognition_fallback", "severity": "high", "detail": reason}],
                },
            },
        )
