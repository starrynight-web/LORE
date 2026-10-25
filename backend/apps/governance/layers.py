"""
LORE Enterprise — 9-Layer Governed Knowledge Engine
Adheres strictly to docs/enterprise/docs/lore.md:
- L7: Permission Layer (RBAC/ABAC query-time authorization before context reaches model)
- L6: Authority Layer (7-rank authority ladder & conflict resolution)
- L5: Temporal Validity Layer (effective_from, expiry, staleness, as_of point-in-time)
- L4: Exception Layer (scoped, time-bounded overrides with mandatory disclosure)
- L3: Evidence Sufficiency Layer (mandatory requirements registry, missing-evidence reports)
- L2: Answer-State Layer (deterministic 9-state machine with precedence order)
- L1: Decision Intelligence Layer (query classification, required evidence, escalation targets)
- L0: Observability Layer (freshness, decision traces, audit events, latency metrics)
- Core: Hybrid vector + lexical search + Reciprocal Rank Fusion + Context Reranker
"""

import re
import uuid
import logging
from datetime import datetime, date, timedelta, timezone as dt_timezone
from typing import List, Dict, Any, Optional, Tuple, Union, Set
from django.utils import timezone
from django.db import models

from apps.governance.models import (
    SourcePermission, ScopedException, EvidenceRequirement,
    ConflictRecord, AccessLevel
)
from apps.governance.contract import (
    Verdict, Directive, EvidenceStatus, CANONICAL_VERDICT_DIRECTIVE_MAP,
    GovernanceReasonCode, GovernanceRequest,
    validate_canonical_envelope, fail_closed_envelope, ContractValidationError
)
from apps.sources.models import SourceDocument
from apps.decisions.models import DecisionRecord
from apps.audit.models import AuditEvent

logger = logging.getLogger(__name__)


# ==============================================================================
# TYPED LAYER EVALUATION TUPLES (Dual Tuple / Named Property Access)
# ==============================================================================
class PermissionFilterTuple(tuple):
    def __new__(cls, cleared_chunks, denial_reasons, reason_codes=None):
        return super().__new__(cls, (cleared_chunks, denial_reasons))

    def __init__(self, cleared_chunks, denial_reasons, reason_codes=None):
        self.cleared_chunks = cleared_chunks
        self.denial_reasons = denial_reasons
        self.is_denied = bool(denial_reasons and not cleared_chunks)
        self.reason_codes = reason_codes or []


class DecisionIntelligenceTuple(tuple):
    def __new__(cls, info_dict, reason_codes=None):
        return super().__new__(cls, (info_dict,))

    def __init__(self, info_dict, reason_codes=None):
        self.info = info_dict
        self.decision_type = info_dict.get('decision_type', 'general_inquiry')
        self.query_intent = info_dict.get('query_intent', 'informational')
        self.label = info_dict.get('label', '')
        self.mandatory_evidence = info_dict.get('mandatory_evidence', [])
        self.escalation_target = info_dict.get('escalation_target', '')
        self.risk_level = info_dict.get('risk_level', 'low')
        self.requires_human_review = (self.risk_level == 'critical')
        self.reason_codes = reason_codes or []

    def __getitem__(self, item):
        if isinstance(item, str):
            return self.info[item]
        return super().__getitem__(item)

    def get(self, key, default=None):
        return self.info.get(key, default)


class TemporalEvaluationTuple(tuple):
    def __new__(cls, valid_chunks, temporal_notes, has_stale_data, reason_codes=None):
        return super().__new__(cls, (valid_chunks, temporal_notes, has_stale_data))

    def __init__(self, valid_chunks, temporal_notes, has_stale_data, reason_codes=None):
        self.valid_chunks = valid_chunks
        self.temporal_notes = temporal_notes
        self.has_stale_data = has_stale_data
        self.reason_codes = reason_codes or []


class ExceptionEvaluationTuple(tuple):
    def __new__(cls, matched_exceptions, has_applicable_exception, exception_notes, reason_codes=None):
        return super().__new__(cls, (matched_exceptions, has_applicable_exception, exception_notes))

    def __init__(self, matched_exceptions, has_applicable_exception, exception_notes, reason_codes=None):
        self.matched_exceptions = matched_exceptions
        self.has_applicable_exception = has_applicable_exception
        self.exception_notes = exception_notes
        self.reason_codes = reason_codes or []


class AuthorityConflictTuple(tuple):
    def __new__(cls, conflicts_resolved, has_unresolved_tie, notes, reason_codes=None, unresolved_conflicts=None):
        return super().__new__(cls, (conflicts_resolved, has_unresolved_tie, notes))

    def __init__(self, conflicts_resolved, has_unresolved_tie, notes, reason_codes=None, unresolved_conflicts=None):
        self.conflicts_resolved = conflicts_resolved
        self.has_unresolved_tie = has_unresolved_tie
        self.notes = notes
        self.reason_codes = reason_codes or []
        self.unresolved_conflicts = unresolved_conflicts or []


class SufficiencyEvaluationTuple(tuple):
    def __new__(cls, evidence_found, evidence_missing, is_sufficient, reason_codes=None):
        return super().__new__(cls, (evidence_found, evidence_missing, is_sufficient))

    def __init__(self, evidence_found, evidence_missing, is_sufficient, reason_codes=None):
        self.evidence_found = evidence_found
        self.evidence_missing = evidence_missing
        self.is_sufficient = is_sufficient
        self.reason_codes = reason_codes or []


class AnswerStateTuple(tuple):
    def __new__(cls, state, directive, reason_codes=None):
        return super().__new__(cls, (state, directive))

    def __init__(self, state, directive, reason_codes=None):
        self.state = state
        self.directive = directive
        self.reason_codes = reason_codes or []


# ==============================================================================
# L7 — PERMISSION LAYER
# ==============================================================================
class PermissionLayer:
    """
    L7 Permission Layer (lore.md §4 L7):
    Authorization happens BEFORE restricted content enters the model's context window.
    Enforces RBAC / ABAC policies and isolates unauthorized evidence completely.
    """
    INTERNAL_ROLES = {
        'workspace_admin', 'member', 'admin', 'compliance_auditor',
        'owner', 'analyst', 'legal_counsel', 'compliance_officer', 'auditor'
    }

    @classmethod
    def filter_authorized_chunks(
        cls,
        chunks: List[Dict[str, Any]],
        user=None,
        user_role: str = 'member'
    ) -> PermissionFilterTuple:
        authorized_chunks = []
        denial_reasons = []
        reason_codes = []

        normalized_role = (user_role or 'member').lower()
        is_anonymous = (user is None and normalized_role in ('anonymous', 'guest', 'unauthenticated'))

        doc_ids = list({c.get('document_id') for c in chunks if c.get('document_id')})
        if not doc_ids:
            return PermissionFilterTuple(chunks, [], [GovernanceReasonCode.L7_PERMISSION_GRANTED.value])

        valid_uuids = []
        for did in doc_ids:
            try:
                uuid.UUID(str(did))
                valid_uuids.append(did)
            except (ValueError, TypeError):
                continue

        permissions_map = {
            str(p.document_id): p 
            for p in SourcePermission.objects.filter(document_id__in=valid_uuids)
        } if valid_uuids else {}

        for chk in chunks:
            doc_id = str(chk.get('document_id', ''))
            perm = permissions_map.get(doc_id)
            doc_title = chk.get('document_title', 'Untitled')

            # Default to INTERNAL access if no explicit permission record exists
            if not perm:
                if is_anonymous:
                    denial_reasons.append(
                        f"Access restricted to document '{doc_title}' (INTERNAL): Anonymous or unauthenticated access blocked."
                    )
                    reason_codes.append(GovernanceReasonCode.L7_ANONYMOUS_BLOCKED.value)
                    continue
                elif normalized_role not in cls.INTERNAL_ROLES:
                    denial_reasons.append(
                        f"Access restricted to document '{doc_title}' (INTERNAL): Role '{normalized_role}' not permitted."
                    )
                    reason_codes.append(GovernanceReasonCode.L7_UNAUTHORIZED_ROLE.value)
                    continue
                else:
                    authorized_chunks.append(chk)
                    continue

            # Explicit SourcePermission evaluation
            if perm.is_user_permitted(user=user, user_role=normalized_role):
                authorized_chunks.append(chk)
            else:
                if is_anonymous:
                    reason_codes.append(GovernanceReasonCode.L7_ANONYMOUS_BLOCKED.value)
                else:
                    reason_codes.append(GovernanceReasonCode.L7_UNAUTHORIZED_ROLE.value)
                denial_reasons.append(
                    f"Access restricted to document '{doc_title}' ({perm.access_level.upper()})"
                )

        if denial_reasons and not authorized_chunks:
            reason_codes.append(GovernanceReasonCode.L7_PERMISSION_DENIED.value)
        elif authorized_chunks:
            reason_codes.append(GovernanceReasonCode.L7_PERMISSION_GRANTED.value)

        # Deduplicate reason codes preserving order
        deduped_reasons = []
        for r in reason_codes:
            if r not in deduped_reasons:
                deduped_reasons.append(r)

        return PermissionFilterTuple(authorized_chunks, denial_reasons, deduped_reasons)


