from rest_framework import serializers
from .models import SourceDocument, DocumentVersion, DocumentPage, ZipImportJob, ZipImportEntry

class DocumentPageSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentPage
        fields = [
            'id', 'page_number', 'text', 'confidence', 'words_count',
            'width', 'height', 'extraction_type', 'engine', 'engine_version',
            'is_repaired', 'bounding_boxes', 'created_at'
        ]

class DocumentVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentVersion
        fields = ['id', 'version_number', 'file_hash', 'change_summary', 'is_current', 'created_at']

class SourceDocumentSerializer(serializers.ModelSerializer):
    pages = DocumentPageSerializer(many=True, read_only=True)
    versions = DocumentVersionSerializer(many=True, read_only=True)
    collection_name = serializers.CharField(source='collection.name', read_only=True)
    workspace_name = serializers.CharField(source='workspace.name', read_only=True)
    owner_username = serializers.CharField(source='owner.username', read_only=True)

    class Meta:
        model = SourceDocument
        fields = [
            'id', 'organization', 'workspace', 'workspace_name', 'collection', 'collection_name',
            'owner', 'owner_username', 'title', 'description', 'original_filename',
            'mime_type', 'file_size', 'file_hash', 'file_obj', 'document_type',
            'status', 'authority_level', 'effective_date', 'expiration_date',
            'stale_after_days', 'current_version_number', 'ocr_confidence', 'page_count',
            'pages', 'versions', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'mime_type', 'file_size', 'file_hash', 'status',
            'ocr_confidence', 'page_count', 'current_version_number', 'created_at', 'updated_at'
        ]


class ZipImportEntrySerializer(serializers.ModelSerializer):
    document_id = serializers.UUIDField(source='document.id', read_only=True, allow_null=True)
    ingestion_job_id = serializers.UUIDField(source='ingestion_job.id', read_only=True, allow_null=True)

    class Meta:
        model = ZipImportEntry
        fields = [
            'id', 'entry_path', 'sanitized_filename', 'file_size', 'compressed_size',
            'file_hash', 'mime_type', 'document_type', 'is_supported', 'is_nested_archive',
            'is_private', 'skip_reason', 'status', 'document_id', 'ingestion_job_id', 'error_message',
            'created_at', 'updated_at'
        ]


class ZipImportJobSerializer(serializers.ModelSerializer):
    entries = ZipImportEntrySerializer(many=True, read_only=True)
    workspace_name = serializers.CharField(source='workspace.name', read_only=True)
    collection_name = serializers.CharField(source='collection.name', read_only=True)
    owner_username = serializers.CharField(source='owner.username', read_only=True)

    class Meta:
        model = ZipImportJob
        fields = [
            'id', 'organization', 'workspace', 'workspace_name', 'collection', 'collection_name',
            'owner', 'owner_username', 'archive_filename', 'archive_size', 'archive_hash',
            'status', 'is_slack_export', 'total_entries', 'supported_entries', 'unsupported_entries',
            'success_count', 'failed_count', 'skipped_count', 'authority_level',
            'description', 'error_message', 'entries', 'created_at', 'updated_at', 'completed_at'
        ]
        read_only_fields = [
            'archive_size', 'archive_hash', 'status', 'is_slack_export', 'total_entries',
            'supported_entries', 'unsupported_entries', 'success_count', 'failed_count',
            'skipped_count', 'created_at', 'updated_at', 'completed_at'
        ]


from .models import EmailAccountConnection, EmailSyncJob


class EmailSyncJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailSyncJob
        fields = [
            'id', 'connection', 'workspace', 'status', 'messages_detected',
            'messages_imported', 'attachments_imported', 'errors', 'duration_ms',
            'started_at', 'completed_at', 'created_at'
        ]


class EmailAccountConnectionSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True)
    workspace_name = serializers.CharField(source='workspace.name', read_only=True)

    class Meta:
        model = EmailAccountConnection
        fields = [
            'id', 'organization', 'workspace', 'workspace_name', 'user', 'user_username',
            'provider', 'email_address', 'account_name', 'status', 'scopes',
            'last_sync_at', 'last_sync_status', 'last_error', 'total_messages_synced',
            'created_at', 'updated_at'
        ]
        # Notice: encrypted_access_token and encrypted_refresh_token are NEVER in fields!


