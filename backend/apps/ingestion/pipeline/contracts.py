"""
Formal Integration Contracts for LORE Visual Extraction.

Defines versioned data schemas, runtime-checkable Python Protocols,
coordinate conventions, provenance structures, error/fallback rules,
and lossless projection adapters bridging:
    - OCRRouter / BaseOCRProvider / TesseractOCRProvider
    - UnifiedDocumentExtractor
    - VisualDocumentExtractor / BaseVisualProvider
    - SourceDocument / DocumentPage
    - SettlementGateCoordinator (Stages 1-6)
    - SequentialPipelineCoordinator (Runs 1-4)

This module is pure contract + adapter logic: it does not instantiate ML/VLM
models, alter database schemas, or modify governance, retrieval, indexing, or
settlement responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Dict,
    FrozenSet,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    TypedDict,
    runtime_checkable,
)

from PIL import Image

from apps.ingestion.pipeline.visual import (
    VisualExtractionKind,
    VisualRegionType,
    format_visual_region_markdown,
)
from apps.knowledge.chunking import StructureAwareChunker


VISUAL_INTEGRATION_CONTRACT_VERSION = "1.0.0"

# Canonical normalized bounding box order matches TesseractOCRProvider & DigitalPDFExtractor
CANONICAL_COORDINATE_ORDER: Tuple[str, ...] = ("ymin", "xmin", "ymax", "xmax")
CANONICAL_COORDINATE_SCALE: int = 1000

# Existing threshold invariants discovered in ocr.py, settlement.py, and quality.py
DIGITAL_PDF_TEXT_THRESHOLD_CHARS: int = 20
SETTLEMENT_OCR_CONFIDENCE_THRESHOLD: float = 0.70

# DocumentPage CharField(max_length=50) constraints in apps/sources/models.py
DOCUMENT_PAGE_CHARFIELD_MAX_LENGTH: int = 50

BASELINE_REQUIRED_PAGE_KEYS: FrozenSet[str] = frozenset({
    "page_number",
    "text",
    "confidence",
    "words_count",
    "width",
    "height",
    "extraction_type",
    "engine",
    "engine_version",
    "is_repaired",
    "bounding_boxes",
})

OPTIONAL_BASELINE_PAGE_KEYS: FrozenSet[str] = frozenset({
    "needs_review",
    "status",
    "language",
    "warnings",
    "rotation",
    "page_classification",
    "is_optional_skipped",
})

VISUAL_EXTENSION_PAGE_KEYS: FrozenSet[str] = frozenset({
    "visual_regions",
    "visual_metadata",
})

DOCUMENT_PAGE_PERSISTENCE_FIELDS: Tuple[str, ...] = (
    "page_number",
    "text",
    "confidence",
    "words_count",
    "width",
    "height",
    "extraction_type",
    "engine",
    "engine_version",
    "is_repaired",
    "bounding_boxes",
)

# Timing keys inspected by SequentialPipelineCoordinator._execute_run_1
PIPELINE_STAGE_TIMING_KEYS: Tuple[str, ...] = (
    "chunking_ms",
    "embedding_ms",
    "indexing_ms",
    "ocr_ms",
    "extraction_ms",
)

OCR_PLACEHOLDER_PREFIXES: Tuple[str, ...] = (
    "[OCR Engine Optional:",
    "[OCR Disabled:",
    "[OCR Error:",
)


class VisualFallbackReason(str, Enum):
    """Canonical reason codes recorded when extraction falls back safely."""

    NONE = "none"
    OCR_PROVIDER_UNAVAILABLE = "ocr_provider_unavailable"
    OCR_EMPTY_SCAN = "ocr_empty_scan"
    OCR_LOW_CONFIDENCE = "ocr_low_confidence"
    VISUAL_PROVIDER_UNAVAILABLE = "visual_provider_unavailable"
    VISUAL_PROVIDER_TIMEOUT_OR_ERROR = "visual_provider_timeout_or_error"
    SOVEREIGNTY_POLICY_BLOCKED = "sovereignty_policy_blocked"
    CONCURRENCY_BUDGET_EXHAUSTED = "concurrency_budget_exhausted"
    ASSET_BUDGET_EXHAUSTED = "asset_budget_exhausted"
    UNSUPPORTED_VISUAL_FORMAT = "unsupported_visual_format"
    EMPTY_VISUAL_CANVAS = "empty_visual_canvas"


class VisualContractError(Exception):
    """Base error for integration contract violations."""


class VisualContractValidationError(VisualContractError):
    """Raised when a page, box, or provider payload violates the contract."""

    def __init__(self, violations: Sequence[str]):
        self.violations: List[str] = list(violations)
        summary = "; ".join(self.violations[:5])
        if len(self.violations) > 5:
            summary += f" (+{len(self.violations) - 5} more)"
        super().__init__(f"Visual integration contract violation: {summary}")


class WordBoundingBoxContract(TypedDict, total=False):
    """Word-level OCR / digital PDF box schema required by DocumentPage UI overlays."""

    word: str
    confidence: float
    x: int
    y: int
    w: int
    h: int
    normalized_box: List[int]


class OCROutputContract(TypedDict, total=False):
    """Return payload contract for BaseOCRProvider.extract_image(image)."""

    status: str
    text: str
    confidence: float
    words_count: int
    width: int
    height: int
    engine: str
    engine_version: str
    bounding_boxes: List[WordBoundingBoxContract]
    needs_review: bool
    language: Optional[str]
    is_optional_skipped: bool


class VisualRegionProvenanceContract(TypedDict, total=False):
    """Canonical visual region schema stored in page['visual_regions']."""

    region_id: str
    region_type: str
    extraction_kind: str
    page_number: int
    bbox: List[float]
    normalized_box: List[int]
    text: str
    markdown: str
    confidence: float
    engine: str
    engine_version: str
    is_inference: bool
    is_repaired: bool
    source_asset_name: str
    word_boxes: List[WordBoundingBoxContract]
    metadata: Dict[str, Any]


class VisualProviderResultContract(TypedDict, total=False):
    """Return payload contract for BaseVisualProvider.analyze_image(image, context)."""

    status: str
    text: str
    confidence: float
    width: int
    height: int
    engine: str
    engine_version: str
    regions: List[VisualRegionProvenanceContract]
    needs_review: bool
    is_optional_skipped: bool
    rotated_degrees: int
    metrics: Dict[str, Any]


class VisualPageMetadataContract(TypedDict, total=False):
    """Per-page telemetry attached under page['visual_metadata']."""

    contract_version: str
    has_visual_content: bool
    visual_region_count: int
    visual_confidence: float
    visual_engines: List[str]
    visual_inference_count: int
    visual_timings_ms: float
    provider_metrics: List[Dict[str, Any]]
    fallback_applied: bool
    fallback_reasons: List[str]
    fallback_error: str
    page_classification: str
    rotation: int
    ocr_triggered: bool
    render_count: int
    warnings: List[str]
    geometry: Dict[str, Any]
    layout_provider: str
    layout_model: str
    layout_regions_count: int
    layout_regions: List[Dict[str, Any]]
    layout_timings_ms: float


class CanonicalExtractedPageContract(TypedDict, total=False):
    """Unified page contract shared across OCRRouter, UnifiedDocumentExtractor,
    VisualDocumentExtractor, SettlementGateCoordinator, and DocumentPage."""

    page_number: int
    text: str
    confidence: float
    words_count: int
    width: float
    height: float
    extraction_type: str
    engine: str
    engine_version: str
    is_repaired: bool
    bounding_boxes: List[WordBoundingBoxContract]
    needs_review: bool
    status: str
    language: Optional[str]
    is_optional_skipped: bool
    warnings: List[str]
    rotation: int
    page_classification: str
    visual_regions: List[VisualRegionProvenanceContract]
    visual_metadata: VisualPageMetadataContract


class SourceDocumentVisualNotesContract(TypedDict, total=False):
    """Non-breaking summary payload nested under SourceDocument.validation_notes['visual_extraction']."""

    contract_version: str
    visual_enabled: bool
    visual_page_count: int
    visual_region_count: int
    visual_engines: List[str]
    has_visual_inference: bool
    avg_visual_confidence: float
    total_visual_ms: float
    fallback_events: List[Dict[str, Any]]
    requires_visual_review: bool


@dataclass
class SettlementCompatibilityReport:
    """Verification report checking readiness for SettlementGateCoordinator and SequentialPipelineCoordinator."""

    contract_version: str = VISUAL_INTEGRATION_CONTRACT_VERSION
    stage_2_deep_screen_text_present: bool = False
    stage_2_screened_char_count: int = 0
    stage_3_non_empty: bool = False
    stage_3_expected_status: str = "failed"
    stage_3_reason_codes: List[str] = field(default_factory=list)
    computed_avg_ocr_confidence: float = 0.0
    document_page_records_valid: bool = False
    stage_6_chunk_compatible: bool = False
    stage_6_chunk_count: int = 0
    run_4_citation_valid: bool = False
    quality_service_expected_threshold: float = SETTLEMENT_OCR_CONFIDENCE_THRESHOLD
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def is_compatible(self) -> bool:
        """True when all blocking settlement/pipeline invariants pass."""
        return len(self.errors) == 0 and self.document_page_records_valid and self.run_4_citation_valid


@runtime_checkable
class OCRProviderProtocol(Protocol):
    """Structural contract matching apps.ingestion.pipeline.ocr.BaseOCRProvider."""

    def is_available(self) -> bool:
        ...

    def extract_image(self, image: Image.Image) -> Dict[str, Any]:
        ...


@runtime_checkable
class OCRRouterProtocol(Protocol):
    """Structural contract matching apps.ingestion.pipeline.ocr.OCRRouter."""

    def process_pdf(self, file_path_or_bytes: Any, max_pages: int = 50) -> List[Dict[str, Any]]:
        ...

    def process_image(self, file_path_or_bytes: Any) -> List[Dict[str, Any]]:
        ...


@runtime_checkable
class DocumentExtractorProtocol(Protocol):
    """Structural contract matching UnifiedDocumentExtractor."""

    def extract_document(
        self,
        file_path_or_bytes: Any,
        doc_type: str,
        filename: str = "",
    ) -> List[Dict[str, Any]]:
        ...


@runtime_checkable
class VisualProviderProtocol(Protocol):
    """Structural contract matching apps.ingestion.pipeline.visual.BaseVisualProvider."""

    provider_name: str
    engine_version: str
    requires_remote_egress: bool

    def is_available(self) -> bool:
        ...

    def analyze_image(
        self,
        image: Image.Image,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ...


@runtime_checkable
class VisualExtensionHookProtocol(Protocol):
    """Non-competing opt-in hook allowing OCRRouter/UnifiedDocumentExtractor
    to delegate visual enrichment without opening or parsing source files twice."""

    def enrich_page(
        self,
        page_data: Dict[str, Any],
        page_image: Optional[Image.Image] = None,
        raw_file: Any = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ...


@runtime_checkable
class VisualDocumentExtractorProtocol(Protocol):
    """Structural contract matching apps.ingestion.pipeline.visual.VisualDocumentExtractor."""

    def extract_file_object(
        self,
        file_obj: Any,
        workspace: Any = None,
        organization: Any = None,
        policy_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ...

    def extract_document(
        self,
        file_path_or_bytes: Any,
        doc_type: str = "",
        filename: str = "",
        workspace: Any = None,
        organization: Any = None,
        policy_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        ...


def validate_normalized_box(box: Any, label: str = "normalized_box") -> List[int]:
    """Validate canonical [ymin, xmin, ymax, xmax] coordinates on the 0..1000 scale."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise VisualContractValidationError([
            f"{label} must be a 4-element sequence [ymin, xmin, ymax, xmax], got {box!r}"
        ])

    coords: List[int] = []
    for idx, val in enumerate(box):
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise VisualContractValidationError([
                f"{label}[{idx}] must be numeric, got {type(val).__name__}"
            ])
        iv = int(round(val))
        if iv < 0 or iv > CANONICAL_COORDINATE_SCALE:
            raise VisualContractValidationError([
                f"{label}[{idx}]={iv} outside canonical [0, {CANONICAL_COORDINATE_SCALE}]"
            ])
        coords.append(iv)

    ymin, xmin, ymax, xmax = coords
    if ymin > ymax or xmin > xmax:
        raise VisualContractValidationError([
            f"{label} has inverted bounds: ymin={ymin}, xmin={xmin}, ymax={ymax}, xmax={xmax}"
        ])
    return coords


