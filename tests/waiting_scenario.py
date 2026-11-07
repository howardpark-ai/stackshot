"""Scenario test for the one rule for waiting items — fixture data, no live store, no network.

Every open item always has a MOVER (the one party whose move it is now) and an EXPECTED-BY, and an item past its expected-by is
surfaced (get, the board) whatever kind of wait it is in (waiting.py). Nothing escalates it: the ladder that once did (mover, then
the keeper, then a stuck list) is gone, and so are its records and everything that showed them.

Covers: the derivation for every wait (a plain on-agent item, needs decision / external / a session, a wake, a hold with a wake,
a due date, a check, a hold waiting for a pane recycle, a hold with no date of its own given the cap, `after` inheriting the
blocker's mover and expected-by (the later of two, closed ones ignored, a loop safe), a failed wait) and the rollout floor; no
ladder code is left (no tick, no step, no landing, no [waiting] ladder key) and a late item gets no notice and no record; the cap
on a wake a session sets ([waiting] cap_days, cap_needs_owner, a checked said entry, a board answer, the anchored backstop);
after=[] / "none" / clear_after=true clear the list, through the MCP layer too; a failed notice delivery is recorded on the item;
the surfaces: get, the items API, the item page, board.md, the brief, a parked item turning stale past its expected-by; and
what is gone from them: board.md's Stuck section, the brief's stuck count and lines, the audit status's waiting counts, the items
API's step.
Review round: a machine is unreachable only after online_minutes from its last check-in or the server's start; a due date
at the end of time is no date and one bad item stops no pass or tick; the cap gates a wake (not a due date, which is accepted but
clamped: the expected-by is never later than the last move + cap_days unless his words are recorded for that very date, as for a
wake), has no anchored exemption, takes an Acked-by entry checked against a message from the last cap_days or a board answer since
the item's last move; a change to what an item waits on drops a failed wait and an old ladder record; a close of an `after` item
releases it or leaves the others (no failed wait); the rollout floor staggers derived dates by a per-item jitter and the board
shows nothing derived as late before the server's record has a baseline. An old waiting.json (with the ladder's keys) is read for
its baseline and first-seen dates only and is never rewritten.

    tests/run-suite waiting        → exit 0 / 1"""
import asyncio, json, os, re, sys, pathlib, tempfile, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="waitingtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the wake and the waiting rule, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone"), 1)}
now0 = time.time()
DAY = 86400.0
ZONE_OFFSET = 4 * 3600.0                             # the instance timezone (the config's `timezone` above): UTC+4, no DST
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", **({"gone": "2026-01-01T00:00:00Z"} if n == "home-gone" else {})} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-sparrow", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-stew": "builds it"}, "back_agents": {"team-back": "the back", "home-stew": "builds it"}}}}))   # the keeper is the page's builder home-stew; the page's name line (home-sparrow) is no session to tell: the router rules what is addressed to it
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-stew: builds it\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("500"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    # the creator is no one's mover. An item the scenario means to be moved by its first session (what the creator used to be) stores that mover, as the server's start pass does for a live item with none.
    if status == "open" and not any(meta.get(k) for k in ("needs", "state", "wait_kind")):
        meta = {("post_wake_mover" if (meta.get("hold") or meta.get("after") or meta.get("recycle")) else "mover"): owner or U["home-owner"], **meta}
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": owner or U["home-owner"], "project": "projects/alpha", "next": "do the thing", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
import server, waiting as W
from ui import render as ui_render
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
told = []
real_tell = server._tell_woken
server._tell_woken = lambda gid, owner, note, tag="wake": told.append((tag, gid, owner, note))
ST = T / "state/waiting.json"
def baseline(at):                                   # the server's record from long ago (an old file: it still carries the ladder's keys, which nothing reads): no rollout runway in the way
    ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": at, "seen": {}, "reported": [], "agent_rejudge": {"at": at, "rewritten": [], "restarted": []}}))
baseline(now0 - 82 * DAY)
def wk(offset):                                     # a wake as a session writes it, minute resolution, in the instance timezone
    return time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + offset + ZONE_OFFSET))
def W_of(i, at=None, **kw):
    at = now0 if at is None else at
    ctx = server._WaitCtx(at)
    for k, v in kw.items(): setattr(ctx, k, v)
    return server._waiting_of(f"a{i}", rd(i), at, ctx)
IDLE_S = W._idle_hours() * 3600.0

# ---- 1. the derivation, one wait at a time
item(1)                                                                       # a plain on-agent item
w = W_of(1)
check("a plain on-agent item: the owner's move, expected [idle] hours after its state clock, the kind 'idle', and past due long since (its clock is 10 days old)",
      w["mover"] == {"kind": "session", "who": U["home-owner"]} and w["wait"] == "idle" and abs(w["expected_by"] - (now0 - 10 * DAY + IDLE_S)) < 1 and w["overdue"], w)
item(2, needs=["decision"], ask="Decide: x · Recommend: y · Stakes: z · By: no date", su=now0 - 1 * DAY)
w = W_of(2)
check("needs decision: Oliver's move, 3 days (default_days) after the state clock, not yet due",
      w["mover"] == {"kind": "owner", "who": server.OWNER} and w["wait"] == "needs" and abs(w["expected_by"] - (now0 - DAY + 3 * DAY)) < 1 and not w["overdue"], w)
item(3, needs=["external"], su=now0 - 4 * DAY)
w = W_of(3)
check("needs external: an outside party's move, past due after 3 days", w["mover"]["kind"] == "outside" and w["wait"] == "needs" and w["overdue"], w)
item(4, needs=["team-back"], su=now0 - 1 * DAY)
w = W_of(4)
check("needs naming a session: that session's move, counted in hours (3 hours from its clock, so a day-old one is past due)", w["mover"] == {"kind": "session", "who": "team-back"} and w["wait"] == "needs" and w["agent"] and abs(w["expected_by"] - (now0 - DAY + 3 * 3600)) < 1 and w["overdue"], w)
item(5, wake=wk(2 * DAY), su=now0 - 1 * DAY)
w = W_of(5)
check("a wake alone (a reminder, no hold): the owner's move, expected at the wake", w["wait"] == "wake" and abs(w["expected_by"] - W.wake_epoch(wk(2 * DAY))) < 1 and not w["overdue"], w)
item(6, hold=True, wake=wk(-3600), su=now0 - 1 * DAY)
w = W_of(6)
check("a hold with a wake: the kind 'hold', expected at the wake; the wake past: past due (a held item is no longer exempt)", w["wait"] == "hold" and w["overdue"] and w["mover"]["who"] == U["home-owner"], w)
item(7, due="2026-10-25", su=now0 - 1 * DAY)
w = W_of(7)
check("a due date: expected at the end of that day (instance timezone)", w["wait"] == "due" and abs(w["expected_by"] - W.due_epoch("2026-10-25")) < 1, w)
item(8, check="pr_merged o/r#1", su=now0 - 1 * DAY)
w = W_of(8)
check("a check with empty needs (its mover only the owner by fallback) keeps the cap (7 days) after it was set: an agent wait only when needs names another session", w["wait"] == "check" and not w["agent"] and abs(w["expected_by"] - (now0 - DAY + 7 * 3600 * 24)) < 1 and not w["overdue"], w)
item(9, hold=True, recycle=True, recycle_at=now0 - 2 * DAY, su=now0 - 2 * DAY)
w = W_of(9)
check("a hold waiting for a pane recycle: the fleet tool's move, expected the cap after the recycle was flagged",
      w["wait"] == "recycle" and w["mover"] == {"kind": "outside", "who": "the fleet tool (pane recycle)"} and abs(w["expected_by"] - (now0 - 2 * DAY + 7 * DAY)) < 1, w)
