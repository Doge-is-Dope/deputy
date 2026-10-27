# Computer Use Web

The React, TypeScript and Vite front end for conversations, task progress and live desktop control. It connects to the runtime through HTTP and WebRTC. The runtime handles model calls and desktop actions.

## Local development

Use Node.js 24 and Bun 1.4.4. The Bun version is pinned in `package.json`. Bun installs dependencies from `bun.lock`; Vite, TypeScript and Vitest run on Node.js.

Install the locked dependencies from `clients/web/`:

```bash
bun install --frozen-lockfile
```

Start the runtime and the dev server as in the [main README](../../README.md#quick-start). The dev server proxies `/api` to `http://127.0.0.1:8000`; set `CU_API_URL` to point it elsewhere:

```bash
CU_API_URL=http://127.0.0.1:8000 bun run dev
```

The live view connects through `/api/live`. During takeover, it sends mouse and keyboard input over a WebRTC data channel. Text entered with an input method editor (IME) is sent after composition ends.

If the runtime is on another computer, the browser must be able to reach both its API and the TURN relay servers listed in `/api/status` under `ice_servers`. The default Compose setup is for local access; setting `CU_API_URL` alone does not configure remote access.

## Code layout

| Path | Responsibility |
| --- | --- |
| `src/App.tsx` | Switching conversations, sending, stopping, continuing and control actions |
| `src/components/conversation/` | The conversation page: messages, replies, delegated work and its steps, and the plan card |
| `src/components/sidebar/` | The sidebar: projects, recents, conversation rows, dragging, and its list state |
| `src/components/desktop/` | The live desktop view and the remote screen |
| `src/components/markdown/` | Agent replies rendered as markdown, loaded on demand |
| `src/components/composer/` | The message composer: its text and @ mentions, the question it asks and the answers to it |
| `src/components/settings/` | The settings dialog, a file per page; a page is added to `PAGES` in `settings-dialog.tsx` |
| `src/components/` | The screenshot viewer, icons and other parts used across the page |
| `src/components/ui/` | Shared shadcn UI components |
| `src/hooks/use-api.ts` | Status and run queries, server-sent events and the open conversation's state |
| `src/hooks/use-live.ts` | The live view's WebRTC connection, reconnects and input channel |
| `src/lib/api.ts` | API types, requests, and event and screenshot URLs |
| `src/lib/thread.ts`, `format.ts` | Converting events into conversation items and plans, and formatting text |
| `src/lib/conversations.ts` | Grouping runs into conversations by thread; sending in an open conversation continues it |
| `src/lib/appearance.ts`, `src/lib/themes.ts`, `src/index.css` | Appearance settings, theme palettes and global styles |

## Checks and build

```bash
bun run lint
bun run test
bun run build
```

`bun run test` runs Vitest. `bun run build` checks TypeScript types and writes the production build to `dist/`.

After building, run `bun run preview` to preview the site. It uses the same `/api` proxy and `CU_API_URL` setting as the development server. Keep the runtime running in a separate process. The runtime does not serve the front end's static files yet.

KaTeX is pinned and overridden to 0.19.1 because the math plugins still request the vulnerable 0.16 series. Keep the override until their dependency ranges include a patched version. The shared UI state variants live in `src/components/ui/variants.css`, so styling does not pull in the shadcn CLI and its dependencies.
