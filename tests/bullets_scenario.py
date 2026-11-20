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
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import ids as _model_ids; from stackshot.service import question as question_svc
from stackshot.web.tools import notes as _notes_tool
from stackshot.service import wait_gates as wait_gates_svc
from stackshot.service import update as _update_svc
from stackshot.service import store as _service_store
from stackshot.core import config as _cfg
from stackshot.core import instance as _core_instance
from stackshot.web import render as _rmod
from fastmcp.exceptions import ToolError
from stackshot.web import publish as _web_publish
from stackshot.model import field_gates as _fg
from stackshot.service import checks as checks_svc
from stackshot.service import wakes as wakes_svc
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import create as _wt_create
from stackshot.service import telling
from stackshot.service import writes
_cfg.CFG.setdefault("model", {})["guards"] = False      # fixture owners the fleet does not know; the write guards have their own suite
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None

MAIN = "falcon-main"
STK = "projects/example"
def goaled(desc):
    """the goal gate reads the first bullet; these tests are about the other limits, so a first bullet that is not a Goal bullet gets the label (a text that is no bullet is left to the form gate)"""
    return re.sub(r"^(-[ \t]+)(?!Goal:)", r"\1Goal: ", desc, count=1)
def create(desc="- Goal: A thing\n- It lives here\n- Done when done", **kw):
    desc = goaled(desc)
    if not kw.get("next") and "ask" not in kw:
        kw["next"] = f"{MAIN}: carry on"          # an open item has an open step (N6): a create with no next of its own gets a named one
    r = _wt_create.stackshot_create(subject=kw.pop("subject", "[home] a thing"), description=desc, project=STK, owner=MAIN, **kw)
    return r, _model_ids._norm_id(r.split()[1])
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except ToolError as e:
        check(name, all(w in str(e) for w in want), str(e))
def passes(name, f):
    try:
        f(); check(name, True)
    except ToolError as e:
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
check("fixture: the link-heavy bullet is over 120 raw and within 120 as read", len(long_link) > 120 and _fg._visible_len(long_link) <= 120, (len(long_link), _fg._visible_len(long_link)))
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
check("fixture: the three-word name is a prefix of 304 characters, so the action alone is under the limit", _fg._next_len(WORDY + "act") == 3 and len(WORDY) == 304, (_fg._next_len(WORDY + "act"), len(WORDY)))
refused("a line of 304+ characters behind a three-word prefix is refused by the whole-line cap", lambda: create(next=WORDY + "act"), "a line of next is 307 characters in all", "limit for the whole line is 280", "one short line per next action")
passes("a line of exactly 280 characters in all passes (80 of prefix, 200 of action)", lambda: create(next="falcon-main-" + "x" * 60 + ": " + "w" * 200))
refused("…and 281 in all are refused, though the action is within 200", lambda: create(next="falcon-main-" + "x" * 67 + ": " + "w" * 200), "a line of next is 281 characters in all", "limit for the whole line is 280")
passes("…a bullet marker and bold marks in front of the actor are part of the prefix", lambda: create(next="- **home-other:** " + "w" * 200))
refused("…and 201 behind them are refused", lambda: create(next="- **home-other:** " + "w" * 201), "a line of next is 201 characters")
check("_next_len: the characters after the prefix; a line with no prefix, or a label that names no one, counts whole",
      _fg._next_len("home-other: abc") == 3 and _fg._next_len("my-x (builder): abc") == 3 and _fg._next_len("1. **my-x:** abc") == 3 and _fg._next_len("abc def ghi") == 11
      and _fg._next_len("Status: abc") == 11 and _fg._next_len("home-other:abc") == 14 and _fg._next_len(f"home-other: [{'w' * 5}](https://example.com/{'u' * 50}) z") == 7,
      [_fg._next_len(x) for x in ("home-other: abc", "my-x (builder): abc", "1. **my-x:** abc", "abc def ghi", "Status: abc", "home-other:abc")])
refused("a long line among short ones is refused", lambda: create(next="home-other: first\n- " + n_long), "a line of next is")
passes("a link in next counts by its text", lambda: create(next=f"home-other: read {link} " + "w" * 150))
passes("a long command line of the owner's is not judged", lambda: create(next=f"{_core_instance.OWNER}: `" + "x " * 150 + "`"))
r, g = create(next="ops-x: merged 0109c0de0, 12 tests passed")
check("the report notes stay notes: the item is created and the reply carries the note", "next reads like a report" in r and _service_store._path(g).exists(), r)
check("a line over 200 characters is no longer a note", _notes_tool._report_note("ops-x: " + "word " * 60) == "", _notes_tool._report_note("ops-x: " + "word " * 60))

# ---- 3. updates judge only the text written in the call
prose_item(30)
passes("an update without description or next on a prose item is not refused", lambda: _update_svc._update("a30", priority="p2", sender=MAIN))
passes("…nor one that sets a due date", lambda: _update_svc._update("a30", due="2026-12-01", sender=MAIN))
check("…and the stored text is untouched", _service_store._load("a30")["description"] == "A thing. It lives here. Done when done." and len(_service_store._load("a30")["metadata"]["next"]) > 200)
refused("an update that carries a prose description is refused", lambda: _update_svc._update("a30", description="Reworded. Still prose.", sender=MAIN), "not a `- ` bullet")
refused("an update that carries a long next line is refused", lambda: _update_svc._update("a30", next=n_long, sender=MAIN), "a line of next is 201 characters")
passes("an update that carries a bullet description passes", lambda: _update_svc._update("a30", description="- Goal: Reworded\n- As bullets", sender=MAIN))
prose_item(31)
passes("an update that carries only a short next passes although the stored description is prose", lambda: _update_svc._update("a31", next="home-other: do it", dropped=[1], sender=MAIN))
check("…and the stored prose description is untouched", _service_store._load("a31")["description"] == "A thing. It lives here. Done when done.")

# ---- 4. a close judges its new description
prose_item(32); prose_item(33); prose_item(34)
refused("complete with a prose description is refused", lambda: _wt_complete.stackshot_complete("a32", outcome="done", reason="finished", description="It is done and in use.", sender=MAIN), "not a `- ` bullet")
check("…and the item stays open", _service_store._load("a32")["status"] == "open")
passes("complete with bullets passes", lambda: _wt_complete.stackshot_complete("a32", outcome="done", reason="finished", outcome_text="- It is done\n- In use", sender=MAIN))
refused("update with status=completed and a prose description is refused",
        lambda: _update_svc._update("a33", status="completed", outcome="done", reason="finished", description="Done and in use.", sender=MAIN), "not a `- ` bullet")
