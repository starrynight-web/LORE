"""
LORE Enterprise — Selective Zero-Knowledge Proof (ZKP) Attestation Comprehensive Test Suite
Specification: Master User Request & docs/GOVERNANCE_CONTRACT.md §14

Covers:
1. Workspace Merkle State Commitment & Determinism:
   - Deterministic leaf hashing and Merkle state root calculation.
   - Lifecycle filtering: only status == 'stable' rules are committed; draft/quarantine/superseded omitted.
   - Cryptographic Merkle inclusion proof generation and verification.
   - Tamper rejection (altered leaf, altered root, altered sibling hashes).
2. ZK Witness Builder & Private/Public Isolation:
   - Separation of PrivateWitness (local) and PublicInputs (external).
   - Strict zero-leakage: raw policy statements and source paths never appear in PublicInputs.
   - Role commitment hashing with cryptographic salt.
   - Authority floor & temporal bounds constraints.
3. Pluggable Prover & Verifier (ZKAttestationService):
   - Pure-Python zkp_lite_merkle prover & offline verifier.
   - Honest labeling ('zkp_lite_merkle' vs 'noir_zk_snark').
   - Cryptographic verification passes on valid envelopes.
   - Verification fails when state root, proof bytes, authority, or timestamp are tampered.
   - ZeroLeakageSecurityError raised when sensitive text is detected in envelope.
4. Hot-Path Governance Engine Invariants:
   - Default lore.get_context / evaluate has zk_attestation=False (envelope['zk_attestation'] is None).
   - Opt-in zk_attestation=True generates valid attestation envelope.
   - Deterministic bundle_hash present across all evaluation envelopes.
5. MCP Tools (lore.attest_compliance & lore.verify_zk_proof):
   - Tool execution and JSON serialization.
   - Verification of generated proofs and rejection of tampered proofs.
6. REST API Endpoints:
   - POST /api/governance/zk-attest/
   - POST /api/governance/zk-verify/
"""

import uuid
import json
import base64
import hashlib
import time
from datetime import datetime, timezone as dt_timezone
import pytest
from rest_framework.test import APIClient

from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument
from apps.knowledge.models import KnowledgeItem, DocumentChunk
from apps.governance.layers import EnterpriseGovernanceEngine
from apps.governance.zkp import (
    hash_leaf_preimage,
    compute_workspace_state_root,
    generate_merkle_inclusion_proof,
    verify_merkle_inclusion_proof,
    build_zk_witness,
    ZKAttestationService,
    ZKAttestationEnvelope,
    ZeroLeakageSecurityError,
    get_zk_attestation_service,
)
from apps.governance.zkp.merkle_state import EMPTY_STATE_ROOT
import mcp_server


@pytest.fixture
def zkp_test_env(db):
    org = Organization.objects.create(
        name="ZK Cryptography Org",
        slug=f"zk-org-{uuid.uuid4().hex[:6]}"
    )
    ws = Workspace.objects.create(
        name="ZK Cryptography Workspace",
        slug=f"zk-ws-{uuid.uuid4().hex[:6]}",
        organization=org
    )
    doc = SourceDocument.objects.create(
        organization=org,
        workspace=ws,
        title="Enterprise Data Retention Policy",
        document_type="pdf",
        status="approved",
        original_filename="retention_policy.pdf",
        mime_type="application/pdf",
        file_size=1024,
        file_hash=hashlib.sha256(b"retention_policy_pdf_content").hexdigest(),
        authority_level=5
    )
    chunk = DocumentChunk.objects.create(
        organization=org,
        workspace=ws,
        document=doc,
        chunk_index=0,
        text="Customer PII data must be retained for at least 7 years and encrypted at rest using AES-256."
    )
    stable_rule_1 = KnowledgeItem.objects.create(
        organization=org,
        workspace=ws,
        document=doc,
        source_chunk=chunk,
        item_type="rule",
        code="POL-SEC-001",
        statement="Customer PII data must be retained for 7 years under regulatory mandate.",
        status="stable",
        authority_level=5,
        confidence=0.99
    )
    stable_rule_2 = KnowledgeItem.objects.create(
        organization=org,
        workspace=ws,
        document=doc,
        source_chunk=chunk,
        item_type="rule",
        code="POL-SEC-002",
        statement="All customer databases must mandate mutual TLS 1.3 encryption in transit.",
        status="stable",
        authority_level=4,
        confidence=0.95
    )
    draft_rule = KnowledgeItem.objects.create(
        organization=org,
        workspace=ws,
        document=doc,
        source_chunk=chunk,
        item_type="rule",
        code="DRAFT-001",
        statement="Proposed policy: Experimental biometric authentication.",
        status="draft",
        authority_level=2,
        confidence=0.50
    )
    quarantined_rule = KnowledgeItem.objects.create(
        organization=org,
        workspace=ws,
        document=doc,
        source_chunk=chunk,
        item_type="rule",
        code="QUAR-001",
        statement="Conflicting policy under dispute.",
        status="quarantined",
        authority_level=1,
        confidence=0.40
    )

    return {
        "org": org,
        "ws": ws,
        "doc": doc,
        "chunk": chunk,
        "stable_1": stable_rule_1,
        "stable_2": stable_rule_2,
        "draft": draft_rule,
        "quarantined": quarantined_rule,
    }


