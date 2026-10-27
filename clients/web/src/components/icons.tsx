// The app's icons, drawn in one style: a 24×24 grid, round caps and joins, and soft rounded corners. Strokes are in
// screen pixels, not scaled with the icon (non-scaling strokes, index.css): 1.33 as drawn here, ChatGPT's line at
// 20px, which the 20px icons keep, and 1.25 at 16px and under.
import {
  useId,
  type ComponentProps,
  type ReactNode,
  type SVGProps,
} from "react"

type IconProps = SVGProps<SVGSVGElement>

function Icon({ children, ...props }: IconProps & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={20}
      height={20}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.33}
      strokeLinecap="round"
      strokeLinejoin="round"
      data-icon=""
      aria-hidden
      {...props}
    >
      {children}
    </svg>
  )
}

// Navigation and layout

export const MonitorIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="3" y="4" width="18" height="12.5" rx="3" />
    <path d="M9 20.5h6M12 16.5v4" />
  </Icon>
)

export const ComposeIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M11 4H7.5A3.5 3.5 0 0 0 4 7.5v9A3.5 3.5 0 0 0 7.5 20h9a3.5 3.5 0 0 0 3.5-3.5V13" />
    <path d="M17.4 4.1a2.05 2.05 0 0 1 2.9 2.9l-7.2 7.2-3.6.9.9-3.6z" />
  </Icon>
)

// Searching the conversations (the sidebar's 搜尋, ⌘K), as SF Symbols' magnifyingglass.
export const SearchIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="10.25" cy="10.25" r="7.25" />
    <path d="M15.4 15.4 20.75 20.75" />
  </Icon>
)

// Who is signed in (the sidebar's account row), as SF Symbols' person.crop.circle: a head and shoulders in a circle
// of the status marks' size.
export const PersonIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.75" />
    <circle cx="12" cy="10" r="3" />
    <path d="M6.4 18.2a6.5 6.5 0 0 1 11.2 0" />
  </Icon>
)

// Signing out (the account menu's 登出), as SF Symbols' rectangle.portrait.and.arrow.right: a door left open, an
// arrow leaving through it.
export const SignOutIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M10 3.75H7A3.25 3.25 0 0 0 3.75 7v10A3.25 3.25 0 0 0 7 20.25h3" />
    <path d="M15.5 7.5 20 12l-4.5 4.5M20 12H9.5" />
  </Icon>
)

export const GearIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M9.18 5.19Q9.84 4.92 10.10 3.83L10.10 3.83Q10.37 2.74 11.97 2.74L12.03 2.74Q13.63 2.74 13.90 3.83L13.90 3.83Q14.16 4.92 14.82 5.19L14.82 5.19Q15.47 5.47 16.43 4.88L16.43 4.88Q17.39 4.30 18.52 5.43L18.57 5.48Q19.70 6.61 19.12 7.57L19.12 7.57Q18.53 8.53 18.81 9.18L18.81 9.18Q19.08 9.84 20.17 10.10L20.17 10.10Q21.26 10.37 21.26 11.97L21.26 12.03Q21.26 13.63 20.17 13.90L20.17 13.90Q19.08 14.16 18.81 14.82L18.81 14.82Q18.53 15.47 19.12 16.43L19.12 16.43Q19.70 17.39 18.57 18.52L18.52 18.57Q17.39 19.70 16.43 19.12L16.43 19.12Q15.47 18.53 14.82 18.81L14.82 18.81Q14.16 19.08 13.90 20.17L13.90 20.17Q13.63 21.26 12.03 21.26L11.97 21.26Q10.37 21.26 10.10 20.17L10.10 20.17Q9.84 19.08 9.18 18.81L9.18 18.81Q8.53 18.53 7.57 19.12L7.57 19.12Q6.61 19.70 5.48 18.57L5.43 18.52Q4.30 17.39 4.88 16.43L4.88 16.43Q5.47 15.47 5.19 14.82L5.19 14.82Q4.92 14.16 3.83 13.90L3.83 13.90Q2.74 13.63 2.74 12.03L2.74 11.97Q2.74 10.37 3.83 10.10L3.83 10.10Q4.92 9.84 5.19 9.18L5.19 9.18Q5.47 8.53 4.88 7.57L4.88 7.57Q4.30 6.61 5.43 5.48L5.48 5.43Q6.61 4.30 7.57 4.88L7.57 4.88Q8.53 5.47 9.18 5.19Z" />
    <circle cx="12" cy="12" r="3" />
  </Icon>
)

