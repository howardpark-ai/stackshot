"""Scenario test for "a wait written only in words" (a board item's next said with no `after`, and nothing woke its mover after the close) — fixture data, no live store, no network, no server socket.

Oliver picked "A. All three":
  1  REFUSE a next line that defers on another open item in words (once / after / when / until / before / as soon as, then a board#N) unless `after` names that item: the refusal gives the fix
     after=["board#N"]; the lines the write sets are judged, never a stored one; a closed or unknown item, a plain mention, an id before the word and a negation pass; other flagged words stay a flag
  2  A CLOSE tells the mover of each open item whose next or description names the closed item: one batched notice per mover (closed item, outcome, reason, the items that named it), never the
     closer, never an item that has the closed one in `after` (it gets the existing wake), never a closed item; Oliver as mover → the sessions its notices go to
  3  GET shows each board#N the item's next names with its live state (closed with the time and outcome, open with the mover, waiting, not found), the item itself left out

    tests/run-suite item_waits        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="itemwaits-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-peer", "home-lost", "home-beta-front")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time(); DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", **({"gone": "2026-01-01T00:00:00Z"} if n == "home-lost" else {})} for n, u in U.items()}))
def proj(session, agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": proj("home-stew", {"home-front": "the front", "team-back": "the back", "home-other": "the other"}, {"team-back": "the back", "home-other": "the other"})}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
NEW = "- The thing works now\n- It lives here\n- Finished when it ships"
def item(i, owner=None, status="open", letter="g", subject=None, desc=None, **meta):
    base = {"owner": owner or U["home-front"], "project": "projects/alpha", "next": "home-front: do the thing"}
    base.update(meta)
    su = now0 - 10 * DAY
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": desc or DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su, "metadata": base}))
def rd(i, letter="g"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def raw(i, letter="g"): return (T / f"store/{letter}/{i}.json").read_text()
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1200]}" if got is not None else ""))
def refused(name, f, *want, none=()):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want) and not any(w in str(e) for w in none), str(e))
def passes(name, f, *want):
    try:
        out = f(); check(name, all(w in out for w in want), out)
    except Exception as e:
        check(name, False, str(e))
def refused_nw(name, i, f, *want, none=()):
    was = raw(i); refused(name, f, *want, none=none); check(name + " (nothing written)", raw(i) == was, None)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.model import model_guards as mg
from stackshot.service import telling
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
told: list[tuple[str, str, str, str]] = []           # every notice the server sends: (gid(s), recipient, note, tag)
telling.tell_woken = lambda gid, owner, note, tag="wake", result=None: told.append((gid, owner, note, tag))
def close_told(since=0): return [t for t in told[since:] if t[3] == "close"]
def upd(i, **kw): return server._update(f"board#{i}", sender="home-front", **kw)
OWN = server._model.owner_display()
ZONE_HOURS = 4                                  # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
FUT = time.strftime("%Y-%m-%d", time.gmtime(now0 + 5 * DAY + ZONE_HOURS * 3600))
FRONT, PEER, OTHER, BACK = U["home-front"], U["home-peer"], U["home-other"], U["team-back"]

# ================================================================ 1. the words (pure)
DEFERS = [
    ("home-peer: Once Oliver's board#41 steps are done, ship it", ["board#41"]),
    ("home-peer: once board#41 closes, ship it", ["board#41"]),
    ("home-peer: ship it after board#12 closes", ["board#12"]),
    ("home-peer: After board#12 is done: ship it", ["board#12"]),
    ("home-peer: when board#7 is done, tell Robin", ["board#7"]),
    ("home-peer: continue when the review in board#42 lands", ["board#42"]),
    ("home-peer: keep polling until board#3 lands", ["board#3"]),
    ("home-peer: run the check before board#9 ships", ["board#9"]),
    ("home-peer: as soon as board#4 has the result, ask Robin", ["board#4"]),
    ("home-peer: after board#5 and board#6 close, merge", ["board#5", "board#6"]),
    ("- home-peer: **Once** [board#8](https://board.example/items/8) closes", ["board#8"]),
    ("home-peer: ship once the review (board#41) lands", ["board#41"]),
    ("home-peer: once the review, board#41, lands, ship", ["board#41"]),
    ("home-peer: ship it when the work (board#12) is merged", ["board#12"]),
    ("home-peer: board#61が閉じたら配布", ["board#61"]),
    ("home-peer: board#61の完了後に配布してください", ["board#61"]),
    ("home-peer: board#61の段階1が終わったら知らせてください", ["board#61"]),
    ("home-peer: board#61以降に整理", ["board#61"]),
    ("home-peer: board#61まで維持", ["board#61"]),
    ("home-peer: board#61の前に終わらせる", ["board#61"]),
    ("home-peer: board#61 と board#62が完了したら配布", ["board#61", "board#62"]),
]
for line, want in DEFERS:
    got = mg.deferral_refs(line)
    check(f"words: defers → {line!r}", got and got[0][1] == want, got)
PASS = [
    "home-peer: see board#41 for the background",
    "home-peer: board#12 is the review before the release",
    "home-peer: no need to wait until board#12 closes",
    "home-peer: not after board#12",
    "home-peer: I close this with board#42's first real review.",
    "home-peer: after the review, board#12 is next",
    "home-peer: run `until board#5 closes`",
    "(server: waiting until board#5 closes)",
    "home-peer: ship the fix",
    "home-peer: once done, check board#5 for the rest of the list, then close it out and move to the next thing",
    "home-peer: when ready, ship",
    "home-peer: merge after the review",
    "home-peer: close the item when ISSUE-41 closes",
    "home-peer: after the review, board#12 is next",
    "home-peer: once done, check board#5 for the rest",
    "home-peer: board#61を参考にして配布",
    "home-peer: board#61の結果を見て、次に整理",
    "home-peer: 配布の後で board#61 を確認",
    "home-peer: board#61を読んでから、以降の手順を整理",
]
for line in PASS:
    check(f"words: no deferral → {line!r}", mg.deferral_refs(line) == [], mg.deferral_refs(line))
check("words: a fenced block is code, not a line of next", mg.deferral_refs("home-peer: ship it\n```\nonce board#5 closes\n```\nhome-peer: go") == [], None)
check("words: a long id is whole (a short id is not read as the start of a longer one, and the reverse)", mg.deferral_refs("home-peer: after board#99 closes")[0][1] == ["board#99"], None)

# ================================================================ 2. the refusal on a write
open_ = lambda r: {"board#61": "g61", "board#62": "g62"}.get(r, "")           # the pure helper's callbacks: 61, 62 open; anything else closed or unknown
check("unwaited: an open item the after list lacks is found, one the list names or the item itself is not",
      mg.unwaited_deferrals("home-peer: once board#61 closes\nhome-peer: after board#62 lands", ["g62"], open_, None, "g1") == [("home-peer: once board#61 closes", ["board#61"])]
      and mg.unwaited_deferrals("home-peer: after board#61 closes", None, open_, None, "g61") == [] and mg.unwaited_deferrals("home-peer: after board#9 closes", None, open_, None, "g1") == [], None)

item(61, subject="[home] the item waited on")
item(62, subject="[home] a second item waited on")
item(13, status="completed", outcome="done", reason="it works", needs=[], next="", subject="[home] closed already")
item(44, needs=[BACK], mover="team-back", subject="[home] the item that defers")
LINE = "team-back: Once board#61 closes, ship it"
FIX = ('after=["board#61"]',)
refused_nw("1 refuse: a next line that defers on an open item in words is refused, with the fix after=[\"board#<n>\"]", 44, lambda: upd(44, next=LINE),
           "Refused:", "next line", "defers on board#61 in words", 'after=["board#61"] with ask_by=YYYY-MM-DD', "does not wait after it", "nothing wakes its mover", "supplies=<one line: what its output gives this item>", "see board#61")
refused("1 refuse: …once board#<a> lands (a line the precise wait list also catches) is one refusal", lambda: upd(44, next="team-back: once board#61 lands, ship it"), "defers on board#61", none=("problems",))
for w in ("after board#61 closes", "when board#61 is done", "until board#61 lands", "before board#61 ships", "as soon as board#61 closes"):
    refused_nw(f"1 refuse: …{w}", 44, lambda w=w: upd(44, next=f"team-back: ship it {w}"), "defers on board#61")
refused_nw("1 refuse: …two items, one line: both in the fix", 44, lambda: upd(44, next="team-back: after board#61 and board#62 close, ship"), "defers on board#61, board#62", 'after=["board#61", "board#62"]', "does not wait after them")
def _why(f):
    try: f(); return ""
    except Exception as e: return str(e)
_fix44 = _why(lambda: upd(44, next=LINE))
check("1 refuse: …the default fix names until=YYYY-MM-DD as the way to wait for a day (a bare date makes the item wait until then, and outside a hand-off parks it), not a wake that leaves the item active",
      "until=YYYY-MM-DD makes the item wait until then" in _fix44 and "outside a hand-off the date parks the item" in _fix44 and "wake=YYYY-MM-DD" not in _fix44, _fix44[-400:])
refused_nw("1 refuse: …a Japanese line is refused too", 44, lambda: upd(44, next="team-back: board#61が閉じたら配布"), "defers on board#61", "defer_after_id")
refused_nw("1 refuse: …a bracketed id is refused", 44, lambda: upd(44, next="team-back: ship once the review (board#61) lands"), "defers on board#61")
item(9131, needs=["decision"], mover=OWN, ask="Decide: x · Recommend: y · Stakes: z · By: no date", subject="[home] on his call", next="Oliver: decide, after board#61 closes")
refused_nw("1 refuse: …an item on his call is told to write \"see board#<n>\", not after= with ask_by", 9131, lambda: upd(9131, next="Oliver: decide, after board#61 closes"),
           "defers on board#61", "needs decision", 'see board#61', none=("ask_by=YYYY-MM-DD",))
passes("1 refuse: …after=[…] in the same write passes, and is stored", lambda: upd(44, next=LINE, after=["board#61"], ask_by=FUT), "updated board#44")
check("1 refuse: …stored", rd(44)["metadata"]["after"] == ["g61"] and rd(44)["metadata"]["next"] == LINE, rd(44)["metadata"])
passes("1 refuse: …a later write with the same line passes while after names it", lambda: upd(44, next="team-back: Once board#61 closes, ship it, then tell Robin"), "updated board#44")
item(14, needs=[BACK], mover="team-back", subject="[home] defers on two", after=["g61"])
refused_nw("1 refuse: …after names one of the two: the other is still refused", 14, lambda: upd(14, next="team-back: after board#61 and board#62 close, ship"), "defers on board#62", none=("defers on board#61",))
item(15, needs=[BACK], mover="team-back", subject="[home] closed and unknown")
passes("1 refuse: …a closed item is nothing to wait for", lambda: upd(15, next="team-back: after board#13 closed, ship"), "updated board#15")
passes("1 refuse: …a Japanese line on a closed item passes", lambda: upd(15, next="team-back: board#43が閉じたら配布"), "updated board#15")
passes("1 refuse: …an unknown item is nothing to wait for", lambda: upd(15, next="team-back: once board#68 closes, ship"), "updated board#15")
passes("1 refuse: …a plain mention passes", lambda: upd(15, next="team-back: see board#61 for the list"), "updated board#15")
passes("1 refuse: …the item's own id passes", lambda: upd(15, next="team-back: once board#15 has its page, close it"), "updated board#15")
passes("1 refuse: …other flagged words stay a flag: accepted, noted for the auditor", lambda: upd(15, next="team-back: merge after the review"), "updated board#15")
check("1 refuse: …no flag is stored for that one; get reads the words from next", "model_flags" not in rd(15)["metadata"] and "flag: next uses after" in server.stackshot_get("board#15"), rd(15)["metadata"])
item(63, needs=[BACK], mover="team-back", subject="[home] a stored deferral", next=LINE)
passes("1 refuse: a stored deferral is not rejudged by a write that does not set next", lambda: upd(63, subject="[home] a stored deferral, renamed"), "updated board#63")
passes("1 refuse: …nor by a description write", lambda: upd(63, description=DESC + "\n- one more fact"), "updated board#63")
refused_nw("1 refuse: …but the line the write sets is judged", 63, lambda: upd(63, next=LINE + " today"), "defers on board#61")
passes("1 refuse: …the same item gets the line back once after names the item", lambda: upd(63, next=LINE + " today", after=["board#61"], ask_by=FUT), "updated board#63")
item(9130, needs=[BACK], mover="team-back", subject="[home] clear after", after=["g61"], next=LINE)
refused("1 refuse: …dropping the after link with the line set is refused", lambda: upd(9130, clear_after=True, next=LINE), "defers on board#61")
# a create
refused("1 refuse: a create with a deferring next is refused too, and offers only what a create can pass (no state)",
        lambda: server._create(subject="[home] create defers", description=DESC, project="projects/alpha", owner="home-front", next=LINE, needs=[BACK], mover="team-back"),
        "defers on board#61", 'after=["board#61"]', none=("state=blocked",))
passes("1 refuse: …with after=[…] it is created", lambda: server._create(subject="[home] create waits", description=DESC, project="projects/alpha", owner="home-front", next=LINE, needs=[BACK], mover="team-back", after=["board#61"], ask_by=FUT), "created")
# a close and a reopen: not judged / judged
item(16, needs=[BACK], mover="team-back", subject="[home] closing", next=LINE)
passes("1 refuse: a close is never refused for the stored line", lambda: upd(16, status="completed", outcome="done", reason="it works", description=NEW), "updated board#16")

# ================================================================ 3. the close notice
item(17, subject="[home] the item that closes", desc=DESC)
item(18, needs=[PEER], mover="home-peer", subject="[home] names it in next", next="home-peer: go on with the rest. Once board#17 closes, ship it", owner=U["home-other"])
item(19, needs=[PEER], mover="home-peer", subject="[home] names it in the description", desc="- Waits for the output of board#17\n- Done when shipped", next="home-peer: something else")
item(9132, needs=[OTHER], mover="home-other", subject="[home] another mover", next="home-other: look at board#17 again")
item(9133, subject="[home] waits after it and names it", after=["g17"], hold=True, needs=[BACK], mover="team-back", next="team-back: board#17 is the input")
item(9134, status="completed", outcome="done", reason="x", needs=[], next="", subject="[home] closed and names it", desc="- Was waiting for board#17")
item(9135, needs=[FRONT], mover="home-front", subject="[home] the closer's own item", next="home-front: after board#17, tidy up")
item(9136, needs=[PEER], mover="home-peer", subject="[home] does not name it", next="home-peer: board#99 is something else; board#9 too")
item(9137, needs=["decision"], mover=OWN, ask="Decide: x · Recommend: y · Stakes: z · By: no date", subject="[home] his item names it", next="Oliver: check board#17 first", owner=U["home-other"])
item(21, needs=[PEER, OTHER], mover="home-peer", subject="[home] two sessions in needs", next="home-peer: wait on the numbers in board#17")
n0 = len(told)
out = server.stackshot_complete("board#17", outcome="done", reason="the output is in the store", description=NEW, sender="home-front")
ct = close_told(n0)
by = {}
for gid, owner, note, tag in ct: by.setdefault(owner, []).append((gid, note))
check("2 close: the movers of the items that name it are told, one message each", set(by) == {PEER, OTHER}, {k: v for k, v in by.items()})
peer_gids = by.get(PEER, [("", "")])[0][0].split(",")
check("2 close: …home-peer gets one batched message for its items (18, 19, 21), not one each", len(by.get(PEER, [])) == 1 and sorted(peer_gids) == ["g18", "g19", "g21"], by.get(PEER))
pn = by.get(PEER, [("", "")])[0][1]
check("2 close: …it names the closed item, how it ended, why, and who closed it", "board#17 [home] the item that closes closed (done: the output is in the store)" in pn and "by home-front" in pn, pn)
check("2 close: …and each item that named it, with where (next or description) and a link", "3 open items you move name it" in pn and "board#18 [home] names it in next (its next names board#17)" in pn
      and "board#19 [home] names it in the description (its description names board#17)" in pn and "board#21" in pn, pn)
on = by.get(OTHER, [("", "")])[0][1]
check("2 close: …home-other gets its own, for 9132 alone (singular); 9137 is Oliver's, so its keeper hears it, and that is the closer here", sorted(by.get(OTHER, [("", "")])[0][0].split(",")) == ["g9132"]
      and "An open item you move names it" in on and "open items you move name it" not in on, by.get(OTHER))
check("2 close: the closer (home-front) is not told, though its item 9135 names the closed one", FRONT not in by and not any("g9135" in t[0] for t in ct), [(t[0], t[1]) for t in ct])
check("2 close: an item that has it in after (9133) gets the existing wake, not this notice", not any("g9133" in t[0] for t in ct) and any(t[3] == "wake" and "g9133" in t[0] for t in told[n0:]), [(t[0], t[3]) for t in told[n0:]])
check("2 close: a closed item (9134) and a longer id (a longer id in 9136) are not told", not any(g in t[0] for t in ct for g in ("g9134", "g9136")), [(t[0]) for t in ct])
check("2 close: the reply says it", "other open items name board#17" in out or "other open item names board#17" in out, out[-600:])
check("2 close: …and names the movers told", "home-peer" in out.split("name board#17 in next or description")[-1] and "home-other" in out.split("name board#17 in next or description")[-1], out[-500:])
# an item Oliver moves: the sessions its notices go to hear it (here the page keeper home-front), unless they closed it
item(28, subject="[home] closed by home-peer", needs=[PEER]); item(9142, needs=["decision"], mover=OWN, ask="Decide: x · Recommend: y · Stakes: z · By: no date", subject="[home] his item names it", next="Oliver: check board#28 first")
n6 = len(told)
server._update("board#28", status="completed", outcome="done", reason="finished", description=NEW, sender="home-peer")
c6 = close_told(n6)
check("2 close: an item Oliver moves → the sessions its notices go to hear the close (the keeper of its page)", [(t[1], t[0]) for t in c6] == [(FRONT, "g9142")], c6)
# a close with nobody naming it says nothing, a second close of the same item (reopen and close again) is a new close
item(22, subject="[home] nobody names it")
n1 = len(told)
out2 = server.stackshot_complete("board#22", outcome="done", reason="finished", description=NEW, sender="home-front")
check("2 close: nothing named it → no message, no reply line", close_told(n1) == [] and "name board#22" not in out2 and "names board#22" not in out2, out2[-400:])
# dropped and superseded
item(23, subject="[home] will be superseded"); item(24, subject="[home] its replacement")
item(9138, needs=[PEER], mover="home-peer", subject="[home] names the dropped one", next="home-peer: after board#23, go")
n2 = len(told)
server.stackshot_complete("board#23", outcome="superseded", superseded_by="board#24", reason="merged into board#24", description=NEW, sender="home-front")
st = close_told(n2)
check("2 close: a superseded item names its replacement in the message", len(st) == 1 and "superseded by board#24" in st[0][2] and "merged into board#24" in st[0][2], st)
item(25, subject="[home] will be dropped")
item(9139, needs=[OTHER], mover="home-other", subject="[home] names the dropped one", next="home-other: board#25 gives the input")
n3 = len(told)
server.stackshot_complete("board#25", outcome="dropped", reason="no longer needed", description=NEW, sender="home-front")
dt_ = close_told(n3)
check("2 close: a dropped item says dropped", len(dt_) == 1 and "closed (dropped: no longer needed)" in dt_[0][2], dt_)
# the close by update(status=completed) and by the mover itself
item(26, subject="[home] closes by update", needs=[PEER])
item(9140, needs=[PEER], mover="home-peer", subject="[home] names it", next="home-peer: build on board#26")
n4 = len(told)
server._update("board#26", status="completed", outcome="done", reason="finished", description=NEW, sender="home-peer")
check("2 close: update(status=completed) tells too, and the closer (home-peer, mover of 9140) is not told", close_told(n4) == [], close_told(n4))
item(9141, needs=[OTHER], mover="home-other", subject="[home] names it too", next="home-other: build on board#27"); item(27, subject="[home] closes by update 2", needs=[PEER])
n5 = len(told)
server._update("board#27", status="completed", outcome="done", reason="finished", description=NEW, sender="home-peer")
check("2 close: …and another mover is told", [t[1] for t in close_told(n5)] == [OTHER], close_told(n5))
# a failure of the notice never fails the close
orig = telling.tell_close_mentions
telling.tell_close_mentions = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
item(64, subject="[home] closes though the notice fails")
out3 = server.stackshot_complete("board#64", outcome="done", reason="finished", description=NEW, sender="home-front")
check("2 close: a notice that fails never fails the close", rd(64)["status"] == "completed" and "updated board#64" in out3, out3[-200:])
telling.tell_close_mentions = orig

# the notice stays small: 20 items name it, the message lists 8 and counts the rest, well inside MSG_MAX
item(29, subject="[home] named by many")
for i in range(9300, 9320):
    item(i, needs=[PEER], mover="home-peer", subject=f"[home] names it {i} with a long subject " + "x" * 80, next="home-peer: build on board#29")
n7 = len(told)
out7 = server.stackshot_complete("board#29", outcome="done", reason="finished", description=NEW, sender="home-front")
c7 = close_told(n7)
check("2 close: 20 naming items → one message, the first 8 listed and the rest counted, well inside MSG_MAX",
      len(c7) == 1 and "20 open items you move name it" in c7[0][2] and c7[0][2].count("\n- board#") == 8 and "- … and 12 more" in c7[0][2] and len(c7[0][2]) < server.MSG_MAX // 2, [(len(t[2]), t[2][:300]) for t in c7])
check("2 close: …the gids of all 20 ride on the send (the record of an undelivered line)", len(c7[0][0].split(",")) == 20, c7[0][0])
check("2 close: …and the reply counts all 20", "20 other open items name board#29" in out7, out7[-500:])

# the router's path (as _wake_tell): where the router holds the project for the recipient, the notice is recorded for it and not sent
item(65, subject="[home] closes with the router live"); item(30, needs=[PEER], mover="home-peer", subject="[home] named, router holds", next="home-peer: use board#65's output", owner=U["home-other"])
rec, stash_ = [], []
real = (server._router_live.holds, server._routing.record, server._router_live.stash)
server._router_live.holds = lambda project, sid, stand_in_too=False: sid == PEER
server._routing.record = lambda project, **kw: (rec.append((project, kw)), "nid_a")[1]
server._router_live.stash = lambda nid, body: stash_.append((nid, body))
n8 = len(told)
try:
    server.stackshot_complete("board#65", outcome="done", reason="finished", description=NEW, sender="home-front")
finally:
    server._router_live.holds, server._routing.record, server._router_live.stash = real
mine = [r for r in rec if r[1].get("label") == "close board#65"]
check("2 close: a recipient the router holds the project for gets the notice through the routing log, and no message", close_told(n8) == [] and len(mine) == 1 and mine[0][1].get("live") is True
      and mine[0][1].get("pilot") is True and "board#30" in mine[0][1].get("text", ""), (close_told(n8), rec))
check("2 close: …the full text is stashed for the router to deliver", len(stash_) == 1 and stash_[0][0] == "nid_a" and "board#30" in stash_[0][1] and "names it" in stash_[0][1], stash_)

# ================================================================ 4. get shows the live state of the items next names
item(30, subject="[home] get names these", needs=[PEER], mover="home-peer", next=f"home-peer: check board#17 and board#62, then board#30 itself, board#68, and board#17 again; board#14 too")
g = server.stackshot_get("board#30")
check("3 get: a `named in next:` block follows next", "next:\nhome-peer: check board#17" in g and "\nnamed in next:\n" in g, g)
check("3 get: a closed item shows its close time in the instance timezone and its outcome", re.search(r"- board#17: closed \w{3} \w{3} \d+(?:st|nd|rd|th) \d\d:\d\d \(done\)", g), g)
check("3 get: an open item shows its mover", "- board#62: open, mover " in g, g)
check("3 get: …a waiting item shows what it waits after", "- board#14: open, waiting after board#61" in g, g)
check("3 get: …an unknown item says not found", "- board#68: not found" in g, g)
check("3 get: …the item itself is left out, an item named twice appears once", "- board#30" not in g and g.count("- board#17:") == 1, g)
item(31, subject="[home] names no one", next="home-peer: just do it")
check("3 get: no board#N in next → no block", "named in next" not in server.stackshot_get("board#31"), None)
item(32, status="completed", outcome="done", reason="x", needs=[], next="", subject="[home] closed")
check("3 get: a closed item shows none", "named in next" not in server.stackshot_get("board#32"), None)
nl = server._next_names_lines({"gid": "g30", "metadata": {"next": "home-peer: " + " ".join(f"board#{i}" for i in range(71, 83))}})
check("3 get: …at most eight, then a count", len(nl) == 1 + 8 + 1 and nl[-1] == "- … and 4 more", nl)

# ================================================================ 5. a cleared wait names the next lines that still wait on it
NOTE = "whose wait was just cleared: reword it)"
notes = lambda out: [ln for ln in out.splitlines() if ln.startswith("(note: ") and "wait was just cleared" in ln]
item(9143, needs=[BACK], mover="team-back", subject="[home] clear after, stale line", after=["g61"], next="team-back: tidy the docs\nteam-back: ship once board#61 closes")
o_a = upd(9143, clear_after=True)
check("5 cleared: clear_after with a next line that defers on the item it waited on → one note, the line's position, the id", notes(o_a) == [f"(note: next line 2 still waits on board#61, {NOTE}"], notes(o_a))
check("5 cleared: …the write went through (after gone, next untouched)", "after" not in rd(9143)["metadata"] and "ship once board#61 closes" in rd(9143)["metadata"]["next"], rd(9143)["metadata"])
item(9144, needs=[BACK], mover="team-back", subject="[home] clear after, clean next", after=["g61"], next="team-back: ship the fix, see board#61 for the list")
check("5 cleared: clear_after with a next that only mentions the item → no note", notes(upd(9144, clear_after=True)) == [], None)
item(9145, needs=[BACK], mover="team-back", subject="[home] clear wait, stale line", wait_kind="relay", wait_event="board#61 closes", ask_by=FUT, next="team-back: ship after board#61 closes")
o_b = upd(9145, clear_wait=True)
check("5 cleared: clear_wait with a line that defers on the board#N its wait named → noted", notes(o_b) == [f"(note: next line 1 still waits on board#61, {NOTE}"] and "wait_kind" not in rd(9145)["metadata"], (notes(o_b), rd(9145)["metadata"]))
item(7, needs=[BACK], mover="team-back", subject="[home] a line of another session", after=["g61"], next="team-back: tidy the docs")
server._update("board#7", sender="home-peer", next="home-peer: build once board#61 closes")
check("5 cleared: …the fixture holds a line written by the other session", "home-peer: build once board#61 closes" in rd(7)["metadata"]["next"], rd(7)["metadata"])
o7 = upd(7, clear_after=True)
check("5 cleared: a line another session wrote is named too", len(notes(o7)) == 1 and "board#61" in notes(o7)[0], notes(o7))
item(9147, needs=[BACK], mover="team-back", subject="[home] a smaller after list", after=["g61", "g62"], next="team-back: first once board#61 closes\nteam-back: then once board#62 closes")
o_c = upd(9147, after=["board#62"], ask_by=FUT)
check("5 cleared: an after list that drops one item names only the lines on the dropped one", len(notes(o_c)) == 1 and "next line 1 still waits on board#61" in notes(o_c)[0], notes(o_c))
item(9148, needs=[BACK], mover="team-back", subject="[home] nothing cleared", after=["g61"], next="team-back: ship once board#61 closes")
check("5 cleared: a write that clears nothing (after stays) → no note", notes(upd(9148, subject="[home] nothing cleared, renamed")) == [], None)
item(9149, needs=[BACK], mover="team-back", subject="[home] a stored deferral, no wait", next="team-back: ship once board#61 closes")
check("5 cleared: …nor does an item that never had a wait", notes(upd(9149, clear_after=True)) == [] and notes(upd(9149, clear_wait=True)) == [], None)
item(9150, needs=[BACK], mover="team-back", subject="[home] many stale lines", after=["g61"], next="\n".join(f"team-back: step {k} after board#61 closes" for k in range(1, 8)))
o_d = upd(9150, clear_after=True)
check("5 cleared: at most five notes, then a count", len(notes(o_d)) == 6 and "2 more next lines still wait" in notes(o_d)[-1] and "next line 5 still waits" in notes(o_d)[4], notes(o_d))
item(9151, needs=[BACK], mover="team-back", subject="[home] a done line", after=["g61"], next="team-back: tidy the docs\nteam-back: ship once board#61 closes")
upd(9151, done=[1])
o_e = upd(9151, clear_after=True)
check("5 cleared: the position is the step's place in the checklist, as done= and reword= count it (a finished step keeps its number)", notes(o_e) == [f"(note: next line 2 still waits on board#61, {NOTE}"], notes(o_e))
item(9152, needs=[BACK], mover="team-back", subject="[home] after named by id form", after=["g61"], next="team-back: Once board#61 closes, ship it")
check("5 cleared: the reply names the stale line for after=none as well", len(notes(upd(9152, after="none"))) == 1, None)

item(9153, needs=[BACK], mover="team-back", subject="[home] the wait moves stores", after=["g61"], next="team-back: ship once board#61 closes")
o_f = upd(9153, clear_after=True, wait_kind="relay", wait_event="board#61 closes", ask_by=FUT)
check("5 cleared: an id that moves from after to wait_event in one write is still waited on → no note", notes(o_f) == [] and "after" not in rd(9153)["metadata"] and rd(9153)["metadata"].get("wait_event") == "board#61 closes", (notes(o_f), rd(9153)["metadata"]))

# ================================================================ 6. the text agents learn it from
desc_ = {t.name: t.description for t in __import__("asyncio").run(server.mcp.list_tools())}
check("text: update, create, get and complete teach the new rule", all(w in desc_["update"] for w in ("defers on another item in words", 'after=["board#N"]', "Only the lines the call sets are checked"))
      and "defers on another item in words" in desc_["create"] and "named in next:" in desc_["get"] and "names the closed item" in desc_["complete"], None)

check("text: update teaches the note a cleared wait carries", "whose wait was just cleared: reword it" in desc_["update"] and "clear_wait" in desc_["update"], None)

print(("ok" if not fails else "FAILED") + f": item waits scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
