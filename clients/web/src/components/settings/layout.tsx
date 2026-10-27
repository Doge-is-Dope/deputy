import { type ReactNode } from "react"

/** A page's settings under its title, in one card or more: the title names them, so no heading of their own. */
export function Section({ children }: { children: ReactNode }) {
  return <div className="mt-6 flex flex-col gap-4">{children}</div>
}

/** Settings that go together: one card, a row each. */
export function Card({ children }: { children: ReactNode }) {
  return (
    <div className="divide-y rounded-xl border bg-card px-5 dark:bg-card/40">
      {children}
    </div>
  )
}

/** A setting's name on the left, its value or control on the right; on a narrow screen a wide one goes under it. */
export function Row({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="flex min-h-14 flex-wrap items-center justify-between gap-x-6 gap-y-3 py-3">
      <div>{label}</div>
      <div className="ml-auto min-w-0 text-right break-words text-muted-foreground">
        {children}
      </div>
    </div>
  )
}
