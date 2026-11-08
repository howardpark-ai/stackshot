"""Scenario test for the Landed list (landed.py, the header count and the page in render.py, GET /landed and POST /landed/clear in server.py) — fixture data, the routes through Starlette's test client, no live store, no network.

Covers:
  * the set: a close by an agent to done or dropped is a record (a session's close through the complete tool, and the server's own close on a done check); Oliver's own close
    (his answer on the board, a write whose sender is he) makes none, nor does a close to any other outcome (superseded);
  * the board item, until cleared: an entry stays until Oliver clears it (like a phone's notifications): the home count and the page read one function (Board.landed_rows), so the count equals the
    number of lines on the page for mixed data, before and after a single Clear and after Clear all; opening the page clears nothing; a cleared entry leaves both; 60 days is the bound of an uncleared one;
    an entry the old code marked `seen` is uncleared; the old /landed/seen route still clears;
  * a landed.json that cannot be read is never written over; a hand-edited ts of inf or nan is a bad record, not an error;
  * the header: the Closed card linking /closed after Waiting (/landed redirects to it), drawn at 0 muted;
  * the board item, scope groups: the top headings are the scopes sala's sidebar has (home, work, ops), read from projects.py (a mark set on purpose, else derive_scope) in [project_scopes] order, each project nested under its scope; counts per scope and per project;
  * the page (the Closed page, ui/render.py): a New section of uncleared closes above the Last 14 days list; grouped by project (under its scope), newest first within a group, the groups by their newest close; each row the
    outcome tag, the id and subject (a link), the relative close time (exact time on hover), the close reason under it, a Clear button; Clear all at the top; nothing escaped wrongly; behind the sign-in;
  * Clear and Clear all refuse a visitor not signed in and a foreign origin; a close that lands after the page was drawn stays on the list;
  * a reopened item loses its record, and its next close is a new uncleared record whatever the first one's state;
  * the For you list is untouched: still hidden (render._SHOW_FOR_YOU), its rows unchanged by a clear here;
  * a landed.json that does not parse is moved aside and the list starts empty.

    tests/run-suite landed        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="landedtest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
EMAIL = "oliver@example.org"
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
A, X, B, Y = ("22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333", "44444444-4444-4444-8444-444444444444",
              "55555555-5555-4555-8555-555555555555")
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for u, n in
                                                      ((A, "work-osprey-main"), (X, "work-osprey-x"), (B, "home-beta"), (Y, "home-beta-x"))}))
def page_entry(name, agents): return {"title": name.title(), "name": name.title(), "org": "home", "tags": [], "type": "project", "session": agents[0], "status": "active", "board": [], "board_row": False,
                                      "updated": 1, "mirror": "https://example.invalid/" + name, "agents": {a: "builds" for a in agents}}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": page_entry("alpha", ["work-osprey-main", "work-osprey-x"]),
                                                              "projects/beta": page_entry("beta", ["home-beta", "home-beta-x"])}}))
for k, v in (("alpha", "ALPHA"), ("beta", "BETA")):
    (T / f"brain/projects/{k}.md").write_text(f"---\ntitle: {k.title()}\n---\n# {k.title()}\n\n## Current state\n\n{v}-STATE.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
now0 = time.time(); DAY = 86400.0
DESC = "- Goal: A thing\n- It lives here\n- Finished when it works"
def item(i, owner=A, status="open", project="projects/alpha", subject=None, su=None, **meta):
    su = now0 - 3600 if su is None else su
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": owner, "project": project, "next": "the next step", **meta}}))
# 1-9 open items an agent will close · 10-19 already-closed fixtures for the page's order
for i in (1, 2, 3, 4, 5, 6, 7, 8): item(i)
item(9, owner=B, project="projects/beta"); item(10, owner=B, project="projects/beta")
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
(T / "fakepush.py").write_text("import sys\nprint('delivered → ' + sys.argv[-2])\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())

from stackshot.core import config as _cfg; from stackshot.web import landed as ld; from stackshot.web import foryou as fy
from stackshot.web import server
from stackshot.web.ui import render
from starlette.testclient import TestClient
pub = [0]; server._publish = lambda: pub.__setitem__(0, pub[0] + 1)
server._PUSH = [sys.executable, str(T / "fakepush.py")]
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
_cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, "live": True}
NEWD = "- Goal: The thing works and is in use"
def cl(i, sender="work-osprey-x", outcome="done", reason="PR 80 is live", **kw):
    return server.stackshot_complete(f"a{i}", outcome=outcome, reason=reason, description=NEWD, sender=sender, **kw)
def board(): return render.Board(str(T / "store"))
def hdr(b=None):
    h = (b or board()).html(); return h[h.find('<nav class="hcards"'):h.find("</nav>", h.find('<nav class="hcards"')) + 6]
def txt(h): return re.sub(r"<[^>]+>", "", h)
def recs(): return {r["gid"]: r for r in ld.records()}
def agents(): return sum(1 for f in (T / "store/a").glob("*.json") if json.loads(f.read_text())["status"] == "open")      # the open items: Agents at work, all of them here
CARD = r'<a class="hcard[^"]*" href="([^"]+)"[^>]*><b>(\d+)</b><span>(.*?)(?: <i class="hnew[^"]*">(\d+)<em> new</em></i>)?</span></a>'      # the header's count cards, the number over its label; the Closed card's fourth item is its new count, on the label line
def cards(h=None): return [(href, n, re.sub(r"<[^>]+>", "", lab)) + ((int(new or 0),) if href == "/closed" else ()) for href, n, lab, new in re.findall(CARD, h or hdr())]
def base(n=0, b=None): return [("#your-move", "0", "Your move"), ("#agents-at-work", str(agents()), "On agent"), ("#queued-release", "0", "Queued for release"), ("#waiting-list", "0", "Waiting"), ("/closed", str(len((b or board()).done)), "Closed", n)]
def ids_of(h): return re.findall(r'<a class="ir-link" href="/items/(a?\d+)"', newsec(h) if '<section id="new"' in h else h)      # the item ids the lines of the New section link, in page order
def newsec(h): return h[h.find('<section id="new"'):h.find('<section id="completed"')]      # the New section of the Closed page; the Last 14 days section follows it
# ---- 1. the store on its own
check("the list starts empty; its file lives in the state dir", ld.records() == [] and str(ld.path()).startswith(f"{tmp}/state/"), ld.path())
K = int(now0) - 5000
check("a record needs an outcome that lands: done and dropped do, superseded and unrecorded do not", ld.record("a34", K, "done") and ld.record("a11", K + 1, "dropped", by="x", project="p")
      and not ld.record("a16", K + 2, "superseded") and not ld.record("a17", K + 3, "unrecorded") and sorted(r["gid"] for r in ld.records(now=K + 500)) == ["a11", "a34"])
check("…the same close recorded twice makes no second record; a later close of the item replaces the record, uncleared", not ld.record("a34", K, "done")
      and ld.clear([ld.key("a34", K)], now=K + 100) == 1 and [r["gid"] for r in ld.records(now=K + 500)] == ["a11"] and ld.record("a34", K + 1000, "done") and [r["cleared"] for r in ld.records(now=K + 2500) if r["gid"] == "a34"] == [0])
check("a cleared close recorded again (the same close, twice) stays cleared: the record is kept so it cannot come back", ld.clear([ld.key("a11", K + 1)], now=K + 2000) == 1
      and not ld.record("a11", K + 1, "dropped", by="x", project="p") and "a11" not in {r["gid"] for r in ld.records(now=K + 2500)})
check("clear names a close by its item and clock: the old key clears nothing once the item closed again", ld.clear([ld.key("a34", K)], now=K + 2100) == 0 and ld.clear([ld.key("a34", K + 1000)], now=K + 2100) == 1)
ld.record("a18", K + 5, "done"); ld.record("a28", K + 6, "done")
check("…None clears every uncleared record; the file is written whole (no tmp file beside it)", ld.clear(None, now=K + 3000) == 2 and ld.records(now=K + 3500) == []
      and not list(ld.path().parent.glob(".landed.json*")))
ld.forget("a18"); ld.forget("a28")
ld.forget("a34"); ld.forget("a11")
check("forget takes a record off (an item open again)", ld.records(now=K + 3500) == [] and ld._load() == {})
ld.path().write_text("{ not json", encoding="utf-8")
check("a landed.json that does not parse is moved aside and the list starts empty", ld.records() == [] and len(list(ld.path().parent.glob("landed.json.bad-*"))) == 1, list(ld.path().parent.iterdir()))
ld.path().unlink(missing_ok=True)
for f in ld.path().parent.glob("landed.json.bad-*"): f.unlink()

# a file that cannot be read is never written over: record, forget and clear raise and leave it; the board's reader sees an empty list
ld.record("old1", K + 10, "done", by="x", project="p")
before_txt = ld.path().read_text(encoding="utf-8")
os.chmod(ld.path(), 0)
_real_read = pathlib.Path.read_text
try:
    try: ld.path().read_text(); readable = True              # root reads a mode 000 file: then a read error is made by hand
    except PermissionError: readable = False
    if readable: pathlib.Path.read_text = lambda self, *a, **k: (_ for _ in ()).throw(PermissionError(13, "forced")) if self == ld.path() else _real_read(self, *a, **k)
    errs = []
    for fn in (lambda: ld.record("new", K + 20, "done"), lambda: ld.forget("old1"), lambda: ld.clear(None)):
        try: fn(); errs.append(None)
        except OSError as e: errs.append(e.__class__.__name__)
    seen_by_reader = ld.records(now=K + 500)
finally:
    pathlib.Path.read_text = _real_read
    os.chmod(ld.path(), 0o644)
check("an unreadable landed.json (EACCES): record, forget and clear raise instead of writing, the reader sees an empty list, and the file still holds the old record and not the new one",
      errs == ["PermissionError"] * 3 and seen_by_reader == [] and ld.path().read_text(encoding="utf-8") == before_txt and set(ld._load()) == {"old1"}, (errs, seen_by_reader))
check("…readable again, the next record works and keeps the old one", ld.record("new", K + 20, "done") and set(ld._load()) == {"old1", "new"})
# a hand-edited ts of inf or nan is a bad record like any other: the others load, and the next write drops it
ld.path().write_text(json.dumps({"closes": {"good": {"ts": K + 30, "outcome": "done", "by": "", "project": "", "cleared": 0}, "inf": {"ts": float("inf"), "outcome": "done"},
                                            "nan": {"ts": float("nan"), "outcome": "done"}, "str": {"ts": "x", "outcome": "done"}}}), encoding="utf-8")
check("a ts of Infinity, NaN or text does not raise: that record is skipped and the good one is listed", [r["gid"] for r in ld.records(now=K + 500)] == ["good"], ld.records(now=K + 500))
check("…the next record() writes the file without the bad ones", ld.record("next", K + 40, "done") and set(ld._load()) == {"good", "next"} and "Infinity" not in ld.path().read_text(encoding="utf-8"))
for g in ("good", "next", "old1", "new"): ld.forget(g)
# an entry the old code marked `seen` (the page opened once) was never cleared by Oliver: it is on the list again, and the next write drops the field
ld.path().write_text(json.dumps({"closes": {"was-marked": {"ts": K + 50, "outcome": "done", "by": "", "project": "", "seen": K + 60}}}), encoding="utf-8")
check("an entry stored by the old code as seen (`seen` set, no `cleared`) is uncleared: listed, and the next write drops the old field", [r["gid"] for r in ld.records(now=K + 500)] == ["was-marked"]
      and ld.record("after", K + 70, "done") and "seen" not in ld.path().read_text(encoding="utf-8").replace("was-marked", "") and {r["gid"] for r in ld.records(now=K + 500)} == {"was-marked", "after"})
for g in ("was-marked", "after"): ld.forget(g)

# ---- 1b. un-clear in the store
ld.record("u1", int(now0) - 100, "done"); ld.record("u2", int(now0) - 200, "done"); ld.clear(["u1:%d" % (int(now0) - 100)])
check("un-clear restores a cleared record whose key matches, and says how many", ld.unclear(["u1:%d" % (int(now0) - 100)]) == 1 and recs()["u1"]["cleared"] == 0 and "u2" in recs())
check("…an uncleared record, an unknown key, a key of another close of the same item, and no key at all restore nothing",
      ld.unclear(["u1:%d" % (int(now0) - 100)]) == 0 and ld.unclear(["nope:1"]) == 0 and ld.unclear(["u2:%d" % (int(now0) - 201)]) == 0 and ld.unclear([]) == 0 and ld.unclear([""]) == 0)
ld.clear(["u2:%d" % (int(now0) - 200)]); d_ = ld._load(); d_["u2"]["ts"] = int(now0 - 61 * DAY); ld._save(d_)
check("…a cleared record past the 60 days is not restored (it would not be listed)", ld.unclear([ld.key("u2", now0 - 61 * DAY)], now=now0) == 0 and ld._load()["u2"]["cleared"] > 0)
d_ = ld._load(); d_["u2"]["ts"] = int(now0 - 59 * DAY); ld._save(d_)
check("…one at 59 days is", ld.unclear([ld.key("u2", now0 - 59 * DAY)], now=now0) == 1 and ld._load()["u2"]["cleared"] == 0)
ld.forget("u1"); ld.forget("u2")

# ---- 2. the set: whose closes land
check("before any close the header carries the Closed card at 0, its number muted, still a link to the page (drawn at 0, not hidden), with no new badge",
      cards() == base(0) and '<a class="hcard zero" href="/closed"' in hdr() and "hnew" not in hdr(), txt(hdr()))
cl(1); cl(2, outcome="dropped", reason="not needed any more")
check("an agent's close, done or dropped, is a record: uncleared, with the item's project, the outcome and who closed it", set(recs()) == {"a1", "a2"}
      and recs()["a1"]["outcome"] == "done" and recs()["a2"]["outcome"] == "dropped" and not recs()["a1"]["cleared"] and recs()["a1"]["project"] == "projects/alpha"
      and server._session_label(recs()["a1"]["by"]) == "work-osprey-x", recs())
cl(3, outcome="superseded", reason="replaced", superseded_by="a1")
check("a close to superseded makes no record", "a3" not in recs() and rd(3)["status"] == "completed", recs())
# Oliver's own closes: his answer on the board (author), and a write whose sender is he (the tools refuse that sender, a server path may write as him)
it4 = rd(4); it4["status"] = "completed"; it4["metadata"].update(outcome="dropped", reason="drop it"); it4["updated"] = it4["state_updated"] = time.time()
server._save("a4", it4, author=(server.OWNER, "board"))
it5 = rd(5); it5["status"] = "completed"; it5["metadata"].update(outcome="done", reason="he did it"); it5["updated"] = it5["state_updated"] = time.time()
server._save("a5", it5, writer="Oliver")
check("Oliver's own close makes no record, whether it is his board answer or a write whose sender is he", "a4" not in recs() and "a5" not in recs() and rd(4)["status"] == rd(5)["status"] == "completed", recs())
# the server's own close on a done check: a record with no closer
item(6, check="item_closed a1")
server._check_close("a6", server._load("a6"), "item_closed a1", time.time())
check("the server's own close on a done check is a record with no closer, shown as stackshot", "a6" in recs() and recs()["a6"]["by"] == "" and recs()["a6"]["outcome"] == "done", recs().get("a6"))
cl(9, sender="home-beta")
check("a close in another project is a record too", set(recs()) == {"a1", "a2", "a6", "a9"}, set(recs()))

# ---- 3. the count and the header
def page_lines(h=None): return len(re.findall(r'<li class="irow lrow"', h if h is not None else board().landed_html()))
def agree(label, expect=None):
    """the home header's count, the page's lines, the page's Clear buttons and the shared function are one number."""
    b_ = board(); ph_ = b_.landed_html(); hc = cards(hdr(b_))[-1][3]
    got = (hc, page_lines(ph_), ph_.count('class="lclear"'), len(b_.landed_rows()), b_.landed_count(), len(b_.landed_keys()))
    check(f"count = lines: {label}: header {got[0]}, page lines {got[1]}, Clear buttons {got[2]}" + (f", expected {expect}" if expect is not None else ""), len(set(got)) == 1 and (expect is None or got[0] == expect), got)
