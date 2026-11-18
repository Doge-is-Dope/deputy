import { describe, expect, it } from "vitest"

import {
  EMPTY,
  UNZOOMED,
  applied,
  constrained,
  held,
  markupName,
  redone,
  shapePath,
  sizesFor,
  strokePath,
  commentsIn,
  relabelled,
  withComments,
  drawnOf,
  undone,
  zoomedAt,
  type Mark,
} from "@/lib/markup"

const box: Mark = {
  id: "b",
  kind: "rect",
  color: "red",
  from: [10, 10],
  to: [20, 20],
}
const words: Mark = {
  id: "w",
  kind: "comment",
  at: [5, 5],
  text: "a",
}
const pen: Mark = {
  id: "p",
  kind: "pen",
  color: "red",
  points: [
    [0, 0, 0.5],
    [10, 5, 0.5],
    [20, 20, 0.5],
  ],
}

describe("undo and redo", () => {
  const one = applied(EMPTY, [box])
  const two = applied(one, [box, words])

  it("go back and forth through the gestures", () => {
    expect(undone(two).marks).toEqual([box])
    expect(undone(undone(two)).marks).toEqual([])
    expect(redone(undone(undone(two))).marks).toEqual([box])
    expect(redone(redone(undone(undone(two)))).marks).toEqual([box, words])
  })

  it("forget what was undone once something new is drawn", () => {
    const again = applied(undone(two), [box, pen])
    expect(again.future).toEqual([])
    expect(redone(again)).toBe(again)
  })

  it("leave nothing to undo as it is", () => {
    expect(undone(EMPTY)).toBe(EMPTY)
    expect(redone(EMPTY)).toBe(EMPTY)
  })
})

describe("sizes and paths", () => {
  it("scale with the image's long side", () => {
    const small = sizesFor(1000, 500)
    const large = sizesFor(500, 2000)
    expect(large.line).toBe(small.line * 2)
  })

  it("draw a stroke as one closed outline, the same each time", () => {
    const d = strokePath(pen.points, 4)
    expect(d).toMatch(/^M.*Z$/)
    expect(strokePath(pen.points, 4)).toBe(d)
    expect(strokePath([], 4)).toBe("")
  })

  it("round a rectangle's corners, however it was dragged, and no more than it can take", () => {
    const d = shapePath("rect", [100, 80], [0, 0], 4)
    expect(d.startsWith("M12 0H88A12 12 0 0 1 100 12")).toBe(true)
    expect(d.match(/A/g)).toHaveLength(4)
    expect(shapePath("rect", [0, 0], [10, 100], 4)).toContain("A5 5")
  })

  it("give an arrow its line and a head at its end", () => {
    const d = shapePath("arrow", [0, 0], [100, 0], 4)
    expect(d.startsWith("M0 0L100 0M")).toBe(true)
    expect(d.match(/L100 0/g)).toHaveLength(2)
  })
})

describe("constrained", () => {
  it("makes a rectangle or an ellipse as wide as it is tall, toward the pointer", () => {
    expect(constrained("rect", [10, 10], [40, 20])).toEqual([40, 40])
    expect(constrained("ellipse", [10, 10], [0, -30])).toEqual([-30, -30])
  })

  it("turns an arrow to the nearest 45°, as long as it was", () => {
    const [x, y] = constrained("arrow", [0, 0], [100, 10])
    expect(Math.round(x)).toBe(100)
    expect(Math.round(y)).toBe(0)
    const [dx, dy] = constrained("arrow", [0, 0], [50, 60])
    expect(Math.round(dx)).toBe(Math.round(dy))
  })
})