def rect_to_normalized_box(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    canvas_width: float,
    canvas_height: float,
) -> List[int]:
    """Convert canvas rect (x0, y0, x1, y1) into canonical [ymin, xmin, ymax, xmax] (0..1000)."""
    if canvas_width <= 0 or canvas_height <= 0:
        return [0, 0, 0, 0]

    lo_x, hi_x = sorted((float(x0), float(x1)))
    lo_y, hi_y = sorted((float(y0), float(y1)))

    def _clamp(val: float, limit: float) -> int:
        scaled = int(round((val / limit) * CANONICAL_COORDINATE_SCALE))
        return max(0, min(CANONICAL_COORDINATE_SCALE, scaled))

    return [
        _clamp(lo_y, float(canvas_height)),
        _clamp(lo_x, float(canvas_width)),
        _clamp(hi_y, float(canvas_height)),
        _clamp(hi_x, float(canvas_width)),
    ]


def xywh_to_normalized_box(
    x: float,
    y: float,
    w: float,
    h: float,
    canvas_width: float,
    canvas_height: float,
) -> List[int]:
    """Convert pixel/point (x, y, w, h) rectangle into canonical [ymin, xmin, ymax, xmax]."""
    return rect_to_normalized_box(
        x0=x,
        y0=y,
        x1=float(x) + max(0.0, float(w)),
        y1=float(y) + max(0.0, float(h)),
        canvas_width=canvas_width,
        canvas_height=canvas_height,
    )


