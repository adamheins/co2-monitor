# co2-monitor

A DIY CO₂, temperature and humidity monitor: an Adafruit QT Py ESP32-S3 running
ESPHome with a Sensirion SCD41 (CO₂) and SHT45 (temperature/humidity), plus a
Python logger that records readings over USB and shows a live terminal dashboard.

## Layout

```
firmware/                 ESPHome configs
  co2-monitor-usb.yaml    USB-only: prints DATA,<co2>,<temp>,<rh> every 30 s
  co2-monitor-wifi.yaml   Wi-Fi: web server + Home Assistant API
  secrets.yaml            Wi-Fi/API credentials (git-ignored, create your own)
src/co2_monitor/          logger and dashboard
  cli.py                  entry point (serial → CSV → dashboard)
  parsing.py              parse firmware DATA lines
  storage.py              CSV log read/append
  trends.py               time-bucketing for trend lines
  dashboard.py            rich terminal dashboard
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

## Logger

```bash
uv run co2-monitor                         # dashboard, appends to data/co2_log.csv
uv run co2-monitor --port /dev/ttyACM1 --out data/office.csv
uv run co2-monitor --plain                 # one line per reading
```

The log is append-only CSV (`timestamp,co2_ppm,temp_c,rh_percent`). On startup
the last 24 h are loaded from it so the trend lines and stats survive restarts.
`--plain` is used automatically when output isn't a terminal.

Only one program can use the serial port at a time; close `esphome logs` or any
serial monitor first.

## Development

```bash
uv sync
uv run pytest
```
