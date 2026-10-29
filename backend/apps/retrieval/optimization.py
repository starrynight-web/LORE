import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from django.db import transaction
from django.utils import timezone

from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument
from apps.ingestion.models import IngestionJob
from apps.audit.models import AuditEvent
from apps.retrieval.models import RetrievalConfiguration, RetrievalOptimizationRun
from apps.retrieval.evaluation import RetrievalEvaluationHarness, RetrievalTestCase, RetrievalMetricsResult
from apps.retrieval.services import HybridRetrievalService

logger = logging.getLogger(__name__)


class EvidenceDrivenOptimizationService:
    """
    Evidence-Driven Retrieval Optimization Engine (Prompt 3).
    Evaluates current baseline against ground truth, tests controlled candidates,
    enforces governance and security boundaries, and implements controlled release
    and rollback behavior.
    """

    @classmethod
    def get_or_create_active_config(cls, workspace: Optional[Workspace] = None) -> RetrievalConfiguration:
        """
        Retrieves the active production configuration for the workspace or initializes default.
        """
        if workspace:
            config = RetrievalConfiguration.objects.filter(workspace=workspace, is_active=True).first()
            if config:
                return config

        # Global active config
        config = RetrievalConfiguration.objects.filter(workspace=None, is_active=True).first()
        if config:
            return config

        # Initialize Default Baseline Configuration
        with transaction.atomic():
            default_config = RetrievalConfiguration.objects.create(
                workspace=workspace,
                version=1,
                name="Production Baseline Configuration",
                is_active=True,
                limit=8,
                rrf_k=60.0,
                min_relevance_threshold=0.05,
                context_budget_tokens=800,
                enable_graph_expansion=True,
                graph_max_depth=2,
                graph_max_nodes=15,
                notes="Initial production default configuration."
            )
        return default_config

    @classmethod
    def generate_controlled_candidates(cls, base: RetrievalConfiguration) -> List[Dict[str, Any]]:
        """
        Generates bounded, well-reasoned candidate configurations to avoid uncontrolled combinatorial search.
        """
        candidates = []

        # Candidate 1: High Precision & Stricter Reranking
        candidates.append({
            'name': 'Candidate A: High-Precision Rerank Filter',
            'limit': max(5, base.limit - 2),
            'rrf_k': 50.0,
            'min_relevance_threshold': 0.10,
            'context_budget_tokens': max(600, base.context_budget_tokens - 100),
            'enable_graph_expansion': base.enable_graph_expansion,
            'graph_max_depth': base.graph_max_depth,
            'graph_max_nodes': base.graph_max_nodes,
            'notes': 'Stricter relevance threshold (0.10) to reduce distractor noise.'
        })

        # Candidate 2: High Recall & Wider Context Budget
        candidates.append({
            'name': 'Candidate B: High-Recall Multi-Document Fusion',
            'limit': base.limit + 4,
            'rrf_k': 70.0,
            'min_relevance_threshold': 0.04,
            'context_budget_tokens': base.context_budget_tokens + 400,
            'enable_graph_expansion': True,
            'graph_max_depth': 3,
            'graph_max_nodes': 20,
            'notes': 'Expanded candidate pool (limit 12) and context budget (1200 tokens) for complex synthesis.'
        })

        # Candidate 3: Low-Latency Streaming Profile
        candidates.append({
            'name': 'Candidate C: Low-Latency Streaming Profile',
            'limit': 5,
            'rrf_k': 60.0,
            'min_relevance_threshold': 0.08,
            'context_budget_tokens': 500,
            'enable_graph_expansion': False,
            'graph_max_depth': 1,
            'graph_max_nodes': 5,
            'notes': 'Optimized for sub-50ms latency with graph traversal disabled.'
        })

        return candidates

    @classmethod
    def run_optimization(
        cls,
        workspace: Workspace,
        document: Optional[SourceDocument] = None,
        job: Optional[IngestionJob] = None,
        custom_cases: Optional[List[Dict[str, Any]]] = None
    ) -> RetrievalOptimizationRun:
        """
        Executes evidence-driven retrieval optimization:
        1. Loads verified evaluation dataset.
        2. Evaluates baseline.
        3. Evaluates candidates on tuning data.
        4. Validates top candidate on held-out test data.
        5. Enforces governance invariant (zero tolerance for leakage).
        6. Persists audit record and decision.
        """
        active_config = cls.get_or_create_active_config(workspace)
        all_cases = RetrievalEvaluationHarness.load_gold_cases_for_workspace(
            workspace=workspace,
            document=document,
            custom_cases=custom_cases
        )

        # ---------------- Check for Missing Evaluation Data ----------------
        if not all_cases:
            run_rec = RetrievalOptimizationRun.objects.create(
                workspace=workspace,
                document=document,
                job=job,
                status='blocked_missing_evaluation_dataset',
                baseline_config=active_config,
                decision='blocked_no_dataset',
                decision_reason=(
                    "Verified evaluation dataset not available for current document/workspace. "
                    "Production retrieval configuration safely preserved without speculative promotion."
                ),
                eval_cases_count=0
            )
            return run_rec

        # ---------------- Split Tuning vs Held-out Test Data ----------------
        tuning_cases, heldout_cases = RetrievalEvaluationHarness.split_tuning_and_heldout(all_cases)

        # ---------------- Baseline Evaluation ----------------
        def make_search_fn(cfg_params: Dict[str, Any]):
            retriever = HybridRetrievalService()
            def _fn(q: str, k: int):
                return retriever.search(
                    query=q,
                    workspace_id=str(workspace.id),
                    organization_id=str(workspace.organization.id),
                    limit=cfg_params.get('limit', k),
                    rrf_k=cfg_params.get('rrf_k', 60.0),
                    min_relevance_threshold=cfg_params.get('min_relevance_threshold', 0.05),
                    context_budget_tokens=cfg_params.get('context_budget_tokens', 800),
                    enable_graph_expansion=cfg_params.get('enable_graph_expansion', True),
                    graph_max_depth=cfg_params.get('graph_max_depth', 2),
                    graph_max_nodes=cfg_params.get('graph_max_nodes', 15)
                )
            return _fn

        base_search_fn = make_search_fn(active_config.to_dict())
        baseline_metrics = RetrievalEvaluationHarness.evaluate_configuration(
            search_fn=base_search_fn,
            cases=tuning_cases,
            k=active_config.limit
        )

        # ---------------- Evaluate Candidates on Tuning Data ----------------
        candidate_specs = cls.generate_controlled_candidates(active_config)
        candidate_eval_results = []

        for cand_spec in candidate_specs:
            cand_fn = make_search_fn(cand_spec)
            m_res = RetrievalEvaluationHarness.evaluate_configuration(
                search_fn=cand_fn,
                cases=tuning_cases,
                k=cand_spec['limit']
            )
            candidate_eval_results.append({
                'spec': cand_spec,
                'metrics': m_res
            })

        # ---------------- Candidate Comparison & Ranking ----------------
        # Objective Score: F = 0.4*Recall + 0.35*MRR + 0.25*Precision - 10.0*Leakage
        def score_metrics(m: RetrievalMetricsResult) -> float:
            if m.leakage_rate > 0.0:
                return -100.0  # Immediate veto on security or leakage violation
            return (0.40 * m.recall_k) + (0.35 * m.mrr) + (0.25 * m.precision_k)

        baseline_score = score_metrics(baseline_metrics)
        best_candidate = None
        best_cand_score = baseline_score
        best_cand_metrics = None

        for item in candidate_eval_results:
            cand_score = score_metrics(item['metrics'])
            # Must strictly improve objective by at least 0.02 without regressing leakage
            if cand_score > best_cand_score and (cand_score - baseline_score) >= 0.02:
                # Assert no regression in primary metrics
                no_mrr_regression = item['metrics'].mrr >= (baseline_metrics.mrr - 0.01)
                no_recall_regression = item['metrics'].recall_k >= (baseline_metrics.recall_k - 0.01)
                if no_mrr_regression and no_recall_regression:
                    best_candidate = item['spec']
                    best_cand_score = cand_score
                    best_cand_metrics = item['metrics']

        # ---------------- Held-out Generalization Validation ----------------
        heldout_passed = True
        heldout_reason = ""
        if best_candidate and heldout_cases:
            cand_heldout_fn = make_search_fn(best_candidate)
            base_heldout_fn = make_search_fn(active_config.to_dict())

            heldout_cand_metrics = RetrievalEvaluationHarness.evaluate_configuration(cand_heldout_fn, heldout_cases)
            heldout_base_metrics = RetrievalEvaluationHarness.evaluate_configuration(base_heldout_fn, heldout_cases)

            if heldout_cand_metrics.leakage_rate > 0.0:
                heldout_passed = False
                heldout_reason = "Vetoed: Candidate leaked prohibited sources on held-out evaluation set."
            elif score_metrics(heldout_cand_metrics) < (score_metrics(heldout_base_metrics) - 0.02):
                heldout_passed = False
                heldout_reason = "Overfitting detected: Candidate improved tuning set but regressed held-out evaluation set."

        # ---------------- Final Decision Resolution ----------------
        proposed_config_obj = None

        if best_candidate and best_cand_metrics and heldout_passed:
            decision = 'improvement_proposed'
            status = 'improvement_proposed'
            decision_notes = (
                f"Candidate '{best_candidate['name']}' demonstrated justified empirical improvement. "
                f"Tuning score: {best_cand_score:.3f} vs baseline {baseline_score:.3f} "
                f"(MRR: {best_cand_metrics.mrr:.3f} vs {baseline_metrics.mrr:.3f}). "
                f"Awaiting authorized promotion."
            )
            # Create proposed config in database
            with transaction.atomic():
                next_version = (RetrievalConfiguration.objects.filter(workspace=workspace).order_by('-version').first() or active_config).version + 1
                proposed_config_obj = RetrievalConfiguration.objects.create(
                    workspace=workspace,
                    version=next_version,
                    name=best_candidate['name'],
                    is_active=False,
                    limit=best_candidate['limit'],
                    rrf_k=best_candidate['rrf_k'],
                    min_relevance_threshold=best_candidate['min_relevance_threshold'],
                    context_budget_tokens=best_candidate['context_budget_tokens'],
                    enable_graph_expansion=best_candidate['enable_graph_expansion'],
                    graph_max_depth=best_candidate['graph_max_depth'],
                    graph_max_nodes=best_candidate['graph_max_nodes'],
                    notes=best_candidate['notes']
                )
        elif best_candidate and not heldout_passed:
            decision = 'rejected_regression'
            status = 'retained_baseline'
            decision_notes = f"Rejected candidate: {heldout_reason}. Preserved baseline configuration."
        else:
            decision = 'retained_baseline'
            status = 'retained_baseline'
            decision_notes = (
                "Baseline configuration remains optimal. "
                "Tested candidate configurations did not achieve required improvement margin without regressions."
            )

        run_rec = RetrievalOptimizationRun.objects.create(
            workspace=workspace,
            document=document,
            job=job,
            status=status,
            baseline_config=active_config,
            proposed_config=proposed_config_obj,
            rollback_config=active_config,
            baseline_metrics=baseline_metrics.to_dict(),
            candidate_metrics=best_cand_metrics.to_dict() if best_cand_metrics else {},
            category_breakdown=baseline_metrics.category_breakdown,
            decision=decision,
            decision_reason=decision_notes,
            eval_cases_count=len(all_cases),
            eval_dataset_version="gold_v1.0"
        )

        AuditEvent.objects.create(
            organization=workspace.organization,
            workspace=workspace,
            event_type='retrieval_optimization_evaluated',
            target_type='retrieval_configuration',
            target_id=str(active_config.id),
            details={
                'optimization_run_id': str(run_rec.id),
                'status': status,
                'decision': decision,
                'baseline_mrr': round(baseline_metrics.mrr, 4),
                'proposed_config_id': str(proposed_config_obj.id) if proposed_config_obj else None
            }
        )

        return run_rec

    @classmethod
    def promote_configuration(cls, optimization_run_id: str, user=None) -> RetrievalConfiguration:
        """
        Promotes a proposed retrieval configuration under the release policy.
        Preserves the previous active configuration for safe rollback.
        """
        run_rec = RetrievalOptimizationRun.objects.select_related(
            'workspace', 'baseline_config', 'proposed_config'
        ).get(id=optimization_run_id)

        if not run_rec.proposed_config:
            raise ValueError(f"OptimizationRun {optimization_run_id} has no proposed configuration to promote.")

        ws = run_rec.workspace
        new_config = run_rec.proposed_config
        old_config = run_rec.baseline_config

        with transaction.atomic():
            # Deactivate existing active configurations in workspace
            RetrievalConfiguration.objects.filter(workspace=ws, is_active=True).update(is_active=False)

            # Activate newly promoted configuration
            new_config.is_active = True
            new_config.save(update_fields=['is_active'])

            # Update run record
            run_rec.is_promoted = True
            run_rec.promoted_at = timezone.now()
            run_rec.promoted_by = user
            run_rec.rollback_config = old_config
            run_rec.decision = 'promoted'
            run_rec.status = 'completed'
            run_rec.save()

        AuditEvent.objects.create(
            organization=ws.organization,
            workspace=ws,
            user=user,
            event_type='retrieval_configuration_promoted',
            target_type='retrieval_configuration',
            target_id=str(new_config.id),
            details={
                'promoted_version': new_config.version,
                'previous_version': old_config.version if old_config else None,
                'optimization_run_id': str(run_rec.id)
            }
        )

        return new_config

    @classmethod
    def rollback_configuration(
        cls,
        workspace: Workspace,
        target_config_id: Optional[str] = None,
        user=None
    ) -> RetrievalConfiguration:
        """
        Rolls back the active configuration to the previous known-good configuration.
        """
        with transaction.atomic():
            current_active = RetrievalConfiguration.objects.filter(workspace=workspace, is_active=True).first()

            if target_config_id:
                target_config = RetrievalConfiguration.objects.get(id=target_config_id, workspace=workspace)
            else:
                # Find previous version
                target_config = RetrievalConfiguration.objects.filter(
                    workspace=workspace, is_active=False
                ).order_by('-created_at').first()

            if not target_config:
                raise ValueError("No previous configuration found for rollback.")

            if current_active:
                current_active.is_active = False
                current_active.save(update_fields=['is_active'])

            target_config.is_active = True
            target_config.save(update_fields=['is_active'])

        AuditEvent.objects.create(
            organization=workspace.organization,
            workspace=workspace,
            user=user,
            event_type='retrieval_configuration_rollback',
            target_type='retrieval_configuration',
            target_id=str(target_config.id),
            details={
                'rolled_back_to_version': target_config.version,
                'deactivated_version': current_active.version if current_active else None
            }
        )

        return target_config
