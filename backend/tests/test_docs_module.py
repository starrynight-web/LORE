import json
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from apps.docs.models import DocsPublishingConfig, DocsContentRevision
from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument, DocumentPage
from apps.knowledge.models import DocumentChunk


class DocsModuleIntegrationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="Northstar Corp", slug="northstar-corp")
        self.workspace = Workspace.objects.create(
            organization=self.org,
            name="Default Workspace",
            slug="default-workspace"
        )
        self.admin_user = User.objects.create_superuser(
            username='docs_admin',
            email='admin@lore.internal',
            password='Password123!'
        )
        # Create test document and chunk to verify live telemetry
        self.doc = SourceDocument.objects.create(
            organization=self.org,
            workspace=self.workspace,
            title="LORE Governance Whitepaper",
            file_size=1024,
            page_count=10,
            status="ready"
        )
        DocumentPage.objects.create(
            document=self.doc,
            page_number=1,
            text="Deterministic governance and zero-knowledge policy attestation.",
            confidence=0.98
        )
        DocumentChunk.objects.create(
            organization=self.org,
            workspace=self.workspace,
            document=self.doc,
            text="Deterministic governance and zero-knowledge policy attestation.",
            chunk_index=0
        )

    def test_default_access_control_locked_when_outside_schedule(self):
        """Verify that outside June 10 - June 14, unauthenticated visitors receive the restricted view."""
        config = DocsPublishingConfig.get_active_config()
        config.is_public_accessible = True
        config.enforce_schedule = True
        config.admin_override = False
        config.schedule_start = datetime(2026, 6, 10, 0, 0, 0, tzinfo=dt_timezone.utc)
        config.schedule_end = datetime(2026, 6, 14, 23, 59, 59, tzinfo=dt_timezone.utc)
        config.save()

        res = self.client.get('/api/v1/docs/')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data['is_open'])
        self.assertEqual(res.data['status'], 'restricted')
        self.assertEqual(res.data['reason'], 'SCHEDULE_LOCKED')
        self.assertIn('June 10', res.data['message'])

    def test_passkey_unlocks_preview_during_lockdown(self):
        """Verify that judges/evaluators with the passkey can bypass the restricted window."""
        res = self.client.get('/api/v1/docs/?passkey=LORE2026')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['is_open'])
        self.assertEqual(res.data['status'], 'active')
        self.assertIn('pitch_deck', res.data)
        self.assertIn('team', res.data)
        self.assertIn('whitepaper', res.data)
        self.assertIn('live_telemetry', res.data)

    def test_admin_override_enables_instant_public_access(self):
        """Verify that admin_override = True immediately opens /docs to all visitors."""
        config = DocsPublishingConfig.get_active_config()
        config.admin_override = True
        config.save()

        res = self.client.get('/api/v1/docs/')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['is_open'])
        self.assertEqual(res.data['status'], 'active')

    def test_admin_can_update_settings_and_schedule(self):
        """Verify admin endpoint modifies schedule dates and passkeys."""
        payload = {
            "is_public_accessible": True,
            "enforce_schedule": True,
            "admin_override": False,
            "schedule_start": "2026-06-11T08:00:00Z",
            "schedule_end": "2026-06-15T18:00:00Z",
            "judge_passkey": "INVENT2026",
            "closed_message": "Custom Showcase Notice"
        }
        res = self.client.post(
            '/api/v1/docs/settings/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_ADMIN_KEY='lore_admin_secret_2026'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'success')
        self.assertEqual(res.data['config']['judge_passkey'], 'INVENT2026')

        # Confirm new passkey works
        test_res = self.client.get('/api/v1/docs/?passkey=INVENT2026')
        self.assertTrue(test_res.data['is_open'])

    def test_admin_can_update_team_content(self):
        """Verify admin can update team member cards and publish new revisions."""
        team_payload = {
            "section_key": "team",
            "title": "Team & Contributors",
            "content_json": {
                "team_name": "LORE Next-Gen AI Team",
                "charter": "Decentralized verification systems.",
                "members": [
                    {
                        "id": "member-test-1",
                        "full_name": "Dr. Test Engineer",
                        "role": "Chief Scientist",
                        "email": "scientist@lore.internal",
                        "avatar_url": "https://api.dicebear.com/7.x/bottts/svg?seed=Scientist",
                        "bio": "Expert in cryptographic attestation."
                    }
                ]
            }
        }
        res = self.client.post(
            '/api/v1/docs/content/',
            data=json.dumps(team_payload),
            content_type='application/json',
            HTTP_X_ADMIN_KEY='lore_admin_secret_2026'
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'success')

        # Verify manifest now serves the updated team
        doc_res = self.client.get('/api/v1/docs/?passkey=LORE2026')
        self.assertEqual(doc_res.data['team']['team_name'], "LORE Next-Gen AI Team")
        self.assertEqual(len(doc_res.data['team']['members']), 1)

    def test_export_markdown_and_json(self):
        """Verify export endpoints generate valid Markdown and JSON downloads."""
        # 1. Test Markdown export
        md_res = self.client.get('/api/v1/docs/export/?format=markdown')
        self.assertEqual(md_res.status_code, 200)
        self.assertIn('text/markdown', md_res['Content-Type'])
        self.assertIn('LORE: The Cryptographic Truth Engine', md_res.content.decode('utf-8'))
        self.assertIn('Y Combinator–Style Pitch Deck', md_res.content.decode('utf-8'))

        # 2. Test JSON export
        json_res = self.client.get('/api/v1/docs/export/?format=json')
        self.assertEqual(json_res.status_code, 200)
        self.assertIn('application/json', json_res['Content-Type'])
        data = json.loads(json_res.content.decode('utf-8'))
        self.assertIn('pitch_deck', data)
        self.assertIn('team', data)
        self.assertIn('whitepaper', data)
        self.assertIn('live_telemetry', data)

    def test_live_telemetry_reflects_actual_db_counts(self):
        """Verify live telemetry reflects real database records."""
        res = self.client.get('/api/v1/docs/telemetry/')
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(res.data['database']['total_documents'], 1)
        self.assertGreaterEqual(res.data['database']['total_chunks'], 1)
        self.assertEqual(res.data['mcp_manifest']['total_tools'], 41)
