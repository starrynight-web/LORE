---
name: http-retries
description: Retry idempotent HTTP calls with capped exponential backoff and jitter. Never retry non-idempotent requests blindly.
---
# HTTP retries

## When to retry
Retry only on connection errors, 429 and 5xx responses, and only for idempotent methods.

## Backoff
Use exponential backoff starting at 100ms, capped at 5s, with full jitter.

## References
See [reference.md](reference.md) for status code details.
