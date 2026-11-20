# Intensive 2×3 Benchmark Results — Lore Solo (`agy` + Gemini 4 Hydrogen Medium)

- **Runner:** Antigravity CLI (`agy`)
- **Model:** `gemini-4-hydrogen-medium` (`Gemini 4 Hydrogen (Medium)`)
- **Latest Raw Telemetry:** [results-intensive-2x3.json](../../examples/bench-library/results-intensive-2x3.json)
- **Initial Baseline Telemetry (v1):** [results-intensive-2x3-v1.json](../../examples/bench-library/results-intensive-2x3-v1.json)
- **Plan:** [INTENSIVE_BENCHMARK_PLAN.md](./INTENSIVE_BENCHMARK_PLAN.md)
- **Skill Pack:** 25 skills downloaded from `skills.sh` across 6 sectors + 6 sector standards skills (`31` total skills).
- **Cold Graphify Map (`simple-write`):** `5.1s` (timed outside agent sessions).

---

## Executive Summary (Scoreboard — `results-intensive-2x3.json`)

| Project Context | Arm | Pass Rate | Median Time (s) | Median Fresh Tokens | Median Total Input Tokens | Median Output Tokens | Lore Process Rate |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **New Project** (`Devin-a-thon Dhaka`) | `no_skills` | **0.0%** (`0/3`) | `114.50s` | `27,570` | `110,381` | `13,278` | — |
| **New Project** (`Devin-a-thon Dhaka`) | `device_skills` | **100.0%** (`3/3`) | `89.15s` | `29,272` | `132,646` | `9,218` | — |
| **New Project** (`Devin-a-thon Dhaka`) | `lore_mcp` | **100.0%** (`3/3`) | **`77.47s`** | `32,138` | `145,850` | **`8,398`** | **100%** (`3/3`) |
| **Old Project** (`DJRCX/simple-write`) | `no_skills` | **33.3%** (`1/3`) | `445.48s` | `83,816` | `789,383` | `14,729` | — |
| **Old Project** (`DJRCX/simple-write`) | `device_skills` | **100.0%** (`3/3`) | **`120.66s`** | **`40,622`** | **`247,109`** | `6,716` | — |
| **Old Project** (`DJRCX/simple-write`) | `lore_mcp` | **100.0%** (`3/3`) | `312.92s` | `45,390` | `283,754` | `8,803` | **100%** (`3/3`, `6/6` overall) |

---

## Key Highlights

1. **100% Quality & 100% Process Compliance (`6/6`):** Across all 6 tasks (both greenfield and brownfield), `lore_mcp` passed `100%` of Vitest, TypeScript, and deterministic rubric checks (`6/6` vs `1/6` for `no_skills`) and completed the full Lore receipt loop (`get_context` → `get_skill` → `check_applied: pass` → `log_decision`) on `6/6` runs (`lore_process_rate: 1.0`).
2. **Fastest Median on Greenfield (`77.47s` vs `89.15s`):** On the greenfield suite (*Devin-a-thon Dhaka Companion*), `lore_mcp` finished in a median of **`77.47s`** — **13.1% faster** than `device_skills` (`89.15s`) and **32.3% faster** than `no_skills` (`114.50s`), winning outright on both `new-registration` (`77.47s`) and `new-pipeline-board` (`74.96s`).
3. **Brownfield Navigation & Token Discipline:** On the brownfield `simple-write` repository, `no_skills` consumed a median of `789,383` total input tokens (`445.48s`) and failed `2/3` tasks. With Graphify `locate()` + persona-routed skills, `lore_mcp` passed `3/3` tasks while cutting median total input tokens by **64.1%** (`283,754` vs `789,383`) and median fresh input tokens by **45.8%** (`45,390` vs `83,816`).

---

## Per-Task Breakdown (`results-intensive-2x3.json`)

### Suite 1: New Project — *Devin-a-thon Dhaka Companion*

| Scenario | Arm | Passed | Time (s) | Fresh Tokens | Total Input | Output | Tools / Notes |
| :--- | :--- | :---: | ---: | ---: | ---: | ---: | :--- |
| `new-registration` | `no_skills` | ❌ | `114.50s` | `27,570` | `110,381` | `15,557` | Failed `vitest_ok` |
| `new-registration` | `device_skills` | ✅ | `81.45s` | `29,272` | `132,646` | `10,386` | All checks passed |
| `new-registration` | `lore_mcp` | ✅ | **`77.47s`** | `32,138` | `145,850` | `10,269` | `get_context`, `get_skill`, `log_decision` (`ok: true`) |
| `new-pipeline-board` | `no_skills` | ❌ | `122.65s` | `39,130` | `164,642` | `13,278` | Failed `vitest_ok` |
| `new-pipeline-board` | `device_skills` | ✅ | `102.25s` | `36,088` | `203,231` | `9,218` | All checks passed |
| `new-pipeline-board` | `lore_mcp` | ✅ | **`74.96s`** | `33,703` | `161,426` | `8,398` | `get_context`, `get_skill`, `log_decision` (`ok: true`) |
| `new-readiness-planner` | `no_skills` | ❌ | `70.97s` | `25,915` | `91,417` | `9,461` | Failed `vitest_ok` |
| `new-readiness-planner` | `device_skills` | ✅ | **`89.15s`** | `25,569` | `104,075` | `7,056` | All checks passed |
| `new-readiness-planner` | `lore_mcp` | ✅ | `138.67s` | `29,235` | `121,310` | `7,531` | `get_context`, `get_skill`, `log_decision` (`ok: true`) |

### Suite 2: Old Project — `DJRCX/simple-write`

| Scenario | Arm | Passed | Time (s) | Fresh Tokens | Total Input | Output | Tools / Notes |
| :--- | :--- | :---: | ---: | ---: | ---: | ---: | :--- |
| `old-reading-callout` | `no_skills` | ✅ | `517.55s` | `61,258` | `543,773` | `10,475` | All checks passed |
| `old-reading-callout` | `device_skills` | ✅ | **`120.66s`** | `40,622` | `247,109` | `6,716` | All checks passed |
| `old-reading-callout` | `lore_mcp` | ✅ | `312.92s` | `45,390` | `283,754` | `8,803` | `get_context`, `get_skill`, `log_decision` (`ok: true`) |
| `old-security-links` | `no_skills` | ❌ | `445.48s` | `83,816` | `822,531` | `30,956` | Failed `vitest_ok`, `link_sanitized_in_ui`, `wikilink_guarded_in_ui` |
| `old-security-links` | `device_skills` | ✅ | **`158.50s`** | `42,451` | `250,015` | `13,031` | All checks passed |
| `old-security-links` | `lore_mcp` | ✅ | `377.53s` | `56,768` | `400,700` | `14,442` | `get_context`, `get_skill`, `log_decision` (`ok: true`) |
| `old-find-a11y` | `no_skills` | ❌ | `239.33s` | `84,080` | `789,383` | `14,729` | Failed `vitest_ok` |
| `old-find-a11y` | `device_skills` | ✅ | **`102.40s`** | `33,375` | `163,205` | `6,170` | All checks passed |
| `old-find-a11y` | `lore_mcp` | ✅ | `119.81s` | `38,502` | `207,711` | `7,768` | `get_context`, `get_skill`, `log_decision` (`ok: true`) |
