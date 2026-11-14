"""Scenario test for the read side of the `until` date (waiting.stored_until / until_of / kind_of, and every reader that takes a stored `until`) — fixture items, no live store, no network, no model call.

An open item that stores `until` is waiting; one that stores none is alive (or waits by the legacy fields, exactly as before). `wait_kind` is optional beside it: no kind = a wait on the date alone
(kind time); a kind keeps its behavior with `until` as its date (a relay's ask-by day, the backstop of an anchor, item or event wait). Nothing writes `until` yet: this suite plants it in fixtures and
holds that every reader takes it, and that an item without one reads as it always did.

  1  the accessor: stored until (with and without a kind), the legacy wake and ask_by per kind, garbage kinds, no date at all; date-only = the start of that day, THH:MM = that minute; past and future
  2  model.derive / view / stamp / words: waiting iff until; kind time when none; a kind keeps its own; the legacy readings are untouched (a wake on an alive item is still a backstop);
     check_fields judges a given `until`; the wait fields that must clear when a wait ends list `until`
  3  watchers: stored_kind, time_epoch, backstop_epoch, can_end, next_moment, due and watches for an until-only item and for the kinds anchor, item, relay and event with an `until` backstop;
     the backoff after a failed turn; end_wait / turn_alive clear `until` with the kind group; a relay's "not yet" puts the new date back where the old one stood
  4  states, stall, silence (the shared readings), audit (check_stale, dates_findings), dated_wait: each reads the stored `until` where it read a wake
  5  the board: home.end_of, itempage.wait_end_label, both renderers' wake_of, and get's `until:` line; the wait basis and the owner's words are read for the very `until` they were given for

    tests/run-suite until        -> exit 0 / 1"""
import copy, datetime as dt, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="untiltest-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK)

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml      # never the host's session store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1                 # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                           # an isolated HOME
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state", "transcripts/-home-x"): (T / d).mkdir(parents=True)
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-owner", "home-stew", "marsh-builder", "quill-agent", "home-other"), 1)}
(T / "store/anchors.json").write_text("{}"); (T / "store/next-id").write_text("900")
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/quill": {"title": "Quill", "name": "Quill", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active",
                                                                               "board": [], "board_open": 0, "agents": {"quill-agent": "the front", "marsh-builder": "the back"}, "back_agents": {"marsh-builder": "the back"}}}}))
(T / "brain/projects/quill.md").write_text("---\ntitle: Quill\ndisplay-name: home-stew\nagents:\n  quill-agent: the front\n  background:\n    marsh-builder: the back\n---\n\n# Quill\n")
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()})); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))

from stackshot.core import config as _cfg
from stackshot.waits import waiting as W, watchers as WK, stall as ST, dated_wait as DW, event_waits as EW
from stackshot.model import model as M, states as S
from stackshot.audit import audit_checks as AC, silence as SI
from stackshot.web import home as HOME, itempage as IP, render as RR, server
from stackshot.service import update as _update_svc
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import wakes as wakes_svc, watching as watching_svc
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.service import gates, telling
from stackshot.web.ui import render as UR

H = 3600.0; DAY = 86400.0
ZONE_HOURS = 4                                                                              # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
ZONE = dt.timezone(dt.timedelta(hours=ZONE_HOURS))
now = time.time()
if min((now + ZONE_HOURS * 3600) % 86400, 86400 - (now + ZONE_HOURS * 3600) % 86400) < 600: now -= 900     # not within ten minutes of a local midnight: a date word stays on one day
day = lambda n: (dt.datetime.fromtimestamp(now, ZONE) + dt.timedelta(days=n)).strftime("%Y-%m-%d")
at = lambda n, hm: f"{day(n)}T{hm}"
ep = lambda s: W.wake_epoch(s)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

OWNER = "Oliver"; BACK = "marsh-builder"
def item(i="1", status="open", **meta):
    return {"id": i, "gid": f"a{i}", "subject": f"[home] item {i}", "description": "- A thing", "status": status, "updated": now - H, "state_updated": now - H, "confirmed": now - H,
            "metadata": {"project": "projects/quill", "next": f"{BACK}: do it", **meta}}
def derive(it, t=None, **kw): return M.derive(it, now if t is None else t, **kw)
DOC = {"status": "open"}

# ---- 1. the accessor
check("stored_until: read from the item, trimmed", W.stored_until({"until": f" {day(3)} "}) == day(3) and W.stored_until({}) == "" and W.stored_until({"until": None}) == "")
check("kind_of: a stored kind stands, with or without an until", W.kind_of({"wait_kind": "relay", "until": day(2)}) == "relay" and W.kind_of({"wait_kind": "Anchor"}) == "anchor" and W.kind_of({"wait_kind": "event", "until": day(2)}) == "event")
check("kind_of: an until and no kind is a wait on the date alone: time", W.kind_of({"until": day(2)}) == "time" and W.kind_of({"until": day(2), "wait_kind": "nonsense"}) == "time")
check("kind_of: no until and no kind is none (the legacy readers decide)", W.kind_of({}) == "" and W.kind_of({"wake": day(2)}) == "" and W.kind_of({"wait_kind": "nonsense"}) == "")
check("until_of: the stored until first, whatever the kind and the legacy fields say",
      all(W.until_of({"until": day(5), "wake": day(1), "ask_by": day(2), **k}) == day(5) for k in ({}, {"wait_kind": "time"}, {"wait_kind": "relay"}, {"wait_kind": "anchor"}, {"wait_kind": "item"}, {"wait_kind": "event"})))
