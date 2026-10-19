import datetime
import threading
import urllib.error
import urllib.request

import pytest

from co2_monitor.client import ServerClient
from co2_monitor.models import Reading
from co2_monitor.server import MonitorHTTPServer, ReadingStore, SerialReader
from co2_monitor.storage import CsvLog

T0 = datetime.datetime(2026, 10, 3, 17, 0, 0)


def reading(minutes, co2=700):
    return Reading(T0 + datetime.timedelta(minutes=minutes), co2, 22.0, 50.0)


def test_store_assigns_sequence_numbers():
    store = ReadingStore([reading(0), reading(1)])
    store.add(reading(2))
    assert [s for s, _ in store.after(0)] == [1, 2, 3]
    assert [s for s, _ in store.after(2)] == [3]
    assert store.latest() == reading(2)


def test_store_drops_readings_older_than_span():
    store = ReadingStore(span=datetime.timedelta(minutes=10))
    for m in (0, 5, 10, 15):
        store.add(reading(m))
    assert [r.timestamp.minute for _, r in store.after(0)] == [10, 15]


def test_serial_state_change_detection():
    store = ReadingStore()
    assert store.set_serial_state(True)
    assert not store.set_serial_state(True)
    assert store.set_serial_state(False, "gone")


def test_handle_line_logs_and_stores(tmp_path):
    store = ReadingStore()
    with CsvLog(tmp_path / "log.csv") as log:
        reader = SerialReader("loop://", store, log, echo=False)
        assert reader.handle_line("[I][app:100]: setup") is None
        assert reader.handle_line("[I][main:042]: DATA,nan,nan,nan") is None
        r = reader.handle_line("\x1b[0;32m[I][main:042]: DATA,742,22.41,38.17\x1b[0m")
    assert r is not None and (r.co2_ppm, r.temp_c, r.rh_percent) == (742, 22.41, 38.17)
    assert store.latest() == r
    assert (tmp_path / "log.csv").read_text().splitlines()[1].endswith(",742,22.41,38.17")


@pytest.fixture
def server(tmp_path):
    log_path = tmp_path / "log.csv"
    log_path.write_text("timestamp,co2_ppm,temp_c,rh_percent\n2026-10-03T17:00:00,700,22.00,50.00\n")
    store = ReadingStore([reading(0), reading(1, co2=750)])
    httpd = MonitorHTTPServer(("127.0.0.1", 0), store, log_path, "/dev/ttyACM0")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, ServerClient(f"http://127.0.0.1:{httpd.server_address[1]}")
    httpd.shutdown()
    httpd.server_close()


def test_status_endpoint(server):
    httpd, client = server
    status = client.status()
    assert status["run_id"] == httpd.store.run_id
    assert status["device"] == "/dev/ttyACM0"
    assert status["serial_connected"] is False
    assert status["latest"]["co2_ppm"] == 750
    datetime.datetime.fromisoformat(status["server_time"])  # parseable


def test_readings_endpoint(server):
    httpd, client = server
    data = client.readings()
    assert data["run_id"] == httpd.store.run_id
    assert [r["seq"] for r in data["readings"]] == [1, 2]
    assert data["readings"][1]["timestamp"] == "2026-10-03T17:01:00"
    assert [r["seq"] for r in client.readings(after=1)["readings"]] == [2]


def test_csv_endpoint(server):
    _, client = server
    with urllib.request.urlopen(client.base_url + "/api/readings.csv") as resp:
        assert resp.headers["Content-Type"] == "text/csv"
        assert resp.read().decode().startswith("timestamp,co2_ppm")


def test_bad_requests(server):
    _, client = server
    for path in ("/api/readings?after=abc", "/api/series?hours=0", "/api/series?hours=nan",
                 "/api/series?hours=1&points=x"):
        with pytest.raises(urllib.error.HTTPError) as e:
            client._get(path)
        assert e.value.code == 400, path
    with pytest.raises(urllib.error.HTTPError) as e:
        client._get("/nope")
    assert e.value.code == 404


def test_dashboard_page(server):
    _, client = server
    with urllib.request.urlopen(client.base_url + "/") as resp:
        assert resp.headers["Content-Type"].startswith("text/html")
        assert "<title>CO₂ Monitor</title>" in resp.read().decode()


@pytest.fixture
def live_server(tmp_path):
    """Server whose store and CSV hold readings relative to the current time."""
    now = datetime.datetime.now().replace(microsecond=0)
    recent = [Reading(now - datetime.timedelta(minutes=m), 600 + m, 22.0, 50.0) for m in (50, 40, 1)]
    old = Reading(now - datetime.timedelta(days=3), 1000, 20.0, 40.0)
    log_path = tmp_path / "log.csv"
    with CsvLog(log_path) as log:
        for r in [old, *recent]:
            log.append(r)
    httpd = MonitorHTTPServer(("127.0.0.1", 0), ReadingStore(recent), log_path, "/dev/ttyACM0")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield ServerClient(f"http://127.0.0.1:{httpd.server_address[1]}")
    httpd.shutdown()
    httpd.server_close()


def test_series_from_memory(live_server):
    data = live_server._get("/api/series?hours=1&points=10")
    assert data["bucket_s"] == 360
    assert [p["co2_ppm"] for p in data["points"]] == [650, 640, 601]
    assert data["stats"]["co2_ppm"] == {"min": 601, "mean": 630.33, "max": 650}


def test_series_from_csv_for_long_ranges(live_server):
    data = live_server._get("/api/series?hours=96&points=4")
    co2 = [p["co2_ppm"] for p in data["points"]]
    assert co2[0] == 1000  # the 3-day-old reading only exists in the CSV
    assert data["stats"]["co2_ppm"]["max"] == 1000


def test_series_never_uses_buckets_shorter_than_reading_interval(live_server):
    data = live_server._get("/api/series?hours=1&points=2000")
    assert data["bucket_s"] == 30


def test_series_buckets_are_whole_reading_intervals(live_server):
    # 6 h over 480 points would be 45 s buckets; rounded up to 2 readings (60 s) each.
    data = live_server._get("/api/series?hours=6&points=480")
    assert data["bucket_s"] == 60


def test_series_empty_range(live_server):
    data = live_server._get("/api/series?hours=0.01")
    assert data["points"] == [] and data["stats"] is None
