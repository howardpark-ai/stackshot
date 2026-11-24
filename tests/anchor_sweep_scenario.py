"""Scenario test for anchors that end on their own (anchors/anchor_sweep.py): fixture data in a scratch folder, no live store, no network, no GitHub call, no server socket.

Four rules, each a small function with its own checks, then `sweep` over all of them:
  1. items  an entry scoped to items, every one closed, goes (whatever its kind); a project-wide entry never; one open item, an unreadable item, or an empty item store keeps it
  2. quiet  a merged or closed GitHub issue or pull request goes 14 days after its last activity: the boundary (13 days 23 hours stays, 14 days goes), a reopening and a new comment restart it,
            an entry added lately waits its own 14 days, an old or missing reader position removes nothing, an anchor an open item waits on is spared
  3. repo   an archived repository's anchors go (item-scoped ones too) once the reader has looked at the anchor since it marked the repository, an issue the reader found gone goes after a day
            (and the look after the mark); a young position only
  4. pages  every entry of a closed or archived page goes; an active page and a page the registry does not list keep theirs
and: every removal is a log-only line on the page's routing log with the call that puts the anchor back (scoped to the items still open, project-wide when all are closed; a call too long for the
log's 300 characters is whole in the state folder's record, and the line says where), a second sweep removes nothing, `rules=` runs only some, the closing reply lists what ended and a close ends
only the entries scoped to the item that closed, a reopening's reply names the restore call, the reader's accessor carries a per-anchor status; the store is read, changed and saved under the anchors
lock (an anchor added between the sweep's read and its save, or between its first read and the locked one, survives), an anchor an open item waits on is spared in every form of the anchor (a list
wait, an issue and a pull request of one number, /files, a #mention, the github: form, a held item the entry is scoped to) and a closed item's wait spares nothing, an item that cannot be read
(a missing folder, an unreadable alias map, an empty store) is unknown and keeps the entry, duplicate entries are removed one by one, and one tick removes at most [anchor_hub] sweep_per_tick.

    tests/run-suite anchor_sweep         → exit 0 / 1"""
import contextlib, io, json, os, pathlib, re, shutil, sys, threading, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="p1531a-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
sys.path.insert(0, STACK)

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.anchors import anchor_sweep as SW, anchors as ANC
from stackshot.fleet import inbox as _inbox
from stackshot.github import ghsync
from stackshot.router import routing

DAY = 86400.0
NOW = 1_800_000_000.0                                    # a fixed "now": every age below is a number of days before it
iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
P1, P2, P3 = "projects/alpha", "projects/beta", "projects/gamma"
PR = "https://github.com/o/r/pull/9"
ISSUE = "https://github.com/o/r/issues/4"
REL = "https://github.com/o/r/releases"
WIDE = "https://example.invalid/wide"
SLACK = "https://acme.slack.com/archives/C0000000001"
SOLO = "https://example.invalid/solo"
AID = lambda u: ANC.anchor_id(u)
sh = ghsync.shown

# the item store: a1 open, a2 completed, a3 open, a4 file gone (never made)
os.makedirs(T / "store/a", exist_ok=True)
def put_item(n, status="open", **meta):
    (T / f"store/a/{n}.json").write_text(json.dumps({"id": str(n), "subject": f"[home] item a{n}", "description": "- A thing, finished when it works", "status": status, "updated": 1.0,
                                                    "metadata": {"owner": "Oliver", "project": P1, **meta}}))
put_item(1); put_item(2, "completed"); put_item(3)
(T / "store/next-id").write_text("10")

def entry(url, items=None, added=1.0): return {"url": url, "items": items, "added": added, "by": "t"}
def set_store(d): ANC.save(d)
def get_store(): return json.loads((T / "store/anchors.json").read_text())
def urls(store, page): return [e["url"] for e in store.get(page, [])]
def lines(page): return [n for n in routing.read(page) if n.get("kind") == "anchor"]
def reader(state=None, looked=None, repos=None, gone=None, status=None, saved=NOW - 60):
    return SW.Reader({"github": {"state": state or {}, "looked": looked or {}}, "github_repos": {"archived": repos or {}, "gone": gone or {}}}, saved, {"anchors": status or {}})
def closed(updated): return {"state": "closed", "comments": 0, "updated": iso(updated), "pr": True, "merged": True}
def opened(updated): return {"state": "open", "comments": 0, "updated": iso(updated), "pr": True}
ALIVE = NOW - 600                                        # the reader looked at the anchor ten minutes ago

# ---------- rule 1: items ----------
st = {P1: [entry(SOLO, ["a2"]), entry("https://example.invalid/two", ["a2", "a4"]), entry("https://example.invalid/mixed", ["a2", "a1"]),
           entry(WIDE), entry("https://example.invalid/open", ["a3"]), entry("https://example.invalid/slackish", ["a2"])],
      P2: [entry(SLACK, ["a2"]), entry(PR, ["a2"])]}
h1 = SW.rule_items(st)
got = sorted((h.page, h.entry["url"]) for h in h1)
check("rule 1: an entry whose every item is closed or whose file is gone goes, whatever its kind (a Slack channel, a GitHub pull request, a plain url)",
      got == sorted([(P1, SOLO), (P1, "https://example.invalid/two"), (P1, "https://example.invalid/slackish"), (P2, SLACK), (P2, PR)]), got)
check("rule 1: a project-wide entry is never touched, and an entry with one open item among closed ones stays", all(h.entry["url"] not in (WIDE, "https://example.invalid/mixed", "https://example.invalid/open") for h in h1), got)
check("rule 1: the reason names the items", all("closed" in h.why and sh("a2") in h.why for h in h1) and all(h.rule == "items" for h in h1), [h.why for h in h1])
check("rule 1: an item that cannot be read keeps the entry (status 'unknown' is not 'closed')", SW.rule_items({P1: [entry(SOLO, ["a2", "a9"])]}, lambda g: {"a2": "closed"}.get(g, "unknown")) == [], "")
(T / "store/a/5.json").write_text("{not json")
check("rule 1: item_status: open, completed, a missing file, an unreadable file", [SW.item_status(g) for g in ("a1", "a2", "a4", "a5")] == ["open", "closed", "closed", "unknown"], [SW.item_status(g) for g in ("a1", "a2", "a4", "a5")])
(T / "store/a/5.json").unlink()

