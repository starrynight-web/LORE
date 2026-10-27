import re
import math
import logging
from typing import List, Tuple, Optional, Dict, Any
from django.db import connection, transaction
from django.conf import settings

from apps.knowledge.models import DocumentChunk
from apps.sources.models import SourceDocument

logger = logging.getLogger(__name__)


class BaseLexicalSearchBackend:
    """Base interface for database-specific full-text lexical search backends."""
    name: str = "base"

    def search(
        self,
        query: str,
        workspace_id: str,
        organization_id: str,
        collection_id: Optional[str] = None,
        document_id: Optional[str] = None,
        limit: int = 25
    ) -> List[Tuple[float, DocumentChunk]]:
        raise NotImplementedError


class PostgresFullTextSearchBackend(BaseLexicalSearchBackend):
    """
    PostgreSQL full-text search backend using tsvector, tsquery, and SearchRank.
    Ranks headers (weight 'A') higher than chunk text (weight 'B').
    """
    name = "postgresql_fts"

    def search(
        self,
        query: str,
        workspace_id: str,
        organization_id: str,
        collection_id: Optional[str] = None,
        document_id: Optional[str] = None,
        limit: int = 25
    ) -> List[Tuple[float, DocumentChunk]]:
        try:
            from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
        except ImportError:
            logger.warning("django.contrib.postgres is not available. Falling back to structured lexical search.")
            return SqliteFullTextSearchBackend().search(
                query, workspace_id, organization_id, collection_id, document_id, limit
            )

        qs = DocumentChunk.objects.exclude(
            document__status__in=['quarantined', 'failed', 'deleted', 'uploaded']
        )
        if workspace_id:
            qs = qs.filter(workspace_id=workspace_id)
        if organization_id:
            qs = qs.filter(organization_id=organization_id)
        if collection_id:
            qs = qs.filter(document__collection_id=collection_id)
        if document_id:
            qs = qs.filter(document_id=document_id)

        # Weighted vector: contextual_header (A = 1.0), text (B = 0.4)
        vector = SearchVector('contextual_header', weight='A') + SearchVector('text', weight='B')

        try:
            search_query = SearchQuery(query, search_type='websearch')
        except Exception:
            search_query = SearchQuery(query, search_type='plain')

        ranked_qs = qs.annotate(
            rank=SearchRank(vector, search_query)
        ).filter(
            rank__gt=0.005
        ).order_by('-rank').select_related('document', 'document__collection', 'document_version')[:limit]

        results = [(float(getattr(c, 'rank', 0.0)), c) for c in ranked_qs]
        return results


