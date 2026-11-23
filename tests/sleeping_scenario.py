"""Scenario test for a sleeping session's presence (liveness.sleeping, clients.sleeping_sessions, the view's `sleeping`, the sessions tool's tag, messaging and push) — fixture data, no live store, no network.

The fleet tool puts a session that has been idle for an hour to sleep: its process ends, its pane stays, and a line addressed to it wakes it. The tool marks it with a `sleeping` time on
the session's row in its link store (<[client] session_links>/<letter>/sessions.json); stackshot only reads the key. A sleeper is in no puller's poll, so it used to be marked gone after
the grace, refused a message after dead_after, and forgotten after the horizon. Covered, with the history played through the real check-in and tick:

  * the view: a sleeper is never marked gone (not at the first poll without it, not at the hook TTL, not past the horizon) and its row carries the time it went to sleep; a gone stamp left from
    before the mark was read is lifted by the next tick; when the mark goes the normal rules start from that moment (gone now, present for the grace, dead after dead_after); a poll that reports
    the session again clears it. A non-string, an empty or a blank `sleeping` is no mark: the session goes gone as any other and is forgotten at the horizon.
  * liveness: sleeping / running / gone_for / present / pane_dead / session_down / idle_live on rows, with a control row that is only gone.
  * a message: gone_why and `_dead_recipient` say nothing of a sleeper and refuse the control gone for the same time; push queues the sleeper's line like a live pane's (never readdressed) and
    readdresses the control's to its project.
  * the sessions tool: "sleeping since <time>" for a sleeper, the plain "not running now" for a pane just gone.

    tests/run-suite sleeping      → exit 0 / 1"""
import contextlib, datetime as dt, io, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="sleepingtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = ""', f'session_links = "{tmp}/links"', 1); assert f'session_links = "{tmp}/links"' in toml        # the fixture store, never the host's
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "names.tsv").write_text("host-a\tbox-a\ta\n")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/state/clients/fleet", PUSH_INBOX_WAIT="0.05", ANCHOR_PUSH_SOURCE="msg")
for k in ("STACKSHOT_URL", "CLAUDE_CODE_SESSION_ID", "ANCHOR_PUSH_FORCE"): os.environ.pop(k, None)
for d in ("store/a", "links/a", "brain/projects", "secrets", "touch", "transcripts"): (T / d).mkdir(parents=True)
sys.path.insert(0, STACK); logging.disable(logging.CRITICAL)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.fleet import clients as cl
from stackshot.fleet import fleet as fl
from stackshot.fleet import liveness as LV
from stackshot.fleet import sessions_registry as _sr
from stackshot.fleet import push
from stackshot.fleet import retired_recipient as rr
from stackshot.router import routing
from stackshot.web import server          # installs the hooks the message relay reads
from stackshot.web.tools import sessions as _wt_sessions
from stackshot.service import messaging as _messaging
from stackshot.service import telling
from stackshot.web import publish as _web_publish
from fastmcp.exceptions import ToolError
_web_publish._publish = lambda: None
check("the view is the fleet directory the readers use", cl.VIEW == fl.FLEET_DIR, (cl.VIEW, fl.FLEET_DIR))

HOST = "host-a"
NOW0 = float(int(time.time())); DAY = 86400.0; T0 = NOW0 - 40 * DAY
def uid(n): return f"0000000a-0000-4000-8000-{n:012x}"
iso = lambda ts: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
NAP, NAP2, OLD, FORGOT = uid(1), uid(2), uid(3), uid(4)                  # a sleeper, a sleeper whose gone stamp predates its mark, a session only gone for 2 hours, one gone for 40 days
BAD = {uid(5): 7, uid(6): "", uid(7): "   ", uid(8): True}               # a `sleeping` that is no mark: a number, an empty string, a blank one, a boolean
NAMES = {NAP: "work-osprey-nap", NAP2: "work-osprey-nap2", OLD: "work-osprey-old", FORGOT: "work-osprey-forgot", uid(5): "work-bad-num", uid(6): "work-bad-empty", uid(7): "work-bad-blank", uid(8): "work-bad-bool"}
def rec(u): return {"uuid": u, "name": NAMES[u], "name_source": "user"}
def links(sleepers=None, **extra):
    """the fleet tool's store: every session's row with its link, the `sleeping` time on the rows of `sleepers` ({uuid: value}); a key of NAP is written in capitals (the store's keys are lowercased on read)."""
    rows = {}
    for u, n in NAMES.items():
        r = {"name": n, "url": f"https://term.example/#s={n}", "machine": "a", "seen": "x"}
        if sleepers and u in sleepers: r["sleeping"] = sleepers[u]
        rows[u.upper() if u == NAP else u] = r
    (T / "links/a/sessions.json").write_text(json.dumps(rows))
    os.utime(T / "links/a/sessions.json", ns=(time.time_ns() + links.n * 10**9,) * 2); links.n += 1       # a new stamp each write: the reader looks again only when the file changes
