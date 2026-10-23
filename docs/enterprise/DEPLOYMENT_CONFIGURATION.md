# LORE Enterprise — Deployment Configuration Guide

**Document Version:** 1.0.0  
**Specification:** lore.md (Master Prompt Requirement 1, 8, 10)  
**Deployment Target:** Customer-Deployed / Airgapped Infrastructure  
**Verification Date:** 2026-10-24

---

## 1. Customer-Deployed Architecture & Topologies

LORE Enterprise is designed to execute entirely within customer-controlled infrastructure. Data processing, chunking, OCR, dense embedding generation, relational storage, vector indexing, graph traversal, and 9-layer governance decisions run locally without external cloud dependencies.

### 1.1 Single-Node Enclave Topology (Airgapped / Small Enterprise)
```
+--------------------------------------------------------------------------------+
|                        CUSTOMER ENCLAVE SERVER (RHEL 9 / Ubuntu 24.04)         |
|                                                                                |
|  +---------------------------+       +--------------------------------------+  |
|  |  LORE Web & API Service   | <---> |  LORE Governed MCP Server            |  |
|  |  Port: 8000 (Internal)    |       |  Port: 8001 (Internal) / STDIO       |  |
|  +---------------------------+       +--------------------------------------+  |
|               |                                         |                      |
|               +--------------------+--------------------+                      |
|                                    |                                           |
|       +----------------------------+----------------------------+              |
|       v                                                         v              |
|  +---------------------------+       +--------------------------------------+  |
|  |  PostgreSQL 16 (Local)    |       |  Qdrant Vector Store (Local Node)    |  |
|  |  Port: 5432 (127.0.0.1)   |       |  Port: 6333 / 6334 (127.0.0.1)       |  |
|  +---------------------------+       +--------------------------------------+  |
|               |                                         |                      |
|  +---------------------------+       +--------------------------------------+  |
|  |  SentenceTransformers     |       |  Tesseract 5.4 OCR                   |  |
|  |  all-MiniLM-L6-v2 (CPU)   |       |  Local Offline Binary                |  |
|  +---------------------------+       +--------------------------------------+  |
|                                                                                |
|  NETWORK EGRESS: STRICTLY BLOCKED (Zero outbound internet access permitted)    |
+--------------------------------------------------------------------------------+
```

### 1.2 Multi-Node VPC Topology (High Availability / Enterprise)
- **Application Pods**: Scaled horizontally behind an internal load balancer (HAProxy / ALB).
- **Relational Storage**: PostgreSQL 16 Primary-Replica cluster with `pg_trgm` and full-text search.
- **Vector Storage**: Clustered Qdrant nodes (3-node Raft consensus) on dedicated private subnets.
- **Worker Tier**: Asynchronous Celery workers for OCR and document settlement extraction.

---

## 2. Port & Network Matrix

All service ports must be bound strictly to internal loopback (`127.0.0.1`) or private VPC subnets. Public internet exposure of any backend port is strictly prohibited.

| Service | Protocol | Default Port | Exposure | Description |
| :--- | :--- | :---: | :--- | :--- |
| **LORE REST API & UI** | HTTP / HTTPS | `8000` | Internal VPC / VPN | Governed query endpoints, admin console, document upload |
| **LORE Governed MCP** | HTTP / STDIO | `8001` | Internal / Local | Model Context Protocol server exposing governed tools |
| **PostgreSQL Database** | TCP | `5432` | `127.0.0.1` only | Canonical system of record and relational knowledge graph |
| **Qdrant REST API** | HTTP | `6333` | `127.0.0.1` only | Dense vector indexing and similarity search |
| **Qdrant gRPC** | gRPC | `6334` | `127.0.0.1` only | High-throughput vector batch ingestion |
| **Internet Egress** | TCP | None | **BLOCKED** | Zero outbound traffic permitted in `local_only` mode |

---

## 3. Environment Variable Reference Matrix

Below is the authoritative configuration matrix. System checks validate these variables at startup and fail immediately if incompatible settings are detected.

### 3.1 Production Security & Boundaries
| Variable | Allowed Values | Production Default | Constraint / Hardening Rule |
| :--- | :--- | :---: | :--- |
| `DEBUG` | `True`, `False` | `False` | Must be `False` in production. Triggers strict security checks. |
| `SECRET_KEY` | High-entropy string | *(Required)* | Must not use the development default key (`lore-enterprise-dev...`). Check `lore.security.E001`. |
| `ALLOWED_HOSTS` | Comma-separated domains | *(Required)* | Wildcards (`*`) and empty lists are prohibited. Check `lore.security.E003`. |
| `GUEST_MODE_ENABLED`| `True`, `False` | `False` | **Strictly prohibited** in production. If `True` when `DEBUG=False`, startup raises `ImproperlyConfigured`. Check `lore.security.E002`. |
| `CORS_ALLOW_ALL_ORIGINS` | `True`, `False` | `False` | Wildcard CORS is prohibited in production. Check `lore.security.E004`. |
| `CORS_ALLOWED_ORIGINS` | Comma-separated URLs | *(Required)* | Explicit list of trusted frontend origins (e.g. `https://lore.internal.corp`). |
| `CSRF_COOKIE_SECURE` | `True`, `False` | `True` | Forces HTTPS transmission for CSRF tokens. |
| `SESSION_COOKIE_SECURE`| `True`, `False` | `True` | Forces HTTPS transmission for session cookies. |

