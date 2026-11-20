"""Scenario test for three more writes the server fixes and says so instead of refusing (service/step_settle.py, gates._said_plain, said.plain_quote / find_by_quote, call_log.unfix) — fixture data, the
tools called in-process, no live store, no network. The transcripts are fixture files in a temporary directory, never the host's.

Covers:
  1  his step first in next while the write clears needs and hands the item to an agent: the write goes through; the step is marked done when the write carries said, else dropped; the reply says which, the
     call log counts `his-step-settled`, and the weekly report counts it; a write that does not clear needs, or hands the item to nobody, or whose step is not first, or that marks the step itself, or whose his-line
     is one this very write adds, is as it was (refused or untouched, no fix)
  2  said sent as plain text: recorded as his Acked-by with that quote, his latest typed message that holds the words found in the sender's transcript and checked; text that no message of his holds is refused; an
     unreadable transcript stores it unchecked; broken JSON and the structured form are as before; counted as `said-text`
  3  step="none": the refusal text names it as a way out and it now is one: it drops the step that stood first under the agent's state (counted as `step-none-applied`, the no-op line of the older reply is not
     told), and step="none" on an item that has no such line is as before
  4  the id forms the update tool accepts (g<n>, board#<n>, #<n>, the bare number) on issue-numbered items: kinds 1 and 3 settle the same item the update read
  5  done or dropped follows what the write stores as said: only a checked Acked-by marks his step done; an empty, null, unchecked or other-tagged said drops it, and the line says what was stored
  6  step="none" on an item that stores a step or the your-step state, with needs cleared and a mover: the retry keeps step="none" and goes through
  7  the branches of step_settle that no write above tells apart (called directly or by a write built for the branch)

    tests/run-suite fix_and_tell_more        → exit 0 / 1"""
import asyncio, contextlib, datetime as dt, io, json, logging, os, pathlib, re, sys, time, types
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="fixtellmore-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
MARK = "<!-- fleet -->"
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                 (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^sync = false', 'sync = true'), (r'(?m)^issues_repo = ""', 'issues_repo = "o/r"'),
                 (r'(?m)^api_url = "[^"]*"', 'api_url = "http://127.0.0.1:9"'), (r'(?m)^token_file = ""', f'token_file = "{tmp}/github.token"'),
                 (r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]'), (r'(?m)^injected_marker = ""', f'injected_marker = "{MARK}"')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "github.token").write_text("test-token\n")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None); os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "store/g", "fleet/a", "state/s1", "brain/projects", "secrets", "transcripts/-home-x"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
AWAY = "00000000-0000-4000-8000-000000000003"          # a session whose transcript is not on this box
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now}, AWAY: {"name": "home-away", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-agent", "status": "active", "board": [], "board_open": 0}}}))
DESC = "- Goal: A thing, finished when it works"
HIS = "Oliver: paste it into the form"
AGENT_LINE = "home-agent: build it"


def where(i):
    """The store file of item `i`: a number is an older item (letter a); "g<n>" is an issue-numbered one, the id shape a real board holds."""
    return T / (f"store/g/{i[1:]}.json" if isinstance(i, str) else f"store/a/{i}.json")


def item(i, status="open", **meta):
    where(i).write_text(json.dumps({"id": str(i)[1:] if isinstance(i, str) else str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "next": f"{HIS}\n{AGENT_LINE}", **meta}}))
for i in range(1, 40):
    item(i)                                                       # his step first, an agent's state under it: the shape the guard refuses
item(30, next=f"{AGENT_LINE}\n{HIS}")                             # his step second: the guard is quiet
item(31, next=AGENT_LINE)                                         # no step of his at all
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")

# his typed message, one the fleet tool typed (the marker), an assistant message that holds the same words, and a later message of his that holds them again
def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
TS = lambda n: f"2026-11-01T01:{n:02d}:00Z"
def u(n, text, kind="human", **kw): return {"type": "user", "uuid": uid(n), "origin": {"kind": kind}, "message": {"role": "user", "content": text}, "timestamp": TS(n), **kw}
def asst(n, text): return {"type": "assistant", "uuid": uid(n), "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}, "timestamp": TS(n)}
rows = [u(10, "I pasted it into the form, go on with the build"), asst(11, "he said: I pasted it into the form"), u(12, MARK + " I pasted the thing typed by a tool"),
        u(13, "later: Ship it as it is,\nthen close the loop"), u(14, "Ship it as it is, and say so on the item"), u(15, "a peer note: ship it", kind="peer"), u(16, "pick option B please")]
(T / "transcripts/-home-x" / f"{AGENT}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def rd(i): return json.loads(where(i).read_text())
def mt(i): return rd(i)["metadata"]

from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import steps as S; from stackshot.model import said as SAID
from stackshot.core import call_log as CL; from stackshot.tools import refusal_report as RR; from stackshot.web import middleware as _wmw; from stackshot.service import gates; from stackshot.service import step_settle as SS
from fastmcp.exceptions import ToolError
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, owner, note, tag))
def upd(i, **kw):
    """The update tool on item `i`: a number is item a<i>; a text is the id as the writer sends it (g<n>, board#<n>, #<n>, <n>)."""
    return _wt_update.stackshot_update(i if isinstance(i, str) else f"a{i}", **{"sender": "home-agent", **kw})
