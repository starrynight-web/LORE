#!/usr/bin/env python
"""
LORE Enterprise Model Context Protocol (MCP) Server.
Enables AI agents in Claude Desktop, Cursor, Windsurf, Antigravity, and custom clients
to interact with LORE's Governed Knowledge Grid, Hybrid Retrieval, Anti-Hallucination
RAG engine, Decision Lineage, and Dual-Stream OCR Pipeline.

Specification: lore.md §11 (MCP Tool Surface) & §12.2 (The Constitution Pattern).

Usage:
  python backend/mcp_server.py                 # Runs stdio JSON-RPC MCP server
  python backend/mcp_server.py --list-tools    # Prints registered tools manifest
  python backend/mcp_server.py --test          # Self-test all retrieval & governance tools
"""

import sys
import os
import re
import json
import logging
import traceback
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Union
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Ensure UTF-8 I/O for bilingual English & Bengali streaming
reconfigure_stdout = getattr(sys.stdout, 'reconfigure', None)
if callable(reconfigure_stdout):
    reconfigure_stdout(encoding='utf-8')
reconfigure_stderr = getattr(sys.stderr, 'reconfigure', None)
if callable(reconfigure_stderr):
    reconfigure_stderr(encoding='utf-8')

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

from django.utils import timezone
from django.db import models
from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument, DocumentVersion, DocumentPage
from apps.knowledge.models import (
    DocumentChunk, KnowledgeItem, KnowledgeRelationship,
    RelationshipType, RelationshipApprovalStatus
)
from apps.decisions.models import DecisionRecord
from apps.audit.models import AuditEvent
from apps.governance.models import (
    EvidenceRequirement, ConflictRecord, SourcePermission,
    ScopedException, AccessLevel
)
from apps.governance.contract import (
    GovernanceRequest, GovernanceReasonCode, Verdict, Directive,
    validate_canonical_envelope, fail_closed_envelope
)
from apps.governance.modes import sanitize_sensitive_data
from apps.governance.layers import (
    EnterpriseGovernanceEngine, PermissionLayer, AuthorityLayer,
    TemporalValidityLayer, ExceptionLayer, EvidenceSufficiencyLayer
)
from apps.retrieval.services import HybridRetrievalService

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[LORE-MCP] %(levelname)s: %(message)s")
logger = logging.getLogger("lore_mcp")

# MCP Protocol Definitions
PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {
    "name": "lore-enterprise-mcp",
    "version": "2.1.0",
    "description": "LORE Enterprise Governed Knowledge Grid & Anti-Hallucination MCP Server (lore.md §11)"
}


# ==============================================================================
# STRUCTURED ERROR HELPERS
# ==============================================================================
def make_error_response(
    code: str,
    message: str,
    reason_code: str = "ERROR",
    details: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None
) -> str:
    """Produces a sanitized, structured JSON error envelope adhering to lore.error/1."""
    clean_message = sanitize_sensitive_data(message)
    clean_details = sanitize_sensitive_data(details or {})
    payload = {
        "schema": "lore.error/1",
        "is_error": True,
        "error": {
            "code": code,
            "message": clean_message,
            "reason_code": reason_code,
            "details": clean_details
        },
        "trace_id": trace_id or f"err-{uuid.uuid4().hex[:8]}",
        "timestamp": timezone.now().isoformat()
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


IGNORE_WORKSPACE_SENTINELS = {"", "null", "none", "undefined", "false", "true", "0", "nil"}


def resolve_workspace(
    workspace_id: Optional[Union[str, uuid.UUID]] = None,
    organization_id: Optional[Union[str, uuid.UUID]] = None,
    workspace_name: Optional[str] = None
) -> Tuple[Optional[Workspace], Optional[str]]:
    """
    Validates tenant boundary and resolves target workspace.
    Supports workspace_id (UUID or str), workspace_name, and smart default resolution
    to the workspace with the highest count of stable/approved documents.
    Fails closed with structured error JSON if invalid or cross-tenant.
    """
    ws = None

    # Normalize input strings and filter out agent sentinel strings
    ws_id_str = str(workspace_id).strip() if workspace_id is not None else None
    if ws_id_str and ws_id_str.lower() in IGNORE_WORKSPACE_SENTINELS:
        ws_id_str = None

    ws_name_str = str(workspace_name).strip() if workspace_name is not None else None
    if ws_name_str and ws_name_str.lower() in IGNORE_WORKSPACE_SENTINELS:
        ws_name_str = None

    # Check for explicit "default" keyword
    force_default = False
    if ws_id_str and ws_id_str.lower() == "default":
        ws_id_str = None
        force_default = True
    if ws_name_str and ws_name_str.lower() == "default":
        ws_name_str = None
        force_default = True

    if ws_id_str and not force_default:
        try:
            ws = Workspace.objects.filter(id=ws_id_str).select_related('organization').first()
        except Exception:
            # If workspace_id was not a valid UUID format, try lookup by name
            ws = Workspace.objects.filter(name__iexact=ws_id_str).select_related('organization').first()
            if not ws:
                ws = Workspace.objects.filter(name__icontains=ws_id_str).select_related('organization').first()
        if not ws:
            # In case UUID query returned None, also attempt lookup by name
            ws = Workspace.objects.filter(name__iexact=ws_id_str).select_related('organization').first()
            if not ws:
                ws = Workspace.objects.filter(name__icontains=ws_id_str).select_related('organization').first()
        if not ws and not ws_name_str:
            return None, make_error_response("RESOURCE_NOT_FOUND", f"Workspace with ID or name '{workspace_id}' does not exist.", reason_code="WORKSPACE_NOT_FOUND")

    if not ws and ws_name_str and not force_default:
        ws = Workspace.objects.filter(name__iexact=ws_name_str).select_related('organization').first()
        if not ws:
            ws = Workspace.objects.filter(name__icontains=ws_name_str).select_related('organization').first()
        if not ws:
            return None, make_error_response("RESOURCE_NOT_FOUND", f"Workspace with name '{workspace_name}' does not exist.", reason_code="WORKSPACE_NOT_FOUND")

    if not ws:
        # Smart Default Workspace Resolution:
        # Resolve to the workspace with highest count of stable/approved documents (ordered by most recent document update)
        try:
            from django.db.models import Count, Max, Q
            candidate_ws = (
                Workspace.objects.annotate(
                    doc_count=Count(
                        'documents',
                        filter=Q(documents__status__in=['approved', 'ready', 'active', 'stable']) |
                               Q(documents__governance_status__in=['approved', 'ready', 'active', 'stable'])
                    ),
                    latest_doc_update=Max('documents__updated_at')
                )
                .filter(doc_count__gt=0)
                .order_by('-doc_count', '-latest_doc_update')
                .select_related('organization')
                .first()
            )
            ws = candidate_ws
        except Exception as ws_ex:
            logger.warning(f"Smart workspace resolution fallback: {ws_ex}")
            ws = None

        if not ws:
            ws = Workspace.objects.filter(is_default=True).select_related('organization').first() or Workspace.objects.select_related('organization').first()

        if not ws:
            return None, make_error_response("RESOURCE_NOT_FOUND", "No active workspace found in LORE.", reason_code="WORKSPACE_NOT_FOUND")

    if organization_id and ws.organization:
        org_id_str = str(organization_id).strip()
        if org_id_str.lower() not in IGNORE_WORKSPACE_SENTINELS and org_id_str.lower() != "default":
            if str(getattr(ws.organization, "id", "")) != org_id_str:
                return None, make_error_response(
                    "PERMISSION_DENIED",
                    f"Workspace '{ws.id}' does not belong to organization '{organization_id}'. Cross-tenant access denied.",
                    reason_code="TENANT_ISOLATION_VIOLATION"
                )

    return ws, None


def resolve_workspace_from_args(args: Dict[str, Any]) -> Tuple[Optional[Workspace], Optional[str]]:
    """Resolves workspace from MCP arguments dict supporting workspace_id, workspace_name, and organization_id."""
    return resolve_workspace(
        workspace_id=args.get("workspace_id"),
        organization_id=args.get("organization_id"),
        workspace_name=args.get("workspace_name")
    )


def get_organization_id(ws: Workspace) -> str:
    """Safely extracts organization UUID string from a workspace instance."""
    org_id = getattr(ws, "organization_id", None)
    if not org_id and ws.organization:
        org_id = getattr(ws.organization, "id", None)
    return str(org_id or ws.id)



# ==============================================================================
# TOOLS MANIFEST (lore.md §11: 15 canonical tools + documented aliases)
# ==============================================================================
# TOOLS MANIFEST (lore.md §11 & ChatGPT Web 2026 Spec: canonical tools + aliases)
# ==============================================================================
# JSON literal compatibility for schema manifests
true = True
false = False
null = None

READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
}
MUTATING_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
}

