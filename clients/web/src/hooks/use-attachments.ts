import {
  useEffect,
  useEffectEvent,
  useState,
  useSyncExternalStore,
} from "react"

import { showError } from "@/components/notice"
import { editDraft } from "@/hooks/use-drafts"
import { useT } from "@/lib/i18n"
import {
  MAX_FILES,
  failure,
  isPhoto,
  refused,
  thumbnail,
  unique,
  uploaded,
  type Attachment,
} from "@/lib/attachments"
import { withComments } from "@/lib/markup"
import { forgetTiles } from "@/lib/side-panel"
import { store } from "@/lib/store"

const KEY = "draft-attachments"

/** What is attached to each conversation's message being written (use-drafts' keys), kept as its words are: for this
 * tab, so switching conversations or reloading the page leaves them where they were. Only what has uploaded is stored:
 * one still on its way when the page reloads is gone. */
const attached = store<Record<string, Attachment[]>>(
  (() => {
    try {
      const stored = JSON.parse(sessionStorage.getItem(KEY) ?? "{}")
      return stored && typeof stored === "object" ? stored : {}
    } catch {
      return {}
    }
  })()
)
// The files themselves, to send again after a failure: for this visit only.
const files = new Map<string, File>()

function edit(draft: string, change: (list: Attachment[]) => Attachment[]) {
  const all = { ...attached.get() }
  const list = change(all[draft] ?? [])
  if (list.length) all[draft] = list
  else delete all[draft]
  attached.set(all)
  const kept: Record<string, Attachment[]> = {}
  for (const [key, each] of Object.entries(all)) {
    const ready = each.filter((one) => one.state === "ready")
    if (ready.length) kept[key] = ready
  }
  try {
    sessionStorage.setItem(KEY, JSON.stringify(kept))
  } catch {
    // Not stored; they still hold until the page reloads.
  }
}

/** What is attached to the message being written in `draft`'s composer: each file uploads as soon as it is added. */
export function useAttachments(draft: string) {
  const t = useT()
  const list =
    useSyncExternalStore(attached.subscribe, attached.get)[draft] ?? []
  const update = (key: string, change: Partial<Attachment>) =>
    edit(draft, (all) =>
      all.map((each) => (each.key === key ? { ...each, ...change } : each))
    )

  // A failure is said once, in a notice; the tile stays, with a way to try again only where that can help.
  function send(key: string, file: File) {
    update(key, { state: "uploading" })
    uploaded(file).then(
      (id) => update(key, { id, state: "ready" }),
      (error: unknown) => {
        const why = failure(error)
        const words = t.composer.attachments
        if (why === "failed") {
          showError(words.failed(file.name))
          update(key, { state: "failed" })
          return
        }
        showError(why === "size" ? words.size : words.unreadable(file.name))
        update(key, { state: "rejected" })
      }
    )
  }

  // A tile for the file, as it starts to upload; its preview comes once made.
  function taken(file: File, key: string = crypto.randomUUID()): Attachment {
    files.set(key, file)
    const image = isPhoto(file.type)
    if (image)
      thumbnail(file).then(
        (preview) => update(key, { preview }),
        () => {} // a file that is no image after all: its tile stays plain
      )
    return {
      key,
      name: file.name,
      kind: image ? "image" : "file",
      preview: null,
      id: null,
      state: "uploading",
    }
  }

  // Under a name no other tile has, numbered as the model would get it (unique), so its name on the tile is the one
  // the model gets, and a picture's comments in the message are labelled by it.
  function named(file: File, others: Attachment[]) {
    const name = unique(file.name, new Set(others.map((each) => each.name)))
    return name === file.name
      ? file
      : new File([file], name, {
          type: file.type,
          lastModified: file.lastModified,
        })
  }

  /** Files added as tiles, after those there: the tiles they became. */
  function add(picked: File[]) {
    const room = MAX_FILES - list.length
    if (picked.length > room) showError(t.composer.attachments.many(MAX_FILES))
    const added: Attachment[] = []
    for (const file of picked.slice(0, Math.max(0, room))) {
      if (refused(file)) {
        showError(t.composer.attachments.size)
        continue
      }
      added.push(taken(named(file, [...list, ...added])))
    }
    edit(draft, (all) => [...all, ...added])
    for (const each of added) send(each.key, files.get(each.key)!)
    return added
  }

  /** The tile's file changed for another (its marked-up copy), in its place and under its key, so what shows it goes
   * on showing it: the tile it became. */
  function replace(key: string, file: File) {
    const tile = taken(
      named(
        file,
        list.filter((each) => each.key !== key)
      ),
      key
    )
    edit(draft, (all) => all.map((each) => (each.key === key ? tile : each)))
    send(key, files.get(key)!)
    return tile
  }

  function remove(key: string) {
    const tile = attached.get()[draft]?.find((each) => each.key === key)
    if (tile?.kind === "image")
      editDraft(draft, (text) => withComments(text, [], tile.name))
    files.delete(key)
    forgetTiles([key])
    edit(draft, (all) => all.filter((each) => each.key !== key))
  }

  return {
    list,
    add,
    replace,
    remove,
    retry: (key: string) => send(key, files.get(key)!),
    // Only what a message took: a file added while it was being sent stays for the next.
    clear: (sent: readonly Attachment[]) => {
      const keys = new Set(sent.map((each) => each.key))
      for (const key of keys) files.delete(key)
      forgetTiles(keys, true)
      edit(draft, (all) => all.filter((each) => !keys.has(each.key)))
    },
    // Every file is uploaded: the message can go with them.
    ready: list.every((each) => each.state === "ready"),
  }
}