links.n = 0
rd = lambda: json.loads((cl.VIEW / "a" / "sessions.json").read_text())
st = lambda: json.loads(cl.STATE.read_text())["sessions"]

# ---- 1. the history, through the real check-in and tick
# T0 (40 days ago): everything is polled; the store marks NAP and the four malformed ones. An hour on, only OLD is polled: the rest are not in the poll.
links({NAP: iso(T0 + 300), **BAD})
cl.checkin(HOST, [rec(u) for u in NAMES], now=T0)
check("everything polled: nothing is gone, and the store's one real mark is read", all(not r.get("gone") for r in rd().values()) and cl.sleeping_sessions().keys() == {NAP}, rd())
cl.checkin(HOST, [rec(OLD)], now=T0 + 3600)
v = rd()
check("an hour on, polled without it: the sleeper is not gone and its row carries the time it went to sleep, its link kept", "gone" not in v[NAP] and v[NAP]["sleeping"] == iso(T0 + 300) and v[NAP]["url"].endswith("work-osprey-nap"), v[NAP])
check("…and its record in the server's state is not gone either", "gone" not in st()[NAP], st()[NAP])
check("the session polled is not gone; every session not polled and not asleep is, with its stamp", "gone" not in v[OLD] and all(v[u]["gone"] == iso(T0 + 3600) for u in (NAP2, FORGOT, *BAD)), {u[-3:]: r.get("gone") for u, r in v.items()})
check("a `sleeping` that is a number, an empty string, a blank string or a boolean is no mark: those sessions went gone as any other, and their rows carry no `sleeping`",
      all(u not in cl.sleeping_sessions() and "sleeping" not in v[u] and v[u].get("gone") for u in BAD), {u[-3:]: (r.get("gone"), r.get("sleeping")) for u, r in v.items() if u in BAD})
check("the hub's sleeping_sessions lists only the one real mark, keyed lowercase", cl.sleeping_sessions() == {NAP: iso(T0 + 300)}, cl.sleeping_sessions())
check("liveness reads the row: NAP asleep, running, present; the ones gone are neither", LV.sleeping(v[NAP]) == iso(T0 + 300) and LV.running(v[NAP]) and LV.present(v[NAP], T0 + 3600)
      and not LV.running(v[FORGOT]) and LV.sleeping(v[FORGOT]) == "", v[NAP])
# the store marks NAP2 only now: its gone stamp (T0 + 1 h) predates the mark. A tick alone (no poll) lifts it.
links({NAP: iso(T0 + 300), NAP2: iso(T0 + 7000), **BAD})
check("before the tick: NAP2's record still carries the old gone stamp", st()[NAP2].get("gone") == iso(T0 + 3600), st()[NAP2])
cl.tick(now=T0 + 7200)
v = rd()
check("a tick after the mark appears lifts the old gone stamp from the record and the view shows the sleeper (no gone, its time)", "gone" not in st()[NAP2] and "gone" not in v[NAP2] and v[NAP2]["sleeping"] == iso(T0 + 7000), (st()[NAP2], v[NAP2]))
# the horizon: five days ago a poll comes (OLD alone); FORGOT and the malformed ones have been gone for 35 days, the two sleepers have been without a poll for 40
cl.checkin(HOST, [rec(OLD)], now=NOW0 - 5 * DAY)
check("past the horizon: the sessions gone 35 days are forgotten (record and view), the sleepers are kept, asleep, though no poll reported them for 40 days",
      all(u not in st() and u not in rd() for u in (FORGOT, *BAD)) and all(u in st() and "gone" not in rd()[u] and rd()[u].get("sleeping") for u in (NAP, NAP2)), (sorted(x[-3:] for x in st()), {u[-3:]: r.get("gone") for u, r in rd().items()}))
