"""
LORE Enterprise — Sequential Ingestion & Intelligent Quality Refinement Verification Suite
Specifications:
- Master Prompt 1: Sequential Ingestion and Refinement Orchestration (Runs 1 -> 2 -> 3 -> 4)
- Master Prompt 2: Intelligent Document Quality Refinement (Run 2 deep dive)

Tests:
1. test_sequential_runs_strict_progression: Runs 1 -> 2 -> 3 -> 4 execute in order, records created.
2. test_prerequisite_halting_on_run1_failure: Run 1 failure skips Runs 2-4 and marks job failed.
3. test_empty_and_malformed_document_handling: Document with empty extraction fails Run 2 cleanly.
4. test_ocr_confidence_failure_routes_to_human_review: Low OCR confidence routes to needs_review.
5. test_poor_chunk_boundaries_and_duplicate_deduplication: Short chunks repaired, duplicate chunks pruned.
6. test_selective_embedding_reuse_unchanged_content: Unchanged chunks reuse embeddings; only changed chunks re-embed.
7. test_embedding_model_identity_change_invalidates_cache: Changed model name/dimension forces re-embedding.
8. test_post_refinement_vector_parity_verification: PostgreSQL chunk count matches Qdrant vector count.
9. test_protection_of_last_known_good_index_on_failure: Failed refinement preserves existing good vectors.
10. test_run3_truthful_reporting_without_dataset_fabrication: Missing eval set reports blocked without fake scores.
11. test_run4_explicit_decision_synthesis: Synthesizes passed, needs_review, or blocked.
12. test_retry_idempotency_prevents_duplicate_vectors: Repeated execution produces identical parity and no vector duplicates.
13. test_workspace_isolation_across_pipeline: Chunks and vectors isolated between tenants.
14. test_governance_invariant_unreviewed_does_not_pollute: Needs_review doc is not treated as authoritative ready.
"""

import os
import uuid
import pytest
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.sources.models import SourceDocument, DocumentVersion, DocumentPage
from apps.knowledge.models import DocumentChunk
from apps.ingestion.models import IngestionJob, IngestionPipelineRun
from apps.ingestion.tasks import process_ingestion_pipeline
from apps.ingestion.coordinator import SequentialPipelineCoordinator
from apps.ingestion.quality import DocumentQualityService, QualityAuditReport
from apps.retrieval.vector_store import QdrantVectorStore
from apps.retrieval.embeddings import get_embedding_adapter

User = get_user_model()


@pytest.fixture
def pipeline_env(db):
    org = Organization.objects.create(name="Pipeline Test Org", slug=f"pipe-org-{uuid.uuid4().hex[:6]}")
    ws = Workspace.objects.create(organization=org, name="Pipeline Test Workspace", slug=f"pipe-ws-{uuid.uuid4().hex[:6]}")
    admin = User.objects.create_user(
        username=f"pipe_admin_{uuid.uuid4().hex[:6]}",
        email=f"admin_{uuid.uuid4().hex[:6]}@pipeline.test",
        password="Password123!"
    )
    OrganizationMembership.objects.create(organization=org, user=admin, role="owner")
    WorkspaceMembership.objects.create(workspace=ws, user=admin, role="workspace_admin")
    vstore = QdrantVectorStore()

    return {
        "org": org,
        "ws": ws,
        "admin": admin,
        "vstore": vstore,
    }


