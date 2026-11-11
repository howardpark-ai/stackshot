"""Scenario test for the one rule for waiting items: whose move it is, and no computed date. Fixture data, no live store, no network.

Every open item has a MOVER (the one party whose move it is now, `waiting.mover_for`). No "expected by" time is computed for any item and a parked
item (on hold, or after an open item) carries no stale mark: it is held until its own wake or its blocker's close, and a wake that passed or a
check that failed is caught by the passes that read the item's own fields (the wake pass, the dates pass, the failed-check notice, the
wait-end audit: their own suites). The items API keeps `expected_by`, `wait` and `overdue` as keys, always empty (null, "", null), so that a
reader written against them does not break. Nothing escalates a late item: the ladder that once did is gone, and so are its records.

Covers: the mover for every wait (a plain item, needs decision / external / a session, a wake, a hold with a wake, a hold waiting for a pane
recycle, `after` taking the mover of its first open blocker, a loop safe, a failed wait keeping the item's own mover); no compute, floor,
jitter, wait-state or ladder code is left, and a config file that still has the old keys loads; a parked item is held, never stale; a late item gets
no notice and no record; the cap on a wake a session sets ([waiting] cap_days, cap_needs_owner, a checked said entry, a board answer, the
anchored backstop; a due date is a deadline and is accepted as it is); after=[] / "none" / clear_after=true clear the list, through the MCP
layer too; a failed notice delivery is recorded on the item; a due date at the end of time is no date and one bad item stops no read; a change
to what an item waits on drops a failed wait and an old ladder record; the surfaces (get, the items API, the item page, board.md, the brief)
print no expected-by time and no `waiting:` line, and an old waiting.json is ignored and never rewritten.

    tests/run-suite waiting        → exit 0 / 1"""
import asyncio, json, os, re, sys, pathlib, tempfile, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="waitingtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
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
        meta = {("post_wake_mover" if (hd_(meta) or meta.get("after") or meta.get("recycle")) else "mover"): owner or U["home-owner"], **meta}
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
from stackshot.web import server; from stackshot.waits import waiting as W
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
from stackshot.web.ui import render as ui_render
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
told = []
real_tell = server._tell_woken
server._tell_woken = lambda gid, owner, note, tag="wake": told.append((tag, gid, owner, note))
def wk(offset):                                     # a wake as a session writes it, minute resolution, in the instance timezone
    return time.strftime("%Y-%m-%dT%H:%M", time.gmtime(now0 + offset + ZONE_OFFSET))

# ---- 1. whose move it is (waiting.mover_for): no date is computed for any wait
def M(i):
    def load(g):
        p = T / f"store/a/{g[1:]}.json"
        return json.loads(p.read_text()) if p.exists() else None
    return W.mover_for({**rd(i), "gid": f"a{i}"}, load)
