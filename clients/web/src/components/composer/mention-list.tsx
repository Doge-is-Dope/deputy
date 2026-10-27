import { useT } from "@/lib/i18n"
import type { Target } from "@/components/composer/mention-text"

/** The names an @ being typed completes to, over the composer: picked with the pointer, or with the keys the text
 * hands on (useMentionText). */
export function MentionList({
  id,
  options,
  current,
  onHighlight,
  onChoose,
}: {
  id: string
  options: Target[]
  current: number // the option Enter picks
  onHighlight: (index: number) => void
  onChoose: (name: string) => void
}) {
  const t = useT()
  return (
    <div
      id={id}
      role="listbox"
      aria-label={t.composer.mention.list}
      // Picking with the pointer leaves the focus in the text, where the name goes.
      onMouseDown={(event) => event.preventDefault()}
      className="absolute -inset-x-px bottom-full mb-2 rounded-[1.75rem] border bg-popover p-1.5 text-sm text-popover-foreground shadow-[0_4px_16px_rgb(0_0_0/0.08)] transition-[opacity,translate] duration-150 ease-(--ease-out) motion-reduce:transition-none starting:translate-y-1 starting:opacity-0"
    >
      {options.map(({ name, description, logo: Logo }, index) => (
        <div
          key={name}
          id={`${id}-${index}`}
          role="option"
          aria-selected={index === current}
          onMouseMove={() => onHighlight(index)}
          onClick={() => onChoose(name)}
          className="flex cursor-default items-center gap-2 rounded-[1.375rem] px-3 py-2 aria-selected:bg-accent aria-selected:text-accent-foreground"
        >
          {/* The logo and the name as a mention shows them: 16px, and 3px apart. */}
          <span className="flex shrink-0 items-center gap-[3px]">
            <Logo className="size-4" />
            {name}
          </span>
          <span className="min-w-0 truncate text-muted-foreground">
            {description}
          </span>
        </div>
      ))}
    </div>
  )
}
