# Setup site

The site is the dashboard for creating personas. The editor still starts `lore-solo mcp` on its own. Closing the site leaves those files in place.

`uvx lore-solo install` puts the command on this computer. `uvx lore-solo setup`, or `./scripts/lore-solo setup` from a clone, starts Django on `127.0.0.1:7421` and Next.js on `127.0.0.1:3000`. The same commands work on macOS, Linux, and Windows. The page rewrites `/api` to Django. The link printed in the terminal carries a setup key that changes every start. That key guards the site only.

To work on the page while the API is already running:

```bash
cd web
npm ci
npm run dev
```

`web/lib/api.ts` is the only client. It calls same-origin `/api/...` and throws the `error` string from a failed JSON body.

## Pages

A new library opens a welcome dialog over the dashboard. Outside clicks and Escape do not dismiss it. Get started leads to skills, then a persona, then an optional codebase map. Each of those three steps can be skipped. Finishing or skipping the last step marks setup complete.

| Route | File | What it does |
| --- | --- | --- |
| `/` | `web/app/page.tsx` | Call counts, top agents, personas, and skills, plus recent calls |
| `/personas` | `web/app/personas/page.tsx` | Create, list, and delete personas |
| `/personas/[id]` | `web/app/personas/[id]/page.tsx` | Edit one persona, open its skills, approve, and add a skill |
| `/skills` | `web/app/skills/page.tsx` | Search skills.sh, add a file, create, list, and delete skills |
| `/skills/[...id]` | `web/app/skills/[...id]/page.tsx` | Read and edit one skill |
| `/codebase` | `web/app/codebase/page.tsx` | Add, list, and delete codebases |
| `/codebase/[id]` | `web/app/codebase/[id]/page.tsx` | Rename a codebase, build its map, and read the links |
| `/settings` | `web/app/settings/page.tsx` | Token budget, max items, provider key, and draft model |
| `/locked` | `web/app/locked/page.tsx` | Shown when the setup key cookie is missing. No sidebar |

The shell is `web/components/Shell.tsx`. The sidebar links are `web/components/app-sidebar.tsx`. The header and breadcrumb are `web/components/site-header.tsx`. `/locked` does not use the shell.

API handlers are in `lore/setup/views.py`, routed from `lore/setup/urls.py`. A new page action needs a view there and a call in the page. The view writes markdown through `lore/core`. It does not keep a second store.

## Visual system

The layout follows the [shadcn dashboard example](https://ui.shadcn.com/examples/dashboard): inset collapsible sidebar, header with the sidebar trigger, stat cards, and content cards. The example’s revenue chart, document table, and account menu are not part of this site.

shadcn is the `base-nova` style (`web/components.json`). Components come from Base UI.

- A link-styled button uses `nativeButton={false}` and `render={<Link href="..." />}`.
- `Select` takes an `items` list.
- Forms use `Field`, `FieldLabel`, and `FieldGroup` with React state. They post JSON through `api()`.
- Success messages use `toast.success` from `sonner`. Failures use `web/components/error-alert.tsx`.
- Icons are lucide. Add a component with `npx shadcn@latest add <name>` from `web/`.

`web/app/layout.tsx` wraps the tree in `ThemeProvider` (`defaultTheme="system"`) and `TooltipProvider`. Tokens live in `web/app/globals.css`.

## Draft model

Settings calls `GET /api/provider/models` and `POST /api/provider/models`. The list comes from the provider’s models endpoint with the saved key. The public response is `{provider, configured, last4, model}`. The key stays in the library `.lore/provider.json` and is never returned.

Until a model is saved, drafts use the default for that provider: Groq `llama-3.3-70b-versatile`, OpenRouter `openai/gpt-4o-mini`, Gemini `gemini-2.5-flash`, OpenAI `gpt-4o-mini`, Anthropic `claude-haiku-4-5`. Saving a new key for the same provider keeps the chosen model. Switching providers resets to that provider’s default.

## A window later

The setup site can later open in its own application window. The installer would still place the `lore` command where editors can start it. `lore mcp` stays that process. A window has not been built.
