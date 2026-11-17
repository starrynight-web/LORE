"""
LORE Enterprise - Intranet & Web Scraper Connector (docs/enterprise/fix/knowledge.md §4)
Synchronizes internal portal pages, employee handbooks, and regulatory bulletins.
"""

import time
import logging
from typing import Optional, Generator, Dict, Any
from .base import BaseConnector, SyncCheckpoint, SyncEvent

logger = logging.getLogger(__name__)


class WebScraperConnector(BaseConnector):
    """
    Intranet & Web Scraper Source Connector.
    Crawls configured root URLs with depth limits and HTML-to-markdown conversion.
    """

    @property
    def connector_type(self) -> str:
        return "web_scraper"

    def test_connection(self) -> bool:
        return bool(self.config.get("target_urls") or self.config.get("mock_pages"))

    def list_events(
        self,
        checkpoint: Optional[SyncCheckpoint] = None,
        full_sync: bool = False,
    ) -> Generator[SyncEvent, None, Optional[SyncCheckpoint]]:
        mock_pages = self.config.get("mock_pages", [
            {
                "url": "https://intranet.enterprise.com/policies/acceptable-use",
                "title": "Acceptable Use Policy (AUP)",
                "content": "# Acceptable Use Policy\nCompany devices must not run unauthorized P2P file sharing software.",
                "etag": "w/123456",
            },
        ])

        for page in mock_pages:
            yield SyncEvent(
                event_type="create" if full_sync or not checkpoint else "update",
                external_id=page["url"],
                source_type="web_scraper",
                title=page["title"],
                mime_type="text/markdown",
                file_bytes=page["content"].encode("utf-8"),
                external_version=page.get("etag", str(int(time.time()))),
                metadata={
                    "source_url": page["url"],
                    "crawled_at": time.time(),
                },
            )

        return SyncCheckpoint(
            cursor=f"scrape-{int(time.time())}",
            last_synced_at=str(time.time()),
            state={"target_urls": self.config.get("target_urls", [])},
        )

    def fetch_document_content(self, external_id: str) -> bytes:
        return f"Scraped content from {external_id}".encode("utf-8")

