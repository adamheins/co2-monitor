"""Time-bucketing of readings for the trend lines."""


def bucket_means(history, now, span, n):
    """Mean CO2 in each of n equal time buckets covering (now - span, now]; None where empty."""
    start, width = now - span, span / n
    sums, counts = [0.0] * n, [0] * n
    for ts, ppm, *_ in history:
        if ts <= start or ts > now:
            continue
        i = min(int((ts - start) / width), n - 1)
        sums[i] += ppm
        counts[i] += 1
    return [s / c if c else None for s, c in zip(sums, counts)]


def bucket_readings(readings, end, span, n):
    """Average readings into n equal time buckets covering (end - span, end].

    Returns (bucket_midpoint, count, co2, temp, rh) for each non-empty bucket, oldest first.
    """
    start, width = end - span, span / n
    acc = {}  # bucket index -> [count, co2 sum, temp sum, rh sum]
    for r in readings:
        if r.timestamp <= start or r.timestamp > end:
            continue
        i = min(int((r.timestamp - start) / width), n - 1)
        a = acc.setdefault(i, [0, 0.0, 0.0, 0.0])
        a[0] += 1
        a[1] += r.co2_ppm
        a[2] += r.temp_c
        a[3] += r.rh_percent
    return [
        (start + width * (i + 0.5), c, co2 / c, temp / c, rh / c)
        for i, (c, co2, temp, rh) in sorted(acc.items())
    ]


def fill_single_gaps(values):
    """Fill isolated empty buckets with the previous value.

    When a bucket is about as wide as the 30 s reading interval, timing jitter
    leaves occasional buckets empty; those aren't real gaps in the data.
    """
    filled = list(values)
    for i in range(1, len(values)):
        nxt_ok = i == len(values) - 1 or values[i + 1] is not None
        if values[i] is None and values[i - 1] is not None and nxt_ok:
            filled[i] = values[i - 1]
    return filled