def st(i): return [(x["status"], x["text"]) for x in S.view(mt(i), keeper=OWNER)]
def his(i): return [s for s, t in st(i) if t == HIS]
def attempt(i, **kw):
    """→ (reply or None, refusal text, the fixes the call noted [(kind, line)])."""
    tok = CL.begin()
    try:
        try: return upd(i, **kw), "", None
        except ToolError as e: return None, str(e), None
    finally:
        fx = CL.end(tok)
        globals()["_fx"] = fx
def run(i, **kw):
    r, why, _ = attempt(i, **kw)
    return r, why, list(globals()["_fx"])
kinds = lambda fx: [k for k, _ in fx]
HAND = dict(next="home-agent: go on with the build", needs="none", mover="home-agent")

# ---- 1. his step first, needs cleared, the item handed to an agent
r, why, fx = run(1, **HAND)
check("1 a write that clears needs and hands the item to an agent while his step is first in next goes through (it was refused)", r is not None and why == "", why)
check("1 …his step is dropped (no said), the agent's lines stay open", his(1) == ["dropped"] and ("open", AGENT_LINE) in st(1), st(1))
check("1 …the fix is counted as his-step-settled and the line says dropped, why, and how to put it back", kinds(fx) == ["his-step-settled"] and "dropped" in fx[0][1] and "no said" in fx[0][1] and "write it again" in fx[0][1] and "paste it into the form" in fx[0][1], fx)
check("1 …the reply carries no refusal and his step is not first in next any more", HIS not in mt(1)["next"].splitlines()[:1] and not mt(1).get("needs"), mt(1))
r, why, fx = run(2, said=[{"tag": "Acked-by", "quote": "I pasted it into the form", "msg": uid(10)}], **HAND)
check("1 …with a checked Acked-by on the write his step is marked done, and the line says so", r is not None and his(2) == ["done"] and kinds(fx) == ["his-step-settled"] and "marked done" in fx[0][1] and "checked Acked-by" in fx[0][1], (why, st(2), fx))
check("1 …the said entry is on the item, checked", [e.get("checked") for e in mt(2).get("said", [])] == [True], mt(2).get("said"))
r, why, fx = run(3, **{**HAND, "agent": "home-agent"})
check("1 an agent named with agent= and mover together: still settled (the same write)", r is not None and his(3) == ["dropped"], (why, st(3)))
r, why, fx = run(19, next="home-agent: go on with the build", needs="none")
check("1 an item handed on by a line of next that opens with another session (no mover) is settled too", r is not None and his(19) == ["dropped"] and kinds(fx) == ["his-step-settled"], (why, st(19), fx))
r, why, fx = run(4, needs="none")
check("1 clearing needs with no one handed the item is as it was: refused, nothing written", r is None and "his step would sit hidden" in why and his(4) == ["open"] and mt(4).get("needs") == ["home-agent"] and fx == [], (why, st(4), mt(4).get("needs"), fx))
r, why, fx = run(5, next="home-agent: go on with the build", mover="home-agent")
check("1 handing the item on without clearing needs is as it was: refused, nothing written", r is None and "his step would sit hidden" in why and his(5) == ["open"] and fx == [], (why, st(5), fx))
r, why, fx = run(6, next=f"{HIS}\nhome-agent: go on", needs="none", mover="home-agent")
check("1 a his-line this very write adds is not on the checklist: refused as before, nothing written", r is None and "his step would sit hidden" in why and fx == [] and mt(6).get("needs") == ["home-agent"], (why, fx))
r, why, fx = run(7, done=[1], needs="none", mover="home-agent", said=[{"tag": "Acked-by", "quote": "I pasted it into the form", "msg": uid(10)}])
check("1 a write that marks his step itself is as it was: done, no fix told", r is not None and his(7) == ["done"] and "his-step-settled" not in kinds(fx), (why, st(7), fx))
r, why, fx = run(30, **HAND)
check("1 his step second in next: the guard is quiet, the step stays open, no fix", r is not None and his(30) == ["open"] and fx == [], (why, st(30), fx))
r, why, fx = run(31, **HAND)
check("1 an item with no step of his: no fix", r is not None and fx == [] and kinds(fx) == [], (why, fx))

