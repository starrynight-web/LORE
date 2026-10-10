# MCP client compatibility

Fill this in from [smoke-test.md](smoke-test.md) runs. Use ✅ (works), ⚠️ (partly, add a note), ❌ (not supported), or leave it blank (not tested yet).

| Capability | Cursor | VS Code | Antigravity | Claude Desktop |
| --- | --- | --- | --- | --- |
| Server starts from project config | ✅ ¹ | ✅ | ❌ ⁹ | n/a |
| Lists 12 tools | ✅ | ✅ | ✅ | |
| Shows server instructions to the model | | | ✅ ¹⁰ | |
| Agent calls `get_context` unprompted (with rule file) | ✅ | ✅ ⁶ | ✅ | n/a |
| Asks the user on `ask_user`, neutrally | ✅ | ✅ ⁷ | ✅ | ✅ ¹² |
| Uses `structuredContent` (vs. text only) | | | | |
| Follows `resource_link` items | | | | |
| Resource picker shows `lore://` resources | ✅ ⁴ | | | ✅ ¹³ |
| Prompts available (slash or picker) | ✅ | ✅ | ✅ | ✅ ¹³ |
| `${userHome}` expanded in `command` | ✅ | ✅ | n/a ⁹ | n/a |
| `${workspaceFolder}` expanded in args | ² | ² | n/a ⁹ | n/a |
| Asks before write tools | ⚠️ ⁵ | ✅ | ✅ | ✅ |
| Demo scenario passes (rows 1–10) | ✅ ³ | ✅ ⁸ | ✅ ¹¹ | n/a |
| MCP Apps (`ui://`) | | | | |

Tested versions:

- Lore: 0.1.0-dev (2026-10-08)
- Cursor: 3.21.18
- VS Code: 1.140.0 (built-in agent mode)
- Antigravity: 2.19.1 (Gemini 3.8 Flash, High)
- Claude Desktop: 2.9939.4 (Linux, Free plan, Haiku 5.5)

Notes:

1. Cursor reads `.cursor/mcp.json` only at the workspace root. Opening the parent of the demo folder shows no `lore` server, and Cursor creates an empty `mcp.json` there.
2. Can't tell from this run: Lore finds `.lore/` from the working directory even when the variable isn't expanded.
3. Cursor, 2026-10-08, verified from `.lore/audit.log` and `dec-0001.md`. The call order was `get_context` (conflict, `dec-0001`), then `check_compliance` (`dec-0002`), then `log_decision` (outcome attached to `dec-0001`). The agent asked the user to choose, implemented `refresh-rotation@v2`, and cited all four item IDs. It also noted that `conf-0031` stays open for @security. `check_compliance` returned `conflict` rather than `abstain` because `conf-0031` is still open; see row 9 of the smoke test.
4. Customize → MCPs shows 16 resources: the 14 from the demo bundle plus the two decision records, `dec-0001` and `dec-0002`. Prompts appear as `/` commands in chat.
5. `log_decision` ran without an approval prompt. Cursor decides this from its own run-mode and allowlist settings, not from Lore's `readOnlyHint`/`destructiveHint` annotations. This is acceptable because Lore's write tools can't approve knowledge or delete anything. If you want a prompt before every write, set Cursor's run mode to ask before MCP tools.
6. VS Code (Copilot agent mode), 2026-10-08, `dec-0003`. The agent read the source files and `.lore/conflicts/conf-0031.md` directly, then called `get_context` before making any edit. VS Code shows `log_decision`'s input as its own wrapper (`serverName`/`toolName`), but the real arguments reached Lore and the outcome was recorded on `dec-0003`.
7. In the first run the agent labelled the rotation option "(Recommended)". The server instructions, the conflict "Next:" line and the rule files now say to present both options neutrally, and the re-run asked without a recommendation.
8. Re-run on a fresh copy of `examples/demo-app`, 2026-10-08. The call order was `get_context` (`dec-0001`), `get_context` again with the user's choice in the intent (`dec-0002`), then `log_decision` (choice recorded on `dec-0002`), the edit, `check_compliance` on `file_path` only (no git repository, `dec-0003`), then `log_decision` (outcome on `dec-0003`). `check_compliance` still returned `conflict` because `conf-0031` is open, and the agent did not ask again. The user chose `refresh-static@v1` and the agent cited it with `jwt-expiry@v3`, `no-token-logging@v1` and `error-wrapping@v2`. The first run, on a workspace that already had the Cursor run's endpoint, is what showed that `check_compliance` needed a `file_path`-only mode.
9. Antigravity, 2026-10-08. It loaded `AGENTS.md` and `.agents/rules/lore.md` from the workspace, but not `.agents/mcp_config.json`: `lore` was missing from Installed MCP Servers and never started. Add it to the global `~/.gemini/config/mcp_config.json` with absolute paths instead. Antigravity also has a shared token budget for rules, skills and MCP tools; when it's exceeded, it drops large customizations, MCP tools included. Check the Mcp Tools breakdown under Customizations shows `lore` with nothing excluded.
10. Antigravity caches each server's instructions and tool schemas under `~/.gemini/antigravity/mcp/<server>/` (`instructions.md` plus one JSON file per tool). The model loads a schema when it needs it: it read `get_context.json`, `check_compliance.json` and `log_decision.json` before calling those tools.
11. Antigravity with Gemini 3.8 Flash (High), 2026-10-08, verified from `.lore/audit.log` and Antigravity's own transcript. The call order was `get_context` (conflict, `dec-0001`), then a neutral `ask_question` that listed both rule IDs; the user chose `refresh-rotation@v2`. Next came `check_compliance` on the unchanged file (`dec-0002`), `get_context` for `src/auth/token_test.go` (`dec-0003`), the edit, `check_compliance` again (`dec-0004`), and `log_decision` (outcome on `dec-0001`). The agent cited all four item IDs. The run took about six minutes, mostly spent reading `.lore/` files directly and running `go vet`; Lore's calls took under 70 ms each. The agent also first read an unrelated plugin skill, `dak-setup/SKILL.md`, because of the user's other installed skills.
12. Claude Desktop, 2026-10-08. Prompt: "Using Lore, what rules apply to src/auth/token.go if I add a refresh-token endpoint?" Claude called `get_context` (conflict, `dec-0001`), listed the rules that apply either way, then explained both sides of `conf-0031` without recommending one and named @security as the owner. After the user chose `refresh-static@v1`, it called `log_decision` (outcome on `dec-0001`, all four IDs) and said it couldn't edit the file from a chat. Claude Desktop reads its config only at startup, and if the file is invalid JSON it ignores it and logs "Refusing config write: the load was degraded". After fixing the file, quit the app completely (it keeps running in the tray) and start it again.
13. In Claude Desktop, the **+** menu lists 18 items from `lore`: that matches the 4 prompts plus the 14 resources in the demo bundle, without `dec-0001`, which was created during the chat. Claude Desktop may read the resource list once and not refresh it when Lore reports a change; not confirmed. The tool count wasn't checked.
