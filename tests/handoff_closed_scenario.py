"""Scenario test for the hand-off line of a CLOSED item (waits/handoff.py: closed_words, last_record) — pure: dict fixtures, no store, no config, no network.

A closed item keeps the three times of its last hand-off, shown by get as one line:
  handoff: handed to X at 09:02, taken 09:05, live 10:40

  1  an open item's line is unchanged: handed to X, taken HH:MM | not yet taken (since HH:MM)
  2  a taken hand-off that the close leaves in place shows handed, taken and live
  3  an untaken hand-off the close ends (it moves into the history) shows "not taken", with the same handed and live times
  4  a second hand-off keeps the latest: the closed line names the newest record; the earlier one stays in the history
  5  a reopened item shows the open line again; its next close shows the new live time
  6  an old closed item with no hand-off on record shows nothing, and an item with no close clock shows no live part; neither errors
  7  the times are in the instance's timezone (here UTC, passed in)

    python3 tests/handoff_closed_scenario.py        → exit 0 / 1"""
import datetime as dt, logging, os, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.waits import handoff as H

UTC = dt.timezone.utc
DAY = dt.datetime(2026, 11, 27, tzinfo=UTC)


def at(hh, mm):
    return (DAY + dt.timedelta(hours=hh, minutes=mm)).timestamp()


NOW = at(23, 59)      # the same day as every time above, so the times read HH:MM
FAILS, RAN = [], []


def check(name, cond, got=None):
    RAN.append(name)
    if not cond:
        FAILS.append(name)
        print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))


def line(item):
    return H.words(item, NOW, UTC)


def closed(status="completed", state_updated=None, **meta):
    it = {"id": "fixture-1", "status": status, "metadata": dict(meta)}
    if state_updated is not None:
        it["state_updated"] = state_updated
    return it


def rec(to, handed, taken=None, **extra):
    r = H.new_record(to, "", "fixture-sender", handed, **extra)
    if taken is not None:
        r["taken_at"] = taken
    return r


# 1  open: unchanged
op = {"id": "fixture-1", "status": "open", "metadata": {"handoff": rec("alice-builder", at(9, 2), at(9, 5))}}
check("1 open item: the line is unchanged (taken HH:MM)", line(op) == ["handoff: handed to alice-builder, taken 09:05"], line(op))
op2 = {"id": "fixture-1", "status": "open", "metadata": {"handoff": rec("alice-builder", at(9, 2))}}
check("1 open item not yet taken: the line is unchanged", line(op2) == ["handoff: handed to alice-builder, not yet taken (since 09:02)"], line(op2))

# 2  taken, kept by the close
c2 = closed(state_updated=at(10, 40), handoff=rec("alice-builder", at(9, 2), at(9, 5)))
check("2 taken then closed: handed, taken and live", line(c2) == ["handoff: handed to alice-builder at 09:02, taken 09:05, live 10:40"], line(c2))

# 3  untaken, ended by the close: follow moves it to the history
c3 = {"id": "fixture-1", "status": "open", "state_updated": at(9, 30), "metadata": {"handoff": rec("alice-builder", at(9, 2))}}
c3["status"] = "completed"; c3["state_updated"] = at(10, 40)
out = H.follow(c3, "alice-builder", "", at(10, 40))
check("3 untaken then closed: the close ends the record into the history", out == "ended" and "handoff" not in c3["metadata"], (out, c3["metadata"].keys()))
check("3 untaken then closed: the line says not taken, with handed and live", line(c3) == ["handoff: handed to alice-builder at 09:02, not taken, live 10:40"], line(c3))

# 4  second hand-off: the first one moves to the history; the closed line names the latest
item4 = {"id": "fixture-1", "status": "open", "metadata": {"handoff": rec("alice-builder", at(9, 2), at(9, 5))}}
meta4 = item4["metadata"]
H.push_history(meta4, meta4[H.KEY], at(11, 0), "handed on")
meta4[H.KEY] = rec("bob-front", at(11, 0))
item4["status"] = "completed"; item4["state_updated"] = at(12, 0)
H.follow(item4, "bob-front", "", at(12, 0))
check("4 second hand-off, then closed: the line names the latest hand-off, untaken", line(item4) == ["handoff: handed to bob-front at 11:00, not taken, live 12:00"], line(item4))
check("4 second hand-off: the first record stays in the history (the latest one, ended by the close, follows it there)", [h.get("to") for h in meta4.get(H.HISTORY, [])] == ["alice-builder", "bob-front"], meta4.get(H.HISTORY))

# 5  reopen, then close again
c5 = closed(state_updated=at(10, 40), handoff=rec("alice-builder", at(9, 2), at(9, 5)))
c5["status"] = "open"
check("5 reopened: the open line, not the closed one", line(c5) == ["handoff: handed to alice-builder, taken 09:05"], line(c5))
c5["status"] = "completed"; c5["state_updated"] = at(13, 0)
check("5 closed again: the live time is the newer close", line(c5) == ["handoff: handed to alice-builder at 09:02, taken 09:05, live 13:00"], line(c5))

# 6  no data: nothing, no error
check("6 old closed item with no hand-off: no line", line(closed(state_updated=at(10, 40))) == [], line(closed(state_updated=at(10, 40))))
check("6 closed item with empty metadata and no clock: no line", line(closed()) == [], line(closed()))
c6 = closed(handoff=rec("alice-builder", at(9, 2), at(9, 5)))
check("6 closed item with no close clock: the handed and taken times, no live part", line(c6) == ["handoff: handed to alice-builder at 09:02, taken 09:05"], line(c6))
c6b = closed(state_updated=at(10, 40), handoff_history=[{"to": "bob-front"}])
check("6 a history entry with no time: no line and no error", line(c6b) == [], line(c6b))

# 7  the instance's timezone: the same instants read in another zone
DUBAI = dt.timezone(dt.timedelta(hours=4))
c7 = closed(state_updated=at(10, 40), handoff=rec("alice-builder", at(9, 2), at(9, 5)))
check("7 the times are shown in the instance's zone", H.words(c7, at(12, 0), DUBAI) ==["handoff: handed to alice-builder at 13:02, taken 13:05, live 14:40"], H.words(c7, NOW, DUBAI))

print(f"{len(RAN) - len(FAILS)}/{len(RAN)} checks passed")
sys.exit(1 if FAILS else 0)
