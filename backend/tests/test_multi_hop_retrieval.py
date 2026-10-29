"""
LORE Enterprise — Multi-Hop Retrieval Test Suite
Verifies query decomposition, parallel sub-query execution, provenance tagging, and result fusion.
"""
import os
import sys
import pytest
from typing import Dict, List, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lore_enterprise.settings')
import django
django.setup()

from apps.identity.models import Organization, User
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument
from apps.retrieval.services import HybridRetrievalService
from apps.retrieval.multi_hop import QueryDecomposer, SubQuery, MultiHopResult
from apps.retrieval.query_understanding import QueryUnderstandingService
from apps.governance.evidence_package import StructuredEvidencePackage


@pytest.mark.django_db
class TestMultiHopRetrievalSuite:
    """Test suite covering Three-Tier Multi-Hop Retrieval architecture."""

    def test_01_query_decomposition_compound_detection(self):
        """Verify compound query detection across diverse syntaxes."""
        # Compound queries
        assert QueryDecomposer.is_compound_query("Sarah needs $4,500 purchase + 3 days leave") is True
        assert QueryDecomposer.is_compound_query("What is the procurement limit for equipment and also what are the leave carryover rules?") is True
        assert QueryDecomposer.is_compound_query("Can we approve the hotel stay and she also requested 4 days leave?") is True
        assert QueryDecomposer.is_compound_query("Emergency procurement rules and what is the leave policy during blackout?") is True

        # Simple single-topic queries
        assert QueryDecomposer.is_compound_query("What is the nightly hotel cap for Tokyo?") is False
        assert QueryDecomposer.is_compound_query("What are the retention rules for audit logs?") is False
        assert QueryDecomposer.is_compound_query("Who can approve a $5,000 procurement?") is False

    def test_02_decompose_procurement_and_leave(self):
        """Verify Q2 decomposition: procurement + leave."""
        q = "Sarah needs $4,500 purchase + 3 days leave"
        analysis = QueryUnderstandingService.analyze(q)
        sub_queries = QueryDecomposer.decompose(q, analysis)

        assert len(sub_queries) == 2
        domains = [sq.domain for sq in sub_queries]
        assert "procurement" in domains
        assert "annual_leave" in domains

        proc_sq = next(sq for sq in sub_queries if sq.domain == "procurement")
        leave_sq = next(sq for sq in sub_queries if sq.domain == "annual_leave")

        assert "DOC-003" in proc_sq.target_doc_codes
        assert "DOC-005" in leave_sq.target_doc_codes

    def test_03_decompose_emergency_procurement_and_blackout(self):
        """Verify Q9 decomposition: emergency procurement + leave blackout."""
        q = "Emergency Procurement exception and also leave blackout coverage"
        analysis = QueryUnderstandingService.analyze(q)
        sub_queries = QueryDecomposer.decompose(q, analysis)

        assert len(sub_queries) >= 2
        domains = [sq.domain for sq in sub_queries]
        assert "emergency_procurement" in domains or "procurement" in domains
        assert "annual_leave" in domains

    def test_04_fusion_and_provenance_tagging(self):
        """Verify result fusion round-robin and provenance preservation."""
        service = HybridRetrievalService()

        # Mock sub-results
        sq_proc = SubQuery(
            id="sub_A_procurement",
            text="procurement purchase",
            domain="procurement",
            target_doc_codes=["DOC-003"],
            companion_docs=[],
            role_label="procurement"
        )
        sq_leave = SubQuery(
            id="sub_B_annual_leave",
            text="annual leave blackout",
            domain="annual_leave",
            target_doc_codes=["DOC-005"],
            companion_docs=[],
            role_label="annual_leave"
        )

        res_proc = MultiHopResult(
            sub_query=sq_proc,
            chunks=[
                {
                    'chunk_id': 'chunk-proc-1',
                    'document_code': 'DOC-003',
                    'document_title': 'Procurement Authority Matrix',
                    'score': 0.85,
                    'multi_hop_boost': 0.5,
                    'text': 'Head of Dept approves up to $10,000'
                },
                {
                    'chunk_id': 'chunk-proc-2',
                    'document_code': 'DOC-003',
                    'document_title': 'Procurement Authority Matrix',
                    'score': 0.70,
                    'multi_hop_boost': 0.5,
                    'text': 'Purchases under $5,000 require manager approval'
                }
            ],
            retrieval_mode='hybrid',
            total_ms=10
        )

        res_leave = MultiHopResult(
            sub_query=sq_leave,
            chunks=[
                {
                    'chunk_id': 'chunk-leave-1',
                    'document_code': 'DOC-005',
                    'document_title': 'Annual Leave Policy',
                    'score': 0.90,
                    'multi_hop_boost': 0.5,
                    'text': 'Annual inventory blackout period prohibits leave'
                },
                {
                    'chunk_id': 'chunk-leave-2',
                    'document_code': 'DOC-005',
                    'document_title': 'Annual Leave Policy',
                    'score': 0.65,
                    'multi_hop_boost': 0.5,
                    'text': 'Max 5 days carryover permitted'
                }
            ],
            retrieval_mode='hybrid',
            total_ms=12
        )

        fused = service._fuse_multi_hop_results([res_proc, res_leave], limit=6)

        assert len(fused) == 4
        # Verify both domains are represented in fused results
        domains = {c.get('multi_hop_domain') for c in fused}
        assert 'procurement' in domains
        assert 'annual_leave' in domains

        # Verify source tagging
        sources = {c.get('multi_hop_source') for c in fused}
        assert 'sub_A_procurement' in sources
        assert 'sub_B_annual_leave' in sources

    def test_05_evidence_package_xml_multi_hop_tags(self):
        """Verify StructuredEvidencePackage serializes multi_hop_domain tags into LLM context."""
        chunks = [
            {
                'chunk_id': 'c1',
                'document_code': 'DOC-003',
                'document_title': 'Procurement Matrix',
                'text': 'Approval rules for $4,500.',
                'multi_hop_domain': 'procurement',
                'authority_level': 6,
                'governance_status': 'active',
                'score': 0.9
            },
            {
                'chunk_id': 'c2',
                'document_code': 'DOC-005',
                'document_title': 'Annual Leave Policy',
                'text': 'Leave rules for 3 days.',
                'multi_hop_domain': 'annual_leave',
                'authority_level': 5,
                'governance_status': 'active',
                'score': 0.88
            }
        ]

        pkg = StructuredEvidencePackage.from_chunks(
            query="Sarah needs $4,500 purchase + 3 days leave",
            chunks=chunks
        )

        xml = pkg.format_for_llm()
        assert 'multi_hop_domain="procurement"' in xml
        assert 'multi_hop_domain="annual_leave"' in xml

