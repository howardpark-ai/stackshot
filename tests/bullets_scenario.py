"""Scenario test for the write-time form gates of an item's text (Tue Oct 27th 2026) — fixture data, no live store, no network.

Covers: a description is refused unless every non-blank line is a `- ` bullet of at most [description] line_max (120) characters and
there are at most max_lines (8) of them, with the refusal naming the line, the limit and the fix; blank lines between bullets and a
nested bullet are fine; a Markdown link counts by its text and a naked URL not at all; a line of next over [metadata.next] line_max
(200) is refused, a `<owner>:` command line and the hash/count/past-tense report notes are not; only the text written in the call is
judged (an update without description and next on an item whose stored description is prose is not refused); a close judges its new
description (complete, and update with status=completed); the limits come from the config; the script question route keeps its form;
and the tool texts state the limits; a subject over [subject] max_length (80) and a close reason over [close] reason_max (120) are refused on create, update and the closes, a stored longer one is left alone, and the server's own closes are cut to the limit.

    tests/run-suite bullets        → exit 0 / 1"""
import json, os, re, sys, pathlib, tempfile, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="bulletstest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra"): (T / d).mkdir(parents=True)
NAMES = ("falcon-main", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/example.md", "type: project\ntitle: Stackshot\ndisplay-name: falcon\nagents:\n  falcon-main: builds it\nstatus: active")
page("projects/other.md", "type: project\ntitle: Other\ndisplay-name: home-other\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.web import server; from stackshot.model import ids as _model_ids
from stackshot.service import telling
from stackshot.service import writes
server._cfg.CFG.setdefault("model", {})["guards"] = False      # fixture owners the fleet does not know; the write guards have their own suite
server._publish = lambda: None

MAIN = "falcon-main"
STK = "projects/example"
def goaled(desc):
    """the goal gate reads the first bullet; these tests are about the other limits, so a first bullet that is not a Goal bullet gets the label (a text that is no bullet is left to the form gate)"""
    return re.sub(r"^(-[ \t]+)(?!Goal:)", r"\1Goal: ", desc, count=1)
def create(desc="- Goal: A thing\n- It lives here\n- Done when done", **kw):
    desc = goaled(desc)
    if not kw.get("next") and "ask" not in kw:
        kw["next"] = f"{MAIN}: carry on"          # an open item has an open step (N6): a create with no next of its own gets a named one
    r = server.stackshot_create(subject=kw.pop("subject", "[home] a thing"), description=desc, project=STK, owner=MAIN, **kw)
    return r, _model_ids._norm_id(r.split()[1])
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except server.ToolError as e:
        check(name, all(w in str(e) for w in want), str(e))
def passes(name, f):
    try:
        f(); check(name, True)
    except server.ToolError as e:
        check(name, False, str(e))
def prose_item(i):
    """an item stored before the gate: a prose description and a long next line, as the live store has"""
    now = time.time()
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] old item {i}", "description": "A thing. It lives here. Done when done.", "status": "open",
                                                    "updated": now, "state_updated": now, "confirmed": now,
                                                    "metadata": {"owner": MAIN, "project": STK, "next": "home-other: " + "word " * 60}}))
FIX = "write short `- ` bullets, one fact each"
bullet = lambda n: "- Goal: " + "x" * (n - 8)        # a bullet of exactly n characters (a Goal bullet, as a first bullet must be)

# ---- 1. descriptions on create
refused("a prose line is refused, naming the line, the limit and the fix", lambda: create("A thing. It lives here. Done when done."),
        "Refused: description line is not a `- ` bullet", '"A thing. It lives here. Done when done."', FIX, "details go on the project page", "8 lines of 120")
refused("one prose line among bullets is refused", lambda: create("- A thing\nIt lives here\n- Done when done"), "not a `- ` bullet", '"It lives here"')
refused("a bullet marker without its space is prose", lambda: create("-A thing"), "not a `- ` bullet")
refused("a star bullet is not a `- ` bullet", lambda: create("* A thing"), "not a `- ` bullet")
refused("a bullet of 121 characters is refused, with its length, the limit and the fix", lambda: create(bullet(121)),
        "description bullet is 121 characters", "limit is 120", FIX, "URL does not count")
passes("a bullet of 120 characters passes", lambda: create(bullet(120)))
refused("the line cap stays: 9 bullets", lambda: create("\n".join(f"- fact {i}" for i in range(9))), "description has 9 lines", "limit is 8", FIX)
passes("8 bullets pass", lambda: create("\n".join(f"- fact {i}" for i in range(8))))
passes("blank lines between bullets are free (they are not lines)", lambda: create("- one\n\n- two\n\n\n- three\n\n- four\n- five\n- six"))
passes("a nested bullet counts as a bullet", lambda: create("- one\n  - nested\n- two"))
link = "[board#1](https://github.com/example/board/issues/1)"
long_link = f"- Waits on {link} and {link} and {link} and {link}, then on the vendor"
check("fixture: the link-heavy bullet is over 120 raw and within 120 as read", len(long_link) > 120 and server._visible_len(long_link) <= 120, (len(long_link), server._visible_len(long_link)))
passes("a link-heavy bullet passes: a link counts by its text, not its URL", lambda: create(long_link))
refused("the words of a link do count", lambda: create("- " + f"[{'w' * 130}](https://example.com/x)"), "description bullet is")
passes("a long URL on a link is not counted", lambda: create("- Lives at [the doc](https://example.com/" + "a" * 200 + ")"))
refused("a naked URL is refused, however short (it is never drawn as a link for sure)", lambda: create("- Lives at https://example.com/a"), "description has a bare URL")
refused("the forbidden tokens still refuse", lambda: create("- resolved: it works"), "contains 'resolved:'")

