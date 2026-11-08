"""Scenario test for liveness.py — one clock and one answer for "is this session or machine up, unreachable, idle-live" — fixture data, no live store, no network.

liveness.py replaced the separate readings in clients.py (is a puller online, is a hook-registered session past its TTL, is a gone record past the horizon), fleet.py (running,
gone for how long, present within the grace, dead after how long), server.py (_idle_live, _machine_unreachable, _session_down, _pane_dead), mover_state.py (what a pane's
registry row says, how long it has been idle), stall.py (the idle test) and the two inbox readers (push.inbox_serves, inbox.alive / inbox._present). It is a pure consolidation:
this suite holds a frozen copy of each old reader (the code as it stood before) and asserts, over a table of cases per reader, that the old copy and the live name give the same
answer: a session that runs, is gone a second, ten minutes, an hour, a month, or on a stamp nobody can read; a machine online, silent, silent for exactly the grace, never
vouched for, or not in the view at all; a server that started a minute or two hours ago; a pane that is busy, idle, in a shell, headless, or whose process is gone. It also
pins a few answers as literals (the thresholds at their edges), and checks that the old names (fleet.running, clients.online, mover_state.is_idle …) are the very functions in
liveness.py. Where two readers give different answers on the same row they are kept apart by the name of the window each reads (grace, dead_after): the table has those rows
and pins both.

    tests/run-suite liveness        → exit 0 / 1"""
import json, os, re, subprocess, sys, pathlib, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="livenesstest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts (the stopped check reads them)
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "fleet/b", "fleet/c", "fleet/d", "fleet/e", "fleet/g", "state/anchor-hub", "brain/projects", "transcripts", "cli"): (T / d).mkdir(parents=True)
(T / "store/projects.json").write_text(json.dumps({"pages": {}}))
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

from stackshot.core import config as cfg; from stackshot.fleet import fleet; from stackshot.fleet import clients; from stackshot.waits import mover_state; from stackshot.waits import stall; from stackshot.fleet import inbox; from stackshot.fleet import push; from stackshot.fleet import liveness as LV; from stackshot.web import server
NOW = float(int(time.time()))        # whole seconds: the stamps below are second-granular, so an edge case lands exactly on the edge
iso = lambda delta: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - delta))
UU = lambda n: f"{n:08d}-0000-4000-8000-000000000000"
def setcfg(**kw):
    for k, v in kw.items(): server._cfg.CFG.setdefault("client", {})[k] = v

# ================================================================= the old readers, frozen (the code as it stood before liveness.py), one block per file
import datetime as dt
from pathlib import Path
def o_ts(iso_):                                                   # fleet._ts and clients._ts
    try: return dt.datetime.fromisoformat(str(iso_).replace("Z", "+00:00")).timestamp()
    except Exception: return 0.0
o_grace = lambda: 60.0 * float(cfg.get("client", "online_minutes") or 10)                       # fleet._grace, clients._online, clients._grace
o_dead_after = lambda: max(o_grace(), 60.0 * float(cfg.get("client", "dead_after_minutes") or 60))
o_ttl = lambda: 3600.0 * float(cfg.get("client", "session_ttl_hours") or 12)
o_horizon = lambda: 86400.0 * float(cfg.get("client", "session_horizon_days") or 30)
def o_running(row): return isinstance(row, dict) and not row.get("gone")
def o_gone_for(row, now=None):
    if not isinstance(row, dict) or not row.get("gone"): return 0.0
    t = o_ts(row["gone"]); return float("inf") if not t else max(0.0, (time.time() if now is None else now) - t)
def o_present(row, now=None): return isinstance(row, dict) and o_gone_for(row, now) <= o_grace()
def o_online(m, now=None): return bool(m.get("puller")) and (time.time() if now is None else now) - o_ts(m["puller"]) <= o_grace()      # clients.online
o_reported_lately = lambda seen, now: now - o_ts(seen) <= o_grace()                                # clients._upsert's claim guard
o_hook_expired = lambda seen, now: now - o_ts(seen) > o_ttl()                                       # clients._expire
o_past_horizon = lambda gone, now: now - o_ts(gone) > o_horizon()                                   # clients._expire
def o_idle_live(who, nm, idx):                                                                      # server._idle_live
    sid = server._anc.canonical(who, nm); rec = idx.get(sid.lower()) or idx.get(sid)
    return bool(rec) and o_running(rec)