# ---------- rule 2: quiet ----------
aid_pr, aid_is = AID(PR), AID(ISSUE)
base = {P1: [entry(PR, None, 1.0), entry(ISSUE, ["a1"], 1.0), entry(WIDE)]}
def quiet(days, **kw):
    rd = reader({aid_pr: closed(NOW - days * DAY), aid_is: closed(NOW - days * DAY)}, {aid_pr: ALIVE, aid_is: ALIVE}, **kw)
    return sorted(h.entry["url"] for h in SW.rule_quiet(base, rd, NOW))
check("rule 2: a merged or closed GitHub anchor goes at 14 days of no activity, project-wide or scoped to an open item alike", quiet(14) == sorted([PR, ISSUE]), quiet(14))
check("rule 2: ...and not a second sooner: 13 days 23 hours 59 minutes stays", quiet(14 - 1 / 1440) == [] and quiet(13) == [], (quiet(14 - 1 / 1440), quiet(13)))
check("rule 2: a project-wide non-GitHub entry never goes by this rule", WIDE not in quiet(400), quiet(400))
check("rule 2: a reopened one (the reader saved it open) stays however old", [h for h in SW.rule_quiet(base, reader({aid_pr: opened(NOW - 90 * DAY), aid_is: opened(NOW - 90 * DAY)}, {aid_pr: ALIVE, aid_is: ALIVE}), NOW)] == [], "")
check("rule 2: a new comment moves its `updated` and restarts the 14 days: closed 30 days ago, a comment 3 days ago, stays",
      SW.rule_quiet(base, reader({aid_pr: {**closed(NOW - 30 * DAY), "updated": iso(NOW - 3 * DAY)}}, {aid_pr: ALIVE}), NOW) == [], "")
check("rule 2: a reopening and a new close: the clock is the new `updated` (closed again 2 days ago stays; closed 15 days ago goes)",
      SW.rule_quiet(base, reader({aid_pr: closed(NOW - 2 * DAY)}, {aid_pr: ALIVE}), NOW) == [] and len(SW.rule_quiet(base, reader({aid_pr: closed(NOW - 15 * DAY)}, {aid_pr: ALIVE}), NOW)) == 1, "")
check("rule 2: an entry added 3 days ago for a long-closed pull request waits its own 14 days from the day it was added",
      SW.rule_quiet({P1: [entry(PR, None, NOW - 3 * DAY)]}, reader({aid_pr: closed(NOW - 90 * DAY)}, {aid_pr: ALIVE}), NOW) == []
      and len(SW.rule_quiet({P1: [entry(PR, None, NOW - 15 * DAY)]}, reader({aid_pr: closed(NOW - 90 * DAY)}, {aid_pr: ALIVE}), NOW)) == 1, "")
check("rule 2: a position older than 6 hours, a missing position, an anchor the reader has not looked at lately, and one it has no state for remove nothing",
      SW.rule_quiet(base, reader({aid_pr: closed(NOW - 90 * DAY)}, {aid_pr: ALIVE}, saved=NOW - 7 * 3600), NOW) == []
      and SW.rule_quiet(base, SW.Reader({}, None, {}), NOW) == []
      and SW.rule_quiet(base, reader({aid_pr: closed(NOW - 90 * DAY)}, {aid_pr: NOW - 2 * DAY}), NOW) == []
      and SW.rule_quiet(base, reader({}, {}), NOW) == [], "")
check("rule 2: a releases feed or a repo root is never 'finished'", SW.rule_quiet({P1: [entry(REL)]}, reader({AID(REL): closed(NOW - 90 * DAY)}, {AID(REL): ALIVE}), NOW) == [], "")
wait_spared = lambda p, e: e["url"] == PR
check("rule 2: an anchor an open item waits on is spared (the `spared` test)", [h.entry["url"] for h in SW.rule_quiet(base, reader({aid_pr: closed(NOW - 90 * DAY), aid_is: closed(NOW - 90 * DAY)}, {aid_pr: ALIVE, aid_is: ALIVE}), NOW, wait_spared)] == [ISSUE], "")

# ---------- rule 3: repo ----------
rbase = {P1: [entry(PR, ["a1"]), entry(REL), entry("https://github.com/o/r"), entry("https://github.com/x/y/pull/1"), entry(SLACK)]}
RLOOK = {aid_pr: ALIVE, AID(REL): ALIVE, AID("https://github.com/o/r"): ALIVE}      # the reader looked at each of them ten minutes ago
rd = reader({aid_pr: opened(NOW)}, RLOOK, repos={"o/r": NOW - 3600})
got = sorted(h.entry["url"] for h in SW.rule_repo(rbase, rd, NOW))
check("rule 3: every GitHub anchor on an archived repository goes, an item-scoped one too; another repository's and a Slack channel stay", got == sorted([PR, REL, "https://github.com/o/r"]), got)
check("rule 3: ...but only once the reader looked at the anchor itself after it marked the repository: a new anchor on a repository marked an hour ago, looked at before the mark or never, stays",
      [h.entry["url"] for h in SW.rule_repo(rbase, reader({aid_pr: opened(NOW)}, {aid_pr: NOW - 7200, AID(REL): NOW - 1800}, repos={"o/r": NOW - 3600}), NOW)] == [REL]
      and SW.rule_repo(rbase, reader({aid_pr: opened(NOW)}, {}, repos={"o/r": NOW - 3600}), NOW) == []
      and [h.entry["url"] for h in SW.rule_repo(rbase, reader({aid_pr: opened(NOW)}, {aid_pr: NOW}, repos={"o/r": NOW - 3600}), NOW)] == [PR], "")
