// How often the shown part of a reply being written is let grow, in milliseconds.
export const STEP_MS = 50
// How long a character takes to fade in once it is let in (index.css's reply-char-in), in milliseconds.
export const FADE_MS = 700
// The rate follows how fast characters come: each batch weighs this much in it, the rate before it the rest. Batches
// closer together than MIN_GAP_MS count as that far apart, so two in one poll don't make the rate soar.
const ARRIVAL_WEIGHT = 0.1
const MIN_GAP_MS = 10
// The slowest a backlog is let in, in characters a second.
const MIN_RATE = 1

/** Reveal characters at a smoothed arrival rate, adjusting speed to drain the backlog.
 * Carry fractional characters between steps. Times use performance.now() milliseconds. */
export class Pace {
  /** How many characters to show. */
  shown: number
  /** Characters a second. */
  rate = MIN_RATE
  private received: number
  private arrived: number | null = null
  private stepped: number | null = null
  private carry = 0

  constructor(shown: number) {
    this.shown = shown
    this.received = shown
  }

  /** The text is `length` characters long at `now`: lets in what is due by then, and returns how many to show. Once
   * `written`, no more is coming: the rest goes on at the pace it had. */
  step(length: number, now: number, written = false): number {
    const added = length - this.received
    this.received = length
    if (added > 0) {
      // The first batch sets the rate to its own size a second; a later one moves it towards how fast it came.
      this.rate =
        this.arrived === null
          ? added
          : Math.max(
              MIN_RATE,
              ARRIVAL_WEIGHT *
                ((added * 1000) / Math.max(now - this.arrived, MIN_GAP_MS)) +
                (1 - ARRIVAL_WEIGHT) * this.rate
            )
      this.arrived = now
    }
    // Once for each STEP_MS gone by (not at all on the first step, nothing being due yet), the rate leans towards the
    // backlog: down while the backlog would take under half a second at this rate, up while longer, and up more while
    // it would take over about a second. Once written, never down: with nothing more to wait for, it ends at its pace.
    const elapsed = this.stepped === null ? 0 : (now - this.stepped) / 1000
    this.stepped = now
    const backlog = length - this.shown
    for (let lean = 0; lean < (elapsed * 1000) / STEP_MS; lean++) {
      const before = this.rate
      if (backlog > 0 && backlog < this.rate * 1.5)
        this.rate = (backlog + this.rate * 1.5) / 2
      if (backlog > this.rate / 1.2) this.rate = (backlog + this.rate / 1.2) / 2
      if (written) this.rate = Math.max(before, this.rate)
    }
    this.rate = Math.max(MIN_RATE, this.rate)
    const due = elapsed * this.rate + this.carry
    const whole = Math.floor(due)
    this.carry = due - whole
    this.shown = Math.min(length, this.shown + whole)
    // Caught up, the time until more comes is not owed: the next batch starts from nothing due.
    if (this.shown >= length) {
      this.stepped = null
      this.carry = 0
    }
    return this.shown
  }
}

/** Cut near count without splitting a UTF-16 surrogate pair. */
export function cut(text: string, count: number): number {
  const code = text.charCodeAt(count - 1)
  return code >= 0xd800 && code <= 0xdbff ? count + 1 : count
}