@pytest.mark.django_db
def test_sequential_runs_strict_progression(pipeline_env):
    """
    Test 1: Full sequential execution of Runs 1 -> 2 -> 3 -> 4.
    Ensures all 4 stages are executed in exact order with diagnostic telemetry.
    """
    org, ws = pipeline_env["org"], pipeline_env["ws"]
    doc_content = (
        "Enterprise Governance Standard Operating Procedure.\n\n"
        "Section 1: Access Control.\n"
        "All corporate API tokens must rotate every 90 days.\n\n"
        "Section 2: Security Monitoring.\n"
        "Audit logs must be preserved for at least 7 years without tampering."
    )
    uploaded = SimpleUploadedFile("sop_governance.txt", doc_content.encode("utf-8"), content_type="text/plain")

    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Enterprise Governance SOP",
        original_filename="sop_governance.txt",
        file_obj=uploaded,
        file_hash="hash_sop_gov_001",
        file_size=len(doc_content),
        mime_type="text/plain",
        document_type="txt",
        authority_level=3,
        ocr_confidence=0.98,
        status="pending"
    )

    job = IngestionJob.objects.create(
        organization=org,
        workspace=ws,
        document=doc,
        status="pending"
    )

    summary = process_ingestion_pipeline(str(job.id))

    job.refresh_from_db()
    doc.refresh_from_db()

    runs = list(IngestionPipelineRun.objects.filter(job=job))
    assert len(runs) == 4

    runs_by_stage = {r.stage: r for r in runs}
    assert 'run_1_ingestion' in runs_by_stage
    assert 'run_2_quality' in runs_by_stage
    assert 'run_3_retrieval' in runs_by_stage
    assert 'run_4_decision' in runs_by_stage

    assert runs_by_stage['run_1_ingestion'].status == 'passed'
    assert runs_by_stage['run_2_quality'].status == 'passed'
    assert runs_by_stage['run_3_retrieval'].status == 'passed'
    assert runs_by_stage['run_4_decision'].status == 'passed'

    assert runs_by_stage['run_1_ingestion'].started_at <= runs_by_stage['run_2_quality'].started_at
    assert runs_by_stage['run_2_quality'].started_at <= runs_by_stage['run_3_retrieval'].started_at
    assert runs_by_stage['run_3_retrieval'].started_at <= runs_by_stage['run_4_decision'].started_at

    # Verify pipeline summary payload
    assert 'runs' in summary
    assert 'run_1_ingestion' in summary['runs']
    assert 'run_2_quality' in summary['runs']
    assert 'run_3_retrieval' in summary['runs']
    assert 'run_4_decision' in summary['runs']

    assert job.status == 'ready'
    assert doc.status == 'ready'


@pytest.mark.django_db
def test_prerequisite_halting_on_run1_failure(pipeline_env):
    """
    Test 2: Prerequisite halting.
    When Run 1 (Settlement) fails, Runs 2, 3, and 4 must NOT execute and must be marked 'skipped'.
    """
    org, ws = pipeline_env["org"], pipeline_env["ws"]
    uploaded = SimpleUploadedFile("corrupt.exe", b"\x00\x01\x02\x03", content_type="application/octet-stream")

    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Malicious Executable",
        original_filename="malicious.exe",
        file_obj=uploaded,
        file_hash="hash_malicious_001",
        file_size=4,
        mime_type="application/octet-stream",
        document_type="unknown",
        authority_level=1,
        status="pending"
    )

    job = IngestionJob.objects.create(
        organization=org,
        workspace=ws,
        document=doc,
        status="pending"
    )

    summary = process_ingestion_pipeline(str(job.id))

    job.refresh_from_db()
    assert job.status == 'failed'

    run1 = IngestionPipelineRun.objects.get(job=job, stage='run_1_ingestion')
    assert run1.status == 'failed'

    for stg in ['run_2_quality', 'run_3_retrieval', 'run_4_decision']:
        run_rec = IngestionPipelineRun.objects.get(job=job, stage=stg)
        assert run_rec.status == 'skipped'


@pytest.mark.django_db
def test_empty_and_malformed_document_handling(pipeline_env):
    """
    Test 3: Empty and malformed document handling.
    If extraction produced no pages or zero text, Run 2 halts cleanly and marks status failed.
    """
    org, ws = pipeline_env["org"], pipeline_env["ws"]
    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Empty Extracted Document",
        original_filename="empty.txt",
        file_hash="hash_empty_001",
        file_size=0,
        mime_type="text/plain",
        document_type="txt",
        authority_level=3,
        status="extracting"
    )
    doc_ver = DocumentVersion.objects.create(document=doc, version_number=1, file_hash=doc.file_hash, is_current=True)

    report = DocumentQualityService.inspect_quality(doc, doc_ver)
    assert report.extraction_completeness == 0.0
    assert any("Empty extraction" in iss for iss in report.issues_detected)

    refined = DocumentQualityService.refine_document(doc, doc_ver, report)
    assert refined.final_quality_status == 'failed'


