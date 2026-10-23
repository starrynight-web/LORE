"""
LORE Enterprise — System Configuration Checks & Startup Validation
Enforces Requirement 8 (configuration validation & clear startup errors)
and Requirement 10 (security boundaries & production deployment safety).
"""

import os
from django.core.checks import register, Error, Warning, Tags
from django.conf import settings


@register(Tags.security)
def check_production_security_settings(app_configs, **kwargs):
    """Validates that unsafe development shortcuts and defaults cannot run in production."""
    errors = []
    is_debug = getattr(settings, 'DEBUG', True)

    if not is_debug:
        # 1. Insecure default secret key check
        secret_key = getattr(settings, 'SECRET_KEY', '')
        if secret_key in ('lore-enterprise-dev-secret-key-insecure-only-for-dev', '', None):
            errors.append(
                Error(
                    "Insecure default SECRET_KEY detected in production (DEBUG=False).",
                    hint="Set a unique, cryptographically secure SECRET_KEY environment variable.",
                    id="lore.security.E001"
                )
            )

        # 2. Guest Mode Authentication Shortcut Check
        guest_mode = getattr(settings, 'GUEST_MODE_ENABLED', False)
        if guest_mode:
            errors.append(
                Error(
                    "GUEST_MODE_ENABLED is True in production (DEBUG=False). "
                    "This allows unauthenticated visitors to be escalated to demo admin.",
                    hint="Set GUEST_MODE_ENABLED=False in production environment variables.",
                    id="lore.security.E002"
                )
            )

        # 3. Permissive ALLOWED_HOSTS Check
        allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', [])
        if '*' in allowed_hosts or not allowed_hosts:
            errors.append(
                Error(
                    "ALLOWED_HOSTS is set to '*' or is empty in production (DEBUG=False).",
                    hint="Specify exact domain names or IP addresses in ALLOWED_HOSTS (e.g. 'lore.internal.company.com').",
                    id="lore.security.E003"
                )
            )

        # 4. Permissive CORS Check
        cors_allow_all = getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False)
        if cors_allow_all:
            errors.append(
                Error(
                    "CORS_ALLOW_ALL_ORIGINS is True in production (DEBUG=False).",
                    hint="Set CORS_ALLOW_ALL_ORIGINS=False and specify CORS_ALLOWED_ORIGINS.",
                    id="lore.security.E004"
                )
            )

        # 5. Secure Cookies Warning
        if not getattr(settings, 'CSRF_COOKIE_SECURE', False):
            errors.append(
                Warning(
                    "CSRF_COOKIE_SECURE is False in production.",
                    hint="Set CSRF_COOKIE_SECURE=True to ensure CSRF cookies are transmitted only over HTTPS.",
                    id="lore.security.W005"
                )
            )
        if not getattr(settings, 'SESSION_COOKIE_SECURE', False):
            errors.append(
                Warning(
                    "SESSION_COOKIE_SECURE is False in production.",
                    hint="Set SESSION_COOKIE_SECURE=True to ensure session cookies are transmitted only over HTTPS.",
                    id="lore.security.W006"
                )
            )

    return errors


@register("lore_configuration")
def check_execution_and_embedding_configuration(app_configs, **kwargs):
    """Validates execution modes, embedding provider compatibility, and vector dimensions."""
    errors = []

    # 1. Execution Mode Check
    mode = getattr(settings, 'EXECUTION_MODE', 'deterministic_first').lower()
    valid_modes = ('local_only', 'deterministic_first', 'approved_remote')
    if mode not in valid_modes:
        errors.append(
            Error(
                f"Unsupported EXECUTION_MODE '{mode}'. Supported modes: {list(valid_modes)}.",
                hint="Set EXECUTION_MODE to 'local_only', 'deterministic_first', or 'approved_remote'.",
                id="lore.config.E010"
            )
        )

    # 2. Local-only with remote models contradiction check
    allow_remote = getattr(settings, 'ALLOW_REMOTE_MODELS', False)
    if mode == 'local_only' and allow_remote:
        errors.append(
            Warning(
                "EXECUTION_MODE is 'local_only', but ALLOW_REMOTE_MODELS is True. "
                "Local-only policy strictly overrides and suppresses all remote inference.",
                hint="Set ALLOW_REMOTE_MODELS=False when running in airgapped local-only mode.",
                id="lore.config.W011"
            )
        )

    # 3. Embedding Provider Check
    provider = getattr(settings, 'EMBEDDING_PROVIDER', 'sentence-transformers').lower()
    valid_providers = ('sentence-transformers', 'local_transformer', 'hash_projection', 'ngram_hash')
    if provider not in valid_providers:
        errors.append(
            Error(
                f"Unsupported EMBEDDING_PROVIDER '{provider}'. Supported providers: {list(valid_providers)}.",
                hint="Configure EMBEDDING_PROVIDER to 'sentence-transformers' for local neural retrieval.",
                id="lore.config.E012"
            )
        )

    # 4. Neural Model Availability Check
    if provider in ('sentence-transformers', 'local_transformer'):
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            allow_fallback = getattr(settings, 'ALLOW_HASH_PROJECTION_FALLBACK', False)
            if not allow_fallback:
                errors.append(
                    Error(
                        "SentenceTransformers is configured but cannot be imported, and ALLOW_HASH_PROJECTION_FALLBACK=False.",
                        hint="Install sentence-transformers/torch, or enable ALLOW_HASH_PROJECTION_FALLBACK=True only for offline tests.",
                        id="lore.config.E013"
                    )
                )

    # 5. Dimension Consistency Check between Embedder and Vector Store
    try:
        from apps.retrieval.embeddings import get_embedding_adapter
        from apps.retrieval.vector_store import QdrantVectorStore

        embedder = get_embedding_adapter()
        vstore = QdrantVectorStore()

        if embedder.dimension != vstore.vector_dim:
            errors.append(
                Error(
                    f"Incompatible embedding dimensions: Embedding adapter produces {embedder.dimension}-dim vectors, "
                    f"but Qdrant vector store is configured for {vstore.vector_dim}-dim vectors.",
                    hint="Ensure EMBEDDING_MODEL_NAME dimension matches Qdrant collection vector_dim (default 384 for all-MiniLM-L6-v2).",
                    id="lore.vector.E020"
                )
            )
    except Exception as ex:
        # Don't fail check if DB or Qdrant initialization is deferred during build
        pass

    return errors
