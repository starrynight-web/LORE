"""
LORE Enterprise - Export Judge Distillation Dataset (docs/enterprise/fix/knowledge.md §4)
Exports human-resolved UNRESOLVED_AUTHORITY_TIE and review queue overrides
in Alpaca or ChatML format for fine-tuning the local Phi-4 Judge.
"""

import os
import json
from django.core.management.base import BaseCommand, CommandError
from apps.governance.models import JudgeDistillationPair
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Exports human resolution pairs for Phi-4 Judge fine-tuning distillation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            type=str,
            required=False,
            help="Filter distillation pairs by workspace ID or slug.",
        )
        parser.add_argument(
            "--format",
            type=str,
            choices=["alpaca", "chatml"],
            default="alpaca",
            help="Dataset export format: 'alpaca' (instruction/input/output) or 'chatml' (system/user/assistant).",
        )
        parser.add_argument(
            "--output",
            type=str,
            required=False,
            help="Path to output JSONL file. Defaults to stdout if omitted.",
        )

    def handle(self, *args, **options):
        workspace_arg = options.get("workspace")
        fmt = options.get("format", "alpaca")
        out_path = options.get("output")

        qs = JudgeDistillationPair.objects.all()
        if workspace_arg:
            try:
                ws = Workspace.objects.filter(id=workspace_arg).first()
                if not ws:
                    ws = Workspace.objects.filter(slug=workspace_arg).first()
                if ws:
                    qs = qs.filter(workspace=ws)
                else:
                    qs = qs.filter(workspace_id=workspace_arg)
            except Exception:
                qs = qs.filter(workspace_id=workspace_arg)

        count = qs.count()
        records = []
        for pair in qs.order_by("created_at"):
            if fmt == "chatml":
                records.append(pair.to_chatml())
            else:
                records.append(pair.to_alpaca())

        if out_path:
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully exported {count} distillation pairs in {fmt.upper()} format to {out_path}."
                )
            )
        else:
            for rec in records:
                self.stdout.write(json.dumps(rec, ensure_ascii=False))
            self.stderr.write(
                self.style.SUCCESS(f"Streamed {count} distillation pairs in {fmt.upper()} format.")
            )