refused("complete with a bullet over 120 characters is refused", lambda: _wt_complete.stackshot_complete("a34", outcome="done", reason="finished", outcome_text=bullet(130), sender=MAIN),
        "outcome_text bullet is 130 characters")

# ---- 5. the limits come from the config
d_cfg, n_cfg = _cfg.CFG["description"], _cfg.CFG["metadata"]["next"]
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
d, why = question_svc._question_text("The retry failed twice.\nShould it go on?", "box", "q-script")
check("the question route's text becomes bullets, then the Filed by bullet", why == "" and d == "- The retry failed twice.\n- Should it go on?\n- Filed by q-script (a script on box)", (d, why))
passes("…and that text passes the gate as it is", lambda: _fg._gate_description(d))
d2, _ = question_svc._question_text("x" * 300, "box", "q-script")
check("a line over the limit is clipped to it, with an ellipsis", d2.splitlines()[0].endswith(" …") and len(d2.splitlines()[0]) <= 120, d2)
passes("…and the clipped text passes the gate", lambda: _fg._gate_description(d2))
writes.QUESTION.on = True
refused("the gate has no question-route exemption any more: prose is refused while the flag is set", lambda: _fg._gate_description("Plain prose."), "not a `- ` bullet")
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
    check(f"fixture: {name} is long raw and short as read", len(line) > 120 and _fg._visible_len(line) == len("- See board#1 now"), (len(line), _fg._visible_len(line)))
    passes(f"a link counts by its text only: {name}", lambda line=line: create(line))
refused("…while text after such a link still counts", lambda: create(f'- See [board#1]({url} "a title") ' + "w" * 120), "description bullet is")

# ---- 6c. next: the owner exemption is a whole backtick command, the ask exemption only next's first line without an ask
cmd = f"{_core_instance.OWNER}: `" + "x " * 150 + "`"
passes("a long command in one backtick span is not judged", lambda: create(next=cmd))
passes("…also under a bullet marker and with a closing full stop", lambda: create(next="- " + cmd + "."))
refused("a long prose line starting with the owner's name is judged and refused", lambda: create(next=f"{_core_instance.OWNER}: " + "please read this and decide " * 10), "a line of next is")
refused("…even when it holds a backtick span", lambda: create(next=f"{_core_instance.OWNER}: run `ls` " + "and then think about it " * 10), "a line of next is")
ASKL = "Decide: " + "ship it " * 20 + "· Recommend: ship · Stakes: a week · By: no date"
check("fixture: the ask line is over 200 characters and a valid ask", 200 < len(ASKL) <= 240 and _rmod.parse_ask(ASKL) is not None, (len(ASKL), _rmod.parse_ask(ASKL)))
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
check("question: the clipped bullets pass the gate", all(_ok for _ok in [not _fg._gate_description(question_svc._question_text("a " * 200 + "\n- " + LK + " " + "b " * 100, "box", "q")[0])]))

# ---- 6e. the question route: empty lines, a long sender
d3, why3 = question_svc._question_text("- \n...\n---\nReal line\n* \n", "box", "q")
check("question: a line that is empty after its marker (or only digits and punctuation) is skipped, not written as an empty bullet", why3 == "" and d3 == "- Real line\n- Filed by q (a script on box)", (d3, why3))
d3b, why3b = question_svc._question_text("- \n…\n", "box", "q")
check("question: a text with no line of words is refused", d3b == "" and "no line of words" in why3b, (d3b, why3b))
d4, why4 = question_svc._question_text("Real line", "box", "s" * 300)
check("question: a long sender is clipped like any bullet, so the text still passes the gate (never a 400)", why4 == "" and d4.splitlines()[-1].endswith(" …") and all(len(l) <= 120 for l in d4.splitlines()), (d4, why4))
passes("…and the gate takes it", lambda: _fg._gate_description(d4))
d5, why5 = question_svc._question_text("Real line", "m" * 300, "q")
check("question: a long machine name too", why5 == "" and all(len(l) <= 120 for l in d5.splitlines()), d5)
d6, why6 = question_svc._question_text("\n".join(f"line {i}" for i in range(1, 9)), "box", "q")
check("question: more lines than max_lines less one stay refused (not 'and N more')", d6 == "" and "at most 7" in why6, (d6, why6))

# ---- 6f. work stays linear on a 40,000-character line
def timed(name, f, limit=2.0):          # CPU time of this process, so a loaded runner does not fail it
    t0 = time.process_time(); f(); dt_ = time.process_time() - t0
    check(f"timing: {name} takes under {limit:g} s", dt_ < limit, round(dt_, 2))
for name, line in (("brackets", "[" * 40000), ("closing brackets", "]" * 40000), ("open links", "[a](<" * 8000), ("open titles", "[a](x (" * 6000), ("open quotes", '[a](x "' * 6000),
                   ("spaces after a destination", "[a](x" + " " * 40000), ("spaces inside the paren", "[a](" + " " * 40000), ("urls", "http://" * 5700), ("parens", "[a](" + "(" * 40000),
                   ("backticks", "`" * 40000), ("link texts", "[a]" * 13000), ("words", "word " * 8000), ("a command line", _core_instance.OWNER + ": `" + "x" * 40000)):
    timed(f"_visible_len on {name}", lambda line=line: _fg._visible_len(line))
for name, line in (("words", "home-other: " + "word " * 8000), ("brackets", "home-other: " + "[" * 40000), ("open links", "home-other: " + "[a](<" * 8000), ("a command", _core_instance.OWNER + ": `" + "x" * 40000), ("spaces", _core_instance.OWNER + ":" + " " * 40000 + "x")):
    def run_next(line=line):
        try: _fg._gate_next(line)
        except ToolError: pass
    timed(f"_gate_next on {name}", run_next)
    def run_desc(line=line):
        try: _fg._gate_description("- " + line)
        except ToolError: pass
    timed(f"_gate_description on {name}", run_desc)
