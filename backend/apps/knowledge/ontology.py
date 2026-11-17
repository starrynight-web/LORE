"""
LORE Enterprise - Canonical Enterprise Ontology (docs/enterprise/fix/knowledge.md §2)
Defines standardized canonical entity nodes and relationships:
- Enterprise Nodes: Organization, Department, System, Service, Vendor, Regulation, Role, DataAsset
- LORE Core Nodes: Rule, Skill, Component, Version, Exception, Decision
"""

from enum import Enum
from typing import Dict, List, Any


class CanonicalEntityType(str, Enum):
    # Enterprise Entities
    ORGANIZATION = "organization"
    DEPARTMENT = "department"
    SYSTEM = "system"
    SERVICE = "service"
    VENDOR = "vendor"
    REGULATION = "regulation"
    ROLE = "role"
    DATA_ASSET = "data_asset"

    # Core LORE Governance Entities
    RULE = "rule"
    SKILL = "skill"
    COMPONENT = "component"
    VERSION = "version"
    EXCEPTION = "exception"
    DECISION = "decision"


CANONICAL_ENTITY_DESCRIPTIONS: Dict[str, str] = {
    CanonicalEntityType.ORGANIZATION: "Top-level corporate, business, or institutional entity.",
    CanonicalEntityType.DEPARTMENT: "Business unit or functional division (e.g. Legal, SecOps, Engineering).",
    CanonicalEntityType.SYSTEM: "Enterprise software platform, infrastructure stack, or data pipeline.",
    CanonicalEntityType.SERVICE: "Specific microservice, API, or cloud service.",
    CanonicalEntityType.VENDOR: "Third-party vendor, SaaS provider, or contractor (e.g. AWS, Stripe, Okta).",
    CanonicalEntityType.REGULATION: "Statutory or regulatory compliance mandate (e.g. GDPR, HIPAA, SOC 2, EU AI Act).",
    CanonicalEntityType.ROLE: "Organizational or security role (e.g. DPO, Security Officer, SysAdmin).",
    CanonicalEntityType.DATA_ASSET: "Protected data repository, table, bucket, or schema (e.g. customer_pii_vault).",
    CanonicalEntityType.RULE: "Deterministic policy directive or operational rule.",
    CanonicalEntityType.SKILL: "Standard operating procedure or procedural workflow.",
    CanonicalEntityType.COMPONENT: "Technical component or architectural domain.",
    CanonicalEntityType.VERSION: "Explicit version or release specification.",
    CanonicalEntityType.EXCEPTION: "Time-bounded, scoped policy exception.",
    CanonicalEntityType.DECISION: "Historical compliance or operational decision record.",
}


class OntologyRelationshipType(str, Enum):
    # Relational & Architectural Edges
    APPLIES_TO = "APPLIES_TO"
    DEPENDS_ON = "DEPENDS_ON"
    REQUIRES = "REQUIRES"
    SUPERSEDES = "SUPERSEDES"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    DERIVED_FROM = "DERIVED_FROM"
    OVERRIDES = "OVERRIDES"
    GOVERNED_BY = "GOVERNED_BY"
    
    # Canonical Enterprise Linkage Edges
    RUNS_ON = "RUNS_ON"
    PROVIDED_BY = "PROVIDED_BY"
    PROCESSED_BY = "PROCESSED_BY"
    OWNED_BY = "OWNED_BY"
    COMPLIES_WITH = "COMPLIES_WITH"
    RESOLVES = "RESOLVES"

