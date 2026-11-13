"""Scenario test for the For you list (a notice for him is a row in a list, never a turn of a front agent) — fixture data, the HTTP routes through Starlette's test client, no live store, no network, no Slack.

Covers: a close with his words on the item (a said entry, a quoted attribution) makes a row, with the router live and with it off, and
records no router notice; the front agent owner is told by its own one marked line of a close by another session (not the
owner's own write, not a muted item; one message per write, none twice) and of an item back with it alone, and of nothing else ("only when back with it": a builder's step is never pushed to it: not a needs leave while another session
stays in needs, not a work line marked done, for a front or a background owner; the hand-back line is sent once, when the last other
session leaves); the writer's reply says it is a row; a
close without his words on an item he does not watch makes no row (the old quiet line); a muted item makes no row; a Watch flag
adds an item that is not watched; an item with his board answer is watched by default; needs=decision makes a decision row (also
on an item with no words), which goes when he answers on the board (his own answer makes no row); a reopen and a failed check
make a row; a due date within 24 h makes one urgent row per due date, posted once to Slack (stubbed), not again, and a due date
long past, an unwatched item and a muted one make none; a failed release message makes NO row but is still delivered as a message to the project; a
for-you.json from before this (a release_failed row) loads without the stale row and the next write removes it; the board's For you section (newest first, link, time in the instance timezone, a seen form) is built but the board page hides it behind ui_render._SHOW_FOR_YOU (Sun Oct 25th 2026), an item
page the Watch / Mute control; the watch and seen routes refuse a visitor who is not signed in, a wrong token and a foreign
origin; seen clears a row, "all" clears every one; `client.py get for-you` returns the rows and the flags as JSON.

    tests/run-suite for_you        → exit 0 / 1"""
import contextlib, io, json, logging, os, pathlib, re, socket, subprocess, sys, tempfile, threading, time
BID_A = 9160
BID_B = 9161

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="foryoutest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
EMAIL = "oliver@example.org"
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the For you list, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
S, A, X, B = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
              "44444444-4444-4444-8444-444444444444")
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for u, n in
                                                      ((S, "osprey"), (A, "osprey-main"), (X, "osprey-x"), (B, "home-beta"))}))
AGENTS = {"osprey-main": "Oliver's point of contact", "osprey-x": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {
    "title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "osprey", "status": "active", "board": [], "board_row": False,
    "updated": 1, "mirror": "https://example.invalid/alpha", "agents": AGENTS, "back_agents": {"osprey-x": AGENTS["osprey-x"]}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
DESC = "- A thing\n- It lives here\n- Finished when it works"
now0 = time.time()
ZONE_HOURS = 4                                                                         # the instance zone is Asia/Dubai: UTC+4, no daylight saving
ABY = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 5 * 86400 + ZONE_HOURS * 3600))      # the day a wait on news comes back to someone
ASK = "Decide: whether to ship · Recommend: yes · Stakes: none either way · By: no date"
YESNO = "Decide: whether to go ahead · Recommend: go · Stakes: a day either way · By: no date"
SAID = [{"tag": "Acked-by", "quote": "go ahead", "msg": "m1", "session": "s1", "ts": 1.0, "checked": True}]
ANS = [{"ts": 1.0, "kind": "decision", "choice": "Go", "via": "board"}]
def item(i, owner=A, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600,
                                                       "metadata": {"owner": owner, **({} if {"mover", "then", "hold", "after"} & set(meta) or "decision" in (meta.get("needs") or []) else {"mover": owner}), "project": "projects/alpha", "next": "the next step", **meta}}))
# 1-9: closes · 10-19: decisions · 20-29: reopen, check · 30-39: due dates · 50-59: routes
item(1, said=SAID); item(2); item(3, said=SAID); item(4, said=SAID); item(5, answers=ANS); item(6, said=SAID); item(7)
item(8, said=SAID); item(9)
item(10); item(11); item(12, said=SAID)
item(60, said=SAID); item(61, said=SAID); item(62)
item(20, said=SAID); item(21, said=SAID, check={"kind": "pr_merged", "url": "https://example.invalid/pr/1"})
item(50); item(51); item(52, said=SAID); item(53)
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
push_log = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(push_log)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
def pushes(): return [json.loads(l) for l in push_log.read_text().splitlines()] if push_log.exists() else []
def settle(until=30):
    """wait until the board's relay threads have ended: each push runs in a thread of its own. A fixed
    0.5 s was too short under coverage on a busy box (a measured run on main, for 0110c0d). The Slack worker
    (for-you-slack) lives on once started, so it is not waited for: a check of its posts joins its queue (server._fyslack._foryou_slack_wait)."""
    end = time.time() + until
    while time.time() < end and any(t is not threading.main_thread() and t.is_alive() and t.name != "for-you-slack" for t in threading.enumerate()):
        time.sleep(0.02)
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())

from stackshot.core import config as _cfg; from stackshot.router import routing; from stackshot.web import foryou as fy
from stackshot.web import server
from stackshot.web.auth import signin as _signin
from stackshot.service import telling
from stackshot.service import writes
from stackshot.web.ui import render as ui_render
from starlette.testclient import TestClient
server._publish = server._fyev._publish = lambda: None; telling.PUSH = [sys.executable, str(T / "fakepush.py")]
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
# a front agent is told of a close only while Oliver is there and it touched the item (tests/front_quiet_scenario.py covers the gate). These checks are about the notice's shape and
# who is named in it, so Oliver is there for every front pane unless a check flips PRESENT; with it off the gate's own verdict is used (this fixture runs no panes: nobody is told).
PRESENT = [True]
_real_verdict = telling.front_verdict
telling.front_verdict = lambda gid, owner, kind: ("send", "") if PRESENT[0] else _real_verdict(gid, owner, kind)
def cfg(live=False): _cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, **({"live": True} if live else {})}
slack = []
REAL_SLACK_POST, REAL_SLACK_ON = server._fyslack._for_you_slack_post, server._fyslack._for_you_slack_on
server._fyslack._for_you_slack_post = lambda text: slack.append(text) or ""      # the Slack hook is stubbed: nothing leaves this process
server._fyslack._for_you_slack_on = lambda: True
pub = [0]; server._publish = server._fyev._publish = lambda: pub.__setitem__(0, pub[0] + 1)
NEWD = "- The thing works and is in use"
def cl(i, sender="osprey-x", reason="PR 14 is live", description=NEWD): return server.stackshot_complete(f"a{i}", outcome="done", reason=reason, description=description, sender=sender)
def rows(): return fy.rows()
def of(gid, kind=None): return [r for r in rows() if r.get("gid") == gid and (kind is None or r["kind"] == kind)]
def to_front(since): return [x for x in pushes()[since:] if x[0] in (A, "osprey-main")]
def to_front_of(gid, since): return [x for x in to_front(since) if re.search(rf"\b{gid}\b", x[1])]

# ---- 1. the list itself
check("the list starts empty; its file lives in the state dir", rows() == [] and str(fy.path()).startswith(f"{tmp}/state/"), fy.path())
r0 = fy.add(key="k:1", kind="closed", gid="a16", item="a16", project="projects/alpha", what="first", url="")
r1 = fy.add(key="k:2", kind="closed", gid="a13", item="a13", project="projects/alpha", what="second", url="")
check("add stores a row with an id, newest first in rows()", r0 and r1 and r1["id"] > r0["id"] and [r["what"] for r in rows()] == ["second", "first"], rows())
check("the same key makes no second row", fy.add(key="k:1", kind="closed", gid="a16", item="a16", project="p", what="again", url="") is None and len(rows()) == 2)
check("the file is a small JSON file written whole (no tmp file left beside it)", json.loads(fy.path().read_text()) and not list(fy.path().parent.glob("for-you.json.*")) and not list(fy.path().parent.glob("*.tmp")), list(fy.path().parent.iterdir()))
fy.seen("all"); check("seen all clears every row", rows() == [])
check("a seen row's key is remembered: the same event does not come back", fy.add(key="k:1", kind="closed", gid="a16", item="a16", project="p", what="again", url="") is None)
fy.set_flag("a16", "mute"); fy.set_flag("a13", "watch")
check("flags: mute and watch are stored, default removes", fy.flag("a16") == "mute" and fy.flag("a13") == "watch" and fy.flag("a14") == "", fy.flags())
fy.set_flag("a16", "default"); fy.set_flag("a13", "default")
check("…default removes the flag", fy.flags() == {} and fy.flag("a16") == "", fy.flags())
try: fy.set_flag("a16", "loud"); check("an unknown mode is refused", False)
except ValueError: check("an unknown mode is refused", True)

