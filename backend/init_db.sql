-- ==============================================================================
-- LORE Enterprise - Multi-Database Initialization Script
-- Enables PostgreSQL pgvector, pg_trgm, and UUID extensions.
-- Pre-provisions storage schema for transactional join keys (rule_id, document_id)
-- and multi-tenant row-level security (RLS) isolation.
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table for pgvector dense embeddings and full-text search indexing
CREATE TABLE IF NOT EXISTS lore_pgvector_storage (
    id VARCHAR(64) PRIMARY KEY,
    collection_name VARCHAR(100) NOT NULL,
    vector_data TEXT NOT NULL,
    payload_data TEXT NOT NULL,
    document_id VARCHAR(64),
    rule_id VARCHAR(64),
    workspace_id VARCHAR(64),
    organization_id VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pgvector_coll ON lore_pgvector_storage (collection_name);
CREATE INDEX IF NOT EXISTS idx_pgvector_doc ON lore_pgvector_storage (document_id);
CREATE INDEX IF NOT EXISTS idx_pgvector_rule ON lore_pgvector_storage (rule_id);
CREATE INDEX IF NOT EXISTS idx_pgvector_ws ON lore_pgvector_storage (workspace_id, organization_id);

