"""
LORE Enterprise — Multi-Dimensional Regression Benchmark Test Suite
Runs and asserts all 12 required test groups (A to L) in pytest with deterministic
evaluations and detailed diagnostic assertion reporting.
"""

import pytest
from tests.regression_benchmark import BenchmarkRunner, build_benchmark_test_cases, BenchmarkEvaluator
from apps.governance.contract import GovernanceRequest
from apps.governance.layers import EnterpriseGovernanceEngine
from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument
from apps.governance.models import SourcePermission, AccessLevel
from django.contrib.auth.models import User
import uuid
import time


@pytest.fixture
def benchmark_fixture(db):
    org = Organization.objects.create(name="Bench Test Org", slug=f"bench-org-{uuid.uuid4().hex[:6]}")
    ws = Workspace.objects.create(organization=org, name="Bench Workspace", slug=f"bench-ws-{uuid.uuid4().hex[:6]}")
    user = User.objects.create_user(username=f"bench_user_{uuid.uuid4().hex[:6]}", password="password")
    return org, ws, user


def _run_single_case(case, org, ws, user):
    current_chunks = list(case.candidate_evidence)
    if case.test_id == "BENCH-K02":
        doc_pub = SourceDocument.objects.create(
            organization=org, workspace=ws, title="General IT Handbook",
            original_filename="handbook.pdf", mime_type="application/pdf",
            file_size=1024, file_hash=f"hash-pub-{uuid.uuid4().hex[:6]}",
            status="ready", authority_level=4
        )
        doc_res = SourceDocument.objects.create(
            organization=org, workspace=ws, title="Executive Compensation Confidential",
            original_filename="exec.pdf", mime_type="application/pdf",
            file_size=2048, file_hash=f"hash-res-{uuid.uuid4().hex[:6]}",
            status="ready", authority_level=7
        )
        SourcePermission.objects.create(
            document=doc_res,
            access_level=AccessLevel.RESTRICTED,
            allowed_roles=["workspace_admin"]
        )
        current_chunks[0]["document_id"] = str(doc_pub.id)
        current_chunks[1]["document_id"] = str(doc_res.id)

    req = GovernanceRequest(
        workspace=ws,
        organization=org,
        principal=user,
        user_role=case.user_role,
        query=case.query,
        candidate_evidence=current_chunks,
        as_of=case.as_of
    )
    t0 = time.time()
    envelope = EnterpriseGovernanceEngine.evaluate(req)
    latency_ms = (time.time() - t0) * 1000
    rec = BenchmarkEvaluator.evaluate_test_case(case, envelope, latency_ms)
    return rec


