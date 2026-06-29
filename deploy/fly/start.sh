#!/usr/bin/env bash
# Entrypoint for the Fly Machine: bring up the Docker daemon (the sandbox needs it), then the app.
set -euo pipefail

DATA="${VERITAS_DATA:-/data}"
mkdir -p "$DATA"

# Start dockerd inside the microVM. We only ever run `--network none` sandboxes, so we skip the bridge
# and iptables setup entirely — fewer privileges needed, and isolation is unaffected. Docker's data
# lives on the mounted Fly Volume so pulled images and layers survive restarts.
dockerd \
  --data-root="$DATA/docker" \
  --bridge=none \
  --iptables=false \
  >/var/log/dockerd.log 2>&1 &

# Wait for the daemon to answer before we accept any traffic.
for _ in $(seq 1 60); do
  if docker info >/dev/null 2>&1; then break; fi
  sleep 1
done
if ! docker info >/dev/null 2>&1; then
  echo "FATAL: dockerd did not come up; the wedge fails closed without a sandbox." >&2
  tail -n 40 /var/log/dockerd.log >&2 || true
  exit 1
fi

# Pre-pull the sandbox image (cached on the Volume after the first boot, so this is a no-op later).
docker image inspect python:3.12-slim >/dev/null 2>&1 || docker pull python:3.12-slim

# Hand off to the app. Bind to all interfaces inside the microVM; Fly's proxy terminates TLS in front.
exec uvicorn hub.app:app --host 0.0.0.0 --port 8099
