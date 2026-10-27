import { useT } from "@/lib/i18n"
import type { Login } from "@/lib/session"

/** The page while the runtime turns it away: where to sign in, in a line, with nothing to fill in. */
export function SignedOut({ login }: { login: Login }) {
  const t = useT()
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-2 bg-background px-4 text-center">
      <h1 className="text-base font-medium">
        {login === "proxy" ? t.signedOut.proxy : t.signedOut.token}
      </h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        {login === "proxy" ? t.signedOut.proxyHow : t.signedOut.tokenHow}
      </p>
    </main>
  )
}
