"""Scenario test for a long step of the owner's put into the shape the board draws, and for a reword of his step done as drop plus add — fixture data, the tools called in-process, no live store, no network.

Covers: step_split (the pure part): a step of about 280 characters with seven actions written as a chain of sentences comes out as a summary of at most 90 characters (the first action and `(+6 more)`) and seven lines that
open with his name, each within the line limit, every word of the original in them, and the same again from the output (idempotent); a short step, one action, a numbered step and a step with a fenced block are left as they
are; an inline numbered list (`1) … 2) …`) is cut at its items; a clause over the line limit on its own is cut at a comma and every word stays; nothing is cut inside a code span or after an abbreviation.
Through update: step=<the long text> stores the summary as the step (your-step) and adds the seven lines to next, written by the sender, beside the server's own line for the summary, and the reply says "split into a summary and 7
lines"; the board's list for his step (render.your_steps) holds the seven actions; sent again, the same text changes nothing and adds no second set; a short step is untouched and says nothing; a long line of his in next
(`<owner>: …` with several actions) is split into one line per action and the reply says so, while a line that is an open step already, a line of another actor and one whole command in backticks are left as they are; a create
with a long line of his splits it. A reword of one of his lines (a line a session wrote) is done as drop plus add, whoever wrote it: the old line shows as dropped, the new words are an open line at the end, the reply says so,
and a reword whose new words are long and carry several actions splits them as well; a reword of the line the server keeps from step= is the new step text (the line is made again and the old one dropped); a reword of the line the server
keeps from an ask is refused, naming the ask; done and dropped keep their rules for his step (done is refused); a reword of a session's own line (not his) keeps its rules (another session's line, old words with progress added).

    tests/run-suite step_split        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="stepsplittest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"


def write_toml():
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's session store (session links off)
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                     (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                     (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^sync = false', 'sync = true'), (r'(?m)^issues_repo = ""', 'issues_repo = "o/r"'),
                     (r'(?m)^api_url = "[^"]*"', 'api_url = "http://127.0.0.1:9"'), (r'(?m)^token_file = ""', f'token_file = "{tmp}/github.token"')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")


write_toml()
(T / "github.token").write_text("test-token\n")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
OTHER = "00000000-0000-4000-8000-000000000003"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now}, OTHER: {"name": "home-other", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-agent", "status": "active", "board": [], "board_open": 0}}}))
DESC = "- Goal: A thing, finished when it works"
ASK = "Decide: whether to ship it now · Recommend: ship · Stakes: a day either way · By: no date"
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True}]
def item(i, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": DESC, "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "next": "home-agent: build it", **meta}}))
for i in range(1, 40):
    item(i)                                                       # items in the agent's hands
(T / "store/next-id").write_text("60"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]

from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import steps as S; from stackshot.model import nextlines as NL; from stackshot.model import owner_steps as HS
from stackshot.model import step_split as SS
from stackshot.model import states as ST
from stackshot.core import call_log as _CL
from stackshot.core import config as _cfg
from stackshot.anchors.anchorhub import core
os.makedirs(core.ADIR, exist_ok=True)       # the hub's state folder, named by the code's own constant
from fastmcp.exceptions import ToolError
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import update as _wt_update
from stackshot.web.ui import render as ui_render
from stackshot.service import store as _service_store
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, owner, note, tag))
def refused(name, f, *want, i=None):
    was = rd(i) if i is not None else None
    try:
        out = f(); check(name, False, out)
    except ToolError as e:
        check(name, all(w in str(e) for w in want) and (was is None or rd(i) == was), str(e))
def send(call):
    """(the reply or the refusal, the fixes the call noted as (kind, line))."""
    tok = _CL.begin()
    try: out = call()
    except ToolError as e: out = e
    finally: fx = _CL.end(tok)
    return out, fx
def upd(i, **kw): return _wt_update.stackshot_update(f"a{i}", sender="home-agent", **kw)
def upo(i, **kw): return _wt_update.stackshot_update(f"a{i}", sender="home-other", **kw)
def st(i): return [(x["status"], x["text"]) for x in S.view(mt(i), keeper=OWNER)]
def his(i): return [(s, t) for s, t in st(i) if t.startswith("Oliver:")]
def his_open(i): return [t for s, t in his(i) if s == "open"]
def words(t): return re.findall(r"\w+", t)
OPEN = lambda t: ("open", t)

# seven actions, written as a chain of sentences: choose among models, compare sellers, pay, get a kit, open a link, meet a deadline, report back (neutral words)
ACTS = ["Choose one of the three models listed on the item", "Compare the sellers of that model and note the best price", "Pay for it by card", "Order the starter kit from that seller",
        "Open the setup link that comes with the kit", "Finish the setup before the end of the month", "Tell the session how it went"]
LONG = ". ".join(ACTS) + "."
LINE_ROOM = 200

# ---- 1. the pure part
check("the fixture is the shape of the case: one line of about 280 characters, seven actions", 250 <= len(LONG) <= 300, len(LONG))
got = SS.split_step(LONG, LINE_ROOM)
check("1 a chain of seven sentences splits into a summary and seven lines", got is not None and len(got[1]) == 7, got)
summary, lines = got
check("1 …the summary is the first action and the count of the rest, within 90 characters, and is no copy of the first line",
      summary == f"{ACTS[0]} (+6 more)" and len(summary) <= SS.SUMMARY_MAX and summary != lines[0], summary)
check("1 …each line opens with his name and holds one action, each within the line limit", lines == [f"Oliver: {a}" for a in ACTS] and all(len(x) <= LINE_ROOM + 20 for x in lines), lines)
check("1 …every word of the original is in the lines, in order (the full stops are all that is gone)", words(LONG) == words(" ".join(S.without_owner(x) for x in lines)), (words(LONG), lines))
again = SS.split_step(summary, LINE_ROOM)
check("1 …idempotent: the summary and each line, fed back, split no further", again is None and all(SS.split_line(x, LINE_ROOM) is None for x in lines), (again, lines))
check("1 a step of 110 characters or fewer is left as written, however many actions", SS.split_step("Do one thing. Do another. And a third.", LINE_ROOM) is None)
check("1 one action in more than 110 characters is left as written (no sentence end to cut at)", SS.split_step("Open the page " + "and then keep going with the next part of it, " * 3 + "until it is over", LINE_ROOM) is None)
NUM = "1. Choose one of the three models listed on the item\n2. Compare the sellers of that model and note the best price\n3. Pay for it by card, then order the starter kit from the same seller and finish the setup"
check("1 a numbered step (the writer's own structure) is kept as it is", SS.split_step(NUM, LINE_ROOM) is None and SS.actions(NUM, LINE_ROOM) == [])
check("1 a step with a fenced block is kept as it is", SS.split_step("Run this and read the output.\n```\nls -l\n```\nThen tell the session what it printed, and open the link in the kit leaflet. " * 2, LINE_ROOM) is None)
INL = "Do these in order: 1) choose one of the three models listed on the item 2) compare the sellers of that model and note the best price 3) pay for it by card and order the starter kit from the same seller"
inl = SS.actions(INL, LINE_ROOM)
check("1 inline numbered items are cut at their items (the numbers are the list's own), the words before them kept as a first action", inl[0] == "Do these in order:" and len(inl) == 4 and inl[1].startswith("choose one of the three models"), inl)
CODE = "Run `ls -l. then cd ..` in the box terminal. Read what it prints, e.g. the file names, and tell the session whether the new build is there, as soon as the box answers at all"
cd = SS.actions(CODE, LINE_ROOM)
check("1 nothing is cut inside a code span or after an abbreviation (e.g.)", len(cd) == 2 and cd[0] == "Run `ls -l. then cd ..` in the box terminal" and cd[1].startswith("Read what it prints, e.g. the file names"), cd)
BIG = ("First choose a model from the list on the item, and compare what each seller says about it on their own pages, and write down the price and the delivery time for each of them, "
       "then pay for the one you picked with a card that works abroad. Second tell the session what you paid.")
bg = SS.actions(BIG, 100)
check("1 a clause over the line limit on its own is cut at a comma, every word kept and every piece within the limit", len(bg) >= 4 and all(len(x) <= 100 for x in bg) and words(BIG) == words(" ".join(bg)), bg)
check("1 one long sentence is one action: it is left as written, never cut mid-sentence", SS.actions("please read this and decide " * 10, LINE_ROOM) == [] and SS.actions(BIG.split(". ")[0], 100) == [], None)
check("1 the summary of a long first action is cut at a word, with the count, within 90 characters", len(SS.summary_of("word " * 40, 6)) <= 90 and SS.summary_of("word " * 40, 6).endswith(" (+6 more)"), SS.summary_of("word " * 40, 6))

# ---- 1b. the boundaries, the caps, the spans, the guards (each one a mutant of the code that must fail a check here)
def two(n):
    """A text of exactly n characters with two sentences."""
    a = "Open the page and read it."
    return a + " " + "x" * (n - len(a) - 2) + "."
check("1b the fixture is the length it says", all(len(two(n)) == n for n in (60, 100, 110, 111, 160)), [len(two(n)) for n in (60, 100, 110, 111, 160)])
check("1b SPLIT_OVER is 110 and the cutoff is its own: a step of 110 characters, or of 60 or 100, is left as written even with two sentences",
      SS.SPLIT_OVER == 110 and all(SS.split_step(two(n), LINE_ROOM) is None for n in (60, 100, 110)), SS.SPLIT_OVER)
check("1b …and a step of 111 or of 160 characters is split into its two sentences", all(len(SS.actions(two(n), LINE_ROOM)) == 2 for n in (111, 160)), [SS.actions(two(n), LINE_ROOM) for n in (111, 160)])
sent = lambda k: " ".join(f"Do thing number {i} now." for i in range(1, k + 1))
check("1b the fixture of the action cap is a text of many short sentences within SPLIT_MAX", len(sent(21)) < SS.SPLIT_MAX, len(sent(21)))
check("1b a text of 20 actions is split, of 21 is left as written (MAX_ACTIONS)", SS.MAX_ACTIONS == 20 and len(SS.actions(sent(20), LINE_ROOM)) == 20 and SS.actions(sent(21), LINE_ROOM) == [], (SS.MAX_ACTIONS, len(SS.actions(sent(21), LINE_ROOM))))
para = lambda n: " ".join(f"Read the part {i} of the long page and write down what it says about the plan, the price, the date and the name of the seller." for i in range(1, n + 1))
check("1b a text over SPLIT_MAX characters is left as written however few actions it makes; the same text under it is split", SS.SPLIT_MAX == 2000 and len(para(15)) < SS.SPLIT_MAX < len(para(16))
      and SS.actions(para(16), LINE_ROOM) == [] and len(SS.actions(para(15), LINE_ROOM)) == 15, (len(para(15)), len(para(16))))
t0 = time.time(); huge = SS.split_step(("Do the next thing there now. " * 2000), LINE_ROOM); el = time.time() - t0
check("1b a text of 56 KB is left as written, at once (no thousands of lines, no work under the item lock)", huge is None and el < 2, (huge, el))
BIGCL = "word " * 60000      # 300 KB in one clause with no comma: the space fallback of `_wrap`
t0 = time.time(); pieces = SS._wrap(BIGCL.strip(), 200); el = time.time() - t0
check("1b _wrap is linear: a clause of 300 KB is cut in well under 5 seconds, every piece within the limit, every word kept", el < 5 and all(len(x) <= 200 for x in pieces) and words(" ".join(pieces)) == words(BIGCL), (el, len(pieces)))
LNK = "[the long title of that page](https://example.org/a/page)"
CSP = "`run the tool with its args`"
wrap_ok = True; wrap_bad = None
for pad in range(0, 40):
    clause = ("a " * pad) + "Read " + LNK + " and then " + CSP + " " + "omega " * 12 + "end"
    got = SS._wrap(clause, 60)
    if not (any(LNK in p for p in got) and any(CSP in p for p in got) and words(" ".join(got)) == words(clause)):
        wrap_ok = False; wrap_bad = (pad, got); break
check("1b _wrap never cuts inside a link or a code span (a space inside either is no place to cut), every word kept", wrap_ok, wrap_bad)
check("1b _wrap leaves a link longer than the limit whole on a piece of its own", any("[a link with a very long title that goes past the limit by far](http://x.example/y)" in p for p in SS._wrap("Open this now and then " + "[a link with a very long title that goes past the limit by far](http://x.example/y) and then read what is there", 40)), None)
PLAN = "Pick plan 1) basic or 2) pro on the pricing page and note what each one costs per month. Then tell the session which one you chose and why that one"
pl = SS.actions(PLAN, LINE_ROOM)
check("1b a number in a sentence (`plan 1) basic or 2) pro`) is no list: two sentences, the words of the first whole", len(pl) == 2 and pl[0].startswith("Pick plan 1) basic or 2) pro on the pricing page"), pl)
AFTER = "Read the notice first. 1) choose one of the three models listed on the item 2) compare the sellers of that model and note the best price 3) pay for it by card"
af = SS.actions(AFTER, LINE_ROOM)
check("1b …but a list that starts after the end of a sentence is a list: the numbers dropped, the items cut", af[0] == "Read the notice first" and len(af) == 4 and af[1].startswith("choose one of the three models"), af)
INCODE = "Run `note: 1) a 2) b` in the box terminal and read what it prints there. Then read [the page: 1) first 2) second](http://x.example/y) and tell the session what it said and when"
ic = SS.actions(INCODE, LINE_ROOM)
check("1b inline numbers inside a code span or a link are no list items: the span and the link stay whole in their actions", len(ic) == 2 and "`note: 1) a 2) b`" in ic[0] and "[the page: 1) first 2) second](http://x.example/y)" in ic[1], ic)
JUNK = "Open the page and read the notice that is shown there at the top of it. ; Then tell the session what it said and wait for the answer to come back.; . Done now"
jk = SS.actions(JUNK, LINE_ROOM)
check("1b a clause of marks only (`;`, `.`) is no action: every action holds a word, none is dropped with one", len(jk) >= 2 and all(re.search(r"\w", x) for x in jk) and words(" ".join(jk)) == words(JUNK), jk)
check("1b a line that is not his (another actor's, or none) is not split by split_line", SS.split_line("home-agent: " + LONG, LINE_ROOM) is None and SS.split_line(LONG, LINE_ROOM) is None and SS.split_line("Oliver: " + LONG, LINE_ROOM) is not None, None)
check("1b the two kinds of fix invite no resend (call_log.NO_RESEND), and the reply line does not say to send again", {"step-split", "step-split-dropped", "step-reworded"} <= set(_CL.NO_RESEND) and "send it again" not in _CL.reply_note([("step-split", "x"), ("step-split-dropped", "z"), ("step-reworded", "y")]), _CL.NO_RESEND)

UNB = "Open the page now. " + "x" * 215 + " is the code to copy there."
check("1b L1: a text with a word longer than a line (and a second sentence) is left as written, and says why", 111 <= len(UNB) <= 300 and SS.actions(UNB, LINE_ROOM) == [] and "longer than a line" in SS.skipped(UNB, LINE_ROOM), (len(UNB), SS.skipped(UNB, LINE_ROOM)))
LBL = "Read [" + "label " * 35 + "](http://x.example/p) at once. Then tell the session what it said there."
check("1b L1: …a link whose words are longer than a line is no exception", 111 <= len(LBL) and SS.actions(LBL, LINE_ROOM) == [], (len(LBL), SS.actions(LBL, LINE_ROOM)))
NUR = "Open the page now. Read http://x.example/" + "a" * 230 + " and say so to the session there."
nu = SS.actions(NUR, LINE_ROOM)
check("1b L1: …but a naked URL longer than a line is exempt (it counts for nothing): the text is split, every word kept", len(nu) >= 2 and all(len(x) <= LINE_ROOM or "http://" in x for x in nu) and words(" ".join(nu)) == words(NUR), nu)
CSPAN = "Do it first. Run `" + "x" * 220 + "` and report back to the session."
check("1b L2: a clause held up by a code span longer than a line is not cut at the spaces around it: the text is left as written, and says why", 111 <= len(CSPAN) <= 300 and SS.actions(CSPAN, LINE_ROOM) == [] and "code span" in SS.skipped(CSPAN, LINE_ROOM), (len(CSPAN), SS.actions(CSPAN, LINE_ROOM)))
check("1b L3: skipped says nothing for a text that is split, a short one and a one-action one", SS.skipped(LONG, LINE_ROOM) == "" and SS.skipped("short one. and two.", LINE_ROOM) == "" and SS.skipped("please read this and decide " * 10, LINE_ROOM) == "", None)
check("1b L3: …and names the size and the action count", "2000 characters" in SS.skipped(para(16), LINE_ROOM) and "at most 20 lines" in SS.skipped(sent(21), LINE_ROOM), (SS.skipped(para(16), LINE_ROOM), SS.skipped(sent(21), LINE_ROOM)))

# ---- 2. step= through update
r, fx = send(lambda: upd(1, step=LONG))
check("2 step= with the long chain is not refused", not isinstance(r, ToolError), r)
check("2 …the stored step is the summary, the item reads your-step", mt(1).get("step") == summary and mt(1).get("state") == "your-step", mt(1))
check("2 …the seven actions are open lines of next that open with his name, written by the sender, after its own line",
      [t for t in mt(1)["next"].splitlines() if t.startswith("Oliver:") and t != f"Oliver: {summary}"] == lines and mt(1)["next"].splitlines()[0] == "home-agent: build it", mt(1)["next"])
check("2 …and the server's own line for the summary stands beside them (his step), recorded as the server's", his_open(1)[-1] == f"Oliver: {summary}" or f"Oliver: {summary}" in his_open(1), his(1))
wr = dict(NL.resolve(mt(1), OWNER))
check("2 …the lines are the sender's, none of them is the server's", all(wr.get(x) == AGENT for x in lines), wr)
check("2 …the reply says what was done in one line: split into a summary and 7 lines", [k for k, _ in fx] == ["step-split"] and "split into a summary and 7 lines" in fx[0][1], fx)
bd = ui_render.Board(str(T / "store"))
shown = [first for first, _rest in bd.your_steps(bd.item("a1"))]
check("2 …the board's list for his step is the seven actions, in order (the summary stays in the title)", shown == ACTS, shown)
r, fx = send(lambda: upd(1, step=LONG))
check("2 the same long step sent again changes nothing: no second set of lines, the summary's line not doubled", not isinstance(r, ToolError) and mt(1)["next"].count("Oliver:") == 8 and [k for k, _ in fx] == ["step-split"] and "nothing was added" in fx[0][1], (r, fx, mt(1)["next"]))
check("2 …(sent again, its next stays the same text)", mt(1)["next"].count("Oliver: " + ACTS[3]) == 1, mt(1)["next"])
r, fx = send(lambda: upd(2, step="check that the box answers and say so"))
check("2 a short step is untouched: stored as written, no line added, no fix", mt(2).get("step") == "check that the box answers and say so" and mt(2)["next"].count("Oliver:") == 1 and not fx, (mt(2), fx))
r, fx = send(lambda: upd(3, step=NUM))
check("2 a numbered step is stored as written, with no fix", mt(3).get("step") == NUM and not fx, (mt(3).get("step"), fx))
r, fx = send(lambda: upd(4, step=summary, next=f"home-agent: build it\n" + "\n".join(lines)))
check("2 a step the writer already split (a summary and its lines in next) is stored as written, no fix, the lines once", mt(4).get("step") == summary and mt(4)["next"].count("Oliver:") == 8 and not fx, (mt(4)["next"], fx))
r, fx = send(lambda: upd(5, step=LONG, next="home-agent: build it\nhome-agent: test it"))
check("2 a long step beside a next of the writer's: the lines join that next, after the writer's own lines", mt(5)["next"].splitlines()[:2] == ["home-agent: build it", "home-agent: test it"] and [t for t in mt(5)["next"].splitlines() if t in lines] == lines, (r, mt(5)["next"]))
r, fx = send(lambda: upd(6, step=LONG, clear_next=True))
check("2 clear_next beside a long step: the old lines go (dropped), the split lines are the item's next", mt(6)["next"].count("home-agent:") == 0 and all(x in mt(6)["next"].splitlines() for x in lines), (r, mt(6)["next"]))
item(41, next="home-agent: build it\nhome-agent: test it")
r, fx = send(lambda: upd(41, step=LONG, next="none"))
check("2 next=none beside a long step: the split lines are the item's next once each (the old lines the write leaves out are carried over as for any next=none)", not isinstance(r, ToolError) and all(mt(41)["next"].splitlines().count(x) == 1 for x in lines) and mt(41)["next"].count("Oliver:") == 8, (r, mt(41)["next"]))
def own(i, text):       # an item whose lines of next were written by the sender (the record the server keeps of who wrote which line)
    item(i, next=text)
    (T / f"store/a/{i}.json").write_text(json.dumps({**rd(i), "metadata": {**mt(i), "next_by": [[AGENT, NL.key_of(x)] for x in text.splitlines()]}}))
own(47, "home-agent: build it\nhome-agent: test it")
r, fx = send(lambda: upd(47, step=LONG, clear_next=True))
check("2 clear_next beside a long step, on lines the sender wrote: the old lines are gone (dropped), the split lines are the item's next",
      not isinstance(r, ToolError) and mt(47)["next"].count("home-agent:") == 0 and all(x in mt(47)["next"].splitlines() for x in lines), (r, mt(47)["next"]))
own(48, "home-agent: build it\nhome-agent: test it")
r, fx = send(lambda: upd(48, step=LONG, next="none"))
check("2 next=none beside a long step, on lines the sender wrote: the split lines are in next once each", not isinstance(r, ToolError) and all(mt(48)["next"].splitlines().count(x) == 1 for x in lines), (r, mt(48)["next"]))
check("2 the item's History says the step was split", "split by the server into a summary and 7 lines" in json.dumps(rd(1)), None)

# a script's write (item sync, the terminal rows) is no session's: a step stays as it is made, no lines are added
from stackshot.service import update as _update_svc
item(42, next="home-agent: build it\nOliver: " + LONG)
_update_svc._update("a42", step=LONG, sender="home-agent")
check("2 a script's write of a long step (not a tool call) stores it whole and adds no line (the line it holds already stays one)", mt(42).get("step") == LONG and mt(42)["next"].count("Oliver:") == 1 and "(+" not in mt(42)["next"], (mt(42).get("step"), mt(42)["next"]))
# an item that holds the long step as a line of his already: the split drops it, the actions replace it
item(43, next="home-agent: build it\nOliver: " + LONG)
r, fx = send(lambda: upd(43, step=LONG))
check("2 a long step on an item that holds `<owner>: <the step>` as an open line: that line is dropped, the summary and the seven actions are open, no copy of the whole step stays open",
      ("dropped", "Oliver: " + LONG) in his(43) and OPEN("Oliver: " + LONG) not in his(43) and len(his_open(43)) == 8 and all(x in his_open(43) for x in lines), (r, st(43)))
check("2 …and the reply says that line was dropped", any(k == "step-split-dropped" and "whole long step" in t for k, t in fx), fx)
r, fx = send(lambda: upd(43, step=LONG))
check("2 …sent again it adds nothing (still eight open lines of his) and says so", len(his_open(43)) == 8 and [k for k, _ in fx] == ["step-split"] and "nothing was added" in fx[0][1], (st(43), fx))
# a step of more than a page: left as written, so the old refusal answers, at once
item(44)
t0 = time.time(); r, fx = send(lambda: upd(44, step=("Do the next thing there now. " * 2000)))
check("2 a step of 56 KB is no split (no thousands of lines): the old limit refuses it, at once, and the item is as it was", isinstance(r, ToolError) and "step at most" in str(r) and mt(44)["next"] == "home-agent: build it" and time.time() - t0 < 5, (str(r)[:200], mt(44)["next"]))

# a step over the limit that the server could not split is refused as ever, and the refusal says why
item(49)
BIGSTEP = para(16)
r, fx = send(lambda: upd(49, step=BIGSTEP))
check("2 L3: a step of more than 2000 characters is refused as before, and the refusal says the server did not split it, and why", isinstance(r, ToolError) and "step at most" in str(r) and "did not split it into lines of next" in str(r) and "2000 characters" in str(r), str(r)[:400])
r, fx = send(lambda: upd(49, step=UNB))
check("2 L1: a step of 111 to 300 characters with a word longer than a line is stored as written, no line added, the refusal of a long line of next is not made", mt(49).get("step") == UNB and mt(49)["next"].count("Oliver:") == 1 and not isinstance(r, ToolError), (r, mt(49)))

# ---- 2b. the lines of a split belong to the step: replacing or withdrawing the step takes them
ACTS_B = ["Read the notice on the main page", "Write down the code it shows there", "Send the code to the session in a note", "Check that the session confirms it works", "Open the second page from the list", "Tell the session what the second page says"]
LONG_B = ". ".join(ACTS_B) + "."
sum_b, lines_b = SS.split_step(LONG_B, LINE_ROOM)
def opened(i): return his_open(i)
item(50)
upd(50, step=LONG)
r, fx = send(lambda: upd(50, step=LONG_B))
check("2b a second long step replaces the first as a whole: the old summary line and the old seven action lines are dropped, the new summary and its six lines are open (7 open lines of his)",
      sorted(opened(50)) == sorted([f"Oliver: {sum_b}", *lines_b]) and all(("dropped", x) in his(50) for x in lines), (r, st(50)))
check("2b …and the reply says in one line that the old lines were dropped with it", any(k == "step-split-dropped" and "dropped with it (replaced)" in t for k, t in fx), fx)
check("2b …the board's list for his step is the six actions of the new step", [first for first, _rest in ui_render.Board(str(T / "store")).your_steps(ui_render.Board(str(T / "store")).item("a50"))] == ACTS_B, None)
item(51)
upd(51, step=LONG)
r, fx = send(lambda: upd(51, step="check that the box answers and say so"))
check("2b a short step after a split replaces the whole group: only the short step's line is open", opened(51) == ["Oliver: check that the box answers and say so"] and mt(51).get("step") == "check that the box answers and say so" and "step_lines" not in mt(51), (r, st(51), mt(51)))
item(52)
upd(52, step=LONG)
r, fx = send(lambda: upd(52, step="none"))
check("2b step=none after a split withdraws the step and every open line of it: no line of his is open, the state is gone, the agent's own line stays",
      opened(52) == [] and mt(52).get("state") != "your-step" and not mt(52).get("step") and "home-agent: build it" in mt(52)["next"] and "step_lines" not in mt(52) and not any(x in mt(52)["next"] for x in ACTS), (r, st(52), mt(52)))
check("2b …and the reply says the lines were dropped with the step (withdrawn)", any(k == "step-split-dropped" and "dropped with it (withdrawn)" in t for k, t in fx), fx)
item(53)
upd(53, step=LONG)
d_ = rd(53); m_ = d_["metadata"]
for e_ in m_["steps"]:
    if e_["text"] == lines[1]: e_["status"], e_["by"], e_["at"] = "done", "Oliver", now
m_["next"] = "\n".join(x for x in m_["next"].splitlines() if x != lines[1])
(T / "store/a/53.json").write_text(json.dumps(d_))
r, fx = send(lambda: upd(53, step=LONG_B))
check("2b a line of the old split that is done stays done when the step is replaced, the open ones go", ("done", lines[1]) in his(53) and ("dropped", lines[0]) in his(53) and ("dropped", lines[1]) not in his(53), st(53))
item(62)
upd(62, step=LONG)
d_ = rd(62); m_ = d_["metadata"]
for e_ in m_["steps"]:
    if e_["text"] == lines[1]: e_["status"], e_["by"], e_["at"] = "done", "Oliver", now
m_["next"] = "\n".join(x for x in m_["next"].splitlines() if x != lines[1]) + "\n" + lines[1]      # the line done, and the same words written again as an open line
(T / "store/a/62.json").write_text(json.dumps(d_))
r, fx = send(lambda: upd(62, step=LONG_B))
check("2b the done line stays done when an open line of the same words is dropped with the old step (a line is told apart by its status, not only by its words)", ("done", lines[1]) in his(62) and ("dropped", lines[1]) in his(62) and opened(62).count(lines[1]) == 0, (r, st(62)))
item(54)
upd(54, step=LONG)
r, fx = send(lambda: upd(54, step=LONG))
check("2b the same long step sent again drops nothing", len(opened(54)) == 8 and not any(k == "step-split-dropped" for k, t in fx), (st(54), fx))
# the stored summary sent again is not a new step: nothing of the split goes, and the reply says nothing was changed
def same_step_case(i, name, call):
    item(i)
    upd(i, step=LONG)
    keys_was = list(mt(i)["step_lines"])
    r, fx = send(lambda: call(i, mt(i)["step"]))
    check(f"2b {name}: the eight open lines of his stay open, nothing is dropped, the record of the split is as it was",
          not isinstance(r, ToolError) and len(opened(i)) == 8 and not any(k == "step-split-dropped" for k, t in fx) and mt(i).get("step_lines") == keys_was and len(keys_was) == 7, (r, st(i), fx, mt(i).get("step_lines")))
    check(f"2b {name}: …and the reply says nothing was changed", any(k == "step-split" and "nothing was changed" in t or k == "step-split" and "nothing was added" in t for k, t in fx), fx)
same_step_case(70, "the stored summary sent again", lambda i, s: upd(i, step=s))
same_step_case(71, "the stored summary sent again with trailing spaces", lambda i, s: upd(i, step=s + "   \n "))
same_step_case(72, "the stored summary sent again with the whole next sent back", lambda i, s: upd(i, step=s, next=mt(i)["next"]))
same_step_case(73, "the original long text sent again", lambda i, s: upd(i, step=LONG))
item(74)
upd(74, step=LONG)
r, fx = send(lambda: upd(74, step="check that the box answers and say so", next=mt(74)["next"]))
check("2b a different step still drops the old lines, also when next is sent back whole with them (their lines leave with the step, the call is not refused)",
      not isinstance(r, ToolError) and opened(74) == ["Oliver: check that the box answers and say so"] and any(k == "step-split-dropped" for k, t in fx), (r, st(74), fx))
item(75)
upd(75, step=LONG)
r, fx = send(lambda: upd(75, step=LONG_B, next=mt(75)["next"]))
check("2b a long step replaced by another long one, with next sent back whole (still listing the old lines), is not refused: the old lines are dropped and the new ones are open",
      not isinstance(r, ToolError) and sorted(opened(75)) == sorted([f"Oliver: {sum_b}", *lines_b]), (r, st(75), fx))
# an action of the split that was ticked done stays done when the same long step is sent again
item(76)
upd(76, step=LONG)
d_ = rd(76); m_ = d_["metadata"]
for e_ in m_["steps"]:
    if e_["text"] == lines[1]: e_["status"], e_["by"], e_["at"] = "done", "Oliver", now
m_["next"] = "\n".join(x for x in m_["next"].splitlines() if x != lines[1])
(T / "store/a/76.json").write_text(json.dumps(d_))
r, fx = send(lambda: upd(76, step=LONG))
check("2b the same long step sent again after one action was ticked done does not open that action again", not isinstance(r, ToolError) and ("done", lines[1]) in his(76) and lines[1] not in opened(76) and len(opened(76)) == 7, (r, st(76)))
# a different long step that holds the same words as an action that was ticked done opens every one of its own actions
LONG_C = ". ".join([ACTS_B[0], ACTS[1], ACTS_B[2], ACTS_B[3]]) + "."
sum_c, lines_c = SS.split_step(LONG_C, LINE_ROOM)
def settle(i, line, how):       # the line of his marked done or dropped on the item (as a tick or a drop leaves it), and gone from next
    d_ = rd(i); m_ = d_["metadata"]
    for e_ in m_["steps"]:
        if e_["text"] == line: e_["status"], e_["by"], e_["at"] = how, "Oliver", now
    m_["next"] = "\n".join(x for x in m_["next"].splitlines() if x != line)
    (T / f"store/a/{i}.json").write_text(json.dumps(d_))
item(80)
upd(80, step=LONG)
settle(80, lines[1], "done")
r, fx = send(lambda: upd(80, step=LONG_C))
check("2b a different long step that holds the same words as a done action opens all four of its own actions (the done line stays done, the record lists four keys, all four open)",
      not isinstance(r, ToolError) and len(lines_c) == 4 and lines[1] in lines_c and sorted(opened(80)) == sorted([f"Oliver: {sum_c}", *lines_c]) and ("done", lines[1]) in his(80) and len(mt(80)["step_lines"]) == 4, (r, st(80), fx))
check("2b …and the reply does not say a line was on the item already", not any(k == "step-split" and "already" in t for k, t in fx), fx)
# a dropped action stays dropped when the same long step is sent again, as a done one stays done
item(81)
upd(81, step=LONG)
settle(81, lines[2], "dropped")
r, fx = send(lambda: upd(81, step=LONG))
check("2b the same long step sent again does not open an action that was dropped", not isinstance(r, ToolError) and ("dropped", lines[2]) in his(81) and lines[2] not in opened(81) and len(opened(81)) == 7, (r, st(81), fx))
# the stored summary sent with clear_next=true: every line is wiped, the record goes, and the reply does not say nothing changed
item(82)
upd(82, step=LONG)
r, fx = send(lambda: upd(82, step=mt(82)["step"], clear_next=True))
check("2b the stored summary sent with clear_next=true wipes the lines, the record of the split goes, and the reply does not say nothing was changed",
      not isinstance(r, ToolError) and not any(x in mt(82).get("next", "").splitlines() for x in lines) and "step_lines" not in mt(82) and not any(k == "step-split" and "nothing was changed" in t for k, t in fx), (mt(82).get("next"), mt(82).get("step_lines"), fx))
# a stored step_lines with a step and no state: any write that settles the state takes the record with the step
item(83)
upd(83, step=LONG)
d_ = rd(83); d_["metadata"].pop("state", None)
(T / "store/a/83.json").write_text(json.dumps(d_))
r, fx = send(lambda: upd(83, next="home-agent: build it, then check it"))
check("2b a write on an item whose step stands with no state stored takes the step away, and the record of its split with it", not isinstance(r, ToolError) and not mt(83).get("step") and "step_lines" not in mt(83), (r, mt(83)))
# a record of a split with no step stored (an item as an older write left it) drops nothing
item(77)
upd(77, step=LONG)
d_ = rd(77); m_ = d_["metadata"]
m_.pop("step", None); m_.pop("state", None)
(T / "store/a/77.json").write_text(json.dumps(d_))
r, fx = send(lambda: upd(77, step="check that the box answers and say so"))
check("2b a record of a split with no step stored belongs to no step: a step written then drops none of the open lines", not isinstance(r, ToolError) and all(x in opened(77) for x in lines) and not any(k == "step-split-dropped" for k, t in fx), (r, st(77), fx))
# a state change that takes the step away takes the record of its lines with it
item(78)
upd(78, step=LONG)
r, fx = send(lambda: upd(78, supplies="a kit from the seller", after=["a1"], ask_by=time.strftime("%Y-%m-%d", time.gmtime(now + 10 * 86400))))
check("2b a write that moves the item to blocked takes the stored step away, and the record of its split with it", not isinstance(r, ToolError) and not mt(78).get("step") and "step_lines" not in mt(78), (r, mt(78)))
# his answer, a close and a hand-over settle the whole group
from stackshot.service import answer as answer_svc
item(55)
upd(55, step=LONG)
r = answer_svc._answer("a55", "", "", "done")
check("2b his Done ticks the summary line and every action line: none of his is open, all eight are done", opened(55) == [] and len([1 for s_, t_ in his(55) if s_ == "done"]) == 8, (r, st(55)))
check("2b …and the record of the split goes with the step: no step_lines is left after his Done", "step_lines" not in mt(55) and not mt(55).get("step"), mt(55))
item(56)
upd(56, step=LONG)
from stackshot.web.tools import complete as _wt_complete
r = _wt_complete.stackshot_complete("a56", outcome="dropped", reason="no longer wanted", outcome_text="- It was dropped, nobody wants it", sender="home-agent")
check("2b a close settles the group: none of his lines is open and the record of the split goes with the step", opened(56) == [] and "step_lines" not in mt(56) and not mt(56).get("step"), (r, st(56), mt(56)))
item(57)
upd(57, step=LONG)
r, fx = send(lambda: upd(57, mover="home-agent", step="none"))
check("2b a hand-over to the agent with the step withdrawn leaves no line of his open", not isinstance(r, ToolError) and opened(57) == [], (r, st(57)))

# a script's create and update (item sync, the terminal rows) store a long line of his whole; a session's write splits it
from stackshot.service import create as _create_svc
LONG2 = "Open the page and read the notice. Copy the code it shows. Paste it into the form and send it. Then tell the session what happened there."
check("2c the fixture is a long line of his of 135 characters or so with four actions", 120 <= len(LONG2) <= 180 and len(SS.actions(LONG2, LINE_ROOM)) == 4, len(LONG2))
gid_s, _rs = _create_svc.create_item(subject="[home] script made", description=DESC, project="projects/alpha", owner=OWNER, next="home-agent: build it\nOliver: " + LONG2, needs="home-agent", by="home-agent")
check("2c a create that is no session's (a script's) stores a long line of his as one line, whole", _service_store._load(gid_s)["metadata"]["next"].splitlines() == ["home-agent: build it", "Oliver: " + LONG2], _service_store._load(gid_s)["metadata"]["next"])
gid_t = _wt_create.stackshot_create(subject="[home] session made", description=DESC, project="projects/alpha", needs="home-agent", next="home-agent: build it\nOliver: " + LONG2, sender="home-agent")
check("2c …a session's create of the same line splits it", len(_service_store._load(re.match(r"created (\S+)", gid_t).group(1))["metadata"]["next"].splitlines()) == 5, gid_t)
item(58)
_update_svc._update("a58", next="home-agent: build it\nOliver: " + LONG2, sender="home-agent")
check("2c an update that is no session's stores a long line of his as one line, whole", mt(58)["next"].splitlines() == ["home-agent: build it", "Oliver: " + LONG2], mt(58)["next"])
item(61)
r, fx = send(lambda: upd(61, next="home-agent: build it\nOliver: " + LONG2))
check("2c …and a session's update of the same line splits it into its four actions", len(mt(61)["next"].splitlines()) == 5 and [k for k, _ in fx] == ["step-split"], (r, mt(61)["next"]))
item(59, next="home-agent: build it\nOliver: look at the page first")
_update_svc._update("a59", reword={2: "Oliver: " + LONG2}, sender="home-agent")
check("2c …and so does the new words of a reword of his line from a script: one new line, whole", his_open(59) == ["Oliver: " + LONG2], st(59))
# the server's own line for the stored step is remade, never dropped by hand: the step stored whole by a script, then sent by a session
item(60)
_update_svc._update("a60", step=LONG, sender="home-agent")
r, fx = send(lambda: upd(60, step=LONG))
check("2c a session sends the long step that the item stores already (the server's own line for it): that line is dropped once, by the remake, and the reply does not claim a line of his was dropped",
      sorted(his_open(60)) == sorted([f"Oliver: {summary}", *lines]) and sum(1 for k, t in fx if k == "step-split-dropped") == 0 and his(60).count(("dropped", "Oliver: " + LONG)) == 1, (st(60), fx))

# ---- 3. long lines of his in next
LONGLINE = "Oliver: " + LONG
r, fx = send(lambda: upd(7, next="home-agent: build it\n" + LONGLINE))
check("3 a long line of his in next with seven actions is stored as seven lines, one per action, the other lines as they were",
      mt(7)["next"].splitlines() == ["home-agent: build it", *lines], (r, mt(7)["next"]))
check("3 …and the reply says so", [k for k, _ in fx] == ["step-split"] and "split into 7 lines" in fx[0][1], fx)
r, fx = send(lambda: upd(7, next="home-agent: build it\n" + "\n".join(lines)))
check("3 the lines fed back change nothing, no fix", mt(7)["next"].splitlines() == ["home-agent: build it", *lines] and not fx, (mt(7)["next"], fx))
r, fx = send(lambda: upd(8, next="home-agent: build it. Then test it after that and open the pull request once it is green. Then wait for the review and fix what comes back of it"))
check("3 a long line of the agent's own (not his) is not split here: the next-line rules judge it as before (stored as one line, or refused whole)", not [k for k, _ in fx if k == "step-split"] and (isinstance(r, ToolError) or mt(8)["next"].count("\n") == 0), (r, fx, mt(8)["next"]))
item(45, next="home-agent: build it\nOliver: " + LONG)
r, fx = send(lambda: upd(45, next="home-agent: build it\nOliver: " + LONG))
check("3 a long line of his that is an open step already is left as it stands (its key is known): one line, no fix", mt(45)["next"].splitlines() == ["home-agent: build it", "Oliver: " + LONG] and not fx, (r, fx, mt(45)["next"]))
BIGCMD = "Oliver: `echo one. echo two; echo three. echo four; echo five. echo six; echo seven. echo eight; echo nine. echo ten; echo eleven. echo twelve; echo more`"
item(46)
r, fx = send(lambda: upd(46, next=f"home-agent: build it\n{BIGCMD}"))
check("3 a long line that is one whole command in backticks is left as it is, whatever sentence marks are inside", mt(46)["next"].splitlines() == ["home-agent: build it", BIGCMD] and not fx, (r, fx, mt(46)["next"]))
CMDLINE = "Oliver: `for p in a b; do echo $p; done`"
r, fx = send(lambda: upd(9, next=f"home-agent: build it\n{CMDLINE}"))
check("3 a line that is one whole command in backticks is left as it is", f"{CMDLINE}" in mt(9)["next"].splitlines() and not fx, (r, fx))
r = _wt_create.stackshot_create(subject="[home] do the thing", description=DESC, project="projects/alpha", needs="home-agent", next="home-agent: build it\n" + LONGLINE, sender="home-agent")
cid = re.match(r"created (\S+)", r).group(1)
cm = _service_store._load(cid)["metadata"]
check("3 a create with a long line of his: stored as seven lines, one per action", cm["next"].splitlines() == ["home-agent: build it", *lines], (r, cm["next"]))

# ---- 4. a reword of his step is drop plus add
item(10, next="home-agent: build it\nOliver: look at the page first\nhome-agent: verify it")
r, fx = send(lambda: upd(10, reword={2: "Oliver: look at the page and the logs first"}))
check("4 a reword of a line of his is not refused", not isinstance(r, ToolError), r)
check("4 …the old line shows as dropped (by the sender) and the new words are an open line at the end",
      st(10) == [OPEN("home-agent: build it"), ("dropped", "Oliver: look at the page first"), OPEN("home-agent: verify it"), OPEN("Oliver: look at the page and the logs first")], st(10))
check("4 …next holds the open lines, the new words last", mt(10)["next"].splitlines() == ["home-agent: build it", "home-agent: verify it", "Oliver: look at the page and the logs first"], mt(10)["next"])
check("4 …the reply says it was done as drop plus add", [k for k, _ in fx] == ["step-reworded"] and "drop plus add" in fx[0][1] and "dropped" in str(r), (fx, r))
check("4 …the reply carries the dropped step's line too", "(step 2 dropped: Oliver: look at the page first)" in str(r), r)
item(11, next="home-agent: build it\nOliver: look at the page first")
(T / "store/a/11.json").write_text(json.dumps({**rd(11), "metadata": {**mt(11), "next_by": [[AGENT, NL.key_of("home-agent: build it")], [OTHER, NL.key_of("Oliver: look at the page first")]]}}))
r, fx = send(lambda: upd(11, reword={"Oliver: look at the page first": "Oliver: look at the logs first"}))
check("4 a line of his that another session wrote is reworded the same way (it is dropped and added, as dropped=[n] and a new line would)", not isinstance(r, ToolError) and his(11) == [("dropped", "Oliver: look at the page first"), OPEN("Oliver: look at the logs first")], (r, st(11)))
item(12, next="home-agent: build it\nOliver: look at the page first")
r, fx = send(lambda: upd(12, reword={2: "Oliver: look at the page first and then tell the session what you saw there"}))
check("4 new words that are the old words with more added are no refusal for his line: drop plus add", not isinstance(r, ToolError) and his(12)[0] == ("dropped", "Oliver: look at the page first") and len(his_open(12)) == 1, (r, st(12)))
item(13, next="home-agent: build it\nOliver: look at the page first")
r, fx = send(lambda: upd(13, reword={2: "Oliver: " + LONG}))
check("4 new words that carry seven actions are split into seven lines (drop plus add, then the split)", not isinstance(r, ToolError) and his(13)[0] == ("dropped", "Oliver: look at the page first") and his_open(13) == lines, (r, st(13)))
check("4 …and the reply says the split and the drop plus add", {k for k, _ in fx} == {"step-split", "step-reworded"}, fx)
item(14, next="home-agent: build it\nOliver: look at the page first")
r, fx = send(lambda: upd(14, reword={2: "home-other: look at the page first"}))
check("4 a reword that gives his line to a session is a hand-on like any new line for that session: the hand-on check still asks for what closes the item, and nothing is written", isinstance(r, ToolError) and "hands a14 to home-other" in str(r) and st(14)[1] == OPEN("Oliver: look at the page first"), (r, st(14)))
item(15, next="home-agent: build it\nOliver: look at the page first")
upd(15, step="check the box")
refused("4 done on the line of his that the server keeps stays refused (only his answer ticks it)", lambda: upd(15, done=["Oliver: check the box"]), "Oliver's", i=15)
r, fx = send(lambda: upd(15, reword={2: "Oliver: look at the page first"}))
check("4 a reword to the very words it has changes nothing and says nothing", not isinstance(r, ToolError) and not fx and st(15)[1] == OPEN("Oliver: look at the page first"), (r, fx, st(15)))

# the line the server keeps from step=
r = upd(16, step="check that the box answers and say so")
rec = HS.recorded(mt(16))
check("4 the server's own step line is recorded (the fixture of the next checks)", rec == "Oliver: check that the box answers and say so", rec)
r, fx = send(lambda: upd(16, reword={"Oliver: check that the box answers and say so": "Oliver: check that the box answers on its own address"}))
check("4 a reword of the line the server keeps from step= is the new step text: the step reads the new words", not isinstance(r, ToolError) and mt(16).get("step") == "check that the box answers on its own address", (r, mt(16)))
check("4 …the old line shows as dropped, the new line is open and recorded as the server's, and the reply says it was done as a new step text",
      ("dropped", "Oliver: check that the box answers and say so") in his(16) and OPEN("Oliver: check that the box answers on its own address") in his(16) and HS.recorded(mt(16)) == "Oliver: check that the box answers on its own address"
      and [k for k, _ in fx] == ["step-reworded"] and "new step text" in fx[0][1], (st(16), fx))
r, fx = send(lambda: upd(17, step="check that the box answers and say so"))
r, fx = send(lambda: upd(17, reword={2: "Oliver: " + LONG}))
check("4 …a long new text for the server's own line is split like a long step: the step is the summary, the seven actions are lines", not isinstance(r, ToolError) and mt(17).get("step") == summary and all(x in his_open(17) for x in lines), (r, mt(17)))
upd(18, step="check that the box answers and say so")
r, fx = send(lambda: upd(18, step="check that the box answers at all", reword={2: "Oliver: other words"}))
check("4 …a reword beside a step= in one call is refused (two new texts for one step), naming step=", isinstance(r, ToolError) and "step=" in str(r) and mt(18).get("step") == "check that the box answers and say so", r)
item(19, needs=["decision", "home-agent"], ask=ASK, options=OPTS, next="home-agent: build it")
upd(19, description=DESC + "\n- more")
refused("4 a reword of the line the server keeps from an ask is refused, and the refusal names the ask", lambda: upd(19, reword={"Oliver: whether to ship it now": "Oliver: whether to ship it later"}), "own step", "ask=", i=19)
item(20, next="home-agent: build it\nhome-other: second")
(T / "store/a/20.json").write_text(json.dumps({**rd(20), "metadata": {**mt(20), "next_by": [[AGENT, NL.key_of("home-agent: build it")], [OTHER, NL.key_of("home-other: second")]]}}))
refused("4 a reword of another session's line (not his) keeps its refusal", lambda: upd(20, reword={2: "home-other: second, later"}), "reword: step 2 is a line of", "only the session that wrote a step rewords it", i=20)
item(21, next="home-agent: build it")
(T / "store/a/21.json").write_text(json.dumps({**rd(21), "metadata": {**mt(21), "next_by": [[AGENT, NL.key_of("home-agent: build it")]]}}))
refused("4 a reword of a session's own line to its old words with progress added keeps its refusal", lambda: upd(21, reword={1: "home-agent: build it, and it passed on the box"}), "old text with words added", i=21)

print(("ok" if not fails else "FAILED") + f": step_split scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
