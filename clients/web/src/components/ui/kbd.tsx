import * as React from "react"
import { cn } from "cn"

/** `row`: in a sidebar or menu row, 24 tall and 4 from the row's edges, so its corners are concentric with the row's; the
 * negative margin keeps a row with padding at its own height. */
function Kbd({
  className,
  row = false,
  ...props
}: React.ComponentProps<"kbd"> & { row?: boolean }) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        "pointer-events-none inline-flex h-5 w-fit min-w-5 items-center justify-center gap-1 rounded-xs bg-muted px-1 font-sans text-xs font-medium text-muted-foreground select-none",
        "in-data-[slot=tooltip-content]:bg-background/20 in-data-[slot=tooltip-content]:text-background dark:in-data-[slot=tooltip-content]:bg-muted dark:in-data-[slot=tooltip-content]:text-muted-foreground",
        row && "-my-0.5 h-6 min-w-6 px-1.5",
        className
      )}
      {...props}
    />
  )
}

export { Kbd }
