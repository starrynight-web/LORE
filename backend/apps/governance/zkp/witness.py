"""
LORE Enterprise — Zero-Knowledge Witness & Public Inputs Schema (docs/GOVERNANCE_CONTRACT.md §14)
Enforces cryptographic separation between Private Witness (kept strictly local)
and Public Inputs (verifiable without leaking proprietary statements or source paths).
"""

import time
import uuid
import hashlib
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from .merkle_state import (
    generate_merkle_inclusion_proof,
    hash_leaf_preimage,
)


class PrivateWitness(BaseModel):
    """
    Zero-Knowledge Private Witness.
    CRITICAL SECURITY INVARIANT: This object NEVER leaves the prover boundary.
    Contains raw rule statements, exact paths, unhashed roles, and Merkle sibling routes.
    """
    rule_id: str
    rule_code: str
    rule_statement: str
    source_path: str
    content_hash: str
    authority_rank: int
    rule_status: str
    effective_from_epoch: int
    effective_to_epoch: int
    allowed_roles: List[str]
    matched_role: str
    role_salt: str
    merkle_path: List[str]
    merkle_indices: List[int]
    evidence_excerpt_hash: str
    leaf_hash: str


class PublicInputs(BaseModel):
    """
    Cryptographic Public Inputs.
    Safe to share with external auditors, counterparties, and clients.
    Contains commitments, thresholds, and roots, but ZERO verbatim policy text.
    """
    workspace_state_root: str
    decision_type: str
    evaluation_timestamp: int
    required_authority_floor: int
    evidence_status_code: int = 1  # 1: SATISFIED, 0: UNSATISFIED
    requester_role_commitment: str  # SHA256(matched_role:role_salt)
    policy_commitment_hash: str  # SHA256(decision_type:workspace_state_root:evaluation_timestamp)


class ZKAttestationEnvelope(BaseModel):
    """
    Verifiable Zero-Knowledge Attestation Envelope attached to lore.result/1.
    """
    proof_system: str = Field(description="Cryptographic proof system: 'noir', 'zk_snark', or 'zkp_lite_merkle'")
    workspace_state_root: str
    public_inputs: Dict[str, Any]
    proof_b64: str
    verified: bool = False
    generated_at: str


def build_zk_witness(
    workspace_id: str,
    rule_id: str,
    decision_type: str = "general_inquiry",
    evaluation_timestamp: Optional[int] = None,
    required_authority_floor: int = 4,
    evidence_status: str = "satisfied",
    user_role: str = "member",
    custom_rules: Optional[List[Dict[str, Any]]] = None,
    evidence_excerpt: str = "",
    role_salt: Optional[str] = None,
) -> tuple[PrivateWitness, PublicInputs]:
    """
    Builds a strongly-typed PrivateWitness and PublicInputs pair for ZK proving.
    Ensures that private text is isolated and public commitments are generated.
    """
    eval_ts = evaluation_timestamp if evaluation_timestamp is not None else int(time.time())
    salt = role_salt or uuid.uuid4().hex

    inclusion_data = generate_merkle_inclusion_proof(
        workspace_id=workspace_id,
        rule_id=rule_id,
        custom_rules=custom_rules,
    )

    target_rule = inclusion_data["target_rule"]
    statement = target_rule.get("statement", "")
    content_hash = target_rule.get("content_hash") or hashlib.sha256(statement.encode("utf-8")).hexdigest()
    authority_rank = int(target_rule.get("authority_rank", 3))
    status = str(target_rule.get("status", "stable"))
    eff_from = int(target_rule.get("effective_from_epoch", 0))
    eff_to = int(target_rule.get("effective_to_epoch", 253402300799))
    allowed_roles = target_rule.get("allowed_roles") or ["member", "compliance_officer", "admin"]
    source_path = str(target_rule.get("source_path", "document"))

    # Matched role validation
    clean_user_role = (user_role or "member").lower()
    matched_role = clean_user_role if clean_user_role in allowed_roles else (allowed_roles[0] if allowed_roles else "member")

    # Salted commitment of role
    role_commitment = hashlib.sha256(f"{matched_role}:{salt}".encode("utf-8")).hexdigest()

    # Evidence status code (1 = SATISFIED, 0 = INSUFFICIENT / VIOLATION)
    evidence_status_code = 1 if str(evidence_status).lower() in ("satisfied", "supported", "active") else 0

    # Policy commitment
    root = inclusion_data["workspace_state_root"]
    policy_commitment = hashlib.sha256(f"{decision_type}:{root}:{eval_ts}".encode("utf-8")).hexdigest()
    evidence_excerpt_hash = hashlib.sha256((evidence_excerpt or "").encode("utf-8")).hexdigest()

    private_witness = PrivateWitness(
        rule_id=str(target_rule.get("rule_id", rule_id)),
        rule_code=str(target_rule.get("code", "")),
        rule_statement=statement,
        source_path=source_path,
        content_hash=content_hash,
        authority_rank=authority_rank,
        rule_status=status,
        effective_from_epoch=eff_from,
        effective_to_epoch=eff_to,
        allowed_roles=allowed_roles,
        matched_role=matched_role,
        role_salt=salt,
        merkle_path=inclusion_data["merkle_path"],
        merkle_indices=inclusion_data["merkle_indices"],
        evidence_excerpt_hash=evidence_excerpt_hash,
        leaf_hash=inclusion_data["leaf_hash"],
    )

    public_inputs = PublicInputs(
        workspace_state_root=root,
        decision_type=decision_type,
        evaluation_timestamp=eval_ts,
        required_authority_floor=required_authority_floor,
        evidence_status_code=evidence_status_code,
        requester_role_commitment=role_commitment,
        policy_commitment_hash=policy_commitment,
    )

    return private_witness, public_inputs

