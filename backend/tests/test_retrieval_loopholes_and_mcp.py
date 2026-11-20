import os
import json
import time
import uuid
import pytest
from django.utils import timezone
from django.contrib.auth.models import User

from apps.workspaces.models import Workspace, Organization, WorkspaceMembership
from apps.sources.models import SourceDocument
from apps.knowledge.models import DocumentChunk, KnowledgeItem
from apps.retrieval.services import HybridRetrievalService
from apps.retrieval.query_understanding import QueryUnderstandingService
import mcp_server


def create_source_doc(org, ws, user, title, document_code, authority_level=4, status="ready"):
    return SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        owner=user,
        title=title,
        canonical_title=title,
        document_code=document_code,
        original_filename=f"{document_code.lower()}.pdf",
        mime_type="application/pdf",
        file_size=4096,
        file_hash=uuid.uuid4().hex,
        status=status,
        governance_status="approved",
        authority_level=authority_level,
        current_version_number=1
    )


@pytest.fixture
def test_setup(db):
    org = Organization.objects.create(name="Loophole Test Org", slug=f"loophole-org-{uuid.uuid4().hex[:6]}")
    user = User.objects.create_user(username=f"user_{uuid.uuid4().hex[:6]}", password="password")
    
    # Workspace 1: empty seeded workspace (created first)
    empty_ws = Workspace.objects.create(
        organization=org,
        name="Empty Seeded Workspace",
        slug=f"empty-ws-{uuid.uuid4().hex[:6]}"
    )
    WorkspaceMembership.objects.create(workspace=empty_ws, user=user, role="owner")
    
    # Workspace 2: active workspace with stable documents (created second, holds knowledge)
    active_ws = Workspace.objects.create(
        organization=org,
        name="Textbook Library Workspace",
        slug=f"active-ws-{uuid.uuid4().hex[:6]}"
    )
    WorkspaceMembership.objects.create(workspace=active_ws, user=user, role="owner")

    return {
        "org": org,
        "user": user,
        "empty_ws": empty_ws,
        "active_ws": active_ws,
    }


