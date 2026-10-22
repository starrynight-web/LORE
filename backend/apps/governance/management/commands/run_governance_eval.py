import json
from django.core.management.base import BaseCommand
from apps.governance.evaluation import GovernanceEvaluationHarness

class Command(BaseCommand):
    help = "Executes the reproducible LORE governance evaluation benchmark suite (P3 §15)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--benchmark',
            type=str,
            default=None,
            help='Path to custom gold evaluation benchmark JSON file.',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            default=False,
            help='Output summary as JSON.',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            default=False,
            help='Print individual case evaluation results.',
        )

    def handle(self, *args, **options):
        benchmark_file = options.get('benchmark')
        output_json = options.get('json')
        verbose = options.get('verbose')

        harness = GovernanceEvaluationHarness(benchmark_file=benchmark_file)
        summary = harness.run_benchmark()

        if output_json:
            self.stdout.write(json.dumps(summary, indent=2))
            return

        self.stdout.write(self.style.NOTICE(
            f"\n======================================================\n"
            f"   LORE ENTERPRISE GOVERNANCE EVALUATION HARNESS\n"
            f"======================================================\n"
            f"Total Benchmark Cases: {summary['total_cases']}\n"
            f"Passed Cases:          {summary['passed_cases']}/{summary['total_cases']}\n"
            f"Precision:             {summary['precision'] * 100:.2f}%\n"
            f"Hallucination Rate:    {summary['hallucination_rate'] * 100:.2f}%\n"
            f"Abstention Accuracy:   {summary['abstention_accuracy'] * 100:.2f}%\n"
            f"Citation Validity:     {summary['citation_validity'] * 100:.2f}%\n"
            f"Contract Compliance:   {summary['contract_compliance'] * 100:.2f}%\n"
            f"Execution Duration:    {summary['duration_ms']}ms\n"
            f"======================================================"
        ))

        if verbose or not summary['benchmark_passed']:
            for r in summary['results']:
                status = self.style.SUCCESS("PASS") if r['passed'] else self.style.ERROR("FAIL")
                self.stdout.write(
                    f"[{status}] {r['case_id']} - {r['name']}: "
                    f"Expected={r['expected_verdict']}/{r['expected_directive']}, "
                    f"Actual={r['actual_verdict']}/{r['actual_directive']}"
                )

        if summary['benchmark_passed']:
            self.stdout.write(self.style.SUCCESS("\n[SUCCESS] Governance Evaluation Gate: PASSED (Zero Hallucinations, 100% Correct Abstention)."))
        else:
            self.stdout.write(self.style.ERROR("\n[FAILED] Governance Evaluation Gate: FAILED to satisfy enterprise thresholds."))
            exit(1)
