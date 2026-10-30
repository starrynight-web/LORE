---
type: skill
id: skill:community/devrelay-challenges@v1
title: devrelay challenges
persona: persona:community
status: draft
summary: Active DEV Challenges, MLH hackathons, and community events via the DEV Events
  API — deadlines, judging rubrics, sponsor tracks, prize categories, and FAQs from
---
# DEV Challenges & Events

The `devrelay-gateway` MCP server provides dedicated tools to query live DEV Challenges and community events directly from the DEV Events API (`/api/events`).

## Why This Exists

DEV regularly hosts technical challenges, hackathons, and open-source events (such as Hacktoberfest sprints and partner hackathons). To participate effectively, agents need access to the exact rules, judging rubrics, and sponsor requirements.

## Surface challenges without being asked

The user installed DevRelay partly so they stop finding out about a challenge the week
after it closed. You are the one who notices. Check `get_challenges` (and `get_events`
for livestreams and takeovers) on your own initiative when:

- The user describes what they are building, especially with a named framework,
  cloud provider, database, AI model, or sponsor's product.
- The user mentions a deadline, a demo, a submission, a prize, a hackathon, Global Hack
  Week, or a sponsor.
- The user is learning a technology or says they want to write more.
- A non-trivial piece of work reaches a good solve (see [[devrelay-publishing]]);
  the write-up may be an entry.
- The user asks what they should build or work on next.

Classify by date first (below). When an active or upcoming challenge fits, mention it
in one or two lines as an interlude towards the bottom of your response *before* your
final closing summary (never as the very last part of the message): title, what it
asks for, deadline with days remaining, link. Then offer to audit the project against
`full_details` and draft the entry. When nothing fits, say nothing about challenges;
do not pad a reply with irrelevant events.

For the user's own MLH hackathons, the same instinct applies through
`list_my_mlh_events`; see [[devrelay-offers]] and [[devrelay-mlh-submissions]].

DEV Events API features:

- **Event Type Filtering (`type_of`)**: Enables filtering events by type (`challenge`, `live_stream`, `takeover`, `other`).
- **The `full_details` Agent Context Attribute**: Added specifically to provide API consumers and AI agents with the complete, unabridged text dump of all event context (prompts, rules, judging rubrics, sponsor tracks, submission requirements, FAQs, prize tiers, and templates) that may not be displayed on the public event summary card.

## Choosing a Tool

| You need | Call |
| --- | --- |
| Active, upcoming, or past DEV Challenges | `get_challenges` |
| Full rules, rubric, and context for a challenge | `get_challenge_details` |
| Community events filtered by type (`live_stream`, `takeover`, `other`) | `get_events` |
| Full details for any specific event by ID | `get_event_by_id` |
| Stage/publish a challenge entry post | `create_article` (with `published: false`) |

---

## Working with `full_details`

When calling `get_challenge_details` or `get_event_by_id`, always inspect the `full_details` field. While `description` and `details` provide short marketing summaries, `full_details` is the authoritative source for:

1. **Submission Prompts & Themes**: What specific application, tool, or article the challenge is asking builders to create.
2. **Judging Rubrics & Scoring Criteria**: Explicit criteria judges use to score submissions (e.g. UX, code quality, technical execution, documentation).
3. **Required Tags**: Mandatory submission tags (e.g. `#devchallenge`, `#hacktoberfest`, sponsor tags).
4. **Sponsor Tracks & Prizes**: Specific category requirements (e.g. vector database integration, deployment targets) to qualify for sponsor prize tiers.
5. **Technical Constraints**: Requirements such as permissive open-source licensing (MIT/Apache 2.0), live demo URLs, or embedded architecture diagrams.
6. **Submission Deadlines**: Exact cut-off timestamps and timezone requirements.

---

## Temporal Awareness & Date Classification

The DEV Events API returns events from across history — past, ongoing, and upcoming. **You MUST evaluate `starts_at` and `ends_at` timestamps against the current date to contextually classify each event:**

