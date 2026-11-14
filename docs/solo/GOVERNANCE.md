# Solo governance

Lore Solo routes skills through personas. Governance is the content-trust layer on top of that: scan before `draft` becomes `stable`, stamp freshness, and surface soft aging in `get_context`.

## What runs

1. **Built-in ATR static scan** (always). Vendored Agent Threat Rules under `lore/core/governance/rules/`, plus Lore-owned `LORE-P9` whitespace padding. Findings carry ATR ids, OWASP `AST01`, and SkillSpector-compatible categories (`P1`, `P2`, `P3`, `P9`, …).
2. **Optional NVIDIA SkillSpector** when `skillspector` is on `PATH`. Invoked as `skillspector scan … --no-llm --format json`. Missing SkillSpector is fine; ATR still runs.
3. **Owned freshness checks** (never block approve). Path/script claim verification, `verified_at` stamp, optional `covers` git drift, and a 30-day `product`/`product_version` aging heuristic.

## Approve policy (2A)

| Signal | Approve |
| --- | --- |
| critical / high findings | Blocked unless `accept_risk: true` |
| medium / low findings | Allowed (badges remain) |
| stale / aging claims | Allowed; item `freshness` becomes `aging` |

`POST /api/items/<id>/approve` with body `{"accept_risk": true, "note": "…"}` records the override in `governance.scan`.

## Edits reset trust

Approval is bound to the exact text that was scanned. When a persona or skill is
changed through the supported update APIs (`update_persona`, `update_skill`, or
the setup site item POSTs), any change to title, summary, or body resets the item
to `draft` before the write and drops the previous `governance` header, so a risk
acceptance or freshness stamp cannot silently attach to different text. The
fresh draft is re-scanned for badges, and promotion to `stable` only happens
through a new, successful approval. Saving identical content keeps the current
status and approval. Editing files directly on disk bypasses these update APIs
and is not guaranteed to be enforced — serve paths still require `stable`, but
out-of-band edits are not re-scanned until the next approve or update call.

## Frontmatter

```yaml
governance:
  scan:
    tool: lore-static
    at: 2026-11-10T12:00:00Z
    score: 0
    findings: []
    accepted_risk: false
  freshness:
    status: current
    verified_at: 2026-11-10
    claims_ok: 0
    claims_stale: []
    claims_unverifiable: 0
```

## CLI

```bash
lore-solo govern scan [path] [--json]
lore-solo govern check [path] [--json]
lore-solo doctor   # includes SkillSpector + knowledge counts
```

## Install SkillSpector (optional)

```bash
uv tool install git+https://github.com/NVIDIA/skillspector.git
```

The setup site Settings page shows whether SkillSpector is on `PATH` and offers the same install command to copy. Approvals use it automatically when present; Lore’s built-in ATR scan always runs.

## Standards

- Detection rules: [Agent Threat Rules](https://github.com/Agent-Threat-Rule/agent-threat-rules) (MIT; see `lore/core/governance/rules/NOTICE`)
- Risk framing: [OWASP Agentic Skills Top 10 — AST01](https://owasp.org/projects/agentic-skills-top-10)
- Enrichment / category interop: [NVIDIA SkillSpector](https://github.com/NVIDIA/skillspector)