check("until_of: legacy time reads the wake, legacy relay the ask_by", W.until_of({"wait_kind": "time", "wake": day(2), "ask_by": day(1)}) == day(2) and W.until_of({"wait_kind": "relay", "wake": day(1), "ask_by": day(3)}) == day(3))
check("until_of: legacy anchor, item and event read the earlier of ask_by and wake",
      all(W.until_of({"wait_kind": k, "wake": day(4), "ask_by": day(2)}) == day(2) and W.until_of({"wait_kind": k, "wake": day(1), "ask_by": day(2)}) == day(1) for k in ("anchor", "item", "event")))
check("until_of: a legacy backstop kind with one date reads it, with an unreadable one reads the other, with none reads none",
      W.until_of({"wait_kind": "item", "wake": day(4)}) == day(4) and W.until_of({"wait_kind": "anchor", "ask_by": day(2), "wake": "someday"}) == day(2) and W.until_of({"wait_kind": "event"}) == "" and W.until_of({"wait_kind": "event", "wake": "someday"}) == "")
check("until_of: no kind reads the wake, else the ask_by, else none", W.until_of({"wake": day(2), "ask_by": day(3)}) == day(2) and W.until_of({"ask_by": day(3)}) == day(3) and W.until_of({}) == "" and W.until_of({"wait_kind": "time"}) == "")
check("until_of: THH:MM is kept as written", W.until_of({"until": at(2, "14:30")}) == at(2, "14:30"))
check("wake_epoch reads an until: date-only is the start of that day, THH:MM that minute",
      ep(day(2)) == dt.datetime.fromisoformat(day(2) + "T00:00").replace(tzinfo=ZONE).timestamp() and ep(at(2, "14:30")) == ep(day(2)) + 14.5 * H and ep("someday") is None and ep("") is None)
check("past and future: a date-only until of today is already past, one of tomorrow is ahead", ep(day(0)) <= now < ep(day(1)) and ep(at(0, "00:01")) > ep(day(0)))
check("wake_value: the stored until, else the wake as stored", W.wake_value({"until": day(2), "wake": day(1)}) == day(2) and W.wake_value({"wake": day(1)}) == day(1) and not W.wake_value({}))

# ---- 2. model: derive, view, stamp, words, check_fields
for name, meta in (("a date-only until", {"until": day(3)}), ("a THH:MM until", {"until": at(3, "09:30")}), ("an until beside a state doing", {"until": day(3), "state": "doing", "needs": [BACK]}),
                   ("an until beside a hold", {"until": day(3), "hold": True}), ("an until beside a stored mover", {"until": day(3), "mover": BACK})):
    mod = derive(item(**meta))
    check(f"derive: {name} is a wait on a time, by its until", mod.state == M.WAITING and mod.wait is not None and mod.wait.kind == "time" and not mod.wait.kind_explicit and mod.wait.until == meta["until"]
          and mod.wait.by_until and not mod.wait.backstop and not mod.wait.due, mod)
check("derive: an until that has passed is a wait that is due", derive(item(until=day(-1))).wait.due and not derive(item(until=day(2))).wait.due and derive(item(until=at(0, "00:00"))).wait.due)
check("derive: an until in the near future by the minute is not due yet", not derive(item(until=at(1, "00:00")), t=ep(at(1, "00:00")) - 60).wait.due and derive(item(until=at(1, "00:00")), t=ep(at(1, "00:00")) + 1).wait.due)
alive = derive(item(wake=day(2), needs=[BACK]))
check("derive: no until, no kind: still alive, and a wake on it is still the mover's backstop", alive.state == M.ALIVE and alive.checkback == day(2), alive)
check("derive: no date and no kind: alive", derive(item(needs=[BACK])).state == M.ALIVE)
check("derive: a legacy hold and wake is the wait it was (no until: by_until false, the wake as its end)",
      (lambda w: w.kind == "time" and w.until == day(4) and not w.by_until)(derive(item(state="parked", hold=True, wake=day(4), needs=[BACK], wait_basis={"text": "x", "wake": day(4)})).wait))
rel = derive(item(wait_kind="relay", until=day(2), ask_by=day(9), wait_event="the vendor"))
check("derive: a relay's until is its ask-by day, and it wins over a stored ask_by", rel.wait.kind == "relay" and rel.wait.until == day(2) and rel.wait.by_until and rel.wait.kind_explicit and not rel.wait.due)
check("derive: a relay with an until that passed is due", derive(item(wait_kind="relay", until=day(-1), wait_event="the vendor")).wait.due)
for k, extra in (("anchor", {"wait_anchor": "https://example.test/x"}), ("item", {"after": ["a9"]}), ("event", {"wait_event": "pr_merged quill/widgets#5"})):
    w = derive(item(wait_kind=k, until=day(3), wake=day(1), **extra)).wait
    check(f"derive: a {k} wait with an until takes it as its backstop (over a wake)", w.kind == k and w.backstop == day(3) and not w.until and w.by_until and w.kind_explicit, w)
