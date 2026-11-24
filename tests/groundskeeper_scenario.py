"""Scenario test for the anchors' daily pass (anchors/groundskeeper.py, run from the audit tick by service/audit_ticks._anchor_daily_tick): fixture data in a scratch folder, no live store, no network, no model call, no server socket.

  1  the gate: the first run of a day runs the three parts and writes the day to <state>/anchor-daily/last-run; a second run the same day does nothing; the next day runs again; a part that fails leaves no marker (the same
     day runs again on the next tick); a run in progress (the lock held) is not started a second time; a read-only copy does nothing
  2  part A, acts: what the sweep's rules ended and the ten-minute tick has not removed goes, with its routing-log line and restore call; a cap of its own (DAILY_CAP, far above the tick's 50); the mass-removal guard of rule 5
     still holds; a second run removes nothing; a status that is old or missing removes nothing by rule 5
  3  part B, reports and never removes: the same anchor on two pages, a direct entry naming a retired or an unregistered session (never "none", never a cloud session id), an anchor silent for 60 days (not one added lately, not
     one whose record is young); the roster or the status file that cannot be read is "cannot tell", never a guess; one report file per day, one routing-log line per day; the store is as it was
  4  part C, bounds the files: held notice texts older than 30 days, unbound.log rotated once per ISO week keeping 8, reports kept 30 days, shadow.jsonl once 30 days old; only what it lists, only in the state folder, no
     link followed (a link to a folder, a link in place of a file), subfolders and other names untouched
  5  the builder is told once and only when something was removed, through the audit tick's own sender
  6  each part failing alone does not stop the other two
  7  the audit tick: `_silence_tick` runs the pass after the other three, once a day, never raises into the tick, stands still when the audit is off
  8  no model call: the module imports no model client and starts no process (a full run with process starting refused), no writer of shadow.jsonl in the code

    tests/run-suite groundskeeper         → exit 0 / 1"""
import ast, contextlib, io, json, os, pathlib, re, sys, time, types
import datetime as dt

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="gkeep-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
sys.path.insert(0, STACK)

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.anchors import anchor_sweep as SW, anchors as ANC, groundskeeper as GK
from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro
from stackshot.core import xlock as _xlock
from stackshot.fleet import inbox as _inbox
from stackshot.fleet import sessions_registry as _sr
from stackshot.router import routing

DAY = 86400.0
NOW = 1_800_000_000.0                                    # a fixed "now" (a Friday, noon in the test zone): every age below is a number of days before it
ZONE = _cfg.tz()
today = lambda t=NOW: dt.datetime.fromtimestamp(t, ZONE).strftime("%Y-%m-%d")
local = lambda t: dt.datetime.fromtimestamp(t, ZONE).strftime("%Y-%m-%d %H:%M:%S")      # the form the anchors service writes its times in
P1, P2, P3 = "projects/alpha", "projects/beta", "projects/gamma"
STATE = T / "state"; ADIR = STATE / "anchor-daily"; ROUTER = STATE / "router"; HELD = ROUTER / "held"; FLAGS = pathlib.Path(_inbox.FLAGS)
for d in ("store/a", "fleet/a", "brain", "state", "outside"): (T / d).mkdir(parents=True, exist_ok=True)
os.makedirs(FLAGS, exist_ok=True); os.makedirs(HELD, exist_ok=True)
check("the anchors service's state folder is a folder directly below the state folder (where part C rotates its log)", FLAGS.parent == STATE, _inbox.FLAGS)

def put_item(n, status="open"):
    (T / f"store/a/{n}.json").write_text(json.dumps({"id": str(n), "subject": f"[home] item a{n}", "description": "- A thing, finished when it works", "status": status, "updated": 1.0, "metadata": {"project": P1}}))
put_item(1); put_item(2, "completed"); (T / "store/next-id").write_text("10")
def entry(url, items=None, added=1.0): return {"url": url, "items": items, "added": added, "by": "t"}
def set_store(d): ANC.save(d)
def get_store(): return json.loads((T / "store/anchors.json").read_text())
def urls(page): return [e["url"] for e in get_store().get(page, [])]
def lines(page, label=None): return [n for n in routing.read(page) if n.get("kind") == "anchor" and (label is None or n.get("label") == label)]
NOREADER = SW.Reader(None, None, None)
class Err:
    def __enter__(self): self.b = io.StringIO(); self.c = contextlib.redirect_stderr(self.b); self.c.__enter__(); return self
    def __exit__(self, *a): self.c.__exit__(*a)
    @property
    def text(self): return self.b.getvalue()
