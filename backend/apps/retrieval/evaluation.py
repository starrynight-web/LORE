import os
import math
import time
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Callable

from django.conf import settings
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument
from apps.knowledge.models import DocumentChunk
from apps.retrieval.services import HybridRetrievalService

logger = logging.getLogger(__name__)


@dataclass
class RetrievalTestCase:
    """
    Structured representation of a verified retrieval evaluation case.
    Covers enterprise challenges: multi-document synthesis, temporal/versions,
    authority arbitration, hard negatives, and restricted access isolation.
    """
    case_id: str
    query: str
    category: str
    expected_document_ids: List[str] = field(default_factory=list)
    expected_chunk_ids: List[str] = field(default_factory=list)
    expected_titles: List[str] = field(default_factory=list)
    prohibited_document_ids: List[str] = field(default_factory=list)
    prohibited_chunk_ids: List[str] = field(default_factory=list)
    min_authority_rank: int = 0
    requires_citations: bool = True
    description: str = ""
    unverified: bool = False


@dataclass
class RetrievalMetricsResult:
    """
    Measurable empirical retrieval metrics.
    Never lumps distinct signals into an opaque single score.
    """
    precision_k: float = 0.0
    recall_k: float = 0.0
    mrr: float = 0.0
    ndcg_k: float = 0.0
    correct_source_rate: float = 0.0
    evidence_coverage: float = 0.0
    citation_source_accuracy: float = 0.0
    avg_latency_ms: float = 0.0
    leakage_rate: float = 0.0
    total_cases: int = 0
    passed_cases: int = 0
    category_breakdown: Dict[str, Dict[str, float]] = field(default_factory=dict)
    case_results: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'precision_k': round(self.precision_k, 4),
            'recall_k': round(self.recall_k, 4),
            'mrr': round(self.mrr, 4),
            'ndcg_k': round(self.ndcg_k, 4),
            'correct_source_rate': round(self.correct_source_rate, 4),
            'evidence_coverage': round(self.evidence_coverage, 4),
            'citation_source_accuracy': round(self.citation_source_accuracy, 4),
            'avg_latency_ms': round(self.avg_latency_ms, 2),
            'leakage_rate': round(self.leakage_rate, 4),
            'total_cases': self.total_cases,
            'passed_cases': self.passed_cases,
            'category_breakdown': self.category_breakdown,
        }


