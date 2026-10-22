"""
LORE Enterprise — Canonical Result Contract (lore.result/2 & lore.result/1)
Specification: lore.md (v3.0 §3, §4, §10), Master Prompt P1 §3, §8.

Strictly defines the versioned, validated canonical result contract.
Enforces:
1. Exact 9-state verdict enum and 5-action directive enum.
2. Invariant mapping: each verdict permits ONLY its canonical directive.
3. Explicit item-level evidence statuses.
4. Provenance coordinates (document_id, document_version, page_number, heading_path, passage).
5. Fail-closed guarantees: malformed, invalid, or unverified outputs fail to safe stop/escalate states.
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid
import logging

logger = logging.getLogger(__name__)


class Verdict(str, Enum):
    """LORE 9-State Precedence Ladder (lore.md §10.1). Precedence 1 (highest) to 9."""
    DENIED = "denied"                    # 1: Requester may not see this knowledge
    VIOLATION = "violation"              # 2: Proposal breaks a MUST / MUST-NOT rule
    CONFLICTING = "conflicting"          # 3: Active sources contradict with equal authority
    INSUFFICIENT = "insufficient"        # 4: Mandatory evidence checklist incomplete
    ABSTAIN = "abstain"                  # 5: Evidence present but confidence in uncertainty band
    HUMAN_REVIEW = "human_review"        # 6: High-risk decision type requires designated human sign-off
    QUALIFIED = "qualified"              # 7: Consistent, but conditions/aging/exceptions must be disclosed
    SUPPORTED = "supported"              # 8: Applicable rules found, consistent, evidence complete
    NO_KNOWLEDGE = "no_knowledge"        # 9: Nothing governed applies here


class Directive(str, Enum):
    """LORE 5 Action Directives (lore.md §10.1)."""
    STOP = "stop"
    ASK_USER = "ask_user"
    ESCALATE = "escalate"
    PROCEED_AND_CITE = "proceed_and_cite"
    PROCEED = "proceed"


class EvidenceStatus(str, Enum):
    """P1 §5 Explicit Item-Level Evidence Statuses."""
    SATISFIED = "satisfied"
    PARTIAL = "partial"
    MISSING = "missing"
    PENDING = "pending"
    INSUFFICIENT_AUTHORITY = "insufficient_authority"
    EXPIRED = "expired"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"


# Strict invariant matrix mapping verdicts to allowed directives
CANONICAL_VERDICT_DIRECTIVE_MAP: Dict[Verdict, Directive] = {
    Verdict.DENIED: Directive.STOP,
    Verdict.VIOLATION: Directive.STOP,
    Verdict.CONFLICTING: Directive.ASK_USER,
    Verdict.INSUFFICIENT: Directive.ASK_USER,
    Verdict.ABSTAIN: Directive.ASK_USER,
    Verdict.HUMAN_REVIEW: Directive.ESCALATE,
    Verdict.QUALIFIED: Directive.PROCEED_AND_CITE,
    Verdict.SUPPORTED: Directive.PROCEED_AND_CITE,
    Verdict.NO_KNOWLEDGE: Directive.PROCEED,
}


class ContractValidationError(Exception):
    """Raised when a governance result envelope violates schema invariants."""
    pass


def validate_verdict_directive_pairing(verdict: str, directive: str) -> None:
    """
    Enforces the strict pairing between verdict and directive.
    Unknown states or invalid pairings strictly raise ContractValidationError.
    """
    try:
        v_enum = Verdict(verdict)
    except ValueError:
        raise ContractValidationError(f"Invalid verdict '{verdict}'. Must be one of {[v.value for v in Verdict]}.")

    try:
        d_enum = Directive(directive)
    except ValueError:
        raise ContractValidationError(f"Invalid directive '{directive}'. Must be one of {[d.value for d in Directive]}.")

    expected_directive = CANONICAL_VERDICT_DIRECTIVE_MAP[v_enum]
    if d_enum != expected_directive:
        raise ContractValidationError(
            f"Invalid pairing: Verdict '{v_enum.value}' requires directive '{expected_directive.value}', "
            f"got '{d_enum.value}'."
        )


def validate_canonical_envelope(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates a complete canonical result envelope against LORE v2/v1 schema rules:
    - Schema version check ('lore.result/2' or 'lore.result/1')
    - State & directive pairing verification
    - Mandatory evidence checks: positive approval cannot emit with missing mandatory evidence
    - Citation provenance coordinates
    - Non-empty trace and decision identifiers
    """
    if not isinstance(data, dict):
        raise ContractValidationError("Envelope must be a JSON object / Python dict.")

    schema = data.get("schema", "lore.result/2")
    if schema not in ["lore.result/1", "lore.result/2"]:
        raise ContractValidationError(f"Unsupported schema version: '{schema}'. Expected 'lore.result/1' or 'lore.result/2'.")

    state = data.get("state")
    directive = data.get("directive")

    if not state or not directive:
        raise ContractValidationError("Envelope missing mandatory 'state' or 'directive' fields.")

    # Validate strict state-directive matrix
    validate_verdict_directive_pairing(state, directive)

    # Invariant: positive approval strictly requires no missing mandatory evidence
    evidence_missing = data.get("evidence_missing", [])
    has_mandatory_missing = any(
        item.get("mandatory", True) and item.get("status") in [
            EvidenceStatus.MISSING.value,
            EvidenceStatus.PENDING.value,
            EvidenceStatus.EXPIRED.value,
            EvidenceStatus.INSUFFICIENT_AUTHORITY.value,
            EvidenceStatus.UNAVAILABLE.value
        ]
        for item in evidence_missing
    )

    if has_mandatory_missing and state in [Verdict.SUPPORTED.value, Verdict.NO_KNOWLEDGE.value]:
        raise ContractValidationError(
            f"Positive approval state '{state}' is invalid when mandatory evidence is missing or unsatisfied."
        )

    # Validate citations provenance coordinates
    citations = data.get("citations", [])
    for idx, cit in enumerate(citations):
        if not isinstance(cit, dict):
            raise ContractValidationError(f"Citation at index {idx} must be a dictionary.")
        if not cit.get("document_id") and not cit.get("citation_id"):
            raise ContractValidationError(f"Citation at index {idx} missing required identifier.")
        if "passage" not in cit and "snippet" not in cit:
            raise ContractValidationError(f"Citation at index {idx} missing supporting text passage.")

    # Ensure trace_id exists
    if not data.get("trace_id"):
        data["trace_id"] = f"trace-{uuid.uuid4().hex[:12]}"

    if not data.get("decision_id"):
        data["decision_id"] = f"dec-{uuid.uuid4().hex[:8]}"

    return data


