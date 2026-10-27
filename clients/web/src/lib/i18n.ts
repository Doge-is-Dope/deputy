import { useSyncExternalStore } from "react"

import { en } from "@/locales/en"
import { zhHant, type Messages } from "@/locales/zh-Hant"

// The interface's language: 繁體中文, the one it was written in, unless 設定 > 一般 chose another or the browser's
// ("auto"), which this browser keeps.
// Components read its words with useT, which re-renders them when it changes; code outside components reads them
// with t(), at the time it runs.

const MESSAGES = { "zh-Hant": zhHant, en } satisfies Record<string, Messages>

export type Locale = keyof typeof MESSAGES
export type Language = "auto" | Locale

/** The languages to choose from, each named in itself. */
export const LANGUAGES: { id: Locale; name: string }[] = [
  { id: "zh-Hant", name: "繁體中文" },
  { id: "en", name: "English" },
]

const KEY = "language"
const listeners = new Set<() => void>()

/** The browser's first language that the interface has; English when it has none of them. */
function detect(): Locale {
  for (const tag of navigator.languages) {
    if (/^zh\b/i.test(tag)) return "zh-Hant"
    if (/^en\b/i.test(tag)) return "en"
  }
  return "en"
}

function stored(): Language {
  try {
    const language = localStorage.getItem(KEY)
    return language === "auto" || (language && language in MESSAGES)
      ? (language as Language)
      : "zh-Hant"
  } catch {
    return "zh-Hant"
  }
}

let state: { language: Language; locale: Locale }

function apply(language: Language) {
  const locale = language === "auto" ? detect() : language
  state = { language, locale }
  document.documentElement.lang = locale
  for (const listener of listeners) listener()
}

apply(stored())
// The browser's language can change while the page is open; it matters only while it is the choice.
addEventListener("languagechange", () => {
  if (state.language === "auto") apply("auto")
})
// A choice made in another tab applies here too.
addEventListener("storage", (event) => {
  if (event.key === KEY || event.key === null) apply(stored())
})

export function setLanguage(language: Language) {
  try {
    if (language === "zh-Hant") localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, language)
  } catch {
    // Not stored; the choice still holds until the page reloads.
  }
  apply(language)
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** The language chosen and the one it comes to. */
export function useLanguage() {
  return useSyncExternalStore(subscribe, () => state)
}

/** The interface's words, in its language now. */
export function useT(): Messages {
  return MESSAGES[useLanguage().locale]
}

/** The same, for code outside components: as of when it runs. */
export const t = (): Messages => MESSAGES[state.locale]

/** The interface's language as of when it runs, for Intl to say dates and times in. */
export const locale = (): Locale => state.locale
