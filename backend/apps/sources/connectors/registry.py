"""
LORE Enterprise - Event-Driven Connector Bus & Registry (docs/enterprise/fix/knowledge.md §4)
Registers and instantiates enterprise connectors:
- Confluence, SharePoint, Jira, GitHub, Slack, Web Scraper, Gmail, Local Folder
- Handles webhook ingestion triggers and streaming batch dispatch
"""

import logging
from typing import Dict, Type, Any, Optional
from .base import BaseConnector
from .confluence import ConfluenceConnector
from .sharepoint import SharePointConnector
from .jira import JiraConnector
from .github import GitHubConnector
from .web_scraper import WebScraperConnector
from .gmail import GmailConnector
from .local_folder import LocalFolderConnector

logger = logging.getLogger(__name__)


class EnterpriseConnectorRegistry:
    """
    Central registry for instantiating and dispatching enterprise connectors.
    """

    _REGISTRY: Dict[str, Type[BaseConnector]] = {
        "confluence": ConfluenceConnector,
        "sharepoint": SharePointConnector,
        "jira": JiraConnector,
        "github": GitHubConnector,
        "web_scraper": WebScraperConnector,
        "gmail": GmailConnector,
        "local_folder": LocalFolderConnector,
    }

    @classmethod
    def register(cls, connector_type: str, connector_cls: Type[BaseConnector]):
        cls._REGISTRY[connector_type.lower()] = connector_cls

    @classmethod
    def get_connector(
        cls,
        connector_type: str,
        organization_id: str,
        workspace_id: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> BaseConnector:
        c_type = connector_type.lower()
        if c_type not in cls._REGISTRY:
            raise ValueError(f"Unknown enterprise connector type: '{connector_type}'. Available: {list(cls._REGISTRY.keys())}")

        cls_obj = cls._REGISTRY[c_type]
        return cls_obj(organization_id=organization_id, workspace_id=workspace_id, config=config)

    @classmethod
    def list_available_connectors(cls) -> Dict[str, str]:
        return {
            "confluence": "Atlassian Confluence Cloud & Server",
            "sharepoint": "Microsoft SharePoint & OneDrive 365",
            "jira": "Atlassian Jira Issue Tracking & Service Management",
            "github": "GitHub / GitLab Repository Markdown & ADRs",
            "web_scraper": "Enterprise Intranet & Portal Scraper",
            "gmail": "Google Workspace Gmail & Drive Sync",
            "local_folder": "Local & Mounted Network File Share",
        }

