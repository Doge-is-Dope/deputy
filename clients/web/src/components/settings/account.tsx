import { CopyButton } from "@/components/copy-button"
import { UserAvatar } from "@/components/sidebar/user-avatar"
import { Button } from "@/components/ui/button"
import { useT } from "@/lib/i18n"
import { signOut, useSession } from "@/lib/session"
import { Card, Row, Section } from "@/components/settings/layout"

/** Who the page is signed in as and how, as the runtime said (runtime/src/computer_use/auth); signing out where the
 * page can. Nothing here is kept: the runtime is asked each time the page starts. */
export function Account() {
  const t = useT()
  const { user, login } = useSession()
  if (!user) return null
  return (
    <Section>
      <Card>
        {/* Their circle as the sidebar draws it, a size up, with their name and how they signed in. */}
        <div className="flex items-center gap-4 py-5">
          <UserAvatar id={user.id} className="size-12 shrink-0" />
          <div className="min-w-0">
            <div className="truncate text-base font-medium">{user.name}</div>
            <div className="truncate text-muted-foreground">
              {login === "proxy"
                ? t.settings.signInProxy
                : login === "token"
                  ? t.settings.signInToken
                  : t.settings.signInNone}
            </div>
          </div>
        </div>
        <Row label={t.settings.userId}>
          <span className="flex items-center justify-end gap-1">
            <span className="font-mono text-xs break-all select-all">
              {user.id}
            </span>
            <CopyButton text={user.id} />
          </span>
        </Row>
        {login === "token" && (
          <Row label={t.sidebar.signOut}>
            <Button variant="outline" size="sm" onClick={() => void signOut()}>
              {t.sidebar.signOut}
            </Button>
          </Row>
        )}
      </Card>
    </Section>
  )
}
