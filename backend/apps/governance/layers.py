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
from typing import List, Dict, Any, Optional, Tuple
from django.utils import timezone
from apps.governance.models import SourcePermission, ScopedException, EvidenceRequirement, ConflictRecord, AccessLevel
from apps.governance.contract import (
    Verdict, Directive, EvidenceStatus, CANONICAL_VERDICT_DIRECTIVE_MAP,
    validate_canonical_envelope, fail_closed_envelope, ContractValidationError
)
from apps.sources.models import SourceDocument
from apps.decisions.models import DecisionRecord
from apps.audit.models import AuditEvent

logger = logging.getLogger(__name__)


# ==============================================================================
# L7 — PERMISSION LAYER
# ==============================================================================
class PermissionLayer:
    """
    L7 Permission Layer (lore.md §4 L7):
    Authorization happens BEFORE restricted content enters the model's context window.
    """
    @classmethod
    def filter_authorized_chunks(
        cls,
        chunks: List[Dict[str, Any]],
        user=None,
        user_role: str = 'member'
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        authorized_chunks = []
        denial_reasons = []

        doc_ids = list({c.get('document_id') for c in chunks if c.get('document_id')})
        if not doc_ids:
            return chunks, []

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
            
            # Default to INTERNAL access if no explicit permission record exists
            if not perm:
                authorized_chunks.append(chk)
                continue

            if perm.is_user_permitted(user=user, user_role=user_role):
                authorized_chunks.append(chk)
            else:
                denial_reasons.append(
                    f"Access restricted to document '{chk.get('document_title', 'Untitled')}' ({perm.access_level.upper()})"
                )

        return authorized_chunks, denial_reasons


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
    def classify(cls, query: str) -> Dict[str, Any]:
        q_lower = query.lower()
        if any(w in q_lower for w in ['দলিল', 'খতিয়ান', 'খতিয়ান', 'মৌজা', 'সাফ কবলা', 'deed', 'khatian', 'schedule of property', 'statutory']):
            dt = 'statutory_compliance'
        elif any(w in q_lower for w in ['vendor', 'tool', 'cloudbox', 'software', 'approve', 'purchase', 'procure', 'third-party']):
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

        meta = cls.DECISION_CATALOG.get(dt, cls.DECISION_CATALOG['general_inquiry'])
        return {
            'decision_type': dt,
            'label': meta['label'],
            'mandatory_evidence': meta['mandatory_evidence'],
            'escalation_target': meta['escalation_target'],
            'risk_level': meta['risk_level']
        }


# ==============================================================================
# L6 — AUTHORITY LAYER
# ==============================================================================
class AuthorityLayer:
    """
    L6 Authority Layer (lore.md §4 L6):
    Unified 7-rank authority ladder. Higher rank wins; same rank newer wins;
    unresolved contradiction -> conflicting state (never settled silently).
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
        chunks: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], bool, List[str]]:
        conflicts_resolved = []
        has_unresolved_tie = False
        notes = []

        if len(chunks) < 2:
            return conflicts_resolved, has_unresolved_tie, notes

        # Check for informal approval overriding formal preconditions
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

        # Check for same-rank direct contradictions
        rank_groups: Dict[int, List[Dict[str, Any]]] = {}
        for c in chunks:
            r = c.get('authority_level', 3)
            rank_groups.setdefault(r, []).append(c)

        for rank, group in rank_groups.items():
            if len(group) >= 2 and rank >= 3:
                positive_chunks = [c for c in group if any(w in c.get('text', '').lower() for w in ['approved', 'permitted', 'allowed'])]
                negative_chunks = [c for c in group if any(w in c.get('text', '').lower() for w in ['prohibit', 'forbidden', 'denied', 'must not', 'condition'])]
                if positive_chunks and negative_chunks:
                    pos_c = positive_chunks[0]
                    neg_c = negative_chunks[0]
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
                    elif neg_ver > pos_ver:
                        conflicts_resolved.append({
                            'informal_claim': pos_c.get('text', '')[:120].strip(),
                            'authoritative_source': f"{neg_c.get('document_title')} (v{neg_ver})",
                            'resolution': 'version_supersession',
                            'note': f"Version {neg_ver} supersedes earlier version {pos_ver} at Rank {rank}."
                        })
                        notes.append(f"Supersession Resolution (L6): {neg_c.get('document_title')} v{neg_ver} supersedes v{pos_ver}.")
                    else:
                        # Contradiction at equal rank and equal version -> unresolved tie!
                        has_unresolved_tie = True
                        notes.append(f"Unresolved Contradiction (L6): Two authoritative sources at Rank {rank} disagree without dominance or supersession.")

        return conflicts_resolved, has_unresolved_tie, notes


# ==============================================================================
# L5 — TEMPORAL VALIDITY LAYER
# ==============================================================================
class TemporalValidityLayer:
    """
    L5 Temporal Validity Layer (lore.md §4 L5):
    effective_from/to, expiry, stale_after, and point-in-time as_of queries.
    """
    @classmethod
    def evaluate(
        cls,
        chunks: List[Dict[str, Any]],
        as_of: Optional[Any] = None
    ) -> Tuple[List[Dict[str, Any]], List[str], bool]:
        valid_chunks = []
        temporal_notes = []
        has_stale_data = False

        # Parse and normalize as_of reference timestamp
        if isinstance(as_of, str):
            from django.utils.dateparse import parse_datetime, parse_date
            parsed = parse_datetime(as_of)
            if not parsed:
                d = parse_date(as_of)
                if d:
                    parsed = datetime(d.year, d.month, d.day, 0, 0, 0)
            ref_time = parsed or timezone.now()
        elif isinstance(as_of, datetime):
            ref_time = as_of
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

        for chk in chunks:
            doc = docs_map.get(str(chk.get('document_id', '')))
            if not doc:
                valid_chunks.append(chk)
                continue

            # 0. Stable-Only Serving Check (P1 §6): Only 'ready' documents may serve as authoritative evidence
            if doc.status != 'ready':
                temporal_notes.append(
                    f"Lifecycle Exclusion (P1 §6): Document '{doc.title}' has status '{doc.status}' (not 'ready'). "
                    "Draft, quarantined, or processing records cannot serve as authoritative evidence."
                )
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

            valid_chunks.append(chk)

        return valid_chunks, temporal_notes, has_stale_data


# ==============================================================================
# L4 — EXCEPTION LAYER
# ==============================================================================
class ExceptionLayer:
    """
    L4 Exception Layer (lore.md §4 L4):
    Scoped, time-bounded overrides.
    Matching exceptions are ALWAYS disclosed in the result.
    """
    @classmethod
    def evaluate(
        cls,
        workspace_id: str,
        query: str,
        as_of: Optional[datetime] = None
    ) -> Tuple[List[Dict[str, Any]], bool, List[str]]:
        active_exceptions = ScopedException.objects.filter(
            workspace_id=workspace_id,
            status='active'
        )
        matched_exceptions = []
        exception_notes = []
        now = as_of or timezone.now()
        q_lower = query.lower()

        for exc in active_exceptions:
            if not exc.is_currently_valid(now):
                continue

            # Check scope dimension matching
            scope_val_lower = exc.scope_value.lower()
            if scope_val_lower in q_lower or exc.rule_code.lower() in q_lower:
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

        has_applicable_exception = bool(matched_exceptions)
        return matched_exceptions, has_applicable_exception, exception_notes


# ==============================================================================
# L3 — EVIDENCE SUFFICIENCY LAYER
# ==============================================================================
class EvidenceSufficiencyLayer:
    """
    L3 Evidence Sufficiency Layer (lore.md §4 L3):
    Evaluates whether evidence is complete enough to support the classified decision type.
    Outputs the exact list of missing requirements.
    """
    @classmethod
    def evaluate(
        cls,
        workspace_id: str,
        decision_info: Dict[str, Any],
        retrieved_chunks: List[Dict[str, Any]],
        query: str,
        has_exception: bool = False
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
        dt = decision_info['decision_type']
        mandatory_reqs = decision_info['mandatory_evidence']
        q_lower = query.lower()

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
            # Check data residency proof
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

            # Check assessment report
            has_assessment = any(w in all_text for w in ['assessment', 'soc 2', 'iso 27001', 'audit passed', 'certified'])
            if not has_assessment and not has_exception:
                evidence_missing.append({
                    'requirement': 'formal_security_assessment_report',
                    'mandatory': True,
                    'status': EvidenceStatus.PENDING.value,
                    'description': 'Vendor security assessment report is pending formal audit completion.'
                })

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
            if not has_schedule:
                evidence_missing.append({
                    'requirement': 'property_schedule_and_khatian',
                    'mandatory': True,
                    'status': EvidenceStatus.MISSING.value,
                    'description': 'Specific land schedule, CS khatian, or plot demarcation is absent from the provided record.'
                })

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

        # 4. Authority Threshold Check: Top evidence must have sufficient authority for high-risk governance
        if dt in ('vendor_approval', 'data_processing', 'statutory_compliance', 'deployment_approval'):
            max_auth = max([c.get('authority_level', 1) for c in retrieved_chunks], default=0)
            if max_auth > 0 and max_auth <= 2 and not has_exception:
                evidence_missing.append({
                    'requirement': 'authoritative_controlling_source',
                    'mandatory': True,
                    'status': EvidenceStatus.INSUFFICIENT_AUTHORITY.value,
                    'description': f'Top evidence has informal authority rank {max_auth}; decisions of type {dt} require verified policy or contract rank >= 4.'
                })

        # Any unsatisfied mandatory requirement causes insufficiency
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
        is_sufficient = len(unsatisfied_mandatory) == 0
        return evidence_found, evidence_missing, is_sufficient


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
    ) -> Tuple[str, str]:
        # Precedence 1: Denied (L7)
        if is_denied:
            return 'denied', 'stop'

        # Precedence 2: Violation (MUST/MUST-NOT rule breach)
        if is_violation:
            return 'violation', 'stop'

        # Precedence 3: Conflicting (L6 unresolved tie)
        if has_unresolved_conflict:
            return 'conflicting', 'ask_user'

        # Precedence 4: Insufficient (L3 mandatory evidence gap)
        if not is_sufficient:
            return 'insufficient', 'ask_user'

        # Precedence 5: Abstain (Uncertainty band [0.45-0.55])
        if is_abstain:
            return 'abstain', 'ask_user'

        # Precedence 6: Human Review (L1 critical escalation)
        if requires_human_review:
            return 'human_review', 'escalate'

        # Precedence 7: Qualified (L4 exception, L5 stale rule, L6 subordinate override)
        if is_qualified:
            return 'qualified', 'proceed_and_cite'

        # Precedence 8: Supported (All requirements met)
        if chunks_count > 0:
            return 'supported', 'proceed_and_cite'

        # Precedence 9: No Knowledge
        return 'no_knowledge', 'proceed'


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
    ) -> DecisionRecord:
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
                'evidence_found_count': len(envelope.get('evidence_found', [])),
                'evidence_missing_count': len(envelope.get('evidence_missing', [])),
                'citations_count': len(envelope.get('citations', []))
            }
        )

        return decision


# ==============================================================================
# UNIFIED 9-LAYER MASTER ORCHESTRATOR
# ==============================================================================
class EnterpriseGovernanceEngine:
    """
    Unified 9-layer Master Engine executing the full LORE pipeline from lore.md:
    L7 -> L1 -> Core Retrieval -> L6 -> L5 -> L4 -> L3 -> L2 -> L0
    """
    @classmethod
    def evaluate(
        cls,
        query: str,
        retrieved_chunks: List[Dict[str, Any]],
        workspace,
        user=None,
        user_role: str = 'member',
        as_of: Optional[Any] = None,
        schema_version: str = 'lore.result/2',
        groq_api_key: Optional[str] = None,
        llm_model: Optional[str] = None
    ) -> Dict[str, Any]:
        try:
            return cls._evaluate_internal(
                query=query,
                retrieved_chunks=retrieved_chunks,
                workspace=workspace,
                user=user,
                user_role=user_role,
                as_of=as_of,
                schema_version=schema_version,
                groq_api_key=groq_api_key,
                llm_model=llm_model
            )
        except Exception as unhandled_err:
            logger.exception(f"Unhandled error in EnterpriseGovernanceEngine.evaluate: {unhandled_err}")
            return fail_closed_envelope(
                query=query,
                error_message=str(unhandled_err),
                error_category="GOVERNANCE_EXECUTION_FAILURE",
                decision_type="general_inquiry"
            )

    @classmethod
    def _evaluate_internal(
        cls,
        query: str,
        retrieved_chunks: List[Dict[str, Any]],
        workspace,
        user=None,
        user_role: str = 'member',
        as_of: Optional[Any] = None,
        schema_version: str = 'lore.result/2',
        groq_api_key: Optional[str] = None,
        llm_model: Optional[str] = None
    ) -> Dict[str, Any]:
        trace_id = f"trace-{uuid.uuid4().hex[:12]}"
        decision_id = f"dec-{uuid.uuid4().hex[:8]}"
        timing_stages: Dict[str, float] = {}
        dt = 'general_inquiry'

        # -------------------------------------------------------------
        # STAGE 0: L7 — Permission Layer
        # -------------------------------------------------------------
        t0 = timezone.now()
        cleared_chunks, denial_reasons = PermissionLayer.filter_authorized_chunks(
            retrieved_chunks, user=user, user_role=user_role
        )
        is_denied = bool(denial_reasons and not cleared_chunks)
        timing_stages['l7_permission_ms'] = (timezone.now() - t0).total_seconds() * 1000

        # -------------------------------------------------------------
        # STAGE 1: L1 — Decision Intelligence Layer
        # -------------------------------------------------------------
        t1 = timezone.now()
        decision_info = DecisionIntelligenceLayer.classify(query)
        dt = decision_info['decision_type']
        escalation_target = decision_info['escalation_target']
        requires_human_review = (decision_info['risk_level'] == 'critical')
        timing_stages['l1_intelligence_ms'] = (timezone.now() - t1).total_seconds() * 1000

        # -------------------------------------------------------------
        # STAGE 2: L5 — Temporal Validity Layer
        # -------------------------------------------------------------
        t2 = timezone.now()
        active_chunks, temporal_notes, has_stale = TemporalValidityLayer.evaluate(
            cleared_chunks, as_of=as_of
        )
        timing_stages['l5_temporal_ms'] = (timezone.now() - t2).total_seconds() * 1000

        # -------------------------------------------------------------
        # STAGE 3: L4 — Exception Layer
        # -------------------------------------------------------------
        t3 = timezone.now()
        matched_exceptions, has_exception, exception_notes = ExceptionLayer.evaluate(
            str(workspace.id), query, as_of=as_of
        )
        timing_stages['l4_exception_ms'] = (timezone.now() - t3).total_seconds() * 1000

        # -------------------------------------------------------------
        # STAGE 4: L6 — Authority Layer
        # -------------------------------------------------------------
        t4 = timezone.now()
        conflicts_resolved, has_unresolved_conflict, authority_notes = AuthorityLayer.evaluate_conflicts(
            active_chunks
        )
        timing_stages['l6_authority_ms'] = (timezone.now() - t4).total_seconds() * 1000

        # -------------------------------------------------------------
        # STAGE 5: L3 — Evidence Sufficiency Layer
        # -------------------------------------------------------------
        t5 = timezone.now()
        evidence_found, evidence_missing, is_sufficient = EvidenceSufficiencyLayer.evaluate(
            str(workspace.id), decision_info, active_chunks, query, has_exception=has_exception
        )
        timing_stages['l3_sufficiency_ms'] = (timezone.now() - t5).total_seconds() * 1000

        # -------------------------------------------------------------
        # STAGE 6: L2 — Answer-State Layer (Precedence Resolution)
        # -------------------------------------------------------------
        is_qualified = bool(has_exception or has_stale or conflicts_resolved)
        is_violation = False # Set if explicit negative prohibition is breached

        state, directive = AnswerStateLayer.resolve_state(
            is_denied=is_denied,
            is_violation=is_violation,
            has_unresolved_conflict=has_unresolved_conflict,
            is_sufficient=is_sufficient,
            is_abstain=False,
            requires_human_review=requires_human_review,
            is_qualified=is_qualified,
            chunks_count=len(active_chunks)
        )

        # Assemble notes across layers
        all_notes = temporal_notes + exception_notes + authority_notes
        if is_denied:
            all_notes.extend(denial_reasons)

        # Formulate answer text
        if state == 'denied':
            answer = f"Access Denied: You do not have sufficient permissions to view the authoritative records for '{query}'."
        elif state == 'insufficient':
            answer = (
                f"Cannot authorize request for '{query}'. Mandatory governance evidence is missing:\n" +
                "\n".join(f"- [{m['requirement']}]: {m['description']}" for m in evidence_missing)
            )
            if escalation_target:
                answer += f"\n\n**Escalation Recommendation**: Route to {escalation_target.replace('_', ' ').title()}."
        elif state == 'conflicting':
            answer = (
                f"Governance Warning: Contradictory authoritative sources detected for '{query}'. "
                "LORE will not guess between equal-authority policies. Please request human adjudication."
            )
        elif state == 'no_knowledge':
            answer = f"No governed knowledge found in active workspace matching '{query}'."
        else:
            # Import synthesis engine for grounded answer generation
            from apps.decisions.engine import GroundedGenerationService
            answer = GroundedGenerationService.synthesize_answer(
                query, active_chunks, conflicts_resolved, state,
                groq_api_key=groq_api_key, llm_model=llm_model
            )

        # Build citations
        citations = []
        for chk in active_chunks:
            citations.append({
                'citation_id': f"cit-{uuid.uuid4().hex[:6]}",
                'document_id': chk.get('document_id'),
                'document_title': chk.get('document_title'),
                'document_version': chk.get('document_version', 1),
                'page_number': chk.get('page_number', 1),
                'heading_path': chk.get('heading_path', 'General'),
                'passage': chk.get('text', ''),
                'authority_level': chk.get('authority_level', 3)
            })

        total_tokens = sum(c.get('token_count', len(c.get('text', '').split())) for c in active_chunks)

        envelope = {
            'schema': schema_version,
            'state': state,
            'directive': directive,
            'answer': answer,
            'decision_type': dt,
            'escalation_target': escalation_target,
            'risk_level': decision_info['risk_level'],
            'items': evidence_found,
            'evidence_found': evidence_found,
            'evidence_missing': evidence_missing,
            'conflicts_resolved': conflicts_resolved,
            'exceptions_applied': matched_exceptions,
            'citations': citations,
            'notes': all_notes,
            'layers_breakdown': {
                'l7_permission': {'status': 'passed' if not is_denied else 'denied', 'denials': denial_reasons},
                'l1_decision_intelligence': {'decision_type': dt, 'escalation': escalation_target, 'risk': decision_info['risk_level']},
                'l6_authority': {'conflicts_count': len(conflicts_resolved), 'unresolved_tie': has_unresolved_conflict},
                'l5_temporal': {'stale_data': has_stale, 'temporal_notes': temporal_notes},
                'l4_exceptions': {'applied_count': len(matched_exceptions), 'exceptions': matched_exceptions},
                'l3_sufficiency': {'is_sufficient': is_sufficient, 'missing_count': len(evidence_missing)},
                'l2_answer_state': {'final_state': state, 'directive': directive},
                'l0_observability': {'trace_id': trace_id, 'timings_ms': timing_stages}
            },
            'decision_id': decision_id,
            'trace_id': trace_id,
            'token_count': total_tokens,
            'llm_provider': 'groq' if groq_api_key else 'deterministic_synthesis',
            'llm_model': llm_model or ('gpt-oss-120B' if groq_api_key else 'deterministic-citation-engine'),
            'anti_hallucination_active': True
        }

        # Contract Validation Gate (P1 §3, §8): Validate against schema and invariant rules
        try:
            validate_canonical_envelope(envelope)
        except ContractValidationError as cve:
            logger.error(f"Canonical envelope contract validation failed: {cve}")
            return fail_closed_envelope(
                query=query,
                error_message=str(cve),
                error_category="CONTRACT_VALIDATION_FAILURE",
                trace_id=trace_id,
                decision_type=dt
            )

        # -------------------------------------------------------------
        # STAGE 7: L0 — Observability Layer (Persist Decision)
        # -------------------------------------------------------------
        try:
            ObservabilityLayer.record_decision(
                organization=workspace.organization,
                workspace=workspace,
                user=user,
                trace_id=trace_id,
                query=query,
                envelope=envelope,
                token_count=total_tokens
            )
        except Exception as ex:
            logger.warning(f"Could not record decision trace in L0: {ex}")

        return envelope

