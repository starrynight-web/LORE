"""Standing text the editor shows the agent before it searches a repository."""

STANDING_INSTRUCTIONS = (
    "Call get_context once with the task sentence. "
    "It returns matching skill summaries, cite_ids, and the files to open. "
    "Edit only those files. "
    "Then call check_applied with the decision_id and the skill ids you followed. "
    "Then call log_decision with a one-line outcome. "
    "If the note says the map is missing or building, call map_codebase once and keep working "
    "from the summaries. Do not walk the tree while the map builds. "
    "Do not read .lore/skills, .lore/personas, or graphify-out/graph.json."
)

RULE_BEGIN = "<!-- lore -->"
RULE_END = "<!-- /lore -->"
