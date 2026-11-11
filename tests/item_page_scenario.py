"""Scenario test for the item page on the item model (itempage.py, ui/render.py Board.item_html) — fixture data, no live store, no network, no server.

The page says an item in the model's terms:
  * the id and the subject as the title, the goal under it (none when there is no goal);
  * one state line: the state tag (Your move | On agent | Waiting | Done), since <age>, and the warnings (handed over, not yet taken); never the mover or the `then` (the sidebar's Mover and Then rows), a closed item's reason under it;
  * no "Where it stands" section;
  * the ask, its option cards and the answer box only while the item is alive with the owner as mover (anyone else's item has the comment box in the same place, open);
  * Next: every line, each `<mover>: <action>` (an unnamed line gets the item's mover), a waiting item's headed "After the wait";
  * for a waiting item the wait (what, watched by, until, then, his words) and the chases logged on it;
  * the sidebar (Mover, Owner and Creator first, then project, then, priority, wake, anchors, the GitHub issue), today's other fields in a closed More details fold;
  * Background (the stored description; open), History and Comments (closed) as folds, in the order: state line, Your step or the ask, Next, Background, History, Comments; History is one line per revision with its author (`written_by`), Comments the people's words.

    tests/run-suite item_page        → exit 0 / 1"""
import html, json, os, re, sys, pathlib, subprocess, tempfile, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="itempage-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
HERE, OTHER = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
now = time.time(); H = 3600.0; DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({HERE: {"name": "home-here", "machine": "a", "seen": now}, OTHER: {"name": "home-other", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
ASK = "Decide: whether to ship · Recommend: ship · Stakes: none either way · By: no date"
OPTS = [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}]
def item(i, subject, status="open", su=None, written_by=None, **meta):
    su = now - 3 * H if su is None else su
    d = {"id": str(i), "subject": subject, "description": "A thing. It lives here.", "status": status, "updated": su, "state_updated": su, "confirmed": su,
         "metadata": {"owner": HERE, "project": "projects/alpha", **meta}}
    if written_by: d["written_by"] = written_by
    (T / f"store/a/{i}.json").write_text(json.dumps(d))
FIVE = "\n".join(f"Oliver: step {k}" for k in range(1, 6))
item(1, "[home] ask item", goal="Ship the thing", needs=["decision"], ask=ASK, options=OPTS, mover="Oliver", then="home-other", next=FIVE, priority="p1")
item(2, "[home] agent item", mover="home-other", next="do the first thing\nhome-other: second thing\n- a sub step\nhome-other: third\nhome-other: fourth",
     handoff={"to": "home-other", "from": "home-here", "at": now - 600, "delivered_at": now - 590, "taken_at": None}, woke={"what": "the PR merged", "to": "home-other", "at": now - 700})
item(3, "[home] time wait", wait_kind="time", wake="2099-01-01", post_wake_mover="home-other", next="home-other: check the date", wait_basis={"text": "the vendor's holiday", "wake": "2099-01-01"})
item(4, "[home] item wait", wait_kind="item", after=["a2"], post_wake_mover="home-other", next="home-other: go on")
item(5, "[home] anchor wait", wait_kind="anchor", wait_anchor="https://github.com/o/r/pull/9", wait_event="the review lands", post_wake_mover="home-other", wake="2099-02-01",
     chases=[{"at": now - 2 * H, "by": "home-here", "note": "asked in the PR"}, {"at": now - H, "by": "home-here", "note": "pinged the reviewer"}], next="home-here: wait for it")
item(6, "[home] relay wait", wait_kind="relay", wait_event="the contract", party="Acme", ask_by="2099-03-01", post_wake_mover="home-other", next="home-other: read it")
item(7, "[home] done item", status="completed", su=now - 2 * DAY, outcome="done", reason="shipped as asked", mover=None)
item(8, "[home] history item", mover="home-other", next="home-other: x", written_by="home-other")
item(9, "[home] no ask item", mover="home-other", next="home-other: x", needs=["home-other"])
HOH = {"to": "Oliver", "from": "home-here", "at": now - 600, "delivered_at": None, "taken_at": None, "no_clock": True}      # a real hand-off to the owner carries no clock
item(60, "[home] your call, handed to Oliver", mover="Oliver", needs=["decision"], ask=ASK, options=OPTS, next="Oliver: decide", handoff=HOH)
item(61, "[home] your step, handed to Oliver", mover="Oliver", state="your-step", step="`uv run tools/x.py --go` and say done", next="home-other: check it", handoff=HOH)
item(62, "[home] handed to a session, not taken", mover="home-other", next="home-other: x", handoff={"to": "home-other", "from": "home-here", "at": now - 600, "delivered_at": now - 590, "taken_at": None})
item(63, "[home] handed to a session, taken", mover="home-other", next="home-other: x", handoff={"to": "home-other", "from": "home-here", "at": now - 600, "delivered_at": now - 590, "taken_at": now - 300})
item(41, "[home] mover history", mover="home-other", next="home-other: x", written_by="home-other")
item(80, "[home] creator by another", owner=OTHER, mover="home-other", next="home-other: x", written_by="home-other")
item(81, "[home] no creator", owner="", mover="home-other", next="home-other: x")
item(82, "[home] no creator, done", status="completed", su=now - 2 * DAY, outcome="done", reason="shipped as asked", mover=None, owner="")
item(10, "[home] oliver step",mover="Oliver", then="home-other", next="Oliver: run the command")
item(42, "[home] step handed over", mover="home-other", needs=["home-other"], next="home-here: the second part", written_by="home-other")
item(43, "[home] step hand-over, session down", mover="home-other", needs=["home-other"], next="home-gone: the second part", written_by="home-other")
item(11, "[home] bulleted next", mover="home-other", next="- home-other: step 1\n* home-other: step 2\n1. home-other: step 3\n2) home-other: step 4\n- home-other: step 5")
item(12, "[home] named bullet", mover="home-other", next="home-other: do x\n- Oliver: run `cmd`")
item(16, "[home] unnamed bullets", mover="home-other", next="home-other: do x\n- an unnamed bullet\n  an indented line\n3. a numbered one")
item(13, "[home] fenced next", mover="home-other", next="Oliver: run this:\n```\nls -l\nOliver: not a line\n```\nhome-other: then this\n~~~\nsecond\n~~~")
item(14, "[home] waiting with a decision", wait_kind="time", wake="2099-05-01", post_wake_mover="home-other", needs=["decision"], ask=ASK, options=OPTS, next="home-other: x")
item(15, "[home] <script>alert(1)</script> & \"q\"", goal="Goal <b>bold</b> & <script>x</script>", mover="home-other", next="home-other: <img src=x onerror=alert(1)> & more\n- <i>sub</i>", written_by="<u>who</u>")
LINK = "[PR #28](https://github.com/example-owner/stackshot/pull/28)"
item(19, "[home] oliver step, handed", mover="Oliver", next="Oliver: run it", handoff={"to": "Oliver", "from": "home-here", "at": now - 600, "delivered_at": now - 590, "taken_at": None})
item(20, "[home] ask with a tag", mover="Oliver", needs=["decision"], ask="Decide: whether <script>x</script> ships [PR #1](https://github.com/o/r/pull/1) · Recommend: yes · Stakes: none · By: no date", options=OPTS, next="Oliver: decide")
item(17, "[home] next with a link", mover="home-other", next=f"home-other: merge {LINK} (the search) and run `uv run x`")
LONGN = "go through the open review comments one by one and answer each of them in the thread before anything else is merged, see " + LINK + " and then carry on with the rest of the list for this item without waiting"
item(18, "[home] long next with a link", mover="home-other", next="home-other: " + LONGN)
item(23, "[home] your step", mover="Oliver", state="your-step", step="\n`uv run tools/x.py --go` and say done\nsecond line of the step", next="home-other: check the result once he has run it")
item(24, "[home] agent with a step field", mover="home-other", state="your-step", step="`uv run y`", next="home-other: do the other thing")
item(25, "[home] hostile step", mover="Oliver", state="your-step", step="<script>alert(1)</script> `<b>x</b>` & more", next="Oliver: <script>alert(1)</script> then `<b>x</b>` & so on\nOliver: fallback <i>line</i>", written_by="<u>who</u>")
item(28, "[home] hostile step field only", mover="Oliver", state="your-step", step="<script>alert(1)</script> `<b>x</b>` & more", next="home-other: check it", written_by="<u>who</u>")      # no line of his on the checklist: the step field itself is drawn (the fallback)
item(26, "[home] hostile mover", mover="<i>evil</i>", next="<i>evil</i>: do <img src=x onerror=alert(1)>", written_by="<u>who</u>", handoff={"to": "<i>evil</i>", "from": "home-here", "at": now - 600, "delivered_at": now - 590, "taken_at": None})
item(27, "[home] fenced step", mover="Oliver", state="your-step", step="```\nuv run x\n```", next="Oliver: fallback line")
item(21, "[home] dump item", mover="home-other", state="your-step", step="run x", next="home-other: x", written_by="home-other")
item(22, "[home] decided item", mover="Oliver", needs=["decision"], ask=ASK, options=OPTS, next="Oliver: decide", written_by="home-other")
STEPCMD = "run the one line `sala op reauth box-a --from me --words \"go\"` and say done"
item(30, "[home] step with a command", state="your-step", step=STEPCMD, mover="Oliver", then="home-other", needs=["home-other"], next="home-other: check it")
item(31, "[home] step with a pane line", state="your-step", step="! sala reauth box-a", mover="Oliver", then="home-other", needs=["home-other"], next="home-other: check it")
item(32, "[home] step with a link", state="your-step", step="Sign in at https://example.com/login/now and say done", mover="Oliver", then="home-other", needs=["home-other"], next="home-other: check it")
item(44, "[home] step with two links", state="your-step", step="Compare https://example.com/p/aaa with https://example.com/p/bbb and say done", mover="Oliver", then="home-other", needs=["home-other"], next="home-other: check it")
item(45, "[home] step with a command and a link", state="your-step", step="Open https://example.com/p/aaa then run `sala op reauth box-a` and say done", mover="Oliver", then="home-other", needs=["home-other"], next="home-other: check it")
item(46, "[home] step with a lone-word backtick", state="your-step", step="Set the mode to `default` and say done", mover="Oliver", then="home-other", needs=["home-other"], next="home-other: check it")
item(33, "[home] step with plain words", state="your-step", step="Call the office and say done", mover="Oliver", then="home-other", needs=["home-other"], next="home-other: check it")
item(34, "[home] step item, closed", status="completed", su=now - 2 * DAY, state="your-step", step=STEPCMD, outcome="done", reason="done", mover=None)
item(35, "[home] open question", needs=["decision"], ask=ASK, mover="Oliver", then="home-other", next="home-other: wait")                                       # an ask with no options
item(36, "[home] approve or decline", needs=["decision"], ask=ASK, mover="Oliver", then="home-other", next="home-other: wait",
     options=[{"label": "Approve", "line": "Go ahead.", "recommended": True}, {"label": "Decline", "line": "Do not.", "recommended": False}])   # Approve and Decline, stored by the owner
item(37, "[home] misshaped options", needs=["decision"], ask=ASK, mover="Oliver", then="home-other", next="home-other: wait",
     options=[{"label": "Approve", "line": "Go ahead.", "recommended": False}, {"label": "Decline", "line": "Do not.", "recommended": False}])   # no recommended one: draws no button (the board item review)
item(70, "[home] verifying item", state="verifying", proof="the link opens on the phone", end="2099-01-01", needs=["home-other"], mover="home-other", next="home-other: check the result")
item(71, "[home] commented item", mover="home-other", next="home-other: x")
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": "https://x.slack.com/archives/C0000000001", "items": ["a1"], "added": 1, "by": "t"}]}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q")
def commit(i, msg, meta=None, **top):          # a second and third revision of item item 8, each with its author
    p = T / f"store/a/{i}.json"; d = json.loads(p.read_text()); d.update(top); d["metadata"].update(meta or {}); p.write_text(json.dumps(d)); git("add", "-A"); git("commit", "-q", "-m", msg)
git("add", "-A"); git("commit", "-q", "-m", "fixture")
commit(71, "c1", {"answers": [{"ts": now - H, "kind": "comment", "text": "looks fine to me", "via": "github", "url": "https://github.com/o/r/issues/1#issuecomment-5", "comment_id": 5}]}, written_by="home-other", updated=now - H)      # one comment of his, on GitHub: the Comments fold lists it
commit(8, "r2", {"priority": "p1"}, written_by="home-other", updated=now - 2 * H)
commit(8, "r3", written_by="Oliver", updated=now - H, subject="[home] history item, renamed")
commit(41, "m2", {"mover": "home-here"}, written_by="home-other", updated=now - H)                # a mover change is History's `mover: A → B`
commit(41, "m3", {"owner": OTHER}, written_by="home-other", updated=now - H // 2)                  # …and a change of the stored owner is the keeper of record
commit(42, "h1", {"mover": "home-here", "needs": ["home-here"], "handover": {"step": "aaaaaaaaaaaa", "kind": "moved", "to": "home-here", "at": now - H}}, written_by="", updated=now - H)         # a finished step handed the item on (handover.py)
commit(43, "h2", {"handover": {"step": "bbbbbbbbbbbb", "kind": "fallback", "to": "home-gone", "at": now - H, "why": "no pane of it is in the heartbeat"}}, written_by="", updated=now - H)       # …or could not: the item stays
LONGLINE = "home-other: go through the open review comments one by one and answer each in the thread before anything else is merged, see [PR #28](https://github.com/o/r/pull/28), then carry on with the rest of the list"
BIGDESC = "- one fact about the item\n- <script>alert(1)</script> and a second fact\n- the links: [PR #28](https://github.com/o/r/pull/28)\n- his words: go ahead"
commit(21, "d1", {"next": LONGLINE + "\nhome-other: second line", "ask": ASK, "options": OPTS}, written_by="home-other", updated=now - 3 * H, description=BIGDESC)   # the dump: next, ask, options and description in one revision
commit(21, "d2", written_by="home-other", updated=now - 2 * H, description=BIGDESC + "\n- a fifth fact")                                                      # and the description again
commit(22, "e1", {"needs": [], "ask": "", "options": [], "mover": "home-other"}, written_by="Oliver", updated=now - H)                                              # his answer: the ask and the options leave
commit(21, "d3", {"state": "doing", "next": "home-other: short one"}, written_by="Oliver", updated=now - H)

sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web.ui import render as ui_render
from stackshot.web import itempage; from stackshot.model import model as _mdl
bd = ui_render.Board(f"{tmp}/store")
page = lambda g, **kw: bd.item_html(g, **kw)
BOX = {"action": "/items/a1/answer", "token": "TOKEN", "sent": ""}
istate = lambda h: html.unescape(re.sub(r"<[^>]+>", "", (re.search(r'<p class="istate">(.*?)</p>', h, re.S) or [0, ""])[1]))
istat = lambda h: html.unescape(re.sub(r"<[^>]+>", "", (re.search(r'<div class="istat">(.*?)</div>', h, re.S) or [0, ""])[1]))        # the state line and what sits beside it
upd = lambda h: (lambda t: t[t.find("updated"):] if "updated" in t else "")(istat(h))                                                           # …from "updated" on: the latest change
side = lambda h: h[h.find('<aside class="iside"'):h.find("</aside>")]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

# ---- 1. the title and the state line
wt = lambda h: html.unescape(re.sub(r"<[^>]+>", " ", (re.search(r'<section class="iwait">.*?</section>', h, re.S) or [""])[0]))
p1, p2, p3, p4, p5, p6, p7 = (page(f"a{i}", answer=BOX) for i in (1, 2, 3, 4, 5, 6, 7))
check("the title is the id and the subject (the prefix dropped), the goal under it; no goal, no goal line", '<h1><span class="hid">a1</span> ask item</h1><p class="igoal">Ship the thing</p>' in p1 and "<title>a1 · ask item</title>" in p1
      and '<h1><span class="hid">a2</span> agent item</h1>' in p2 and 'class="igoal"' not in p2, re.findall(r"<h1>.*?</h1>(?:<p class=.igoal.>.*?</p>)?", p1 + p2))
check("alive with the owner as mover: Your move · since <age>; the post-handback mover is the sidebar's Then row, not on the line", re.fullmatch(r"Your move · since 3h ago", istate(p1)) is not None, istate(p1))
check("alive with a session as mover, handed over and not yet taken: no mover on the line (the sidebar's Mover row names it)", re.match(r"On agent · since .* · handed over, not yet taken", istate(p2)) is not None and "mover" not in istate(p2), istate(p2))
p60, p61, p62, p63 = (page(f"a{i}", answer=BOX) for i in (60, 61, 62, 63))
check("a your-call item handed to Oliver shows no 'not yet taken' warning", istate(p60).startswith("Your move") and "not yet taken" not in p60, istate(p60))
check("a your-step item handed to Oliver shows no 'not yet taken' warning", istate(p61).startswith("Your move") and "not yet taken" not in p61, istate(p61))
check("a hand-off to a session that has not taken it shows the warning; one taken does not", "handed over, not yet taken" in istate(p62) and "not yet taken" not in p63, (istate(p62), istate(p63)))
check("waiting on a time: the state line says Waiting; the wait block has what (his reason), watched by the scheduler, until",
      istate(p3) == "Waiting · since 3h ago" and re.search(r"Waits on\s+the vendor's holiday\s+Watched by\s+the scheduler\s+Until\s+Thu Jan 1st\s+Picks it up\s+home-other", wt(p3)) is not None, (istate(p3), wt(p3)))
check("waiting on an item: its close, watched by the server", istate(p4).startswith("Waiting · since") and re.search(r"Waits on\s+a2\s+\(open\)\s+Watched by\s+the server\s+End\s+no end date set\s+Picks it up\s+home-other", wt(p4)) is not None, (istate(p4), wt(p4)))
check("waiting on an anchor: the event, watched by the anchor module, the backstop", istate(p5).startswith("Waiting · since") and re.search(r"the review lands\s+Watched by\s+the anchor module\s+Backstop\s+Sun Feb 1st\s+Picks it up\s+home-other", wt(p5)) is not None, (istate(p5), wt(p5)))
check("waiting on news only he relays: the party's event, ask by", istate(p6).startswith("Waiting · since") and re.search(r"Acme's the contract\s+\(news only Oliver relays\)\s+Watched by\s+the scheduler\s+Ask by\s+Sun Mar 1st\s+Picks it up\s+home-other", wt(p6)) is not None, (istate(p6), wt(p6)))
check("dead: Done <age>, and the close's reason under the state line", re.fullmatch(r"Done · \d+d ago", istate(p7)) is not None and '<p class="ireason">shipped as asked</p>' in p7, istate(p7))
# the project is not on the line under the title: it stays on the sidebar's Project row. The page is one document in both layouts (the stylesheet moves the side panel beside the item from 768px and stacks it on a phone), so one read of the markup covers both
_proj = "Alpha"
_stat = lambda h: h[h.find('<div class="istat">'):h.find("</div>", h.find('<div class="istat">'))]
_row = lambda h: re.search(r'<dt>Project</dt><dd>(.*?)</dd>', h, re.S)
check("the line under the title never names the project, on an alive, a waiting and a closed item; the Project row of the sidebar still does, linked",
      all(_proj not in _stat(h_) and "<a " not in re.sub(r"<a href=\"/items/[^\"]*\">[^<]*</a>", "", re.search(r'<p class="istate">(.*?)</p>', h_, re.S).group(1)) and _row(h_) is not None and _proj in _row(h_).group(1) and "<a href=" in _row(h_).group(1)
          for h_ in (p1, p2, p3, p7)), [(_stat(h_), _row(h_) and _row(h_).group(1)) for h_ in (p1, p7)])
check("both layouts read the same markup: the sidebar sits before the main column in the source, the line under the title only in the main column, and the phone's order keeps the sidebar out of that line",
      p7.index('<aside class="iside"') < p7.index('<div class="istat">') and p7.index("</h1>") < p7.index('<div class="istat">') and ".iside{order:1}" in p7)

# ---- 2. the latest change in plain words (itempage.plain_change, last_change) and the page without a Where it stands section
PC = itempage.plain_change
check("plain words: a hand-over, a next edit and a description edit", PC("needs: heron-engineer; mover: falcon-redesign → heron-engineer; next edited") == "handed to heron-engineer, changed what comes next"
      and PC("mover: A → B; next edited; description edited") == "handed to B, changed what comes next" and PC("description edited 2×, 11:50–11:53") == "updated the background", PC("mover: A → B; next edited; description edited"))
check("plain words: needs decision with state your-call is one asked-for-your-decision, in the place of the first", PC("needs: decision; state: your-call; next and ask edited") == "asked for your decision, changed what comes next"
      and PC("state: your-call; needs: decision") == "asked for your decision" and PC("needs: decision") == "needs: decision" and PC("state: your-call") == "state: your-call", PC("needs: decision; state: your-call; next and ask edited"))
check("plain words: your-step is a step for you; model and expected_by clauses are dropped", PC("state: your-step; step edited") == "gave you a step, step edited" and PC("model: opus; expected_by: 2026-10-29; next edited") == "changed what comes next"
      and PC("state: doing; expected_by: 2026-10-29; mover: Oliver → ops-x") == "handed to ops-x" and PC("expected_by: 2026-10-29") == "expected_by: 2026-10-29", None)
check("plain words: needs <session> goes when a mover clause is there (the hand-over says it), not otherwise and not for a decision; state: doing goes; a cleared state is taking it back to work; nothing left shows the full text",
      PC("needs: a, b; mover: A → B; next edited") == "handed to B, changed what comes next" and PC("needs: ops-x") == "needs: ops-x" and PC("needs: decision; mover: A → B") == "needs: decision, handed to B"
      and PC("state cleared (was doing)") == "took it back to work" and PC("state cleared (was your-step); next edited") == "took it back to work, changed what comes next" and PC("state: doing") == "state: doing" and PC("model: opus; state: doing") == "model: opus; state: doing", None)
check("plain words: completed, woke, named and anything unrecognised stay as written; only the first two clauses show; a hand-over to no one stays as written",
      PC("state cleared") == "state cleared" and PC("completed: done as asked") == "completed: done as asked" and PC("woke: the PR merged") == "woke: the PR merged" and PC("named x") == "named x"
      and PC("next edited; description edited; state: your-step") == "changed what comes next, updated the background" and PC("mover: A → no one") == "mover: A → no one" and PC("created as “[home] x”") == "created as “[home] x”" and PC("") == "", None)
check("plain words: a semicolon inside a field's value is no clause: a clause starts only at '; ' and a label the History writes",
      PC("next: …queued behind #7; then the IDs into the instance config") == "changed what comes next"
      and PC("next: a; b; needs: x") == "changed what comes next, needs: x" and PC("needs: x; next: a; b; c") == "needs: x, changed what comes next"
      and PC("state: your-step; step: do a; then b; next edited") == "gave you a step, step: do a; then b" and PC("description: a; b; next edited") == "updated the background, changed what comes next"
      and PC("next edited; description edited; state: your-step") == "changed what comes next, updated the background", PC("next: a; b; needs: x"))
long_what = ("x" * 40 + " ") * 6
check("a long change is clipped on a word and ends in an ellipsis; a missing who or what is left out; the text is escaped",
      len(itempage.last_change("Oliver", long_what, str)) <= 110 and itempage.last_change("Oliver", long_what, str).endswith("…")
      and itempage.last_change("Oliver", "", str) == "" and itempage.last_change("", "did it.", str) == ": did it" and itempage.last_change("<u>a</u>", "<b>x</b>", html.escape) == " by &lt;u&gt;a&lt;/u&gt;: &lt;b&gt;x&lt;/b&gt;", itempage.last_change("Oliver", long_what, str))
check("no page carries a Where it stands section, its fold key or its style", all("Where it stands" not in p_ and "iwhere" not in p_ and 'data-fold="item.where"' not in p_ for p_ in (p1, p7, page("a2"), page("a23"), page("a5"))))

# ---- 3. the ask and the answer box: only while the owner is the mover
check("the owner's item: the ask, its options and the answer box, before Next", p1.index('<div class="iask">') < p1.index('<form class="ianswer"') < p1.index("<h2>Next</h2>") and 'name="choice" value="Ship"' in p1)
check("a session's item: no ask, no answer box in the main column; the comment box takes the answer box's slot (before Next), with the comment button alone",
      'class="iask"' not in p2 and "Your answer" not in p2 and '<form class="ianswer" data-comment-only' in p2 and 'value="answer"' not in p2 and p2.index('<form class="ianswer"') < p2.index('id="next"'), p2[p2.find('class="istat"'):][:600])
check("a waiting item and a closed one ask nothing", all('class="iask"' not in p and "Your answer" not in p for p in (p3, p4, p5, p6, p7)))
check("a step of his with no ask still gets the answer box (alive, his)", '<form class="ianswer"' in page("a10", answer=BOX) and '<form class="ianswer" data-comment-only' not in page("a10", answer=BOX))
check("the answer box and the comment box have no corner grip (resize:none) and a bottom-edge handle: a focusable horizontal separator, with its script and style on the page",
      all(re.search(r'<div class="abox"><textarea id="atext" name="text".*?</textarea><div class="rsz" role="separator" aria-orientation="horizontal" tabindex="0" aria-controls="atext" aria-label="Resize the answer box"></div></div>', p, re.S) for p in (p1, p2))
      and "resize:none}.ianswer textarea:focus-visible" in bd._css() and "resize:vertical" not in bd._css() and "cursor:row-resize" in bd._css() and "@media(pointer:coarse){.rsz{display:none}.abox textarea{" in bd._css()
      and "setPointerCapture" in ui_render._ABOX_JS and "'ArrowDown'" in ui_render._ABOX_JS and all(ui_render._ABOX_JS in p for p in (p1, p2)) and ui_render._ABOX_JS not in page("a1"), p1[p1.find('class="abox"'):][:500])
check("not signed in: no box at all", '<form class="ianswer"' not in page("a1") and '<form class="ianswer"' not in page("a2"))

# ---- 4. Next: every line, numbered, each named, nothing folded
nx = lambda h: (lambda m: m.group(1) if m else "")(re.search(r'<summary><h2>(?:Next|After the wait)</h2></summary>(.*?)</details><details class="fold" data-fold="item.description"', h, re.S))   # Next's own body (a waiting item's is headed "After the wait")
n1, n2 = nx(p1), nx(p2)
OLI = lambda *xs: '<ul class="inext" aria-label="Next steps">' + "".join(f'<li class="cl-open"><span class="cb" aria-hidden="true"></span><div class="cl-b"><span class="sr">To do: </span><span class="cl-t">{x}</span></div></li>' for x in xs) + "</ul>"      # Next is a checklist
check("five lines: all five drawn in order in one checklist, no '+N more', no fold", n1.count("<li ") == 5
      and n1 == OLI("Oliver: step 1", "Oliver: step 2", "Oliver: step 3", "Oliver: step 4", "Oliver: step 5")
      and n1.count("<ul") == 1 and "more" not in n1 and "<details" not in n1 and "<summary" not in n1 and "inextmore" not in p1 and "next-more" not in p1 and "start=" not in n1, n1)
check("three lines or fewer: no fold", "+" not in nx(p3) and "<details" not in nx(page("a10")))
check("the fold's style is gone from the page", "inextmore" not in p1 and "summary.more" not in p1)
check("every line starts with its mover: an unnamed one gets the item's mover; a bare bullet is a step of its own (nextlines' lines) and takes no mover in front of it", '<span class="cl-t">home-other: do the first thing</span>' in n2 and '<span class="cl-t">home-other: second thing</span></div></li>' in n2 and '<span class="cl-t">a sub step</span></div></li>' in n2 and n2.count("<li ") == 5 and "more" not in n2, n2)
check("a waiting item's unnamed next would name the post-wake mover", '<span class="cl-t">home-other: check the date</span>' in nx(p3), nx(p3))
check("no Next on a closed item", "<h2>Next</h2>" not in p7)
check("every section is a fold with the same heading markup: Next and Background open, History and Comments closed; the description is headed Background",
      all(f'<details class="fold" data-fold="item.{k}"{o} id="{k}"><summary><h2>{t}' in p1 for k, o, t in (("next", " open", "Next"), ("description", " open", "Background"), ("history", "", "History"), ("comments", "", "Comments")))
      and "<h2>Description</h2>" not in p1 and p1.count("<h2>") >= 4, re.findall(r'<details class="fold"[^>]*>', p1))
bgp = lambda h: [h.find(s_) for s_ in ('<p class="istate">', '<div class="iask">', "<h2>Next</h2>", "<h2>Background</h2>", "<h2>History", "<h2>Comments")]
check("the page's order: title and state line; the ask; Next; Background; History; Comments", (lambda o: min(o) > 0 and o == sorted(o))(bgp(p1)) and p1.index("</h1>") < p1.index('<p class="istate">'), bgp(p1))
check("the Background shows the stored description (the field keeps its name) and says none when there is none", "A thing. It lives here." in p1[p1.index("<h2>Background</h2>"):p1.index("<h2>History")], p1[p1.index("<h2>Background</h2>"):][:300])

# ---- 5. the wait and its chases
wt5, wt6, wt3 = wt(p5), wt(p6), wt(p3)
check("the wait block of an anchor wait: the anchor linked, the event, who watches, the backstop, then, the chases (count, when, who, note)",
      '<a href="https://github.com/o/r/pull/9"' in p5 and "the review lands" in wt5 and "Watched by" in wt5 and "the anchor module" in wt5 and "Backstop" in wt5 and "Picks it up" in wt5
      and "Chases" in wt5 and "2 " in wt5 and "asked in the PR" in wt5 and "pinged the reviewer" in wt5 and 'drop it?' in wt5, wt5)
check("a relay wait: the party's event, ask by, none chased yet", "Acme" in wt6 and "Ask by" in wt6 and "none yet" in wt6, wt6)
check("a time wait: his reason and no chases row; an alive or closed item has no wait block", "the vendor's holiday" in wt3 and "Chases" not in wt3 and all('class="iwait"' not in p for p in (p1, p2, p7)))
check("an item wait names the item and whether it is open", 'href="/items/a2"' in p4 and "(open)" in p4)

# ---- 6. the sidebar
sd1 = side(p1)
labels = lambda h: [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<dt>(.*?)</dt>", h)]      # every row's label, tags dropped (Owner and Creator carry a hover span, Anchors a count)
check("the sidebar's fields in order: mover, creator (no contact), project, then, priority, wake, anchors, then the More details fold with the rest",
      labels(sd1) == ["Mover", "Creator", "Project", "Then", "Priority", "Anchors 1", "Confirmed"], labels(sd1))
check("then: the session that takes the item after the owner's move, a sidebar row (the line under the title no longer says it)", re.search(r"<dt>Then</dt><dd>home-other</dd>", sd1) is not None and "Mover and then" not in sd1 and " then " not in istate(p1), sd1[:600])
check("priority is a tag, the anchor scoped to the item is listed", '<span class="tag t-p1">P1</span>' in sd1 and "slack.com" in sd1 and '<dt>Anchors <span class="count">1</span></dt>' in sd1)
check("a waiting item's sidebar: the one who picks it up is the Mover row and there is no Then row (it stands only beside the owner); its wake, backstop or ask by", "<dt>Then</dt>" not in side(p3) and "<dt>Mover</dt><dd>home-other" in side(p3) and "<dt>Wake</dt><dd>Thu Jan 1st</dd>" in side(p3) and "<dt>Backstop</dt>" in side(p5) and "<dt>Ask by</dt>" in side(p6), side(p3))
check("a closed item's sidebar has no Expected by (an open one has none either) and no then; the header says how it ended", "<dt>Expected by</dt>" not in side(p7) and "<dt>Then</dt>" not in side(p7) and istate(p7).startswith("Done"), side(p7))
check("today's other fields (due, confirmed) sit in a closed More details fold; the Mover row is not among them (it opens the panel); Whose move is gone", '<details class="fold imore" data-fold="item.more"><summary><h3>More details</h3></summary>' in sd1
      and "<dt>Mover</dt>" not in sd1.split("More details")[1] and "<dt>Confirmed</dt>" in sd1.split("More details")[1] and "<dt>Whose move</dt>" not in sd1)

# ---- 6a. the Mover row: first in the panel (Mover, Owner, Creator in one group), drawn once, on every kind of item; the title line names neither the mover nor the `then`
grp1 = lambda h: re.search(r'<aside class="iside"[^>]*><dl class="sgrp">(.*?)</dl>', h, re.S).group(1)
kinds = {"alive, a session moves it": ("a2", "home-other"), "alive, the owner moves it, a session next": ("a1", "home-other"), "alive, no mover and no then": ("a23", "no agent"),
         "waiting on a time": ("a3", "home-other"), "waiting on an item": ("a4", "home-other"), "closed": ("a7", "no agent")}
for what, (g, who) in kinds.items():
    h_ = page(g); sl_ = istate(h_)
    check(f"the Mover row opens the panel ({what}): Mover, then Creator, in the first group; it names {who}; drawn once on the whole page",
          labels(grp1(h_)) == ["Mover", "Creator"] and re.match(rf"<dt>Mover</dt><dd>{who}\b", grp1(h_)) is not None and h_.count("<dt>Mover</dt>") == 1 and "mover" not in sl_ and "then" not in sl_, (labels(grp1(h_)), sl_))
check("with a contact the group is Mover, Owner, Creator, in that order, and every other row keeps its place after it",
      labels(grp1(page("a1", contact="home-other"))) == ["Mover", "Owner", "Creator"] and labels(side(page("a1", contact="home-other")))[:6] == ["Mover", "Owner", "Creator", "Project", "Then", "Priority"], labels(side(page("a1", contact="home-other"))))
check("a hostile mover name is escaped in the Mover row", "<dt>Mover</dt><dd>&lt;i&gt;evil&lt;/i&gt;</dd>" in grp1(page("a26")) and "<i>evil" not in page("a26").split("<h2>")[0], grp1(page("a26")))
check("a waiting item says who picks it up in the sidebar's Mover row and in the wait block, never on the line under the title (nothing is lost with it); it has no Then row",
      all("<dt>Then</dt>" not in side(h_) and "<dt>Mover</dt><dd>home-other" in side(h_) and re.search(r"Picks it up\s+home-other", wt(h_)) is not None and "then" not in istate(h_) for h_ in (p3, p4, p5, p6)), [istate(h_) for h_ in (p3, p4)])

# ---- 6b. the Creator row: under Owner, on open and closed items, the History's name, a clear label when there is none
CR_LBL = '<dt><span title="who created this item">Creator</span></dt>'
cre = lambda h: re.search(r"<dt><span title=\"who created this item\">Creator</span></dt><dd>(.*?)</dd>", side(h))
created_by = lambda g: re.search(r"created by ([^<]*?)$", [html.unescape(re.sub(r"<[^>]+>", "", x.replace("</div>", "\n"))).strip().split("\n") for x in hist(page(g))][-1][-1]).group(1)
hist = lambda h: re.findall(r'<li class="ev ev-[a-z]+">.*?</li>', h[h.find('id="history"'):h.find('id="comments"')], re.S)
p80, p81, p82 = page("a80"), page("a81"), page("a82")
check("a Creator row is in the sidebar of an open item and of a closed one", all(CR_LBL in side(h) for h in (p1, p2, p7, p80)), side(p1)[:500])
check("…right below Owner when the item has a contact (the same group, Mover above them), and right below Mover when it has none",
      re.search(r'<dl class="sgrp"><dt>Mover</dt><dd>[^\n]*?</dd><dt><span title="[^"]*">Owner</span></dt><dd>home-other</dd>' + re.escape(CR_LBL), side(page("a1", contact="home-other"))) is not None
      and re.match(r'<aside class="iside" aria-label="Details"><dl class="sgrp"><dt>Mover</dt><dd>.*?</dd>' + re.escape(CR_LBL), side(p1)) is not None, side(page("a1", contact="home-other"))[:500])
check("…and it names the creator, the same name as the History's \"created by\" (home-here, and home-other for a session that is not the mover's)",
      cre(p1).group(1) == "home-here" == created_by("a1") and cre(p7).group(1) == "home-here" == created_by("a7") and cre(p80).group(1) == "home-other" == created_by("a80"), (cre(p1), cre(p80)))
check("an item that names no creator reads \"unknown\" in a muted span, never blank, on an open and a closed item",
      all(cre(h) is not None and cre(h).group(1) == '<span class="dim">unknown</span>' for h in (p81, p82)), (cre(p81), cre(p82)))
check("…and the History keeps its own wording for it (\"nobody\")", created_by("a81") == "nobody", created_by("a81"))

# ---- 7. History: one line per revision, with its author; Comments apart; the folds
h8 = page("a8")
hist = lambda h: re.findall(r'<li class="ev ev-[a-z]+">.*?</li>', h[h.find('id="history"'):h.find('id="comments"')], re.S)
lines = [html.unescape(re.sub(r"<[^>]+>", "", x.replace("</div>", "\n"))).strip().split("\n") for x in hist(h8)]
check("one entry per revision, newest first: a header line with the author and the time, then one bullet per change",
      len(lines) == 3 and re.fullmatch(r"Oliver · \w{3} \w{3} \d+\w\w \d\d:\d\d", lines[0][0]) and lines[0][1:] == ["subject edited (was “[home] history item”)"]
      and lines[1][0].startswith("home-other · ") and lines[1][1:] == ["priority: p2 → p1"] and lines[2][0].startswith("home-other · ") and lines[2][1:] == ["created as “[home] history item” · On agent · mover home-other · created by home-here"], lines)
h41 = page("a41")
lines41 = [html.unescape(re.sub(r"<[^>]+>", "", x.replace("</div>", "\n"))).strip().split("\n") for x in hist(h41)]
check("History writes a mover change as `mover: A → B`, and no line for a change of the stored creator, never `owner:`",
      ["mover: home-other → home-here"] in [l[1:] for l in lines41] and not any(("keeper of record" in " ".join(l)) for l in lines41) and "owner:" not in " ".join(sum(lines41, [])), lines41)
lines42 = [html.unescape(re.sub(r"<[^>]+>", "", x.replace("</div>", "\n"))).strip().split("\n") for x in hist(page("a42"))]
lines43 = [html.unescape(re.sub(r"<[^>]+>", "", x.replace("</div>", "\n"))).strip().split("\n") for x in hist(page("a43"))]
check("History: a step handed to the next session shows the plain mover change and its own `step hand-over:` line", lines42[0][1:] == ["needs: home-here", "mover: home-other → home-here", "step hand-over: item moved from home-other to home-here"], lines42)
check("History: a hand-over that could not be made says the session isn't running and who keeps the item (and no mover change)", lines43[0][1:] == ["step hand-over: the next step is home-gone's but that session isn't running; it stays with home-other"], lines43)
check("History: in the two hand-over fixtures (moved, fallback) the line sits once on the revision that made it and the creation revision has none", [sum(x.startswith("step hand-over:") for x in l) for l in lines42] == [1, 0] and [sum(x.startswith("step hand-over:") for x in l) for l in lines43] == [1, 0], (lines42, lines43))
check("…the creation line names the mover",  any(l[1:] == ["created as “[home] mover history” · On agent · mover home-other · created by home-here"] for l in lines41), lines41)
check("…the author in bold and the time in the board's zone share the header line, as on GitHub",
      all(re.match(r'<li class="ev ev-[a-z]+"><div class="eh"><b>[^<]+</b> · <span class="t">\w{3} \w{3} \d+\w\w \d\d:\d\d</span></div><div class="w"><div class="eb">', x) for x in hist(h8)), hist(h8)[:2])
check("the count on the History fold is the number of lines", '<h2>History <span class="count">3</span></h2>' in h8, h8[h8.find('id="history"'):][:200])
check("the three folds: Background open, History and Comments closed by default, with their counts", '<details class="fold" data-fold="item.description" open id="description">' in h8
      and '<details class="fold" data-fold="item.history" id="history">' in h8 and '<details class="fold" data-fold="item.comments" id="comments">' in h8
      and 'no comments' in h8 and ui_render._FOLD_JS in h8 and ui_render._FOLD_HEAD in h8)
check("closed items keep Background, History and Comments", all(f'id="{k}"' in p7 for k in ("description", "history", "comments")))

# ---- 8. what stayed: the For you control, the answer route's form, the old badges that mean something
wq = {"action": "/items/a1/watch", "token": "W", "flag": "", "watched": True, "why": "it asks for you"}
check("the For you control stays in the sidebar", "<dt>For you</dt>" in side(page("a1", watch=wq)) and 'action="/items/a1/watch"' in page("a1", watch=wq))
check("the answer form posts as before, with the token and the buttons", 'method="post" action="/items/a1/answer"' in p1 and '<input type="hidden" name="token" value="TOKEN">' in p1
      and p1.count('name="act"') == 1 and '<button type="submit" class="b main" name="act" value="answer">Send</button>' in p1 and "Send as" not in p1)
pc2 = page("a2", answer=BOX)
check("one Send button: it answers while the item needs his decision (act=answer), and is a comment otherwise (act=comment)",
      '<button type="submit" class="b main" name="act" value="comment">Send</button>' in pc2 and 'name="act" value="answer"' not in pc2 and "Send as" not in pc2 and pc2.count('name="act"') == 1, pc2[pc2.find('class="ianswer"'):][:600])
check("a mobile order puts the state line, the ask and the wait before the sidebar", ".imain>.istat,.imain>.iask,.imain>.ianswer,.imain>.iwait,.imain>.ioutcome{order:0}.iside{order:1}" in p1 and ".iwhere" not in p1)
check("the page's header draws the search box once, after the title bar, and no marker comment is left", p1.count('<form class="sbox"') == 1 and "the search box goes here" not in p1
      and p1.index('class="hbar"') < p1.index('<form class="sbox"') < p1.index("</h1>"))
try: page("a99"); check("an unknown id is a KeyError", False)
except KeyError: check("an unknown id is a KeyError", True)

# ---- 9. review findings: bulleted and numbered next lines, fenced blocks, his ask on old data, clipping, escaping
bul = nx(page("a11"))
check("five named bullets or numbers: all five drawn in one list, nothing folded; no marker doubles the list's own numbering",
      bul.count("<li ") == 5 and OLI("home-other: step 1", "home-other: step 2", "home-other: step 3", "home-other: step 4", "home-other: step 5") in bul and "more" not in bul and not re.search(r'cl-t">\s*(?:[-*+•]|\d+[.)])\s', bul), bul)
nb = nx(page("a12"))
check("a bullet that opens with a name is a line of its own: two lines, the marker dropped", nb.count("<li ") == 2 and '<span class="cl-t">home-other: do x</span>' in nb and '<span class="cl-t">Oliver: run <code>cmd</code></span>' in nb, nb)
nu = nx(page("a16"))
check("an unnamed bullet and a numbered one are steps of their own, an indented line belongs to the step above (nextlines' lines)", nu.count("<li ") == 3 and nu == OLI("home-other: do x", "an unnamed bullet", "a numbered one").replace("<span class=\"cl-t\">an unnamed bullet</span>", "<span class=\"cl-t\">an unnamed bullet</span><ul><li>an indented line</li></ul>"), nu)
from stackshot.web import itempage; from stackshot.model import model as _mdl
ls = itempage.next_lines("home-other: do x\n- Oliver: run `cmd`", "home-other")
check("itempage.next_lines counts a named bullet as a line", [x.text for x in ls] == ["home-other: do x", "Oliver: run `cmd`"] and all(not x.subs for x in ls), ls)
nf = nx(page("a13")); lf = itempage.next_lines(json.loads((T / "store/a/13.json").read_text())["metadata"]["next"], "home-other")
check("a fenced block stays whole under its line, never a line of its own and never given a mover", len(lf) == 2 and lf[0].text == "Oliver: run this:" and lf[0].subs == ["```\nls -l\nOliver: not a line\n```"]
      and lf[1].text == "home-other: then this" and lf[1].subs == ["~~~\nsecond\n~~~"], lf)
check("…and the page draws the block as code inside the line, 'not a line' unprefixed", nf.count('<pre><code>') == 2 and "ls -l\nOliver: not a line\n" in nf and "home-other: Oliver: not a line" not in nf and "<li>home-other: ```" not in nf and "+" not in nf, nf)
w14 = page("a14", answer=BOX)
check("needs=decision on a waiting item (old data): his ask, options and answer box still show, and the state line says it waits",
      istate(w14).startswith("Waiting · since") and 'class="iask"' in w14 and '<form class="ianswer"' in w14 and 'name="choice" value="Ship"' in w14 and '<form class="ianswer" data-comment-only' not in w14, istate(w14))
check("a closed item with needs decision left on it shows no ask", 'class="iask"' not in page("a7", answer=BOX))
long = ("Run the whole “vendor review” (the first pass, then the second pass) and send the summary to the owner so that the decision can be made before the end of the month; " * 3).strip()
c1, c2 = itempage.clip(long, 160), itempage.clip("He said “wait until the vendor answers about the (renewal and the price", 40)
check("clip cuts at a word or sentence end, never leaves a quote or bracket open, and says it cut", len(c1) <= 160 and c1.endswith(("…", ".")) and not c1.endswith(" …") and c1.count("“") == c1.count("”") and c1.count("(") == c1.count(")")
      and "“" not in c2 and "(" not in c2 and c2.endswith("…") and len(c2) <= 40, (c1, c2))
check("a short text passes whole and a word is never cut in two", itempage.clip("a short line", 160) == "a short line" and itempage.clip("alpha beta gamma delta", 14) in ("alpha beta…", "alpha beta"), itempage.clip("alpha beta gamma delta", 14))
p15 = page("a15", answer=BOX)
check("item data is escaped everywhere: the goal, subject, next, sub step, author and the latest change carry no live tag",
      "<script>alert" not in p15 and "<script>x<" not in p15 and "<img src=x" not in p15 and "<u>" not in p15 and "<i>sub" not in p15 and "<b>bold" not in p15 and "&lt;script&gt;" in p15 and "&lt;img src=x onerror=alert(1)&gt; &amp; more" in p15
      and "Goal &lt;b&gt;bold&lt;/b&gt; &amp; &lt;script&gt;x&lt;/script&gt;" in p15.split('<div class="ilayout">')[0] and "&lt;i&gt;sub&lt;/i&gt;" in p15, re.findall(r"<h1>.*?</h1>", p15))
check("…and a revision's author is escaped on the History line", "<b>&lt;u&gt;who&lt;/u&gt;</b> · <span class=\"t\">" in p15 and "created as “[home] &lt;script&gt;" in p15, p15[p15.find('id="history"'):][:400])

cm = itempage.clip_md
CM = "see [the long link text that is here](https://example.com/some/long/address/that/goes/on) and then `some code here` and **bold words** after"
cuts = [cm(CM, n) for n in range(10, len(CM))]
check("clip_md never cuts inside a link, a code span or a bold span, for every length",
      all(len(c) <= n for c, n in zip(cuts, range(10, len(CM)))) and all("](" not in c or c.count("[") == c.count("]") and c.count("](") == c.count(")") - c.count("(") + c.count("](") for c in cuts)
      and all(c.count("`") % 2 == 0 and c.count("**") % 2 == 0 and "https://example.com/some" not in c.replace("https://example.com/some/long/address/that/goes/on)", "") for c in cuts), [c for c in cuts if "](" in c or c.count("`") % 2 or c.count("**") % 2][:3])
check("clip_md keeps a link's text alone when the cut falls in its address, drops a code span whole, and leaves a short text as it is",
      cm("see [the link](https://example.com/a/very/long/address/indeed) and more words", 30) == "see the link…" and cm("run `uv run something long` now please", 12) == "run…" and cm("short [a](https://x.y) text", 160) == "short [a](https://x.y) text",
      (cm("see [the link](https://example.com/a/very/long/address/indeed) and more words", 30), cm("run `uv run something long` now please", 12)))


# ---- 11. the state label is a tag
check("the state label is a tag of the lists' kind: your move, on agent, waiting and done each their own colour class, defined in both themes (the Your move one reads the page's --orange, which each theme sets)",
      '<span class="tag t-you">Your move</span>' in p1 and '<span class="tag t-agent">On agent</span>' in p2 and '<span class="tag t-wait">Waiting</span>' in page("a5") and '<span class="tag t-done">Done</span>' in p7
      and all(p1.count(f"--t-{k}:") >= 2 and p1.count(f"--t-{k}-bg:") >= 2 for k in ("agent", "wait", "done"))
      and "--t-you:var(--orange)" in p1 and "--t-you-bg:color-mix(in srgb,var(--orange) 12%,var(--card))" in p1 and p1.count("--orange:") >= 3, re.findall(r'<span class="tag t-[a-z]+">[^<]*</span>', p1 + p7)[:4])

check("History: the marker dot is drawn on the entries only (ul.hist > li), so a list nested in a fold keeps its own bullets", "ul.hist>li::before{content:''" in p1 and "ul.hist li::before{" not in p1, None)

# ---- 13. a your-step item that is his move: what comes next is the step itself
w23, w24 = page("a23"), page("a24")
check("your-step, his move: the step form is under the state line and shows the step; no other section repeats it",
      '<div class="iask istep"><b>Your step</b>' in w23 and w23.index('<div class="iask istep">') > w23.index('<div class="istat">') and w23.index('<div class="iask istep">') < w23.index("<h2>Next</h2>")
      and "<code>uv run tools/x.py --go</code>" in w23[w23.find('<div class="iask istep">'):][:800] and w23.count("uv run tools/x.py --go") == 1, w23[w23.find('<div class="istat">'):][:900])
check("…and a mover who is not Oliver keeps no Your step block", 'class="iask istep"' not in w24 and 'class="iask istep"' not in page("a10"), None)

# ---- 14. review of the state line's latest change: a hostile step, mover and author; italics in clip_md; the comment box's words
w25, w26, w28 = page("a25"), page("a26"), page("a28")
top = lambda h: h[h.find('<div class="istat">'):h.find("<h2>Next</h2>")]      # the state line, the step form under it and the ask: everything above Next
check("a hostile step and mover label are escaped above Next and in the sidebar's Mover row",
      all("<script>" not in top(x) and "<img" not in top(x) and "<i>evil" not in top(x) and "<u>" not in top(x) and "<b>x</b>" not in top(x) for x in (w25, w26))
      and "<i>evil" not in side(w26) and "&lt;script&gt;alert(1)&lt;/script&gt;" in top(w25) and "&lt;i&gt;evil&lt;/i&gt;" in side(w26), (top(w25), side(w26)))
IT = "run the *careful pass* over snake_case_names and _every other_ file, then go on with the rest of the list for the day, one at a time"
cuts = {n: itempage.clip_md(IT, n) for n in range(12, len(IT))}
check("clip_md protects *italic* and _italic_ spans like bold (no stray marker after a cut) and leaves snake_case alone",
      all(c.count("*") % 2 == 0 for c in cuts.values())
      and all(("*careful" not in c) or ("pass*" in c) for c in cuts.values()) and all(("_every" not in c) or ("other_" in c) for c in cuts.values())
      and any("snake_case_names" in c for c in cuts.values()) and all(len(c) <= n for n, c in cuts.items()), [c for c in cuts.values() if "*careful" in c and "pass*" not in c or "_every" in c and "other_" not in c][:3])
check("a hostile step field with no line of his on the checklist is drawn escaped (the step field is the fallback)",
      "<script>" not in top(w28) and "<b>x</b>" not in top(w28) and "<u>" not in top(w28) and "&lt;script&gt;alert(1)&lt;/script&gt;" in top(w28) and "more" in top(w28), top(w28))
check("on a non-decision item the box says it is a comment; on a decision item it is the answer",
      "Write a comment; the agent on it is told" in page("a9", answer=BOX) and "Your answer" not in page("a9", answer=BOX) and "Your answer" in page("a1", answer=BOX) and "Note (optional)" in page("a1", answer=BOX) and "Note (optional)" not in page("a9", answer=BOX))

# ---- 10. History like GitHub's: a header line, then one bullet per change, a text field's text in a closed fold
h21 = page("a21"); hs21 = h21[h21.find('id="history"'):h21.find('id="comments"')]
es21 = ['<li class="ev ev-' + x for x in hs21.split('<li class="ev ev-')[1:]]      # a fold's own list holds <li>s: split on the entries
tx21 = lambda x: [y.strip() for y in html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</(div|summary)>", "\n", x))).split("\n") if y.strip()]
check("History: three revisions, newest first, one entry each, the author and the time on one header line",
      len(es21) == 4 and all(re.match(r'<li class="ev ev-[a-z]+"><div class="eh"><b>[^<]+</b> · <span class="t">[^<]+</span></div>', x) for x in es21[:3]) and "<b>Oliver</b>" in es21[0] and "<b>home-other</b>" in es21[1], [x[:140] for x in es21])
check("History: a scalar field reads 'state your-step → doing' and a next line shows its first line with the rest folded",
      "state your-step → <b>doing</b>" in es21[0] and "next: home-other: short one" in tx21(es21[0]), tx21(es21[0]))
check("History: the description edited again reads 'description edited' and holds the new text in a closed fold, never inline",
      '<div class="eb">description edited<details class="ehold"><summary class="more">the new description</summary>' in es21[1] and "<details class=\"ehold\" open" not in es21[1]
      and "a fifth fact" in es21[1] and "a fifth fact" not in re.sub(r"<details.*?</details>", "", es21[1], flags=re.S), es21[1][:500])
bl = re.findall(r'<div class="eb">(.*?)(?:<details|</div>)', es21[2], re.S)
check("History: a next line over 160 characters is clipped to one line with no half link and a fold for the whole next; the fold holds the rest",
      bl[0].startswith("next: home-other: go through") and bl[0].endswith("PR #28…") and "](" not in bl[0] and 'summary class="more">the whole next' in es21[2] and "second line" in es21[2].split("the whole next")[1], bl)
check("History: the dump (next, ask, options and the description in one revision) is four bullets, the field text only inside closed folds",
      len(bl) == 4 and bl[1:] == ["ask edited", "options edited", "description edited"] and es21[2].count('<details class="ehold">') == 4 and "<details class=\"ehold\" open" not in es21[2], bl)
bare = re.sub(r"<details.*?</details>", "", es21[2], flags=re.S)
check("History: text in a fold is escaped, and no field text sits outside a fold", "<script>" not in hs21 and "script&gt;alert(1)" in es21[2] and "one fact about the item" in es21[2] and "one fact about the item" not in bare and "Recommend: ship" not in bare, es21[2][-700:])
ev21 = [(k, x) for _t, k, x in bd.item_events(bd.item("a21"))[0]]
check("item_events (the search index, the migration comment) gives the bullets: no fold, no field text",
      all("<details" not in x and "one fact about the item" not in x and "second line" not in x for _k, x in ev21) and any("description edited" in x for _k, x in ev21), ev21[:4])

h22 = page("a22"); hs22 = h22[h22.find('id="history"'):h22.find('id="comments"')]
e22 = ['<li class="ev ev-' + x for x in hs22.split('<li class="ev ev-')[1:]][0]
check("History: the ask that leaves with the decision is a bullet with the Decide line and a closed fold holding the whole ask, never clipped away",
      '<div class="eb">the ask was: whether to ship<details class="ehold"><summary class="more">the whole ask</summary>' in e22 and "Recommend: ship" in e22.split("the whole ask")[1] and "Recommend: ship" not in re.sub(r"<details.*?</details>", "", e22, flags=re.S), e22[:700])
ev22 = [x for _t, k, x in bd.item_events(bd.item("a22"))[0] if "the ask was" in x]
check("…and item_events (the search, the migration comment) takes the bullet alone", ev22 and all("<details" not in x and "Recommend" not in x for x in ev22), ev22)
# ---- 12. the step of a your-step item: its block, directly under the state line, with the note box and ONE Send (no Done)
S20, S21, S22, S23, S24 = (page(f"a{i}", answer=BOX) for i in (30, 31, 32, 33, 34))
blk = lambda h: (re.search(r'<div class="iask istep">.*?</div></div>', h, re.S) or [""])[0]
check("a step item shows a Your step block directly after the state line and before Next, the note box and ONE Send in it, no Done",
      S20.find('class="iask istep"') > S20.find('<div class="istat">') > 0 and S20.find('class="iask istep"') < S20.find("<h2>Next</h2>")
      and "<b>Your step</b>" in S20 and S20.count('name="act" value="send">Send</button>') == 1 and 'value="done"' not in S20 and 'value="comment"' not in S20 and ">Done<" not in S20 and "A note, or nothing: Send with an empty box finishes the step" in S20 and (lambda f: f.count('<button type="submit"') == 1)(S20[S20.find('<form class="ianswer"'):S20.find('</form>', S20.find('<form class="ianswer"'))])
      and "<textarea" in S20 and S20.count('<form class="ianswer"') == 1 and 'name="choice"' not in S20, S20[S20.find('class="iask istep"'):][:600])
check("the step form's note box has the resize wrapper: its textarea inside .abox with the handle, and the page carries the resize script", re.search(r'<div class="abox"><textarea id="atext" name="text".*?</textarea><div class="rsz" role="separator"', S20) is not None and ui_render._ABOX_JS in S20)
b20 = blk(S20)
check("a command in the step is a copyable code block, the line says 'the command below', the command is exactly as the item wrote it",
      '<div class="cmd"><pre><code>sala op reauth box-a --from me --words &quot;go&quot;</code></pre><button type="button" class="b copy"' in b20 and "the command below" in b20, b20)
b21 = blk(S21)
check("a `! ...` pane line stays verbatim in one code block, with no text line around it", '<pre><code>! sala reauth box-a</code></pre>' in b21 and b21.count('<div class="cmd">') == 1 and 'istepbody"><div class="cmd">' in b21, b21)
b22 = blk(S22)
check("a step with only a link keeps it inline as a link that opens in a new tab, in no code block", 'href="https://example.com/login/now" target="_blank" rel="noopener"' in b22 and "Sign in at" in b22 and "<pre>" not in b22 and 'class="cmd"' not in b22, b22)
S44, S45, S46 = (page(f"a{i}", answer=BOX) for i in (44, 45, 46))
b44, b45, b46 = blk(S44), blk(S45), blk(S46)
_alinks = lambda h: re.findall(r'<a href="(https://example\.com/p/[a-z]+)" target="_blank" rel="noopener">', h)
check("a step with two links and no command draws both as links and no Copy box", _alinks(b44) == ["https://example.com/p/aaa", "https://example.com/p/bbb"] and "<pre>" not in b44 and 'class="b copy"' not in b44 and "and say done" in b44, b44)
check("a step with a command and a link boxes the command only; the link stays inline", b45.count('<div class="cmd">') == 1 and '<pre><code>sala op reauth box-a</code></pre>' in b45 and _alinks(b45) == ["https://example.com/p/aaa"]
      and "https://example.com/p/aaa</code>" not in b45 and "the command below" in b45, b45)
check("a step with a lone-word backtick keeps it inline, no Copy box", "<code>default</code>" in b46 and "<pre>" not in b46 and 'class="b copy"' not in b46, b46)
b23 = blk(S23)
check("a step of plain words is shown as it reads, with no code block", "Call the office and say done" in b23 and "<pre>" not in b23, b23)
check("the block and the form are only for an item with a step: a decision item, an agent item, a plain Oliver-moves item and a closed step item have none",
      all('class="iask istep"' not in page(f"a{i}", answer=BOX) for i in (1, 2, 10, 14)) and 'class="ianswer"' not in S24, [i for i in (1, 2, 10, 14) if 'class="iask istep"' in page(f"a{i}", answer=BOX)])
Q30, Y31 = page("a35", answer=BOX), page("a36", answer=BOX)
acts = lambda h: re.findall(r'<button type="submit"[^>]*name="act" value="([^"]*)">([^<]*)</button>', h[h.find('<form class="ianswer"'):])
check("an ask with no options has no Approve or Decline (item page): it has Yes and No option cards, Yes first and marked recommended",
      "Approve" not in Q30 and "Decline" not in Q30 and re.findall(r'name="choice" value="([^"]*)"', Q30) == ["Yes", "No"]
      and '<span class="alab">Yes</span> <span class="badge rec">recommended</span>' in Q30 and '<span class="alab">No</span><span class="adesc">' in Q30, re.findall(r'name="choice" value="([^"]*)"', Q30))
check("no Yes or No on an item with stored options, on an item that asks no decision or on a closed one (item page)",
      all('value="Yes"' not in x and 'value="No"' not in x for x in (Y31, page("a1", answer=BOX), page("a9", answer=BOX), page("a4", answer=BOX))), None)
check("an open question gets the note box and one Send, which posts act=answer; no Done, no comment button (beside Yes and No)",
      '<textarea id="atext" name="text"' in Q30 and acts(Q30) == [("answer", "Send")] and 'value="done"' not in Q30 and "Your step" not in Q30, acts(Q30))
check("Approve and Decline stored as the options give exactly those two option cards, the recommended one first and marked; the box keeps its one Send",
      re.findall(r'name="choice" value="([^"]*)"', Y31) == ["Approve", "Decline"] and '<span class="alab">Approve</span> <span class="badge rec">recommended</span>' in Y31 and ("answer", "Send") in acts(Y31) and len(acts(Y31)) == 1 and 'value="done"' not in Y31, acts(Y31))
M37 = page("a37", answer=BOX)
check("a decision with misshaped options has no option cards, so the box is labelled 'Write your answer; the agent on it is told' (not the note label) and its Send is the main button; with option cards the note label is kept",
      'name="choice"' not in M37 and '<label for="atext">Write your answer; the agent on it is told</label>' in M37 and "Note (optional)" not in M37
      and '<button type="submit" class="b main" name="act" value="answer">Send</button>' in M37
      and '<label class="anote" for="atext">Note (optional)</label>' in Q30 and '<label class="anote" for="atext">Note (optional)</label>' in Y31, M37[M37.find('<form class="ianswer"'):][:700])
check(", no page has a Done button now; the step form's one Send posts act=send", all('value="done"' not in page(f"a{i}", answer=BOX) for i in (1, 2, 9, 10, 14, 35, 36)) and 'name="act" value="send"' in S20)
check("the decision item keeps today's ask block and form", 'class="iask"' in p1 and '<form class="ianswer"' in p1 and 'name="choice" value="Ship"' in p1 and 'name="act" value="done"' not in p1)
check("with no answer box (signed out) the step is still on the page, with no form", "<b>Your step</b>" in page("a30") and "<form" not in blk(page("a30")) and 'value="done"' not in page("a30"))
check("the answer script is on the page only when the page has a form: a step item with the box has it, signed out (the step block alone) has not",
      "querySelector('form.ianswer')" in S20 and "querySelector('form.ianswer')" not in page("a30"), None)
check("ctrl+enter: the item page carries the key script exactly when it carries an answer or comment box (a step item, a decision, a comment-only item), not signed out",
      S20.count(ui_render._SENDKEY_JS) == 1 and page("a30").count(ui_render._SENDKEY_JS) == 0 and page("a1", answer=BOX).count(ui_render._SENDKEY_JS) == 1 and page("a1").count(ui_render._SENDKEY_JS) == 0
      and "requestSubmit(b)" in ui_render._SENDKEY_JS and "e.isComposing" in ui_render._SENDKEY_JS, None)
check("a disabled button takes no hover accent", ".b:hover:not(:disabled)" in S20 and ".b.std" not in S20 and ".b.pri" not in S20 and ".abtn" not in S20.replace(".abtns", ""))
sb = itempage.step_block; ld = lambda i: json.loads((T / f"store/a/{i}.json").read_text())
s20, s21, s22, s23 = sb(ld(30)), sb(ld(31)), sb(ld(32)), sb(ld(33))
check("itempage.step_block: a command leaves the text for a block; a `!` line is the one verbatim block; a link stays in the text and is no block; plain words have no block",
      s20 and s20.blocks == ['sala op reauth box-a --from me --words "go"'] and "the command below" in s20.text and not s20.verbatim
      and s21 and s21.verbatim and s21.blocks == ["! sala reauth box-a"] and s21.text == ""
      and s22 and s22.blocks == [] and "https://example.com/login/now" in s22.text and s23 and s23.blocks == [] and s23.text.startswith("Call the office"), (s20, s21, s22, s23))
check("itempage.step_block: None for a closed item, an item with no state, and a your-step item with no step line",
      sb(ld(34)) is None and sb(ld(10)) is None and sb({"status": "open", "metadata": {"state": "your-step"}}) is None and sb({"status": "open", "metadata": {"state": "your-step", "step": "  "}}) is None)

# ---- 13. the comment box: in the answer box's slot, open, on every open item the owner does not move; the Comments fold keeps the list only
def open_details(h, at):             # how many <details> are open around position `at`: any enclosing fold, open or closed, makes it more than 0
    return h[:at].count("<details") - h[:at].count("</details>")
CF = '<form class="ianswer" data-comment-only'
NOT_HIS = {"a2": "doing", "a3": "waiting on a time", "a4": "waiting on an item", "a5": "waiting on an anchor", "a6": "waiting on a relay", "a70": "verifying", "a71": "doing, with a comment"}
HIS = {"a1": "a decision", "a35": "an open question", "a36": "approve or decline", "a37": "misshaped options", "a14": "a waiting item with a decision left",
       "a10": "a step of his, no ask", "a30": "a step with a command", "a23": "a your-step item", "a60": "a call handed to him", "a61": "a step handed to him"}
PG_THEIRS = {g: page(g, answer=BOX) for g in NOT_HIS}; PG_HIS = {g: page(g, answer=BOX) for g in HIS}
check("fixtures: the verifying item reads as waiting, a doing one as on its agent", istate(PG_THEIRS["a70"]).startswith("Waiting") and not istate(PG_THEIRS["a2"]).startswith("Waiting"), (istate(PG_THEIRS["a70"]), istate(PG_THEIRS["a2"])))
def slot_problems(h):
    """why the comment box is not drawn where the answer box would be: once, a form of its own, outside every fold, straight after the state line and before every section"""
    bad = []
    if h.count('<form class="ianswer"') != 1 or h.count(CF) != 1: bad.append("not exactly one comment form")
    if h.count('name="act" value="comment"') != 1 or h.count('<button type="submit" class="b main" name="act" value="comment">Send</button>') != 1: bad.append("not exactly one comment button")
    at = h.find(CF)
    if at < 0: return bad + ["no comment form"]
    if open_details(h, at): bad.append("the form sits inside a fold")
    st = h.find('<div class="istat">')
    if not 0 <= st < at: bad.append("the form is not after the state line")
    elif any(t in h[st:at] for t in ("<details", "<h2", "<section", "<ul", "<ol")): bad.append("a section sits between the state line and the form")
    for sec in ('id="next"', 'id="description"', 'id="history"', 'id="comments"'):
        i = h.find(sec)
        if i < 0 or i < at: bad.append("the form is not before " + sec)
    wi = h.find('<section class="iwait">')
    if wi >= 0 and wi < at: bad.append("the form is after the wait")
    return bad
check("an open item he does not move (doing, every wait, verifying, one with comments): the comment form is drawn once, open, straight under the state line and before Next, Background, History and Comments",
      all(slot_problems(h) == [] for h in PG_THEIRS.values()), {g: slot_problems(h) for g, h in PG_THEIRS.items() if slot_problems(h)})
check("…the form is the box as it was: the token, the comment text box, the comment button alone, no answer button, no cards",
      all('<input type="hidden" name="token" value="TOKEN">' in h and h.count('<textarea id="atext" name="text" rows="3" maxlength="4000"></textarea>') == 1 and 'name="act" value="answer"' not in h and "<form class=\"ianswer\" data-cards" not in h
          and "<b>Add a comment</b>" in h and "Write a comment; the agent on it is told" in h and 'method="post" action="/items/a1/answer"' in h for h in PG_THEIRS.values()), None)
check("…and open: not one fold wraps it, in every open state (doing, waiting, verifying), and its position is the same as the answer box's (after the state line, before Next)",
      all(open_details(PG_THEIRS[g], PG_THEIRS[g].find(CF)) == 0 for g in ("a2", "a3", "a70")) and open_details(PG_HIS["a1"], PG_HIS["a1"].find('<form class="ianswer"')) == 0
      and all(h.index('<div class="istat">') < h.index('<form class="ianswer"') < h.index('id="next"') for h in (*PG_THEIRS.values(), PG_HIS["a1"], PG_HIS["a35"], PG_HIS["a10"])), None)
check("an item he moves has exactly one form with a text box: the decision's, the question's, the step's, never a second comment form",
      all(h.count('<form class="ianswer"') == 1 and CF not in h and h.count("<textarea") == 1 for h in PG_HIS.values()),
      {g: (h.count('<form class="ianswer"'), h.count("<textarea")) for g, h in PG_HIS.items() if h.count('<form class="ianswer"') != 1 or CF in h or h.count("<textarea") != 1})
check("…its own buttons stay: answer on a decision, send on a step, a plain comment on his item that asks nothing; one button each",
      all(PG_HIS[g].count('name="act" value="answer"') == 1 for g in ("a1", "a36", "a14")) and all(PG_HIS[g].count('name="act" value="send"') == 1 for g in ("a30", "a23", "a61"))
      and PG_HIS["a10"].count('name="act" value="comment"') == 1 and all(h.count('name="act"') == 1 for h in PG_HIS.values()), None)
cm = lambda h: h[h.index('id="comments"'):h.index("</div></div><script>")]
check("the Comments fold keeps the list: his comment is in it, the count says 1, and it holds no form, a text box or a button; an item with none says so",
      "looks fine to me" in cm(PG_THEIRS["a71"]) and 'ev-comment' in cm(PG_THEIRS["a71"]) and '<span class="count">1</span>' in cm(PG_THEIRS["a71"])
      and all("<form" not in cm(h) and "<textarea" not in cm(h) and "<button" not in cm(h) for h in (*PG_THEIRS.values(), *PG_HIS.values())) and "no comments" in cm(PG_THEIRS["a2"]), cm(PG_THEIRS["a71"])[:500])
check("the Comments fold is still closed by default; the comment box is not behind it",
      all('<details class="fold" data-fold="item.comments" id="comments">' in h for h in PG_THEIRS.values()) and all(CF not in cm(h) for h in PG_THEIRS.values()), None)
check("a closed item keeps today's page: no form of any kind for the answer or a comment, with or without the box",
      all('<form class="ianswer"' not in page(g, answer=BOX) and '<form class="ianswer"' not in page(g) for g in ("a7", "a34")) and "<textarea" not in page("a7", answer=BOX))
check("signed out (no box handed over), an open item he does not move draws no comment form either, and no answer script", all('<form class="ianswer"' not in page(g) and ui_render._ANSWER_JS not in page(g) for g in NOT_HIS))
check("the answer, key and resize scripts ride with the box where it now sits", all(ui_render._ANSWER_JS in h and h.count(ui_render._SENDKEY_JS) == 1 and ui_render._ABOX_JS in h for h in PG_THEIRS.values()))
check("the comment box has the same .ianswer card as the answer box and no top margin of its own (the state line's own gap is the space above it)",
      ".ianswer[data-comment-only]" not in bd._css() and ".imain>.ianswer" in bd._css(), None)

# ---- the inputs' tokens ----
def _lum(hx):
    c = [int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5)]; c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
def _cr(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True); return (hi + .05) / (lo + .05)
_c = bd._css()
def _tok(rule, name):
    m = re.search(re.escape(rule) + r"\{[^}]*--" + name + r":(#[0-9a-f]{3,6})", _c); h = m.group(1) if m else None
    return "#" + "".join(ch * 2 for ch in h[1:]) if h and len(h) == 4 else h
_L = {n: _tok(":root", n) for n in ("ibd", "ifill", "iph", "bg", "card", "fg")}
_D = {n: _tok(":root[data-theme=dark]", n) for n in ("ibd", "ifill", "iph", "bg", "card", "fg")}
_ok = all(v and len(v) == 7 for d in (_L, _D) for v in d.values())
check("inputs: the border is 3:1 on the page, the card and the fill, the placeholder 4.5:1 on the fill, in light and dark (WCAG AA, non-text and text)", _ok
      and all(_cr(t["ibd"], t[k]) >= 3 for t in (_L, _D) for k in ("bg", "card", "ifill")) and all(_cr(t["iph"], t["ifill"]) >= 4.5 for t in (_L, _D))
      and all(_cr(t["fg"], t["ifill"]) >= 7 for t in (_L, _D)), (_L, _D))
check("inputs: the fill is lighter than the card in dark, and the answer, comment and note boxes, the home row's box and the search bar all take the tokens",
      _ok and _lum(_D["ifill"]) > _lum(_D["card"]) and _lum(_L["ifill"]) >= _lum(_L["card"])
      and "background:var(--ifill);border:1px solid var(--ibd)" in _c[_c.find(".ianswer textarea{"):_c.find(".ianswer textarea{") + 400]
      and "background:var(--ifill);border:1px solid var(--ibd)" in _c[_c.find("form.hanswer textarea{"):_c.find("form.hanswer textarea{") + 400]
      and "textarea::placeholder{color:var(--iph);opacity:1}" in _c and "border:1px solid var(--ibd" in _c[_c.find(".sbox input{"):_c.find(".sbox input{") + 300]
      and ".sbox input::placeholder{color:var(--iph" in _c, None)


# every page's title bar is the home h1 (logo and title) as a link to "/", and the side panel stands on it, pinned by default as on home (the stored closed state is panel_open_scenario's)
def title_panel_problems(p):
    bad = []
    if re.findall(r'<(?:h1|p) class="site"><a href="([^"]*)"><img class="logo"', p) != ["/"]: bad.append("title link is not exactly one href=/")
    if "\u2190 " in p.split("</main>")[0][:3000] and 'class="topline"' in p: bad.append("the old back arrow is still there")
    for need in (ui_render._PANEL_BODY + '<div id="layout">', '<aside id="panel"', 'id="panel-edge"', 'id="panel-scrim"', 'id="panel-open"', 'id="machines"', 'id="runners"', 'id="audit-panel"', ui_render._PANEL_JS[:60]):
        if need not in p: bad.append("missing " + need)
    # the item page is drawn like every page: pinned, the button offering to hide it (it no longer starts closed on its own; a person's stored closed state is put in on the way out)
    if p.count("<body") != 1 or ui_render._PANEL_BODY not in p: bad.append("the item page's body is not pinned (the panel would start closed)")
    if 'aria-expanded="true" title="Hide summary panel"' not in p[p.find('id="panel-open"') - 120:p.find('id="panel-open"') + 250]: bad.append("the panel button is not rendered for an open panel")
    if "stackshot.panel" in p or "localStorage" in ui_render._PANEL_JS: bad.append("the panel state is stored in the browser")
    if p.count('<aside id="panel"') != 1 or p.count("</div><script>") < 1: bad.append("panel not once / no script")
    return bad
check("title and panel: the item page has the home title as a link to / and the same side panel", title_panel_problems(page("a1")) == [], title_panel_problems(page("a1")))

if fails: print(f"FAILED: item page scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: item page scenario, {len(ran)} checks")