def run(now=NOW, **kw):
    with Err() as e: out = GK.run(now, **kw)
    return out, e.text
def reset_day(): (ADIR / GK.MARK).unlink(missing_ok=True)
def reset_all():
    reset_day()
    for f in ADIR.glob("report-*.json"): f.unlink()

# ---------- 2 + 1: part A through the gate ----------
CLOSED = [f"https://example.invalid/closed/{i}" for i in range(120)]
set_store({P1: [entry(u, ["a2"]) for u in CLOSED] + [entry("https://example.invalid/open", ["a1"]), entry("https://example.invalid/wide")]})
told = []
tick_removed = SW.sweep_tick()
check("2 the ten-minute tick removes at most [anchor_hub] sweep_per_tick (50) entries: 70 closed-item entries are left for the day's pass", len(tick_removed) == 50 and len([u for u in urls(P1) if u in CLOSED]) == 70, (len(tick_removed), len(urls(P1))))
check("1 before the first run there is no marker", GK.marker() == "")
out, err = run(reader=NOREADER, reg={}, tell=told.append)
check("1 the first run of the day runs the three parts and marks the day", out is not None and out["failed"] == [] and out["day"] == today() and GK.marker() == today() and (ADIR / GK.MARK).read_text() == today() + "\n", (out, err))
check("2 part A: the 70 entries the tick had not reached are removed in one run (the daily cap is far above the tick's), the open item's and the project-wide entry stay",
      len(out["removed"]) == 70 and urls(P1) == ["https://example.invalid/open", "https://example.invalid/wide"] and GK.DAILY_CAP >= 10 * SW.PER_TICK, (len(out["removed"]), urls(P1)))
ln = lines(P1, "anchor removed (items)")
check("2 …each removal has its routing-log line with the call that puts it back, ruled archived by the automatic ruler, and its line in the state folder's record",
      len(ln) == 120 and all(n.get("ruling") == "archived" and n.get("ruled_by") == routing.AUTO_RULER and "restore: anchors(project=" in str(n.get("text")) for n in ln)
      and len((T / "state/anchor-removed.jsonl").read_text().splitlines()) == 120, len(ln))
check("5 the builder is told once, in one line, that 70 entries were removed, with where the restore lines are, and no session is named in it",
      len(told) == 1 and "70 anchor entries" in told[0] and "items: 70" in told[0] and "anchor-removed.jsonl" in told[0] and "\n" not in told[0], told)
n_lines = len(ln)
parts_run = {"a": 0, "b": 0, "c": 0}
real = (GK.pass_a, GK.pass_b, GK.pass_c)
def spy(name, fn):
    def f(*a, **k): parts_run[name] += 1; return fn(*a, **k)
    return f
GK.pass_a, GK.pass_b, GK.pass_c = spy("a", real[0]), spy("b", real[1]), spy("c", real[2])
try:
    out2, err2 = run(NOW + 3600, reader=NOREADER, reg={}, tell=told.append)
    check("1 a second run the same day does nothing: no part runs, the marker stands, nobody is told again", out2 is None and parts_run == {"a": 0, "b": 0, "c": 0} and GK.marker() == today() and len(told) == 1, (out2, parts_run))
    out3, err3 = run(NOW + DAY, reader=NOREADER, reg={}, tell=told.append)
    check("1 the next day it runs again (all three parts), marks the new day, and with nothing to remove tells nobody",
          out3 is not None and parts_run == {"a": 1, "b": 1, "c": 1} and GK.marker() == today(NOW + DAY) and out3["removed"] == [] and len(told) == 1, (out3, parts_run, told))
    check("2 a second pass over the same store removes nothing (idempotent)", len(lines(P1, "anchor removed (items)")) == n_lines, "")
    # a part that fails leaves no marker, and the same day runs again
    reset_day(); parts_run.update(a=0, b=0, c=0)
    GK.pass_b = lambda *a, **k: (_ for _ in ()).throw(OSError("report folder gone"))
    out4, err4 = run(reader=NOREADER, reg={}, tell=told.append)
    check("1 a part that raises leaves no marker, is one line on stderr, and its result says which failed", out4["failed"] == ["b"] and GK.marker() == "" and "part b skipped: OSError: report folder gone" in err4, (out4, err4))
    GK.pass_b = spy("b", real[1])
    out5, err5 = run(NOW + 600, reader=NOREADER, reg={}, tell=told.append)
    check("1 …the next tick of the same day runs all three again and marks the day", out5 is not None and out5["failed"] == [] and GK.marker() == today() and parts_run["a"] == 2 and parts_run["c"] == 2, (out5, parts_run))
    # each part failing alone stops neither of the others
    for bad in "abc":
        reset_day(); parts_run.update(a=0, b=0, c=0)
        boom = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        setattr(GK, f"pass_{bad}", boom)
        o, e = run(reader=NOREADER, reg={}, tell=told.append)
        setattr(GK, f"pass_{bad}", spy(bad, real["abc".index(bad)]))
        others = {p for p in "abc" if p != bad}
        check(f"6 part {bad} failing alone: the other two ran, the failure is named, no marker", o["failed"] == [bad] and all(parts_run[p] == 1 for p in others) and GK.marker() == "", (o, parts_run))
