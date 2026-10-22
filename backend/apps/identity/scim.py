import logging
from typing import Dict, Any, List, Optional
from django.contrib.auth.models import User
from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership

logger = logging.getLogger(__name__)

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"

class SCIMService:
    """
    SCIM 2.0 (System for Cross-domain Identity Management) Service.
    Enables Okta, Azure AD (Entra ID), Google Workspace, and PingIdentity
    automated enterprise directory provisioning, group syncing, and deprovisioning.
    Specification: Master Prompt P4 §22 (Enterprise Identity & SCIM Provisioning).
    """

    @classmethod
    def serialize_user(cls, user: User) -> Dict[str, Any]:
        return {
            "schemas": [SCIM_USER_SCHEMA],
            "id": str(user.id),
            "userName": user.username,
            "name": {
                "givenName": user.first_name or "",
                "familyName": user.last_name or "",
                "formatted": f"{user.first_name} {user.last_name}".strip() or user.username
            },
            "emails": [
                {
                    "value": user.email,
                    "primary": True
                }
            ] if user.email else [],
            "active": user.is_active,
            "meta": {
                "resourceType": "User",
                "created": user.date_joined.isoformat() if hasattr(user, 'date_joined') and user.date_joined else ""
            }
        }

    @classmethod
    def list_users(cls, org_id: Optional[str] = None) -> Dict[str, Any]:
        qs = User.objects.all()
        if org_id:
            qs = qs.filter(organization_memberships__organization_id=org_id)

        users = [cls.serialize_user(u) for u in qs.order_by('id')[:100]]
        return {
            "schemas": [SCIM_LIST_SCHEMA],
            "totalResults": len(users),
            "itemsPerPage": len(users),
            "startIndex": 1,
            "Resources": users
        }

    @classmethod
    def create_user(cls, data: Dict[str, Any], org_id: Optional[str] = None) -> Dict[str, Any]:
        user_name = data.get("userName")
        if not user_name:
            raise ValueError("SCIM payload missing required 'userName' attribute.")

        emails = data.get("emails", [])
        email = emails[0].get("value") if emails and isinstance(emails, list) else ""
        name_obj = data.get("name", {})
        first_name = name_obj.get("givenName", "")
        last_name = name_obj.get("familyName", "")
        active = data.get("active", True)

        user, created = User.objects.get_or_create(
            username=user_name,
            defaults={
                'email': email,
                'first_name': first_name,
                'last_name': last_name,
                'is_active': active
            }
        )

        if not created:
            user.email = email or user.email
            user.first_name = first_name or user.first_name
            user.last_name = last_name or user.last_name
            user.is_active = active
            user.save()

        # Associate with default or target organization
        org = None
        if org_id:
            org = Organization.objects.filter(id=org_id).first()
        if not org:
            org = Organization.objects.first()

        if org:
            OrganizationMembership.objects.get_or_create(
                organization=org,
                user=user,
                defaults={'role': 'member'}
            )

        return cls.serialize_user(user)

    @classmethod
    def update_user(cls, user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        user = User.objects.get(id=user_id)
        if "active" in data:
            user.is_active = bool(data["active"])
        if "userName" in data:
            user.username = data["userName"]
        if "emails" in data and isinstance(data["emails"], list) and data["emails"]:
            user.email = data["emails"][0].get("value", user.email)
        if "name" in data and isinstance(data["name"], dict):
            user.first_name = data["name"].get("givenName", user.first_name)
            user.last_name = data["name"].get("familyName", user.last_name)
        user.save()
        return cls.serialize_user(user)

    @classmethod
    def deactivate_user(cls, user_id: int) -> bool:
        user = User.objects.get(id=user_id)
        user.is_active = False
        user.save(update_fields=['is_active'])
        return True

    @classmethod
    def list_groups(cls, org_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Exposes Workspace and Role groupings as SCIM Groups for IdP directory sync.
        """
        qs = Workspace.objects.all()
        if org_id:
            qs = qs.filter(organization_id=org_id)

        groups = []
        for ws in qs:
            memberships = WorkspaceMembership.objects.filter(workspace=ws).select_related('user')
            members = [
                {"value": str(m.user_id), "display": m.user.username}
                for m in memberships
            ]
            groups.append({
                "schemas": [SCIM_GROUP_SCHEMA],
                "id": str(ws.id),
                "displayName": f"{ws.organization.name} - {ws.name}",
                "members": members
            })

        return {
            "schemas": [SCIM_LIST_SCHEMA],
            "totalResults": len(groups),
            "itemsPerPage": len(groups),
            "startIndex": 1,
            "Resources": groups
        }

    @classmethod
    def sync_group_members(cls, workspace_id: str, member_user_ids: List[int], role: str = 'contributor') -> Dict[str, Any]:
        """
        Syncs directory group membership to LORE workspace memberships.
        """
        ws = Workspace.objects.get(id=workspace_id)
        # Add members
        for uid in member_user_ids:
            try:
                user = User.objects.get(id=uid)
                WorkspaceMembership.objects.update_or_create(
                    workspace=ws,
                    user=user,
                    defaults={'role': role}
                )
            except User.DoesNotExist:
                logger.warning(f"SCIM Group sync: User {uid} does not exist.")

        memberships = WorkspaceMembership.objects.filter(workspace=ws).select_related('user')
        return {
            "schemas": [SCIM_GROUP_SCHEMA],
            "id": str(ws.id),
            "displayName": f"{ws.organization.name} - {ws.name}",
            "members": [
                {"value": str(m.user_id), "display": m.user.username}
                for m in memberships
            ]
        }
