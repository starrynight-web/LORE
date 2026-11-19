import uuid
from datetime import datetime, timezone as dt_timezone
from django.db import models
from django.utils import timezone
from apps.identity.models import User

class DocsPublishingConfig(models.Model):
    """
    Access Control and Scheduling Configuration for the /docs endpoint.
    Guarantees admin-enforced visibility windows (e.g. June 10 - June 14)
    and instant overrides for judges, investors, and team reviews.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    is_public_accessible = models.BooleanField(
        default=True,
        help_text="Master toggle: When False, /docs is locked to unauthenticated viewers."
    )
    enforce_schedule = models.BooleanField(
        default=True,
        help_text="When True, public access is gated strictly by schedule_start and schedule_end."
    )
    # Default scheduled window: June 10, 2026 00:00 UTC to June 14, 2026 23:59:59 UTC
    schedule_start = models.DateTimeField(
        default=datetime(2026, 6, 10, 0, 0, 0, tzinfo=dt_timezone.utc),
        help_text="Start of public showcase window."
    )
    schedule_end = models.DateTimeField(
        default=datetime(2026, 6, 14, 23, 59, 59, tzinfo=dt_timezone.utc),
        help_text="End of public showcase window."
    )
    admin_override = models.BooleanField(
        default=False,
        help_text="Admin emergency override: Bypasses schedule restriction and enables immediate access."
    )
    closed_message = models.TextField(
        default="LORE Enterprise Documentation & YC Pitch Deck is reserved for the official judging and investor showcase period (June 10 - June 14).",
        help_text="Notice displayed when public access window is closed."
    )
    allow_judge_passkey = models.BooleanField(
        default=True,
        help_text="Allows evaluators with a temporary passkey to preview locked documentation."
    )
    judge_passkey = models.CharField(
        max_length=64,
        default="LORE2026",
        help_text="Emergency passkey for judges/auditors during restricted preview periods."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Docs Publishing Configuration"
        verbose_name_plural = "Docs Publishing Configurations"

    @classmethod
    def get_active_config(cls):
        config = cls.objects.first()
        if not config:
            config = cls.objects.create()
        return config

    def is_currently_open(self, user=None, passkey=None) -> bool:
        """
        Calculates if the docs endpoint is currently accessible.
        Admins and staff always have access.
        """
        if user and (user.is_staff or user.is_superuser):
            return True
        if self.allow_judge_passkey and passkey and passkey.strip() == self.judge_passkey:
            return True
        if not self.is_public_accessible:
            return False
        if self.admin_override:
            return True
        if not self.enforce_schedule:
            return True
        now = timezone.now()
        return self.schedule_start <= now <= self.schedule_end


class DocsContentRevision(models.Model):
    """
    Structured section contents, versioning, and drafts for the /docs system.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section_key = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Section identifier (e.g. 'pitch_deck', 'whitepaper', 'team', 'roadmap', 'changelog')"
    )
    title = models.CharField(max_length=255)
    content_json = models.JSONField(default=dict)
    version = models.IntegerField(default=1)
    is_published = models.BooleanField(default=True)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-version', '-updated_at']
        unique_together = ('section_key', 'version')

    def __str__(self):
        return f"{self.section_key} (v{self.version}) - {'Published' if self.is_published else 'Draft'}"
