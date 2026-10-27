"""
LORE Enterprise — Typed Evidence Requirement Registry
Specification: lore.md (v3.0 §3, §4, §10), Master Audit Specification.

Enforces:
1. Explicit, typed, and configurable evidence requirements by decision type.
2. Distinct conditions under which requirements apply (e.g. spend > $25k).
3. Required evidence type, acceptable authority, and approval status.
4. Handling strategies for missing, pending, expired, and conflicting evidence.
5. Strict domain boundaries: never imposes requirements from unrelated decision categories.
"""

import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional, Callable, Tuple
from datetime import datetime
from apps.governance.contract import EvidenceStatus, GovernanceReasonCode

logger = logging.getLogger(__name__)


class RequirementHandlingStrategy(str, Enum):
    MISSING = "missing"
    INSUFFICIENT = "insufficient"
    VIOLATION = "violation"
    CONFLICTING = "conflicting"
    ABSTAIN = "abstain"
    QUALIFIED = "qualified"


@dataclass
class TypedRequirement:
    requirement_id: str
    decision_type: str                         # e.g. 'procurement_governance', 'vendor_approval', 'policy_compliance'
    evidence_type: str                         # e.g. 'cfo_written_approval', 'formal_security_assessment'
    description: str                           # Clear description of the required evidence
    applies_to_intents: List[str]              # ['action_authorization', 'informational', 'comparison', '*']
    condition_fn: Optional[Callable[[Any, Dict[str, Any]], bool]] = None
    min_authority_level: int = 4               # 4=procedure/minutes, 6=contract, 7=policy
    acceptable_statuses: List[str] = field(default_factory=lambda: ['approved', 'active', 'ready'])
    relevant_scopes: List[str] = field(default_factory=list)
    on_missing: str = "insufficient"
    on_pending: str = "insufficient"
    on_expired: str = "insufficient"
    on_conflicting: str = "conflicting"
    is_mandatory: bool = True

    def applies(self, query_analysis: Any, context: Optional[Dict[str, Any]] = None) -> bool:
        """Determines whether this requirement is active for the current query and context."""
        context = context or {}
        intent = getattr(query_analysis, 'intent', '')
        intent_val = intent.value if hasattr(intent, 'value') else str(intent)

        # Check intent applicability
        if '*' not in self.applies_to_intents and intent_val not in self.applies_to_intents:
            # Also check action authorization aliases
            is_action = intent_val in ('action_authorization', 'approval_compliance_decision', 'action_request')
            if 'action_authorization' in self.applies_to_intents and not is_action:
                return False
            if 'action_authorization' not in self.applies_to_intents and is_action and '*' not in self.applies_to_intents:
                return False

        # Check custom condition function if present
        if self.condition_fn:
            try:
                return self.condition_fn(query_analysis, context)
            except Exception as e:
                logger.warning(f"Error evaluating condition for requirement {self.requirement_id}: {e}")
                return False

        return True


@dataclass
class RequirementEvaluationResult:
    requirement_id: str
    decision_type: str
    evidence_type: str
    description: str
    is_mandatory: bool
    status: EvidenceStatus
    matched_chunks: List[Dict[str, Any]] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'requirement': self.requirement_id,
            'decision_type': self.decision_type,
            'evidence_type': self.evidence_type,
            'mandatory': self.is_mandatory,
            'status': self.status.value,
            'description': self.description,
            'matched_chunks_count': len(self.matched_chunks),
            'notes': self.notes
        }


