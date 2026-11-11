"""Scenario test for a close that keeps the item's description — fixture data, no live store, no network.

A close used to tell the closing session to rewrite the description to the end state, so a closed item no longer said what it was about. Now the close's summary is its own
field, `metadata.outcome_text`, and the description stays as it was.

Covers: a close (complete, or update with status=completed) keeps the description and stores the outcome text; the reply and `get` show it; a description passed with a close
(an older caller) is stored as the outcome text and never over the description, both together are refused with the item untouched unless the description is the stored one (then it is ignored);
whose words are on a close are read from the outcome text and the reason, not the kept description; an outcome text is held to the bullet form and
length of a description but may say what was resolved; the description of a closed item can still be edited by an update, and the outcome text stays; reopening drops the outcome text
and leaves the description. The item page: a closed item with an outcome text shows an Outcome block under the state line and above Background, Background shows the original
description; an open item, and a closed one with no outcome text, show none. The repair (close_repair.py, server._close_description_repair, tools/restore_close_descriptions.py)
puts back, from the store's git, the description held before the close for items closed in the window, moves the close's text into the outcome text, leaves an item closed
before the window, one that already has an outcome text (counted), one whose close did not rewrite the description, one edited after the close, one with no earlier revision and an open one, changes nothing but the
description and the outcome text, is idempotent, and `--live --apply` is refused unless the unit's ActiveState is inactive or failed (active, activating, deactivating, or systemd unable to say, are refused).

    tests/run-suite close_keeps_description        → exit 0 / 1"""
