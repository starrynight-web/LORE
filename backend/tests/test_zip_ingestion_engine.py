import io
import os
import zipfile
import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership, Collection
from apps.sources.models import SourceDocument, ZipImportJob, ZipImportEntry
from apps.sources.zip_security import (
    ZipArchiveSecurityService,
    ZipSecurityError,
    ZIP_MAX_COMPRESSION_RATIO,
    ZIP_MAX_SINGLE_FILE_SIZE_BYTES
)
from apps.sources.zip_engine import ZipImportEngine


@pytest.fixture
def test_setup(db):
    user = User.objects.create_user(username='test_zip_user', email='zip_user@lore.demo', password='ZipPassword123!')
    other_user = User.objects.create_user(username='other_zip_user', email='other@lore.demo', password='OtherPassword123!')

    org = Organization.objects.create(name='Acme Corp', slug='acme-corp')
    OrganizationMembership.objects.create(user=user, organization=org, role='admin')
    OrganizationMembership.objects.create(user=other_user, organization=org, role='member')

    workspace = Workspace.objects.create(organization=org, name='Engineering Workspace', slug='eng-ws')
    WorkspaceMembership.objects.create(user=user, workspace=workspace, role='workspace_admin')

    other_workspace = Workspace.objects.create(organization=org, name='Restricted Workspace', slug='restricted-ws')
    WorkspaceMembership.objects.create(user=other_user, workspace=other_workspace, role='workspace_admin')

    client = APIClient()
    client.force_authenticate(user=user)

    other_client = APIClient()
    other_client.force_authenticate(user=other_user)

    return {
        'user': user,
        'other_user': other_user,
        'org': org,
        'workspace': workspace,
        'other_workspace': other_workspace,
        'client': client,
        'other_client': other_client,
    }


