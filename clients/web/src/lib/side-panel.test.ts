import { describe, expect, it } from "vitest"

import { EMPTY, applied, type Mark } from "@/lib/markup"
import {
  CLOSED,
  COMPUTER,
  answered,
  closedFile,
  forgotten,
  getPanel,
  keyOf,
  markedTile,
  openFile,
  setMarkup,
  setPanelOpen,
  showComputer,
  left,
  marked,
  opened,
  removed,
  shownFiles,
  shownTab,
  switched,
  tilesGone,
  type Panel,
  type Source,
} from "@/lib/side-panel"

const sent = (file: string, run = "r1"): Source => ({
  kind: "sent",
  run,
  file,
  name: file,
})
const draft = (key: string, of = "t1"): Source => ({
  kind: "draft",
  draft: of,
  key,
  name: `${key}.png`,
})
const line: Mark = {
  id: "m",
  kind: "rect",
  color: "red",
  from: [0, 0],
  to: [9, 9],
}
const drawn = applied(EMPTY, [line])
const openAll = (panel: Panel, source: Source) => opened(panel, source)
const keys = (panel: Panel) => panel.files.map((each) => each.key)

describe("opened", () => {
  it("adds a tab, chooses it and opens the panel", () => {
    const panel = opened(CLOSED, sent("a.png"))
    expect(panel.open).toBe(true)
    expect(panel.tab).toBe(keyOf(sent("a.png")))
    expect(keys(panel)).toEqual([keyOf(sent("a.png"))])
  })

  it("only shows a tab that is open already", () => {
    const once = opened(opened(CLOSED, sent("a.png")), sent("b.png"))
    const twice = opened(once, sent("a.png"))
    expect(keys(twice)).toEqual(keys(once))
    expect(twice.tab).toBe(keyOf(sent("a.png")))
  })

  it("keeps what was drawn on the others", () => {
    const a = keyOf(sent("a.png"))
    const panel = opened(
      marked(opened(CLOSED, sent("a.png")), a, drawn),
      sent("b.png")
    )
    expect(panel.files[0].markup).toBe(drawn)
  })
})

describe("closing a tab", () => {
  const three = [sent("a.png"), sent("b.png"), sent("c.png")].reduce(
    openAll,
    CLOSED
  )
  const [a, b, c] = keys(three)

  it("chooses the one to its right, else its left, else the computer", () => {
    const chosen = { ...three, tab: b }
    expect(closedFile(chosen, b, keys(chosen)).tab).toBe(c)
    expect(closedFile({ ...three, tab: c }, c, [a, b, c]).tab).toBe(b)
    const one = opened(CLOSED, sent("a.png"))
    expect(closedFile(one, a, [a]).tab).toBe(COMPUTER)
  })

  it("keeps the chosen tab when another closes", () => {
    expect(closedFile({ ...three, tab: a }, c, [a, b, c]).tab).toBe(a)
  })

  it("asks first when it holds markup, and does as answered", () => {
    const asked = closedFile(marked(three, b, drawn), b, [a, b, c])
    expect(asked.confirm).toEqual({ key: b, then: "close" })
    expect(keys(asked)).toEqual([a, b, c])
    const kept = answered(asked, false, [a, b, c])
    expect(kept.confirm).toBeNull()
    expect(kept.files[1].markup).toBe(drawn)
    const gone = answered(asked, true, [a, b, c])
    expect(keys(gone)).toEqual([a, c])
    expect(gone.confirm).toBeNull()
  })

  it("closes an empty markup without asking", () => {
    expect(keys(closedFile(marked(three, b, EMPTY), b, [a, b, c]))).toEqual([
      a,
      c,
    ])
  })

  it("asks first while a comment's words are typed and not kept", () => {
    const typing = {
      ...marked(three, b, EMPTY),
      files: marked(three, b, EMPTY).files.map((each) =>
        each.key === b ? { ...each, writing: true } : each
      ),
    }
    expect(closedFile(typing, b, [a, b, c]).confirm).toEqual({
      key: b,
      then: "close",
    })
  })
})

describe("leaving markup", () => {
  const a = keyOf(sent("a.png"))
  const one = opened(CLOSED, sent("a.png"))

  it("leaves an empty one at once", () => {
    expect(left(marked(one, a, EMPTY), a).files[0].markup).toBeNull()
  })

  it("asks when something is drawn, and keeps the tab either way", () => {
    const asked = left(marked(one, a, drawn), a)
    expect(asked.confirm).toEqual({ key: a, then: "leave" })
    const gone = answered(asked, true, [a])
    expect(keys(gone)).toEqual([a])
    expect(gone.files[0].markup).toBeNull()
  })
})

