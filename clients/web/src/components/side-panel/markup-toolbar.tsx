import type { ReactNode } from "react"
import { cn } from "cn"

import {
  ArrowUpRightIcon,
  CheckIcon,
  ChevronDownIcon,
  CircleIcon,
  CommentIcon,
  DownloadIcon,
  PenIcon,
  RedoIcon,
  ScribbleIcon,
  SquareIcon,
  UndoIcon,
} from "@/components/icons"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { Zoom } from "@/components/side-panel/pdf-pages"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useT } from "@/lib/i18n"
import { COLORS, type Color, type Shape, type Tool } from "@/lib/markup"

const SHAPES: Record<Shape, typeof SquareIcon> = {
  rect: SquareIcon,
  ellipse: CircleIcon,
  arrow: ArrowUpRightIcon,
}

/** A colour's dot, with a faint edge inside it so a light one still shows on the white bar. */
function Dot({ color, className }: { color: Color; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "size-4.5 shrink-0 rounded-full shadow-[inset_0_0_0_1px_rgb(0_0_0/0.1)]",
        className
      )}
      style={{ backgroundColor: COLORS[color] }}
    />
  )
}

/** A round 36 button with its name in a tooltip; the chosen tool in the pressed button's fill. */
function ToolButton({
  label,
  pressed,
  disabled,
  onClick,
  children,
  render,
}: {
  label: string
  pressed?: boolean
  disabled?: boolean
  onClick?: () => void
  children: ReactNode
  render?: (button: React.ReactElement) => React.ReactElement
}) {
  const button = (
    <Button
      variant={pressed ? "secondary" : "ghost"}
      size="icon"
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className="rounded-full"
    />
  )
  return (
    <Tooltip>
      <TooltipTrigger render={render ? render(button) : button}>
        {children}
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  )
}

/** A plain button with words in the bar: its words as far in from its edge as an icon button's icon (8), so words and
 * icons sit 20 apart all along the bar. */
export const TEXT_BUTTON = "rounded-full px-2"

const Divider = () => (
  <span aria-hidden className="mx-1 h-5 w-px shrink-0 bg-border" />
)

// The zoom's menu: shares of the printed size, then as wide as the panel.
const ZOOMS = [25, 50, 100, 150, 200]

/** The bar under an attachment, level with the composer's bottom: to mark a picture up, size a PDF and download either;
 * marking up, the tools, undo and redo, and, unless the top row has them, leaving or adding the copy. Its buttons sit
 * 4 in from its edge, so their icons are 13 from it all round. */
export function MarkupToolbar({
  editing,
  markable,
  download,
  onStart,
  tool,
  onTool,
  shape,
  color,
  onColor,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  ends,
  zoom,
}: {
  editing: boolean
  markable: boolean
  download: { href?: string; name: string }
  onStart: () => void
  tool: Tool
  onTool: (tool: Tool) => void
  shape: Shape
  color: Color
  onColor: (color: Color) => void
  canUndo: boolean
  canRedo: boolean
  onUndo: () => void
  onRedo: () => void
  ends: ReactNode // 取消 and the copy's button, here where the top row doesn't hold them
  zoom?: { value: Zoom; fit: number; onChange: (zoom: Zoom) => void } // a PDF's
}) {
  const t = useT()
  const Shaped = SHAPES[shape]
  return (
    <div
      role="toolbar"
      className="flex max-w-full animate-in items-center gap-1 rounded-full border bg-background p-1 shadow-[0_2px_8px_rgb(0_0_0/0.04)] duration-200 ease-(--ease-out) fade-in slide-in-from-bottom-1 motion-reduce:slide-in-from-bottom-0 dark:bg-[color-mix(in_oklch,var(--muted)_40%,var(--background))]"
    >
      {/* Fades in afresh as the bar turns from previewing to marking up and back. */}
      <div
        key={editing ? "tools" : "preview"}
        className="flex animate-in items-center gap-1 duration-200 ease-(--ease-out) fade-in"
      >
        {editing ? (
          <>
            <ToolButton
              label={t.markup.pen}
              pressed={tool === "pen"}
              onClick={() => onTool("pen")}
            >
              <PenIcon />
            </ToolButton>
            <DropdownMenu>
              <ToolButton
                label={t.markup.shape}
                pressed={tool in SHAPES}
                render={(button) => <DropdownMenuTrigger render={button} />}
              >
                <Shaped />
              </ToolButton>
              <DropdownMenuContent side="top" align="center" sideOffset={12}>
                {(Object.keys(SHAPES) as Shape[]).map((each) => {
                  const Icon = SHAPES[each]
                  return (
                    <DropdownMenuItem key={each} onClick={() => onTool(each)}>
                      <Icon />
                      {t.markup[each]}
                    </DropdownMenuItem>
                  )
                })}
              </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu>
              <ToolButton
                label={t.markup.color}
                render={(button) => <DropdownMenuTrigger render={button} />}
              >
                <Dot color={color} />
              </ToolButton>
              <DropdownMenuContent
                side="top"
                align="center"
                sideOffset={12}
                className="min-w-0"
              >
                {(Object.keys(COLORS) as Color[]).map((each) => (
                  <DropdownMenuItem key={each} onClick={() => onColor(each)}>
                    <Dot color={each} className="size-4" />
                    {t.markup.colors[each]}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            <ToolButton
              label={t.markup.comment}
              pressed={tool === "comment"}
              onClick={() => onTool("comment")}
            >
              <CommentIcon />
            </ToolButton>
            <Divider />
            <ToolButton
              label={t.markup.undo}
              disabled={!canUndo}
              onClick={onUndo}
            >
              <UndoIcon />
            </ToolButton>
            <ToolButton
              label={t.markup.redo}
              disabled={!canRedo}
              onClick={onRedo}
            >
              <RedoIcon />
            </ToolButton>
            {ends && (
              <>
                <Divider />
                {ends}
              </>
            )}
          </>
        ) : (
          <>
            {zoom && (
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={
                    <Button
                      variant="ghost"
                      aria-label={t.tabs.zoom}
                      className={cn(TEXT_BUTTON, "tabular-nums")}
                    />
                  }
                >
                  {zoom.value === "fit" ? zoom.fit : zoom.value}%
                  <ChevronDownIcon className="size-4 text-muted-foreground" />
                </DropdownMenuTrigger>
                <DropdownMenuContent side="top" align="start" sideOffset={8}>
                  {ZOOMS.map((each) => (
                    <DropdownMenuItem
                      key={each}
                      onClick={() => zoom.onChange(each)}
                      className="tabular-nums"
                    >
                      {each}%
                      {zoom.value === each && <CheckIcon className="ml-auto" />}
                    </DropdownMenuItem>
                  ))}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => zoom.onChange("fit")}>
                    {t.tabs.fit}
                    {zoom.value === "fit" && <CheckIcon className="ml-auto" />}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
            {markable && (
              <Button variant="ghost" className={TEXT_BUTTON} onClick={onStart}>
                <ScribbleIcon />
                {t.markup.start}
              </Button>
            )}
            <a
              href={download.href}
              download={download.name}
              className={cn(buttonVariants({ variant: "ghost" }), TEXT_BUTTON)}
            >
              <DownloadIcon />
              {t.tabs.download}
            </a>
          </>
        )}
      </div>
    </div>
  )
}
