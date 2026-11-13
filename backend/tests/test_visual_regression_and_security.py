"""
Comprehensive Regression & Security Test Suite for LORE Visual Extraction (Prompt 10).

Covers:
  - Regression: Tesseract OCR, Bengali visual repair & numeral normalization, Native & Scanned PDFs,
    DOCX / XLSX / PPTX extractors, Celery batch routing & retry workflows, 6-stage settlement,
    L7 permissions, immutable DocumentVersion increments, HybridRetrievalService, MCP tools.
  - Visual Extraction: Tables, Charts, Forms, Bounding boxes, Provenance, Pydantic lore.visual/1.0
    strict validation, Uncertain/missing values, Batch processing.
  - Security: Untrusted upload validation (magic bytes & sizes), macro/script/XXE non-execution,
    ZIP bomb & PDF page/pixel limits, zero temp-file leakage, tenant/workspace isolation,
    no logging of sensitive extracted content.
"""
import io
import json
import logging
import os
import tempfile
import uuid
import zipfile
from unittest.mock import patch

import fitz  # PyMuPDF
import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw

import mcp_server
from apps.governance.layers import PermissionLayer
from apps.governance.models import AccessLevel, SourcePermission
from apps.identity.models import Organization
from apps.ingestion.batch import IngestionBatchService
from apps.ingestion.models import IngestionBatch, IngestionJob
from apps.ingestion.pipeline.charts import PyMuPDFOpenCVChartExtractor
from apps.ingestion.pipeline.extractors import (
    PresentationExtractor,
    UnifiedDocumentExtractor,
    WorkerExtractorRegistry,
)
from apps.ingestion.pipeline.forms import CheckboxState, FormKVExtractor
from apps.ingestion.pipeline.ocr import (
    BaseOCRProvider,
    OCRRouter,
    bangla_to_arabic_digits,
    is_visual_encoded_document,
    repair_visual_bengali_document,
)
from apps.ingestion.pipeline.pdf_visual import PDFSafetyLimits, PyMuPDFVisualPDFAdapter
from apps.ingestion.pipeline.tables import CellStatus, SLANetPlusTableExtractor
from apps.ingestion.pipeline.visual_schema import (
    ChartValuePrecision,
    VisualDocument,
    validate_visual_document_payload,
)
from apps.ingestion.settlement import SettlementGateCoordinator
from apps.retrieval.services import HybridRetrievalService
from apps.sources.models import DocumentVersion, SourceDocument
from apps.sources.services import StorageSecurityService
from apps.workspaces.models import Workspace


# ---------------------------------------------------------------------------
# Helpers to synthesize realistic untrusted/test artifacts in memory
# ---------------------------------------------------------------------------

def _make_png_bytes(width: int = 400, height: int = 240) -> bytes:
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, width - 20, height - 20], outline=(0, 0, 0), width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img.close()
    return buf.getvalue()