server._cfg.CFG.setdefault("fleet", {})["tool_name"] = "sala"; w_named = W_of(9); server._cfg.CFG["fleet"]["tool_name"] = ""
check("…and with [fleet] tool_name set the mover is named by it", w_named["mover"] == {"kind": "outside", "who": "sala (pane recycle)"}, w_named)
item(10, hold=True, su=now0 - 1 * DAY)
w = W_of(10)
check("a hold with no wake, after or recycle (a legacy park): given now + the cap once, and flagged as having no date of its own", w["nodate"] and w["wait"] == "hold" and abs(w["expected_by"] - (now0 + 7 * DAY)) < 1 and not w["overdue"], w)
w = W_of(10, seen=lambda g: now0 - 9 * DAY)
check("…with the date the server first saw it, it does not slide: past due once the cap has run", w["nodate"] and w["overdue"] and abs(w["expected_by"] - (now0 - 2 * DAY)) < 1, w)
item(10, hold=True, hold_set={"at": now0 - 8 * DAY, "by": "home-owner"}, su=now0 - 1 * DAY)
w = W_of(10)
check("…and a hold the server stamped (metadata.hold_set) counts from that stamp, the one the holds report already uses", w["overdue"] and abs(w["expected_by"] - (now0 - 8 * DAY + 7 * DAY)) < 1, w)
item(11, hold=True, wake=wk(DAY), after=["a12", "a13", "a14"], su=now0 - 1 * DAY)
item(12, owner=U["team-back"], wake=wk(3 * DAY), su=now0 - DAY); item(13, owner=U["home-other"], wake=wk(5 * DAY), su=now0 - DAY); item(14, status="completed", outcome="done")
w = W_of(11)
check("after two open blockers: the later of the two decides, and its mover is the item's (via it); a closed blocker is ignored",
      w["wait"] == "after" and w["mover"] == {"kind": "session", "who": U["home-other"], "via": "a13"} and abs(w["expected_by"] - W.wake_epoch(wk(5 * DAY))) < 1 and not w["overdue"], w)
item(15, after=["a16"]); item(16, after=["a15"])
w = W_of(15)
check("a loop of afters does not hang: it falls through to the item's own wait", w["wait"] in ("idle", "after") and w["expected_by"] > 0, w)
item(17, wait_failed={"what": "check pr_merged o/r#2", "why": "its pull request was closed without being merged", "at": now0 - 3600}, su=now0 - 1 * DAY)
w = W_of(17)
check("a failed wait: expected when it failed, past due at once, saying why", w["wait"] == "failed" and w["overdue"] and abs(w["expected_by"] - (now0 - 3600)) < 1 and "closed without being merged" in w["why"], w)
item(18, owner=U["home-gone"], hold=True, wake=wk(5 * DAY), su=now0 - 1 * DAY)
w = W_of(18)
check("a mover that cannot move matters only when the item needs its move now: its wake days off is not past due, and nothing reads it as down", not w["overdue"] and not w["down"] and w["expected_by"] > now0 + 4 * DAY, w)
item(19, owner=U["home-gone"], hold=True, wake=wk(-3600), su=now0 - 1 * DAY)
w = W_of(19)
check("…its wake past: past due by the date, and the pane being gone changes nothing (no down tracking is wired: waiting.compute takes it as an argument for the fleet-recovery work)", w["overdue"] and not w["down"] and abs(w["expected_by"] - W.wake_epoch(wk(-3600))) < 1, w)
w = W.compute({**rd(19), "gid": "a19"}, now0, None, lambda who: "is not running (its pane is gone)", None, 0.0)
check("…waiting.compute still reads a mover given as down (its `down` argument): the reason named, past due", "is not running" in w["down"] and "is not running" in w["why"] and w["overdue"], w)
rf = W.compute({**rd(2), "gid": "a2"}, now0, None, None, None, now0 + 10 * DAY)
rw = W.compute({**rd(5), "gid": "a5"}, now0, None, None, None, now0 + 10 * DAY)
check("the rollout floor lifts a derived date (needs + default) to the floor plus a per-item jitter of up to default_days, never a date the item carries (a wake); raw_eb keeps the item's own",
      now0 + 10 * DAY <= rf["expected_by"] < now0 + 13 * DAY and abs(rf["raw_eb"] - (now0 - DAY + 3 * DAY)) < 1 and abs(rw["expected_by"] - W.wake_epoch(wk(2 * DAY))) < 1 and rw["raw_eb"] == rw["expected_by"], (rf, rw))
ja = [W.jitter(f"a{i}") for i in range(300)]
check("the jitter is a fixed fraction in [0, 1) of the item id, spread over the range", all(0 <= j < 1 for j in ja) and max(ja) - min(ja) > 0.9 and W.jitter("a7") == W.jitter("a7") and W.jitter("a7") != W.jitter("a8"), (min(ja), max(ja)))
check("the floor before the server's first pass: none for a call without a clock, now + default_days for a reader (nothing derived reads as late before the rule has started)",
      W.floor_of({"baseline": None}) == 0.0 and abs(W.floor_of({"baseline": None}, now0) - (now0 + 3 * DAY)) < 1 and abs(W.floor_of({"baseline": now0 - DAY}, now0) - (now0 + 2 * DAY)) < 1)
check("words: who, when, past due by, why; the item page leaves the 'expected by' lead to its heading",
      W.line(W_of(17), now0, str, str).startswith(f"{U['home-owner']} · expected by ") and "past due by" in W.line(W_of(17), now0, str, str) and W.line(W_of(2), now0, lead=False).startswith(f"{server.OWNER} · ") and "expected by" not in W.line(W_of(2), now0, lead=False),
      (W.line(W_of(17), now0), W.line(W_of(2), now0, lead=False)))

# ---- 1b. an item that waits after agent work in progress (a doing item whose mover is a session): due AFTER_DOING_SECONDS (12 h) after that item's last write, not a cap from its own last move
def doing_blocker(i, upd, state_upd=None, **meta):          # a doing item last written `upd` (and state-changed `state_upd`); the waiter below has a much older clock of its own
    item(i, needs=["team-back"], state="doing", **meta)
    d = rd(i); d["updated"] = upd; d["state_updated"] = upd if state_upd is None else state_upd; (T / f"store/a/{i}.json").write_text(json.dumps(d))
H12 = 12 * 3600.0
check("the named constant is 12 hours and the agent_hours clock is still 3", W.AFTER_DOING_SECONDS == H12 == 43200.0 and W.agent_hours() == 3.0 and W.cap_days() == 7.0, (W.AFTER_DOING_SECONDS, W.agent_hours(), W.cap_days()))
doing_blocker(48, now0 - 11 * 3600); item(47, after=["a48"], su=now0 - 5 * DAY)
w = W_of(47)
check("after a doing item last written 11 h ago: not past due, expected 12 h after that write (the waiter's own 5-day-old clock is not the anchor), the blocker's mover", w["wait"] == "after" and w["mover"] == {"kind": "session", "who": "team-back", "via": "a48"} and not w["overdue"] and abs(w["expected_by"] - (now0 - 11 * 3600 + H12)) < 1, w)
doing_blocker(54, now0 - 13 * 3600); item(49, after=["a54"], su=now0 - 5 * DAY)
w = W_of(49)
check("…last written 13 h ago: past due, by about an hour", w["wait"] == "after" and w["overdue"] and abs(w["expected_by"] - (now0 - 13 * 3600 + H12)) < 1 and "past due by" in W.line(w, now0), w)
doing_blocker(88, now0 - 5 * 3600, state_upd=now0 - 20 * 3600); item(87, after=["a88"], su=now0 - 5 * DAY)
w = W_of(87)
check("the anchor is the later of updated and state_updated: a write 5 h ago keeps it alive although the state changed 20 h ago", not w["overdue"] and abs(w["expected_by"] - (now0 - 5 * 3600 + H12)) < 1, w)
doing_blocker(94, now0 - 13 * 3600); item(92, after=["a94"], su=now0 - 5 * DAY)
w_before = W_of(92); d_ = rd(94); d_["updated"] = now0 - 60; (T / "store/a/94.json").write_text(json.dumps(d_)); w_after = W_of(92)
check("…a write by the builder resets the clock: past due at 13 h, not past due once the blocker is written again, expected 12 h after that write", w_before["overdue"] and not w_after["overdue"] and abs(w_after["expected_by"] - (now0 - 60 + H12)) < 1, (w_before["expected_by"] - now0, w_after["expected_by"] - now0))
doing_blocker(96, now0 - 13 * 3600); item(95, after=["a96"], su=now0 - 60)
w = W_of(95)
check("a waiter set a minute ago behind a builder item quiet for 13 h is past due too: the clock follows the builder's item, not the waiter's", w["overdue"], w)
item(98, needs=["team-back"], su=now0 - 13 * 3600); item(97, after=["a98"], su=now0 - 5 * DAY)
w = W_of(97)
check("a blocker not stored as doing keeps its own clock (needs a session: agent_hours from its state clock): unchanged by the 12 h", w["wait"] == "after" and abs(w["expected_by"] - (now0 - 13 * 3600 + 3 * 3600)) < 1 and w["overdue"], w)
item(47, needs=["decision"], ask="Decide: x · Recommend: y · Stakes: z · By: no date", su=now0 - DAY); item(23, after=["a47"], su=now0 - 5 * DAY)
w = W_of(23)
check("a blocker waiting on the owner (not a builder): its own three-day clock, unchanged", w["mover"]["kind"] == "owner" and abs(w["expected_by"] - (now0 - DAY + 3 * DAY)) < 1 and not w["overdue"], w)
item(49, wake=wk(2 * DAY), su=now0 - 13 * 3600); item(48, after=["a49"], su=now0 - 5 * DAY)
w = W_of(48)
check("a blocker with a wake keeps the wake as its date: unchanged by the 12 h", abs(w["expected_by"] - W.wake_epoch(wk(2 * DAY))) < 1 and not w["overdue"], w)
for _i in sorted(set([47, 48, 49, 54, 87, 88, 92, 94, 95, 96, 97, 98, 23, 47, 48, 49])): (T / f"store/a/{_i}.json").unlink(missing_ok=True)

