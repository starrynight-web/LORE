from rest_framework import serializers
from .models import IngestionJob, IngestionPipelineRun


class IngestionPipelineRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = IngestionPipelineRun
        fields = [
            'id', 'stage', 'status', 'attempt_count',
            'started_at', 'completed_at', 'diagnostics', 'error_message',
            'created_at', 'updated_at'
        ]


class IngestionJobSerializer(serializers.ModelSerializer):
    document_title = serializers.CharField(source='document.title', read_only=True)
    document_type = serializers.CharField(source='document.document_type', read_only=True)
    ocr_confidence = serializers.FloatField(source='document.ocr_confidence', read_only=True)
    pipeline_runs = IngestionPipelineRunSerializer(many=True, read_only=True)

    class Meta:
        model = IngestionJob
        fields = [
            'id', 'document', 'document_title', 'document_type', 'ocr_confidence',
            'status', 'current_stage', 'stage_timings', 'pipeline_summary', 'pipeline_runs',
            'error_message', 'error_category', 'attempt_count', 'max_retries',
            'started_at', 'completed_at', 'created_at', 'updated_at'
        ]
