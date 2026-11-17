import { useState, type RefObject } from "react"

import { ChevronDownIcon } from "@/components/icons"
import { ConversationMenuItems } from "@/components/sidebar/conversation-item"
import type { ConversationEdits } from "@/components/sidebar/app-sidebar"
import { NameField } from "@/components/sidebar/name-field"
import { useRename } from "@/hooks/use-rename"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { Conversation } from "@/lib/api"
import { nameOf } from "@/lib/conversations"
import { useT } from "@/lib/i18n"

/** The open conversation's name in the header, which opens its menu: the sidebar row's, renaming it in place here.
 * While it runs it is only its name, as its row then has no menu. */
export function TitleMenu({
  conversation,
  running,
  edits,
  onRename,
}: {
  conversation: Conversation
  running: boolean
  edits: RefObject<ConversationEdits | null>
  onRename: (id: string, title: string) => Promise<{ title: string } | null>
}) {
  const t = useT()
  const { draft, setDraft, title, start, cancel, commit } = useRename(
    conversation,
    onRename
  )
  const name = title ?? nameOf(conversation)
  // The sidebar's edits as the menu opened.
  const [menu, setMenu] = useState<ConversationEdits | null>(null)

  // As wide as the name being typed, its words where the button's were: a hidden copy of it sizes the field. The
  // button has no border, so its words are on the 16 column of the header buttons' icons.
  if (draft !== null)
    return (
      <div className="relative min-w-0 text-sm font-medium">
        <span
          aria-hidden
          className="invisible block h-9 overflow-hidden px-2 whitespace-pre"
        >
          {draft}{" "}
        </span>
        <NameField
          value={draft}
          label={t.sidebar.renameConversation}
          onChange={setDraft}
          onSave={commit}
          onCancel={cancel}
          className="absolute inset-0 rounded-lg bg-muted px-2 outline-none"
        />
      </div>
    )
  if (running)
    return <h1 className="min-w-0 truncate px-2 text-sm font-medium">{name}</h1>
  return (
    <DropdownMenu
      onOpenChange={(open) => {
        if (open) setMenu(edits.current)
      }}
    >
      <h1 className="flex min-w-0">
        <DropdownMenuTrigger
          render={
            <Button variant="ghost" className="min-w-0 gap-1.5 border-0 px-2" />
          }
        >
          <span className="truncate">{name}</span>
          <ChevronDownIcon className="size-4 text-muted-foreground" />
        </DropdownMenuTrigger>
      </h1>
      {/* No focus back to the button (finalFocus): the rename field takes its place. */}
      <DropdownMenuContent align="start" finalFocus={false}>
        {menu && (
          <ConversationMenuItems
            conversation={conversation}
            projects={menu.projects}
            onRename={start}
            onDelete={menu.remove}
            onMove={menu.move}
            onNewProject={menu.bringIn}
          />
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