finally:
    GK.pass_a, GK.pass_b, GK.pass_c = real
reset_all()
# one run at a time: the lock held by another holder -> nothing starts
lock = _xlock.XLock(GK.LOCK)
import threading
held_evt, free_evt, got = threading.Event(), threading.Event(), {}
def hold():
    with lock: held_evt.set(); free_evt.wait(10)
th = threading.Thread(target=hold); th.start(); held_evt.wait(10)
try:
    o, e = run(reader=NOREADER, reg={}, tell=told.append)
    check("1 while another run holds the lock a run does nothing and marks nothing", o is None and GK.marker() == "", (o, e))
finally:
    free_evt.set(); th.join()
o, e = run(reader=NOREADER, reg={}, tell=told.append)
check("1 …and once the lock is free the day runs", o is not None and GK.marker() == today(), (o, e))
reset_all()
_ro_real = _ro.is_read_only; _ro.is_read_only = lambda: True
try: o, e = run(reader=NOREADER, reg={}, tell=told.append)
finally: _ro.is_read_only = _ro_real
check("1 a read-only copy does nothing", o is None and GK.marker() == "", o)

# ---------- 2: the cap of its own, the guard, the status ----------
reset_all(); told.clear()
GK.DAILY_CAP = 3
try:
    set_store({P2: [entry(f"https://example.invalid/c/{i}", ["a2"]) for i in range(7)]})
    o, e = run(reader=NOREADER, reg={}, tell=told.append)
    check("2 the daily cap bounds one run (3 of 7 entries; the rest wait for the ten-minute tick)", len(o["removed"]) == 3 and len(urls(P2)) == 4 and "3 anchor entries" in told[0], (len(o["removed"]), told))
finally: GK.DAILY_CAP = 500
reset_all(); told.clear()
UNR = [f"https://github.com/o/r/issues/{700 + i}" for i in range(6)]
AIDS = [ANC.anchor_id(u) for u in UNR]
set_store({P3: [entry(u, None, 1.0) for u in UNR]})
ux = lambda days: {"unreadable": {"at": NOW - days * DAY, "why": "refused", "since": "x", "tries": 4}}
rd_all = SW.Reader({}, NOW - 60, {"anchors": {a: ux(9) for a in AIDS}}, NOW - 60)
o, e = run(reader=rd_all, reg={}, tell=told.append)
check("2 the mass-removal guard of rule 5 holds in the daily pass: 6 of 6 unreadable removes nothing, says so once on the routing log, tells nobody", o["removed"] == [] and urls(P3) == UNR and told == []
      and len([n for n in lines(P3) if "held back" in json.dumps(n)]) == 1, (o, told))
reset_all()
rd_some = SW.Reader({}, NOW - 60, {"anchors": {**{a: ux(9) for a in AIDS[:2]}, **{a: {} for a in AIDS[2:]}}}, NOW - 60)
o, e = run(reader=rd_some, reg={}, tell=told.append)
check("2 below the guard the old unreadable ones go (2 of 6), through the sweep's own rule 5", sorted(x["url"] for x in o["removed"]) == sorted(UNR[:2]) and all(x["rule"] == "unreadable" for x in o["removed"]), o["removed"])
reset_all(); told.clear()
set_store({P3: [entry(u, None, 1.0) for u in UNR[:2]]})
rd_old = SW.Reader({}, NOW - 60, {"anchors": {a: ux(30) for a in AIDS[:2]}}, NOW - 3600)        # a status file an hour old
o, e = run(reader=rd_old, reg={}, tell=told.append)
check("2 a status file that is old removes nothing by rule 5, and the run still ends well", o["removed"] == [] and len(urls(P3)) == 2 and o["failed"] == [], o)

