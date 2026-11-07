import { isComposing } from "@/lib/keys"

/** A name edited in place over its row: Enter or leaving the field saves, Esc cancels. Enter or Esc while an input
 * method is composing is the input method's. */
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
      onFocus={(event) => event.currentTarget.select()}
      onBlur={onSave}
      onKeyDown={(event) => {
        if (isComposing(event.nativeEvent)) return
        if (event.key === "Enter") onSave()
        if (event.key === "Escape") onCancel()
      }}
      className={className}
    />
  )
}
