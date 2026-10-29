import type { ReactNode } from "react"
import { toast } from "sonner"

import { CloseIcon, WarningIcon } from "@/components/icons"
import { Button } from "@/components/ui/button"
import { useT } from "@/lib/i18n"

/** A notice at the top of the window, in a toast.custom: what happened, with its icon, and one action to follow it
    up when it has one. Equal-width surfaces keep the collapsed stack legible. */
export function Notice({
  icon,
  text,
  action,
  onAction,
  onDismiss,
}: {
  icon?: ReactNode
  text: string
  action?: string
  onAction?: () => void
  onDismiss: () => void
}) {
  const say = useT()
  return (
    <div
      data-notice
      className="flex w-full items-center rounded-full border bg-popover py-1.5 pr-1.5 pl-3 text-sm text-popover-foreground shadow-[0_4px_16px_rgb(0_0_0/0.08)]"
    >
      <div
        data-notice-content
        className="flex min-w-0 flex-1 items-center gap-2.5"
      >
        {icon}
        {/* One line, as a conversation's name is in the sidebar. */}
        <span className="min-w-0 flex-1 truncate">{text}</span>
        <div className="flex shrink-0 items-center gap-1.5">
          {action && (
            <Button
              size="sm"
              className="shrink-0 rounded-full px-3.5"
              onClick={onAction}
            >
              {action}
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon-sm"
            className="rounded-full text-muted-foreground hover:text-foreground"
            aria-label={say.common.close}
            onClick={onDismiss}
          >
            <CloseIcon aria-hidden className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}

/** Why what the user asked did not go through, as a notice with the others: one at a time, a new one in its place. */
export function showError(text: string) {
  toast.custom(
    (id) => (
      <Notice
        icon={
          <WarningIcon
            aria-hidden
            className="size-5 shrink-0 text-destructive"
          />
        }
        text={text}
        onDismiss={() => toast.dismiss(id)}
      />
    ),
    { id: "error", className: "w-full" }
  )
}
