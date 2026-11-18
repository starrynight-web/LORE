"""
LORE Enterprise - GLiNER Zero-Shot NER & High-Cosine Entity Resolution (docs/enterprise/fix/knowledge.md §2)
Resolves canonical entities across siloed documents, rules, and third-party tools:
- Links disparate mentions (e.g. Jira tickets, Confluence runbooks, vendor contract PDFs) to canonical nodes.
- Uses high-cosine semantic threshold (>0.92) to prevent false entity merges.
"""

import re
import math
import logging
import threading
from typing import List, Dict, Any, Optional, Tuple
from django.conf import settings
from django.db.models import Q
from apps.knowledge.models import (
    CanonicalEntity, KnowledgeItem, DocumentChunk,
    KnowledgeRelationship, RelationshipType, RelationshipApprovalStatus
)
from apps.knowledge.ontology import CanonicalEntityType

logger = logging.getLogger(__name__)


# GLiNER zero-shot labels mapped to LORE canonical ontology
GLINER_LABEL_TO_CANONICAL: Dict[str, str] = {
    "vendor": CanonicalEntityType.VENDOR.value,
    "software system": CanonicalEntityType.SYSTEM.value,
    "regulation": CanonicalEntityType.REGULATION.value,
    "component": CanonicalEntityType.COMPONENT.value,
    "technology": CanonicalEntityType.SYSTEM.value,
    "organizational role": CanonicalEntityType.ROLE.value,
}