# ---- the call log and the weekly report count it, through the middleware
CALLS = T / "state/calls"
def lines():
    out = []
    for p in sorted(CALLS.glob("*.jsonl")) if CALLS.exists() else []:
        out += [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out
def wipe():
    for p in list(CALLS.glob("*.jsonl")) if CALLS.exists() else []: p.unlink()
def reply(text): return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], structured_content={"result": text})
def mw(i, **kw):
    async def nxt(ctx): return reply(upd(i, **kw))
    ctx = types.SimpleNamespace(message=types.SimpleNamespace(name="update", arguments={"item_id": f"a{i}", "sender": "home-agent"}))
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        try: return asyncio.run(_wmw._RefusalLog().on_call_tool(ctx, nxt))
        except ToolError as e: return e
wipe()
for i in (8, 9): item(i)
out = mw(8, **HAND)
text = out.content[0].text if not isinstance(out, ToolError) else str(out)
check("1 through the middleware: the reply carries one (fixed for you: …) line that says dropped, and no invitation to send the field again", "(fixed for you: " in text and "dropped" in text and "send it again" not in text and text.count("fixed for you") == 1, text[-400:])
out2 = mw(9, said=[{"tag": "Acked-by", "quote": "I pasted it into the form", "msg": uid(10)}], **HAND)
rowsl = lines()
check("1 …and the call log holds the kind, once, on the item and the sender", [r.get("fix") for r in rowsl] == [["his-step-settled"], ["his-step-settled"]] and rowsl[0]["sender"] == "home-agent" and rowsl[0]["ok"] is True, rowsl)
cur = RR.tally(rowsl); prev = RR.tally([])
rep = RR.build(RR.week_start(dt.date.today()), cur, prev)
check("1 the weekly report counts it among what the server corrected instead of refusing", cur["fixes"]["his-step-settled"] == 2 and "his-step-settled 2" in rep and "corrected by the server instead of refused: 2" in rep, rep)
wipe()

# ---- 2. said sent as plain text
def sess_gate(said, sess=AGENT):
    tok = CL.begin()
    try:
        try: got, why = gates.gate_said(said, sess, "home-agent"), ""
        except ToolError as e: got, why = None, str(e)
    finally: fx = CL.end(tok)
    return got, why, fx
got, why, fx = sess_gate("Ship it as it is")
check("2 plain text is recorded as his Acked-by with that quote, his latest message that holds the words, checked", got and len(got) == 1 and got[0]["tag"] == "Acked-by" and got[0]["quote"] == "Ship it as it is" and got[0]["msg"] == uid(14) and got[0]["checked"] is True and got[0]["session"] == AGENT, (got, why))
check("2 …counted as said-text, and the line names the message and how to give another tag", kinds(fx) == ["said-text"] and uid(14)[:8] in fx[0][1] and "Acked-by" in fx[0][1] and "list of objects" in fx[0][1], fx)
got, why, fx = sess_gate("Ship it as it is,\n   then   close the loop")
check("2 the words are found whitespace aside, in the one message that holds them", got and got[0]["msg"] == uid(13), (got, why))
got, why, fx = sess_gate("\"I pasted it into the form\"")
check("2 a JSON string holding text is text too", got and got[0]["quote"] == "I pasted it into the form" and got[0]["msg"] == uid(10), (got, why))
got, why, fx = sess_gate("I pasted the thing typed by a tool")
check("2 a message the fleet tool typed (the marker) is not his: the words are not found, refused", got is None and "no message of Oliver's own" in why and "said=[{tag" in why and fx == [], (got, why, fx))
got, why, fx = sess_gate("a peer note: ship it")
check("2 a message of peer origin is not his typed words: refused", got is None and "no message of Oliver's own" in why, (got, why))
got, why, fx = sess_gate("this was never said by him")
check("2 words no message of his holds are refused, and the refusal says how to pass the structured form", got is None and why.startswith("Refused: said: no message of Oliver's own") and "cut his sentences verbatim" in why, why)
got, why, fx = sess_gate("Ship it as it is", sess=AWAY)
check("2 a session whose transcript this box cannot read stores it unchecked, with no message, as the structured form does", got and got[0]["checked"] is False and got[0]["msg"] == "" and got[0]["tag"] == "Acked-by" and kinds(fx) == ["said-text"] and "unchecked" in fx[0][1], (got, why, fx))
got, why, fx = sess_gate("[ok, acked-by it is")
check("2 text that opens like JSON and is not is refused as before", got is None and "not valid JSON" in why and fx == [], why)
got, why, fx = sess_gate([{"tag": "Acked-by", "quote": "Ship it as it is", "msg": uid(14)}])
check("2 the structured form is as it was: checked, and no fix is told", got and got[0]["checked"] and got[0]["msg"] == uid(14) and fx == [], (got, why, fx))
got, why, fx = sess_gate("")
check("2 an empty said is as it was: nothing", got == [] and fx == [], (got, fx))
PQ = getattr(SAID, "plain_quote", lambda s: None)
check("2 plain_quote: text, a JSON string and nothing else", PQ("hello  there") == "hello  there" and PQ('"hi"') == "hi" and PQ("[a") == "" and PQ("{a") == "" and PQ("") == ""
      and PQ("123") == "" and PQ(["x"]) == "" and PQ(None) == "", None)
