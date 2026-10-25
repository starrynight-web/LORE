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
    
    current_version_number = models.PositiveIntegerField(default=1)
    ocr_confidence = models.FloatField(default=0.0)
    page_count = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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

