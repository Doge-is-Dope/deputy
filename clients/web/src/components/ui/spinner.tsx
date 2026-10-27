import { cn } from "cn"
import { SpinnerIcon as Loader2Icon } from "@/components/icons"
import { useT } from "@/lib/i18n"

function Spinner({ className, ...props }: React.ComponentProps<"span">) {
  const t = useT()
  return (
    <Loader2Icon
      data-slot="spinner"
      role="status"
      aria-label={t.common.loading}
      className={cn("size-5", className)}
      {...props}
    />
  )
}

export { Spinner }