# ---- 2. next lines on create
n_ok, n_long = "home-other: " + "w" * 200, "home-other: " + "w" * 201
check("fixture: next lines of exactly 200 and 201 characters after the `<actor>: ` prefix", len(n_ok.split(": ", 1)[1]) == 200 and len(n_long.split(": ", 1)[1]) == 201)
refused("a next line of 201 characters is refused, with its length, the limit and the fix", lambda: create(next=n_long),
        "a line of next is 201 characters after its `<actor>: ` prefix", "limit is 200", "one short line per next action", "project page")
passes("a next line of 200 characters passes", lambda: create(next=n_ok))
LONGNAME = "falcon-engineer-with-a-very-long-name (builder): "
passes("the limit counts after the `<actor>: ` prefix: a 200-character action behind a long actor name passes (the whole line is over 250)", lambda: create(next=LONGNAME + "w" * 200))
refused("…and 201 characters after the prefix are refused, the refusal counting after the prefix", lambda: create(next=LONGNAME + "w" * 201), "a line of next is 201 characters after its `<actor>: ` prefix", "limit is 200", "one short line per next action")
WORDY = "w" * 100 + " " + "w" * 100 + " " + "w" * 100 + ": "       # a name of three words of any length is a prefix too: the whole line is capped as well
check("fixture: the three-word name is a prefix of 304 characters, so the action alone is under the limit", server._next_len(WORDY + "act") == 3 and len(WORDY) == 304, (server._next_len(WORDY + "act"), len(WORDY)))
refused("a line of 304+ characters behind a three-word prefix is refused by the whole-line cap", lambda: create(next=WORDY + "act"), "a line of next is 307 characters in all", "limit for the whole line is 280", "one short line per next action")
passes("a line of exactly 280 characters in all passes (80 of prefix, 200 of action)", lambda: create(next="falcon-main-" + "x" * 60 + ": " + "w" * 200))
refused("…and 281 in all are refused, though the action is within 200", lambda: create(next="falcon-main-" + "x" * 67 + ": " + "w" * 200), "a line of next is 281 characters in all", "limit for the whole line is 280")
passes("…a bullet marker and bold marks in front of the actor are part of the prefix", lambda: create(next="- **home-other:** " + "w" * 200))
refused("…and 201 behind them are refused", lambda: create(next="- **home-other:** " + "w" * 201), "a line of next is 201 characters")
check("_next_len: the characters after the prefix; a line with no prefix, or a label that names no one, counts whole",
      server._next_len("home-other: abc") == 3 and server._next_len("my-x (builder): abc") == 3 and server._next_len("1. **my-x:** abc") == 3 and server._next_len("abc def ghi") == 11
      and server._next_len("Status: abc") == 11 and server._next_len("home-other:abc") == 14 and server._next_len(f"home-other: [{'w' * 5}](https://example.com/{'u' * 50}) z") == 7,
      [server._next_len(x) for x in ("home-other: abc", "my-x (builder): abc", "1. **my-x:** abc", "abc def ghi", "Status: abc", "home-other:abc")])
refused("a long line among short ones is refused", lambda: create(next="home-other: first\n- " + n_long), "a line of next is")
passes("a link in next counts by its text", lambda: create(next=f"home-other: read {link} " + "w" * 150))
passes("a long command line of the owner's is not judged", lambda: create(next=f"{server.OWNER}: `" + "x " * 150 + "`"))
r, g = create(next="ops-x: merged 0109c0de0, 12 tests passed")
check("the report notes stay notes: the item is created and the reply carries the note", "next reads like a report" in r and server._path(g).exists(), r)
check("a line over 200 characters is no longer a note", server._report_note("ops-x: " + "word " * 60) == "", server._report_note("ops-x: " + "word " * 60))

# ---- 3. updates judge only the text written in the call
prose_item(30)
passes("an update without description or next on a prose item is not refused", lambda: server._update("a30", priority="p2", sender=MAIN))
passes("…nor one that sets a due date", lambda: server._update("a30", due="2026-12-01", sender=MAIN))
check("…and the stored text is untouched", server._load("a30")["description"] == "A thing. It lives here. Done when done." and len(server._load("a30")["metadata"]["next"]) > 200)
refused("an update that carries a prose description is refused", lambda: server._update("a30", description="Reworded. Still prose.", sender=MAIN), "not a `- ` bullet")
refused("an update that carries a long next line is refused", lambda: server._update("a30", next=n_long, sender=MAIN), "a line of next is 201 characters")
passes("an update that carries a bullet description passes", lambda: server._update("a30", description="- Goal: Reworded\n- As bullets", sender=MAIN))
prose_item(31)
passes("an update that carries only a short next passes although the stored description is prose", lambda: server._update("a31", next="home-other: do it", dropped=[1], sender=MAIN))
check("…and the stored prose description is untouched", server._load("a31")["description"] == "A thing. It lives here. Done when done.")

# ---- 4. a close judges its new description
prose_item(32); prose_item(33); prose_item(34)
refused("complete with a prose description is refused", lambda: server.stackshot_complete("a32", outcome="done", reason="finished", description="It is done and in use.", sender=MAIN), "not a `- ` bullet")
check("…and the item stays open", server._load("a32")["status"] == "open")
passes("complete with bullets passes", lambda: server.stackshot_complete("a32", outcome="done", reason="finished", outcome_text="- It is done\n- In use", sender=MAIN))
refused("update with status=completed and a prose description is refused",
        lambda: server._update("a33", status="completed", outcome="done", reason="finished", description="Done and in use.", sender=MAIN), "not a `- ` bullet")
refused("complete with a bullet over 120 characters is refused", lambda: server.stackshot_complete("a34", outcome="done", reason="finished", outcome_text=bullet(130), sender=MAIN),
        "outcome_text bullet is 130 characters")

