import base64
import time
import email.utils
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple, Generator
import requests
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
from django.conf import settings
from django.utils import timezone as dj_timezone

from .base import SyncCheckpoint, SyncEvent
from .email_base import BaseEmailConnector, EmailMessageDTO, EmailAttachmentDTO
from apps.sources.services import MAX_FILE_SIZE_BYTES, ALLOWED_EXTENSIONS

logger = logging.getLogger(__name__)

GMAIL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class GmailConnector(BaseEmailConnector):
    """
    Enterprise Gmail / Google Workspace Email Connector:
    - Minimum required scope: https://www.googleapis.com/auth/gmail.readonly (read-only)
    - Safe base64url message and attachment decoding
    - Clean HTML-to-text sanitization (malicious scripts & tags stripped)
    - Resumable checkpointing and incremental change detection
    - Rate-limit backoff and automatic token refresh
    - Filters out spam and trash by default
    """

    def __init__(
        self,
        organization_id: str,
        workspace_id: str,
        connection_model=None,
        config: Optional[Dict[str, Any]] = None
    ):
        super().__init__(organization_id, workspace_id, config)
        self.connection = connection_model
        self.client_id = getattr(settings, 'GMAIL_CLIENT_ID', '') or (self.config.get('client_id', ''))
        self.client_secret = getattr(settings, 'GMAIL_CLIENT_SECRET', '') or (self.config.get('client_secret', ''))
        self.redirect_uri = getattr(settings, 'GMAIL_REDIRECT_URI', '') or (self.config.get('redirect_uri', ''))

    @property
    def connector_type(self) -> str:
        return 'gmail'

    @property
    def provider_name(self) -> str:
        return 'gmail'

    # =========================================================================
    # OAuth Helpers
    # =========================================================================

    @classmethod
    def build_authorization_url(cls, client_id: str, redirect_uri: str, state: str) -> str:
        """Constructs the Google OAuth 2.0 authorization URL with offline access and read-only scope."""
        params = {
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': GMAIL_READONLY_SCOPE,
            'access_type': 'offline',
            'prompt': 'consent',
            'state': state,
            'include_granted_scopes': 'true',
        }
        return f"{GMAIL_AUTH_URL}?{urllib.parse.urlencode(params)}"

    @classmethod
    def exchange_code_for_tokens(
        cls,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str
    ) -> Dict[str, Any]:
        """Exchanges an authorization code for access and refresh tokens."""
        payload = {
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        resp = requests.post(GMAIL_TOKEN_URL, data=payload, headers=headers, timeout=15)
        if not resp.ok:
            error_data = {}
            try:
                error_data = resp.json()
            except Exception:
                pass
            error_desc = error_data.get('error_description') or error_data.get('error') or resp.text
            raise ValueError(f"Google OAuth token exchange failed (HTTP {resp.status_code}): {error_desc}")
        return resp.json()

    @classmethod
    def fetch_user_profile(cls, access_token: str) -> Dict[str, Any]:
        """Retrieves user profile (emailAddress, messagesTotal) using access token."""
        headers = {'Authorization': f'Bearer {access_token}'}
        resp = requests.get(f"{GMAIL_API_BASE}/profile", headers=headers, timeout=10)
        if not resp.ok:
            raise ValueError(f"Failed to fetch Gmail profile: HTTP {resp.status_code} {resp.text}")
        return resp.json()

    def refresh_access_token_if_needed(self) -> str:
        """Refreshes the stored access token if expired or about to expire in <= 5 minutes."""
        if not self.connection:
            raise ValueError("No connection model associated with this connector.")

        now = dj_timezone.now()
        token_expires_at = self.connection.token_expires_at
        current_access_token = self.connection.get_access_token()

        if token_expires_at and token_expires_at > (now + dj_timezone.timedelta(minutes=5)) and current_access_token:
            return current_access_token

        refresh_token = self.connection.get_refresh_token()
        if not refresh_token:
            # If no refresh token and current access token is present, fallback to current
            if current_access_token:
                return current_access_token
            raise ValueError("No refresh token available to refresh expired OAuth credentials.")

        payload = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
        }
        resp = requests.post(GMAIL_TOKEN_URL, data=payload, timeout=15)
        if not resp.ok:
            self.connection.status = 'error'
            self.connection.last_error = f"Token refresh failed: HTTP {resp.status_code}"
            self.connection.save(update_fields=['status', 'last_error'])
            raise ValueError(f"Failed to refresh Google OAuth token: HTTP {resp.status_code} {resp.text}")

        data = resp.json()
        new_access_token = data.get('access_token', '')
        expires_in = data.get('expires_in', 3600)

        self.connection.set_tokens(access_token=new_access_token)
        self.connection.token_expires_at = now + dj_timezone.timedelta(seconds=expires_in)
        self.connection.status = 'connected'
        self.connection.last_error = ''
        self.connection.save(update_fields=['encrypted_access_token', 'token_expires_at', 'status', 'last_error'])

        return new_access_token

    def revoke_token(self) -> bool:
        """Revokes the refresh token on Google's authorization servers."""
        if not self.connection:
            return False
        token = self.connection.get_refresh_token() or self.connection.get_access_token()
        if not token:
            return False
        try:
            resp = requests.post(f"{GMAIL_REVOKE_URL}?token={token}", timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.warning("Error revoking Google token: %s", e)
            return False

    def test_connection(self) -> bool:
        """Tests live connectivity to Gmail API."""
        try:
            token = self.refresh_access_token_if_needed()
            headers = {'Authorization': f'Bearer {token}'}
            resp = requests.get(f"{GMAIL_API_BASE}/profile", headers=headers, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.warning("Gmail test_connection failed: %s", e)
            return False

    # =========================================================================
    # Request & Rate Limit Handling
    # =========================================================================

    def _api_get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Performs authenticated GET request to Gmail API with exponential backoff on HTTP 429/503."""
        token = self.refresh_access_token_if_needed()
        headers = {'Authorization': f'Bearer {token}'}
        url = f"{GMAIL_API_BASE}/{endpoint.lstrip('/')}"

        max_retries = 3
        backoff_delay = 1.0

        for attempt in range(max_retries + 1):
            self.throttle()
            resp = requests.get(url, headers=headers, params=params, timeout=20)

            if resp.status_code == 200:
                return resp.json()

            # Handle rate limiting (429) or transient server errors (500, 503)
            if resp.status_code in (429, 500, 503) and attempt < max_retries:
                logger.warning("Gmail API rate limit / transient error (%d). Backing off for %.2fs...", resp.status_code, backoff_delay)
                time.sleep(backoff_delay)
                backoff_delay *= 2.0
                continue

            if resp.status_code == 401:
                # Token might have been invalidated mid-session; refresh and retry once
                if attempt == 0:
                    token = self.refresh_access_token_if_needed()
                    headers['Authorization'] = f'Bearer {token}'
                    continue

            raise ValueError(f"Gmail API error ({resp.status_code}) on {endpoint}: {resp.text}")

        return {}

    # =========================================================================
    # Synchronization & Message Extraction
    # =========================================================================

    def fetch_messages_batch(
        self,
        checkpoint: Optional[SyncCheckpoint] = None,
        max_results: int = 50,
        page_token: Optional[str] = None
    ) -> Tuple[List[str], Optional[str], Optional[SyncCheckpoint]]:
        """
        Queries messages matching enterprise sync criteria:
        - Excludes spam and trash (-in:spam -in:trash)
        - Supports incremental query filtering (after:{timestamp})
        """
        query_parts = ["-in:spam", "-in:trash"]

        # Check incremental checkpoint
        last_epoch = 0
        if checkpoint and checkpoint.last_synced_at:
            try:
                dt = datetime.fromisoformat(checkpoint.last_synced_at)
                last_epoch = int(dt.timestamp())
                if last_epoch > 0:
                    query_parts.append(f"after:{last_epoch - 300}")  # 5 min overlap safety buffer
            except Exception:
                pass

        params: Dict[str, Any] = {
            'q': " ".join(query_parts),
            'maxResults': min(max_results, 100),
        }
        if page_token:
            params['pageToken'] = page_token

        data = self._api_get('messages', params=params)
        raw_msgs = data.get('messages', [])
        message_ids = [m['id'] for m in raw_msgs if 'id' in m]
        next_page_token = data.get('nextPageToken')

        new_checkpoint = checkpoint or SyncCheckpoint()
        new_checkpoint.state['last_query'] = params['q']

        return message_ids, next_page_token, new_checkpoint

    def fetch_message_detail(self, message_id: str) -> EmailMessageDTO:
        """Fetches complete message payload, headers, body, and attachments."""
        data = self._api_get(f"messages/{message_id}", params={'format': 'full'})
        return self._parse_gmail_payload(data)

    def _parse_gmail_payload(self, data: Dict[str, Any]) -> EmailMessageDTO:
        """Parses Gmail raw JSON into EmailMessageDTO with safe decoding and HTML cleaning."""
        msg_id = data.get('id', '')
        thread_id = data.get('threadId', msg_id)
        snippet = data.get('snippet', '')
        labels = data.get('labelIds', [])

        payload = data.get('payload', {})
        headers_list = payload.get('headers', [])
        headers_map: Dict[str, str] = {}
        for h in headers_list:
            headers_map[h.get('name', '').lower()] = h.get('value', '')

        subject = headers_map.get('subject', '(No Subject)')
        sender = headers_map.get('from', '') or 'Unknown Sender'
        recipients = [r.strip() for r in headers_map.get('to', '').split(',') if r.strip()]
        cc_recipients = [c.strip() for c in headers_map.get('cc', '').split(',') if c.strip()]

        # Parse timestamps
        sent_at = None
        date_header = headers_map.get('date')
        if date_header:
            try:
                parsed_tuple = email.utils.parsedate_to_datetime(date_header)
                if parsed_tuple:
                    sent_at = parsed_tuple.astimezone(timezone.utc)
            except Exception:
                pass

        internal_date = data.get('internalDate')
        received_at = None
        if internal_date:
            try:
                received_at = datetime.fromtimestamp(int(internal_date) / 1000.0, tz=timezone.utc)
            except Exception:
                pass

        body_plain_parts: List[str] = []
        body_html_parts: List[str] = []
        attachments: List[EmailAttachmentDTO] = []

        def _traverse_parts(part: Dict[str, Any]):
            mime = part.get('mimeType', '').lower()
            filename = part.get('filename', '')
            body_obj = part.get('body', {}) or {}
            raw_data = body_obj.get('data')
            attachment_id = body_obj.get('attachmentId')
            size = body_obj.get('size', 0)

            # Check if this part is a file attachment
            if filename and (attachment_id or raw_data):
                att_bytes = b''
                if raw_data:
                    att_bytes = self._decode_base64url(raw_data)
                elif attachment_id:
                    # Bounded size check
                    if size <= MAX_FILE_SIZE_BYTES:
                        try:
                            att_data = self._api_get(f"messages/{msg_id}/attachments/{attachment_id}")
                            if 'data' in att_data:
                                att_bytes = self._decode_base64url(att_data['data'])
                        except Exception as e:
                            logger.warning("Could not fetch attachment %s for message %s: %s", filename, msg_id, e)

                if att_bytes:
                    attachments.append(
                        EmailAttachmentDTO(
                            filename=filename,
                            mime_type=mime or 'application/octet-stream',
                            size_bytes=len(att_bytes),
                            data=att_bytes,
                            attachment_id=attachment_id or "",
                            content_id=part.get('headers', {}).get('Content-ID', '')
                        )
                    )
                return

            # Extract textual body parts
            if raw_data:
                decoded_text = self._decode_base64url(raw_data).decode('utf-8', errors='replace')
                if mime == 'text/plain':
                    body_plain_parts.append(decoded_text)
                elif mime == 'text/html':
                    body_html_parts.append(decoded_text)

            for subpart in part.get('parts', []):
                _traverse_parts(subpart)

        _traverse_parts(payload)

        # Body resolution and sanitization
        plain_body = "\n\n".join(body_plain_parts).strip()
        html_body = "\n\n".join(body_html_parts).strip()

        if not plain_body and html_body:
            # Convert HTML to clean, safe markdown / text
            plain_body = self._sanitize_html_to_text(html_body)

        return EmailMessageDTO(
            external_id=msg_id,
            thread_id=thread_id,
            subject=subject,
            sender=sender,
            recipients=recipients,
            cc_recipients=cc_recipients,
            sent_at=sent_at or received_at or datetime.now(timezone.utc),
            received_at=received_at or sent_at or datetime.now(timezone.utc),
            body_plain=plain_body,
            body_html=html_body,
            snippet=snippet,
            labels=labels,
            headers=headers_map,
            attachments=attachments
        )

    @staticmethod
    def _decode_base64url(data_str: str) -> bytes:
        """Safely decodes base64url data string with missing padding."""
        cleaned = data_str.replace('-', '+').replace('_', '/')
        padding = len(cleaned) % 4
        if padding > 0:
            cleaned += '=' * (4 - padding)
        try:
            return base64.b64decode(cleaned)
        except Exception:
            return b""

    @staticmethod
    def _sanitize_html_to_text(html_str: str) -> str:
        """Strips scripts, styles, and extracts readable markdown from HTML email bodies."""
        if not html_str:
            return ""
        if not BeautifulSoup:
            import re
            return re.sub(r'<[^>]+>', ' ', html_str).strip()
        try:
            soup = BeautifulSoup(html_str, 'html.parser')
            # Remove scripts, styles, objects, and iframes for security
            for tag in soup(['script', 'style', 'iframe', 'object', 'embed', 'head', 'noscript']):
                tag.decompose()

            # Convert hyperlinks to Markdown [text](href)
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text().strip()
                if text and href.startswith(('http://', 'https://', 'mailto:')):
                    a.replace_with(f"[{text}]({href})")

            text = soup.get_text(separator='\n')
            # Collapse excessive whitespace
            lines = [l.strip() for l in text.splitlines()]
            clean_text = "\n".join(l for l in lines if l)
            return clean_text
        except Exception:
            return html_str

    def list_events(
        self,
        checkpoint: Optional[SyncCheckpoint] = None,
        full_sync: bool = False
    ) -> Generator[SyncEvent, None, Optional[SyncCheckpoint]]:
        """
        Yields SyncEvent items for new or modified messages since checkpoint.
        Implements BaseConnector contract.
        """
        page_token = None
        max_seen_timestamp = datetime.now(timezone.utc)
        events_emitted = 0
        current_checkpoint = None if full_sync else checkpoint

        while True:
            msg_ids, next_page, updated_cp = self.fetch_messages_batch(
                checkpoint=current_checkpoint,
                max_results=50,
                page_token=page_token
            )

            for mid in msg_ids:
                try:
                    dto = self.fetch_message_detail(mid)
                    if dto.sent_at and dto.sent_at > max_seen_timestamp:
                        max_seen_timestamp = dto.sent_at

                    # Format formatted body
                    recipients_str = ", ".join(dto.recipients) if dto.recipients else "None"
                    cc_str = f"\nCc: {', '.join(dto.cc_recipients)}" if dto.cc_recipients else ""
                    time_str = dto.sent_at.strftime('%Y-%m-%d %H:%M:%S UTC') if dto.sent_at else "Unknown"

                    full_content = (
                        f"# Email: {dto.subject}\n\n"
                        f"From: {dto.sender}\n"
                        f"To: {recipients_str}{cc_str}\n"
                        f"Date: {time_str}\n"
                        f"Thread-ID: {dto.thread_id} • Message-ID: {dto.external_id}\n\n"
                        f"---\n\n"
                        f"{dto.get_clean_body()}\n"
                    )

                    yield SyncEvent(
                        event_type='create',
                        external_id=dto.external_id,
                        source_type='gmail',
                        title=f"Email: {dto.subject}",
                        mime_type='text/plain',
                        file_bytes=full_content.encode('utf-8'),
                        metadata={
                            'thread_id': dto.thread_id,
                            'sender': dto.sender,
                            'recipients': dto.recipients,
                            'sent_at': time_str,
                            'snippet': dto.snippet,
                            'attachments': [
                                {'filename': a.filename, 'mime_type': a.mime_type, 'size': a.size_bytes}
                                for a in dto.attachments
                            ]
                        }
                    )
                    events_emitted += 1
                except Exception as e:
                    logger.warning("Failed processing email message %s: %s", mid, e)
                    continue

            page_token = next_page
            if not page_token:
                break

        return SyncCheckpoint(
            cursor=str(int(max_seen_timestamp.timestamp())),
            last_synced_at=max_seen_timestamp.isoformat(),
            state={'total_synced': events_emitted}
        )

    def fetch_document_content(self, external_id: str) -> bytes:
        """Fetches formatted email document bytes by message identifier."""
        dto = self.fetch_message_detail(external_id)
        content = f"# Email: {dto.subject}\n\nFrom: {dto.sender}\n\n{dto.get_clean_body()}"
        return content.encode('utf-8')
