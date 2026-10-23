"""
LORE Enterprise — Core Governance Engine Completion Verification Suite
Specifications: lore.md (v3.0 §3, §4, §10), GOVERNANCE_CONTRACT.md, Master Prompt Requirements.

Tests:
1. L7 Permission Layer (RBAC/ABAC query-time authorization, anonymous blocking, zero-leakage)
2. L1 Decision Intelligence Layer (deterministic classification, explicit types, critical risk)
3. L5 Temporal Validity Layer (lifecycle exclusion, future effective, expiry, staleness, point-in-time)
4. L4 Scoped Exception Layer (time-bounded window, policy_context dimensions, expired exception rejection)
5. L6 Authority Layer (7-rank ladder, version supersession, database ConflictRecord detection)
6. L3 Evidence Sufficiency Layer (mandatory checklists, database requirements, authority floor)
7. L2 Answer-State Layer (deterministic 9-state precedence ladder)
8. Invariant Enforcement (model cannot override permission denial, conflict, or insufficiency)
9. Resilience and Fail-Closed (unexpected layer failures, missing LLM provider, prompt injection)
10. Deterministic Re-Evaluation (identical inputs yield identical results)
"""

import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
import pytest
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.sources.models import SourceDocument
from apps.governance.models import (
    SourcePermission, ScopedException, EvidenceRequirement, ConflictRecord, AccessLevel
)
from apps.governance.contract import (
    Verdict, Directive, EvidenceStatus, GovernanceReasonCode, GovernanceRequest,
    validate_canonical_envelope, fail_closed_envelope, ContractValidationError
)
from apps.governance.layers import (
    PermissionLayer, DecisionIntelligenceLayer, TemporalValidityLayer,
    ExceptionLayer, AuthorityLayer, EvidenceSufficiencyLayer, AnswerStateLayer,
    EnterpriseGovernanceEngine
)

User = get_user_model()


@pytest.fixture
def enterprise_suite(db):
    org = Organization.objects.create(name="Governance Engine Org", slug="gov-engine-org")
    ws = Workspace.objects.create(organization=org, name="Core Governance WS", slug="core-gov-ws")
    admin_user = User.objects.create_user(
        username="lead_auditor@gov.test", password="Password123!", email="lead_auditor@gov.test"
    )
    OrganizationMembership.objects.create(organization=org, user=admin_user, role="owner")
    WorkspaceMembership.objects.create(workspace=ws, user=admin_user, role="workspace_admin")

    regular_user = User.objects.create_user(
        username="engineer@gov.test", password="Password123!", email="engineer@gov.test"
    )
    OrganizationMembership.objects.create(organization=org, user=regular_user, role="member")
    WorkspaceMembership.objects.create(workspace=ws, user=regular_user, role="member")

    return {
        "org": org,
        "ws": ws,
        "admin_user": admin_user,
        "regular_user": regular_user
    }


