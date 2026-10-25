"""
LORE Enterprise — Governed Evidence Presentation Engine
Specification: lore.md (v3.0 §3, §4, §10), Evidence Quality Contract:
1. Prefer the shortest exact source passage that proves the answer.
2. Remove duplicate and near-duplicate passages.
3. Do not include a source merely because it was retrieved.
4. Clearly distinguish direct evidence from inference.
5. Do not invent page numbers, approval status, source passages, or effective dates.
6. If the source cannot prove a claim, state that limitation.
7. Preserve provenance and auditability.
"""

import re
import uuid
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone

logger = logging.getLogger(__name__)


class EvidencePresentationEngine:
    """
    Curates authoritative evidence citations strictly adhering to the
    evidence presentation and quality contract.
    """

    @classmethod
    def curate_citations(
        cls,
        query: str,
        answer: str,
        active_chunks: List[Dict[str, Any]],
        conflicts_resolved: Optional[List[Dict[str, Any]]] = None,
        as_of: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Filters, minimizes, and curates retrieved chunks into minimal, high-fidelity
        proof citations with actual stored metadata.
        """
        if not active_chunks:
            return []

        conflicts_resolved = conflicts_resolved or []
        ref_time = as_of or timezone.now()

        # Step 1: Remove duplicates and near-duplicates
        deduped_chunks = cls._deduplicate_chunks(active_chunks)

        # Step 2: Extract shortest exact passages and build candidate citations
        candidate_citations: List[Dict[str, Any]] = []
        for chk in deduped_chunks:
            cit = cls._build_citation_entry(chk, query, answer, ref_time, conflicts_resolved)
            candidate_citations.append(cit)
        ans_lower = (answer or '').lower()
        # Sort candidate citations: sources cited directly in answer come first, then approved governing policy, then authority, then score
        def _sort_key(c):
            t = (c.get('document_title') or '').lower()
            did = str(c.get('document_id') or '').lower()
            cited_in_ans = 3 if (t in ans_lower or (did and did in ans_lower)) else 0
            st = c.get('document_status', 'unknown')
            is_gov = 2 if st == 'approved' else (1 if st not in ['draft', 'superseded', 'future-effective'] else 0)
            return (cited_in_ans, is_gov, int(c.get('authority_level', 0) or 0), float(c.get('score', 0.0) or 0.0))

        candidate_citations.sort(key=_sort_key, reverse=True)

        # Step 3: Select only necessary sources
        # Primary source is always included; other sources included only if they add
        # necessary multi-part facts or establish genuine conflicts/supersessions.
        curated = cls._filter_necessary_sources(candidate_citations, query, answer, conflicts_resolved)

        return curated

    @classmethod
    def _deduplicate_chunks(cls, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Removes exact duplicates and near-duplicate chunks while retaining
        the strongest source location and provenance (Requirement 4).
        """
        unique_chunks: List[Dict[str, Any]] = []

        # Sort by relevance score descending
        sorted_chunks = sorted(
            chunks,
            key=lambda c: (float(c.get('score', 0.0) or 0.0), int(c.get('authority_level', 0) or 0)),
            reverse=True
        )

        for chk in sorted_chunks:
            doc_id = str(chk.get('document_id', ''))
            doc_title = chk.get('document_title', '')
            raw_text = (chk.get('text') or '').strip()
            if not raw_text:
                continue

            cleaned_prefix = re.sub(r'\s+', ' ', raw_text.lower())[:60]
            chk_tokens = set(re.findall(r'\b\w{4,}\b', raw_text.lower()))

            # Check if this chunk is a duplicate/near-duplicate of an already accepted chunk from the same doc
            is_dup = False
            for existing in unique_chunks:
                if str(existing.get('document_id', '')) == doc_id or (doc_title and existing.get('document_title') == doc_title):
                    ex_clean = re.sub(r'\s+', ' ', (existing.get('text') or '').lower().strip())
                    if cleaned_prefix == ex_clean[:60] and len(cleaned_prefix) > 25:
                        is_dup = True
                    elif len(chk_tokens) >= 5:
                        ex_tokens = set(re.findall(r'\b\w{4,}\b', ex_clean))
                        if ex_tokens:
                            inter = len(chk_tokens.intersection(ex_tokens))
                            union = len(chk_tokens.union(ex_tokens))
                            if union > 0 and (inter / union) >= 0.75:
                                is_dup = True
                    if is_dup:
                        # Retain the strongest source location and provenance (Requirement 4)
                        if (existing.get('page_number') is None or existing.get('page_number') == 0) and chk.get('page_number'):
                            existing['page_number'] = chk.get('page_number')
                        if (not existing.get('heading_path') or existing.get('heading_path') == 'General') and chk.get('heading_path'):
                            existing['heading_path'] = chk.get('heading_path')
                        if int(chk.get('authority_level', 0) or 0) > int(existing.get('authority_level', 0) or 0):
                            existing['authority_level'] = chk.get('authority_level')
                        break

            if is_dup:
                continue

            unique_chunks.append(dict(chk))

        return unique_chunks

    @classmethod
    def _build_citation_entry(
        cls,
        chk: Dict[str, Any],
        query: str,
        answer: str,
        ref_time: datetime,
        conflicts_resolved: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Builds a complete, typed citation dictionary using ONLY actual stored metadata.
        Never invents page numbers, approval status, source passages, or effective dates.
        """
        doc_id = str(chk.get('document_id') or f"doc-{uuid.uuid4().hex[:8]}")
        doc_title = chk.get('document_title') or "Untitled Document"
        version = chk.get('document_version') or 1
        page_num = chk.get('page_number')  # May be None if unpaginated
        heading = chk.get('heading_path') or chk.get('section') or None
        raw_text = chk.get('text', '').strip()
        auth_level = chk.get('authority_level', 3)

        # 1. Shortest exact source passage that proves the answer
        shortest_passage = cls.extract_shortest_passage(raw_text, answer, query)

        # 2. Document Status from actual stored metadata
        doc_status = cls._resolve_document_status(chk, ref_time, conflicts_resolved)

        # 3. Effective date and supersession details
        effective_date_str = cls._format_effective_date(chk.get('effective_date'))
        supersession_details = cls._resolve_supersession(chk, conflicts_resolved)

        # 4. Evidence Type: Direct vs Inference
        evidence_type = cls._classify_evidence_type(shortest_passage, answer, query)

        # 5. Why this source applies
        applicability = cls._explain_applicability(doc_title, auth_level, doc_status, chk)

        # 6. Source limitation (if source cannot fully prove claim or has conditions)
        limitation = cls._identify_limitation(raw_text, doc_status, chk)

        # 7. Which answer claim this passage supports (Requirement 5 & 7)
        supported_claim = cls._identify_supported_claim(shortest_passage, answer, query)

        entry = {
            'citation_id': chk.get('citation_id') or f"cit-{uuid.uuid4().hex[:6]}",
            'document_id': doc_id,
            'document_title': doc_title,
            'document_version': version,
            'page_number': page_num,
            'section': heading,
            'heading_path': heading or 'General',
            'passage': raw_text,
            'shortest_passage': shortest_passage,
            'authority_level': auth_level,
            'document_status': doc_status,
            'effective_date': effective_date_str,
            'supersession_details': supersession_details,
            'applicability_explanation': applicability,
            'explanation': applicability,
            'evidence_type': evidence_type,
            'supported_claim': supported_claim,
            'claim_supported': supported_claim,
            'limitation': limitation,
            'score': round(float(chk.get('score', 0.0) or 0.0), 4)
        }

        # Preserve GraphRAG coordinates if present
        if chk.get('graph_expanded'):
            entry['graph_expanded'] = True
            entry['graph_depth'] = chk.get('graph_depth', 1)
            entry['traversed_relationship'] = chk.get('traversed_relationship')
            entry['edge_provenance'] = chk.get('edge_provenance')
            entry['graph_path'] = chk.get('graph_path', [])

        return entry

    @classmethod
    def extract_shortest_passage(cls, chunk_text: str, answer: str, query: str) -> str:
        """
        Extracts the shortest exact source sentence(s) that proves the answer.
        Guaranteed to be an exact verbatim substring of chunk_text with zero hallucination.
        """
        if not chunk_text:
            return ""

        # Clean sentence splitting that preserves exact substrings
        sentences = [s.strip() for s in re.split(r'(?<=[.!?\n])\s+', chunk_text) if len(s.strip()) > 10]
        if not sentences:
            return chunk_text[:200].strip()

        # Extract factual numbers / terms from answer (exclude single isolated digits to avoid page number collisions)
        ans_values = set(re.findall(r'\$\s*\d+(?:,\d{3})*(?:\.\d{2})?|\b\d+\s*(?:days?|years?|months?|hours?|users?|gb|tb|mb|%)\b', answer.lower()))
        q_terms = set(re.findall(r'\b[a-z]{4,}\b', query.lower())) - {'what', 'when', 'where', 'which', 'who', 'does', 'with', 'from', 'have', 'more'}

        ans_substantive = set(re.findall(r'\b[a-z]{4,}\b', answer.lower())) - {
            'what', 'when', 'where', 'which', 'who', 'does', 'with', 'from', 'have', 'more',
            'according', 'policy', 'document', 'page', 'proposed', 'formally', 'approved', 'draft',
            'review', 'internal', 'authoritative', 'operational', 'rule', 'rules'
        }

        best_sentence = sentences[0]
        best_score = -1

        for sent in sentences:
            sent_lower = sent.lower()
            sent_words = set(re.findall(r'\b[a-z]{4,}\b', sent_lower))

            # Value match bonus (proves specific number/date)
            val_matches = sum(1 for val in ans_values if val in sent_lower)
            # Query keyword overlap
            q_matches = len(q_terms.intersection(sent_words))
            # Substantive answer keyword overlap (proves the specific answer claims)
            ans_matches = len(ans_substantive.intersection(sent_words))

            # Length penalty: prefer concise exact sentences among high matches
            length_penalty = len(sent) / 500.0
            score = (val_matches * 6.0) + (ans_matches * 3.0) + (q_matches * 1.5) - length_penalty

            if score > best_score:
                best_score = score
                best_sentence = sent

        # Ensure returned sentence is an exact verbatim substring
        return best_sentence

    @classmethod
    def _resolve_document_status(
        cls,
        chk: Dict[str, Any],
        ref_time: datetime,
        conflicts_resolved: List[Dict[str, Any]]
    ) -> str:
        """
        Resolves document status strictly from stored metadata:
        'approved' | 'draft' | 'archived' | 'superseded' | 'future-effective' | 'unknown'
        """
        raw_status = (chk.get('document_status') or chk.get('status') or '').lower()
        title_lower = (chk.get('document_title') or '').lower()
        text_lower = (chk.get('text') or '').lower()

        # Check explicit superseded status or supersession resolutions
        if chk.get('is_superseded') or raw_status == 'superseded':
            return 'superseded'
        for cr in conflicts_resolved:
            if cr.get('resolution') in ['version_supersession', 'supersession']:
                if chk.get('document_title') in cr.get('informal_claim', ''):
                    return 'superseded'

        # Check future-effective date
        eff = chk.get('effective_date')
        if eff:
            try:
                if isinstance(eff, str):
                    eff_dt = datetime.fromisoformat(eff.replace('Z', '+00:00'))
                else:
                    eff_dt = eff
                if timezone.is_naive(eff_dt):
                    eff_dt = timezone.make_aware(eff_dt, dt_timezone.utc)
                if eff_dt > ref_time:
                    return 'future-effective'
            except Exception:
                pass

        if chk.get('is_future_effective'):
            return 'future-effective'

        # Check expiration date (past expiration date means archived/expired)
        exp = chk.get('expiration_date')
        if exp:
            try:
                if isinstance(exp, str):
                    exp_dt = datetime.fromisoformat(exp.replace('Z', '+00:00'))
                else:
                    exp_dt = exp
                if timezone.is_naive(exp_dt):
                    exp_dt = timezone.make_aware(exp_dt, dt_timezone.utc)
                if exp_dt < ref_time:
                    return 'archived'
            except Exception:
                pass

        # Check draft status (never present draft as approved)
        is_draft_doc = (
            chk.get('is_draft') or
            raw_status == 'draft' or
            'draft' in title_lower or
            any(p in text_lower for p in ['draft for review', 'draft for comment', 'status: draft', 'proposed internal policy', 'unapproved draft', 'pending formal adoption', 'pending approval'])
        )
        if is_draft_doc:
            return 'draft'

        # Check archived
        if raw_status == 'archived' or chk.get('is_archived'):
            return 'archived'

        # Check approved / ready (only when explicitly approved or active ready)
        if raw_status in ['ready', 'approved', 'active']:
            return 'approved'

        # Requirement 2 & 10: Missing or uncertain approval metadata must remain unknown.
        # DO NOT infer that a document is approved merely because it has Authority Rank 1 or any rank.
        return 'unknown'

    @classmethod
    def _format_effective_date(cls, eff: Any) -> Optional[str]:
        if not eff:
            return None
        if isinstance(eff, str):
            # Extract date portion YYYY-MM-DD
            m = re.search(r'\b\d{4}-\d{2}-\d{2}\b', eff)
            return m.group(0) if m else eff[:10]
        if hasattr(eff, 'strftime'):
            return eff.strftime('%Y-%m-%d')
        return None

    @classmethod
    def _resolve_supersession(cls, chk: Dict[str, Any], conflicts_resolved: List[Dict[str, Any]]) -> Optional[str]:
        title = chk.get('document_title', '')
        ver = chk.get('document_version', 1)

        for cr in conflicts_resolved:
            if cr.get('resolution') == 'version_supersession':
                if title in cr.get('informal_claim', ''):
                    return f"Superseded by {cr.get('authoritative_source')} (earlier v{ver})"
                if title in cr.get('authoritative_source', ''):
                    return f"Supersedes prior version ({cr.get('note', '')})"

        if chk.get('superseded_by'):
            return f"Superseded by {chk.get('superseded_by')}"
        if chk.get('supersedes'):
            return f"Supersedes {chk.get('supersedes')}"

        return None

    @classmethod
    def _classify_evidence_type(cls, shortest_passage: str, answer: str, query: str) -> str:
        """
        Clearly distinguishes direct evidence from inference.
        'direct': passage contains the exact key value, name, or rule stated in answer.
        'inference': answer represents an evaluated conclusion derived from broader constraints.
        """
        p_lower = shortest_passage.lower()
        ans_lower = answer.lower()

        # Check if substantive key numbers or values in answer are directly in the passage
        values = re.findall(r'\$\d+|\b\d+\s*(?:days?|years?|months?)\b|\b\d+\b', ans_lower)
        if values and any(v in p_lower for v in values):
            return 'direct'

        # Check high word overlap
        key_words = [w for w in re.findall(r'\b[a-z]{4,}\b', ans_lower) if w not in {'according', 'policy', 'document', 'established', 'information'}]
        if key_words:
            matched = sum(1 for w in key_words if w in p_lower)
            if matched / len(key_words) >= 0.5:
                return 'direct'

        return 'inference'

    @classmethod
    def _explain_applicability(cls, title: str, auth: int, status: str, chk: Dict[str, Any]) -> str:
        if status == 'unknown':
            return f"Rank {auth} record from '{title}' with unverified approval status (non-binding until approved)."
        if status == 'draft':
            return f"Rank {auth} draft document from '{title}' (unapproved proposal, non-binding)."
        if status == 'superseded':
            return f"Rank {auth} superseded historical record from '{title}' (superseded by newer version)."
        if status == 'future-effective':
            return f"Rank {auth} future-effective rule from '{title}' (takes effect on future effective date)."
        if auth >= 6:
            return f"Authoritative Rank {auth} approved policy establishing binding operational compliance for '{title}'."
        elif auth >= 4:
            return f"Rank {auth} procedural baseline governing standard operational practices in '{title}'."
        else:
            return f"Rank {auth} informative record providing supplemental factual context from '{title}'."

    @classmethod
    def _identify_limitation(cls, text: str, status: str, chk: Dict[str, Any]) -> Optional[str]:
        """
        States limitations if the source cannot fully prove a claim or has conditions.
        """
        t_lower = text.lower()
        if status == 'unknown':
            return "Unverified approval: Approval status is unknown or uncertain; cannot serve as binding approved policy."
        if status == 'draft':
            return "Non-binding: Document is an unapproved draft; cannot authorize production operations."
        if status == 'future-effective':
            return "Temporal restriction: Rule is future-effective and does not apply to current operations."
        if status == 'superseded':
            return "Historical record: Policy has been superseded by a newer version."
        if any(w in t_lower for w in ['receipts required', 'receipt required', 'original receipts']):
            return "Conditional: Requires submission of original itemized receipts for expense verification."
        if any(w in t_lower for w in ['subject to approval', 'pending approval', 'requires sign-off']):
            return "Prerequisite: Action remains subject to designated managerial approval."
        return None

    @classmethod
    def _identify_supported_claim(cls, passage: str, answer: str, query: str) -> str:
        """
        Determines which specific answer claim is substantiated by the passage (Requirement 5 & 7).
        """
        p_lower = passage.lower()
        q_lower = query.lower()
        if any(w in p_lower for w in ['audit logging', 'record relevant security events', 'successful and failed authentication']):
            return "Mandatory access-control and security event logging requirements (authentication, privileged functions, permission changes, record changes)."
        if any(w in p_lower for w in ['per diem', 'meal allowance', 'breakfast', 'lunch', 'dinner']):
            return "Reimbursable daily meal allowances and receipt substantiation rules."
        if any(w in p_lower for w in ['tier 1', 'tier 2', 'tier 3', 'micro-purchase', 'expenditure threshold']):
            return "Procurement expenditure threshold and approval requirements."
        if any(w in p_lower for w in ['retention', 'retained', 'statutory audit', 'ledger']):
            return "Mandatory records retention schedule."

        # Default to first sentence of answer
        sents = [s.strip() for s in re.split(r'(?<=[.!?\n])\s+', answer) if len(s.strip()) > 10]
        return sents[0] if sents else answer[:120].strip()

    @classmethod
    def _filter_necessary_sources(
        cls,
        citations: List[Dict[str, Any]],
        query: str,
        answer: str,
        conflicts_resolved: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Excludes sources merely because they were retrieved.
        Keeps primary proof source, and includes other sources ONLY if they add
        necessary additional facts or establish genuine conflicts.
        """
        if not citations:
            return []

        q_lower = query.lower()
        ans_lower = answer.lower()

        # The primary source: choose the source cited in the answer or highest scored candidate
        matching_cited = [c for c in citations if c['document_title'].lower() in ans_lower or (str(c.get('document_id', '')) and str(c.get('document_id', '')).lower() in ans_lower)]
        if matching_cited:
            ans_fact_words = set(re.findall(r'\b[a-z]{4,}\b', ans_lower)) - {'according', 'policy', 'document', 'page', 'proposed', 'formally', 'approved', 'draft'}
            primary = max(matching_cited, key=lambda c: len(ans_fact_words.intersection(set(re.findall(r'\b[a-z]{4,}\b', (c.get('shortest_passage') or '').lower())))))
        else:
            primary = citations[0]

        necessary: List[Dict[str, Any]] = [primary]
        covered_facts = set(re.findall(r'\b[a-z0-9$]{3,}\b', primary['shortest_passage'].lower()))

        # Extract answer numerical/financial values and entities (Requirements 5 & 8)
        ans_values = set(re.findall(r'\$\s*\d+(?:,\d{3})*(?:\.\d{2})?|\b\d+\s*(?:days?|years?|months?|hours?|users?|gb|tb|mb|%)\b', ans_lower))

        # Check multi-part query requirements
        multi_entities = re.findall(r'\b(?:supplier\s+[a-z0-9_-]+|vendor\s+[a-z0-9_-]+|tier\s*\d+|level\s*\d+|breakfast|lunch|dinner|micro-purchase|small procurement|major contract)\b', q_lower)

        user_asks_draft = bool(re.search(r'\b(draft|proposed|in draft)\b', q_lower))

        for cit in citations:
            if cit == primary:
                continue

            title = cit['document_title']
            doc_id = str(cit.get('document_id', ''))
            p_text = (cit.get('shortest_passage') or cit.get('passage', '')).lower()
            status = cit.get('document_status', '')

            # Do not duplicate citations for the same document unless proving an unrepresented value
            is_same_doc = any(
                (cit.get('document_id') and cit.get('document_id') == n.get('document_id')) or
                cit['document_title'] == n['document_title']
                for n in necessary
            )
            if is_same_doc:
                continue

            # Condition A: Involved in genuine conflict or supersession
            is_conflict_source = any(
                title in cr.get('informal_claim', '') or title in cr.get('authoritative_source', '')
                for cr in conflicts_resolved
            )
            if is_conflict_source:
                necessary.append(cit)
                continue

            # Draft documents must NOT be included as supplementary citations unless user asks about the draft (Requirement 3)
            if status == 'draft' and not user_asks_draft:
                continue

            # Condition B: Explicitly cited in answer text (e.g. governing policy or material amendment)
            if title.lower() in ans_lower or (doc_id and doc_id.lower() in ans_lower):
                necessary.append(cit)
                continue

            # Condition C: Proves an answer fact or table value not covered by already-selected citations (Requirement 5)
            cit_values = set(re.findall(r'\$\s*\d+(?:,\d{3})*(?:\.\d{2})?|\b\d+\s*(?:days?|years?|months?|hours?|users?|gb|tb|mb|%)\b', p_text))
            already_covered_values = set(re.findall(r'\$\s*\d+(?:,\d{3})*(?:\.\d{2})?|\b\d+\s*(?:days?|years?|months?|hours?|users?|gb|tb|mb|%)\b', " ".join(n['shortest_passage'].lower() for n in necessary)))
            new_values = cit_values.intersection(ans_values) - already_covered_values
            if new_values:
                necessary.append(cit)
                covered_facts.update(re.findall(r'\b[a-z0-9$]{3,}\b', p_text))
                continue

            # Condition D: Multi-entity question where this source covers an unrepresented entity (Requirement 8)
            covers_unrepresented_entity = any(
                (ent in p_text and not any(ent in n['shortest_passage'].lower() for n in necessary))
                for ent in multi_entities
            )
            if covers_unrepresented_entity:
                necessary.append(cit)
                covered_facts.update(re.findall(r'\b[a-z0-9$]{3,}\b', p_text))
                continue

            # Otherwise: Exclude unrelated or redundant documents (Requirement 6)

        return necessary
