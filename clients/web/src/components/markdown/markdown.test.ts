import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

beforeEach(() => vi.resetModules())
afterEach(() => {
  vi.doUnmock("./markdown-content")
  vi.doUnmock("./copy-button")
})

describe("deferred Markdown", () => {
  it("shares a pending preload and renders the latest streaming props once ready", async () => {
    let resolve!: (module: typeof import("./markdown-content")) => void
    const pending = new Promise<typeof import("./markdown-content")>((done) => {
      resolve = done
    })
    const load = vi.fn(() => pending)
    vi.doMock("./markdown-content", load)
    const { Markdown, preloadMarkdown } = await import("./markdown")
    const loading = preloadMarkdown()
    expect(preloadMarkdown()).toBe(loading)
    expect(
      renderToStaticMarkup(createElement(Markdown, { text: "先到的文字" }))
    ).toBe("")

    resolve({
      Markdown: ({ text, streaming, className }) =>
        createElement("div", { className, "data-streaming": streaming }, text),
    })
    await loading
    expect(load).toHaveBeenCalledTimes(1)
    expect(
      renderToStaticMarkup(
        createElement(Markdown, {
          text: "先到的文字，還有後續內容",
          streaming: true,
          className: "leading-7",
        })
      )
    ).toBe(
      '<div class="leading-7" data-streaming="true">先到的文字，還有後續內容</div>'
    )
  })

  it("keeps incoming text readable and escaped when the chunk fails", async () => {
    vi.doMock("./markdown-content", () => {
      throw new Error("chunk unavailable")
    })
    const { Markdown, preloadMarkdown } = await import("./markdown")
    await preloadMarkdown()
    for (const text of ["第一段", "第一段\n<script>後續內容</script>"]) {
      const html = renderToStaticMarkup(createElement(Markdown, { text }))
      expect(html).toContain("第一段")
      expect(html).not.toContain("<script>")
      if (text.includes("後續"))
        expect(html).toContain("&lt;script&gt;後續內容")
    }
  })

  it("retains CJK, line breaks, code, tables, math and literal HTML", async () => {
    // The copy control uses browser-only locale state; exercise the real text pipeline in Node.
    vi.doMock("@/components/copy-button", () => ({ CopyButton: () => null }))
    const { Markdown, preloadMarkdown } = await import("./markdown")
    await preloadMarkdown()
    const html = renderToStaticMarkup(
      createElement(Markdown, {
        text: "中文**粗體**\n下一行\n\n```ts\nconst x = 1\n```\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\n\\(x^2\\)\n\n<Enter>",
      })
    )
    expect(html).toContain('data-streamdown="strong">粗體</span>')
    expect(html).toContain("<br")
    expect(html).toContain("const x = 1")
    expect(html).toContain("<table")
    expect(html).toContain('class="katex"')
    expect(html).toContain("&lt;Enter&gt;")
  })
})