wipe()
item(10, next=AGENT_LINE); item(11)
out = mw(10, said="Ship it as it is", next="home-agent: go on")
text = out.content[0].text if not isinstance(out, ToolError) else str(out)
check("2 through update: plain said lands as an Acked-by of his message, the reply says so once, and the old refusal is gone", not isinstance(out, ToolError) and [e["tag"] for e in mt(10).get("said", [])] == ["Acked-by"] and mt(10)["said"][0]["msg"] == uid(14) and mt(10)["said"][0]["checked"]
      and "(fixed for you: said was sent as text" in text and text.count("fixed for you") == 1 and "send it again" not in text, (text[-500:], mt(10).get("said")))
rowsl = lines()
rep = RR.build(RR.week_start(dt.date.today()), RR.tally(rowsl), RR.tally([]))
check("2 the weekly report counts it", rowsl and rowsl[-1].get("fix") == ["said-text"] and "said-text 1" in rep, (rowsl, rep))
wipe()

# ---- 3. step="none": the way out the refusal names
r, why, fx = run(12, next="home-agent: more")
check("3 the refusal text names both ways out and no longer says what step='none' does for an item in his step", r is None and "dropped=[its number], or step='none'" in why and "releases an item" not in why and "was written by" in why, why)
r, why, fx = run(13, next="home-agent: more", step="none")
check("3 step='none', the way out that text names, now works: the write goes through and his step is dropped", r is not None and why == "" and his(13) == ["dropped"] and ("open", AGENT_LINE) in st(13), (why, st(13)))
check("3 …it is counted as step-none-applied, the line says so, and the older no-op line (changed nothing) is not told", kinds(fx) == ["step-none-applied"] and "dropped" in fx[0][1] and "paste it into the form" in fx[0][1] and "changed nothing" not in json.dumps(fx), fx)
check("3 …the item has no stored step or state to withdraw, and none is made", "step" not in mt(13) and mt(13).get("state") in (None, ""), mt(13))
r, why, fx = run(14, next=f"{HIS}\nhome-agent: more", step="none")
check("3 a his-line this very write adds is not on the checklist: step='none' leaves it refused, as the refusal said", r is None and "his step would sit hidden" in why and mt(14).get("needs") == ["home-agent"], (why, fx))
r, why, fx = run(31, step="none")
check("3 step='none' on an item that has no step of his is as before: nothing changes and the no-op line is told (step-none)", r is not None and kinds(fx) == ["step-none"] and "changed nothing" in fx[0][1], (why, fx))
r, why, fx = run(15, step="none")
check("3 step='none' alone (the guard not reached) is as before: no-op, his step stays open", r is not None and his(15) == ["open"] and kinds(fx) == ["step-none"], (why, st(15), fx))
r, why, fx = run(16, next="home-agent: more", step="none", done=[1])
check("3 step='none' beside a done of its own is as it was: the write's own mark stands", r is not None and his(16) == ["done"] and "step-none-applied" not in kinds(fx), (why, st(16), fx))
for i in (17, 18): item(i)
wipe()
out = mw(17, next="home-agent: more", step="none")
text = out.content[0].text if not isinstance(out, ToolError) else str(out)
check("3 through the middleware: the reply carries the line, once, with no invitation to send it again", "(fixed for you: step=\"none\" dropped" in text and text.count("fixed for you") == 1 and "send it again" not in text, text[-400:])
rowsl = lines()
rep = RR.build(RR.week_start(dt.date.today()), RR.tally(rowsl), RR.tally([]))
check("3 the weekly report counts it", rowsl and rowsl[-1].get("fix") == ["step-none-applied"] and "step-none-applied 1" in rep, (rowsl, rep))
wipe()

