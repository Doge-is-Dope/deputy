/** A random id; not crypto.randomUUID, which a page opened over plain HTTP on another address does not have. */
export function randomId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
    byte.toString(16).padStart(2, "0")
  ).join("")
}
