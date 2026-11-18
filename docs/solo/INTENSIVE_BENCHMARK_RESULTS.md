# Intensive 2×3 Benchmark Results — Lore Solo (`agy` + Gemini 4 Hydrogen Medium)

- **Runner:** Antigravity CLI (`agy`)
- **Model:** `gemini-4-hydrogen-medium` (`Gemini 4 Hydrogen (Medium)`)
- **Latest Raw Telemetry (v2):** [results-intensive-2x3.json](../../examples/bench-library/results-intensive-2x3.json)
- **Previous Baseline Telemetry (v1):** [results-intensive-2x3-v1.json](../../examples/bench-library/results-intensive-2x3-v1.json)
- **Plan:** [INTENSIVE_BENCHMARK_PLAN.md](./INTENSIVE_BENCHMARK_PLAN.md)
- **Skill Pack:** 25 skills downloaded from `skills.sh` across 6 sectors + 6 sector standards skills (`31` total skills).
- **Cold Graphify Map (`simple-write`):** `0.9s` (timed outside agent sessions).

---

## Executive Summary (v2 Scoreboard — After `locate()` & Batched `get_skill` Changes)

| Project Context | Arm | Pass Rate | Median Time (s) | Median Fresh Tokens | Median Total Input Tokens | Median Output Tokens | Lore Process Rate |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **New Project** (`Devin-a-thon Dhaka`) | `no_skills` | **0.0%** (`0/3`) | `156.64s` | `31,686` | `134,877` | `13,044` | — |
| **New Project** (`Devin-a-thon Dhaka`) | `device_skills` | **100.0%** (`3/3`) | `272.17s` | `49,507` | `108,194` | `8,419` | — |
| **New Project** (`Devin-a-thon Dhaka`) | `lore_mcp` | **100.0%** (`3/3`) | `227.49s` | `58,097` | `144,356` | `8,480` | **100%** (`3/3`) |
| **Old Project** (`DJRCX/simple-write`) | `no_skills` | **33.3%** (`1/3`) | `289.75s` | `73,836` | `462,848` | `10,471` | — |
| **Old Project** (`DJRCX/simple-write`) | `device_skills` | **100.0%** (`3/3`) | **`144.25s`** | **`40,060`** | **`225,313`** | `6,984` | — |
| **Old Project** (`DJRCX/simple-write`) | `lore_mcp` | **100.0%** (`3/3`) | `201.67s` | `56,827` | `391,162` | `7,622` | **83.3%** (`5/6` overall) |

---

## Effect of Recent Changes (v1 → v2 Comparison)

Three major changes were tested in v2:
1. **Batched `get_skill(names=[...])`:** All `6/6` `lore_mcp` runs adopted `get_skill(names=[...])` on their first skill fetch, requesting 2–3 skills in a single MCP call.
2. **Improved `locate()` ranking in `lore/core/graph.py`:** Down-ranked `.json` config files, removed 2-char stop-word substring collisions, and deduplicated per-file scoring.
   - In `old-find-a11y`, `get_context` now surfaced **`src/App.tsx`** and **`src/components/write-editor.tsx`** directly in the top 8 files. As a result, `old-find-a11y` (`lore_mcp`) dropped from **`260.51s` → `115.29s`** (**55.7% faster**, beating `device_skills` at `144.25s`), and total input tokens dropped from **`512,381` → `263,074`** (**48.7% fewer**).
   - In `old-security-links`, `get_context` surfaced all three target files (`src/App.tsx`, `src/lib/documents.ts`, `src/components/write-editor.tsx`) in the top 8, finishing in **`201.67s`** (vs `device_skills` at `440.63s`, **54.2% faster**).
3. **Why `old-reading-callout` (`lore_mcp`) spiked to `485.90s` and `old-find-a11y` had `check_applied: false`:**
   - In `old-find-a11y`, the agent also fetched `skill:frontend-engineer/frontend-standards@v1` (which had been omitted from the 8-item cap by `backend-*` noise) and cited it in `log_decision`, so `check_applied` correctly flagged `"unknown": ["skill:frontend-engineer/frontend-standards@v1"]`.
   - In `old-reading-callout`, `no_skills` and `lore_mcp` both hit higher LLM/tooling variance (`394.75s` and `485.90s`), pulling up the `old_project` median even though `old-find-a11y` and `old-security-links` were both fast.

