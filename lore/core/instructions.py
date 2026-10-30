"""Standing text the editor shows the agent before it searches a repository."""

STANDING_INSTRUCTIONS = (
    "Call get_context once with the task sentence. "
    "It returns the matching skill summaries and the files to open. Edit those files. "
    "If the note says the map is missing or building, call map_codebase once and keep working "
    "from the summaries. Do not walk the tree while the map builds. "
    "Call get_skill only for the one skill you are about to apply. "
    "Do not read .lore/skills, .lore/personas, or graphify-out/graph.json."
)

RULE_BEGIN = "<!-- lore -->"
RULE_END = "<!-- /lore -->"