check("derive: an item wait is due when every item it waits after is closed, as before", derive(item(wait_kind="item", until=day(3), after=["a9"]), after_open=lambda i: []).wait.due and not derive(item(wait_kind="item", until=day(3), after=["a9"]), after_open=lambda i: ["a9"]).wait.due)
check("derive: no stored kind and no until, a stored state outside is still a relay wait (the legacy reading)", derive(item(state="outside", needs=["external"], ask_by=day(2), party="the vendor")).wait.kind == "relay")
check("derive: no kind but an until beats a stored state outside: the wait is on the date alone", (lambda w: w.kind == "time" and w.by_until)(derive(item(state="outside", needs=["external"], until=day(2))).wait))
check("derive: an until does not raise the alive-state conflict a stored wait_kind does", not derive(item(until=day(3), state="doing", needs=[BACK])).conflicts and derive(item(wait_kind="time", wake=day(3), state="doing", needs=[BACK])).conflicts)
check("derive: owner words and the wait basis stand for the very until", derive(item(until=day(3), cap_ok={"wake": day(3), "by": "x"})).wait.owner_words and not derive(item(until=day(3), cap_ok={"wake": day(4), "by": "x"})).wait.owner_words
      and derive(item(until=day(3), wait_basis={"text": f"vendor ships {day(3)}", "wake": day(3), "by": "x", "at": 1})).wait.basis == f"vendor ships {day(3)}")

it = item(until=day(3))
shown = M.view(it, derive(it), now, check=False)
check("view (the writer's reading): waiting, and the stamp stores the pair waiting / time", shown.state == M.WAITING and M.stamp_values(it, shown) == ("waiting", "time"), shown)
it2 = item(until=day(3), phase="waiting", waits_on="time")
check("view (the stored pair): an until item stamped waiting / time reads as waiting on a time", (lambda s: s.state == M.WAITING and s.wait.kind == "time" and s.wait.until == day(3))(M.view(it2, derive(it2), now)))
it3 = item(until=day(3), phase="waiting", waits_on="relay", wait_event="the vendor")
check("view: the stored kind of the pair decides the kind, the date stays the until", (lambda s: s.wait.kind == "relay" and s.wait.until == day(3) and s.wait.by_until)(M.view(it3, derive(it3), now)))
it4 = item(needs=[BACK], wake=day(2), phase="waiting", waits_on="time")
check("view: a stored waiting pair on an alive reading (the wake) is the legacy wait, by the wake, unchanged", (lambda s: s.state == M.WAITING and s.wait.until == day(2) and not s.wait.by_until)(M.view(it4, derive(it4), now)))
check("words: a stored until reads 'until', a legacy wake reads 'wake'", "a time (until " + day(3) + ")" in M.words(derive(item(until=day(3)))) and "a time (wake " + day(4) + ")" in M.words(derive(item(wait_kind="time", wake=day(4)))))
check("words: a relay and the backstop kinds read 'until' beside a stored until, the legacy words beside the old fields",
      f"until {day(2)}" in M.words(rel) and "ask by" not in M.words(rel) and f"ask by {day(2)}" in M.words(derive(item(wait_kind="relay", ask_by=day(2), wait_event="the vendor")))
      and f"; until {day(3)})" in M.words(derive(item(wait_kind="anchor", until=day(3), wait_anchor="https://example.test/x"))) and f"backstop wake {day(3)}" in M.words(derive(item(wait_kind="anchor", wake=day(3), wait_anchor="https://example.test/x")))
      and f"(until {day(3)})" in M.words(derive(item(wait_kind="item", until=day(3), after=["a9"]))) and f"; until {day(3)})" in M.words(derive(item(wait_kind="event", until=day(3), wait_event="recycle"))))
check("check_fields: a given until must be a real date or minute; none given is fine",
      M.check_fields({"until": day(2)}) == [] and M.check_fields({"until": at(2, "09:30")}) == [] and M.check_fields({}) == [] and len(M.check_fields({"until": "2030-02-31"})) == 1
      and len(M.check_fields({"until": "tomorrow"})) == 1 and len(M.check_fields({"until": day(2) + "T25:00"})) == 1 and M.check_fields({"ask_by": day(2)}) == [])
check("the wait fields that clear when a wait ends list until: WAIT_GROUP, DROP_ON_CLOSE, LIVE_DROP, MODEL_FIELDS",
      "until" in M.WAIT_GROUP and "until" in M.DROP_ON_CLOSE and "until" in WK.LIVE_DROP and "until" in M.MODEL_FIELDS and "until" in WK.WAS_FIELDS)

# ---- 3. watchers
UO = item(until=day(-1))["metadata"]; UF = item(until=day(2))["metadata"]; UT = item(until=at(2, "09:30"))["metadata"]
check("stored_kind: an until-only item reads time; a stored kind stands; none is none", WK.stored_kind(UF) == "time" and WK.stored_kind({"wait_kind": "relay", "until": day(2)}) == "relay" and WK.stored_kind({}) == "" and WK.stored_kind({"wake": day(2)}) == "")
check("time_epoch / backstop_epoch / next_moment: the until, by the minute when it has one", WK.time_epoch(UT) == ep(at(2, "09:30")) and WK.backstop_epoch(UT) == ep(at(2, "09:30")) and WK.next_moment(UT) == ep(at(2, "09:30")) and WK.time_epoch(UF) == ep(day(2)))
check("time_epoch: the until wins over a wake, and a verifying item's end date is only the fallback", WK.time_epoch({"until": day(3), "wake": day(1)}) == ep(day(3)) and WK.time_epoch({"state": "verifying", "end": day(2)}) == W.due_epoch(day(2))
      and WK.time_epoch({"state": "verifying", "end": day(2), "until": day(5)}) == ep(day(5)))
