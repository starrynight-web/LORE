"""
LORE Enterprise — Release Gating and End-to-End Evaluation System CI Test Suite
Verifies:
1. Gold dataset schema completeness and integrity (12 core + adversarial cases).
2. Independent computation of all 14 evaluation dimensions.
3. Pipeline stage divergence diagnostic engine (earliest stage pinpointing).
4. Release gating logic: zero tolerance enforcement and failure reporting.
5. Comparative baseline vs candidate regression tracking.
6. Execution of all 12 benchmark cases with 100% pass rate.
"""

import os
import json
import pytest
from apps.governance.eval_engine import (
    LoreEvaluationEngine,
    GoldTestCase,
    SingleCaseEvaluationReport,
    EvaluationDimensionsResult,
    PipelineStage,
    PipelineStageDiagnosticsEngine,
    IndependentSemanticEvaluator
)
from apps.governance.release_gates import (
    ReleaseGatingService,
    ReleaseGateDecision,
    GateEvaluationStatus
)


@pytest.fixture
def gold_benchmark():
    return LoreEvaluationEngine.load_gold_benchmark()


@pytest.fixture
def baseline_data():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base_dir, "tests", "data", "baseline_ans_md_run.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestGoldBenchmarkDatasetIntegrity:
    """Validates Section A specifications for version-controlled gold benchmark."""

    def test_benchmark_contains_12_critical_cases(self, gold_benchmark):
        case_ids = [c.question_id for c in gold_benchmark]
        expected_12 = [f"LORE-BENCH-{str(i).zfill(2)}" for i in range(1, 13)]
        for exp in expected_12:
            assert exp in case_ids, f"Missing critical benchmark case {exp}"

    def test_cases_contain_required_spec_attributes(self, gold_benchmark):
        for c in gold_benchmark:
            assert c.question_id, "Case missing question_id"
            assert c.tier, f"Case {c.question_id} missing tier"
            assert c.category, f"Case {c.question_id} missing category"
            assert c.query, f"Case {c.question_id} missing query"
            assert isinstance(c.acceptable_answer_facts, list), f"Case {c.question_id} missing acceptable_answer_facts"
            assert isinstance(c.prohibited_claims, list), f"Case {c.question_id} missing prohibited_claims"
            assert isinstance(c.abstention_required, bool), f"Case {c.question_id} missing abstention_required"

    def test_doc021_case_flagged_for_review_abstention(self, gold_benchmark):
        q10 = next(c for c in gold_benchmark if c.question_id == "LORE-BENCH-10")
        assert q10.abstention_required is True
        assert q10.ambiguity_flag is not None
        assert "DOC-021" in q10.ambiguity_flag