def create_in_memory_zip(file_dict: dict, comment: bytes = b'') -> io.BytesIO:
    """Helper to generate in-memory ZIP archives."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        if comment:
            zf.comment = comment
        for path, data in file_dict.items():
            if isinstance(data, str):
                data = data.encode('utf-8')
            zf.writestr(path, data)
    buf.seek(0)
    return buf


@pytest.mark.django_db
class TestZipArchiveSecurity:
    """Tests the security gate and sanitization functions."""

    def test_sanitize_entry_path_normal(self):
        rel, base = ZipArchiveSecurityService.sanitize_entry_path("docs/security/policy.pdf")
        assert rel == "docs/security/policy.pdf"
        assert base == "policy.pdf"

    def test_sanitize_entry_path_backslash(self):
        rel, base = ZipArchiveSecurityService.sanitize_entry_path("docs\\security\\policy.pdf")
        assert rel == "docs/security/policy.pdf"
        assert base == "policy.pdf"

    def test_zip_slip_traversal_detection(self):
        with pytest.raises(ZipSecurityError, match="Zip Slip"):
            ZipArchiveSecurityService.sanitize_entry_path("../../etc/passwd")

        with pytest.raises(ZipSecurityError, match="Zip Slip"):
            ZipArchiveSecurityService.sanitize_entry_path("folder/../../../secret.txt")

    def test_absolute_path_rejection(self):
        with pytest.raises(ZipSecurityError, match="Absolute paths not permitted"):
            ZipArchiveSecurityService.sanitize_entry_path("/etc/shadow")

    def test_windows_drive_letter_rejection(self):
        with pytest.raises(ZipSecurityError, match="Drive prefix not permitted"):
            ZipArchiveSecurityService.sanitize_entry_path("C:\\Windows\\System32\\calc.exe")

    def test_null_byte_rejection(self):
        with pytest.raises(ZipSecurityError, match="null byte"):
            ZipArchiveSecurityService.sanitize_entry_path("innocent.txt\0.exe")

    def test_corrupted_archive_rejected(self):
        corrupt_buf = io.BytesIO(b'PK\x03\x04corrupted-archive-garbage-bytes')
        with pytest.raises(ZipSecurityError, match="Corrupted or invalid"):
            ZipArchiveSecurityService.inspect_archive(corrupt_buf, 'corrupt.zip')

    def test_nested_archive_flagged(self):
        files = {
            'document.txt': 'Sample document content for LORE testing.',
            'nested.zip': create_in_memory_zip({'inner.txt': 'hidden'}).getvalue(),
            'backup.tar.gz': b'fake tar content'
        }
        buf = create_in_memory_zip(files)
        meta = ZipArchiveSecurityService.inspect_archive(buf, 'bundle.zip')

        nested_entries = [e for e in meta['entries'] if e['is_nested_archive']]
        assert len(nested_entries) == 2
        for ne in nested_entries:
            assert ne['is_supported'] is False
            assert "Nested archive detected" in ne['skip_reason']

    def test_unsupported_extensions_detected(self):
        files = {
            'malicious.exe': b'MZ\x90\x00executable',
            'script.sh': b'#!/bin/bash\nrm -rf /',
            'readme.txt': 'Valid text document'
        }
        buf = create_in_memory_zip(files)
        meta = ZipArchiveSecurityService.inspect_archive(buf, 'mixed.zip')

        supported = [e for e in meta['entries'] if e['is_supported']]
        unsupported = [e for e in meta['entries'] if not e['is_supported']]

        assert len(supported) == 1
        assert supported[0]['sanitized_filename'] == 'readme.txt'
        assert len(unsupported) == 2
        assert any(e['sanitized_filename'] == 'malicious.exe' for e in unsupported)
        assert any(e['sanitized_filename'] == 'script.sh' for e in unsupported)


@pytest.mark.django_db
class TestZipIngestionEngineWorkflow:
    """Tests the full preview, start, cancel, retry, and summary workflow."""

    def test_preview_and_import_valid_archive(self, test_setup):
        ws = test_setup['workspace']
        user = test_setup['user']
        client = test_setup['client']

        files = {
            'policy.txt': 'All engineers must use multi-factor authentication for SSH and AWS access.',
            'guide.md': '# Deployment Runbook\nAlways check stage health before deployment.',
            'unsupported.bin': b'\x00\x01\x02\x03binary-blob'
        }
        zip_buf = create_in_memory_zip(files)
        upload = SimpleUploadedFile('company_docs.zip', zip_buf.getvalue(), content_type='application/zip')

        # 1. Preview
        res = client.post('/api/v1/sources/zip-imports/preview/', {
            'file': upload,
            'workspace': str(ws.id),
            'authority_level': 5,
            'description': 'Core engineering standards'
        }, format='multipart')

        assert res.status_code == 201
        data = res.json()
        job_id = data['id']
        assert data['status'] == 'previewed'
        assert data['total_entries'] == 3
        assert data['supported_entries'] == 2
        assert data['unsupported_entries'] == 1
        assert len(data['entries']) == 3

        # 2. Start Import
        start_res = client.post(f'/api/v1/sources/zip-imports/{job_id}/start/')
        assert start_res.status_code == 200
        start_data = start_res.json()
        assert start_data['status'] in ('completed', 'partial_success')
        assert start_data['success_count'] == 2
        assert start_data['failed_count'] == 0

        # Verify documents were created in LORE
        docs = SourceDocument.objects.filter(workspace=ws)
        assert docs.count() >= 2
        doc_filenames = [d.original_filename for d in docs]
        assert 'policy.txt' in doc_filenames
        assert 'guide.md' in doc_filenames

        # 3. Retrieve Summary
        sum_res = client.get(f'/api/v1/sources/zip-imports/{job_id}/summary/')
        assert sum_res.status_code == 200
        sum_data = sum_res.json()
        assert sum_data['success_count'] == 2
        assert len(sum_data['entries']) == 3

        # CSV Summary
        csv_res = client.get(f'/api/v1/sources/zip-imports/{job_id}/summary/?export=csv')
        assert csv_res.status_code == 200
        assert b'policy.txt' in csv_res.content
        assert b'guide.md' in csv_res.content

    def test_direct_zip_upload_to_documents_endpoint(self, test_setup):
        """Tests that uploading a .zip directly to /sources/documents/ auto-extracts without breaking contract."""
        ws = test_setup['workspace']
        client = test_setup['client']

        files = {
            'remote_work.txt': 'Remote work policy requires encrypted VPN connection.',
            'onboarding.md': '# Employee Onboarding Checklist\n1. Generate GPG Key.'
        }
        zip_buf = create_in_memory_zip(files)
        upload = SimpleUploadedFile('hr_bundle.zip', zip_buf.getvalue(), content_type='application/zip')

        res = client.post('/api/v1/sources/documents/', {
            'file': upload,
            'workspace': str(ws.id),
            'authority_level': 4
        }, format='multipart')

        assert res.status_code == 201
        data = res.json()
        assert 'zip_job' in data
        assert data['count'] == 2
        assert SourceDocument.objects.filter(workspace=ws, original_filename='remote_work.txt').exists()
        assert SourceDocument.objects.filter(workspace=ws, original_filename='onboarding.md').exists()

    def test_cancellation_flow(self, test_setup):
        ws = test_setup['workspace']
        client = test_setup['client']

        files = {
            'doc1.txt': 'Doc 1 content',
            'doc2.txt': 'Doc 2 content'
        }
        zip_buf = create_in_memory_zip(files)
        upload = SimpleUploadedFile('cancel_me.zip', zip_buf.getvalue(), content_type='application/zip')

        preview_res = client.post('/api/v1/sources/zip-imports/preview/', {
            'file': upload,
            'workspace': str(ws.id)
        }, format='multipart')
        job_id = preview_res.json()['id']

        # Cancel the job
        cancel_res = client.post(f'/api/v1/sources/zip-imports/{job_id}/cancel/')
        assert cancel_res.status_code == 200
        assert cancel_res.json()['status'] == 'cancelled'

        # Trying to start a cancelled job should fail
        start_res = client.post(f'/api/v1/sources/zip-imports/{job_id}/start/')
        assert start_res.status_code == 400

    def test_retry_mechanism_retries_only_failed(self, test_setup):
        ws = test_setup['workspace']
        user = test_setup['user']
        client = test_setup['client']

        files = {
            'success_doc.txt': 'Successfully imported text document.',
            'broken_doc.txt': 'This doc will be marked failed initially.'
        }
        zip_buf = create_in_memory_zip(files)
        upload = SimpleUploadedFile('retry_bundle.zip', zip_buf.getvalue(), content_type='application/zip')

        preview_res = client.post('/api/v1/sources/zip-imports/preview/', {
            'file': upload,
            'workspace': str(ws.id)
        }, format='multipart')
        job_id = preview_res.json()['id']

        job = ZipImportJob.objects.get(id=job_id)

        # Manually execute first entry successfully and mark second as failed
        entries = list(job.entries.all())
        entries[0].status = 'imported'
        entries[0].save()
        entries[1].status = 'failed'
        entries[1].error_message = 'Simulated OCR engine timeout'
        entries[1].save()

        job.status = 'partial_success'
        job.success_count = 1
        job.failed_count = 1
        job.save()

        # Call retry endpoint
        retry_res = client.post(f'/api/v1/sources/zip-imports/{job_id}/retry/')
        assert retry_res.status_code == 200

        # Check that entry 0 remained imported, entry 1 was retried and imported
        entries[0].refresh_from_db()
        entries[1].refresh_from_db()
        assert entries[0].status == 'imported'
        assert entries[1].status == 'imported'

    def test_workspace_isolation_cross_tenant_denied(self, test_setup):
        ws = test_setup['workspace']
        other_client = test_setup['other_client']

        files = {'secret.txt': 'Confidential engineering policy'}
        zip_buf = create_in_memory_zip(files)
        upload = SimpleUploadedFile('secret.zip', zip_buf.getvalue(), content_type='application/zip')

        # Other user (not a member of ws) tries to preview or upload to ws
        res = other_client.post('/api/v1/sources/zip-imports/preview/', {
            'file': upload,
            'workspace': str(ws.id)
        }, format='multipart')
        assert res.status_code == 404

    def test_zip_slip_attack_in_archive_rejected_on_preview(self, test_setup):
        ws = test_setup['workspace']
        client = test_setup['client']

        # Malicious zip with path traversal entry
        files = {
            'good.txt': 'innocent content',
            '../../etc/shadow': 'root::0:0:root:/root:/bin/bash'
        }
        zip_buf = create_in_memory_zip(files)
        upload = SimpleUploadedFile('malicious_slip.zip', zip_buf.getvalue(), content_type='application/zip')

        res = client.post('/api/v1/sources/zip-imports/preview/', {
            'file': upload,
            'workspace': str(ws.id)
        }, format='multipart')

        assert res.status_code == 400
        data = res.json()
        assert 'Zip Slip' in data['error'] or 'security_violation' in data.get('category', '')
