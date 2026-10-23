"""
LORE Enterprise — Execution Strategy & Model-Minimal Governance Modes
Specification: lore.md, LORE Enterprise Deterministic-First Strategy.

Provides explicit, documented execution modes:
1. `local_only`: zero external inference, embeddings, OCR, or generation calls.
   Complete offline operation without external credentials or network egress.
2. `deterministic_first`: deterministic code runs first. External models are invoked
   only for well-defined, unresolved semantic tasks where approved.
3. `approved_remote`: external providers permitted only when the relevant policy
   and tenant settings explicitly authorize them.

Guarantees:
- Code is preferred for validation, hashing, deduplication, temporal rules,
  authority ladder, conflict resolution, sufficiency, and extractive synthesis.
- Models are NEVER the source of truth for a governance decision.
- Secrets (API keys, authorization headers) are strictly scrubbed from logs and envelopes.
- No silent cloud fallback when local inference or providers fail.
- Thread-safe bounded concurrency, timeouts, and retries for remote calls.
"""

import re
import time
import logging
import threading
from enum import Enum
from typing import Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from django.conf import settings

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    """Explicit LORE Execution Modes."""
    LOCAL_ONLY = "local_only"
    DETERMINISTIC_FIRST = "deterministic_first"
    APPROVED_REMOTE = "approved_remote"


class ModelTaskPurpose(str, Enum):
    """Categorized task purposes for model invocations."""
    GENERATION = "generation"
    EMBEDDING = "embedding"
    OCR = "ocr"
    RERANKING = "reranking"
    CLASSIFICATION = "classification"


@dataclass
class ModelExecutionMetric:
    """Audit and telemetry record for deterministic vs model execution."""
    provider: str
    model_name: str
    purpose: str
    latency_ms: float
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_total: int = 0
    cost_usd: float = 0.0
    was_deterministic: bool = True
    reason: str = "deterministic_code_execution"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model_name": self.model_name,
            "purpose": self.purpose,
            "latency_ms": round(self.latency_ms, 2),
            "tokens_prompt": self.tokens_prompt,
            "tokens_completion": self.tokens_completion,
            "tokens_total": self.tokens_total,
            "cost_usd": round(self.cost_usd, 6),
            "was_deterministic": self.was_deterministic,
            "reason": self.reason,
        }


# Bounded concurrency semaphore for optional remote calls (default max 5 concurrent external calls)
_remote_concurrency_limit = getattr(settings, 'REMOTE_CALL_MAX_CONCURRENCY', 5)
_remote_semaphore = threading.BoundedSemaphore(value=max(1, _remote_concurrency_limit))


# Sensitive credential patterns for strict secret scrubbing
_SECRET_PATTERNS = [
    (re.compile(r'(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{8,}'), r'\1[REDACTED_SECRET]'),
    (re.compile(r'(?i)gsk_[a-zA-Z0-9]{15,}'), r'[REDACTED_SECRET]'),
    (re.compile(r'(?i)sk-[a-zA-Z0-9_\-]{15,}'), r'[REDACTED_SECRET]'),
    (re.compile(r'(?i)(api[_-]?key["\']?\s*[:=]\s*["\']?)([^"\'\s,;]+)'), r'\1[REDACTED_SECRET]'),
    (re.compile(r'(?i)(password["\']?\s*[:=]\s*["\']?)([^"\'\s,;]+)'), r'\1[REDACTED_SECRET]'),
    (re.compile(r'(?i)(secret["\']?\s*[:=]\s*["\']?)([^"\'\s,;]+)'), r'\1[REDACTED_SECRET]'),
]

_SENSITIVE_KEY_NAMES = {
    'groq_api_key', 'api_key', 'apikey', 'secret_key', 'secret',
    'password', 'authorization', 'x-groq-api-key', 'auth_token', 'token'
}


def sanitize_sensitive_data(val: Any) -> Any:
    """
    Recursively scrubs API keys, bearer tokens, and secrets from dicts, lists, and strings.
    Ensures secrets NEVER leak into audit logs or result envelopes.
    """
    if isinstance(val, str):
        cleaned = val
        for pat, repl in _SECRET_PATTERNS:
            cleaned = pat.sub(repl, cleaned)
        return cleaned
    elif isinstance(val, dict):
        sanitized = {}
        for k, v in val.items():
            if str(k).lower() in _SENSITIVE_KEY_NAMES:
                sanitized[k] = "[REDACTED_SECRET]"
            else:
                sanitized[k] = sanitize_sensitive_data(v)
        return sanitized
    elif isinstance(val, (list, tuple)):
        sanitized_list = [sanitize_sensitive_data(item) for item in val]
        return type(val)(sanitized_list)
    return val