check("can_end / watches: an until-only wait can be ended and is watched; with watchers off it is not", WK.can_end(UF) and WK.watches({"status": "open", "metadata": UF}) and not WK.watches({"status": "completed", "metadata": UF}) and not WK.watches({"status": "open", "metadata": {"needs": [BACK]}}))
check("due: an until-only wait is due as time once its minute has passed, not before", WK.due({"metadata": UO}, now) == "time" and WK.due({"metadata": UF}, now) == "" and WK.due({"metadata": UT}, ep(at(2, "09:30")) - 1) == "" and WK.due({"metadata": UT}, ep(at(2, "09:30"))) == "time")
check("due: a turn that failed is left alone for the backoff, and next_moment says when it is looked at again", WK.due({"metadata": {**UO, "watch": {"failed_at": now - 60}}}, now) == ""
      and WK.due({"metadata": {**UO, "watch": {"failed_at": now - WK.BACKOFF - 1}}}, now) == "time" and WK.next_moment({**UO, "watch": {"failed_at": now}}) == now + WK.BACKOFF)
check("a legacy time wait is read as it was: the wake, no until", WK.time_epoch({"wait_kind": "time", "wake": day(2)}) == ep(day(2)) and WK.due({"metadata": {"wait_kind": "time", "wake": day(-1)}}, now) == "time" and WK.can_end({"wait_kind": "time"}) is False)
rl, rl_old = {"wait_kind": "relay", "until": day(-1), "wait_event": "the vendor"}, {"wait_kind": "relay", "ask_by": day(-1), "wait_event": "the vendor"}
check("relay: an until is the ask-by day (can_end, due, next_moment), as an ask_by was", WK.can_end(rl) and WK.due({"metadata": rl}, now) == "relay" and WK.due({"metadata": {**rl, "until": day(2)}}, now) == "" and WK.next_moment({**rl, "until": day(2)}) == ep(day(2))
      and WK.due({"metadata": rl_old}, now) == "relay" and WK.can_end(rl_old) and not WK.can_end({"wait_kind": "relay"}))
check("relay: the until beats a later ask_by", WK.due({"metadata": {**rl, "ask_by": day(5)}}, now) == "relay" and WK.due({"metadata": {**rl, "until": day(3), "ask_by": day(-2)}}, now) == "")
an = {"wait_kind": "anchor", "wait_anchor": "https://example.test/x", "until": day(-1)}
check("anchor: the until is the backstop (can_end by the anchor, due backstop past it, next_moment its minute)", WK.can_end(an) and WK.due({"metadata": an}, now) == "backstop" and WK.due({"metadata": {**an, "until": day(2)}}, now) == "" and WK.next_moment({**an, "until": day(2)}) == ep(day(2))
      and WK.can_end({k: v for k, v in an.items() if k != "until"}) and WK.backstop_epoch({**an, "wake": day(-5), "ask_by": day(-4)}) == ep(day(-1)))
it_w = {"wait_kind": "item", "after": ["a9"], "until": day(-1)}
check("item: the last after item closing ends it (item); with one open, the until passed is the backstop; an until alone is enough to end it",
      WK.due({"metadata": it_w}, now, []) == "item" and WK.due({"metadata": it_w}, now, ["a9"]) == "backstop" and WK.due({"metadata": {**it_w, "until": day(2)}}, now, ["a9"]) == ""
      and WK.can_end({"wait_kind": "item", "until": day(2)}) and not WK.can_end({"wait_kind": "item"}) and WK.next_moment({**it_w, "until": day(2)}) == ep(day(2)))
evw = {"wait_kind": "event", "wait_event": "pr_merged quill/widgets#5"}
check("event: no end without a backstop; with an until it can end, is due as backstop past it, and next_moment is its minute", not WK.can_end(evw) and WK.can_end({**evw, "until": day(2)}) and WK.due({"metadata": {**evw, "until": day(-1)}}, now) == "backstop"
      and WK.due({"metadata": {**evw, "until": day(2)}}, now) == "" and WK.next_moment({**evw, "until": at(2, "09:30")}) == ep(at(2, "09:30")))
check("event: the until counts as the backstop an event wait needs, so the gap 'no backstop day' no longer reads", WK.can_end({**evw, "until": day(2)}) and EW.problem(evw["wait_event"]) == "")

full = {"until": day(2), "wait_kind": "anchor", "wait_anchor": "https://example.test/x", "wait_event": "a notice", "ask_by": day(3), "post_wake_mover": BACK, "wake": day(1), "hold": True, "hold_set": {"at": 1, "by": "x"},
        "wait_basis": {"text": "t", "wake": day(2)}, "cap_ok": {"wake": day(2), "by": "x", "quote": "ok"}, "after": ["a9"], "needs": [BACK], "mover": BACK, "project": "projects/quill"}
