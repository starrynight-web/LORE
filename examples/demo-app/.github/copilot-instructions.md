Team rules for this repository come from the `lore` MCP server.

- Before creating or editing a file, call the `get_context` tool with `file_path` (repo-relative) and a one-line `intent`.
- Obey the returned `directive`. On `ask_user`, stop, explain both sides of the conflict with their rule IDs, and ask which applies before writing that code. On `stop`, do not make the change.
- Never merge or pick between conflicting rules yourself. When asking the user to choose, present both options neutrally; don't mark either as recommended.
- Cite the rule IDs you followed, e.g. `[rule:auth/jwt-expiry@v3]`.
- Before finishing, call `check_compliance` with the diff (or just `file_path` if there's no git repository), then `log_decision` with the `decision_id`.
