#!/usr/bin/env python
"""
LORE Enterprise — Repeatable Multi-Dimensional Regression Benchmark
Evaluates LORE across 12 required test groups (A to L) using authentic synthetic
enterprise datasets, recording detailed per-test diagnostics and evaluating 8
distinct scoring dimensions independently.

Required Test Groups:
A. Single fact.
B. Multi-part answer.
C. Policy version comparison.
D. Draft versus approved status.
E. Current versus future-effective policy.
F. Historical and archived policy.
G. Threshold boundaries.
H. Supplier comparison.
I. Missing evidence.
J. Genuine source conflict.
K. Access-control denial.
L. Expandable details and proof.

Scoring Dimensions:
1. Answer Correctness
2. Completeness
3. Source Authority
4. Temporal Applicability
5. Citation Support
6. Relevance
7. Concise Presentation
8. Permission Enforcement
"""

import os
import sys
import json
import time
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone as dt_timezone
from typing import List, Dict, Any, Optional, Tuple

# Reconfigure stdout/stderr for Unicode support
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Configure Django environment if not already loaded
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lore_enterprise.settings')
import django
try:
    django.setup()
except Exception:
    pass

from django.utils import timezone
from apps.governance.contract import GovernanceRequest, Verdict, Directive
from apps.governance.layers import EnterpriseGovernanceEngine
from apps.governance.evidence import EvidencePresentationEngine
from apps.identity.models import Organization
from apps.workspaces.models import Workspace
from apps.sources.models import SourceDocument
from apps.governance.models import SourcePermission, AccessLevel
from django.contrib.auth.models import User


# ==============================================================================
# BENCHMARK DATA CONTRACTS
# ==============================================================================

@dataclass
class BenchmarkTestCase:
    test_id: str
    group: str
    group_name: str
    query: str
    expected_facts: List[str]
    permitted_caveats: List[str] = field(default_factory=list)
    expected_governing_doc_ids: List[str] = field(default_factory=list)
    expected_excluded_docs: List[Dict[str, str]] = field(default_factory=list)
    expected_state: str = "supported"
    expected_directive: Optional[str] = None
    expected_missing_evidence: List[str] = field(default_factory=list)
    candidate_evidence: List[Dict[str, Any]] = field(default_factory=list)
    as_of: Optional[Any] = None
    user_role: str = "member"
    is_cross_tenant: bool = False
    notes: str = ""


@dataclass
class BenchmarkExecutionRecord:
    test_id: str
    group: str
    group_name: str
    query: str
    expected_facts: List[str]
    permitted_caveats: List[str]
    expected_governing_doc_ids: List[str]
    expected_excluded_docs: List[Dict[str, str]]
    actual_answer: str
    actual_evidence: List[Dict[str, Any]]
    answer_state: str
    governance_decision: str
    all_requested_facts_present: bool
    citations_directly_support: bool
    evidence_duplicated_or_irrelevant: bool
    scoring: Dict[str, float]
    overall_score: float
    status: str  # PASS, PARTIAL, FAIL, BLOCKED
    latency_ms: float
    diagnostics: List[str] = field(default_factory=list)


# ==============================================================================
# SYNTHETIC BENCHMARK DATASET REGISTRY (GROUPS A - L)
# ==============================================================================

