---
type: skill
id: skill:workspace/find@v1
title: find
persona: persona:workspace
status: draft
summary: Quickly find pages or databases in Notion by title keywords. Returns precise
  matches rather than comprehensive results.
---
# Notion Find

Use the Notion MCP server to quickly locate pages or databases whose titles match the query.

## Behavior

- Treat the query as fuzzy search terms for titles (e.g. "Q1 plan", "product launch spec").
- Search both:
  - Individual pages
  - Databases
- Return a short list of the best matches with:
  - Title
  - Type (page or database)
  - Location / parent (if available)
- Prefer precision over recall: better to show 5-10 very relevant results than 50 noisy ones.

If nothing is found, say so clearly and suggest alternate search terms.
