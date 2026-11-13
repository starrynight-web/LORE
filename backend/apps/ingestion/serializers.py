from rest_framework import serializers
from .models import IngestionBatch, IngestionJob, IngestionPipelineRun


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
            'id', 'batch', 'document', 'document_title', 'document_type', 'ocr_confidence',
            'status', 'current_stage', 'workload_class', 'queue_name',
            'worker_id', 'heartbeat_at', 'idempotency_key',
            'is_cancellation_requested', 'cancelled_at',
            'stage_timings', 'pipeline_summary', 'pipeline_runs',
            'error_message', 'error_category', 'attempt_count', 'max_retries',
            'started_at', 'completed_at', 'created_at', 'updated_at'
        ]


class IngestionBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = IngestionBatch
        fields = [
            'id', 'organization', 'workspace', 'created_by',
            'status', 'total_files', 'visual_jobs_count', 'lightweight_jobs_count',
            'completed_count', 'failed_count', 'needs_review_count',
            'quarantined_count', 'cancelled_count', 'skipped_duplicate_count',
            'max_concurrent_visual', 'max_concurrent_lightweight',
            'metadata', 'created_at', 'updated_at', 'completed_at',
        ]
