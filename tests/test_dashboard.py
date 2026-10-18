import datetime
import io

from rich.console import Console

from co2_monitor.dashboard import Dashboard, axis, co2_status, sparkline


def render(renderable):
    buf = io.StringIO()
    Console(file=buf, width=90, color_system=None).print(renderable)
    return buf.getvalue()


def test_co2_status_bands():
    assert co2_status(799)[0] == "Good"
    assert co2_status(800)[0] == "Moderate"
    assert co2_status(1200)[0] == "Poor, ventilate"
    assert co2_status(2000)[0] == "Very poor, ventilate now"


def test_axis_places_labels():
    assert axis(11, "-1h", "mid", "now") == "-1h mid now"


def test_sparkline_marks_missing_data():
    text, lo, hi = sparkline([400, None, 800])
    assert text.plain == "▁·█"
    assert (lo, hi) == (400, 800)


def test_waiting_state_without_history():
    out = render(Dashboard("/dev/ttyACM0", "log.csv"))
    assert "Waiting for first reading" in out
    assert "Last 30 min" not in out


def test_renders_readings_stats_and_trends():
    now = datetime.datetime.now()
    history = [
        (now - datetime.timedelta(minutes=m), 600 + m, 22.0, 50.0) for m in range(120, 0, -1)
    ]
    dash = Dashboard("/dev/ttyACM0", "log.csv", history)
    dash.update(now, 650, 22.5, 48.0)
    out = render(dash)
    for expected in ("650", "Last 30 min", "Last 24 h", "CO₂ trend", "1 reading ·"):
        assert expected in out
    # Trend ends are labelled with the first and latest readings in each window.
    assert "629 " in out  # first reading inside the last 30 min
    assert "720 " in out  # first reading inside the last 24 h
