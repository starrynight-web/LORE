"""
LORE Form Extraction Module using PyMuPDF, OpenCV, and Tesseract OCR.

Deterministic, local-first structured form evidence extraction integrated into
LORE's ingestion pipeline without invoking LLMs or touching Settlement,
Governance, or Knowledge Store responsibilities.

Supports:
- Printed forms, invoices, expense claims, and application forms.
- Checkboxes with explicit ``checked`` / ``unchecked`` / ``unknown`` state classification.
- Radio-style circular selections where visually distinguishable.
- Multi-column spatial key-value mapping, label-value pairs, date, numeric,
  currency, and percentage fields.
- Signature region detection (presence/blankness only; never identifies signers).
- Blank field preservation, original page coordinate + crop provenance,
  handwritten/low-confidence preservation without false certainty, and explicit
  ambiguous-mapping / review warnings.

Strict Non-Inference Rules:
- Never infer document/workflow approval from populated approval fields.
- Never identify a signer from a signature image or stroke scribble.
- Never infer, autocomplete, or fabricate missing/blank values.
- Return structured form evidence only; LORE governance and settlement remain
  responsible for subsequent validation and decisions.
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
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, cast

from PIL import Image

from apps.governance.modes import sanitize_sensitive_data

from .charts import (
    _box_intersection_area,
    _coerce_bool,
    _collect_pymupdf_text_spans,
    _read_setting_or_env,
    _transform_pdf_rect_to_display,
    crop_box_to_page_coords,
    resolve_chart_crop_geometry,
)
from .contracts import (
    VisualExtractionKind,
    VisualPipelineIntegrationAdapter,
    VisualRegionType,
    build_visual_region_provenance,
)
from .ocr import (
    BaseOCRProvider,
    TesseractOCRProvider,
    bangla_to_arabic_digits,
)
from .visual import (
    apply_text_normalization,
    format_visual_region_markdown,
)

logger = logging.getLogger(__name__)

# Optional runtime dependencies (detected gracefully without crashing)
np: Any
try:
    import numpy as _np  # type: ignore

    np = _np
    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore
    HAS_NUMPY = False

cv2: Any
try:
    import cv2 as _cv2  # type: ignore

    cv2 = _cv2
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
class FormDocumentSubtype(str, Enum):
    """Descriptive classification of form-style documents/regions."""

    PRINTED_FORM = "printed_form"
    INVOICE = "invoice"
    EXPENSE_CLAIM = "expense_claim"
    APPLICATION_FORM = "application_form"
    GENERIC_FORM = "generic_form"
    UNKNOWN = "unknown"


class FormFieldDataType(str, Enum):
    """Extracted semantic value type for form fields."""

    TEXT = "text"
    DATE = "date"
    NUMERIC = "numeric"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    BOOLEAN_CHECKBOX = "checkbox"
    RADIO_CHOICE = "radio"
    SIGNATURE_REGION = "signature_region"


class CheckboxState(str, Enum):
    """Visual/symbolic state of a checkbox or radio control."""

    CHECKED = "checked"
    UNCHECKED = "unchecked"
    UNKNOWN = "unknown"


class FormFieldStatus(str, Enum):
    """Extraction certainty/completeness status of a form field."""

    POPULATED = "populated"
    BLANK = "blank"
    CHECKED = "checked"
    UNCHECKED = "unchecked"
    AMBIGUOUS = "ambiguous"
    LOW_CONFIDENCE = "low_confidence"
    UNREADABLE = "unreadable"
    SIGNATURE_PRESENT = "signature_present"
    SIGNATURE_BLANK = "signature_blank"
    UNKNOWN = "unknown"


@dataclass
class FormExtractorConfig:
    """Configuration for deterministic PyMuPDF + OpenCV + Tesseract form extraction."""

    min_ocr_confidence: float = 0.62
    min_resolution_width: int = 160
    min_resolution_height: int = 120
    preserve_crop_image: bool = True
    crop_output_dir: str = ""
    max_embedded_crop_bytes: int = 262144
    enable_targeted_box_ocr: bool = True

    def __post_init__(self) -> None:
        self.min_ocr_confidence = max(0.05, min(0.99, self.min_ocr_confidence))
        self.min_resolution_width = max(40, self.min_resolution_width)
        self.min_resolution_height = max(40, self.min_resolution_height)
        self.max_embedded_crop_bytes = max(16384, self.max_embedded_crop_bytes)
        self.crop_output_dir = (self.crop_output_dir or "").strip()

    @classmethod
    def from_settings_or_env(cls) -> "FormExtractorConfig":
        return cls(
            min_ocr_confidence=float(_read_setting_or_env("FORM_MIN_OCR_CONFIDENCE", 0.62)),
            min_resolution_width=int(_read_setting_or_env("FORM_MIN_RESOLUTION_WIDTH", 160)),
            min_resolution_height=int(_read_setting_or_env("FORM_MIN_RESOLUTION_HEIGHT", 120)),
            preserve_crop_image=_coerce_bool(_read_setting_or_env("FORM_PRESERVE_CROP_IMAGE", True), True),
            crop_output_dir=str(_read_setting_or_env("FORM_CROP_OUTPUT_DIR", "") or ""),
            max_embedded_crop_bytes=int(_read_setting_or_env("FORM_MAX_EMBEDDED_CROP_BYTES", 262144)),
        )


def build_form_crop_reference(
    *,
    crop_img: Image.Image,
    crop_geom: Mapping[str, Any],
    page_number: int,
    region_id: str,
    config: FormExtractorConfig,
    source_asset_name: str = "",
) -> Dict[str, Any]:
    """Creates a content-addressed crop reference and optional PNG artifact for forms."""
    buf = io.BytesIO()
    crop_img.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    sha = hashlib.sha256(png_bytes).hexdigest()
    crop_id = f"p{page_number}-{region_id}-crop-{sha[:12]}"
    ref: Dict[str, Any] = {
        "crop_id": crop_id,
        "crop_ref": f"lore://forms/crops/{crop_id}.png",
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
                logger.debug("Could not persist form crop PNG: %s", sanitize_sensitive_data(str(exc)))
        if len(png_bytes) <= config.max_embedded_crop_bytes:
            ref["crop_image_base64"] = base64.b64encode(png_bytes).decode("ascii")
        else:
            thumb = crop_img.copy()
            thumb.thumbnail((520, 520))
            tbuf = io.BytesIO()
            thumb.save(tbuf, format="PNG")
            thumb.close()
            tbytes = tbuf.getvalue()
            if len(tbytes) <= config.max_embedded_crop_bytes:
                ref["crop_thumbnail_base64"] = base64.b64encode(tbytes).decode("ascii")

    return ref


# ==============================================================================
# FIELD PATTERNS, DOMAIN CUES & SAFETY CLASSIFICATION
# ==============================================================================
_CURRENCY_RE = re.compile(
    r"^\s*([(\+\-]?\s*(?:([$€£¥৳₹])\s*|([A-Z]{3})\s+)(\d[\d,]*(?:\.\d{1,4})?)\s*\)?|"
    r"[(\+\-]?\s*(\d[\d,]*(?:\.\d{1,4})?)\s*(USD|EUR|GBP|BDT|INR|CAD|AUD)\s*\)?)\s*$",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"^\s*([+\-]?\d[\d,]*(?:\.\d+)?)\s*%\s*$")
_PLAIN_NUM_RE = re.compile(r"^\s*([+\-]?\d[\d,]*(?:\.\d+)?)\s*$")
_DATE_ISO_RE = re.compile(r"^\s*(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])\s*$")
_DATE_DMY_MDY_RE = re.compile(r"^\s*(?:0?[1-9]|[12]\d|3[01])[-/.](?:0?[1-9]|1[0-2])[-/.](?:19|20)?\d{2}\s*$")
_DATE_TEXT_RE = re.compile(
    r"^\s*(?:(?:\d{1,2}\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
    r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+(?:19|20)\d{2})?|"
    r"\d{1,2}[- ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*[- ](?:19|20)?\d{2})\s*$",
    re.IGNORECASE,
)
_BLANK_PLACEHOLDER_RE = re.compile(r"^\s*(?:[_\-.~…]{2,}|/\s*/(?:\s*/)?|\[?\s*\]?|N/?A\s+placeholder)\s*$")
_UNDERSCORE_RUN_RE = re.compile(r"_{3,}")
_TEXT_CHECKBOX_RE = re.compile(r"^(?:\[\s*([xX✓✔✗✘ ])\s*\]|([☐☑☒□■]))(?:\s+(.*))?$")
_TEXT_RADIO_RE = re.compile(r"^(?:\(\s*([xX*•●o ])\s*\)|([○●◉◯]))(?:\s+(.*))?$")

_SIGNATURE_LABEL_RE = re.compile(
    r"(?:signature|sign\s*here|applicant\s*sign|claimant\s*sign|authorized\s*sign|"
    r"manager\s*sign|signed\s*by|স্বাক্ষর|সাক্ষর)",
    re.IGNORECASE,
)
_APPROVAL_LABEL_RE = re.compile(
    r"(?:\bapprov(?:ed|al)(?:\s+by|\s+status|\s+date)?\b|\bauthoriz(?:ed|ation)(?:\s+by)?\b|"
    r"\bverif(?:ied|ication)(?:\s+by)?\b|\bsign[-\s]*off\b|\bcleared(?:\s+by)?\b)",
    re.IGNORECASE,
)
_NUMERIC_LABEL_CUE_RE = re.compile(
    r"(?:amount|total|subtotal|tax|vat|gst|fee|price|cost|qty|quantity|hours?|days?|"
    r"miles?|km|balance|due|paid|reimburs|discount|rate|count|age|salary|income)",
    re.IGNORECASE,
)
_DATE_LABEL_CUE_RE = re.compile(
    r"(?:date|dob|birth|issued|expiry|due\s*date|period|তারিখ)",
    re.IGNORECASE,
)
_KNOWN_KEY_NOUN_RE = re.compile(
    r"(?:name|email|phone|tel|mobile|fax|address|city|state|zip|postal|country|id|"
    r"number|no\.?|invoice|receipt|vendor|supplier|claimant|applicant|department|"
    r"role|title|position|date|dob|total|subtotal|tax|amount|balance|terms|"
    r"currency|method|account|bank|project|category|notes|remarks|description|"
    r"approved|approval|status|signature|signed|gender|marital|license)",
    re.IGNORECASE,
)

_SUBTYPE_KEYWORDS: Dict[FormDocumentSubtype, Tuple[str, ...]] = {
    FormDocumentSubtype.INVOICE: (
        "invoice", "bill to", "ship to", "subtotal", "tax", "vat", "gst",
        "total due", "amount due", "payment terms", "po number", "purchase order", "remit",
    ),
    FormDocumentSubtype.EXPENSE_CLAIM: (
        "expense claim", "expense report", "reimbursement", "claimant",
        "mileage", "per diem", "receipt", "cost center", "travel expense",
    ),
    FormDocumentSubtype.APPLICATION_FORM: (
        "application", "applicant", "date of birth", "dob", "marital status",
        "nationality", "position applied", "emergency contact", "declaration", "passport",
    ),
}


def is_signature_label(label: str) -> bool:
    return bool(label and _SIGNATURE_LABEL_RE.search(label))


def is_approval_related_label(label: str) -> bool:
    return bool(label and _APPROVAL_LABEL_RE.search(label))


def _as_box4(box: Sequence[float]) -> Tuple[float, float, float, float]:
    return (box[0], box[1], box[2], box[3])


def _is_blank_placeholder(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return True
    if _BLANK_PLACEHOLDER_RE.match(s):
        return True
    if set(s) <= {"_", "-", ".", " ", "/", "|"} and ("_" in s or "/" in s or "." * 3 in s):
        return True
    return False


def parse_form_field_value(raw_text: str, label: str = "") -> Dict[str, Any]:
    """
    Classifies a form field value without altering exact raw text or fabricating
    missing fields. Never forces identifier/postal/hyphenated strings into numbers.
    """
    raw = (raw_text or "").strip()
    if _is_blank_placeholder(raw):
        return {
            "raw_value": "",
            "field_type": (
                FormFieldDataType.SIGNATURE_REGION.value
                if is_signature_label(label)
                else (FormFieldDataType.DATE.value if _DATE_LABEL_CUE_RE.search(label or "") else FormFieldDataType.TEXT.value)
            ),
            "numeric_value": None,
            "currency": "",
            "unit": "",
            "is_blank": True,
        }

    norm_digits = bangla_to_arabic_digits(raw)

    if is_signature_label(label):
        return {
            "raw_value": raw,
            "field_type": FormFieldDataType.SIGNATURE_REGION.value,
            "numeric_value": None,
            "currency": "",
            "unit": "",
            "is_blank": False,
        }

    m_pct = _PERCENT_RE.match(norm_digits)
    if m_pct:
        try:
            num_val = float(m_pct.group(1).replace(",", ""))
        except ValueError:
            num_val = None
        return {
            "raw_value": raw,
            "field_type": FormFieldDataType.PERCENTAGE.value,
            "numeric_value": num_val,
            "currency": "",
            "unit": "%",
            "is_blank": False,
        }

    m_cur = _CURRENCY_RE.match(norm_digits)
    if m_cur:
        sym = m_cur.group(2) or ""
        code = (m_cur.group(3) or m_cur.group(6) or "").upper()
        num_str = (m_cur.group(4) or m_cur.group(5) or "").replace(",", "")
        neg = norm_digits.lstrip().startswith("(") and norm_digits.rstrip().endswith(")") or norm_digits.lstrip().startswith("-")
        try:
            num_val = float(num_str)
            if neg:
                num_val = -abs(num_val)
        except ValueError:
            num_val = None
        cur_tok = sym or code
        return {
            "raw_value": raw,
            "field_type": FormFieldDataType.CURRENCY.value,
            "numeric_value": num_val,
            "currency": cur_tok,
            "unit": cur_tok,
            "is_blank": False,
        }

    if _DATE_ISO_RE.match(norm_digits) or _DATE_DMY_MDY_RE.match(norm_digits) or _DATE_TEXT_RE.match(norm_digits):
        return {
            "raw_value": raw,
            "field_type": FormFieldDataType.DATE.value,
            "numeric_value": None,
            "currency": "",
            "unit": "",
            "is_blank": False,
        }

    m_num = _PLAIN_NUM_RE.match(norm_digits)
    if m_num:
        # Keep leading-zero IDs/zips (like "02139" or "0041") as text unless label is strongly numeric
        num_token = m_num.group(1).replace(",", "")
        looks_like_code = (
            len(num_token) >= 5
            and num_token.startswith("0")
            and "." not in num_token
            and not _NUMERIC_LABEL_CUE_RE.search(label or "")
        )
        if not looks_like_code:
            try:
                return {
                    "raw_value": raw,
                    "field_type": FormFieldDataType.NUMERIC.value,
                    "numeric_value": float(num_token),
                    "currency": "",
                    "unit": "",
                    "is_blank": False,
                }
            except ValueError:
                pass

    return {
        "raw_value": raw,
        "field_type": FormFieldDataType.TEXT.value,
        "numeric_value": None,
        "currency": "",
        "unit": "",
        "is_blank": False,
    }


def classify_form_subtype(
    full_text: str,
    labels: Sequence[str],
    *,
    has_form_geometry: bool = False,
) -> FormDocumentSubtype:
    """Deterministically classifies form subtype strictly for descriptive metadata."""
    hay = " \n ".join([full_text or "", *labels]).lower()
    scores: Dict[FormDocumentSubtype, int] = {}
    for subtype, kws in _SUBTYPE_KEYWORDS.items():
        scores[subtype] = sum(1 for kw in kws if kw in hay)

    best_type, best_score = max(scores.items(), key=lambda kv: kv[1])
    if best_score >= 2:
        return best_type
    if best_score == 1:
        # Single strong title hit (e.g. "Expense Claim", "Invoice", "Application Form")
        if any(k in hay for k in ("invoice", "expense claim", "expense report", "application form")):
            return best_type
    if len(labels) >= 1 or has_form_geometry:
        return FormDocumentSubtype.PRINTED_FORM
    return FormDocumentSubtype.UNKNOWN


# ==============================================================================
# FORM REGION CANDIDATE DETECTION (PDF & OPENCV RASTER)
# ==============================================================================
def detect_form_candidates_in_pdf_page(
    *,
    pymupdf_page: Any,
    page_number: int,
    table_rects_display: Sequence[Tuple[float, float, float, float]] = (),
    chart_rects_display: Sequence[Tuple[float, float, float, float]] = (),
) -> List[Dict[str, Any]]:
    """
    Detects form regions on a PyMuPDF page using native PDF rectangles/lines/text
    while avoiding duplicate extraction over already-detected table or chart areas.
    """
    if pymupdf_page is None:
        return []

    try:
        disp_rect = pymupdf_page.rect
        pw = float(disp_rect.width)
        ph = float(disp_rect.height)
    except Exception:
        return []
    if pw <= 0 or ph <= 0:
        return []

    # Avoid duplicating areas already covered by table or chart extractors
    excluded_rects = list(table_rects_display) + list(chart_rects_display)

    def _overlaps_excluded(r: Tuple[float, float, float, float]) -> bool:
        ra = max(1.0, (r[2] - r[0]) * (r[3] - r[1]))
        for ex in excluded_rects:
            inter = _box_intersection_area(r, ex)
            ea = max(1.0, (ex[2] - ex[0]) * (ex[3] - ex[1]))
            if inter >= 0.45 * min(ra, ea):
                return True
        return False

    spans = _collect_pymupdf_text_spans(pymupdf_page)
    non_excl_spans = []
    for sp in spans:
        sp_b = sp.get("bbox_display") or sp.get("bbox")
        if sp_b and not _overlaps_excluded(tuple(sp_b)):
            non_excl_spans.append({**sp, "bbox_display": tuple(sp_b)})
    raw_text = "\n".join(str(sp.get("text") or "") for sp in non_excl_spans)

    kv_hits = 0
    checkbox_or_blank_hits = 0
    for sp in non_excl_spans:
        t = str(sp.get("text") or "").strip()
        if not t or "http://" in t.lower() or "https://" in t.lower():
            continue
        if ":" in t and len(t.split(":")[0].split()) <= 5:
            kv_hits += 1
        if _UNDERSCORE_RUN_RE.search(t) or _TEXT_CHECKBOX_RE.match(t) or _TEXT_RADIO_RE.match(t) or is_signature_label(t):
            checkbox_or_blank_hits += 1

    # Count form vector shapes (small checkbox squares, input rectangles, fill underlines)
    form_draw_boxes: List[Tuple[float, float, float, float]] = []
    small_control_boxes = 0
    input_rect_boxes = 0
    try:
        drawings = pymupdf_page.get_drawings() or []
    except Exception:
        drawings = []

    for d in drawings:
        db = _transform_pdf_rect_to_display(d.get("rect"), pymupdf_page)
        if db is None or _overlaps_excluded(db):
            continue
        bw = db[2] - db[0]
        bh = db[3] - db[1]
        if bw > 0.94 * pw and bh > 0.94 * ph:
            continue
        if 6.0 <= bw <= 26.0 and 6.0 <= bh <= 26.0 and 0.72 <= (bw / max(bh, 1.0)) <= 1.38:
            small_control_boxes += 1
            form_draw_boxes.append(db)
        elif bw >= 28.0 and 10.0 <= bh <= 0.25 * ph:
            input_rect_boxes += 1
            form_draw_boxes.append(db)
        elif bw >= 28.0 and bh <= 4.0:
            form_draw_boxes.append(db)

    form_signal = (
        kv_hits >= 2
        or checkbox_or_blank_hits >= 2
        or (kv_hits >= 1 and (small_control_boxes >= 1 or input_rect_boxes >= 1 or checkbox_or_blank_hits >= 1))
        or small_control_boxes >= 2
        or input_rect_boxes >= 2
    )
    if not form_signal:
        return []

    all_boxes = list(form_draw_boxes) + [tuple(sp["bbox_display"]) for sp in non_excl_spans if sp.get("bbox_display")]
    if not all_boxes:
        return []

    fx0 = max(0.0, min(b[0] for b in all_boxes) - 10.0)
    fy0 = max(0.0, min(b[1] for b in all_boxes) - 10.0)
    fx1 = min(pw, max(b[2] for b in all_boxes) + 10.0)
    fy1 = min(ph, max(b[3] for b in all_boxes) + 10.0)
    if (fx1 - fx0) < 40.0 or (fy1 - fy0) < 30.0:
        return []

    bbox_disp_tuple = (round(fx0, 2), round(fy0, 2), round(fx1, 2), round(fy1, 2))
    bbox_disp = list(bbox_disp_tuple)
    if _overlaps_excluded(bbox_disp_tuple) and (
        sum(_box_intersection_area(bbox_disp_tuple, ex) for ex in excluded_rects)
        > 0.65 * ((fx1 - fx0) * (fy1 - fy0))
    ):
        return []

    return [{
        "region_id": f"p{page_number}-form-1",
        "bbox_display": bbox_disp,
        "page_number": page_number,
        "kv_hits": kv_hits,
        "small_control_boxes": small_control_boxes,
        "input_rect_boxes": input_rect_boxes,
        "source_asset_name": f"pdf:page_{page_number}:form_1",
        "preview_text": raw_text[:240],
    }]


def detect_form_regions_opencv(
    image: Image.Image,
    *,
    ocr_text_hint: str = "",
) -> List[Tuple[float, float, float, float]]:
    """
    Detects form-bearing bounding boxes in a raster page using OpenCV geometric
    features (input boxes, horizontal underlines, checkbox squares, radio circles)
    and optional text hints.
    """
    if image is None or image.width < 48 or image.height < 48:
        return []

    img_w, img_h = float(image.width), float(image.height)
    if not HAS_OPENCV or not HAS_NUMPY or cv2 is None or np is None:
        if ocr_text_hint and ("_" * 3 in ocr_text_hint or ":" in ocr_text_hint):
            return [(0.0, 0.0, img_w, img_h)]
        return []

    rgb = image if image.mode == "RGB" else image.convert("RGB")
    try:
        bgr = cv2.cvtColor(np.asarray(rgb, dtype=np.uint8), cv2.COLOR_RGB2BGR)
    finally:
        if rgb is not image:
            rgb.close()

    geom = _detect_form_structure_opencv(bgr, image.width, image.height)
    ctrl_count = (
        len(geom["field_boxes"])
        + len(geom["checkboxes"])
        + len(geom["radio_buttons"])
        + len(geom["underline_slots"])
    )
    has_text_cues = False
    if ocr_text_hint:
        lines = [ln.strip() for ln in ocr_text_hint.splitlines() if ln.strip()]
        kv_cnt = sum(1 for ln in lines if ":" in ln and len(ln.split(":")[0].split()) <= 5)
        has_text_cues = kv_cnt >= 2 or any(_UNDERSCORE_RUN_RE.search(ln) or is_signature_label(ln) for ln in lines)

    if ctrl_count < 2 and not has_text_cues:
        return []

    all_rects: List[Tuple[float, float, float, float]] = []
    for box_list_key in ("field_boxes", "checkboxes", "radio_buttons", "underline_slots"):
        for item in geom[box_list_key]:
            b = item["bbox_crop"]
            all_rects.append((float(b[0]), float(b[1]), float(b[2]), float(b[3])))

    if has_text_cues or not all_rects:
        return [(0.0, 0.0, img_w, img_h)]

    # Expand comfortably around detected controls when form extent is bounded purely by geometry
    pad_x = max(24.0, img_w * 0.10)
    pad_y = max(28.0, img_h * 0.12)
    rx0 = max(0.0, min(r[0] for r in all_rects) - pad_x)
    ry0 = max(0.0, min(r[1] for r in all_rects) - pad_y)
    rx1 = min(img_w, max(r[2] for r in all_rects) + pad_x)
    ry1 = min(img_h, max(r[3] for r in all_rects) + pad_y)
    if (rx1 - rx0) >= 0.72 * img_w and (ry1 - ry0) >= 0.72 * img_h:
        return [(0.0, 0.0, img_w, img_h)]
    return [(round(rx0, 2), round(ry0, 2), round(rx1, 2), round(ry1, 2))]


def is_likely_form_raster_opencv(image: Image.Image, ocr_text_hint: str = "") -> bool:
    return bool(detect_form_regions_opencv(image, ocr_text_hint=ocr_text_hint))


# ==============================================================================
# OPENCV FORM PRIMITIVES: BOXES, UNDERLINES, CHECKBOXES, RADIO CIRCLES & INK
# ==============================================================================
def _estimate_canvas_bg(gray: Any) -> float:
    if np is None:
        return 255.0
    h, w = gray.shape[:2]
    if h < 4 or w < 4:
        return 255.0
    border = np.concatenate([gray[:2, :].ravel(), gray[-2:, :].ravel(), gray[:, :2].ravel(), gray[:, -2:].ravel()])
    p75 = float(np.percentile(gray, 75))
    bmed = float(np.median(border)) if border.size else p75
    return max(bmed, p75)


def _measure_roi_ink(
    gray: Any,
    box_xyxy: Tuple[int, int, int, int],
    *,
    bg_gray: float,
    inset_x: int = 2,
    inset_y: int = 2,
    dark_delta: int = 28,
) -> Dict[str, Any]:
    """Measures clean dark ink density and largest stroke span inside a cropped ROI."""
    assert np is not None and cv2 is not None
    h_img, w_img = gray.shape[:2]
    x0 = max(0, min(w_img, box_xyxy[0] + inset_x))
    y0 = max(0, min(h_img, box_xyxy[1] + inset_y))
    x1 = max(x0, min(w_img, box_xyxy[2] - inset_x))
    y1 = max(y0, min(h_img, box_xyxy[3] - inset_y))
    rw = x1 - x0
    rh = y1 - y0
    if rw < 3 or rh < 3:
        return {
            "ink_ratio": 0.0,
            "max_span_ratio": 0.0,
            "mean_ink_contrast": 0.0,
            "component_count": 0,
            "roi_w": rw,
            "roi_h": rh,
        }

    roi = gray[y0:y1, x0:x1]
    # Use local bright percentile of ROI + page bg so darkened scans stay calibrated
    roi_bg = min(bg_gray, max(120.0, float(np.percentile(roi, 88))))
    dark_diff = np.clip(roi_bg - roi.astype(np.float32), 0.0, 255.0)
    mask = (dark_diff > float(dark_delta)).astype(np.uint8) * 255
    ink_ratio = float(np.mean(mask > 0))
    mean_ink_contrast = float(np.mean(dark_diff[mask > 0])) if np.any(mask > 0) else 0.0

    n_c, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    max_span = 0.0
    sig_comps = 0
    for lbl in range(1, n_c):
        cx, cy, cw, ch, area = [int(v) for v in stats[lbl]]
        if area < 2:
            continue
        sig_comps += 1
        span_r = max(cw / max(float(rw), 1.0), ch / max(float(rh), 1.0))
        if span_r > max_span:
            max_span = span_r

    return {
        "ink_ratio": round(ink_ratio, 4),
        "max_span_ratio": round(max_span, 4),
        "mean_ink_contrast": round(mean_ink_contrast, 2),
        "component_count": sig_comps,
        "roi_w": rw,
        "roi_h": rh,
    }


def _classify_checkbox_roi(gray: Any, bx: int, by: int, bw: int, bh: int, bg_gray: float) -> Dict[str, Any]:
    """Classifies interior of a square checkbox into checked / unchecked / unknown."""
    assert np is not None
    t_x = max(2, min(bw // 3, round(bw * 0.22)))
    t_y = max(2, min(bh // 3, round(bh * 0.22)))
    metrics = _measure_roi_ink(
        gray,
        (bx, by, bx + bw, by + bh),
        bg_gray=bg_gray,
        inset_x=t_x,
        inset_y=t_y,
        dark_delta=28,
    )
    ratio = metrics["ink_ratio"]
    span = metrics["max_span_ratio"]
    ink_contrast = metrics["mean_ink_contrast"]

    # Check border contrast so faint/degraded broken outlines mark unknown cleanly
    top_strip = np.mean(gray[by : min(gray.shape[0], by + max(1, t_y // 2)), bx : bx + bw])
    border_contrast = bg_gray - float(top_strip)
    if border_contrast < 22.0 and ratio > 0.03:
        state = CheckboxState.UNKNOWN
        reason = "low_contrast_or_degraded_checkbox_outline"
    elif ratio <= 0.032 or (ratio <= 0.045 and span < 0.25):
        state = CheckboxState.UNCHECKED
        reason = "clean_empty_interior"
    elif ratio > 0.04 and border_contrast >= 100.0 and ink_contrast < 0.50 * border_contrast:
        state = CheckboxState.UNKNOWN
        reason = "faint_or_smudged_interior_mark"
    elif 0.070 <= ratio <= 0.84 and span >= 0.40:
        state = CheckboxState.CHECKED
        reason = "distinct_check_or_cross_stroke"
    else:
        state = CheckboxState.UNKNOWN
        reason = "ambiguous_smudge_partial_or_overfilled_mark"

    return {
        "state": state,
        "reason": reason,
        "ink_ratio": ratio,
        "max_span_ratio": span,
        "component_count": metrics["component_count"],
    }


def _classify_radio_roi(gray: Any, bx: int, by: int, bw: int, bh: int, bg_gray: float) -> Dict[str, Any]:
    """Classifies concentric center dot inside a circular radio control."""
    assert np is not None
    cx = bx + 0.5 * bw
    cy = by + 0.5 * bh
    r_inner = max(2.0, min(bw, bh) * 0.26)
    x0 = max(0, math.floor(cx - r_inner))
    y0 = max(0, math.floor(cy - r_inner))
    x1 = min(gray.shape[1], math.ceil(cx + r_inner))
    y1 = min(gray.shape[0], math.ceil(cy + r_inner))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return {"state": CheckboxState.UNKNOWN, "reason": "too_small_radio_roi", "ink_ratio": 0.0}

    yy, xx = np.ogrid[y0:y1, x0:x1]
    disk_mask = ((xx + 0.5 - cx) ** 2 + (yy + 0.5 - cy) ** 2) <= (r_inner ** 2)
    roi = gray[y0:y1, x0:x1]
    roi_bg = min(bg_gray, max(120.0, float(np.percentile(gray[by : by + bh, bx : bx + bw], 88))))
    ink = (roi_bg - roi.astype(np.float32)) > 30.0
    denom = max(1, int(np.sum(disk_mask)))
    dot_ratio = round(float(np.sum(ink & disk_mask)) / float(denom), 4)

    if dot_ratio >= 0.28:
        state = CheckboxState.CHECKED
        reason = "solid_center_dot_detected"
    elif dot_ratio <= 0.045:
        state = CheckboxState.UNCHECKED
        reason = "hollow_radio_center"
    else:
        state = CheckboxState.UNKNOWN
        reason = "ambiguous_radio_fill_density"

    return {
        "state": state,
        "reason": reason,
        "ink_ratio": dot_ratio,
    }


def _has_four_square_corners_and_sides(ink_bin: Any, bx: int, by: int, bw: int, bh: int) -> bool:
    """
    Distinguishes true square/rectangular box outlines from letters ('E', 'H', 'S',
    'O', '0', 'D') or circles by requiring continuous 4-sided middle-edge coverage
    plus inked square corners.
    """
    assert np is not None
    patch = ink_bin[by : by + bh, bx : bx + bw] > 0
    if patch.shape[0] < 8 or patch.shape[1] < 8:
        return False
    edge = max(2, min(5, round(min(bw, bh) * 0.16)))

    # Require continuous border spans along the inner 60% of all four sides (eliminates E/H/C/S/A/T/Z glyphs)
    mx0 = max(1, bw // 5)
    mx1 = max(mx0 + 2, (4 * bw) // 5)
    my0 = max(1, bh // 5)
    my1 = max(my0 + 2, (4 * bh) // 5)
    top_cov = float(np.mean(np.any(patch[:edge, mx0:mx1], axis=0)))
    bot_cov = float(np.mean(np.any(patch[-edge:, mx0:mx1], axis=0)))
    left_cov = float(np.mean(np.any(patch[my0:my1, :edge], axis=1)))
    right_cov = float(np.mean(np.any(patch[my0:my1, -edge:], axis=1)))
    if min(top_cov, bot_cov, left_cov, right_cov) < 0.78:
        return False

    c_sz = max(2, min(4, round(min(bw, bh) * 0.18)))
    corners = [
        float(np.mean(patch[:c_sz, :c_sz])),
        float(np.mean(patch[:c_sz, -c_sz:])),
        float(np.mean(patch[-c_sz:, :c_sz])),
        float(np.mean(patch[-c_sz:, -c_sz:])),
    ]
    # Circles/curves have empty corners (<0.20); square boxes have >= 3 corners inked
    return sum(1 for c in corners if c >= 0.28) >= 3 and float(np.mean(corners)) >= 0.30


def _detect_form_structure_opencv(
    crop_bgr: Any,
    crop_w: int,
    crop_h: int,
) -> Dict[str, Any]:
    """
    Detects bordered field rectangles, horizontal fill underlines, checkboxes,
    radio circles, and vertical column dividers using OpenCV.
    """
    out: Dict[str, Any] = {
        "field_boxes": [],
        "underline_slots": [],
        "checkboxes": [],
        "radio_buttons": [],
        "v_dividers_x": [],
        "bg_gray": 255.0,
    }
    if not HAS_OPENCV or not HAS_NUMPY or cv2 is None or np is None:
        return out

    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    bg_gray = _estimate_canvas_bg(gray)
    out["bg_gray"] = round(bg_gray, 2)

    s = max(0.70, min(float(crop_w), float(crop_h)) / 700.0)
    dark_diff = np.clip(bg_gray - gray.astype(np.float32), 0.0, 255.0)
    # Clean binary ink for structural geometry + adaptive mask for degraded contrast scans
    ink_diff = (dark_diff > 28.0).astype(np.uint8) * 255
    block_sz = max(15, round(25 * s) | 1)
    ink_adapt = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, block_sz, 11
    )
    ink_bin = cv2.bitwise_or(ink_diff, cv2.bitwise_and(ink_adapt, (dark_diff > 16.0).astype(np.uint8) * 255))

    # 1. Extract structural horizontal & vertical line masks
    min_hlen = max(24, round(32 * s))
    min_vlen = max(14, round(16 * s))
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (min_hlen, 1))
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_vlen))
    h_mask = cv2.morphologyEx(ink_bin, cv2.MORPH_OPEN, kh)
    v_mask = cv2.morphologyEx(ink_bin, cv2.MORPH_OPEN, kv)

    # Vertical column dividers spanning significant height
    n_vc, _, v_stats, _ = cv2.connectedComponentsWithStats(v_mask, connectivity=8)
    for lbl in range(1, n_vc):
        vx, vy, vw, vh, _ = [int(v) for v in v_stats[lbl]]
        if vw <= max(10, int(10 * s)) and vh >= max(100, round(crop_h * 0.18)):
            cx_v = vx + 0.5 * vw
            if 0.15 * crop_w < cx_v < 0.85 * crop_w:
                out["v_dividers_x"].append(round(cx_v, 2))

    # Horizontal line segments -> potential underlines / borders
    h_segments: List[Tuple[float, float, float, float]] = []
    n_hc, _, h_stats, _ = cv2.connectedComponentsWithStats(h_mask, connectivity=8)
    for lbl in range(1, n_hc):
        hx, hy, hw, hh, _ = [int(v) for v in h_stats[lbl]]
        if hw >= min_hlen and hh <= max(7, round(7 * s)):
            h_segments.append((float(hx), float(hy), float(hx + hw), float(hy + hh)))

    # 2. Field Rectangles from closed H+V grid mask AND clean ink contours
    grid_mask = cv2.dilate(cv2.bitwise_or(h_mask, v_mask), np.ones((3, 3), np.uint8), iterations=1)
    box_cands: List[Tuple[float, float, float, float]] = []
    for mask_src in (grid_mask, ink_bin):
        cnts, _ = cv2.findContours(mask_src, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in cnts:
            bx, by, bw, bh = cv2.boundingRect(cnt)
            if bw < max(42, round(44 * s)) or bh < max(16, round(16 * s)):
                continue
            if bh > int(crop_h * 0.24) or (bw > 0.90 * crop_w and bh > 0.75 * crop_h):
                continue
            peri = cv2.arcLength(cnt, True)
            if peri <= 0:
                continue
            approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
            if len(approx) < 4 or len(approx) > 8:
                continue
            if _has_four_square_corners_and_sides(ink_bin, bx, by, bw, bh):
                box_cands.append((float(bx), float(by), float(bx + bw), float(by + bh)))

    # Deduplicate overlapping field_boxes and drop outer row wrapper if it strictly contains >=2 child boxes
    box_cands.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    dedup_boxes: List[Tuple[float, float, float, float]] = []
    for b in box_cands:
        ba = max(1.0, (b[2] - b[0]) * (b[3] - b[1]))
        if any(
            _box_intersection_area(b, ex) >= 0.72 * min(ba, max(1.0, (ex[2] - ex[0]) * (ex[3] - ex[1])))
            and max((b[2] - b[0]) / max(ex[2] - ex[0], 1.0), (ex[2] - ex[0]) / max(b[2] - b[0], 1.0)) <= 1.25
            for ex in dedup_boxes
        ):
            continue
        dedup_boxes.append(b)

    filtered_boxes: List[Tuple[float, float, float, float]] = []
    for b in dedup_boxes:
        children = [
            ch for ch in dedup_boxes
            if ch != b
            and (ch[2] - ch[0]) * (ch[3] - ch[1]) < 0.85 * ((b[2] - b[0]) * (b[3] - b[1]))
            and _box_intersection_area(ch, b) >= 0.80 * ((ch[2] - ch[0]) * (ch[3] - ch[1]))
        ]
        if len(children) >= 2:
            continue
        filtered_boxes.append(b)

    filtered_boxes.sort(key=lambda b: (round(b[1] / 10.0), b[0]))
    for idx_b, b in enumerate(filtered_boxes, start=1):
        ink_info = _measure_roi_ink(
            gray,
            (int(b[0]), int(b[1]), int(b[2]), int(b[3])),
            bg_gray=bg_gray,
            inset_x=max(3, round(4 * s)),
            inset_y=max(3, round(4 * s)),
            dark_delta=28,
        )
        out["field_boxes"].append({
            "box_id": f"box_{idx_b}",
            "bbox_crop": b,
            "ink_ratio": ink_info["ink_ratio"],
            "component_count": ink_info["component_count"],
        })

    # 3. Underline blank slots (horizontal rules not already top/bottom border of a field box)
    for hs in h_segments:
        hx0, hy0, hx1, hy1 = hs
        hw = hx1 - hx0
        if hw < max(34, round(36 * s)) or hw > 0.70 * crop_w:
            continue
        cy_h = 0.5 * (hy0 + hy1)
        near_box_edge = any(
            (abs(cy_h - b[1]) <= 6.0 or abs(cy_h - b[3]) <= 6.0)
            and min(hx1, b[2]) - max(hx0, b[0]) >= 0.55 * hw
            for b in filtered_boxes
        )
        if near_box_edge:
            continue
        above_ink = _measure_roi_ink(
            gray,
            (int(hx0), max(0, round(hy0 - 28 * s)), int(hx1), max(1, round(hy0 - 2))),
            bg_gray=bg_gray,
            inset_x=2,
            inset_y=1,
            dark_delta=28,
        )
        out["underline_slots"].append({
            "bbox_crop": (hx0, max(0.0, hy0 - 26.0 * s), hx1, hy1),
            "rule_y": round(cy_h, 2),
            "rule_x0": round(hx0, 2),
            "rule_x1": round(hx1, 2),
            "ink_above_ratio": above_ink["ink_ratio"],
        })

    # 4. Checkboxes (square contours) & Radio Buttons (circular contours)
    side_min = max(10, round(10.0 * s))
    side_max = max(44, round(48.0 * s))
    cb_raw: List[Dict[str, Any]] = []
    rb_raw: List[Dict[str, Any]] = []

    cnts_ctrl, _ = cv2.findContours(ink_bin, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in cnts_ctrl:
        bx, by, bw, bh = cv2.boundingRect(cnt)
        if not (side_min <= bw <= side_max and side_min <= bh <= side_max):
            continue
        aspect = float(bw) / max(float(bh), 1.0)
        if not (0.72 <= aspect <= 1.38):
            continue
        peri = cv2.arcLength(cnt, True)
        if peri <= 0:
            continue
        area = cv2.contourArea(cnt)
        approx_sq = cv2.approxPolyDP(cnt, 0.045 * peri, True)
        approx_circ = cv2.approxPolyDP(cnt, 0.025 * peri, True)
        circularity = (4.0 * math.pi * area) / max(peri * peri, 1e-6)

        if _has_four_square_corners_and_sides(ink_bin, bx, by, bw, bh) and 4 <= len(approx_sq) <= 7:
            cls_cb = _classify_checkbox_roi(gray, bx, by, bw, bh, bg_gray)
            cb_raw.append({
                "bbox_crop": (float(bx), float(by), float(bx + bw), float(by + bh)),
                "area": float(bw * bh),
                **cls_cb,
            })
        elif len(approx_circ) >= 7 and circularity >= 0.68 and 0.78 <= aspect <= 1.28:
            # Verify outer border has ink in compass points (not just a solid dot)
            patch = ink_bin[by : by + bh, bx : bx + bw] > 0
            border_pts = [
                np.any(patch[:3, bw // 3 : (2 * bw) // 3]),
                np.any(patch[-3:, bw // 3 : (2 * bw) // 3]),
                np.any(patch[bh // 3 : (2 * bh) // 3, :3]),
                np.any(patch[bh // 3 : (2 * bh) // 3, -3:]),
            ]
            if sum(1 for p in border_pts if p) >= 3:
                cls_rb = _classify_radio_roi(gray, bx, by, bw, bh, bg_gray)
                rb_raw.append({
                    "bbox_crop": (float(bx), float(by), float(bx + bw), float(by + bh)),
                    "area": float(bw * bh),
                    **cls_rb,
                })

    # Keep outer contour for nested duplicate squares/circles
    def _dedup_controls(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        items.sort(key=lambda d: d["area"], reverse=True)
        kept: List[Dict[str, Any]] = []
        for it in items:
            ib = it["bbox_crop"]
            ia = max(1.0, it["area"])
            if any(
                _box_intersection_area(ib, ex["bbox_crop"]) >= 0.45 * min(ia, max(1.0, ex["area"]))
                for ex in kept
            ):
                continue
            kept.append(it)
        kept.sort(key=lambda d: (round(d["bbox_crop"][1] / 12.0), d["bbox_crop"][0]))
        return kept

    out["checkboxes"] = _dedup_controls(cb_raw)
    # Remove any radio candidate overlapping an already accepted square checkbox
    cb_boxes = [c["bbox_crop"] for c in out["checkboxes"]]
    rb_filtered = [
        r for r in _dedup_controls(rb_raw)
        if not any(_box_intersection_area(r["bbox_crop"], cb) > 0.35 * min(r["area"], max(1.0, (cb[2]-cb[0])*(cb[3]-cb[1]))) for cb in cb_boxes)
    ]
    out["radio_buttons"] = rb_filtered
    return out


# ==============================================================================
# TOKEN COLLECTION, TEXT-ONLY CONTROL DETECTION & MULTI-COLUMN LINE SEGMENTATION
# ==============================================================================
def _map_word_boxes_from_ocr_result(
    *,
    ocr_res: Mapping[str, Any],
    target_w: float,
    target_h: float,
    pad_px: int = 0,
    repair_bengali: bool = True,
    convert_bangla_digits: bool = False,
) -> List[Dict[str, Any]]:
    """Maps TesseractOCRProvider word bounding_boxes back to exact crop coordinates."""
    out: List[Dict[str, Any]] = []
    padded_w = target_w + 2.0 * float(pad_px)
    padded_h = target_h + 2.0 * float(pad_px)
    res_w = float(ocr_res.get("width") or padded_w or 1.0)
    res_h = float(ocr_res.get("height") or padded_h or 1.0)
    default_conf = float(ocr_res.get("confidence", 0.0) or 0.0)

    for wb in ocr_res.get("bounding_boxes") or []:
        if not isinstance(wb, Mapping):
            continue
        raw_w = str(wb.get("word") or "").strip()
        if not raw_w:
            continue
        norm_w, _ = apply_text_normalization(
            raw_w, repair_bengali=repair_bengali, convert_bangla_digits=convert_bangla_digits
        )
        if not norm_w:
            continue

        nb = wb.get("normalized_box")
        if isinstance(nb, (list, tuple)) and len(nb) == 4:
            px0 = (float(nb[1]) / 1000.0) * padded_w - pad_px
            py0 = (float(nb[0]) / 1000.0) * padded_h - pad_px
            px1 = (float(nb[3]) / 1000.0) * padded_w - pad_px
            py1 = (float(nb[2]) / 1000.0) * padded_h - pad_px
        else:
            sx = padded_w / max(res_w, 1.0)
            sy = padded_h / max(res_h, 1.0)
            px0 = float(wb.get("x", 0.0) or 0.0) * sx - pad_px
            py0 = float(wb.get("y", 0.0) or 0.0) * sy - pad_px
            px1 = px0 + float(wb.get("w", 0.0) or 0.0) * sx
            py1 = py0 + float(wb.get("h", 0.0) or 0.0) * sy

        x0 = max(0.0, min(target_w, px0))
        y0 = max(0.0, min(target_h, py0))
        x1 = max(x0, min(target_w, px1))
        y1 = max(y0, min(target_h, py1))
        if (x1 - x0) < 1.0 or (y1 - y0) < 1.0:
            continue

        out.append({
            "text": norm_w,
            "bbox_crop": (x0, y0, x1, y1),
            "cx": 0.5 * (x0 + x1),
            "cy": 0.5 * (y0 + y1),
            "width": x1 - x0,
            "height": y1 - y0,
            "confidence": float(wb.get("confidence", default_conf) or default_conf),
            "source": "ocr_tesseract",
        })
    return out


def _collect_crop_text_tokens(
    *,
    crop_img: Image.Image,
    crop_geom: Mapping[str, Any],
    ocr_provider: BaseOCRProvider,
    pymupdf_page: Optional[Any],
    native_words: Optional[Sequence[Mapping[str, Any]]],
    struct_geom: Mapping[str, Any],
    config: FormExtractorConfig,
    repair_bengali: bool,
    convert_bangla_digits: bool,
) -> Dict[str, Any]:
    """
    Collects word tokens from native PDF spans (when present) and/or Tesseract OCR
    (including targeted box OCR for inked form cells missed by full-crop OCR).
    """
    cw = float(crop_img.width)
    ch = float(crop_img.height)
    cl = float(crop_geom.get("crop_left", 0.0) or 0.0)
    ct = float(crop_geom.get("crop_top", 0.0) or 0.0)
    sx = float(crop_geom.get("scale_x", 1.0) or 1.0)
    sy = float(crop_geom.get("scale_y", 1.0) or 1.0)

    def _disp_rect_to_crop(disp_xyxy: Sequence[float]) -> Optional[Tuple[float, float, float, float]]:
        lx0 = disp_xyxy[0] / max(sx, 1e-6) - cl
        ly0 = disp_xyxy[1] / max(sy, 1e-6) - ct
        lx1 = disp_xyxy[2] / max(sx, 1e-6) - cl
        ly1 = disp_xyxy[3] / max(sy, 1e-6) - ct
        x0, x1 = max(0.0, min(cw, min(lx0, lx1))), max(0.0, min(cw, max(lx0, lx1)))
        y0, y1 = max(0.0, min(ch, min(ly0, ly1))), max(0.0, min(ch, max(ly0, ly1)))
        if (x1 - x0) < 1.0 or (y1 - y0) < 1.0:
            return None
        return (x0, y0, x1, y1)

    native_tokens: List[Dict[str, Any]] = []
    if pymupdf_page is not None:
        try:
            words_raw = pymupdf_page.get_text("words") or []
        except Exception:
            words_raw = []
        for w_item in words_raw:
            if len(w_item) < 5:
                continue
            disp_r = _transform_pdf_rect_to_display(w_item[:4], pymupdf_page)
            if disp_r is None:
                continue
            cbox = _disp_rect_to_crop(disp_r)
            if cbox is None:
                continue
            txt, _ = apply_text_normalization(
                str(w_item[4] or "").strip(),
                repair_bengali=repair_bengali,
                convert_bangla_digits=convert_bangla_digits,
            )
            if not txt:
                continue
            native_tokens.append({
                "text": txt,
                "bbox_crop": cbox,
                "cx": 0.5 * (cbox[0] + cbox[2]),
                "cy": 0.5 * (cbox[1] + cbox[3]),
                "width": cbox[2] - cbox[0],
                "height": cbox[3] - cbox[1],
                "confidence": 0.99,
                "source": "native_pdf",
            })

    if not native_tokens and native_words:
        pw = float(crop_geom.get("page_width", cw) or cw)
        ph = float(crop_geom.get("page_height", ch) or ch)
        for nw in native_words:
            txt_raw = str(nw.get("word") or nw.get("text") or "").strip()
            if not txt_raw:
                continue
            nb = nw.get("normalized_box")
            if isinstance(nb, (list, tuple)) and len(nb) == 4:
                disp_r = (
                    (float(nb[1]) / 1000.0) * pw,
                    (float(nb[0]) / 1000.0) * ph,
                    (float(nb[3]) / 1000.0) * pw,
                    (float(nb[2]) / 1000.0) * ph,
                )
            elif all(k in nw for k in ("x", "y", "w", "h")):
                disp_r = (
                    float(nw["x"]),
                    float(nw["y"]),
                    float(nw["x"]) + float(nw["w"]),
                    float(nw["y"]) + float(nw["h"]),
                )
            else:
                continue
            cbox = _disp_rect_to_crop(disp_r)
            if cbox is None:
                continue
            txt, _ = apply_text_normalization(
                txt_raw, repair_bengali=repair_bengali, convert_bangla_digits=convert_bangla_digits
            )
            if not txt:
                continue
            native_tokens.append({
                "text": txt,
                "bbox_crop": cbox,
                "cx": 0.5 * (cbox[0] + cbox[2]),
                "cy": 0.5 * (cbox[1] + cbox[3]),
                "width": cbox[2] - cbox[0],
                "height": cbox[3] - cbox[1],
                "confidence": float(nw.get("confidence", 0.98) or 0.98),
                "source": "native_pdf",
            })

    ocr_triggered = False
    ocr_available = True
    ocr_status = "not_needed"
    ocr_engine = str(getattr(ocr_provider, "engine", "tesseract") or "tesseract")
    ocr_version = str(getattr(ocr_provider, "version", "") or "")
    ocr_lang = str(getattr(ocr_provider, "lang", "") or "")
    ocr_conf = 0.99 if native_tokens else 0.0
    ocr_warnings: List[str] = []
    ocr_tokens: List[Dict[str, Any]] = []
    ocr_full_text = ""

    # Run Tesseract when raster/scanned OR native PDF lacks text tokens
    if not native_tokens:
        ocr_triggered = True
        pad = 16
        padded = Image.new("RGB", (int(cw) + 2 * pad, int(ch) + 2 * pad), (255, 255, 255))
        padded.paste(crop_img, (pad, pad))
        try:
            full_res = ocr_provider.extract_image(padded)
        finally:
            padded.close()

        ocr_status = str(full_res.get("status", "success"))
        ocr_available = ocr_status != "provider_unavailable"
        ocr_engine = str(full_res.get("engine") or ocr_engine)
        ocr_version = str(full_res.get("engine_version") or ocr_version)
        ocr_lang = str(full_res.get("language") or ocr_lang)
        for wm in full_res.get("warnings") or []:
            ws = str(wm or "").strip()
            if ws and ws not in ocr_warnings:
                ocr_warnings.append(ws)
        if full_res.get("error_detail"):
            ew = str(full_res["error_detail"])
            if ew not in ocr_warnings:
                ocr_warnings.append(ew)

        if not ocr_available:
            ocr_conf = 0.0
            ocr_warnings.append("Tesseract OCR binary unavailable; form relies only on structural OpenCV boxes.")
        else:
            raw_t = str(full_res.get("text") or "")
            if VisualPipelineIntegrationAdapter.is_ocr_placeholder_text(raw_t):
                raw_t = ""
            ocr_full_text, _ = apply_text_normalization(
                raw_t, repair_bengali=repair_bengali, convert_bangla_digits=convert_bangla_digits
            )
            ocr_conf = float(full_res.get("confidence", 0.0) or 0.0)
            ocr_tokens = _map_word_boxes_from_ocr_result(
                ocr_res=full_res,
                target_w=cw,
                target_h=ch,
                pad_px=pad,
                repair_bengali=repair_bengali,
                convert_bangla_digits=convert_bangla_digits,
            )

            # Fallback/targeted crop OCR on inked form boxes & unlabelled box left strips
            if config.enable_targeted_box_ocr and struct_geom.get("field_boxes"):
                def _run_subcrop_ocr(sub_rect: Tuple[float, float, float, float], pad_px_sub: int = 12) -> List[Dict[str, Any]]:
                    sx0, sy0, sx1, sy1 = [round(v) for v in sub_rect]
                    sx0 = max(0, min(int(cw), sx0))
                    sy0 = max(0, min(int(ch), sy0))
                    sx1 = max(sx0 + 1, min(int(cw), sx1))
                    sy1 = max(sy0 + 1, min(int(ch), sy1))
                    if (sx1 - sx0) < 12 or (sy1 - sy0) < 10:
                        return []
                    sub_crop = crop_img.crop((sx0, sy0, sx1, sy1))
                    bpadded = Image.new("RGB", (sub_crop.width + 2 * pad_px_sub, sub_crop.height + 2 * pad_px_sub), (255, 255, 255))
                    bpadded.paste(sub_crop, (pad_px_sub, pad_px_sub))
                    sub_crop.close()
                    try:
                        sub_res = ocr_provider.extract_image(bpadded)
                    finally:
                        bpadded.close()
                    mapped = _map_word_boxes_from_ocr_result(
                        ocr_res=sub_res,
                        target_w=float(sx1 - sx0),
                        target_h=float(sy1 - sy0),
                        pad_px=pad_px_sub,
                        repair_bengali=repair_bengali,
                        convert_bangla_digits=convert_bangla_digits,
                    )
                    for st in mapped:
                        lx0, ly0, lx1, ly1 = st["bbox_crop"]
                        nb = (float(sx0) + lx0, float(sy0) + ly0, float(sx0) + lx1, float(sy0) + ly1)
                        st["bbox_crop"] = nb
                        st["cx"] = 0.5 * (nb[0] + nb[2])
                        st["cy"] = 0.5 * (nb[1] + nb[3])
                    return mapped

                for fbox in struct_geom["field_boxes"]:
                    fx0, fy0, fx1, fy1 = [float(v) for v in fbox["bbox_crop"]]
                    # 1) Targeted OCR inside inked form boxes missed by whole-form OCR
                    if float(fbox.get("ink_ratio", 0.0)) >= 0.025 and (fx1 - fx0) >= 24.0 and (fy1 - fy0) >= 14.0:
                        has_tok = any(
                            fx0 - 2.0 <= t["cx"] <= fx1 + 2.0 and fy0 - 2.0 <= t["cy"] <= fy1 + 2.0
                            for t in ocr_tokens
                        )
                        if not has_tok:
                            ocr_tokens.extend(_run_subcrop_ocr((fx0 + 2.0, fy0 + 2.0, fx1 - 2.0, fy1 - 2.0)))

                    # 2) Targeted OCR on left label strip when PSM-3 suppressed a short label beside a wide box
                    if fx0 >= 28.0:
                        lx0 = max(0.0, fx0 - min(220.0, fx0 * 0.95))
                        lx1 = fx0 - 4.0
                        ly0 = max(0.0, fy0 - 8.0)
                        ly1 = min(ch, fy1 + 8.0)
                        has_left_tok = any(
                            lx0 <= t["cx"] <= fx0 and ly0 <= t["cy"] <= ly1
                            for t in ocr_tokens
                        )
                        if not has_left_tok and (lx1 - lx0) >= 20.0:
                            ocr_tokens.extend(_run_subcrop_ocr((lx0, ly0, lx1, ly1)))

    merged_tokens = native_tokens if native_tokens else ocr_tokens
    source_mode = "native_pdf" if (native_tokens and not ocr_tokens) else "raster"
    if native_tokens and struct_geom.get("checkboxes"):
        # Exclude glyph false positives before reporting mixed mode cleanly later
        real_cbs = _prune_false_controls_in_words(struct_geom["checkboxes"], native_tokens)
        if real_cbs:
            source_mode = "mixed"

    return {
        "tokens": merged_tokens,
        "native_tokens_count": len(native_tokens),
        "ocr_tokens_count": len(ocr_tokens),
        "full_text": ocr_full_text or " ".join(t["text"] for t in merged_tokens),
        "source_mode": source_mode,
        "ocr_metadata": {
            "ocr_triggered": ocr_triggered,
            "ocr_available": ocr_available,
            "engine": ocr_engine,
            "engine_version": ocr_version,
            "language": ocr_lang,
            "status": ocr_status,
            "confidence": round(ocr_conf, 4),
            "warnings": ocr_warnings,
        },
    }


def _strip_tokens_inside_controls(
    tokens: Sequence[Mapping[str, Any]],
    checkboxes: Sequence[Mapping[str, Any]],
    radio_buttons: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Filters false-positive OCR artifacts inside drawn checkboxes (e.g. 'x', 'O', '[]')
    and drops OpenCV radio circle false positives sitting inside multi-letter words.
    """
    ctrl_boxes = [c["bbox_crop"] for c in checkboxes] + [r["bbox_crop"] for r in radio_buttons]
    cleaned: List[Dict[str, Any]] = []
    for tk in tokens:
        tb = tk["bbox_crop"]
        txt = str(tk.get("text") or "").strip()
        inside_ctrl = any(
            cb[0] - 4.0 <= tb[0] and tb[2] <= cb[2] + 4.0 and cb[1] - 4.0 <= tb[1] and tb[3] <= cb[3] + 4.0
            for cb in ctrl_boxes
        )
        if inside_ctrl and (
            txt in {"o", "O", "0", "x", "X", "v", "V", "[]", "[ ]", "[x]", "[X]", "©", "®", "☐", "☑", "☒", "○", "●", "◉", "◎", "◯", "✓", "✔"}
            or (len(txt) <= 3 and sum(c.isalnum() for c in txt) <= 1)
        ):
            continue
        cleaned.append(dict(tk))
    return cleaned


