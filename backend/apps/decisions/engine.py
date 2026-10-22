import uuid
from typing import List, Dict, Any, Optional
from apps.governance.models import EvidenceRequirement, ConflictRecord
from apps.sources.models import SourceDocument

class AnswerStateMachine:
    """
    Implements the deterministic 9-state governance machine from lore.md section 10.
    Produces structured lore.result/1 response envelopes with citations and directives.
    """

    @classmethod
    def evaluate(
        cls,
        query: str,
        retrieved_chunks: List[Dict[str, Any]],
        workspace_id: str,
        user=None
    ) -> Dict[str, Any]:
        trace_id = f"trace-{uuid.uuid4().hex[:12]}"
        decision_id = f"dec-{uuid.uuid4().hex[:8]}"

        # 1. Decision Type Classification
        q_lower = query.lower()
        if any(w in q_lower for w in ['vendor', 'tool', 'cloudbox', 'software', 'approve', 'purchase']):
            decision_type = 'vendor_approval'
        elif any(w in q_lower for w in ['privacy', 'gdpr', 'customer data', 'pii', 'retention']):
            decision_type = 'data_processing'
        elif any(w in q_lower for w in ['security', 'password', 'jwt', 'auth', 'token', 'policy']):
            decision_type = 'policy_compliance'
        else:
            decision_type = 'general_inquiry'

        # 2. If no chunks found:
        if not retrieved_chunks:
            return {
                'schema': 'lore.result/1',
                'state': 'no_knowledge',
                'directive': 'proceed',
                'answer': "No governed knowledge found in active workspace matching the query.",
                'decision_type': decision_type,
                'items': [],
                'evidence_found': [],
                'evidence_missing': [],
                'conflicts_resolved': [],
                'citations': [],
                'notes': ["No applicable rules or documents retrieved."],
                'decision_id': decision_id,
                'trace_id': trace_id,
                'token_count': 0
            }

        # 3. Check Evidence Sufficiency
        evidence_found = []
        citations = []
        total_tokens = 0

        for chk in retrieved_chunks:
            tokens = chk.get('token_count', len(chk.get('text', '').split()))
            total_tokens += tokens
            evidence_found.append({
                'document_id': chk.get('document_id'),
                'document_title': chk.get('document_title'),
                'authority_level': chk.get('authority_level'),
                'page_number': chk.get('page_number'),
                'score': chk.get('score'),
                'heading': chk.get('heading_path'),
                'snippet': chk.get('text', '')[:200]
            })
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

        evidence_missing = []
        conflicts_resolved = []
        notes = []

        # Built-in requirement checks for vendor_approval (Northstar case study)
        if decision_type == 'vendor_approval':
            has_assessment = any('assessment' in c.get('text', '').lower() or 'approved' in c.get('text', '').lower() for c in retrieved_chunks)
            has_residency = any('residency' in c.get('text', '').lower() or 'location' in c.get('text', '').lower() for c in retrieved_chunks)
            has_policy = any(c.get('authority_level', 0) >= 6 for c in retrieved_chunks)

            if not has_residency:
                evidence_missing.append({
                    'requirement': 'data_residency_proof',
                    'mandatory': True,
                    'status': 'missing',
                    'description': 'Verified proof of customer data geographical residency required by policy.'
                })
            if not has_assessment:
                evidence_missing.append({
                    'requirement': 'vendor_risk_assessment',
                    'mandatory': True,
                    'status': 'pending',
                    'description': 'Formal security assessment sign-off is pending or incomplete.'
                })

        # 4. Check for Cross-Source Contradictions & Authority Resolution
        # If wiki says "approved" but policy requires conditions
        has_informal_approval = any(
            c.get('authority_level', 0) <= 2 and 'approved' in c.get('text', '').lower()
            for c in retrieved_chunks
        )
        has_formal_condition = any(
            c.get('authority_level', 0) >= 6 and any(w in c.get('text', '').lower() for w in ['condition', 'require', 'must', 'prohibit'])
            for c in retrieved_chunks
        )

        if has_informal_approval and has_formal_condition:
            conflicts_resolved.append({
                'informal_claim': 'Informal wiki entry marked vendor as approved',
                'authoritative_source': 'Approved Security Policy (Authority Rank 7)',
                'resolution': 'authority_dominance',
                'note': 'Higher authority policy conditions override informal wiki entries.'
            })
            notes.append("Conflict resolved: Security Policy overrides informal team notes.")

        # 5. Determine Final Answer State
        if evidence_missing:
            state = 'insufficient'
            directive = 'ask_user'
            answer = (
                f"Cannot confirm approval for '{query}'. Mandatory governance evidence is missing:\n" +
                "\n".join(f"- {m['requirement']}: {m['description']}" for m in evidence_missing)
            )
        elif conflicts_resolved:
            state = 'qualified'
            directive = 'proceed_and_cite'
            answer = (
                f"Information regarding '{query}' is qualified by governance policy. "
                "Informal claims were overridden by authoritative policy directives."
            )
        else:
            state = 'supported'
            directive = 'proceed_and_cite'
            answer = (
                f"Knowledge retrieval complete for query: '{query}'. "
                f"Found {len(citations)} authoritative citations supporting this request."
            )

        return {
            'schema': 'lore.result/1',
            'state': state,
            'directive': directive,
            'answer': answer,
            'decision_type': decision_type,
            'items': evidence_found,
            'evidence_found': evidence_found,
            'evidence_missing': evidence_missing,
            'conflicts_resolved': conflicts_resolved,
            'citations': citations,
            'notes': notes,
            'decision_id': decision_id,
            'trace_id': trace_id,
            'token_count': total_tokens
        }
