import { useLayoutEffect, useRef, type CSSProperties } from "react"
import { Toaster as Sonner, type ToasterProps } from "sonner"

import { useAppearance } from "@/lib/appearance"

/** Use the app theme and font. Stack up to three notices for 3 seconds;
 * expand and pause on interaction, dismiss by swiping sideways. Merge caller styles. */
function Toaster({ style, ...props }: ToasterProps) {
  const { resolved } = useAppearance()
  const root = useRef<HTMLElement>(null)
  useLayoutEffect(() => {
    const element = root.current
    if (!element) return
    // Sonner's bottom stack puts the newest notice below older ones. Keep that stack at the top of the viewport,
    // using Sonner's own measured heights and offsets so wrapped text and expanding both stay within the viewport.
    const place = () => {
      const list = element.querySelector<HTMLOListElement>(
        "[data-sonner-toaster]"
      )
      if (!list) return
      const notices = Array.from(
        list.querySelectorAll<HTMLElement>(
          '[data-sonner-toast][data-visible="true"]'
        )
      ).filter((notice) => notice.dataset.removed !== "true")
      // Use Sonner's drag distance; fade only our surface so its swipe-out animation continues from this opacity.
      for (const notice of notices) {
        const distance = Math.abs(
          parseFloat(notice.style.getPropertyValue("--swipe-amount-x")) || 0
        )
        const opacity = String(Math.max(0, 1 - distance / 160))
        if (
          notice.style.getPropertyValue("--notice-swipe-opacity") !== opacity
        ) {
          notice.style.setProperty("--notice-swipe-opacity", opacity)
        }
      }
      const height = (notice: HTMLElement) =>
        parseFloat(notice.style.getPropertyValue("--initial-height")) ||
        notice.offsetHeight
      const gap = parseFloat(list.style.getPropertyValue("--gap")) || 0
      const stackHeight = notices.some(
        (notice) => notice.dataset.expanded === "true"
      )
        ? Math.max(
            0,
            ...notices.map(
              (notice) =>
                (parseFloat(notice.style.getPropertyValue("--offset")) || 0) +
                height(notice)
            )
          )
        : notices.length
          ? height(notices[0]) + (notices.length - 1) * gap
          : 0
      const value = `${stackHeight}px`
      if (list.style.getPropertyValue("--notice-stack-height") !== value) {
        list.style.setProperty("--notice-stack-height", value)
      }
    }
    const observer = new MutationObserver(place)
    observer.observe(element, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: [
        "style",
        "data-expanded",
        "data-visible",
        "data-removed",
      ],
    })
    place()
    return () => observer.disconnect()
  }, [])
  return (
    <Sonner
      ref={root}
      theme={resolved}
      className="toaster group"
      duration={3000}
      visibleToasts={3}
      gap={12}
      swipeDirections={["left", "right"]}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)",
          fontFamily: "inherit",
          ...style,
        } as CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
