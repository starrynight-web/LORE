"""
LORE Enterprise - CI/CD Exit-Code Gating Tool (lore-gate) (docs/enterprise/fix/knowledge.md §4)
Deterministic exit-code gates for GitHub Actions / GitLab CI pipelines:
  Exit Code 0: PASS (All compliance and governance criteria met)
  Exit Code 3: ASK_USER (Ambiguous evidence or human sign-off required)
  Exit Code 4: STOP (Critical security/policy violation or unresolved conflict)
"""

import sys
import json
import argparse
import logging
from typing import Dict, Any, Optional

from apps.governance.classifiers import EnterpriseDecisionClassifier
from apps.ingestion.security_funnel import SettlementSecurityFunnel
from apps.governance.live_evidence import LiveEvidenceRegistry, LiveEvidenceStatus

logger = logging.getLogger("lore_gate")

EXIT_PASS = 0
EXIT_ASK_USER = 3
EXIT_STOP = 4


def evaluate_gate(
    query_or_action: str,
    file_content: Optional[str] = None,
    target_entity: str = "",
    workspace_name: str = "default",
    strict_evidence: bool = True,
) -> Dict[str, Any]:
    """
    Evaluates policy compliance, security constraints, and live evidence.
    Returns evaluation result dictionary containing the deterministic exit_code.
    """
    violations = []
    warnings = []

    # 1. Security Scan (Prompt injection, secret leakage, copyleft licenses)
    text_to_scan = (file_content or "") + "\n" + query_or_action
    sec_scan = SettlementSecurityFunnel.run_deep_scan(text_to_scan)

    if not sec_scan["passed"]:
        for threat in sec_scan["threats_detected"]:
            violations.append(f"SECURITY_THREAT: {threat}")
        for secret in sec_scan["secrets_detected"]:
            violations.append(f"EXPOSED_SECRET: Found exposed {secret['type']}")

    if sec_scan.get("has_restrictive_copyleft"):
        for lic in sec_scan["copyleft_violations"]:
            violations.append(f"LICENSE_VIOLATION: Restrictive copyleft license '{lic}' detected.")

    # 2. Decision Classification & Mandatory Evidence Verification
    classification = EnterpriseDecisionClassifier.classify(query_or_action)
    decision_type = classification["decision_type"]
    mandatory_evidence = classification.get("mandatory_evidence", [])

    missing_evidence = []
    pending_evidence = []

    if strict_evidence and mandatory_evidence:
        for ev_type in mandatory_evidence:
            ev_check = LiveEvidenceRegistry.verify_evidence(
                evidence_type=ev_type,
                target_entity=target_entity or "generic_target",
            )
            ev_status = ev_check.get("status")
            if ev_status == LiveEvidenceStatus.MISSING:
                missing_evidence.append(ev_type)
            elif ev_status == LiveEvidenceStatus.PENDING:
                pending_evidence.append(ev_type)

    # 3. Deterministic Exit-Code Calculation
    # Hard violations -> STOP (4)
    if violations:
        exit_code = EXIT_STOP
        decision = "STOP"
        reason = f"Security or compliance policy hard stop: {'; '.join(violations[:3])}"
    elif missing_evidence:
        exit_code = EXIT_STOP
        decision = "STOP"
        reason = f"Mandatory evidence missing: {', '.join(missing_evidence)}"
    elif pending_evidence:
        exit_code = EXIT_ASK_USER
        decision = "ASK_USER"
        reason = f"Evidence pending human verification: {', '.join(pending_evidence)}"
    else:
        exit_code = EXIT_PASS
        decision = "PASS"
        reason = "All security checks and mandatory evidence satisfied."

    return {
        "exit_code": exit_code,
        "decision": decision,
        "reason": reason,
        "decision_type": decision_type,
        "classification": classification,
        "security_scan": sec_scan,
        "violations": violations,
        "missing_evidence": missing_evidence,
        "pending_evidence": pending_evidence,
    }


def main():
    parser = argparse.ArgumentParser(description="LORE Enterprise CI/CD Exit-Code Gate")
    parser.add_argument("--query", "-q", required=True, help="Query or action description to evaluate")
    parser.add_argument("--file", "-f", help="Optional path to source/diff file to inspect")
    parser.add_argument("--entity", "-e", default="", help="Target entity or vendor (e.g. AWS, Stripe, internal-repo)")
    parser.add_argument("--workspace", "-w", default="default", help="Workspace identifier")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()

    file_content = None
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8", errors="ignore") as fp:
                file_content = fp.read()
        except Exception as e:
            sys.stderr.write(f"Error reading file {args.file}: {e}\n")
            sys.exit(EXIT_STOP)

    result = evaluate_gate(
        query_or_action=args.query,
        file_content=file_content,
        target_entity=args.entity,
        workspace_name=args.workspace,
    )

    if args.json:
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
    else:
        sys.stdout.write(f"LORE-GATE DECISION: [{result['decision']}] (Exit Code: {result['exit_code']})\n")
        sys.stdout.write(f"Reason: {result['reason']}\n")
        if result["violations"]:
            sys.stdout.write(f"Violations:\n" + "\n".join(f"  - {v}" for v in result["violations"]) + "\n")

    sys.exit(result["exit_code"])


if __name__ == "__main__":
    main()