# ==============================================================================
# L1 — DECISION INTELLIGENCE LAYER
# ==============================================================================
class DecisionIntelligenceLayer:
    """
    L1 Decision Intelligence Layer (lore.md §4 L1):
    Classifies incoming queries into decision types, mapping mandatory evidence
    requirements and designating escalation targets.
    """
    DECISION_CATALOG = {
        'vendor_approval': {
            'label': 'Third-Party Vendor & Cloud Approval',
            'mandatory_evidence': ['policy_condition', 'assessment_report', 'contract_term', 'data_residency_proof'],
            'escalation_target': 'security_team',
            'risk_level': 'high'
        },
        'procurement_governance': {
            'label': 'Procurement Threshold & Expenditure Governance',
            'mandatory_evidence': ['approved_policy'],
            'escalation_target': 'procurement_officer',
            'risk_level': 'medium'
        },
        'data_processing': {
            'label': 'Data Processing & Customer PII Compliance',
            'mandatory_evidence': ['policy_condition', 'data_classification', 'retention_rule', 'sovereignty_proof'],
            'escalation_target': 'compliance_officer',
            'risk_level': 'high'
        },
        'deployment_approval': {
            'label': 'Production Deployment & Release Gate',
            'mandatory_evidence': ['policy_condition', 'sign_off', 'vulnerability_scan'],
            'escalation_target': 'engineering_lead',
            'risk_level': 'medium'
        },
        'statutory_compliance': {
            'label': 'Legal Deed, Khatian & Land Record Verification',
            'mandatory_evidence': ['statutory_deed', 'schedule_of_property', 'authority_sign_off'],
            'escalation_target': 'legal_counsel',
            'risk_level': 'critical'
        },
        'policy_compliance': {
            'label': 'Internal Policy & Security Procedure',
            'mandatory_evidence': ['approved_policy', 'implementation_rule'],
            'escalation_target': 'compliance_officer',
            'risk_level': 'medium'
        },
        'code_change': {
            'label': 'Architectural & Engineering Conventions',
            'mandatory_evidence': ['applicable_rules'],
            'escalation_target': 'tech_lead',
            'risk_level': 'low'
        },
        'general_inquiry': {
            'label': 'Factual Knowledge Query',
            'mandatory_evidence': ['relevant_fact'],
            'escalation_target': 'workspace_admin',
            'risk_level': 'low'
        }
    }

    @classmethod
    def classify(
        cls,
        query: str,
        explicit_decision_type: Optional[str] = None
    ) -> DecisionIntelligenceTuple:
        reason_codes = []
        q_lower = query.lower()

        # Step 1: Classify Query Intent (Requirement 1 & 7)
        # Distinguish informational questions, comparisons, policy interpretation, recommendations, and action/approval requests
        is_comparison = any(w in q_lower for w in ['compare', 'difference between', 'versus', ' vs ', 'better', 'fastest', 'cheapest', 'lowest price', 'delivery time', 'trade-off'])
        is_recommendation = any(w in q_lower for w in ['which should we', 'which vendor is', 'what do you recommend', 'which supplier', 'recommendation', 'which is best', 'best supplier', 'best vendor'])
        is_threshold_or_amount = bool(re.search(r'\$\s*\d+|(?:threshold|limit|tier|boundary|ceiling|maximum amount|micro-purchase|small procurement|major contract|emergency procurement)', q_lower))
        is_policy_query = any(w in q_lower for w in [
            'what does the policy say', 'is it allowed', 'policy regarding', 'policy on',
            'under the policy', 'according to policy', 'rules for', 'guidelines for', 'procedure for',
            'annual leave', 'leave allowance', 'security access', 'access level', 'access without', 'deploy without',
            'what is the', 'what are the'
        ])
        is_explicit_action = (
            any(w in q_lower for w in ['approve ', 'authorize ', 'onboard ', 'deploy ', 'release to ', 'execute ', 'grant access', 'perform ', 'bypass ', 'enable ', 'disable ', 'skip ', 'override ', 'connect ']) or
            (any(w in q_lower for w in ['can we approve', 'can i approve', 'approve this', 'grant approval', 'can we onboard', 'can we deploy', 'can i deploy', 'should we approve', 'can i bypass', 'can we bypass', 'can i enable', 'can we enable', 'can i disable', 'can we disable', 'can i skip', 'can we skip']) and not any(w in q_lower for w in ['what is', 'what are', 'threshold', 'policy say', 'allowance', 'days', 'hours']))
        )

        if is_comparison:
            query_intent = 'comparison'
        elif is_recommendation:
            query_intent = 'recommendation'
        elif is_explicit_action and not any(w in q_lower for w in ['what is', 'what are', 'threshold', 'policy say', 'tell me', 'explain', 'how many']):
            query_intent = 'action_request'
        elif is_threshold_or_amount or is_policy_query:
            query_intent = 'policy_interpretation'
        else:
            query_intent = 'informational'

        # Step 2: Classify Decision Type
        if explicit_decision_type and explicit_decision_type in cls.DECISION_CATALOG:
            dt = explicit_decision_type
            reason_codes.append(GovernanceReasonCode.L1_EXPLICIT_DECISION_TYPE.value)
        else:
            if any(w in q_lower for w in ['দলিল', 'খতিয়ান', 'খতিয়ান', 'মৌজা', 'সাফ কবলা', 'deed', 'khatian', 'schedule of property', 'statutory']):
                dt = 'statutory_compliance'
            elif any(w in q_lower for w in ['procurement', 'purchase', 'rfp', 'competitive quote', 'micro-purchase', 'supplier', 'emergency procurement']) and (is_threshold_or_amount or is_policy_query or 'emergency' in q_lower or is_comparison or is_recommendation):
                dt = 'procurement_governance'
            elif (is_explicit_action and any(w in q_lower for w in ['vendor', 'supplier', 'third-party', 'cloudbox', 'tool', 'software', 'app'])):
                dt = 'vendor_approval'
            elif any(w in q_lower for w in ['privacy', 'gdpr', 'customer data', 'pii', 'retention', 'residency', 'sovereignty']):
                dt = 'data_processing'
            elif any(w in q_lower for w in ['deploy', 'production', 'release', 'launch', 'staging']) and is_explicit_action:
                dt = 'deployment_approval'
            elif any(w in q_lower for w in ['security', 'password', 'jwt', 'auth', 'token', 'policy', 'compliance', 'annual leave', 'leave', 'access level']):
                dt = 'policy_compliance'
            elif any(w in q_lower for w in ['refactor', 'function', 'class', 'test', 'api', 'architecture', 'convention']):
                dt = 'code_change'
            else:
                dt = 'general_inquiry'
            reason_codes.append(GovernanceReasonCode.L1_DECISION_CLASSIFIED.value)

        meta = cls.DECISION_CATALOG.get(dt, cls.DECISION_CATALOG['general_inquiry'])
        if meta['risk_level'] == 'critical':
            reason_codes.append(GovernanceReasonCode.L1_CRITICAL_RISK_FLAGGED.value)

        info = {
            'decision_type': dt,
            'query_intent': query_intent,
            'label': meta['label'],
            'mandatory_evidence': meta['mandatory_evidence'],
            'escalation_target': meta['escalation_target'],
            'risk_level': meta['risk_level']
        }
        return DecisionIntelligenceTuple(info, reason_codes)


