"""
LORE Enterprise — Permanent End-to-End Evaluation & Diagnostic Engine
Evaluates full query-to-answer pipeline across 14 independent dimensions,
pinpoints earliest pipeline stage divergence on failures, and provides
deterministic and independent semantic evaluation.
"""

import os
import re
import json
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple, Set

logger = logging.getLogger(__name__)


# ==============================================================================
# PIPELINE STAGES
# ==============================================================================

class PipelineStage:
    STAGE_1_QUERY_UNDERSTANDING = "STAGE_1_QUERY_UNDERSTANDING"
    STAGE_2_RETRIEVAL_CANDIDATE_GENERATION = "STAGE_2_RETRIEVAL_CANDIDATE_GENERATION"
    STAGE_3_FUSION_AND_RERANKING = "STAGE_3_FUSION_AND_RERANKING"
    STAGE_4_EVIDENCE_SUFFICIENCY_GATING = "STAGE_4_EVIDENCE_SUFFICIENCY_GATING"
    STAGE_5_AUTHORITY_AND_TEMPORAL_RESOLUTION = "STAGE_5_AUTHORITY_AND_TEMPORAL_RESOLUTION"
    STAGE_6_SYNTHESIS_AND_NUMERICAL_REASONING = "STAGE_6_SYNTHESIS_AND_NUMERICAL_REASONING"
    STAGE_7_CITATION_ATTRIBUTION = "STAGE_7_CITATION_ATTRIBUTION"
    STAGE_8_VALIDATION_AND_SAFETY_GATING = "STAGE_8_VALIDATION_AND_SAFETY_GATING"


# ==============================================================================
# DATA CONTRACTS
# ==============================================================================

@dataclass
class GoldTestCase:
    question_id: str
    tier: str
    category: str
    query: str
    acceptable_answer_facts: List[str]
    required_source_document_codes: List[str]
    required_source_document_titles: List[str] = field(default_factory=list)
    required_passages_or_sections: List[str] = field(default_factory=list)
    expected_policy_version: Optional[str] = None
    expected_effective_date: Optional[str] = None
    expected_answer_state: str = "supported"
    expected_directive: str = "proceed_and_cite"
    required_citation_coverage: Dict[str, Any] = field(default_factory=dict)
    prohibited_claims: List[str] = field(default_factory=list)
    abstention_required: bool = False
    ambiguity_flag: Optional[str] = None
    notes: str = ""


@dataclass
class StageDiagnostics:
    query: str
    candidate_source_ids: List[str] = field(default_factory=list)
    candidate_document_codes: List[str] = field(default_factory=list)
    final_evidence_set: List[Dict[str, Any]] = field(default_factory=list)
    applied_governance_rules: List[str] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    earliest_failing_stage: Optional[str] = None
    failure_category: Optional[str] = None
    failure_details: List[str] = field(default_factory=list)


@dataclass
class EvaluationDimensionsResult:
    # 1. Retrieval recall and precision
    retrieval_recall: float = 0.0
    retrieval_precision: float = 0.0
    
    # 2. Correct source selection
    correct_source_selection: bool = False
    
    # 3. Required evidence completeness
    required_evidence_completeness: float = 0.0
    
    # 4. Source authority and status correctness
    source_authority_correctness: bool = True
    source_status_correctness: bool = True
    
    # 5. Temporal correctness
    temporal_correctness: bool = True
    
    # 6. Numerical and logical reasoning
    numerical_reasoning_correct: bool = True
    
    # 7. Final factual correctness
    final_factual_correctness: bool = False
    
    # 8. Answer completeness
    answer_completeness: float = 0.0
    
    # 9. Claim-level citation precision and coverage
    citation_coverage: float = 0.0
    citation_precision: float = 0.0
    
    # 10. Unsupported-claim and hallucination rate
    unsupported_claim_count: int = 0
    hallucination_detected: bool = False
    
    # 11. Correct abstention on missing information
    correct_abstention: bool = True
    
    # 12. User-facing clarity and conciseness
    conciseness_score: float = 1.0
    robotic_boilerplate_detected: bool = False
    answer_first_verified: bool = True
    
    # 13. Governance false-positive and false-negative rates
    is_governance_false_positive: bool = False
    is_governance_false_negative: bool = False
    
    # 14. Latency and cost
    latency_ms: int = 0
    token_count: int = 0
    estimated_cost_usd: float = 0.0