# the hook TTL: the machine's puller is silent for a day, a tick reads every session as quiet past the TTL (12 h): the sleepers are not marked gone for it, the polled one is
cl.tick(now=NOW0 - 4 * DAY)
check("the hook TTL: a session quiet for a day with no puller is marked gone, a sleeper is not", rd()[OLD].get("gone") and "gone" not in rd()[NAP] and "gone" not in rd()[NAP2], {u[-3:]: r.get("gone") for u, r in rd().items()})
cl.checkin(HOST, [rec(OLD)], now=NOW0 - 3 * 3600)
check("a poll that reports OLD again clears it", "gone" not in rd()[OLD], rd()[OLD])
cl.checkin(HOST, [], now=NOW0 - 2 * 3600)
check("OLD is gone from two hours ago, the sleepers are not", rd()[OLD]["gone"] == iso(NOW0 - 2 * 3600) and "gone" not in rd()[NAP] and "gone" not in rd()[NAP2], {u[-3:]: r.get("gone") for u, r in rd().items()})
cl.checkin(HOST, [], now=NOW0)
v = rd(); on = fl.read("a", "machine").get("online") or {}
check("now: the machine is online, the sleepers are present with their times, OLD is gone two hours", on.get("ok") is True and "gone" not in v[NAP] and v[OLD]["gone"] == iso(NOW0 - 2 * 3600) and v[NAP2]["sleeping"] == iso(T0 + 7000), (on, v))
check("the view's rows say the same through fleet.sessions(): a sleeper is present and not dead, OLD is neither present nor a pane", LV.present(fl.sessions()[NAP], NOW0) and LV.pane_dead(fl.sessions()[NAP], NOW0) == ""
      and not LV.present(fl.sessions()[OLD], NOW0) and LV.pane_dead(fl.sessions()[OLD], NOW0) != "", (fl.sessions()[NAP], fl.sessions()[OLD]))

# ---- 2. liveness on rows (the machine "a" is online in the view)
past = iso(NOW0 - 40 * DAY)
S = {"name": "n", "machine": "a", "sleeping": past}                                   # a sleeper
G = {"name": "n", "machine": "a", "gone": past}                                       # only gone, for the same time: the control
SG = {**G, "sleeping": past}                                                          # a stale gone stamp on a sleeper
check("sleeping(): the time of a non-empty string, stripped; any other value is no mark", LV.sleeping(S) == past and LV.sleeping({"sleeping": f" {past} "}) == past
      and all(LV.sleeping({"sleeping": x}) == "" for x in (7, 0, 1.5, True, None, "", "  ", [], {}, [past])) and LV.sleeping({}) == "" and LV.sleeping(None) == "" and LV.sleeping("x") == "")
check("running / gone_for / present: a sleeper is running, gone for no time, present (a gone stamp on it changes nothing); the control is none of them",
      LV.running(S) and LV.running(SG) and LV.gone_for(S, NOW0) == 0.0 and LV.gone_for(SG, NOW0) == 0.0 and LV.present(S, NOW0) and LV.present(SG, NOW0)
      and not LV.running(G) and LV.gone_for(G, NOW0) == 40 * DAY and not LV.present(G, NOW0))
check("a malformed mark is no mark: the row behaves as the control", all((LV.running({**G, "sleeping": x}), LV.present({**G, "sleeping": x}, NOW0), LV.pane_dead({**G, "sleeping": x}, NOW0) != "") == (False, False, True) for x in (7, "", "  ", True, None)))
check("pane_dead: a sleeper is never dead (empty), the control gone as long on an online machine is", LV.pane_dead(S, NOW0) == "" and LV.pane_dead(SG, NOW0) == "" and "gone for" in LV.pane_dead(G, NOW0), (LV.pane_dead(S, NOW0), LV.pane_dead(G, NOW0)))
stuck = lambda: "an API error"
check("session_down: a sleeper is not down (not for an old error, not for a silent machine); the control gone is, and a running pane stopped on an error is",
      LV.session_down(S, stuck, 0.0, NOW0) == "" and LV.session_down(SG, stuck, 0.0, NOW0) == "" and LV.session_down({**S, "machine": "zz"}, stuck, 0.0, NOW0) == ""
      and LV.session_down(G, stuck, 0.0, NOW0) == "is not running (its pane is gone)" and LV.session_down({"name": "n", "machine": "a"}, stuck, 0.0, NOW0).startswith("is stopped on an error"), (LV.session_down(S, stuck, 0.0, NOW0), LV.session_down(G, stuck, 0.0, NOW0)))
