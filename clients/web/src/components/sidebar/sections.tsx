import {
  useEffect,
  useRef,
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
import { carriedBy, RECENTS, TAKES } from "@/components/sidebar/drag"
import { FOLD } from "@/components/sidebar/motion"
import type { Lists } from "@/hooks/use-api"

function LoadingRows({ ref }: { ref?: Ref<HTMLLIElement> }) {
  const t = useT()
  return (
    <li
      ref={ref}
      role="status"
      className="flex flex-col gap-0.5 motion-safe:animate-pulse"
    >
      <span className="sr-only">{t.common.loading}</span>
      {Array.from({ length: 3 }, (_, index) => (
        <SidebarMenuSkeleton
          key={index}
          className="h-8 pl-row-text pointer-coarse:h-10"
        />
      ))}
    </li>
  )
}

export function SectionLabel({
  label,
  open,
  onOpen,
}: {
  label: string
  open: boolean
  onOpen?: (open: boolean) => void // none: it does not fold, and is a heading only
}) {
  if (!onOpen)
    return (
      <SidebarGroupLabel className="w-full pl-row-text text-sm font-normal text-muted-foreground">
        {label}
      </SidebarGroupLabel>
    )
  return (
    <SidebarGroupLabel
      render={<button type="button" />}
      aria-expanded={open}
      onClick={() => onOpen(!open)}
      className="group/label w-full gap-1 pl-row-text text-sm font-normal text-muted-foreground [&>svg]:size-4"
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
  const group = useRef<HTMLDivElement | null>(null)
  return (
    <SidebarGroup
      ref={(node) => {
        setNodeRef(node)
        group.current = node
      }}
      className="pt-0 pb-2"
    >
      <SectionLabel
        label={t.sidebar.recents}
        open={open}
        onOpen={(open) => {
          // The room under its label, down to the end of what scrolls: all its fold moves over (FOLD).
          const label = group.current?.firstElementChild
          if (label && scroller.current)
            group.current!.style.setProperty(
              "--fold-room",
              `${scroller.current.getBoundingClientRect().bottom - label.getBoundingClientRect().bottom}px`
            )
          onOpen(open)
        }}
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
      {/* A conversation carried out of a project, over the recents: a line around them, on the rows' column. */}
      {isOver && carried !== undefined && carried.project !== null && (
        <span
          aria-hidden
          className={cn(
            "pointer-events-none absolute inset-x-2 top-0 bottom-2",
            TAKES
          )}
        />
      )}
    </SidebarGroup>
  )
}
