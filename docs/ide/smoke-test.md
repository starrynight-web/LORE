# IDE smoke test

Run this the same way in Cursor, VS Code and Antigravity. Claude Desktop gets the shorter check in [claude-desktop.md](claude-desktop.md). Record results in [compat-matrix.md](compat-matrix.md).

## Setup

1. `go install ./cmd/lore` from the Lore repo, then check that `~/go/bin/lore version` prints a version.
2. Copy the demo app somewhere disposable, so decision files don't pile up in the repo: `cp -r examples/demo-app /tmp/lore-demo`.
3. Open `/tmp/lore-demo` as the workspace. Its `.cursor/`, `.vscode/` and `.agents/` configs and rule files are already in place.
4. Confirm the IDE lists `lore` with 12 tools.

## Scenario

Start a new agent chat and send exactly:

> Add a refresh-token endpoint in src/auth/token.go.

Pass if all of these happen:

| # | Expected | How to check |
| - | -------- | ------------ |
| 1 | The agent calls `get_context` on its own, before editing | tool-call trace in chat |
| 2 | The result has `verdict: conflict`, `directive: ask_user`, `conf-0031` | expand the tool result |
| 3 | The agent explains both rules (rotate on every use vs. 30-day static) and asks you to choose | chat reply |
| 4 | The agent does not write the refresh logic before you answer | no edit to `token.go` yet |
| 5 | Rule IDs are cited, e.g. `rule:auth/refresh-rotation@v2` | chat reply |
| 6 | `.lore/decisions/dec-0001.md` exists | file tree |
| 7 | Superseded `jwt-expiry@v2` and draft `session-cookie@v1` are never mentioned as rules | chat reply |

Then answer "use rotation" and check:

| # | Expected |
| - | -------- |
| 8 | The agent implements rotation and follows `jwt-expiry@v3` (15 minutes) and `no-token-logging@v1` |
| 9 | It calls `check_compliance` with its diff. While `conf-0031` is open the verdict is `conflict` again; the agent should say your choice covers it rather than ask a second time, and should check the MUST rules by hand. Without an open conflict the verdict is `abstain` ("could not verify automatically"). |
| 10 | It calls `log_decision` with `dec-0001`; the decision file gains an Outcomes entry |

## Prompts and resources

- Run the `explain_conflict` prompt from the IDE's prompt UI. It should describe `conf-0031` without picking a side.
- Run `validate_change` after an edit.
- If the IDE has a resource picker, attach `lore://rules/auth/jwt-expiry@v3`.

## Afterwards

- `lore trace dec-0001` in the demo folder shows what was used and excluded.
- `.lore/audit.log` has one line per tool call.
