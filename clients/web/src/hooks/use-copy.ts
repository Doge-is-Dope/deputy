import { useState } from "react"

import { useFlash } from "@/hooks/use-flash"

const COPIED_MS = 2000

/**
 * Copies a report for the user to send on: says so for a moment once it is copied, and where the browser won't let
 * the page copy (a page not on HTTPS or localhost), keeps the text to show for copying by hand.
 */
export function useCopy() {
  const [copied, setCopied] = useFlash<true>(COPIED_MS)
  const [manual, setManual] = useState<string | null>(null)

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      setManual(text)
    }
  }

  return { copied: copied === true, manual, copy }
}
