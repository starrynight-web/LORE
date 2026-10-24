"""
LORE Enterprise — Automated Tests for Concise Answer-Generation Contract
Specification:
1. Answer user's exact question in the first sentence.
2. Put key value, decision, name, date, or comparison first.
3. Plain language and normally no more than 1–3 short sentences.
4. Return every requested value for multi-part questions (compact list/table).
5. Do not replace direct answer with generic governance warning when evidence supports it.
6. Keep policy caveats (draft vs approved, future-effective vs current).
7. If answer cannot be established, say exactly what is missing; never guess.
8. Keep internal diagnostics, token counts, layer latencies out of default answer.
9. Do not repeat the same fact in multiple paragraphs.
10. Keep underlying governance decision and audit record intact.

Validation Gate:
Compare final answer against requested facts; verify every part is answered;
downgrade to insufficient if any part is missing from evidence.
"""

import uuid
import pytest
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone
from apps.governance.layers import EnterpriseGovernanceEngine
from apps.governance.contract import Verdict, Directive, GovernanceReasonCode, EvidenceStatus
from apps.decisions.engine import GroundedGenerationService
from apps.decisions.synthesizer import ConciseAnswerSynthesizer, AnswerCompletenessValidator


@pytest.fixture
def mock_workspace(db):
    from apps.identity.models import Organization
    from apps.workspaces.models import Workspace
    org = Organization.objects.create(name="Contract Test Org", slug=f"contract-org-{uuid.uuid4().hex[:6]}")
    ws = Workspace.objects.create(name="Contract Workspace", slug=f"contract-ws-{uuid.uuid4().hex[:6]}", organization=org)
    return ws


# ==============================================================================
# 1. SINGLE-VALUE QUESTION TEST
# ==============================================================================
@pytest.mark.django_db
class TestSingleValueQuestion:
    def test_single_value_direct_answer_first_sentence(self, mock_workspace):
        """
        Requirements 1, 2, 3:
        - Answers the user's exact question in the first sentence.
        - Puts the key value (90 days) first.
        - Plain language and 1-3 short sentences.
        - Preserves source attribution and audit envelope integrity.
        """
        chunks = [
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "Enterprise Data Policy 2026",
                "document_version": 1,
                "authority_level": 6,
                "page_number": 4,
                "score": 0.95,
                "text": "Password rotation is required every 90 days for all production credentials. Passwords must be at least 16 characters long."
            }
        ]

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the password rotation interval?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="general_inquiry"
        )

        assert envelope["schema"] == "lore.result/2"
        assert envelope["state"] == Verdict.SUPPORTED.value
        assert envelope["directive"] == Directive.PROCEED_AND_CITE.value

        answer = envelope["answer"]
        sentences = [s.strip() for s in answer.split("\n")[0].split(". ") if s.strip()]

        # Sentence 1 must contain the key value and direct answer
        assert "90 days" in sentences[0]
        assert "password rotation" in sentences[0].lower() or "rotation" in sentences[0].lower()

        # Overall answer must be concise (1-3 sentences total)
        total_sentences = [s.strip() for s in answer.replace("\n", " ").split(". ") if len(s.strip()) > 5]
        assert len(total_sentences) <= 3

        # Must maintain source attribution for auditability
        assert "Enterprise Data Policy 2026" in answer

        # Must not contain governance diagnostic noise
        assert "Governance Determination" not in answer
        assert "token_count" not in answer
        assert "layer_latency" not in answer


