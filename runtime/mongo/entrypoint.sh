#!/bin/sh
# A one-member replica set with access control, which needs a key file: made once in the data volume. The image's
# entrypoint creates the root user and runs init-runtime.js on first start; compose's healthcheck initiates the set.
set -e
key=/data/db/keyfile
if [ ! -f "$key" ]; then
  head -c 756 /dev/urandom | base64 > "$key"
  chmod 400 "$key"
  chown mongodb:mongodb "$key"
fi
exec docker-entrypoint.sh mongod --replSet rs0 --keyFile "$key" --bind_ip_all