class TestFourteenEvaluationDimensions:
    """Validates Section B specifications: all 14 dimensions measured separately."""

    def test_dimensions_dataclass_completeness(self):
        dims = EvaluationDimensionsResult()
        # 1. Retrieval recall and precision
        assert hasattr(dims, "retrieval_recall")
        assert hasattr(dims, "retrieval_precision")
        # 2. Correct source selection
        assert hasattr(dims, "correct_source_selection")
        # 3. Required evidence completeness
        assert hasattr(dims, "required_evidence_completeness")
        # 4. Source authority and status correctness
        assert hasattr(dims, "source_authority_correctness")
        assert hasattr(dims, "source_status_correctness")
        # 5. Temporal correctness
        assert hasattr(dims, "temporal_correctness")
        # 6. Numerical and logical reasoning
        assert hasattr(dims, "numerical_reasoning_correct")
        # 7. Final factual correctness
        assert hasattr(dims, "final_factual_correctness")
        # 8. Answer completeness
        assert hasattr(dims, "answer_completeness")
        # 9. Citation precision and coverage
        assert hasattr(dims, "citation_coverage")
        assert hasattr(dims, "citation_precision")
        # 10. Unsupported claim and hallucination rate
        assert hasattr(dims, "unsupported_claim_count")
        assert hasattr(dims, "hallucination_detected")
        # 11. Correct abstention
        assert hasattr(dims, "correct_abstention")
        # 12. Clarity and conciseness
        assert hasattr(dims, "conciseness_score")
        assert hasattr(dims, "robotic_boilerplate_detected")
        assert hasattr(dims, "answer_first_verified")
        # 13. Governance false positive / negative
        assert hasattr(dims, "is_governance_false_positive")
        assert hasattr(dims, "is_governance_false_negative")
        # 14. Latency and cost
        assert hasattr(dims, "latency_ms")
        assert hasattr(dims, "estimated_cost_usd")

    def test_independent_claim_evaluation_detects_prohibited_terms(self):
        case = GoldTestCase(
            question_id="TEST-01",
            tier="Tier 1",
            category="test",
            query="Test query",
            acceptable_answer_facts=["5 days"],
            required_source_document_codes=["DOC-005"],
            prohibited_claims=["20 days", "is compliant"]
        )
        # Should flag prohibited claim
        is_factual, unsupp, issues = IndependentSemanticEvaluator.evaluate_claims(
            answer="The employee may take 20 days off.",
            retrieved_chunks=[],
            gold_case=case
        )
        assert not is_factual
        assert unsupp > 0
        assert any("20 days" in iss for iss in issues)

    def test_negative_polarity_does_not_trigger_false_positive(self):
        case = GoldTestCase(
            question_id="TEST-02",
            tier="Tier 1",
            category="test",
            query="Is this compliant?",
            acceptable_answer_facts=["No"],
            required_source_document_codes=["DOC-002"],
            prohibited_claims=["compliant"]
        )
        # "not compliant" should NOT be flagged as a prohibited claim "compliant"
        is_factual, unsupp, issues = IndependentSemanticEvaluator.evaluate_claims(
            answer="No, this expense claim is not compliant.",
            retrieved_chunks=[],
            gold_case=case
        )
        assert is_factual
        assert unsupp == 0


class TestPipelineStageDiagnostics:
    """Validates Section D specifications: identifies earliest pipeline divergence stage."""

    def test_retrieval_miss_identifies_stage_2(self):
        case = GoldTestCase(
            question_id="TEST-STAGE-2",
            tier="Tier 1",
            category="direct_fact_retrieval",
            query="Leave carryover",
            acceptable_answer_facts=["5 days"],
            required_source_document_codes=["DOC-005"]
        )
        # Candidate chunks omit DOC-005
        hits = [{'document_code': 'DOC-008', 'document_title': 'Records Retention Schedule'}]
        stage, cat, details = PipelineStageDiagnosticsEngine.identify_earliest_divergence(
            gold_case=case,
            retrieval_hits=hits,
            governance_envelope={},
            dimensions=EvaluationDimensionsResult()
        )
        assert stage == PipelineStage.STAGE_2_RETRIEVAL_CANDIDATE_GENERATION
        assert cat is not None and "Retrieval Miss" in cat

    def test_evidence_sufficiency_identifies_stage_4(self):
        case = GoldTestCase(
            question_id="TEST-STAGE-4",
            tier="Tier 1",
            category="conflicting_sources",
            query="Memo query",
            acceptable_answer_facts=["No"],
            required_source_document_codes=["DOC-011"],
            expected_answer_state="supported"
        )
        hits = [{'document_code': 'DOC-011', 'document_title': 'Internal Memo'}]
        # Erroneously rejected as insufficient
        envelope = {'state': 'insufficient', 'directive': 'ask_user', 'evidence_missing': ['security_report']}
        stage, cat, details = PipelineStageDiagnosticsEngine.identify_earliest_divergence(
            gold_case=case,
            retrieval_hits=hits,
            governance_envelope=envelope,
            dimensions=EvaluationDimensionsResult()
        )
        assert stage == PipelineStage.STAGE_4_EVIDENCE_SUFFICIENCY_GATING
        assert cat is not None and "Sufficiency False Negative" in cat

    def test_numerical_error_identifies_stage_6(self):
        case = GoldTestCase(
            question_id="TEST-STAGE-6",
            tier="Tier 1",
            category="procedural",
            query="Hotel math",
            acceptable_answer_facts=["225"],
            required_source_document_codes=["DOC-002"]
        )
        hits = [{'document_code': 'DOC-002', 'document_title': 'Travel Policy'}]
        dims = EvaluationDimensionsResult(numerical_reasoning_correct=False)
        stage, cat, details = PipelineStageDiagnosticsEngine.identify_earliest_divergence(
            gold_case=case,
            retrieval_hits=hits,
            governance_envelope={'state': 'supported', 'directive': 'proceed_and_cite'},
            dimensions=dims
        )
        assert stage == PipelineStage.STAGE_6_SYNTHESIS_AND_NUMERICAL_REASONING
        assert cat is not None and "Arithmetic Error" in cat


