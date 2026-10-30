---
type: skill
id: skill:community/devrelay-knowledge@v1
title: devrelay knowledge
persona: persona:community
status: draft
summary: Fetch authoritative reference guides from the DevRelay knowledge base at
  https://devrelay.com/knowledge — MLH (participant guide, organizer guide, Code of
  Condu
---
# DevRelay Knowledge Base

`https://devrelay.com/knowledge` serves curated, sourced reference guides as
**plain Markdown over plain HTTP**. There's no auth, no JavaScript, and no HTML
shell. What you fetch is what goes into context.

The user installed DevRelay so that answers about MLH, Global Hack Week, DEV,
DEV Challenges, and Hacktoberfest come from the source rather than from
recollection. Fetch on your own initiative whenever one of those comes up, even
in passing: "GHW" in a build task, "hacktoberfest" in a repo, "MLH" in a README,
a question about how to post on DEV, or a hackathon the user is organizing is
enough to fetch the matching guide before you say anything about it.

Models get these programs wrong from memory. Hacktoberfest 2026 no longer counts
pull requests, GHW changes theme monthly, Local Hack Day was renamed, the `.io`
domains redirect to `.com`, and MLH now owns DEV.

## Pick the guide

| The question is about… | Topic |
| --- | --- |
| MLH in general, its programs, links, contacts, and the MLH–DEV relationship | `mlh` |
| **Taking part as a hacker:** MLH account, finding events, eligibility, registering, what happens at a hackathon, submitting, judging, prizes, Hack Days, the MLH Fellowship | `mlh-hackers` |
| **Organizing:** becoming an MLH Member Event, requirements and benefits, venue, budget, sponsorship, marketing, registration fields, judging plans, the Hack Days program | `mlh-organizers` |
| **Rules and safety:** the MLH Code of Conduct and reporting lines, Standard Hackathon Rules (including AI use), cheating and incident procedures, Contest Terms | `mlh-policies` |
| **Global Hack Week:** how it works, challenges and points, swag and shipping, Discord, Guilds, the FAQ | `global-hack-week` |
| DEV (dev.to) in general, its content model, the API, and DevRelay's DEV tools | `dev` |
| **Posting on DEV:** Code of Conduct, Content Policy, AI guidelines, `ai_disclosure_level`, plagiarism, the editor and Liquid tags, tags, moderation | `dev-guidelines` |
| **Entering DEV Challenges:** eligibility, submission templates and tags, recurring rules, judging, badges and prizes, the monthly MLH × DEV writing challenge | `dev-challenges` |
| **Hacktoberfest 2026:** stickers and rewards, key dates, DEV Challenge rounds, GHW: Hacktoberfest, Fests, hosting | `hacktoberfest` |

Fetch the topic document directly, not the index, which only lists topics. When
a question spans two guides (for example, "how do I submit my GHW project to a
DEV Challenge?"), fetch both.

## Through the gateway first

When the `devrelay-gateway` MCP server is connected, read documents with its
`get_knowledge_document` tool instead of fetching over HTTP. For example, pass
`topic: "global-hack-week"`, or omit `topic` for the index. It returns the same
Markdown, needs no login, and works even when your shell can't make HTTPS
requests. An unknown topic comes back as an error listing the real ones.
Without the tool, fetch over HTTP as below.

## Endpoints

Every topic is at `https://devrelay.com/knowledge/<topic>`, for example:

```bash
curl -s https://devrelay.com/knowledge/mlh-hackers
```

- `https://devrelay.com/knowledge` is the index.
- `https://devrelay.com/v1/knowledge.json` is the machine-readable index (slug,
  title, summary, url, bytes, sha256).

Use a tool that returns the raw response body: `WebFetch`, `curl`, or a browser
tool. All are `GET`, and all return `text/markdown`.

A web *search* tool is not a fetch, even one that can open a URL. It hands back
search results or a summary rather than the document. If search is your only
web tool and you can run shell commands, fetch with `curl` instead (`curl.exe`
in Windows PowerShell).

An unknown slug returns a 404 whose **body is Markdown listing the real topics**.
Read it rather than guessing again. If the host is unreachable, say so. Don't
silently substitute recollection or web search results for the document.

For self-hosting or staging, swap the origin for `$DEVRELAY_BASE_URL`, the same
variable the gateway uses for updates and skills.

## How to use what you get

1. **Fetch before answering**, not after drafting from memory.
2. **Prefer one full guide over several partial searches.** The guides are
   written to be read whole. Don't fetch every topic when the question is about
   one.
3. **Static knowledge vs. live data.** The guides explain how programs work.
   They deliberately leave out specific upcoming events, open challenges, session
   schedules, and sponsor offers. For those, use the live tools each guide names
   in its "Live data lives elsewhere" section: `search_mlh_events`,
   `get_mlh_event`, `list_my_mlh_events`, `list_event_offers` (see
   [[devrelay-offers]]), `get_challenges` and `get_challenge_details` (see
   [[devrelay-challenges]]), or the upstream page the guide links, such as
   `https://ghw.mlh.com/schedule`. Never present a date from memory as current.
4. **Honor the freshness markers.** Every guide opens with a `Last verified` date
   and ends with its sources. Guides flag volatile sections inline and say where
   two upstream sources disagree. When they do, tell the user.
5. **Respect the "does not know" section.** Each guide ends with an explicit list
   of gaps. If the answer is in that list, say it isn't published. Don't fill
   the gap with a plausible guess.
6. **Cite the guide**, and pass through the upstream link it names, so the user
   can verify. For example: `Per the DevRelay knowledge base (verified
   2026-09-30, sourced from github.com/MLH/mlh-policies): …`

## Relationship to the other DevRelay skills

- This skill is for **static reference knowledge**: programs, rules,
  definitions, and how-tos.
- [[devrelay-navigator]] is for **live platform data** on dev.to and MLH via the
  MCP gateway.
- [[devrelay-community-wisdom]] is for **synthesizing opinion** from dev.to
  threads.

They compose. Read `global-hack-week` to learn how GHW challenges work, then
`search_mlh_events` to find this month's week. Read `dev-challenges` for the
recurring rules, then `get_challenge_details` for the open challenge's rubric,
then [[devrelay-publishing]] to draft the entry within `dev-guidelines`. Read
`mlh-hackers` for how submission works, then [[devrelay-mlh-submissions]] to do
it.

## Note on MLH tooling

The legacy MyMLH fixture tools (`list_upcoming_hackathons`,
`get_hackathon_details`, `verify_member_status`, and the old MyMLH user and OAuth
tools) are **disabled in the current build**. If you remember them existing,
they're gone on purpose, so don't report their absence as a bug. General MLH and
GHW questions come from this knowledge base. The user's own events, offers,
projects, and submissions come from the MLH participant tools (see
[[devrelay-navigator]]).