def o_machine_unreachable(letter, started, now=None):                                               # server._machine_unreachable (started = server._STARTED)
    on = fleet.read(str(letter or ""), "machine").get("online") if letter else None
    if not (isinstance(on, dict) and on.get("ok") is False): return ""
    now = time.time() if now is None else now
    basis = max(o_ts(on.get("since")), started)
    return "its machine's puller is not checking in" if now - basis >= o_grace() else ""
def o_session_down(who, nm, idx, stuck, started, now=None):                                         # server._session_down
    sid = server._anc.canonical(who, nm); rec = idx.get(sid.lower()) or idx.get(sid)
    if not isinstance(rec, dict) or not rec: return ""
    if o_running(rec):
        why = stuck(sid) if stuck is not None else server._pane_stuck(sid, nm, idx)
        if why: return f"is stopped on an error ({why})"
        off = o_machine_unreachable(rec.get("machine"), started, now)
        return f"is unreachable ({off})" if off else ""
    return "" if o_present(rec) else "is not running (its pane is gone)"
def o_pane_dead(rec, now=None):                                                                     # server._pane_dead
    gone = o_gone_for(rec, now)
    if gone < o_dead_after(): return ""
    on = fleet.read(str((rec or {}).get("machine") or ""), "machine").get("online")
    if not (isinstance(on, dict) and on.get("ok") is True): return ""
    return f"its pane has been gone for {'a time not known' if gone == float('inf') else str(int(gone // 60)) + ' min'} while its machine is online"
def o_pane_row(names, ids, sessions_dir):                                                           # mover_state.pane_row
    names, ids = {n for n in names if n}, {i for i in ids if i}
    best = None
    try: files = list(Path(sessions_dir).glob("*.json"))
    except OSError: return None
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            if r.get("kind") != "interactive": continue
            if not (r.get("sessionId") in ids or r.get("name") in names): continue
            os.kill(int(r.get("pid")), 0)
            at = float(r.get("statusUpdatedAt") or r.get("updatedAt") or 0) / 1000.0
            if best is None or at > best[0]: best = (at, r)
        except Exception: continue
    return best
o_status = lambda best: (str(best[1].get("status") or ""), best[0]) if best else ("", 0.0)
o_is_idle = lambda st, at: st in ("idle", "shell") and bool(at)
def o_idle_since(st, at, *floors):
    if not o_is_idle(st, at): return 0.0
    return max(float(at), *(float(f or 0) for f in floors))
def o_idle_seconds(st, at, now, *floors):
    s = o_idle_since(st, at, *floors); return max(0.0, now - s) if s else 0.0
def o_online_ok(machine_json): return bool((machine_json.get("online") or {}).get("ok"))           # push.inbox_serves / inbox.alive, inline before
def o_inbox_serves(name):                                                                           # push.inbox_serves
    try:
        for L in fleet.letters():
            rows = fleet.read(L, "sessions")
            if any(o_present(v) and (u == name or v.get("name") == name) for u, v in rows.items()):
                return L != push.PUB or bool((fleet.read(L, "machine").get("online") or {}).get("ok"))
    except Exception: pass
    return False
def o_inbox_alive(it, idx):                                                                         # inbox.alive
    return any(not r.get("gone") and bool((fleet.read(str(r.get("machine") or ""), "machine").get("online") or {}).get("ok")) for _u, r in inbox._rows_for(it, idx))

# the machines of the view (machine.json): a online, b silent for a day, c silent for 5 minutes, d silent for exactly the grace, e with no `online` record, g silent since an unreadable stamp, f with no file
def machine(L, online=None, raw=None):
    p = T / "fleet" / L / "machine.json"; p.parent.mkdir(parents=True, exist_ok=True)
    body = {"letter": L, "fleet": f"box-{L}", "claude": "1.0.0"}
    if online is not None: body["online"] = online
    p.write_text(raw if raw is not None else json.dumps(body))
machine("a", {"ok": True, "since": iso(86400)})                  # online
machine("b", {"ok": False, "since": iso(86400)})                 # silent for a day
machine("c", {"ok": False, "since": iso(300)})                   # silent for 5 minutes
machine("d", {"ok": False, "since": iso(600)})                   # silent for exactly the grace
machine("e")                                                     # no `online` record: no puller vouches for it
machine("g", {"ok": False, "since": "rubbish"})                  # silent, since when unknown
(T / "fleet/f").mkdir(exist_ok=True)                             # a machine folder with no machine.json (letter f)