# ---------- 3: part B ----------
reset_all()
def sess(sid, name, state="live"): return {"id": sid, "name": name, "aliases": [], "state": state, "transcripts": []}
REG = T / "fleet/a/session-registry.json"
def write_reg(*rows): REG.write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-11-20T00:00:00Z", "sessions": {r["id"]: r for r in rows}}))
write_reg(sess("00000000-0000-4000-8000-000000000001", "agent-a"), sess("00000000-0000-4000-8000-000000000002", "agent-b", "retired"))
_cfg.CFG.setdefault("client", {})["session_links"] = f"{tmp}/fleet"
_cfg.CFG.setdefault("anchor_hub", {})["direct"] = {"slack:C0000000001": "agent-a", "slack:C0000000002": "agent-b", "slack:C0000000003": "agent-ghost", "slack:C0000000004": "none", "slack:C0000000005": "cse_e1"}
DUP = "https://github.com/o/r/issues/900"
PLAIN = "https://example.invalid/plain"
S = {k: f"https://github.com/o/r/issues/{800 + i}" for i, k in enumerate(("old", "recent", "new", "norec", "young", "edge", "justin"))}
store_b = {P1: [entry(DUP), entry(PLAIN, None, NOW - 100 * DAY), entry(S["old"], None, NOW - 100 * DAY), entry(S["recent"], None, NOW - 100 * DAY), entry(S["new"], None, NOW - 10 * DAY), entry(S["norec"], None, NOW - 100 * DAY),
                entry(S["edge"], None, NOW - 100 * DAY), entry(S["justin"], None, NOW - 100 * DAY)],
           P2: [entry(DUP), entry(S["young"], None, NOW - 100 * DAY)]}
aid = lambda k: ANC.anchor_id(S[k])
def status_for(began): return {"history_since": local(began), "anchors": {aid("old"): {"last": local(NOW - 70 * DAY)}, aid("recent"): {"last": local(NOW - 10 * DAY)}, aid("edge"): {"last": local(NOW - 60 * DAY)}, aid("justin"): {"last": local(NOW - 60 * DAY + 3600)}}}
set_store(store_b); before = get_store()
rdB = SW.Reader({}, NOW - 60, status_for(NOW - 100 * DAY), NOW - 60)
f = GK.pass_b_findings(NOW, store=get_store(), reader=rdB)
sil = {a["url"]: a["days"] for a in f["silent"]["anchors"]}
check("3 the same anchor on two pages is reported with its pages; one on a single page is not", f["duplicates"] == [{"anchor": ANC.anchor_id(DUP), "pages": [P1, P2]}], f["duplicates"])
check("3 a direct entry naming a retired session or one the registry has not is reported with the reason; a live one, \"none\" and a cloud session id are not",
      sorted((p["anchor"], p["session"], p["why"]) for p in f["direct"]["problems"]) == [("slack:C0000000002", "agent-b", "retired"), ("slack:C0000000003", "agent-ghost", "not registered")] and f["direct"]["checked"] == 4 and f["direct"]["cannot_tell"] == "", f["direct"])
check("3 an anchor whose last event is 70 days back is silent; 10 days, or exactly 60 days less an hour, is not; exactly 60 days is; an entry added 10 days ago is not; a url the service has no reader for is never silent",
      PLAIN not in sil and S["old"] in sil and sil[S["old"]] == 70 and S["recent"] not in sil and S["edge"] in sil and S["justin"] not in sil and S["new"] not in sil, sil)
check("3 an anchor with no event on record counts from when it was added or the service's record began, whichever is later: added 100 days ago with a record of 100 days is silent, with a record of 20 days it is not",
      S["norec"] in sil and S["young"] in sil and S["norec"] in {a["url"] for a in GK.pass_b_findings(NOW, store=get_store(), reader=rdB)["silent"]["anchors"]}
      and S["norec"] not in {a["url"] for a in GK.pass_b_findings(NOW, store=get_store(), reader=SW.Reader({}, NOW - 60, status_for(NOW - 20 * DAY), NOW - 60))["silent"]["anchors"]}, sil)
