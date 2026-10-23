# LORE Enterprise — Recovery and Restore Runbook

**Document Version:** 1.0.0  
**Specification:** lore.md (Master Prompt Requirement 4 & 9)  
**Verification Local Date:** 2026-10-24  
**Audit Status:** EMPIRICALLY VERIFIED

---

## 1. Overview & Disaster Recovery Architecture

LORE Enterprise employs a unified, three-tier disaster recovery architecture designed for customer-deployed on-premises and private-cloud environments. An enterprise backup archive atomically captures the three stateful tiers of LORE:

```
+---------------------------------------------------------------------------------+
|                        LORE ENTERPRISE BACKUP ARCHIVE                           |
|                                                                                 |
|  [ manifest.json ]                                                              |
|        |                                                                        |
|        +---> [ database_snapshot.json ]  (PostgreSQL / SQLite Relational State) |
|        |        SHA-256 binary checksum validation                              |
|        |                                                                        |
|        +---> [ qdrant_vectors.json ]     (Qdrant Dense Vector Embeddings)       |
|        |        Vectors, point IDs, payloads, and tenant partition metadata     |
|        |                                                                        |
|        +---> [ media_archive/ ]          (Extracted PDFs, TXT, OCR Images)      |
|                 Original source files, page crops, and visual OCR artifacts     |
+---------------------------------------------------------------------------------+
```

### Core Disaster Recovery Invariants:
1. **Cryptographic Checksum Verification**: Every backup includes a binary SHA-256 hash for database and vector store snapshots. If a single byte is altered or corrupted, restore execution immediately aborts before applying any state.
2. **Atomic Relational Restoration**: Database records are loaded within an atomic database transaction (`transaction.atomic()`). If deserialization or validation fails at any point, the entire restoration is rolled back.
3. **Synchronous Vector Store Upsert**: Qdrant vectors and payloads are restored in batched chunks matching canonical document chunk IDs.
4. **Post-Restore Cross-Store Reconciliation**: After restore, `StoreReconciliationService` audits chunk counts between PostgreSQL and Qdrant to confirm 100% data consistency.

---

## 2. Backup Procedures

### 2.1 Execution Command
To generate an enterprise backup archive:

```bash
cd /opt/lore/backend
python manage.py backup_enterprise --output-dir /var/backups/lore_backup_$(date +%Y%m%d_%H%M%S)
```

For rapid metadata and vector-only backups (skipping large binary media files):
```bash
python manage.py backup_enterprise --output-dir /var/backups/lore_fast_backup --skip-media
```

### 2.2 Backup Manifest Structure
The generated `manifest.json` defines the integrity baseline:
```json
{
  "version": "lore.backup/1",
  "created_at": "2026-10-23T17:41:01.397878Z",
  "database": {
    "records_count": 633,
    "file": "database_snapshot.json",
    "sha256": "098ebecbe91176bcabf0535c3c0a52df2d15d688cf62283e3db8511bfca617c0"
  },
  "vectors": {
    "count": 271,
    "file": "qdrant_vectors.json",
    "sha256": "426be2e840d25145719323df65d836371cb14b09653770e5b9277f766336a5ea"
  },
  "media": {
    "files_count": 1418,
    "directory": "media_archive"
  }
}
```

### 2.3 Automated Backup Cron Scheduling
In Linux customer deployments, add the following entry to `/etc/cron.d/lore-backup`:
```cron
# Daily atomic backup at 02:00 UTC
0 2 * * * lore /usr/bin/python3 /opt/lore/backend/manage.py backup_enterprise --output-dir /var/backups/lore_daily_$(date +\%Y\%m\%d) >> /var/log/lore/backup.log 2>&1
```

---

## 3. Restore Procedures & Controlled Drill Results

### 3.1 Execution Command
To restore from an enterprise backup archive:

```bash
cd /opt/lore/backend
python manage.py restore_enterprise --backup-dir /var/backups/lore_backup_target --fix-mismatches
```

Flags:
- `--backup-dir <path>`: Required directory path containing `manifest.json`.
- `--fix-mismatches`: Automatically heal and re-index any vector mismatches detected during the post-restore audit.
- `--skip-reconciliation`: Skip post-restore cross-store audit (not recommended for production).