# ==============================================================================
# 2. MULTI-VALUE QUESTION (THREE VALUES AND A TOTAL) TESTS
# ==============================================================================
@pytest.mark.django_db
class TestMultiValueAndTotalQuestion:
    def test_three_values_and_total_all_returned_with_compact_list(self, mock_workspace):
        """
        Requirement 4:
        - Returns every requested value (breakfast, lunch, dinner, and total).
        - Uses a compact list.
        - First sentence puts key values first.
        """
        chunks = [
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "Travel and Expense Policy",
                "document_version": 1,
                "authority_level": 5,
                "page_number": 2,
                "score": 0.92,
                "text": (
                    "Business travel meal allowances are as follows: Breakfast: $15. "
                    "Lunch: $25. Dinner: $45. The daily maximum allowance total is $85. "
                    "All expense claims require itemized receipts."
                )
            }
        ]

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What are the meal allowances for breakfast, lunch, and dinner, and what is the daily total?",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="general_inquiry"
        )

        assert envelope["state"] == Verdict.SUPPORTED.value
        answer = envelope["answer"]

        # All 4 requested values must be present
        assert "$15" in answer  # Breakfast
        assert "$25" in answer  # Lunch
        assert "$45" in answer  # Dinner
        assert "$85" in answer  # Daily Total

        # Must contain a compact list
        assert "- Breakfast:" in answer or "- Breakfast" in answer
        assert "- Lunch:" in answer or "- Lunch" in answer
        assert "- Dinner:" in answer or "- Dinner" in answer
        assert "- Daily Total:" in answer or "- Daily Total" in answer

        # First sentence answers exact question with values
        first_line = answer.split("\n")[0]
        assert "$15" in first_line
        assert "$25" in first_line

    def test_multi_part_incomplete_evidence_downgrades_from_supported_to_insufficient(self, mock_workspace):
        """
        IMPORTANT VALIDATION GATE:
        Before returning SUPPORTED, compare answer against question's requested facts.
        If dinner and total are missing from evidence, MUST NOT return SUPPORTED.
        Must downgrade to 'insufficient' (directive 'ask_user') and state what is missing.
        """
        incomplete_chunks = [
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "Partial Expense Policy",
                "document_version": 1,
                "authority_level": 5,
                "page_number": 1,
                "score": 0.88,
                "text": "For morning and midday travel, breakfast allowance is $15 and lunch allowance is $25."
                # Dinner and daily total are completely omitted!
            }
        ]

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What are the meal allowances for breakfast, lunch, and dinner, and what is the daily total?",
            retrieved_chunks=incomplete_chunks,
            workspace=mock_workspace,
            decision_type="general_inquiry"
        )

        # Invariant: Must NOT be SUPPORTED
        assert envelope["state"] == Verdict.INSUFFICIENT.value
        assert envelope["directive"] == Directive.ASK_USER.value

        # Must record missing facts in evidence_missing
        missing_reqs = [m["requirement"] for m in envelope["evidence_missing"]]
        assert any("dinner" in r for r in missing_reqs)
        assert any("total" in r for r in missing_reqs)

        # Answer must state what was found and what is missing
        answer = envelope["answer"]
        assert "incomplete" in answer.lower() or "missing" in answer.lower()
        assert "dinner" in answer.lower()


# ==============================================================================
# 3. COMPARISON BETWEEN TWO VERSIONS TEST
# ==============================================================================
@pytest.mark.django_db
class TestVersionComparisonQuestion:
    def test_comparison_between_two_versions_puts_comparison_first(self, mock_workspace):
        """
        Requirements 1, 2, 3:
        - Puts comparison decision in the first sentence.
        - Clearly distinguishes Version 1.0 vs Version 2.0.
        - Plain language, 1-3 short sentences.
        """
        chunks = [
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "Data Protection Standards v1",
                "document_version": 1,
                "authority_level": 6,
                "page_number": 1,
                "score": 0.85,
                "text": "Under Version 1.0, data at rest is stored unencrypted or using legacy DES encryption."
            },
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "Data Protection Standards v2",
                "document_version": 2,
                "authority_level": 6,
                "page_number": 1,
                "score": 0.95,
                "text": "Under Version 2.0, all data at rest must be encrypted using AES-256 encryption."
            }
        ]

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="Compare encryption standards between Version 1.0 and Version 2.0.",
            retrieved_chunks=chunks,
            workspace=mock_workspace,
            decision_type="general_inquiry"
        )

        assert envelope["state"] in (Verdict.SUPPORTED.value, Verdict.QUALIFIED.value)
        answer = envelope["answer"]

        # First sentence must compare both versions
        first_sentence = answer.split(". ")[0]
        assert "Version 2.0" in first_sentence or "v2" in first_sentence.lower()
        assert "AES-256" in first_sentence
        assert "Version 1.0" in first_sentence or "v1" in first_sentence.lower()

        # Conciseness: normally no more than 1-3 short sentences
        sentences = [s.strip() for s in answer.split(". ") if len(s.strip()) > 5]
        assert len(sentences) <= 3


