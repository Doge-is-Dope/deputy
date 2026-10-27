import { useMemo, useState } from "react"

import { sectionsOf, type Conversation } from "@/lib/conversations"
import { reducedMotion } from "@/lib/motion"
import { openProject, openRun } from "@/lib/route"
import { DROP } from "@/components/sidebar/motion"
import { useStoredNames } from "@/hooks/use-stored-names"

/**
 * The sidebar's projects and recents as the viewer sees them, and the edits to them. An edit shows at once, before the
 * runtime has made it, while the rows it takes away close up where they were (`left`, `closing`); one that fails goes
 * back. Which projects the viewer opened, made and put in order is kept in this browser.
 */
export function useSidebarLists({
  conversations,
  selectedProject,
  onDelete,
  onMove,
}: {
  conversations: Conversation[] | null
  selectedProject: string | null // the project whose home is open
  onDelete: (
    conversations: string[],
    project: string | null
  ) => Promise<boolean>
  onMove: (
    conversation: string,
    project: string | null
  ) => Promise<{ project: string | null } | null>
}) {
  // Which projects the viewer unfolded, and which they made here that have no conversation yet (a project is
  // otherwise only what its runs carry): both kept in this browser.
  const [opened, setOpened] = useStoredNames("opened-projects")
  const [made, setMade] = useStoredNames("made-projects")
  // The projects' order, kept in this browser: as the viewer dragged them, a new one first. A conversation moving into
  // or out of one leaves it where it is.
  const [order, , setOrder] = useStoredNames("project-order")
  // Projects being renamed, old name to new: listed by the new name from the moment it is given, open as they were,
  // while their conversations move one by one. Each goes once the list has none left under the old name.
  const [renamed, setRenamed] = useState<Record<string, string>>({})
  const stale = Object.keys(renamed).filter(
    (old) =>
      !conversations?.some((conversation) => conversation.project === old)
  )
  if (stale.length > 0)
    setRenamed((map) =>
      Object.fromEntries(
        Object.entries(map).filter(([old]) => !stale.includes(old))
      )
    )
  // Conversations being moved, each to its project (null: the recents): listed there from the moment they are moved,
  // as a renamed project is. Each goes once the list has it there, or is gone, or if the move failed.
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
  // Projects being deleted, as they were with their conversations, listed in their place a moment longer while they
  // fold shut (ProjectGroup's leaving).
  const [closing, setClosing] = useState<[string, Conversation[]][]>([])
  const { projects: listed, recents } = useMemo(() => {
    const kept = (conversations ?? []).filter(
      (conversation) => !removed.includes(conversation.id)
    )
    const shown = kept.map((conversation) => {
      const project =
        conversation.id in placed
          ? placed[conversation.id]
          : conversation.project
      return {
        ...conversation,
        project:
          project !== null && project in renamed ? renamed[project] : project,
      }
    })
    const sections = sectionsOf(
      [...shown, ...left].toSorted((a, b) => b.updated - a.updated)
    )
    const listed = new Set(sections.projects.map(([name]) => name))
    // Those made here and still empty too.
    const empty = made
      .filter((name) => !listed.has(name))
      .map((name): [string, Conversation[]] => [name, []])
    const standing = [...sections.projects, ...empty].filter(
      ([name]) => !closing.some(([shut]) => shut === name)
    )
    return { ...sections, projects: [...standing, ...closing] }
  }, [closing, conversations, left, made, placed, removed, renamed])
  const unordered = listed
    .map(([name]) => name)
    .filter((name) => !order.includes(name))
  if (unordered.length > 0)
    setOrder((list) => [
      ...unordered.filter((name) => !list.includes(name)),
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
  // Gone from the list at once, its row closing up as a moved one's does, rather than when the list comes back. Its
  // project stays should it be the last there, as when it moves out.
  const remove = async (conversation: Conversation) => {
    if (conversation.project !== null) setMade(conversation.project, true)
    setRemoved((ids) => [...ids, conversation.id])
    leave(conversation)
    if (!(await onDelete([conversation.id], null)))
      setRemoved((ids) => ids.filter((id) => id !== conversation.id))
  }
  // All of it at once: its conversations out of the list and its row folding shut with them, rather than each going
  // as its delete is done; then the project itself. Those that fail to go come back.
  const deleteProject = async (project: string, items: Conversation[]) => {
    const ids = items.map((conversation) => conversation.id)
    setRemoved((list) => [...list, ...ids])
    if (project === selectedProject) openRun(null)
    const forget = () => {
      setClosing((list) => list.filter(([name]) => name !== project))
      setMade(project, false)
      setOrder((list) => list.filter((each) => each !== project))
    }
    if (reducedMotion()) forget()
    else {
      setClosing((list) => [...list, [project, items]])
      setTimeout(forget, DROP.duration)
    }
    if (ids.length > 0 && !(await onDelete(ids, project)))
      setRemoved((list) => list.filter((id) => !ids.includes(id)))
  }
  // It goes back should the move fail. A project stays when its last conversation moves out, as one made here and still
  // empty does.
  const move = async (conversation: Conversation, project: string | null) => {
    const from = conversation.project
    if (from === project) return
    if (from !== null) setMade(from, true)
    shift(conversation, project)
    if ((await onMove(conversation.id, project)) === null)
      shift({ ...conversation, project }, from)
  }
  // Every conversation in it moved to the new name; this browser's lists follow, and its home if open. All of it shows
  // at once: the list does not wait for the moves (renamed).
  const renameProject = async (
    project: string,
    items: Conversation[],
    name: string
  ) => {
    if (items.length > 0) setRenamed((map) => ({ ...map, [project]: name }))
    // In its place: into the place of the name it takes, should that be another project's.
    setOrder((list) =>
      list.includes(name)
        ? list.filter((each) => each !== project)
        : list.map((each) => (each === project ? name : each))
    )
    if (made.includes(project)) {
      setMade(project, false)
      setMade(name, true)
    }
    if (opened.includes(project)) {
      setOpened(project, false)
      setOpened(name, true)
    }
    if (project === selectedProject) openProject(name)
    let moved = true
    for (const conversation of items)
      moved = (await onMove(conversation.id, name)) !== null && moved
    // One that did not move stays under the old name, which shows again.
    if (!moved)
      setRenamed((map) =>
        Object.fromEntries(
          Object.entries(map).filter(([old]) => old !== project)
        )
      )
  }
  return {
    projects,
    recents,
    closing,
    left,
    opened,
    setOpened,
    setMade,
    setOrder,
    remove,
    deleteProject,
    move,
    renameProject,
  }
}
