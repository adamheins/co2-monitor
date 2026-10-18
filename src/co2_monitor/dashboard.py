"""Live terminal dashboard built with rich."""

import datetime
import time
from collections import deque

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from co2_monitor.trends import bucket_means, fill_single_gaps

SPARK_CHARS = "▁▂▃▄▅▆▇█"
TREND_WIDTH = 60  # characters per trend line
HISTORY_SPAN = datetime.timedelta(hours=24)  # longest trend; also how much CSV is preloaded
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
    """Live terminal view; rich calls __rich__ on every refresh, so timers stay current."""

    METRICS = [
        # key, label, unit, format, status function; order matches history rows
        ("co2", "CO₂", "ppm", "{:.0f}", co2_status),
        ("temp", "Temperature", "°C", "{:.1f}", temp_status),
        ("rh", "Humidity", "% RH", "{:.1f}", rh_status),
    ]

    # title, span, axis labels
    WINDOWS = [
        ("Last 30 min", datetime.timedelta(minutes=30), ("-30m", "-15m", "now")),
        ("Last 24 h", datetime.timedelta(hours=24), ("-24h", "-12h", "now")),
    ]

    def __init__(self, port, out, history=()):
        self.port, self.out = port, out
        self.start = time.monotonic()
        self.latest = None  # dict of metric -> value
        self.latest_at = None  # datetime of latest reading
        self.latest_mono = None
        self.n_readings = 0  # readings received this run
        self.history = deque(history)  # (datetime, co2, temp, rh), oldest first

    def update(self, ts, co2, temp, rh):
        self.latest = {"co2": co2, "temp": temp, "rh": rh}
        self.latest_at, self.latest_mono = ts, time.monotonic()
        self.n_readings += 1
        self.history.append((ts, co2, temp, rh))
        while self.history and self.history[0][0] <= ts - HISTORY_SPAN:
            self.history.popleft()

    def _readings(self):
        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim", min_width=12)
        table.add_column(justify="right", min_width=6)
        table.add_column(min_width=5)
        table.add_column()
        assert self.latest is not None
        for key, label, unit, fmt, status_fn in self.METRICS:
            value = self.latest[key]
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
        for i, (_, label, unit, fmt, _) in enumerate(self.METRICS, start=1):
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

    def _windows(self):
        """Stats table plus CO2 trend for each time window that has data."""
        now = datetime.datetime.now()
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

    def _status_line(self):
        running = format_duration(time.monotonic() - self.start)
        if self.latest_mono is None:
            return Text(
                f"Waiting for first reading (sensor reports every 30 s) · running {running}",
                style="dim",
            )
        ago = time.monotonic() - self.latest_mono
        text = Text(
            f"Last reading {self.latest_at:%H:%M:%S} ({ago:.0f} s ago) · "
            f"{self.n_readings} reading{'s' if self.n_readings != 1 else ''} · running {running}",
            style="dim",
        )
        if ago > STALE_AFTER_S:
            text.append(f"\nNo data for {ago:.0f} s, check the USB connection", style="bold red")
        return text

    def __rich__(self):
        parts = []
        if self.latest is not None:
            parts += [self._readings(), Text("")]
        parts += self._windows()
        parts.append(self._status_line())
        body = Group(*parts)
        border = "dim" if self.latest is None else co2_status(self.latest["co2"])[1]
        return Panel(
            body,
            title="[bold]CO₂ Monitor[/bold]",
            subtitle=f"[dim]{self.port} → {self.out} · Ctrl+C to stop[/dim]",
            border_style=border,
            expand=False,
            padding=(1, 2),
        )
