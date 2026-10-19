"""Live terminal dashboard built with rich."""

import datetime
import threading
from collections import deque

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from co2_monitor.trends import bucket_means, fill_single_gaps

SPARK_CHARS = "▁▂▃▄▅▆▇█"
TREND_WIDTH = 60  # characters per trend line
HISTORY_SPAN = datetime.timedelta(hours=24)  # longest trend window
STALE_AFTER_S = 90  # warn if no reading for this long


def co2_status(ppm):
    if ppm < 800:
        return "Good", "green"
    if ppm < 1200:
        return "Moderate", "yellow"
    if ppm < 2000:
        return "Poor, ventilate", "red"
    return "Very poor, ventilate now", "bold red"


def temp_status(c):
    if c < 18:
        return "Cool", "cyan"
    if c > 26:
        return "Warm", "yellow"
    return "Comfortable", "green"


def rh_status(rh):
    if rh < 30:
        return "Dry", "yellow"
    if rh > 60:
        return "Humid", "yellow"
    return "Comfortable", "green"


def format_duration(seconds):
    return str(datetime.timedelta(seconds=int(seconds)))


def sparkline(values):
    """Colour-coded sparkline; missing buckets are drawn as a dim dot."""
    present = [v for v in values if v is not None]
    lo, hi = min(present), max(present)
    text = Text()
    for v in values:
        if v is None:
            text.append("·", style="dim")
            continue
        idx = round((v - lo) / (hi - lo) * (len(SPARK_CHARS) - 1)) if hi > lo else 3
        text.append(SPARK_CHARS[idx], style=co2_status(v)[1])
    return text, lo, hi


def axis(width, left, middle, right):
    """A row of `width` characters with labels at the left edge, centre and right edge."""
    chars = [" "] * width
    mid = (width - len(middle)) // 2
    for pos, label in ((0, left), (mid, middle), (width - len(right), right)):
        chars[pos : pos + len(label)] = label
    return "".join(chars)


class Dashboard:
    """Live terminal view of a co2-monitor server's data.

    rich calls __rich__ on every refresh (from its own thread), so timers stay
    current; the lock keeps that from racing with sync().
    """

    METRICS = [
        # label, unit, format, status function; order matches Reading fields after timestamp
        ("CO₂", "ppm", "{:.0f}", co2_status),
        ("Temperature", "°C", "{:.1f}", temp_status),
        ("Humidity", "% RH", "{:.1f}", rh_status),
    ]

    # title, span, axis labels
    WINDOWS = [
        ("Last 30 min", datetime.timedelta(minutes=30), ("-30m", "-15m", "now")),
        ("Last 24 h", datetime.timedelta(hours=24), ("-24h", "-12h", "now")),
    ]

    def __init__(self, source):
        self.source = source  # shown in the subtitle, e.g. the server URL
        self.history = deque()  # Readings, oldest first
        self.status = None  # latest /api/status payload
        self.error = None  # last error talking to the server, if the last poll failed
        self.clock_offset = datetime.timedelta(0)  # server clock minus local clock
        self._lock = threading.Lock()

    def sync(self, status, readings, reset=False):
        """Apply a successful poll: server status plus any new readings."""
        with self._lock:
            if reset:
                self.history.clear()
            self.history.extend(readings)
            if self.history:
                cutoff = self.history[-1].timestamp - HISTORY_SPAN
                while self.history[0].timestamp <= cutoff:
                    self.history.popleft()
            self.status = status
            server_time = datetime.datetime.fromisoformat(status["server_time"])
            self.clock_offset = server_time - datetime.datetime.now()
            self.error = None

    def set_error(self, message):
        with self._lock:
            self.error = message

    def now(self):
        """Current time on the server's clock, so ages are right across machines."""
        return datetime.datetime.now() + self.clock_offset

    def _readings(self, latest):
        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim", min_width=12)
        table.add_column(justify="right", min_width=6)
        table.add_column(min_width=5)
        table.add_column()
        for i, (label, unit, fmt, status_fn) in enumerate(self.METRICS, start=1):
            value = latest[i]
            status, style = status_fn(value)
            table.add_row(
                label,
                Text(fmt.format(value), style=f"bold {style}"),
                unit,
                Text(f"● {status}", style=style),
            )
        return table

    def _stats(self, title, rows):
        table = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False, header_style="dim")
        table.add_column(Text(title, style="bold"), style="dim", min_width=12)
        for col in ("Min", "Avg", "Max"):
            table.add_column(col, justify="right", min_width=6)
        table.add_column("")
        for i, (label, unit, fmt, _) in enumerate(self.METRICS, start=1):
            values = [row[i] for row in rows]
            table.add_row(
                label,
                fmt.format(min(values)),
                fmt.format(sum(values) / len(values)),
                fmt.format(max(values)),
                unit,
            )
        return table

    def _trend(self, rows, now, span, labels):
        values = bucket_means(rows, now, span, TREND_WIDTH)
        if span / TREND_WIDTH <= datetime.timedelta(seconds=60):
            values = fill_single_gaps(values)
        spark, _, _ = sparkline(values)
        # Label the ends with the first and most recent readings in the window.
        first_label = f"{rows[0][1]:.0f} "
        return Group(
            Text("CO₂ trend (· = no data)", style="dim"),
            Text.assemble((first_label, "dim"), spark, (f" {rows[-1][1]:.0f} ppm", "dim")),
            Text(" " * len(first_label) + axis(TREND_WIDTH, *labels), style="dim"),
        )

    def _windows(self, now):
        """Stats table plus CO2 trend for each time window that has data."""
        parts = []
        for title, span, labels in self.WINDOWS:
            rows = [row for row in self.history if now - span < row[0] <= now]
            if not rows:
                continue
            parts += [
                self._stats(title, rows),
                Text(""),
                self._trend(rows, now, span, labels),
                Text(""),
            ]
        return parts

    def _status_lines(self, now):
        lines = []
        if self.error is not None:
            lines.append(Text(f"Can't reach the server: {self.error} (retrying)", style="bold red"))
        status = self.status
        serial_ok = status is None or status["serial_connected"]
        if status is not None and not serial_ok:
            error = status["serial_error"] or "not connected"
            lines.append(Text(f"Server can't read {status['device']}: {error}", style="bold red"))

        if self.history:
            latest = self.history[-1]
            ago = (now - latest.timestamp).total_seconds()
            line = f"Last reading {latest.timestamp:%H:%M:%S} ({ago:.0f} s ago)"
            if self.status is not None:
                started = datetime.datetime.fromisoformat(self.status["started_at"])
                line += f" · server up {format_duration((now - started).total_seconds())}"
            lines.append(Text(line, style="dim"))
            if ago > STALE_AFTER_S and self.error is None and serial_ok:
                lines.append(Text(f"No new data for {ago:.0f} s", style="bold red"))
        elif self.status is not None:
            lines.append(Text("Waiting for first reading (sensor reports every 30 s)", style="dim"))
        elif self.error is None:
            lines.append(Text(f"Connecting to {self.source}…", style="dim"))
        return lines

    def __rich__(self):
        with self._lock:
            now = self.now()
            latest = self.history[-1] if self.history else None
            parts = []
            if latest is not None:
                parts += [self._readings(latest), Text("")]
            parts += self._windows(now)
            parts += self._status_lines(now)
        border = "dim" if latest is None else co2_status(latest.co2_ppm)[1]
        return Panel(
            Group(*parts),
            title="[bold]CO₂ Monitor[/bold]",
            subtitle=f"[dim]{self.source} · Ctrl+C to stop[/dim]",
            border_style=border,
            expand=False,
            padding=(1, 2),
        )
