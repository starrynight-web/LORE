"""
Unit & Integration Tests for LORE Visual JSON Schema v1 (lore.visual/1.0).

Covers:
1. All 12 typed Pydantic models and 12 mandatory per-element provenance fields.
2. Strict Pydantic validation (no silent scalar coercion, extra_forbidden on 1.0,
   non-finite number rejection, strict mutation validation).
3. Validated coordinate ranges and cross-validated page/document references.
4. Consistent deterministic serialization and JSON round-tripping.
5. Schema version validation (rejecting lore.result/* and lore.visual/2.0).
6. No fabricated confidence scores.
7. Nullable uncertain/unavailable values; chart exact/estimated/unavailable distinction;
   table cell & form field empty/unreadable/unknown distinction; ambiguous outputs.
8. Backward-compatible schema evolution (1.x additive fields + legacy LORE page migration).
9. End-to-end conversion from PyMuPDF/OpenCV/Tesseract extractors without altering
   LORE governance or result contracts.
"""

from __future__ import annotations

import io
import json
import math
import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from apps.governance.contract import Directive, Verdict, validate_canonical_envelope
from apps.ingestion.pipeline.charts import PyMuPDFOpenCVChartExtractor
from apps.ingestion.pipeline.forms import FormExtractorConfig, FormKVExtractor
from apps.ingestion.pipeline.ocr import BaseOCRProvider
from apps.ingestion.pipeline.visual_schema import (
    VISUAL_SCHEMA_ID,
    BoundingBox,
    ChartAxis,
    ChartDataPoint,
    ChartElement,
    ChartSeries,
    ChartType,
    ChartValuePrecision,
    CoordinateSpace,
    ExtractionProvenance,
    ExtractionWarning,
    FormElement,
    FormField,
    FormFieldStatus,
    FormFieldType,
    FormRadioGroup,
    SelectionState,
    SourceCropReference,
    SourceMode,
    TableCell,
    TableCellStatus,
    TableElement,
    TextElement,
    TextRole,
    ValidationStatus,
    VisualDocument,
    VisualElement,
    VisualElementType,
    VisualPage,
    WarningSeverity,
    migrate_visual_payload,
    pages_to_visual_document,
    parse_visual_schema_version,
    region_dict_to_visual_element,
    validate_visual_document_payload,
)


def _sample_bbox(ymin=100, xmin=50, ymax=400, xmax=800) -> BoundingBox:
    return BoundingBox(
        ymin=ymin,
        xmin=xmin,
        ymax=ymax,
        xmax=xmax,
        coordinate_space=CoordinateSpace.NORMALIZED_1000,
        page_bbox_xywh=[50.0, 100.0, 750.0, 300.0],
        page_width=1000.0,
        page_height=1000.0,
        rotation=0,
    )


def _mandatory_keys() -> set[str]:
    return {
        "element_id",
        "element_type",
        "source_document_id",
        "page_number",
        "bounding_box",
        "content",
        "extraction_method",
        "extractor_version",
        "confidence",
        "validation_status",
        "warnings",
        "source_crop_reference",
    }