f2 = GK.pass_b_findings(NOW, store=get_store(), reader=SW.Reader({}, NOW - 60, status_for(NOW - 100 * DAY), NOW - 3600))
check("3 a status file that is old: the silent anchors are \"cannot tell\", none is named", f2["silent"]["anchors"] == [] and "status file" in f2["silent"]["cannot_tell"], f2["silent"])
f3 = GK.pass_b_findings(NOW, store=get_store(), reader=SW.Reader({}, NOW - 60, None, None))
check("3 a status file that is missing: the same", f3["silent"]["anchors"] == [] and f3["silent"]["cannot_tell"], f3["silent"])
REG.write_text("{torn")
f4 = GK.pass_b_findings(NOW, store=get_store(), reader=rdB)
check("3 a session registry that cannot be read: the direct entries are \"cannot tell\", none is called retired or unregistered (never from an unreadable roster)", f4["direct"]["problems"] == [] and "cannot be read" in f4["direct"]["cannot_tell"], f4["direct"])
REG.unlink()
f5 = GK.pass_b_findings(NOW, store=get_store(), reader=rdB)
check("3 …a registry with no file: the same", f5["direct"]["problems"] == [] and f5["direct"]["cannot_tell"], f5["direct"])
write_reg(sess("00000000-0000-4000-8000-000000000001", "agent-a"), sess("00000000-0000-4000-8000-000000000002", "agent-b", "retired"))
_cfg.CFG["anchor_hub"]["direct"] = {}
REG.write_text("{torn")
f6 = GK.pass_b_findings(NOW, store=get_store(), reader=rdB)
check("3 no direct entry at all: nothing to check, so nothing to say even with a registry that cannot be read", f6["direct"] == {"checked": 0, "problems": [], "cannot_tell": ""}, f6["direct"])
write_reg(sess("00000000-0000-4000-8000-000000000001", "agent-a"), sess("00000000-0000-4000-8000-000000000002", "agent-b", "retired"))
_cfg.CFG["anchor_hub"]["direct"] = {"slack:C0000000002": "agent-b", "slack:C0000000003": "agent-ghost"}
n_label = len(lines(P1, GK.LABEL))
with Err():
    fb = GK.pass_b(NOW, today(), store=get_store(), reader=rdB)
rep = ADIR / f"report-{today()}.json"
check("3 the report is one file for the day, with the findings and the day", rep.is_file() and json.loads(rep.read_text())["day"] == today() and json.loads(rep.read_text())["duplicates"] == fb["duplicates"], rep.exists())
check("3 …and one summary line on the routing log of the first page with a finding, that says nothing was removed and where the report is",
      len(lines(P1, GK.LABEL)) == n_label + 1 and "nothing removed" in str(lines(P1, GK.LABEL)[-1].get("text")) and str(rep) in str(lines(P1, GK.LABEL)[-1].get("text")), lines(P1, GK.LABEL))
with Err(): GK.pass_b(NOW + 60, today(), store=get_store(), reader=rdB)
check("3 …a second pass of the same day rewrites the report and adds no second line", len(lines(P1, GK.LABEL)) == n_label + 1, len(lines(P1, GK.LABEL)))
check("3 part B removed nothing and changed nothing in the store, whatever it found (duplicates, a retired target, silent anchors)", get_store() == before, "")
set_store({P1: [entry("https://example.invalid/fine", None, NOW - DAY)]}); reset_all(); _cfg.CFG["anchor_hub"]["direct"] = {}; n_label = len(lines(P1, GK.LABEL))
with Err(): fq = GK.pass_b(NOW, today(), store=get_store(), reader=SW.Reader({}, NOW - 60, {"anchors": {}}, NOW - 60))
check("3 with nothing to report the file is still written and no line goes on any routing log", (ADIR / f"report-{today()}.json").is_file() and len(lines(P1, GK.LABEL)) == n_label and fq["duplicates"] == [], lines(P1, GK.LABEL))

# ---------- 4: part C ----------
def touch(path, age_days, now=NOW, text="x"):
    path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_symlink(): path.write_text(text)
    t = now - age_days * DAY; os.utime(path, (t, t), follow_symlinks=False)
    return path
