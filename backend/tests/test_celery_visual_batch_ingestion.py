import csv
import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from xml.sax.saxutils import escape

import docx
import fitz
import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from PIL import Image, ImageDraw
from rest_framework.test import APIClient

from apps.identity.models import Organization, OrganizationMembership
from apps.ingestion.batch import (
    IngestionBatchService,
    WorkloadConcurrencyGate,
    dispatch_pending_batch_jobs,
)
from apps.ingestion.models import IngestionBatch, IngestionJob
from apps.ingestion.pipeline.extractors import (
    DocxExtractor,
    PresentationExtractor,
    SpreadsheetExtractor,
    WorkerExtractorRegistry,
    classify_ingestion_workload,
    needs_visual_extraction,
)
from apps.ingestion.pipeline.ocr import BaseOCRProvider
from apps.ingestion.tasks import (
    TransientIngestionError,
    PermanentIngestionError,
    process_lightweight_document_job,
    process_visual_document_job,
    recover_stalled_ingestion_jobs_task,
)
from apps.knowledge.models import DocumentChunk
from apps.sources.models import DocumentPage, SourceDocument
from apps.subscriptions.models import Plan, Subscription
from apps.workspaces.models import Collection, Workspace, WorkspaceMembership


def _make_pdf_bytes(text_lines, filename="doc.pdf") -> SimpleUploadedFile:
    doc = fitz.open()
    for page_text in (text_lines if isinstance(text_lines, list) else [text_lines]):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 96), page_text, fontsize=12)
    raw = doc.tobytes()
    doc.close()
    return SimpleUploadedFile(filename, raw, content_type="application/pdf")


