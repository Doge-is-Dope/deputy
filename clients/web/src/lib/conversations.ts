import type { RunSummary } from "@/lib/api"

/** One conversation: a first goal and the runs that followed it in the same thread. */
export type Conversation = {
  id: string // the thread: its first run's id
  runs: RunSummary[] // oldest first
  latest: RunSummary
  updated: number // when its latest run started
  title: string | null // its name, made by the runtime from its first message (agent/title.py); null until then
  project: string | null // the project its first run was started in; null for one the user began on the page
}

/** The sidebar's sections: each project's conversations under its name, then the rest as recents, each most recently
 * active first. Projects in the order their most recent conversation comes. */
export function sectionsOf(conversations: Conversation[]) {
  const projects = new Map<string, Conversation[]>()
  const recents: Conversation[] = []
  for (const conversation of conversations) {
    const { project } = conversation
    if (project === null) recents.push(conversation)
    else projects.set(project, [...(projects.get(project) ?? []), conversation])
  }
  return { projects: [...projects], recents }
}

/** What a conversation is listed by: its name, or its first message until it has one. */
export const nameOf = (conversation: Conversation) =>
  conversation.title ?? (conversation.runs[0].goal || conversation.id)

/** The runs grouped into conversations, the most recently active first. */
export function conversationsOf(runs: RunSummary[]): Conversation[] {
  const byThread = new Map<string, RunSummary[]>()
  for (const run of runs) {
    const thread = run.thread ?? run.id
    byThread.set(thread, [...(byThread.get(thread) ?? []), run])
  }
  return [...byThread]
    .map(([id, members]) => {
      const ordered = members.toSorted((a, b) => a.started - b.started)
      const latest = ordered.at(-1)!
      // Named in its first run as a rule, in a later one when that run was stopped before the name came; a name the
      // user gives it goes to its latest run (server.update_conversation), so the latest run's name stands.
      const title = ordered.findLast((run) => run.title)?.title ?? null
      return {
        id,
        runs: ordered,
        latest,
        updated: latest.started,
        title,
        project: ordered[0].project ?? null, // null, not a nameless project, from a runtime that does not say
      }
    })
    .sort((a, b) => b.updated - a.updated)
}
