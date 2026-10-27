# Icons

Icons are defined in `clients/web/src/components/icons.tsx` and rendered through its `Icon` wrapper. Application icons are
drawn locally rather than copied from an icon library. Provider logos are the exception; see **Where shapes come from**.

## The grid and the line

- A 24 × 24 viewBox, round caps and joins, soft rounded corners. `Icon` renders 20 × 20 by default.
- Lines only. Strokes do not scale with the icon (`vector-effect: non-scaling-stroke`, `index.css`): 1.33 screen
  pixels at 20px (ChatGPT's line), 1.25 at 16px and under (the `[data-icon]:is(.size-4, .size-3.5)` rule, plus trace
  and menu icons by their slot). Never set a stroke width on a drawn path; only a mask's cut has one (`OfflineIcon`).
- Fill only where it carries meaning: the agent's solid pointer (`CursorEnterIcon`, as on the favicon), the stop
  square, the ellipsis dots (dots, so they stay round at 16px), the provider marks and `ComputerLogo`. No filled status
  icons: a filled glyph among line icons reads as wrong.
- Use a `useId()` mask for slashes and cutouts. Keep a flat cut along the slash with equal spacing on both sides,
  as in SF Symbols (`OfflineIcon`). Do not build cutouts from separate round-capped strokes. A badge on a corner is the
  exception: the line it interrupts stops short and ends round, as every line end does (`FolderPlusIcon`).
- A dot is a zero-length line (`h.01`), so it takes the stroke's width and round cap (`KeyboardIcon`, `DragIcon`).

## Sizes in the app

| Size | Where |
|---|---|
| 24px | The composer's send arrow, in its 32px button. |
| 20px | Toolbar and header buttons, the composer's stop (a 10px square in its 32px button), the live view's corners and take-over pill, the sidebar's menu buttons, banners. The default for a `Button` icon with no size class (`button.tsx`), for `Spinner` and for `Icon`. |
| 18px | The sidebar row's "more" ellipsis. |
| 16px | Step lines and status marks (`TraceIcon`), menu items, copy buttons, the settings navigation, select chevrons, the notice's close cross. |
| 14px | Row chevrons that fold a step open, the stacked agent heads. |
| 12px | Provider marks in the usage popover. |
| 1em | The @Computer logo in a message and the composer: the size of the text around it. |

Set a size with a `size-*` class on the icon, or let the container's rule size it; do not pass `width`/`height`.

## Optical size

Icons at the same pixel size must read the same size. Measure the ink box (the shape plus half the stroke each side,
at 1.33 px for 20px) in grid units:

- Most icons: 19-20.5 wide or tall. Paths stay within about 3-21.
- Circles are r 8.75 everywhere (status marks, `ClockIcon`, `InfoIcon`, `SpinnerIcon`), ink 19.5: the spinner swaps in
  place with the plan's status circles.
- Smaller by nature, and left so: chevrons, the close cross, arrows, the check, the stop square, the ellipsis, the
  mouse (`ScrollIcon`, narrow), the keyboard (flat). The provider marks and `ComputerLogo` fill all 24, as their makers
  draw them.

## Families

Shapes that mean related things share their parts, so the step list reads as one vocabulary.

- **The agent's pointer**: `ClickIcon` (pointer + burst), `PointerIcon` (move), `DragIcon` (press point, a dot, the
  pointer where it lets go), `CursorPositionIcon` (pointer + guides from the top and left edges), `CursorEnterIcon`
  (the solid pointer coming into a screen). All but `PointerIcon` reuse Click's pointer path; `PointerIcon` is the bare
  pointer drawn larger, so it alone fills the icon.
- **The person's hand**: `PointingHandIcon` (take over the desktop) and `HandIcon` (the agent asks you to take over,
  `hand.raised`). Both are one outline with fingers 3.2 wide from x 7.4, a palm whose bottom is one circular arc
  (r 7) running on into a straight thumb out to the upper left, and lines parting the fingers; the pointing hand
  raises the index and folds the rest to knuckles. Narrow, not wide: both span 3.6-20.2 across and 3-21 down, so they
  read the same size side by side.
- **Folders**: `FolderIcon` (a project in the sidebar) and `FolderOpenIcon` (one whose conversations are shown) share
  the back panel's top edge and corners; the open one's swung-out flap is one line with the back, its slant running
  into the bottom left corner, so no corner is drawn twice (two overlapping lines blur at 20px). Both ink 18.5 × 15.5.
  `FolderPlusIcon` (make a project) and `FolderRemoveIcon` (take a conversation out of its project) are the whole
  folder in place, as large as the plain one and lined up with it, with a plus or a cross filling a 7.5 square centred
  on its bottom right corner, the plus's lines running on along the right and bottom edges. The folder's line stops 3.5
  short of that square on both edges and ends round, the same in both (`FolderBadgeIcon`); the badge's tips are drawn
  just past the grid (overflow visible), and the ink box is about 22.5 × 19.5.
- **Who holds the desktop**: take-over shows the person's hand; returning control shows the agent's solid pointer in a
  screen (`CursorEnterIcon`, also on the composer's hand-over prompt).
- **Status circles**: line circles with a mark inside, r 8.75.

Name an action's icon after the action (`ScreenshotIcon`, `CursorPositionIcon`), a generic glyph after its shape.

## Where shapes come from

- SF Symbols is the reference for a shape and its proportions; name the symbol in the icon's comment ("as SF Symbols'
  viewfinder").
- Draw every shape here, on this grid and with this set's parts; never copy path data from an icon set (Lucide, Tabler
  and the like). The one exception is the provider marks, other companies' logos, which come from lobehub's set (MIT).
- Each icon gets a one-line comment saying what it means where it is used.

## Measuring and upkeep

- [scripts/measure-icons.js](../scripts/measure-icons.js): paste it into the Browser pane's JavaScript tool on the Vite
  dev server (edit `names`). It renders each icon through the app's own module and prints its ink box at 20px; compare
  it with the numbers above and with its neighbours.
- Remove icons nothing uses, and the helpers only they used. Update comments that give a size or a path's extent.
