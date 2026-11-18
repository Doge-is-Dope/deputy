import { store } from "@/lib/store"
import { en } from "@/locales/en"
import { zhHant, type Messages } from "@/locales/zh-Hant"

// The interface's language: 繁體中文, the one it was written in, unless 設定 > 一般 chose another or the browser's
// ("auto"), which this browser keeps.
// Components read its words with useT, which re-renders them when it changes; code outside components reads them
// with t(), at the time it runs.

const MESSAGES = { "zh-Hant": zhHant, en } satisfies Record<string, Messages>

type Locale = keyof typeof MESSAGES

/** A word in every language the interface has, so a search finds it in any of them whichever is shown. */
export const everyLanguage = (word: (messages: Messages) => string) =>
  Object.values(MESSAGES).map(word)
export type Language = "auto" | Locale

/** The languages to choose from, each named in itself. */
export const LANGUAGES: { id: Locale; name: string }[] = [
  { id: "zh-Hant", name: "繁體中文" },
  { id: "en", name: "English" },
]

const KEY = "language"

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

/** The language chosen and the one it comes to, put on <html>. */
function applied(language: Language) {
  const locale = language === "auto" ? detect() : language
  document.documentElement.lang = locale
  return { language, locale }
}

const chosen = store(applied(stored()))
// The browser's language can change while the page is open; it matters only while it is the choice.
addEventListener("languagechange", () => {
  if (chosen.get().language === "auto") chosen.set(applied("auto"))
})
// A choice made in another tab applies here too.
addEventListener("storage", (event) => {
  if (event.key === KEY || event.key === null) chosen.set(applied(stored()))
})

export function setLanguage(language: Language) {
  try {
    if (language === "zh-Hant") localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, language)
  } catch {
    // Not stored; the choice still holds until the page reloads.
  }
  chosen.set(applied(language))
}

/** The language chosen and the one it comes to. */
export const useLanguage = chosen.use

/** The interface's words, in its language now. */
export function useT(): Messages {
  return MESSAGES[useLanguage().locale]
}

/** The same, for code outside components: as of when it runs. */
export const t = (): Messages => MESSAGES[chosen.get().locale]

/** The interface's language as of when it runs, for Intl to say dates and times in. */
export const locale = (): Locale => chosen.get().locale