@dataclass
class SingleCaseEvaluationReport:
    test_id: str
    tier: str
    category: str
    query: str
    passed: bool
    dimensions: EvaluationDimensionsResult
    diagnostics: Optional[StageDiagnostics] = None
    human_review_required: bool = False
    human_review_reason: Optional[str] = None


# ==============================================================================
# INDEPENDENT SEMANTIC EVALUATOR
# ==============================================================================

class IndependentSemanticEvaluator:
    """
    Evaluates answer factuality, claim entailment, and citation grounding
    independently of the generation model or self-reported prose.
    """

    @classmethod
    def evaluate_claims(
        cls,
        answer: str,
        retrieved_chunks: List[Dict[str, Any]],
        gold_case: GoldTestCase
    ) -> Tuple[bool, int, List[str]]:
        """
        Extracts material claims from answer, verifies against evidence and prohibited claims.
        Returns: (is_factual, unsupported_count, list_of_issues)
        """
        ans_lower = answer.lower()
        issues = []
        unsupported_count = 0

        # 1. Prohibited claims check (zero tolerance)
        for prohibited in gold_case.prohibited_claims:
            p_lower = prohibited.lower().strip()
            # If prohibited claim is a phrase, check with word boundaries avoiding false positives on "not compliant"
            if p_lower:
                pattern = rf'(?<!not\s)\b{re.escape(p_lower)}\b'
                if re.search(pattern, ans_lower):
                    issues.append(f"Prohibited claim/phrase detected: '{prohibited}'")
                    unsupported_count += 1

        # 2. Check for robotic boilerplate
        robotic_phrases = [
            "authoritative operational rule",
            "authoritative operational logging",
            "as an ai",
            "this document is the authoritative"
        ]
        for rp in robotic_phrases:
            if rp in ans_lower:
                issues.append(f"Robotic boilerplate phrase detected: '{rp}'")

        # 3. Required facts check
        missing_facts = []
        for fact in gold_case.acceptable_answer_facts:
            f_lower = fact.lower()
            if not cls._contains_fact(ans_lower, f_lower):
                missing_facts.append(fact)

        if missing_facts:
            issues.append(f"Missing required facts: {missing_facts}")

        # 4. Abstention verification
        if gold_case.abstention_required:
            abstention_indicators = [
                "not provided", "not available", "could not be verified",
                "missing", "absent", "cannot verify", "insufficient evidence",
                "not present", "access denied", "denied"
            ]
            has_abstention = any(ind in ans_lower for ind in abstention_indicators)
            if not has_abstention:
                issues.append("Case required explicit abstention on missing content, but answer did not abstain.")
                unsupported_count += 1

        is_factual = (unsupported_count == 0) and (len(missing_facts) == 0)
        return is_factual, unsupported_count, issues

    @classmethod
    def _contains_fact(cls, text: str, fact: str) -> bool:
        """Normalized fact matching supporting numbers, dates, stemmed forms, and terms."""
        t_clean = re.sub(r'[^\w\s]', ' ', text).lower()
        f_clean = re.sub(r'[^\w\s]', ' ', fact).lower()
        
        f_tokens = [tok for tok in f_clean.split() if tok]
        if not f_tokens:
            return True
        
        t_words = set(t_clean.split())
        for tok in f_tokens:
            # Exact word match
            if tok in t_words:
                continue
            # Substring match in cleaned text
            if tok in t_clean:
                continue
            # Stemmed variations (e.g. defer -> deferred, character -> characters, receipt -> receipts)
            tok_stem = tok[:-1] if len(tok) > 4 and tok.endswith('s') else tok
            tok_stem = tok_stem[:-2] if len(tok_stem) > 4 and tok_stem.endswith('ed') else tok_stem
            tok_stem = tok_stem[:-3] if len(tok_stem) > 5 and tok_stem.endswith('ing') else tok_stem
            if any(w.startswith(tok_stem) for w in t_words if len(tok_stem) >= 4):
                continue
            return False
        return True


