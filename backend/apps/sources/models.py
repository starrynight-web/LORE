import uuid
from django.db import models
from django.contrib.auth.models import User
from apps.identity.models import Organization
from apps.workspaces.models import Workspace, Collection

class SourceDocument(models.Model):
    DOCUMENT_TYPES = [
        ('pdf', 'Portable Document Format (PDF)'),
        ('docx', 'Microsoft Word (DOCX)'),
        ('txt', 'Plaintext / Markdown'),
        ('image', 'Image (PNG/JPEG)'),
        ('spreadsheet', 'Spreadsheet (CSV/XLSX)'),
        ('presentation', 'Presentation (PPTX)'),
        ('other', 'Other Document'),
    ]

    STATUS_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('queued', 'Queued for Ingestion'),
        ('extracting', 'Extracting Text / OCR'),
        ('normalizing', 'Normalizing Content'),
        ('chunking', 'Chunking & Structural Analysis'),
        ('embedding', 'Generating Vectors'),
        ('indexing', 'Indexing Graph & Search'),
        ('ready', 'Ready / Active'),
        ('approved', 'Approved Policy'),
        ('draft', 'Draft (Unapproved)'),
        ('archived', 'Archived Record'),
        ('superseded', 'Superseded Policy'),
        ('future-effective', 'Future-Effective Rule'),
        ('unknown', 'Unknown Status'),
        ('failed', 'Processing Failed'),
        ('needs_review', 'Needs Review'),
        ('quarantined', 'Quarantined / Untrusted'),
    ]

    AUTHORITY_LEVELS = [
        (1, 'informal_note (Rank 1)'),
        (2, 'wiki_entry (Rank 2)'),
        (3, 'reviewed_document (Rank 3)'),
        (4, 'maintained_procedure (Rank 4)'),
        (5, 'team_convention (Rank 5)'),
        (6, 'signed_contract (Rank 6)'),
        (7, 'approved_policy (Rank 7)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='documents')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='documents')
    collection = models.ForeignKey(Collection, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='owned_documents')

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    original_filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100)
    file_size = models.PositiveBigIntegerField()
    file_hash = models.CharField(max_length=64, db_index=True)  # SHA-256
    file_obj = models.FileField(upload_to='documents/%Y/%m/')
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES, default='pdf')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded')

    # Governance metadata (lore.md L6 & L5)
    authority_level = models.PositiveSmallIntegerField(choices=AUTHORITY_LEVELS, default=3)
    effective_date = models.DateTimeField(null=True, blank=True)
    expiration_date = models.DateTimeField(null=True, blank=True)
    stale_after_days = models.IntegerField(default=365)

    # Enhanced Document Identity, Status, and Temporal Governance
    document_code = models.CharField(max_length=50, blank=True, default='', db_index=True)
    canonical_title = models.CharField(max_length=255, blank=True, default='')
    owner_name = models.CharField(max_length=255, blank=True, default='')
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_to = models.DateTimeField(null=True, blank=True)
    approval_date = models.DateTimeField(null=True, blank=True)
    superseded_by = models.CharField(max_length=255, blank=True, default='')
    source_uri = models.CharField(max_length=500, blank=True, default='')
    governance_status = models.CharField(max_length=50, blank=True, default='')
    is_missing = models.BooleanField(default=False)
    validation_notes = models.JSONField(default=dict, blank=True)
    
    current_version_number = models.PositiveIntegerField(default=1)
    ocr_confidence = models.FloatField(default=0.0)
    page_count = models.PositiveIntegerField(default=1)

    # Connector provenance tracking
    external_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    email_connection = models.ForeignKey(
        'EmailAccountConnection',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='synced_documents'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Keep effective_date and effective_from synchronized
        if self.effective_from and not self.effective_date:
            self.effective_date = self.effective_from
        elif self.effective_date and not self.effective_from:
            self.effective_from = self.effective_date
        # Keep expiration_date and effective_to synchronized
        if self.effective_to and not self.expiration_date:
            self.expiration_date = self.effective_to
        elif self.expiration_date and not self.effective_to:
            self.effective_to = self.expiration_date
        super().save(*args, **kwargs)

        # Invalidate workspace cache on document edits/status changes
        try:
            from apps.retrieval.cache import TenantSafeCacheService
            TenantSafeCacheService.invalidate_workspace(str(self.workspace_id))
        except Exception:
            pass

    def delete(self, *args, **kwargs):
        doc_id = str(self.id)
        ws_id = str(self.workspace_id)
        # 1. Clean up vector index in Qdrant
        try:
            from apps.retrieval.vector_store import QdrantVectorStore
            QdrantVectorStore().delete_document_chunks("lore_chunks", doc_id)
        except Exception:
            pass

        # 2. Clean up SQLite FTS index if applicable
        try:
            from django.db import connection
            if connection.vendor == 'sqlite':
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM knowledge_documentchunk_fts WHERE document_id = ?", [doc_id])
        except Exception:
            pass

        # 3. Invalidate cache
        try:
            from apps.retrieval.cache import TenantSafeCacheService
            TenantSafeCacheService.invalidate_workspace(ws_id)
        except Exception:
            pass

        return super().delete(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.workspace.name})"

class DocumentVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name='versions')
    version_number = models.PositiveIntegerField(default=1)
    file_hash = models.CharField(max_length=64)
    file_obj = models.FileField(upload_to='document_versions/%Y/%m/')
    change_summary = models.TextField(blank=True, default='')
    is_current = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('document', 'version_number')
        ordering = ['-version_number']

