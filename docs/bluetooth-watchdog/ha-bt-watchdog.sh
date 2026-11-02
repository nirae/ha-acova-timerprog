#!/usr/bin/env bash
# Restart bluetoothd when a BLE entity stays "unavailable" too long.
#
# A BlueZ "ghost" connection (Connected: yes with no working transport) cannot be
# cleared from inside Home Assistant: only a daemon/adapter reset fixes it. This
# watchdog detects the stuck state via the HA API and restarts the host service.
# It runs on the Pi host (root, via systemd), not inside the HA container.
set -euo pipefail

HA_URL="${HA_URL:-http://localhost:8123}"
WATCH_ENTITY="${WATCH_ENTITY:-climate.seche_serviettes}"
MAX_UNAVAIL="${MAX_UNAVAIL:-600}"          # seconds of continuous unavailability before acting
STATE_FILE="${STATE_FILE:-/run/ha-bt-watchdog.unavail-since}"

if [ -z "${HA_TOKEN:-}" ]; then
  echo "HA_TOKEN not set (expected in the EnvironmentFile)" >&2
  exit 1
fi

state="$(curl -sf --max-time 10 -H "Authorization: Bearer ${HA_TOKEN}" \
  "${HA_URL}/api/states/${WATCH_ENTITY}" 2>/dev/null \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["state"])' 2>/dev/null || echo "query_failed")"

now="$(date +%s)"

# Only "unavailable" is the stuck BLE signal. A failed API query (HA restarting,
# token issue) must NOT trigger a restart, so treat anything else as healthy.
if [ "${state}" != "unavailable" ]; then
  rm -f "${STATE_FILE}"
  exit 0
fi

if [ -f "${STATE_FILE}" ]; then
  since="$(cat "${STATE_FILE}" 2>/dev/null || echo "${now}")"
else
  since="${now}"
  echo "${since}" > "${STATE_FILE}"
fi

elapsed=$(( now - since ))
if [ "${elapsed}" -ge "${MAX_UNAVAIL}" ]; then
  logger -t ha-bt-watchdog "${WATCH_ENTITY} unavailable for ${elapsed}s (>= ${MAX_UNAVAIL}s): restarting bluetooth"
  systemctl restart bluetooth
  # Reset the timer so recovery (and the next poll cycle) gets a full window
  # before another restart could fire.
  rm -f "${STATE_FILE}"
fi
