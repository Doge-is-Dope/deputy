import { useRef, useState, type ComponentType, type SVGProps } from "react"
import { cn } from "cn"

import {
  GearIcon,
  MonitorIcon,
  PersonIcon,
  ShieldCheckIcon,
  SparkleIcon,
  SunIcon,
} from "@/components/icons"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { type Status } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { General } from "@/components/settings/general"
import { Appearance } from "@/components/settings/appearance"
import { Desktop } from "@/components/settings/desktop"
import { Model } from "@/components/settings/model"
import { Permissions } from "@/components/settings/permissions"
import { Account } from "@/components/settings/account"

type Page =
  "general" | "appearance" | "desktop" | "model" | "permissions" | "account"

// What this browser keeps, then what the runtime runs with, in one list as ChatGPT's and Claude's settings menus are.
// Pages are named in the interface's language. A page is its entry here: its icon, and what it shows.
const PAGES: {
  id: Page
  icon: ComponentType<SVGProps<SVGSVGElement>>
  Content: ComponentType<{ status: Status | null; offline: boolean }>
}[] = [
  { id: "general", icon: GearIcon, Content: General },
  { id: "appearance", icon: SunIcon, Content: Appearance },
  { id: "desktop", icon: MonitorIcon, Content: Desktop },
  { id: "account", icon: PersonIcon, Content: Account },
  { id: "model", icon: SparkleIcon, Content: Model },
  { id: "permissions", icon: ShieldCheckIcon, Content: Permissions },
]

/** Browser settings for language, appearance, models and approvals.
 * Runtime connections are read-only. */
export function SettingsDialog({
  open,
  onOpenChange,
  status,
  offline,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  status: Status | null
  offline: boolean
}) {
  const t = useT()
  const [page, setPage] = useState<Page>("general")
  const { Content } = PAGES.find(({ id }) => id === page)!
  // Opened, the focus is on the window itself rather than its first page, so no page shows a focus ring before the
  // user moves to one; Tab goes on from there.
  const popup = useRef<HTMLDivElement>(null)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={popup}
        initialFocus={popup}
        className="flex h-[min(40rem,calc(100dvh-2rem))] flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl md:flex-row"
      >
        <aside className="flex shrink-0 flex-col gap-3 border-b p-3 md:w-52 md:gap-2 md:border-r md:border-b-0 md:bg-sidebar">
          <DialogTitle className="flex h-8 items-center px-2">
            {t.settings.title}
          </DialogTitle>
          {/* On a narrow screen the pages scroll sideways in a row, with no scrollbar track under them (Windows keeps
              one in view). */}
          <nav
            aria-label={t.settings.pages}
            className="-mx-3 flex [scrollbar-width:none] gap-1 overflow-x-auto px-3 md:mx-0 md:flex-col md:gap-0.5 md:overflow-visible md:px-0"
          >
            {PAGES.map(({ id, icon: Icon }) => (
              <button
                key={id}
                type="button"
                aria-current={id === page ? "page" : undefined}
                onClick={() => setPage(id)}
                className={cn(
                  "flex h-8 shrink-0 items-center gap-2 rounded-md px-2.5 outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring md:h-9 md:px-2",
                  id === page && "bg-sidebar-accent"
                )}
              >
                <Icon className="size-4 shrink-0" />
                {t.settings[id]}
              </button>
            ))}
          </nav>
        </aside>

        <main className="min-h-0 flex-1 overflow-y-auto bg-background px-5 pt-6 pb-10 md:px-8 md:pt-12">
          <h2 className="text-xl tracking-tight md:text-2xl">
            {t.settings[page]}
          </h2>
          <Content status={status} offline={offline} />
        </main>
      </DialogContent>
    </Dialog>
  )
}