b = board()
check("the count is the uncleared records whose item is closed: 4", b.landed_count() == 4, b.landed_count())
h = hdr(b)
check("the header: the Closed card after Waiting, a card linking /closed in the same nav as the other count cards, its new badge reading 4",
      cards(h) == base(4, b) and '<i class="hnew">4<em> new</em></i>' in h and "4 new: closed by an agent, not cleared yet" in h
      and h.index("waiting-list") < h.index('href="/closed"'), h)
agree("four fresh closes", 4)
full = b.html()
check("…inside the live set's counts block (so the in-place update swaps it), in the header under the rendered line and above the search box, before the lists", full.index("<header") < full.index('<p class="rline">') < full.index('href="/closed"') < full.index('class="sbox"') < full.index("</header>") < full.index('<section id="your-move">')
      and "counts=" in re.search(r'<meta name="stackshot-blocks" content="([^"]*)">', full).group(1), None)
# the 60 days an uncleared record is kept: older than that it is neither counted nor listed; a cleared one never is
rec_old = dict(ld._load()["a2"])
d_ = ld._load(); d_["a2"]["ts"] = int(now0 - 15 * DAY); ld._save(d_)
check("an uncleared close 15 days old is still counted and listed: it stays until he clears it", board().landed_count() == 4 and "a2" in {r["gid"] for r, _ in board().landed_rows()}, board().landed_count())
agree("a 15-day-old uncleared close", 4)
d_ = ld._load(); d_["a2"]["ts"] = int(now0 - 59 * DAY); ld._save(d_)
check("…and so is one 59 days old", board().landed_count() == 4 and "a2" in {r["gid"] for r, _ in board().landed_rows()})
d_ = ld._load(); d_["a2"]["ts"] = int(now0 - 61 * DAY); ld._save(d_)
check("…an uncleared close past the 60 days a record is kept is neither counted nor listed (the bound)", board().landed_count() == 3 and "a2" not in {r["gid"] for r, _ in board().landed_rows()}, board().landed_count())
agree("a 61-day-old close", 3)
d_ = ld._load(); d_["a2"]["ts"] = rec_old["ts"]; ld._save(d_)
check("…back in its own time it counts again", board().landed_count() == 4)
d_ = ld._load(); d_["a2"]["cleared"] = now0; ld._save(d_)
check("a cleared close is neither counted nor listed", board().landed_count() == 3 and "a2" not in {r["gid"] for r, _ in board().landed_rows()})
d_ = ld._load(); d_["a2"]["cleared"] = 0; ld._save(d_)
it7 = rd(7); ld.record("a7", time.time(), "done", by=X, project="projects/alpha")      # a record whose item the store holds open (a missed reopen)
check("a record whose item is not closed in the store is neither counted nor listed", board().landed_count() == 4 and "a7" not in {r["gid"] for r, _ in board().landed_rows()})
agree("a record of an open item", 4)
ld.forget("a7")

