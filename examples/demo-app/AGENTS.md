# Agent instructions

This repository's team rules are served by the **Lore** MCP server (`lore`).

- Before creating or editing any file, call the `get_context` tool with `file_path` (repo-relative) and a one-line `intent`.
- Follow the `directive` in the result:
  - `proceed_and_cite`: follow every MUST and SHOULD item and cite the rule IDs you followed.
  - `ask_user`: stop and explain the conflict or uncertainty, show both sides with their IDs, and ask which applies. Do not write the disputed code until the user answers.
  - `stop`: do not make the change; say which rule forbids it.
- Never merge or choose between conflicting rules yourself. When asking the user to choose, present both options neutrally; don't mark either as recommended.
- Before finishing, call `check_compliance` with your diff (or just `file_path` if there's no git repository), then `log_decision` with the `decision_id` and a one-line outcome.
- Items marked Unverified are hints, never rules.
