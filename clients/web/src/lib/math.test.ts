import { describe, expect, it } from "vitest"

import { dollarMath } from "@/lib/math"

describe("dollarMath", () => {
  it("turns LaTeX's inline delimiters into $$", () => {
    expect(dollarMath("\\(7^{53} = 6168\\) 是答案，\\(x\\) 也是")).toBe(
      "$$7^{53} = 6168$$ 是答案，$$x$$ 也是"
    )
  })

  it("makes \\[ \\] alone on a line a block, at its indent", () => {
    expect(dollarMath("公式：\n\\[ a^2 + b^2 = c^2 \\]\n完")).toBe(
      "公式：\n$$\na^2 + b^2 = c^2\n$$\n完"
    )
    expect(dollarMath("1. 畢氏定理\n   \\[a^2+b^2\\]")).toBe(
      "1. 畢氏定理\n   $$\n   a^2+b^2\n   $$"
    )
  })

  it("keeps a block written over several lines where it is", () => {
    expect(
      dollarMath("\\[\n\\begin{cases} x \\\\[2pt] y \\end{cases}\n\\]")
    ).toBe("$$\n\\begin{cases} x \\\\[2pt] y \\end{cases}\n$$")
  })

  it("leaves code as written", () => {
    const text =
      "用 `\\(x\\)` 寫：\n```latex\n\\(x\\) \\[y\\]\n```\n然後 \\(z\\)"
    expect(dollarMath(text)).toBe(
      "用 `\\(x\\)` 寫：\n```latex\n\\(x\\) \\[y\\]\n```\n然後 $$z$$"
    )
    expect(dollarMath("```\n\\(x\\) still being written")).toBe(
      "```\n\\(x\\) still being written"
    )
  })

  it("opens the formula a reply being written ends in", () => {
    expect(dollarMath("\\(x\\) 答案是 \\(7^{53", true)).toBe(
      "$$x$$ 答案是 $$7^{53"
    )
    expect(dollarMath("步驟：\n\\[\nx^2+\\frac", true)).toBe(
      "步驟：\n$$\nx^2+\\frac"
    )
    expect(dollarMath("```\n\\(x", true)).toBe("```\n\\(x")
    expect(dollarMath("\\(x\\) 和 C:\\\\(", true)).toBe("$$x$$ 和 C:\\\\(")
  })

  it("leaves a formula not ended in a reply written in full", () => {
    expect(dollarMath("答案是 \\(7^{53")).toBe("答案是 \\(7^{53")
  })

  it("leaves dollars and escaped backslashes alone", () => {
    expect(dollarMath("NT$1,200 和 $5")).toBe("NT$1,200 和 $5")
    expect(dollarMath("路徑 C:\\\\(備份\\\\)")).toBe("路徑 C:\\\\(備份\\\\)")
  })
})
