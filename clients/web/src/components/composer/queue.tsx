import { useState } from "react"
import { cn } from "cn"

import { ClockIcon, TrashIcon } from "@/components/icons"
import { Button } from "@/components/ui/button"
import { type Pending } from "@/lib/api"
import { useT } from "@/lib/i18n"

/**
 * What was sent while the run works and its agents have not read yet, on a card tucked behind the composer's top edge:
 * read, a message leaves it for the conversation; deleted before that, the agents never see it. It sinks behind the
 * composer while the composer asks something, as the question rises out of it, and comes back once that is answered.
 */
export function Queue({
  messages,
  hidden,
  onWithdraw,
}: {
  messages: Pending[]
  hidden: boolean // the composer asks something, which is all it shows
  onWithdraw?: (message: Pending) => void
}) {
  const t = useT()
  // Kept while the card folds away, so it does not go blank as it closes.
  const [kept, setKept] = useState(messages)
  if (messages.length > 0 && messages !== kept) setKept(messages)
  const shut = hidden || messages.length === 0
  return (
    // Its room opens and folds as the question row's does, on the same curve, so as one comes the other goes and the
    // conversation above hardly moves. The card's foot reaches under the composer (-mb-6 here, pb-6 on the card), and
    // only there does it clip, so the card sinks into the composer and shows nowhere else.
    <div
      inert={shut}
      className={cn(
        "grid transition-[grid-template-rows] duration-300 ease-(--ease-drawer) motion-reduce:transition-none",
        shut ? "grid-rows-[0fr]" : "grid-rows-[1fr]"
      )}
    >
      <div className="-mb-6 min-h-0 overflow-hidden">
        {/* What leaves goes first: sinking, its words fade in half the time; rising, it waits for the question's
          words to fade. Transform and opacity only. Every icon sits 12px from the card's top, from the composer
          and from the icon beside it (28px rows, 6px more at either end), its mark 12px from the sides. */}
        <ul
          className={cn(
            "mx-3.5 rounded-t-[1.25rem] glass pt-1.5 pb-7.5 transition-[translate,opacity] ease-(--ease-drawer) motion-reduce:translate-y-0 motion-reduce:delay-0 motion-reduce:[transition-duration:150ms]",
            shut
              ? "translate-y-full opacity-0 [transition-duration:300ms,150ms]"
              : "[transition-delay:100ms] [transition-duration:300ms,250ms]"
          )}
        >
          {kept.map((message) => (
            <li
              key={message.id}
              className="flex h-7 items-center gap-2.5 pr-1.5 pl-2.5 text-sm"
            >
              <ClockIcon className="size-4 shrink-0 text-muted-foreground" />
              {/* One line each, as a conversation's name is in the sidebar. */}
              <span className="min-w-0 flex-1 truncate">{message.text}</span>
              {onWithdraw && (
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="size-6 rounded-full text-muted-foreground hover:text-foreground"
                  aria-label={t.composer.withdraw}
                  onClick={() => onWithdraw(message)}
                >
                  <TrashIcon aria-hidden className="size-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
