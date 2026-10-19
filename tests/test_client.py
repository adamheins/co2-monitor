import datetime

from co2_monitor.client import Syncer
from co2_monitor.dashboard import Dashboard

T0 = datetime.datetime.now().replace(microsecond=0)


def row(seq, co2):
    ts = T0 - datetime.timedelta(minutes=10) + datetime.timedelta(seconds=30 * seq)
    return {"seq": seq, "timestamp": ts.isoformat(), "co2_ppm": co2, "temp_c": 22.0, "rh_percent": 50.0}


class FakeServer:
    """Mimics ServerClient; tracks which `after` values were requested."""

    def __init__(self, run_id, rows):
        self.run_id, self.rows, self.requests = run_id, rows, []

    def status(self):
        return {
            "server_time": datetime.datetime.now().isoformat(),
            "started_at": T0.isoformat(),
            "device": "/dev/ttyACM0",
            "serial_connected": True,
            "serial_error": None,
        }

    def readings(self, after=0):
        self.requests.append(after)
        return {"run_id": self.run_id, "readings": [r for r in self.rows if r["seq"] > after]}


def test_initial_load_then_incremental():
    server = FakeServer("a", [row(1, 700), row(2, 710)])
    dash = Dashboard("fake")
    syncer = Syncer(server, dash)

    new, reset = syncer.poll()
    assert reset and [r.co2_ppm for r in new] == [700, 710]

    server.rows.append(row(3, 720))
    new, reset = syncer.poll()
    assert not reset and [r.co2_ppm for r in new] == [720]
    assert server.requests == [0, 2]
    assert [r.co2_ppm for r in dash.history] == [700, 710, 720]


def test_no_new_readings():
    server = FakeServer("a", [row(1, 700)])
    syncer = Syncer(server, Dashboard("fake"))
    syncer.poll()
    new, reset = syncer.poll()
    assert new == [] and not reset


def test_server_restart_refetches_everything():
    server = FakeServer("a", [row(1, 700), row(2, 710), row(3, 720)])
    dash = Dashboard("fake")
    syncer = Syncer(server, dash)
    syncer.poll()

    # Server restarts: new run id, sequence numbers start again from 1.
    server.run_id, server.rows = "b", [row(1, 800), row(2, 810)]
    new, reset = syncer.poll()
    assert reset and [r.co2_ppm for r in new] == [800, 810]
    assert server.requests[-2:] == [3, 0]
    assert [r.co2_ppm for r in dash.history] == [800, 810]
    assert syncer.last_seq == 2
