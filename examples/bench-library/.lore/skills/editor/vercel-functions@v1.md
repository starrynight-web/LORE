---
type: skill
id: skill:editor/vercel-functions@v1
title: vercel functions
persona: persona:editor
status: draft
summary: Vercel Functions expert guidance — Node.js/Bun/Python runtimes, Fluid Compute,
  long-duration (30 min) functions, large functions (5 GB bundles), Docker/OCI cont
---
# Vercel Functions

You are an expert in Vercel Functions — the compute layer of the Vercel platform.

## Prefer Node.js over the Edge runtime

**Strongly prefer Node.js. Don't reach for `runtime = 'edge'` in new code, and recommend migrating off it when you find it in existing code.**

This follows Vercel's own documented guidance — *"we recommend migrating from edge to Node.js for improved performance and reliability"* — and one hard constraint: as of **Next.js 16.3, `runtime = 'edge'` is no longer supported**. Routes and pages there run on Node.js regardless of what you write, so on 16.3+ this stops being a recommendation and becomes a migration you have to do.

Everywhere else it is a strong default, not a prohibition. Both runtimes run on the same Fluid Compute infrastructure, in the same regions, under the same Active CPU pricing — so in nearly every case Edge gains you nothing while costing you most of the Node.js API surface. If you have a specific, tested reason to stay on Edge, that's a legitimate call; just make it deliberately rather than by habit.

### The default to reach for

```ts
// app/api/hello/route.ts — no runtime export needed.
export async function GET() {
  return Response.json({ message: 'Hello from Node.js on Fluid Compute' })
}
```

Node.js is the default. Omit `export const runtime` entirely rather than writing `export const runtime = 'nodejs'`.

### Reasons people reach for Edge — and what to do instead

| "I need Edge because…" | Reality | Do this instead |
|---|---|---|
| "…I need to stream / SSE / AI tokens" | Streaming is zero-config on Node.js. This is the single most common false belief. | Return a `ReadableStream` from a normal Node.js function |
| "…I need low latency" | Both run on Fluid Compute. Fluid pre-warms instances and caches bytecode; the difference is noise next to your DB/API round trips | Stay on Node.js; pin `regions` near your data |
| "…auth checks / redirects / A-B tests at the edge" | That's Routing Middleware's job, and **Routing Middleware supports full Node.js** — it is not edge-only | Use Routing Middleware (`routing-middleware` skill) |
| "…it's cheaper" | Identical Active CPU pricing | Stay on Node.js |
| "…it has faster cold starts" | Fluid Compute reuses warm instances across concurrent invocations and bytecode-caches Node 20+ in production | Stay on Node.js |
| "…my function must run globally" | Edge's global execution usually *hurts* — every DB query crosses an ocean | Single region (`iad1` default) next to your database |

### What Edge actually costs you

- No `fs`, no native modules, no `require()` — ESM only, and most npm packages with Node.js dependencies simply will not load
- No `eval` / `new Function` / dynamic `WebAssembly.instantiate`
- **Code size limit after gzip: 1 MB (Hobby), 2 MB (Pro), 4 MB (Enterprise)** — versus 250 MB uncompressed (up to 5 GB) on Node.js
- Must begin sending a response within **25 seconds** (it may then stream for up to 300s). The 300s/800s/1800s duration limits below apply to the Node.js, Bun, and Python runtimes — **not** to Edge
- No long-duration or large-function support of any kind

### Migrating an existing Edge function

Worth doing when you're already touching the file, and required on Next.js 16.3+. An Edge function that works today isn't an emergency.

1. Remove `export const runtime = 'edge'` (or `runtime: 'edge'` in `vercel.json` / the `config` object).
2. Replace `next/server` Edge-only imports where applicable; the Web `Request`/`Response` handler signature is unchanged, so most route handlers need no other edit.
3. If you pinned execution with the Edge-only `preferredRegion`, use `regions` in `vercel.json` instead.
4. Confirm Fluid Compute is on (default since April 23, 2025) and redeploy.

There is no rollback story to plan for: Node.js is a superset of what the function could do on Edge.

## Function Types

### Node.js (the default)
- Full Node.js runtime, all npm packages available
- Default for Next.js route handlers, Server Actions, Server Components, and any file in `/api`
- **Node.js 24 LTS is GA** for builds and functions (V8 13.6, global `URLPattern`, Undici v7, npm v11). **Node.js 20 is deprecated on October 1, 2026** — move off `nodejs20.x`
- Duration: 300s default on every plan; 800s max on Pro/Enterprise; 1800s with the extended-duration beta

