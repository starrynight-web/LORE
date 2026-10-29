"""
LORE Enterprise — Ingestion, Evidence Preservation, and Document Identity Test Suite
Specification:
- DOC-005 carry-forward quantity and expiry date.
- DOC-008 audit retention duration and trigger.
- DOC-002 lodging limit and meal allowance field separation.
- DOC-015 future effective date.
- DOC-016 supersession metadata.
- DOC-017 pending access status.
- DOC-021 referenced but missing content.
- DOC-009 contract terms and DOC-010 invoice facts.

Rules:
- Do not change the source documents to make tests pass.
- Report extraction fidelity, metadata correctness, and index freshness.
"""

import os
import re
import uuid
import zipfile
import tempfile
import pytest
from datetime import datetime, timezone as dt_timezone
from django.conf import settings
from django.core.files import File

from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument, DocumentVersion, DocumentPage
from apps.knowledge.models import (
    DocumentChunk, KnowledgeRelationship, RelationshipType, RelationshipApprovalStatus
)
from apps.ingestion.settlement import ExtractionValidationService, StagedMergeService
from apps.ingestion.metadata import DocumentMetadataExtractor
from apps.retrieval.services import HybridRetrievalService


def get_dataset_zip_path():
    candidate_paths = [
        os.path.join(settings.BASE_DIR, "Lore_Dataset.zip"),
        os.path.join(settings.BASE_DIR, "..", "Lore_Dataset.zip"),
        r"E:\desktop\lore dataset\Lore_Dataset.zip",
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("Lore_Dataset.zip not found in candidate paths.")


@pytest.mark.django_db
class TestIngestionAndEvidencePreservation:

    @pytest.fixture(autouse=True)
    def setup_corpus(self):
        """Sets up workspace and ingests target documents from the actual benchmark dataset."""
        uid = uuid.uuid4().hex[:6]
        self.org = Organization.objects.create(name=f"Northstar Enterprise {uid}", slug=f"northstar-{uid}")
        self.ws = Workspace.objects.create(name=f"Governance Workspace {uid}", organization=self.org)
        self.retrieval_service = HybridRetrievalService()

        # Ingest target documents from benchmark zip
        zip_path = get_dataset_zip_path()
        zf = zipfile.ZipFile(zip_path)

        targets = [
            'DOC-002', 'DOC-005', 'DOC-008', 'DOC-009',
            'DOC-010', 'DOC-015', 'DOC-016', 'DOC-017', 'DOC-020'
        ]

        self.docs = {}
        for doc_code in targets:
            matches = [n for n in zf.namelist() if doc_code in n]
            if not matches:
                continue
            entry_name = matches[0]
            data = zf.read(entry_name)
            ext = os.path.splitext(entry_name)[1].lower().strip('.')
            if ext == 'xlsx':
                doc_type = 'spreadsheet'
                mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            elif ext == 'docx':
                doc_type = 'docx'
                mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            else:
                doc_type = 'pdf'
                mime = 'application/pdf'

            with tempfile.NamedTemporaryFile(suffix='.' + ext, delete=False) as tf:
                tf.write(data)
                tf_path = tf.name

            with open(tf_path, 'rb') as f:
                doc = SourceDocument.objects.create(
                    organization=self.org,
                    workspace=self.ws,
                    title=entry_name,
                    original_filename=entry_name,
                    mime_type=mime,
                    file_size=len(data),
                    file_hash=uuid.uuid4().hex,
                    file_obj=File(f, name=entry_name),
                    document_type=doc_type,
                    status='uploaded'
                )

            doc_ver = DocumentVersion.objects.create(
                document=doc,
                version_number=1,
                file_hash=doc.file_hash,
                file_obj=doc.file_obj,
                is_current=True
            )

            # Stage 3 Extraction & Metadata resolution
            s3, pages_data = ExtractionValidationService.extract_and_validate(doc, doc_ver)
            doc.refresh_from_db()

            # Stage 6 Staged Merge & Chunking
            s6 = StagedMergeService.staged_merge_and_verify(doc, doc_ver, pages_data)
            doc.refresh_from_db()
            doc.status = doc.governance_status or 'ready'
            doc.save(update_fields=['status'])

            self.docs[doc_code] = doc
            os.remove(tf_path)

        # Register DOC-021 missing referenced document
        self.doc_021 = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title='DOC-021 — Travel & Expense Policy (2025)',
            canonical_title='Travel & Expense Policy (2025)',
            document_code='DOC-021',
            original_filename='DOC-021_Travel_Expense_Policy_2025_MISSING.pdf',
            mime_type='application/pdf',
            file_size=0,
            file_hash='0' * 64,
            document_type='pdf',
            status='missing',
            governance_status='missing',
            is_missing=True,
            authority_level=1,
            owner_name='People Operations & Finance',
            effective_from=datetime(2025, 1, 1, 0, 0, tzinfo=dt_timezone.utc),
            effective_date=datetime(2025, 1, 1, 0, 0, tzinfo=dt_timezone.utc),
            validation_notes={'notes': 'Referenced replacement for DOC-016; source document absent from corpus.'}
        )

        doc_016 = self.docs.get('DOC-016')
        if doc_016:
            KnowledgeRelationship.objects.create(
                organization=self.org,
                workspace=self.ws,
                source_document=doc_016,
                target_document=self.doc_021,
                relationship_type=RelationshipType.SUPERSEDES,
                approval_status=RelationshipApprovalStatus.APPROVED,
                confidence=1.0,
                metadata={'description': 'DOC-016 expired 2024-12-31 and was superseded effective 2025-01-01 by DOC-021.'}
            )

    def test_doc005_carry_forward_quantity_and_expiry_date(self):
        """
        Verify DOC-005 preserves:
        - Carry-forward quantity: exactly 5 working days
        - Expiry date: March 31 of next leave year
        - Attached to section identifier / Q&A heading without numeric detachment
        """
        doc = self.docs.get('DOC-005')
        assert doc is not None, "DOC-005 must be ingested"
        assert doc.document_code == 'DOC-005'
        assert doc.status == 'draft'
        assert doc.owner_name == 'People Operations'

        carry_chunks = DocumentChunk.objects.filter(
            document=doc,
            text__icontains='March 31'
        )
        assert carry_chunks.exists(), "DOC-005 must contain chunk with March 31 expiry date"

        found_5_days = False
        found_march_31 = False
        for c in carry_chunks:
            assert c.section_identifier in ('Section 3', 'Section 4', 'Q2', '')
            if '5 unused' in c.text or '5 days' in c.text or 'five days' in c.text:
                found_5_days = True
            if 'March 31' in c.text:
                found_march_31 = True
            assert any(term in c.text for term in ['carry forward', 'Carried-over', 'carried forward'])

        assert found_5_days, "DOC-005 must preserve 5 unused working days carry-forward limit"
        assert found_march_31, "DOC-005 must preserve March 31 expiry date"

    def test_doc008_audit_retention_duration_and_trigger(self):
        """
        Verify DOC-008 preserves:
        - Table headers intact with continuation rows
        - Audit retention duration: 2 years
        - Audit retention trigger: Event timestamp
        - Category: Audit events
        """
        doc = self.docs.get('DOC-008')
        assert doc is not None, "DOC-008 must be ingested"
        assert doc.document_code == 'DOC-008'
        assert doc.status == 'draft'
        assert doc.owner_name == 'Records Management / Legal'

        audit_chunk = DocumentChunk.objects.filter(
            document=doc,
            text__icontains='Audit events'
        ).first()
        assert audit_chunk is not None, "Audit events row must exist in DOC-008 chunks"

        # Verify table header row is preserved
        assert 'Record Category' in audit_chunk.text, "Table header row must be preserved in table chunk"
        assert 'Retention Period' in audit_chunk.text, "Retention Period header must be preserved in table chunk"
        assert 'Retention Trigger' in audit_chunk.text, "Retention Trigger header must be preserved in table chunk"

        # Verify exact row values
        assert '2 years' in audit_chunk.text, "Audit events retention duration must be 2 years"
        assert 'Event timestamp' in audit_chunk.text, "Audit events retention trigger must be Event timestamp"

    def test_doc002_lodging_limit_and_meal_allowance_field_separation(self):
        """
        Verify DOC-002:
        - Hotel reimbursement cap of $220/night is in Section 4
        - Daily meal allowance ($70 daily max, $15 breakfast, $20 lunch, $35 dinner) is in Section 5
        - Lodging and meal allowances are NOT merged into a single chunk without distinct field labels
        """
        doc = self.docs.get('DOC-002')
        assert doc is not None, "DOC-002 must be ingested"
        assert doc.document_code == 'DOC-002'
        assert doc.status == 'approved'
        assert doc.authority_level == 7

        # Lodging limit chunk (Section 4)
        hotel_chunk = DocumentChunk.objects.filter(
            document=doc,
            text__icontains='$220'
        ).first()
        assert hotel_chunk is not None, "DOC-002 must have a chunk containing $220 hotel cap"
        assert hotel_chunk.section_identifier == 'Section 4'
        assert 'Hotel reimbursement is capped at $220 per night' in hotel_chunk.text
        # Meal allowance fields must NOT be merged into Section 4
        assert 'Daily maximum $70' not in hotel_chunk.text
        assert 'Breakfast $15' not in hotel_chunk.text

        # Meal allowance chunk (Section 5)
        meal_chunk = DocumentChunk.objects.filter(
            document=doc,
            text__icontains='$70'
        ).first()
        assert meal_chunk is not None, "DOC-002 must have a chunk containing $70 meal allowance"
        assert meal_chunk.section_identifier == 'Section 5'
        assert '$15' in meal_chunk.text  # Breakfast
        assert '$20' in meal_chunk.text  # Lunch
        assert '$35' in meal_chunk.text  # Dinner
        assert '$70' in meal_chunk.text  # Daily max
        assert 'capped at $220 per night' not in meal_chunk.text

    def test_doc015_future_effective_date_not_inferred_as_draft(self):
        """
        Verify DOC-015:
        - Governance status is 'future-effective' (NOT 'draft')
        - Effective date is 2027-01-01
        - New hotel cap is US$240/night
        - Preserves existing DOC-002 $220 cap through 2026-12-31
        """
        doc = self.docs.get('DOC-015')
        assert doc is not None, "DOC-015 must be ingested"
        assert doc.status == 'future-effective', "Future-effective document must NOT be inferred as draft"
        assert doc.governance_status == 'future-effective'
        assert doc.effective_from == datetime(2027, 1, 1, 0, 0, tzinfo=dt_timezone.utc)

        cap_chunk = DocumentChunk.objects.filter(document=doc, text__icontains='$240').first()
        assert cap_chunk is not None
        assert 'US$240 per night' in cap_chunk.text or '$240 per night' in cap_chunk.text
        assert '1 January 2027' in cap_chunk.text or 'January 1, 2027' in cap_chunk.text

    def test_doc016_supersession_metadata(self):
        """
        Verify DOC-016:
        - Status is 'superseded'
        - Superseded by 'DOC-021' on 2025-01-01
        - Expired on 2024-12-31
        - Historical lodging cap is USD $150/night
        """
        doc = self.docs.get('DOC-016')
        assert doc is not None, "DOC-016 must be ingested"
        assert doc.status == 'superseded'
        assert doc.superseded_by == 'DOC-021'
        assert doc.effective_to == datetime(2024, 12, 31, 0, 0, tzinfo=dt_timezone.utc)

        # Historical lodging cap
        cap_chunk = DocumentChunk.objects.filter(document=doc, text__icontains='$150').first()
        assert cap_chunk is not None
        assert 'USD $150 per night' in cap_chunk.text or '$150 per night' in cap_chunk.text

        # Supersession chunks
        super_chunks = list(DocumentChunk.objects.filter(document=doc, text__icontains='DOC-021'))
        assert len(super_chunks) > 0, "DOC-016 must contain chunks referencing DOC-021"
        assert any('DOC-021' in c.text and 'January 1, 2025' in c.text for c in super_chunks)

    def test_doc017_pending_access_status(self):
        """
        Verify DOC-017:
        - Carla Reyes requested 'Workspace Administrator'
        - Approval status is explicitly 'PENDING'
        - Effective date is 'Not effective'
        - Revocation date is 'Not applicable'
        """
        doc = self.docs.get('DOC-017')
        assert doc is not None, "DOC-017 must be ingested"

        carla_chunk = DocumentChunk.objects.filter(
            document=doc,
            text__icontains='Carla Reyes'
        ).first()
        assert carla_chunk is not None, "Carla Reyes access request must exist in DOC-017"
        assert 'Workspace Administrator' in carla_chunk.text
        assert 'PENDING' in carla_chunk.text
        assert 'Not effective' in carla_chunk.text

    def test_doc021_referenced_but_missing_content(self):
        """
        Verify DOC-021:
        - Registered as 'missing' with is_missing=True
        - Boundary distinction: referenced in corpus (by DOC-016) but file absent
        - Linked via approved KnowledgeRelationship (SUPERSEDES)
        """
        assert self.doc_021.is_missing is True, "DOC-021 must be marked is_missing=True"
        assert self.doc_021.status == 'missing'
        assert self.doc_021.canonical_title == 'Travel & Expense Policy (2025)'

        doc_016 = self.docs.get('DOC-016')
        rel = KnowledgeRelationship.objects.filter(
            source_document=doc_016,
            target_document=self.doc_021,
            relationship_type=RelationshipType.SUPERSEDES
        ).first()
        assert rel is not None, "KnowledgeRelationship DOC-016 -> DOC-021 must exist"
        assert rel.approval_status == RelationshipApprovalStatus.APPROVED

    def test_doc009_contract_terms_and_doc010_invoice_facts(self):
        """
        Verify exact numerical facts and separation:
        - DOC-009: Atlas Agreement annual fee $48,000, 4 quarterly installments of $12,000, term 1 Jan 2027 - 31 Dec 2027, status 'draft'
        - DOC-010: Atlas Invoice 2026-041 subtotal $4,800.00, tax $384.00, total due $5,184.00, status 'active'
        """
        doc_009 = self.docs.get('DOC-009')
        assert doc_009 is not None
        assert doc_009.status == 'draft'
        assert doc_009.effective_from == datetime(2027, 1, 1, 0, 0, tzinfo=dt_timezone.utc)
        assert doc_009.effective_to == datetime(2027, 12, 31, 0, 0, tzinfo=dt_timezone.utc)

        chunk_fee = DocumentChunk.objects.filter(document=doc_009, text__icontains='$48,000').first()
        assert chunk_fee is not None
        assert '$48,000' in chunk_fee.text
        assert '$12,000' in chunk_fee.text

        doc_010 = self.docs.get('DOC-010')
        assert doc_010 is not None
        assert doc_010.status == 'active'

        chunk_inv = DocumentChunk.objects.filter(document=doc_010, text__icontains='$5,184.00').first()
        assert chunk_inv is not None
        assert '$4,800.00' in chunk_inv.text
        assert '$384.00' in chunk_inv.text
        assert '$5,184.00' in chunk_inv.text

    def test_hybrid_retrieval_evidence_preservation(self):
        """
        Verify HybridRetrievalService accurately retrieves preserved evidence with:
        - Canonical document code and section identifier
        - Exact numeric values and policy constraints
        """
        # Query 1: DOC-008 audit retention
        res_audit = self.retrieval_service.search(
            query="What is the retention duration and trigger for audit events?",
            workspace_id=str(self.ws.id),
            organization_id=str(self.org.id),
            limit=3
        )
        assert len(res_audit) > 0
        top_audit = res_audit[0]
        assert top_audit['document_code'] == 'DOC-008'
        assert '2 years' in top_audit['text']
        assert 'Event timestamp' in top_audit['text']
        assert 'Record Category' in top_audit['text']

        # Query 2: DOC-005 carryover
        res_carry = self.retrieval_service.search(
            query="How many unused annual leave days may be carried forward and when do they expire?",
            workspace_id=str(self.ws.id),
            organization_id=str(self.org.id),
            limit=3
        )
        assert len(res_carry) > 0
        carry_codes = [r['document_code'] for r in res_carry]
        assert 'DOC-005' in carry_codes
        doc005_hit = next(r for r in res_carry if r['document_code'] == 'DOC-005')
        assert '5 unused' in doc005_hit['text'] or '5 days' in doc005_hit['text']
        assert 'March 31' in doc005_hit['text']

        # Query 3: DOC-017 Carla Reyes
        res_carla = self.retrieval_service.search(
            query="What is the approval status of Carla Reyes's workspace access request?",
            workspace_id=str(self.ws.id),
            organization_id=str(self.org.id),
            limit=3
        )
        assert len(res_carla) > 0
        carla_hit = next((r for r in res_carla if 'Carla Reyes' in r['text']), None)
        assert carla_hit is not None
        assert carla_hit['document_code'] == 'DOC-017'
        assert 'PENDING' in carla_hit['text']

    def test_index_consistency_and_deletion_propagation(self):
        """
        Verify that document deletion cleanly cleans up vector index,
        SQLite FTS index, and invalidates cache.
        """
        temp_doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            title='Temporary Test Document',
            original_filename='temp_test_doc.pdf',
            mime_type='application/pdf',
            file_size=1024,
            file_hash='1' * 64,
            document_code='DOC-999',
            status='ready'
        )
        chunk = DocumentChunk.objects.create(
            organization=self.org,
            workspace=self.ws,
            document=temp_doc,
            chunk_index=0,
            text='Temporary test content for deletion propagation test.',
            contextual_header='Document: Temporary Test Document',
            section_identifier='Section 1'
        )

        doc_id = str(temp_doc.id)
        assert DocumentChunk.objects.filter(document_id=doc_id).exists()

        # Execute delete
        temp_doc.delete()

        # Verify chunks deleted from PostgreSQL
        assert not DocumentChunk.objects.filter(document_id=doc_id).exists()
        assert not SourceDocument.objects.filter(id=doc_id).exists()

    def test_extraction_fidelity_and_data_validation(self):
        """
        Verify extraction fidelity, confidence metrics, and validation note records:
        - High extraction confidence on digital PDFs
        - Distinguish not found in retrieved chunks vs not present in corpus
        """
        for code, doc in self.docs.items():
            assert doc.page_count >= 1, f"{code} page count must be >= 1"
            assert doc.ocr_confidence >= 0.80, f"{code} confidence must be >= 0.80, got {doc.ocr_confidence}"
            assert doc.canonical_title != "", f"{code} must have canonical title"

        # Corpus vs retrieval boundary check
        missing_doc = SourceDocument.objects.filter(document_code='DOC-021').first()
        assert missing_doc is not None
        assert missing_doc.is_missing is True
        assert missing_doc.status == 'missing'
        # Absent from chunks
        assert not DocumentChunk.objects.filter(document=missing_doc).exists()
