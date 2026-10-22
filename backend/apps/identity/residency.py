import logging
from typing import Dict, Any, List, Optional
from django.core.exceptions import PermissionDenied

logger = logging.getLogger(__name__)

SUPPORTED_RESIDENCY_REGIONS = {
    'us': 'United States (US-East / US-West FedRAMP & SOC2)',
    'eu': 'European Union (GDPR / Sovereign Cloud Frankfurt & Dublin)',
    'apac': 'Asia-Pacific (Singapore / Tokyo / Sydney)',
    'local_onprem': 'Local Air-Gapped / Sovereign On-Premise Enclave'
}

class DataResidencyViolation(PermissionDenied):
    """Raised when an operation attempts to egress data outside its sovereign region boundary."""
    pass

class DataResidencyService:
    """
    Enterprise Sovereign Boundary & Data Residency Enforcement Service (P4 §24).
    Guarantees that documents, extracted text, embeddings, and telemetry
    never egress across unauthorized geopolitical and compliance boundaries.
    """

    @classmethod
    def get_supported_regions(cls) -> Dict[str, str]:
        return SUPPORTED_RESIDENCY_REGIONS

    @classmethod
    def validate_region(cls, region: str) -> bool:
        return region.lower() in SUPPORTED_RESIDENCY_REGIONS

    @classmethod
    def check_residency_compliance(
        cls,
        organization_region: str,
        target_processing_region: str,
        operation_name: str = "retrieval_or_indexing"
    ) -> bool:
        """
        Validates whether target processing region satisfies organization's data residency constraints.
        """
        org_reg = (organization_region or 'us').lower()
        target_reg = (target_processing_region or 'us').lower()

        # Same region is always compliant
        if org_reg == target_reg:
            return True

        # Local onprem enclaves strictly disallow ANY remote processing
        if org_reg == 'local_onprem' and target_reg != 'local_onprem':
            logger.error(f"[Data Residency Breach] Organization strictly requires 'local_onprem'. Target '{target_reg}' is forbidden.")
            raise DataResidencyViolation(
                f"Data residency policy violation: Air-gapped on-premise data cannot egress to '{target_reg}' for {operation_name}."
            )

        # EU GDPR sovereign boundary strictly prevents US/APAC transfer without explicit DPA
        if org_reg == 'eu' and target_reg not in ('eu', 'local_onprem'):
            logger.error(f"[Data Residency Breach] EU GDPR boundary prevents transfer to '{target_reg}'.")
            raise DataResidencyViolation(
                f"Data residency policy violation: EU GDPR sovereign data cannot be processed in region '{target_reg}'."
            )

        logger.info(f"[Data Residency Verified] {operation_name} compliant: org_region={org_reg}, target={target_reg}")
        return True
