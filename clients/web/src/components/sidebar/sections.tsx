import {
  useEffect,
  useState,
  type ReactNode,
  type Ref,
  type RefObject,
} from "react"
import { useDroppable } from "@dnd-kit/core"
import { cn } from "cn"

import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuSkeleton,
} from "@/components/ui/sidebar"
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible"
import { useT } from "@/lib/i18n"
import { ChevronDownIcon } from "@/components/icons"
import { carriedBy, RECENTS } from "@/components/sidebar/drag"
import { FOLD } from "@/components/sidebar/motion"
import type { Lists } from "@/hooks/use-api"

/** Accessible loading placeholders. `inset` aligns them with project conversations. */
export function LoadingRows({
  ref,
  inset = false,
  className,
}: {
  ref?: Ref<HTMLLIElement>
  inset?: boolean
  className?: string
}) {
  const t = useT()
  return (
    <li
      ref={ref}
      role="status"
      className={cn("@container flex flex-col gap-0.5", className)}
    >
      <span className="sr-only">{t.common.loading}</span>
      {Array.from({ length: 3 }, (_, index) => (
        <SidebarMenuSkeleton
          key={index}
          className={cn(
            "h-8 pointer-coarse:h-10",
            inset && "pl-10 [--row-at:32px]"
          )}
        />
      ))}
    </li>
  )
}

/** Collapsible section heading. Highlights when it can accept a dropped conversation. */
export function SectionLabel({
  label,
  open,
  lit = false,
  onOpen,
}: {
  label: string
  open: boolean
  lit?: boolean
  onOpen?: (open: boolean) => void // none: it does not fold, and is a heading only
}) {
  if (!onOpen)
    return (
      <SidebarGroupLabel className="w-full text-sm font-normal text-muted-foreground">
        {label}
      </SidebarGroupLabel>
    )
  return (
    <SidebarGroupLabel
      render={<button type="button" />}
      aria-expanded={open}
      onClick={() => onOpen(!open)}
      className={cn(
        "group/label w-full gap-1 text-sm font-normal text-muted-foreground [&>svg]:size-4",
        lit && "bg-sidebar-accent"
      )}
    >
      {label}
      <ChevronDownIcon
        className={cn(
          "size-4 opacity-0 transition-[opacity,rotate] duration-200 ease-(--ease-out) group-hover/label:opacity-100 group-focus-visible/label:opacity-100 motion-reduce:transition-none [@media(hover:none)]:opacity-100",
          !open && "-rotate-90"
        )}
      />
    </SidebarGroupLabel>
  )
}

/** Recent conversations with infinite scrolling. Dropping a conversation here removes it from its project. */
export function RecentsGroup({
  open,
  onOpen,
  lists,
  scroller,
  children,
}: {
  open: boolean
  onOpen: (open: boolean) => void
  lists: Lists
  scroller: RefObject<HTMLElement | null> // the list that scrolls, around the group
  children: ReactNode // their rows
}) {
  const t = useT()
  const { setNodeRef, isOver, active } = useDroppable({ id: RECENTS })
  const carried = carriedBy(active)
  // State reattaches the observer when the mobile sheet remounts the list.
  const [end, setEnd] = useState<HTMLLIElement | null>(null)
  const more = lists.more(null)
  const { load } = lists
  useEffect(() => {
    if (!end || !more) return
    const observer = new IntersectionObserver(
      ([entry]) => entry.isIntersecting && load(null),
      { root: scroller.current, rootMargin: "200px" }
    )
    observer.observe(end)
    return () => observer.disconnect()
  }, [end, more, load, scroller])
  return (
    <SidebarGroup ref={setNodeRef} className="pt-0 pb-2">
      <SectionLabel
        label={t.sidebar.recents}
        open={open}
        lit={isOver && carried !== undefined && carried.project !== null}
        onOpen={onOpen}
      />
      <Collapsible open={open}>
        <CollapsibleContent className={FOLD}>
          <SidebarMenu className="gap-0.5">
            {children}
            {/* Animate placeholders only while loading. Reobserve each replacement so a visible end
                keeps loading pages until it fills the viewport. */}
            {more &&
              (lists.loading(null) ? (
                <LoadingRows ref={setEnd} />
              ) : (
                <li ref={setEnd} aria-hidden className="h-8" />
              ))}
          </SidebarMenu>
        </CollapsibleContent>
      </Collapsible>
    </SidebarGroup>
  )
}