# ================================================================= 0. the old names are the new functions
check("alias: fleet presence names are liveness.py's", all(getattr(fleet, n) is getattr(LV, m) for n, m in
      (("running", "running"), ("gone_for", "gone_for"), ("present", "present"), ("_grace", "grace"), ("dead_after", "dead_after"), ("_ts", "ts"))))
check("alias: clients.online and clients._ts are liveness.py's", clients.online is LV.puller_online and clients._ts is LV.ts and clients._online is LV.online_window)
check("alias: mover_state's pane names are liveness.py's", all(getattr(mover_state, n) is getattr(LV, n) for n in ("pane_row", "status", "is_idle", "idle_since", "idle_seconds", "idle_for", "IDLE")))
src = lambda f: __import__("inspect").getsource(f)
check("server: the four readers are one call into liveness.py each", all(f"_lv.{call}(" in src(getattr(server, fn)) for fn, call in
      (("_idle_live", "idle_live"), ("_machine_unreachable", "machine_unreachable"), ("_session_down", "session_down"), ("_pane_dead", "pane_dead"))))
check("stall: the idle test is liveness.py's", "_lv.is_idle(" in src(stall.action) and not hasattr(stall, "_mover_state"))

# ================================================================= 1. the windows
for online, dead, ttl, hz in ((10, 60, 12, 30), (3, 60, 12, 30), (3, 2, 1, 1), (90, 60, 12, 30), (10, 0, 12, 30), (0, 0, 0, 0)):     # (0 reads as unset: the default)
    setcfg(online_minutes=online, dead_after_minutes=dead, session_ttl_hours=ttl, session_horizon_days=hz)
    check(f"windows {online}/{dead}/{ttl}/{hz}: grace, online window, dead_after, ttl and horizon match the old reads",
          (LV.grace(), LV.online_window(), LV.dead_after(), LV.session_ttl(), LV.horizon()) == (o_grace(), o_grace(), o_dead_after(), o_ttl(), o_horizon()),
          (LV.grace(), LV.online_window(), LV.dead_after(), LV.session_ttl(), LV.horizon()))
setcfg(online_minutes=10, dead_after_minutes=60, session_ttl_hours=12, session_horizon_days=30)
check("windows: defaults are 10 min, 60 min, 12 h, 30 d, and dead_after is never below the grace",
      (LV.grace(), LV.dead_after(), LV.session_ttl(), LV.horizon()) == (600.0, 3600.0, 43200.0, 2592000.0))
setcfg(online_minutes=90)
check("windows: dead_after follows a longer grace", LV.dead_after() == 5400.0); setcfg(online_minutes=10)
check("ts: an ISO stamp, a Z stamp, nothing, rubbish", LV.ts("2026-01-01T00:00:00Z") == o_ts("2026-01-01T00:00:00Z") > 0 and LV.ts(None) == LV.ts("rubbish") == LV.ts("") == 0.0)

# ================================================================= 2. presence of one session row
GONE = [0, 1, 599, 600, 601, 1800, 3599, 3600, 3601, 86400 * 40]
rows = [("running", {"name": "x"}), ("empty gone", {"gone": ""}), ("bad stamp", {"gone": "rubbish"}), ("none", None), ("list", []), ("text", "x"), ("empty dict", {})] \
       + [(f"gone {d}s", {"gone": iso(d)}) for d in GONE]
for label, r in rows:
    for now in (NOW, NOW + 30):
        got = (LV.running(r), LV.gone_for(r, now), LV.present(r, now))
        want = (o_running(r), o_gone_for(r, now), o_present(r, now))
        check(f"presence {label} @+{int(now - NOW)}: running, gone_for, present agree", got == want, (got, want))
        check(f"presence {label} @+{int(now - NOW)}: pane_dead and idle_live agree", LV.pane_dead(r, now) == o_pane_dead(r, now) and LV.idle_live(r) == (bool(r) and o_running(r)), (LV.pane_dead(r, now), o_pane_dead(r, now)))