outside = T / "outside"; secret = touch(outside / "keep.json", 400)
for f_ in HELD.glob("*"): f_.unlink() if f_.is_file() or f_.is_symlink() else None
touch(HELD / "aaaaaa.json", 31); touch(HELD / "bbbbbb.json", 29); touch(HELD / "cccccc.json", 30)     # the boundary: 30 days goes, 29 stays
touch(HELD / "notes.txt", 90); touch(HELD / "AAAAAA.json", 90); touch(HELD / "aaaaaa.json.bak", 90)       # names that are no notice id's: not listed
os.symlink(secret, HELD / "dddddd.json"); os.utime(HELD / "dddddd.json", (NOW - 90 * DAY,) * 2, follow_symlinks=False)    # a link in place of a text
(HELD / "sub").mkdir(); touch(HELD / "sub/eeeeee.json", 90)
touch(ROUTER / "shadow.jsonl", 31); touch(ROUTER / "calls.jsonl", 90); touch(ROUTER / "live.jsonl", 90)
os.makedirs(ADIR, exist_ok=True)
for k in (0, 29, 30, 45): touch(ADIR / f"report-{today(NOW - k * DAY)}.json", 0)
touch(ADIR / "report-2027-99-99.json", 0); touch(ADIR / "report-old.json", 0); touch(ADIR / "notes.txt", 0)
c = GK.pass_c(NOW, today())
check("4 held notice texts: 31 and 30 days go, 29 stays; a name that is no notice id, a link, a subfolder's file and another folder's files are not touched",
      c["held"] == ["aaaaaa.json", "cccccc.json"] and sorted(p.name for p in HELD.iterdir()) == ["AAAAAA.json", "aaaaaa.json.bak", "bbbbbb.json", "dddddd.json", "notes.txt", "sub"]
      and (HELD / "sub/eeeeee.json").exists() and secret.exists() and (ROUTER / "calls.jsonl").exists() and (ROUTER / "live.jsonl").exists(), (c["held"], sorted(p.name for p in HELD.iterdir())))
check("4 shadow.jsonl, which nothing writes, goes at 30 days (31 here) and nothing else of the router's folder", c["shadow"] == ["shadow.jsonl"] and not (ROUTER / "shadow.jsonl").exists(), c["shadow"])
touch(ROUTER / "shadow.jsonl", 29); c = GK.pass_c(NOW, today())
check("4 …and not at 29 days", c["shadow"] == [] and (ROUTER / "shadow.jsonl").exists(), c)
check("4 reports: those 30 days old or more (by the day in the name) go, today's and 29 days' stay; a name with no real date and other names are not touched",
      sorted(p.name for p in ADIR.iterdir() if p.name.startswith("report-") or p.name == "notes.txt") == sorted([f"report-{today(NOW)}.json", f"report-{today(NOW - 29 * DAY)}.json", "report-2027-99-99.json", "report-old.json", "notes.txt"]), sorted(p.name for p in ADIR.iterdir()))
# a link in place of a folder: nothing outside is touched
os.rename(HELD, T / "held-real"); os.symlink(outside, HELD)
touch(outside / "ffffff.json", 90)
c = GK.pass_c(NOW, today())
check("4 a link where a folder is expected (router/held -> another folder) is not followed: the files behind it stay", c["held"] == [] and (outside / "ffffff.json").exists() and (outside / "keep.json").exists(), c)
os.unlink(HELD); os.rename(T / "held-real", HELD)
(ROUTER / "shadow.jsonl").unlink(); touch(outside / "shadow.jsonl", 90)
os.symlink(outside / "shadow.jsonl", ROUTER / "shadow.jsonl"); os.utime(ROUTER / "shadow.jsonl", (NOW - 90 * DAY,) * 2, follow_symlinks=False)
c = GK.pass_c(NOW, today())
check("4 a link in place of shadow.jsonl is no plain file: it is left, and so is its target", c["shadow"] == [] and os.path.islink(ROUTER / "shadow.jsonl") and (outside / "shadow.jsonl").exists(), c)
os.unlink(ROUTER / "shadow.jsonl")
# unbound.log
for p in FLAGS.glob("unbound.log*"): p.unlink()
(FLAGS / "unbound.log").write_text("2027-01-14 slack:C1 mention x\n")
W = GK._week(NOW)
c = GK.pass_c(NOW, today())
check("4 unbound.log is rotated to unbound.log.<ISO week> once a week: the log is renamed whole and the service writes a new one", c["unbound"]["rotated"] == f"unbound.log.{W}" and (FLAGS / f"unbound.log.{W}").read_text().startswith("2027-01-14") and not (FLAGS / "unbound.log").exists(), (c["unbound"], sorted(p.name for p in FLAGS.iterdir())))
(FLAGS / "unbound.log").write_text("2027-01-15 slack:C2 mention y\n")
c = GK.pass_c(NOW + 2 * DAY, today(NOW + 2 * DAY))
check("4 …not a second time in the same week", c["unbound"]["rotated"] == "" and (FLAGS / "unbound.log").read_text().startswith("2027-01-15") and sorted(p.name for p in FLAGS.glob("unbound.log*")) == sorted(["unbound.log", f"unbound.log.{W}"]), c["unbound"])
c = GK.pass_c(NOW + 7 * DAY, today(NOW + 7 * DAY))
check("4 …and the next week it is", c["unbound"]["rotated"] == f"unbound.log.{GK._week(NOW + 7 * DAY)}" and not (FLAGS / "unbound.log").exists(), c["unbound"])
for p in FLAGS.glob("unbound.log*"): p.unlink()
for i in range(10, 22): (FLAGS / f"unbound.log.2026-W{i:02d}").write_text("old\n")      # twelve rotated copies already
(FLAGS / "unbound.log").write_text("fresh\n"); (FLAGS / "unbound.log.2026-W5").write_text("not ours\n"); (FLAGS / "unbound.log.gz").write_text("not ours\n")
c = GK.pass_c(NOW, today())
kept = sorted(p.name for p in FLAGS.glob("unbound.log.????-W??"))
check("4 rotation keeps exactly 8 rotated files, the newest by week, this week's included; names that are no rotated copy stay",
      len(kept) == 8 and kept[-1] == f"unbound.log.{W}" and kept[0] == "unbound.log.2026-W15" and (FLAGS / "unbound.log.2026-W5").exists() and (FLAGS / "unbound.log.gz").exists() and len(c["unbound"]["deleted"]) == 5, (kept, c["unbound"]))
