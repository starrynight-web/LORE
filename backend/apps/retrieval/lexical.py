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

        qs = DocumentChunk.objects.filter(
            document__status='ready'
        ).exclude(
            document__status__in=['quarantined', 'failed', 'needs_review', 'uploaded', 'draft', 'deleted', 'stale']
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

        results = [(float(c.rank), c) for c in ranked_qs]
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
        qs = DocumentChunk.objects.filter(
            document__status='ready'
        ).exclude(
            document__status__in=['quarantined', 'failed', 'needs_review', 'uploaded', 'draft', 'deleted', 'stale']
        )
        if workspace_id:
            qs = qs.filter(workspace_id=workspace_id)
        if organization_id:
            qs = qs.filter(organization_id=organization_id)
        if collection_id:
            qs = qs.filter(document__collection_id=collection_id)
        if document_id:
            qs = qs.filter(document_id=document_id)

        # Clean query tokens
        clean_q = query.strip()
        tokens = [w.lower() for w in re.findall(r'\w+', clean_q) if len(w) > 1]
        if not tokens:
            return []

        # Attempt SQLite FTS5 Query if table exists
        fts_hits = self._query_fts5(clean_q, tokens, workspace_id, organization_id, document_id, limit)
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

        # Prefilter candidate chunks using token matching to keep in-memory scoring bounded
        from django.db.models import Q
        q_filter = Q()
        for t in tokens[:6]:
            q_filter |= Q(text__icontains=t) | Q(contextual_header__icontains=t)
        candidate_qs = candidate_qs.filter(q_filter)

        for chunk in candidate_qs[:100]:
            body = (chunk.text or "").lower()
            header = (chunk.contextual_header or "").lower()
            heading = (chunk.heading_path or "").lower()

            # Exact phrase match bonus
            phrase_bonus = 0.40 if has_phrase and (q_lower in body or q_lower in header) else 0.0

            # Token overlap scoring
            matched_body = sum(1 for t in tokens if t in body)
            matched_header = sum(1 for t in tokens if t in header or t in heading)

            body_coverage = matched_body / len(tokens)
            header_coverage = matched_header / len(tokens)

            # Header is weighted higher than body
            lexical_score = (0.50 * body_coverage) + (0.35 * header_coverage) + phrase_bonus

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
                params = [fts_query]
                if workspace_id:
                    sql += " AND workspace_id = ?"
                    params.append(str(workspace_id))
                if organization_id:
                    sql += " AND organization_id = ?"
                    params.append(str(organization_id))
                if document_id:
                    sql += " AND document_id = ?"
                    params.append(str(document_id))
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
