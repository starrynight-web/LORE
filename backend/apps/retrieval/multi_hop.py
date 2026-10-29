"""
LORE Enterprise — Multi-Hop Retrieval Engine
Implements query decomposition, parallel sub-query retrieval, and provenance-tagged fusion.
"""
import re
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from .query_understanding import QueryUnderstandingService, QueryAnalysis

logger = logging.getLogger(__name__)


@dataclass
class SubQuery:
    """A decomposed sub-query with its own retrieval context."""
    id: str                          # e.g., "sub_a_procurement"
    text: str                        # The actual sub-query text
    domain: str                      # e.g., "procurement", "annual_leave"
    target_doc_codes: List[str]      # Inferred target documents
    companion_docs: List[str]        # Required companion documents
    role_label: str                  # Human-readable role for provenance


@dataclass
class MultiHopResult:
    """Result of multi-hop retrieval with provenance tracking."""
    sub_query: SubQuery
    chunks: List[Dict[str, Any]]
    retrieval_mode: str              # "hybrid", "graph_expanded", etc.
    total_ms: int


class QueryDecomposer:
    """
    Detects compound queries and splits them into independent sub-queries.
    Uses pattern matching + QueryUnderstandingService for domain inference.
    """
    
    # Patterns that indicate compound queries
    COMPOUND_PATTERNS = [
        r'\band\b.*\b(also|additionally|furthermore|moreover|in addition)\b',
        r'\b(also|additionally|furthermore|moreover)\b.*\band\b',
        r'\bshe\b.*\b(he|they)\b.*\b(also|additionally)\b',  # Multi-subject
        r'\b(both|two|separate|multiple)\b.*\b(issues|questions|requests|needs)\b',
        r'\.\s+(He|She|They|It)\b.*\b(also|additionally|furthermore|moreover)\b',
        r'\b(purchase|procurement)\b.*\b(and|\+)\b.*\b(leave|vacation|pto)\b',
        r'\b(leave|vacation|pto)\b.*\b(and|\+)\b.*\b(purchase|procurement)\b',
    ]
    
    # Domain keyword clusters for splitting
    DOMAIN_CLUSTERS = {
        'procurement': ['purchase', 'procurement', 'buy', 'supplier', 'vendor', 'rfp', 
                       'quote', 'equipment', 'cnc', 'milling', '$', 'usd', 'cost'],
        'annual_leave': ['leave', 'vacation', 'holiday', 'pto', 'time off', 'carryover',
                        'carry forward', 'blackout', 'inventory count', 'fiscal year'],
        'travel_lodging': ['hotel', 'lodging', 'accommodation', 'nightly cap', 'room rate'],
        'travel_meals': ['meal', 'meals', 'breakfast', 'lunch', 'dinner', 'per diem'],
        'travel_receipts': ['receipt', 'receipts', 'lost receipt', 'itemized'],
        'records_retention': ['retention', 'retain', 'preservation', 'audit log', 'schedule'],
        'security_access': ['access', 'permission', 'workspace', 'carla reyes', 'alice morgan'],
        'emergency_procurement': ['emergency', 'outage', 'bypass', 'critical', 'urgent'],
        'expense_claim': ['expense', 'claim', 'reimbursement', 'submission', '15 days'],
    }

    DOMAIN_DEFAULT_DOCS = {
        'procurement': ['DOC-003'],
        'annual_leave': ['DOC-005'],
        'travel_lodging': ['DOC-002'],
        'travel_meals': ['DOC-002'],
        'travel_receipts': ['DOC-002'],
        'records_retention': ['DOC-008'],
        'security_access': ['DOC-017'],
        'emergency_procurement': ['DOC-004'],
        'expense_claim': ['DOC-002', 'DOC-014'],
    }
    
    @classmethod
    def is_compound_query(cls, query: str) -> bool:
        """Detect if a query contains multiple independent sub-questions."""
        q_lower = query.lower()
        
        # Check compound patterns
        for pattern in cls.COMPOUND_PATTERNS:
            if re.search(pattern, q_lower):
                return True
        
        # Check for multiple domain clusters
        detected_domains = cls._detect_domains(q_lower)
        if len(detected_domains) >= 2:
            return True
        
        # Check for multiple question marks or explicit multi-part phrasing
        if q_lower.count('?') >= 2:
            return True
        
        if any(p in q_lower for p in ['what all', 'and what', 'also need to know', 
                                       'both the', 'two questions']):
            return True
        
        return False
    
    @classmethod
    def _detect_domains(cls, text: str) -> List[str]:
        """Detect which domain clusters are present in the text."""
        detected = []
        text_lower = text.lower()
        for domain, keywords in cls.DOMAIN_CLUSTERS.items():
            if any(kw in text_lower for kw in keywords):
                detected.append(domain)
        
        # Disambiguate emergency_procurement vs pure procurement
        if 'emergency_procurement' in detected and 'procurement' in detected:
            non_emergency_text = re.sub(r'\bemergency\s+procurement\b', '', text_lower)
            if not any(kw in non_emergency_text for kw in ['purchase', 'buy', 'supplier', 'quote', 'equipment', '$', 'usd']):
                detected.remove('procurement')
                
        return detected
    
    @classmethod
    def decompose(cls, query: str, base_analysis: QueryAnalysis) -> List[SubQuery]:
        """
        Decompose a compound query into independent sub-queries.
        Each sub-query gets its own domain inference and target docs.
        """
        if not cls.is_compound_query(query):
            # Not compound — return single sub-query
            return [SubQuery(
                id="single",
                text=query,
                domain=base_analysis.subject_domain,
                target_doc_codes=base_analysis.all_target_doc_codes,
                companion_docs=base_analysis.required_companion_docs,
                role_label="primary"
            )]
        
        sub_queries = []
        q_lower = query.lower()
        
        # Strategy 1: Split by domain clusters
        detected_domains = cls._detect_domains(q_lower)
        
        if len(detected_domains) >= 2:
            for i, domain in enumerate(detected_domains):
                # Extract the portion of the query relevant to this domain
                sub_text = cls._extract_domain_portion(query, domain)
                if not sub_text:
                    sub_text = query  # Fallback to full query
                
                # Run QueryUnderstanding on the sub-query
                sub_analysis = QueryUnderstandingService.analyze(sub_text)
                target_docs = list(sub_analysis.all_target_doc_codes)
                for default_doc in cls.DOMAIN_DEFAULT_DOCS.get(domain, []):
                    if default_doc not in target_docs:
                        target_docs.append(default_doc)
                
                sub_queries.append(SubQuery(
                    id=f"sub_{chr(65+i)}_{domain}",
                    text=sub_text,
                    domain=domain,
                    target_doc_codes=target_docs,
                    companion_docs=sub_analysis.required_companion_docs,
                    role_label=domain
                ))
        
        # Strategy 2: Split by sentence boundaries if domain split failed
        if len(sub_queries) < 2:
            sentences = re.split(r'[.!?]\s+|\band\b(?=\s+(?:she|he|they|it)\b)', query, flags=re.IGNORECASE)
            sentences = [s.strip() for s in sentences if len(s.strip()) > 15]
            
            if len(sentences) >= 2:
                for i, sent in enumerate(sentences[:3]):  # Max 3 sub-queries
                    sub_analysis = QueryUnderstandingService.analyze(sent)
                    sub_queries.append(SubQuery(
                        id=f"sub_{chr(65+i)}_sentence",
                        text=sent,
                        domain=sub_analysis.subject_domain,
                        target_doc_codes=sub_analysis.all_target_doc_codes,
                        companion_docs=sub_analysis.required_companion_docs,
                        role_label=sub_analysis.subject_domain
                    ))
        
        # Fallback: if decomposition failed, return original query
        if not sub_queries:
            return [SubQuery(
                id="single",
                text=query,
                domain=base_analysis.subject_domain,
                target_doc_codes=base_analysis.all_target_doc_codes,
                companion_docs=base_analysis.required_companion_docs,
                role_label="primary"
            )]
        
        return sub_queries
    
    @classmethod
    def _extract_domain_portion(cls, query: str, domain: str) -> str:
        """Extract the portion of the query most relevant to a domain."""
        keywords = cls.DOMAIN_CLUSTERS.get(domain, [])
        sentences = re.split(r'[.!?]\s+|\s+and\s+|\s+also\s+|\s+but\s+|\s*\+\s*', query, flags=re.IGNORECASE)
        
        relevant_sentences = []
        for sent in sentences:
            sent_lower = sent.lower()
            if any(kw in sent_lower for kw in keywords):
                relevant_sentences.append(sent.strip())
        
        return " ".join(relevant_sentences) if relevant_sentences else query

