import { cn } from "cn"

import { MonitorIcon, TerminalIcon } from "@/components/icons"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useCopy } from "@/hooks/use-copy"
import { type Status } from "@/lib/api"
import { connectionOf } from "@/lib/format"
import { useT } from "@/lib/i18n"
import { Card, Section } from "@/components/settings/layout"

/** Show desktop and code-runner connection status, with copyable failure details. */
export function Desktop({
  status,
  offline,
}: {
  status: Status | null
  offline: boolean
}) {
  const t = useT()
  const desktop = connectionOf(status, offline)
  const runner = status?.code_runner && !offline ? status.code_runner : null
  const state = (connected: boolean) =>
    connected ? t.settings.connected : t.settings.disconnected
  return (
    <Section>
      <Card>
        <Connection
          icon={MonitorIcon}
          name={t.settings.windowsDesktop}
          // While the runtime itself can't be reached, the row says that instead.
          state={
            desktop && {
              ...desktop,
              label: offline ? desktop.label : state(desktop.connected),
            }
          }
        />
        {runner && (
          <Connection
            icon={TerminalIcon}
            name={t.settings.codeRunner}
            state={{ ...runner, label: state(runner.connected) }}
          />
        )}
      </Card>
    </Section>
  )
}

function Connection({
  icon: Icon,
  name,
  state,
}: {
  icon: typeof MonitorIcon
  name: string
  state: { connected: boolean; label: string; detail: string } | null
}) {
  const t = useT()
  const problem = state && !state.connected ? state.detail : ""
  return (
    <div className="py-3">
      {/* On a narrow screen the state goes under the name, whole, as a row's value does. */}
      <div className="flex min-h-8 flex-wrap items-center justify-between gap-x-6 gap-y-1">
        <span className="flex items-center gap-2.5 whitespace-nowrap">
          <Icon className="size-4 shrink-0 text-muted-foreground" />
          {name}
        </span>
        <span className="ml-auto inline-flex items-center gap-2 whitespace-nowrap">
          <span
            aria-hidden
            className={cn(
              "size-2 shrink-0 rounded-full",
              !state
                ? "bg-muted-foreground"
                : state.connected
                  ? "bg-success"
                  : "bg-destructive"
            )}
          />
          {state?.label ?? t.settings.connecting}
        </span>
      </div>
      {problem && (
        <div className="ml-6.5">
          <Problem text={problem} />
        </div>
      )}
    </div>
  )
}

/** Copy connection details while keeping the tooltip open to confirm the copy. */
function Problem({ text }: { text: string }) {
  const t = useT()
  const { copied, copy } = useCopy()
  const label = copied ? t.common.copied : t.common.copy
  return (
    <Tooltip>
      <TooltipTrigger
        closeOnClick={false}
        render={
          <button
            type="button"
            className="mt-1 block max-w-full rounded-sm text-left font-mono text-xs leading-5 break-words text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
            onClick={() => copy(text)}
          />
        }
      >
        {text}
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
}
