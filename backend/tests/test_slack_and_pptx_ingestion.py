import io
import os
import json
import zipfile
import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership, Collection
from apps.sources.models import SourceDocument, ZipImportJob, ZipImportEntry, DocumentPage
from apps.sources.zip_security import ZipArchiveSecurityService
from apps.sources.zip_engine import ZipImportEngine
from apps.sources.slack_engine import SlackExportService
from apps.ingestion.pipeline.extractors import PresentationExtractor, UnifiedDocumentExtractor
from apps.governance.models import SourcePermission, AccessLevel
from apps.governance.layers import PermissionLayer, GovernanceReasonCode


@pytest.fixture
def test_setup(db):
    user = User.objects.create_user(username='slack_admin_user', email='admin@lore.demo', password='AdminPassword123!')
    member_user = User.objects.create_user(username='regular_member_user', email='member@lore.demo', password='MemberPassword123!')
    external_user = User.objects.create_user(username='external_ws_user', email='external@lore.demo', password='ExternalPassword123!')

    org = Organization.objects.create(name='LORE Technologies', slug='lore-tech')
    OrganizationMembership.objects.create(user=user, organization=org, role='admin')
    OrganizationMembership.objects.create(user=member_user, organization=org, role='member')
    OrganizationMembership.objects.create(user=external_user, organization=org, role='member')

    workspace = Workspace.objects.create(organization=org, name='Core Platform Workspace', slug='core-ws')
    WorkspaceMembership.objects.create(user=user, workspace=workspace, role='workspace_admin')
    WorkspaceMembership.objects.create(user=member_user, workspace=workspace, role='member')

    isolated_workspace = Workspace.objects.create(organization=org, name='Isolated Workspace', slug='isolated-ws')
    WorkspaceMembership.objects.create(user=external_user, workspace=isolated_workspace, role='workspace_admin')

    client = APIClient()
    client.force_authenticate(user=user)

    member_client = APIClient()
    member_client.force_authenticate(user=member_user)

    external_client = APIClient()
    external_client.force_authenticate(user=external_user)

    return {
        'user': user,
        'member_user': member_user,
        'external_user': external_user,
        'org': org,
        'workspace': workspace,
        'isolated_workspace': isolated_workspace,
        'client': client,
        'member_client': member_client,
        'external_client': external_client,
    }


