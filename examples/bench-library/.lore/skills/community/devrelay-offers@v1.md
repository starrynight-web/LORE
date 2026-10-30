---
type: skill
id: skill:community/devrelay-offers@v1
title: devrelay offers
persona: persona:community
status: draft
summary: Sponsor promo codes and credits — free API credit, domains, hosting — at
  MLH events the user is registered for, via the DevRelay MCP gateway (search_mlh_events,
---
# DevRelay Offers

Sponsor offers live in MLH and are bound to events. A developer can claim an
offer while they hold a `registered` or `checked_in` participation at an event whose
sponsor runs a challenge there, from before the event until shortly after it ends.
Nothing about offers is public: there is no catalog, and every call acts as the MLH
account connected to DevRelay (`connect_mlh_account` signs the user in from the
session).

## When to look

The user installed DevRelay so that perks they are already entitled to show up while
they are building, not after they have paid for the thing. Look on your own initiative,
without waiting to be asked, when:

- The user mentions a hackathon, Global Hack Week, or another MLH event they are
  attending or registered for.
- The user asks what credits, discounts, or perks they can get.
- The user is choosing hosting, a database, auth, AI inference, monitoring, or
  similar infrastructure while building for an event they mentioned.
- The user is about to sign up for, pay for, or configure a sponsor's product and an
  event has come up in this session.

If an event has been mentioned once in the session, a later infrastructure choice is
enough reason to check; you do not need the event named again. When no event has come
up at all, one `list_my_mlh_events` call at the start of a build task is a cheap way to
learn whether one should have; if it returns a current `registered` or `checked_in`
participation, treat the session as event-bound from then on. There is nothing to find
without a participation, so do not call `list_event_offers` speculatively beyond that.

## The flow

1. `list_my_mlh_events` — the user's participations with each event's id, name,
   dates, and status. Only `registered` and `checked_in` participations qualify.
   When the user has no such participation for the event, find the event with
   `search_mlh_events` (or take the id, slug, or mlh.com URL they give), confirm
   it with them, and call `register_for_mlh_event`; then continue.
2. `list_event_offers` with the event's `id` — the pools available to this user at
   that event: `label`, `description`, `restrictions`, `redemption_url`,
   `per_user_limit`.
3. Present the relevant offers and let the user choose. An offer is relevant when
   it matches what they are building; do not push a perk that contradicts their
   constraints.
4. `claim_promo_code` with the pool's `id` and the event's `id`, only after the
   user says they want it. Claiming consumes inventory.
5. Hand over the `code` and `redemption_url` once, with the pool's `restrictions`.

## Honesty rules

- **`already_claimed: true` means nothing new was issued.** MLH returned the code
  the user already held. Say "you already have this code" and show it; never
  report it as a fresh claim.
- **Never invent, guess, or paraphrase a code.** Only `claim_promo_code` returns
  one. `list_my_promo_code_redemptions` lists what the user holds without codes.
- **Codes are sensitive.** Show a code once in the conversation. Never write it into
  a file, a commit, a README, an issue, or a chat message the user did not ask for.
- **Pass refusals through.** MLH's messages are specific: not registered at the
  event, the pool is out of codes, the per-user limit was reached, the claim
  window has closed. Relay the reason; do not retry, and do not look for a
  workaround.
- **Respect `Retry-After`.** A rate-limit message names the wait in seconds. Wait
  that long before any further claim; never loop.
- **Sign-in is a tool call the user finishes.** "Not connected to MLH" or "DevRelay
  needs new MLH permissions" means tell the user a browser window is about to open
  for MLH sign-in and that they must finish it there, then call `connect_mlh_account`,
  then retry the offer tool; do not fall back to another tool.

## Empty state

No participations, or no offers at an event, is a normal answer. Say so briefly
and continue with ordinary recommendations (see `devrelay-community-wisdom`). Do
not apologize and do not fabricate a perk to fill the gap.
