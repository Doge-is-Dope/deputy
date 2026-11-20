import { type ReactNode } from "react"

/** A page's settings under its title, in one card or more; a group the title does not name has its own (Group). */
export function Section({ children }: { children: ReactNode }) {
  return <div className="mt-6 flex flex-col gap-4">{children}</div>
}

/** Settings under a heading of their own, where the page's title does not say what they are; its words start where a
 * card's do. An action for the whole group goes at its right, and a line under the heading says what is not seen. */
export function Group({
  title,
  action,
  note,
  children,
}: {
  title: ReactNode
  action?: ReactNode
  note?: string
  children: ReactNode
}) {
  // A transparent left border stands for the card's, so the words start on its words' column, not 1px before. Tall
  // enough for an action's button (36), with one or without, so every heading sits the same distance from its card.
  return (
    <section className="flex flex-col gap-2">
      <div className="flex min-h-9 items-center justify-between gap-4 border-l border-transparent pr-2 pl-5">
        <h3 className="font-medium">{title}</h3>
        {action}
      </div>
      {note && (
        <p className="-mt-1 border-l border-transparent px-5 text-xs text-muted-foreground">
          {note}
        </p>
      )}
      {children}
    </section>
  )
}

/** Settings that go together: one card, a row each. */
export function Card({ children }: { children: ReactNode }) {
  return (
    <div className="divide-y rounded-xl border bg-card px-5 dark:bg-card/40">
      {children}
    </div>
  )
}

/** A setting's name on the left, its value or control on the right; on a narrow screen a wide one goes under it. 56
 * tall, a 36 control's too (py-2.5), so a card's rows are one height whatever they hold. */
export function Row({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="flex min-h-14 flex-wrap items-center justify-between gap-x-6 gap-y-3 py-2.5">
      <div>{label}</div>
      <div className="ml-auto min-w-0 text-right break-words text-muted-foreground">
        {children}
      </div>
    </div>
  )
}