def create_slack_export_zip(include_malformed: bool = False) -> io.BytesIO:
    """Creates a realistic Slack export ZIP archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. users.json
        users = [
            {
                "id": "U01",
                "name": "alice",
                "real_name": "Alice Smith",
                "profile": {"display_name": "alice.smith", "email": "alice@company.com"}
            },
            {
                "id": "U02",
                "name": "bob",
                "real_name": "Bob Jones",
                "profile": {"display_name": "bobjones", "email": "bob@company.com"}
            },
            {
                "id": "U03",
                "name": "charlie",
                "real_name": "Charlie Brown",
                "profile": {"display_name": "charlie", "email": "charlie@company.com"}
            }
        ]
        zf.writestr("users.json", json.dumps(users))

        # 2. channels.json (public)
        channels = [
            {
                "id": "C01",
                "name": "general",
                "is_private": False,
                "is_general": True,
                "topic": {"value": "Company-wide announcements"},
                "purpose": {"value": "General workspace discussions"},
                "members": ["U01", "U02", "U03"]
            },
            {
                "id": "C02",
                "name": "dev-general",
                "is_private": False,
                "topic": {"value": "Engineering chat"},
                "purpose": {"value": "Dev coordination"},
                "members": ["U01", "U02"]
            }
        ]
        zf.writestr("channels.json", json.dumps(channels))

        # 3. groups.json (private)
        groups = [
            {
                "id": "G01",
                "name": "exec-confidential",
                "is_private": True,
                "is_group": True,
                "topic": {"value": "Executive strategy discussions"},
                "purpose": {"value": "Restricted governance decisions"},
                "members": ["U01"]
            }
        ]
        zf.writestr("groups.json", json.dumps(groups))

        # 4. Messages in general channel (threads, replies, mentions, attachments, links)
        general_day1 = [
            {
                "type": "message",
                "user": "U01",
                "text": "Welcome to the new quarter! Please review <https://lore.ai|LORE System>. Ping <@U02> if issues arise.",
                "ts": "1698240000.000100",
                "attachments": [
                    {
                        "title": "Quarterly Objectives Document",
                        "title_link": "https://company.internal/okrs.pdf",
                        "text": "Review section 4 on Settlement Gate compliance."
                    }
                ],
                "files": [
                    {
                        "name": "architecture_diagram.png",
                        "url_private": "https://files.slack.com/diagram.png"
                    }
                ]
            },
            {
                "type": "message",
                "user": "U02",
                "text": "I will review the settlement gates now.",
                "ts": "1698240060.000200",
                "thread_ts": "1698240000.000100"  # Reply to Alice
            },
            {
                "type": "message",
                "user": "U03",
                "text": "All services deployed successfully.",
                "ts": "1698240120.000300",
                "thread_ts": "1698240000.000100"  # Second reply
            },
            {
                "type": "message",
                "user": "U02",
                "text": "Standalone note: remember to update database indexes.",
                "ts": "1698240200.000400"
            }
        ]
        zf.writestr("general/2026-10-20.json", json.dumps(general_day1))

        # 5. Messages in exec-confidential (private channel)
        exec_day1 = [
            {
                "type": "message",
                "user": "U01",
                "text": "CONFIDENTIAL: Merger and acquisition discussions with Titan Corp.",
                "ts": "1698250000.000100"
            }
        ]
        zf.writestr("exec-confidential/2026-10-20.json", json.dumps(exec_day1))

        # 6. Malformed JSON test file (simulates corrupted export date record)
        if include_malformed:
            zf.writestr("dev-general/2026-10-21.json", "{CORRUPTED_JSON_ENTRY: NOT VALID,")
            # And valid day 2 in dev-general
            dev_day2 = [
                {
                    "type": "message",
                    "user": "U02",
                    "text": "Dev general message on day 2.",
                    "ts": "1698260000.000100"
                }
            ]
            zf.writestr("dev-general/2026-10-22.json", json.dumps(dev_day2))

    buf.seek(0)
    return buf


def create_realistic_pptx(include_table: bool = True, include_notes: bool = True, corrupted_slide: bool = False) -> io.BytesIO:
    """Generates a valid OpenXML PowerPoint (.pptx) file package in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # [Content_Types].xml
        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/notesSlides/notesSlide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""
        zf.writestr("[Content_Types].xml", content_types)

        # _rels/.rels
        root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""
        zf.writestr("_rels/.rels", root_rels)

        # docProps/core.xml
        core_props = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title>Enterprise Architecture Roadmap</dc:title>
  <dc:creator>Chief Technology Officer</dc:creator>
</cp:coreProperties>"""
        zf.writestr("docProps/core.xml", core_props)

        # ppt/presentation.xml
        presentation_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldIdLst>
    <p:sldId id="256" r:id="rId1"/>
    <p:sldId id="257" r:id="rId2"/>
  </p:sldIdLst>
</p:presentation>"""
        zf.writestr("ppt/presentation.xml", presentation_xml)

        # ppt/_rels/presentation.xml.rels
        pres_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/>
</Relationships>"""
        zf.writestr("ppt/_rels/presentation.xml.rels", pres_rels)

        # ppt/slides/slide1.xml
        slide1_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="1" name="Title 1"/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>
        <p:txBody>
          <a:p><a:r><a:t>Platform Strategic Initiatives</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="Content 1"/><p:nvPr/></p:nvSpPr>
        <p:txBody>
          <a:p><a:pPr lvl="0"/><a:r><a:t>High-Level Governance Goals</a:t></a:r></a:p>
          <a:p><a:pPr lvl="1"/><a:r><a:t>Automated 6-Stage Settlement Gate</a:t></a:r></a:p>
          <a:p><a:pPr lvl="1"/><a:r><a:t>Slack Channel Provenance Verification</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>"""
        zf.writestr("ppt/slides/slide1.xml", slide1_xml)

        # ppt/slides/_rels/slide1.xml.rels
        slide1_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdNotes1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide1.xml"/>
