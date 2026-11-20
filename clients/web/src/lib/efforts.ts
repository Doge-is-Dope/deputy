/** Each reasoning effort, lowest first, as the runtime names it (agent/models.py LEVELS). Named in the interface's
 * language (settings.efforts). */
export const EFFORTS = [
  "none",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
] as const

export type Effort = (typeof EFFORTS)[number]