check("rule 3: ...and the look must be lately: one older than 6 hours is no confirmation, even after the mark",
      SW.rule_repo({P1: [entry(PR)]}, reader({aid_pr: opened(NOW)}, {aid_pr: NOW - 7 * 3600}, repos={"o/r": NOW - 8 * 3600}), NOW) == [], "")
gone = reader({aid_pr: opened(NOW)}, {aid_pr: ALIVE}, gone={aid_pr: NOW - SW.GONE_S})
check("rule 3: an issue or pull request whose read answered 'not found' for a day goes; 23 hours is not yet", [h.entry["url"] for h in SW.rule_repo(rbase, gone, NOW)] == [PR]
      and SW.rule_repo(rbase, reader({aid_pr: opened(NOW)}, {aid_pr: ALIVE}, gone={aid_pr: NOW - 23 * 3600}), NOW) == [], "")
check("rule 3: ...and only when the reader looked at it after it first answered 'not found'", SW.rule_repo(rbase, reader({aid_pr: opened(NOW)}, {aid_pr: NOW - 2 * DAY}, gone={aid_pr: NOW - SW.GONE_S}), NOW) == [], "")
check("rule 3: 'gone' needs a read before it (a state saved): an anchor never read is not 'gone'", SW.rule_repo(rbase, reader({}, {}, gone={aid_pr: NOW - 5 * DAY}), NOW) == [], "")
check("rule 3: a position older than 6 hours or missing removes nothing", SW.rule_repo(rbase, reader({aid_pr: opened(NOW)}, {aid_pr: ALIVE}, repos={"o/r": NOW - 3600}, saved=NOW - 8 * 3600), NOW) == []
      and SW.rule_repo(rbase, SW.Reader(None, None, None), NOW) == [], "")
check("rule 3: the repository's name is read case-blind", len(SW.rule_repo({P1: [entry("https://github.com/O/R/pull/9")]}, reader({}, {AID("https://github.com/O/R/pull/9"): ALIVE}, repos={"o/r": NOW - 3600}), NOW)) == 1, "")

# ---------- rule 4: pages ----------
reg = {P1: {"status": "archived"}, P2: {"status": "Closed "}, P3: {"status": "active"}}
pst = {P1: [entry(SOLO, ["a1"]), entry(WIDE)], P2: [entry(PR)], P3: [entry(SLACK)], "projects/unlisted": [entry(SLACK)]}
got = sorted((h.page, h.entry["url"]) for h in SW.rule_pages(pst, reg))
check("rule 4: every entry of an archived or closed page goes, item-scoped and project-wide; an active page and an unlisted page keep theirs", got == sorted([(P1, SOLO), (P1, WIDE), (P2, PR)]), got)
check("rule 4: a registry that could not be read ({}) ends nothing", SW.rule_pages(pst, {}) == [], "")

# ---------- sweep: all four, the log, idempotence ----------
put_item(6, "completed")
sst = {P1: [entry(SOLO, ["a2"]), entry(WIDE), entry(PR, None, 1.0), entry("https://example.invalid/open", ["a3"]), entry("https://example.invalid/part", ["a2", "a3"])],
       P2: [entry(SLACK), entry(REL)], P3: [entry(ISSUE, ["a1"]), entry("https://example.invalid/p3", ["a6"])]}
set_store(sst)
rd = reader({aid_pr: closed(NOW - 20 * DAY)}, {aid_pr: ALIVE}, repos={"q/q": NOW - 3600})
out = SW.sweep(NOW, reader=rd, reg={P1: {"status": "active"}, P2: {"status": "archived"}, P3: {"status": "active"}})
left = get_store()
check("sweep: it ends rule 1's (a closed item), rule 2's (a pull request quiet for 20 days) and rule 4's (the archived page's) in one pass, and nothing else",
      sorted((o["page"], o["url"], o["rule"]) for o in out) == sorted([(P1, SOLO, "items"), (P1, PR, "quiet"), (P2, SLACK, "pages"), (P2, REL, "pages"), (P3, "https://example.invalid/p3", "items")]), out)
check("sweep: what stays is the project-wide entry, the open-item entry, the partly open entry and the entry of the active page", urls(left, P1) == [WIDE, "https://example.invalid/open", "https://example.invalid/part"] and urls(left, P3) == [ISSUE] and P2 not in left, left)
check("sweep: a page left with no entry is dropped from the store, not kept as an empty list", P2 not in left, left)
lg = lines(P1)
check("sweep: each removal is one log-only line on its page's routing log, ruled archived by the automatic ruler, with the url and the call that puts it back",
      len(lines(P1)) == 2 and all(n.get("ruling") == "archived" and n.get("ruled_by") == routing.AUTO_RULER for n in lg)
      and any(n.get("url") == SOLO and f'anchors(project="{P1}", add=["{SOLO}"])' in (n.get("text") or "") for n in lg), lg)
check("sweep: the restore call keeps the items still open (project-wide when every one is closed)",
      SW.restore_call(P1, entry("https://example.invalid/part", ["a2", "a3"])) == f'anchors(project="{P1}", add=["https://example.invalid/part"], items=["{sh("a3")}"])'
      and SW.restore_call(P1, entry(SOLO, ["a2"])) == f'anchors(project="{P1}", add=["{SOLO}"])', "")
check("sweep: the returned dicts carry the same restore call as the log line", all(o["restore"] in " ".join((n.get("text") or "") for n in lines(o["page"])) for o in out), out)
check("sweep: a restore line is the call itself: anchors(project=..., add=[...]) parses back to its url", all(re.fullmatch(r'anchors\(project="[^"]+", add=\["[^"]+"\](, items=\["[^"]+"(, "[^"]+")*\])?\)', o["restore"]) for o in out), [o["restore"] for o in out])
again = SW.sweep(NOW, reader=rd, reg={P1: {"status": "active"}, P2: {"status": "archived"}, P3: {"status": "active"}})
check("sweep: a second sweep removes nothing and writes no second log line (idempotent)", again == [] and get_store() == left and len(lines(P1)) == 2 and len(lines(P2)) == 2, (again, len(lines(P1))))