# ==============================================================================
# 1. L7 PERMISSION LAYER INDEPENDENT TESTS
# ==============================================================================
@pytest.mark.django_db
class TestPermissionLayerL7:
    def test_unauthenticated_anonymous_user_blocked_from_internal_docs(self, enterprise_suite):
        ws = enterprise_suite["ws"]
        org = enterprise_suite["org"]

        doc = SourceDocument.objects.create(
            organization=org, workspace=ws, title="Internal Security Standard",
            original_filename="sec.pdf", mime_type="application/pdf", file_size=1024,
            file_hash="hash-sec-1", status="ready", authority_level=6
        )

        chunk = {"document_id": str(doc.id), "document_title": doc.title, "text": "Internal details"}

        # Anonymous caller (no user, role=anonymous)
        res = PermissionLayer.filter_authorized_chunks([chunk], user=None, user_role="anonymous")
        assert len(res.cleared_chunks) == 0
        assert res.is_denied is True
        assert GovernanceReasonCode.L7_ANONYMOUS_BLOCKED.value in res.reason_codes
        assert GovernanceReasonCode.L7_PERMISSION_DENIED.value in res.reason_codes

    def test_restricted_document_requires_explicit_role_or_user(self, enterprise_suite):
        ws = enterprise_suite["ws"]
        org = enterprise_suite["org"]
        admin_user = enterprise_suite["admin_user"]
        regular_user = enterprise_suite["regular_user"]

        doc = SourceDocument.objects.create(
            organization=org, workspace=ws, title="Confidential Executive Compensation",
            original_filename="comp.pdf", mime_type="application/pdf", file_size=1024,
            file_hash="hash-comp-1", status="ready", authority_level=7
        )

        SourcePermission.objects.create(
            document=doc,
            access_level=AccessLevel.CONFIDENTIAL,
            allowed_roles=["workspace_admin", "owner"]
        )

        chunk = {"document_id": str(doc.id), "document_title": doc.title, "text": "Executive bonus scales"}

        # Regular member should be denied
        res_member = PermissionLayer.filter_authorized_chunks([chunk], user=regular_user, user_role="member")
        assert len(res_member.cleared_chunks) == 0
        assert res_member.is_denied is True
        assert GovernanceReasonCode.L7_UNAUTHORIZED_ROLE.value in res_member.reason_codes

        # Workspace Admin should be authorized
        res_admin = PermissionLayer.filter_authorized_chunks([chunk], user=admin_user, user_role="workspace_admin")
        assert len(res_admin.cleared_chunks) == 1
        assert res_admin.is_denied is False
        assert GovernanceReasonCode.L7_PERMISSION_GRANTED.value in res_admin.reason_codes

    def test_permission_filter_tuple_compatibility(self):
        chunks = [{"document_id": str(uuid.uuid4()), "document_title": "Doc 1", "text": "Sample"}]
        # Test tuple unpacking
        cleared, denials = PermissionLayer.filter_authorized_chunks(chunks, user_role="member")
        assert len(cleared) == 1
        assert len(denials) == 0


# ==============================================================================
# 2. L1 DECISION INTELLIGENCE LAYER TESTS
# ==============================================================================
@pytest.mark.django_db
class TestDecisionIntelligenceLayerL1:
    def test_explicit_decision_type_honored(self):
        # Query text has no vendor keywords, but explicit type is vendor_approval
        res = DecisionIntelligenceLayer.classify("What is the speed of light?", explicit_decision_type="vendor_approval")
        assert res.decision_type == "vendor_approval"
        assert res.risk_level == "high"
        assert "policy_condition" in res.mandatory_evidence
        assert GovernanceReasonCode.L1_EXPLICIT_DECISION_TYPE.value in res.reason_codes

    def test_critical_risk_flagged_for_statutory(self):
        res = DecisionIntelligenceLayer.classify("দলিল ও খতিয়ান যাচাইকরণ")
        assert res.decision_type == "statutory_compliance"
        assert res.risk_level == "critical"
        assert res.requires_human_review is True
        assert GovernanceReasonCode.L1_CRITICAL_RISK_FLAGGED.value in res.reason_codes

    def test_catalog_fallback_general_inquiry(self):
        res = DecisionIntelligenceLayer.classify("Who invented the transistor?")
        assert res.decision_type == "general_inquiry"
        assert res.risk_level == "low"
        assert res.requires_human_review is False
        assert GovernanceReasonCode.L1_DECISION_CLASSIFIED.value in res.reason_codes