# ---- 2. no ladder: an item past its expected-by is shown (get, the board) and nothing else happens; no tick, no step, no record
import inspect
for i in range(1, 20): (T / f"store/a/{i}.json").unlink(missing_ok=True)
baseline(now0 - 82 * DAY)
LATE = 30
item(LATE, hold=True, wake=wk(-3600), su=now0 - 1 * DAY)
eb = W.wake_epoch(wk(-3600))
w = W_of(LATE, eb + 600)
check("a hold ten minutes past its wake: past due, its mover the owner", w["overdue"] and w["wait"] == "hold" and w["mover"] == {"kind": "session", "who": U["home-owner"]}, w)
g30 = server.stackshot_get(f"a{LATE}")
check("get shows it on its waiting line, as past due, with no step of a ladder and no stuck mark", "waiting: " in g30 and "past due" in g30 and not re.search(r"step \d of \d|\(stuck\)|stuck list", g30), g30)
check("no waiting tick is left: it is not on the runner's table, and the server has no function of that name nor of its plan, send or record",
      not any("waiting" in t.name for t in server._minute_ticks()) and not any(hasattr(server, n) for n in ("_waiting_tick", "_wait_plan", "_wait_record", "_wait_raise", "_wait_text", "_wait_options", "_wait_recipient", "_wait_hint", "_waiting_counts", "_WAIT_LAST", "_DOWN_SINCE")),
      [n for n in dir(server) if "wait" in n.lower()][:30])
check("waiting.py has no ladder: no steps, no landings, no grace, no record check", not any(hasattr(W, n) for n in ("STEPS", "LANDINGS", "grace_hours", "agent_grace_hours", "stuck_to", "grace_for", "start_of", "step_due", "record_of", "record_valid", "stuck_step")),
      [n for n in dir(W) if not n.startswith("_")])
check("the ladder's config keys are gone from the [waiting] defaults", not {"grace_hours", "agent_grace_hours", "stuck_to"} & set(W.DEFAULTS) and "grace_hours" not in toml and "agent_grace_hours" not in toml, sorted(W.DEFAULTS))
told.clear()
server._update(f"a{LATE}", next="home-owner: moved on", sender="home-owner")
check("a state change on a late item sends the server's ordinary notices only: none of tag 'wait', and it writes no record under `waiting`", not [t for t in told if t[0] == "wait"] and "waiting" not in rd(LATE)["metadata"], (told, rd(LATE)["metadata"]))

# ---- 3. the rollout floor and the holds with no date of their own (read from the server's record; nothing in the server writes it now)
for i in range(30, 60): (T / f"store/a/{i}.json").unlink(missing_ok=True)
ST.unlink(missing_ok=True)
item(50, needs=["external"], su=now0 - 20 * DAY)                              # old, with only a derived date
item(51, hold=True, su=now0 - 20 * DAY)                                       # a legacy park with no date at all
item(52, hold=True, wake=wk(-3600), su=now0 - 20 * DAY)                       # an item that carries its own date
check("with no record on disk, an item with only a derived date has a runway (not past due) and one with its own date past is past due; a hold with no date of its own is given now + the cap",
      not W_of(50)["overdue"] and W_of(52)["overdue"] and W_of(51)["nodate"] and not W_of(51)["overdue"] and abs(W_of(51)["expected_by"] - (now0 + 7 * DAY)) < 1, (W_of(50), W_of(51), W_of(52)))
check("…and reading it writes nothing: the record is not created by a read", not ST.exists())
ST.write_text(json.dumps({"baseline": now0, "seen": {"a51": now0}}))
check("past the runway (baseline + default_days, and its jitter of up to as much again) the needs item is past due; the undated hold, remembered at the baseline, not before the cap has run",
      not W_of(50, now0 + 2 * DAY)["overdue"] and W_of(50, now0 + 6 * DAY + 60)["overdue"] and not W_of(51, now0 + 6 * DAY + 60)["overdue"] and W_of(51, now0 + 8 * DAY)["overdue"],
      (W_of(50, now0 + 6 * DAY + 60), W_of(51, now0 + 8 * DAY)))

# ---- 4. a close of an `after` item (no failed wait: the item is released, or still waits on the others), a mover that is down
for i in range(30, 60): (T / f"store/a/{i}.json").unlink(missing_ok=True)
baseline(now0 - 82 * DAY)
item(60, hold=True, wake=wk(5 * DAY), after=["a61"], su=now0 - DAY, wait_failed={"what": "after a99", "why": "an old failure", "at": now0 - 82}); item(61, wake=wk(3 * DAY))
told.clear()
server.stackshot_complete("a61", outcome="dropped", reason="not needed", description="- Dropped", sender="home-owner")
m60 = rd(60)["metadata"]
check("the last prerequisite dropped: the item is released, so nothing is waited on and nothing failed: no wait_failed (a stale one included), no old ladder record, hold, wake and after gone",
      not any(k in m60 for k in ("wait_failed", "waiting", "hold", "wake", "after")), m60)
check("…the item's default mover (the project's builder: no mover is stored) is told once, by the wake notice that says the prerequisite was dropped",
      [(t[0], t[2]) for t in told if t[1] == "a60"] == [("wake", U["home-stew"])] and "a61" in [t[3] for t in told if t[1] == "a60"][0] and "dropped" in [t[3] for t in told if t[1] == "a60"][0], told)
told.clear()
item(63, hold=True, wake=wk(5 * DAY), after=["a64", "a65"], su=now0 - DAY); item(64, wake=wk(3 * DAY)); item(65, wake=wk(4 * DAY))
told.clear()
server.stackshot_complete("a64", outcome="dropped", reason="not needed", description="- Dropped", sender="home-owner")
m63 = rd(63)["metadata"]
check("a prerequisite dropped while another still stands: the wait goes on, on the one left; nothing failed, nobody is told", m63.get("after") == ["a65"] and "wait_failed" not in m63 and m63.get("hold") is True and not [t for t in told if t[1] == "a63"], (m63, told))
item(66, hold=True, wake=wk(5 * DAY), after=["a67"], su=now0 - DAY); item(67, wake=wk(3 * DAY))
server.stackshot_complete("a67", outcome="superseded", superseded_by="a61", reason="replaced", description="- Replaced", sender="home-owner")
check("a prerequisite superseded by an item that is not open is no failure either: the item is released", "after" not in rd(66)["metadata"] and "wait_failed" not in rd(66)["metadata"], rd(66)["metadata"])
for i in range(60, 70): (T / f"store/a/{i}.json").unlink(missing_ok=True)

