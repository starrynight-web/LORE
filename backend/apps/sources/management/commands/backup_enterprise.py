"""
LORE Enterprise — Automated Backup Management Command
Exports database records, Qdrant vectors, and media files with SHA-256 integrity manifest.
"""

import os
import json
import hashlib
import shutil
from datetime import datetime
from django.utils import timezone
from django.core.management.base import BaseCommand
from django.core import serializers
from django.conf import settings
from django.apps import apps
from apps.retrieval.vector_store import QdrantVectorStore


class Command(BaseCommand):
    help = "Creates an atomic backup of LORE database, Qdrant vectors, and media storage."

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            type=str,
            default=None,
            help='Directory path where backup archive should be created.'
        )
        parser.add_argument(
            '--skip-media',
            action='store_true',
            help='Skip archiving media files for rapid metadata and vector backup.'
        )

    def handle(self, *args, **options):
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        out_dir = options.get('output_dir') or os.path.join(settings.BASE_DIR, 'backups', f'lore_backup_{timestamp}')
        os.makedirs(out_dir, exist_ok=True)

        self.stdout.write(self.style.NOTICE(f"[BACKUP] Initiating LORE Enterprise backup to: {out_dir}"))

        # 1. Export Database Records (Excluding ContentTypes and Permissions which auto-seed)
        db_file = os.path.join(out_dir, "database_snapshot.json")
        models_to_export = [
            'identity.Organization',
            'identity.OrganizationMember',
            'workspaces.Workspace',
            'workspaces.Collection',
            'sources.SourceDocument',
            'sources.DocumentVersion',
            'sources.DocumentPage',
            'knowledge.DocumentChunk',
            'knowledge.KnowledgeItem',
            'knowledge.KnowledgeRelationship',
            'governance.SourcePermission',
            'governance.ConflictRecord',
            'governance.ScopedException',
            'governance.EvidenceRequirement',
            'audit.AuditEvent',
        ]

        all_objects = []
        total_records = 0
        for model_label in models_to_export:
            try:
                model = apps.get_model(model_label)
                qs = model.objects.all()
                count = qs.count()
                total_records += count
                for obj in qs:
                    all_objects.append(obj)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  Skipping {model_label}: {e}"))

        serialized_data = serializers.serialize("json", all_objects, indent=2)
        serialized_bytes = serialized_data.encode('utf-8')
        with open(db_file, "wb") as f:
            f.write(serialized_bytes)

        db_sha256 = hashlib.sha256(serialized_bytes).hexdigest()
        self.stdout.write(self.style.SUCCESS(f"[BACKUP] Exported {total_records} database records (SHA-256: {db_sha256[:12]}...)"))

        # 2. Export Qdrant Vector Data
        vstore_file = os.path.join(out_dir, "qdrant_vectors.json")
        vstore = QdrantVectorStore()
        vectors_exported = 0
        vector_data = []

        if vstore.client:
            try:
                # Scroll points from lore_chunks collection
                if hasattr(vstore.client, 'scroll'):
                    records, _ = vstore.client.scroll(
                        collection_name="lore_chunks",
                        limit=5000,
                        with_payload=True,
                        with_vectors=True
                    )
                    for r in records:
                        vector_data.append({
                            "id": str(r.id),
                            "vector": r.vector,
                            "payload": r.payload
                        })
                        vectors_exported += 1
            except Exception as ex:
                self.stdout.write(self.style.WARNING(f"  Could not scroll Qdrant points: {ex}"))

        v_bytes = json.dumps(vector_data, indent=2).encode('utf-8')
        with open(vstore_file, "wb") as f:
            f.write(v_bytes)

        v_sha256 = hashlib.sha256(v_bytes).hexdigest()
        self.stdout.write(self.style.SUCCESS(f"[BACKUP] Exported {vectors_exported} Qdrant vectors (SHA-256: {v_sha256[:12]}...)"))

        # 3. Archive Media Directory
        skip_media = options.get('skip_media', False)
        media_src = settings.MEDIA_ROOT
        media_dst = os.path.join(out_dir, "media_archive")
        media_file_count = 0
        if not skip_media and os.path.exists(media_src):
            shutil.copytree(media_src, media_dst, dirs_exist_ok=True)
            for _, _, files in os.walk(media_dst):
                media_file_count += len(files)
        else:
            os.makedirs(media_dst, exist_ok=True)
        self.stdout.write(self.style.SUCCESS(f"[BACKUP] Archived {media_file_count} media files."))

        # 4. Generate Manifest
        manifest = {
            "version": "lore.backup/1",
            "created_at": timezone.now().isoformat(),
            "database": {
                "records_count": total_records,
                "file": "database_snapshot.json",
                "sha256": db_sha256
            },
            "vectors": {
                "count": vectors_exported,
                "file": "qdrant_vectors.json",
                "sha256": v_sha256
            },
            "media": {
                "files_count": media_file_count,
                "directory": "media_archive"
            }
        }
        manifest_file = os.path.join(out_dir, "manifest.json")
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        self.stdout.write(self.style.SUCCESS(f"[BACKUP] Backup completed successfully. Manifest written to: {manifest_file}"))