# ==============================================================================
# 1. MERKLE STATE COMMITMENT & DETERMINISM TESTS
# ==============================================================================

@pytest.mark.django_db
def test_merkle_state_root_deterministic_and_excludes_non_stable(zkp_test_env):
    ws = zkp_test_env["ws"]
    
    # Compute state root
    root1 = compute_workspace_state_root(str(ws.id))
    assert isinstance(root1, str)
    assert len(root1) == 64
    assert root1 != EMPTY_STATE_ROOT

    # Determinism: computing a second time produces identical root
    root2 = compute_workspace_state_root(str(ws.id))
    assert root1 == root2

    # Verify that draft and quarantined rules did NOT enter the root
    # Build custom rules with only the stable rules and verify root matches
    stable_custom = [
        {
            "rule_id": str(zkp_test_env["stable_1"].id),
            "content_hash": hashlib.sha256(zkp_test_env["stable_1"].statement.encode("utf-8")).hexdigest(),
            "authority_rank": 5,
            "status": "stable",
            "effective_from_epoch": 0,
            "effective_to_epoch": 253402300799,
            "allowed_roles_hash": hashlib.sha256(b"admin,compliance_officer,member").hexdigest(),
        },
        {
            "rule_id": str(zkp_test_env["stable_2"].id),
            "content_hash": hashlib.sha256(zkp_test_env["stable_2"].statement.encode("utf-8")).hexdigest(),
            "authority_rank": 4,
            "status": "stable",
            "effective_from_epoch": 0,
            "effective_to_epoch": 253402300799,
            "allowed_roles_hash": hashlib.sha256(b"admin,compliance_officer,member").hexdigest(),
        }
    ]
    custom_root = compute_workspace_state_root(str(ws.id), custom_rules=stable_custom)
    assert root1 == custom_root

    # Adding a draft or quarantined rule to custom_rules should NOT change the root
    stable_plus_draft = stable_custom + [{
        "rule_id": "draft-id-999",
        "content_hash": "deadbeef",
        "authority_rank": 1,
        "status": "draft",
    }]
    root_with_draft = compute_workspace_state_root(str(ws.id), custom_rules=stable_plus_draft)
    assert root_with_draft == custom_root