def fleet_gone(on):                                  # home-gone's pane: gone for months (past the grace) or running
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", **({"gone": "2026-01-01T00:00:00Z"} if n == "home-gone" and on else {})} for n, u in U.items()}))
fleet_gone(True)

# ---- 4b. a machine counts as unreachable only after its puller has been silent for online_minutes from its last check-in or the server's start
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": False, "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now0 - 7200))}}))
fleet_gone(False)
real_started = server._STARTED
server._STARTED = now0 - 60
check("the server started a minute ago: a puller that reads late because of the server's own downtime is not unreachable", server._machine_unreachable("a", now0) == "", server._machine_unreachable("a", now0))
server._STARTED = now0 - 3600
check("the server has been up an hour and the puller last checked in two hours ago: unreachable", "puller is not checking in" in server._machine_unreachable("a", now0), server._machine_unreachable("a", now0))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": False, "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now0 - 60))}}))
check("…a puller that checked in a minute ago is not (online_minutes is ten)", server._machine_unreachable("a", now0) == "", server._machine_unreachable("a", now0))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": False, "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now0 - 7200))}}))
nmx, idxx = server._anc.names(), server._sessions_index()
check("a running session on it reads as unreachable then, with the reason", "is unreachable" in server._session_down(U["home-other"], nmx, idxx, None, now0), server._session_down(U["home-other"], nmx, idxx, None, now0))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
server._STARTED = real_started
fleet_gone(True)

# ---- 5. the cap on a wake a session sets
for i in range(30, 70): (T / f"store/a/{i}.json").unlink(missing_ok=True)
item(70, su=now0 - DAY)
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
server._update("a70", wake=day(6), sender="home-owner")
check("a wake within the cap (6 days) is accepted", rd(70)["metadata"].get("wake") == day(6), rd(70)["metadata"])
refused("a wake past the cap (8 days) is refused, naming the cap, the config key, and the ways to his words: ask him to answer on the item (first), or a checked said entry",
        lambda: server._update("a70", wake=day(8), sender="home-owner"), "at most 7 days", "[waiting] cap_days", "said=", "to answer on the item")
check("…the refusal left the wake as it was", rd(70)["metadata"].get("wake") == day(6), rd(70)["metadata"])
refused("a hold with a far wake is refused the same way", lambda: server._update("a70", hold=True, wake=day(20), sender="home-owner"), "at most 7 days")
server._cfg.CFG["waiting"]["cap_days"] = 10
server._update("a70", wake=day(9), sender="home-owner")
check("[waiting] cap_days is a config value, read at use", rd(70)["metadata"].get("wake") == day(9), rd(70)["metadata"])
server._cfg.CFG["waiting"]["cap_days"] = 7
server._cfg.CFG["waiting"]["cap_needs_owner"] = False
server._update("a70", wake=day(20), sender="home-owner")
check("cap_needs_owner = false: a longer wake is allowed", rd(70)["metadata"].get("wake") == day(20), rd(70)["metadata"])
server._cfg.CFG["waiting"]["cap_needs_owner"] = True
server._update("a70", wake="none", sender="home-owner")
# his words, checked against a real transcript
TR = T / "transcripts" / "-home-x"
def entry(uuid, text, kind="human", ts=None):
    return json.dumps({"type": "user", "uuid": uuid, "timestamp": ts or time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now0 - 3600)), "origin": {"kind": kind}, "promptSource": "typed", "message": {"role": "user", "content": text}})
(TR / f"{U['home-owner']}.jsonl").write_text(entry("11111111-1111-4111-8111-000000000001", "keep it on hold for ten days") + "\n"
                                           + entry("11111111-1111-4111-8111-000000000002", "relayed text", kind="peer") + "\n"
                                           + entry("11111111-1111-4111-8111-000000000003", "park it until the end of the month", ts="2026-09-01T00:00:00.000Z") + "\n")
server._update("a70", wake=day(10), sender="home-owner", said=[{"tag": "Acked-by", "quote": "keep it on hold for ten days", "msg": "11111111-1111-4111-8111-000000000001"}])
check("a longer wake with his words behind it (an Acked-by entry checked against the transcript) is accepted", rd(70)["metadata"].get("wake") == day(10) and rd(70)["metadata"]["said"][-1]["checked"] is True, rd(70)["metadata"])
server._update("a70", wake="none", sender="home-owner")
refused("an unchecked said entry (a session whose transcript this box cannot read) is not enough for a long wake",
        lambda: server._update("a70", wake=day(10), sender="home-owner", said=[{"tag": "Acked-by", "quote": "park it", "msg": "11111111-1111-4111-8111-000000000009", "session": "cse_0123456789abcdef"}]), "at most 7 days")
refused("a said entry that is checked but not tagged Acked-by (Suggested-by) is not his word for a long wait",
        lambda: server._update("a70", wake=day(10), sender="home-owner", said=[{"tag": "Suggested-by", "quote": "keep it on hold for ten days", "msg": "11111111-1111-4111-8111-000000000001"}]), "at most 7 days")
refused("a checked Acked-by entry for a message older than cap_days is not enough either (his words from a month ago)",
        lambda: server._update("a70", wake=day(10), sender="home-owner", said=[{"tag": "Acked-by", "quote": "park it until the end of the month", "msg": "11111111-1111-4111-8111-000000000003"}]), "at most 7 days")
item(71, su=now0 - DAY, answers=[{"ts": now0 - 3600, "kind": "decision", "text": "wait until after the 30th", "via": "board"}])
server._update("a71", wake=day(12), sender="home-owner")
check("his board answer on the item, given since its last state change, is enough", rd(71)["metadata"].get("wake") == day(12), rd(71)["metadata"])
item(72, su=now0 - DAY, answers=[{"ts": now0 - 30 * DAY, "kind": "decision", "text": "an old answer", "via": "board"}])
refused("…an answer from before the item's last state change is not", lambda: server._update("a72", wake=day(12), sender="home-owner"), "at most 7 days")
item(74, su=now0 - DAY, answers=[{"ts": now0 - 3600, "kind": "decision", "text": "ok, wait until after the 30th", "via": "board"}])
server._update("a74", next="home-owner: moved on a little", sender="home-owner")
refused("…nor is one the item has moved past since (a session's update after his answer used it up)", lambda: server._update("a74", wake=day(12), sender="home-owner"), "at most 7 days")
item(73, su=now0 - DAY)
real_scoped = server._scoped_anchors
server._scoped_anchors = lambda project, gid: [{"url": "https://x", "items": [gid]}]
server._update("a73", hold=True, wake=day(6), wait_basis=f"visit on {day(8)}", sender="home-owner")
refused("no wait is exempt: a hold on an anchored thread with a backstop wake past the cap is refused like any long wait", lambda: server._update("a73", hold=True, wake=day(25), sender="home-owner"), "at most 7 days")
server._scoped_anchors = real_scoped
item(75, su=now0 - DAY)
r75 = server._update("a75", due=day(20), sender="home-owner")
check("a due date is a deadline, not a wait: one three weeks out is accepted on update", rd(75)["metadata"].get("due") == day(20), rd(75)["metadata"])
check("…and the reply says its expected-by is capped, at which date, and why", "expected-by capped at " in r75 and f"past 7 days needs {server.OWNER}'s words" in r75, r75)
out = server._create(subject="[home] far due", description=DESC, project="projects/alpha", owner="home-owner", next="home-owner: x", due=day(30))
check("…and on create, with the same line", out.startswith("created ") and "expected-by capped at " in out, out)
w = W_of(75)
check("…but its expected-by is never later than the item's last move + cap_days (setting the due was itself a move: the cap runs seven days from this write), whatever the due says",
      w["wait"] == "due" and abs(w["expected_by"] - (rd(75)["state_updated"] + 7 * DAY)) < 1 and "capped" in w["basis"] and not w["overdue"], w)
