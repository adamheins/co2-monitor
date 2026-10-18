"""Parse readings from the firmware's serial log output.

The USB firmware (firmware/co2-monitor-usb.yaml) prints a line like
    [I][main:...]: DATA,680,22.52,55.71
every 30 s, giving CO2 (ppm), temperature (°C) and relative humidity (%).
"""

import re

DATA_RE = re.compile(r"DATA,([\d.]+),([\d.]+),([\d.]+)")


def parse_line(line):
    """(co2_ppm, temp_c, rh_percent) from a firmware DATA line, or None.

    Lines that don't match (other log output, or 'nan' readings while the
    sensors warm up) give None.
    """
    m = DATA_RE.search(line)
    if m is None:
        return None
    co2, temp, rh = (float(x) for x in m.groups())
    return co2, temp, rh