item(1)                                                                       # a plain on-agent item
check("a plain item: the stored mover's move", M(1) == {"kind": "session", "who": U["home-owner"]}, M(1))
item(2, needs=["decision"], ask="Decide: x · Recommend: y · Stakes: z · By: no date", su=now0 - 1 * DAY)
check("needs decision: Oliver's move", M(2) == {"kind": "owner", "who": server.OWNER}, M(2))
item(3, needs=["external"], su=now0 - 4 * DAY)
check("needs external: an outside party's move, however long ago it was set", M(3)["kind"] == "outside", M(3))
item(4, needs=["team-back"], su=now0 - 1 * DAY)
check("needs naming a session: that session's move", M(4) == {"kind": "session", "who": "team-back"}, M(4))
item(5, wake=wk(2 * DAY), su=now0 - 1 * DAY)
check("a wake alone (a reminder, no hold): the owner's move", M(5) == {"kind": "session", "who": U["home-owner"]}, M(5))
item(6, hold=True, wake=wk(-3600), su=now0 - 1 * DAY)
check("a hold with a wake that has passed: the same mover, nothing else is said of it", M(6)["who"] == U["home-owner"] and "via" not in M(6), M(6))
item(9, hold=True, recycle=True, recycle_at=now0 - 2 * DAY, su=now0 - 2 * DAY)
check("a hold waiting for a pane recycle: the fleet tool's move", M(9) == {"kind": "outside", "who": "the fleet tool (pane recycle)"}, M(9))
server._cfg.CFG.setdefault("fleet", {})["tool_name"] = "sala"; m_named = M(9); server._cfg.CFG["fleet"]["tool_name"] = ""
check("…and with [fleet] tool_name set the mover is named by it", m_named == {"kind": "outside", "who": "sala (pane recycle)"}, m_named)
item(10, hold=True, recycle=True, wake=wk(DAY), su=now0 - 2 * DAY)
check("…a recycle hold that has a wake of its own keeps the item's mover", M(10)["kind"] == "session", M(10))
item(11, hold=True, wake=wk(DAY), after=["a14", "a12", "a13"], su=now0 - 1 * DAY)
item(12, owner=U["team-back"], wake=wk(3 * DAY), su=now0 - DAY); item(13, owner=U["home-other"], wake=wk(5 * DAY), su=now0 - DAY); item(14, status="completed", outcome="done")
check("after several blockers: the first open one in the item's list names the mover (via it); a closed one is skipped",
      M(11) == {"kind": "session", "who": U["team-back"], "via": "a12"}, M(11))
item(15, after=["a16"]); item(16, after=["a15"])
check("a loop of afters does not hang: it ends on a session's move", M(15)["kind"] == "session", M(15))
item(17, wait_failed={"what": "check pr_merged o/r#2", "why": "its pull request was closed without being merged", "at": now0 - 3600}, after=["a12"], su=now0 - 1 * DAY)
check("a failed wait keeps the item's own mover, whatever it was waiting after", M(17) == {"kind": "session", "who": U["home-owner"]}, M(17))
item(18, owner=U["home-gone"], hold=True, wake=wk(5 * DAY), su=now0 - 1 * DAY)
check("a mover that cannot move is named as it is stored: nothing reads it as down", M(18)["who"] == U["home-gone"], M(18))
gone = [n for n in ("compute", "_compute", "fallback", "default_days", "agent_hours", "expected_parse", "agent_clock", "last_write", "end_epoch", "state_path", "load_state", "save_state",
                    "floor_of", "jitter", "_idle_hours", "_lane_wait", "who_words", "why_words", "line", "age_words", "AFTER_DOING_SECONDS", "DAY") if hasattr(W, n)]
check("waiting.py computes no date: compute, the rollout floor and jitter, the wait's clocks, its record file and its words are gone", not gone, gone)
gone_s = [n for n in ("_waiting_of", "_capped_note", "_due_cap_words", "_retire_afters", "RETIRE_EB_SLOP") if hasattr(server, n)]
check("…nor does the server keep a wait reader, the capped note or the retire pass's wait reading", not gone_s, gone_s)
check("the [waiting] defaults hold only what is still read: the cap, the basis weekday and the dated-wait minimum", set(W.DEFAULTS) == {"cap_days", "cap_needs_owner", "basis_weekday", "dated_wait_min_hours"}, sorted(W.DEFAULTS))
g2 = server.stackshot_get("a2"); b0 = server.stackshot_brief()
check("get and the brief print no `waiting:` line and no expected-by time, however old the item", "waiting:" not in g2 and "expected" not in g2.lower() and "waiting:" not in b0 and "past due" not in g2, g2)
for i in range(1, 20): (T / f"store/a/{i}.json").unlink(missing_ok=True)

