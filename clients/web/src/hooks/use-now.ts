import { useEffect, useState } from "react"

/**
 * The time now in seconds, kept current every so often (each second unless said) while enabled: on the clock's whole
 * seconds, so every clock on the page turns over together.
 */
export function useNow(enabled: boolean, every = 1000) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    if (!enabled) return
    let timer = 0
    const next = () => {
      timer = window.setTimeout(
        () => {
          setNow(Date.now() / 1000)
          next()
        },
        every - (Date.now() % every)
      )
    }
    next()
    return () => window.clearTimeout(timer)
  }, [enabled, every])
  return now
}
