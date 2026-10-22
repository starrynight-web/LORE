# LORE Enterprise — Integrations & Identity Runbook (P4)

## 1. Enterprise Identity & SSO Architecture (P4 §22)

LORE Enterprise supports federated authentication and directory provisioning compliant with enterprise identity providers: **Okta**, **Microsoft Entra ID (Azure AD)**, **Google Workspace**, and **PingIdentity**.

```
+------------------+         SAML 2.0 / OIDC          +-------------------------+
|  Enterprise IdP  | -------------------------------> |    LORE Enterprise      |
|  (Okta / Entra)  | <------------------------------- |   Authentication Layer  |
+------------------+                                  +-------------------------+
         |                                                         |
         | SCIM 2.0 (Automated Provisioning)                       |
         v                                                         v
+-------------------------------------------------------------------------------+
|  Endpoints:                                                                   |
|  - GET/POST  /api/v1/identity/scim/v2/Users      (Provision Users)            |
|  - GET/PUT   /api/v1/identity/scim/v2/Users/{id} (Update/Deactivate)          |
|  - GET       /api/v1/identity/scim/v2/Groups     (List Workspace Groups)      |
|  - POST      /api/v1/identity/scim/v2/Groups/{id}(Sync Directory Groups)     |
+-------------------------------------------------------------------------------+
```

---

### 1.1 SCIM 2.0 Protocol Specification
LORE conforms to **RFC 7643** (Core Schema) and **RFC 7644** (Protocol):

#### User Synchronization:
- **Endpoint:** `POST /api/v1/identity/scim/v2/Users`
- **Payload:**
  ```json
  {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
    "userName": "sarah.connor@acme.com",
    "name": {
      "givenName": "Sarah",
      "familyName": "Connor"
    },
    "emails": [
      {
        "value": "sarah.connor@acme.com",
        "primary": true
      }
    ],
    "active": true
  }
  ```
- **Deprovisioning:** When a user is deprovisioned in the IdP, a `DELETE /api/v1/identity/scim/v2/Users/{id}` is sent. LORE automatically sets `is_active=False` and revokes all active auth tokens.

#### Group & Role Mapping:
Enterprise directory groups map deterministically to LORE workspace permission tiers:

| Enterprise IdP Group | LORE Workspace Role | Permissions |
| :--- | :--- | :--- |
| `Security-Engineers` | `workspace_admin` | Manage collections, configure exceptions, review queue |
| `Compliance-Auditors`| `reviewer` | Review low-confidence documents, audit log inspection |
| `Domain-Editors`     | `contributor` | Upload sources, trigger ingestion, author notes |
| `General-Employees`  | `viewer` | Read-only governed query access |

---

## 2. Generic Source Connectors Framework (P4 §21)

All external data ingestion sources adhere to the unified `BaseConnector` contract (`backend/apps/sources/connectors/base.py`):

```python
class BaseConnector(abc.ABC):
    def test_connection(self) -> bool: ...
    def list_events(self, checkpoint: Optional[SyncCheckpoint], full_sync: bool) -> Generator[SyncEvent, None, Optional[SyncCheckpoint]]: ...
    def fetch_document_content(self, external_id: str) -> bytes: ...
    def sync(self, checkpoint: Optional[SyncCheckpoint], full_sync: bool) -> SyncResult: ...
```

### 2.1 Available Connector Implementations
- **`LocalFolderConnector` (`local_folder`):** Synchronizes mounted NFS/SMB fileshares and local storage directories with incremental mtime change detection.
- **`SharePointConnector` (`sharepoint`):** Connects to Microsoft Graph API drives using delta sync tokens.
- **`S3Connector` (`s3`):** Scans Amazon S3 / MinIO buckets using S3 object versioning and ETag hashing.

---

## 3. Compliance Review Workflows (P4 §23)

Documents flagged for low OCR confidence ($< 70\%$) or unverified provenance are quarantined in the Compliance Review Queue (`/api/v1/governance/review/`):
- **Approval (`POST /api/v1/governance/review/{id}/approve/`):** Marks document `ready`, purges cache, and logs an `item_promoted` event in `AuditEvent`.
- **Rejection (`POST /api/v1/governance/review/{id}/reject/`):** Confirms quarantine status and records reviewer identity.
