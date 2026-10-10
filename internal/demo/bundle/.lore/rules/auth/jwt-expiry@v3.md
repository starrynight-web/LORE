---
type: rule
title: Access token expiry
description: Access tokens must expire within 15 minutes.
status: stable
modality: must
severity: high
authority: policy
applies_to: [component:auth]
supersedes: rule:auth/jwt-expiry@v2
effective_from: 2026-07-01
stale_after: 2027-07-01
source_id: src:policies-auth-md
anchor: policies/auth.md#L42
origin: human_authored
owner: "@security"
tags: [auth, jwt, token, expiry]
---
Access tokens expire in 15 minutes or less.