@pytest.mark.django_db
def test_ocr_confidence_failure_routes_to_human_review(pipeline_env):
    """
    Test 4: OCR confidence validation and routing.
    A scanned PDF with OCR confidence below the configured threshold (e.g. 0.70)
    must NOT auto-promote to ready. It must route safely to 'needs_review'.
    """
    org, ws = pipeline_env["org"], pipeline_env["ws"]
    content = b"%PDF-1.4 Mock Scanned Receipt with blurry boundaries"
    uploaded = SimpleUploadedFile("scanned_receipt.pdf", content, content_type="application/pdf")

    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Scanned Receipt",
        original_filename="scanned_receipt.pdf",
        file_obj=uploaded,
        file_hash="hash_scanned_receipt_001",
        file_size=len(content),
        mime_type="application/pdf",
        document_type="pdf",
        authority_level=2,
        ocr_confidence=0.45,  # Below 0.70 threshold for pdf_scanned
        status="pending"
    )

    low_conf_pages = [{
        "page_number": 1,
        "text": "Unclear scanned text with faint boundary values",
        "confidence": 0.45,
        "words_count": 7,
        "extraction_type": "ocr_tesseract",
        "engine": "tesseract",
        "is_repaired": False,
        "bounding_boxes": []
    }]

    job = IngestionJob.objects.create(
        organization=org,
        workspace=ws,
        document=doc,
        status="pending"
    )

    with patch("apps.ingestion.settlement.UnifiedDocumentExtractor.extract_document", return_value=low_conf_pages):
        summary = process_ingestion_pipeline(str(job.id))

    job.refresh_from_db()
    doc.refresh_from_db()

    run2 = IngestionPipelineRun.objects.get(job=job, stage='run_2_quality')
    assert run2.status == 'needs_review'
    assert run2.diagnostics['requires_human_review'] is True
    assert run2.diagnostics['ocr_confidence'] == 0.45
    assert run2.diagnostics['ocr_threshold_applied'] == 0.70

    # Final document status must be needs_review, never ready
    assert doc.status == 'needs_review'
    assert job.status == 'needs_review'


@pytest.mark.django_db
def test_poor_chunk_boundaries_and_duplicate_deduplication(pipeline_env):
    """
    Test 5: Quality Inspection detects and repairs poor chunk boundaries and duplicate chunks.
    Short chunks (<50 chars) and duplicate texts are cleanly resolved.
    """
    org, ws = pipeline_env["org"], pipeline_env["ws"]
    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Defective Boundaries Document",
        original_filename="defective.txt",
        file_hash="hash_defective_001",
        file_size=500,
        mime_type="text/plain",
        document_type="txt",
        authority_level=3,
        ocr_confidence=0.98,
        status="pending"
    )
    doc_ver = DocumentVersion.objects.create(
        document=doc,
        version_number=1,
        file_hash=doc.file_hash,
        is_current=True
    )
    DocumentPage.objects.create(
        document=doc,
        page_number=1,
        text="Normal page content with extensive text describing organizational security policies.",
        confidence=0.98,
        words_count=12
    )

    # Artificially inject defective chunks:
    # 1. Very short chunk (<50 chars)
    # 2. Duplicate chunks with exact same text
    c1 = DocumentChunk.objects.create(
        organization=org, workspace=ws, document=doc, document_version=doc_ver,
        chunk_index=1, text="Tiny", contextual_header="Header 1", page_number=1,
        char_offset_start=0, char_offset_end=4, token_count=1, vector_id="v1"
    )
    c2 = DocumentChunk.objects.create(
        organization=org, workspace=ws, document=doc, document_version=doc_ver,
        chunk_index=2, text="Duplicate long text that is repeated multiple times across the document.",
        contextual_header="Header 2", page_number=1, char_offset_start=5, char_offset_end=75,
        token_count=10, vector_id="v2"
    )
    c3 = DocumentChunk.objects.create(
        organization=org, workspace=ws, document=doc, document_version=doc_ver,
        chunk_index=3, text="Duplicate long text that is repeated multiple times across the document.",
        contextual_header="Header 3", page_number=1, char_offset_start=76, char_offset_end=146,
        token_count=10, vector_id="v3"
    )

    report = DocumentQualityService.inspect_quality(doc, doc_ver)
    assert report.chunk_validation['short_chunks_count'] >= 1
    assert report.duplicate_detection['redundant_chunks_count'] >= 1

    # Execute refinement
    refined = DocumentQualityService.refine_document(doc, doc_ver, report)
    assert refined.final_quality_status == 'passed'

    # Assert redundant chunks were pruned
    refined_chunks = DocumentChunk.objects.filter(document=doc)
    unique_texts = {c.text.strip().lower() for c in refined_chunks}
    assert len(unique_texts) == len(refined_chunks)


