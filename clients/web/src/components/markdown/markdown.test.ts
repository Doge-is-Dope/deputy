import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// A reply's pictures open in the viewer, whose language is the page's: neither needs a page here.
beforeEach(() => {
  vi.resetModules()
  vi.doMock("@/components/screenshot-viewer", () => ({
    ScreenshotViewer: () => null,
  }))
  vi.doMock("@/lib/i18n", async () => {
    const { en } = await import("@/locales/en")
    return { t: () => en, useT: () => en, locale: () => "en" }
  })
})
afterEach(() => {
  vi.doUnmock("./markdown-content")
  vi.doUnmock("./copy-button")
  vi.doUnmock("@/components/screenshot-viewer")
  vi.doUnmock("@/lib/i18n")
})

describe("deferred Markdown", () => {
  it("shows a picture the coding agent made where it is linked, with the link to download it", async () => {
    vi.doMock("@/components/copy-button", () => ({ CopyButton: () => null }))
    const { Markdown } = await import("./markdown-content")
    const html = renderToStaticMarkup(
      createElement(Markdown, {
        text: "[圖](sandbox:/workspace/abc123/out/chart.png) [表](sandbox:/workspace/abc123/logo.svg)",
      })
    )
    expect(html).toContain(
      'src="/api/conversations/abc123/files/out/chart.png"'
    )
    expect(html).toMatch(
      /<a [^>]*href="\/api\/conversations\/abc123\/files\/out\/chart.png"[^>]*download="">圖<\/a>/
    )
    // Only the pictures a page shows safely; any other file is a link.
    expect(html).not.toContain('src="/api/conversations/abc123/files/logo.svg"')
  })

  it("downloads workspace links through the API while preserving ordinary links", async () => {
    vi.doMock("@/components/copy-button", () => ({ CopyButton: () => null }))
    const { Markdown } = await import("./markdown-content")
    const html = renderToStaticMarkup(
      createElement(Markdown, {
        text: "[CSV](/workspace/abc123/reports/budget.csv) [表](sandbox:/workspace/abc123/table.txt) [網站](https://example.com/workspace/abc123/a.csv)",
      })
    )
    expect(html).toContain(
      'href="/api/conversations/abc123/files/reports/budget.csv"'
    )
    expect(html).toContain('href="/api/conversations/abc123/files/table.txt"')
    expect(html).toContain('download=""')
    expect(html).toContain('target="_self"')
    expect(html).toContain('href="https://example.com/workspace/abc123/a.csv"')
  })

  it("holds a fence that is still opening back while streaming, and sizes a block by its lines", async () => {
    vi.doMock("@/components/copy-button", () => ({ CopyButton: () => null }))
    const { Markdown } = await import("./markdown-content")
    const draw = (text: string, streaming = true) =>
      renderToStaticMarkup(createElement(Markdown, { text, streaming }))
    for (const text of [
      "內容：\n`",
      "內容：\n``",
      "內容：\n```",
      "內容：\n```te",
    ]) {
      expect(draw(text)).not.toContain("<pre")
      expect(draw(text)).not.toContain("`")
    }
    expect(draw("內容：\n```text\n")).toContain(">text<")
    expect(draw("`code` 開頭的一行")).toContain("<code")
    expect(draw("```text\na\nb\n```", false)).toContain(
      "contain-intrinsic-size:auto 88px"
    )
  })

  it("draws a table being written only as a table, each row once it is whole", async () => {
    vi.doMock("@/components/copy-button", () => ({ CopyButton: () => null }))
    const { Markdown } = await import("./markdown-content")
    const text = "計算：\n\n| 數字 | 平方 |\n|---:|---:|\n| 1 | 1 |\n| 2 | 4 |"
    let rows = 0
    for (let end = 1; end <= text.length; end++) {
      const html = renderToStaticMarkup(
        createElement(Markdown, { text: text.slice(0, end), streaming: true })
      )
      // Never the table's pipes as words, and never a row taken back.
      expect(html.replace(/<[^>]*>/g, "")).not.toContain("|")
      const now = html.split("<tr").length - 1
      expect(now).toBeGreaterThanOrEqual(rows)
      rows = now
    }
    expect(rows).toBe(2) // the header and the first row; the last row shows once the reply is whole
  })

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
