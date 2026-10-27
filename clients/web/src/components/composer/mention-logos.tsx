import { Fragment, type RefObject } from "react"
import { cn } from "cn"

import { ComputerLogo } from "@/components/icons"
import { MARK } from "@/components/composer/mention-text"

// The text's box and type, which the layer that draws the logos over it has to share line for line. Both keep room
// for a scrollbar, which takes room on some systems, so that their lines break alike when the text scrolls.
export const TEXT =
  "block max-h-52 min-h-10 px-1 py-2 font-composer text-base leading-6 whitespace-pre-wrap [scrollbar-gutter:stable] md:text-sm"

/** The layer over the text that draws each mention's logo over its MARK: the same text, unseen, scrolled with the
 * text box (useMentionText). */
export function MentionLogos({
  ref,
  shown,
  logos,
}: {
  ref: RefObject<HTMLDivElement | null>
  shown: string // the text as the text box holds it
  logos: number[] // where each MARK with a logo over it is
}) {
  return (
    <div
      ref={ref}
      aria-hidden
      className={cn(
        TEXT,
        "pointer-events-none absolute inset-0 overflow-hidden text-transparent"
      )}
    >
      {logos.map((start, index) => (
        <Fragment key={start}>
          {shown.slice(index ? logos[index - 1] + 1 : 0, start)}
          {/* The text's size, 1px into the MARK, where it leaves the caret before it in view, and level with
          the middle of a capital letter (Geist's are 0.71em). The MARK's 1.25em leave a quarter em, less 1px,
          after it. */}
          <span className="relative">
            {MARK}
            <ComputerLogo className="absolute top-[0.145em] left-px size-[1em]" />
          </span>
        </Fragment>
      ))}
      {shown.slice(logos[logos.length - 1] + 1)}
      {/* A line break at the end starts a line in the textarea, which the layer needs as well. */}
      &#8203;
    </div>
  )
}
