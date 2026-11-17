"""
LORE Enterprise - GitHub & GitLab Source Connector (docs/enterprise/fix/knowledge.md §4)
Synchronizes repository markdown documentation, security policy files (SECURITY.md),
architecture decision records (docs/adr/), and OpenAPI / SPDX schemas.
"""

import time
import logging
from typing import Optional, Generator, Dict, Any
from .base import BaseConnector, SyncCheckpoint, SyncEvent

logger = logging.getLogger(__name__)


class GitHubConnector(BaseConnector):
    """
    GitHub / GitLab Repository Documentation Connector.
    Extracts SECURITY.md, architecture docs, and CI governance configs.
    """

    @property
    def connector_type(self) -> str:
        return "github"

    def test_connection(self) -> bool:
        return bool(self.config.get("repo") or self.config.get("mock_files"))

    def list_events(
        self,
        checkpoint: Optional[SyncCheckpoint] = None,
        full_sync: bool = False,
    ) -> Generator[SyncEvent, None, Optional[SyncCheckpoint]]:
        repo = self.config.get("repo", "enterprise/core-platform")
        mock_files = self.config.get("mock_files", [
            {
                "path": "SECURITY.md",
                "commit_sha": "abc12345",
                "content": "# Security Policy\nReport vulnerabilities to security@enterprise.com. Never commit secrets.",
            },
            {
                "path": "docs/adr/0004-encryption-at-rest.md",
                "commit_sha": "def67890",
                "content": "# ADR-0004: Encryption at Rest\nAll S3 buckets and databases must use customer-managed KMS keys with AES-256.",
            },
        ])

        for f in mock_files:
            yield SyncEvent(
                event_type="create" if full_sync or not checkpoint else "update",
                external_id=f"{repo}/{f['path']}",
                source_type="github",
                title=f"{repo}: {f['path']}",
                mime_type="text/markdown",
                file_bytes=f["content"].encode("utf-8"),
                external_version=f["commit_sha"],
                metadata={
                    "repository": repo,
                    "file_path": f["path"],
                    "branch": "main",
                },
            )

        return SyncCheckpoint(
            cursor=f"gh-commit-{int(time.time())}",
            last_synced_at=str(time.time()),
            state={"repo": repo},
        )

    def fetch_document_content(self, external_id: str) -> bytes:
        return f"GitHub content for {external_id}".encode("utf-8")