# ---- 2. no ladder: an item past its expected-by is shown (get, the board) and nothing else happens; no tick, no step, no record
import inspect
for i in range(1, 20): (T / f"store/a/{i}.json").unlink(missing_ok=True)
LATE = 30
item(LATE, hold=True, wake=wk(-3600), su=now0 - 1 * DAY)
g30 = server.stackshot_get(f"a{LATE}")
check("get shows a hold ten minutes past its wake as it is: no waiting line, no past-due mark, no step of a ladder and no stuck mark", "waiting: " not in g30 and "past due" not in g30 and not re.search(r"step \d of \d|\(stuck\)|stuck list", g30), g30)
check("no waiting tick is left: it is not on the runner's table, and the server has no function of that name nor of its plan, send or record",
      not any("waiting" in t.name for t in server._minute_ticks()) and not any(hasattr(server, n) for n in ("_waiting_tick", "_wait_plan", "_wait_record", "_wait_raise", "_wait_text", "_wait_options", "_wait_recipient", "_wait_hint", "_waiting_counts", "_WAIT_LAST", "_DOWN_SINCE")),
      [n for n in dir(server) if "wait" in n.lower()][:30])
check("waiting.py has no ladder: no steps, no landings, no grace, no record check", not any(hasattr(W, n) for n in ("STEPS", "LANDINGS", "grace_hours", "agent_grace_hours", "stuck_to", "grace_for", "start_of", "step_due", "record_of", "record_valid", "stuck_step")),
      [n for n in dir(W) if not n.startswith("_")])
check("the ladder's config keys are gone from the [waiting] defaults", not {"grace_hours", "agent_grace_hours", "stuck_to"} & set(W.DEFAULTS) and "grace_hours" not in toml and "agent_grace_hours" not in toml, sorted(W.DEFAULTS))
told.clear()
server._update(f"a{LATE}", next="home-owner: moved on", sender="home-owner")
check("a state change on a late item sends the server's ordinary notices only: none of tag 'wait', and it writes no record under `waiting`", not [t for t in told if t[0] == "wait"] and "waiting" not in rd(LATE)["metadata"], (told, rd(LATE)["metadata"]))

# ---- 4. a close of an `after` item (no failed wait: the item is released, or still waits on the others), a mover that is down
for i in range(30, 60): (T / f"store/a/{i}.json").unlink(missing_ok=True)
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
check("a prerequisite dropped while another still stands: the wait goes on, on the one left; nothing failed, nobody is told", m63.get("after") == ["a65"] and "wait_failed" not in m63 and hd_(m63) is True and not [t for t in told if t[1] == "a63"], (m63, told))
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
check("a wake within the cap (6 days) is accepted", wk_(rd(70)["metadata"]) == day(6), rd(70)["metadata"])
refused("a wake past the cap (8 days) is refused, naming the cap, the config key, and the ways to his words: ask him to answer on the item (first), or a checked said entry",
        lambda: server._update("a70", wake=day(8), sender="home-owner"), "at most 7 days", "[waiting] cap_days", "said=", "to answer on the item")
check("…the refusal left the wake as it was", wk_(rd(70)["metadata"]) == day(6), rd(70)["metadata"])
refused("a hold with a far wake is refused the same way", lambda: server._update("a70", hold=True, wake=day(20), sender="home-owner"), "at most 7 days")
server._cfg.CFG["waiting"]["cap_days"] = 10
server._update("a70", wake=day(9), sender="home-owner")
check("[waiting] cap_days is a config value, read at use", wk_(rd(70)["metadata"]) == day(9), rd(70)["metadata"])
server._cfg.CFG["waiting"]["cap_days"] = 7
server._cfg.CFG["waiting"]["cap_needs_owner"] = False
server._update("a70", wake=day(20), sender="home-owner")
check("cap_needs_owner = false: a longer wake is allowed", wk_(rd(70)["metadata"]) == day(20), rd(70)["metadata"])
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
check("a longer wake with his words behind it (an Acked-by entry checked against the transcript) is accepted", wk_(rd(70)["metadata"]) == day(10) and rd(70)["metadata"]["said"][-1]["checked"] is True, rd(70)["metadata"])
server._update("a70", wake="none", sender="home-owner")
refused("an unchecked said entry (a session whose transcript this box cannot read) is not enough for a long wake",
        lambda: server._update("a70", wake=day(10), sender="home-owner", said=[{"tag": "Acked-by", "quote": "park it", "msg": "11111111-1111-4111-8111-000000000009", "session": "cse_0123456789abcdef"}]), "at most 7 days")
