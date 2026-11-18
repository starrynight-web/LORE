# LORE Enterprise — Canonical Governance Result Contract
**Document Version:** 2.0.0  
**Specification Reference:** `lore.md` (v3.0 §3, §4, §10), Master Prompt P1 §3–§8  
**Canonical Schema Identifier:** `lore.result/2` (with full backward compatibility for `lore.result/1`)

---

## 1. Executive Summary & Purpose

The LORE Enterprise Canonical Result Contract provides a deterministic, typed, auditable interface across API, retrieval, governance layers, and Model Context Protocol (MCP) tool boundaries.

The contract establishes strict invariants:
1. **Separation of Retrieval Ranking from Governance:** Retrieval (`ContextReranker`) scores purely on semantic and lexical relevance. Authority is an arbitration mechanism used exclusively by Layer 6 (Authority Layer) when deciding between competing relevant evidence—authority never turns irrelevant or out-of-scope evidence into a valid decision.
2. **Deterministic 9-State Precedence Ladder:** Exactly 9 discrete verdict states mapped to 5 action directives. Malformed states, invalid state-directive pairings, or unverified outputs never default to approval.
3. **Fail-Closed Governance Gate:** Any internal error, missing mandatory evidence, equal-authority contradiction, or dependency failure strictly fails closed to safe escalation states (`insufficient` or `conflicting`).
4. **Stable-Only Serving:** Draft, quarantined, failed, and unreviewed records are barred from entering live authoritative decisions.
5. **Untrusted Data Encapsulation:** Retrieved chunks are treated as untrusted data within `<untrusted_evidence_data>` tags to prevent prompt injection.

---

## 2. Canonical Verdicts and Directives Matrix

LORE enforces the **Canonical Verdict-Directive Invariant Matrix**. Any response violating this matrix is rejected by `validate_canonical_envelope()` and converted to a typed fail-closed envelope.

| Precedence | Verdict (`state`) | Canonical Directive (`directive`) | Semantics & Trigger Conditions |
|---|---|---|---|
| **1 (Highest)** | `denied` | `stop` | L7 Permission Layer: Requester is not authorized to access governing records. |
| **2** | `violation` | `stop` | Proposal explicitly breaches a MUST or MUST-NOT statutory or organizational rule. |
| **3** | `conflicting` | `ask_user` | L6 Authority Layer: Contradictory records exist at equal authority without supersession. LORE refuses to guess. |
| **4** | `insufficient` | `ask_user` | L3 Sufficiency Layer: Mandatory evidence checklist has items missing, pending, or unverified. |
| **5** | `abstain` | `ask_user` | Evidence exists but model/classifier falls into the uncertainty band (0.45–0.55). |
| **6** | `human_review` | `escalate` | L1 Intelligence Layer: Critical decision type requires designated human sign-off. |
| **7** | `qualified` | `proceed_and_cite` | Consistent evidence found, but subject to an active L4 exception, L5 stale rule, or superseded claim. |
| **8** | `supported` | `proceed_and_cite` | All mandatory evidence requirements satisfied with active, consistent, verified records. |
| **9 (Lowest)** | `no_knowledge` | `proceed` | No governed documents or applicable rules exist in the active authorized workspace. |

---

## 3. Explicit Item-Level Evidence Statuses

Evidence requirements in L3 (`EvidenceSufficiencyLayer`) use explicit, typed statuses:

- `satisfied`: Verified evidence found in active, published, authorized records.
- `partial`: Fragmentary evidence found; insufficient for mandatory sign-off.
- `missing`: Mandatory requirement completely absent from retrieved records.
- `pending`: Evidence is in progress (e.g., vendor security assessment pending audit).
- `insufficient_authority`: Supporting text exists, but only in informal sources (e.g. Rank 1/2 wiki) whereas the decision type mandates Rank $\ge 4$.
- `expired`: Governing document has passed its `expiration_date`.
- `conflicting`: Multiple active sources make contradictory claims regarding this requirement.
- `unavailable`: Evidence exists but cannot be accessed by the current requester under L7 permissions (withheld without leaking protected content).

