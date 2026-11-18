import io
import json
import uuid
import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument, DocumentVersion, DocumentPage
from apps.knowledge.models import DocumentChunk
from apps.sources.services import StorageSecurityService, ALLOWED_EXTENSIONS
from apps.ingestion.pipeline.extractors import EmlFileExtractor, UnifiedDocumentExtractor, TextExtractor
import mcp_server


class TestMultiFormatExtensions:
    """Verifies that .yaml, .yml, .toml, and .eml are recognized and validated safely."""

    def test_allowed_extensions_contain_new_types(self):
        for ext in ('.yaml', '.yml', '.toml', '.eml'):
            assert ext in ALLOWED_EXTENSIONS, f"Extension '{ext}' missing from ALLOWED_EXTENSIONS"
            assert ALLOWED_EXTENSIONS[ext] == 'txt'

    def test_storage_security_validates_yaml(self):
        yaml_content = b"version: '3.8'\nservices:\n  web:\n    image: nginx:alpine\n"
        upload = SimpleUploadedFile("deploy.yaml", yaml_content)
        meta = StorageSecurityService.inspect_and_validate(upload)
        assert meta['document_type'] == 'txt'
        assert meta['mime_type'] == 'application/x-yaml'
        assert meta['file_size'] == len(yaml_content)

    def test_storage_security_validates_toml(self):
        toml_content = b"[tool.poetry]\nname = 'lore'\nversion = '1.0.0'\n"
        upload = SimpleUploadedFile("pyproject.toml", toml_content)
        meta = StorageSecurityService.inspect_and_validate(upload)
        assert meta['document_type'] == 'txt'
        assert meta['mime_type'] == 'application/toml'

    def test_storage_security_validates_eml(self):
        eml_content = (
            b"From: ciso@enterprise.internal\r\n"
            b"To: compliance@enterprise.internal\r\n"
            b"Subject: Encryption Architecture Policy Update\r\n"
            b"Date: Mon, 18 Nov 2026 10:00:00 +0000\r\n"
            b"\r\n"
            b"Please ensure all S3 buckets are encrypted with AES-256-GCM.\r\n"
        )
        upload = SimpleUploadedFile("policy_update.eml", eml_content)
        meta = StorageSecurityService.inspect_and_validate(upload)
        assert meta['document_type'] == 'txt'
        assert meta['mime_type'] == 'message/rfc822'

    def test_eml_file_extractor_parses_rfc822(self):
        eml_bytes = (
            b"From: Jane Doe <jane@company.com>\r\n"
            b"To: John Smith <john@company.com>\r\n"
            b"Subject: Quarterly Governance Audit\r\n"
            b"Date: Mon, 18 Nov 2026 14:30:00 +0000\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"\r\n"
            b"The Q4 regulatory audit is scheduled for next Tuesday.\r\n"
            b"All team leads must submit their compliance evidence by Friday.\r\n"
        )
        pages = EmlFileExtractor.extract(eml_bytes)
        assert len(pages) == 1
        page = pages[0]
        text = page['text']
        assert "# Email: Quarterly Governance Audit" in text
        assert "**From:** Jane Doe <jane@company.com>" in text
        assert "**To:** John Smith <john@company.com>" in text
        assert "The Q4 regulatory audit is scheduled for next Tuesday." in text
        assert page['extraction_type'] == 'eml_rfc822_extract'

    def test_unified_extractor_dispatches_eml_and_yaml(self):
        extractor = UnifiedDocumentExtractor()
        
        # Test .eml dispatch
        eml_bytes = b"From: a@b.com\r\nTo: c@d.com\r\nSubject: Test\r\n\r\nMessage body"
        eml_res = extractor.extract_document(eml_bytes, doc_type='txt', filename='test.eml')
        assert eml_res[0]['extraction_type'] == 'eml_rfc822_extract'
        assert "# Email: Test" in eml_res[0]['text']

        # Test .yaml dispatch
        yaml_bytes = b"foo: bar\nkey: value\n"
        yaml_res = extractor.extract_document(yaml_bytes, doc_type='txt', filename='config.yaml')
        assert yaml_res[0]['extraction_type'] == 'plaintext_extract'
        assert "foo: bar" in yaml_res[0]['text']


class TestUploadMemorySettings:
    """Verifies that Django upload memory limits are properly configured."""

    def test_upload_memory_limits_configured(self):
        assert hasattr(settings, 'DATA_UPLOAD_MAX_MEMORY_SIZE')
        assert settings.DATA_UPLOAD_MAX_MEMORY_SIZE >= 100 * 1024 * 1024  # >= 100 MB
        assert hasattr(settings, 'FILE_UPLOAD_MAX_MEMORY_SIZE')
        assert settings.FILE_UPLOAD_MAX_MEMORY_SIZE >= 50 * 1024 * 1024   # >= 50 MB
        assert settings.DATA_UPLOAD_MAX_NUMBER_FILES >= 125


@pytest.mark.django_db
class TestMCPFetchAndCitationEnrichment:
    """Verifies fetch() handles DocumentChunk.text and get_context citations have granular locators."""

    @pytest.fixture
    def setup_entities(self):
        org = Organization.objects.create(name="Cyber Corp", slug=f"cyber-{uuid.uuid4().hex[:6]}")
        ws = Workspace.objects.create(organization=org, name="Compliance WS", slug="comp-ws", is_default=True)
        doc = SourceDocument.objects.create(
            organization=org,
            workspace=ws,
            title="Enterprise Security Architecture",
            original_filename="security_arch.docx",
            document_code="DOC-SEC-001",
            status="ready",
            authority_level=6,
            current_version_number=1,
            file_size=1024,
            file_hash="hash_sec_arch_0000000000000000000000000000000000000000"
        )
        ver = DocumentVersion.objects.create(
            document=doc,
            version_number=1,
            file_hash=doc.file_hash,
            is_current=True
        )
        chunk = DocumentChunk.objects.create(
            organization=org,
            workspace=ws,
            document=doc,
            document_version=ver,
            chunk_index=0,
            text="All cloud environments must implement mutual TLS (mTLS) for inter-service communication.",
            page_number=3,
            section_identifier="Section 3.2 mTLS Architecture",
            heading_path="Security > Network Security > mTLS",
            token_count=18
        )
        return {"org": org, "ws": ws, "doc": doc, "chunk": chunk}

    def test_handle_fetch_on_chunk_reads_text_without_attribute_error(self, setup_entities):
        chunk = setup_entities["chunk"]
        ws = setup_entities["ws"]

        # Call handle_fetch with chunk ID
        raw_res = mcp_server.handle_fetch({"id": str(chunk.id), "workspace_id": str(ws.id)})
        res = json.loads(raw_res)

        assert res["id"] == str(chunk.id)
        assert "mutual TLS (mTLS)" in res["text"]
        assert "lore://chunk/" in res["url"]
        assert res["metadata"]["page_number"] == 3
        assert res["metadata"]["section"] == "Section 3.2 mTLS Architecture"
        assert res["metadata"]["heading_path"] == "Security > Network Security > mTLS"

    def test_handle_fetch_on_document_chunks_fallback_reads_text(self, setup_entities):
        doc = setup_entities["doc"]
        ws = setup_entities["ws"]

        # Call handle_fetch on doc (which has no DocumentPage, so falls back to chunks)
        raw_res = mcp_server.handle_fetch({"id": str(doc.id), "workspace_id": str(ws.id)})
        res = json.loads(raw_res)

        assert res["id"] == str(doc.id)
        assert "mutual TLS (mTLS)" in res["text"]
        assert res["metadata"]["document_code"] == "DOC-SEC-001"

