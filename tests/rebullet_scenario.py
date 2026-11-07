"""Scenario test for the description's form and the re-bullet pass — fixture data, no live store, no network, no server socket, no model call (the call is a stub).

  1  the write guard (model_guards.description_problem): a paragraph or a bullet over 300 characters, or a description over 400 characters with no bullet, is a thick block; short
     bullets, a short plain text, fenced code and `>` quotes are not; a link counts as its words and a bare URL as four characters
  2  in the server: [model] description_guard = "note" (the default) lets the write through with the guidance in the reply (create and update); "refuse" refuses it, nothing written;
     an update that does not set the description never judges it; a close is never judged; the tool texts say bullets
  3  the report on existing items counts it (the brief line, the full text, tools/model_guard_report.py --json)
  4  the checks on a rewrite (rebullet.py): every URL, number, date, code span, quoted span and `>` quote of the old text must be in the new one; every line a bullet; at most the
     ceiling's lines; not a thick block; not much shorter or longer; a lossy rewrite is refused, a clean one passes
  5  the pass with the call stubbed (tools/rebullet_descriptions.py): the open items the candidate test picks (with [description] require_bullets = true, the write gate's
     bullet_text.judge; with false, the board item's thick-block test), closed ones and passing ones skipped, the longest first; the dry run names the test and counts per reason; the sample writes nothing
     and prints before and after; the apply writes through POST /client/rebullet and leaves a lossy rewrite alone
  6  the one writer (/client/rebullet): the sender `rebullet`, the state clock and confirm stay, the owner is told nothing; a description changed since the rewrite was made wins; a closed item, a
     lossy rewrite and a machine that is not the server box are refused

    tests/run-suite rebullet        → exit 0 / 1"""