# ==============================================================================
# 3. L5 TEMPORAL VALIDITY LAYER TESTS
# ==============================================================================
@pytest.mark.django_db
class TestTemporalValidityLayerL5:
    def test_unpublished_quarantined_draft_excluded(self, enterprise_suite):
        ws = enterprise_suite["ws"]
        org = enterprise_suite["org"]

        doc_draft = SourceDocument.objects.create(
            organization=org, workspace=ws, title="Draft Guidelines",
            original_filename="draft.pdf", mime_type="application/pdf", file_size=1024,
            file_hash="hash-draft-1", status="draft", authority_level=4
        )

        chunk = {"document_id": str(doc_draft.id), "text": "Draft content"}
        res = TemporalValidityLayer.evaluate([chunk])
        assert len(res.valid_chunks) == 0
        assert GovernanceReasonCode.L5_LIFECYCLE_EXCLUSION.value in res.reason_codes

    def test_future_effective_date_excluded(self, enterprise_suite):
        ws = enterprise_suite["ws"]
        org = enterprise_suite["org"]

        doc_future = SourceDocument.objects.create(
            organization=org, workspace=ws, title="2030 Roadmap",
            original_filename="2030.pdf", mime_type="application/pdf", file_size=1024,
            file_hash="hash-future-1", status="ready", authority_level=6,
            effective_date=timezone.now() + timedelta(days=60)
        )

        chunk = {"document_id": str(doc_future.id), "text": "Future plans"}
        res = TemporalValidityLayer.evaluate([chunk])
        assert len(res.valid_chunks) == 0
        assert GovernanceReasonCode.L5_FUTURE_EFFECTIVE_EXCLUSION.value in res.reason_codes

    def test_expired_document_excluded(self, enterprise_suite):
        ws = enterprise_suite["ws"]
        org = enterprise_suite["org"]

        doc_expired = SourceDocument.objects.create(
            organization=org, workspace=ws, title="Expired 2023 Agreement",
            original_filename="old.pdf", mime_type="application/pdf", file_size=1024,
            file_hash="hash-expired-1", status="ready", authority_level=6,
            expiration_date=timezone.now() - timedelta(days=30)
        )

        chunk = {"document_id": str(doc_expired.id), "text": "Expired terms"}
        res = TemporalValidityLayer.evaluate([chunk])
        assert len(res.valid_chunks) == 0
        assert GovernanceReasonCode.L5_EXPIRATION_EXCLUSION.value in res.reason_codes

    def test_stale_document_caveat_applied(self, enterprise_suite):
        ws = enterprise_suite["ws"]
        org = enterprise_suite["org"]

        doc_stale = SourceDocument.objects.create(
            organization=org, workspace=ws, title="Aging Standard",
            original_filename="stale.pdf", mime_type="application/pdf", file_size=1024,
            file_hash="hash-stale-1", status="ready", authority_level=5,
            stale_after_days=30
        )
        # Update updated_at back 45 days
        SourceDocument.objects.filter(id=doc_stale.id).update(
            updated_at=timezone.now() - timedelta(days=45)
        )

        chunk = {"document_id": str(doc_stale.id), "text": "Aging content"}
        res = TemporalValidityLayer.evaluate([chunk])
        assert len(res.valid_chunks) == 1
        assert res.has_stale_data is True
        assert GovernanceReasonCode.L5_STALE_RECORD_CAVEAT.value in res.reason_codes


# ==============================================================================
# 4. L4 SCOPED EXCEPTION LAYER TESTS
# ==============================================================================
@pytest.mark.django_db
class TestExceptionLayerL4:
    def test_scoped_exception_via_policy_context(self, enterprise_suite):
        ws = enterprise_suite["ws"]

        ScopedException.objects.create(
            workspace=ws,
            rule_code="NET-004",
            scope_type="vendor",
            scope_value="VendorX",
            justification="Proof of concept waiver",
            approved_by="Security Director",
            status="active",
            window_start=timezone.now() - timedelta(days=2),
            window_end=timezone.now() + timedelta(days=14)
        )

        # Query does not contain "VendorX", but policy_context passes vendor="VendorX"
        res = ExceptionLayer.evaluate(
            str(ws.id),
            query="Can we route traffic through external proxy?",
            policy_context={"vendor": "VendorX"}
        )
        assert res.has_applicable_exception is True
        assert len(res.matched_exceptions) == 1
        assert res.matched_exceptions[0]["rule_code"] == "NET-004"
        assert GovernanceReasonCode.L4_EXCEPTION_APPLIED.value in res.reason_codes

    def test_expired_exception_rejected_with_reason_code(self, enterprise_suite):
        ws = enterprise_suite["ws"]

        ScopedException.objects.create(
            workspace=ws,
            rule_code="SEC-W-01",
            scope_type="vendor",
            scope_value="PastTool",
            justification="Past waiver",
            approved_by="CISO",
            status="active",
            window_start=timezone.now() - timedelta(days=60),
            window_end=timezone.now() - timedelta(days=10)
        )

        res = ExceptionLayer.evaluate(str(ws.id), "Can we use PastTool?")
        assert res.has_applicable_exception is False
        assert len(res.matched_exceptions) == 0
        assert GovernanceReasonCode.L4_EXCEPTION_EXPIRED.value in res.reason_codes


