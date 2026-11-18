---
type: skill
id: skill:database-engineer/database-migration@v1
title: database migration
persona: persona:database-engineer
status: stable
summary: Guidance from wshobson/agents/database-migration.
governance:
  scan:
    tool: lore-static
    at: '2026-11-16T23:46:03Z'
    score: 0
    findings: []
    accepted_risk: false
    accepted_at: null
    accepted_note: null
  freshness:
    status: current
    verified_at: null
    claims_ok: 0
    claims_stale: []
    claims_unverifiable: 0
---
Execute database migrations across ORMs with zero-downtime strategies and rollback procedures. Supports three major ORMs: Sequelize, TypeORM, and Prisma, with migration syntax and CLI commands for each Covers schema transformations including column additions, renames, type changes, and data restructuring with multi-step approaches for large tables Includes transaction-based and checkpoint-based rollback strategies to safely recover from failed migrations Provides zero-downtime deployment patterns using blue-green strategies that decouple schema changes from application code updates Handles cross-database migrations with dialect-specific logic for PostgreSQL, MySQL, and other platforms Database Migration Master database schema and data migrations across ORMs (Sequelize, TypeORM, Prisma), including rollback strategies and zero-downtime deployments. When to Use This Skill Migrating between different ORMs Performing schema transformations Moving data between databases Implementing rollback procedures Zero-downtime deployments Database version upgrades Data model refactoring ORM Migrations Sequelize Migrations
