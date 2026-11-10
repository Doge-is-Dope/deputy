# Computer Use Web

The React, TypeScript and Vite front end for conversations and live desktop control. It talks to the runtime over HTTP and WebRTC.

## Local development

Use Node.js 24 and Bun 1.4.4 (pinned in `package.json`). From `clients/web/`:

```bash
bun install --frozen-lockfile
```

Start the runtime and the dev server as in the [main README](../../README.md#quick-start). The dev server proxies `/api` to `http://127.0.0.1:8000`; set `CU_API_URL` to point it elsewhere:

```bash
CU_API_URL=http://127.0.0.1:8000 bun run dev
```

For a runtime on another computer, the browser must also reach the TURN servers in `/api/status` (`ice_servers`); `CU_API_URL` alone is not enough.

## Code layout

| Path | Responsibility |
| --- | --- |
| `src/App.tsx` | The page: switching, sending, stopping and control actions |
| `src/components/conversation/` | Messages, replies, delegated work and the plan card |
| `src/components/sidebar/` | Projects, recents, conversation rows and dragging |
| `src/components/desktop/` | The live desktop view |
| `src/components/markdown/` | Agent replies as markdown |
| `src/components/composer/` | The message composer and its questions |
| `src/components/memory/` | Rules, citations and memory notices |
| `src/components/settings/` | The settings dialog; add a page to `PAGES` in `settings-dialog.tsx` |
| `src/components/ui/` | Shared shadcn components |
| `src/components/` | Icons, the screenshot viewer and other shared parts |
| `src/hooks/use-api.ts` | Status, sidebar lists and run queries |
| `src/hooks/use-run-events.ts` | Run event streams |
| `src/hooks/use-route.ts` | The open conversation and project, from the URL hash |
| `src/hooks/use-live.ts` | The live view's WebRTC connection |
| `src/lib/api.ts` | API types and requests |
| `src/lib/conversation-lists.ts` | Sidebar pages, and the latest conversations a shut project's status comes from |
| `src/lib/conversations.ts` | Grouping runs into conversations |
| `src/lib/thread.ts`, `format.ts` | Turning events into conversation items; formatting text |
| `src/lib/memory.ts`, `settings.ts` | Memory data; settings navigation |
| `src/lib/appearance.ts`, `themes.ts`, `src/index.css` | Appearance, themes and global styles |

## Checks and build

```bash
bun run lint
bun run test
bun run build
```

`bun run build` checks types and writes `dist/`. `bun run preview` serves it with the same `/api` proxy; the runtime does not serve the front end.

The image (`Dockerfile`, `Caddyfile`) builds `dist/` and serves it with `/api` passed on to the runtime; compose runs it on port 8080. Front-end work stays on the dev server at 5173.

KaTeX is overridden to 0.19.1 until the math plugins accept a patched version. Shared UI state variants live in `src/components/ui/variants.css`, so styling does not need the shadcn CLI.
