import { useState, type KeyboardEvent } from "react"
import { cn } from "cn"

import { Button } from "@/components/ui/button"
import { Kbd } from "@/components/ui/kbd"
import { useT } from "@/lib/i18n"
import { ENTER_KEYCAP } from "@/lib/keys"
import type { QuestionOption } from "@/lib/thread"
import { CheckIcon, QuestionIcon } from "@/components/icons"

const ROW =
  "w-full rounded-[1.25rem] px-3.5 py-2 text-left text-sm leading-6 transition-[background-color,scale] duration-150 ease-(--ease-out) outline-none active:scale-[0.985] motion-reduce:active:scale-100 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset disabled:opacity-50 motion-reduce:transition-none"

/** Options come in one after another, a beat apart. */
const stagger = (index: number) => ({ transitionDelay: `${index * 40}ms` })

/** Up and down go through the options; past the last, or Esc, back to the composer. */
function moveAmongOptions(event: KeyboardEvent<HTMLDivElement>) {
  const step = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0
  if (step === 0 && event.key !== "Escape") return
  event.preventDefault()
  const options = [...event.currentTarget.querySelectorAll("button")]
  const next = step && options[options.indexOf(event.target as never) + step]
  if (next) next.focus()
  else if (step >= 0) document.getElementById("goal")?.focus()
}

/** What the main agent asked the user: choosing an option sends it as their next message; the composer answers too. */
export function QuestionCard({
  question,
  options,
  multiple,
  answered,
  answer,
  onReply,
}: {
  question: string
  options: QuestionOption[]
  multiple: boolean // several may be chosen, then sent together
  answered: boolean
  answer: string | null // what the user answered, once known
  onReply: (text: string) => Promise<boolean> // true once it is sent
}) {
  const t = useT()
  const [sending, setSending] = useState(false)
  const [checked, setChecked] = useState<ReadonlySet<number>>(new Set())
  const toggle = (index: number) =>
    setChecked((was) => {
      const now = new Set(was)
      if (!now.delete(index)) now.add(index)
      return now
    })
  if (answered)
    return (
      <div className="flex arrive gap-2 text-sm leading-6">
        <QuestionIcon className="mt-1 size-4 shrink-0 text-muted-foreground/70" />
        <div className="min-w-0 wrap-break-word">
          <p className="text-muted-foreground">{question}</p>
          {answer && <p className="whitespace-pre-wrap">{answer}</p>}
        </div>
      </div>
    )
  const reply = async (text: string) => {
    setSending(true)
    if (!(await onReply(text))) setSending(false)
  }
  const send = () =>
    void reply(
      t.run.question.list(
        options
          .filter((_, index) => checked.has(index))
          .map((option) => option.label)
      )
    )
  return (
    <section
      aria-label={question}
      className="w-full max-w-md arrive rounded-[1.75rem] border bg-background dark:bg-[color-mix(in_oklch,var(--muted)_40%,var(--background))]"
    >
      <p className="px-4 pt-3.5 pb-1 text-sm leading-6 text-pretty wrap-break-word">
        {question}
      </p>
      {multiple ? (
        <>
          <div className="space-y-1 p-2" onKeyDown={moveAmongOptions}>
            {options.map((option, index) => (
              <div key={index} className="arrive-line" style={stagger(index)}>
                <button
                  type="button"
                  role="checkbox"
                  aria-checked={checked.has(index)}
                  data-question-option
                  disabled={sending}
                  onClick={() => toggle(index)}
                  onKeyDown={(event) => {
                    // A click leaves the focus here: Enter still sends what is chosen.
                    if (event.key !== "Enter" || checked.size === 0) return
                    event.preventDefault()
                    send()
                  }}
                  className={cn(
                    ROW,
                    "flex items-center gap-3 hover:bg-accent",
                    checked.has(index) && "bg-accent"
                  )}
                >
                  <span className="relative flex size-5 shrink-0 items-center justify-center rounded-full border border-foreground">
                    {/* The fill spreads from the middle; the check changes as the plan's status icons do. */}
                    <span
                      className={cn(
                        "absolute -inset-px rounded-full bg-primary transition-[opacity,scale] ease-(--ease-out) motion-reduce:transition-none",
                        checked.has(index)
                          ? "scale-100 opacity-100 duration-200"
                          : "scale-50 opacity-0 duration-100"
                      )}
                    />
                    <span className="swap text-primary-foreground">
                      <CheckIcon
                        className="size-3.5"
                        data-hidden={checked.has(index) ? undefined : ""}
                      />
                    </span>
                  </span>
                  <span className="min-w-0">
                    <span className="block wrap-break-word">
                      {option.label}
                    </span>
                    {option.reason && (
                      <span className="block text-xs leading-4 wrap-break-word text-muted-foreground/70">
                        {option.reason}
                      </span>
                    )}
                  </span>
                </button>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between gap-2 pr-3 pb-3 pl-4">
            <span className="text-xs text-muted-foreground">
              {checked.size > 0
                ? t.run.question.picked(checked.size)
                : t.run.question.pickMany}
            </span>
            <Button
              data-question-send
              size="sm"
              className="rounded-full font-normal"
              disabled={sending || checked.size === 0}
              onClick={send}
            >
              {t.composer.send}
              <Kbd className="bg-primary-foreground/15 text-primary-foreground/80 pointer-coarse:hidden">
                {ENTER_KEYCAP}
              </Kbd>
            </Button>
          </div>
        </>
      ) : options.length > 0 ? (
        <div className="space-y-1 p-2" onKeyDown={moveAmongOptions}>
          {options.map((option, index) => (
            <div key={index} className="arrive-line" style={stagger(index)}>
              <button
                type="button"
                data-question-option
                disabled={sending}
                onClick={() => void reply(option.label)}
                className={cn(
                  ROW,
                  "block",
                  index === 0
                    ? "bg-primary text-primary-foreground hover:bg-primary/85 focus-visible:ring-primary-foreground/60"
                    : "hover:bg-accent"
                )}
              >
                <span className="flex items-center gap-2">
                  <span className="min-w-0 wrap-break-word">
                    {option.label}
                  </span>
                  {index === 0 && (
                    <span className="shrink-0 rounded-md bg-primary-foreground/15 px-1.5 text-xs leading-5 text-primary-foreground/80">
                      {t.run.question.recommended}
                    </span>
                  )}
                </span>
                {option.reason && (
                  <span
                    className={cn(
                      "mt-0.5 block text-xs leading-4 wrap-break-word",
                      index === 0
                        ? "text-primary-foreground/60"
                        : "text-muted-foreground/70"
                    )}
                  >
                    {option.reason}
                  </span>
                )}
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="px-4 pb-3.5 text-sm leading-6 text-muted-foreground">
          {t.run.question.typeBelow}
        </p>
      )}
    </section>
  )
}