export const SunIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.75v1.5M12 19.75v1.5M2.75 12h1.5M19.75 12h1.5M5.46 5.46l1.06 1.06M17.48 17.48l1.06 1.06M5.46 18.54l1.06-1.06M17.48 6.52l1.06-1.06" />
  </Icon>
)

export const SparkleIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 3.5Q13 11 20.5 12Q13 13 12 20.5Q11 13 3.5 12Q11 11 12 3.5Z" />
  </Icon>
)

/** The sidebar toggle. Open, it shows the panel's edge; closed, the edge shrinks to a small handle inside the left
    side. index.css morphs between the two; the attributes are the end state, for browsers without CSS geometry. */
export const SidebarIcon = ({
  open = true,
  ...props
}: IconProps & { open?: boolean }) => (
  <Icon {...props}>
    <rect x="3" y="4" width="18" height="16" rx="4" />
    <rect
      className="sidebar-icon-edge"
      data-open={open}
      x={open ? 9.5 : 7}
      y={open ? 4 : 8}
      width={open ? 0.01 : 1.5}
      height={open ? 16 : 8}
      rx={open ? 0 : 0.75}
    />
  </Icon>
)

/** Make a panel fill the page: two arrows pointing out to the corners. */
export const ExpandIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="m14 10 5.5-5.5M14.5 4.5h5v5" />
    <path d="m10 14-5.5 5.5M9.5 19.5h-5v-5" />
  </Icon>
)

/** Put a filled panel back: two arrows pointing in from the corners. */
export const ShrinkIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M19.5 4.5 14 10M14 5v5h5" />
    <path d="M4.5 19.5 10 14M10 19v-5H5" />
  </Icon>
)

export const CloseIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />
  </Icon>
)

export const ChevronDownIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M6.5 9.5 12 15l5.5-5.5" />
  </Icon>
)

export const ChevronUpIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M6.5 14.5 12 9l5.5 5.5" />
  </Icon>
)

export const ChevronLeftIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M14.5 6.5 9 12l5.5 5.5" />
  </Icon>
)

export const ChevronRightIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M9.5 6.5 15 12l-5.5 5.5" />
  </Icon>
)

/** Delete: a soft can, with a rounded tab on the lid and its bottom corners rounded at 3, tangent to the tapered
    sides. */
export const TrashIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4.5 7h15M9 7V5.5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2V7" />
    <path d="M6 7l.79 10.72A3 3 0 0 0 9.8 20.5h4.4a3 3 0 0 0 3-2.78L18 7M10.5 10.5v5M13.5 10.5v5" />
  </Icon>
)

/** More: three dots in a row, as SF Symbols' ellipsis. Filled, not stroked, so they stay round dots at 16px, where a
    dotted stroke would thin to specks. */
export const EllipsisIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
    <circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none" />
  </Icon>
)

/** A filled mark drawn by `children` in the text color: the provider logos, as their makers draw them. */
function MarkIcon({ children, ...props }: IconProps & { children: ReactNode }) {
  return (
    <Icon fill="currentColor" stroke="none" {...props}>
      {children}
    </Icon>
  )
}

