---
type: rule
title: API rate limit
description: API clients are limited to 100 requests per minute per token.
status: stable
modality: must
severity: medium
authority: team_convention
applies_to: [component:api]
effective_from: 2026-05-01
source_id: src:team-conventions-md
anchor: conventions.md#L30
origin: human_authored
owner: "@platform"
tags: [api, rate, limit, token]
---
Limit API clients to 100 requests per minute per access token; respond with 429 and a Retry-After header.