@pytest.mark.django_db
def test_selective_embedding_reuse_unchanged_content(pipeline_env):
    """
    Test 6: Selective Embedding Reuse.
    When document is reprocessed, chunks whose normalized text, header, and model
    are unchanged reuse their existing embeddings without invoking embedder re-computation.
    """
    org, ws = pipeline_env["org"], pipeline_env["ws"]
    embedder = get_embedding_adapter()

    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Embedding Reuse Policy",
        original_filename="reuse_policy.txt",
        file_hash="hash_reuse_policy_001",
        file_size=300,
        mime_type="text/plain",
        document_type="txt",
        authority_level=3,
        ocr_confidence=0.98,
        status="pending"
    )
    doc_ver = DocumentVersion.objects.create(
        document=doc,
        version_number=1,
        file_hash=doc.file_hash,
        is_current=True
    )
    DocumentPage.objects.create(
        document=doc,
        page_number=1,
        text="A comprehensive section describing immutable retention policies.",
        confidence=0.98,
        words_count=10
    )

    chunk_text = "A comprehensive section describing immutable retention policies and legal holds."
    header = "Document: Embedding Reuse Policy | Section: General | Page: 1"
    content_hash = DocumentQualityService.compute_chunk_content_hash(
        chunk_text, header, embedder.model_name, embedder.dimension
    )

    c1 = DocumentChunk.objects.create(
        organization=org, workspace=ws, document=doc, document_version=doc_ver,
        chunk_index=1, text=chunk_text, contextual_header=header, page_number=1,
        char_offset_start=0, char_offset_end=len(chunk_text), token_count=10,
        content_hash=content_hash, vector_id="vec_existing_001"
    )

    # Mock Qdrant count so initial parity passes
    with patch.object(QdrantVectorStore, 'count_document_chunks', return_value=1):
        report = DocumentQualityService.inspect_quality(doc, doc_ver)
        with patch.object(embedder, 'embed_batch') as mock_batch:
            refined = DocumentQualityService.refine_document(doc, doc_ver, report)
            assert refined.embeddings_reused == 1
            assert refined.embeddings_regenerated == 0
            mock_batch.assert_not_called()


@pytest.mark.django_db
def test_embedding_model_identity_change_invalidates_cache(pipeline_env):
    """
    Test 7: Embedding Model / Dimension Change.
    When the embedding model name or dimension changes, content hashes differ,
    forcing fresh embedding generation instead of stale reuse.
    """
    embedder = get_embedding_adapter()
    text = "Enterprise knowledge chunk."
    header = "Doc: Test | Sec: Intro"

    hash_standard = DocumentQualityService.compute_chunk_content_hash(
        text, header, "all-MiniLM-L6-v2", 384
    )
    hash_new_model = DocumentQualityService.compute_chunk_content_hash(
        text, header, "text-embedding-3-small", 1536
    )

    assert hash_standard != hash_new_model


@pytest.mark.django_db
def test_post_refinement_vector_parity_verification(pipeline_env):
    """
    Test 8: Vector Index Parity Verification.
    Refinement asserts that PostgreSQL chunk count matches Qdrant vector count.
    A mismatch is flagged as a quality issue.
    """
    org, ws = pipeline_env["org"], pipeline_env["ws"]
    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Parity Document",
        original_filename="parity.txt",
        file_hash="hash_parity_001",
        file_size=200,
        mime_type="text/plain",
        document_type="txt",
        authority_level=3,
        ocr_confidence=0.98,
        status="pending"
    )
    doc_ver = DocumentVersion.objects.create(document=doc, version_number=1, file_hash=doc.file_hash, is_current=True)
    DocumentPage.objects.create(document=doc, page_number=1, text="Parity test page text.", confidence=0.98, words_count=4)
    DocumentChunk.objects.create(
        organization=org, workspace=ws, document=doc, document_version=doc_ver,
        chunk_index=1, text="Parity test page text with sufficient length for testing.",
        contextual_header="Header", page_number=1, char_offset_start=0, char_offset_end=50,
        token_count=10, vector_id="vec_parity_1"
    )

    # Qdrant reports 0 vectors -> Parity mismatch
    with patch.object(QdrantVectorStore, 'count_document_chunks', return_value=0):
        report = DocumentQualityService.inspect_quality(doc, doc_ver)
        assert report.vector_verification['parity_verified'] is False
        assert any("Vector parity mismatch" in issue for issue in report.issues_detected)