# ---- 5. the limits come from the config
d_cfg, n_cfg = server._cfg.CFG["description"], server._cfg.CFG["metadata"]["next"]
was = (d_cfg.get("max_lines"), d_cfg.get("line_max"), n_cfg.get("line_max"))
check("the shipped defaults: 8 lines, 120 characters, next 200", was == (8, 120, 200), was)
d_cfg["max_lines"], d_cfg["line_max"], n_cfg["line_max"] = 2, 30, 40
refused("config: a bullet over a smaller line_max is refused with that limit", lambda: create(bullet(31)), "31 characters", "limit is 30", "2 lines of 30")
passes("config: a bullet at the smaller line_max passes", lambda: create(bullet(30)))
refused("config: a smaller max_lines is refused with that limit", lambda: create("- a\n- b\n- c"), "description has 3 lines", "limit is 2")
refused("config: a smaller next line_max is refused with that limit", lambda: create("- a", next="home-other: " + "w" * 41), "a line of next is 41 characters", "limit is 40")
passes("config: …and a line of exactly that many characters after the prefix passes", lambda: create("- a", next="home-other: " + "w" * 40))
d_cfg["max_lines"], d_cfg["line_max"], n_cfg["line_max"] = 10, 200, 300
passes("config: larger limits are respected", lambda: create("\n".join(bullet(200) for _ in range(10)), next="home-other: " + "w" * 280))
d_cfg["max_lines"], d_cfg["line_max"], n_cfg["line_max"] = was
del d_cfg["line_max"], n_cfg["line_max"]
refused("config: without the keys the defaults hold (120)", lambda: create(bullet(121)), "limit is 120")
passes("config: …and 200 for next", lambda: create(next=n_ok))

# ---- 6. the script question route writes bullets and goes through the full gate (the HTTP-level cases are in question_scenario)
d, why = server._question_text("The retry failed twice.\nShould it go on?", "box", "q-script")
check("the question route's text becomes bullets, then the Filed by bullet", why == "" and d == "- The retry failed twice.\n- Should it go on?\n- Filed by q-script (a script on box)", (d, why))
passes("…and that text passes the gate as it is", lambda: server._gate_description(d))
d2, _ = server._question_text("x" * 300, "box", "q-script")
check("a line over the limit is clipped to it, with an ellipsis", d2.splitlines()[0].endswith(" …") and len(d2.splitlines()[0]) <= 120, d2)
passes("…and the clipped text passes the gate", lambda: server._gate_description(d2))
writes.QUESTION.on = True
refused("the gate has no question-route exemption any more: prose is refused while the flag is set", lambda: server._gate_description("Plain prose."), "not a `- ` bullet")
writes.QUESTION.on = False

# ---- 6b. the bullet marker, and the forms of a link
passes("a dash followed by two spaces is a bullet", lambda: create("-  two spaces"))
passes("a dash followed by a tab is a bullet", lambda: create("-\ttabbed"))
refused("a dash with no space after it is not", lambda: create("-no space"), "not a `- ` bullet")
url = "https://example.com/" + "u" * 120
for name, md in (("a titled link", f'[board#1]({url} "a title")'), ("a titled link, single quotes", f"[board#1]({url} 'a title')"),
                 ("an angle destination with a space", f"[board#1](<https://example.com/a b/{'u' * 120}>)"),
                 ("one level of balanced parentheses in the url", f"[board#1](https://en.wikipedia.org/wiki/Foo_(bar){'u' * 120})"),
                 ("a plain link", f"[board#1]({url})")):
    line = f"- See {md} now"
    check(f"fixture: {name} is long raw and short as read", len(line) > 120 and server._visible_len(line) == len("- See board#1 now"), (len(line), server._visible_len(line)))
    passes(f"a link counts by its text only: {name}", lambda line=line: create(line))
refused("…while text after such a link still counts", lambda: create(f'- See [board#1]({url} "a title") ' + "w" * 120), "description bullet is")

# ---- 6c. next: the owner exemption is a whole backtick command, the ask exemption only next's first line without an ask
cmd = f"{server.OWNER}: `" + "x " * 150 + "`"
passes("a long command in one backtick span is not judged", lambda: create(next=cmd))
passes("…also under a bullet marker and with a closing full stop", lambda: create(next="- " + cmd + "."))
refused("a long prose line starting with the owner's name is judged and refused", lambda: create(next=f"{server.OWNER}: " + "please read this and decide " * 10), "a line of next is")
refused("…even when it holds a backtick span", lambda: create(next=f"{server.OWNER}: run `ls` " + "and then think about it " * 10), "a line of next is")
ASKL = "Decide: " + "ship it " * 20 + "· Recommend: ship · Stakes: a week · By: no date"
check("fixture: the ask line is over 200 characters and a valid ask", 200 < len(ASKL) <= 240 and server._rmod.parse_ask(ASKL) is not None, (len(ASKL), server._rmod.parse_ask(ASKL)))
passes("an ask line as next's first line is not judged when the call passes no ask", lambda: create(next=ASKL + "\nhome-other: do it", needs=["decision"], options=[{"label": "A", "line": "a", "recommended": True}, {"label": "B", "line": "b"}]))
refused("…but it is judged when the call also passes an ask", lambda: create(next=ASKL, ask="Decide: x · Recommend: y · Stakes: z · By: no date", needs=["decision"]), "a line of next is")
refused("…and an ask-shaped line that is not the first line is judged", lambda: create(next="home-other: first\n" + ASKL), "a line of next is")

# ---- 6d. clipping is by how a line reads, at a word outside any link and any naked URL (bullet_text, shared by the cold call and the question route)
from stackshot.model import bullet_text as BT
LK = "[board#1](https://github.com/example/board/issues/1)"
long_words = " ".join(["word"] * 40)                    # 199 characters of words
c1 = BT.clip_bullet(f"- {long_words} {LK} tail", 120)
check("clip: a line made long by words is cut at a word, with an ellipsis, within the limit, and the link after the cut is dropped whole",
      c1.endswith(" …") and BT.visible_len(c1) <= 120 and "[board" not in c1 and "](" not in c1 and not c1[:-2].rstrip().endswith("wor"), c1)