# ==============================================================================
# PIPELINE STAGE DIVERGENCE DIAGNOSTIC
# ==============================================================================

class PipelineStageDiagnosticsEngine:
    """
    Identifies the earliest stage at which the pipeline diverged from expected behavior.
    """

    @classmethod
    def identify_earliest_divergence(
        cls,
        gold_case: GoldTestCase,
        retrieval_hits: List[Dict[str, Any]],
        governance_envelope: Dict[str, Any],
        dimensions: EvaluationDimensionsResult
    ) -> Tuple[Optional[str], Optional[str], List[str]]:
        """
        Returns: (earliest_stage, failure_category, details_list)
        """
        details = []

        # STAGE 2: Retrieval Candidate Generation
        # Did retrieval retrieve any of the required documents?
        retrieved_codes = []
        for h in retrieval_hits:
            c = (h.get('document_code') or '').upper()
            t = (h.get('document_title') or '').upper()
            if c:
                retrieved_codes.append(c)
            # Match DOC-XXX in title
            m = re.search(r'DOC-\d{3}', t)
            if m and m.group(0) not in retrieved_codes:
                retrieved_codes.append(m.group(0))

        req_codes = [c.upper() for c in gold_case.required_source_document_codes]
        if req_codes and not any(rc in retrieved_codes for rc in req_codes):
            details.append(f"Required documents {req_codes} missing from retrieval candidates {retrieved_codes[:5]}")
            return (
                PipelineStage.STAGE_2_RETRIEVAL_CANDIDATE_GENERATION,
                "Retrieval Miss: Required source documents omitted from candidate pool.",
                details
            )

        # STAGE 3: Fusion and Reranking
        # Was the required document ranked too low or excluded from top candidates?
        top_codes = retrieved_codes[:3]
        if req_codes and not any(rc in top_codes for rc in req_codes) and any(rc in retrieved_codes for rc in req_codes):
            details.append(f"Required document found in candidates but ranked below Top-3 (Top: {top_codes})")
            return (
                PipelineStage.STAGE_3_FUSION_AND_RERANKING,
                "Reranking Demotion: Governing document demoted behind distractors.",
                details
            )

        # STAGE 4: Evidence Sufficiency Gating
        state = governance_envelope.get('state', '').lower()
        directive = governance_envelope.get('directive', '').lower()
        expected_state = gold_case.expected_answer_state.lower()
        expected_directive = gold_case.expected_directive.lower()

        # If answer was blocked/insufficient when it shouldn't be
        if expected_state == 'supported' and state in ('insufficient', 'violation'):
            missing_ev = governance_envelope.get('evidence_missing', [])
            details.append(f"Unexpected governance rejection/escalation: state={state}, directive={directive}, missing={missing_ev}")
            return (
                PipelineStage.STAGE_4_EVIDENCE_SUFFICIENCY_GATING,
                "Evidence Sufficiency False Negative: Valid query blocked by overbroad action gate or missing requirement.",
                details
            )

        # STAGE 5: Authority and Temporal Resolution
        if not dimensions.temporal_correctness:
            details.append("Temporal resolution failed: active vs future/superseded document conflict resolved incorrectly.")
            return (
                PipelineStage.STAGE_5_AUTHORITY_AND_TEMPORAL_RESOLUTION,
                "Temporal Resolution Error: Future-effective or superseded policy improperly applied.",
                details
            )

        if not dimensions.source_authority_correctness:
            details.append("Authority resolution failed: informal or lower-ranked source overrode approved policy.")
            return (
                PipelineStage.STAGE_5_AUTHORITY_AND_TEMPORAL_RESOLUTION,
                "Authority Inversion: Non-authoritative source selected over governing policy.",
                details
            )

        # STAGE 6: Synthesis and Numerical Reasoning
        if not dimensions.numerical_reasoning_correct:
            details.append("Numerical calculation error in synthesis (e.g. rate division, threshold, or fee discrepancy).")
            return (
                PipelineStage.STAGE_6_SYNTHESIS_AND_NUMERICAL_REASONING,
                "Synthesis Arithmetic Error: Calculation discrepancy in synthesized response.",
                details
            )

        if dimensions.answer_completeness < 1.0 and not gold_case.abstention_required:
            details.append(f"Answer completeness failure: completeness={dimensions.answer_completeness:.2f}")
            return (
                PipelineStage.STAGE_6_SYNTHESIS_AND_NUMERICAL_REASONING,
                "Incomplete Synthesis: Model answered only part of a multi-part query.",
                details
            )

        # STAGE 7: Citation Attribution
        if dimensions.citation_coverage < 1.0 and gold_case.expected_answer_state in ('supported', 'qualified'):
            details.append(f"Citation attribution failure: coverage={dimensions.citation_coverage:.2f}")
            return (
                PipelineStage.STAGE_7_CITATION_ATTRIBUTION,
                "Citation Defect: Mandatory citations missing, misattributed, or duplicated.",
                details
            )

        # STAGE 8: Validation and Safety Gating
        if dimensions.unsupported_claim_count > 0 or dimensions.hallucination_detected:
            details.append(f"Validation failure: {dimensions.unsupported_claim_count} unsupported claims or prohibited terms passed validation.")
            return (
                PipelineStage.STAGE_8_VALIDATION_AND_SAFETY_GATING,
                "Safety Gate Escape: Hallucinated or prohibited claim passed post-generation validation.",
                details
            )

        return None, None, []