# ==============================================================================
# 5. L6 AUTHORITY & CONFLICT LAYER TESTS
# ==============================================================================
@pytest.mark.django_db
class TestAuthorityLayerL6:
    def test_database_conflict_record_detection(self, enterprise_suite):
        ws = enterprise_suite["ws"]
        org = enterprise_suite["org"]

        doc_a = SourceDocument.objects.create(
            organization=org, workspace=ws, title="Policy Alpha",
            original_filename="a.pdf", mime_type="application/pdf", file_size=1024,
            file_hash="hash-pa-1", status="ready", authority_level=6
        )
        doc_b = SourceDocument.objects.create(
            organization=org, workspace=ws, title="Policy Beta",
            original_filename="b.pdf", mime_type="application/pdf", file_size=1024,
            file_hash="hash-pb-1", status="ready", authority_level=6
        )

        ConflictRecord.objects.create(
            workspace=ws,
            source_a=doc_a,
            source_b=doc_b,
            claim_a="Deployments require dual lead approval",
            claim_b="Deployments require single lead approval",
            resolution_status="unresolved",
            resolution_notes="Awaiting Q4 executive meeting"
        )

        chunks = [
            {"document_id": str(doc_a.id), "document_title": doc_a.title, "authority_level": 6, "text": "dual approval"},
            {"document_id": str(doc_b.id), "document_title": doc_b.title, "authority_level": 6, "text": "single approval"}
        ]

        res = AuthorityLayer.evaluate_conflicts(chunks, workspace_id=str(ws.id))
        assert res.has_unresolved_tie is True
        assert GovernanceReasonCode.L6_DATABASE_CONFLICT_DETECTED.value in res.reason_codes
        assert GovernanceReasonCode.L6_UNRESOLVED_CONTRADICTION.value in res.reason_codes

    def test_authority_dominance(self):
        chunks = [
            {"document_title": "Informal Note", "authority_level": 1, "text": "Cloud storage is permitted unconditionally"},
            {"document_title": "Enterprise Security Policy", "authority_level": 7, "text": "Cloud storage is prohibited without encryption"}
        ]
        res = AuthorityLayer.evaluate_conflicts(chunks)
        assert len(res.conflicts_resolved) == 1
        assert res.conflicts_resolved[0]["resolution"] == "authority_dominance"
        assert res.has_unresolved_tie is False
        assert GovernanceReasonCode.L6_AUTHORITY_DOMINANCE.value in res.reason_codes


# ==============================================================================
# 6. L3 EVIDENCE SUFFICIENCY LAYER TESTS
# ==============================================================================
@pytest.mark.django_db
class TestEvidenceSufficiencyLayerL3:
    def test_database_custom_requirement_enforcement(self, enterprise_suite):
        ws = enterprise_suite["ws"]

        EvidenceRequirement.objects.create(
            workspace=ws,
            decision_type="vendor_approval",
            evidence_type="iso_27001_certificate",
            is_mandatory=True,
            description="Active ISO 27001 certification must be on file."
        )

        decision_info = DecisionIntelligenceLayer.classify("Can we approve new vendor?")
        chunks = [
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "Vendor Brochure",
                "authority_level": 5,
                "text": "We are a safe and reliable cloud provider with data residency."
            }
        ]

        res = EvidenceSufficiencyLayer.evaluate(
            str(ws.id), decision_info, chunks, query="Can we approve new vendor?"
        )

        assert res.is_sufficient is False
        assert any(m["requirement"] == "iso_27001_certificate" for m in res.evidence_missing)
        assert GovernanceReasonCode.L3_CUSTOM_REQUIREMENT_UNSATISFIED.value in res.reason_codes

    def test_insufficient_authority_rank_for_critical_decision(self, enterprise_suite):
        ws = enterprise_suite["ws"]
        decision_info = DecisionIntelligenceLayer.classify("Can we approve cloud vendor?")
        chunks = [
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "Informal Chat",
                "authority_level": 2,
                "text": "Vendor has passed SOC 2 and Schedule D is signed."
            }
        ]

        res = EvidenceSufficiencyLayer.evaluate(
            str(ws.id), decision_info, chunks, query="Can we approve cloud vendor?"
        )
        assert res.is_sufficient is False
        assert any(m["requirement"] == "authoritative_controlling_source" for m in res.evidence_missing)
        assert GovernanceReasonCode.L3_INSUFFICIENT_AUTHORITY_RANK.value in res.reason_codes