mm = copy.deepcopy(full); WK.end_wait(mm)
check("end_wait: until goes with the kind group, the hold, the wake, the basis and the owner's words; the rest stays",
      not any(k in mm for k in ("until", "wait_kind", "wait_anchor", "wait_event", "ask_by", "post_wake_mover", "wake", "hold", "hold_set", "wait_basis", "cap_ok", "after")) and mm["needs"] == [BACK] and mm["project"] == "projects/quill", mm)
mm = copy.deepcopy(full); WK.turn_alive(mm, BACK, "its until came", now)
check("turn_alive: the wait ends with its until, the post-wake mover moves the item and the arrival is recorded", "until" not in mm and "wait_kind" not in mm and mm["mover"] == BACK and mm["woke"]["what"] == "its until came")
mm = copy.deepcopy(full); WK.turn_to_owner(mm, BACK, "Decide: x", [], "its until came", now)
check("turn_to_owner: the wait's until goes too", "until" not in mm and mm["then"] == BACK and mm["needs"] == ["decision"])
mm = {"wait_kind": "relay", "until": day(-1), "wait_event": "the vendor", "needs": [BACK]}
WK.remember(mm, "relay", now); WK.turn_to_owner(mm, BACK, "Decide: x", [], "due", now); WK.restore_wait(mm, day(6), True, now)
check("restore_wait (an until relay): 'not yet' puts the new date back as the until, not as an ask_by", mm.get("until") == day(6) and "ask_by" not in mm and mm["wait_kind"] == "relay" and WK.due({"metadata": mm}, now) == "", mm)
mm = {"wait_kind": "relay", "ask_by": day(-1), "wait_event": "the vendor", "needs": [BACK]}
WK.remember(mm, "relay", now); WK.turn_to_owner(mm, BACK, "Decide: x", [], "due", now); WK.restore_wait(mm, day(6), True, now)
check("restore_wait (a legacy relay): the new date goes to ask_by as it always did", mm.get("ask_by") == day(6) and "until" not in mm, mm)
check("what_until: the arrival words", WK.what_until(day(2)) == f"its until {day(2)} came" and WK.what_time(day(2)) == f"its wake {day(2)} came")
check("world_line: a relay wait's ask-by day is its until", WK.world_line("a1", "s", {"wait_kind": "relay", "until": day(2), "wait_event": "the vendor"}).endswith(f"ask by {day(2)}")
      and WK.world_line("a1", "s", {"wait_kind": "relay", "ask_by": day(3), "wait_event": "the vendor"}).endswith(f"ask by {day(3)}"))

# ---- 4. states, stall, silence, audit, dated_wait
parked = item(hold=True, until=day(4), cap_ok={"wake": day(4), "by": "x", "quote": "park it"}, needs=[BACK])
check("states.derive: a hold with an until and the owner's words for that until is parked, as a wake is", S.derive(parked) == "parked" and S.derive(item(hold=True, until=day(4), needs=[BACK])) == "parked"
      and S.derive(item(until=day(4), needs=[BACK])) == "doing")
base = lambda **kw: item(state="doing", needs=[BACK], **kw)
WAITING_TIME = "the board shows it waiting (time)"
check("stall.not_due: an until-only wait is a wait the board shows, ahead or passed, so the stall pass leaves it alone", ST.not_due(base(until=day(2)), now) == WAITING_TIME and ST.not_due(base(until=day(-1)), now) == WAITING_TIME)
_cfg.CFG.setdefault("model", {})["watchers"] = False
check("stall.not_due (watchers off): the board's reading is the same, a bare wake ahead is only a reminder and holds nothing off; due_at is the until, or the wake once it has passed",
      ST.not_due(base(until=day(2)), now) == WAITING_TIME and ST.not_due(base(until=day(-1)), now) == WAITING_TIME and ST.not_due(base(wake=day(2)), now) == ""
      and ST.due_at(base(until=day(-1))) == ep(day(-1)) and ST.due_at(base(wake=day(-1))) == ep(day(-1)) and ST.due_at(base(wake=day(2)), now) == 0.0)
_cfg.CFG["model"]["watchers"] = True
check("stall.due_at: no date is 0", ST.due_at(base()) == 0.0)
# silence.reading: an item that waits is not on an agent, whatever its last write; the same item with no date is
sil = base(until=day(2)); sil["updated"] = sil["state_updated"] = now - 30 * H
quiet = base(); quiet["updated"] = quiet["state_updated"] = now - 30 * H
check("silence.reading: an until item is not on an agent; the same item with no date is", SI.reading(sil, BACK, [], now) == "" and SI.reading(quiet, BACK, [], now) == "agent",
      (SI.reading(sil, BACK, [], now), SI.reading(quiet, BACK, [], now)))
# audit: past its until with no write since
stale_until = base(until=at(0, "00:00")); stale_wake = base(wake=at(0, "00:00"))
last = now - 40 * H
check("check_stale: past its until with no write since is a finding that says until; past its wake says wake, as it did", "past its until (" in AC.check_stale(stale_until, stale_until["metadata"], BACK, lambda i: [], now, last)
      and "past its wake (" in AC.check_stale(stale_wake, stale_wake["metadata"], BACK, lambda i: [], now, last))
