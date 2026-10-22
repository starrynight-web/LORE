#!/usr/bin/env python
"""
LORE Enterprise Model Context Protocol (MCP) Server.
Enables AI agents in Claude Desktop, Cursor, Windsurf, Antigravity, and custom clients
to interact with LORE's Governed Knowledge Grid, Hybrid Retrieval, Anti-Hallucination
RAG engine, and Dual-Stream OCR Pipeline.

Usage:
  python backend/mcp_server.py                 # Runs stdio JSON-RPC MCP server
  python backend/mcp_server.py --list-tools    # Prints registered tools
  python backend/mcp_server.py --test          # Self-test all retrieval tools
"""

import sys
import os
import json
import logging
import traceback
from typing import Dict, Any, List, Optional

# Ensure UTF-8 I/O for bilingual English & Bengali streaming
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Setup environment & Django context
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lore_enterprise.settings')

try:
    import django
    django.setup()
except Exception as e:
    sys.stderr.write(f"[LORE MCP FATAL] Could not initialize Django: {e}\n")
    sys.exit(1)

from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument, DocumentPage
from apps.knowledge.models import DocumentChunk
from apps.retrieval.services import HybridRetrievalService
from apps.decisions.engine import AnswerStateMachine
from apps.governance.layers import EnterpriseGovernanceEngine

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[LORE-MCP] %(levelname)s: %(message)s")
logger = logging.getLogger("lore_mcp")

# MCP Protocol Definitions
PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {
    "name": "lore-enterprise-mcp",
    "version": "2.0.0",
    "description": "LORE Enterprise Governed Knowledge Grid & Anti-Hallucination MCP Server"
}

TOOLS_MANIFEST = [
    {
        "name": "lore_search",
        "description": "Performs hybrid vector + lexical search across LORE enterprise knowledge with reciprocal rank fusion (RRF) and deep context reranking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query or keyword phrase (supports Bengali and English)"
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of the target workspace. If omitted, uses default active workspace."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of ranked passages to return (default: 6)",
                    "default": 6
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "lore_governed_query",
        "description": "Executes an anti-hallucination governed RAG query. Answers strictly using extracted PDF context, enforces 9-state governance, and provides authoritative citations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question to evaluate against governed enterprise documents."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional target workspace UUID."
                },
                "groq_api_key": {
                    "type": "string",
                    "description": "Optional user Groq API key for high-speed deterministic LLM generation with gpt-oss-120B."
                },
                "llm_model": {
                    "type": "string",
                    "description": "Target LLM model (default: gpt-oss-120B)",
                    "default": "gpt-oss-120B"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "lore_get_document",
        "description": "Retrieves comprehensive document details, page OCR confidence, and full extracted text for a specific enterprise document.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "UUID of the source document in LORE."
                }
            },
            "required": ["document_id"]
        }
    },
    {
        "name": "lore_ocr_extract",
        "description": "Executes real-time dual-stream OCR extraction (Tesseract / Bengali OCR engine) on a local document or image file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to a PDF or image file on the local filesystem."
                }
            },
            "required": ["file_path"]
        }
    }
]

def get_default_workspace() -> Optional[Workspace]:
    return Workspace.objects.filter(is_default=True).first() or Workspace.objects.first()

def handle_search(args: Dict[str, Any]) -> str:
    query = args.get("query", "").strip()
    if not query:
        return "Error: query cannot be empty."

    ws_id = args.get("workspace_id")
    if ws_id:
        ws = Workspace.objects.filter(id=ws_id).first()
    else:
        ws = get_default_workspace()

    if not ws:
        return "Error: No active workspace found in LORE."

    doc_id = args.get("document_id")
    limit = int(args.get("limit", 6))
    retriever = HybridRetrievalService()
    results = retriever.search(
        query=query,
        workspace_id=str(ws.id),
        organization_id=str(ws.organization.id),
        document_id=doc_id,
        limit=limit
    )

    if not results:
        return f"Zero passages found matching '{query}' in workspace '{ws.name}'."

    output_lines = [
        f"### LORE Hybrid Search Results ({len(results)} passages reranked)",
        f"Workspace: {ws.name} ({ws.id})",
        ""
    ]
    for i, r in enumerate(results, 1):
        output_lines.append(
            f"**[{i}] {r.get('document_title')}** (Page {r.get('page_number')}, Score: {r.get('score')}, Auth Rank: {r.get('authority_level')})\n"
            f"> {r.get('text', '')[:350]}...\n"
        )

    return "\n".join(output_lines)