| Status | Condition | Agent Action |
| --- | --- | --- |
| **🟢 Active / Ongoing** | `starts_at <= now <= ends_at` | Primary targets for current entry. Highlight submission deadline (`ends_at`) and days remaining. |
| **🔵 Upcoming** | `now < starts_at` | Announced events. Note start date; prepare ideas and dependencies ahead of kickoff. |
| **⚪ Past / Concluded** | `ends_at < now` | Submissions closed. **Never present as active.** Use exclusively for historical research, retrospective analysis, or winning architecture patterns. |

### Rules for Date Handling

1. **Never recommend entering a past challenge.** If a user asks "What challenges can I participate in?", filter out concluded events (`ends_at < now`) or explicitly group results by Active, Upcoming, and Concluded.
2. **State time remaining.** For active challenges, compute and report the remaining window (e.g. *"Active — 6 days left, closes Oct 15 at 23:59 UTC"*).
3. **Historical research context.** When using past challenges to extract rubric patterns or winning architectural designs, explicitly clarify that the challenge concluded in the past.

---

## End-to-End Challenge Workflow

Follow this 5-step workflow when helping a user participate in a DEV Challenge:

### Step 1: Discover Active Challenges

Call `get_challenges` to list active hackathons and challenges:

```json
{
  "name": "get_challenges",
  "arguments": { "page": 1, "per_page": 10 }
}
```

### Step 2: Fetch Rules and Rubrics

Call `get_challenge_details` with the chosen challenge ID to retrieve `full_details`:

```json
{
  "name": "get_challenge_details",
  "arguments": { "id": 101 }
}
```

Parse the `full_details` markdown for track guidelines, rubrics, and submission requirements.

### Step 3: Audit Project & Workspace

Audit the user's workspace against the criteria found in `full_details`:

- Check for a valid open-source license file (`LICENSE` / `LICENSE.md`).
- Ensure deployment configurations or templates (Docker, Railway, Vercel) are intact.
- Generate an architectural system diagram (Mermaid format is natively rendered on DEV).
- Validate required environment variables and setup documentation in `README.md`.

### Step 4: Draft the Submission Article

Draft a structured submission post following the template in `full_details`:

- Include an executive summary of what was built.
- Embed the architecture diagram and tech stack choices.
- Highlight how the project addresses specific sponsor tracks.
- Include links to the public GitHub repository and live demo.
- Stage to the user's drafts with `create_article`. Leave `ai_disclosure_level`
  unset: DevRelay sends `some_ai`, which is the honest level for an agent-drafted
  entry and what challenge rules expect (see [[devrelay-publishing]]):

```json
{
  "name": "create_article",
  "arguments": {
    "title": "My Project Submission: Building an AI Agent for DEV",
    "body_markdown": "...",
    "published": false,
    "tags": ["devchallenge", "hacktoberfest", "ai", "webdev"]
  }
}
```

### Step 5: Pre-Submission Review

Present a final checklist to the user verifying that all items from `full_details` have been met before they publish. Publishing is the user's call: set `published: true` only after an explicit yes in this session.

---

## General Rules Live in the Knowledge Base

`full_details` covers one challenge. The rules that recur across DEV Challenges
are in the `dev-challenges` knowledge guide (see [[devrelay-knowledge]]): the
Official Rules' eligibility (18+, excluded countries, DEV Members), teams of up
to four, the one-submission and new-work defaults, plagiarism consequences,
non-English entries, tie-breaks, and how prizes are paid. Where it and
`full_details` disagree, the challenge page wins for that challenge.

## Sourcing & Provenance

When reporting on challenges or events:

- Always cite the challenge title, event ID, dates, and canonical link (`location_url` or `https://dev.to/events/<id>`).
- If `full_details` is null or empty for an event, note that the organizer has not supplied an extended agent context dump and rely on `description`/`details`.
