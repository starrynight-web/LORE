# LORE Enterprise — 9-Layer Governance Implementation Map

**Document Version:** 2.0 (Verified Runtime Mapping)  
**Date:** October 2026  
**Auditor / Architect:** Antigravity Advanced Agentic Coding Engine  
**Specification Reference:** `docs/enterprise/docs/lore.md` (§4, §10, §11), `docs/GOVERNANCE_CONTRACT.md`

---

## Overview

The LORE Enterprise governance engine operates as an ordered, deterministic evaluation machine executing between hybrid retrieval and final context delivery.

```
Incoming Query + Retrieved Seed Chunks (≤ 800 tokens)
   │
   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 0: L7 — Permission Layer (Pre-Model Authorization)              │
│ Excludes unauthorized chunks before they enter context window.          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Cleared Chunks
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: L1 — Decision Intelligence (Query Classification)             │
│ Classifies decision type, sets mandatory evidence, escalation target.  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Classified Context
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: L5 — Temporal Validity (Lifecycle & Point-in-Time)            │
│ Drops unapproved/draft/failed, future effective, and expired records.  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Active Chunks
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: L4 — Scoped Exception Layer (Time-Bounded Overrides)          │
│ Matches active exceptions; satisfies mandatory evidence conditionally. │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Active Chunks + Exceptions
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 4: L6 — Authority & Conflict Resolution                          │
│ 7-rank ladder dominance; version supersession; flags unresolved ties.  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Authoritative Chunks + Conflicts
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 5: L3 — Evidence Sufficiency Layer                               │
│ Evaluates mandatory criteria; emits typed missing-evidence statuses.   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Sufficiency State
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 6: L2 — Answer-State Layer (Precedence State Machine)            │
│ Deterministic 9-state ladder: denied > violation > ... > supported     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Resolved State & Directive
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 7: Grounded Answer Synthesis (Zero-Hallucination Generation)     │
│ Groq API (temperature=0.0) or deterministic excerpt citations.        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Raw Envelope
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 8: Canonical Contract Validation Gate                            │
│ Mathematical enforcement of state-directive invariants (contract.py)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Validated Envelope
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STAGE 9: L0 — Observability Layer (Audit & Lineage Persistence)        │
│ Records DecisionRecord, AuditEvent, trace_id, and stage latency.       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Layer Specifications

### L7 — Permission Layer (Pre-Model Authorization)

- **Documented Purpose:** `lore.md` §4 L7. "Authorization happens BEFORE restricted content enters the model's context window. An unauthorized agent never sees the text, even in intermediate prompts."
- **Implementation File:** [`backend/apps/governance/layers.py:36-85`](file:///e:/LORE/backend/apps/governance/layers.py#L36-L85)
- **Class / Method:** `PermissionLayer.filter_authorized_chunks(chunks, user, user_role)`
- **Pipeline Stage:** Stage 0 (Executed first, immediately upon receiving retrieved candidates).
- **Relational Data Model:** [`SourcePermission`](file:///e:/LORE/backend/apps/governance/models.py#L48-L80)
  - Fields: `document` (OneToOne to `SourceDocument`), `access_level` (`public`, `internal`, `restricted`, `confidential`), `allowed_roles` (JSON list), `allowed_users` (JSON list), `redaction_required` (boolean).
- **Enforcement Invariants:**
  - `public`: Permitted to all users.
  - `internal`: Permitted to `workspace_admin`, `member`, `admin`, `compliance_auditor`, `owner`.
  - `restricted` / `confidential`: Requires superuser, explicit username in `allowed_users`, or explicit role match in `allowed_roles`.
  - Chunks failing authorization are completely omitted from `cleared_chunks`.
  - If all candidate chunks are unauthorized, sets `is_denied = True`.
- **Execution Mode:** 100% Deterministic Rule Algorithm (Zero model inference).
- **Test Coverage:**
  - `tests/test_saas_security_and_lifecycle.py::test_tenant_isolation_workspace_and_documents`
  - `tests/test_retrieval_stack_audit.py::test_05_governance_filters_prevent_unauthorized_and_unpublished`
- **Limitations & Gaps:**
  - Field-level column/passage redaction (`redaction_required=True`) is flagged in the model but currently operates at chunk granularity (omitting the entire chunk rather than masking regex PII patterns).

---

### L6 — Authority & Conflict Resolution Layer

- **Documented Purpose:** `lore.md` §4 L6. "Unified 7-rank authority ladder. Higher rank wins; same rank newer wins; unresolved contradiction $\to$ conflicting state (never settled silently)."
- **Implementation File:** [`backend/apps/governance/layers.py:172-258`](file:///e:/LORE/backend/apps/governance/layers.py#L172-L258)
- **Class / Method:** `AuthorityLayer.evaluate_conflicts(chunks)`
- **Pipeline Stage:** Stage 4 (Evaluated after temporal filtering and exception matching).
- **Relational Data Models:**
  - [`SourceDocument.authority_level`](file:///e:/LORE/backend/apps/sources/models.py#L59) (PositiveSmallIntegerField, ranks 1 to 7).
  - [`DocumentVersion.version_number`](file:///e:/LORE/backend/apps/sources/models.py#L80) (PositiveIntegerField).
  - [`ConflictRecord`](file:///e:/LORE/backend/apps/governance/models.py#L19-L39) (Relational table linking conflicting documents).
- **Enforcement Invariants:**
  - **7-Rank Ladder:**
    - Rank 7: `approved_policy`
    - Rank 6: `signed_contract`
    - Rank 5: `team_convention`
    - Rank 4: `maintained_procedure`
    - Rank 3: `reviewed_document`
    - Rank 2: `wiki_entry`
    - Rank 1: `informal_note`
  - **Authority Dominance:** If an informal claim (Rank $\le 2$) asserts approval (`allowed`, `permitted`, `yes`) while a formal record (Rank $\ge 6$) asserts prohibition (`prohibit`, `require`, `must not`), the formal record dominates and the conflict is resolved as `authority_dominance`.
  - **Version Supersession:** If two chunks at equal rank ($\ge 3$) disagree, the chunk with the higher `document_version` supersedes the earlier version (`version_supersession`).
  - **Unresolved Contradiction:** If two authoritative chunks at equal rank and equal version disagree without supersession, `has_unresolved_tie = True` is raised. The engine is strictly forbidden from guessing.
- **Execution Mode:** 100% Deterministic Rule Algorithm.
- **Test Coverage:**
  - `tests/test_governance_p1.py::test_authority_dominance_overrides_informal_claim`
  - `tests/test_governance_p1.py::test_version_supersession_at_equal_rank`
  - `tests/test_governance_p1.py::test_equal_rank_contradiction_without_supersession_flags_unresolved`
- **Limitations & Gaps:**
  - Contradiction detection relies on semantic keyword matching (`permitted` vs `forbidden`); fine-grained numerical value contradictions (e.g. 15-minute vs 30-minute timeout) require explicit `ConflictRecord` rows.

---

### L5 — Temporal Validity Layer

- **Documented Purpose:** `lore.md` §4 L5. "Is this rule in effect right now (or at date X)? Evaluates effective_from, expiry, staleness aging, and historical as_of point-in-time queries."
- **Implementation File:** [`backend/apps/governance/layers.py:263-361`](file:///e:/LORE/backend/apps/governance/layers.py#L263-L361)
- **Class / Method:** `TemporalValidityLayer.evaluate(chunks, as_of=None)`
- **Pipeline Stage:** Stage 2 (Evaluated immediately after decision intelligence classification).
- **Relational Data Model:** [`SourceDocument`](file:///e:/LORE/backend/apps/sources/models.py#L7-L76)
  - Fields: `status`, `effective_date`, `expiration_date`, `stale_after_days`, `updated_at`.
- **Enforcement Invariants:**
  - **Stable-Only Serving (§6):** Any chunk whose `SourceDocument.status != 'ready'` (e.g. `quarantined`, `draft`, `failed`, `needs_review`) is strictly excluded with a `Lifecycle Exclusion` note.
  - **Future Effective Exclusion:** If `effective_date > ref_time`, chunk is excluded.
  - **Expiration Exclusion:** If `expiration_date < ref_time`, chunk is excluded.
  - **Staleness Aging:** If `ref_time - updated_at > stale_after_days` (default 365 days), chunk remains in context but flags `has_stale_data = True` and forces answer state to `qualified`.
  - **Point-in-Time `as_of` Queries:** Normalizes string/datetime timestamps to UTC aware datetimes, evaluating document validity at that exact historical moment.
- **Execution Mode:** 100% Deterministic Date Arithmetic.
- **Test Coverage:**
  - `tests/test_governance_p1.py::test_temporal_validity_future_effective_date_excluded`
  - `tests/test_governance_p1.py::test_historical_as_of_point_in_time_query`
  - `tests/test_governance_p1.py::test_quarantined_and_unapproved_documents_barred_from_context`
- **Limitations & Gaps:**
  - Relies on document-level dates; chunk-level lifecycle dates (e.g. individual clause sunset dates) are inherited from parent document.

---

### L4 — Scoped Exception Layer

- **Documented Purpose:** `lore.md` §4 L4. "Scoped, time-bounded overrides. An exception applies only if every scope dimension matches and the query time falls within window. Disclosed in every result."
- **Implementation File:** [`backend/apps/governance/layers.py:366-412`](file:///e:/LORE/backend/apps/governance/layers.py#L366-L412)
- **Class / Method:** `ExceptionLayer.evaluate(workspace_id, query, as_of=None)`
- **Pipeline Stage:** Stage 3.
- **Relational Data Model:** [`ScopedException`](file:///e:/LORE/backend/apps/governance/models.py#L82-L154)
  - Fields: `rule_code`, `scope_type` (`department`, `project`, `data_type`, `vendor`), `scope_value`, `window_start`, `window_end`, `justification`, `approved_by`, `status` (`active`, `expired`, `revoked`).
- **Enforcement Invariants:**
  - Status must be `'active'`.
  - Query time must satisfy `window_start <= now <= window_end`.
  - Scope value or rule code must match query tokens.
  - Matching exceptions satisfy mandatory evidence requirements that would otherwise block approval, transitioning verdict from `insufficient` to `qualified`.
  - Applied exceptions are mandatory disclosures in `envelope['exceptions_applied']`.
- **Execution Mode:** 100% Deterministic Rule Matching.
- **Test Coverage:**
  - `tests/test_governance_p1.py::test_active_matching_exception_applies`
  - `tests/test_governance_p1.py::test_expired_exception_is_rejected`
- **Limitations & Gaps:**
  - Scope matching uses case-insensitive substring matching against query text; structured scope attributes (e.g. passing explicit `{vendor: "CloudBox"}` in query payload) should be supported alongside free text.

---

### L3 — Evidence Sufficiency Layer

- **Documented Purpose:** `lore.md` §4 L3. "Evaluates whether evidence is complete enough to support the classified decision type. Outputs the exact list of missing requirements."
- **Implementation File:** [`backend/apps/governance/layers.py:417-532`](file:///e:/LORE/backend/apps/governance/layers.py#L417-L532)
- **Class / Method:** `EvidenceSufficiencyLayer.evaluate(workspace_id, decision_info, retrieved_chunks, query, has_exception=False)`
- **Pipeline Stage:** Stage 5.
- **Relational Data Model:** [`EvidenceRequirement`](file:///e:/LORE/backend/apps/governance/models.py#L7-L18)
  - Fields: `decision_type`, `evidence_type`, `is_mandatory`, `min_authority_level`, `description`.
- **Enforcement Invariants:**
  - Checks domain criteria:
    - **Vendor Approval:** Checks executed regional data residency addendum (`Schedule D`) and formal security assessment report.
    - **Statutory Land Compliance:** Checks registered Saf Kabla deed and property schedule / CS/RS khatian.
    - **Data Processing:** Checks data retention and lawful consent policy.
  - **Authority Threshold Gating:** High-risk decisions require controlling evidence rank $\ge 4$. If top evidence has informal rank $\le 2$, records `INSUFFICIENT_AUTHORITY`.
  - **Mathematical Non-Approval Guarantee:** If any mandatory requirement is unsatisfied, `is_sufficient = False`. The engine cannot emit `supported`.
  - Outputs typed status per requirement: `satisfied`, `missing`, `pending`, `insufficient_authority`.
- **Execution Mode:** 100% Deterministic Rule Algorithm.
- **Test Coverage:**
  - `tests/test_governance_p1.py::test_vendor_approval_insufficient_evidence_escalation`
  - `tests/test_governance_p1.py::test_positive_approval_forbidden_when_mandatory_evidence_missing`
- **Limitations & Gaps:**
  - Evidence existence is evaluated via keyword presence in active context (`Schedule D`, `data residency`, etc.); structured metadata flags on documents could complement text-based heuristics.

---

### L2 — Answer-State Layer (Precedence Machine)

- **Documented Purpose:** `lore.md` §10. "Deterministic 9-state machine with strict precedence order. Resolves final verdict and single action directive."
- **Implementation File:** [`backend/apps/governance/layers.py:537-598`](file:///e:/LORE/backend/apps/governance/layers.py#L537-L598)
- **Class / Method:** `AnswerStateLayer.resolve_state(...)`
- **Pipeline Stage:** Stage 6.
- **Contract Definition:** [`backend/apps/governance/contract.py:15-38`](file:///e:/LORE/backend/apps/governance/contract.py#L15-L38)
- **Precedence Order & Invariant Mapping:**

| Precedence | State (Verdict) | Directive | Trigger Condition |
|---|---|---|---|
| **1 (Highest)** | `denied` | `stop` | L7 permission check failed (`is_denied = True`). |
| **2** | `violation` | `stop` | Explicit negative prohibition breached (`is_violation = True`). |
| **3** | `conflicting` | `ask_user` | L6 unresolved contradiction between equal-rank authoritative sources. |
| **4** | `insufficient` | `ask_user` | L3 mandatory evidence requirement missing (`is_sufficient = False`). |
| **5** | `abstain` | `ask_user` | Relevance score in uncertainty band [0.45, 0.55]. |
| **6** | `human_review` | `escalate` | L1 critical risk query requiring mandatory human review. |
| **7** | `qualified` | `proceed_and_cite` | L4 exception applied, L5 stale rule, or L6 subordinate override. |
| **8** | `supported` | `proceed_and_cite` | All mandatory evidence present and valid (`chunks_count > 0`). |
| **9 (Lowest)** | `no_knowledge` | `proceed` | Zero candidate chunks found in active workspace. |

- **Execution Mode:** 100% Deterministic Precedence Tree.
- **Test Coverage:**
  - `tests/test_governance_p1.py::TestCanonicalResultContract::test_valid_verdict_directive_pairings`
  - `tests/test_governance_p1.py::TestCanonicalResultContract::test_invalid_verdict_directive_pairing_fails`

---

### L1 — Decision Intelligence Layer

- **Documented Purpose:** `lore.md` §4 L1. "Classifies incoming queries into decision types, mapping mandatory evidence requirements and designating escalation targets."
- **Implementation File:** [`backend/apps/governance/layers.py:90-167`](file:///e:/LORE/backend/apps/governance/layers.py#L90-L167)
- **Class / Method:** `DecisionIntelligenceLayer.classify(query)`
- **Pipeline Stage:** Stage 1.
- **Catalog Structure:**
  - `statutory_compliance`: Risk `critical`, escalation `legal_counsel`.
  - `vendor_approval`: Risk `high`, escalation `security_team`.
  - `data_processing`: Risk `high`, escalation `compliance_officer`.
  - `deployment_approval`: Risk `medium`, escalation `engineering_lead`.
  - `policy_compliance`: Risk `medium`, escalation `compliance_officer`.
  - `code_change`: Risk `low`, escalation `tech_lead`.
  - `general_inquiry`: Risk `low`, escalation `workspace_admin`.
- **Execution Mode:** Deterministic Regex & Lexical Token Matching.
- **Test Coverage:** Verified in `test_governance_p1.py` and benchmark harness E01-E10.

---

### L0 — Observability & Lineage Layer

- **Documented Purpose:** `lore.md` §4 L0. "Freshness, decision traces, audit events, and latency metrics."
- **Implementation File:** [`backend/apps/governance/layers.py:602-654`](file:///e:/LORE/backend/apps/governance/layers.py#L602-L654)
- **Class / Method:** `ObservabilityLayer.record_decision(...)`
- **Pipeline Stage:** Stage 9 (Final persistence stage).
- **Relational Data Models:**
  - [`DecisionRecord`](file:///e:/LORE/backend/apps/decisions/models.py#L5-L35): Persists `trace_id`, `decision_type`, `state`, `directive`, `evidence_found`, `evidence_missing`, `conflicts_resolved`, `citations`, `token_count`.
  - [`AuditEvent`](file:///e:/LORE/backend/apps/audit/models.py): Append-only audit record (`event_type='decision_recorded'`).
- **Telemetry Metrics Recorded:**
  - Stage execution timings in milliseconds: `l7_permission_ms`, `l1_intelligence_ms`, `l5_temporal_ms`, `l4_exception_ms`, `l6_authority_ms`, `l3_sufficiency_ms`.
- **Execution Mode:** Asynchronous / Synchronous Relational DB Write.
- **Test Coverage:**
  - `tests/test_evaluation_and_resilience_p3.py::test_telemetry_snapshot_and_api_endpoint`
  - `tests/test_enterprise_pipeline.py::test_governed_rag_query_with_citations`

---

### Canonical Contract Validation Gate (`contract.py`)

- **Documented Purpose:** `docs/GOVERNANCE_CONTRACT.md`. "Mathematical enforcement of invariant rules on every response before emission. Fail-closed on violation."
- **Implementation File:** [`backend/apps/governance/contract.py`](file:///e:/LORE/backend/apps/governance/contract.py)
- **Functions:** `validate_canonical_envelope(envelope)`, `fail_closed_envelope(...)`
- **Enforced Invariants:**
  1. `state` must be one of the 9 canonical values.
  2. `directive` must be one of the 5 canonical values.
  3. `state` and `directive` must match the canonical mapping table.
  4. If `evidence_missing` contains unsatisfied mandatory items, `state` cannot be `supported`.
  5. If `state == 'denied'`, citations must be empty (zero leakage).
  6. Any contract violation triggers `fail_closed_envelope()`, returning `state='violation'`, `directive='stop'` with zero document content.
- **Test Coverage:**
  - `tests/test_governance_p1.py::TestCanonicalResultContract` (4 tests).
