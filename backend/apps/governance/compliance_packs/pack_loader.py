"""
LORE Enterprise - Compliance Pack Definitions & Workspace Loader (docs/enterprise/fix/knowledge.md §4)
Loads and applies pre-built governance packs:
- SOC 2 Type II
- ISO/IEC 27001
- HIPAA
- GDPR
- EU AI Act
Populates L6 Authority Ladder hierarchies, L3 Evidence Requirements, and canonical rules.
"""

import logging
from typing import Dict, Any, List, Optional
from apps.knowledge.models import KnowledgeItem, CanonicalEntity
from apps.governance.models import EvidenceRequirement
from apps.knowledge.ontology import CanonicalEntityType

logger = logging.getLogger(__name__)

COMPLIANCE_PACKS: Dict[str, Dict[str, Any]] = {
    "soc2": {
        "id": "soc2",
        "name": "SOC 2 Type II Governance Pack",
        "regulation": "AICPA SOC 2 (Trust Services Criteria)",
        "evidence_requirements": [
            {
                "decision_type": "vendor_approval",
                "evidence_type": "SOC2_REPORT",
                "is_mandatory": True,
                "min_authority_level": 3,
                "description": "SOC 2 Type II independent auditor report within 12 months.",
            },
            {
                "decision_type": "deployment",
                "evidence_type": "CAB_APPROVAL",
                "is_mandatory": True,
                "min_authority_level": 3,
                "description": "Change Advisory Board sign-off and peer review record.",
            },
            {
                "decision_type": "access_control",
                "evidence_type": "MFA_ATTESTATION",
                "is_mandatory": True,
                "min_authority_level": 3,
                "description": "Attestation of FIDO2 or hardware token MFA enforcement.",
            },
        ],
        "rules": [
            {
                "code": "SOC2-CC6.1",
                "statement": "Logical access to production assets and customer data requires unique user identity and multi-factor authentication.",
                "authority_level": 4,
                "component": "access_control",
            },
            {
                "code": "SOC2-CC7.2",
                "statement": "Vulnerability scanning must be conducted at least monthly and before major production infrastructure deployments.",
                "authority_level": 3,
                "component": "vulnerability_management",
            },
            {
                "code": "SOC2-CC8.1",
                "statement": "All software changes must undergo peer review, automated testing, and CAB approval before deployment.",
                "authority_level": 3,
                "component": "change_management",
            },
        ],
    },
    "iso27001": {
        "id": "iso27001",
        "name": "ISO/IEC 27001:2022 ISMS Pack",
        "regulation": "ISO/IEC 27001:2022 Information Security Management",
        "evidence_requirements": [
            {
                "decision_type": "data_processing",
                "evidence_type": "RISK_TREATMENT_PLAN",
                "is_mandatory": True,
                "min_authority_level": 4,
                "description": "Formally approved ISMS risk assessment and treatment plan.",
            },
            {
                "decision_type": "deployment",
                "evidence_type": "KMS_KEY_INVENTORY",
                "is_mandatory": True,
                "min_authority_level": 3,
                "description": "Cryptographic key inventory and rotation log.",
            },
        ],
        "rules": [
            {
                "code": "ISO-A.8.24",
                "statement": "Cryptographic controls and key management rules must be defined and applied across all sensitive data stores.",
                "authority_level": 4,
                "component": "cryptography",
            },
            {
                "code": "ISO-A.8.20",
                "statement": "Networks must be segregated into security perimeters according to trust levels.",
                "authority_level": 3,
                "component": "network_security",
            },
        ],
    },
    "hipaa": {
        "id": "hipaa",
        "name": "HIPAA Security & Privacy Pack",
        "regulation": "45 CFR Parts 160 and 164 (HIPAA)",
        "evidence_requirements": [
            {
                "decision_type": "vendor_approval",
                "evidence_type": "BUSINESS_ASSOCIATE_AGREEMENT",
                "is_mandatory": True,
                "min_authority_level": 4,
                "description": "Signed Business Associate Agreement (BAA) governing ePHI handling.",
            },
            {
                "decision_type": "data_processing",
                "evidence_type": "EPHI_ACCESS_LOG",
                "is_mandatory": True,
                "min_authority_level": 3,
                "description": "Tamper-evident audit trail of all electronic protected health information access.",
            },
        ],
        "rules": [
            {
                "code": "HIPAA-164.312(a)",
                "statement": "Access controls must enforce unique user identification and emergency access procedures for systems storing ePHI.",
                "authority_level": 5,
                "component": "healthcare_compliance",
            },
            {
                "code": "HIPAA-164.312(e)",
                "statement": "Electronic protected health information transmitted over public networks must be encrypted with TLS 1.3.",
                "authority_level": 5,
                "component": "transmission_security",
            },
        ],
    },
    "gdpr": {
        "id": "gdpr",
        "name": "EU GDPR Data Protection Pack",
        "regulation": "Regulation (EU) 2016/679 (GDPR)",
        "evidence_requirements": [
            {
                "decision_type": "data_processing",
                "evidence_type": "DPIA_ASSESSMENT",
                "is_mandatory": True,
                "min_authority_level": 4,
                "description": "Data Protection Impact Assessment signed by DPO.",
            },
            {
                "decision_type": "vendor_approval",
                "evidence_type": "STANDARD_CONTRACTUAL_CLAUSES",
                "is_mandatory": True,
                "min_authority_level": 4,
                "description": "Executed EU Standard Contractual Clauses (SCCs) for cross-border processing.",
            },
        ],
        "rules": [
            {
                "code": "GDPR-Art28",
                "statement": "Data processing by a third party must be governed by a binding contract defining subject matter, duration, and obligations.",
                "authority_level": 5,
                "component": "data_protection",
            },
            {
                "code": "GDPR-Art32",
                "statement": "Technical and organizational measures including encryption and pseudonymisation must be implemented to ensure security.",
                "authority_level": 5,
                "component": "technical_measures",
            },
            {
                "code": "GDPR-Art44",
                "statement": "Cross-border transfers of EU personal data outside the EEA without adequacy or approved safeguards are strictly prohibited.",
                "authority_level": 5,
                "component": "cross_border_transfer",
            },
        ],
    },
    "eu_ai_act": {
        "id": "eu_ai_act",
        "name": "EU AI Act Governance Pack",
        "regulation": "Regulation (EU) 2024/1689 (EU AI Act)",
        "evidence_requirements": [
            {
                "decision_type": "deployment",
                "evidence_type": "TECHNICAL_DOCUMENTATION_ANNEX_IV",
                "is_mandatory": True,
                "min_authority_level": 4,
                "description": "Comprehensive technical documentation demonstrating high-risk AI system compliance.",
            },
            {
                "decision_type": "deployment",
                "evidence_type": "CONFORMITY_ASSESSMENT",
                "is_mandatory": True,
                "min_authority_level": 4,
                "description": "CE-mark conformity assessment and fundamental rights impact review.",
            },
        ],
        "rules": [
            {
                "code": "EU-AI-Art9",
                "statement": "High-risk AI systems must establish, implement, document and maintain a continuous risk management system throughout their lifecycle.",
                "authority_level": 5,
                "component": "ai_risk_management",
            },
            {
                "code": "EU-AI-Art14",
                "statement": "High-risk AI systems must be designed to enable natural persons to oversee their operation and override outputs (Human-in-the-Loop).",
                "authority_level": 5,
                "component": "human_oversight",
            },
        ],
    },
}