check("check_stale: an until still ahead, or a write since it passed, is no finding", AC.check_stale(base(until=day(2)), base(until=day(2))["metadata"], BACK, lambda i: [], now, last) == ""
      and AC.check_stale(stale_until, stale_until["metadata"], BACK, lambda i: [], now, now - 60) == "")
fnd, _passes = AC.dates_findings({"a1": {**stale_until, "written_at": last, "written_by": "quill-agent"}, "a2": {**stale_wake, "written_at": last, "written_by": "quill-agent"}, "a3": base(until=day(3))}, {}, now, None)
check("dates_findings: both the until and the wake item past their date are found, the one ahead is not", len(fnd) == 2 and all("past its" in f["detail"] for f in fnd) and sorted(f["detail"].split()[2] for f in fnd) == ["until", "wake"], fnd)
held_u = base(hold=True, until=day(3)); dw = DW.held_wait(held_u, now)
check("dated_wait.held_wait: a hold with an until ahead is a dated wait on it (at = the until as stored)", dw is not None and dw.until == ep(day(3)) and dw.at == day(3) and DW.held_wait(base(hold=True, until=day(-1)), now) is None)
check("dated_wait.basis_wait: a wait_basis for the very until makes the wait", (lambda d: d is not None and d.until == ep(day(3)))(DW.basis_wait(base(until=day(3), wait_basis={"text": f"vendor ships {day(3)}", "wake": day(3), "by": "x", "at": 1}), now, None))
      and DW.basis_wait(base(until=day(3), wait_basis={"text": f"vendor ships {day(3)}", "wake": day(4), "by": "x", "at": 1}), now, None) is None)

# ---- 5. the board
check("home.end_of: the stored until is the end of the wait whatever its kind", HOME.end_of(derive(item(until=at(2, "09:30")))) == at(2, "09:30") and HOME.end_of(rel) == day(2)
      and HOME.end_of(derive(item(wait_kind="anchor", until=day(3), wait_anchor="https://example.test/x"))) == day(3) and HOME.end_of(derive(item(wait_kind="item", until=day(3), after=["a9"]))) == day(3))
check("home.end_of: the legacy fields end a wait as before", HOME.end_of(derive(item(state="parked", hold=True, wake=day(3), needs=[BACK]))) == day(3) and HOME.end_of(derive(item(wait_kind="relay", ask_by=day(2), wait_event="the vendor"))) == day(2)
      and HOME.end_of(derive(item(wait_kind="anchor", wake=day(3), wait_anchor="https://example.test/x"))) == day(3))
check("itempage.wait_end_label: 'until' for a stored until of any kind; the legacy words for the old fields",
      IP.wait_end_label(rel.wait) == "until" and IP.wait_end_label(derive(item(until=day(2))).wait) == "until" and IP.wait_end_label(derive(item(wait_kind="anchor", until=day(3), wait_anchor="https://example.test/x")).wait) == "until"
      and IP.wait_end_label(derive(item(wait_kind="relay", ask_by=day(2), wait_event="the vendor")).wait) == "ask by" and IP.wait_end_label(derive(item(wait_kind="anchor", wake=day(3), wait_anchor="https://example.test/x")).wait) == "backstop"
      and IP.wait_end_label(derive(item(state="parked", hold=True, wake=day(3), needs=[BACK])).wait) == "until")
for label, mod_ in (("web.render", RR), ("web.ui.render", UR)):
    w1 = mod_.wake_of({"metadata": {"until": at(2, "14:30")}}); w2 = mod_.wake_of({"metadata": {"until": day(2)}}); w3 = mod_.wake_of({"metadata": {"wake": at(3, "08:00")}})
    check(f"{label}.wake_of: a stored until first (a minute, or a day), else the wake, else none", isinstance(w1, dt.datetime) and w1.strftime("%H:%M") == "14:30" and w2 == dt.date.fromisoformat(day(2))
          and isinstance(w3, dt.datetime) and w3.strftime("%H:%M") == "08:00" and mod_.wake_of({"metadata": {"until": day(2), "wake": day(5)}}) == w2 and mod_.wake_of({"metadata": {}}) is None
          and mod_.wake_of({"metadata": {"until": "someday", "wake": day(5)}}) is None and mod_.wake_of({"metadata": {"until": "  ", "wake": day(5)}}) == dt.date.fromisoformat(day(5)))
    check(f"{label}.wake_key: sorts an until by its minute, no date last", mod_.wake_key({"metadata": {"until": day(2)}}) < mod_.wake_key({"metadata": {"until": day(3)}}) < mod_.wake_key({"metadata": {}}))