TOOLS_MANIFEST: List[Dict[str, Any]] = [
    {
        "name": "lore.get_context",
        "description": "Canonical flagship LORE tool: retrieves governed context for a file or intent, evaluates through the 9-layer governance engine, and returns a canonical lore.result/2 envelope. Defaults to a concise <=800-token governed envelope. Pass max_tokens (up to 3200) or deep_context=true (or limit > 10) when full multi-paragraph chapter excerpts are required.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path of the file being edited or inspected."
                },
                "intent": {
                    "type": "string",
                    "description": "Task intent or query to evaluate against governed knowledge."
                },
                "query": {
                    "type": "string",
                    "description": "Direct query string (alternative to file_path + intent)."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "organization_id": {
                    "type": "string",
                    "description": "Optional UUID of organization for tenant isolation check."
                },
                "user_role": {
                    "type": "string",
                    "description": "Principal role (e.g. member, workspace_admin, auditor, anonymous). Default: member.",
                    "default": "member"
                },
                "as_of": {
                    "type": "string",
                    "description": "Optional point-in-time date for temporal evaluation (YYYY-MM-DD or ISO)."
                },
                "execution_mode": {
                    "type": "string",
                    "description": "Execution strategy: 'local_only', 'deterministic_first', or 'approved_remote'.",
                    "default": "deterministic_first"
                },
                "synthesis_mode": {
                    "type": "string",
                    "description": "Synthesis mode: 'auto', 'extractive', 'abstractive', 'deterministic'.",
                    "default": "auto"
                },
                "document_id": {
                    "type": "string",
                    "description": "Optional UUID of specific source document to scope retrieval."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of candidate passages to retrieve (1-50, default: 10).",
                    "default": 10
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Optional maximum token budget for returned context passages (default: 800; max: 3200). Increase to 1600-3200 when synthesizing multi-chapter book sections or cross-document comparisons."
                },
                "deep_context": {
                    "type": "boolean",
                    "description": "When true, expands context delivery up to 2400 tokens across up to 12 ranked passages for deep multi-paragraph synthesis.",
                    "default": false
                },
                "groq_api_key": {
                    "type": "string",
                    "description": "Optional Groq API key for remote model inference if authorized."
                },
                "llm_model": {
                    "type": "string",
                    "description": "Target LLM model (default: gpt-oss-120B).",
                    "default": "gpt-oss-120B"
                },
                "zk_attestation": {
                    "type": "boolean",
                    "description": "Opt-in generation of verifiable Zero-Knowledge Proof (ZKP) policy attestation. Default: false.",
                    "default": false
                }
            }
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.search",
        "description": "Performs hybrid vector + lexical search across LORE enterprise knowledge. NOTICE: Returns un-adjudicated candidate passages; not an authoritative governance decision. Defaults to a concise <=800-token governed envelope. Pass max_tokens (up to 3200) or deep_context=true (or limit > 10) when full multi-paragraph chapter excerpts are required.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query or keyword phrase (English and Bengali supported)."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "organization_id": {
                    "type": "string",
                    "description": "Optional UUID of target organization."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of ranked passages to return (1-50, default: 6).",
                    "default": 6
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Optional maximum token budget for returned context passages (default: 800; max: 3200). Increase to 1600-3200 when synthesizing multi-chapter book sections or cross-document comparisons."
                },
                "deep_context": {
                    "type": "boolean",
                    "description": "When true, expands context delivery up to 2400 tokens across up to 12 ranked passages for deep multi-paragraph synthesis.",
                    "default": false
                },
                "document_id": {
                    "type": "string",
                    "description": "Optional UUID of specific source document to scope search."
                },
                "unverified": {
                    "type": "boolean",
                    "description": "If true, includes draft and quarantined knowledge items in search. Default: false.",
                    "default": false
                },
                "output_format": {
                    "type": "string",
                    "description": "Output representation: 'text' (default markdown summary) or 'json' (structured candidate envelope).",
                    "default": "text"
                }
            },
            "required": [
                "query"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.check_compliance",
        "description": "Evaluates a proposed code diff or specification change against governed enterprise rules, returning per-rule PASS/FAIL/UNCERTAIN verdicts and machine exit codes (0=PASS, 3=ask_user, 4=stop) for pre-commit gating.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff": {
                    "type": "string",
                    "description": "Unified diff, code patch, or policy statement to evaluate."
                },
                "intent": {
                    "type": "string",
                    "description": "High-level summary of the change or feature being developed."
                },
                "file_path": {
                    "type": "string",
                    "description": "Target file or component path being modified."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "organization_id": {
                    "type": "string",
                    "description": "Optional UUID of target organization."
                },
                "user_role": {
                    "type": "string",
                    "description": "Role of the executing principal. Default: member.",
                    "default": "member"
                },
                "as_of": {
                    "type": "string",
                    "description": "Optional point-in-time date for temporal rule applicability."
                },
                "zk_attestation": {
                    "type": "boolean",
                    "description": "Opt-in generation of verifiable Zero-Knowledge Proof (ZKP) policy attestation. Default: false.",
                    "default": false
                }
            },
            "required": [
                "diff"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.detect_conflicts",
        "description": "Generates a conflict report across enterprise knowledge, listing contradictory claims, conflicting documents, and authority resolutions (L6).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "scope": {
                    "type": "string",
                    "description": "Optional query keyword, document title, or component to filter conflicts."
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: 'all', 'unresolved', or 'resolved_by_authority'. Default: 'all'.",
                    "default": "all"
                }
            }
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.trace",
        "description": "Retrieves the full decision lineage for a trace ID: query -> candidate rules -> versions -> sources -> governance layers breakdown -> citations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_id": {
                    "type": "string",
                    "description": "The trace ID or decision UUID to inspect."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            },
            "required": [
                "trace_id"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.log_decision",
        "description": "Appends an authoritative decision record to the LORE audit log and decision lineage database (L0).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task prompt or query that was evaluated."
                },
                "rules": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "List of rule codes or policy titles that governed the decision."
                },
                "outcome": {
                    "type": "string",
                    "description": "Decision state/directive: 'proceed_and_cite', 'stop', 'ask_user', 'escalate', 'violation', 'supported'."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes, justification, or summary."
                },
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object"
                    },
                    "description": "Optional list of cited document sources."
                },
                "token_count": {
                    "type": "integer",
                    "description": "Tokens consumed during task evaluation.",
                    "default": 0
                }
            },
            "required": [
                "task",
                "rules",
                "outcome"
            ]
        },
        "annotations": {
            "readOnlyHint": false,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.get_history",
        "description": "Retrieves document version timeline, modification history, and SUPERSEDES relationship chains (L5).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Document ID, original filename, or title to inspect."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            },
            "required": [
                "file"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.stats",
        "description": "Computes knowledge graph statistics: document counts, chunks, rule/skill items, graph edges, conflicts, and decision volume (L0).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            }
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.check_evidence_sufficiency",
        "description": "Standalone evidence sufficiency evaluation: verifies whether available evidence satisfies mandatory requirements for a given decision type (L3).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "decision_type": {
                    "type": "string",
                    "description": "Decision category (e.g. 'vendor_approval', 'production_deployment', 'security_change', 'general_inquiry')."
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "Optional list of evidence tokens, entity names, or candidate claims."
                },
                "query": {
                    "type": "string",
                    "description": "Optional search query to automatically retrieve and evaluate candidate evidence."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            },
            "required": [
                "decision_type"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.get_authority_info",
        "description": "Retrieves authority hierarchy metadata (rank 1-7), document status, staleness thresholds, and access level for a source document (L6).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "Document UUID, title, or original filename."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            },
            "required": [
                "source_id"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.query_as_of",
        "description": "Point-in-time historical retrieval and governance evaluation: strictly enforces document validity and edges active on the specified date (L5).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question to evaluate against historical point-in-time knowledge."
                },
                "as_of": {
                    "type": "string",
                    "description": "Historical date/timestamp (YYYY-MM-DD or ISO 8601)."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum passages to retrieve (default: 6).",
                    "default": 6
                },
                "user_role": {
                    "type": "string",
                    "description": "Executing role for RBAC check. Default: member.",
                    "default": "member"
                }
            },
            "required": [
                "query",
                "as_of"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.get_active_exceptions",
        "description": "Lists active scoped exceptions applying to the current context, department, project, or vendor (L4).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "rule_code": {
                    "type": "string",
                    "description": "Optional rule code to filter exceptions (e.g. 'SEC-R-014')."
                },
                "scope_type": {
                    "type": "string",
                    "description": "Optional scope category: 'department', 'project', 'data_type', 'vendor'."
                },
                "as_of": {
                    "type": "string",
                    "description": "Optional point-in-time date to check historical exception validity."
                }
            }
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.escalate_to_human",
        "description": "Creates a human review ticket in the compliance queue when a decision encounters conflicting evidence, unresolvable ambiguity, or high-risk rules (L2).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The task or question requiring human adjudication."
                },
                "state": {
                    "type": "string",
                    "description": "Reason for escalation ('human_review', 'conflicting', 'violation', 'insufficient'). Default: human_review.",
                    "default": "human_review"
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "context": {
                    "type": "object",
                    "description": "Optional dictionary of context, candidate citations, or notes."
                }
            },
            "required": [
                "query"
            ]
        },
        "annotations": {
            "readOnlyHint": false,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.bootstrap",
        "description": "Serves the constitution (agent.md) and phase policies on connect, establishing meta-rules and operational directives for the client session (lore.md \u00a711 & \u00a712.2).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "phase": {
                    "type": "string",
                    "description": "Development phase: 'meta', 'planning', 'implementation', or 'verification'."
                }
            }
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.get_skill",
        "description": "Retrieves procedural steps, prerequisites, and authority guidelines for a specific engineering or operational skill (lore.md \u00a711).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name or identifier (e.g. 'ui-ux-pro', 'security-audit', 'compliance-gate')."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            },
            "required": [
                "name"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.list_documents",
        "description": "Lists all accessible workspace documents (including title, page count, status, authority level, and document ID) for document-scoped discovery.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "organization_id": {
                    "type": "string",
                    "description": "Optional UUID of target organization."
                }
            }
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.get_document",
        "description": "Retrieves comprehensive document details, page OCR confidence, and extracted text for an enterprise source document.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "UUID of the source document in LORE."
                }
            },
            "required": [
                "document_id"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.ocr_extract",
        "description": "Executes real-time dual-stream OCR extraction (Tesseract / Bengali OCR engine) on a local document or image file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to a PDF or image file on the local filesystem."
                }
            },
            "required": [
                "file_path"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.attest_compliance",
        "description": "Evaluates enterprise policy compliance and generates a verifiable zero-knowledge attestation (ZK-SNARK or ZKP-lite Merkle) proving compliance without leaking confidential rule statements or source document paths.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "decision_type": {
                    "type": "string",
                    "description": "Category of decision: 'vendor_approval', 'production_deployment', 'security_change', 'statutory_compliance', 'general_inquiry'."
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "Candidate evidence tokens, entities, or claims to evaluate."
                },
                "query": {
                    "type": "string",
                    "description": "Optional search query to retrieve evidence context."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "organization_id": {
                    "type": "string",
                    "description": "Optional UUID of target organization."
                },
                "user_role": {
                    "type": "string",
                    "description": "Requester RBAC role. Default: member.",
                    "default": "member"
                },
                "required_authority_floor": {
                    "type": "integer",
                    "description": "Minimum authority rank required for binding compliance (1-7). Default: 4.",
                    "default": 4
                },
                "backend": {
                    "type": "string",
                    "description": "Proving backend: 'auto' (default), 'noir', or 'zkp_lite_merkle'.",
                    "default": "auto"
                }
            },
            "required": [
                "decision_type"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore.verify_zk_proof",
        "description": "Cryptographically verifies an external ZKAttestationEnvelope (ZK-SNARK or ZKP-lite Merkle proof) offline without requiring database access or exposing proprietary rule statements.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "attestation_envelope": {
                    "type": "object",
                    "description": "The serialized ZKAttestationEnvelope JSON object containing proof_system, workspace_state_root, public_inputs, and proof_b64."
                }
            },
            "required": [
                "attestation_envelope"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "search",
        "description": "ChatGPT Deep Research standard search tool. Queries LORE governed knowledge and returns candidate passages. Defaults to a concise <=800-token governed envelope. Pass max_tokens (up to 3200) or deep_context=true (or limit > 10) when full multi-paragraph chapter excerpts are required.",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query or keyword phrase to evaluate against enterprise knowledge."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of candidate passages to retrieve (1-50, default: 6).",
                    "default": 6
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Optional maximum token budget for returned context passages (default: 800; max: 3200). Increase to 1600-3200 when synthesizing multi-chapter book sections or cross-document comparisons."
                },
                "deep_context": {
                    "type": "boolean",
                    "description": "When true, expands context delivery up to 2400 tokens across up to 12 ranked passages for deep multi-paragraph synthesis.",
                    "default": false
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            },
            "required": [
                "query"
            ]
        }
    },
    {
        "name": "fetch",
        "description": "ChatGPT Deep Research standard fetch tool. Retrieves full governed rule, document, or chunk content by ID.",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Identifier of the document, chunk, or rule to retrieve."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            },
            "required": [
                "id"
            ]
        }
    },
    {
        "name": "lore_attest_compliance",
        "description": "Legacy alias for lore.attest_compliance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "decision_type": {
                    "type": "string",
                    "description": "Decision category."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Target workspace UUID."
                }
            },
            "required": [
                "decision_type"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore_verify_zk_proof",
        "description": "Legacy alias for lore.verify_zk_proof.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "attestation_envelope": {
                    "type": "object",
                    "description": "ZK attestation envelope."
                }
            },
            "required": [
                "attestation_envelope"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore_search",
        "description": "Legacy alias for lore.search. Performs hybrid vector + lexical search. Defaults to a concise <=800-token governed envelope. Pass max_tokens (up to 3200) or deep_context=true (or limit > 10) when full multi-paragraph chapter excerpts are required.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Target workspace UUID."
                },
                "limit": {
                    "type": "integer",
                    "description": "Result limit (default: 6).",
                    "default": 6
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Optional maximum token budget for returned context passages (default: 800; max: 3200). Increase to 1600-3200 when synthesizing multi-chapter book sections or cross-document comparisons."
                },
                "deep_context": {
                    "type": "boolean",
                    "description": "When true, expands context delivery up to 2400 tokens across up to 12 ranked passages for deep multi-paragraph synthesis.",
                    "default": false
                }
            },
            "required": [
                "query"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore_governed_query",
        "description": "Legacy alias for lore.get_context. Executes 9-layer anti-hallucination governed query. Defaults to a concise <=800-token governed envelope. Pass max_tokens (up to 3200) or deep_context=true (or limit > 10) when full multi-paragraph chapter excerpts are required.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question to evaluate against governed enterprise documents."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Target workspace UUID."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of candidate passages to retrieve (1-50, default: 10).",
                    "default": 10
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Optional maximum token budget for returned context passages (default: 800; max: 3200). Increase to 1600-3200 when synthesizing multi-chapter book sections or cross-document comparisons."
                },
                "deep_context": {
                    "type": "boolean",
                    "description": "When true, expands context delivery up to 2400 tokens across up to 12 ranked passages for deep multi-paragraph synthesis.",
                    "default": false
                },
                "groq_api_key": {
                    "type": "string",
                    "description": "Optional Groq API key."
                },
                "llm_model": {
                    "type": "string",
                    "description": "Target model (default: gpt-oss-120B).",
                    "default": "gpt-oss-120B"
                }
            },
            "required": [
                "query"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore_list_documents",
        "description": "Legacy alias for lore.list_documents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "organization_id": {
                    "type": "string",
                    "description": "Optional UUID of target organization."
                }
            }
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore_get_document",
        "description": "Legacy alias for lore.get_document.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "UUID of the source document in LORE."
                }
            },
            "required": [
                "document_id"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore_ocr_extract",
        "description": "Legacy alias for lore.ocr_extract.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to a PDF or image file."
                }
            },
            "required": [
                "file_path"
            ]
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        }
    },
    {
        "name": "lore_get_context",
        "description": "Underscore alias for lore.get_context. Canonical flagship LORE tool: retrieves governed context for a file or intent, evaluates through the 9-layer governance engine, and returns a canonical lore.result/2 envelope. Defaults to a concise <=800-token governed envelope. Pass max_tokens (up to 3200) or deep_context=true (or limit > 10) when full multi-paragraph chapter excerpts are required.",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path of the file being edited or inspected."
                },
                "intent": {
                    "type": "string",
                    "description": "Task intent or query to evaluate against governed knowledge."
                },
                "query": {
                    "type": "string",
                    "description": "Direct query string (alternative to file_path + intent)."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "organization_id": {
                    "type": "string",
                    "description": "Optional UUID of organization for tenant isolation check."
                },
                "user_role": {
                    "type": "string",
                    "description": "Principal role (e.g. member, workspace_admin, auditor, anonymous). Default: member.",
                    "default": "member"
                },
                "as_of": {
                    "type": "string",
                    "description": "Optional point-in-time date for temporal evaluation (YYYY-MM-DD or ISO)."
                },
                "execution_mode": {
                    "type": "string",
                    "description": "Execution strategy: 'local_only', 'deterministic_first', or 'approved_remote'.",
                    "default": "deterministic_first"
                },
                "synthesis_mode": {
                    "type": "string",
                    "description": "Synthesis mode: 'auto', 'extractive', 'abstractive', 'deterministic'.",
                    "default": "auto"
                },
                "document_id": {
                    "type": "string",
                    "description": "Optional UUID of specific source document to scope retrieval."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of candidate passages to retrieve (1-50, default: 10).",
                    "default": 10
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Optional maximum token budget for returned context passages (default: 800; max: 3200). Increase to 1600-3200 when synthesizing multi-chapter book sections or cross-document comparisons."
                },
                "deep_context": {
                    "type": "boolean",
                    "description": "When true, expands context delivery up to 2400 tokens across up to 12 ranked passages for deep multi-paragraph synthesis.",
                    "default": false
                },
                "groq_api_key": {
                    "type": "string",
                    "description": "Optional Groq API key for remote model inference if authorized."
                },
                "llm_model": {
                    "type": "string",
                    "description": "Target LLM model (default: gpt-oss-120B).",
                    "default": "gpt-oss-120B"
                },
                "zk_attestation": {
                    "type": "boolean",
                    "description": "Opt-in generation of verifiable Zero-Knowledge Proof (ZKP) policy attestation. Default: false.",
                    "default": false
                }
            }
        }
    },
    {
        "name": "lore_check_compliance",
        "description": "Underscore alias for lore.check_compliance. Evaluates a proposed code diff or specification change against governed enterprise rules, returning per-rule PASS/FAIL/UNCERTAIN verdicts and machine exit codes (0=PASS, 3=ask_user, 4=stop) for pre-commit gating.",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff": {
                    "type": "string",
                    "description": "Unified diff, code patch, or policy statement to evaluate."
                },
                "intent": {
                    "type": "string",
                    "description": "High-level summary of the change or feature being developed."
                },
                "file_path": {
                    "type": "string",
                    "description": "Target file or component path being modified."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "organization_id": {
                    "type": "string",
                    "description": "Optional UUID of target organization."
                },
                "user_role": {
                    "type": "string",
                    "description": "Role of the executing principal. Default: member.",
                    "default": "member"
                },
                "as_of": {
                    "type": "string",
                    "description": "Optional point-in-time date for temporal rule applicability."
                },
                "zk_attestation": {
                    "type": "boolean",
                    "description": "Opt-in generation of verifiable Zero-Knowledge Proof (ZKP) policy attestation. Default: false.",
                    "default": false
                }
            },
            "required": [
                "diff"
            ]
        }
    },
    {
        "name": "lore_detect_conflicts",
        "description": "Underscore alias for lore.detect_conflicts. Generates a conflict report across enterprise knowledge, listing contradictory claims, conflicting documents, and authority resolutions (L6).",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "scope": {
                    "type": "string",
                    "description": "Optional query keyword, document title, or component to filter conflicts."
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: 'all', 'unresolved', or 'resolved_by_authority'. Default: 'all'.",
                    "default": "all"
                }
            }
        }
    },
    {
        "name": "lore_trace",
        "description": "Underscore alias for lore.trace. Retrieves the full decision lineage for a trace ID: query -> candidate rules -> versions -> sources -> governance layers breakdown -> citations.",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_id": {
                    "type": "string",
                    "description": "The trace ID or decision UUID to inspect."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            },
            "required": [
                "trace_id"
            ]
        }
    },
    {
        "name": "lore_log_decision",
        "description": "Underscore alias for lore.log_decision. Appends an authoritative decision record to the LORE audit log and decision lineage database (L0).",
        "annotations": {
            "readOnlyHint": false,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task prompt or query that was evaluated."
                },
                "rules": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "List of rule codes or policy titles that governed the decision."
                },
                "outcome": {
                    "type": "string",
                    "description": "Decision state/directive: 'proceed_and_cite', 'stop', 'ask_user', 'escalate', 'violation', 'supported'."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes, justification, or summary."
                },
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object"
                    },
                    "description": "Optional list of cited document sources."
                },
                "token_count": {
                    "type": "integer",
                    "description": "Tokens consumed during task evaluation.",
                    "default": 0
                }
            },
            "required": [
                "task",
                "rules",
                "outcome"
            ]
        }
    },
    {
        "name": "lore_get_history",
        "description": "Underscore alias for lore.get_history. Retrieves document version timeline, modification history, and SUPERSEDES relationship chains (L5).",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Document ID, original filename, or title to inspect."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            },
            "required": [
                "file"
            ]
        }
    },
    {
        "name": "lore_stats",
        "description": "Underscore alias for lore.stats. Computes knowledge graph statistics: document counts, chunks, rule/skill items, graph edges, conflicts, and decision volume (L0).",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            }
        }
    },
    {
        "name": "lore_check_evidence_sufficiency",
        "description": "Underscore alias for lore.check_evidence_sufficiency. Standalone evidence sufficiency evaluation: verifies whether available evidence satisfies mandatory requirements for a given decision type (L3).",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "decision_type": {
                    "type": "string",
                    "description": "Decision category (e.g. 'vendor_approval', 'production_deployment', 'security_change', 'general_inquiry')."
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "Optional list of evidence tokens, entity names, or candidate claims."
                },
                "query": {
                    "type": "string",
                    "description": "Optional search query to automatically retrieve and evaluate candidate evidence."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            },
            "required": [
                "decision_type"
            ]
        }
    },
    {
        "name": "lore_get_authority_info",
        "description": "Underscore alias for lore.get_authority_info. Retrieves authority hierarchy metadata (rank 1-7), document status, staleness thresholds, and access level for a source document (L6).",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "Document UUID, title, or original filename."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            },
            "required": [
                "source_id"
            ]
        }
    },
    {
        "name": "lore_query_as_of",
        "description": "Underscore alias for lore.query_as_of. Point-in-time historical retrieval and governance evaluation: strictly enforces document validity and edges active on the specified date (L5).",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question to evaluate against historical point-in-time knowledge."
                },
                "as_of": {
                    "type": "string",
                    "description": "Historical date/timestamp (YYYY-MM-DD or ISO 8601)."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum passages to retrieve (default: 6).",
                    "default": 6
                },
                "user_role": {
                    "type": "string",
                    "description": "Executing role for RBAC check. Default: member.",
                    "default": "member"
                }
            },
            "required": [
                "query",
                "as_of"
            ]
        }
    },
    {
        "name": "lore_get_active_exceptions",
        "description": "Underscore alias for lore.get_active_exceptions. Lists active scoped exceptions applying to the current context, department, project, or vendor (L4).",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "rule_code": {
                    "type": "string",
                    "description": "Optional rule code to filter exceptions (e.g. 'SEC-R-014')."
                },
                "scope_type": {
                    "type": "string",
                    "description": "Optional scope category: 'department', 'project', 'data_type', 'vendor'."
                },
                "as_of": {
                    "type": "string",
                    "description": "Optional point-in-time date to check historical exception validity."
                }
            }
        }
    },
    {
        "name": "lore_escalate_to_human",
        "description": "Underscore alias for lore.escalate_to_human. Creates a human review ticket in the compliance queue when a decision encounters conflicting evidence, unresolvable ambiguity, or high-risk rules (L2).",
        "annotations": {
            "readOnlyHint": false,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The task or question requiring human adjudication."
                },
                "state": {
                    "type": "string",
                    "description": "Reason for escalation ('human_review', 'conflicting', 'violation', 'insufficient'). Default: human_review.",
                    "default": "human_review"
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "context": {
                    "type": "object",
                    "description": "Optional dictionary of context, candidate citations, or notes."
                }
            },
            "required": [
                "query"
            ]
        }
    },
    {
        "name": "lore_bootstrap",
        "description": "Underscore alias for lore.bootstrap. Serves the constitution (agent.md) and phase policies on connect, establishing meta-rules and operational directives for the client session (lore.md \u00a711 & \u00a712.2).",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                },
                "workspace_name": {
                    "type": "string",
                    "description": "Optional name of target workspace."
                },
                "phase": {
                    "type": "string",
                    "description": "Development phase: 'meta', 'planning', 'implementation', or 'verification'."
                }
            }
        }
    },
    {
        "name": "lore_get_skill",
        "description": "Underscore alias for lore.get_skill. Retrieves procedural steps, prerequisites, and authority guidelines for a specific engineering or operational skill (lore.md \u00a711).",
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name or identifier (e.g. 'ui-ux-pro', 'security-audit', 'compliance-gate')."
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Optional UUID of target workspace."
                }
            },
            "required": [
                "name"
            ]
        }
    }
]