class CompliancePackLoader:
    """
    Applies compliance packs to a workspace, creating CanonicalEntity,
    EvidenceRequirements, and default KnowledgeItems.
    """

    @classmethod
    def list_packs(cls) -> List[Dict[str, str]]:
        return [
            {"id": p["id"], "name": p["name"], "regulation": p["regulation"]}
            for p in COMPLIANCE_PACKS.values()
        ]

    @classmethod
    def apply_pack(cls, pack_id: str, workspace, organization) -> Dict[str, Any]:
        p_id = pack_id.lower().strip()
        if p_id not in COMPLIANCE_PACKS:
            raise ValueError(f"Unknown compliance pack '{pack_id}'. Available: {list(COMPLIANCE_PACKS.keys())}")

        pack = COMPLIANCE_PACKS[p_id]

        # 1. Create or resolve Canonical Regulation Entity
        reg_entity, _ = CanonicalEntity.objects.get_or_create(
            workspace=workspace,
            organization=organization,
            entity_type=CanonicalEntityType.REGULATION.value,
            canonical_name=p_id,
            defaults={
                "name": pack["regulation"],
                "description": f"Automated governance compliance pack for {pack['name']}.",
                "properties": {"pack_id": p_id},
            },
        )

        # 2. Populate Evidence Requirements
        created_reqs = []
        for req in pack["evidence_requirements"]:
            er, created = EvidenceRequirement.objects.update_or_create(
                workspace=workspace,
                decision_type=req["decision_type"],
                evidence_type=req["evidence_type"],
                defaults={
                    "is_mandatory": req["is_mandatory"],
                    "min_authority_level": req["min_authority_level"],
                    "description": req["description"],
                },
            )
            created_reqs.append(str(er.id))

        # 3. Populate Canonical Rules
        created_rules = []
        for r in pack["rules"]:
            ki, created = KnowledgeItem.objects.update_or_create(
                workspace=workspace,
                organization=organization,
                code=r["code"],
                defaults={
                    "statement": r["statement"],
                    "item_type": "rule",
                    "authority_level": r["authority_level"],
                    "component": r["component"],
                    "status": "stable",
                    "confidence": 1.0,
                },
            )
            created_rules.append(str(ki.id))

        logger.info(f"Applied compliance pack '{pack_id}' to workspace {workspace.name} ({len(created_rules)} rules, {len(created_reqs)} reqs).")

        return {
            "pack_id": p_id,
            "pack_name": pack["name"],
            "regulation_entity_id": str(reg_entity.id),
            "evidence_requirements_count": len(created_reqs),
            "rules_count": len(created_rules),
            "status": "applied",
        }

