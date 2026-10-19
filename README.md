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
uv run co2-monitor-server                  # /dev/ttyACM0 → data/co2_log.csv, http://127.0.0.1:8765
uv run co2-monitor-server --device /dev/ttyACM1 --out data/office.csv --port 9000
uv run co2-monitor-server --host 0.0.0.0   # also serve other machines on the network
```

Open the printed URL (default http://127.0.0.1:8765/) in a browser for the web
dashboard: current readings with comfort status, CO₂/temperature/humidity charts
over 1 h to 30 d with a synced hover readout, a table view and a CSV download.
It updates live, follows the system light/dark theme and needs no internet
access. The range is kept in the URL (e.g. `#7d`), so views can be bookmarked.
To open it from a phone or another computer, start the server with
`--host 0.0.0.0`; there is no authentication, so only do that on a trusted network.

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

## Terminal client (optional)

```bash
uv run co2-monitor                                   # dashboard for http://127.0.0.1:8765
uv run co2-monitor --server http://myserver.local:8765
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
