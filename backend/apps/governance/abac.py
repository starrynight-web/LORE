"""
LORE Enterprise - SCIM 2.0 / OIDC Role Sync & L7 Pre-Retrieval ABAC (docs/enterprise/fix/knowledge.md §1 & §3)
Enforces:
1. SCIM / OIDC group mapping from enterprise IdPs (Okta, Entra ID, Keycloak) directly into LORE roles.
2. Pre-retrieval database filtering (WHERE allowed_roles && user_roles) guaranteeing zero context leakage.
"""

import logging
from typing import List, Dict, Any, Optional, Set
from django.db.models import Q
from apps.governance.models import SourcePermission, AccessLevel

logger = logging.getLogger(__name__)


# Enterprise IdP group-to-role taxonomy mapping
DEFAULT_SCIM_ROLE_MAPPING: Dict[str, str] = {
    # Identity Provider Group substring / exact -> LORE Canonical Role
    "admin": "workspace_admin",
    "owner": "owner",
    "security": "security_officer",
    "sec-ops": "security_officer",
    "secops": "security_officer",
    "sec": "security_officer",
    "compliance": "compliance_auditor",
    "legal": "compliance_auditor",
    "audit": "compliance_auditor",
    "eng": "developer",
    "engineering": "developer",
    "developer": "developer",
    "devops": "developer",
    "product": "member",
    "finance": "member",
    "hr": "member",
    "sales": "member",
    "contractor": "guest",
    "intern": "guest",
}


class SCIMRoleSynchronizer:
    """
    Synchronizes SCIM 2.0 and OIDC IdP group claims with LORE user roles and permissions.
    """

    @classmethod
    def map_idp_groups_to_roles(
        cls,
        idp_groups: List[str],
        custom_mapping: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        mapping = custom_mapping or DEFAULT_SCIM_ROLE_MAPPING
        assigned_roles: Set[str] = {"member"}  # Base baseline role

        for group in idp_groups:
            group_clean = group.lower().strip()
            matched = False
            for pattern, target_role in mapping.items():
                if pattern in group_clean:
                    assigned_roles.add(target_role)
                    matched = True
            if not matched and group_clean:
                assigned_roles.add(f"group:{group_clean}")

        return sorted(list(assigned_roles))

    @classmethod
    def sync_user_roles(
        cls,
        user,
        idp_groups: List[str],
        idp_claims: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        roles = cls.map_idp_groups_to_roles(idp_groups)
        if user and hasattr(user, "profile"):
            user.profile.roles = roles
            user.profile.save(update_fields=["roles"])
        elif user and hasattr(user, "is_superuser") and user.is_superuser:
            if "owner" not in roles:
                roles.append("owner")
            if "workspace_admin" not in roles:
                roles.append("workspace_admin")
        return roles

    @classmethod
    def apply_document_scim_policy(
        cls,
        document,
        allowed_roles: List[str],
        access_level: str = AccessLevel.INTERNAL,
        allowed_users: Optional[List[str]] = None,
        redaction_required: bool = False,
    ) -> SourcePermission:
        perm, _ = SourcePermission.objects.update_or_create(
            document=document,
            defaults={
                "access_level": access_level,
                "allowed_roles": allowed_roles,
                "allowed_users": allowed_users or [],
                "redaction_required": redaction_required,
            },
        )
        return perm


def build_authorized_document_filter(
    user=None,
    user_role: str = "member",
    workspace_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> Q:
    """
    Constructs a database Q-object filter enforcing L7 ABAC permissions at the query layer.
    Ensures that only documents the user is strictly authorized to view enter retrieval candidates.
    """
    base_q = Q()
    if workspace_id:
        base_q &= Q(workspace_id=workspace_id)
    if organization_id:
        base_q &= Q(organization_id=organization_id)

    # Superusers / Owners have comprehensive tenant-level access
    if user and getattr(user, "is_superuser", False) or user_role in ("owner", "workspace_admin"):
        return base_q

    # Standard users:
    # 1. Documents without permissions or public: accessible
    # 2. Internal documents: accessible to authenticated tenant members
    # 3. Restricted/Confidential documents: must match user role or username
    user_name = getattr(user, "username", "") if user else ""
    user_id_str = str(getattr(user, "id", "")) if user else ""

    perm_public = Q(permissions__isnull=True) | Q(permissions__access_level=AccessLevel.PUBLIC)

    perm_internal = Q(permissions__access_level=AccessLevel.INTERNAL)

    from django.db import connection

    if connection.vendor == 'postgresql':
        perm_restricted_role = (
            Q(permissions__access_level__in=[AccessLevel.RESTRICTED, AccessLevel.CONFIDENTIAL])
            & Q(permissions__allowed_roles__contains=[user_role])
        )
    else:
        perm_restricted_role = (
            Q(permissions__access_level__in=[AccessLevel.RESTRICTED, AccessLevel.CONFIDENTIAL])
            & Q(permissions__allowed_roles__icontains=user_role)
        )

    perm_restricted_user = Q()
    if user_name:
        if connection.vendor == 'postgresql':
            perm_restricted_user |= (
                Q(permissions__access_level__in=[AccessLevel.RESTRICTED, AccessLevel.CONFIDENTIAL])
                & Q(permissions__allowed_users__contains=[user_name])
            )
        else:
            perm_restricted_user |= (
                Q(permissions__access_level__in=[AccessLevel.RESTRICTED, AccessLevel.CONFIDENTIAL])
                & Q(permissions__allowed_users__icontains=user_name)
            )
    if user_id_str:
        if connection.vendor == 'postgresql':
            perm_restricted_user |= (
                Q(permissions__access_level__in=[AccessLevel.RESTRICTED, AccessLevel.CONFIDENTIAL])
                & Q(permissions__allowed_users__contains=[user_id_str])
            )
        else:
            perm_restricted_user |= (
                Q(permissions__access_level__in=[AccessLevel.RESTRICTED, AccessLevel.CONFIDENTIAL])
                & Q(permissions__allowed_users__icontains=user_id_str)
            )

    return base_q & (perm_public | perm_internal | perm_restricted_role | perm_restricted_user)