def build_benchmark_test_cases() -> List[BenchmarkTestCase]:
    cases: List[BenchmarkTestCase] = []

    # --------------------------------------------------------------------------
    # GROUP A: Single Fact
    # --------------------------------------------------------------------------
    cases.append(BenchmarkTestCase(
        test_id="BENCH-A01",
        group="A",
        group_name="Single Fact",
        query="What is the mandatory encryption algorithm for production database snapshots at rest?",
        expected_facts=["AES-256"],
        permitted_caveats=[],
        expected_governing_doc_ids=["DOC-ENC-002"],
        expected_excluded_docs=[{"title": "Legacy Storage Guideline v1.0", "reason": "superseded"}],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-a01-enc-v2",
                "document_id": "DOC-ENC-002",
                "document_code": "POL-SEC-041",
                "document_title": "Production Data Encryption Standard v2.0",
                "document_version": 2,
                "authority_level": 7,
                "document_status": "approved",
                "page_number": 4,
                "heading_path": "Section 4.1 > Cryptographic Standards",
                "text": "Section 4.1: AES-256 encryption is strictly mandatory for all production database snapshots and storage at rest.",
                "score": 0.94
            },
            {
                "chunk_id": "chk-a01-legacy",
                "document_id": "DOC-ENC-001",
                "document_code": "POL-SEC-041-OLD",
                "document_title": "Legacy Storage Guideline v1.0",
                "document_version": 1,
                "authority_level": 4,
                "document_status": "superseded",
                "is_superseded": True,
                "page_number": 2,
                "heading_path": "Legacy Storage",
                "text": "Deprecated: RC4 or 3DES storage encryption was permitted prior to 2025 revision.",
                "score": 0.70
            }
        ],
        notes="Single factual inquiry; must answer with AES-256 and exclude superseded guideline."
    ))

    cases.append(BenchmarkTestCase(
        test_id="BENCH-A02",
        group="A",
        group_name="Single Fact",
        query="What is the annual leave allowance for employees?",
        expected_facts=["25 days"],
        permitted_caveats=["Statutory bank holidays are provided in addition"],
        expected_governing_doc_ids=["POL-HR-001"],
        expected_excluded_docs=[],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-a02-leave",
                "document_id": "POL-HR-001",
                "document_code": "POL-HR-001",
                "document_title": "POL-HR-001: Employee Benefits and Leave Policy",
                "authority_level": 6,
                "document_status": "approved",
                "page_number": 3,
                "heading_path": "Section 2.1 > Annual Leave",
                "text": "Employees receive 25 days of paid annual leave per calendar year. Statutory bank holidays are provided in addition.",
                "score": 0.91
            }
        ],
        notes="Standard single-fact HR policy inquiry."
    ))

    # --------------------------------------------------------------------------
    # GROUP B: Multi-Part Answer
    # --------------------------------------------------------------------------
    cases.append(BenchmarkTestCase(
        test_id="BENCH-B01",
        group="B",
        group_name="Multi-Part Answer",
        query="What are the breakfast, lunch, and dinner meal allowances under the Travel Policy?",
        expected_facts=["$15", "$25", "$45"],
        permitted_caveats=["all claims must be substantiated with itemized receipts"],
        expected_governing_doc_ids=["DOC-TRV-SCH"],
        expected_excluded_docs=[],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-b01-b",
                "document_id": "DOC-TRV-SCH",
                "document_title": "Travel Policy Meal Allowance Schedule",
                "authority_level": 6,
                "document_status": "approved",
                "page_number": 5,
                "heading_path": "Schedule A > Itemized Meal Allowances",
                "text": "Itemized Meal Rates Schedule: The breakfast allowance is $15.",
                "score": 0.88
            },
            {
                "chunk_id": "chk-b01-l",
                "document_id": "DOC-TRV-SCH",
                "document_title": "Travel Policy Meal Allowance Schedule",
                "authority_level": 6,
                "document_status": "approved",
                "page_number": 5,
                "heading_path": "Schedule A > Itemized Meal Allowances",
                "text": "Itemized Meal Rates Schedule: The lunch allowance is $25.",
                "score": 0.86
            },
            {
                "chunk_id": "chk-b01-d",
                "document_id": "DOC-TRV-SCH",
                "document_title": "Travel Policy Meal Allowance Schedule",
                "authority_level": 6,
                "document_status": "approved",
                "page_number": 5,
                "heading_path": "Schedule A > Itemized Meal Allowances",
                "text": "Itemized Meal Rates Schedule: The dinner allowance is $45.",
                "score": 0.85
            }
        ],
        notes="Multi-part table inquiry; all 3 discrete meal amounts must be returned."
    ))

    cases.append(BenchmarkTestCase(
        test_id="BENCH-B02",
        group="B",
        group_name="Multi-Part Answer",
        query="What are the security access levels under the Security Access Policy?",
        expected_facts=["Level 1", "Level 2", "Level 3", "Level 4"],
        permitted_caveats=[],
        expected_governing_doc_ids=["POL-SEC-004"],
        expected_excluded_docs=[],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-b02-levels",
                "document_id": "POL-SEC-004",
                "document_code": "POL-SEC-004",
                "document_title": "POL-SEC-004: Enterprise Access Control Policy",
                "authority_level": 7,
                "document_status": "approved",
                "page_number": 2,
                "heading_path": "Section 1.2 > Classification Tiers",
                "text": "Security access is structured into four levels: Level 1 (Public/Guest), Level 2 (Standard Employee), Level 3 (Manager/Confidential), and Level 4 (Administrative/MFA Required).",
                "score": 0.93
            }
        ],
        notes="Multi-part enumeration query; must preserve all four defined access tiers."
    ))

    # --------------------------------------------------------------------------
    # GROUP C: Policy Version Comparison
    # --------------------------------------------------------------------------
    cases.append(BenchmarkTestCase(
        test_id="BENCH-C01",
        group="C",
        group_name="Policy Version Comparison",
        query="Compare version 1 and version 2 of the Travel Policy",
        expected_facts=["Version 1", "$40", "Version 2", "$50"],
        permitted_caveats=["Version 2.0 supersedes Version 1.0"],
        expected_governing_doc_ids=["DOC-TRV-V1", "DOC-TRV-V2"],
        expected_excluded_docs=[],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-c01-v1",
                "document_id": "DOC-TRV-V1",
                "document_title": "Travel Policy (v1.0)",
                "document_version": 1,
                "authority_level": 5,
                "document_status": "superseded",
                "page_number": 3,
                "heading_path": "Section 3.1 > Per Diem",
                "text": "Under Version 1.0, the maximum daily meal allowance was $40 per day.",
                "score": 0.88
            },
            {
                "chunk_id": "chk-c01-v2",
                "document_id": "DOC-TRV-V2",
                "document_title": "Travel Policy (v2.0)",
                "document_version": 2,
                "authority_level": 5,
                "document_status": "approved",
                "page_number": 3,
                "heading_path": "Section 3.1 > Per Diem",
                "text": "Version 2.0 supersedes Version 1.0 and increases the daily meal allowance to $50 per day.",
                "score": 0.87
            }
        ],
        notes="Version comparison inquiry; must return both rates and explain supersession."
    ))

    # --------------------------------------------------------------------------
    # GROUP D: Draft Versus Approved Status
    # --------------------------------------------------------------------------
    cases.append(BenchmarkTestCase(
        test_id="BENCH-D01",
        group="D",
        group_name="Draft Versus Approved Status",
        query="What is the daily meal allowance under current approved policy?",
        expected_facts=["$220"],
        permitted_caveats=["Draft", "proposes $180", "non-binding"],
        expected_governing_doc_ids=["DOC-002"],
        expected_excluded_docs=[{"title": "DOC-001 Draft Expense Policy", "reason": "unapproved draft"}],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-d01-approved",
                "document_id": "DOC-002",
                "document_code": "DOC-002",
                "document_title": "DOC-002 Travel and Expense Policy",
                "document_version": 2,
                "authority_level": 7,
                "document_status": "approved",
                "page_number": 2,
                "heading_path": "Section 2 > Per Diem",
                "text": "Effective July 1, 2026: The approved daily meal allowance is $220 per travel day.",
                "score": 0.85
            },
            {
                "chunk_id": "chk-d01-draft",
                "document_id": "DOC-001",
                "document_code": "DOC-001",
                "document_title": "DOC-001 Draft Expense Policy",
                "document_version": 1,
                "authority_level": 4,
                "document_status": "draft",
                "is_draft": True,
                "page_number": 1,
                "heading_path": "Draft Proposal",
                "text": "Status: DRAFT. Daily meal allowance is $180 per day. Pending board approval.",
                "score": 0.95  # Higher semantic similarity must NOT override approved policy
            }
        ],
        as_of=datetime(2026, 10, 1, tzinfo=dt_timezone.utc),
        notes="Approved DOC-002 ($220) must govern; draft DOC-001 ($180) must remain non-binding caveat."
    ))

    cases.append(BenchmarkTestCase(
        test_id="BENCH-D02",
        group="D",
        group_name="Draft Versus Approved Status",
        query="What does the draft expense policy say?",
        expected_facts=["$180"],
        permitted_caveats=["draft", "non-binding", "unapproved"],
        expected_governing_doc_ids=["DOC-001"],
        expected_excluded_docs=[],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-d02-draft",
                "document_id": "DOC-001",
                "document_code": "DOC-001",
                "document_title": "DOC-001 Draft Expense Policy",
                "document_version": 1,
                "authority_level": 4,
                "document_status": "draft",
                "is_draft": True,
                "page_number": 1,
                "heading_path": "Draft Proposal",
                "text": "Status: DRAFT. Daily meal allowance is $180 per day. Pending formal adoption.",
                "score": 0.92
            }
        ],
        notes="Query specifically asks what the draft says; must report $180 and disclose draft status."
    ))

    # --------------------------------------------------------------------------
    # GROUP E: Current Versus Future-Effective Policy
    # --------------------------------------------------------------------------
    cases.append(BenchmarkTestCase(
        test_id="BENCH-E01",
        group="E",
        group_name="Current Versus Future-Effective Policy",
        query="What is the current meal allowance?",
        expected_facts=["$50"],
        permitted_caveats=["Effective January 1, 2027", "increases to $70"],
        expected_governing_doc_ids=["POL-EXP-001"],
        expected_excluded_docs=[{"title": "POL-EXP-001-AMEND", "reason": "future-effective policy not applicable in 2026"}],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-e01-curr",
                "document_id": "POL-EXP-001",
                "document_code": "POL-EXP-001",
                "document_title": "POL-EXP-001: Travel & Expense Standard",
                "authority_level": 6,
                "document_status": "approved",
                "effective_date": "2024-01-01",
                "page_number": 6,
                "heading_path": "Section 4.1 > Current Per Diem",
                "text": "Employees are authorized a daily meal per diem of $50.",
                "score": 0.86
            },
            {
                "chunk_id": "chk-e01-fut",
                "document_id": "POL-EXP-001-AMEND",
                "document_code": "POL-EXP-001-AMEND",
                "document_title": "POL-EXP-001-AMEND: Travel Allowance Update 2027",
                "authority_level": 6,
                "document_status": "future-effective",
                "is_future_effective": True,
                "effective_date": "2027-01-01",
                "page_number": 1,
                "heading_path": "Amendment 2027",
                "text": "Effective January 1, 2027, the daily meal per diem increases to $70.",
                "score": 0.94
            }
        ],
        as_of=datetime(2026, 6, 15, tzinfo=dt_timezone.utc),
        notes="Current rate ($50) answers current query; future rate ($70) retained as upcoming caveat."
    ))

    # --------------------------------------------------------------------------
    # GROUP F: Historical and Archived Policy
    # --------------------------------------------------------------------------
    cases.append(BenchmarkTestCase(
        test_id="BENCH-F01",
        group="F",
        group_name="Historical and Archived Policy",
        query="What was the travel meal allowance in 2024?",
        expected_facts=["$150"],
        permitted_caveats=["superseded in 2026 by DOC-002 ($220)"],
        expected_governing_doc_ids=["DOC-016"],
        expected_excluded_docs=[{"title": "DOC-002 Travel Policy", "reason": "superseded DOC-016 only in 2026"}],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-f01-hist",
                "document_id": "DOC-016",
                "document_code": "DOC-016",
                "document_title": "DOC-016 Travel Policy 2024",
                "authority_level": 6,
                "document_status": "superseded",
                "effective_date": "2024-01-01",
                "page_number": 4,
                "heading_path": "Section 2 > Historical Per Diem",
                "text": "In 2024, the authorized daily travel meal allowance was $150.",
                "score": 0.88
            },
            {
                "chunk_id": "chk-f01-curr",
                "document_id": "DOC-002",
                "document_code": "DOC-002",
                "document_title": "DOC-002 Travel and Expense Policy 2026",
                "authority_level": 7,
                "document_status": "approved",
                "effective_date": "2026-07-01",
                "page_number": 2,
                "heading_path": "Section 2 > Current Per Diem",
                "text": "Effective July 1, 2026: The approved daily meal allowance is $220 per travel day.",
                "score": 0.83
            }
        ],
        as_of=datetime(2024, 6, 1, tzinfo=dt_timezone.utc),
        notes="Historical point-in-time query for 2024 must answer from 2024 governing policy ($150)."
    ))

    cases.append(BenchmarkTestCase(
        test_id="BENCH-F02",
        group="F",
        group_name="Historical and Archived Policy",
        query="What was the meal allowance in version 1 of the Travel Policy?",
        expected_facts=["$40"],
        permitted_caveats=["Version 2.0 increased daily meal allowance to $50"],
        expected_governing_doc_ids=["DOC-TRV-V1"],
        expected_excluded_docs=[],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-f02-v1",
                "document_id": "DOC-TRV-V1",
                "document_title": "Travel Policy (v1.0)",
                "document_version": 1,
                "authority_level": 5,
                "document_status": "superseded",
                "is_superseded": True,
                "page_number": 3,
                "heading_path": "Section 3.1",
                "text": "Under Version 1.0, the maximum daily meal allowance was $40 per day.",
                "score": 0.86
            },
            {
                "chunk_id": "chk-f02-v2",
                "document_id": "DOC-TRV-V2",
                "document_title": "Travel Policy (v2.0)",
                "document_version": 2,
                "authority_level": 5,
                "document_status": "approved",
                "page_number": 3,
                "heading_path": "Section 3.1",
                "text": "Version 2.0 supersedes Version 1.0 and increases the daily meal allowance to $50 per day.",
                "score": 0.84
            }
        ],
        notes="Question explicitly specifies Version 1; Sentence 1 must answer directly from Version 1 ($40)."
    ))

    # --------------------------------------------------------------------------
    # GROUP G: Threshold Boundaries
    # --------------------------------------------------------------------------
    cases.append(BenchmarkTestCase(
        test_id="BENCH-G01",
        group="G",
        group_name="Threshold Boundaries",
        query="What approval is required for a $5,000 purchase?",
        expected_facts=["$5,000", "Tier 1", "Department Manager"],
        permitted_caveats=["without competitive bids"],
        expected_governing_doc_ids=["POL-PROC-001"],
        expected_excluded_docs=[],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-g01-thresh",
                "document_id": "POL-PROC-001",
                "document_code": "POL-PROC-001",
                "document_title": "Enterprise Procurement Policy",
                "authority_level": 7,
                "document_status": "approved",
                "page_number": 3,
                "heading_path": "Section 3 > Expenditure Thresholds",
                "text": (
                    "Enterprise Procurement Policy - Section 3: Expenditure Thresholds.\n"
                    "Tier 1 (Micro-Purchase): Purchases up to and including $5,000 require only Department Manager approval without competitive bids.\n"
                    "Tier 2 (Small Procurement): Purchases greater than $5,000 and up to and including $25,000 require at least 3 competitive quotes and Director approval.\n"
                    "Tier 3 (Major Contracts): Purchases exceeding $25,000 require a formal competitive Request for Proposals (RFP), Legal review, and VP approval."
                ),
                "score": 0.91
            }
        ],
        notes="Exact inclusive boundary $5,000 falls strictly into Tier 1 (micro-purchase)."
    ))

    cases.append(BenchmarkTestCase(
        test_id="BENCH-G02",
        group="G",
        group_name="Threshold Boundaries",
        query="What approval is required for a $25,000 purchase?",
        expected_facts=["$25,000", "Tier 2", "3 competitive quotes", "Director approval"],
        permitted_caveats=[],
        expected_governing_doc_ids=["POL-PROC-001"],
        expected_excluded_docs=[],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-g02-thresh",
                "document_id": "POL-PROC-001",
                "document_code": "POL-PROC-001",
                "document_title": "Enterprise Procurement Policy",
                "authority_level": 7,
                "document_status": "approved",
                "page_number": 3,
                "heading_path": "Section 3 > Expenditure Thresholds",
                "text": (
                    "Enterprise Procurement Policy - Section 3: Expenditure Thresholds.\n"
                    "Tier 1 (Micro-Purchase): Purchases up to and including $5,000 require only Department Manager approval without competitive bids.\n"
                    "Tier 2 (Small Procurement): Purchases greater than $5,000 and up to and including $25,000 require at least 3 competitive quotes and Director approval.\n"
                    "Tier 3 (Major Contracts): Purchases exceeding $25,000 require a formal competitive Request for Proposals (RFP), Legal review, and VP approval."
                ),
                "score": 0.91
            }
        ],
        notes="Exact inclusive boundary $25,000 falls strictly into Tier 2 (small procurement)."
    ))

    # --------------------------------------------------------------------------
    # GROUP H: Supplier Comparison
    # --------------------------------------------------------------------------
    cases.append(BenchmarkTestCase(
        test_id="BENCH-H01",
        group="H",
        group_name="Supplier Comparison",
        query="Compare Supplier Alpha and Supplier Beta for pricing and delivery",
        expected_facts=["Supplier Alpha", "$12,000", "5 business days", "Supplier Beta", "$9,500", "14 business days"],
        permitted_caveats=[],
        expected_governing_doc_ids=["PROP-ALPHA", "PROP-BETA"],
        expected_excluded_docs=[],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-h01-alpha",
                "document_id": "PROP-ALPHA",
                "document_title": "Supplier Alpha Proposal",
                "authority_level": 5,
                "document_status": "approved",
                "page_number": 1,
                "heading_path": "Commercial Terms",
                "text": "Supplier Alpha proposes a total project cost of $12,000 with expedited delivery in 5 business days.",
                "score": 0.88
            },
            {
                "chunk_id": "chk-h01-beta",
                "document_id": "PROP-BETA",
                "document_title": "Supplier Beta Proposal",
                "authority_level": 5,
                "document_status": "approved",
                "page_number": 1,
                "heading_path": "Commercial Terms",
                "text": "Supplier Beta proposes an economical rate of $9,500 with standard delivery within 14 business days.",
                "score": 0.87
            }
        ],
        notes="Supplier comparison; must state pricing and delivery for both proposals."
    ))

    cases.append(BenchmarkTestCase(
        test_id="BENCH-H02",
        group="H",
        group_name="Supplier Comparison",
        query="Which supplier is best between Supplier Alpha and Supplier Beta?",
        expected_facts=["cost", "delivery speed", "specify"],
        permitted_caveats=["Supplier Beta is best for cost", "Supplier Alpha is best for delivery speed"],
        expected_governing_doc_ids=["PROP-ALPHA", "PROP-BETA"],
        expected_excluded_docs=[],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-h02-alpha",
                "document_id": "PROP-ALPHA",
                "document_title": "Supplier Alpha Proposal",
                "authority_level": 5,
                "document_status": "approved",
                "page_number": 1,
                "heading_path": "Commercial Terms",
                "text": "Supplier Alpha offers $12,000 with 5 business days delivery.",
                "score": 0.88
            },
            {
                "chunk_id": "chk-h02-beta",
                "document_id": "PROP-BETA",
                "document_title": "Supplier Beta Proposal",
                "authority_level": 5,
                "document_status": "approved",
                "page_number": 1,
                "heading_path": "Commercial Terms",
                "text": "Supplier Beta offers $9,500 with 14 business days delivery.",
                "score": 0.87
            }
        ],
        notes="Ambiguous 'best' supplier query; must articulate the cost vs speed trade-off."
    ))

    # --------------------------------------------------------------------------
    # GROUP I: Missing Evidence
    # --------------------------------------------------------------------------
    cases.append(BenchmarkTestCase(
        test_id="BENCH-I01",
        group="I",
        group_name="Missing Evidence",
        query="Can we approve third-party vendor CloudBox for EU customer records?",
        expected_facts=["Cannot authorize", "missing"],
        permitted_caveats=["Route to Security Team"],
        expected_governing_doc_ids=["POL-SEC-041", "MSA-CLOUDBOX"],
        expected_excluded_docs=[],
        expected_state="insufficient",
        expected_directive="ask_user",
        expected_missing_evidence=["executed_data_residency_addendum"],
        candidate_evidence=[
            {
                "chunk_id": "chk-i01-policy",
                "document_id": "POL-SEC-041",
                "document_code": "POL-SEC-041",
                "document_title": "POL-SEC-041: Cloud Security Policy v3.0",
                "authority_level": 7,
                "document_status": "approved",
                "page_number": 2,
                "heading_path": "Section 1.2 > Third-Party Data Residency",
                "text": "No cloud software may process or store sensitive customer data without an executed Contractual Data Residency Guarantee (Schedule D).",
                "score": 0.90
            },
            {
                "chunk_id": "chk-i01-contract",
                "document_id": "MSA-CLOUDBOX",
                "document_title": "Executed Vendor Agreement — CloudBox Inc.",
                "authority_level": 6,
                "document_status": "approved",
                "page_number": 4,
                "heading_path": "Section 7 > Data Protection",
                "text": "Dedicated regional data residency requires execution of Schedule D (Data Sovereignty Addendum). Schedule D has not been attached or executed as of the effective date.",
                "score": 0.88
            }
        ],
        notes="Missing mandatory data residency agreement; engine must forbid approval and report insufficient."
    ))

    # --------------------------------------------------------------------------
    # GROUP J: Genuine Source Conflict
    # --------------------------------------------------------------------------
    cases.append(BenchmarkTestCase(
        test_id="BENCH-J01",
        group="J",
        group_name="Genuine Source Conflict",
        query="What is the maximum data retention period for financial audit ledgers?",
        expected_facts=["Contradictory authoritative sources detected", "365 days", "7 years"],
        permitted_caveats=["LORE will not guess between equal-authority policies"],
        expected_governing_doc_ids=["POL-LOG-01", "POL-COMP-02"],
        expected_excluded_docs=[],
        expected_state="conflicting",
        expected_directive="ask_user",
        candidate_evidence=[
            {
                "chunk_id": "chk-j01-pol1",
                "document_id": "POL-LOG-01",
                "document_code": "POL-LOG-01",
                "document_title": "POL-LOG-01: Information Lifecycle Policy",
                "authority_level": 6,
                "document_status": "approved",
                "page_number": 5,
                "heading_path": "Section 4 > Log Retention",
                "text": "Section 4: Financial audit ledgers must be retained for exactly 365 days before purging.",
                "score": 0.89
            },
            {
                "chunk_id": "chk-j01-pol2",
                "document_id": "POL-COMP-02",
                "document_code": "POL-COMP-02",
                "document_title": "POL-COMP-02: Corporate Compliance Standard",
                "authority_level": 6,
                "document_status": "approved",
                "page_number": 8,
                "heading_path": "Section 9 > Statutory Records",
                "text": "Section 9: Financial audit ledgers must be retained for exactly 7 years to satisfy statutory audit mandates.",
                "score": 0.88
            }
        ],
        notes="Equal-rank (Rank 6) contradiction without supersession; engine must escalate to conflicting."
    ))

    # --------------------------------------------------------------------------
    # GROUP K: Access-Control Denial
    # --------------------------------------------------------------------------
    cases.append(BenchmarkTestCase(
        test_id="BENCH-K01",
        group="K",
        group_name="Access-Control Denial",
        query="What are the secret proprietary avionics radar frequencies?",
        expected_facts=["No governed knowledge found"],
        permitted_caveats=[],
        expected_governing_doc_ids=[],
        expected_excluded_docs=[{"title": "ACME-AV-2026: Flight Guidance System Spec", "reason": "foreign tenant workspace"}],
        expected_state="no_knowledge",
        expected_directive="proceed",
        candidate_evidence=[],
        is_cross_tenant=True,
        notes="Cross-tenant isolation barrier; foreign tenant records must be 100% invisible."
    ))

    cases.append(BenchmarkTestCase(
        test_id="BENCH-K02",
        group="K",
        group_name="Access-Control Denial",
        query="What is the equipment policy and executive salary?",
        expected_facts=["standard IT equipment", "laptop"],
        permitted_caveats=[],
        expected_governing_doc_ids=["General IT Handbook", "DOC-PUB-IT"],
        expected_excluded_docs=[{"title": "Executive Compensation Confidential", "reason": "L7 permission restricted for role member"}],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-k02-pub",
                "document_id": "DOC-PUB-IT",
                "document_title": "General IT Handbook",
                "authority_level": 4,
                "document_status": "approved",
                "page_number": 1,
                "heading_path": "Equipment",
                "text": "All employees receive standard IT equipment including a company laptop.",
                "score": 0.80
            },
            {
                "chunk_id": "chk-k02-restricted",
                "document_id": "DOC-RESTRICTED-EXEC",
                "document_title": "Executive Compensation Confidential",
                "authority_level": 7,
                "document_status": "approved",
                "page_number": 1,
                "heading_path": "Compensation",
                "text": "Confidential: Executive base salary scale exceeds $500,000 annually with 50% equity.",
                "score": 0.95
            }
        ],
        user_role="member",
        notes="L7 permission filter blocks restricted document; $500,000 must never leak into answer or citations."
    ))

    # --------------------------------------------------------------------------
    # GROUP L: Expandable Details and Proof
    # --------------------------------------------------------------------------
    cases.append(BenchmarkTestCase(
        test_id="BENCH-L01",
        group="L",
        group_name="Expandable Details and Proof",
        query="What is the data retention period for customer activity logs?",
        expected_facts=["365 days"],
        permitted_caveats=[],
        expected_governing_doc_ids=["doc-data-retention-policy"],
        expected_excluded_docs=[{"title": "Engineering Informal Wiki Guidelines", "reason": "low authority informal source outranked"}],
        expected_state="supported",
        expected_directive="proceed_and_cite",
        candidate_evidence=[
            {
                "chunk_id": "chk-l01-wiki",
                "document_id": "doc-wiki",
                "document_title": "Engineering Informal Wiki Guidelines",
                "document_status": "unknown",
                "authority_level": 2,
                "page_number": 1,
                "heading_path": "Wiki > Logs",
                "text": "Customer activity logs should generally be retained for 30 days before deletion.",
                "score": 0.96  # High semantic similarity
            },
            {
                "chunk_id": "chk-l01-policy",
                "document_id": "doc-data-retention-policy",
                "document_code": "POL-SEC-042",
                "document_title": "POL-SEC-042: Enterprise Data Retention Policy",
                "document_status": "approved",
                "authority_level": 6,
                "page_number": 9,
                "heading_path": "Section 5.1 > Activity Logs",
                "text": "Section 5.1: Customer activity logs must be retained for exactly 365 days to comply with statutory audit mandates.",
                "score": 0.72  # Lower similarity score
            }
        ],
        notes="Concise view must state 365 days in sentence 1; expanded citations must retain Page 9 and Section 5.1 provenance."
    ))

    return cases