# the same rows on a machine: pane_dead reads machine.json only when the row names one, so the rows above (no `machine`) never reach the machine-online branch. Here every dict row
# takes each machine of the view: a online (the branch that gives a reason), b silent for a day, d silent for the grace, e with no `online` record, g with an unreadable stamp, f with no file
# and z not in the view (these five never give one). The gone stamps include dead_after - 1, dead_after (the boundary second) and one past it.
MROWS = [(lab, r) for lab, r in rows if isinstance(r, dict)]
for L in "abdegfz":
    for label, r in MROWS:
        for now in (NOW, NOW + 30):
            rm = {**r, "machine": L}; got = LV.pane_dead(rm, now); want = o_pane_dead(rm, now)
            check(f"pane_dead on machine {L}, {label} @+{int(now - NOW)}: new agrees with old", got == want, (got, want))
            check(f"pane_dead on machine {L}, {label} @+{int(now - NOW)}: a reason only when gone past dead_after on a machine that is online", bool(got) == (L == "a" and o_gone_for(rm, now) >= o_dead_after()), got)
setcfg(online_minutes=90)          # dead_after follows a longer grace: 90 min, so 3600 s is no longer the boundary
for d in (3600, 5399, 5400, 5401):
    for L in "abe":
        rm = {"gone": iso(d), "machine": L}; got = LV.pane_dead(rm, NOW); want = o_pane_dead(rm, NOW)
        check(f"pane_dead at a 90 minute grace on machine {L}, gone {d}s: new agrees with old", got == want and bool(got) == (L == "a" and d >= 5400), (got, want))
setcfg(online_minutes=10)
setcfg(online_minutes=3)
check("presence at a 3 minute grace: every row agrees again", all((LV.present(r, NOW) == o_present(r, NOW), LV.pane_dead(r, NOW) == o_pane_dead(r, NOW)) == (True, True) for _l, r in rows)); setcfg(online_minutes=10)
check("literal: present at exactly the grace, not a second past it", LV.present({"gone": iso(600)}, NOW) and not LV.present({"gone": iso(601)}, NOW))
check("literal: a gone session is not a pane to message until dead_after, and then only when its machine is online",
      LV.pane_dead({"gone": iso(3599), "machine": "a"}, NOW) == "" and "gone for 60 min while its machine is online" in LV.pane_dead({"gone": iso(3600), "machine": "a"}, NOW)
      and LV.pane_dead({"gone": iso(86400), "machine": "b"}, NOW) == "" and LV.pane_dead({"gone": "rubbish", "machine": "a"}, NOW) != "" and "a time not known" in LV.pane_dead({"gone": "rubbish", "machine": "a"}, NOW))

# ================================================================= 3. machines: the puller's own record (clients), and the view (machine.json)
PUL = [("never", {}), ("empty", {"puller": ""}), ("rubbish", {"puller": "rubbish"})] + [(f"{d}s ago", {"puller": iso(d)}) for d in (0, 1, 599, 600, 601, 7200)]
for label, m in PUL:
    for now in (NOW, NOW + 20):
        check(f"puller {label} @+{int(now - NOW)}: online agrees", LV.puller_online(m, now) == o_online(m, now) and clients.online(m, now) == o_online(m, now), (LV.puller_online(m, now), o_online(m, now)))
check("literal: a puller is online at exactly the window, not past it", LV.puller_online({"puller": iso(600)}, NOW) and not LV.puller_online({"puller": iso(601)}, NOW) and not LV.puller_online({}, NOW))
for d in (0, 599, 600, 601):
    check(f"reported lately {d}s", LV.reported_lately(iso(d), NOW) == o_reported_lately(iso(d), NOW))
for d in (0, 43199, 43200, 43201, 86400 * 3):
    check(f"hook session expired after {d}s", LV.hook_session_expired(iso(d), NOW) == o_hook_expired(iso(d), NOW) and LV.hook_session_expired(iso(d), NOW) == (d > 43200))
for d in (0, 86400 * 30 - 1, 86400 * 30, 86400 * 30 + 1, 86400 * 365):
    check(f"past the horizon after {d}s", LV.past_horizon(iso(d), NOW) == o_past_horizon(iso(d), NOW) and LV.past_horizon(iso(d), NOW) == (d > 86400 * 30))
check("expiry: a missing stamp reads as long ago", LV.hook_session_expired(None, NOW) and LV.past_horizon("rubbish", NOW) and o_hook_expired(None, NOW) and o_past_horizon("rubbish", NOW))

