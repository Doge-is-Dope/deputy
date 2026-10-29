import * as React from "react"
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"
import { cn } from "cn"

import { Button } from "@/components/ui/button"
import { CloseIcon as XIcon } from "@/components/icons"
import { useT } from "@/lib/i18n"

function Dialog({ ...props }: DialogPrimitive.Root.Props) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

function DialogPortal({ ...props }: DialogPrimitive.Portal.Props) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />
}

function DialogOverlay({
  className,
  ...props
}: DialogPrimitive.Backdrop.Props) {
  return (
    <DialogPrimitive.Backdrop
      data-slot="dialog-overlay"
      className={cn(
        "fixed inset-0 isolate z-50 bg-black/10 duration-200 ease-(--ease-out) supports-backdrop-filter:backdrop-blur-xs data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:duration-150 data-closed:fade-out-0",
        className
      )}
      {...props}
    />
  )
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  ...props
}: DialogPrimitive.Popup.Props & {
  showCloseButton?: boolean
}) {
  const t = useT()
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Popup
        data-slot="dialog-content"
        className={cn(
          "fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-xl bg-popover p-4 text-sm text-popover-foreground ring-1 ring-foreground/10 duration-200 ease-(--ease-out) outline-none sm:max-w-sm data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 motion-reduce:data-open:zoom-in-100 data-closed:animate-out data-closed:duration-150 data-closed:fade-out-0 data-closed:zoom-out-95 motion-reduce:data-closed:zoom-out-100",
          className
        )}
        {...props}
      >
        {children}
        {/* Its middle 28px in from the top and the right, level with a title row of h-8 under p-3 (the settings') or pt-3
            (a dialog with a title and a list under it). */}
        {showCloseButton && (
          <DialogPrimitive.Close
            data-slot="dialog-close"
            render={
              <Button
                variant="ghost"
                className="absolute top-2.5 right-2.5"
                size="icon"
              />
            }
          >
            <XIcon />
            <span className="sr-only">{t.common.close}</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Popup>
    </DialogPortal>
  )
}

// At the type scale's 16/24, so a question that wraps keeps its lines apart.
function DialogTitle({ className, ...props }: DialogPrimitive.Title.Props) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn("font-heading text-base font-medium", className)}
      {...props}
    />
  )
}

/** Asks one thing: a title, what it needs under it, then Cancel and the one action at the right. Cancel closes it;
 * the action leaves closing to the caller, which may keep it open (a name still empty). */
function ActionDialog({
  open,
  onOpenChange,
  title,
  action,
  onAction,
  destructive = false,
  disabled = false,
  initialFocus,
  finalFocus,
  className,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: React.ReactNode
  action: string
  onAction: () => void
  destructive?: boolean
  disabled?: boolean // the action, until what it needs is given
  initialFocus?: DialogPrimitive.Popup.Props["initialFocus"]
  finalFocus?: DialogPrimitive.Popup.Props["finalFocus"]
  className?: string
  children?: React.ReactNode
}) {
  const t = useT()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        initialFocus={initialFocus}
        finalFocus={finalFocus}
        className={className}
      >
        <DialogTitle>{title}</DialogTitle>
        {children}
        <div className="flex flex-row justify-end gap-2">
          <DialogPrimitive.Close render={<Button variant="ghost" />}>
            {t.common.cancel}
          </DialogPrimitive.Close>
          <Button
            variant={destructive ? "destructive" : "default"}
            disabled={disabled}
            onClick={onAction}
          >
            {action}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export {
  ActionDialog,
  Dialog,
  DialogContent,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
}