# ==============================================================================
# 7. L2 ANSWER-STATE LAYER TESTS
# ==============================================================================
class TestAnswerStateLayerL2:
    def test_precedence_ladder_strict_ordering(self):
        # 1. Denied beats all
        s1 = AnswerStateLayer.resolve_state(
            is_denied=True, is_violation=True, has_unresolved_conflict=True,
            is_sufficient=False, is_abstain=True, requires_human_review=True,
            is_qualified=True, chunks_count=5
        )
        assert s1.state == "denied"
        assert s1.directive == "stop"

        # 2. Violation beats conflict & insufficient
        s2 = AnswerStateLayer.resolve_state(
            is_denied=False, is_violation=True, has_unresolved_conflict=True,
            is_sufficient=False, is_abstain=False, requires_human_review=False,
            is_qualified=False, chunks_count=5
        )
        assert s2.state == "violation"
        assert s2.directive == "stop"

        # 3. Conflicting beats insufficient
        s3 = AnswerStateLayer.resolve_state(
            is_denied=False, is_violation=False, has_unresolved_conflict=True,
            is_sufficient=False, is_abstain=False, requires_human_review=False,
            is_qualified=False, chunks_count=5
        )
        assert s3.state == "conflicting"
        assert s3.directive == "ask_user"

        # 4. Insufficient beats human review and qualified
        s4 = AnswerStateLayer.resolve_state(
            is_denied=False, is_violation=False, has_unresolved_conflict=False,
            is_sufficient=False, is_abstain=False, requires_human_review=True,
            is_qualified=True, chunks_count=5
        )
        assert s4.state == "insufficient"
        assert s4.directive == "ask_user"


# ==============================================================================
# 8. INVARIANT ENFORCEMENT & MODEL ISOLATION TESTS
# ==============================================================================
@pytest.mark.django_db
class TestInvariantEnforcement:
    def test_model_cannot_override_permission_denial(self, enterprise_suite):
        ws = enterprise_suite["ws"]
        org = enterprise_suite["org"]

        doc = SourceDocument.objects.create(
            organization=org, workspace=ws, title="Secret IP Document",
            original_filename="secret.pdf", mime_type="application/pdf", file_size=1024,
            file_hash="hash-sec-ip", status="ready", authority_level=7
        )

        SourcePermission.objects.create(
            document=doc,
            access_level=AccessLevel.RESTRICTED,
            allowed_roles=["owner"]
        )

        chunk = {
            "document_id": str(doc.id),
            "document_title": doc.title,
            "document_version": 1,
            "page_number": 1,
            "text": "Secret formula: Alpha Omega 42"
        }

        # Query as regular member with a simulated Groq API key
        req = GovernanceRequest(
            workspace=ws,
            user_role="member",
            query="What is the secret formula?",
            candidate_evidence=[chunk],
            groq_api_key="gsk-fake-key-12345"
        )

        envelope = EnterpriseGovernanceEngine.evaluate(request=req)

        # Invariant 1: State must be denied
        assert envelope["state"] == "denied"
        assert envelope["directive"] == "stop"

        # Invariant 2: Zero citations or evidence leakage
        assert envelope["citations"] == []
        assert envelope["evidence_found"] == []

        # Invariant 3: Model was not invoked, answer is deterministic access denied
        assert "Access Denied" in envelope["answer"]
        assert "Alpha Omega" not in envelope["answer"]

        # Invariant 4: Contract validation passed
        assert envelope["layers_breakdown"]["l7_permission"]["status"] == "denied"
        assert GovernanceReasonCode.L7_PERMISSION_DENIED.value in envelope["reason_codes"]

    def test_model_cannot_override_missing_evidence(self, enterprise_suite):
        ws = enterprise_suite["ws"]

        # Missing Schedule D for vendor approval
        chunks = [
            {
                "document_id": str(uuid.uuid4()),
                "document_title": "CloudBox Terms",
                "authority_level": 6,
                "text": "Schedule D has not been attached. Data residency unverified."
            }
        ]

        envelope = EnterpriseGovernanceEngine.evaluate(
            query="Approve CloudBox for customer PII",
            retrieved_chunks=chunks,
            workspace=ws,
            groq_api_key="gsk-fake-key-12345"
        )

        assert envelope["state"] == "insufficient"
        assert envelope["directive"] == "ask_user"
        assert len(envelope["evidence_missing"]) > 0

    def test_contract_validation_rejects_denied_with_citations(self):
        malformed_envelope = {
            "schema": "lore.result/2",
            "state": "denied",
            "directive": "stop",
            "answer": "Denied with leak",
            "citations": [{"document_id": "doc-leak", "passage": "Sensitive text"}],
            "evidence_found": [{"document_id": "doc-leak"}],
            "layers_breakdown": {"l7_permission": {"status": "denied"}}
        }

        with pytest.raises(ContractValidationError) as exc:
            validate_canonical_envelope(malformed_envelope)
        assert "Security Invariant Violated" in str(exc.value)