</Relationships>"""
        zf.writestr("ppt/slides/_rels/slide1.xml.rels", slide1_rels)

        # ppt/notesSlides/notesSlide1.xml
        if include_notes:
            notes_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:txBody>
          <a:p><a:r><a:t>Speaker Note: Emphasize that Slack chat is untrusted informal communication (Authority Rank 1).</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:notes>"""
            zf.writestr("ppt/notesSlides/notesSlide1.xml", notes_xml)

        # ppt/slides/slide2.xml (with Table)
        if corrupted_slide:
            zf.writestr("ppt/slides/slide2.xml", "<<<BROKEN_XML_NOT_WELL_FORMED>>>")
        elif include_table:
            slide2_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="3" name="Title 2"/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>
        <p:txBody>
          <a:p><a:r><a:t>Q3 Budget Allocation</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
      <p:graphicFrame>
        <a:graphic>
          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">
            <a:tbl>
              <a:tr>
                <a:tc><a:txBody><a:p><a:r><a:t>Department</a:t></a:r></a:p></a:txBody></a:tc>
                <a:tc><a:txBody><a:p><a:r><a:t>Allocated</a:t></a:r></a:p></a:txBody></a:tc>
                <a:tc><a:txBody><a:p><a:r><a:t>Spent</a:t></a:r></a:p></a:txBody></a:tc>
              </a:tr>
              <a:tr>
                <a:tc><a:txBody><a:p><a:r><a:t>Engineering</a:t></a:r></a:p></a:txBody></a:tc>
                <a:tc><a:txBody><a:p><a:r><a:t>$5.0M</a:t></a:r></a:p></a:txBody></a:tc>
                <a:tc><a:txBody><a:p><a:r><a:t>$4.8M</a:t></a:r></a:p></a:txBody></a:tc>
              </a:tr>
              <a:tr>
                <a:tc><a:txBody><a:p><a:r><a:t>Product</a:t></a:r></a:p></a:txBody></a:tc>
                <a:tc><a:txBody><a:p><a:r><a:t>$2.5M</a:t></a:r></a:p></a:txBody></a:tc>
                <a:tc><a:txBody><a:p><a:r><a:t>$2.1M</a:t></a:r></a:p></a:txBody></a:tc>
              </a:tr>
            </a:tbl>
          </a:graphicData>
        </a:graphic>
      </p:graphicFrame>
    </p:spTree>
  </p:cSld>
</p:sld>"""
            zf.writestr("ppt/slides/slide2.xml", slide2_xml)
        else:
            slide2_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree></p:spTree></p:cSld>
</p:sld>"""
            zf.writestr("ppt/slides/slide2.xml", slide2_xml)

    buf.seek(0)
    return buf


