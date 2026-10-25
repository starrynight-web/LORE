import re

PREAMBLE_PATTERNS = [
    r'^(?:what\s+is\s+the|what\s+are\s+the|what\s+is|what\s+are|what\s+does\s+the|what\s+does|what\s+do|what\s+can)\s+',
    r'^(?:can\s+you\s+explain|can\s+you\s+tell\s+me|can\s+we|can\s+i|could\s+you\s+explain|could\s+you)\s+',
    r'^(?:tell\s+me\s+about|explain\s+the|explain\s+to\s+me|explain|describe\s+the|describe)\s+',
    r'^(?:summarize\s+the|summarize|give\s+me\s+the|give\s+me|show\s+me\s+the|show\s+me)\s+',
    r'^(?:how\s+do\s+we|how\s+do\s+i|how\s+to|how\s+does|how\s+is|how\s+can)\s+',
    r'^(?:is\s+there\s+a|is\s+it\s+allowed\s+to|are\s+there|is\s+there)\s+',
    r'^(?:please\s+provide|please\s+explain|please\s+tell\s+me|please)\s+',
    r'^(?:rules\s+regarding|rules\s+for|policy\s+regarding|policy\s+on|guidelines\s+for)\s+',
]

COMMON_DOMAINS = [
    ("travel", "Travel Expense Policy"),
    ("meal allowance", "Meal Allowance & Per Diem"),
    ("procurement", "Procurement Approval Limits"),
    ("access-control", "Access-Control Logging"),
    ("logging", "Audit Logging & Monitoring"),
    ("encryption", "Data Encryption Standard"),
    ("retention", "Document Retention Schedule"),
    ("remote work", "Remote Work Policy"),
    ("vendor", "Vendor Risk Management"),
    ("cloud", "Cloud Storage Governance"),
    ("sovereignty", "Data Sovereignty & Residency"),
]

def generate_conversation_title(query: str, max_length: int = 50) -> str:
    """
    Generates a concise, deterministic conversation title from the first user inquiry.
    Avoids inventing facts, hallucinating, or leaking sensitive secret tokens.
    """
    if not query or not query.strip():
        return "New Conversation"

    clean = query.strip()

    # Check for strong matching common governance domains first
    lower_q = clean.lower()
    for keyword, domain_title in COMMON_DOMAINS:
        if keyword in lower_q and ("policy" in lower_q or "standard" in lower_q or "rule" in lower_q or "what" in lower_q):
            return domain_title

    # Strip conversational prefixes
    working = clean
    for pat in PREAMBLE_PATTERNS:
        working = re.sub(pat, '', working, flags=re.IGNORECASE).strip()

    # Strip leading articles ('the', 'a', 'an')
    working = re.sub(r'^(?:the|a|an)\s+', '', working, flags=re.IGNORECASE).strip()

    # Strip punctuation at end and start
    working = re.sub(r'[?!.,;:\'"]+$', '', working).strip()
    working = re.sub(r'^[?!.,;:\'"]+', '', working).strip()

    if not working:
        return "Governed Inquiry"

    # Normalize whitespace
    working = re.sub(r'\s+', ' ', working)

    # Capitalize appropriately (Title Case)
    words = working.split(' ')
    capitalized_words = []
    lowercase_minor = {'and', 'or', 'the', 'a', 'an', 'in', 'on', 'at', 'for', 'to', 'of', 'with', 'by'}

    for idx, w in enumerate(words):
        if idx > 0 and w.lower() in lowercase_minor:
            capitalized_words.append(w.lower())
        else:
            capitalized_words.append(w.capitalize())

    candidate = " ".join(capitalized_words)

    # Bound length cleanly without cutting words
    if len(candidate) <= max_length:
        return candidate

    truncated = candidate[:max_length]
    if ' ' in truncated:
        truncated = truncated.rsplit(' ', 1)[0]
    return f"{truncated}..."