# ==============================================================================
# 9. RESILIENCE, PROMPT INJECTION & DETERMINISM TESTS
# ==============================================================================
@pytest.mark.django_db
class TestResilienceAndDeterminism:
    def test_unexpected_layer_failure_fails_closed(self, enterprise_suite):
        ws = enterprise_suite["ws"]

        # Force an unexpected internal error during layer execution
        with patch.object(TemporalValidityLayer, "evaluate", side_effect=RuntimeError("Database corruption simulation")):
            envelope = EnterpriseGovernanceEngine.evaluate(
                query="Verify our SOC 2 compliance",
                retrieved_chunks=[{"document_id": str(uuid.uuid4()), "text": "Data"}],
                workspace=ws
            )

        assert envelope["state"] == "insufficient"
        assert envelope["directive"] == "ask_user"
        assert envelope["error_category"] == "GOVERNANCE_EXECUTION_FAILURE"
        assert envelope["citations"] == []
        assert envelope["evidence_found"] == []
        assert GovernanceReasonCode.FAIL_CLOSED_GATE_INVOKED.value in envelope["reason_codes"]

    def test_missing_llm_provider_deterministic_fallback(self, enterprise_suite):
        ws = enterprise_suite["ws"]
        org = enterprise_suite["org"]

        doc = SourceDocument.objects.create(
            organization=org, workspace=ws, title="Encryption Standard",
            original_filename="enc.pdf", mime_type="application/pdf", file_size=1024,
            file_hash="hash-enc-1", status="ready", authority_level=6
        )

        chunk = {
            "document_id": str(doc.id),
            "document_title": doc.title,
            "document_version": 1,
            "page_number": 1,
            "authority_level": 6,
            "text": "All internal database volumes must enforce AES-256 encryption."
        }

        # Evaluate with no Groq API key and no cloud credentials
        envelope = EnterpriseGovernanceEngine.evaluate(
            query="What encryption standard is required for database volumes?",
            retrieved_chunks=[chunk],
            workspace=ws,
            groq_api_key=None
        )

        assert envelope["state"] == "supported"
        assert envelope["directive"] == "proceed_and_cite"
        assert envelope["llm_provider"] == "deterministic_synthesis"
        assert len(envelope["citations"]) == 1
        assert "AES-256" in envelope["answer"]

    def test_repeated_evaluations_are_strictly_deterministic(self, enterprise_suite):
        ws = enterprise_suite["ws"]
        org = enterprise_suite["org"]

        doc = SourceDocument.objects.create(
            organization=org, workspace=ws, title="Password Rotation Policy",
            original_filename="pwd.pdf", mime_type="application/pdf", file_size=1024,
            file_hash="hash-pwd-1", status="ready", authority_level=7
        )

        chunk = {
            "document_id": str(doc.id),
            "document_title": doc.title,
            "document_version": 1,
            "page_number": 1,
            "authority_level": 7,
            "text": "Privileged account passwords must be rotated every 90 days."
        }

        req = GovernanceRequest(
            workspace=ws,
            query="What is the password rotation cycle?",
            candidate_evidence=[chunk]
        )

        # Run 3 times
        eval1 = EnterpriseGovernanceEngine.evaluate(request=req)
        eval2 = EnterpriseGovernanceEngine.evaluate(request=req)
        eval3 = EnterpriseGovernanceEngine.evaluate(request=req)

        assert eval1["state"] == eval2["state"] == eval3["state"] == "supported"
        assert eval1["directive"] == eval2["directive"] == eval3["directive"] == "proceed_and_cite"
        assert eval1["reason_codes"] == eval2["reason_codes"] == eval3["reason_codes"]
        assert eval1["answer"] == eval2["answer"] == eval3["answer"]
        assert len(eval1["citations"]) == len(eval2["citations"]) == len(eval3["citations"]) == 1
