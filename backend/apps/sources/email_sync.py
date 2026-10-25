import io
import time
import os
import re
import logging
from typing import Dict, Any, Optional, List, Tuple
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from .models import SourceDocument, EmailAccountConnection, EmailSyncJob
from .connectors.gmail import GmailConnector
from .connectors.base import SyncCheckpoint
from .services import ALLOWED_EXTENSIONS, MAX_FILE_SIZE_BYTES
from apps.governance.models import SourcePermission, AccessLevel
from apps.governance.layers import PermissionLayer
from apps.audit.models import AuditEvent
from apps.subscriptions.services import QuotaEnforcementService

logger = logging.getLogger(__name__)


class EmailSyncService:
    """
    Enterprise Email Ingestion and Lifecycle Service:
    - Orchestrates incremental and full email account synchronization.
    - Preserves provenance, thread IDs, timestamps, and sender/recipient attribution.
    - Routes email text and attachments into LORE's canonical settlement pipeline.
    - Enforces Step 4 privacy policy: Mailbox visibility is strictly restricted
      to the connecting user and workspace_admins via LORE L7 SourcePermission layer.
    - Enforces untrusted communication classification (Authority Rank 1 / informal_note).
    - Supports atomic disconnect with documented retention or cascade deletion choice.
    """

    @classmethod
    def get_connector_for_connection(cls, connection: EmailAccountConnection):
        """Factory creating the appropriate connector instance for the connection."""
        if connection.provider == 'gmail':
            return GmailConnector(
                organization_id=str(connection.organization.id),
                workspace_id=str(connection.workspace.id),
                connection_model=connection
            )
        else:
            raise NotImplementedError(f"Email provider '{connection.provider}' is not supported yet.")

    @classmethod
    def trigger_sync(
        cls,
        connection: EmailAccountConnection,
        user,
        max_messages: int = 50,
        full_sync: bool = False
    ) -> EmailSyncJob:
        """
        Executes email synchronization for the given connection.
        Supports resume via checkpoints, rate-limit tolerance, and duplicate prevention.
        """
        if connection.status == 'disconnected':
            raise ValueError("Cannot synchronize a disconnected email account.")

        t0 = time.time()
        connection.status = 'syncing'
        connection.last_sync_status = 'syncing'
        connection.last_error = ''
        connection.save(update_fields=['status', 'last_sync_status', 'last_error'])

        sync_job = EmailSyncJob.objects.create(
            connection=connection,
            workspace=connection.workspace,
            status='running',
            started_at=timezone.now()
        )

        from .views import SourceDocumentViewSet
        sources_view = SourceDocumentViewSet()

        connector = cls.get_connector_for_connection(connection)
        checkpoint = None if full_sync else SyncCheckpoint.from_dict(connection.sync_checkpoint)

        page_token = None
        messages_detected = 0
        messages_imported = 0
        attachments_imported = 0
        errors: List[str] = []

        try:
            # Query matching messages batch
            msg_ids, next_page, updated_checkpoint = connector.fetch_messages_batch(
                checkpoint=checkpoint,
                max_results=max_messages,
                page_token=page_token
            )
            messages_detected = len(msg_ids)

            for mid in msg_ids:
                try:
                    # 1. Fetch detailed message DTO
                    dto = connector.fetch_message_detail(mid)

                    # 2. Duplicate prevention: Check if already indexed in this workspace
                    existing_doc = SourceDocument.objects.filter(
                        workspace=connection.workspace,
                        external_id=dto.external_id
                    ).first()

                    if existing_doc:
                        logger.info("Email message %s already indexed. Skipping duplicate.", dto.external_id)
                        continue

                    # 3. Format structured document representation
                    recipients_str = ", ".join(dto.recipients) if dto.recipients else "None"
                    cc_str = f"\nCc: {', '.join(dto.cc_recipients)}" if dto.cc_recipients else ""
                    time_str = dto.sent_at.strftime('%Y-%m-%d %H:%M:%S UTC') if dto.sent_at else "Unknown"

                    full_text = (
                        f"# Email: {dto.subject}\n\n"
                        f"**From:** {dto.sender}\n"
                        f"**To:** {recipients_str}{cc_str}\n"
                        f"**Date:** {time_str}\n"
                        f"**Thread-ID:** {dto.thread_id} • **Message-ID:** {dto.external_id}\n\n"
                        f"---\n\n"
                        f"{dto.get_clean_body()}\n"
                    )

                    privacy_disclosure = (
                        f"[RESTRICTED EMAIL]: Synced from mailbox '{connection.email_address}'. "
                        f"From: {dto.sender}. Thread-ID: {dto.thread_id}. "
                        f"Visibility restricted to mailbox owner and workspace admins. "
                        f"Untrusted communication (Authority Rank 1)."
                    )

                    clean_title = f"Email: {dto.subject.strip() or '(No Subject)'}"[:250]
                    safe_filename = f"email_{re.sub(r'[^a-zA-Z0-9_-]', '_', dto.external_id)}.txt"

                    upload_file = SimpleUploadedFile(
                        name=safe_filename,
                        content=full_text.encode('utf-8'),
                        content_type='text/plain'
                    )

                    # 4. Ingest through LORE's canonical pipeline with authority_level=1
                    doc, ingestion_job = sources_view._ingest_single_file(
                        file_obj=upload_file,
                        workspace=connection.workspace,
                        collection=None,
                        user=connection.user,
                        title=clean_title,
                        description=privacy_disclosure,
                        authority_level=1  # Always informal_note
                    )

                    # Set connector linkage
                    doc.external_id = dto.external_id
                    doc.email_connection = connection
                    doc.save(update_fields=['external_id', 'email_connection'])

                    # 5. Enforce Step 4 Privacy: RESTRICTED access to mailbox owner & admin
                    SourcePermission.objects.filter(document=doc).delete()
                    SourcePermission.objects.create(
                        document=doc,
                        access_level=AccessLevel.RESTRICTED,
                        allowed_roles=['workspace_admin', 'owner'],
                        allowed_users=[connection.user.username],
                        redaction_required=False
                    )

                    messages_imported += 1

                    # 6. Process supported attachments
                    for att in dto.attachments:
                        att_ext = os.path.splitext(att.filename.lower())[1]
                        if att_ext in ALLOWED_EXTENSIONS and att.size_bytes <= MAX_FILE_SIZE_BYTES:
                            try:
                                att_upload = SimpleUploadedFile(
                                    name=att.filename,
                                    content=att.data,
                                    content_type=att.mime_type
                                )
                                att_title = f"Attachment: {att.filename} ({clean_title})"[:250]
                                att_desc = f"Attachment from email message {dto.external_id} ({connection.email_address})"

                                att_doc, att_job = sources_view._ingest_single_file(
                                    file_obj=att_upload,
                                    workspace=connection.workspace,
                                    collection=None,
                                    user=connection.user,
                                    title=att_title,
                                    description=att_desc,
                                    authority_level=1
                                )
                                att_doc.external_id = f"{dto.external_id}_att_{att.filename}"
                                att_doc.email_connection = connection
                                att_doc.save(update_fields=['external_id', 'email_connection'])

                                # Apply same restricted permission
                                SourcePermission.objects.filter(document=att_doc).delete()
                                SourcePermission.objects.create(
                                    document=att_doc,
                                    access_level=AccessLevel.RESTRICTED,
                                    allowed_roles=['workspace_admin', 'owner'],
                                    allowed_users=[connection.user.username],
                                    redaction_required=False
                                )
                                attachments_imported += 1
                            except Exception as att_err:
                                logger.warning("Could not ingest attachment %s: %s", att.filename, att_err)

                except Exception as msg_err:
                    err_msg = f"Message {mid} sync error: {str(msg_err)}"
                    logger.warning(err_msg)
                    errors.append(err_msg)

            # Update connection state and checkpoint
            now = timezone.now()
            connection.status = 'connected'
            connection.last_sync_at = now
            connection.last_sync_status = 'partial_success' if errors else 'success'
            connection.total_messages_synced += messages_imported
            if updated_checkpoint:
                updated_checkpoint.last_synced_at = now.isoformat()
                connection.sync_checkpoint = updated_checkpoint.to_dict()
            connection.save(update_fields=['status', 'last_sync_at', 'last_sync_status', 'total_messages_synced', 'sync_checkpoint'])

            sync_job.status = 'partial_success' if errors else 'completed'
            sync_job.messages_detected = messages_detected
            sync_job.messages_imported = messages_imported
            sync_job.attachments_imported = attachments_imported
            sync_job.errors = errors
            sync_job.duration_ms = int((time.time() - t0) * 1000)
            sync_job.completed_at = now
            sync_job.save()

            # Audit event
            AuditEvent.objects.create(
                organization=connection.organization,
                workspace=connection.workspace,
                user=user,
                event_type='ingestion_completed',
                target_type='email_account_connection',
                target_id=str(connection.id),
                details={
                    'action': 'email_synchronized',
                    'email_address': connection.email_address,
                    'provider': connection.provider,
                    'messages_detected': messages_detected,
                    'messages_imported': messages_imported,
                    'attachments_imported': attachments_imported,
                    'errors_count': len(errors),
                }
            )

        except Exception as e:
            logger.exception("Fatal error during email synchronization: %s", e)
            connection.status = 'error'
            connection.last_sync_status = 'failed'
            connection.last_error = str(e)
            connection.save(update_fields=['status', 'last_sync_status', 'last_error'])

            sync_job.status = 'failed'
            sync_job.errors = [str(e)]
            sync_job.duration_ms = int((time.time() - t0) * 1000)
            sync_job.completed_at = timezone.now()
            sync_job.save()

        return sync_job

    @classmethod
    def disconnect_connection(
        cls,
        connection: EmailAccountConnection,
        user,
        retain_content: bool = True
    ) -> Dict[str, Any]:
        """
        Disconnects an email connection:
        - Stops further synchronization.
        - Revokes provider OAuth token if possible.
        - If retain_content is False: Cascades deletion of all SourceDocument records
          imported from this connection, leaving all other workspace documents untouched.
        - If retain_content is True: Preserves indexed documents with existing restricted permissions.
        """
        # Revoke provider token
        try:
            connector = cls.get_connector_for_connection(connection)
            connector.revoke_token()
        except Exception as e:
            logger.warning("Token revocation exception during disconnect: %s", e)

        purged_count = 0
        if not retain_content:
            # Delete all documents belonging strictly to this connection
            docs_to_delete = SourceDocument.objects.filter(email_connection=connection)
            purged_count = docs_to_delete.count()
            docs_to_delete.delete()

        # Update connection status
        connection.status = 'disconnected'
        connection.encrypted_access_token = ''
        connection.encrypted_refresh_token = ''
        connection.last_sync_status = 'disconnected'
        connection.save(update_fields=['status', 'encrypted_access_token', 'encrypted_refresh_token', 'last_sync_status'])

        # Audit Event
        AuditEvent.objects.create(
            organization=connection.organization,
            workspace=connection.workspace,
            user=user,
            event_type='decision_recorded',
            target_type='email_account_connection',
            target_id=str(connection.id),
            details={
                'action': 'email_account_disconnected',
                'email_address': connection.email_address,
                'provider': connection.provider,
                'retain_content': retain_content,
                'documents_purged': purged_count
            }
        )

        return {
            'connection_id': str(connection.id),
            'status': 'disconnected',
            'retain_content': retain_content,
            'documents_purged': purged_count
        }