t0 = time.process_time(); BT.clip_bullet("- " + "word " * 8000 + "[a](x) " * 2000, 120); BT.bullets("\n".join("word " * 600 for _ in range(8)), 8, 120)
check("timing: clipping a 40k line takes under 2 s of CPU", time.process_time() - t0 < 2.0, round(time.process_time() - t0, 2))
timed("judge on 40,000 lines of ```a (the count is first, the fence scan is one pass)", lambda: BT.judge("\n".join("```a" for _ in range(40000)), 8, 120))
check("judge: 40,000 lines of ```a are refused as lines, at once", BT.judge("\n".join("```a" for _ in range(40000)), 8, 120) == ("lines", "", 40000))
timed("judge on 8 lines that open a fence and never close it, 40k times over a long line", lambda: BT.judge("```a\n" * 7 + "x" * 40000, 8, 120))
timed("judge on a fenced block of 40,000 characters of words", lambda: BT.judge("```\n" + "word " * 8000 + "\n```", 8, 120))
check("judge: fences pair off one at a time (a second block is a block, an unpaired last fence is none)",
      BT.judge("```\nprose a\n```\n- ok\n```x\nprose b\n```\n```\nprose c", 10, 120) == ("marker", "```", 0), BT.judge("```\nprose a\n```\n- ok\n```x\nprose b\n```\n```\nprose c", 10, 120))
check("an owner-name line with spaces round the backticks is the whole-command form; prose after it is not", _fg._owner_command(f"  {_core_instance.OWNER}: `ls -l`  ") and not _fg._owner_command(f"{_core_instance.OWNER}: `ls` and more"), None)

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
passes("gate: a short `>` quote line is taken", lambda: _fg._gate_description("- ok\n> his words"))
refused("gate: a `>` quote line still gets the length check", lambda: _fg._gate_description("- ok\n" + QL), "characters, the limit is 120")
FENCE = "- ok\n```\n" + "x" * 300 + "\nplain prose in a fence\n```"
check("judge: a fenced block, fence lines included, is held to nothing but the line count", BT.judge(FENCE, 8, 120) is None)
passes("gate: a fenced block with a long line and prose is taken", lambda: _fg._gate_description(FENCE))
refused("gate: a fenced block counts toward max_lines", lambda: _fg._gate_description("```\n" + "\n".join("x" for _ in range(8)) + "\n```"), "lines, the limit is 8")
refused("gate: an unclosed fence is no fence", lambda: _fg._gate_description("- ok\n```\nprose"), "not a `- ` bullet")
refused("gate: an indented line that is not a bullet is prose", lambda: _fg._gate_description("- ok\n    continued text"), "not a `- ` bullet")
passes("gate: an indented bullet is a bullet", lambda: _fg._gate_description("- ok\n    - nested"))
# parallel bullets nest under one parent, indented two spaces; a nested line is a line for max_lines and is held to line_max like any other
NEST = "- Three batches\n  - Batch 1: the gate\n  - Batch 2: the prompt\n  - Batch 3: the tests"
check("judge: a parent with three `  - ` children passes", BT.judge(NEST, 8, 120) is None, BT.judge(NEST, 8, 120))
passes("gate: a parent with three `  - ` children is taken", lambda: _fg._gate_description(NEST))
check("judge: a nested line counts as a line for max_lines", BT.judge(NEST, 4, 120) is None and BT.judge(NEST, 3, 120) == ("lines", "", 4), BT.judge(NEST, 3, 120))
check("judge: a nested line is held to line_max, indent not counted", BT.judge("- Parent\n  " + bullet(120), 8, 120) is None and BT.judge("- Parent\n  " + bullet(121), 8, 120) == ("long", "  " + bullet(121), 121), BT.judge("- Parent\n  " + bullet(121), 8, 120))
refused("gate: a nested line over the limit is refused", lambda: _fg._gate_description("- Parent\n  " + bullet(121)), "bullet is 121 characters")
refused("gate: the refusal hint says parallel bullets nest under a parent, indented two spaces", lambda: create("A thing. It lives here."), "parallel bullets such as batches, steps or parts go under one parent bullet, indented two spaces")
check("rebullet.verdict: a rewrite that nests its items two spaces under the lead is accepted", RB.verdict("Three batches. Batch 1 the gate. Batch 2 the prompt. Batch 3 the tests.", "- Three batches\n  - Batch 1 the gate\n  - Batch 2 the prompt\n  - Batch 3 the tests", line_max=120) == "", RB.verdict("Three batches. Batch 1 the gate. Batch 2 the prompt. Batch 3 the tests.", "- Three batches\n  - Batch 1 the gate\n  - Batch 2 the prompt\n  - Batch 3 the tests", line_max=120))
check("rebullet.parse keeps the indent of a nested bullet", RB.parse("- Parent\n  - Child one\n  - Child two") == "- Parent\n  - Child one\n  - Child two", RB.parse("- Parent\n  - Child one\n  - Child two"))
for name, txt in (("a quote line", "- ok\n> his words"), ("a long quote line", "- ok\n" + QL), ("a fence", FENCE), ("an indented line", "- ok\n  more prose"), ("prose", "Plain prose."),
                  ("a long bullet", "- " + "word " * 40), ("nine lines", "\n".join("- x" for _ in range(9))), ("a clean text", "- a\n- b")):
    try:
        _fg._gate_description(txt); gate_says = True
    except ToolError:
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
        _fg._gate_description(out)
    except ToolError as e:
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
check("clip: a lone long link keeps its link (words clipped) and passes the gate", "](https://example.com/page)" in lone and not _fg._gate_description(lone), lone)
# the switches: require_bullets = false is the whole way back
d_cfg["require_bullets"] = False
LONGN = "home-other: " + "word " * 60
passes("require_bullets = false: a next line over 200 characters is taken again", lambda: _fg._gate_next(LONGN))
check("…and read as the old note", "a line over 200 characters" in _notes_tool._report_note(LONGN), _notes_tool._report_note(LONGN))
dq, whyq = question_svc._question_text("Real line one\n1. numbered\n" + "z " * 100, "box", "q")
check("require_bullets = false: the question route keeps its old form (lines as written, then a blank line and the plain provenance line)",
      whyq == "" and dq.endswith("\n\nFiled by q (a script on box)") and dq.startswith("Real line one\n1. numbered\n"), (dq[-80:], whyq))
