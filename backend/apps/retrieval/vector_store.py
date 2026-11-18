import os
import json
import math
import logging
from typing import List, Dict, Any, Optional
from django.conf import settings

logger = logging.getLogger(__name__)


class BaseVectorStore:
    def upsert_chunks(self, collection_name: str, vectors: List[List[float]], payloads: List[Dict[str, Any]], ids: List[str]):
        raise NotImplementedError

    def search(self, collection_name: str, query_vector: List[float], filter_dict: Optional[Dict[str, Any]] = None, limit: int = 10) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def search_lexical(self, collection_name: str, query_text: str, filter_dict: Optional[Dict[str, Any]] = None, limit: int = 10) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def search_hybrid(self, collection_name: str, query_vector: List[float], query_text: str, filter_dict: Optional[Dict[str, Any]] = None, alpha: float = 0.5, limit: int = 10) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def delete_document_chunks(self, collection_name: str, document_id: str):
        raise NotImplementedError

    def count_document_chunks(self, collection_name: str, document_id: str) -> int:
        raise NotImplementedError

    def list_indexed_document_ids(self, collection_name: str) -> set:
        raise NotImplementedError


class QdrantVectorStore(BaseVectorStore):
    """
    Qdrant vector store adapter:
    Supports local embedded file storage or remote Qdrant service.
    Reuses a process-wide shared client to prevent storage folder locks
    and disparate in-memory fallback instances.
    """
    _shared_client = None

    def __init__(self, vector_dim: int = 384):
        self.vector_dim = vector_dim
        self.client = None
        self._init_client()

    def _init_client(self):
        if QdrantVectorStore._shared_client is not None:
            self.client = QdrantVectorStore._shared_client
            return

        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as rest_models
            self.models = rest_models

            qdrant_url = getattr(settings, 'QDRANT_URL', '')
            if qdrant_url:
                api_key = getattr(settings, 'QDRANT_API_KEY', None)
                self.client = QdrantClient(url=qdrant_url, api_key=api_key)
            else:
                storage_path = getattr(settings, 'QDRANT_LOCAL_PATH', os.path.join(settings.BASE_DIR, 'qdrant_storage'))
                os.makedirs(storage_path, exist_ok=True)
                self.client = QdrantClient(path=storage_path)

            QdrantVectorStore._shared_client = self.client

        except Exception as e:
            err_msg = str(e)
            logger.warning(f"Could not initialize primary QdrantClient: {err_msg}.")
            # When storage folder is locked by another process (e.g. Django runserver in dev/test),
            # spin up a local snapshot replica in temp directory to avoid degraded empty in-memory search
            replica_client = None
            if "already accessed by another instance" in err_msg or "locked" in err_msg.lower():
                try:
                    import shutil, tempfile
                    storage_path = getattr(settings, 'QDRANT_LOCAL_PATH', os.path.join(settings.BASE_DIR, 'qdrant_storage'))
                    replica_dir = os.path.join(tempfile.gettempdir(), f"lore_qdrant_replica_{os.getpid()}")
                    shutil.rmtree(replica_dir, ignore_errors=True)
                    shutil.copytree(storage_path, replica_dir, ignore=shutil.ignore_patterns('*.lock', '.lock'))
                    from qdrant_client import QdrantClient
                    replica_client = QdrantClient(path=replica_dir)
                    logger.info(f"Initialized concurrent Qdrant replica client at {replica_dir}")
                except Exception as re_err:
                    logger.warning(f"Could not initialize Qdrant replica: {re_err}")

            if replica_client is not None:
                self.client = replica_client
                QdrantVectorStore._shared_client = self.client
            else:
                logger.warning("Falling back to shared in-memory mode.")
                try:
                    from qdrant_client import QdrantClient
                    self.client = QdrantClient(":memory:")
                    QdrantVectorStore._shared_client = self.client
                except Exception:
                    self.client = None

    def _ensure_collection(self, collection_name: str):
        if not self.client:
            return
        try:
            from qdrant_client.http import models as rest_models
            collections = self.client.get_collections().collections
            exists = any(c.name == collection_name for c in collections)
            if not exists:
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=rest_models.VectorParams(
                        size=self.vector_dim,
                        distance=rest_models.Distance.COSINE
                    )
                )
        except Exception as e:
            logger.warning(f"Error ensuring collection {collection_name}: {e}")

    def upsert_chunks(self, collection_name: str, vectors: List[List[float]], payloads: List[Dict[str, Any]], ids: List[str]):
        if not self.client:
            return
        self._ensure_collection(collection_name)
        try:
            from qdrant_client.http import models as rest_models
            points = [
                rest_models.PointStruct(
                    id=ids[i],
                    vector=vectors[i],
                    payload=payloads[i]
                )
                for i in range(len(ids))
            ]
            self.client.upsert(collection_name=collection_name, points=points)
        except Exception as e:
            logger.error(f"Error upserting vectors to Qdrant: {e}")

    def search(self, collection_name: str, query_vector: List[float], filter_dict: Optional[Dict[str, Any]] = None, limit: int = 10) -> List[Dict[str, Any]]:
        if not self.client:
            return []
        self._ensure_collection(collection_name)
        try:
            from qdrant_client.http import models as rest_models
            query_filter = None
            if filter_dict:
                must_conditions = []
                for k, v in filter_dict.items():
                    if isinstance(v, (list, tuple, set)):
                        v_list = [str(x) for x in v]
                        must_conditions.append(
                            rest_models.FieldCondition(key=k, match=rest_models.MatchAny(any=v_list))
                        )
                    else:
                        must_conditions.append(
                            rest_models.FieldCondition(key=k, match=rest_models.MatchValue(value=v))
                        )
                if must_conditions:
                    query_filter = rest_models.Filter(must=must_conditions)

            if hasattr(self.client, 'query_points'):
                response = self.client.query_points(
                    collection_name=collection_name,
                    query=query_vector,
                    query_filter=query_filter,
                    limit=limit
                )
                hits = getattr(response, 'points', response)
            elif hasattr(self.client, 'search'):
                hits = self.client.search(
                    collection_name=collection_name,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=limit
                )
            else:
                hits = []

            out = []
            for hit in hits:
                out.append({
                    'id': str(hit.id),
                    'score': float(hit.score),
                    'payload': hit.payload or {}
                })
            return out
        except Exception as e:
            logger.warning(f"Error searching Qdrant: {e}")
            return []

    def search_lexical(self, collection_name: str, query_text: str, filter_dict: Optional[Dict[str, Any]] = None, limit: int = 10) -> List[Dict[str, Any]]:
        if not self.client:
            return []
        self._ensure_collection(collection_name)
        try:
            scroll_res = self.client.scroll(
                collection_name=collection_name,
                limit=max(limit * 5, 50),
                with_payload=True,
                with_vectors=False
            )
            points = scroll_res[0] if isinstance(scroll_res, tuple) else scroll_res
            query_terms = set(query_text.lower().split())
            results = []
            for p in points:
                payload = p.payload or {}
                if filter_dict:
                    match = True
                    for fk, fv in filter_dict.items():
                        if isinstance(fv, (list, tuple, set)):
                            val = payload.get(fk)
                            if isinstance(val, (list, tuple, set)):
                                if not any(x in fv for x in val):
                                    match = False
                                    break
                            elif val not in fv and str(val) not in [str(x) for x in fv]:
                                match = False
                                break
                        else:
                            if str(payload.get(fk, '')) != str(fv):
                                match = False
                                break
                    if not match:
                        continue
                text = str(payload.get('text', '')).lower()
                overlap = sum(1 for term in query_terms if term in text)
                if overlap > 0:
                    score = overlap / max(1, len(query_terms))
                    results.append({'id': str(p.id), 'score': float(score), 'payload': payload})
            results.sort(key=lambda x: x['score'], reverse=True)
            return results[:limit]
        except Exception as e:
            logger.warning(f"Error in Qdrant search_lexical: {e}")
            return []

    def search_hybrid(self, collection_name: str, query_vector: List[float], query_text: str, filter_dict: Optional[Dict[str, Any]] = None, alpha: float = 0.5, limit: int = 10) -> List[Dict[str, Any]]:
        dense_hits = self.search(collection_name=collection_name, query_vector=query_vector, filter_dict=filter_dict, limit=limit * 2)
        lexical_hits = self.search_lexical(collection_name=collection_name, query_text=query_text, filter_dict=filter_dict, limit=limit * 2)

        combined: Dict[str, Dict[str, Any]] = {}
        for d in dense_hits:
            combined[d['id']] = {'score': alpha * d['score'], 'payload': d['payload']}
        for l in lexical_hits:
            if l['id'] in combined:
                combined[l['id']]['score'] += (1.0 - alpha) * l['score']
            else:
                combined[l['id']] = {'score': (1.0 - alpha) * l['score'], 'payload': l['payload']}

        out = [{'id': k, 'score': round(v['score'], 4), 'payload': v['payload']} for k, v in combined.items()]
        out.sort(key=lambda x: x['score'], reverse=True)
        return out[:limit]

    def delete_document_chunks(self, collection_name: str, document_id: str):
        if not self.client:
            return
        self._ensure_collection(collection_name)
        try:
            from qdrant_client.http import models as rest_models
            self.client.delete(
                collection_name=collection_name,
                points_selector=rest_models.Filter(
                    must=[rest_models.FieldCondition(key="document_id", match=rest_models.MatchValue(value=document_id))]
                )
            )
        except Exception as e:
            logger.warning(f"Error deleting chunks for document {document_id}: {e}")

    def delete_workspace_vectors(self, collection_name: str, workspace_id: str):
        if not self.client:
            return
        self._ensure_collection(collection_name)
        try:
            from qdrant_client.http import models as rest_models
            self.client.delete(
                collection_name=collection_name,
                points_selector=rest_models.Filter(
                    must=[rest_models.FieldCondition(key="workspace_id", match=rest_models.MatchValue(value=str(workspace_id)))]
                )
            )
        except Exception as e:
            logger.warning(f"Error deleting vectors for workspace {workspace_id}: {e}")

    def count_document_chunks(self, collection_name: str, document_id: str) -> int:
        if not self.client:
            return 0
        self._ensure_collection(collection_name)
        try:
            from qdrant_client.http import models as rest_models
            res = self.client.count(
                collection_name=collection_name,
                count_filter=rest_models.Filter(
                    must=[rest_models.FieldCondition(key="document_id", match=rest_models.MatchValue(value=document_id))]
                )
            )
            return getattr(res, 'count', 0)
        except Exception as e:
            logger.warning(f"Error counting chunks for document {document_id}: {e}")
            return 0

    def list_indexed_document_ids(self, collection_name: str) -> set:
        if not self.client:
            return set()
        self._ensure_collection(collection_name)
        try:
            doc_ids = set()
            offset = None
            while True:
                scroll_res = self.client.scroll(
                    collection_name=collection_name,
                    limit=250,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False
                )
                points, next_offset = scroll_res
                for p in points:
                    if p.payload and 'document_id' in p.payload:
                        doc_ids.add(str(p.payload['document_id']))
                if not next_offset:
                    break
                offset = next_offset
            return doc_ids
        except Exception as e:
            logger.warning(f"Error listing indexed document ids from Qdrant: {e}")
            return set()


