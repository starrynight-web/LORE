import os
import hashlib
import mimetypes
from typing import Dict, Any, Optional, Generator
from datetime import datetime, timezone

from .base import BaseConnector, SyncCheckpoint, SyncEvent

class LocalFolderConnector(BaseConnector):
    """
    Local / Mounted File System Connector.
    Synchronizes files from a local directory or network mount into LORE.
    Specification: Master Prompt P4 §21 (Generic Connector Framework).
    """

    @property
    def connector_type(self) -> str:
        return 'local_folder'

    def test_connection(self) -> bool:
        folder_path = self.config.get('folder_path', '')
        return os.path.exists(folder_path) and os.path.isdir(folder_path)

    def fetch_document_content(self, external_id: str) -> bytes:
        if not os.path.exists(external_id):
            raise FileNotFoundError(f"File not found: {external_id}")
        with open(external_id, 'rb') as f:
            return f.read()

    def list_events(
        self,
        checkpoint: Optional[SyncCheckpoint] = None,
        full_sync: bool = False
    ) -> Generator[SyncEvent, None, Optional[SyncCheckpoint]]:
        folder_path = self.config.get('folder_path', '')
        if not os.path.exists(folder_path):
            return SyncCheckpoint(last_synced_at=datetime.now(timezone.utc).isoformat())

        last_synced_mtime = 0.0
        if checkpoint and not full_sync:
            try:
                last_synced_mtime = float(checkpoint.cursor or 0.0)
            except ValueError:
                last_synced_mtime = 0.0

        max_mtime_seen = last_synced_mtime

        for root, dirs, files in os.walk(folder_path):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                try:
                    stat = os.stat(file_path)
                    mtime = stat.st_mtime
                    if mtime > max_mtime_seen:
                        max_mtime_seen = mtime

                    # Only yield if file is newer than checkpoint
                    if full_sync or mtime > last_synced_mtime:
                        mime_type, _ = mimetypes.guess_type(file_path)
                        mime_type = mime_type or 'application/octet-stream'

                        hasher = hashlib.sha256()
                        with open(file_path, 'rb') as f:
                            while chunk := f.read(65536):
                                hasher.update(chunk)
                        file_hash = hasher.hexdigest()

                        yield SyncEvent(
                            event_type='create' if full_sync or last_synced_mtime == 0 else 'update',
                            external_id=file_path,
                            source_type='local_folder',
                            title=os.path.splitext(file_name)[0],
                            mime_type=mime_type,
                            content_hash=file_hash,
                            metadata={'file_size': stat.st_size, 'mtime': mtime}
                        )
                except Exception:
                    continue

        return SyncCheckpoint(
            cursor=str(max_mtime_seen),
            last_synced_at=datetime.now(timezone.utc).isoformat(),
            state={'folder_path': folder_path}
        )