refused("a said entry that is checked but not tagged Acked-by (Suggested-by) is not his word for a long wait",
        lambda: server._update("a70", wake=day(10), sender="home-owner", said=[{"tag": "Suggested-by", "quote": "keep it on hold for ten days", "msg": "11111111-1111-4111-8111-000000000001"}]), "at most 7 days")
refused("a checked Acked-by entry for a message older than cap_days is not enough either (his words from a month ago)",
        lambda: server._update("a70", wake=day(10), sender="home-owner", said=[{"tag": "Acked-by", "quote": "park it until the end of the month", "msg": "11111111-1111-4111-8111-000000000003"}]), "at most 7 days")
item(71, su=now0 - DAY, answers=[{"ts": now0 - 3600, "kind": "decision", "text": "wait until after the 30th", "via": "board"}])
server._update("a71", wake=day(12), sender="home-owner")
check("his board answer on the item, given since its last state change, is enough", wk_(rd(71)["metadata"]) == day(12), rd(71)["metadata"])
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
check("…as it is: the reply says nothing of a cap or an expected-by, and no record of his words is kept for it", "capped" not in r75 and "expected-by" not in r75 and "cap_ok" not in rd(75)["metadata"], r75)
out = server._create(subject="[home] far due", description=DESC, project="projects/alpha", owner="home-owner", next="home-owner: x", due=day(30))
check("…and on create", out.startswith("created ") and "capped" not in out and "expected-by" not in out, out)
told.clear()
server._update("a75", next="home-owner: moved on", sender="home-owner")
check("a move leaves the due date as it was", rd(75)["metadata"].get("due") == day(20), rd(75)["metadata"])
item(77, su=now0 - DAY)
server._update("a77", wake=day(10), sender="home-owner", said=[{"tag": "Acked-by", "quote": "keep it on hold for ten days", "msg": "11111111-1111-4111-8111-000000000001"}])
m77 = rd(77)["metadata"]
check("a wake past the cap accepted on his words records them (cap_ok)", m77.get("cap_ok", {}).get("wake") == day(10) and m77["cap_ok"]["by"] == "a checked said entry" and W.words_of(m77), m77)
server._update("a77", wake=day(3), sender="home-owner")
check("a new wake within the cap drops the record of his words", "cap_ok" not in rd(77)["metadata"], rd(77)["metadata"])
item(78, su=now0 - DAY, wake=day(10), cap_ok={"wake": day(11), "by": "a board answer"}, hold=True)
check("words recorded for another wake do not cover this one", not W.words_of(rd(78)["metadata"]), rd(78)["metadata"])


# ---- 5b. the records of his words behind a wake: kept for that wake, dropped when it changes or goes, and the texts that teach the cap
item(29, su=now0 - DAY, due=day(20), wake=day(10), hold=True, cap_ok={"wake": day(10), "by": "a board answer", "due": day(20), "due_by": "a board answer"})
server._update("a29", due=day(22), sender="home-owner")
co = rd(29)["metadata"].get("cap_ok") or {}
check("…changing the due leaves the wake's record (no record is kept for a due date any more)", wk_(co) == day(10), rd(29)["metadata"])
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

fleet_gone(False)
cr = ""
async def create_desc():
    async with Client(server.mcp) as c:
        return next((x.description or "" for x in await c.list_tools() if x.name == "create"), "")
