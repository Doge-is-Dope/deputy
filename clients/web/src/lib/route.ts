// The open conversation lives in the URL, #/run/<id> (its first run's id), so a reload or a shared link reopens it;
// none means a new task.

/** The link that opens a conversation, or a new task for null. */
export const runHref = (run: string | null) => (run ? `#/run/${run}` : "#")

/** The conversation the URL opens; null for a new task. */
export const runFromHash = () =>
  window.location.hash.match(/^#\/run\/([\w-]+)$/)?.[1] ?? null

/** Opens a conversation, or a new task for null. */
export function openRun(run: string | null) {
  window.location.hash = runHref(run).slice(1)
}

// A project's home, #/project/<name>, where a new conversation begins in it.

export const projectHref = (project: string) =>
  `#/project/${encodeURIComponent(project)}`

/** The project whose home the URL opens; null elsewhere. */
export const projectFromHash = () => {
  const match = window.location.hash.match(/^#\/project\/(.+)$/)
  return match ? decodeURIComponent(match[1]) : null
}

export function openProject(project: string) {
  window.location.hash = projectHref(project).slice(1)
}

// Every conversation on one page, #/chats, as Claude's "All chats" is.

export const CHATS_HREF = "#/chats"

/** Whether the URL opens the page of every conversation. */
export const chatsFromHash = () => window.location.hash === CHATS_HREF