# ---- 2. a close with his words: a row, never a front agent turn
for live in (True,):      # the router rules every project since the "router off" pass is gone
    cfg(live=live)
    base = 1 if live else 6        # live: item 1, item 3, item 4; off: item 6 (said) — each in its own mode
    gid_ = "a1" if live else "a6"
    p0 = len(pushes()); n0 = len(routing.read("projects/alpha"))
    out = cl(int(gid_[1:])); settle()
    rr = of(gid_, "closed")
    mode = "router live" if live else "router off"
    check(f"close with his said entry, owner a front agent, {mode}: one closed row", len(rr) == 1, rows())
    check(f"…naming who closed it, the outcome, the subject and the reason; no item id inside (the list shows it beside)",
          rr and rr[0]["what"] == f"closed by osprey-x (done): [home] item {gid_[1:]} — PR 14 is live" and rr[0]["item"] == gid_ and rr[0]["project"] == "projects/alpha" and not rr[0]["urgent"], rr)
    check(f"…{mode}: the front agent is told by its own message and no other: one line with the mark, no row-style or old-style notice (Sun Oct 25th 2026)",
          [x[1] for x in to_front(p0) if "closed" in x[1] or "[for Oliver]" in x[1]] == [f"[for Oliver] [stackshot] {gid_} [home] item {gid_[1:]}: closed by osprey-x: done (PR 14 is live) \u2192 {BOARD}/items/{gid_}"], pushes()[p0:])
    check(f"…{mode}: no `close` notice is recorded for the router", not [n for n in routing.read("projects/alpha")[n0:] if str(n.get("label", "")).startswith("close ")], routing.read("projects/alpha")[n0:])
    check(f"…{mode}: the reply says it is a row on the For you list and that the owner was told at once", "is a row on his For you list" in out and "not a message to" not in out
          and "(its mover osprey-main is a front agent: told at once that it was closed)" in out and "not told" not in out, out)
check("the row links to the item", rr and rr[0]["url"] == f"{BOARD}/items/a1", rr)
out = cl(2); settle()
check("close with none of his words on an item he does not watch: no row, the owner told at once as before (it is its own page's keeper; no keeper to tell instead)", not of("a2") and "For you list" not in out and "told at once that it was closed" in out, (of("a2"), out))
out = cl(9); check("…same for another unwatched item", not of("a9"))
settle(); p3_ = len(pushes())
fy.set_flag("a3", "mute"); out = cl(3); settle()
check("a muted item (his words on it, but he muted it): no row", not of("a3") and "For you list" not in out and "not told; the board shows it" in out, (of("a3"), out))
check("…and no message to the owner either (a muted item is not told)", not [x for x in to_front(p3_) if "a3 " in x[1]] and "told at once" not in out, (pushes()[p3_:], out))
fy.set_flag("a7", "watch"); out = cl(7); settle()
check("a Watch flag adds an item with no words on it: a row", len(of("a7", "closed")) == 1, rows())
out = cl(5); check("an item with his board answer is watched by default: a row", len(of("a5", "closed")) == 1, rows())
out = cl(4, reason='Oliver, Mon Jan 12th 2099: "no longer needed"', description=NEWD); check("a quoted attribution counts as his words: a row", len(of("a4", "closed")) == 1 and "For you list" in out, (of("a4"), out))
out = cl(8, sender="osprey-main"); check("…the row is made whoever closes (a8 closed by its own front agent)", len(of("a8", "closed")) == 1, rows())
check("every row came from a close above; nothing for the unwatched ones", sorted({r["gid"] for r in rows()}) == ["a1", "a4", "a5", "a7", "a8"], sorted({r["gid"] for r in rows()}))

# ---- 2b. the owner is told at once of a close by another session; of an item's steps only when it is back with it alone
# ("only when it is back with the builder"): a builder's step handback and a work line marked done are never pushed
# owner A = osprey-main (a front agent), builder X = osprey-x (a background agent), B = home-beta (a session no page names)
settle()
def to_owner(owner, gid, since): return [x[1] for x in pushes()[since:] if x[0] == owner and re.search(rf"\b{gid}\b", x[1]) and not x[1].startswith("[board]")]
for live in (True,):      # the router rules every project since the "router off" pass is gone
    cfg(live=live); mode = "router live" if live else "router off"; b = 70 if live else 80      # items 70-79 router live, 80-89 off
    item(b, needs=["osprey-x"]); item(b + 1); item(b + 2, needs=["external", "osprey-x"])
    item(b + 3, needs=["osprey-x"], next="osprey-x: migrating")
    item(b + 4, needs=["osprey-x"]); item(b + 5, needs=["external", "osprey-x"]); item(b + 6, needs=["osprey-x"])
    item(b + 7, owner=B); item(b + 8, owner=B, needs=["osprey-x"], next="osprey-x: migrating")
    g = lambda k: f"a{b + k}"
    p0 = len(pushes()); out = cl(b); settle()
    check(f"owner told, {mode}: a close by the builder (no words on the item, so no row): one marked line to the front agent owner, with the outcome, the subject and the item link",
          to_owner(A, g(0), p0) == [f"[for Oliver] [stackshot] {g(0)} [home] item {b}: closed by osprey-x: done (PR 14 is live) \u2192 {BOARD}/items/{g(0)}"] and not of(g(0)), (pushes()[p0:], of(g(0))))
    check(f"…{mode}: the reply says so, and not the quiet 'not told' line", "told at once that it was closed" in out and "not told" not in out, out)
    p0 = len(pushes()); out = cl(b + 1, sender="osprey-main"); settle()
    check(f"owner told, {mode}: a close by the owner itself tells the owner nothing", not to_owner(A, g(1), p0) and "told at once" not in out, (pushes()[p0:], out))
    p0 = len(pushes()); out = server._update(g(2), needs=["external"], next="Oliver: builder done; review it", wait_event="the review", ask_by=ABY, sender="osprey-x"); settle()
    check(f"no step line, {mode}: the builder takes itself off needs (`external` stays in it; the owner is not named): nothing is pushed to the front agent owner, and the reply promises nothing",
          not to_front_of(g(2), p0) and "told at once" not in out and "step came back" not in out and "not told" not in out, (pushes()[p0:], out))
    p0 = len(pushes()); out = server._update(g(3), work={"state": "done"}, sender="osprey-x"); settle()
    check(f"no step line, {mode}: the builder marks its last step done by a status done (needs unchanged, X still named): nothing is pushed to the front agent owner, and the write is on the item",
          not to_front_of(g(3), p0) and "told at once" not in out and rd(b + 3)["metadata"]["needs"] == ["osprey-x"]
          and [l["status"] for l in rd(b + 3)["metadata"]["steps"]] == ["done"], (pushes()[p0:], out, rd(b + 3)["metadata"]))
    p0 = len(pushes()); out = server._update(g(4), next="osprey-x: halfway there", sender="osprey-x"); settle()
    check(f"{mode}: an update by the builder that only sets next (still named, no work done) tells the owner nothing", not to_front_of(g(4), p0) and "told at once" not in out, (pushes()[p0:], out))
    p0 = len(pushes()); out = server._update(g(5), subject="[home] item %d renamed" % (b + 5), sender="osprey-x"); settle()
    check(f"…{mode}: nor does a filing edit", not to_owner(A, g(5), p0), pushes()[p0:])
    p0 = len(pushes()); out = server._update(g(6), needs=["osprey-main"], next="osprey-main: over to you", sender="osprey-x"); settle()
    hb = [x for x in to_owner(A, g(6), p0)]
    check(f"owner told, {mode}: the builder hands the item back to the owner alone: stackshot hands nothing to a front agent by itself, and the builder is the writer, so nobody is told; the reply says so and nothing is recorded or pushed",
          "nobody is told: a front agent is not handed an item on stackshot's own motion" in out and "told it is back with them alone" not in out and "told at once" not in out and not hb
          and not [x for x in pushes()[p0:] if "back with" in x[1]], (pushes()[p0:], out))
    fy.set_flag(g(5), "mute"); p0 = len(pushes()); out = server._update(g(5), needs=["external"], next="Oliver: builder done", wait_event="the review", ask_by=ABY, sender="osprey-x"); settle()
    check(f"{mode}: a muted item hands a step back, and nobody tells the owner", not to_owner(A, g(5), p0) and "told at once" not in out, (pushes()[p0:], out))
    item(b + 9, needs=["osprey-x"]); fy.set_flag(g(9), "mute"); p0 = len(pushes()); out = cl(b + 9); settle()
    check(f"…{mode}: nor does a muted item's close", not to_owner(A, g(9), p0) and "told at once" not in out, (pushes()[p0:], out))
    p0 = len(pushes()); out = cl(b + 7); settle()
    check(f"owner that is not a front agent, {mode}: a close by the builder is told as before, once, unmarked (the older notice; this change adds no second line)",
          len(to_owner(B, g(7), p0)) == 1 and "[for Oliver]" not in to_owner(B, g(7), p0)[0], (pushes()[p0:], out))
    p0 = len(pushes()); out = server._update(g(8), work={"state": "done"}, sender="osprey-x"); settle()
    check(f"no step line, {mode}: a step marked done by a status done on an item a background owner owns hands nothing back and tells the owner nothing (its mover gets the same board notice as for done=[n] on its last step, which it always got)",
          not [x for x in pushes()[p0:] if re.search(rf"\b{g(8)}\b", x[1]) and "handed back" in x[1]] and not to_owner(B, g(8), p0) and "told at once" not in out
          and all(x[1].startswith("[board]") and "removed their next lines" in x[1] for x in pushes()[p0:]), (pushes()[p0:], out))