# ---- 4. the page: grouping and order, with a fixture of known times
ld.clear(None)                           # a clean slate: the real closes above are cleared
for g in ("a1", "a2", "a6", "a9"): ld.forget(g)
def closed(i, su, project, subject, outcome="done", by=X, cleared=0.0, reason="r"):
    item(i, owner=A if project.endswith("alpha") else B, status="completed", su=su, project=project, subject=subject, outcome=outcome, reason=reason)
    ld.record(f"a{i}", su, outcome, by=by, project=project)
    if cleared: ld.clear([ld.key(f"a{i}", su)], now=cleared)
t0 = int(now0) - 3600
ZONE_HOURS = 4; ABBR = f"+{ZONE_HOURS:02d}"       # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST) and its own abbreviation
WHY = "PR 80 is live and the nightly run is green, so nothing is left to do here; a long reason that the home Completed rows would cut with an ellipsis too"
closed(20, t0 - 100, "projects/alpha", "[home] alpha newest", reason=WHY)
closed(21, t0 - 7200, "projects/alpha", "[home] alpha older", outcome="dropped", by=A, reason="not needed any more")
closed(22, t0 - 50, "projects/beta", "[home] beta newest overall", by=B, reason="shipped")
closed(23, t0 - 9000, "projects/beta", "[home] beta oldest", reason='a "quoted" <b>reason</b> & more')
closed(24, t0 - 3 * 3600, "projects/alpha", "[home] <b>escaped</b> & \"q\"")
closed(25, t0 - 20 * DAY, "projects/alpha", "[home] twenty days old and uncleared")
closed(26, t0 - 20 * DAY - 60, "projects/alpha", "[home] twenty days old and cleared", cleared=now0 - 100)
closed(27, t0 - 10, "projects/beta", "[home] cleared at once", cleared=now0 - 50)
b = board(); ph = b.landed_html()
order_ids = ids_of(ph)
heads = re.findall(r'<h3 class="iscope">([^<]*) <span class="count">(\d+)</span>', newsec(ph))
check("the New section groups by scope alone (Alpha is work's, Beta's is home: work first, the scopes in config order), each subsection newest first",
      heads == [("work", "4"), ("home", "2")] and [i.lstrip("a") for i in order_ids] == ["20", "21", "24", "25", "22", "23"], (heads, order_ids))