c2 = BT.clip_bullet(f"- see {LK} then " + long_words, 120)
check("clip: a link before the cut stays whole (its URL is no length)", c2.startswith(f"- see {LK} then word") and c2.endswith(" …") and BT.visible_len(c2) <= 120, c2)
c3 = BT.clip_bullet("- " + "word " * 21 + LK, 120)          # the link starts inside the room: it goes whole or not at all
check("clip: a link that would be cut is never cut in half", ("](" not in c3) or c3.count("[board#1]") == 1 and LK in c3, c3)
c3b = BT.clip_bullet("- " + "word " * 23 + "[" + "w" * 40 + "](https://example.com/x)", 120)
check("clip: a link that does not fit goes whole", "[www" not in c3b and "](https" not in c3b and c3b.endswith(" …") and BT.visible_len(c3b) <= 120, c3b)
URL = "https://example.com/" + "u" * 300
c4 = BT.clip_bullet("- " + long_words + " " + URL + " tail", 120)
check("clip: next to a naked URL, the URL is not cut and not counted", URL not in c4 and "https://" not in c4 and c4.endswith(" …") and BT.visible_len(c4) <= 120, c4)
c5 = BT.clip_bullet("- " + "word " * 5 + URL + " " + "tail " * 30, 120)
check("clip: a naked URL before the cut stays whole", URL in c5 and c5.endswith(" …") and BT.visible_len(c5) <= 120, c5)
check("clip: a line that already reads within the limit is untouched, however long its URL", BT.clip_bullet("- see " + URL, 120) == "- see " + URL and BT.clip_bullet(long_bullet := bullet(120), 120) == long_bullet)
c6 = BT.clip_bullet("- " + "x" * 300, 120)
check("clip: one word longer than the room is cut inside it", c6.endswith(" …") and BT.visible_len(c6) <= 120 and len(c6) > 100, c6)
c7 = BT.clip_bullet("- [" + "w" * 200 + "](https://example.com/x)", 120)
check("clip: a line that is only a long link keeps the link, its words clipped (never a bare ellipsis bullet)", c7.startswith("- [w") and c7.endswith("](https://example.com/x)") and BT.visible_len(c7) <= 120 and BT.RX_BULLET.match(c7), c7)
check("bullets: more than max_lines: the last kept line says how many more, within max_lines",
      BT.bullets("\n".join(f"l{i}" for i in range(1, 11)), 6, 120).splitlines() == [f"- l{i}" for i in range(1, 6)] + ["- …and 5 more"])
check("bullets: a numbered list, \"e.g.\" and \"Dr.\" are kept as written (no sentence split)",
      BT.bullets("1. First step, e.g. this one.\n2) Dr. Kim signs it.", 8, 120) == "- First step, e.g. this one.\n- Dr. Kim signs it.")
check("question: the clipped bullets pass the gate", all(_ok for _ok in [not server._gate_description(server._question_text("a " * 200 + "\n- " + LK + " " + "b " * 100, "box", "q")[0])]))

# ---- 6e. the question route: empty lines, a long sender
d3, why3 = server._question_text("- \n...\n---\nReal line\n* \n", "box", "q")
check("question: a line that is empty after its marker (or only digits and punctuation) is skipped, not written as an empty bullet", why3 == "" and d3 == "- Real line\n- Filed by q (a script on box)", (d3, why3))
d3b, why3b = server._question_text("- \n…\n", "box", "q")
check("question: a text with no line of words is refused", d3b == "" and "no line of words" in why3b, (d3b, why3b))
d4, why4 = server._question_text("Real line", "box", "s" * 300)
check("question: a long sender is clipped like any bullet, so the text still passes the gate (never a 400)", why4 == "" and d4.splitlines()[-1].endswith(" …") and all(len(l) <= 120 for l in d4.splitlines()), (d4, why4))
passes("…and the gate takes it", lambda: server._gate_description(d4))
d5, why5 = server._question_text("Real line", "m" * 300, "q")
check("question: a long machine name too", why5 == "" and all(len(l) <= 120 for l in d5.splitlines()), d5)
d6, why6 = server._question_text("\n".join(f"line {i}" for i in range(1, 9)), "box", "q")
check("question: more lines than max_lines less one stay refused (not 'and N more')", d6 == "" and "at most 7" in why6, (d6, why6))

# ---- 6f. work stays linear on a 40,000-character line
def timed(name, f, limit=2.0):          # CPU time of this process, so a loaded runner does not fail it
    t0 = time.process_time(); f(); dt_ = time.process_time() - t0
    check(f"timing: {name} takes under {limit:g} s", dt_ < limit, round(dt_, 2))
for name, line in (("brackets", "[" * 40000), ("closing brackets", "]" * 40000), ("open links", "[a](<" * 8000), ("open titles", "[a](x (" * 6000), ("open quotes", '[a](x "' * 6000),
                   ("spaces after a destination", "[a](x" + " " * 40000), ("spaces inside the paren", "[a](" + " " * 40000), ("urls", "http://" * 5700), ("parens", "[a](" + "(" * 40000),
                   ("backticks", "`" * 40000), ("link texts", "[a]" * 13000), ("words", "word " * 8000), ("a command line", server.OWNER + ": `" + "x" * 40000)):
    timed(f"_visible_len on {name}", lambda line=line: server._visible_len(line))
for name, line in (("words", "home-other: " + "word " * 8000), ("brackets", "home-other: " + "[" * 40000), ("open links", "home-other: " + "[a](<" * 8000), ("a command", server.OWNER + ": `" + "x" * 40000), ("spaces", server.OWNER + ":" + " " * 40000 + "x")):
    def run_next(line=line):
        try: server._gate_next(line)
        except server.ToolError: pass
    timed(f"_gate_next on {name}", run_next)
    def run_desc(line=line):
        try: server._gate_description("- " + line)
        except server.ToolError: pass
    timed(f"_gate_description on {name}", run_desc)