check("view: online_ok reads online.ok as a bool", [LV.machine_online_ok(fleet.read(L, "machine")) for L in "abcdefz"] == [o_online_ok(fleet.read(L, "machine")) for L in "abcdefz"] == [True, False, False, False, False, False, False])
for started in (0.0, NOW - 60, NOW - 599, NOW - 600, NOW - 7200):
    for L in ("a", "b", "c", "d", "e", "f", "g", "z", "", None):
        for now in (NOW, NOW + 30):
            got = LV.machine_unreachable(L, now, started); want = o_machine_unreachable(L, started, now)
            check(f"unreachable {L!r} started {int(NOW - started)}s ago @+{int(now - NOW)}", got == want, (got, want))
check("literal: silent for exactly the grace is unreachable, five minutes is not, online and unknown never are",
      [bool(LV.machine_unreachable(L, NOW, 0.0)) for L in "abcdefg"] == [False, True, False, True, False, False, True])
check("literal: a server up for a minute calls no silent puller unreachable", not any(LV.machine_unreachable(L, NOW, NOW - 60) for L in "abcdefg"))
server._STARTED = NOW - 7200
check("server wrapper: _machine_unreachable gives the same, reading _STARTED at the call", all(server._machine_unreachable(L, NOW) == o_machine_unreachable(L, server._STARTED, NOW) for L in ("a", "b", "c", "d", "e", "f", "g", "z", "", None)))
server._STARTED = NOW - 60
check("server wrapper: …and follows _STARTED when it moves", server._machine_unreachable("b", NOW) == "" and server._machine_unreachable("b", NOW + 600) != "")

# ================================================================= 4. a session that cannot move an item (server._session_down, _idle_live) and the readers beside them
UR, UG1, UG2, UG3, UB, UD, UE, UF, UST, UX = (UU(i) for i in range(1, 11))
def sess(machine_, **kw): return {"name": f"home-{kw.pop('n', 'x')}", "machine": machine_, **kw}
idx = {UR: sess("a", n="run-online"), UG1: sess("a", n="gone-1s", gone=iso(1)), UG2: sess("a", n="gone-30m", gone=iso(1800)), UG3: sess("a", n="gone-month", gone=iso(86400 * 40)),
       UB: sess("b", n="run-silent-day"), UD: sess("d", n="run-silent-grace"), UE: sess("e", n="run-no-puller"), UF: sess("f", n="run-unknown-machine"),
       UST: sess("a", n="run-stopped", stopped="Credit balance is too low"), UX: {}}
stucks = {"unset": None, "quiet": lambda sid: "", "stopped": lambda sid: "usage limit"}
for started in (0.0, NOW - 60, NOW - 7200):
    server._STARTED = started
    for who in list(idx) + [UU(99), "cse_0123456789abcdef", ""]:
        for sn, stuck in stucks.items():
            got = server._session_down(who, {}, idx, stuck, NOW); want = o_session_down(who, {}, idx, stuck, started, NOW)
            check(f"session_down {idx.get(who, {}).get('name', who)} stuck={sn} started {int(NOW - started)}s ago", got == want, (got, want))
        check(f"idle_live {idx.get(who, {}).get('name', who)}", server._idle_live(who, {}, idx) == o_idle_live(who, {}, idx), (server._idle_live(who, {}, idx), o_idle_live(who, {}, idx)))
server._STARTED = NOW - 7200
down = lambda u, stuck="quiet": server._session_down(u, {}, idx, stucks[stuck], NOW)
check("literal: running on an online machine is up; a puller silent for a day makes it unreachable; one with no puller or no record of its machine is not unreachable",
      down(UR) == "" and down(UB).startswith("is unreachable (its machine's puller is not checking in") and down(UD).startswith("is unreachable") and down(UE) == "" and down(UF) == "")
check("literal: stopped on an error is down whatever the machine, a relaunch under way is not, a pane gone past the grace is",
      down(UR, "stopped") == "is stopped on an error (usage limit)" and down(UG1) == "" and down(UG2) == "is not running (its pane is gone)" and down(UG3) == "is not running (its pane is gone)" and down(UX) == "")
check("literal: no stuck callable reads the puller's `stopped` from the row", down(UST, "unset") == "is stopped on an error (Credit balance is too low)" and down(UR, "unset") == "")
check("literal: a cloud session or an unknown name is never down", down("cse_0123456789abcdef") == "" and down(UU(99)) == "")
# two readers on the SAME row, kept apart by the window each reads (see the module docstring): a session gone 30 minutes
r30 = idx[UG2]
check("disagreement kept: gone 30 min is not present (grace 10), is down for session_down, and is still a pane for pane_dead (dead_after 60) and for _reachable's presence test",
      not LV.present(r30, NOW) and down(UG2) != "" and LV.pane_dead(r30, NOW) == "" and server._reachable(UG2, idx) is False, (LV.present(r30, NOW), down(UG2), LV.pane_dead(r30, NOW)))
