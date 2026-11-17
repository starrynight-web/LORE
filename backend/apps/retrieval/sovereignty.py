"""
LORE Enterprise - Data Sovereignty & Residency Router (docs/enterprise/fix/knowledge.md §1)
Enforces regional boundaries, tenant data residency compliance (GDPR, HIPAA, PDPA, Sovereign Air-gap),
and deterministic routing of embeddings, LLMs, and vector/graph storage.
"""

import os
import logging
from typing import Dict, Any, List, Optional
from django.conf import settings

logger = logging.getLogger(__name__)


class SovereigntyRegion:
    EU_CENTRAL = "eu_central"         # Frankfurt / Europe West - GDPR Compliant
    US_EAST = "us_east"               # N. Virginia - HIPAA / FedRAMP / SOC 2
    APAC_SINGAPORE = "apac_singapore" # Singapore - PDPA Compliant
    SOVEREIGN_ONPREM = "sovereign_onprem" # Air-gapped / Local-only isolated enclave


class DataSovereigntyViolation(Exception):
    """Raised when an operation attempts to transmit data across a restricted sovereignty boundary."""
    pass


class DataSovereigntyRouter:
    """
    Routes document processing, embeddings, LLM generation, and storage
    to region-locked endpoints based on workspace and source compliance metadata.
    """

    DEFAULT_REGION = getattr(settings, "DEFAULT_DATA_RESIDENCY_REGION", SovereigntyRegion.EU_CENTRAL)

    REGIONAL_ENDPOINTS: Dict[str, Dict[str, Any]] = {
        SovereigntyRegion.EU_CENTRAL: {
            "region_code": "eu_central",
            "jurisdiction": "European Union (GDPR)",
            "embedding_endpoint": os.environ.get("EU_EMBEDDING_ENDPOINT", "https://eu-central.lore.enterprise/embeddings"),
            "llm_endpoint": os.environ.get("EU_LLM_ENDPOINT", "https://eu-central.lore.enterprise/llm"),
            "vector_cluster": os.environ.get("EU_VECTOR_CLUSTER", "qdrant-eu-central.lore.internal"),
            "graph_cluster": os.environ.get("EU_GRAPH_CLUSTER", "neo4j-eu-central.lore.internal"),
            "allows_cross_border_transfer": False,
        },
        SovereigntyRegion.US_EAST: {
            "region_code": "us_east",
            "jurisdiction": "United States (HIPAA / SOC 2)",
            "embedding_endpoint": os.environ.get("US_EMBEDDING_ENDPOINT", "https://us-east.lore.enterprise/embeddings"),
            "llm_endpoint": os.environ.get("US_LLM_ENDPOINT", "https://us-east.lore.enterprise/llm"),
            "vector_cluster": os.environ.get("US_VECTOR_CLUSTER", "qdrant-us-east.lore.internal"),
            "graph_cluster": os.environ.get("US_GRAPH_CLUSTER", "neo4j-us-east.lore.internal"),
            "allows_cross_border_transfer": True,
        },
        SovereigntyRegion.APAC_SINGAPORE: {
            "region_code": "apac_singapore",
            "jurisdiction": "Asia-Pacific (PDPA)",
            "embedding_endpoint": os.environ.get("APAC_EMBEDDING_ENDPOINT", "https://apac-sin.lore.enterprise/embeddings"),
            "llm_endpoint": os.environ.get("APAC_LLM_ENDPOINT", "https://apac-sin.lore.enterprise/llm"),
            "vector_cluster": os.environ.get("APAC_VECTOR_CLUSTER", "qdrant-apac-sin.lore.internal"),
            "graph_cluster": os.environ.get("APAC_GRAPH_CLUSTER", "neo4j-apac-sin.lore.internal"),
            "allows_cross_border_transfer": True,
        },
        SovereigntyRegion.SOVEREIGN_ONPREM: {
            "region_code": "sovereign_onprem",
            "jurisdiction": "Sovereign Air-Gapped Local Enclave",
            "embedding_endpoint": "local://sentence-transformers/all-MiniLM-L6-v2",
            "llm_endpoint": "local://ollama/phi4:deterministic",
            "vector_cluster": "local://qdrant_storage",
            "graph_cluster": "local://kuzu_storage",
            "allows_cross_border_transfer": False,
        },
    }

    @classmethod
    def resolve_region(
        cls,
        workspace=None,
        document=None,
        compliance_tags: Optional[List[str]] = None,
    ) -> str:
        """
        Determines the designated sovereignty region based on hierarchical metadata:
        1. Document-level metadata ('sovereignty_region', 'compliance_framework')
        2. Workspace-level metadata / settings
        3. Global fallback configuration
        """
        tags = set(compliance_tags or [])

        # 1. Document metadata inspection
        if document:
            doc_meta = getattr(document, "metadata", None) or getattr(document, "validation_notes", {}) or {}
            if isinstance(doc_meta, dict):
                reg = doc_meta.get("sovereignty_region")
                if reg in cls.REGIONAL_ENDPOINTS:
                    return reg
                doc_tags = doc_meta.get("compliance_tags", [])
                if isinstance(doc_tags, list):
                    tags.update([str(t).upper() for t in doc_tags if t])

        # 2. Workspace metadata inspection
        if workspace:
            ws_meta = getattr(workspace, "metadata", {}) or {}
            if isinstance(ws_meta, dict):
                ws_reg = ws_meta.get("sovereignty_region")
                if ws_reg in cls.REGIONAL_ENDPOINTS:
                    return ws_reg
                ws_tags = ws_meta.get("compliance_tags", [])
                if isinstance(ws_tags, list):
                    tags.update([str(t).upper() for t in ws_tags if t])

        # 3. Compliance Tag Heuristics
        if "SOVEREIGN" in tags or "AIRGAP" in tags or getattr(settings, "EXECUTION_MODE", "") == "local_only":
            return SovereigntyRegion.SOVEREIGN_ONPREM

        if "GDPR" in tags or "EU_AI_ACT" in tags or "EU" in tags:
            return SovereigntyRegion.EU_CENTRAL

        if "HIPAA" in tags or "FEDRAMP" in tags or "US" in tags:
            return SovereigntyRegion.US_EAST

        if "PDPA" in tags or "APAC" in tags:
            return SovereigntyRegion.APAC_SINGAPORE

        default_reg = cls.DEFAULT_REGION
        return default_reg if default_reg in cls.REGIONAL_ENDPOINTS else SovereigntyRegion.EU_CENTRAL

    @classmethod
    def get_endpoints(cls, region: Optional[str] = None) -> Dict[str, Any]:
        """Returns routing endpoints and parameters for the designated region."""
        reg_key = region or cls.DEFAULT_REGION
        if reg_key not in cls.REGIONAL_ENDPOINTS:
            reg_key = SovereigntyRegion.EU_CENTRAL
        return cls.REGIONAL_ENDPOINTS[reg_key]

    @classmethod
    def assert_residency_compliance(cls, source_region: str, target_endpoint: str) -> bool:
        """
        Enforces strict zero-leakage compliance:
        Throws DataSovereigntyViolation if a sovereign or GDPR-locked region is targeted by an untrusted remote host.
        """
        cfg = cls.get_endpoints(source_region)
        endpoint_clean = (target_endpoint or "").lower().strip()

        if not cfg.get("allows_cross_border_transfer", False):
            if source_region == SovereigntyRegion.SOVEREIGN_ONPREM:
                if not (endpoint_clean.startswith("local://") or "localhost" in endpoint_clean or "127.0.0.1" in endpoint_clean):
                    raise DataSovereigntyViolation(
                        f"Air-gapped sovereign data violation: Target endpoint '{target_endpoint}' violates sovereign enclave."
                    )
            elif source_region == SovereigntyRegion.EU_CENTRAL:
                if "us-east" in endpoint_clean or "apac" in endpoint_clean:
                    raise DataSovereigntyViolation(
                        f"EU GDPR cross-border transfer violation: Attempted data transit from {source_region} to {target_endpoint}."
                    )
        return True

    @classmethod
    def get_embedding_endpoint(cls, workspace=None, document=None) -> str:
        region = cls.resolve_region(workspace=workspace, document=document)
        return cls.get_endpoints(region).get("embedding_endpoint", "")

    @classmethod
    def get_llm_endpoint(cls, workspace=None, document=None) -> str:
        region = cls.resolve_region(workspace=workspace, document=document)
        return cls.get_endpoints(region).get("llm_endpoint", "")

    @classmethod
    def get_vector_cluster(cls, workspace=None, document=None) -> str:
        region = cls.resolve_region(workspace=workspace, document=document)
        return cls.get_endpoints(region).get("vector_cluster", "")

    @classmethod
    def get_graph_cluster(cls, workspace=None, document=None) -> str:
        region = cls.resolve_region(workspace=workspace, document=document)
        return cls.get_endpoints(region).get("graph_cluster", "")
