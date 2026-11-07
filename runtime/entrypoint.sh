#!/usr/bin/env bash
# API and live-view relay. The deployment prepares its desktop backend before entering here.
set -euo pipefail

# The browser cannot reach the container's addresses, so the live view's WebRTC media is relayed through this
# TURN server, which the browser reaches over one published TCP port. Browsers use a TURN server only with
# credentials; a new password each start reaches the page through the API. It relays only to this container's own
# addresses, where the live view's peer is: anyone with the password could otherwise send through it to any address.
export CU_TURN_PASSWORD="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
peers=(--denied-peer-ip=0.0.0.0-255.255.255.255 --denied-peer-ip=::-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff)
for address in $(hostname -i); do peers+=(--allowed-peer-ip="$address"); done
turnserver -n --no-cli --no-tls --no-dtls --lt-cred-mech --user="live:$CU_TURN_PASSWORD" --realm=computer-use \
  --listening-port=3478 --fingerprint --simple-log --log-file=/tmp/turnserver.log "${peers[@]}" &

# The container lives as long as the API. init forwards stop signals and reaps helper processes.
exec computer-use-runtime --host 0.0.0.0 "$@"
