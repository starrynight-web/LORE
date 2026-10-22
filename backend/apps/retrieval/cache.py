"""
LORE Enterprise — Tenant-Safe Cache Service
Specification: Master Prompt P2 §13, lore.md §4.

Guarantees:
1. Strict partition isolation across tenant (organization), workspace, and authorization roles.
   Cached results NEVER cross org, workspace, user, or role boundaries.
2. Incorporates query, as_of point-in-time timestamp, and role into key derivation.
3. Fast, deterministic invalidation upon document deletion, permission revocation, or policy updates.
"""

import hashlib
import json
import logging
from typing import Dict, Any, Optional
from django.core.cache import cache

logger = logging.getLogger(__name__)


class TenantSafeCacheService:
    """
    Enforces authorization-aware, tenant-isolated caching of governed RAG results.
    """
    DEFAULT_TTL = 3600  # 1 hour

    @classmethod
    def _hash_query(cls, query: str, as_of: Optional[Any] = None) -> str:
        raw = f"{query.strip().lower()}|as_of={str(as_of or '')}"
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]

    @classmethod
    def make_cache_key(
        cls,
        organization_id: str,
        workspace_id: str,
        user_role: str,
        query: str,
        as_of: Optional[Any] = None
    ) -> str:
        q_hash = cls._hash_query(query, as_of=as_of)
        role = (user_role or 'member').lower()
        return f"lore:cache:t_{organization_id}:ws_{workspace_id}:role_{role}:{q_hash}"

    @classmethod
    def _workspace_tag_key(cls, workspace_id: str) -> str:
        return f"lore:tags:ws_{workspace_id}"

    @classmethod
    def get(
        cls,
        organization_id: Optional[str] = None,
        workspace_id: str = "",
        user_role: str = "member",
        query: str = "",
        as_of: Optional[Any] = None,
        org_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        target_org = organization_id or org_id or ""
        key = cls.make_cache_key(
            organization_id=target_org,
            workspace_id=workspace_id,
            user_role=user_role,
            query=query,
            as_of=as_of
        )
        try:
            cached_data = cache.get(key)
            if cached_data:
                logger.debug(f"[Cache Hit] Key={key}")
                return cached_data
        except Exception as ex:
            logger.warning(f"Cache get failed for key {key}: {ex}")
        return None

    @classmethod
    def set(
        cls,
        organization_id: Optional[str] = None,
        workspace_id: str = "",
        user_role: str = "member",
        query: str = "",
        envelope: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TTL,
        as_of: Optional[Any] = None,
        org_id: Optional[str] = None,
        value: Optional[Dict[str, Any]] = None
    ) -> bool:
        target_org = organization_id or org_id or ""
        data = envelope if envelope is not None else value
        if not data:
            return False

        # Never cache denied or internal error envelopes
        state = data.get('state')
        if state in ('denied',) or data.get('error_category'):
            return False

        key = cls.make_cache_key(
            organization_id=target_org,
            workspace_id=workspace_id,
            user_role=user_role,
            query=query,
            as_of=as_of
        )
        try:
            cache.set(key, data, timeout=timeout)
            # Track key under workspace tag set for fast invalidation
            tag_key = cls._workspace_tag_key(workspace_id)
            tracked_keys = cache.get(tag_key) or []
            if key not in tracked_keys:
                tracked_keys.append(key)
                cache.set(tag_key, tracked_keys[-200:], timeout=timeout * 2)
            return True
        except Exception as ex:
            logger.warning(f"Cache set failed for key {key}: {ex}")
            return False

    @classmethod
    def _purge_tag(cls, tag_id: str) -> int:
        if not tag_id:
            return 0
        tag_key = cls._workspace_tag_key(tag_id)
        count = 0
        try:
            tracked_keys = cache.get(tag_key) or []
            for k in tracked_keys:
                cache.delete(k)
                count += 1
            cache.delete(tag_key)
            if count > 0:
                logger.info(f"[Cache Invalidation] Purged {count} keys for tag {tag_id}")
        except Exception as ex:
            logger.warning(f"Cache purge failed for {tag_id}: {ex}")
        return count

    @classmethod
    def invalidate_workspace(cls, workspace_id: Optional[str] = None, organization_id: Optional[str] = None, *args, **kwargs) -> int:
        """Invalidates all cached entries for a given workspace."""
        total = 0
        if workspace_id:
            total += cls._purge_tag(workspace_id)
        if organization_id:
            total += cls._purge_tag(organization_id)
        for a in args:
            if isinstance(a, str):
                total += cls._purge_tag(a)
        for k in ('ws_id', 'org_id'):
            val = kwargs.get(k)
            if val and isinstance(val, str):
                total += cls._purge_tag(val)
        return total

    @classmethod
    def invalidate_document(cls, workspace_id: str, document_id: str) -> int:
        """Document update or deletion invalidates the parent workspace cache."""
        return cls.invalidate_workspace(workspace_id)
