import os
import django
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lore_enterprise.settings')
django.setup()

from apps.sources.models import SourceDocument
from apps.knowledge.models import DocumentChunk

# Target authority ranks based on document type and Master Document Register (DOC-020)
# Approved Policy: 7, Contract: 6, Procedure/Schedule/Register: 4, Review/Proposal/Minutes: 3, Historical: 2, Informal: 1
AUTHORITY_MAP = {
    'DOC-001': (1, 'DOC-001 — Travel_Expense_Policy_v1.pdf'),
    'DOC-002': (7, 'DOC-002 — Travel_Expense_Policy_v2.pdf'),
    'DOC-003': (3, 'DOC-003 — Procurement_Authority_Matrix.xlsx'),
    'DOC-004': (3, 'DOC-004 — Emergency_Procurement_Exception.pdf'),
    'DOC-005': (3, 'DOC-005 — Annual_Leave_Policy.pdf'),
    'DOC-006': (7, 'DOC-006 — Employee_Code_of_Conduct.docx'),
    'DOC-007': (3, 'DOC-007 — Information_Security_Policy.pdf'),
    'DOC-008': (4, 'DOC-008 — Records_Retention_Schedule.xlsx'),
    'DOC-009': (6, 'DOC-009 — Vendor_Contract_Atlas_Services.pdf'),
    'DOC-010': (3, 'DOC-010 — Atlas_Invoice_2026_041.pdf'),
    'DOC-011': (1, 'DOC-011 — Travel_Team_Internal_Memo.pdf'),
    'DOC-012': (3, 'DOC-012 — Supplier_Quotes_Q3.xlsx'),
    'DOC-014': (2, 'DOC-014 — Incomplete_Expense_Claim.pdf'),
    'DOC-015': (3, 'DOC-015 — Travel_Policy_Amendment_Future.pdf'),
    'DOC-016': (2, 'DOC-016_Archived_Travel_Policy_2024.pdf'),
    'DOC-017': (3, 'DOC-017_Workspace_Access_Request.docx'),
    'DOC-018': (3, 'DOC-018_Capital_Purchase_Decision_Pack.pdf'),
    'DOC-019': (3, 'DOC-019_Procurement_Review_Minutes.docx'),
    'DOC-020': (4, 'DOC-020_Master_Document_Register.xlsx'),
}

for doc in SourceDocument.objects.all():
    matched = False
    for code, (rank, clean_name) in AUTHORITY_MAP.items():
        if code in doc.title or code in doc.original_filename:
            doc.title = clean_name
            doc.authority_level = rank
            doc.save(update_fields=['title', 'authority_level'])
            matched = True
            
            # Update chunks
            for chk in DocumentChunk.objects.filter(document=doc):
                header = chk.contextual_header or ""
                header = re.sub(r'Authority Rank:\s*\d+', f'Authority Rank: {rank}', header)
                header = re.sub(r'Document:\s*[^|]+', f'Document: {clean_name} ', header)
                chk.contextual_header = header
                chk.save(update_fields=['contextual_header'])
            print(f"Updated {code} -> rank={rank}, title='{clean_name}'")
            break
    if not matched:
        print(f"No match for doc: {doc.title}")

print("Document reconciliation completed.")
