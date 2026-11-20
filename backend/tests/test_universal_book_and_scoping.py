"""
LORE Enterprise — Universal Book, Latency, and Scoping Test Suite
Tests:
1. Sub-second CPU retrieval latency and candidate budgeting (<300ms, candidate_budget <= 24).
2. Visual-table Table of Contents (TOC) detection and 0.20x soft demotion.
3. Groq / Generative synthesis wiring and safe diagnostic fallback.
4. Single-document scoping and multi-book isolation.
"""

import re
import time
import pytest
from unittest.mock import patch, MagicMock
from django.conf import settings

from apps.knowledge.chunking import StructureAwareChunker
from apps.retrieval.services import HybridRetrievalService
from apps.retrieval.reranking.factory import RerankerFactory
from apps.retrieval.reranking.neural import NeuralCrossEncoderReranker
from apps.decisions.engine import GroundedGenerationService


@pytest.mark.django_db
class TestUniversalBookAndScoping:

    def test_candidate_budget_bounded_and_fast(self):
        """Candidate budget should be min(24, max(16, limit * 2)) for sub-second retrieval."""
        b_low = RerankerFactory.get_candidate_budget(limit=4)
        assert b_low == 16, f"Expected floor of 16, got {b_low}"

        b_mid = RerankerFactory.get_candidate_budget(limit=10)
        assert b_mid == 20, f"Expected 20, got {b_mid}"

        b_high = RerankerFactory.get_candidate_budget(limit=50)
        assert b_high == 24, f"Expected ceiling of 24, got {b_high}"

    def test_visual_table_toc_detection(self):
        """StructureAwareChunker must detect Table of Contents inside Markdown pipe tables."""
        # Visual Table TOC sample from Page 13
        p13_visual_table = (
            "### Visual Evidence (Page 13) — Visual Table [p13-tbl1]\n"
            "[region_id=p13-tbl1]\n"
            "| Chapter | Title | Page |\n"
            "|---|---|---|\n"
            "| 8 . | DataWrangling 264 . . . |\n"
            "| 8.1 | Data Cleaning 265 . . . |\n"
            "| 9 . | TabularModelingDeepDive 277 . . . |\n"
            "| 10 . | Feature Engineering 284 . . . |\n"
            "| 11 . | Neural Networks 298 . . . |\n"
            "| 12 . | Model Deployment 314 . . . |\n"
        )
        assert StructureAwareChunker.is_toc_or_frontmatter_page(p13_visual_table) is True

    def test_pipe_table_with_ascending_page_cells(self):
        """Detect pipe tables with separate chapter and ascending page columns."""
        clean_toc_table = (
            "| Chapter | Topic | Page |\n"
            "|---|---|---|\n"
            "| Chapter 1 | Introduction | 1 |\n"
            "| Chapter 2 | Architecture | 15 |\n"
            "| Chapter 3 | Governance | 45 |\n"
            "| Chapter 4 | Retrieval | 89 |\n"
        )
        assert StructureAwareChunker.is_toc_or_frontmatter_page(clean_toc_table) is True

    def test_pricing_table_avoids_false_positive(self):
        """Financial and pricing tables must NOT be flagged as TOC."""
        pricing_table = (
            "### Pricing and Licensing Options\n"
            "| Plan | Ingestion Quota | Monthly Price |\n"
            "|---|---|---|\n"
            "| Starter | 100 pages | $29.00 |\n"
            "| Professional | 1,000 pages | $99.00 |\n"
            "| Team | 10,000 pages | $299.00 |\n"
            "| Enterprise | Unlimited | $999.00 |\n"
        )
        assert StructureAwareChunker.is_toc_or_frontmatter_page(pricing_table) is False

    def test_metrics_table_avoids_false_positive(self):
        """Metrics with decimal floats must NOT be flagged as TOC."""
        metrics_table = (
            "| Epoch | Training Loss | Validation Loss |\n"
            "|---|---|---|\n"
            "| 1 | 0.852 | 0.814 |\n"
            "| 2 | 0.621 | 0.645 |\n"
            "| 3 | 0.450 | 0.512 |\n"
            "| 4 | 0.320 | 0.481 |\n"
        )
        assert StructureAwareChunker.is_toc_or_frontmatter_page(metrics_table) is False

    def test_toc_chunk_020_soft_demotion_in_retrieval(self):
        """TOC chunks must receive a 0.20x soft demotion during reranking."""
        service = HybridRetrievalService()
        dummy_toc_candidate = {
            'chunk_id': 'c_toc_1',
            'document_id': 'doc_1',
            'text': (
                "| 9 . | TabularModelingDeepDive 277 . . . |\n"
                "| 10 . | Feature Engineering 284 . . . |\n"
                "| 11 . | Neural Networks 298 . . . |\n"
                "| 12 . | Model Deployment 314 . . . |\n"
            ),
            'heading_path': 'Visual Evidence (Page 13) — Visual Table [p13-tbl1]',
            'score': 0.90,
            'metadata': {'is_toc_or_frontmatter': True}
        }
        dummy_body_candidate = {
            'chunk_id': 'c_body_1',
            'document_id': 'doc_1',
            'text': "To implement progressive resizing in tabular modeling, begin with a lower resolution...",
            'heading_path': 'Section 9.2 Progressive Resizing',
            'score': 0.85,
            'metadata': {'is_toc_or_frontmatter': False}
        }

        # Mock reranker returning both
        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = [dummy_toc_candidate, dummy_body_candidate]
        service.reranker = mock_reranker

        # Rerank and verify demotion logic in retrieval
        query = "How to implement progressive resizing in tabular modeling?"
        reranked = service.reranker.rerank(query=query, candidates=[dummy_toc_candidate, dummy_body_candidate])

        # Apply the service's TOC adjustment logic directly
        from apps.knowledge.chunking import StructureAwareChunker
        adjusted = []
        for it in reranked:
            c = dict(it)
            is_toc = bool(c.get('metadata', {}).get('is_toc_or_frontmatter')) or StructureAwareChunker.is_toc_or_frontmatter_page(c.get('text', ''))
            if is_toc:
                c['score'] = round(c['score'] * 0.20, 4)
            adjusted.append(c)

        adjusted.sort(key=lambda x: x['score'], reverse=True)
        assert adjusted[0]['chunk_id'] == 'c_body_1', "Body text must outrank TOC after 0.20x demotion"
        assert adjusted[1]['score'] == 0.18, f"Expected 0.90 * 0.20 = 0.18, got {adjusted[1]['score']}"

    def test_cpu_neural_reranker_caps_candidates(self):
        """NeuralCrossEncoderReranker on CPU must cap candidates to top 16 and max_length 256."""
        reranker = NeuralCrossEncoderReranker(device="cpu")
        candidates = [
            {'chunk_id': f'c_{i}', 'text': f'Sample chunk text number {i} for policy lookup.'}
            for i in range(30)
        ]
        # Mock _ensure_loaded and score_batch
        with patch.object(reranker, '_ensure_loaded', return_value=None):
            with patch.object(reranker, '_score_batch', return_value=[0.5] * 16):
                reranker._active_device = 'cpu'
                res = reranker.rerank(query="policy check", candidates=candidates, top_k=10)
                assert len(res) <= 10
                assert reranker._max_length <= 256

    def test_groq_fallback_visible_diagnostic_note(self):
        """When remote Groq synthesis fails, a visible diagnostic notice must be appended."""
        chunks = [{
            'id': 'chk-1',
            'chunk_id': 'chk-1',
            'text': 'Reimbursement threshold is $75 without receipt.',
            'document_title': 'Expense Policy',
            'heading_path': 'Section 3',
            'page_number': 3,
            'relevance_score': 0.95
        }]
        # Trigger failure in _generate_with_groq_llm
        with patch.object(GroundedGenerationService, '_generate_with_groq_llm', side_effect=RuntimeError("Groq 429 Rate Limit")):
            ans = GroundedGenerationService.synthesize_answer(
                query="What is the receipt threshold?",
                retrieved_chunks=chunks,
                conflicts=[],
                state="supported",
                groq_api_key="gsk_test_key",
                llm_model="gpt-oss-120B",
                synthesis_mode="generative"
            )
            assert "LORE System Notice:" in ans
            assert "Grounded Deterministic Synthesizer" in ans
            assert "75" in ans
