---
type: skill
id: skill:workspace/lecture-study-notion@v1
title: lecture study notion
persona: persona:workspace
status: draft
summary: Extracts lecture slides (PPTX/PDF), structures comprehensive quiz-oriented
  study lessons, and syncs them to Notion workspaces via Zapier MCP. Handles zero-depen
---
# Lecture Study Sync to Notion

Turn slide decks and lecture presentations into comprehensive, exam-ready study lessons and publish them directly to Notion using Zapier MCP.

## Overview & Workflow

```
+------------------+      +--------------------+      +----------------------+
|  1. Extract PPTX | ---> |  2. Structure Note | ---> |  3. Sync to Notion   |
| (Slide text/tbl) |      | (Quiz-Ready Guide) |      | (Zapier Streamable)  |
+------------------+      +--------------------+      +----------------------+
```

---

## Step 1: Extract Slide Content

Use the zero-dependency Python extractor in `scripts/extract_pptx.py` to parse text and tables from PowerPoint presentations without external packages:

```bash
python3 scripts/extract_pptx.py "/path/to/lecture.pptx"
```

For machine-readable JSON output:
```bash
python3 scripts/extract_pptx.py "/path/to/lecture.pptx" --json
```

---

## Step 2: Structure the Study Lesson

Structure the study lesson specifically for academic exams and quizzes. Follow this schema:

1. **Header & Objectives**: Course name, lecture title, key exam focus areas.
2. **Foundational Contrasts**: Paradigm comparisons (e.g. SPM vs. OOP, Compiled vs. Interpreted).
3. **Core Topic Breakdown**: Clear definitions, real-world analogies, and memory triggers.
4. **Code Walkthroughs**: Syntactically clean code snippets illustrating concepts in action.
5. **Solved Slide Exercises**: Fully worked-out solutions for all practice questions, domain modeling prompts, and tricky code traces.
6. **🎯 Quiz Quick-Review Summary**: High-yield bullet points for last-minute review.

---

## Step 3: Notion & Zapier MCP Integration

Use `scripts/zapier_notion_client.py` for reliable, direct interaction with Zapier MCP over Streamable HTTP.

### Initializing the Client
```python
from scripts.zapier_notion_client import ZapierNotionClient

client = ZapierNotionClient()
```
The client automatically discovers your Zapier endpoint from `~/.gemini/config/mcp_config.json`.

### Locating the Target Page / Column
```python
# 1. Search for parent page by title
pages = client.find_page_by_title("Mid Subjects:")

# 2. Inspect child blocks (e.g., column_list, column, embed)
children = client.get_block_children(target_page_id)
```

---

## Step 4: Writing Content Safely to Notion

### Critical Rule: The Notion Column Trap
> [!CAUTION]
> **Never delete an empty placeholder paragraph from a column before adding content.**
> In Notion, if a `column` reaches 0 children, Notion automatically archives/deletes the column. Always append new content first, then delete the placeholder.

### Safe Column Population
Use `safe_populate_column()`, which guarantees column preservation by appending markdown first and then cleaning placeholder blocks:

```python
client.safe_populate_column(column_id, markdown_text)
```

### Appending to Standard Pages
For standard pages (not columns), use `append_markdown()`:
```python
client.append_markdown(page_id, markdown_text)
```
The client automatically splits long markdown into clean semantic chunks (under 1500 chars) and applies request throttling to prevent payload timeouts or Notion block limits.

---

## Complete Example Workflow

```python
import os
from scripts.extract_pptx import extract_slide_content
from scripts.zapier_notion_client import ZapierNotionClient

# 1. Extract slide text
slides = extract_slide_content("/home/user/Class/Lecture_1.pptx")

# 2. Compose markdown study lesson based on extracted slides
lesson_markdown = \"\"\"# 📘 Lecture 1 Study Guide
### 1. Key Concepts
...
### 2. Solved Exercises
...
\"\"\"

# 3. Publish to Notion column
client = ZapierNotionClient()
target_column_id = "3eb4dd44-fa4a-805e-92ec-f08b06e990b7"
client.safe_populate_column(target_column_id, lesson_markdown)
print("Study lesson synced successfully!")
```

---

## Additional Resources

- For Notion API data sources, database queries, and Streamable HTTP headers, see [reference.md](reference.md).
