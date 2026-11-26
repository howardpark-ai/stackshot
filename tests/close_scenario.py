"""Scenario test for closing an item: the close's form, what it writes, what it marks and what it keeps — fixture data, no live store, no network.
Four parts (formerly four suites), each with its own fixture and its own process, because each sets up a different instance config
(the owner's name, the transcripts, the marks switch) that the server modules read once, when they are imported, and cannot be reset in one process.

1. the close like an issue tracker closes an issue (formerly close, tests/run-suite close): a close (complete, or update with status=completed) is refused without outcome, reason or an
   outcome_text (the end state; the description stays as it was, part 3), each refusal naming what is missing and, for a pane with an older cached schema, that it closes through the portal meanwhile; an
   unknown outcome, a reason of more than one line, superseded without superseded_by, superseded_by with another outcome, naming
   the item itself or an item that does not exist are refused; outcome, reason and superseded_by outside a close are refused. The
   close clears next, ask and needs (and the hold and its wake), keeps due, and stores outcome, outcome_text, reason and superseded_by (an item
   superseded by a completed one is fine); get shows them. Reopening needs a new next and drops them. The board: the completed list
   shows the outcome as a tag; the item page shows outcome and reason at the top with superseded linking the other item, and no
   next or ask for any completed item, old ones too; the history's completion event carries outcome and reason; board.md's
   completed list carries them.

2. a close marks the item's open next steps (formerly close_marks; no closed item shows an open next step): before a close marked nothing: the steps still open stayed open on the closed item's checklist. Now:
  1  a close with outcome done marks the closer's own steps still open DONE, by the closer, at the time of the close; dropped and superseded mark them DROPPED; steps marked in the same call keep their marks
     (done=[…] / dropped=[…] with the close win for their steps); steps already marked are untouched
  2  the server's own closes (a done check, the owner's "drop" on a watcher ask) mark the open steps the same way (done / dropped), by the server
  3  reopening is unchanged: the marks stay, the steps an OLD close left open are dropped, the new next is the open step; a closed item's checklist still refuses a mark
  4  the text agents learn it from (complete and update) says it
  5  the backfill: the server's start-up pass (migsvc._close_marks_pass, once before it serves) marks the open steps of the items closed before (done for outcome done, dropped otherwise) by "stackshot (backfill)" at the item's close time,
     changes nothing else in the store, logs one line, and a second start does nothing; tools/close_marks_backfill.py is its read-only report (dry run, --json, no --apply, no --live)

3. a close that keeps the item's description (formerly close_keeps_description): a close used to tell the closing session to rewrite the description to the end state, so a closed item no longer said what it was about. Now the close's summary is its own
field, `metadata.outcome_text`, and the description stays as it was.

Covers: a close (complete, or update with status=completed) keeps the description and stores the outcome text; the reply and `get` show it; a description passed with a close
(an older caller) is stored as the outcome text and never over the description, both together are refused with the item untouched unless the description is the stored one (then it is ignored);
whose words are on a close are read from the outcome text and the reason, not the kept description; an outcome text is held to the bullet form and
length of a description but may say what was resolved; the description of a closed item can still be edited by an update, and the outcome text stays; reopening drops the outcome text
and leaves the description. The item page: a closed item with an outcome text shows an Outcome block under the state line and above Background, Background shows the original
description; an open item, and a closed one with no outcome text, show none. The repair (close_repair.py, migsvc._close_description_repair, tools/restore_close_descriptions.py)
puts back, from the store's git, the description held before the close for items closed in the window, moves the close's text into the outcome text, leaves an item closed
before the window, one that already has an outcome text (counted), one whose close did not rewrite the description, one edited after the close, one with no earlier revision and an open one, changes nothing but the
description and the outcome text, is idempotent, and `--live --apply` is refused unless the unit's ActiveState is inactive or failed (active, activating, deactivating, or systemd unable to say, are refused).

4. a session's close ticks only its own open steps (formerly complete_own_steps; the complete tool, and update with status=completed): before, a close marked every step still open, another session's included: a builder that closed its item after its own step silently ticked a step that another session still owed. Now:
  1  an item with an open step of the sender and an open step of another session: the complete tool and the update tool refuse the close, name the other session's step in plain words and say what to do; nothing is written (the item
     stays open, both steps stay open); the refusal holds for every outcome, and for the steps a legacy item stored with no writer (the creator's)
  2  the close goes through, ticking only the sender's own steps, when no other session's step is open (the other's step is already marked, or the call marks it itself: done=[n] / dropped=[n] with the close), and an owner's step
     in the list never holds it up (a close settles it, as before)
  3  the server's own closes (a done check, a watcher's drop, a script's close) are unchanged: they settle every open step
  4  the text agents learn it from (complete and update) says a close ticks only the sender's own steps

The file runs each part in a process of its own (`close_scenario.py --part <name>`; a part's own summary line is its former suite's) and adds up their checks: the final line is the sum.
Every check of the four former suites is kept, under the same name and condition.

    tests/run-suite close        → exit 0 / 1"""
import json, logging, os, pathlib, re, shutil, subprocess, sys, tempfile, time, stat
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
_made = []      # the scratch folder of the part this process runs, removed in the finally of _run_part (and by _scratch at exit, whatever ends the process)