w8 = W_of(75, now0 + 8 * DAY)
check("…so an item due in three weeks surfaces after cap_days without a move", w8["overdue"], w8)
baseline(now0 - 82 * DAY); told.clear()
server._update("a75", next="home-owner: moved on", sender="home-owner")
w9 = W_of(75, time.time() + 6 * DAY)
check("a move restarts the clamp window (the cap after the new move); a far due is still a due date", not w9["overdue"] and w9["wait"] == "due", w9)
server._cfg.CFG["waiting"]["cap_needs_owner"] = False
w10 = W_of(75, time.time() + 8 * DAY)
check("cap_needs_owner = false lifts the clamp: the due date stands", not w10["overdue"] and abs(w10["expected_by"] - W.due_epoch(day(20))) < 1, w10)
server._cfg.CFG["waiting"]["cap_needs_owner"] = True
item(76, su=now0 - 2 * DAY, wake=day(30), hold=True)                 # a wake stored before the rule (no words recorded): read as it is, not refused, but clamped
w = W_of(76)
check("a wake stored earlier with no words recorded is clamped to the cap after the item's last move too", abs(w["expected_by"] - (now0 - 2 * DAY + 7 * DAY)) < 1 and "capped" in w["basis"], w)
item(77, su=now0 - DAY)
server._update("a77", wake=day(10), sender="home-owner", said=[{"tag": "Acked-by", "quote": "keep it on hold for ten days", "msg": "11111111-1111-4111-8111-000000000001"}])
m77 = rd(77)["metadata"]
w = W_of(77)
check("a wake past the cap accepted on his words records them (cap_ok) and its expected-by stands at the wake, not clamped", m77.get("cap_ok", {}).get("wake") == day(10) and m77["cap_ok"]["by"] == "a checked said entry"
      and abs(w["expected_by"] - W.wake_epoch(day(10))) < 1 and "capped" not in w["basis"], (m77, w))
server._update("a77", wake=day(3), sender="home-owner")
check("a new wake within the cap drops the record of his words", "cap_ok" not in rd(77)["metadata"], rd(77)["metadata"])
item(78, su=now0 - DAY, wake=day(10), cap_ok={"wake": day(11), "by": "a board answer"}, hold=True)
check("words recorded for another wake do not cover this one", "capped" in W_of(78)["basis"], W_of(78))
item(79, su=now0 - 2 * DAY, after=["a80"]); item(80, owner=U["team-back"], su=now0 - DAY, wake=day(20), cap_ok={"wake": day(20), "by": "a board answer"})
w = W_of(79)
check("an item waiting after a blocker whose far date has his words is still clamped by its own last move: waiting on a far blocker is not a way past the cap",
      w["wait"] == "after" and abs(w["expected_by"] - (now0 - 2 * DAY + 7 * DAY)) < 1 and W_of(80)["expected_by"] > now0 + 18 * DAY, (w, W_of(80)))
# ---- 5b. Oliver's words for a far due date, the hint for a clamped item, the after clamp's down grace, the records' lifetime, the rollout floor
item(83, su=now0 - DAY)
r_cap = server._update("a83", due=day(20), sender="home-owner", said=[{"tag": "Acked-by", "quote": "keep it on hold for ten days", "msg": "11111111-1111-4111-8111-000000000001"}])
m_cap = rd(83)["metadata"]
w = W_of(83)
check("a far due date accepted on his words records them (cap_ok due) and stands at the due, not clamped, with no capped line in the reply",
      m_cap.get("cap_ok", {}).get("due") == day(20) and m_cap["cap_ok"]["due_by"] == "a checked said entry" and abs(w["expected_by"] - W.due_epoch(day(20))) < 1
      and "capped" not in w["basis"] and "expected-by capped" not in r_cap, (m_cap, w, r_cap))
w = W_of(75)
check("…the same due without words is clamped (item 75 above)", "capped" in w["basis"] and "cap_ok" not in rd(75)["metadata"], (w, rd(75)["metadata"]))
server._update("a83", due=day(21), sender="home-owner")
check("a changed due accepted without words drops the record, and the new date is clamped", "cap_ok" not in rd(83)["metadata"] and "capped" in W_of(83)["basis"], (rd(83)["metadata"], W_of(83)))
item(151, su=now0 - DAY, due=day(20), cap_ok={"due": day(21), "due_by": "a board answer"})
check("words recorded for another due date do not cover this one", "capped" in W_of(151)["basis"], W_of(151))
item(29, su=now0 - DAY, due=day(20), wake=day(10), hold=True, cap_ok={"wake": day(10), "by": "a board answer", "due": day(20), "due_by": "a board answer"})
w = W_of(29)
check("a wake and a due date each keep their own record: the wake wait stands on its words", w["wait"] == "hold" and "capped" not in w["basis"], w)
server._update("a29", due=day(22), sender="home-owner")
co = rd(29)["metadata"].get("cap_ok") or {}
check("…changing the due drops only the due's record, the wake's stays", co.get("wake") == day(10) and "due" not in co and "due_by" not in co, rd(29)["metadata"])
server._update("a29", clear_due=True, sender="home-owner")
check("…clearing the due leaves the wake's record", rd(29)["metadata"].get("cap_ok", {}).get("wake") == day(10), rd(29)["metadata"])
server._update("a29", clear_hold=True, sender="home-owner")
check("…clear_hold drops the wake and its record", "cap_ok" not in rd(29)["metadata"] and "wake" not in rd(29)["metadata"], rd(29)["metadata"])
item(43, su=now0 - DAY, wake=day(10), cap_ok={"wake": day(10), "by": "a board answer"})
server._update("a43", clear_wake=True, sender="home-owner")
check("clear_wake drops the record of his words", "cap_ok" not in rd(43)["metadata"] and "wake" not in rd(43)["metadata"], rd(43)["metadata"])
item(44, su=now0 - DAY, wake=day(10), due=day(20), cap_ok={"wake": day(10), "by": "a board answer", "due": day(20), "due_by": "a board answer"})
server.stackshot_complete("a44", outcome="done", reason="finished", description="- Done", sender="home-owner")
check("completing an item drops the record", "cap_ok" not in rd(44)["metadata"] and rd(44)["status"] == "completed", rd(44)["metadata"])
# the clamp with an active rollout floor: the clamped date lands on the floor, not on the cap's (already past) date
item(84, su=now0 - 10 * DAY, due=day(30))
baseline(now0)
w = W_of(84)
fl = now0 + W.default_days() * DAY + W.jitter("a84") * W.default_days() * DAY
check("a rollout floor is active: the clamped expected-by lands on the floor (the rollout runway), raw_eb keeps the cap's date (already past), and the item is not yet overdue",
      abs(w["expected_by"] - fl) < 1 and abs(w["raw_eb"] - (now0 - 3 * DAY)) < 1 and not w["overdue"] and "capped" in w["basis"], (w, fl))
baseline(now0 - 82 * DAY)
w = W_of(84)
check("…and with the rollout over the same item is overdue at the cap's date", w["overdue"] and abs(w["expected_by"] - (now0 - 3 * DAY)) < 1, w)
item(158, su=now0 - 10 * DAY, due=day(-5))
baseline(now0)
w = W_of(158)
check("…a due date of its own that is already past is not lifted by the floor (it is not clamped: it lies before the cap)", w["overdue"] and abs(w["expected_by"] - W.due_epoch(day(-5))) < 1, w)
baseline(now0 - 82 * DAY)
fleet_gone(False)
cr = ""
async def create_desc():
    async with Client(server.mcp) as c:
        return next((x.description or "" for x in await c.list_tools() if x.name == "create"), "")
from fastmcp import Client
cr = asyncio.run(create_desc())
check("create's description carries the cap sentence", server._CAP_FORM.strip() in cr and "7 days" in cr and "capped" in cr, cr[-400:])
check("the update description carries the rule, the cap and clear_after, and no ladder: the other texts keep their form", all(x in server._WAIT_FORM for x in ("expected-by", "7 days", "clear_after=true")) and not re.search(r"stuck list|ladder", server._WAIT_FORM), server._WAIT_FORM)
_gd = asyncio.run(server.mcp.get_tool("get")).description if hasattr(server.mcp, "get_tool") else ""
_bd = asyncio.run(server.mcp.get_tool("brief")).description if hasattr(server.mcp, "get_tool") else ""
check("get and brief describe the `waiting:` line: mover, expected-by, past due, nothing sent, and teach no ladder, step or stuck list",
      all("`waiting:`" in d and "past due by" in d and "nothing is sent" in d and not re.search(r"ladder|stuck list|step \d of|grace", d) for d in (_gd, _bd)), (_gd[:80], _bd[:80]))

