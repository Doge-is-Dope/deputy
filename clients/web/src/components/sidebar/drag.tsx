import {
  closestCenter,
  pointerWithin,
  type Active,
  type CollisionDetection,
  type Modifier,
} from "@dnd-kit/core"
import { getEventCoordinates } from "@dnd-kit/utilities"

import { type Conversation } from "@/lib/conversations"
import { FolderIcon } from "@/components/icons"

// The row a dragged project is carried by (DragOverlay): its folder, shut as the project is while dragged
// (ProjectGroup), and its name, lifted as a menu is over the page.
export function DraggedProject({ name }: { name: string }) {
  return (
    <div className="flex h-8 items-center gap-2.5 rounded-md bg-sidebar-accent pr-2 pl-2.5 text-sm text-sidebar-accent-foreground shadow-md ring-1 ring-foreground/10 pointer-coarse:h-10">
      <FolderIcon className="shrink-0" />
      <span className="truncate">{name}</span>
    </div>
  )
}

// The chip a dragged conversation is carried by (DragOverlay): its name, lifted as a project's row is, but only as wide
// as the name and beside the pointer, so the project it would go into shows under it, as Gmail carries mail to a label.
export function DraggedConversation({ name }: { name: string }) {
  return (
    <div className="flex h-8 w-max max-w-56 items-center rounded-md bg-sidebar-accent px-2.5 text-sm text-sidebar-accent-foreground shadow-md ring-1 ring-foreground/10 pointer-coarse:h-10">
      <span className="truncate">{name}</span>
    </div>
  )
}

// The conversation a drag carries; none while it is a project.
export const carriedBy = (active: Active | null): Conversation | undefined =>
  active?.data.current?.conversation

// Where the recents take a conversation dropped on them, out of its project. A project's name is trimmed, so none has
// this one; each project takes conversations by its name.
export const RECENTS = " recents"
// Where the new project row takes one: into the project made for it, named in the dialog that opens.
export const NEW_PROJECT = " new project"

// A conversation goes where the pointer is: into a project, a new one, out to the recents, or nowhere. A project takes
// the place of the project its row's middle is within, open or shut: passing an open one, it takes its place as its
// middle crosses that one's edge, with the list's conversations between, not once it has crossed its middle, which
// for a long list is far up or down; the nearest, where its middle is within none, as between two.
export const collision: CollisionDetection = (args) => {
  if (carriedBy(args.active)) return pointerWithin(args)
  const projects = args.droppableContainers.filter(
    (container) => container.id !== RECENTS && container.id !== NEW_PROJECT
  )
  if (args.collisionRect) {
    const middle = args.collisionRect.top + args.collisionRect.height / 2
    const within = projects.find((container) => {
      const rect = args.droppableRects.get(container.id)
      return rect && middle >= rect.top && middle <= rect.bottom
    })
    if (within)
      return [{ id: within.id, data: { droppableContainer: within, value: 0 } }]
  }
  return closestCenter({ ...args, droppableContainers: projects })
}

// A conversation's chip, its corner just under and right of the pointer.
export const byPointer: Modifier = ({
  active,
  activatorEvent,
  draggingNodeRect,
  transform,
}) => {
  const at = activatorEvent && getEventCoordinates(activatorEvent)
  if (!carriedBy(active) || !at || !draggingNodeRect) return transform
  return {
    ...transform,
    x: transform.x + at.x - draggingNodeRect.left + 12,
    y: transform.y + at.y - draggingNodeRect.top + 12,
  }
}

// A project dragged along the list only: up and down, and no further than its ends.
export const alongList: Modifier = ({
  active,
  transform,
  draggingNodeRect,
  containerNodeRect,
}) => {
  if (carriedBy(active)) return transform
  if (!draggingNodeRect || !containerNodeRect) return { ...transform, x: 0 }
  const y = Math.min(
    Math.max(transform.y, containerNodeRect.top - draggingNodeRect.top),
    containerNodeRect.bottom - draggingNodeRect.bottom
  )
  return { ...transform, x: 0, y }
}