from fastmcp import Client
cr = asyncio.run(create_desc())
check("create's description carries the cap sentence", server._CAP_FORM.strip() in cr and "7 days" in cr and "accepted as it is" in cr, cr[-400:])
check("the update description carries the rule, the cap and clear_after, and no ladder and no timed-in-days wait: the other texts keep their form", all(x in server._WAIT_FORM for x in ("real dates only", "7 days", "clear_after=true")) and not re.search(r"stuck list|ladder|timed in days", server._WAIT_FORM), server._WAIT_FORM)
_gd = asyncio.run(server.mcp.get_tool("get")).description if hasattr(server.mcp, "get_tool") else ""
_bd = asyncio.run(server.mcp.get_tool("brief")).description if hasattr(server.mcp, "get_tool") else ""
check("get and brief no longer describe a `waiting:` line or an expected-by, and teach no ladder, step or stuck list",
      all("`waiting:`" not in d and "expected-by" not in d and "expected by" not in d and not re.search(r"ladder|stuck list|step \d of|grace", d) for d in (_gd, _bd)) and _gd and _bd, (_gd[:80], _bd[:80]))


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
check("through the MCP layer: update takes clear_after (a boolean) and clears the list, and its description names the rule", "clear_after" in props and props["clear_after"].get("type") == "boolean" and "after" not in rd(80)["metadata"] and "real dates only" in desc, (list(props), rd(80)["metadata"]))

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

# ---- 7d. recording a failed delivery is written under the item lock
for i in range(85, 400): (T / f"store/a/{i}.json").unlink(missing_ok=True)
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
check("an item with such a due date reads as any item: get shows it, the items API lists it and the board builds", "item 89" in server.stackshot_get("a89"), server.stackshot_get("a89")[:200])
bad = {"id": "9", "subject": "[home] bad", "status": "open", "metadata": 5, "state_updated": "garbage"}
check("a stored value that makes the mover reading raise gives that row no mover fields and fails no list: the reading is guarded", server._wait_fields("a9", bad, server._WaitCtx(now0)) == {}, server._wait_fields("a9", bad, server._WaitCtx(now0)))
check("the board builds with the item of such a due date on it, and shows it", "a89" in ui_render.Board(f"{tmp}/store").markdown(), None)

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

# ---- 8. the surfaces: the items API, the item page, board.md, the brief; a parked item is held, never stale
for i in range(30, 400): (T / f"store/a/{i}.json").unlink(missing_ok=True)
late = wk(-3600)
item(82, hold=True, wake=late, su=now0 - DAY)                                 # a hold past its wake
item(26, hold=True, wake=wk(2 * DAY), su=now0 - DAY)                         # parked, inside its date
item(27, su=now0 - DAY, undelivered=[{"to": "home-stew", "tag": "wait", "at": now0 - 60, "why": "no pane"}])
item(28, hold=True, su=now0 - DAY)                                           # no date of its own
bd = ui_render.Board(f"{tmp}/store")
r_old = bd.item("a82")
check("the renderer computes no wait for any item: no `_wait` on a row", all("_wait" not in bd.item(g) for g in ("a82", "a26", "a27", "a28")), sorted(r_old))
check("a parked item is held, never stale: past its wake, inside it, or with no date of its own (the wake pass and the dates pass are what notice a wake that passed)",
      all(bd.item(g)["_fresh"] == "held" for g in ("a82", "a26", "a28")), [(g, bd.item(g)["_fresh"]) for g in ("a82", "a26", "a28")])
check("the board has no stuck list and no list of undated waits: the undelivered notice is still listed", not hasattr(bd, "stuck") and not hasattr(bd, "nodate") and [r["gid"] for r in bd.undelivered] == ["a27"], [r["gid"] for r in bd.undelivered])
md = bd.markdown()
check("board.md has no Stuck section and no undated waits: its head lists the undelivered notices (before Machines)",
      "## Stuck" not in md and "## Undelivered notices" in md and md.index("## Undelivered notices") < md.index("## Machines") and "no date of their own" not in md and "undated" not in md, md[md.find("## Undel"):md.find("## Machines")][:600])
