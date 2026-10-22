import json
from django.core.management.base import BaseCommand
from apps.sources.reconciliation import StoreReconciliationService

class Command(BaseCommand):
    help = "Reconciles consistency between PostgreSQL (canonical truth) and Qdrant (derived vector index)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--workspace',
            type=str,
            default=None,
            help='UUID of workspace to filter reconciliation.',
        )
        parser.add_argument(
            '--fix',
            action='store_true',
            default=False,
            help='Automatically fix detected discrepancies (re-index missing chunks, purge orphans).',
        )
        parser.add_argument(
            '--collection',
            type=str,
            default='lore_chunks',
            help='Qdrant collection name to reconcile.',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            default=False,
            help='Output summary as JSON.',
        )

    def handle(self, *args, **options):
        workspace_id = options.get('workspace')
        fix = options.get('fix')
        collection = options.get('collection')
        output_json = options.get('json')

        self.stdout.write(self.style.NOTICE(
            f"Starting Store Reconciliation (workspace={workspace_id or 'all'}, fix={fix}, collection={collection})..."
        ))

        summary = StoreReconciliationService.reconcile(
            workspace_id=workspace_id,
            fix=fix,
            collection_name=collection
        )

        if output_json:
            self.stdout.write(json.dumps(summary, indent=2))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Reconciliation Complete: {summary['total_documents_checked']} documents checked. "
            f"Healthy: {summary['healthy_documents']}."
        ))

        if summary['mismatches']:
            self.stdout.write(self.style.WARNING(f"\nDiscrepancies Found ({len(summary['mismatches'])}):"))
            for m in summary['mismatches']:
                status = "REPAIRED" if m.get('fixed') else "UNRESOLVED"
                self.stdout.write(
                    f" - Doc {m['document_id']} ('{m['title']}'): PG Chunks={m['postgres_chunk_count']}, "
                    f"Qdrant Vectors={m['qdrant_vector_count']} -> [{status}]"
                )

        if summary['orphans']:
            self.stdout.write(self.style.WARNING(f"\nOrphaned Vectors Found in Qdrant ({len(summary['orphans'])}):"))
            for o in summary['orphans']:
                status = "PURGED" if o.get('fixed') else "UNRESOLVED"
                self.stdout.write(f" - Orphan Doc {o['document_id']}: {o['reason']} -> [{status}]")

        if not summary['mismatches'] and not summary['orphans']:
            self.stdout.write(self.style.SUCCESS("\nAll data stores are 100% synchronized and consistent."))
        elif not fix:
            self.stdout.write(self.style.NOTICE("\nRun with --fix to automatically repair discrepancies."))