class TestAllRequiredModelsAndFields:
    def test_all_twelve_models_and_mandatory_element_fields_present(self):
        bb = _sample_bbox()
        warn = ExtractionWarning(
            code="low_contrast_tick",
            message="Secondary tick faded",
            severity=WarningSeverity.LOW,
            source="chart_validator",
            element_id="el-chart-1",
            page_number=1,
        )
        crop_ref = SourceCropReference(
            crop_id="p1-el-chart-1-crop-abcdef123456",
            crop_ref="lore://charts/crops/p1-el-chart-1-crop-abcdef123456.png",
            mime_type="image/png",
            sha256="a" * 64,
            byte_size=1024,
            width_px=400,
            height_px=300,
            crop_rect_px=[40, 80, 440, 380],
            source_asset_name="doc-1:p1:chart",
        )
        prov = ExtractionProvenance(
            source_document_id="doc-1",
            document_version=1,
            page_number=1,
            extraction_method="pymupdf_opencv_chart",
            extractor_version="1.0.0",
            engine_name="pymupdf_opencv_chart",
            source_mode=SourceMode.VECTOR,
            language="eng",
            source_crop_reference=crop_ref,
            page_rotation=0,
            extracted_at="2026-11-12T10:00:00Z",
        )

        text_el = TextElement(
            element_id="el-text-1",
            element_type=VisualElementType.TITLE_HEADING,
            source_document_id="doc-1",
            page_number=1,
            bounding_box=_sample_bbox(20, 40, 80, 500),
            content="Quarterly Expense Summary",
            extraction_method="native_pdf",
            extractor_version="1.24.0",
            confidence=0.98,
            validation_status=ValidationStatus.VALID,
            warnings=[],
            source_crop_reference=None,
            text_role=TextRole.TITLE,
            heading_level=1,
            language="en",
            word_count=3,
        )

        table_el = TableElement(
            element_id="el-table-1",
            source_document_id="doc-1",
            page_number=1,
            bounding_box=_sample_bbox(120, 40, 350, 900),
            content="| Category | Amount |\n| Travel | $240 |",
            extraction_method="slanet_plus",
            extractor_version="SLANet_plus",
            confidence=0.87,
            validation_status=ValidationStatus.NEEDS_REVIEW,
            warnings=[],
            source_crop_reference="lore://tables/crops/el-table-1.png",
            num_rows=2,
            num_cols=3,
            headers=["Category", "Amount", None],
            header_row_indices=[0],
            cells=[
                TableCell(row_index=0, col_index=0, is_header=True, status=TableCellStatus.POPULATED, value="Category", confidence=0.95),
                TableCell(row_index=0, col_index=1, is_header=True, status=TableCellStatus.POPULATED, value="Amount", confidence=0.94),
                TableCell(row_index=0, col_index=2, is_header=True, status=TableCellStatus.UNKNOWN, value=None, confidence=None, needs_review=True),
                TableCell(row_index=1, col_index=0, status=TableCellStatus.EMPTY, value=None, source="none", confidence=None),
                TableCell(row_index=1, col_index=1, status=TableCellStatus.UNREADABLE, value=None, source="ocr_tesseract", confidence=0.21, needs_review=True),
                TableCell(row_index=1, col_index=2, status=TableCellStatus.MISSING, value=None, source="none", confidence=None, needs_review=True),
            ],
            footnotes=["All values preliminary."],
        )

        chart_el = ChartElement(
            element_id="el-chart-1",
            source_document_id="doc-1",
            page_number=1,
            bounding_box=bb,
            content="Bar chart: Q1=120 exact, Q2=145.5 estimated, Q3 unavailable",
            extraction_method="pymupdf_opencv_chart",
            extractor_version="1.0.0",
            confidence=0.79,
            validation_status=ValidationStatus.NEEDS_REVIEW,
            warnings=[warn],
            source_crop_reference=crop_ref,
            provenance=prov,
            chart_type=ChartType.VERTICAL_BAR,
            title="Quarterly Revenue",
            source_mode=SourceMode.VECTOR,
            axes=[
                ChartAxis(
                    axis_id="y1",
                    unit="USD",
                    scale_type="linear",
                    is_calibrated=True,
                    origin_value=50.0,
                    min_value=50.0,
                    max_value=200.0,
                    contains_zero=False,
                    tick_values=[50.0, 100.0, 150.0, 200.0],
                )
            ],
            series=[
                ChartSeries(
                    series_id="s1",
                    name="Revenue",
                    axis_id="y1",
                    unit="USD",
                    color_hex="#1F77B4",
                    data_points=[
                        ChartDataPoint(category="Q1", value=120.0, precision=ChartValuePrecision.EXACT, unit="USD", source="native_data_label"),
                        ChartDataPoint(category="Q2", value=145.5, precision=ChartValuePrecision.ESTIMATED, unit="USD", uncertainty=1.8, source="vector_geometry"),
                        ChartDataPoint(category="Q3", value=None, precision=ChartValuePrecision.UNAVAILABLE, source="unavailable"),
                    ],
                )
            ],
        )

        form_el = FormElement(
            element_id="el-form-1",
            source_document_id="doc-1",
            page_number=1,
            bounding_box=_sample_bbox(420, 40, 950, 920),
            content="Vendor: Northstar | Manager Approval: Pending slot",
            extraction_method="pymupdf_opencv_form",
            extractor_version="1.0.0",
            confidence=0.84,
            validation_status=ValidationStatus.INCOMPLETE,
            warnings=[],
            source_crop_reference="lore://forms/crops/el-form-1.png",
            form_subtype="expense_claim",
            column_count=2,
            fields=[
                FormField(field_id="f1", label="Vendor", field_type=FormFieldType.TEXT, value="Northstar", status=FormFieldStatus.POPULATED, confidence=0.95),
                FormField(field_id="f2", label="PO Number", field_type=FormFieldType.TEXT, value=None, status=FormFieldStatus.EMPTY, source="structural_slot"),
                FormField(field_id="f3", label="Receipt Ref", field_type=FormFieldType.TEXT, value=None, status=FormFieldStatus.UNREADABLE, possibly_handwritten=True, confidence=0.18),
                FormField(field_id="f4", label="Express", field_type=FormFieldType.CHECKBOX, value=None, status=FormFieldStatus.UNKNOWN, selection_state=SelectionState.UNKNOWN),
                FormField(field_id="f5", label="Standard", field_type=FormFieldType.RADIO, value="checked", status=FormFieldStatus.CHECKED, selection_state=SelectionState.CHECKED),
                FormField(field_id="f6", label="Approval", field_type=FormFieldType.TEXT, value="Signed", status=FormFieldStatus.POPULATED, is_approval_field=True),
            ],
            radio_groups=[FormRadioGroup(group_id="rg1", option_field_ids=["f5"], selected_value="Standard")],
        )

        unknown_el = VisualElement(
            element_id="el-fig-1",
            element_type=VisualElementType.FIGURE,
            source_document_id="doc-1",
            page_number=1,
            bounding_box=_sample_bbox(700, 700, 900, 950),
            content=None,
            extraction_method="pp_doclayout_s",
            extractor_version="PP-DocLayout-S",
            confidence=None,
            validation_status=ValidationStatus.NEEDS_REVIEW,
            warnings=[],
            source_crop_reference=None,
        )

        doc = VisualDocument(
            schema_version=VISUAL_SCHEMA_ID,
            source_document_id="doc-1",
            document_version=1,
            title="Expense Report Q1",
            page_count=1,
            pages=[VisualPage(page_number=1, width=1000.0, height=1000.0, rotation=0)],
            elements=[text_el, table_el, chart_el, form_el, unknown_el],
            validation_status=ValidationStatus.NEEDS_REVIEW,
        )

        dumped = doc.to_dict()
        assert dumped["schema_version"] == "lore.visual/1.0"
        assert len(dumped["elements"]) == 5
        for el_dict in dumped["elements"]:
            assert _mandatory_keys().issubset(set(el_dict.keys()))

        # Subclass inheritance & precision counts check
        for el in doc.elements:
            assert isinstance(el, VisualElement)
        assert chart_el.value_precision_summary() == {"exact": 1, "estimated": 1, "unavailable": 1}