check("an uncleared close 20 days old is in the New section, and counted (agrees with the count); a cleared one of the same age is not, nor a cleared recent one",
      "twenty days old and uncleared" in newsec(ph) and "twenty days old and cleared" not in newsec(ph) and "cleared at once" not in newsec(ph) and "a26" not in newsec(ph) and "a27" not in newsec(ph), None)
lines = re.findall(r'<li class="irow lrow"[^>]*>.*?</li>', ph, re.S)
l22 = next(l for l in lines if "beta newest overall" in l); l21 = next(l for l in lines if "alpha older" in l); l20 = next(l for l in lines if "alpha newest" in l)
AGE = lambda ts: render.landed_ago(b.now.timestamp() - ts)
check("a line is the one row: the outcome tag and the title (the headline) with its relative close time beside it, the close reason under it, then Clear under the reason",
      l22.index('class="tag t-done"') < l22.index('class="ir-link"') < l22.index(" lago") < l22.index('class="ir-det"') < l22.index('class="lclear"') < l22.index("t-done") + len(l22)
      and re.search(r'<a class="ir-link" href="/items/\w*22"[^>]*><span class="ir-id">[^<]*22</span> <span class="hgoal">beta newest overall</span></a>', l22) and 'class="tag t-done"' in l22 and 'class="tag t-dropped"' in l21, (l22, l21))
check("…the row holds the number, the title, the outcome and the reason and nothing else: who closed it is not on the line (Oliver: he reads that on the item page)",
      "closed by" not in l22 and "lby" not in l22 and "home-beta" not in l22 and "work-osprey-main" not in l21, l22)
check("…the close time is relative, beside the title, with the exact time in the board's zone on hover, as the site's other ages are drawn (the tip with data-ts)",
      re.search(rf'<span class="tip ir-age lago" data-ts="{t0 - 50}" data-tip="{re.escape(b.when(t0 - 50))} {re.escape(ABBR)}" title="">{re.escape(AGE(t0 - 50))}</span>', l22)
      and re.search(rf'data-ts="{t0 - 7200}" data-tip="[^"]*" title="">3h ago</span>', l21) and l22.index('class="ir-link"') < l22.index(' lago"') < l22.index('class="ir-det"') and b.when(t0 - 50) not in txt(l22), l22)
check("…the hour in the hover is the hour in Asia/Dubai",
      re.search(rf'data-tip="[^"]*(\d\d:\d\d) {re.escape(ABBR)}"', l22).group(1) == time.strftime("%H:%M", time.gmtime(t0 - 50 + ZONE_HOURS * 3600)), l22)
check("the relative words: just now, Nm ago, Nh ago (to 48 h), Nd ago",
      [render.landed_ago(x) for x in (0, 59, 60, 12 * 60, 89 * 60 + 59, 90 * 60, 3 * 3600, 86399, 86400, 47 * 3600, 48 * 3600, 20 * 86400, -5)]
      == ["just now", "just now", "1m ago", "12m ago", "1h ago", "1h ago", "3h ago", "23h ago", "24h ago", "47h ago", "2d ago", "20d ago", "just now"])
CSS_ = b._css()
_cl = re.search(r"((?:li\.lrow\.lcleared \.ir-[a-z]+,?)+)\{([^}]*)\}", CSS_)
check("a cleared row dims whole: the cleared-row rule reaches the project line, the title line (with the age), the who line and the reason at .45, and not the actions (the Undo stays bright)",
      _cl and {x.replace("li.lrow.lcleared ", "") for x in _cl.group(1).split(",") if x} == {".ir-proj", ".ir-top", ".ir-who", ".ir-det"} and "opacity:.45" in _cl.group(2) and ".ir-act" not in _cl.group(1), _cl and _cl.group(0))
check("each line shows the close reason under the title in its own block, after the title and before Clear; wrapped, never cut with an ellipsis or held to one line, no title attribute",
      '<div class="ir-det">shipped</div>' in l22 and l22.index("beta newest overall") < l22.index('class="ir-det"') < l22.index('class="lclear"')
      and l21.count('class="ir-det"') == 1 and "not needed any more" in l21 and 'class="ir-det" title' not in ph
      and (m_ := re.search(r"\.ir-det\{margin-top:6px[^}]*\}", CSS_)) and "overflow-wrap:anywhere" in m_.group(0) and "ellipsis" not in m_.group(0) and "nowrap" not in m_.group(0) and "overflow:hidden" not in m_.group(0), l22)
check("…the long reason is whole in the line, escaped; one with quotes and tags is escaped", f'<div class="ir-det">{WHY}</div>' in l20
      and '<div class="ir-det">a &quot;quoted&quot; &lt;b&gt;reason&lt;/b&gt; &amp; more</div>' in ph and "<b>reason</b>" not in ph)
check("the subject is escaped on the page", "&lt;b&gt;escaped&lt;/b&gt; &amp;" in ph and "<b>escaped</b>" not in ph)
check("there is no per-line `new` tag and no seen state on the page any more", "Mark all seen" not in ph and ">new<" not in ph and not re.search(r'<li class="[^"]*\bnew\b', ph))
KEYS = {ld.key(f"a{i}", ts) for i, ts in ((20, t0 - 100), (21, t0 - 7200), (22, t0 - 50), (23, t0 - 9000), (24, t0 - 3 * 3600), (25, t0 - 20 * DAY))}
top = re.search(r'<form class="lmark" method="post" action="/landed/clear"><input type="hidden" name="keys" value="([^"]*)"><button type="submit" class="b">Clear all</button></form>', ph)
check("Clear all is at the top, above the list: after the note, before the first subsection; its form carries the keys of the lines on the page (and no more)",
      top and set(top.group(1).split(",")) == KEYS and ph.index('class="lnote"') < ph.index('class="lmark"') < ph.index('class="fold sfold hscope"') and ph.count('class="lmark"') == 1, ph[:200])
per = re.findall(r'<form class="lclear" method="post" action="/landed/clear"><input type="hidden" name="keys" value="([^"]*)"><button type="submit" class="b" aria-label="Clear (a?\d+)">Clear</button></form>', ph)
check("every line has its own Clear button posting that close's key alone", len(per) == 6 and {k for k, _i in per} == KEYS and all("," not in k for k, _i in per)
, per)
check("the CSS gives Clear all and Clear the one 32 px button look, with no size classes", re.search(r"\.b\{[^}]*min-height:32px", b._css()) and ".b.sm" not in b._css() and "form.lmark .abtn" not in b._css())
check("mark=False draws no buttons and no Clear all", 'class="lclear"' not in b.landed_html(mark=False) and 'class="lmark"' not in b.landed_html(mark=False) and page_lines(b.landed_html(mark=False)) == 6)
check("the note says what is shown and that an entry stays until cleared", "6 closes by agents" in ph and "stays here until you clear it" in ph, txt(ph)[:300])
agree("mixed data: 6 listed, 2 cleared, 1 past the window not made", 6)

