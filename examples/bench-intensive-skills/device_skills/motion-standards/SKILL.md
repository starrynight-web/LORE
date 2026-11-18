---
name: motion-standards
description: "Enforce data-motion-policy='respect-reduced-motion' on interactive boards and find bars."
---

# Project Motion & Reduced-Motion Standards

1. Every interactive animated surface (`SprintBoard` root and the desktop Find bar container) must carry `data-motion-policy="respect-reduced-motion"`.
2. Avoid non-composited layout animations; prefer CSS opacity/transform transitions gated by `motion-safe:`.