# ---------- sweep: the rules= selection, an unreadable or empty store, a spared wait ----------
set_store(sst)
only = SW.sweep(NOW, rules=("items",), reader=rd, reg={})
check("sweep(rules=('items',)) runs rule 1 alone: the quiet pull request and the archived page's entries stay", sorted(o["rule"] for o in only) == ["items", "items"] and PR in urls(get_store(), P1) and SLACK in urls(get_store(), P2), only)
set_store(sst)
check("sweep with no reader position at all removes nothing by rules 2 and 3 (a reader that is down knows nothing new)", SW.sweep(NOW, rules=("quiet", "repo"), reader=SW.Reader(None, None, None), reg={}) == [] and get_store() == sst, "")
(T / "store/anchors.json").write_text("{broken")
check("sweep over a store that cannot be read removes nothing and does not write it", SW.sweep(NOW, reader=rd, reg=reg) == [] and (T / "store/anchors.json").read_text() == "{broken", "")
set_store(sst)
put_item(7, "open", wait_anchor=PR, state="parked", hold=True, needs=["external"], wake="2099-01-01", next="mv: look again")
spared = SW.sweep(NOW, rules=("quiet",), reader=rd, reg={})
check("sweep: an anchor an open item's wait_anchor names is spared by rule 2 even when it is quiet (an item scoped to it need not be)", spared == [] and PR in urls(get_store(), P1), spared)
(T / "store/a/7.json").unlink()
set_store(sst)
check("sweep: the same anchor with no item waiting on it goes by rule 2", [o["url"] for o in SW.sweep(NOW, rules=("quiet",), reader=rd, reg={})] == [PR], "")

# ---------- the callers: a close's lines, the page registry from disk, the reader from its files ----------
set_store({P1: [entry(SOLO, ["a2"]), entry(WIDE)]})
txt = SW.on_close("a2")
check("on_close: the removed url, its page and its restore call are the lines of the close's reply; a project-wide entry stays", SOLO in txt and P1 in txt and "restore: anchors(" in txt and urls(get_store(), P1) == [WIDE], txt)
check("on_close: a close that ends nothing says nothing", SW.on_close("a2") == "" and SW.close_note([]) == "", "")
pub = []
set_store({P1: [entry(SOLO, ["a2"])]}); SW.on_close("a2", lambda: pub.append(1))
check("on_close: the board is published when anchors went, not otherwise", pub == [1] and (SW.on_close("a2", lambda: pub.append(2)) == "") and pub == [1], pub)

(T / "store/projects.json").write_text(json.dumps({"pages": {P1: {"title": "p", "name": "p", "org": "home", "tags": [], "type": "project", "session": "", "status": "archived", "board": [], "board_row": False,
                                                                 "updated": 1, "mirror": "https://example.invalid/p"}}}))
set_store({P1: [entry(WIDE), entry(SOLO, ["a1"])], P3: [entry(SLACK)]})
got = SW.on_page_change()
check("on_page_change: the archived page's anchors go (read from the registry on disk), another page's stay", sorted(o["url"] for o in got) == sorted([WIDE, SOLO]) and P1 not in get_store() and urls(get_store(), P3) == [SLACK], got)

ah = _inbox.FLAGS; ah.mkdir(parents=True, exist_ok=True)
(ah / "cursors.json").write_text(json.dumps({"github": {"state": {aid_pr: closed(NOW - 20 * DAY)}, "looked": {aid_pr: ALIVE}}, "github_repos": {"archived": {}, "gone": {}}}))
(ah / "status.json").write_text(json.dumps({"anchors": {aid_pr: {"unreadable": {"since": "2026-11-20 10:00:00", "why": "declined", "warned": True, "next": "x"}}}}))
set_store({P1: [entry(PR)]})
live = time.time()
rdd = SW.Reader.load()
r = rdd.reading(aid_pr)
check("Reader.load: reads the reader's two files; a Reading has its state, its `updated`, the time it last looked, and its raw status entry (where a later 'unreadable' mark sits)",
      r.known and r.finished and abs(r.updated - (NOW - 20 * DAY)) < 1 and r.looked == ALIVE and r.status.get("unreadable", {}).get("why") == "declined" and rdd.saved_at is not None, r)
check("Reader.reading: an anchor the reader knows nothing of is empty, with an empty status", SW.Reader.load().reading("github:o/r#99") == SW.Reading(anchor="github:o/r#99"), SW.Reader.load().reading("github:o/r#99"))
os.utime(ah / "cursors.json", (live - 7 * 3600, live - 7 * 3600))
check("Reader.fresh: a position file older than 6 hours is not believed; a young one is", not SW.Reader.load().fresh(live) and SW.Reader(None, live - 10, None).fresh(live), "")
(ah / "cursors.json").write_text("{nope")
check("Reader.load: a position file that cannot be parsed is an empty record, never a crash", SW.Reader.load().saved_at is None and not SW.Reader.load().reading(aid_pr).known, "")
check("Reader: the saved key's own spelling of a renamed repository is read as the current one (the same canonical anchor id)", SW.Reader({"github": {"state": {"github:o/r#9": closed(1.0)}}}, None, None).reading(aid_pr).known, "")

# ---------- hand-edited junk steps over ----------
set_store({P1: [entry(SOLO, ["a2"])]})
raw = json.loads((T / "store/anchors.json").read_text()); raw["projects/junk"] = "not a list"; raw[P2] = [5, {"url": 7}, {"url": SOLO, "items": 3}]
(T / "store/anchors.json").write_text(json.dumps(raw))
check("sweep: a store with a page that is no list, entries that are no dicts or have no url steps over them and still ends what it should", [o["url"] for o in SW.sweep(NOW, reader=SW.Reader(None, None, None), reg={})] == [SOLO], "")

