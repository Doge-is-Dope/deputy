#!/usr/bin/env bash
# One shared desktop session per container; stopping an API server leaves it running.
set -euo pipefail

: "${RDP_HOST:?}" "${RDP_USER:?}" "${RDP_PASSWORD:?}"
export DISPLAY="${RDP_DISPLAY:-:1}"
export RDP_KEYBOARD_PIPE="${RDP_KEYBOARD_PIPE:-/tmp/rdp-keyboard}"
width="${RDP_SCREEN_WIDTH:-1280}"
height="${RDP_SCREEN_HEIGHT:-800}"

# Note: Xvfb only moves the pointer once a window is mapped; xfreerdp's window always is while connected.
# `docker compose restart` keeps /tmp, so clear the lock a previous Xvfb left behind.
rm -f "/tmp/.X${DISPLAY#:}-lock" "/tmp/.X11-unix/X${DISPLAY#:}"
# -noreset: Xvfb would otherwise reset the keymap below once its last client disconnects.
Xvfb "$DISPLAY" -screen 0 "${width}x${height}x24" -nolisten tcp -noreset &
until xdotool getdisplaygeometry >/dev/null 2>&1; do sleep 0.2; done
# FreeRDP's Unicode input (unicode:on below, which its text pipe needs) sends a key whose keysym has text as that
# text: Tab, Escape and Delete would reach Windows as characters that move no focus, close nothing and delete nothing.
# Their keys get keysyms without text, so their scancodes go through; computers/rdp.py names them so (KEYSYMS).
python -c '
from Xlib import XK, display
XK.load_keysym_group("xkb")
d = display.Display()
for code, name in ((23, "ISO_Left_Tab"), (9, "Cancel"), (119, "Select")):
    d.change_keyboard_mapping(code, [[XK.string_to_keysym(name)] * 2])
d.sync()
'

# Keep one RDP session open, sized to the virtual display; reconnect if it drops. This loop is the only reconnect:
# with FreeRDP's own, its window stays up while it retries, so a lost session looks connected.
rdp_args=(
  /v:"$RDP_HOST" /u:"$RDP_USER" /p:"$RDP_PASSWORD"
  /size:"${width}x${height}" /bpp:24 /gfx:AVC444 /cert:tofu +clipboard -wallpaper /log-level:WARN
  /wm-class:rdp-session  # the tools look for this window to tell if the session is up
)
rdp_args+=(/kbd:"layout:0x00000409,lang:0x0409,pipe:$RDP_KEYBOARD_PIPE,unicode:on")
[[ -n "${RDP_DOMAIN:-}" ]] && rdp_args+=(/d:"$RDP_DOMAIN")
# Beside the keyboard pipe; computers/rdp.py reports the first as the desktop's status.
signin_failed="$(dirname "$RDP_KEYBOARD_PIPE")/rdp-signin-failed"
rdp_log="$(dirname "$RDP_KEYBOARD_PIPE")/rdp-attempt.log"
rm -f "$signin_failed"
while true; do
  # FreeRDP creates the keyboard pipe and fails if it exists, as after a kept /tmp or a killed xfreerdp.
  rm -f "$RDP_KEYBOARD_PIPE"
  xfreerdp3 "${rdp_args[@]}" 2>&1 | tee "$rdp_log" >&2 || true
  # Windows refused the sign-in: every retry is another failed sign-in, and enough of them lock the account. The
  # log names the refusal; the exit code does not tell it from a crash (134 is also an abort).
  if error=$(grep -oEm1 "ERRCONNECT_(LOGON_FAILURE|WRONG_PASSWORD|ACCOUNT_(LOCKED_OUT|DISABLED))" "$rdp_log"); then
    echo "RDP sign-in failed ($error); not retrying: check RDP_USER and RDP_PASSWORD" >&2
    echo "$error" >"$signin_failed"
    break
  fi
  echo "RDP session ended; reconnecting in 5s" >&2
  sleep 5
done &

# The common entrypoint owns the API and live-view relay.
exec desktop-entrypoint "$@"
