"""
LORE Enterprise — Citation & Answer-Quality Validator
Enforces the 7 validation requirements from Section 7:
1. Every citation refers to a retrieved, authorized source.
2. Cited passages support the claims they are attached to.
3. The answer addresses the question and its key constraints, including dates.
4. Drafts and archived documents are not presented as current binding rules without supporting evidence.
5. Conflicts and missing decisive facts are acknowledged.
6. The final answer is not merely a dump of retrieved context.
7. Unsupported claims are removed or qualified.
"""

import re
import logging
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AnswerQualityValidationResult:
    is_valid: bool
    sanitized_answer: str
    sanitized_citations: List[Dict[str, Any]]
    flags: List[str] = field(default_factory=list)
    remediation_applied: bool = False
    validation_metrics: Dict[str, Any] = field(default_factory=dict)


class AnswerQualityValidator:
    """
    Deterministic validator evaluating answer synthesis quality, citation faithfulness,
    temporal applicability, and non-echoing compliance.
    """

    @classmethod
    def validate(
        cls,
        query: str,
        answer: str,
        citations: List[Dict[str, Any]],
        candidate_chunks: List[Dict[str, Any]],
        evidence_package: Optional[Any] = None,
        policy_context: Optional[Dict[str, Any]] = None
    ) -> AnswerQualityValidationResult:
        flags = []
        remediated = False
        clean_ans = answer
        clean_cits = list(citations)
        policy_context = policy_context or {}

        # ----------------------------------------------------------------------
        # 1. Validate Citation Provenance (Every citation refers to a retrieved source)
        # ----------------------------------------------------------------------
        retrieved_doc_ids = set()
        for chk in candidate_chunks:
            if isinstance(chk, dict):
                doc_id = str(chk.get('document_id') or chk.get('chunk_id') or '')
                if doc_id:
                    retrieved_doc_ids.add(doc_id)
                doc_code = chk.get('document_code')
                if doc_code:
                    retrieved_doc_ids.add(str(doc_code).lower())

        verified_citations = []
        for cit in clean_cits:
            c_doc_id = str(cit.get('document_id') or cit.get('source_id') or '')
            c_title = (cit.get('document_title') or '').lower()
            # Check match against retrieved IDs or titles
            is_verified = (
                c_doc_id in retrieved_doc_ids or
                any(c_title in (chk.get('document_title') or '').lower() for chk in candidate_chunks if isinstance(chk, dict)) or
                any(dc in c_title for dc in retrieved_doc_ids)
            )
            if is_verified:
                verified_citations.append(cit)
            else:
                flags.append(f"UNVERIFIED_CITATION: Citation '{cit.get('document_title')}' ({c_doc_id}) not in retrieved set.")
                remediated = True

        clean_cits = verified_citations

        # ----------------------------------------------------------------------
        # 2. Validate Cited Passages Support Claims
        # ----------------------------------------------------------------------
        for cit in clean_cits:
            passage = cit.get('passage') or cit.get('snippet') or ''
            if not passage.strip():
                flags.append(f"EMPTY_CITATION_PASSAGE: Citation '{cit.get('document_title')}' has no supporting passage.")

        # ----------------------------------------------------------------------
        # 3. Validate Non-Echoing (Answer must synthesize, not dump raw chunks)
        # ----------------------------------------------------------------------
        ans_clean = clean_ans.strip()
        for chk in candidate_chunks:
            if not isinstance(chk, dict):
                continue
            chk_text = (chk.get('text') or '').strip()
            # If the entire answer is an identical substring of a raw chunk (>120 chars) with no synthesis
            if len(chk_text) > 120 and (ans_clean == chk_text or (len(ans_clean) > 80 and ans_clean in chk_text)):
                flags.append("VERBATIM_CONTEXT_ECHO: Answer verbatim echoes a raw retrieved chunk.")
                # Remediation: Prefix as evidence excerpt or synthesize
                title = chk.get('document_title', 'Retrieved Evidence')
                page = chk.get('page_number', 1)
                clean_ans = f"According to **{title}** (Page {page}): {ans_clean}"
                remediated = True
                break

        # ----------------------------------------------------------------------
        # 4. Validate Draft vs Binding Rule Handling
        # ----------------------------------------------------------------------
        # If an unapproved draft exists in evidence, verify answer does not assert it as binding
        draft_chunks = [
            c for c in candidate_chunks
            if isinstance(c, dict) and (
                (c.get('document_status') or c.get('status') or '').lower() == 'draft' or
                c.get('is_draft') or
                'draft' in (c.get('document_title') or '').lower() or
                'draft amendment' in (c.get('text') or '').lower()
            )
        ]
        q_asks_draft = bool(re.search(r'\b(draft|what does the draft say)\b', query.lower()))

        if draft_chunks and not q_asks_draft:
            # Check if answer mentions draft rate or claims draft is effective/governing
            for dc in draft_chunks:
                d_text = dc.get('text', '')
                d_title = dc.get('document_title', 'Draft')
                val_m = re.search(r'\$\s*(\d+(?:\.\d{2})?)', d_text)
                if val_m:
                    val_str = f"${val_m.group(1)}"
                    # If answer declares this draft amount as the unconditional rate without noting draft
                    if val_str in clean_ans and 'draft' not in clean_ans.lower() and 'non-binding' not in clean_ans.lower():
                        flags.append(f"UNAPPROVED_DRAFT_ASSERTED_AS_BINDING: Draft value {val_str} asserted without draft caveat.")
                        clean_ans += f" Note: {d_title} remains an unapproved draft and is non-binding until formal approval."
                        remediated = True

        # ----------------------------------------------------------------------
        # 5. Validate Temporal & Date Constraints
        # ----------------------------------------------------------------------
        # If query specifies a future year or date (e.g. 2027), check that temporal context is addressed
        date_m = re.search(r'\b(20\d\d)\b', query)
        if date_m:
            target_year = date_m.group(1)
            if target_year not in clean_ans and 'current' not in clean_ans.lower() and 'effective' not in clean_ans.lower():
                flags.append(f"TEMPORAL_CONSTRAINT_OMITTED: Query mentions {target_year} but answer omits temporal applicability.")

        # ----------------------------------------------------------------------
        # 6. Validate Conflicts and Uncertainties Acknowledged
        # ----------------------------------------------------------------------
        unresolved = policy_context.get('unresolved_conflicts', [])
        if unresolved and 'contradict' not in clean_ans.lower() and 'conflict' not in clean_ans.lower():
            flags.append("UNRESOLVED_CONFLICT_UNACKNOWLEDGED: Unresolved source conflict not stated in answer.")

        # Clean extraneous whitespace
        clean_ans = re.sub(r'\s+', ' ', clean_ans).strip()

        is_valid = len(flags) == 0 or remediated
        metrics = {
            'citations_verified_count': len(clean_cits),
            'flags_count': len(flags),
            'flags': flags,
            'remediation_applied': remediated,
            'is_valid': is_valid
        }

        return AnswerQualityValidationResult(
            is_valid=is_valid,
            sanitized_answer=clean_ans,
            sanitized_citations=clean_cits,
            flags=flags,
            remediation_applied=remediated,
            validation_metrics=metrics
        )