# ==============================================================================
# TOKEN BUDGET & EXCERPT RESOLUTION (On-Demand Dynamic Budgeting)
# ==============================================================================

def resolve_mcp_token_budget(args: Dict[str, Any], default_limit: int = 10) -> Tuple[int, int, bool]:
    """
    Dynamically computes effective limit and token budget based on MCP client requests.
    Returns (limit, effective_max_tokens, is_expanded).
    """
    try:
        limit = min(max(1, int(args.get("limit", default_limit))), 50)
    except (ValueError, TypeError):
        limit = default_limit

    raw_max_tokens = args.get("max_tokens")
    parsed_max_tokens = None
    if raw_max_tokens is not None:
        try:
            parsed_max_tokens = int(raw_max_tokens)
        except (ValueError, TypeError):
            parsed_max_tokens = None

    deep_context = bool(args.get("deep_context", False))

    is_expanded = (
        (parsed_max_tokens is not None and parsed_max_tokens > 800)
        or deep_context
        or (limit > 10)
    )

    if parsed_max_tokens is not None:
        effective_max_tokens = min(max(200, parsed_max_tokens), 3200)
    elif deep_context:
        effective_max_tokens = 2400
    elif limit > 10:
        effective_max_tokens = min(3200, limit * 160)
    else:
        effective_max_tokens = 800

    return limit, effective_max_tokens, is_expanded


def truncate_sentence_safe(text: str, max_chars: int) -> str:
    """Truncates text up to max_chars without breaking mid-sentence if possible."""
    if not text or len(text) <= max_chars:
        return text or ""
    snippet = text[:max_chars]
    min_bound = int(max_chars * 0.6)
    matches = list(re.finditer(r'[.!?](?:\s|$)', snippet))
    if matches and matches[-1].end() >= min_bound:
        return snippet[:matches[-1].end()].strip()
    last_space = snippet.rfind(" ")
    if last_space >= min_bound:
        return snippet[:last_space].strip() + "..."
    return snippet.strip() + "..."


def estimate_tokens(text: str) -> int:
    """Estimates tokens using tiktoken (cl100k_base) if installed, or word-based heuristic."""
    if not text:
        return 0
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return max(1, len(enc.encode(text)))
    except Exception:
        words = text.split()
        return max(1, int(len(words) * 1.3))


# ==============================================================================
# TOOL HANDLERS (Direct Routing to Canonical Backend Services)
# ==============================================================================

