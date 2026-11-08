"""Scenario test for closing an item like an issue tracker closes an issue — fixture data,
no live store, no network.

Covers: a close (complete, or update with status=completed) is refused without outcome, reason or an outcome_text (the end state;
the description stays as it was, tests/close_keeps_description_scenario.py), each refusal naming what is missing and, for a pane with an older cached schema, that it closes through the portal meanwhile; an
unknown outcome, a reason of more than one line, superseded without superseded_by, superseded_by with another outcome, naming
the item itself or an item that does not exist are refused; outcome, reason and superseded_by outside a close are refused. The
close clears next, ask and needs (and the hold and its wake), keeps due, and stores outcome, outcome_text, reason and superseded_by (an item
superseded by a completed one is fine); get shows them. Reopening needs a new next and drops them. The board: the completed list
shows the outcome as a tag; the item page shows outcome and reason at the top with superseded linking the other item, and no
next or ask for any completed item, old ones too; the history's completion event carries outcome and reason; board.md's
completed list carries them.

    tests/run-suite close        → exit 0 / 1"""
import json, os, re, sys, pathlib, subprocess, tempfile, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="closetest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
DESC = "- A thing\n- It lives here\n- Finished when it works"
def item(i, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                       "metadata": {"owner": OWNER, "project": "projects/alpha", **meta}}))
LIVE = {"next": "do the thing", "needs": "decision", "due": "2026-10-20",
        "ask": "Decide: whether to ship · Recommend: ship · Stakes: none either way · By: no date"}
for i in range(1, 8):
    item(i, **LIVE)
item(8, hold=True, wake="2026-12-01", next="later")
item(9, status="completed", **LIVE)       # closed before no outcome, its next and ask still in the file (no backfill)
(T / "store/next-id").write_text("20"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
def snap(msg): git("add", "-A"); git("commit", "-q", "--allow-empty", "-m", msg)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())

from stackshot.web import server
from stackshot.web.ui import render as ui_render
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except server.ToolError as e:
        check(name, all(w in str(e) for w in want), str(e))
NEW = "- The thing works and is in use"

# ---- 1. refusals
refused("an old cached schema (complete with the id alone): names what is missing and the portal path, never a relaunch",
        lambda: server.stackshot_complete("a1"), "closing a1 needs outcome, reason, outcome_text", "a relaunch does not",
        "portal_codemode_execute with codemode.stackshot_complete({item_id, outcome, reason, outcome_text, superseded_by})")
refused("update status=completed alone: the same", lambda: server._update("a1", status="completed"), "closing a1 needs outcome, reason, outcome_text", "codemode.stackshot_complete")
refused("no reason", lambda: server.stackshot_complete("a1", outcome="done", outcome_text=NEW), "needs reason")
refused("no outcome_text", lambda: server.stackshot_complete("a1", outcome="done", reason="it works"), "needs outcome_text")
refused("no outcome", lambda: server.stackshot_complete("a1", reason="it works", outcome_text=NEW), "needs outcome")
refused("an unknown outcome", lambda: server.stackshot_complete("a1", outcome="finished", reason="it works", outcome_text=NEW), "outcome must be one of done | dropped | superseded")
refused("a reason of two lines", lambda: server.stackshot_complete("a1", outcome="done", reason="it works\nand more", outcome_text=NEW), "reason is one line")
refused("an outcome_text that is not bullets", lambda: server.stackshot_complete("a1", outcome="done", reason="it works", outcome_text="It works now."), "outcome_text line is not a `- ` bullet")
refused("superseded without superseded_by", lambda: server.stackshot_complete("a1", outcome="superseded", reason="moved", outcome_text=NEW), "needs superseded_by")
refused("superseded_by with outcome done", lambda: server.stackshot_complete("a1", outcome="done", reason="it works", outcome_text=NEW, superseded_by="a2"), "superseded_by goes with outcome=superseded")
refused("superseded by itself", lambda: server.stackshot_complete("a1", outcome="superseded", reason="moved", outcome_text=NEW, superseded_by="A1"), "cannot be superseded by itself")
refused("superseded by an item that does not exist", lambda: server.stackshot_complete("a1", outcome="superseded", reason="moved", outcome_text=NEW, superseded_by="a99"), "a99, which does not exist")
refused("outcome on an open item without a close", lambda: server._update("a1", outcome="done"), "go with a close")
refused("outcome_text on an open item without a close", lambda: server._update("a1", outcome_text=NEW), "go with a close")
refused("reason outside a close", lambda: server._update("a1", next="x", reason="why"), "go with a close")
check("nothing above changed the item", rd(1)["status"] == "open" and rd(1)["metadata"]["next"] == "do the thing" and rd(1)["description"] == DESC, rd(1))

