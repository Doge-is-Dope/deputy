---
name: design-system
description: The web app's design system - the type scale (which font size each role uses) and the icon system (clients/web/src/components/icons.tsx; rules in references/icons.md). Use when adding or changing text sizes, adding, redrawing, resizing or reviewing an icon, or when text or an icon looks too big, too small or too heavy next to its neighbours.
---

# Design system

The web app (`clients/web/`) uses sizes, shapes and interaction patterns found in the reference products: ChatGPT, Codex,
Claude and Apple. Do not introduce a size, shape or pattern absent from those references.

- **Type**: below.
- **Icons**: [references/icons.md](references/icons.md).

## Type

The main font is Geist. Chinese text falls back to PingFang TC, Noto Sans TC and Microsoft JhengHei (`--font-sans`
in `index.css`). Code uses Tailwind's `font-mono` stack. Use weight 400 for body text and 500 (`font-medium`) for
titles. Reply headings, bold text and table headers also use 500: `index.css` overrides Streamdown's weight 600.

### The scale

Use sizes from Tailwind's type scale and their default line heights, except where the table below specifies a
different line height. Do not use arbitrary sizes such as `text-[Npx]` or `text-[Nrem]`.

| Class | Size / line | Role |
|---|---|---|
| `text-2xl` | 24 / 32 | The home page's greeting, a project home's name, the Chats page title, the settings page heading from `md` up. |
| `text-xl` | 20 / 28 | The settings page heading on narrow screens. |
| `text-lg` | 18 / 28 | The run page's message when a run is missing or fails to load. |
| `text-base` | 16 / 24 | Dialog and sheet titles, the task goal. Headings inside a reply (h1-h6 are one size, `index.css`). |
| `text-sm` | 14 / **24** (`leading-6`) | The conversation, one size as in the ChatGPT desktop app: your messages, the agent's replies and words on the way, the status line above the composer, and the composer itself (16 below `md`, `text-base md:text-sm`: under 16 a phone zooms in on focus). A task's words and report, the plan's steps, a note, an error line. |
| `text-sm` | 14 / 20 | The interface: sidebar (its section headings too, muted), step lines, menus, buttons, settings, text fields. The details under a step and code blocks (`leading-5`). |
| `text-xs` | 12 / 16 | Small print: the time and usage under a reply, tooltips, keys, `xs` and `sm` buttons, copyable error text (mono, `leading-4`), a setting's description. |

One exception: the letter in the settings appearance preview is 10px (`text-[0.625rem]`), part of a miniature
drawing, not text to read.

### Changing a size

- Pick a role above; a new role takes the size of the nearest existing one. Adding a size needs a reason the scale
  cannot give, and goes into this table.
- Keep a role's size the same everywhere it appears (the conversation is 14 in a message, a reply and the status line).
- Muted color, not a smaller size, sets text apart: a step's details from its title, a sidebar heading from its rows.
- The @Computer logo is 1em with `em` offsets (`mentions.tsx`, `composer.tsx`), so it follows the text it sits in;
  check it after changing that text's font.

## Measuring

- [scripts/measure-type.js](scripts/measure-type.js): paste it into the Browser pane's JavaScript tool on the Vite dev
  server. It lists every rendered font size with examples and flags one off the scale.
- [scripts/measure-icons.js](scripts/measure-icons.js): see references/icons.md.