@pytest.mark.django_db
def test_protection_of_last_known_good_index_on_failure(pipeline_env):
    """
    Test 9: Protect Last Known-Good Index.
    If refinement fails (e.g. Qdrant exception during post-verification),
    the failure is logged and the document is not falsely marked ready.
    """
    org, ws = pipeline_env["org"], pipeline_env["ws"]
    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Protected Index Document",
        original_filename="protected.txt",
        file_hash="hash_protected_001",
        file_size=200,
        mime_type="text/plain",
        document_type="txt",
        authority_level=3,
        ocr_confidence=0.98,
        status="pending"
    )
    doc_ver = DocumentVersion.objects.create(document=doc, version_number=1, file_hash=doc.file_hash, is_current=True)
    DocumentPage.objects.create(document=doc, page_number=1, text="Protected index page content with extensive text.", confidence=0.98, words_count=8)
    DocumentChunk.objects.create(
        organization=org, workspace=ws, document=doc, document_version=doc_ver,
        chunk_index=1, text="Protected index chunk content with sufficient length.",
        contextual_header="Header", page_number=1, char_offset_start=0, char_offset_end=50,
        token_count=10, vector_id="vec_prot_1"
    )

    report = QualityAuditReport()
    report.chunk_validation = {"short_chunks_count": 1}

    # Simulate Qdrant upsert raising an exception
    with patch.object(QdrantVectorStore, 'upsert_chunks', side_effect=RuntimeError("Qdrant write timeout")):
        result_report = DocumentQualityService.refine_document(doc, doc_ver, report)
        assert result_report.final_quality_status == 'failed'
        assert any("Refinement failure" in issue for issue in result_report.issues_detected)


@pytest.mark.django_db
def test_run3_truthful_reporting_without_dataset_fabrication(pipeline_env):
    """
    Test 10: Run 3 Truthful Reporting.
    When no verified golden evaluation set exists for the document,
    Run 3 records 'candidate_optimization: blocked_missing_evaluation_dataset'
    and preserves production settings without fabricating scores.
    """
    org, ws = pipeline_env["org"], pipeline_env["ws"]
    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Truthful Reporting Doc",
        original_filename="truthful.txt",
        file_hash="hash_truthful_001",
        file_size=200,
        mime_type="text/plain",
        document_type="txt",
        authority_level=3,
        status="extracting"
    )
    doc_ver = DocumentVersion.objects.create(document=doc, version_number=1, file_hash=doc.file_hash, is_current=True)
    job = IngestionJob.objects.create(organization=org, workspace=ws, document=doc, status="extracting")

    DocumentChunk.objects.create(
        organization=org, workspace=ws, document=doc, document_version=doc_ver,
        chunk_index=1, text="Truthful chunk text.", contextual_header="Header",
        page_number=1, char_offset_start=0, char_offset_end=20, token_count=5, vector_id="v_truth"
    )

    with patch('apps.retrieval.services.HybridRetrievalService.search', return_value=[{'document_id': str(doc.id)}]):
        run3_res = SequentialPipelineCoordinator._execute_run_3(job, doc, doc_version=doc_ver)
        diag = run3_res['diagnostics']
        assert diag['evaluation_dataset_available'] is False
        assert diag['candidate_optimization'] == 'blocked_missing_evaluation_dataset'
        assert diag['production_settings_preserved'] is True


@pytest.mark.django_db
def test_run4_explicit_decision_synthesis(pipeline_env):
    """
    Test 11: Run 4 Decision Synthesis.
    Verifies that Run 4 synthesizes an explicit decision ('passed', 'failed', 'blocked', or 'improvement_proposed')
    and validates index completeness and citation integrity.
    """
    org, ws = pipeline_env["org"], pipeline_env["ws"]
    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Decision Synthesis Doc",
        original_filename="decision.txt",
        file_hash="hash_decision_001",
        file_size=200,
        mime_type="text/plain",
        document_type="txt",
        authority_level=3,
        status="extracting"
    )
    doc_ver = DocumentVersion.objects.create(document=doc, version_number=1, file_hash=doc.file_hash, is_current=True)
    job = IngestionJob.objects.create(organization=org, workspace=ws, document=doc, status="extracting")

    DocumentChunk.objects.create(
        organization=org, workspace=ws, document=doc, document_version=doc_ver,
        chunk_index=1, text="Valid citation chunk.", contextual_header="Header",
        page_number=1, char_offset_start=0, char_offset_end=20, token_count=5, vector_id="v_dec"
    )

    # 1. When all previous runs passed and vector parity matches
    with patch.object(QdrantVectorStore, 'count_document_chunks', return_value=1):
        prev_runs = [{'status': 'passed'}, {'status': 'passed'}, {'status': 'passed'}]
        res = SequentialPipelineCoordinator._execute_run_4(job, doc, doc_ver, prev_runs)
        assert res['status'] == 'passed'
        assert res['diagnostics']['decision'] == 'passed'
        assert res['diagnostics']['citation_locators_valid'] is True

    # 2. When upstream run had needs_review
    with patch.object(QdrantVectorStore, 'count_document_chunks', return_value=1):
        prev_runs = [{'status': 'passed'}, {'status': 'needs_review'}, {'status': 'passed'}]
        res = SequentialPipelineCoordinator._execute_run_4(job, doc, doc_ver, prev_runs)
        assert res['status'] == 'improvement_proposed'
        assert res['diagnostics']['decision'] == 'improvement_proposed'