class DocumentPage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name='pages')
    document_version = models.ForeignKey(DocumentVersion, on_delete=models.CASCADE, null=True, blank=True, related_name='pages')
    page_number = models.PositiveIntegerField()
    text = models.TextField(blank=True, default='')
    confidence = models.FloatField(default=1.0)
    words_count = models.PositiveIntegerField(default=0)
    width = models.FloatField(default=0.0)
    height = models.FloatField(default=0.0)
    extraction_type = models.CharField(max_length=50, default='digital')
    engine = models.CharField(max_length=50, default='native')
    engine_version = models.CharField(max_length=50, blank=True, default='')
    is_repaired = models.BooleanField(default=False)
    bounding_boxes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['page_number']
        unique_together = ('document', 'page_number')

    def __str__(self):
        return f"{self.document.title} - Page {self.page_number} ({self.confidence:.2f})"


class ZipImportJob(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('previewed', 'Previewed'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('partial_success', 'Partial Success'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='zip_import_jobs')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='zip_import_jobs')
    collection = models.ForeignKey(Collection, on_delete=models.SET_NULL, null=True, blank=True, related_name='zip_import_jobs')
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='zip_import_jobs')

    archive_filename = models.CharField(max_length=255)
    archive_size = models.PositiveBigIntegerField(default=0)
    archive_hash = models.CharField(max_length=64, db_index=True)
    archive_file = models.FileField(upload_to='zip_archives/%Y/%m/', null=True, blank=True)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')
    is_slack_export = models.BooleanField(default=False)
    total_entries = models.PositiveIntegerField(default=0)
    supported_entries = models.PositiveIntegerField(default=0)
    unsupported_entries = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)

    authority_level = models.PositiveSmallIntegerField(choices=SourceDocument.AUTHORITY_LEVELS, default=3)
    description = models.TextField(blank=True, default='')
    error_message = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"ZipImportJob {self.id} ({self.archive_filename}) [{self.status}]"


class ZipImportEntry(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('imported', 'Imported'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    import_job = models.ForeignKey(ZipImportJob, on_delete=models.CASCADE, related_name='entries')
    entry_path = models.CharField(max_length=500)
    sanitized_filename = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField(default=0)
    compressed_size = models.PositiveBigIntegerField(default=0)
    file_hash = models.CharField(max_length=64, blank=True, default='')
    mime_type = models.CharField(max_length=100, blank=True, default='')
    document_type = models.CharField(max_length=50, blank=True, default='')
    is_supported = models.BooleanField(default=False)
    is_nested_archive = models.BooleanField(default=False)
    is_private = models.BooleanField(default=False)
    skip_reason = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')

    document = models.ForeignKey(SourceDocument, null=True, blank=True, on_delete=models.SET_NULL, related_name='zip_entry')
    ingestion_job = models.ForeignKey('ingestion.IngestionJob', null=True, blank=True, on_delete=models.SET_NULL, related_name='zip_entry')
    error_message = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['entry_path']

    def __str__(self):
        return f"{self.sanitized_filename} ({self.status})"


class EmailAccountConnection(models.Model):
    """
    Represents an authorized external email connection (e.g. Gmail) in a workspace.
    Tokens are strictly encrypted at rest via TokenEncryptionService.
    Tokens and secrets are never exposed in serialized responses or string representations.
    """
    PROVIDER_CHOICES = [
        ('gmail', 'Google Workspace / Gmail'),
        ('outlook', 'Microsoft Outlook / 365'),
    ]

    STATUS_CHOICES = [
        ('connected', 'Connected'),
        ('syncing', 'Syncing'),
        ('error', 'Sync Error'),
        ('disconnected', 'Disconnected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='email_connections')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='email_connections')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_connections')

    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES, default='gmail')
    email_address = models.CharField(max_length=255)
    account_name = models.CharField(max_length=255, blank=True, default='')

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='connected')
    encrypted_access_token = models.TextField(blank=True, default='')
    encrypted_refresh_token = models.TextField(blank=True, default='')
    token_expires_at = models.DateTimeField(null=True, blank=True)
    scopes = models.JSONField(default=list, blank=True)

    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=50, default='idle')
    last_error = models.TextField(blank=True, default='')
    sync_checkpoint = models.JSONField(default=dict, blank=True)
    total_messages_synced = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('workspace', 'user', 'email_address')

    def __str__(self):
        return f"{self.provider.upper()} ({self.email_address}) [{self.status}]"

    def __repr__(self):
        return f"<EmailAccountConnection id={self.id} email={self.email_address} provider={self.provider} status={self.status}>"

    def set_tokens(self, access_token: str, refresh_token: str = ""):
        from .token_encryption import TokenEncryptionService
        if access_token:
            self.encrypted_access_token = TokenEncryptionService.encrypt(access_token)
        if refresh_token:
            self.encrypted_refresh_token = TokenEncryptionService.encrypt(refresh_token)

    def get_access_token(self) -> str:
        from .token_encryption import TokenEncryptionService
        return TokenEncryptionService.decrypt(self.encrypted_access_token)

    def get_refresh_token(self) -> str:
        from .token_encryption import TokenEncryptionService
        return TokenEncryptionService.decrypt(self.encrypted_refresh_token)


class EmailSyncJob(models.Model):
    """
    Tracks atomic background or synchronous email sync batches for observability and auditability.
    """
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('partial_success', 'Partial Success'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(EmailAccountConnection, on_delete=models.CASCADE, related_name='sync_jobs')
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='email_sync_jobs')

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='queued')
    messages_detected = models.PositiveIntegerField(default=0)
    messages_imported = models.PositiveIntegerField(default=0)
    attachments_imported = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"EmailSyncJob {self.id} ({self.connection.email_address}) [{self.status}]"