# ==============================================================================
# 4. QUESTION WHOSE ANSWER IS ABSENT TEST
# ==============================================================================
@pytest.mark.django_db
class TestAbsentAnswerQuestion:
    def test_absent_answer_says_exactly_what_is_missing_never_guesses(self, mock_workspace):
        """
        Requirement 7:
        - If the answer cannot be established, say exactly what is missing.
        - Never guess or hallucinate ungrounded facts.
        - State must be INSUFFICIENT with directive ASK_USER.
        """
        unrelated_chunks = [
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "Facility Safety Manual",
                "document_version": 1,
                "authority_level": 4,
                "page_number": 3,
                "score": 0.20,
                "text": "Fire extinguishers are inspected every 6 months. Emergency evacuation routes are posted at all stairwells."
            }
        ]

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the pet policy for office visitors?",
            retrieved_chunks=unrelated_chunks,
            workspace=mock_workspace,
            decision_type="general_inquiry"
        )

        assert envelope["state"] == Verdict.INSUFFICIENT.value
        assert envelope["directive"] == Directive.ASK_USER.value

        # Must record missing topic
        assert len(envelope["evidence_missing"]) > 0
        assert "pet" in envelope["evidence_missing"][0]["requirement"]

        # Answer must state that the pet policy could not be established
        answer = envelope["answer"]
        assert "could not be established" in answer or "missing" in answer
        assert "pet" in answer.lower()


# ==============================================================================
# 5. DRAFT OR FUTURE-EFFECTIVE EVIDENCE TESTS
# ==============================================================================
@pytest.mark.django_db
class TestDraftOrFutureEffectiveEvidence:
    def test_draft_policy_preserves_policy_caveat(self, mock_workspace):
        """
        Requirement 6:
        - Keep policy caveats that materially affect correctness.
        - Distinguish a draft policy from an approved policy.
        - First sentence directly states that the policy is currently in draft status.
        """
        draft_chunks = [
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "Remote Work Policy (Draft)",
                "document_version": 1,
                "authority_level": 3,
                "page_number": 1,
                "score": 0.90,
                "is_draft": True,
                "text": "Status: DRAFT. Employees may work remotely up to 3 days per week pending executive sign-off."
            }
        ]

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="Is the remote work policy approved?",
            retrieved_chunks=draft_chunks,
            workspace=mock_workspace,
            decision_type="general_inquiry",
            policy_context={"is_draft": True}
        )

        answer = envelope["answer"]

        # Sentence 1 must put the draft caveat first
        first_sentence = answer.split(". ")[0]
        assert "draft" in first_sentence.lower()
        assert "not been approved" in first_sentence.lower() or "not approved" in first_sentence.lower()

        # Must maintain provenance
        assert "Remote Work Policy (Draft)" in answer

    def test_future_effective_rule_preserves_effective_date_caveat(self, mock_workspace):
        """
        Requirement 6:
        - Distinguishes a future-effective rule from the current rule.
        - Sentence 1 puts the effective date caveat first.
        """
        future_chunks = [
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "Data Retention Standard 2027",
                "document_version": 1,
                "authority_level": 6,
                "page_number": 2,
                "score": 0.91,
                "text": "Effective January 1, 2027: All database audit logs must be retained for 10 years. Not yet in effect."
            }
        ]

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What is the data retention period under the 2027 standard?",
            retrieved_chunks=future_chunks,
            workspace=mock_workspace,
            decision_type="general_inquiry",
            policy_context={"future_effective_date": "January 1, 2027"}
        )

        answer = envelope["answer"]

        # First sentence must mention future effective date and that it is not yet in effect
        first_sentence = answer.split(". ")[0]
        assert "January 1, 2027" in first_sentence or "takes effect" in first_sentence.lower()
        assert "not yet in effect" in first_sentence.lower()