/** What was dropped: its files, and whether a folder was among them. */
function dropped(data: DataTransfer) {
  const files: File[] = []
  let folder = false
  for (const item of data.items) {
    if (item.kind !== "file") continue
    if (item.webkitGetAsEntry()?.isDirectory) folder = true
    else {
      const file = item.getAsFile()
      if (file) files.push(file)
    }
  }
  return { files, folder }
}

/** Files dragged over the page: dropped anywhere, they are attached while `enabled`; never opened in place of the app.
 * A folder cannot be: it is left out, with a notice. Whether files are over the page now, to show where they would go. */
export function useFileDrop(
  enabled: boolean,
  onFiles: (files: File[]) => void
) {
  const t = useT()
  const [over, setOver] = useState(false)
  const take = useEffectEvent((data: DataTransfer) => {
    const { files, folder } = dropped(data)
    if (folder) showError(t.composer.attachments.folder)
    if (files.length) onFiles(files)
  })
  useEffect(() => {
    // Entering a child fires before leaving its parent: over the page while more were entered than left.
    let depth = 0
    const files = (event: DragEvent) =>
      event.dataTransfer?.types.includes("Files") ?? false
    const enter = (event: DragEvent) => {
      if (!files(event)) return
      depth += 1
      setOver(true)
    }
    const leave = (event: DragEvent) => {
      if (!files(event)) return
      depth = Math.max(0, depth - 1)
      if (depth === 0) setOver(false)
    }
    const hover = (event: DragEvent) => {
      if (!files(event)) return
      event.preventDefault()
      event.dataTransfer!.dropEffect = enabled ? "copy" : "none"
    }
    const drop = (event: DragEvent) => {
      if (!files(event)) return
      event.preventDefault()
      depth = 0
      setOver(false)
      if (enabled) take(event.dataTransfer!)
    }
    window.addEventListener("dragenter", enter)
    window.addEventListener("dragleave", leave)
    window.addEventListener("dragover", hover)
    window.addEventListener("drop", drop)
    return () => {
      window.removeEventListener("dragenter", enter)
      window.removeEventListener("dragleave", leave)
      window.removeEventListener("dragover", hover)
      window.removeEventListener("drop", drop)
    }
  }, [enabled])
  return enabled && over
}