# ==============================================================================
# BENCHMARK EVALUATOR & SCORING ENGINE
# ==============================================================================

class BenchmarkEvaluator:
    """
    Evaluates LORE execution against expected criteria across 8 independent dimensions.
    Does not count an answer correct merely because it is labeled SUPPORTED.
    """

    @classmethod
    def evaluate_test_case(
        cls,
        case: BenchmarkTestCase,
        envelope: Dict[str, Any],
        latency_ms: float
    ) -> BenchmarkExecutionRecord:
        answer_text = str(envelope.get("answer") or envelope.get("answer_text") or "").strip()
        state = str(envelope.get("state") or "").lower()
        directive = str(envelope.get("directive") or "").lower()
        citations = envelope.get("citations") or []
        evidence_missing = envelope.get("evidence_missing") or []

        diagnostics: List[str] = []

        # ----------------------------------------------------------------------
        # Dimension 1: Answer Correctness
        # ----------------------------------------------------------------------
        correctness_score = 0.0
        expected_state_match = (state == case.expected_state.lower()) or (
            case.expected_state == "supported" and state in ["supported", "qualified"]
        )

        facts_present = [fact.lower() in answer_text.lower() for fact in case.expected_facts]
        has_all_facts = all(facts_present) if case.expected_facts else True

        if expected_state_match and has_all_facts:
            correctness_score = 1.0
        elif expected_state_match and any(facts_present):
            correctness_score = 0.5
            diagnostics.append("Partial fact match in answer text.")
        else:
            diagnostics.append(f"Expected state '{case.expected_state}' but got '{state}'.")

        # ----------------------------------------------------------------------
        # Dimension 2: Completeness
        # ----------------------------------------------------------------------
        completeness_score = (
            sum(1.0 for f in facts_present if f) / max(len(case.expected_facts), 1)
        ) if case.expected_facts else 1.0

        # ----------------------------------------------------------------------
        # Dimension 3: Source Authority
        # ----------------------------------------------------------------------
        authority_score = 1.0
        if case.expected_governing_doc_ids and citations:
            cited_doc_ids = [str(c.get("document_id") or "") for c in citations]
            cited_titles = [str(c.get("document_title") or "") for c in citations]
            has_governing_cited = any(
                exp in cited_doc_ids or any(exp.lower() in t.lower() for t in cited_titles)
                for exp in case.expected_governing_doc_ids
            )
            if not has_governing_cited:
                authority_score = 0.0
                diagnostics.append(f"Governing doc {case.expected_governing_doc_ids} not found in primary citations.")

        # ----------------------------------------------------------------------
        # Dimension 4: Temporal Applicability
        # ----------------------------------------------------------------------
        temporal_score = 1.0
        if case.permitted_caveats:
            has_permitted_caveat = any(c.lower() in answer_text.lower() for c in case.permitted_caveats)
            if not has_permitted_caveat:
                temporal_score = 0.5
                diagnostics.append("Expected material caveat omitted from response.")

        # ----------------------------------------------------------------------
        # Dimension 5: Citation Support
        # ----------------------------------------------------------------------
        citation_score = 1.0
        if case.expected_state in ["supported", "qualified"]:
            if not citations and case.candidate_evidence:
                citation_score = 0.0
                diagnostics.append("Zero citations returned for supported governance state.")
            elif citations:
                # Check for proving passage content
                has_substantive_passages = all(len(c.get("passage", "").strip()) >= 10 for c in citations)
                if not has_substantive_passages:
                    citation_score = 0.5
                    diagnostics.append("Citation missing substantive source passage.")
        elif case.expected_state in ["denied", "no_knowledge"]:
            if citations:
                citation_score = 0.0
                diagnostics.append("Security Invariant Violated: Citations present in denied/no_knowledge state.")

        # ----------------------------------------------------------------------
        # Dimension 6: Relevance & Negative Pruning
        # ----------------------------------------------------------------------
        relevance_score = 1.0
        for exc in case.expected_excluded_docs:
            exc_title = exc.get("title", "")
            if any(exc_title.lower() in str(c.get("document_title", "")).lower() for c in citations):
                relevance_score = 0.0
                diagnostics.append(f"Excluded document '{exc_title}' ({exc.get('reason')}) was improperly cited.")

        # ----------------------------------------------------------------------
        # Dimension 7: Concise Presentation
        # ----------------------------------------------------------------------
        concise_score = 1.0
        # Check sentence count in default answer
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', answer_text) if len(s.strip()) > 5]
        if len(sentences) > 4:
            concise_score = 0.5
            diagnostics.append(f"Answer exceeds concise contract ({len(sentences)} sentences).")

        # Invariant: No internal execution diagnostics in default text
        if any(term in answer_text for term in ["latency_ms", "tokens_total", "l7_permission", "reason_codes"]):
            concise_score = 0.0
            diagnostics.append("Internal governance diagnostics leaked into default answer text.")

        # ----------------------------------------------------------------------
        # Dimension 8: Permission Enforcement
        # ----------------------------------------------------------------------
        permission_score = 1.0
        if case.user_role == "member":
            if "$500,000" in answer_text or any("Executive Compensation" in str(c.get("document_title")) for c in citations):
                permission_score = 0.0
                diagnostics.append("Restricted executive compensation data leaked to member role.")
        if case.is_cross_tenant:
            if "Flight Guidance" in answer_text or citations:
                permission_score = 0.0
                diagnostics.append("Cross-tenant document leaked into external tenant query.")

        # Overall weighted score
        weights = {
            "correctness": 0.25,
            "completeness": 0.20,
            "authority": 0.15,
            "temporal": 0.10,
            "citations": 0.10,
            "relevance": 0.10,
            "conciseness": 0.05,
            "permission": 0.05
        }
        overall_score = (
            correctness_score * weights["correctness"] +
            completeness_score * weights["completeness"] +
            authority_score * weights["authority"] +
            temporal_score * weights["temporal"] +
            citation_score * weights["citations"] +
            relevance_score * weights["relevance"] +
            concise_score * weights["conciseness"] +
            permission_score * weights["permission"]
        )

        # Status determination
        if overall_score >= 0.95 and correctness_score == 1.0 and completeness_score == 1.0:
            status = "PASS"
        elif overall_score >= 0.70 and correctness_score >= 0.5:
            status = "PARTIAL"
        else:
            status = "FAIL"

        # Citation support checks
        citations_directly_support = (citation_score >= 0.8)
        evidence_duplicated_or_irrelevant = (relevance_score < 1.0)

        scoring_dict = {
            "answer_correctness": round(correctness_score, 2),
            "completeness": round(completeness_score, 2),
            "source_authority": round(authority_score, 2),
            "temporal_applicability": round(temporal_score, 2),
            "citation_support": round(citation_score, 2),
            "relevance": round(relevance_score, 2),
            "concise_presentation": round(concise_score, 2),
            "permission_enforcement": round(permission_score, 2)
        }

        return BenchmarkExecutionRecord(
            test_id=case.test_id,
            group=case.group,
            group_name=case.group_name,
            query=case.query,
            expected_facts=case.expected_facts,
            permitted_caveats=case.permitted_caveats,
            expected_governing_doc_ids=case.expected_governing_doc_ids,
            expected_excluded_docs=case.expected_excluded_docs,
            actual_answer=answer_text,
            actual_evidence=citations,
            answer_state=state,
            governance_decision=directive,
            all_requested_facts_present=has_all_facts,
            citations_directly_support=citations_directly_support,
            evidence_duplicated_or_irrelevant=evidence_duplicated_or_irrelevant,
            scoring=scoring_dict,
            overall_score=round(overall_score, 3),
            status=status,
            latency_ms=round(latency_ms, 2),
            diagnostics=diagnostics
        )


