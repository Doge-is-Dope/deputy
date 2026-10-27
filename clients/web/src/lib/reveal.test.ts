import { describe, expect, it } from "vitest"

import { cut, Pace, STEP_MS } from "@/lib/reveal"

/**
 * Plays batches (`[time, characters]`) into a pace as the page would: a step as each comes and one every STEP_MS,
 * on a clock of whole milliseconds, written from `written` on. Returns how many characters were shown and had come at
 * each step.
 */
function play(batches: [number, number][], until: number, written = Infinity) {
  const pace = new Pace(0)
  const steps: { time: number; shown: number; length: number }[] = []
  let length = 0
  let next = 0
  for (let time = 0; time <= until; time++) {
    let came = false
    while (next < batches.length && batches[next][0] <= time) {
      length += batches[next][1]
      next++
      came = true
    }
    if (came || time % STEP_MS === 0)
      steps.push({
        time,
        shown: pace.step(length, time, time >= written),
        length,
      })
  }
  return steps
}

// 2 characters every 50 ms, 40 a second, for 3 seconds, as a model writing Chinese at a steady pace.
const STEADY = Array.from(
  { length: 60 },
  (_, index) => [25 + index * 50, 2] as [number, number]
)

describe("Pace", () => {
  it("shows nothing of a first batch at once, and takes its size a second as the rate", () => {
    const pace = new Pace(0)
    expect(pace.step(12, 1000)).toBe(0)
    expect(pace.rate).toBe(12)
  })

  it("never shows more than has come, nor takes back what it showed", () => {
    const steps = play(STEADY, 4000)
    steps.forEach((step, index) => {
      expect(step.shown).toBeLessThanOrEqual(step.length)
      if (index)
        expect(step.shown).toBeGreaterThanOrEqual(steps[index - 1].shown)
    })
  })

  it("keeps about half a second behind a steady stream, at its rate, a character or two at a time", () => {
    const steps = play(STEADY, 4000)
    const middle = steps.filter(
      (step) => step.time >= 1500 && step.time <= 3000
    )
    for (const step of middle) {
      expect(step.length - step.shown).toBeGreaterThan(8)
      expect(step.length - step.shown).toBeLessThan(30)
    }
    const growth = middle
      .slice(1)
      .map((step, index) => step.shown - middle[index].shown)
    expect(Math.max(...growth)).toBeLessThanOrEqual(3)
    // At 40 characters a second, some 60 are shown over that second and a half.
    expect(middle.at(-1)!.shown - middle[0].shown).toBeGreaterThan(50)
    expect(middle.at(-1)!.shown - middle[0].shown).toBeLessThan(70)
  })

  it("lets the rest in at that pace once the stream ends, rather than at once", () => {
    const steps = play(STEADY, 5000)
    const ended = steps.filter((step) => step.time >= 3000)
    const growth = ended
      .slice(1)
      .map((step, index) => step.shown - ended[index].shown)
    expect(Math.max(...growth)).toBeLessThanOrEqual(3)
    expect(ended.at(-1)!.shown).toBe(120)
  })

  it("ends at its pace once written, rather than slowing as the rest runs out", () => {
    const done = (written?: number) =>
      play(STEADY, 5000, written).find((step) => step.shown === 120)!.time
    expect(done()).toBeGreaterThan(3700)
    expect(done(2975)).toBeLessThan(3600)
    const ending = play(STEADY, 5000, 2975).filter(
      (step) => step.time >= 2975 && step.time % STEP_MS === 0
    )
    const left = ending.filter((step) => step.shown < 120)
    left.slice(1).forEach((step, index) => {
      expect(step.shown - left[index].shown).toBeGreaterThanOrEqual(1)
      expect(step.shown - left[index].shown).toBeLessThanOrEqual(3)
    })
  })

  it("still spreads a burst that comes written, never slowing to a crawl", () => {
    const steps = play([[0, 200]], 3000, 0)
    const at = (time: number) => steps.find((step) => step.time >= time)!.shown
    expect(at(100)).toBeLessThan(60)
    expect(at(1000)).toBe(200)
  })

  it("spreads a burst over a second or so, faster at first and slower as it ends", () => {
    const steps = play([[0, 200]], 3000)
    const at = (time: number) => steps.find((step) => step.time >= time)!.shown
    expect(at(250)).toBeGreaterThan(40)
    expect(at(250)).toBeLessThan(120)
    expect(at(600)).toBeLessThan(200)
    expect(at(2000)).toBe(200)
    expect(at(250) - at(0)).toBeGreaterThan(at(1000) - at(750))
  })

  it("evens out batches that come far apart", () => {
    // 30 characters every 400 ms: let in a few every step, not 30 then nothing.
    const batches = Array.from(
      { length: 8 },
      (_, index) => [index * 400, 30] as [number, number]
    )
    const steps = play(batches, 3200).filter(
      (step) => step.time % STEP_MS === 0
    )
    const middle = steps.filter(
      (step) => step.time >= 1000 && step.time <= 3000
    )
    const growth = middle
      .slice(1)
      .map((step, index) => step.shown - middle[index].shown)
    expect(Math.max(...growth)).toBeLessThanOrEqual(8)
    expect(Math.min(...growth)).toBeGreaterThan(0)
  })

  it("carries a fraction of a character over, so a slow backlog still comes a character at a time", () => {
    const steps = play([[0, 12]], 2000)
    const shown = steps.map((step) => step.shown)
    expect(shown.at(-1)).toBe(12)
    shown.slice(1).forEach((count, index) => {
      expect(count - shown[index]).toBeLessThanOrEqual(1)
    })
  })

  it("owes nothing for the time it was caught up", () => {
    const pace = new Pace(0)
    pace.step(5, 0)
    for (let time = STEP_MS; pace.shown < 5; time += STEP_MS) pace.step(5, time)
    expect(pace.step(25, 60_000)).toBe(5)
  })
})

describe("cut", () => {
  it("keeps the two halves of a character together", () => {
    expect(cut("好😀", 2)).toBe(3)
    expect(cut("好😀", 3)).toBe(3)
    expect(cut("好看", 1)).toBe(1)
  })
})