d_cfg.pop("require_bullets")
refused("…and back on by default: the next line is refused again", lambda: _fg._gate_next(LONGN), "a line of next is")
check("…and the question route bullets again", question_svc._question_text("Real line one", "box", "q")[0].startswith("- Real line one"))
was_next = n_cfg.get("line_max")
n_cfg["line_max"] = 0
passes("[metadata.next] line_max = 0 means off: a long next line is taken", lambda: _fg._gate_next(LONGN))
check("…and the old note returns", "a line over 200 characters" in _notes_tool._report_note(LONGN), _notes_tool._report_note(LONGN))
passes("…while the description gate still holds", lambda: _fg._gate_description("- ok"))
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
refused("update: a new subject of 81 characters is refused", lambda: _update_svc._update("a60", subject=subj(81), sender=MAIN), "the subject is 81 characters and the limit is 80")
check("…and the stored subject is untouched", json.loads((T / "store/a/60.json").read_text())["subject"] == OLD_LONG)
passes("update: a subject of 80 characters passes", lambda: _update_svc._update("a60", subject=subj(80), sender=MAIN))
check("…and it is stored", json.loads((T / "store/a/60.json").read_text())["subject"] == subj(80))
long_subject_item(61, OLD_LONG)
passes("update: an unrelated write on an item with a stored 137-character subject passes", lambda: _update_svc._update("a61", priority="p2", sender=MAIN))
passes("…so does one that sets the very subject it has", lambda: _update_svc._update("a61", subject=OLD_LONG, sender=MAIN))
check("…and the stored subject stays as it was", json.loads((T / "store/a/61.json").read_text())["subject"] == OLD_LONG)
refused("update: a subject without a scope prefix is still refused first", lambda: _update_svc._update("a61", subject="no prefix", sender=MAIN), "subject must start with one of")
s_cfg = _cfg.CFG["subject"]; was_s = s_cfg.get("max_length")
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
refused("complete: a reason of 121 characters is refused, with its length, the limit and the fix", lambda: _wt_complete.stackshot_complete("a62", outcome="done", reason=why(121), outcome_text=GOOD, sender=MAIN),
        "Refused: the reason is 121 characters and the limit is 120", "Shorten it", "outcome_text bullets")
check("…and the item stays open", json.loads((T / "store/a/62.json").read_text())["status"] == "open")
passes("complete: a reason of 120 characters passes", lambda: _wt_complete.stackshot_complete("a62", outcome="done", reason=why(120), outcome_text=GOOD, sender=MAIN))
refused("update status=completed: a reason of 121 characters is refused", lambda: _update_svc._update("a63", status="completed", outcome="done", reason=why(121), outcome_text=GOOD, sender=MAIN),
        "the reason is 121 characters and the limit is 120")
passes("update status=completed: a reason of 120 characters passes", lambda: _update_svc._update("a63", status="completed", outcome="done", reason=why(120), outcome_text=GOOD, sender=MAIN))
# a reopen is unaffected, and an old close with a long stored reason is left as it is
d64 = json.loads((T / "store/a/64.json").read_text()); d64["status"] = "completed"; d64["metadata"] = {"owner": MAIN, "project": STK, "outcome": "done", "reason": why(300)}
(T / "store/a/64.json").write_text(json.dumps(d64))
passes("a reopen is unaffected by a stored 300-character reason", lambda: _update_svc._update("a64", status="open", next=f"{MAIN}: take it up again", sender=MAIN))
check("…the reason is dropped by the reopen as before", "reason" not in json.loads((T / "store/a/64.json").read_text())["metadata"])
# the server's own closes keep to the limit by cutting, and never fail
check("_fit: text within the limit is returned as one line", _fg._fit("a  b\nc", 10) == "a b c")
fitted = _fg._fit("word " * 100, 120)
check("_fit: text over the limit is cut at a word, with the ellipsis, within the limit", len(fitted) <= 120 and fitted.endswith(" …") and _fg._fit("x" * 300, 120).endswith(" …") and len(_fg._fit("x" * 300, 120)) == 120, (len(fitted), fitted))
check("_fit: 0 means no limit", len(_fg._fit("word " * 100, 0)) == 499)
long_subject_item(65, "[home] done check")
d65 = json.loads((T / "store/a/65.json").read_text()); d65["metadata"]["check"] = "item_closed a67"; (T / "store/a/65.json").write_text(json.dumps(d65))
was_label = checks_svc.check_label; checks_svc.check_label = lambda c: "label " * 60
try:
    it65 = _service_store._load("a65"); telling.tell_check_closed = lambda *a, **k: None; wakes_svc.release_after = lambda *a, **k: None
    checks_svc.check_close("a65", it65, "item_closed a67", time.time())
finally:
    checks_svc.check_label = was_label
m65 = json.loads((T / "store/a/65.json").read_text())
check("a done check's close writes a reason within 120 characters, starting with the check's words", m65["status"] == "completed" and m65["metadata"]["outcome"] == "done"
      and m65["metadata"]["reason"].startswith("done check passed: label") and len(m65["metadata"]["reason"]) <= 120, m65["metadata"].get("reason"))
it66 = _service_store._load("a66"); wait_gates_svc._watch_close(it66, "dropped on his answer on the board: " + "something " * 40, time.time())
check("a watcher's drop writes a reason within 120 characters", it66["status"] == "completed" and 0 < len(it66["metadata"]["reason"]) <= 120, it66["metadata"].get("reason"))

# ---- 6k. an update that drops lines of the description says which; the write itself is as before
def upd_desc(gid, desc): return _update_svc._update(gid, description=desc, sender=MAIN)
def stored_desc(gid): return _service_store._load(gid)["description"]
def dropped_lines(out): return [ln for ln in out.splitlines() if ln.startswith("(note: this write dropped")]
OLD = "- Goal: Keep the thing running\n- It lives on the demo-box under /srv/thing\n- Done when the check passes"
_, d1 = create(OLD)
NEW1 = "- Goal: Keep the thing running\n- Done when the check passes"
o1 = upd_desc(d1, NEW1)
check("dropped: one line gone → one note that names the old text", len(dropped_lines(o1)) == 1 and "dropped 1 line of the old description" in o1 and '"It lives on the demo-box under /srv/thing"' in o1, o1)
check("dropped: …the note sits in the reply after the item block, on its own line, and the write is stored as sent", o1.startswith("updated ") and o1.find("(note: this write dropped") > o1.find("\n") > 0 and stored_desc(d1) == NEW1, (o1, stored_desc(d1)))
_, d2 = create(OLD + "\n- A third fact about it")
NEW2 = "- Goal: Keep the thing running\n- Done when the check passes"
o2 = upd_desc(d2, NEW2)
check("dropped: several lines gone → one note with every old line", len(dropped_lines(o2)) == 1 and "dropped 2 lines" in o2 and "It lives on the demo-box under /srv/thing" in o2 and "A third fact about it" in o2, o2)
check("dropped: …stored as sent", stored_desc(d2) == NEW2)
_, d3 = create(OLD + "\n  - a child bullet under it")
NEW3 = "- Done when the check passes\n-   Goal:   Keep the thing running\n- a child bullet under it\n  - It lives on the demo-box under /srv/thing"
o3 = upd_desc(d3, NEW3)
check("dropped: a line that is reordered, re-indented, re-spaced or moved under another bullet is kept → no note", "dropped" not in o3, o3)
check("dropped: …and it is stored as sent", stored_desc(d3) == NEW3, stored_desc(d3))
_, d4 = create(OLD)
NEW4 = "- Goal: Keep the thing running\n- It lives on the demo-box under /srv/other\n- Done when the check passes"
o4 = upd_desc(d4, NEW4)
check("dropped: a reworded line counts as dropped, with its old text, and says so", len(dropped_lines(o4)) == 1 and "dropped 1 line" in o4 and "/srv/thing" in dropped_lines(o4)[0] and "/srv/other" not in dropped_lines(o4)[0]
      and "reworded line counts as dropped" in o4, o4)
