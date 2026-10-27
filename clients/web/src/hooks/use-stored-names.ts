import { useEffect, useState } from "react"

/** A list of project names kept in this browser under `key`; a browser that keeps nothing keeps it for the visit. Set
 * one name in or out, or the whole list. */
export function useStoredNames(key: string) {
  const [names, setNames] = useState<string[]>(() => {
    try {
      const stored: unknown = JSON.parse(localStorage.getItem(key) ?? "[]")
      return Array.isArray(stored)
        ? stored.filter((item) => typeof item === "string")
        : []
    } catch {
      return []
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(names))
    } catch {
      // Not stored: the list still holds until the page reloads.
    }
  }, [key, names])
  const put = (name: string, included: boolean) =>
    setNames((list) =>
      included
        ? list.includes(name)
          ? list
          : [...list, name]
        : list.filter((item) => item !== name)
    )
  return [names, put, setNames] as const
}
