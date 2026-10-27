#!/usr/bin/env bash
# Virtual display -> one RDP session to Windows. The agents run next to it in the HTTP API's server, which every
# client reaches them through (the web page, the CLI, the eval) and which streams the display to the page over WebRTC.
set -euo pipefail

: "${RDP_HOST:?}" "${RDP_USER:?}" "${RDP_PASSWORD:?}"
export DISPLAY="${RDP_DISPLAY:-:1}"
width="${RDP_SCREEN_WIDTH:-1280}"
height="${RDP_SCREEN_HEIGHT:-800}"

# Note: Xvfb only moves the pointer once a window is mapped; xfreerdp's window always is while connected.
# `docker compose restart` keeps /tmp, so clear the lock a previous Xvfb left behind.
rm -f "/tmp/.X${DISPLAY#:}-lock" "/tmp/.X11-unix/X${DISPLAY#:}"
Xvfb "$DISPLAY" -screen 0 "${width}x${height}x24" -nolisten tcp &
until xdotool getdisplaygeometry >/dev/null 2>&1; do sleep 0.2; done

# The browser cannot reach the container's addresses, so the live view's WebRTC media is relayed through this
# TURN server, which the browser reaches over one published TCP port. Browsers use a TURN server only with
# credentials; a new password each start reaches the page through the API.
export CU_TURN_PASSWORD="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
turnserver -n --no-cli --no-tls --no-dtls --lt-cred-mech --user="live:$CU_TURN_PASSWORD" --realm=computer-use \
  --listening-port=3478 --fingerprint --simple-log --log-file=/tmp/turnserver.log &

# The API and live view; its run output goes to the container log.
computer-use-runtime --host 0.0.0.0 &

# Keep one RDP session open, sized to the virtual display; reconnect if it drops.
rdp_args=(
  /v:"$RDP_HOST" /u:"$RDP_USER" /p:"$RDP_PASSWORD"
  /size:"${width}x${height}" /bpp:24 /cert:tofu +clipboard -wallpaper +auto-reconnect /log-level:WARN
  /wm-class:rdp-session  # the tools look for this window to tell if the session is up
)
[[ -n "${RDP_DOMAIN:-}" ]] && rdp_args+=(/d:"$RDP_DOMAIN")
while true; do
  xfreerdp3 "${rdp_args[@]}" || true
  echo "RDP session ended; reconnecting in 5s" >&2
  sleep 5
done