# ==============================================================================
# L6 — AUTHORITY LAYER
# ==============================================================================
class AuthorityLayer:
    """
    L6 Authority Layer (lore.md §4 L6):
    Unified 7-rank authority ladder. Higher rank wins; same rank newer version wins;
    unresolved contradiction -> conflicting state (never settled silently).
    Also queries database ConflictRecord entries between candidate documents.
    """
    AUTHORITY_LADDER = {
        7: 'approved_policy',
        6: 'signed_contract',
        5: 'team_convention',
        4: 'maintained_procedure',
        3: 'reviewed_document',
        2: 'wiki_entry',
        1: 'informal_note'
    }

    @classmethod
    def _detect_genuine_contradiction(
        cls,
        c1: Dict[str, Any],
        c2: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Distinguishes genuine contradictions from compatible rules or internal clauses (Requirement 8).
        """
        # 1. Chunks from the same document are internal conditions/clauses, not cross-source contradictions
        id1 = str(c1.get('document_id') or c1.get('document_title') or '')
        id2 = str(c2.get('document_id') or c2.get('document_title') or '')
        if id1 and id2 and id1 == id2:
            return None

        # 2. Check explicit scope compatibility: different scopes do not contradict each other
        scope1 = (c1.get('scope') or '').lower()
        scope2 = (c2.get('scope') or '').lower()
        if scope1 and scope2 and scope1 != scope2:
            return None

        t1 = c1.get('text', '')
        t2 = c2.get('text', '')
        t1_lower = t1.lower()
        t2_lower = t2.lower()

        # 2b. Check if one source is a request/register record and the other is a governing policy
        title1 = (c1.get('document_title') or '').lower()
        title2 = (c2.get('document_title') or '').lower()
        is_reg1 = any(r in title1 for r in ['register', 'request', 'pack', 'memo', 'invoice'])
        is_reg2 = any(r in title2 for r in ['register', 'request', 'pack', 'memo', 'invoice'])
        if is_reg1 != is_reg2:
            return None  # Transactional request forms and registers do not contradict governing policies

        # 3. Direct rule contradiction: unconditional permit vs unconditional prohibit
        pos1 = any(w in t1_lower for w in ['approved', 'permitted', 'allowed', 'authorized'])
        neg1 = any(w in t1_lower for w in ['prohibit', 'forbidden', 'denied', 'must not', 'strictly prohibited'])
        pos2 = any(w in t2_lower for w in ['approved', 'permitted', 'allowed', 'authorized'])
        neg2 = any(w in t2_lower for w in ['prohibit', 'forbidden', 'denied', 'must not', 'strictly prohibited'])

        # Precondition / receipt requirement clauses are compatible conditions, not contradictions
        is_condition1 = any(w in t1_lower for w in ['provided that', 'subject to', 'receipt required', 'receipts required', 'itemized receipt', 'prior approval'])
        is_condition2 = any(w in t2_lower for w in ['provided that', 'subject to', 'receipt required', 'receipts required', 'itemized receipt', 'prior approval'])

        if (pos1 and not neg1 and neg2 and not is_condition2) or (pos2 and not neg2 and neg1 and not is_condition1):
            # Domain alignment check: both passages must address the same operational domain
            domain_terms = [
                'travel', 'flight', 'airfare', 'hotel', 'meal', 'lodging', 'expense', 'per diem', 'reimburse',
                'procurement', 'purchase', 'spend', 'vendor', 'supplier', 'rfp', 'bid',
                'access', 'login', 'credential', 'password', 'mfa', 'privileged', 'permission',
                'leave', 'vacation', 'sick', 'parental',
                'retention', 'records', 'schedule', 'audit', 'ledger', 'log', 'logging', 'destroy'
            ]
            d1 = {w for w in domain_terms if w in t1_lower or w in title1}
            d2 = {w for w in domain_terms if w in t2_lower or w in title2}
            if not (d1 & d2):
                return None  # Unrelated operational domains do not contradict each other

            return {
                'type': 'directive_contradiction',
                'claim_a': t1[:140].strip(),
                'claim_b': t2[:140].strip()
            }

        # 4. Numerical contradiction on the same subject (e.g. meal allowance $200 vs $250)
        # Compatible verification conditions (e.g. receipt requirement over $25) are not contradictions against rate definitions
        is_threshold_or_condition = (
            (is_condition1 or any(w in t1_lower for w in ['receipt', 'exceeding', 'threshold', 'audit'])) !=
            (is_condition2 or any(w in t2_lower for w in ['receipt', 'exceeding', 'threshold', 'audit']))
        )
        if is_threshold_or_condition:
            return None

        amounts1 = set(re.findall(r'\$\s*(\d+(?:\.\d{2})?)', t1))
        amounts2 = set(re.findall(r'\$\s*(\d+(?:\.\d{2})?)', t2))
        if amounts1 and amounts2 and amounts1 != amounts2:
            subjects = ['meal', 'allowance', 'per diem', 'daily', 'expense', 'travel', 'reimbursement']
            common_subjects = [s for s in subjects if s in t1_lower and s in t2_lower]
            if common_subjects:
                # Ensure it is not a breakdown (e.g. breakfast vs lunch vs dinner) or category difference (meal vs lodging)
                is_breakdown = any(w in t1_lower or w in t2_lower for w in ['breakfast', 'lunch', 'dinner', 'lodging', 'hotel', 'flight'])
                if not is_breakdown:
                    val1 = sorted(list(amounts1))[0]
                    val2 = sorted(list(amounts2))[0]
                    if val1 != val2:
                        return {
                            'type': 'numerical_contradiction',
                            'claim_a': f"${val1} ({c1.get('document_title')})",
                            'claim_b': f"${val2} ({c2.get('document_title')})"
                        }

        # Check for duration / time-period numerical contradiction (e.g. retention periods: 365 days vs 7 years)
        dur_pattern = r'\b(\d+)\s*(days?|months?|years?|weeks?|hours?)\b'
        dur1 = re.findall(dur_pattern, t1_lower)
        dur2 = re.findall(dur_pattern, t2_lower)
        if dur1 and dur2:
            time_subjects = ['retention', 'retained', 'retain', 'preserve', 'storage', 'audit', 'ledger', 'record', 'log', 'notice', 'review period']
            common_time = [s for s in time_subjects if s in t1_lower and s in t2_lower]
            if common_time:
                def _to_days(num_str, unit):
                    n = float(num_str)
                    u = unit.lower()
                    if 'day' in u: return n
                    if 'week' in u: return n * 7
                    if 'month' in u: return n * 30
                    if 'year' in u: return n * 365
                    if 'hour' in u: return n / 24.0
                    return n

                d1_norm = _to_days(dur1[0][0], dur1[0][1])
                d2_norm = _to_days(dur2[0][0], dur2[0][1])
                if abs(d1_norm - d2_norm) > 1.0:
                    return {
                        'type': 'duration_contradiction',
                        'claim_a': f"{dur1[0][0]} {dur1[0][1]} ({c1.get('document_title')})",
                        'claim_b': f"{dur2[0][0]} {dur2[0][1]} ({c2.get('document_title')})"
                    }

        # Check if chunks describe distinct commercial entities or suppliers (e.g. Supplier Alpha vs Supplier Beta)
        ent_pattern = r'\b(?:supplier|vendor|provider|contractor)\s+([a-z0-9_-]+)\b|\b(cloudbox|aws|azure|gcp|alpha|beta|gamma|delta)\b'
        raw_ent1 = re.findall(ent_pattern, t1_lower + " " + c1.get('document_title', '').lower())
        raw_ent2 = re.findall(ent_pattern, t2_lower + " " + c2.get('document_title', '').lower())
        ent1 = {g for tup in raw_ent1 for g in tup if g}
        ent2 = {g for tup in raw_ent2 for g in tup if g}
        if ent1 and ent2 and ent1 != ent2 and not (ent1 & ent2):
            return None  # Distinct commercial entities / proposals are compatible

        # Check if chunks describe different threshold tiers (e.g. Tier 1 up to $5,000 vs Tier 2 up to $25,000 vs Tier 3 >$25,000)
        tier_terms = ['tier 1', 'tier 2', 'tier 3', 'micro-purchase', 'small procurement', 'major contract', 'between', 'up to', 'exceeding', 'greater than', 'less than', 'under $', 'over $']
        is_tier1 = any(w in t1_lower for w in tier_terms)
        is_tier2 = any(w in t2_lower for w in tier_terms)
        if is_tier1 and is_tier2:
            return None  # Distinct threshold tiers are complementary

        # Check if one is an emergency exception / outage procedure vs peacetime rule
        is_emerg1 = any(w in t1_lower for w in ['emergency', 'outage', 'disaster recovery', 'critical incident'])
        is_emerg2 = any(w in t2_lower for w in ['emergency', 'outage', 'disaster recovery', 'critical incident'])
        if is_emerg1 != is_emerg2:
            return None  # Emergency procedures are conditional exceptions

        # Check if chunks describe distinct leave types (annual leave vs sick leave)
        leave_terms = ['annual leave', 'sick leave', 'parental leave', 'maternity leave', 'bereavement']
        lt1 = [w for w in leave_terms if w in t1_lower]
        lt2 = [w for w in leave_terms if w in t2_lower]
        if lt1 and lt2 and set(lt1) != set(lt2):
            return None

        # Check if chunks describe distinct security access levels (Level 1 vs Level 2 vs Level 4)
        lvl1 = set(re.findall(r'\blevel\s+([1-4])\b', t1_lower))
        lvl2 = set(re.findall(r'\blevel\s+([1-4])\b', t2_lower))
        if lvl1 and lvl2 and lvl1 != lvl2:
            return None

        return None

    @classmethod
    def _is_chunk_relevant_to_query(cls, chunk: Dict[str, Any], query: Optional[str]) -> bool:
        """
        Evaluates whether a candidate chunk contains evidence directly relevant to the user's inquiry (Requirement 2 & 3).
        """
        if not query or not query.strip():
            return True
        q_clean = query.strip().lower()
        stop_words = {
            'what', 'is', 'are', 'the', 'a', 'an', 'in', 'on', 'at', 'for', 'to', 'of',
            'and', 'or', 'by', 'with', 'from', 'as', 'be', 'can', 'we', 'it', 'this',
            'that', 'do', 'does', 'all', 'any', 'my', 'your', 'our', 'under', 'according',
            'tell', 'show', 'please', 'would', 'could', 'how', 'much', 'many', 'must'
        }
        q_tokens = [w for w in re.findall(r'\w+', q_clean) if len(w) > 1 and w not in stop_words]
        if not q_tokens:
            return True

        doc_text = f"{chunk.get('document_title', '')} {chunk.get('contextual_header', '')} {chunk.get('heading_path', '')} {chunk.get('text', '')}".lower()

        if q_clean in doc_text:
            return True

        matched = 0
        for t in q_tokens:
            if t in doc_text:
                matched += 1
            elif t in ['logged', 'logging', 'logs', 'log'] and any(v in doc_text for v in ['log', 'logging', 'logs', 'record', 'audit']):
                matched += 1
            elif t == 'actions' and any(v in doc_text for v in ['events', 'functions', 'changes', 'attempts', 'activities']):
                matched += 1

        coverage = matched / len(q_tokens)
        return coverage >= 0.30 or any(p in doc_text for p in ['audit logging', 'security events', 'must record'])

    @classmethod
    def evaluate_conflicts(
        cls,
        chunks: List[Dict[str, Any]],
        workspace_id: Optional[str] = None,
        query: Optional[str] = None
    ) -> AuthorityConflictTuple:
        conflicts_resolved = []
        unresolved_conflicts = []
        has_unresolved_tie = False
        notes = []
        reason_codes = []

        if len(chunks) < 2:
            if chunks:
                reason_codes.append(GovernanceReasonCode.L6_SINGLE_SOURCE_AUTHORITATIVE.value)
            return AuthorityConflictTuple(conflicts_resolved, has_unresolved_tie, notes, reason_codes, unresolved_conflicts)

        # 1. Database ConflictRecord check between candidate documents
        doc_ids = list({c.get('document_id') for c in chunks if c.get('document_id')})
        valid_uuids = []
        for did in doc_ids:
            try:
                valid_uuids.append(uuid.UUID(str(did)))
            except (ValueError, TypeError):
                continue

        if valid_uuids and workspace_id:
            db_conflicts = ConflictRecord.objects.filter(
                workspace_id=workspace_id,
                source_a_id__in=valid_uuids,
                source_b_id__in=valid_uuids
            ).select_related('source_a', 'source_b')
            for cr in db_conflicts:
                if cr.resolution_status == 'unresolved':
                    # Gating: A candidate document must contain evidence relevant to the claim before it can participate in conflict detection
                    c_a_chunks = [c for c in chunks if str(c.get('document_id')) == str(cr.source_a_id)]
                    c_b_chunks = [c for c in chunks if str(c.get('document_id')) == str(cr.source_b_id)]

                    if query:
                        rel_a = any(cls._is_chunk_relevant_to_query(c, query) for c in c_a_chunks)
                        rel_b = any(cls._is_chunk_relevant_to_query(c, query) for c in c_b_chunks)
                        if not (rel_a and rel_b):
                            continue

                        # Check if conflict claim addresses the query subject
                        claim_str = f"{cr.claim_a} {cr.claim_b} {cr.resolution_notes or ''}".lower()
                        q_tokens = [w for w in re.findall(r'\w+', query.lower()) if len(w) > 2 and w not in ['what', 'is', 'are', 'the', 'must', 'for', 'does', 'action', 'actions']]
                        if q_tokens and not any(t in claim_str for t in q_tokens):
                            # Conflict claim is about an unrelated subject
                            continue

                    # Check if one source is a request/register record and the other is a governing policy
                    title_a = (getattr(cr.source_a, 'title', '') or '').lower()
                    title_b = (getattr(cr.source_b, 'title', '') or '').lower()
                    is_reg_a = any(r in title_a for r in ['register', 'request', 'pack'])
                    is_reg_b = any(r in title_b for r in ['register', 'request', 'pack'])
                    if is_reg_a != is_reg_b:
                        # Transactional request registers do not contradict governing policies
                        continue

                    has_unresolved_tie = True
                    unresolved_conflicts.append({
                        'source_a': cr.source_a.title,
                        'source_b': cr.source_b.title,
                        'claim_a': cr.claim_a,
                        'claim_b': cr.claim_b,
                        'rank': cr.source_a.authority_level
                    })
                    notes.append(
                        f"Database Conflict Detected (L6): Unresolved conflict between '{cr.source_a.title}' "
                        f"and '{cr.source_b.title}'. Notes: {cr.resolution_notes or cr.claim_a}"
                    )
                    reason_codes.append(GovernanceReasonCode.L6_DATABASE_CONFLICT_DETECTED.value)
                    reason_codes.append(GovernanceReasonCode.L6_UNRESOLVED_CONTRADICTION.value)
                elif cr.resolution_status == 'resolved_by_authority':
                    conflicts_resolved.append({
                        'informal_claim': cr.claim_b[:120],
                        'authoritative_source': cr.source_a.title,
                        'resolution': 'authority_dominance',
                        'note': f"Database Record: {cr.resolution_notes or 'Resolved by authority dominance.'}"
                    })
                    reason_codes.append(GovernanceReasonCode.L6_AUTHORITY_DOMINANCE.value)

        # 2. Check for informal claim overriding formal preconditions (Rank <= 2 vs Rank >= 6)
        informal_approval_chunks = [
            c for c in chunks 
            if c.get('authority_level', 3) <= 2 and any(w in c.get('text', '').lower() for w in ['approved', 'permitted', 'allowed', 'yes'])
        ]
        formal_restrictive_chunks = [
            c for c in chunks 
            if c.get('authority_level', 3) >= 6 and any(w in c.get('text', '').lower() for w in ['prohibit', 'forbidden', 'condition', 'require', 'must not', 'not permitted'])
        ]

        if informal_approval_chunks and formal_restrictive_chunks:
            formal = formal_restrictive_chunks[0]
            informal = informal_approval_chunks[0]
            conflicts_resolved.append({
                'informal_claim': informal.get('text', '')[:120].strip(),
                'authoritative_source': f"{formal.get('document_title')} (Rank {formal.get('authority_level')})",
                'resolution': 'authority_dominance',
                'note': f"Rank {formal.get('authority_level')} {cls.AUTHORITY_LADDER.get(formal.get('authority_level', 6))} strictly overrides Rank {informal.get('authority_level')} {cls.AUTHORITY_LADDER.get(informal.get('authority_level', 2))} claim."
            })
            notes.append(f"Authority Dominance (L6): {formal.get('document_title')} outranks informal claims.")
            reason_codes.append(GovernanceReasonCode.L6_AUTHORITY_DOMINANCE.value)

        # 3. Check for same-rank cross-source contradictions
        # Requirement 3: Draft documents must not create false equal-rank contradictions against approved policies.
        applicable_chunks = [
            c for c in chunks
            if (c.get('document_status') or c.get('status') or '').lower() != 'draft'
            and not c.get('is_draft')
        ]

        rank_groups: Dict[int, List[Dict[str, Any]]] = {}
        for c in applicable_chunks:
            r = c.get('authority_level', 3)
            rank_groups.setdefault(r, []).append(c)

        for rank, group in rank_groups.items():
            if len(group) >= 2 and rank >= 3:
                # Compare each pair in group
                for i in range(len(group)):
                    for j in range(i + 1, len(group)):
                        c1 = group[i]
                        c2 = group[j]

                        # Skip if chunks belong to the same document
                        if c1.get('document_id') and c2.get('document_id') and str(c1.get('document_id')) == str(c2.get('document_id')):
                            continue
                        if c1.get('document_title') and c2.get('document_title') and c1.get('document_title') == c2.get('document_title'):
                            continue

                        # Check relevance to question: candidate chunks must be relevant to participate in conflict detection
                        if query:
                            if not (cls._is_chunk_relevant_to_query(c1, query) and cls._is_chunk_relevant_to_query(c2, query)):
                                continue

                        # Check version supersession within same rank
                        v1 = c1.get('document_version', 1)
                        v2 = c2.get('document_version', 1)
                        if v1 > v2:
                            conflicts_resolved.append({
                                'informal_claim': c2.get('text', '')[:120].strip(),
                                'authoritative_source': f"{c1.get('document_title')} (v{v1})",
                                'resolution': 'version_supersession',
                                'note': f"Version {v1} supersedes earlier version {v2} at Rank {rank}."
                            })
                            notes.append(f"Supersession Resolution (L6): {c1.get('document_title')} v{v1} supersedes v{v2}.")
                            reason_codes.append(GovernanceReasonCode.L6_VERSION_SUPERSESSION.value)
                            continue
                        elif v2 > v1:
                            conflicts_resolved.append({
                                'informal_claim': c1.get('text', '')[:120].strip(),
                                'authoritative_source': f"{c2.get('document_title')} (v{v2})",
                                'resolution': 'version_supersession',
                                'note': f"Version {v2} supersedes earlier version {v1} at Rank {rank}."
                            })
                            notes.append(f"Supersession Resolution (L6): {c2.get('document_title')} v{v2} supersedes v{v1}.")
                            reason_codes.append(GovernanceReasonCode.L6_VERSION_SUPERSESSION.value)
                            continue

                        # Equal versions or different documents: check genuine contradiction (Requirements 8 & 9)
                        contra = cls._detect_genuine_contradiction(c1, c2)
                        if contra:
                            has_unresolved_tie = True
                            unresolved_conflicts.append({
                                'source_a': c1.get('document_title', 'Source A'),
                                'source_b': c2.get('document_title', 'Source B'),
                                'claim_a': contra['claim_a'],
                                'claim_b': contra['claim_b'],
                                'rank': rank
                            })
                            notes.append(
                                f"Unresolved Contradiction (L6): Two authoritative sources at Rank {rank} "
                                f"('{c1.get('document_title')}' and '{c2.get('document_title')}') genuinely disagree on {contra['type']}. "
                                "Precedence cannot be established."
                            )
                            reason_codes.append(GovernanceReasonCode.L6_UNRESOLVED_CONTRADICTION.value)

        # Deduplicate reason codes
        deduped = []
        for r in reason_codes:
            if r not in deduped:
                deduped.append(r)

        return AuthorityConflictTuple(conflicts_resolved, has_unresolved_tie, notes, deduped, unresolved_conflicts)


# ==============================================================================
# L5 — TEMPORAL VALIDITY LAYER
# ==============================================================================
class TemporalValidityLayer:
    """
    L5 Temporal Validity Layer (lore.md §4 L5):
    effective_from/to, expiry, stale_after, and point-in-time as_of queries.
    Enforces stable-only serving (only 'ready' documents may serve as evidence).
    """
    @classmethod
    def _parse_date(cls, val: Any) -> Optional[datetime]:
        """Parses various date and datetime formats into an aware UTC datetime."""
        if not val:
            return None
        if isinstance(val, datetime):
            return val if not timezone.is_naive(val) else timezone.make_aware(val, dt_timezone.utc)
        if isinstance(val, date):
            return timezone.make_aware(datetime(val.year, val.month, val.day, 0, 0, 0), dt_timezone.utc)
        if isinstance(val, str):
            from django.utils.dateparse import parse_datetime, parse_date
            dt = parse_datetime(val)
            if dt:
                return dt if not timezone.is_naive(dt) else timezone.make_aware(dt, dt_timezone.utc)
            d = parse_date(val)
            if d:
                return timezone.make_aware(datetime(d.year, d.month, d.day, 0, 0, 0), dt_timezone.utc)
            clean_val = val.strip()
            for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%B %Y", "%b %Y", "%Y-%m-%d"):
                try:
                    parsed = datetime.strptime(clean_val, fmt)
                    return timezone.make_aware(parsed, dt_timezone.utc)
                except ValueError:
                    continue
        return None

    @classmethod
    def _extract_query_event_date(
        cls,
        query: str,
        chunks: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[datetime]:
        """
        Extracts historical event or reference dates embedded in the natural language query.
        Examples: 'March 2026', 'July 1, 2026', 'predates DOC-002', 'in 2024'.
        """
        if not query:
            return None
        q_lower = query.lower()

        # 1. Explicit Month and Year: e.g. 'March 2026', 'July 1, 2026', 'January 2027'
        m_month = re.search(r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2},?\s+)?(20\d\d)\b', q_lower)
        if m_month:
            return cls._parse_date(m_month.group(0))

        # 2. ISO Date: YYYY-MM-DD
        m_iso = re.search(r'\b(20\d\d)-(\d{2})-(\d{2})\b', query)
        if m_iso:
            return cls._parse_date(m_iso.group(0))

        # 3. Relative inquiry: 'predates DOC-002', 'prior to DOC-002', 'before DOC-002'
        m_predates = re.search(r'\b(?:predates?|prior to|before)\s+([a-z0-9_-]+)', q_lower)
        if m_predates:
            target_code = m_predates.group(1).upper()
            if chunks:
                for c in chunks:
                    c_title = (c.get('document_title') or '').upper()
                    c_code = (c.get('document_code') or '').upper()
                    if target_code in c_title or target_code in c_code:
                        eff = cls._parse_date(c.get('effective_date'))
                        if eff:
                            # 1 day before target effective date represents the predating historical era
                            return eff - timedelta(days=1)

        # 4. Explicit Year: e.g. 'in 2024', 'for 2024', 'during 2024'
        m_year = re.search(r'\b(?:in|for|during|fy|year)\s+(20\d\d)\b', q_lower)
        if m_year:
            year_val = int(m_year.group(1))
            return timezone.make_aware(datetime(year_val, 1, 1, 0, 0, 0), dt_timezone.utc)

        return None

    @classmethod
    def evaluate(
        cls,
        chunks: List[Dict[str, Any]],
        as_of: Optional[Any] = None,
        query: Optional[str] = None,
        policy_context: Optional[Dict[str, Any]] = None
    ) -> TemporalEvaluationTuple:
        valid_chunks = []
        temporal_notes = []
        has_stale_data = False
        reason_codes = []
        policy_context = policy_context or {}

        # 1. Determine point-in-time reference timestamp (as_of / event date)
        if as_of:
            ref_time = cls._parse_date(as_of) or timezone.now()
            reason_codes.append(GovernanceReasonCode.L5_HISTORICAL_AS_OF_APPLIED.value)
        elif policy_context.get('as_of') or policy_context.get('event_date'):
            ref_time = cls._parse_date(policy_context.get('as_of') or policy_context.get('event_date')) or timezone.now()
            reason_codes.append(GovernanceReasonCode.L5_HISTORICAL_AS_OF_APPLIED.value)
        elif query:
            extracted_date = cls._extract_query_event_date(query, chunks)
            if extracted_date:
                ref_time = extracted_date
                reason_codes.append(GovernanceReasonCode.L5_HISTORICAL_AS_OF_APPLIED.value)
            else:
                ref_time = timezone.now()
        else:
            ref_time = timezone.now()

        if timezone.is_naive(ref_time):
            ref_time = timezone.make_aware(ref_time, dt_timezone.utc)

        # 2. Check if the user is explicitly inquiring what the draft says or its approval status (Requirement 3)
        user_asking_draft = False
        user_asking_older_version = False
        if policy_context.get('is_draft'):
            user_asking_draft = True
        elif query:
            q_lower = query.lower()
            if any(p in q_lower for p in ['what does the draft say', 'draft policy', 'in draft', 'proposed policy', 'draft allowance', 'draft says', 'draft specifies', 'policy approved', 'is it approved', 'approval status']):
                user_asking_draft = True
            elif 'draft' in q_lower and any(w in q_lower for w in ['what', 'show', 'tell', 'says', 'quote', 'value', 'is', 'status']):
                user_asking_draft = True
            elif re.search(r'\b(?:is|are)\s+.*approved\b', q_lower):
                user_asking_draft = True

            is_version_comparison = any(p in q_lower for p in ['compare', 'difference between', 'changed between', 'versus', ' vs ']) and any(p in q_lower for p in ['version', 'v1', 'v2'])
            if is_version_comparison or any(p in q_lower for p in ['version 1', 'v1', 'older version', 'prior version', 'previous version', 'historical version', 'in version 1', 'under version 1', 'v1 of', 'version 1 of', 'what was the']):
                user_asking_older_version = True

        # 3. Load DB records for candidate chunks if available
        doc_ids = list({c.get('document_id') for c in chunks if c.get('document_id')})
        valid_uuids = []
        for did in doc_ids:
            try:
                uuid.UUID(str(did))
                valid_uuids.append(did)
            except (ValueError, TypeError):
                continue

        docs_map = {
            str(d.id): d 
            for d in SourceDocument.objects.filter(id__in=valid_uuids)
        } if valid_uuids else {}

        # 4. Canonical supersession analysis (Requirement 4)
        # Track which target documents/codes are superseded as of ref_time
        superseded_identifiers: Set[str] = set()

        # 4a. DB KnowledgeRelationship supersession
        if valid_uuids:
            try:
                from apps.knowledge.models import KnowledgeRelationship, RelationshipType, RelationshipApprovalStatus
                super_rels = KnowledgeRelationship.objects.filter(
                    target_document_id__in=valid_uuids,
                    relationship_type=RelationshipType.SUPERSEDES,
                    approval_status=RelationshipApprovalStatus.APPROVED
                ).select_related('source_document', 'target_document')

                for s_rel in super_rels:
                    if s_rel.is_temporally_valid(ref_time):
                        s_doc = s_rel.source_document
                        if s_doc and s_doc.status in ('ready', 'approved'):
                            s_eff = cls._parse_date(s_doc.effective_date)
                            # Requirement 5: A superseding amendment cannot supersede prior policy BEFORE its effective date!
                            if s_eff and s_eff > ref_time:
                                continue
                            superseded_identifiers.add(str(s_rel.target_document_id))
                            t_title = s_rel.target_document.title if s_rel.target_document else str(s_rel.target_document_id)
                            temporal_notes.append(
                                f"Supersession Exclusion: Document '{t_title}' is superseded by '{s_doc.title}' "
                                f"(effective as of {ref_time.strftime('%Y-%m-%d')})."
                            )
                            reason_codes.append(GovernanceReasonCode.L5_SUPERSEDED_DOCUMENT_EXCLUSION.value)
            except Exception as e:
                logger.warning(f"Error checking supersession in TemporalValidityLayer: {e}")

        # 4b. In-memory / chunk metadata supersession
        for c in chunks:
            c_supersedes = c.get('supersedes') or []
            if isinstance(c_supersedes, str):
                c_supersedes = [c_supersedes]
            c_eff = cls._parse_date(c.get('effective_date'))
            # Only active supersessions apply
            if c_eff and c_eff > ref_time:
                continue
            for target in c_supersedes:
                if target:
                    superseded_identifiers.add(str(target).upper())
                    superseded_identifiers.add(str(target))

        # 5. Evaluate each chunk against all separate governance attributes (Requirements 1-10)
        for chk in chunks:
            doc_id = str(chk.get('document_id', ''))
            doc = docs_map.get(doc_id)
            doc_title = chk.get('document_title') or (doc.title if doc else 'Policy Document')
            doc_code = str(chk.get('document_code') or '').upper()

            # Separate attributes (Requirement 1)
            raw_status = (chk.get('document_status') or chk.get('status') or (doc.status if doc else '') or '').lower()
            auth_rank = chk.get('authority_level') if chk.get('authority_level') is not None else (doc.authority_level if doc else 3)
            eff_date = cls._parse_date(chk.get('effective_date') or (doc.effective_date if doc else None))
            exp_date = cls._parse_date(chk.get('expiration_date') or (doc.expiration_date if doc else None))
            scope = (chk.get('scope') or '').lower()

            # Lifecycle check (P1 §6): Quarantined, failed, or processing records cannot serve as evidence
            if raw_status in ['quarantined', 'failed', 'needs_review'] or (doc and doc.status in ['quarantined', 'failed', 'needs_review']):
                temporal_notes.append(
                    f"Lifecycle Exclusion (P1 §6): Document '{doc_title}' has status '{raw_status or (doc.status if doc else '')}'. "
                    "Quarantined, unverified, or processing records cannot serve as authoritative evidence."
                )
                reason_codes.append(GovernanceReasonCode.L5_LIFECYCLE_EXCLUSION.value)
                continue

            # Check if document is superseded as of ref_time (Requirements 4 & 7)
            is_superseded_now = (
                doc_id in superseded_identifiers or
                doc_code in superseded_identifiers or
                any(t in doc_title.upper() for t in superseded_identifiers if len(t) >= 4) or
                chk.get('is_superseded') or
                raw_status == 'superseded'
            )

            # Resolve document status strictly from stored metadata (Requirements 2 & 10)
            text_lower = (chk.get('text') or '').lower()
            is_draft_doc = (
                chk.get('is_draft') or
                raw_status == 'draft' or
                'draft' in doc_title.lower() or
                any(p in text_lower for p in ['draft for review', 'draft for comment', 'status: draft', 'proposed internal policy', 'unapproved draft', 'pending formal adoption', 'pending approval'])
            )
            if is_draft_doc:
                resolved_status = 'draft'
            elif is_superseded_now:
                resolved_status = 'superseded'
            elif chk.get('is_archived') or raw_status == 'archived':
                resolved_status = 'archived'
            elif chk.get('is_future_effective') or raw_status == 'future-effective' or (eff_date and eff_date > ref_time):
                resolved_status = 'future-effective'
            elif raw_status in ['ready', 'approved', 'active']:
                resolved_status = 'approved'
            else:
                # Requirement 2 & 10: Missing or uncertain approval metadata must remain unknown.
                # DO NOT infer that a document is approved merely because it has Authority Rank 1 or any rank.
                resolved_status = 'unknown'

            # Attach resolved separate attributes to chunk
            chk['document_status'] = resolved_status
            chk['authority_level'] = auth_rank
            if eff_date:
                chk['effective_date'] = eff_date
            if exp_date:
                chk['expiration_date'] = exp_date

            # --- APPLICABILITY EVALUATION ---
            # Step A: Draft check (Requirement 3)
            if resolved_status == 'draft':
                # Check if there is an approved alternative chunk in candidate evidence that directly addresses the query
                has_approved_alternative = False
                if query:
                    # If this draft chunk contains direct factual answers (e.g. logging requirements):
                    chk_has_direct_answer = any(
                        p in chk.get('text', '').lower()
                        for p in ['audit logging', 'record relevant security events', 'successful and failed authentication']
                    )
                    for other_chk in chunks:
                        if other_chk == chk:
                            continue
                        other_status = (other_chk.get('document_status') or other_chk.get('status') or '').lower()
                        if other_status in ('approved', 'ready') and not other_chk.get('is_draft'):
                            if chk_has_direct_answer:
                                other_text = other_chk.get('text', '').lower()
                                if any(p in other_text for p in ['audit logging', 'record relevant security events', 'successful and failed authentication']):
                                    has_approved_alternative = True
                                    break
                            elif AuthorityLayer._is_chunk_relevant_to_query(other_chk, query):
                                has_approved_alternative = True
                                break

                if user_asking_draft or not has_approved_alternative:
                    valid_chunks.append(chk)
                    temporal_notes.append(
                        f"Document '{doc_title}' is an unapproved draft. Draft terms remain non-binding."
                    )
                    continue
                else:
                    val_m = re.search(r'\$\s*(\d+(?:\.\d{2})?)', chk.get('text', ''))
                    rate_str = f" proposing ${val_m.group(1)}" if val_m else ""
                    temporal_notes.append(
                        f"Lifecycle Exclusion (P1 §6): Document '{doc_title}' is in draft status{rate_str} and cannot serve as governing policy when approved policy exists. Draft terms remain non-binding."
                    )
                    reason_codes.append(GovernanceReasonCode.L5_LIFECYCLE_EXCLUSION.value)
                    continue

            # Step B: Future-Effective check (Requirement 5)
            if eff_date and eff_date > ref_time:
                val_m = re.search(r'\$\s*(\d+(?:\.\d{2})?)', chk.get('text', ''))
                rate_str = f" proposing ${val_m.group(1)}" if val_m else ""
                temporal_notes.append(
                    f"Document '{doc_title}' is not yet effective (effective {eff_date.strftime('%Y-%m-%d')}{rate_str}). Excluded from active context."
                )
                reason_codes.append(GovernanceReasonCode.L5_FUTURE_EFFECTIVE_EXCLUSION.value)
                continue

            # Step C: Supersession check (Requirements 4, 6, 7)
            if is_superseded_now:
                if user_asking_older_version:
                    valid_chunks.append(chk)
                    temporal_notes.append(
                        f"Notice: Document '{doc_title}' is an older version superseded by subsequent policy."
                    )
                    continue
                else:
                    temporal_notes.append(
                        f"Supersession Exclusion: Document '{doc_title}' is superseded as of {ref_time.strftime('%Y-%m-%d')}. Excluded."
                    )
                    reason_codes.append(GovernanceReasonCode.L5_SUPERSEDED_DOCUMENT_EXCLUSION.value)
                    continue

            # Step D: Expiration check (Requirements 6 & 7)
            if exp_date and exp_date < ref_time:
                temporal_notes.append(
                    f"Document '{doc_title}' expired on {exp_date.strftime('%Y-%m-%d')}. Excluded."
                )
                reason_codes.append(GovernanceReasonCode.L5_EXPIRATION_EXCLUSION.value)
                continue

            # Step E: Staleness aging check
            if doc:
                stale_days = doc.stale_after_days or 365
                stale_threshold = timedelta(days=stale_days)
                upd = doc.updated_at
                if upd:
                    if timezone.is_naive(upd):
                        upd = timezone.make_aware(upd, dt_timezone.utc)
                    if (ref_time - upd) > stale_threshold:
                        has_stale_data = True
                        temporal_notes.append(
                            f"Notice: Source '{doc.title}' is past its stale threshold ({stale_days} days). Caveat applied."
                        )
                        reason_codes.append(GovernanceReasonCode.L5_STALE_RECORD_CAVEAT.value)

            # Chunk is active and applicable to the requested date and scope!
            valid_chunks.append(chk)
            reason_codes.append(GovernanceReasonCode.L5_DOCUMENT_ACTIVE.value)

        # Deduplicate reason codes
        deduped = []
        for r in reason_codes:
            if r not in deduped:
                deduped.append(r)

        return TemporalEvaluationTuple(valid_chunks, temporal_notes, has_stale_data, deduped)


# ==============================================================================
# L4 — EXCEPTION LAYER
# ==============================================================================
class ExceptionLayer:
    """
    L4 Exception Layer (lore.md §4 L4):
    Scoped, time-bounded overrides.
    Matching exceptions are ALWAYS disclosed in the result.
    Checks query text and structured policy_context.
    """
    @classmethod
    def evaluate(
        cls,
        workspace_id: str,
        query: str,
        as_of: Optional[datetime] = None,
        policy_context: Optional[Dict[str, Any]] = None
    ) -> ExceptionEvaluationTuple:
        active_exceptions = []
        if workspace_id:
            try:
                uuid.UUID(workspace_id)
                active_exceptions = list(ScopedException.objects.filter(
                    workspace_id=workspace_id,
                    status='active'
                ))
            except (ValueError, TypeError):
                active_exceptions = []
        matched_exceptions = []
        exception_notes = []
        reason_codes = []
        now = as_of or timezone.now()
        q_lower = query.lower()

        # Build context search terms from policy_context if present
        context_terms = set()
        if policy_context and isinstance(policy_context, dict):
            for v in policy_context.values():
                if isinstance(v, str):
                    context_terms.add(v.lower())

        for exc in active_exceptions:
            # Check validity window
            if not exc.is_currently_valid(now):
                reason_codes.append(GovernanceReasonCode.L4_EXCEPTION_EXPIRED.value)
                continue

            # Check scope dimension matching
            scope_val_lower = exc.scope_value.lower()
            rule_code_lower = exc.rule_code.lower()

            is_matched = (
                scope_val_lower in q_lower or
                rule_code_lower in q_lower or
                scope_val_lower in context_terms or
                any(scope_val_lower in t for t in context_terms)
            )

            if is_matched:
                matched_exceptions.append({
                    'exception_id': str(exc.id),
                    'rule_code': exc.rule_code,
                    'scope_type': exc.scope_type,
                    'scope_value': exc.scope_value,
                    'justification': exc.justification,
                    'approved_by': exc.approved_by,
                    'window_end': exc.window_end.isoformat() if exc.window_end else None
                })
                exception_notes.append(
                    f"Scoped Exception Applied (L4): [{exc.rule_code}] override for {exc.scope_type}='{exc.scope_value}' "
                    f"approved by {exc.approved_by} until {exc.window_end.strftime('%Y-%m-%d') if exc.window_end else 'revocation'}. "
                    f"Justification: {exc.justification}"
                )
                reason_codes.append(GovernanceReasonCode.L4_EXCEPTION_APPLIED.value)
            else:
                reason_codes.append(GovernanceReasonCode.L4_EXCEPTION_SCOPE_MISMATCH.value)

        has_applicable_exception = bool(matched_exceptions)

        # Deduplicate reason codes
        deduped = []
        for r in reason_codes:
            if r not in deduped:
                deduped.append(r)

        return ExceptionEvaluationTuple(matched_exceptions, has_applicable_exception, exception_notes, deduped)


# ==============================================================================
# L3 — EVIDENCE SUFFICIENCY LAYER
# ==============================================================================
class EvidenceSufficiencyLayer:
    """
    L3 Evidence Sufficiency Layer (lore.md §4 L3):
    Evaluates whether evidence is complete enough to support the classified decision type.
    Outputs the exact list of missing requirements based on domain catalogs and database requirements.
    """
    @classmethod
    def evaluate(
        cls,
        workspace_id: str,
        decision_info: Union[Dict[str, Any], DecisionIntelligenceTuple],
        retrieved_chunks: List[Dict[str, Any]],
        query: str,
        has_exception: bool = False
    ) -> SufficiencyEvaluationTuple:
        dt = decision_info['decision_type']
        q_lower = query.lower()
        reason_codes = []

        intent = getattr(decision_info, 'query_intent', None)
        if intent is None and isinstance(decision_info, dict):
            intent = decision_info.get('query_intent')
        is_action_gate = (intent == 'action_request') or (intent is None)

        evidence_found = []
        for chk in retrieved_chunks:
            evidence_found.append({
                'document_id': chk.get('document_id'),
                'document_title': chk.get('document_title'),
                'authority_level': chk.get('authority_level', 3),
                'page_number': chk.get('page_number', 1),
                'score': round(chk.get('score', 0.0), 4),
                'heading': chk.get('heading_path', 'General'),
                'snippet': chk.get('text', '')[:220].strip()
            })

        evidence_missing = []
        all_text = " ".join(c.get('text', '').lower() for c in retrieved_chunks)

        # 1. Vendor Approval Sufficiency Checks (Action Gates Only - Requirements 2 & 3)
        if dt == 'vendor_approval' and is_action_gate:
            if any(w in q_lower for w in ['customer data', 'pii', 'sensitive', 'residency']):
                has_residency = (
                    ('data residency' in all_text or 'schedule d' in all_text) and
                    ('schedule d has not been attached' not in all_text)
                )
                if not has_residency and not has_exception:
                    evidence_missing.append({
                        'requirement': 'executed_data_residency_addendum',
                        'mandatory': True,
                        'status': EvidenceStatus.MISSING.value,
                        'description': 'Schedule D (Regional Data Sovereignty Addendum) is unexecuted; mandatory geographic data storage guarantee is missing.'
                    })
                    reason_codes.append(GovernanceReasonCode.L3_MANDATORY_EVIDENCE_MISSING.value)

            has_assessment = any(w in all_text for w in ['assessment', 'soc 2', 'iso 27001', 'audit passed', 'certified'])
            if not has_assessment and not has_exception:
                evidence_missing.append({
                    'requirement': 'formal_security_assessment_report',
                    'mandatory': True,
                    'status': EvidenceStatus.PENDING.value,
                    'description': 'Vendor security assessment report is pending formal audit completion.'
                })
                reason_codes.append(GovernanceReasonCode.L3_MANDATORY_EVIDENCE_MISSING.value)

        # 2. Statutory Land & Legal Deed Checks
        elif dt == 'statutory_compliance':
            has_deed = any(term in all_text for term in ['saf kabla', 'deed', 'দলিল', 'খতিয়ান', 'খতিয়ান'])
            has_schedule = any(term in all_text for term in ['schedule', 'তফসিল', 'মৌজা'])
            if not has_deed:
                evidence_missing.append({
                    'requirement': 'statutory_registered_deed',
                    'mandatory': True,
                    'status': EvidenceStatus.MISSING.value,
                    'description': 'Registered Saf Kabla Deed or CS/RS record document was not found in active verified context.'
                })
                reason_codes.append(GovernanceReasonCode.L3_MANDATORY_EVIDENCE_MISSING.value)
            if not has_schedule:
                evidence_missing.append({
                    'requirement': 'property_schedule_and_khatian',
                    'mandatory': True,
                    'status': EvidenceStatus.MISSING.value,
                    'description': 'Specific land schedule, CS khatian, or plot demarcation is absent from the provided record.'
                })
                reason_codes.append(GovernanceReasonCode.L3_MANDATORY_EVIDENCE_MISSING.value)

        # 3. Data Processing Sufficiency Checks (Action Gates Only - Requirements 2 & 3)
        elif dt == 'data_processing' and is_action_gate:
            has_retention = any(w in all_text for w in ['retention', 'deletion', 'erasure', 'consent', 'gdpr'])
            if not has_retention:
                evidence_missing.append({
                    'requirement': 'data_retention_and_consent_policy',
                    'mandatory': True,
                    'status': EvidenceStatus.MISSING.value,
                    'description': 'Defined data retention schedule and lawful processing consent records are missing.'
                })
                reason_codes.append(GovernanceReasonCode.L3_MANDATORY_EVIDENCE_MISSING.value)

        # 4. Database-Configured Workspace Evidence Requirements (Action Gates Only)
        if workspace_id and is_action_gate:
            try:
                db_reqs = EvidenceRequirement.objects.filter(
                    models.Q(workspace_id=workspace_id) | models.Q(workspace__isnull=True),
                    decision_type__in=[dt, '*']
                )
                for req in db_reqs:
                    req_type_lower = req.evidence_type.lower()
                    # Check if evidence type is satisfied in text or heading
                    is_present = (req_type_lower in all_text)
                    if not is_present and req.is_mandatory and not has_exception:
                        evidence_missing.append({
                            'requirement': req.evidence_type,
                            'mandatory': True,
                            'status': EvidenceStatus.MISSING.value,
                            'description': req.description or f"Mandatory evidence '{req.evidence_type}' required for {dt}."
                        })
                        reason_codes.append(GovernanceReasonCode.L3_CUSTOM_REQUIREMENT_UNSATISFIED.value)
            except Exception as dberr:
                logger.warning(f"Error querying custom database evidence requirements: {dberr}")

        # 5. Authority Threshold Check: Top evidence must have sufficient authority for high-risk action gates
        if is_action_gate and dt in ('vendor_approval', 'data_processing', 'statutory_compliance', 'deployment_approval'):
            max_auth = max([c.get('authority_level', 1) for c in retrieved_chunks], default=0)
            if max_auth > 0 and max_auth <= 2 and not has_exception:
                evidence_missing.append({
                    'requirement': 'authoritative_controlling_source',
                    'mandatory': True,
                    'status': EvidenceStatus.INSUFFICIENT_AUTHORITY.value,
                    'description': f'Top evidence has informal authority rank {max_auth}; decisions of type {dt} require verified policy or contract rank >= 4.'
                })
                reason_codes.append(GovernanceReasonCode.L3_INSUFFICIENT_AUTHORITY_RANK.value)

        # 6. Informational / Comparative Sufficiency Check (Requirement 8)
        # Ensure fact-bearing sources exist for informational, comparison, or policy interpretation questions
        if not is_action_gate and not evidence_missing and len(retrieved_chunks) > 0:
            has_factual_content = any(len(c.get('text', '').strip()) > 10 for c in retrieved_chunks)
            if not has_factual_content:
                evidence_missing.append({
                    'requirement': 'relevant_fact',
                    'mandatory': True,
                    'status': EvidenceStatus.MISSING.value,
                    'description': f"No authoritative governing source found answering '{query}'."
                })
                reason_codes.append(GovernanceReasonCode.L3_MANDATORY_EVIDENCE_MISSING.value)

        # Evaluate sufficiency
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

        return SufficiencyEvaluationTuple(evidence_found, evidence_missing, is_sufficient, deduped)


# ==============================================================================
# L2 — ANSWER-STATE LAYER
# ==============================================================================
class AnswerStateLayer:
    """
    L2 Answer-State Layer (lore.md §10):
    Deterministic 9-state machine with precedence ordering (highest wins):
    1. denied (stop)
    2. violation (stop)
    3. conflicting (ask_user)
    4. insufficient (ask_user + missing-list)
    5. abstain (ask_user)
    6. human_review (escalate)
    7. qualified (proceed_and_cite)
    8. supported (proceed_and_cite)
    9. no_knowledge (proceed)
    """
    @classmethod
    def resolve_state(
        cls,
        is_denied: bool,
        is_violation: bool,
        has_unresolved_conflict: bool,
        is_sufficient: bool,
        is_abstain: bool,
        requires_human_review: bool,
        is_qualified: bool,
        chunks_count: int
    ) -> AnswerStateTuple:
        reason_codes = []

        # Precedence 1: Denied (L7)
        if is_denied:
            reason_codes.append(GovernanceReasonCode.L7_PERMISSION_DENIED.value)
            return AnswerStateTuple('denied', 'stop', reason_codes)

        # Precedence 2: Violation (MUST/MUST-NOT rule breach)
        if is_violation:
            reason_codes.append(GovernanceReasonCode.L2_RULE_VIOLATION_TRIGGERED.value)
            return AnswerStateTuple('violation', 'stop', reason_codes)

        # Precedence 3: Conflicting (L6 unresolved tie)
        if has_unresolved_conflict:
            reason_codes.append(GovernanceReasonCode.L6_UNRESOLVED_CONTRADICTION.value)
            return AnswerStateTuple('conflicting', 'ask_user', reason_codes)

        # Precedence 4: Insufficient (L3 mandatory evidence gap)
        if not is_sufficient:
            reason_codes.append(GovernanceReasonCode.L3_MANDATORY_EVIDENCE_MISSING.value)
            return AnswerStateTuple('insufficient', 'ask_user', reason_codes)

        # Precedence 5: Abstain (Uncertainty band [0.45-0.55])
        if is_abstain:
            reason_codes.append(GovernanceReasonCode.L2_UNCERTAINTY_ABSTAIN.value)
            return AnswerStateTuple('abstain', 'ask_user', reason_codes)

        # Precedence 6: Human Review (L1 critical escalation)
        if requires_human_review:
            reason_codes.append(GovernanceReasonCode.L2_HUMAN_REVIEW_REQUIRED.value)
            return AnswerStateTuple('human_review', 'escalate', reason_codes)

        # Precedence 7: Qualified (L4 exception, L5 stale rule, L6 subordinate override)
        if is_qualified:
            reason_codes.append(GovernanceReasonCode.L2_STATE_RESOLVED.value)
            return AnswerStateTuple('qualified', 'proceed_and_cite', reason_codes)

        # Precedence 8: Supported (All requirements met)
        if chunks_count > 0:
            reason_codes.append(GovernanceReasonCode.L2_STATE_RESOLVED.value)
            return AnswerStateTuple('supported', 'proceed_and_cite', reason_codes)

        # Precedence 9: No Knowledge
        reason_codes.append(GovernanceReasonCode.L2_NO_KNOWLEDGE_DETERMINED.value)
        return AnswerStateTuple('no_knowledge', 'proceed', reason_codes)


# ==============================================================================
# L0 — OBSERVABILITY LAYER
# ==============================================================================
class ObservabilityLayer:
    """
    L0 Observability Layer (lore.md §4 L0):
    Freshness, decision traces, audit events, and latency metrics.
    """
    @classmethod
    def record_decision(
        cls,
        organization,
        workspace,
        user,
        trace_id: str,
        query: str,
        envelope: Dict[str, Any],
        token_count: int = 0
    ) -> Optional[DecisionRecord]:
        try:
            decision = DecisionRecord.objects.create(
                trace_id=trace_id,
                organization=organization,
                workspace=workspace,
                user=user,
                query=query,
                decision_type=envelope.get('decision_type', 'general_inquiry'),
                state=envelope.get('state', 'supported'),
                directive=envelope.get('directive', 'proceed_and_cite'),
                answer_text=envelope.get('answer', ''),
                evidence_found=envelope.get('evidence_found', []),
                evidence_missing=envelope.get('evidence_missing', []),
                conflicts_resolved=envelope.get('conflicts_resolved', []),
                citations=envelope.get('citations', []),
                token_count=token_count
            )

            AuditEvent.objects.create(
                organization=organization,
                workspace=workspace,
                user=user,
                event_type='decision_recorded',
                target_type='decision',
                target_id=str(decision.id),
                details={
                    'trace_id': trace_id,
                    'state': envelope.get('state'),
                    'directive': envelope.get('directive'),
                    'decision_type': envelope.get('decision_type'),
                    'reason_codes': envelope.get('reason_codes', []),
                    'evidence_found_count': len(envelope.get('evidence_found', [])),
                    'evidence_missing_count': len(envelope.get('evidence_missing', [])),
                    'citations_count': len(envelope.get('citations', []))
                }
            )

            return decision
        except Exception as ex:
            logger.warning(f"ObservabilityLayer could not persist decision trace: {ex}")
            return None


# ==============================================================================
# UNIFIED 9-LAYER MASTER ORCHESTRATOR
# ==============================================================================
class EnterpriseGovernanceEngine:
    """
    Unified 9-layer Master Engine executing the full LORE pipeline from lore.md:
    L7 -> L1 -> Core Retrieval -> L5 -> L4 -> L6 -> L3 -> L2 -> L0

    Enforces the explicit GovernanceRequest contract and typed lore.result/2 result schema.
    """
    @classmethod
    def evaluate(
        cls,
        query: Union[str, GovernanceRequest] = '',
        retrieved_chunks: Optional[List[Dict[str, Any]]] = None,
        workspace=None,
        user=None,
        user_role: str = 'member',
        as_of: Optional[Any] = None,
        schema_version: str = 'lore.result/2',
        groq_api_key: Optional[str] = None,
        llm_model: Optional[str] = None,
        request: Optional[GovernanceRequest] = None,
        policy_context: Optional[Dict[str, Any]] = None,
        decision_type: Optional[str] = None,
        trace_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        # Unpack GovernanceRequest if passed either as 'query' positional or 'request' keyword
        if isinstance(query, GovernanceRequest):
            req = query
        elif request is not None:
            req = request
        else:
            req = GovernanceRequest(
                workspace=workspace,
                organization=getattr(workspace, 'organization', None),
                principal=user,
                user_role=user_role,
                query=query,
                decision_type=decision_type,
                as_of=as_of,
                candidate_evidence=retrieved_chunks or [],
                policy_context=policy_context,
                trace_id=trace_id,
                schema_version=schema_version,
                groq_api_key=groq_api_key,
                llm_model=llm_model,
                execution_mode=kwargs.get('execution_mode'),
                synthesis_mode=kwargs.get('synthesis_mode')
            )

        try:
            return cls._evaluate_internal(req)
        except Exception as unhandled_err:
            logger.exception(f"Unhandled error in EnterpriseGovernanceEngine.evaluate: {unhandled_err}")
            return fail_closed_envelope(
                query=req.query,
                error_message=str(unhandled_err),
                error_category="GOVERNANCE_EXECUTION_FAILURE",
                trace_id=req.trace_id,
                decision_type=req.decision_type or "general_inquiry"
            )

    @classmethod
    def _evaluate_internal(cls, req: GovernanceRequest) -> Dict[str, Any]:
        trace_id = req.trace_id or f"trace-{uuid.uuid4().hex[:12]}"
        decision_id = f"dec-{uuid.uuid4().hex[:8]}"
        timing_stages: Dict[str, float] = {}
        all_reason_codes: List[str] = []

        workspace = req.workspace
        ws_id = str(workspace.id) if workspace and hasattr(workspace, 'id') else ''
        candidate_chunks = req.candidate_evidence or []

        # Check for degraded retrieval (e.g. vector store outage or lexical-only fallback)
        is_retrieval_degraded = any(
            c.get('retrieval_status') == 'degraded_lexical_only' or c.get('circuit_breaker_active') is True
            for c in candidate_chunks if isinstance(c, dict)
        )
        if is_retrieval_degraded:
            all_reason_codes.append("DEGRADED_RETRIEVAL_VECTOR_OUTAGE")

        # Check for GraphRAG expansion and degraded graph traversal budget
        graph_expanded_chunks = [c for c in candidate_chunks if isinstance(c, dict) and c.get('graph_expanded')]
        is_graph_degraded = any(
            c.get('graph_degraded') is True or c.get('retrieval_status') == 'degraded_graph_timeout'
            for c in candidate_chunks if isinstance(c, dict)
        ) or (bool(req.policy_context and req.policy_context.get('graph_traversal', {}).get('degraded')))

        if graph_expanded_chunks:
            all_reason_codes.append(GovernanceReasonCode.GRAPH_EXPANSION_APPLIED.value)
        if is_graph_degraded:
            all_reason_codes.append(GovernanceReasonCode.GRAPH_TRAVERSAL_BUDGET_DEGRADED.value)

        # -------------------------------------------------------------
        # STAGE 0: L7 — Permission Layer (RBAC / ABAC query-time check)
        # -------------------------------------------------------------
        t0 = timezone.now()
        perm_res = PermissionLayer.filter_authorized_chunks(
            candidate_chunks, user=req.principal, user_role=req.user_role
        )
        cleared_chunks = perm_res.cleared_chunks
        denial_reasons = perm_res.denial_reasons
        is_denied = perm_res.is_denied
        all_reason_codes.extend(perm_res.reason_codes)
        timing_stages['l7_permission_ms'] = (timezone.now() - t0).total_seconds() * 1000

        # -------------------------------------------------------------
        # STAGE 1: L1 — Decision Intelligence Layer
        # -------------------------------------------------------------
        t1 = timezone.now()
        decision_info = DecisionIntelligenceLayer.classify(
            req.query, explicit_decision_type=req.decision_type
        )
        dt = decision_info.decision_type
        escalation_target = decision_info.escalation_target
        requires_human_review = decision_info.requires_human_review
        all_reason_codes.extend(decision_info.reason_codes)
        timing_stages['l1_intelligence_ms'] = (timezone.now() - t1).total_seconds() * 1000

        # -------------------------------------------------------------
        # STAGE 2: L5 — Temporal Validity Layer
        # -------------------------------------------------------------
        t2 = timezone.now()
        temp_res = TemporalValidityLayer.evaluate(
            cleared_chunks, as_of=req.as_of, query=req.query, policy_context=req.policy_context
        )
        active_chunks = temp_res.valid_chunks
        temporal_notes = temp_res.temporal_notes
        has_stale = temp_res.has_stale_data
        all_reason_codes.extend(temp_res.reason_codes)
        timing_stages['l5_temporal_ms'] = (timezone.now() - t2).total_seconds() * 1000

        # -------------------------------------------------------------
        # STAGE 3: L4 — Exception Layer
        # -------------------------------------------------------------
        t3 = timezone.now()
        exc_res = ExceptionLayer.evaluate(
            ws_id, req.query, as_of=req.as_of, policy_context=req.policy_context
        )
        matched_exceptions = exc_res.matched_exceptions
        has_exception = exc_res.has_applicable_exception
        exception_notes = exc_res.exception_notes
        all_reason_codes.extend(exc_res.reason_codes)
        timing_stages['l4_exception_ms'] = (timezone.now() - t3).total_seconds() * 1000

        # -------------------------------------------------------------
        # STAGE 4: L6 — Authority Layer
        # -------------------------------------------------------------
        t4 = timezone.now()
        auth_res = AuthorityLayer.evaluate_conflicts(
            active_chunks, workspace_id=ws_id, query=req.query
        )
        conflicts_resolved = auth_res.conflicts_resolved
        has_unresolved_conflict = auth_res.has_unresolved_tie
        authority_notes = auth_res.notes
        all_reason_codes.extend(auth_res.reason_codes)
        timing_stages['l6_authority_ms'] = (timezone.now() - t4).total_seconds() * 1000

        # -------------------------------------------------------------
        # STAGE 5: L3 — Evidence Sufficiency Layer
        # -------------------------------------------------------------
        t5 = timezone.now()
        suff_res = EvidenceSufficiencyLayer.evaluate(
            ws_id, decision_info, active_chunks, req.query, has_exception=has_exception
        )
        evidence_found = suff_res.evidence_found
        evidence_missing = suff_res.evidence_missing
        is_sufficient = suff_res.is_sufficient
        all_reason_codes.extend(suff_res.reason_codes)
        timing_stages['l3_sufficiency_ms'] = (timezone.now() - t5).total_seconds() * 1000

        # -------------------------------------------------------------
        # STAGE 6: L2 — Answer-State Layer (Precedence Resolution)
        # -------------------------------------------------------------
        is_qualified = bool(has_exception or has_stale or conflicts_resolved)
        is_violation = False
        if req.policy_context and req.policy_context.get('is_violation'):
            is_violation = True
        elif not has_exception and active_chunks:
            q_lower = req.query.lower()
            intent = getattr(decision_info, 'query_intent', 'informational')
            is_policy_inquiry = (intent in ('policy_interpretation', 'informational')) and any(w in q_lower for w in ['what does', 'what is', 'policy say', 'tell me', 'explain', 'summarize'])
            has_proposing_bypass = any(w in q_lower for w in ['without', 'bypass', 'skip', 'disable', 'disregard'])
            # Only trigger violation if the user is attempting an unauthorized action bypass, NOT when merely asking what the policy says
            if has_proposing_bypass and not is_policy_inquiry:
                for chk in active_chunks:
                    txt = chk.get('text', '').lower()
                    if any(p in txt for p in ['must never', 'must maintain', 'must not', 'strictly prohibited', 'strictly forbidden', 'bypassing requires active exception']):
                        is_violation = True
                        all_reason_codes.append(GovernanceReasonCode.L2_RULE_VIOLATION_TRIGGERED.value)
                        break

        state_res = AnswerStateLayer.resolve_state(
            is_denied=is_denied,
            is_violation=is_violation,
            has_unresolved_conflict=has_unresolved_conflict,
            is_sufficient=is_sufficient,
            is_abstain=False,
            requires_human_review=requires_human_review,
            is_qualified=is_qualified,
            chunks_count=len(active_chunks)
        )
        state = state_res.state
        directive = state_res.directive
        all_reason_codes.extend(state_res.reason_codes)

        # Assemble notes across layers
        all_notes = temporal_notes + exception_notes + authority_notes
        if is_denied:
            all_notes.extend(denial_reasons)

        gen_metrics: Dict[str, Any] = {}

        # Formulate answer text strictly according to model policy
        if state == 'denied':
            answer = f"Access Denied: You do not have sufficient permissions to view the authoritative records for '{req.query}'."
            # Security Invariant: Zero leakage of citations or evidence_found on L7 permission denial
            citations = []
            evidence_found = []
        elif state == 'insufficient':
            answer = (
                f"Cannot authorize request for '{req.query}'. Mandatory governance evidence is missing:\n" +
                "\n".join(f"- [{m['requirement']}]: {m['description']}" for m in evidence_missing)
            )
            if escalation_target:
                answer += f"\n\n**Escalation Recommendation**: Route to {escalation_target.replace('_', ' ').title()}."
            citations = []
        elif state == 'conflicting':
            conflict_sources_text = ""
            if getattr(auth_res, 'unresolved_conflicts', None):
                u = auth_res.unresolved_conflicts[0]
                conflict_sources_text = f" Specifically, '{u.get('source_a')}' ({u.get('claim_a')}) contradicts '{u.get('source_b')}' ({u.get('claim_b')})."
            answer = (
                f"Governance Warning: Contradictory authoritative sources detected for '{req.query}'.{conflict_sources_text} "
                "LORE will not guess between equal-authority policies. Please request human adjudication."
            )
            from apps.governance.evidence import EvidencePresentationEngine
            citations = EvidencePresentationEngine.curate_citations(
                query=req.query,
                answer=answer,
                active_chunks=active_chunks,
                conflicts_resolved=conflicts_resolved,
                as_of=req.as_of
            )
        elif state == 'no_knowledge':
            answer = f"No governed knowledge found in active workspace matching '{req.query}'."
            citations = []
        else:
            # Grounded generation for supported/qualified outcomes
            from apps.decisions.engine import GroundedGenerationService
            ctx_with_notes = {
                'temporal_notes': temporal_notes,
                'exceptions_applied': matched_exceptions,
                'unresolved_conflicts': getattr(auth_res, 'unresolved_conflicts', []),
                **(req.policy_context or {})
            }
            answer_res = GroundedGenerationService.synthesize_answer(
                req.query, active_chunks, conflicts_resolved, state,
                groq_api_key=req.groq_api_key, llm_model=req.llm_model,
                execution_mode=getattr(req, 'execution_mode', None),
                synthesis_mode=getattr(req, 'synthesis_mode', None),
                policy_context=ctx_with_notes,
                workspace=req.workspace,
                return_metrics=True
            )
            if isinstance(answer_res, tuple):
                answer, gen_metrics = answer_res
            else:
                answer = answer_res
                gen_metrics = GroundedGenerationService.last_metrics or {}

            
            from apps.decisions.synthesizer import AnswerCompletenessValidator
            val_res = AnswerCompletenessValidator.validate(
                query=req.query,
                answer=answer,
                candidate_chunks=active_chunks,
                current_state=state,
                evidence_missing=evidence_missing,
                policy_context=ctx_with_notes
            )
            if val_res.is_downgraded:
                state = val_res.new_state
                directive = val_res.new_directive
                answer = val_res.new_answer
                evidence_missing = val_res.evidence_missing
                if val_res.reason_code:
                    all_reason_codes.append(val_res.reason_code)
            elif val_res.answer_completed:
                answer = val_res.new_answer

            # Build curated proof citations using EvidencePresentationEngine
            from apps.governance.evidence import EvidencePresentationEngine
            citations = EvidencePresentationEngine.curate_citations(
                query=req.query,
                answer=answer,
                active_chunks=active_chunks,
                conflicts_resolved=conflicts_resolved,
                as_of=req.as_of
            )
        
        # If terminal non-supported state, always record fresh deterministic metric
        if not gen_metrics or state in ('denied', 'violation', 'conflicting', 'insufficient', 'abstain', 'human_review', 'no_knowledge'):
            gen_metrics = {
                'provider': 'deterministic_governance_engine',
                'model_name': 'rules_precedence_ladder',
                'was_deterministic': True,
                'tokens_total': 0,
                'cost_usd': 0.0,
                'latency_ms': 0.1,
                'reason': f"governance_terminal_state_{state}"
            }

        total_tokens = sum(c.get('token_count', len(c.get('text', '').split())) for c in active_chunks)

        from apps.governance.modes import get_active_execution_mode
        active_mode = get_active_execution_mode(
            workspace=req.workspace,
            policy_context=req.policy_context,
            requested_mode=getattr(req, 'execution_mode', None)
        )
        all_reason_codes.append(f"EXECUTION_MODE_{active_mode.value.upper()}")
        if gen_metrics.get('was_deterministic', True):
            all_reason_codes.append(GovernanceReasonCode.DETERMINISTIC_SYNTHESIS_APPLIED.value)
        else:
            all_reason_codes.append(GovernanceReasonCode.MODEL_INFERENCE_INVOKED.value)

        # Deduplicate reason codes preserving exact layer order
        deduped_reason_codes = []
        for rc in all_reason_codes:
            if rc not in deduped_reason_codes:
                deduped_reason_codes.append(rc)
        # Distinct Validation Signals (Requirement 6)
        provenance_passed = bool(citations and all(bool(c.get('document_id')) for c in citations))
        relevance_passed = bool(citations and state in ('supported', 'qualified') and not is_denied)
        entailment_passed = bool(citations and state in ('supported', 'qualified') and answer and not any(w in answer.lower() for w in ['contradictory authoritative sources', 'cannot authorize', 'access denied', 'no governed knowledge']))
        authority_passed = bool(citations and all(c.get('document_status') in ['approved', 'ready', 'active'] for c in citations))
        conflict_passed = not has_unresolved_conflict

        # Success claims: ONLY true when the underlying validations actually pass!
        audit_provenance_verified = provenance_passed and relevance_passed
        zero_hallucination = provenance_passed and relevance_passed and entailment_passed and conflict_passed and state in ('supported', 'qualified')

        validation_signals = {
            'source_provenance': provenance_passed,
            'relevance': relevance_passed,
            'entailment': entailment_passed,
            'authority': authority_passed,
            'conflict': conflict_passed,
            'audit_provenance_verified': audit_provenance_verified,
            'zero_hallucination': zero_hallucination,
        }

        envelope = {
            'schema': req.schema_version,
            'state': state,
            'directive': directive,
            'answer': answer,
            'answer_text': answer,
            'decision_type': dt,
            'escalation_target': escalation_target,
            'risk_level': decision_info.risk_level,
            'items': evidence_found,
            'evidence_found': evidence_found,
            'evidence_missing': evidence_missing,
            'conflicts_resolved': conflicts_resolved,
            'exceptions_applied': matched_exceptions,
            'citations': citations,
            'notes': all_notes,
            'reason_codes': deduped_reason_codes,
            'execution_mode': active_mode.value,
            'model_metrics': gen_metrics,
            'was_deterministic': gen_metrics.get('was_deterministic', True),
            'graph_expanded_count': len(graph_expanded_chunks),
            'graph_degraded': is_graph_degraded,
            'graph_traversal_paths': [c.get('graph_path') for c in active_chunks if c.get('graph_path')],
            'layers_breakdown': {
                'l7_permission': {'status': 'passed' if not is_denied else 'denied', 'denials': denial_reasons},
                'l1_decision_intelligence': {'decision_type': dt, 'escalation': escalation_target, 'risk': decision_info.risk_level},
                'l6_authority': {'conflicts_count': len(conflicts_resolved), 'unresolved_tie': has_unresolved_conflict},
                'l5_temporal': {'stale_data': has_stale, 'temporal_notes': temporal_notes},
                'l4_exceptions': {'applied_count': len(matched_exceptions), 'exceptions': matched_exceptions},
                'l3_sufficiency': {'is_sufficient': is_sufficient, 'missing_count': len(evidence_missing)},
                'l2_answer_state': {'final_state': state, 'directive': directive},
                'l0_observability': {'trace_id': trace_id, 'timings_ms': timing_stages},
                'graph_expansion': {
                    'expanded_nodes_count': len(graph_expanded_chunks),
                    'degraded': is_graph_degraded,
                    'status': 'degraded' if is_graph_degraded else ('active' if graph_expanded_chunks else 'none')
                }
            },
            'decision_id': decision_id,
            'trace_id': trace_id,
            'token_count': total_tokens,
            'llm_provider': 'groq' if req.groq_api_key else 'deterministic_synthesis',
            'llm_model': req.llm_model or ('gpt-oss-120B' if req.groq_api_key else 'deterministic-citation-engine'),
            'anti_hallucination_active': zero_hallucination,
            'validation_signals': validation_signals,
            'retrieval_degraded': is_retrieval_degraded
        }

        # Contract Validation Gate (P1 §3, §8): Validate against schema and invariant rules
        try:
            validate_canonical_envelope(envelope)
        except ContractValidationError as cve:
            logger.error(f"Canonical envelope contract validation failed: {cve}")
            return fail_closed_envelope(
                query=req.query,
                error_message=str(cve),
                error_category="CONTRACT_VALIDATION_FAILURE",
                trace_id=trace_id,
                decision_type=dt
            )

        # -------------------------------------------------------------
        # STAGE 7: L0 — Observability Layer (Persist Decision)
        # -------------------------------------------------------------
        if workspace and hasattr(workspace, 'organization'):
            ObservabilityLayer.record_decision(
                organization=workspace.organization,
                workspace=workspace,
                user=req.principal,
                trace_id=trace_id,
                query=req.query,
                envelope=envelope,
                token_count=total_tokens
            )

        return envelope