# ---- 4b. one foldable subsection per scope, as on home: work, home and ops are the subsections, in sala's sidebar order; a row names no project
SUB_H = r'<details class="fold sfold hscope" data-fold="([^"]+)" open><summary><h3 class="iscope">([^<]*) <span class="count">(\d+)</span></h3></summary>(.*?)</ul></details>'
def scope_tree(h, sec=None):
    """The New section as a tree: [(scope, count, [ids])], read in document order from the subsections and the lines."""
    return [(m.group(2), int(m.group(3)), [i.lstrip("a") for i in ids_of(m.group(4))]) for m in re.finditer(SUB_H, sec if sec is not None else newsec(h), re.S)]
def whos(h): return {i.lstrip("a"): txt(w) for i, w in re.findall(r'<a class="ir-link" href="/items/(a?\d+)".*?(?:<div class="ir-who">(.*?)</div>)?<div class="ir-det"', newsec(h), re.S)}
check("the scope comes from the project (projects.py, as sala's sidebar takes it), not from the subject: Alpha's agents are work-..., so its four [home] items sit under work and Beta's two (home-...) under home, the scopes in [project_scopes] order",
      scope_tree(ph) == [("work", 4, ["20", "21", "24", "25"]), ("home", 2, ["22", "23"])], scope_tree(ph))
def compl(h): return h[h.find('<section id="completed"'):]      # the Last 14 days section, below the New section
_bq = board(); _bq.proj_title = lambda k: 'A<b>&"x'; _bq_html = _bq.landed_html()
_rows_new = re.findall(r'<li class="irow lrow"[^>]*>.*?</li>', newsec(_bq_html), re.S); _rows_done = re.findall(r'<li class="irow"[^>]*>.*?</li>', compl(_bq_html), re.S)
_PJ = lambda l: re.search(r'<div class="ir-proj">(.*?)</div>', l)
check("every row of the Closed page names its project in a small line above the title, New rows and Last 14 days rows alike: a link to the project's page with the project's name (escaped), before the title line, and no who line",
      len(_rows_new) == 6 and len(_rows_done) >= 6 and all(_PJ(l) and 'A&lt;b&gt;&amp;&quot;x' in _PJ(l).group(1) and re.fullmatch(r'<a class="pjl" href="/projects/(alpha|beta)">A&lt;b&gt;&amp;&quot;x</a>', _PJ(l).group(1))
                                                         and l.index('class="ir-proj"') < l.index('class="ir-top"') and 'ir-who' not in l and 'A<b>' not in l for l in _rows_new + _rows_done)
      and not hasattr(_bq, "closed_who"), (len(_rows_new), len(_rows_done), _rows_done[:1]))
check("...with the real names: the line reads Alpha or Beta behind its scope (as the projects are titled) and links the project's page, on the New rows and on the Last 14 days rows",
      {m.group(1) for l in re.findall(r'<li class="irow[^"]*"[^>]*>.*?</li>', ph, re.S) for m in [re.search(r'<a class="pjl" href="/projects/(alpha|beta)">(?:home|work|ops)/(Alpha|Beta)</a>', l)] if m} == {"alpha", "beta"}
      and all(re.search(r'<a class="pjl" href="/projects/(alpha|beta)">(?:home|work|ops)/(Alpha|Beta)</a>', l) for l in re.findall(r'<li class="irow[^"]*"[^>]*>.*?</li>', ph, re.S)), None)
check("...the card's edge: a New row has the green New edge (data-st=new), a Last 14 days row the plain edge (no data-st)",
      all('data-st="new"' in l.split(">")[0] + ">" for l in _rows_new) and all("data-st" not in l.split(">")[0] for l in _rows_done), (_rows_new[0][:160], _rows_done[0][:160]))
check("...a project's own page leaves the project line out (it says the project) and still gives its sub-page row a who line (done_row's `sub`), so the line is the Closed page's alone",
      '<div class="ir-who">sub page</div>' in board().done_row(next(r for r in board().rows if r["gid"] == "a20"), sub="sub page") and 'ir-who' not in board().done_row(next(r for r in board().rows if r["gid"] == "a20"))
      and 'ir-proj' not in board().done_row(next(r for r in board().rows if r["gid"] == "a20")) and 'ir-proj' in board().done_row(next(r for r in board().rows if r["gid"] == "a20"), named=True))
from stackshot.projects import projects as prj
check("the page's scope for a project is projects.py's: derive_scope for the page, the picker's order", prj.scopes() == ["work", "home", "ops"] and [board().landed_scope(k)[0] for k in ("projects/alpha", "projects/beta", "ops/gamma", "")] == ["work", "home", "ops", "home"])
reg = json.loads((T / "store/projects.json").read_text()); reg["pages"]["ops/gamma"] = page_entry("gamma", ["ops-gamma-main"]); reg["pages"]["projects/delta"] = page_entry("delta", ["home-delta"])
(T / "store/projects.json").write_text(json.dumps(reg))
MIX = {30: ("ops/gamma", "[home] gamma in the ops scope", t0 - 5000), 31: ("projects/delta", "[work] delta newest, an home project", t0 - 10), 32: ("", "[home] a close with no project", t0 - 9182)}
for i, (pj, sj, ts) in MIX.items(): closed(i, ts, pj, sj)
b = board(); pm = b.landed_html(); tree = scope_tree(pm)
check("mixed scopes: three subsections in the order work, home, ops; each close under its project's scope, newest first inside a scope whatever its project (home: Delta's 31 is the newest, then Beta's 22 and 23, the close with no project 32 last)",
      tree == [("work", 4, ["20", "21", "24", "25"]), ("home", 4, ["31", "22", "23", "32"]), ("ops", 1, ["30"])], tree)
check("...the item with a [work] subject in an home project did not move to work; a close with no project sits in the default scope (home); no row has a who line",
      "31" in tree[1][2] and all(not v for v in whos(pm).values()) and len(whos(pm)) == 9, whos(pm))
check("...the counts add up: the subsection counts, the lines under them and the Clear buttons are the count: 9",
      all(n == len(ids) for _sc, n, ids in tree) and sum(n for _sc, n, _p in tree) == 9 and page_lines(pm) == 9 and pm.count('class="lclear"') == 9, tree)
check("...heading order in the document is the scopes only: work, home, ops (no project headings, no h2 per scope)",
      re.findall(r'<h3 class="iscope">([^<]*) <span', newsec(pm)) == ["work", "home", "ops"] and 'lscopehd' not in pm and 'class="lgroup"' not in pm, None)