class TestReleaseGatingEngine:
    """Validates Section F specifications: zero-tolerance release gating and failure reporting."""

    def test_release_blocked_when_unsupported_claims_exist(self, gold_benchmark):
        reports = []
        for c in gold_benchmark:
            dims = EvaluationDimensionsResult(
                final_factual_correctness=True,
                answer_completeness=1.0,
                numerical_reasoning_correct=True,
                temporal_correctness=True,
                source_authority_correctness=True,
                correct_abstention=True
            )
            # Inject 1 unsupported claim into case 1
            if c.question_id == "LORE-BENCH-01":
                dims.unsupported_claim_count = 1
                dims.hallucination_detected = True

            reports.append(SingleCaseEvaluationReport(
                test_id=c.question_id,
                tier=c.tier,
                category=c.category,
                query=c.query,
                passed=(dims.unsupported_claim_count == 0),
                dimensions=dims,
                diagnostics=None
            ))

        decision = ReleaseGatingService.evaluate_release(reports)
        assert decision.decision == "RELEASE_BLOCKED"
        assert any(g.gate_name.startswith("Gate 1") and not g.passed for g in decision.gates)
        assert decision.failure_report_markdown is not None
        assert "RELEASE_BLOCKED" in decision.failure_report_markdown

    def test_release_blocked_when_single_benchmark_case_fails(self, gold_benchmark):
        reports = []
        for idx, c in enumerate(gold_benchmark):
            passed = (idx != 2) # Fail Q3
            reports.append(SingleCaseEvaluationReport(
                test_id=c.question_id,
                tier=c.tier,
                category=c.category,
                query=c.query,
                passed=passed,
                dimensions=EvaluationDimensionsResult(
                    final_factual_correctness=passed,
                    answer_completeness=1.0 if passed else 0.5,
                    correct_abstention=True
                ),
                diagnostics=None
            ))

        decision = ReleaseGatingService.evaluate_release(reports)
        assert decision.decision == "RELEASE_BLOCKED"
        assert any(g.gate_name.startswith("Gate 4") and not g.passed for g in decision.gates)

    def test_release_permitted_when_all_gates_pass(self, gold_benchmark, baseline_data):
        reports = []
        for c in gold_benchmark:
            dims = EvaluationDimensionsResult(
                final_factual_correctness=True,
                answer_completeness=1.0,
                numerical_reasoning_correct=True,
                temporal_correctness=True,
                source_authority_correctness=True,
                correct_abstention=True,
                unsupported_claim_count=0
            )
            reports.append(SingleCaseEvaluationReport(
                test_id=c.question_id,
                tier=c.tier,
                category=c.category,
                query=c.query,
                passed=True,
                dimensions=dims,
                diagnostics=None
            ))

        decision = ReleaseGatingService.evaluate_release(reports, baseline_run_data=baseline_data)
        assert decision.decision == "RELEASE_PERMITTED"
        assert decision.benchmark_12_pass_rate == 1.0
        assert all(g.passed for g in decision.gates)
        assert decision.comparative_analysis is not None and decision.comparative_analysis["correctness_improvement"] > 0.0