fmt_it = {**item(until=at(2, "09:30"), needs=[BACK], state="doing"), "metadata": {"project": "projects/quill", "until": at(2, "09:30"), "next": f"{BACK}: do it", "state": "doing", "needs": [BACK]}}
out = server._fmt(fmt_it)
check("get: an `until:` line beside the model line when the item stores one", f"until: {at(2, '09:30')}" in out.splitlines() and "model: waiting on a time (until " in out, out)
out2 = server._fmt({**fmt_it, "metadata": {k: v for k, v in fmt_it["metadata"].items() if k != "until"}})
check("get: no `until:` line when the item stores none", not any(l.startswith("until:") for l in out2.splitlines()), out2)
bw = item(until=day(3), wait_basis={"text": f"vendor ships {day(3)}", "wake": day(3), "by": "quill-agent", "at": 1.0}, cap_ok={"wake": day(3), "by": "x", "quote": "park it"})
bw["status"] = "open"
out3 = server._fmt(bw)
check("get: the wait basis and the owner's words are read for the very until", f"for the wake {day(3)} only" in out3 and f"behind the wake {day(3)}" in out3, out3)
check("the basis and the words are read for the date they were given for only", W.basis_of({"until": day(4), "wait_basis": {"text": f"x {day(3)}", "wake": day(3)}}) == "" and W.basis_of({"wake": day(3), "wait_basis": {"text": f"x {day(3)}", "wake": day(3)}}) == f"x {day(3)}"
      and W.cap_words({"until": day(3), "cap_ok": {"wake": day(3)}}, "wake") and not W.cap_words({"until": day(4), "cap_ok": {"wake": day(3)}}, "wake") and W.words_of({"until": day(3), "cap_ok": {"wake": day(3), "quote": "q"}})["quote"] == "q"
      and W.cap_words({"wake": day(3), "cap_ok": {"wake": day(3)}}, "wake") and W.cap_words({"due": day(3), "cap_ok": {"due": day(3)}}, "due"))

# ---- 6. the server's own paths: the write refusal, clear_wait, a close, the wake sweep, the recycle release, the arrival text (a store of fixture items)
import logging
logging.disable(logging.INFO)
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
def sitem(i, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": status, "updated": now - 10 * DAY,
                                                      "state_updated": now - 10 * DAY, "confirmed": now - 10 * DAY, "metadata": {"owner": U["home-owner"], "project": "projects/quill", "next": f"{BACK}: do it", **meta}}))
    return f"a{i}"
def srd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def smt(i): return srd(i)["metadata"]

try:
    gates.gate_model_args({"wait_kind": "time"}, {"wait": True}); msg = ""
except Exception as e:  # noqa: BLE001
    msg = str(e)
check("refusal text: clear_wait names the five a caller can pass, never `until` (it is no write field yet)", msg.startswith("Refused: clear_wait drops wait_kind") and "post_wake_mover" in msg and "until" not in msg and "does not go with a new wait_kind" in msg, msg)
_, dropped = gates.gate_model_args({}, {"wait": True})
check("clear_wait still drops the whole wait group, `until` among it", "until" in dropped and "wait_kind" in dropped, dropped)

g1 = sitem(901, wait_kind="time", until=day(3), needs=[BACK], mover=BACK)
_update_svc._update(g1, sender=BACK, clear_wait=True)
check("clear_wait: the stored until goes with the wait kind", "until" not in smt(901) and "wait_kind" not in smt(901), smt(901))
g2 = sitem(902, until=day(3), needs=[BACK], mover=BACK)
_update_svc._update(g2, sender=BACK, clear_wait=True)
check("clear_wait: an until with no kind (a wait on the date alone) goes too, and the item reads alive", "until" not in smt(902) and M.derive(srd(902), now).state == M.ALIVE, smt(902))
g3 = sitem(903, until=day(3), needs=[BACK], mover=BACK)
_update_svc._update(g3, sender=BACK, status="completed", outcome="done", reason="ok", description="- Done")
check("a close removes the stored until from the item", srd(903)["status"] == "completed" and "until" not in smt(903), smt(903))
g4 = sitem(904, hold=True, until=day(3), needs=[BACK], mover=BACK)
_update_svc._update(g4, sender=BACK, clear_hold=True)
check("clear_hold: the hold and the until it stood on go together", "hold" not in smt(904) and "until" not in smt(904), smt(904))
g5 = sitem(905, until=day(3), needs=[BACK], mover=BACK)
_update_svc._update(g5, sender=BACK, clear_wake=True)
check("clear_wake: the date of the wait goes with it, and the item reads alive", "until" not in smt(905) and M.derive(srd(905), now).state == M.ALIVE, smt(905))

for kind, extra in (("anchor", {"wait_anchor": "https://example.test/x"}), ("event", {"wait_event": "pr_merged quill/widgets#5"})):
    mm = {"wait_kind": kind, "until": day(-1), "needs": [BACK], **extra}
    WK.remember(mm, "dropit", now); WK.turn_to_owner(mm, BACK, "Decide: x", [], "its until came", now); WK.restore_wait(mm, day(6), True, now)
    check(f"restore_wait ({kind} wait, until backstop): the new date goes back as the until, not as an ask_by", mm.get("until") == day(6) and "ask_by" not in mm and mm["wait_kind"] == kind and WK.due({"metadata": mm}, now) == "", mm)
    mm = {"wait_kind": kind, "ask_by": day(-1), "needs": [BACK], **extra}
    WK.remember(mm, "dropit", now); WK.turn_to_owner(mm, BACK, "Decide: x", [], "its backstop came", now); WK.restore_wait(mm, day(6), True, now)
    check(f"restore_wait ({kind} wait, legacy ask_by backstop): the new date goes to ask_by as before", mm.get("ask_by") == day(6) and "until" not in mm, mm)

