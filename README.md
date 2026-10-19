# co2-monitor

A DIY CO₂, temperature and humidity monitor: an Adafruit QT Py ESP32-S3 running
ESPHome with a Sensirion SCD41 (CO₂) and SHT45 (temperature/humidity), plus
Python software in two parts:

- **`co2-monitor-server`** reads the monitor over USB, logs readings to CSV and
  serves a live web dashboard plus a JSON API.
- **`co2-monitor`** (optional) shows the same data as a terminal dashboard, on
  the same machine or another one.

## Layout

```
firmware/                 ESPHome configs
  co2-monitor-usb.yaml    USB-only: prints DATA,<co2>,<temp>,<rh> every 30 s
  co2-monitor-wifi.yaml   Wi-Fi: web server + Home Assistant API
  secrets.yaml            Wi-Fi/API credentials (git-ignored, create your own)
src/co2_monitor/
  server.py               serial reader, CSV logging, HTTP API
  static/index.html       web dashboard (self-contained HTML/JS/SVG)
  client.py               terminal client: polls a server, drives dashboard.py
  dashboard.py            rich terminal dashboard
  models.py               Reading type (JSON and text forms)
  parsing.py              parse firmware DATA lines
  storage.py              CSV log read/append
  trends.py               time-bucketing for trend lines
deploy/
  co2-monitor-server.service  systemd user service for the server
tests/                    pytest suite
data/                     CSV logs (git-ignored)
```

## Hardware

- Adafruit QT Py ESP32-S3 (2MB PSRAM, #5700)
- Adafruit SCD-41 CO₂ sensor, STEMMA QT (#5190)
- Adafruit SHT45 temperature/humidity sensor, STEMMA QT (#5665)
- 2× STEMMA QT / Qwiic JST SH 4-pin cables

Chain them QT Py → SCD41 → SHT45. Keep the SHT45 a few cm from the other two
boards so their heat doesn't skew temperature and humidity.

## Firmware

Requires [ESPHome](https://esphome.io) (e.g. `pipx install esphome`).

```bash
cd firmware
esphome run co2-monitor-usb.yaml --device /dev/ttyACM0
```

If it hangs after flashing, press RESET on the board once. The USB-only firmware
has no Wi-Fi, so updates also go over USB.

The Wi-Fi config reads credentials from `firmware/secrets.yaml`:

```yaml
api_encryption_key: "..."
wifi_ssid: "..."
wifi_password: "..."
hotspot_ssid: "..."
hotspot_password: "..."
ap_password: "..."
```

## Server

```bash
uv run co2-monitor-server                    # /dev/ttyACM0 → data/co2_log.csv, port 8080, all interfaces
uv run co2-monitor-server --host 127.0.0.1   # this machine only
uv run co2-monitor-server --device /dev/ttyACM1 --out data/office.csv
```

On startup it prints the dashboard's address on your network, e.g.
`Dashboard at http://10.88.111.9:8080/  (on this machine: http://localhost:8080/)`.
(Ports below 1024, such as 80, need extra permission on Linux; the server
explains how if you pick one.)

Open the printed URL in a browser (from any device on the network) for the web
dashboard: current readings with comfort status, CO₂/temperature/humidity charts
over 1 h to 30 d with a synced hover readout, a table view and a CSV download.
It updates live, follows the system light/dark theme and needs no internet
access. The range is kept in the URL (e.g. `#7d`), so views can be bookmarked.
There is no authentication: anyone on the network can view it, so run it on a
trusted network or use `--host 127.0.0.1`.

The log is append-only CSV (`timestamp,co2_ppm,temp_c,rh_percent`). The server
keeps the last 24 h in memory (preloaded from the CSV at startup) and reconnects
automatically if the monitor is unplugged. It prints each reading as it arrives.

Only one program can use the serial port at a time; close `esphome logs` or any
serial monitor first.

### HTTP API

All endpoints are `GET`:

| Endpoint | Returns |
|---|---|
| `/` | the web dashboard |
| `/api/status` | server/sensor status and the latest reading (JSON) |
| `/api/series?hours=H&points=P` | the last H hours averaged into at most P time buckets, plus min/mean/max (JSON) |
| `/api/readings?after=N` | readings from the last 24 h with sequence number > N (JSON) |
| `/api/readings.csv` | the full CSV log |

Each reading looks like
`{"seq": 12, "timestamp": "2026-10-18T19:44:08", "co2_ppm": 755.0, "temp_c": 22.43, "rh_percent": 38.2}`.
Sequence numbers restart with the server; the `run_id` in each response
changes too, so clients know to fetch everything again.

### Running as a service

`deploy/co2-monitor-server.service` is a systemd *user* service, so it runs as
you (serial access via the `dialout` group, log in your project folder) with no
root needed:

```bash
systemctl --user link ~/dev/code/co2-monitor/deploy/co2-monitor-server.service
systemctl --user start co2-monitor-server     # start now
systemctl --user enable co2-monitor-server    # start automatically
loginctl enable-linger                        # keep running when logged out, start at boot
journalctl --user -u co2-monitor-server -f    # follow its output
```

The unit runs `.venv/bin/co2-monitor-server`, so run `uv sync` first. Edit the
`ExecStart` line to change the device, port or log file, then
`systemctl --user daemon-reload`. Stop the service before flashing firmware or
using `esphome logs`, since only one program can hold the serial port.

## Terminal client (optional)

```bash
uv run co2-monitor                                   # dashboard for http://localhost:8080
uv run co2-monitor --server http://10.88.111.9:8080
uv run co2-monitor --plain                           # one line per reading
```

The client polls every 5 s (`--interval`), fetching only new readings. Ages are
computed on the server's clock, so they're right even if the two machines'
clocks differ. `--plain` is used automatically when output isn't a terminal.

## Development

```bash
uv sync
uv run pytest
```
