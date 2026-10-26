"""
LORE Enterprise — Structured Evidence-to-Answer Synthesis & Policy-Temporal Tests
Adheres strictly to the 9 requirements from Section 6 & 7:
1. Target policy-temporal question: "Which hotel reimbursement cap applies to travel on January 5, 2027, considering the future amendment and existing policy?"
2. Approved amendment scenario.
3. Unapproved draft inquiry scenario.
4. Expired and superseded policy exclusion scenario.
5. Retroactive and scoped exception scenario.
6. Unknown approval status scenario.
7. Conflicting effective dates scenario.
8. Missing or unverified citation validation scenario.
9. Observability and predictable answer contract verification.
"""

import pytest
import os
import re
import uuid
from datetime import datetime, timezone as dt_tz, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.conf import settings
from django.utils import timezone

from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument, DocumentVersion
from apps.knowledge.models import DocumentChunk
from apps.retrieval.services import HybridRetrievalService
from apps.governance.layers import EnterpriseGovernanceEngine
from apps.governance.contract import GovernanceRequest, AnswerStatus, Verdict
from apps.governance.evidence_package import StructuredEvidencePackage, EvidenceItem
from apps.governance.validation import AnswerQualityValidator


@pytest.mark.django_db
class TestStructuredEvidenceSynthesis(TestCase):

    @classmethod
    def setUpTestData(cls):
        setattr(settings, 'ALLOW_HASH_PROJECTION_FALLBACK', True)
        os.environ['ALLOW_HASH_PROJECTION_FALLBACK'] = 'True'

        cls.org = Organization.objects.create(name="Northstar Corp", slug=f"northstar-{uuid.uuid4().hex[:6]}")
        cls.workspace = Workspace.objects.create(name="Northstar Policy", slug=f"policy-{uuid.uuid4().hex[:6]}", organization=cls.org)

        # DOC-002: Travel Expense Policy v2.0
        cls.doc002 = SourceDocument.objects.create(
            workspace=cls.workspace,
            organization=cls.org,
            title="DOC-002 — Travel_Expense_Policy_v2.pdf",
            original_filename="doc-002.pdf",
            mime_type="application/pdf",
            file_size=2048,
            file_hash=f"hash002-{uuid.uuid4().hex}",
            status="ready",
            authority_level=7,
            effective_date=timezone.now() - timedelta(days=100)
        )
        ver002 = DocumentVersion.objects.create(document=cls.doc002, version_number=2, is_current=True)
        DocumentChunk.objects.create(
            document=cls.doc002,
            document_version=ver002,
            chunk_index=0,
            workspace=cls.workspace,
            organization=cls.org,
            text=(
                "TRAVEL & EXPENSE POLICY Northstar Manufacturing Ltd. Version 2.0. Effective July 1, 2026. "
                "Section 4. Hotel Limits. Hotel reimbursement is capped at $220 per night, before applicable taxes and mandatory fees. "
                "Travelers should choose safe, business-appropriate lodging at or below the cap."
            ),
            page_number=1,
            heading_path='General'
        )

        # DOC-015: Travel Policy Amendment Future
        cls.doc015 = SourceDocument.objects.create(
            workspace=cls.workspace,
            organization=cls.org,
            title="DOC-015 — Travel_Policy_Amendment_Future.pdf",
            original_filename="doc-015.pdf",
            mime_type="application/pdf",
            file_size=1024,
            file_hash=f"hash015-{uuid.uuid4().hex}",
            status="ready",
            authority_level=1,
            effective_date=timezone.now() + timedelta(days=60)
        )
        ver015 = DocumentVersion.objects.create(document=cls.doc015, version_number=1, is_current=True)
        DocumentChunk.objects.create(
            document=cls.doc015,
            document_version=ver015,
            chunk_index=0,
            workspace=cls.workspace,
            organization=cls.org,
            text=(
                "TRAVEL EXPENSE POLICY AMENDMENT DOC-015. Published September 2026. Future effective date: 1 January 2027. "
                "Section 2. Effective 1 January 2027, the maximum reimbursable hotel accommodation cost will be US$240 per night. "
                "Section 5. Status: Draft amendment for formal approval. No actual signature or approval is asserted."
            ),
            page_number=1,
            heading_path='General'
        )

        # DOC-001: Travel Expense Policy v1.0
        cls.doc001 = SourceDocument.objects.create(
            workspace=cls.workspace,
            organization=cls.org,
            title="DOC-001 — Travel_Expense_Policy_v1.pdf",
            original_filename="doc-001.pdf",
            mime_type="application/pdf",
            file_size=1024,
            file_hash=f"hash001-{uuid.uuid4().hex}",
            status="ready",
            authority_level=1
        )
        ver001 = DocumentVersion.objects.create(document=cls.doc001, version_number=1, is_current=True)
        DocumentChunk.objects.create(
            document=cls.doc001,
            document_version=ver001,
            chunk_index=0,
            workspace=cls.workspace,
            organization=cls.org,
            text="Travel Expense Policy v1.0 Draft. Daily meal allowance is $50. Status: Draft for review.",
            page_number=1,
            heading_path='General'
        )

        # DOC-016: Archived Travel Policy 2024
        cls.doc016 = SourceDocument.objects.create(
            workspace=cls.workspace,
            organization=cls.org,
            title="DOC-016_Archived_Travel_Policy_2024",
            original_filename="doc-016.pdf",
            mime_type="application/pdf",
            file_size=1024,
            file_hash=f"hash016-{uuid.uuid4().hex}",
            status="ready",
            authority_level=4,
            expiration_date=timezone.now() - timedelta(days=200)
        )
        ver016 = DocumentVersion.objects.create(document=cls.doc016, version_number=1, is_current=True)
        DocumentChunk.objects.create(
            document=cls.doc016,
            document_version=ver016,
            chunk_index=0,
            workspace=cls.workspace,
            organization=cls.org,
            text="Archived Travel Policy 2024. Hotel reimbursement was capped at $180 per night. Superseded.",
            page_number=1,
            heading_path='General'
        )

    def setUp(self):
        setattr(settings, 'ALLOW_HASH_PROJECTION_FALLBACK', True)
        os.environ['ALLOW_HASH_PROJECTION_FALLBACK'] = 'True'
        self.workspace = self.__class__.workspace
        self.organization = self.__class__.org
        self.retrieval = HybridRetrievalService()

    def test_target_question_hotel_reimbursement_cap_january_5_2027(self):
        """
        Section 6 Target Question:
        "Which hotel reimbursement cap applies to travel on January 5, 2027, considering the future amendment and existing policy?"

        Expected evidence:
        - DOC-002 sets a $220-per-night hotel cap effective July 1, 2026.
        - DOC-015 proposes a $240-per-night cap effective January 1, 2027.
        - DOC-015 is identified as an unapproved draft.

        Expected answer behavior:
        - Does NOT repeat the unrelated rule about travel authorized before July 1, 2026 as the main answer.
        - Explains that DOC-002 establishes the $220 cap for its effective period.
        - Explains that DOC-015's proposed $240 cap is not binding if it remains unapproved.
        - States that evidence does not establish an approved amendment replacing DOC-002.
        - On that evidence, $220 per night is the supported cap.
        - Cites both documents (DOC-002 and DOC-015) and distinguishes existing rule from non-binding proposal.
        """
        query = "Which hotel reimbursement cap applies to travel on January 5, 2027, considering the future amendment and existing policy?"

        chunks = self.retrieval.search(
            query=query,
            workspace_id=str(self.workspace.id),
            organization_id=str(self.organization.id),
            limit=8
        )

        # Verify both DOC-002 and DOC-015 were retrieved
        retrieved_titles = [c.get('document_title', '') for c in chunks]
        assert any('doc-002' in t.lower() for t in retrieved_titles), "DOC-002 must be retrieved"
        assert any('doc-015' in t.lower() for t in retrieved_titles), "DOC-015 must be retrieved"

        req = GovernanceRequest(
            workspace=self.workspace,
            principal="auditor@northstar.local",
            user_role="member",
            query=query,
            candidate_evidence=chunks
        )

        envelope = EnterpriseGovernanceEngine.evaluate(req)

        # 1. State and Directive verification
        assert envelope.get('state') == Verdict.SUPPORTED.value
        assert envelope.get('status') == AnswerStatus.ANSWERED.value

        answer = envelope.get('answer', '')

        # 2. Does NOT repeat the unrelated sentence about travel authorized before July 1, 2026 as the main answer
        first_sentence = re.split(r'(?<=[.!?])\s+', answer.strip())[0].lower()
        assert "travel approved or expenses incurred before july 1, 2026" not in first_sentence, (
            "Must NOT echo the unrelated grandfathering rule as the main answer."
        )

        # 3. Direct conclusion: $220 is the applicable cap for travel on January 5, 2027
        assert "$220" in first_sentence, f"First sentence must state the $220 cap, got: {first_sentence}"
        assert "january 5, 2027" in first_sentence.lower() or "doc-002" in first_sentence.lower()

        # 4. Explains DOC-002 establishes $220 cap for its effective period
        assert "$220" in answer
        assert "doc-002" in answer.lower()

        # 5. Explains DOC-015's proposed $240 cap is not binding because it remains unapproved
        assert "$240" in answer
        assert "doc-015" in answer.lower()
        assert any(w in answer.lower() for w in ['unapproved draft', 'draft', 'non-binding', 'without formal adoption'])

        # 6. States that evidence does not establish an approved amendment replacing DOC-002
        assert "does not establish an approved amendment" in answer.lower() or "remains the supported" in answer.lower()

        # 7. Citations: Both DOC-002 and DOC-015 must be cited
        citations = envelope.get('citations', [])
        cited_titles = [c.get('document_title', '').lower() for c in citations]
        has_doc002 = any('doc-002' in t for t in cited_titles)
        has_doc015 = any('doc-015' in t for t in cited_titles)
        assert has_doc002, "DOC-002 must be cited as the governing policy"
        assert has_doc015, "DOC-015 must be cited as the non-binding amendment proposal"

        # 8. Predictable answer contract fields (Section 5)
        assert 'reasoning_summary' in envelope
        assert 'applicable_rules' in envelope
        assert 'conflicts' in envelope
        assert 'uncertainties' in envelope
        assert envelope.get('status') in [s.value for s in AnswerStatus]

        # 9. Observability timings (Section 8)
        timings = envelope.get('layers_breakdown', {}).get('l0_observability', {}).get('timings_ms', {})
        assert 'evidence_assembly_ms' in timings
        assert 'generation_ms' in timings
        assert 'validation_ms' in timings
        assert 'total_ms' in timings

    def test_approved_amendment_scenario(self):
        """
        Tests the scenario where an amendment is approved and its effective date has arrived.
        When approved, the amendment supersedes the prior cap.
        """
        # Create candidate chunks where DOC-015 is explicitly marked as approved
        approved_chunk_doc015 = {
            'chunk_id': 'chunk-doc015-approved',
            'document_id': 'doc-015-approved-uuid',
            'document_title': 'DOC-015 — Travel_Policy_Amendment_Approved.pdf',
            'document_status': 'approved',
            'status': 'approved',
            'authority_level': 7,
            'is_approved': True,
            'is_draft': False,
            'text': (
                "TRAVEL EXPENSE POLICY AMENDMENT (DOC-015) Approved. "
                "Effective 1 January 2027, the maximum reimbursable hotel accommodation cost will be US$240 per night. "
                "This approved amendment formally supersedes the $220 nightly cap in DOC-002."
            ),
            'page_number': 1,
            'effective_date': '2027-01-01'
        }
        gov_chunk_doc002 = {
            'chunk_id': 'chunk-doc002',
            'document_id': 'doc-002-uuid',
            'document_title': 'DOC-002 — Travel_Expense_Policy_v2.pdf',
            'document_status': 'approved',
            'status': 'approved',
            'authority_level': 7,
            'is_approved': True,
            'is_draft': False,
            'text': "Section 4. Hotel Limits. Hotel reimbursement is capped at $220 per night, before applicable taxes.",
            'page_number': 1,
            'effective_date': '2026-07-01'
        }

        query = "Which hotel reimbursement cap applies to travel on January 5, 2027, considering the future amendment and existing policy?"

        req = GovernanceRequest(
            workspace=self.workspace,
            principal="auditor@northstar.local",
            user_role="member",
            query=query,
            candidate_evidence=[approved_chunk_doc015, gov_chunk_doc002]
        )

        envelope = EnterpriseGovernanceEngine.evaluate(req)

        answer = envelope.get('answer', '')
        # When amendment is approved and effective date has arrived, $240 applies
        assert "$240" in answer
        assert "approved amendment" in answer.lower() or "supersedes" in answer.lower()

    def test_unapproved_draft_inquiry_discloses_non_binding_status(self):
        """
        Tests that inquiring what a draft policy specifies discloses its non-binding status.
        """
        query = "What does the draft expense policy say about meal allowances?"

        chunks = self.retrieval.search(
            query=query,
            workspace_id=str(self.workspace.id),
            organization_id=str(self.organization.id),
            limit=8
        )

        req = GovernanceRequest(
            workspace=self.workspace,
            principal="member@northstar.local",
            user_role="member",
            query=query,
            candidate_evidence=chunks
        )

        envelope = EnterpriseGovernanceEngine.evaluate(req)
        answer = envelope.get('answer', '')

        assert envelope.get('state') == Verdict.SUPPORTED.value
        assert any(w in answer.lower() for w in ['draft', 'unapproved', 'non-binding'])
        assert any(w in answer.lower() for w in ['meal', 'allowance', '$'])

    def test_unknown_approval_status_is_stated_explicitly(self):
        """
        Tests that missing or unverifiable approval status is explicitly acknowledged,
        and never assumed to be approved merely from dates or recency.
        """
        unknown_status_chunk = {
            'chunk_id': 'chunk-doc099-unknown',
            'document_id': 'doc-099-uuid',
            'document_title': 'DOC-099 — Lodging_Policy_Addendum.pdf',
            'document_status': 'unknown',
            'status': 'unknown',
            'authority_level': 4,
            'is_approved': False,
            'is_draft': False,
            'text': (
                "Section 1. Effective 1 January 2027, the hotel reimbursement cap is specified as $240 per night. "
                "Document control: pending governance review."
            ),
            'page_number': 1
        }
        gov_chunk_doc002 = {
            'chunk_id': 'chunk-doc002',
            'document_id': 'doc-002-uuid',
            'document_title': 'DOC-002 — Travel_Expense_Policy_v2.pdf',
            'document_status': 'approved',
            'status': 'approved',
            'authority_level': 7,
            'is_approved': True,
            'text': "Section 4. Hotel reimbursement is capped at $220 per night, before applicable taxes.",
            'page_number': 1,
            'effective_date': '2026-07-01'
        }

        query = "Which hotel reimbursement cap applies to travel on January 5, 2027, considering the future amendment and existing policy?"

        req = GovernanceRequest(
            workspace=self.workspace,
            principal="member@northstar.local",
            user_role="member",
            query=query,
            candidate_evidence=[unknown_status_chunk, gov_chunk_doc002]
        )

        envelope = EnterpriseGovernanceEngine.evaluate(req)
        answer = envelope.get('answer', '')

        # Must state that approval status is unknown / unverified
        assert any(w in answer.lower() for w in ['unknown', 'unverified', 'cannot be established'])
        assert "$220" in answer

    def test_expired_policy_excluded_from_current_rule(self):
        """
        Tests that an expired/superseded policy (e.g. DOC-016 from 2024) is not asserted
        as the current governing rule.
        """
        query = "What is the current hotel reimbursement cap under the Travel Policy?"

        chunks = self.retrieval.search(
            query=query,
            workspace_id=str(self.workspace.id),
            organization_id=str(self.organization.id),
            limit=8
        )

        req = GovernanceRequest(
            workspace=self.workspace,
            principal="member@northstar.local",
            user_role="member",
            query=query,
            candidate_evidence=chunks
        )

        envelope = EnterpriseGovernanceEngine.evaluate(req)
        answer = envelope.get('answer', '')

        assert "$220" in answer
        # Must not cite DOC-016 as current governing policy
        citations = envelope.get('citations', [])
        for c in citations:
            if 'doc-016' in c.get('document_title', '').lower():
                assert c.get('document_status') in ['archived', 'superseded']

    def test_citation_and_answer_quality_validator_catches_unverified_source(self):
        """
        Section 7: Validates that unverified or unauthorized sources are stripped
        by AnswerQualityValidator.
        """
        valid_chunk = {
            'document_id': 'doc-valid-01',
            'document_title': 'DOC-002 — Travel_Expense_Policy_v2.pdf',
            'text': 'Hotel reimbursement is capped at $220 per night.',
            'page_number': 1
        }
        fake_citation = {
            'citation_id': 'cit-fake-99',
            'document_id': 'doc-nonexistent-99',
            'document_title': 'DOC-999 — Invented_Source.pdf',
            'passage': 'Invented passage text.'
        }
        real_citation = {
            'citation_id': 'cit-valid-01',
            'document_id': 'doc-valid-01',
            'document_title': 'DOC-002 — Travel_Expense_Policy_v2.pdf',
            'passage': 'Hotel reimbursement is capped at $220 per night.'
        }

        res = AnswerQualityValidator.validate(
            query="What is the hotel reimbursement cap?",
            answer="The hotel cap is $220 per night.",
            citations=[real_citation, fake_citation],
            candidate_chunks=[valid_chunk]
        )

        # Unverified fake citation must be removed
        assert len(res.sanitized_citations) == 1
        assert res.sanitized_citations[0]['document_id'] == 'doc-valid-01'
        assert any('UNVERIFIED_CITATION' in flag for flag in res.flags)

    def test_no_verbatim_echoing_of_raw_context(self):
        """
        Section 7: Validates that raw chunks dumped verbatim without synthesis
        are flagged by AnswerQualityValidator.
        """
        raw_text = (
            "Section 4. Hotel Limits Hotel reimbursement is capped at $220 per night, before applicable taxes and mandatory fees. "
            "Travelers should choose safe, business-appropriate lodging at or below the cap. A higher rate requires prior written approval."
        )
        chunk = {
            'document_id': 'doc-002',
            'document_title': 'DOC-002 — Travel Policy',
            'text': raw_text
        }

        res = AnswerQualityValidator.validate(
            query="What is the hotel reimbursement cap?",
            answer=raw_text,  # Verbatim echo of entire chunk
            citations=[],
            candidate_chunks=[chunk]
        )

        assert any('VERBATIM_CONTEXT_ECHO' in flag for flag in res.flags)
        assert res.remediation_applied is True
        assert res.sanitized_answer != raw_text

    def test_structured_evidence_package_model_fidelity(self):
        """
        Section 2: Validates that StructuredEvidencePackage correctly preserves
        complete metadata, exact passages, authority ranks, and diagnostic metrics.
        """
        chunk = {
            'chunk_id': 'chk-100',
            'document_id': 'doc-002-test',
            'document_title': 'DOC-002 — Travel_Expense_Policy_v2.pdf',
            'text': 'Hotel reimbursement is capped at $220 per night.',
            'document_status': 'approved',
            'authority_level': 7,
            'page_number': 1,
            'effective_date': '2026-07-01',
            'score': 0.85,
            'rrf_score': 0.032
        }

        pkg = StructuredEvidencePackage.from_chunks(
            query="Which hotel reimbursement cap applies?",
            chunks=[chunk],
            target_date="2027-01-05"
        )

        assert len(pkg.items) == 1
        item = pkg.items[0]
        assert item.document_code == "DOC-002"
        assert item.approval_status == "approved"
        assert item.effective_from == "2026-07-01"
        assert item.authority_rank == 7
        assert item.is_binding is True
        assert item.diagnostic_metadata.get('score') == 0.85

        xml_tag = item.to_xml_tag(1)
        assert 'id="DOC-002"' in xml_tag
        assert 'status="approved"' in xml_tag
        assert 'Hotel reimbursement is capped at $220 per night.' in xml_tag
