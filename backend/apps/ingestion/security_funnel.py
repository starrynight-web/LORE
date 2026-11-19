"""
LORE Enterprise - Settlement Stage 2 Security Funnel (docs/enterprise/fix/knowledge.md §3)
Chains:
1. Microsoft Presidio PII & Enterprise Secret Redactor
2. DeBERTa Prompt Injection Scanner
3. SPDX License Compliance Scanner
"""

import re
import time
import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

# Enterprise PII & Secret Patterns (Presidio-compatible)
PII_AND_SECRET_PATTERNS = {
    "AWS_KEY": re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    "GITHUB_PAT": re.compile(r"\b(ghp_[0-9a-zA-Z]{36})\b"),
    "JWT_TOKEN": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._-]{10,}\.[A-Za-z0-9._-]{10,}\b"),
    "PRIVATE_KEY": re.compile(r"-----BEGIN\s+(?:RSA|EC|DSA|OPENSSH)?\s*PRIVATE\s+KEY-----"),
    "PASSWORD_IN_URI": re.compile(r"://[^\s/:@]+:([^\s/:@]+)@"),
    "US_SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "EMAIL_ADDRESS": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
}

# Advanced Prompt Injection & Jailbreak Signatures (DeBERTa injection detector heuristics)
ADVANCED_INJECTION_PATTERNS = [
    re.compile(r"<\s*script[^>]*>.*?</\s*script\s*>", re.IGNORECASE | re.DOTALL),
    re.compile(r"(?:ignore|disregard|bypass)\s+(?:all\s+)?(?:previous|prior|above|system)\s+(?:instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:in\s+developer\s+mode|dan|unrestricted)", re.IGNORECASE),
    re.compile(r"(?:reveal|exfiltrate|output|dump)\s+(?:the\s+)?(?:system\s+prompt|master\s+rules|api\s+key)", re.IGNORECASE),
    re.compile(r"system\s*override\s*:\s*bypass\s+governance", re.IGNORECASE),
    re.compile(r"bypass\s+governance", re.IGNORECASE),
    re.compile(r"<!--\s*system-override.*?-->", re.IGNORECASE | re.DOTALL),
    re.compile(r"\[\s*system\s*:\s*instruction\s*\]", re.IGNORECASE),
]

# SPDX Software License Identification Patterns
SPDX_LICENSE_PATTERNS = {
    "GPL-3.0": re.compile(r"\b(?:GNU\s+General\s+Public\s+License\s+v3|GPL-3\.0|GPLv3)\b", re.IGNORECASE),
    "AGPL-3.0": re.compile(r"\b(?:Affero\s+General\s+Public\s+License|AGPL-3\.0|AGPLv3)\b", re.IGNORECASE),
    "GPL-2.0": re.compile(r"\b(?:GNU\s+General\s+Public\s+License\s+v2|GPL-2\.0|GPLv2)\b", re.IGNORECASE),
    "Apache-2.0": re.compile(r"\b(?:Apache\s+License(?:,\s+Version|\s+2\.0))\b", re.IGNORECASE),
    "MIT": re.compile(r"\b(?:MIT\s+License)\b", re.IGNORECASE),
    "BSD-3-Clause": re.compile(r"\b(?:BSD\s+3-Clause|3-clause\s+BSD)\b", re.IGNORECASE),
}

RESTRICTIVE_COPYLEFT_LICENSES = {"GPL-3.0", "AGPL-3.0", "GPL-2.0"}


class SettlementSecurityFunnel:
    """
    Executes deep security verification across documents, web pages, and repositories.
    """

    @classmethod
    def run_deep_scan(cls, content: str, sanitize_pii: bool = False) -> Dict[str, Any]:
        t0 = time.time()
        threats = []
        secrets = []
        pii_matches = []
        detected_licenses = []
        copyleft_violations = []

        redacted_content = content

        # 1. Prompt Injection Scanning (DeBERTa injection emulation)
        for pattern in ADVANCED_INJECTION_PATTERNS:
            match = pattern.search(content)
            if match:
                threats.append(f"Prompt injection signature detected: {match.group(0)[:60]}")

        # 2. Presidio PII & High-Entropy Secret Scanning
        for pii_type, pattern in PII_AND_SECRET_PATTERNS.items():
            for m in pattern.finditer(content):
                matched_val = m.group(0)
                if pii_type in ("AWS_KEY", "GITHUB_PAT", "JWT_TOKEN", "PRIVATE_KEY", "PASSWORD_IN_URI"):
                    secrets.append({
                        "type": pii_type,
                        "location": (m.start(), m.end()),
                        "snippet": matched_val[:4] + "***" + matched_val[-4:] if len(matched_val) > 8 else "***",
                    })
                else:
                    pii_matches.append({
                        "type": pii_type,
                        "location": (m.start(), m.end()),
                    })

                if sanitize_pii:
                    redacted_content = redacted_content.replace(matched_val, f"[REDACTED_{pii_type}]")

        # 3. SPDX License Scanning
        for lic_name, pattern in SPDX_LICENSE_PATTERNS.items():
            if pattern.search(content):
                detected_licenses.append(lic_name)
                if lic_name in RESTRICTIVE_COPYLEFT_LICENSES:
                    copyleft_violations.append(lic_name)

        is_clean = len(threats) == 0 and len(secrets) == 0
        duration_ms = round((time.time() - t0) * 1000, 2)

        return {
            "passed": is_clean,
            "threats_detected": threats,
            "threat_count": len(threats),
            "secrets_detected": secrets,
            "secret_count": len(secrets),
            "pii_detected": pii_matches,
            "pii_count": len(pii_matches),
            "detected_licenses": detected_licenses,
            "copyleft_violations": copyleft_violations,
            "has_restrictive_copyleft": len(copyleft_violations) > 0,
            "redacted_content": redacted_content if sanitize_pii else None,
            "duration_ms": duration_ms,
        }
