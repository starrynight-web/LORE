"""Standing text the editor shows the agent before it searches a repository."""

STANDING_INSTRUCTIONS = (
    "Call get_context once with the task sentence. "
    "It returns matching skill summaries, cite_ids, and suggested files to inspect. "
    "Treat file suggestions as advisory, not an edit allowlist. "
    "Inspect source code, follow dependencies, use scoped repository search when suggestions "
    "are missing, stale, or incomplete, and create new files when the task requires them. "
    "Call get_skill with a returned skill id when its summary is insufficient to follow its "
    "instructions; retrieve remaining pages when has_more is true. "
    "Then call check_applied with the decision_id and the skill ids you followed, and call "
    "log_decision with a one-line outcome. "
    "check_applied records citation consistency, not verified code compliance. "
    "If the map is unavailable, continue with skills and normal scoped search. "
    "Call map_codebase only when mapping is available and a build or explicit retry is "
    "useful; do not repeatedly request a missing mapper. "
    "Do not walk .lore/skills or .lore/personas or read graphify-out/graph.json directly; "
    "use Lore tools for knowledge discovery."
)

RULE_BEGIN = "<!-- lore -->"
RULE_END = "<!-- /lore -->"
