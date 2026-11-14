"""tests/_midnight.py - a suite that reads today's date while it runs waits out a local midnight that would fall inside the run.

A suite that writes "tomorrow" or "today" into a fixture from the clock at its start, and then asks the code under test, which reads the clock again, whether a day is in the
future or has passed, answers differently when a midnight of the instance's zone falls between the two reads: the window is the few seconds between them, once a day. `wait_out`
sleeps past a midnight that is close, so the suite starts on the far side of it. It is the cheap form of the guard tests/audit_hourly_scenario.py keeps (a clock moved off the
boundary) for a suite that reads the real clock and cannot move it.

    import _midnight; _midnight.wait_out("Asia/Dubai")        # before the suite's first read of the clock
"""
import datetime, time, zoneinfo


def wait_out(zone: str, within: float = 180.0) -> float:
    """Sleep until just past the next midnight of `zone` when it is less than `within` seconds away (the margin is a suite's whole run, with room). → the seconds slept, 0.0 for none."""
    now = time.time()
    local = datetime.datetime.fromtimestamp(now, zoneinfo.ZoneInfo(zone))
    midnight = (local + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    left = midnight.timestamp() - now
    if left >= within:
        return 0.0
    time.sleep(left + 1.0)
    return left + 1.0
