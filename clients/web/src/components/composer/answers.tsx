import {
  useEffect,
  useEffectEvent,
  type ComponentProps,
  type ReactNode,
  type RefObject,
} from "react"
import { cn } from "cn"

import { Button } from "@/components/ui/button"
import { Kbd } from "@/components/ui/kbd"
import { isComposing } from "@/lib/keys"

/**
 * Enter and Esc answer what the composer asks while the focus is in its text or on nothing, so it can stay where it is
 * as the question comes. Anything else with the focus keeps its keys: Enter on 「拒絕」 declines, on a link opens it,
 * and in the live view types on the desktop. So do the @ list, the composer's Enter that sends what is written, and
 * Chinese input.
 */
export function useAnswerKeys(
  keys: Partial<Record<"Enter" | "Escape", () => void>> | null,
  text: RefObject<HTMLTextAreaElement | null>
) {
  const onKeyDown = useEffectEvent((event: globalThis.KeyboardEvent) => {
    if (event.defaultPrevented || isComposing(event)) return
    if (event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return
    if (event.target !== document.body && event.target !== text.current) return
    const answer = keys?.[event.key as "Enter" | "Escape"]
    if (!answer) return
    event.preventDefault()
    answer()
  })
  const on = keys !== null
  useEffect(() => {
    if (!on) return
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [on])
}

/** One answer to what is asked: its words, and what it does. */
export type AnswerChoice = {
  label: ReactNode
  onClick: () => void
  disabled?: boolean
}

/** A question's two answers; `byEnter` false when Enter does something else meanwhile (sends what is written). */
export type Ask = {
  key: string
  decline: AnswerChoice
  accept: AnswerChoice & { byEnter?: boolean }
}

/** A question's answers side by side, declining (Esc) before accepting (⏎), as the composer and the live view ask. */
export function AnswerPair({
  decline,
  accept,
  className,
}: {
  decline: AnswerChoice
  accept: AnswerChoice
  className?: string
}) {
  return (
    <div className={cn("flex gap-1.5", className)}>
      <Answer
        shortcut="Esc"
        disabled={decline.disabled}
        onClick={decline.onClick}
      >
        {decline.label}
      </Answer>
      <Answer
        primary
        shortcut="⏎"
        disabled={accept.disabled}
        onClick={accept.onClick}
      >
        {accept.label}
      </Answer>
    </div>
  )
}

/** An answer in the composer's corner, the size of its send button, with the key that gives it on a keyboard if any. */
function Answer({
  primary = false,
  shortcut,
  children,
  ...props
}: ComponentProps<typeof Button> & { primary?: boolean; shortcut?: string }) {
  return (
    <Button
      type="button"
      variant={primary ? "default" : "ghost"}
      size="lg"
      className="rounded-full font-normal"
      {...props}
    >
      {children}
      {shortcut && (
        <Kbd
          className={cn(
            "pointer-coarse:hidden",
            primary
              ? "bg-primary-foreground/15 text-primary-foreground/80"
              : "bg-foreground/[0.06]"
          )}
        >
          {shortcut}
        </Kbd>
      )}
    </Button>
  )
}