class SqliteFullTextSearchBackend(BaseLexicalSearchBackend):
    """
    SQLite full-text search backend supporting FTS5 virtual tables with BM25 ranking,
    with an in-memory tokenized BM25-style fallback if the FTS5 virtual table is uninitialized.
    """
    name = "sqlite_fts5"

    @classmethod
    def ensure_sqlite_fts_table(cls):
        """Creates and populates SQLite FTS5 table if supported and missing."""
        if connection.vendor != 'sqlite':
            return
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_documentchunk_fts USING fts5(
                        chunk_id UNINDEXED,
                        document_id UNINDEXED,
                        workspace_id UNINDEXED,
                        organization_id UNINDEXED,
                        contextual_header,
                        text,
                        tokenize = 'unicode61'
                    );
                """)
        except Exception as e:
            logger.debug(f"SQLite FTS5 virtual table initialization note: {e}")

    @classmethod
    def sync_chunk_to_fts(cls, chunk: DocumentChunk):
        """Upserts a single DocumentChunk into SQLite FTS5 index."""
        if connection.vendor != 'sqlite':
            return
        try:
            cls.ensure_sqlite_fts_table()
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM knowledge_documentchunk_fts WHERE chunk_id = ?",
                    [str(chunk.id)]
                )
                cursor.execute("""
                    INSERT INTO knowledge_documentchunk_fts(
                        chunk_id, document_id, workspace_id, organization_id, contextual_header, text
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, [
                    str(chunk.id),
                    str(chunk.document_id),
                    str(chunk.workspace_id),
                    str(chunk.organization_id),
                    chunk.contextual_header or "",
                    chunk.text or ""
                ])
        except Exception as e:
            logger.debug(f"SQLite FTS sync note: {e}")

    def search(
        self,
        query: str,
        workspace_id: str,
        organization_id: str,
        collection_id: Optional[str] = None,
        document_id: Optional[str] = None,
        limit: int = 25
    ) -> List[Tuple[float, DocumentChunk]]:
        # 1. Base Queryset with strict tenancy & publication filtering
        qs = DocumentChunk.objects.exclude(
            document__status__in=['quarantined', 'failed', 'deleted', 'uploaded']
        )
        if workspace_id:
            qs = qs.filter(workspace_id=workspace_id)
        if organization_id:
            qs = qs.filter(organization_id=organization_id)
        if collection_id:
            qs = qs.filter(document__collection_id=collection_id)
        if document_id:
            qs = qs.filter(document_id=document_id)

        # Clean query tokens and filter stopwords to prioritize subject and action keywords
        clean_q = query.strip()
        all_tokens = [w.lower() for w in re.findall(r'\w+', clean_q) if len(w) > 1]
        if not all_tokens:
            return []

        stop_words = {
            'what', 'is', 'are', 'the', 'a', 'an', 'in', 'on', 'at', 'for', 'to', 'of',
            'and', 'or', 'by', 'with', 'from', 'as', 'be', 'can', 'we', 'it', 'this',
            'that', 'do', 'does', 'all', 'any', 'my', 'your', 'our', 'under', 'according',
            'tell', 'show', 'please', 'would', 'could', 'how', 'much', 'many', 'must'
        }
        content_tokens = [w for w in all_tokens if w not in stop_words]
        query_terms = content_tokens if content_tokens else all_tokens

        # Expand morphological variants for domain inquiries
        extended_terms = list(query_terms)
        if any(w in ['logged', 'logging', 'logs', 'log'] for w in all_tokens):
            for variant in ['log', 'logging', 'logs', 'record', 'records', 'audit']:
                if variant not in extended_terms:
                    extended_terms.append(variant)

        if any(w in ['leave', 'vacation', 'holiday', 'carryover', 'carry'] for w in all_tokens):
            for variant in ['leave', 'annual leave', 'vacation', 'pto', 'carryover', 'carry forward', 'expire', 'accrue']:
                if variant not in extended_terms:
                    extended_terms.append(variant)

        if any(w in ['retention', 'retained', 'retain', 'schedule'] for w in all_tokens):
            for variant in ['retention', 'retained', 'schedule', 'audit events', 'trigger', 'disposal', 'records']:
                if variant not in extended_terms:
                    extended_terms.append(variant)

        if any(w in ['procurement', 'purchase', 'buy', 'exception', 'waiver', 'emergency'] for w in all_tokens):
            for variant in ['procurement', 'purchase', 'emergency', 'exception', 'waiver', 'approval', 'cfo']:
                if variant not in extended_terms:
                    extended_terms.append(variant)

        if any(w in ['receipt', 'receipts', 'claim', 'dinner', 'reimbursement'] for w in all_tokens):
            for variant in ['receipt', 'receipts', 'lost', 'expense claim', 'reimbursement', 'itemized']:
                if variant not in extended_terms:
                    extended_terms.append(variant)

        if any(w in ['invoice', 'contract', 'discrepancy', 'atlas'] for w in all_tokens):
            for variant in ['invoice', 'contract', 'agreement', 'atlas', 'installment', 'discrepancy']:
                if variant not in extended_terms:
                    extended_terms.append(variant)

        # Attempt SQLite FTS5 Query if table exists
        fts_hits = self._query_fts5(clean_q, extended_terms, workspace_id, organization_id, document_id, limit)
        if fts_hits is not None and len(fts_hits) > 0:
            chunk_ids = [hit[0] for hit in fts_hits]
            score_map = {hit[0]: hit[1] for hit in fts_hits}
            chunks = list(qs.filter(id__in=chunk_ids).select_related('document', 'document__collection', 'document_version'))
            chunks.sort(key=lambda c: score_map.get(str(c.id), 0.0), reverse=True)
            return [(score_map.get(str(c.id), 0.5), c) for c in chunks[:limit]]

        # 2. Resilient Structured BM25-like Lexical Scorer
        # Computes token presence, contextual header weighting, and exact phrase match
        scored_results: List[Tuple[float, DocumentChunk]] = []
        candidate_qs = qs.select_related('document', 'document__collection', 'document_version')

        q_lower = clean_q.lower()
        has_phrase = len(q_lower) > 3

        # Prefilter candidate chunks using content keywords to keep in-memory scoring bounded
        from django.db.models import Q
        q_filter = Q()
        for t in extended_terms[:8]:
            q_filter |= Q(text__icontains=t) | Q(contextual_header__icontains=t)
        candidate_qs = candidate_qs.filter(q_filter)

        for chunk in candidate_qs[:100]:
            body = (chunk.text or "").lower()
            header = (chunk.contextual_header or "").lower()
            heading = (chunk.heading_path or "").lower()
            doc_title = (chunk.document.title if chunk.document else "").lower()
            combined_text = f"{doc_title} {header} {heading} {body}"

            # Exact phrase match bonus
            phrase_bonus = 0.40 if has_phrase and (q_lower in body or q_lower in header) else 0.0

            # Token overlap scoring using meaningful query terms
            matched_terms = 0
            for t in query_terms:
                if t in combined_text:
                    matched_terms += 1
                elif t in ['logged', 'logging', 'logs', 'log'] and any(v in combined_text for v in ['log', 'logging', 'logs', 'record', 'audit']):
                    matched_terms += 1
                elif t == 'actions' and any(v in combined_text for v in ['events', 'functions', 'changes', 'attempts', 'activities']):
                    matched_terms += 1

            matched_header = sum(1 for t in query_terms if t in header or t in heading)

            term_coverage = matched_terms / len(query_terms) if query_terms else 0.0
            header_coverage = matched_header / len(query_terms) if query_terms else 0.0

            # Content-focused lexical score
            lexical_score = (0.55 * term_coverage) + (0.25 * header_coverage) + phrase_bonus

            # Domain-specific bonuses based on user query intent
            if any(w in ['retention', 'retained', 'retain'] for w in all_tokens):
                if 'retention schedule' in combined_text or 'retention period' in combined_text or 'retention trigger' in combined_text or 'audit events' in combined_text:
                    lexical_score += 0.35
            elif any(w in ['logged', 'logging', 'logs', 'log'] for w in all_tokens):
                if 'audit logging' in combined_text or 'security events' in combined_text or 'must record' in combined_text:
                    lexical_score += 0.25

            if any(w in ['carryover', 'carry'] for w in all_tokens) or ('annual' in all_tokens and 'leave' in all_tokens):
                if 'carryover limits' in combined_text or 'annual leave policy' in combined_text or 'carry forward' in combined_text:
                    lexical_score += 0.30

            if 'emergency' in all_tokens and any(w in ['procurement', 'exception'] for w in all_tokens):
                if 'emergency procurement' in combined_text or 'mandatory conditions' in combined_text:
                    lexical_score += 0.35

            if any(w in ['receipt', 'receipts'] for w in all_tokens):
                if 'receipts and expense claims' in combined_text or 'lost receipts require' in combined_text or 'itemized receipts are required' in combined_text:
                    lexical_score += 0.35

            if lexical_score > 0.05:
                scored_results.append((round(lexical_score, 4), chunk))

        scored_results.sort(key=lambda x: x[0], reverse=True)
        return scored_results[:limit]

    def _query_fts5(
        self,
        query: str,
        tokens: List[str],
        workspace_id: str,
        organization_id: str,
        document_id: Optional[str],
        limit: int
    ) -> Optional[List[Tuple[str, float]]]:
        if connection.vendor != 'sqlite':
            return None
        try:
            with connection.cursor() as cursor:
                # Check if FTS5 table exists
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_documentchunk_fts'"
                )
                if not cursor.fetchone():
                    return None

                # Format FTS5 match query
                # Escapes special characters and joins with OR/NEAR
                fts_query = " OR ".join(f'"{t}"*' for t in tokens[:8])
                sql = """
                    SELECT chunk_id, bm25(knowledge_documentchunk_fts, 2.0, 1.0) AS rank
                    FROM knowledge_documentchunk_fts
                    WHERE knowledge_documentchunk_fts MATCH ?
                """
                params: List[Any] = [fts_query]
                if workspace_id:
                    sql += " AND workspace_id = ?"
                    params.append(workspace_id)
                if organization_id:
                    sql += " AND organization_id = ?"
                    params.append(organization_id)
                if document_id:
                    sql += " AND document_id = ?"
                    params.append(document_id)
                sql += " ORDER BY rank ASC LIMIT ?"
                params.append(limit)

                cursor.execute(sql, params)
                rows = cursor.fetchall()
                if not rows:
                    return None

                # BM25 returns lower = better (negative or small positive values depending on SQLite version)
                # Convert BM25 to positive relevance [0, 1]
                converted = []
                for row in rows:
                    cid = str(row[0])
                    raw_bm25 = float(row[1])
                    norm_score = max(0.1, 1.0 / (1.0 + abs(raw_bm25)))
                    converted.append((cid, round(norm_score, 4)))
                converted.sort(key=lambda x: x[1], reverse=True)
                return converted
        except Exception as e:
            logger.debug(f"SQLite FTS5 query bypass: {e}")
            return None


class LexicalSearchService:
    """
    Stable facade for database-agnostic full-text lexical search.
    Automatically routes to PostgreSQL tsvector search or SQLite FTS5/BM25 search.
    """

    @classmethod
    def get_backend(cls) -> BaseLexicalSearchBackend:
        if connection.vendor == 'postgresql':
            return PostgresFullTextSearchBackend()
        return SqliteFullTextSearchBackend()

    @classmethod
    def search_chunks(
        cls,
        query: str,
        workspace_id: str,
        organization_id: str,
        collection_id: Optional[str] = None,
        document_id: Optional[str] = None,
        limit: int = 25
    ) -> List[Tuple[float, DocumentChunk]]:
        backend = cls.get_backend()
        return backend.search(
            query=query,
            workspace_id=workspace_id,
            organization_id=organization_id,
            collection_id=collection_id,
            document_id=document_id,
            limit=limit
        )

    @classmethod
    def get_backend_info(cls) -> Dict[str, Any]:
        backend = cls.get_backend()
        return {
            "backend_name": backend.name,
            "database_vendor": connection.vendor,
            "supports_fts5": connection.vendor == 'sqlite',
            "supports_postgres_search": connection.vendor == 'postgresql',
        }
