import os
from typing import Any, List, Dict
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.core.files.base import ContentFile

from apps.identity.models import Organization, OrganizationMembership
from apps.workspaces.models import Workspace, WorkspaceMembership, Collection
from apps.sources.models import SourceDocument, DocumentVersion
from apps.ingestion.models import IngestionJob
from apps.ingestion.tasks import process_ingestion_pipeline
from apps.subscriptions.models import Plan, Subscription

class Command(BaseCommand):
    help = 'Seeds multi-tenant demo organizations, plans, users, and documents for LORE Enterprise.'

    def handle(self, *args, **options):
        self.stdout.write("Seeding LORE Enterprise multi-tenant demo environment...")

        # 0. Seed Plans
        plan_starter, _ = Plan.objects.get_or_create(
            slug='starter',
            defaults={
                'name': 'Starter Tier',
                'description': 'For small teams needing governed RAG with core provenance controls.',
                'price_monthly': 49.00,
                'max_storage_mb': 500,
                'max_documents': 50,
                'max_monthly_queries': 500,
                'max_workspaces': 2,
                'max_members': 5,
                'allow_custom_models': False,
                'allow_ocr_bengali': True,
                'allow_audit_export': False,
            }
        )
        plan_enterprise, _ = Plan.objects.get_or_create(
            slug='enterprise-scale',
            defaults={
                'name': 'Enterprise Scale',
                'description': 'Full compliance, anti-hallucination grid, multi-workspace governance and citations.',
                'price_monthly': 299.00,
                'max_storage_mb': 10000,
                'max_documents': 1000,
                'max_monthly_queries': 20000,
                'max_workspaces': 25,
                'max_members': 50,
                'allow_custom_models': True,
                'allow_ocr_bengali': True,
                'allow_audit_export': True,
            }
        )

        # 1. Create Demo Users for Northstar Digital (Tenant 1)
        admin_user, _ = User.objects.get_or_create(
            username='admin@northstar.demo',
            defaults={'email': 'admin@northstar.demo', 'first_name': 'Sarah', 'last_name': 'Chen'}
        )
        admin_user.set_password('Northstar2026!')
        admin_user.is_staff = True
        admin_user.save()

        reviewer_user, _ = User.objects.get_or_create(
            username='reviewer@northstar.demo',
            defaults={'email': 'reviewer@northstar.demo', 'first_name': 'Marcus', 'last_name': 'Vance'}
        )
        reviewer_user.set_password('Northstar2026!')
        reviewer_user.save()

        viewer_user, _ = User.objects.get_or_create(
            username='viewer@northstar.demo',
            defaults={'email': 'viewer@northstar.demo', 'first_name': 'Elena', 'last_name': 'Rostova'}
        )
        viewer_user.set_password('Northstar2026!')
        viewer_user.save()

        # 2. Create Tenant 1 Organization: Northstar Digital
        org, _ = Organization.objects.get_or_create(
            slug='northstar-digital',
            defaults={'name': 'Northstar Digital (Simulated Enterprise)', 'description': 'ICAIB 2026 Knowledge Grid Benchmark Organization'}
        )
        OrganizationMembership.objects.get_or_create(
            organization=org, user=admin_user, defaults={'role': 'owner'}
        )
        OrganizationMembership.objects.get_or_create(
            organization=org, user=reviewer_user, defaults={'role': 'admin'}
        )
        OrganizationMembership.objects.get_or_create(
            organization=org, user=viewer_user, defaults={'role': 'member'}
        )

        # Northstar Subscription
        Subscription.objects.get_or_create(
            organization=org,
            defaults={
                'plan': plan_enterprise,
                'status': 'active',
                'stripe_subscription_id': 'sub_northstar_dev_01'
            }
        )

        # 3. Create Tenant 1 Workspace
        ws, _ = Workspace.objects.get_or_create(
            organization=org,
            slug='governance-security',
            defaults={'name': 'Governance & Security Workspace', 'description': 'Enterprise policy, compliance, and vendor risk records', 'is_default': True}
        )
        WorkspaceMembership.objects.get_or_create(
            workspace=ws, user=admin_user, defaults={'role': 'workspace_admin'}
        )
        WorkspaceMembership.objects.get_or_create(
            workspace=ws, user=reviewer_user, defaults={'role': 'editor'}
        )
        WorkspaceMembership.objects.get_or_create(
            workspace=ws, user=viewer_user, defaults={'role': 'viewer'}
        )

        # 4. Create Collections
        col_policies, _ = Collection.objects.get_or_create(workspace=ws, name='Cloud Policies', defaults={'color': 'indigo', 'icon': 'shield'})
        col_vendors, _ = Collection.objects.get_or_create(workspace=ws, name='Vendor Assessments', defaults={'color': 'amber', 'icon': 'briefcase'})
        col_contracts, _ = Collection.objects.get_or_create(workspace=ws, name='Executed Contracts', defaults={'color': 'emerald', 'icon': 'file-text'})

        # 5. Northstar Documents from knowledge_grid_enterprise.md
        docs_to_seed: List[Dict[str, Any]] = [
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
            title = str(item['title'])
            filename = str(item['filename'])
            content_str = str(item['content'])
            content_bytes = content_str.encode('utf-8')
            collection = item['collection']
            auth_val: Any = item['authority']
            authority = int(auth_val)

            doc, created = SourceDocument.objects.get_or_create(
                organization=org,
                workspace=ws,
                title=title,
                defaults={
                    'collection': collection,
                    'owner': admin_user,
                    'original_filename': filename,
                    'mime_type': 'text/markdown' if filename.endswith('.md') else 'text/plain',
                    'file_size': len(content_bytes),
                    'file_hash': 'sha256-' + filename[:16],
                    'file_obj': ContentFile(content_bytes, name=filename),
                    'document_type': 'txt',
                    'authority_level': authority,
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

        # 6. Tenant 2: Acme Aerospace & Defense (Demonstrates Strict Tenant Isolation)
        acme_admin, _ = User.objects.get_or_create(
            username='admin@acme.demo',
            defaults={'email': 'admin@acme.demo', 'first_name': 'Frank', 'last_name': 'Reynolds'}
        )
        acme_admin.set_password('Acme2026!')
        acme_admin.save()

        acme_org, _ = Organization.objects.get_or_create(
            slug='acme-aerospace',
            defaults={'name': 'Acme Aerospace (Tenant 2)', 'description': 'Defense Contractor & Aircraft Guidance Systems'}
        )
        OrganizationMembership.objects.get_or_create(
            organization=acme_org, user=acme_admin, defaults={'role': 'owner'}
        )
        Subscription.objects.get_or_create(
            organization=acme_org,
            defaults={
                'plan': plan_starter,
                'status': 'active',
                'stripe_subscription_id': 'sub_acme_dev_01'
            }
        )

        acme_ws, _ = Workspace.objects.get_or_create(
            organization=acme_org,
            slug='avionics-rnd',
            defaults={'name': 'Avionics R&D Workspace', 'description': 'Proprietary aerospace guidance telemetry', 'is_default': True}
        )
        WorkspaceMembership.objects.get_or_create(
            workspace=acme_ws, user=acme_admin, defaults={'role': 'workspace_admin'}
        )

        acme_content = (
            "# ACME Aerospace — Flight Control Guidance Spec v4\n"
            "Confidential Defense Documentation. STRICTLY RESTRICTED TO ACME AEROSPACE.\n"
            "Guidance system Model AC-990 employs redundant inertial sensors with 20ms response loop."
        ).encode('utf-8')

        acme_doc, acme_doc_created = SourceDocument.objects.get_or_create(
            organization=acme_org,
            workspace=acme_ws,
            title='ACME-AV-2026: Flight Guidance System Spec',
            defaults={
                'owner': acme_admin,
                'original_filename': 'acme-flight-guidance-v4.md',
                'mime_type': 'text/markdown',
                'file_size': len(acme_content),
                'file_hash': 'sha256-acme-guidance-01',
                'file_obj': ContentFile(acme_content, name='acme-flight-guidance-v4.md'),
                'document_type': 'txt',
                'authority_level': 7,
                'status': 'queued'
            }
        )
        if acme_doc_created:
            acme_job = IngestionJob.objects.create(
                document=acme_doc,
                organization=acme_org,
                workspace=acme_ws,
                status='queued',
                current_stage='inspection'
            )
            process_ingestion_pipeline(str(acme_job.id))
            self.stdout.write(f"  + Seeded Tenant 2 document: {acme_doc.title}")

        self.stdout.write(self.style.SUCCESS("\nSuccessfully seeded LORE Enterprise Multi-Tenant Demo Environment!"))
        self.stdout.write("="*70)
        self.stdout.write("TENANT 1: Northstar Digital (Enterprise Scale Plan)")
        self.stdout.write("  Admin:    admin@northstar.demo    / Northstar2026! (Role: Owner)")
        self.stdout.write("  Reviewer: reviewer@northstar.demo / Northstar2026! (Role: Admin / Editor)")
        self.stdout.write("  Viewer:   viewer@northstar.demo   / Northstar2026! (Role: Member / Viewer)")
        self.stdout.write("-"*70)
        self.stdout.write("TENANT 2: Acme Aerospace (Starter Plan - Isolated Tenant)")
        self.stdout.write("  Admin:    admin@acme.demo         / Acme2026!      (Role: Owner)")
        self.stdout.write("="*70)
