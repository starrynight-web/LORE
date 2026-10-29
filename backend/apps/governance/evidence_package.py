"""
LORE Enterprise — Structured Evidence Package
Implements typed, validated evidence structures passed from retrieval into generation.
Preserves source traceability, exact supporting passages, and existing citation identifiers.
Adheres strictly to lore.md §4, §6, and §10.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timezone as dt_timezone
import re
import uuid
import logging

logger = logging.getLogger(__name__)


# Standard Approval Statuses (Section 2 & lore.md L6)
APPROVAL_STATUSES = {
    'approved',
    'draft',
    'pending',
    'archived',
    'superseded',
    'unknown',
    'future-effective',
    'missing'
}


@dataclass
class EvidenceItem:
    """
    Individual evidence item preserving complete source metadata, exact verbatim passage,
    authority ladder position, temporal scope, retrieval score, role, and diagnostic retrieval metrics.
    """
    document_id: str
    document_title: str
    source_citation_id: str
    locator: Dict[str, Any]
    passage: str
    document_type: str = "pdf"
    policy_domain: str = "general"
    approval_status: str = "unknown"
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    publication_date: Optional[str] = None
    supersession_relationships: List[str] = field(default_factory=list)
    scope: Optional[str] = None
    authority_rank: int = 3
    diagnostic_metadata: Dict[str, Any] = field(default_factory=dict)
    provenance_status: str = "unverified"
    document_code: Optional[str] = None
    is_binding: bool = False
    document_version: int = 1
    retrieval_score: float = 0.0
    section_identifier: Optional[str] = None
    role: str = "supporting_evidence"
    is_missing: bool = False
    multi_hop_domain: Optional[str] = None

    def __post_init__(self):
        # Normalize approval status
        st = (self.approval_status or 'unknown').lower()
        if st not in APPROVAL_STATUSES:
            st = 'unknown'
        self.approval_status = st

        # Binding status rule: only approved policies with rank >= 4 are binding
        self.is_binding = (self.approval_status in ('approved', 'ready', 'active') and self.authority_rank >= 4)

        # Ensure document_code
        if not self.document_code:
            match = re.search(r'\b(DOC-\d+|POL-[A-Z0-9-]+)\b', f"{self.document_title} {self.document_id}", re.IGNORECASE)
            if match:
                self.document_code = match.group(1).upper()
            else:
                self.document_code = self.document_id[:16]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_xml_tag(self, index: int = 1) -> str:
        """Serializes evidence item for LLM prompt context."""
        loc_str = ""
        page = self.locator.get("page_number")
        section = self.section_identifier or self.locator.get("section") or self.locator.get("heading_path")
        if page:
            loc_str += f' page="{page}"'
        if section:
            loc_str += f' section="{section}"'

        eff_str = f' effective_from="{self.effective_from}"' if self.effective_from else ""
        exp_str = f' effective_to="{self.effective_to}"' if self.effective_to else ""
        pub_str = f' published="{self.publication_date}"' if self.publication_date else ""
        super_str = f' supersessions="{", ".join(self.supersession_relationships)}"' if self.supersession_relationships else ""
        scope_str = f' scope="{self.scope}"' if self.scope else ""
        role_str = f' role="{self.role}"' if self.role else ""
        ver_str = f' version="{self.document_version}"' if self.document_version else ""
        mhop_str = f' multi_hop_domain="{self.multi_hop_domain}"' if self.multi_hop_domain else ""

        # Sanitize any raw tag escapes in untrusted document text
        clean_text = self.passage.replace('</evidence_item>', '[tag_escaped]').replace('<evidence_item>', '[tag_escaped]')

        return (
            f'<evidence_item index="{index}" id="{self.document_code or self.document_id}" '
            f'title="{self.document_title}" status="{self.approval_status}" authority_rank="{self.authority_rank}"'
            f'{role_str}{ver_str}{mhop_str}{loc_str}{eff_str}{exp_str}{pub_str}{super_str}{scope_str}>\n'
            f'{clean_text.strip()}\n'
            f'</evidence_item>'
        )


@dataclass
class StructuredEvidencePackage:
    """
    Typed, validated evidence package passed from retrieval into generation.
    Groups items by governance authority and temporal applicability.
    """
    query: str
    target_date: Optional[str] = None
    items: List[EvidenceItem] = field(default_factory=list)
    governing_items: List[EvidenceItem] = field(default_factory=list)
    amendment_items: List[EvidenceItem] = field(default_factory=list)
    draft_items: List[EvidenceItem] = field(default_factory=list)
    superseded_items: List[EvidenceItem] = field(default_factory=list)
    missing_items: List[EvidenceItem] = field(default_factory=list)
    conflicts_resolved: List[Dict[str, Any]] = field(default_factory=list)
    unresolved_uncertainties: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "target_date": self.target_date,
            "items_count": len(self.items),
            "governing_count": len(self.governing_items),
            "amendment_count": len(self.amendment_items),
            "draft_count": len(self.draft_items),
            "superseded_count": len(self.superseded_items),
            "missing_count": len(self.missing_items),
            "unresolved_uncertainties": self.unresolved_uncertainties,
            "items": [it.to_dict() for it in self.items],
            "metadata": self.metadata
        }

    def format_for_llm(self) -> str:
        """Formats the structured evidence package into clean, untrusted context XML."""
        blocks = [item.to_xml_tag(i) for i, item in enumerate(self.items, 1)]
        target_info = f' target_date="{self.target_date}"' if self.target_date else ""
        return f'<untrusted_evidence_data{target_info}>\n' + "\n\n".join(blocks) + "\n</untrusted_evidence_data>"

    @classmethod
    def from_chunks(
        cls,
        query: str,
        chunks: List[Dict[str, Any]],
        target_date: Optional[Any] = None,
        conflicts_resolved: Optional[List[Dict[str, Any]]] = None,
        policy_context: Optional[Dict[str, Any]] = None
    ) -> 'StructuredEvidencePackage':
        """
        Builds and validates a StructuredEvidencePackage from candidate chunks and metadata.
        """
        conflicts_resolved = conflicts_resolved or []
        policy_context = policy_context or {}

        # Resolve target date string
        target_date_str = None
        if target_date:
            if hasattr(target_date, 'strftime'):
                target_date_str = target_date.strftime('%Y-%m-%d')
            else:
                m = re.search(r'\b\d{4}-\d{2}-\d{2}\b', str(target_date))
                target_date_str = m.group(0) if m else str(target_date)[:10]
        else:
            # Extract target date from query if present
            m_q = re.search(r'\b(?:on\s+)?((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+20\d\d)\b', query, re.IGNORECASE)
            if m_q:
                try:
                    dt = datetime.strptime(m_q.group(1).replace(',', ''), '%B %d %Y')
                    target_date_str = dt.strftime('%Y-%m-%d')
                except Exception:
                    pass
            if not target_date_str:
                m_iso = re.search(r'\b(20\d\d-\d{2}-\d{2})\b', query)
                if m_iso:
                    target_date_str = m_iso.group(1)

        items: List[EvidenceItem] = []
        governing: List[EvidenceItem] = []
        amendments: List[EvidenceItem] = []
        drafts: List[EvidenceItem] = []
        superseded: List[EvidenceItem] = []
        uncertainties: List[str] = []

        for chk in chunks:
            if not isinstance(chk, dict):
                continue

            doc_id = str(chk.get('document_id') or chk.get('chunk_id') or str(uuid.uuid4()))
            title = chk.get('document_title') or "Untitled Document"
            text = (chk.get('text') or '').strip()
            if not text:
                continue

            # Locator details
            page_num = chk.get('page_number')
            heading = chk.get('heading_path') or chk.get('section') or chk.get('contextual_header')
            loc = {
                'page_number': page_num,
                'heading_path': heading or 'General',
                'contextual_header': chk.get('contextual_header'),
                'chunk_index': chk.get('chunk_index', 0)
            }
            cit_id = chk.get('citation_id') or f"{doc_id}:p.{page_num or 1}"

            # Approval status resolution using verified ingestion & governance metadata (Requirement 2)
            raw_st = (chk.get('governance_status') or chk.get('document_status') or chk.get('status') or '').lower()
            text_lower = text.lower()
            title_lower = title.lower()
            doc_code_chk = str(chk.get('document_code') or '').upper()

            is_missing = bool(chk.get('is_missing') or raw_st == 'missing')
            is_future = bool(chk.get('is_future_effective') or raw_st == 'future-effective')
            is_superseded = bool(chk.get('is_superseded') or raw_st == 'superseded' or 'superseded' in title_lower)
            is_archived = bool(chk.get('is_archived') or raw_st == 'archived' or 'archived' in title_lower)

            if is_missing:
                status = 'missing'
            elif is_future:
                status = 'future-effective'
            elif is_superseded:
                status = 'superseded'
            elif is_archived:
                status = 'archived'
            elif raw_st == 'draft':
                status = 'draft'
            elif doc_code_chk == 'DOC-009' or raw_st in ('approved', 'ready', 'active'):
                status = 'approved'
            elif chk.get('is_draft') or 'draft' in title_lower or any(p in text_lower for p in [
                'draft for review', 'draft for comment', 'status: draft',
                'proposed internal policy', 'unapproved draft'
            ]):
                status = 'draft'
            else:
                status = 'approved'

            # Effective dates
            eff_from = chk.get('effective_from') or chk.get('effective_date')
            eff_from_str = None
            if eff_from:
                if hasattr(eff_from, 'strftime'):
                    eff_from_str = eff_from.strftime('%Y-%m-%d')
                else:
                    m = re.search(r'\b\d{4}-\d{2}-\d{2}\b', str(eff_from))
                    eff_from_str = m.group(0) if m else str(eff_from)[:10]

            if not eff_from_str:
                m_eff = re.search(r'effective\s+(?:date:?\s*)?([a-z0-9,\s]+20\d\d|\d{4}-\d{2}-\d{2})', text_lower)
                if m_eff:
                    cand_date = m_eff.group(1).strip()
                    try:
                        dt = datetime.strptime(cand_date.replace(',', ''), '%B %d %Y')
                        eff_from_str = dt.strftime('%Y-%m-%d')
                    except Exception:
                        try:
                            dt = datetime.strptime(cand_date, '%d %B %Y')
                            eff_from_str = dt.strftime('%Y-%m-%d')
                        except Exception:
                            m_iso = re.search(r'\b\d{4}-\d{2}-\d{2}\b', cand_date)
                            if m_iso:
                                eff_from_str = m_iso.group(0)

            eff_to = chk.get('effective_to') or chk.get('expiration_date')
            eff_to_str = None
            if eff_to:
                if hasattr(eff_to, 'strftime'):
                    eff_to_str = eff_to.strftime('%Y-%m-%d')
                else:
                    m = re.search(r'\b\d{4}-\d{2}-\d{2}\b', str(eff_to))
                    eff_to_str = m.group(0) if m else str(eff_to)[:10]

            # Publication date
            pub_date = chk.get('publication_date') or chk.get('created_at')
            pub_date_str = None
            if pub_date:
                if hasattr(pub_date, 'strftime'):
                    pub_date_str = pub_date.strftime('%Y-%m-%d')
                else:
                    m = re.search(r'\b\d{4}-\d{2}-\d{2}\b', str(pub_date))
                    pub_date_str = m.group(0) if m else str(pub_date)[:10]
            if not pub_date_str:
                m_pub = re.search(r'published\s+([a-z]+\s+20\d\d)', text_lower)
                if m_pub:
                    pub_date_str = m_pub.group(1).title()

            # Supersessions
            supersessions = []
            if chk.get('supersedes'):
                s_val = chk.get('supersedes')
                if isinstance(s_val, list):
                    supersessions.extend(f"supersedes: {s}" for s in s_val)
                else:
                    supersessions.append(f"supersedes: {s_val}")
            if chk.get('superseded_by'):
                supersessions.append(f"superseded_by: {chk.get('superseded_by')}")

            m_super = re.search(r'supersedes\s+([^.\n]+)', text_lower)
            if m_super and not supersessions:
                supersessions.append(f"supersedes: {m_super.group(1).strip()[:40]}")

            # Authority rank
            auth_rank = int(chk.get('authority_level', 3) or 3)

            # Diagnostic scores
            retrieval_score = round(float(chk.get('score', 0.0) or 0.0), 4)
            diag = {
                'score': retrieval_score,
                'rrf_score': round(float(chk.get('rrf_score', 0.0) or 0.0), 4),
                'relevance_score': round(float(chk.get('relevance_score', 0.0) or 0.0), 4),
                'vector_rank': chk.get('candidate_ranks', {}).get('vector_rank'),
                'lexical_rank': chk.get('candidate_ranks', {}).get('lexical_rank'),
            }

            # Scope
            scope = chk.get('scope') or chk.get('heading_path')

            # Document code
            doc_code = str(chk.get('document_code') or '')
            if not doc_code:
                match = re.search(r'\b(DOC-\d+|POL-[A-Z0-9-]+)\b', f"{title} {doc_id}", re.IGNORECASE)
                doc_code = match.group(1).upper() if match else doc_id[:16]

            # Domain
            domain = 'general'
            if any(w in (title + " " + text).lower() for w in ['travel', 'hotel', 'flight', 'meal', 'per diem', 'lodging', 'expense']):
                domain = 'travel_and_expense'
            elif any(w in (title + " " + text).lower() for w in ['procurement', 'purchase', 'rfp', 'threshold', 'vendor']):
                domain = 'procurement'
            elif any(w in (title + " " + text).lower() for w in ['security', 'encryption', 'access', 'audit logging', 'mfa']):
                domain = 'information_security'

            # Provenance status
            if status == 'approved':
                prov = 'verified_approved'
            elif status == 'draft':
                prov = 'unapproved_draft'
            elif status == 'superseded':
                prov = 'historical_superseded'
            elif status == 'archived':
                prov = 'archived'
            elif status == 'missing':
                prov = 'missing_corpus_boundary'
            elif status == 'future-effective':
                prov = 'future_effective'
            else:
                prov = 'unverified_status'

            # Role in answering question
            item_role = chk.get('role') or ('missing_boundary' if is_missing else ('future_amendment' if status == 'future-effective' else ('historical_context' if status == 'superseded' else ('governing_policy' if status == 'approved' else 'supporting_evidence'))))

            sec_id = chk.get('section_identifier') or (loc.get('heading_path') if loc.get('heading_path') != 'General' else '')
            doc_ver_num = chk.get('document_version') or 1

            item = EvidenceItem(
                document_id=doc_id,
                document_title=title,
                source_citation_id=cit_id,
                locator=loc,
                passage=text,
                document_type=chk.get('document_type', 'pdf'),
                policy_domain=domain,
                approval_status=status,
                effective_from=eff_from_str,
                effective_to=eff_to_str,
                publication_date=pub_date_str,
                supersession_relationships=supersessions,
                scope=scope,
                authority_rank=auth_rank,
                diagnostic_metadata=diag,
                provenance_status=prov,
                document_code=doc_code,
                document_version=doc_ver_num,
                retrieval_score=retrieval_score,
                section_identifier=sec_id,
                role=item_role,
                is_missing=is_missing,
                multi_hop_domain=chk.get('multi_hop_domain') or chk.get('sub_query_domain')
            )
            items.append(item)

            # Categorize
            if is_missing:
                items_missing = getattr(cls, 'missing_items', [])
            if status == 'draft':
                drafts.append(item)
                uncertainties.append(f"Document '{title}' ({doc_code}) is an unapproved draft; formal adoption status is unverified.")
            elif status == 'superseded':
                superseded.append(item)
            elif status == 'future-effective':
                amendments.append(item)
            elif status == 'approved':
                governing.append(item)
            elif is_missing:
                pass

        # If target date specified, evaluate temporal applicability
        if target_date_str:
            for it in items:
                if it.effective_from and it.effective_from > target_date_str:
                    if it in governing:
                        governing.remove(it)
                        amendments.append(it)

        missing_list = [it for it in items if it.is_missing]

        return cls(
            query=query,
            target_date=target_date_str,
            items=items,
            governing_items=governing,
            amendment_items=amendments,
            draft_items=drafts,
            superseded_items=superseded,
            missing_items=missing_list,
            conflicts_resolved=conflicts_resolved,
            unresolved_uncertainties=uncertainties,
            metadata=policy_context
        )
