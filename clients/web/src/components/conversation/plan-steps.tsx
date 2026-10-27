import { useEffect, useRef, useState } from "react"
import { cn } from "cn"

import { type Plan, type PlanStep } from "@/lib/thread"
import {
  CircleDashedIcon,
  CheckCircleIcon,
  SpinnerIcon,
} from "@/components/icons"

type PlanRow = { key: string; step: PlanStep; gone: boolean }

/** Each step by its words, and which time they come in the list, so two alike are two rows. */
function planRows(steps: PlanStep[]): PlanRow[] {
  const seen = new Map<string, number>()
  return steps.map((step) => {
    const count = seen.get(step.content) ?? 0
    seen.set(step.content, count + 1)
    return { key: `${step.content}#${count}`, step, gone: false }
  })
}

/** The plan's rows, with each step the main agent dropped kept where it was for as long as it takes to fold away. */
function usePlanRows(steps: PlanStep[]): PlanRow[] {
  const [rows, setRows] = useState(() => planRows(steps))
  const [was, setWas] = useState(steps)
  if (was !== steps) {
    const next = planRows(steps)
    const kept = new Set(next.map((row) => row.key))
    rows.forEach((row, index) => {
      if (kept.has(row.key)) return
      const before = rows[index - 1]
      const at = before ? next.findIndex((r) => r.key === before.key) + 1 : 0
      next.splice(at, 0, { ...row, gone: true })
    })
    setWas(steps)
    setRows(next)
  }
  useEffect(() => {
    if (!rows.some((row) => row.gone)) return
    const timer = window.setTimeout(
      () => setRows((now) => now.filter((row) => !row.gone)),
      300
    )
    return () => window.clearTimeout(timer)
  }, [rows])
  return rows
}

/** Animate plan row changes. Unfinished steps return to pending when the run ends. */
export function PlanSteps({ plan, active }: { plan: Plan; active: boolean }) {
  const rows = usePlanRows(plan.steps)
  // Rows that come after the list is drawn grow into place (in-data-ready:starting); those it came with arrive with it.
  const list = useRef<HTMLOListElement>(null)
  useEffect(() => list.current?.setAttribute("data-ready", ""), [])
  return (
    <ol ref={list}>
      {rows.map(({ key, step, gone }) => {
        const status =
          step.status === "completed"
            ? "completed"
            : active
              ? step.status
              : "pending"
        return (
          <li
            key={key}
            inert={gone}
            data-gone={gone || undefined}
            className="grid grid-rows-[1fr] transition-[grid-template-rows,opacity,filter] duration-300 ease-(--ease-out) data-gone:grid-rows-[0fr] data-gone:opacity-0 data-gone:blur-[2px] motion-reduce:transition-none in-data-ready:starting:grid-rows-[0fr] in-data-ready:starting:opacity-0 in-data-ready:starting:blur-[2px]"
          >
            <div className="min-h-0 overflow-hidden">
              <div className="flex gap-2.5 py-1 text-sm leading-6">
                <span className="swap mt-1 size-4 shrink-0">
                  <CircleDashedIcon
                    className="size-4 text-muted-foreground"
                    data-hidden={status === "pending" ? undefined : ""}
                  />
                  <SpinnerIcon
                    className="size-4"
                    still={!active}
                    data-hidden={status === "in_progress" ? undefined : ""}
                  />
                  <CheckCircleIcon
                    className="size-4 text-muted-foreground"
                    data-hidden={status === "completed" ? undefined : ""}
                  />
                </span>
                <span
                  className={cn(
                    "min-w-0 wrap-break-word line-through decoration-transparent transition-[color,text-decoration-color] duration-250 ease-(--ease-out) motion-reduce:transition-none",
                    status === "in_progress"
                      ? "text-foreground"
                      : "text-muted-foreground",
                    status === "completed" && "decoration-muted-foreground/70"
                  )}
                >
                  {step.content}
                </span>
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
