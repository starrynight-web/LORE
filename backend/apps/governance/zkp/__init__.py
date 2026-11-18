"""
LORE Enterprise — Zero-Knowledge Proof (ZKP) Attestation Layer
Provides cryptographic policy and lineage attestations for cross-organization compliance verification.
"""

from .merkle_state import (
    compute_workspace_state_root,
    generate_merkle_inclusion_proof,
    verify_merkle_inclusion_proof,
    hash_leaf_preimage,
    EMPTY_LEAF_HASH,
)
from .witness import (
    PrivateWitness,
    PublicInputs,
    ZKAttestationEnvelope,
    build_zk_witness,
)
from .prover import (
    ZKAttestationService,
    get_zk_attestation_service,
    ZeroLeakageSecurityError,
)

__all__ = [
    "compute_workspace_state_root",
    "generate_merkle_inclusion_proof",
    "verify_merkle_inclusion_proof",
    "hash_leaf_preimage",
    "EMPTY_LEAF_HASH",
    "PrivateWitness",
    "PublicInputs",
    "ZKAttestationEnvelope",
    "build_zk_witness",
    "ZKAttestationService",
    "get_zk_attestation_service",
    "ZeroLeakageSecurityError",
]