# ---- 2. a close: done, through complete
out = server.stackshot_complete("a1", outcome="Done", reason="PR #11 live at 010bc0d", outcome_text=NEW)
m = rd(1)["metadata"]
check("complete closes it, keeps the description and stores the outcome text", rd(1)["status"] == "completed" and rd(1)["description"] == DESC and m.get("outcome_text") == NEW, rd(1))
check("the close clears next, ask and needs", not any(k in m for k in ("next", "ask", "needs")), m)
check("due stays as a record", m.get("due") == "2026-10-20", m)
check("outcome (lower-cased) and reason are stored, no superseded_by", m.get("outcome") == "done" and m.get("reason") == "PR #11 live at 010bc0d" and "superseded_by" not in m, m)
check("the reply shows outcome, reason and outcome_text", "outcome: done" in out and "reason: PR #11 live at 010bc0d" in out and f"outcome text:\n{NEW}" in out and "next:" not in out, out)
check("get shows them", "outcome: done" in server.stackshot_get("a1"), server.stackshot_get("a1"))
refused("outcome on an already completed item", lambda: server._update("a1", status="completed", outcome="dropped"), "already completed",
        "to correct its close, reopen it (status=open with a next) and close it again")
snap("a1 done")

# ---- 3. update with status=completed: dropped, and an item on hold
out = server._update("a8", status="completed", outcome="dropped", reason="no longer needed after the redesign", outcome_text="- Not pursued; the redesign removed the need")
m = rd(8)["metadata"]
check("update status=completed closes a held item: hold and wake go", rd(8)["status"] == "completed" and "hold" not in m and "wake" not in m and m.get("outcome") == "dropped", m)

# ---- 4. superseded, by an open item and by a completed one
server.stackshot_complete("a2", outcome="superseded", reason="merged into a3", outcome_text="- Merged into a3, which carries the work", superseded_by="A3")
check("superseded by an open item: stored, normalised", rd(2)["metadata"].get("superseded_by") == "a3" and rd(2)["metadata"].get("outcome") == "superseded", rd(2)["metadata"])
server.stackshot_complete("a4", outcome="superseded", reason="reworded as a1", outcome_text="- Reworded as a1", superseded_by="a1")
check("superseded by a completed item is fine", rd(4)["metadata"].get("superseded_by") == "a1", rd(4)["metadata"])
snap("a2 a4 superseded")

# ---- 5. reopening
refused("reopening without a new next", lambda: server._update("a4", status="open"), "reopening a4 needs a new next")
out = server._update("a4", status="open", next="Oliver: pick it up again", needs=["decision"], ask="Decide: pick it up again now · Recommend: pick it up · Stakes: a day of delay · By: no date")
m = rd(4)["metadata"]
check("reopening drops outcome, outcome_text, reason and superseded_by and takes the new next",
      rd(4)["status"] == "open" and not any(k in m for k in ("outcome", "outcome_text", "reason", "superseded_by")) and rd(4)["description"] == DESC and m.get("next", "").split("\n")[0] == "Oliver: pick it up again", m)      # the server's step of his follows it on the list
snap("a4 reopened")
server.stackshot_complete("a4", outcome="dropped", reason="not needed after all", outcome_text="- Not needed after all")
check("a reopened item closes again", rd(4)["metadata"].get("outcome") == "dropped", rd(4)["metadata"])
snap("a4 dropped")