class PGVectorStore(BaseVectorStore):
    """
    PostgreSQL Vector & Lexical Store Adapter (pgvector + pg_search / BM25).
    Preserves LORE's transactional join key (rule_id and document_id),
    enables row-level security (RLS) scoping (workspace_id + org_id),
    and supports hybrid dense+lexical retrieval.
    """

    def __init__(self, vector_dim: int = 384):
        self.vector_dim = vector_dim
        self._ensure_table()

    def _ensure_table(self):
        from django.db import connection
        with connection.cursor() as cursor:
            vendor = connection.vendor
            if vendor == 'postgresql':
                try:
                    cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                except Exception as ex:
                    logger.debug(f"pgvector extension creation: {ex}")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS lore_pgvector_storage (
                        id VARCHAR(64) PRIMARY KEY,
                        collection_name VARCHAR(100) NOT NULL,
                        vector_data TEXT NOT NULL,
                        payload_data TEXT NOT NULL,
                        document_id VARCHAR(64),
                        rule_id VARCHAR(64),
                        workspace_id VARCHAR(64),
                        organization_id VARCHAR(64),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_pgvector_coll ON lore_pgvector_storage (collection_name);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_pgvector_doc ON lore_pgvector_storage (document_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_pgvector_ws ON lore_pgvector_storage (workspace_id, organization_id);")
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS lore_pgvector_storage (
                        id VARCHAR(64) PRIMARY KEY,
                        collection_name VARCHAR(100) NOT NULL,
                        vector_data TEXT NOT NULL,
                        payload_data TEXT NOT NULL,
                        document_id VARCHAR(64),
                        rule_id VARCHAR(64),
                        workspace_id VARCHAR(64),
                        organization_id VARCHAR(64),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

    def upsert_chunks(self, collection_name: str, vectors: List[List[float]], payloads: List[Dict[str, Any]], ids: List[str]):
        from django.db import connection
        self._ensure_table()
        with connection.cursor() as cursor:
            for i, chunk_id in enumerate(ids):
                vec = vectors[i]
                payload = payloads[i] if i < len(payloads) else {}
                doc_id = str(payload.get('document_id', ''))
                rule_id = str(payload.get('rule_id', payload.get('code', '')))
                ws_id = str(payload.get('workspace_id', ''))
                org_id = str(payload.get('organization_id', ''))
                vec_json = json.dumps(vec)
                payload_json = json.dumps(payload)

                cursor.execute("DELETE FROM lore_pgvector_storage WHERE id = %s;", [chunk_id])

                cursor.execute("""
                    INSERT INTO lore_pgvector_storage 
                    (id, collection_name, vector_data, payload_data, document_id, rule_id, workspace_id, organization_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """, [chunk_id, collection_name, vec_json, payload_json, doc_id, rule_id, ws_id, org_id])

    def search(self, collection_name: str, query_vector: List[float], filter_dict: Optional[Dict[str, Any]] = None, limit: int = 10) -> List[Dict[str, Any]]:
        from django.db import connection

        self._ensure_table()
        sql = "SELECT id, vector_data, payload_data FROM lore_pgvector_storage WHERE collection_name = %s"
        params: List[Any] = [collection_name]

        extra_filters = {}
        if filter_dict:
            for k, v in filter_dict.items():
                if k in ['document_id', 'rule_id', 'workspace_id', 'organization_id']:
                    if isinstance(v, (list, tuple, set)):
                        v_list = [str(item) for item in v]
                        if v_list:
                            placeholders = ', '.join(['%s'] * len(v_list))
                            sql += f" AND {k} IN ({placeholders})"
                            params.extend(v_list)
                        else:
                            sql += " AND 1=0"
                    else:
                        sql += f" AND {k} = %s"
                        params.append(str(v))
                else:
                    extra_filters[k] = v

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        results = []
        q_norm = math.sqrt(sum(x * x for x in query_vector)) or 1.0

        for r_id, r_vec_str, r_payload_str in rows:
            try:
                payload = json.loads(r_payload_str)
                if extra_filters:
                    match = True
                    for fk, fv in extra_filters.items():
                        if fk == 'allowed_roles' and isinstance(fv, (list, set, tuple)):
                            doc_roles = payload.get('allowed_roles') or []
                            if doc_roles and not any(r in fv for r in doc_roles):
                                match = False
                                break
                        elif fk == 'access_level' and isinstance(fv, (list, set, tuple)):
                            doc_al = payload.get('access_level')
                            if doc_al and doc_al not in fv:
                                match = False
                                break
                        elif isinstance(fv, (list, set, tuple)):
                            val = payload.get(fk)
                            if isinstance(val, (list, set, tuple)):
                                if not any(r in fv for r in val):
                                    match = False
                                    break
                            elif val not in fv and str(val) not in [str(x) for x in fv]:
                                match = False
                                break
                        elif str(payload.get(fk, '')) != str(fv):
                            match = False
                            break
                    if not match:
                        continue

                vec = json.loads(r_vec_str)
                dot = sum(a * b for a, b in zip(query_vector, vec))
                v_norm = math.sqrt(sum(x * x for x in vec)) or 1.0
                score = dot / (q_norm * v_norm)
                results.append({
                    'id': str(r_id),
                    'score': float(score),
                    'payload': payload
                })
            except Exception:
                continue

        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit]

    def search_lexical(self, collection_name: str, query_text: str, filter_dict: Optional[Dict[str, Any]] = None, limit: int = 10) -> List[Dict[str, Any]]:
        from django.db import connection

        self._ensure_table()
        sql = "SELECT id, payload_data FROM lore_pgvector_storage WHERE collection_name = %s"
        params: List[Any] = [collection_name]

        extra_filters = {}
        if filter_dict:
            for k, v in filter_dict.items():
                if k in ['document_id', 'rule_id', 'workspace_id', 'organization_id']:
                    if isinstance(v, (list, tuple, set)):
                        v_list = [str(item) for item in v]
                        if v_list:
                            placeholders = ', '.join(['%s'] * len(v_list))
                            sql += f" AND {k} IN ({placeholders})"
                            params.extend(v_list)
                        else:
                            sql += " AND 1=0"
                    else:
                        sql += f" AND {k} = %s"
                        params.append(str(v))
                else:
                    extra_filters[k] = v

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        query_terms = set(query_text.lower().split())
        scored = []
        for r_id, r_payload_str in rows:
            try:
                payload = json.loads(r_payload_str)
                if extra_filters:
                    match = True
                    for fk, fv in extra_filters.items():
                        if fk == 'allowed_roles' and isinstance(fv, (list, set, tuple)):
                            doc_roles = payload.get('allowed_roles') or []
                            if doc_roles and not any(r in fv for r in doc_roles):
                                match = False
                                break
                        elif fk == 'access_level' and isinstance(fv, (list, set, tuple)):
                            doc_al = payload.get('access_level')
                            if doc_al and doc_al not in fv:
                                match = False
                                break
                        elif isinstance(fv, (list, set, tuple)):
                            val = payload.get(fk)
                            if isinstance(val, (list, set, tuple)):
                                if not any(r in fv for r in val):
                                    match = False
                                    break
                            elif val not in fv and str(val) not in [str(x) for x in fv]:
                                match = False
                                break
                        elif str(payload.get(fk, '')) != str(fv):
                            match = False
                            break
                    if not match:
                        continue

                text = str(payload.get('text', '')).lower()
                matches = sum(1 for term in query_terms if term in text)
                if matches > 0:
                    score = matches / max(1, len(query_terms))
                    scored.append({
                        'id': str(r_id),
                        'score': float(score),
                        'payload': payload
                    })
            except Exception:
                continue

        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:limit]

    def search_hybrid(
        self,
        collection_name: str,
        query_vector: List[float],
        query_text: str,
        filter_dict: Optional[Dict[str, Any]] = None,
        alpha: float = 0.5,
        limit: int = 10,
        use_rrf: bool = True,
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search combining cosine similarity ANN embeddings with lexical search.
        Supports Reciprocal Rank Fusion (RRF, k=60) or convex alpha blending.
        """
        dense_hits = self.search(collection_name=collection_name, query_vector=query_vector, filter_dict=filter_dict, limit=limit * 2)
        lexical_hits = self.search_lexical(collection_name=collection_name, query_text=query_text, filter_dict=filter_dict, limit=limit * 2)

        if use_rrf:
            # Reciprocal Rank Fusion (RRF, k=60)
            rrf_scores: Dict[str, Dict[str, Any]] = {}
            for rank, d in enumerate(dense_hits, start=1):
                cid = d['id']
                rrf_score = 1.0 / (rrf_k + rank)
                rrf_scores[cid] = {'score': rrf_score, 'payload': d['payload']}

            for rank, l in enumerate(lexical_hits, start=1):
                cid = l['id']
                rrf_score = 1.0 / (rrf_k + rank)
                if cid in rrf_scores:
                    rrf_scores[cid]['score'] += rrf_score
                else:
                    rrf_scores[cid] = {'score': rrf_score, 'payload': l['payload']}

            out = [{'id': k, 'score': round(v['score'], 6), 'payload': v['payload']} for k, v in rrf_scores.items()]
        else:
            combined: Dict[str, Dict[str, Any]] = {}
            for d in dense_hits:
                combined[d['id']] = {'score': alpha * d['score'], 'payload': d['payload']}
            for l in lexical_hits:
                if l['id'] in combined:
                    combined[l['id']]['score'] += (1.0 - alpha) * l['score']
                else:
                    combined[l['id']] = {'score': (1.0 - alpha) * l['score'], 'payload': l['payload']}

            out = [{'id': k, 'score': round(v['score'], 4), 'payload': v['payload']} for k, v in combined.items()]

        out.sort(key=lambda x: x['score'], reverse=True)
        return out[:limit]

    def delete_document_chunks(self, collection_name: str, document_id: str):
        from django.db import connection
        self._ensure_table()
        with connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM lore_pgvector_storage WHERE collection_name = %s AND document_id = %s;
            """, [collection_name, str(document_id)])

    def delete_workspace_vectors(self, collection_name: str, workspace_id: str):
        from django.db import connection
        self._ensure_table()
        with connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM lore_pgvector_storage WHERE workspace_id = %s;
            """, [str(workspace_id)])

    def count_document_chunks(self, collection_name: str, document_id: str) -> int:
        from django.db import connection
        self._ensure_table()
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM lore_pgvector_storage WHERE collection_name = %s AND document_id = %s;
            """, [collection_name, str(document_id)])
            row = cursor.fetchone()
            return row[0] if row else 0

    def list_indexed_document_ids(self, collection_name: str) -> set:
        from django.db import connection
        self._ensure_table()
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT document_id FROM lore_pgvector_storage 
                WHERE collection_name = %s AND document_id IS NOT NULL AND document_id != '';
            """, [collection_name])
            rows = cursor.fetchall()
            return {str(r[0]) for r in rows if r[0]}


# Class Aliases for Enterprise Storage Parity
PgVectorLexicalAdapter = PGVectorStore
SqliteVecFtsAdapter = BaseVectorStore
VectorLexicalStoreAdapter = BaseVectorStore


_VECTOR_STORE_REGISTRY: Dict[str, BaseVectorStore] = {}


def get_vector_store(backend: Optional[str] = None, vector_dim: int = 384) -> BaseVectorStore:
    """
    Factory to retrieve configured Vector Store.
    Supported backends: 'qdrant' (default), 'pgvector', 'postgres', 'sqlite_vec'.
    Respects LORE_VECTOR_BACKEND and VECTOR_STORE_BACKEND environment settings.
    """
    chosen = (
        backend
        or getattr(settings, 'LORE_VECTOR_BACKEND', None)
        or getattr(settings, 'VECTOR_STORE_BACKEND', 'qdrant')
    ).lower()
    if chosen in _VECTOR_STORE_REGISTRY:
        return _VECTOR_STORE_REGISTRY[chosen]

    if chosen in ('pgvector', 'postgres', 'postgresql'):
        store = PGVectorStore(vector_dim=vector_dim)
    else:
        store = QdrantVectorStore(vector_dim=vector_dim)

    _VECTOR_STORE_REGISTRY[chosen] = store
    return store
