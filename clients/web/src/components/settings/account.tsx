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
        <Row label={t.settings.accountName}>{user.name}</Row>
        <Row label={t.settings.signInMethod}>
          {login === "proxy"
            ? t.settings.signInProxy
            : login === "token"
              ? t.settings.signInToken
              : t.settings.signInNone}
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