# ---- 6. after=[] clears; so do "none" and clear_after=true, through the MCP layer too
item(80, after=["a81"], su=now0 - DAY); item(81, su=now0 - DAY)
server._update("a80", after=[], sender="home-owner")
check("after=[] clears the list", "after" not in rd(80)["metadata"], rd(80)["metadata"])
item(80, after=["a81"], su=now0 - DAY); server._update("a80", after="none", sender="home-owner")
check('after="none" clears it', "after" not in rd(80)["metadata"], rd(80)["metadata"])
item(80, after=["a81"], su=now0 - DAY); server._update("a80", clear_after=True, sender="home-owner")
check("clear_after=true clears it, the form that survives a client that drops an empty list", "after" not in rd(80)["metadata"], rd(80)["metadata"])
item(80, after=["a81"], su=now0 - DAY)
refused("clear_after with a new list is refused", lambda: server._update("a80", clear_after=True, after=["a81"], sender="home-owner"), "clear_after drops the after list")
from fastmcp import Client
async def via_mcp():
    async with Client(server.mcp) as c:
        tools = {x.name: x for x in await c.list_tools()}
        props = tools["update"].inputSchema["properties"]
        await c.call_tool("update", {"item_id": "a80", "clear_after": True, "sender": "home-owner"})
        return props, tools["update"].description or ""
props, desc = asyncio.run(via_mcp())
check("through the MCP layer: update takes clear_after (a boolean) and clears the list, and its description names the rule", "clear_after" in props and props["clear_after"].get("type") == "boolean" and "after" not in rd(80)["metadata"] and "expected-by" in desc, (list(props), rd(80)["metadata"]))

# ---- 7. a failed delivery is recorded on the item and counted
(T / "failpush.py").write_text("import sys\nmode = open(sys.argv[0] + '.mode').read().strip()\nprint('delivered → x' if mode == 'ok' else 'FAILED → ' + sys.argv[-2]); sys.exit(0 if mode == 'ok' else 1)\n")
(T / "failpush.py.mode").write_text("fail")
server._PUSH = [sys.executable, str(T / "failpush.py")]
item(90, su=now0 - DAY)
real_tell("a90", "home-stew", "[stackshot] a test notice", tag="wait").join()
u = rd(90)["metadata"].get("undelivered") or []
check("a notice that could not be delivered is recorded on the item: who, which kind, when, why", len(u) == 1 and u[0]["tag"] == "wait" and u[0]["to"] and "FAILED" in u[0]["why"] and u[0]["at"] > now0 - 5, u)
check("…a filing record: the state clock stays", rd(90)["state_updated"] == now0 - DAY, rd(90))
for _ in range(6): real_tell("a90", "home-stew", "[stackshot] again", tag="idle").join()
check("only the last five are kept", len(rd(90)["metadata"]["undelivered"]) == 5, rd(90)["metadata"]["undelivered"])
check("get lists them", "undelivered notices:" in server.stackshot_get("a90") and "(idle) to " in server.stackshot_get("a90"), server.stackshot_get("a90"))
(T / "failpush.py.mode").write_text("ok")
item(91, su=now0 - DAY); real_tell("a91", "home-stew", "[stackshot] fine", tag="wait").join()
check("a delivered notice records nothing", "undelivered" not in rd(91)["metadata"], rd(91)["metadata"])
real_tell("a90,a91", "home-stew", "[stackshot] batch", tag="wait").join()
(T / "failpush.py.mode").write_text("fail")
real_tell("a90,a91", "home-stew", "[stackshot] batch", tag="wait").join()
check("a batched notice (several ids) is recorded on each item it was about", len(rd(91)["metadata"].get("undelivered") or []) == 1 and len(rd(90)["metadata"]["undelivered"]) == 5, (rd(90)["metadata"]["undelivered"], rd(91)["metadata"]))
server._update("a90", next="home-owner: moved", sender="home-owner")
check("a state change drops the record (the item has moved since)", "undelivered" not in rd(90)["metadata"], rd(90)["metadata"])
server._PUSH = [sys.executable, str(T / "failpush.py")]

# ---- 7b. a late item is not raised to anyone: past its date the server sends no notice and writes no record, whatever the mover
for i in range(30, 400): (T / f"store/a/{i}.json").unlink(missing_ok=True)
baseline(now0 - 82 * DAY)
item(85, due=day(-3), su=now0 - 5 * DAY)
told.clear()
w85 = W_of(85)
check("a due date that passed: the item is past due on the board and in get, and no `wait` notice goes to anyone", w85["overdue"] and w85["wait"] == "due" and not [t for t in told if t[0] == "wait"], (w85, told))

# ---- 7c. the rollout: staggered, nothing late on the board before the server has a record, an item late by its own date reads late at once
for i in range(85, 400): (T / f"store/a/{i}.json").unlink(missing_ok=True)
ST.unlink(missing_ok=True)
for i in range(86, 126): item(i, needs=["external"], su=now0 - 20 * DAY)            # forty items late only by a derived date
item(46, hold=True, wake=wk(-10 * DAY), su=now0 - 20 * DAY)                           # late by its own date for ten days when the server first looks
bd0 = ui_render.Board(f"{tmp}/store")
check("before the server's first pass the board shows nothing derived as late (no baseline: now + default_days), while an item late by its own date reads late",
      not any(bd0.item(f"a{i}")["_wait"]["overdue"] for i in range(86, 126)) and bd0.item("a46")["_wait"]["overdue"], [bd0.item(f"a{i}")["_wait"]["overdue"] for i in (86, 125, 46)])
ST.write_text(json.dumps({"baseline": now0, "seen": {}}))
check("with a baseline of now: the item late by its own date is past due, none of the forty derived ones is yet", W_of(46, now0)["overdue"] and not any(W_of(i, now0)["overdue"] for i in range(86, 126)), None)
ov_a = {i for i in range(86, 126) if W_of(i, now0 + 4.5 * DAY)["overdue"]}; ov_b = {i for i in range(86, 126) if W_of(i, now0 + 6.2 * DAY)["overdue"]}
check("the forty derived ones go past due spread over default_days after the runway, not all at once: some at day 4.5, all of them by day 6.2", 0 < len(ov_a) < 40 and len(ov_b) == 40, (len(ov_a), len(ov_b)))
ST.unlink(missing_ok=True)
check("losing the record changes no stored item: the forty read as before the first pass (not late), and nothing was written to them", not any(W_of(i, now0 + 6.3 * DAY)["overdue"] for i in range(86, 126)) and "waiting" not in rd(86)["metadata"], None)
W_floor = W.floor_of({"baseline": now0}, now0 + 10 * DAY)
check("the floor is the baseline plus default_days, and moves with a baseline only: the same baseline gives the same floor whenever it is read", abs(W_floor - (now0 + 3 * DAY)) < 1, W_floor)

# ---- 7d. recording a failed delivery is written under the item lock
for i in range(85, 400): (T / f"store/a/{i}.json").unlink(missing_ok=True)
baseline(now0 - 82 * DAY)
import threading
item(53, su=now0 - DAY)
with server._ITEM_LOCK:
    th = threading.Thread(target=lambda: server._record_undelivered("a53", "home-stew", "wait", "no pane"))
    th.start(); time.sleep(0.3)
    held_off = "undelivered" not in rd(53)["metadata"]
    m = rd(53); m["metadata"]["next"] = "changed under the lock holder"; (T / "store/a/53.json").write_text(json.dumps(m))
th.join(5)
check("recording a failed delivery waits for the item lock (an update in progress finishes first) and re-reads the item under it: the update's change is kept",
      held_off and rd(53)["metadata"].get("next") == "changed under the lock holder" and len(rd(53)["metadata"].get("undelivered") or []) == 1, rd(53)["metadata"])

# ---- 7e. one bad item never stops the board, a read or the pass
for i in range(85, 400): (T / f"store/a/{i}.json").unlink(missing_ok=True)
check("a due date at the end of time is no date, not an exception: 9999-12-31 and 3000-01-01 give none, a normal one a date",
      W.due_epoch("9999-12-31") is None and W.due_epoch("3000-01-01") is None and W.due_epoch("2026-12-31") is not None and W.wake_epoch("9999-12-31T23:59") is None and "unreadable" in W.when_words(1e30), (W.due_epoch("9999-12-31"),))