def _prune_false_controls_in_words(
    controls: Sequence[Dict[str, Any]],
    tokens: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Removes square/circular contours that are actually letters ('O', 'E', 'H', '0', 'D') inside text words."""
    kept: List[Dict[str, Any]] = []
    for ctrl in controls:
        bx0, by0, bx1, by1 = ctrl["bbox_crop"]
        cx = 0.5 * (bx0 + bx1)
        cy = 0.5 * (by0 + by1)
        bw = bx1 - bx0
        in_word = False
        for tk in tokens:
            tx0, ty0, tx1, ty1 = tk["bbox_crop"]
            txt = str(tk.get("text") or "").strip()
            alnum_count = sum(1 for ch in txt if ch.isalnum())
            if alnum_count >= 2 and (tx0 - 2.0 <= cx <= tx1 + 2.0) and (ty0 - 3.0 <= cy <= ty1 + 3.0):
                # Multi-character word encloses this glyph contour and width isn't a leading '[]'/'()' token
                if bw < (tx1 - tx0) * 0.85:
                    in_word = True
                    break
        if not in_word:
            kept.append(ctrl)
    return kept


def _prune_false_radio_circles_in_words(
    radio_buttons: Sequence[Dict[str, Any]],
    tokens: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Backward-compatible wrapper pruning circular contours inside text words."""
    return _prune_false_controls_in_words(radio_buttons, tokens)


def _segment_row_phrases(tokens: Sequence[Mapping[str, Any]], crop_w: float) -> List[Dict[str, Any]]:
    """
    Groups word tokens into horizontal phrases WITHOUT crossing wide horizontal
    column gutters or form gaps. Distinct X clusters on the same Y line remain
    distinct segments so multi-column forms stay cleanly separated.
    """
    if not tokens:
        return []
    sorted_t = sorted(tokens, key=lambda t: (float(t["cy"]), float(t["bbox_crop"][0])))

    # Cluster into horizontal baseline rows
    rows: List[List[Mapping[str, Any]]] = []
    for tk in sorted_t:
        placed = False
        for row in reversed(rows):
            ref_cy = sum(float(x["cy"]) for x in row) / len(row)
            ref_h = max(8.0, sum(float(x["height"]) for x in row) / len(row))
            if abs(float(tk["cy"]) - ref_cy) <= max(7.0, 0.58 * ref_h):
                row.append(tk)
                placed = True
                break
        if not placed:
            rows.append([tk])

    phrases: List[Dict[str, Any]] = []
    for row in rows:
        row_sorted = sorted(row, key=lambda t: float(t["bbox_crop"][0]))
        sub_groups: List[List[Mapping[str, Any]]] = [[row_sorted[0]]]
        for tk in row_sorted[1:]:
            prev = sub_groups[-1][-1]
            prev_b = prev["bbox_crop"]
            cur_b = tk["bbox_crop"]
            avg_h = max(8.0, 0.5 * (float(prev["height"]) + float(tk["height"])))
            gap_x = float(cur_b[0]) - float(prev_b[2])
            # Conservative word-joining gap keeps separate columns & separate fields intact
            max_word_gap = max(14.0, min(26.0, 1.35 * avg_h))
            # Never join across colon boundaries or distinct underscore runs if wide spacing exists
            if gap_x <= max_word_gap and gap_x >= -4.0:
                sub_groups[-1].append(tk)
            else:
                sub_groups.append([tk])

        for sg in sub_groups:
            bx0 = min(float(t["bbox_crop"][0]) for t in sg)
            by0 = min(float(t["bbox_crop"][1]) for t in sg)
            bx1 = max(float(t["bbox_crop"][2]) for t in sg)
            by1 = max(float(t["bbox_crop"][3]) for t in sg)
            confs = [float(t.get("confidence", 0.0) or 0.0) for t in sg]
            sources = {str(t.get("source", "ocr_tesseract")) for t in sg}
            text_joined = " ".join(str(t["text"]) for t in sg).strip()
            phrases.append({
                "text": text_joined,
                "words": list(sg),
                "bbox_crop": (bx0, by0, bx1, by1),
                "cx": 0.5 * (bx0 + bx1),
                "cy": 0.5 * (by0 + by1),
                "confidence": round(sum(confs) / len(confs), 4) if confs else 0.0,
                "min_confidence": round(min(confs), 4) if confs else 0.0,
                "source": "native_pdf" if sources == {"native_pdf"} else "ocr_tesseract",
            })

    phrases.sort(key=lambda p: (round(p["cy"] / 8.0), p["bbox_crop"][0]))
    return phrases


# ==============================================================================
# MULTI-COLUMN PARTITIONING & SPATIAL KEY-VALUE + CHECKBOX + SIGNATURE ENGINE
# ==============================================================================
def _detect_column_boundaries(
    phrases: Sequence[Mapping[str, Any]],
    v_dividers_x: Sequence[float],
    crop_w: float,
) -> List[Tuple[float, float]]:
    """
    Detects persistent vertical column boundaries (from explicit vertical dividers
    or multi-row whitespace gutters) without splitting narrow single-column forms.
    """
    if crop_w <= 0:
        return [(0.0, 1.0)]

    split_xs: List[float] = sorted(x for x in v_dividers_x if 0.18 * crop_w <= x <= 0.82 * crop_w)
    if not split_xs and len(phrases) >= 4:
        # Check whether significant pairs of phrases share rows on opposite sides of a middle gutter
        mid_lo, mid_hi = crop_w * 0.30, crop_w * 0.72
        row_pairs = 0
        gap_centers: List[float] = []
        # Group phrases by row Y to look for recurring 2-column splits
        y_rows: List[List[Mapping[str, Any]]] = []
        for p in phrases:
            if not y_rows or abs(p["cy"] - y_rows[-1][0]["cy"]) > 10.0:
                y_rows.append([p])
            else:
                y_rows[-1].append(p)

        for r in y_rows:
            if len(r) < 2:
                continue
            r_s = sorted(r, key=lambda x: x["bbox_crop"][0])
            # Look for a middle gap between sub-blocks inside this row
            best_gap = 0.0
            best_mid = None
            for i in range(len(r_s) - 1):
                g_l = float(r_s[i]["bbox_crop"][2])
                g_r = float(r_s[i + 1]["bbox_crop"][0])
                gap_mid = 0.5 * (g_l + g_r)
                if mid_lo <= gap_mid <= mid_hi and (g_r - g_l) >= max(24.0, 0.04 * crop_w):
                    # Verify right side actually contains another label/KV pair rather than single right value
                    right_txt = " ".join(x["text"] for x in r_s[i + 1 :]).strip()
                    left_txt = " ".join(x["text"] for x in r_s[: i + 1]).strip()
                    if (":" in left_txt and ":" in right_txt) or (
                        _KNOWN_KEY_NOUN_RE.search(left_txt) and _KNOWN_KEY_NOUN_RE.search(right_txt) and (g_r - g_l) >= 35.0
                    ):
                        if (g_r - g_l) > best_gap:
                            best_gap = g_r - g_l
                            best_mid = gap_mid
            if best_mid is not None:
                row_pairs += 1
                gap_centers.append(best_mid)

        if row_pairs >= 2 and gap_centers:
            # Verify no single non-header KV phrase spans across the candidate median split
            cand_x = sorted(gap_centers)[len(gap_centers) // 2]
            crossing = sum(
                1 for p in phrases
                if p["bbox_crop"][0] < cand_x - 12.0 and p["bbox_crop"][2] > cand_x + 12.0
                and ":" in p["text"]
            )
            if crossing == 0:
                split_xs = [round(cand_x, 2)]

    # Deduplicate close split lines
    clean_splits: List[float] = []
    for sx in split_xs:
        if not clean_splits or abs(sx - clean_splits[-1]) > 25.0:
            clean_splits.append(sx)

    cols: List[Tuple[float, float]] = []
    prev_x = 0.0
    for sx in clean_splits:
        cols.append((prev_x, sx))
        prev_x = sx
    cols.append((prev_x, crop_w))
    return cols


def _assign_column_index(cx: float, cols: Sequence[Tuple[float, float]]) -> int:
    for idx, (cx0, cx1) in enumerate(cols):
        if cx0 <= cx <= cx1 + 1e-6:
            return idx
    return 0


def _looks_like_field_label(text: str) -> bool:
    s = (text or "").strip()
    if not s or len(s) > 48:
        return False
    if s.endswith(":") or s.endswith("："):
        return True
    if _is_blank_placeholder(s):
        return False
    # Check if string matches common form field nouns without looking like a pure date/money value
    if _CURRENCY_RE.match(s) or _PERCENT_RE.match(s) or _DATE_ISO_RE.match(s) or _DATE_DMY_MDY_RE.match(s):
        return False
    if len(s.split()) <= 5 and _KNOWN_KEY_NOUN_RE.search(s):
        return True
    return False


def _find_rect_to_right_or_below(
    label_box: Tuple[float, float, float, float],
    rects: Sequence[Mapping[str, Any]],
    *,
    col_bounds: Tuple[float, float],
    used_rect_indices: set,
) -> Optional[int]:
    lx0, ly0, lx1, ly1 = label_box
    lcy = 0.5 * (ly0 + ly1)
    best_i = None
    best_dist = 1e9
    for idx, item in enumerate(rects):
        if idx in used_rect_indices:
            continue
        bx0, by0, bx1, by1 = item["bbox_crop"]
        bcx = 0.5 * (bx0 + bx1)
        bcy = 0.5 * (by0 + by1)
        if not (col_bounds[0] - 8.0 <= bcx <= col_bounds[1] + 8.0):
            continue
        # Right on the same row
        if abs(bcy - lcy) <= max(16.0, 0.72 * (by1 - by0)) and -4.0 <= (bx0 - lx1) <= 95.0:
            dist = max(0.0, bx0 - lx1) + abs(bcy - lcy) * 0.5
            if dist < best_dist:
                best_dist = dist
                best_i = idx
        # Immediately below the label caption
        elif (min(lx1, bx1) - max(lx0, bx0)) >= min(20.0, 0.35 * (lx1 - lx0)) and -4.0 <= (by0 - ly1) <= 26.0:
            dist = 20.0 + max(0.0, by0 - ly1)
            if dist < best_dist:
                best_dist = dist
                best_i = idx
    return best_i


def _analyze_signature_roi(
    *,
    gray: Optional[Any],
    bg_gray: float,
    roi_box: Tuple[float, float, float, float],
    tokens_inside: Sequence[Mapping[str, Any]],
    signature_id: str,
    label: str,
    crop_geom: Mapping[str, Any],
    is_header_only: bool = False,
) -> Dict[str, Any]:
    """
    Detects presence vs blankness of handwriting/scribble ink inside a signature
    region strictly WITHOUT attempting OCR or signer identification.
    """
    bx0, by0, bx1, by1 = roi_box
    ink_ratio = 0.0
    max_span = 0.0
    if gray is not None and (bx1 - bx0) >= 12.0 and (by1 - by0) >= 10.0:
        metrics = _measure_roi_ink(
            gray,
            (int(bx0), int(by0), int(bx1), int(by1)),
            bg_gray=bg_gray,
            inset_x=3,
            inset_y=3,
            dark_delta=26,
        )
        ink_ratio = float(metrics["ink_ratio"])
        max_span = float(metrics["max_span_ratio"])

    if is_header_only:
        status = FormFieldStatus.SIGNATURE_BLANK.value
        present = False
    elif ink_ratio >= 0.008 and max_span >= 0.14:
        status = FormFieldStatus.SIGNATURE_PRESENT.value
        present = True
    elif tokens_inside and any(not _is_blank_placeholder(t["text"]) and not is_signature_label(t["text"]) for t in tokens_inside):
        status = FormFieldStatus.SIGNATURE_PRESENT.value
        present = True
    elif ink_ratio >= 0.003:
        status = FormFieldStatus.UNKNOWN.value
        present = False
    else:
        status = FormFieldStatus.SIGNATURE_BLANK.value
        present = False

    coords = crop_box_to_page_coords(roi_box, crop_geom)
    return {
        "signature_id": signature_id,
        "label": label or "Signature",
        "status": status,
        "contains_handwriting_or_mark": present,
        "stroke_ink_ratio": round(ink_ratio, 4),
        "stroke_span_ratio": round(max_span, 4),
        # Hard epistemic safety invariants: never identify signers from signatures
        "signer_identified": False,
        "signer_identity": None,
        "signer_identity_inferred": False,
        "is_authoritative_decision": False,
        "coordinates": coords,
    }


def _reconstruct_controls(
    *,
    phrases: Sequence[Mapping[str, Any]],
    tokens: Sequence[Mapping[str, Any]],
    struct_geom: Mapping[str, Any],
    cols: Sequence[Tuple[float, float]],
    crop_geom: Mapping[str, Any],
    crop_w: float,
    gray: Optional[Any],
    bg_gray: float,
) -> Dict[str, Any]:
    """
    Reconstructs checkboxes and radio-style groups cleanly (combining OpenCV
    geometric controls and Unicode/ASCII textual controls), associates labels,
    and flags ambiguous labelings or unknown marks.
    """
    checkboxes_out: List[Dict[str, Any]] = []
    radio_out: List[Dict[str, Any]] = []
    consumed_phrase_indices: set = set()
    consumed_word_ids: set = set()

    def _pair_control_label(
        ctrl_box: Tuple[float, float, float, float],
        is_radio: bool = False,
    ) -> Tuple[str, Optional[Mapping[str, Any]], bool, str]:
        bx0, by0, bx1, by1 = ctrl_box
        ccx = 0.5 * (bx0 + bx1)
        ccy = 0.5 * (by0 + by1)
        col_i = _assign_column_index(ccx, cols)
        col_l, col_r = cols[col_i]
        other_ctrl_boxes = [
            c["bbox_crop"]
            for c in (struct_geom.get("checkboxes") or []) + (struct_geom.get("radio_buttons") or [])
            if c["bbox_crop"] != ctrl_box
        ]

        def _has_intervening_control(x_left: float, x_right: float) -> bool:
            for ob in other_ctrl_boxes:
                ocy = 0.5 * (ob[1] + ob[3])
                if abs(ocy - ccy) > 18.0:
                    continue
                ocx = 0.5 * (ob[0] + ob[2])
                if x_left - 1.0 < ocx < x_right + 2.0:
                    return True
            return False

        candidates: List[Tuple[float, int, str, Tuple[float, float, float, float]]] = []
        for idx_p, phr in enumerate(phrases):
            if idx_p in consumed_phrase_indices:
                continue
            pb = phr["bbox_crop"]
            txt = str(phr["text"] or "").strip()
            if not txt or _is_blank_placeholder(txt):
                continue
            p_col = _assign_column_index(phr["cx"], cols)
            if p_col != col_i and not (col_l - 12.0 <= phr["cx"] <= col_r + 12.0):
                continue
            if abs(float(phr["cy"]) - ccy) > max(16.0, 0.9 * (pb[3] - pb[1])):
                continue
            dx_right = pb[0] - bx1
            dx_left = bx0 - pb[2]
            if -2.0 <= dx_right <= min(210.0, crop_w * 0.35):
                if _has_intervening_control(bx1, pb[0]):
                    continue
                # Prefer label to the immediate right
                candidates.append((max(0.0, dx_right) + abs(phr["cy"] - ccy) * 0.4, idx_p, "right", pb))
            elif 0.0 <= dx_left <= 65.0 and not is_radio:
                if _has_intervening_control(pb[2], bx0):
                    continue
                # Optional left label ("Approve [ ]") penalized slightly so right label wins
                candidates.append((30.0 + dx_left + abs(phr["cy"] - ccy) * 0.4, idx_p, "left", pb))

        if not candidates:
            return "", None, True, "unlabeled_control_without_adjacent_label"

        candidates.sort(key=lambda c: c[0])
        best_d, best_idx, best_side, _ = candidates[0]
        # Check if second candidate is ambiguously competing at near-identical distance (same side or equidistant)
        is_ambig = False
        ambig_reason = ""
        if len(candidates) >= 2:
            sec_d, sec_idx, sec_side, _ = candidates[1]
            # Equidistant on opposite sides ("Yes [ ] No") or overlapping vertically -> flag ambiguous
            if best_side != sec_side and abs(sec_d - best_d) <= 18.0:
                is_ambig = True
                ambig_reason = (
                    f"equidistant_competing_labels: {phrases[best_idx]['text']!r} vs {phrases[sec_idx]['text']!r}"
                )

        # Avoid consuming full key:value phrase if it also ends with a colon for next field; strip trailing punctuation
        chosen = phrases[best_idx]
        consumed_phrase_indices.add(best_idx)
        for w in chosen.get("words") or []:
            consumed_word_ids.add(id(w))
        return str(chosen["text"]).strip(), chosen, is_ambig, ambig_reason

    # Combine OpenCV checkboxes
    for idx_c, cb in enumerate(struct_geom.get("checkboxes") or [], start=1):
        cbox = _as_box4(cb["bbox_crop"])
        lbl, lbl_phr, lbl_ambig, ambig_why = _pair_control_label(cbox, is_radio=False)
        st = cb["state"]
        st_val = st.value if isinstance(st, CheckboxState) else str(st)
        is_ambig = lbl_ambig or st_val == CheckboxState.UNKNOWN.value
        if st_val == CheckboxState.UNKNOWN.value and not ambig_why:
            ambig_why = str(cb.get("reason") or "ambiguous_checkbox_visual_mark")

        checkboxes_out.append({
            "checkbox_id": f"cb_{idx_c}",
            "label": lbl,
            "state": st_val,
            "detection_method": "opencv_contour",
            "confidence": round(
                min(0.95, float(lbl_phr["confidence"]) if lbl_phr else 0.65)
                if st_val != CheckboxState.UNKNOWN.value
                else 0.35,
                4,
            ),
            "visual_metrics": {
                "ink_ratio": cb.get("ink_ratio", 0.0),
                "max_span_ratio": cb.get("max_span_ratio", 0.0),
                "reason": cb.get("reason", ""),
            },
            "is_ambiguous": is_ambig,
            "ambiguity_reason": ambig_why,
            "is_approval_field": is_approval_related_label(lbl),
            "is_authoritative_decision": False,
            "approval_inferred": False,
            "checkbox_coordinates": crop_box_to_page_coords(cbox, crop_geom),
            "label_coordinates": crop_box_to_page_coords(lbl_phr["bbox_crop"], crop_geom) if lbl_phr else None,
        })

    # Detect symbolic Unicode/ASCII checkboxes in phrases when OpenCV didn't detect an overlapping box
    for idx_p, phr in enumerate(phrases):
        if idx_p in consumed_phrase_indices:
            continue
        txt = str(phr["text"] or "").strip()
        m_cb = _TEXT_CHECKBOX_RE.match(txt)
        if m_cb:
            mark = (m_cb.group(1) or m_cb.group(2) or "").strip()
            lbl = str(m_cb.group(3) or "").strip()
            if mark in {"x", "X", "✓", "✔", "☑", "☒", "■"}:
                st_val = CheckboxState.CHECKED.value
            elif mark in {"", "☐", "□"}:
                st_val = CheckboxState.UNCHECKED.value
            else:
                st_val = CheckboxState.UNKNOWN.value

            # Skip if already matched by OpenCV box near start of phrase
            pb = phr["bbox_crop"]
            if any(
                abs(cb_x - pb[0]) <= 22.0 and abs(cb_y - phr["cy"]) <= 14.0
                for c in checkboxes_out
                for cb_x, cb_y in [(
                    c["checkbox_coordinates"]["local_box"][0],
                    0.5 * (c["checkbox_coordinates"]["local_box"][1] + c["checkbox_coordinates"]["local_box"][3]),
                )]
            ):
                continue

            consumed_phrase_indices.add(idx_p)
            for w in phr.get("words") or []:
                consumed_word_ids.add(id(w))
            checkboxes_out.append({
                "checkbox_id": f"cb_{len(checkboxes_out) + 1}",
                "label": lbl,
                "state": st_val,
                "detection_method": "text_glyph",
                "confidence": round(float(phr["confidence"]), 4),
                "visual_metrics": {"glyph": mark},
                "is_ambiguous": (not lbl) or st_val == CheckboxState.UNKNOWN.value,
                "ambiguity_reason": "unknown_checkbox_glyph" if st_val == CheckboxState.UNKNOWN.value else ("" if lbl else "unlabeled_checkbox"),
                "is_approval_field": is_approval_related_label(lbl),
                "is_authoritative_decision": False,
                "approval_inferred": False,
                "checkbox_coordinates": crop_box_to_page_coords((pb[0], pb[1], min(pb[2], pb[0] + 20.0), pb[3]), crop_geom),
                "label_coordinates": crop_box_to_page_coords(pb, crop_geom),
            })

    # Radio circles from OpenCV
    raw_radios: List[Dict[str, Any]] = []
    for idx_r, rb in enumerate(struct_geom.get("radio_buttons") or [], start=1):
        rbox = _as_box4(rb["bbox_crop"])
        lbl, lbl_phr, lbl_ambig, ambig_why = _pair_control_label(rbox, is_radio=True)
        st = rb["state"]
        st_val = st.value if isinstance(st, CheckboxState) else str(st)
        raw_radios.append({
            "radio_id": f"radio_{idx_r}",
            "label": lbl,
            "state": st_val,
            "detection_method": "opencv_circle",
            "confidence": round(float(lbl_phr["confidence"]) if lbl_phr else 0.60, 4),
            "visual_metrics": {"dot_ink_ratio": rb.get("ink_ratio", 0.0), "reason": rb.get("reason", "")},
            "is_ambiguous": lbl_ambig or st_val == CheckboxState.UNKNOWN.value,
            "ambiguity_reason": ambig_why or (rb.get("reason", "") if st_val == CheckboxState.UNKNOWN.value else ""),
            "_local_box": rbox,
            "radio_coordinates": crop_box_to_page_coords(rbox, crop_geom),
            "label_coordinates": crop_box_to_page_coords(lbl_phr["bbox_crop"], crop_geom) if lbl_phr else None,
        })

    # Group spatially proximate radio buttons into mutual-choice groups
    used_radios = set()
    grp_counter = 0
    for i, r0 in enumerate(raw_radios):
        if i in used_radios:
            continue
        grp_counter += 1
        group_items = [r0]
        used_radios.add(i)
        b0 = r0["_local_box"]
        col0 = _assign_column_index(0.5 * (b0[0] + b0[2]), cols)
        for j, rj in enumerate(raw_radios):
            if j in used_radios:
                continue
            bj = rj["_local_box"]
            if _assign_column_index(0.5 * (bj[0] + bj[2]), cols) != col0:
                continue
            same_row = abs(0.5 * (bj[1] + bj[3]) - 0.5 * (b0[1] + b0[3])) <= 18.0
            stacked_close = abs(0.5 * (bj[0] + bj[2]) - 0.5 * (b0[0] + b0[2])) <= 22.0 and abs(bj[1] - b0[3]) <= 45.0
            if same_row or stacked_close:
                group_items.append(rj)
                used_radios.add(j)

        cleaned_opts = [{k: v for k, v in it.items() if k != "_local_box"} for it in group_items]
        selected = [it["label"] or it["radio_id"] for it in cleaned_opts if it["state"] == CheckboxState.CHECKED.value]
        has_unknown = any(it["state"] == CheckboxState.UNKNOWN.value for it in cleaned_opts)
        grp_ambig = len(selected) > 1 or has_unknown or any(it["is_ambiguous"] for it in cleaned_opts)
        grp_why = ""
        if len(selected) > 1:
            grp_why = f"multiple_radio_options_selected ({', '.join(selected)})"
        elif has_unknown:
            grp_why = "ambiguous_radio_dot_density"
        radio_out.append({
            "group_id": f"rg_{grp_counter}",
            "options": cleaned_opts,
            "selected_options": selected,
            "is_ambiguous": grp_ambig,
            "ambiguity_reason": grp_why,
        })

    return {
        "checkboxes": checkboxes_out,
        "radio_groups": radio_out,
        "consumed_phrase_indices": consumed_phrase_indices,
        "consumed_word_ids": consumed_word_ids,
    }


def _reconstruct_form_kv_and_signatures(
    *,
    phrases: Sequence[Mapping[str, Any]],
    tokens: Sequence[Mapping[str, Any]],
    struct_geom: Mapping[str, Any],
    cols: Sequence[Tuple[float, float]],
    consumed_phrase_indices: Sequence[int],
    crop_geom: Mapping[str, Any],
    crop_w: float,
    crop_h: float,
    gray: Optional[Any],
    bg_gray: float,
    config: FormExtractorConfig,
) -> Dict[str, Any]:
    """
    Deterministic 4-pass spatial KV mapper:
    1. Signature labels & signature boxes/underlines (presence only, never signer ID).
    2. Inline Key: Value or Key: + blank/underline/adjacent box splits.
    3. Boxed field cells and underline blank slots (label left/above/inside/below).
    4. Same-row key-column -> value-column horizontal pairing + ambiguity audit.
    """
    fields: List[Dict[str, Any]] = []
    signatures: List[Dict[str, Any]] = []
    ambiguous_records: List[Dict[str, Any]] = []

    consumed_p = set(consumed_phrase_indices)
    used_fboxes: set = set()
    used_underlines: set = set()
    fboxes = list(struct_geom.get("field_boxes") or [])
    underlines = list(struct_geom.get("underline_slots") or [])

    def _tokens_inside_rect(rx0: float, ry0: float, rx1: float, ry1: float, margin: float = 3.0) -> List[Mapping[str, Any]]:
        return [
            t for t in tokens
            if (rx0 - margin) <= float(t["cx"]) <= (rx1 + margin)
            and (ry0 - margin) <= float(t["cy"]) <= (ry1 + margin)
        ]

    def _make_field(
        *,
        label: str,
        raw_val: str,
        label_box: Optional[Tuple[float, float, float, float]],
        value_box: Optional[Tuple[float, float, float, float]],
        field_box: Tuple[float, float, float, float],
        confidence: float,
        source: str,
        col_idx: int,
        force_ambiguous: bool = False,
        ambiguity_reason: str = "",
        possibly_handwritten: bool = False,
    ) -> Dict[str, Any]:
        parsed = parse_form_field_value(raw_val, label=label)
        is_blank = bool(parsed["is_blank"])
        is_low_conf = (not is_blank) and (confidence < config.min_ocr_confidence)
        if possibly_handwritten and not is_blank and source != "native_pdf":
            is_low_conf = is_low_conf or (confidence < 0.78)

        if force_ambiguous:
            status = FormFieldStatus.AMBIGUOUS.value
            certainty = "uncertain"
        elif is_blank and possibly_handwritten:
            status = FormFieldStatus.UNREADABLE.value
            certainty = "unavailable"
        elif is_blank:
            status = FormFieldStatus.BLANK.value
            certainty = "high" if source == "native_pdf" or confidence >= 0.55 else "uncertain"
        elif is_low_conf:
            status = FormFieldStatus.LOW_CONFIDENCE.value
            certainty = "uncertain"
        else:
            status = FormFieldStatus.POPULATED.value
            certainty = "high"

        is_approval = is_approval_related_label(label)
        fld_entry = {
            "field_id": f"fld_{len(fields) + 1}",
            "label": label,
            "field": label,
            "raw_value": parsed["raw_value"],
            "value": parsed["raw_value"],
            "field_type": parsed["field_type"],
            "numeric_value": parsed["numeric_value"],
            "currency": parsed["currency"],
            "unit": parsed["unit"],
            "status": status,
            "is_blank": is_blank,
            "is_ambiguous": force_ambiguous,
            "ambiguity_reason": ambiguity_reason,
            "is_low_confidence": is_low_conf,
            "possibly_handwritten": possibly_handwritten or is_low_conf,
            "confidence": round(max(0.0, min(1.0, confidence)), 4),
            "certainty": certainty,
            "column_index": col_idx,
            "is_approval_field": is_approval,
            "is_authoritative_decision": False,
            "approval_inferred": False,
            "source": source if not is_blank else "structural_slot",
            "field_coordinates": crop_box_to_page_coords(field_box, crop_geom),
            "label_coordinates": crop_box_to_page_coords(label_box, crop_geom) if label_box else None,
            "value_coordinates": crop_box_to_page_coords(value_box, crop_geom) if value_box else None,
        }
        if force_ambiguous:
            ambiguous_records.append({
                "field_id": fld_entry["field_id"],
                "label": label,
                "raw_value": parsed["raw_value"],
                "reason": ambiguity_reason,
                "field_coordinates": fld_entry["field_coordinates"],
            })
        return fld_entry

    # ------------------------------------------------------------------
    # Pass 1: Signature Regions (presence vs blankness only, never OCR identity)
    # ------------------------------------------------------------------
    for idx_p, phr in enumerate(phrases):
        if idx_p in consumed_p:
            continue
        txt = str(phr["text"] or "").strip()
        # Strip colon/underscores when checking signature cue
        clean_lbl = re.sub(r"[:：_\s]+$", "", txt).strip()
        if not is_signature_label(clean_lbl):
            continue
        # Only treat short field labels or "Signature: ____" as signature regions, not long paragraphs
        if len(clean_lbl.split()) > 6:
            continue

        pb = phr["bbox_crop"]
        col_i = _assign_column_index(phr["cx"], cols)
        col_bounds = cols[col_i]
        consumed_p.add(idx_p)

        # Look for matching signature box or underline (above/right/below)
        sig_roi: Optional[Tuple[float, float, float, float]] = None
        box_i = _find_rect_to_right_or_below(pb, fboxes, col_bounds=col_bounds, used_rect_indices=used_fboxes)
        if box_i is not None:
            used_fboxes.add(box_i)
            sig_roi = _as_box4(fboxes[box_i]["bbox_crop"])
        else:
            # Check underline on same row (to the right) OR directly above signature caption
            best_ul = None
            best_ud = 1e9
            for ui, ul in enumerate(underlines):
                if ui in used_underlines:
                    continue
                ux0, uy0, ux1, uy1 = float(ul["rule_x0"]), float(ul["bbox_crop"][1]), float(ul["rule_x1"]), float(ul["rule_y"])
                ucx = 0.5 * (ux0 + ux1)
                if not (col_bounds[0] - 8.0 <= ucx <= col_bounds[1] + 8.0):
                    continue
                # Underline immediately to right on same baseline
                if abs(uy1 - pb[3]) <= 18.0 and -6.0 <= (ux0 - pb[2]) <= 60.0:
                    d = max(0.0, ux0 - pb[2])
                    if d < best_ud:
                        best_ud = d
                        best_ul = (ui, (ux0, max(0.0, uy1 - 36.0), ux1, max(uy1 - 2.0, uy0 + 6.0)))
                # Caption sits directly below signature underline ("Authorized Signature")
                elif 0.0 <= (pb[1] - uy1) <= 22.0 and (min(pb[2], ux1) - max(pb[0], ux0)) >= 20.0:
                    d = 10.0 + (pb[1] - uy1)
                    if d < best_ud:
                        best_ud = d
                        best_ul = (ui, (ux0, max(0.0, uy1 - 36.0), ux1, max(uy1 - 2.0, uy0 + 6.0)))
            if best_ul is not None:
                used_underlines.add(best_ul[0])
                sig_roi = best_ul[1]

        is_hdr_only = False
        if sig_roi is None:
            # Synthesize immediate right/above signature ROI bounded inside column
            rx_right = min(col_bounds[1] - 4.0, pb[2] + 190.0)
            if (rx_right - pb[2]) >= 48.0:
                sig_roi = (pb[2] + 6.0, max(0.0, pb[1] - 14.0), rx_right, pb[3] + 6.0)
            else:
                sig_roi = pb
                is_hdr_only = True

        # Mark any OCR tokens that happened to land inside signature scribble as consumed so they aren't misread as signer name
        toks_sig = _tokens_inside_rect(*sig_roi, margin=2.0)
        for p2_i, phr2 in enumerate(phrases):
            if p2_i in consumed_p:
                continue
            p2b = phr2["bbox_crop"]
            if _box_intersection_area(p2b, sig_roi) >= 0.45 * max(1.0, (p2b[2] - p2b[0]) * (p2b[3] - p2b[1])):
                if not _looks_like_field_label(phr2["text"]):
                    consumed_p.add(p2_i)

        sig_rec = _analyze_signature_roi(
            gray=gray,
            bg_gray=bg_gray,
            roi_box=sig_roi,
            tokens_inside=[t for t in toks_sig if id(t) not in {id(w) for w in phr.get("words") or []}],
            signature_id=f"sig_{len(signatures) + 1}",
            label=clean_lbl,
            crop_geom=crop_geom,
            is_header_only=is_hdr_only,
        )
        signatures.append(sig_rec)

    # ------------------------------------------------------------------
    # Pass 2: Inline "Label: Value" & "Label: ____" or "Label:" + Right/Box Value
    # ------------------------------------------------------------------
    for idx_p, phr in enumerate(phrases):
        if idx_p in consumed_p:
            continue
        txt = str(phr["text"] or "").strip()
        if not txt or "http://" in txt.lower() or "https://" in txt.lower():
            continue
        if ":" not in txt and "：" not in txt:
            continue

        col_sep = "：" if "：" in txt and (":" not in txt or txt.index("：") < txt.index(":")) else ":"
        left_raw, right_raw = txt.split(col_sep, 1)
        label = left_raw.strip()
        val_raw = right_raw.strip()
        if not label or len(label.split()) > 5:
            continue

        pb = phr["bbox_crop"]
        col_i = _assign_column_index(phr["cx"], cols)
        col_bounds = cols[col_i]
        consumed_p.add(idx_p)

        # Estimate split X inside phrase words
        split_x = pb[0] + (pb[2] - pb[0]) * min(0.8, max(0.2, len(label) / max(len(txt), 1)))
        for w in phr.get("words") or []:
            if col_sep in str(w["text"]):
                split_x = float(w["bbox_crop"][2])
                break
        label_box = (pb[0], pb[1], max(pb[0] + 4.0, split_x), pb[3])

        # Clean trailing/inline underscore placeholders in right_raw
        val_clean = _UNDERSCORE_RUN_RE.sub("", val_raw).strip()
        if val_clean and not _is_blank_placeholder(val_clean):
            vbox = (min(pb[2] - 2.0, split_x + 2.0), pb[1], pb[2], pb[3])
            fields.append(
                _make_field(
                    label=label,
                    raw_val=val_clean,
                    label_box=label_box,
                    value_box=vbox,
                    field_box=pb,
                    confidence=float(phr["min_confidence"]),
                    source=str(phr["source"]),
                    col_idx=col_i,
                    possibly_handwritten=(float(phr["min_confidence"]) < config.min_ocr_confidence),
                )
            )
            continue

        # Right part was blank or underscores -> check paired right/below field_box or same-row value phrase within same column
        matched_val = ""
        matched_vbox: Optional[Tuple[float, float, float, float]] = None
        matched_conf = float(phr["confidence"])
        matched_src = str(phr["source"])
        hand_flag = False
        fbox_full = pb

        box_i = _find_rect_to_right_or_below(pb, fboxes, col_bounds=col_bounds, used_rect_indices=used_fboxes)
        if box_i is not None:
            used_fboxes.add(box_i)
            fb = fboxes[box_i]
            fbox = _as_box4(fb["bbox_crop"])
            fbox_full = (min(pb[0], fbox[0]), min(pb[1], fbox[1]), max(pb[2], fbox[2]), max(pb[3], fbox[3]))
            in_phrases = [
                (j_p, p2) for j_p, p2 in enumerate(phrases)
                if j_p not in consumed_p
                and fbox[0] - 4.0 <= p2["cx"] <= fbox[2] + 4.0
                and fbox[1] - 4.0 <= p2["cy"] <= fbox[3] + 4.0
            ]
            if in_phrases:
                for j_p, _ in in_phrases:
                    consumed_p.add(j_p)
                matched_val = " ".join(p2["text"] for _, p2 in in_phrases).strip()
                matched_vbox = fbox
                matched_conf = min(float(p2["min_confidence"]) for _, p2 in in_phrases)
                matched_src = in_phrases[0][1]["source"]
                hand_flag = matched_conf < config.min_ocr_confidence
            elif float(fb.get("ink_ratio", 0.0)) >= 0.018:
                hand_flag = True
                matched_vbox = fbox
                matched_conf = 0.25
        else:
            # Check same-row value phrase immediately to the right in the same column
            row_vals: List[Tuple[int, Mapping[str, Any]]] = []
            for j_p, p2 in enumerate(phrases):
                if j_p in consumed_p:
                    continue
                if _assign_column_index(p2["cx"], cols) != col_i:
                    continue
                p2b = p2["bbox_crop"]
                if abs(float(p2["cy"]) - float(phr["cy"])) <= max(12.0, 0.75 * (pb[3] - pb[1])):
                    dx = float(p2b[0]) - float(pb[2])
                    if 0.0 <= dx <= min(180.0, (col_bounds[1] - col_bounds[0]) * 0.55):
                        if ":" in p2["text"] or "：" in p2["text"] or _looks_like_field_label(p2["text"]):
                            break
                        row_vals.append((j_p, p2))
            if row_vals:
                row_vals.sort(key=lambda x: x[1]["bbox_crop"][0])
                j_p0, p2_0 = row_vals[0]
                consumed_p.add(j_p0)
                v_clean = _UNDERSCORE_RUN_RE.sub("", p2_0["text"]).strip()
                if v_clean and not _is_blank_placeholder(v_clean):
                    matched_val = v_clean
                    matched_vbox = p2_0["bbox_crop"]
                    matched_conf = float(p2_0["min_confidence"])
                    matched_src = str(p2_0["source"])
                    hand_flag = matched_conf < config.min_ocr_confidence
                    fbox_full = (pb[0], min(pb[1], matched_vbox[1]), matched_vbox[2], max(pb[3], matched_vbox[3]))

            # Consume overlapping underline slot if one exists beside this blank label
            for ui, ul in enumerate(underlines):
                if ui in used_underlines:
                    continue
                if abs(float(ul["rule_y"]) - pb[3]) <= 14.0 and -6.0 <= (ul["rule_x0"] - pb[2]) <= 40.0:
                    used_underlines.add(ui)
                    if not matched_val and float(ul.get("ink_above_ratio", 0.0)) >= 0.025:
                        hand_flag = True
                        matched_vbox = ul["bbox_crop"]
                        matched_conf = 0.25
                    fbox_full = (pb[0], min(pb[1], ul["bbox_crop"][1]), max(pb[2], ul["rule_x1"]), max(pb[3], ul["rule_y"]))
                    break

        fields.append(
            _make_field(
                label=label,
                raw_val=matched_val,
                label_box=label_box,
                value_box=matched_vbox,
                field_box=fbox_full,
                confidence=matched_conf,
                source=matched_src,
                col_idx=col_i,
                possibly_handwritten=hand_flag,
            )
        )

    # ------------------------------------------------------------------
    # Pass 3: Remaining Boxed Cells & Underline Blank Slots + Left/Above Labels
    # ------------------------------------------------------------------
    for box_i, fb in enumerate(fboxes):
        if box_i in used_fboxes:
            continue
        fbox = _as_box4(fb["bbox_crop"])
        col_i = _assign_column_index(0.5 * (fbox[0] + fbox[2]), cols)
        col_bounds = cols[col_i]

        # Phrases inside box vs adjacent labels left/above
        in_p = [
            (j_p, p) for j_p, p in enumerate(phrases)
            if j_p not in consumed_p
            and fbox[0] - 2.0 <= p["cx"] <= fbox[2] + 2.0
            and fbox[1] - 2.0 <= p["cy"] <= fbox[3] + 2.0
        ]
        in_p.sort(key=lambda x: x[1]["cy"])

        # Candidate external labels to the left or immediately above
        ext_labels: List[Tuple[float, int, Mapping[str, Any]]] = []
        for j_p, p in enumerate(phrases):
            if j_p in consumed_p:
                continue
            pb = p["bbox_crop"]
            if _assign_column_index(p["cx"], cols) != col_i:
                continue
            if not _looks_like_field_label(p["text"]):
                continue
            # Left label
            if abs(p["cy"] - 0.5 * (fbox[1] + fbox[3])) <= 18.0 and 0.0 <= (fbox[0] - pb[2]) <= 95.0:
                ext_labels.append((fbox[0] - pb[2], j_p, p))
            # Above label
            elif (min(pb[2], fbox[2]) - max(pb[0], fbox[0])) >= min(20.0, 0.3 * (pb[2] - pb[0])) and 0.0 <= (fbox[1] - pb[3]) <= 26.0:
                ext_labels.append((12.0 + (fbox[1] - pb[3]), j_p, p))

        if len(ext_labels) >= 2 and abs(ext_labels[0][0] - ext_labels[1][0]) <= 14.0:
            # Ambiguous double label competing for a single form box
            _, j_p0, p0 = ext_labels[0]
            _, j_p1, p1 = ext_labels[1]
            consumed_p.add(j_p0)
            consumed_p.add(j_p1)
            for j_p, _ in in_p:
                consumed_p.add(j_p)
            val_txt = " ".join(p["text"] for _, p in in_p).strip()
            fields.append(
                _make_field(
                    label=f"{p0['text']} / {p1['text']}",
                    raw_val=val_txt,
                    label_box=p0["bbox_crop"],
                    value_box=fbox if val_txt else None,
                    field_box=fbox,
                    confidence=min(float(p["min_confidence"]) for _, p in in_p) if in_p else 0.5,
                    source=in_p[0][1]["source"] if in_p else "structural_slot",
                    col_idx=col_i,
                    force_ambiguous=True,
                    ambiguity_reason=f"competing_labels_for_single_box ({p0['text']!r} vs {p1['text']!r})",
                )
            )
            used_fboxes.add(box_i)
            continue

        if ext_labels:
            ext_labels.sort(key=lambda x: x[0])
            _, j_lbl, lbl_p = ext_labels[0]
            consumed_p.add(j_lbl)
            used_fboxes.add(box_i)
            for j_p, _ in in_p:
                consumed_p.add(j_p)
            val_txt = " ".join(p["text"] for _, p in in_p).strip()
            v_conf = min(float(p["min_confidence"]) for _, p in in_p) if in_p else float(lbl_p["confidence"])
            hand_flag = (not in_p and float(fb.get("ink_ratio", 0.0)) >= 0.018) or (
                bool(in_p) and v_conf < config.min_ocr_confidence
            )
            if not in_p and float(fb.get("ink_ratio", 0.0)) >= 0.018:
                v_conf = 0.25
            fields.append(
                _make_field(
                    label=lbl_p["text"].rstrip(":").strip(),
                    raw_val=val_txt,
                    label_box=lbl_p["bbox_crop"],
                    value_box=fbox if (val_txt or hand_flag) else None,
                    field_box=(
                        min(lbl_p["bbox_crop"][0], fbox[0]),
                        min(lbl_p["bbox_crop"][1], fbox[1]),
                        max(lbl_p["bbox_crop"][2], fbox[2]),
                        max(lbl_p["bbox_crop"][3], fbox[3]),
                    ),
                    confidence=v_conf,
                    source=in_p[0][1]["source"] if in_p else "structural_slot",
                    col_idx=col_i,
                    possibly_handwritten=hand_flag,
                )
            )
        elif len(in_p) >= 2 and len(in_p[0][1]["text"].split()) <= 4:
            # Top caption inside box + value row below inside same box
            used_fboxes.add(box_i)
            for j_p, _ in in_p:
                consumed_p.add(j_p)
            lbl_p = in_p[0][1]
            val_txt = " ".join(p["text"] for _, p in in_p[1:]).strip()
            v_conf = min(float(p["min_confidence"]) for _, p in in_p[1:])
            fields.append(
                _make_field(
                    label=lbl_p["text"].rstrip(":").strip(),
                    raw_val=val_txt,
                    label_box=lbl_p["bbox_crop"],
                    value_box=in_p[1][1]["bbox_crop"],
                    field_box=fbox,
                    confidence=v_conf,
                    source=in_p[1][1]["source"],
                    col_idx=col_i,
                    possibly_handwritten=(v_conf < config.min_ocr_confidence),
                )
            )
        elif len(in_p) == 1 and _looks_like_field_label(in_p[0][1]["text"]) and float(fbox[3] - in_p[0][1]["bbox_crop"][3]) >= 12.0:
            # Box contains only a top caption and blank lower half -> blank field preserved
            used_fboxes.add(box_i)
            consumed_p.add(in_p[0][0])
            lbl_p = in_p[0][1]
            fields.append(
                _make_field(
                    label=lbl_p["text"].rstrip(":").strip(),
                    raw_val="",
                    label_box=lbl_p["bbox_crop"],
                    value_box=None,
                    field_box=fbox,
                    confidence=float(lbl_p["confidence"]),
                    source="structural_slot",
                    col_idx=col_i,
                )
            )

    # Underline slots with labels left or immediately below (blank slots & filled lines)
    for ui, ul in enumerate(underlines):
        if ui in used_underlines:
            continue
        ux0, uy0, ux1, uy1 = float(ul["rule_x0"]), float(ul["bbox_crop"][1]), float(ul["rule_x1"]), float(ul["rule_y"])
        col_i = _assign_column_index(0.5 * (ux0 + ux1), cols)
        lbl_cand = None
        for j_p, p in enumerate(phrases):
            if j_p in consumed_p:
                continue
            if _assign_column_index(p["cx"], cols) != col_i:
                continue
            pb = p["bbox_crop"]
            if _is_blank_placeholder(p["text"]):
                continue
            if abs(pb[3] - uy1) <= 14.0 and 0.0 <= (ux0 - pb[2]) <= 65.0 and len(p["text"].split()) <= 5:
                lbl_cand = (j_p, p)
                break
            if 0.0 <= (pb[1] - uy1) <= 22.0 and (min(pb[2], ux1) - max(pb[0], ux0)) >= 20.0 and _looks_like_field_label(p["text"]):
                lbl_cand = (j_p, p)
                break

        if lbl_cand is None:
            continue
        j_lbl, lbl_p = lbl_cand
        consumed_p.add(j_lbl)
        used_underlines.add(ui)

        # Text sitting above underline
        above_p = [
            (j_p, p) for j_p, p in enumerate(phrases)
            if j_p not in consumed_p
            and (ux0 - 6.0) <= p["cx"] <= (ux1 + 6.0)
            and (uy0 - 4.0) <= p["cy"] <= (uy1 + 2.0)
        ]
        for j_p, _ in above_p:
            consumed_p.add(j_p)
        val_txt = _UNDERSCORE_RUN_RE.sub("", " ".join(p["text"] for _, p in above_p)).strip()
        v_conf = min(float(p["min_confidence"]) for _, p in above_p) if above_p else float(lbl_p["confidence"])
        hand_flag = (not above_p and float(ul.get("ink_above_ratio", 0.0)) >= 0.025) or (
            bool(above_p) and v_conf < config.min_ocr_confidence
        )
        if not above_p and float(ul.get("ink_above_ratio", 0.0)) >= 0.025:
            v_conf = 0.25
        fields.append(
            _make_field(
                label=lbl_p["text"].rstrip(":").strip(),
                raw_val=val_txt,
                label_box=lbl_p["bbox_crop"],
                value_box=ul["bbox_crop"] if (val_txt or hand_flag) else None,
                field_box=(min(lbl_p["bbox_crop"][0], ux0), min(lbl_p["bbox_crop"][1], uy0), max(lbl_p["bbox_crop"][2], ux1), max(lbl_p["bbox_crop"][3], uy1)),
                confidence=v_conf,
                source=above_p[0][1]["source"] if above_p else "structural_slot",
                col_idx=col_i,
                possibly_handwritten=hand_flag,
            )
        )

    # ------------------------------------------------------------------
    # Pass 4: Colon-less Label->Value Same-Row Pairs & Ambiguity Check on Remaining Tokens
    # ------------------------------------------------------------------
    # Group remaining phrases by column and row
    for col_i, col_bounds in enumerate(cols):
        rem_in_col = [
            (idx_p, phr) for idx_p, phr in enumerate(phrases)
            if idx_p not in consumed_p
            and _assign_column_index(phr["cx"], cols) == col_i
            and not _is_blank_placeholder(phr["text"])
        ]
        # Pair left-known-label + right-value on same Y row when clear 2-item structure holds
        by_y: List[List[Tuple[int, Mapping[str, Any]]]] = []
        for idx_p, phr in rem_in_col:
            if not by_y or abs(phr["cy"] - by_y[-1][0][1]["cy"]) > 10.0:
                by_y.append([(idx_p, phr)])
            else:
                by_y[-1].append((idx_p, phr))

        for row_items in by_y:
            if len(row_items) == 2:
                (i_l, p_l), (i_r, p_r) = sorted(row_items, key=lambda x: x[1]["bbox_crop"][0])
                if _looks_like_field_label(p_l["text"]) and not _looks_like_field_label(p_r["text"]):
                    consumed_p.add(i_l)
                    consumed_p.add(i_r)
                    v_clean = _UNDERSCORE_RUN_RE.sub("", p_r["text"]).strip()
                    fields.append(
                        _make_field(
                            label=p_l["text"].rstrip(":").strip(),
                            raw_val=v_clean,
                            label_box=p_l["bbox_crop"],
                            value_box=p_r["bbox_crop"] if v_clean else None,
                            field_box=(p_l["bbox_crop"][0], min(p_l["bbox_crop"][1], p_r["bbox_crop"][1]), p_r["bbox_crop"][2], max(p_l["bbox_crop"][3], p_r["bbox_crop"][3])),
                            confidence=float(p_r["min_confidence"]),
                            source=str(p_r["source"]),
                            col_idx=col_i,
                            possibly_handwritten=(float(p_r["min_confidence"]) < config.min_ocr_confidence),
                        )
                    )

    # Check truly orphan values near multiple existing/unclaimed labels or unlabeled short values in mid-form
    unclaimed_labels = [
        (i, p) for i, p in enumerate(phrases)
        if i not in consumed_p and _looks_like_field_label(p["text"]) and (":" in p["text"] or p["bbox_crop"][1] > crop_h * 0.14)
    ]
    unclaimed_vals = [
        (i, p) for i, p in enumerate(phrases)
        if i not in consumed_p
        and not _looks_like_field_label(p["text"])
        and not _is_blank_placeholder(p["text"])
        and p["bbox_crop"][1] > crop_h * 0.14
        and p["bbox_crop"][3] < crop_h * 0.92
    ]
    for iv, pv in unclaimed_vals:
        col_v = _assign_column_index(pv["cx"], cols)
        # Count close candidate labels vertically/horizontally in same column
        near_lbls = []
        for il, pl in unclaimed_labels:
            if _assign_column_index(pl["cx"], cols) != col_v:
                continue
            dy = abs(pl["cy"] - pv["cy"])
            dx = min(abs(pl["bbox_crop"][0] - pv["bbox_crop"][2]), abs(pv["bbox_crop"][0] - pl["bbox_crop"][2]), abs(pl["cx"] - pv["cx"]))
            if dy <= 34.0 and dx <= 160.0:
                near_lbls.append((dy + 0.35 * dx, il, pl))
        # Also detect competing labels from already-extracted fields only if multiple unclaimed labels compete around pv
        if len(near_lbls) >= 2:
            near_lbls.sort(key=lambda x: x[0])
            lbl_names = " / ".join(x[2]["text"].rstrip(":") for x in near_lbls[:2])
            consumed_p.add(iv)
            fields.append(
                _make_field(
                    label=lbl_names,
                    raw_val=pv["text"],
                    label_box=near_lbls[0][2]["bbox_crop"],
                    value_box=pv["bbox_crop"],
                    field_box=pv["bbox_crop"],
                    confidence=float(pv["min_confidence"]),
                    source=str(pv["source"]),
                    col_idx=col_v,
                    force_ambiguous=True,
                    ambiguity_reason=f"value_equidistant_between_multiple_labels ({lbl_names})",
                )
            )
        elif len(near_lbls) == 1 and len(pv["text"].split()) <= 4:
            # Ambiguous stacked label directly above unboxed orphan value? Only bind if strictly aligned vertically, else flag ambiguous
            d0, il0, pl0 = near_lbls[0]
            x_ov = min(pl0["bbox_crop"][2], pv["bbox_crop"][2]) - max(pl0["bbox_crop"][0], pv["bbox_crop"][0])
            if x_ov >= 16.0 and 0.0 <= (pv["bbox_crop"][1] - pl0["bbox_crop"][3]) <= 24.0:
                consumed_p.add(iv)
                consumed_p.add(il0)
                fields.append(
                    _make_field(
                        label=pl0["text"].rstrip(":").strip(),
                        raw_val=pv["text"],
                        label_box=pl0["bbox_crop"],
                        value_box=pv["bbox_crop"],
                        field_box=(min(pl0["bbox_crop"][0], pv["bbox_crop"][0]), pl0["bbox_crop"][1], max(pl0["bbox_crop"][2], pv["bbox_crop"][2]), pv["bbox_crop"][3]),
                        confidence=float(pv["min_confidence"]),
                        source=str(pv["source"]),
                        col_idx=col_v,
                        possibly_handwritten=(float(pv["min_confidence"]) < config.min_ocr_confidence),
                    )
                )

    return {
        "fields": fields,
        "signatures": signatures,
        "ambiguous_records": ambiguous_records,
    }


# ==============================================================================
# VALIDATION & REVIEW FLAGS
# ==============================================================================
def validate_form_extraction(
    *,
    fields: Sequence[Mapping[str, Any]],
    checkboxes: Sequence[Mapping[str, Any]],
    radio_groups: Sequence[Mapping[str, Any]],
    signatures: Sequence[Mapping[str, Any]],
    ambiguous_records: Sequence[Mapping[str, Any]],
    crop_w: int,
    crop_h: int,
    ocr_meta: Mapping[str, Any],
    source_mode: str,
    config: FormExtractorConfig,
) -> Dict[str, Any]:
    """
    Audits extracted form structure and sets explicit review warnings when any
    mapping is ambiguous, low-confidence, incomplete, or low-resolution.
    Never infers approval or fabricates missing fields.
    """
    issues: List[Dict[str, Any]] = []

    def _add(code: str, severity: str, detail: str) -> None:
        if not any(i["code"] == code for i in issues):
            issues.append({"code": code, "severity": severity, "detail": detail})

    if crop_w < config.min_resolution_width or crop_h < config.min_resolution_height:
        _add(
            "low_resolution_form_crop",
            "high",
            f"Form crop resolution {crop_w}x{crop_h} is below reliable threshold {config.min_resolution_width}x{config.min_resolution_height}.",
        )

    if ocr_meta.get("ocr_triggered") and not ocr_meta.get("ocr_available", True):
        _add(
            "ocr_provider_unavailable",
            "high",
            "Tesseract OCR is unavailable for raster/scanned form text.",
        )
    elif ocr_meta.get("ocr_triggered") and str(ocr_meta.get("status", "")) in ("empty_scan", "error"):
        _add(
            "ocr_empty_or_failed",
            "high",
            f"OCR finished with status={ocr_meta.get('status')!r}; form values require manual inspection.",
        )

    total_elements = len(fields) + len(checkboxes) + sum(len(rg.get("options") or []) for rg in radio_groups) + len(signatures)
    if total_elements == 0:
        _add("no_form_fields_detected", "high", "No structured form fields, checkboxes, or signature slots could be reliably detected.")

    low_conf_fields = [f for f in fields if f.get("is_low_confidence")]
    unreadable_fields = [f for f in fields if f.get("status") == FormFieldStatus.UNREADABLE.value]
    blank_fields = [f for f in fields if f.get("is_blank")]
    unknown_cb = [c for c in checkboxes if c.get("state") == CheckboxState.UNKNOWN.value]
    ambig_cb = [c for c in checkboxes if c.get("is_ambiguous") and c.get("state") != CheckboxState.UNKNOWN.value]
    ambig_rg = [rg for rg in radio_groups if rg.get("is_ambiguous")]
    blank_sigs = [s for s in signatures if s.get("status") == FormFieldStatus.SIGNATURE_BLANK.value]
    unk_sigs = [s for s in signatures if s.get("status") == FormFieldStatus.UNKNOWN.value]

    if low_conf_fields or (source_mode != "native_pdf" and ocr_meta.get("ocr_triggered") and float(ocr_meta.get("confidence", 1.0) or 0.0) < config.min_ocr_confidence):
        _add(
            "low_confidence_or_handwritten_values",
            "high",
            f"{len(low_conf_fields)} form field(s) have low OCR confidence or handwritten characteristics (<{config.min_ocr_confidence:.2f}).",
        )

    if unreadable_fields:
        _add(
            "unreadable_handwritten_or_inked_field",
            "high",
            f"{len(unreadable_fields)} field slot(s) contain unparsed handwritten/ink strokes without reliable OCR text.",
        )

    if ambiguous_records or ambig_cb or ambig_rg:
        _add(
            "ambiguous_field_mapping",
            "high",
            f"Ambiguous spatial label/value/control associations detected ({len(ambiguous_records)} field, {len(ambig_cb)} checkbox, {len(ambig_rg)} radio).",
        )

    if unknown_cb or unk_sigs:
        _add(
            "ambiguous_checkbox_or_signature_mark",
            "high",
            f"{len(unknown_cb)} checkbox(es) and {len(unk_sigs)} signature slot(s) have indeterminate visual state.",
        )

    is_complete = (len(blank_fields) == 0 and len(blank_sigs) == 0 and len(unreadable_fields) == 0)
    if not is_complete:
        _add(
            "incomplete_form_fields",
            "medium",
            f"Form has {len(blank_fields)} blank field(s) and {len(blank_sigs)} blank signature region(s); missing values were not inferred.",
        )

    has_high = any(i["severity"] == "high" for i in issues)
    needs_review = has_high or (not is_complete) or len(issues) > 0
    return {
        "is_reliable": (not has_high) and total_elements > 0,
        "is_complete": is_complete,
        "review_required": has_high,
        "needs_review": needs_review,
        "issue_codes": [i["code"] for i in issues],
        "issues": issues,
        "warnings": [i["detail"] for i in issues],
    }


# ==============================================================================
# MAIN FORM EXTRACTOR CLASS
# ==============================================================================
class FormKVExtractor:
    """
    Deterministic Form Extractor using PyMuPDF, OpenCV, and TesseractOCRProvider.

    Plugs cleanly into:
    - ``route_and_extract_region`` / ``PPDocLayoutSProvider`` (``form_extractor=...``)
    - ``PyMuPDFVisualPDFAdapter`` (``form_extractor=...``)
    - ``VisualDocumentExtractor.with_form_extractor(...)``
    """

    engine_name = "pymupdf_opencv_form"

    def __init__(
        self,
        config: Optional[FormExtractorConfig] = None,
        ocr_provider: Optional[BaseOCRProvider] = None,
        repair_bengali: bool = True,
        convert_bangla_digits: bool = False,
    ):
        self.config = config or FormExtractorConfig.from_settings_or_env()
        self.ocr_provider: BaseOCRProvider = ocr_provider or TesseractOCRProvider()
        self.repair_bengali = repair_bengali
        self.convert_bangla_digits = convert_bangla_digits

    @staticmethod
    def is_available() -> bool:
        return HAS_OPENCV or HAS_PYMUPDF

    def extract_form_region(
        self,
        *,
        page_image: Image.Image,
        form_box: Optional[Sequence[float]] = None,
        bbox_format: str = "normalized",
        page_number: int = 1,
        page_width: Optional[float] = None,
        page_height: Optional[float] = None,
        source_rotation: int = 0,
        coords_in_unrotated_space: bool = False,
        region_id: Optional[str] = None,
        layout_score: Optional[float] = None,
        layout_label: str = "form",
        pymupdf_page: Optional[Any] = None,
        native_words: Optional[Sequence[Mapping[str, Any]]] = None,
        source_asset_name: str = "",
        pre_cropped_display_rect: Optional[Sequence[float]] = None,
    ) -> Dict[str, Any]:
        """
        Extracts structured form evidence (fields, blanks, checkboxes, radio groups,
        signature regions, coordinates, and review metadata) for a form crop.
        """
        eff_rid = region_id or f"p{page_number}-form-1"
        crop_img, geom = resolve_chart_crop_geometry(
            page_image=page_image,
            chart_box=form_box,
            bbox_format=bbox_format,
            page_width=page_width,
            page_height=page_height,
            source_rotation=source_rotation,
            coords_in_unrotated_space=coords_in_unrotated_space,
            padding_px=10,
            pre_cropped_display_rect=pre_cropped_display_rect,
        )

        if crop_img is None or not geom:
            pw = float(page_width or getattr(page_image, "width", 1.0) or 1.0)
            ph = float(page_height or getattr(page_image, "height", 1.0) or 1.0)
            return cast(Dict[str, Any], build_visual_region_provenance(
                region_id=eff_rid,
                region_type=VisualRegionType.FORM_KV,
                extraction_kind=VisualExtractionKind.HEURISTIC_LAYOUT,
                page_number=page_number,
                bbox=[0.0, 0.0, pw, ph],
                normalized_box=[0, 0, 1000, 1000],
                text="[Form region crop failed or degenerate bounding box]",
                markdown=format_visual_region_markdown(
                    page_number, eff_rid, "Form Region", "[Degenerate form bounding box; flagged for review]"
                ),
                confidence=0.0,
                engine=self.engine_name,
                engine_version=f"pymupdf-{PYMUPDF_VERSION}_cv2-{OPENCV_VERSION}"[:50],
                is_inference=False,
                is_repaired=False,
                source_asset_name=source_asset_name or f"page_{page_number}:{eff_rid}",
                word_boxes=[],
                metadata={
                    "review_required": True,
                    "needs_review": True,
                    "form_fields": [],
                    "form": {
                        "form_subtype": FormDocumentSubtype.UNKNOWN.value,
                        "is_complete": False,
                        "fields": [],
                        "checkboxes": [],
                        "radio_groups": [],
                        "signature_regions": [],
                    },
                    "form_validation": {
                        "is_reliable": False,
                        "is_complete": False,
                        "review_required": True,
                        "needs_review": True,
                        "issue_codes": ["degenerate_form_crop"],
                        "issues": [{"code": "degenerate_form_crop", "severity": "high", "detail": "Invalid form crop bounds."}],
                    },
                },
            ))

        try:
            cw = crop_img.width
            ch = crop_img.height
            crop_bgr = None
            gray = None
            bg_gray = 255.0
            struct_geom: Dict[str, Any]
            if HAS_OPENCV and HAS_NUMPY and cv2 is not None and np is not None:
                crop_bgr = cv2.cvtColor(np.asarray(crop_img, dtype=np.uint8), cv2.COLOR_RGB2BGR)
                gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
                struct_geom = _detect_form_structure_opencv(crop_bgr, cw, ch)
                bg_gray = float(struct_geom.get("bg_gray", 255.0))
            else:
                struct_geom = {"field_boxes": [], "underline_slots": [], "checkboxes": [], "radio_buttons": [], "v_dividers_x": [], "bg_gray": 255.0}

            tok_out = _collect_crop_text_tokens(
                crop_img=crop_img,
                crop_geom=geom,
                ocr_provider=self.ocr_provider,
                pymupdf_page=pymupdf_page,
                native_words=native_words,
                struct_geom=struct_geom,
                config=self.config,
                repair_bengali=self.repair_bengali,
                convert_bangla_digits=self.convert_bangla_digits,
            )
            raw_tokens = tok_out["tokens"]
            struct_geom["checkboxes"] = _prune_false_controls_in_words(struct_geom.get("checkboxes") or [], raw_tokens)
            struct_geom["radio_buttons"] = _prune_false_controls_in_words(struct_geom.get("radio_buttons") or [], raw_tokens)
            clean_tokens = _strip_tokens_inside_controls(raw_tokens, struct_geom.get("checkboxes") or [], struct_geom.get("radio_buttons") or [])
            phrases = _segment_row_phrases(clean_tokens, float(cw))
            cols = _detect_column_boundaries(phrases, struct_geom.get("v_dividers_x") or [], float(cw))

            ctrl_out = _reconstruct_controls(
                phrases=phrases,
                tokens=clean_tokens,
                struct_geom=struct_geom,
                cols=cols,
                crop_geom=geom,
                crop_w=float(cw),
                gray=gray,
                bg_gray=bg_gray,
            )
            kv_out = _reconstruct_form_kv_and_signatures(
                phrases=phrases,
                tokens=clean_tokens,
                struct_geom=struct_geom,
                cols=cols,
                consumed_phrase_indices=ctrl_out["consumed_phrase_indices"],
                crop_geom=geom,
                crop_w=float(cw),
                crop_h=float(ch),
                gray=gray,
                bg_gray=bg_gray,
                config=self.config,
            )

            fields = kv_out["fields"]
            signatures = kv_out["signatures"]
            checkboxes = ctrl_out["checkboxes"]
            radio_groups = ctrl_out["radio_groups"]
            ambiguous_records = list(kv_out["ambiguous_records"]) + [
                {"control_id": c["checkbox_id"], "label": c["label"], "reason": c["ambiguity_reason"]}
                for c in checkboxes if c.get("is_ambiguous")
            ] + [
                {"group_id": rg["group_id"], "reason": rg["ambiguity_reason"]}
                for rg in radio_groups if rg.get("is_ambiguous")
            ]

            subtype = classify_form_subtype(
                tok_out["full_text"],
                [f["label"] for f in fields] + [c["label"] for c in checkboxes] + [s["label"] for s in signatures],
                has_form_geometry=bool(struct_geom["field_boxes"] or checkboxes or radio_groups or struct_geom["underline_slots"]),
            )
            validation = validate_form_extraction(
                fields=fields,
                checkboxes=checkboxes,
                radio_groups=radio_groups,
                signatures=signatures,
                ambiguous_records=ambiguous_records,
                crop_w=cw,
                crop_h=ch,
                ocr_meta=tok_out["ocr_metadata"],
                source_mode=tok_out["source_mode"],
                config=self.config,
            )

            crop_ref = build_form_crop_reference(
                crop_img=crop_img,
                crop_geom=geom,
                page_number=page_number,
                region_id=eff_rid,
                config=self.config,
                source_asset_name=source_asset_name,
            )

            # Map tokens to page word_boxes contract cleanly
            word_boxes_out: List[Dict[str, Any]] = []
            for t in raw_tokens:
                coords = crop_box_to_page_coords(t["bbox_crop"], geom)
                dx, dy, dw, dh = coords["bbox"]
                word_boxes_out.append({
                    "word": t["text"],
                    "confidence": round(float(t.get("confidence", 0.0) or 0.0), 4),
                    "x": round(dx),
                    "y": round(dy),
                    "w": round(max(1.0, dw)),
                    "h": round(max(1.0, dh)),
                    "normalized_box": coords["normalized_box"],
                })

            blank_fields_summary = [
                {"field_id": f["field_id"], "label": f["label"], "field_coordinates": f["field_coordinates"]}
                for f in fields if f.get("is_blank")
            ]
            counts = {
                "total_fields": len(fields),
                "populated_fields": sum(1 for f in fields if f.get("status") == FormFieldStatus.POPULATED.value),
                "blank_fields": len(blank_fields_summary),
                "ambiguous_fields": len(ambiguous_records),
                "low_confidence_fields": sum(1 for f in fields if f.get("is_low_confidence")),
                "checkboxes_total": len(checkboxes),
                "checkboxes_checked": sum(1 for c in checkboxes if c["state"] == CheckboxState.CHECKED.value),
                "checkboxes_unchecked": sum(1 for c in checkboxes if c["state"] == CheckboxState.UNCHECKED.value),
                "checkboxes_unknown": sum(1 for c in checkboxes if c["state"] == CheckboxState.UNKNOWN.value),
                "radio_groups": len(radio_groups),
                "signature_regions": len(signatures),
            }

            form_payload = {
                "form_subtype": subtype.value,
                "source_mode": tok_out["source_mode"],
                "is_complete": validation["is_complete"],
                "column_count": len(cols),
                "fields": fields,
                "blank_fields": blank_fields_summary,
                "checkboxes": checkboxes,
                "radio_groups": radio_groups,
                "signature_regions": signatures,
                "ambiguous_fields": ambiguous_records,
                "counts": counts,
                "governance_notices": {
                    "approval_inferred": False,
                    "signer_identified": False,
                    "missing_values_inferred": False,
                    "settlement_delegated": True,
                },
                "ocr_text": tok_out["full_text"],
                "raw_tokens_count": len(raw_tokens),
            }

            # Format clear deterministic text/markdown summary
            summary_lines: List[str] = [f"Form Subtype: {subtype.value} | Source: {tok_out['source_mode']} | Columns: {len(cols)}"]
            for f in fields:
                v_disp = f["raw_value"] if not f["is_blank"] else "[BLANK]"
                flags = []
                if f["is_ambiguous"]:
                    flags.append("AMBIGUOUS")
                if f["is_low_confidence"]:
                    flags.append(f"LOW_CONF={f['confidence']:.2f}")
                if f["status"] == FormFieldStatus.UNREADABLE.value:
                    flags.append("UNREADABLE_INK")
                suffix = f" ({', '.join(flags)})" if flags else ""
                summary_lines.append(f"- **{f['label']}**: {v_disp}{suffix}")
            for cb in checkboxes:
                summary_lines.append(f"- Checkbox [{cb['state']}]: {cb['label'] or '[unlabeled]'}")
            for rg in radio_groups:
                opts_s = ", ".join(f"{o['label'] or o['radio_id']}={o['state']}" for o in rg["options"])
                summary_lines.append(f"- Radio ({rg['group_id']}): {opts_s}")
            for sig in signatures:
                summary_lines.append(f"- Signature ({sig['label']}): {sig['status']} [signer_identified=False]")
            if validation["issue_codes"]:
                summary_lines.append(f"[Review Warnings: {', '.join(validation['issue_codes'])}]")

            text_out = "\n".join(summary_lines)
            vis_type = VisualRegionType.SIGNATURE if (layout_label.lower() == "signature" and signatures and not fields) else VisualRegionType.FORM_KV
            ext_kind = (
                VisualExtractionKind.OCR_LAYOUT
                if (tok_out["native_tokens_count"] > 0 or tok_out["ocr_metadata"]["ocr_available"])
                else VisualExtractionKind.HEURISTIC_LAYOUT
            )

            field_confs = [float(f["confidence"]) for f in fields] + [float(c["confidence"]) for c in checkboxes]
            agg_conf = round(sum(field_confs) / len(field_confs), 4) if field_confs else float(tok_out["ocr_metadata"]["confidence"] or 0.5)
            if validation["review_required"]:
                agg_conf = min(agg_conf, 0.58)
            agg_conf = max(0.0, min(1.0, agg_conf))

            compat_form_fields = [
                {
                    "field": f["label"],
                    "value": f["raw_value"],
                    "status": f["status"],
                    "field_type": f["field_type"],
                    "is_blank": f["is_blank"],
                    "confidence": f["confidence"],
                }
                for f in fields
            ]

            source_coords = {
                "page_number": page_number,
                "page_width": float(geom["page_width"]),
                "page_height": float(geom["page_height"]),
                "source_rotation": int(geom["source_rotation"]),
                "display_bbox_xywh": list(geom["chart_display_bbox"]),
                "display_rect_xyxy": list(geom["chart_display_rect"]),
                "pixel_rect_xyxy": list(geom["chart_pixel_box"]),
                "normalized_box": list(geom["chart_normalized_box"]),
                "crop_rect_px": list(geom["crop_rect_px"]),
            }

            return cast(Dict[str, Any], build_visual_region_provenance(
                region_id=eff_rid,
                region_type=vis_type,
                extraction_kind=ext_kind,
                page_number=page_number,
                bbox=list(geom["chart_display_bbox"]),
                normalized_box=list(geom["chart_normalized_box"]),
                text=text_out,
                markdown=format_visual_region_markdown(
                    page_number,
                    eff_rid,
                    f"Form Evidence ({subtype.value})",
                    text_out,
                ),
                confidence=agg_conf,
                engine=self.engine_name,
                engine_version=f"pymupdf-{PYMUPDF_VERSION}_cv2-{OPENCV_VERSION}"[:50],
                is_inference=False,
                is_repaired=bool(tok_out["ocr_metadata"].get("ocr_triggered") and self.repair_bengali),
                source_asset_name=source_asset_name or f"pdf:page_{page_number}:{eff_rid}",
                word_boxes=cast(Any, word_boxes_out),
                metadata={
                    "review_required": validation["review_required"],
                    "needs_review": validation["needs_review"],
                    "form_fields": compat_form_fields,
                    "form": form_payload,
                    "form_validation": validation,
                    "form_crop_reference": crop_ref,
                    "source_coordinates": source_coords,
                    "ocr_metadata": tok_out["ocr_metadata"],
                    "layout_label": layout_label,
                    "layout_score": layout_score,
                },
            ))
        finally:
            crop_bgr = None
            gray = None
            bg_gray = 255.0
            try:
                crop_img.close()
            except Exception:
                pass


# Ergonomic alias consistent with ChartExtractor / SLANetPlusTableExtractor
FormExtractor = FormKVExtractor

__all__ = [
    "HAS_NUMPY",
    "HAS_OPENCV",
    "HAS_PYMUPDF",
    "OPENCV_VERSION",
    "CheckboxState",
    "FormDocumentSubtype",
    "FormExtractor",
    "FormExtractorConfig",
    "FormFieldDataType",
    "FormFieldStatus",
    "FormKVExtractor",
    "build_form_crop_reference",
    "classify_form_subtype",
    "detect_form_candidates_in_pdf_page",
    "detect_form_regions_opencv",
    "is_approval_related_label",
    "is_likely_form_raster_opencv",
    "is_signature_label",
    "parse_form_field_value",
    "validate_form_extraction",
]