@pytest.mark.django_db
class TestSlackExportIngestion:
    """Part A & B Tests: Slack export ZIP, JSON processing, Privacy and Permissions."""

    def test_slack_archive_detection(self):
        """Verifies signature detection of Slack export ZIP archives."""
        buf = create_slack_export_zip()
        with zipfile.ZipFile(buf, 'r') as zf:
            assert SlackExportService.is_slack_archive(zf) is True

        # Non-slack archive
        dummy_buf = io.BytesIO()
        with zipfile.ZipFile(dummy_buf, 'w') as zf:
            zf.writestr("document.txt", "Plain text file")
        dummy_buf.seek(0)
        with zipfile.ZipFile(dummy_buf, 'r') as zf:
            assert SlackExportService.is_slack_archive(zf) is False

    def test_slack_metadata_and_attribution_extraction(self):
        """Verifies channel, users, author attribution, and message preservation."""
        buf = create_slack_export_zip()
        with zipfile.ZipFile(buf, 'r') as zf:
            slack_data = SlackExportService.inspect_slack_archive(zf)
            assert 'U01' in slack_data['users_map']
            assert slack_data['users_map']['U01']['real_name'] == 'Alice Smith'
            assert slack_data['users_map']['U02']['real_name'] == 'Bob Jones'

            # Channels check
            ch_names = [c['channel_name'] for c in slack_data['channels']]
            assert 'general' in ch_names
            assert 'exec-confidential' in ch_names

            # Normalization of general channel
            gen_ch = next(c for c in slack_data['channels'] if c['channel_name'] == 'general')
            full_text, pages, stats = SlackExportService.normalize_channel(zf, gen_ch, slack_data['users_map'])

            # Author attribution
            assert "Alice Smith" in full_text
            assert "@Bob Jones" in full_text  # mention replacement
            # Timestamps
            assert "2023-10-25" in full_text or "UTC" in full_text
            # Threads and replies hierarchy
            assert "Thread Replies (2):" in full_text
            assert "↳ **Bob Jones**" in full_text
            assert "↳ **Charlie Brown**" in full_text
            # Attachments & Links
            assert "[Quarterly Objectives Document](https://company.internal/okrs.pdf)" in full_text
            assert "[LORE System](https://lore.ai)" in full_text
            assert "[architecture_diagram.png](https://files.slack.com/diagram.png)" in full_text
            # Untrusted notice
            assert "Authority Rank 1 (informal_note)" in full_text

    def test_slack_zip_preview_and_import_pipeline(self, test_setup):
        """Tests full end-to-end Slack ZIP preview, channel separation, and execution."""
        buf = create_slack_export_zip()
        file_obj = SimpleUploadedFile(name='slack_export_2026.zip', content=buf.getvalue(), content_type='application/zip')

        # 1. Preview archive
        job = ZipImportEngine.preview_archive(
            file_obj=file_obj,
            workspace=test_setup['workspace'],
            user=test_setup['user']
        )

        assert job.is_slack_export is True
        assert job.authority_level == 1
        assert job.total_entries == 2  # general and exec-confidential
        assert job.entries.filter(is_private=True).count() == 1  # exec-confidential is private
        assert job.entries.filter(is_private=False).count() == 1  # general is public

        # 2. Execute import
        job = ZipImportEngine.execute_import(job, test_setup['user'])
        assert job.status == 'completed'
        assert job.entries.filter(status='imported').count() == 2

        # Verify created documents
        gen_doc = SourceDocument.objects.get(workspace=test_setup['workspace'], title='Slack #general')
        assert gen_doc.authority_level == 1  # strictly informal_note
        assert gen_doc.pages.count() >= 1

        exec_doc = SourceDocument.objects.get(workspace=test_setup['workspace'], title='Slack #exec-confidential')
        assert exec_doc.authority_level == 1
        assert "CONFIDENTIAL" in exec_doc.pages.first().text

    def test_slack_privacy_and_permission_isolation(self, test_setup):
        """
        Part B: Verifies that private channels/DMs are isolated via L7 Permission Layer:
        - Regular member cannot retrieve or view chunks from private channels.
        - Admin or uploader can view chunks.
        - Public channel chunks are visible to workspace members.
        """
        buf = create_slack_export_zip()
        file_obj = SimpleUploadedFile(name='slack_export.zip', content=buf.getvalue(), content_type='application/zip')

        job = ZipImportEngine.preview_archive(file_obj, test_setup['workspace'], test_setup['user'])
        ZipImportEngine.execute_import(job, test_setup['user'])

        gen_doc = SourceDocument.objects.get(workspace=test_setup['workspace'], title='Slack #general')
        exec_doc = SourceDocument.objects.get(workspace=test_setup['workspace'], title='Slack #exec-confidential')

        # Check SourcePermission records
        gen_perm = SourcePermission.objects.get(document=gen_doc)
        exec_perm = SourcePermission.objects.get(document=exec_doc)

        assert gen_perm.access_level == AccessLevel.INTERNAL
        assert exec_perm.access_level == AccessLevel.RESTRICTED
        assert test_setup['user'].username in exec_perm.allowed_users

        # Test L7 Permission Filter for regular member
        candidate_chunks = [
            {'document_id': str(gen_doc.id), 'document_title': gen_doc.title, 'text': 'General message chunk'},
            {'document_id': str(exec_doc.id), 'document_title': exec_doc.title, 'text': 'Confidential M&A chunk'}
        ]

        # Regular member query
        res_member = PermissionLayer.filter_authorized_chunks(
            chunks=candidate_chunks,
            user=test_setup['member_user'],
            user_role='member'
        )
        allowed_titles_member = [c['document_title'] for c in res_member.cleared_chunks]
        assert 'Slack #general' in allowed_titles_member
        assert 'Slack #exec-confidential' not in allowed_titles_member
        assert len(res_member.denial_reasons) == 1
        assert "Access restricted to document 'Slack #exec-confidential' (RESTRICTED)" in res_member.denial_reasons[0]
        assert GovernanceReasonCode.L7_UNAUTHORIZED_ROLE.value in res_member.reason_codes

        # Admin query
        res_admin = PermissionLayer.filter_authorized_chunks(
            chunks=candidate_chunks,
            user=test_setup['user'],
            user_role='workspace_admin'
        )
        allowed_titles_admin = [c['document_title'] for c in res_admin.cleared_chunks]
        assert 'Slack #general' in allowed_titles_admin
        assert 'Slack #exec-confidential' in allowed_titles_admin

    def test_slack_malformed_json_partial_success(self, test_setup):
        """Verifies partial success when individual JSON files in export are malformed."""
        buf = create_slack_export_zip(include_malformed=True)
        file_obj = SimpleUploadedFile(name='slack_malformed.zip', content=buf.getvalue(), content_type='application/zip')

        job = ZipImportEngine.preview_archive(file_obj, test_setup['workspace'], test_setup['user'])
        job = ZipImportEngine.execute_import(job, test_setup['user'])

        # Dev general should still succeed with the valid day 2 message
        assert job.status in ('completed', 'partial_success')
        dev_doc = SourceDocument.objects.get(workspace=test_setup['workspace'], title='Slack #dev-general')
        assert "Dev general message on day 2" in dev_doc.pages.first().text

    def test_slack_duplicate_detection_and_safe_reimport(self, test_setup):
        """Verifies that re-importing the same Slack channel prevents duplicate documents."""
        buf = create_slack_export_zip()
        file_obj1 = SimpleUploadedFile(name='export1.zip', content=buf.getvalue(), content_type='application/zip')
        job1 = ZipImportEngine.preview_archive(file_obj1, test_setup['workspace'], test_setup['user'])
        ZipImportEngine.execute_import(job1, test_setup['user'])

        initial_count = SourceDocument.objects.filter(workspace=test_setup['workspace']).count()

        # Re-import identical archive
        file_obj2 = SimpleUploadedFile(name='export2.zip', content=buf.getvalue(), content_type='application/zip')
        job2 = ZipImportEngine.preview_archive(file_obj2, test_setup['workspace'], test_setup['user'])
        ZipImportEngine.execute_import(job2, test_setup['user'])

        final_count = SourceDocument.objects.filter(workspace=test_setup['workspace']).count()
        assert final_count == initial_count  # No duplicate documents created!

    def test_direct_slack_json_upload(self, test_setup):
        """Verifies direct upload of a single Slack conversation JSON file."""
        messages = [
            {"type": "message", "user": "U10", "text": "Direct uploaded chat line 1", "ts": "1698300000.000100"},
            {"type": "message", "user": "U11", "text": "Direct uploaded chat line 2", "ts": "1698300060.000200"}
        ]
        json_bytes = json.dumps(messages).encode('utf-8')
        file_obj = SimpleUploadedFile(name='team_standup.json', content=json_bytes, content_type='application/json')

        response = test_setup['client'].post(
            '/api/v1/sources/documents/',
            {
                'file': file_obj,
                'workspace': str(test_setup['workspace'].id),
                'title': 'Standup Discussion'
            },
            format='multipart'
        )

        assert response.status_code == 201
        doc_data = response.data['document']
        doc = SourceDocument.objects.get(id=doc_data['id'])
        assert doc.authority_level == 1
        assert "Direct uploaded chat line 1" in doc.pages.first().text