class TestStrictValidationCoordinatesAndPageRefs:
    def test_strict_type_enforcement_rejects_scalar_coercion_and_non_finite_values(self):
        bb = _sample_bbox()
        base = {
            "element_id": "el-1",
            "element_type": "text",
            "source_document_id": "doc-1",
            "page_number": 1,
            "bounding_box": bb.to_dict(),
            "content": "Sample",
            "extraction_method": "native_pdf",
            "extractor_version": "1.0",
            "confidence": 0.9,
            "validation_status": "valid",
            "warnings": [],
            "source_crop_reference": None,
        }

        # String where int expected
        bad_page_str = {**base, "page_number": "1"}
        with pytest.raises(ValidationError):
            TextElement.model_validate(bad_page_str)

        # Bool where int expected (Python bool is subclass of int!)
        bad_page_bool = {**base, "page_number": True}
        with pytest.raises(ValidationError):
            TextElement.model_validate(bad_page_bool)

        # String where float expected
        bad_conf_str = {**base, "confidence": "0.9"}
        with pytest.raises(ValidationError):
            TextElement.model_validate(bad_conf_str)

        # Bool where float expected
        bad_conf_bool = {**base, "confidence": True}
        with pytest.raises(ValidationError):
            TextElement.model_validate(bad_conf_bool)

        # NaN / Inf where finite float expected
        for non_finite in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValidationError):
                TextElement.model_validate({**base, "confidence": non_finite})

        # Non-string / whitespace ID
        with pytest.raises(ValidationError):
            TextElement.model_validate({**base, "element_id": "   "})
        with pytest.raises(ValidationError):
            TextElement.model_validate({**base, "element_id": 123})

        # Unknown field forbidden in strict lore.visual/1.0
        with pytest.raises(ValidationError):
            TextElement.model_validate({**base, "unexpected_v1_extra": "boom"})

        # Strict post-construction assignment validation
        valid_el = TextElement.model_validate(base)
        with pytest.raises(ValidationError):
            valid_el.page_number = 0
        with pytest.raises(ValidationError):
            valid_el.confidence = 1.5

    def test_bounding_box_coordinate_and_rotation_validation(self):
        # Inverted y / x
        with pytest.raises(ValidationError):
            BoundingBox(ymin=500, xmin=10, ymax=200, xmax=100)
        with pytest.raises(ValidationError):
            BoundingBox(ymin=10, xmin=500, ymax=200, xmax=100)

        # Out of normalized [0, 1000] bounds
        with pytest.raises(ValidationError):
            BoundingBox(ymin=0, xmin=0, ymax=1001, xmax=500)
        with pytest.raises(ValidationError):
            BoundingBox(ymin=-1, xmin=0, ymax=100, xmax=500)

        # Out of unit [0.0, 1.0] bounds
        with pytest.raises(ValidationError):
            BoundingBox(ymin=0.1, xmin=0.2, ymax=1.05, xmax=0.8, coordinate_space=CoordinateSpace.NORMALIZED_0_1)

        # Page points exceeding page_width
        with pytest.raises(ValidationError):
            BoundingBox(ymin=10, xmin=10, ymax=200, xmax=700, coordinate_space=CoordinateSpace.PAGE_POINTS, page_width=612.0, page_height=792.0)

        # Invalid rotation
        with pytest.raises(ValidationError):
            BoundingBox(ymin=0, xmin=0, ymax=100, xmax=100, rotation=45)

    def test_document_level_page_ref_and_document_id_cross_validation(self):
        bb = _sample_bbox()
        el_p3 = TextElement(
            element_id="el-p3",
            source_document_id="doc-1",
            page_number=3,
            bounding_box=bb,
            content="Page 3",
            extraction_method="native_pdf",
            extractor_version="1.0",
        )
        # Element page_number > doc.page_count
        with pytest.raises(ValidationError):
            VisualDocument(source_document_id="doc-1", page_count=2, elements=[el_p3])

        # Source document ID mismatch
        el_wrong_doc = TextElement(
            element_id="el-1",
            source_document_id="doc-other",
            page_number=1,
            bounding_box=bb,
            content="Mismatch",
            extraction_method="native_pdf",
            extractor_version="1.0",
        )
        with pytest.raises(ValidationError):
            VisualDocument(source_document_id="doc-1", page_count=2, elements=[el_wrong_doc])

        # Duplicate element_id
        el_dup1 = TextElement(element_id="dup", source_document_id="doc-1", page_number=1, bounding_box=bb, content="A", extraction_method="native_pdf", extractor_version="1.0")
        el_dup2 = TextElement(element_id="dup", source_document_id="doc-1", page_number=1, bounding_box=bb, content="B", extraction_method="native_pdf", extractor_version="1.0")
        with pytest.raises(ValidationError):
            VisualDocument(source_document_id="doc-1", page_count=1, elements=[el_dup1, el_dup2])

        # Contradictory VisualPage dimensions vs BoundingBox page_points
        el_px = TextElement(
            element_id="el-px",
            source_document_id="doc-1",
            page_number=1,
            bounding_box=BoundingBox(ymin=10, xmin=10, ymax=200, xmax=750, coordinate_space=CoordinateSpace.PAGE_POINTS),
            content="Too wide",
            extraction_method="native_pdf",
            extractor_version="1.0",
        )
        with pytest.raises(ValidationError):
            VisualDocument(
                source_document_id="doc-1",
                page_count=1,
                pages=[VisualPage(page_number=1, width=612.0, height=792.0)],
                elements=[el_px],
            )

    def test_provenance_warning_and_bounding_box_conversions(self):
        # BoundingBox xywh -> canonical [ymin, xmin, ymax, xmax] conversion
        bb = BoundingBox.from_xywh(61.2, 79.2, 122.4, 158.4, page_width=612.0, page_height=792.0, rotation=90)
        assert bb.to_normalized_list() == [100, 100, 300, 300]
        assert bb.rotation == 90

        # Contradictory provenance page_number or source_document_id must raise ValidationError
        with pytest.raises(ValidationError):
            TextElement(
                element_id="el-prov-bad",
                source_document_id="doc-1",
                page_number=1,
                bounding_box=bb,
                content="text",
                extraction_method="native_pdf",
                extractor_version="1.0",
                provenance=ExtractionProvenance(
                    source_document_id="doc-other",
                    page_number=1,
                    extraction_method="native_pdf",
                    extractor_version="1.0",
                ),
            )

        # Warning referencing wrong page_number on element or unknown element_id on doc must fail
        with pytest.raises(ValidationError):
            TextElement(
                element_id="el-warn-bad",
                source_document_id="doc-1",
                page_number=1,
                bounding_box=bb,
                content="text",
                extraction_method="native_pdf",
                extractor_version="1.0",
                warnings=[
                    ExtractionWarning(code="bad_page", message="wrong page", page_number=2)
                ],
            )

        with pytest.raises(ValidationError):
            VisualDocument(
                source_document_id="doc-1",
                page_count=1,
                elements=[
                    TextElement(
                        element_id="el-real",
                        source_document_id="doc-1",
                        page_number=1,
                        bounding_box=_sample_bbox(),
                        content="ok",
                        extraction_method="native_pdf",
                        extractor_version="1.0",
                    )
                ],
                warnings=[
                    ExtractionWarning(code="orphan_warn", message="missing element", element_id="el-nonexistent")
                ],
            )


