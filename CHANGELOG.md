# Changelog

## 0.2.9 — 2026-11-20

GitHub release artifacts are produced by the tag-triggered release workflow
once its native platform matrix and Docker image gates pass. PyPI publication
is a separate, user-owned step on those verified artifacts — this entry does
not assert that upload has happened.

### Changed

- Refreshed project logo and favicon package (`web/app` icons, `web/public`
  favicon/manifest assets, `assets/lore-logo*.png`, and README brand header).
- Polished the setup-site chrome (sidebar navigation/branding, header, charts,
  and related page styling) to match the new brand.

## 0.2.8 — 2026-11-20

GitHub release artifacts are produced by the tag-triggered release workflow
once its native platform matrix and Docker image gates pass. PyPI publication
is a separate, user-owned step on those verified artifacts — this entry does
not assert that upload has happened.

### Changed

- Updated Lore branding and app icons (`web/app/icon.svg`, `web/app/favicon.ico`,
  `web/app/apple-icon.png`, `web/public/icons/`, and the `L` arc logo in
  `AppSidebar` and `SiteHeader`).

## 0.2.7 — 2026-11-20

GitHub release artifacts are produced by the tag-triggered release workflow
once its native platform matrix and Docker image gates pass. PyPI publication
is a separate, user-owned step on those verified artifacts — this entry does
not assert that upload has happened.

### Changed

- Cleaned up unused legacy code and endpoints (`lore.connect.lore_command`,
  `lore.core.budget.context_content_tokens`, `lore.core.personas.set_status`,
  `lore.release.release_tag`, `lore.core.workspace.copy_example`, unused
  `/api/workspace/example`, `/api/graph/build`, `/api/graph`, and
  `/graph/view/` routes, and unused `web/` components/exports).
- Added **Connect installed editors** (`POST /api/connect/agents`) to `/connect`
  and updated `scripts/lore-solo` / `scripts/lore-solo.ps1` to forward all
  current CLI subcommands (`update`, `container`, `govern`, `skill`, `persona`,
  `stats`, `help`).
- Aligned `README.md`, `docs/solo/*`, `docs/ide/*`, `examples/persona-pack/.cursor/mcp.json`,
  and historical `docs/` banners with the `0.2.7` codebase and latest 2×3
  benchmark results.

## 0.2.6 — 2026-11-20

GitHub release artifacts are produced by the tag-triggered release workflow
once its native platform matrix and Docker image gates pass. PyPI publication
is a separate, user-owned step on those verified artifacts — this entry does
not assert that upload has happened.

Rolls up the user-visible changes of 0.2.4 and 0.2.5, which this release
builds on:

- From 0.2.5: token telemetry on the dashboard, autonomous
  `lore-solo skill|persona|stats|govern approve` subcommands and `--full` MCP
  tools, the Intellecta setup UI and Connect onboarding step, and cleaner
  `setup`/`connect` behaviour.
- From 0.2.4: Windows-safe `lore-solo update` / `install` handoff.

### Fixed

- CI: `test_killed_worker_recovers_as_interrupted` could fail on slow runners
  (the retry build reported the stale `interrupted` status), which turned the
  0.2.5 docs commit red. The test now retries until the new build is accepted.
  No runtime code changed.
- Lint: `scripts/build_site_bundle.py` is now executable, resolving ruff
  `EXE001`.

## 0.2.5 — 2026-11-18

GitHub release artifacts are produced by the tag-triggered release workflow
once its native platform matrix and Docker image gates pass. PyPI publication
is a separate, user-owned step on those verified artifacts — this entry does
not assert that upload has happened.

### Added

- Token telemetry: `allocate()` persists `tokens_used` and `token_budget` in
  context call frontmatter, aggregated into `lore/core/usage.py` (`total`,
  `avg`, `max`, `budget`, `tracked_calls`, `series`, `tokens_by_persona`) and
  visualized on the dashboard.
