import pytest
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone
from apps.governance.contract import GovernanceRequest
from apps.governance.models import SourcePermission, AccessLevel
from apps.governance.layers import EnterpriseGovernanceEngine, PermissionLayer
from apps.governance.evidence import EvidencePresentationEngine
from apps.retrieval.services import ContextReranker, HybridRetrievalService


# ==============================================================================
# RETRIEVAL-TO-EVIDENCE PIPELINE AUDIT TEST SUITE
# Covers all 7 required scenarios from audit specification:
# 1. Duplicate chunks from one policy (retaining strongest provenance)
# 2. A current policy plus a draft version (caveats, non-binding isolation)
# 3. A current policy plus a future amendment (caveats, temporal isolation)
# 4. A question explicitly asking about an older version (answering from specified version)
# 5. A question requiring several values from one table (multi-value preservation)
# 6. A workspace with inaccessible documents (L7 permission filtering before synthesis)
# 7. A query where the most semantically similar chunk is not the authoritative one
# ==============================================================================


class TestRetrievalToEvidencePipeline:

    def test_duplicate_chunks_from_one_policy_retains_strongest_provenance(self):
        """
        Requirement 4:
        Deduplicate identical and overlapping chunks while retaining the strongest
        source location and provenance.
        """
        # Chunk 1 has higher score but missing page number and generic heading
        chunk_weak_provenance = {
            'chunk_id': 'chk-001',
            'document_id': 'doc-travel-policy',
            'document_title': 'Corporate Travel & Expense Policy',
            'authority_level': 5,
            'page_number': None,
            'heading_path': 'General',
            'text': 'The standard daily meal allowance for domestic business travel is $50 per day.',
            'score': 0.88
        }
        # Chunk 2 has slightly lower score but strong provenance: page 14, specific heading
        chunk_strong_provenance = {
            'chunk_id': 'chk-002',
            'document_id': 'doc-travel-policy',
            'document_title': 'Corporate Travel & Expense Policy',
            'authority_level': 5,
            'page_number': 14,
            'heading_path': 'Section 3.2 > Meal & Incidental Allowances',
            'text': 'The standard daily meal allowance for domestic business travel is $50 per day.',
            'score': 0.85
        }

        # Deduplicate through EvidencePresentationEngine
        deduped = EvidencePresentationEngine._deduplicate_chunks([chunk_weak_provenance, chunk_strong_provenance])

        # Must collapse into exactly 1 chunk
        assert len(deduped) == 1
        retained = deduped[0]
        # Strongest provenance must be preserved: page 14 and specific heading
        assert retained.get('page_number') == 14
        assert retained.get('heading_path') == 'Section 3.2 > Meal & Incidental Allowances'

    def test_current_policy_plus_draft_version(self):
        """
        Requirements 3, 7, 9:
        Current policy plus a draft version:
        - The approved current policy ($50) answers the operational question.
        - The draft version ($65) is cited strictly as a material caveat, not binding policy.
        - The draft does not override the current policy regardless of similarity.
        """
        chunk_current = {
            'chunk_id': 'chk-current',
            'document_id': 'doc-001-current',
            'document_title': 'Travel Policy 2024 (Approved)',
            'document_status': 'approved',
            'authority_level': 5,
            'page_number': 4,
            'text': 'The current approved daily meal allowance for employees is $50.',
            'score': 0.82
        }
        chunk_draft = {
            'chunk_id': 'chk-draft',
            'document_id': 'doc-002-draft',
            'document_title': 'Travel Policy Amendment 2025 (Draft)',
            'document_status': 'draft',
            'is_draft': True,
            'authority_level': 5,
            'page_number': 2,
            'text': 'Draft Proposal: Proposed daily meal allowance is $65.',
            'score': 0.95 # Higher semantic similarity must NOT override approved policy
        }

        req = GovernanceRequest(
            workspace="ws-test",
            organization="org-test",
            query="What is the daily meal allowance for employees?",
            candidate_evidence=[chunk_current, chunk_draft]
        )
        res = EnterpriseGovernanceEngine.evaluate(req)

        assert res.get('state') == 'supported'
        ans = res.get('answer') or res.get('answer_text', '')
        # Primary answer must state the approved current rate ($50)
        assert '$50' in ans
        # Draft is mentioned strictly as a non-binding caveat
        assert 'Draft' in ans or 'draft' in ans
        assert 'non-binding' in ans.lower() or 'proposes' in ans.lower()

        # Primary citation must be the approved current document
        citations = res.get('citations', [])
        assert len(citations) >= 1
        assert citations[0]['document_id'] == 'doc-001-current'
        assert citations[0]['document_status'] == 'approved'

    def test_current_policy_plus_future_amendment(self):
        """
        Requirements 3, 5, 7:
        Current policy plus a future amendment:
        - The current policy ($50) governs current operations.
        - Future amendment ($70, effective 2027) is preserved as a material caveat.
        - Future amendment is not applied prior to its effective date.
        """
        chunk_current = {
            'chunk_id': 'chk-curr',
            'document_id': 'doc-curr',
            'document_title': 'POL-EXP-001: Travel & Expense Standard',
            'document_status': 'approved',
            'authority_level': 5,
            'page_number': 6,
            'effective_date': '2024-01-01',
            'text': 'Employees are authorized a daily meal per diem of $50.',
            'score': 0.85
        }
        chunk_future = {
            'chunk_id': 'chk-fut',
            'document_id': 'doc-fut',
            'document_title': 'POL-EXP-001-AMEND: Travel Allowance Update 2027',
            'document_status': 'future-effective',
            'is_future_effective': True,
            'authority_level': 5,
            'page_number': 1,
            'effective_date': '2027-01-01',
            'text': 'Effective January 1, 2027, the daily meal per diem increases to $70.',
            'score': 0.92
        }

        now_2026 = datetime(2026, 6, 15, tzinfo=dt_timezone.utc)
        req = GovernanceRequest(
            workspace="ws-test",
            organization="org-test",
            query="What is the current meal allowance?",
            candidate_evidence=[chunk_current, chunk_future],
            as_of=now_2026
        )
        res = EnterpriseGovernanceEngine.evaluate(req)

        assert res.get('state') == 'supported'
        ans = res.get('answer') or res.get('answer_text', '')
        # Primary answer states the current operational per diem ($50)
        assert '$50' in ans
        # Material future-effective caveat disclosed
        assert '2027' in ans
        assert '$70' in ans

    def test_question_explicitly_asking_about_older_version(self):
        """
        Requirement 7:
        For a question about one document's content, answer from that document when
        the question explicitly specifies it. Use other versions only to explain
        relevant caveats or differences.
        """
        chunk_v1 = {
            'chunk_id': 'chk-v1',
            'document_id': 'doc-travel-v1',
            'document_title': 'Travel Policy (v1.0)',
            'document_version': 1,
            'document_status': 'superseded',
            'is_superseded': True,
            'authority_level': 5,
            'page_number': 3,
            'text': 'Under Version 1.0, the maximum daily meal allowance was $40 per day.',
            'score': 0.86
        }
        chunk_v2 = {
            'chunk_id': 'chk-v2',
            'document_id': 'doc-travel-v2',
            'document_title': 'Travel Policy (v2.0)',
            'document_version': 2,
            'document_status': 'approved',
            'authority_level': 5,
            'page_number': 3,
            'text': 'Version 2.0 supersedes Version 1.0 and increases the daily meal allowance to $50 per day.',
            'score': 0.84
        }

        # Query explicitly specifies version 1
        query = "What was the meal allowance in version 1 of the Travel Policy?"
        req = GovernanceRequest(
            workspace="ws-test",
            organization="org-test",
            query=query,
            candidate_evidence=[chunk_v1, chunk_v2]
        )
        res = EnterpriseGovernanceEngine.evaluate(req)

        assert res.get('state') in ('supported', 'qualified')
        ans = res.get('answer') or res.get('answer_text', '')
        # First sentence answers directly from version 1 ($40)
        import re
        first_sentence = re.split(r'\.\s+', ans)[0]
        assert '$40' in first_sentence
        # Version 2 is mentioned as a subsequent difference / update note
        assert 'version 2' in ans.lower()
        assert '$50' in ans

    def test_question_requiring_several_values_from_one_table(self):
        """
        Requirements 1, 4, 5, 8:
        A question requiring several values from one table:
        - Deduplication does not discard distinct passages proving different values.
        - All requested values (breakfast $15, lunch $25, dinner $45) are collected and returned.
        - Primary and secondary citations cover all distinct requested facts.
        """
        chunk_breakfast = {
            'chunk_id': 'chk-table-b',
            'document_id': 'doc-travel-table',
            'document_title': 'Travel Policy Meal Allowance Schedule',
            'authority_level': 5,
            'page_number': 5,
            'heading_path': 'Schedule A > Meal Rates',
            'text': 'Itemized Meal Rates Schedule: The breakfast allowance is $15.',
            'score': 0.85
        }
        chunk_lunch = {
            'chunk_id': 'chk-table-l',
            'document_id': 'doc-travel-table',
            'document_title': 'Travel Policy Meal Allowance Schedule',
            'authority_level': 5,
            'page_number': 5,
            'heading_path': 'Schedule A > Meal Rates',
            'text': 'Itemized Meal Rates Schedule: The lunch allowance is $25.',
            'score': 0.84
        }
        chunk_dinner = {
            'chunk_id': 'chk-table-d',
            'document_id': 'doc-travel-table',
            'document_title': 'Travel Policy Meal Allowance Schedule',
            'authority_level': 5,
            'page_number': 5,
            'heading_path': 'Schedule A > Meal Rates',
            'text': 'Itemized Meal Rates Schedule: The dinner allowance is $45.',
            'score': 0.83
        }

        query = "What are the breakfast, lunch, and dinner meal allowances under the Travel Policy?"
        req = GovernanceRequest(
            workspace="ws-test",
            organization="org-test",
            query=query,
            candidate_evidence=[chunk_breakfast, chunk_lunch, chunk_dinner]
        )
        res = EnterpriseGovernanceEngine.evaluate(req)

        assert res.get('state') == 'supported'
        ans = res.get('answer') or res.get('answer_text', '')
        # First sentence must return every requested value
        assert '$15' in ans
        assert '$25' in ans
        assert '$45' in ans

        # Curated citations must keep the distinct passages proving each value
        citations = res.get('citations', [])
        assert len(citations) >= 1
        all_citation_text = " ".join(c.get('passage', '') for c in citations)
        assert '$15' in all_citation_text
        assert '$25' in all_citation_text
        assert '$45' in all_citation_text

    @pytest.mark.django_db
    def test_workspace_with_inaccessible_documents(self):
        """
        Requirement 10:
        Preserve permission filtering before evidence reaches the answer generator.
        When a workspace has inaccessible restricted documents, they are gated out
        at L7 before reaching temporal, authority, synthesis, or citations.
        """
        import uuid
        from apps.sources.models import SourceDocument
        from apps.identity.models import Organization
        from apps.workspaces.models import Workspace
        from django.contrib.auth.models import User

        org = Organization.objects.create(name="Perm Org", slug=f"perm-org-{uuid.uuid4().hex[:6]}")
        ws = Workspace.objects.create(organization=org, name="Perm WS", slug=f"perm-ws-{uuid.uuid4().hex[:6]}")
        member_user = User.objects.create_user(username=f"member_audit_{uuid.uuid4().hex[:6]}", password="password")

        # Document 1: Public operational policy
        doc_public = SourceDocument.objects.create(
            organization=org, workspace=ws, title="General IT Handbook",
            original_filename="handbook.pdf", mime_type="application/pdf",
            file_size=1024, file_hash=f"hash-pub-{uuid.uuid4().hex[:6]}",
            status="ready", authority_level=4
        )
        # Document 2: Restricted Executive Compensation (Admin only)
        doc_restricted = SourceDocument.objects.create(
            organization=org, workspace=ws, title="Executive Compensation Confidential",
            original_filename="exec.pdf", mime_type="application/pdf",
            file_size=2048, file_hash=f"hash-res-{uuid.uuid4().hex[:6]}",
            status="ready", authority_level=7
        )
        SourcePermission.objects.create(
            document=doc_restricted,
            access_level=AccessLevel.RESTRICTED,
            allowed_roles=["workspace_admin"]
        )

        cand_public = {
            'document_id': str(doc_public.id),
            'document_title': doc_public.title,
            'authority_level': 4,
            'text': 'All employees receive standard IT equipment including a company laptop.',
            'score': 0.80
        }
        cand_restricted = {
            'document_id': str(doc_restricted.id),
            'document_title': doc_restricted.title,
            'authority_level': 7,
            'text': 'Confidential: Executive base salary scale exceeds $500,000 annually with 50% equity.',
            'score': 0.95
        }

        # User has role 'member' -> restricted doc must be filtered out at L7
        req = GovernanceRequest(
            workspace=ws,
            organization=org,
            principal=member_user,
            user_role="member",
            query="What is the equipment policy and executive salary?",
            candidate_evidence=[cand_public, cand_restricted]
        )
        res = EnterpriseGovernanceEngine.evaluate(req)

        # Restricted document chunks must never appear in citations or final answer
        citations = res.get('citations', [])
        assert not any(c.get('document_id') == str(doc_restricted.id) for c in citations)
        assert not any('Executive Compensation' in c.get('document_title', '') for c in citations)
        answer_text = res.get('answer') or res.get('answer_text', '')
        assert '$500,000' not in answer_text

    def test_semantically_similar_chunk_not_authoritative(self):
        """
        Requirement 9:
        Do not use similarity scores alone as proof of authority or correctness.
        When a highly similar chunk from an informal source contradicts an
        authoritative approved source with lower similarity, the authoritative source
        strictly prevails.
        """
        # Chunk A: Informal wiki / draft guideline with very high similarity (0.95), low authority (Rank 2)
        chunk_informal_high_sim = {
            'chunk_id': 'chk-wiki',
            'document_id': 'doc-wiki',
            'document_title': 'Engineering Informal Wiki Guidelines',
            'document_status': 'unknown',
            'authority_level': 2,
            'page_number': 1,
            'text': 'Customer activity logs should generally be retained for 30 days before deletion.',
            'score': 0.95 # Highly similar conversational text
        }
        # Chunk B: Formal approved policy with lower similarity (0.72), high authority (Rank 6)
        chunk_authoritative_lower_sim = {
            'chunk_id': 'chk-policy',
            'document_id': 'doc-data-retention-policy',
            'document_title': 'POL-SEC-042: Enterprise Data Retention Policy',
            'document_status': 'approved',
            'authority_level': 6,
            'page_number': 9,
            'text': 'Section 5.1: Customer activity logs must be retained for exactly 365 days to comply with statutory audit mandates.',
            'score': 0.72 # Lower similarity score
        }

        req = GovernanceRequest(
            workspace="ws-test",
            organization="org-test",
            query="What is the data retention period for customer activity logs?",
            candidate_evidence=[chunk_informal_high_sim, chunk_authoritative_lower_sim]
        )
        res = EnterpriseGovernanceEngine.evaluate(req)

        assert res.get('state') == 'supported'
        ans = res.get('answer') or res.get('answer_text', '')
        # The authoritative policy (365 days) must be the primary answer, NOT 30 days
        assert '365 days' in ans
        assert '30 days' not in ans.split('.')[0]

        # The primary citation must be the Rank 6 policy, not the Rank 2 wiki
        citations = res.get('citations', [])
        assert len(citations) >= 1
        assert citations[0]['document_id'] == 'doc-data-retention-policy'
        assert citations[0]['authority_level'] == 6
