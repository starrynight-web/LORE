from rest_framework import serializers
from .models import SourceDocument, DocumentVersion, DocumentPage

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