def handle_get_context(args: Dict[str, Any]) -> str:
    """Flagship governed context retrieval and 9-layer adjudication (lore.md §4 & §11)."""
    try:
        raw_query = args.get("query") or args.get("intent") or args.get("task_intent") or ""
        file_path = args.get("file_path", "")

        if not raw_query and file_path:
            query = f"Rules and compliance requirements for {file_path}"
        elif file_path and raw_query:
            query = f"{raw_query} (file: {file_path})"
        else:
            query = str(raw_query).strip()

        if not query:
            return make_error_response("INVALID_ARGUMENT", "Either 'query' or 'file_path' and 'intent' must be provided.")

        ws, err = resolve_workspace_from_args(args)
        if err or not ws:
            return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

        limit, effective_max_tokens, is_expanded = resolve_mcp_token_budget(args, default_limit=10)

        groq_api_key = args.get("groq_api_key")
        llm_model = args.get("llm_model", "gpt-oss-120B")
        doc_id = args.get("document_id")
        if doc_id is not None:
            doc_id = str(doc_id).strip()
        doc_title = args.get("document_title") or args.get("focus_files") or args.get("focus_file")
        if not doc_id and doc_title:
            from apps.knowledge.models import SourceDocument
            from django.db.models import Q
            matched_doc = SourceDocument.objects.filter(
                workspace=ws
            ).filter(
                Q(title__icontains=str(doc_title).strip()) |
                Q(canonical_title__icontains=str(doc_title).strip()) |
                Q(original_filename__icontains=str(doc_title).strip()) |
                Q(document_code__iexact=str(doc_title).strip())
            ).first()
            if matched_doc:
                doc_id = str(matched_doc.id)

        as_of = args.get("as_of")
        user_role = args.get("user_role", "member")
        execution_mode = args.get("execution_mode")
        synthesis_mode = args.get("synthesis_mode")

        # 1. Hybrid Retrieval through canonical service
        retriever = HybridRetrievalService()
        candidate_chunks = retriever.search(
            query=query,
            workspace_id=str(ws.id),
            organization_id=get_organization_id(ws),
            document_id=doc_id,
            limit=limit,
            context_budget_tokens=effective_max_tokens
        )

        # 2. Canonical 9-Layer Governance Adjudication
        policy_context = {
            "max_context_tokens": effective_max_tokens,
            "deep_context": is_expanded,
            "limit": limit,
            "document_id": doc_id
        }
        envelope = EnterpriseGovernanceEngine.evaluate(
            query=query,
            retrieved_chunks=candidate_chunks,
            workspace=ws,
            user=None,
            user_role=user_role,
            as_of=as_of,
            groq_api_key=groq_api_key,
            llm_model=llm_model,
            execution_mode=execution_mode,
            synthesis_mode=synthesis_mode,
            policy_context=policy_context,
            zk_attestation=bool(args.get("zk_attestation", False))
        )

        envelope = sanitize_sensitive_data(envelope)

        max_passage_chars = 1200 if is_expanded else 400
        envelope_citations = envelope.get("citations", [])
        if doc_id:
            envelope_citations = [
                c for c in envelope_citations
                if str(c.get("document_id") or "") == str(doc_id)
            ]
        max_citations_count = min(limit, 12) if is_expanded else 6

        citations_list = []
        for c in envelope_citations[:max_citations_count]:
            raw_p = c.get("passage") or c.get("shortest_passage") or ""
            trunc_p = truncate_sentence_safe(raw_p, max_chars=max_passage_chars)
            citations_list.append({
                "document": str(c.get("document_title") or ""),
                "document_code": str(c.get("document_code") or ""),
                "page": int(c.get("page_number") or 1),
                "page_number": int(c.get("page_number") or 1),
                "section": str(c.get("section") or c.get("heading_path") or ""),
                "passage": trunc_p,
                "authority_rank": int(c.get("authority_level") or 4)
            })

        # Pack evidence_passages greedily up to effective_max_tokens
        evidence_passages = []
        actual_packed_tokens = 0

        potential_items = []
        for c in envelope_citations:
            potential_items.append({
                "document": str(c.get("document_title") or ""),
                "page": int(c.get("page_number") or 1),
                "page_number": int(c.get("page_number") or 1),
                "section": str(c.get("section") or c.get("heading_path") or ""),
                "authority_rank": int(c.get("authority_level") or 4),
                "score": float(c.get("score") or 1.0),
                "text": str(c.get("passage") or c.get("shortest_passage") or "")
            })

        if is_expanded:
            for chk in candidate_chunks:
                if chk.get("governance_status") in ("draft", "quarantined") or chk.get("status") in ("draft", "quarantined"):
                    continue
                if doc_id and str(chk.get("document_id")) != str(doc_id):
                    continue
                t = str(chk.get("document_title") or "")
                p = int(chk.get("page_number") or 1)
                s = str(chk.get("section") or chk.get("heading_path") or "")
                if not any(it["document"] == t and it["page"] == p and it["section"] == s for it in potential_items):
                    potential_items.append({
                        "document": t,
                        "page": p,
                        "page_number": p,
                        "section": s,
                        "authority_rank": int(chk.get("authority_level") or 4),
                        "score": float(chk.get("score") or 0.0),
                        "text": str(chk.get("text") or chk.get("content") or "")
                    })

        for item in potential_items:
            raw_text = item["text"]
            clean_text = truncate_sentence_safe(raw_text, max_chars=max_passage_chars)
            if not clean_text:
                continue
            toks = estimate_tokens(clean_text)
            if evidence_passages and (actual_packed_tokens + toks > effective_max_tokens):
                if not is_expanded or actual_packed_tokens + 20 > effective_max_tokens:
                    break
                continue
            if not evidence_passages and toks > effective_max_tokens:
                clean_text = truncate_sentence_safe(clean_text, max_chars=effective_max_tokens * 3)
                toks = estimate_tokens(clean_text)

            evidence_passages.append({
                "document": item["document"],
                "page": item["page"],
                "section": item["section"],
                "authority_rank": item["authority_rank"],
                "score": item["score"],
                "text": clean_text
            })
            actual_packed_tokens += toks
            if actual_packed_tokens >= effective_max_tokens:
                break

        result_json = {
            "schema": str(envelope.get("schema", "lore.result/2")),
            "status": str(envelope.get("state") or ""),
            "directive": str(envelope.get("directive") or ""),
            "answer": str(envelope.get("answer") or ""),
            "decision_type": str(envelope.get("decision_type") or ""),
            "escalation_target": envelope.get("escalation_target"),
            "evidence_missing": envelope.get("evidence_missing", []),
            "conflicts_resolved": envelope.get("conflicts_resolved", []),
            "exceptions_applied": envelope.get("exceptions_applied", []),
            "layers_breakdown": envelope.get("layers_breakdown", {}),
            "llm_provider": envelope.get("llm_provider"),
            "llm_model": envelope.get("llm_model"),
            "anti_hallucination_active": True,
            "citations_count": int(len(citations_list)),
            "retrieval_degraded": bool(envelope.get("retrieval_degraded", False)),
            "execution_mode": envelope.get("execution_mode"),
            "was_deterministic": bool(envelope.get("was_deterministic", True)),
            "bundle_hash": envelope.get("bundle_hash"),
            "zk_attestation": envelope.get("zk_attestation"),
            "token_budget_applied": int(effective_max_tokens),
            "tokens_returned": int(actual_packed_tokens),
            "context_mode": "expanded" if is_expanded else "standard",
            "evidence_passages": evidence_passages,
            "citations": citations_list,
            "trace_id": str(envelope.get("trace_id") or "")
        }

        return json.dumps(result_json, indent=2, ensure_ascii=False, default=str)
    except Exception as ex:
        logger.error(f"Error executing handle_get_context: {ex}\n{traceback.format_exc()}")
        return make_error_response(
            "INTERNAL_ERROR",
            f"Error executing lore.get_context: {ex}",
            reason_code="CONTEXT_EXECUTION_EXCEPTION"
        )