check("...the subject's scope prefix is not repeated on the lines (the heading says it); Clear all carries all 9 keys; the note counts 9",
      "[work]" not in pm and "[home]" not in pm and len(re.search(r'<form class="lmark"[^>]*><input type="hidden" name="keys" value="([^"]*)"', pm).group(1).split(",")) == 9 and "9 closes by agents" in pm, txt(pm)[:200])
agree("mixed scopes: 9 listed under three subsections", 9)
# the subsections fold like home's (one shared helper, ui/groups.py): native details, open by default, the count in the summary, a key of their own
subsK = re.findall(r'<details class="fold sfold hscope" data-fold="([^"]+)"( open)?><summary><h3 class="iscope">', newsec(pm))
check("the New subsections are native details.fold with the h3.iscope in the summary, open by default, one data-fold key each (closed.new.<scope>), the page's script keeps no fold state",
      subsK == [("closed.new.work", " open"), ("closed.new.home", " open"), ("closed.new.ops", " open")] and "setItem" not in render._HOME_FOLD_JS, subsK)
# the same markup and the same grouping as home's lists: the Closed page calls the Board's shared scope_sections, so a row's scope, the order and the count come from one place
shared = b.scope_sections("x", [(None, r) for r in b.rows if r["gid"] in ("a20", "a31", "a30", "a22")], lambda pr: "<li></li>", row=lambda pr: pr[1])
check("the Closed page's grouping is Board.scope_sections, the one home's lists call (same order: work, home, ops; same summary form)",
      re.findall(r'<h3 class="iscope">([^<]*) <span class="count">(\d+)</span>', shared) == [("work", "1"), ("home", "2"), ("ops", "1")], shared[:300])
# a live count: the page script counts the live lines of each subsection (a cleared line stays dimmed and is not counted)
check("the page script updates a subsection's count from its live lines (details.hscope inside the New section), not an old per-project or per-scope heading",
      "#new details.hscope" in render._LANDED_JS and "section.lgroup" not in render._LANDED_JS and "section.lscope" not in render._LANDED_JS)
# the board item: clearing a line never moves a subsection and an Undo puts the same page back
def shape(h): return [(sc, ids) for sc, _n, ids in scope_tree(h)]
orig = shape(pm); KEY9 = {f"a{i}": ld.key(f"a{i}", r["ts"]) for i, r in ((int(g[1:]), r) for g, r in recs().items())}
moved = []
for gid_, k_ in sorted(KEY9.items()):
    n_ = ld.clear([k_]); got_ = shape(board().landed_html())
    want_ = [(sc, [i for i in ids if i != gid_.lstrip("a")]) for sc, ids in orig]; want_ = [(sc, ids) for sc, ids in want_ if ids]       # only that line leaves; a scope with no line left leaves with it
    if n_ != 1 or got_ != want_: moved.append((gid_, got_))
    back_ = ld.unclear([k_])
    if back_ != 1 or scope_tree(board().landed_html()) != scope_tree(pm): moved.append((gid_, "undo", scope_tree(board().landed_html())))
check("clearing any one of the nine lines moves no subsection (the others keep their order; a scope whose only line it was leaves), and an Undo of it puts the very same page back", moved == [], moved)
check("the scopes keep their order (work, home, ops) and the lines of a scope their close order", orig == [("work", ["20", "21", "24", "25"]), ("home", ["31", "22", "23", "32"]), ("ops", ["30"])], orig)
pid = prj.ensure_ids(["projects/delta"])["projects/delta"]; prj.set_mark(pid, scope="ops")
tree2 = scope_tree(board().landed_html())
check("a scope set on purpose for the page (its mark) wins over the derived one, as in the picker: Delta's 31 moves under ops, ahead of Gamma's 30 (newer close); the page still has 9 lines",
      [(sc, n) for sc, n, _p in tree2] == [("work", 4), ("home", 3), ("ops", 2)] and tree2[2][2] == ["31", "30"] and page_lines() == 9, tree2)
prj.set_mark(pid, scope=None)
hs = re.search(r"\.hscope h3\.iscope\{[^}]*\}", b._css()).group(0)
check("the headings stay readable at 360 px: the subsection heading wraps anywhere, has no nowrap; the old per-scope and per-project heading styles are gone",
      "overflow-wrap:anywhere" in hs and "nowrap" not in hs and "lscopehd" not in b._css() and "section.lgroup" not in b._css())
WORK4 = ((20, t0 - 100), (21, t0 - 7200), (24, t0 - 3 * 3600), (25, t0 - 20 * DAY))
check("a scope with no close is left out (no empty heading): clearing work's four leaves home and ops",
      (ld.clear([ld.key(f"a{i}", ts) for i, ts in WORK4], now=now0), [sc for sc, _n, _p in scope_tree(board().landed_html())])[1] == ["home", "ops"])
for i in MIX: ld.forget(f"a{i}"); (T / f"store/a/{i}.json").unlink()
for i, ts in WORK4: d_ = ld._load(); d_[f"a{i}"]["cleared"] = 0.0; ld._save(d_)
check("(cleanup of the mixed-scope fixtures) the page is back to the six lines: work's four and home's two", page_lines() == 6 and [(sc, n) for sc, n, _p in scope_tree(board().landed_html())] == [("work", 4), ("home", 2)])

