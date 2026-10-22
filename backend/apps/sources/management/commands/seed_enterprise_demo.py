import os
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.core.files.base import ContentFile

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership, Collection
from apps.sources.models import SourceDocument, DocumentVersion
from apps.ingestion.models import IngestionJob
from apps.ingestion.tasks import process_ingestion_pipeline

class Command(BaseCommand):
    help = 'Seeds the Northstar Digital demo organization, workspace, and case study documents.'

    def handle(self, *args, **options):
        self.stdout.write("Seeding LORE Enterprise Northstar Digital demo environment...")

        # 1. Create Demo Admin User
        admin_user, _ = User.objects.get_or_create(
            username='admin@northstar.demo',
            defaults={'email': 'admin@northstar.demo', 'first_name': 'Sarah', 'last_name': 'Chen'}
        )
        admin_user.set_password('Northstar2026!')
        admin_user.is_staff = True
        admin_user.save()

        # 2. Create Organization
        org, _ = Organization.objects.get_or_create(
            slug='northstar-digital',
            defaults={'name': 'Northstar Digital (Simulated Enterprise)', 'description': 'ICAIB 2026 Knowledge Grid Benchmark Organization'}
        )
        OrganizationMembership.objects.get_or_create(
            organization=org,
            user=admin_user,
            defaults={'role': 'owner'}
        )

        # 3. Create Workspace
        ws, _ = Workspace.objects.get_or_create(
            organization=org,
            slug='governance-security',
            defaults={'name': 'Governance & Security Workspace', 'description': 'Enterprise policy, compliance, and vendor risk records', 'is_default': True}
        )
        WorkspaceMembership.objects.get_or_create(
            workspace=ws,
            user=admin_user,
            defaults={'role': 'workspace_admin'}
        )

        # 4. Create Collections
        col_policies, _ = Collection.objects.get_or_create(workspace=ws, name='Cloud Policies', defaults={'color': 'indigo', 'icon': 'shield'})
        col_vendors, _ = Collection.objects.get_or_create(workspace=ws, name='Vendor Assessments', defaults={'color': 'amber', 'icon': 'briefcase'})
        col_contracts, _ = Collection.objects.get_or_create(workspace=ws, name='Executed Contracts', defaults={'color': 'emerald', 'icon': 'file-text'})

        # 5. Northstar Documents from knowledge_grid_enterprise.md
        docs_to_seed = [
            {
                'title': 'POL-SEC-041: Cloud Security Policy v3.0',
                'filename': 'cloud-security-policy-v3.0.md',
                'collection': col_policies,
                'authority': 7,  # approved_policy
                'content': (
                    "# Northstar Digital — Cloud Security Policy v3.0\n"
                    "Document ID: POL-SEC-041 | Status: APPROVED | Effective: 2026-10-01\n\n"
                    "## 1. Scope & Core Directives\n"
                    "This policy applies to all Northstar Digital infrastructure, engineering teams, and third-party SaaS vendors.\n"
                    "No cloud software may process, store, or transmit Tier-1 Sensitive Customer Data unless all of the following conditions are strictly verified:\n"
                    "1. Current ISO 27001 or SOC 2 Type II certification on file.\n"
                    "2. Completed Third-Party Risk Assessment with a score >= 80% and zero open critical vulnerabilities.\n"
                    "3. Contractual Data Residency Guarantee ensuring sensitive customer records remain within designated geographic borders (US/EU regions).\n"
                    "4. Formal written sign-off from the Chief Information Security Officer (CISO) and Legal Counsel.\n\n"
                    "## 2. Conditional Exceptions & Prohibitions\n"
                    "Vendor CloudBox is categorized as Tier-2 SaaS. Use of CloudBox for internal non-sensitive code assets is permitted.\n"
                    "Use of CloudBox for customer PII, financial records, or credentials without verified data residency is strictly PROHIBITED."
                )
            },
            {
                'title': 'Engineering Wiki Entry — CloudBox Tools',
                'filename': 'wiki-cloudbox-tools.md',
                'collection': col_vendors,
                'authority': 2,  # wiki_entry
                'content': (
                    "# Engineering Wiki: CloudBox Collaboration\n"
                    "Author: DevTeam Lead | Last Modified: 2026-03-15 | Authority: Informal Wiki\n\n"
                    "## Overview\n"
                    "CloudBox is approved for engineering workflows. Developers can use it to sync team documentation and build artifacts.\n"
                    "Several teams are actively using CloudBox shared folders for customer data migration tests without issues."
                )
            },
            {
                'title': 'ASM-CLB-002: CloudBox Vendor Assessment Report',
                'filename': 'assessment-cloudbox-2026.md',
                'collection': col_vendors,
                'authority': 3,  # reviewed_document (pending)
                'content': (
                    "# Vendor Security Assessment: CloudBox Inc.\n"
                    "Assessment ID: ASM-CLB-002 | Review Date: 2026-08-10 | Status: PENDING SIGN-OFF\n\n"
                    "## Assessment Summary\n"
                    "SOC 2 Type II report received and reviewed: Satisfactory.\n"
                    "Data Residency Verification: Incomplete. CloudBox uses multi-tenant global clusters by default.\n"
                    "Regional containment addendum requested from vendor; waiting on Legal review.\n"
                    "Recommendation: Conditional approval pending receipt of executed Data Processing Addendum (DPA)."
                )
            },
            {
                'title': 'Procurement Note — CloudBox Enterprise Tier',
                'filename': 'procurement-cloudbox-note.txt',
                'collection': col_vendors,
                'authority': 1,  # informal_note
                'content': (
                    "Procurement Note - 2026-09-02\n"
                    "From: Procurement Dept\n"
                    "Subject: CloudBox Subscription Renewal\n"
                    "Renewed 50 developer seats for CloudBox Enterprise. Department manager approved expense."
                )
            },
            {
                'title': 'Executed Vendor Agreement — CloudBox Inc.',
                'filename': 'contract-cloudbox-executed.md',
                'collection': col_contracts,
                'authority': 6,  # signed_contract
                'content': (
                    "# Master Services Agreement — CloudBox Inc. & Northstar Digital\n"
                    "Contract Ref: MSA-2026-088 | Executed: 2026-09-15 | Authority: Signed Legal Contract\n\n"
                    "## Section 7: Data Protection & Processing\n"
                    "CloudBox agrees to implement commercially reasonable administrative, physical, and technical safeguards.\n"
                    "Dedicated regional data residency requires execution of Schedule D (Data Sovereignty Addendum). "
                    "Schedule D has not been attached or executed as of the effective date of this agreement."
                )
            }
        ]

        for item in docs_to_seed:
            content_bytes = item['content'].encode('utf-8')
            doc, created = SourceDocument.objects.get_or_create(
                organization=org,
                workspace=ws,
                title=item['title'],
                defaults={
                    'collection': item['collection'],
                    'owner': admin_user,
                    'original_filename': item['filename'],
                    'mime_type': 'text/markdown' if item['filename'].endswith('.md') else 'text/plain',
                    'file_size': len(content_bytes),
                    'file_hash': 'sha256-' + item['filename'][:16],
                    'file_obj': ContentFile(content_bytes, name=item['filename']),
                    'document_type': 'txt',
                    'authority_level': item['authority'],
                    'status': 'queued'
                }
            )

            if created:
                job = IngestionJob.objects.create(
                    document=doc,
                    organization=org,
                    workspace=ws,
                    status='queued',
                    current_stage='inspection'
                )
                process_ingestion_pipeline(str(job.id))
                self.stdout.write(f"  + Seeded and processed: {item['title']} -> Status: {doc.status}")

        self.stdout.write(self.style.SUCCESS("Successfully seeded Northstar Digital demo environment!"))
        self.stdout.write("Credentials:")
        self.stdout.write("  Username: admin@northstar.demo")
        self.stdout.write("  Password: Northstar2026!")