@pytest.mark.django_db
class TestPresentationExtractionAndIngestion:
    """Part C & D Tests: PPTX slide extraction, ordering, tables, speaker notes, and API upload."""

    def test_pptx_slide_extraction_and_ordering(self):
        """Verifies slide ordering, 1-indexed numbers (page_number), titles, and bullet hierarchies."""
        buf = create_realistic_pptx(include_table=True, include_notes=True)
        extractor = PresentationExtractor()
        pages = extractor.extract(buf)

        assert len(pages) == 2
        # Slide 1 verification
        s1 = pages[0]
        assert s1['page_number'] == 1
        assert "# Slide 1: Platform Strategic Initiatives" in s1['text']
        assert "High-Level Governance Goals" in s1['text']
        assert "  - Automated 6-Stage Settlement Gate" in s1['text']
        assert "  - Slack Channel Provenance Verification" in s1['text']
        # Notes
        assert "Speaker Notes:" in s1['text']
        assert "Authority Rank 1" in s1['text']

        # Slide 2 verification (Table)
        s2 = pages[1]
        assert s2['page_number'] == 2
        assert "# Slide 2: Q3 Budget Allocation" in s2['text']
        assert "| Department | Allocated | Spent |" in s2['text']
        assert "| --- | --- | --- |" in s2['text']
        assert "| Engineering | $5.0M | $4.8M |" in s2['text']

    def test_pptx_corrupted_slide_handling(self):
        """Verifies that a corrupted slide XML does not crash the parser and isolates the error."""
        buf = create_realistic_pptx(corrupted_slide=True)
        pages = PresentationExtractor.extract(buf)
        assert len(pages) == 2
        assert pages[0]['page_number'] == 1
        assert pages[1]['page_number'] == 2
        assert "[Corrupted slide data]" in pages[1]['text']

    def test_empty_presentation_handling(self):
        """Verifies that an empty or slide-free presentation is safely handled."""
        dummy_buf = io.BytesIO()
        with zipfile.ZipFile(dummy_buf, 'w') as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
        dummy_buf.seek(0)
        pages = PresentationExtractor.extract(dummy_buf)
        assert len(pages) == 1
        assert "[Empty presentation or no slides found]" in pages[0]['text']

    def test_direct_pptx_upload_via_api(self, test_setup):
        """Tests direct HTTP upload of .pptx file via LORE documents API."""
        buf = create_realistic_pptx()
        upload_file = SimpleUploadedFile(
            name='architecture_roadmap.pptx',
            content=buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.presentationml.presentation'
        )

        response = test_setup['client'].post(
            '/api/v1/sources/documents/',
            {
                'file': upload_file,
                'workspace': str(test_setup['workspace'].id),
                'title': 'Q3 Roadmap Presentation'
            },
            format='multipart'
        )

        assert response.status_code == 201
        doc_id = response.data['document']['id']
        doc = SourceDocument.objects.get(id=doc_id)
        assert doc.document_type == 'presentation'
        assert doc.pages.count() == 2

        # Verify slide-level citation fidelity
        p1 = doc.pages.get(page_number=1)
        p2 = doc.pages.get(page_number=2)
        assert "Platform Strategic Initiatives" in p1.text
        assert "Q3 Budget Allocation" in p2.text

    def test_cross_workspace_authorization(self, test_setup):
        """Verifies multi-tenant isolation: User in Workspace B cannot access Workspace A documents."""
        buf = create_realistic_pptx()
        upload_file = SimpleUploadedFile(
            name='isolated_roadmap.pptx',
            content=buf.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.presentationml.presentation'
        )

        res_upload = test_setup['client'].post(
            '/api/v1/sources/documents/',
            {
                'file': upload_file,
                'workspace': str(test_setup['workspace'].id),
                'title': 'Confidential Architecture'
            },
            format='multipart'
        )
        doc_id = res_upload.data['document']['id']

        # External user in different workspace tries to retrieve
        res_get = test_setup['external_client'].get(f'/api/v1/sources/documents/{doc_id}/')
        assert res_get.status_code == 404