t0 = time.process_time(); BT.clip_bullet("- " + "word " * 8000 + "[a](x) " * 2000, 120); BT.bullets("\n".join("word " * 600 for _ in range(8)), 8, 120)
check("timing: clipping a 40k line takes under 2 s of CPU", time.process_time() - t0 < 2.0, round(time.process_time() - t0, 2))
timed("judge on 40,000 lines of ```a (the count is first, the fence scan is one pass)", lambda: BT.judge("\n".join("```a" for _ in range(40000)), 8, 120))
check("judge: 40,000 lines of ```a are refused as lines, at once", BT.judge("\n".join("```a" for _ in range(40000)), 8, 120) == ("lines", "", 40000))
timed("judge on 8 lines that open a fence and never close it, 40k times over a long line", lambda: BT.judge("```a\n" * 7 + "x" * 40000, 8, 120))
timed("judge on a fenced block of 40,000 characters of words", lambda: BT.judge("```\n" + "word " * 8000 + "\n```", 8, 120))
check("judge: fences pair off one at a time (a second block is a block, an unpaired last fence is none)",
      BT.judge("```\nprose a\n```\n- ok\n```x\nprose b\n```\n```\nprose c", 10, 120) == ("marker", "```", 0), BT.judge("```\nprose a\n```\n- ok\n```x\nprose b\n```\n```\nprose c", 10, 120))
check("an owner-name line with spaces round the backticks is the whole-command form; prose after it is not", server._owner_command(f"  {server.OWNER}: `ls -l`  ") and not server._owner_command(f"{server.OWNER}: `ls` and more"), None)

# ---- 6g. the way back, and the re-bullet pass held to the same line limit
from stackshot.model import rebullet as RB
d_cfg["require_bullets"] = False
passes("require_bullets = false: prose passes the bullet check again (the way back)", lambda: create("Plain prose, as before."))
refused("…but the line cap still holds", lambda: create("\n".join(f"line {i}" for i in range(9))), "description has 9 lines")
d_cfg.pop("require_bullets")
refused("…and back on by default", lambda: create("Plain prose, as before."), "not a `- ` bullet")
OLD = "Some old text. " * 20
check("rebullet.verdict with line_max: a bullet the gate would refuse is refused there, naming the limit",
      "a line of" in RB.verdict(OLD, "- " + "Some old text " * 11, line_max=120) and "at most 120" in RB.verdict(OLD, "- " + "Some old text " * 11, line_max=120), RB.verdict(OLD, "- " + "Some old text " * 11, line_max=120))
check("…and with line_max 0 no length is judged", "at most 120" not in RB.verdict(OLD, "- " + "Some old text " * 11, line_max=0), RB.verdict(OLD, "- " + "Some old text " * 11, line_max=0))
check("the rubric names the character limit it is given", "about 120 characters" in RB.RUBRIC.format(lines=8, chars=120) and "about 200 characters" in RB.RUBRIC.format(lines=8, chars=200))

# ---- 6h. the board item round 3: one judgement for the gate and the re-bullet pass, a clip that tests the finished string, the switches
import random
QL = "> " + "He said that we should do it " * 5                  # a quote of about 150 characters
check("judge: a `>` quote line is exempt from the marker (and a short one passes the gate)", BT.judge("- ok\n> his words", 8, 120) is None)
passes("gate: a short `>` quote line is taken", lambda: server._gate_description("- ok\n> his words"))
refused("gate: a `>` quote line still gets the length check", lambda: server._gate_description("- ok\n" + QL), "characters, the limit is 120")
FENCE = "- ok\n```\n" + "x" * 300 + "\nplain prose in a fence\n```"
check("judge: a fenced block, fence lines included, is held to nothing but the line count", BT.judge(FENCE, 8, 120) is None)
passes("gate: a fenced block with a long line and prose is taken", lambda: server._gate_description(FENCE))
refused("gate: a fenced block counts toward max_lines", lambda: server._gate_description("```\n" + "\n".join("x" for _ in range(8)) + "\n```"), "lines, the limit is 8")
refused("gate: an unclosed fence is no fence", lambda: server._gate_description("- ok\n```\nprose"), "not a `- ` bullet")
refused("gate: an indented line that is not a bullet is prose", lambda: server._gate_description("- ok\n    continued text"), "not a `- ` bullet")
passes("gate: an indented bullet is a bullet", lambda: server._gate_description("- ok\n    - nested"))
# parallel bullets nest under one parent, indented two spaces; a nested line is a line for max_lines and is held to line_max like any other
NEST = "- Three batches\n  - Batch 1: the gate\n  - Batch 2: the prompt\n  - Batch 3: the tests"
check("judge: a parent with three `  - ` children passes", BT.judge(NEST, 8, 120) is None, BT.judge(NEST, 8, 120))
passes("gate: a parent with three `  - ` children is taken", lambda: server._gate_description(NEST))
check("judge: a nested line counts as a line for max_lines", BT.judge(NEST, 4, 120) is None and BT.judge(NEST, 3, 120) == ("lines", "", 4), BT.judge(NEST, 3, 120))
check("judge: a nested line is held to line_max, indent not counted", BT.judge("- Parent\n  " + bullet(120), 8, 120) is None and BT.judge("- Parent\n  " + bullet(121), 8, 120) == ("long", "  " + bullet(121), 121), BT.judge("- Parent\n  " + bullet(121), 8, 120))
refused("gate: a nested line over the limit is refused", lambda: server._gate_description("- Parent\n  " + bullet(121)), "bullet is 121 characters")
refused("gate: the refusal hint says parallel bullets nest under a parent, indented two spaces", lambda: create("A thing. It lives here."), "parallel bullets such as batches, steps or parts go under one parent bullet, indented two spaces")
check("rebullet.verdict: a rewrite that nests its items two spaces under the lead is accepted", RB.verdict("Three batches. Batch 1 the gate. Batch 2 the prompt. Batch 3 the tests.", "- Three batches\n  - Batch 1 the gate\n  - Batch 2 the prompt\n  - Batch 3 the tests", line_max=120) == "", RB.verdict("Three batches. Batch 1 the gate. Batch 2 the prompt. Batch 3 the tests.", "- Three batches\n  - Batch 1 the gate\n  - Batch 2 the prompt\n  - Batch 3 the tests", line_max=120))
check("rebullet.parse keeps the indent of a nested bullet", RB.parse("- Parent\n  - Child one\n  - Child two") == "- Parent\n  - Child one\n  - Child two", RB.parse("- Parent\n  - Child one\n  - Child two"))
for name, txt in (("a quote line", "- ok\n> his words"), ("a long quote line", "- ok\n" + QL), ("a fence", FENCE), ("an indented line", "- ok\n  more prose"), ("prose", "Plain prose."),
                  ("a long bullet", "- " + "word " * 40), ("nine lines", "\n".join("- x" for _ in range(9))), ("a clean text", "- a\n- b")):
    try:
        server._gate_description(txt); gate_says = True
    except server.ToolError:
        gate_says = False
    form = RB.verdict("Zq " + txt, txt, line_max=120)       # the old text is the text with a word before it: nothing lost, the form is all that is judged
    refuses = any(k in form for k in ("a line is not a bullet", "a line of", "lines, over"))
    check(f"rebullet.verdict agrees with the gate on {name}", refuses == (not gate_says), (form, gate_says))