cfg(live=True)
# marking work lines done, one by one or the last one, pushes nothing to the owner: the record is the item's History
item(90, needs=["osprey-x"], next="osprey-x: one\nosprey-x: two\nosprey-x: three"); item(91, needs=["osprey-x"], next="osprey-x: mine\nosprey-docs: theirs")
p0 = len(pushes()); outs = []
for k in ("one", "two", "three"):
    outs.append(server._update("a90", work={"state": "done"}, sender="osprey-x")); settle()
    check(f"work lines, {k} of three marked done: nothing is pushed to the owner", not to_front_of("a90", p0) and "told at once" not in outs[-1], (pushes()[p0:], outs[-1]))
check("...the third (the builder's whole step is done): still nothing pushed to the front agent owner, and every line is done on the item", not to_front_of("a90", p0)
      and [l["status"] for l in rd(90)["metadata"]["steps"]] == ["done"] * 3 and "step came back" not in outs[-1], (pushes()[p0:], outs[-1]))
p0 = len(pushes()); out = server._update("a91", work={"state": "done"}, sender="osprey-x"); settle()
check("...a line of another agent still open: the builder's own last line done pushes nothing either", not to_front_of("a91", p0), (pushes()[p0:], out))
# (a) to (c): a builder leaving needs while another session stays, its last work line, and the hand-back's one line, are in router_live_scenario (it has a second background agent)
# (d) another session closes the item while a second session is still named in its needs: the owner still gets the close line
item(66, needs=["osprey-x", "osprey-docs"]); p0 = len(pushes()); outd = cl(66); settle()
check("(d) a close by another session: the front agent owner still gets its one marked close line", to_owner(A, "a66", p0) == [f"[for Oliver] [stackshot] a66 [home] item 66: closed by osprey-x: done (PR 14 is live) \u2192 {BOARD}/items/a66"]
      and "told at once that it was closed" in outd, (pushes()[p0:], outd))
# the done check's own close tells a front agent owner too
CHK = "item_closed a99"
item(92); item(93); item(94, owner="Oliver"); item(95, owner="an-outside-party"); item(96)
fy.set_flag("a93", "mute")
p0 = len(pushes()); server._check_close("a92", server._load("a92"), CHK, time.time()); settle()
check("done check: its close tells the front agent owner at once, one marked line, the same shape as a session's close with the check as the closer",
      len(to_owner(A, "a92", p0)) == 1 and to_owner(A, "a92", p0)[0].startswith("[for Oliver] [stackshot] a92 [home] item 92: closed by stackshot's done check: done (done check passed: ")
      and to_owner(A, "a92", p0)[0].endswith(f") \u2192 {BOARD}/items/a92"), pushes()[p0:])
# Oliver not there for the pane: the same close tells nobody (the item's close revision is the board's record), and the routing log says it was held
PRESENT[0] = False; item(67, needs=["osprey-x"]); p0 = len(pushes()); n0 = len(routing.read("projects/alpha")); outh = cl(67); settle(); PRESENT[0] = True
check("Oliver not there for the pane: a close tells the front agent owner nothing, the reply still names it, and the routing log holds a line ruled `held` for it",
      not to_owner(A, "a67", p0) and rd(67)["status"] == "completed"
      and [n for n in routing.read("projects/alpha")[n0:] if n.get("ruling") == "held" and "a67" in str(n.get("label", "")) + str(n.get("text", ""))], (pushes()[p0:], routing.read("projects/alpha")[n0:], outh))
p0 = len(pushes()); server._check_close("a93", server._load("a93"), CHK, time.time()); settle()
check("…a muted item: the owner is not told", not to_owner(A, "a93", p0), pushes()[p0:])
p0 = len(pushes()); server._check_close("a94", server._load("a94"), CHK, time.time()); server._check_close("a95", server._load("a95"), CHK, time.time()); settle()
check("…the owner Oliver, or a name that is no session: nobody is marked for it", not [x for x in pushes()[p0:] if ("a94" in x[1] or "a95" in x[1]) and "[for Oliver]" in x[1]], pushes()[p0:])
# the other small gaps: [board] tell_owner off, and an owner that is Oliver or no session, on a close and on a handed-back step
_cfg.CFG.setdefault("board", {})["tell_owner"] = False
item(97, needs=["osprey-x"], next="osprey-x: only"); item(98, needs=["external", "osprey-x"])
p0 = len(pushes()); server._check_close("a96", server._load("a96"), CHK, time.time()); out = cl(97); outh = server._update("a98", needs=["external"], next="Oliver: handed back", wait_event="the review", ask_by=ABY, sender="osprey-x"); settle()
check("tell_owner off: a done check's close, a session's close and an item back with the owner alone tell the front agent owner nothing", not [x for x in pushes()[p0:] if x[0] == A and re.search(r"a9[678]\b", x[1]) and x[1].startswith("[for Oliver]")]
      and "told at once" not in out + outh, (pushes()[p0:], out, outh))
_cfg.CFG["board"]["tell_owner"] = True
item(99, owner="Oliver", needs=["osprey-x"], next="osprey-x: only"); item(64, owner="an-outside-party", needs=["osprey-x"], next="osprey-x: only")
p0 = len(pushes()); outs = [server._update("a99", work={"state": "done"}, sender="osprey-x"), server._update("a64", work={"state": "done"}, sender="osprey-x"), cl(99), cl(64)]; settle()
check("an owner that is Oliver or no session (an outside party's name): a close tells nobody marked, and the reply does not say it told one", not [x for x in pushes()[p0:] if re.search(r"a(99|64)\b", x[1]) and x[1].startswith("[for Oliver]")]
      and not any("told at once" in o for o in outs), (pushes()[p0:], outs))
cfg(live=True)

# ---- 3. a decision row; his own board answer takes it off and makes none
settle(); cfg(live=True); p0 = len(pushes())
server._update("a10", needs=["decision"], ask=ASK, next="Oliver: make the call", sender="osprey-x"); settle()
d10 = of("a10", "decision")
check("needs=decision on an item with no words on it: a decision row with the question", len(d10) == 1 and d10[0]["what"] == "needs your decision: whether to ship", d10)
check("…nothing is pushed to the front agent for it", not to_front(p0), pushes()[p0:])
server._update("a11", needs=["decision"], ask=ASK, next="Oliver: wait", sender="osprey-x"); mute_before = len(rows())
fy.set_flag("a12", "mute"); server._update("a12", needs=["decision"], ask=ASK, next="Oliver: wait", sender="osprey-x")
check("…a muted item with a decision asked makes no row", not of("a12"), of("a12"))
server._update("a10", needs=[], next="osprey-x: back on the owner", sender="osprey-x")
check("the decision leaves the item's needs another way (a session cleared it): its row goes", not of("a10", "decision"), of("a10"))
d11 = of("a11", "decision"); check("a11's decision row is there", len(d11) == 1)

# ---- 4. reopen, a failed check
server._update("a1", status="open", next="osprey-x: one more thing", sender="osprey-x")
check("a reopen of a watched item: a reopened row", len(of("a1", "reopened")) == 1 and of("a1", "reopened")[0]["what"].startswith("reopened by osprey-x"), of("a1"))
it21 = server._load("a21"); n21 = len(of("a21"))
server._check_fail("a21", it21, "pr_merged https://example.invalid/pr/1", "the pull request was closed unmerged", time.time())
c21 = of("a21", "check_failed")
check("a check that can no longer pass: a check_failed row naming it and why", len(c21) == 1 and "can no longer end: the pull request was closed unmerged" in c21[0]["what"], c21)
check("an unrelated save of the same item makes no second one", (server._update("a21", next="osprey-x: again", sender="osprey-x"), len(of("a21", "check_failed")))[1] == 1, of("a21"))

# ---- 5. a due date within 24 h: one urgent row, one Slack post
import datetime as dt
ZONE = dt.timezone(dt.timedelta(hours=ZONE_HOURS))
def due_item(i, days, **meta):
    d = (dt.datetime.fromtimestamp(now0, ZONE) + dt.timedelta(days=days)).strftime("%Y-%m-%d")
    item(i, **{"due": d}, **meta); return d
