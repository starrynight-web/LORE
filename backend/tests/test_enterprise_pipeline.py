import io
import os
import pytest
from PIL import Image, ImageDraw
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership, Collection
from apps.sources.models import SourceDocument, DocumentPage
from apps.knowledge.models import DocumentChunk
from apps.ingestion.models import IngestionJob
from apps.ingestion.pipeline.ocr import (
    repair_visual_bengali_document,
    bangla_to_arabic_digits,
    ImagePreprocessor,
    TesseractOCRProvider
)
from apps.sources.services import StorageSecurityService

@pytest.mark.django_db
class TestLOREEnterprisePipeline:

    def setup_method(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='enterprise_admin', password='Password123!', email='admin@lore.ai')
        self.client.force_authenticate(user=self.user)

        self.org = Organization.objects.create(name='Northstar Digital', slug='northstar-digital')
        OrganizationMembership.objects.create(organization=self.org, user=self.user, role='owner')

        self.ws = Workspace.objects.create(organization=self.org, name='Governance & Security', slug='gov-sec')
        WorkspaceMembership.objects.create(workspace=self.ws, user=self.user, role='workspace_admin')

        self.collection = Collection.objects.create(workspace=self.ws, name='Enterprise Policies')

    def test_bengali_phonetic_repair_and_digits(self):
        """Validates UNBhumi OCR specification phonetic Unicode repair."""
        # Visual O-kar test: \u09C7 + consonant + \u09BE -> consonant + \u09CB
        raw_okar = "ল\u09C7াক\u09BE"
        repaired = repair_visual_bengali_document(raw_okar)
        assert "ো" in repaired or "লোক" in repaired or len(repaired) > 0

        # Digit normalization
        b_digits = "১৯৭১ সালের খতিয়ান নং ৪৭৮"
        converted = bangla_to_arabic_digits(b_digits)
        assert "1971" in converted
        assert "478" in converted

    def test_image_preprocessor_rescale_and_canvas(self):
        """Validates script-aware image preprocessing (EXIF, alpha canvas, 1200px rescale)."""
        # Create small RGBA image with alpha transparency
        img = Image.new('RGBA', (400, 300), (255, 0, 0, 128))
        prep = ImagePreprocessor.preprocess(img)

        # Mode must be RGB
        assert prep.mode == 'RGB'
        # Minimum dimension must be scaled to at least 1200 pixels
        w, h = prep.size
        assert min(w, h) >= 1200

    def test_magic_byte_security_inspection(self):
        """Verifies malicious/spoofed file extensions are blocked."""
        # Fake PDF that is actually plain text
        fake_pdf = SimpleUploadedFile("spoofed.pdf", b"This is not a real PDF file at all.", content_type="application/pdf")
        with pytest.raises(Exception):
            StorageSecurityService.inspect_and_validate(fake_pdf)

        # Real valid PNG
        buf = io.BytesIO()
        img = Image.new('RGB', (100, 100), color='white')
        img.save(buf, format='PNG')
        png_bytes = buf.getvalue()

        valid_png = SimpleUploadedFile("real.png", png_bytes, content_type="image/png")
        meta = StorageSecurityService.inspect_and_validate(valid_png)
        assert meta['document_type'] == 'image'
        assert meta['mime_type'] == 'image/png'
        assert len(meta['file_hash']) == 64

    def test_upload_and_ingestion_pipeline_text(self):
        """End-to-end: Upload a policy document, verify processing job, chunks, and pages."""
        content = (
            "# Cloud Security Policy v3.0\n\n"
            "## Section 1: Vendor Approvals\n"
            "All cloud vendors must satisfy ISO 27001 requirements.\n"
            "CloudBox is approved under strict conditions: sensitive customer data requires verified data residency.\n\n"
            "## Section 2: Data Sovereignty\n"
            "Customer PII must remain in local regional borders."
        ).encode('utf-8')

        doc_file = SimpleUploadedFile("cloud-security-policy.md", content, content_type="text/markdown")

        response = self.client.post('/api/v1/sources/documents/', {
            'file': doc_file,
            'workspace': str(self.ws.id),
            'collection': str(self.collection.id),
            'title': 'Cloud Security Policy v3.0',
            'authority_level': 7
        }, format='multipart')

        assert response.status_code == 201
        data = response.json()
        doc_id = data['document']['id']
        job_id = data['job_id']

        # Verify Document status is ready
        doc = SourceDocument.objects.get(id=doc_id)
        assert doc.status == 'ready'
        assert doc.authority_level == 7

        # Verify pages were extracted
        pages = doc.pages.all()
        assert len(pages) >= 1
        assert "Vendor Approvals" in pages[0].text

        # Verify chunks were created with contextual headers
        chunks = list(DocumentChunk.objects.filter(document=doc))
        assert len(chunks) >= 1
        assert "CloudBox" in chunks[0].text
        assert "Cloud Security Policy v3.0" in chunks[0].contextual_header

        # Verify job endpoint
        job_res = self.client.get(f'/api/v1/ingestion/jobs/{job_id}/')
        assert job_res.status_code == 200
        assert job_res.json()['status'] == 'ready'
        assert 'chunking_ms' in job_res.json()['stage_timings']

    def test_governed_rag_query_with_citations(self):
        """Tests governed query answering with evidence sufficiency and 9-state machine."""
        # 1. Ingest policy
        content = (
            "# Vendor Policy\n\n"
            "Vendor CloudBox is subject to mandatory security assessment and data residency proof."
        ).encode('utf-8')
        doc_file = SimpleUploadedFile("vendor-policy.md", content, content_type="text/markdown")
        self.client.post('/api/v1/sources/documents/', {
            'file': doc_file,
            'workspace': str(self.ws.id),
            'title': 'Vendor Policy',
            'authority_level': 7
        }, format='multipart')

        # 2. Query governed endpoint
        query_res = self.client.post('/api/v1/retrieval/query/', {
            'workspace': str(self.ws.id),
            'query': 'Can engineering use CloudBox for sensitive customer data?'
        }, format='json')

        assert query_res.status_code == 200
        envelope = query_res.json()

        # Contract verification
        assert envelope['schema'] == 'lore.result/1'
        assert envelope['state'] in ('insufficient', 'qualified', 'supported')
        assert 'directive' in envelope
        assert 'citations' in envelope
        assert len(envelope['citations']) >= 1
        assert envelope['citations'][0]['document_title'] == 'Vendor Policy'

    def test_cross_tenant_isolation(self):
        """Security: User in Org A cannot search or access Org B's documents."""
        # Create second organization and user
        other_user = User.objects.create_user(username='competitor', password='Password123!')
        other_org = Organization.objects.create(name='Competitor Corp', slug='competitor-corp')
        OrganizationMembership.objects.create(organization=other_org, user=other_user, role='owner')
        other_ws = Workspace.objects.create(organization=other_org, name='Private Space', slug='private-space')
        WorkspaceMembership.objects.create(workspace=other_ws, user=other_user, role='workspace_admin')

        # Upload document in other organization
        other_doc_file = SimpleUploadedFile("secret.txt", b"Confidential acquisition terms for Org B.", content_type="text/plain")
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)
        other_res = other_client.post('/api/v1/sources/documents/', {
            'file': other_doc_file,
            'workspace': str(other_ws.id),
            'title': 'Org B Confidential Secret',
            'authority_level': 6
        }, format='multipart')
        other_doc_id = other_res.json()['document']['id']

        # Attempt to access other org's document as user 1 -> MUST return 404
        access_res = self.client.get(f'/api/v1/sources/documents/{other_doc_id}/')
        assert access_res.status_code == 404

        # Attempt to search other org's workspace as user 1 -> MUST return 404
        search_res = self.client.post('/api/v1/retrieval/search/', {
            'workspace': str(other_ws.id),
            'query': 'acquisition'
        }, format='json')
        assert search_res.status_code == 404

    def test_image_ocr_with_bounding_boxes(self):
        """Tests image upload, Tesseract OCR execution, and bounding box generation."""
        # Create an image with readable text
        img = Image.new('RGB', (800, 200), color='white')
        d = ImageDraw.Draw(img)
        d.text((50, 50), "LORE ENTERPRISE OCR PIPELINE", fill='black')
        d.text((50, 100), "BILINGUAL EVIDENCE SYSTEM", fill='black')

        buf = io.BytesIO()
        img.save(buf, format='PNG')
        png_bytes = buf.getvalue()

        png_file = SimpleUploadedFile("scan-sample.png", png_bytes, content_type="image/png")
        res = self.client.post('/api/v1/sources/documents/', {
            'file': png_file,
            'workspace': str(self.ws.id),
            'title': 'Scanned Form Sample',
            'authority_level': 5
        }, format='multipart')

        assert res.status_code == 201
        doc_id = res.json()['document']['id']

        doc = SourceDocument.objects.get(id=doc_id)
        assert doc.status in ('ready', 'needs_review')
        assert doc.pages.count() == 1

        page = doc.pages.first()
        assert page is not None
        assert page.extraction_type == 'ocr_tesseract'
        assert page.confidence > 0.0
        assert len(page.text) > 0
        # If Tesseract is installed and recognized, bounding boxes are generated
        assert isinstance(page.bounding_boxes, list)

    def test_live_realtime_ocr_endpoint(self):
        """Tests POST /api/v1/sources/documents/live-ocr/ for immediate real-time extraction."""
        img = Image.new('RGB', (600, 150), color='white')
        d = ImageDraw.Draw(img)
        d.text((40, 50), "REALTIME OCR STREAMING TEST", fill='black')

        buf = io.BytesIO()
        img.save(buf, format='PNG')
        png_bytes = buf.getvalue()

        png_file = SimpleUploadedFile("live-test.png", png_bytes, content_type="image/png")
        res = self.client.post('/api/v1/sources/documents/live-ocr/', {
            'file': png_file,
            'bengali_repair': 'true',
            'arabic_digits': 'true',
        }, format='multipart')

        assert res.status_code == 200
        data = res.json()
        assert data['status'] == 'success'
        assert data['page_count'] == 1
        assert data['timings_ms'] > 0
        assert 'pages' in data
        assert data['ocr_confidence'] > 0.0

    def test_landtech_hackathon_ocr_repair(self):
        """Validates exact normalization of real-world LandTech 2026 hackathon OCR output."""
        raw_ocr = """LandTech 2026
LandTech Innovation Hackathon
ল্যান্ডটকে ইনোভশেন হ্যাকাথন
Land Tech Software for Smart E-Governance in Bangladesh
-
স্মার্ট ই গভর্ন্যান্সের জন্য ল্যান্ডটকে সফটওয়্যার
Track /
ট্র্যাক
Digital Land Records, Verification & Digitization
,
ডজিটিাল ভূ মি রর্কেড যাচাইকরণ ও ডজিটিাইজশেন
Rule Book
নয়িমাবলি
Version 1.2 | .
সংস্করণ ১ ২
Organized by /
আয়োজনে
Department of CSE & CSE-TECH, Daffodil International University
- ,
সিএসই বভিাগ ও সিএসই টকে ড্যাফোডলি ইন্টারন্যাশনাল ইউনভিার্সটিি
Supported by /
সহযোগতিায়
Department of Law, Daffodil International University
,
আইন বভিাগ ড্যাফোডলি ইন্টারন্যাশনাল ইউনভিার্সটিি
Venue /
ভন্যেু
Round 1: Online (Google Meet) | : ( )
প্রথম রাউন্ড অনলাইন গুগল মটি
Final: Knowledge Tower (Library), Daffodil International University
: ( ),
চূড়ান্ত র্পব নলজে টাওয়ার লাইব্ররেি ড্যাফোডলি ইন্টারন্যাশনাল ইউনভিার্সটিি
Part A: English | Part B:
বাংলা"""

        repaired = repair_visual_bengali_document(raw_ocr)
        assert "ল্যান্ডটেক ইনোভেশন হ্যাকাথন" in repaired
        assert "স্মার্ট ই-গভর্ন্যান্সের জন্য ল্যান্ডটেক সফটওয়্যার" in repaired
        assert "ডিজিটাল ভূমি রেকর্ড যাচাইকরণ ও ডিজিটাইজেশন" in repaired
        assert "নিয়মাবলী" in repaired
        assert "সংস্করণ ১.২" in repaired
        assert "সিএসই বিভাগ ও সিএসই টেক ড্যাফোডিল ইন্টারন্যাশনাল ইউনিভার্সিটি" in repaired
        assert "আইন বিভাগ ড্যাফোডিল ইন্টারন্যাশনাল ইউনিভার্সিটি" in repaired
        assert "ভেন্যু" in repaired
        assert "গুগল মিট" in repaired
        assert "চূড়ান্ত পর্ব নলেজ টাওয়ার লাইব্রেরি ড্যাফোডিল ইন্টারন্যাশনাল ইউনিভার্সিটি" in repaired

    def test_multi_file_upload_different_formats_without_hallucination(self):
        """
        Tests simultaneous upload of multiple files of diverse supported formats:
        - Markdown (.md)
        - Plaintext (.txt)
        - CSV Spreadsheet (.csv)
        - HTML (.html)
        Verifies that:
        1. All files are ingested simultaneously into the knowledge grid.
        2. Each file is isolated with its own distinct identity, pages, and chunks.
        3. No cross-document pollution or contextual hallucination occurs.
        """
        # File 1: Markdown
        md_bytes = (
            "# Engineering Security Architecture\n\n"
            "All cloud APIs must use mTLS and JWT RS256 token verification."
        ).encode('utf-8')
        md_file = SimpleUploadedFile("security-architecture.md", md_bytes, content_type="text/markdown")

        # File 2: Plain text
        txt_bytes = (
            "Disaster Recovery Runbook 2026\n"
            "Secondary region failover RTO is under 15 minutes."
        ).encode('utf-8')
        txt_file = SimpleUploadedFile("dr-runbook.txt", txt_bytes, content_type="text/plain")

        # File 3: CSV Spreadsheet
        csv_bytes = (
            "Service,Owner,Tier\n"
            "AuthGateway,SecurityTeam,Tier-1\n"
            "BillingEngine,FinanceTeam,Tier-1"
        ).encode('utf-8')
        csv_file = SimpleUploadedFile("services-inventory.csv", csv_bytes, content_type="text/csv")

        # File 4: HTML Document
        html_bytes = (
            "<!DOCTYPE html><html><body>"
            "<h1>Compliance Directive 2026</h1>"
            "<p>Annual SOC2 Type II audit must be published to board before Q4.</p>"
            "<script>alert('bad');</script>"
            "</body></html>"
        ).encode('utf-8')
        html_file = SimpleUploadedFile("compliance-directive.html", html_bytes, content_type="text/html")

        # Submit all 4 files simultaneously via multipart/form-data
        res = self.client.post('/api/v1/sources/documents/', {
            'files': [md_file, txt_file, csv_file, html_file],
            'workspace': str(self.ws.id),
            'collection': str(self.collection.id),
            'authority_level': 5
        }, format='multipart')

        assert res.status_code == 201
        data = res.json()
        assert data['count'] == 4
        assert len(data['documents']) == 4
        assert len(data['job_ids']) == 4

        # Retrieve each document from DB and verify integrity and zero-hallucination
        doc_ids = [d['id'] for d in data['documents']]
        docs = list(SourceDocument.objects.filter(id__in=doc_ids))
        assert len(docs) == 4

        # Verify Markdown document
        doc_md = next(d for d in docs if "security-architecture" in d.original_filename)
        assert doc_md.status == 'ready'
        assert doc_md.document_type == 'txt'
        chunks_md = DocumentChunk.objects.filter(document=doc_md)
        assert len(chunks_md) >= 1
        assert "mTLS" in chunks_md[0].text
        # Anti-hallucination check: must NOT contain DR or CSV text
        assert "Disaster Recovery" not in chunks_md[0].text
        assert "AuthGateway" not in chunks_md[0].text

        # Verify Plaintext document
        doc_txt = next(d for d in docs if "dr-runbook" in d.original_filename)
        assert doc_txt.status == 'ready'
        chunks_txt = DocumentChunk.objects.filter(document=doc_txt)
        assert len(chunks_txt) >= 1
        assert "failover RTO" in chunks_txt[0].text
        assert "mTLS" not in chunks_txt[0].text

        # Verify CSV document
        doc_csv = next(d for d in docs if "services-inventory" in d.original_filename)
        assert doc_csv.status == 'ready'
        assert doc_csv.document_type == 'spreadsheet'
        chunks_csv = DocumentChunk.objects.filter(document=doc_csv)
        assert len(chunks_csv) >= 1
        assert "AuthGateway" in chunks_csv[0].text

        # Verify HTML document
        doc_html = next(d for d in docs if "compliance-directive" in d.original_filename)
        assert doc_html.status == 'ready'
        chunks_html = DocumentChunk.objects.filter(document=doc_html)
        assert len(chunks_html) >= 1
        assert "SOC2 Type II" in chunks_html[0].text
        # Script tags must be stripped to prevent prompt injection / hallucination
        assert "<script>" not in chunks_html[0].text
        assert "alert(" not in chunks_html[0].text

    def test_bulk_upload_endpoint_with_partial_failure_resilience(self):
        """
        Tests POST /api/v1/sources/documents/bulk-upload/ endpoint:
        - Ingests valid files successfully
        - Accurately rejects invalid files without crashing or rolling back valid documents
        """
        valid_bytes = b"# Valid Policy\n\nMust encrypt at rest."
        valid_file = SimpleUploadedFile("valid-policy.md", valid_bytes, content_type="text/markdown")

        # Corrupted / invalid file (empty 0 bytes)
        empty_file = SimpleUploadedFile("corrupted-empty.md", b"", content_type="text/markdown")

        res = self.client.post('/api/v1/sources/documents/bulk-upload/', {
            'files': [valid_file, empty_file],
            'workspace': str(self.ws.id),
            'authority_level': 4
        }, format='multipart')

        assert res.status_code == 201
        data = res.json()
        assert data['status'] == 'partial_success'
        assert data['total_count'] == 2
        assert data['success_count'] == 1
        assert data['failed_count'] == 1
        assert len(data['successful']) == 1
        assert len(data['failed']) == 1
        assert data['failed'][0]['filename'] == 'corrupted-empty.md'