QW = ("we should do this and that " * 6).split()
QC = len(QW) // 2
check("rebullet.lost: one `>` quote written as two `- Oliver: \"…\"` bullets, each with its own quotes, is kept", RB.lost("Quote:\n> " + " ".join(QW), '- Oliver: "' + " ".join(QW[:QC]) + '"\n- Oliver: "' + " ".join(QW[QC:]) + '"') == [],
      RB.lost("Quote:\n> " + " ".join(QW), '- Oliver: "' + " ".join(QW[:QC]) + '"\n- Oliver: "' + " ".join(QW[QC:]) + '"'))
check("…and a quote with words changed in one bullet is still lost", RB.lost("Quote:\n> " + " ".join(QW), '- Oliver: "' + " ".join(QW[:QC]) + '"\n- Oliver: "changed ' + " ".join(QW[QC + 1:]) + '"') != [])
QA, QB = " ".join(QW[:16]), " ".join(QW[16:])
check("rebullet.lost: a kept quote over the limit written as `- Oliver: \"…\"` bullets split across lines still counts as kept",
      RB.lost("Quote:\n> " + " ".join(QW), f'- Oliver: "{QA}\n- {QB}"') == [] and RB.lost("Quote:\n> " + " ".join(QW), f'- Oliver: "{QA}"') != [], RB.lost("Quote:\n> " + " ".join(QW), f'- Oliver: "{QA}\n- {QB}"'))
# the clip tests the finished string
URLB = "http://example.com/" + "p" * 60
for n in range(60, 140):
    line = "- " + "w" * n + " " + URLB + " tail words follow here and more"
    c = BT.clip_bullet(line, 120)
    if BT.visible_len(c) > 120 or not BT.RX_BULLET.match(c):
        check("clip: a URL at the boundary (n=%d) gives a finished bullet within the limit" % n, False, c); break
else:
    check("clip: a URL at the boundary, at every offset from 60 to 139, gives a finished bullet within the limit", True)
rnd = random.Random(388)
ALPHA = ["word", "a", "bb", "[link text](https://example.com/a/b)", "[l](<https://x.org/a b>)", "https://example.com/" + "u" * 30, "x" * 70, "…", "(paren)", "[", "]", "(", ")", "e.g.", "1.", "-", "`c`"]
bad = []
for _ in range(3000):
    text = "\n".join(" ".join(rnd.choice(ALPHA) for _ in range(rnd.randint(1, 40))) for _ in range(rnd.randint(1, 12)))
    out = BT.bullets(text, 8, 120)
    if not out:
        continue
    try:
        server._gate_description(out)
    except server.ToolError as e:
        bad.append((text[:200], out[:300], str(e)[:200])); break
check("fuzz: 3000 random texts through bullet_text.bullets all pass _gate_description", not bad, bad)
bad = []
for _ in range(3000):
    line = "- " + " ".join(rnd.choice(ALPHA) for _ in range(rnd.randint(1, 60)))
    for lm in (30, 60, 120):
        c = BT.clip_bullet(line, lm)
        if BT.visible_len(c) > lm:
            bad.append((line[:150], lm, c)); break
    if bad: break
check("fuzz: clip_bullet output reads within its limit (3000 lines, three limits)", not bad, bad)
check("marker: `\\d{1,2}[.)]` is taken off, a longer number is a word", BT.clean_lines("12. twelve\n1234. a year") == ["twelve", "1234. a year"], BT.clean_lines("12. twelve\n1234. a year"))
check("clean_lines: a line with a digit or letter and no more is kept; one with none is dropped", BT.clean_lines("12.\n...\n---\nx") == ["12.", "x"], BT.clean_lines("12.\n...\n---\nx"))
bad = []
URLSHAPES = ["https://example.com/" + "u" * 30 + "[{w}](https://e.org/x)", "[{w}](https://e.org/x)https://example.com/{u}", "- https://a.io/{u}[{w}](https://e.org/x)https://b.io/{u}", "- x[{w}](https://e.org/x)https://b.io/{u}y", "- {u}[{w}](<https://e.org/a b>)http://c.d/{u}"]
for _ in range(3000):
    shape = rnd.choice(URLSHAPES)
    line = ("- " + shape if not shape.startswith("- ") else shape).format(w=" ".join(rnd.choice(["long", "words", "here", "x" * 30]) for _ in range(rnd.randint(10, 60))), u="p" * rnd.randint(1, 40))
    for lm in (40, 80, 120):
        c = BT.clip_bullet(line, lm)
        if BT.visible_len(c) > lm:
            bad.append((line[:150], lm, c)); break
    if bad: break
