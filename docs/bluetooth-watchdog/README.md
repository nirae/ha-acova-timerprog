# Optional: Bluetooth watchdog for host BlueZ

A sample systemd watchdog that restarts `bluetooth.service` when a BLE entity stays
`unavailable` for too long. **You only need this if Home Assistant talks to the radiator
through the host's BlueZ** (HA Container / Core on Linux, or some HAOS adapters) **and
you hit stuck "ghost" connections.** If you use an ESPHome Bluetooth proxy, you almost
certainly don't need it.

## The problem it works around

BlueZ can keep a ghost connection to a device: `bluetoothctl info <addr>` shows
`Connected: yes` but there is no working transport, and even `disconnect` times out. The
device then stops advertising and no client can reach it. **No device integration can
clear this** — it is a daemon/adapter-level state. The integration already bounds its
sessions and keeps retrying, so it recovers on its own *once the adapter is healthy*;
this watchdog is what makes it healthy again by restarting the service.

A weak signal makes it far more likely (half-opened connections that die leave ghosts),
so first make sure the adapter sees the radiator at roughly −75 dBm or better, or move to
an ESPHome Bluetooth proxy. Use this watchdog only if ghosts still happen.

## Install (Linux host, as root)

```bash
sudo install -m 755 ha-bt-watchdog.sh /usr/local/bin/ha-bt-watchdog.sh
sudo install -m 644 ha-bt-watchdog.service ha-bt-watchdog.timer /etc/systemd/system/

sudo tee /etc/ha-bt-watchdog.env >/dev/null <<'EOF'
HA_TOKEN=PASTE_A_LONG_LIVED_TOKEN_HERE
HA_URL=http://localhost:8123
WATCH_ENTITY=climate.your_radiator   # the climate entity created by this integration
MAX_UNAVAIL=600
EOF
sudo chmod 600 /etc/ha-bt-watchdog.env

sudo systemctl daemon-reload
sudo systemctl enable --now ha-bt-watchdog.timer
```

Create the token in HA → Profile → Security → Long-lived access tokens. `HA_URL` is the
API as seen from the host (`http://localhost:8123` when HA runs in host networking).

## Notes

- The script restarts bluetooth **only** when the entity reads `unavailable`; a failed
  API call (HA restarting, bad token) is treated as healthy and never triggers a restart.
- Keep `MAX_UNAVAIL` well above the integration's polling interval so a single failed
  poll never triggers a restart (600 s = at least two failed 300 s polls).
- Restarting bluetooth briefly drops every other BLE device on that adapter; HA
  reconnects them.

```bash
systemctl list-timers ha-bt-watchdog.timer      # next run
journalctl -t ha-bt-watchdog --no-pager | tail  # what it did
```