- Autonomous CLI subcommands (`lore-solo skill`, `persona`, `stats`,
  `govern approve`) with `--json` output, and `--full` MCP tools
  (`search_skills`, `install_skill`, `list_inbox`, `list_skills`,
  `setup_persona`, `approve_item`, `check_security`, `check_freshness`,
  `get_telemetry`, plus `include_drafts` on `list_personas`).
- Intellecta ("Soft Bento Glass") UI across the setup dashboard (`web/`):
  `Plus Jakarta Sans` + `JetBrains Mono`, lime/mint accent tokens, desktop
  floating left rail with bottom theme switcher, mobile top bar with centered
  circular navigation pills, hero quick-add combo (`Installed skills`,
  `Created personas`, `+ Add`), `Most called skills` bar chart, token spline
  chart, and themed Graphify codebase viewer.
- Onboarding Connect step (`Welcome -> 1. Connect -> 2. Skills -> 3. Role ->
  4. Project`) writing `.mcp.json`, `.cursor/mcp.json`, and `.vscode/mcp.json`
  with an optional SkillSpector addon prompt.

### Fixed

- `lore-solo setup` surfaces early exit causes (such as port-in-use from
  `~/.lore/setup.log`) and forwards `SIGHUP`/`SIGTERM` so closing the terminal
  stops Django and Next.js child process groups cleanly.
- `lore-solo connect` install command always prints `uvx lore-solo connect`
  instead of leaking local launcher paths.
- Moved `backdrop-blur` to a `fixed inset-0 -z-10` layer in `Shell.tsx` so
  modals no longer clip or scroll inside a `backdrop-filter` containing block.

## 0.2.4 — 2026-11-16

GitHub release artifacts are produced by the tag-triggered release workflow
once its native platform matrix and Docker image gates pass. PyPI publication
is a separate, user-owned step on those verified artifacts — this entry does
not assert that upload has happened.

### Fixed

- Windows: `lore-solo update` / `install` no longer try to replace the running
  tool Python in-place (Access is denied / os error 5). When started from
  `~/.lore/tools/lore-solo`, they hand off to a fresh `uv tool run`
  process after exit. Recovery hint still points at `uvx lore-solo install`.

## 0.2.3 — 2026-11-16

GitHub release artifacts are produced by the tag-triggered release workflow
once its native platform matrix and Docker image gates pass. PyPI publication
is a separate, user-owned step on those verified artifacts — this entry does
not assert that upload has happened.

### Fixed

- Persona draft: longer provider timeout with clearer Gemini/network errors;
  default Gemini model is `gemini-3.5-flash-lite`; model pickers list only
  chat models returned by the live API for the saved key.
- Waiting skill descriptions: YAML frontmatter with unquoted `:` in
  `description` values no longer drops the summary; empty inbox summaries
  are repaired on list.
- Deleting a persona returns its skills to waiting (and recovers skills
  orphaned by earlier deletes) so they can be attached to a new role.

### Added

- Persona skill bulk approve with selection; skills/persona lists sort by
  A–Z, Z–A, or drafts first instead of governance pill clusters on cards.
- Confirm dialog before deleting a persona.
- Draft-role errors show above the Draft role button in the create modal.

## 0.2.2 — 2026-11-14

GitHub release artifacts are produced by the tag-triggered release workflow
once its native platform matrix and Docker image gates pass. PyPI publication
is a separate, user-owned step on those verified artifacts — this entry does
not assert that upload has happened.

### Added

- `lore-solo help` and `lore-solo update`: command catalog plus PyPI upgrade
  that refreshes the cached setup site.
- Setup status lines while the dashboard downloads and starts, with a labeled
  banner explaining the local URL (URL still alone on stdout for scripts).
- Local skill import: multi-file pick, bulk folder import for skills.sh-style
  `SKILL.md` trees, and “Add selected” when only waiting local skills exist.
- Search filters for saved and waiting skills; list descriptions clamped to
  two lines.
- Settings: SkillSpector status and copyable install command; governance
  badge when a scan used SkillSpector.

## 0.2.1 — 2026-11-12

