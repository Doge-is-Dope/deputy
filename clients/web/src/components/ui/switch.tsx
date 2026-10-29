import { Switch as SwitchPrimitive } from "@base-ui/react/switch"
import { cn } from "cn"

/** An on/off setting, as ChatGPT's and Claude's settings have them: a pill whose knob slides across as it fills. */
function Switch({ className, ...props }: SwitchPrimitive.Root.Props) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "inline-flex h-5 w-8 shrink-0 items-center rounded-full border border-transparent bg-input p-px transition-colors duration-150 ease-(--ease-out) outline-none focus-visible:ring-3 focus-visible:ring-ring/50 motion-reduce:transition-none dark:bg-input/80 data-checked:bg-primary data-disabled:cursor-not-allowed data-disabled:opacity-50",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="block size-4 rounded-full bg-background shadow-sm transition-transform duration-150 ease-(--ease-out) motion-reduce:transition-none data-checked:translate-x-3 dark:data-checked:bg-primary-foreground"
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
