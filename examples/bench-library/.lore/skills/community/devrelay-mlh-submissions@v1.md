---
type: skill
id: skill:community/devrelay-mlh-submissions@v1
title: devrelay mlh submissions
persona: persona:community
status: draft
summary: Create or update an MLH project (with screenshots), manage its team, submit
  it to an MLH event, and enter it into the event's challenges through the DevRelay
  MC
---
# DevRelay MLH Submissions

Project submission is a chain of MLH writes, each acting as the MLH account
connected to DevRelay, and MLH enforces the order and the rules, the same ones its
website enforces. Your job is to call the steps in order, pass MLH's answers
through faithfully, and never claim a result MLH did not return.

MLH events submit one of two ways, and `get_mlh_event` tells them apart only by
what MLH answers, so follow the event's own instructions when they say:

- **Project-first** (most MLH hackathons and Hack Days): each participant submits
  one project to the event, then enters it into categories.
- **Challenge-first** (Global Hack Week and other challenge events): each
  challenge entry is its own submission. `enter_challenge` submits the project
  to the event itself, and a participant may use a different project for each
  challenge.

With the user, use the words MLH's website uses: the project, its **submission**
to the event (not "event submission"), and the **prize categories** it entered
(not "challenge entries"; at a challenge-first event, the **challenges** it
entered). The tool names keep the API's terms; the user never needs them.

## The chain

1. `list_my_mlh_events` — find the event and the user's participation. At an
   event whose registration and check-in run on MLH, MLH requires the user to be
   checked in, as its website does, and refuses steps 5 and 6 and project edits
   otherwise ("You are not registered or checked in at {event}."); any other event
   needs only the connected account. When the user is not registered, find the
   event with `search_mlh_events` (or take the id, slug, or mlh.com URL they give),
   confirm it with them, and offer `register_for_mlh_event`; when they are
   registered but not checked in, offer `check_in_to_mlh_event` once the event's
   `check_in.state` allows it. Then continue.
2. `get_mlh_event` with the event id — the challenges (prize categories), each with
   an `id`, name, prize description, and a `description` that is the sponsor's own
   statement of what they want built and judged. Read those descriptions; the names
   ("Best Use of Vultr") say nothing about the criteria, and a track claimed against
   the name alone is a track the judges will score against the text. Note which are
   `active`.
3. **Check the event takes submissions through MLH at all, before creating
   anything.** An event whose `submission_url` points at Devpost or another
   third-party platform does not: MLH will refuse step 5, and a project created in
   step 4 will exist attached to no event. When you see that, say so, give the user
   that URL, and stop here. Do not create the MLH project to "have it ready".
4. `list_my_projects` — a project can be submitted to one MLH event only. Reuse
   an existing project only when it is not yet submitted to any event, or is
   already submitted to this one; `list_my_projects` does not say which, so ask
   the user when it is unclear. Otherwise `create_project` a new one for this
   event, even for the same repository, with the repository `source_url` (a
   project-first event requires a GitHub, GitLab or Bitbucket repository; a
   project can start without one), `built_with`, `short_description`, and
   `ai_tools`, plus name, description, demo URLs, `extra_links`, and
   `screenshot_paths` when known. Always send `built_with`: many events
   reject a submission with no technologies ("Select at least one technology").
   When the stack is unknown, infer it from the repository (manifests, imports) or
   ask the user. When reusing a project with any of these empty, fill them with
   `update_project` before submitting. See "The submission fields" below.
5. **Project-first:** `submit_project_to_event` with the project id and event id,
   in the same turn as `create_project` — nothing goes between them. One project
   per participant per event and one event per project, while the event's
   submission window is open. **Challenge-first:** skip this step; step 6 submits
   the project.
6. `enter_challenge` with the project id, event id, each chosen challenge id, and
   its `sponsor_usage`. At a project-first event the event submission must exist
   first; MLH refuses otherwise. Enter at least one: a submission with no entries
   does not show in the gallery. MLH holds the project to each challenge's own
   required fields (a screenshot, a demo URL) and answers 422 naming what is
   missing. MLH may approve an entry at once, which locks the project, so finish
   `update_project` edits before this step. A challenge that runs with no event
   takes `enter_challenge` without an `event_id`.

`update_project` changes only the fields passed. Use it to fix a project after a
422 or when the user adds a demo link or a screenshot. Never clear `built_with` on a submitted
project: the technology requirement applies to edits too.

MLH locks the project and all of its entries once an entry at its event is
approved or wins, or that event's submission window closes. Every edit, answer
change, withdrawal, and reactivation is then refused.

