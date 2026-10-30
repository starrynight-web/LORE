---
type: skill
id: skill:community/devrelay-publishing@v1
title: devrelay publishing
persona: persona:community
status: draft
summary: Draft, stage, and update DEV (dev.to) posts about the user's work through
  the DevRelay MCP gateway (create_article, update_article, get_my_articles, unpublish_a
---
# DevRelay Publishing

The user installed DevRelay so that the things they figure out while working with you
turn into posts on DEV without a separate "now write it up" chore. This skill is how
that happens. It is proactive by design: you offer, the user decides, DEV holds the
draft.

## When to offer, unprompted

Offer at the moment the milestone lands, in the same message that reports it. Not in
a list of things you could do next, not the next time the user asks "what now" — by
then they have had to think of it themselves, which is the chore this skill exists to
remove. Waiting for a prompt is the failure mode here, and a menu option is waiting.

Offer a post **once** when the work reaches a natural stopping point that someone else
would learn from:

- A bug that took real investigation is understood and fixed.
- A design or architecture decision is settled, especially one where community
  wisdom (see [[devrelay-community-wisdom]]) informed the choice.
- A feature or migration ships and the approach is non-obvious.
- A comparison or evaluation of libraries, services, or patterns concludes.
- The user says something like "that was painful", "I wish I'd known", "finally", or
  "that's a good trick" about what just happened.

Do **not** offer for a typo fix, a routine dependency bump, a change with no lesson in
it, or a piece of work the user already declined to write about in this session. One
offer per piece of work; a "no" ends it.

The offer is a sentence, not a pitch:

> This would make a solid DEV post: "Why our Tokio shutdown panicked, and the one-line
> fix". Want me to draft it to your DEV drafts? You'd review and publish from there.

If the same milestone also merits a saved session (see [[devrelay-sessions]]), make
both offers in the same message. Place these offers (along with `🌐 Community Wisdom`
and any challenge/event heads-up) as an interlude towards the bottom of the response,
right *before* your final closing summary or next-steps wrap-up rather than at the very end.

## Also check, at the same moment

A good solve is also the moment to check whether the work fits something live:

- `get_challenges` — is there an active or upcoming DEV Challenge this post could be an
  entry for? If yes, say so with the deadline; the draft then follows the challenge's
  `full_details` template (see [[devrelay-challenges]]).
- `list_my_mlh_events` — is the user registered at an MLH event this project belongs
  to? A write-up may double as their submission narrative (see
  [[devrelay-mlh-submissions]]).

Mention a match in one line in that same pre-summary interlude. Say nothing when there is no match.

## Drafting

1. **Ground it.** Run `search_dev_to_semantic` on the topic before writing. Link the two
   or three posts that shaped the approach, in the citation format from
   [[devrelay-navigator]]. Do not write a post that ignores the thread the community is
   already having.
2. **Write for a reader who was not in the session.** Problem, what was tried, what
   worked and why, the code that matters, what you would do differently. Short. Real
   code from the repo, with secrets, tokens, internal hostnames, and private paths
   scrubbed.
3. **Embed the session** where a transcript adds evidence:
   `{% agent_session <id_or_slug> %}` (see [[devrelay-sessions]]).
4. **Pick up to four tags** from `list_tags` or the challenge's required tags; never
   invent one.
5. **Stage it as a draft:**

```json
{
  "name": "create_article",
  "arguments": {
    "title": "Why our Tokio shutdown panicked, and the one-line fix",
    "body_markdown": "...",
    "published": false,
    "tags": ["rust", "async", "debugging"]
  }
}
```

   Leave `published` unset or `false`. Leave `ai_disclosure_level` unset.
6. **Hand over `edit_url`, not `url`.** DEV addresses an unpublished post by a
   `-temp-slug-<id>` URL, which is what `url` holds for a draft: it works, but it
   reads as broken and the user will assume the post did not save. `create_article`,
   `update_article`, and `get_my_articles` all return `edit_url` alongside it —
   that is the link to give, every time, in the same message as the draft. Tell
   them they publish from DEV, or ask you to.

DEV's Content Policy, AI Guidelines, plagiarism rules, and its rules for agents
(`dev.to/llms.txt`) are summarized in the `dev-guidelines` knowledge guide (see
[[devrelay-knowledge]]). Read it when a draft raises a question the steps above
do not answer, such as affiliate links, cross-posting with a canonical URL, or
citing someone else's code.

## AI disclosure

DEV asks authors to disclose AI involvement. DevRelay answers for you: every
`create_article` sends `ai_disclosure_level: "some_ai"` unless you pass a different
level. That is the honest floor for a post an agent drafted, so:

- **Do not override to `no_ai`.** Only the user can decide that, and only for a post
  they wrote entirely themselves.
- **Use `fully_autonomous`** when the agent wrote and published the post with no human
  edits, for example an automated pipeline the user set up.
- **`not_disclosed`** exists but is not something to choose on the user's behalf.
- **`update_article` leaves the level unchanged** unless you pass one. Pass `some_ai`
  when you contribute to a revision of a post that has no disclosure yet.
- Do not ask the user whether to disclose. Do tell them the post is marked `some_ai`
  when you hand over the draft URL, so they know.

## Publishing and updating

- `published: true` only after an explicit yes in this session for this post. A draft
  on DEV is reversible; a published post is public immediately.
- `update_article` sends the full `title` and `body_markdown`; fetch the current body
  with `get_article_content` first so you are editing the real text, not your memory
  of it. Fields you leave unset stay as they are.
- `get_my_articles` with `state: "unpublished"` lists existing drafts; reuse one for
  the same piece of work rather than creating a second.
- `unpublish_article` takes a post down. Confirm before calling it.

## Reading the tools' answers

- **A 422** names what DEV rejected (a tag, a missing body, a title length). Fix it and
  retry the same call.
- **"MLH denied"** or a linked-account error means the MLH account has no DEV account
  linked, or the login lacks the write scope. Tell the user a browser window is about
  to open for MLH sign-in, call `connect_mlh_account`, then retry.
- **"DEV did not confirm the write"** means the post may already exist. Check
  `get_my_articles` before creating again; never double-post.
- **Rate limits** name the wait. Respect it; never loop on writes.