**Invariant:** A verdict of `supported` or `qualified` is **strictly impossible** if any mandatory requirement has a status other than `satisfied`.

---

## 4. Canonical JSON Envelope Specification (`lore.result/2`)

```json
{
  "schema": "lore.result/2",
  "state": "supported | qualified | insufficient | conflicting | abstain | human_review | violation | denied | no_knowledge",
  "directive": "proceed_and_cite | proceed | ask_user | escalate | stop",
  "answer": "Grounded, anti-hallucination factual synthesis text...",
  "decision_type": "vendor_approval | data_processing | statutory_compliance | deployment_approval | policy_compliance | code_change | general_inquiry",
  "escalation_target": "security_team | compliance_officer | legal_counsel | engineering_lead | workspace_admin",
  "risk_level": "low | medium | high | critical",
  "evidence_found": [
    {
      "document_id": "UUID",
      "document_title": "String",
      "authority_level": 1-7,
      "page_number": 1,
      "score": 0.892,
      "heading": "String",
      "snippet": "Verifiable excerpt..."
    }
  ],
  "evidence_missing": [
    {
      "requirement": "executed_data_residency_addendum",
      "mandatory": true,
      "status": "missing | pending | expired | insufficient_authority | unavailable",
      "description": "Specific missing governance proof..."
    }
  ],
  "conflicts_resolved": [
    {
      "informal_claim": "String",
      "authoritative_source": "String",
      "resolution": "authority_dominance | version_supersession",
      "note": "Reasoning..."
    }
  ],
  "exceptions_applied": [
    {
      "exception_id": "UUID",
      "rule_code": "SEC-042",
      "scope_type": "vendor",
      "scope_value": "CloudBox",
      "justification": "Approved emergency migration",
      "approved_by": "VP Security",
      "window_end": "2026-12-31T23:59:59Z"
    }
  ],
  "citations": [
    {
      "citation_id": "cit-abcdef",
      "document_id": "UUID",
      "document_title": "String",
      "document_version": 2,
      "page_number": 14,
      "heading_path": "Section 4.1 > Encryption at Rest",
      "passage": "Exact text passage...",
      "authority_level": 7
    }
  ],
  "notes": ["Chronological trace notes across L7 -> L0..."],
  "decision_id": "dec-a1b2c3d4",
  "trace_id": "trace-e5f6g7h8",
  "token_count": 482,
  "llm_provider": "groq | deterministic_synthesis",
  "llm_model": "gpt-oss-120B | deterministic-citation-engine",
  "anti_hallucination_active": true,
  "layers_breakdown": {
    "l7_permission": { "status": "passed", "denials": [] },
    "l1_decision_intelligence": { "decision_type": "vendor_approval", "escalation": "security_team", "risk": "high" },
    "l6_authority": { "conflicts_count": 1, "unresolved_tie": false },
    "l5_temporal": { "stale_data": false, "temporal_notes": [] },
    "l4_exceptions": { "applied_count": 0, "exceptions": [] },
    "l3_sufficiency": { "is_sufficient": true, "missing_count": 0 },
    "l2_answer_state": { "final_state": "supported", "directive": "proceed_and_cite" },
    "l0_observability": { "trace_id": "trace-e5f6g7h8", "timings_ms": { "l7_permission_ms": 1.2, "l1_intelligence_ms": 0.4 } }
  }
}
```

---

## 5. Backward Compatibility (`lore.result/1`)

`lore.result/1` is fully supported by consumers:
- The alias field `items` is retained alongside `evidence_found`.
- `validate_canonical_envelope()` accepts both `lore.result/1` and `lore.result/2`.
- Response structure maintains existing key naming, ensuring legacy API and frontend consumers continue to work seamlessly.

---