def build_visual_region_provenance(
    *,
    region_id: str,
    region_type: str | VisualRegionType,
    extraction_kind: str | VisualExtractionKind,
    page_number: int,
    bbox: Sequence[float],
    normalized_box: Sequence[int],
    engine: str,
    engine_version: str = "1.0",
    confidence: float = 0.0,
    text: str = "",
    markdown: str = "",
    is_inference: bool = False,
    is_repaired: bool = False,
    source_asset_name: str = "",
    word_boxes: Optional[Sequence[WordBoundingBoxContract]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> VisualRegionProvenanceContract:
    """Build a contract-validated provenance dictionary for one detected visual region."""
    valid_norm = validate_normalized_box(normalized_box, label=f"region[{region_id}].normalized_box")
    r_type = region_type.value if isinstance(region_type, VisualRegionType) else str(region_type)
    e_kind = extraction_kind.value if isinstance(extraction_kind, VisualExtractionKind) else str(extraction_kind)

    return {
        "region_id": str(region_id),
        "region_type": r_type,
        "extraction_kind": e_kind,
        "page_number": max(1, int(page_number)),
        "bbox": [round(float(v), 2) for v in bbox[:4]],
        "normalized_box": valid_norm,
        "text": str(text or ""),
        "markdown": str(markdown or ""),
        "confidence": round(max(0.0, min(1.0, float(confidence))), 4),
        "engine": str(engine),
        "engine_version": str(engine_version),
        "is_inference": bool(is_inference),
        "is_repaired": bool(is_repaired),
        "source_asset_name": str(source_asset_name or ""),
        "word_boxes": [dict(wb) for wb in (word_boxes or [])],
        "metadata": dict(metadata or {}),
    }


class VisualPipelineIntegrationAdapter:
    """
    Stateless contract enforcement, safe fallback, and lossless projection layer
    connecting Visual Extraction outputs to existing OCR, Model, Settlement,
    and Coordinator components.
    """

    @staticmethod
    def is_ocr_placeholder_text(text: Optional[str]) -> bool:
        """Detect optional/unavailable OCR placeholder banners emitted by ocr.py."""
        stripped = (text or "").strip()
        return any(stripped.startswith(prefix) for prefix in OCR_PLACEHOLDER_PREFIXES)

    @classmethod
    def _validate_word_boxes(cls, boxes: Any, page_idx: int) -> List[str]:
        violations: List[str] = []
        if not isinstance(boxes, list):
            return [f"page[{page_idx}].bounding_boxes must be list, got {type(boxes).__name__}"]
        for b_idx, item in enumerate(boxes):
            if not isinstance(item, Mapping):
                violations.append(f"page[{page_idx}].bounding_boxes[{b_idx}] must be dict")
                continue
            if "word" not in item:
                violations.append(
                    f"page[{page_idx}].bounding_boxes[{b_idx}] missing required 'word' key "
                    "(must stay isolated from visual_regions for UI overlay compatibility)"
                )
            if "normalized_box" in item and item["normalized_box"] is not None:
                try:
                    validate_normalized_box(
                        item["normalized_box"],
                        label=f"page[{page_idx}].bounding_boxes[{b_idx}].normalized_box",
                    )
                except VisualContractValidationError as exc:
                    violations.extend(exc.violations)
        return violations

    @classmethod
    def _validate_visual_regions(cls, regions: Any, page_num: Any, page_idx: int) -> List[str]:
        violations: List[str] = []
        if not isinstance(regions, list):
            return [f"page[{page_idx}].visual_regions must be list, got {type(regions).__name__}"]

        valid_types = {rt.value for rt in VisualRegionType}
        valid_kinds = {ek.value for ek in VisualExtractionKind}

        for r_idx, reg in enumerate(regions):
            prefix = f"page[{page_idx}].visual_regions[{r_idx}]"
            if not isinstance(reg, Mapping):
                violations.append(f"{prefix} must be dict")
                continue
            for req in ("region_id", "region_type", "extraction_kind", "page_number", "normalized_box", "engine"):
                if req not in reg:
                    violations.append(f"{prefix} missing required key '{req}'")
            if "region_type" in reg and reg["region_type"] not in valid_types:
                violations.append(f"{prefix}.region_type invalid: {reg['region_type']!r}")
            if "extraction_kind" in reg and reg["extraction_kind"] not in valid_kinds:
                violations.append(f"{prefix}.extraction_kind invalid: {reg['extraction_kind']!r}")
            if "page_number" in reg and reg["page_number"] != page_num:
                violations.append(f"{prefix}.page_number={reg['page_number']!r} != page_number={page_num!r}")
            if "normalized_box" in reg:
                try:
                    validate_normalized_box(reg["normalized_box"], label=f"{prefix}.normalized_box")
                except VisualContractValidationError as exc:
                    violations.extend(exc.violations)
            conf = reg.get("confidence", 0.0)
            if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
                violations.append(f"{prefix}.confidence={conf!r} outside [0.0, 1.0]")
            if "is_inference" not in reg or not isinstance(reg["is_inference"], bool):
                violations.append(f"{prefix}.is_inference must be bool")
        return violations

    @classmethod
    def validate_visual_provider_result(
        cls,
        result: Mapping[str, Any],
        strict: bool = True,
    ) -> List[str]:
        """Validate output of BaseVisualProvider.analyze_image(...) against the contract."""
        violations: List[str] = []
        for req in ("status", "text", "confidence", "width", "height", "engine", "engine_version", "regions"):
            if req not in result:
                violations.append(f"visual_provider_result missing required key '{req}'")
        if "regions" in result and not isinstance(result["regions"], list):
            violations.append("visual_provider_result.regions must be list")
        conf = result.get("confidence", 0.0)
        if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
            violations.append(f"visual_provider_result.confidence={conf!r} outside [0.0, 1.0]")

        if strict and violations:
            raise VisualContractValidationError(violations)
        return violations

    @classmethod
    def validate_page_payload(
        cls,
        page_data: Mapping[str, Any],
        page_idx: int = 0,
        strict: bool = True,
    ) -> List[str]:
        """Validate a page dict against OCRRouter, UnifiedDocumentExtractor, and DocumentPage contracts."""
        violations: List[str] = []
        for key in sorted(BASELINE_REQUIRED_PAGE_KEYS):
            if key not in page_data:
                violations.append(f"page[{page_idx}] missing required baseline key '{key}'")

        page_num = page_data.get("page_number")
        if isinstance(page_num, bool) or not isinstance(page_num, int) or page_num < 1:
            violations.append(f"page[{page_idx}].page_number must be int >= 1, got {page_num!r}")

        conf = page_data.get("confidence", 0.0)
        if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
            violations.append(f"page[{page_idx}].confidence={conf!r} must be in [0.0, 1.0]")

        wc = page_data.get("words_count", 0)
        if isinstance(wc, bool) or not isinstance(wc, int) or wc < 0:
            violations.append(f"page[{page_idx}].words_count must be int >= 0, got {wc!r}")

        for dim in ("width", "height"):
            val = page_data.get(dim, 0.0)
            if isinstance(val, bool) or not isinstance(val, (int, float)) or float(val) < 0:
                violations.append(f"page[{page_idx}].{dim} must be numeric >= 0, got {val!r}")

        for cf in ("extraction_type", "engine", "engine_version"):
            val = str(page_data.get(cf, ""))
            if len(val) > DOCUMENT_PAGE_CHARFIELD_MAX_LENGTH:
                violations.append(
                    f"page[{page_idx}].{cf} length {len(val)} exceeds DocumentPage CharField(max_length=50)"
                )

        if "bounding_boxes" in page_data:
            violations.extend(cls._validate_word_boxes(page_data["bounding_boxes"], page_idx))

        if "visual_regions" in page_data and page_data["visual_regions"] is not None:
            violations.extend(cls._validate_visual_regions(page_data["visual_regions"], page_num, page_idx))

        if strict and violations:
            raise VisualContractValidationError(violations)
        return violations

    @classmethod
    def merge_baseline_and_visual_page(
        cls,
        baseline_page: Mapping[str, Any],
        visual_regions: Sequence[Mapping[str, Any]],
        visual_metadata: Optional[Mapping[str, Any]] = None,
        fallback_reason: VisualFallbackReason = VisualFallbackReason.NONE,
        extra_fallback_reasons: Sequence[str] = (),
    ) -> CanonicalExtractedPageContract:
        """
        Extend an OCRRouter/UnifiedDocumentExtractor page payload with grounded
        visual regions while preserving baseline word boxes and digital confidence.
        """
        cls.validate_page_payload(baseline_page, strict=True)
        merged: Dict[str, Any] = dict(baseline_page)
        merged["bounding_boxes"] = [dict(b) for b in baseline_page.get("bounding_boxes", [])]

        regions_list = [dict(r) for r in visual_regions]
        raw_base_text = str(baseline_page.get("text") or "")
        is_placeholder = cls.is_ocr_placeholder_text(raw_base_text)
        has_real_base_text = bool(raw_base_text.strip()) and not is_placeholder

        visual_markdown_blocks: List[str] = []
        for reg in regions_list:
            md = str(reg.get("markdown") or "").strip()
            if md:
                visual_markdown_blocks.append(md)
            else:
                visual_markdown_blocks.append(format_visual_region_markdown(reg))

        if visual_markdown_blocks:
            joined_visual = "\n\n".join(visual_markdown_blocks)
            if has_real_base_text:
                merged["text"] = f"{raw_base_text.rstrip()}\n\n{joined_visual}"
            else:
                merged["text"] = joined_visual
        elif is_placeholder and regions_list:
            merged["text"] = ""

        merged["words_count"] = len(str(merged.get("text") or "").split())

        # Preserve digital/good OCR confidence when real baseline text was extracted;
        # use conservative confidence when visual regions supply the sole content.
        base_conf = float(baseline_page.get("confidence", 0.0) or 0.0)
        vis_confs = [float(r.get("confidence", 0.0) or 0.0) for r in regions_list]
        vis_conf = (sum(vis_confs) / len(vis_confs)) if vis_confs else 0.0
        if not has_real_base_text and regions_list:
            merged["confidence"] = round(max(0.0, min(1.0, vis_conf)), 4)

        fallback_reasons = [r for r in extra_fallback_reasons if r and r != VisualFallbackReason.NONE.value]
        if fallback_reason != VisualFallbackReason.NONE and fallback_reason.value not in fallback_reasons:
            fallback_reasons.insert(0, fallback_reason.value)

        engines = sorted({str(r.get("engine", "")) for r in regions_list if r.get("engine")})
        meta_out: VisualPageMetadataContract = {
            "contract_version": VISUAL_INTEGRATION_CONTRACT_VERSION,
            "has_visual_content": len(regions_list) > 0,
            "visual_region_count": len(regions_list),
            "visual_confidence": round(vis_conf, 4),
            "visual_engines": engines,
            "visual_inference_count": sum(1 for r in regions_list if r.get("is_inference")),
            "visual_timings_ms": float((visual_metadata or {}).get("visual_timings_ms", 0.0) or 0.0),
            "provider_metrics": list((visual_metadata or {}).get("provider_metrics", [])),
            "fallback_applied": bool(fallback_reasons),
            "fallback_reasons": fallback_reasons,
        }
        if visual_metadata and visual_metadata.get("fallback_error"):
            meta_out["fallback_error"] = str(visual_metadata["fallback_error"])

        merged["visual_regions"] = regions_list
        merged["visual_metadata"] = meta_out
        cls.validate_page_payload(merged, strict=True)
        return merged  # type: ignore[return-value]

    @classmethod
    def apply_fallback(
        cls,
        baseline_page: Mapping[str, Any],
        reason: VisualFallbackReason,
        error_detail: str = "",
        preserve_visual_regions: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> CanonicalExtractedPageContract:
        """Degrade gracefully to baseline OCR/extractor output with explicit provenance."""
        return cls.merge_baseline_and_visual_page(
            baseline_page=baseline_page,
            visual_regions=list(preserve_visual_regions or []),
            visual_metadata={"fallback_error": str(error_detail or "")},
            fallback_reason=reason,
        )

    @classmethod
    def _clamp_charfield(cls, value: Any) -> str:
        text = str(value or "")
        return text[:DOCUMENT_PAGE_CHARFIELD_MAX_LENGTH]

    @classmethod
    def to_document_page_kwargs(
        cls,
        page_data: Mapping[str, Any],
        validate: bool = True,
    ) -> Dict[str, Any]:
        """
        Project a canonical page dict strictly onto existing apps.sources.models.DocumentPage
        fields without requiring DB schema changes.
        """
        if validate:
            cls.validate_page_payload(page_data, strict=True)

        return {
            "page_number": int(page_data["page_number"]),
            "text": str(page_data.get("text") or ""),
            "confidence": round(max(0.0, min(1.0, float(page_data.get("confidence", 1.0) or 0.0))), 4),
            "words_count": max(0, int(page_data.get("words_count", 0) or 0)),
            "width": float(page_data.get("width", 0.0) or 0.0),
            "height": float(page_data.get("height", 0.0) or 0.0),
            "extraction_type": cls._clamp_charfield(page_data.get("extraction_type", "digital")),
            "engine": cls._clamp_charfield(page_data.get("engine", "native")),
            "engine_version": cls._clamp_charfield(page_data.get("engine_version", "")),
            "is_repaired": bool(page_data.get("is_repaired", False)),
            "bounding_boxes": [dict(b) for b in (page_data.get("bounding_boxes") or [])],
        }

    @classmethod
    def build_source_document_validation_notes(
        cls,
        pages_data: Sequence[Mapping[str, Any]],
        existing_validation_notes: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Produce non-destructive visual provenance summary inside SourceDocument.validation_notes,
        preserving existing keys (such as DocumentMetadataExtractor's 'notes').
        """
        notes: Dict[str, Any] = dict(existing_validation_notes or {})
        visual_pages = 0
        total_regions = 0
        engines: set[str] = set()
        has_inference = False
        confs: List[float] = []
        total_ms = 0.0
        fallback_events: List[Dict[str, Any]] = []
        requires_review = False

        for p in pages_data:
            p_num = int(p.get("page_number", 1))
            regions = list(p.get("visual_regions") or [])
            vm = dict(p.get("visual_metadata") or {})
            if regions or vm.get("has_visual_content"):
                visual_pages += 1
            total_regions += len(regions)
            for reg in regions:
                if reg.get("engine"):
                    engines.add(str(reg["engine"]))
                if reg.get("is_inference"):
                    has_inference = True
                if "confidence" in reg:
                    confs.append(float(reg["confidence"] or 0.0))
            for eng in vm.get("visual_engines") or []:
                engines.add(str(eng))
            total_ms += float(vm.get("visual_timings_ms", 0.0) or 0.0)
            if vm.get("fallback_applied") or vm.get("fallback_reasons"):
                fallback_events.append({
                    "page_number": p_num,
                    "reasons": list(vm.get("fallback_reasons") or []),
                })
            if p.get("needs_review"):
                requires_review = True

        summary: SourceDocumentVisualNotesContract = {
            "contract_version": VISUAL_INTEGRATION_CONTRACT_VERSION,
            "visual_enabled": True,
            "visual_page_count": visual_pages,
            "visual_region_count": total_regions,
            "visual_engines": sorted(engines),
            "has_visual_inference": has_inference,
            "avg_visual_confidence": round(sum(confs) / len(confs), 4) if confs else 0.0,
            "total_visual_ms": round(total_ms, 2),
            "fallback_events": fallback_events,
            "requires_visual_review": requires_review,
        }
        notes["visual_extraction"] = summary
        return notes

    @classmethod
    def project_pipeline_stage_timings(
        cls,
        pages_data: Sequence[Mapping[str, Any]],
        base_timings: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, float]:
        """Project visual latencies into SequentialPipelineCoordinator timing keys without schema breakage."""
        timings: Dict[str, float] = {}
        for key in PIPELINE_STAGE_TIMING_KEYS:
            if base_timings and key in base_timings:
                timings[key] = float(base_timings[key] or 0.0)

        visual_ms = sum(
            float((p.get("visual_metadata") or {}).get("visual_timings_ms", 0.0) or 0.0)
            for p in pages_data
        )
        timings["visual_extraction_ms"] = round(visual_ms, 2)
        if "extraction_ms" in timings:
            timings["extraction_ms"] = round(timings["extraction_ms"] + visual_ms, 2)
        return timings

    @classmethod
    def verify_settlement_compatibility(
        cls,
        pages_data: Sequence[Mapping[str, Any]],
        document_type: str,
        document_title: str = "",
        doc_id: str = "contract-check",
        org_name: str = "contract-org",
        ws_name: str = "contract-ws",
        authority_rank: int = 3,
    ) -> SettlementCompatibilityReport:
        """
        Verify downstream compatibility across SettlementGateCoordinator (Stages 2, 3, 6)
        and SequentialPipelineCoordinator (Runs 1, 2, 4) without DB mutations.
        """
        report = SettlementCompatibilityReport()
        pages_list = list(pages_data)

        if not pages_list:
            report.stage_3_reason_codes.append("S3_EMPTY_EXTRACTION")
            report.errors.append("pages_data is empty; Stage 3 would fail with S3_EMPTY_EXTRACTION.")
            return report

        for idx, page in enumerate(pages_list):
            violations = cls.validate_page_payload(page, page_idx=idx, strict=False)
            if violations:
                report.errors.extend(violations)

        try:
            for page in pages_list:
                cls.to_document_page_kwargs(page, validate=False)
            report.document_page_records_valid = len(report.errors) == 0
        except Exception as exc:
            report.errors.append(f"DocumentPage projection failed: {exc}")
            report.document_page_records_valid = False

        # Mirror SettlementGateCoordinator Stage 2 deep re-screen text assembly
        full_screen_text = " ".join(str(p.get("text") or "") for p in pages_list)
        report.stage_2_screened_char_count = len(full_screen_text.strip())
        report.stage_2_deep_screen_text_present = report.stage_2_screened_char_count > 0

        # Mirror ExtractionValidationService Stage 3 non-empty check
        report.stage_3_non_empty = any(len(str(p.get("text") or "").strip()) > 0 for p in pages_list)
        avg_conf = sum(float(p.get("confidence", 1.0) or 0.0) for p in pages_list) / max(len(pages_list), 1)
        report.computed_avg_ocr_confidence = round(avg_conf, 4)

        if not report.stage_3_non_empty:
            report.stage_3_expected_status = "failed"
            report.stage_3_reason_codes.append("S3_EMPTY_EXTRACTION")
        elif avg_conf < SETTLEMENT_OCR_CONFIDENCE_THRESHOLD and document_type in ("pdf", "image"):
            report.stage_3_expected_status = "needs_review"
            report.stage_3_reason_codes.append("S3_LOW_CONFIDENCE_QUARANTINE")
        else:
            report.stage_3_expected_status = "passed"
            report.stage_3_reason_codes.append("S3_EXTRACTION_VALID")

        # Warn on known extraction_type=='digital' vs 'digital_pdf' discrepancy in quality.py:100
        ext_types = {str(p.get("extraction_type", "")) for p in pages_list}
        if document_type == "pdf" and "digital_pdf" in ext_types:
            report.quality_service_expected_threshold = SETTLEMENT_OCR_CONFIDENCE_THRESHOLD
            report.warnings.append(
                "Pages use extraction_type='digital_pdf'; DocumentQualityService.get_ocr_threshold() "
                "only elevates threshold to 0.90 when extraction_type=='digital'."
            )
        elif "statutory" in (document_title or "").lower() or "deed" in (document_title or "").lower():
            report.quality_service_expected_threshold = 0.80
        else:
            report.quality_service_expected_threshold = SETTLEMENT_OCR_CONFIDENCE_THRESHOLD

        # Mirror Stage 6 StructureAwareChunker + Run 4 locator invariant
        try:
            chunks = StructureAwareChunker.chunk_document_pages(
                doc_id=doc_id,
                doc_title=document_title or "Contract Verification Document",
                org_name=org_name,
                ws_name=ws_name,
                authority_rank=authority_rank,
                pages_data=[cls.to_document_page_kwargs(p, validate=False) for p in pages_list],
            )
            report.stage_6_chunk_count = len(chunks)
            report.stage_6_chunk_compatible = len(chunks) > 0 if report.stage_3_non_empty else True
            if report.stage_3_non_empty and not chunks:
                report.errors.append("StructureAwareChunker produced 0 chunks for non-empty extracted text.")
            report.run_4_citation_valid = all(
                int(c.get("page_number", 0)) >= 1
                and int(c.get("char_offset_end", -1)) >= int(c.get("char_offset_start", 0))
                for c in chunks
            )
            if not report.run_4_citation_valid:
                report.errors.append("Run 4 citation locator invariant failed on one or more chunks.")
        except Exception as exc:
            report.errors.append(f"StructureAwareChunker contract check failed: {exc}")
            report.stage_6_chunk_compatible = False
            report.run_4_citation_valid = False

        return report