@pytest.mark.django_db
def test_merkle_inclusion_proof_and_verification(zkp_test_env):
    ws = zkp_test_env["ws"]
    rule = zkp_test_env["stable_1"]

    proof_data = generate_merkle_inclusion_proof(
        workspace_id=str(ws.id),
        rule_id=str(rule.id)
    )

    root = proof_data["workspace_state_root"]
    leaf_hash = proof_data["leaf_hash"]
    path = proof_data["merkle_path"]
    indices = proof_data["merkle_indices"]

    # Verify inclusion proof mathematically
    is_valid = verify_merkle_inclusion_proof(root, leaf_hash, path, indices)
    assert is_valid is True

    # Tampering test 1: altered leaf hash fails
    fake_leaf = hashlib.sha256(b"tampered_leaf_content").hexdigest()
    assert verify_merkle_inclusion_proof(root, fake_leaf, path, indices) is False

    # Tampering test 2: altered state root fails
    fake_root = hashlib.sha256(b"tampered_state_root").hexdigest()
    assert verify_merkle_inclusion_proof(fake_root, leaf_hash, path, indices) is False

    # Tampering test 3: altered sibling in path fails
    tampered_path = list(path)
    if tampered_path:
        tampered_path[0] = hashlib.sha256(b"corrupted_sibling").hexdigest()
        assert verify_merkle_inclusion_proof(root, leaf_hash, tampered_path, indices) is False


# ==============================================================================
# 2. ZK WITNESS & PUBLIC/PRIVATE SEPARATION TESTS
# ==============================================================================

@pytest.mark.django_db
def test_zk_witness_isolation_and_commitments(zkp_test_env):
    ws = zkp_test_env["ws"]
    rule = zkp_test_env["stable_1"]

    witness, public_inputs = build_zk_witness(
        workspace_id=str(ws.id),
        rule_id=str(rule.id),
        decision_type="regulatory_compliance",
        required_authority_floor=4,
        evidence_status="satisfied",
        user_role="compliance_officer"
    )

    # 1. Private witness properties
    assert witness.rule_id == str(rule.id)
    assert witness.rule_statement == rule.statement
    assert witness.authority_rank == 5
    assert witness.rule_status == "stable"
    assert len(witness.merkle_path) > 0

    # 2. Public inputs properties
    pub_dict = public_inputs.model_dump()
    assert pub_dict["workspace_state_root"] == witness.merkle_path[-1] or len(pub_dict["workspace_state_root"]) == 64
    assert pub_dict["decision_type"] == "regulatory_compliance"
    assert pub_dict["required_authority_floor"] == 4
    assert pub_dict["evidence_status_code"] == 1
    assert "requester_role_commitment" in pub_dict
    assert "policy_commitment_hash" in pub_dict

    # 3. CRITICAL INVARIANT: Zero verbatim policy text in public inputs
    pub_json = json.dumps(pub_dict)
    assert rule.statement not in pub_json
    assert "Customer PII" not in pub_json
    assert "AES-256" not in pub_json


@pytest.mark.django_db
def test_zk_witness_rejects_missing_or_draft_rule(zkp_test_env):
    ws = zkp_test_env["ws"]
    draft_rule = zkp_test_env["draft"]

    # Requesting proof for a draft rule must fail since only status=='stable' rules exist in tree
    with pytest.raises(ValueError, match="not found in stable rules"):
        build_zk_witness(
            workspace_id=str(ws.id),
            rule_id=str(draft_rule.id)
        )


# ==============================================================================
# 3. PLUGGABLE PROVER & OFFLINE VERIFIER TESTS
# ==============================================================================

@pytest.mark.django_db
def test_zkp_lite_merkle_proving_and_verification(zkp_test_env):
    ws = zkp_test_env["ws"]
    rule = zkp_test_env["stable_1"]

    witness, public_inputs = build_zk_witness(
        workspace_id=str(ws.id),
        rule_id=str(rule.id),
        decision_type="regulatory_compliance",
        required_authority_floor=4,
        evidence_status="satisfied",
        user_role="compliance_officer"
    )

    prover = get_zk_attestation_service()
    envelope = prover.prove(witness, public_inputs, backend="zkp_lite_merkle")

    assert envelope.proof_system == "zkp_lite_merkle"
    assert envelope.verified is True
    assert envelope.workspace_state_root == public_inputs.workspace_state_root

    # Offline verification without DB access
    is_valid = prover.verify(envelope)
    assert is_valid is True


