import datetime

from co2_monitor.storage import CsvLog, load_history

T0 = datetime.datetime(2026, 10, 3, 17, 0, 0)


def test_new_log_gets_header_once(tmp_path):
    path = tmp_path / "sub" / "log.csv"
    with CsvLog(path) as log:
        log.append(T0, 680, 22.523, 55.71)
    with CsvLog(path) as log:
        log.append(T0 + datetime.timedelta(seconds=30), 700, 22.5, 55.0)
    assert path.read_text().splitlines() == [
        "timestamp,co2_ppm,temp_c,rh_percent",
        "2026-10-03T17:00:00,680,22.52,55.71",
        "2026-10-03T17:00:30,700,22.50,55.00",
    ]


def test_load_history_filters_by_time_and_skips_bad_rows(tmp_path):
    path = tmp_path / "log.csv"
    path.write_text(
        "timestamp,co2_ppm,temp_c,rh_percent\n"
        "2026-10-03T16:00:00,900,22.0,50.0\n"  # too old
        "2026-10-03T17:00:00,680,22.5,55.7\n"
        "garbage\n"
        "2026-10-03T17:00:30,nope,22.5,55.7\n"
        "2026-10-03T17:01:00,700,22.6,55.1\n"
    )
    history = load_history(path, since=T0 - datetime.timedelta(minutes=30))
    assert history == [
        (T0, 680.0, 22.5, 55.7),
        (T0 + datetime.timedelta(minutes=1), 700.0, 22.6, 55.1),
    ]


def test_load_history_missing_file(tmp_path):
    assert load_history(tmp_path / "missing.csv", since=T0) == []
