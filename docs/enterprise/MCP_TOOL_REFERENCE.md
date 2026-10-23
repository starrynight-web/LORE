# LORE Enterprise — Governed MCP Interface Reference

**Protocol Version**: `2024-11-05`  
**Server Implementation**: `backend/mcp_server.py` (v2.1.0)  
**Specification**: [`lore.md`](file:///e:/LORE/docs/enterprise/docs/lore.md#L753-L776) §11 (MCP Tool Surface) & §12.2 (The Constitution Pattern)  
**Test Suite**: `backend/tests/test_mcp_interface.py` (**30/30 tests passing**)

---

## 1. Architectural Overview & Governance Invariants

The LORE Enterprise Model Context Protocol (MCP) server provides a unified, secure interface for AI agents in Claude Desktop, Cursor, Windsurf, Antigravity, and autonomous CI/CD pipelines to interact with LORE's Governed Knowledge Grid.

```
+---------------------------------------------------------------------------------------------------+
|                                  AI Agents & Developer Environments                               |
|                     (Claude Desktop, Cursor, Windsurf, Antigravity, Git Hooks)                     |
+---------------------------------------------------------------------------------------------------+
                                                  │
                                                  │ stdio JSON-RPC 2.0 (UTF-8)
                                                  ▼
+---------------------------------------------------------------------------------------------------+
|                                  LORE Enterprise MCP Server (v2.1.0)                              |
|                                       backend/mcp_server.py                                       |
+---------------------------------------------------------------------------------------------------+
       │                                          │                                          │
       ▼                                          ▼                                          ▼
┌──────────────────────┐               ┌──────────────────────┐               ┌──────────────────────┐
│  Canonical Services  │               │ 9-Layer Master Engine│               │ Security & Safety    │
│  - HybridRetrieval   │               │ - L7: Permission     │               │ - Tenant Isolation   │
│  - ContextReranker   │               │ - L6: Authority      │               │ - Secret Scrubber    │
│  - Dual-Stream OCR   │               │ - L5: Temporal       │               │ - Bounded Concurrency│
│  - KnowledgeGraph    │               │ - L4: Exceptions     │               │ - Structured Errors  │
│  - DecisionAuditLog  │               │ - L3: Sufficiency    │               │ - Pre-commit Gating  │
│                      │               │ - L2: State Machine  │               │   (Exit 0, 3, 4)     │
└──────────────────────┘               └──────────────────────┘               └──────────────────────┘
```

### Core Invariants

1. **Zero Governance Bypass**:
   Decision-oriented operations (`lore.get_context`, `lore.check_compliance`, `lore.query_as_of`) strictly execute through `EnterpriseGovernanceEngine.evaluate()` and canonical Django ORM domain models. No MCP tool handler implements separate or unverified decision logic.

2. **Strict Separation of Raw Search and Governed Decisions**:
   `lore.search` returns un-adjudicated candidate passages for exploration. It explicitly sets `is_governed_decision: false` and includes a prominent warning banner stating that raw search results cannot be used as an authoritative governance decision.

3. **Machine Interface & Git Pre-Commit Gating**:
   `lore.check_compliance` returns semantic verdicts alongside machine-readable exit codes:
   - **`0` = PASS** (`proceed_and_cite`): Diff strictly adheres to enterprise standards.
   - **`3` = UNCERTAIN** (`ask_user`): Evidence is incomplete or conflicting; agent must seek clarification.
   - **`4` = FAIL** (`stop`): Diff violates an authoritative standard (Rank ≥ 4); execution must halt.

4. **Tenant Scope & Authorization Enforcement**:
   Every tool verifies `workspace_id` and cross-references `organization_id`. Cross-tenant requests immediately fail closed with `PERMISSION_DENIED` and reason code `TENANT_ISOLATION_VIOLATION`. L7 permissions ensure unauthorized evidence (e.g. restricted documents) is purged before candidate passages reach callers.

5. **Secret Scrubbing & Safe Error Envelopes**:
   All text and JSON outputs pass through `sanitize_sensitive_data()`. Sensitive credentials (`gsk_*`, `sk-*`, `Bearer *`, passwords) are redacted. Internal exceptions fail closed into structured `lore.error/1` envelopes without exposing Python stack traces.

---

## 2. Tool Manifest & Capability Matrix

All tools support both canonical dot-notation (`lore.<tool>`) and underscore aliases (`lore_<tool>`) for full client compatibility.

| Canonical Name | Compatibility Aliases | Governance Layer | Primary Output Schema | Purpose |
|---|---|---|---|---|
| `lore.get_context` | `lore_get_context`, `lore_governed_query`, `lore.context` | All (L7-L0) | `lore.result/2` | Flagship governed context retrieval and 9-layer adjudication. |
| `lore.search` | `lore_search` | Core Retrieval | `lore.search_results/1` | Hybrid vector + lexical search across passages. |
| `lore.check_compliance` | `lore_check_compliance` | L2 + L6 + Judge | `lore.compliance/1` | Per-rule diff evaluation with pre-commit exit codes (0, 3, 4). |
| `lore.detect_conflicts` | `lore_detect_conflicts` | L6 (Authority) | `lore.conflicts/1` | Cross-document contradiction report & authority dominance. |
| `lore.trace` | `lore_trace` | L0 (Observability) | `lore.trace/1` | Complete decision lineage: rule -> version -> sources -> audit events. |
| `lore.log_decision` | `lore_log_decision` | L0 (Observability) | `lore.decision_log/1` | Appends authoritative decision record to audit database. |
| `lore.get_history` | `lore_get_history` | L5 (Temporal) | `lore.history/1` | Document version timeline and SUPERSEDES relationship chains. |
| `lore.stats` | `lore_stats` | L0 (Observability) | `lore.stats/1` | Knowledge graph counts, document health, and decision volume. |
| `lore.check_evidence_sufficiency` | `lore_check_evidence_sufficiency` | L3 (Sufficiency) | `lore.sufficiency/1` | Evaluates mandatory requirements for a decision type. |
| `lore.get_authority_info` | `lore_get_authority_info` | L6 (Authority) | `lore.authority/1` | 7-tier authority ladder metadata, staleness, and permissions. |
| `lore.query_as_of` | `lore_query_as_of` | L5 (Temporal) | `lore.result/2` | Point-in-time historical retrieval and validity verification. |
| `lore.get_active_exceptions` | `lore_get_active_exceptions` | L4 (Exceptions) | `lore.exceptions/1` | Active scoped overrides applying to context/vendor/project. |
| `lore.escalate_to_human` | `lore_escalate_to_human` | L2 (Answer State) | `lore.escalation/1` | Enqueues review ticket in compliance queue. |
| `lore.bootstrap` | `lore_bootstrap` | Core Constitution | `lore.constitution/1` | Serves `agent.md` constitution and phase policies. |
| `lore.get_skill` | `lore_get_skill` | Core Operational | `lore.skill/1` | Procedural steps and prerequisites for engineering skills. |
| `lore.get_document` | `lore_get_document` | Source Registry | `lore.document/1` | Page OCR confidence, metadata, and extracted text. |
| `lore.ocr_extract` | `lore_ocr_extract` | Ingestion / OCR | `lore.ocr/1` | Real-time dual-stream OCR extraction on local file. |

---

## 3. Comprehensive Tool Reference

### 3.1 `lore.get_context`

**Description**: The flagship LORE tool. Retrieves candidate knowledge passages, evaluates them through all 9 governance layers, enforces deterministic-first synthesis, and produces an authoritative envelope.

#### Arguments
```json
{
  "type": "object",
  "properties": {
    "file_path": {"type": "string", "description": "Path of the file being edited or inspected."},
    "intent": {"type": "string", "description": "Task intent or query to evaluate against governed knowledge."},
    "query": {"type": "string", "description": "Direct query string (alternative to file_path + intent)."},
    "workspace_id": {"type": "string", "description": "Optional UUID of target workspace."},
    "organization_id": {"type": "string", "description": "Optional UUID of organization for tenant check."},
    "user_role": {"type": "string", "description": "Principal role ('member', 'workspace_admin', 'auditor').", "default": "member"},
    "as_of": {"type": "string", "description": "Optional point-in-time date (YYYY-MM-DD or ISO)."},
    "execution_mode": {"type": "string", "description": "'local_only', 'deterministic_first', 'approved_remote'.", "default": "deterministic_first"},
    "synthesis_mode": {"type": "string", "description": "'auto', 'extractive', 'abstractive', 'deterministic'.", "default": "auto"},
    "document_id": {"type": "string", "description": "Optional UUID of specific source document."},
    "limit": {"type": "integer", "description": "Candidate passages limit (1-50).", "default": 10},
    "groq_api_key": {"type": "string", "description": "Optional Groq API key if remote approved."},
    "llm_model": {"type": "string", "description": "Target LLM model.", "default": "gpt-oss-120B"}
  }
}
```

#### Example Call
```json
{
  "jsonrpc": "2.0",
  "id": 101,
  "method": "tools/call",
  "params": {
    "name": "lore.get_context",
    "arguments": {
      "file_path": "backend/apps/storage/s3.py",
      "intent": "Can we configure S3 buckets without server-side encryption?",
      "execution_mode": "deterministic_first"
    }
  }
}
```

#### Result Schema (`lore.result/2`)
```json
{
  "schema": "lore.result/2",
  "status": "violation",
  "directive": "stop",
  "answer": "According to Production Data Encryption Standard v2.0 (Page 1, Authority Rank 7): Section 4.1: All production database snapshots and object storage must be encrypted with AES-256-GCM. Unencrypted S3 buckets violate enterprise security policy.",
  "decision_type": "security_policy",
  "escalation_target": "security_officer",
  "evidence_missing": [],
  "conflicts_resolved": [],
  "exceptions_applied": [],
  "layers_breakdown": {
    "l7_permission": {"status": "passed", "denials": []},
    "l1_decision_intelligence": {"decision_type": "security_policy", "risk": "high"},
    "l6_authority": {"conflicts_count": 0, "unresolved_tie": false},
    "l5_temporal": {"stale_data": false},
    "l4_exceptions": {"applied_count": 0},
    "l3_sufficiency": {"is_sufficient": true},
    "l2_answer_state": {"final_state": "violation", "directive": "stop"}
  },
  "llm_provider": "deterministic_synthesis",
  "anti_hallucination_active": true,
  "citations_count": 1,
  "execution_mode": "deterministic_first",
  "was_deterministic": true,
  "citations": [
    {
      "document": "Production Data Encryption Standard v2.0",
      "page": 1,
      "authority_rank": 7
    }
  ],
  "trace_id": "trace-4b82c9e102f1"
}
```

---

### 3.2 `lore.search`

**Description**: High-speed hybrid vector + lexical search. Returns candidate passages with rank and relevance scores. Clearly identified as un-adjudicated informational retrieval.

#### Arguments
```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "description": "Search query."},
    "workspace_id": {"type": "string", "description": "Optional target workspace UUID."},
    "limit": {"type": "integer", "description": "Result limit (1-50). Default: 6.", "default": 6},
    "unverified": {"type": "boolean", "description": "Include draft/quarantined items. Default: false.", "default": false},
    "output_format": {"type": "string", "description": "'text' or 'json'. Default: 'text'.", "default": "text"}
  },
  "required": ["query"]
}
```

#### Example Output (`output_format="json"`)
```json
{
  "schema": "lore.search_results/1",
  "is_governed_decision": false,
  "governance_status": "ungoverned_informational_retrieval",
  "warning": "Raw search results are un-adjudicated candidate passages and CANNOT be used as an authoritative governance decision. For governed decisions, evaluate with lore.get_context or lore.check_compliance.",
  "query": "encryption standard",
  "workspace_id": "3b2909f1-a182-4f7b-99d8-8ec930db1920",
  "workspace_name": "Security & Governance",
  "total_passages": 1,
  "passages": [
    {
      "rank": 1,
      "document_title": "Production Data Encryption Standard v2.0",
      "page_number": 1,
      "score": 0.9421,
      "authority_level": 7,
      "text": "Section 4.1: All production database snapshots and object storage must be encrypted with AES-256-GCM..."
    }
  ]
}
```

---

### 3.3 `lore.check_compliance`

**Description**: Evaluates a unified code diff against governed enterprise rules, returning individual rule outcomes and pre-commit machine exit codes.

#### Arguments
```json
{
  "type": "object",
  "properties": {
    "diff": {"type": "string", "description": "Unified diff or code snippet."},
    "intent": {"type": "string", "description": "Optional intent description."},
    "file_path": {"type": "string", "description": "Target file or component path."},
    "workspace_id": {"type": "string", "description": "Optional UUID of target workspace."},
    "user_role": {"type": "string", "description": "Executing role.", "default": "member"}
  },
  "required": ["diff"]
}
```

#### Exit Code Semantics
- **`0` = PASS** (`proceed_and_cite`): Diff complies with all rules. CI/CD or git pre-commit hook exits cleanly.
- **`3` = UNCERTAIN** (`ask_user`): Missing evidence or unresolved conflict. Agent pauses and prompts user.
- **`4` = FAIL** (`stop`): Diff violates an authoritative rule. CI/CD or pre-commit hook halts commit.

#### Example Output (`lore.compliance/1`)
```json
{
  "schema": "lore.compliance/1",
  "overall_verdict": "FAIL",
  "directive": "stop",
  "exit_code": 4,
  "machine_action": "halt",
  "rules_checked": 2,
  "rules_passed": 1,
  "rules_failed": 1,
  "rules_uncertain": 0,
  "rule_evaluations": [
    {
      "rule_code": "SEC-R-014",
      "title": "Database credentials must not be stored in plaintext or commit diffs.",
      "verdict": "FAIL",
      "authority_rank": 7,
      "notes": "Diff contains prohibited pattern matching negative directive in SEC-R-014"
    },
    {
      "rule_code": "POL-ENC-v2",
      "title": "Production Data Encryption Standard v2.0",
      "verdict": "PASS",
      "authority_rank": 7,
      "notes": "Evaluated against authoritative document standard."
    }
  ],
  "governance_state": "violation",
  "trace_id": "trace-77c8e9b012d4",
  "citations": []
}
```

---

### 3.4 `lore.detect_conflicts`

**Description**: Reports contradictions across knowledge documents, showing contradictory claims, authority rankings, and resolution status.

#### Arguments
```json
{
  "type": "object",
  "properties": {
    "workspace_id": {"type": "string", "description": "Optional target workspace UUID."},
    "scope": {"type": "string", "description": "Filter by query keyword or document title."},
    "status": {"type": "string", "description": "'all', 'unresolved', 'resolved_by_authority'.", "default": "all"}
  }
}
```

#### Example Output (`lore.conflicts/1`)
```json
{
  "schema": "lore.conflicts/1",
  "workspace": "Security & Governance",
  "workspace_id": "3b2909f1-a182-4f7b-99d8-8ec930db1920",
  "total_conflicts": 1,
  "unresolved_count": 0,
  "resolved_by_authority_count": 1,
  "conflicts": [
    {
      "id": "c10928f4-3401-4ecb-88a9-4d89a2b0c112",
      "source_a": {
        "id": "e76ea889-ced5-4d19-9b4b-1a7a485dcab7",
        "title": "Production Data Encryption Standard v2.0",
        "authority_rank": 7
      },
      "source_b": {
        "id": "f88cb019-2184-46ab-a09c-5a91b30df294",
        "title": "Legacy Storage Guideline v1.0",
        "authority_rank": 4
      },
      "claim_a": "Storage must use AES-256-GCM encryption at all times.",
      "claim_b": "Storage may use unencrypted local volumes for staging caches.",
      "resolution_status": "resolved_by_authority",
      "resolution_notes": "Policy v2.0 (Rank 7) dominates Legacy Guideline (Rank 4).",
      "created_at": "2026-10-23T16:00:00Z"
    }
  ]
}
```

---

### 3.5 `lore.trace` & `lore.log_decision`

#### `lore.log_decision`
Appends a governed decision to the audit trail:
```json
{
  "task": "Migrate production customer DB",
  "rules": ["SEC-R-014", "POL-ENC-v2"],
  "outcome": "proceed_and_cite",
  "notes": "Verified AES-256-GCM encryption in staging.",
  "token_count": 420
}
```

#### `lore.trace`
Retrieves full decision lineage by trace ID:
```json
{
  "schema": "lore.trace/1",
  "trace_id": "trace-819a0b2c14df",
  "decision_id": "dec-a82f019b",
  "timestamp": "2026-10-23T16:54:20Z",
  "query": "Migrate production customer DB",
  "decision_type": "agent_action_decision",
  "state": "supported",
  "directive": "proceed_and_cite",
  "answer": "Verified AES-256-GCM encryption in staging.",
  "evidence_found": ["SEC-R-014", "POL-ENC-v2"],
  "token_count": 420,
  "audit_events": [
    {
      "event_type": "decision_recorded",
      "target_type": "decision",
      "timestamp": "2026-10-23T16:54:20Z",
      "details": {"state": "supported", "directive": "proceed_and_cite"}
    }
  ]
}
```

---

### 3.6 `lore.get_history`

**Description**: Retrieves document revision timeline and GraphRAG `SUPERSEDES` relationships.

#### Example Output (`lore.history/1`)
```json
{
  "schema": "lore.history/1",
  "document_id": "e76ea889-ced5-4d19-9b4b-1a7a485dcab7",
  "title": "Production Data Encryption Standard v2.0",
  "original_filename": "encryption_standard.pdf",
  "current_version": 2,
  "authority_level": 7,
  "status": "ready",
  "versions": [
    {
      "version_number": 2,
      "file_hash": "hash_enc_v2_999999...",
      "change_summary": "Mandate AES-256-GCM for all at-rest storage.",
      "is_current": true,
      "created_at": "2026-09-23T10:00:00Z"
    },
    {
      "version_number": 1,
      "file_hash": "hash_enc_v1_000000...",
      "change_summary": "Initial encryption policy.",
      "is_current": false,
      "created_at": "2025-09-23T10:00:00Z"
    }
  ],
  "supersedes_chain": [
    {
      "relationship_id": "edge-0012-99a",
      "newer_document": "Production Data Encryption Standard v2.0",
      "superseded_document": "Legacy Storage Guideline v1.0",
      "provenance": "Canonical policy lifecycle",
      "approval_status": "approved"
    }
  ]
}
```

---

### 3.7 `lore.check_evidence_sufficiency`

**Description**: Standalone evaluation of mandatory evidence requirements without executing an entire query.

#### Example Output (`lore.sufficiency/1`)
```json
{
  "schema": "lore.sufficiency/1",
  "decision_type": "vendor_approval",
  "is_sufficient": false,
  "evidence_found": [
    {"document_title": "Evidence SOC2 report", "authority_level": 5}
  ],
  "evidence_missing": [
    {
      "requirement": "data_residency_guarantee",
      "status": "missing",
      "mandatory": true,
      "description": "Formal data residency agreement in European Union"
    }
  ],
  "verdict_impact": "insufficient_requires_ask_user",
  "mandatory_requirements": [
    {
      "evidence_type": "data_residency_guarantee",
      "min_authority": 5,
      "is_mandatory": true
    }
  ],
  "reason_codes": ["L3_MANDATORY_EVIDENCE_UNSATISFIED"]
}
```

---

### 3.8 `lore.get_authority_info`

**Description**: Inspects source document authority ranking (1-7), hierarchy dominance, staleness rules, and permission classification.

#### Example Output (`lore.authority/1`)
```json
{
  "schema": "lore.authority/1",
  "document_id": "e76ea889-ced5-4d19-9b4b-1a7a485dcab7",
  "title": "Production Data Encryption Standard v2.0",
  "authority_rank": 7,
  "authority_level_name": "approved_policy (Rank 7)",
  "hierarchy_rank_explanation": "Authority ladder (1-7): 7=approved_policy (dominates conflicting lower tiers), 6=signed_contract, 5=team_convention, 4=maintained_procedure, 3=reviewed_document, 2=wiki_entry, 1=informal_note.",
  "status": "ready",
  "effective_date": "2026-09-23T10:00:00Z",
  "expiration_date": "2027-09-23T10:00:00Z",
  "stale_after_days": 365,
  "access_level": "internal"
}
```

---

### 3.9 `lore.query_as_of`

**Description**: Enforces historical point-in-time validity. Ensures documents effective after `as_of` or expired before `as_of` are strictly excluded from context and decisions.

```json
{
  "query": "encryption standard",
  "as_of": "2026-03-01",
  "workspace_id": "3b2909f1-a182-4f7b-99d8-8ec930db1920"
}
```

---

### 3.10 `lore.get_active_exceptions`

**Description**: Lists active, time-bounded scoped overrides matching the current context.

```json
{
  "schema": "lore.exceptions/1",
  "workspace": "Security & Governance",
  "as_of": "now",
  "total_active": 1,
  "exceptions": [
    {
      "id": "exc-0041-998b",
      "rule_code": "SEC-R-014",
      "scope_type": "vendor",
      "scope_value": "CloudBox",
      "window_start": "2026-10-18T00:00:00Z",
      "window_end": "2026-11-17T00:00:00Z",
      "justification": "Approved temporary sandbox exemption for migration validation.",
      "approved_by": "CISO Jane Doe",
      "status": "active"
    }
  ]
}
```

---

### 3.11 `lore.escalate_to_human`

**Description**: Explicitly creates a human review ticket when ambiguity, conflicting claims, or high-risk directives require manual sign-off.

```json
{
  "schema": "lore.escalation/1",
  "ticket_id": "dec-esc-00192841",
  "trace_id": "trace-esc-8f9012da",
  "query": "Uncertain vendor security approval for CloudBox",
  "escalation_state": "human_review",
  "escalation_target": "compliance_review_queue",
  "queue_status": "queued",
  "message": "Human review requested. Ticket dec-esc-00192841 placed in compliance review queue."
}
```

---

### 3.12 `lore.bootstrap` & `lore.get_skill`

#### `lore.bootstrap`
Serves the constitution (`agent.md`) on agent connect (lore.md §12.2), establishing mandatory directives:
- Retrieve architecture and security rules before planning.
- Run `lore.check_compliance(diff)` before committing code.
- Obey exit code 4 (STOP) and exit code 3 (ASK_USER).

#### `lore.get_skill`
Retrieves standardized procedural steps for engineering skills (`ui-ux-pro`, `security-review`, `compliance-gate`).

---

## 4. Error Handling & Structured Envelope (`lore.error/1`)

When input validation fails, a resource is missing, or an unexpected exception occurs, the server responds with a structured, sanitized error envelope:

```json
{
  "schema": "lore.error/1",
  "is_error": true,
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "Workspace '...' does not belong to organization '...'. Cross-tenant access denied.",
    "reason_code": "TENANT_ISOLATION_VIOLATION",
    "details": {}
  },
  "trace_id": "err-58f3c06b",
  "timestamp": "2026-10-23T16:54:26Z"
}
```

Standard error codes:
- `INVALID_ARGUMENT`: Missing required arguments, bad parameters, or malformed UUIDs.
- `RESOURCE_NOT_FOUND`: Non-existent document, workspace, trace, or file.
- `PERMISSION_DENIED`: Cross-tenant access violation or insufficient role for restricted source.
- `INTERNAL_ERROR`: Unhandled exception trapped safely; stack trace logged to stderr, not returned to client.

---

## 5. Deprecation & Migration Guide

Legacy client applications calling underscore tool names remain fully supported:

| Legacy Call | Canonical Replacement | Status | Sunset Date |
|---|---|---|---|
| `lore_governed_query` | `lore.get_context` | Deprecated (Supported via alias) | Q4 2027 |
| `lore_search` | `lore.search` | Supported alias | Maintained |
| `lore_get_document` | `lore.get_document` | Supported alias | Maintained |
| `lore_ocr_extract` | `lore.ocr_extract` | Supported alias | Maintained |

All clients are encouraged to migrate to dot-notation names (`lore.get_context`, `lore.search`, `lore.check_compliance`) to align with MCP standard naming conventions.
