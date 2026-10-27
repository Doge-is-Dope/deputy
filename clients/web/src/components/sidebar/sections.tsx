import { type ReactNode } from "react"
import { useDroppable } from "@dnd-kit/core"
import { cn } from "cn"

import { SidebarGroup, SidebarGroupLabel } from "@/components/ui/sidebar"
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible"
import { useT } from "@/lib/i18n"
import { ChevronDownIcon } from "@/components/icons"
import { carriedBy, RECENTS } from "@/components/sidebar/drag"
import { FOLD } from "@/components/sidebar/motion"

/** A heading that folds its section away and back, as ChatGPT's and Codex's sidebar headings do: a chevron after the
    name on hover, pointing down while the section shows and to the side while it is folded. The rows' size, as
    theirs: only the muted color sets it apart. Lit as a hovered row is while its section would take a carried
    conversation. */
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

/** The recents under the projects, headed as Claude's sidebar heads its list: a heading above the conversations, not
 * one of them, smaller and lighter, close above them. A conversation dropped on it goes out of its project into it, the
 * heading lit meanwhile. Room under the last row, as much as above the line under the header's commands (pb-2), so the
 * list does not end on the sidebar's edge. */
export function RecentsGroup({
  open,
  onOpen,
  children,
}: {
  open: boolean
  onOpen: (open: boolean) => void
  children: ReactNode
}) {
  const t = useT()
  const { setNodeRef, isOver, active } = useDroppable({ id: RECENTS })
  const carried = carriedBy(active)
  return (
    <SidebarGroup ref={setNodeRef} className="pt-0 pb-2">
      <SectionLabel
        label={t.sidebar.recents}
        open={open}
        lit={isOver && carried !== undefined && carried.project !== null}
        onOpen={onOpen}
      />
      <Collapsible open={open}>
        <CollapsibleContent className={FOLD}>{children}</CollapsibleContent>
      </Collapsible>
    </SidebarGroup>
  )
}