# ---- 4. every id form the update tool accepts reaches the same item: the settle path reads the item the update read
# A real board holds issue-numbered items (store/g/<n>.json, id g<n>); a writer sends g<n>, board#<n>, #<n> or the bare number. The first two groups above use the older letter-a items only.
for k, form in enumerate(("g{n}", "board#{n}", "#{n}", "{n}", " Board#{n} ")):
    n = 9201 + k; ref = form.format(n=n); g = f"g{n}"
    item(g)
    r, why, fx = run(ref, **HAND)
    check(f"4 id sent as {ref!r}: his step first, needs cleared, item handed to an agent: the write goes through and his step is dropped", r is not None and his(g) == ["dropped"] and "his-step-settled" in kinds(fx), (why, st(g), fx))
    g2 = f"g{n + 10}"
    item(g2)
    r, why, fx = run(form.format(n=n + 10), next="home-agent: more", step="none")
    check(f"4 id sent as {ref!r}: step='none' drops his step, as the refusal text says", r is not None and his(g2) == ["dropped"] and "step-none-applied" in kinds(fx), (why, st(g2), fx))
item("g9230")
r, why, fx = run("board" + chr(35) + "9230", said=[{"tag": "Acked-by", "quote": "I pasted it into the form", "msg": uid(10)}], **HAND)
check("4 id sent as board#<n> with a checked Acked-by: his step is marked done", r is not None and his("g9230") == ["done"] and "marked done" in fx[0][1], (why, st("g9230"), fx))

# ---- 5. done or dropped is decided by what the write stores as said, never by the argument as sent
def said_of(i): return mt(i).get("said") or []
for k, (label, v) in enumerate((("null", "null"), ("an empty list", []), ("[ ]", "[ ]"), ("[\\n]", "[\n]"), ("an empty text", ""))):
    i = 40 + k; item(i)
    r, why, fx = run(i, said=v, **HAND)
    check(f"5 said={label}: no word of his is stored, so his step is dropped and the line says so (never 'on record')", r is not None and his(i) == ["dropped"] and said_of(i) == [] and kinds(fx) == ["his-step-settled"]
          and "stores no said" in fx[0][1] and "checked Acked-by" not in fx[0][1] and "on record" not in fx[0][1], (why, st(i), said_of(i), fx))
item(46)
tp = T / f"transcripts/-home-x/{AGENT}.jsonl"; hold = tp.with_suffix(".away")
tp.rename(hold)
try: r, why, fx = run(46, said="I never typed this", **HAND)
finally: hold.rename(tp)
check("5 plain-text said whose transcript cannot be read here is stored unchecked: his step is dropped, and the line says the Acked-by is unchecked", r is not None and his(46) == ["dropped"]
      and [(e["tag"], e["checked"]) for e in said_of(46)] == [("Acked-by", False)] and sorted(kinds(fx)) == ["his-step-settled", "said-text"]
      and "unchecked" in dict(fx)["his-step-settled"] and "checked Acked-by of his is stored" not in dict(fx)["his-step-settled"], (why, st(46), said_of(46), fx))
item(47)
r, why, fx = run(47, said=[{"tag": "Reported-by", "quote": "Ship it as it is", "msg": uid(14)}], **HAND)
check("5 a checked Reported-by (about nothing the step says) is no proof that he did it: dropped, and the line names the tag", r is not None and his(47) == ["dropped"] and [(e["tag"], e["checked"]) for e in said_of(47)] == [("Reported-by", True)]
      and "Reported-by" in fx[0][1] and "checked Acked-by of his is stored" not in fx[0][1], (why, st(47), said_of(47), fx))
item(48)
r, why, fx = run(48, said="Ship it as it is", **HAND)
check("5 plain-text said that finds his message is a checked Acked-by: his step is marked done", r is not None and his(48) == ["done"] and [(e["tag"], e["checked"]) for e in said_of(48)] == [("Acked-by", True)]
      and sorted(kinds(fx)) == ["his-step-settled", "said-text"] and "marked done" in dict(fx)["his-step-settled"], (why, st(48), said_of(48), fx))
