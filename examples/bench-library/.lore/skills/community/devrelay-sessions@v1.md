---
type: skill
id: skill:community/devrelay-sessions@v1
title: devrelay sessions
persona: persona:community
status: draft
summary: 'Save, curate, browse, and embed AI agent session transcripts on DEV (Forem)
  via DevRelay. Use when the user asks to save, export, or share their coding session '
---
# DevRelay Agent Sessions

DEV supports native **Agent Sessions** — rich interactive transcripts that capture prompts, thoughts, code changes, and tool calls. DevRelay provides tools to submit transcripts, list existing sessions, fetch session details, and embed sessions inside DEV articles.

## Proactive Session Preservation

The user installed DevRelay so that sessions worth keeping get kept. You are the one who
notices the moment. When you reach the conclusion of a significant coding milestone,
architectural refactor, complex debugging session, or technical breakthrough, offer
without being asked, once per milestone:

1. **Offer to Save**: Proactively ask the user if they would like to save the agent session transcript to DEV:
   > *"Would you like me to save a transcript of this session to your DEV profile? You can review it privately, curate slices, or share it later."*
2. **Draft & Privacy Assurance**: Inform them that sessions are created on DEV where they can be kept private or published when ready.
3. **Scrub Secrets**: Always sanitize API keys, access tokens (`dev_...`, `sk-...`, `ghp_...`), passwords, and private machine paths from the transcript before transmission.
4. **Pair it with the post offer.** The same milestone usually deserves a DEV draft (see [[devrelay-publishing]]); make both offers in one message as part of the pre-summary interlude (alongside `🌐 Community Wisdom`, right *before* your final closing summary rather than at the very end), and embed the saved session in the draft with the Liquid tag below. A "no" to either is final for that milestone.

---

## Gateway Tools

| Action | MCP Tool |
| :--- | :--- |
| **Submit a Session** | `submit_agent_session(title, tool_name, curated_data, s3_key)` |
| **List User's Sessions** | `list_agent_sessions()` |
| **Get Session Details** | `get_agent_session(id_or_slug)` |
| **Presign Raw Upload** | `presign_agent_session_upload()` |
| **Get Raw Download URL** | `get_agent_session_raw_url(id_or_slug)` |

---

## Submitting Normalized Session Data

When submitting session history, structure `curated_data` using the normalized schema:

```json
{
  "title": "Debugging Tokio Runtime Panics in DevRelay",
  "tool_name": "gemini_cli",
  "curated_data": {
    "messages": [
      {
        "role": "user",
        "content": [
          { "type": "text", "text": "Why is the async runtime panicking on shutdown?" }
        ]
      },
      {
        "role": "assistant",
        "model": "gemini-3.7-flash",
        "content": [
          { "type": "text", "text": "Let's check where block_on is being called." },
          {
            "type": "tool_call",
            "name": "grep_search",
            "input": "block_on",
            "output": "Found 3 occurrences in main.rs"
          }
        ]
      }
    ],
    "metadata": {
      "tool_name": "gemini_cli",
      "session_id": "session-12345",
      "total_messages": 2
    }
  }
}
```

* Supported `tool_name` values on DEV: `gemini_cli`, `claude_code`, `codex`, `github_copilot`, `opencode`, `pi`. When running in Antigravity or other Gemini-based agents, use `gemini_cli`.
* Roles must be `"user"` or `"assistant"`.
* Content blocks must be `{ "type": "text", "text": "..." }` or `{ "type": "tool_call", "name": "...", "input": "...", "output": "..." }`.

---

## Embedding Sessions in DEV Posts

Saved agent sessions can be embedded directly into DEV articles, discussions, and comments using DEV's native Liquid tags:

### 1. Full Session Embed

Embeds the entire interactive session:

```liquid
{% agent_session 42 %}
{% agent_session fixing-tokio-runtime-abc123 %}
```

### 2. Message Range Slice

Embeds a specific contiguous range of messages (0-indexed):

```liquid
{% agent_session 42 0..5 %}
```

### 3. Named Slice Embed

Embeds a curated slice named in the session metadata:

```liquid
{% agent_session 42 root-cause-investigation %}
```

> **Note on Permissions**: Unpublished (draft) sessions can only be embedded in articles by their author. Once published on DEV, any author can embed public sessions.

---

## CLI Usage

Developers can also manage sessions directly from the terminal via the DevRelay CLI:

```bash
# List user sessions
devrelay sessions list

# View session by ID or slug
devrelay sessions get 42

# Submit transcript JSON file
devrelay sessions submit --title "Feature implementation" --file ./transcript.json

# Submit raw JSON string
devrelay sessions submit --title "Quick debugging" --json '{"messages": [...]}'
```
