import { Fragment } from "react"

import { ComputerLogo } from "@/components/icons"

// @Computer, which sends a message to the desktop: a word of its own, in any case, and not part of a longer word or
// of an email address. The runtime reads it the same way (agent/main_agent.py), and so does forComputer (lib/api.ts).
const MENTION = /(?<![A-Za-z0-9_])@computer(?![A-Za-z0-9_])/gi
export const MENTION_LENGTH = "@Computer".length

/** Where each @Computer in the text starts. */
export const mentionsIn = (text: string) =>
  Array.from(text.matchAll(MENTION), (match) => match.index)

/** The text split at the @ of each mention: the pieces around them, with the @s at the odd places. */
export function splitAtMentions(text: string) {
  const pieces: string[] = []
  let from = 0
  for (const start of mentionsIn(text)) {
    pieces.push(text.slice(from, start), "@")
    from = start + 1
  }
  pieces.push(text.slice(from))
  return pieces
}

/** Replace each @Computer mention's @ with the same logo used by the composer. */
export function MessageText({ text }: { text: string }) {
  return splitAtMentions(text).map((piece, index) =>
    index % 2 ? (
      <ComputerLogo
        key={index}
        className="mr-[3px] ml-px inline-block size-[1em] align-[-0.145em]"
      />
    ) : (
      <Fragment key={index}>{piece}</Fragment>
    )
  )
}
