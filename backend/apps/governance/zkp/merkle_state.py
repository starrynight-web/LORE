"""
LORE Enterprise — Workspace Merkle State Tree (docs/GOVERNANCE_CONTRACT.md §14)
Builds deterministic binary Merkle state commitments over status == "stable" rules
and active governance constraints within a workspace.
Supports zero-leakage inclusion proofs for cross-organization policy attestation.
"""

import math
import hashlib
from typing import List, Dict, Any, Optional, Tuple

EMPTY_LEAF_HASH = hashlib.sha256(b"lore:zkp:empty_leaf").hexdigest()
EMPTY_STATE_ROOT = hashlib.sha256((EMPTY_LEAF_HASH + EMPTY_LEAF_HASH).encode("utf-8")).hexdigest()


def hash_leaf_preimage(
    rule_id: str,
    content_hash: str,
    authority_rank: int,
    status: str,
    effective_from_epoch: int,
    effective_to_epoch: int,
    allowed_roles_hash: str,
) -> str:
    """
    Computes deterministic leaf hash for a rule:
    SHA256(rule_id || content_hash || authority_rank || status || effective_from_epoch || effective_to_epoch || allowed_roles_hash)
    """
    preimage = f"{rule_id}:{content_hash}:{authority_rank}:{status}:{effective_from_epoch}:{effective_to_epoch}:{allowed_roles_hash}".encode("utf-8")
    return hashlib.sha256(preimage).hexdigest()


def _pad_leaves_to_power_of_two(leaves: List[str], min_size: int = 8) -> List[str]:
    """Pads leaf list to the next power of 2 with deterministic EMPTY_LEAF_HASH."""
    target_len = max(min_size, 1 << (len(leaves) - 1).bit_length()) if leaves else min_size
    padded = list(leaves)
    while len(padded) < target_len:
        padded.append(EMPTY_LEAF_HASH)
    return padded


def build_merkle_tree(leaves: List[str]) -> Tuple[str, List[List[str]]]:
    """
    Constructs a deterministic binary Merkle tree from a list of leaf hashes.
    Returns: (root_hash, tree_layers) where tree_layers[0] is padded leaves and tree_layers[-1] is [root].
    """
    if not leaves:
        return EMPTY_STATE_ROOT, [[EMPTY_LEAF_HASH, EMPTY_LEAF_HASH], [EMPTY_STATE_ROOT]]

    padded = _pad_leaves_to_power_of_two(leaves)
    layers = [padded]

    current_layer = padded
    while len(current_layer) > 1:
        next_layer = []
        for i in range(0, len(current_layer), 2):
            left = current_layer[i]
            right = current_layer[i + 1] if i + 1 < len(current_layer) else EMPTY_LEAF_HASH
            combined = hashlib.sha256((left + right).encode("utf-8")).hexdigest()
            next_layer.append(combined)
        layers.append(next_layer)
        current_layer = next_layer

    root = layers[-1][0] if layers[-1] else EMPTY_STATE_ROOT
    return root, layers