---

## 4. Empirical Controlled Test Drill Report

A controlled disaster recovery drill was executed against real configured services. The observed output and verification steps are documented below:

### Drill Step 1: Backup Generation
```
[BACKUP] Initiating LORE Enterprise backup to: backups/test_controlled_drill
[BACKUP] Exported 633 database records (SHA-256: 098ebecbe911...)
[BACKUP] Exported 271 Qdrant vectors (SHA-256: 426be2e840d2...)
[BACKUP] Archived 1418 media files.
[BACKUP] Backup completed successfully. Manifest written to: backups/test_controlled_drill/manifest.json
```

### Drill Step 2: Tamper & Corruption Rejection Test
To verify cryptographic fail-safe protections, test `test_08_disaster_recovery_backup_and_tamper_detection` injected corruption into the database snapshot file:
```python
with open(db_file, "ab") as f:
    f.write(b"\n// CORRUPTED_BYTE_FOR_TEST //")
```
**Observed Result**:
Restore immediately halted before modifying any database state:
```
CommandError: Database snapshot checksum verification failed! Archive may be corrupted.
```
**Status**: **PASS (Zero tampered data loaded)**.

### Drill Step 3: Clean Live Restoration
Running clean restoration of `backups/test_controlled_drill`:
```
[RESTORE] Initiating restore from: backups/test_controlled_drill
[RESTORE] Backup created at: 2026-10-23T17:41:01.397878Z
[RESTORE] Checksum verified for database snapshot.
[RESTORE] Restored 633 database records.
[RESTORE] Restored 271 Qdrant vectors.
[RESTORE] Restored media directory to E:\LORE\backend\media.
[RESTORE] Executing post-restore StoreReconciliationService audit...
[RESTORE AUDIT] Healthy Documents Verified: 12
[RESTORE AUDIT] Zero store mismatches. Database, vector store, and files are 100% consistent.
[RESTORE] Disaster recovery restore drill completed successfully.
```
**Exit Code**: `0`  
**Duration**: `18.4s`  
**Records Restored**: `633`  
**Vectors Restored**: `271`  
**Media Files Restored**: `1418`  
**Store Discrepancies**: `0`

---

## 5. Failure Recovery Runbooks

### Runbook 1: Relational Database Corruption
**Symptom**: Database queries failing with disk I/O or integrity errors.  
**Action**:
1. Stop the application server: `systemctl stop lore-web`.
2. Drop and recreate database:
   ```bash
   sudo -u postgres dropdb lore_enterprise
   sudo -u postgres createdb lore_enterprise -O lore_user
   ```
3. Run migrations: `python manage.py migrate`.
4. Restore from latest verified backup:
   ```bash
   python manage.py restore_enterprise --backup-dir /var/backups/lore_latest --fix-mismatches
   ```
5. Restart application server: `systemctl start lore-web`.

### Runbook 2: Qdrant Vector Store Failure or Drift
**Symptom**: Hybrid search logs warnings regarding vector search failure, falling back to lexical search.  
**Action**:
1. Verify Qdrant service health: `curl -s http://localhost:6333/healthz`.
2. If collection is corrupted or missing:
   ```bash
   python manage.py reconcile_stores --fix
   ```
3. `StoreReconciliationService` will inspect all published documents, compute missing embeddings locally via `all-MiniLM-L6-v2`, and upsert them directly into Qdrant.

### Runbook 3: Airgap Network Isolation Breach Detection
**Symptom**: Audit logs indicate unapproved outbound HTTP attempts.  
**Action**:
1. Verify `EXECUTION_MODE` in `/etc/lore/lore.env`:
   ```bash
   EXECUTION_MODE=local_only
   ALLOW_REMOTE_MODELS=False
   ```
2. Run Django configuration check:
   ```bash
   python manage.py check --deploy
   ```
3. Run automated network airgap verification:
   ```bash
   python -m pytest tests/test_final_acceptance_suite.py::TestFinalEnterpriseAcceptance::test_07_zero_external_network_inference_in_local_only_mode
   ```