## 6. Verification and Validation Procedures

All boundaries (DRF views, Celery workers, MCP tools, and test harnesses) invoke:
1. `apps.governance.contract.validate_canonical_envelope(envelope)` before returning responses.
2. In case of unexpected runtime or schema exceptions, `fail_closed_envelope()` guarantees an invariant-preserving fallback with `error_category` and an auditable trace ID.

---

## 7. Selective Zero-Knowledge Proof (ZKP) Attestation Layer

LORE Enterprise provides an opt-in Selective Zero-Knowledge Proof (ZKP) attestation subsystem (`apps.governance.zkp`), upgrading LORE's baseline `ZKP-lite` (SHA-256 `bundle_hash` & Merkle provenance) into mathematically verifiable zero-knowledge policy and lineage attestations for cross-organization compliance checks and external audit exports.

### 7.1 Cryptographic Separation of Concerns

1. **Workspace Policy Merkle State Commitment (`workspace_state_root`)**:
   - Built over all `status == "stable"` rules in the workspace.
   - Non-stable rules (`draft`, `quarantine`, `superseded`, `stale`) are strictly excluded.
   - Leaf preimage:
     $$\text{Leaf} = \text{SHA256}(\text{rule\_id} \parallel \text{content\_hash} \parallel \text{authority\_rank} \parallel \text{status} \parallel \text{effective\_from} \parallel \text{effective\_to} \parallel \text{allowed\_roles\_hash})$$
   - Padded with deterministic empty leaf hashes to powers of two.

2. **Private Witness Isolation**:
   - `PrivateWitness` holds verbatim rule statements, confidential source paths, unhashed roles, and Merkle sibling routes.
   - **Critical Security Invariant**: The private witness NEVER leaves the prover boundary and is never serialized into public envelopes or API responses.

3. **Public Inputs**:
   - Verifiable commitments including `workspace_state_root`, `decision_type`, `evaluation_timestamp`, `required_authority_floor`, `evidence_status_code`, and `requester_role_commitment` (salted hash).
   - Zero proprietary statements, contract clauses, or confidential file paths are disclosed.

4. **Dual Proving Architectures & Honest Labeling**:
   - **`noir` / `noir_zk_snark`**: Full zero-knowledge SNARK circuit compiled and verified via Noir (`nargo` / Barretenberg) when available.
   - **`zkp_lite_merkle`**: Pure-Python / Rust fallback verifying deterministic Merkle inclusion, temporal validity windows, authority floors, and role authorizations without external toolchain dependencies.
   - Honest labeling ensures `proof_system` accurately identifies the underlying cryptographic proof mechanism.

### 7.2 Integration with Canonical Envelopes (`lore.result/1` & `lore.result/2`)

The attestation envelope is attached via the optional nullable `zk_attestation` property:

```json
{
  "schema": "lore.result/1",
  "state": "supported",
  "directive": "proceed_and_cite",
  "bundle_hash": "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
  "zk_attestation": {
    "proof_system": "zkp_lite_merkle",
    "workspace_state_root": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "public_inputs": {
      "decision_type": "regulatory_compliance",
      "required_authority_floor": 4,
      "evidence_status_code": 1,
      "evaluation_timestamp": 1731888000,
      "requester_role_commitment": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
      "policy_commitment_hash": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a"
    },
    "proof_b64": "eyJwb2xpY3lfaW52YXJpYW50cyI6IHRydWV9...",
    "verified": true,
    "generated_at": "2026-11-17T23:30:00Z"
  }
}
```

### 7.3 Hot-Path Latency Invariant

To ensure sub-second retrieval performance across everyday IDE workflows:
- Default queries (`lore.get_context`, `lore.check_compliance`) evaluate with `zk_attestation=False` (returning `zk_attestation: null`).
- Proving occurs strictly on-demand when `zk_attestation=True` or via dedicated endpoints (`lore.attest_compliance`, `POST /api/governance/zk-attest/`).
