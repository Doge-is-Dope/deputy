import type { Conversation, RunSummary } from "@/lib/api"

/** The sidebar's sections: each project's conversations under its id, then the rest as recents, each most recently
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
  conversation.title ?? (conversation.goal || conversation.id)

/** A conversation from its runs, oldest first, as the lists fold them (storage.conversations_of): for one beyond the
 * pages they hold. Null without runs. */
export function conversationOf(runs: RunSummary[]): Conversation | null {
  const [first, latest] = [runs[0], runs.at(-1)]
  if (!first || !latest) return null
  const title = runs.findLast((run) => run.title)?.title ?? null
  const { thread: id, project, goal } = first
  return { id, project, title, goal, last: latest.started, latest }
}

/** Merges pages by conversation ID, most recently active first. Later lists win on duplicates,
 * which can occur when a conversation moves between page requests. */
export function merged(lists: Conversation[][]): Conversation[] {
  const byId = new Map<string, Conversation>()
  for (const list of lists)
    for (const conversation of list) byId.set(conversation.id, conversation)
  return [...byId.values()].sort((a, b) => b.last - a.last)
}