@pytest.mark.django_db
class TestLoreRegressionBenchmark:

    @pytest.fixture(autouse=True)
    def setup_cases(self):
        self.cases_by_id = {c.test_id: c for c in build_benchmark_test_cases()}

    def test_group_a_single_fact(self, benchmark_fixture):
        """Group A: Single fact inquiries."""
        org, ws, user = benchmark_fixture
        for cid in ["BENCH-A01", "BENCH-A02"]:
            case = self.cases_by_id[cid]
            rec = _run_single_case(case, org, ws, user)
            assert rec.status == "PASS", f"{cid} failed: {rec.diagnostics}"
            assert rec.all_requested_facts_present, f"{cid} missing facts: {case.expected_facts}"

    def test_group_b_multipart_answer(self, benchmark_fixture):
        """Group B: Multi-part answer inquiries."""
        org, ws, user = benchmark_fixture
        for cid in ["BENCH-B01", "BENCH-B02"]:
            case = self.cases_by_id[cid]
            rec = _run_single_case(case, org, ws, user)
            assert rec.status == "PASS", f"{cid} failed: {rec.diagnostics}"
            assert rec.all_requested_facts_present, f"{cid} missing facts: {case.expected_facts}"

    def test_group_c_policy_version_comparison(self, benchmark_fixture):
        """Group C: Policy version comparison inquiries."""
        org, ws, user = benchmark_fixture
        case = self.cases_by_id["BENCH-C01"]
        rec = _run_single_case(case, org, ws, user)
        assert rec.status == "PASS", f"BENCH-C01 failed: {rec.diagnostics}"
        assert rec.all_requested_facts_present

    def test_group_d_draft_versus_approved_status(self, benchmark_fixture):
        """Group D: Draft versus approved status."""
        org, ws, user = benchmark_fixture
        for cid in ["BENCH-D01", "BENCH-D02"]:
            case = self.cases_by_id[cid]
            rec = _run_single_case(case, org, ws, user)
            assert rec.status == "PASS", f"{cid} failed: {rec.diagnostics}"

    def test_group_e_current_versus_future_effective_policy(self, benchmark_fixture):
        """Group E: Current versus future-effective policy."""
        org, ws, user = benchmark_fixture
        case = self.cases_by_id["BENCH-E01"]
        rec = _run_single_case(case, org, ws, user)
        assert rec.status == "PASS", f"BENCH-E01 failed: {rec.diagnostics}"
        assert "$50" in rec.actual_answer
        assert "2027" in rec.actual_answer or "70" in rec.actual_answer

    def test_group_f_historical_and_archived_policy(self, benchmark_fixture):
        """Group F: Historical and archived policy."""
        org, ws, user = benchmark_fixture
        for cid in ["BENCH-F01", "BENCH-F02"]:
            case = self.cases_by_id[cid]
            rec = _run_single_case(case, org, ws, user)
            assert rec.status == "PASS", f"{cid} failed: {rec.diagnostics}"

    def test_group_g_threshold_boundaries(self, benchmark_fixture):
        """Group G: Threshold boundaries."""
        org, ws, user = benchmark_fixture
        for cid in ["BENCH-G01", "BENCH-G02"]:
            case = self.cases_by_id[cid]
            rec = _run_single_case(case, org, ws, user)
            assert rec.status == "PASS", f"{cid} failed: {rec.diagnostics}"

    def test_group_h_supplier_comparison(self, benchmark_fixture):
        """Group H: Supplier comparison."""
        org, ws, user = benchmark_fixture
        for cid in ["BENCH-H01", "BENCH-H02"]:
            case = self.cases_by_id[cid]
            rec = _run_single_case(case, org, ws, user)
            assert rec.status == "PASS", f"{cid} failed: {rec.diagnostics}"

    def test_group_i_missing_evidence(self, benchmark_fixture):
        """Group I: Missing evidence."""
        org, ws, user = benchmark_fixture
        case = self.cases_by_id["BENCH-I01"]
        rec = _run_single_case(case, org, ws, user)
        assert rec.status == "PASS", f"BENCH-I01 failed: {rec.diagnostics}"
        assert rec.answer_state == "insufficient"
        assert rec.governance_decision == "ask_user"

    def test_group_j_genuine_source_conflict(self, benchmark_fixture):
        """Group J: Genuine source conflict."""
        org, ws, user = benchmark_fixture
        case = self.cases_by_id["BENCH-J01"]
        rec = _run_single_case(case, org, ws, user)
        assert rec.status == "PASS", f"BENCH-J01 failed: {rec.diagnostics}"
        assert rec.answer_state == "conflicting"
        assert rec.governance_decision == "ask_user"

    def test_group_k_access_control_denial(self, benchmark_fixture):
        """Group K: Access-control denial."""
        org, ws, user = benchmark_fixture
        for cid in ["BENCH-K01", "BENCH-K02"]:
            case = self.cases_by_id[cid]
            rec = _run_single_case(case, org, ws, user)
            assert rec.status == "PASS", f"{cid} failed: {rec.diagnostics}"
            if cid == "BENCH-K01":
                assert rec.answer_state == "no_knowledge"
            elif cid == "BENCH-K02":
                assert "$500,000" not in rec.actual_answer

    def test_group_l_expandable_details_and_proof(self, benchmark_fixture):
        """Group L: Expandable details and proof."""
        org, ws, user = benchmark_fixture
        case = self.cases_by_id["BENCH-L01"]
        rec = _run_single_case(case, org, ws, user)
        assert rec.status == "PASS", f"BENCH-L01 failed: {rec.diagnostics}"
        assert rec.citations_directly_support
        assert not rec.evidence_duplicated_or_irrelevant