# ---- 5. clear: opening the page clears nothing; Clear; Clear all
COOKIE = server._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
SAME = {"Origin": BOARD}
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def get(path, cookie=COOKIE):
        c.cookies.clear()
        if cookie: c.cookies.set(server._UI_COOKIE, cookie)
        return c.get(path, follow_redirects=False)
    def post(path, data, headers=SAME, cookie=COOKIE):
        c.cookies.clear()
        if cookie: c.cookies.set(server._UI_COOKIE, cookie)
        return c.post(path, data=data, headers=headers, follow_redirects=False)
    os.environ["STACKSHOT_AUTH"] = "oauth"
    try:
        anon = get("/closed", cookie=None); anon_post = post("/landed/clear", {"keys": ",".join(KEYS)}, cookie=None); anon_old = post("/landed/seen", {"keys": ",".join(KEYS)}, cookie=None)
    finally: os.environ["STACKSHOT_AUTH"] = "off"
    check("behind the board's sign-in: a visitor not signed in is sent to the login (the page) and refused (both buttons, and the old route), and nothing is cleared", anon.status_code == 302 and "/ui/login" in anon.headers["location"]
          and anon_post.status_code == 403 and anon_old.status_code == 403 and board().landed_count() == 6, (anon.status_code, anon_post.status_code, anon_old.status_code))
    p0 = pub[0]
    g = get("/closed")
    check("opening the page: 200, no-store, every entry listed", g.status_code == 200 and g.headers["cache-control"] == "no-store" and page_lines(g.text) == 6 and "<h1>Closed</h1>" in g.text, (g.status_code, g.headers.get("cache-control")))
    check("…and it cleared nothing: the count is still 6, nothing is republished, the header still reads 6", board().landed_count() == 6 and pub[0] == p0 and cards() == base(6), (board().landed_count(), pub[0] - p0))
    g2 = get("/closed"); get("/closed")
    check("opening it again, and again: the same six lines, the same count", page_lines(g2.text) == 6 and board().landed_count() == 6 and pub[0] == p0)
    agree("after opening the page three times", 6)
    # a single Clear
    ev = post("/landed/clear", {"keys": ld.key("a22", t0 - 50)}, headers={"Origin": "https://evil.example.net"})
    check("Clear from a foreign origin is refused (403); nothing is cleared", ev.status_code == 403 and board().landed_count() == 6)
    p1 = pub[0]
    one = post("/landed/clear", {"keys": ld.key("a22", t0 - 50)})
    check("Clear on one line: 303 back to /landed, that one entry is gone from the page and the count (5), the board is republished", one.status_code == 303 and one.headers["location"] == "/closed"
          and board().landed_count() == 5 and "a22" not in {r["gid"] for r, _ in board().landed_rows()} and "beta newest overall" not in newsec(board().landed_html()) and pub[0] == p1 + 1, (one.status_code, board().landed_count()))
    check("…the header reads 5 and the Clear all form no longer carries the cleared key", cards() == base(5) and ld.key("a22", t0 - 50) not in re.search(r'class="lmark".*?value="([^"]*)"', board().landed_html()).group(1))
    agree("after a single Clear", 5)
    again = post("/landed/clear", {"keys": ld.key("a22", t0 - 50)})
    check("…clearing it again clears nothing and republishes nothing", again.status_code == 303 and board().landed_count() == 5 and pub[0] == p1 + 1)

    # Undo, the page's fetch path (Accept: application/json), and the gates on the new route
    JS = {**SAME, "Accept": "application/json"}; k22 = ld.key("a22", t0 - 50); k20 = ld.key("a20", t0 - 100)
    ids_all = [i.lstrip("a") for i in ids_of(ph)]
    ids_now = [i.lstrip("a") for i in ids_of(board().landed_html())]
    check("the cleared line left the page and every other line kept its place (the order is the earlier one minus a22)", ids_now == [i for i in ids_all if i != "22"], (ids_all, ids_now))
    pu0 = pub[0]
    un = post("/landed/unclear", {"keys": k22})
    check("Undo from the form (no JavaScript): 303 back to /landed, the line is back in the very place it had, the count is 6, the board is republished",
          un.status_code == 303 and un.headers["location"] == "/closed" and board().landed_count() == 6 and pub[0] == pu0 + 1
          and [i.lstrip("a") for i in ids_of(board().landed_html())] == ids_all, (un.status_code, board().landed_count()))
    agree("after an Undo", 6)
    check("…the header reads 6 again", cards() == base(6))
    j1 = post("/landed/clear", {"keys": k20}, headers=JS)
    check("Clear through the page's script: 200 JSON {ok, changed: 1}, no redirect, no-store; the count is 5 and the board is republished",
          j1.status_code == 200 and j1.json() == {"ok": True, "changed": 1} and j1.headers["cache-control"] == "no-store" and board().landed_count() == 5 and pub[0] == pu0 + 2, (j1.status_code, j1.text))
    j1b = post("/landed/clear", {"keys": k20}, headers=JS)
    check("…the same Clear again: 200, changed 0, nothing republished", j1b.status_code == 200 and j1b.json() == {"ok": True, "changed": 0} and pub[0] == pu0 + 2)
    agree("after a Clear through the script", 5)
    j2 = post("/landed/unclear", {"keys": k20}, headers=JS)
    check("Undo through the page's script: 200 JSON changed 1, the count is 6 again, republished", j2.status_code == 200 and j2.json() == {"ok": True, "changed": 1} and board().landed_count() == 6 and pub[0] == pu0 + 3, (j2.status_code, j2.text))
    agree("after an Undo through the script", 6)
    pu1 = pub[0]
    nops = [post("/landed/unclear", {"keys": k}, headers=JS) for k in (k20, "nope:1", "", ld.key("a20", t0 - 99), "a20")]
    check("Undo of a line that is not cleared, of an unknown key, of no key, of another close of the item, of a bare id: changed 0 each, nothing republished, the count is still 6",
          all(r.status_code == 200 and r.json() == {"ok": True, "changed": 0} for r in nops) and pub[0] == pu1 and board().landed_count() == 6, [r.text for r in nops])
    # a cleared close older than the 60 days is not restored
    d_ = ld._load(); d_["a25"]["ts"] = int(time.time() - 61 * DAY); d_["a25"]["cleared"] = time.time() - 5; ld._save(d_)
    old_ = post("/landed/unclear", {"keys": ld.key("a25", d_["a25"]["ts"])}, headers=JS)
    check("Undo of a cleared close past the 60 days restores nothing (changed 0, still cleared)", old_.json() == {"ok": True, "changed": 0} and ld._load()["a25"]["cleared"] > 0 and pub[0] == pu1, old_.text)
    d_ = ld._load(); d_["a25"]["ts"] = t0 - 20 * DAY; d_["a25"]["cleared"] = 0.0; ld._save(d_)
    # Clear all, then Undo of each line: the same page
    keys_all = re.search(r'name="keys" value="([^"]*)"', board().landed_html()).group(1)
    ca = post("/landed/clear", {"keys": keys_all}, headers=JS)
    check("Clear all through the script: changed 6, the count is 0 (the page is the server's; its script keeps the lines in place)", ca.json() == {"ok": True, "changed": 6} and board().landed_count() == 0 and page_lines() == 0)
    agree("after Clear all through the script", 0)
    ua = post("/landed/unclear", {"keys": keys_all}, headers=JS)
    check("…Undo with all six keys (the script sends one line's key; this is the same route with many): changed 6, the count is 6, the page is as it was",
          ua.json() == {"ok": True, "changed": 6} and board().landed_count() == 6 and [i.lstrip("a") for i in ids_of(board().landed_html())] == ids_all)
    agree("after Undo of all", 6)
    # the gates of the new route: those of Clear
    os.environ["STACKSHOT_AUTH"] = "oauth"
    try: anon_un = post("/landed/unclear", {"keys": k22}, cookie=None, headers=JS)
    finally: os.environ["STACKSHOT_AUTH"] = "off"
    ld.clear([k22]); pu2 = pub[0]
    evil_un = post("/landed/unclear", {"keys": k22}, headers={"Origin": "https://evil.example.net", "Accept": "application/json"})
    bare_un = post("/landed/unclear", {"keys": k22}, headers={"Accept": "application/json"})
    big_un = post("/landed/unclear", {"keys": "x" * 70000}, headers=JS)
    check("Undo has Clear's gates: not signed in 403, a foreign origin 403, no origin 403, a body over 64 KB 413; none of them restores anything",
          (anon_un.status_code, evil_un.status_code, bare_un.status_code, big_un.status_code) == (403, 403, 403, 413) and ld._load()["a22"]["cleared"] > 0 and board().landed_count() == 5 and pub[0] == pu2,
          (anon_un.status_code, evil_un.status_code, bare_un.status_code, big_un.status_code))
    big_cl = post("/landed/clear", {"keys": "x" * 70000}, headers=JS)
    check("…and Clear keeps its 64 KB cap too (413)", big_cl.status_code == 413)
    agree("(Undo gates over) a22 cleared again, as before this block", 5)
    pg_ = get("/closed")
    check("the page carries its script: relative times redraw, Clear and Undo go through fetch, with the form post as the fallback; it inserts no HTML",
          "<script>(function(){var M=document.querySelector('main#top')" in pg_.text and "/landed/unclear" in pg_.text and "fetch(f.action" in pg_.text and "innerHTML" not in render._LANDED_JS and "insertAdjacentHTML" not in render._LANDED_JS
          and "outerHTML" not in render._LANDED_JS and "document.write" not in render._LANDED_JS and "textContent" in render._LANDED_JS and 'f.method=' in render._LANDED_JS)
    # a close that lands after a page was drawn is not cleared by that page's Clear all
    b_ = board(); keys_ = b_.landed_keys()
    cl(8, sender="work-osprey-x", reason="landed after the page was drawn")
    n_ = ld.clear(keys_)
    check("Clear all with the keys a page was drawn with clears those and not a close that landed after it was drawn", n_ == 5 and board().landed_count() == 1 and "a8" in recs() and not recs()["a8"]["cleared"], (n_, recs().keys()))
    check("…the header counts it: 1 new", cards() == base(1), txt(hdr()))
    agree("a close after the page was drawn", 1)
    # put the fixture back to six for the Clear all route
    for i, ts in ((20, t0 - 100), (21, t0 - 7200), (22, t0 - 50), (23, t0 - 9000), (24, t0 - 3 * 3600), (25, t0 - 20 * DAY)):
        d_ = ld._load(); d_[f"a{i}"]["cleared"] = 0.0; ld._save(d_)
    agree("six uncleared and one landed after: seven", 7)
    keys_html = re.search(r'name="keys" value="([^"]*)"', board().landed_html()).group(1)
    p2 = pub[0]
    ok = post("/landed/clear", {"keys": keys_html})
    check("Clear all: 303 back to /landed, every entry on the page is gone, the count is 0, the board is republished", ok.status_code == 303 and ok.headers["location"] == "/closed" and board().landed_count() == 0 and page_lines() == 0 and pub[0] == p2 + 1, (ok.status_code, ok.headers.get("location")))
    check("…the header reads no new badge and still links the page; the page says nothing is waiting and draws no Clear all", cards() == base(0) and "hnew" not in hdr() and "Nothing an agent closed is waiting here" in board().landed_html() and 'class="lmark"' not in board().landed_html())
    agree("after Clear all", 0)
    none_ = post("/landed/clear", {"keys": ""})
    check("…no keys clears nothing (it is not a clear-everything button)", none_.status_code == 303)
    # the old route still clears
    cl(7, sender="work-osprey-x", reason="old route"); k1 = ld.key("a7", recs()["a7"]["ts"])
    check("a new close is on the list again", board().landed_count() == 1)
    old = post("/landed/seen", {"keys": k1})
    check("the old /landed/seen route (a page open from before) still works: it clears the keys it carries", old.status_code == 303 and old.headers["location"] == "/closed" and board().landed_count() == 0)

    # ---- 6. a reopened item that closes again counts as a new close
    cl(10, sender="home-beta", reason="first close")
    ld.clear(None)
    check("an item closed once and cleared: not counted", board().landed_count() == 0 and recs() == {} and ld._load()["a10"]["cleared"] > 0)
    server.stackshot_update("a10", status="open", sender="home-beta", description="- Goal: A thing\n- It lives here\n- Finished when it really works", next="home-beta: look at it again")
    check("a reopen takes the item's record off: it has not landed (any more), and the page does not list it", rd(10)["status"] == "open" and "a10" not in ld._load()
          and "a10" not in {r["gid"] for r, _ in board().landed_rows()}, ld._load().keys())
    time.sleep(1.1)       # the close's clock is whole seconds: a second close in the same second would be the same close
    cl(10, sender="home-beta", reason="second close")
    check("…and its next close is a new record, uncleared, though the first one was cleared: the count is 1 again", recs()["a10"]["cleared"] == 0 and board().landed_count() == 1 and '<i class="hnew">1<em> new</em></i>' in hdr(), recs().get("a10"))
    check("…one line for the item on the page, not one per close", board().landed_html().count('href="/items/a10"') == 2 and page_lines() == len(board().landed_rows()) == 1)
    agree("a reopened and re-closed item", 1)
    g3 = get("/closed")
    check("…opening the page does not clear it", board().landed_count() == 1 and cards() == base(1) and page_lines(g3.text) == 1)
    # a close by Oliver of an item an agent closed before and that was reopened: no record
    server.stackshot_update("a10", status="open", sender="home-beta", description="- Goal: A thing\n- It lives here\n- Finished when it is done for good", next="home-beta: once more")
    it10 = rd(10); it10["status"] = "completed"; it10["metadata"].update(outcome="done", reason="he closed it"); it10["updated"] = it10["state_updated"] = time.time()
    server._save("a10", it10, author=(server.OWNER, "board"))
    check("a close by Oliver after a reopen: no record, nothing on the page", "a10" not in recs() and board().landed_count() == 0)
    agree("a close by Oliver after a reopen", 0)