d_soon = due_item(30, 0, said=SAID); due_item(31, 0); due_item(32, 0, said=SAID); due_item(33, 10, said=SAID); due_item(34, -10, said=SAID); due_item(35, -0, answers=ANS)
fy.set_flag("a32", "mute")
end30 = server._wt.due_epoch(d_soon)
slack.clear(); server._FORYOU_LAST[0] = 0.0
pub0 = pub[0]
made = server._foryou_tick(end30 - 10 * 3600); server._fyslack._foryou_slack_wait()      # the Slack post is the worker thread's: wait for its queue
due = lambda g: of(g, "due")
check("the board is republished (the debounced _publish) after a due-date pass that made rows", made and pub[0] == pub0 + 1, (made, pub0, pub))
check("a due date ending in 10 h on a watched item: one urgent due row", made.count("a30") == 1 and len(due("a30")) == 1 and due("a30")[0]["urgent"] and due("a30")[0]["what"].startswith("due "), (made, due("a30")))
check("…an unwatched item with a due date makes none, nor a muted one", not due("a31") and not due("a32"), rows())
check("…a due date 10 days off and one 10 days past make none (the first pass after a deploy must not raise every old overdue item)", not due("a33") and not due("a34"))
check("…an item with his board answer and a near due date is watched: a row", len(due("a35")) == 1)
check("…each urgent row was posted to Slack once, with the text and the link", len(slack) == 2 and all(s.startswith("[stackshot] For you (urgent): ") and "/items/" in s for s in slack) and all(r["slacked"] for r in (due("a30")[0], due("a35")[0])), (slack, due("a30")))
server._FORYOU_LAST[0] = 0.0; made2 = server._foryou_tick(end30 - 10 * 3600 + 3600); server._fyslack._foryou_slack_wait()
check("the next pass makes no second row and posts nothing again", made2 == [] and len(due("a30")) == 1 and len(slack) == 2, (made2, slack))
server._FORYOU_LAST[0] = 0.0; made3 = server._foryou_tick(end30 + 3600)
check("an hour after the due date's end the same due date still has its one row (a due date makes one row, overdue or not)", made3 == [] and len(due("a30")) == 1)
check("a pass within five minutes of the last does nothing", server._foryou_tick(end30 - 10 * 3600) == [])
fy.seen(str(due("a30")[0]["id"])); server._FORYOU_LAST[0] = 0.0; made4 = server._foryou_tick(end30 - 10 * 3600 + 3600)
check("a due row he marked seen does not come back for the same due date", made4 == [] and not due("a30"), (made4, due("a30")))

# ---- 6. a failed release makes no row: the message still goes on to the project
slack.clear(); n_before = len(rows()); pub1 = pub[0]
rel = "[release] PR #16 FAILED at the restart: stackshot.service did not come back"
delivered = []; real_message = server._message
server._message = lambda to, text, sender, *a, **k: delivered.append((to, text, sender)) or "delivered"
try:
    with TestClient(server.mcp.http_app(), base_url=BOARD) as c0:
        tok0 = open(__import__("stackshot.fleet.client", fromlist=["_"]).mint(socket.gethostname())).read().strip()
        H0 = {"Authorization": "Bearer " + tok0}
        st0 = c0.post("/client/message", json={"to": "projects/example", "text": rel, "sender": "release"}, headers=H0)
        check("a failed release message from release.sh makes no For you row, posts nothing to Slack and republishes nothing", len(rows()) == n_before and not slack and pub[0] == pub1 and not [r for r in rows() if "FAILED" in r["what"]], (st0.status_code, rows(), slack))
        check("…and is still delivered to the project as a message, text and sender unchanged", st0.status_code == 200 and delivered == [("projects/example", rel, "release")], (st0.status_code, st0.text[:200], delivered))
        c0.post("/client/message", json={"to": "projects/example", "text": "[release] PR #17 merged and released at abc123", "sender": "release"}, headers=H0)
        c0.post("/client/message", json={"to": "projects/example", "text": rel.replace("231", "233"), "sender": "home-beta"}, headers=H0)
        check("a release that went well and a failure told by another sender: no row either, both delivered", len(rows()) == n_before and len(delivered) == 3, (rows(), delivered))
finally:
    server._message = real_message
check("release_failed is no longer a kind, and the helper that made its rows is gone", "release_failed" not in fy.KINDS and not hasattr(server, "_foryou_release_failed"))
try: fy.add(key="rf:new", kind="release_failed", what="x"); check("foryou.add refuses the retired kind", False)
except ValueError: check("foryou.add refuses the retired kind", True)

def urgent(text, key=None, **kw):
    """An urgent row for the Slack tests below (a due row stands in for what a failed release used to make)."""
    row = fy.add(key=key or f"urgent:{text}", kind="due", what=text, urgent=True, **kw)
    if row: server._fyslack._foryou_slack(row)
    return row

server._fyslack._foryou_slack_wait()

# ---- 7. the stub every later section reads
server._wt.cap_needs_owner = lambda: False
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((tag, gid, owner, note))

# ---- 8. the board page, the item page, the routes
fy.seen("all")
for k, (g, w, ts) in enumerate((("a50", "older row", now0 - 7200), ("a51", "newer row <b>&", now0 - 60))):
    fy.add(key=f"page:{k}", kind="closed", gid=g, item=g, project="projects/alpha", what=w, url=f"{BOARD}/items/{g[1:]}", urgent=(k == 1), ts=ts)
B_ = ui_render.Board(str(T / "store"))
html_ = B_.for_you_html()
check("the board's For you section is always drawn, with a count", '<section id="for-you"' in html_ and "For you" in html_ and ">2<" in html_, html_[:300])
check("…newest first: the newer row comes before the older", 0 < html_.index("newer row") < html_.index("older row"), html_)
check("…each row has the item link, what happened (escaped), the time in the instance timezone and a seen form",
      'class="fy-id" href="/items/a51"' in html_ and 'class="fy-seen"' in html_ and "newer row" in html_, html_[:600])
check("…text from a row is escaped", "newer row &lt;b&gt;&amp;" in html_ and "<b>&" not in html_)
local_when = dt.datetime.fromtimestamp(now0 - 60, ZONE).strftime("%H:%M")
check("…the time shown is in the instance timezone", local_when in html_, (local_when, html_))
check("…an urgent row is marked; each row has a seen form posting to /for-you/seen; a mark-all form when there are several",
      "urgent" in html_ and html_.count('action="/for-you/seen"') >= 3 and 'value="all"' in html_, html_)
fy.seen("all"); empty = B_.for_you_html()
check("an empty list says so and keeps the section (the live page swaps blocks in place, so the block set must not change)", 'id="for-you"' in empty and "nothing new for you" in empty, empty)
fy.add(key="page:hid", kind="closed", gid="a52", item="a52", project="projects/alpha", what="row behind the hidden section", url=f"{BOARD}/items/52", ts=now0)
full = B_.html()
_blocks = re.search(r'<meta name="stackshot-blocks" content="([^"]*)">', full).group(1)
_body = full.split("<body", 1)[1]       # the style sheet in the head keeps its unused For you rules; the body is what is shown
check("the full board page does not show the For you section while _SHOW_FOR_YOU in ui/render.py is off: no section, heading, seen form, seen script, jump link or block fingerprint (the home fold script names the old for-you key it removes)",
      ui_render._SHOW_FOR_YOU is False and 'id="for-you"' not in _body and "For you" not in _body and "fy-" not in _body and "for-you" not in _body.replace(ui_render._HOME_FOLD_JS, "")
      and ui_render._FORYOU_JS not in full and "for-you" not in [p.split("=")[0] for p in _blocks.split()], _blocks)
check("…the row is still recorded (display only): the list holds it", any(r["what"] == "row behind the hidden section" for r in fy.rows()), fy.rows())
ui_render._SHOW_FOR_YOU = True
try: full_on = B_.html()
finally: ui_render._SHOW_FOR_YOU = False
check("…the one switch brings the section back after the status block and before Your move, with its seen script and its block fingerprint", 'id="for-you"' in full_on and full_on.index('id="status"') < full_on.index('id="for-you"') < full_on.index('id="your-move"') and ui_render._FORYOU_JS in full_on
      and "for-you" in [p.split("=")[0] for p in re.search(r'<meta name="stackshot-blocks" content="([^"]*)">', full_on).group(1).split()])
fy.seen(str(next(r["id"] for r in fy.rows() if r["what"] == "row behind the hidden section")))