GitHub release artifacts are produced by the tag-triggered release workflow
once its native platform matrix and Docker image gates pass. PyPI publication
is a separate, user-owned step on those verified artifacts — this entry does
not assert that upload has happened.

0.2.1 carries the full 0.2.0 feature set (see below) plus release-pipeline
fixes.

### Fixed

- Release workflow: the `site` job's source-version check now runs after
  `uv sync` via `uv run --frozen python`, so `tomllib` resolves under the
  managed Python 3.12 on every runner — Ubuntu's system Python 3.10 lacks it.
- Release site `build_id`: frontend source hashing now sorts by relative POSIX
  path so Windows Path ordering cannot produce a different `build_id` than
  Linux/macOS. The previous Windows drift made `assemble_site_manifest`
  reject the matrix with "bundle fragments were built from different sources".
- CI portability (pushed ahead of this tag): `--bundle-dir` resolves to an
  absolute path before the setup subprocess changes directory; unit fixtures
  provide a fake `lore-solo` binary and fake Graphify executable instead of
  relying on installed tools; the POSIX file-mode assertion is skipped on
  Windows where permission bits are not representable.

### Notes

- The `v0.2.0` tag remains untouched in history: its release-artifact workflow
  failed before packaging (the Ubuntu `tomllib` issue above), and nothing was
  ever published to GitHub Releases or PyPI for it. `v0.2.1` is retargeted onto
  the build_id fix so the same version ships once the release matrix is green.

## 0.2.0 — 2026-11-12 (unpublished candidate)

This version was tagged but its release workflow failed during the artifact
stage, so it was never published. It exists for history only; 0.2.1 includes
everything below.

### Added

- Full-skill retrieval: `get_skill` returns the complete body of one stable
  skill on demand, alongside the `get_context` summaries.
- Honest decision and citation receipts: `check_applied` and `log_decision`
  record which skills were served and cited — that is the only evidence they
  carry; they are not a code-compliance verdict.
- Advisory IDE standing rules written by `connect` (DevRelay-shaped). They ask
  the agent to call Lore; they are not enforced.
- Durable codebase mapping with freshness status: `map_codebase`, with an
  honest `unavailable` fallback when the optional map extra has no binary
  wheel for the platform. `map_status` and `locate` are admin tools behind
  `lore-solo mcp --full`, not part of the default coding surface.
- Deterministic native install: managed-Python `uvx` bootstrap, pinned
  `release_constraints.txt`, binary wheels only (`--no-build`), optional
  `--map` extra.
- Release site bundles: `lore/site_bundles.json` stays empty in source and is
  generated by the release workflow from verified per-platform archives.
- Optional container path: `lore-solo container mcp|setup|map` against
  locally built `mcp`/`full` images. Verified on rootless Podman; Docker Engine
  and Docker Desktop are covered by argument tests, not local runs.
- Governance layer: built-in ATR static scan plus optional NVIDIA SkillSpector,
  approve-time blocking on critical/high findings, freshness stamps, accepted
  risk with note, and `lore-solo govern` CLI. See docs/solo/GOVERNANCE.md.

### Fixed

- Editing a persona or skill through the supported update APIs now resets the
  item to `draft` and clears the previous governance stamp before writing, so a
  prior approval or accepted risk cannot carry onto changed text. Promotion to
  `stable` requires a fresh successful approve.
- Strict typing and import corrections across the touched modules, plus
  regression coverage for malformed `governance` headers (non-dict values, bad
  `verified_at`) — runtime fallback behavior was already correct and is
  unchanged.
- Web dependencies: nested vulnerable `postcss` under Next replaced via a
  scoped override (Next stays on 15.5.x); the CLI-only `shadcn` package removed
  and its used CSS subset vendored with MIT attribution. `npm audit` is clean
  at audit time — see docs/solo/DEPENDENCY_AUDIT.md.

### Notes

- Supported release targets: Windows x86_64, glibc Linux x86_64, macOS arm64.
  Linux is the platform verified locally; the others are produced and gated in
  the release workflow.
- The product promise is better-guided work, not guaranteed token savings —
  see docs/solo/QUALITY_PLAN.md.