check("disagreement kept: gone a month on an online machine is dead to pane_dead, on a silent one it is not (cannot tell it from a pane that is away)",
      LV.pane_dead(idx[UG3], NOW) != "" and LV.pane_dead({**idx[UG3], "machine": "b"}, NOW) == "")

# ================================================================= 5. the readers in push.py and inbox.py
def fleet_rows(**per_machine):
    for L, r in per_machine.items(): (T / "fleet" / L / "sessions.json").write_text(json.dumps(r))
fleet_rows(a={UU(21): {"name": "pub-run", "machine": "a"}, UU(22): {"name": "pub-gone-5m", "machine": "a", "gone": iso(300)}, UU(23): {"name": "pub-gone-long", "machine": "a", "gone": iso(1800)}},
           b={UU(24): {"name": "far-run", "machine": "b"}}, c={}, d={}, e={}, g={})
names = ["pub-run", "pub-gone-5m", "pub-gone-long", "far-run", "nobody", UU(21), UU(23), UU(24)]
for a_online in (True, False):
    machine("a", {"ok": a_online, "since": iso(86400)})
    for n in names:
        check(f"push.inbox_serves {n} publisher online={a_online}", push.inbox_serves(n) == o_inbox_serves(n), (push.inbox_serves(n), o_inbox_serves(n)))
    check(f"push.inbox_serves online={a_online}: the answers (publisher's panes follow its puller, a far machine's always serve, a pane gone past the grace and nobody do not)",
          [push.inbox_serves(n) for n in ("pub-run", "pub-gone-5m", "pub-gone-long", "far-run", "nobody")] == [a_online, a_online, False, True, False])
    idx2 = {u: {**r, "machine": "a"} for u, r in {UU(21): {"name": "pub-run"}, UU(22): {"name": "pub-gone-5m", "gone": iso(300)}, UU(23): {"name": "pub-gone-long", "gone": iso(1800)}}.items()}
    idx2[UU(24)] = {"name": "far-run", "machine": "b"}; idx2[UU(25)] = {"name": "silent-run", "machine": "b"}; idx2[UU(26)] = {"name": "nopuller-run", "machine": "e"}
    machine("b", {"ok": a_online, "since": iso(86400)})
    for u in idx2:
        it = {"to": u}
        check(f"inbox.alive {idx2[u]['name']} (machines online={a_online})", inbox.alive(it, idx2) == o_inbox_alive(it, idx2), (inbox.alive(it, idx2), o_inbox_alive(it, idx2)))
    check(f"inbox._present (machines online={a_online}) is fleet.present over the index", inbox._present(idx2) == {u for u, r in idx2.items() if o_present(r)})
machine("a", {"ok": True, "since": iso(86400)}); machine("b", {"ok": False, "since": iso(86400)})

# ================================================================= 6. the CLI's registry: which row is the pane, is it idle, for how long
dead_pid = subprocess.Popen([sys.executable, "-c", "pass"]); dead_pid.wait(); DEAD = dead_pid.pid          # a process that has ended: its row says nothing
def row(i, **kw):
    r = {"kind": "interactive", "pid": os.getpid(), "sessionId": UU(i), "name": f"pane-{i}", "status": "busy", "statusUpdatedAt": int((NOW - 100) * 1000), **kw}
    (T / "cli" / f"{i}.json").write_text(json.dumps(r))
