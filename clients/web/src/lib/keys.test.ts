import { afterEach, describe, expect, it, vi } from "vitest"

async function keysOn(platform: string) {
  vi.resetModules()
  vi.stubGlobal("navigator", { platform })
  return import("@/lib/keys")
}

const press = (init: Partial<KeyboardEvent>) =>
  ({
    key: "",
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    ...init,
  }) as KeyboardEvent

afterEach(() => vi.unstubAllGlobals())

describe("Shortcut", () => {
  it("reads, names and matches ⌘ shortcuts on a Mac", async () => {
    const { shortcutLabel, shortcutAria, isShortcut } = await keysOn("MacIntel")
    const open = { key: "o", shift: true }
    expect(shortcutLabel(open)).toBe("⇧ ⌘ O")
    expect(shortcutAria(open)).toBe("Meta+Shift+O")
    expect(shortcutLabel({ key: "," })).toBe("⌘ ,")
    expect(
      isShortcut(press({ key: "O", metaKey: true, shiftKey: true }), open)
    ).toBe(true)
    expect(
      isShortcut(press({ key: "o", ctrlKey: true, shiftKey: true }), open)
    ).toBe(false)
    expect(isShortcut(press({ key: "o", metaKey: true }), open)).toBe(false)
    expect(
      isShortcut(press({ key: ",", metaKey: true, altKey: true }), { key: "," })
    ).toBe(false)
  })

  it("uses Ctrl elsewhere", async () => {
    const { shortcutLabel, shortcutAria, isShortcut } = await keysOn("Win32")
    expect(shortcutLabel({ key: "o", shift: true })).toBe("Ctrl Shift O")
    expect(shortcutAria({ key: "b" })).toBe("Control+B")
    expect(isShortcut(press({ key: "b", ctrlKey: true }), { key: "b" })).toBe(
      true
    )
    expect(isShortcut(press({ key: "b", metaKey: true }), { key: "b" })).toBe(
      false
    )
  })
})