br = bd.brief()
check("the brief carries an undelivered count and no stuck count, no stuck line and no line of undated waits", "1 with an undelivered notice" in br and not re.search(r"\d+ stuck|^  stuck: |more stuck|no date of their own|undated", br, re.M), br)
ph = bd.item_html("a82")
check("the item page has no Expected by row in its sidebar and prints no computed date or 'past due by' (a held item past its wake, and one inside its date)", "Expected by" not in ph and "past due by" not in ph and "Expected by" not in bd.item_html("a26"), re.findall(r"Expected by.{0,300}", ph))
st_, ct_, body_ = server._client_get("items", {"key": U["home-owner"]})
x = {i["gid"]: i for i in json.loads(body_)["items"]}
check("the items API (the web board and sala read it) carries the mover of a held item and no ladder step; expected_by, wait and overdue stay as keys and are always empty",
      x["a82"]["held"] and "step" not in x["a82"] and x["a82"]["mover"]["kind"] == "session" and all(v["expected_by"] is None and v["wait"] == "" and v["overdue"] is None for v in x.values()) and len(x) >= 3, x.get("a82"))
from starlette.testclient import TestClient
with TestClient(server.mcp.http_app()) as _tc:
    _r = _tc.get("/audit/status")
check("the audit status carries no waiting counts: GET /audit/status answers the audit's own status and no `waiting` key", _r.status_code == 200 and "waiting" not in _r.json() and set(_r.json()) == set(server._audit.status()) | {"runner", "phase_sweep", "card"}, (_r.status_code, _r.text[:200]))      # the audit's own keys, the minute set's runner record (runner.py), the phase sweep's counters and the audit shortlist the side panel polls (card); never a waiting one

# a session mover stored as a transcript id never reaches a page or the board as the id
_own = U["home-owner"]
check("the stored mover of a82 is the owner's transcript id (the premise of the next checks)", W.mover_for({**rd(82), "gid": "a82"})["who"] == _own and len(_own) >= 32, rd(82)["metadata"])
check("item page: the page never prints the mover's transcript id", _own not in ph, ph[:400])
check("board.md carries no row for the ladder's last step: the mover of a past-due hold is named on its own row, not its id",
      "## Stuck" not in md and "(the ladder's last step" not in md, md[:300])
check("the brief has no stuck line for it either, and no id of the mover", "  stuck: a82" not in br and _own not in br, br)
check("the stale tip of a stale item prints no date and no past-due mark", "past due" not in ui_render.stale_tip(r_old, bd.mover_name) and "expected by" not in ui_render.stale_tip(r_old, bd.mover_name), ui_render.stale_tip(r_old, bd.mover_name))
check("get shows a held item with no waiting line", "waiting:" not in server.stackshot_get("a82"), server.stackshot_get("a82"))
check("an id that resolves to no session stays the raw id", bd.mover_name("deadbeef-0000-4000-8000-000000000000") == "deadbeef-0000-4000-8000-000000000000")

