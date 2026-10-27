import { useCallback, useEffect, useRef, useState } from "react"

import { api } from "@/lib/api"

export type LiveState = "connecting" | "live" | "retrying"

// How long to wait for ICE candidates (the TURN server's included) before sending the offer anyway, and
// before trying again after a connection fails.
const GATHER_MS = 3000
const RETRY_MS = 3000

/** Resolves once the browser has all its candidates, so one offer carries them (no trickle ICE). */
function gathered(peer: RTCPeerConnection) {
  return new Promise<void>((resolve) => {
    const done = () => {
      if (peer.iceGatheringState !== "complete") return
      peer.removeEventListener("icegatheringstatechange", done)
      resolve()
    }
    peer.addEventListener("icegatheringstatechange", done)
    done()
    window.setTimeout(resolve, GATHER_MS)
  })
}

export type LiveInput =
  | { type: "move"; x: number; y: number }
  | { type: "button"; button: "left" | "middle" | "right"; down: boolean }
  | {
      type: "wheel"
      direction: "up" | "down" | "left" | "right"
      x: number
      y: number
    }
  | { type: "key"; key: string; down: boolean }
  | { type: "text"; text: string }

/** A point on the desktop, in screen pixels. */
export type ScreenPoint = { x: number; y: number }

/**
 * The desktop over WebRTC: its video, and a channel for the user's input (which the runtime applies only
 * while the user has control) that also brings where the agent's pointer is, for the page to draw: screen
 * captures leave the pointer out. Reconnects on its own when the connection drops. `iceServers` is null until
 * the runtime's status says which to use.
 */
export function useLive(iceServers: RTCIceServer[] | null) {
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [state, setState] = useState<LiveState>("connecting")
  const [attempt, setAttempt] = useState(0)
  // Null while the user has control: the page draws their pointer at their mouse.
  const [pointer, setPointer] = useState<ScreenPoint | null>(null)
  const channel = useRef<RTCDataChannel | null>(null)
  // A new array arrives with every status poll; reconnect only when the servers themselves change.
  const servers = iceServers === null ? null : JSON.stringify(iceServers)

  useEffect(() => {
    if (servers === null) return
    let closed = false
    const peer = new RTCPeerConnection({ iceServers: JSON.parse(servers) })
    const retry = () => {
      if (closed) return
      closed = true
      peer.close()
      setState("retrying")
      window.setTimeout(() => setAttempt((count) => count + 1), RETRY_MS)
    }

    peer.addTransceiver("video", { direction: "recvonly" })
    const input = peer.createDataChannel("input")
    channel.current = input
    input.onmessage = (event) => {
      const message = JSON.parse(event.data)
      if (message.type === "pointer")
        setPointer(
          message.point && { x: message.point[0], y: message.point[1] }
        )
    }
    peer.ontrack = (event) => {
      // Play frames as soon as they arrive rather than buffering for smoothness: the desktop answers the
      // user's own clicks and keys, so delay shows more than an occasional stutter.
      const receiver = event.receiver as RTCRtpReceiver & {
        jitterBufferTarget?: number | null
      }
      if ("jitterBufferTarget" in receiver) receiver.jitterBufferTarget = 0
      setStream(event.streams[0] ?? new MediaStream([event.track]))
    }
    peer.onconnectionstatechange = () => {
      if (peer.connectionState === "connected") setState("live")
      if (["failed", "disconnected"].includes(peer.connectionState)) retry()
    }

    async function connect() {
      await peer.setLocalDescription(await peer.createOffer())
      await gathered(peer)
      const answer = await api.live(peer.localDescription!.sdp)
      if (!closed) await peer.setRemoteDescription(answer)
    }
    connect().catch(retry)

    return () => {
      closed = true
      channel.current = null
      peer.close()
    }
  }, [servers, attempt])

  const send = useCallback((event: LiveInput) => {
    if (channel.current?.readyState === "open")
      channel.current.send(JSON.stringify(event))
  }, [])

  return { stream, state, send, pointer }
}