import asyncio, contextlib, datetime, importlib.util, io, json, os, re, subprocess, sys, pathlib, tempfile, time, logging, hashlib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="rebullet-test-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), owner=True, keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the re-bullet pass, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-peer", "home-lost", "home-beta-front")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
def proj(session, agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": proj("home-stew", {"home-front": "the front", "team-back": "the back"}, {"team-back": "the back"})}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing.\n- It lives here.\n- Done when done."
def item(i, owner=None, status="open", su=None, letter="a", subject=None, desc=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    base = {"owner": owner or U["home-front"], "project": "projects/alpha", "next": "home-front: do the thing"}
    base.update(meta)
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": DESC if desc is None else desc, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su, "metadata": base}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def refused(name, f, *want, none=()):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want) and not any(w in str(e) for w in none), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
import server, model, model_guards as mg, rebullet as rb
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda gid, owner, note, tag="wake": None
raw = lambda i, letter="a": (T / f"store/{letter}/{i}.json").read_text()
def upd(i, letter="a", **kw): return server._update(f"{letter}{i}", sender="home-front", **kw)
def set_cfg(**kw):
    server._cfg.CFG["model"] = {"rebullet_machines": ["box-a"], **kw}      # the example-owner instance lists box-a (tests/_instance.py)
set_cfg()
SERVER_BOX = "box-a"

# ================================================================ 1. the write guard, pure
P = mg.description_problem
check("1 guard: an empty description and a short plain one are fine", P("") == "" and P("A thing. It lives here.") == "" and P("a" * 300) == "", None)
check("1 guard: a paragraph over 300 characters is a thick block, with the guidance", "a paragraph of 301 characters" in P("a" * 301) and "short `- ` bullets, one line each" in P("a" * 301)
      and "never a paragraph" in P("a" * 301) and "what it is, the links, his words" in P("a" * 301), P("a" * 301))
two = ("b" * 250) + "\n\n" + ("c" * 250)
check("1 guard: two paragraphs of 250 (500 characters) with no bullet are one thick block; the same with a bullet are not", "500 characters with no bullet" in P(two) and P("- " + ("b" * 250) + "\n\n" + ("c" * 250)) == "", P(two))
check("1 guard: over 400 characters in all with no bullet is thick, 400 exactly is not", "no bullet" in P(("d" * 200) + "\n\n" + ("e" * 201)) and P(("d" * 200) + "\n\n" + ("e" * 200)) == "", None)
five = "\n".join("- " + ("short bullet " * 9).strip() for _ in range(5))
check("1 guard: five bullets of about 110 characters (over 500 in all) are fine, each short", len(five) > 500 and P(five) == "", P(five))
check("1 guard: a bullet over 300 characters is a thick block; a numbered list and * bullets count as bullets", "paragraph of 309" in P("- " + ("f" * 309)) and P("1. aaa\n2. bbb\n* ccc\n+ ddd") == "", P("- " + ("f" * 309)))
check("1 guard: an indented continuation line belongs to its bullet; a plain line after a list is a new paragraph", "paragraph of 301" in P("- " + ("g" * 150) + "\n  " + ("g" * 150)) and P("- one\n" + ("h" * 301)).startswith("description has a paragraph of 301"), P("- " + ("g" * 150) + "\n  " + ("g" * 150)))
check("1 guard: a fenced code block does not count, however long", P("- what it is\n```\n" + ("x" * 2000) + "\n```\n- done when done") == "" and P("~~~sh\n" + ("y" * 900) + "\n~~~") == "", None)
check("1 guard: a > quote does not count, however long (his words)", P("- what it is\n> " + ("z " * 400) + "\n- next") == "" and P("> " + ("q" * 800)) == "", None)
check("1 guard: …but the prose around a fence still counts", "a paragraph of 350" in P(("p" * 350) + "\n```\ncode\n```"), None)
check("1 guard: a link counts as its words and a bare URL as four characters", P("- see [the plan](https://example.org/" + ("a" * 400) + ")") == "" and P("- see https://example.org/" + ("b" * 600)) == "", None)
check("1 guard: units: bullets, plain runs, no fence, no quote, link words", mg.description_units("Intro\n- one two\n  continued\n```\nxxxx\n```\n> quote long\nafter [w](http://u) https://v.example/q\n") == (["Intro", "one two continued", "after w link"], True), mg.description_units("Intro\n- one two\n  continued\n```\nxxxx\n```\n> quote long\nafter [w](http://u) https://v.example/q\n"))
check("1 guard: it is registered: a key of GUARDS, a label, a text guard", "description" in mg.GUARDS and mg.LABELS["description"] == "description not in bullets" and "description" in mg.FIELD_GUARDS, None)

# ================================================================ 2. in the server: note, refuse, untouched fields, closes, the tool texts
server._cfg.CFG["description"]["require_bullets"] = False      # the board item's bullet gate would refuse the thick text before the guard under test (note, then refuse) sees it: off for section 2
THICK = ("Move the widget to shelf-2 so it syncs from shelf-1 on its own when shelf-1 is full, as Oliver asked on Mon Jun 8th: \"it should sync by itself, no button\". "
         "The plan is at https://example.org/plan/42 and the unit is `widget-sync.service`. About 12 checks run every 30 seconds, and the sync must finish within 5 minutes. "
         "Nothing is built yet; the first step is a dry run on shelf-2, and then the full sync test, which needs the second disk mounted first.")
check("2 setup: the fixture text is thick and over 400 characters", len(THICK) > 400 and P(THICK) != "", len(THICK))
out = server._create(subject="[home] a thick create", description=THICK, project="projects/alpha", owner="home-front", next="home-front: go")
gid = re.search(r"created (\S+) ", out).group(1); stored = server._load(server._norm_id(gid))
check("2 note: the default writes the thick description and says so in the reply", stored["description"] == THICK and "(note: description has a paragraph of" in out and "short `- ` bullets, one line each" in out, out[:900])
out = server._create(subject="[home] a bulleted create", description=DESC, project="projects/alpha", owner="home-front", next="home-front: go")
check("2 note: bullets draw no note", "description has" not in out and "(note: description" not in out, out[:600])
item(60); item(61, desc=THICK); item(62, desc=THICK)
out = upd(60, description=THICK)
check("2 note: an update that sets a thick description goes through with the note", rd(60)["description"] == THICK and "(note: description has a paragraph of" in out, out[:900])
out = upd(61, next="home-front: another step")
check("2 note: an update that does not set the description never judges it (an old item's text is not its writer's)", "(note: description" not in out and rd(61)["description"] == THICK, out[:400])
set_cfg(description_guard="refuse")
was = raw(60)
refused("2 refuse: an update with a thick description is refused with the guidance", lambda: upd(60, description=THICK + " More."), "Refused:", "description has a paragraph of", "short `- ` bullets")
check("2 refuse: …nothing written", raw(60) == was, None)
refused("2 refuse: a create with a thick description is refused", lambda: server._create(subject="[home] refused create", description=THICK, project="projects/alpha", owner="home-front", next="home-front: go"), "Refused:", "description has a paragraph of")
upd(60, description=DESC)
check("2 refuse: bullets pass", rd(60)["description"] == DESC, rd(60))
out = upd(61, next="home-front: a third step")
check("2 refuse: an update that does not set the description still passes on an item that has a thick one", rd(61)["metadata"]["next"] == "home-front: a third step", out[:300])
was62 = rd(62)["description"]
upd(62, status="completed", outcome="done", reason="it is done", outcome_text=THICK + " It ended well.", next="")
check("2 refuse: a close is never judged (its outcome text is kept apart, the description stays)", rd(62)["status"] == "completed" and rd(62)["metadata"]["outcome_text"].endswith("It ended well.") and rd(62)["description"] == was62, rd(62)["status"])
set_cfg(description_guard="whatever")
out = upd(60, description=THICK)
check("2 mode: an unknown value reads as note", "(note: description has a paragraph of" in out, out[:300])
set_cfg(guards=False, description_guard="refuse")
out = upd(60, description=THICK + " Again.")
check("2 mode: [model] guards = false turns the description guard off too", "(note: description" not in out and rd(60)["description"].endswith("Again."), out[:300])
set_cfg()
tools = {t.name: t.description or "" for t in asyncio.run(server.mcp.list_tools())}
check("2 tools: create, update and complete say short bullets, one line each, never a paragraph", all("short `- ` bullets" in tools[n] for n in ("create", "update")) and "never a paragraph" in tools["create"]
      and "never a paragraph" in tools["update"] and "short `- ` bullets" in tools["complete"] and "outcome_text" in tools["complete"], [n for n in ("create", "update", "complete") if "bullets" not in tools[n]])
check("2 tools: the rule is not 1-3 lines any more, and the line ceiling's refusal says bullets", "1–3 short lines" not in tools["create"] and "1–3 short lines" not in server.mcp.instructions, None)
refused("2 ceiling: more than [description] max_lines lines is still refused", lambda: upd(60, description="\n".join(f"- line {i}" for i in range(10))), "description has 10 lines", "short `- ` bullets")

# a reopen judges the description only when it sets one; the question route is exempt
set_cfg(description_guard="refuse")
item(70, status="completed", desc=THICK, outcome="done", reason="done")
upd(70, status="open", next="home-front: pick it up again")
check("2 reopen: in refuse mode a reopen that does not set the description is not refused over the old thick one", rd(70)["status"] == "open" and rd(70)["description"] == THICK, rd(70)["status"])
item(71, status="completed", desc=THICK, outcome="done", reason="done")
was71 = raw(71)
refused("2 reopen: …but one that sets a thick description is refused, nothing written", lambda: upd(71, status="open", next="home-front: pick it up again", description=THICK + " More."), "description has a paragraph of")
check("2 reopen: …(nothing written)", raw(71) == was71, None)
upd(71, status="open", next="home-front: pick it up again", description=DESC)
check("2 reopen: …and one that sets bullets reopens", rd(71)["status"] == "open" and rd(71)["description"] == DESC, rd(71)["status"])
refused("2 question route: without the exemption the thick create is refused in refuse mode", lambda: server._create(subject="[home] a question", description=THICK, project="projects/alpha", owner="home-front", next="home-front: go"), "description has a paragraph of")
server._QUESTION.on = True
try:
    out_q = server._create(subject="[home] a script's question", description=THICK, project="projects/alpha", owner="home-front", next="home-front: go")
finally:
    server._QUESTION.on = False
check("2 question route: …a create under the question route's flag is exempt (a script's text is never stranded on a wording refusal)", out_q.startswith("created") and "description has" not in out_q, out_q[:200])
set_cfg()

server._cfg.CFG["description"].pop("require_bullets", None)       # back on (the default) for the rest
# ================================================================ 3. the report on existing items
for k in list(T.glob("store/*/[0-9]*.json")): k.unlink()
item(1, desc=THICK); item(2); item(3, status="completed", desc=THICK); item(4, desc=THICK + THICK)
rep = mg.report({f"a{i}": rd(i) for i in (1, 2, 3, 4)}, mg.Ctx(), one_mover=True)
check("3 report: the open items with a thick description are counted under `description`, the closed one and the bulleted one are not", rep.ids.get("description") == ["a1", "a4"], rep.ids)
check("3 report: the brief line and the full text carry the count", "description not in bullets 2" in mg.brief_line(rep) and "description not in bullets: 2: a1, a4" in mg.full_text(rep), mg.brief_line(rep))
env = {**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml", "STACKSHOT_FLEET_DIR": f"{tmp}/fleet"}
cl = subprocess.run([sys.executable, os.path.join(STACK, "tools/model_guard_report.py"), "--json"], capture_output=True, text=True, env=env)
check("3 report: tools/model_guard_report.py --json lists them", cl.returncode == 0 and json.loads(cl.stdout)["guards"].get("description") == ["a1", "a4"], (cl.returncode, cl.stdout[:300], cl.stderr[:300]))

# ================================================================ 4. the checks on a rewrite (rebullet.py)
V0 = lambda *a, **k: rb.verdict(*a, line_max=0, **k)      # these checks are about meaning and shape, not the write gate's line length (line_max 0 judges no length)
GOOD = ("- Move the widget to shelf-2 so it syncs from shelf-1 on its own when shelf-1 is full\n- Oliver, Mon Jun 8th: \"it should sync by itself, no button\"\n"
        "- Plan: https://example.org/plan/42; unit `widget-sync.service`\n- About 12 checks every 30 seconds; sync within 5 minutes\n"
        "- Nothing built yet: first a dry run on shelf-2, then the full sync test (needs the second disk mounted first)")
check("4 verdict: a rewrite that keeps every link, number, date, quote and code span, in bullets, passes", rb.verdict(THICK, GOOD) == "" and rb.lost(THICK, GOOD) == [], (rb.verdict(THICK, GOOD), rb.lost(THICK, GOOD)))
def lossy(name, new, want):
    v = rb.verdict(THICK, new)
    check(f"4 verdict: refused when {name}", want in v, v)
lossy("a URL is gone", GOOD.replace("https://example.org/plan/42", "the plan page"), "url https://example.org/plan/42")
lossy("a number is gone", GOOD.replace("12 checks", "a dozen checks"), "number 12")
lossy("a time is gone", GOOD.replace("within 5 minutes", "quickly"), "number 5")
lossy("a date is gone", GOOD.replace("Mon Jun 8th", "Monday"), "date Jun 8th")
lossy("his quote is reworded", GOOD.replace("it should sync by itself, no button", "wants it automatic"), "quote “it should sync by itself, no button”")
lossy("a code span is gone", GOOD.replace("`widget-sync.service`", "the sync unit"), "code `widget-sync.service`")
lossy("it is not bullets (a plain line)", GOOD + "\nThe plan and the unit and the checks again.", "a line is not a bullet")
lossy("it is empty", "  \n", "empty")
lossy("it is the old text", THICK, "the old text")
lossy("it has more lines than the ceiling", "\n".join(GOOD.splitlines() + ["- the plan", "- the unit", "- the checks", "- the cutover"]), "9 lines, over the description's 8-line ceiling")
check("4 verdict: a bullet that is itself a thick block is refused", "a bullet of" in rb.verdict(THICK, "- " + THICK.replace("\n", " ")), rb.verdict(THICK, "- " + THICK))
_res = rb.resolved; rb.resolved = lambda o, n: ""
check("4 verdict: much shorter (the numbers kept, the sentences dropped) is refused", "much shorter" in V0(THICK, "- Oliver it it its nothing 26 1 2 42 12 30 5 `widget-sync.service` https://example.org/plan/42 \"it should sync by itself, no button\" Jun 8th"),
      V0(THICK, "- Oliver it it its nothing 26 1 2 42 12 30 5 `widget-sync.service` https://example.org/plan/42 \"it should sync by itself, no button\" Jun 8th"))
rb.resolved = _res
check("4 verdict: a forbidden token the old text lacked is refused", "contains 'done:'" in rb.verdict(THICK, GOOD + "\n- done: yes", forbid=["done:"]), None)
FENCED = "Run this on the box, as Oliver said \"go ahead\":\n```sh\nsudo systemctl restart stackshot\n```\n" + ("The unit is restarted by the deploy and nothing else needs doing here. " * 2)
FB = "- Run on the box, as Oliver said \"go ahead\":\n```sh\nsudo systemctl restart stackshot\n```\n- The unit is restarted by the deploy and nothing else needs doing here\n- The unit is restarted by the deploy and nothing else needs doing here"
check("4 verdict: a fenced block and a quote line are kept as they were, outside the bullet rule", rb.verdict(FENCED, FB) == "" and "code block" in rb.verdict(FENCED, FB.replace("sudo systemctl restart stackshot", "sudo restart")), rb.verdict(FENCED, FB))
check("4 verdict: a > quote line is kept or refused", V0("> keep these words exactly\n" + ("pad " * 40), "- " + ("pad " * 38).strip() + "\n> keep these words exactly") == ""
      and "quote line keep these words exactly" in V0("> keep these words exactly\n" + ("pad " * 40), "- " + ("pad " * 38).strip()), None)
check("4 parse: a preface and a code fence around the bullets are dropped; no bullet is no answer", rb.parse("Here is the rewrite:\n\n- a\n- b") == "- a\n- b" and rb.parse("```\n- a\n- b\n```") == "- a\n- b" and rb.parse("nothing here") == "", None)
check("4 message: the item as context and the description as data between tags", "<description>" in rb.build_message("board#9028", {"subject": "[home] s", "description": "desc text", "metadata": {"goal": "g"}}) and "desc text" in rb.build_message("board#9028", {"description": "desc text"}), None)

LINKED = "- see [the plan](https://example.org/plan/42) for the details, which are long enough to count as a body of text here"
check("4 verdict: a link written on its words stays one: the same address as a bare URL is refused", rb.lost("see [the plan](https://example.org/plan/42) now", "- see https://example.org/plan/42 now") == ["link on its words ](https://example.org/plan/42)"]
      and rb.lost("see [the plan](https://example.org/plan/42) now", "- see [the plan](https://example.org/plan/42) now") == [], rb.lost("see [the plan](https://example.org/plan/42) now", "- see https://example.org/plan/42 now"))
tries = []
def twice(first, second):
    def r(message, system):
        tries.append(message)
        return {"status": "ok", "text": first if len(tries) == 1 else second}
    return r
item_ = {"subject": "[home] s", "description": THICK, "metadata": {}}
bad1 = GOOD + "\n- the plan\n- the unit\n- the checks\n- the cutover"
st_, new_, note_ = rb.rewrite("board#9029", item_, twice(bad1, GOOD))
check("4 retry: a refused first answer gets one more call that is told why; a good second answer stands, marked", st_ == "ok" and new_ == GOOD and note_ == "second try" and len(tries) == 2
      and "Your previous answer was refused by a check: 9 lines, over the description's 8-line ceiling" in tries[1] and "<previous>" in tries[1], (st_, note_, len(tries)))
tries.clear()
st_, new_, note_ = rb.rewrite("board#9029", item_, twice(bad1, bad1))
check("4 retry: a second refusal stands, with the reason", st_ == "refused" and new_ == "" and "9 lines" in note_ and len(tries) == 2, (st_, note_, len(tries)))
tries.clear()
st_, new_, note_ = rb.rewrite("board#9029", item_, twice(bad1, GOOD), retry=False)
check("4 retry: retry=False is one call", st_ == "refused" and len(tries) == 1, (st_, len(tries)))
st_, new_, note_ = rb.rewrite("board#9029", item_, lambda m, s_: {"status": "timeout", "text": "", "note": "killed after 120 s"})
check("4 call: a runner that failed is `call`, never retried into a write", st_ == "call" and "timeout" in note_ and new_ == "", (st_, note_))
st_, new_, note_ = rb.rewrite("board#9029", item_, lambda m, s_: {"status": "ok", "text": "no bullets here, just prose"})
check("4 call: an answer with no bullet is refused", st_ == "refused" and "no bullets" in note_, (st_, note_))
st_, new_, note_ = rb.rewrite("board#9029", item_, lambda m, s_: {"status": "ok", "text": GOOD})
check("4 call: a good first answer is ok with no note", st_ == "ok" and note_ == "" and new_ == GOOD, (st_, note_))

# second form of the rule: whose words they are, no restated title or id, one bullet per numbered step, the done line on its own
ATTR = "Oliver: try one folder first, then move the rest a couple of days before the handover. The move lands by Tue Jun 16th, as agreed in board#9025. Done when all folders sit in the new place. " + ("Padding about the plan and the budget. " * 6)
check("4 whose words: dropping the name in front of his words is refused, keeping it passes", "Oliver (1 mention in the old text, 0 in the new" in rb.verdict(ATTR, "- Try one folder first, then move the rest a couple of days before the handover.\n- The move lands by Tue Jun 16th, as agreed in board#9025.\n- Done when all folders sit in the new place.\n- Padding about the plan and the budget. " * 1)
      and rb.verdict(ATTR, "- Oliver: try one folder first, then move the rest a couple of days before the handover.\n- The move lands by Tue Jun 16th, as agreed in board#9025.\n- Padding about the plan and the budget. Padding about the plan and the budget. Padding about the plan and the budget.\n- Done when all folders sit in the new place.") == "",
      rb.verdict(ATTR, "- Oliver: try one folder first, then move the rest a couple of days before the handover.\n- The move lands by Tue Jun 16th, as agreed in board#9025.\n- Padding about the plan and the budget. Padding about the plan and the budget. Padding about the plan and the budget.\n- Done when all folders sit in the new place."))
check("4 whose words: every mention counts (two in the old text, one in the new is refused), and the Japanese name too", "Oliver (2 mentions in the old text, 1 in the new" in "; ".join(rb.lost("Oliver said a. Oliver said b.", "- Oliver said a and b.")) and any("オリバー" in x for x in rb.lost("オリバー: いいです", "- いいです")), rb.lost("Oliver said a. Oliver said b.", "- Oliver said a and b."))
check("4 ids: an id stays as written (the form with a lower-case board is not the form with a capital), and none is added", "id board#9031 as written" in "; ".join(rb.lost("see board#9031 for it", "- see Board#9031 for it")) and "an id was added or its form changed (Board#9031)" in rb.shape("see board#9031 for it", "- Board#9031 is it"), rb.shape("see board#9031 for it", "- Board#9031 is it"))
check("4 ids: a bullet that brings the item's own id in is refused", "board#9029" in rb.shape("a plain description of the work", "- board#9029: a plain description of the work"), None)
check("4 title: a first bullet that mostly repeats the subject is refused, one with the substance first passes",
      "restates the title" in rb.shape("x", "- Move the widget to shelf-2: let it sync by itself when shelf-1 is full.", "[home] Move the widget to shelf-2 and let it sync by itself when shelf-1 is full")
      and rb.shape("x", "- shelf-2 passed the sync dry run on the sample cluster.", "[home] Move the widget to shelf-2 and let it sync by itself when shelf-1 is full") == ""
      and rb.shape("x", "- anything at all here", "") == "", None)
check("4 title: only the first bullet is compared", rb.shape("x", "- The dry run passed on the new box.\n- Move the widget to shelf-2 and let it sync by itself when shelf-1 is full.", "[home] Move the widget to shelf-2 and let it sync by itself when shelf-1 is full") == "", None)
STEPS = "Order: (1) a test on the new shelf only; (2) a live copy from the old shelf; (3) the automatic sync with a lock; (4) a drill. Done when the drill has passed and he has seen the result."
check("4 steps: two numbered steps in one bullet are refused; one bullet per step, and the done line as its own bullet, pass",
      "numbered steps share a bullet" in rb.shape(STEPS, "- Order: (1) a test on the new shelf only; (2) a live copy from the old shelf\n- (3) the automatic sync with a lock; (4) a drill\n- Done when the drill has passed and he has seen the result")
      and rb.shape(STEPS, "- (1) a test on the new shelf only\n- (2) a live copy from the old shelf\n- (3) the automatic sync with a lock\n- (4) a drill\n- Done when the drill has passed and he has seen the result") == "", None)
check("4 steps: `1)` and `1.` markers count too; a single step needs no split", "numbered steps share" in rb.shape("1) a 2) b", "- 1) a 2) b") and rb.shape("only (1) one step here", "- only (1) one step here") == "", None)
check("4 done: a done line glued into another bullet is refused, so is one that is no bullet's start", "glued" in rb.shape(STEPS, "- (1) a\n- (2) b\n- (3) c\n- (4) a drill. Done when the drill has passed and he has seen the result") and "not a bullet of its own" in rb.shape("Done when x", "- x is complete"), None)
check("4 done: `Finished when` and `Done =` count the same; an item with no done line needs none", "glued" in rb.shape("Finished when all of it is live.", "- Sidebar: sessions. Finished when all of it is live") and rb.shape("Done = the hall told him.", "- Done = the hall told him.") == "" and rb.shape("no such line", "- no such line") == "", None)
check("4 title: a first bullet the old text's own first sentence already said is not a restatement (the rewrite brought nothing in)",
      rb.shape("the sync job reads the sample API through the token, which expires Sep 19th 2099; more follows.", "- the sample API token expires Sep 19th 2099", "[home] Renew the sample API token before it expires Sep 19th 2099") == ""
      and "restates the title" in rb.shape("a short list of what waits", "- the sample reader: a short list", "[home] Sample reader: short list"), None)
check("4 bullets: a bullet over 240 characters is refused with the fix, 240 or less passes", "a bullet of 241 characters" in rb.shape("x", "- " + ("k" * 241)) and rb.shape("x", "- " + ("k" * 240)) == "", None)
BOOKING = ("Stage layout notes from Morgan, collected in the [e-mail thread](https://mail.example/t/1) and Slack [#venue](https://chat.example/c/9).\n"
           "Marcus asked about the booking on Jun 2nd; Oliver explained his reason: it fixes the date and the seating plan. "
           "Oliver handed it to Jordan, who has to return the signed form before his slot is held.\nDone = the hall confirms or the date is cancelled; Marcus hears either way.")
BOOKING_OK = ("- Stage layout notes from Morgan\n- Collected in the [e-mail thread](https://mail.example/t/1) and Slack [#venue](https://chat.example/c/9)\n"
              "- Marcus asked about the booking on Jun 2nd; Oliver explained his reason: it fixes the date and the seating plan\n"
              "- Oliver handed it to Jordan, who has to return the signed form before his slot is held\n- Done = the hall confirms or the date is cancelled; Marcus hears either way")
check("4 pronouns: the source's own words, pronouns and all, pass", V0(BOOKING, BOOKING_OK) == "", V0(BOOKING, BOOKING_OK))
BAD = BOOKING_OK.replace("handed it to Jordan", "handed the booking to Jordan")
check("4 pronouns: `handed it` turned into `handed the booking` is refused twice over: a pronoun lost, and a thing brought in from another sentence",
      "may resolve a pronoun" in rb.resolved(BOOKING, BAD) and "brings in booking" in rb.resolved(BOOKING, BAD) and 'pronoun "it"' in rb.verdict(BOOKING, BAD) and rb.resolved(BOOKING, BOOKING_OK) == "", (rb.resolved(BOOKING, BAD), rb.verdict(BOOKING, BAD)))
check("4 pronouns: `his reason` turned into `Oliver's reason` is refused (a pronoun lost)", 'pronoun "his" (2 in the old text, 1 in the new' in rb.verdict(BOOKING, BOOKING_OK.replace("explained his reason", "explained Oliver's reason")), rb.verdict(BOOKING, BOOKING_OK.replace("explained his reason", "explained Oliver's reason")))
check("4 pronouns: every pronoun counts, `it` and `its` and the Japanese ones too", "pronoun \"it\"" in "; ".join(rb.lost("it works. it is fine", "- it works")) and "pronoun \"彼の\"" in "; ".join(rb.lost("彼の 言葉", "- オリバーの言葉"))
      and rb.lost("the item is itemised", "- the item is itemised") == [] and rb.lost("see it", "- see it now") == [], rb.lost("the item is itemised", "- the item is itemised"))
check("4 pronouns: a semicolon or a parenthesis does not end a sentence (a bullet taken from both halves of one is not a borrowing)",
      rb.resolved("His pick on the board: Automatic sync (live copy; shelf-2 takes the files itself after shelf-1 fills). Other sentence here.", "- His pick on the board: Automatic sync (live copy; shelf-2 takes the files itself after shelf-1 fills)") == "", None)
check("4 pronouns: a bullet that matches no sentence, or a sentence with no pronoun, is not judged", rb.resolved("The plan is at the url. Another thing entirely.", "- The plan is at the url, and the thing") == "" and rb.resolved("a b", "- x y") == "", None)
check("4 stop: no full stop at the end of a bullet (a `...`, a quote line and a code block are left), the answer's own lines otherwise as they are",
      rb.parse("- one two three.\n- four five.\n- six...\n> a quote.\n```\ncode.\n```\n- end 7.") == "- one two three\n- four five\n- six...\n> a quote.\n```\ncode.\n```\n- end 7", rb.parse("- one two three.\n- four five.\n- six...\n> a quote.\n```\ncode.\n```\n- end 7."))
NEGOLD = "Do not restart the service before the backup ends. Never delete the old data, and keep the logs for 30 days. Nothing else changes."
check("4 meaning: a lost negation is refused (\"do not restart, never delete\" is not \"restart, delete\"), the same words with their negations pass",
      "fewer negations (1 against 3" in rb.verdict(NEGOLD, "- Restart the service before the backup ends\n- Delete the old data, and keep the logs for 30 days\n- Nothing else changes")
      and rb.verdict(NEGOLD, "- Do not restart the service before the backup ends\n- Never delete the old data, and keep the logs for 30 days\n- Nothing else changes") == "", rb.verdict(NEGOLD, "- Restart the service before the backup ends\n- Delete the old data, and keep the logs for 30 days\n- Nothing else changes"))
check("4 meaning: the Japanese negations count too (ない, ません, 不, なかった)", rb.meaning("配布できない, 問題ありません, 不 可, しなかった", "- 配布できる, 問題あります, 可, した").startswith("the rewrite has fewer negations") and rb.meaning("会議の話", "- 会議の話") == "", None)
FACT = "The report is due on Jun 12th and the team owns the draft and the review of the figures."
check("4 meaning: an added fact (words the old text lacks, beyond a few) is refused; a few joining or inflected words are not",
      "brings in 4 words" in rb.verdict(FACT, "- The report is due on Jun 12th\n- The team owns the draft and the review of the figures and the budget approval from finance leadership")
      and rb.verdict(FACT, "- The report is due on Jun 12th\n- The team owns the draft, and reviews the figures") == "", rb.verdict(FACT, "- The report is due on Jun 12th\n- The team owns the draft and the review of the figures and the budget approval from finance leadership"))
STEPS3 = "Order: (1) build the image; (2) test it on the staging box; (3) ship it to the live box."
check("4 meaning: step numbers keep their order and none is dropped",
      "the numbered steps changed (1 2 3 became 2 1 3)" in rb.meaning(STEPS3, "- (2) test it on the staging box\n- (1) build the image\n- (3) ship it to the live box") and "became 1 3" in rb.meaning(STEPS3, "- (1) build the image\n- test it on the staging box\n- (3) ship it to the live box")
      and rb.meaning(STEPS3, "- (1) build the image\n- (2) test it on the staging box\n- (3) ship it to the live box") == "", rb.meaning(STEPS3, "- (2) test it on the staging box\n- (1) build the image\n- (3) ship it to the live box"))
check("4 url: the whole address must stay (…/a is not …/abc), and a link stays on its words", rb.lost("see https://x.example/a now", "- see https://x.example/abc now") == ["url https://x.example/a"] and rb.lost("see https://x.example/a now", "- see https://x.example/a now") == []
      and rb.lost("see https://x.example/abc now", "- see https://x.example/a now") == ["url https://x.example/abc"], rb.lost("see https://x.example/a now", "- see https://x.example/abc now"))
check("4 ids: a bare #9012 or g9077 the old text lacked is refused; one it had stays", "(#9012)" in rb.shape("a plain text", "- see #9012 here") and "(g9077)" in rb.shape("a plain text", "- see g9077 here") and rb.shape("see g9077 and #9012 here", "- see g9077 and #9012 here") == ""
      and "id g9077 as written" in "; ".join(rb.lost("see g9077 here", "- see here")) and rb.shape("a plain text", "- the https://x.example/g9077 page, version v2x and 2g") == "", rb.shape("a plain text", "- see #9012 here"))
class _FakeP:
    argv = None
    def __init__(self, argv, **kw): _FakeP.argv = argv; self.pid = 1; self.returncode = 0
    def communicate(self, msg, timeout=None): return json.dumps({"result": "- a", "is_error": False}), ""
import router as _router2
_orig_popen = _router2.subprocess.Popen; _router2.subprocess.Popen = _FakeP
try:
    r1 = _router2.run_call("m", "sys", model_name="haiku"); a1 = list(_FakeP.argv)
    r2 = _router2.run_call("m", "sys"); a2 = list(_FakeP.argv)
finally:
    _router2.subprocess.Popen = _orig_popen
check("4 call: run_call(model_name=haiku) starts the CLI with --model haiku; without it, [router] model", r1["status"] == "ok" and a1[a1.index("--model") + 1] == "haiku" and a2[a2.index("--model") + 1] == _router2.model(), (a1[:12], a2[:12]))
check("4 rubric: the call is told to nest parallel items under one parent bullet, indented two spaces", all(w in rb.RUBRIC for w in ("Parallel items", "under one parent bullet", "indented two spaces (`  - `)")), None)
check("4 rubric: the call is told about pronouns, and the full stop", all(w in rb.RUBRIC for w in ("NEVER resolve a pronoun", "Every pronoun of the source stays", "may keep two clauses", "Do not end a bullet with a full stop")), None)
check("4 rubric: the call is told about attribution, ids, the title, steps and the done line", all(w in rb.RUBRIC for w in ("Keep who said what", "never Board#N", "Do not restate the item's title or id", "One bullet per numbered step", "its own last bullet")), None)
check("4 rubric: whole sentences, no fragments, a parenthetical stays, the first sentence stays whole", all(w in rb.RUBRIC for w in ("complete statement with its own subject and verb", "never start a bullet with where, which", "A parenthetical stays in the bullet", "keep that sentence whole")), None)

# fragments (round 4): the four rewrites that lost meaning in the first all-21 sample, and what stays allowed
FRAG_TITLE = "Rework the sample pages on one layout. Design: projects/alpha/sample-pages/layout (draft 2). Steps: board#3 and board#4. Done when the pages use the layout."
FRAG_PAREN = "Booking opened Sat Apr 4th: the hall and the stage crew run on the new rota (a shared calendar, reminders and swaps work). Before the full season, the seat limit must be raised (board#5)."
FRAG_WHERE = "The print shop turned down the order: the job waits for a new quote on [issue #4](https://example.org/i/4), where [our answer](https://example.org/i/4#c1) on which paper sizes are chosen is posted."
FRAG_SHORT = "Part 1 of the Venue page: list the rooms the workshop could use, scored on cost. Pinned on 2031-03-30."
fr = rb.fragment
check("4 fragment: 'On one layout' (the subject cut off the first sentence) is refused", "starts with 'On'" in fr(FRAG_TITLE, "- On one layout\n- Design: projects/alpha/sample-pages/layout (draft 2)"), fr(FRAG_TITLE, "- On one layout"))
check("4 fragment: the whole first sentence, restating the title's words, is fine", fr(FRAG_TITLE, "- Rework the sample pages on one layout\n- Design: projects/alpha/sample-pages/layout (draft 2)\n- Steps: board#3 and board#4\n- Done when the pages use the layout") == "", fr(FRAG_TITLE, "- Rework the sample pages on one layout"))
check("4 fragment: a parenthetical cut loose from its sentence is refused", "cut loose" in fr(FRAG_PAREN, "- Booking opened Sat Apr 4th: the hall and the stage crew run on the new rota\n- a shared calendar, reminders and swaps work"), None)
check("4 fragment: the parenthetical kept in its bullet is fine", fr(FRAG_PAREN, "- Booking opened Sat Apr 4th: the hall and the stage crew run on the new rota (a shared calendar, reminders and swaps work)\n- Before the full season, the seat limit must be raised (board#5)") == "", None)
check("4 fragment: a bullet starting with 'Where' is refused", "starts with 'Where'" in fr(FRAG_WHERE, "- The print shop turned down the order: the job waits for a new quote on [issue #4](https://example.org/i/4)\n- Where [our answer](https://example.org/i/4#c1) on which paper sizes are chosen is posted"), None)
check("4 fragment: a bullet of two words is refused; a sentence that introduces a list may be split at its colon (the sample rewrites do)", "too short" in fr(FRAG_SHORT, "- Pinned\n- List the rooms") and fr("Oliver approved the quote (Mon Mar 30th): order the paper tray, keep the spare toner apart from the ink.", "- Oliver approved the quote (Mon Mar 30th)\n- Order the paper tray\n- Keep the spare toner apart from the ink") == "", fr(FRAG_SHORT, "- Pinned"))
check("4 fragment: a step, a Done line, a label with its value and a joining word the source starts with are allowed", fr("(1) staging. (2) a drill. Done when it passes. But only after that.", "- (1) staging\n- (2) a drill\n- Done when it passes\n- But only after that") == "" and fr("a: b c", "- Note: b") == "", fr("(1) staging. (2) a drill. Done when it passes. But only after that.", "- (1) staging\n- (2) a drill\n- Done when it passes\n- But only after that"))
check("4 fragment: verdict refuses it, last, with the same reason", "starts with 'Where'" in rb.verdict(FRAG_WHERE, "- The print shop turned down the order: the job waits for a new quote on [issue #4](https://example.org/i/4)\n- Where [our answer](https://example.org/i/4#c1) on which paper sizes are chosen is posted"), rb.verdict(FRAG_WHERE, "- The print shop turned down the order: the job waits for a new quote on [issue #4](https://example.org/i/4)\n- Where [our answer](https://example.org/i/4#c1) on which paper sizes are chosen is posted"))

LEAD_BUILDS = "Builds 1, 2 and 4 of B on projects/alpha/queue-two (Plan, decided Thu Apr 2nd, board#2): a summary page of only what is open; the changes-since-last-visit view; help text served by the tool itself. Done when the page lists the open items."
LEAD_LEFTOVERS = "Two leftovers from the library upgrade. (1) the printer queue: print.py uses the old driver; the switches go after Jul 3rd. (2) the sample config carries a duplicate entry."
check("4 lead: the lead copied into each item (Build 1 of B: ..., Build 2 of B: ...) is refused", "lead 'builds 1, 2 and 4 of b" in rb.lead(LEAD_BUILDS, "- Build 1 of B on projects/alpha/queue-two (Plan, decided Thu Apr 2nd, board#2): a summary page of only what is open\n- Build 2 of B on projects/alpha/queue-two: the changes-since-last-visit view"), None)
check("4 lead: the lead whole as the first bullet, then the items, is fine", rb.lead(LEAD_BUILDS, "- Builds 1, 2 and 4 of B on projects/alpha/queue-two (Plan, decided Thu Apr 2nd, board#2):\n- A summary page of only what is open\n- The changes-since-last-visit view") == "", rb.lead(LEAD_BUILDS, "- Builds 1, 2 and 4 of B on projects/alpha/queue-two (Plan, decided Thu Apr 2nd, board#2):\n- A summary page"))
check("4 lead: a short first sentence is the lead and is kept as a bullet, or refused when it is dropped", rb.lead(LEAD_LEFTOVERS, "- Two leftovers from the library upgrade\n- (1) the printer queue: print.py uses the old driver\n- (2) the sample config carries a duplicate entry") == ""
      and "lead 'two leftovers from the library upgrade'" in rb.lead(LEAD_LEFTOVERS, "- (1) the printer queue: print.py uses the old driver; the switches go after Jul 3rd\n- (2) the sample config carries a duplicate entry"), None)
check("4 lead: a first sentence with a colon and no list after it is no lead (an attribution with its quote may be split)", rb.lead(THICK, GOOD) == "", rb.lead(THICK, GOOD))
check("4 lead: verdict refuses it, and the rubric tells the call about the lead", "lead 'two leftovers" in rb.verdict(LEAD_LEFTOVERS, "- (1) the printer queue: print.py uses the old driver; the switches go after Jul 3rd\n- (2) the sample config carries a duplicate entry")
      and "stays whole in one bullet, the first" in rb.RUBRIC and "Never copy part of a lead into each item" in rb.RUBRIC, rb.verdict(LEAD_LEFTOVERS, "- (1) the printer queue: print.py uses the old driver; the switches go after Jul 3rd\n- (2) the sample config carries a duplicate entry"))

# review fixes (round 5)
check("4 steps: a markdown numbered list, '- 1. check logs', keeps its steps; a changed order is still refused", rb.meaning("1. check logs\n2. restart the unit", "- 1. check logs\n- 2. restart the unit") == ""
      and "numbered steps changed" in rb.meaning("1. check logs\n2. restart the unit", "- 2. restart the unit\n- 1. check logs"), rb.meaning("1. check logs\n2. restart the unit", "- 1. check logs\n- 2. restart the unit"))
check("4 short: a short sentence the source wrote ('Review pending', 'Importer fails', Japanese) is a statement; a cut-off phrase of two words is not",
      fr("Review pending. Importer fails on large files.", "- Review pending\n- Importer fails on large files") == "" and fr("Importer fails. Nothing else.", "- Importer fails\n- Nothing else") == ""
      and fr("インポーターが失敗する。理由は不明だ", "- インポーターが失敗する\n- 理由は不明だ") == "" and fr("インポーターが大きなファイルで失敗する", "- インポーターが\n- 失敗する") == ""
      and "too short" in fr("Pinned by Oliver on Jun 24th, no deadline set.", "- Pinned by\n- Oliver on Jun 24th"), (fr("Review pending. Importer fails on large files.", "- Review pending\n- Importer fails on large files"), fr("Pinned by Oliver on Jun 24th, no deadline set.", "- Pinned by\n- Oliver on Jun 24th")))
check("4 clause: 'If Sam ran short, the jobs move first' (opener, comma, main clause) is a whole statement; 'Where our answer is posted' (no main clause) is not",
      fr("The check is on Jun 17th: if Sam ran short, the nightly jobs move first to the other queue.", "- The check is on Jun 17th\n- If Sam ran short, the nightly jobs move first to the other queue") == ""
      and "starts with 'If'" in fr("The check is on Jun 17th: if Sam ran short.", "- The check is on Jun 17th\n- If Sam ran short"), None)
def _opener(tail):    # a bullet cut from the middle of a sentence, starting with the opener `tail`
    return fr(f"The plan holds: {tail[0].lower() + tail[1:]}.", f"- The plan holds\n- {tail}")
_ok_t, _bad_t = "If Sam ran short, the nightly jobs move first to the reserve queue", ("Although she is away on Friday, and the schedule is tight", "When the schema arrives, which Anna owns",
                "While the exporter waits, for the schema from Anna on Friday", "If Sam ran short, because the others are simple", "When it is ready, whose owner is Anna", "If it fails, where the log is kept")
check("4 clause: an opener with a comma and a word-led main clause passes; a relative, a joining word, a preposition or another subordinator after the comma is still a fragment",
      _opener(_ok_t) == "" and all("starts with" in _opener(t) for t in _bad_t), [_opener(t) for t in (_ok_t,) + _bad_t])
check("4 clause: the comma must come within ten words of the opener", "starts with 'If'" in _opener("If " + "word " * 11 + "ends, the jobs move first to the lane"), _opener("If " + "word " * 11 + "ends, the jobs move first to the lane"))
OMERGE = "Merged the migration on Jun 3rd. It fixes the login bug for all users, and nothing else changed in the release notes of that week."
check("4 pronoun: a bullet that holds the pronoun's sentence and the one before it whole is the source's own, and passes verdict; a word borrowed without the whole sentence is still refused",
      V0(OMERGE, "- Merged the migration on Jun 3rd. It fixes the login bug for all users, and nothing else changed in the release notes of that week") == ""
      and "resolve a pronoun" in V0(OMERGE, "- Merged the migration on Jun 3rd\n- It fixes the login bug for all users of the migration, and nothing else changed in the release notes of that week"),
      (rb.verdict(OMERGE, "- Merged the migration on Jun 3rd. It fixes the login bug for all users, and nothing else changed in the release notes of that week"), rb.verdict(OMERGE, "- Merged the migration on Jun 3rd\n- It fixes the login bug for all users of the migration, and nothing else changed in the release notes of that week")))

# ================================================================ 5. the pass with the call stubbed
STORE = T / "pass-store"
for d in ("g",): (STORE / d).mkdir(parents=True)
def pitem(n, desc, status="open", subject=None):
    (STORE / "g" / f"{n}.json").write_text(json.dumps({"id": str(n), "subject": subject or f"[home] item {n}", "description": desc, "status": status, "updated": 1.0, "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "home-front: go"}}))
SHORTER = THICK[:440]
pitem(9017, THICK); pitem(9009, DESC); pitem(9031, THICK, status="completed"); pitem(9024, THICK.replace("shelf-2", "home-bob"), subject="[home] the lossy one"); pitem(9173, "- a short bullet\n```\n" + ("c" * 900) + "\n```")
pitem(9023, "Plain text, one line, 410 characters: " + ("word " * 58) + "end 7.")
ANSWERS = {"board#9017": GOOD, "board#9024": GOOD.replace("shelf-2", "home-bob").replace("https://example.org/plan/42", "the plan page")}
calls = []
def stub(message, system):
    calls.append((message, system))
    m = re.search(r'"item": "(board#\d+)"', message)
    ans = ANSWERS.get(m.group(1)) if m else None
    return {"status": "ok", "text": ans} if ans is not None else {"status": "exit", "text": "", "note": "no answer for the item"}
spec = importlib.util.spec_from_file_location("rebullet_descriptions", os.path.join(STACK, "tools", "rebullet_descriptions.py")); rd_tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd_tool)
items = rd_tool.load_all(STORE)
cands = rd_tool.candidates(items)
check("5 pass: the candidates are the open items whose description is a thick block, the longest first; a closed item, a bulleted one and one with long code only are skipped",
      cands == ["g9017", "g9024", "g9023"] or cands == ["g9024", "g9017", "g9023"] or cands == ["g9023", "g9017", "g9024"], cands)
check("5 pass: closed (g9031), bulleted (g9009) and code-only (g9173) are not candidates", not {"g9009", "g9031", "g9173"} & set(cands), cands)
snap = lambda p: hashlib.sha256(b"".join(f.read_bytes() for f in sorted(p.rglob("*.json")))).hexdigest()
h0 = snap(STORE)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = rd_tool.main(["--store", str(STORE)], runner=stub)
check("5 dry run: counts the items it would touch, names the test and counts per reason, calls no model, writes nothing",
      rc == 0 and "3 are candidates by bullet_text.judge (require_bullets = true; max_lines 8, line_max 120): marker 3, long 0, lines 0" in buf.getvalue() and "board#9017: marker," in buf.getvalue()
      and "DRY RUN" in buf.getvalue() and not calls and snap(STORE) == h0, buf.getvalue()[:700])

# the candidate test follows [description] require_bullets (the gate; before it, the board item's thick block)
CSTORE = T / "cand-store"; (CSTORE / "g").mkdir(parents=True)
def citem(n, desc, status="open"):
    (CSTORE / "g" / f"{n}.json").write_text(json.dumps({"id": str(n), "subject": f"[home] cand {n}", "description": desc, "status": status, "updated": 1.0, "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "home-front: go"}}))
PROSE = "The exporter fails on large files.\nIt retries three times and gives up.\nNobody has looked at the logs yet."     # three prose lines, each far under 300 characters
LONGB = "- " + ("word " * 30).strip() + "\n- a short second bullet"                                                          # a bullet of 149 characters
MANY = "\n".join(f"- bullet {k}" for k in range(9))                                                                             # 9 lines, the ceiling is 8
citem(9015, PROSE); citem(9174, LONGB); citem(9175, DESC); citem(9176, MANY); citem(9177, PROSE, status="completed"); citem(9018, THICK); citem(9178, "")
cs = rd_tool.load_all(CSTORE)
check("5 test: require_bullets true: prose lines under 300 characters make a candidate, bullets over 120 make one, more than max_lines lines make one; a text that passes judge, an empty one and a closed item do not",
      sorted(rd_tool.candidates(cs, strict=True, max_lines=8, line_max=120)) == sorted(["g9018", "g9015", "g9174", "g9176"]), rd_tool.candidates(cs, strict=True, max_lines=8, line_max=120))
check("5 test: require_bullets false keeps the earlier test: the short prose lines are not a candidate, the long bullet (under 300) is not, only the thick block is",
      rd_tool.candidates(cs, strict=False, max_lines=8, line_max=120) == ["g9018"], rd_tool.candidates(cs, strict=False, max_lines=8, line_max=120))
check("5 test: the reasons are marker (not a bullet), long (a bullet over line_max) and lines (over max_lines)",
      [rd_tool.reason(cs[g]["description"], max_lines=8, line_max=120) for g in ("g9015", "g9174", "g9175", "g9176", "g9178")] == ["marker", "long", "", "lines", ""]
      and rd_tool.reason(cs["g9018"]["description"], strict=False) == "thick" and rd_tool.reason(PROSE, strict=False) == "", None)
check("5 test: the ceiling and the length follow the config values passed (line_max 200 lets the 149-character bullet pass, max_lines 20 the nine lines)",
      sorted(rd_tool.candidates(cs, strict=True, max_lines=20, line_max=200)) == sorted(["g9018", "g9015"]), rd_tool.candidates(cs, strict=True, max_lines=20, line_max=200))
def cdry(*extra):
    b = io.StringIO()
    with contextlib.redirect_stdout(b):
        r = rd_tool.main(["--store", str(CSTORE), *extra], runner=stub)
    return r, b.getvalue()
r_on, o_on = cdry()
check("5 test: the dry run with require_bullets true says which test it used and counts per reason",
      r_on == 0 and "open items: 4 are candidates by bullet_text.judge (require_bullets = true; max_lines 8, line_max 120): marker 2, long 1, lines 1; 2 pass and are skipped" in o_on, o_on)
server._cfg.CFG["description"]["require_bullets"] = False
try:
    r_off, o_off = cdry()
finally:
    server._cfg.CFG["description"].pop("require_bullets", None)
check("5 test: with require_bullets false the dry run uses the thick-block test and counts it", r_off == 0 and "1 are candidates by thick block, model_guards.description_problem (require_bullets = false" in o_off
      and "thick 1;" in o_off and "board#9018: thick," in o_off and "board#9015" not in o_off, o_off)
hlp = subprocess.run([sys.executable, os.path.join(STACK, "tools/rebullet_descriptions.py"), "--help"], capture_output=True, text=True, env=env).stdout.replace("\n", " ")
check("5 test: --help and the docstring describe the judge test, require_bullets and the reasons, not only the old thick block", "bullet_text.judge" in hlp and "thick-block test" in hlp
      and all(w in rd_tool.__doc__ for w in ("bullet_text.judge", "require_bullets", "marker", "long", "lines")), hlp[:300])
out_md = T / "sample.md"
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = rd_tool.main(["--sample", "2", "--store", str(STORE), "--out", str(out_md)], runner=stub)
md = out_md.read_text(encoding="utf-8")
check("5 sample: the 2 longest are run (the lossy one twice), before and after as markdown, nothing written", rc == 0 and len(calls) == 3 and "# Re-bullet sample" in md and md.count("**Before**") == 2 and snap(STORE) == h0, (rc, len(calls), md[:300]))
check("5 sample: a passing rewrite shows its bullets, a refused one says why", ("**After** " in md or "**After**" in md) and "refused, the rewrite lost url https://example.org/plan/42" in md and "- Move the widget to shelf-2 so it syncs" in md, md[:1500])
check("5 sample: it needs a copy of the store given, and --apply takes neither --store nor --sample",
      all(subprocess.run([sys.executable, os.path.join(STACK, "tools/rebullet_descriptions.py"), *a], capture_output=True, text=True, env=env).returncode == 2 for a in (["--sample", "3"], ["--apply", "--store", str(STORE)], ["--apply", "--sample", "2", "--store", str(STORE)])), None)
def dry(*a):
    b = io.StringIO()
    with contextlib.redirect_stdout(b):
        r = rd_tool.main([*a, "--store", str(STORE)], runner=stub)
    return r, b.getvalue()
r1, o1 = dry("--only", "board#9017,g9024"); r2, o2 = dry("--except", "#9017 9023"); r3, o3 = dry("--only", "board#9009,9031")
check("5 only/except: --only keeps those candidates, --except drops them; ids as board#N, #N, gN or N, commas or spaces; a non-candidate is said and skipped",
      r1 == 0 and "board#9017:" in o1 and "board#9024:" in o1 and "board#9023:" not in o1 and "--only: 2 candidate(s) left" in o1
      and r2 == 0 and "board#9024:" in o2 and "board#9017:" not in o2 and "board#9023:" not in o2 and "--except: 1 candidate(s) left" in o2
      and "board#9009 is not a candidate" in o3 and "board#9031 is not a candidate" in o3 and "--only: 0 candidate(s) left" in o3, (o1, o2, o3))
calls.clear(); buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = rd_tool.main(["--sample", "5", "--store", str(STORE), "--only", "board#9017", "--out", str(T / "only.md")], runner=stub)
check("5 only/except: a sample with --only runs the one item only", rc == 0 and len(calls) == 1 and (T / "only.md").read_text(encoding="utf-8").count("**Before**") == 1, len(calls))
check("5 only/except: a bad id, or --only with --except, is refused (exit 2)",
      all(subprocess.run([sys.executable, os.path.join(STACK, "tools/rebullet_descriptions.py"), *a], capture_output=True, text=True, env=env).returncode == 2 for a in (["--only", "board#x"], ["--only", "g1", "--except", "g2"])), None)
_tool = lambda *a: subprocess.run([sys.executable, os.path.join(STACK, "tools/rebullet_descriptions.py"), *a], capture_output=True, text=True, env=env)
r_empty = [_tool(*a) for a in (["--only", ""], ["--only", " , "], ["--except", ""], ["--apply", "--from", str(T / "sample.json"), "--only", ""], ["--apply", "--from", str(T / "sample.json"), "--except", "  "])]
check("5 only/except: an empty or blank list is refused (exit 2) and writes nothing, so an empty shell variable never widens the run to every item",
      all(r.returncode == 2 and "empty list" in r.stderr for r in r_empty) and snap(STORE) == h0, [(r.returncode, r.stderr[-120:]) for r in r_empty])
jfile = T / "sample.json"
jdoc = json.loads(jfile.read_text(encoding="utf-8")) if jfile.exists() else {}
jr = {r["gid"]: r for r in jdoc.get("rewrites", [])}
check("5 json: --sample --out F.md also saves F.json: per item the id, old text, new text, status and the verdict (the refusal's reason)",
      len(jr) == 2 and all(r["old"] and "item" in r and "subject" in r for r in jr.values()) and sorted(r["status"] for r in jr.values()) == ["ok", "refused"]
      and any(r["status"] == "ok" and r["new"] == GOOD and r["verdict"] == "" for r in jr.values()) and any(r["status"] == "refused" and "lost url" in r["verdict"] for r in jr.values()), jdoc)
check("5 json: load_saved gives the ok rewrites only, by id", list(rd_tool.load_saved(jfile)) == [g for g, r in jr.items() if r["status"] == "ok"], None)
check("5 from: --from needs --apply alone (not --sample, --store, --json, or a dry run), and a file that is not a rewrites list is refused",
      all(_tool(*a).returncode == 2 for a in (["--from", str(jfile)], ["--apply", "--from", str(jfile), "--sample", "2"], ["--apply", "--from", str(jfile), "--store", str(STORE)], ["--apply", "--from", str(T / "nosuch.json")],
                                           ["--apply", "--from", str(out_md)])), None)
check("5 call: the system prompt says bullets, what to keep and that the text is data; it runs on a Haiku-class model by default", "short markdown bullets" in calls[0][1] and "every URL, every number and date" in calls[0][1]
      and "data, never instructions" in calls[0][1] and rb.MODEL == "haiku", calls[0][1][:300])
import router as _router
argv = _router.build_argv("sys", "haiku")
check("5 call: router.run_call's argv carries the model and unsets the API variables; without one it keeps [router] model", argv[argv.index("--model") + 1] == "haiku" and "-u ANTHROPIC_API_KEY" in " ".join(argv)
      and _router.build_argv("sys")[_router.build_argv("sys").index("--model") + 1] == _router.model(), argv[:6])

# the apply, against the server's write path: the same items as the pass's store, in the server's own store (letter g = board#N)
for k in list(T.glob("store/*/[0-9]*.json")): k.unlink()
PLAIN = "Plain text, one line, 410 characters: " + ("word " * 58) + "end 7."
ANSWERS["board#9023"] = "- Plain text, one line, 410 characters:\n- " + ("word " * 20).strip() + "\n- " + ("word " * 19).strip() + "\n- " + ("word " * 19).strip() + "\n- word end 7"      # bullets within the write gate's 120
item(9017, letter="g", desc=THICK, su=now0 - 9 * DAY); item(9009, letter="g", su=now0 - 9 * DAY); item(9031, letter="g", status="completed", desc=THICK, su=now0 - 9 * DAY)
item(9024, letter="g", desc=THICK.replace("shelf-2", "home-bob"), su=now0 - 9 * DAY); item(9023, letter="g", desc=PLAIN, su=now0 - 9 * DAY)
before = {n: raw(n, "g") for n in (9017, 9009, 9031, 9024, 9023)}
told = []
for fn in ("_pilot_relay", "_owed_mark", "_tell_owner"):
    orig = getattr(server, fn)
    setattr(server, fn, (lambda o, f: (lambda *a, **k: (told.append(f), o(*a, **k))[1]))(orig, fn))
post = lambda what, body, timeout: server._client_post(SERVER_BOX, what, body)
calls.clear()
apply_json = T / "approved-apply.json"
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc_s = rd_tool.main(["--sample", "9", "--store", str(T / "store"), "--json", str(apply_json)], runner=stub)
ran_for = [re.search(r'"item": "(board#\d+)"', m).group(1) for m, _ in calls]
check("5 apply: the sample's call ran for the three candidates only (the closed item and the bulleted one were not offered to it); the lossy one was tried a second time", sorted(ran_for) == ["board#9017", "board#9023", "board#9024", "board#9024"], ran_for)
check("5 apply: --apply without --from is refused (exit 2) and names --from; with --from it asks no model", _tool("--apply").returncode == 2 and "--from" in _tool("--apply").stderr and not calls[len(ran_for):], _tool("--apply").stderr[-200:])
nrun = len(calls)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = rd_tool.main(["--apply", "--from", str(apply_json)], runner=None, poster=post)
out_text = buf.getvalue()
check("5 apply: --from writes the two good rewrites; the lossy one was marked refused in the file, so it is not in the run; no model was called; the exit is 0",
      rc == 0 and len(calls) == nrun and "written board#9017: set" in out_text and "written board#9023: set" in out_text and "board#9024" not in out_text and "2 item(s) tried, 2 written, 0 left alone" in out_text, out_text)
check("5 apply: the item is in bullets now, the guard no longer calls it thick", rd(9017, "g")["description"] == GOOD and P(rd(9017, "g")["description"]) == "" and rd(9023, "g")["description"] == ANSWERS["board#9023"], rd(9017, "g")["description"])
check("5 apply: the lossy item, the closed one and the bulleted one are exactly as they were", all(raw(n, "g") == before[n] for n in (9009, 9031, 9024)), None)
m1, b1 = rd(9017, "g"), json.loads(before[9017])
check("5 apply: the record names the writer (rebullet via a script on the server box)", m1["written_by"] == f"rebullet via a script on {SERVER_BOX}", m1.get("written_by"))
check("5 apply: a filing edit: the state clock and the confirm did not move, the rest of the item is as it was", m1["state_updated"] == b1["state_updated"] and m1["confirmed"] == b1["confirmed"]
      and m1["updated"] > b1["updated"] and {k: v for k, v in m1["metadata"].items() if k != "phase"} == b1["metadata"] and m1["subject"] == b1["subject"], (m1["metadata"], b1["metadata"]))      # the stored phase apart: every save of an open item writes it
check("5 apply: no page is owed and no one is told (no relay, no debt mark, no notice to the owner)", not told, told)
told.clear()
upd(9009, letter="g", description="- one\n- two")
check("5 apply: (contrast: an ordinary description edit by a session does owe the page and tell, so the silence above is the route's)", bool(told), told)

# --apply --from: exactly the saved texts, no model call, an item not in the file never written
for n in (9007, 9016, 9014, 9022, 9036): item(n, letter="g", desc=THICK, su=now0 - 9 * DAY)
item(9013, letter="g", status="completed", desc=THICK, su=now0 - 9 * DAY)
LOSSY = GOOD.replace("12 checks", "a dozen checks")
saved_rows = [{"item": f"board#{n}", "gid": f"g{n}", "subject": f"[home] item {n}", "old": THICK, "new": new, "status": st, "verdict": ""}
              for n, new, st in ((9007, GOOD, "ok"), (9016, GOOD, "ok"), (9022, GOOD, "refused"), (9036, LOSSY, "ok"), (9013, GOOD, "ok"))]
ffile = T / "approved.json"; ffile.write_text(json.dumps({"rewrites": saved_rows}), encoding="utf-8")
item(9016, letter="g", desc=THICK + " Edited since.", su=now0 - 9 * DAY)
was_f = {n: raw(n, "g") for n in (9016, 9014, 9022, 9036, 9013)}
calls.clear(); told.clear(); buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = rd_tool.main(["--apply", "--from", str(ffile)], runner=None, poster=post)
ft = buf.getvalue()
check("5 from: the saved text is written as it is, with no model call", rd(9007, "g")["description"] == GOOD and not calls and "written board#9007: set" in ft, ft)
check("5 from: an item changed since the sample is left alone, a text the current checks refuse is left alone, a refused entry and an item not in the file are never written; the exit is 1",
      rc == 1 and "left alone board#9016: its description changed since the sample was read" in ft and "left alone board#9036: the current checks refuse the saved text" in ft
      and all(raw(n, "g") == was_f[n] for n in (9016, 9014, 9022, 9036, 9013)) and "board#9014" not in ft and "board#9022" not in ft and "left alone board#9013: the item is not open" in ft and "3 left alone" in ft, ft)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = rd_tool.main(["--apply", "--from", str(ffile), "--only", "board#9007"], runner=None, poster=post)
check("5 from: --only narrows the file's rewrites too; the one already written is no longer the old text, so it is left alone, not rewritten", rc == 1 and "left alone board#9007: its description changed" in buf.getvalue() and "9016" not in buf.getvalue() and "1 item(s) tried" in buf.getvalue(), buf.getvalue())

# ================================================================ 6. the one writer
def route(body, machine=SERVER_BOX): return server._client_post(machine, "rebullet", body)
item(9027, letter="g", desc=THICK, su=now0 - 9 * DAY); item(9032, letter="g", status="completed", desc=THICK)
B = {"item": "board#9027", "sender": "rebullet", "old": THICK, "description": GOOD}
was = raw(9027, "g")
st, d = route(B, "testbox")
check("6 route: a machine that is not the server box is refused, nothing written", st == 400 and "only from the server box" in d["error"] and raw(9027, "g") == was, (st, d))
st, d = route({**B, "sender": "home-front"})
check("6 route: a sender that names a session is refused (the pass writes as itself)", st == 400 and "names a session" in d["error"] and raw(9027, "g") == was, (st, d))
st, d = route({**B, "sender": ""})
check("6 route: a sender is required", st == 400 and "sender is required" in d["error"] and raw(9027, "g") == was, (st, d))
st, d = route({**B, "old": THICK + " edited since"})
check("6 route: a description that changed since the rewrite was made wins: refused, nothing written", st == 400 and "changed since the rewrite was made" in d["error"] and raw(9027, "g") == was, (st, d))
st, d = route({**B, "description": GOOD.replace("12 checks", "a dozen checks")})
check("6 route: a lossy rewrite is refused here too, whoever sends it", st == 400 and "number 12" in d["error"] and raw(9027, "g") == was, (st, d))
was2 = raw(9032, "g")
st, d = route({**B, "item": "board#9032", "old": THICK})
check("6 route: a closed item is refused, left as it was", st == 400 and "not open" in d["error"] and raw(9032, "g") == was2, (st, d))
st, d = route({"item": "board#9027", "sender": "rebullet", "description": GOOD})
check("6 route: old and description are required", st == 400 and "required" in d["error"], (st, d))
set_cfg(rebullet_machines=["testbox"])
st, d = route({**B, "description": GOOD.replace("12 checks", "a dozen checks")}, "testbox")
check("6 route: [model] rebullet_machines says which machines may write (a lossy rewrite still refused there)", st == 400 and "number 12" in d["error"], (st, d))
st, d = route(B)
check("6 route: …and the server box is no longer one of them", st == 400 and "only from the server box" in d["error"], (st, d))
set_cfg()
st, d = route(B)
check("6 route: the rewrite is written, the reply names the item", st == 200 and d["action"] == "set" and d["item"] == "board#9027" and rd(9027, "g")["description"] == GOOD, (st, d))
st, d = route(B)
check("6 route: the same rewrite again is already, nothing changes", st == 200 and d["action"] == "already" and rd(9027, "g")["description"] == GOOD, (st, d))
st, d = server._client_post(SERVER_BOX, "nosuch", {})
check("6 route: the list of writes in the 404 names rebullet", st == 404 and "rebullet" in d["error"], d)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": rebullet scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