# ---------- the anchors lock: another writer's change is never lost, never brought back ----------
real_load, real_save = ANC.load, ANC.save
NEW1, NEW2, NEW3, NEWG = "https://example.invalid/new1", "https://example.invalid/new2", "https://example.invalid/new3", "https://github.com/o/r/pull/31"
def other_add(page, url):
    with ANC.LOCK:
        s = real_load(); s.setdefault(page, []).append(entry(url)); real_save(s)
def sweep_items_with(load):
    ANC.load = load
    try: return SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})
    finally: ANC.load = real_load

set_store({P1: [entry(SOLO, ["a2"]), entry(WIDE)]}); seen = []
def load_a():
    seen.append(1); s = real_load()
    if len(seen) == 1: other_add(P1, NEW1)         # another writer adds an anchor after the sweep's first read of the store and before its removal
    return s
out = sweep_items_with(load_a)
check("race: an anchor added by another writer between the sweep's read and its save is kept (the removal reads the store again under the anchors lock)",
      [o["url"] for o in out] == [SOLO] and urls(get_store(), P1) == [WIDE, NEW1] and len(seen) >= 2, (out, get_store()))

set_store({P1: [entry(SOLO, ["a2"]), entry(WIDE)]}); seen = []; threads = []; held_off = []
def load_b():
    seen.append(1); s = real_load()
    if len(seen) == 2:                            # inside the sweep's hold: a writer that starts now has to wait for its save
        t = threading.Thread(target=other_add, args=(P1, NEW2), name="s1531fix-adder"); t.start(); threads.append(t); t.join(0.6); held_off.append(t.is_alive())
    return s
out = sweep_items_with(load_b)
for t in threads: t.join(10)
check("race: a writer that comes while the sweep holds the anchors lock waits for the sweep's save, and its anchor and the removal both stand",
      held_off == [True] and not any(t.is_alive() for t in threads) and [o["url"] for o in out] == [SOLO] and urls(get_store(), P1) == [WIDE, NEW2], (held_off, out, get_store()))
check("race: the anchors lock is the cross-process lock of its name (an XLock named anchors, outside the item lock's order)", ANC.LOCK is __import__("stackshot.core.xlock", fromlist=["XLock"]).XLock("anchors"), ANC.LOCK)

from stackshot.web import server as _server      # installs the service layer's hooks the anchors tool reads through
from stackshot.web.tools import anchors as WA
WA._publish = lambda: None
GHOST = "projects/ghost"                          # a key whose page is gone: the anchors tool lists and removes it only
set_store({GHOST: [entry(SOLO), entry(WIDE)]}); res = []
def tool_remove():
    try: res.append(WA._anchors(GHOST, remove=[SOLO]))
    except Exception as e: res.append(e)
with ANC.LOCK:
    t = threading.Thread(target=tool_remove, name="s1531fix-tool"); t.start(); t.join(0.6); waited = t.is_alive()
    s = real_load(); s[GHOST].append(entry(NEW3)); real_save(s)
t.join(10)
check("race: the anchors tool's removal takes the anchors lock and reads the store again under it (an anchor added while it waited stays)",
      waited and not t.is_alive() and len(res) == 1 and urls(get_store(), GHOST) == [WIDE, NEW3], (waited, res, get_store()))
set_store({P1: [entry(WIDE)]}); res = []
def tool_add():
    try: res.append(WA._anchors(P1, add=[NEWG]))
    except Exception as e: res.append(e)
with ANC.LOCK:
    t = threading.Thread(target=tool_add, name="s1531fix-tool"); t.start(); t.join(0.6); waited = t.is_alive()
    s = real_load(); s[P1].append(entry(NEW3)); real_save(s)
t.join(10)
check("race: the anchors tool's add takes the anchors lock and reads the store again under it (an anchor added while it waited stays, and its own is added)",
      waited and not t.is_alive() and len(res) == 1 and not isinstance(res[0], Exception) and sorted(urls(get_store(), P1)) == sorted([WIDE, NEW3, NEWG]), (waited, res, get_store()))

# ---------- the waiters: every form of the anchor, a list wait, a held item; a closed item's wait spares nothing ----------
QR = reader({aid_pr: closed(NOW - 90 * DAY)}, {aid_pr: ALIVE})
def quiet_went(entry_items=None, status="open", **meta):
    for f in (T / "store/a").glob("2?.json"): f.unlink()
    put_item(20, status, **meta)
    set_store({P1: [entry(PR, entry_items)]})
    return [o["url"] for o in SW.sweep(NOW, rules=("quiet",), reader=QR, reg={})] == [PR]
check("waiters: with no item waiting on it a quiet pull request goes (the control of the checks below)", quiet_went(), "")
forms = {"the same pull request": PR, "its issue form (/issues/9)": "https://github.com/o/r/issues/9", "its github: form": "github:o/r#9", "its /files page": PR + "/files", "a #mention fragment": PR + "#mention=alice"}
from stackshot.service import watching as _watching
check("waiters: the sweep's anchor_key is the waits' own (service/watching.anchor_key) for every form and for shapes neither knows", all(SW.anchor_key(u) == _watching.anchor_key(u) for u in [*forms.values(), "not an anchor", "", SLACK, "gmail:q:x", REL]), "")
for label, url in forms.items():
    check(f"waiters: an open item's wait_anchor in the form of {label} spares the anchor", not quiet_went(wait_anchor=url), url)
    check(f"waiters: …and an open anchor line of a list wait in the form of {label} spares it", not quiet_went(wait_kind="list", wait_mode="any", until="2099-01-01", waits=[{"kind": "anchor", "anchor": url, "event": "x"}, {"kind": "time", "until": "2099-01-01"}]), url)