check("dropped: …the new wording is what is stored", stored_desc(d4) == NEW4)
o5 = _update_svc._update(d4, priority="p2", sender=MAIN)
check("dropped: an update that does not pass a description gives no note", "dropped" not in o5, o5)
o5b = upd_desc(d4, NEW4)
check("dropped: the description sent back as stored gives no note", "dropped" not in o5b, o5b)
o5c = upd_desc(d4, NEW4 + "\n- Added: a new fact")
check("dropped: a line added and none removed gives no note", "dropped" not in o5c, o5c)
r6, d6 = create(OLD)
check("dropped: a create gives no note", "dropped" not in r6, r6)
_, d7 = create("\n".join(["- Goal: Keep the thing running"] + [f"- Old fact number {i}" for i in range(1, 8)]))
o7 = upd_desc(d7, "- Goal: Keep the thing running")
n7 = dropped_lines(o7)
check("dropped: at most five lines are named, then a count of the rest", len(n7) == 1 and "dropped 7 lines" in n7[0] and "Old fact number 5" in n7[0] and "Old fact number 6" not in n7[0] and n7[0].rstrip(")").endswith("and 2 more"), n7)
check("dropped: …the write is stored as sent", stored_desc(d7) == "- Goal: Keep the thing running")
_, d8 = create("- Goal: Keep the thing running\n- See [the long page](https://link.test/" + "a" * 130 + ") for it")
o8 = upd_desc(d8, "- Goal: Keep the thing running")
n8 = dropped_lines(o8)
check("dropped: a long old line that holds a long link keeps the whole link, the cut runs on to the link's end", len(n8) == 1 and "a" * 130 in n8[0] and "for it" not in n8[0] and n8[0].endswith('…")'), n8)
DOCS = "https://docs.example.com/projects/some/very/long/path/to/the/design/document/with/a/long/name/and/anchor?x=1&y=2#section-nine"
_, d8c = create("- Goal: Keep the thing running\n- Design is in [the design page](" + DOCS + ") now")
n8c = dropped_lines(upd_desc(d8c, "- Goal: Keep the thing running"))
check("dropped: …the review's example: the link target is in the note and the cut falls after the link", len(n8c) == 1 and f"[the design page]({DOCS})" in n8c[0] and "now" not in n8c[0].split("keep:")[1], n8c)
_, d8d = create("- Goal: Keep the thing running\n- A fact first, then words " + "word " * 10 + "and [a link](https://link.test/" + "b" * 50 + ") after that")
n8d = dropped_lines(upd_desc(d8d, "- Goal: Keep the thing running"))
check("dropped: …a word cut that lands inside a link moves to the link's end too", len(n8d) == 1 and "b" * 50 + ")" in n8d[0] and "after that" not in n8d[0], n8d)
_, d8e = create("- Goal: Keep the thing running\n- Long link [here](https://link.test/" + "c" * 600 + ") end")
n8e = dropped_lines(upd_desc(d8e, "- Goal: Keep the thing running"))
q8e = n8e[0].split('keep: "')[1].rstrip(')').rstrip('"') if n8e else ""
check("dropped: …a link past the hard cap is cut plainly at it", len(n8e) == 1 and q8e.endswith(" …") and len(q8e) == _update_svc._DROPPED_NOTE_LINK_MAX + 2 and "c" * 200 in q8e, (n8e, len(q8e)))
check("dropped: the hard cap is a named constant above the line cap", _update_svc._DROPPED_NOTE_LINK_MAX == 300 > _update_svc._DROPPED_NOTE_LINE_MAX)
_, d8f = create("- Goal: Keep the thing running\n- Same fact\n- Same fact")
o8f = upd_desc(d8f, "- Goal: Keep the thing running")
check("dropped: a duplicate line counts once", len(dropped_lines(o8f)) == 1 and "dropped 1 line of" in o8f and o8f.count('"Same fact"') == 1, o8f)
_, d8b = create("- Goal: Keep the thing running\n- " + "word " * 12 + "end")
_cap_was = _update_svc._DROPPED_NOTE_LINE_MAX; _update_svc._DROPPED_NOTE_LINE_MAX = 30
try: n8b = dropped_lines(upd_desc(d8b, "- Goal: Keep the thing running"))
finally: _update_svc._DROPPED_NOTE_LINE_MAX = _cap_was
check("dropped: …the length each old line is cut to is the named constant", len(n8b) == 1 and '"word word word word word word …"' in n8b[0] and "end" not in n8b[0], n8b)
_, d9 = create(OLD)
check("dropped: the constants for the cap are named in the service", _update_svc._DROPPED_NOTE_MAX == 5 and _update_svc._DROPPED_NOTE_LINE_MAX == 120)
r9 = _update_svc._update(d9, status="completed", outcome="done", reason="finished", outcome_text="- It ended well", sender=MAIN)
check("dropped: a close that passes no description gives no note", "dropped" not in r9, r9)

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

# ---- 5. a bullet over the limit is split at the end of its sentences: the write goes through as meant and the reply says so
from stackshot.core import call_log as _CL
def with_fixes(f):
    tok = _CL.begin()
    try:
        out = f()
    except BaseException:
        _CL.end(tok)
        raise
    return out, _CL.end(tok)