# Standard regex and dictionary heuristics for zero-shot entity candidates
ENTITY_INDICATOR_PATTERNS = {
    CanonicalEntityType.VENDOR: [
        r"\b(?:AWS|Amazon Web Services|Google Cloud|GCP|Microsoft Azure|Azure|Stripe|Okta|Datadog|Snowflake|Twilio|Atlassian|Salesforce|Cloudflare|GitHub|GitLab)\b",
    ],
    CanonicalEntityType.REGULATION: [
        r"\b(?:GDPR|General Data Protection Regulation|HIPAA|SOC 2|SOC-2|ISO 27001|ISO/IEC 27001|PCI-DSS|PCI DSS|EU AI Act|CCPA|NIST 800-53|FedRAMP)\b",
    ],
    CanonicalEntityType.SYSTEM: [
        r"\b(?:production-k8s|billing-pipeline|auth-service|user-db|core-api|kafka-cluster|data-warehouse|analytics-lake|redis-cache)\b",
    ],
    CanonicalEntityType.DEPARTMENT: [
        r"\b(?:SecOps|Security Operations|DevOps|Legal & Compliance|Infra|Platform Engineering|Product Engineering|Human Resources|Finance)\b",
    ],
    CanonicalEntityType.ROLE: [
        r"\b(?:Data Protection Officer|DPO|CISO|Security Officer|System Administrator|DevOps Lead|Compliance Auditor|Database Admin)\b",
    ],
    CanonicalEntityType.DATA_ASSET: [
        r"\b(?:customer_pii|payment_tokens|credit_card_records|audit_logs|source_code_repo|user_credentials|health_records)\b",
    ],
}


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class EntityResolutionService:
    """
    Extracts, deduplicates, and links canonical enterprise entities across documents and rules.
    Enforces >0.92 cosine similarity for semantic entity linking.
    """

    SIMILARITY_THRESHOLD = 0.92

    _gliner_lock = threading.Lock()
    _shared_gliner_model = None
    _gliner_attempted = False

    @classmethod
    def _get_gliner_model(cls):
        """Thread-safe lazy loader for local zero-shot GLiNER model."""
        if cls._shared_gliner_model is not None:
            return cls._shared_gliner_model
        with cls._gliner_lock:
            if cls._shared_gliner_model is not None:
                return cls._shared_gliner_model
            if cls._gliner_attempted:
                return None
            cls._gliner_attempted = True
            try:
                from gliner import GLiNER
                model_name = getattr(settings, 'GLINER_MODEL_NAME', 'urchade/gliner_small-v2.1')
                try:
                    cls._shared_gliner_model = GLiNER.from_pretrained(model_name, local_files_only=True)
                except Exception:
                    cls._shared_gliner_model = GLiNER.from_pretrained(model_name, local_files_only=False)
                logger.info(f"[EntityResolution] Successfully initialized local GLiNER model '{model_name}'")
                return cls._shared_gliner_model
            except Exception as exc:
                logger.info(f"[EntityResolution] GLiNER initialization skipped/unavailable ({exc}), relying on regex taxonomy.")
                return None

    @classmethod
    def extract_mentions(cls, text: str) -> List[Dict[str, Any]]:
        """
        Zero-shot entity extraction via regex patterns and GLiNER pipeline fallback.
        """
        extracted = []
        seen = set()

        # 1. High-confidence regex indicator patterns
        for entity_type, patterns in ENTITY_INDICATOR_PATTERNS.items():
            for pat in patterns:
                for match in re.finditer(pat, text, re.IGNORECASE):
                    name = match.group(0).strip()
                    key = (entity_type.value, name.lower())
                    if key not in seen:
                        seen.add(key)
                        extracted.append({
                            "name": name,
                            "entity_type": entity_type.value,
                            "start": match.start(),
                            "end": match.end(),
                            "confidence": 0.95,
                        })

        # 2. General acronym / system identifier extraction heuristic (e.g. POL-SEC-01)
        general_matches = re.finditer(r"\b([A-Z]{3,}-[A-Z0-9]+(?:\.[0-9]+)?)\b", text)
        for gm in general_matches:
            val = gm.group(1).strip()
            key = (CanonicalEntityType.SYSTEM.value, val.lower())
            if key not in seen:
                seen.add(key)
                extracted.append({
                    "name": val,
                    "entity_type": CanonicalEntityType.SYSTEM.value,
                    "start": gm.start(),
                    "end": gm.end(),
                    "confidence": 0.88,
                })

        # 3. Neural Zero-Shot Entity Extraction via Local GLiNER
        gliner_model = cls._get_gliner_model()
        if gliner_model and text and text.strip():
            try:
                labels = list(GLINER_LABEL_TO_CANONICAL.keys())
                predictions = gliner_model.predict_entities(text[:2048], labels, threshold=0.45)
                for pred in predictions:
                    ent_text = pred.get("text", "").strip()
                    raw_label = pred.get("label", "").lower()
                    if not ent_text or len(ent_text) < 2:
                        continue
                    canonical_type = GLINER_LABEL_TO_CANONICAL.get(raw_label, CanonicalEntityType.SYSTEM.value)
                    key = (canonical_type, ent_text.lower())
                    if key not in seen:
                        seen.add(key)
                        extracted.append({
                            "name": ent_text,
                            "entity_type": canonical_type,
                            "start": pred.get("start", 0),
                            "end": pred.get("end", len(ent_text)),
                            "confidence": round(float(pred.get("score", 0.90)), 2),
                        })
            except Exception as exc:
                logger.debug(f"[EntityResolution] GLiNER inference warning: {exc}")

        return extracted

    @classmethod
    def resolve_and_link_entity(
        cls,
        workspace,
        organization,
        entity_name: str,
        entity_type: str,
        embedding: Optional[List[float]] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Tuple[CanonicalEntity, bool]:
        """
        Resolves entity_name against existing CanonicalEntity nodes in workspace:
        1. Exact canonical name or alias match
        2. High-cosine embedding match (> 0.92)
        3. If no match found, creates a new CanonicalEntity node.
        """
        clean_name = entity_name.strip()
        canonical_name = clean_name.lower()

        # 1. Exact canonical name match within workspace
        existing = CanonicalEntity.objects.filter(
            workspace=workspace,
            organization=organization,
            entity_type=entity_type,
            canonical_name=canonical_name,
        ).first()

        if existing:
            return existing, False

        # Check aliases
        from django.db import connection
        alias_match = None
        if connection.vendor == 'postgresql':
            alias_match = CanonicalEntity.objects.filter(
                workspace=workspace,
                organization=organization,
                entity_type=entity_type,
                aliases__contains=[clean_name],
            ).first()
        else:
            for cand in CanonicalEntity.objects.filter(
                workspace=workspace,
                organization=organization,
                entity_type=entity_type,
            ):
                if clean_name in (cand.aliases or []):
                    alias_match = cand
                    break

        if alias_match:
            return alias_match, False

        # Attempt local embedding if not provided for semantic matching
        if embedding is None:
            try:
                from apps.retrieval.embeddings import get_embedding_adapter
                adapter = get_embedding_adapter()
                if hasattr(adapter, 'embed_text'):
                    embedding = adapter.embed_text(clean_name)
            except Exception:
                embedding = None

        # 2. Embedding similarity matching (> 0.92)
        if embedding:
            candidates = CanonicalEntity.objects.filter(
                workspace=workspace,
                organization=organization,
                entity_type=entity_type,
            ).exclude(embedding=[])

            for cand in candidates:
                cand_vec = cand.embedding
                sim = _cosine_similarity(embedding, cand_vec)
                if sim >= cls.SIMILARITY_THRESHOLD:
                    # Append as alias and reuse canonical entity
                    if clean_name not in cand.aliases:
                        cand.aliases.append(clean_name)
                        cand.save(update_fields=["aliases"])
                    return cand, False

        # 3. Create new canonical entity
        new_entity = CanonicalEntity.objects.create(
            workspace=workspace,
            organization=organization,
            entity_type=entity_type,
            name=clean_name,
            canonical_name=canonical_name,
            aliases=[clean_name],
            embedding=embedding or [],
            properties=properties or {},
        )
        return new_entity, True

    @classmethod
    def link_document_entities(
        cls,
        document,
        workspace,
        organization,
    ) -> List[Dict[str, Any]]:
        """
        Scans document text, resolves canonical entities, and creates KnowledgeRelationship edges.
        """
        from apps.sources.models import SourceDocument

        text = getattr(document, "raw_text", "") or getattr(document, "content", "") or document.title
        mentions = cls.extract_mentions(text)
        linked_results = []

        for m in mentions:
            entity, created = cls.resolve_and_link_entity(
                workspace=workspace,
                organization=organization,
                entity_name=m["name"],
                entity_type=m["entity_type"],
            )

            # Link document -> entity via APPLIES_TO relationship
            rel, rel_created = KnowledgeRelationship.objects.get_or_create(
                workspace=workspace,
                organization=organization,
                source_document=document,
                target_canonical_entity=entity,
                relationship_type=RelationshipType.APPLIES_TO,
                defaults={
                    "confidence": m["confidence"],
                    "provenance": "gliner_entity_resolution",
                    "approval_status": RelationshipApprovalStatus.APPROVED,
                },
            )

            linked_results.append({
                "entity_name": entity.name,
                "entity_type": entity.entity_type,
                "canonical_id": str(entity.id),
                "is_new_entity": created,
                "relationship_id": str(rel.id),
            })

        return linked_results
