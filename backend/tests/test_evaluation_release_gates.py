"""
LORE Enterprise — CI Regression Tests for Evidence-Based Evaluation Release Gates
Validates that LORE passes all 9 release gates against the versioned golden evaluation dataset.
"""

import pytest
import os
import json
from apps.workspaces.models import Workspace
from tests.evaluation_suite_runner import (
    load_golden_dataset,
    setup_golden_dataset_fixture,
    evaluate_retrieval_quality,
    evaluate_groundedness_and_citations,
    evaluate_governance_correctness,
    evaluate_graphrag_contribution,
    evaluate_operational_performance,
    evaluate_tenant_isolation_and_egress,
    RELEASE_GATES
)


@pytest.mark.django_db(transaction=True)
class TestEvaluationReleaseGatesCI:
    """CI Regression suite asserting mandatory enterprise release gates pass empirically."""

    @pytest.fixture(autouse=True)
    def setup_suite(self):
        self.dataset = load_golden_dataset()
        self.fixtures = setup_golden_dataset_fixture()
        self.ws_primary = self.fixtures["ws_primary"]
        self.ws_foreign = self.fixtures["ws_foreign"]
        self.test_cases = self.dataset["test_cases"]

    def test_gate_01_zero_unauthorized_disclosure(self):
        """Mandatory zero-tolerance: Zero foreign tenant data may leak across workspace boundaries."""
        results = evaluate_tenant_isolation_and_egress(self.ws_primary, self.ws_foreign)
        assert results["foreign_tenant_leaks_count"] == 0
        assert results["tenant_isolation_leakage_rate"] == 0.0

    def test_gate_02_zero_unapproved_egress(self):
        """Mandatory zero-tolerance: In local_only mode, zero external calls or telemetric emissions occur."""
        results = evaluate_tenant_isolation_and_egress(self.ws_primary, self.ws_foreign)
        assert results["local_only_external_call_occurred"] is False
        assert results["local_only_airgap_preserved"] is True

    def test_gate_03_zero_secret_leakage(self):
        """Mandatory zero-tolerance: API keys, bearer tokens, and secrets must be 100% redacted."""
        results = evaluate_tenant_isolation_and_egress(self.ws_primary, self.ws_foreign)
        assert results["secrets_leaked"] is False
        assert results["secret_scrubbing_pass"] is True

    def test_gate_04_retrieval_recall_at_5(self):
        """Recall@5 must meet or exceed 85% threshold across golden test cases."""
        results = evaluate_retrieval_quality(self.ws_primary, self.test_cases)
        assert results["recall_at_5"] >= 0.85
        assert results["recall_at_3"] >= 0.80

    def test_gate_05_retrieval_mrr(self):
        """Mean Reciprocal Rank must meet or exceed 0.75."""
        results = evaluate_retrieval_quality(self.ws_primary, self.test_cases)
        assert results["mrr"] >= 0.75

    def test_gate_06_groundedness_fraction(self):
        """Answer claims must achieve >= 90% evidence groundedness with zero hallucination."""
        results = evaluate_groundedness_and_citations(self.ws_primary, self.test_cases)
        assert results["groundedness_mean"] >= 0.90

    def test_gate_07_citation_accuracy(self):
        """Citation accuracy must meet or exceed 95% against verified documents and pages."""
        results = evaluate_groundedness_and_citations(self.ws_primary, self.test_cases)
        assert results["citation_locator_accuracy"] >= 0.95
        assert results["valid_citations_count"] == results["total_citations_evaluated"]

    def test_gate_08_governance_accuracy(self):
        """Governance 9-layer engine must achieve >= 95% state and directive accuracy."""
        results = evaluate_governance_correctness(self.ws_primary, self.test_cases)
        assert results["state_accuracy"] >= 0.95
        assert results["directive_accuracy"] >= 0.95

    def test_gate_09_operational_p95_latency(self):
        """End-to-end P95 evaluation latency must remain under 250ms."""
        results = evaluate_operational_performance(self.ws_primary, self.test_cases)
        assert results["latency_percentiles_ms"]["p95"] <= 250.0
        assert results["failure_rate"] == 0.0

    def test_all_release_gates_pass_overall(self):
        """Comprehensive verification: all release gates evaluate to PASSED."""
        retrieval = evaluate_retrieval_quality(self.ws_primary, self.test_cases)
        groundedness = evaluate_groundedness_and_citations(self.ws_primary, self.test_cases)
        governance = evaluate_governance_correctness(self.ws_primary, self.test_cases)
        operational = evaluate_operational_performance(self.ws_primary, self.test_cases)
        tenant_iso = evaluate_tenant_isolation_and_egress(self.ws_primary, self.ws_foreign)

        metrics_map = {
            "tenant_isolation_leakage_rate": tenant_iso["tenant_isolation_leakage_rate"],
            "local_only_external_call_occurred": tenant_iso["local_only_external_call_occurred"],
            "secrets_leaked": tenant_iso["secrets_leaked"],
            "recall_at_5": retrieval["recall_at_5"],
            "mrr": retrieval["mrr"],
            "groundedness_mean": groundedness["groundedness_mean"],
            "citation_locator_accuracy": groundedness["citation_locator_accuracy"],
            "state_accuracy": governance["state_accuracy"],
            "p95": operational["latency_percentiles_ms"]["p95"]
        }

        failed_gates = []
        for gate in RELEASE_GATES:
            val = metrics_map.get(gate["metric_name"])
            th = gate["threshold_value"]
            if gate["threshold_type"] == "max":
                passed = (val <= th)
            else:
                passed = (val >= th)
            if not passed:
                failed_gates.append(gate["gate_id"])

        assert len(failed_gates) == 0, f"Failed release gates: {failed_gates}"
