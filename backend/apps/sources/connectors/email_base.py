import abc
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple, Generator
from datetime import datetime
from .base import BaseConnector, SyncCheckpoint, SyncEvent, SyncResult


@dataclass
class EmailAttachmentDTO:
    """Represents an attachment extracted from an email message."""
    filename: str
    mime_type: str
    size_bytes: int
    data: bytes
    attachment_id: str = ""
    content_id: str = ""


@dataclass
class EmailMessageDTO:
    """Provider-neutral Data Transfer Object for an email message."""
    external_id: str
    thread_id: str
    subject: str
    sender: str
    recipients: List[str]
    cc_recipients: List[str] = field(default_factory=list)
    sent_at: Optional[datetime] = None
    received_at: Optional[datetime] = None
    body_plain: str = ""
    body_html: str = ""
    snippet: str = ""
    labels: List[str] = field(default_factory=list)
    headers: Dict[str, str] = field(default_factory=dict)
    attachments: List[EmailAttachmentDTO] = field(default_factory=list)

    def get_clean_body(self) -> str:
        """Returns readable plain text body or fallback."""
        if self.body_plain and self.body_plain.strip():
            return self.body_plain.strip()
        if self.snippet and self.snippet.strip():
            return self.snippet.strip()
        return "[Empty message body]"


class BaseEmailConnector(BaseConnector):
    """
    Provider-neutral base class for Email Connectors (Gmail, Microsoft 365 / Outlook).
    Enforces minimum read-only scope, safe HTML handling, attachment size limits,
    resumable sync checkpoints, and credential security.
    """

    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """Returns the canonical provider identifier (e.g. 'gmail', 'outlook')."""
        pass

    @abc.abstractmethod
    def fetch_messages_batch(
        self,
        checkpoint: Optional[SyncCheckpoint] = None,
        max_results: int = 50,
        page_token: Optional[str] = None
    ) -> Tuple[List[str], Optional[str], Optional[SyncCheckpoint]]:
        """
        Retrieves a page of message IDs matching the sync criteria.
        Returns:
            (message_ids, next_page_token, updated_checkpoint)
        """
        pass

    @abc.abstractmethod
    def fetch_message_detail(self, message_id: str) -> EmailMessageDTO:
        """Fetches and normalizes full message content and attachments."""
        pass

    @abc.abstractmethod
    def refresh_access_token_if_needed(self) -> str:
        """Verifies access token validity and refreshes using stored refresh token if expired."""
        pass

    @abc.abstractmethod
    def revoke_token(self) -> bool:
        """Revokes the OAuth token on the provider's authorization server upon disconnection."""
        pass
