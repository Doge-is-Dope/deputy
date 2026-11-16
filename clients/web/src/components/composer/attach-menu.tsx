import { PaperclipIcon } from "@/components/icons"
import { useT } from "@/lib/i18n"

/** The list the plus button or a typed @ opens over the composer. Its keys are handled in the text (composer.tsx). */
export function AttachMenu({
  id,
  onChoose,
}: {
  id: string
  onChoose: () => void
}) {
  const t = useT()
  return (
    <div
      id={id}
      role="listbox"
      aria-label={t.composer.attachments.add}
      // Picking with the pointer leaves the focus in the text, where the list's keys work.
      onMouseDown={(event) => event.preventDefault()}
      className="absolute bottom-full -left-px mb-2 w-max min-w-36 rounded-popup bg-popover p-popup text-sm text-popover-foreground shadow-md ring-1 ring-foreground/10 transition-[opacity,translate] duration-150 ease-(--ease-out) motion-reduce:transition-none starting:translate-y-1 starting:opacity-0"
    >
      <div
        id={`${id}-0`}
        role="option"
        aria-selected
        onClick={onChoose}
        className="flex cursor-default items-center gap-2 rounded-row bg-accent px-2 py-1.5 text-accent-foreground"
      >
        <PaperclipIcon className="size-4 text-muted-foreground" />
        {t.composer.attachments.add}
      </div>
    </div>
  )
}