class RetrievalEvaluationHarness:
    """
    Empirical Retrieval Evaluation & Benchmarking Harness.
    Evaluates hybrid search configurations against ground-truth evidence:
    - Precision@K, Recall@K, MRR, nDCG@K
    - Correct source and evidence coverage
    - Zero tolerance for stale/poison/cross-tenant leakage
    - Tuning set vs held-out evaluation set separation
    """

    CATEGORIES = [
        'single_doc_exact',
        'multi_doc_synthesis',
        'temporal_and_versions',
        'authority_conflict',
        'hard_negatives_distractors',
        'identifiers_and_amounts',
        'insufficient_evidence_abstention',
        'restricted_access_isolation',
    ]

    DEFAULT_GOLD_SET_PATH = os.path.join(settings.BASE_DIR, 'tests', 'data', 'gold_evaluation_set.json')

    @classmethod
    def load_gold_cases_for_workspace(
        cls,
        workspace: Workspace,
        document: Optional[SourceDocument] = None,
        custom_cases: Optional[List[Dict[str, Any]]] = None
    ) -> List[RetrievalTestCase]:
        """
        Loads verified evaluation cases. Maps titles and identifiers to relational records in the workspace.
        """
        raw_cases = []
        if custom_cases is not None:
            raw_cases = custom_cases
        elif os.path.exists(cls.DEFAULT_GOLD_SET_PATH):
            try:
                with open(cls.DEFAULT_GOLD_SET_PATH, 'r', encoding='utf-8') as f:
                    raw_cases = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load gold evaluation set from {cls.DEFAULT_GOLD_SET_PATH}: {e}")

        test_cases: List[RetrievalTestCase] = []
        ws_docs = {d.title.lower(): d for d in SourceDocument.objects.filter(workspace=workspace)}

        # Also map documents by doc codes or filenames
        doc_code_map = {}
        for d in ws_docs.values():
            if d.original_filename:
                doc_code_map[d.original_filename.lower()] = d
            for part in d.title.split():
                if '-' in part:
                    doc_code_map[part.lower()] = d

        for c in raw_cases:
            case_id = c.get('case_id', '')
            query = c.get('query', '')
            cat = c.get('category') or cls._infer_category(c)
            mandatory_evidence = c.get('mandatory_evidence_required', [])

            expected_doc_ids = []
            expected_titles = []
            prohibited_doc_ids = []

            # Check if this case matches documents in current workspace
            for code in mandatory_evidence:
                code_lower = code.lower()
                target_doc = doc_code_map.get(code_lower) or ws_docs.get(code_lower)
                if target_doc:
                    expected_doc_ids.append(str(target_doc.id))
                    expected_titles.append(target_doc.title)

            is_unverified = c.get('unverified', False)

            # If document-specific filter requested, only include if matches document
            if document and not is_unverified:
                doc_title_lower = (document.title or '').lower()
                doc_id_str = str(document.id)
                matches_doc = (
                    doc_id_str in expected_doc_ids or
                    any(code.lower() in doc_title_lower for code in mandatory_evidence) or
                    (document.original_filename and any(code.lower() in document.original_filename.lower() for code in mandatory_evidence))
                )
                if not matches_doc:
                    if doc_title_lower and doc_title_lower in query.lower():
                        expected_doc_ids.append(doc_id_str)
                        expected_titles.append(document.title)
                    else:
                        continue

            # Prohibited adversarial and cross-tenant sources
            if cat in ('restricted_access_isolation', 'temporal_and_versions', 'quarantined_adversarial'):
                # Add quarantined/stale docs in workspace as prohibited
                quarantined_ids = list(SourceDocument.objects.filter(
                    workspace=workspace, status__in=['quarantined', 'failed']
                ).values_list('id', flat=True))
                prohibited_doc_ids.extend([str(qid) for qid in quarantined_ids])

                # Add cross-tenant foreign workspace documents as strictly prohibited
                foreign_ids = list(SourceDocument.objects.exclude(
                    workspace=workspace
                ).values_list('id', flat=True))
                prohibited_doc_ids.extend([str(fid) for fid in foreign_ids])

            # Also allow explicit prohibited_document_ids from case definition
            for pid in c.get('prohibited_document_ids', []):
                prohibited_doc_ids.append(str(pid))

            test_cases.append(RetrievalTestCase(
                case_id=case_id,
                query=query,
                category=cat,
                expected_document_ids=expected_doc_ids,
                expected_titles=expected_titles,
                prohibited_document_ids=prohibited_doc_ids,
                min_authority_rank=c.get('min_authority_rank', 0),
                requires_citations=c.get('requires_citations', True),
                description=c.get('description', ''),
                unverified=is_unverified
            ))

        return test_cases

    @classmethod
    def _infer_category(cls, raw_case: Dict[str, Any]) -> str:
        case_id = raw_case.get('case_id', '').upper()
        if 'SUPERSEDED' in case_id or 'TEMPORAL' in case_id:
            return 'temporal_and_versions'
        if 'CONTRADICTION' in case_id or 'EQUAL_RANK' in case_id:
            return 'authority_conflict'
        if 'MISSING' in case_id or 'INSUFFICIENT' in case_id:
            return 'insufficient_evidence_abstention'
        if 'TENANT' in case_id or 'BARRIER' in case_id or 'UNTRUSTED' in case_id:
            return 'restricted_access_isolation'
        if 'PROMPT_INJECTION' in case_id:
            return 'hard_negatives_distractors'
        return 'single_doc_exact'

    @classmethod
    def split_tuning_and_heldout(
        cls,
        cases: List[RetrievalTestCase],
        tuning_ratio: float = 0.60
    ) -> Tuple[List[RetrievalTestCase], List[RetrievalTestCase]]:
        """
        Separates tuning cases from held-out evaluation cases to prevent parameter overfitting.
        """
        if len(cases) < 4:
            # Insufficient cases to safely split without starving evaluation
            return cases, []

        split_idx = max(2, int(len(cases) * tuning_ratio))
        return cases[:split_idx], cases[split_idx:]

    @classmethod
    def evaluate_configuration(
        cls,
        search_fn: Callable[[str, int], List[Dict[str, Any]]],
        cases: List[RetrievalTestCase],
        k: int = 5
    ) -> RetrievalMetricsResult:
        """
        Executes empirical evaluation across all cases and calculates precision, recall,
        MRR, nDCG@K, correct source rate, latency, and security/leakage rates.
        """
        if not cases:
            return RetrievalMetricsResult()

        case_results = []
        category_stats: Dict[str, Dict[str, Any]] = {}
        for cat in cls.CATEGORIES:
            category_stats[cat] = {
                'count': 0,
                'passed': 0,
                'precision_sum': 0.0,
                'recall_sum': 0.0,
                'mrr_sum': 0.0,
                'latency_sum': 0.0
            }

        total_precision = 0.0
        total_recall = 0.0
        total_mrr = 0.0
        total_ndcg = 0.0
        total_correct_source = 0.0
        total_evidence_coverage = 0.0
        total_citation_accuracy = 0.0
        total_latency = 0.0
        total_leakage = 0.0
        passed_cases = 0

        for tc in cases:
            t0 = time.time()
            try:
                hits = search_fn(tc.query, k)
            except Exception as e:
                logger.error(f"Search evaluation failed for query '{tc.query}': {e}")
                hits = []
            latency_ms = (time.time() - t0) * 1000
            total_latency += latency_ms

            retrieved_chunk_ids = [str(h.get('chunk_id', '')) for h in hits if h.get('chunk_id')]
            retrieved_doc_ids = [str(h.get('document_id', '')) for h in hits if h.get('document_id')]
            retrieved_titles = [(h.get('document_title') or '').lower() for h in hits if h.get('document_title')]

            # 1. Leakage Verification (Prohibited documents must NEVER appear in top K)
            leaked = False
            for pid in tc.prohibited_document_ids:
                if pid in retrieved_doc_ids[:k]:
                    leaked = True
                    break
            for pcid in tc.prohibited_chunk_ids:
                if pcid in retrieved_chunk_ids[:k]:
                    leaked = True
                    break

            leakage_score = 1.0 if leaked else 0.0
            total_leakage += leakage_score

            # 2. Case Metric Calculation
            if tc.category == 'insufficient_evidence_abstention' or not tc.expected_document_ids:
                # Queries where evidence does not exist or should abstain
                case_passed = (not leaked) and (len(retrieved_doc_ids) == 0 or not tc.expected_document_ids)
                p_k = 1.0 if not leaked else 0.0
                r_k = 1.0 if not leaked else 0.0
                mrr = 1.0 if not leaked else 0.0
                ndcg = 1.0 if not leaked else 0.0
                source_rate = 1.0 if not leaked else 0.0
                cov = 1.0 if not leaked else 0.0
                cit_acc = 1.0 if not leaked else 0.0
            else:
                # Expected documents exist
                expected_ids = set(tc.expected_document_ids)
                expected_titles = {t.lower() for t in tc.expected_titles}

                hits_count = 0
                first_rank = 0
                for rank, (d_id, d_title) in enumerate(zip(retrieved_doc_ids[:k], retrieved_titles[:k]), 1):
                    if d_id in expected_ids or d_title in expected_titles:
                        hits_count += 1
                        if first_rank == 0:
                            first_rank = rank

                p_k = hits_count / max(len(retrieved_doc_ids[:k]), 1)
                r_k = hits_count / max(len(expected_ids), 1)
                mrr = (1.0 / first_rank) if first_rank > 0 else 0.0

                # nDCG@K
                dcg = 0.0
                for rank, (d_id, d_title) in enumerate(zip(retrieved_doc_ids[:k], retrieved_titles[:k]), 1):
                    rel = 1.0 if (d_id in expected_ids or d_title in expected_titles) else 0.0
                    dcg += rel / math.log2(rank + 1)
                idcg = sum(1.0 / math.log2(r + 1) for r in range(1, min(len(expected_ids), k) + 1))
                ndcg = (dcg / idcg) if idcg > 0 else 0.0

                source_rate = 1.0 if first_rank > 0 else 0.0
                cov = min(1.0, hits_count / max(len(expected_ids), 1))
                cit_acc = 1.0 if (not leaked and hits_count > 0) else 0.0
                case_passed = (not leaked) and (hits_count > 0)

            if case_passed:
                passed_cases += 1

            total_precision += p_k
            total_recall += r_k
            total_mrr += mrr
            total_ndcg += ndcg
            total_correct_source += source_rate
            total_evidence_coverage += cov
            total_citation_accuracy += cit_acc

            cat = tc.category if tc.category in category_stats else 'single_doc_exact'
            c_stat = category_stats[cat]
            c_stat['count'] += 1
            if case_passed:
                c_stat['passed'] += 1
            c_stat['precision_sum'] += p_k
            c_stat['recall_sum'] += r_k
            c_stat['mrr_sum'] += mrr
            c_stat['latency_sum'] += latency_ms

            case_results.append({
                'case_id': tc.case_id,
                'category': tc.category,
                'passed': case_passed,
                'precision_k': round(p_k, 3),
                'recall_k': round(r_k, 3),
                'mrr': round(mrr, 3),
                'latency_ms': round(latency_ms, 1),
                'leaked': leaked,
                'retrieved_count': len(hits)
            })

        n = max(len(cases), 1)
        cat_breakdown: Dict[str, Dict[str, float]] = {}
        for cat, s in category_stats.items():
            cnt = s['count']
            if cnt > 0:
                cat_breakdown[cat] = {
                    'cases_count': cnt,
                    'pass_rate': round(s['passed'] / cnt, 3),
                    'precision_k': round(s['precision_sum'] / cnt, 3),
                    'recall_k': round(s['recall_sum'] / cnt, 3),
                    'mrr': round(s['mrr_sum'] / cnt, 3),
                    'avg_latency_ms': round(s['latency_sum'] / cnt, 1)
                }

        return RetrievalMetricsResult(
            precision_k=total_precision / n,
            recall_k=total_recall / n,
            mrr=total_mrr / n,
            ndcg_k=total_ndcg / n,
            correct_source_rate=total_correct_source / n,
            evidence_coverage=total_evidence_coverage / n,
            citation_source_accuracy=total_citation_accuracy / n,
            avg_latency_ms=total_latency / n,
            leakage_rate=total_leakage / n,
            total_cases=len(cases),
            passed_cases=passed_cases,
            category_breakdown=cat_breakdown,
            case_results=case_results
        )
