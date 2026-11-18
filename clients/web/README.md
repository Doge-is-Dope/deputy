# Computer Use Web

The web app for chatting with the agent and watching or controlling the desktop live: React, TypeScript and Vite, talking to the runtime over HTTP and WebRTC.

## Development

Use Node.js 24 and Bun 1.4.4. From `clients/web/`:

```bash
bun install --frozen-lockfile
bun run dev
```

Start the runtime first ([main README](../../README.md#quick-start)). The dev server runs on port 5173 and passes `/api` to `http://127.0.0.1:8000`, or to `CU_API_URL`. For the live view of a runtime on another computer, the browser must reach its TURN server.

## Code layout

| Path              | What it holds                                                                                |
| ----------------- | -------------------------------------------------------------------------------------------- |
| `src/App.tsx`     | The page and its actions                                                                     |
| `src/components/` | The interface: conversation, composer, sidebar, live desktop view, settings and shared parts |
| `src/hooks/`      | Data from the runtime, event streams, routing and the live connection                        |
| `src/lib/`        | API types, turning run events into a conversation, and formatting                            |
| `src/locales/`    | English and Traditional Chinese text                                                         |
| `src/index.css`   | Global styles and themes                                                                     |

## Attachments

The composer takes up to five files from the plus button, a paste or a drop anywhere on the page, with a new message or an answer to the agent's question: each up to 20 MB (a PDF over 5 MB or 100 pages only the coding agent opens). Each uploads as soon as it is added, a photo over 2048 on the long side or over 5 MB shrunk first (`src/lib/attachments.ts`), and the message goes once all are up. Attachments go with a new message, not while the agent works. A picture the coding agent links in its reply is shown there and opens full size. `Caddyfile` caps a request at 24 MB.

Clicking an attachment opens it in a tab of the panel beside the conversation, next to the computer's tab (`src/lib/side-panel.ts`, `src/components/side-panel/`): a picture, a PDF's pages (drawn by pdf.js, loaded the first time a PDF opens, only the pages near the view kept drawn), or plain text (`previewOf` in `src/lib/attachments.ts`); any other file downloads. A picture can be marked up there with a pen and shapes, and comments: numbered pins whose words go into the message being written, each with where it is on the picture in percent, as ChatGPT sends them (`src/lib/markup.ts`). Strokes and shapes are drawn into a copy at the picture's own size as a PNG, which goes into the message through the same shrink and upload as any file, or in place of the composer tile it came from; a picture with comments only goes as it is. The original is never changed. The computer's live view runs only while its tab is chosen.

## Checks and build

```bash
bun run lint
bun run test
bun run build
```

`bun run build` checks types and writes `dist/`. The Docker image serves `dist/` and passes `/api` to the runtime; compose runs it on port 8080.
