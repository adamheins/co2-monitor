"""A single sensor reading, with its JSON and one-line text forms."""

import datetime
from typing import NamedTuple


class Reading(NamedTuple):
    timestamp: datetime.datetime
    co2_ppm: float
    temp_c: float
    rh_percent: float

    def to_json(self):
        return {
            "timestamp": self.timestamp.isoformat(timespec="seconds"),
            "co2_ppm": self.co2_ppm,
            "temp_c": self.temp_c,
            "rh_percent": self.rh_percent,
        }

    @classmethod
    def from_json(cls, data):
        return cls(
            datetime.datetime.fromisoformat(data["timestamp"]),
            float(data["co2_ppm"]),
            float(data["temp_c"]),
            float(data["rh_percent"]),
        )


def format_reading(r):
    return (
        f"{r.timestamp:%Y-%m-%d %H:%M:%S}  CO₂ {r.co2_ppm:5.0f} ppm  "
        f"Temp {r.temp_c:5.1f} °C  RH {r.rh_percent:5.1f} %"
    )