describe("comments", () => {
  // At x% and y% of the picture.
  const note = (id: string, x: number, y: number, text: string): Mark => ({
    id,
    kind: "comment",
    at: [x / 100, y / 100],
    text,
  })

  it("stay out of what is drawn into the picture", () => {
    expect(drawnOf([box, words, pen])).toEqual([box, pen])
  })

  it("go as the file's name and each numbered with where it is, in tenths of a percent", () => {
    const marks = [
      note("a", 73.125, 70, "改成儲存"),
      box,
      note("b", 17.5, 31, "加提示"),
    ]
    expect(withComments("看一下", marks, "登入畫面.png")).toBe(
      "看一下\n\n登入畫面.png：\n1. (x: 73.1%, y: 70.0%) 改成儲存\n2. (x: 17.5%, y: 31.0%) 加提示"
    )
  })

  it("are read back from the draft, the picture's last ones, as pins", () => {
    const draft =
      "a.png：\n1. (x: 1.0%, y: 1.0%) 舊的\n\nb.png：\n1. (x: 5.0%, y: 5.0%) 乙\n\na.png：\n1. (x: 10.0%, y: 20.0%) 一\n2. (x: 50.5%, y: 75.0%) 二 (x: 3%)\n謝謝"
    expect(
      commentsIn(draft, "a.png").map(({ at, text }) => [at, text])
    ).toEqual([
      [[0.1, 0.2], "一"],
      [[0.505, 0.75], "二 (x: 3%)"],
    ])
    expect(commentsIn(draft, "c.png")).toEqual([])
  })

  it("go in place of those read back, numbered again, whatever follows them", () => {
    const draft =
      "a.png：\n1. (x: 10.0%, y: 10.0%) 一\n2. (x: 20.0%, y: 20.0%) 二\n\nb.png：\n1. (x: 5.0%, y: 5.0%) 乙\n\n謝謝"
    expect(
      withComments(
        draft,
        [note("b", 20, 20, "二"), note("c", 50, 50, "三")],
        "a.png"
      )
    ).toBe(
      "a.png：\n1. (x: 20.0%, y: 20.0%) 二\n2. (x: 50.0%, y: 50.0%) 三\n\nb.png：\n1. (x: 5.0%, y: 5.0%) 乙\n\n謝謝"
    )
  })

  it("on more lines than one go on set in, and read back whole", () => {
    const marks = [note("a", 10, 10, "第一行\n第二行"), note("b", 50, 50, "二")]
    const draft = withComments("", marks, "a.png")
    expect(draft).toBe(
      "a.png：\n1. (x: 10.0%, y: 10.0%) 第一行\n   第二行\n2. (x: 50.0%, y: 50.0%) 二"
    )
    const back = commentsIn(draft, "a.png")
    expect(back.map(({ text }) => text)).toEqual(["第一行\n第二行", "二"])
    expect(withComments(draft, back.slice(1), "a.png")).toBe(
      "a.png：\n1. (x: 50.0%, y: 50.0%) 二"
    )
  })

  it("are read back as a hand may have retyped them", () => {
    const one = "1. (x: 10.0%, y: 20.0%) 一"
    for (const draft of [
      `a.png:\n${one}`, // a half-width colon
      `a.png ：  \n${one}`, // spaces around it
      `a.png：\n\n${one}`, // a blank line under the heading
      "a.png：\n1.(x:10%, y:20%)一", // spaces left out
    ])
      expect(commentsIn(draft, "a.png").map(({ text }) => text)).toEqual(["一"])
    const between = `a.png：\n${one}\n\n2. (x: 1.0%, y: 1.0%) 二\n\n謝謝`
    expect(withComments(between, commentsIn(between, "a.png"), "a.png")).toBe(
      "a.png：\n1. (x: 10.0%, y: 20.0%) 一\n2. (x: 1.0%, y: 1.0%) 二\n\n謝謝"
    )
  })

  it("keep a spot a hand moved off the picture on its edge, and leave a broken line as words", () => {
    const draft =
      "a.png：\n1. (x: 150.0%, y: -5.0%) 圖外\n2. (x: 1.2.3%, y: 10.0%) 壞的"
    expect(
      commentsIn(draft, "a.png").map(({ at, text }) => [at, text])
    ).toEqual([[[1, 0], "圖外"]])
    expect(withComments(draft, commentsIn(draft, "a.png"), "a.png")).toBe(
      "a.png：\n1. (x: 100.0%, y: 0.0%) 圖外\n2. (x: 1.2.3%, y: 10.0%) 壞的"
    )
  })

  it("take their heading and its blank line with them once none are left", () => {
    const draft =
      "看一下\n\na.png：\n1. (x: 1.0%, y: 1.0%) 一\n\nb.png：\n1. (x: 5.0%, y: 5.0%) 乙"
    expect(withComments(draft, [], "a.png")).toBe(
      "看一下\n\nb.png：\n1. (x: 5.0%, y: 5.0%) 乙"
    )
    expect(withComments(draft, [], "b.png")).toBe(
      "看一下\n\na.png：\n1. (x: 1.0%, y: 1.0%) 一"
    )
    expect(
      withComments("a.png：\n1. (x: 1.0%, y: 1.0%) 一\n\n謝謝", [], "a.png")
    ).toBe("謝謝")
  })

  it("leave the draft as it was without any", () => {
    expect(withComments("hi", [box, pen], "a.png")).toBe("hi")
    const draft = "a.png：\n這一行是訊息本文"
    expect(withComments(draft, [], "a.png")).toBe(draft)
  })

  it("follow the picture's copy under its new name", () => {
    expect(
      relabelled("a.png：\n1. x\na.png： is fine", "a.png", "a-markup.png")
    ).toBe("a-markup.png：\n1. x\na.png： is fine")
  })
})

describe("zoom", () => {
  it("stays between whole and eight times", () => {
    expect(zoomedAt(UNZOOMED, 0.5, [50, 50], 100, 100).scale).toBe(1)
    expect(zoomedAt(UNZOOMED, 100, [50, 50], 100, 100).scale).toBe(8)
  })

  it("keeps the point it zooms about where it is", () => {
    const view = zoomedAt(UNZOOMED, 2, [30, 40], 100, 100)
    expect((30 - view.x) / view.scale).toBe(30)
    expect((40 - view.y) / view.scale).toBe(40)
  })

  it("never moves the content off an edge", () => {
    expect(held({ scale: 2, x: 10, y: -500 }, 100, 100)).toEqual({
      scale: 2,
      x: 0,
      y: -100,
    })
  })
})

describe("markupName", () => {
  it("marks the name and makes it a PNG", () => {
    expect(markupName("登入畫面.jpg")).toBe("登入畫面-markup.png")
    expect(markupName("shot")).toBe("shot-markup.png")
  })

  it("marks a copy marked up again once", () => {
    expect(markupName("登入畫面-markup.png")).toBe("登入畫面-markup.png")
  })
})
