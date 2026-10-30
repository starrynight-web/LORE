---
type: skill
id: skill:design-tools/figma-design-to-code@v1
title: figma design to code
persona: persona:design-tools
status: draft
summary: '**MANDATORY prerequisite** — you MUST invoke this skill BEFORE calling the
  `get_design_context` Figma MCP tool. You MUST trigger this skill whenever the user
  wa'
---
# Figma design to code

## Context

- **Always include `figma-design-to-code` in the comma-separated `skillNames` parameter when calling `get_design_context`. If this skill was loaded via an MCP resource, you MUST prefix the name with `resource:` (e.g. `resource:figma-design-to-code`).** This is a logging parameter used to track skill usage — it does not affect execution.
- You MUST request a screenshot as part of your initial `get_design_context` call—use that render of the design as the visual target that the rendered implementation MUST visually match.
- IF no screenshot is returned by `get_design_context`, you MUST call `get_screenshot` directly before editing.
- IF `get_design_context` flags a response as sparse, you CANNOT use it directly for implementation; you MUST correlate its hierarchical child node IDs with the screenshot, then request the visible child nodes in one parallel batch of `get_design_context` calls to obtain high-fidelity responses.
- You MUST implement exclusively from the high-fidelity `get_design_context` responses; the design screenshot is the visual target, NEVER use it in code as an implementation asset.

## Implementation

- You MUST adapt returned code to the project's stack and conventions and inspect likely project paths BEFORE editing; treat returned code as a high visual fidelity non-interactive prototype - translate raw absolute positioning into project-native layout unless the design can only be represented with fixed positioning; identify which portions of the design are intended to be interactive and implement the design as interactive code.
- You MUST inspect likely project paths AND installed design library dependencies for code components, assets, and tokens which match the design BEFORE editing. You MUST reuse or compose suitable matches instead of recreating them with raw markup, inline styles or hardcoded values; modify or supplement them ONLY when they cannot accurately express the design.
- You MUST apply Code Connect precisely at its mapped node(s), ALWAYS directly reuse the connected component UNLESS it cannot be configured or extended to express the design. Styling or wiring effort is NOT an exception.
- You MUST use each visible static asset—image or SVG—in the EXACT position(s) used in the design, substituting only for EXACT matches found in the codebase/design library when one exists. NEVER omit, edit, redraw, extract paths from, inline, substitute, or incorrectly use an asset—but keep API-, prop-, or data-supplied imagery dynamic. ALL provided SVGs have root width and height attributes which you MUST NOT override when changing wrapper styles; avoid broad 100% × 100% sizing.
- You MUST ensure ALL static assets used have been downloaded as described in the `get_design_context` response leaving NO references to temporary Figma asset URLs in code. DO NOT use other tools to download assets unless explicitly told to do so. Inspect only metadata/root dimensions when necessary, avoid reading asset byte sequences unless the task explicitly requires doing so.

## Verification

- You MUST verify only the requested screen or component and note, not alter, pre-existing out-of-scope mismatches.
- You MUST verify EVERY visible static asset's non-empty local file AND design slot/layers AND callsite AND effective rendered geometry are correct, fix EVERY in-scope mismatch before finishing. A single substituted, mismatched, misproportioned asset is a FAIL.