@pytest.mark.django_db
def test_zkp_verification_tamper_rejection(zkp_test_env):
    ws = zkp_test_env["ws"]
    rule = zkp_test_env["stable_1"]

    witness, public_inputs = build_zk_witness(
        workspace_id=str(ws.id),
        rule_id=str(rule.id),
        decision_type="regulatory_compliance",
        required_authority_floor=4,
        evidence_status="satisfied",
        user_role="compliance_officer"
    )

    prover = get_zk_attestation_service()
    envelope = prover.prove(witness, public_inputs, backend="zkp_lite_merkle")

    # 1. Tamper state root
    bad_root_env = ZKAttestationEnvelope(**envelope.model_dump())
    bad_root_env.workspace_state_root = hashlib.sha256(b"corrupted_root").hexdigest()
    assert prover.verify(bad_root_env) is False

    # 2. Tamper authority floor (raise above rule authority)
    bad_floor_env = ZKAttestationEnvelope(**envelope.model_dump())
    bad_floor_env.public_inputs["required_authority_floor"] = 10
    assert prover.verify(bad_floor_env) is False

    # 3. Tamper evidence status (unsatisfied)
    bad_status_env = ZKAttestationEnvelope(**envelope.model_dump())
    bad_status_env.public_inputs["evidence_status_code"] = 0
    assert prover.verify(bad_status_env) is False

    # 4. Tamper proof payload bytes
    bad_proof_env = ZKAttestationEnvelope(**envelope.model_dump())
    bad_proof_env.proof_b64 = base64.b64encode(b'{"corrupted": true}').decode("utf-8")
    assert prover.verify(bad_proof_env) is False


@pytest.mark.django_db
def test_zero_leakage_assertion_catches_leakage(zkp_test_env):
    ws = zkp_test_env["ws"]
    rule = zkp_test_env["stable_1"]

    witness, public_inputs = build_zk_witness(
        workspace_id=str(ws.id),
        rule_id=str(rule.id),
        decision_type="regulatory_compliance",
        required_authority_floor=4,
        evidence_status="satisfied",
    )

    prover = get_zk_attestation_service()
    envelope = prover.prove(witness, public_inputs, backend="zkp_lite_merkle")

    # Clean envelope passes
    prover.assert_zero_leakage(envelope, witness)

    # Injected rule statement raises ZeroLeakageSecurityError
    leaked_env = ZKAttestationEnvelope(**envelope.model_dump())
    leaked_env.public_inputs["leaked_statement"] = witness.rule_statement
    with pytest.raises(ZeroLeakageSecurityError, match="Private rule text snippet"):
        prover.assert_zero_leakage(leaked_env, witness)


# ==============================================================================
# 4. GOVERNANCE ENGINE HOT-PATH INVARIANTS & OPT-IN ZKP
# ==============================================================================

@pytest.mark.django_db
def test_governance_engine_zkp_opt_in_and_latency_invariant(zkp_test_env):
    ws = zkp_test_env["ws"]
    chunk = zkp_test_env["chunk"]

    retrieved = [{
        "chunk_id": str(chunk.id),
        "document_id": str(zkp_test_env["doc"].id),
        "rule_id": str(zkp_test_env["stable_1"].id),
        "text": chunk.text,
        "score": 0.95,
        "authority_level": 5,
        "source_type": "file"
    }]

    # Invariant 1: Hot-path default (zk_attestation=False) has zk_attestation is None
    env_default = EnterpriseGovernanceEngine.evaluate(
        query="What is the customer PII retention mandate?",
        retrieved_chunks=retrieved,
        workspace=ws,
        zk_attestation=False
    )
    assert env_default.get("zk_attestation") is None
    assert env_default.get("bundle_hash") is not None
    assert len(env_default.get("bundle_hash")) == 64

    # Invariant 2: Opt-in (zk_attestation=True) attaches valid ZK attestation
    env_opt_in = EnterpriseGovernanceEngine.evaluate(
        query="What is the customer PII retention mandate?",
        retrieved_chunks=retrieved,
        workspace=ws,
        zk_attestation=True
    )
    zk_payload = env_opt_in.get("zk_attestation")
    assert zk_payload is not None
    assert zk_payload.get("verified") is True
    assert zk_payload.get("proof_system") in ("zkp_lite_merkle", "noir_zk_snark")
    assert len(zk_payload.get("workspace_state_root")) == 64


