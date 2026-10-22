import abc
import time
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Generator
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class SyncCheckpoint:
    """
    Tracks state of external system synchronizations to enable robust incremental synchronization.
    """
    cursor: Optional[str] = None
    last_synced_at: Optional[str] = None
    state: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'cursor': self.cursor,
            'last_synced_at': self.last_synced_at,
            'state': self.state
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> 'SyncCheckpoint':
        if not data:
            return cls()
        return cls(
            cursor=data.get('cursor'),
            last_synced_at=data.get('last_synced_at'),
            state=data.get('state', {})
        )

@dataclass
class SyncEvent:
    """
    Represents an atomic external source event (create, update, delete).
    """
    event_type: str  # 'create', 'update', 'delete'
    external_id: str
    source_type: str
    title: str
    mime_type: str
    file_bytes: Optional[bytes] = None
    download_url: Optional[str] = None
    content_hash: Optional[str] = None
    external_version: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def calculate_hash(self) -> str:
        if self.file_bytes:
            return hashlib.sha256(self.file_bytes).hexdigest()
        if self.content_hash:
            return self.content_hash
        return hashlib.sha256(f"{self.external_id}:{self.external_version}".encode()).hexdigest()

@dataclass
class SyncResult:
    """
    Summary outcome of a connector synchronization run.
    """
    connector_name: str
    success: bool
    events_detected: int = 0
    documents_created: int = 0
    documents_updated: int = 0
    documents_deleted: int = 0
    errors: List[str] = field(default_factory=list)
    next_checkpoint: Optional[SyncCheckpoint] = None
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'connector_name': self.connector_name,
            'success': self.success,
            'events_detected': self.events_detected,
            'documents_created': self.documents_created,
            'documents_updated': self.documents_updated,
            'documents_deleted': self.documents_deleted,
            'errors': self.errors,
            'next_checkpoint': self.next_checkpoint.to_dict() if self.next_checkpoint else None,
            'duration_ms': self.duration_ms
        }

class BaseConnector(abc.ABC):
    """
    Abstract Contract for Enterprise Source Connectors (SharePoint, Drive, S3, Confluence, etc.).
    Supports full and incremental synchronization, rate limiting, and change detection.
    """

    def __init__(self, organization_id: str, workspace_id: str, config: Optional[Dict[str, Any]] = None):
        self.organization_id = organization_id
        self.workspace_id = workspace_id
        self.config = config or {}
        self.rate_limit_delay_seconds = float(self.config.get('rate_limit_delay_seconds', 0.1))

    @property
    @abc.abstractmethod
    def connector_type(self) -> str:
        """Returns connector identifier (e.g. 'sharepoint', 's3', 'google_drive')."""
        pass

    @abc.abstractmethod
    def test_connection(self) -> bool:
        """Validates credentials and network connectivity to the upstream source."""
        pass

    @abc.abstractmethod
    def list_events(
        self,
        checkpoint: Optional[SyncCheckpoint] = None,
        full_sync: bool = False
    ) -> Generator[SyncEvent, None, Optional[SyncCheckpoint]]:
        """
        Yields SyncEvent objects detected since the checkpoint.
        Returns the new SyncCheckpoint upon completion.
        """
        pass

    @abc.abstractmethod
    def fetch_document_content(self, external_id: str) -> bytes:
        """Fetches the raw document bytes for a specific external identifier."""
        pass

    def throttle(self):
        """Applies rate-limiting delay between upstream requests."""
        if self.rate_limit_delay_seconds > 0:
            time.sleep(self.rate_limit_delay_seconds)

    def sync(
        self,
        checkpoint: Optional[SyncCheckpoint] = None,
        full_sync: bool = False
    ) -> SyncResult:
        """
        Default high-level synchronization orchestration.
        Iterates over discovered events and yields SyncResult.
        """
        t0 = time.time()
        result = SyncResult(
            connector_name=self.connector_type,
            success=False
        )

        try:
            event_gen = self.list_events(checkpoint=checkpoint, full_sync=full_sync)
            while True:
                try:
                    event = next(event_gen)
                    self.throttle()
                    result.events_detected += 1
                    if event.event_type == 'create':
                        result.documents_created += 1
                    elif event.event_type == 'update':
                        result.documents_updated += 1
                    elif event.event_type == 'delete':
                        result.documents_deleted += 1
                except StopIteration as stop:
                    result.next_checkpoint = stop.value
                    break

            result.success = True
        except Exception as e:
            logger.exception(f"Error during {self.connector_type} sync: {e}")
            result.errors.append(str(e))
            result.success = False

        result.duration_ms = int((time.time() - t0) * 1000)
        return result