import json, os, re, sys, pathlib, subprocess, time, logging, stat
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="closekeeptest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "bin-active", "bin-inactive", "bin-unsure"): (T / d).mkdir(parents=True)
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
import shutil
try:
    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
    def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
    def mt(i): return rd(i)["metadata"]

    from stackshot.web import server
    from stackshot.web.ui import render as r2
    server._publish = lambda: None
    server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
    def refused(name, f, *want):
        try:
            out = f(); check(name, False, out)
        except server.ToolError as e:
            check(name, all(w in str(e) for w in want), str(e))

    # ---- 1. a close keeps the description and stores the outcome text
    out = server.stackshot_complete("a1", outcome="done", reason="the export runs from the new bucket", outcome_text=NEW)
    check("complete: the description is exactly what it was, the outcome text is stored", rd(1)["status"] == "completed" and rd(1)["description"] == DESC and mt(1).get("outcome_text") == NEW, rd(1))
    check("complete: outcome and reason are stored as before", mt(1).get("outcome") == "done" and mt(1).get("reason") == "the export runs from the new bucket", mt(1))
    check("complete: the reply and get show the outcome text under a label, and the description as it was", f"outcome text:\n{NEW}" in out and DESC in out and f"outcome text:\n{NEW}" in server.stackshot_get("a1"), out)
    server._update("a2", status="completed", outcome="dropped", reason="not needed after the move", outcome_text="- Not needed: the move made it moot")
    check("update status=completed with outcome_text: the same", rd(2)["description"] == DESC and mt(2).get("outcome_text") == "- Not needed: the move made it moot" and mt(2).get("outcome") == "dropped", rd(2))
    refused("a close with no outcome text is refused and names it", lambda: server.stackshot_complete("a3", outcome="done", reason="it works"), "needs outcome_text")
    refused("an outcome text that is not bullets is refused, named outcome_text", lambda: server.stackshot_complete("a3", outcome="done", reason="it works", outcome_text="It works now."), "outcome_text line is not a `- ` bullet")
    refused("an outcome text over the line limit is refused, named outcome_text", lambda: server.stackshot_complete("a3", outcome="done", reason="it works", outcome_text="- " + "long " * 40), "outcome_text bullet is")
    refused("outcome_text outside a close is refused", lambda: server._update("a3", outcome_text=NEW), "go with a close")
    check("…and nothing above touched the open item", rd(3)["status"] == "open" and rd(3)["description"] == DESC and "outcome_text" not in mt(3), rd(3))
    server.stackshot_complete("a3", outcome="done", reason="it works", outcome_text="- Resolved: the export moved\n- Done: the old bucket is empty")
    check("an outcome text may say what was resolved and done (the forbidden tokens guard live descriptions, not an end state)", mt(3).get("outcome_text", "").startswith("- Resolved:") and rd(3)["description"] == DESC, mt(3))

    # ---- 2. a description passed with a close (an older caller) is the outcome text
    LEGACY = "- The export runs from the new bucket\n- Written by a caller that predates outcome_text"
    server.stackshot_complete("a4", outcome="done", reason="finished", description=LEGACY)
    check("complete with a description: stored as the outcome text, the description is not replaced", rd(4)["status"] == "completed" and rd(4)["description"] == DESC and mt(4).get("outcome_text") == LEGACY, rd(4))
    server._update("a5", status="completed", outcome="done", reason="finished", description=LEGACY)
    check("update status=completed with a description: the same", rd(5)["description"] == DESC and mt(5).get("outcome_text") == LEGACY, rd(5))
    refused("a description and an outcome text together are refused", lambda: server.stackshot_complete("a6", outcome="done", reason="finished", description=LEGACY, outcome_text=NEW), "passes both")
    check("…the item is untouched", rd(6)["status"] == "open" and rd(6)["description"] == DESC and "outcome_text" not in mt(6), rd(6))
    server.stackshot_complete("a6", outcome="done", reason="finished", description=f"  {DESC}\n", outcome_text=NEW)
    check("a description passed with an outcome text that equals the stored one (after strip) is ignored: the close goes through with the outcome text",
          rd(6)["status"] == "completed" and rd(6)["description"] == DESC and mt(6).get("outcome_text") == NEW, rd(6))
    refused("a legacy description that is not bullets is refused as the outcome text", lambda: server.stackshot_complete("a8", outcome="done", reason="finished", description="It is finished."), "outcome_text line is not a `- ` bullet")

    # ---- 2b. whose words: a close is judged on what it wrote (the outcome text and the reason), not on the background the description keeps
    QUOTE = f'- {server.OWNER}, Wed Oct 28th: "ship it"'
    bg_quote = {"status": "completed", "description": QUOTE, "metadata": {"outcome_text": NEW, "reason": "shipped"}}
    check("_owner_words on a close: the owner quoted only in the kept description does not count (no For you row for every close)", server._owner_words(bg_quote) == "", server._owner_words(bg_quote))
    check("…quoted in the outcome text it counts", server._owner_words({**bg_quote, "description": DESC, "metadata": {"outcome_text": QUOTE, "reason": "shipped"}}) == "quoted in the text")
    check("…quoted in the reason it counts", server._owner_words({**bg_quote, "description": DESC, "metadata": {"outcome_text": NEW, "reason": f'{server.OWNER}, Wed Oct 28th: "ship it"'}}) == "quoted in the text")
    check("an open item is still judged on its description", server._owner_words({"status": "open", "description": QUOTE, "metadata": {}}) == "quoted in the text")
    check("a closed item with no outcome text (stored before this change) is still judged on its description", server._owner_words({"status": "completed", "description": QUOTE, "metadata": {"reason": "shipped"}}) == "quoted in the text")

    # ---- 3. the description of a closed item can still be edited; the outcome text stays; reopening drops it
    EDIT = "- Move the nightly export to the new bucket\n- Owner: home-here\n- The old bucket is deleted since"
    server._update("a1", description=EDIT)
    check("update on a closed item still edits its description, and leaves the outcome text", rd(1)["description"] == EDIT and mt(1).get("outcome_text") == NEW and rd(1)["status"] == "completed", rd(1))
    server._update("a2", status="open", next="home-here: pick it up again")
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
    rows, skipped = server._close_description_repair(apply=False)
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
    rows2, skipped2 = server._close_description_repair(apply=False)
    check("idempotent: a second look finds nothing to restore", rows2 == [], rows2)
    r = tool(str(T / "bin-inactive"), "--live", "--apply")
    check("…and a second --apply (the unit inactive) restores nothing and exits 0", r.returncode == 0 and "0 item(s) restored" in r.stdout, (r.returncode, r.stdout[-300:]))
    bd2 = r2.Board(f"{tmp}/store")
    p11 = bd2.item_html("a11")
    check("a restored item's page: Outcome shows the close's text, Background the original description", "rewritten at the close" in p11[p11.find('class="fold ioutcome"'):p11.find('id="description"')]
          and "Move the nightly export" in p11[p11.find('id="description"'):], p11[:200])

    print(("ok" if not fails else "FAILED") + f": close keeps description scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
    sys.exit(1 if fails else 0)
finally:      # the folder goes whatever happened (a failing check, an exception, sys.exit); _scratch removes it at exit as well
    shutil.rmtree(tmp, ignore_errors=True)
