"""Standing text the editor shows the agent before it searches a repository."""

STANDING_INSTRUCTIONS = (
    "Call get_context once with the task sentence. "
    "It returns matching skill summaries, cite_ids, and suggested files to inspect. "
    "Treat file suggestions as advisory, not an edit allowlist. "
    "Inspect source code, follow dependencies, use scoped repository search when suggestions "
    "are missing, stale, or incomplete, and create new files when the task requires them. "
    "Call get_skill with a returned skill id (or names=[...] to fetch multiple at once) when its "
    "summary is insufficient to follow its instructions; retrieve remaining pages when has_more is true. "
    "When finished, call log_decision once with the decision_id, a one-line outcome, "
    "and rule_ids set to the skill ids you followed (this records both the citation "
    "receipt and outcome; citations are not verified code compliance). "
    "If the map is unavailable, continue with skills and normal scoped search. "
    "Call map_codebase only when mapping is available and a build or explicit retry is "
    "useful; do not repeatedly request a missing mapper. "
    "Do not walk .lore/skills or .lore/personas or read graphify-out/graph.json directly; "
    "use Lore tools for knowledge discovery."
)

RULE_BEGIN = "<!-- lore -->"
RULE_END = "<!-- /lore -->"