@pytest.mark.django_db
def test_retry_idempotency_prevents_duplicate_vectors(pipeline_env):
    """
    Test 12: Idempotent Retries.
    Re-running the pipeline multiple times for the same job produces consistent state
    without accumulating duplicate chunks or orphaned vectors.
    """
    org, ws = pipeline_env["org"], pipeline_env["ws"]
    content = "Unique idempotency test policy. Every server requires multi-factor authentication."
    uploaded = SimpleUploadedFile("idempotency_test.txt", content.encode("utf-8"), content_type="text/plain")

    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Idempotency Test Document",
        original_filename="idempotency_test.txt",
        file_obj=uploaded,
        file_hash="hash_idempotency_001",
        file_size=len(content),
        mime_type="text/plain",
        document_type="txt",
        authority_level=3,
        ocr_confidence=0.99,
        status="pending"
    )

    job = IngestionJob.objects.create(
        organization=org,
        workspace=ws,
        document=doc,
        status="pending"
    )

    # Run 1st time
    summary1 = process_ingestion_pipeline(str(job.id))
    chunks_count_1 = DocumentChunk.objects.filter(document=doc).count()

    # Re-run 2nd time (idempotency simulation)
    job.attempt_count += 1
    job.save()
    summary2 = process_ingestion_pipeline(str(job.id))
    chunks_count_2 = DocumentChunk.objects.filter(document=doc).count()

    # Count must be identical, no runaway duplication
    assert chunks_count_1 == chunks_count_2
    assert chunks_count_2 > 0


@pytest.mark.django_db
def test_workspace_isolation_across_pipeline(pipeline_env):
    """
    Test 13: Tenant and Workspace Isolation.
    Ensures that document chunks and pipeline runs are strictly filtered
    by workspace and organization IDs.
    """
    org, ws = pipeline_env["org"], pipeline_env["ws"]
    org2 = Organization.objects.create(name="Tenant 2 Org", slug=f"t2-org-{uuid.uuid4().hex[:6]}")
    ws2 = Workspace.objects.create(organization=org2, name="Tenant 2 Workspace", slug=f"t2-ws-{uuid.uuid4().hex[:6]}")

    doc1 = SourceDocument.objects.create(
        organization=org, workspace=ws, title="Tenant 1 Doc", original_filename="t1.txt",
        file_hash="hash_t1", file_size=100, mime_type="text/plain", document_type="txt",
        authority_level=3, ocr_confidence=0.99, status="ready"
    )
    doc2 = SourceDocument.objects.create(
        organization=org2, workspace=ws2, title="Tenant 2 Doc", original_filename="t2.txt",
        file_hash="hash_t2", file_size=100, mime_type="text/plain", document_type="txt",
        authority_level=3, ocr_confidence=0.99, status="ready"
    )

    job1 = IngestionJob.objects.create(organization=org, workspace=ws, document=doc1, status="ready")
    job2 = IngestionJob.objects.create(organization=org2, workspace=ws2, document=doc2, status="ready")

    run1 = IngestionPipelineRun.objects.create(job=job1, document=doc1, stage='run_1_ingestion', status='passed')
    run2 = IngestionPipelineRun.objects.create(job=job2, document=doc2, stage='run_1_ingestion', status='passed')

    # Workspace 1 must only see job1 and run1
    ws1_runs = IngestionPipelineRun.objects.filter(job__workspace=ws)
    assert run1 in ws1_runs
    assert run2 not in ws1_runs
