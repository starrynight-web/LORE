import os
import zipfile
import tempfile
import logging
from typing import Dict, Any, List, Optional
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from .models import ZipImportJob, ZipImportEntry, SourceDocument, DocumentVersion
from .zip_security import ZipArchiveSecurityService, ZipSecurityError
from apps.ingestion.models import IngestionJob
from apps.ingestion.tasks import process_ingestion_pipeline, process_document_job
from apps.subscriptions.services import QuotaEnforcementService
from apps.audit.models import AuditEvent
from django.conf import settings

logger = logging.getLogger(__name__)


class ZipImportEngine:
    """
    Orchestrates secure ZIP ingestion into LORE Enterprise:
    1. Deep archive security inspection & safe preview.
    2. Atomic entry extraction and ingestion via LORE's canonical pipeline.
    3. Cancellation, retry-of-failed-only, and comprehensive audit lineage.
    """

    @classmethod
    def preview_archive(
        cls,
        file_obj,
        workspace,
        user,
        collection=None,
        authority_level: int = 3,
        description: str = ''
    ) -> ZipImportJob:
        """
        Secures and previews the archive.
        Creates a ZipImportJob in 'previewed' state and registers all detected entries.
        """
        # 1. Perform deep security inspection
        inspect_data = ZipArchiveSecurityService.inspect_archive(
            file_obj=file_obj,
            archive_filename=getattr(file_obj, 'name', 'archive.zip')
        )

        # 2. Check SaaS storage & upload quotas
        QuotaEnforcementService.check_upload_quota(
            workspace.organization,
            inspect_data['archive_size']
        )

        # 3. Create ZipImportJob record
        with transaction.atomic():
            job = ZipImportJob.objects.create(
                organization=workspace.organization,
                workspace=workspace,
                collection=collection,
                owner=user,
                archive_filename=inspect_data['archive_filename'],
                archive_size=inspect_data['archive_size'],
                archive_hash=inspect_data['archive_hash'],
                archive_file=file_obj,
                status='previewed',
                total_entries=inspect_data['total_entries'],
                supported_entries=inspect_data['supported_entries'],
                unsupported_entries=inspect_data['unsupported_entries'],
                authority_level=1 if inspect_data.get('is_slack_export') else authority_level,
                is_slack_export=inspect_data.get('is_slack_export', False),
                description=description
            )

            # 4. Create ZipImportEntry records
            entries_to_create = []
            for item in inspect_data['entries']:
                entry_status = 'pending' if item['is_supported'] else 'skipped'
                entries_to_create.append(
                    ZipImportEntry(
                        import_job=job,
                        entry_path=item['entry_path'],
                        sanitized_filename=item['sanitized_filename'],
                        file_size=item['file_size'],
                        compressed_size=item['compressed_size'],
                        document_type=item['document_type'],
                        is_supported=item['is_supported'],
                        is_nested_archive=item['is_nested_archive'],
                        is_private=item.get('is_private', False),
                        skip_reason=item['skip_reason'],
                        status=entry_status
                    )
                )
            ZipImportEntry.objects.bulk_create(entries_to_create)

            # 5. Log audit event
            AuditEvent.objects.create(
                organization=workspace.organization,
                workspace=workspace,
                user=user,
                event_type='document_uploaded',
                target_type='zip_import_job',
                target_id=str(job.id),
                details={
                    'action': 'zip_archive_previewed',
                    'filename': job.archive_filename,
                    'total_entries': job.total_entries,
                    'supported_entries': job.supported_entries,
                    'unsupported_entries': job.unsupported_entries,
                    'sha256': job.archive_hash,
                }
            )

        return job

    @classmethod
    def execute_import(
        cls,
        job: ZipImportJob,
        user,
        entry_ids: Optional[List[str]] = None
    ) -> ZipImportJob:
        """
        Executes ingestion for supported entries in the archive.
        Reuses LORE's canonical ingestion pipeline (`_ingest_single_file`).
        Supports partial failure: failures do not abort remaining files.
        """
        if job.status == 'cancelled':
            raise ValidationError("Cannot start or resume a cancelled ZIP import job.")

        if not job.archive_file or not os.path.exists(job.archive_file.path):
            job.status = 'failed'
            job.error_message = "Stored archive file is missing or unreadable on disk."
            job.save(update_fields=['status', 'error_message'])
            return job

        job.status = 'processing'
        job.error_message = ''
        job.save(update_fields=['status', 'error_message'])

        # Filter entries to process
        entries_qs = job.entries.filter(is_supported=True)
        if entry_ids:
            entries_qs = entries_qs.filter(id__in=entry_ids)
        else:
            entries_qs = entries_qs.filter(status__in=['pending', 'failed'])

        entries_to_process = list(entries_qs)
        if not entries_to_process:
            # If nothing to process, update status based on existing counts
            cls._finalize_job_status(job)
            return job

        # Read archive safely inside bounded temporary context
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                zip_ref = zipfile.ZipFile(job.archive_file.path, 'r')
            except Exception as e:
                job.status = 'failed'
                job.error_message = f"Failed to open archive: {str(e)}"
                job.save(update_fields=['status', 'error_message'])
                return job

            with zip_ref:
                if job.is_slack_export:
                    from .slack_engine import SlackExportService
                    slack_data = SlackExportService.inspect_slack_archive(zip_ref)
                    users_map = slack_data['users_map']
                    channels_by_name = {c['channel_name']: c for c in slack_data['channels']}

                    for entry in entries_to_process:
                        job.refresh_from_db(fields=['status'])
                        if job.status == 'cancelled':
                            job.entries.filter(status='pending').update(status='cancelled')
                            break

                        ch_name = entry.entry_path.replace('slack/', '')
                        ch_info = channels_by_name.get(ch_name)
                        if not ch_info:
                            entry.status = 'failed'
                            entry.error_message = f"Slack channel '{ch_name}' not found in archive."
                            entry.save(update_fields=['status', 'error_message'])
                            continue

                        try:
                            full_text, pages, stats = SlackExportService.normalize_channel(
                                zip_ref=zip_ref,
                                channel_info=ch_info,
                                users_map=users_map
                            )
                            doc, ingestion_job = SlackExportService.import_channel_to_lore(
                                workspace=job.workspace,
                                user=job.owner,
                                collection=job.collection,
                                channel_info=ch_info,
                                full_text=full_text,
                                page_records=pages,
                                job=job
                            )
                            entry.status = 'imported'
                            entry.document = doc
                            entry.ingestion_job = ingestion_job
                            entry.mime_type = doc.mime_type
                            entry.document_type = doc.document_type
                            entry.file_size = doc.file_size
                            entry.file_hash = doc.file_hash
                            entry.error_message = ''
                            entry.save()
                        except Exception as err:
                            logger.warning("Failed importing Slack channel '%s': %s", ch_name, err)
                            entry.status = 'failed'
                            entry.error_message = str(err)
                            entry.save()

                    cls._finalize_job_status(job)
                    return job

                # Standard ZIP document extraction
                # Map ZipInfo by original path and normalized path
                info_map = {
                    info.filename.replace('\\', '/'): info for info in zip_ref.infolist()
                }

                from .views import SourceDocumentViewSet
                sources_view = SourceDocumentViewSet()

                for entry in entries_to_process:
                    # Check for external cancellation
                    job.refresh_from_db(fields=['status'])
                    if job.status == 'cancelled':
                        # Mark remaining entries as cancelled
                        job.entries.filter(status='pending').update(status='cancelled')
                        break

                    # Locate corresponding ZipInfo
                    matching_info = None
                    for norm_path, info in info_map.items():
                        # Try exact match or suffix match
                        if norm_path == entry.entry_path or norm_path.endswith('/' + entry.entry_path) or info.filename == entry.entry_path:
                            matching_info = info
                            break

                    if not matching_info:
                        # Fallback: search by basename
                        for norm_path, info in info_map.items():
                            if os.path.basename(norm_path) == entry.sanitized_filename:
                                matching_info = info
                                break

                    if not matching_info:
                        entry.status = 'failed'
                        entry.error_message = f"Archive entry '{entry.entry_path}' not found in ZIP index."
                        entry.save(update_fields=['status', 'error_message'])
                        continue

                    # Extract file with safe streaming and size bounding
                    safe_temp_name = f"{entry.id}_{entry.sanitized_filename}"
                    try:
                        extracted_file_path, file_sha256, actual_size = ZipArchiveSecurityService.extract_single_entry_bounded(
                            zip_ref=zip_ref,
                            info=matching_info,
                            target_dir=temp_dir,
                            sanitized_filename=safe_temp_name
                        )

                        entry.file_hash = file_sha256
                        entry.file_size = actual_size

                        # Read into Django UploadedFile to pass to canonical pipeline
                        with open(extracted_file_path, 'rb') as f:
                            content = f.read()

                        upload_file = SimpleUploadedFile(
                            name=entry.sanitized_filename,
                            content=content,
                            content_type=entry.mime_type or 'application/octet-stream'
                        )

                        clean_title = os.path.splitext(entry.sanitized_filename)[0]

                        # Ingest through LORE's canonical pipeline
                        doc, ingestion_job = sources_view._ingest_single_file(
                            file_obj=upload_file,
                            workspace=job.workspace,
                            collection=job.collection,
                            user=job.owner,
                            title=clean_title,
                            description=job.description or f"Imported from {job.archive_filename}",
                            authority_level=job.authority_level
                        )

                        entry.status = 'imported'
                        entry.document = doc
                        entry.ingestion_job = ingestion_job
                        entry.mime_type = doc.mime_type
                        entry.document_type = doc.document_type
                        entry.error_message = ''
                        entry.save()

                    except Exception as err:
                        logger.warning("Failed importing entry '%s' from ZIP: %s", entry.entry_path, err)
                        entry.status = 'failed'
                        entry.error_message = str(err)
                        entry.save()
                    finally:
                        # Ensure temp file is cleaned up immediately
                        try:
                            target_temp = os.path.join(temp_dir, safe_temp_name)
                            if os.path.exists(target_temp):
                                os.remove(target_temp)
                        except Exception:
                            pass

        cls._finalize_job_status(job)
        return job

    @classmethod
    def retry_failed_entries(cls, job: ZipImportJob, user) -> ZipImportJob:
        """
        Retries ONLY entries that failed in a previous import attempt.
        Successfully imported documents are left untouched.
        """
        failed_entries = job.entries.filter(status='failed', is_supported=True)
        if not failed_entries.exists():
            return job

        failed_ids = [str(e.id) for e in failed_entries]
        failed_entries.update(status='pending', error_message='')

        return cls.execute_import(job=job, user=user, entry_ids=failed_ids)

    @classmethod
    def cancel_job(cls, job: ZipImportJob, user) -> ZipImportJob:
        """
        Cancels an in-flight or pending ZIP import job.
        Marks pending entries as cancelled.
        """
        with transaction.atomic():
            job.status = 'cancelled'
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'completed_at'])

            job.entries.filter(status='pending').update(status='cancelled')

            AuditEvent.objects.create(
                organization=job.organization,
                workspace=job.workspace,
                user=user,
                event_type='document_uploaded',
                target_type='zip_import_job',
                target_id=str(job.id),
                details={
                    'action': 'zip_import_cancelled',
                    'filename': job.archive_filename,
                    'success_count': job.success_count,
                    'failed_count': job.failed_count,
                }
            )

        return job

    @classmethod
    def _finalize_job_status(cls, job: ZipImportJob):
        """Calculates final tallies and overall status."""
        job.refresh_from_db()
        if job.status == 'cancelled':
            return

        entries = job.entries.all()
        job.success_count = entries.filter(status='imported').count()
        job.failed_count = entries.filter(status='failed').count()
        job.skipped_count = entries.filter(status__in=['skipped', 'cancelled']).count()

        if job.failed_count == 0 and job.success_count > 0:
            job.status = 'completed'
        elif job.success_count > 0 and job.failed_count > 0:
            job.status = 'partial_success'
        elif job.failed_count > 0 and job.success_count == 0:
            job.status = 'failed'
        else:
            job.status = 'completed'

        job.completed_at = timezone.now()
        job.save()

        AuditEvent.objects.create(
            organization=job.organization,
            workspace=job.workspace,
            user=job.owner,
            event_type='ingestion_completed',
            target_type='zip_import_job',
            target_id=str(job.id),
            details={
                'action': 'zip_import_finished',
                'status': job.status,
                'filename': job.archive_filename,
                'success_count': job.success_count,
                'failed_count': job.failed_count,
                'skipped_count': job.skipped_count,
            }
        )

    @classmethod
    def generate_summary(cls, job: ZipImportJob) -> Dict[str, Any]:
        """Returns structured import summary with per-file status breakdown."""
        entries = job.entries.all()
        entry_list = []
        for e in entries:
            entry_list.append({
                'id': str(e.id),
                'entry_path': e.entry_path,
                'sanitized_filename': e.sanitized_filename,
                'file_size': e.file_size,
                'file_hash': e.file_hash,
                'document_type': e.document_type,
                'is_supported': e.is_supported,
                'is_nested_archive': e.is_nested_archive,
                'skip_reason': e.skip_reason,
                'status': e.status,
                'document_id': str(e.document.id) if e.document else None,
                'document_title': e.document.title if e.document else None,
                'error_message': e.error_message,
            })

        return {
            'job_id': str(job.id),
            'archive_filename': job.archive_filename,
            'archive_size': job.archive_size,
            'archive_hash': job.archive_hash,
            'status': job.status,
            'total_entries': job.total_entries,
            'supported_entries': job.supported_entries,
            'unsupported_entries': job.unsupported_entries,
            'success_count': job.success_count,
            'failed_count': job.failed_count,
            'skipped_count': job.skipped_count,
            'error_message': job.error_message,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            'entries': entry_list,
        }
