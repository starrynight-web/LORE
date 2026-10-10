---
type: rule
title: No token logging
description: Never log token values.
status: stable
modality: must_not
severity: high
authority: policy
applies_to: [component:auth, component:api]
effective_from: 2026-01-15
source_id: src:policies-auth-md
anchor: policies/auth.md#L57
origin: human_authored
owner: "@security"
tags: [auth, token, logging, secrets]
---
Never log access or refresh token values, in full or in part.
