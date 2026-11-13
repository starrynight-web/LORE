"""
LORE Enterprise — Visual Extraction JSON Schema v1 (lore.visual/1.0)
====================================================================

Strict Pydantic v2 contract representing structured visual extraction evidence
produced by LORE Visual Extraction pipelines (PDF/OCR, PP-DocLayout-S,
SLANet_plus tables, PyMuPDF+OpenCV charts, and deterministic forms).

Architectural Isolation Contract:
- Strictly an extraction-evidence contract (``lore.visual/1.0``).
- NEVER replaces, modifies, or emits LORE Governance / Canonical Answer
  verdicts (``lore.result/1`` or ``lore.result/2`` in ``apps/governance/contract.py``).
- Preserves nullable fields when values, headers, cell text, or confidence scores
  are unavailable or uncertain — never fabricates confidence or missing data.
- Enforces strict scalar typing, coordinate bounds, page references,
  schema-version checks, deterministic JSON serialization, and
  backward-compatible minor-version evolution within major schema ``1.x``.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from enum import Enum
from typing import (
    Annotated,
    Any,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
)

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    Tag,
    model_validator,
)

# Canonical 0..1000 scale matches LORE DigitalPDFExtractor, TesseractOCRProvider, and contracts.py
CANONICAL_COORDINATE_SCALE: int = 1000


# ==============================================================================
# SCHEMA VERSION CONSTANTS & VALIDATION
# ==============================================================================
VISUAL_SCHEMA_NAMESPACE: str = "lore.visual"
VISUAL_SCHEMA_MAJOR: int = 1
VISUAL_SCHEMA_MINOR: int = 0
VISUAL_SCHEMA_ID: str = f"{VISUAL_SCHEMA_NAMESPACE}/{VISUAL_SCHEMA_MAJOR}.{VISUAL_SCHEMA_MINOR}"

_SCHEMA_VERSION_RE = re.compile(r"^lore\.visual/(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$")

E = TypeVar("E", bound=Enum)


class VisualSchemaEvolutionError(ValueError):
    """Raised when a visual payload carries an incompatible or malformed schema version."""


def parse_visual_schema_version(schema_version: Any) -> Tuple[int, int]:
    """
    Validate and parse a LORE Visual Schema version identifier (e.g. ``lore.visual/1.0``).
    Rejects non-strings, governance envelopes (``lore.result/*``), malformed tags,
    and incompatible major versions (!= 1).
    """
    if type(schema_version) is not str:
        raise VisualSchemaEvolutionError(
            f"schema_version must be a string, got {type(schema_version).__name__}"
        )
    m = _SCHEMA_VERSION_RE.match(schema_version)
    if not m:
        raise VisualSchemaEvolutionError(
            f"Invalid schema_version {schema_version!r}. Expected format 'lore.visual/<major>.<minor>' (canonical: {VISUAL_SCHEMA_ID!r})."
        )
    major = int(m.group(1))
    minor = int(m.group(2))
    if major != VISUAL_SCHEMA_MAJOR:
        raise VisualSchemaEvolutionError(
            f"Unsupported visual schema major version {major} in {schema_version!r}; supported major version is {VISUAL_SCHEMA_MAJOR}."
        )
    return major, minor


# ==============================================================================
# STRICT PRIMITIVE & ENUM ANNOTATIONS
# ==============================================================================
def _ensure_non_blank_str(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be empty or whitespace-only")
    return value


def _strict_enum_validator(enum_cls: Type[E]):
    def _validate(value: Any) -> E:
        if isinstance(value, enum_cls):
            return value
        if type(value) is str:
            return enum_cls(value)
        raise ValueError(
            f"Expected {enum_cls.__name__} or str, got {type(value).__name__}"
        )

    return BeforeValidator(_validate)


def _validate_iso_datetime(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if type(value) is str:
        if not value.strip():
            raise ValueError("datetime string must not be empty")
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid ISO-8601 timestamp {value!r}") from exc
        return value
    raise ValueError(f"Expected datetime or ISO-8601 string, got {type(value).__name__}")


NonBlankStr = Annotated[StrictStr, AfterValidator(_ensure_non_blank_str)]
StrictFiniteFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]
StrictFiniteNumber = Union[StrictInt, StrictFiniteFloat]
ConfidenceScore = Annotated[StrictFloat, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
PositivePageInt = Annotated[StrictInt, Field(ge=1)]
NonNegInt = Annotated[StrictInt, Field(ge=0)]
NonNegNumber = Union[NonNegInt, Annotated[StrictFloat, Field(ge=0.0, allow_inf_nan=False)]]
StrictISOTimestamp = Annotated[Union[datetime, StrictStr], BeforeValidator(_validate_iso_datetime)]


# ==============================================================================
# CANONICAL SCHEMA ENUMS
# ==============================================================================
class CoordinateSpace(str, Enum):
    NORMALIZED_1000 = "normalized_1000"
    NORMALIZED_0_1 = "normalized_0_1"
    PAGE_POINTS = "page_points"
    PIXELS = "pixels"


class VisualElementType(str, Enum):
    TEXT = "text"
    TITLE_HEADING = "title_heading"
    PARAGRAPH = "paragraph"
    HEADER_FOOTER = "header_footer"
    TABLE = "table"
    CHART = "chart"
    FORM = "form"
    FORM_KV = "form_kv"
    FIGURE = "figure"
    DIAGRAM = "diagram"
    EMBEDDED_IMAGE = "embedded_image"
    SVG_GRAPHIC = "svg_graphic"
    STAMP_OR_SEAL = "stamp_or_seal"
    SIGNATURE = "signature"
    PAGE_SNAPSHOT = "page_snapshot"
    UNKNOWN = "unknown"


class ValidationStatus(str, Enum):
    VALID = "valid"
    NEEDS_REVIEW = "needs_review"
    AMBIGUOUS = "ambiguous"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


class WarningSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SourceMode(str, Enum):
    NATIVE_PDF = "native_pdf"
    OCR = "ocr"
    VECTOR = "vector"
    RASTER = "raster"
    MIXED = "mixed"
    HEURISTIC = "heuristic"
    STRUCTURAL_SLOT = "structural_slot"
    HYBRID = "hybrid"
    FALLBACK = "fallback"
    UNAVAILABLE = "unavailable"


class TextRole(str, Enum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    HEADER = "header"
    FOOTER = "footer"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    LIST_ITEM = "list_item"
    UNKNOWN = "unknown"


class TableCellStatus(str, Enum):
    POPULATED = "populated"
    EMPTY = "empty"
    UNREADABLE = "unreadable"
    MISSING = "missing"
    UNKNOWN = "unknown"


class ChartType(str, Enum):
    VERTICAL_BAR = "vertical_bar"
    HORIZONTAL_BAR = "horizontal_bar"
    GROUPED_BAR = "grouped_bar"
    STACKED_BAR = "stacked_bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    UNKNOWN = "unknown"


class ChartValuePrecision(str, Enum):
    EXACT = "exact"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class FormFieldType(str, Enum):
    TEXT = "text"
    DATE = "date"
    NUMERIC = "numeric"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    SIGNATURE_REGION = "signature_region"
    UNKNOWN = "unknown"


class FormFieldStatus(str, Enum):
    POPULATED = "populated"
    EMPTY = "empty"
    UNREADABLE = "unreadable"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    LOW_CONFIDENCE = "low_confidence"
    CHECKED = "checked"
    UNCHECKED = "unchecked"
    SIGNATURE_PRESENT = "signature_present"
    SIGNATURE_BLANK = "signature_blank"


class SelectionState(str, Enum):
    CHECKED = "checked"
    UNCHECKED = "unchecked"
    UNKNOWN = "unknown"


StrictCoordinateSpace = Annotated[CoordinateSpace, _strict_enum_validator(CoordinateSpace)]
StrictVisualElementType = Annotated[VisualElementType, _strict_enum_validator(VisualElementType)]
StrictValidationStatus = Annotated[ValidationStatus, _strict_enum_validator(ValidationStatus)]
StrictWarningSeverity = Annotated[WarningSeverity, _strict_enum_validator(WarningSeverity)]
StrictSourceMode = Annotated[SourceMode, _strict_enum_validator(SourceMode)]
StrictTextRole = Annotated[TextRole, _strict_enum_validator(TextRole)]
StrictTableCellStatus = Annotated[TableCellStatus, _strict_enum_validator(TableCellStatus)]
StrictChartType = Annotated[ChartType, _strict_enum_validator(ChartType)]
StrictChartValuePrecision = Annotated[ChartValuePrecision, _strict_enum_validator(ChartValuePrecision)]
StrictFormFieldType = Annotated[FormFieldType, _strict_enum_validator(FormFieldType)]
StrictFormFieldStatus = Annotated[FormFieldStatus, _strict_enum_validator(FormFieldStatus)]
StrictSelectionState = Annotated[SelectionState, _strict_enum_validator(SelectionState)]

_UNAVAILABLE_EXTRACTION_METHODS = frozenset({
    "unavailable",
    "ocr_unavailable",
    "none",
    "skipped",
    "optional_skipped",
})


# ==============================================================================
# SHARED BASE & SUPPORTING MODELS
# ==============================================================================
class _StrictVisualBaseModel(BaseModel):
    """Base Pydantic model enforcing strict field validation and deterministic serialization."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        ser_json_timedelta="iso8601",
    )

    def to_dict(self, *, exclude_none: bool = False) -> Dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=exclude_none)

    def to_json(self, *, indent: Optional[int] = None, exclude_none: bool = False, sort_keys: bool = True) -> str:
        payload = self.to_dict(exclude_none=exclude_none)
        return json.dumps(payload, sort_keys=sort_keys, indent=indent, ensure_ascii=False, allow_nan=False)


class BoundingBox(_StrictVisualBaseModel):
    """
    Coordinate-validated bounding box using LORE's canonical ``[ymin, xmin, ymax, xmax]``
    ordering on the 0..1000 normalized scale by default, with optional source page space metadata.
    """

    ymin: NonNegNumber
    xmin: NonNegNumber
    ymax: NonNegNumber
    xmax: NonNegNumber
    coordinate_space: StrictCoordinateSpace = CoordinateSpace.NORMALIZED_1000
    page_bbox_xywh: Optional[List[NonNegNumber]] = None
    page_width: Optional[StrictFiniteNumber] = Field(default=None, gt=0)
    page_height: Optional[StrictFiniteNumber] = Field(default=None, gt=0)
    rotation: Optional[StrictInt] = None
    schema_extensions: Optional[Dict[StrictStr, Any]] = None

    @model_validator(mode="after")
    def _validate_bounds_and_geometry(self) -> "BoundingBox":
        ymin = float(self.ymin)
        xmin = float(self.xmin)
        ymax = float(self.ymax)
        xmax = float(self.xmax)

        if ymin > ymax:
            raise ValueError(f"BoundingBox ymin ({ymin}) must be <= ymax ({ymax})")
        if xmin > xmax:
            raise ValueError(f"BoundingBox xmin ({xmin}) must be <= xmax ({xmax})")

        if self.coordinate_space == CoordinateSpace.NORMALIZED_1000:
            limit = float(CANONICAL_COORDINATE_SCALE)
            for name, val in (("ymin", ymin), ("xmin", xmin), ("ymax", ymax), ("xmax", xmax)):
                if val < 0.0 or val > limit:
                    raise ValueError(
                        f"BoundingBox.{name}={val} out of normalized range [0, {CANONICAL_COORDINATE_SCALE}]"
                    )
        elif self.coordinate_space == CoordinateSpace.NORMALIZED_0_1:
            for name, val in (("ymin", ymin), ("xmin", xmin), ("ymax", ymax), ("xmax", xmax)):
                if val < 0.0 or val > 1.0:
                    raise ValueError(f"BoundingBox.{name}={val} out of unit range [0.0, 1.0]")
        else:
            # PAGE_POINTS or PIXELS
            if self.page_width is not None and xmax > float(self.page_width) + 1.0:
                raise ValueError(
                    f"BoundingBox.xmax={xmax} exceeds declared page_width={self.page_width}"
                )
            if self.page_height is not None and ymax > float(self.page_height) + 1.0:
                raise ValueError(
                    f"BoundingBox.ymax={ymax} exceeds declared page_height={self.page_height}"
                )

        if self.rotation is not None and self.rotation not in (0, 90, 180, 270):
            raise ValueError(f"BoundingBox.rotation must be one of 0, 90, 180, 270, got {self.rotation}")

        if self.page_bbox_xywh is not None:
            if len(self.page_bbox_xywh) != 4:
                raise ValueError("BoundingBox.page_bbox_xywh must contain exactly 4 numbers [x, y, w, h]")
            px, py, pw, ph = [float(v) for v in self.page_bbox_xywh]
            if self.page_width is not None and (px + pw) > float(self.page_width) + 2.0:
                raise ValueError(
                    f"BoundingBox.page_bbox_xywh right edge ({px + pw}) exceeds page_width ({self.page_width})"
                )
            if self.page_height is not None and (py + ph) > float(self.page_height) + 2.0:
                raise ValueError(
                    f"BoundingBox.page_bbox_xywh bottom edge ({py + ph}) exceeds page_height ({self.page_height})"
                )

        return self

    def to_normalized_list(self) -> List[int]:
        """Return canonical [ymin, xmin, ymax, xmax] integers on the 0..1000 scale when possible."""
        if self.coordinate_space == CoordinateSpace.NORMALIZED_1000:
            return [
                int(round(float(self.ymin))),
                int(round(float(self.xmin))),
                int(round(float(self.ymax))),
                int(round(float(self.xmax))),
            ]
        if self.coordinate_space == CoordinateSpace.NORMALIZED_0_1:
            return [
                int(round(float(self.ymin) * CANONICAL_COORDINATE_SCALE)),
                int(round(float(self.xmin) * CANONICAL_COORDINATE_SCALE)),
                int(round(float(self.ymax) * CANONICAL_COORDINATE_SCALE)),
                int(round(float(self.xmax) * CANONICAL_COORDINATE_SCALE)),
            ]
        if self.page_width and self.page_height:
            return [
                max(0, min(CANONICAL_COORDINATE_SCALE, int(round((float(self.ymin) / float(self.page_height)) * CANONICAL_COORDINATE_SCALE)))),
                max(0, min(CANONICAL_COORDINATE_SCALE, int(round((float(self.xmin) / float(self.page_width)) * CANONICAL_COORDINATE_SCALE)))),
                max(0, min(CANONICAL_COORDINATE_SCALE, int(round((float(self.ymax) / float(self.page_height)) * CANONICAL_COORDINATE_SCALE)))),
                max(0, min(CANONICAL_COORDINATE_SCALE, int(round((float(self.xmax) / float(self.page_width)) * CANONICAL_COORDINATE_SCALE)))),
            ]
        raise ValueError("Cannot convert non-normalized BoundingBox to 0..1000 without page_width and page_height")

    @classmethod
    def from_normalized_box(
        cls,
        normalized_box: Sequence[Union[int, float]],
        *,
        page_bbox_xywh: Optional[Sequence[float]] = None,
        page_width: Optional[float] = None,
        page_height: Optional[float] = None,
        rotation: Optional[int] = None,
    ) -> "BoundingBox":
        if not isinstance(normalized_box, (list, tuple)) or len(normalized_box) != 4:
            raise ValueError(f"normalized_box must be a 4-element sequence, got {normalized_box!r}")
        for val in normalized_box:
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError(f"normalized_box coordinates must be numeric, got {type(val).__name__}")
        ymin, xmin, ymax, xmax = normalized_box
        return cls(
            ymin=ymin,
            xmin=xmin,
            ymax=ymax,
            xmax=xmax,
            coordinate_space=CoordinateSpace.NORMALIZED_1000,
            page_bbox_xywh=list(page_bbox_xywh[:4]) if page_bbox_xywh is not None else None,
            page_width=page_width,
            page_height=page_height,
            rotation=rotation,
        )

    @classmethod
    def from_xywh(
        cls,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        page_width: float,
        page_height: float,
        rotation: Optional[int] = None,
    ) -> "BoundingBox":
        if page_width <= 0 or page_height <= 0:
            raise ValueError(f"page_width ({page_width}) and page_height ({page_height}) must be > 0")
        if x < 0 or y < 0 or w < 0 or h < 0:
            raise ValueError("x, y, w, h must be non-negative")
        xmin_n = max(0, min(CANONICAL_COORDINATE_SCALE, int(round((x / page_width) * CANONICAL_COORDINATE_SCALE))))
        ymin_n = max(0, min(CANONICAL_COORDINATE_SCALE, int(round((y / page_height) * CANONICAL_COORDINATE_SCALE))))
        xmax_n = max(xmin_n, min(CANONICAL_COORDINATE_SCALE, int(round(((x + w) / page_width) * CANONICAL_COORDINATE_SCALE))))
        ymax_n = max(ymin_n, min(CANONICAL_COORDINATE_SCALE, int(round(((y + h) / page_height) * CANONICAL_COORDINATE_SCALE))))
        return cls(
            ymin=ymin_n,
            xmin=xmin_n,
            ymax=ymax_n,
            xmax=xmax_n,
            coordinate_space=CoordinateSpace.NORMALIZED_1000,
            page_bbox_xywh=[round(float(x), 4), round(float(y), 4), round(float(w), 4), round(float(h), 4)],
            page_width=float(page_width),
            page_height=float(page_height),
            rotation=rotation,
        )


class ExtractionWarning(_StrictVisualBaseModel):
    """Structured warning raised during extraction, OCR, geometry calibration, or validation."""

    code: NonBlankStr
    message: NonBlankStr
    severity: StrictWarningSeverity = WarningSeverity.MEDIUM
    source: Optional[NonBlankStr] = None
    element_id: Optional[NonBlankStr] = None
    page_number: Optional[PositivePageInt] = None
    field_path: Optional[NonBlankStr] = None
    details: Dict[StrictStr, Any] = Field(default_factory=dict)
    schema_extensions: Optional[Dict[StrictStr, Any]] = None


class SourceCropReference(_StrictVisualBaseModel):
    """Content-addressed visual crop reference and pixel geometry."""

    crop_id: Optional[NonBlankStr] = None
    crop_ref: Optional[NonBlankStr] = None
    mime_type: Optional[NonBlankStr] = None
    sha256: Optional[NonBlankStr] = None
    byte_size: Optional[NonNegInt] = None
    width_px: Optional[PositivePageInt] = None
    height_px: Optional[PositivePageInt] = None
    crop_rect_px: Optional[List[NonNegNumber]] = None
    source_asset_name: Optional[StrictStr] = None
    crop_file_path: Optional[StrictStr] = None
    crop_image_base64: Optional[StrictStr] = None
    crop_thumbnail_base64: Optional[StrictStr] = None
    schema_extensions: Optional[Dict[StrictStr, Any]] = None

    @model_validator(mode="after")
    def _validate_reference_minimum(self) -> "SourceCropReference":
        if not (self.crop_ref or self.crop_id or self.crop_file_path or self.source_asset_name):
            raise ValueError(
                "SourceCropReference must provide at least one of crop_ref, crop_id, crop_file_path, or source_asset_name"
            )
        if self.sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", self.sha256):
            raise ValueError(f"SourceCropReference.sha256 must be a 64-char hex digest, got {self.sha256!r}")
        if self.crop_rect_px is not None and len(self.crop_rect_px) != 4:
            raise ValueError("SourceCropReference.crop_rect_px must contain 4 numbers [x0, y0, x1, y1]")
        return self


CropReferenceValue = Union[SourceCropReference, NonBlankStr]


class ExtractionProvenance(_StrictVisualBaseModel):
    """Explicit lineage tracking document, page, extractor, source mode, and repair state."""

    source_document_id: NonBlankStr
    document_version: Optional[PositivePageInt] = None
    page_number: PositivePageInt
    extraction_method: NonBlankStr
    extractor_version: NonBlankStr
    engine_name: Optional[NonBlankStr] = None
    source_mode: Optional[StrictSourceMode] = None
    language: Optional[NonBlankStr] = None
    source_asset_name: Optional[StrictStr] = None
    source_crop_reference: Optional[CropReferenceValue] = None
    page_rotation: Optional[StrictInt] = None
    is_repaired: StrictBool = False
    is_inference: StrictBool = False
    extracted_at: Optional[StrictISOTimestamp] = None
    metadata: Dict[StrictStr, Any] = Field(default_factory=dict)
    schema_extensions: Optional[Dict[StrictStr, Any]] = None

    @model_validator(mode="after")
    def _validate_rotation(self) -> "ExtractionProvenance":
        if self.page_rotation is not None and self.page_rotation not in (0, 90, 180, 270):
            raise ValueError(f"page_rotation must be 0, 90, 180, or 270, got {self.page_rotation}")
        return self


# ==============================================================================
# VISUAL ELEMENT HIERARCHY (BASE + TYPED TEXT / TABLE / CHART / FORM)
# ==============================================================================
class VisualElement(_StrictVisualBaseModel):
    """
    Canonical visual element contract shared across all extracted page elements.

    Preserves the 12 mandatory fields plus nullable uncertain values and zero
    fabricated confidence scores.
    """

    element_id: NonBlankStr
    element_type: StrictVisualElementType = VisualElementType.UNKNOWN
    source_document_id: NonBlankStr
    page_number: PositivePageInt
    bounding_box: BoundingBox
    content: Optional[StrictStr] = None
    extraction_method: NonBlankStr
    extractor_version: NonBlankStr
    confidence: Optional[ConfidenceScore] = None
    validation_status: StrictValidationStatus = ValidationStatus.VALID
    warnings: List[ExtractionWarning] = Field(default_factory=list)
    source_crop_reference: Optional[CropReferenceValue] = None

    reading_order: Optional[NonNegInt] = None
    layout_label: Optional[StrictStr] = None
    layout_confidence: Optional[ConfidenceScore] = None
    markdown: Optional[StrictStr] = None
    is_repaired: StrictBool = False
    provenance: Optional[ExtractionProvenance] = None
    metadata: Dict[StrictStr, Any] = Field(default_factory=dict)
    schema_extensions: Optional[Dict[StrictStr, Any]] = None

    @model_validator(mode="after")
    def _validate_element_invariants(self) -> "VisualElement":
        # Never allow a non-null fabricated confidence when the extraction method or source
        # explicitly indicates that no extractor ran.
        method_norm = self.extraction_method.strip().lower()
        if method_norm in _UNAVAILABLE_EXTRACTION_METHODS and self.confidence is not None:
            raise ValueError(
                f"confidence must be null (None) when extraction_method={self.extraction_method!r}; got {self.confidence}"
            )

        if self.bounding_box.rotation is not None and self.provenance and self.provenance.page_rotation is not None:
            if self.bounding_box.rotation != self.provenance.page_rotation:
                raise ValueError(
                    f"bounding_box.rotation ({self.bounding_box.rotation}) != provenance.page_rotation ({self.provenance.page_rotation})"
                )

        if self.provenance is not None:
            if self.provenance.source_document_id != self.source_document_id:
                raise ValueError(
                    f"provenance.source_document_id ({self.provenance.source_document_id!r}) "
                    f"does not match element.source_document_id ({self.source_document_id!r})"
                )
            if self.provenance.page_number != self.page_number:
                raise ValueError(
                    f"provenance.page_number ({self.provenance.page_number}) "
                    f"does not match element.page_number ({self.page_number})"
                )
            if self.provenance.extraction_method != self.extraction_method:
                raise ValueError(
                    f"provenance.extraction_method ({self.provenance.extraction_method!r}) "
                    f"does not match element.extraction_method ({self.extraction_method!r})"
                )
            if self.provenance.extractor_version != self.extractor_version:
                raise ValueError(
                    f"provenance.extractor_version ({self.provenance.extractor_version!r}) "
                    f"does not match element.extractor_version ({self.extractor_version!r})"
                )
            if self.provenance.source_mode == SourceMode.UNAVAILABLE and self.confidence is not None:
                raise ValueError(
                    f"confidence must be null (None) when provenance.source_mode is 'unavailable'; got {self.confidence}"
                )

        for w in self.warnings:
            if w.page_number is not None and w.page_number != self.page_number:
                raise ValueError(
                    f"Warning {w.code!r} page_number ({w.page_number}) != element page_number ({self.page_number})"
                )
            if w.element_id is not None and w.element_id != self.element_id:
                raise ValueError(
                    f"Warning {w.code!r} element_id ({w.element_id!r}) != element_id ({self.element_id!r})"
                )

        return self


class TextElement(VisualElement):
    """Structured narrative, title, heading, caption, or header/footer visual element."""

    element_type: StrictVisualElementType = VisualElementType.TEXT
    text_role: Optional[StrictTextRole] = None
    heading_level: Optional[StrictInt] = Field(default=None, ge=1, le=6)
    language: Optional[NonBlankStr] = None
    text_source: Optional[StrictSourceMode] = None
    word_count: Optional[NonNegInt] = None
    lines: List[StrictStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_text_type(self) -> "TextElement":
        allowed = {
            VisualElementType.TEXT,
            VisualElementType.TITLE_HEADING,
            VisualElementType.PARAGRAPH,
            VisualElementType.HEADER_FOOTER,
        }
        if self.element_type not in allowed:
            raise ValueError(
                f"TextElement requires element_type in {[t.value for t in sorted(allowed, key=lambda x: x.value)]}, "
                f"got {self.element_type.value!r}"
            )
        if self.text_source == SourceMode.UNAVAILABLE and self.confidence is not None:
            raise ValueError(
                f"confidence must be null (None) when text_source is 'unavailable'; got {self.confidence}"
            )
        return self


# ==============================================================================
# TABLE CELL & TABLE ELEMENT
# ==============================================================================
class TableCell(_StrictVisualBaseModel):
    """
    Individual table grid cell explicitly distinguishing:
    - ``populated``
    - ``empty``
    - ``unreadable``
    - ``missing``
    - ``unknown``
    """

    cell_id: Optional[NonBlankStr] = None
    row_index: NonNegInt
    col_index: NonNegInt
    row_span: PositivePageInt = 1
    col_span: PositivePageInt = 1
    is_header: StrictBool = False
    status: StrictTableCellStatus
    value: Optional[StrictStr] = None
    lines: List[StrictStr] = Field(default_factory=list)
    numeric_value: Optional[StrictFiniteNumber] = None
    unit: Optional[NonBlankStr] = None
    source: Optional[StrictStr] = None
    confidence: Optional[ConfidenceScore] = None
    bounding_box: Optional[BoundingBox] = None
    needs_review: StrictBool = False
    warnings: List[ExtractionWarning] = Field(default_factory=list)
    schema_extensions: Optional[Dict[StrictStr, Any]] = None

    @model_validator(mode="after")
    def _validate_cell_epistemics(self) -> "TableCell":
        if self.status == TableCellStatus.POPULATED:
            if self.value is None or not self.value.strip():
                raise ValueError("TableCell with status='populated' must carry a non-empty string value")
        elif self.status in (TableCellStatus.EMPTY, TableCellStatus.UNREADABLE, TableCellStatus.MISSING):
            if self.value is not None or self.numeric_value is not None:
                raise ValueError(
                    f"TableCell with status={self.status.value!r} must have value=None and numeric_value=None"
                )
        if self.source in _UNAVAILABLE_EXTRACTION_METHODS and self.confidence is not None:
            raise ValueError(
                f"TableCell.confidence must be None when source={self.source!r}; got {self.confidence}"
            )
        if self.status == TableCellStatus.MISSING and self.confidence is not None:
            raise ValueError(
                f"TableCell with status='missing' must have confidence=None; got {self.confidence}"
            )
        return self


class TableElement(VisualElement):
    """Structured table element preserving grid spans, nullable headers, cells, and footnotes."""

    element_type: Literal[VisualElementType.TABLE] = VisualElementType.TABLE
    num_rows: NonNegInt
    num_cols: NonNegInt
    headers: List[Optional[StrictStr]] = Field(default_factory=list)
    header_row_indices: List[NonNegInt] = Field(default_factory=list)
    cells: List[TableCell] = Field(default_factory=list)
    footnotes: List[StrictStr] = Field(default_factory=list)
    has_merged_cells: StrictBool = False
    structure_confidence: Optional[ConfidenceScore] = None

    @model_validator(mode="after")
    def _validate_table_grid(self) -> "TableElement":
        if self.cells and (self.num_rows == 0 or self.num_cols == 0):
            raise ValueError("TableElement with cells must declare num_rows >= 1 and num_cols >= 1")

        if self.headers and self.num_cols > 0 and len(self.headers) != self.num_cols:
            raise ValueError(
                f"TableElement.headers length ({len(self.headers)}) must match num_cols ({self.num_cols})"
            )

        for r_idx in self.header_row_indices:
            if self.num_rows > 0 and r_idx >= self.num_rows:
                raise ValueError(f"header_row_index {r_idx} exceeds num_rows={self.num_rows}")

        occupied: Dict[Tuple[int, int], str] = {}
        for idx, cell in enumerate(self.cells):
            if cell.row_index + cell.row_span > self.num_rows:
                raise ValueError(
                    f"Cell[{idx}] row span ({cell.row_index} + {cell.row_span}) exceeds num_rows={self.num_rows}"
                )
            if cell.col_index + cell.col_span > self.num_cols:
                raise ValueError(
                    f"Cell[{idx}] col span ({cell.col_index} + {cell.col_span}) exceeds num_cols={self.num_cols}"
                )
            if cell.row_span > 1 or cell.col_span > 1:
                if not self.has_merged_cells:
                    object.__setattr__(self, "has_merged_cells", True)
            for r in range(cell.row_index, cell.row_index + cell.row_span):
                for c in range(cell.col_index, cell.col_index + cell.col_span):
                    if (r, c) in occupied and cell.status != TableCellStatus.MISSING:
                        raise ValueError(
                            f"Overlapping table grid occupancy at row={r}, col={c} between {occupied[(r, c)]} and cell[{idx}]"
                        )
                    occupied[(r, c)] = cell.cell_id or f"cell[{idx}]"

        return self


# ==============================================================================
# CHART SERIES & CHART ELEMENT
# ==============================================================================
class ChartAxis(_StrictVisualBaseModel):
    """Calibrated or uncalibrated axis descriptor preserving non-zero origins and units."""

    axis_id: NonBlankStr
    label: Optional[StrictStr] = None
    unit: Optional[StrictStr] = None
    scale_type: Optional[NonBlankStr] = None
    is_calibrated: StrictBool = False
    origin_value: Optional[StrictFiniteNumber] = None
    min_value: Optional[StrictFiniteNumber] = None
    max_value: Optional[StrictFiniteNumber] = None
    contains_zero: Optional[StrictBool] = None
    estimated_uncertainty: Optional[NonNegNumber] = None
    tick_values: List[StrictFiniteNumber] = Field(default_factory=list)
    calibration_reason: Optional[StrictStr] = None
    schema_extensions: Optional[Dict[StrictStr, Any]] = None

    @model_validator(mode="after")
    def _validate_axis_range(self) -> "ChartAxis":
        if self.min_value is not None and self.max_value is not None:
            if float(self.min_value) > float(self.max_value):
                raise ValueError(f"ChartAxis.min_value ({self.min_value}) > max_value ({self.max_value})")
        return self


class ChartDataPoint(_StrictVisualBaseModel):
    """Single data point explicitly tagged as ``exact``, ``estimated``, or ``unavailable``."""

    point_id: Optional[NonBlankStr] = None
    category: Optional[StrictStr] = None
    x: Optional[Union[StrictStr, StrictFiniteNumber]] = None
    value: Optional[StrictFiniteNumber] = None
    precision: StrictChartValuePrecision
    unit: Optional[StrictStr] = None
    uncertainty: Optional[NonNegNumber] = None
    axis_id: Optional[StrictStr] = None
    source: Optional[StrictStr] = None
    cumulative_value: Optional[StrictFiniteNumber] = None
    percentage: Optional[StrictFiniteNumber] = None
    bounding_box: Optional[BoundingBox] = None
    confidence: Optional[ConfidenceScore] = None
    schema_extensions: Optional[Dict[StrictStr, Any]] = None

    @model_validator(mode="after")
    def _validate_precision_contract(self) -> "ChartDataPoint":
        if self.precision == ChartValuePrecision.UNAVAILABLE:
            if self.value is not None or self.cumulative_value is not None or self.percentage is not None:
                raise ValueError(
                    "ChartDataPoint with precision='unavailable' must keep value, cumulative_value, and percentage as None"
                )
            if self.source in _UNAVAILABLE_EXTRACTION_METHODS and self.confidence is not None:
                raise ValueError(
                    f"ChartDataPoint with unavailable source must keep confidence=None, got {self.confidence}"
                )
        elif self.precision in (ChartValuePrecision.EXACT, ChartValuePrecision.ESTIMATED):
            if self.value is None:
                raise ValueError(
                    f"ChartDataPoint with precision={self.precision.value!r} must include a non-null numeric value"
                )
            if self.precision == ChartValuePrecision.EXACT and self.uncertainty is not None and float(self.uncertainty) > 0.0:
                raise ValueError(
                    f"ChartDataPoint with precision='exact' cannot have positive uncertainty={self.uncertainty}; use 'estimated'"
                )
        return self


class ChartSeries(_StrictVisualBaseModel):
    """Named or unnamed visual chart series bound to an optional calibrated axis."""

    series_id: NonBlankStr
    name: Optional[StrictStr] = None
    axis_id: Optional[StrictStr] = None
    unit: Optional[StrictStr] = None
    color_hex: Optional[StrictStr] = None
    confidence: Optional[ConfidenceScore] = None
    data_points: List[ChartDataPoint] = Field(default_factory=list)
    schema_extensions: Optional[Dict[StrictStr, Any]] = None

    @model_validator(mode="after")
    def _validate_color_hex(self) -> "ChartSeries":
        if self.color_hex is not None and self.color_hex != "":
            if not _HEX_COLOR_RE.match(self.color_hex):
                raise ValueError(f"ChartSeries.color_hex must be '#RRGGBB' hex or None, got {self.color_hex!r}")
        return self

    def precision_counts(self) -> Dict[str, int]:
        counts = {
            ChartValuePrecision.EXACT.value: 0,
            ChartValuePrecision.ESTIMATED.value: 0,
            ChartValuePrecision.UNAVAILABLE.value: 0,
        }
        for dp in self.data_points:
            counts[dp.precision.value] += 1
        return counts


class ChartElement(VisualElement):
    """Structured chart extraction contract preserving axes, series, units, and value precision."""

    element_type: Literal[VisualElementType.CHART] = VisualElementType.CHART
    chart_type: StrictChartType = ChartType.UNKNOWN
    title: Optional[StrictStr] = None
    source_mode: Optional[StrictSourceMode] = None
    categories: List[Optional[StrictStr]] = Field(default_factory=list)
    axes: List[ChartAxis] = Field(default_factory=list)
    series: List[ChartSeries] = Field(default_factory=list)
    legends: List[StrictStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_chart_axes_and_series(self) -> "ChartElement":
        seen_series_ids: set[str] = set()
        for s in self.series:
            if s.series_id in seen_series_ids:
                raise ValueError(f"Duplicate ChartSeries.series_id {s.series_id!r} inside ChartElement {self.element_id!r}")
            seen_series_ids.add(s.series_id)
        seen_axis_ids: set[str] = set()
        for ax in self.axes:
            if ax.axis_id in seen_axis_ids:
                raise ValueError(f"Duplicate ChartAxis.axis_id {ax.axis_id!r} inside ChartElement {self.element_id!r}")
            seen_axis_ids.add(ax.axis_id)
        return self

    def value_precision_summary(self) -> Dict[str, int]:
        totals = {
            ChartValuePrecision.EXACT.value: 0,
            ChartValuePrecision.ESTIMATED.value: 0,
            ChartValuePrecision.UNAVAILABLE.value: 0,
        }
        for s in self.series:
            sc = s.precision_counts()
            for k, v in sc.items():
                totals[k] += v
        return totals


# ==============================================================================
# FORM FIELD & FORM ELEMENT
# ==============================================================================
class FormField(_StrictVisualBaseModel):
    """
    Structured form field, checkbox, radio option, or signature region.

    Explicitly distinguishes ``populated``, ``empty``, ``unreadable``, ``unknown``,
    ``ambiguous``, and ``low_confidence`` without inferring approval or signer identity.
    """

    field_id: NonBlankStr
    label: Optional[StrictStr] = None
    field_type: StrictFormFieldType = FormFieldType.TEXT
    value: Optional[StrictStr] = None
    numeric_value: Optional[StrictFiniteNumber] = None
    currency: Optional[NonBlankStr] = None
    unit: Optional[NonBlankStr] = None
    status: StrictFormFieldStatus
    selection_state: Optional[StrictSelectionState] = None
    is_ambiguous: StrictBool = False
    ambiguity_reason: Optional[StrictStr] = None
    possibly_handwritten: StrictBool = False
    is_approval_field: StrictBool = False
    confidence: Optional[ConfidenceScore] = None
    column_index: Optional[NonNegInt] = None
    source: Optional[StrictStr] = None
    bounding_box: Optional[BoundingBox] = None
    label_bounding_box: Optional[BoundingBox] = None
    value_bounding_box: Optional[BoundingBox] = None
    warnings: List[ExtractionWarning] = Field(default_factory=list)
    schema_extensions: Optional[Dict[StrictStr, Any]] = None

    @model_validator(mode="after")
    def _validate_field_epistemics(self) -> "FormField":
        if self.status in (FormFieldStatus.EMPTY, FormFieldStatus.SIGNATURE_BLANK):
            if self.value is not None or self.numeric_value is not None:
                raise ValueError(
                    f"FormField with status={self.status.value!r} must have value=None and numeric_value=None"
                )
        elif self.status == FormFieldStatus.UNREADABLE:
            if self.value is not None or self.numeric_value is not None:
                raise ValueError("FormField with status='unreadable' must have value=None and numeric_value=None")
        elif self.status == FormFieldStatus.POPULATED:
            if self.field_type not in (FormFieldType.CHECKBOX, FormFieldType.RADIO, FormFieldType.SIGNATURE_REGION):
                if self.value is None or not self.value.strip():
                    raise ValueError("FormField with status='populated' must carry a non-empty string value")

        if self.selection_state is not None:
            if self.status == FormFieldStatus.CHECKED and self.selection_state != SelectionState.CHECKED:
                raise ValueError("FormField status='checked' conflicts with selection_state")
            if self.status == FormFieldStatus.UNCHECKED and self.selection_state != SelectionState.UNCHECKED:
                raise ValueError("FormField status='unchecked' conflicts with selection_state")
            if self.status == FormFieldStatus.UNKNOWN and self.field_type in (FormFieldType.CHECKBOX, FormFieldType.RADIO):
                if self.selection_state != SelectionState.UNKNOWN:
                    raise ValueError("FormField status='unknown' on checkbox/radio requires selection_state='unknown'")

        if self.source in _UNAVAILABLE_EXTRACTION_METHODS and self.confidence is not None:
            raise ValueError(
                f"FormField.confidence must be None when source={self.source!r}; got {self.confidence}"
            )
        return self


class FormRadioGroup(_StrictVisualBaseModel):
    """Mutually-exclusive radio option cluster with explicit ambiguity tracking."""

    group_id: NonBlankStr
    label: Optional[StrictStr] = None
    option_field_ids: List[NonBlankStr] = Field(default_factory=list)
    selected_value: Optional[StrictStr] = None
    is_ambiguous: StrictBool = False
    ambiguity_reason: Optional[StrictStr] = None
    schema_extensions: Optional[Dict[StrictStr, Any]] = None


class FormElement(VisualElement):
    """Structured form extraction evidence preserving blank fields, controls, and signature slots."""

    element_type: StrictVisualElementType = VisualElementType.FORM
    form_subtype: Optional[StrictStr] = None
    source_mode: Optional[StrictStr] = None
    column_count: Optional[PositivePageInt] = None
    fields: List[FormField] = Field(default_factory=list)
    radio_groups: List[FormRadioGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_form_element(self) -> "FormElement":
        if self.element_type not in (VisualElementType.FORM, VisualElementType.FORM_KV):
            raise ValueError(
                f"FormElement requires element_type in ('form', 'form_kv'), got {self.element_type.value!r}"
            )
        seen_ids: set[str] = set()
        for f in self.fields:
            if f.field_id in seen_ids:
                raise ValueError(f"Duplicate FormField.field_id {f.field_id!r} in FormElement {self.element_id!r}")
            seen_ids.add(f.field_id)
        for rg in self.radio_groups:
            for fid in rg.option_field_ids:
                if fid not in seen_ids:
                    raise ValueError(
                        f"FormRadioGroup {rg.group_id!r} references unknown field_id {fid!r}"
                    )
        return self


# ==============================================================================
# POLYMORPHIC ELEMENT DISCRIMINATION & PAGE / DOCUMENT CONTAINER
# ==============================================================================
def _discriminate_element_tag(value: Any) -> str:
    et = value.get("element_type") if isinstance(value, Mapping) else getattr(value, "element_type", None)
    et_val = et.value if isinstance(et, Enum) else str(et or "")
    if et_val == VisualElementType.TABLE.value:
        return "table"
    if et_val == VisualElementType.CHART.value:
        return "chart"
    if et_val in (VisualElementType.FORM.value, VisualElementType.FORM_KV.value):
        return "form"
    if et_val in (
        VisualElementType.TEXT.value,
        VisualElementType.TITLE_HEADING.value,
        VisualElementType.PARAGRAPH.value,
        VisualElementType.HEADER_FOOTER.value,
    ):
        return "text"
    return "visual"


AnyVisualElement = Annotated[
    Union[
        Annotated[TableElement, Tag("table")],
        Annotated[ChartElement, Tag("chart")],
        Annotated[FormElement, Tag("form")],
        Annotated[TextElement, Tag("text")],
        Annotated[VisualElement, Tag("visual")],
    ],
    Discriminator(_discriminate_element_tag),
]


class VisualPage(_StrictVisualBaseModel):
    """Per-page geometric metadata and page-level extraction provenance summary."""

    page_number: PositivePageInt
    width: Optional[StrictFiniteNumber] = Field(default=None, gt=0)
    height: Optional[StrictFiniteNumber] = Field(default=None, gt=0)
    rotation: StrictInt = 0
    page_classification: Optional[NonBlankStr] = None
    extraction_method: Optional[NonBlankStr] = None
    extractor_version: Optional[NonBlankStr] = None
    confidence: Optional[ConfidenceScore] = None
    validation_status: StrictValidationStatus = ValidationStatus.VALID
    warnings: List[ExtractionWarning] = Field(default_factory=list)
    schema_extensions: Optional[Dict[StrictStr, Any]] = None

    @model_validator(mode="after")
    def _validate_page_rotation(self) -> "VisualPage":
        if self.rotation not in (0, 90, 180, 270):
            raise ValueError(f"VisualPage.rotation must be 0, 90, 180, or 270, got {self.rotation}")
        for w in self.warnings:
            if w.page_number is not None and w.page_number != self.page_number:
                raise ValueError(
                    f"Page warning {w.code!r} page_number ({w.page_number}) != VisualPage.page_number ({self.page_number})"
                )
        return self


def _split_minor_extras_for_model(raw: Any, model_cls: Type[BaseModel]) -> Any:
    """
    Backward-compatible minor-version evolution helper (used ONLY for ``lore.visual/1.x`` where x >= 1):
    preserves unrecognized additive fields inside ``schema_extensions`` without relaxing known
    field type checks or major-version strictness.
    """
    if not isinstance(raw, Mapping):
        return raw

    out: Dict[str, Any] = dict(raw)
    known = set(model_cls.model_fields.keys())
    if model_cls is VisualDocument:
        known.add("schema")

    extras: Dict[str, Any] = {}
    for k in list(out.keys()):
        if k not in known:
            extras[k] = out.pop(k)

    if extras:
        existing_ext = out.get("schema_extensions")
        if existing_ext is None:
            out["schema_extensions"] = extras
        elif isinstance(existing_ext, Mapping):
            merged_ext = dict(existing_ext)
            merged_ext.update(extras)
            out["schema_extensions"] = merged_ext
        else:
            # Put back invalid schema_extensions so Pydantic raises a clean ValidationError
            out["schema_extensions"] = existing_ext

    # Recurse into declared sub-structures
    for sub_key, sub_cls in (
        ("bounding_box", BoundingBox),
        ("label_bounding_box", BoundingBox),
        ("value_bounding_box", BoundingBox),
        ("provenance", ExtractionProvenance),
    ):
        if sub_key in out and isinstance(out[sub_key], Mapping):
            out[sub_key] = _split_minor_extras_for_model(out[sub_key], sub_cls)

    if "source_crop_reference" in out and isinstance(out["source_crop_reference"], Mapping):
        out["source_crop_reference"] = _split_minor_extras_for_model(out["source_crop_reference"], SourceCropReference)

    for list_key, item_cls in (
        ("warnings", ExtractionWarning),
        ("pages", VisualPage),
        ("cells", TableCell),
        ("axes", ChartAxis),
        ("series", ChartSeries),
        ("data_points", ChartDataPoint),
        ("fields", FormField),
        ("radio_groups", FormRadioGroup),
    ):
        if list_key in out and isinstance(out[list_key], list):
            out[list_key] = [
                _split_minor_extras_for_model(it, item_cls) if isinstance(it, Mapping) else it
                for it in out[list_key]
            ]

    if "elements" in out and isinstance(out["elements"], list):
        evolved_els: List[Any] = []
        tag_map: Dict[str, Type[BaseModel]] = {
            "table": TableElement,
            "chart": ChartElement,
            "form": FormElement,
            "text": TextElement,
            "visual": VisualElement,
        }
        for el in out["elements"]:
            if isinstance(el, Mapping):
                target_cls = tag_map[_discriminate_element_tag(el)]
                evolved_els.append(_split_minor_extras_for_model(el, target_cls))
            else:
                evolved_els.append(el)
        out["elements"] = evolved_els

    return out


class VisualDocument(_StrictVisualBaseModel):
    """
    Top-level LORE Visual JSON Schema v1 document envelope (``lore.visual/1.0``).

    Validates schema version, document-wide page bounds, coordinate consistency,
    element provenance alignment, and deterministic JSON serialization.
    """

    schema_version: NonBlankStr = VISUAL_SCHEMA_ID
    source_document_id: NonBlankStr
    document_version: Optional[PositivePageInt] = None
    title: Optional[StrictStr] = None
    filename: Optional[StrictStr] = None
    document_type: Optional[StrictStr] = None
    page_count: PositivePageInt = 1
    pages: List[VisualPage] = Field(default_factory=list)
    elements: List[AnyVisualElement] = Field(default_factory=list)
    validation_status: StrictValidationStatus = ValidationStatus.VALID
    warnings: List[ExtractionWarning] = Field(default_factory=list)
    provenance: Optional[ExtractionProvenance] = None
    extracted_at: Optional[StrictISOTimestamp] = None
    metadata: Dict[StrictStr, Any] = Field(default_factory=dict)
    schema_extensions: Optional[Dict[StrictStr, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def _handle_schema_version_and_minor_evolution(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data

        raw = dict(data)
        if "schema" in raw:
            alias_ver = raw.pop("schema")
            if "schema_version" in raw and raw["schema_version"] != alias_ver:
                raise ValueError(
                    f"Conflicting 'schema' ({alias_ver!r}) and 'schema_version' ({raw['schema_version']!r})"
                )
            raw.setdefault("schema_version", alias_ver)

        sv = raw.get("schema_version", VISUAL_SCHEMA_ID)
        major, minor = parse_visual_schema_version(sv)

        # Strict 1.0 forbids unexpected fields cleanly; minor >= 1 in 1.x preserves additive fields safely.
        if major == 1 and minor >= 1:
            return _split_minor_extras_for_model(raw, cls)
        return raw

    @model_validator(mode="after")
    def _validate_document_cross_references(self) -> "VisualDocument":
        parse_visual_schema_version(self.schema_version)

        page_map: Dict[int, VisualPage] = {}
        for p in self.pages:
            if p.page_number > self.page_count:
                raise ValueError(
                    f"VisualPage.page_number={p.page_number} exceeds VisualDocument.page_count={self.page_count}"
                )
            if p.page_number in page_map:
                raise ValueError(f"Duplicate VisualPage for page_number={p.page_number}")
            page_map[p.page_number] = p

        seen_element_ids: set[str] = set()
        for el in self.elements:
            if el.element_id in seen_element_ids:
                raise ValueError(f"Duplicate element_id {el.element_id!r} in VisualDocument {self.source_document_id!r}")
            seen_element_ids.add(el.element_id)

            if el.page_number > self.page_count:
                raise ValueError(
                    f"Element {el.element_id!r} references page_number={el.page_number} > page_count={self.page_count}"
                )

            if el.source_document_id != self.source_document_id:
                raise ValueError(
                    f"Element {el.element_id!r} source_document_id={el.source_document_id!r} "
                    f"does not match document source_document_id={self.source_document_id!r}"
                )

            page_info = page_map.get(el.page_number)
            if page_info is not None:
                bb = el.bounding_box
                if page_info.width is not None and bb.page_width is not None:
                    if abs(float(page_info.width) - float(bb.page_width)) > max(1.0, 0.02 * float(page_info.width)):
                        raise ValueError(
                            f"Element {el.element_id!r} bounding_box.page_width={bb.page_width} "
                            f"inconsistent with VisualPage({el.page_number}).width={page_info.width}"
                        )
                if page_info.height is not None and bb.page_height is not None:
                    if abs(float(page_info.height) - float(bb.page_height)) > max(1.0, 0.02 * float(page_info.height)):
                        raise ValueError(
                            f"Element {el.element_id!r} bounding_box.page_height={bb.page_height} "
                            f"inconsistent with VisualPage({el.page_number}).height={page_info.height}"
                        )
                if bb.coordinate_space in (CoordinateSpace.PAGE_POINTS, CoordinateSpace.PIXELS):
                    if page_info.width is not None and float(bb.xmax) > float(page_info.width) + 1.0:
                        raise ValueError(
                            f"Element {el.element_id!r} xmax={bb.xmax} exceeds VisualPage({el.page_number}).width={page_info.width}"
                        )
                    if page_info.height is not None and float(bb.ymax) > float(page_info.height) + 1.0:
                        raise ValueError(
                            f"Element {el.element_id!r} ymax={bb.ymax} exceeds VisualPage({el.page_number}).height={page_info.height}"
                        )

        for w in self.warnings:
            if w.page_number is not None and w.page_number > self.page_count:
                raise ValueError(
                    f"Document warning {w.code!r} references page_number={w.page_number} > page_count={self.page_count}"
                )
            if w.element_id is not None and self.elements and w.element_id not in seen_element_ids:
                raise ValueError(
                    f"Document warning {w.code!r} references unknown element_id={w.element_id!r}"
                )

        if self.provenance is not None:
            if self.provenance.source_document_id != self.source_document_id:
                raise ValueError(
                    f"Document provenance.source_document_id={self.provenance.source_document_id!r} "
                    f"!= source_document_id={self.source_document_id!r}"
                )
            if self.provenance.page_number > self.page_count:
                raise ValueError(
                    f"Document provenance.page_number={self.provenance.page_number} > page_count={self.page_count}"
                )

        return self

    @classmethod
    def from_json(cls, raw: Union[str, bytes]) -> "VisualDocument":
        return cls.model_validate_json(raw)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VisualDocument":
        return cls.model_validate(payload)

    @classmethod
    def export_json_schema(cls) -> Dict[str, Any]:
        schema = cls.model_json_schema(mode="serialization")
        schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        schema["$id"] = f"https://lore.enterprise/schemas/{VISUAL_SCHEMA_ID}.json"
        schema["x-lore-schema-id"] = VISUAL_SCHEMA_ID
        return schema


# ==============================================================================
# SCHEMA EVOLUTION & LORE EXTRACTOR ADAPTER HELPERS
# ==============================================================================
def _map_validation_status(
    *,
    needs_review: bool = False,
    review_required: bool = False,
    is_ambiguous: bool = False,
    is_incomplete: bool = False,
    is_unavailable: bool = False,
) -> ValidationStatus:
    if is_unavailable:
        return ValidationStatus.UNAVAILABLE
    if is_ambiguous:
        return ValidationStatus.AMBIGUOUS
    if needs_review or review_required:
        return ValidationStatus.NEEDS_REVIEW
    if is_incomplete:
        return ValidationStatus.INCOMPLETE
    return ValidationStatus.VALID


def _extract_confidence_safely(
    raw_conf: Any,
    *,
    is_unavailable: bool = False,
    source: Optional[str] = None,
) -> Optional[float]:
    if is_unavailable or (source and source.strip().lower() in _UNAVAILABLE_EXTRACTION_METHODS):
        return None
    if raw_conf is None or isinstance(raw_conf, bool):
        return None
    try:
        val = float(raw_conf)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(val):
        return None
    return round(max(0.0, min(1.0, val)), 4)


def _warnings_from_validation_dict(
    val_dict: Optional[Mapping[str, Any]],
    *,
    source: str,
    element_id: str,
    page_number: int,
) -> List[ExtractionWarning]:
    out: List[ExtractionWarning] = []
    if not val_dict:
        return out
    sev_map = {
        "low": WarningSeverity.LOW,
        "medium": WarningSeverity.MEDIUM,
        "high": WarningSeverity.HIGH,
        "critical": WarningSeverity.CRITICAL,
    }
    for iss in val_dict.get("issues") or []:
        if not isinstance(iss, Mapping):
            continue
        code = str(iss.get("code") or "validation_issue").strip() or "validation_issue"
        detail = str(iss.get("detail") or iss.get("message") or code).strip() or code
        sev = sev_map.get(str(iss.get("severity") or "medium").lower(), WarningSeverity.MEDIUM)
        out.append(
            ExtractionWarning(
                code=code,
                message=detail,
                severity=sev,
                source=source,
                element_id=element_id,
                page_number=page_number,
            )
        )
    return out


_SOURCE_CROP_REF_FIELDS: frozenset[str] = frozenset(SourceCropReference.model_fields.keys())


def _coerce_crop_reference(raw_ref: Any, source_asset_name: str = "") -> Optional[CropReferenceValue]:
    if isinstance(raw_ref, Mapping):
        clean = {k: v for k, v in raw_ref.items() if k in _SOURCE_CROP_REF_FIELDS and v is not None}
        if clean:
            return SourceCropReference.model_validate(clean)
    if isinstance(raw_ref, str) and raw_ref.strip():
        return raw_ref.strip()
    if source_asset_name and source_asset_name.strip():
        return source_asset_name.strip()
    return None


def _coerce_bounding_box_from_dict(
    raw_coords: Optional[Mapping[str, Any]],
    *,
    fallback_bbox: Optional[Sequence[Any]] = None,
    page_width: Optional[float] = None,
    page_height: Optional[float] = None,
    rotation: Optional[int] = None,
) -> Optional[BoundingBox]:
    if not raw_coords:
        return None
    nb = raw_coords.get("normalized_box")
    bb_wh = raw_coords.get("bbox") or fallback_bbox
    if isinstance(nb, (list, tuple)) and len(nb) == 4:
        return BoundingBox.from_normalized_box(
            nb,
            page_bbox_xywh=[max(0.0, float(v)) for v in bb_wh[:4]] if isinstance(bb_wh, (list, tuple)) and len(bb_wh) >= 4 else None,
            page_width=page_width,
            page_height=page_height,
            rotation=rotation,
        )
    return None


def region_dict_to_visual_element(
    region: Mapping[str, Any],
    *,
    source_document_id: str,
    default_page_number: int = 1,
    document_version: Optional[int] = None,
    page_width: Optional[float] = None,
    page_height: Optional[float] = None,
    page_rotation: Optional[int] = None,
) -> AnyVisualElement:
    """
    Convert a LORE ``VisualRegionProvenanceContract`` dictionary (from layout,
    SLANet_plus tables, charts, or forms) into a validated ``lore.visual/1.0``
    typed element without fabricating confidence scores or missing values.
    """
    rid = str(region.get("region_id") or f"p{default_page_number}-region-1").strip() or "region-1"
    page_num = max(1, int(region.get("page_number") or default_page_number))
    raw_rtype = str(region.get("region_type") or VisualElementType.UNKNOWN.value).lower().strip()
    try:
        rtype = VisualElementType(raw_rtype)
    except ValueError:
        rtype = VisualElementType.UNKNOWN

    meta = dict(region.get("metadata") or {})
    src_coords = meta.get("source_coordinates") or {}
    eff_pw = page_width or src_coords.get("page_width")
    eff_ph = page_height or src_coords.get("page_height")
    eff_rot = page_rotation if page_rotation is not None else src_coords.get("source_rotation")
    if eff_rot is not None:
        eff_rot = int(eff_rot) % 360

    bb = BoundingBox.from_normalized_box(
        region.get("normalized_box") or [0, 0, 1000, 1000],
        page_bbox_xywh=(
            [max(0.0, float(v)) for v in (region.get("bbox") or [])[:4]]
            if isinstance(region.get("bbox"), (list, tuple)) and len(region.get("bbox") or []) >= 4
            else None
        ),
        page_width=float(eff_pw) if eff_pw else None,
        page_height=float(eff_ph) if eff_ph else None,
        rotation=eff_rot,
    )

    engine = str(region.get("engine") or "unknown_extractor").strip() or "unknown_extractor"
    engine_ver = str(region.get("engine_version") or "1.0").strip() or "1.0"
    ocr_meta = dict(meta.get("ocr_metadata") or {})
    ocr_unavailable = bool(
        (ocr_meta.get("ocr_triggered") and not ocr_meta.get("ocr_available", True))
        or str(ocr_meta.get("status") or "") == "provider_unavailable"
        or engine in _UNAVAILABLE_EXTRACTION_METHODS
    )
    raw_text = region.get("text")
    content_val: Optional[str] = str(raw_text) if raw_text is not None and str(raw_text).strip() != "" else None
    if content_val and content_val.strip().startswith("[OCR ") and ocr_unavailable:
        content_val = None

    conf = _extract_confidence_safely(
        region.get("confidence"),
        is_unavailable=ocr_unavailable,
        source=engine,
    )
    crop_ref_raw = (
        meta.get("table_crop_reference")
        or meta.get("chart_crop_reference")
        or meta.get("form_crop_reference")
    )
    crop_ref = _coerce_crop_reference(crop_ref_raw, source_asset_name=str(region.get("source_asset_name") or ""))

    prov = ExtractionProvenance(
        source_document_id=source_document_id,
        document_version=document_version,
        page_number=page_num,
        extraction_method=engine,
        extractor_version=engine_ver,
        engine_name=engine,
        language=str(ocr_meta.get("language") or "").strip() or None,
        source_asset_name=str(region.get("source_asset_name") or "") or None,
        source_crop_reference=crop_ref,
        page_rotation=eff_rot,
        is_repaired=bool(region.get("is_repaired", False)),
        is_inference=bool(region.get("is_inference", False)),
    )

    common: Dict[str, Any] = {
        "element_id": rid,
        "element_type": rtype,
        "source_document_id": source_document_id,
        "page_number": page_num,
        "bounding_box": bb,
        "content": content_val,
        "extraction_method": engine,
        "extractor_version": engine_ver,
        "confidence": conf,
        "markdown": str(region.get("markdown") or "") or None,
        "is_repaired": bool(region.get("is_repaired", False)),
        "layout_label": str(meta.get("raw_label") or meta.get("layout_label") or "") or None,
        "layout_confidence": _extract_confidence_safely(meta.get("layout_score")),
        "source_crop_reference": crop_ref,
        "provenance": prov,
    }

    # --- TABLE ELEMENT ---
    if rtype == VisualElementType.TABLE:
        tbl_struct = dict(meta.get("table_structure") or {})
        tbl_val = dict(meta.get("table_validation") or {})
        raw_cells = list(tbl_struct.get("cells") or [])
        cells_out: List[TableCell] = []
        seen_grid_pos: set[Tuple[int, int]] = set()
        for c_idx, rc in enumerate(raw_cells):
            if not isinstance(rc, Mapping):
                continue
            r0 = int(rc.get("row", 0))
            c0 = int(rc.get("col", 0))
            rs = max(1, int(rc.get("rowspan", 1)))
            cs = max(1, int(rc.get("colspan", 1)))
            raw_state = str(rc.get("state") or "unknown").lower()
            try:
                c_status = TableCellStatus(raw_state)
            except ValueError:
                c_status = TableCellStatus.UNKNOWN

            cell_src = str(rc.get("source") or "") or None
            cell_txt = rc.get("text")
            if c_status == TableCellStatus.POPULATED and (cell_txt is None or not str(cell_txt).strip()):
                c_status = TableCellStatus.EMPTY
            if c_status in (TableCellStatus.EMPTY, TableCellStatus.UNREADABLE, TableCellStatus.MISSING):
                cell_val: Optional[str] = None
            else:
                cell_val = str(cell_txt) if cell_txt is not None and str(cell_txt).strip() != "" else None

            cell_conf = _extract_confidence_safely(
                rc.get("confidence"),
                is_unavailable=(c_status == TableCellStatus.MISSING),
                source=cell_src,
            )
            if c_status == TableCellStatus.EMPTY and cell_src in (None, "none") and cell_conf == 0.0:
                cell_conf = None

            cell_bb = _coerce_bounding_box_from_dict(
                {"normalized_box": rc.get("normalized_box"), "bbox": rc.get("bbox")},
                page_width=float(eff_pw) if eff_pw else None,
                page_height=float(eff_ph) if eff_ph else None,
                rotation=eff_rot,
            )
            c_warnings = [
                ExtractionWarning(
                    code=str(w),
                    message=str(w),
                    severity=WarningSeverity.MEDIUM,
                    source=engine,
                    element_id=rid,
                    page_number=page_num,
                    field_path=f"cells[{c_idx}]",
                )
                for w in (rc.get("warnings") or [])
                if str(w).strip()
            ]
            # Avoid duplicate occupied cell collision if noisy raw parser reported overlap
            if (r0, c0) in seen_grid_pos:
                continue
            for rr in range(r0, r0 + rs):
                for cc in range(c0, c0 + cs):
                    seen_grid_pos.add((rr, cc))

            cells_out.append(
                TableCell(
                    cell_id=str(rc.get("cell_id") or f"{rid}-r{r0}c{c0}"),
                    row_index=r0,
                    col_index=c0,
                    row_span=rs,
                    col_span=cs,
                    is_header=bool(rc.get("is_header", False)),
                    status=c_status,
                    value=cell_val,
                    lines=[str(ln) for ln in (rc.get("lines") or [])],
                    source=cell_src,
                    confidence=cell_conf,
                    bounding_box=cell_bb,
                    needs_review=bool(rc.get("needs_review", False)),
                    warnings=c_warnings,
                )
            )

        num_rows = int(tbl_struct.get("num_rows") or (max((c.row_index + c.row_span for c in cells_out), default=0)))
        num_cols = int(tbl_struct.get("num_cols") or (max((c.col_index + c.col_span for c in cells_out), default=0)))
        raw_hdrs = list(tbl_struct.get("headers") or [])
        headers_out = [
            (str(h) if h is not None and str(h).strip() != "" else None)
            for h in raw_hdrs[:num_cols]
        ] if raw_hdrs and num_cols > 0 else []
        if headers_out and len(headers_out) < num_cols:
            headers_out.extend([None] * (num_cols - len(headers_out)))

        warnings_out = _warnings_from_validation_dict(
            tbl_val, source="table_validator", element_id=rid, page_number=page_num
        )
        v_stat = _map_validation_status(
            needs_review=bool(tbl_val.get("needs_review", meta.get("needs_review", False))),
            is_unavailable=(meta.get("structure_fallback_applied") and not cells_out),
        )
        return TableElement(
            **common,
            validation_status=v_stat,
            warnings=warnings_out,
            num_rows=num_rows,
            num_cols=num_cols,
            headers=headers_out,
            header_row_indices=[int(i) for i in (tbl_struct.get("header_row_indices") or []) if 0 <= int(i) < num_rows],
            cells=cells_out,
            footnotes=[str(fn) for fn in (tbl_struct.get("footnotes") or []) if str(fn).strip()],
            has_merged_cells=bool(tbl_struct.get("has_merged_cells", False)),
            structure_confidence=_extract_confidence_safely(tbl_struct.get("structure_score")),
        )

    # --- CHART ELEMENT ---
    if rtype == VisualElementType.CHART:
        ch_payload = dict(meta.get("chart") or {})
        ch_val = dict(meta.get("chart_validation") or {})
        raw_ctype = str(ch_payload.get("chart_type") or ChartType.UNKNOWN.value).lower()
        try:
            c_type = ChartType(raw_ctype)
        except ValueError:
            c_type = ChartType.UNKNOWN

        raw_smode = ch_payload.get("source_mode")
        src_mode_enum: Optional[SourceMode] = None
        if raw_smode:
            try:
                src_mode_enum = SourceMode(str(raw_smode).lower())
            except ValueError:
                src_mode_enum = None

        axes_out: List[ChartAxis] = []
        raw_axes = dict(ch_payload.get("axes") or {})
        for ax_key, ax_id in (("x", "x"), ("y_primary", "y1"), ("y_secondary", "y2")):
            ax_d = raw_axes.get(ax_key)
            if not isinstance(ax_d, Mapping) or not ax_d:
                continue
            if ax_key == "y_secondary" and not ax_d.get("present"):
                continue
            axes_out.append(
                ChartAxis(
                    axis_id=ax_id,
                    label=str(ax_d.get("label") or "") or None,
                    unit=str(ax_d.get("unit") or "") or None,
                    scale_type=str(ax_d.get("scale_type") or "") or None,
                    is_calibrated=bool(ax_d.get("is_valid", False)),
                    origin_value=ax_d.get("origin_value"),
                    min_value=ax_d.get("axis_min_value"),
                    max_value=ax_d.get("axis_max_value"),
                    contains_zero=ax_d.get("contains_zero"),
                    estimated_uncertainty=ax_d.get("estimated_uncertainty"),
                    tick_values=list(ax_d.get("tick_values") or []),
                    calibration_reason=str(ax_d.get("reason") or "") or None,
                )
            )

        series_out: List[ChartSeries] = []
        for s_idx, rs in enumerate(ch_payload.get("series") or [], start=1):
            if not isinstance(rs, Mapping):
                continue
            pts_out: List[ChartDataPoint] = []
            for p_idx, dp in enumerate(rs.get("data_points") or [], start=1):
                if not isinstance(dp, Mapping):
                    continue
                raw_prec = str(dp.get("precision") or ChartValuePrecision.UNAVAILABLE.value).lower()
                try:
                    prec_enum = ChartValuePrecision(raw_prec)
                except ValueError:
                    prec_enum = ChartValuePrecision.UNAVAILABLE
                dp_val = dp.get("value")
                if prec_enum == ChartValuePrecision.UNAVAILABLE or dp_val is None:
                    prec_enum = ChartValuePrecision.UNAVAILABLE
                    dp_val = None
                    cum_val = None
                    pct_val = None
                else:
                    cum_val = dp.get("cumulative_value")
                    pct_val = dp.get("percentage")

                dp_bb = _coerce_bounding_box_from_dict(
                    {"normalized_box": dp.get("normalized_box"), "bbox": dp.get("bbox")},
                    page_width=float(eff_pw) if eff_pw else None,
                    page_height=float(eff_ph) if eff_ph else None,
                    rotation=eff_rot,
                )
                pts_out.append(
                    ChartDataPoint(
                        point_id=f"{rid}-s{s_idx}-p{p_idx}",
                        category=str(dp.get("category")) if dp.get("category") is not None else None,
                        x=dp.get("x"),
                        value=dp_val,
                        precision=prec_enum,
                        unit=str(dp.get("unit") or "") or None,
                        uncertainty=None if prec_enum == ChartValuePrecision.EXACT else dp.get("uncertainty"),
                        axis_id=str(dp.get("axis") or rs.get("axis") or "") or None,
                        source=str(dp.get("source") or "") or None,
                        cumulative_value=cum_val,
                        percentage=pct_val,
                        bounding_box=dp_bb,
                    )
                )

            c_hex = str(rs.get("color_hex") or "").strip() or None
            series_out.append(
                ChartSeries(
                    series_id=f"{rid}-s{s_idx}",
                    name=str(rs.get("name")) if rs.get("name") is not None else None,
                    axis_id=str(rs.get("axis") or "") or None,
                    unit=str(rs.get("unit") or "") or None,
                    color_hex=c_hex if (c_hex and _HEX_COLOR_RE.match(c_hex)) else None,
                    data_points=pts_out,
                )
            )

        warnings_out = _warnings_from_validation_dict(
            ch_val, source="chart_validator", element_id=rid, page_number=page_num
        )
        v_stat = _map_validation_status(
            needs_review=bool(ch_val.get("needs_review", False)),
            review_required=bool(ch_val.get("review_required", False)),
            is_unavailable=(c_type == ChartType.UNKNOWN and not series_out),
        )
        raw_legends = [
            str(lg.get("text") or lg) if isinstance(lg, Mapping) else str(lg)
            for lg in (ch_payload.get("legends") or [])
            if (lg.get("text") if isinstance(lg, Mapping) else lg)
        ]
        return ChartElement(
            **common,
            validation_status=v_stat,
            warnings=warnings_out,
            chart_type=c_type,
            title=str(ch_payload.get("title") or "") or None,
            source_mode=src_mode_enum,
            categories=[str(c) if c is not None else None for c in (ch_payload.get("categories") or [])],
            axes=axes_out,
            series=series_out,
            legends=raw_legends,
        )

    # --- FORM ELEMENT ---
    if rtype in (VisualElementType.FORM, VisualElementType.FORM_KV):
        f_payload = dict(meta.get("form") or {})
        f_val = dict(meta.get("form_validation") or {})
        fields_out: List[FormField] = []
        used_fids: set[str] = set()

        def _uniq_fid(base: str) -> str:
            cand = base
            n = 2
            while cand in used_fids:
                cand = f"{base}_{n}"
                n += 1
            used_fids.add(cand)
            return cand

        # Standard form key-value fields
        for rf in f_payload.get("fields") or []:
            if not isinstance(rf, Mapping):
                continue
            fid = _uniq_fid(str(rf.get("field_id") or f"fld_{len(used_fids) + 1}"))
            raw_st = str(rf.get("status") or "unknown").lower()
            if raw_st == "blank" or rf.get("is_blank"):
                fst = FormFieldStatus.EMPTY
            else:
                try:
                    fst = FormFieldStatus(raw_st)
                except ValueError:
                    fst = FormFieldStatus.UNKNOWN
            raw_ft = str(rf.get("field_type") or "text").lower()
            try:
                ftype = FormFieldType(raw_ft)
            except ValueError:
                ftype = FormFieldType.UNKNOWN

            f_src = str(rf.get("source") or "") or None
            if fst in (FormFieldStatus.EMPTY, FormFieldStatus.UNREADABLE, FormFieldStatus.SIGNATURE_BLANK):
                f_val_str = None
                f_num = None
            else:
                raw_v = rf.get("raw_value", rf.get("value"))
                f_val_str = str(raw_v) if raw_v is not None and str(raw_v).strip() != "" else None
                f_num = rf.get("numeric_value")
                if fst == FormFieldStatus.POPULATED and f_val_str is None:
                    fst = FormFieldStatus.EMPTY

            f_conf = _extract_confidence_safely(rf.get("confidence"), source=f_src)
            if fst == FormFieldStatus.EMPTY and f_src in (None, "structural_slot") and f_conf == 0.0:
                f_conf = None

            fields_out.append(
                FormField(
                    field_id=fid,
                    label=str(rf.get("label")) if rf.get("label") is not None else None,
                    field_type=ftype,
                    value=f_val_str,
                    numeric_value=f_num,
                    currency=str(rf.get("currency") or "") or None,
                    unit=str(rf.get("unit") or "") or None,
                    status=fst,
                    is_ambiguous=bool(rf.get("is_ambiguous", False)),
                    ambiguity_reason=str(rf.get("ambiguity_reason") or "") or None,
                    possibly_handwritten=bool(rf.get("possibly_handwritten", False)),
                    is_approval_field=bool(rf.get("is_approval_field", False)),
                    confidence=f_conf,
                    column_index=rf.get("column_index"),
                    source=f_src,
                    bounding_box=_coerce_bounding_box_from_dict(rf.get("field_coordinates"), page_width=float(eff_pw) if eff_pw else None, page_height=float(eff_ph) if eff_ph else None, rotation=eff_rot),
                    label_bounding_box=_coerce_bounding_box_from_dict(rf.get("label_coordinates"), page_width=float(eff_pw) if eff_pw else None, page_height=float(eff_ph) if eff_ph else None, rotation=eff_rot),
                    value_bounding_box=_coerce_bounding_box_from_dict(rf.get("value_coordinates"), page_width=float(eff_pw) if eff_pw else None, page_height=float(eff_ph) if eff_ph else None, rotation=eff_rot),
                )
            )

        # Checkboxes
        for cb in f_payload.get("checkboxes") or []:
            if not isinstance(cb, Mapping):
                continue
            cid = _uniq_fid(str(cb.get("checkbox_id") or f"cb_{len(used_fids) + 1}"))
            st_raw = str(cb.get("state") or "unknown").lower()
            sel = SelectionState(st_raw) if st_raw in {"checked", "unchecked", "unknown"} else SelectionState.UNKNOWN
            cb_status = {
                SelectionState.CHECKED: FormFieldStatus.CHECKED,
                SelectionState.UNCHECKED: FormFieldStatus.UNCHECKED,
                SelectionState.UNKNOWN: FormFieldStatus.UNKNOWN,
            }[sel]
            fields_out.append(
                FormField(
                    field_id=cid,
                    label=str(cb.get("label")) if cb.get("label") is not None else None,
                    field_type=FormFieldType.CHECKBOX,
                    value=None if sel == SelectionState.UNKNOWN else sel.value,
                    status=cb_status,
                    selection_state=sel,
                    is_ambiguous=bool(cb.get("is_ambiguous", False)),
                    ambiguity_reason=str(cb.get("ambiguity_reason") or "") or None,
                    is_approval_field=bool(cb.get("is_approval_field", False)),
                    confidence=_extract_confidence_safely(cb.get("confidence")),
                    source=str(cb.get("detection_method") or "") or None,
                    bounding_box=_coerce_bounding_box_from_dict(cb.get("checkbox_coordinates"), page_width=float(eff_pw) if eff_pw else None, page_height=float(eff_ph) if eff_ph else None, rotation=eff_rot),
                    label_bounding_box=_coerce_bounding_box_from_dict(cb.get("label_coordinates"), page_width=float(eff_pw) if eff_pw else None, page_height=float(eff_ph) if eff_ph else None, rotation=eff_rot),
                )
            )

        # Radio groups + options
        radio_groups_out: List[FormRadioGroup] = []
        for rg in f_payload.get("radio_groups") or []:
            if not isinstance(rg, Mapping):
                continue
            gid = str(rg.get("group_id") or f"rg_{len(radio_groups_out) + 1}")
            opt_ids: List[str] = []
            for opt in rg.get("options") or []:
                if not isinstance(opt, Mapping):
                    continue
                oid = _uniq_fid(str(opt.get("radio_id") or f"{gid}_opt_{len(opt_ids) + 1}"))
                opt_ids.append(oid)
                st_raw = str(opt.get("state") or "unknown").lower()
                sel = SelectionState(st_raw) if st_raw in {"checked", "unchecked", "unknown"} else SelectionState.UNKNOWN
                r_status = {
                    SelectionState.CHECKED: FormFieldStatus.CHECKED,
                    SelectionState.UNCHECKED: FormFieldStatus.UNCHECKED,
                    SelectionState.UNKNOWN: FormFieldStatus.UNKNOWN,
                }[sel]
                fields_out.append(
                    FormField(
                        field_id=oid,
                        label=str(opt.get("label")) if opt.get("label") is not None else None,
                        field_type=FormFieldType.RADIO,
                        value=None if sel == SelectionState.UNKNOWN else sel.value,
                        status=r_status,
                        selection_state=sel,
                        is_ambiguous=bool(opt.get("is_ambiguous", False)),
                        ambiguity_reason=str(opt.get("ambiguity_reason") or "") or None,
                        confidence=_extract_confidence_safely(opt.get("confidence")),
                        source=str(opt.get("detection_method") or "") or None,
                        bounding_box=_coerce_bounding_box_from_dict(opt.get("radio_coordinates"), page_width=float(eff_pw) if eff_pw else None, page_height=float(eff_ph) if eff_ph else None, rotation=eff_rot),
                        label_bounding_box=_coerce_bounding_box_from_dict(opt.get("label_coordinates"), page_width=float(eff_pw) if eff_pw else None, page_height=float(eff_ph) if eff_ph else None, rotation=eff_rot),
                    )
                )
            sel_opts = list(rg.get("selected_options") or [])
            radio_groups_out.append(
                FormRadioGroup(
                    group_id=gid,
                    label=None,
                    option_field_ids=opt_ids,
                    selected_value=str(sel_opts[0]) if len(sel_opts) == 1 else None,
                    is_ambiguous=bool(rg.get("is_ambiguous", False)),
                    ambiguity_reason=str(rg.get("ambiguity_reason") or "") or None,
                )
            )

        # Signature regions (presence only, never signer identity)
        for sig in f_payload.get("signature_regions") or []:
            if not isinstance(sig, Mapping):
                continue
            sid = _uniq_fid(str(sig.get("signature_id") or f"sig_{len(used_fids) + 1}"))
            st_raw = str(sig.get("status") or "unknown").lower()
            try:
                sig_st = FormFieldStatus(st_raw)
            except ValueError:
                sig_st = FormFieldStatus.UNKNOWN
            fields_out.append(
                FormField(
                    field_id=sid,
                    label=str(sig.get("label")) if sig.get("label") is not None else None,
                    field_type=FormFieldType.SIGNATURE_REGION,
                    value=None,
                    status=sig_st,
                    is_approval_field=bool(sig.get("is_approval_field", False)),
                    confidence=_extract_confidence_safely(sig.get("confidence")),
                    source="signature_roi_ink_detector",
                    bounding_box=_coerce_bounding_box_from_dict(sig.get("signature_coordinates"), page_width=float(eff_pw) if eff_pw else None, page_height=float(eff_ph) if eff_ph else None, rotation=eff_rot),
                    label_bounding_box=_coerce_bounding_box_from_dict(sig.get("label_coordinates"), page_width=float(eff_pw) if eff_pw else None, page_height=float(eff_ph) if eff_ph else None, rotation=eff_rot),
                )
            )

        warnings_out = _warnings_from_validation_dict(
            f_val, source="form_validator", element_id=rid, page_number=page_num
        )
        v_stat = _map_validation_status(
            needs_review=bool(f_val.get("needs_review", meta.get("needs_review", False))),
            review_required=bool(f_val.get("review_required", False)),
            is_ambiguous=bool(f_payload.get("ambiguous_fields")),
            is_incomplete=(f_payload.get("is_complete") is False),
        )
        col_cnt = f_payload.get("column_count")
        return FormElement(
            **common,
            validation_status=v_stat,
            warnings=warnings_out,
            form_subtype=str(f_payload.get("form_subtype") or "") or None,
            source_mode=str(f_payload.get("source_mode") or "") or None,
            column_count=int(col_cnt) if col_cnt and int(col_cnt) >= 1 else None,
            fields=fields_out,
            radio_groups=radio_groups_out,
        )

    # --- TEXT ELEMENT ---
    if rtype in (
        VisualElementType.TEXT,
        VisualElementType.TITLE_HEADING,
        VisualElementType.PARAGRAPH,
        VisualElementType.HEADER_FOOTER,
    ):
        role_map = {
            VisualElementType.TITLE_HEADING: TextRole.HEADING,
            VisualElementType.PARAGRAPH: TextRole.PARAGRAPH,
            VisualElementType.HEADER_FOOTER: TextRole.HEADER,
            VisualElementType.TEXT: TextRole.UNKNOWN,
        }
        v_stat = _map_validation_status(
            needs_review=bool(meta.get("needs_review", False)),
            is_unavailable=ocr_unavailable,
        )
        lines = [ln for ln in (content_val or "").splitlines() if ln.strip()] if content_val else []
        return TextElement(
            **common,
            validation_status=v_stat,
            text_role=role_map.get(rtype, TextRole.UNKNOWN),
            language=str(ocr_meta.get("language") or "") or None,
            word_count=len((content_val or "").split()) if content_val is not None else None,
            lines=lines,
        )

    # --- GENERIC VISUAL ELEMENT ---
    v_stat = _map_validation_status(
        needs_review=bool(meta.get("needs_review", False)),
        is_unavailable=ocr_unavailable and content_val is None,
    )
    return VisualElement(**common, validation_status=v_stat)


def pages_to_visual_document(
    pages: Sequence[Mapping[str, Any]],
    *,
    source_document_id: str,
    document_version: Optional[int] = None,
    title: Optional[str] = None,
    filename: Optional[str] = None,
    document_type: Optional[str] = None,
    schema_version: str = VISUAL_SCHEMA_ID,
) -> VisualDocument:
    """
    Convert a sequence of LORE extracted page payloads (``CanonicalExtractedPageContract``)
    into a strictly validated ``VisualDocument`` (``lore.visual/1.0``).
    """
    pages_out: List[VisualPage] = []
    elements_out: List[AnyVisualElement] = []
    doc_warnings: List[ExtractionWarning] = []
    seen_ids: set[str] = set()

    max_page_num = max((int(p.get("page_number") or 1) for p in pages), default=1)
    page_count = max(1, len(pages), max_page_num)

    for p_idx, page in enumerate(pages, start=1):
        p_num = max(1, int(page.get("page_number") or p_idx))
        pw_raw = page.get("width")
        ph_raw = page.get("height")
        pw = float(pw_raw) if isinstance(pw_raw, (int, float)) and float(pw_raw) > 0 else None
        ph = float(ph_raw) if isinstance(ph_raw, (int, float)) and float(ph_raw) > 0 else None
        rot = int(page.get("rotation") or 0) % 360

        p_engine = str(page.get("engine") or "").strip() or None
        p_ver = str(page.get("engine_version") or "").strip() or None
        p_unavail = bool(page.get("is_optional_skipped", False)) or str(page.get("status") or "") == "provider_unavailable"
        p_conf = _extract_confidence_safely(page.get("confidence"), is_unavailable=p_unavail, source=p_engine)
        p_warns = [
            ExtractionWarning(
                code="page_extraction_warning",
                message=str(w),
                severity=WarningSeverity.MEDIUM,
                source=p_engine or "page_extractor",
                page_number=p_num,
            )
            for w in (page.get("warnings") or [])
            if str(w).strip()
        ]
        p_status = _map_validation_status(
            needs_review=bool(page.get("needs_review", False)),
            is_unavailable=p_unavail,
        )
        pages_out.append(
            VisualPage(
                page_number=p_num,
                width=pw,
                height=ph,
                rotation=rot,
                page_classification=str(page.get("page_classification") or "") or None,
                extraction_method=p_engine,
                extractor_version=p_ver,
                confidence=p_conf,
                validation_status=p_status,
                warnings=p_warns,
            )
        )

        for r_idx, reg in enumerate(page.get("visual_regions") or [], start=1):
            if not isinstance(reg, Mapping):
                continue
            reg_copy = dict(reg)
            base_id = str(reg_copy.get("region_id") or f"p{p_num}-region-{r_idx}").strip() or f"p{p_num}-region-{r_idx}"
            cand_id = base_id
            suffix = 2
            while cand_id in seen_ids:
                cand_id = f"{base_id}-{suffix}"
                suffix += 1
            seen_ids.add(cand_id)
            reg_copy["region_id"] = cand_id
            elements_out.append(
                region_dict_to_visual_element(
                    reg_copy,
                    source_document_id=source_document_id,
                    default_page_number=p_num,
                    document_version=document_version,
                    page_width=pw,
                    page_height=ph,
                    page_rotation=rot,
                )
            )

    doc_status = ValidationStatus.VALID
    if any(el.validation_status == ValidationStatus.UNAVAILABLE for el in elements_out) or any(
        p.validation_status == ValidationStatus.UNAVAILABLE for p in pages_out
    ):
        if all(p.validation_status == ValidationStatus.UNAVAILABLE for p in pages_out) and not elements_out:
            doc_status = ValidationStatus.UNAVAILABLE
        else:
            doc_status = ValidationStatus.NEEDS_REVIEW
    elif any(
        el.validation_status in (ValidationStatus.NEEDS_REVIEW, ValidationStatus.AMBIGUOUS, ValidationStatus.INCOMPLETE)
        for el in elements_out
    ) or any(p.validation_status == ValidationStatus.NEEDS_REVIEW for p in pages_out):
        doc_status = ValidationStatus.NEEDS_REVIEW

    return VisualDocument(
        schema_version=schema_version,
        source_document_id=source_document_id,
        document_version=document_version,
        title=title,
        filename=filename,
        document_type=document_type,
        page_count=page_count,
        pages=pages_out,
        elements=elements_out,
        validation_status=doc_status,
        warnings=doc_warnings,
    )


def migrate_visual_payload(
    payload: Mapping[str, Any],
    *,
    source_document_id: Optional[str] = None,
) -> VisualDocument:
    """
    Upgrade backward-compatible payloads into a validated ``VisualDocument``:
    - Accepts ``lore.visual/1.0`` and minor ``lore.visual/1.x`` payloads directly.
    - Converts legacy single-page ``CanonicalExtractedPageContract`` dicts (with
      ``page_number`` / ``visual_regions`` and no ``schema_version``) into ``lore.visual/1.0``.
    - Rejects incompatible major versions (e.g. ``lore.visual/2.0``) or Governance envelopes
      (``lore.result/1``, ``lore.result/2``).
    """
    if not isinstance(payload, Mapping):
        raise ValueError("Visual payload must be a mapping/dictionary")

    if "schema_version" in payload or "schema" in payload:
        return VisualDocument.model_validate(payload)

    # Legacy pre-schema LORE single-page or multi-page container
    if "pages" in payload and isinstance(payload.get("pages"), list):
        doc_id = source_document_id or str(payload.get("source_document_id") or "").strip()
        if not doc_id:
            raise ValueError("Legacy multi-page payload requires source_document_id")
        return pages_to_visual_document(payload["pages"], source_document_id=doc_id)

    if "page_number" in payload or "visual_regions" in payload:
        doc_id = source_document_id or str(payload.get("source_document_id") or "").strip()
        if not doc_id:
            raise ValueError("Legacy page payload requires source_document_id")
        return pages_to_visual_document([payload], source_document_id=doc_id)

    # Unversioned modern-shape dict defaults strictly to lore.visual/1.0
    return VisualDocument.model_validate(payload)


def validate_visual_document_payload(payload: Union[str, bytes, Mapping[str, Any]]) -> VisualDocument:
    """Strict entry point validating JSON string/bytes or dict against ``lore.visual/1.x``."""
    if isinstance(payload, (str, bytes)):
        return VisualDocument.from_json(payload)
    if isinstance(payload, Mapping):
        return VisualDocument.from_dict(payload)
    raise TypeError(f"Expected JSON str/bytes or mapping, got {type(payload).__name__}")


def _truncate_str(value: str, limit: int = 50) -> str:
    return value[:limit] if len(value) > limit else value


def _render_table_element_text(el: TableElement) -> str:
    """Render TableElement to pipe-delimited Markdown without shifting columns or fabricating blanks."""
    lines: List[str] = []
    if el.num_cols <= 0:
        if el.markdown and el.markdown.strip():
            lines.append(el.markdown.strip())
        elif el.content and el.content.strip():
            lines.append(el.content.strip())
        return "\n".join(lines)

    grid: Dict[Tuple[int, int], str] = {}
    for cell in el.cells:
        if cell.status == TableCellStatus.POPULATED:
            cell_txt = (cell.value or "").replace("\n", " / ").replace("|", "\\|").strip()
            if cell.unit and cell.unit not in cell_txt:
                cell_txt = f"{cell_txt} {cell.unit}".strip()
        elif cell.status == TableCellStatus.EMPTY:
            cell_txt = ""
        else:
            cell_txt = f"[{cell.status.value.upper()}]"
        grid[(cell.row_index, cell.col_index)] = cell_txt

    headers: List[str] = []
    has_explicit_headers = bool(el.headers)
    for c_idx in range(el.num_cols):
        if has_explicit_headers and c_idx < len(el.headers):
            hdr = el.headers[c_idx]
            headers.append((hdr or f"col_{c_idx + 1}_unknown").replace("|", "\\|").strip())
        else:
            headers.append(f"col_{c_idx + 1}")

    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * el.num_cols) + " |")

    header_row_set = set(el.header_row_indices)
    for r_idx in range(el.num_rows):
        if r_idx in header_row_set and has_explicit_headers:
            continue
        row_cells = [grid.get((r_idx, c_idx), "") for c_idx in range(el.num_cols)]
        lines.append("| " + " | ".join(row_cells) + " |")

    for fn in el.footnotes:
        if fn and fn.strip():
            lines.append(f"Footnote: {fn.strip()}")

    return "\n".join(lines)


def _render_chart_element_text(el: ChartElement) -> str:
    """Render ChartElement with explicit precision tags (exact/estimated/unavailable)."""
    lines: List[str] = []
    title_part = f": {el.title.strip()}" if el.title and el.title.strip() else ""
    lines.append(f"[Chart ({el.chart_type.value}){title_part}]")
    if el.axes:
        ax_parts = []
        for ax in el.axes:
            unit_part = f" ({ax.unit})" if ax.unit else ""
            label_part = ax.label or ax.axis_id
            cal_part = "calibrated" if ax.is_calibrated else "uncalibrated"
            range_part = ""
            if ax.min_value is not None or ax.max_value is not None:
                range_part = f" [{ax.min_value}..{ax.max_value}]"
            ax_parts.append(f"{ax.axis_id}={label_part}{unit_part}{range_part} [{cal_part}]")
        lines.append("Axes: " + "; ".join(ax_parts))
    for ser in el.series:
        s_name = ser.name or ser.series_id
        s_unit = f" {ser.unit}" if ser.unit else ""
        pts = []
        for dp in ser.data_points:
            cat = dp.category if dp.category is not None else (str(dp.x) if dp.x is not None else dp.point_id)
            if dp.precision == ChartValuePrecision.UNAVAILABLE or dp.value is None:
                pts.append(f"{cat}=UNAVAILABLE")
            else:
                unit_suffix = dp.unit or s_unit.strip()
                u_str = f" {unit_suffix}" if unit_suffix else ""
                pts.append(f"{cat}={dp.value}{u_str} [{dp.precision.value}]")
        lines.append(f"Series {s_name}: " + (", ".join(pts) if pts else "[no data points]"))
    if el.content and el.content.strip() and not el.series:
        lines.append(el.content.strip())
    return "\n".join(lines)


def _render_form_element_text(el: FormElement) -> str:
    """Render FormElement fields deterministically without inferring approval or signer identity."""
    lines: List[str] = []
    subtype = el.form_subtype or "form"
    lines.append(f"[Form ({subtype})]")
    for fld in el.fields:
        lbl = (fld.label or fld.field_id).strip()
        meta_bits = [fld.field_type.value, f"status={fld.status.value}"]
        if fld.selection_state is not None:
            meta_bits.append(f"selection={fld.selection_state.value}")
        if fld.is_ambiguous:
            meta_bits.append("ambiguous=true")
        if fld.possibly_handwritten:
            meta_bits.append("handwritten=true")
        if fld.value is not None and fld.value.strip():
            val_str = fld.value.strip()
        else:
            val_str = f"[{fld.status.value.upper()}]"
        lines.append(f"- {lbl} ({', '.join(meta_bits)}): {val_str}")
    if not el.fields and el.content and el.content.strip():
        lines.append(el.content.strip())
    return "\n".join(lines)


def extract_visual_document_screenable_text(vdoc: VisualDocument) -> str:
    """
    Collect all textual content embedded inside a validated ``VisualDocument``
    so Stage 2 deep security screening and Stage 5 conflict pre-scan cover every
    narrative block, table header/cell/footnote, chart label/series, form field,
    and warning without any blind spots.
    """
    if not isinstance(vdoc, VisualDocument):
        vdoc = validate_visual_document_payload(vdoc)

    parts: List[str] = []
    if vdoc.title:
        parts.append(vdoc.title)
    if vdoc.filename:
        parts.append(vdoc.filename)

    for w in vdoc.warnings:
        parts.append(w.message)
    for pg in vdoc.pages:
        for w in pg.warnings:
            parts.append(w.message)

    for el in vdoc.elements:
        if el.content:
            parts.append(el.content)
        if el.markdown:
            parts.append(el.markdown)
        for w in el.warnings:
            parts.append(w.message)
        if isinstance(el, TextElement):
            parts.extend(line for line in el.lines if line)
        elif isinstance(el, TableElement):
            parts.extend(h for h in el.headers if h)
            for cell in el.cells:
                if cell.value:
                    parts.append(cell.value)
                parts.extend(line for line in cell.lines if line)
                if cell.unit:
                    parts.append(cell.unit)
                for cw in cell.warnings:
                    parts.append(cw.message)
            parts.extend(fn for fn in el.footnotes if fn)
        elif isinstance(el, ChartElement):
            if el.title:
                parts.append(el.title)
            parts.extend(c for c in el.categories if c)
            parts.extend(lg for lg in el.legends if lg)
            for ax in el.axes:
                if ax.label:
                    parts.append(ax.label)
                if ax.unit:
                    parts.append(ax.unit)
                if ax.calibration_reason:
                    parts.append(ax.calibration_reason)
            for ser in el.series:
                if ser.name:
                    parts.append(ser.name)
                if ser.unit:
                    parts.append(ser.unit)
                for dp in ser.data_points:
                    if dp.category:
                        parts.append(dp.category)
                    if dp.unit:
                        parts.append(dp.unit)
                    if dp.value is not None:
                        parts.append(str(dp.value))
        elif isinstance(el, FormElement):
            for fld in el.fields:
                if fld.label:
                    parts.append(fld.label)
                if fld.value:
                    parts.append(fld.value)
                if fld.ambiguity_reason:
                    parts.append(fld.ambiguity_reason)
                for fw in fld.warnings:
                    parts.append(fw.message)
            for rg in el.radio_groups:
                if rg.label:
                    parts.append(rg.label)
                if rg.selected_value:
                    parts.append(rg.selected_value)
                if rg.ambiguity_reason:
                    parts.append(rg.ambiguity_reason)

    return "\n".join(p.strip() for p in parts if isinstance(p, str) and p.strip())


def assess_visual_document_settlement_readiness(vdoc: VisualDocument) -> Dict[str, Any]:
    """
    Evaluate structural/extraction readiness of a validated ``VisualDocument``
    without inferring document authority, approval, sufficiency, or authorization.

    Distinguishes:
    - ``rejected``: invalid/unavailable document-level status or zero readable content.
    - ``needs_review``: incomplete, uncertain, ambiguous, unreadable, uncalibrated,
      estimated-only, or unmeasured confidence requiring human verification.
    - ``valid``: clean complete extraction ready to proceed through remaining stages.
    """
    if not isinstance(vdoc, VisualDocument):
        vdoc = validate_visual_document_payload(vdoc)

    doc_status = vdoc.validation_status
    incomplete_element_ids: List[str] = []
    invalid_element_ids: List[str] = []
    ambiguous_field_ids: List[str] = []
    unreadable_cell_ids: List[str] = []
    missing_cell_ids: List[str] = []
    unavailable_chart_point_ids: List[str] = []
    estimated_chart_point_ids: List[str] = []
    approval_field_ids: List[str] = []
    measured_confidences: List[float] = []
    warning_codes: List[str] = [w.code for w in vdoc.warnings]

    for pg in vdoc.pages:
        if pg.confidence is not None:
            measured_confidences.append(float(pg.confidence))
        if pg.validation_status in (ValidationStatus.INVALID, ValidationStatus.UNAVAILABLE):
            invalid_element_ids.append(f"page:{pg.page_number}")
        elif pg.validation_status != ValidationStatus.VALID:
            incomplete_element_ids.append(f"page:{pg.page_number}")
        warning_codes.extend(w.code for w in pg.warnings)

    for el in vdoc.elements:
        if el.confidence is not None:
            measured_confidences.append(float(el.confidence))
        warning_codes.extend(w.code for w in el.warnings)
        if el.validation_status in (ValidationStatus.INVALID, ValidationStatus.UNAVAILABLE):
            invalid_element_ids.append(el.element_id)
        elif el.validation_status in (
            ValidationStatus.INCOMPLETE,
            ValidationStatus.NEEDS_REVIEW,
            ValidationStatus.AMBIGUOUS,
        ):
            incomplete_element_ids.append(el.element_id)

        if isinstance(el, TableElement):
            for idx, cell in enumerate(el.cells):
                cid = cell.cell_id or f"{el.element_id}:r{cell.row_index}c{cell.col_index}_{idx}"
                if cell.confidence is not None:
                    measured_confidences.append(float(cell.confidence))
                warning_codes.extend(w.code for w in cell.warnings)
                if cell.status in (TableCellStatus.UNREADABLE, TableCellStatus.UNKNOWN):
                    unreadable_cell_ids.append(cid)
                elif cell.status == TableCellStatus.MISSING:
                    missing_cell_ids.append(cid)
                elif cell.needs_review:
                    incomplete_element_ids.append(cid)

        elif isinstance(el, ChartElement):
            for ax in el.axes:
                if not ax.is_calibrated:
                    incomplete_element_ids.append(f"{el.element_id}:axis:{ax.axis_id}")
            for ser in el.series:
                for dp in ser.data_points:
                    if dp.precision == ChartValuePrecision.UNAVAILABLE:
                        unavailable_chart_point_ids.append(dp.point_id)
                    elif dp.precision == ChartValuePrecision.ESTIMATED:
                        estimated_chart_point_ids.append(dp.point_id)

        elif isinstance(el, FormElement):
            for fld in el.fields:
                if fld.confidence is not None:
                    measured_confidences.append(float(fld.confidence))
                warning_codes.extend(w.code for w in fld.warnings)
                if fld.is_approval_field:
                    approval_field_ids.append(fld.field_id)
                if fld.is_ambiguous or fld.status in (
                    FormFieldStatus.UNREADABLE,
                    FormFieldStatus.UNKNOWN,
                    FormFieldStatus.AMBIGUOUS,
                    FormFieldStatus.LOW_CONFIDENCE,
                ) or fld.selection_state == SelectionState.UNKNOWN or fld.possibly_handwritten:
                    ambiguous_field_ids.append(fld.field_id)
            for rg in el.radio_groups:
                if rg.is_ambiguous:
                    ambiguous_field_ids.append(rg.group_id)

    screenable = extract_visual_document_screenable_text(vdoc)
    has_substantive_elements = any(
        isinstance(el, (TextElement, TableElement, ChartElement, FormElement))
        for el in vdoc.elements
    )

    measured_avg: Optional[float] = None
    if measured_confidences:
        measured_avg = round(sum(measured_confidences) / len(measured_confidences), 4)

    rejected_reasons: List[str] = []
    if doc_status in (ValidationStatus.INVALID, ValidationStatus.UNAVAILABLE):
        rejected_reasons.append(f"visual_document validation_status={doc_status.value!r}")
    if not screenable and not has_substantive_elements:
        rejected_reasons.append("visual_document contains zero extractable text or visual elements")
    if vdoc.elements and len(invalid_element_ids) == len(vdoc.elements) and not screenable:
        rejected_reasons.append("all extracted visual elements are invalid or unavailable")

    review_reasons: List[str] = []
    if doc_status in (ValidationStatus.INCOMPLETE, ValidationStatus.NEEDS_REVIEW, ValidationStatus.AMBIGUOUS):
        review_reasons.append(f"visual_document validation_status={doc_status.value!r}")
    if invalid_element_ids and not rejected_reasons:
        review_reasons.append(f"partial invalid/unavailable regions: {invalid_element_ids[:10]}")
    if incomplete_element_ids:
        review_reasons.append(f"incomplete or review_required items: {incomplete_element_ids[:10]}")
    if unreadable_cell_ids or missing_cell_ids:
        review_reasons.append(
            f"uncertain table cells (unreadable={len(unreadable_cell_ids)}, missing={len(missing_cell_ids)})"
        )
    if ambiguous_field_ids:
        review_reasons.append(f"ambiguous or low-confidence form fields: {ambiguous_field_ids[:10]}")
    if unavailable_chart_point_ids:
        review_reasons.append(f"unavailable chart points: {len(unavailable_chart_point_ids)}")
    if measured_avg is None:
        review_reasons.append("measured OCR/visual confidence is unavailable (null)")
    elif measured_avg < 0.70:
        review_reasons.append(f"measured visual confidence {measured_avg:.3f} < 0.70")

    is_rejected = bool(rejected_reasons)
    is_incomplete_or_uncertain = bool(review_reasons)

    return {
        "schema_version": vdoc.schema_version,
        "readiness": "rejected" if is_rejected else ("needs_review" if is_incomplete_or_uncertain else "valid"),
        "is_rejected": is_rejected,
        "is_incomplete_or_uncertain": is_incomplete_or_uncertain,
        "rejected_reasons": rejected_reasons,
        "review_reasons": review_reasons,
        "measured_confidence": measured_avg,
        "confidence_available": measured_avg is not None,
        "warning_codes": sorted(set(warning_codes)),
        "uncertainty": {
            "has_incomplete_or_uncertain": is_rejected or is_incomplete_or_uncertain,
            "invalid_element_ids": invalid_element_ids,
            "incomplete_element_ids": incomplete_element_ids,
            "ambiguous_field_ids": ambiguous_field_ids,
            "unreadable_cell_ids": unreadable_cell_ids,
            "missing_cell_ids": missing_cell_ids,
            "unavailable_chart_point_ids": unavailable_chart_point_ids,
            "estimated_chart_point_ids": estimated_chart_point_ids,
            "approval_field_ids": approval_field_ids,
        },
    }


def build_settlement_visual_provenance(
    vdoc: VisualDocument,
    *,
    source_file_hash: str = "",
    doc_version_number: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Build immutable settlement provenance summary for ``SourceDocument.validation_notes``
    and ``DocumentChunk.metadata``.

    Explicitly records that visual extraction signals NEVER elevate governance authority,
    approval status, evidence sufficiency, or human authorization.
    """
    if not isinstance(vdoc, VisualDocument):
        vdoc = validate_visual_document_payload(vdoc)

    readiness = assess_visual_document_settlement_readiness(vdoc)
    type_counts: Dict[str, int] = {}
    extractor_versions: Dict[str, str] = {}
    for el in vdoc.elements:
        t_key = el.element_type.value
        type_counts[t_key] = type_counts.get(t_key, 0) + 1
        extractor_versions[f"{el.extraction_method}"] = el.extractor_version
    for pg in vdoc.pages:
        if pg.extraction_method and pg.extractor_version:
            extractor_versions.setdefault(pg.extraction_method, pg.extractor_version)

    all_warnings: List[Dict[str, Any]] = [w.model_dump(mode="json") for w in vdoc.warnings]
    for pg in vdoc.pages:
        all_warnings.extend(w.model_dump(mode="json") for w in pg.warnings)
    for el in vdoc.elements:
        all_warnings.extend(w.model_dump(mode="json") for w in el.warnings)

    return {
        "schema_version": vdoc.schema_version,
        "source_document_id": vdoc.source_document_id,
        "source_file_hash": source_file_hash,
        "document_version": doc_version_number if doc_version_number is not None else vdoc.document_version,
        "validation_status": vdoc.validation_status.value,
        "readiness": readiness["readiness"],
        "page_count": vdoc.page_count,
        "element_count": len(vdoc.elements),
        "element_type_counts": type_counts,
        "extractor_versions": extractor_versions,
        "measured_confidence": readiness["measured_confidence"],
        "confidence_available": readiness["confidence_available"],
        "warnings": all_warnings[:100],
        "warning_count": len(all_warnings),
        "uncertainty": readiness["uncertainty"],
        "governance_invariants": {
            "ocr_confidence_is_authority": False,
            "layout_confidence_is_approval": False,
            "table_correctness_is_sufficiency": False,
            "populated_form_is_authorization": False,
        },
    }


def visual_document_to_canonical_pages(
    vdoc: VisualDocument,
    *,
    baseline_pages: Sequence[Mapping[str, Any]] = (),
    source_file_hash: str = "",
) -> List[Dict[str, Any]]:
    """
    Convert a validated ``VisualDocument`` (``lore.visual/1.0``) into the canonical
    LORE per-page representation consumed by ``DocumentPage``, ``StructureAwareChunker``,
    ``DocumentQualityService``, and ``SettlementGateCoordinator``.
    """
    if not isinstance(vdoc, VisualDocument):
        vdoc = validate_visual_document_payload(vdoc)

    baseline_by_page: Dict[int, Dict[str, Any]] = {}
    for bp in baseline_pages:
        if isinstance(bp, Mapping) and bp.get("page_number"):
            pno = int(bp["page_number"])
            baseline_by_page[pno] = dict(bp)

    vpages_by_num: Dict[int, VisualPage] = {pg.page_number: pg for pg in vdoc.pages}
    els_by_page: Dict[int, List[AnyVisualElement]] = {}
    for el in vdoc.elements:
        els_by_page.setdefault(el.page_number, []).append(el)

    max_page = max(
        [vdoc.page_count]
        + list(baseline_by_page.keys())
        + list(vpages_by_num.keys())
        + list(els_by_page.keys())
    )

    canonical_pages: List[Dict[str, Any]] = []
    for pno in range(1, max_page + 1):
        base = dict(baseline_by_page.get(pno) or {})
        vpage = vpages_by_num.get(pno)
        page_els = sorted(
            els_by_page.get(pno, []),
            key=lambda e: (
                e.reading_order if e.reading_order is not None else 999999,
                float(e.bounding_box.ymin),
                float(e.bounding_box.xmin),
                e.element_id,
            ),
        )

        rendered_blocks: List[str] = []
        bboxes_out: List[Dict[str, Any]] = []
        cell_prov_out: List[Dict[str, Any]] = []
        field_prov_out: List[Dict[str, Any]] = []
        chart_prov_out: List[Dict[str, Any]] = []
        el_confs: List[float] = []
        methods_seen: List[str] = []
        versions_seen: Dict[str, str] = {}
        page_warnings: List[Dict[str, Any]] = []
        repaired_flag = bool(base.get("is_repaired", False))

        if vpage is not None:
            if vpage.confidence is not None:
                el_confs.append(float(vpage.confidence))
            if vpage.extraction_method:
                methods_seen.append(vpage.extraction_method)
                if vpage.extractor_version:
                    versions_seen[vpage.extraction_method] = vpage.extractor_version
            page_warnings.extend(w.model_dump(mode="json") for w in vpage.warnings)

        for el in page_els:
            repaired_flag = repaired_flag or bool(el.is_repaired)
            if el.confidence is not None:
                el_confs.append(float(el.confidence))
            methods_seen.append(el.extraction_method)
            versions_seen[el.extraction_method] = el.extractor_version
            page_warnings.extend(w.model_dump(mode="json") for w in el.warnings)

            if isinstance(el, TableElement):
                rendered_blocks.append(_render_table_element_text(el))
                for cell in el.cells:
                    cell_prov_out.append({
                        "table_element_id": el.element_id,
                        "cell_id": cell.cell_id,
                        "row_index": cell.row_index,
                        "col_index": cell.col_index,
                        "row_span": cell.row_span,
                        "col_span": cell.col_span,
                        "status": cell.status.value,
                        "unit": cell.unit,
                        "confidence": cell.confidence,
                        "needs_review": cell.needs_review,
                        "bounding_box": cell.bounding_box.model_dump(mode="json") if cell.bounding_box else None,
                    })
            elif isinstance(el, ChartElement):
                rendered_blocks.append(_render_chart_element_text(el))
                chart_prov_out.append({
                    "chart_element_id": el.element_id,
                    "chart_type": el.chart_type.value,
                    "source_mode": el.source_mode.value if el.source_mode else None,
                    "axes": [ax.model_dump(mode="json") for ax in el.axes],
                    "value_precision_summary": el.value_precision_summary(),
                    "confidence": el.confidence,
                    "validation_status": el.validation_status.value,
                })
            elif isinstance(el, FormElement):
                rendered_blocks.append(_render_form_element_text(el))
                for fld in el.fields:
                    field_prov_out.append({
                        "form_element_id": el.element_id,
                        "field_id": fld.field_id,
                        "label": fld.label,
                        "field_type": fld.field_type.value,
                        "status": fld.status.value,
                        "selection_state": fld.selection_state.value if fld.selection_state else None,
                        "is_ambiguous": fld.is_ambiguous,
                        "possibly_handwritten": fld.possibly_handwritten,
                        "is_approval_field": fld.is_approval_field,
                        "confidence": fld.confidence,
                        "bounding_box": fld.bounding_box.model_dump(mode="json") if fld.bounding_box else None,
                        "label_bounding_box": fld.label_bounding_box.model_dump(mode="json") if fld.label_bounding_box else None,
                        "value_bounding_box": fld.value_bounding_box.model_dump(mode="json") if fld.value_bounding_box else None,
                    })
            elif isinstance(el, TextElement):
                txt = (el.content or "\n".join(el.lines) or el.markdown or "").strip()
                if txt:
                    if el.element_type == VisualElementType.TITLE_HEADING and not txt.startswith("#"):
                        lvl = el.heading_level or 1
                        txt = f"{'#' * min(max(lvl, 1), 4)} {txt}"
                    rendered_blocks.append(txt)
            else:
                txt = (el.content or el.markdown or "").strip()
                if txt:
                    rendered_blocks.append(f"[{el.element_type.value}] {txt}")

            crop_ref = el.source_crop_reference
            if isinstance(crop_ref, SourceCropReference):
                crop_ref_val: Any = crop_ref.model_dump(mode="json")
            else:
                crop_ref_val = crop_ref

            bboxes_out.append({
                "element_id": el.element_id,
                "element_type": el.element_type.value,
                "source_document_id": el.source_document_id,
                "page_number": el.page_number,
                "ymin": el.bounding_box.ymin,
                "xmin": el.bounding_box.xmin,
                "ymax": el.bounding_box.ymax,
                "xmax": el.bounding_box.xmax,
                "normalized_box": el.bounding_box.to_normalized_list(),
                "page_bbox_xywh": el.bounding_box.page_bbox_xywh,
                "coordinate_space": el.bounding_box.coordinate_space.value,
                "page_width": el.bounding_box.page_width,
                "page_height": el.bounding_box.page_height,
                "rotation": el.bounding_box.rotation,
                "reading_order": el.reading_order,
                "extraction_method": el.extraction_method,
                "extractor_version": el.extractor_version,
                "confidence": el.confidence,
                "validation_status": el.validation_status.value,
                "source_crop_reference": crop_ref_val,
                "warnings": [w.model_dump(mode="json") for w in el.warnings],
            })

        base_text = str(base.get("text") or "").strip()
        if base_text and rendered_blocks:
            extra_blocks = [b for b in rendered_blocks if b and b not in base_text]
            final_text = f"{base_text}\n\n" + "\n\n".join(extra_blocks) if extra_blocks else base_text
        elif rendered_blocks:
            final_text = "\n\n".join(b for b in rendered_blocks if b).strip()
        else:
            final_text = base_text

        measured_page_conf: Optional[float] = (
            round(sum(el_confs) / len(el_confs), 4) if el_confs else None
        )
        base_conf = base.get("confidence")
        if base_conf is not None and not page_els:
            db_safe_conf = float(base_conf)
            measured_page_conf = float(base_conf)
        elif measured_page_conf is not None:
            db_safe_conf = measured_page_conf
        elif base_conf is not None and base_text:
            db_safe_conf = float(base_conf)
            measured_page_conf = float(base_conf)
        else:
            # Never fabricate confidence when visual extraction yielded no measured score
            db_safe_conf = 0.0

        eff_w = float(vpage.width) if (vpage and vpage.width) else float(base.get("width") or 0.0)
        eff_h = float(vpage.height) if (vpage and vpage.height) else float(base.get("height") or 0.0)
        eff_rot = vpage.rotation if vpage else int(base.get("rotation") or 0)

        primary_method = (
            (vpage.extraction_method if vpage and vpage.extraction_method else None)
            or (methods_seen[0] if len(set(methods_seen)) == 1 else ("visual_hybrid" if methods_seen else None))
            or str(base.get("extraction_type") or "visual_schema")
        )
        primary_engine = (
            (vpage.extraction_method if vpage and vpage.extraction_method else None)
            or (methods_seen[0] if methods_seen else str(base.get("engine") or "lore_visual"))
        )
        primary_ver = (
            (vpage.extractor_version if vpage and vpage.extractor_version else None)
            or (versions_seen.get(primary_engine) if versions_seen else None)
            or str(base.get("engine_version") or vdoc.schema_version)
        )

        # Preserve baseline word bounding_boxes if present on DocumentPage; always keep region boxes in visual_provenance
        base_bboxes = list(base.get("bounding_boxes") or [])
        final_bboxes = base_bboxes if base_bboxes else bboxes_out

        page_dict: Dict[str, Any] = {
            **base,
            "page_number": pno,
            "text": final_text,
            "confidence": db_safe_conf,
            "measured_confidence": measured_page_conf,
            "confidence_available": measured_page_conf is not None,
            "words_count": len(final_text.split()) if final_text else 0,
            "width": eff_w,
            "height": eff_h,
            "rotation": eff_rot,
            "extraction_type": _truncate_str(str(base.get("extraction_type") or primary_method), 50),
            "engine": _truncate_str(str(base.get("engine") or primary_engine), 50),
            "engine_version": _truncate_str(str(base.get("engine_version") or primary_ver), 50),
            "is_repaired": repaired_flag,
            "bounding_boxes": final_bboxes,
            "visual_regions": [el.model_dump(mode="json") for el in page_els],
            "visual_provenance": {
                "schema_version": vdoc.schema_version,
                "source_document_id": vdoc.source_document_id,
                "source_file_hash": source_file_hash,
                "page_number": pno,
                "rotation": eff_rot,
                "measured_confidence": measured_page_conf,
                "confidence_available": measured_page_conf is not None,
                "extractor_versions": versions_seen,
                "element_ids": [el.element_id for el in page_els],
                "element_types": [el.element_type.value for el in page_els],
                "region_bounding_boxes": bboxes_out,
                "cell_provenance": cell_prov_out,
                "field_provenance": field_prov_out,
                "chart_provenance": chart_prov_out,
                "warnings": page_warnings,
            },
        }
        canonical_pages.append(page_dict)

    return canonical_pages


__all__ = [
    "AnyVisualElement",
    "BoundingBox",
    "ChartAxis",
    "ChartDataPoint",
    "ChartElement",
    "ChartSeries",
    "ChartType",
    "ChartValuePrecision",
    "CoordinateSpace",
    "ExtractionProvenance",
    "ExtractionWarning",
    "FormElement",
    "FormField",
    "FormFieldStatus",
    "FormFieldType",
    "FormRadioGroup",
    "SelectionState",
    "SourceCropReference",
    "SourceMode",
    "TableCell",
    "TableCellStatus",
    "TableElement",
    "TextElement",
    "TextRole",
    "VISUAL_SCHEMA_ID",
    "VISUAL_SCHEMA_MAJOR",
    "VISUAL_SCHEMA_MINOR",
    "VISUAL_SCHEMA_NAMESPACE",
    "ValidationStatus",
    "VisualDocument",
    "VisualElement",
    "VisualElementType",
    "VisualPage",
    "VisualSchemaEvolutionError",
    "WarningSeverity",
    "assess_visual_document_settlement_readiness",
    "build_settlement_visual_provenance",
    "extract_visual_document_screenable_text",
    "migrate_visual_payload",
    "pages_to_visual_document",
    "parse_visual_schema_version",
    "region_dict_to_visual_element",
    "validate_visual_document_payload",
    "visual_document_to_canonical_pages",
]
