import { useState, type ReactElement } from "react"
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"
import { PreviewCard } from "@base-ui/react/preview-card"
import { cn } from "cn"

import { Button } from "@/components/ui/button"
import { Dialog, DialogOverlay, DialogPortal } from "@/components/ui/dialog"
import { screenshotUrl } from "@/lib/api"
import type { Shot } from "@/lib/thread"
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
} from "@/components/icons"
import { useT } from "@/lib/i18n"

// How long the pointer rests on a thumbnail before it shows, in milliseconds.
const PEEK_DELAY = 400

// The round buttons over the dark backdrop, light in both themes, as Claude's image viewer sets its close button.
const ROUND =
  "rounded-full bg-white/10 text-white hover:bg-white/20 hover:text-white dark:hover:bg-white/20 disabled:opacity-30"

/**
 * A screen's thumbnail that shows the screen larger above it while the pointer rests on it, as Claude's attachments
 * do; `children` is the thumbnail's button, which opens the screen full size.
 */
export function ScreenshotPeek({
  run,
  name,
  children,
}: {
  run: string
  name: string
  children: ReactElement
}) {
  // Closed by the click, which opens the viewer over it. Opened by the pointer only: the focus the viewer gives back as
  // it closes does not bring it up again.
  const [open, setOpen] = useState(false)
  return (
    <PreviewCard.Root
      open={open}
      onOpenChange={(next, { reason }) => {
        if (!next || reason === "trigger-hover") setOpen(next)
      }}
    >
      <PreviewCard.Trigger
        render={children}
        delay={PEEK_DELAY}
        onClick={() => setOpen(false)}
      />
      <PreviewCard.Portal>
        <PreviewCard.Positioner
          side="top"
          align="end"
          sideOffset={8}
          className="isolate z-50"
        >
          <PreviewCard.Popup className="origin-(--transform-origin) overflow-hidden rounded-xl bg-muted shadow-lg ring-1 ring-foreground/10 duration-150 ease-(--ease-out) data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 motion-reduce:data-open:zoom-in-100 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95 motion-reduce:data-closed:zoom-out-100">
            {/* The full screenshot, not a smaller copy: one image on demand, so the viewer opens on it already loaded. */}
            <img
              src={screenshotUrl(run, name)}
              alt=""
              width={320}
              height={200}
              decoding="async"
              className="block aspect-[16/10] w-80 object-cover"
            />
          </PreviewCard.Popup>
        </PreviewCard.Positioner>
      </PreviewCard.Portal>
    </PreviewCard.Root>
  )
}

/**
 * A run's screenshots full screen over the page, one at a time, as Claude shows an image: the arrow keys step through
 * them, Escape or a click beside the screen closes it.
 */
export function ScreenshotViewer({
  run,
  shots,
  index,
  onIndexChange,
}: {
  run: string
  shots: Shot[]
  index: number | null
  onIndexChange: (index: number | null) => void
}) {
  const t = useT()
  // The screen last shown, kept while the viewer fades out.
  const [shown, setShown] = useState(index)
  if (index !== null && index !== shown) setShown(index)
  const shot = shown === null ? null : shots[shown]
  const go = (step: number) => {
    if (index === null) return
    const next = index + step
    if (next >= 0 && next < shots.length) onIndexChange(next)
  }
  const many = shots.length > 1

  return (
    <Dialog
      open={index !== null}
      onOpenChange={(open) => !open && onIndexChange(null)}
    >
      <DialogPortal>
        <DialogOverlay className="bg-black/80 supports-backdrop-filter:backdrop-blur-none" />
        <DialogPrimitive.Popup
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") go(-1)
            if (event.key === "ArrowRight") go(1)
          }}
          onClick={(event) => {
            if (event.target === event.currentTarget) onIndexChange(null)
          }}
          className="fixed inset-0 z-50 grid place-items-center duration-200 ease-(--ease-out) outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 motion-reduce:data-open:zoom-in-100 data-closed:animate-out data-closed:duration-150 data-closed:fade-out-0 data-closed:zoom-out-95 motion-reduce:data-closed:zoom-out-100"
        >
          {shot && shown !== null && (
            <>
              <img
                src={screenshotUrl(run, shot.name)}
                alt={shot.label}
                className="max-h-[calc(100dvh-7rem)] max-w-[calc(100vw-2rem)] rounded-lg bg-muted shadow-2xl sm:max-w-[calc(100vw-9rem)]"
              />
              <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center gap-2 px-4 pb-4 text-sm text-white">
                <DialogPrimitive.Title className="min-w-0 truncate">
                  {shot.label}
                </DialogPrimitive.Title>
                {many && (
                  <DialogPrimitive.Description className="text-white/60 tabular-nums">
                    {shown + 1} / {shots.length}
                  </DialogPrimitive.Description>
                )}
              </div>
              {many && (
                <>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t.screenshots.previous}
                    disabled={shown === 0}
                    onClick={() => go(-1)}
                    className={cn(ROUND, "absolute top-1/2 left-4 -mt-4.5")}
                  >
                    <ChevronLeftIcon />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t.screenshots.next}
                    disabled={shown === shots.length - 1}
                    onClick={() => go(1)}
                    className={cn(ROUND, "absolute top-1/2 right-4 -mt-4.5")}
                  >
                    <ChevronRightIcon />
                  </Button>
                </>
              )}
              <DialogPrimitive.Close
                render={
                  <Button
                    variant="ghost"
                    size="icon"
                    className={cn(ROUND, "absolute top-4 right-4")}
                  />
                }
              >
                <CloseIcon />
                <span className="sr-only">{t.common.close}</span>
              </DialogPrimitive.Close>
            </>
          )}
        </DialogPrimitive.Popup>
      </DialogPortal>
    </Dialog>
  )
}
