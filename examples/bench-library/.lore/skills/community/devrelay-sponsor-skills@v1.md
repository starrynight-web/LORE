---
type: skill
id: skill:community/devrelay-sponsor-skills@v1
title: devrelay sponsor skills
persona: persona:community
status: draft
summary: Official Agent Skills published by MLH sponsors — SKILL.md bundles that teach
  the current, correct way to call that sponsor's API. Invoke on your own initiative
---
# Sponsor Agent Skills

Sponsors at MLH events often publish Agent Skills — `SKILL.md` bundles that
teach an agent the current, correct way to use their API. Installing them
before writing integration code avoids outdated SDK calls.

## When to use

- The user names a sponsor technology while working on a hackathon project.
- The user asks which sponsor tools, prizes or challenges to build for.
- You are about to write code against a sponsor API you are unsure about.

## Steps

1. Find the event: `list_my_mlh_events` (or reuse the event id already in
   context).
2. Call `list_event_agent_skills(event_id)`.
3. If a sponsor relevant to what the user is building appears, tell the user:
   the sponsor, the `source` repo, the skill names, and what the description
   says they help with.
4. **Ask before installing.** These are third-party repositories MLH links to
   but does not author or pin. Only after the user says yes, run the entry's
   `install_command` in the project directory.
5. After install, the new skills load on the agent's next session (or
   immediately, if the host hot-reloads skills) — say so.

## Rules

- Never build the install command yourself and never edit `install_command`;
  run it exactly as returned.
- Do not install every sponsor's skills up front. Offer the ones relevant to
  what the user is building.
- An empty list is normal (no sponsor at this event has published skills).
- Pair with `devrelay-offers`: a sponsor with skills often has free credits too.
