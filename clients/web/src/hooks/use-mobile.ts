import * as React from "react"

const MOBILE_BREAKPOINT = 768
const QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

// One list for the page, made on first use: every render reads it, and making one per read is wasted work.
let list: MediaQueryList | undefined
const media = () => (list ??= window.matchMedia(QUERY))

function subscribe(onChange: () => void) {
  media().addEventListener("change", onChange)
  return () => media().removeEventListener("change", onChange)
}

export function useIsMobile() {
  return React.useSyncExternalStore(subscribe, () => media().matches)
}