class TestConfidenceAndEpistemicSemantics:
    def test_no_fabricated_confidence_on_missing_or_unavailable_extractions(self):
        bb = _sample_bbox()
        # Omitted confidence stays strictly None
        el = TextElement(
            element_id="el-noconf",
            source_document_id="doc-1",
            page_number=1,
            bounding_box=bb,
            content=None,
            extraction_method="unavailable",
            extractor_version="1.0",
            validation_status=ValidationStatus.UNAVAILABLE,
        )
        assert el.confidence is None

        # Non-null confidence when extraction_method is 'unavailable' must be rejected
        with pytest.raises(ValidationError):
            TextElement(
                element_id="el-fake-conf",
                source_document_id="doc-1",
                page_number=1,
                bounding_box=bb,
                content=None,
                extraction_method="unavailable",
                extractor_version="1.0",
                confidence=0.85,
                validation_status=ValidationStatus.UNAVAILABLE,
            )

        # Non-null confidence with provenance source_mode='unavailable' must be rejected
        with pytest.raises(ValidationError):
            VisualElement(
                element_id="el-fake-prov-conf",
                element_type=VisualElementType.FIGURE,
                source_document_id="doc-1",
                page_number=1,
                bounding_box=bb,
                content=None,
                extraction_method="tesseract_ocr",
                extractor_version="5.3",
                confidence=0.5,
                validation_status=ValidationStatus.UNAVAILABLE,
                provenance=ExtractionProvenance(
                    source_document_id="doc-1",
                    page_number=1,
                    extraction_method="tesseract_ocr",
                    extractor_version="5.3",
                    source_mode=SourceMode.UNAVAILABLE,
                ),
            )

    def test_chart_precision_exact_estimated_unavailable_rules(self):
        # Unavailable MUST have null numeric value
        with pytest.raises(ValidationError):
            ChartDataPoint(category="Q3", value=55.0, precision=ChartValuePrecision.UNAVAILABLE)

        # Unavailable from unavailable source cannot fabricate confidence
        with pytest.raises(ValidationError):
            ChartDataPoint(category="Q3", value=None, precision=ChartValuePrecision.UNAVAILABLE, source="unavailable", confidence=0.9)

        # Exact and estimated MUST carry non-null values
        with pytest.raises(ValidationError):
            ChartDataPoint(category="Q1", value=None, precision=ChartValuePrecision.EXACT)
        with pytest.raises(ValidationError):
            ChartDataPoint(category="Q2", value=None, precision=ChartValuePrecision.ESTIMATED)

        # Exact cannot claim positive uncertainty
        with pytest.raises(ValidationError):
            ChartDataPoint(category="Q1", value=100.0, precision=ChartValuePrecision.EXACT, uncertainty=2.5)

    def test_table_cell_empty_unreadable_unknown_and_grid_rules(self):
        bb = _sample_bbox()
        # Populated requires non-empty text
        with pytest.raises(ValidationError):
            TableCell(row_index=0, col_index=0, status=TableCellStatus.POPULATED, value=None)
        with pytest.raises(ValidationError):
            TableCell(row_index=0, col_index=0, status=TableCellStatus.POPULATED, value="  ")

        # Empty / unreadable / missing reject values
        for st in (TableCellStatus.EMPTY, TableCellStatus.UNREADABLE, TableCellStatus.MISSING):
            with pytest.raises(ValidationError):
                TableCell(row_index=0, col_index=0, status=st, value="unexpected")

        # Missing cell rejects fabricated confidence
        with pytest.raises(ValidationError):
            TableCell(row_index=0, col_index=0, status=TableCellStatus.MISSING, value=None, confidence=0.5)

        # Header count mismatch and overlapping cell span collision rejected
        with pytest.raises(ValidationError):
            TableElement(
                element_id="t1",
                source_document_id="doc-1",
                page_number=1,
                bounding_box=bb,
                content=None,
                extraction_method="slanet_plus",
                extractor_version="1.0",
                num_rows=2,
                num_cols=2,
                headers=["Col1"],  # length 1 != num_cols 2
            )

        with pytest.raises(ValidationError):
            TableElement(
                element_id="t2",
                source_document_id="doc-1",
                page_number=1,
                bounding_box=bb,
                content=None,
                extraction_method="slanet_plus",
                extractor_version="1.0",
                num_rows=2,
                num_cols=2,
                cells=[
                    TableCell(row_index=0, col_index=0, row_span=2, col_span=1, status=TableCellStatus.POPULATED, value="Merged"),
                    TableCell(row_index=1, col_index=0, status=TableCellStatus.EMPTY, value=None),
                ],
            )

    def test_form_field_empty_unreadable_unknown_and_ambiguous_rules(self):
        # Empty / unreadable cannot carry fabricated values
        for st in (FormFieldStatus.EMPTY, FormFieldStatus.UNREADABLE, FormFieldStatus.SIGNATURE_BLANK):
            with pytest.raises(ValidationError):
                FormField(field_id="f1", label="Amount", field_type=FormFieldType.CURRENCY, status=st, value="100.00")

        # Conflicting checkbox status vs selection_state
        with pytest.raises(ValidationError):
            FormField(
                field_id="cb1",
                label="Agree",
                field_type=FormFieldType.CHECKBOX,
                status=FormFieldStatus.CHECKED,
                selection_state=SelectionState.UNCHECKED,
            )

        # Radio group referencing nonexistent field_id
        with pytest.raises(ValidationError):
            FormElement(
                element_id="frm-1",
                source_document_id="doc-1",
                page_number=1,
                bounding_box=_sample_bbox(),
                content=None,
                extraction_method="pymupdf_opencv_form",
                extractor_version="1.0",
                fields=[],
                radio_groups=[FormRadioGroup(group_id="rg1", option_field_ids=["missing_opt"], is_ambiguous=True)],
            )