// Provider marks from LobeHub Icons (https://github.com/lobehub/lobe-icons), each in its own 24-unit grid.
// Copyright (c) 2023 LobeHub, MIT License.
export const OpenAIIcon = (props: IconProps) => (
  <MarkIcon {...props}>
    <path d="M9.205 8.658v-2.26c0-.19.072-.333.238-.428l4.543-2.616c.619-.357 1.356-.523 2.117-.523 2.854 0 4.662 2.212 4.662 4.566 0 .167 0 .357-.024.547l-4.71-2.759a.797.797 0 00-.856 0l-5.97 3.473zm10.609 8.8V12.06c0-.333-.143-.57-.429-.737l-5.97-3.473 1.95-1.118a.433.433 0 01.476 0l4.543 2.617c1.309.76 2.189 2.378 2.189 3.948 0 1.808-1.07 3.473-2.76 4.163zM7.802 12.703l-1.95-1.142c-.167-.095-.239-.238-.239-.428V5.899c0-2.545 1.95-4.472 4.591-4.472 1 0 1.927.333 2.712.928L8.23 5.067c-.285.166-.428.404-.428.737v6.898zM12 15.128l-2.795-1.57v-3.33L12 8.658l2.795 1.57v3.33L12 15.128zm1.796 7.23c-1 0-1.927-.332-2.712-.927l4.686-2.712c.285-.166.428-.404.428-.737v-6.898l1.974 1.142c.167.095.238.238.238.428v5.233c0 2.545-1.974 4.472-4.614 4.472zm-5.637-5.303l-4.544-2.617c-1.308-.761-2.188-2.378-2.188-3.948A4.482 4.482 0 014.21 6.327v5.423c0 .333.143.571.428.738l5.947 3.449-1.95 1.118a.432.432 0 01-.476 0zm-.262 3.9c-2.688 0-4.662-2.021-4.662-4.519 0-.19.024-.38.047-.57l4.686 2.71c.286.167.571.167.856 0l5.97-3.448v2.26c0 .19-.07.333-.237.428l-4.543 2.616c-.619.357-1.356.523-2.117.523zm5.899 2.83a5.947 5.947 0 005.827-4.756C22.287 18.339 24 15.84 24 13.296c0-1.665-.713-3.282-1.998-4.448.119-.5.19-.999.19-1.498 0-3.401-2.759-5.947-5.946-5.947-.642 0-1.26.095-1.88.31A5.962 5.962 0 0010.205 0a5.947 5.947 0 00-5.827 4.757C1.713 5.447 0 7.945 0 10.49c0 1.666.713 3.283 1.998 4.448-.119.5-.19 1-.19 1.499 0 3.401 2.759 5.946 5.946 5.946.642 0 1.26-.095 1.88-.309a5.96 5.96 0 004.162 1.713z" />
  </MarkIcon>
)

export const AnthropicIcon = (props: IconProps) => (
  <MarkIcon {...props}>
    <path d="M13.827 3.52h3.603L24 20h-3.603l-6.57-16.48zm-7.258 0h3.767L16.906 20h-3.674l-1.343-3.461H5.017l-1.344 3.46H0L6.57 3.522zm4.132 9.959L8.453 7.687 6.205 13.48H10.7z" />
  </MarkIcon>
)

/** The mark of a model's provider, from its "provider:model" spec; none for a provider without one. */
export function ProviderIcon({
  model,
  className,
}: {
  model: string
  className?: string
}) {
  const Mark = { openai: OpenAIIcon, anthropic: AnthropicIcon }[
    model.split(":")[0]
  ]
  return Mark ? <Mark className={className} /> : null
}

export const CheckIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </Icon>
)

/** Copy: a sheet over another, as SF Symbols' doc.on.doc. The one behind stops 3.5 short of the front one, so the
    two still read apart at 16px, where the strokes are thickest for the shape. */
export const CopyIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="9.5" y="9.5" width="11" height="11" rx="2.5" />
    <path d="M6 14.5A2.5 2.5 0 0 1 3.5 12V6A2.5 2.5 0 0 1 6 3.5h6A2.5 2.5 0 0 1 14.5 6" />
  </Icon>
)

/** Import: an arrow down into a tray, as SF Symbols' tray.and.arrow.down; a theme taken from a line of text. */
export const ImportIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 3.5v11M7.5 10l4.5 4.5 4.5-4.5" />
    <path d="M3.5 14v3a3 3 0 0 0 3 3h11a3 3 0 0 0 3-3v-3" />
  </Icon>
)

export const ArrowUpIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 19V5M6 11l6-6 6 6" />
  </Icon>
)

export const ArrowDownIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 5v14M6 13l6 6 6-6" />
  </Icon>
)

