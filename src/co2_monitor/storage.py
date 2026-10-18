"""CSV log of readings: timestamp,co2_ppm,temp_c,rh_percent."""

import csv
import datetime
from pathlib import Path

HEADER = ["timestamp", "co2_ppm", "temp_c", "rh_percent"]


def load_history(path, since):
    """(timestamp, co2, temp, rh) rows from an existing log CSV, newer than `since`."""
    history = []
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    ts = datetime.datetime.fromisoformat(row["timestamp"])
                    if ts > since:
                        history.append(
                            (
                                ts,
                                float(row["co2_ppm"]),
                                float(row["temp_c"]),
                                float(row["rh_percent"]),
                            )
                        )
                except (KeyError, TypeError, ValueError):
                    continue
    except FileNotFoundError:
        pass
    return history


class CsvLog:
    """Append-only CSV log; writes the header when the file is new or empty."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists() or self.path.stat().st_size == 0
        self._file = open(self.path, "a", newline="")
        self._writer = csv.writer(self._file)
        if new_file:
            self._write(HEADER)

    def append(self, ts, co2, temp, rh):
        # Same precision as the firmware prints.
        self._write([ts.isoformat(timespec="seconds"), f"{co2:.0f}", f"{temp:.2f}", f"{rh:.2f}"])

    def _write(self, row):
        self._writer.writerow(row)
        self._file.flush()

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