S1, S2 = "Goal: " + "a" * 55 + ".", "b" * 60 + "."
r, fx = with_fixes(lambda: create(f"- {S1} {S2}"))
g = r[1]
check("5 a bullet over 120 made of two sentences is split in two bullets and the item is made", _service_store._load(g)["description"] == f"- {S1}\n- {S2}", _service_store._load(g)["description"])
check("5 …the fix is counted once, as description-bullet, and its line names the limit and says no word changed", [k for k, _ in fx] == ["description-bullet"] and "over 120 characters" in fx[0][1] and "no word changed" in fx[0][1], fx)
note = _CL.reply_note(fx)
check("5 …the reply line does not invite a resend: the same bullet sent again would be refused", note.startswith("\n(fixed for you: 1 description bullet") and note.endswith(".)") and "send it again" not in note, note)
r, fx = with_fixes(lambda: create(f"- Goal: " + "c" * 50 + "; " + "d" * 50 + "; " + "e" * 40 + "\n- Second bullet"))
d = _service_store._load(r[1])["description"].splitlines()
check("5 a semicolon ends a clause too: the clauses that fit together stay together, every semicolon stays, the other bullets stay", d == ["- Goal: " + "c" * 50 + "; " + "d" * 50 + ";", "- " + "e" * 40, "- Second bullet"], d)
check("5 …the words and the semicolons are all there", " ".join(" ".join(d).replace("- ", "").split()) == "Goal: " + "c" * 50 + "; " + "d" * 50 + "; " + "e" * 40 + " Second bullet", d)
refused("5 one long sentence has no end to split at: still refused with its length and the fix", lambda: create(bullet(121)), "description bullet is 121 characters", "limit is 120")
refused("5 a clause of its own over the limit: still refused", lambda: create("- Goal: ok. " + "z" * 130), "description bullet is")
refused("5 an end of sentence inside a link is no place to cut: still refused", lambda: create("- Goal: " + "x" * 100 + " [one. two](https://example.com/a) " + "y" * 30), "description bullet is")
refused("5 a split that would pass the line cap is no fix: still refused", lambda: create("\n".join(["- Goal: " + "p" * 60 + ". " + "q" * 60] + [f"- fact {i}" for i in range(7)])), "description bullet is")
refused("5 a long quoted line (his words) is never split: still refused", lambda: create("- Goal: ok\n> " + "w" * 70 + ". " + "v" * 70), "description bullet is")
refused("5 a prose line is still no bullet: refused", lambda: create("- Goal: ok. " + "k" * 50 + "\nplain " + "m" * 130), "not a `- ` bullet")
r, fx = with_fixes(lambda: create("- Goal: ok\n- fits"))
check("5 a description within the form is no fix and no line", fx == [] and _CL.reply_note(fx) == "", fx)
g2 = create()[1]
_, fx = with_fixes(lambda: _update_svc._update(g2, description=f"- {S1} {S2}", sender=MAIN))
check("5 update: the same split on a description written by an update, counted and told", _service_store._load(g2)["description"] == f"- {S1}\n- {S2}" and [k for k, _ in fx] == ["description-bullet"], (_service_store._load(g2)["description"], fx))
refused("5 update: a bullet with nothing to split is refused as before", lambda: _update_svc._update(g2, description=bullet(125), sender=MAIN), "description bullet is 125 characters")
check("5 split_long: None for a text with no long bullet, and the same for a line_max of 0", BT.split_long("- a\n- b", 8, 120) is None and BT.split_long(f"- {S1} {S2}", 8, 0) is None, None)
check("5 split_long: a link and a code span are never cut, a fenced block and a quote are left", BT.split_long("- " + "x" * 60 + ". `a. b` " + "y" * 60, 8, 120) is None or "`a. b`" in BT.split_long("- " + "x" * 60 + ". `a. b` " + "y" * 60, 8, 120)[0], None)

# ---- 5b. the review of the split: children, the History line, the 120 boundary, where a cut is not made, line ends
def hist(gid):
    return [x.get("text") for x in ((_service_store._load(gid).get("metadata") or {}).get("stall") or {}).get("log") or []]
LONG2 = "- Goal: " + "a" * 55 + ". " + "b" * 60 + "."
check("5b children: a long bullet that has an indented bullet under it is not split (the children would end up under the last piece): split_long gives none", BT.split_long(LONG2 + "\n  - child one\n  - child two", 8, 120) is None, None)
refused("5b children: …so the write is refused as before, with the length and the limit", lambda: create(LONG2 + "\n  - child one"), "description bullet is", "limit is 120")
r, fx = with_fixes(lambda: create(f"- Goal: ok\n  - {S1} child\n- {S1} {S2}"))
check("5b children: a long bullet with no children is still split when another bullet has them (the children stay under their own parent)", _service_store._load(r[1])["description"] == f"- Goal: ok\n  - {S1} child\n- {S1}\n- {S2}", (_service_store._load(r[1])["description"], fx))
sp = BT.split_long(f"- {S1} {S2}\n- tail", 8, 120)
check("5b idempotent: the split text keeps the form, and a second split finds nothing to do", sp is not None and BT.judge(sp[0], 8, 120) is None and BT.split_long(sp[0], 8, 120) is None, sp)
check("5b history: a created item records the split in History (the stored text is not the text sent)", any("long bullet" in (t or "") and "split by the server" in (t or "") for t in hist(g)), hist(g))
g3 = create()[1]
before3 = hist(g3)
_update_svc._update(g3, description=f"- {S1} {S2}", sender=MAIN)
check("5b history: an update that is split records it in History, once", [t for t in hist(g3) if t not in before3 and "split by the server" in t] and len([t for t in hist(g3) if "split by the server" in t]) == 1, hist(g3))
g4 = create()[1]
_update_svc._update(g4, description="- Goal: A thing\n- fits", sender=MAIN)
check("5b history: a description that needed no split adds no such line", not any("split by the server" in (t or "") for t in hist(g4)), hist(g4))
# the 120 boundary: a clause of exactly 120 stands, one of 121 is no fix; two clauses that merge to exactly 120 stay one bullet
A117 = "a" * 117 + "."                            # "- " + A117 reads 120
check("5b boundary: a clause that reads exactly 120 is kept (the split is made)", BT.split_long(f"- {A117} " + "c" * 10 + ".", 8, 120) is not None and BT.split_long(f"- {A117} " + "c" * 10 + ".", 8, 120)[0].splitlines()[0] == "- " + A117, None)
check("5b boundary: a clause that reads 121 is no fix", BT.split_long("- " + "a" * 118 + ". " + "c" * 10 + ".", 8, 120) is None, None)
k120 = "- " + "a" * 56 + ". " + "b" * 59 + "."          # two clauses that read 120 together: one bullet; 121 together: two
check("5b boundary: two clauses that together read exactly 120 stay one bullet, one more character and they are two",
      BT.split_long(k120 + " " + "z" * 20 + ".", 8, 120)[0].splitlines()[0] == k120 and BT.split_long("- " + "a" * 56 + ". " + "b" * 60 + ". " + "z" * 60 + ".", 8, 120)[0].splitlines()[:2] == ["- " + "a" * 56 + ".", "- " + "b" * 60 + "."], BT.split_long(k120 + " " + "z" * 20 + ".", 8, 120))
