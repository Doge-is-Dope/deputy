import { cn } from "cn"

// One shape of a placeholder, the text at 10% over whatever it sits on. It does not pulse by itself: what holds the
// shapes does, as one animation however many there are.
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("rounded-md bg-foreground/10", className)}
      {...props}
    />
  )
}

export { Skeleton }