describe("the computer and the panel", () => {
  const a = keyOf(sent("a.png"))
  const panel = marked(opened(CLOSED, sent("a.png")), a, drawn)

  it("keeps the tabs and their markup when the computer is shown or the panel closes", () => {
    const kept = keyOf(sent("kept.png", "r7"))
    const tab = () => getPanel().files.find((each) => each.key === kept)
    openFile(sent("kept.png", "r7"))
    setMarkup(kept, drawn)
    showComputer()
    expect(getPanel().tab).toBe(COMPUTER)
    expect(tab()?.markup).toBe(drawn)
    setPanelOpen(false)
    expect(getPanel().open).toBe(false)
    expect(tab()?.markup).toBe(drawn)
  })

  it("removes a tile's tab without asking", () => {
    const tile = keyOf(draft("k"))
    const both = opened(panel, draft("k"))
    expect(keys(removed(both, tile, keys(both)))).toEqual([a])
  })
})

describe("tiles sent or removed", () => {
  // Another conversation's tab, out of sight, between this one's.
  const panel = [
    sent("a.png", "r1"),
    draft("k", "t1"),
    sent("b.png", "r9"),
    draft("j", "t1"),
    draft("i", "t1"),
  ].reduce(openAll, CLOSED)
  const [a, k, , j, i] = keys(panel)
  const shown = [a, k, j, i]

  it("give way to the next tab in view, not one out of sight", () => {
    expect(forgotten({ ...panel, tab: k }, new Set([k]), shown).tab).toBe(j)
  })

  it("skip the others going with them", () => {
    const after = forgotten({ ...panel, tab: k }, new Set([k, j]), shown)
    expect(after.tab).toBe(i)
    expect(keys(after)).toEqual([a, keyOf(sent("b.png", "r9")), i])
    expect(forgotten({ ...panel, tab: j }, new Set([j, i]), shown).tab).toBe(k)
  })

  it("show the computer where none stays, or none was in view", () => {
    expect(
      forgotten({ ...panel, tab: k }, new Set([a, k, j, i]), shown).tab
    ).toBe(COMPUTER)
    expect(forgotten({ ...panel, tab: k }, new Set([k]), []).tab).toBe(COMPUTER)
  })

  it("close the panel when sent from under the tab in view, not when removed or sent from behind it", () => {
    const open = { ...panel, open: true, tab: k }
    const sentAway = tilesGone(open, new Set(["k"]), true, shown)
    expect(sentAway.open).toBe(false)
    expect(keys(sentAway)).not.toContain(k)
    expect(tilesGone(open, new Set(["k"]), false, shown)).toMatchObject({
      open: true,
      tab: j,
    })
    expect(
      tilesGone({ ...open, tab: a }, new Set(["k"]), true, shown)
    ).toMatchObject({ open: true, tab: a })
  })

  it("take the tab of a message's picture with its marked-up copy, once sent", () => {
    const copied = { ...panel, open: true, tab: a, copies: { [a]: "c" } }
    const sentAway = tilesGone(copied, new Set(["c"]), true, shown)
    expect(keys(sentAway)).not.toContain(a)
    expect(sentAway.open).toBe(false)
    expect(tilesGone(copied, new Set(["c"]), false, shown)).toBe(copied)
  })
})

describe("what a conversation shows", () => {
  const panel = [
    sent("a.png", "r1"),
    sent("b.png", "r9"),
    draft("k", "t1"),
    draft("j", "t2"),
  ].reduce(openAll, CLOSED)

  it("shows its messages' attachments and its own draft's tiles", () => {
    expect(shownFiles(panel, ["r1"], "t1").map((each) => each.key)).toEqual([
      keyOf(sent("a.png", "r1")),
      keyOf(draft("k", "t1")),
    ])
  })

  it("shows the computer while the chosen tab is another conversation's", () => {
    const shown = shownFiles(panel, ["r1"], "t1")
    expect(shownTab({ ...panel, tab: keyOf(draft("j", "t2")) }, shown)).toBe(
      COMPUTER
    )
    expect(shownTab({ ...panel, tab: keyOf(sent("a.png", "r1")) }, shown)).toBe(
      keyOf(sent("a.png", "r1"))
    )
  })
})

describe("markedTile", () => {
  it("names the tab of a tile going out with marks not put on it", () => {
    openFile(draft("tile", "t9"))
    expect(markedTile(["tile"])).toBeNull()
    setMarkup(keyOf(draft("tile", "t9")), drawn)
    expect(markedTile(["other"])).toBeNull()
    expect(markedTile(["tile"])).toBe(keyOf(draft("tile", "t9")))
  })
})

describe("switching conversations", () => {
  it("restores the selected tab and keeps edits when another conversation opens a file", () => {
    const first = sent("a.png")
    const second = draft("second", "t2")
    const a = marked(opened(switched(CLOSED, "t1"), first), keyOf(first), drawn)
    const b = opened(switched(a, "t2"), second)
    const shown = shownFiles(b, ["r1"], "t1")
    expect(shownTab(b, shown, "t1")).toBe(keyOf(first))
    expect(switched(b, "t1").tab).toBe(keyOf(first))
    expect(switched(b, "t1").files[0].markup).toBe(drawn)
  })
})