@pytest.mark.django_db
class TestRetrievalLoopholesAndMCP:

    def test_rare_term_and_heading_outranks_chapter1(self, test_setup):
        """
        Test 1: Rare Term & Heading Outranks Chapter-1 Overview
        Seed a multi-page textbook where pages 31/44/49 have generic 'machine learning models and data'
        and page 63 has heading 'The Drivetrain Approach' + page 64 sibling steps.
        Assert pages 63-64 rank #1 in both lore.search and lore.get_context.
        """
        active_ws = test_setup["active_ws"]
        org = test_setup["org"]
        user = test_setup["user"]

        doc = create_source_doc(
            org=org,
            ws=active_ws,
            user=user,
            title="Deep Learning for Coders Textbook",
            document_code="BOOK-DL-01",
            authority_level=4
        )

        # Generic overview chunks on earlier pages
        DocumentChunk.objects.create(
            document=doc,
            organization=org,
            workspace=active_ws,
            chunk_index=31,
            page_number=31,
            heading_path="Introduction to Machine Learning",
            section_identifier="Chapter 1 Overview",
            text="In this chapter we introduce machine learning models and data. We discuss how machine learning models work with data, according to the book, exploring various exact steps and models.",
            token_count=35
        )
        DocumentChunk.objects.create(
            document=doc,
            organization=org,
            workspace=active_ws,
            chunk_index=44,
            page_number=44,
            heading_path="Data Collection and Preparation",
            section_identifier="Section 2.1",
            text="Machine learning models and data preparation steps are critical when building real-world applications. We explore data cleaning and data pipelines.",
            token_count=30
        )
        DocumentChunk.objects.create(
            document=doc,
            organization=org,
            workspace=active_ws,
            chunk_index=49,
            page_number=49,
            heading_path="Training Models",
            section_identifier="Section 2.4",
            text="Here we consider how machine learning models learn patterns from training data, according to the book, reviewing the exact steps of data ingestion.",
            token_count=32
        )

        # Page 63: Specific heading and rare term: 'The Drivetrain Approach'
        DocumentChunk.objects.create(
            document=doc,
            organization=org,
            workspace=active_ws,
            chunk_index=63,
            page_number=63,
            heading_path="The Drivetrain Approach",
            section_identifier="Chapter 3: The Drivetrain Approach",
            text="The Drivetrain Approach to building machine learning products requires four steps: Objective, Levers, Data, and Models. We start with the defined objective.",
            token_count=35
        )
        # Page 64: Sibling steps continuation
        DocumentChunk.objects.create(
            document=doc,
            organization=org,
            workspace=active_ws,
            chunk_index=64,
            page_number=64,
            heading_path="The Drivetrain Approach",
            section_identifier="Chapter 3: The Drivetrain Approach Steps",
            text="Following the Objective, the next levers in the drivetrain approach determine what inputs we control, what data we can collect, and finally what models we build.",
            token_count=35
        )

        query = "According to the book, what are the exact steps of the 'drivetrain approach' to building machine learning products?"

        # 1. Test hybrid search with deep context
        service = HybridRetrievalService()
        results = service.search(
            query=query,
            workspace_id=str(active_ws.id),
            organization_id=str(org.id),
            deep_context=True,
            limit=8
        )
        assert len(results) > 0
        top_chunk = results[0]
        assert top_chunk["page_number"] in (63, 64)
        assert "drivetrain approach" in (top_chunk.get("heading_path", "") + top_chunk.get("text", "")).lower()

        # 2. Test MCP lore.search
        mcp_res_json = mcp_server.handle_search({
            "query": query,
            "workspace_id": str(active_ws.id),
            "output_format": "json",
            "deep_context": True
        })
        mcp_data = json.loads(mcp_res_json)
        assert "passages" in mcp_data
        assert len(mcp_data["passages"]) > 0
        top_mcp = mcp_data["passages"][0]
        assert top_mcp["page_number"] in (63, 64)

        # 3. Test MCP lore.get_context
        ctx_res_json = mcp_server.handle_get_context({
            "intent": query,
            "workspace_id": str(active_ws.id),
            "deep_context": True
        })
        ctx_data = json.loads(ctx_res_json)
        assert ctx_data.get("schema") in ("lore.result/1", "lore.result/2")
        citations = ctx_data.get("citations", [])
        assert len(citations) > 0
        top_citation = citations[0]
        assert top_citation.get("page_number") in (63, 64)

    def test_mcp_search_and_auto_workspace_discovery(self, test_setup):
        """
        Test 2: lore.search & Auto-Workspace Discovery
        Call lore.search, lore_search, and search with UUID objects, document_id, max_tokens=2400,
        deep_context=True without workspace_id.
        Assert zero TypeError / internal crashes and automatic selection of the workspace with stable docs.
        """
        active_ws = test_setup["active_ws"]
        org = test_setup["org"]
        user = test_setup["user"]

        doc = create_source_doc(
            org=org,
            ws=active_ws,
            user=user,
            title="Enterprise Governance Manual",
            document_code="GOV-MANUAL",
            authority_level=4
        )
        DocumentChunk.objects.create(
            document=doc,
            organization=org,
            workspace=active_ws,
            chunk_index=1,
            page_number=1,
            heading_path="Security Architecture",
            section_identifier="Section 1.1",
            text="Enterprise authorization mandates strict role-based access control and zero trust policies.",
            token_count=20
        )

        # Omit workspace_id entirely; pass UUID objects for document_id and ensure auto-discovery
        doc_uuid = doc.id
        call_variants = ["lore.search", "lore_search", "search"]

        for tool_name in call_variants:
            raw_res = mcp_server.call_tool(tool_name, {
                "query": "What are the enterprise authorization mandates?",
                "document_id": doc_uuid,
                "max_tokens": 2400,
                "deep_context": True,
                "output_format": "json"
            })
            assert isinstance(raw_res, str)
            parsed = json.loads(raw_res)
            # Must NOT be an internal error or TypeError
            assert parsed.get("state") != "INTERNAL_ERROR"
            assert "error" not in parsed or parsed.get("error") is None
            if "passages" in parsed:
                assert len(parsed["passages"]) > 0
                assert parsed["passages"][0]["document_id"] == str(doc_uuid)
            elif "results" in parsed:
                assert len(parsed["results"]) > 0

    def test_comparison_per_entity_quotas(self, test_setup):
        """
        Test 3: Comparison Multi-Hop & Per-Entity Quotas
        Query: 'Compare progressive resizing, test-time augmentation (TTA), and mixup'
        Assert all 3 concepts are represented in returned chunks with acronym expansion coverage.
        """
        active_ws = test_setup["active_ws"]
        org = test_setup["org"]
        user = test_setup["user"]

        doc = create_source_doc(
            org=org,
            ws=active_ws,
            user=user,
            title="Computer Vision Techniques",
            document_code="CV-TECH-01",
            authority_level=3
        )

        # Concept 1: Progressive resizing (lots of chunks)
        for i in range(1, 4):
            DocumentChunk.objects.create(
                document=doc,
                organization=org,
                workspace=active_ws,
                chunk_index=10 + i,
                page_number=100 + i,
                heading_path="Progressive Resizing",
                section_identifier=f"Section 7.{i}",
                text=f"Progressive resizing involves training on smaller images first, then increasing image sizes. Step {i} saves computational resources.",
                token_count=25
            )

        # Concept 2: Test-time augmentation (using full term on page 200)
        DocumentChunk.objects.create(
            document=doc,
            organization=org,
            workspace=active_ws,
            chunk_index=20,
            page_number=200,
            heading_path="Test-Time Augmentation",
            section_identifier="Section 8.1",
            text="Test-time augmentation averages predictions across multiple transformed versions of the test images to improve accuracy.",
            token_count=25
        )

        # Concept 3: Mixup data augmentation
        DocumentChunk.objects.create(
            document=doc,
            organization=org,
            workspace=active_ws,
            chunk_index=30,
            page_number=300,
            heading_path="Mixup Regularization",
            section_identifier="Section 9.1",
            text="Mixup is a data augmentation technique where pairs of images and labels are blended linearly using a Beta distribution parameter.",
            token_count=25
        )

        query = "Compare progressive resizing, test-time augmentation (TTA), and mixup"
        service = HybridRetrievalService()
        results = service.multi_hop_search(
            query=query,
            workspace_id=str(active_ws.id),
            organization_id=str(org.id),
            limit=12,
            enable_multi_hop=True
        )

        returned_text = " ".join((r.get("text", "") + " " + r.get("heading_path", "")) for r in results).lower()
        
        # Verify all 3 concepts are represented in the retrieved evidence
        assert "progressive resizing" in returned_text, "Progressive resizing must be present"
        assert ("test-time augmentation" in returned_text or "tta" in returned_text), "TTA must be present"
        assert "mixup" in returned_text, "Mixup must be present"

    def test_markdown_table_toc_demotion_and_deduplication(self, test_setup):
        """
        Test 4: Visual-Table TOC Demotion & Same-Page Overlap Deduplication
        1. Verify Markdown pipe table TOC page receives 0.20x demotion.
        2. Same-page visual-table vs native-text chunks with Jaccard overlap >= 0.75 are deduplicated.
        """
        active_ws = test_setup["active_ws"]
        org = test_setup["org"]
        user = test_setup["user"]

        doc = create_source_doc(
            org=org,
            ws=active_ws,
            user=user,
            title="Tabular Modeling Deep Dive Guide",
            document_code="GUIDE-TAB-01",
            authority_level=3
        )

        # Table of contents formatted as markdown pipe table with chapter titles and page numbers
        toc_text = (
            "| Chapter | Section Title | Page |\n"
            "|---|---|---|\n"
            "| 1 | Machine Learning Intro | 10 |\n"
            "| 2 | Data Preparation Deep Dive | 45 |\n"
            "| 3 | Tabular Modeling Techniques | 120 |\n"
            "| 4 | Embeddings and Categorical Variables | 180 |\n"
            "| 5 | Model Evaluation and Ensembling | 250 |\n"
        )
        DocumentChunk.objects.create(
            document=doc,
            organization=org,
            workspace=active_ws,
            chunk_index=2,
            page_number=2,
            heading_path="Table of Contents",
            section_identifier="TOC",
            text=toc_text,
            token_count=50,
            metadata={"is_toc_or_frontmatter": True}
        )

        # Substantive body text on Tabular Modeling
        DocumentChunk.objects.create(
            document=doc,
            organization=org,
            workspace=active_ws,
            chunk_index=120,
            page_number=120,
            heading_path="Tabular Modeling Techniques",
            section_identifier="Section 3.1",
            text="Tabular modeling techniques utilize entity embeddings for categorical features and decision trees or neural networks for numerical features.",
            token_count=35
        )

        # Duplicate table extraction on the same page 120 with > 0.75 token Jaccard overlap
        DocumentChunk.objects.create(
            document=doc,
            organization=org,
            workspace=active_ws,
            chunk_index=121,
            page_number=120,
            heading_path="Tabular Modeling Techniques",
            section_identifier="Section 3.1",
            text="| Feature | Method |\n|---|---|\n| Categorical features | Entity embeddings for categorical variables |\n| Numerical features | Decision trees and neural networks for numerical features |",
            token_count=30
        )

        query = "Explain tabular modeling techniques and entity embeddings"
        service = HybridRetrievalService()
        results = service.search(
            query=query,
            workspace_id=str(active_ws.id),
            organization_id=str(org.id),
            limit=8
        )

        assert len(results) > 0
        # 1. Body chunk on page 120 must outrank TOC chunk on page 2
        p120_ranks = [i for i, r in enumerate(results) if r["page_number"] == 120]
        toc_ranks = [i for i, r in enumerate(results) if r["page_number"] == 2]

        assert len(p120_ranks) > 0
        if toc_ranks:
            assert p120_ranks[0] < toc_ranks[0], "Body chunk must outrank demoted TOC chunk"

        # 2. Page 120 should only have 1 chunk due to same-page deduplication
        page_120_results = [r for r in results if r["page_number"] == 120]
        assert len(page_120_results) == 1, "Duplicate table and prose on same page must be deduplicated"

    def test_out_of_corpus_hallucination_prevention_and_latency(self, test_setup):
        """
        Test 5: Air-Gapped Hallucination Prevention & Sub-1.50s Latency
        Out-of-corpus query ('DeepSeek-R1 GRPO') returns no_knowledge (0 citations)
        and finishes in < 1.50s on CPU.
        """
        active_ws = test_setup["active_ws"]
        org = test_setup["org"]
        user = test_setup["user"]

        doc = create_source_doc(
            org=org,
            ws=active_ws,
            user=user,
            title="Standard Corporate Travel Policy",
            document_code="DOC-TRAVEL",
            authority_level=3
        )
        DocumentChunk.objects.create(
            document=doc,
            organization=org,
            workspace=active_ws,
            chunk_index=1,
            page_number=1,
            heading_path="Travel Expenses",
            section_identifier="Section 1",
            text="All business travel expenses must comply with standard lodging and meal allowances.",
            token_count=20
        )

        t_start = time.time()
        ctx_res_json = mcp_server.handle_get_context({
            "intent": "Explain DeepSeek-R1 GRPO mathematical derivation and reward modeling algorithm.",
            "workspace_id": str(active_ws.id)
        })
        elapsed = time.time() - t_start

        ctx_data = json.loads(ctx_res_json)
        # Invariant: Never invent citations on unindexed/out-of-corpus concepts
        assert (ctx_data.get("status") or ctx_data.get("state")) in ("no_knowledge", "insufficient", "abstain")
        assert len(ctx_data.get("citations", [])) == 0
        assert elapsed < 1.50, f"Query took {elapsed:.2f}s, exceeding 1.50s limit"