COOKIE = _signin._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
SAME = {"Origin": BOARD}
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def post(path, data, headers=SAME, cookie=COOKIE):
        c.cookies.clear()
        if cookie: c.cookies.set(_signin._UI_COOKIE, cookie)
        return c.post(path, data=data, headers=headers, follow_redirects=False)
    def page(path, cookie=COOKIE):
        c.cookies.clear()
        if cookie: c.cookies.set(_signin._UI_COOKIE, cookie)
        return c.get(path)
    wtok = lambda g: server._watch_token(EMAIL, g)
    atok = lambda g: server._answer_token(EMAIL, g)
    g_in, g_out = page("/items/a51"), page("/items/a51", cookie=None)
    check("the item page, signed in, carries the For you control: Watch, Mute and Default, with this item's token",
          g_in.status_code == 200 and 'class="iwatch"' in g_in.text and 'action="/items/a51/watch"' in g_in.text and f'value="{wtok("a51")}"' in g_in.text
          and all(f'value="{m}"' in g_in.text for m in ("watch", "mute", "default")), g_in.status_code)
    check("…not signed in: no control", 'class="iwatch"' not in g_out.text, g_out.status_code)
    before = fy.flags()
    r_anon = post("/items/a51/watch", {"token": wtok("a51"), "mode": "mute"}, cookie=None)
    r_tok = post("/items/a51/watch", {"token": wtok("a52"), "mode": "mute"})
    r_none = post("/items/a51/watch", {"mode": "mute"})
    r_evil = post("/items/a51/watch", {"token": wtok("a51"), "mode": "mute"}, headers={"Origin": "https://evil.example.net"})
    r_ans = post("/items/a51/watch", {"token": atok("a51"), "mode": "mute"})
    check("the watch route refuses (403) a visitor not signed in, another item's token, no token, another origin and the answer form's token; nothing changes",
          [r.status_code for r in (r_anon, r_tok, r_none, r_evil, r_ans)] == [403] * 5 and fy.flags() == before, [r.status_code for r in (r_anon, r_tok, r_none, r_evil, r_ans)])
    check("an unknown item is 404; a bad mode is 400", post("/items/a49/watch", {"token": wtok("a17"), "mode": "mute"}).status_code == 404 and post("/items/a51/watch", {"token": wtok("a51"), "mode": "loud"}).status_code == 400)
    r_ok = post("/items/a51/watch", {"token": wtok("a51"), "mode": "mute"})
    check("Mute from the item page: 303 back to the item, the flag stored", r_ok.status_code == 303 and r_ok.headers["location"] == "/items/a51" and fy.flag("a51") == "mute", (r_ok.status_code, r_ok.headers.get("location")))
    check("…the page now shows it muted, with its button disabled", "Muted" in page("/items/a51").text and re.search(r'<button[^>]*value="mute"[^>]*disabled', page("/items/a51").text) is not None)
    post("/items/a51/watch", {"token": wtok("a51"), "mode": "watch"}); check("Watch stores watch", fy.flag("a51") == "watch")
    post("/items/a51/watch", {"token": wtok("a51"), "mode": "default"}); check("Default removes the flag", fy.flag("a51") == "")
    # the seen route
    fy.seen("all")
    ra = fy.add(key="seen:a", kind="closed", gid="a50", item="a50", project="p", what="one", url="")
    rb = fy.add(key="seen:b", kind="closed", gid="a50", item="a50", project="p", what="two", url="")
    os.environ["STACKSHOT_AUTH"] = "oauth"      # auth off (this suite's default) leaves the whole board open, the seen route with it
    try: s_anon = post("/for-you/seen", {"id": str(ra["id"])}, cookie=None)
    finally: os.environ["STACKSHOT_AUTH"] = "off"
    s_evil = post("/for-you/seen", {"id": str(ra["id"])}, headers={"Origin": "https://evil.example.net"})
    s_bad = post("/for-you/seen", {"id": "x1"})
    check("the seen route refuses (403) a visitor not signed in and a foreign origin, and a bad id is 400; nothing cleared", s_anon.status_code == 403 and s_evil.status_code == 403 and s_bad.status_code == 400 and len(rows()) == 2, (s_anon.status_code, s_evil.status_code, s_bad.status_code))
    s_ok = post("/for-you/seen", {"id": str(ra["id"])})
    check("seen clears that row only, then 303 to the board's For you section", s_ok.status_code == 303 and s_ok.headers["location"] == "/#for-you" and [r["what"] for r in rows()] == ["two"], (s_ok.status_code, s_ok.headers.get("location"), rows()))
    s_all = post("/for-you/seen", {"id": "all"}); check("seen all clears the list", s_all.status_code == 303 and rows() == [])
    # his own board answer: a decision row goes, none is made
    cfg(live=True); server._update("a52", needs=["decision"], ask=YESNO, next="Oliver: wait", sender="osprey-x")
    server._update("a53", needs=["decision"], ask=YESNO, next="Oliver: wait", sender="osprey-x")
    check("(setup) a52 and a53 each have a decision row", len(of("a52", "decision")) == 1 and len(of("a53", "decision")) == 1, rows())
    n_rows = len(rows())
    r_ans = post("/items/a52/answer", {"token": atok("a52"), "act": "answer", "text": "go ahead"})
    check("his answer on the board takes the item's decision row off the list and makes no row of its own", r_ans.status_code == 303 and not of("a52") and len(rows()) == n_rows - 1 and of("a53", "decision"), (r_ans.status_code, rows()))
    # the client API
    tok = open(__import__("stackshot.fleet.client", fromlist=["_"]).mint(socket.gethostname())).read().strip(); H = {"Authorization": "Bearer " + tok}
    fy.set_flag("a51", "mute")
    rr_ = c.get("/client/for-you", headers=H); rn_ = c.get("/client/for-you")
    js = rr_.json() if rr_.status_code == 200 else {}
    check("GET /client/for-you needs the machine token, then returns JSON: rows (newest first) and the flags by shown id", rn_.status_code == 401 and rr_.status_code == 200
          and js.get("rows") and js["rows"][0]["item"] == "a53" and set(js["rows"][0]) >= {"id", "kind", "item", "project", "what", "url", "urgent", "ts", "when", "slacked"}
          and js["flags"] == fy.flags() and js["flags"].get("a51") == "mute" and js["flags"].get("a7") == "watch" and "generated" in js, (rr_.status_code, rr_.text[:400]))
    check("…each row's `when` is an ISO time in the instance timezone (+04:00)", all(r["when"].endswith(f"+{ZONE_HOURS:02d}:00") for r in js.get("rows", [])), js.get("rows"))
    import urllib.request, urllib.error; from stackshot.fleet import client
    class _Resp:
        def __init__(s, r): s.status = r.status_code; s._b = r.content
        def read(s): return s._b
        def __enter__(s): return s
        def __exit__(s, *a): return False
    def fake_urlopen(req, timeout=0):
        path = req.full_url.replace(client.server_url(), "")
        r = (c.post(path, content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(path, headers=dict(req.header_items())))
        if r.status_code >= 400: raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
        return _Resp(r)
    client.urllib.request.urlopen = fake_urlopen
    so, se = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se): rc = client.main(["client.py", "get", "for-you"])
    out_js = json.loads(so.getvalue()) if so.getvalue().strip() else {}
    check("client.py get for-you prints that JSON and exits 0", rc == 0 and out_js.get("flags") == fy.flags() and [r["id"] for r in out_js.get("rows", [])] == [r["id"] for r in js["rows"]] and se.getvalue() == "", (rc, so.getvalue()[:300], se.getvalue()))
    # ---- the web server's two machine-token routes (sala's home-term: the token, no cookie, no page token): seen and watch
    host = socket.gethostname()
    _cfg.CFG["project_agent"] = {"form_senders": ["fleet-web"], "form_machines": [host]}          # the form's caller: this label from this machine only
    H_other = {"Authorization": "Bearer " + open(client.mint("other-box")).read().strip()}         # a second machine's token, not the form's
    ROW_KEYS = {"id", "kind", "item", "project", "what", "url", "urgent", "ts", "when", "slacked"}
    def rpost(path, body, hd=H): return c.post(path, json=body, headers=hd)
    def state(): return (json.dumps(fy.rows(), sort_keys=True), json.dumps(fy.flags(), sort_keys=True))
    def get_fy(): return c.get("/client/for-you", headers=H).json()
    def quiet(fn, *a, **k):
        e = io.StringIO()
        with contextlib.redirect_stderr(e): r = fn(*a, **k)
        return r, e.getvalue()
    keep_rows = [dict(r) for r in fy.rows()]; fy.seen("all")
    ids = [fy.add(key=f"web:{n}", kind="closed", gid="a50", item="a50", project="projects/alpha", what=f"web row {n}", url="")["id"] for n in (1, 2, 3, 4)]
    # no token, a wrong token
    s0, p0 = state(), pub[0]
    anon = [c.post(p, json=b) for p, b in (("/client/for-you/seen", {"id": ids[0], "sender": "fleet-web"}), ("/client/items/a51/watch", {"state": "mute", "sender": "fleet-web"}))]
    bad_tok = [c.post(p, json=b, headers={"Authorization": "Bearer " + "x" * 40}) for p, b in (("/client/for-you/seen", {"id": ids[0], "sender": "fleet-web"}), ("/client/items/a51/watch", {"state": "mute", "sender": "fleet-web"}))]
    check("web routes: no token or an unknown token is 401 on both; nothing changes", [r.status_code for r in anon + bad_tok] == [401] * 4 and state() == s0, [r.status_code for r in anon + bad_tok])
    # who may call: a wrong sender from the right machine, the right sender from the wrong machine, either one on an unknown item/row (the refusal comes first)
    calls = [("/client/for-you/seen", {"id": ids[0], "sender": "osprey-x"}, H), ("/client/for-you/seen", {"id": "all", "sender": "fleet-web"}, H_other),
             ("/client/for-you/seen", {"id": 99999, "sender": "home-web"}, H),
             ("/client/items/a51/watch", {"state": "mute", "sender": "osprey-x"}, H), ("/client/items/a51/watch", {"state": "mute", "sender": "fleet-web"}, H_other),
             ("/client/items/a49/watch", {"state": "mute", "sender": "FLEET-WEB"}, H)]
    res = [rpost(*a) for a in calls]
    check("web routes: a wrong sender (right machine) and the right sender from another machine are 403 with a reason, on both routes, before any 404; nothing changes",
          [r.status_code for r in res] == [403] * 6 and all("web form" in r.json().get("error", "") and "form_machines" in r.json()["error"] for r in res) and state() == s0 and pub[0] == p0,
          [(r.status_code, r.text[:120]) for r in res])
    check("web routes: a sender that is missing, not a string or not one line is 400; a body that is not a JSON object is 400",
          [rpost("/client/for-you/seen", b).status_code for b in ({"id": ids[0]}, {"id": ids[0], "sender": 5}, {"id": ids[0], "sender": ""}, {"id": ids[0], "sender": "a\nb"})] == [400] * 4
          and rpost("/client/items/a51/watch", {"state": "mute"}).status_code == 400
          and c.post("/client/for-you/seen", content=b"[1]", headers=H).status_code == 400 and c.post("/client/items/a51/watch", content=b"not json", headers=H).status_code == 400
          and state() == s0)
    # seen: a bad body is 400, an unknown row 404
    bad_ids = [{"sender": "fleet-web"}] + [{"id": v, "sender": "fleet-web"} for v in ("x1", "", 0, -3, True, 1.5, None, [1], "ALL", "3")]
    check("seen: a missing, non-numeric, zero, negative, boolean, fractional, null, list, \"ALL\" or numeric-string id is 400; nothing cleared",
          [rpost("/client/for-you/seen", b).status_code for b in bad_ids] == [400] * len(bad_ids) and state() == s0, [rpost("/client/for-you/seen", b).status_code for b in bad_ids])
    r_nf = rpost("/client/for-you/seen", {"id": 99999, "sender": "fleet-web"})
    check("seen: a row id that is on no list is 404 with a reason; nothing cleared, nothing published", r_nf.status_code == 404 and r_nf.json().get("error") and state() == s0 and pub[0] == p0, (r_nf.status_code, r_nf.text))
    # seen: one row
    (r_one, log_one) = quiet(rpost, "/client/for-you/seen", {"id": ids[1], "sender": "fleet-web"})
    js1 = r_one.json()
    check("seen: one row → 200 {ok, seen: [that id], rows: the rows still unseen, newest first, in GET /client/for-you's shape}",
          r_one.status_code == 200 and set(js1) == {"ok", "seen", "rows"} and js1["ok"] is True and js1["seen"] == [ids[1]]
          and [r["id"] for r in js1["rows"]] == [ids[3], ids[2], ids[0]] and all(set(r) == ROW_KEYS for r in js1["rows"]) and js1["rows"] == get_fy()["rows"]
          and [r["id"] for r in fy.rows()] == [ids[3], ids[2], ids[0]], (r_one.status_code, r_one.text[:400]))
    check("…it was logged to stderr with the sender and the board was published (debounced _publish)", "fleet-web" in log_one and str(ids[1]) in log_one and pub[0] == p0 + 1, (log_one, pub[0] - p0))
    check("…the same row again is now 404 (it is no longer on the list)", rpost("/client/for-you/seen", {"id": ids[1], "sender": "fleet-web"}).status_code == 404)
    # seen: all
    p1 = pub[0]
    (r_all, log_all) = quiet(rpost, "/client/for-you/seen", {"id": "all", "sender": "fleet-web"})
    ja = r_all.json()
    check("seen \"all\": 200, `seen` lists every id that was on the list (ascending), `rows` is empty, the list is empty", r_all.status_code == 200 and ja == {"ok": True, "seen": [ids[0], ids[2], ids[3]], "rows": []}
          and fy.rows() == [] and get_fy()["rows"] == [], (r_all.status_code, r_all.text[:300]))
    check("…logged with the sender and published", "fleet-web" in log_all and pub[0] == p1 + 1, (log_all, pub[0] - p1))
    p2 = pub[0]; r_all2 = rpost("/client/for-you/seen", {"id": "all", "sender": "fleet-web"})
    check("\"all\" on an empty list is 200 with nothing marked (and nothing to publish)", r_all2.status_code == 200 and r_all2.json() == {"ok": True, "seen": [], "rows": []} and pub[0] == p2, r_all2.text)
    # watch: an item as shown (board#N), by its number, and by its store id
    (T / "store/g").mkdir(exist_ok=True); shutil_copy = (T / "store/a/51.json").read_text(); (T / "store/g/9160.json").write_text(shutil_copy.replace('"id": "51"', '"id": "9160"'))
    fy.set_flag("a51", "mute"); fy.set_flag("a7", "watch"); w0 = dict(fy.flags())
    p3 = pub[0]
    (r_w, log_w) = quiet(rpost, "/client/items/board%239160/watch", {"state": "watch", "sender": "fleet-web"})
    jw = r_w.json()
    check("watch: board#<a> (percent-encoded in the path) → 200 {ok, item: \"board#<a>\", state: \"watch\", flags: the whole map by shown id}",
          r_w.status_code == 200 and set(jw) == {"ok", "item", "state", "flags"} and jw["ok"] is True and jw["item"] == f"board#{BID_A}" and jw["state"] == "watch"
          and jw["flags"] == {**fy.payload(server._gh.shown)["flags"]} and jw["flags"].get(f"board#{BID_A}") == "watch" and jw["flags"].get("a51") == "mute" and jw["flags"].get("a7") == "watch",
          (r_w.status_code, r_w.text[:300]))
    check("…the flag is stored under the store id, is visible in GET /client/for-you, and the change is logged with the sender and published",
          fy.flag("g9160") == "watch" and get_fy()["flags"] == jw["flags"] and "fleet-web" in log_w and f"board#{BID_A}" in log_w and pub[0] == p3 + 1, (fy.flags(), log_w, pub[0] - p3))
    r_w2 = rpost("/client/items/9160/watch", {"state": "mute", "sender": "fleet-web"})
    check("watch: a bare number reads as board#N; mute replaces the flag", r_w2.status_code == 200 and r_w2.json()["item"] == f"board#{BID_A}" and r_w2.json()["state"] == "mute" and fy.flag("g9160") == "mute" and get_fy()["flags"].get(f"board#{BID_A}") == "mute", r_w2.text[:300])
    r_w3 = rpost("/client/items/a51/watch", {"state": "default", "sender": "fleet-web"})
    check("watch: an older store id works; default removes the flag, and the map no longer has it",
          r_w3.status_code == 200 and r_w3.json()["item"] == "a51" and r_w3.json()["state"] == "default" and "a51" not in r_w3.json()["flags"] and fy.flag("a51") == ""
          and "a51" not in get_fy()["flags"] and get_fy()["flags"].get("a7") == "watch", r_w3.text[:300])
    s1 = state(); p4 = pub[0]
    unknown = [rpost(f"/client/items/{k}/watch", {"state": "mute", "sender": "fleet-web"}).status_code for k in ("a17", "board%23999999", "9161", "zzz", "board%23abc")]
    check("watch: an unknown item (a store id, board#N, a number, a word, a bad board id) is 404; nothing changes, nothing published", unknown == [404] * 5 and state() == s1 and pub[0] == p4, unknown)
    bad_states = [{"sender": "fleet-web"}] + [{"state": v, "sender": "fleet-web"} for v in ("loud", "", "WATCH", 5, None, ["mute"])]
    check("watch: a missing or bad state (loud, empty, upper case, a number, null, a list) is 400; nothing changes",
          [rpost("/client/items/a51/watch", b).status_code for b in bad_states] == [400] * len(bad_states) and state() == s1 and pub[0] == p4)
    check("watch: a bad state on an unknown item is 400 (the body is read first), not 404", rpost("/client/items/a49/watch", {"state": "loud", "sender": "fleet-web"}).status_code == 400)
    # the client.py verbs, through the same app
    so, se = io.StringIO(), io.StringIO()
    rows_cli = [fy.add(key=f"web:cli{n}", kind="closed", gid="a50", item="a50", project="projects/alpha", what=f"cli {n}", url="")["id"] for n in (1, 2)]
    with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se): rc = client.main(["client.py", "post", "for-you-seen", "--id", str(rows_cli[0]), "--sender", "fleet-web"])
    j_cli = json.loads(so.getvalue()) if so.getvalue().strip() else {}
    check("client.py post for-you-seen --id N --sender L prints the server's JSON and exits 0", rc == 0 and j_cli.get("seen") == [rows_cli[0]] and [r["id"] for r in j_cli.get("rows", [])] == [rows_cli[1]], (rc, so.getvalue()[:300], se.getvalue()[:300]))
    so, se = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se): rc = client.main(["client.py", "post", "watch", "--item", f"board#{BID_A}", "--state", "watch", "--sender", "fleet-web"])
    j_cli = json.loads(so.getvalue()) if so.getvalue().strip() else {}
    check("client.py post watch --item board#N --state S --sender L prints the server's JSON and exits 0", rc == 0 and j_cli.get("item") == f"board#{BID_A}" and j_cli.get("state") == "watch" and fy.flag("g9160") == "watch" and j_cli.get("flags", {}).get(f"board#{BID_A}") == "watch", (rc, so.getvalue()[:300], se.getvalue()[:300]))
    outs = []
    for argv in (["post", "for-you-seen", "--id", "7", "--sender", "osprey-x"], ["post", "watch", "--item", f"board#{BID_A}", "--state", "mute", "--sender", "osprey-x"],
                 ["post", "for-you-seen", "--id", "9999", "--sender", "fleet-web"], ["post", "watch", "--item", f"board#{BID_B}", "--state", "mute", "--sender", "fleet-web"],
                 ["post", "for-you-seen", "--id", "x", "--sender", "fleet-web"], ["post", "for-you-seen", "--sender", "fleet-web"], ["post", "watch", "--item", f"board#{BID_A}", "--sender", "fleet-web"]):
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se): rc = client.main(["client.py", *argv])
        outs.append((rc, so.getvalue(), se.getvalue()))
    check("client.py: a 403, a 404, a bad id and a missing option each exit 1 with the reason on stderr and nothing on stdout; the flag was not changed by the refused call",
          all(o[0] == 1 and o[1] == "" and o[2] for o in outs) and "form_senders" in outs[0][2] and "form_senders" in outs[1][2] and "404" in outs[2][2] and "404" in outs[3][2] and fy.flag("g9160") == "watch", outs)
    # put everything back for the sections that follow
    (T / "store/g/9160.json").unlink(); fy.set_flag("g9160", "default"); fy.set_flag("a51", "mute"); fy.seen("all")
    for r in keep_rows: fy.add(key=r["key"] + ":restored", kind=r["kind"], gid=r["gid"], item=r["item"], project=r["project"], what=r["what"], url=r["url"], urgent=r["urgent"], ts=r["ts"])
    _cfg.CFG.pop("project_agent", None)