# quotes are left as they are
q = "> " + "w" * 70 + ". " + "v" * 70
res_q = BT.split_long(f"- {S1} {S2}\n{q}", 8, 120)
check("5b quote: a long quoted line stays as written while a long bullet beside it is split", res_q is not None and res_q[0].splitlines()[-1] == q and res_q[0].count("\n") == 2, res_q)
check("5b quote: a text whose only long line is a quote has nothing to split", BT.split_long(q, 8, 120) is None, None)
# where a cut is not made: the guard shows where the only cut there is would be the forbidden one (the pieces would merge back otherwise), so the text is no fix
def pieces(t):
    got = BT.split_long(t, 8, 120)
    return None if got is None else got[0].splitlines()
for w in ("e.g.", "i.e.", "Mr.", "Dr.", "vs."):
    check(f"5b no cut: after {w} (the one cut there is): no fix", pieces("- " + "x" * 60 + f" {w} " + "y" * 60 + ".") is None, pieces("- " + "x" * 60 + f" {w} " + "y" * 60 + "."))
check("5b no cut: after a numbered item like 3.", pieces("- " + "x" * 60 + " step 3. " + "y" * 60 + ".") is None, None)
check("5b no cut: inside parentheses", pieces("- " + "x" * 50 + " (first part. second part " + "y" * 60 + ")") is None, None)
check("5b no cut: after an entity (the semicolon of &amp; is no clause end, the text never comes out as '&amp')", pieces("- " + "x" * 60 + " fish &amp; " + "y" * 60 + ".") is None, None)
check("5b no cut: …and one more spelled with a number, &#38;", pieces("- " + "x" * 60 + " fish &#38; " + "y" * 60 + ".") is None, None)
check("5b no cut: a real sentence end beside them is still a cut (an abbreviation in the text does not stop the split)", pieces("- Use e.g. " + "x" * 10 + ", then " + "y" * 60 + ". " + "z" * 40 + ".") is not None and len(pieces("- Use e.g. " + "x" * 10 + ", then " + "y" * 60 + ". " + "z" * 40 + ".")) == 2, None)
check("5b no cut: …a parenthesis that closes before the full stop is no bar", pieces("- " + "x" * 50 + " (a note) " + "y" * 20 + ". " + "z" * 60 + ".") is not None, None)
check("5b no cut: …and a semicolon after a word still ends a clause", pieces("- " + "x" * 60 + "; " + "y" * 60 + ".") == ["- " + "x" * 60 + ";", "- " + "y" * 60 + "."], pieces("- " + "x" * 60 + "; " + "y" * 60 + "."))
# the re-check of the split: a text whose split would still break the form (a prose line elsewhere) is left as written, and nothing is counted or noted
(got_t, got_n), fx_d = with_fixes(lambda: _fg.fix_long_bullets(LONG2 + "\nplain prose that is no bullet"))
check("5b re-check: a split text that still breaks the form (a later line that is no bullet) is no fix: the text comes back as written, no note, nothing counted", got_t == LONG2 + "\nplain prose that is no bullet" and got_n == "" and fx_d == [], (got_t, got_n, fx_d))
(got_t, got_n), fx_d = with_fixes(lambda: _fg.fix_long_bullets(LONG2))
check("5b fix_long_bullets: the text split, the History line for the item (the count, by the server), and the one counted fix", got_t.count("\n") == 1 and got_n == "description: 1 long bullet split by the server at the end of a sentence" and [k for k, _ in fx_d] == ["description-bullet"], (got_t, got_n, fx_d))
(got_t, got_n), fx_d = with_fixes(lambda: _fg.fix_long_bullets("- Goal: ok\n- fits"))
check("5b fix_long_bullets: a description that fits comes back as it is with no note", got_t == "- Goal: ok\n- fits" and got_n == "" and fx_d == [], (got_t, got_n, fx_d))

# line ends
crlf = f"- {S1} {S2}\r\n- tail\r\n"
res_c = BT.split_long(crlf, 8, 120)
check("5b line ends: a CRLF text is split with CRLF line ends and the same trailing end (nothing but the cut changes)", res_c is not None and res_c[0] == f"- {S1}\r\n- {S2}\r\n- tail\r\n" and "\n" not in res_c[0].replace("\r\n", ""), res_c)
check("5b line ends: an LF text stays LF", BT.split_long(f"- {S1} {S2}\n", 8, 120)[0] == f"- {S1}\n- {S2}\n", None)

# ---- 5c. the second review: the splitter changes the text at the cut and nowhere else; it is linear and refuses a wall of text at once; a resend is no new fix
check("5c exact: a semicolon that ends a piece stays, in the stored text and in the splitter", pieces("- " + "x" * 60 + "; " + "y" * 60 + "; " + "z" * 20) == ["- " + "x" * 60 + ";", "- " + "y" * 60 + "; " + "z" * 20], pieces("- " + "x" * 60 + "; " + "y" * 60 + "; " + "z" * 20))
mixed = f"- {S1} {S2}\r\n- k2\n- k3\r"
check("5c exact: mixed line ends are kept as they were (CRLF, LF and a lone CR), the cut takes its own line's end", BT.split_long(mixed, 8, 120)[0] == f"- {S1}\r\n- {S2}\r\n- k2\n- k3\r", BT.split_long(mixed, 8, 120))
check("5c exact: a line break of another kind (NEL, form feed, U+2028) is kept too, and a last line with no end is cut with the first end the text has",
      BT.split_long(f"- {S1} {S2}\x85- k\x0c- {S1} {S2}", 8, 120)[0] == f"- {S1}\x85- {S2}\x85- k\x0c- {S1}\x85- {S2}" and BT.split_long(f"- k\u2028- {S1} {S2}", 8, 120)[0] == f"- k\u2028- {S1}\u2028- {S2}", BT.split_long(f"- {S1} {S2}\x85- k\x0c- {S1} {S2}", 8, 120))
sp3 = "- " + "a" * 30 + ".   " + "b" * 30 + ".  " + "c" * 60 + "."
check("5c exact: the spaces between two clauses that stay together stay as written (a run of three), the cut drops only the gap it is made at", pieces(sp3) == ["- " + "a" * 30 + ".   " + "b" * 30 + ".", "- " + "c" * 60 + "."], pieces(sp3))
check("5c exact: a golden split: three sentences with an indent, a link and a code span, as the splitter has always cut them",
      pieces("  - " + "a" * 40 + " [one. two](https://example.com/a) `x. y`. " + "b" * 50 + ". " + "c" * 30 + ".") == ["  - " + "a" * 40 + " [one. two](https://example.com/a) `x. y`. " + "b" * 50 + ".", "  - " + "c" * 30 + "."], pieces("  - " + "a" * 40 + " [one. two](https://example.com/a) `x. y`. " + "b" * 50 + ". " + "c" * 30 + "."))
