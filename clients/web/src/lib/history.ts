/** Latest turns on first open; keep the first loaded turn when newer turns arrive. */
export const HISTORY_PAGE = 10

export function historyStart(runs: string[], first: string | null) {
  const index = first === null ? -1 : runs.indexOf(first)
  return index < 0 ? Math.max(0, runs.length - HISTORY_PAGE) : index
}
