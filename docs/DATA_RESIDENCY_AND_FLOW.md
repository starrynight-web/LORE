# LORE Enterprise — Data Residency & Sovereign Boundary Architecture (P4 §24)

## 1. Geopolitical Sovereign Boundaries

LORE Enterprise supports multi-region deployment architectures ensuring regulatory compliance with **GDPR** (EU), **FedRAMP / SOC2** (US), and **Local Air-Gapped Sovereign Enclaves** (On-Premise / Defense).

| Region Code | Geographic Region | Compliance Standards | Egress Rules |
| :--- | :--- | :--- | :--- |
| `us` | United States (Virginia / Ohio) | SOC2 Type II, HIPAA, FedRAMP Moderate | Permitted within US cloud infrastructure. |
| `eu` | European Union (Frankfurt / Dublin) | GDPR Chapter V, EU Cloud Code of Conduct | Strictly prohibited from egress to US/APAC without approved DPA. |
| `apac` | Asia-Pacific (Singapore / Sydney) | APRA, MAS Guidelines, PDPA | Retained within designated APAC data centers. |
| `local_onprem`| Air-Gapped Sovereign Enclave | National Security / Air-gapped Defense | **Zero external network egress**. Offline embedding & local Qdrant. |

---

## 2. End-to-End Enterprise Data Flow

```
+---------------------------------------------------------------------------------------------------+
|                                      DATA RESIDENCY PIPELINE                                      |
|                                                                                                   |
|  [Source Upload] --> [Magic Byte Validation] --> [Local Extraction / OCR]                        |
|                                                              |                                    |
|                                                              v                                    |
|  [Regional Vector Store] <-- [Regional Embedder] <-- [Structure Chunker]                          |
|         (Qdrant)                (Local Model)                                                     |
|                                                                                                   |
|  ================================ SOVEREIGN BOUNDARY GATE =====================================   |
|                                                                                                   |
|  [Governed Retrieval]                                                                             |
|         |                                                                                         |
|         +--> [L7 Permission Layer]                                                                |
|         +--> [L6 Authority Arbitration]                                                           |
|         +--> [L5 Temporal Validity]                                                               |
|         +--> [L4 Scoped Exception]                                                                |
|         +--> [L3 Evidence Sufficiency]                                                            |
|         +--> [L2 Answer State Settler]                                                            |
|         |                                                                                         |
|         v                                                                                         |
|  [DataResidencyService.check_residency_compliance]                                                 |
|         |                                                                                         |
|         +---> If target region != org sovereign region: RAISE DataResidencyViolation             |
|         +---> If compliant: EMIT canonical lore.result/2 envelope                                 |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Sovereign Boundary Enforcement Rules

The `DataResidencyService` (`backend/apps/identity/residency.py`) enforces strict invariants:

1. **Air-Gapped Sovereign Enforcement:** Organizations configured with `local_onprem` are mathematically barred from utilizing any cloud API endpoints (e.g., external LLM gateways, remote vector endpoints). Any egress attempt raises `DataResidencyViolation`.
2. **GDPR Sovereign Containment:** Data originated within `eu` workspaces cannot be vectorized or processed in `us` or `apac` clusters.
3. **Audit Provenance:** Every cross-region request attempt is recorded in `AuditEvent` with actor IP address and geographical metadata.