def _fixture(prefix, dirs, transcripts=False, marks_off=False, owner=None):
    """The part's scratch folder, its stackshot.toml (a copy of the base instance with every path in the folder), RULES.md, the environment the server reads and the folders in `dirs`; returns (tmp, T).
    transcripts: the transcripts roots point into the folder; marks_off: require_marks = false; owner: a named owner (instead of "the owner")."""
    tmp = _scratch.mkdtemp(prefix=prefix); T = pathlib.Path(tmp); _made.append(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
    if owner is not None:
        toml = _instance.set_person(toml, owner)      # a named owner, so `<owner> to …` is a form the model reads (with no [instance] owner the name is not one of the owner's names)
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
    if transcripts:
        toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
    if marks_off:
        toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    for d in dirs: (T / d).mkdir(parents=True)
    return tmp, T


# ================================================================ part 1: the close (formerly close_scenario)
def part_close():
    tmp, T = _fixture("closetest-", ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"))
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
    from stackshot.service import update as _update_svc
    from fastmcp.exceptions import ToolError
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    from stackshot.web.tools import anchors as _wt_anchors
    from stackshot.web.tools import route as _wt_route
    from stackshot.web.tools import complete as _wt_complete
    from stackshot.web.tools import get as _wt_get
    from stackshot.web.tools import text as _wt_text
    from stackshot.web.tools import update as _wt_update
    from stackshot.web.ui import render as ui_render
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    _web_page_debts._owing_note = lambda debtor: ""        # the page rule is not under test here
    def refused(name, f, *want):
        try:
            out = f(); check(name, False, out)
        except ToolError as e:
            check(name, all(w in str(e) for w in want), str(e))
    NEW = "- The thing works and is in use"

    # ---- 1. refusals
    refused("an old cached schema (complete with the id alone): names what is missing and the portal path, never a relaunch",
            lambda: _wt_complete.stackshot_complete("a1"), "closing a1 needs outcome, reason, outcome_text", "a relaunch does not",
            "portal_codemode_execute with codemode.stackshot_complete({item_id, outcome, reason, outcome_text, superseded_by})")
    refused("update status=completed alone: the same", lambda: _update_svc._update("a1", status="completed"), "closing a1 needs outcome, reason, outcome_text", "codemode.stackshot_complete")
    refused("no reason", lambda: _wt_complete.stackshot_complete("a1", outcome="done", outcome_text=NEW), "needs reason")
    refused("no outcome_text", lambda: _wt_complete.stackshot_complete("a1", outcome="done", reason="it works"), "needs outcome_text")
    refused("no outcome", lambda: _wt_complete.stackshot_complete("a1", reason="it works", outcome_text=NEW), "needs outcome")
    refused("an unknown outcome", lambda: _wt_complete.stackshot_complete("a1", outcome="finished", reason="it works", outcome_text=NEW), "outcome must be one of done | dropped | superseded")
    refused("a reason of two lines", lambda: _wt_complete.stackshot_complete("a1", outcome="done", reason="it works\nand more", outcome_text=NEW), "reason is one line")
    refused("an outcome_text that is not bullets", lambda: _wt_complete.stackshot_complete("a1", outcome="done", reason="it works", outcome_text="It works now."), "outcome_text line is not a `- ` bullet")
    refused("superseded without superseded_by", lambda: _wt_complete.stackshot_complete("a1", outcome="superseded", reason="moved", outcome_text=NEW), "needs superseded_by")
    refused("superseded_by with outcome done", lambda: _wt_complete.stackshot_complete("a1", outcome="done", reason="it works", outcome_text=NEW, superseded_by="a2"), "superseded_by goes with outcome=superseded")
    refused("superseded by itself", lambda: _wt_complete.stackshot_complete("a1", outcome="superseded", reason="moved", outcome_text=NEW, superseded_by="A1"), "cannot be superseded by itself")
    refused("superseded by an item that does not exist", lambda: _wt_complete.stackshot_complete("a1", outcome="superseded", reason="moved", outcome_text=NEW, superseded_by="a99"), "a99, which does not exist")
    refused("outcome on an open item without a close", lambda: _update_svc._update("a1", outcome="done"), "go with a close")
    refused("outcome_text on an open item without a close", lambda: _update_svc._update("a1", outcome_text=NEW), "go with a close")
    refused("reason outside a close", lambda: _update_svc._update("a1", next="x", reason="why"), "go with a close")
    check("nothing above changed the item", rd(1)["status"] == "open" and rd(1)["metadata"]["next"] == "do the thing" and rd(1)["description"] == DESC, rd(1))

    # ---- 2. a close: done, through complete
    out = _wt_complete.stackshot_complete("a1", outcome="Done", reason="PR #11 live at 010bc0d", outcome_text=NEW)
    m = rd(1)["metadata"]
    check("complete closes it, keeps the description and stores the outcome text", rd(1)["status"] == "completed" and rd(1)["description"] == DESC and m.get("outcome_text") == NEW, rd(1))
    check("the close clears next, ask and needs", not any(k in m for k in ("next", "ask", "needs")), m)
    check("due stays as a record", m.get("due") == "2026-10-20", m)
    check("outcome (lower-cased) and reason are stored, no superseded_by", m.get("outcome") == "done" and m.get("reason") == "PR #11 live at 010bc0d" and "superseded_by" not in m, m)
    check("the reply shows outcome, reason and outcome_text", "outcome: done" in out and "reason: PR #11 live at 010bc0d" in out and f"outcome text:\n{NEW}" in out and "next:" not in out, out)
    check("get shows them", "outcome: done" in _wt_get.stackshot_get("a1"), _wt_get.stackshot_get("a1"))
    refused("outcome on an already completed item", lambda: _update_svc._update("a1", status="completed", outcome="dropped"), "already completed",
            "to correct its close, reopen it (status=open with a next) and close it again")
    snap("a1 done")

    # ---- 3. update with status=completed: dropped, and an item on hold
    out = _update_svc._update("a8", status="completed", outcome="dropped", reason="no longer needed after the redesign", outcome_text="- Not pursued; the redesign removed the need")
    m = rd(8)["metadata"]
    check("update status=completed closes a held item: hold and wake go", rd(8)["status"] == "completed" and "hold" not in m and "wake" not in m and m.get("outcome") == "dropped", m)

    # ---- 4. superseded, by an open item and by a completed one
    _wt_complete.stackshot_complete("a2", outcome="superseded", reason="merged into a3", outcome_text="- Merged into a3, which carries the work", superseded_by="A3")
    check("superseded by an open item: stored, normalised", rd(2)["metadata"].get("superseded_by") == "a3" and rd(2)["metadata"].get("outcome") == "superseded", rd(2)["metadata"])
    AN4 = "https://github.com/o/r/pull/44"; AN2 = "https://github.com/o/r/pull/45"
    (T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": AN4, "items": ["a4"], "added": 1.0, "by": "t"}, {"url": AN2, "items": ["a3"], "added": 1.0, "by": "t"}]}))
    out4 = _wt_complete.stackshot_complete("a4", outcome="superseded", reason="reworded as a1", outcome_text="- Reworded as a1", superseded_by="a1")
    check("superseded by a completed item is fine", rd(4)["metadata"].get("superseded_by") == "a1", rd(4)["metadata"])
    left4 = json.loads((T / "store/anchors.json").read_text())
    check("a close ends the anchors scoped to it only, and its reply lists them with the call that puts one back (the anchor of an open item stays)",
          [e["url"] for e in left4.get("projects/alpha", [])] == [AN2] and AN4 in out4 and f'anchors(project="projects/alpha", add=["{AN4}"])' in out4, (left4, out4))
    snap("a2 a4 superseded")

    # ---- 5. reopening
    refused("reopening without a new next", lambda: _update_svc._update("a4", status="open"), "reopening a4 needs a new next")
    out = _update_svc._update("a4", status="open", next="Oliver: pick it up again", needs=["decision"], ask="Decide: pick it up again now · Recommend: yes · Stakes: a day of delay · By: no date")
    m = rd(4)["metadata"]
    check("reopening drops outcome, outcome_text, reason and superseded_by and takes the new next",
          rd(4)["status"] == "open" and not any(k in m for k in ("outcome", "outcome_text", "reason", "superseded_by")) and rd(4)["description"] == DESC and m.get("next", "").split("\n")[0] == "Oliver: pick it up again", m)      # the server's step of his follows it on the list
    check("a reopening's reply carries one line naming the call that puts the anchor its close ended back, scoped to the item again",
          f'anchors(project="projects/alpha", add=["{AN4}"], items=["{__import__("stackshot.github.ghsync", fromlist=["x"]).shown("a4")}"])' in out and out.count("anchors that ended when") == 1, out)
    snap("a4 reopened")
    _wt_complete.stackshot_complete("a4", outcome="dropped", reason="not needed after all", outcome_text="- Not needed after all")
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
    check("item page: …the close is not said twice: the reason shows only once (under the state line)",
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
                                                                             for d in (_wt_complete._COMPLETE_DESC, _wt_update._UPDATE_DESC)))
    check("…inside the first 2048 characters, where the CLI cuts a tool description", all(0 < _wt_text._lead(d).find("drops outcome, outcome_text, reason and superseded_by") < 2048 - 40
                                                                                      for d in (_wt_complete._COMPLETE_DESC, _wt_update._UPDATE_DESC)))

    print(("ok" if not fails else "FAILED") + f": close scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
    sys.exit(1 if fails else 0)

# ================================================================ part 2: a close marks the open steps (formerly close_marks_scenario)
def part_marks():
    BID_A = 9183
    BID_B = 9184
    BID_C = 9185
    BID_D = 9186
    BID_E = 9187
    BID_F = 9188
    tmp, T = _fixture("closemarks-", ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"), transcripts=True, marks_off=True)      # removed (and flock-held while the suite runs) by _scratch, pass or fail
    NAMES = ("home-owner", "home-stew", "team-back", "home-front")
    U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
    now0 = time.time(); DAY = 86400.0
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
    def proj(session, agents, back):
        return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": proj("home-stew", {"home-front": "the front", "team-back": "the back"}, {"team-back": "the back"})}}))
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
    (T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
    DESC = "- A thing\n- It lives here\n- Done when done"
    NEW = "- The thing works now\n- It lives here\n- Finished when it ships"
    L3 = "home-front: build it\nhome-front: test it\nteam-back: tell the keeper"
    def item(i, status="open", letter="g", close_at=None, **meta):
        base = {"owner": U["home-front"], "project": "projects/alpha", "next": L3}
        base.update(meta); base = {k: v for k, v in base.items() if v is not None}
        su = close_at or now0 - 10 * DAY
        (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                                  "updated": su, "state_updated": su, "confirmed": su, "metadata": base}))
    def rd(i, letter="g"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
    def raw(i, letter="g"): return (T / f"store/{letter}/{i}.json").read_text()
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1200]}" if got is not None else ""))
    def sts(i): return [(x["status"], x.get("by") or "") for x in rd(i)["metadata"].get("steps") or []]
    def kinds(i): return [k for k, _ in sts(i)]
    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import steps as S
    from stackshot.web.tools import get as _get_tool
    from stackshot.service import migrations as migsvc
    from stackshot.service import wait_gates as wait_gates_svc
    from stackshot.service import update as _update_svc
    from stackshot.core import instance as _core_instance
    from fastmcp.exceptions import ToolError
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    from stackshot.service import checks as checks_svc
    from stackshot.service import telling
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    _web_page_debts._owing_note = lambda debtor: ""
    told: list = []
    telling.tell_woken = lambda gid, owner, note, tag="wake", result=None: told.append((gid, owner, note, tag))
    telling.tell_check_closed = lambda gid, item, label: []
    def close(i, outcome="done", sup="", **kw):
        return _update_svc._update(f"board#{i}", status="completed", outcome=outcome, reason="it ended", description=NEW, superseded_by=sup, sender="home-front", **kw)
    def refused(name, f, *want):
        try:
            out = f(); check(name, False, out)
        except ToolError as e:
            check(name, all(w in str(e) for w in want), str(e))

    # ================================================================ 1. a close marks the open steps
    for i in (1, 2, 3, 4, 5, 6, 7, 8): item(i)
    t0 = time.time()
    close(1, "done")
    check("close done: next is gone, every step is done, by the closer, at the time of the close", "next" not in rd(1)["metadata"] and kinds(1) == ["done"] * 3 and {b for _, b in sts(1)} == {"home-front"}
          and all(t0 - 1 <= x["at"] <= time.time() + 1 for x in rd(1)["metadata"]["steps"]), rd(1)["metadata"])
    check("close done: no step of the closed item is open (view, as get and the page read it)", all(x["status"] != S.OPEN for x in S.view(rd(1)["metadata"], closed=True)), None)
    close(2, "dropped")
    check("close dropped: every step is dropped, by the closer", kinds(2) == ["dropped"] * 3 and {b for _, b in sts(2)} == {"home-front"}, sts(2))
    close(3, "superseded", sup="board#1")
    check("close superseded: every step is dropped, by the closer", kinds(3) == ["dropped"] * 3 and {b for _, b in sts(3)} == {"home-front"}, sts(3))
    _update_svc._update("board#4", status="completed", outcome="dropped", reason="it ended", description=NEW, sender="home-front", done=[1])
    check("a mark passed with the close wins for its step: done=[1] with outcome dropped → done, dropped, dropped", kinds(4) == ["done", "dropped", "dropped"], sts(4))
    _update_svc._update("board#5", status="completed", outcome="done", reason="it ended", description=NEW, sender="home-front", dropped=["home-front: test it"])
    check("a mark passed with the close wins for its step: dropped=[text] with outcome done → done, dropped, done", kinds(5) == ["done", "dropped", "done"], sts(5))
    _update_svc._update("board#6", sender="home-front", done=[1])                       # one step done earlier, by update: the close leaves it as it is, marks the rest
    at6 = rd(6)["metadata"]["steps"][0]["at"]
    close(6, "dropped")
    check("a step marked before the close is untouched (by, at, status); the others follow the outcome", kinds(6) == ["done", "dropped", "dropped"] and rd(6)["metadata"]["steps"][0]["at"] == at6, rd(6)["metadata"]["steps"])
    g1 = _get_tool._fmt({**rd(1), "gid": "g1"})
    check("get on the closed item lists a checklist with no open step", "checklist:" in g1 and "[open" not in g1 and "[done · home-front" in g1, g1[-400:])
    item(8, next="home-front: one", steps=[{"text": "home-front: gone", "status": "open"}, {"text": "home-front: one", "status": "open"}])
    close(8, "done")
    check("a stored open step whose line already left next reads dropped (view), the one in next follows the outcome: dropped, done", kinds(8) == ["dropped", "done"], sts(8))

    item(9); item(12)
    mb9, mb12 = rd(9)["metadata"], rd(12)["metadata"]
    _update_svc._update("board#9", status="completed", outcome="done", reason="it ended", description=NEW, sender="home-front", dropped=[2])
    close(12, "done")
    check("History and the mirror's comment (steps.changes): the mark a close puts by itself is no event, a step marked the other way in the same call is",
          S.changes(mb12, rd(12)["metadata"], True) == [] and S.changes(mb9, rd(9)["metadata"], True) == [("dropped", "home-front: test it")], (S.changes(mb12, rd(12)["metadata"], True), S.changes(mb9, rd(9)["metadata"], True)))

    # ================================================================ 2. the server's own closes
    item(10); item(11)
    checks_svc.check_close("g10", rd(10), "a done check", time.time())
    check("a done check's close marks the open steps done, by the server", kinds(10) == ["done"] * 3 and {b for _, b in sts(10)} == {_core_instance.NAME} and rd(10)["metadata"]["outcome"] == "done", sts(10))
    it11 = rd(11); wait_gates_svc._watch_close(it11, "dropped on his answer", time.time())
    check("a watcher ask's drop marks the open steps dropped, by the server", [x["status"] for x in it11["metadata"]["steps"]] == ["dropped"] * 3 and it11["metadata"]["outcome"] == "dropped", it11["metadata"])

    # ================================================================ 3. reopening and the closed item's checklist
    refused("a mark on a closed item is refused: reopen it first", lambda: _update_svc._update("board#1", sender="home-front", done=[1]), "closed", "reopen")
    check("…and the refusal wrote nothing", kinds(1) == ["done"] * 3, sts(1))
    _update_svc._update("board#1", status="open", next="home-front: a fresh start", sender="home-front")
    check("reopening: the marks the close made stay, the new next is the one open step", [x["status"] for x in S.view(rd(1)["metadata"])] == ["done"] * 3 + ["open"], rd(1)["metadata"])
    item(9187, status="completed", outcome="dropped", reason="old", steps=[{"text": "home-front: old one", "status": "open"}, {"text": "home-front: old two", "status": "done", "by": "home-front", "at": now0 - 100}], next=None)
    _update_svc._update(f"board#{BID_E}", status="open", next="home-front: back again", sender="home-front")
    check("reopening an OLD close (steps left open) is unchanged: the steps left open are dropped, the new next is the open step",
          [x["status"] for x in S.view(rd(9187)["metadata"])] == ["dropped", "done", "open"], rd(9187)["metadata"])

    # ================================================================ 4. the text
    desc_ = {t.name: t.description for t in __import__("asyncio").run(server.mcp.list_tools())}
    check("text: complete and update say a close ticks only the closer's own open steps, done or dropped by the outcome", all("ticks only the steps that are still open and are yours" in desc_[n] and "dropped" in desc_[n] for n in ("complete", "update"))
          and "marks nothing" not in desc_["update"] + desc_["complete"] + desc_["get"], [n for n in ("complete", "update") if "ticks only the steps that are still open and are yours" not in desc_[n]])

    # ================================================================ 5. the backfill tool
    CLOSE = now0 - 3 * DAY
    OLD = lambda *t: [{"text": x, "status": "open"} for x in t]
    item(9186, status="completed", close_at=CLOSE, outcome="done", reason="x", next=None, steps=[{"text": "home-front: shipped", "status": "done", "by": "home-front", "at": CLOSE - 60}, *OLD("home-front: A left open", "team-back: B left open")])
    item(9183, status="completed", close_at=CLOSE, outcome="dropped", reason="x", next=None, steps=OLD("home-front: C left open"))
    item(9188, status="completed", close_at=CLOSE, outcome="superseded", superseded_by=f"board#{BID_D}", reason="x", next=None, steps=OLD("home-front: D left open"))
    item(9184, status="completed", close_at=CLOSE, next=None, steps=OLD("home-front: E left open, an old close with no outcome"))
    item(34, status="completed", close_at=CLOSE, outcome="done", reason="x", next=None, steps=[{"text": "home-front: all marked", "status": "done", "by": "home-front", "at": CLOSE}])
    item(35, status="completed", close_at=CLOSE, outcome="done", reason="x", next=None)                      # no steps at all
    item(36, close_at=CLOSE, next="home-front: an open item", steps=OLD("home-front: an open item"))               # open: not the tool's
    def snapshot(): return {p.name: p.read_text() for p in (T / "store/g").glob("*.json")}
    before = snapshot()
    tool = os.path.join(STACK, "stackshot/tools/close_marks_backfill.py"); cfg = f"{tmp}/stackshot.toml"
    def run(*a):
        return subprocess.run([sys.executable, tool, *a], capture_output=True, text=True, env={**os.environ}, timeout=300)
    # the earlier sections left their closed items in this store: the tool lists only what still has an open step, which is the fixtures above
    d = run("--config", cfg)
    lines = [l for l in d.stdout.splitlines() if l.strip()]
    byitem = {l.split(" ")[0]: l for l in lines}
    check("dry run: exit 0, one line for each closed item with an open step and no other", d.returncode == 0 and sorted(byitem) == sorted([f"board#{BID_D}", f"board#{BID_A}", f"board#{BID_F}", f"board#{BID_B}"]), (d.returncode, d.stdout, d.stderr[-400:]))
    check("dry run: each line has the outcome, the mark and the steps", "(done)" in byitem.get(f"board#{BID_D}", "") and "would mark 2 steps done" in byitem[f"board#{BID_D}"] and "2. home-front: A left open" in byitem[f"board#{BID_D}"] and "3. team-back: B left open" in byitem[f"board#{BID_D}"]
          and "(dropped)" in byitem.get(f"board#{BID_A}", "") and "would mark 1 step dropped" in byitem[f"board#{BID_A}"] and "(superseded)" in byitem.get(f"board#{BID_F}", "") and "dropped" in byitem[f"board#{BID_F}"]
          and "(no outcome)" in byitem.get(f"board#{BID_B}", "") and "dropped" in byitem[f"board#{BID_B}"], d.stdout)
    check("dry run: writes nothing", before == snapshot(), None)
    dj = run("--config", cfg, "--json")
    rows = json.loads(dj.stdout) if dj.returncode == 0 else []
    check("dry run: --json is the rows", [r["item"] for r in rows] == [f"board#{BID_A}", f"board#{BID_B}", f"board#{BID_D}", f"board#{BID_F}"] and rows[2]["status"] == "done" and rows[0]["status"] == "dropped"
          and rows[2]["steps"] == [{"position": 2, "text": "home-front: A left open"}, {"position": 3, "text": "team-back: B left open"}], dj.stdout[:600])
    check("the tool has no --apply and no --live any more: the server is the only writer", run("--apply").returncode == 2 and run("--live").returncode == 2 and before == snapshot(), None)
    nc = run("--config", f"{tmp}/no-such.toml")
    check("a config that is not there is an error", nc.returncode == 2 and "not a file" in nc.stderr, (nc.returncode, nc.stderr))
    # the server's start-up pass (__main__ runs it once before it serves): in-process here, its log line on stderr
    import io, contextlib
    def start_pass():
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            got = migsvc._close_marks_pass()
        return got, buf.getvalue()
    got, log = start_pass()
    check("start-up pass: marks the four items, and logs one line with the counts", [r["item"] for r in got] == [f"board#{BID_A}", f"board#{BID_B}", f"board#{BID_D}", f"board#{BID_F}"] and sum(1 for l in log.splitlines() if "migrate: close marks:" in l) == 1
          and "4 closed item(s)" in log and "5 open step(s)" in log and "2 done, 3 dropped" in log, (got, log[-600:]))
    BY = "stackshot (backfill)"
    s9032, s9020, s9037, s9030 = (rd(i)["metadata"]["steps"] for i in (9186, 9183, 9188, 9184))
    check("start-up pass: outcome done → the open steps done, the done one untouched; by the backfill, at the item's close time",
          [x["status"] for x in s9032] == ["done", "done", "done"] and s9032[0]["by"] == "home-front" and s9032[0]["at"] == CLOSE - 60 and all(x["by"] == BY and x["at"] == CLOSE for x in s9032[1:]), s9032)
    check("start-up pass: outcome dropped, superseded and none → dropped", [x["status"] for x in s9020 + s9037 + s9030] == ["dropped"] * 3 and all(x["by"] == BY and x["at"] == CLOSE for x in s9020 + s9037 + s9030), (s9020, s9037, s9030))
    def no_steps(d_):
        d_ = json.loads(json.dumps(d_)); d_["metadata"].pop("steps", None); d_.pop("activity", None); return d_      # the item's activity clock (activity.py) is compared apart, below
    check("start-up pass: nothing else in the file changed (same fields, same clocks)", all(no_steps(rd(i)) == no_steps(json.loads(before[f"{i}.json"])) for i in (9186, 9183, 9188, 9184)),
          [(i, no_steps(rd(i)), no_steps(json.loads(before[f"{i}.json"]))) for i in (9186, 9183, 9188, 9184) if no_steps(rd(i)) != no_steps(json.loads(before[f"{i}.json"]))])
    check("start-up pass: the activity clock an item from before the field gains at its first save is its last update, not the pass's time",
          all(rd(i).get("activity") == max(json.loads(before[f"{i}.json"])["updated"], json.loads(before[f"{i}.json"])["state_updated"]) for i in (9186, 9183, 9188, 9184)), [(i, rd(i).get("activity")) for i in (9186, 9183, 9188, 9184)])
    check("start-up pass: the items with no open step and the open item are as they were", all(raw(i) == before[f"{i}.json"] for i in (34, 35, 36)), None)
    check("start-up pass: nothing else in the store changed (every other file byte for byte, no file added)", all(snapshot()[n] == before[n] for n in before if n not in ("9186.json", "9183.json", "9188.json", "9184.json")) and set(snapshot()) == set(before), None)
    after_apply = snapshot()
    again = run("--config", cfg)
    check("a dry run after it finds nothing", again.returncode == 0 and not again.stdout.strip() and "0 closed items" in again.stderr, (again.stdout, again.stderr))
    got2, log2 = start_pass()
    check("a second start is idempotent: it marks nothing, writes no file and logs nothing", got2 == [] and "close marks" not in log2 and after_apply == snapshot(), (got2, log2[-300:]))
    item(9185, status="completed", close_at=CLOSE, outcome="done", reason="x", next=None, steps=OLD("home-front: F left open, found by a later start"))
    got3, _ = start_pass()
    check("a later start marks an item closed meanwhile with an open step, and only it", [r["item"] for r in got3] == [f"board#{BID_C}"] and kinds(9185) == ["done"], got3)
    g9186 = _get_tool._fmt({**rd(9186), "gid": "g9186"})
    check("get on a backfilled item shows no open step", "checklist:" in g9186 and "[open" not in g9186, g9186[-400:])

    print(("ok" if not fails else "FAILED") + f": close marks scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)


# ================================================================ part 3: a close keeps the description (formerly close_keeps_description_scenario)
def part_keeps_description():
    tmp, T = _fixture("closekeeptest-", ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "bin-active", "bin-inactive", "bin-unsure"))
    OWNER = "00000000-0000-4000-8000-000000000001"
    now = time.time(); DAY = 86400.0
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                    "session": "home-here", "status": "active", "board": [], "board_open": 0}}}))
    DESC = "- Move the nightly export to the new bucket\n- Owner: home-here\n- Finished when the old bucket is empty"
    NEW = "- The export runs from the new bucket\n- The old bucket is empty"
    LIVE = {"next": "do the thing", "needs": "decision", "due": "2026-10-20",
            "ask": "Decide: whether to ship · Recommend: ship · Stakes: none either way · By: no date"}
    def put(i, status="open", desc=DESC, at=None, **meta):
        at = now - 3600 if at is None else at
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": desc, "status": status,
                                                           "updated": at, "state_updated": at, "confirmed": at,
                                                           "metadata": {"owner": OWNER, "project": "projects/alpha", **meta}}))
    for i in range(1, 9):
        put(i, **LIVE)
    (T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
    git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
    git("init", "-q")
    def snap(msg): git("add", "-A"); git("commit", "-q", "--allow-empty", "-m", msg)
    # the repair's history: each item is written open and committed, then closed as the old close did (the description rewritten to the end state) and committed
    OLD_END = "- The export runs from the new bucket (rewritten at the close)"
    for i in (11, 12, 13, 14, 15, 16, 21, 22): put(i, **LIVE)
    put(18, **LIVE); put(19, **LIVE)
    snap("fixture: everything open")
    put(11, "completed", OLD_END, outcome="done", reason="shipped")                                  # closed an hour ago, the description rewritten
    put(12, "completed", OLD_END, at=now - 20 * DAY, outcome="done", reason="shipped long ago")      # closed before the window
    put(13, "completed", DESC, outcome="done", reason="shipped, description untouched")             # a close that did not rewrite it
    put(14, "completed", OLD_END, outcome="done", reason="shipped, edited afterwards")
    put(15, "completed", OLD_END, outcome="dropped", reason="not needed", outcome_text="- Not needed after the move")      # already has an outcome text
    put(21, "completed", OLD_END, outcome="done", reason="shipped (tool run 1)")
    put(22, "completed", OLD_END, outcome="superseded", reason="replaced by 21", superseded_by="a21")
    snap("fixture: closed with the description rewritten")
    EDITED = "- Move the nightly export to the new bucket (clarified by hand after the close)"
    put(14, "completed", EDITED, outcome="done", reason="shipped, edited afterwards")
    snap("fixture: a14 edited after the close")
    (T / "store/a/17.json").write_text(json.dumps({"id": "17", "subject": "[home] item 17", "description": OLD_END, "status": "completed", "updated": now - 3600, "state_updated": now - 3600,
                                                   "confirmed": now - 3600, "metadata": {"owner": OWNER, "project": "projects/alpha", "outcome": "done", "reason": "born closed"}}))
    # the item written just above is never committed open: it has no revision before its close (the file on disk is its only one)

    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
    def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
    def mt(i): return rd(i)["metadata"]

    from stackshot.web import server
    from stackshot.service import migrations as migsvc
    from stackshot.service import update as _update_svc
    from fastmcp.exceptions import ToolError
    from stackshot.core import instance as _core_instance
    from stackshot.model import said as _said
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    from stackshot.web.tools import anchors as _wt_anchors
    from stackshot.web.tools import route as _wt_route
    from stackshot.web.tools import complete as _wt_complete
    from stackshot.web.tools import get as _wt_get
    from stackshot.web.ui import render as r2
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    _web_page_debts._owing_note = lambda debtor: ""        # the page rule is not under test here
    def refused(name, f, *want):
        try:
            out = f(); check(name, False, out)
        except ToolError as e:
            check(name, all(w in str(e) for w in want), str(e))

    # ---- 1. a close keeps the description and stores the outcome text
    out = _wt_complete.stackshot_complete("a1", outcome="done", reason="the export runs from the new bucket", outcome_text=NEW)
    check("complete: the description is exactly what it was, the outcome text is stored", rd(1)["status"] == "completed" and rd(1)["description"] == DESC and mt(1).get("outcome_text") == NEW, rd(1))
    check("complete: outcome and reason are stored as before", mt(1).get("outcome") == "done" and mt(1).get("reason") == "the export runs from the new bucket", mt(1))
    check("complete: the reply and get show the outcome text under a label, and the description as it was", f"outcome text:\n{NEW}" in out and DESC in out and f"outcome text:\n{NEW}" in _wt_get.stackshot_get("a1"), out)
    _update_svc._update("a2", status="completed", outcome="dropped", reason="not needed after the move", outcome_text="- Not needed: the move made it moot")
    check("update status=completed with outcome_text: the same", rd(2)["description"] == DESC and mt(2).get("outcome_text") == "- Not needed: the move made it moot" and mt(2).get("outcome") == "dropped", rd(2))
    refused("a close with no outcome text is refused and names it", lambda: _wt_complete.stackshot_complete("a3", outcome="done", reason="it works"), "needs outcome_text")
    refused("an outcome text that is not bullets is refused, named outcome_text", lambda: _wt_complete.stackshot_complete("a3", outcome="done", reason="it works", outcome_text="It works now."), "outcome_text line is not a `- ` bullet")
    refused("an outcome text over the line limit that cannot be split (one unbroken token) is refused, named outcome_text", lambda: _wt_complete.stackshot_complete("a3", outcome="done", reason="it works", outcome_text="- " + "long" * 40), "outcome_text bullet is")
    refused("outcome_text outside a close is refused", lambda: _update_svc._update("a3", outcome_text=NEW), "go with a close")
    check("…and nothing above touched the open item", rd(3)["status"] == "open" and rd(3)["description"] == DESC and "outcome_text" not in mt(3), rd(3))
    _wt_complete.stackshot_complete("a3", outcome="done", reason="it works", outcome_text="- Resolved: the export moved\n- Done: the old bucket is empty")
    check("an outcome text may say what was resolved and done (the forbidden tokens guard live descriptions, not an end state)", mt(3).get("outcome_text", "").startswith("- Resolved:") and rd(3)["description"] == DESC, mt(3))

    # ---- 2. a description passed with a close (an older caller) is the outcome text
    LEGACY = "- The export runs from the new bucket\n- Written by a caller that predates outcome_text"
    _wt_complete.stackshot_complete("a4", outcome="done", reason="finished", description=LEGACY)
    check("complete with a description: stored as the outcome text, the description is not replaced", rd(4)["status"] == "completed" and rd(4)["description"] == DESC and mt(4).get("outcome_text") == LEGACY, rd(4))
    _update_svc._update("a5", status="completed", outcome="done", reason="finished", description=LEGACY)
    check("update status=completed with a description: the same", rd(5)["description"] == DESC and mt(5).get("outcome_text") == LEGACY, rd(5))
    refused("a description and an outcome text together are refused", lambda: _wt_complete.stackshot_complete("a6", outcome="done", reason="finished", description=LEGACY, outcome_text=NEW), "passes both")
    check("…the item is untouched", rd(6)["status"] == "open" and rd(6)["description"] == DESC and "outcome_text" not in mt(6), rd(6))
    _wt_complete.stackshot_complete("a6", outcome="done", reason="finished", description=f"  {DESC}\n", outcome_text=NEW)
    check("a description passed with an outcome text that equals the stored one (after strip) is ignored: the close goes through with the outcome text",
          rd(6)["status"] == "completed" and rd(6)["description"] == DESC and mt(6).get("outcome_text") == NEW, rd(6))
    refused("a legacy description that is not bullets is refused as the outcome text", lambda: _wt_complete.stackshot_complete("a8", outcome="done", reason="finished", description="It is finished."), "outcome_text line is not a `- ` bullet")

    # ---- 2b. whose words: a close is judged on what it wrote (the outcome text and the reason), not on the background the description keeps
    QUOTE = f'- {_core_instance.OWNER}, Wed Oct 28th: "ship it"'
    bg_quote = {"status": "completed", "description": QUOTE, "metadata": {"outcome_text": NEW, "reason": "shipped"}}
    check("_owner_words on a close: the owner quoted only in the kept description does not count (no For you row for every close)", _said._owner_words(bg_quote) == "", _said._owner_words(bg_quote))
    check("…quoted in the outcome text it counts", _said._owner_words({**bg_quote, "description": DESC, "metadata": {"outcome_text": QUOTE, "reason": "shipped"}}) == "quoted in the text")
    check("…quoted in the reason it counts", _said._owner_words({**bg_quote, "description": DESC, "metadata": {"outcome_text": NEW, "reason": f'{_core_instance.OWNER}, Wed Oct 28th: "ship it"'}}) == "quoted in the text")
    check("an open item is still judged on its description", _said._owner_words({"status": "open", "description": QUOTE, "metadata": {}}) == "quoted in the text")
    check("a closed item with no outcome text (stored before this change) is still judged on its description", _said._owner_words({"status": "completed", "description": QUOTE, "metadata": {"reason": "shipped"}}) == "quoted in the text")

    # ---- 3. the description of a closed item can still be edited; the outcome text stays; reopening drops it
    EDIT = "- Move the nightly export to the new bucket\n- Owner: home-here\n- The old bucket is deleted since"
    _update_svc._update("a1", description=EDIT)
    check("update on a closed item still edits its description, and leaves the outcome text", rd(1)["description"] == EDIT and mt(1).get("outcome_text") == NEW and rd(1)["status"] == "completed", rd(1))
    _update_svc._update("a2", status="open", next="home-here: pick it up again")
    check("reopening drops outcome, outcome_text and reason and leaves the description", rd(2)["status"] == "open" and rd(2)["description"] == DESC
          and not any(k in mt(2) for k in ("outcome", "outcome_text", "reason", "superseded_by")), rd(2))

    # ---- 4. the item page: an Outcome block under the state line and above Background
    bd = r2.Board(f"{tmp}/store")
    p1 = bd.item_html("a1")
    i_stat, i_out, i_bg = p1.find('<div class="istat">'), p1.find('class="fold ioutcome"'), p1.find('id="description"')
    check("closed item with an outcome text: an Outcome block, after the state line and before Background", 0 < i_stat < i_out < i_bg, (i_stat, i_out, i_bg))
    blk = p1[i_out:p1.find("</details>", i_out)]
    check("…it holds the outcome text and a heading Outcome", "<h2>Outcome</h2>" in blk and "The export runs from the new bucket" in blk and "The old bucket is empty" in blk, blk)
    bg = p1[i_bg:p1.find("</details>", i_bg)]
    check("…Background shows the description (as edited above), not the outcome text", "Move the nightly export to the new bucket" in bg and "deleted since" in bg and "The export runs from the new bucket" not in bg, bg)
    p4 = bd.item_html("a4")
    check("a close with a legacy description: Background shows the original description, Outcome the legacy text",
          "Move the nightly export" in p4[p4.find('id="description"'):] and "Written by a caller that predates" in p4[p4.find('class="fold ioutcome"'):p4.find('id="description"')], p4[:200])
    p7 = bd.item_html("a7")
    check("an open item: no Outcome block", 'class="fold ioutcome"' not in p7 and 'id="description"' in p7 and ">Outcome<" not in p7)
    p13 = bd.item_html("a13")
    check("a closed item with no outcome text: no Outcome block, Background as before", 'class="fold ioutcome"' not in p13 and "Finished when the old bucket is empty" in p13 and ">Outcome<" not in p13)
    check("the Outcome block is the first section under the state line (before Next and History too)", p1.find('class="fold ioutcome"') < p1.find('id="history"') and (p1.find('id="next"') < 0 or p1.find('class="fold ioutcome"') < p1.find('id="next"')))

    check("the phone layout orders the block with the state line", ".imain>.ioutcome{order:0}" in p1)

    # ---- 5. the repair, dry: what it would restore, and nothing written
    before_files = {i: (T / f"store/a/{i}.json").read_text() for i in (11, 12, 13, 14, 15, 16, 17, 21, 22)}
    rows, skipped = migsvc._close_description_repair(apply=False)
    by = {r["gid"]: r for r in rows}
    check("dry run: the closed items whose close rewrote the description and left no outcome text are listed (a11, a21, a22) and no other", sorted(by) == ["a11", "a21", "a22"], sorted(by))
    check("…each row has the description now, the one before the close and the outcome text it would get", by["a11"]["before"] == OLD_END and by["a11"]["after"] == DESC and by["a11"]["outcome_text"] == OLD_END, by.get("a11"))
    check("…an item that already has an outcome text (a1, edited after its close; a15) is left and counted, so the close's text is never dropped", skipped.get("has_outcome") == 2 and "a1" not in by and "a15" not in by, (skipped, sorted(by)))
    check("…the reasons for the rest are counted: a12 old, a3 a4 a5 a6 a13 kept, a14 edited after, a17 no history, and the open ones", skipped.get("old") == 1 and skipped.get("kept") == 5 and skipped.get("edited") == 1
          and skipped.get("no_history") == 1 and skipped.get("open", 0) >= 4, skipped)
    check("…a dry run writes nothing", all((T / f"store/a/{i}.json").read_text() == before_files[i] for i in before_files))

    # ---- 6. the tool: --live --apply is refused while the service runs (or systemd cannot say); a dry run is allowed
    def fake_systemctl(d, state, code=0):
        """A systemctl that answers `show -p ActiveState --value <unit>` with the state (and exits code); anything else it is asked fails."""
        (T / d).mkdir(exist_ok=True); p = T / d / "systemctl"
        p.write_text('#!/bin/sh\n[ "$2" = show ] && [ "$3" = -p ] && [ "$4" = ActiveState ] && [ "$5" = --value ] && [ "$6" = stackshot.service ] || exit 9\n'
                     f'echo "{state}"\nexit {code}\n'); p.chmod(p.stat().st_mode | stat.S_IXUSR)
    for st in ("active", "activating", "deactivating", "inactive", "failed"):
        fake_systemctl(f"bin-{st}", st)
    fake_systemctl("bin-unsure", "", 1)
    TOOL = str(pathlib.Path(STACK, "stackshot", "tools", "restore_close_descriptions.py"))
    def tool(bindir, *args):
        env = dict(os.environ, PATH=bindir + os.pathsep + os.environ.get("PATH", ""), STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
        return subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True, timeout=600, env=env)
    r = tool(str(T / "bin-active"), "--live", "--apply")
    check("--live --apply while stackshot.service is active: refused, exit 1, says why", r.returncode == 1 and "refused while the stackshot server may be running" in r.stderr and "stackshot.service is active" in r.stderr, (r.returncode, r.stderr[:300]))
    check("…nothing was written", all((T / f"store/a/{i}.json").read_text() == before_files[i] for i in before_files))
    r = tool(str(T / "bin-unsure"), "--live", "--apply")
    check("--live --apply when systemd cannot say: refused too", r.returncode == 1 and "systemctl could not say" in r.stderr and all((T / f"store/a/{i}.json").read_text() == before_files[i] for i in before_files), (r.returncode, r.stderr[:300]))
    r = tool(str(T / "bin-active"))
    check("the arguments are checked: neither --store nor --live is exit 1", r.returncode == 1 and "exactly one of" in r.stderr, (r.returncode, r.stderr[:200]))
    r = tool(str(T / "bin-active"), "--live")
    check("a dry run while the service is active is allowed: it lists what it would restore and writes nothing",
          r.returncode == 0 and "would restore the description" in r.stdout and "3 item(s) would restore" in r.stdout and "has outcome text: 2" in r.stdout and "dry run: nothing was written" in r.stdout
          and all((T / f"store/a/{i}.json").read_text() == before_files[i] for i in before_files), (r.returncode, r.stdout[-400:], r.stderr[-300:]))

    # ---- 7. the tool, applied (the service not running)
    for state in ("activating", "deactivating"):
        r = tool(str(T / f"bin-{state}"), "--live", "--apply")
        check(f"--live --apply while the unit is {state} (is-active says non-zero for it): refused, nothing written", r.returncode == 1 and "refused while the stackshot server may be running" in r.stderr
              and all((T / f"store/a/{i}.json").read_text() == before_files[i] for i in before_files), (r.returncode, r.stderr[:300]))
    r = tool(str(T / "bin-failed"), "--live", "--apply")
    check("--live --apply with the unit failed (stopped): exit 0 and it says it restored 3 items", r.returncode == 0 and "3 item(s) restored their description" in r.stdout, (r.returncode, r.stdout[-400:], r.stderr[-300:]))
    check("a11: the description is the one before the close, the close's text is the outcome text", rd(11)["description"] == DESC and mt(11).get("outcome_text") == OLD_END and rd(11)["status"] == "completed", rd(11))
    check("a21 and a22: restored too", rd(21)["description"] == DESC and rd(22)["description"] == DESC and mt(22).get("superseded_by") == "a21", (rd(21), rd(22)))
    check("nothing else of a restored item changed: status, outcome, reason and every clock are as they were",
          all({k: v for k, v in rd(i).items() if k not in ("description", "written_by", "written_at", "activity")} == {k: v for k, v in json.loads(before_files[i]).items() if k != "description"}
              | {"metadata": {**json.loads(before_files[i])["metadata"], "outcome_text": OLD_END}} for i in (11, 21, 22)), [rd(i) for i in (11, 21)])
    check("…and the activity clock an item from before the field gains at its first save is its last update, not the repair's time (activity.py)",
          all(rd(i).get("activity") == max(json.loads(before_files[i])["updated"], json.loads(before_files[i]).get("state_updated") or 0) for i in (11, 21, 22)), [(i, rd(i).get("activity")) for i in (11, 21, 22)])
    check("the items it left are exactly as they were: a12 (old), a13 (kept), a14 (edited after), a15 (has outcome text), a16 (open), a17 (no history)", all((T / f"store/a/{i}.json").read_text() == before_files[i] for i in (12, 13, 14, 15, 16, 17)))
    check("a14 keeps the edit made after the close", rd(14)["description"] == EDITED, rd(14)["description"])
    rows2, skipped2 = migsvc._close_description_repair(apply=False)
    check("idempotent: a second look finds nothing to restore", rows2 == [], rows2)
    r = tool(str(T / "bin-inactive"), "--live", "--apply")
    check("…and a second --apply (the unit inactive) restores nothing and exits 0", r.returncode == 0 and "0 item(s) restored" in r.stdout, (r.returncode, r.stdout[-300:]))
    bd2 = r2.Board(f"{tmp}/store")
    p11 = bd2.item_html("a11")
    check("a restored item's page: Outcome shows the close's text, Background the original description", "rewritten at the close" in p11[p11.find('class="fold ioutcome"'):p11.find('id="description"')]
          and "Move the nightly export" in p11[p11.find('id="description"'):], p11[:200])

    print(("ok" if not fails else "FAILED") + f": close keeps description scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
    sys.exit(1 if fails else 0)


# ================================================================ part 4: a close ticks only its own open steps (formerly complete_own_steps_scenario)
def part_own_steps():
    tmp, T = _fixture("ownsteps-", ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"), transcripts=True, owner="Robin")      # removed (and flock-held while the suite runs) by _scratch, pass or fail
    NAMES = ("home-owner", "home-stew", "team-back", "home-front")
    U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
    now0 = time.time(); DAY = 86400.0
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
    def proj(session, agents, back):
        return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": proj("home-stew", {"home-front": "the front", "team-back": "the back"}, {"team-back": "the back"})}}))
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
    (T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
    DESC = "- A thing\n- It lives here\n- Done when done"
    OUT = "- The thing works now\n- It lives here\n- Finished when it ships"
    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    from stackshot.web import server; from stackshot.model import steps as S; from stackshot.model import nextlines as NL
    from stackshot.service import wait_gates as wait_gates_svc
    from stackshot.service import update as _update_svc
    from stackshot.core import instance as _core_instance
    from stackshot.web.tools import text as _web_tools_text
    from fastmcp.exceptions import ToolError
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    from stackshot.service import checks as checks_svc
    from stackshot.web.tools import update as _wt_update
    from stackshot.web.tools import complete as _wt_complete
    OWNER = _core_instance.OWNER
    _web_publish._publish = lambda: None
    _web_page_debts._owing_note = lambda debtor: ""

    MINE, THEIRS = "home-front: build it", "team-back: verify the deploy"
    def item(i, lines=(MINE, THEIRS), writers=None, status="open", **meta):
        """An item of the front agent with the given next lines; `writers` (default: the front agent for a home-front line, the back agent for the others) are the sessions whose writes put the lines in next, None for a legacy item with no record."""
        text = "\n".join(lines)
        ws = writers or [U["home-front"] if ln.startswith("home-front:") else U["team-back"] for ln in lines]
        base = {"owner": U["home-front"], "project": "projects/alpha", "next": text, "needs": ["team-back"]}
        if writers != "legacy": base["next_by"] = [[w, NL.key_of(ln)] for ln, w in zip(lines, ws)]
        base.update(meta)
        su = now0 - 10 * DAY
        (T / f"store/g/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                          "updated": su, "state_updated": su, "confirmed": su, "metadata": base}))
    def rd(i): return json.loads((T / f"store/g/{i}.json").read_text())
    def raw(i): return (T / f"store/g/{i}.json").read_text()
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1500]}" if got is not None else ""))
    def sts(i): return [(x["status"], x.get("by") or "") for x in rd(i)["metadata"].get("steps") or []]
    def kinds(i): return [k for k, _ in sts(i)]
    def ref(i): return "board" + "#" + str(i)      # the tools take the item as board#N: built here, so the text carries no literal id shape
    def complete(i, who="home-front", outcome="done", sup=""):
        return _wt_complete.stackshot_complete(ref(i), outcome=outcome, reason="it ended", outcome_text=OUT, superseded_by=sup, sender=who)
    def close_update(i, who="home-front", outcome="done", **kw):
        return _wt_update.stackshot_update(ref(i), status="completed", outcome=outcome, reason="it ended", outcome_text=OUT, sender=who, **kw)
    def refused(name, f, *want):
        try:
            out = f(); check(name, False, out)
        except ToolError as e:
            check(name, all(w in str(e) for w in want), str(e))
            return str(e)
        return ""

    # ================================================================ 1. another session's open step holds the close back
    item(1)
    before = raw(1)
    msg = refused("complete by the sender: refused, the other session's step is named, with who owes it", lambda: complete(1), "Refused", "team-back: verify the deploy", "owed by team-back", "stays open")
    check("…the sender's own step is not named as the one in the way", "build it" not in msg, msg)
    check("…the refusal says nothing is ticked and what to do: wait for that session, mark your own steps, or mark the step in the closing call", "nothing is ticked" in msg and "done=[n]" in msg and "dropped=[2]" in msg, msg)
    check("…and wrote nothing: the item is open, the file is as it was", raw(1) == before and rd(1)["status"] == "open" and "steps" not in rd(1)["metadata"], rd(1))
    item(2)
    refused("update with status=completed: the same refusal", lambda: close_update(2), "team-back: verify the deploy", "stays open")
    check("…and it wrote nothing", raw(2) == (T / "store/g/2.json").read_text() and rd(2)["status"] == "open", rd(2))
    for n, oc in ((3, "dropped"), (4, "superseded")):
        item(n)
        refused(f"outcome {oc}: refused too", lambda: complete(n, outcome=oc, sup=ref(1) if oc == "superseded" else ""), "team-back: verify the deploy")
        check(f"…{oc}: the item is still open with both steps open", rd(n)["status"] == "open" and rd(n)["metadata"]["next"] == f"{MINE}\n{THEIRS}", rd(n))
    item(5, lines=(THEIRS,))
    refused("the sender has no step of its own and another's is open: refused", lambda: complete(5), "team-back: verify the deploy")
    item(6, lines=(MINE, "team-back: verify the deploy", "home-stew: watch the release"), writers=[U["home-front"], U["team-back"], U["home-stew"]])
    msg6 = refused("two other sessions' steps: both are named", lambda: complete(6), "mark those steps", "owed by team-back", "owed by home-stew", "verify the deploy", "home-stew: watch the release", "dropped=[2, 3]")
    item(7, lines=(MINE, "home-stew: a line from before the record"), writers="legacy")
    check("a legacy item (no writer record): its lines are the creator's, so the creator closes it as before", "completed" in complete(7) and kinds(7) == ["done", "done"] and rd(7)["status"] == "completed", sts(7))
    item(8, lines=(MINE, "home-stew: a line from before the record"), writers="legacy")
    refused("…and another session that is not the creator is refused for them", lambda: complete(8, who="team-back"), "Refused", "stays open")
    item(9, lines=(MINE, THEIRS), writers=["home-front", "team-back"])      # the record stores a pane's name instead of the id
    msg9 = refused("writers stored as names are told apart too", lambda: complete(9), "team-back: verify the deploy")
    check("…and the sender's own step, stored under its pane name, is still its own (not named)", "build it" not in msg9, msg9)

    # a step that opens with the sender's name is the sender's own, whoever wrote the line (a front agent writes `team-back: build it`, the builder closes)
    item(30, lines=("team-back: build the thing",), writers=[U["home-front"]])
    complete(30, who="team-back")
    check("a step that opens with the closer's name, written by the creator, is the closer's own: the builder closes, the step is done by it", rd(30)["status"] == "completed" and sts(30) == [("done", "team-back")], sts(30))
    item(31, lines=("team-back: build the thing",), writers=[U["home-front"]])
    complete(31, who="home-front")
    check("…and the creator that wrote it closes too (its writer)", rd(31)["status"] == "completed" and kinds(31) == ["done"], sts(31))
    item(32, lines=("team-back: build the thing", "home-stew: watch the release"), writers=[U["home-front"], U["home-front"]])
    msg32 = refused("a line the creator wrote that opens with a third session's name is that session's: the builder's close is refused for it alone", lambda: complete(32, who="team-back"), "owed by home-stew")
    check("…and the builder's own step is not named", "build the thing" not in msg32 and "owed by team-back" not in msg32, msg32)
    item(33, lines=("team-back: build the thing",), writers=[U["home-front"]])
    close_update(33, who="team-back")
    check("update with status=completed by the named session closes it as well", rd(33)["status"] == "completed", rd(33))
    item(34, lines=(MINE, "the next step"), writers=[U["home-front"], U["team-back"]])
    complete(34)
    check("a line that names nobody owes nothing to anyone: it never holds a close up, and the close ticks it", rd(34)["status"] == "completed" and kinds(34) == ["done", "done"], sts(34))
    item(35, lines=("team-back: build the thing",), writers=[U["home-front"]])
    refused("another session than the one the step names is refused (the front agent's main, home-stew)", lambda: complete(35, who="home-stew"), "owed by team-back")

    item(36, lines=("team-back: verify the deploy",), writers=["home-front"])      # written by the closer (stored under its pane name) for another session: its own by writer
    complete(36)
    check("a step the closer wrote for another session is the closer's own (writer stored as a pane name)", rd(36)["status"] == "completed" and kinds(36) == ["done"], sts(36))

    # the owner's step in any form the model reads as his (config.owner_opener_rx: his name, an alias, a non-Latin alias, `you:`, `<owner> to …`) never holds a close up; a step of another session still does
    from stackshot.core import config as _cfg
    ALIASES = _cfg.owner_aliases()
    check("the instance has a Latin and a non-Latin alias for the owner (the forms below are read from it, never typed here)", len(ALIASES) >= 2 and ALIASES[0].isascii() and not ALIASES[1].isascii(), ALIASES)
    check("the fixture names its owner, so the `<owner> to …` case below reads a real name", OWNER == "Robin" and OWNER in _cfg.owner_names(), (OWNER, _cfg.owner_names()))
    for k, owner_line in enumerate((f"{ALIASES[0]}: approve the deploy", f"{ALIASES[1]}: approve the deploy", "you: approve the deploy", f"{OWNER} to run: the deploy script", f"{ALIASES[0]} to review: the deploy",
                                    f"{ALIASES[0].lower()}: approve the deploy", f"{ALIASES[0]} (decision): approve the deploy", f"{OWNER.upper()} (decision): approve the deploy"), start=40):
        item(k, lines=(MINE, owner_line), writers=[U["home-front"], U["team-back"]])
        complete(k)
        check(f"an owner's step opened as `{owner_line.split(':')[0]}:` by another session is the owner's, not another session's: the close goes through and ticks it", rd(k)["status"] == "completed" and kinds(k) == ["done", "done"], (owner_line, sts(k)))
    item(60, lines=(MINE, "you: approve the deploy", THEIRS), writers=[U["home-front"], U["team-back"], U["team-back"]])
    msg60 = refused("control: an owner's step and another session's step: the close is refused for the other session's step alone", lambda: complete(60), "owed by team-back", "verify the deploy")
    check("…and the owner's step is not named in the refusal", "approve the deploy" not in msg60 and "owed by you" not in msg60, msg60)

    # ================================================================ 2. what closes
    item(10, lines=(MINE, "home-front: test it"))
    out10 = complete(10)
    check("only the sender's own steps are open: the close ticks them, by the sender", rd(10)["status"] == "completed" and kinds(10) == ["done", "done"] and {b for _, b in sts(10)} == {"home-front"} and "next" not in rd(10)["metadata"], (sts(10), out10[:200]))
    item(11, steps=[{"text": THEIRS, "status": "done", "by": "team-back", "at": now0 - 100}], lines=(MINE,))
    complete(11)
    check("a step of another session that it marked itself earlier is left as it is (by, at): the close ticks only the sender's", rd(11)["status"] == "completed" and [(k, b) for k, b in sts(11)] == [("done", "team-back"), ("done", "home-front")] and rd(11)["metadata"]["steps"][0]["at"] == now0 - 100, sts(11))
    item(12)
    close_update(12, dropped=[2])
    check("the closing call marks the other's step itself (dropped=[2]): the close goes through, that step is dropped, the sender's own is done, both by the sender", rd(12)["status"] == "completed" and kinds(12) == ["done", "dropped"] and {b for _, b in sts(12)} == {"home-front"}, sts(12))
    item(13)
    close_update(13, done=["team-back: verify the deploy"])
    check("done=[text] on the other's step with the close: it is done, by the sender", rd(13)["status"] == "completed" and kinds(13) == ["done", "done"], sts(13))
    item(14)
    close_update(14, outcome="dropped", dropped=[2])
    check("outcome dropped with the other's step marked: own and marked steps are dropped", rd(14)["status"] == "completed" and kinds(14) == ["dropped", "dropped"], sts(14))
    item(15, lines=(MINE, f"{OWNER}: read it", ), writers=[U["home-front"], U["team-back"]])
    complete(15)
    check(f"an owner's step ({OWNER}'s) never holds the close up: it is settled by the close, as before", rd(15)["status"] == "completed" and kinds(15) == ["done", "done"], sts(15))
    item(16)
    out16 = _wt_update.stackshot_update(ref(16), sender="home-front", done=[1])
    check("marking your own step with update leaves the item open and the other's step open (the way the refusal points to)", rd(16)["status"] == "open" and rd(16)["metadata"]["next"] == THEIRS and kinds(16) == ["done", "open"], (sts(16), rd(16)["metadata"]))
    complete(16, who="team-back")
    check("…then the other session closes it: its own step is ticked, by it", rd(16)["status"] == "completed" and kinds(16) == ["done", "done"] and sts(16)[1][1] == "team-back", sts(16))
    item(17)
    check("a close the closer does not mark, with a step of its own and the other's marked in the same call by name: goes through", "completed" in close_update(17, dropped=[THEIRS]), None)

    # ================================================================ 3. the server's own closes
    item(20); item(21); item(22)
    checks_svc.check_close("g20", rd(20), "a done check", time.time())
    check("a done check's close settles every open step, by the server (unchanged)", kinds(20) == ["done", "done"] and {b for _, b in sts(20)} == {_core_instance.NAME} and rd(20)["metadata"]["outcome"] == "done", sts(20))
    it21 = rd(21); wait_gates_svc._watch_close(it21, "dropped on his answer", time.time())
    check("a watcher ask's drop settles every open step, by the server (unchanged)", [x["status"] for x in it21["metadata"]["steps"]] == ["dropped", "dropped"], it21["metadata"])
    _update_svc._update(ref(22), status="completed", outcome="done", reason="it ended", outcome_text=OUT, sender="a script on testbox")
    check("a script's close (no session's tool call) settles every open step (unchanged)", rd(22)["status"] == "completed" and kinds(22) == ["done", "done"], sts(22))

    # ================================================================ 4. the text
    import asyncio
    desc_ = {t.name: t.description for t in asyncio.run(server.mcp.list_tools())}
    for n in ("complete", "update"):
        check(f"text: {n} says a close ticks only the closer's own steps and leaves another session's open", "ticks only the steps that are still open and are yours" in desc_[n] and "another session" in desc_[n] and "marks every step" not in desc_[n], desc_[n][:300])
    check("text: the rule a refused close appends says it too", "ticks only the steps that are still open and are yours" in _web_tools_text._CLOSE_REFUSAL and "marks every step" not in _web_tools_text._CLOSE_REFUSAL, None)
    check("text: complete tells where to mark another session's step (update, done or dropped with the close)", "mark it in the closing call with update" in desc_["complete"] and "dropped=[n]" in desc_["complete"], None)

    print(("ok" if not fails else "FAILED") + f": complete own steps scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)


PARTS = {"close": part_close, "marks": part_marks, "keeps_description": part_keeps_description, "own_steps": part_own_steps}


def _run_part(name):
    try:
        PARTS[name]()      # ends the process itself (sys.exit or os._exit) with the part's summary line and its exit code
    finally:      # the folder goes whatever happened (a failing check, an exception, sys.exit); _scratch removes it at exit as well (os._exit included)
        for d in _made: shutil.rmtree(d, ignore_errors=True)


def _run_all():
    total = 0; failed = []
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], capture_output=True, text=True, timeout=1500)
        sys.stdout.write(r.stdout); sys.stdout.flush(); sys.stderr.write(r.stderr); sys.stderr.flush()
        m = re.search(r"^(ok|FAILED): .*? scenario, (\d+) checks", r.stdout, re.M)
        if m: total += int(m.group(2))
        if r.returncode != 0 or not m or m.group(1) != "ok":
            failed.append(name); print(f"FAIL part {name}: exit {r.returncode}, summary {m.group(0) if m else 'missing'}" + (f"\n{r.stderr[-600:]}" if not m else ""))
    print(("ok" if not failed else "FAILED") + f": close scenario, {total} checks in {len(PARTS)} parts" + (f", failed: {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--part"]: _run_part(sys.argv[2])
    else: _run_all()
