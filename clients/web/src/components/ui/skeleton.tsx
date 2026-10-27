import { cn } from "cn"

// The same pass of light as the conversation's placeholder (index.css's skeleton-shape), not shadcn's pulse: it needs a
// size container round the shapes, and --at where a shape starts in it.
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("skeleton-shape rounded-md", className)}
      {...props}
    />
  )
}

export { Skeleton }