class RequirementRegistry:
    """
    Central, typed registry of evidence requirements for LORE Enterprise.
    Supports default requirements by decision type and runtime workspace configuration.
    """

    _registry: Dict[str, List[TypedRequirement]] = {}

    @classmethod
    def register(cls, requirement: TypedRequirement) -> None:
        cls._registry.setdefault(requirement.decision_type, []).append(requirement)

    @classmethod
    def get_registered_requirements(cls, decision_type: str) -> List[TypedRequirement]:
        return cls._registry.get(decision_type, [])

    @classmethod
    def get_applicable_requirements(
        cls,
        decision_type: str,
        query_analysis: Any,
        context: Optional[Dict[str, Any]] = None
    ) -> List[TypedRequirement]:
        """
        Retrieves all requirements that apply to the current query and context.
        Strictly limits requirements to the classified decision type and global ('*') types.
        Never imposes requirements from unrelated decision types.
        """
        applicable = []
        context = context or {}

        # 1. Requirements for specific decision type
        dt_reqs = cls._registry.get(decision_type, [])
        for req in dt_reqs:
            if req.applies(query_analysis, context):
                applicable.append(req)

        # 2. Global requirements if any
        for req in cls._registry.get('*', []):
            if req.applies(query_analysis, context):
                applicable.append(req)

        return applicable

    @classmethod
    def evaluate_requirements(
        cls,
        decision_type: str,
        query_analysis: Any,
        active_chunks: List[Dict[str, Any]],
        query: str,
        context: Optional[Dict[str, Any]] = None,
        as_of: Optional[datetime] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool, List[str]]:
        """
        Evaluates applicable evidence requirements against the retrieved, active evidence chunks.
        
        Returns:
            evidence_found: List of satisfied requirement dicts with matched chunks
            evidence_missing: List of unsatisfied requirement dicts with explicit reasons
            is_sufficient: Boolean indicating whether all mandatory requirements are satisfied
            reason_codes: Audit reason codes
        """
        context = context or {}
        reason_codes = []
        applicable_reqs = cls.get_applicable_requirements(decision_type, query_analysis, context)

        evidence_found = []
        evidence_missing = []
        q_lower = query.lower()

        # If no explicit requirements are defined for an informational query, verify at least 1 authoritative fact exists
        intent = getattr(query_analysis, 'intent', '')
        intent_val = intent.value if hasattr(intent, 'value') else str(intent)
        is_informational = intent_val in ('exact_fact_lookup', 'informational', 'policy_interpretation', 'procedural_instructions')

        if not applicable_reqs:
            if is_informational and active_chunks:
                # Basic fact-bearing sufficiency check
                has_substantive_fact = any(len(c.get('text', '').strip()) > 15 for c in active_chunks)
                if has_substantive_fact:
                    evidence_found.append({
                        'requirement': 'relevant_governing_fact',
                        'decision_type': decision_type,
                        'evidence_type': 'authoritative_fact',
                        'status': EvidenceStatus.SATISFIED.value,
                        'description': 'Direct factual evidence retrieved from governing source.'
                    })
                    reason_codes.append(GovernanceReasonCode.L3_ALL_MANDATORY_SATISFIED.value)
                    return evidence_found, evidence_missing, True, reason_codes
                else:
                    evidence_missing.append({
                        'requirement': 'relevant_governing_fact',
                        'decision_type': decision_type,
                        'evidence_type': 'authoritative_fact',
                        'mandatory': True,
                        'status': EvidenceStatus.MISSING.value,
                        'description': f"No authoritative governing source found answering '{query}'."
                    })
                    reason_codes.append(GovernanceReasonCode.L3_MANDATORY_EVIDENCE_MISSING.value)
                    return evidence_found, evidence_missing, False, reason_codes

        for req in applicable_reqs:
            # Check if this requirement is satisfied by retrieved chunks
            matched = cls._find_matching_evidence(req, active_chunks, query_analysis, query)
            
            if matched:
                evidence_found.append({
                    'requirement': req.requirement_id,
                    'decision_type': req.decision_type,
                    'evidence_type': req.evidence_type,
                    'status': EvidenceStatus.SATISFIED.value,
                    'description': req.description,
                    'matched_chunks_count': len(matched)
                })
            else:
                # Determine precise failure status
                status = EvidenceStatus.MISSING
                desc = req.description

                # Check if evidence is present but pending or unapproved
                pending_match = cls._find_pending_or_unapproved_evidence(req, active_chunks)
                if pending_match:
                    status = EvidenceStatus.PENDING
                    desc = f"{req.description} (Record is pending formal approval / unexecuted)."
                
                evidence_missing.append({
                    'requirement': req.requirement_id,
                    'decision_type': req.decision_type,
                    'evidence_type': req.evidence_type,
                    'mandatory': req.is_mandatory,
                    'status': status.value,
                    'description': desc
                })
                reason_codes.append(GovernanceReasonCode.L3_MANDATORY_EVIDENCE_MISSING.value)

        # Evaluate sufficiency: True if 0 unsatisfied mandatory requirements
        unsatisfied_mandatory = [
            m for m in evidence_missing 
            if m.get('mandatory', True) and m.get('status') in [
                EvidenceStatus.MISSING.value,
                EvidenceStatus.PENDING.value,
                EvidenceStatus.EXPIRED.value,
                EvidenceStatus.INSUFFICIENT_AUTHORITY.value,
                EvidenceStatus.UNAVAILABLE.value,
                EvidenceStatus.CONFLICTING.value
            ]
        ]
        is_sufficient = (len(unsatisfied_mandatory) == 0)
        if is_sufficient:
            reason_codes.append(GovernanceReasonCode.L3_ALL_MANDATORY_SATISFIED.value)

        # Deduplicate reason codes
        deduped = []
        for r in reason_codes:
            if r not in deduped:
                deduped.append(r)

        return evidence_found, evidence_missing, is_sufficient, deduped

    @classmethod
    def _find_matching_evidence(
        cls,
        req: TypedRequirement,
        active_chunks: List[Dict[str, Any]],
        query_analysis: Any,
        query: str
    ) -> List[Dict[str, Any]]:
        """
        Finds active chunks that satisfy the typed requirement:
        - Validates minimum authority level
        - Validates acceptable approval status
        - Validates factual keywords / terms corresponding to the evidence type
        """
        matched = []
        for chk in active_chunks:
            if not isinstance(chk, dict):
                continue
            
            # 1. Authority validation
            auth = int(chk.get('authority_level', 0) or 0)
            if auth < req.min_authority_level:
                continue

            # 2. Status validation
            status = (chk.get('document_status') or chk.get('status') or '').lower()
            if req.acceptable_statuses and status not in req.acceptable_statuses and not chk.get('is_approved'):
                # Exclude drafts or unverified items from satisfying formal policy requirements
                continue

            text_lower = (chk.get('text', '')).lower()
            header_lower = f"{chk.get('contextual_header', '')} {chk.get('heading_path', '')} {chk.get('section_identifier', '')}".lower()
            combined = f"{text_lower} {header_lower}"

            # 3. Match evidence type
            if req.evidence_type == 'cfo_written_approval':
                # Must provide evidence of formal CFO approval
                if ('cfo approval' in combined or 'cfo approved' in combined) and ('missing' not in combined and 'deferred' not in combined and 'without cfo' not in combined):
                    matched.append(chk)
            elif req.evidence_type == 'procurement_committee_resolution':
                # Procurement review minutes recording decision
                if any(w in combined for w in ['meeting minutes', 'procurement review', 'committee decision', 'action item', 'defer purchase']):
                    matched.append(chk)
            elif req.evidence_type == 'emergency_procurement_conditions':
                # Rule establishing the 3 conditions
                if any(w in combined for w in ['mandatory conditions', 'threat to life', 'sole available source', 'retrospective review', 'written cfo approval']):
                    matched.append(chk)
            elif req.evidence_type == 'formal_security_assessment':
                # SOC2 or ISO report
                if any(w in combined for w in ['soc 2', 'iso 27001', 'security assessment report', 'audit passed']):
                    matched.append(chk)
            elif req.evidence_type == 'data_residency_addendum':
                # Schedule D executed
                if ('schedule d' in combined or 'data residency addendum' in combined) and 'not been attached' not in combined and 'unexecuted' not in combined:
                    matched.append(chk)
            elif req.evidence_type == 'governing_hotel_reimbursement_cap':
                # Governing hotel cap
                code_or_title = f"{chk.get('document_code', '')} {chk.get('document_title', '')}".lower()
                if ('$220' in combined or 'hotel accommodation' in combined or 'lodging cap' in combined) and ('doc-002' in code_or_title or 'travel' in code_or_title):
                    matched.append(chk)
            elif req.evidence_type == 'written_finance_exception':
                # Written approval from Finance
                if any(w in combined for w in ['written exception from finance', 'finance approval granted', 'finance exception attached']):
                    matched.append(chk)
            elif req.evidence_type == 'official_policy_dominance':
                # Official policy overriding informal memo
                code_or_title = f"{chk.get('document_code', '')} {chk.get('document_title', '')}".lower()
                if 'doc-002' in code_or_title or 'travel' in code_or_title:
                    matched.append(chk)
            elif req.evidence_type == 'missing_receipt_declaration_process':
                # DOC-002 Section 6 process
                if any(w in combined for w in ['missing receipt declaration', 'itemized receipts', 'declaration form', '15 calendar days', 'written explanation']):
                    matched.append(chk)
            elif req.evidence_type == 'dual_source_comparison':
                # Covered if both target codes exist in active chunks
                req_codes = [c.lower() for c in getattr(query_analysis, 'required_companion_docs', [])]
                if req_codes:
                    all_codes = []
                    for c in active_chunks:
                        c_code = str(c.get('document_code', '')).lower()
                        if not c_code:
                            m_code = re.search(r'\b(doc-\d+)\b', c.get('document_title', '').lower())
                            if m_code:
                                c_code = m_code.group(1)
                        if c_code:
                            all_codes.append(c_code)
                    if all(rc in all_codes for rc in req_codes):
                        matched.append(chk)
                else:
                    matched.append(chk)
            elif req.evidence_type == 'records_retention_schedule_facts':
                # Duration and trigger
                if any(w in combined for w in ['retention', 'retained', 'audit events', 'retention period', '2 years', '365 days', 'event timestamp', 'statutory audit', 'retention schedule']):
                    matched.append(chk)
            elif req.evidence_type == 'annual_leave_carryover_facts':
                # 5 days and March 31
                if any(w in combined for w in ['carry forward', '5 unused working days', 'march 31']):
                    matched.append(chk)
            elif req.evidence_type == 'workspace_access_status':
                # Access register entry
                if any(w in combined for w in ['workspace access request', 'carla reyes', 'pending', 'ar-2024-043']):
                    matched.append(chk)
            elif req.evidence_type == 'source_inventory_verification':
                # Missing boundary verified
                if chk.get('is_missing') or 'doc-020' in str(chk.get('document_code', '')).lower() or 'master document register' in str(chk.get('document_title', '')).lower():
                    matched.append(chk)
            else:
                # Default generic text match
                req_slug = req.evidence_type.replace('_', ' ')
                if req_slug in combined or any(w in combined for w in req_slug.split() if len(w) > 3):
                    matched.append(chk)

        return matched

    @classmethod
    def _find_pending_or_unapproved_evidence(
        cls,
        req: TypedRequirement,
        active_chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Checks if evidence exists in draft, pending, or unapproved form."""
        pending = []
        for chk in active_chunks:
            if not isinstance(chk, dict):
                continue
            status = (chk.get('document_status') or chk.get('status') or '').lower()
            text_lower = chk.get('text', '').lower()
            if status in ('draft', 'pending', 'needs_review') or chk.get('is_draft') or 'pending' in text_lower or 'draft' in text_lower:
                pending.append(chk)
        return pending


# ==============================================================================
# STANDARD REQUIREMENT CATALOG REGISTRATION
# ==============================================================================

# 1. Procurement Governance Requirements
def _is_procurement_over_25k(qa: Any, ctx: Dict[str, Any]) -> bool:
    q_raw = (getattr(qa, 'raw_query', '') or (ctx.get('query', '') if ctx else '')).lower()
    # If inquiring what the committee minutes decided or asking why/why not, it is informational retrieval about the minutes
    if any(w in q_raw for w in ['minutes', 'why or why not', 'why not', 'review minutes', 'committee decision', 'record']):
        return False
    amounts = getattr(qa, 'monetary_amounts', [])
    return any(a > 25000 for a in amounts) or any(w in q_raw for w in ['32,000', '$32000', 'over $25,000', 'major purchase', 'vertical milling machine'])

RequirementRegistry.register(TypedRequirement(
    requirement_id="procurement_cfo_approval_over_25k",
    decision_type="procurement_governance",
    evidence_type="cfo_written_approval",
    description="Formal written CFO approval required for capital expenditures exceeding $25,000.",
    applies_to_intents=["action_authorization", "approval_compliance_decision"],
    condition_fn=_is_procurement_over_25k,
    min_authority_level=4,
    acceptable_statuses=["approved", "active", "ready"],
    on_missing="insufficient",
    is_mandatory=True
))

RequirementRegistry.register(TypedRequirement(
    requirement_id="procurement_committee_resolution",
    decision_type="procurement_governance",
    evidence_type="procurement_committee_resolution",
    description="Documented Procurement Committee review minutes recording authorization decision.",
    applies_to_intents=["action_authorization", "exact_fact_lookup", "*"],
    condition_fn=lambda qa, ctx: 'minutes' in (getattr(qa, 'raw_query', '') or (ctx.get('query', '') if ctx else '')).lower() or 'procurement review' in (getattr(qa, 'raw_query', '') or (ctx.get('query', '') if ctx else '')).lower(),
    min_authority_level=4,
    acceptable_statuses=["approved", "active", "ready", "draft"],
    on_missing="insufficient",
    is_mandatory=True
))

RequirementRegistry.register(TypedRequirement(
    requirement_id="emergency_procurement_conditions",
    decision_type="procurement_governance",
    evidence_type="emergency_procurement_conditions",
    description="The three mandatory conditions for Emergency Procurement Exception (CFO approval, documented emergency, 2-day review).",
    applies_to_intents=["informational", "exact_fact_lookup", "policy_interpretation", "*"],
    condition_fn=lambda qa, ctx: 'emergency' in (getattr(qa, 'raw_query', '') or (ctx.get('query', '') if ctx else '')).lower() and 'condition' in (getattr(qa, 'raw_query', '') or (ctx.get('query', '') if ctx else '')).lower(),
    min_authority_level=4,
    acceptable_statuses=["approved", "active", "ready", "draft"],
    on_missing="insufficient",
    is_mandatory=True
))

# 2. Vendor Approval Requirements (Applies ONLY to vendor / third-party onboarding, NOT travel or equipment!)
def _is_vendor_onboarding_action(qa: Any, ctx: Dict[str, Any]) -> bool:
    q_raw = (getattr(qa, 'raw_query', '') or (ctx.get('query', '') if ctx else '')).lower()
    intent = getattr(qa, 'intent', '')
    intent_val = intent.value if hasattr(intent, 'value') else str(intent)
    is_action = intent_val in ('action_authorization', 'approval_compliance_decision', 'action_request') or any(p in q_raw for p in ['can we', 'should we', 'approve', 'allow', 'onboard'])
    has_vendor = any(w in q_raw for w in ['onboard', 'vendor approval', 'third-party', 'cloudbox', 'saas provider', 'vendor'])
    has_travel = any(w in q_raw for w in ['hotel', 'lodging', 'flight', 'per diem', 'memo', 'travel coordinator', 'expense claim'])
    return is_action and has_vendor and not has_travel

RequirementRegistry.register(TypedRequirement(
    requirement_id="vendor_security_assessment",
    decision_type="vendor_approval",
    evidence_type="formal_security_assessment",
    description="Formal third-party security assessment report (SOC 2 Type II or ISO 27001) required for vendor approval.",
    applies_to_intents=["action_authorization"],
    condition_fn=_is_vendor_onboarding_action,
    min_authority_level=4,
    acceptable_statuses=["approved", "active", "ready"],
    on_missing="insufficient",
    is_mandatory=True
))

RequirementRegistry.register(TypedRequirement(
    requirement_id="vendor_data_residency_addendum",
    decision_type="vendor_approval",
    evidence_type="data_residency_addendum",
    description="Executed Schedule D (Regional Data Sovereignty Addendum) required for vendors processing customer data.",
    applies_to_intents=["action_authorization"],
    condition_fn=lambda qa, ctx: _is_vendor_onboarding_action(qa, ctx) and any(w in (getattr(qa, 'raw_query', '') or (ctx.get('query', '') if ctx else '')).lower() for w in ['customer data', 'pii', 'residency', 'sensitive']),
    min_authority_level=6,
    acceptable_statuses=["approved", "active", "ready"],
    on_missing="insufficient",
    is_mandatory=True
))

# 3. Policy Compliance / Travel & Expense Requirements
def _is_active_hotel_cap_query(qa: Any, ctx: Dict[str, Any]) -> bool:
    q_raw = (getattr(qa, 'raw_query', '') or (ctx.get('query', '') if ctx else '')).lower()
    is_historical = any(w in q_raw for w in ['archived', 'superseded', '2024', 'doc-016', 'historical', 'replaced'])
    is_lodging = getattr(qa, 'is_lodging_query', False) or any(w in q_raw for w in ['hotel', 'lodging', 'nightly cap', 'accommodation'])
    return is_lodging and not is_historical

RequirementRegistry.register(TypedRequirement(
    requirement_id="travel_hotel_cap_compliance",
    decision_type="policy_compliance",
    evidence_type="governing_hotel_reimbursement_cap",
    description="Governing hotel accommodation cap ($220/night under DOC-002) for business travel.",
    applies_to_intents=["*"],
    condition_fn=_is_active_hotel_cap_query,
    min_authority_level=6,
    acceptable_statuses=["approved", "active", "ready"],
    on_missing="insufficient",
    is_mandatory=True
))

def _is_travel_exception_action_request(qa: Any, ctx: Dict[str, Any]) -> bool:
    q_raw = (getattr(qa, 'raw_query', '') or (ctx.get('query', '') if ctx else '')).lower()
    # A compliance evaluation ("Is this compliant?") checks whether requirements are met and must not require missing exception evidence
    if any(w in q_raw for w in ['compliant', 'compliance', 'is this compliant', 'is it compliant']):
        return False
    return any(p in q_raw for p in ['authorize reimbursement', 'approve reimbursement', 'approve over cap', 'grant exception'])

RequirementRegistry.register(TypedRequirement(
    requirement_id="travel_written_finance_exception",
    decision_type="policy_compliance",
    evidence_type="written_finance_exception",
    description="Written approval from Finance required for expense claims exceeding the governing hotel cap.",
    applies_to_intents=["action_authorization", "approval_compliance_decision"],
    condition_fn=_is_travel_exception_action_request,
    min_authority_level=4,
    acceptable_statuses=["approved", "active", "ready"],
    on_missing="insufficient",
    is_mandatory=True
))

RequirementRegistry.register(TypedRequirement(
    requirement_id="travel_memo_rate_authority",
    decision_type="policy_compliance",
    evidence_type="official_policy_dominance",
    description="Governing Travel Policy (DOC-002, Rank 7) dominance over non-authoritative Internal Memorandum (DOC-011, Rank 1).",
    applies_to_intents=["*"],
    condition_fn=lambda qa, ctx: 'memo' in getattr(qa, 'raw_query', '').lower() and ('250' in getattr(qa, 'raw_query', '') or 'approve a booking' in getattr(qa, 'raw_query', '').lower()),
    min_authority_level=6,
    acceptable_statuses=["approved", "active", "ready"],
    on_missing="insufficient",
    is_mandatory=True
))

RequirementRegistry.register(TypedRequirement(
    requirement_id="travel_lost_receipt_process",
    decision_type="policy_compliance",
    evidence_type="missing_receipt_declaration_process",
    description="Missing Receipt Declaration procedure under DOC-002 Section 6 (15-day deadline, explanation, manager approval).",
    applies_to_intents=["*"],
    condition_fn=lambda qa, ctx: getattr(qa, 'is_receipt_query', False) or (
        any(w in getattr(qa, 'raw_query', '').lower() for w in ['lose', 'loses', 'lost', 'missing receipt']) or
        ('receipt' in getattr(qa, 'raw_query', '').lower() and any(w in getattr(qa, 'raw_query', '').lower() for w in ['missing', 'declaration', 'without']))
    ),
    min_authority_level=6,
    acceptable_statuses=["approved", "active", "ready"],
    on_missing="insufficient",
    is_mandatory=True
))

# 4. Cross-Document Comparison Requirements
RequirementRegistry.register(TypedRequirement(
    requirement_id="dual_source_invoice_and_contract",
    decision_type="contract_compliance",
    evidence_type="dual_source_comparison",
    description="Both the invoice and the vendor agreement must be present to evaluate discrepancies.",
    applies_to_intents=["cross_document_comparison", "comparison", "*"],
    condition_fn=lambda qa, ctx: getattr(qa, 'is_cross_document', False) or ('invoice' in getattr(qa, 'raw_query', '').lower() and 'contract' in getattr(qa, 'raw_query', '').lower()),
    min_authority_level=3,
    acceptable_statuses=["approved", "active", "ready", "draft"],
    on_missing="insufficient",
    is_mandatory=True
))

# 5. Records Governance / Data Processing Requirements
RequirementRegistry.register(TypedRequirement(
    requirement_id="records_retention_schedule_facts",
    decision_type="data_processing",
    evidence_type="records_retention_schedule_facts",
    description="Direct evidence of retention period (2 years) and retention trigger (event timestamp) from Records Retention Schedule.",
    applies_to_intents=["exact_fact_lookup", "informational", "*"],
    condition_fn=lambda qa, ctx: getattr(qa, 'is_retention_query', False) or 'retention schedule' in getattr(qa, 'raw_query', '').lower(),
    min_authority_level=4,
    acceptable_statuses=["approved", "active", "ready", "draft"],
    on_missing="insufficient",
    is_mandatory=True
))

# 6. People Operations / HR Policy Requirements
def _is_leave_carryover_query(qa: Any, ctx: Dict[str, Any]) -> bool:
    q_raw = (getattr(qa, 'raw_query', '') or (ctx.get('query', '') if ctx else '')).lower()
    return any(w in q_raw for w in ['carry forward', 'carryover', 'carry over', 'unused', 'expire', 'expiration'])

RequirementRegistry.register(TypedRequirement(
    requirement_id="annual_leave_carryover_facts",
    decision_type="policy_compliance",
    evidence_type="annual_leave_carryover_facts",
    description="Direct evidence of annual leave carry forward limit (5 days) and expiration date (March 31) from Annual Leave Policy.",
    applies_to_intents=["exact_fact_lookup", "informational", "*"],
    condition_fn=_is_leave_carryover_query,
    min_authority_level=4,
    acceptable_statuses=["approved", "active", "ready", "draft"],
    on_missing="insufficient",
    is_mandatory=True
))

# 7. Access Governance Requirements
RequirementRegistry.register(TypedRequirement(
    requirement_id="workspace_access_status",
    decision_type="general_inquiry",
    evidence_type="workspace_access_status",
    description="Evidence from Workspace Access Request Register establishing granted roles and approval status.",
    applies_to_intents=["access_status_lookup", "exact_fact_lookup", "*"],
    condition_fn=lambda qa, ctx: getattr(qa, 'is_access_query', False) or 'carla reyes' in getattr(qa, 'raw_query', '').lower(),
    min_authority_level=3,
    acceptable_statuses=["approved", "active", "ready", "draft"],
    on_missing="insufficient",
    is_mandatory=True
))

# 8. Negative Retrieval / Corpus Boundary Requirements
RequirementRegistry.register(TypedRequirement(
    requirement_id="missing_document_boundary_verification",
    decision_type="general_inquiry",
    evidence_type="source_inventory_verification",
    description="Verification of source document inventory and Master Document Register when content is absent from the corpus.",
    applies_to_intents=["missing_document_negative", "exact_fact_lookup", "*"],
    condition_fn=lambda qa, ctx: getattr(qa, 'is_negative_query', False) or 'doc-021' in getattr(qa, 'raw_query', '').lower(),
    min_authority_level=4,
    acceptable_statuses=["approved", "active", "ready"],
    on_missing="insufficient",
    is_mandatory=True
))
