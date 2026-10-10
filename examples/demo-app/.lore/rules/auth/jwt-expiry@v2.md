---
type: rule
title: Access token expiry
description: Access tokens must expire within 60 minutes.
status: stable
modality: must
severity: high
authority: policy
applies_to: [component:auth]
effective_from: 2025-01-01
source_id: src:policies-auth-md
anchor: policies/auth.md#L40
origin: human_authored
owner: "@security"
tags: [auth, jwt, token, expiry]
---
Access tokens issued by any service MUST expire in 60 minutes or less.
