"""receiver_health — when a receiver's last check is too old to trust.

Each receiver of the receivers service reports a real check to status.json on a fixed beat: Slack and GitHub each minute, Google and Notion
each half hour (a receiver with nothing bound stamps its beat too, so an idle one stays fresh). A receiver whose thread has died stops
reporting, and its last report keeps saying healthy. The board therefore shows a receiver whose last check is more than STALE_FACTOR times its
beat old as stale, with the age, instead of healthy.
A receiver that knows it will not report for a while says so: status.json["hold"][name] is the time until which no check is expected (the first
pass after a start, which reads every anchor, and a wait after GitHub refuses calls, which waits ten minutes). The age is then counted from the later of the
last check and that time, so a long deliberate wait never reads as stale. The next check clears the hold.
Pure functions with no imports from the service itself: the board's page, its live receivers endpoint and the tests read the same rule here
(tests/receiver_reliability_scenario.py checks that the beats below agree with the constants the receivers run on)."""

EVERY = {"github": 60, "slack": 60, "google": 1800, "notion": 1800}   # s: how often each receiver reports a check
STALE_FACTOR = 2                                                      # a check older than this many beats is stale (exactly this many is not yet)


def stale_age(name: str, ok: bool, checked_ts: float, now_ts: float, hold_until: float = 0.0) -> int:
    """Seconds since the last check (or since the end of its announced hold, if later) when a healthy receiver's check is older than STALE_FACTOR
    beats, else 0. A receiver that is down already shows its error, a receiver with no known beat or no readable check time is never called stale,
    and a check stamped in the future is fresh."""
    every = EVERY.get(name)
    if not every or not ok or not checked_ts: return 0
    try: held = float(hold_until or 0.0)
    except (TypeError, ValueError): held = 0.0
    held = 0.0 if held != held else min(held, now_ts + 3600, checked_ts + 7200)   # a hold is a wait of minutes: a huge, infinite or garbled end time never hides a dead receiver for more than two hours past its last check
    age = now_ts - max(checked_ts, held)
    return int(age) if age > STALE_FACTOR * every else 0


def age_words(seconds: float) -> str:
    """The board's short age: 7m, 5h, 3d (the page script's dur() writes the same)."""
    m = int(max(seconds, 0) // 60)
    return f"{m}m" if m < 60 else f"{m // 60}h" if m < 2880 else f"{m // 1440}d"


def stale_note(name: str, seconds: float) -> str:
    """The tooltip of a stale receiver, the same text on the server-drawn card and in the live update (which takes it from the receivers endpoint)."""
    return f"no check for {age_words(seconds)} (it reports every {age_words(EVERY[name])}); the last one said healthy"