/** Go again: resuming a run. */
export const RefreshIcon = (props: IconProps) => (
  <Icon {...props}>
    {/* The arc runs into the arrowhead's corner at (20, 8.5). */}
    <path d="M20 12a8 8 0 1 1-2.34-5.66L20 8.5" />
    <path d="M20 4v4.5h-4.5" />
  </Icon>
)

/** Turning, unless `still`. The box around the glyph turns, not the svg: Chrome lays out the page's layers again every
 * frame an svg turns, and not for a box. Its classes size the glyph (and so its line weight); the rest go on the box. */
export const SpinnerIcon = ({
  className,
  still = false,
  ...props
}: ComponentProps<"span"> & { still?: boolean }) => (
  <span
    aria-hidden
    className={
      still ? "inline-flex shrink-0" : "inline-flex shrink-0 animate-spin"
    }
    {...props}
  >
    <Icon className={className}>
      <circle cx="12" cy="12" r="8.75" opacity={0.25} />
      <path d="M20.75 12A8.75 8.75 0 0 0 12 3.25" />
    </Icon>
  </span>
)

export const StopIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect
      x="6"
      y="6"
      width="12"
      height="12"
      rx="2.5"
      fill="currentColor"
      stroke="none"
    />
  </Icon>
)

// Messages and notices

const OFFLINE_SLASH = "M4.4 5.6l14.6 14.6"

/** Whole arcs of radius 6 and 12 around the dot, each ±45°, cut flat along the slash with a 0.75 gap on both sides,
 *  as SF Symbols does, so every arc still reads as one. */
export const OfflineIcon = (props: IconProps) => {
  const gap = useId()
  return (
    <Icon {...props}>
      <mask
        id={gap}
        maskUnits="userSpaceOnUse"
        x="0"
        y="0"
        width="24"
        height="24"
      >
        <rect width="24" height="24" fill="white" stroke="none" />
        {/* The slash's 1.5 plus the gap on each side, in screen pixels like every stroke. */}
        <path d={OFFLINE_SLASH} stroke="black" strokeWidth={3} />
      </mask>
      <path
        d="M3.51 10.01A12 12 0 0 1 20.49 10.01M7.76 14.26A6 6 0 0 1 16.24 14.26M12 18.5h.01"
        mask={`url(#${gap})`}
      />
      <path d={OFFLINE_SLASH} />
    </Icon>
  )
}

export const WarningIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M10.3 4.5a2 2 0 0 1 3.4 0l7 12.1a2 2 0 0 1-1.7 3H5a2 2 0 0 1-1.7-3z" />
    <path d="M12 10v3.5M12 16.5h.01" />
  </Icon>
)

export const InfoIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.75" />
    <path d="M12 11v5.5M12 7.75h.01" />
  </Icon>
)

/** Asking for a person: the agent requests a takeover. A raised hand, as SF Symbols' hand.raised, drawn as the
    pointing hand is: one outline with fingers 3.2 wide from x 7.4, a palm whose bottom is one circular arc (r 7)
    running on into the thumb, straight out to the upper left, and lines parting the fingers partway down. */
export const HandIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M7.4 13.57L7.4 6.2A1.6 1.6 0 0 1 10.6 6.2L10.6 4.6A1.6 1.6 0 0 1 13.8 4.6L13.8 5.6A1.6 1.6 0 0 1 17 5.6L17 8.2A1.6 1.6 0 0 1 20.2 8.2L20.2 14A7 7 0 0 1 8.25 18.95L4.07 14.77A1.6 1.6 0 0 1 6.33 12.51Z" />
    <path d="M10.6 6.2L10.6 11M13.8 5.6L13.8 11M17 8.2L17 11.6" />
  </Icon>
)

export const ShieldCheckIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M11.3 3.3a2 2 0 0 1 1.4 0l5.5 2a2 2 0 0 1 1.3 1.9v4.3c0 4.3-2.9 7.7-6.8 9.3a2 2 0 0 1-1.4 0C7.4 19.2 4.5 15.8 4.5 11.5V7.2a2 2 0 0 1 1.3-1.9z" />
    <path d="m9 12 2.2 2.2L15.2 10" />
  </Icon>
)