check("the server's own read gives the same", server._client_get("for-you", {})[0] == 200 and json.loads(server._client_get("for-you", {})[2])["flags"] == fy.flags())

# ---- 9. a Slack post that failed is tried again on the next pass, then marked; at most three tries; only young rows; only with a Slack path
fy.seen("all")
posts = []; script = ["boom: network down", ""]      # the first post fails, the second goes
server._fyslack._for_you_slack_post = lambda text: (posts.append(text), script.pop(0) if script else "")[1]
err9 = io.StringIO()
with contextlib.redirect_stderr(err9):
    urgent("PR #18 FAILED at the build: it broke"); server._fyslack._foryou_slack_wait()
byid = lambda rid: fy.row_by_id(rid)
r9 = next(r for r in rows() if "PR #18" in r["what"])
check("a Slack post that failed: the row stays on the list, unposted, with one try counted, and the failure is logged with the reason",
      not r9["slacked"] and r9["slack_tries"] == 1 and len(posts) == 1 and "row %d not posted to Slack (try 1 of 3" % r9["id"] in err9.getvalue() and "boom: network down" in err9.getvalue(), (r9, err9.getvalue()))
server._fyslack._foryou_slack_wait()
check("…nothing posts it again before the next pass", len(posts) == 1)
server._FORYOU_LAST[0] = 0.0; server._foryou_tick(time.time() + 400); server._fyslack._foryou_slack_wait()
r9 = byid(r9["id"])
check("…the next pass tries it again, and this time it is posted: the row is marked (slacked) with two tries", r9["slacked"] and r9["slack_tries"] == 2 and len(posts) == 2 and posts[0] == posts[1], (r9, posts))
server._FORYOU_LAST[0] = 0.0; server._foryou_tick(time.time() + 800); server._fyslack._foryou_slack_wait()
check("…a posted row is not posted again", len(posts) == 2 and byid(r9["id"])["slack_tries"] == 2)
posts.clear(); server._fyslack._for_you_slack_post = lambda text: (posts.append(text), "still down")[1]
err9 = io.StringIO()
with contextlib.redirect_stderr(err9):
    urgent("PR #22 FAILED at the build: again"); server._fyslack._foryou_slack_wait()
    for k in range(4):
        server._FORYOU_LAST[0] = 0.0; server._foryou_tick(time.time() + 400 * (k + 1)); server._fyslack._foryou_slack_wait()
