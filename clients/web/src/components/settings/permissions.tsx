import { useId } from "react"
import { Radio } from "@base-ui/react/radio"
import { RadioGroup } from "@base-ui/react/radio-group"

import { api, type Approvals, type Status } from "@/lib/api"
import { setApprovals, useChoices } from "@/lib/choices"
import { useT } from "@/lib/i18n"
import { Card, Section } from "@/components/settings/layout"

const APPROVALS: Approvals[] = ["ask", "auto"]

/** Choose manual approval or auto review. Changes reach active web runs at their
 * next flagged step; CLI runs always ask. Persist choices through lib/choices.ts. */
export function Permissions({ status }: { status: Status | null }) {
  const t = useT()
  const id = useId()
  const { approvals } = useChoices()
  function choose(next: Approvals) {
    setApprovals(next)
    // A run that ended meanwhile, or one from the command line, turns it away: the next message brings it.
    for (const { run } of status?.running ?? [])
      api.setApprovals(run, next).catch(() => {})
  }

  return (
    <Section>
      <RadioGroup
        aria-label={t.settings.approvals}
        value={approvals}
        onValueChange={(next) => choose(next as Approvals)}
      >
        <Card>
          {APPROVALS.map((option) => {
            // Each named, then what it does in a muted line under it, as Claude's permission modes are.
            const mode = t.settings.approvalModes[option]
            return (
              <label
                key={option}
                className="flex min-h-14 cursor-pointer items-center gap-6 py-3 has-disabled:cursor-default"
              >
                <span className="flex-1">
                  <span id={`${id}-${option}`} className="block">
                    {mode.label}
                  </span>
                  <span
                    id={`${id}-${option}-description`}
                    className="mt-0.5 block text-xs text-muted-foreground"
                  >
                    {mode.description}
                  </span>
                </span>
                {/* Named by its row's words: the radio is not a native input, so the row's label does not name it.
                  Chosen, it fills as its dot grows in, and the one left empties as its dot shrinks away; with motion
                  reduced, the dot only fades. */}
                <Radio.Root
                  value={option}
                  aria-labelledby={`${id}-${option}`}
                  aria-describedby={`${id}-${option}-description`}
                  className="flex size-4 shrink-0 items-center justify-center rounded-full border border-input transition-[background-color,border-color] duration-150 ease-(--ease-out) outline-none focus-visible:ring-3 focus-visible:ring-ring/50 data-checked:border-primary data-checked:bg-primary data-disabled:opacity-50"
                >
                  <Radio.Indicator className="size-1.5 rounded-full bg-primary-foreground transition-[scale,opacity] duration-200 ease-(--ease-out) data-ending-style:scale-0 data-starting-style:scale-0 motion-reduce:data-ending-style:scale-100 motion-reduce:data-ending-style:opacity-0 motion-reduce:data-starting-style:scale-100 motion-reduce:data-starting-style:opacity-0" />
                </Radio.Root>
              </label>
            )
          })}
        </Card>
      </RadioGroup>
    </Section>
  )
}