### 3.2 Execution Strategy & Model-Minimal Operation
| Variable | Allowed Values | Default | Description |
| :--- | :--- | :---: | :--- |
| `EXECUTION_MODE` | `local_only`, `deterministic_first`, `approved_remote` | `deterministic_first` | Overall execution strategy. `local_only` enforces complete airgap. Check `lore.config.E010`. |
| `ALLOW_REMOTE_MODELS` | `True`, `False` | `False` | Global toggle. In `local_only` mode, must be `False`. Check `lore.config.W011`. |
| `GROQ_API_KEY` | String or empty | `""` | Optional external provider key. Scrubbed from logs; ignored in `local_only`. |
| `REMOTE_LLM_MODEL` | Provider model name | `llama-3.3-70b-versatile` | Approved remote model when authorized by tenant policy. |

### 3.3 Embedding & Vector Store Configuration
| Variable | Allowed Values | Default | Description |
| :--- | :--- | :---: | :--- |
| `EMBEDDING_PROVIDER` | `sentence-transformers`, `local_transformer` | `sentence-transformers` | Neural embedding engine. Silent hash fallback is prohibited. Check `lore.config.E012`. |
| `EMBEDDING_MODEL_NAME` | HuggingFace model path | `all-MiniLM-L6-v2` | Local embedding model. |
| `EMBEDDING_DIMENSION` | Integer | `384` | Must match model output and Qdrant collection dimension. Check `lore.vector.E020`. |
| `QDRANT_HOST` | IP / Hostname | `localhost` | Qdrant vector store host. |
| `QDRANT_PORT` | Port number | `6333` | Qdrant vector store port. |
| `ALLOW_HASH_PROJECTION_FALLBACK` | `True`, `False` | `False` | **Must be False** in production. Prohibits silent low-quality hash embeddings. |

---

## 4. Offline / Airgapped Deployment Runbook

### 4.1 Step 1: Pre-caching SentenceTransformers Model
In an airgapped environment without internet access, the neural embedding weights must be preloaded into the local HuggingFace cache:

```bash
# On an internet-connected staging machine:
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Export cache directory to transfer archive:
tar -czvf lore_hf_cache.tar.gz ~/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/

# On the airgapped target host:
mkdir -p /root/.cache/huggingface/hub
tar -xzvf lore_hf_cache.tar.gz -C /root/.cache/huggingface/hub/
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

### 4.2 Step 2: Offline Tesseract OCR Installation
Install Tesseract OCR binaries and offline language traineddata files:
```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-ben
# Verify offline operation:
tesseract --version
tesseract --list-langs
```

### 4.3 Step 3: Production Environment File Setup
Create `/etc/lore/lore.env` with strict permissions (`chmod 600`):
```ini
DEBUG=False
SECRET_KEY=c8f49a0293847f98e8201a4bc567890123456789abcdef0123456789abcdef01
ALLOWED_HOSTS=lore.internal.company.com,10.0.1.15
CORS_ALLOW_ALL_ORIGINS=False
CORS_ALLOWED_ORIGINS=https://lore.internal.company.com
GUEST_MODE_ENABLED=False
EXECUTION_MODE=local_only
ALLOW_REMOTE_MODELS=False
EMBEDDING_PROVIDER=sentence-transformers
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384
ALLOW_HASH_PROJECTION_FALLBACK=False
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
CSRF_COOKIE_SECURE=True
SESSION_COOKIE_SECURE=True
```

---

## 5. Clean Installation & Upgrade Runbook

### 5.1 Clean Installation Workflow
1. **Clone repository & prepare virtual environment**:
   ```bash
   cd /opt/lore/backend
   python3 -m venv venv
   source venv/bin/activate
   pip install --no-index --find-links=/opt/wheels -r requirements.txt
   ```
2. **Execute Database Migrations**:
   ```bash
   python manage.py migrate
   ```
3. **Run System Configuration Checks**:
   ```bash
   python manage.py check --deploy
   ```
   *Expected output*: `System check identified no issues (0 silenced).`
4. **Seed Initial Collections & Admin**:
   ```bash
   python manage.py createsuperuser --noinput
   ```
5. **Start Services via Systemd**:
   ```bash
   systemctl enable --now lore-web
   systemctl enable --now lore-mcp
   ```

### 5.2 Safe Upgrade & Rollback Workflow
1. **Create Pre-Upgrade Backup**:
   ```bash
   python manage.py backup_enterprise --output-dir /var/backups/pre_upgrade_$(date +%Y%m%d)
   ```
2. **Apply Upgraded Code and Migrations**:
   ```bash
   git pull origin main
   python manage.py migrate
   python manage.py check --deploy
   systemctl restart lore-web lore-mcp
   ```
3. **Execute Post-Upgrade Validation**:
   ```bash
   python -m pytest tests/test_final_acceptance_suite.py
   ```
4. **Rollback (if verification fails)**:
   ```bash
   git checkout <previous_commit_tag>
   python manage.py restore_enterprise --backup-dir /var/backups/pre_upgrade_<timestamp> --fix-mismatches
   systemctl restart lore-web lore-mcp
   ```
