import { describe, expect, it, vi } from "vitest"

import { decoded, previewOf, unique } from "@/lib/attachments"

// Uploads carry the browser's choices, which naming a file doesn't touch.
vi.mock("@/lib/choices", () => ({ currentChoices: () => ({}) }))

describe("decoded", () => {
  const bytes = (values: number[]) => new Uint8Array(values).buffer

  it("reads UTF-8, and leaves out a character cut off where reading stopped", () => {
    const utf8 = new TextEncoder().encode("報價單")
    expect(decoded(utf8.buffer)).toBe("報價單")
    expect(decoded(utf8.slice(0, 7).buffer)).toBe("報價")
  })

  it("reads Big5, as Taiwan's Excel saves a CSV", () => {
    expect(
      decoded(bytes([179, 248, 187, 249, 179, 230, 44, 170, 247, 195, 66, 10]))
    ).toBe("報價單,金額\n")
  })

  it("leaves out a Big5 character cut off where reading stopped", () => {
    expect(decoded(bytes([179, 248, 187, 249, 179]))).toBe("報價")
  })

  it("reads UTF-16 by its byte order mark", () => {
    expect(decoded(bytes([0xff, 0xfe, 0x31, 0x58, 0xf9, 0x50]))).toBe("報價")
  })
})

describe("unique", () => {
  it("numbers a name another file has, as the runtime does", () => {
    const taken = new Set(["image.png", "image (2).png", "notes", ".env"])
    expect(unique("image.png", taken)).toBe("image (3).png")
    expect(unique("notes", taken)).toBe("notes (2)")
    expect(unique(".env", taken)).toBe(".env (2)")
    expect(unique("other.png", taken)).toBe("other.png")
  })
})

describe("previewOf", () => {
  it("knows pictures, PDFs and plain text by their names", () => {
    expect(previewOf("shot.png")).toBe("image")
    expect(previewOf("photo.JPEG")).toBe("image")
    expect(previewOf("報價單.pdf")).toBe("pdf")
    for (const name of ["a.txt", "b.md", "c.csv", "d.json", "e.yml", "f.log"])
      expect(previewOf(name)).toBe("text")
  })

  it("leaves anything else, and pages, to download", () => {
    for (const name of [
      "page.html",
      "logo.svg",
      "sheet.xlsx",
      "README",
      "archive.tar.gz",
    ])
      expect(previewOf(name)).toBeNull()
  })
})
