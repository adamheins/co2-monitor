"""Server: reads the CO2 monitor over USB serial, logs to CSV and serves readings over HTTP.

Endpoints (all GET, JSON unless noted):
    /                        web dashboard (HTML)
    /api/status              server and sensor status, plus the latest reading
    /api/series?hours=H&points=P
                             readings over the last H hours averaged into at most P
                             time buckets, plus min/mean/max per measurement
    /api/readings?after=N    readings from the last 24 h with sequence number > N
    /api/readings.csv        the full CSV log (text/csv)

Sequence numbers restart when the server restarts; `run_id` in the status and
readings responses changes too, so clients know to fetch everything again.
"""

import argparse
import datetime
import errno
import json
import math
import socket
import sys
import threading
import time
import uuid
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import serial

from co2_monitor.models import Reading, format_reading
from co2_monitor.parsing import parse_line
from co2_monitor.storage import CsvLog, load_history
from co2_monitor.trends import bucket_readings

HISTORY_SPAN = datetime.timedelta(hours=24)  # kept in memory and served to clients
RECONNECT_DELAY_S = 5
READING_INTERVAL = datetime.timedelta(seconds=30)  # how often the firmware reports
MAX_SERIES_HOURS = 24 * 366
FIELDS = ("co2_ppm", "temp_c", "rh_percent")


class ReadingStore:
    """Thread-safe store of recent readings, each tagged with a sequence number."""

    def __init__(self, history=(), span=HISTORY_SPAN):
        self.span = span
        self.run_id = uuid.uuid4().hex
        self.started_at = datetime.datetime.now()
        self.serial_connected = False
        self.serial_error = None
        self._lock = threading.Lock()
        self._readings = deque()  # (seq, Reading), oldest first
        self._seq = 0
        for reading in history:
            self.add(reading)

    def add(self, reading):
        with self._lock:
            self._seq += 1
            self._readings.append((self._seq, reading))
            cutoff = reading.timestamp - self.span
            while self._readings[0][1].timestamp <= cutoff:
                self._readings.popleft()

    def after(self, seq):
        """(seq, Reading) pairs with sequence number greater than `seq`."""
        with self._lock:
            return [(s, r) for s, r in self._readings if s > seq]

    def latest(self):
        with self._lock:
            return self._readings[-1][1] if self._readings else None

    def set_serial_state(self, connected, error=None):
        """Record the serial connection state; returns True if it changed."""
        with self._lock:
            changed = (connected, error) != (self.serial_connected, self.serial_error)
            self.serial_connected, self.serial_error = connected, error
            return changed


class SerialReader(threading.Thread):
    """Reads the monitor's serial output, reconnecting if the device goes away."""

    def __init__(self, device, store, log, echo=True):
        super().__init__(daemon=True)
        self.device, self.store, self.log, self.echo = device, store, log, echo

    def handle_line(self, line):
        """Log and store a DATA line; returns the Reading, or None for other output."""
        values = parse_line(line)
        if values is None:
            return None
        reading = Reading(datetime.datetime.now(), *values)
        self.log.append(reading)
        self.store.add(reading)
        if self.echo:
            print(format_reading(reading), flush=True)
        return reading

    def run(self):
        while True:
            try:
                with serial.serial_for_url(self.device, 115200, timeout=5) as ser:
                    if self.store.set_serial_state(True):
                        print(f"Connected to {self.device}", flush=True)
                    while True:
                        raw = ser.readline()  # b"" on timeout
                        if raw:
                            self.handle_line(raw.decode(errors="ignore"))
            except (serial.SerialException, OSError) as e:
                if self.store.set_serial_state(False, str(e)):
                    print(
                        f"Can't read {self.device}: {e} (retrying every {RECONNECT_DELAY_S} s)",
                        flush=True,
                    )
                time.sleep(RECONNECT_DELAY_S)


class MonitorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store, log_path, device):
        self.store, self.log_path, self.device = store, Path(log_path), device
        super().__init__(address, Handler)

    def status(self):
        store, latest = self.store, self.store.latest()
        return {
            "run_id": store.run_id,
            "started_at": store.started_at.isoformat(timespec="seconds"),
            # Millisecond precision: browsers don't reliably parse microseconds.
            "server_time": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "device": self.device,
            "serial_connected": store.serial_connected,
            "serial_error": store.serial_error,
            "latest": latest.to_json() if latest else None,
        }

    def readings_since(self, since):
        """Readings newer than `since`: from memory if recent enough, else from the CSV."""
        if since >= datetime.datetime.now() - self.store.span:
            return [r for _, r in self.store.after(0) if r.timestamp > since]
        return load_history(self.log_path, since)

    def series(self, hours, points):
        end = datetime.datetime.now()
        span = datetime.timedelta(hours=hours)
        # Bucket width is a whole number of reporting intervals, so every bucket
        # averages the same number of readings (and none is narrower than one).
        per_bucket = max(1, math.ceil(span / (points * READING_INTERVAL)))
        n = max(1, int(span // (per_bucket * READING_INTERVAL)))
        readings = self.readings_since(end - span)
        buckets = bucket_readings(readings, end, span, n)
        stats = None
        if readings:
            stats = {}
            for i, field in enumerate(FIELDS, start=1):
                values = [r[i] for r in readings]
                stats[field] = {
                    "min": min(values),
                    "mean": round(sum(values) / len(values), 2),
                    "max": max(values),
                }
        return {
            "start": (end - span).isoformat(timespec="milliseconds"),
            "end": end.isoformat(timespec="milliseconds"),
            "bucket_s": (span / n).total_seconds(),
            "points": [
                {
                    "t": t.isoformat(timespec="milliseconds"),
                    "n": count,
                    "co2_ppm": round(co2, 1),
                    "temp_c": round(temp, 2),
                    "rh_percent": round(rh, 2),
                }
                for t, count, co2, temp, rh in buckets
            ],
            "stats": stats,
        }


class Handler(BaseHTTPRequestHandler):
    server: MonitorHTTPServer

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            page = resources.files("co2_monitor").joinpath("static/index.html").read_bytes()
            self._send(page, "text/html; charset=utf-8")
        elif url.path == "/api/status":
            self._send_json(self.server.status())
        elif url.path == "/api/series":
            self._series(parse_qs(url.query))
        elif url.path == "/api/readings":
            self._readings(parse_qs(url.query))
        elif url.path == "/api/readings.csv":
            self._csv()
        elif url.path == "/api":
            self._send_json(
                {
                    "endpoints": [
                        "/api/status",
                        "/api/series?hours=H&points=P",
                        "/api/readings?after=N",
                        "/api/readings.csv",
                    ]
                }
            )
        else:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _series(self, query):
        try:
            hours = float(query.get("hours", ["24"])[0])
            points = int(query.get("points", ["300"])[0])
        except ValueError:
            hours = points = None
        if hours is None or points is None or not 0 < hours <= MAX_SERIES_HOURS:
            self._send_json(
                {"error": f"hours must be a number in (0, {MAX_SERIES_HOURS}], points an integer"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._send_json(self.server.series(hours, max(10, min(points, 2000))))

    def _readings(self, query):
        try:
            after = int(query.get("after", ["0"])[0])
        except ValueError:
            self._send_json({"error": "after must be an integer"}, HTTPStatus.BAD_REQUEST)
            return
        store = self.server.store
        readings = [{"seq": seq, **r.to_json()} for seq, r in store.after(after)]
        self._send_json({"run_id": store.run_id, "readings": readings})

    def _csv(self):
        try:
            body = self.server.log_path.read_bytes()
        except FileNotFoundError:
            self._send_json({"error": "no log yet"}, HTTPStatus.NOT_FOUND)
            return
        self._send(body, "text/csv", {"Content-Disposition": "attachment; filename=co2_log.csv"})

    def _send_json(self, obj, status=HTTPStatus.OK):
        self._send(json.dumps(obj).encode(), "application/json", status=status)

    def _send(self, body, content_type, headers=None, status=HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # clients poll every few seconds; keep the console for readings


def local_ip():
    """This machine's primary network address, or None if it has no network."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # connect() on a UDP socket sends nothing; it just picks the outgoing
            # interface. 192.0.2.1 is a reserved documentation address.
            s.connect(("192.0.2.1", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def dashboard_urls(host, port):
    """URLs to reach the dashboard: (network URLs, this-machine URL)."""
    suffix = "" if port == 80 else f":{port}"
    if host in ("0.0.0.0", ""):
        ip = local_ip()
        return ([f"http://{ip}{suffix}/"] if ip else []), f"http://localhost{suffix}/"
    return [f"http://{host}{suffix}/"], None


BIND_PERMISSION_HELP = """\
Permission denied listening on port {port}: on Linux, ports below 1024 need extra
permission. Either use another port (e.g. --port 8080), or allow it, for example:
  sudo sysctl net.ipv4.ip_unprivileged_port_start={port}
  (to keep it after reboots, put "net.ipv4.ip_unprivileged_port_start={port}"
  in /etc/sysctl.d/99-unprivileged-ports.conf)"""


def main():
    parser = argparse.ArgumentParser(
        description="Read the CO2 monitor over USB, log readings to CSV and serve them over HTTP."
    )
    parser.add_argument(
        "--device", default="/dev/ttyACM0", help="monitor's serial device (default: %(default)s)"
    )
    parser.add_argument(
        "--out", default="data/co2_log.csv", help="CSV file to append to (default: %(default)s)"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="address to listen on; 127.0.0.1 for this machine only (default: %(default)s, "
        "all interfaces)",
    )
    parser.add_argument("--port", type=int, default=8080, help="HTTP port (default: %(default)s)")
    args = parser.parse_args()

    # Preload recent readings so clients get the full 24 h after a restart.
    store = ReadingStore(load_history(args.out, datetime.datetime.now() - HISTORY_SPAN))
    # Bind before touching the serial device or the log, so a port problem fails fast.
    try:
        httpd = MonitorHTTPServer((args.host, args.port), store, args.out, args.device)
    except PermissionError:
        sys.exit(BIND_PERMISSION_HELP.format(port=args.port))
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            sys.exit(f"Port {args.port} is already in use; pick another with --port.")
        raise

    network, local = dashboard_urls(args.host, args.port)
    if network:
        print(f"Dashboard at {', '.join(network)}" + (f"  (on this machine: {local})" if local else ""))
    else:
        print(f"Dashboard at {local} (no network address found)")
    print(f"Logging {args.device} to {args.out} (Ctrl+C to stop)", flush=True)

    with CsvLog(args.out) as log:
        SerialReader(args.device, store, log).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
