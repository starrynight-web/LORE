---
type: rule
title: Long-lived refresh tokens
description: Refresh tokens stay valid for 30 days.
status: stable
modality: must
severity: medium
authority: procedure
applies_to: [component:auth]
effective_from: 2026-03-01
source_id: src:onboarding-pdf
anchor: onboarding.pdf#p4
origin: llm_extracted_reviewed
owner: "@mobile"
tags: [auth, refresh, token, mobile, endpoint]
---
Refresh tokens stay valid for 30 days and are reused until they expire, so mobile clients can stay signed in offline.