check("idle_live: a sleeper has no turn to count idle time from (not live), a running pane is", not LV.idle_live(S) and not LV.idle_live(SG) and LV.idle_live({"name": "n"}) and not LV.idle_live(G) and not LV.idle_live(None))
check("fleet.by_name: a sleeper's name resolves to it (as a running session's does)", fl.by_name({NAP: v[NAP], OLD: v[OLD]}, NOW0) == {"work-osprey-nap": NAP, "work-osprey-old": OLD}
      and fl.by_name({NAP: v[NAP], OLD: v[OLD]}, NOW0, present_only=True) == {"work-osprey-nap": NAP}, fl.by_name({NAP: v[NAP], OLD: v[OLD]}, NOW0, present_only=True))

# ---- 3. a message to a sleeper, and to a pane gone as long
page = lambda name, sess, **kw: {"title": name, "name": name, "org": "home", "tags": [], "type": "project", "session": sess, "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": f"https://example.invalid/{name}", **kw}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": page("Alpha", "work-osprey", role="name", agents={"work-osprey-main": "the contact", "work-osprey-old": "builds", "work-osprey-nap": "builds more"},
                                                                                    back_agents={"work-osprey-old": "builds", "work-osprey-nap": "builds more"})}}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
_sr.TTL = 0
(T / "fakepush.py").write_text("import sys\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nprint('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
HUB = pathlib.Path(push.A); HUB.mkdir(parents=True, exist_ok=True)
Q = HUB / "queue-msg"; LOG = HUB / rr.LOG_NAME
push.SRC, push.Q = "msg", str(Q)
sock_sent = []
push.resolve = lambda name: ""                  # no pane listens on a socket: every line takes the queue
push.send = lambda sock, text: sock_sent.append((sock, text)) or True
push.inbox_serves = lambda name: False
def deliver(name, text, sender):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = push.deliver(name, text, sender)
    return rc, buf.getvalue().strip()
def queued(name): return [json.loads(l) for l in (Q / f"{name}.jsonl").read_text().splitlines()] if (Q / f"{name}.jsonl").exists() else []
def routed(key): return [x for x in routing.read(key) if x.get("kind") == "message"]
view = rr._view()
check("the heartbeat the readers see is the view just written (both sleepers, the control)", view is not None and {NAP, NAP2, OLD} <= set(view[0]), view and sorted(view[0]))
check("gone_why: nothing of a sleeper (by name and by id), the control's pane is gone for two hours on an online machine", rr.gone_why("work-osprey-nap", view=view) == "" and rr.gone_why(NAP, view=view) == ""
      and "gone for 120 min" in rr.gone_why("work-osprey-old", view=view), (rr.gone_why("work-osprey-nap", view=view), rr.gone_why("work-osprey-old", view=view)))
idx = _sr._sessions_index()
def dead(to, name):
    try: _messaging._dead_recipient(to, [r for r in idx.values() if r.get("name") == name], idx); return None
    except ToolError as e: return e
check("message: `_dead_recipient` lets a message to a sleeper through; the one gone as long is refused, readdressed to its project when the router can pass it on (`_Retired`)", dead(NAP, "work-osprey-nap") is None
      and isinstance(dead(OLD, "work-osprey-old"), _messaging._Retired) and dead(OLD, "work-osprey-old").project == "projects/alpha", (dead(NAP, "work-osprey-nap"), dead(OLD, "work-osprey-old")))
check("message: `_pane_dead` agrees (the sleeper no dead pane)", _messaging._pane_dead(idx[NAP]) == "" and _messaging._pane_dead(idx[OLD]) != "")
check("message: `_reachable` is true for the sleeper (the grace does not apply to it), false for the control", _messaging._reachable(NAP, idx) is True and _messaging._reachable("work-osprey-nap", idx) is True and _messaging._reachable(OLD, idx) is False)
n_alpha = len(routed("projects/alpha"))
rc, out = deliver("work-osprey-nap", "[stackshot] work-osprey-nap, a hand-off came to you", "stackshot")
check("push: a line for the sleeper is queued under its own name, like one for a live pane (nothing readdressed, nothing routed)", rc == 1 and out == "queued → work-osprey-nap" and len(queued("work-osprey-nap")) == 1
      and len(routed("projects/alpha")) == n_alpha and not LOG.exists(), (rc, out, queued("work-osprey-nap")))
rc, out = deliver(NAP, "[stackshot] by id", "stackshot")
check("…and one by its transcript id", out.startswith("queued") and "retired" not in out and len(queued(NAP)) == 1 and len(routed("projects/alpha")) == n_alpha, (rc, out))
rc, out = deliver("work-osprey-old", "[stackshot] work-osprey-old, a hand-off came to you", "stackshot")
check("control: the same line for the pane gone as long is readdressed to its project", rc == 1 and out.startswith("queued (retired: work-osprey-old, ") and "sent to projects/alpha" in out
      and queued("work-osprey-old") == [] and len(routed("projects/alpha")) == n_alpha + 1, (rc, out))

# ---- 4. the sessions tool
ls = _wt_sessions._sessions_listing("", now=NOW0).split("\n")
zone = dt.timezone(dt.timedelta(hours=4))
want = dt.datetime.fromtimestamp(T0 + 300, zone).strftime("%m-%d %H:%M +04")
nap = [l for l in ls if l.startswith("- work-osprey-nap ")]
check("sessions tool: a sleeper's row says since when it sleeps, in the instance's zone, and that a message wakes it", len(nap) == 1 and nap[0].endswith(f" · sleeping since {want} (asleep until a message wakes it)"), nap)
check("…and says nothing of 'not running' for it", nap and "not running" not in nap[0] and "sleeping" in nap[0], nap)
check("…a pane gone two hours that no open item names is left out, as before", not any(l.startswith("- work-osprey-old ") for l in ls), [l for l in ls if "old" in l])
# the mark goes: the normal rules start from the next check-in
links({NAP: iso(T0 + 300), **BAD})
cl.checkin(HOST, [], now=NOW0 + 10)
v = rd()
check("the mark gone from NAP2: it is marked gone from that check-in, its row carries no `sleeping`, it is present for the grace and a pane for dead_after", v[NAP2]["gone"] == iso(NOW0 + 10) and "sleeping" not in v[NAP2]
      and LV.present(v[NAP2], NOW0 + 20) and not LV.present(v[NAP2], NOW0 + 10 + 601) and LV.pane_dead(v[NAP2], NOW0 + 20) == "" and LV.pane_dead(v[NAP2], NOW0 + 10 + 3601) != "", v[NAP2])
ls = _wt_sessions._sessions_listing("", now=NOW0 + 20).split("\n")
check("sessions tool: the pane just gone is the plain 'not running now'; the sleeper still sleeping", any(l.startswith("- work-osprey-nap2 ") and l.endswith("not running now (relaunching, or retired; shown as last known)") for l in ls)
      and any(l.startswith("- work-osprey-nap ") and " · sleeping since " in l for l in ls), [l for l in ls if "nap" in l])
cl.checkin(HOST, [rec(NAP)], now=NOW0 + 30)
links()
cl.checkin(HOST, [rec(NAP)], now=NOW0 + 40)
v = rd()
check("the sleeper wakes (polled again, and the mark gone): a running row with no `sleeping` and no gone", "gone" not in v[NAP] and "sleeping" not in v[NAP] and LV.idle_live(v[NAP]) and cl.sleeping_sessions() == {}, v[NAP])
check("an unreadable or absent store marks nothing: no sleepers", (T / "links/a/sessions.json").unlink() is None and cl.sleeping_sessions() == {})

print(("ok" if not fails else "FAILED") + f": sleeping scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
