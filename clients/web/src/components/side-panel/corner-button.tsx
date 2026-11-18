import type { ComponentProps, ReactNode } from "react"
import { cn } from "cn"

import { CloseIcon, ExpandIcon } from "@/components/icons"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

/**
 * The panel's own button, at its top right: to expand or shrink it (`pressed`), else to close it. Beside the page's
 * toggle for the panel, which keeps the window's corner (App.tsx); in the corner itself where that is out of sight (a
 * phone's sheet, full screen).
 */
export function CornerButton({
  label,
  pressed,
  beside,
  hint,
  ...props
}: Omit<ComponentProps<typeof Button>, "children" | "className"> & {
  label: string
  pressed?: boolean // undefined: it closes
  beside: boolean
  hint?: ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label={label}
            aria-pressed={pressed}
            className={cn(
              "touch-target absolute top-1.5 z-10 transition-[background-color] duration-200 ease-(--ease-out) md:top-2",
              // Where it ends while the panel slides in (index.css's --slide), so it never passes over the toggle.
              "translate-x-[calc(var(--slide)*-100cqw)]",
              "[visibility:var(--panel-corner-visibility,visible)]",
              beside ? "right-12.5 md:right-12" : "right-2.5 md:right-2"
            )}
            {...props}
          />
        }
      >
        {pressed === undefined ? (
          <CloseIcon className="size-5" />
        ) : (
          <ExpandIcon inward={pressed} className="size-5" />
        )}
      </TooltipTrigger>
      <TooltipContent side="bottom" align="end">
        {label}
        {hint}
      </TooltipContent>
    </Tooltip>
  )
}