check("fuzz: clip_bullet on a naked URL touching a link (3000 lines, three limits) reads within its limit", not bad, bad)
bad = []
PRE = ["- ", "- https://a.io/{u}", "- {u}", "- x", "- (", "- http://q.r/{u}("]
POST = ["", "https://b.io/{u}", "y", "http://c.d/{u})", " tail"]
for _ in range(20000):
    w = "".join(rnd.choice("abc ") for _ in range(rnd.randint(1, 200))) if rnd.random() < .5 else "w" * rnd.randint(1, 200)
    line = (rnd.choice(PRE) + "[" + w + "](https://e.org/" + "z" * rnd.randint(0, 30) + ")" + rnd.choice(POST)).replace("{u}", "p" * rnd.randint(1, 60))
    lm = rnd.choice([30, 60, 120])
    c = BT.clip_bullet(line, lm)
    if BT.visible_len(c) > lm:
        bad.append((line[:150], lm, c)); break
check("fuzz: clip_bullet on a link with a naked URL touching it, words of every kind (20000 lines), reads within its limit (1235 of 60000 failed before)", not bad, bad)
lone = BT.clip_bullet("- [" + "long words " * 30 + "](https://example.com/page)", 120)
check("clip: a lone long link keeps its link (words clipped) and passes the gate", "](https://example.com/page)" in lone and not server._gate_description(lone), lone)
# the switches: require_bullets = false is the whole way back
d_cfg["require_bullets"] = False
LONGN = "home-other: " + "word " * 60
passes("require_bullets = false: a next line over 200 characters is taken again", lambda: server._gate_next(LONGN))
check("…and read as the old note", "a line over 200 characters" in server._report_note(LONGN), server._report_note(LONGN))
dq, whyq = server._question_text("Real line one\n1. numbered\n" + "z " * 100, "box", "q")
check("require_bullets = false: the question route keeps its old form (lines as written, then a blank line and the plain provenance line)",
      whyq == "" and dq.endswith("\n\nFiled by q (a script on box)") and dq.startswith("Real line one\n1. numbered\n"), (dq[-80:], whyq))
d_cfg.pop("require_bullets")
refused("…and back on by default: the next line is refused again", lambda: server._gate_next(LONGN), "a line of next is")
check("…and the question route bullets again", server._question_text("Real line one", "box", "q")[0].startswith("- Real line one"))
was_next = n_cfg.get("line_max")
n_cfg["line_max"] = 0
passes("[metadata.next] line_max = 0 means off: a long next line is taken", lambda: server._gate_next(LONGN))
check("…and the old note returns", "a line over 200 characters" in server._report_note(LONGN), server._report_note(LONGN))
passes("…while the description gate still holds", lambda: server._gate_description("- ok"))
if was_next is None: del n_cfg["line_max"]
else: n_cfg["line_max"] = was_next

# ---- 6b. short titles and close reasons: a subject over 80 characters and a close reason over 120 are refused where they are written
subj = lambda n: "[home] " + "s" * (n - 7)         # a subject of exactly n characters, the scope prefix counted
refused("create: a subject of 81 characters is refused, with its length, the limit and the fix", lambda: create(subject=subj(81)),
        "Refused: the subject is 81 characters and the limit is 80", "scope prefix counted", "Shorten it", "description bullets")
passes("create: a subject of 80 characters passes", lambda: create(subject=subj(80)))
def long_subject_item(i, subject):
    now = time.time()
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": "- Goal: A thing\n- It lives here\n- Done when done", "status": "open",
                                                    "updated": now, "state_updated": now, "confirmed": now, "metadata": {"owner": MAIN, "project": STK, "next": "home-other: do it"}}))
OLD_LONG = subj(137)
long_subject_item(60, OLD_LONG)
refused("update: a new subject of 81 characters is refused", lambda: server._update("a60", subject=subj(81), sender=MAIN), "the subject is 81 characters and the limit is 80")
check("…and the stored subject is untouched", json.loads((T / "store/a/60.json").read_text())["subject"] == OLD_LONG)
passes("update: a subject of 80 characters passes", lambda: server._update("a60", subject=subj(80), sender=MAIN))
check("…and it is stored", json.loads((T / "store/a/60.json").read_text())["subject"] == subj(80))
long_subject_item(61, OLD_LONG)
passes("update: an unrelated write on an item with a stored 137-character subject passes", lambda: server._update("a61", priority="p2", sender=MAIN))
passes("…so does one that sets the very subject it has", lambda: server._update("a61", subject=OLD_LONG, sender=MAIN))
check("…and the stored subject stays as it was", json.loads((T / "store/a/61.json").read_text())["subject"] == OLD_LONG)
refused("update: a subject without a scope prefix is still refused first", lambda: server._update("a61", subject="no prefix", sender=MAIN), "subject must start with one of")
s_cfg = server._cfg.CFG["subject"]; was_s = s_cfg.get("max_length")
s_cfg["max_length"] = 30
refused("config: [subject] max_length is the limit", lambda: create(subject=subj(31)), "is 31 characters and the limit is 30")
passes("…and 30 passes", lambda: create(subject=subj(30)))
if was_s is None: del s_cfg["max_length"]
else: s_cfg["max_length"] = was_s
del s_cfg["max_length"]
passes("…and with no key the default is 80", lambda: create(subject=subj(80)))
refused("…81 refused by the default", lambda: create(subject=subj(81)), "the limit is 80")
s_cfg["max_length"] = was_s if was_s is not None else 80

why = lambda n: "r" * n
for i in (62, 63, 64, 65, 66):
    long_subject_item(i, "[home] close me")
GOOD = "- It is done\n- In use"
refused("complete: a reason of 121 characters is refused, with its length, the limit and the fix", lambda: server.stackshot_complete("a62", outcome="done", reason=why(121), outcome_text=GOOD, sender=MAIN),
        "Refused: the reason is 121 characters and the limit is 120", "Shorten it", "outcome_text bullets")
