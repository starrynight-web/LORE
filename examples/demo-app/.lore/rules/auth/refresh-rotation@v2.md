---
type: rule
title: Rotate refresh tokens
description: Rotate the refresh token on every use.
status: stable
modality: must
severity: high
authority: team_convention
applies_to: [component:auth]
effective_from: 2026-08-01
source_id: src:team-conventions-md
anchor: policies/auth.md#L88
origin: human_authored
owner: "@security"
tags: [auth, refresh, token, rotation, endpoint]
---
Rotate the refresh token on every use; the previous refresh token becomes invalid immediately.