item(89, due="9999-12-31", su=now0 - 10 * DAY)
w = W_of(89)
check("an item with such a due date reads as an ordinary wait (its needs default), not a crash", w["wait"] in ("idle", "needs") and w["expected_by"] > 0, w)
bad = {"metadata": 5, "status": "open", "state_updated": "garbage"}
wb = W.compute({**bad, "gid": "a9"}, now0)
check("a stored value that makes the rule raise reads as not late, a date the cap away: the fallback", wb["overdue"] is False and wb["wait"] == "idle" and wb["expected_by"] > now0 and "could not be read" in wb["basis"], wb)
bdx = ui_render.Board(f"{tmp}/store")
check("the board builds with such an item on it, and shows it", bdx.item("a89")["_wait"]["expected_by"] > 0 and "a89" in bdx.markdown(), None)

# ---- 7f. a change to what the item waits on drops a failed wait and an old ladder record (one an earlier version wrote), a filing edit does not
for i in range(85, 400): (T / f"store/a/{i}.json").unlink(missing_ok=True)
fail_rec = {"what": "check pr_merged o/r#2", "why": "its pull request was closed without being merged", "at": now0 - 3600}
ladder_rec = {"since": now0 - 5 * DAY, "eb": now0 - 3600, "step": 2, "at": {"1": now0 - 90000, "2": now0 - 3600}}
for i in (55, 56, 57, 58, 62, 68, 69): item(i, wait_failed=fail_rec, waiting=ladder_rec, su=now0 - 5 * DAY)
server._update("a55", check="pr_merged o/r#5", sender="home-owner")
check("setting a check alone (a filing edit, no state change) drops the failed wait and the ladder record: the new check is a new wait", not any(k in rd(55)["metadata"] for k in ("wait_failed", "waiting")) and rd(55)["metadata"].get("check"), rd(55)["metadata"])
server._update("a56", wake=day(2), sender="home-owner")
check("a new wake drops them", not any(k in rd(56)["metadata"] for k in ("wait_failed", "waiting")), rd(56)["metadata"])
item(93, su=now0 - DAY)
server._update("a57", after=["a93"], ask_by=day(9), sender="home-owner")
check("an after list drops them", not any(k in rd(57)["metadata"] for k in ("wait_failed", "waiting")), rd(57)["metadata"])
server._update("a58", needs=["team-back"], sender="home-owner")
check("a change of needs drops them", not any(k in rd(58)["metadata"] for k in ("wait_failed", "waiting")), rd(58)["metadata"])
server._update("a62", hold=True, wake=day(3), wait_basis=f"visit on {day(8)}", sender="home-owner")
check("a hold drops them", not any(k in rd(62)["metadata"] for k in ("wait_failed", "waiting")), rd(62)["metadata"])
server._update("a68", recycle=True, hold=True, sender="home-owner")
check("a recycle wait drops them", not any(k in rd(68)["metadata"] for k in ("wait_failed", "waiting")), rd(68)["metadata"])
server._update("a69", priority="p2", sender="home-owner")
check("a filing edit that changes none of those (priority) keeps them", "wait_failed" in rd(69)["metadata"] and "waiting" in rd(69)["metadata"], rd(69)["metadata"])

# ---- 8. the surfaces: the items API, the item page, board.md, the brief, stale
for i in range(30, 400): (T / f"store/a/{i}.json").unlink(missing_ok=True)
baseline(now0 - 82 * DAY)
late = wk(-3600); eb = W.wake_epoch(late)
item(82, hold=True, wake=late, su=now0 - DAY)                                 # a hold past its wake
item(26, hold=True, wake=wk(2 * DAY), su=now0 - DAY)                         # parked, inside its date
item(27, su=now0 - DAY, undelivered=[{"to": "home-stew", "tag": "wait", "at": now0 - 60, "why": "no pane"}])
item(28, hold=True, su=now0 - DAY)                                           # no date of its own
# the page and the board read the clock too: put the wake in the page's past by moving the item's clocks in step
bd = ui_render.Board(f"{tmp}/store")
r_old = bd.item("a82")
check("the renderer computes the same rule for every open item: mover, expected-by, past due", r_old["_wait"]["overdue"] and r_old["_wait"]["wait"] == "hold" and bd.item("a26")["_wait"]["overdue"] is False, (r_old.get("_wait"), bd.item("a26").get("_wait")))
check("a parked item past its expected-by reads stale, not held; one inside it stays held", r_old["_fresh"] == "stale" and bd.item("a26")["_fresh"] == "held", (r_old["_fresh"], bd.item("a26")["_fresh"]))
check("the board has no stuck list: the Board keeps no `stuck`, and the undelivered notice and the undated hold are still listed", not hasattr(bd, "stuck") and [r["gid"] for r in bd.undelivered] == ["a27"] and [r["gid"] for r in bd.nodate] == ["a28"], ([r["gid"] for r in bd.undelivered], [r["gid"] for r in bd.nodate]))
md = bd.markdown()
check("board.md has no Stuck section; the undelivered notices and the undated waits are listed in its head (before Machines)",
      "## Stuck" not in md and "## Undelivered notices and undated waits" in md and md.index("## Undelivered notices and undated waits") < md.index("## Machines") and "Undelivered notices" in md and "no date of their own" in md and "a82" not in md.split("## Undelivered notices and undated waits")[1].split("## Machines")[0], md[md.find("## Undel"):md.find("## Machines")][:600])
br = bd.brief()
check("the brief carries an undelivered count and no stuck count and no stuck line", "1 with an undelivered notice" in br and not re.search(r"\d+ stuck|^  stuck: |more stuck", br, re.M), br)
ph = bd.item_html("a82")
check("the item page has an Expected by row in its sidebar (the only markup the rule adds), past due drawn like the stale mark", "<dt>Expected by</dt><dd><span class=\"iwarn\">" in ph and "past due" in ph, re.findall(r"<dt>Expected by</dt>.{0,300}", ph))
check("…and a parked item inside its date shows it plainly", "<dt>Expected by</dt><dd>" in bd.item_html("a26") and "past due" not in bd.item_html("a26").split("Expected by")[1][:300], bd.item_html("a26")[:0])
st_, ct_, body_ = server._client_get("items", {"key": U["home-owner"]})
x = {i["gid"]: i for i in json.loads(body_)["items"]}
check("the items API (the web board and sala read it) carries mover, expected_by, wait and overdue for a held item too, and no ladder step",
      x["a82"]["held"] and x["a82"]["overdue"] and "step" not in x["a82"] and x["a82"]["wait"] == "hold" and x["a26"]["overdue"] is False and x["a82"]["mover"]["kind"] == "session", x.get("a82"))
from starlette.testclient import TestClient
with TestClient(server.mcp.http_app()) as _tc:
    _r = _tc.get("/audit/status")
check("the audit status carries no waiting counts: GET /audit/status answers the audit's own status and no `waiting` key", _r.status_code == 200 and "waiting" not in _r.json() and set(_r.json()) == set(server._audit.status()) | {"runner", "phase_sweep"}, (_r.status_code, _r.text[:200]))      # the audit's own keys, and the minute set's runner record (runner.py); never a waiting one

# a session mover stored as a transcript id shows as its name wherever a wait is displayed (the Owner field's resolver); an id that does not resolve stays raw
_own = U["home-owner"]
check("the stored mover of a82 is the owner's transcript id (the premise of the next checks)", r_old["_wait"]["mover"]["who"] == _own and len(_own) >= 32, r_old["_wait"]["mover"])
check("item page: the Expected by row is the day only (the mover is the header's) and the page never prints the mover's transcript id", "<dt>Expected by</dt><dd>" in ph and "home-owner · " not in ph.split("Expected by")[1].split("</dd>")[0] and _own not in ph, ph.split("Expected by")[1][:400])
import copy
def _expb(gid, **over):
    """The Expected by cell of an item page, with the item's derived wait changed by `over` (a copy; the Board's row is put back)."""
    r_ = bd.item(gid); keep = r_["_wait"]; r_["_wait"] = copy.deepcopy(keep)
    for k, v in over.items(): r_["_wait"][k] = v
    try: h_ = bd.item_html(gid)
    finally: r_["_wait"] = keep
    return h_.split("<dt>Expected by</dt><dd>")[1].split("</dd>")[0], h_
