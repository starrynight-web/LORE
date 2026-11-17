"""
LORE Enterprise - Celery Periodic Tasks for Sources & Governance (prompt §1.4)
Handles:
1. L0 Graph Health & Drift Monitoring
2. Incremental Enterprise Connector Polling (Confluence, SharePoint, Jira, GitHub, Scraper)
3. Live Evidence Verification (Vanta, ServiceNow, Jira)
"""

import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="sources.l0_graph_drift_check")
def periodic_l0_graph_drift_check(workspace_id=None):
    """Periodic Celery Beat task monitoring graph health, orphaned rules, and expired exceptions."""
    try:
        from apps.governance.telemetry import L0GraphHealthMonitor
        result = L0GraphHealthMonitor.run_drift_check(workspace_id=workspace_id)
        logger.info(f"L0 Graph Health Check completed: {result.get('status')} (score={result.get('anomaly_score')})")
        return result
    except Exception as e:
        logger.error(f"L0 Graph Health Check error: {e}")
        return {"status": "ERROR", "error": str(e)}


@shared_task(name="sources.connector_incremental_sync")
def periodic_connector_sync(workspace_id=None):
    """Periodic Celery Beat task syncing configured enterprise connectors."""
    try:
        from apps.sources.connectors.registry import EnterpriseConnectorRegistry
        results = EnterpriseConnectorRegistry.sync_all_active_connectors(workspace_id=workspace_id)
        logger.info(f"Enterprise Connector sync completed: {len(results)} connectors synced")
        return results
    except Exception as e:
        logger.error(f"Enterprise Connector sync error: {e}")
        return {"status": "ERROR", "error": str(e)}


@shared_task(name="sources.live_evidence_refresh")
def periodic_live_evidence_refresh(workspace_id=None):
    """Periodic Celery Beat task refreshing live evidence connectors (Vanta, ServiceNow, Jira)."""
    try:
        from apps.governance.live_evidence import LiveEvidenceRegistry
        results = LiveEvidenceRegistry.refresh_all(workspace_id=workspace_id)
        logger.info(f"Live Evidence refresh completed: {results}")
        return results
    except Exception as e:
        logger.error(f"Live Evidence refresh error: {e}")
        return {"status": "ERROR", "error": str(e)}