r9 = next(r for r in rows() if "PR #22" in r["what"])
check("a post that keeps failing is tried three times in all (the first and two retries), then left: unposted, tries stored on the row, every failure logged, the last saying no more tries",
      not r9["slacked"] and r9["slack_tries"] == 3 and len(posts) == 3 and err9.getvalue().count("not posted to Slack") == 3 and "(try 3 of 3, no more tries)" in err9.getvalue(), (r9, len(posts), err9.getvalue()))
posts.clear(); old = fy.add(key="old:slack", kind="due", what="PR #1 FAILED long ago", urgent=True, ts=time.time() - 90000)
server._FORYOU_LAST[0] = 0.0; server._foryou_tick(time.time() + 100); server._fyslack._foryou_slack_wait()
check("a row more than 24 h old is not retried", not posts and not byid(old["id"])["slacked"] and byid(old["id"])["slack_tries"] == 0, (posts, byid(old["id"])))
server._fyslack._for_you_slack_on = lambda: False
fresh = fy.add(key="fresh:slack", kind="due", what="PR #2 FAILED", urgent=True)
server._fyslack._foryou_slack(fresh); server._FORYOU_LAST[0] = 0.0; server._foryou_tick(time.time() + 100); server._fyslack._foryou_slack_wait()
check("with no Slack path set nothing is queued or retried, and nothing is counted", not posts and byid(fresh["id"])["slack_tries"] == 0)
server._fyslack._for_you_slack_on = lambda: True

# ---- 10. a Slack command that hangs is killed with everything it started, and no write or tick waits for it
pidf, kidf, outf = T / "hang.pid", T / "hang.kid", T / "slack.out"
_cfg.CFG["for_you"] = {"slack_command": f"sh -c 'echo $$ > {pidf}; sleep 60 & echo $! > {kidf}; wait'"}
server._fyslack._for_you_slack_post, server._fyslack._for_you_slack_on = REAL_SLACK_POST, REAL_SLACK_ON
server._fyslack._FORYOU_SLACK_TIMEOUT = 1.5
err10 = io.StringIO(); t0 = time.time()
with contextlib.redirect_stderr(err10):
    urgent("PR #23 FAILED at the restart: hung")
    server._FORYOU_LAST[0] = 0.0; server._foryou_tick(time.time() + 400)
    t_enq = time.time() - t0
    server._fyslack._foryou_slack_wait()
t_all = time.time() - t0
r10 = next(r for r in rows() if "PR #23" in r["what"])
check("the row write and the tick only queue the post: both return at once while the command is still running", t_enq < 1.0, t_enq)
check("the hanging command is killed at the timeout (not 60 s): the row has one failed try and the log says it was killed", 1.4 < t_all < 15 and not r10["slacked"] and r10["slack_tries"] == 1 and "did not finish in 1.5 s; killed" in err10.getvalue(), (t_all, r10, err10.getvalue()))
def alive(pid):
    try: st = pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError: return False
    return st != "Z"
pid_, kid_ = int(pidf.read_text()), int(kidf.read_text())
for _ in range(30):
    if not alive(pid_) and not alive(kid_): break
    time.sleep(0.1)