_cell, _page = _expb("a82", mover={"kind": "outside", "who": "<b>evil</b> & co"}, why='<script>alert(1)</script> & "q" \'s\' home-owner stopped')
check("item page: item text in a wait (its why, a mover name) never reaches the page unescaped", "<b>evil</b>" not in _page and "<script>alert(1)</script>" not in _page and "<b>" not in _cell, _cell)
_cell, _ = _expb("a26")
check("item page: a parked item inside its date shows the day plainly, with no past-due mark", _cell and "iwarn" not in _cell and "past due" not in _cell and "<a " not in _cell, _cell)
check("board.md carries no row for the ladder's last step: the mover of a past-due hold is named on its own row, not its id",
      "## Stuck" not in md and "(the ladder's last step" not in md, md[:300])
check("the brief has no stuck line for it either, and no id of the mover", "  stuck: a82" not in br and _own not in br, br)
check("the stale tip of a parked item past its expected-by names the mover", "home-owner" in ui_render.stale_tip(r_old, bd.mover_name) and _own not in ui_render.stale_tip(r_old, bd.mover_name), ui_render.stale_tip(r_old, bd.mover_name))
check("the get tool's waiting: line already names it (the server's resolver)", server._waiting_of("a82", rd(82))["line"].startswith("home-owner · "), server._waiting_of("a82", rd(82))["line"])
check("an id that resolves to no session stays the raw id; Oliver and an outside party stay as they are",
      bd.mover_name("deadbeef-0000-4000-8000-000000000000") == "deadbeef-0000-4000-8000-000000000000"
      and W.line({"mover": {"kind": "owner", "who": "Oliver"}, "expected_by": eb, "wait": "wake", "basis": "wake"}, eb, bd.mover_name).startswith("Oliver · ")
      and W.line({"mover": {"kind": "outside", "who": "an outside party"}, "expected_by": eb, "wait": "wake", "basis": "wake"}, eb, bd.mover_name).startswith("an outside party · "))
check("why_words shows a session mover's name in the why text, an unresolved one stays raw",
      W.why_words({"mover": {"kind": "session", "who": _own}, "why": f"{_own} is stopped on an error (x)"}, bd.mover_name) == "home-owner is stopped on an error (x)"
      and W.why_words({"mover": {"kind": "session", "who": "zz"}, "why": "zz is stopped"}, bd.mover_name) == "zz is stopped")

# ---- 9. what is gone: an old waiting.json is ignored (read for its baseline and first-seen dates, never rewritten), and a store with an item in every state shows no ladder stuck line on the board or in the brief
for i in range(30, 400): (T / f"store/a/{i}.json").unlink(missing_ok=True)
hrs = lambda n: time.strftime("%Y-%m-%d %H:%M", time.gmtime(now0 + n * 3600 + ZONE_OFFSET))
OLD = {"baseline": now0 - 82 * DAY, "seen": {"a35": now0 - 9 * DAY}, "reported": ["a35"], "agent_rejudge": {"at": now0 - 82 * DAY, "rewritten": [], "restarted": []}, "ladder": {"stuck_to": "briefing"}}
ST.write_text(json.dumps(OLD)); raw_old = ST.read_text()
item(30, su=now0 - 5 * DAY)                                                                                # a plain on-agent item, idle for days
item(31, needs=["decision"], ask="Decide: x · Recommend: y · Stakes: z · By: no date", su=now0 - 5 * DAY)   # Oliver's call
item(32, needs=["external"], su=now0 - 9 * DAY)                                                            # an outside party, long past its three days
item(33, needs=["team-back"], su=now0 - 2 * DAY)                                                           # a session named in needs
item(34, hold=True, wake=wk(-3600), su=now0 - DAY)                                                         # a hold past its wake
item(35, hold=True, su=now0 - 20 * DAY)                                                                    # a hold with no date of its own
item(36, hold=True, wake=wk(3 * DAY), after=["a37"], su=now0 - DAY); item(37, wake=wk(2 * DAY), su=now0 - DAY)   # after a blocker
item(38, due=day(-4), su=now0 - 6 * DAY)                                                                   # a due date that passed
item(39, check="pr_merged o/r#9", su=now0 - 9 * DAY)                                                       # a check, long past its cap
item(40, wait_failed={"what": "check pr_merged o/r#2", "why": "its pull request was closed without being merged", "at": now0 - 3600}, su=now0 - DAY)
item(41, su=now0 - DAY, undelivered=[{"to": "home-stew", "tag": "wait", "at": now0 - 60, "why": "no pane"}])
item(42, needs=["team-back"], state="doing", expected_by=hrs(-5), su=now0 - DAY)                           # a doing item stored with a time that has long passed: the time is ignored, it is never past due
item(43, needs=["team-back"], state="verifying", proof="the link opens", end=day(-5), su=now0 - 9 * DAY)  # a verifying item past its end
item(44, status="completed", outcome="done")
item(45, hold=True, wake=wk(-3600), su=now0 - 5 * DAY, waiting={"since": now0 - 5 * DAY, "eb": now0 - 3600, "step": 3, "at": {"1": now0 - 9e4, "2": now0 - 5e4, "3": now0 - 4e3}})   # a record the ladder wrote, at its last step
item(46, owner=U["home-front"], needs=["external"], su=now0 - 9 * DAY)                                      # a front agent's outside wait
bd9 = ui_render.Board(f"{tmp}/store"); md9 = bd9.markdown(); br9 = bd9.brief()
check("the board has the open items of every state, the late ones past due (a store worth the check)",
      all(bd9.item(f"a{i}")["_wait"]["overdue"] for i in (30, 32, 34, 38, 39, 40, 43, 45)) and not bd9.item("a37")["_wait"]["overdue"], [(i, bd9.item(f"a{i}")["_wait"]["overdue"]) for i in (30, 32, 34, 37, 38, 39, 40, 43, 45)])
check("…and a doing item stored with a long-passed time is not one of them: kind `doing`, no date, not past due, whatever the old time said",
      bd9.item("a42")["_wait"]["wait"] == "doing" and not bd9.item("a42")["_wait"]["overdue"] and bd9.item("a42")["_wait"]["expected_by"] == 0.0, bd9.item("a42")["_wait"])
check("board.md has no stuck word at all: no Stuck section, no ladder line, whatever the item's state", not re.search("stuck", md9, re.I), [m for m in md9.split("\n") if re.search("stuck", m, re.I)][:5])
check("the brief has no stuck count and no stuck line", not re.search("stuck", br9, re.I), [m for m in br9.split("\n") if re.search("stuck", m, re.I)][:5])
g_a = server.stackshot_get("a45")
check("an item carrying an old ladder record at step 3 reads as any late hold: no step line, no stuck mark in get, and a waiting line", not re.search(r"step \d of \d|stuck", g_a) and "waiting: " in g_a and "past due" in g_a, g_a)
st_9, ct_9, body_9 = server._client_get("items", {"key": U["home-owner"]})
items9 = {i["gid"]: i for i in json.loads(body_9)["items"]}
check("the items API carries no step on any item, the one with the old record included", items9 and not any("step" in i for i in items9.values()) and items9["a45"]["overdue"], list(items9.get("a45", {})))
check("the old waiting.json was read and not rewritten by any of that (the get, the board, the brief, the items API)", ST.read_text() == raw_old, ST.read_text()[:300])
st_old = W.load_state()
check("…it is read for its baseline and first-seen dates only: the ladder's `reported` list is not loaded", st_old["baseline"] == OLD["baseline"] and st_old["seen"] == OLD["seen"] and "reported" not in st_old, st_old)
check("…and the floor from it is the baseline plus default_days", abs(W.floor_of(st_old, now0) - (OLD["baseline"] + 3 * DAY)) < 1, W.floor_of(st_old, now0))
import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": waiting scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
