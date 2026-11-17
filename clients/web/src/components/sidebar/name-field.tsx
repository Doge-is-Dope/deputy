import { cn } from "cn"

import { isComposing } from "@/lib/keys"

/** A name edited in place over its row, all of it chosen: Enter or leaving the field saves, Esc cancels. Enter or
 * Esc while an input method is composing is the input method's. */
export function NameField({
  value,
  label,
  className,
  onChange,
  onSave,
  onCancel,
}: {
  value: string
  label: string
  className: string
  onChange: (value: string) => void
  onSave: () => void
  onCancel: () => void
}) {
  return (
    <input
      autoFocus
      value={value}
      aria-label={label}
      onChange={(event) => onChange(event.target.value)}
      // All of it chosen, to type over, with the caret after its last character and the end of the name in view.
      onFocus={(event) => {
        const field = event.currentTarget
        field.setSelectionRange(0, field.value.length, "forward")
        field.scrollLeft = field.scrollWidth
      }}
      onBlur={onSave}
      onKeyDown={(event) => {
        if (isComposing(event.nativeEvent)) return
        if (event.key === "Enter") onSave()
        if (event.key === "Escape") onCancel()
      }}
      // The page's selection color is a step off its background, as light as the field's own fill: here it is the accent
      // laid over the field, which shows on any fill and theme.
      className={cn(
        "selection:bg-[color-mix(in_srgb,var(--theme-accent)_24%,transparent)]",
        className
      )}
    />
  )
}