check("…the command and the child it started (a sleep 60 holding its output) are both gone: the whole process group was killed", not alive(pid_) and not alive(kid_), (pid_, kid_))
_cfg.CFG["for_you"] = {"slack_command": f"sh -c 'cat > {outf}'"}
server._fyslack._FORYOU_SLACK_TIMEOUT = 10.0
urgent("PR #25 FAILED at the build: fine"); server._fyslack._foryou_slack_wait()
r11 = next(r for r in rows() if "PR #25" in r["what"])
check("a real command that works gets the text on its standard input and the row is marked (the worker went on after the killed one)",
      r11["slacked"] and r11["slack_tries"] == 1 and "PR #25 FAILED" in outf.read_text(), (r11, outf.read_text() if outf.exists() else None))
_cfg.CFG["for_you"] = {"slack_command": "sh -c 'cat >/dev/null; exit 3'"}
err10 = io.StringIO()
with contextlib.redirect_stderr(err10):
    urgent("PR #26 FAILED at the build: nope"); server._fyslack._foryou_slack_wait()
check("a command that exits non-zero is a failed try with its exit status in the log", "sh exited 3" in err10.getvalue(), err10.getvalue())
_cfg.CFG["for_you"] = {"slack_command": ""}
server._fyslack._for_you_slack_post = lambda text: slack.append(text) or ""; server._fyslack._for_you_slack_on = lambda: True

# ---- 11. a for-you.json that does not parse is moved aside, the list starts empty, ids go on, nothing crashes
fp = fy.path()
fp.write_text('{"rows": [{"id": 4021, "key": "x:closed:1", "what": "cut off here', encoding="utf-8")
err11 = io.StringIO()
with contextlib.redirect_stderr(err11):
    rs = fy.rows()
bad = sorted(fp.parent.glob("for-you.json.bad-*"))
check("a truncated file: no crash, an empty list, no flags (nothing to keep them from), the old file kept as for-you.json.bad-<epoch>, and a log line",
      rs == [] and fy.flags() == {} and len(bad) == 1 and bad[0].read_text().startswith('{"rows": [{"id": 4021') and "does not parse" in err11.getvalue() and bad[0].name in err11.getvalue(), (rs, bad, err11.getvalue()))
r_ = fy.add(key="c:1", kind="closed", what="after the move")
check("…ids go on from the highest id still readable in the bad file (4021 → 4022), and the fresh file is written at once", r_["id"] == 4022 and json.loads(fp.read_text())["seq"] == 4022, (r_, fp.read_text()[:200]))
fp.write_text("not json at all", encoding="utf-8"); t_ = int(time.time())
r_ = fy.add(key="c:2", kind="closed", what="nothing readable")
check("a file with no id to read: the sequence starts from the clock instead, so an id is never given twice", r_["id"] >= t_ and len(sorted(fp.parent.glob("for-you.json.bad-*"))) == 2, (r_, sorted(fp.parent.glob("for-you.json.bad-*"))))
fp.write_bytes(b'\xff\xfe{"rows"'); rs = fy.rows()
check("a file that is not text: moved aside too, no crash", rs == [] and len(sorted(fp.parent.glob("for-you.json.bad-*"))) == 3)
fp.write_text("[1, 2]", encoding="utf-8"); rs = fy.rows()
check("valid JSON of the wrong shape: moved aside too", rs == [] and len(sorted(fp.parent.glob("for-you.json.bad-*"))) == 4)
fp.write_text("{", encoding="utf-8")
check("the surfaces survive a corrupt file: the board section, the client read and a new row", "nothing new for you" in ui_render.Board(str(T / "store")).for_you_html() and server._client_get("for-you", {})[0] == 200
      and fy.add(key="c:3", kind="closed", what="still works") is not None)

# ---- 12. a close with his words whose row could not be written still reaches the owner, the old way, and the reply says so
cfg(live=True); fy.set_flag("a62", "watch")
orig_save = fy._save
def disk_full(d): raise OSError(28, "No space left on device")
t12 = len(told); err12 = io.StringIO()
fy._save = disk_full
try:
    with contextlib.redirect_stderr(err12):
        out60 = cl(60); out62 = cl(62); settle()
        it61 = server._load("a61"); it61["status"] = "completed"; it61["state_updated"] = time.time(); it61["metadata"] = {**it61["metadata"], "outcome": "done", "reason": "its check passed"}
        writes.save("a61", it61); told61 = telling.tell_check_closed("a61", it61, "item_closed a99"); settle()
finally:
    fy._save = orig_save
to_a = lambda g: [(o, n) for _t, _g, o, n in told[t12:] if o == A and g in n]       # tell_woken is section 7's stub: it records what would be pushed
check("the row write fails on a close with his words: no row, the failure is logged, and the old notice goes to the front owner at once, marked [for Oliver]",
      not of("a60") and "for-you: a60 not recorded" in err12.getvalue() and len(to_a("a60 closed by osprey-x (done)")) == 1 and to_a("a60 closed")[0][1].startswith("[for Oliver] [stackshot] a60 closed by osprey-x (done)"),
      (of("a60"), err12.getvalue(), told[t12:]))
check("…the writer's reply says which happened: the list could not be written, so the old notice was sent (not 'a row', not 'not told')",
      "For you list could not be written" in out60 and "sent to osprey-main instead" in out60 and "is a row on his For you list" not in out60 and "not told" not in out60, out60)
check("a watched close with none of his words has no fallback: no row, no old-style notice to the owner (its own marked line of Sun Oct 25th 2026 is the only one)",
      not of("a62") and len(to_a("a62")) == 1 and to_a("a62")[0][1].startswith("[for Oliver] [stackshot] a62 [home] item 62: closed by osprey-x: done") and "For you list" not in out62, (to_a("a62"), out62))
check("the done check's close with his words: same fallback, the mover is in the ids told, and no keeper (the mover alone)", len(to_a("a61 closed by stackshot's done check")) == 1 and A in told61 and len(told61) == 1, (told61, told[t12:]))
out63 = (item(63, said=SAID), cl(63))[1]; settle()
check("(afterwards) with the list writable again the same close is a row, not a notice", len(of("a63", "closed")) == 1 and not to_a("a63 closed") and "is a row on his For you list" in out63, (of("a63"), out63))

# ---- 13. a for-you.json written before this: a release_failed row goes, the other rows stay, ids go on
fp = fy.path()
fp.write_text(json.dumps({"rows": [
    {"id": 41, "key": "release:abc:1", "ts": now0 - 2600, "kind": "release_failed", "gid": "", "item": "", "project": "projects/example", "what": "[release] PR #27 FAILED at the build", "url": "", "urgent": True, "slacked": 1.0, "slack_tries": 1},
    {"id": 40, "key": "a1:closed:1", "ts": now0 - 5000, "kind": "closed", "gid": "a1", "item": "a1", "project": "projects/alpha", "what": "closed by x: old row", "url": "", "urgent": False, "slacked": 0, "slack_tries": 0}],
    "flags": {"a9": "mute"}, "keys": {"release:abc:1": now0 - 2600, "a1:closed:1": now0 - 5000}, "seq": 41}), encoding="utf-8")
rs14 = fy.rows(); pl14 = fy.payload(server._gh.shown)
check("an old file with a release_failed row: the row is not in rows() or the payload, the other row is",
      [r["id"] for r in rs14] == [40] and [r["id"] for r in pl14["rows"]] == [40] and pl14["rows"][0]["what"] == "closed by x: old row", (rs14, pl14))
html14 = ui_render.Board(str(T / "store")).for_you_html()
check("…the board's section draws the old row and not the stale one, and the client read serves it", "old row" in html14 and "PR #27" not in html14 and server._client_get("for-you", {})[0] == 200, html14)
check("…the flags and keys are untouched by the drop", fy.flags() == {"a9": "mute"} and fy.has_key("release:abc:1") and fy.has_key("a1:closed:1"), fy.flags())
r14 = fy.add(key="n:1", kind="closed", gid="a1", item="a1", project="p", what="new")
on_disk = json.loads(fp.read_text())
check("the next save removes the stale row from the file and the ids go on from the highest one, the dropped row's included (41 → 42)",
      [r["id"] for r in on_disk["rows"]] == [40, 42] and r14["id"] == 42 and on_disk["seq"] == 42, on_disk)
fp.write_text(json.dumps({"rows": [{"id": 50, "key": "k", "ts": 1, "kind": "release_failed", "what": "w"}], "flags": {}, "keys": {}, "seq": 0}), encoding="utf-8")
check("a file whose only row is a release_failed one: an empty list, and a new row still gets an id above the dropped one", fy.rows() == [] and fy.add(key="n:2", kind="closed", what="z")["id"] == 51)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
