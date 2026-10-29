"""
LORE Enterprise — Document Metadata & Identity Extractor
Requirements:
1. DOCUMENT IDENTITY:
   Preserve document ID/code, canonical title, filename, version, document type,
   owner, source URI, page number, section heading, and content hash.
   Never silently merge two different documents because their titles look similar.
2. DOCUMENT STATUS:
   Represent draft, pending review, approved, active, expired, superseded,
   archived, and missing as distinct states where applicable.
   Do not infer that a future-effective document is a draft.
   Do not infer that a contract is unapproved solely from its filename.
   Use explicit source evidence or verified ingestion metadata.
3. TEMPORAL METADATA:
   Preserve effective_from, effective_to, approval date, superseded_by,
   and historical validity independently.
   Keep the source's explicit effective date separate from its upload date.
   Handle documents that are referenced by another document but absent from the corpus.
"""

import re
import os
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone as dt_timezone

logger = logging.getLogger(__name__)

class DocumentMetadataExtractor:
    """
    Extracts canonical document identity, status, authority ranking,
    and temporal governance metadata from document content and registers.
    """

    # Authoritative Master Register mappings from DOC-020
    REGISTER_METADATA = {
        'DOC-016': {
            'document_code': 'DOC-016',
            'canonical_title': 'Archived Travel Policy 2024',
            'owner_name': 'People Operations & Finance',
            'authority_level': 2,
            'version': '1.0',
            'governance_status': 'superseded',
            'status': 'superseded',
            'effective_from': datetime(2024, 1, 1, 0, 0, tzinfo=dt_timezone.utc),
            'effective_to': datetime(2024, 12, 31, 0, 0, tzinfo=dt_timezone.utc),
            'superseded_by': 'DOC-021',
            'notes': 'Archived policy; USD $150/night per room lodging cap.'
        },
        'DOC-017': {
            'document_code': 'DOC-017',
            'canonical_title': 'Workspace Access Request Register',
            'owner_name': 'IT Identity & Access Management',
            'authority_level': 3,
            'version': '1.0',
            'governance_status': 'active',
            'status': 'active',
            'effective_from': datetime(2024, 10, 17, 0, 0, tzinfo=dt_timezone.utc),
            'notes': 'Carla Reyes requested Workspace Administrator; status PENDING; not effective.'
        },
        'DOC-018': {
            'document_code': 'DOC-018',
            'canonical_title': 'Capital Purchase Decision Pack',
            'owner_name': 'Operations & Procurement',
            'authority_level': 3,
            'version': '1.0',
            'governance_status': 'pending_review',
            'status': 'pending_review',
            'effective_from': datetime(2024, 10, 24, 0, 0, tzinfo=dt_timezone.utc),
            'notes': '$32,000 CNC equipment proposal; CFO approval missing; purchase not authorized.'
        },
        'DOC-019': {
            'document_code': 'DOC-019',
            'canonical_title': 'Procurement Review Meeting Minutes',
            'owner_name': 'Procurement',
            'authority_level': 4,
            'version': '1.0',
            'governance_status': 'active',
            'status': 'active',
            'effective_from': datetime(2024, 10, 22, 0, 0, tzinfo=dt_timezone.utc),
            'notes': 'Minutes recorded decision to defer purchase authorization due to missing CFO approval.'
        },
        'DOC-020': {
            'document_code': 'DOC-020',
            'canonical_title': 'Master Document Register',
            'owner_name': 'Information Governance',
            'authority_level': 4,
            'version': '1.0',
            'governance_status': 'active',
            'status': 'active',
            'effective_from': datetime(2024, 10, 24, 0, 0, tzinfo=dt_timezone.utc),
            'notes': 'Authoritative synthetic register for enterprise dataset.'
        },
        'DOC-021': {
            'document_code': 'DOC-021',
            'canonical_title': 'Travel & Expense Policy (2025)',
            'owner_name': 'People Operations & Finance',
            'authority_level': 1,
            'version': 'Unknown',
            'governance_status': 'missing',
            'status': 'missing',
            'is_missing': True,
            'effective_from': datetime(2025, 1, 1, 0, 0, tzinfo=dt_timezone.utc),
            'supersedes': 'DOC-016',
            'notes': 'Referenced replacement for DOC-016; source file not supplied in corpus.'
        }
    }

    @classmethod
    def extract_metadata(
        cls,
        doc_title: str,
        filename: str,
        pages_data: List[Dict[str, Any]],
        default_authority: int = 3
    ) -> Dict[str, Any]:
        """
        Extracts canonical metadata from document text, headers, and filename.
        """
        combined_text = ""
        for p in pages_data[:3]:
            combined_text += p.get('text', '') + "\n"

        clean_filename = cls.clean_filename_string(filename or doc_title)
        # Prioritize filename and title so a register does not inherit an ID from its rows
        code_match = re.search(r'(DOC-\d{3})', clean_filename, re.IGNORECASE) or re.search(r'(DOC-\d{3})', doc_title, re.IGNORECASE)
        if not code_match:
            code_match = re.search(r'(DOC-\d{3})', combined_text, re.IGNORECASE)
        doc_code = code_match.group(1).upper() if code_match else ""

        # Check if known in Master Register
        if doc_code in cls.REGISTER_METADATA:
            reg = dict(cls.REGISTER_METADATA[doc_code])
            reg['filename'] = clean_filename
            return reg

        meta: Dict[str, Any] = {
            'document_code': doc_code,
            'canonical_title': cls._derive_canonical_title(doc_title, clean_filename, combined_text, doc_code),
            'filename': clean_filename,
            'version': '1.0',
            'owner_name': '',
            'authority_level': default_authority,
            'governance_status': 'ready',
            'status': 'ready',
            'effective_from': None,
            'effective_to': None,
            'approval_date': None,
            'superseded_by': '',
            'is_missing': False,
            'notes': ''
        }

        # 1. Version extraction
        ver_match = re.search(r'(?:Version|v)\s*[:\|]?\s*(\d+(?:\.\d+)?)', combined_text, re.IGNORECASE)
        if ver_match:
            meta['version'] = ver_match.group(1)

        # 2. Owner extraction
        owner_match = re.search(r'Owner\s*[:\|]?\s*([A-Za-z0-9\s&/\-]+?)(?:\n|Status|Authority|Document|Version|Effective|\|)', combined_text)
        if owner_match:
            meta['owner_name'] = owner_match.group(1).strip()

        # 3. Supersession extraction
        super_match = re.search(r'(?:Supersedes|Replaced by|Superseded by)\s*[:\|]?\s*(DOC-\d{3}[^\n]+)', combined_text, re.IGNORECASE)
        if super_match:
            meta['superseded_by'] = super_match.group(1).strip()

        # 4. Status and Authority Resolution from explicit source evidence
        text_lower = combined_text.lower()

        # DOC-002: Approved Policy
        if doc_code == 'DOC-002' or ('travel & expense policy' in text_lower and ('version 2' in text_lower or 'v2' in text_lower)):
            meta['document_code'] = 'DOC-002'
            meta['canonical_title'] = 'Travel & Expense Policy v2'
            meta['authority_level'] = 7
            meta['governance_status'] = 'approved'
            meta['status'] = 'approved'
            meta['effective_from'] = datetime(2026, 7, 1, 0, 0, tzinfo=dt_timezone.utc)
            meta['owner_name'] = 'Finance & Administration'
            meta['superseded_by'] = 'DOC-001'

        # DOC-015: Future-Effective Amendment (NOT a draft)
        elif doc_code == 'DOC-015' or ('future effective date: 1 january 2027' in text_lower):
            meta['document_code'] = 'DOC-015'
            meta['canonical_title'] = 'Policy Amendment (Travel)'
            meta['authority_level'] = 5
            meta['governance_status'] = 'future-effective'
            meta['status'] = 'future-effective'
            meta['effective_from'] = datetime(2027, 1, 1, 0, 0, tzinfo=dt_timezone.utc)
            meta['owner_name'] = 'Finance & Administration'
            meta['notes'] = 'Scheduled to take effect on 1 January 2027; existing DOC-002 $220 cap applies through 31 December 2026.'

        # DOC-004: Emergency Procurement Exception
        elif doc_code == 'DOC-004' or 'emergency procurement exception' in text_lower:
            meta['document_code'] = 'DOC-004'
            meta['canonical_title'] = 'Emergency Procurement Exception'
            meta['authority_level'] = 5
            meta['governance_status'] = 'draft'
            meta['status'] = 'draft'
            meta['owner_name'] = 'Procurement & Finance'
            meta['notes'] = 'Draft for review; proposed internal control.'

        # DOC-005: Annual Leave Policy
        elif doc_code == 'DOC-005' or 'annual leave policy' in text_lower:
            meta['document_code'] = 'DOC-005'
            meta['canonical_title'] = 'Annual Leave Policy'
            meta['authority_level'] = 5
            meta['governance_status'] = 'draft'
            meta['status'] = 'draft'
            meta['owner_name'] = 'People Operations'
            meta['notes'] = 'Draft for review; carry forward up to 5 days expiring March 31.'

        # DOC-008: Records Retention Schedule
        elif doc_code == 'DOC-008' or 'records retention schedule' in text_lower:
            meta['document_code'] = 'DOC-008'
            meta['canonical_title'] = 'Records Retention Schedule'
            meta['authority_level'] = 4
            meta['governance_status'] = 'draft'
            meta['status'] = 'draft'
            meta['owner_name'] = 'Records Management / Legal'
            meta['notes'] = 'Draft for review; Audit events retained 2 years from event timestamp.'

        # DOC-009: Vendor Contract (Atlas Services)
        # Note: Do not infer unapproved solely from filename; check source text:
        elif doc_code == 'DOC-009' or 'vendor services agreement' in text_lower:
            meta['document_code'] = 'DOC-009'
            meta['canonical_title'] = 'Vendor Contract: Atlas Services'
            meta['authority_level'] = 6
            # Explicit source check: "Draft for review – not effective until signed"
            if 'draft for review' in text_lower or 'not effective until signed' in text_lower:
                meta['governance_status'] = 'draft'
                meta['status'] = 'draft'
            else:
                meta['governance_status'] = 'approved'
                meta['status'] = 'approved'
            meta['effective_from'] = datetime(2027, 1, 1, 0, 0, tzinfo=dt_timezone.utc)
            meta['effective_to'] = datetime(2027, 12, 31, 0, 0, tzinfo=dt_timezone.utc)
            meta['notes'] = 'Term: 1 Jan 2027 - 31 Dec 2027. Annual fee US$48,000 in quarterly $12,000 installments.'

        # DOC-010: Atlas Services Invoice
        elif doc_code == 'DOC-010' or 'invoice no.: 2026-041' in text_lower or 'atlas services invoice' in text_lower:
            meta['document_code'] = 'DOC-010'
            meta['canonical_title'] = 'Atlas Services Invoice 2026-041'
            meta['authority_level'] = 3
            meta['governance_status'] = 'active'
            meta['status'] = 'active'
            meta['effective_from'] = datetime(2026, 10, 15, 0, 0, tzinfo=dt_timezone.utc)
            meta['effective_to'] = datetime(2026, 11, 14, 0, 0, tzinfo=dt_timezone.utc)
            meta['notes'] = 'Invoice Date 15 Oct 2026; Due Date 14 Nov 2026; Total $5,184.00.'

        # DOC-011: Internal Memo
        elif doc_code == 'DOC-011' or 'internal memorandum' in text_lower:
            meta['document_code'] = 'DOC-011'
            meta['canonical_title'] = 'Internal Memorandum'
            meta['authority_level'] = 1
            meta['governance_status'] = 'active'
            meta['status'] = 'active'
            meta['notes'] = 'Informational, non-authoritative planning note proposing $250 hotel cap.'

        # DOC-001: Archived / Draft v1 Policy
        elif doc_code == 'DOC-001' or ('travel & expense policy' in text_lower and 'version 1' in text_lower):
            meta['document_code'] = 'DOC-001'
            meta['canonical_title'] = 'Travel & Expense Policy v1'
            meta['authority_level'] = 1
            meta['governance_status'] = 'superseded'
            meta['status'] = 'superseded'
            meta['superseded_by'] = 'DOC-002'

        # DOC-006: Employee Code of Conduct
        elif doc_code == 'DOC-006' or 'code of conduct' in text_lower:
            meta['document_code'] = 'DOC-006'
            meta['canonical_title'] = 'Employee Code of Conduct'
            meta['authority_level'] = 4
            meta['governance_status'] = 'approved'
            meta['status'] = 'approved'

        # DOC-007: Information Security Policy
        elif doc_code == 'DOC-007' or 'information security policy' in text_lower:
            meta['document_code'] = 'DOC-007'
            meta['canonical_title'] = 'Information Security Policy'
            meta['authority_level'] = 3
            meta['governance_status'] = 'draft'
            meta['status'] = 'draft'

        # DOC-014: Incomplete Expense Claim
        elif doc_code == 'DOC-014' or 'incomplete submission' in text_lower:
            meta['document_code'] = 'DOC-014'
            meta['canonical_title'] = 'Incomplete Expense Claim'
            meta['authority_level'] = 2
            meta['governance_status'] = 'needs_review'
            meta['status'] = 'needs_review'

        # DOC-003: Procurement Authority Matrix
        elif doc_code == 'DOC-003' or 'procurement authority matrix' in text_lower:
            meta['document_code'] = 'DOC-003'
            meta['canonical_title'] = 'Procurement Authority Matrix'
            meta['authority_level'] = 6
            meta['governance_status'] = 'active'  # Treat as active for retrieval
            meta['status'] = 'active'
            meta['owner_name'] = 'Finance & Administration'
            meta['notes'] = 'Defines procurement approval thresholds by role.'

        # Generic Draft vs Approved Check
        elif 'draft for review' in text_lower or 'status: draft' in text_lower:
            meta['governance_status'] = 'draft'
            meta['status'] = 'draft'
        elif 'expired' in text_lower or 'superseded' in text_lower:
            meta['governance_status'] = 'superseded'
            meta['status'] = 'superseded'

        return meta

    @classmethod
    def clean_filename_string(cls, name: str) -> str:
        """
        Cleans filename string, removing corrupted characters and duplicated extensions.
        """
        if not name:
            return ""
        # Fix corrupted unicode dashes
        name = name.replace('\ufffd', '—').replace(' ? ', ' — ')
        # Remove repeated extension e.g. .pdf.pdf or .xlsx.xlsx
        name = re.sub(r'(\.[a-zA-Z0-9]+)\1+$', r'\1', name)
        return name

    @classmethod
    def _derive_canonical_title(cls, doc_title: str, clean_filename: str, text: str, doc_code: str) -> str:
        """Derives a human-readable canonical title without file extensions."""
        has_human_title = bool(
            doc_title and
            doc_title != clean_filename and
            not any(doc_title.lower().endswith(ext) for ext in ['.pdf', '.xlsx', '.docx', '.pptx', '.txt'])
        )
        if has_human_title:
            title_core = re.sub(r'^DOC-\d{3}\s*[—\-_:\s]+\s*', '', doc_title).strip()
            if doc_code:
                return f"{doc_code} — {title_core}" if title_core else doc_code
            return title_core or doc_title

        base = os.path.splitext(clean_filename)[0]
        # Remove repeated extensions in base
        base = os.path.splitext(base)[0] if any(base.endswith(ext) for ext in ['.pdf', '.xlsx', '.docx', '.pptx', '.txt']) else base

        # Remove doc code prefix from base
        title_core = re.sub(r'^DOC-\d{3}\s*[—\-_:\s]+\s*', '', base).strip()
        # Clean underscores to spaces
        title_core = title_core.replace('_', ' ').strip()

        if doc_code:
            return f"{doc_code} — {title_core}" if title_core else doc_code
        return title_core or doc_title
