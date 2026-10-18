"""Command-line entry point: read the serial port, log to CSV, show the dashboard."""

import argparse
import datetime
import sys

import serial
from rich.live import Live

from co2_monitor.dashboard import HISTORY_SPAN, Dashboard
from co2_monitor.parsing import parse_line
from co2_monitor.storage import CsvLog, load_history


def run(port, out, plain):
    # Preload recent readings so the trend lines survive restarts.
    history = load_history(out, datetime.datetime.now() - HISTORY_SPAN)

    with serial.Serial(port, 115200, timeout=60) as ser, CsvLog(out) as log:
        dashboard = Dashboard(port, out, history)
        live = None
        if plain:
            print(f"Logging from {port} to {out} (Ctrl+C to stop)", flush=True)
        else:
            live = Live(dashboard, refresh_per_second=1)
            live.start()

        try:
            for raw in ser:
                reading = parse_line(raw.decode(errors="ignore"))
                if reading is None:
                    continue
                now = datetime.datetime.now()
                log.append(now, *reading)
                dashboard.update(now, *reading)
                if plain:
                    co2, temp, rh = reading
                    print(
                        f"{now:%Y-%m-%d %H:%M:%S}  CO₂ {co2:5.0f} ppm  "
                        f"Temp {temp:5.1f} °C  RH {rh:5.1f} %",
                        flush=True,
                    )
        finally:
            if live is not None:
                live.stop()


def main():
    parser = argparse.ArgumentParser(description="Log CO2 monitor readings to CSV.")
    parser.add_argument("--port", default="/dev/ttyACM0", help="serial port")
    parser.add_argument(
        "--out", default="data/co2_log.csv", help="CSV file to append to (default: %(default)s)"
    )
    parser.add_argument(
        "--plain", action="store_true", help="print one line per reading instead of the dashboard"
    )
    args = parser.parse_args()
    plain = args.plain or not sys.stdout.isatty()

    try:
        run(args.port, args.out, plain)
    except KeyboardInterrupt:
        pass
