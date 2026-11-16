// Files the user attaches to a message: each is shrunk if it is a large image, then uploaded as soon as it is picked
// (runtime attachments.py), so the message names it by id.

import { ApiError, api } from "@/lib/api"

// As the runtime takes them: at most this many to a message; a photo, which a model reads, up to MAX_BYTES and this long
// a side; any other file up to MAX_KEPT (a PDF over MAX_BYTES only code opens).
export const MAX_FILES = 5
export const MAX_BYTES = 5 * 1024 * 1024
export const MAX_KEPT = 20 * 1024 * 1024
export const MAX_SIDE = 2048
const PHOTOS = ["image/jpeg", "image/png", "image/webp"]

/** A photo or screenshot a model looks at itself. Any other image (a GIF, an iPhone's HEIC) is a file like any. */
export const isPhoto = (type: string) => PHOTOS.includes(type)
const limit = (type: string) => (isPhoto(type) ? MAX_BYTES : MAX_KEPT)

/** What a file's card says it is: its extension, as people know kinds of files by; empty for a name without one. */
export function kindOf(name: string): string {
  const dot = name.lastIndexOf(".")
  return dot > 0 && name.length - dot <= 6
    ? name.slice(dot + 1).toUpperCase()
    : ""
}

export type Attachment = {
  key: string // this page's own, while it uploads
  name: string
  kind: "image" | "file"
  preview: string | null // a small copy of the image, as a data URL, to keep with the draft
  id: string | null // the upload's, once the runtime has it
  // failed: may go if tried again; rejected: cannot go (unreadable, too large), only taken off
  state: "uploading" | "ready" | "failed" | "rejected"
}

/** An attachment as its message shows it: the file the runtime kept it as; or, for one just sent from here whose log
 * has not come yet, no file and, for a photo, its preview (null while it has none). */
export type Shown = { file: string; name: string; preview?: string | null }

/** What went with each message just sent from here, by its run, shown with it until its log names them. A few only:
 * the log comes a moment later. */
const sent = new Map<string, Shown[]>()

export function sentWith(run: string, attached?: Attachment[]): Shown[] {
  if (attached?.length) {
    sent.set(
      run,
      attached.map(({ name, kind, preview }) =>
        kind === "image" ? { file: "", name, preview } : { file: "", name }
      )
    )
    if (sent.size > 8) sent.delete(sent.keys().next().value!)
  }
  return sent.get(run) ?? []
}

/** The file as it goes: an image larger than MAX_SIDE or MAX_BYTES is turned upright and shrunk, in its own format (as
 * the model sees it), or as WebP when that is still over MAX_BYTES (a PNG photo); anything else as it is. */
export async function prepared(file: File): Promise<Blob> {
  if (!isPhoto(file.type)) return file
  const bitmap = await createImageBitmap(file) // turned upright by its EXIF orientation
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height))
  if (scale === 1 && file.size <= MAX_BYTES) {
    bitmap.close()
    return file
  }
  const canvas = new OffscreenCanvas(
    Math.round(bitmap.width * scale),
    Math.round(bitmap.height * scale)
  )
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  bitmap.close()
  const blob = await canvas.convertToBlob({ type: file.type, quality: 0.85 })
  return blob.size <= MAX_BYTES
    ? blob
    : canvas.convertToBlob({ type: "image/webp", quality: 0.85 })
}

// A preview fills a 56 tile at twice the pixels: its shorter side this long.
const PREVIEW_SIDE = 112

/** A small copy of an image for its tile, turned upright, as a data URL: small enough to keep with the draft. */
export async function thumbnail(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(
    1,
    PREVIEW_SIDE / Math.min(bitmap.width, bitmap.height)
  )
  const canvas = new OffscreenCanvas(
    Math.round(bitmap.width * scale),
    Math.round(bitmap.height * scale)
  )
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  bitmap.close()
  const blob = await canvas.convertToBlob({ type: "image/webp", quality: 0.8 })
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

/** Whether the file is too large to go, before it is sent: a photo is shrunk first, so only once it has been. */
export function refused(file: File): boolean {
  return !isPhoto(file.type) && file.size > limit(file.type)
}

/** Why an upload failed, as the page says it: a file that cannot be read (the browser cannot open the image, or the
 * runtime turns it away) is "unreadable" and no use trying again; anything else, such as a lost connection, "failed". */
export function failure(error: unknown): "size" | "unreadable" | "failed" {
  if (error instanceof Error && error.message === "size") return "size"
  if (error instanceof ApiError)
    return error.status === 413
      ? "size"
      : error.status === 400
        ? "unreadable"
        : "failed"
  // createImageBitmap's, for a file that is no image it can open.
  if (error instanceof DOMException) return "unreadable"
  return "failed"
}

/** Uploads a prepared file; its id. */
export async function uploaded(file: File): Promise<string> {
  await file.slice(0, 1).arrayBuffer() // a dropped folder cannot be read: a DOMException, so unreadable
  const blob = await prepared(file)
  if (blob.size > limit(file.type)) throw new Error("size")
  return (await api.upload(blob, file.name)).id
}