check("waiters: a wait on another pull request spares nothing", quiet_went(wait_anchor="https://github.com/o/r/pull/10") and quiet_went(wait_anchor="https://github.com/o2/r/pull/9"), "")
check("waiters: a list line that has arrived is not an open wait", quiet_went(wait_kind="list", wait_mode="any", until="2099-01-01", waits=[{"kind": "anchor", "anchor": PR, "event": "x", "arrived": {"at": 5, "what": "y"}}, {"kind": "time", "until": "2099-01-01"}]), "")
check("waiters: a closed item's wait spares nothing (the wait_anchor and a list line alike)", quiet_went(status="completed", wait_anchor=PR)
      and quiet_went(status="completed", wait_kind="list", wait_mode="any", until="2099-01-01", waits=[{"kind": "anchor", "anchor": PR, "event": "x"}, {"kind": "time", "until": "2099-01-01"}]), "")
check("waiters: an entry scoped to a parked open item is spared; one scoped to an open item that is not on hold goes",
      not quiet_went(["a20"], hold=True, needs=["external"], wake="2099-01-01", next="mv: x") and quiet_went(["a20"]) and quiet_went(["a20"], status="completed"), "")
real_items = ANC.items_read
def broken_items(): raise OSError("store unreadable")
ANC.items_read = broken_items
try:
    with contextlib.redirect_stderr(io.StringIO()) as err:
        went = quiet_went()
finally: ANC.items_read = real_items
check("waiters: when the items cannot be read every anchor is spared, with a line on stderr", not went and "every anchor is spared" in err.getvalue(), err.getvalue())
(T / "store/a/9.json").write_text("{not json")       # an item file that cannot be parsed may hold the wait on this very anchor: `items()` leaves it out, the sweep must not take that for no wait
SW._SAID.clear()
with contextlib.redirect_stderr(io.StringIO()) as err:
    went = quiet_went()
    went_again = quiet_went()
check("waiters: an item file that cannot be parsed makes the sweep unsure: rule 2 removes nothing while it is there, and the line on stderr is said once", not went and not went_again and err.getvalue().count("could not be read") == 1 and "a/9.json" in err.getvalue(), err.getvalue())
set_store({P1: [entry(PR), entry(SOLO, ["a2"])]})
with contextlib.redirect_stderr(io.StringIO()):
    out = SW.sweep(NOW, rules=("quiet", "repo", "items"), reader=reader({aid_pr: closed(NOW - 90 * DAY)}, {aid_pr: ALIVE}, repos={"o/r": NOW - 3600}), reg={})
check("waiters: ...and so does rule 3, while rule 1 (which reads no wait) still ends the entry of a closed item", [o["url"] for o in out] == [SOLO] and PR in urls(get_store(), P1), out)
check("waiters: items_read names the file it could not read, and items() leaves it out", ANC.items_read()[1] == ["a/9.json"] and all(t["gid"] != "a9" for t in ANC.items()), ANC.items_read()[1])
(T / "store/a/9.json").unlink()
check("waiters: with the file readable again the quiet pull request goes", quiet_went(), "")
for f in (T / "store/a").glob("2?.json"): f.unlink()

# ---------- an item that cannot be read is unknown, never closed ----------
MAPF = T / "store" / ghsync.MAP_NAME
store_items = [(g, SW.item_state(g)) for g in ("a1", "a2", "a4")]
check("item_state: open, completed, and a missing file in a store that holds items (closed)", [s[0] for _, s in store_items] == ["open", "closed", "closed"], store_items)
check("item_state: an item whose letter folder is missing is unknown, not closed, even when another folder exists", SW.item_state("b3")[0] == "unknown" and "no folder" in SW.item_state("b3")[1], SW.item_state("b3"))
MAPF.write_text("{nope")
check("item_state: an id that is not in the store, while the alias map cannot be read, is unknown (it may be an old id); an id whose file is there is still read",
      SW.item_state("a40")[0] == "unknown" and SW.item_state("a2")[0] == "closed" and SW.item_state("a1")[0] == "open", [SW.item_state(g) for g in ("a40", "a2", "a1")])
MAPF.write_text(json.dumps({"aliases": 5}))
check("item_state: an alias map that is not a map reads the same way", SW.item_state("a40")[0] == "unknown", SW.item_state("a40"))
MAPF.write_text(json.dumps({"aliases": {"a41": "a2"}}))
check("item_state: an old id is read through the alias map when it can be read", SW.item_state("a41")[0] == "closed", SW.item_state("a41"))
MAPF.unlink()
os.rename(T / "store/a", T / "store/aoff"); os.mkdir(T / "store/a")
try:
    empty = [SW.item_state(g) for g in ("a2", "a4")]
    set_store({P1: [entry(SOLO, ["a2"])]}); SW._SAID.clear()
    with contextlib.redirect_stderr(io.StringIO()) as err:
        kept = SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})
        again = SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})
finally:
    os.rmdir(T / "store/a"); os.rename(T / "store/aoff", T / "store/a")
check("item_state: a store that holds no item at all reads every id as unknown, never closed", [s[0] for s in empty] == ["unknown", "unknown"], empty)
check("sweep: an empty item store ends nothing, and says so once on stderr (the entry is kept)", kept == [] and again == [] and urls(get_store(), P1) == [SOLO] and err.getvalue().count("read as unknown") == 1, (kept, err.getvalue()))
set_store({P1: [entry(SOLO, ["b3"]), entry(WIDE, None)]})
with contextlib.redirect_stderr(io.StringIO()):
    kept = SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})
check("sweep: an item whose letter folder is missing keeps the entry scoped to it", kept == [] and urls(get_store(), P1) == [SOLO, WIDE], (kept, get_store()))

