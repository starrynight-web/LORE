"""
LORE Enterprise — Automated Restore & Disaster Recovery Drill Command
Restores database records, Qdrant vectors, and media files with automated reconciliation.
"""

import os
import json
import hashlib
import shutil
from django.core.management.base import BaseCommand, CommandError
from django.core import serializers
from django.conf import settings
from django.db import transaction
from apps.retrieval.vector_store import QdrantVectorStore
from apps.sources.reconciliation import StoreReconciliationService


class Command(BaseCommand):
    help = "Restores LORE Enterprise state from an atomic backup and runs verification drills."

    def add_arguments(self, parser):
        parser.add_argument(
            '--backup-dir',
            type=str,
            required=True,
            help='Directory path containing the backup archive to restore.'
        )
        parser.add_argument(
            '--skip-reconciliation',
            action='store_true',
            help='Skip post-restore store reconciliation audit.'
        )
        parser.add_argument(
            '--fix-mismatches',
            action='store_true',
            help='Automatically heal and re-index any vector mismatches detected during post-restore audit.'
        )

    def handle(self, *args, **options):
        backup_dir = options['backup_dir']
        manifest_file = os.path.join(backup_dir, "manifest.json")

        if not os.path.exists(manifest_file):
            raise CommandError(f"Backup manifest not found at: {manifest_file}")

        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.stdout.write(self.style.NOTICE(f"[RESTORE] Initiating restore from: {backup_dir}"))
        self.stdout.write(self.style.NOTICE(f"[RESTORE] Backup created at: {manifest.get('created_at')}"))

        # 1. Verify Checksums
        db_file = os.path.join(backup_dir, manifest['database']['file'])
        with open(db_file, "rb") as f:
            actual_db_sha = hashlib.sha256(f.read()).hexdigest()
        if actual_db_sha != manifest['database']['sha256']:
            raise CommandError("Database snapshot checksum verification failed! Archive may be corrupted.")
        self.stdout.write(self.style.SUCCESS("[RESTORE] Checksum verified for database snapshot."))

        # 2. Restore Database Records inside Transaction
        with open(db_file, "r", encoding="utf-8") as f:
            data = f.read()

        records_restored = 0
        with transaction.atomic():
            for obj in serializers.deserialize("json", data):
                obj.save()
                records_restored += 1

        self.stdout.write(self.style.SUCCESS(f"[RESTORE] Restored {records_restored} database records."))

        # 3. Restore Qdrant Vectors
        vstore_file = os.path.join(backup_dir, manifest['vectors']['file'])
        vectors_restored = 0
        if os.path.exists(vstore_file):
            with open(vstore_file, "r", encoding="utf-8") as f:
                vector_data = json.load(f)

            vstore = QdrantVectorStore()
            if vstore.client and vector_data:
                ids = [p['id'] for p in vector_data]
                vectors = [p['vector'] for p in vector_data]
                payloads = [p['payload'] for p in vector_data]
                vstore.upsert_chunks("lore_chunks", vectors, payloads, ids)
                vectors_restored = len(ids)

        self.stdout.write(self.style.SUCCESS(f"[RESTORE] Restored {vectors_restored} Qdrant vectors."))

        # 4. Restore Media Directory
        media_src = os.path.join(backup_dir, manifest['media']['directory'])
        media_dst = settings.MEDIA_ROOT
        if os.path.exists(media_src):
            os.makedirs(media_dst, exist_ok=True)
            shutil.copytree(media_src, media_dst, dirs_exist_ok=True)
            self.stdout.write(self.style.SUCCESS(f"[RESTORE] Restored media directory to {media_dst}."))

        # 5. Post-Restore Store Reconciliation Drill
        if not options.get('skip_reconciliation'):
            self.stdout.write(self.style.NOTICE("[RESTORE] Executing post-restore StoreReconciliationService audit..."))
            fix_enabled = options.get('fix_mismatches', False)
            audit_result = StoreReconciliationService.reconcile(fix=fix_enabled)
            healthy = audit_result.get('healthy_documents', 0)
            mismatches = audit_result.get('mismatches', [])
            fixed_count = audit_result.get('fixed_count', 0)

            self.stdout.write(self.style.SUCCESS(f"[RESTORE AUDIT] Healthy Documents Verified: {healthy}"))
            if mismatches:
                self.stdout.write(self.style.WARNING(f"[RESTORE AUDIT] Mismatches detected: {len(mismatches)}"))
                for m in mismatches:
                    title_safe = str(m.get('title', m.get('document_id'))).encode('ascii', errors='replace').decode('ascii')
                    self.stdout.write(self.style.WARNING(f"  - {title_safe}: PG={m.get('postgres_chunk_count')} vs Qdrant={m.get('qdrant_vector_count')} (status={m.get('status')})"))
                if fixed_count > 0:
                    self.stdout.write(self.style.SUCCESS(f"[RESTORE AUDIT] Successfully auto-healed and re-indexed {fixed_count} documents into Qdrant."))
            else:
                self.stdout.write(self.style.SUCCESS("[RESTORE AUDIT] Zero store mismatches. Database, vector store, and files are 100% consistent."))

        self.stdout.write(self.style.SUCCESS("[RESTORE] Disaster recovery restore drill completed successfully."))