# ---- 9. what is gone: an old waiting.json is never read or rewritten, and a store with an item in every state shows no ladder stuck line and no expected time
for i in range(30, 400): (T / f"store/a/{i}.json").unlink(missing_ok=True)
hrs = lambda n: time.strftime("%Y-%m-%d %H:%M", time.gmtime(now0 + n * 3600 + ZONE_OFFSET))
ST = T / "state/waiting.json"; ST.parent.mkdir(parents=True, exist_ok=True)
OLD = "{ this is not json: an old waiting.json of any shape is never read"
ST.write_text(OLD); raw_old = ST.read_text()
item(30, su=now0 - 5 * DAY)                                                                                # a plain on-agent item, idle for days
item(31, needs=["decision"], ask="Decide: x · Recommend: y · Stakes: z · By: no date", su=now0 - 5 * DAY)   # Oliver's call
item(32, needs=["external"], su=now0 - 9 * DAY)                                                            # an outside party, long ago
item(33, needs=["team-back"], su=now0 - 2 * DAY)                                                           # a session named in needs
item(34, hold=True, wake=wk(-3600), su=now0 - DAY)                                                         # a hold past its wake
item(35, hold=True, su=now0 - 20 * DAY)                                                                    # a hold with no date of its own
item(36, hold=True, wake=wk(3 * DAY), after=["a37"], su=now0 - DAY); item(37, wake=wk(2 * DAY), su=now0 - DAY)   # after a blocker
item(38, due=day(-4), su=now0 - 6 * DAY)                                                                   # a due date that passed
item(39, check="pr_merged o/r#9", su=now0 - 9 * DAY)                                                       # a check, long since set
item(40, wait_failed={"what": "check pr_merged o/r#2", "why": "its pull request was closed without being merged", "at": now0 - 3600}, su=now0 - DAY)
item(41, su=now0 - DAY, undelivered=[{"to": "home-stew", "tag": "wait", "at": now0 - 60, "why": "no pane"}])
item(42, needs=["team-back"], state="doing", expected_by=hrs(-5), su=now0 - DAY)                           # a doing item stored with a time that has long passed: the time is ignored
item(43, needs=["team-back"], state="verifying", proof="the link opens", end=day(-5), su=now0 - 9 * DAY)  # a verifying item past its end
item(44, status="completed", outcome="done")
item(45, hold=True, wake=wk(-3600), su=now0 - 5 * DAY, waiting={"since": now0 - 5 * DAY, "eb": now0 - 3600, "step": 3, "at": {"1": now0 - 9e4, "2": now0 - 5e4, "3": now0 - 4e3}})   # a record the ladder wrote, at its last step
item(46, owner=U["home-front"], needs=["external"], su=now0 - 9 * DAY)                                      # a front agent's outside wait
bd9 = ui_render.Board(f"{tmp}/store"); md9 = bd9.markdown(); br9 = bd9.brief()
check("the board builds with an item of every state and none of them reads stale only because it is parked: a held item is held",
      all(bd9.item(f"a{i}")["_fresh"] == "held" for i in (34, 35, 36)), [(i, bd9.item(f"a{i}")["_fresh"]) for i in (34, 35, 36)])
check("…a verifying item waiting on its end day, past it or not, is held too, and a doing item stored with a long-passed time reads as any doing item", bd9.item("a43")["_fresh"] == "held" and bd9.item("a42")["_fresh"] != "held", (bd9.item("a43")["_fresh"], bd9.item("a42")["_fresh"]))
check("board.md has no stuck word at all: no Stuck section, no ladder line, whatever the item's state", not re.search("stuck", md9, re.I), [m for m in md9.split("\n") if re.search("stuck", m, re.I)][:5])
check("the brief has no stuck count and no stuck line", not re.search("stuck", br9, re.I), [m for m in br9.split("\n") if re.search("stuck", m, re.I)][:5])
g_a = server.stackshot_get("a45")
check("an item carrying an old ladder record at step 3 reads as any late hold: no step line, no stuck mark in get, no waiting line and no past-due mark", not re.search(r"step \d of \d|stuck", g_a) and "waiting: " not in g_a and "past due" not in g_a, g_a)
st_9, ct_9, body_9 = server._client_get("items", {"key": U["home-owner"]})
items9 = {i["gid"]: i for i in json.loads(body_9)["items"]}
check("the items API carries no step on any item, the one with the old record included, and no expected time on any", items9 and not any("step" in i for i in items9.values()) and all(i["expected_by"] is None and i["overdue"] is None and i["wait"] == "" for i in items9.values()) and "a45" in items9, list(items9.get("a45", {})))
check("the old waiting.json was neither read nor rewritten by any of that (the get, the board, the brief, the items API): it still holds what it held", ST.read_text() == raw_old, ST.read_text()[:300])

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": waiting scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