# a path that cannot be looked at is unknown, whatever the reason: only "not there" says an item is gone (Path.exists() answers False to a permission, an input error and a symlink loop alike)
os.symlink("8.json", T / "store/a/8.json")            # a symlink loop where the item's file should be: stat answers ELOOP
set_store({P1: [entry(SOLO, ["a8"]), entry(WIDE, None)]}); SW._SAID.clear()
with contextlib.redirect_stderr(io.StringIO()) as err:
    loop_state = SW.item_state("a8")
    kept = SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})
    SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})
check("item_state: a symlink loop where the item's file should be reads as unknown (the file can not be looked at), never closed", loop_state[0] == "unknown" and "looked at" in loop_state[1], loop_state)
check("sweep: the entry scoped to it stays, and the unknown item is said once on stderr", kept == [] and urls(get_store(), P1) == [SOLO, WIDE] and err.getvalue().count("a8 read as unknown") == 1, (kept, err.getvalue()))
(T / "store/a/8.json").unlink()
if os.geteuid() != 0:
    os.mkdir(T / "store/c"); (T / "store/c/1.json").write_text(json.dumps({"id": "1", "status": "open", "metadata": {}})); os.chmod(T / "store/c", 0)
    set_store({P1: [entry(SOLO, ["c1"])]})
    try:
        locked_state = SW.item_state("c1")
        with contextlib.redirect_stderr(io.StringIO()): kept = SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})
        os.rename(T / "store/a", T / "store/aoff"); os.mkdir(T / "store/a")
        try:
            no_items = SW.item_state("a4")
            try: SW._store_has_items(); raised = None
            except OSError as e: raised = e
        finally:
            os.rmdir(T / "store/a"); os.rename(T / "store/aoff", T / "store/a")
    finally:
        os.chmod(T / "store/c", 0o755)
        shutil.rmtree(T / "store/c", ignore_errors=True)
    check("item_state: a letter folder that cannot be searched (mode 000) reads as unknown: its item file can not be looked at, so it is not 'no file'", locked_state[0] == "unknown" and "looked at" in locked_state[1], locked_state)
    check("sweep: the entry scoped to an item in that folder stays", kept == [] and urls(get_store(), P1) == [SOLO], kept)
    check("item_state: a store whose item folders cannot be listed is unknown ('cannot be looked at'), not 'holds no item at all', and _store_has_items raises the error", no_items[0] == "unknown" and "looked at" in no_items[1] and isinstance(raised, PermissionError), (no_items, raised))
else:
    print("skipped: the mode-000 letter folder checks (running as root: a permission does not stop root)")

# ---------- re-adding an anchor that is already there renews its `added` time (rule 2 counts its 14 days from it) ----------
live = time.time()
RD = reader({aid_pr: closed(live - 90 * DAY)}, {aid_pr: live - 600}, saved=live - 60)
set_store({P1: [entry(PR, None, 1.0)]})
control = SW.sweep(live, rules=("quiet",), reader=RD, reg={})
check("re-add: control: a pull request closed 90 days ago, added long ago, goes by rule 2", [o["url"] for o in control] == [PR], control)
set_store({P1: [entry(PR, None, 1.0)]}); st = ANC.load(); t0 = time.time()
ANC.add(st, P1, [PR], None, by="t"); ANC.save(st)
check("re-add: adding the url that is already there sets its `added` to now (and adds no second entry)", len(get_store()[P1]) == 1 and get_store()[P1][0]["added"] >= t0, get_store())
check("re-add: ...so rule 2 does not remove it on the next tick", SW.sweep(live, rules=("quiet",), reader=RD, reg={}) == [] and urls(get_store(), P1) == [PR], get_store())
set_store({P1: [entry(PR, ["a1"], 1.0)]}); st = ANC.load(); ANC.add(st, P1, [PR], ["a3"], by="t"); ANC.save(st)
check("re-add: a re-add that widens the scope renews it too, and the scope is still the union", get_store()[P1][0]["added"] >= t0 and get_store()[P1][0]["items"] == ["a1", "a3"], get_store())
set_store({P1: [entry(PR, None, 1.0)]}); st = ANC.load(); ANC.add(st, P1, [PR], ["a3"], by="t"); ANC.save(st)
check("re-add: a scoped add of a project-wide entry leaves it project-wide, and renews it", get_store()[P1][0]["items"] is None and get_store()[P1][0]["added"] >= t0, get_store())

# ---------- a close ends only the entries scoped to the item that closed ----------
STALE = "https://example.invalid/stale"
set_store({P1: [entry(SOLO, ["a2"]), entry(STALE, ["a6"]), entry(WIDE)]})
txt = SW.on_close("a2")
check("on_close: an entry of another closed item that nothing touched survives the close of this one", SOLO in txt and STALE not in txt and urls(get_store(), P1) == [STALE, WIDE], (txt, get_store()))
check("on_close: …and the next tick of the sweep ends it", [o["url"] for o in SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})] == [STALE], get_store())
set_store({P1: [entry(PR, None, 1.0)]})
check("on_close: it runs rule 1 only: a quiet pull request stays through a close", SW.on_close("a2") == "" and urls(get_store(), P1) == [PR], get_store())
set_store({P1: [entry(SOLO, ["a2", "a6"])]})
check("on_close: an entry scoped to the closed item and another closed one goes with the close", SOLO in SW.on_close("a6") and urls(get_store(), P1) == [], "")

# ---------- a reopening: the lines of what the close ended ----------
set_store({P1: [entry(SOLO, ["a2"])]}); SW.on_close("a2")
note = SW.reopen_note("a2", P1)
check("reopen_note: an item reopened after its close ended an anchor gets one line naming the restore call, scoped to the item again",
      note.count("\n") == 1 and f'anchors(project="{P1}", add=["{SOLO}"], items=["{sh("a2")}"])' in note, note)