for p in FLAGS.glob("unbound.log*"): p.unlink()
os.symlink(secret, FLAGS / "unbound.log")
c = GK.pass_c(NOW, today())
check("4 a link in place of unbound.log is not rotated", c["unbound"]["rotated"] == "" and os.path.islink(FLAGS / "unbound.log") and secret.exists(), c["unbound"])
os.unlink(FLAGS / "unbound.log"); (FLAGS / "unbound.log").write_text("")
check("4 an empty unbound.log is not rotated", GK.pass_c(NOW, today())["unbound"]["rotated"] == "", "")
saved = _inbox.FLAGS; _inbox.FLAGS = outside
try:
    (outside / "unbound.log").write_text("x\n"); c = GK.pass_c(NOW, today())
    check("4 a service folder outside the state folder is none of this pass's: nothing is rotated there", c["unbound"]["rotated"] == "" and (outside / "unbound.log").exists(), c["unbound"])
finally: _inbox.FLAGS = saved
check("4 constants: 30 days for held texts and reports and shadow.jsonl, 8 rotated copies, 60 days silent", (GK.HELD_DAYS, GK.REPORT_DAYS, GK.SHADOW_DAYS, GK.UNBOUND_KEEP, GK.SILENT_DAYS) == (30, 30, 30, 8, 60), "")

# ---------- 7: the audit tick ----------
reset_all(); told.clear()
from stackshot.service import audit_ticks as AT
from stackshot.service import fleet_events as FE
sent, pubs, order = [], [], []
real_flag = FE.inbox_flag_send
AT._hooks = lambda: types.SimpleNamespace(publish=lambda *a, **k: pubs.append(1))
FE.inbox_flag_send = lambda to, text: sent.append((to, text))
real_ticks = (AT._hourly_tick, AT._hand_idle_tick, AT._busy_tell_tick, AT._anchor_daily_tick)
AT._hourly_tick = lambda *a, **k: order.append("hourly"); AT._hand_idle_tick = lambda *a, **k: order.append("hand"); AT._busy_tell_tick = lambda *a, **k: order.append("busy")
AT._anchor_daily_tick = lambda *a, **k: (order.append("daily"), real_ticks[3](*a, **k))[1]
_cfg.CFG.setdefault("audit", {}).update(enabled=False, mode="script")
set_store({P1: [entry(u, ["a2"]) for u in CLOSED[:4]]})
with Err(): AT._silence_tick()
check("7 the audit off: the audit tick stands still as a whole, the daily pass included", order == [] and GK.marker() == "" and sent == [] and len(urls(P1)) == 4, order)
_cfg.CFG["audit"]["enabled"] = True
with Err() as e: AT._silence_tick()
check("7 the audit on: the daily pass runs last, after the hourly line, the idle hand-over and the busy tell, removes what the rules ended, publishes the board once and marks the day",
      order == ["hourly", "hand", "busy", "daily"] and urls(P1) == [] and GK.marker() == today(time.time()) and len(pubs) == 1, (order, urls(P1), GK.marker(), e.text[-300:]))