def _make_png_bytes(text="Visual Batch OCR Evidence", filename="scan.png") -> SimpleUploadedFile:
    img = Image.new("RGB", (600, 220), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 580, 200], outline=(0, 0, 0), width=3)
    draw.text((40, 80), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return SimpleUploadedFile(filename, buf.getvalue(), content_type="image/png")


def _make_docx_bytes(text, filename="policy.docx") -> SimpleUploadedFile:
    d = docx.Document()
    d.add_heading("Enterprise Policy", level=1)
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return SimpleUploadedFile(
        filename,
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def _make_xlsx_bytes(rows, filename="sheet.xlsx") -> SimpleUploadedFile:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(
        filename,
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _make_pptx_bytes(title, body, filename="deck.pptx") -> SimpleUploadedFile:
    buf = io.BytesIO()
    slide_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        "<p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id=\"2\" name=\"Title\"/><p:cNvSpPr/>"
        '<p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:spPr/>'
        f"<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{escape(title)}</a:t></a:r></a:p>"
        f"<a:p><a:r><a:t>{escape(body)}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/slides/slide1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        "</Types>"
    )
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("ppt/slides/slide1.xml", slide_xml)
    return SimpleUploadedFile(
        filename,
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


def _make_csv_bytes(rows, filename="data.csv") -> SimpleUploadedFile:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow(row)
    return SimpleUploadedFile(filename, buf.getvalue().encode("utf-8"), content_type="text/csv")


class _FastDeterministicOCR(BaseOCRProvider):
    def get_engine_info(self):
        return {"name": "tesseract-mock", "version": "5.3.0"}

    def extract_image(self, image, languages=None):
        w, h = getattr(image, "size", (600, 220))
        return {
            "text": "Enterprise scanned visual document invoice total 12500 BDT approved policy compliance verified.",
            "confidence": 0.94,
            "words_count": 11,
            "width": float(w),
            "height": float(h),
            "engine": "tesseract",
            "engine_version": "5.3.0",
            "is_repaired": False,
            "status": "success",
            "needs_review": False,
            "bounding_boxes": [
                {"word": "Enterprise", "x": 10, "y": 10, "w": 60, "h": 18, "confidence": 0.94}
            ],
        }


def _build_mock_vstore() -> MagicMock:
    m = MagicMock()
    m.verify_document_indexed.return_value = True
    m.smoke_test_retrieval.return_value = True
    m.count_document_chunks.return_value = 1
    m.search.return_value = [{"id": "smoke-hit", "score": 0.99, "payload": {"text": "verified"}}]
    return m


@pytest.mark.django_db
class TestCeleryVisualBatchIngestion:
    def setup_method(self):
        WorkerExtractorRegistry.clear()
        WorkloadConcurrencyGate.reset_stats()

        self.client: Any = APIClient()
        self.user = User.objects.create_user(
            username="batch_admin",
            password="Password123!",
            email="batch_admin@lore.ai",
        )
        self.client.force_authenticate(user=self.user)

        self.org = Organization.objects.create(name="Batch Corp", slug="batch-corp")
        OrganizationMembership.objects.create(organization=self.org, user=self.user, role="owner")

        self.ws = Workspace.objects.create(organization=self.org, name="Primary WS", slug="primary-ws")
        WorkspaceMembership.objects.create(workspace=self.ws, user=self.user, role="workspace_admin")
        self.collection = Collection.objects.create(workspace=self.ws, name="Mixed Docs")

        # Second workspace & second organization for isolation tests
        self.ws_other = Workspace.objects.create(organization=self.org, name="Secondary WS", slug="secondary-ws")
        WorkspaceMembership.objects.create(workspace=self.ws_other, user=self.user, role="workspace_admin")

        self.other_user = User.objects.create_user(
            username="tenant_b_user",
            password="Password123!",
            email="tenant_b@lore.ai",
        )
        self.org_b = Organization.objects.create(name="Tenant B Corp", slug="tenant-b-corp")
        OrganizationMembership.objects.create(organization=self.org_b, user=self.other_user, role="owner")
        self.ws_b = Workspace.objects.create(organization=self.org_b, name="Tenant B WS", slug="tenant-b-ws")
        WorkspaceMembership.objects.create(workspace=self.ws_b, user=self.other_user, role="workspace_admin")

    def test_workload_classification_and_native_vs_visual_routing(self):
        assert classify_ingestion_workload("pdf", "report.pdf") == "visual"
        assert classify_ingestion_workload("image", "scan.png") == "visual"
        assert classify_ingestion_workload("image", "photo.webp") == "visual"
        assert classify_ingestion_workload("docx", "contract.docx") == "lightweight"
        assert classify_ingestion_workload("spreadsheet", "ledger.xlsx") == "lightweight"
        assert classify_ingestion_workload("spreadsheet", "ledger.csv") == "lightweight"
        assert classify_ingestion_workload("presentation", "slides.pptx") == "lightweight"

        assert needs_visual_extraction("pdf", "report.pdf")[0] is True
        assert needs_visual_extraction("image", "scan.tiff")[0] is True
        assert needs_visual_extraction("docx", "contract.docx") == (False, "native_office_or_text_parser")
        assert needs_visual_extraction("spreadsheet", "ledger.xlsx") == (False, "native_office_or_text_parser")
        assert needs_visual_extraction("presentation", "slides.pptx") == (False, "native_office_or_text_parser")
        assert needs_visual_extraction("spreadsheet", "data.csv") == (False, "native_office_or_text_parser")

        # Worker extractor cache initializes once per profile per worker process
        vis1 = WorkerExtractorRegistry.get_visual_extractor()
        vis2 = WorkerExtractorRegistry.get_visual_extractor()
        light1 = WorkerExtractorRegistry.get_lightweight_extractor()
        light2 = WorkerExtractorRegistry.get_lightweight_extractor()
        assert vis1 is vis2
        assert light1 is light2
        assert vis1.pdf_visual_adapter is not None
        assert light1.pdf_visual_adapter is None
        stats = WorkerExtractorRegistry.get_stats()
        assert stats["init_counts"]["visual"] == 1
        assert stats["init_counts"]["lightweight"] == 1

    def test_100_mixed_files_batch_routing_worker_reuse_and_native_parsers(self):
        enterprise_plan, _ = Plan.objects.get_or_create(
            slug="enterprise-batch-test",
            defaults={
                "name": "Enterprise Tier",
                "description": "High-volume batch ingestion plan",
                "price_monthly": 0.00,
                "max_storage_mb": 2048,
                "max_documents": 500,
                "max_monthly_queries": 10000,
                "max_workspaces": 10,
                "max_members": 25,
                "allow_custom_models": True,
                "allow_ocr_bengali": True,
                "allow_audit_export": True,
            },
        )
        Subscription.objects.update_or_create(
            organization=self.org,
            defaults={"plan": enterprise_plan, "status": "active"},
        )

        # Mix of 100 unique valid files:
        # 20 PDFs (visual), 10 PNGs (visual), 20 DOCX, 20 XLSX, 15 PPTX, 15 CSV (70 lightweight)
        files = []
        for i in range(20):
            files.append(
                _make_pdf_bytes(
                    f"Enterprise Governance PDF Record #{i}: Detailed compliance statement and verified metrics {i * 17}.",
                    filename=f"doc_{i:03d}.pdf",
                )
            )
        for i in range(10):
            files.append(
                _make_png_bytes(
                    text=f"Image Scan #{i} Authorized Fiscal Invoice",
                    filename=f"img_{i:03d}.png",
                )
            )
        for i in range(20):
            files.append(
                _make_docx_bytes(
                    f"DOCX Procedure #{i}: Standard enterprise retention and audit trail clause number {i + 100}.",
                    filename=f"word_{i:03d}.docx",
                )
            )
        for i in range(20):
            files.append(
                _make_xlsx_bytes(
                    [["Account", "Department", "Amount"], [f"ACC-{i}", "Engineering", 1000 + i]],
                    filename=f"sheet_{i:03d}.xlsx",
                )
            )
        for i in range(15):
            files.append(
                _make_pptx_bytes(
                    f"Quarterly Architecture Review #{i}",
                    f"Slide content covering reliability milestone {i} and zero data loss.",
                    filename=f"deck_{i:03d}.pptx",
                )
            )
        for i in range(15):
            files.append(
                _make_csv_bytes(
                    [["Metric", "Value", "Quarter"], [f"throughput_{i}", f"{95 + i}", "Q4"]],
                    filename=f"table_{i:03d}.csv",
                )
            )
        assert len(files) == 100

        # Ensure images use fast deterministic OCR while Office parsers run natively and fast vector/embedder is mocked
        mock_vstore = _build_mock_vstore()
        fast_vis_extractor = WorkerExtractorRegistry.get_visual_extractor()
        fast_vis_extractor.router.ocr_provider = _FastDeterministicOCR()
        assert fast_vis_extractor.pdf_visual_adapter is not None
        fast_vis_extractor.pdf_visual_adapter.ocr_provider = _FastDeterministicOCR()
        fast_vis_extractor.pdf_visual_adapter.fallback_router.ocr_provider = _FastDeterministicOCR()

        with patch("apps.ingestion.settlement.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.coordinator.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.quality.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.batch.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.pipeline.extractors.DocxExtractor.extract", wraps=DocxExtractor.extract) as spy_p_docx, \
             patch("apps.ingestion.pipeline.extractors.SpreadsheetExtractor.extract_xlsx", wraps=SpreadsheetExtractor.extract_xlsx) as spy_xlsx, \
             patch("apps.ingestion.pipeline.extractors.SpreadsheetExtractor.extract_csv", wraps=SpreadsheetExtractor.extract_csv) as spy_csv, \
             patch("apps.ingestion.pipeline.extractors.PresentationExtractor.extract", wraps=PresentationExtractor.extract) as spy_pptx:
            res = self.client.post(
                "/api/v1/sources/documents/bulk-upload/",
                {"workspace": str(self.ws.id), "files": files},
                format="multipart",
            )

        assert res.status_code == 201, res.data
        assert res.data["total_count"] == 100
        assert res.data["success_count"] == 100
        assert res.data["failed_count"] == 0
        assert res.data["visual_jobs_count"] == 30
        assert res.data["lightweight_jobs_count"] == 70

        batch = IngestionBatch.objects.get(id=res.data["batch_id"])
        assert batch.status == "completed"
        assert batch.completed_count == 100
        assert batch.visual_jobs_count == 30
        assert batch.lightweight_jobs_count == 70

        # Confirm native Office parsers handled DOCX/XLSX/CSV/PPTX without routing through visual OCR
        assert spy_p_docx.call_count == 20
        assert spy_xlsx.call_count == 20
        assert spy_csv.call_count == 15
        assert spy_pptx.call_count == 15

        # Confirm visual model extractor initialized ONCE per worker despite 30 visual documents
        stats = WorkerExtractorRegistry.get_stats()
        assert stats["init_counts"]["visual"] == 1

        # Confirm queueing over 100 files is rejected cleanly
        over_limit = [_make_csv_bytes([["a"], [str(i)]], filename=f"x_{i}.csv") for i in range(101)]
        bad_res = self.client.post(
            "/api/v1/sources/documents/bulk-upload/",
            {"workspace": str(self.ws.id), "files": over_limit},
            format="multipart",
        )
        assert bad_res.status_code == 400
        assert "100" in str(bad_res.data["error"])

    @override_settings(
        CELERY_TASK_ALWAYS_EAGER=False,
        INGESTION_VISUAL_MAX_CONCURRENCY=2,
        INGESTION_LIGHTWEIGHT_MAX_CONCURRENCY=4,
    )
    def test_separate_celery_queues_and_controlled_concurrency_limits(self):
        # 5 PDFs (visual limit=2) and 7 CSVs (lightweight limit=4)
        files = [
            _make_pdf_bytes(f"Queued visual PDF #{i} with enough substance for testing.", filename=f"vis_{i}.pdf")
            for i in range(5)
        ] + [
            _make_csv_bytes([["col"], [f"lightweight_row_content_{i}_sufficient_text"]], filename=f"lt_{i}.csv")
            for i in range(7)
        ]

        dispatched_calls = []

        def fake_visual_apply(args=None, queue=None, **kwargs):
            assert args is not None
            dispatched_calls.append(("visual", args[0], queue))
            m = MagicMock()
            m.id = f"vis-task-{args[0]}"
            return m

        def fake_light_apply(args=None, queue=None, **kwargs):
            assert args is not None
            dispatched_calls.append(("lightweight", args[0], queue))
            m = MagicMock()
            m.id = f"light-task-{args[0]}"
            return m

        with patch.object(process_visual_document_job, "apply_async", side_effect=fake_visual_apply), \
             patch.object(process_lightweight_document_job, "apply_async", side_effect=fake_light_apply):
            res = self.client.post(
                "/api/v1/sources/documents/bulk-upload/",
                {"workspace": str(self.ws.id), "files": files},
                format="multipart",
            )

        assert res.status_code == 201
        visual_dispatched = [c for c in dispatched_calls if c[0] == "visual"]
        light_dispatched = [c for c in dispatched_calls if c[0] == "lightweight"]

        # Controlled initial dispatch: capped at separate heavy vs lightweight ceilings
        assert len(visual_dispatched) == 2
        assert len(light_dispatched) == 4
        assert all(q == "ingestion_visual" for _, _, q in visual_dispatched)
        assert all(q == "ingestion_light" for _, _, q in light_dispatched)

        # Now verify WorkloadConcurrencyGate enforces runtime ceilings concurrently
        WorkloadConcurrencyGate.reset_stats()

        def run_gate(wcls):
            with WorkloadConcurrencyGate.acquire(wcls):
                time.sleep(0.03)

        with ThreadPoolExecutor(max_workers=12) as pool:
            futs = [pool.submit(run_gate, "visual") for _ in range(6)] + [
                pool.submit(run_gate, "lightweight") for _ in range(10)
            ]
            for f in futs:
                f.result()

        gate_stats = WorkloadConcurrencyGate.stats()
        assert gate_stats["peak"]["visual"] <= 2
        assert gate_stats["peak"]["lightweight"] <= 4
        assert gate_stats["active"]["visual"] == 0
        assert gate_stats["active"]["lightweight"] == 0

    def test_duplicate_files_idempotency_and_org_workspace_isolation(self):
        pdf_a = _make_pdf_bytes(
            "Shared confidential handbook text with identical hash and enough substance.",
            filename="handbook_copy1.pdf",
        )
        pdf_dup_same_name_content = _make_pdf_bytes(
            "Shared confidential handbook text with identical hash and enough substance.",
            filename="handbook_copy2.pdf",
        )
        # Re-read identical bytes for exact hash match
        raw_bytes = pdf_a.read()
        pdf_a.seek(0)
        f1 = SimpleUploadedFile("copy1.pdf", raw_bytes, content_type="application/pdf")
        f2 = SimpleUploadedFile("copy2.pdf", raw_bytes, content_type="application/pdf")

        mock_vstore = _build_mock_vstore()

        with patch("apps.ingestion.settlement.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.coordinator.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.quality.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.batch.QdrantVectorStore", return_value=mock_vstore):
            res1 = self.client.post(
                "/api/v1/sources/documents/bulk-upload/",
                {"workspace": str(self.ws.id), "files": [f1, f2]},
                format="multipart",
            )
            assert res1.status_code == 201
            assert res1.data["skipped_duplicate_count"] == 1
            assert SourceDocument.objects.filter(workspace=self.ws).count() == 1

            # Re-uploading same bytes into the SAME workspace is idempotent (no duplicate doc/chunks)
            f3 = SimpleUploadedFile("copy3.pdf", raw_bytes, content_type="application/pdf")
            res2 = self.client.post(
                "/api/v1/sources/documents/bulk-upload/",
                {"workspace": str(self.ws.id), "files": [f3]},
                format="multipart",
            )
            assert res2.status_code == 201
            assert res2.data["skipped_duplicate_count"] == 1
            assert SourceDocument.objects.filter(workspace=self.ws).count() == 1

            # Uploading same bytes into ANOTHER workspace is isolated (creates its own workspace doc)
            f4 = SimpleUploadedFile("copy4.pdf", raw_bytes, content_type="application/pdf")
            res_ws2 = self.client.post(
                "/api/v1/sources/documents/bulk-upload/",
                {"workspace": str(self.ws_other.id), "files": [f4]},
                format="multipart",
            )
            assert res_ws2.status_code == 201
            assert res_ws2.data["skipped_duplicate_count"] == 0
            assert SourceDocument.objects.filter(workspace=self.ws_other).count() == 1

            # Cross-organization isolation on API endpoints (Tenant B cannot view or cancel Org A batch)
            client_b: Any = APIClient()
            client_b.force_authenticate(user=self.other_user)
            f5 = SimpleUploadedFile("copy5.pdf", raw_bytes, content_type="application/pdf")
            res_b = client_b.post(
                "/api/v1/sources/documents/bulk-upload/",
                {"workspace": str(self.ws_b.id), "files": [f5]},
                format="multipart",
            )
            assert res_b.status_code == 201
            assert SourceDocument.objects.filter(organization=self.org_b).count() == 1

            cross_get = client_b.get(f"/api/v1/ingestion/batches/{res1.data['batch_id']}/")
            assert cross_get.status_code == 404
            cross_cancel = client_b.post(f"/api/v1/ingestion/batches/{res1.data['batch_id']}/cancel/")
            assert cross_cancel.status_code == 404
            cross_rec = client_b.post(
                "/api/v1/ingestion/jobs/recover-stalled/",
                {"workspace_id": str(self.ws.id)},
                format="json",
            )
            assert cross_rec.status_code == 404

    def test_corrupted_pdfs_and_partial_failures_isolate_cleanly(self):
        good_pdf = _make_pdf_bytes(
            "Valid Compliance Policy: Every transaction is logged cleanly and settled with provenance.",
            filename="valid.pdf",
        )
        good_csv = _make_csv_bytes(
            [["control", "status", "detail"], ["SOC2-CC6", "active", "verified encryption control"]],
            filename="valid.csv",
        )
        corrupt_body_pdf = SimpleUploadedFile(
            "corrupt_body.pdf",
            b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Truncated CORRUPT STREAM \x00\xff\xfe",
            content_type="application/pdf",
        )
        bad_magic_pdf = SimpleUploadedFile(
            "not_actually_pdf.pdf",
            b"NOT_A_PDF_HEADER_AT_ALL_123456",
            content_type="application/pdf",
        )
        empty_file = SimpleUploadedFile("empty.pdf", b"", content_type="application/pdf")

        mock_vstore = _build_mock_vstore()

        with patch("apps.ingestion.settlement.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.coordinator.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.quality.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.batch.QdrantVectorStore", return_value=mock_vstore):
            res = self.client.post(
                "/api/v1/sources/documents/bulk-upload/",
                {
                    "workspace": str(self.ws.id),
                    "files": [good_pdf, good_csv, corrupt_body_pdf, bad_magic_pdf, empty_file],
                },
                format="multipart",
            )

        assert res.status_code == 201
        assert res.data["status"] == "partial_success"
        # bad_magic_pdf and empty_file fail pre-validation cleanly
        assert res.data["failed_count"] == 2
        assert res.data["success_count"] == 3

        # Valid docs reached ready
        assert SourceDocument.objects.get(original_filename="valid.pdf").status == "ready"
        assert SourceDocument.objects.get(original_filename="valid.csv").status == "ready"

        # Corrupted PDF body isolated at Stage 3 -> failed, zero published chunks
        corrupt_doc = SourceDocument.objects.get(original_filename="corrupt_body.pdf")
        assert corrupt_doc.status == "failed"
        assert DocumentChunk.objects.filter(document=corrupt_doc).count() == 0

        batch = IngestionBatch.objects.get(id=res.data["batch_id"])
        assert batch.status == "partial_success"
        assert batch.completed_count == 2
        assert batch.failed_count == 3  # 2 validation failures + 1 pipeline failure

    def test_partially_extracted_document_never_publishes_as_ready(self):
        doc_file = _make_pdf_bytes(
            ["Page 1 valid enterprise compliance policy text.", "Page 2 simulated error target."],
            filename="partial_fail.pdf",
        )
        partial_pages = [
            {
                "page_number": 1,
                "text": "Page 1 valid enterprise compliance policy text with sufficient content.",
                "confidence": 0.96,
                "words_count": 10,
                "width": 595.0,
                "height": 842.0,
                "extraction_type": "digital_pdf",
                "status": "extracted",
                "bounding_boxes": [],
            },
            {
                "page_number": 2,
                "text": "",
                "confidence": 0.0,
                "words_count": 0,
                "width": 595.0,
                "height": 842.0,
                "extraction_type": "pdf_malformed",
                "status": "page_error",
                "warnings": ["Page 2 extraction failed gracefully: simulated stream error"],
                "bounding_boxes": [],
            },
        ]

        mock_vstore = _build_mock_vstore()

        with patch("apps.ingestion.settlement.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.coordinator.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.quality.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.settlement.UnifiedDocumentExtractor.extract_document", return_value=partial_pages):
            res = self.client.post(
                "/api/v1/sources/documents/bulk-upload/",
                {"workspace": str(self.ws.id), "files": [doc_file]},
                format="multipart",
            )

        assert res.status_code == 201
        doc = SourceDocument.objects.get(original_filename="partial_fail.pdf")
        job = IngestionJob.objects.get(document=doc)
        assert doc.status != "ready"
        assert doc.status == "needs_review"
        assert job.status == "needs_review"

    def test_celery_retries_transient_vs_permanent_and_batch_retry_failed(self):
        pdf_file = _make_pdf_bytes("Retryable Visual PDF content with enough length.", filename="retry_me.pdf")
        doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title="Retry Target",
            original_filename="retry_me.pdf",
            mime_type="application/pdf",
            file_size=pdf_file.size,
            file_hash="a" * 64,
            file_obj=pdf_file,
            document_type="pdf",
            status="queued",
        )
        batch = IngestionBatch.objects.create(
            organization=self.org,
            workspace=self.ws,
            total_files=1,
            visual_jobs_count=1,
        )
        job = IngestionJob.objects.create(
            document=doc,
            organization=self.org,
            workspace=self.ws,
            batch=batch,
            workload_class="visual",
            queue_name="ingestion_visual",
            status="queued",
        )

        # Transient error triggers Celery self.retry and updates attempt_count
        retry_sentinel = RuntimeError("celery_retry_scheduled")
        with patch("apps.ingestion.tasks.process_ingestion_pipeline", side_effect=TransientIngestionError("timeout")), \
             patch.object(process_visual_document_job, "retry", side_effect=retry_sentinel) as mock_retry, \
             patch("apps.ingestion.batch.QdrantVectorStore", return_value=MagicMock()):
            with pytest.raises(RuntimeError, match="celery_retry_scheduled"):
                process_visual_document_job(str(job.id))

        assert mock_retry.called
        job.refresh_from_db()
        assert job.attempt_count == 2
        assert job.status == "queued"
        assert job.error_category == "TRANSIENT_RETRY"

        # Permanent error does NOT call self.retry and leaves doc non-ready
        with patch("apps.ingestion.tasks.process_ingestion_pipeline", side_effect=PermanentIngestionError("corrupt")), \
             patch.object(process_visual_document_job, "retry") as mock_perm_retry, \
             patch("apps.ingestion.batch.QdrantVectorStore", return_value=MagicMock()):
            with pytest.raises(PermanentIngestionError):
                process_visual_document_job(str(job.id))

        assert not mock_perm_retry.called

        # Mark failed & verify batch retry-failed endpoint recovers it cleanly
        job.status = "failed"
        job.save(update_fields=["status"])
        doc.status = "failed"
        doc.save(update_fields=["status"])

        mock_vstore = _build_mock_vstore()
        with patch("apps.ingestion.settlement.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.coordinator.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.quality.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.batch.QdrantVectorStore", return_value=mock_vstore):
            retry_res = self.client.post(f"/api/v1/ingestion/batches/{batch.id}/retry-failed/")

        assert retry_res.status_code == 200
        assert retry_res.data["retried_count"] == 1
        job.refresh_from_db()
        doc.refresh_from_db()
        assert job.status == "ready"
        assert doc.status == "ready"

    def test_cancellation_queued_and_midflight_prevents_partial_publication(self):
        pdf_file = _make_pdf_bytes("Cancellation test document content long enough.", filename="cancel_me.pdf")
        doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title="Cancel Target",
            original_filename="cancel_me.pdf",
            mime_type="application/pdf",
            file_size=pdf_file.size,
            file_hash="b" * 64,
            file_obj=pdf_file,
            document_type="pdf",
            status="queued",
        )
        batch = IngestionBatch.objects.create(
            organization=self.org,
            workspace=self.ws,
            total_files=1,
            visual_jobs_count=1,
        )
        job = IngestionJob.objects.create(
            document=doc,
            organization=self.org,
            workspace=self.ws,
            batch=batch,
            workload_class="visual",
            queue_name="ingestion_visual",
            status="queued",
        )

        # Simulate cooperative cancellation triggered right inside Run 1 execution
        mock_vstore = _build_mock_vstore()

        from apps.ingestion.coordinator import SequentialPipelineCoordinator
        orig_run1 = SequentialPipelineCoordinator._execute_run_1

        def cancelling_run1(j, d, dv):
            res = orig_run1(j, d, dv)
            IngestionJob.objects.filter(id=j.id).update(is_cancellation_requested=True)
            return res

        with patch("apps.ingestion.settlement.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.coordinator.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.batch.QdrantVectorStore", return_value=mock_vstore), \
             patch.object(SequentialPipelineCoordinator, "_execute_run_1", side_effect=cancelling_run1):
            SequentialPipelineCoordinator.orchestrate_pipeline(str(job.id), raise_exceptions=False)

        job.refresh_from_db()
        doc.refresh_from_db()
        batch.refresh_from_db()
        assert job.status == "cancelled"
        assert doc.status != "ready"
        assert DocumentChunk.objects.filter(document=doc).count() == 0
        assert mock_vstore.delete_document_chunks.called
        assert batch.status == "cancelled"

    def test_worker_restart_recovery_rolls_back_partial_state_and_completes(self):
        pdf_file = _make_pdf_bytes(
            "Worker Crash Recovery Document: Compliance policy section 4.2 verified.",
            filename="crashed_worker.pdf",
        )
        doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title="Crashed Worker Doc",
            original_filename="crashed_worker.pdf",
            mime_type="application/pdf",
            file_size=pdf_file.size,
            file_hash="c" * 64,
            file_obj=pdf_file,
            document_type="pdf",
            status="extracting",
        )
        batch = IngestionBatch.objects.create(
            organization=self.org,
            workspace=self.ws,
            status="processing",
            total_files=1,
            visual_jobs_count=1,
        )
        stale_time = timezone.now() - timedelta(seconds=600)
        job = IngestionJob.objects.create(
            document=doc,
            organization=self.org,
            workspace=self.ws,
            batch=batch,
            workload_class="visual",
            queue_name="ingestion_visual",
            status="extracting",
            current_stage="extraction",
            worker_id="dead-worker:9999",
            started_at=stale_time,
            heartbeat_at=stale_time,
            attempt_count=1,
            max_retries=3,
        )
        # Seed orphaned partial page + chunk left by dead worker before crash
        DocumentPage.objects.create(
            document=doc,
            page_number=1,
            text="partial incomplete text",
            confidence=0.40,
            extraction_type="scanned_ocr",
        )
        DocumentChunk.objects.create(
            document=doc,
            organization=self.org,
            workspace=self.ws,
            chunk_index=0,
            text="partial orphaned chunk",
            token_count=3,
            vector_id="00000000-0000-0000-0000-000000000001",
            content_hash="stale-hash",
        )

        mock_vstore = _build_mock_vstore()

        with patch("apps.ingestion.settlement.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.coordinator.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.quality.QdrantVectorStore", return_value=mock_vstore), \
             patch("apps.ingestion.batch.QdrantVectorStore", return_value=mock_vstore):
            rec_res = self.client.post(
                "/api/v1/ingestion/jobs/recover-stalled/",
                {"workspace_id": str(self.ws.id), "timeout_seconds": 60},
                format="json",
            )

        assert rec_res.status_code == 200
        assert rec_res.data["recovered_count"] == 1
        assert str(job.id) in rec_res.data["recovered_job_ids"]

        job.refresh_from_db()
        doc.refresh_from_db()
        batch.refresh_from_db()
        assert job.attempt_count == 2
        assert job.status == "ready"
        assert doc.status == "ready"
        assert batch.status == "completed"
        # Orphaned chunk was purged cleanly before final settlement (no "partial orphaned chunk" leaked)
        texts = list(DocumentChunk.objects.filter(document=doc).values_list("text", flat=True))
        assert texts
        assert all("partial orphaned chunk" not in t for t in texts)