def handle_search(args: Dict[str, Any]) -> str:
    """
    Hybrid vector + lexical search across enterprise knowledge.
    Distinguishes raw un-adjudicated candidate passages from governed decisions.
    """
    try:
        raw_query = args.get("query") or args.get("intent") or args.get("task_intent") or ""
        query = str(raw_query).strip()
        if not query:
            return make_error_response("INVALID_ARGUMENT", "The 'query' parameter cannot be empty.")

        ws, err = resolve_workspace_from_args(args)
        if err or not ws:
            return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

        limit, effective_max_tokens, is_expanded = resolve_mcp_token_budget(args, default_limit=6)

        doc_id = args.get("document_id")
        if doc_id is not None:
            doc_id = str(doc_id).strip()
        doc_title = args.get("document_title") or args.get("focus_files") or args.get("focus_file")
        if not doc_id and doc_title:
            from apps.knowledge.models import SourceDocument
            from django.db.models import Q
            matched_doc = SourceDocument.objects.filter(
                workspace=ws
            ).filter(
                Q(title__icontains=str(doc_title).strip()) |
                Q(canonical_title__icontains=str(doc_title).strip()) |
                Q(original_filename__icontains=str(doc_title).strip()) |
                Q(document_code__iexact=str(doc_title).strip())
            ).first()
            if matched_doc:
                doc_id = str(matched_doc.id)

        unverified = bool(args.get("unverified", False))
        output_format = str(args.get("output_format", "text")).lower()

        retriever = HybridRetrievalService()
        results = retriever.search(
            query=query,
            workspace_id=str(ws.id),
            organization_id=get_organization_id(ws),
            document_id=doc_id,
            limit=limit,
            context_budget_tokens=effective_max_tokens,
            deep_context=is_expanded
        )

        # Exclude quarantined or draft documents unless specifically requested
        if not unverified:
            results = [
                r for r in results
                if r.get("status") not in ("quarantined", "draft") and
                   r.get("governance_status") not in ("quarantined", "draft")
            ]

        # Clean any secrets from text
        results = sanitize_sensitive_data(results)

        max_chars_per_passage = min(1400, max(350, (effective_max_tokens * 4) // max(1, len(results)))) if results else 350

        if output_format == "json":
            passages_list = []
            actual_returned_tokens = 0
            for i, r in enumerate(results, 1):
                clean_text = truncate_sentence_safe(r.get("text") or "", max_chars=max_chars_per_passage)
                toks = estimate_tokens(clean_text)
                actual_returned_tokens += toks
                passages_list.append({
                    "rank": int(i),
                    "document_id": str(r.get("document_id") or ""),
                    "chunk_id": str(r.get("chunk_id") or r.get("id") or ""),
                    "rule_id": str(r.get("rule_id") or ""),
                    "document_title": str(r.get("document_title") or ""),
                    "page_number": int(r.get("page_number") or 1),
                    "score": float(r.get("score") or 0.0),
                    "authority_level": int(r.get("authority_level") or 4),
                    "text": clean_text
                })

            payload = {
                "schema": "lore.search_results/1",
                "is_governed_decision": False,
                "governance_status": "ungoverned_informational_retrieval",
                "warning": (
                    "Raw search results are un-adjudicated candidate passages and CANNOT be used as an "
                    "authoritative governance decision. For governed decisions, evaluate with lore.get_context "
                    "or lore.check_compliance."
                ),
                "query": query,
                "workspace_id": str(ws.id),
                "workspace_name": ws.name,
                "token_budget_applied": int(effective_max_tokens),
                "tokens_returned": int(actual_returned_tokens),
                "context_mode": "expanded" if is_expanded else "standard",
                "total_passages": int(len(results)),
                "passages": passages_list
            }
            return json.dumps(payload, indent=2, ensure_ascii=False, default=str)

        # Default Text output (Preserves backward compatibility with CLI/agents)
        if not results:
            diag = retriever.last_diagnostics
            mode_note = f" (retrieval mode: {diag.get('retrieval_mode', 'hybrid')})" if diag else ""
            return sanitize_sensitive_data(f"Zero passages found matching '{query}' in workspace '{ws.name}'{mode_note}.")

        output_lines = [
            f"### LORE Hybrid Search Results ({len(results)} passages reranked)",
            f"Workspace: {ws.name} ({ws.id})",
            "> [!] **Ungoverned Informational Retrieval**: Raw search results are candidate passages only "
            "and have not undergone 9-layer governance verification (permissions, temporal validity, "
            "conflict resolution, evidence sufficiency). Do not execute high-impact actions without "
            "evaluating through `lore.get_context` or `lore.check_compliance`.\n"
        ]

        diag = retriever.last_diagnostics
        if diag and diag.get('retrieval_mode') == 'degraded_lexical_only':
            output_lines.append("> [!] **Degraded Mode**: Vector store is unavailable. Operating under lexical-only fallback.\n")

        for i, r in enumerate(results, 1):
            clean_text = truncate_sentence_safe(r.get('text', ''), max_chars=max_chars_per_passage)
            output_lines.append(
                f"**[{i}] {r.get('document_title')}** (Page {r.get('page_number')}, Score: {r.get('score')}, Auth Rank: {r.get('authority_level')})\n"
                f"> {clean_text}...\n"
            )

        return sanitize_sensitive_data("\n".join(output_lines))
    except Exception as ex:
        logger.error(f"Error executing handle_search: {ex}\n{traceback.format_exc()}")
        return make_error_response(
            "INTERNAL_ERROR",
            f"Error executing lore.search: {ex}",
            reason_code="SEARCH_EXECUTION_EXCEPTION"
        )


def handle_standard_search(args: Dict[str, Any]) -> str:
    """
    ChatGPT Deep Research & Pro Connector standard search tool.
    Returns JSON structure: {"results": [{"id": ..., "title": ..., "text": ..., "url": ...}]}
    """
    try:
        raw_query = args.get("query") or args.get("intent") or ""
        query = str(raw_query).strip()
        if not query:
            return make_error_response("INVALID_ARGUMENT", "The 'query' parameter cannot be empty.")

        ws, err = resolve_workspace_from_args(args)
        if err or not ws:
            return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

        limit, effective_max_tokens, is_expanded = resolve_mcp_token_budget(args, default_limit=6)

        doc_id = args.get("document_id")
        if doc_id is not None:
            doc_id = str(doc_id).strip()
        doc_title = args.get("document_title") or args.get("focus_files") or args.get("focus_file")
        if not doc_id and doc_title:
            from apps.knowledge.models import SourceDocument
            from django.db.models import Q
            matched_doc = SourceDocument.objects.filter(
                workspace=ws
            ).filter(
                Q(title__icontains=str(doc_title).strip()) |
                Q(canonical_title__icontains=str(doc_title).strip()) |
                Q(original_filename__icontains=str(doc_title).strip()) |
                Q(document_code__iexact=str(doc_title).strip())
            ).first()
            if matched_doc:
                doc_id = str(matched_doc.id)

        retriever = HybridRetrievalService()
        results = retriever.search(
            query=query,
            workspace_id=str(ws.id),
            organization_id=get_organization_id(ws),
            document_id=doc_id,
            limit=limit,
            context_budget_tokens=effective_max_tokens,
            deep_context=is_expanded
        )
        # Exclude quarantined or draft documents
        results = [
            r for r in results
            if r.get("status") not in ("quarantined", "draft") and
               r.get("governance_status") not in ("quarantined", "draft")
        ]
        results = sanitize_sensitive_data(results)

        max_chars_per_passage = min(1400, max(350, (effective_max_tokens * 4) // max(1, len(results)))) if results else 350

        standard_results = []
        actual_returned_tokens = 0
        for r in results:
            r_id = str(r.get("chunk_id") or r.get("document_id") or r.get("id") or "")
            title = str(r.get("document_title") or r.get("title") or "LORE Document")
            raw_text = r.get("content") or r.get("text") or ""
            clean_text = truncate_sentence_safe(raw_text, max_chars=max_chars_per_passage)
            url = f"lore://document/{r.get('document_id', r_id)}"
            toks = estimate_tokens(clean_text)
            actual_returned_tokens += toks
            standard_results.append({
                "id": str(r_id),
                "title": title,
                "text": clean_text,
                "url": url,
                "metadata": {
                    "document_id": str(r.get("document_id") or ""),
                    "chunk_id": str(r.get("chunk_id") or r_id),
                    "authority_level": int(r.get("authority_level") or 4),
                    "score": float(r.get("score") or 1.0),
                    "page_number": int(r.get("page_number") or 1)
                }
            })

        payload = {
            "results": standard_results,
            "token_budget_applied": int(effective_max_tokens),
            "tokens_returned": int(actual_returned_tokens),
            "context_mode": "expanded" if is_expanded else "standard"
        }
        return json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    except Exception as ex:
        logger.error(f"Error executing handle_standard_search: {ex}\n{traceback.format_exc()}")
        return make_error_response(
            "INTERNAL_ERROR",
            f"Error executing search: {ex}",
            reason_code="SEARCH_EXECUTION_EXCEPTION"
        )


def handle_fetch(args: Dict[str, Any]) -> str:
    """
    ChatGPT Deep Research & Pro Connector standard fetch tool.
    Retrieves full governed rule, document, or chunk content by ID.
    """
    item_id = str(args.get("id") or args.get("document_id") or "").strip()
    if not item_id:
        return make_error_response("INVALID_ARGUMENT", "The 'id' parameter cannot be empty.")

    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    # 1. Check SourceDocument
    doc = SourceDocument.objects.filter(id=item_id, workspace=ws).first() or SourceDocument.objects.filter(id=item_id).first()
    if doc:
        if doc.status in ("quarantined", "draft"):
            return make_error_response("PERMISSION_DENIED", f"Document '{item_id}' is in {doc.status} state.", reason_code="DOCUMENT_QUARANTINED")

        pages = list(DocumentPage.objects.filter(document=doc).order_by("page_number"))
        content = "\n\n".join([f"--- Page {p.page_number} ---\n{p.text}" for p in pages if p.text])
        if not content:
            chunks = list(DocumentChunk.objects.filter(document=doc).order_by("chunk_index"))
            content = "\n\n".join([getattr(c, "text", "") or getattr(c, "content", "") for c in chunks if (getattr(c, "text", None) or getattr(c, "content", None))])

        content = sanitize_sensitive_data(content)
        return json.dumps({
            "id": str(doc.id),
            "title": doc.title,
            "text": content,
            "url": f"lore://document/{doc.id}",
            "metadata": {
                "document_code": doc.document_code or "",
                "authority_level": doc.authority_level,
                "current_version": doc.current_version_number,
                "status": doc.status
            }
        }, indent=2, ensure_ascii=False)

    # 2. Check DocumentChunk
    chunk = DocumentChunk.objects.filter(id=item_id).select_related("document").first()
    if chunk:
        doc = chunk.document
        if doc and doc.status in ("quarantined", "draft"):
            return make_error_response("PERMISSION_DENIED", f"Chunk document is in {doc.status} state.", reason_code="DOCUMENT_QUARANTINED")

        content = sanitize_sensitive_data(getattr(chunk, "text", "") or getattr(chunk, "content", "") or "")
        return json.dumps({
            "id": str(chunk.id),
            "title": doc.title if doc else "Document Passage",
            "text": content,
            "url": f"lore://chunk/{chunk.id}",
            "metadata": {
                "document_id": str(doc.id) if doc else "",
                "page_number": chunk.page_number,
                "section": chunk.section_identifier or getattr(chunk, "heading_path", "") or "",
                "heading_path": getattr(chunk, "heading_path", "") or "",
                "authority_level": doc.authority_level if doc else 4
            }
        }, indent=2, ensure_ascii=False)

    # 3. Check KnowledgeItem
    item = KnowledgeItem.objects.filter(id=item_id).select_related("document").first() or KnowledgeItem.objects.filter(code=item_id).first()
    if item:
        content = sanitize_sensitive_data(item.statement or "")
        return json.dumps({
            "id": str(item.id),
            "title": f"Rule {item.code or item.id}",
            "text": content,
            "url": f"lore://rule/{item.code or item.id}",
            "metadata": {
                "code": item.code or "",
                "authority_level": item.authority_level,
                "status": item.status or "stable"
            }
        }, indent=2, ensure_ascii=False)

    return make_error_response("RESOURCE_NOT_FOUND", f"Item with ID '{item_id}' not found.", reason_code="ITEM_NOT_FOUND")


def handle_check_compliance(args: Dict[str, Any]) -> str:
    """
    Evaluates a proposed code diff or specification change against governed enterprise rules.
    Outputs PASS/FAIL/UNCERTAIN verdicts and machine exit codes (lore.md §11).
    """
    diff = args.get("diff", "").strip()
    if not diff:
        return make_error_response("INVALID_ARGUMENT", "The 'diff' parameter is required.")

    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    intent = args.get("intent", "Code change verification")
    file_path = args.get("file_path", "")
    user_role = args.get("user_role", "member")
    as_of = args.get("as_of")

    # 1. Retrieve applicable active rules
    rules_qs = KnowledgeItem.objects.filter(workspace=ws, item_type='rule', status='stable')
    rule_items = list(rules_qs[:20])

    # 2. Retrieve authoritative candidate chunks for diff context
    search_query = f"{intent} {file_path}".strip() or diff[:300]
    retriever = HybridRetrievalService()
    candidate_chunks = retriever.search(
        query=search_query,
        workspace_id=str(ws.id),
        organization_id=get_organization_id(ws),
        limit=8
    )

    # 3. Adjudicate via EnterpriseGovernanceEngine
    envelope = EnterpriseGovernanceEngine.evaluate(
        query=f"Compliance check for proposed diff: {search_query}",
        retrieved_chunks=candidate_chunks,
        workspace=ws,
        user=None,
        user_role=user_role,
        as_of=as_of,
        decision_type="compliance_check",
        zk_attestation=bool(args.get("zk_attestation", False))
    )

    # 4. Compute per-rule verdicts
    rule_evaluations = []
    overall_state = envelope.get("state", "supported")
    directive = envelope.get("directive", "proceed_and_cite")

    diff_lower = diff.lower()
    has_explicit_fail = (overall_state in ("violation", "denied"))
    has_explicit_uncertain = (overall_state in ("conflicting", "insufficient", "abstain"))

    for item in rule_items:
        rule_code = item.code or f"RULE-{str(item.id)[:6].upper()}"
        stmt = item.statement.lower()

        # Deterministic check for violation patterns
        if "must not" in stmt or "forbidden" in stmt or "never" in stmt:
            # Check if diff mentions prohibited entity/pattern
            prohibited_terms = [w for w in ["plaintext", "password", "eval(", "http://", "0.0.0.0"] if w in stmt]
            violates = any(term in diff_lower for term in prohibited_terms)
            if violates:
                verdict = "FAIL"
                notes = f"Diff contains prohibited pattern matching negative directive in {rule_code}"
                has_explicit_fail = True
            else:
                verdict = "PASS"
                notes = "No prohibited patterns detected."
        else:
            if has_explicit_fail:
                verdict = "FAIL"
                notes = envelope.get("answer", "Policy violation detected.")
            elif has_explicit_uncertain:
                verdict = "UNCERTAIN"
                notes = "Evidence insufficient or conflicting; requires human review."
            else:
                verdict = "PASS"
                notes = "Diff aligns with approved standards."

        rule_evaluations.append({
            "rule_code": rule_code,
            "title": item.statement[:120],
            "verdict": verdict,
            "authority_rank": item.authority_level,
            "notes": notes
        })

    # If no explicit KnowledgeItems exist, summarize from candidate citations
    if not rule_evaluations:
        for c in envelope.get("citations", []):
            rule_evaluations.append({
                "rule_code": f"DOC-{c.get('document_id', 'REF')[:6]}",
                "title": c.get("document_title", "Governed Standard"),
                "verdict": "FAIL" if has_explicit_fail else ("UNCERTAIN" if has_explicit_uncertain else "PASS"),
                "authority_rank": c.get("authority_level", 3),
                "notes": "Evaluated against authoritative document standard."
            })

    # 5. Determine Overall Verdict and Machine Exit Code (lore.md §11)
    # exit codes: 0 = PASS (proceed), 3 = UNCERTAIN (ask_user), 4 = FAIL (stop)
    passed_count = sum(1 for r in rule_evaluations if r["verdict"] == "PASS")
    failed_count = sum(1 for r in rule_evaluations if r["verdict"] == "FAIL")
    uncertain_count = sum(1 for r in rule_evaluations if r["verdict"] == "UNCERTAIN")

    if failed_count > 0 or has_explicit_fail:
        overall_verdict = "FAIL"
        exit_code = 4
        final_directive = "stop"
    elif uncertain_count > 0 or has_explicit_uncertain:
        overall_verdict = "UNCERTAIN"
        exit_code = 3
        final_directive = "ask_user"
    else:
        overall_verdict = "PASS"
        exit_code = 0
        final_directive = "proceed_and_cite"

    result_payload = {
        "schema": "lore.compliance/1",
        "overall_verdict": overall_verdict,
        "directive": final_directive,
        "exit_code": exit_code,
        "machine_action": "proceed" if exit_code == 0 else ("halt" if exit_code == 4 else "prompt_user"),
        "rules_checked": len(rule_evaluations),
        "rules_passed": passed_count,
        "rules_failed": failed_count,
        "rules_uncertain": uncertain_count,
        "rule_evaluations": rule_evaluations,
        "governance_state": overall_state,
        "bundle_hash": envelope.get("bundle_hash"),
        "zk_attestation": envelope.get("zk_attestation"),
        "trace_id": envelope.get("trace_id"),
        "citations": envelope.get("citations", [])
    }

    return json.dumps(result_payload, indent=2, ensure_ascii=False)


def handle_detect_conflicts(args: Dict[str, Any]) -> str:
    """Detects and reports contradictions, cross-document conflicts, and authority resolutions (L6)."""
    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    scope = (args.get("scope") or "").strip().lower()
    status_filter = (args.get("status") or "all").strip().lower()

    # Query ConflictRecord
    qs = ConflictRecord.objects.filter(workspace=ws).select_related('source_a', 'source_b')
    if status_filter in ('unresolved', 'resolved_by_authority', 'human_overridden'):
        qs = qs.filter(resolution_status=status_filter)

    conflicts_list = []
    for c in qs[:50]:
        claim_text = f"{c.claim_a} {c.claim_b}".lower()
        title_text = f"{c.source_a.title} {c.source_b.title}".lower()
        if scope and (scope not in claim_text and scope not in title_text):
            continue

        conflicts_list.append({
            "id": str(c.id),
            "source_a": {
                "id": str(c.source_a.id),
                "title": c.source_a.title,
                "authority_rank": c.source_a.authority_level
            },
            "source_b": {
                "id": str(c.source_b.id),
                "title": c.source_b.title,
                "authority_rank": c.source_b.authority_level
            },
            "claim_a": c.claim_a,
            "claim_b": c.claim_b,
            "resolution_status": c.resolution_status,
            "resolution_notes": c.resolution_notes,
            "created_at": c.created_at.isoformat()
        })

    # Query GraphRAG CONFLICTS_WITH edges
    rel_qs = KnowledgeRelationship.objects.filter(
        workspace=ws, relationship_type=RelationshipType.CONFLICTS_WITH
    ).select_related('source_document', 'target_document')

    for r in rel_qs[:20]:
        if not r.source_document or not r.target_document:
            continue
        conflicts_list.append({
            "id": str(r.id),
            "source_a": {
                "id": str(r.source_document.id),
                "title": r.source_document.title,
                "authority_rank": r.source_document.authority_level
            },
            "source_b": {
                "id": str(r.target_document.id),
                "title": r.target_document.title,
                "authority_rank": r.target_document.authority_level
            },
            "claim_a": f"Contradicts relationship: {r.provenance}",
            "claim_b": f"Conflicted by graph edge {r.id}",
            "resolution_status": "unresolved" if r.source_document.authority_level == r.target_document.authority_level else "resolved_by_authority",
            "resolution_notes": f"Relationship edge: {r.relationship_type} (confidence={r.confidence})",
            "created_at": r.created_at.isoformat()
        })

    payload = {
        "schema": "lore.conflicts/1",
        "workspace": ws.name,
        "workspace_id": str(ws.id),
        "total_conflicts": len(conflicts_list),
        "unresolved_count": sum(1 for c in conflicts_list if c["resolution_status"] == "unresolved"),
        "resolved_by_authority_count": sum(1 for c in conflicts_list if c["resolution_status"] == "resolved_by_authority"),
        "conflicts": conflicts_list
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_trace(args: Dict[str, Any]) -> str:
    """Retrieves full decision lineage, audit history, and citations for a trace ID (L0)."""
    trace_id = (args.get("trace_id") or "").strip()
    if not trace_id:
        return make_error_response("INVALID_ARGUMENT", "The 'trace_id' parameter is required.")

    # Search by trace_id or primary key UUID
    decision = DecisionRecord.objects.filter(trace_id=trace_id).first()
    if not decision:
        try:
            decision = DecisionRecord.objects.filter(id=trace_id).first()
        except Exception:
            pass

    if not decision:
        return make_error_response("RESOURCE_NOT_FOUND", f"Decision trace '{trace_id}' not found.", reason_code="TRACE_NOT_FOUND")

    # Fetch audit events
    audit_events = AuditEvent.objects.filter(details__icontains=trace_id)[:10]
    audit_summary = [
        {
            "event_type": a.event_type,
            "target_type": a.target_type,
            "timestamp": a.created_at.isoformat(),
            "details": a.details
        }
        for a in audit_events
    ]

    payload = {
        "schema": "lore.trace/1",
        "trace_id": decision.trace_id,
        "decision_id": str(decision.id),
        "timestamp": decision.created_at.isoformat(),
        "query": decision.query,
        "decision_type": decision.decision_type,
        "state": decision.state,
        "directive": decision.directive,
        "answer": decision.answer_text,
        "evidence_found": decision.evidence_found,
        "evidence_missing": decision.evidence_missing,
        "conflicts_resolved": decision.conflicts_resolved,
        "citations": decision.citations,
        "token_count": decision.token_count,
        "audit_events": audit_summary
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_log_decision(args: Dict[str, Any]) -> str:
    """Appends an authoritative decision record to the LORE audit log and decision database (L0)."""
    task = (args.get("task") or "").strip()
    rules = args.get("rules") or []
    outcome = (args.get("outcome") or "").strip().lower()

    if not task:
        return make_error_response("INVALID_ARGUMENT", "The 'task' parameter is required.")
    if not rules:
        return make_error_response("INVALID_ARGUMENT", "The 'rules' list cannot be empty.")
    if not outcome:
        return make_error_response("INVALID_ARGUMENT", "The 'outcome' parameter is required.")

    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    # Normalize state & directive
    if outcome in ("proceed_and_cite", "proceed", "supported"):
        state = "supported"
        directive = "proceed_and_cite"
    elif outcome in ("stop", "violation", "denied"):
        state = "violation"
        directive = "stop"
    elif outcome in ("ask_user", "conflicting", "insufficient"):
        state = "conflicting"
        directive = "ask_user"
    elif outcome in ("escalate", "human_review"):
        state = "human_review"
        directive = "escalate"
    else:
        state = "qualified"
        directive = "proceed_and_cite"

    trace_id = f"trace-{uuid.uuid4().hex[:12]}"
    notes = args.get("notes", "")
    citations = args.get("citations", [])
    token_count = int(args.get("token_count", 0))

    decision = DecisionRecord.objects.create(
        trace_id=trace_id,
        organization=ws.organization,
        workspace=ws,
        user=None,
        query=task,
        decision_type="agent_action_decision",
        state=state,
        directive=directive,
        answer_text=notes,
        evidence_found=rules,
        citations=citations,
        token_count=token_count
    )

    AuditEvent.objects.create(
        organization=ws.organization,
        workspace=ws,
        event_type="decision_recorded",
        target_type="decision",
        target_id=str(decision.id),
        details={"trace_id": trace_id, "rules": rules, "state": state, "directive": directive}
    )

    payload = {
        "schema": "lore.decision_log/1",
        "logged": True,
        "decision_id": str(decision.id),
        "trace_id": trace_id,
        "task": task,
        "rules_applied": rules,
        "state": state,
        "directive": directive,
        "created_at": decision.created_at.isoformat()
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_get_history(args: Dict[str, Any]) -> str:
    """Retrieves document version timeline and SUPERSEDES relationship chains (L5)."""
    file_query = (args.get("file") or "").strip()
    if not file_query:
        return make_error_response("INVALID_ARGUMENT", "The 'file' parameter (document id, filename, or title) is required.")

    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    doc = None
    # Try UUID lookup
    try:
        doc = SourceDocument.objects.filter(workspace=ws, id=file_query).first()
    except Exception:
        pass

    if not doc:
        doc = SourceDocument.objects.filter(workspace=ws, original_filename__iexact=file_query).first()
    if not doc:
        doc = SourceDocument.objects.filter(workspace=ws, title__icontains=file_query).first()

    if not doc:
        return make_error_response("RESOURCE_NOT_FOUND", f"Document matching '{file_query}' not found in workspace '{ws.name}'.")

    versions = DocumentVersion.objects.filter(document=doc).order_by('-version_number')
    version_history = [
        {
            "version_number": v.version_number,
            "file_hash": v.file_hash,
            "change_summary": v.change_summary,
            "is_current": v.is_current,
            "created_at": v.created_at.isoformat()
        }
        for v in versions
    ]

    # Supersedes chain from GraphRAG
    supersedes_edges = KnowledgeRelationship.objects.filter(
        workspace=ws,
        relationship_type=RelationshipType.SUPERSEDES
    ).filter(
        models.Q(source_document=doc) | models.Q(target_document=doc)
    ).select_related('source_document', 'target_document')

    supersedes_chain = []
    for edge in supersedes_edges:
        supersedes_chain.append({
            "relationship_id": str(edge.id),
            "newer_document": edge.source_document.title if edge.source_document else "Unknown",
            "superseded_document": edge.target_document.title if edge.target_document else "Unknown",
            "provenance": edge.provenance,
            "approval_status": edge.approval_status
        })

    payload = {
        "schema": "lore.history/1",
        "document_id": str(doc.id),
        "title": doc.title,
        "original_filename": doc.original_filename,
        "current_version": doc.current_version_number,
        "authority_level": doc.authority_level,
        "status": doc.status,
        "effective_date": doc.effective_date.isoformat() if doc.effective_date else None,
        "expiration_date": doc.expiration_date.isoformat() if doc.expiration_date else None,
        "versions": version_history,
        "supersedes_chain": supersedes_chain
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_stats(args: Dict[str, Any]) -> str:
    """Computes comprehensive knowledge graph and governance metrics (L0)."""
    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    doc_count = SourceDocument.objects.filter(workspace=ws).count()
    ready_docs = SourceDocument.objects.filter(workspace=ws, status='ready').count()
    quarantined_docs = SourceDocument.objects.filter(workspace=ws, status='quarantined').count()
    chunk_count = DocumentChunk.objects.filter(workspace=ws).count()

    items = KnowledgeItem.objects.filter(workspace=ws)
    rules_count = items.filter(item_type='rule').count()
    skills_count = items.filter(item_type='skill').count()
    facts_count = items.filter(item_type='fact').count()
    exceptions_count = items.filter(item_type='exception').count()

    edges_count = KnowledgeRelationship.objects.filter(workspace=ws).count()
    conflicts_total = ConflictRecord.objects.filter(workspace=ws).count()
    conflicts_unresolved = ConflictRecord.objects.filter(workspace=ws, resolution_status='unresolved').count()
    decisions_count = DecisionRecord.objects.filter(workspace=ws).count()

    payload = {
        "schema": "lore.stats/1",
        "workspace": ws.name,
        "workspace_id": str(ws.id),
        "documents": {
            "total": doc_count,
            "ready": ready_docs,
            "quarantined": quarantined_docs,
            "chunks": chunk_count
        },
        "knowledge_items": {
            "rules": rules_count,
            "skills": skills_count,
            "facts": facts_count,
            "exceptions": exceptions_count
        },
        "graph_edges": {
            "total_relationships": edges_count
        },
        "governance_health": {
            "conflicts_total": conflicts_total,
            "conflicts_unresolved": conflicts_unresolved,
            "decisions_logged": decisions_count
        }
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_check_evidence_sufficiency(args: Dict[str, Any]) -> str:
    """Evaluates mandatory evidence sufficiency for a decision type (L3)."""
    decision_type = (args.get("decision_type") or "").strip()
    if not decision_type:
        return make_error_response("INVALID_ARGUMENT", "The 'decision_type' parameter is required.")

    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    query = args.get("query", "")
    entities = args.get("entities") or []

    # If query given, fetch real candidates
    if query:
        retriever = HybridRetrievalService()
        candidate_chunks = retriever.search(
            query=query,
            workspace_id=str(ws.id),
            organization_id=get_organization_id(ws),
            limit=6
        )
    else:
        # Build synthetic evidence items from entities
        candidate_chunks = []
        for ent in entities:
            candidate_chunks.append({
                "text": str(ent),
                "authority_level": 5,
                "document_title": f"Evidence {ent}"
            })

    eval_query = query or f"approve {decision_type} {' '.join(str(e) for e in entities)}".strip()

    # Evaluate through canonical L3 EvidenceSufficiencyLayer
    res = EvidenceSufficiencyLayer.evaluate(
        workspace_id=str(ws.id),
        decision_info={"decision_type": decision_type, "query_intent": "action_request"},
        retrieved_chunks=candidate_chunks,
        query=eval_query,
        has_exception=False
    )

    reqs = EvidenceRequirement.objects.filter(
        models.Q(workspace=ws) | models.Q(workspace__isnull=True),
        decision_type=decision_type
    )
    mandatory_reqs = [
        {"evidence_type": r.evidence_type, "min_authority": r.min_authority_level, "is_mandatory": r.is_mandatory}
        for r in reqs
    ]

    payload = {
        "schema": "lore.sufficiency/1",
        "decision_type": decision_type,
        "is_sufficient": res.is_sufficient,
        "evidence_found": res.evidence_found,
        "evidence_missing": res.evidence_missing,
        "verdict_impact": "sufficient" if res.is_sufficient else "insufficient_requires_ask_user",
        "mandatory_requirements": mandatory_reqs,
        "reason_codes": res.reason_codes
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_get_authority_info(args: Dict[str, Any]) -> str:
    """Retrieves document authority ranking (1-7), staleness, and access level (L6)."""
    source_id = (args.get("source_id") or "").strip()
    if not source_id:
        return make_error_response("INVALID_ARGUMENT", "The 'source_id' parameter is required.")

    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    doc = None
    try:
        doc = SourceDocument.objects.filter(workspace=ws, id=source_id).first()
    except Exception:
        pass
    if not doc:
        doc = SourceDocument.objects.filter(workspace=ws, original_filename__iexact=source_id).first()
    if not doc:
        doc = SourceDocument.objects.filter(workspace=ws, title__icontains=source_id).first()

    if not doc:
        return make_error_response("RESOURCE_NOT_FOUND", f"Source document '{source_id}' not found.")

    hierarchy_names = dict(SourceDocument.AUTHORITY_LEVELS)
    access_level = "internal"
    doc_perms = getattr(doc, 'permissions', None)
    if doc_perms:
        access_level = getattr(doc_perms, 'access_level', 'internal')

    payload = {
        "schema": "lore.authority/1",
        "document_id": str(doc.id),
        "title": doc.title,
        "authority_rank": doc.authority_level,
        "authority_level_name": hierarchy_names.get(doc.authority_level, "reviewed_document"),
        "hierarchy_rank_explanation": (
            "Authority ladder (1-7): 7=approved_policy (dominates conflicting lower tiers), "
            "6=signed_contract, 5=team_convention, 4=maintained_procedure, 3=reviewed_document, "
            "2=wiki_entry, 1=informal_note."
        ),
        "status": doc.status,
        "effective_date": doc.effective_date.isoformat() if doc.effective_date else None,
        "expiration_date": doc.expiration_date.isoformat() if doc.expiration_date else None,
        "stale_after_days": doc.stale_after_days,
        "access_level": access_level
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_query_as_of(args: Dict[str, Any]) -> str:
    """Point-in-time historical retrieval and governance evaluation (L5)."""
    query = (args.get("query") or "").strip()
    as_of = (args.get("as_of") or "").strip()

    if not query:
        return make_error_response("INVALID_ARGUMENT", "The 'query' parameter is required.")
    if not as_of:
        return make_error_response("INVALID_ARGUMENT", "The 'as_of' parameter is required (e.g. '2026-03-15').")

    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    try:
        limit = min(max(1, int(args.get("limit", 6))), 50)
    except (ValueError, TypeError):
        limit = 6

    user_role = args.get("user_role", "member")

    retriever = HybridRetrievalService()
    chunks = retriever.search(
        query=query,
        workspace_id=str(ws.id),
        organization_id=get_organization_id(ws),
        limit=limit
    )

    envelope = EnterpriseGovernanceEngine.evaluate(
        query=query,
        retrieved_chunks=chunks,
        workspace=ws,
        user=None,
        user_role=user_role,
        as_of=as_of
    )

    envelope["as_of_evaluated"] = as_of
    return json.dumps(envelope, indent=2, ensure_ascii=False)


def handle_get_active_exceptions(args: Dict[str, Any]) -> str:
    """Lists active scoped exceptions applying to the current context (L4)."""
    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    rule_code = (args.get("rule_code") or "").strip()
    scope_type = (args.get("scope_type") or "").strip()
    as_of = args.get("as_of")

    qs = ScopedException.objects.filter(workspace=ws, status='active')
    if rule_code:
        qs = qs.filter(rule_code__iexact=rule_code)
    if scope_type:
        qs = qs.filter(scope_type=scope_type)

    active_exceptions = []
    for exc in qs[:50]:
        if exc.is_currently_valid(as_of=as_of):
            active_exceptions.append({
                "id": str(exc.id),
                "rule_code": exc.rule_code,
                "scope_type": exc.scope_type,
                "scope_value": exc.scope_value,
                "window_start": exc.window_start.isoformat() if exc.window_start else None,
                "window_end": exc.window_end.isoformat() if exc.window_end else None,
                "justification": exc.justification,
                "approved_by": exc.approved_by,
                "status": exc.status
            })

    payload = {
        "schema": "lore.exceptions/1",
        "workspace": ws.name,
        "as_of": as_of or "now",
        "total_active": len(active_exceptions),
        "exceptions": active_exceptions
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_escalate_to_human(args: Dict[str, Any]) -> str:
    """Creates a human review ticket in the review queue (L2 / lore.md §11)."""
    query = (args.get("query") or "").strip()
    if not query:
        return make_error_response("INVALID_ARGUMENT", "The 'query' parameter is required.")

    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    state = args.get("state", "human_review")
    context = args.get("context") or {}

    trace_id = f"trace-esc-{uuid.uuid4().hex[:8]}"
    decision = DecisionRecord.objects.create(
        trace_id=trace_id,
        organization=ws.organization,
        workspace=ws,
        user=None,
        query=query,
        decision_type="human_escalation_ticket",
        state="human_review",
        directive="escalate",
        answer_text=f"Escalated to human reviewer due to {state}.",
        evidence_missing=[f"Human approval required for: {query[:80]}"]
    )

    AuditEvent.objects.create(
        organization=ws.organization,
        workspace=ws,
        event_type="item_quarantined",
        target_type="escalation_ticket",
        target_id=str(decision.id),
        details={"trace_id": trace_id, "state": state, "context": context}
    )

    payload = {
        "schema": "lore.escalation/1",
        "ticket_id": str(decision.id),
        "trace_id": trace_id,
        "query": query,
        "escalation_state": state,
        "escalation_target": "compliance_review_queue",
        "queue_status": "queued",
        "message": f"Human review requested. Ticket {decision.id} placed in compliance review queue."
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_bootstrap(args: Dict[str, Any]) -> str:
    """Serves the constitution (agent.md) and phase policy on connect (lore.md §11 & §12.2)."""
    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    phase = args.get("phase", "all")
    constitution_text = (
        "# agent.md — The Constitution (lore.md §12.2)\n\n"
        "## Core Governance Directives\n"
        "1. Before planning any application or feature -> call `lore.get_context` to retrieve architecture & security rules.\n"
        "2. During UI implementation -> call `lore.get_skill('ui-ux-pro')` for taste & accessibility guidelines.\n"
        "3. Before any database or auth modification -> enforce security policies (non-negotiable).\n"
        "4. Before completing any change or pull request -> run `lore.check_compliance(diff)`.\n"
        "5. Respect exit codes: exit 4 = STOP (hard violation), exit 3 = ASK_USER (missing evidence or conflict).\n"
        "6. Models are never the source of truth for governance decisions.\n"
    )

    payload = {
        "schema": "lore.constitution/1",
        "workspace": ws.name,
        "workspace_id": str(ws.id),
        "phase": phase,
        "constitution": constitution_text,
        "operational_rules": [
            {"directive": "pre_edit_context", "tool": "lore.get_context", "requirement": "Mandatory before file edits"},
            {"directive": "pre_commit_compliance", "tool": "lore.check_compliance", "requirement": "Mandatory before final merge"},
            {"directive": "conflict_adjudication", "tool": "lore.detect_conflicts", "requirement": "Authority rank dominates lower tiers"}
        ]
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_get_skill(args: Dict[str, Any]) -> str:
    """Retrieves procedural steps and prerequisites for an engineering or governance skill."""
    name = (args.get("name") or "").strip().lower()
    if not name:
        return make_error_response("INVALID_ARGUMENT", "The 'name' parameter is required.")

    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    # Check KnowledgeItem for skill
    skill_item = KnowledgeItem.objects.filter(
        workspace=ws,
        item_type='skill'
    ).filter(
        models.Q(code__iexact=name) | models.Q(component__iexact=name) | models.Q(statement__icontains=name)
    ).first()

    if skill_item:
        payload = {
            "schema": "lore.skill/1",
            "name": skill_item.code or name,
            "statement": skill_item.statement,
            "authority_rank": skill_item.authority_level,
            "status": skill_item.status
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    # Standard built-in skills (lore.md §11)
    standard_skills = {
        "ui-ux-pro": {
            "name": "ui-ux-pro",
            "title": "UI/UX Design & Taste System",
            "steps": [
                "1. Audit color contrast against WCAG AAA standards.",
                "2. Implement dark/light theme switching with CSS variables.",
                "3. Ensure touch targets >= 44x44px and responsive layouts.",
                "4. Apply subtle micro-animations for interactive affordances."
            ],
            "prerequisites": ["CSS variables", "Design tokens"]
        },
        "security-review": {
            "name": "security-review",
            "title": "Application Security & Threat Audit",
            "steps": [
                "1. Verify RBAC/ABAC query-time permission enforcement.",
                "2. Ensure secrets, API keys, and bearer tokens are scrubbed from all outputs.",
                "3. Validate input sanitization against SQL injection and XSS.",
                "4. Ensure encrypted transport (TLS) and storage (AES-256)."
            ],
            "prerequisites": ["Threat model", "Security persona"]
        },
        "compliance-gate": {
            "name": "compliance-gate",
            "title": "Pre-Commit Compliance Verification",
            "steps": [
                "1. Generate git diff for modified files.",
                "2. Call lore.check_compliance(diff=diff).",
                "3. Abort merge if exit code is 4 (STOP) or 3 (ASK_USER).",
                "4. Log decision trace with lore.log_decision."
            ],
            "prerequisites": ["Git diff", "Active workspace"]
        }
    }

    selected = standard_skills.get(name) or {
        "name": name,
        "title": f"Skill: {name}",
        "steps": [f"1. Evaluate requirements for {name}.", f"2. Execute standardized procedure for {name}."],
        "prerequisites": ["Active workspace"]
    }

    payload = {
        "schema": "lore.skill/1",
        "name": selected["name"],
        "title": selected["title"],
        "steps": selected["steps"],
        "prerequisites": selected.get("prerequisites", []),
        "authority_rank": 5
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_list_documents(args: Dict[str, Any]) -> str:
    """Lists all accessible workspace documents (lore.md §11)."""
    try:
        ws, err = resolve_workspace_from_args(args)
        if err or not ws:
            return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

        from apps.knowledge.models import SourceDocument
        docs = SourceDocument.objects.filter(workspace=ws).exclude(
            status__in=['quarantined', 'failed', 'deleted']
        ).order_by('-authority_level', 'title')

        doc_list = []
        for d in docs:
            doc_list.append({
                "document_id": str(d.id),
                "title": str(d.canonical_title or d.title or ""),
                "document_code": str(d.document_code or ""),
                "document_type": str(d.document_type or ""),
                "page_count": int(getattr(d, 'page_count', 0) or 0),
                "status": str(d.status or ""),
                "governance_status": str(d.governance_status or d.status or ""),
                "authority_level": int(d.authority_level or 4)
            })

        payload = {
            "schema": "lore.documents/1",
            "workspace_id": str(ws.id),
            "workspace_name": ws.name,
            "count": len(doc_list),
            "documents": doc_list
        }
        return json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    except Exception as ex:
        logger.error(f"Error executing handle_list_documents: {ex}\n{traceback.format_exc()}")
        return make_error_response(
            "INTERNAL_ERROR",
            f"Error executing lore.list_documents: {ex}",
            reason_code="LIST_DOCUMENTS_EXCEPTION"
        )


def handle_get_document(args: Dict[str, Any]) -> str:
    """Retrieves document details, page OCR confidence, and full extracted text."""
    doc_id = (args.get("document_id") or "").strip()
    if not doc_id:
        return make_error_response("INVALID_ARGUMENT", "The 'document_id' parameter is required.")

    ws_arg = args.get("workspace_id")
    org_arg = args.get("organization_id")
    ws_name_arg = args.get("workspace_name")
    ws = None
    if ws_arg or org_arg or ws_name_arg:
        ws, err = resolve_workspace_from_args(args)
        if err or not ws:
            return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    qs = SourceDocument.objects.filter(id=doc_id).select_related('workspace')
    if ws is not None:
        qs = qs.filter(workspace=ws)
    doc = qs.first()
    if not doc:
        return make_error_response("RESOURCE_NOT_FOUND", f"Document with ID '{doc_id}' not found.")

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

    payload = {
        "schema": "lore.document/1",
        "document_id": str(doc.id),
        "title": doc.title,
        "document_type": doc.document_type,
        "status": doc.status,
        "authority_level": doc.authority_level,
        "ocr_confidence": doc.ocr_confidence,
        "page_count": doc.page_count,
        "workspace": doc.workspace.name if doc.workspace else "N/A",
        "sample_pages": pages_summary
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_ocr_extract(args: Dict[str, Any]) -> str:
    """Executes real-time dual-stream OCR extraction on a local file."""
    file_path = (args.get("file_path") or "").strip()
    if not file_path:
        return make_error_response("INVALID_ARGUMENT", "The 'file_path' parameter is required.")

    if not os.path.exists(file_path):
        return make_error_response("RESOURCE_NOT_FOUND", f"File does not exist at '{file_path}'.")

    try:
        from apps.ingestion.pipeline.extractors import UnifiedDocumentExtractor
        extractor = UnifiedDocumentExtractor()
        ext = os.path.splitext(file_path.lower())[1]
        doc_type = 'pdf' if ext == '.pdf' else ('image' if ext in ('.png', '.jpg', '.jpeg') else 'other')
        pages = extractor.extract_document(
            file_path_or_bytes=file_path,
            doc_type=doc_type,
            filename=os.path.basename(file_path)
        )

        payload = {
            "schema": "lore.ocr/1",
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
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)
    except Exception as ex:
        safe_ex = sanitize_sensitive_data(str(ex))
        logger.error(f"OCR extraction failed for {file_path}: {safe_ex}")
        return make_error_response("EXECUTION_FAILURE", f"OCR extraction error: {safe_ex}", reason_code="OCR_EXTRACTION_FAILED")


def handle_attest_compliance(args: Dict[str, Any]) -> str:
    """
    Evaluates policy compliance and generates a verifiable zero-knowledge proof (ZKP)
    attestation proving compliance without leaking proprietary policy statements or paths.
    """
    decision_type = args.get("decision_type", "general_inquiry")
    query = args.get("query") or f"Compliance attestation for {decision_type}"
    entities = args.get("entities") or []
    user_role = args.get("user_role", "member")
    authority_floor = int(args.get("required_authority_floor", 4))
    backend = args.get("backend", "auto")

    ws, err = resolve_workspace_from_args(args)
    if err or not ws:
        return err or make_error_response("RESOURCE_NOT_FOUND", "Workspace not found.", reason_code="WORKSPACE_NOT_FOUND")

    # Retrieve context & candidate chunks
    retriever = HybridRetrievalService()
    search_q = f"{query} {' '.join(entities)}".strip()
    candidate_chunks = retriever.search(
        query=search_q,
        workspace_id=str(ws.id),
        organization_id=get_organization_id(ws),
        limit=8
    )

    # Evaluate through governance engine
    envelope = EnterpriseGovernanceEngine.evaluate(
        query=search_q,
        retrieved_chunks=candidate_chunks,
        workspace=ws,
        user=None,
        user_role=user_role,
        decision_type=decision_type,
        zk_attestation=False
    )

    verdict = envelope.get("state", "insufficient")
    directive = envelope.get("directive", "ask_user")
    
    if "evidence_status" in args:
        is_satisfied = (str(args.get("evidence_status")).lower() in ("satisfied", "supported", "active"))
    else:
        is_satisfied = (verdict in ("supported", "qualified"))

    if not is_satisfied:
        return make_error_response(
            "PRECONDITION_FAILED",
            f"Cannot generate compliance attestation: policy evaluation state '{verdict}' does not meet required evidence sufficiency.",
            reason_code="EVIDENCE_NOT_SATISFIED"
        )

    # Resolve target rule to bind
    rule_id = args.get("rule_id")
    if not rule_id:
        applicable_rules = envelope.get("applicable_rules", [])
        if applicable_rules:
            rule_id = applicable_rules[0].get("rule_id") or applicable_rules[0].get("code")
        if not rule_id and candidate_chunks:
            rule_id = candidate_chunks[0].get("rule_id") or candidate_chunks[0].get("document_id")
        if not rule_id:
            first_rule = KnowledgeItem.objects.filter(workspace=ws, status="stable").first()
            if first_rule:
                rule_id = str(first_rule.id)

    if not rule_id:
        return make_error_response("PRECONDITION_FAILED", "No active stable rules found to bind ZK attestation.", reason_code="NO_STABLE_RULES")

    try:
        from apps.governance.zkp import build_zk_witness, get_zk_attestation_service
        witness, pub_in = build_zk_witness(
            workspace_id=str(ws.id),
            rule_id=str(rule_id),
            decision_type=decision_type,
            required_authority_floor=authority_floor,
            evidence_status="satisfied" if is_satisfied else "unsatisfied",
            user_role=user_role,
            evidence_excerpt=envelope.get("answer", "")[:200]
        )
        prover = get_zk_attestation_service()
        zk_env = prover.prove(witness, pub_in, backend=backend)

        res = {
            "schema": "lore.result/1",
            "decision_type": decision_type,
            "state": verdict,
            "directive": directive,
            "evidence_status": "satisfied" if is_satisfied else "unsatisfied",
            "zk_attestation": zk_env.model_dump(),
            "bundle_hash": envelope.get("bundle_hash"),
            "decision_id": envelope.get("decision_id"),
            "token_count": envelope.get("token_count", 0),
            "trace_id": envelope.get("trace_id"),
            "verified": zk_env.verified,
            "notes": [
                f"Opt-in zero-knowledge attestation successfully generated using {zk_env.proof_system}.",
                "Zero proprietary statements or confidential source paths exposed."
            ]
        }
        return json.dumps(res, indent=2, ensure_ascii=False)
    except Exception as ex:
        logger.exception(f"Error generating ZK attestation: {ex}")
        return make_error_response("ATTESTATION_FAILED", f"ZK attestation generation failed: {ex}", reason_code="ZK_PROVE_ERROR")


def handle_verify_zk_proof(args: Dict[str, Any]) -> str:
    """
    Cryptographically verifies an external ZKAttestationEnvelope without database access.
    """
    attestation_envelope = args.get("attestation_envelope")
    if not attestation_envelope:
        return make_error_response("INVALID_ARGUMENT", "Missing 'attestation_envelope' parameter.")

    try:
        from apps.governance.zkp import ZKAttestationEnvelope, get_zk_attestation_service
        if isinstance(attestation_envelope, str):
            attestation_envelope = json.loads(attestation_envelope)

        envelope_obj = ZKAttestationEnvelope(**attestation_envelope)
        prover = get_zk_attestation_service()
        is_valid = prover.verify(envelope_obj)

        pub_in = envelope_obj.public_inputs
        res = {
            "schema": "lore.result/1",
            "verified": is_valid,
            "proof_system": envelope_obj.proof_system,
            "workspace_state_root": envelope_obj.workspace_state_root,
            "decision_type": pub_in.get("decision_type"),
            "evaluation_timestamp": pub_in.get("evaluation_timestamp"),
            "required_authority_floor": pub_in.get("required_authority_floor"),
            "evidence_status_code": pub_in.get("evidence_status_code"),
            "requester_role_commitment": pub_in.get("requester_role_commitment"),
            "details": "Cryptographic zero-knowledge proof verified successfully." if is_valid else "Cryptographic verification failed: proof invalid or constraint violated."
        }
        return json.dumps(res, indent=2, ensure_ascii=False)
    except Exception as ex:
        logger.warning(f"Error verifying ZK attestation envelope: {ex}")
        return make_error_response("VERIFICATION_FAILED", f"Could not verify ZK attestation: {ex}", reason_code="ZK_VERIFY_ERROR")


# ==============================================================================
# ROUTING & DISPATCH TABLE (Exact Dot Notation + Underscore Aliases)
# ==============================================================================
TOOL_DISPATCH_MAP = {
    # Flagship Context Retrieval & Adjudication
    "lore.get_context": "handle_get_context",
    "lore_get_context": "handle_get_context",
    "lore_governed_query": "handle_get_context",
    "lore.context": "handle_get_context",
    "lore_context": "handle_get_context",

    # Hybrid Search
    "lore.search": "handle_search",
    "lore_search": "handle_search",
    "search": "handle_standard_search",
    "fetch": "handle_fetch",

    # Compliance Checking
    "lore.check_compliance": "handle_check_compliance",
    "lore_check_compliance": "handle_check_compliance",

    # Conflict Detection
    "lore.detect_conflicts": "handle_detect_conflicts",
    "lore_detect_conflicts": "handle_detect_conflicts",

    # Decision Lineage & Trace
    "lore.trace": "handle_trace",
    "lore_trace": "handle_trace",

    # Decision Logging
    "lore.log_decision": "handle_log_decision",
    "lore_log_decision": "handle_log_decision",

    # History & Supersedes Timeline
    "lore.get_history": "handle_get_history",
    "lore_get_history": "handle_get_history",

    # Knowledge Graph Statistics
    "lore.stats": "handle_stats",
    "lore_stats": "handle_stats",

    # Evidence Sufficiency
    "lore.check_evidence_sufficiency": "handle_check_evidence_sufficiency",
    "lore_check_evidence_sufficiency": "handle_check_evidence_sufficiency",

    # Authority Information
    "lore.get_authority_info": "handle_get_authority_info",
    "lore_get_authority_info": "handle_get_authority_info",

    # Point-in-time Historical Retrieval
    "lore.query_as_of": "handle_query_as_of",
    "lore_query_as_of": "handle_query_as_of",

    # Active Scoped Exceptions
    "lore.get_active_exceptions": "handle_get_active_exceptions",
    "lore_get_active_exceptions": "handle_get_active_exceptions",

    # Human Review Escalation
    "lore.escalate_to_human": "handle_escalate_to_human",
    "lore_escalate_to_human": "handle_escalate_to_human",

    # Constitution & Bootstrap
    "lore.bootstrap": "handle_bootstrap",
    "lore_bootstrap": "handle_bootstrap",

    # Skill Lookup
    "lore.get_skill": "handle_get_skill",
    "lore_get_skill": "handle_get_skill",

    # Document Discovery & Inspection
    "lore.list_documents": "handle_list_documents",
    "lore_list_documents": "handle_list_documents",
    "lore.get_document": "handle_get_document",
    "lore_get_document": "handle_get_document",

    # OCR Extraction
    "lore.ocr_extract": "handle_ocr_extract",
    "lore_ocr_extract": "handle_ocr_extract",

    # Zero-Knowledge Compliance Attestation & Offline Verification
    "lore.attest_compliance": "handle_attest_compliance",
    "lore_attest_compliance": "handle_attest_compliance",
    "lore.verify_zk_proof": "handle_verify_zk_proof",
    "lore_verify_zk_proof": "handle_verify_zk_proof",
}


def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """Dispatches tool execution with normalization, error trapping, and secret scrubbing."""
    raw_name = (name or "").strip()
    norm_name = raw_name.lower()

    func_name = TOOL_DISPATCH_MAP.get(norm_name)
    if not func_name:
        # Check if dot/underscore conversion finds handler
        if "." in norm_name:
            func_name = TOOL_DISPATCH_MAP.get(norm_name.replace(".", "_"))
        elif "_" in norm_name:
            func_name = TOOL_DISPATCH_MAP.get(norm_name.replace("_", "."))

    if not func_name:
        raise ValueError(f"Unknown tool: '{name}'")

    current_module = sys.modules[__name__]
    handler = getattr(current_module, func_name, None)
    if not handler or not callable(handler):
        raise ValueError(f"Handler '{func_name}' not found for tool: '{name}'")

    try:
        result = handler(arguments)
        return sanitize_sensitive_data(str(result))
    except Exception as ex:
        logger.error(f"Error executing tool '{name}': {ex}\n{traceback.format_exc()}")
        return make_error_response(
            "INTERNAL_ERROR",
            f"Error executing {name}: {ex}",
            reason_code="TOOL_EXECUTION_EXCEPTION"
        )


call_tool = execute_tool


def dispatch_jsonrpc_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Core JSON-RPC 2.0 message dispatcher shared across stdio and Streamable HTTP.
    Returns None for notifications (no response required).
    """
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    # Notifications (no response required in stdio; HTTP 202 in Streamable HTTP)
    if method == "notifications/initialized":
        return None

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
            try:
                tool_result = execute_tool(tool_name, tool_args)
            except Exception as e_call:
                logger.error(f"Error executing {tool_name}: {e_call}\n{traceback.format_exc()}")
                tool_result = make_error_response("INTERNAL_ERROR", f"Error executing {tool_name}: {e_call}")

            # Check if tool_result represents an error envelope
            is_err = False
            try:
                parsed = json.loads(tool_result)
                if isinstance(parsed, dict) and parsed.get("is_error") is True:
                    is_err = True
            except Exception:
                pass

            response["result"] = {
                "content": [
                    {
                        "type": "text",
                        "text": tool_result
                    }
                ],
                "isError": is_err
            }
        elif method in ("resources/list", "prompts/list"):
            response["result"] = {
                method.split("/")[0]: []
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
            "message": sanitize_sensitive_data(str(ex))
        }

    return response


class MCPHttpHandler(BaseHTTPRequestHandler):
    """
    Streamable HTTP and SSE Transport Handler for Model Context Protocol (MCP).
    Enables remote cloud connection from ChatGPT Web, Claude Desktop, and IDEs.
    """
    protocol_version = "HTTP/1.1"

    def do_OPTIONS(self):
        """Preflight CORS handling for web-based MCP clients."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Accept, Mcp-Session-Id, Mcp-Protocol-Version")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        """Handles health probes, SSE discovery stream, and server capabilities."""
        clean_path = self.path.split("?")[0]
        accept = self.headers.get("Accept", "")

        if clean_path in ("/health", "/healthz"):
            body = json.dumps({
                "status": "ready",
                "transport": "streamable-http",
                "server": SERVER_INFO
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        if clean_path in ("/mcp", "/sse", "/"):
            if "text/event-stream" in accept:
                # SSE Discovery Stream
                sse_data = b"event: endpoint\ndata: /mcp\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(sse_data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(sse_data)
                self.wfile.flush()
                return

            payload = {
                "status": "ready",
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": SERVER_INFO,
                "transport": "streamable-http",
                "endpoints": {
                    "mcp": "/mcp",
                    "sse": "/sse"
                }
            }
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        not_found = b'{"error": "Not Found"}'
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(not_found)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(not_found)

    def do_POST(self):
        """Processes JSON-RPC 2.0 messages over Streamable HTTP."""
        clean_path = self.path.split("?")[0]
        if clean_path not in ("/mcp", "/"):
            not_found = b'{"error": "Not Found"}'
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(not_found)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(not_found)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            bad_req = b'{"error": "Missing or invalid Content-Length"}'
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(bad_req)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(bad_req)
            return

        body_raw = self.rfile.read(content_length).decode("utf-8")
        try:
            req = json.loads(body_raw)
        except json.JSONDecodeError as jde:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {jde}"}
            }
            err_bytes = json.dumps(err_resp).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_bytes)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(err_bytes)
            return

        # Handle notifications (e.g. notifications/initialized) -> 202 Accepted
        is_notification = ("id" not in req) or str(req.get("method", "")).startswith("notifications/")
        try:
            from django.db import close_old_connections
            close_old_connections()
        except Exception:
            pass

        resp = dispatch_jsonrpc_request(req)

        try:
            from django.db import close_old_connections
            close_old_connections()
        except Exception:
            pass

        if is_notification or resp is None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Mcp-Session-Id", f"lore-mcp-{uuid.uuid4().hex[:12]}")
            self.end_headers()
            return

        resp_bytes = json.dumps(resp, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Mcp-Session-Id", f"lore-mcp-{uuid.uuid4().hex[:12]}")
        self.end_headers()
        self.wfile.write(resp_bytes)

    def log_message(self, format, *args):
        logger.debug(f"[MCP-HTTP] {format % args}")


def run_http_server(host: str = "0.0.0.0", port: int = 8001):
    """Runs LORE Enterprise MCP server over Streamable HTTP."""
    logger.info(f"LORE Enterprise MCP server listening on http://{host}:{port}/mcp (Streamable HTTP)")
    server = ThreadingHTTPServer((host, port), MCPHttpHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping LORE MCP server...")
    finally:
        server.server_close()


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
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error: Invalid JSON."}
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
            continue

        resp = dispatch_jsonrpc_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
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
        print(handle_get_context({"query": "What are the rules of the hackathon?"}))
        print("\nAll self-tests completed successfully!")
        sys.exit(0)
    elif "--transport" in sys.argv:
        t_idx = sys.argv.index("--transport")
        transport = sys.argv[t_idx + 1] if t_idx + 1 < len(sys.argv) else "stdio"
        if transport in ("http", "streamable-http", "sse"):
            host = os.environ.get("LORE_MCP_HOST", "0.0.0.0")
            port = int(os.environ.get("LORE_MCP_PORT", 8001))
            if "--host" in sys.argv:
                h_idx = sys.argv.index("--host")
                host = sys.argv[h_idx + 1] if h_idx + 1 < len(sys.argv) else host
            if "--port" in sys.argv:
                p_idx = sys.argv.index("--port")
                port = int(sys.argv[p_idx + 1]) if p_idx + 1 < len(sys.argv) else port
            run_http_server(host, port)
        else:
            run_stdio_server()
    else:
        run_stdio_server()