class TestSchemaVersionSerializationAndEvolution:
    def test_schema_version_validation_and_rejection_of_governance_or_major_v2(self):
        assert parse_visual_schema_version("lore.visual/1.0") == (1, 0)
        assert parse_visual_schema_version("lore.visual/1.3") == (1, 3)

        for bad_ver in (
            "lore.visual/2.0",
            "lore.visual/0.9",
            "lore.visual/1",
            "lore.visual/abc",
            "lore.result/1",
            "lore.result/2",
            "1.0",
            "",
            10,
        ):
            with pytest.raises((ValidationError, ValueError)):
                VisualDocument.model_validate(
                    {
                        "schema_version": bad_ver,
                        "source_document_id": "doc-1",
                        "page_count": 1,
                    }
                )

    def test_consistent_deterministic_serialization_and_json_schema_export(self):
        bb = _sample_bbox()
        el_a = TextElement(
            element_id="e1",
            source_document_id="doc-1",
            page_number=1,
            bounding_box=bb,
            content="Text A",
            extraction_method="native_pdf",
            extractor_version="1.0",
            metadata={"z_key": 2, "a_key": 1},
        )
        el_b = TextElement(
            element_id="e1",
            source_document_id="doc-1",
            page_number=1,
            bounding_box=bb,
            content="Text A",
            extraction_method="native_pdf",
            extractor_version="1.0",
            metadata={"a_key": 1, "z_key": 2},
        )
        doc_a = VisualDocument(source_document_id="doc-1", page_count=1, elements=[el_a])
        doc_b = VisualDocument(source_document_id="doc-1", page_count=1, elements=[el_b])

        # Identical canonical JSON regardless of dict insertion order
        json_a = doc_a.to_json()
        json_b = doc_b.to_json()
        assert json_a == json_b

        reloaded = validate_visual_document_payload(json_a)
        assert reloaded == doc_a
        assert isinstance(reloaded.elements[0], TextElement)

        json_schema = VisualDocument.export_json_schema()
        assert json_schema["x-lore-schema-id"] == VISUAL_SCHEMA_ID
        assert json_schema["$id"].endswith(f"{VISUAL_SCHEMA_ID}.json")

    def test_backward_compatible_minor_evolution_and_legacy_migration(self):
        # 1. Minor evolution payload (lore.visual/1.1) with unrecognized additive fields
        v1_1_payload = {
            "schema_version": "lore.visual/1.1",
            "source_document_id": "doc-evol-1",
            "page_count": 1,
            "future_pipeline_profile": "gpu_offload_v2",
            "elements": [
                {
                    "element_id": "tbl-v11",
                    "element_type": "table",
                    "source_document_id": "doc-evol-1",
                    "page_number": 1,
                    "bounding_box": {"ymin": 10, "xmin": 10, "ymax": 500, "xmax": 900},
                    "content": "| A |",
                    "extraction_method": "slanet_plus",
                    "extractor_version": "1.1",
                    "validation_status": "valid",
                    "table_caption_v1_1": "Financial Highlights",
                    "num_rows": 1,
                    "num_cols": 1,
                    "headers": ["A"],
                    "cells": [
                        {
                            "row_index": 0,
                            "col_index": 0,
                            "status": "populated",
                            "value": "42",
                            "v1_1_cell_currency": "USD",
                        }
                    ],
                }
            ],
        }
        evolved_doc = VisualDocument.model_validate(v1_1_payload)
        assert evolved_doc.schema_version == "lore.visual/1.1"
        assert evolved_doc.schema_extensions == {"future_pipeline_profile": "gpu_offload_v2"}
        assert isinstance(evolved_doc.elements[0], TableElement)
        assert evolved_doc.elements[0].schema_extensions == {"table_caption_v1_1": "Financial Highlights"}
        assert evolved_doc.elements[0].cells[0].schema_extensions == {"v1_1_cell_currency": "USD"}

        # Lossless round-trip on evolved 1.1 payload
        assert VisualDocument.from_json(evolved_doc.to_json()) == evolved_doc

        # Still strictly enforces types on 1.1
        bad_v1_1 = json.loads(json.dumps(v1_1_payload))
        bad_v1_1["elements"][0]["num_rows"] = "1"
        with pytest.raises(ValidationError):
            VisualDocument.model_validate(bad_v1_1)

        # 2. Same additive field on lore.visual/1.0 MUST be strictly rejected
        strict_v1_0 = json.loads(json.dumps(v1_1_payload))
        strict_v1_0["schema_version"] = "lore.visual/1.0"
        with pytest.raises(ValidationError):
            VisualDocument.model_validate(strict_v1_0)

        # 3. Migrate legacy pre-schema LORE CanonicalExtractedPageContract page payload
        legacy_page = {
            "page_number": 1,
            "text": "Legacy page text",
            "confidence": 0.91,
            "words_count": 3,
            "width": 612.0,
            "height": 792.0,
            "extraction_type": "digital_pdf",
            "engine": "pymupdf",
            "engine_version": "1.24",
            "is_repaired": False,
            "bounding_boxes": [],
            "visual_regions": [
                {
                    "region_id": "p1-txt-1",
                    "region_type": "paragraph",
                    "extraction_kind": "heuristic_layout",
                    "page_number": 1,
                    "bbox": [40.0, 50.0, 300.0, 40.0],
                    "normalized_box": [63, 65, 114, 555],
                    "text": "Legacy visual paragraph",
                    "markdown": "Legacy visual paragraph",
                    "confidence": 0.91,
                    "engine": "pp_doclayout_s",
                    "engine_version": "PP-DocLayout-S",
                    "is_inference": False,
                    "is_repaired": False,
                    "metadata": {},
                }
            ],
        }
        migrated = migrate_visual_payload(legacy_page, source_document_id="legacy-doc-9")
        assert migrated.schema_version == VISUAL_SCHEMA_ID
        assert migrated.source_document_id == "legacy-doc-9"
        assert isinstance(migrated.elements[0], TextElement)
        assert migrated.elements[0].content == "Legacy visual paragraph"