# ==============================================================================
# BENCHMARK RUNNER
# ==============================================================================

class BenchmarkRunner:
    @classmethod
    def run_all(cls) -> Tuple[List[BenchmarkExecutionRecord], Dict[str, Any]]:
        cases = build_benchmark_test_cases()
        records: List[BenchmarkExecutionRecord] = []

        # Setup standard mock objects for workspace and organizations
        org = Organization.objects.filter(slug="northstar-digital").first()
        if not org:
            org = Organization.objects.create(name="Northstar Digital", slug=f"northstar-{uuid.uuid4().hex[:6]}")
        ws = Workspace.objects.filter(organization=org, slug="governance-security").first()
        if not ws:
            ws = Workspace.objects.create(organization=org, name="Governance Security", slug=f"gov-sec-{uuid.uuid4().hex[:6]}")
        member_user, _ = User.objects.get_or_create(username="benchmark_member_user")

        t_start_suite = time.time()

        for case in cases:
            t0 = time.time()
            try:
                # Handle special permission filtering case setup
                current_chunks = list(case.candidate_evidence)
                if case.test_id == "BENCH-K02":
                    doc_pub = SourceDocument.objects.create(
                        organization=org, workspace=ws, title="General IT Handbook",
                        original_filename="handbook.pdf", mime_type="application/pdf",
                        file_size=1024, file_hash=f"hash-pub-{uuid.uuid4().hex[:6]}",
                        status="ready", authority_level=4
                    )
                    doc_res = SourceDocument.objects.create(
                        organization=org, workspace=ws, title="Executive Compensation Confidential",
                        original_filename="exec.pdf", mime_type="application/pdf",
                        file_size=2048, file_hash=f"hash-res-{uuid.uuid4().hex[:6]}",
                        status="ready", authority_level=7
                    )
                    SourcePermission.objects.create(
                        document=doc_res,
                        access_level=AccessLevel.RESTRICTED,
                        allowed_roles=["workspace_admin"]
                    )
                    current_chunks[0]["document_id"] = str(doc_pub.id)
                    current_chunks[1]["document_id"] = str(doc_res.id)

                req = GovernanceRequest(
                    workspace=ws,
                    organization=org,
                    principal=member_user,
                    user_role=case.user_role,
                    query=case.query,
                    candidate_evidence=current_chunks,
                    as_of=case.as_of
                )
                envelope = EnterpriseGovernanceEngine.evaluate(req)
                latency = (time.time() - t0) * 1000

                rec = BenchmarkEvaluator.evaluate_test_case(case, envelope, latency)
                records.append(rec)
            except Exception as e:
                latency = (time.time() - t0) * 1000
                rec = BenchmarkExecutionRecord(
                    test_id=case.test_id,
                    group=case.group,
                    group_name=case.group_name,
                    query=case.query,
                    expected_facts=case.expected_facts,
                    permitted_caveats=case.permitted_caveats,
                    expected_governing_doc_ids=case.expected_governing_doc_ids,
                    expected_excluded_docs=case.expected_excluded_docs,
                    actual_answer="",
                    actual_evidence=[],
                    answer_state="blocked",
                    governance_decision="stop",
                    all_requested_facts_present=False,
                    citations_directly_support=False,
                    evidence_duplicated_or_irrelevant=False,
                    scoring={k: 0.0 for k in [
                        "answer_correctness", "completeness", "source_authority",
                        "temporal_applicability", "citation_support", "relevance",
                        "concise_presentation", "permission_enforcement"
                    ]},
                    overall_score=0.0,
                    status="BLOCKED",
                    latency_ms=latency,
                    diagnostics=[f"Execution crash: {str(e)}"]
                )
                records.append(rec)

        total_latency = time.time() - t_start_suite

        # Aggregate summary metrics
        total_tests = len(records)
        pass_count = sum(1 for r in records if r.status == "PASS")
        partial_count = sum(1 for r in records if r.status == "PARTIAL")
        fail_count = sum(1 for r in records if r.status == "FAIL")
        blocked_count = sum(1 for r in records if r.status == "BLOCKED")

        dim_keys = [
            "answer_correctness", "completeness", "source_authority",
            "temporal_applicability", "citation_support", "relevance",
            "concise_presentation", "permission_enforcement"
        ]
        dimensional_averages = {
            dim: round(sum(r.scoring[dim] for r in records) / max(total_tests, 1), 3)
            for dim in dim_keys
        }
        avg_score = round(sum(r.overall_score for r in records) / max(total_tests, 1), 3)

        summary = {
            "total_tests": total_tests,
            "pass_count": pass_count,
            "partial_count": partial_count,
            "fail_count": fail_count,
            "blocked_count": blocked_count,
            "pass_rate_pct": round((pass_count / max(total_tests, 1)) * 100, 1),
            "average_overall_score": avg_score,
            "dimensional_averages": dimensional_averages,
            "total_suite_latency_s": round(total_latency, 2)
        }

        return records, summary

    @classmethod
    def save_results(
        cls,
        records: List[BenchmarkExecutionRecord],
        summary: Dict[str, Any],
        output_path: str
    ) -> None:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        data = {
            "version": "1.0.0",
            "benchmark_suite": "LORE Enterprise Multi-Dimensional Regression Benchmark",
            "timestamp": datetime.now(dt_timezone.utc).isoformat(),
            "summary": summary,
            "records": [asdict(r) for r in records]
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# ==============================================================================
# CLI EXECUTION ENTRYPOINT
# ==============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print(" LORE ENTERPRISE — REPEATABLE REGRESSION BENCHMARK")
    print("=" * 80)

    records, summary = BenchmarkRunner.run_all()

    output_json_path = os.path.join(
        BASE_DIR, "tests", "data", "lore_regression_benchmark_results.json"
    )
    BenchmarkRunner.save_results(records, summary, output_json_path)

    print(f"\nBenchmark completed across {summary['total_tests']} tests in {summary['total_suite_latency_s']}s.")
    print(f"Results saved to: {output_json_path}\n")

    print("-" * 80)
    print(f"RESULTS BY TEST CASE:")
    print("-" * 80)
    print(f"{'ID':<10} | {'Group':<30} | {'State':<12} | {'Score':<6} | {'Status'}")
    print("-" * 80)
    for r in records:
        print(f"{r.test_id:<10} | {r.group_name:<30} | {r.answer_state:<12} | {r.overall_score:<6.2f} | {r.status}")

    print("-" * 80)
    print(f"SUMMARY METRICS:")
    print(f"  Total Tests:       {summary['total_tests']}")
    print(f"  Pass:              {summary['pass_count']} ({summary['pass_rate_pct']}%)")
    print(f"  Partial:           {summary['partial_count']}")
    print(f"  Fail:              {summary['fail_count']}")
    print(f"  Blocked:           {summary['blocked_count']}")
    print(f"  Average Score:     {summary['average_overall_score']}")
    print("\nDIMENSIONAL AVERAGES:")
    for dim, score in summary['dimensional_averages'].items():
        print(f"  - {dim:<25}: {score:.3f}")
    print("=" * 80 + "\n")
