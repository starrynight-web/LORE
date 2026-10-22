from rest_framework import serializers
from .models import IngestionJob

class IngestionJobSerializer(serializers.ModelSerializer):
    document_title = serializers.CharField(source='document.title', read_only=True)
    document_type = serializers.CharField(source='document.document_type', read_only=True)
    ocr_confidence = serializers.FloatField(source='document.ocr_confidence', read_only=True)

    class Meta:
        model = IngestionJob
        fields = [
            'id', 'document', 'document_title', 'document_type', 'ocr_confidence',
            'status', 'current_stage', 'stage_timings', 'error_message',
            'error_category', 'attempt_count', 'max_retries',
            'started_at', 'completed_at', 'created_at', 'updated_at'
        ]
