import { ProviderIcon } from "@/components/icons"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { type Choice, type Status } from "@/lib/api"
import { chooseModel, resetModels, resolve, useChoices } from "@/lib/choices"
import { agentName, effortName, modelName } from "@/lib/format"
import { useT } from "@/lib/i18n"
import { Card, Row, Section } from "@/components/settings/layout"

// The agents whose models are chosen here, in this order: the main agent's are every other's default. One the runtime
// adds is shown after them, by its own name.
const AGENTS = ["main", "computer", "coding"]

/** Store model choices in this browser and send them per message (lib/choices.ts).
 * Subagents follow the main agent until overridden; Reset restores runtime defaults. */
export function Model({ status }: { status: Status | null }) {
  const t = useT()
  const { agents: chosen } = useChoices()
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
      <Section>
        <Card>
          {status &&
            order.map((agent) => {
              const choice = resolve(status, agent, chosen)
              return (
                <Row key={agent} label={agentName(agent)}>
                  <ModelPicker
                    label={agentName(agent)}
                    choice={choice}
                    byDefault={resolve(status, agent, {})}
                    models={status.models}
                    efforts={efforts(choice.model)}
                    onChange={(change) => chooseModel(status, agent, change)}
                  />
                </Row>
              )
            })}
          {status?.title_model && (
            <Row label={t.settings.titleGeneration}>
              <span className="inline-flex items-center gap-2 text-sm">
                <ProviderIcon
                  model={status.title_model.model}
                  className="size-4"
                />
                {modelName(status.title_model.model, status.models)}
                <span className="text-muted-foreground">
                  {effortName(status.title_model.effort)}
                </span>
              </span>
            </Row>
          )}
        </Card>
      </Section>
      {/* Beside the dialog's close button and level with it (8 down), placed against the dialog rather than this page,
          so it stays there as the page scrolls. */}
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

/** Model and effort pickers, as the other settings' menus: each opens over its trigger, the choice in its place.
 * Restricted to supported efforts, and marking the runtime's defaults. */
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
  byDefault?: Choice // the runtime's default, marked in the menu; an effort only with its model
  models: Status["models"]
  efforts: string[]
  onChange: (change: Partial<Choice>) => void
}) {
  const t = useT()
  // In the menu only, after the name: the trigger shows the name alone.
  const marked = (isDefault: boolean) =>
    isDefault && (
      <span className="text-muted-foreground">{t.settings.byDefault}</span>
    )
  return (
    <div className="ml-auto flex items-center gap-2">
      <Select
        value={choice.model}
        onValueChange={(model) => onChange({ model: model as string })}
      >
        <SelectTrigger aria-label={`${label}: ${t.settings.model}`}>
          <SelectValue>
            {(model: string) => (
              <>
                <ProviderIcon model={model} className="size-4" />
                {modelName(model, models)}
              </>
            )}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          {models.map(({ id: model, name, unavailable }) => {
            const item = (
              <SelectItem
                key={model}
                value={model}
                disabled={unavailable !== null}
              >
                <ProviderIcon model={model} className="size-4" />
                {/* One line of text, or the row's gap would drop the space " (Default)" starts with. */}
                <span>
                  {name}
                  {marked(model === byDefault?.model)}
                </span>
              </SelectItem>
            )
            if (unavailable === null) return item
            // A disabled item takes no pointer events, so the hover lands on this wrapper.
            return (
              <Tooltip key={model}>
                <TooltipTrigger render={<div />}>{item}</TooltipTrigger>
                <TooltipContent side="left">
                  {t.settings.modelUnavailable[unavailable]}
                </TooltipContent>
              </Tooltip>
            )
          })}
        </SelectContent>
      </Select>
      <Select
        value={choice.effort}
        onValueChange={(effort) => onChange({ effort: effort as string })}
      >
        <SelectTrigger
          aria-label={`${label}: ${t.settings.effort}`}
          className="text-muted-foreground"
        >
          <SelectValue>{(effort: string) => effortName(effort)}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {efforts.map((effort) => (
            <SelectItem key={effort} value={effort}>
              <span>
                {effortName(effort)}
                {marked(
                  choice.model === byDefault?.model &&
                    effort === byDefault.effort
                )}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