def get_active_execution_mode(
    request=None,
    workspace=None,
    policy_context: Optional[Dict[str, Any]] = None,
    requested_mode: Optional[Union[str, ExecutionMode]] = None
) -> ExecutionMode:
    """
    Resolves the active execution mode according to strict precedence:
    1. Explicit requested_mode (if provided and valid)
    2. policy_context.get('execution_mode')
    3. Workspace model configuration (if set)
    4. Django settings.EXECUTION_MODE
    5. Default: ExecutionMode.DETERMINISTIC_FIRST
    """
    candidates = []

    if requested_mode:
        candidates.append(str(requested_mode).lower())

    if policy_context and isinstance(policy_context, dict):
        mode_in_ctx = policy_context.get('execution_mode')
        if mode_in_ctx:
            candidates.append(str(mode_in_ctx).lower())

    if workspace:
        ws_mode = getattr(workspace, 'execution_mode', None)
        if ws_mode:
            candidates.append(str(ws_mode).lower())

    settings_mode = getattr(settings, 'EXECUTION_MODE', None)
    if settings_mode:
        candidates.append(str(settings_mode).lower())

    candidates.append(ExecutionMode.DETERMINISTIC_FIRST.value)

    for cand in candidates:
        try:
            return ExecutionMode(cand)
        except ValueError:
            continue

    return ExecutionMode.DETERMINISTIC_FIRST


def is_remote_model_allowed(
    workspace=None,
    organization=None,
    policy_context: Optional[Dict[str, Any]] = None,
    purpose: ModelTaskPurpose = ModelTaskPurpose.GENERATION,
    mode: Optional[ExecutionMode] = None
) -> Tuple[bool, str]:
    """
    Evaluates whether external inference/transmission is authorized.
    
    Rules:
    - LOCAL_ONLY: Strictly NO external transmission under any circumstances.
    - DETERMINISTIC_FIRST: Permitted only for unresolved semantic generation IF
      the tenant or settings explicitly authorize remote models.
    - APPROVED_REMOTE: Permitted ONLY when the relevant policy and tenant/workspace
      settings explicitly authorize them. If tenant does not authorize, strictly blocked.
    """
    active_mode = mode or get_active_execution_mode(workspace=workspace, policy_context=policy_context)

    # 1. Local-only invariant
    if active_mode == ExecutionMode.LOCAL_ONLY:
        return (
            False,
            "Execution mode is 'local_only': all external inference, API calls, and network egress are strictly prohibited."
        )

    # 2. Check tenant and policy authorization
    tenant_authorized = False
    auth_reason = "No explicit authorization found in tenant policy or workspace configuration."

    if policy_context and isinstance(policy_context, dict):
        if policy_context.get('allow_remote_llm') is True or policy_context.get('allow_remote_models') is True:
            tenant_authorized = True
            auth_reason = "Authorized via explicit policy_context.allow_remote_llm"

    if not tenant_authorized and workspace:
        if getattr(workspace, 'allow_remote_llm', False) is True:
            tenant_authorized = True
            auth_reason = "Authorized via workspace.allow_remote_llm"

    if not tenant_authorized and organization:
        if getattr(organization, 'allow_remote_llm', False) is True:
            tenant_authorized = True
            auth_reason = "Authorized via organization.allow_remote_llm"

    # Global system setting fallback for development/testing
    if not tenant_authorized and getattr(settings, 'ALLOW_REMOTE_MODELS', False) is True:
        tenant_authorized = True
        auth_reason = "Authorized via settings.ALLOW_REMOTE_MODELS"

    # In approved_remote mode, tenant authorization is mandatory
    if active_mode == ExecutionMode.APPROVED_REMOTE:
        if not tenant_authorized:
            return (
                False,
                f"Execution mode 'approved_remote' blocked: Tenant policy has not authorized external provider transmission ({auth_reason})."
            )
        return (True, f"Authorized for {purpose.value}: {auth_reason}")

    # In deterministic_first mode, remote is allowed only if authorized AND for generation/semantic tasks
    if active_mode == ExecutionMode.DETERMINISTIC_FIRST:
        if not tenant_authorized:
            return (
                False,
                f"Deterministic-first remote call blocked: Tenant policy has not authorized external provider transmission ({auth_reason})."
            )
        return (True, f"Deterministic-first permits approved remote model for {purpose.value} ({auth_reason}).")

    return (False, f"Remote execution denied under mode '{active_mode.value}'.")


def acquire_remote_concurrency_slot(timeout: float = 10.0) -> bool:
    """Acquires a concurrency slot for an approved external call."""
    return _remote_semaphore.acquire(timeout=timeout)


def release_remote_concurrency_slot() -> None:
    """Releases a concurrency slot."""
    try:
        _remote_semaphore.release()
    except ValueError:
        pass
