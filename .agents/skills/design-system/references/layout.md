# Layout and corners

Where things line up, how tall rows are and how round corners are. Numbers are CSS pixels.

## Even numbers

Every size, gap, offset and radius is an even number. Tailwind's whole and half spacing steps (`2`, `2.5`, `3`, ...)
are even and its quarter steps are not, so the rule is about those and arbitrary values: no `2.25`, `[3px]`, `[5px]`,
`[11px]`. Two exceptions:

- A hairline is 1px (`border`, `h-px`, `ring-1`), and what it adds to a gap is not counted.
- An optical nudge inside a drawing (the pointer's tip on the live view).

## Where it lives

These are theme tokens in `index.css`, used as classes. Do not write the value again at a call site.

| What | Token | Class |
|---|---|---|
| The radius scale | `--radius`, `--radius-xs` to `--radius-4xl` | `rounded-xs` to `rounded-4xl`. No arbitrary radius (`rounded-[...]`). |
| A popup that lists rows | `--radius-popup`, `--spacing-popup`, `--radius-row` | `rounded-popup p-popup` on the popup, `rounded-row` on its rows: menus, selects, the search list, the list over the composer (plus and @). |
| Where a sidebar row's content starts | `--spacing-row-icon`, `--spacing-row-text`, `--spacing-row-nested` | `pl-row-icon`, `pl-row-text`, `pl-row-nested`: rows, their rename fields, loading rows, drag chips, the settings navigation. |

Everything else here is a Tailwind step (`h-8`, `gap-2.5`) written where it is used: when a third place needs the same
value for the same reason, give it a token beside these.

## Columns

Icons and words each keep one column from top to bottom of a list, as in ChatGPT's sidebar.

### Sidebar (256 wide)

| What | Where |
|---|---|
| Row | 8 from each edge, 32 tall (40 on touch), `rounded-md`, 2 between rows. |
| Icon | 20, its box at x 18 to 38, so its middle is at 28. The toggle, the commands, a project's folder and the account's circle (24) all share that middle; the closed rail keeps it. |
| Label beside an icon | x 48 (`pl-row-icon`, `gap-2.5`). A project's conversations start there too (`pl-row-nested`). |
| Words with no icon | x 20 (`pl-row-text`): section headings and Recents rows. That is where an icon's line starts, so a heading sits over the icons under it. Their rename field and loading rows use the same edge. |
| Trailing button | 32, flush with the row's right edge. |
| Key label | 24 tall, 4 from the row's top, bottom and right edge (`<Kbd row>`). |
| Sections | 16 apart. |

A menu opened from a row keeps the row's columns: the account menu's icons are centered at 28 and its words start at 48
(`alignOffset={-2}`, `gap-3` on its items).

### Page card

From `md` up the page is a card on the sidebar's color: 4 from the window's top, right and bottom, flush with the
sidebar, `rounded-2xl`, its 1px edge drawn over its contents (a border would push them 1 in; a ring outside it would
go under the sidebar on its left). The live view opens inside it, beside the conversation; the line between them
stops 8 short of the card's top and bottom, apart from its edge.

### Header (52 tall in the card, 48 on a phone)

In the card, buttons are 36 with a 20 icon, 8 from its top and right, as a dialog's close button is: the icon is 16 from
the edge. The open conversation's name starts on that 16 column, `text-sm font-medium`. A card docked under the header,
such as the plan, is also 8 from the edge. The header's middle is 30 from the window's top, and the sidebar's toggle
is on that line (`md:pt-2.5` on its header, open or closed).

On a phone there is no card: buttons are 10 from the window's edge and 6 from the top, the sidebar's toggle at the left
on the same line and the name after it.

### Conversation

Replies, your message's right edge and the composer share one column (`max-w-3xl` with 16 on each side). An icon
button under a reply is pulled left by its own padding (`-ms-1.5` for a 28 button with a 16 icon), so the icon's box,
not the button's, starts at the text's edge.

### Composer

One line of text sits between the plus button and send; files open a row of their own over it and leave it as it is.
Past a line, or under a question (a step to approve, a takeover) the text takes the full width and the buttons a row
of their own under it, plus at the left and send or the answers at the right. Under such a question there is no plus
button, as nothing goes with that answer. The plus button's icon, the text and the question's icon share one column,
18 in from the border.

### Lists in a popup

| Popup | Row | Icon and gap |
|---|---|---|
| Menu, select | 32 | 16, gap 8 |
| Search | 36 | 20, gap 10; the field's text, a group's label and the icons start on the dialog's 16 column, and the times and key labels end on it (below) |
| Settings navigation | 32 | 20, gap 10: the sidebar's row |

### Dialog

Every edge sits on a column drawn from top to bottom; check it with lines (Measuring, below).

| What | Where |
|---|---|
| Words | Start 16 from the dialog's left edge and end 16 from its right: the title, the rows, the search field, a group's label. An indented column (the usage dialog's kinds of token, under the agent's name after its icon) is one more shared line, 40. |
| Close button | 36 with a 20 icon, 8 from the top and the right: its icon ends on the right 16 column and its middle is 26 down, level with an `h-8` title under `pt-2.5` or the search field (`h-13`). |
| Highlight | A row or group lit under the pointer is 8 from the dialog's sides and bottom, rounded 12, and reaches 8 past the words, as a menu row does. |
| Top and bottom | A title's line box starts 14 down; where the rows are 32, the last row's line box ends 14 up (the usage dialog), and where a list has no light, the last words end 14 up (the cited rules). A list whose rows carry their own padding keeps it (the project's rules end 20 up). |

The settings page's content keeps its own 32 margin inside the dialog; only its close button is on the dialog's column.

A settings card is `rounded-xl` with 20 inside (`px-5`); its controls are 36 tall, as a dialog's buttons and text field are. What follows a card
without one of its own (a link, a plain list) starts where the card's words do (`px-5`).

A mark to choose with, a radio or a check circle, is 20.

## Corners

One scale, in `index.css`, as steps from `--radius` (12):

| Class | Radius | Used for |
|---|---|---|
| `rounded-xs` | 6 | Key labels. Small pictures: a step's screenshot, the theme's letter. |
| `rounded-sm` | 8 | A switch's thumb. |
| `rounded-md` | 10 | Rows: sidebar, menu, select, settings navigation. `xs` and `sm` buttons. |
| `rounded-lg` | 12 | Buttons, selects, text fields, tooltips. Rows and lit rules in a dialog with a close button. |
| `rounded-xl` | 16 | Popups, dialogs without a close button, cards, code blocks. |
| `rounded-2xl` | 20 | A dialog with a close button (its 12 plus its 8 from the corner). The page card, for the same reason. The plan's card. An option inside a 28 card. |
| `rounded-3xl` | 24 | Your message's bubble. |
| `rounded-4xl` | 28 | The composer and what takes its place: a question's card, the take-over bar. |
| `rounded-full` | | Round buttons, chips, the switch. |

### Concentric corners

A rounded shape inside another, close to its corner, has the outer radius less the gap between them:

    inner = outer - gap

| Outer | Gap | Inner |
|---|---|---|
| Popup, 16 | 6 (`p-1.5`) | Row, 10 |
| Dialog with a close button, 20 | 8 | Close button, 12 |
| Page card, 20 | 8 | Header button, 12 |
| Search dialog, 20 | 8 (`p-2`) | Row, 12 |
| Search row, 12 | 6 (its top, bottom and end) | Key label, 6 |
| Usage dialog, 20 | 8 (each side and the bottom) | Row or agent group, 12 |
| Project's rules, 20 | 8 (each side and the bottom) | A lit rule, 12 |
| Selected theme's outline, 16 | 4 (`p-1`) | Its picture, 12 |
| Question card, 28 | 8 (`p-2`) | Option, 20 |
| Switch, 10 | 2 | Thumb, 8 |
| Row, 10 | 4 | Key label, 6 |
| Tooltip, 12 | 6 | Key label, 6 |

- A new popup with rows takes the first line as it is: `rounded-popup p-popup` around `rounded-row` rows.
- The gap is the same on every side that faces the outer shape: a key label in a tooltip is 6 from its top, bottom
  and right edge, and 6 from the words on its left.
- A round button in a rounded box sits the same distance from the top, the side and the bottom (the composer's send).
- When the gap is as large as the outer radius, the inner shape is clear of the corner and keeps its own radius (a
  select in a settings card, a button in a dialog with `p-4`).
- The composer, and what takes its place, keeps its 28 in the page card's corner. A narrow conversation (a side
  panel open, a small window) puts it 16 from the card's side and bottom, inside the card's 20: the rule's 4 would
  make it a box, and 16 is nearly clear of the corner.

## Measuring

Judge alignment by drawing lines, not by reading numbers alone: a column is right when every edge on it sits on one
line from top to bottom.

- [scripts/draw-guides.js](../scripts/draw-guides.js): paste it into a browser JavaScript evaluator on the Vite dev
  server with the popup, dialog or page open, then take a screenshot. It draws a red dashed line on each column that
  two or more edges share (words' starts and ends, icons, the close icon) and on the first and last line boxes, and a
  blue one on an edge that misses a column by 1 to 4px: each blue line is something to fix. It returns the columns, the misses and the top
  and bottom spacing; `__guidesClear()` takes the lines away.
- [scripts/measure-corners.js](../scripts/measure-corners.js): with the same popup, dialog or page open. It lists every
  rounded shape that sits near a rounded parent's corner, with the radius it has and the one the rule gives, and every
  odd radius. Hover a row first: a highlight shows only under the pointer.
