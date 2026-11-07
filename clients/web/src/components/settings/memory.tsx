import { useEffect, useId, useState } from "react"

import { MemoryList } from "@/components/memory/list"
import { memoryFailed } from "@/components/memory/notices"
import { Card, Section } from "@/components/settings/layout"
import { Button } from "@/components/ui/button"
import { ActionDialog } from "@/components/ui/dialog"
import { Switch } from "@/components/ui/switch"
import { setMemory, useChoices, type MemoryChoice } from "@/lib/choices"
import { useT } from "@/lib/i18n"
import { forgetPersonalMemories, loadMemories, useMemories } from "@/lib/memory"
import { useOpenedSettings } from "@/lib/settings"

const MODES: (keyof MemoryChoice)[] = ["learn", "use"]

/** What the agent learned from the user's interventions: whether it learns and uses them (kept in this browser and sent
 * with each message, lib/choices.ts), and the user's own rules, told everywhere, to edit or delete, or all deleted. A
 * project's own are in its menu (ProjectMemoryDialog). A line in the conversation opens this page at its rule
 * (openMemory). */
export function MemoryPage({ onClose }: { onClose?: () => void }) {
  const t = useT()
  const id = useId()
  const { memory: choice } = useChoices()
  const { list, failed } = useMemories()
  const opened = useOpenedSettings()
  useEffect(() => void loadMemories(), [])
  // A deleted one goes at once; its notice puts it back (memoryDeleted).
  const rows = (list ?? []).filter((memory) => memory.project === null)

  return (
    <>
      <Section>
        <Card>
          {MODES.map((mode) => {
            // Named, then what it does in a muted line under it, as the approval modes are.
            const words = t.settings.memoryModes[mode]
            return (
              <label
                key={mode}
                className="flex min-h-14 cursor-pointer items-center gap-6 py-3"
              >
                <span className="flex-1">
                  <span id={`${id}-${mode}`} className="block">
                    {words.label}
                  </span>
                  <span
                    id={`${id}-${mode}-description`}
                    className="mt-0.5 block text-xs text-muted-foreground"
                  >
                    {words.description}
                  </span>
                </span>
                <Switch
                  checked={choice[mode]}
                  onCheckedChange={(on) => setMemory({ [mode]: on })}
                  aria-labelledby={`${id}-${mode}`}
                  aria-describedby={`${id}-${mode}-description`}
                />
              </label>
            )
          })}
        </Card>

        {list === null ? (
          <p className="px-1 text-sm text-muted-foreground">
            {failed ? t.settings.memoryLoadFailed : t.common.loading}
          </p>
        ) : rows.length === 0 ? (
          <p className="px-1 text-sm text-muted-foreground">
            {t.settings.memoryEmpty}
          </p>
        ) : (
          <>
            <ResetMemory />
            <MemoryList
              memories={rows}
              item={opened.item}
              editing={opened.editing}
              onClose={onClose}
            />
          </>
        )}
      </Section>
    </>
  )
}

/** 刪除全部記憶, between the switches and the rules while there are any: asked about first, as it cannot be undone.
 * The user's own only: a project's are kept, in its menu. */
function ResetMemory() {
  const t = useT()
  const [asking, setAsking] = useState(false)
  async function reset() {
    try {
      await forgetPersonalMemories()
      setAsking(false)
    } catch {
      memoryFailed(t)
    }
  }
  return (
    <>
      <Button
        variant="ghost"
        className="-ml-[9px] self-start text-destructive hover:bg-destructive/10 hover:text-destructive"
        onClick={() => setAsking(true)}
      >
        {t.settings.resetMemory}
      </Button>
      <ActionDialog
        open={asking}
        onOpenChange={setAsking}
        title={t.settings.resetMemoryAsk}
        action={t.settings.resetMemory}
        onAction={reset}
        destructive
        className="sm:max-w-md"
      >
        <p className="text-sm text-muted-foreground">
          {t.settings.resetMemoryDetail}
        </p>
      </ActionDialog>
    </>
  )
}
