import { cn } from "cn"

import { CursorEnterIcon, HandIcon } from "@/components/icons"
import { ScreenshotPeek } from "@/components/screenshot-viewer"
import { screenshotUrl } from "@/lib/api"
import { useT } from "@/lib/i18n"

/** What was asked last, kept while its row folds away so it does not go blank as it closes. */
export type Asked = {
  handover: boolean
  question: string | null
  shot: { run: string; name: string } | null // the screen the step was decided from
}

/** The row over the composer's text that says what it asks, with the screen a step was decided from. */
export function QuestionRow({
  question,
  asked,
  moving,
  onMoved,
  onView,
}: {
  question: string | null // what is asked now; null while nothing is, and the row is shut
  asked: Asked
  moving: boolean // the row is opening or closing
  onMoved: () => void
  onView: () => void // enlarge the screen
}) {
  const t = useT()
  // It opens from nothing (grid rows 0fr to 1fr) and folds back, what it says fading in and out with it. The composer
  // grows upward, and the conversation, following its end, moves up with it. Not a tray floating over the
  // conversation: one composer, the question part of it.
  return (
    <div
      inert={!question}
      data-moving={moving || undefined}
      onTransitionEnd={(event) => {
        if (event.target === event.currentTarget) onMoved()
      }}
      className={cn(
        "grid transition-[grid-template-rows] duration-300 ease-(--ease-drawer) motion-reduce:transition-none",
        question ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
      )}
    >
      {/* Held at the bottom, by the text, so the rising top edge uncovers it rather than cutting through it. */}
      <div className="flex min-h-0 flex-col justify-end overflow-hidden">
        <div
          className={cn(
            "flex shrink-0 items-center gap-2.5 px-4 pt-3.5 transition-[opacity,translate] duration-300 ease-(--ease-drawer) motion-reduce:transition-none",
            !question && "translate-y-2 opacity-0"
          )}
        >
          {/* The agent's pointer coming into the screen, as the return-control button shows it; or a hand held up, as
            the conversation shows a step waiting. */}
          {asked.handover ? (
            <CursorEnterIcon className="size-5 shrink-0 text-takeover" />
          ) : (
            <HandIcon className="size-5 shrink-0 text-warning" />
          )}
          <p className="min-w-0 text-sm text-pretty">{asked.question}</p>
          {asked.shot && (
            <ScreenshotPeek run={asked.shot.run} name={asked.shot.name}>
              <button
                type="button"
                onClick={() => onView()}
                aria-label={t.run.enlarge(asked.question ?? "")}
                className="ml-auto shrink-0 cursor-zoom-in rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <img
                  src={screenshotUrl(asked.shot.run, asked.shot.name, 192)}
                  alt=""
                  width={96}
                  height={60}
                  className="aspect-[16/10] w-24 rounded-lg border bg-muted object-cover transition-opacity hover:opacity-85 max-sm:w-18"
                />
              </button>
            </ScreenshotPeek>
          )}
        </div>
      </div>
    </div>
  )
}