check("5 acked(): a checked Acked-by counts; unchecked, another tag, an acted Done-by and nothing do not",
      SS.acked([{"tag": "Acked-by", "checked": True}]) is True and SS.acked([{"tag": "Acked-by", "checked": False}]) is False and SS.acked([{"tag": "Suggested-by", "checked": True}]) is False
      and SS.acked([{"tag": "Done-by", "checked": True, "kind": "acted"}]) is False and SS.acked([{"tag": "Acked-by", "checked": True, "kind": "acted"}]) is False and SS.acked([]) is False and SS.acked(None) is False, None)

# ---- 6. step='none' on an item that stores a step: the retry keeps step='none' (the refusal text names it), so the stored step and state go with the line
item(50, needs=[], state="your-step", step="paste it into the form")
r, why, fx = run(50, step="none", needs="none", mover="home-agent")
check("6 step='none' with needs cleared and a mover on a your-step item: the write goes through (it was refused twice), his step dropped and the stored state and step gone", r is not None and his(50) == ["dropped"]
      and mt(50).get("state") != "your-step" and "step" not in mt(50) and kinds(fx) == ["step-none-applied"], (why, st(50), mt(50), fx))
item(51)
r, why, fx = run(51, step="none", needs="none", mover="home-agent")
check("6 the same write on an item with no stored step: dropped, told as applied and not as a no-op", r is not None and his(51) == ["dropped"] and kinds(fx) == ["step-none-applied"], (why, st(51), fx))

# ---- 7. the branches of step_settle that the writes above cannot tell apart, called as they are

def refusal(line=HIS, gid="a1", said=()):
    e = gates.HisStepRefusal("refused"); e.line, e.gid, e.said = line, gid, tuple(said); return e
item(60)
plan = SS.settle(refusal(gid="a60"), dict(HAND))
check("7 settle: the control, a refusal of his step on a checklist line gives the write again with the step dropped", plan is not None and plan[0]["dropped"] == [1] and plan[1] == "his-step-settled", plan)
check("7 settle: a line that is not on the checklist gives nothing (it never falls back to the first step)", SS.settle(refusal(line="Oliver: a line the write adds", gid="a60"), dict(HAND)) is None, None)
check("7 settle: a refusal that names no item gives nothing", SS.settle(refusal(gid=""), dict(HAND)) is None, None)
check("7 settle: a write that carries its own done or dropped marks stays as it was", SS.settle(refusal(gid="a60"), {**HAND, "dropped": [2]}) is None and SS.settle(refusal(gid="a60"), {**HAND, "done": [2]}) is None, None)
plan = SS.settle(refusal(gid="a60"), {"step": "none", "dropped": [3], "next": "home-agent: x"})
check("7 settle on the step='none' path merges its marks with the dropped step and drops step (no stored step)", plan is not None and plan[0]["dropped"] == [3, 1] and "step" not in plan[0] and plan[1] == "step-none-applied", plan)
item(61, needs=[], state="your-step", step="x")
plan = SS.settle(refusal(gid="a61"), {"step": "none", "next": "home-agent: x"})
check("7 settle on the step='none' path keeps step='none' where the item stores a step", plan is not None and plan[0].get("step") == "none" and plan[0]["dropped"] == [1], plan)
item(62, status="completed")
check("7 settle: a closed item gives nothing", SS.settle(refusal(gid="a62"), dict(HAND)) is None, None)
item(63, steps=[{"text": HIS, "status": "done", "by": "home-here", "at": now - 7200}, {"text": HIS, "status": "open"}, {"text": AGENT_LINE, "status": "open"}], next=f"{HIS}\n{AGENT_LINE}")
plan = SS.settle(refusal(gid="a63"), dict(HAND))
check("7 settle: the position is that of the open step", plan is not None and plan[0]["dropped"] == [2], plan)
r, why, fx = run(63, **HAND)
check("7 a done step with the same text earlier on the checklist is left as it is: the open one is the one dropped", r is not None and his(63) == ["done", "dropped"], (why, st(63), fx))
item(66, next=f"{HIS}\n{AGENT_LINE}\nhome-agent: third")
r, why, fx = run(66, step="none", needs="none", dropped=[3])
check("7 step='none' beside a dropped of its own: both marks stand (merged, not overwritten)", r is not None and [s for s, t in st(66)] == ["dropped", "open", "dropped"], (why, st(66), fx))
item(64); item(65)
r, why, fx = run(64, next="home-agent: go on", needs="clear")
check("7 needs='clear' reads as clearing needs", r is not None and his(64) == ["dropped"] and "his-step-settled" in kinds(fx), (why, st(64), fx))
r, why, fx = run(65, next="home-agent: go on", step="-")
check("7 step='-' reads as step='none'", r is not None and his(65) == ["dropped"] and "step-none-applied" in kinds(fx), (why, st(65), fx))
check("7 the no-value words: needs '-' and 'clear' clear needs; a mover or agent of '-', 'clear' or 'none' hands the item to nobody",
      SS.clears_needs({"needs": "-"}) and SS.clears_needs({"needs": "clear"}) and SS.clears_needs({"needs": "none"}) and not SS.clears_needs({"needs": "home-agent"})
      and not SS.hands_to_agent({"mover": "-"}) and not SS.hands_to_agent({"mover": "clear"}) and not SS.hands_to_agent({"agent": "none"}) and SS.hands_to_agent({"mover": "home-agent"}), None)
