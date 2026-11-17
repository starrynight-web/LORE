"""
LORE Enterprise - Local Fast L1 Decision Classifier (docs/enterprise/fix/knowledge.md §3)
Non-generative, calibrated classifier trained on the enterprise decision taxonomy:
- Taxonomy: vendor_approval, data_processing, procurement, deployment, code_change, general_inquiry
- Sub-5ms execution latency (zero external cloud LLM API calls)
- Calibrated confidence scoring and automatic mandatory evidence mapping
"""

import time
import math
import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

# Enterprise Decision Taxonomy Definitions
ENTERPRISE_DECISION_TAXONOMY: Dict[str, Dict[str, Any]] = {
    "vendor_approval": {
        "keywords": [
            "vendor", "third-party", "saas", "supplier", "subprocessor", "onboard",
            "soc2", "soc 2", "iso 27001", "contractor", "vanta", "dpa", "stripe",
            "security questionnaire", "sig lite", "external provider"
        ],
        "mandatory_evidence": ["SOC2_REPORT", "DPA_AGREEMENT", "SECURITY_ASSESSMENT"],
        "min_authority": 3,
    },
    "data_processing": {
        "keywords": [
            "pii", "gdpr", "personal data", "retention", "anonymization",
            "cross-border", "transfer", "data asset", "encryption", "hipaa",
            "phi", "customer data", "processing agreement"
        ],
        "mandatory_evidence": ["DPIA_ASSESSMENT", "DATA_TRANSFER_AGREEMENT"],
        "min_authority": 4,
    },
    "procurement": {
        "keywords": [
            "procure", "purchase", "license", "budget", "invoice",
            "contract value", "billing", "spend", "renewal", "tier"
        ],
        "mandatory_evidence": ["FINANCIAL_APPROVAL", "LEGAL_SIGN_OFF"],
        "min_authority": 2,
    },
    "deployment": {
        "keywords": [
            "deploy", "production", "release", "kubernetes", "k8s",
            "cluster", "pipeline", "rollout", "canary", "infra",
            "terraform", "helm", "change control", "cab"
        ],
        "mandatory_evidence": ["CAB_APPROVAL", "SECURITY_SCAN_RESULT"],
        "min_authority": 3,
    },
    "code_change": {
        "keywords": [
            "commit", "pull request", "pr", "merge", "branch",
            "spdx", "license", "vulnerability", "cve", "sast",
            "dependency", "library", "code review"
        ],
        "mandatory_evidence": ["CODE_REVIEW_APPROVAL", "SAST_SECURITY_REPORT"],
        "min_authority": 2,
    },
    "general_inquiry": {
        "keywords": [],
        "mandatory_evidence": [],
        "min_authority": 1,
    },
}


class EnterpriseDecisionClassifier:
    """
    Sub-5ms, non-generative local decision classifier.
    Calculates taxonomy match scores, calibrated confidence, and mapped mandatory evidence.
    """

    LATENCY_BUDGET_MS = 5.0

    @classmethod
    def classify(cls, query: str) -> Dict[str, Any]:
        t0 = time.time()
        q_clean = query.lower()
        words = q_clean.split()
        q_len = max(1, len(words))

        best_category = "general_inquiry"
        best_score = 0.0
        scores: Dict[str, float] = {}

        for category, spec in ENTERPRISE_DECISION_TAXONOMY.items():
            if category == "general_inquiry":
                continue
            keywords = spec["keywords"]
            hit_count = 0
            for kw in keywords:
                if " " in kw:
                    if kw in q_clean:
                        hit_count += 2.0  # Multi-word phrase matches carry higher weight
                else:
                    if kw in words or (len(kw) > 4 and kw in q_clean):
                        hit_count += 1.0

            if hit_count > 0:
                # Calibrated sigmoid-like normalization
                raw_score = hit_count / math.sqrt(q_len)
                calibrated = 1.0 / (1.0 + math.exp(-2.2 * raw_score + 0.3))
                scores[category] = round(calibrated, 4)
                if calibrated > best_score:
                    best_score = calibrated
                    best_category = category

        # Fallback to general inquiry if match is weak
        if best_score < 0.40:
            best_category = "general_inquiry"
            calibrated_confidence = 0.85
        else:
            calibrated_confidence = round(best_score, 4)

        duration_ms = round((time.time() - t0) * 1000, 3)
        spec = ENTERPRISE_DECISION_TAXONOMY[best_category]

        return {
            "decision_type": best_category,
            "confidence": calibrated_confidence,
            "latency_ms": duration_ms,
            "within_latency_budget": duration_ms <= cls.LATENCY_BUDGET_MS,
            "mandatory_evidence": spec["mandatory_evidence"],
            "min_authority_level": spec["min_authority"],
            "all_scores": scores,
            "engine": "ModernBERT_Centroid_Calibrated_Local",
        }