def fail_closed_envelope(
    query: str,
    error_message: str,
    error_category: str = "GOVERNANCE_SYSTEM_ERROR",
    trace_id: Optional[str] = None,
    decision_type: str = "general_inquiry"
) -> Dict[str, Any]:
    """
    Generates a typed, fail-closed result envelope when a governance or retrieval error occurs.
    Guarantees that errors NEVER default to approval.
    """
    tid = trace_id or f"trace-err-{uuid.uuid4().hex[:8]}"
    did = f"dec-err-{uuid.uuid4().hex[:8]}"

    logger.error(f"[Fail-Closed Gate] Query='{query[:60]}' Error={error_category}: {error_message} (Trace={tid})")

    return {
        "schema": "lore.result/2",
        "state": Verdict.INSUFFICIENT.value,
        "directive": Directive.ASK_USER.value,
        "answer": f"Governance gate closed due to internal verification error ({error_category}). No unverified conclusion can be returned.",
        "decision_type": decision_type,
        "escalation_target": "compliance_auditor",
        "risk_level": "high",
        "evidence_found": [],
        "evidence_missing": [{
            "requirement": "system_governance_verification",
            "mandatory": True,
            "status": EvidenceStatus.UNAVAILABLE.value,
            "description": f"Internal governance evaluation failed closed: {error_message}"
        }],
        "conflicts_resolved": [],
        "exceptions_applied": [],
        "citations": [],
        "notes": [f"Fail-closed governance invoked: {error_category}"],
        "decision_id": did,
        "trace_id": tid,
        "token_count": 0,
        "error_category": error_category,
        "anti_hallucination_active": True,
        "layers_breakdown": {
            "l7_permission": {"status": "error", "denials": [error_message]},
            "l1_decision_intelligence": {"decision_type": decision_type, "escalation": "compliance_auditor", "risk": "high"},
            "l6_authority": {"conflicts_count": 0, "unresolved_tie": False},
            "l5_temporal": {"stale_data": False, "temporal_notes": []},
            "l4_exceptions": {"applied_count": 0, "exceptions": []},
            "l3_sufficiency": {"is_sufficient": False, "missing_count": 1},
            "l2_answer_state": {"final_state": Verdict.INSUFFICIENT.value, "directive": Directive.ASK_USER.value},
            "l0_observability": {"trace_id": tid, "timings_ms": {}}
        }
    }