def _make_digital_table_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    x0, y0, col_w, row_h = 60, 100, 150, 36
    for r in range(4):
        y = y0 + r * row_h
        page.draw_line((x0, y), (x0 + 3 * col_w, y), color=(0, 0, 0), width=1)
    for c in range(4):
        x = x0 + c * col_w
        page.draw_line((x, y0), (x, y0 + 3 * row_h), color=(0, 0, 0), width=1)

    cells = [
        ["Category", "FY2025", "Unit"],
        ["Travel", "$1,250.50", "USD"],
        ["Meals", "", "USD"],
    ]
    for r_idx, row in enumerate(cells):
        for c_idx, val in enumerate(row):
            if val:
                page.insert_text((x0 + c_idx * col_w + 10, y0 + r_idx * row_h + 22), val, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _make_vector_bar_chart_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((180, 90), "Quarterly Revenue ($M)", fontsize=14)
    page.draw_line((120, 120), (120, 320), color=(0, 0, 0), width=1.5)
    page.draw_line((120, 320), (460, 320), color=(0, 0, 0), width=1.5)
    for tick_val, ty in [("30", 140), ("20", 200), ("10", 260), ("0", 320)]:
        page.draw_line((114, ty), (120, ty), color=(0, 0, 0), width=1)
        page.insert_text((90, ty + 4), tick_val, fontsize=10)
    bars = [("Q1", 160, 260), ("Q2", 250, 200), ("Q3", 340, 140)]
    for label, bx, top_y in bars:
        page.draw_rect(fitz.Rect(bx, top_y, bx + 44, 320), color=(0.1, 0.3, 0.8), fill=(0.2, 0.45, 0.85))
        page.insert_text((bx + 12, 340), label, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


def _make_scanned_pdf_bytes(page_count: int = 1) -> bytes:
    png_bytes = _make_png_bytes(300, 200)
    doc = fitz.open()
    for _ in range(page_count):
        page = doc.new_page(width=612, height=792)
        page.insert_image(fitz.Rect(50, 50, 500, 350), stream=png_bytes)
    data = doc.tobytes()
    doc.close()
    return data


def _make_minimal_pptx_bytes(slide_text: str = "Quarterly Governance Slide", include_vba: bool = False, xml_doctype: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "ppt/presentation.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>'
            "</p:presentation>",
        )
        zf.writestr(
            "ppt/_rels/presentation.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>'
            "</Relationships>",
        )
        slide_body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            "<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r>"
            f"<a:t>{slide_text}</a:t>"
            "</a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
        )
        if xml_doctype:
            slide_body = (
                '<?xml version="1.0"?>'
                '<!DOCTYPE lolz [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
                "<p:sld><a:t>&xxe;</a:t></p:sld>"
            )
        zf.writestr("ppt/slides/slide1.xml", slide_body)
        if include_vba:
            zf.writestr("ppt/vbaProject.bin", b"MZ_FAKE_MACRO_BINARY")
    return buf.getvalue()


def _make_docx_bytes(text: str = "Governance Policy DOCX Content") -> bytes:
    import docx
    document = docx.Document()
    document.add_heading("Enterprise Compliance Standard", level=1)
    document.add_paragraph(text)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _make_xlsx_bytes(sheet_title: str = "Controls", value: str = "Control-A1") -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = sheet_title
    ws.append(["Control ID", "Status", "Owner"])
    ws.append([value, "Active", "Security Team"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _render_pymupdf_page_pil(page, dpi: int = 144) -> Image.Image:
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return img


class _StubOCRProvider(BaseOCRProvider):
    def __init__(self, text: str = "Scanned OCR Contract Clause", confidence: float = 0.88):
        self.text = text
        self.confidence = confidence
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def extract_image(self, image: Image.Image):
        self.calls += 1
        words = [w for w in self.text.split() if w]
        return {
            "text": self.text,
            "confidence": self.confidence,
            "words_count": len(words),
            "width": image.width,
            "height": image.height,
            "engine": "tesseract_stub",
            "engine_version": "5.3.0-stub",
            "status": "success",
            "needs_review": self.confidence < 0.7,
            "warnings": [],
            "bounding_boxes": [
                {"word": w, "confidence": self.confidence, "x": 10 + i * 25, "y": 10, "w": 20, "h": 12}
                for i, w in enumerate(words)
            ],
        }


def _mock_qdrant_success_for_doc(doc_id_str: str):
    return [
        patch("apps.ingestion.settlement.QdrantVectorStore.delete_document_chunks", return_value=True),
        patch("apps.ingestion.settlement.QdrantVectorStore.upsert_chunks", return_value=True),
        patch(
            "apps.ingestion.settlement.QdrantVectorStore.search",
            return_value=[{"id": "smoke-vec-1", "score": 0.99, "payload": {"document_id": doc_id_str}}],
        ),
    ]


class _StubSLANetModel:
    def predict(self, arr):
        h, w = arr.shape[:2]
        cw, rh = max(1, w // 3), max(1, h // 3)
        boxes = [
            [0, 0, cw, rh], [cw, 0, 2 * cw, rh], [2 * cw, 0, w, rh],
            [0, rh, cw, 2 * rh], [cw, rh, 2 * cw, 2 * rh], [2 * cw, rh, w, 2 * rh],
            [0, 2 * rh, cw, h], [cw, 2 * rh, 2 * cw, h], [2 * cw, 2 * rh, w, h],
        ]
        tokens = [
            "<table>", "<thead>", "<tr>", "<td>", "</td>", "<td>", "</td>", "<td>", "</td>", "</tr>", "</thead>",
            "<tbody>",
            "<tr>", "<td>", "</td>", "<td>", "</td>", "<td>", "</td>", "</tr>",
            "<tr>", "<td>", "</td>", "<td>", "</td>", "<td>", "</td>", "</tr>",
            "</tbody>", "</table>",
        ]
        return [{"res": {"structure": tokens, "bbox": boxes, "structure_score": 0.96}}]


# ===========================================================================
# 1. Visual Extraction Regression & Functional Verification
# ===========================================================================

class TestVisualExtractionRegressionMatrix:
    def test_table_extraction_preserves_structure_empty_cells_and_page_coords(self):
        pdf_bytes = _make_digital_table_pdf_bytes()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        page_img = _render_pymupdf_page_pil(page, dpi=144)
        try:
            native_words = [
                {
                    "word": str(w[4]),
                    "normalized_box": [
                        float(w[1]) / page.rect.height * 1000.0,
                        float(w[0]) / page.rect.width * 1000.0,
                        float(w[3]) / page.rect.height * 1000.0,
                        float(w[2]) / page.rect.width * 1000.0,
                    ],
                }
                for w in page.get_text("words")
            ]
            extractor = SLANetPlusTableExtractor(
                model_loader=lambda _cfg: _StubSLANetModel(),
                ocr_provider=_StubOCRProvider(text="", confidence=0.0),
            )
            res = extractor.extract_table_region(
                page_image=page_img,
                table_box=[120, 200, 1020, 416],
                bbox_format="pixel",
                page_number=1,
                page_width=page.rect.width,
                page_height=page.rect.height,
                region_id="tbl-reg-1",
                native_words=native_words,
            )
        finally:
            page_img.close()
            doc.close()

        assert res["region_type"] == "table"
        assert res["page_number"] == 1
        table_meta = res.get("metadata", {}).get("table_structure") or {}
        cells = table_meta.get("cells", [])
        assert len(cells) == 9
        texts = [c.get("text", "") for c in cells]
        assert any("Travel" in t for t in texts)
        assert any("$1,250.50" in t for t in texts)
        empty_cells = [c for c in cells if c.get("state") == CellStatus.EMPTY.value]
        assert len(empty_cells) >= 1
        for c in cells:
            assert c.get("bbox") is not None
            assert c.get("normalized_box") is not None

    def test_chart_extraction_detects_vector_chart_axes_and_precision_flags(self):
        pdf_bytes = _make_vector_bar_chart_pdf_bytes()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        page_img = _render_pymupdf_page_pil(page, dpi=144)
        try:
            extractor = PyMuPDFOpenCVChartExtractor(ocr_provider=_StubOCRProvider("Quarterly Revenue 0 10 20 30 Q1 Q2 Q3"))
            chart = extractor.extract_chart_region(
                page_image=page_img,
                chart_box=[80, 70, 380, 500],
                bbox_format="pixel",
                page_number=1,
                page_width=page.rect.width,
                page_height=page.rect.height,
                region_id="chart-reg-1",
                pymupdf_page=page,
                source_asset_name="chart_reg_doc.pdf",
            )
        finally:
            page_img.close()
            doc.close()

        assert chart["region_type"] == "chart"
        assert chart["page_number"] == 1
        meta = chart["metadata"]
        assert meta["chart"]["source_mode"] in ("vector", "hybrid", "raster", "vector_pdf")
        assert meta.get("chart_crop_reference", {}).get("crop_ref")
        assert meta.get("source_coordinates")
        valid_precisions = {p.value for p in ChartValuePrecision}
        for s in meta["chart"].get("series", []):
            for pt in s.get("points", []):
                assert pt["precision"] in valid_precisions

    def test_form_extraction_controls_signatures_and_uncertain_blank_fields(self):
        img = Image.new("RGB", (600, 320), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 40, 62, 62], outline=(0, 0, 0), width=2)
        draw.line([(43, 43), (59, 59)], fill=(0, 0, 0), width=2)
        draw.line([(59, 43), (43, 59)], fill=(0, 0, 0), width=2)
        draw.rectangle([40, 90, 62, 112], outline=(0, 0, 0), width=2)
        draw.rectangle([40, 210, 260, 270], outline=(0, 0, 0), width=1)
        draw.line([(60, 250), (110, 225), (160, 255), (210, 230)], fill=(0, 0, 0), width=2)

        class _FormStubOCR(BaseOCRProvider):
            def is_available(self) -> bool:
                return True

            def extract_image(self, image: Image.Image):
                return {
                    "text": "Approved\nRejected\nInvoice Date: 2026-04-01\nNotes:\nSignature:",
                    "confidence": 0.85,
                    "words_count": 7,
                    "width": image.width,
                    "height": image.height,
                    "engine": "tesseract_stub",
                    "engine_version": "5.3.0-stub",
                    "status": "success",
                    "bounding_boxes": [
                        {"text": "Approved", "conf": 0.9, "x": 75, "y": 42, "w": 75, "h": 18},
                        {"text": "Rejected", "conf": 0.9, "x": 75, "y": 92, "w": 70, "h": 18},
                        {"text": "Invoice", "conf": 0.9, "x": 40, "y": 140, "w": 55, "h": 18},
                        {"text": "Date:", "conf": 0.9, "x": 100, "y": 140, "w": 40, "h": 18},
                        {"text": "2026-04-01", "conf": 0.9, "x": 160, "y": 140, "w": 85, "h": 18},
                        {"text": "Notes:", "conf": 0.9, "x": 40, "y": 175, "w": 50, "h": 18},
                        {"text": "Signature:", "conf": 0.9, "x": 40, "y": 192, "w": 75, "h": 16},
                    ],
                }

        try:
            extractor = FormKVExtractor(ocr_provider=_FormStubOCR())
            res = extractor.extract_form_region(
                page_image=img,
                form_box=[0, 0, 320, 600],
                bbox_format="pixel",
                page_number=1,
                source_asset_name="doc-form-test.png",
            )
        finally:
            img.close()

        assert res["region_type"] == "form_kv"
        form_data = res["metadata"]["form"]
        controls = form_data.get("checkboxes", [])
        states = {c.get("state") for c in controls}
        assert CheckboxState.CHECKED.value in states
        assert CheckboxState.UNCHECKED.value in states
        assert all(c.get("approval_inferred") is False and c.get("is_authoritative_decision") is False for c in controls)
        for sf in form_data.get("signature_regions", []):
            assert sf.get("signer_identity") is None

    def test_pydantic_visual_schema_v1_rejects_invalid_and_fabricated_payloads(self):
        base_doc = {
            "schema_version": "lore.visual/1.0",
            "source_document_id": "doc-schema-1",
            "title": "Schema Validation Doc",
            "filename": "schema.pdf",
            "document_type": "pdf",
            "page_count": 1,
            "pages": [
                {
                    "page_number": 1,
                    "width": 612.0,
                    "height": 792.0,
                }
            ],
            "elements": [
                {
                    "element_id": "el-txt-1",
                    "element_type": "text",
                    "source_document_id": "doc-schema-1",
                    "page_number": 1,
                    "bounding_box": {"ymin": 0.1, "xmin": 0.1, "ymax": 0.9, "xmax": 0.8},
                    "content": "Policy Section 1",
                    "extraction_method": "native_pymupdf",
                    "extractor_version": "1.0.0",
                    "confidence": None,
                    "validation_status": "valid",
                    "warnings": [],
                }
            ],
        }
        vdoc = validate_visual_document_payload(base_doc)
        assert isinstance(vdoc, VisualDocument)
        assert vdoc.elements[0].confidence is None

        bad_ver = dict(base_doc, schema_version="lore.visual/9.0")
        with pytest.raises(Exception):
            validate_visual_document_payload(bad_ver)

        bad_bbox = json.loads(json.dumps(base_doc))
        bad_bbox["elements"][0]["bounding_box"]["xmax"] = 1050.0
        with pytest.raises(Exception):
            validate_visual_document_payload(bad_bbox)

        bad_page = json.loads(json.dumps(base_doc))
        bad_page["elements"][0]["page_number"] = 0
        with pytest.raises(Exception):
            validate_visual_document_payload(bad_page)

    @pytest.mark.django_db
    def test_batch_routes_visual_and_lightweight_jobs_and_enforces_limit(self):
        org = Organization.objects.create(name="Batch Reg Org", slug=f"batch-reg-{uuid.uuid4().hex[:6]}")
        ws = Workspace.objects.create(organization=org, name="Batch Reg WS", slug=f"batch-ws-{uuid.uuid4().hex[:6]}")
        user = User.objects.create_user(username=f"batch_{uuid.uuid4().hex[:6]}", password="pw")

        with pytest.raises(Exception):
            IngestionBatchService.validate_batch_size(101)

        pdf_f = SimpleUploadedFile("report.pdf", _make_digital_table_pdf_bytes(), content_type="application/pdf")
        csv_f = SimpleUploadedFile("metrics.csv", b"col1,col2\n1,2\n", content_type="text/csv")

        with patch("apps.ingestion.batch.dispatch_pending_batch_jobs", return_value={"dispatched": 0}):
            res = IngestionBatchService.create_and_dispatch_batch(
                files=[pdf_f, csv_f],
                workspace=ws,
                user=user,
                eager=False,
            )

        batch = IngestionBatch.objects.get(id=res["batch"].id)
        assert batch.total_files == 2
        assert batch.visual_jobs_count == 1
        assert batch.lightweight_jobs_count == 1
        jobs = list(IngestionJob.objects.filter(batch=batch))
        assert {j.workload_class for j in jobs} == {"visual", "lightweight"}


# ===========================================================================
# 2. Core Pipeline & Enterprise Governance Regression Suite
# ===========================================================================

class TestCoreRegressionWithVisualPipeline:
    def test_bengali_repair_numerals_and_ocr_router_cleanup(self):
        assert bangla_to_arabic_digits("২০২৬-০৪-১২") == "2026-04-12"
        corrupted = "াআমর বংলা"
        repaired = repair_visual_bengali_document(corrupted)
        assert isinstance(repaired, str)
        assert len(repaired) > 0
        assert isinstance(is_visual_encoded_document("Regular English text"), bool)

        stub = _StubOCRProvider(text="Bengali and English OCR Policy", confidence=0.92)
        router = OCRRouter(ocr_provider=stub)
        png_bytes = _make_png_bytes(320, 180)
        pages = router.process_image(png_bytes)
        assert len(pages) == 1
        assert pages[0]["engine"] == "tesseract_stub"
        assert pages[0]["confidence"] == pytest.approx(0.92)
        assert stub.calls == 1

    def test_office_formats_and_native_scanned_pdf_extraction(self):
        docx_ext = WorkerExtractorRegistry.get_extractor_for_document(doc_type="docx", filename="policy.docx")
        docx_pages = docx_ext.extract_document(_make_docx_bytes("Enterprise retention policy"), doc_type="docx", filename="policy.docx")
        assert any("Enterprise retention policy" in p.get("text", "") for p in docx_pages)

        xlsx_ext = WorkerExtractorRegistry.get_extractor_for_document(doc_type="xlsx", filename="budget.xlsx")
        xlsx_pages = xlsx_ext.extract_document(_make_xlsx_bytes("Budget", "CAPEX-100"), doc_type="xlsx", filename="budget.xlsx")
        assert any("CAPEX-100" in p.get("text", "") for p in xlsx_pages)

        pptx_pages = PresentationExtractor.extract(_make_minimal_pptx_bytes("Zero Trust Architecture"))
        assert any("Zero Trust Architecture" in p.get("text", "") for p in pptx_pages)

        pdf_ext = WorkerExtractorRegistry.get_extractor_for_document(doc_type="pdf", filename="table.pdf")
        native_pdf_pages = pdf_ext.extract_document(_make_digital_table_pdf_bytes(), doc_type="pdf", filename="table.pdf")
        assert native_pdf_pages[0]["page_number"] == 1
        assert "$1,250.50" in native_pdf_pages[0]["text"]
        assert native_pdf_pages[0].get("visual_metadata") is not None

        scanned_pages = PyMuPDFVisualPDFAdapter(ocr_provider=_StubOCRProvider("Scanned PDF Clause 9", 0.9)).process_pdf(
            _make_scanned_pdf_bytes(1),
        )
        assert len(scanned_pages) == 1
        assert "Scanned PDF Clause 9" in scanned_pages[0]["text"]

    @pytest.mark.django_db
    def test_settlement_versioning_permissions_retrieval_and_mcp_compatibility(self):
        org = Organization.objects.create(name="E2E Reg Org", slug=f"e2e-reg-{uuid.uuid4().hex[:6]}")
        ws = Workspace.objects.create(organization=org, name="E2E Reg WS", slug=f"e2e-ws-{uuid.uuid4().hex[:6]}")
        admin = User.objects.create_user(username=f"e2e_{uuid.uuid4().hex[:6]}", password="pw")

        pdf_bytes = _make_digital_table_pdf_bytes()
        doc = SourceDocument.objects.create(
            organization=org,
            workspace=ws,
            owner=admin,
            title="Travel Expense Schedule",
            original_filename="travel_schedule.pdf",
            document_type="pdf",
            authority_level=5,
            status="pending",
            file_hash="abc123",
            file_size=len(pdf_bytes),
            file_obj=SimpleUploadedFile("travel_schedule.pdf", pdf_bytes, content_type="application/pdf"),
        )
        v1 = DocumentVersion.objects.create(
            document=doc, version_number=1, file_hash="abc123", is_current=True,
            file_obj=SimpleUploadedFile("v1.pdf", pdf_bytes, content_type="application/pdf"),
        )

        patches = _mock_qdrant_success_for_doc(str(doc.id))
        with patches[0], patches[1], patches[2]:
            result = SettlementGateCoordinator.execute_settlement(doc=doc, doc_version=v1)

        assert result.get("status") in ("ready", "passed"), f"Settlement failed: {result}"
        doc.refresh_from_db()
        assert doc.status == "ready"

        v2 = DocumentVersion.objects.create(
            document=doc, version_number=2, file_hash="def456", is_current=False,
            file_obj=SimpleUploadedFile("v2.pdf", pdf_bytes, content_type="application/pdf"),
        )
        assert DocumentVersion.objects.filter(document=doc).count() == 2
        assert v2.version_number == 2

        # MCP compatibility: lore.get_document & lore.search while document is internal
        doc_res = json.loads(mcp_server.execute_tool("lore.get_document", {"document_id": str(doc.id), "workspace_id": str(ws.id)}))
        assert doc_res["schema"] == "lore.document/1"
        assert doc_res["document_id"] == str(doc.id)

        search_res = json.loads(
            mcp_server.execute_tool(
                "lore.search",
                {"query": "Travel USD", "workspace_id": str(ws.id), "organization_id": str(org.id), "output_format": "json"},
            )
        )
        assert search_res["schema"] == "lore.search_results/1"
        assert search_res["total_passages"] >= 1

        # L7 Permission enforcement on restricted document + retrieval filter
        SourcePermission.objects.create(
            document=doc,
            access_level=AccessLevel.RESTRICTED,
            allowed_roles=["compliance_auditor"],
        )
        assert PermissionLayer.can_access_document(doc, user_role="compliance_auditor") is True
        assert PermissionLayer.can_access_document(doc, user_role="guest") is False

        retriever = HybridRetrievalService()
        hits = retriever.search(
            query="Travel USD",
            workspace_id=str(ws.id),
            organization_id=str(org.id),
            limit=5,
            user_role="compliance_auditor",
        )
        assert any(str(doc.id) == str(h.get("document_id")) for h in hits)

        guest_hits = retriever.search(
            query="Travel USD",
            workspace_id=str(ws.id),
            organization_id=str(org.id),
            limit=5,
            user_role="guest",
        )
        assert guest_hits == []


# ===========================================================================
# 3. Security, Resource Limits, Isolation & Log Hygiene Suite
# ===========================================================================

class TestVisualSecurityHardening:
    def test_file_signature_and_size_validation(self):
        with pytest.raises(ValidationError):
            StorageSecurityService.inspect_and_validate(
                SimpleUploadedFile("bad.png", b"\x89PNGNOT_REAL_PNG_BODY", content_type="image/png")
            )
        ok_png = StorageSecurityService.inspect_and_validate(
            SimpleUploadedFile("ok.png", _make_png_bytes(50, 50), content_type="image/png")
        )
        assert ok_png["document_type"] == "image"

        with pytest.raises(ValidationError):
            StorageSecurityService.inspect_and_validate(
                SimpleUploadedFile("bad.jpg", b"\xFF\xD8\x00spoofed", content_type="image/jpeg")
            )

        with pytest.raises(ValidationError):
            StorageSecurityService.inspect_and_validate(
                SimpleUploadedFile("fake.pdf", b"<html><script>alert(1)</script></html>", content_type="application/pdf")
            )
        with pytest.raises(ValidationError):
            StorageSecurityService.inspect_and_validate(
                SimpleUploadedFile("fake.docx", b"NOT_A_PK_ZIP", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            )

        with pytest.raises(ValidationError):
            StorageSecurityService.inspect_and_validate(SimpleUploadedFile("empty.txt", b""))

        oversized = SimpleUploadedFile("huge.pdf", b"%PDF-1.4\n", content_type="application/pdf")
        oversized.size = 51 * 1024 * 1024
        with pytest.raises(ValidationError):
            StorageSecurityService.inspect_and_validate(oversized)

    def test_untrusted_macros_scripts_xxe_and_pdf_js_blocked_never_executed(self):
        macro_pptx = _make_minimal_pptx_bytes("Macro Slide", include_vba=True)
        with pytest.raises(ValidationError, match="macro|executable"):
            StorageSecurityService.inspect_and_validate(
                SimpleUploadedFile("macro.pptx", macro_pptx, content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
            )

        xxe_pptx = _make_minimal_pptx_bytes(xml_doctype=True)
        with pytest.raises(ValidationError, match="DOCTYPE|ENTITY"):
            StorageSecurityService.inspect_and_validate(
                SimpleUploadedFile("xxe.pptx", xxe_pptx, content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
            )
        extracted_xxe = PresentationExtractor.extract(xxe_pptx)
        assert all("/etc/passwd" not in p.get("text", "") for p in extracted_xxe)

        js_pdf = b"%PDF-1.7\n1 0 obj << /Type /Catalog /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >> endobj\n%%EOF"
        with pytest.raises(ValidationError, match="JavaScript|Launch"):
            StorageSecurityService.inspect_and_validate(
                SimpleUploadedFile("malicious.pdf", js_pdf, content_type="application/pdf")
            )

        html_payload = b"<html><body><script>throw new Error('XSS_EXECUTED')</script><p>Safe policy clause.</p></body></html>"
        unified = UnifiedDocumentExtractor()
        html_pages = unified.extract_document(html_payload, doc_type="html", filename="notice.html")
        joined = " ".join(p.get("text", "") for p in html_pages)
        assert "Safe policy clause" in joined
        assert "<script>" not in joined

    def test_zip_bomb_pdf_page_limit_and_pixel_limit_enforced(self):
        bomb_data = b"A" * (12 * 1024 * 1024)
        bomb_buf = io.BytesIO()
        with zipfile.ZipFile(bomb_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("xl/sheet1.xml", bomb_data)
        with pytest.raises(ValidationError, match="decompression ratio|uncompressed"):
            StorageSecurityService.inspect_and_validate(
                SimpleUploadedFile("bomb.xlsx", bomb_buf.getvalue())
            )

        pdf_6p = _make_scanned_pdf_bytes(page_count=6)
        limits = PDFSafetyLimits(max_pages=3)
        adapter = PyMuPDFVisualPDFAdapter(ocr_provider=_StubOCRProvider("Page ok", 0.9), limits=limits)
        pages = adapter.process_pdf(pdf_6p)
        assert len(pages) == 3
        assert any("limit" in str(w).lower() or "trunc" in str(w).lower() or "max" in str(w).lower() for p in pages for w in p.get("warnings", []))

        huge_png = _make_png_bytes(4000, 4000)
        router = OCRRouter(ocr_provider=_StubOCRProvider("Should not run", 0.9))
        with pytest.raises(ValueError, match="pixel count"):
            router.process_image(huge_png)

    def test_zero_temporary_file_leakage_on_pdf_visual_extraction(self):
        tmp_dir = tempfile.gettempdir()
        before = set(os.listdir(tmp_dir))

        pdf_bytes = _make_scanned_pdf_bytes(page_count=2)
        adapter = PyMuPDFVisualPDFAdapter(ocr_provider=_StubOCRProvider("Clean cleanup page", 0.91))
        pages = adapter.process_pdf(pdf_bytes)
        assert len(pages) == 2

        after = set(os.listdir(tmp_dir))
        leaked = {
            f for f in (after - before)
            if f.endswith((".pdf", ".png", ".jpg", ".tiff", ".tmp")) or "lore" in f.lower()
        }
        assert leaked == set(), f"Temporary files leaked during PDF visual extraction: {leaked}"

    @pytest.mark.django_db
    def test_tenant_and_workspace_isolation_across_retrieval_and_mcp(self):
        org_a = Organization.objects.create(name="Tenant Alpha", slug=f"alpha-{uuid.uuid4().hex[:6]}")
        ws_a = Workspace.objects.create(organization=org_a, name="WS Alpha", slug=f"ws-a-{uuid.uuid4().hex[:6]}")
        org_b = Organization.objects.create(name="Tenant Beta", slug=f"beta-{uuid.uuid4().hex[:6]}")
        ws_b = Workspace.objects.create(organization=org_b, name="WS Beta", slug=f"ws-b-{uuid.uuid4().hex[:6]}")
        user_a = User.objects.create_user(username=f"ua_{uuid.uuid4().hex[:6]}", password="pw")

        doc_a = SourceDocument.objects.create(
            organization=org_a,
            workspace=ws_a,
            owner=user_a,
            title="Alpha Merger Directive",
            original_filename="alpha_merger.pdf",
            document_type="pdf",
            authority_level=6,
            status="pending",
            file_hash="hash_alpha",
            file_size=128,
            file_obj=SimpleUploadedFile("alpha.pdf", _make_digital_table_pdf_bytes()),
        )
        ver_a = DocumentVersion.objects.create(
            document=doc_a, version_number=1, file_hash="hash_alpha", is_current=True,
            file_obj=SimpleUploadedFile("alpha_v1.pdf", _make_digital_table_pdf_bytes()),
        )

        patches = _mock_qdrant_success_for_doc(str(doc_a.id))
        with patches[0], patches[1], patches[2]:
            res = SettlementGateCoordinator.execute_settlement(doc=doc_a, doc_version=ver_a)
        assert res.get("status") in ("ready", "passed"), f"Settlement failed: {res}"

        retriever = HybridRetrievalService()
        beta_hits = retriever.search(
            query="Travel USD",
            workspace_id=str(ws_b.id),
            organization_id=str(org_b.id),
            limit=10,
        )
        assert beta_hits == []

        mcp_search_b = json.loads(
            mcp_server.execute_tool(
                "lore.search",
                {"query": "Travel USD", "workspace_id": str(ws_b.id), "organization_id": str(org_b.id), "output_format": "json"},
            )
        )
        assert mcp_search_b["total_passages"] == 0

        mcp_get_b = json.loads(
            mcp_server.execute_tool(
                "lore.get_document",
                {"document_id": str(doc_a.id), "workspace_id": str(ws_b.id), "organization_id": str(org_b.id)},
            )
        )
        assert mcp_get_b.get("schema") == "lore.error/1"

    @pytest.mark.django_db
    def test_sensitive_extracted_content_not_logged(self, caplog):
        sentinel_secret = "CONFIDENTIAL_SALARY_MARKER_847291"
        sentinel_token = "sk-live-supersecret9876543210tokenvalue"

        pdf_doc = fitz.open()
        page = pdf_doc.new_page(width=612, height=792)
        page.insert_text((72, 120), f"Payroll Record: {sentinel_secret}", fontsize=12)
        page.insert_text((72, 150), f"API Credential: {sentinel_token}", fontsize=12)
        secret_pdf_bytes = pdf_doc.tobytes()
        pdf_doc.close()

        org = Organization.objects.create(name="Log Hygiene Org", slug=f"log-hyg-{uuid.uuid4().hex[:6]}")
        ws = Workspace.objects.create(organization=org, name="Log Hygiene WS", slug=f"log-ws-{uuid.uuid4().hex[:6]}")
        owner = User.objects.create_user(username=f"lh_{uuid.uuid4().hex[:6]}", password="pw")

        doc = SourceDocument.objects.create(
            organization=org,
            workspace=ws,
            owner=owner,
            title="Payroll Extract",
            original_filename="payroll.pdf",
            document_type="pdf",
            authority_level=5,
            status="pending",
            file_hash="hash_lh",
            file_size=len(secret_pdf_bytes),
            file_obj=SimpleUploadedFile("payroll.pdf", secret_pdf_bytes, content_type="application/pdf"),
        )
        ver = DocumentVersion.objects.create(
            document=doc, version_number=1, file_hash="hash_lh", is_current=True,
            file_obj=SimpleUploadedFile("payroll_v1.pdf", secret_pdf_bytes, content_type="application/pdf"),
        )

        patches = _mock_qdrant_success_for_doc(str(doc.id))
        with caplog.at_level(logging.DEBUG):
            with patches[0], patches[1], patches[2]:
                SettlementGateCoordinator.execute_settlement(doc=doc, doc_version=ver)

        emitted_logs = "\n".join(rec.getMessage() for rec in caplog.records)
        assert sentinel_secret not in emitted_logs, "Sensitive extracted document text leaked into logs!"
        assert sentinel_token not in emitted_logs, "Sensitive API key/token from document leaked into logs!"