row(1, status="busy"); row(2, status="idle", statusUpdatedAt=int((NOW - 700) * 1000)); row(3, status="shell", statusUpdatedAt=int((NOW - 650) * 1000))
row(4, status="idle", kind="headless"); row(5, status="idle", pid=DEAD); row(6, status="idle", statusUpdatedAt=None, updatedAt=int((NOW - 900) * 1000))
row(7, status="idle", statusUpdatedAt=int((NOW - 800) * 1000), name="shared"); row(8, status="busy", statusUpdatedAt=int((NOW - 50) * 1000), name="shared", sessionId=UU(88))
row(9, status="", statusUpdatedAt=int((NOW - 10) * 1000)); row(10, status="idle", pid="rubbish"); row(11, status="idle", statusUpdatedAt=0, updatedAt=0)
(T / "cli/broken.json").write_text("{not json")
CLI = T / "cli"; queries = [({f"pane-{i}"}, {UU(i)}) for i in range(1, 12)] + [({"shared"}, set()), (set(), {UU(7), UU(88)}), ({"nobody"}, {UU(99)}), (set(), set()), ({""}, {""})]
for names_, ids_ in queries:
    got, want = LV.pane_row(names_, ids_, CLI), o_pane_row(names_, ids_, CLI)
    check(f"pane_row {sorted(names_) or sorted(ids_)}", got == want, (got, want))
    check(f"status/is_idle/idle_since/idle_seconds {sorted(names_) or sorted(ids_)}",
          LV.status(got) == o_status(want) and all(LV.is_idle(*LV.status(got)) == o_is_idle(*o_status(want)) and LV.idle_since(*LV.status(got), f) == o_idle_since(*o_status(want), f)
                                                 and LV.idle_seconds(*LV.status(got), NOW, f) == o_idle_seconds(*o_status(want), NOW, f) for f in (0, NOW - 3000, NOW - 600, NOW + 10)))
check("pane_row: a folder that is not there gives None", LV.pane_row({"x"}, {"y"}, T / "nowhere") is None and o_pane_row({"x"}, {"y"}, T / "nowhere") is None)
for st, at in (("idle", NOW - 700), ("shell", NOW - 700), ("busy", NOW - 700), ("", NOW - 700), ("idle", 0.0), ("idle", 0), ("other", NOW)):
    for floors in ((), (0,), (NOW - 60,), (NOW - 900, NOW - 650), (None,)):
        def both(f, *a):
            try: return f(*a)
            except Exception as e: return type(e).__name__
        check(f"idle test {st!r} at {int(NOW - at)}s floors={len(floors)}",         # (no floor at all raised a TypeError for an idle pane before, and still does: the callers always pass one)
              (LV.is_idle(st, at), both(LV.idle_since, st, at, *floors), both(LV.idle_seconds, st, at, NOW, *floors))
              == (o_is_idle(st, at), both(o_idle_since, st, at, *floors), both(o_idle_seconds, st, at, NOW, *floors)))
check("literal: idle and shell are idle, busy and unknown never are, and a floor later than the status change restarts the count",
      LV.is_idle("idle", 5.0) and LV.is_idle("shell", 5.0) and not LV.is_idle("busy", 5.0) and not LV.is_idle("", 5.0) and not LV.is_idle("idle", 0.0)
      and LV.idle_seconds("idle", NOW - 700, NOW, 0) == 700 and LV.idle_seconds("idle", NOW - 700, NOW, NOW - 100) == 100 and LV.idle_seconds("busy", NOW - 700, NOW, 0) == 0.0)
for who, floors in ((UU(2), (0,)), (UU(2), (NOW - 60,)), (UU(1), (0,)), (UU(3), (0,)), ("pane-3", (0,)), ("nobody", (0,))):
    resolve = lambda w: ({f"pane-{int(w[:8])}"} if w[:8].isdigit() else {w}, {w})
    check(f"idle_for {who[:12]}", LV.idle_for(who, CLI, NOW, *floors, resolve=resolve) == mover_state.idle_for(who, CLI, NOW, *floors, resolve=resolve)
          == (lambda st_at: (st_at[0], o_idle_seconds(st_at[0], st_at[1], NOW, *floors)))(o_status(o_pane_row(*resolve(who), CLI))))
check("stall.action: the engine's idle test gates the step (a busy pane gives nothing, an idle one past the minutes gives the first step)",
      stall.action({"step": 0}, "busy", NOW - 5000, 0.0, NOW, 10.0) == "" and stall.action({"step": 0}, "", 0.0, 0.0, NOW, 10.0) == ""
      and stall.action({"step": 0}, "idle", NOW - 5000, 0.0, NOW, 10.0) == "resend" and stall.action({"step": 0}, "shell", NOW - 5000, 0.0, NOW, 10.0) == "resend"
      and stall.action({"step": 0}, "idle", NOW - 60, 0.0, NOW, 10.0) == "")

print(("ok" if not fails else "FAILED") + f": liveness scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
os._exit(1 if fails else 0)