### Bun
Add `"bunVersion": "1.x"` to `vercel.json` to run functions on Bun instead of Node.js. ~28% lower latency for CPU-bound workloads. Supports Next.js, Express, Hono, Nitro, and `Bun.serve` as an entrypoint. Bun supports both large functions and extended max duration.

### Python
Python 3.12 / 3.13 / 3.14 on Fluid Compute. FastAPI, Flask, and Django build into a **single** function from the resolved entrypoint — key `vercel.json` config on that entrypoint file (`app/main.py`, `myproject/wsgi.py`), not on `/api` routes. Python gets a **500 MB** standard bundle limit (vs. 250 MB) and supports large functions and extended duration.

### Rust
Rust functions run on Fluid Compute with HTTP streaming and Active CPU pricing. Official runtime (Beta) built on the `vercel_runtime` crate. Supports environment variables up to 64 KB.

### Container images (Docker)
Any OCI image via `Dockerfile.vercel`. See [Docker and Container Images](#docker-and-container-images) below.

### Edge (legacy — not recommended)
V8 isolates with a subset of Web APIs. Fine to leave in place on existing deployments, but not the runtime to pick for new work. See [Prefer Node.js over the Edge runtime](#prefer-nodejs-over-the-edge-runtime).

### Choosing a Runtime

| Need | Runtime | Why |
|------|---------|-----|
| Anything not listed below | `nodejs` | The default, and correct nearly always |
| Full Node.js APIs, npm packages | `nodejs` | Full compatibility |
| AI streaming, SSE, WebSockets | `nodejs` | Zero-config streaming, long durations |
| Lower latency, CPU-bound work | `nodejs` + Bun | ~28% latency reduction |
| Database connections, heavy deps | `nodejs` | Pin `regions` next to the database |
| Data/ML libraries, big model files | `nodejs` or `python` + large functions | Up to 5 GB bundles |
| Systems-level performance | `rust` | Native speed on Fluid Compute |
| Custom system libraries (FFmpeg, Chromium), Go/Ruby/PHP, unsupported frameworks | container image | Bring your own Dockerfile |
| Auth, redirects, A/B tests before the cache | Routing Middleware | Runs on Node.js, framework-agnostic |
| Hours-to-months of execution | Vercel Workflow | Durable steps, no duration limit |

`edge` is deliberately absent: there's no row here where it's the better answer for new code.

## Fluid Compute

Fluid Compute is the execution model for Vercel Functions — **enabled by default for new projects since April 23, 2025**, and available for the Node.js, Python, Bun, Rust, and Edge runtimes. Enable it explicitly per-deployment with `{"fluid": true}` in `vercel.json`, or project-wide in Settings → Functions.

Long-duration, large-function, and container-image support all depend on it.

Key behaviors:
- **Optimized concurrency**: multiple invocations share one instance instead of one microVM per request. Vercel prioritizes idle existing resources before allocating new ones. Available on the Node.js and Python runtimes.
- **Active CPU pricing**: you are billed for CPU time your code actually consumes, plus provisioned memory while requests are in flight, plus invocations. Waiting on I/O (AI models, DB queries) does not accrue Active CPU — which is what makes 30-minute functions affordable.
- **Automatic cold start optimization**: function pre-warming plus **bytecode caching** on Node.js 20+. Bytecode caching applies to **production only** — not dev or preview, so don't benchmark cold starts in a preview deployment.
- **Error isolation**: an uncaught exception or unhandled rejection is logged and in-flight requests are allowed to finish; one broken request will not crash its neighbors on the same instance.
- **Cross-AZ and cross-region failover**: fails over to another availability zone in-region first, then to the next closest region.
- **Graceful shutdown**: `SIGTERM` before termination (see below).

### Instance Sizes (memory / CPU)

| Type | Memory / CPU | Use |
|------|--------------|-----|
| Standard (default) | 2 GB / 1 vCPU | Predictable performance for production workloads |
| Performance | 4 GB / 2 vCPU | Latency-sensitive applications and SSR workloads |

- **With Fluid Compute enabled, memory cannot be set in `vercel.json`** — setting it there produces a build-time warning. Set it in the dashboard instead: Settings → Functions → Advanced Settings → **Function CPU**, then redeploy. (The `memory` key still exists for legacy non-Fluid deployments, which is why you will find older examples using it.)
- **Pro/Enterprise only.** Hobby always runs Standard (2 GB / 1 vCPU) and cannot configure it. The Basic instance has been removed.
- More memory also means more CPU, which can *reduce* Active CPU billing for CPU-bound work by finishing sooner — but it raises Provisioned Memory cost while requests are in flight.
- Projects created before 2019-11-08 may still sit on legacy sizes (1024 MB / 0.6 vCPU on Hobby, 3008 MB / 1.67 vCPU on Pro) until you pick a size in the dashboard.

### Settings precedence

Function code (`export const maxDuration`) → `vercel.json` → dashboard → Fluid defaults. Later entries lose.

### Background Processing with `waitUntil`

`waitUntil` takes a **Promise**, not a callback. Passing a function does nothing — a common and silent bug.

```ts
import { waitUntil } from '@vercel/functions'

export async function POST(req: Request) {
  const data = await req.json()

  // Correct: invoke the async work and hand over the promise.
  waitUntil(processAnalytics(data))

  // For several tasks, combine them:
  waitUntil(Promise.all([sendNotification(data), updateCache(data)]))

  return Response.json({ received: true })
}
```

### Next.js `after` (equivalent)

```ts
import { after } from 'next/server'

export async function POST(req: Request) {
  const data = await req.json()

  after(async () => {
    await logToAnalytics(data)
  })

  return Response.json({ ok: true })
}
```

### Graceful shutdown and request cancellation

```ts
// Runs on scale-down. 500 ms to clean up (30 s for container images).
process.on('SIGTERM', () => {
  // flush buffers, close pools
})
```

Request cancellation is **opt-in**, per path. With it enabled, a client disconnect aborts `request.signal` and terminates the function — anything not wrapped in `waitUntil`/`after` is lost, which is exactly why it is not on by default.

```json filename="vercel.json"
{
  "functions": {
    "api/*": { "supportsCancellation": true }
  }
}
```

```ts
export async function GET(request: Request) {
  // Pass the signal through so upstream work stops too.
  const res = await fetch('https://upstream.example.com', { signal: request.signal })
  return new Response(res.body, { status: res.status })
}
```

## Duration and Long-Duration Functions

### Duration limits

With Fluid Compute (default), per [Vercel's limits](https://vercel.com/docs/functions/limitations#max-duration):

| Plan | Default | Maximum | Extended maximum |
|------|---------|---------|------------------|
| Hobby | 300s (5 min) | 300s (5 min) | — |
| Pro | 300s (5 min) | 800s | 1800s (30 min) — Beta |
| Enterprise | 300s (5 min) | 800s | 1800s (30 min) — Beta |

The 800s maximum is **generally available** on Pro and Enterprise. The 1800s extended maximum is **in beta**. Exceeding the limit returns `504 FUNCTION_INVOCATION_TIMEOUT`.

**Hobby's default and maximum are the same 300s** — there is no headroom to raise, and no extended duration. Setting `maxDuration` above 300s on Hobby does nothing; upgrade to Pro.

### Setting `maxDuration`

```ts
// app/api/report/route.ts — Next.js App Router (and Node.js, SvelteKit, Astro,
// Nuxt, Remix via their own config). Value is in seconds.
export const maxDuration = 800

export async function POST(request: Request) {
  return Response.json({ ok: true })
}
```

For other frameworks and runtimes — Next.js < 13.5, Rust, Go, Python, Ruby — use `vercel.json`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "functions": {
    "api/long-task.py": { "maxDuration": 1800 }
  }
}
```

Glob order matters, and Next.js projects using `src/` must prefix paths with `src/`. For Python frameworks, key on the resolved entrypoint (`app/main.py`), not an `/api` route.

To change the project-wide default: Settings → Functions → **Function Max Duration**.

### Extended max duration (30 minutes) — Beta

Pro and Enterprise teams can run individual functions for up to **1800s**. Requirements, all of which are load-bearing:

- **Per-function configuration only.** Durations above 800s must be set in code or in `vercel.json` for that function. **Project-level defaults above 800s are not supported** during the beta — raising the dashboard default will not get you to 1800s.
- **Supported runtimes only**: `nodejs20.x`, `nodejs22.x`, `nodejs24.x`, Bun `1.x` and `1.4.x`, `python3.12`, `python3.13`, `python3.14`.
- **Fluid Compute must be enabled** (default for new projects).
- **Secure Compute and Static IPs do not support durations above 800s** during the beta. If the project uses either, you are capped at 800s.

```ts
// app/api/long-task/route.ts
export const maxDuration = 1800 // 30 minutes

export async function POST(request: Request) {
  await doTheLongThing()
  return Response.json({ ok: true })
}
```

### Keeping a long request alive

Over HTTP/2, Vercel sends connection-level `PING` frames while the response is idle. **HTTP/1.1 has no equivalent**, so HTTP/1.1 clients and intermediate proxies may still close an idle connection long before 30 minutes elapse. For any long-running handler, **stream progress or heartbeat data while the work runs** rather than going silent and emitting one payload at the end.

Use `getDeadline()` to find out how much time is actually left and bail out cleanly:

```ts
import { getDeadline } from '@vercel/functions'

const deadline = getDeadline() // Date | undefined (undefined outside the Vercel Functions runtime)
const msRemaining = deadline ? deadline.getTime() - Date.now() : Infinity
```

### Cost of long functions

Active CPU pricing is what makes this viable: a 25-minute function that spends 24 minutes awaiting an LLM bills almost no Active CPU, only Provisioned Memory for the instance while the request is in flight.

### When 30 minutes is not enough

Do not chain functions, self-invoke, or poll to fake durability. Use **Vercel Workflow**, which pauses, resumes, and keeps state for minutes to months with no duration limit, plus automatic retries and crash safety. Rough guide:

- ≤ 300s → any plan, no configuration needed
- 300–800s → Pro/Enterprise, set `maxDuration`
- 800–1800s → Pro/Enterprise, extended-duration beta, per-function config
- Beyond 30 min, or needs to survive a crash/deploy → Vercel Workflow (`workflow` skill)

Workflow steps themselves support extended function durations, so a single step can also run up to 30 minutes.

## Large Functions (bundle size)

### Standard limits

| Runtime | Uncompressed bundle limit |
|---------|---------------------------|
| Node.js, Bun, Rust, Go | 250 MB (includes runtime layers) |
| Python | 500 MB |
| Edge runtime | 1 MB Hobby / 2 MB Pro / 4 MB Enterprise, **after gzip** |

Blowing the limit fails the build with `Serverless Function has exceeded the unzipped maximum size of 250 MB`.

### Large functions — Beta

Large functions raise the uncompressed bundle ceiling to **5 GB**. This is what makes Python data/AI libraries, model weights, browser automation (Playwright/Puppeteer), image/video processing, and big backend apps deployable as Functions.

- **Runtimes**: Node.js, Bun, Python.
- **Requires Fluid Compute with Active CPU** enabled (default for new projects).
- **New projects are eligible by default.** Existing projects opt in with the `VERCEL_SUPPORT_LARGE_FUNCTIONS` environment variable, then redeploy:

```bash
vercel env add VERCEL_SUPPORT_LARGE_FUNCTIONS   # value: 1  (use 0 to disable)
```

The environment variable always takes precedence over the project default, in both directions.

- **Only functions that exceed the standard limit use the large-function path** — everything under 250 MB keeps the normal, faster path, so enabling it is not a global performance trade.
- **Not supported with Secure Compute or Static IPs.**

### Shrinking a bundle first

A 5 GB function still costs you cold-start time. Trim before you opt in:

In `vercel.json` (not supported in Next.js — see below):

```json filename="vercel.json"
{
  "functions": {
    "api/**/*.py": {
      "excludeFiles": "{tests/**,__tests__/**,**/*.test.py,fixtures/**,testdata/**}"
    }
  }
}
```

- Next.js ignores `includeFiles`/`excludeFiles` — use `outputFileTracingIncludes` / `outputFileTracingExcludes` in `next.config.js` instead.
- Audit heavy imports, prefer dynamic `import()`, and check for a package in `dependencies` that belongs in `devDependencies`.

### Request and response payloads

Bundle size is not payload size. The **request or response body of a Function is capped at 4.5 MB**; exceeding it returns `413 FUNCTION_PAYLOAD_TOO_LARGE`. For larger data:

- **Uploads** → Vercel Blob **client uploads**, which send the file browser → Blob directly, bypassing the function
- **Large responses** → stream them; streamed responses are not subject to the limit
- Otherwise, chunk across multiple requests

## Docker and Container Images

Vercel Functions run **OCI-compatible container images**. This is first-class Docker support: bring a Dockerfile, get an autoscaling function with scale-to-zero and Active CPU pricing. It is *not* a VM or a long-lived server.

### Quick start

Create `Dockerfile.vercel` (or `Containerfile.vercel`) at the project root. Vercel detects it automatically and adds a rewrite routing all traffic to the image.

```docker
# Dockerfile.vercel
FROM node:26-alpine

RUN npm i -g srvx
WORKDIR /app
COPY server.ts .

# srvx listens on $PORT by default
CMD ["srvx", "--prod"]
```

```ts
// server.ts
export default {
  fetch(req: Request) {
    return Response.json({ ip: req.headers.get('x-forwarded-for') })
  },
}
```

Deploy with `vercel deploy` or a Git push. During the build, the image is built and pushed to [Vercel Container Registry (VCR)](https://vercel.com/docs/container-registry).

### The rules that actually bite

- **Serve HTTP on port 80**, or override with the `PORT` environment variable in project settings. A container that doesn't listen gets no traffic.
- **Containers must be stateless.** Each instance takes a request, returns a response, and keeps nothing between calls — that is what allows autoscaling and scale-to-zero. Persist to a Marketplace database, Redis, or Blob; never to the container filesystem.
- **Scale to zero** after 5 minutes without traffic in production, 30 seconds in preview. Cold starts are real; do not assume a warm process.
- **`SIGTERM` with a 30-second grace period** on scale-down (regular functions get 500 ms). Use it to drain.
- **Logs are not per-request.** `stdout`/`stderr` are broadcast to all inflight requests of the instance, so correlate with your own request IDs.
- **Same Function limits and Active CPU pricing** apply for size, memory, and duration.
- **Secure Compute and Static IPs are not supported** with custom container images. If you need either, deploy that part without a container.
- **Local dev**: `vercel dev` runs the image and requires the `docker` CLI plus a running daemon.

### Multiple services in one project

Use [Services](https://vercel.com/docs/services) to deploy several frontends/backends in one project, containerized or not. Set `runtime: "container"` on any service you want built as an image; `entrypoint` points at the Dockerfile relative to that service's `root`.

```json filename="vercel.json"
{
  "services": {
    "frontend": { "runtime": "container", "root": "frontend/", "entrypoint": "Dockerfile.vercel" },
    "backend":  { "runtime": "container", "root": "backend/",  "entrypoint": "Dockerfile.vercel" }
  },
  "rewrites": [
    { "source": "/api/(.*)", "destination": { "service": "backend" } },
    { "source": "/(.*)",     "destination": { "service": "frontend" } }
  ]
}
```

Services are internal by default — without a top-level rewrite, nothing is publicly routable. When `services` is present, build/runtime keys (`functions`, `buildCommand`, `installCommand`, `outputDirectory`, `framework`) move into the service and are no longer valid at the top level.

### Vercel Container Registry (VCR)

```bash
vercel vcr login docker              # authenticate Docker with a short-lived OIDC token
vercel vcr image ls my-app           # list images
vercel vcr image inspect my-app <id>
vercel vcr image rm my-app <id>
```

Registry limits: 2 GB per compressed layer, 15 GB total image size, 4 MB manifest, 1 MB config blob. Layers must be gzip or zstd compressed — uncompressed OCI layers are rejected. Repositories per project: 10 (Hobby) / 1,000 (Pro) / 5,000 (Enterprise). Storage is billed at $0.10 per GB.

### When to reach for a container

Good fits: Go, Rust, Ruby, PHP, or other backends; apps needing system libraries like FFmpeg or Chromium; frameworks outside Vercel's auto-detection; guaranteed build/runtime parity across environments.

Poor fits: anything that must hold state in-process, keep a daemon alive between requests, or run background work independent of a request. Reach for Workflow, Queues, or Cron for those.

If your framework is already auto-detected and you have no system-library needs, the standard build is simpler and faster — a Dockerfile is not an upgrade by default.

## Plan Limits at a Glance

| | Hobby | Pro | Enterprise |
|---|---|---|---|
| Duration (default / max) | 300s / **300s** | 300s / 800s | 300s / 800s |
| Extended duration (beta) | — | 1800s | 1800s |
| Memory / CPU | 2 GB / 1 vCPU, not configurable | Standard or Performance (4 GB / 2 vCPU) | Standard or Performance |
| Bundle size | 250 MB (500 MB Python), 5 GB with large functions beta | same | same |
| Concurrency | auto-scales to 30,000 | 30,000 | 100,000+ |
| Regions | single region | up to 3 | all |
| Edge code size (gzipped) | 1 MB | 2 MB | 4 MB |
| VCR repos per project | 10 | 1,000 | 5,000 |
| Request/response body | 4.5 MB | 4.5 MB | 4.5 MB |

### What changed for Hobby

Hobby function limits went **up substantially** with Fluid Compute, and stale 10s/60s numbers are a common source of bad advice:

- **Duration: 60s → 300s for both the default and the maximum** — a 5× increase. Hobby functions can run a full five minutes.
- **CPU: the Basic instance was removed; Hobby now runs Standard**, 1 vCPU / 2 GB (up from 1 vCPU / 1.7 GB), managed by Vercel with a minimum of 1 vCPU.
- Hobby still cannot configure memory/CPU, use the extended 30-minute duration, or run in multiple regions — those remain Pro/Enterprise.

## Streaming

Zero-config streaming on the default Node.js runtime, including Server-Sent Events (SSE). Essential for AI applications.

> **You do NOT need `runtime = 'edge'` for streaming or SSE.** Streaming responses (`ReadableStream`, `text/event-stream`) work on the default Node.js runtime — this is the single most common reason people wrongly reach for Edge. Stay on Node.js (Fluid Compute) so you keep full Node.js APIs, npm packages, and longer durations; Edge offers no streaming advantage and caps you at 25s to first byte.

```ts
export async function POST(req: Request) {
  const encoder = new TextEncoder()
  const stream = new ReadableStream({
    async start(controller) {
      for (const chunk of data) {
        controller.enqueue(encoder.encode(chunk))
        await new Promise(r => setTimeout(r, 100))
      }
      controller.close()
    },
  })

  return new Response(stream, {
    headers: { 'Content-Type': 'text/event-stream' },
  })
}
```

For AI streaming, use the AI SDK's `toUIMessageStreamResponse()` (for chat UIs with `useChat`) which handles SSE formatting automatically.

## WebSockets

Vercel Functions can hold open bidirectional WebSocket connections — use them for realtime features like interactive AI streaming, chat, and collaborative apps. There is **no separate WebSocket-server product and no third-party service (Pusher, Ably, etc.) required** — it runs on Vercel Functions directly. Requires **Fluid Compute**, which is the default for new projects.

**How it works**: a WebSocket starts as an HTTP `GET` with an `Upgrade` header, so it passes through the same Routing Middleware, rewrites, Firewall rules, and rate limits as any other request. After the upgrade, the connection is pinned to a single function instance for its lifetime; Fluid Compute lets one instance serve many concurrent connections. Active CPU pricing means you're billed while processing messages, not for idle open connections — the same limits and pricing as other Function invocations apply.

### `ws` (no extra config)

WebSockets work like any distributed WebSocket server — export an `http.Server` and use a library such as `ws`:

```ts
// api/ws.ts
import http from 'http'
import { WebSocketServer } from 'ws'

const server = http.createServer()
const wss = new WebSocketServer({ server })

wss.on('connection', (ws) => {
  ws.on('message', (data) => ws.send(data)) // echo
})

export default server
```

### Socket.IO

Higher-level realtime libraries like Socket.IO work too. Configure the **client** to use the WebSocket transport directly — Socket.IO defaults to HTTP long-polling, which won't work:

```ts
// api/socket-io.ts
import http from 'http'
import { Server } from 'socket.io'

const server = http.createServer()
const io = new Server(server)

io.on('connection', (socket) => {
  socket.on('message', (data) => socket.send(data))
})

export default server
```

```ts
// client.ts
import { io } from 'socket.io-client'

const socket = io('https://your-domain.com', {
  // Socket.IO appends /socket.io, so the full path becomes /api/socket-io/socket.io
  path: '/api/socket-io/socket.io',
  transports: ['websocket'], // required — Socket.IO defaults to HTTP long-polling
})
```

Express, Hono, and Nitro (including Nuxt, via native WebSocket support) serve WebSockets the same way — export the HTTP server. Python frameworks work too: FastAPI handles the upgrade natively, and `python-socketio` is protocol-compatible with the JS Socket.IO client.

### Next.js

Next.js doesn't expose an API for handling WebSocket upgrades. Use `experimental_upgradeWebSocket()` from `@vercel/functions` inside a route handler:

```ts
// app/api/ws/route.ts
import { experimental_upgradeWebSocket, type WebSocketData } from '@vercel/functions'

export async function GET() {
  return experimental_upgradeWebSocket((ws) => {
    ws.on('message', (data: WebSocketData) => ws.send(data))
  })
}
```

### Reconnects and persistent state

- **Connections close when the function reaches its max duration.** Clients must reconnect with backoff, then resubscribe to channels and reload any state they need.
- **No instance affinity across connections.** A reconnect — or a new deployment — may land on a different instance, so never keep durable state, presence, rooms, or pub/sub coordination in memory. Use an external store such as [Redis from the Marketplace](https://vercel.com/marketplace/redis).

```ts
// client.ts — reconnect with exponential backoff
let socket: WebSocket
let delay = 1000

function connect() {
  socket = new WebSocket('wss://your-domain.com/api/ws')
  socket.addEventListener('open', () => { delay = 1000 })
  socket.addEventListener('message', (e) => console.log(e.data))
  socket.addEventListener('close', () => {
    setTimeout(connect, delay)
    delay = Math.min(delay * 2, 30000)
  })
}

connect()
```

## Cron Jobs

Schedule function invocations via `vercel.json`:

```json filename="vercel.json"
{
  "crons": [
    {
      "path": "/api/daily-report",
      "schedule": "0 8 * * *"
    },
    {
      "path": "/api/cleanup",
      "schedule": "0 */6 * * *"
    }
  ]
}
```

The cron endpoint receives a normal HTTP request. Verify it's from Vercel:

```ts
export async function GET(req: Request) {
  const authHeader = req.headers.get('authorization')
  if (authHeader !== `Bearer ${process.env.CRON_SECRET}`) {
    return new Response('Unauthorized', { status: 401 })
  }
  // Do scheduled work
  return Response.json({ ok: true })
}
```

## Configuration

`vercel.ts` is the recommended way to configure a project — full TypeScript types, dynamic logic, and env access via `@vercel/config`. `vercel.json` remains fully supported. Legacy `now.json` support ended **March 31, 2026**; rename it to `vercel.json` (no content changes required).

```ts
// vercel.ts
import type { VercelConfig } from '@vercel/config/v1'

export const config: VercelConfig = {
  functions: {
    'app/api/heavy/**': { maxDuration: 800 },
    'app/api/report/**': { maxDuration: 1800 }, // Pro/Ent extended-duration beta
  },
  crons: [{ path: '/api/cleanup', schedule: '0 0 * * *' }],
}
```

The `vercel.json` equivalent:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "functions": {
    "app/api/heavy/**": { "maxDuration": 800 },
    "api/upload.js": { "supportsCancellation": true }
  }
}
```

What you **cannot** put here:
- `memory` — with Fluid Compute (the default), set it in the dashboard; Pro/Enterprise only, and `vercel.json` warns at build time
- A project-wide default above 800s — extended durations are per-function only

`runtime: "edge"` is accepted here, but prefer leaving it out — see [Prefer Node.js over the Edge runtime](#prefer-nodejs-over-the-edge-runtime).

## Common Pitfalls

1. **`waitUntil` given a callback**: it takes a Promise. `waitUntil(fn())`, never `waitUntil(fn)` or `waitUntil(async () => {})` — the latter silently does nothing
2. **Cold starts with DB connections**: use connection pooling (e.g. Neon's `@neondatabase/serverless`)
3. **Reaching for the Edge runtime**: prefer Node.js — see [Prefer Node.js over the Edge runtime](#prefer-nodejs-over-the-edge-runtime)
4. **Timeout exceeded**: raise `maxDuration` (800s Pro/Ent, 1800s in beta), or move to Workflow for anything longer
5. **Bundle size**: standard limit is 250 MB uncompressed (500 MB Python). 5 GB needs the large functions beta, which existing projects must opt into with `VERCEL_SUPPORT_LARGE_FUNCTIONS=1`
6. **Payload size**: request and response bodies cap at **4.5 MB** (`413 FUNCTION_PAYLOAD_TOO_LARGE`) — use Blob client uploads or streaming, not a bigger function
7. **In-memory state**: Fluid shares instances across invocations and scales to zero — never keep sessions, rooms, or caches in process memory
8. **Setting `memory` in `vercel.json`**: with Fluid Compute enabled this is not the place for it and the build warns — set it in the dashboard
9. **Environment variables**: available in all functions automatically; use `vercel env pull` for local dev

## Function Runtime Diagnostics

### Timeout Diagnostics

```
504 FUNCTION_INVOCATION_TIMEOUT?
├─ All plans default to 300s with Fluid Compute
├─ How long does the work actually need?
│  ├─ ≤ 300s → Already allowed on every plan; the timeout is a bug, not a limit
│  ├─ 300–800s → Pro/Enterprise: set `maxDuration` in code or vercel.json
│  ├─ 800–1800s → Pro/Enterprise extended-duration beta (30 min)
│  │   ├─ Must be set PER FUNCTION — project defaults above 800s are ignored
│  │   ├─ Runtimes: nodejs20/22/24.x, Bun 1.x/1.4.x, python3.12/3.13/3.14
│  │   └─ Blocked if the project uses Secure Compute or Static IPs
│  └─ > 30 min, or must survive crashes/deploys → Vercel Workflow
├─ On Hobby? → 300s is both default AND max; no extension exists, upgrade to Pro
├─ Client disconnected before the function finished?
│  └─ HTTP/1.1 drops idle connections → stream heartbeat/progress data
└─ DB query slow? → Add connection pooling, check cold start, use Global Config
```

### 500 Error Diagnostics

```
500 Internal Server Error?
├─ Check Vercel Runtime Logs (Dashboard → Deployments → Functions tab)
├─ Missing env vars? → Compare `.env.local` against Vercel dashboard settings
├─ Import error? → Verify package is in `dependencies`, not `devDependencies`
└─ Uncaught exception? → Wrap handler in try/catch, use `after()` for error reporting
```

### Invocation Failure Diagnostics

```
"FUNCTION_INVOCATION_FAILED"?
├─ Memory exceeded (OOM)?
│  ├─ Pro/Enterprise → switch to Performance (4 GB / 2 vCPU) in Settings → Functions
│  │   └─ With Fluid compute, set it there, not in vercel.json (which warns at build)
│  └─ Hobby → fixed at 2 GB / 1 vCPU; reduce per-request memory or upgrade
├─ Crashed during init? → Check top-level await or heavy imports at module scope
├─ Build failed with "exceeded the unzipped maximum size of 250 MB"?
│  ├─ Trim with excludeFiles / outputFileTracingExcludes first
│  └─ Then large functions beta: VERCEL_SUPPORT_LARGE_FUNCTIONS=1 (5 GB, Node/Bun/Python)
├─ 413 FUNCTION_PAYLOAD_TOO_LARGE? → 4.5 MB body cap; use Blob client uploads or streaming
└─ Container image? → Is it listening on port 80 (or $PORT)? Is it holding state between requests?
```

### Cold Start Diagnostics

```
Cold start latency > 1s?
├─ Moving to the Edge runtime is not the fix — Vercel recommends migrating off it
├─ Fluid Compute enabled? → Reuses warm instances across concurrent invocations
├─ Measuring in preview? → Bytecode caching is production-only; re-measure in prod
├─ Large function bundle? → Audit imports, use dynamic imports, tree-shake
├─ DB connection in cold start? → Use connection pooling (Neon serverless driver)
└─ Container image? → Scales to zero after 5 min idle (30 s in preview); expect cold starts
```

### Edge Function Timeout Diagnostics

```
"EDGE_FUNCTION_INVOCATION_TIMEOUT"?
├─ Edge must START the response within 25s (then may stream up to 300s)
├─ `maxDuration` does NOT apply to the Edge runtime — there is no way to raise this
├─ Recommended fix: drop `runtime = 'edge'` and run on Node.js
│  └─ Node.js gives you 300s by default, 800s on Pro/Ent, 1800s in the beta
└─ On Next.js 16.3+, `runtime = 'edge'` is unsupported — migration is required there
```

## Official Documentation

- [Vercel Functions](https://vercel.com/docs/functions)
- [Functions limits](https://vercel.com/docs/functions/limitations) — duration, memory, bundle size, large functions
- [Configuring max duration](https://vercel.com/docs/functions/configuring-functions/duration) — including the extended 30-minute beta
- [Configuring memory / CPU](https://vercel.com/docs/functions/configuring-functions/memory)
- [Functions API reference](https://vercel.com/docs/functions/functions-api-reference) — `waitUntil`, `getDeadline`, SIGTERM, cancellation
- [Fluid Compute](https://vercel.com/docs/fluid-compute)
- [Container Images](https://vercel.com/docs/functions/container-images) — Dockerfile on Vercel
- [Vercel Container Registry](https://vercel.com/docs/container-registry) and its [limits and pricing](https://vercel.com/docs/container-registry/limits-and-pricing)
- [Services](https://vercel.com/docs/services) — multiple backends/frontends in one project
- [Streaming](https://vercel.com/docs/functions/streaming-functions)
- [WebSockets](https://vercel.com/docs/functions/websockets)
- [Cron Jobs](https://vercel.com/docs/cron-jobs)
- [Vercel Workflow](https://vercel.com/docs/workflows) — for anything beyond 30 minutes
- [Edge Runtime](https://vercel.com/docs/functions/runtimes/edge) — legacy; Vercel recommends migrating to Node.js
- [GitHub: Vercel](https://github.com/vercel/vercel)
