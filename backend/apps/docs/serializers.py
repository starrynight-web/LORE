from rest_framework import serializers
from .models import DocsPublishingConfig, DocsContentRevision

class DocsPublishingConfigSerializer(serializers.ModelSerializer):
    is_currently_open = serializers.SerializerMethodField()

    class Meta:
        model = DocsPublishingConfig
        fields = [
            'id',
            'is_public_accessible',
            'enforce_schedule',
            'schedule_start',
            'schedule_end',
            'admin_override',
            'closed_message',
            'allow_judge_passkey',
            'judge_passkey',
            'is_currently_open',
            'updated_at'
        ]

    def get_is_currently_open(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        passkey = request.headers.get('X-Judge-Passkey') if request else None
        return obj.is_currently_open(user=user, passkey=passkey)


class DocsContentRevisionSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = DocsContentRevision
        fields = [
            'id',
            'section_key',
            'title',
            'content_json',
            'version',
            'is_published',
            'author',
            'author_username',
            'created_at',
            'updated_at'
        ]