check("…and the item stays open", json.loads((T / "store/a/62.json").read_text())["status"] == "open")
passes("complete: a reason of 120 characters passes", lambda: server.stackshot_complete("a62", outcome="done", reason=why(120), outcome_text=GOOD, sender=MAIN))
refused("update status=completed: a reason of 121 characters is refused", lambda: server._update("a63", status="completed", outcome="done", reason=why(121), outcome_text=GOOD, sender=MAIN),
        "the reason is 121 characters and the limit is 120")
passes("update status=completed: a reason of 120 characters passes", lambda: server._update("a63", status="completed", outcome="done", reason=why(120), outcome_text=GOOD, sender=MAIN))
# a reopen is unaffected, and an old close with a long stored reason is left as it is
d64 = json.loads((T / "store/a/64.json").read_text()); d64["status"] = "completed"; d64["metadata"] = {"owner": MAIN, "project": STK, "outcome": "done", "reason": why(300)}
(T / "store/a/64.json").write_text(json.dumps(d64))
passes("a reopen is unaffected by a stored 300-character reason", lambda: server._update("a64", status="open", next=f"{MAIN}: take it up again", sender=MAIN))
check("…the reason is dropped by the reopen as before", "reason" not in json.loads((T / "store/a/64.json").read_text())["metadata"])
# the server's own closes keep to the limit by cutting, and never fail
check("_fit: text within the limit is returned as one line", server._fit("a  b\nc", 10) == "a b c")
fitted = server._fit("word " * 100, 120)
check("_fit: text over the limit is cut at a word, with the ellipsis, within the limit", len(fitted) <= 120 and fitted.endswith(" …") and server._fit("x" * 300, 120).endswith(" …") and len(server._fit("x" * 300, 120)) == 120, (len(fitted), fitted))
check("_fit: 0 means no limit", len(server._fit("word " * 100, 0)) == 499)
long_subject_item(65, "[home] done check")
d65 = json.loads((T / "store/a/65.json").read_text()); d65["metadata"]["check"] = "item_closed a67"; (T / "store/a/65.json").write_text(json.dumps(d65))
was_label = server._check_label; server._check_label = lambda c: "label " * 60
try:
    it65 = server._load("a65"); telling.tell_check_closed = lambda *a, **k: None; server._release_after = lambda *a, **k: None
    server._check_close("a65", it65, "item_closed a67", time.time())
finally:
    server._check_label = was_label
m65 = json.loads((T / "store/a/65.json").read_text())
check("a done check's close writes a reason within 120 characters, starting with the check's words", m65["status"] == "completed" and m65["metadata"]["outcome"] == "done"
      and m65["metadata"]["reason"].startswith("done check passed: label") and len(m65["metadata"]["reason"]) <= 120, m65["metadata"].get("reason"))
it66 = server._load("a66"); server._watch_close(it66, "dropped on his answer on the board: " + "something " * 40, time.time())
check("a watcher's drop writes a reason within 120 characters", it66["status"] == "completed" and 0 < len(it66["metadata"]["reason"]) <= 120, it66["metadata"].get("reason"))

# ---- 7. the tool texts state the limits
TOOLS = {t.name: t.description or "" for t in __import__("asyncio").run(server.mcp.list_tools())}
for tool in ("create", "update", "complete"):
    check(f"{tool}: the description says `- ` bullets and 120 characters", "`- ` bullets" in TOOLS[tool] and "120 characters" in TOOLS[tool], TOOLS[tool][:300])
check("create and update: …and that a next line is refused unless <= 200 characters after its prefix and <= 280 in all", all("refused unless it is <= 200 characters after its `<actor>: ` prefix, and <= 280 in all" in TOOLS[t] for t in ("create", "update")))
check("create and update: …and that parallel bullets go under one parent bullet, indented two spaces", all("go under one parent bullet, indented two spaces" in TOOLS[t] for t in ("create", "update")), TOOLS["create"][:400])
check("the re-bullet rubric tells the model to nest parallel items two spaces under a parent", "Parallel items" in RB.RUBRIC and "indented two spaces" in RB.RUBRIC and "under one parent bullet" in RB.RUBRIC, None)
check("the connector's instructions carry the nesting clause", "parallel bullets under one parent, indented two spaces" in server.mcp.instructions, None)
check("bare_urls: a naked http(s) URL is found, without its closing punctuation", BT.bare_urls("- see https://example.com/a. And (http://example.org/b), HTTPS://EXAMPLE.NET/c") == ["https://example.com/a", "http://example.org/b", "HTTPS://EXAMPLE.NET/c"], BT.bare_urls("- see https://example.com/a."))
check("bare_urls: a URL in [words](url), an image, a code span or a closed fence is not one", BT.bare_urls("- [the doc](https://example.com/a) and ![i](https://example.com/i.png) and `curl https://example.com/b`\n```sh\ncurl https://example.com/c\n```\n- [w](https://en.example.org/w_(x))") == [])
check("bare_urls: <url> is found, an unclosed fence is no fence, a bare URL beside a link is found", BT.bare_urls("- <https://example.com/a>") == ["https://example.com/a"] and BT.bare_urls("```\nhttps://example.com/a\n- x") == ["https://example.com/a"]
      and BT.bare_urls("- [w](https://example.com/a) then https://example.com/b") == ["https://example.com/b"])
check("bare_urls: no URL, an empty text and a long line of brackets cost nothing", BT.bare_urls("") == [] and BT.bare_urls("- no link, example.com is plain") == [] and BT.bare_urls("[" * 40000 + "`" * 40000) == [])
check("create and update: the tool text states the 80-character subject limit", all("at most 80 characters" in TOOLS[t] and "prefix counted" in TOOLS[t] for t in ("create", "update")), TOOLS["create"][:300])
check("complete and update: …and the 120-character reason limit", all("at most 120 characters (longer is refused" in TOOLS[t] for t in ("complete", "update")), TOOLS["complete"][:300])
check("the connector's instructions state them", "`- ` bullets" in server.mcp.instructions and "120 characters" in server.mcp.instructions)

print(("ok" if not fails else "FAILED") + f": bullets scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