`update_challenge_entry`, `withdraw_challenge_entry`, and
`reactivate_challenge_entry` act on an entry id from `enter_challenge` until then.
`update_challenge_entry` changes the entry's `sponsor_usage`, and a blank answer
clears it. Only a `draft` or `submitted` entry can be withdrawn, and withdrawing
needs a reason; DevRelay sends a default when the user gives none. Reactivating
re-enters an entry the team withdrew, and only that: an entry the organizers
rejected cannot be brought back ("Only withdrawn entries can be reactivated; this
one is rejected."). Tell the user to contact the event's organizers about it.

## The team

A teammate joins through an invite: `create_project_invite` returns the project's
live invite, its `invite_url` for a teammate on the website and its `token` for
`join_project` when the teammate uses DevRelay. MLH refuses a join once the team is
locked, when the project's event requires a check-in the joiner lacks, or when the
joiner is already on another project at that event. `list_my_projects` shows the
team as `members` ({id, user_id, name}); `remove_project_member` takes a member's
`id` to remove a teammate, or the user's own to leave. Anyone may leave, the member
who submitted the project may remove others, and the submitter and the last member
cannot be removed. Confirm with the user before removing anyone.

## The submission fields

- **`short_description`** — the one-line pitch. Always send it: some events refuse
  a submission without one ("One-line pitch is required"). Take it from the
  README's opening line or summary, at most 140 characters. Write one from the
  README when it has none, and show it to the user.
- **`built_with`** — the stack, including the AI APIs the project calls at
  runtime, found in its imports and config. Tag those `gemini`, `openai`,
  `claude`, `elevenlabs`, `gemma`, `huggingface`, `ollama`, `openrouter`,
  `llama`, `deepseek`, `grok`, or `mistral`. Each tag is at most 40 characters.
- **`ai_tools`** — the AI used to build the project, filled from what you know
  about yourself. When you helped build it, your own harness goes in as its
  coding tool id (`claude-code`, `codex`, `cursor`, ...) and the model you run on
  as `coding:` plus its OpenRouter id (`coding:anthropic/claude-opus-5.5`). Use
  `coding:claude-older` (likewise `gpt`, `gemini`, `grok`, `mistral`, `qwen`) for
  a model MLH no longer lists, and `coding:unknown` only when you cannot tell the
  model. Add any other tools the user says they used. `hand-coded` means no AI at
  all; MLH drops it beside any other id. There are no `api:` ids: runtime AI goes
  in `built_with`. An unknown id gets a 422 listing the valid tool ids and model
  ids; the model ids there lack the `coding:` prefix, so add it, then retry.
- **`extra_links`** — up to 5 other links (slides, docs, a write-up), each a `url`
  with an optional `label` of at most 60 characters. Each write replaces the whole
  list.
- **`screenshot_paths`** — local PNG or JPEG files of at most 2 MB, up to 5 per
  `create_project` or `update_project` call, added to the project's screenshots.
  Some events and challenges require one ("Upload at least one screenshot"). Take
  real screenshots of the running project, never generated images. Remove one with
  `removed_screenshot_ids`, using the ids in the project's `screenshots`.
- **`sponsor_usage`** — sent with `enter_challenge`, one per entry: the team's
  answer to that prize category's question, a sentence or two on how the project
  uses the sponsor or why it fits, written against the challenge's `description`
  from step 2, at most 1000 characters. Draft it with the user when choosing the
  challenges. Re-entering does not change it; `update_challenge_entry` does.

## Reading MLH's answers

- **`already_existed: true`** on a submission or entry means it was already there
  and nothing changed. Say so; do not report a new submission.
- **A 422 is a requirements failure**, and the message names what failed ("Select
  at least one technology", "One-line pitch is required", "Keep the pitch under 140
  characters", "Link to a YouTube, Vimeo or Loom video", an unknown `ai_tools` id, a
  required demo URL, a program rule). Several failures arrive as one message joined
  with ". ", so look for each phrase rather than matching the whole text. Fix the
  project with `update_project`, then retry the same call.
- **"You are not registered or checked in at {event}."** means offer
  `register_for_mlh_event`, or `check_in_to_mlh_event` when the user is registered
  and the event's `check_in.state` allows it, confirm it with the user, then run the
  step again.
- **"This project is already submitted to {other event}. Create a new project for
  {event}."** arrives as a 422, but `update_project` cannot fix it: the project stays
  with that other event. Match on this message, not the status. Confirm with the
  user, then `create_project` a new one for this event, even for the same repository,
  and submit that.
- **Any other refusal ("MLH denied", "MLH refused") is final for this turn.** The
  window is closed, the project is locked, the project is not theirs, the user
  already submitted another project to this project-first event, or the entry cannot
  be withdrawn or reactivated in its current status. Relay the reason. Do not retry and do not
  try a different id to get around it.
- **Such a refusal on `submit_project_to_event` leaves a new project attached to
  nothing.** The project is real and it is the user's; it is just not part of any
  event. Say that plainly rather than reporting only the refusal, and do not create a
  second project. Offer the two ways out: submit this same project to a different
  event, or leave it and follow the event's own submission link.
- **A rate-limit message names the wait.** Respect it; never loop on writes.
- **"Not connected to MLH" or "DevRelay needs new MLH permissions"** means tell the
  user a browser window is about to open for MLH sign-in and that they must finish
  it there, then call `connect_mlh_account`, then retry the step.

## Before you write

Submissions and entries are visible to organizers and judges. Confirm the event
with the user before calling `register_for_mlh_event`, the project and event before
`submit_project_to_event`, and the project, event, and challenges before
`enter_challenge`. After each write, tell the user what MLH did in plain
language: the project and event by name, the prize categories entered, anything
MLH refused and why, and what comes next. Leave out ids, timestamps, and raw
status values unless the user asks for them. Never send fields MLH owns (`submitter`,
`submitted_at`, `status`); the tools do not expose them.

The rules judges apply (all work during the event, public repo kept public,
secrets out of the repo, AI use disclosed, stop at the deadline) are in the
`mlh-policies` and `mlh-hackers` knowledge guides (see [[devrelay-knowledge]]).
Check the project against them before submitting, and tell the user about any
gap rather than submitting over it.

## Before the user asks

The user installed DevRelay so the submission happens while the window is open. When
`list_my_mlh_events` shows a `registered` or `checked_in` participation whose event is
current and the work in this session is plausibly the project, raise it once: name the
event, the submission deadline, and offer to run the chain. Do not wait for "submit my
project".

## After submitting

Offer, once, to draft the write-up as a DEV post with `create_article` (see
[[devrelay-publishing]]): a draft, `published: false`, with the default `some_ai`
disclosure. Hand over the `edit_url` the tool returns, not `url` — a draft's `url`
carries a `-temp-slug-<id>` suffix that reads as broken. The user publishes from DEV. Do not claim a post was
published unless `create_article` or `update_article` returned it with `published:
true`.
