import { useState } from "react"

import { useFlash } from "@/hooks/use-flash"

const COPIED_MS = 2000

/** Puts `text` on the clipboard. A page opened over plain HTTP on another address has no navigator.clipboard, so
 * there it goes through the copy event the click may still raise; false if neither could. */
async function written(text: string): Promise<boolean> {
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Refused; the copy event may still be let through.
    }
  }
  let put = false
  const take = (event: ClipboardEvent) => {
    event.clipboardData?.setData("text/plain", text)
    event.preventDefault()
    put = true
  }
  document.addEventListener("copy", take)
  try {
    document.execCommand("copy")
  } finally {
    document.removeEventListener("copy", take)
  }
  return put
}

/**
 * Copies a report for the user to send on: says so for a moment once it is copied, and where the browser won't let
 * the page copy at all, keeps the text to show for copying by hand.
 */
export function useCopy() {
  const [copied, setCopied] = useFlash<true>(COPIED_MS)
  const [manual, setManual] = useState<string | null>(null)

  async function copy(text: string) {
    if (await written(text)) setCopied(true)
    else setManual(text)
  }

  return { copied: copied === true, manual, copy }
}
