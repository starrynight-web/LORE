import sys
import threading
import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class LoreEnterpriseConfig(AppConfig):
    name = 'lore_enterprise'
    verbose_name = 'LORE Enterprise Core'

    def ready(self):
        # Register system checks
        from . import checks  # noqa: F401

        # Skip warming during management commands that shouldn't load models
        skip_commands = {'makemigrations', 'migrate', 'collectstatic', 'showmigrations', 'sqlmigrate', 'dumpdata', 'loaddata'}
        if any(cmd in sys.argv for cmd in skip_commands):
            return

        def _prewarm_subsystems():
            try:
                from apps.knowledge.graph_adapters import get_graph_adapter
                get_graph_adapter("kuzu")
                logger.info("[PreWarm] KùzuDB connection pool pre-warmed successfully.")
            except Exception as e:
                logger.debug(f"[PreWarm] KùzuDB pre-warm skipped/handled: {e}")

            try:
                from apps.retrieval.embeddings import get_embedding_adapter
                adapter = get_embedding_adapter()
                if hasattr(adapter, 'embed_text'):
                    adapter.embed_text("LORE warm-up query")
                logger.info("[PreWarm] Local embedding model pre-warmed successfully.")
            except Exception as e:
                logger.debug(f"[PreWarm] Embedding pre-warm skipped/handled: {e}")

            try:
                from apps.retrieval.reranking.neural import NeuralCrossEncoderReranker
                reranker = NeuralCrossEncoderReranker()
                reranker._ensure_loaded()
                logger.info("[PreWarm] Neural cross-encoder reranker pre-warmed successfully.")
            except Exception as e:
                logger.debug(f"[PreWarm] Neural reranker pre-warm skipped/handled: {e}")

        warm_thread = threading.Thread(target=_prewarm_subsystems, daemon=True, name="lore_prewarm_thread")
        warm_thread.start()
