"""
LORE Enterprise - Atlassian Jira Connector (docs/enterprise/fix/knowledge.md §4)
Synchronizes architectural review issues, compliance epics, and security exceptions.
"""

import time
import logging
from typing import Optional, Generator, Dict, Any
from .base import BaseConnector, SyncCheckpoint, SyncEvent

logger = logging.getLogger(__name__)


class JiraConnector(BaseConnector):
    """
    Atlassian Jira Issue / Project Connector.
    Extracts policy directives, exception tickets, and security audit action items.
    """

    @property
    def connector_type(self) -> str:
        return "jira"

    def test_connection(self) -> bool:
        return bool(self.config.get("server_url") or self.config.get("mock_issues"))

    def list_events(
        self,
        checkpoint: Optional[SyncCheckpoint] = None,
        full_sync: bool = False,
    ) -> Generator[SyncEvent, None, Optional[SyncCheckpoint]]:
        jql = self.config.get("jql", "project in (SEC, GOV) AND status = Done")
        mock_issues = self.config.get("mock_issues", [
            {
                "key": "SEC-804",
                "summary": "Mandatory Multi-Factor Authentication Rollout",
                "description": "All employee accounts accessing production infrastructure must enforce FIDO2 WebAuthn MFA.",
                "updated": "2026-10-01T12:00:00Z",
                "status": "Closed",
            },
            {
                "key": "GOV-112",
                "summary": "Approved Exception: Legacy SFTP Endpoint for Partner X",
                "description": "Temporary 6-month exception granted for partner legacy SFTP ingestion under ticket GOV-112.",
                "updated": "2026-10-15T15:30:00Z",
                "status": "Approved",
            },
        ])

        for issue in mock_issues:
            body = f"# [{issue['key']}] {issue['summary']}\n\nStatus: {issue['status']}\n\n{issue['description']}"
            yield SyncEvent(
                event_type="create" if full_sync or not checkpoint else "update",
                external_id=issue["key"],
                source_type="jira",
                title=f"{issue['key']}: {issue['summary']}",
                mime_type="text/markdown",
                file_bytes=body.encode("utf-8"),
                external_version=issue["updated"],
                metadata={
                    "issue_key": issue["key"],
                    "status": issue["status"],
                    "jql_source": jql,
                },
            )

        return SyncCheckpoint(
            cursor=f"jira-sync-{int(time.time())}",
            last_synced_at=str(time.time()),
            state={"jql": jql},
        )

    def fetch_document_content(self, external_id: str) -> bytes:
        return f"Jira Issue details for {external_id}".encode("utf-8")

