// Signing in to a runtime that asks for it (runtime/src/computer_use/auth). It keeps no session: the page holds the
// proof, a cookie with the token, or the sign-in proxy's own, and sends it with every request. What the runtime said
// of who the page is lives here, kept up to date for the components that show it (useSession).

import { useSyncExternalStore } from "react"

/** How a runtime that turned the page away wants it to sign in. */
export type Login = "token" | "proxy"

/** Who the page is signed in as (auth.base.Identity): an id safe as a key, and the name to show. */
export type User = { id: string; name: string }

/** Who the page is signed in as and how; nobody until the runtime has said, as when it could not be reached. */
export type Session = { user: User | null; login: Login | null }

// Asked no longer than this: a runtime or proxy that never answers leaves the page to say it cannot reach it.
const WAIT = 5000

let session: Session = { user: null, login: null }
const listeners = new Set<() => void>()
let asking: Promise<Login | null> | null = null

/** The session, the component showing it drawn again as it changes. */
export const useSession = () =>
  useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => session
  )

/** Asks the runtime who the page is: null when it says, or cannot be reached; how to sign in when it turns the page
 * away. One question at a time. */
function ask(): Promise<Login | null> {
  asking ??= fetch("/api/session", { signal: AbortSignal.timeout(WAIT) })
    .then(async (response) => {
      const answer = await response.json().catch(() => ({}))
      if (response.status === 401)
        return answer.login === "proxy" ? "proxy" : "token"
      if (response.ok && typeof answer.id === "string") {
        const login = ["token", "proxy"].includes(answer.login)
          ? answer.login
          : null
        session = { user: { id: answer.id, name: answer.name }, login }
        listeners.forEach((listener) => listener())
      }
      return null
    })
    .catch(() => null)
    .finally(() => (asking = null))
  return asking
}

/** What every API answer tells the session: a 401 means signed out meanwhile (e.g. a new token on the runtime's
 * restart), and the page starts again, which shows how to sign in; any other answer, while the page does not know
 * who it is yet (the runtime was not up when it started), is the moment to ask. */
export function answered(response: Response) {
  if (response.status === 401) window.location.reload()
  else if (response.ok && !session.user) void ask()
}

/** Drops the token's cookie and starts again, signed out. */
export async function signOut() {
  await fetch("/api/logout", { method: "POST" }).catch(() => null)
  window.location.reload()
}

/** Signs in with the token of the link the runtime printed (#token=…, which the browser never sends anywhere),
 * taking it out of the address first, as Jupyter's link works; then asks who the page is. Null when signed in, or
 * when the runtime cannot be reached (the page says so itself); else how to sign in. */
export async function signIn(): Promise<Login | null> {
  const token = window.location.hash.match(/^#token=(.+)$/)?.[1]
  if (token) {
    history.replaceState(
      null,
      "",
      window.location.pathname + window.location.search
    )
    await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: decodeURIComponent(token) }),
      signal: AbortSignal.timeout(WAIT),
    }).catch(() => null)
  }
  return ask()
}
