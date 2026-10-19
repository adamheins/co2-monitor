import datetime
import io

from rich.console import Console

from co2_monitor.dashboard import Dashboard, axis, co2_status, sparkline
from co2_monitor.models import Reading


def render(renderable):
    buf = io.StringIO()
    Console(file=buf, width=90, color_system=None).print(renderable)
    return buf.getvalue()


def make_status(now, connected=True, error=None):
    return {
        "server_time": now.isoformat(),
        "started_at": (now - datetime.timedelta(hours=1)).isoformat(timespec="seconds"),
        "device": "/dev/ttyACM0",
        "serial_connected": connected,
        "serial_error": error,
    }


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


def test_connecting_state():
    out = render(Dashboard("http://server:8765"))
    assert "Connecting to http://server:8765" in out


def test_waiting_for_first_reading():
    dash = Dashboard("http://server:8765")
    dash.sync(make_status(datetime.datetime.now()), [])
    out = render(dash)
    assert "Waiting for first reading" in out
    assert "Last 30 min" not in out


def test_renders_readings_stats_and_trends():
    now = datetime.datetime.now()
    history = [
        Reading(now - datetime.timedelta(minutes=m), 600 + m, 22.0, 50.0) for m in range(120, 0, -1)
    ]
    history.append(Reading(now, 650, 22.5, 48.0))
    dash = Dashboard("http://server:8765")
    dash.sync(make_status(now), history)
    out = render(dash)
    for expected in ("650", "Last 30 min", "Last 24 h", "CO₂ trend", "server up 1:00:00"):
        assert expected in out
    # Trend ends are labelled with the first and latest readings in each window.
    assert "629 " in out  # first reading inside the last 30 min
    assert "720 " in out  # first reading inside the last 24 h


def test_ages_use_server_clock():
    # Server clock is 10 minutes ahead of ours; a reading stamped "server now" is 0 s old.
    server_now = datetime.datetime.now() + datetime.timedelta(minutes=10)
    dash = Dashboard("http://server:8765")
    dash.sync(make_status(server_now), [Reading(server_now, 700, 22.0, 50.0)])
    out = render(dash)
    assert "(0 s ago)" in out
    assert "No new data" not in out


def test_errors_are_shown():
    now = datetime.datetime.now()
    dash = Dashboard("http://server:8765")
    dash.sync(make_status(now, connected=False, error="device unplugged"), [])
    dash.set_error("Connection refused")
    out = render(dash)
    assert "Can't reach the server: Connection refused" in out
    assert "Server can't read /dev/ttyACM0: device unplugged" in out


def test_reset_replaces_history():
    now = datetime.datetime.now()
    dash = Dashboard("http://server:8765")
    dash.sync(make_status(now), [Reading(now, 700, 22.0, 50.0)])
    dash.sync(make_status(now), [Reading(now, 900, 22.0, 50.0)], reset=True)
    assert [r.co2_ppm for r in dash.history] == [900]