_real = SAID.find_by_quote
def _unreadable(*a, **k): raise PermissionError(13, "unreadable")
_real_entry = SAID.find_entry
SAID.find_by_quote = SAID.find_entry = _unreadable       # the file is found and cannot be read (a chmod 0 file reads fine for a test run as root, so it is the read that fails here)
try: got, why, fx = sess_gate("Ship it as it is")
finally: SAID.find_by_quote, SAID.find_entry = _real, _real_entry
check("7 a transcript that is there but cannot be read stores the plain said unchecked, with no message, and says so", got and got[0]["checked"] is False and got[0]["msg"] == "" and kinds(fx) == ["said-text"] and "unchecked" in fx[0][1], (got, why, fx))
def _unfix_detail():
    t = CL.begin(); CL.fixed("step-none", "n", fields=["x"]); CL.unfix("step-none"); CL.fixed("wake", "w", fields=["wake"]); fixes, detail = CL.end_detail(t); return fixes, detail
check("7 call_log.unfix also takes back the detail the fix left", _unfix_detail() == ([("wake", "w")], {"wake": {"fields": ["wake"]}}), _unfix_detail())
check("7 plain_quote: a JSON string holding spaces is trimmed", SAID.plain_quote('"  hi  "') == "hi", None)

# ---- 8. done only for his only open step; with several, every step of his that leads next is dropped and his words stay stored
SECOND = "Oliver: a second thing for the form"
def ol(i): return [s for s, t in st(i) if t.startswith("Oliver:")]      # the statuses of his lines, in order
ACK = [{"tag": "Acked-by", "quote": "Ship it as it is", "msg": uid(14)}]
item(80)
r, why, fx = run(80, said=[{"tag": "Acked-by", "quote": "pick option B please", "msg": uid(16)}], **HAND)
check("8 one step of his open, a checked Acked-by about something else: still marked done (the accepted trade-off: the only open step is the one it can be about)", r is not None and his(80) == ["done"] and "only open step" in fx[0][1], (why, st(80), fx))
item(81, next=f"{HIS}\n{SECOND}\n{AGENT_LINE}")
r, why, fx = run(81, said=ACK, **HAND)
check("8 two steps of his lead next and a checked Acked-by is stored: both are dropped, none is marked done, the line names both and says his words are stored on the item",
      r is not None and ol(81) == ["dropped", "dropped"] and kinds(fx) == ["his-step-settled"] and "paste it into the form" in fx[0][1] and "a second thing" in fx[0][1] and "2 open steps" in fx[0][1]
      and "stored on the item" in fx[0][1] and "marked done" not in fx[0][1] and [e["checked"] for e in said_of(81)] == [True], (why, st(81), fx))
item(82, next=f"{HIS}\n{SECOND}\n{AGENT_LINE}")
r, why, fx = run(82, **HAND)
check("8 two steps of his and no said: both dropped, and the line says no said is stored", r is not None and ol(82) == ["dropped", "dropped"] and "stores no said" in fx[0][1] and "stored on the item" not in fx[0][1], (why, st(82), fx))
item(83, next=f"{HIS}\n{AGENT_LINE}\n{SECOND}")
r, why, fx = run(83, said=ACK, **HAND)
check("8 a second step of his after the agent line counts: his step is dropped, not done, and the later one stays open", r is not None and ol(83) == ["dropped", "open"] and "marked done" not in fx[0][1], (why, st(83), fx))
item(84, next=f"{HIS}\n{SECOND}\n{AGENT_LINE}")
r, why, fx = run(84, next="home-agent: more", step="none")
check("8 step='none' with two steps of his leading next: both dropped in the one retry (the refusal names it as a way out)", r is not None and ol(84) == ["dropped", "dropped"] and kinds(fx) == ["step-none-applied"] and "a second thing" in fx[0][1], (why, st(84), fx))
item(85, next=f"{HIS}\n{SECOND}\n{AGENT_LINE}")
r, why, fx = run(85, done=[1], said=ACK, **HAND)
check("8 a write that names a step itself (done=[1]) is as it was: his second step is first, refused, nothing settled", r is None and "his step would sit hidden" in why and fx == [] and [s for s, t in st(85)] == ["open", "open", "open"], (why, st(85), fx))
item(86, steps=[{"text": "Oliver: an earlier thing", "status": "done", "by": "home-here", "at": now - 7200}, {"text": HIS, "status": "open"}, {"text": AGENT_LINE, "status": "open"}], next=f"{HIS}\n{AGENT_LINE}")
r, why, fx = run(86, said=ACK, **HAND)
check("8 a done step of his earlier on the checklist does not count: with one open step of his it is marked done", r is not None and his(86) == ["done"], (why, st(86), fx))

