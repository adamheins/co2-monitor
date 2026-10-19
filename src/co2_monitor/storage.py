"""CSV log of readings: timestamp,co2_ppm,temp_c,rh_percent."""

import csv
import datetime
from pathlib import Path

from co2_monitor.models import Reading

HEADER = ["timestamp", "co2_ppm", "temp_c", "rh_percent"]


def load_history(path, since):
    """Readings from an existing log CSV that are newer than `since`."""
    history = []
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    ts = datetime.datetime.fromisoformat(row["timestamp"])
                    if ts > since:
                        history.append(
                            Reading(
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

    def append(self, reading):
        # Same precision as the firmware prints.
        self._write(
            [
                reading.timestamp.isoformat(timespec="seconds"),
                f"{reading.co2_ppm:.0f}",
                f"{reading.temp_c:.2f}",
                f"{reading.rh_percent:.2f}",
            ]
        )

    def _write(self, row):
        self._writer.writerow(row)
        self._file.flush()

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
