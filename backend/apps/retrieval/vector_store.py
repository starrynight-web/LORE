import os
import logging
from typing import List, Dict, Any, Optional
from django.conf import settings

logger = logging.getLogger(__name__)

class BaseVectorStore:
    def upsert_chunks(self, collection_name: str, vectors: List[List[float]], payloads: List[Dict[str, Any]], ids: List[str]):
        raise NotImplementedError

    def search(self, collection_name: str, query_vector: List[float], filter_dict: Optional[Dict[str, Any]] = None, limit: int = 10) -> List[Dict[str, Any]]:
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
            logger.warning(f"Could not initialize QdrantClient: {e}. Falling back to shared in-memory mode.")
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

    def delete_document_chunks(self, collection_name: str, document_id: str):
        if not self.client:
            return
        self._ensure_collection(collection_name)
        try:
            from qdrant_client.http import models as rest_models
            self.client.delete(
                collection_name=collection_name,
                points_selector=rest_models.Filter(
                    must=[rest_models.FieldCondition(key="document_id", match=rest_models.MatchValue(value=str(document_id)))]
                )
            )
        except Exception as e:
            logger.warning(f"Error deleting chunks for document {document_id}: {e}")

    def count_document_chunks(self, collection_name: str, document_id: str) -> int:
        if not self.client:
            return 0
        self._ensure_collection(collection_name)
        try:
            from qdrant_client.http import models as rest_models
            res = self.client.count(
                collection_name=collection_name,
                count_filter=rest_models.Filter(
                    must=[rest_models.FieldCondition(key="document_id", match=rest_models.MatchValue(value=str(document_id)))]
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