def _extract_workspace_stable_rules(
    workspace_id: str,
    custom_rules: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Extracts stable rules for a workspace either from database models or custom input dictionaries.
    """
    if custom_rules is not None:
        return [r for r in custom_rules if str(r.get("status", "stable")).lower() == "stable"]

    try:
        from apps.knowledge.models import KnowledgeItem
        items = KnowledgeItem.objects.filter(workspace_id=workspace_id, status="stable").order_by("id")
        rules = []
        for it in items:
            doc = it.document
            content_hash = hashlib.sha256(it.statement.encode("utf-8")).hexdigest()
            allowed_roles = getattr(doc, "allowed_roles", None) or ["member", "compliance_officer", "admin"]
            roles_str = ",".join(sorted(allowed_roles))
            roles_hash = hashlib.sha256(roles_str.encode("utf-8")).hexdigest()

            eff_from = int(doc.effective_from.timestamp()) if (doc and getattr(doc, "effective_from", None)) else 0
            eff_to = int(doc.effective_to.timestamp()) if (doc and getattr(doc, "effective_to", None)) else 253402300799

            rules.append({
                "rule_id": str(it.id),
                "code": it.code or str(it.id)[:8],
                "statement": it.statement,
                "content_hash": content_hash,
                "authority_rank": it.authority_level,
                "status": it.status,
                "effective_from_epoch": eff_from,
                "effective_to_epoch": eff_to,
                "allowed_roles": allowed_roles,
                "allowed_roles_hash": roles_hash,
                "source_path": getattr(doc, "source_path", getattr(doc, "title", "document")),
            })
        return rules
    except Exception:
        return []


def compute_workspace_state_root(
    workspace_id: str,
    custom_rules: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Computes the canonical Merkle state root commitment for a workspace's active stable rules.
    """
    rules = _extract_workspace_stable_rules(workspace_id, custom_rules)
    if not rules:
        return EMPTY_STATE_ROOT

    # Deterministic sort by rule_id
    sorted_rules = sorted(rules, key=lambda r: str(r.get("rule_id", "")))
    leaves = [
        hash_leaf_preimage(
            rule_id=str(r["rule_id"]),
            content_hash=r["content_hash"],
            authority_rank=int(r.get("authority_rank", 3)),
            status=str(r.get("status", "stable")),
            effective_from_epoch=int(r.get("effective_from_epoch", 0)),
            effective_to_epoch=int(r.get("effective_to_epoch", 253402300799)),
            allowed_roles_hash=str(r.get("allowed_roles_hash", "")),
        )
        for r in sorted_rules
    ]
    root, _ = build_merkle_tree(leaves)
    return root


def generate_merkle_inclusion_proof(
    workspace_id: str,
    rule_id: str,
    custom_rules: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Generates a deterministic Merkle inclusion proof verifying that a given rule_id
    is present within the workspace_state_root without leaking any sibling rules.
    """
    rules = _extract_workspace_stable_rules(workspace_id, custom_rules)
    sorted_rules = sorted(rules, key=lambda r: str(r.get("rule_id", "")))

    rule_match_idx = None
    target_rule = None
    leaves = []

    for idx, r in enumerate(sorted_rules):
        rid = str(r.get("rule_id", ""))
        l_hash = hash_leaf_preimage(
            rule_id=rid,
            content_hash=r["content_hash"],
            authority_rank=int(r.get("authority_rank", 3)),
            status=str(r.get("status", "stable")),
            effective_from_epoch=int(r.get("effective_from_epoch", 0)),
            effective_to_epoch=int(r.get("effective_to_epoch", 253402300799)),
            allowed_roles_hash=str(r.get("allowed_roles_hash", "")),
        )
        leaves.append(l_hash)
        if rid == str(rule_id) or str(r.get("code", "")) == str(rule_id):
            rule_match_idx = idx
            target_rule = r

    if rule_match_idx is None or target_rule is None:
        raise ValueError(f"Rule with id/code '{rule_id}' not found in stable rules for workspace {workspace_id}")

    root, layers = build_merkle_tree(leaves)

    # Compute audit path from bottom layer up
    merkle_path = []
    merkle_indices = []  # 0: sibling is on right, 1: sibling is on left
    current_idx = rule_match_idx

    for layer in layers[:-1]:
        is_right_child = (current_idx % 2 == 1)
        sibling_idx = current_idx - 1 if is_right_child else current_idx + 1

        if sibling_idx < len(layer):
            sibling_hash = layer[sibling_idx]
        else:
            sibling_hash = EMPTY_LEAF_HASH

        merkle_path.append(sibling_hash)
        merkle_indices.append(1 if is_right_child else 0)
        current_idx = current_idx // 2

    return {
        "workspace_state_root": root,
        "leaf_hash": leaves[rule_match_idx],
        "leaf_index": rule_match_idx,
        "merkle_path": merkle_path,
        "merkle_indices": merkle_indices,
        "tree_depth": len(merkle_path),
        "target_rule": target_rule,
    }


def verify_merkle_inclusion_proof(
    workspace_state_root: str,
    leaf_hash: str,
    merkle_path: List[str],
    merkle_indices: List[int],
) -> bool:
    """
    Verifies a cryptographic Merkle inclusion proof.
    """
    current = leaf_hash
    for sibling, direction in zip(merkle_path, merkle_indices):
        if direction == 0:
            # sibling on right
            combined = (current + sibling).encode("utf-8")
        else:
            # sibling on left
            combined = (sibling + current).encode("utf-8")
        current = hashlib.sha256(combined).hexdigest()

    return current.lower() == str(workspace_state_root).lower()