hu, hw, hn = ({"status": "open", "metadata": {"hold": True, **kw}} for kw in ({"until": day(3)}, {"wake": day(3)}, {}))
check("held_only_for_recycle (both renderers): a hold that stands on an until is not released by a recycle, as one that stands on a wake is not",
      all(not mod_.held_only_for_recycle(hu, []) and not mod_.held_only_for_recycle(hw, []) and mod_.held_only_for_recycle(hn, []) and not mod_.held_only_for_recycle(hn, ["a9"]) for mod_ in (RR, UR)))
check("server._held_only_for_recycle: the same through the server, from the files", not server._held_only_for_recycle(hu) and server._held_only_for_recycle(hn))
vf = lambda **kw: {"status": "open", "metadata": {"state": "verifying", "end": day(2), "needs": [BACK], "project": "projects/quill", **kw}}
check("waits_on_end (both renderers): a verifying item waits on its end date only when it stores no until", all(mod_.waits_on_end(vf()) and not mod_.waits_on_end(vf(until=day(3))) for mod_ in (RR, UR)))

# the wake sweep: when the watchers do not own the wait, an until-only item is released, not left waiting for ever
_cfg.CFG.setdefault("model", {})["watchers"] = False
w1 = sitem(911, hold=True, until=day(-1), needs=[BACK], mover=BACK)
w2 = sitem(912, until=day(-1), needs=[BACK], mover=BACK)
w3 = sitem(913, hold=True, until=day(3), needs=[BACK], mover=BACK)
coll = {g: at_ for g, _p, _it, at_ in wakes_svc.wake_rows()}
check("_wakes collects an item that stores only an until, at the moment of that date", {w1, w2, w3} <= set(coll) and coll[w1] == wakes_svc.wake_at(day(-1)) and coll[w3] == wakes_svc.wake_at(day(3)), coll)
check("_next_wake sees it (the runner sleeps until the earliest)", wakes_svc.next_wake() is not None and wakes_svc.next_wake() <= wakes_svc.wake_at(day(-1)))
woke = wakes_svc.wake_pass()
check("_wake_pass releases a hold that stood on an until, and drops the until with it", w1 in woke and "hold" not in smt(911) and "until" not in smt(911) and "hold_set" not in smt(911), (woke, smt(911)))
check("_wake_pass treats an until on an item not on hold as a reminder, and the until goes", w2 in woke and "until" not in smt(912) and srd(912)["status"] == "open", (woke, smt(912)))
check("_wake_pass leaves an until still ahead alone", w3 not in woke and smt(913).get("until") == day(3) and smt(913).get("hold"), (woke, smt(913)))
w4 = sitem(914, until=day(3), needs=[BACK], mover=BACK)
pk = server._wake_park(w4, now)
check("_wake_park reads an until as the wake: it gets past 'no wake' to judge the wait", pk["why"] != "not an open item with a wake and no hold", pk)
check("_wake_park: an item with no date at all is still 'no wake'", server._wake_park(sitem(915, needs=[BACK], mover=BACK), now)["why"] == "not an open item with a wake and no hold")
_cfg.CFG["model"]["watchers"] = True

# the arrival text through the server's own turn
w5 = sitem(921, until=day(-1), needs=[BACK], mover=BACK)
out = {}
fired = watching_svc.watch_fire(w5, "time", now, out)
rows = [r for rs in out.values() for r in rs]
check("_watch_fire (time): the arrival text says the until, not the wake", fired and rows and all(r[2] == f"its until {day(-1)} came" for r in rows) and "until" not in smt(921), (fired, out, smt(921)))
w6 = sitem(922, wake=day(-1), wait_kind="time", needs=[BACK], mover=BACK)
out = {}
fired = watching_svc.watch_fire(w6, "time", now, out)
rows = [r for rs in out.values() for r in rs]
check("_watch_fire (time): a legacy wake still says its wake", fired and rows and all(r[2] == f"its wake {day(-1)} came" for r in rows), (fired, out))
w7 = sitem(923, wait_kind="relay", until=day(-1), wait_event="the vendor", needs=[BACK], mover=BACK)
out = {}
fired = watching_svc.watch_fire(w7, "relay", now, out)
rows = [r for rs in out.values() for r in rs]
check("_watch_fire (relay): the item turns to the owner and the arrival text names the until day as the ask-by day", fired and f"its ask-by day {day(-1)} came" in json.dumps(srd(923)) and "until" not in smt(923), (fired, smt(923)))

# an unparsable until: read as a date that never comes, never an error
bad = item(until="someday")
mb = derive(bad)
check("an unparsable until: the item reads waiting, nothing is due, no reader raises", mb.state == M.WAITING and WK.time_epoch(bad["metadata"]) is None and WK.next_moment(bad["metadata"]) is None and WK.due({"metadata": bad["metadata"]}, now) == ""
      and ST.not_due(item(until="someday", state="doing", needs=[BACK]), now) is not None and AC.check_stale(bad, bad["metadata"], BACK, lambda i: [], now, now - 40 * H) == ""
      and len(M.check_fields({"until": "someday"})) == 1 and W.wake_epoch("someday") is None, (mb.state, WK.time_epoch(bad["metadata"])))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
