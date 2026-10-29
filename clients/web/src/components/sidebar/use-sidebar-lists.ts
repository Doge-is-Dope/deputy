import { useMemo, useState } from "react"

import type { Project } from "@/lib/api"
import { sectionsOf, type Conversation } from "@/lib/conversations"
import { reducedMotion } from "@/lib/motion"
import { openRun } from "@/lib/route"
import { DROP } from "@/components/sidebar/motion"
import { useStoredNames } from "@/hooks/use-stored-names"

/**
 * The sidebar's projects and recents as the viewer sees them, and the edits to them. An edit shows at once, before the
 * runtime has made it, while the rows it takes away close up where they were (`left`, `closing`); one that fails goes
 * back. Projects are the runtime's, by id; which the viewer opened and the order they put them in are kept in this
 * browser.
 */
export function useSidebarLists({
  conversations,
  projects: made,
  selectedProject,
  onDelete,
  onMove,
  onCreateProject,
  onRenameProject,
  onDeleteProject,
}: {
  conversations: Conversation[] | null
  projects: Project[] | null // the viewer's, empty ones too
  selectedProject: string | null // the project whose home is open
  onDelete: (
    conversations: string[],
    project: string | null
  ) => Promise<boolean>
  onMove: (
    conversation: string,
    project: string | null
  ) => Promise<{ project: string | null } | null>
  onCreateProject: (name: string) => Promise<Project | null>
  onRenameProject: (project: string, name: string) => Promise<Project | null>
  onDeleteProject: (project: string) => Promise<unknown>
}) {
  // Which projects the viewer unfolded, by id, kept in this browser.
  const [opened, setOpened] = useStoredNames("opened-projects")
  // The projects' order, kept in this browser: as the viewer dragged them, a new one first. A conversation moving into
  // or out of one leaves it where it is.
  const [order, , setOrder] = useStoredNames("project-order")
  // Projects being renamed, id to new name: listed by it from the moment it is given. Each goes once the runtime's
  // list has it, or if the rename failed.
  const [renamed, setRenamed] = useState<Record<string, string>>({})
  const named = Object.keys(renamed).filter(
    (id) => made?.find((project) => project.id === id)?.name === renamed[id]
  )
  if (named.length > 0)
    setRenamed((map) =>
      Object.fromEntries(
        Object.entries(map).filter(([id]) => !named.includes(id))
      )
    )
  // Conversations being moved, each to its project (null: the recents): listed there from the moment they are moved.
  // Each goes once the list has it there, or is gone, or if the move failed.
  const [placed, setPlaced] = useState<Record<string, string | null>>({})
  const landed = Object.keys(placed).filter((id) => {
    const listed = conversations?.find((conversation) => conversation.id === id)
    return listed === undefined || listed.project === placed[id]
  })
  if (landed.length > 0)
    setPlaced((map) =>
      Object.fromEntries(
        Object.entries(map).filter(([id]) => !landed.includes(id))
      )
    )
  // A copy of each conversation just moved, as it was, listed where it was a moment longer while its row there closes up
  // (ConversationItem's moving): its own row meanwhile opens where it went. A deleted one's row only closes up.
  const [left, setLeft] = useState<Conversation[]>([])
  // Conversations being deleted, by id: out of the list from the moment they are, until it no longer has them; back
  // should the delete fail.
  const [removed, setRemoved] = useState<string[]>([])
  const purged = removed.filter(
    (id) => !conversations?.some((conversation) => conversation.id === id)
  )
  if (purged.length > 0)
    setRemoved((ids) => ids.filter((id) => !purged.includes(id)))
  // Projects being deleted, as they were with their conversations and name, listed in their place a moment longer
  // while they fold shut (ProjectGroup's leaving).
  const [closing, setClosing] = useState<[string, Conversation[], string][]>([])
  // Each project's name by id: as just renamed, else the runtime's, else as it was while it folds shut.
  const names = useMemo(
    () =>
      Object.fromEntries([
        ...closing.map(([id, , name]) => [id, name]),
        ...(made ?? []).map((project) => [project.id, project.name]),
        ...Object.entries(renamed),
      ]) as Record<string, string>,
    [closing, made, renamed]
  )
  const { projects: listed, recents } = useMemo(() => {
    const known = new Set((made ?? []).map((project) => project.id))
    const kept = (conversations ?? []).filter(
      (conversation) => !removed.includes(conversation.id)
    )
    // In the recents, one whose project is gone.
    const shown = kept.map((conversation) => {
      const project =
        conversation.id in placed
          ? placed[conversation.id]
          : conversation.project
      return {
        ...conversation,
        project: project !== null && known.has(project) ? project : null,
      }
    })
    const sections = sectionsOf(
      [...shown, ...left].toSorted((a, b) => b.updated - a.updated)
    )
    const listed = new Set(sections.projects.map(([id]) => id))
    // Those with no conversation too.
    const empty = [...known]
      .filter((id) => !listed.has(id))
      .map((id): [string, Conversation[]] => [id, []])
    const standing = [...sections.projects, ...empty].filter(
      ([id]) => !closing.some(([shut]) => shut === id)
    )
    const shutting = closing.map(([id, items]): [string, Conversation[]] => [
      id,
      items,
    ])
    return { ...sections, projects: [...standing, ...shutting] }
  }, [closing, conversations, left, made, placed, removed])
  const unordered = listed.map(([id]) => id).filter((id) => !order.includes(id))
  if (unordered.length > 0)
    setOrder((list) => [
      ...unordered.filter((id) => !list.includes(id)),
      ...list,
    ])
  // Memoized by hand: the compiler does not keep toSorted's result, so each render made a new list, and from it new
  // names and new row callbacks, and every row rendered again on any change of the sidebar's state (20-30ms).
  const projects = useMemo(
    () => listed.toSorted(([a], [b]) => order.indexOf(a) - order.indexOf(b)),
    [listed, order]
  )
  // Its row where it was closes up (left), for as long as a dropped project takes to settle.
  const leave = (conversation: Conversation) => {
    if (reducedMotion()) return
    setLeft((list) => [
      ...list.filter((each) => each.id !== conversation.id),
      conversation,
    ])
    setTimeout(
      () => setLeft((list) => list.filter((each) => each !== conversation)),
      DROP.duration
    )
  }
  // It shows in its new place at once (placed), its row opening there as the one it leaves closes up.
  const shift = (conversation: Conversation, project: string | null) => {
    setPlaced((map) => ({ ...map, [conversation.id]: project }))
    leave(conversation)
  }
  // Gone from the list at once, its row closing up as a moved one's does, rather than when the list comes back.
  const remove = async (conversation: Conversation) => {
    setRemoved((ids) => [...ids, conversation.id])
    leave(conversation)
    if (!(await onDelete([conversation.id], null)))
      setRemoved((ids) => ids.filter((id) => id !== conversation.id))
  }
  // All of it at once: its conversations out of the list and its row folding shut with them, rather than each going
  // as its delete is done; then the project itself, once they are all gone. Those that fail to go come back, and the
  // project stays with them.
  const deleteProject = async (project: string, items: Conversation[]) => {
    const ids = items.map((conversation) => conversation.id)
    setRemoved((list) => [...list, ...ids])
    if (project === selectedProject) openRun(null)
    const forget = () => {
      setClosing((list) => list.filter(([id]) => id !== project))
      setOpened(project, false)
      setOrder((list) => list.filter((each) => each !== project))
    }
    if (reducedMotion()) forget()
    else {
      setClosing((list) => [...list, [project, items, names[project] ?? ""]])
      setTimeout(forget, DROP.duration)
    }
    if (ids.length > 0 && !(await onDelete(ids, project))) {
      setRemoved((list) => list.filter((id) => !ids.includes(id)))
      return
    }
    await onDeleteProject(project)
  }
  // It goes back should the move fail. A project stays when its last conversation moves out.
  const move = async (conversation: Conversation, project: string | null) => {
    const from = conversation.project
    if (from === project) return
    shift(conversation, project)
    if ((await onMove(conversation.id, project)) === null)
      shift({ ...conversation, project }, from)
  }
  // The project's id once made, unfolded; null if it was not.
  const createProject = async (name: string) => {
    const project = await onCreateProject(name)
    if (project === null) return null
    setOpened(project.id, true)
    return project.id
  }
  // Listed by the new name at once; its id, and so its conversations, its place and its home, stay as they are.
  const renameProject = async (project: string, name: string) => {
    setRenamed((map) => ({ ...map, [project]: name }))
    if ((await onRenameProject(project, name)) === null)
      setRenamed((map) =>
        Object.fromEntries(Object.entries(map).filter(([id]) => id !== project))
      )
  }
  return {
    projects,
    names,
    recents,
    closing,
    left,
    opened,
    setOpened,
    setOrder,
    remove,
    deleteProject,
    move,
    createProject,
    renameProject,
  }
}
