import { cn } from "cn"

import { ChevronDownIcon, ProviderIcon } from "@/components/icons"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { type Choice, type Status } from "@/lib/api"
import { chooseModel, resetModels, resolve, useChoices } from "@/lib/choices"
import { effortName, modelName } from "@/lib/format"
import { useT } from "@/lib/i18n"
import { Row } from "@/components/settings/layout"

// The agents whose models are chosen here, in this order: the main agent's are every other's default. One the runtime
// adds is shown after them, by its own name.
const AGENTS = ["main", "computer", "coding"]

/** Store model choices in this browser and send them per message (lib/choices.ts).
 * Subagents follow the main agent until overridden; Reset restores runtime defaults. */
export function Model({ status }: { status: Status | null }) {
  const t = useT()
  const { agents: chosen } = useChoices()
  const names: Record<string, string> = {
    main: t.settings.mainAgent,
    computer: t.settings.computerAgent,
    coding: t.settings.codingAgent,
  }
  const order = Object.keys(status?.defaults ?? {}).sort(
    (a, b) =>
      (AGENTS.indexOf(a) + 1 || AGENTS.length + 1) -
      (AGENTS.indexOf(b) + 1 || AGENTS.length + 1)
  )
  const efforts = (model: string) =>
    status?.models.find((each) => each.id === model)?.efforts ?? []
  const atDefaults =
    !status ||
    order.every((agent) => {
      const now = resolve(status, agent, chosen)
      const start = resolve(status, agent, {})
      return now.model === start.model && now.effort === start.effort
    })

  return (
    <>
      <div className="mt-6 divide-y">
        {status &&
          order.map((agent) => {
            const choice = resolve(status, agent, chosen)
            return (
              <div
                key={agent}
                className="flex min-h-16 flex-wrap items-center justify-between gap-x-6 gap-y-2 py-3"
              >
                <div>{names[agent] ?? agent}</div>
                <ModelPicker
                  label={names[agent] ?? agent}
                  choice={choice}
                  byDefault={resolve(status, agent, {})}
                  models={status.models.map((each) => each.id)}
                  efforts={efforts(choice.model)}
                  onChange={(change) => chooseModel(status, agent, change)}
                />
              </div>
            )
          })}
        {status?.title_model && (
          <Row label={t.settings.titleGeneration}>
            <span className="inline-flex items-center gap-2 text-sm">
              <ProviderIcon
                model={status.title_model.model}
                className="size-4"
              />
              {modelName(status.title_model.model)}
              <span className="text-muted-foreground">
                {effortName(status.title_model.effort)}
              </span>
            </span>
          </Row>
        )}
      </div>
      {/* Beside the dialog's close button, placed against the dialog rather than this page, so it stays there as the
          page scrolls. */}
      <Button
        variant="ghost"
        className="absolute top-2 right-12"
        disabled={atDefaults}
        onClick={resetModels}
      >
        {t.settings.resetModels}
      </Button>
    </>
  )
}

const PICKER =
  "flex h-9 items-center gap-2 rounded-lg border bg-background py-1.5 pr-2 pl-2.5 text-sm whitespace-nowrap outline-none select-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 data-popup-open:bg-muted"

/** Model and effort pickers, restricted to supported efforts and marking runtime defaults. */
function ModelPicker({
  label,
  choice,
  byDefault,
  models,
  efforts,
  onChange,
}: {
  label: string
  choice: Choice
  byDefault?: Choice // the settings' own, marked in the menu; an effort only with its model
  models: string[]
  efforts: string[]
  onChange: (change: Partial<Choice>) => void
}) {
  const t = useT()
  return (
    <div className="ml-auto flex items-center gap-2">
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label={`${label}: ${t.settings.model}`}
          className={PICKER}
        >
          <ProviderIcon model={choice.model} className="size-4" />
          {modelName(choice.model)}
          <ChevronDownIcon className="size-4 text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent className="min-w-48">
          <DropdownMenuRadioGroup
            value={choice.model}
            onValueChange={(model) => onChange({ model: model as string })}
          >
            {models.map((model) => (
              <DropdownMenuRadioItem
                key={model}
                value={model}
                className="gap-2"
              >
                <ProviderIcon model={model} className="size-4" />
                {/* One line of text, or the item's flex row would drop the space " (Default)" starts with. */}
                <span>
                  {modelName(model)}
                  {model === byDefault?.model && (
                    <span className="text-muted-foreground">
                      {t.settings.byDefault}
                    </span>
                  )}
                </span>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label={`${label}: ${t.settings.effort}`}
          className={cn(PICKER, "text-muted-foreground")}
        >
          {effortName(choice.effort)}
          <ChevronDownIcon className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent className="min-w-36">
          <DropdownMenuRadioGroup
            value={choice.effort}
            onValueChange={(effort) => onChange({ effort: effort as string })}
          >
            {efforts.map((effort) => (
              <DropdownMenuRadioItem key={effort} value={effort}>
                <span>
                  {effortName(effort)}
                  {choice.model === byDefault?.model &&
                    effort === byDefault.effort && (
                      <span className="text-muted-foreground">
                        {t.settings.byDefault}
                      </span>
                    )}
                </span>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
