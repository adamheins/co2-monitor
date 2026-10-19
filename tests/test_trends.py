import datetime

from co2_monitor.models import Reading
from co2_monitor.trends import bucket_means, bucket_readings, fill_single_gaps

NOW = datetime.datetime(2026, 10, 3, 18, 0, 0)


def ago(minutes):
    return NOW - datetime.timedelta(minutes=minutes)


def test_bucket_means_averages_and_marks_empty_buckets():
    history = [
        (ago(70), 999, 0, 0),  # outside the window
        (ago(55), 600, 0, 0),
        (ago(50), 700, 0, 0),
        (ago(5), 800, 0, 0),
        (NOW, 900, 0, 0),
    ]
    # 4 buckets of 15 min covering the last hour
    values = bucket_means(history, NOW, datetime.timedelta(hours=1), 4)
    assert values == [650, None, None, 850]


def test_bucket_readings_averages_every_field_and_skips_empty_buckets():
    readings = [
        Reading(ago(70), 999, 99, 99),  # outside the window
        Reading(ago(55), 600, 20, 40),
        Reading(ago(50), 700, 22, 50),
        Reading(NOW, 900, 24, 60),
    ]
    buckets = bucket_readings(readings, NOW, datetime.timedelta(hours=1), 4)
    assert buckets == [
        (ago(52.5), 2, 650, 21, 45),
        (ago(7.5), 1, 900, 24, 60),
    ]


def test_fill_single_gaps_fills_isolated_gaps_only():
    n = None
    assert fill_single_gaps([1, n, 3, n, n, 6, n]) == [1, 1, 3, n, n, 6, 6]


def test_fill_single_gaps_keeps_leading_gaps():
    n = None
    assert fill_single_gaps([n, n, 2, 3]) == [n, n, 2, 3]