# more abbreviations and emphasis
for w in ("etc.", "U.S.", "No.", "a.m.", "St.", "Inc.", "Jr."):
    check(f"5c no cut: after {w} (the one cut there is): no fix", pieces("- " + "x" * 60 + f" {w} " + "y" * 60 + ".") is None, pieces("- " + "x" * 60 + f" {w} " + "y" * 60 + "."))
check("5c no cut: inside **emphasis** (the stars would be left open on both bullets): no fix", pieces("- **" + "x" * 60 + ". " + "y" * 60 + "** and " + "z" * 30) is None, pieces("- **" + "x" * 60 + ". " + "y" * 60 + "** and " + "z" * 30))
check("5c no cut: …a closed emphasis before the cut is no bar", pieces("- **bold** " + "x" * 60 + ". " + "y" * 60 + ".") == ["- **bold** " + "x" * 60 + ".", "- " + "y" * 60 + "."], pieces("- **bold** " + "x" * 60 + ". " + "y" * 60 + "."))
check("5c no cut: a word that only ends like an abbreviation (Nora.) is a sentence end and is cut", pieces("- " + "x" * 60 + " Nora. " + "y" * 60 + ".") is not None, None)
# the boundary: a bullet that reads exactly line_max is left alone (a `>=` for the test of a long bullet would split it and merge it back, and refuse the whole text)
k120b = "- " + "a" * 58 + ". " + "b" * 57 + "."
long_b = "- " + "c" * 60 + ". " + "d" * 63 + "."
check("5c boundary: a two-sentence bullet that reads exactly 120 stays one bullet beside a longer one that is split", len(k120b) == 120 and pieces(k120b + "\n" + long_b) == [k120b, "- " + "c" * 60 + ".", "- " + "d" * 63 + "."], pieces(k120b + "\n" + long_b))
r, fx = with_fixes(lambda: create("- Goal: ok\n" + k120b + "\n" + long_b))
check("5c boundary: …and the write is made, not refused", _service_store._load(r[1])["description"].splitlines()[-3:] == [k120b, "- " + "c" * 60 + ".", "- " + "d" * 63 + "."], fx)
# a wall of text: refused at once, before any bullet is scanned, and in linear time
class _CountRx:
    def __init__(self, rx): self.rx, self.calls = rx, 0
    def finditer(self, *a, **k): self.calls += 1; return self.rx.finditer(*a, **k)
for label, wall in (("70-character sentences", ("s" * 69 + ". ") * 2900), ("short clauses", "ab. " * 50000), ("links", "[a. b](http://x.y/z) q. " * 8000)):
    wall_t = "- " + wall.strip()
    probe = _CountRx(BT._RX_CLAUSE_END); real_rx = BT._RX_CLAUSE_END; BT._RX_CLAUSE_END = probe
    try:
        t0 = time.time(); got_w = BT.split_long(wall_t, 8, 120); dt_w = time.time() - t0
    finally:
        BT._RX_CLAUSE_END = real_rx
    check(f"5c wall: a {len(wall_t) // 1000} KB bullet of {label} that cannot fit 8 lines of 120 is refused at once (none), without one gap scanned", got_w is None and probe.calls == 0, (got_w is None, probe.calls))
    check(f"5c wall: …in well under a second (bound 2 s; it was 2.6 s for 100 KB and 10 s for 200 KB before)", dt_w < 2.0, dt_w)
t0 = time.time(); (got_t, got_n) = _fg.fix_long_bullets("- " + ("s" * 69 + ". ") * 2900); dt_f = time.time() - t0
check("5c wall: the write gate leaves it as written for its own refusal, also fast", got_n == "" and dt_f < 2.0, dt_f)
# the scan itself is linear: a bullet that passes the guard (a few thousand clauses of links, only spaces count out) is cut in time proportional to its size
many = "- " + " ".join("[w. v](http://x.y/z) q." for _ in range(40))        # about 960 characters read: it may pass the guard and is then scanned for 40 gaps
t0 = time.time(); got_m = BT.split_long(many, 40, 120); dt_m = time.time() - t0
check("5c wall: a bullet within the guard is scanned and split as before, and fast", got_m is not None and BT.judge(got_m[0], 40, 120) is None and dt_m < 2.0, (got_m and got_m[1], dt_m))

# a resend of the same long description is no new fix: the stored text is the split text, nothing changes, nothing is counted, told or noted, and the History keeps its one line
g5 = create()[1]
_update_svc._update(g5, description=f"- {S1} {S2}", sender=MAIN)
n_hist = len([t for t in hist(g5) if "split by the server" in t])
_, fx_r = with_fixes(lambda: _update_svc._update(g5, description=f"- {S1} {S2}", sender=MAIN))
check("5c resend: the same long description sent again to the item that stores it as split counts no fix and adds no line to the reply", fx_r == [] and _CL.reply_note(fx_r) == "", fx_r)
check("5c resend: …and no second History line, and the stored text is as it was", n_hist == 1 and len([t for t in hist(g5) if "split by the server" in t]) == 1 and _service_store._load(g5)["description"] == f"- {S1}\n- {S2}", hist(g5))
(_, n_r), fx_r2 = with_fixes(lambda: _fg.fix_long_bullets(f"- {S1} {S2}", f"- {S1}\n- {S2}"))
check("5c resend: fix_long_bullets with the stored text equal to the split gives the split text, no note and no fix; with another stored text it is a fix again", n_r == "" and fx_r2 == [] and [k for k, _ in with_fixes(lambda: _fg.fix_long_bullets(f"- {S1} {S2}", "- other"))[1]] == ["description-bullet"], fx_r2)
tok_ = _CL.begin(); _fg.fix_long_bullets(f"- {S1} {S2}"); _, det_ = _CL.end_detail(tok_)
check("5c resend: the fix keeps a digest of what the writer sent (the detail of the fix, never the text), so the same text again undoes nothing, and other text does", det_.get("description-bullet", {}).get("sent") and not _CL.undone("description-bullet", det_["description-bullet"], {"description": f"- {S1}  {S2}"}) and _CL.undone("description-bullet", det_["description-bullet"], {"description": "- other"}), det_)

print(("ok" if not fails else "FAILED") + f": bullets scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