# ---- 7. the For you list is untouched
check("the For you list is still hidden and none of this made or took a row of it", render._SHOW_FOR_YOU is False and 'id="for-you"' not in board().html() and fy.rows() == [], fy.rows())


# every page's title bar is the home h1 (logo and title) as a link to "/", and the side panel stands on it, pinned by default as on home
def title_panel_problems(p):
    bad = []
    if re.findall(r'<(?:h1|p) class="site"><a href="([^"]*)"><img class="logo"', p) != ["/"]: bad.append("title link is not exactly one href=/")
    if "\u2190 " in p.split("</main>")[0][:3000] and 'class="topline"' in p: bad.append("the old back arrow is still there")
    for need in (render._PANEL_BODY + '<div id="layout">', '<aside id="panel"', 'id="panel-edge"', 'id="panel-scrim"', 'id="panel-open"', 'id="machines"', 'id="runners"', 'id="audit-panel"', render._PANEL_JS[:60]):
        if need not in p: bad.append("missing " + need)
    # the board item (Oliver): pinned by default, nothing remembered
    if '<body class="panel-pin">' not in p or 'aria-expanded="true" title="Hide summary panel"' not in p: bad.append("the panel does not render pinned")
    if "stackshot.panel" in p or "localStorage" in render._PANEL_JS: bad.append("the panel state is stored in the browser")
    if p.count('<nav class="hcards"') != 1 or '<a class="hcard call" href="/#your-move"' not in p: bad.append("the count cards are not on the page once, linking the home lists")
    if p.count('<aside id="panel"') != 1 or p.count("</div><script>") < 1: bad.append("panel not once / no script")
    return bad
check("title and panel: the Closed page has the home title as a link to / and the same side panel", title_panel_problems(board().landed_html()) == [], title_panel_problems(board().landed_html()))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