/** A person's hand, pointing: the takeover button. As SF Symbols' hand.point.up.left, the raised hand with the index
    alone standing (up to 3) and the other three folded to knuckles that step down, short lines parting them. The
    same palm and thumb. Both span 3.6 to 20.2 across and 3 to 21 down, so they read the same size side by side. */
export const PointingHandIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M7.4 13.57L7.4 4.6A1.6 1.6 0 0 1 10.6 4.6L10.6 9.8A1.6 1.6 0 0 1 13.8 9.8L13.8 10.8A1.6 1.6 0 0 1 17 10.8L17 12A1.6 1.6 0 0 1 20.2 12L20.2 14A7 7 0 0 1 8.25 18.95L4.07 14.77A1.6 1.6 0 0 1 6.33 12.51Z" />
    <path d="M10.6 9.8L10.6 12M13.8 10.8L13.8 12.7M17 12L17 13.5" />
  </Icon>
)

/** The agent's pointer, solid as on the favicon, coming into a screen: handing the desktop back to the agent. */
export const CursorEnterIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M19 10V7a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v8a4 4 0 0 0 4 4h2.5" />
    <path
      fill="currentColor"
      d="M11.53 12.2a.5.5 0 0 1 .64-.64l8 3a.5.5 0 0 1-.03.94l-3.05.95a1 1 0 0 0-.66.66l-.95 3.05a.5.5 0 0 1-.94.03z"
    />
  </Icon>
)

// The agents

/** An agent working in the background: a robot's head, as Codex marks what it did with its agents. */
export const AgentIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="4.5" y="9.5" width="15" height="11" rx="3.5" />
    <path d="M12 9.5V7M9.25 13.5v2.5M14.75 13.5v2.5M2.75 15h1.75M19.5 15h1.75" />
    <circle cx="12" cy="5.25" r="1.75" />
  </Icon>
)

// The agent's actions

/** A click: the pointer with a burst. */
export const ClickIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M9 3.5v2M4.6 5.6l1.4 1.4M3.5 10h2" />
    <path d="M9.6 10.4a.6.6 0 0 1 .8-.8l9.5 3.6a.6.6 0 0 1-.04 1.13l-3.7 1.15a1.2 1.2 0 0 0-.79.79l-1.15 3.7a.6.6 0 0 1-1.13.04z" />
  </Icon>
)

export const PointerIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M3.84 4.62A0.9 0.9 0 0 1 4.8 3.66L19.32 9.18A0.9 0.9 0 0 1 19.26 10.88L13.62 12.62A1.8 1.8 0 0 0 12.42 13.82L10.68 19.46A0.9 0.9 0 0 1 8.98 19.52Z" />
  </Icon>
)

/** A drag: where the button went down, a dot along the way, and the click's pointer where it lets go. */
export const DragIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="4.75" cy="4.75" r="1.75" />
    <path d="M7.6 7.6h.01" />
    <path d="M9.6 10.4a.6.6 0 0 1 .8-.8l9.5 3.6a.6.6 0 0 1-.04 1.13l-3.7 1.15a1.2 1.2 0 0 0-.79.79l-1.15 3.7a.6.6 0 0 1-1.13.04z" />
  </Icon>
)

/** Scrolling: a mouse and its wheel, as SF Symbols' computermouse. */
export const ScrollIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="6.5" y="3" width="11" height="18" rx="5.5" />
    <path d="M12 7v3.5" />
  </Icon>
)

/** A screenshot: the whole screen in a viewfinder's four corners, as SF Symbols' viewfinder. */
export const ScreenshotIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M3 7.5v-2A2.5 2.5 0 0 1 5.5 3h2M16.5 3h2A2.5 2.5 0 0 1 21 5.5v2M21 16.5v2a2.5 2.5 0 0 1-2.5 2.5h-2M7.5 21h-2A2.5 2.5 0 0 1 3 18.5v-2" />
    <circle cx="12" cy="12" r="2.75" />
  </Icon>
)

export const ZoomInIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-4-4M11 8.25v5.5M8.25 11h5.5" />
  </Icon>
)

