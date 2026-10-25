import io
import os
import re
import json
import zipfile
import logging
from datetime import datetime, timezone as dt_timezone
from typing import Dict, Any, List, Tuple, Optional

from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError

from .models import SourceDocument, DocumentVersion, DocumentPage, ZipImportJob, ZipImportEntry
from apps.governance.models import SourcePermission, AccessLevel
from apps.governance.layers import PermissionLayer
from apps.audit.models import AuditEvent
from apps.subscriptions.services import QuotaEnforcementService
from apps.ingestion.tasks import process_ingestion_pipeline, process_document_job
from django.conf import settings

logger = logging.getLogger(__name__)


class SlackExportService:
    """
    Dedicated enterprise ingestion engine for Slack export ZIP archives and JSON files:
    - Automatically detects Slack archive signatures (channels.json, users.json, date JSON files).
    - Preserves user attribution, timestamps, threads, replies, and attachments.
    - Enforces Part B privacy policy: Private channels and DMs are restricted to workspace_admin
      and the importing user via LORE's L7 SourcePermission layer.
    - Enforces untrusted classification: Authority level 1 (informal_note) ensures Slack chatter
      never overrides formal approved enterprise governance policies.
    """

    @classmethod
    def is_slack_archive(cls, zip_ref: zipfile.ZipFile) -> bool:
        """Determines if a ZIP archive conforms to a Slack export."""
        names = zip_ref.namelist()
        for name in names:
            norm = name.replace('\\', '/').lower()
            if norm == 'channels.json' or norm.endswith('/channels.json'):
                return True
            if norm == 'users.json' or norm.endswith('/users.json'):
                return True
            if re.search(r'[^/]+/\d{4}-\d{2}-\d{2}\.json$', norm):
                return True
        return False

    @classmethod
    def parse_json_safe(cls, raw_data: Any) -> Any:
        """Safely parses JSON string or bytes, returning None if malformed."""
        if isinstance(raw_data, (bytes, bytearray)):
            try:
                raw_data = raw_data.decode('utf-8')
            except UnicodeDecodeError:
                raw_data = raw_data.decode('latin-1', errors='replace')
        try:
            return json.loads(raw_data)
        except Exception as e:
            logger.warning("Malformed JSON in Slack export: %s", e)
            return None

    @classmethod
    def inspect_slack_archive(cls, zip_ref: zipfile.ZipFile) -> Dict[str, Any]:
        """
        Inspects Slack export ZIP archive:
        - Extracts users map (ID -> real_name, display_name, email).
        - Extracts channels map (channels.json, groups.json, dms.json, mpdms.json).
        - Identifies all message files grouped per channel.
        """
        names = zip_ref.namelist()

        # 1. Parse users
        users_map: Dict[str, Dict[str, Any]] = {}
        users_file = next((n for n in names if n.replace('\\', '/').lower().endswith('users.json')), None)
        if users_file:
            data = cls.parse_json_safe(zip_ref.read(users_file))
            if isinstance(data, list):
                for u in data:
                    uid = u.get('id')
                    if uid:
                        prof = u.get('profile', {}) or {}
                        real_name = u.get('real_name') or prof.get('real_name') or u.get('name', uid)
                        users_map[uid] = {
                            'id': uid,
                            'name': u.get('name', uid),
                            'real_name': real_name,
                            'display_name': prof.get('display_name') or u.get('name', uid),
                            'email': prof.get('email', ''),
                        }

        # 2. Parse channels / groups / dms
        channels_map: Dict[str, Dict[str, Any]] = {}

        def _load_ch_file(fname: str, is_private_default: bool):
            target_f = next((n for n in names if n.replace('\\', '/').lower().endswith(fname)), None)
            if target_f:
                data = cls.parse_json_safe(zip_ref.read(target_f))
                if isinstance(data, list):
                    for ch in data:
                        cid = ch.get('id') or ch.get('name')
                        cname = ch.get('name') or cid
                        is_priv = ch.get('is_private', is_private_default) or ch.get('is_group', False) or ch.get('is_mpim', False)
                        channels_map[cname] = {
                            'id': ch.get('id', cname),
                            'name': cname,
                            'is_private': is_priv,
                            'is_general': ch.get('is_general', False),
                            'topic': (ch.get('topic') or {}).get('value', ''),
                            'purpose': (ch.get('purpose') or {}).get('value', ''),
                            'members': ch.get('members', []),
                        }

        _load_ch_file('channels.json', is_private_default=False)
        _load_ch_file('groups.json', is_private_default=True)
        _load_ch_file('dms.json', is_private_default=True)
        _load_ch_file('mpdms.json', is_private_default=True)

        # 3. Locate message JSON files and group by channel
        meta_basenames = {'channels.json', 'users.json', 'groups.json', 'dms.json', 'mpdms.json', 'integration_logs.json'}
        channel_files: Dict[str, List[str]] = {}

        for n in names:
            norm = n.replace('\\', '/')
            base = os.path.basename(norm).lower()
            if not norm.endswith('.json') or base in meta_basenames:
                continue

            parts = [p for p in norm.split('/') if p]
            if len(parts) >= 2:
                ch_dir = parts[-2]
                channel_files.setdefault(ch_dir, []).append(norm)

        # Format channel summary objects
        channel_summaries: List[Dict[str, Any]] = []
        for ch_dir, files in channel_files.items():
            ch_meta = channels_map.get(ch_dir, {
                'id': ch_dir,
                'name': ch_dir,
                'is_private': ch_dir.startswith(('mpdm-', 'dm-', 'private-')),
                'is_general': False,
                'topic': '',
                'purpose': '',
                'members': []
            })

            # Count messages across all date files (handling malformed files gracefully)
            msg_count = 0
            for fpath in files:
                m_data = cls.parse_json_safe(zip_ref.read(fpath))
                if isinstance(m_data, list):
                    msg_count += len([m for m in m_data if isinstance(m, dict) and m.get('type') == 'message'])

            channel_summaries.append({
                'channel_name': ch_meta['name'],
                'channel_id': ch_meta['id'],
                'is_private': ch_meta['is_private'],
                'topic': ch_meta['topic'],
                'purpose': ch_meta['purpose'],
                'message_count': msg_count,
                'file_count': len(files),
                'files': sorted(files),
            })

        channel_summaries.sort(key=lambda c: c['channel_name'])

        return {
            'users_map': users_map,
            'channels': channel_summaries,
            'total_channels': len(channel_summaries),
            'total_messages': sum(c['message_count'] for c in channel_summaries),
        }

    @classmethod
    def format_slack_timestamp(cls, ts_str: str) -> str:
        """Converts Slack epoch timestamp string (e.g. '1672531199.000100') into human-readable ISO string."""
        try:
            sec = float(ts_str.split('.')[0])
            dt = datetime.fromtimestamp(sec, tz=dt_timezone.utc)
            return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
        except Exception:
            return ts_str

    @classmethod
    def clean_slack_text(cls, text: str, users_map: Dict[str, Dict[str, Any]]) -> str:
        """
        Replaces Slack syntax markup (<@U123>, <#C123|channel>, <http://...|label>)
        with clean, readable markdown references.
        """
        if not text:
            return ""

        # User mentions <@U12345> or <@U12345|display>
        def _replace_user(m):
            raw = m.group(1)
            parts = raw.split('|')
            uid = parts[0]
            if uid in users_map:
                uname = users_map[uid]['real_name'] or users_map[uid]['display_name']
                return f"@{uname}"
            elif len(parts) > 1:
                return f"@{parts[1]}"
            return f"@{uid}"

        text = re.sub(r'<@([A-Z0-9]+(?:\|[^>]+)?)>', _replace_user, text)

        # Channel mentions <#C12345|channel>
        def _replace_ch(m):
            raw = m.group(1)
            parts = raw.split('|')
            return f"#{parts[1]}" if len(parts) > 1 else f"#{parts[0]}"

        text = re.sub(r'<#([A-Z0-9]+(?:\|[^>]+)?)>', _replace_ch, text)

        # Broadcast mentions
        text = text.replace('<!here>', '@here').replace('<!channel>', '@channel').replace('<!everyone>', '@everyone')

        # Links <http://example.com|Label> -> [Label](http://example.com)
        text = re.sub(r'<(https?://[^|>]+)\|([^>]+)>', r'[\2](\1)', text)
        # Bare links <http://example.com> -> [http://example.com](http://example.com)
        text = re.sub(r'<(https?://[^>]+)>', r'[\1](\1)', text)

        return text

    @classmethod
    def normalize_channel(
        cls,
        zip_ref: zipfile.ZipFile,
        channel_info: Dict[str, Any],
        users_map: Dict[str, Dict[str, Any]]
    ) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
        """
        Extracts, normalizes, and groups all messages for a channel.
        Preserves threads, replies, timestamps, attachments, and links.
        Returns:
            (full_markdown_text, page_records, stats_dict)
        """
        ch_name = channel_info['channel_name']
        ch_id = channel_info['channel_id']
        is_private = channel_info['is_private']
        files = channel_info.get('files', [])

        raw_messages: List[Dict[str, Any]] = []
        malformed_files_count = 0

        # Read and collect messages across all date files
        for fpath in files:
            try:
                data = cls.parse_json_safe(zip_ref.read(fpath))
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('type') == 'message':
                            raw_messages.append(item)
                else:
                    malformed_files_count += 1
            except Exception as e:
                logger.warning("Error reading message file %s: %s", fpath, e)
                malformed_files_count += 1

        # Sort chronologically by timestamp
        def _get_ts(m: dict) -> float:
            try:
                return float(m.get('ts', 0))
            except Exception:
                return 0.0

        raw_messages.sort(key=_get_ts)

        # Thread grouping: group replies under root thread messages
        threads_map: Dict[str, List[Dict[str, Any]]] = {}
        standalones: List[Dict[str, Any]] = []

        for m in raw_messages:
            thread_ts = m.get('thread_ts')
            ts = m.get('ts')

            if thread_ts and thread_ts != ts:
                # Reply
                threads_map.setdefault(thread_ts, []).append(m)
            else:
                standalones.append(m)

        # Build Markdown representation with pages
        privacy_label = "PRIVATE CHANNEL (Restricted Access)" if is_private else "PUBLIC CHANNEL (Internal Workspace)"
        header_text = (
            f"# Slack Channel: #{ch_name} (ID: {ch_id})\n"
            f"*Privacy Classification:* {privacy_label}\n"
            f"*Topic:* {channel_info.get('topic') or 'None'}\n"
            f"*Purpose:* {channel_info.get('purpose') or 'None'}\n"
            f"*Extracted Messages:* {len(raw_messages)} • *Threads:* {len(threads_map)}\n"
            f"*Untrusted User Communication Notice:* Authority Rank 1 (informal_note). Statements in chat do not constitute approved governance policies.\n\n"
            f"---\n\n"
        )

        # Divide into pages (batches of 20 top-level messages or threads)
        pages: List[Dict[str, Any]] = []
        batch_size = 20
        total_batches = max(1, (len(standalones) + batch_size - 1) // batch_size)

        for page_idx in range(1, total_batches + 1):
            start = (page_idx - 1) * batch_size
            end = start + batch_size
            batch_roots = standalones[start:end]

            page_lines = []
            if page_idx == 1:
                page_lines.append(header_text)
            else:
                page_lines.append(f"# Slack #{ch_name} — Part {page_idx} of {total_batches}\n\n")

            for root_m in batch_roots:
                root_ts = root_m.get('ts', '')
                root_author_id = root_m.get('user', 'unknown')
                u_info = users_map.get(root_author_id, {})
                author_display = u_info.get('real_name') or u_info.get('display_name') or root_author_id
                time_display = cls.format_slack_timestamp(root_ts)
                clean_msg = cls.clean_slack_text(root_m.get('text', ''), users_map)

                page_lines.append(f"● **{author_display}** [{time_display}] (msg_id: {root_ts}):\n{clean_msg}\n")

                # Attachments
                for att in root_m.get('attachments', []):
                    title = att.get('title', '')
                    link = att.get('title_link') or att.get('from_url', '')
                    att_text = cls.clean_slack_text(att.get('text') or att.get('fallback', ''), users_map)
                    if link and title:
                        page_lines.append(f"  *Attachment:* [{title}]({link}) {att_text}\n")
                    elif title:
                        page_lines.append(f"  *Attachment:* {title} {att_text}\n")
                    elif att_text:
                        page_lines.append(f"  *Attachment:* {att_text}\n")

                # Files
                for fl in root_m.get('files', []):
                    fname = fl.get('name', 'file')
                    furl = fl.get('url_private') or fl.get('permalink', '')
                    page_lines.append(f"  *Referenced File:* [{fname}]({furl})\n")

                # Thread Replies
                replies = threads_map.get(root_ts, [])
                if replies:
                    page_lines.append(f"\n  *Thread Replies ({len(replies)}):*\n")
                    for rep in replies:
                        rep_ts = rep.get('ts', '')
                        rep_uid = rep.get('user', 'unknown')
                        rep_uinfo = users_map.get(rep_uid, {})
                        rep_author = rep_uinfo.get('real_name') or rep_uinfo.get('display_name') or rep_uid
                        rep_time = cls.format_slack_timestamp(rep_ts)
                        rep_text = cls.clean_slack_text(rep.get('text', ''), users_map)
                        page_lines.append(f"  ↳ **{rep_author}** [{rep_time}] (msg_id: {rep_ts}):\n    {rep_text}\n")

                page_lines.append("\n---\n\n")

            page_content = "".join(page_lines).strip()
            if not page_content:
                page_content = f"# Slack #{ch_name}\n\n[Empty channel conversation]"

            pages.append({
                'page_number': page_idx,
                'text': page_content,
                'confidence': 1.0,
                'words_count': len(page_content.split()),
                'width': 800.0,
                'height': 1000.0,
                'extraction_type': 'slack_export_normalized',
                'engine': 'slack_engine',
                'engine_version': '1.0',
                'is_repaired': False,
                'bounding_boxes': []
            })

        full_markdown = "\n\n".join(p['text'] for p in pages)
        stats = {
            'total_messages': len(raw_messages),
            'total_threads': len(threads_map),
            'pages_count': len(pages),
            'malformed_files_count': malformed_files_count,
        }

        return full_markdown, pages, stats

    @classmethod
    def import_channel_to_lore(
        cls,
        workspace,
        user,
        collection,
        channel_info: Dict[str, Any],
        full_text: str,
        page_records: List[Dict[str, Any]],
        job: Optional[ZipImportJob] = None
    ) -> Tuple[SourceDocument, Optional[IngestionJob]]:
        """
        Creates or updates a SourceDocument and DocumentPage records for a Slack channel.
        Provides duplicate detection and safe re-import.
        Enforces L7 SourcePermission based on channel visibility:
        - Private channels & DMs -> AccessLevel.RESTRICTED (visible only to workspace_admin and importing user).
        - Public channels -> AccessLevel.INTERNAL.
        - Authority Level is strictly locked to 1 (informal_note).
        """
        import hashlib
        from apps.sources.views import SourceDocumentViewSet
        sources_view = SourceDocumentViewSet()

        ch_name = channel_info['channel_name']
        is_private = channel_info['is_private']

        safe_filename = f"slack_{re.sub(r'[^a-zA-Z0-9_-]', '_', ch_name)}.txt"
        title = f"Slack #{ch_name}"

        privacy_disclosure = (
            f"[RESTRICTED SLACK CONTENT]: Private channel '#{ch_name}'. "
            f"Visibility restricted to workspace admins and importing user. "
            f"Untrusted communication (Authority Rank 1)."
            if is_private else
            f"Slack public channel export (#{ch_name}). Untrusted user communication (Authority Rank 1)."
        )

        content_bytes = full_text.encode('utf-8')
        content_hash = hashlib.sha256(content_bytes).hexdigest()

        # 1. Duplicate detection: Check for existing document for this channel in workspace
        existing_doc = SourceDocument.objects.filter(
            workspace=workspace,
            title=title
        ).first()

        if existing_doc and existing_doc.file_hash == content_hash:
            logger.info("Exact duplicate Slack channel '%s' detected (hash: %s). Re-using existing document.", title, content_hash)
            existing_job = IngestionJob.objects.filter(document=existing_doc).order_by('-created_at').first()
            return existing_doc, existing_job

        upload_file = SimpleUploadedFile(
            name=safe_filename,
            content=content_bytes,
            content_type='text/plain'
        )

        if existing_doc:
            # Safe re-import: Update existing channel document with new version
            doc = existing_doc
            doc.file_hash = content_hash
            doc.file_size = len(content_bytes)
            doc.description = privacy_disclosure
            doc.file_obj = upload_file
            doc.authority_level = 1
            doc.status = 'queued'
            doc.save()

            ver_num = doc.versions.count() + 1
            doc.versions.filter(is_current=True).update(is_current=False)
            DocumentVersion.objects.create(
                document=doc,
                version_number=ver_num,
                file_hash=content_hash,
                file_obj=doc.file_obj,
                change_summary=f"Re-imported Slack channel update (version {ver_num})",
                is_current=True
            )
            ingestion_job = IngestionJob.objects.create(
                document=doc,
                organization=workspace.organization,
                workspace=workspace,
                status='queued',
                current_stage='inspection'
            )
            if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', True):
                process_ingestion_pipeline(str(ingestion_job.id))
                doc.refresh_from_db()
                ingestion_job.refresh_from_db()
            else:
                task: Any = process_document_job
                task.delay(str(ingestion_job.id))
        else:
            # Canonical pipeline creation
            doc, ingestion_job = sources_view._ingest_single_file(
                file_obj=upload_file,
                workspace=workspace,
                collection=collection,
                user=user,
                title=title,
                description=privacy_disclosure,
                authority_level=1  # Always informal_note
            )

        # 2. Overwrite DocumentPages with structured thread pages
        if page_records:
            DocumentPage.objects.filter(document=doc).delete()
            current_version = doc.versions.filter(is_current=True).first()
            pages_to_create = []
            for p in page_records:
                pages_to_create.append(
                    DocumentPage(
                        document=doc,
                        document_version=current_version,
                        page_number=p['page_number'],
                        text=p['text'],
                        confidence=p['confidence'],
                        words_count=p['words_count'],
                        width=p['width'],
                        height=p['height'],
                        extraction_type=p['extraction_type'],
                        engine=p['engine'],
                        engine_version=p['engine_version'],
                    )
                )
            DocumentPage.objects.bulk_create(pages_to_create)
            doc.page_count = len(pages_to_create)
            doc.save(update_fields=['page_count'])

        # 3. Apply L7 Permission Layer
        access_level = AccessLevel.RESTRICTED if is_private else AccessLevel.INTERNAL
        allowed_users = [user.username] if user and hasattr(user, 'username') else []
        allowed_roles = ['workspace_admin', 'owner'] if is_private else list(PermissionLayer.INTERNAL_ROLES)

        SourcePermission.objects.filter(document=doc).delete()
        SourcePermission.objects.create(
            document=doc,
            access_level=access_level,
            allowed_roles=allowed_roles,
            allowed_users=allowed_users,
            redaction_required=False
        )

        # 4. Audit Event
        AuditEvent.objects.create(
            organization=workspace.organization,
            workspace=workspace,
            user=user,
            event_type='document_uploaded',
            target_type='document',
            target_id=str(doc.id),
            details={
                'source': 'slack_export_engine',
                'channel_name': ch_name,
                'is_private': is_private,
                'access_level': access_level,
                'authority_level': 1,
                'messages_count': channel_info.get('message_count', 0),
                'reimported': existing_doc is not None,
            }
        )

        return doc, ingestion_job

    @classmethod
    def import_single_slack_json(
        cls,
        file_obj,
        workspace,
        user,
        collection=None,
        channel_name: str = 'imported-chat',
        is_private: bool = False
    ) -> Tuple[SourceDocument, Optional[IngestionJob]]:
        """
        Imports an individual Slack conversation JSON file directly uploaded by a user.
        """
        raw_bytes = file_obj.read()
        file_obj.seek(0)

        data = cls.parse_json_safe(raw_bytes)
        if isinstance(data, dict) and 'messages' in data and isinstance(data['messages'], list):
            data = data['messages']

        if not isinstance(data, list):
            raise ValidationError("Invalid Slack JSON: Expected a JSON array of message records.")

        channel_info = {
            'channel_name': channel_name,
            'channel_id': channel_name,
            'is_private': is_private,
            'topic': 'Direct JSON upload',
            'purpose': 'Imported Slack messages',
            'message_count': len([m for m in data if isinstance(m, dict) and m.get('type') == 'message']),
            'files': []
        }

        # Create dummy in-memory zip containing this file to reuse normalization
        dummy_buf = io.BytesIO()
        with zipfile.ZipFile(dummy_buf, 'w') as zf:
            zf.writestr(f"{channel_name}/messages.json", json.dumps(data).encode('utf-8'))
        dummy_buf.seek(0)

        with zipfile.ZipFile(dummy_buf) as zf:
            channel_info['files'] = [f"{channel_name}/messages.json"]
            full_text, pages, stats = cls.normalize_channel(zf, channel_info, users_map={})

        return cls.import_channel_to_lore(
            workspace=workspace,
            user=user,
            collection=collection,
            channel_info=channel_info,
            full_text=full_text,
            page_records=pages
        )
