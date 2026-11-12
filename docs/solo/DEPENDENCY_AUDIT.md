# Dependency audit - 2026-11-12

Point-in-time snapshot, not a security guarantee. Baseline evidence lives under
`/tmp/lore-remediation-baseline/` (npm-audit.json, pip-audit-*.json); re-run the
commands at the bottom (from the repo root) to reproduce.

## Baseline (web/)

npm audit flagged **8 package-level entries** (distinct packages in the
dependency tree; each may carry multiple advisories): **1 high, 5 moderate,
2 low**.

- **postcss <=8.5.22 (high, nested under `next/`)** - parsing issues in the CSS
  build/source-map path
  ([GHSA-6g55-p6wh-862q](https://github.com/advisories/GHSA-6g55-p6wh-862q),
  [GHSA-r28c-9q8g-f849](https://github.com/advisories/GHSA-r28c-9q8g-f849),
  plus moderate
  [GHSA-qx2v-qp2m-jg93](https://github.com/advisories/GHSA-qx2v-qp2m-jg93),
  [GHSA-fxqj-rqcc-2cmp](https://github.com/advisories/GHSA-fxqj-rqcc-2cmp)).
  This affects the build-time CSS pipeline; it is not proven remotely
  exploitable at runtime. `next@15.x` pins `postcss 8.4.31` for its internal
  copy even through 15.5.29, so no in-line upgrade existed.
- **shadcn CLI chain (moderate/low)** - `shadcn` pulled `@shadcn/registry` ->
  `deepmerge` (prototype pollution,
  [GHSA-gcqx-w48m-w2h4](https://github.com/advisories/GHSA-gcqx-w48m-w2h4);
  no fixed release exists) and `ts-morph` -> `@ts-morph/common` -> `minimatch`
  (glob amplification DoS,
  [GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249);
  the fix needs >=11.0.1 but `@ts-morph/common` allows only `^10`). Although
  `shadcn` sat in `dependencies`, it is a CLI component generator - none of
  this graph ships in the built site.

## Remediation

- **Scoped override, not an upgrade:** `overrides: {"next": {"postcss": "$postcss"}}`
  maps next's internal `postcss` spec onto the already-installed top-level
  dependency declared as `^8.5.31` (resolved 8.5.32 in the lockfile). `next`
  stays at **15.5.28** (no major migration); the nested 8.4.31 copy is gone
  from `node_modules` and `package-lock.json`.
  **Removal condition:** when Next 15 upstream declares a patched postcss
  version, this override should be revisited/dropped.
- **`shadcn` package removed.** The only import was
  `@import "shadcn/tailwind.css"` in `app/globals.css`. A small compatibility
  subset is vendored into `app/ui-utilities.css`: the `data-*` state variants
  and `no-scrollbar` utility the components use, plus related keyframes,
  copied verbatim from `dist/tailwind.css` with the upstream MIT license
  retained in a `/*! ... */` comment so it survives minification. The
  remainder of the upstream file (scroll-fade, shimmer, and other unused
  helpers) was not copied. `components.json` stays as generator metadata -
  if a component is regenerated later, use an explicitly reviewed `shadcn`
  version for that invocation rather than keeping it installed.
- Result: `npm audit` reports **0 vulnerabilities** after `npm ci`.

## Python

- `uv export --frozen --extra dev --extra map --no-emit-project` ->
  `uvx pip-audit -r ... --disable-pip`: **0 vulnerabilities**.
- `lore/release_constraints.txt` -> `uvx pip-audit --disable-pip --no-deps`:
  **0 vulnerabilities**.
- Scope: Linux + CPython 3.12 environment evaluation; other-platform marker
  branches in the lockfile were not exercised.

## Repeat commands

Run from the repo root:

```bash
# web
(cd web && npm ci && npm audit --json)
# python (frozen, dev+map)
uv export --frozen --extra dev --extra map --no-emit-project -o /tmp/req.txt
uvx pip-audit -r /tmp/req.txt --disable-pip -f json
# published constraints
uvx pip-audit -r lore/release_constraints.txt --disable-pip --no-deps -f json
```