check("5 …and the builder named by [audit] builder is told once, in one line, by the audit tick's sender", len(sent) == 1 and sent[0][0] == _cfg.audit_builder() and "4 anchor entries" in sent[0][1], sent)
order.clear()
with Err(): AT._silence_tick()
check("7 a second tick the same day: the pass finds the day marked, removes nothing, publishes nothing, tells nobody", order[-1] == "daily" and len(sent) == 1 and len(pubs) == 1, (order, sent, pubs))
reset_day(); set_store({P1: [entry("https://example.invalid/open", ["a1"])]}); sent.clear(); pubs.clear()
with Err(): AT._silence_tick()
check("5 a day that removed nothing tells the builder nothing and publishes nothing", sent == [] and pubs == [] and GK.marker() == today(time.time()), (sent, pubs))
reset_day(); set_store({P1: [entry("https://example.invalid/x", ["a2"])]}); real_default, real_builder = _cfg.AUDIT_BUILDER, _cfg.CFG["audit"].get("builder"); _cfg.AUDIT_BUILDER = ""; _cfg.CFG["audit"]["builder"] = ""
try:
    with Err() as e: AT._silence_tick()
finally: _cfg.AUDIT_BUILDER = real_default; _cfg.CFG["audit"]["builder"] = real_builder
check("5 with no builder to tell: one stderr line, the removal stands, nothing raises", urls(P1) == [] and "no builder is set" in e.text and sent == [], (e.text, sent))
reset_day(); set_store({P1: [entry("https://example.invalid/y", ["a2"])]})
AT._anchor_daily_tick = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("tick bug"))
with Err() as e: r_ = AT._silence_tick()
check("7 a daily pass that raises into the tick is one stderr line and never escapes the audit tick", r_ is None and "the daily anchor pass not run: RuntimeError: tick bug" in e.text, e.text)
AT._hourly_tick, AT._hand_idle_tick, AT._busy_tell_tick, AT._anchor_daily_tick = real_ticks
FE.inbox_flag_send = real_flag

# ---------- 8: no model, no process ----------
src = pathlib.Path(STACK, "stackshot/anchors/groundskeeper.py").read_text(encoding="utf-8")
imported = set()
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Import): imported |= {a.name for a in node.names}
    elif isinstance(node, ast.ImportFrom): imported |= {f"{node.module}.{a.name}" for a in node.names}
check("8 the module imports no process or model client (no subprocess, no router or audit module, no http client)",
      not any(m.split(".")[0] in ("subprocess", "urllib", "http", "requests", "anthropic", "shlex", "socket") or ".router.router" in "." + m or m.startswith(("stackshot.audit", "stackshot.router.router_live", "stackshot.service")) for m in imported), sorted(imported))
check("8 …its imports are the sweep, the anchors store, the core, the registry and the routing log", {m for m in imported if m.startswith("stackshot")} == {"stackshot.anchors.anchor_sweep", "stackshot.anchors.anchors", "stackshot.core.config", "stackshot.core.readonly", "stackshot.core.xlock", "stackshot.fleet.inbox", "stackshot.fleet.sessions_registry", "stackshot.router.routing"}, sorted(imported))
import subprocess
def refuse(*a, **k): raise AssertionError("a process was started: " + str(a)[:100])
real_proc = (subprocess.Popen, subprocess.run, os.system)
subprocess.Popen, subprocess.run, os.system = refuse, refuse, refuse
try:
    reset_all(); write_reg(sess("00000000-0000-4000-8000-000000000001", "agent-a"))
    set_store({P1: [entry("https://example.invalid/z", ["a2"]), entry(DUP)], P2: [entry(DUP)]})
    o, e = run(tell=told.append)
finally: subprocess.Popen, subprocess.run, os.system = real_proc
check("8 a whole run with starting a process refused ends well: all three parts ran, nothing was started", o is not None and o["failed"] == [] and len(o["removed"]) == 1 and o["report"]["duplicates"], (o, e))
code_dirs = [p for p in pathlib.Path(STACK, "stackshot").rglob("*.py")]
writers = [str(p.relative_to(STACK)) for p in code_dirs if "shadow.jsonl" in p.read_text(encoding="utf-8", errors="replace") and p.name != "groundskeeper.py"]
check("8 shadow.jsonl has no writer in the package: no module but this one names it (only the test harness tests/shadow_harness.py writes it)", writers == [], writers)

print(("ok" if not fails else "FAILED") + f": {len(ran) - len(fails)}/{len(ran)} checks")
sys.exit(1 if fails else 0)
