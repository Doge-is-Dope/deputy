// Code is left as written: a fenced block, to its closing fence or to the end of a reply still being written, and code
// in a line.
const CODE = /^[ \t]*(`{3,}|~{3,})[\s\S]*?(?:\n[ \t]*\1|(?![\s\S]))|`[^`\n]+`/gm
// \[ x \] alone on its line, at any indent (a list item's).
const DISPLAY_LINE = /^([ \t]*)(?<!\\)\\\[(.+?)\\\][ \t]*$/gm
// \[ x \] elsewhere, or with \[ and \] on lines of their own; not LaTeX's line break \\[2pt].
const DISPLAY = /(?<!\\)\\\[([\s\S]+?)\\\]/g
const INLINE = /(?<!\\)\\\(([^\n]+?)\\\)/g

function convert(prose: string): string {
  return prose
    .replace(
      DISPLAY_LINE,
      (_, indent: string, body: string) =>
        `${indent}$$\n${indent}${body.trim()}\n${indent}$$`
    )
    .replace(DISPLAY, (_, body: string) => `$$${body}$$`)
    .replace(INLINE, (_, body: string) => `$$${body}$$`)
}

/** Normalize LaTeX \( \) and \[ \] delimiters to $$ for Streamdown (vercel/streamdown#194).
 * Preserve code, list indentation and block layout. During streaming, normalize an
 * unclosed final formula too, so \[ is not misread as an unfinished link. */
export function dollarMath(text: string, streaming = false): string {
  if (!text.includes("\\(") && !text.includes("\\[")) return text
  let result = ""
  let from = 0
  for (const code of text.matchAll(CODE)) {
    result += convert(text.slice(from, code.index)) + code[0]
    from = code.index + code[0].length
  }
  // Pairs are $$ by now, so a \( or \[ left over in the prose the text ends in was begun and not ended.
  const last = result.length
  result += convert(text.slice(from))
  const open = Math.max(result.lastIndexOf("\\("), result.lastIndexOf("\\["))
  if (!streaming || open < last || result[open - 1] === "\\") return result
  return `${result.slice(0, open)}$$${result.slice(open + 2)}`
}
