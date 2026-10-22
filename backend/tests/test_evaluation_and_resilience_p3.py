import time
import pytest
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.sources.models import SourceDocument
from apps.knowledge.models import DocumentChunk
from apps.decisions.models import DecisionRecord
from apps.audit.models import AuditEvent
from apps.governance.evaluation import GovernanceEvaluationHarness
from apps.governance.baseline_comparator import BaselineComparator
from apps.governance.telemetry import TelemetryService
from apps.retrieval.resilience import (
    CircuitBreaker, CircuitState, CircuitBreakerOpenException,
    resilient_vector_search, qdrant_circuit_breaker
)

@pytest.mark.django_db
class TestEvaluationAndResilienceP3:

    @pytest.fixture(autouse=True)
    def setup_data(self):
        self.org = Organization.objects.create(name='P3 Eval Org', slug='p3-eval-org')
        self.user = User.objects.create_user(username='eval_auditor', password='pass')
        OrganizationMembership.objects.create(organization=self.org, user=self.user, role='owner')

        self.ws = Workspace.objects.create(organization=self.org, name='Eval Workspace', slug='eval-ws')
        WorkspaceMembership.objects.create(workspace=self.ws, user=self.user, role='workspace_admin')

        # Reset process-wide circuit breaker
        qdrant_circuit_breaker.reset()

    def test_governance_benchmark_evaluation_harness(self):
        """
        Verify that the evaluation harness runs all 10 benchmark cases (E01-E10)
        and satisfies enterprise quality gates (Zero Hallucination, 100% Correct Abstention).
        """
        harness = GovernanceEvaluationHarness()
        summary = harness.run_benchmark()

        assert summary['total_cases'] == 10
        assert summary['passed_cases'] == 10
        assert summary['precision'] >= 0.95
        assert summary['hallucination_rate'] == 0.00
        assert summary['abstention_accuracy'] == 1.00
        assert summary['citation_validity'] >= 0.98
        assert summary['contract_compliance'] == 1.00
        assert summary['benchmark_passed'] is True
        assert len(summary['results']) == 10

    def test_baseline_comparator_3_arms(self):
        """
        Verify the 3-arm baseline comparator demonstrates LORE superiority over
        Pure Search and Standard RAG.
        """
        comparator = BaselineComparator()
        report = comparator.run_comparison()

        arms = report['arms']
        assert 'pure_search' in arms
        assert 'standard_rag' in arms
        assert 'lore_enterprise' in arms

        # Standard RAG has significant hallucination and low abstention accuracy
        assert arms['standard_rag']['hallucination_rate'] > 0.20
        assert arms['standard_rag']['correct_abstention_rate'] < 0.50

        # LORE has zero hallucination and 100% correct abstention
        assert arms['lore_enterprise']['hallucination_rate'] == 0.00
        assert arms['lore_enterprise']['correct_abstention_rate'] == 1.00
        assert arms['lore_enterprise']['contract_compliance_rate'] == 1.00

        # Matrix has capability rows
        assert len(report['comparison_matrix']) >= 5

    def test_circuit_breaker_lifecycle(self):
        """
        Verify CircuitBreaker state transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED,
        and fallback execution when open.
        """
        breaker = CircuitBreaker("test_service", failure_threshold=2, recovery_timeout=0.1)
        assert breaker.state == CircuitState.CLOSED

        def failing_op():
            raise ConnectionError("Upstream timeout")

        def fallback_op():
            return "fallback_value"

        # 1. First failure: remains CLOSED
        try:
            breaker.call(failing_op)
        except ConnectionError:
            pass
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 1

        # 2. Second failure: trips to OPEN
        try:
            breaker.call(failing_op)
        except ConnectionError:
            pass
        assert breaker.state == CircuitState.OPEN
        assert breaker.failure_count == 2

        # 3. Call while OPEN: without fallback raises CircuitBreakerOpenException
        with pytest.raises(CircuitBreakerOpenException):
            breaker.call(failing_op)

        # 4. Call while OPEN: with fallback executes fallback
        fallback_res = breaker.call(failing_op, fallback=fallback_op)
        assert fallback_res == "fallback_value"

        # 5. Wait for recovery timeout: transitions to HALF_OPEN
        time.sleep(0.12)
        assert breaker.state == CircuitState.OPEN  # state updates on next call

        # Call in HALF_OPEN with successful operation resets to CLOSED
        success_res = breaker.call(lambda: "healthy_result")
        assert success_res == "healthy_result"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_resilient_vector_search_fallback(self):
        """
        Verify that resilient_vector_search falls back to PostgreSQL lexical chunks
        when the vector store fails, tagging results with fallback_mode='lexical_only'.
        """
        # Create published document and chunk in DB
        doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.ws,
            owner=self.user,
            title='Operational Policy',
            original_filename='ops.md',
            mime_type='text/markdown',
            file_size=100,
            file_hash='ops-hash',
            file_obj=SimpleUploadedFile('ops.md', b"All data centers must enforce dual power feeds."),
            document_type='txt',
            authority_level=6,
            status='ready'
        )

        chunk = DocumentChunk.objects.create(
            organization=self.org,
            workspace=self.ws,
            document=doc,
            chunk_index=0,
            text='All data centers must enforce dual power feeds.',
            contextual_header='Data Center Operations',
            page_number=1
        )

        # Mock broken vector store that raises ConnectionError
        class BrokenVectorStore:
            def search(self, *args, **kwargs):
                raise ConnectionError("Qdrant host unreachable")

        results = resilient_vector_search(
            vector_store=BrokenVectorStore(),
            collection_name="lore_chunks",
            query_vector=[0.1] * 384,
            workspace_id=str(self.ws.id),
            query_text="dual power feeds"
        )

        assert len(results) > 0
        assert results[0]['payload']['chunk_id'] == str(chunk.id)
        assert results[0]['payload']['fallback_mode'] == 'lexical_only'
        assert results[0]['payload']['circuit_breaker_active'] is True

    def test_telemetry_snapshot_and_api_endpoint(self):
        """
        Verify TelemetryService aggregates metrics and the /api/v1/health/telemetry/
        endpoint serves valid JSON percentiles and SLO compliance.
        """
        # Seed DecisionRecords
        DecisionRecord.objects.create(
            trace_id='trace-001',
            organization=self.org,
            workspace=self.ws,
            user=self.user,
            query='Is encryption mandatory?',
            state='supported',
            directive='proceed_and_cite'
        )
        DecisionRecord.objects.create(
            trace_id='trace-002',
            organization=self.org,
            workspace=self.ws,
            user=self.user,
            query='Can we waive SOC2?',
            state='denied',
            directive='stop'
        )

        # Seed AuditEvent with latencies
        AuditEvent.objects.create(
            organization=self.org,
            workspace=self.ws,
            user=self.user,
            event_type='retrieval_query',
            details={'latency_ms': 24.5}
        )

        snapshot = TelemetryService.get_telemetry_snapshot(workspace_id=str(self.ws.id))
        assert snapshot['total_governed_decisions'] == 2
        assert snapshot['state_distribution'].get('supported') == 1
        assert snapshot['state_distribution'].get('denied') == 1
        assert snapshot['directive_distribution'].get('proceed_and_cite') == 1
        assert 'p50' in snapshot['latency_percentiles_ms']
        assert 'qdrant_vector_store' in snapshot['circuit_breakers']
        assert snapshot['slo_compliance']['status'] == 'HEALTHY'

        # Test live HTTP endpoint
        client = APIClient()
        response = client.get('/api/v1/health/telemetry/')
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert 'total_governed_decisions' in data
        assert 'slo_compliance' in data
        assert 'circuit_breakers' in data