# ---- 9. the hand-off shapes, each alone, and a stored step without the your-step state and the reverse
item(90)
r, why, fx = run(90, clear_needs=True, mover="home-agent")
check("9 clear_needs=true with a mover hands the item on: his step is settled", r is not None and his(90) == ["dropped"] and "his-step-settled" in kinds(fx), (why, st(90), fx))
item(91)
r, why, fx = run(91, needs="none", agent="home-agent")
check("9 agent= alone (needs cleared) hands the item on: his step is settled", r is not None and his(91) == ["dropped"] and "his-step-settled" in kinds(fx), (why, st(91), fx))
item(92)
r, why, fx = run(92, needs="none", post_wake_mover="home-agent")
check("9 post_wake_mover= alone (needs cleared) hands the item on: his step is settled", r is not None and his(92) == ["dropped"] and "his-step-settled" in kinds(fx), (why, st(92), fx))
check("9 the hand-off and clearing tests: agent, post_wake_mover, the clear_needs flag and an empty needs list each count by themselves",
      SS.hands_to_agent({"agent": "home-agent"}) and SS.hands_to_agent({"post_wake_mover": "home-agent"}) and SS.clears_needs({"clear_needs": True}) and SS.clears_needs({"needs": []})
      and not SS.clears_needs({"clear_needs": True, "needs": ["home-agent"]}) and not SS.clears_needs({}) and not SS.hands_to_agent({}), None)
item(94, needs=[], step="paste it into the form")
r, why, fx = run(94, step="none", needs="none", mover="home-agent")
check("9 a stored step without the your-step state is withdrawn with step='none' in one call", r is not None and his(94) == ["dropped"] and "step" not in mt(94) and kinds(fx) == ["step-none-applied"], (why, st(94), mt(94), fx))
item(95, needs=[], state="your-step")
r, why, fx = run(95, step="none", needs="none", mover="home-agent")
check("9 the your-step state without a stored step is withdrawn with step='none' in one call", r is not None and his(95) == ["dropped"] and mt(95).get("state") != "your-step" and kinds(fx) == ["step-none-applied"], (why, st(95), mt(95), fx))
item(97, needs=[], step="paste it into the form"); item(98, needs=[], state="your-step"); item(96)
plan94 = SS.settle(refusal(gid="a97"), {"step": "none", "next": "home-agent: x"}); plan95 = SS.settle(refusal(gid="a98"), {"step": "none", "next": "home-agent: x"})
plan96 = SS.settle(refusal(gid="a96"), {"step": "none", "next": "home-agent: x"})
check("9 settle keeps step='none' for a stored step alone and for the state alone, and drops it for neither", plan94 is not None and plan94[0].get("step") == "none" and plan95 is not None and plan95[0].get("step") == "none" and plan96 is not None and "step" not in plan96[0], (plan94, plan95, plan96))

# ---- the plumbing
def _unfix_probe():
    t = CL.begin(); CL.fixed("wake", "w"); CL.fixed("step-none", "n"); got = CL.unfix("step-none"); left = CL.end(t); return got, left
check("call_log.unfix takes back a noted fix and gives its line, and leaves the others", getattr(CL, "unfix", None) is not None and _unfix_probe() == ("n", [("wake", "w")]) and CL.unfix("wake") == "", None)
check("the new kinds invite no resend in the reply line", all(k in CL.NO_RESEND for k in ("his-step-settled", "step-none-applied", "said-text")) and "send it again" not in CL.reply_note([("said-text", "x")]), CL.NO_RESEND)

print(("ok" if not fails else "FAILED") + f": fix_and_tell_more scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
