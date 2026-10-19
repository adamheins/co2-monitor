"""Client: terminal dashboard fed by a co2-monitor server."""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

from rich.live import Live

from co2_monitor.dashboard import Dashboard
from co2_monitor.models import Reading, format_reading


class ServerClient:
    def __init__(self, base_url, timeout=5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path):
        with urllib.request.urlopen(self.base_url + path, timeout=self.timeout) as resp:
            return json.load(resp)

    def status(self):
        return self._get("/api/status")

    def readings(self, after=0):
        return self._get(f"/api/readings?after={after}")


class Syncer:
    """Keeps a Dashboard in step with the server, fetching only readings it hasn't seen."""

    def __init__(self, client, dashboard):
        self.client, self.dashboard = client, dashboard
        self.run_id = None
        self.last_seq = 0

    def poll(self):
        """Fetch status and new readings. Returns (new readings, whether history was reset)."""
        status = self.client.status()
        data = self.client.readings(after=self.last_seq)
        reset = data["run_id"] != self.run_id
        if reset and self.last_seq:
            data = self.client.readings(after=0)  # server restarted: start over
        pairs = [(r["seq"], Reading.from_json(r)) for r in data["readings"]]
        readings = [r for _, r in pairs]
        self.dashboard.sync(status, readings, reset=reset)
        self.run_id = data["run_id"]
        if pairs:
            self.last_seq = pairs[-1][0]
        elif reset:
            self.last_seq = 0
        return readings, reset


def run(server, interval, plain):
    dashboard = Dashboard(server)
    syncer = Syncer(ServerClient(server), dashboard)
    live = None
    if plain:
        print(f"Following {server} (Ctrl+C to stop)", flush=True)
    else:
        live = Live(dashboard, refresh_per_second=1)
        live.start()

    last_error = None
    try:
        while True:
            try:
                new, reset = syncer.poll()
                last_error = None
                if plain:
                    # After (re)connecting, show the latest reading rather than the full 24 h.
                    for reading in new[-1:] if reset else new:
                        print(format_reading(reading), flush=True)
            except (OSError, ValueError, KeyError) as e:  # URLError is an OSError
                message = str(getattr(e, "reason", e))
                dashboard.set_error(message)
                if plain and message != last_error:
                    print(f"Can't reach {server}: {message} (retrying)", file=sys.stderr, flush=True)
                last_error = message
            time.sleep(interval)
    finally:
        if live is not None:
            live.stop()


def main():
    parser = argparse.ArgumentParser(description="Live dashboard for a co2-monitor server.")
    parser.add_argument(
        "--server", default="http://127.0.0.1:8765", help="server URL (default: %(default)s)"
    )
    parser.add_argument(
        "--interval", type=float, default=5, help="seconds between polls (default: %(default)s)"
    )
    parser.add_argument(
        "--plain", action="store_true", help="print one line per reading instead of the dashboard"
    )
    args = parser.parse_args()
    plain = args.plain or not sys.stdout.isatty()

    try:
        run(args.server, args.interval, plain)
    except KeyboardInterrupt:
        pass