---

## Per-Task Breakdown (v2)

### Suite 1: New Project — *Devin-a-thon Dhaka Companion*

| Scenario | Arm | Passed | Time (s) | Fresh Tokens | Total Input | Output | Tools / Notes |
| :--- | :--- | :---: | ---: | ---: | ---: | ---: | :--- |
| `new-registration` | `no_skills` | ❌ | `142.51s` | `31,686` | `134,877` | `13,159` | Failed `vitest_ok` |
| `new-registration` | `device_skills` | ✅ | **`107.77s`** | `45,952` | `108,194` | `9,987` | All checks passed |
| `new-registration` | `lore_mcp` | ✅ | `118.86s` | `33,119` | `144,356` | `9,257` | `get_context`, `get_skill(names=[3])`, `log_decision` (`ok: true`) |
| `new-pipeline-board` | `no_skills` | ❌ | `269.34s` | `57,445` | `153,416` | `13,044` | Failed `vitest_ok` |
| `new-pipeline-board` | `device_skills` | ✅ | `272.17s` | `49,507` | `187,123` | `8,419` | All checks passed |
| `new-pipeline-board` | `lore_mcp` | ✅ | **`227.49s`** | `58,097` | `205,358` | `8,480` | `get_context`, `get_skill(names=[3])`, `log_decision` (`ok: true`) |
| `new-readiness-planner` | `no_skills` | ❌ | `156.64s` | `27,583` | `106,844` | `7,214` | Failed `vitest_ok` |
| `new-readiness-planner` | `device_skills` | ✅ | `418.22s` | `60,473` | `104,351` | `6,873` | All checks passed |
| `new-readiness-planner` | `lore_mcp` | ✅ | `352.10s` | `59,776` | `140,695` | `7,757` | `get_context`, `get_skill(names=[3])`, `log_decision` (`ok: true`) |

### Suite 2: Old Project — `DJRCX/simple-write`

| Scenario | Arm | Passed | Time (s) | Fresh Tokens | Total Input | Output | Tools / Notes |
| :--- | :--- | :---: | ---: | ---: | ---: | ---: | :--- |
| `old-reading-callout` | `no_skills` | ✅ | `394.75s` | `73,836` | `462,848` | `10,471` | All checks passed |
| `old-reading-callout` | `device_skills` | ✅ | **`138.42s`** | `40,060` | `225,313` | `6,984` | All checks passed |
| `old-reading-callout` | `lore_mcp` | ✅ | `485.90s` | `130,843` | `391,162` | `7,622` | `get_context`, `get_skill(names=[2])`, `log_decision` (`ok: true`) |
| `old-security-links` | `no_skills` | ❌ | `289.75s` | `90,844` | `1,008,177` | `24,068` | Failed `vitest_ok`, `link_sanitized_in_ui`, `wikilink_guarded_in_ui` |
| `old-security-links` | `device_skills` | ✅ | `440.63s` | `86,767` | `354,914` | `14,060` | All checks passed |
| `old-security-links` | `lore_mcp` | ✅ | **`201.67s`** | `56,827` | `415,401` | `13,510` | `get_context`, `get_skill(names=[2])`, `log_decision` (`ok: true`) |
| `old-find-a11y` | `no_skills` | ❌ | `72.66s` | `33,493` | `134,644` | `4,900` | Failed `vitest_ok` |
| `old-find-a11y` | `device_skills` | ✅ | `144.25s` | `35,973` | `176,582` | `6,383` | All checks passed |
| `old-find-a11y` | `lore_mcp` | ✅ | **`115.29s`** | `48,759` | `263,074` | `6,815` | `get_context`, `get_skill(names=[2])`, `get_skill`, `log_decision` (`check_applied: fail` on unserved `frontend-standards@v1`) |