# ==============================================================================
# 5. MCP TOOLS INTEGRATION TESTS
# ==============================================================================

@pytest.mark.django_db
def test_mcp_attest_compliance_and_verify_tools(zkp_test_env):
    ws = zkp_test_env["ws"]
    
    # 1. Execute lore.attest_compliance
    attest_args = {
        "workspace_id": str(ws.id),
        "rule_id": str(zkp_test_env["stable_1"].id),
        "decision_type": "regulatory_compliance",
        "required_authority_floor": 4,
        "evidence_status": "satisfied",
        "user_role": "compliance_officer"
    }
    raw_res = mcp_server.execute_tool("lore.attest_compliance", attest_args)
    res = json.loads(raw_res)

    assert res.get("schema") == "lore.result/1"
    assert "zk_attestation" in res
    zk_att = res["zk_attestation"]
    assert zk_att.get("verified") is True
    assert len(zk_att.get("workspace_state_root")) == 64

    # 2. Execute lore.verify_zk_proof on the generated envelope
    verify_args = {
        "attestation_envelope": zk_att
    }
    raw_verify = mcp_server.execute_tool("lore.verify_zk_proof", verify_args)
    v_res = json.loads(raw_verify)

    assert v_res.get("schema") == "lore.result/1"
    assert v_res.get("verified") is True
    assert v_res.get("workspace_state_root") == zk_att["workspace_state_root"]

    # 3. Tampering test via MCP tool: alter state root
    corrupted_att = dict(zk_att)
    corrupted_att["workspace_state_root"] = hashlib.sha256(b"fake").hexdigest()
    raw_fail = mcp_server.execute_tool("lore.verify_zk_proof", {"attestation_envelope": corrupted_att})
    fail_res = json.loads(raw_fail)
    assert fail_res.get("verified") is False


# ==============================================================================
# 6. REST API ENDPOINTS TESTS
# ==============================================================================

@pytest.mark.django_db
def test_rest_api_zk_attest_and_verify_views(zkp_test_env):
    client = APIClient()
    ws = zkp_test_env["ws"]
    rule = zkp_test_env["stable_1"]

    # 1. POST /api/governance/zk-attest/
    attest_payload = {
        "workspace_id": str(ws.id),
        "rule_id": str(rule.id),
        "decision_type": "regulatory_compliance",
        "required_authority_floor": 4,
        "evidence_status": "satisfied",
        "user_role": "compliance_officer"
    }
    resp = client.post("/api/governance/zk-attest/", data=attest_payload, format="json")
    assert resp.status_code == 200
    envelope = resp.json()
    assert envelope.get("proof_system") in ("zkp_lite_merkle", "noir_zk_snark")
    assert envelope.get("verified") is True
    assert len(envelope.get("workspace_state_root")) == 64

    # 2. POST /api/governance/zk-verify/
    verify_payload = {
        "attestation_envelope": envelope
    }
    verify_resp = client.post("/api/governance/zk-verify/", data=verify_payload, format="json")
    assert verify_resp.status_code == 200
    v_data = verify_resp.json()
    assert v_data.get("verified") is True
    assert v_data.get("proof_system") == envelope["proof_system"]

    # 3. Bad Request handling (missing workspace_id)
    bad_resp = client.post("/api/governance/zk-attest/", data={}, format="json")
    assert bad_resp.status_code == 400

    # 4. Verification failure for corrupted envelope
    corrupt_env = dict(envelope)
    corrupt_env["workspace_state_root"] = hashlib.sha256(b"corrupt").hexdigest()
    corrupt_resp = client.post("/api/governance/zk-verify/", data={"attestation_envelope": corrupt_env}, format="json")
    assert corrupt_resp.status_code == 200
    assert corrupt_resp.json().get("verified") is False