check("reopen_note: an item whose close ended nothing, or another project's reopening, gets nothing", SW.reopen_note("a9", P1) == "" and SW.reopen_note("a2", "projects/elsewhere") == "", "")
check("reopen_note: an id is not read as another that it starts with (a20 is not a2)", SW.reopen_note("a20", P1) == "", SW.reopen_note("a20", P1))
DELTA = "projects/delta"
set_store({DELTA: [entry(WIDE), entry(SOLO, ["a1"])]})
SW.sweep(NOW, rules=("pages",), reader=SW.Reader(None, None, None), reg={DELTA: {"status": "archived"}})
pn = SW.page_reopen_note(DELTA)
check("page_reopen_note: a page archived with anchors gets one line: how many ended, where their restore calls are, and one url", "2 anchors" in pn and WIDE in pn and DELTA in pn and "\n" not in pn, pn)
check("page_reopen_note: …and a page whose archiving ended none gets nothing", SW.page_reopen_note("projects/never") == "" and SW.page_reopen_note(P3) == "", (SW.page_reopen_note(P3)))

# ---------- duplicates: an entry is removed for the judgement made on it, never its twin ----------
DUP = "https://example.invalid/dup"
set_store({P1: [entry(DUP, ["a2"]), entry(DUP, ["a1"]), entry(DUP, ["a2"])]})
out = SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})
check("duplicates: two entries with one url, one scoped to an open item: the one that no rule ended stays, each that did is removed and logged once",
      len(out) == 2 and [(e["url"], e["items"]) for e in get_store()[P1]] == [(DUP, ["a1"])] and len([n for n in lines(P1) if n.get("url") == DUP]) == 2, (out, get_store()))
set_store({P1: [entry(DUP, ["a1"]), entry(DUP, ["a2"])]}); out = SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})
check("duplicates: the twin that stays is the one that was not ended, wherever it stands", len(out) == 1 and [e["items"] for e in get_store()[P1]] == [["a1"]], (out, get_store()))
set_store({P1: [entry(DUP, ["a2"]), entry(DUP, ["a2"])]}); out = SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})
check("duplicates: two identical ended entries are both removed and both told", len(out) == 2 and P1 not in get_store(), (out, get_store()))

# ---------- a removal's restore line is never cut by the log's 300 characters ----------
LONG = "https://example.invalid/" + "x" * 420
set_store({P1: [entry(LONG, ["a2"]), entry(SOLO, ["a2"])]})
out = SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})
rec = [json.loads(x) for x in (T / "state" / SW.REMOVED).read_text(encoding="utf-8").splitlines()]
long_line = [n for n in lines(P1) if n.get("url") == LONG]
solo_line = [n for n in lines(P1) if n.get("url") == SOLO][-1]
long_out = [o for o in out if o["url"] == LONG][0]
check("restore lines: a call longer than the log's 300 characters is whole in the state folder's record, and the log line says where", len(long_out["restore"]) > 300
      and any(r["url"] == LONG and r["restore"] == long_out["restore"] for r in rec) and len(long_line) == 1 and str(T / "state" / SW.REMOVED) in long_line[0]["text"] and "too long" in long_line[0]["text"], (long_line, len(long_out["restore"])))
check("restore lines: a short call is whole on the log line", long_out["restore"] not in solo_line["text"] and f'add=["{SOLO}"])' in solo_line["text"], solo_line)
BULK = "projects/bulk"; bulk_urls = [f"https://example.invalid/bulk/{i}" + "y" * 60 for i in range(60)]
set_store({BULK: [entry(u, ["a2"]) for u in bulk_urls]})
out = SW.sweep(NOW, rules=("items",), reader=SW.Reader(None, None, None), reg={})
bl = lines(BULK); rec = [json.loads(x) for x in (T / "state" / SW.REMOVED).read_text(encoding="utf-8").splitlines()]
check("restore lines: a bulk removal of 60 entries writes one log line per entry, each with its whole call", len(out) == 60 and len(bl) == 60 and all(o["restore"] in n["text"] for o in out for n in bl if n.get("url") == o["url"])
      and sorted(n["url"] for n in bl) == sorted(bulk_urls), (len(out), len(bl)))
check("restore lines: …and the record file holds each of the 60 whole", sorted(r["url"] for r in rec if r["page"] == BULK) == sorted(bulk_urls) and all(r["restore"].endswith(")") for r in rec if r["page"] == BULK), len(rec))

# ---------- a cap on one tick ----------
from stackshot.core import config as _cfg
CAPP = "projects/capped"
check("per_tick: 50 when the setting is absent, and for a value that is no whole number or below one", (_cfg.CFG.get("anchor_hub", {}).pop("sweep_per_tick", None), SW.per_tick())[1] == 50
      and all([_cfg.CFG.setdefault("anchor_hub", {}).update(sweep_per_tick=v) or SW.per_tick() == 50 for v in (0, -3, "x", True, 2.5, None)]), SW.per_tick())
_cfg.CFG["anchor_hub"]["sweep_per_tick"] = 3
check("per_tick: the configured whole number", SW.per_tick() == 3, SW.per_tick())
set_store({CAPP: [entry(f"https://example.invalid/cap/{i}", ["a2"]) for i in range(7)]})
counts = [len(SW.sweep_tick()) for _ in range(4)]
check("sweep_tick: removes at most sweep_per_tick entries a tick; the rest go on the next ticks (3, 3, 1, then nothing), each with its log line", counts == [3, 3, 1, 0] and CAPP not in get_store() and len(lines(CAPP)) == 7, (counts, len(lines(CAPP))))
del _cfg.CFG["anchor_hub"]["sweep_per_tick"]
import tomllib
check("stackshot.example.toml: [anchor_hub] sweep_per_tick is set to the default of 50", tomllib.loads(_instance.base_toml()).get("anchor_hub", {}).get("sweep_per_tick") == 50 == SW.PER_TICK, tomllib.loads(_instance.base_toml()).get("anchor_hub"))

print(("ok" if not fails else "FAILED") + f": {len(ran) - len(fails)}/{len(ran)} checks")
sys.exit(1 if fails else 0)