export const PencilIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M14.6 5.4a2.8 2.8 0 0 1 4 4L8.5 19.5 4 20.5l1-4.5z" />
    <path d="m13.5 6.5 4 4" />
  </Icon>
)

/** Pressing keys: a keyboard, its keys as dots and its space bar. */
export const KeyboardIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="2.5" y="6" width="19" height="12" rx="3" />
    <path d="M6.5 10h.01M9.5 10h.01M12.5 10h.01M15.5 10h.01M18 10h.01M8 14.25h8" />
  </Icon>
)

export const ClockIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.75" />
    <path d="M12 7.5V12l3 2" />
  </Icon>
)

/** Where the pointer is: the click's pointer, with guides from the top and left edges to its tip, its x and y. */
export const CursorPositionIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M3 10h3.5M10 3v3.5" />
    <path d="M9.6 10.4a.6.6 0 0 1 .8-.8l9.5 3.6a.6.6 0 0 1-.04 1.13l-3.7 1.15a1.2 1.2 0 0 0-.79.79l-1.15 3.7a.6.6 0 0 1-1.13.04z" />
  </Icon>
)

export const FlagIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M5 20.5V4.5" />
    <path d="M5 5h11.2a1 1 0 0 1 .8 1.6L15 9.5l2 2.9a1 1 0 0 1-.8 1.6H5" />
  </Icon>
)

/** Running a program: a terminal's prompt. */
export const TerminalIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="3" y="4.5" width="18" height="15" rx="3" />
    <path d="m7.5 9.5 3 2.5-3 2.5M12.5 15h4" />
  </Icon>
)

/** Reading, as Codex marks a run of reads: an open book. */
export const BookIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M3.5 4.5h4.5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h4.5a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H16a4 4 0 0 0-4 3 4 4 0 0 0-4-3H3.5a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1z" />
    <path d="M12 8.5v12" />
  </Icon>
)

/** Listing files: a folder with its tab. */
export const FolderIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M3.5 7.5A2.5 2.5 0 0 1 6 5h3.3a1.5 1.5 0 0 1 1.2.6l1.2 1.6a1 1 0 0 0 .8.4H18a2.5 2.5 0 0 1 2.5 2.5v6.4A2.5 2.5 0 0 1 18 19H6a2.5 2.5 0 0 1-2.5-2.5z" />
  </Icon>
)

/** The folder open: FolderIcon's back, its right side cut short by the front flap swung out, in one line so no
    corner is drawn twice; the flap's slanted edge runs down into the bottom left corner. For the project whose
    conversations are shown. */
export const FolderOpenIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M8.5 10.5h10.9a1.1 1.1 0 0 1 1.06 1.4l-1.56 5.4a2.3 2.3 0 0 1-2.2 1.7H6a2.5 2.5 0 0 1-2.5-2.5v-9A2.5 2.5 0 0 1 6 5h3.3a1.5 1.5 0 0 1 1.2.6l1.2 1.6a1 1 0 0 0 .8.4h4a2.5 2.5 0 0 1 2.5 2.5v.4" />
    <path d="M8.5 10.5a2 2 0 0 0-1.8 1.2l-2.8 6.2" />
  </Icon>
)

/** FolderIcon in place, so it reads as large as the folders listed beside it and lines up with them, with a badge
 *  filling a 7.5 square centred on its bottom right corner. The folder's line stops 3.5 short of that square on both
 *  edges, about a line's gap at 16 and 20px, and ends round as every line does; the corner inside goes with it. The
 *  same ends for either badge. */
function FolderBadgeIcon({ badge, ...props }: IconProps & { badge: string }) {
  return (
    // The badge's tips reach a little past the grid's right and bottom edges, drawn rather than cut off.
    <Icon overflow="visible" {...props}>
      <path d="M13.25 19H6a2.5 2.5 0 0 1-2.5-2.5v-9A2.5 2.5 0 0 1 6 5h3.3a1.5 1.5 0 0 1 1.2.6l1.2 1.6a1 1 0 0 0 .8.4H18a2.5 2.5 0 0 1 2.5 2.5v1.65" />
      <path d={badge} />
    </Icon>
  )
}

/** Making a project: a plus across the badge's square, its lines running on along the folder's right and bottom
 *  edges. */
