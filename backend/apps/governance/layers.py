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
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import List, Dict, Any, Optional, Tuple, Union
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
    def __new__(cls, conflicts_resolved, has_unresolved_tie, notes, reason_codes=None):
        return super().__new__(cls, (conflicts_resolved, has_unresolved_tie, notes))

    def __init__(self, conflicts_resolved, has_unresolved_tie, notes, reason_codes=None):
        self.conflicts_resolved = conflicts_resolved
        self.has_unresolved_tie = has_unresolved_tie
        self.notes = notes
        self.reason_codes = reason_codes or []


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

        if explicit_decision_type and explicit_decision_type in cls.DECISION_CATALOG:
            dt = explicit_decision_type
            reason_codes.append(GovernanceReasonCode.L1_EXPLICIT_DECISION_TYPE.value)
        else:
            q_lower = query.lower()
            is_procurement_action = any(w in q_lower for w in ['approve', 'purchase', 'procure', 'buy', 'license', 'adopt', 'contract', 'onboard', 'can we use', 'can i use'])
            is_vendor_entity = any(w in q_lower for w in ['vendor', 'cloudbox', 'third-party', 'supplier'])

            if any(w in q_lower for w in ['দলিল', 'খতিয়ান', 'খতিয়ান', 'মৌজা', 'সাফ কবলা', 'deed', 'khatian', 'schedule of property', 'statutory']):
                dt = 'statutory_compliance'
            elif (is_vendor_entity and is_procurement_action) or ('cloudbox' in q_lower) or (is_procurement_action and any(w in q_lower for w in ['tool', 'software'])):
                dt = 'vendor_approval'
            elif any(w in q_lower for w in ['privacy', 'gdpr', 'customer data', 'pii', 'retention', 'residency', 'sovereignty']):
                dt = 'data_processing'
            elif any(w in q_lower for w in ['deploy', 'production', 'release', 'launch', 'staging']):
                dt = 'deployment_approval'
            elif any(w in q_lower for w in ['security', 'password', 'jwt', 'auth', 'token', 'policy', 'compliance']):
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
    def evaluate_conflicts(
        cls,
        chunks: List[Dict[str, Any]],
        workspace_id: Optional[str] = None
    ) -> AuthorityConflictTuple:
        conflicts_resolved = []
        has_unresolved_tie = False
        notes = []
        reason_codes = []

        if len(chunks) < 2:
            if chunks:
                reason_codes.append(GovernanceReasonCode.L6_SINGLE_SOURCE_AUTHORITATIVE.value)
            return AuthorityConflictTuple(conflicts_resolved, has_unresolved_tie, notes, reason_codes)

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
            )
            for cr in db_conflicts:
                if cr.resolution_status == 'unresolved':
                    has_unresolved_tie = True
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

        # 2. Check for informal claim overriding formal preconditions
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

        # 3. Check for same-rank direct contradictions
        rank_groups: Dict[int, List[Dict[str, Any]]] = {}
        for c in chunks:
            r = c.get('authority_level', 3)
            rank_groups.setdefault(r, []).append(c)

        for rank, group in rank_groups.items():
            if len(group) >= 2 and rank >= 3:
                positive_chunks = [c for c in group if any(w in c.get('text', '').lower() for w in ['approved', 'permitted', 'allowed'])]
                negative_chunks = [c for c in group if any(w in c.get('text', '').lower() for w in ['prohibit', 'forbidden', 'denied', 'must not'])]
                if positive_chunks and negative_chunks:
                    pos_c = positive_chunks[0]
                    neg_c = negative_chunks[0]
                    # Chunks from the same document are internal conditions/clauses, not cross-source contradictions
                    if pos_c.get('document_id') and neg_c.get('document_id') and str(pos_c.get('document_id')) == str(neg_c.get('document_id')):
                        continue
                    pos_ver = pos_c.get('document_version', 1)
                    neg_ver = neg_c.get('document_version', 1)
                    if pos_ver > neg_ver:
                        conflicts_resolved.append({
                            'informal_claim': neg_c.get('text', '')[:120].strip(),
                            'authoritative_source': f"{pos_c.get('document_title')} (v{pos_ver})",
                            'resolution': 'version_supersession',
                            'note': f"Version {pos_ver} supersedes earlier version {neg_ver} at Rank {rank}."
                        })
                        notes.append(f"Supersession Resolution (L6): {pos_c.get('document_title')} v{pos_ver} supersedes v{neg_ver}.")
                        reason_codes.append(GovernanceReasonCode.L6_VERSION_SUPERSESSION.value)
                    elif neg_ver > pos_ver:
                        conflicts_resolved.append({
                            'informal_claim': pos_c.get('text', '')[:120].strip(),
                            'authoritative_source': f"{neg_c.get('document_title')} (v{neg_ver})",
                            'resolution': 'version_supersession',
                            'note': f"Version {neg_ver} supersedes earlier version {pos_ver} at Rank {rank}."
                        })
                        notes.append(f"Supersession Resolution (L6): {neg_c.get('document_title')} v{neg_ver} supersedes v{pos_ver}.")
                        reason_codes.append(GovernanceReasonCode.L6_VERSION_SUPERSESSION.value)
                    else:
                        # Contradiction at equal rank and equal version -> unresolved tie!
                        has_unresolved_tie = True
                        notes.append(f"Unresolved Contradiction (L6): Two authoritative sources at Rank {rank} disagree without dominance or supersession.")
                        reason_codes.append(GovernanceReasonCode.L6_UNRESOLVED_CONTRADICTION.value)

        # Deduplicate reason codes
        deduped = []
        for r in reason_codes:
            if r not in deduped:
                deduped.append(r)

        return AuthorityConflictTuple(conflicts_resolved, has_unresolved_tie, notes, deduped)


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
    def evaluate(
        cls,
        chunks: List[Dict[str, Any]],
        as_of: Optional[Any] = None
    ) -> TemporalEvaluationTuple:
        valid_chunks = []
        temporal_notes = []
        has_stale_data = False
        reason_codes = []

        # Parse and normalize as_of reference timestamp
        if isinstance(as_of, str):
            from django.utils.dateparse import parse_datetime, parse_date
            parsed = parse_datetime(as_of)
            if not parsed:
                d = parse_date(as_of)
                if d:
                    parsed = datetime(d.year, d.month, d.day, 0, 0, 0)
            ref_time = parsed or timezone.now()
            reason_codes.append(GovernanceReasonCode.L5_HISTORICAL_AS_OF_APPLIED.value)
        elif isinstance(as_of, datetime):
            ref_time = as_of
            reason_codes.append(GovernanceReasonCode.L5_HISTORICAL_AS_OF_APPLIED.value)
        else:
            ref_time = timezone.now()

        if timezone.is_naive(ref_time):
            ref_time = timezone.make_aware(ref_time, dt_timezone.utc)

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

        # Check canonical supersession via approved KnowledgeRelationship(SUPERSEDES)
        superseded_doc_ids = set()
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
                        if s_doc and s_doc.status == 'ready':
                            s_eff = s_doc.effective_date
                            if s_eff:
                                if timezone.is_naive(s_eff):
                                    s_eff = timezone.make_aware(s_eff, dt_timezone.utc)
                                if s_eff > ref_time:
                                    continue  # Superseding doc not yet effective as of query time
                            superseded_doc_ids.add(str(s_rel.target_document_id))
                            t_title = s_rel.target_document.title if s_rel.target_document else str(s_rel.target_document_id)
                            temporal_notes.append(
                                f"Supersession Exclusion: Document '{t_title}' is superseded by '{s_doc.title}' "
                                f"(effective as of {ref_time.strftime('%Y-%m-%d')})."
                            )
                            reason_codes.append(GovernanceReasonCode.L5_SUPERSEDED_DOCUMENT_EXCLUSION.value)
            except Exception as e:
                logger.warning(f"Error checking supersession in TemporalValidityLayer: {e}")

        for chk in chunks:
            doc = docs_map.get(str(chk.get('document_id', '')))
            if not doc:
                valid_chunks.append(chk)
                continue

            # Check if document is superseded by an active, effective policy
            if str(doc.id) in superseded_doc_ids:
                continue

            # 0. Stable-Only Serving Check (P1 §6): Only 'ready' documents may serve as authoritative evidence
            if doc.status != 'ready':
                temporal_notes.append(
                    f"Lifecycle Exclusion (P1 §6): Document '{doc.title}' has status '{doc.status}' (not 'ready'). "
                    "Draft, quarantined, or processing records cannot serve as authoritative evidence."
                )
                reason_codes.append(GovernanceReasonCode.L5_LIFECYCLE_EXCLUSION.value)
                continue

            # 1. Not yet effective check
            eff = doc.effective_date
            if eff:
                if timezone.is_naive(eff):
                    eff = timezone.make_aware(eff, dt_timezone.utc)
                if eff > ref_time:
                    temporal_notes.append(
                        f"Document '{doc.title}' is not yet effective (effective {eff.strftime('%Y-%m-%d')}). Excluded from active context."
                    )
                    reason_codes.append(GovernanceReasonCode.L5_FUTURE_EFFECTIVE_EXCLUSION.value)
                    continue

            # 2. Expiration check
            exp = doc.expiration_date
            if exp:
                if timezone.is_naive(exp):
                    exp = timezone.make_aware(exp, dt_timezone.utc)
                if exp < ref_time:
                    temporal_notes.append(
                        f"Document '{doc.title}' expired on {exp.strftime('%Y-%m-%d')}. Excluded."
                    )
                    reason_codes.append(GovernanceReasonCode.L5_EXPIRATION_EXCLUSION.value)
                    continue

            # 3. Staleness aging check
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
        active_exceptions = ScopedException.objects.filter(
            workspace_id=workspace_id,
            status='active'
        )
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

        # 1. Vendor Approval Sufficiency Checks
        if dt == 'vendor_approval':
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

        # 3. Data Processing Sufficiency Checks
        elif dt == 'data_processing':
            has_retention = any(w in all_text for w in ['retention', 'deletion', 'erasure', 'consent', 'gdpr'])
            if not has_retention:
                evidence_missing.append({
                    'requirement': 'data_retention_and_consent_policy',
                    'mandatory': True,
                    'status': EvidenceStatus.MISSING.value,
                    'description': 'Defined data retention schedule and lawful processing consent records are missing.'
                })
                reason_codes.append(GovernanceReasonCode.L3_MANDATORY_EVIDENCE_MISSING.value)

        # 4. Database-Configured Workspace Evidence Requirements
        if workspace_id:
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

        # 5. Authority Threshold Check: Top evidence must have sufficient authority for high-risk governance
        if dt in ('vendor_approval', 'data_processing', 'statutory_compliance', 'deployment_approval'):
            max_auth = max([c.get('authority_level', 1) for c in retrieved_chunks], default=0)
            if max_auth > 0 and max_auth <= 2 and not has_exception:
                evidence_missing.append({
                    'requirement': 'authoritative_controlling_source',
                    'mandatory': True,
                    'status': EvidenceStatus.INSUFFICIENT_AUTHORITY.value,
                    'description': f'Top evidence has informal authority rank {max_auth}; decisions of type {dt} require verified policy or contract rank >= 4.'
                })
                reason_codes.append(GovernanceReasonCode.L3_INSUFFICIENT_AUTHORITY_RANK.value)

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
            cleared_chunks, as_of=req.as_of
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
            active_chunks, workspace_id=ws_id
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
            has_proposing_bypass = any(w in q_lower for w in ['without', 'bypass', 'skip', 'disable', 'disregard'])
            if has_proposing_bypass:
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
            answer = (
                f"Governance Warning: Contradictory authoritative sources detected for '{req.query}'. "
                "LORE will not guess between equal-authority policies. Please request human adjudication."
            )
            citations = []
        elif state == 'no_knowledge':
            answer = f"No governed knowledge found in active workspace matching '{req.query}'."
            citations = []
        else:
            # Grounded generation for supported/qualified outcomes
            from apps.decisions.engine import GroundedGenerationService
            ctx_with_notes = {
                'temporal_notes': temporal_notes,
                'exceptions_applied': matched_exceptions,
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

            # Answer Completeness Validation Gate:
            # Before returning SUPPORTED, compare the final answer against the question's requested facts.
            # If any required part is missing, complete from evidence or downgrade to insufficient.
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
        deduped_reason_codes.append(GovernanceReasonCode.CONTRACT_VALIDATION_PASSED.value)

        envelope = {
            'schema': req.schema_version,
            'state': state,
            'directive': directive,
            'answer': answer,
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
            'anti_hallucination_active': True,
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