class _UnavailableOCRProvider(BaseOCRProvider):
    provider_name = "unavailable_test_ocr"

    def is_available(self) -> bool:
        return False

    def extract_image(self, image, language=None):
        return {
            "status": "provider_unavailable",
            "text": "[OCR Engine Optional: unavailable]",
            "confidence": 0.0,
            "words_count": 0,
            "width": image.width,
            "height": image.height,
            "engine": self.provider_name,
            "engine_version": "unavailable",
            "bounding_boxes": [],
            "needs_review": True,
            "is_optional_skipped": True,
        }


class TestExtractorAdaptersAndGovernanceContractIsolation:
    def test_real_chart_and_form_extractors_convert_cleanly_to_visual_schema(self):
        # 1. Ambiguous low-res chart with unavailable OCR -> honest null values & non-fabricated confidence
        img_ch = Image.new("RGB", (60, 40), (255, 255, 255))
        draw = ImageDraw.Draw(img_ch)
        draw.rectangle([10, 10, 25, 35], fill=(40, 90, 180))
        chart_ext = PyMuPDFOpenCVChartExtractor(ocr_provider=_UnavailableOCRProvider())
        ch_reg = chart_ext.extract_chart_region(
            page_image=img_ch,
            chart_box=[0, 0, 1000, 1000],
            bbox_format="normalized",
            page_number=1,
            page_width=60.0,
            page_height=40.0,
            region_id="p1-ch-lowres",
        )
        img_ch.close()

        # 2. Vector PDF form page (blank + populated + approval field + signature) via FormKVExtractor
        import pymupdf

        pdf_doc = pymupdf.open()
        pg = pdf_doc.new_page(width=612, height=792)
        pg.insert_text((50, 60), "EXPENSE FORM", fontsize=14)
        pg.insert_text((50, 110), "Invoice Number: INV-2026-009", fontsize=11)
        pg.insert_text((50, 145), "Manager Approval: Signed", fontsize=11)
        pg.insert_text((50, 185), "Notes:", fontsize=11)
        pg.draw_rect(pymupdf.Rect(110, 172, 280, 195), color=(0, 0, 0), width=1.2)
        pg.insert_text((50, 235), "Authorized Signature:", fontsize=11)
        pg.draw_line((180, 240), (360, 240), color=(0, 0, 0), width=1.2)

        pix = pg.get_pixmap(dpi=144)
        img_frm = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        native_words = []
        for x0, y0, x1, y1, word, *_ in pg.get_text("words"):
            native_words.append({
                "word": word,
                "confidence": 0.99,
                "x": int(round(x0)),
                "y": int(round(y0)),
                "w": max(1, int(round(x1 - x0))),
                "h": max(1, int(round(y1 - y0))),
                "normalized_box": [
                    max(0, min(1000, int(round((y0 / 792.0) * 1000)))),
                    max(0, min(1000, int(round((x0 / 612.0) * 1000)))),
                    max(0, min(1000, int(round((y1 / 792.0) * 1000)))),
                    max(0, min(1000, int(round((x1 / 612.0) * 1000)))),
                ],
            })

        frm_ext = FormKVExtractor(config=FormExtractorConfig(), ocr_provider=_UnavailableOCRProvider())
        frm_reg = frm_ext.extract_form_region(
            page_image=img_frm,
            form_box=[0, 0, 1000, 1000],
            bbox_format="normalized",
            page_number=2,
            page_width=612.0,
            page_height=792.0,
            region_id="p2-frm-1",
            pymupdf_page=pg,
            native_words=native_words,
        )
        img_frm.close()
        pdf_doc.close()

        vdoc = pages_to_visual_document(
            [
                {
                    "page_number": 1,
                    "width": 60.0,
                    "height": 40.0,
                    "engine": "pp_doclayout_s",
                    "engine_version": "PP-DocLayout-S",
                    "confidence": None,
                    "needs_review": True,
                    "visual_regions": [ch_reg],
                },
                {
                    "page_number": 2,
                    "width": 612.0,
                    "height": 792.0,
                    "engine": "pymupdf",
                    "engine_version": "1.24",
                    "confidence": 0.99,
                    "needs_review": True,
                    "visual_regions": [frm_reg],
                },
            ],
            source_document_id="doc-real-mix",
            document_type="pdf",
        )

        assert vdoc.schema_version == "lore.visual/1.0"
        assert vdoc.page_count == 2
        ch_el = vdoc.elements[0]
        frm_el = vdoc.elements[1]
        assert isinstance(ch_el, ChartElement)
        assert isinstance(frm_el, FormElement)
        # Unavailable OCR on low-res chart kept confidence strictly None (never fabricated!)
        assert ch_el.confidence is None
        assert ch_el.validation_status in (ValidationStatus.NEEDS_REVIEW, ValidationStatus.UNAVAILABLE)
        assert ch_el.source_crop_reference is not None
        # Form blank slot & approval/signature fields preserved without fabrication or governance decision
        statuses_by_lbl = {f.label: f.status for f in frm_el.fields}
        assert statuses_by_lbl.get("Invoice Number") == FormFieldStatus.POPULATED
        assert statuses_by_lbl.get("Notes") == FormFieldStatus.EMPTY
        assert any(f.is_approval_field and f.label == "Manager Approval" for f in frm_el.fields)
        assert not hasattr(frm_el, "verdict") and not hasattr(vdoc, "directive")

        # JSON round-trip preserves exact validated contract
        assert VisualDocument.from_json(vdoc.to_json()) == vdoc

        # Existing LORE lore.result/2 Governance contract remains completely independent and intact
        gov_env = validate_canonical_envelope(
            {
                "schema": "lore.result/2",
                "state": Verdict.SUPPORTED.value,
                "directive": Directive.PROCEED_AND_CITE.value,
                "citations": [{"document_id": "doc-real-mix", "passage": "Invoice Number: INV-2026-009"}],
            }
        )
        assert gov_env["schema"] == "lore.result/2"

    def test_table_and_ambiguous_form_region_conversion_preserves_states_and_nulls(self):
        table_region = {
            "region_id": "p1-tbl-1",
            "region_type": "table",
            "extraction_kind": "vector_table",
            "page_number": 1,
            "bbox": [40.0, 120.0, 520.0, 180.0],
            "normalized_box": [150, 65, 380, 915],
            "text": "| Metric | Q1 | Q2 |\n| Rev | 100 |  |",
            "markdown": "| Metric | Q1 | Q2 |\n| Rev | 100 |  |",
            "confidence": 0.84,
            "engine": "slanet_plus",
            "engine_version": "SLANet_plus",
            "is_inference": False,
            "is_repaired": False,
            "source_asset_name": "page_1:p1-tbl-1",
            "metadata": {
                "needs_review": True,
                "table_structure": {
                    "num_rows": 2,
                    "num_cols": 3,
                    "has_merged_cells": False,
                    "headers": ["Metric", "Q1", ""],
                    "header_row_indices": [0],
                    "structure_score": 0.88,
                    "cells": [
                        {"cell_id": "c00", "row": 0, "col": 0, "rowspan": 1, "colspan": 1, "is_header": True, "state": "populated", "text": "Metric", "source": "native_pdf", "confidence": 0.99, "normalized_box": [150, 65, 220, 300], "bbox": [40.0, 120.0, 150.0, 40.0]},
                        {"cell_id": "c01", "row": 0, "col": 1, "rowspan": 1, "colspan": 1, "is_header": True, "state": "populated", "text": "Q1", "source": "native_pdf", "confidence": 0.99, "normalized_box": [150, 300, 220, 600], "bbox": [190.0, 120.0, 180.0, 40.0]},
                        {"cell_id": "c02", "row": 0, "col": 2, "rowspan": 1, "colspan": 1, "is_header": True, "state": "unknown", "text": "", "source": "ocr_tesseract", "confidence": 0.12, "needs_review": True, "normalized_box": [150, 600, 220, 915], "bbox": [370.0, 120.0, 190.0, 40.0]},
                        {"cell_id": "c10", "row": 1, "col": 0, "rowspan": 1, "colspan": 1, "is_header": False, "state": "populated", "text": "Rev", "source": "native_pdf", "confidence": 0.98, "normalized_box": [220, 65, 380, 300], "bbox": [40.0, 160.0, 150.0, 80.0]},
                        {"cell_id": "c11", "row": 1, "col": 1, "rowspan": 1, "colspan": 1, "is_header": False, "state": "unreadable", "text": "", "source": "ocr_tesseract", "confidence": 0.19, "needs_review": True, "warnings": ["unreadable_cell_ocr_low_conf"], "normalized_box": [220, 300, 380, 600], "bbox": [190.0, 160.0, 180.0, 80.0]},
                        {"cell_id": "c12", "row": 1, "col": 2, "rowspan": 1, "colspan": 1, "is_header": False, "state": "empty", "text": "", "source": "none", "confidence": 0.0, "normalized_box": [220, 600, 380, 915], "bbox": [370.0, 160.0, 190.0, 80.0]},
                    ],
                },
                "table_validation": {
                    "needs_review": True,
                    "issues": [{"code": "unreadable_cells_present", "severity": "high", "detail": "1 unreadable cell"}],
                },
            },
        }

        tbl_el = region_dict_to_visual_element(table_region, source_document_id="doc-tbl-1", page_width=612.0, page_height=792.0)
        assert isinstance(tbl_el, TableElement)
        assert tbl_el.headers == ["Metric", "Q1", None]  # Empty header became nullable None!
        assert tbl_el.validation_status == ValidationStatus.NEEDS_REVIEW
        assert [c.status for c in tbl_el.cells] == [
            TableCellStatus.POPULATED,
            TableCellStatus.POPULATED,
            TableCellStatus.UNKNOWN,
            TableCellStatus.POPULATED,
            TableCellStatus.UNREADABLE,
            TableCellStatus.EMPTY,
        ]
        # Empty/unreadable/unknown cells preserve null value and unmeasured empty cell keeps confidence=None
        assert tbl_el.cells[2].value is None
        assert tbl_el.cells[4].value is None
        assert tbl_el.cells[5].value is None
        assert tbl_el.cells[5].confidence is None
        assert len(tbl_el.warnings) == 1 and tbl_el.warnings[0].code == "unreadable_cells_present"
