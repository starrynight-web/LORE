# Setup site

The site is the dashboard for creating personas. The editor still starts `lore-solo mcp` on its own. Closing the site leaves those files in place.

`uvx lore-solo install` puts the command on this computer. `uvx lore-solo uninstall` removes it and leaves the persona library in place. `uvx lore-solo setup`, or `./scripts/lore-solo setup` from a clone, starts Django on `127.0.0.1:7421` and Next.js on `127.0.0.1:3000`. The same commands work on macOS, Linux, and Windows. The page rewrites `/api` to Django. The link printed in the terminal carries a setup key that changes every start. That key guards the site only.

To work on the page while the API is already running:

```bash
cd web
npm ci
npm run dev
```

`web/lib/api.ts` is the only client. It calls same-origin `/api/...` and throws the `error` string from a failed JSON body.

## Pages

A new library opens a welcome dialog over the dashboard (`web/components/onboarding.tsx`). Outside clicks and Escape do not dismiss the onboarding wizard. **Get started** leads through four steps: **1. Connect** (`connect` — auto-connect installed editors, copy the universal `uvx lore-solo connect` command, write project MCP configs, and check optional SkillSpector), **2. Skills** (`skills`), **3. Role** (`persona`), and **4. Project** (`codebase`). Each step can be skipped. Finishing or skipping the last step marks setup complete in `.lore/onboarding.json`.

| Route | File | What it does |
| --- | --- | --- |
| `/` | `web/app/page.tsx` | **Dashboard**: installed skills & created personas counts, `+ Add` quick-add menu (`Add skill`, `Create persona`), Editor & MCP quickstart card (`Connect IDE`, `MCP`, `Store` tabs), `Most called skills` bar chart, `Personas` card, and `Summary` token telemetry spline chart |
| `/personas` | `web/app/personas/page.tsx` | Create, list, delete personas (with confirm dialog; deleting returns skills to inbox), and add starter personas |
| `/personas/[id]` | `web/app/personas/[id]/page.tsx` | Edit one persona, search/sort/select its skills, approve or bulk-approve drafts (with accept-risk flow), and add a skill |
| `/skills` | `web/app/skills/page.tsx` | Search/sort saved skills and waiting inbox skills, add from skills.sh or local files/folders, adopt inbox skills into a persona, and delete skills |
| `/skills/[...id]` | `web/app/skills/[...id]/page.tsx` | Read, edit, and approve one skill |
| `/codebase` | `web/app/codebase/page.tsx` | Add, list, and delete codebases |
| `/codebase/[id]` | `web/app/codebase/[id]/page.tsx` | Rename a codebase, build/update its Graphify map, view the theme-synced embedded `/api/codebases/<id>/graph` map, and inspect extracted/inferred links |
| `/replay` | `web/app/replay/page.tsx` | **Decisions**: audit trail of `get_context` decision files and agent-reported receipts |
| `/connect` | `web/app/connect/page.tsx` | Auto-connect installed editors (`POST /api/connect/agents`), copy the agent prompt/command (`GET /api/connect`), or write project MCP configs (`.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json`) |
| `/settings` | `web/app/settings/page.tsx` | Token budget, max items, draft provider key, draft model picker, and SkillSpector status/install command |
| `/locked` | `web/app/locked/page.tsx` | Shown when the `lore_key` setup cookie is missing. No shell or navigation |

The shell is `web/components/Shell.tsx` (which also keeps `backdrop-blur` on a `fixed inset-0 -z-10` layer so modals never clip). Desktop navigation is a sticky floating left icon rail in `web/components/app-sidebar.tsx` (`Dashboard`, `Personas`, `Skills`, `Codebase`, `Decisions`, plus a bottom dark/light theme switcher and `Settings`). Mobile navigation is a top bar with circular navigation pills and a theme button in `web/components/site-header.tsx`. `/locked` does not use the shell.

API handlers are in `lore/setup/views.py`, routed from `lore/setup/urls.py`. A new page action needs a view there and a call in the page. The view writes markdown through `lore/core`. It does not keep a second store.

## Visual system

The setup dashboard uses the **Intellecta ("Soft Bento Glass")** visual system (`Plus Jakarta Sans` + `JetBrains Mono` in `web/app/layout.tsx`, lime `#c8eb5e` and lavender `#a59bf3` accent tokens in `web/app/globals.css`), with rounded bento cards, `web/components/page-hero.tsx` headers, `web/components/skill-bar-chart.tsx`, and `web/components/token-spline-chart.tsx`.

UI primitives use the `base-nova` shadcn style (`web/components.json`) built on Base UI (`@base-ui/react`):

- A link-styled button uses `nativeButton={false}` and `render={<Link href="..." />}`.
- `Select` takes an `items` list.
- Forms use `Field`, `FieldLabel`, and `FieldGroup` with React state. They post JSON through `api()`.
- Success messages use `toast.success` from `sonner`. Failures use `web/components/error-alert.tsx`.
- Icons are lucide. Add a component with an explicitly reviewed generator version — `npx shadcn@<pinned-version> add <name>` from `web/` — not `@latest` (see docs/solo/DEPENDENCY_AUDIT.md; the CLI package is intentionally not a dependency and 4.22.1 in particular carried advisory-flagged transitive deps). The `data-*` variants, accordion keyframes, and `no-scrollbar` the components rely on are vendored in `web/app/ui-utilities.css` under the upstream MIT license (kept in a `/*! ... */` comment in `globals.css` so it survives minification); `components.json` remains as generator metadata.

`web/app/layout.tsx` wraps the tree in `ThemeProvider` (`defaultTheme="system"`) and `TooltipProvider`. Tokens live in `web/app/globals.css`.

## Draft model

Settings calls `GET /api/provider/models` and `POST /api/provider/models`. The list comes from the provider’s models endpoint with the saved key. The public response is `{provider, configured, last4, model}`. The key stays in the library `.lore/provider.json` and is never returned.

Until a model is saved, drafts use the default for that provider: Groq `llama-3.3-70b-versatile`, OpenRouter `openai/gpt-4o-mini`, Gemini `gemini-3.5-flash-lite`, OpenAI `gpt-4o-mini`, Anthropic `claude-haiku-4-5`. Saving a new key for the same provider keeps the chosen model. Switching providers resets to that provider’s default.

## A window later

The setup site can later open in its own application window. The installer would still place the `lore-solo` command where editors can start it. `lore-solo mcp` stays that process. A window has not been built.