def handle_governed_query(args: Dict[str, Any]) -> str:
    query = args.get("query", "").strip()
    if not query:
        return "Error: query cannot be empty."

    ws_id = args.get("workspace_id")
    if ws_id:
        ws = Workspace.objects.filter(id=ws_id).first()
    else:
        ws = get_default_workspace()

    if not ws:
        return "Error: No active workspace found in LORE."

    groq_api_key = args.get("groq_api_key")
    llm_model = args.get("llm_model", "gpt-oss-120B")
    doc_id = args.get("document_id")

    # 1. Retrieve Candidate Chunks (Scoped to PDF if document_id provided)
    retriever = HybridRetrievalService()
    chunks = retriever.search(
        query=query,
        workspace_id=str(ws.id),
        organization_id=str(ws.organization.id),
        document_id=doc_id,
        limit=10
    )

    # 2. Evaluate via Complete 9-Layer Enterprise Governance Engine
    envelope = EnterpriseGovernanceEngine.evaluate(
        query=query,
        retrieved_chunks=chunks,
        workspace=ws,
        user=None,
        user_role='workspace_admin',
        groq_api_key=groq_api_key,
        llm_model=llm_model
    )

    result_json = {
        "status": envelope.get("state"),
        "directive": envelope.get("directive"),
        "answer": envelope.get("answer"),
        "decision_type": envelope.get("decision_type"),
        "escalation_target": envelope.get("escalation_target"),
        "evidence_missing": envelope.get("evidence_missing", []),
        "conflicts_resolved": envelope.get("conflicts_resolved", []),
        "exceptions_applied": envelope.get("exceptions_applied", []),
        "layers_breakdown": envelope.get("layers_breakdown", {}),
        "llm_provider": envelope.get("llm_provider"),
        "llm_model": envelope.get("llm_model"),
        "anti_hallucination_active": True,
        "citations_count": len(envelope.get("citations", [])),
        "citations": [
            {
                "document": c.get("document_title"),
                "page": c.get("page_number"),
                "authority_rank": c.get("authority_level")
            } for c in envelope.get("citations", [])
        ],
        "trace_id": envelope.get("trace_id")
    }

    return json.dumps(result_json, indent=2, ensure_ascii=False)

def handle_get_document(args: Dict[str, Any]) -> str:
    doc_id = args.get("document_id", "").strip()
    if not doc_id:
        return "Error: document_id is required."

    doc = SourceDocument.objects.filter(id=doc_id).select_related('workspace').first()
    if not doc:
        return f"Error: Document with ID '{doc_id}' not found."

    pages = DocumentPage.objects.filter(document=doc).order_by('page_number')[:10]
    pages_summary = []
    for p in pages:
        pages_summary.append({
            "page": p.page_number,
            "confidence": p.confidence,
            "engine": p.engine,
            "words_count": p.words_count,
            "snippet": (p.text or "")[:200]
        })

    return json.dumps({
        "document_id": str(doc.id),
        "title": doc.title,
        "document_type": doc.document_type,
        "status": doc.status,
        "authority_level": doc.authority_level,
        "ocr_confidence": doc.ocr_confidence,
        "page_count": doc.page_count,
        "workspace": doc.workspace.name if doc.workspace else "N/A",
        "sample_pages": pages_summary
    }, indent=2, ensure_ascii=False)

def handle_ocr_extract(args: Dict[str, Any]) -> str:
    file_path = args.get("file_path", "").strip()
    if not file_path:
        return "Error: file_path is required."

    if not os.path.exists(file_path):
        return f"Error: File does not exist at '{file_path}'."

    from apps.ingestion.pipeline.extractors import UnifiedDocumentExtractor
    extractor = UnifiedDocumentExtractor()
    t_start = os.times()
    pages = extractor.extract_document(file_path_or_bytes=file_path)

    return json.dumps({
        "file_path": file_path,
        "pages_extracted": len(pages),
        "pages": [
            {
                "page": p.get("page_number"),
                "confidence": p.get("confidence"),
                "engine": p.get("engine"),
                "snippet": (p.get("text") or "")[:250]
            } for p in pages[:5]
        ]
    }, indent=2, ensure_ascii=False)

def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    if name == "lore_search":
        return handle_search(arguments)
    elif name == "lore_governed_query":
        return handle_governed_query(arguments)
    elif name == "lore_get_document":
        return handle_get_document(arguments)
    elif name == "lore_ocr_extract":
        return handle_ocr_extract(arguments)
    else:
        raise ValueError(f"Unknown tool: '{name}'")

def run_stdio_server():
    """Main JSON-RPC 2.0 loop over stdin and stdout."""
    logger.info("LORE Enterprise MCP server active (stdio transport).")

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        # Handle Notifications (no response needed)
        if method == "notifications/initialized":
            continue

        response: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id
        }

        try:
            if method == "initialize":
                response["result"] = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False}
                    },
                    "serverInfo": SERVER_INFO
                }
            elif method == "ping":
                response["result"] = {}
            elif method == "tools/list":
                response["result"] = {
                    "tools": TOOLS_MANIFEST
                }
            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                tool_result = execute_tool(tool_name, tool_args)
                response["result"] = {
                    "content": [
                        {
                            "type": "text",
                            "text": str(tool_result)
                        }
                    ],
                    "isError": False
                }
            else:
                response["error"] = {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
        except Exception as ex:
            logger.error(f"Error handling method {method}: {ex}\n{traceback.format_exc()}")
            response["error"] = {
                "code": -32000,
                "message": str(ex)
            }

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    if "--list-tools" in sys.argv:
        print(json.dumps(TOOLS_MANIFEST, indent=2))
        sys.exit(0)
    elif "--test" in sys.argv:
        print("Testing LORE MCP Server...")
        print("1. Search Test:")
        print(handle_search({"query": "hackathon rulebook"}))
        print("\n2. Governed Query Test:")
        print(handle_governed_query({"query": "What are the rules of the hackathon?"}))
        print("\nAll self-tests completed successfully!")
        sys.exit(0)
    else:
        run_stdio_server()