export const FolderPlusIcon = (props: IconProps) => (
  <FolderBadgeIcon badge="M20.5 15.25v7.5M16.75 19h7.5" {...props} />
)

/** Taking a conversation out of its project: a cross corner to corner of the badge's square. */
export const FolderRemoveIcon = (props: IconProps) => (
  <FolderBadgeIcon
    badge="M16.75 15.25l7.5 7.5M24.25 15.25l-7.5 7.5"
    {...props}
  />
)

export const CodeIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="m8.5 7.5-4.5 4.5 4.5 4.5M15.5 7.5l4.5 4.5-4.5 4.5M13.5 5l-3 14" />
  </Icon>
)

/** Any other action: a wrench, as SF Symbols' wrench. A short open-end wrench on the diagonal: a round head (r 6)
    with a U-shaped jaw and rounded prong tips, eased into a short handle 4.3 wide with a round end. It spans 3.4 to
    20.6, centered. */
export const ToolIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M7.05 19.99L11.09 15.95A2.55 2.55 0 0 1 13.41 15.26A6 6 0 0 0 20.6 8.89A1.05 1.05 0 0 0 18.81 8.23L16.53 10.51A2.15 2.15 0 0 1 13.49 7.47L15.77 5.19A1.05 1.05 0 0 0 15.11 3.4A6 6 0 0 0 8.74 10.59A2.55 2.55 0 0 1 8.05 12.91L4.01 16.95A2.15 2.15 0 0 0 7.05 19.99Z" />
  </Icon>
)

// Status: for a step of work, among the line icons of its actions.

/** Held back: a circle struck through. */
export const NoSignIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.75" />
    <path d="m5.8 18.2 12.4-12.4" />
  </Icon>
)

export const CheckCircleIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.75" />
    <path d="m8.25 12.25 2.5 2.5 5-5" />
  </Icon>
)

/** Not started yet: a circle of eight dashes, as SF Symbols' circle.dashed, a dash at the top. At 16px, where the
    1.25 line's round caps add 0.94 to each end, a dash shows about twice as long as the gap after it. */
export const CircleDashedIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M10.63 3.36A8.75 8.75 0 0 1 13.37 3.36M17.14 4.92A8.75 8.75 0 0 1 19.08 6.86M20.64 10.63A8.75 8.75 0 0 1 20.64 13.37M19.08 17.14A8.75 8.75 0 0 1 17.14 19.08M13.37 20.64A8.75 8.75 0 0 1 10.63 20.64M6.86 19.08A8.75 8.75 0 0 1 4.92 17.14M3.36 13.37A8.75 8.75 0 0 1 3.36 10.63M4.92 6.86A8.75 8.75 0 0 1 6.86 4.92" />
  </Icon>
)

/** The plan: two lines, each after a hollow dot, as ChatGPT's button for its task card. The dots are 1.4 of their own
    width apart, and a line runs 1.3 times a dot, level with its middle. */
export const PlanIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="6.5" cy="6.9" r="2.75" />
    <circle cx="6.5" cy="17.1" r="2.75" />
    <path d="M13.25 6.9h7.75M13.25 17.1h7.75" />
  </Icon>
)

export const XCircleIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.75" />
    <path d="m9.25 9.25 5.5 5.5M14.75 9.25l-5.5 5.5" />
  </Icon>
)

export const PauseCircleIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="8.75" />
    <path d="M10 9v6M14 9v6" />
  </Icon>
)

// The app's mark

/**
 * The agent's pointer on a blue tile, as the favicon draws it (public/favicon.svg). It stands in for the @ of
 * @Computer, which sends a message to the desktop. Not an icon of the set: it is filled, and its outline scales.
 */
export const ComputerLogo = (props: IconProps) => (
  <svg viewBox="0 0 32 32" width={32} height={32} aria-hidden {...props}>
    <rect width="32" height="32" rx="8" fill="#2563eb" />
    <path
      d="M8.75 8.75 24.75 14.75 17.55 17.55 14.75 24.75Z"
      fill="#fff"
      stroke="#fff"
      strokeWidth={3}
      strokeLinejoin="round"
    />
  </svg>
)