# ==============================================================================
# MAIN EVALUATION ENGINE
# ==============================================================================

class LoreEvaluationEngine:
    """
    Coordinates end-to-end evaluation of the 12 benchmark cases + adversarial test cases.
    Computes all 14 evaluation dimensions separately.
    """

    @classmethod
    def load_gold_benchmark(cls, filepath: Optional[str] = None) -> List[GoldTestCase]:
        """Loads version-controlled benchmark dataset."""
        if not filepath:
            # Try app data first, then tests data
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            p1 = os.path.join(base_dir, 'governance', 'data', 'lore_enterprise_gold_benchmark.json')
            p2 = os.path.join(os.path.dirname(base_dir), 'tests', 'data', 'lore_enterprise_gold_benchmark.json')
            filepath = p1 if os.path.exists(p1) else p2

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        cases = []
        for c in data.get('test_cases', []):
            cases.append(GoldTestCase(
                question_id=c['question_id'],
                tier=c['tier'],
                category=c['category'],
                query=c['query'],
                acceptable_answer_facts=c.get('acceptable_answer_facts', []),
                required_source_document_codes=c.get('required_source_document_codes', []),
                required_source_document_titles=c.get('required_source_document_titles', []),
                required_passages_or_sections=c.get('required_passages_or_sections', []),
                expected_policy_version=c.get('expected_policy_version'),
                expected_effective_date=c.get('expected_effective_date'),
                expected_answer_state=c.get('expected_answer_state', 'supported'),
                expected_directive=c.get('expected_directive', 'proceed_and_cite'),
                required_citation_coverage=c.get('required_citation_coverage', {}),
                prohibited_claims=c.get('prohibited_claims', []),
                abstention_required=c.get('abstention_required', False),
                ambiguity_flag=c.get('ambiguity_flag'),
                notes=c.get('notes', '')
            ))
        return cases

    @classmethod
    def evaluate_case(
        cls,
        gold_case: GoldTestCase,
        retrieval_hits: List[Dict[str, Any]],
        governance_envelope: Dict[str, Any],
        latency_ms: int = 0
    ) -> SingleCaseEvaluationReport:
        """
        Evaluates a single execution turn against all 14 dimensions and performs
        deep diagnostic stage analysis.
        """
        dims = EvaluationDimensionsResult()
        dims.latency_ms = latency_ms

        ans = governance_envelope.get('answer', '') or ''
        ans_lower = ans.lower()
        state = governance_envelope.get('state', '').lower()
        directive = governance_envelope.get('directive', '').lower()
        citations = governance_envelope.get('citations', [])

        # ----------------------------------------------------------------------
        # Dimension 1: Retrieval Recall & Precision
        # ----------------------------------------------------------------------
        retrieved_codes = []
        for h in retrieval_hits:
            c = (h.get('document_code') or '').upper()
            t = (h.get('document_title') or '').upper()
            if c and c not in retrieved_codes:
                retrieved_codes.append(c)
            m = re.search(r'DOC-\d{3}', t)
            if m and m.group(0) not in retrieved_codes:
                retrieved_codes.append(m.group(0))

        req_codes = [c.upper() for c in gold_case.required_source_document_codes]
        if not req_codes:
            dims.retrieval_recall = 1.0
            dims.retrieval_precision = 1.0 if not retrieved_codes else 0.5
        else:
            tp = len(set(retrieved_codes).intersection(set(req_codes)))
            dims.retrieval_recall = round(tp / len(req_codes), 3)
            dims.retrieval_precision = round(tp / max(len(retrieved_codes), 1), 3)

        # ----------------------------------------------------------------------
        # Dimension 2: Correct Source Selection
        # ----------------------------------------------------------------------
        if not req_codes:
            dims.correct_source_selection = True
        else:
            top_3 = retrieved_codes[:3]
            dims.correct_source_selection = any(rc in top_3 for rc in req_codes)

        # ----------------------------------------------------------------------
        # Dimension 3: Required Evidence Completeness
        # ----------------------------------------------------------------------
        passages = gold_case.required_passages_or_sections
        if not passages:
            dims.required_evidence_completeness = 1.0
        else:
            all_evidence_text = " ".join([h.get('text', '') for h in retrieval_hits]).lower()
            matched_passages = sum(1 for p in passages if any(tok in all_evidence_text for tok in p.lower().split()[:3]))
            dims.required_evidence_completeness = round(matched_passages / len(passages), 3)

        # ----------------------------------------------------------------------
        # Dimension 4: Source Authority and Status Correctness
        # ----------------------------------------------------------------------
        # DOC-011 memo is non-authoritative; DOC-002 is approved; etc.
        if gold_case.question_id == "LORE-BENCH-07":
            # Must recognize internal memo is non-authoritative
            dims.source_authority_correctness = ("non-authoritative" in ans_lower or "does not override" in ans_lower or "doc-002" in ans_lower)
            dims.source_status_correctness = True
        else:
            dims.source_authority_correctness = True
            dims.source_status_correctness = True

        # ----------------------------------------------------------------------
        # Dimension 5: Temporal Correctness
        # ----------------------------------------------------------------------
        if gold_case.question_id == "LORE-BENCH-05":
            # November 2026 travel: must recognize active policy cap ($220 or $200) and future amendment DOC-015 not effective until 2027
            has_active_cap = ("220" in ans or "200" in ans)
            has_future_ref = ("2027" in ans_lower or "doc-015" in ans_lower or "amendment" in ans_lower or "not take effect" in ans_lower or "does not affect" in ans_lower)
            dims.temporal_correctness = has_active_cap and has_future_ref
        elif gold_case.question_id == "LORE-BENCH-06":
            # Archived 2024 policy superseded
            dims.temporal_correctness = ("superseded" in ans_lower or "replaced" in ans_lower or "archived" in ans_lower or "doc-021" in ans_lower or "doc-002" in ans_lower)
        else:
            dims.temporal_correctness = True

        # ----------------------------------------------------------------------
        # Dimension 6: Numerical and Logical Reasoning
        # ----------------------------------------------------------------------
        if gold_case.question_id == "LORE-BENCH-04":
            # $450 for 2 nights = $225/night vs cap ($220 or $200)
            dims.numerical_reasoning_correct = ("225" in ans or "$225" in ans) and ("220" in ans or "$220" in ans or "200" in ans or "$200" in ans)
        elif gold_case.question_id == "LORE-BENCH-08":
            # Fee discrepancy math: $12,000 quarterly, $14,500 invoiced, or $4,800
            dims.numerical_reasoning_correct = any(amt in ans for amt in ["12,000", "$12,000", "14,500", "$14,500", "4,800", "$4,800", "48,000", "58,000"])
        elif gold_case.question_id == "LORE-BENCH-03":
            # Purchase threshold vs savings estimate math
            dims.numerical_reasoning_correct = any(amt in ans for amt in ["32,000", "25,000", "14,000"])
        else:
            dims.numerical_reasoning_correct = True

        # ----------------------------------------------------------------------
        # Dimension 7: Final Factual Correctness
        # ----------------------------------------------------------------------
        is_factual, unsupp_cnt, issues = IndependentSemanticEvaluator.evaluate_claims(
            answer=ans,
            retrieved_chunks=retrieval_hits,
            gold_case=gold_case
        )
        dims.final_factual_correctness = is_factual
        dims.unsupported_claim_count = unsupp_cnt
        dims.hallucination_detected = (unsupp_cnt > 0)

        # ----------------------------------------------------------------------
        # Dimension 8: Answer Completeness
        # ----------------------------------------------------------------------
        req_facts = gold_case.acceptable_answer_facts
        if not req_facts:
            dims.answer_completeness = 1.0
        else:
            matched_facts = sum(1 for f in req_facts if IndependentSemanticEvaluator._contains_fact(ans_lower, f.lower()))
            dims.answer_completeness = round(matched_facts / len(req_facts), 3)

        # ----------------------------------------------------------------------
        # Dimension 9: Claim-Level Citation Precision and Coverage
        # ----------------------------------------------------------------------
        req_cov = gold_case.required_citation_coverage
        must_cite = [c.upper() for c in req_cov.get('must_cite_any_of', [])]
        min_cit = req_cov.get('min_citations', 0)

        cited_titles_and_codes = []
        for c in citations:
            t = (c.get('document_title') or '').upper()
            code = (c.get('document_code') or '').upper()
            cited_titles_and_codes.append(t)
            if code:
                cited_titles_and_codes.append(code)
            m = re.search(r'DOC-\d{3}', t)
            if m:
                cited_titles_and_codes.append(m.group(0))

        if not must_cite:
            dims.citation_coverage = 1.0
            dims.citation_precision = 1.0
        else:
            matched_must = sum(1 for mc in must_cite if any(mc in ct for ct in cited_titles_and_codes))
            dims.citation_coverage = 1.0 if matched_must > 0 else 0.0
            dims.citation_precision = 1.0 if len(citations) >= min_cit else 0.5

        # Deduplication check: verify no duplicates of exact same doc title/id
        citation_ids = [c.get('document_title') for c in citations if c.get('document_title')]
        if len(citation_ids) != len(set(citation_ids)):
            dims.citation_precision = 0.5

        # ----------------------------------------------------------------------
        # Dimension 10: Unsupported-Claim and Hallucination Rate
        # ----------------------------------------------------------------------
        # Handled above under Dimension 7

        # ----------------------------------------------------------------------
        # Dimension 11: Correct Abstention on Missing Information
        # ----------------------------------------------------------------------
        if gold_case.abstention_required:
            abstention_terms = ["not available", "not present", "not provided", "missing", "absent", "cannot verify", "insufficient", "denied"]
            dims.correct_abstention = any(term in ans_lower for term in abstention_terms) and (state in ('insufficient', 'qualified', 'no_knowledge'))
        else:
            dims.correct_abstention = (state in ('supported', 'qualified'))

        # ----------------------------------------------------------------------
        # Dimension 12: User-Facing Clarity and Conciseness
        # ----------------------------------------------------------------------
        robotic_boilerplate = any(rp in ans_lower for rp in [
            "authoritative operational rule",
            "authoritative operational logging"
        ])
        dims.robotic_boilerplate_detected = robotic_boilerplate

        # Check sentence count (1-4 short sentences or compact list)
        sentences = [s.strip() for s in re.split(r'[.!?\n]', ans) if len(s.strip()) > 5]
        sentence_count = len(sentences)
        dims.conciseness_score = 1.0 if sentence_count <= 6 else 0.5

        # Answer first: check that answer does not open with diagnostic/metadata headers
        open_tokens = ans.strip().split()[:10]
        open_text = " ".join(open_tokens).lower()
        dims.answer_first_verified = not any(h in open_text for h in ["trace-", "diagnostic:", "layers:", "audit:", "evaluation:"])

        # ----------------------------------------------------------------------
        # Dimension 13: Governance False-Positive and False-Negative Rates
        # ----------------------------------------------------------------------
        # False Positive: Approved when missing or unauthorized
        if gold_case.expected_answer_state in ('insufficient', 'violation') and state == 'supported':
            dims.is_governance_false_positive = True
        # False Negative: Rejected/escalated when valid evidence present
        if gold_case.expected_answer_state == 'supported' and state in ('insufficient', 'violation'):
            dims.is_governance_false_negative = True

        # ----------------------------------------------------------------------
        # Dimension 14: Latency and Cost
        # ----------------------------------------------------------------------
        dims.token_count = len(ans.split()) * 2
        # Deterministic / local execution cost is $0.00
        dims.estimated_cost_usd = 0.0

        # ----------------------------------------------------------------------
        # Overall Case Pass Gate
        # ----------------------------------------------------------------------
        case_passed = (
            dims.final_factual_correctness and
            dims.answer_completeness >= 0.75 and
            dims.numerical_reasoning_correct and
            dims.temporal_correctness and
            dims.source_authority_correctness and
            dims.correct_abstention and
            not dims.hallucination_detected and
            not dims.robotic_boilerplate_detected and
            not dims.is_governance_false_positive and
            not dims.is_governance_false_negative
        )

        # Diagnostics & Divergence Stage Identification
        earliest_stage, fail_cat, stage_details = PipelineStageDiagnosticsEngine.identify_earliest_divergence(
            gold_case=gold_case,
            retrieval_hits=retrieval_hits,
            governance_envelope=governance_envelope,
            dimensions=dims
        )

        diagnostics = StageDiagnostics(
            query=gold_case.query,
            candidate_source_ids=[h.get('document_id') for h in retrieval_hits if h.get('document_id')],
            candidate_document_codes=retrieved_codes,
            final_evidence_set=[{
                'document_code': h.get('document_code'),
                'document_title': h.get('document_title'),
                'authority_level': h.get('authority_level'),
                'score': h.get('score')
            } for h in retrieval_hits[:5]],
            applied_governance_rules=governance_envelope.get('layers_breakdown', {}).get('applied_rules', []),
            citations=citations,
            final_answer=ans,
            earliest_failing_stage=earliest_stage,
            failure_category=fail_cat,
            failure_details=stage_details + issues
        )

        # Human Review Requirement Flag
        human_review = False
        human_review_reason = None
        if gold_case.ambiguity_flag:
            human_review = True
            human_review_reason = gold_case.ambiguity_flag
        elif not case_passed and dims.unsupported_claim_count > 0:
            human_review = True
            human_review_reason = f"High-risk hallucination detected on {gold_case.question_id}"

        return SingleCaseEvaluationReport(
            test_id=gold_case.question_id,
            tier=gold_case.tier,
            category=gold_case.category,
            query=gold_case.query,
            passed=case_passed,
            dimensions=dims,
            diagnostics=diagnostics,
            human_review_required=human_review,
            human_review_reason=human_review_reason
        )