# ---- 6. the board
bd = ui_render.Board(f"{tmp}/store")
html = bd.completed_html()
line = lambda g: (re.search(rf'<li class="irow" id="task-a-{g}">.*?</li>', html, re.S) or [""])[0]      # the Closed page's Last 14 days list
check("completed list: the outcome as a tag", '<span class="tag t-done">Done</span>' in line(1) and '<span class="tag t-superseded">Superseded</span>' in line(2)
      and '<span class="tag t-dropped">Dropped</span>' in line(8), (line(1), line(2), line(8)))
check("completed list: an old completed item has no outcome tag, only the plain Closed", line(9) and "t-done" not in line(9) and "t-dropped" not in line(9) and "t-superseded" not in line(9) and '<span class="tag t-closed">Closed</span>' in line(9), line(9))
p2 = bd.item_html("a2")
check("item page: the state line says how it ended (item model, step 3): superseded, the replacing item linked, the reason",
      '<p class="istate"><span class="tag t-superseded">Superseded</span> ' in p2 and ' by <a href="/items/a3">a3</a>' in p2.split('<p class="istate">')[1].split("</p>")[0] and re.search(r'<p class="ireason">merged into (?:<a [^>]*>)?a3', p2) is not None,
      re.findall(r'<div class="istat">.*?</div>', p2))
sec2 = p2[p2.find('<div class="istat">'):p2.find('<details class="fold"')]       # the state line and the reason under it, up to the first section (there is no Where it stands any more)
check("item page: …and the latest change beside it does not say the close again: the reason only once (under the state line)",
      sec2.count("merged into") == 1 and "Where it stands" not in p2 and "iwhere" not in p2, sec2[:300])
check("item page: an old completed item with no outcome says so under its state line", '<p class="ireason">no outcome recorded</p>' in bd.item_html("a9"))
check("item page: a completed item shows its checklist as the record (a superseded close marked its open step dropped), and no ask", "<h2>Next</h2>" in p2 and p2.count('class="cl-open"') == 0 and p2.count('class="cl-dropped"') == 1 and 'class="iask"' not in p2, p2[:300])
p9 = bd.item_html("a9")
check("item page: an old completed item shows no next and no ask either (its fields still in the file)",
      "<h2>Next</h2>" not in p9 and 'class="iask"' not in p9 and rd(9)["metadata"].get("next"), p9[:300])
p3 = bd.item_html("a3")
check("item page: an open item keeps next and ask", "<h2>Next</h2>" in p3 and 'class="iask"' in p3)
hist = lambda g: [re.sub(r"<[^>]+>", "", h) for _ts, k, h in bd.item_events(bd.item(g))[0] if k in ("completed", "reopened")]
check("history: the completion event carries outcome and reason", hist("a1") == ["completed · done — PR #11 live at 010bc0d"], hist("a1"))
check("history: superseded names the replacing item", hist("a2") == ["completed · superseded by a3 — merged into a3"], hist("a2"))
check("history: close, reopen, close", hist("a4") == ["completed · dropped — not needed after all", "reopened · needs your call", "completed · superseded by a1 — reworded as a1"]
      or [h.split(" · ")[0] for h in hist("a4")] == ["completed", "reopened", "completed"], hist("a4"))
md = bd.markdown()
check("board.md: the completed list carries outcome and reason", "**a2** [home] item 2 · **superseded** by a3: merged into a3 · " in md and "**a9** [home] item 9 · " in md,
      [l for l in md.splitlines() if l.startswith("- <a id=\"task-a-")])
a9md = [l for l in md.splitlines() if l.startswith('- <a id="task-a-9">')]
check("board.md: a completed item with no session names no one: no backticked label, no stray store letter",
      len(a9md) == 1 and "`" not in a9md[0] and re.search(r"\*\*a9\*\* \[home\] item 9 · \d\d-\d\d \d\d:\d\d \S+$", a9md[0]), a9md)

# ---- 7. the descriptions say what a close carries
check("the complete and update descriptions carry the close form", all("outcome: done | dropped" in d and "clears next, ask and needs" in d
                                                                         for d in (server._COMPLETE_DESC, server._UPDATE_DESC)))
check("…inside the first 2048 characters, where the CLI cuts a tool description", all(0 < server._lead(d).find("drops outcome, outcome_text, reason and superseded_by") < 2048 - 40
                                                                                  for d in (server._COMPLETE_DESC, server._UPDATE_DESC)))

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": close scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
