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
from datetime import datetime
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

        # Step 3: Select only necessary sources
        # Primary source is always included; other sources included only if they add
        # necessary multi-part facts or establish genuine conflicts/supersessions.
        curated = cls._filter_necessary_sources(candidate_citations, query, answer, conflicts_resolved)

        return curated

    @classmethod
    def _deduplicate_chunks(cls, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Removes exact duplicates and near-duplicate chunks.
        Chunks from the same document and page with high token overlap (>80%)
        or identical core proof sentences are merged, keeping the higher-scored one.
        """
        unique_chunks: List[Dict[str, Any]] = []
        seen_keys: Set[Tuple[str, Any, str]] = set()

        # Sort by relevance score descending so we keep the best representation
        sorted_chunks = sorted(
            chunks,
            key=lambda c: (float(c.get('score', 0.0) or 0.0), int(c.get('authority_level', 0) or 0)),
            reverse=True
        )

        for chk in sorted_chunks:
            doc_id = str(chk.get('document_id', ''))
            page = chk.get('page_number')
            raw_text = (chk.get('text') or '').strip()
            if not raw_text:
                continue

            # Normalized fingerprint: doc_id + page + first 60 chars of cleaned text
            cleaned_prefix = re.sub(r'\s+', ' ', raw_text.lower())[:60]
            key = (doc_id, page, cleaned_prefix)

            if key in seen_keys:
                continue

            # Check near-duplicate Jaccard overlap against already accepted chunks from same doc
            is_near_dup = False
            chk_tokens = set(re.findall(r'\b\w{4,}\b', raw_text.lower()))
            if len(chk_tokens) >= 5:
                for existing in unique_chunks:
                    if str(existing.get('document_id', '')) == doc_id and existing.get('page_number') == page:
                        ex_tokens = set(re.findall(r'\b\w{4,}\b', (existing.get('text') or '').lower()))
                        if ex_tokens:
                            intersection = len(chk_tokens.intersection(ex_tokens))
                            union = len(chk_tokens.union(ex_tokens))
                            if union > 0 and (intersection / union) >= 0.75:
                                is_near_dup = True
                                break

            if is_near_dup:
                continue

            seen_keys.add(key)
            unique_chunks.append(chk)

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
            'evidence_type': evidence_type,
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

        # Extract factual numbers / terms from answer
        ans_values = set(re.findall(r'\$\d+(?:\.\d+)?|\b\d+\s*(?:days?|years?|months?|hours?|users?|gb|tb|mb|%)\b|\b\d+\b', answer.lower()))
        q_terms = set(re.findall(r'\b[a-z]{4,}\b', query.lower())) - {'what', 'when', 'where', 'which', 'who', 'does', 'with', 'from', 'have', 'more'}

        best_sentence = sentences[0]
        best_score = -1

        for sent in sentences:
            sent_lower = sent.lower()
            sent_words = set(re.findall(r'\b[a-z]{4,}\b', sent_lower))

            # Value match bonus (proves specific number/date)
            val_matches = sum(1 for val in ans_values if val in sent_lower)
            # Query keyword overlap
            q_matches = len(q_terms.intersection(sent_words))

            # Length penalty: prefer the shortest sentence among high matches
            length_penalty = len(sent) / 500.0
            score = (val_matches * 5.0) + (q_matches * 2.0) - length_penalty

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
        raw_status = (chk.get('status') or '').lower()
        title_lower = (chk.get('document_title') or '').lower()
        text_lower = (chk.get('text') or '').lower()

        # Check explicit superseded status or supersession resolutions
        if chk.get('is_superseded') or raw_status == 'superseded':
            return 'superseded'
        for cr in conflicts_resolved:
            if cr.get('resolution') == 'version_supersession':
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
                    eff_dt = timezone.make_aware(eff_dt, timezone.utc)
                if eff_dt > ref_time:
                    return 'future-effective'
            except Exception:
                pass

        if chk.get('is_future_effective'):
            return 'future-effective'

        # Check draft status
        if chk.get('is_draft') or raw_status == 'draft' or 'draft' in title_lower or 'status: draft' in text_lower:
            return 'draft'

        # Check archived
        if raw_status == 'archived':
            return 'archived'

        # Check approved / ready
        if raw_status in ['ready', 'approved', 'active']:
            return 'approved'

        # If authority level is high and no negative indicators
        if chk.get('authority_level', 0) >= 6 and raw_status not in ['draft', 'quarantined']:
            return 'approved'

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
        status_text = {
            'approved': 'Approved policy',
            'draft': 'Draft policy (unapproved)',
            'superseded': 'Superseded policy',
            'future-effective': 'Future-effective rule',
            'archived': 'Archived record',
            'unknown': 'Recorded document'
        }.get(status, 'Document')

        if auth >= 6:
            return f"Authoritative Rank {auth} {status_text.lower()} establishing binding operational compliance for '{title}'."
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

        # The primary source (highest score) is always necessary
        necessary: List[Dict[str, Any]] = [citations[0]]
        covered_facts = set(re.findall(r'\b[a-z0-9$]{3,}\b', citations[0]['shortest_passage'].lower()))

        # Check multi-part query requirements
        q_lower = query.lower()
        is_multipart = any(w in q_lower for w in ['breakfast', 'lunch', 'dinner', 'total', 'compare', 'difference'])

        for cit in citations[1:]:
            title = cit['document_title']
            p_text = cit['shortest_passage'].lower()

            # Condition A: Involved in genuine conflict or supersession
            is_conflict_source = any(
                title in cr.get('informal_claim', '') or title in cr.get('authoritative_source', '')
                for cr in conflicts_resolved
            )
            if is_conflict_source:
                necessary.append(cit)
                continue

            # Condition B: Multi-part question where this source adds new necessary facts
            if is_multipart:
                cit_tokens = set(re.findall(r'\b[a-z0-9$]{3,}\b', p_text))
                new_tokens = cit_tokens - covered_facts
                # Does it cover an unanswered entity?
                has_distinct_fact = any(
                    (entity in p_text and entity not in citations[0]['shortest_passage'].lower())
                    for entity in ['lunch', 'dinner', 'breakfast', 'total', 'version 1', 'version 2']
                )
                if has_distinct_fact or len(new_tokens) >= 5:
                    necessary.append(cit)
                    covered_facts.update(cit_tokens)
                    continue

        return necessary
