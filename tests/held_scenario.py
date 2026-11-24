"""Scenario test for holding notices that ask nothing of a background agent
- fixture data, no live store, no network, no server.

Covers (held.py is the store and the decision; telling.hold_notice and router_live._hold_kind are the two places that ask it):
  1. The store: a line is added and handed over once, oldest first, one line each, with a "+N more" tail past the cap (the rest comes at the next turn); an old line
     is dropped; the files are the state, so a reload of the module (a restart of the server) loses nothing; a session is found by its transcript id or its name.
  2. The decision (held.decide) on a table: only a known kind to a background agent, with no Oliver words and no ask; the switch [router] hold_notices turns it off.
  3. Each held kind from the server's own senders to a BACKGROUND agent (the builder) is not pushed and is logged "held: asks nothing (kind)": a completion
     (closed), a change to an item it neither moves nor is named on (changed), a close seen by an observer, a wake that leaves an item still after an open item
     (queue), a page-owed notice and a batch of them (page-owed). And what still wakes it, pushed as before: a completion with Oliver's words, a reopen, a change
     to an item it moves or is named on, a wake that puts the item back in its lane, a hand-off, a naming in needs, a page-debt fallback, a message not marked
     fyi, an fyi that carries [for Oliver], an fyi from Oliver.
  4. A front agent is unchanged: the same senders deliver to it (or tell nobody) as before, and a message that asks something of it (its first line carries the mark) is delivered by the same rules.
  5. The router: a pass to a background agent of a notice recorded with `hold` (page-owed, fyi) is held and ruled held with the reason (the audit's batch is not: the board item, a finding is a task and wakes its mover); the same
     pass to a front agent of a notice with Oliver's words, a ruling for Oliver, and a notice with no hold mark are delivered as before; the pass of an fyi or a page-owed notice to a front agent goes through the front gate (6 and 6b).
  6. The message tool's `fyi`: to a background agent held (the reply says so; the agent is named in no item's needs), to a project recorded with the mark, to a front
     agent held for its next turn through the front gate (it starts no turn; a router pass of one the same, and a script's, through client.py or POST /client/message, the same); a script's marked or plain message, one that says needs: decision, and one in the person's name unchanged; a marked or a plain message to a front agent, a retired or unknown name unchanged; the parameter is on the tool and the text says what it does.
  6b. A page-owed notice passed to a front agent: held for its next turn through the front gate (the line names the page, the item, who changed it and what is owed, within the cap; held once; the owed list and the write refusal unchanged);
     with the person's words or mark, a hand-back, a hook that cannot fetch, a gate that declines or fails, or the switch off, delivered as before; a background agent's, held as before.
  6c. A wake that only leaves a front agent's item after an open item (its place in the queue) asks nothing: filed for its next turn through the front gate (no turn), a wake that puts the item back in its lane and a reminder
     still pushed, a background agent's held as before (queue), a hook that cannot fetch held lines not given a turn either; and the router's pass of a peer's message addressed to a front agent on its first line: delivered
     unless its sender set the fyi flag (6k8, 6k9).
  1b. A held message arrives whole: a session's message (add(..., whole=True): the message tool's fyi, the router's pass of one, a queued line filed from a digest) keeps all its words and line breaks up to
     held.WHOLE_MAX (the message tool's own limit, MSG_MAX, and the room for its label), the lines after the first indented; a longer text is cut at a line or word boundary with a note that counts what was left out
     and says where the rest is (the place shown at most WHERE_MAX characters long, 1o3, 1v); a status notice the server writes stays one line cut at LINE_MAX, at every call site that passes no `whole` (6z1-6z4); a digest's filed
     line arrives whole (6z5); a line separator that is no newline (every character splitlines() breaks at) is made a line break, so no forged entry stands at column 0 (1t); SHOWN_MAX still caps a turn (1l-1t, 6y4-6y9).
  7. The hand-over at a turn start: the client endpoint (POST /client/held) returns the text once, a waking notice does not take the held lines with it, the lines wait
     until a turn start, a front agent's session gets nothing, and client.held_for reads the endpoint.

    tests/run-suite held        → exit 0 / 1"""
import asyncio, datetime, importlib, inspect, json, logging, os, pathlib, re, sys, threading, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="held-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', 'allowed_emails = ["oliver@example.org"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
S, A, X, B, D = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
                 "44444444-4444-4444-8444-444444444444", "66666666-6666-4666-8666-666666666666")
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for u, n in
                                                      ((S, "work-osprey"), (A, "work-osprey-main"), (X, "work-osprey-x"), (B, "home-beta"), (D, "work-osprey-docs"))}))
AGENTS = {"work-osprey-main": "Oliver's point of contact", "work-osprey-x": "builds, merges and releases the code", "work-osprey-docs": "keeps the pages"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {
    "title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "work-osprey", "status": "active", "board": [], "board_row": False,
    "updated": 1, "mirror": "https://example.invalid/alpha", "agents": AGENTS, "back_agents": {"work-osprey-x": AGENTS["work-osprey-x"], "work-osprey-docs": AGENTS["work-osprey-docs"]}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
DESC = "- A thing\n- It lives here\n- Finished when it works"
now0 = time.time()
def item(i, owner=X, status="open", desc=DESC, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": desc, "status": status,
                                                       "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600,
                                                       "metadata": {"owner": owner, **({} if {"needs", "mover", "then", "hold", "after"} & set(meta) else {"mover": owner}), "project": "projects/alpha", "next": "the next step", **meta}}))      # the creator moves nothing; a fixture item that names no mover is moved by its former creator
item(1); item(2, desc=DESC + '\n- Oliver: "ship it"'); item(3); item(4, mover="work-osprey-x"); item(5, needs=["work-osprey-x"]); item(6, observers=[X], owner=A)
item(7, owner=A); item(8, after=["a9"]); item(9)
item(10, owner=A); item(11)
item(14, owner=A, mover="Oliver")      # an item of his: a marked message must name one
item(12, owner=A, after=["a9"]); item(13, owner=A)
(T / "store/next-id").write_text("100")
push_log = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(push_log)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
def pushes(): return [json.loads(l) for l in push_log.read_text().splitlines()] if push_log.exists() else []
def settle(until=30):
    end = time.time() + until
    while time.time() < end and any(t is not threading.main_thread() and t.is_alive() for t in threading.enumerate()):
        time.sleep(0.02)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.core import config as _cfg; from stackshot.router import routing; from stackshot.waits import held; from stackshot.fleet import client
from stackshot.router import router as _router; from stackshot.router import router_live as _live
from stackshot.web import server
from stackshot.web.routes import client_api as _rt_client
from stackshot.service import messaging as _messaging
from stackshot.service import store as _service_store
from stackshot.fleet import clients as _clients
from fastmcp.exceptions import ToolError
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import wakes as wakes_svc
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import message as _wt_message
from stackshot.service import telling
from stackshot.service import handoff as handoff_svc
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None; telling.PUSH = [sys.executable, str(T / "fakepush.py")]
# A marked pass or message starts a front agent's turn only while he is talking with it (or asked it about the item). That is staged as front_hold does: the CLI's registry row of the front agent's pane on this box,
# and the prompt hook's stamp of his last message to it (`present(True)`); the gate's own function reads them. tests/front_turn_scenario.py covers the gate itself. Off by default: a marked pass or message is then not delivered to it (archived, sent to the builder, or refused), never held.
handoff_svc.CLI_SESSIONS = T / "cli"; (T / "cli").mkdir()
(T / f"cli/{os.getpid()}-work-osprey-main.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": A, "name": "work-osprey-main", "status": "idle", "startedAt": int((time.time() - 7200) * 1000)}))
def present(on):
    """He is talking with work-osprey-main (his prompt in its pane a minute ago), or is not (no stamp)."""
    stamp_ = T / "state/prompts" / A
    if on: stamp_.parent.mkdir(parents=True, exist_ok=True); stamp_.write_text(f"{time.time() - 60:.0f}\n")
    else: stamp_.unlink(missing_ok=True)
_real_note = _web_page_debts._owing_note; _web_page_debts._owing_note = lambda debtor: ""
_cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, "live": True}
KEY = "projects/alpha"
MACH = "home-test"
def gate_open():
    """The rollout gate: the builder's and the page keeper's hooks have fetched held lines (held.mark_client), and the machine holds their sessions."""
    held.mark_client(X, "work-osprey-x"); held.mark_client(D, "work-osprey-docs")
for u_, n_ in ((X, "work-osprey-x"), (A, "work-osprey-main"), (D, "work-osprey-docs"), (B, "home-beta")): _clients.register(MACH, {"uuid": u_, "name": n_})
gate_open()
def ids(session): return {X: ("work-osprey-x", X), A: ("work-osprey-main", A), D: ("work-osprey-docs", D)}[session]
def reach(session, since): return [x for x in pushes()[since:] if x[0] in ids(session)]
def hold_lines(): return [n for n in routing.read(KEY) if n.get("ruling") == "held" and str(n.get("reason", "")).startswith("held: asks nothing")]
def gone(*refs): return held.take(*refs)
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def why(fn):
    try: fn(); return ""
    except ToolError as e: return str(e)
def fresh():
    """Empty the held store and the push log between scenarios."""
    for p in held.dir_().glob("*.jsonl"): p.unlink()
    push_log.unlink(missing_ok=True)

# ---- 1. the store
fresh()
k = held.key_of("work-osprey-x")
t0 = 1_000_000_000.0
for i in range(12): held.add(k, "closed", f"line {i}", sender="s", now=t0 + i)
text = held.take(X, "work-osprey-x", now=t0 + 20)
lines = text.splitlines()
check("1a: twelve lines held, the first hand-over shows eight, oldest first, and the tail says how many wait for the next turn", len(lines) == 1 + 8 + 1 and "line 0" in lines[1] and "line 7" in lines[8] and "+4 more" in lines[-1], text)
check("1b: the header counts all twelve and says they asked nothing and come once", lines[0].startswith("[stackshot] 12 notices held for you") and "once" in lines[0], lines[0])
check("1b2: …and says they come from other sessions or stackshot, not from the person, and are no approval of anything", "other sessions" in lines[0] and "not from the person" in lines[0] and "approval" in lines[0], lines[0])
text2 = held.take(X, "work-osprey-x", now=t0 + 21)
check("1c: the next turn start gets the other four, with no tail, and nothing is repeated", "line 8" in text2 and "line 11" in text2 and "line 7" not in text2 and "more" not in text2.splitlines()[-1], text2)
check("1d: and the turn after that gets nothing", held.take(X, "work-osprey-x") == "" and held.count(X, "work-osprey-x") == 0)
held.add(k, "closed", "an old one", now=t0)
check("1e: a line older than seven days is dropped, never handed over", held.take(X, now=t0 + 8 * 86400) == "")
held.add(k, "fyi", "survives a restart", now=time.time())
held_mod = importlib.reload(held)          # a restart of the server loads the module afresh; the files are the state
check("1f: a reload of the module (a restart) loses nothing: the line is still held, found by transcript id alone", held_mod.count(X) == 1 and "survives a restart" in held_mod.take(X))
held = held_mod
for i in range(held.KEEP_MAX + 5): held.add(k, "closed", f"n{i}", now=t0 + i)
check("1g: a session keeps at most KEEP_MAX lines; the oldest go", held.count(X) == held.KEEP_MAX and {r["text"] for r in held._read(held._file(k))} == {f"n{i}" for i in range(5, held.KEEP_MAX + 5)}, held.count(X))
fresh()
held.add(held.key_of(X), "closed", "found by uuid", now=time.time())
check("1h: a session filed by its id is found by its name and the other way", "found by uuid" in held.take("", "work-osprey-x"))
held.add(held.key_of("work-osprey-x"), "closed", "x" * 600, now=time.time())
check("1i: a line is one line and is cut at LINE_MAX", len(held.take(X).splitlines()[1]) < held.LINE_MAX + 60)
held.add(k, "closed", "two\nlines  and   spaces", now=time.time())
check("1j: whitespace and newlines are folded to one line", "two lines and spaces" in held.take(X))
check("1k: the same router notice id added twice is held once (a retried ruling)", held.add(k, "page-owed", "p", nid="n1") and held.add(k, "page-owed", "p", nid="n1") and held.count(X) == 1)
fresh()

# ---- 1b. a held message arrives whole
from stackshot.core import lines as _core_lines
from stackshot.web.tools import text as _wt_text
def multi(total, per=90):
    """A multi-line text of exactly `total` characters: numbered lines of `per` characters (the last one shorter)."""
    out, i = [], 0
    while sum(len(x) + 1 for x in out) - 1 < total:
        out.append(f"line {i:03d} " + "w" * (per - 9)); i += 1
    return "\n".join(out)[:total]
M2000 = multi(2000)
def rows_of(): return held._read(held._file(k))
check("1l fixture: the message is 2000 characters over more than fifteen lines", len(M2000) == 2000 and M2000.count("\n") > 15, (len(M2000), M2000.count("\n")))
check("1l0: the limit is the message tool's own constant, not a copy of its number: held reads core/lines.MSG_MAX, which the tool text re-exports, and WHOLE_MAX is that plus the frame's room",
      held.MSG_MAX == _core_lines.MSG_MAX == _wt_text.MSG_MAX and held.WHOLE_MAX == _core_lines.MSG_MAX + held.FRAME_ROOM and held.WHOLE_MAX > held.MSG_MAX > held.LINE_MAX, (held.MSG_MAX, held.WHOLE_MAX))
from stackshot.audit import audit_run as _audit_run
from stackshot.tools import rulebook_scan as _rb_scan
import ast as _ast, inspect as _inspect
check("1l0b: …and it is ONE constant, never a second copy of the number: the object read by the held store, the tool text, the audit and the rulebook scan is core/lines.MSG_MAX itself (a re-export), and no module but core/lines.py assigns MSG_MAX",
      held.MSG_MAX is _core_lines.MSG_MAX and _wt_text.MSG_MAX is _core_lines.MSG_MAX and _audit_run.MSG_MAX is _core_lines.MSG_MAX and _rb_scan.MSG_MAX is _core_lines.MSG_MAX
      and not [m.__name__ for m in (held, _wt_text, _audit_run, _rb_scan)
               if any(isinstance(nd, _ast.Assign) and any(isinstance(t_, _ast.Name) and t_.id == "MSG_MAX" for t_ in nd.targets) for nd in _ast.walk(_ast.parse(_inspect.getsource(m))))],
      [(m.__name__, m.MSG_MAX) for m in (held, _wt_text, _audit_run, _rb_scan)])
held.add(k, "fyi", M2000, sender="s", whole=True, now=t0)
check("1l: a 2000-character message of several lines is stored whole, with its line breaks", rows_of()[-1]["text"] == M2000, (len(rows_of()[-1]["text"]), rows_of()[-1]["text"][-80:]))
shown_ = held.take(X, now=t0 + 1).splitlines()
first_, rest_ = M2000.split("\n")[0], M2000.split("\n")[1:]
check("1m: …and arrives whole in the turn: the first line after the time and the kind, every later line indented two spaces, the header counting one notice, no cut mark",
      shown_[0].startswith("[stackshot] 1 notice held for you") and shown_[1].startswith("- ") and shown_[1].endswith(" · fyi · " + first_) and shown_[2:] == ["  " + ln for ln in rest_]
      and "left out" not in "\n".join(shown_) and "…" not in "\n".join(shown_), shown_[:4])
fresh()
held.add(k, "fyi", "first\n\n  indented line   \r\nlast\n\n", whole=True, now=t0)
check("1n: line breaks, a blank line and a line's own indent are kept; trailing spaces and blank lines at the ends are trimmed", rows_of()[-1]["text"] == "first\n\n  indented line\nlast", rows_of())
check("1n2: …in the turn the blank line stays blank and each later line is indented two spaces", held.take(X, now=t0 + 1).splitlines()[1:] == [f"- {held._when(t0, t0 + 1)} · fyi · first", "", "    indented line", "  last"])
fresh()
held.add(k, "fyi", "x" * held.WHOLE_MAX, whole=True, now=t0)
check("1o: a message of exactly WHOLE_MAX characters is held whole: no cut, no note", rows_of()[-1]["text"] == "x" * held.WHOLE_MAX, (len(rows_of()[-1]["text"]), rows_of()[-1]["text"][-60:]))
fresh()
framed = "[stackshot message] from some-session (1234abcd): " + "m" * (held.MSG_MAX - 3) + "\n" + "m" * 2
held.add(k, "fyi", framed, whole=True, now=t0)
check("1o2: a message of the tool's own limit under its frame (the label and the framing words) is held whole", rows_of()[-1]["text"] == framed and len(framed) > held.MSG_MAX, len(framed))
fresh()
over = multi(held.WHOLE_MAX + 700)
held.add(k, "fyi", over, whole=True, now=t0, where="notice n77, from home-beta")
cut_ = rows_of()[-1]["text"]; head_, _, note_ = cut_.rpartition("\n"); left_ = len(over) - len(head_)
check("1p: a message above WHOLE_MAX is cut to at most WHOLE_MAX characters in all, the note whole, on a line of its own, at the end, naming where the rest is",
      len(cut_) <= held.WHOLE_MAX and note_.startswith("… (") and note_.endswith("the rest is in notice n77, from home-beta)"), (len(cut_), note_))
check("1p2: …the cut falls at a line boundary (what is kept is whole lines of the original) and the note counts the characters left out exactly",
      over.startswith(head_) and over[len(head_)] == "\n" and note_.startswith(f"… ({left_} characters left out;") and left_ > 700, (left_, note_, len(head_)))
fresh()
one_long = " ".join(["word"] * 2000)
held.add(k, "fyi", one_long, whole=True, now=t0)
cut2 = rows_of()[-1]["text"]; head2, _, note2 = cut2.rpartition("\n")
check("1p3: one long line is cut at a word boundary, never inside a word, and the note counts what was left out and names the message log",
      len(cut2) <= held.WHOLE_MAX and head2.endswith("word") and one_long.startswith(head2) and one_long[len(head2)] == " " and note2 == f"… ({len(one_long) - len(head2)} characters left out; the rest is in {held.REST_IN})", (len(cut2), head2[-20:], note2))
fresh()
no_break = "a" * (held.WHOLE_MAX + 300)
held.add(k, "fyi", no_break, whole=True, now=t0)
cut3 = rows_of()[-1]["text"]; head3, _, note3 = cut3.rpartition("\n")
check("1p4: a text with no break at all is cut at the limit, still closed by a whole note with the right count", len(cut3) <= held.WHOLE_MAX and note3.startswith(f"… ({len(no_break) - len(head3)} characters left out;") and note3.endswith(")"), (len(cut3), note3))
fresh()
held.add(k, "closed", M2000, sender="s", now=t0)
held.add(k, "closed", "a notice\nover two lines", sender="s", now=t0 + 1)
rows_ = rows_of(); shown_ = held.take(X, now=t0 + 2).splitlines()
check("1q: a status notice the server writes (not whole) stays one line, folded, and cut at LINE_MAX however long it is and however many line breaks it has",
      len(rows_[0]["text"]) <= held.LINE_MAX and rows_[0]["text"].endswith("…") and "\n" not in rows_[0]["text"] and rows_[1]["text"] == "a notice over two lines" and len(shown_) == 3 and not any(ln.startswith("  ") for ln in shown_), (rows_, shown_))
fresh()
for i in range(12): held.add(k, "fyi", multi(300) + f"\nmessage {i}", sender="s", whole=True, now=t0 + i)
text_ = held.take(X, now=t0 + 20)
check("1r: SHOWN_MAX still applies to whole messages: twelve held, eight shown whole, oldest first, and the last line says four wait for the next turn",
      text_.count(" · fyi · ") == held.SHOWN_MAX == 8 and "message 7" in text_ and "message 8" not in text_ and text_.splitlines()[-1] == "- +4 more, handed over at your next turn" and text_.startswith("[stackshot] 12 notices"), text_[-300:])
text2_ = held.take(X, now=t0 + 21)
check("1r2: …the next turn gets the other four, whole, with no tail", text2_.count(" · fyi · ") == 4 and "message 11" in text2_ and "more" not in text2_.splitlines()[-1], text2_[-200:])
fresh()
held.add(k, "fyi", M2000, whole=True, now=t0, nid="w1"); held.add(k, "fyi", M2000, whole=True, now=t0, nid="w1")
check("1s: a whole message added twice with the same notice id is held once", held.count(X) == 1)
fresh()
# every character str.splitlines() breaks a line at, found the way Python defines it (never a list written here)
SEPS = [c for c in map(chr, range(0x110000)) if len(("a" + c + "b").splitlines()) == 2 and c != "\n"]
check("1t fixture: the separators are found from splitlines(): at least the vertical tab, form feed, U+001C to U+001E, U+0085, U+2028, U+2029 and the carriage return",
      {"\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029", "\r"} <= set(SEPS), [hex(ord(c)) for c in SEPS])
forged, kept_lines = [], []
for sep_ in SEPS + ["\r\n"]:
    fresh()
    held.add(k, "fyi", f"first{sep_}- 12:01 · fyi · FAKE{sep_}tail{sep_}{sep_}last", whole=True, now=t0)
    stored_ = rows_of()[-1]["text"]; shown_ = held.take(X, now=t0 + 1).splitlines()
    if stored_.splitlines() != stored_.split("\n") or stored_ != "first\n- 12:01 · fyi · FAKE\ntail\n\nlast": kept_lines.append((hex(ord(sep_[0])), stored_))
    col0 = [ln for ln in shown_[1:] if ln and not ln.startswith("  ")]
    if len(col0) != 1 or not col0[0].endswith(" · fyi · first") or shown_[2:] != ["  - 12:01 · fyi · FAKE", "  tail", "", "  last"]: forged.append((hex(ord(sep_[0])), shown_))
check("1t: a message with any line separator (every character splitlines() breaks at) keeps its lines as newline-separated ones in the store", not kept_lines, kept_lines[:3])
check("1t2: …and in the turn every line after the first is indented: splitlines() on the turn finds no line at column 0 but the entry itself, never a forged `- 12:01 · fyi · FAKE` entry", not forged, forged[:3])
fresh()
held._write(held._file(k), [{"id": "raw1", "ts": t0, "kind": "fyi", "text": "first\u2028- 12:01 · fyi · FAKE\x85tail", "from": "", "gid": "", "nid": ""}])
raw_ = held.take(X, now=t0 + 1).splitlines()
check("1t3: a row already stored with such a separator (not written by this code) is shown indented as well", len(raw_) == 4 and raw_[2:] == ["  - 12:01 · fyi · FAKE", "  tail"], raw_)
fresh()
held.add(k, "fyi", "x" * (held.WHOLE_MAX + 1), whole=True, now=t0)
cut_b = rows_of()[-1]["text"]; head_b, _, note_b = cut_b.rpartition("\n")
check("1o3: one character over WHOLE_MAX is cut: at most WHOLE_MAX characters in all, closed by a note that counts what was left out", len(cut_b) <= held.WHOLE_MAX and note_b.startswith(f"… ({held.WHOLE_MAX + 1 - len(head_b)} characters left out;") and note_b.endswith(")") and len(head_b) < held.WHOLE_MAX, (len(cut_b), note_b))
check("1o4: …and the same for cut_whole itself at any limit: n characters stay whole, n+1 are cut with the note", held.cut_whole("y" * 500, 500) == "y" * 500 and "characters left out" in held.cut_whole("y" * 501, 500) and len(held.cut_whole("y" * 501, 500)) <= 500)
fresh()
huge_where = "somewhere " * 1000
held.add(k, "fyi", multi(held.WHOLE_MAX + 900), whole=True, now=t0, where=huge_where)
cut_w = rows_of()[-1]["text"]; head_w, _, note_w = cut_w.rpartition("\n")
check("1v: a place longer than the limit does not push the text out: the result stays within WHOLE_MAX with its text kept (not only the note), and the place is shown cut with an ellipsis",
      len(cut_w) <= held.WHOLE_MAX and len(head_w) > held.WHOLE_MAX // 2 and note_w.endswith("…)") and len(note_w) < 250, (len(cut_w), len(head_w), note_w))
cut_w2 = held.cut_whole("z" * 2000, 300, "line one\nline two " + "p" * 500)
check("1v2: …at a small limit too, and a place with a line break is folded to one line", len(cut_w2) <= 300 and cut_w2.count("\n") == 1 and "line one line two" in cut_w2, (len(cut_w2), cut_w2[-160:]))
fresh()

# ---- 2. the decision
D_ = lambda kind, **kw: held.decide(kind, **{"is_background": True, **kw})
check("2a: a known kind to a background agent that asks nothing is held", all(D_(kd) == kd for kd in held.KINDS))
check("2b: a front agent, an unknown kind, an empty kind are delivered", D_("closed", is_background=False) == "" and D_("wake") == "" and D_("") == "")
check("2c: Oliver's words, an ask, the owner as sender, and the marks [for Oliver] and needs: decision deliver", D_("closed", owner_words=True) == "" and D_("changed", asks=True) == ""
      and D_("fyi", sender_is_owner=True) == "" and D_("closed", text="[for Oliver] look") == "" and D_("closed", text="it now needs: decision") == "")
_cfg.CFG["router"]["hold_notices"] = False
check("2d: [router] hold_notices = false delivers everything", D_("closed") == "")
_cfg.CFG["router"].pop("hold_notices")
check("2e: …and the default is on", D_("closed") == "closed")

# ---- 3. the server's senders to a BACKGROUND agent (the builder, work-osprey-x)
def sent_to(who, since): return reach(who, since)
def logged(kind): return [n for n in hold_lines() if n.get("reason") == f"held: asks nothing ({kind})"]
# closed: a plain completion of an item the builder owns, by another session
fresh(); n0 = len(pushes()); h0 = len(hold_lines()); it = _service_store._load("a1")
out = telling.tell_owner("a1", it, "was completed (done)", B, close=True); settle()
check("3a: a completion of the builder's item by another session is not pushed to it", reach(X, n0) == [], pushes()[n0:])
check("…it is held, one line, for its next turn", held.count(X) == 1 and "item 1" in held.take(X), held.count(X))
check("…and the routing log says held: asks nothing (closed), logged by the server (not delivered to anyone)", len(logged("closed")) == 1 and logged("closed")[0].get("to", "") == "" and logged("closed")[0].get("ruled_by") == routing.AUTO_RULER, hold_lines())
check("…and its ruling line carries the kind of hold (next_turn), so it stays held", [d.get("next_turn") for d in json.loads("[" + ",".join(routing._file(KEY).read_text().splitlines()) + "]") if d.get("ruling") == "held" and d.get("reason") == "held: asks nothing (closed)"] == ["closed"], routing._file(KEY).read_text()[-400:])
fresh(); n0 = len(pushes()); it = _service_store._load("a2")
telling.tell_owner("a2", it, "was completed (done)", B, close=True); settle()
check("3b negative: the same completion with Oliver's words on the item (Oliver: \"ship it\") is pushed to the builder as before", len(reach(X, n0)) == 1 and held.count(X) == 0, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); it = _service_store._load("a1")
telling.tell_owner("a1", it, "was reopened (next: more work)", B); settle()
check("3c negative: a reopen is pushed (it asks the builder to look at the item again)", len(reach(X, n0)) == 1 and held.count(X) == 0, pushes()[n0:])
fresh(); n0 = len(pushes()); it = _service_store._load("a1")
telling.tell_owner("a1", it, "now names work-osprey-docs in its needs too, handed over", B); settle()
check("3d negative: a notice that is neither a completion nor a change (a naming in needs told to the owner) is pushed", len(reach(X, n0)) == 1 and held.count(X) == 0, pushes()[n0:])

# changed: another session set next on an item the builder owns but does not move, and on one it moves, and on one it is named on
def changed(gid, **after):
    it_ = _service_store._load(gid); before = dict(it_["metadata"]); it_["metadata"] = {**before, "next": "home-beta: a new line"}
    return telling.tell_owner_change(gid, it_, before, B, False, False, False, False)
fresh(); n0 = len(pushes()); telling.OWNER_HEARD.clear()
item(3, hold=True, wake="2099-01-01", hold_set={"by": "t", "at": now0}, then=X)          # the builder holds it (it comes to the builder after the wait) but does not move it
changed("a3"); settle()
check("3e: another session's change to next on an item the builder owns and does not move is held (changed), not pushed", reach(X, n0) == [] and held.count(X) == 1 and len(logged("changed")) >= 1, (pushes()[n0:], held.count(X)))
for gid, what in (("a4", "an item it moves"), ("a5", "an item it is named on in needs")):
    fresh(); n0 = len(pushes()); telling.OWNER_HEARD.clear()
    changed(gid); settle()
    check(f"3f negative: the same change to {what} is pushed (it may be an instruction)", len(reach(X, n0)) == 1 and held.count(X) == 0, (gid, pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); telling.OWNER_HEARD.clear(); it = _service_store._load("a1"); before = dict(it["metadata"]); it["metadata"] = {**before, "outcome": "done"}; it["status"] = "completed"
telling.tell_owner_change("a1", it, before, B, True, False, False, False); settle()
check("3g: a close by another session told through the change notice is held (closed)", reach(X, n0) == [] and held.count(X) == 1, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); telling.OWNER_HEARD.clear(); it = _service_store._load("a1"); before = dict(it["metadata"])
telling.tell_owner_change("a1", it, before, B, False, False, False, True); settle()
check("3h negative: a reopen told through the change notice is pushed", len(reach(X, n0)) == 1 and held.count(X) == 0, pushes()[n0:])

# an observer's close
fresh(); n0 = len(pushes()); it = _service_store._load("a6")
telling.tell_observers("a6", it, "was completed (done)", B); settle()
check("3i: a background observer's completion notice is held (closed)", reach(X, n0) == [] and held.count(X) == 1, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); it = _service_store._load("a6")
telling.tell_observers("a6", it, "was reopened (next: again)", B); settle()
check("3j negative: …and a reopen is pushed to it", len(reach(X, n0)) == 1, pushes()[n0:])

# queue: a wake that leaves the item still after an open item
item(8, after=["a9"], owner=X)
fresh(); n0 = len(pushes()); it = _service_store._load("a8")
wakes_svc.wake_tell(X, [("a8", it, "woke (wake 10-29)", "as its keeper of record", False)]); settle()
check("3k: a wake that leaves the builder's item still after an open item (its place in the queue) is held (queue), not pushed", reach(X, n0) == [] and held.count(X) == 1 and len(logged("queue")) == 1, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); it = _service_store._load("a1")
wakes_svc.wake_tell(X, [("a1", it, "woke (wake 10-29)", "as its keeper of record", False)]); settle()
check("3l negative: a wake that puts the item back in its lane is pushed", len(reach(X, n0)) == 1 and held.count(X) == 0, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); it = _service_store._load("a8")
wakes_svc.wake_tell(X, [("a8", it, "reminder", "as its keeper of record", True)]); settle()
check("3m negative: a reminder (an active item the owner is asked to close or refresh) is pushed even when the item has an after", len(reach(X, n0)) == 1, pushes()[n0:])

# page-owed: the keeper that is a background agent
fresh(); n0 = len(pushes()); it = _service_store._load("a1")
out = telling.pilot_relay(KEY, "a1", it, "completed (done)", B, "work-osprey-docs", "agent"); settle()
check("3n: a page-owed notice that hands the debt to the keeper ('the page update is yours as its agent') is an ask: delivered to the background keeper, not held",
      len(reach(D, n0)) == 1 and held.count(D) == 0 and not logged("page-owed"), (out, pushes()[n0:], held.count(D)))
fresh(); n0 = len(pushes()); it = _service_store._load("a1")
out = telling.pilot_relay(KEY, "a1", it, "completed (done)", B, "work-osprey-docs", "name", tail="home-beta left its page update undone past 30 min, so it is yours as its keeper"); settle()
check("3n2: …and so is the fallback after the writer left it undone ('…so it is yours as its keeper'): delivered", len(reach(D, n0)) == 1 and held.count(D) == 0, (pushes()[n0:], held.count(D)))
fresh(); n0 = len(pushes()); it = _service_store._load("a1")
out = telling.pilot_relay(KEY, "a1", it, "completed (done)", B, "work-osprey-docs", "agent",
                          tail="no page update is owed by you (home-beta writes it); this notice is for the anchors scoped to board#1"); settle()
check("3n3: a page-owed notice that owes the keeper nothing (the anchors tail) is held (page-owed), and the writer's reply says it reads it at its next turn",
      reach(D, n0) == [] and held.count(D) == 1 and len(logged("page-owed")) == 1 and "next turn" in out, (out, pushes()[n0:], held.count(D)))
fresh(); n0 = len(pushes())
rows = [(KEY, "a1", _service_store._load("a1"), "completed (done)", B), (KEY, "a3", _service_store._load("a3"), "changed (next)", B)]
ids_ = telling.pilot_relay_many("work-osprey-docs", rows); settle()
check("3o: a batch of page debts moved to a background keeper ('…so it is yours as its keeper') is delivered, one message, nothing held", len(reach(D, n0)) == 1 and held.count(D) == 0, (pushes()[n0:], held.count(D)))
fresh(); n0 = len(pushes())
telling.pilot_relay_many("work-osprey-docs", rows, head="[board] the page debt call could not apply an edit"); settle()
check("3p negative: the page-debt fallback, which names its recipient, is pushed", len(reach(D, n0)) == 1 and held.count(D) == 0, (pushes()[n0:], held.count(D)))

# what still wakes it
fresh(); n0 = len(pushes()); it = _service_store._load("a1")
telling.tell_needed("a1", it, [X], B); settle()
check("3q negative: a naming in needs wakes the builder", len(reach(X, n0)) == 1 and held.count(X) == 0, pushes()[n0:])
fresh(); n0 = len(pushes()); th = telling.tell_woken("a1", X, "[stackshot] a1 handed to you", tag="handoff"); settle()
check("3r negative: a hand-off notice (no hold kind) is pushed", len(reach(X, n0)) == 1 and held.count(X) == 0, pushes()[n0:])
fresh(); n0 = len(pushes()); th = telling.tell_or_hold("a1", X, "[stackshot] a1 closed by home-beta", "closed", tag="owner"); settle()
check("3s: the one decision point holds a kind the sender names (tag owner, hold closed) and returns no thread", th is None and reach(X, n0) == [] and held.count(X) == 1)
fresh(); n0 = len(pushes()); th = telling.tell_or_hold("a1", X, "[stackshot] a1 closed by home-beta [for Oliver] look", "closed", tag="owner"); settle()
check("3t negative: …unless the text carries [for Oliver]", len(reach(X, n0)) == 1 and held.count(X) == 0)
fresh(); n0 = len(pushes()); th = telling.tell_or_hold("a1", X, "[stackshot] a1 closed", "not-a-kind", tag="owner"); settle()
check("3u negative: …or the kind is not one it knows (unsure delivers)", len(reach(X, n0)) == 1 and held.count(X) == 0)
_cfg.CFG["router"]["hold_notices"] = False
fresh(); n0 = len(pushes()); it = _service_store._load("a1"); telling.tell_owner("a1", it, "was completed (done)", B, close=True); settle()
_cfg.CFG["router"].pop("hold_notices")
check("3v: with [router] hold_notices = false the completion is pushed as before", len(reach(X, n0)) == 1 and held.count(X) == 0, pushes()[n0:])

# a close whose outcome is not done tells a builder to stop: delivered
for what_ in ("was completed (dropped)", "was completed (superseded by board#2)"):
    fresh(); n0 = len(pushes()); it = _service_store._load("a1")
    telling.tell_owner("a1", it, what_, B, close=True); settle()
    check(f"3w negative: {what_} is pushed to the builder that owns the item (it must stop), not held", len(reach(X, n0)) == 1 and held.count(X) == 0, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); it = _service_store._load("a6")
telling.tell_observers("a6", it, "was completed (dropped)", B); settle()
check("3x negative: …and a dropped item is pushed to a background observer too", len(reach(X, n0)) == 1 and held.count(X) == 0, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); telling.OWNER_HEARD.clear(); it = _service_store._load("a1"); before = dict(it["metadata"]); it["metadata"] = {**before, "outcome": "dropped"}; it["status"] = "completed"
telling.tell_owner_change("a1", it, before, B, True, False, False, False); settle()
check("3y negative: a drop told through the change notice is pushed", len(reach(X, n0)) == 1 and held.count(X) == 0, (pushes()[n0:], held.count(X)))

# the rollout gate: a session whose hook has not fetched held lines (an old checkout, a cloud session, no turn since the update) gets everything as today
os.unlink(held.clients_file())
check("3z: can_fetch is false for a session never seen asking, and for a cloud session id", not held.can_fetch(X) and not held.can_fetch("work-osprey-x") and not held.can_fetch("cse_0123456789abcdef"))
fresh(); n0 = len(pushes()); it = _service_store._load("a1")
telling.tell_owner("a1", it, "was completed (done)", B, close=True); settle()
check("3z1 gate: a completion to a background agent whose hook does not fetch held lines is pushed as today, nothing is stranded", len(reach(X, n0)) == 1 and held.count(X) == 0, (pushes()[n0:], held.count(X)))
fresh(); n0 = len(pushes()); out = _messaging._message("work-osprey-x", "the PR is merged, nothing to do", "home-beta", fyi=True); settle()
check("3z2 gate: an fyi to it is delivered as an ordinary message", out.startswith("delivered") and len(reach(X, n0)) == 1 and held.count(X) == 0, out)
check("3z3 gate: held.decide with a target that cannot fetch delivers; without a target it decides on the kind alone", held.decide("closed", is_background=True, target="work-osprey-x") == "" and held.decide("closed", is_background=True) == "closed")
gate_open()
check("3z4 gate: once its hook has asked, can_fetch is true by transcript id and by name", held.can_fetch(X) and held.can_fetch("work-osprey-x") and not held.can_fetch(A))
check("3z5 gate: a mark older than CLIENT_DAYS no longer counts", held.can_fetch(X, now=time.time() + (held.CLIENT_DAYS + 1) * 86400) is False)
gate_open()

# ---- 4. a FRONT agent is unchanged
fresh(); n0 = len(pushes()); it = _service_store._load("a7")
out = telling.tell_owner("a7", it, "was completed (done)", B, close=True); settle()
check("4a: a completion of a front agent's item tells nobody and holds nothing, as before", reach(A, n0) == [] and "front agent" in out and held.count(A) == 0, out)
check("…(and the front agent's id has no held line)", held.count(A, "work-osprey-main") == 0)
fresh(); n0 = len(pushes()); it = _service_store._load("a7")
for kind in ("closed", "changed", "queue", "page-owed", "fyi"):
    check(f"4b: hold_notice never holds a notice to a front agent (kind {kind})", telling.hold_notice(A, "text", kind) is False)
check("4c: …and holds nothing for a session that no page lists", telling.hold_notice(B, "text", "closed") is False and held.count(B) == 0)
check("4d: a front agent that keeps the page gets no page-owed notice from pilot_relay, as before (and nothing is held)", telling.pilot_relay(KEY, "a7", it, "completed (done)", B, "work-osprey-main", "name") == "" and held.count(A) == 0)

# ---- 5. the router
def notice(nid, text, hold="", **kw):
    n = {"id": nid, "ts": time.time(), "kind": "board", "label": "board board#1", "who": "home-beta", "to": "", "target": "for home-beta", "pilot": True, "live": True, "text": text, "url": "", "anchor": "", **kw}
    if hold: n["hold"] = hold
    return n
def rec(text, hold="", **kw):
    nid = routing.record(KEY, kind="board", to="", label="board board#1", who="home-beta", text=text, target="for home-beta", pilot=True, live=True, hold=hold, **kw)
    _live.stash(nid, text)
    return next(n for n in routing.read(KEY) if n["id"] == nid)
cx = _router.Context()
def act(n, target, **ln):
    line = {"id": n["id"], "ruling": "passed", "target": target, "reason": "the page update is owed", "for_owner": False, "source": "code", "rule": "test", "item": "", **ln}
    return _live._act(n, KEY, KEY, line, cx, {})
fresh(); n0 = len(pushes()); n = rec("[board] board#1 completed (done) by home-beta — [home] item 1 (projects/alpha) — the page update is owed", hold="page-owed")
res = act(n, "work-osprey-docs")
rr = next(x for x in routing.read(KEY) if x["id"] == n["id"])
check("5a: the router passes a notice recorded with hold=page-owed to a background agent: held, not delivered, ruled held with the reason", reach(D, n0) == [] and held.count(D) == 1
      and res["status"] == "ruled" and res["ruling"] == "held" and rr.get("ruling") == "held" and rr.get("reason") == "held: asks nothing (page-owed)" and rr.get("ruled_by") == _live.BY, (res, rr, pushes()[n0:]))
check("5a2: …the ruling line carries the kind of hold (next_turn), which keeps it held and apart from the router's archived ruling", [d.get("next_turn") for d in json.loads("[" + ",".join(routing._file(KEY).read_text().splitlines()) + "]") if d.get("id") == n["id"] and "ruling" in d and "kind" not in d] == ["page-owed"], routing._file(KEY).read_text()[-400:])
check("…the stored line is the notice's text, one line", "page update is owed" in held.take(D, "work-osprey-docs"))
fresh(); n0 = len(pushes()); n = rec("[board] board#1 completed (done) by home-beta — the page update is owed", hold="page-owed"); res = act(n, "work-osprey-main")
check("5b: the same notice passed to a FRONT agent asks nothing of him, so it starts no turn and is not held for its next turn either: archived (nothing names an item whose work is a builder's)", reach(A, n0) == [] and res["ruling"] == "archived" and held.count(A) == 0, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = rec("[board] board#1 completed — [for Oliver] look at the page", hold="page-owed"); res = act(n, "work-osprey-docs")
check("5c negative: a notice with Oliver's mark is delivered whatever the hold says", len(reach(D, n0)) == 1 and res["ruling"] == "passed" and held.count(D) == 0, res)
fresh(); n0 = len(pushes()); n = rec("[board] board#1 completed", hold="page-owed"); res = act(n, "work-osprey-docs", for_owner=True)
check("5d negative: a ruling marked for Oliver is delivered", len(reach(D, n0)) == 1 and res["ruling"] == "passed", res)
fresh(); n0 = len(pushes()); n = rec("[board] board#1 handed back to you"); res = act(n, "work-osprey-x")
check("5e negative: a notice with no hold mark and no audit rule (any other pass) is delivered as now", len(reach(X, n0)) == 1 and res["ruling"] == "passed" and held.count(X) == 0, res)
fresh(); n0 = len(pushes()); n = rec("a hand-back to its owner", hold="page-owed", handback=True); res = act(n, "work-osprey-x")
check("5f negative: a hand-back (an item given back to its owner) is never held, whatever the mark", len(reach(X, n0)) == 1 and res["ruling"] == "passed", res)
# the audit's batch: one line per item, split by owner
body = "[stackshot] Audit of Thu Oct 29th: 2 findings\na1 · stale · no update for 9 days\na10 · stale · no update for 12 days"
fresh(); n0 = len(pushes())
nid_ = routing.record(KEY, kind="message", to="", label="message to projects/alpha", who="falcon-audit", text=body, target="project-wide", pilot=True, live=True); _live.stash(nid_, body)
n = next(x for x in routing.read(KEY) if x["id"] == nid_)
cx = _router.Context()
ln = _router.audit_rule(KEY, n, KEY, cx)
check("5g: the audit's batch finding is split by item keeper of record (the rule audit-owners)", ln and ln.get("rule") == "audit-owners" and set(ln["split"]) == {"work-osprey-x", "work-osprey-main"}, ln)
if ln:
    res = _live._act(n, KEY, KEY, ln, cx, {})
    check("5h: the lines for the background keeper are delivered at once (a finding is a task, never held); the front keeper's line is archived: he did not ask it to tell him about a10, and a finding asks nothing of him", held.count(X) == 0 and len(reach(X, n0)) == 1 and reach(A, n0) == [] and held.count(A) == 0 and res["ruling"] == "passed"
      and "work-osprey-main: archived" in str(res.get("outcome")), (res, pushes()[n0:], held.count(X)))
    fresh(); n0 = len(pushes()); nid2 = routing.record(KEY, kind="message", to="", label="message to projects/alpha", who="falcon-audit", text=body, target="project-wide", pilot=True, live=True)
    _live.stash(nid2, body); n2 = next(x for x in routing.read(KEY) if x["id"] == nid2)
    only = {**ln, "id": nid2, "target": "work-osprey-x", "split": {"work-osprey-x": ["a1"]}}
    res = _live._act(n2, KEY, KEY, only, cx, {})
    rr = next(x for x in routing.read(KEY) if x["id"] == nid2)
    check("5i: a batch whose every keeper is background is delivered to it and ruled passed, not held", res["ruling"] == "passed" and rr.get("ruling") == "passed" and rr.get("ruled_to") == "work-osprey-x" and len(reach(X, n0)) == 1 and held.count(X) == 0, (res, rr))
    fresh(); n0 = len(pushes()); nid3 = routing.record(KEY, kind="message", to="", label="message to projects/alpha", who="falcon-audit", text=body, target="project-wide", pilot=True, live=True, hold="fyi")
    _live.stash(nid3, body); n3 = next(x for x in routing.read(KEY) if x["id"] == nid3)
    res = _live._act(n3, KEY, KEY, {**ln, "id": nid3}, cx, {})
    check("5j: an audit batch whose sender marked it fyi is still delivered to the background keeper: a finding is a task", len(reach(X, n0)) == 1 and held.count(X) == 0 and res["ruling"] == "passed", (res, pushes()[n0:], held.count(X)))

# ---- 6. the message tool's fyi
check("6a: the message tool takes fyi (default false) and its text says what it does", "fyi" in inspect.signature(_wt_message.stackshot_message).parameters
      and inspect.signature(_wt_message.stackshot_message).parameters["fyi"].default is False)
desc = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == "message").description or ""
check("…and its first sentence about a front agent's mark names the fyi exception", "(except fyi=true, below)" in desc, desc[:1800])
check("…the description names fyi and its effect on a background agent, a project and a front agent", bool(desc) and ("fyi=true" in desc and "next turn" in desc and "to a front agent it is held for that agent's next turn" in desc and "asks nothing of its recipient is sent with fyi" in desc), desc[-600:])
fresh(); n0 = len(pushes()); out = _messaging._message("work-osprey-x", "the PR is merged, nothing to do", "home-beta", fyi=True); settle()
check("6b: an fyi to a background agent is held: the reply says so, nothing is pushed, the line waits", out.startswith("held for work-osprey-x's next turn") and reach(X, n0) == [] and held.count(X) == 1 and len(logged("fyi")) == 1, (out, pushes()[n0:]))
check("…and the message log records it as an fyi that was not delivered", any(json.loads(l).get("fyi") and "held" in json.loads(l)["outcome"] for l in _messaging.MSG_LOG.read_text().splitlines()))
fresh(); n0 = len(pushes()); out = _messaging._message("work-osprey-x", "the PR is merged, nothing to do", "home-beta"); settle()
check("6c negative: the same message without fyi is delivered", out.startswith("delivered") and len(reach(X, n0)) == 1 and held.count(X) == 0, out)
fresh(); n0 = len(pushes()); out = _messaging._message("work-osprey-x", "[for Oliver] the PR is merged, a decision for you", "home-beta", fyi=True); settle()
check("6d negative: an fyi that carries [for Oliver] is delivered", out.startswith("delivered") and len(reach(X, n0)) == 1 and held.count(X) == 0, out)
fresh(); n0 = len(pushes()); out = _messaging._message("work-osprey-x", "go on with a1", "Oliver", fyi=True); settle()
check("6e negative: an fyi from Oliver himself is an ordinary message", out.startswith("delivered") and len(reach(X, n0)) >= 1 and held.count(X) == 0, out)
item(11); fresh(); n0 = len(pushes()); out = _messaging._message("work-osprey-x", "FYI done with a11", "home-beta", fyi=True); settle()
check("6f: an fyi names the builder in no item's needs (it asked nothing), where the same words without fyi do", out.startswith("held") and "work-osprey-x" not in str(rd(11)["metadata"].get("needs")) and "named" not in out, out)
fresh(); out = _messaging._message("work-osprey-x", "done with a11", "home-beta"); settle()
check("…(the control: without fyi the plain item id names it)", "work-osprey-x" in str(rd(11)["metadata"].get("needs")), rd(11)["metadata"])
fresh(); n0 = len(pushes()); out = why(lambda: _messaging._message("work-osprey-main", "the PR is merged", "home-beta"))
check("6g: a plain message to a FRONT agent without the mark is refused by the gate (no flag)", out.startswith("Refused") and "front agent" in out and reach(A, n0) == [], out)
present(True); fresh(); n0 = len(pushes()); out = _messaging._message("work-osprey-main", "[for Oliver] a14 pick a or b", "home-beta", fyi=True); settle()
check("6h: a marked message to it, while he is talking with it, is delivered as it would be without the flag (it asks something)", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0, out)
fresh(); n0 = len(pushes()); out = _messaging._message("work-osprey-main", "[for Oliver] a14 pick a or b", "home-beta"); settle()
check("6h2 control: …and without the flag the same", out.startswith("delivered") and len(reach(A, n0)) == 1 and held.count(A) == 0, out)
present(False); fresh(); n0 = len(pushes()); out = why(lambda: _messaging._message("work-osprey-main", "[for Oliver] a14 pick a or b", "home-beta", fyi=True))
check("6h3: …and while he is not, it is refused, never held (the flag changes nothing: a marked message needs him)", out.startswith("Refused") and "nothing is held" in out and reach(A, n0) == [] and held.count(A) == 0, out)
fresh(); n0 = len(pushes()); out = why(lambda: _messaging._message("work-osprey-main", "it now needs: decision", "home-beta", fyi=True))
check("6h3: an fyi that says needs: decision is no fyi: refused without the mark, as without the flag", out.startswith("Refused") and reach(A, n0) == [] and held.count(A) == 0, out)

# ---- 6b. an fyi to a FRONT agent goes through the front gate: held for its next turn, no turn of its own
def msg(*a, **k):
    try: return _messaging._message(*a, **k)
    except ToolError as e: return str(e)
def fq_log(i): return [x.get("text", "") for x in ((rd(i)["metadata"].get("front_quiet") or {}).get("log") or [])]
held.mark_client(A, "work-osprey-main")
fresh(); n0 = len(pushes()); out = msg("work-osprey-main", "the PR is merged, nothing for you to do", "home-beta", fyi=True); settle()
check("6m: a peer's fyi to a front agent (no mark) starts no turn: nothing is pushed, one line is held, the reply says so", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1 and "cut" not in out, (out, pushes()[n0:], held.count(A)))
got = held.take(A, "work-osprey-main")
check("6n: …it is handed over with the agent's next turn, once, with the sender and the words", "the PR is merged" in got and "home-beta" in got and held.take(A, "work-osprey-main") == "", got)
check("6n2: …and the message log records it as an fyi held, not delivered", any(json.loads(l).get("fyi") and json.loads(l)["to"] == "work-osprey-main" and "held" in json.loads(l)["outcome"] for l in _messaging.MSG_LOG.read_text().splitlines()))
fresh(); n0 = len(pushes()); before_log = fq_log(10); out = msg("work-osprey-main", "a10 is merged, nothing for you to do", "home-beta", fyi=True); settle()
check("6o: an fyi that names an item the board carries: held for the next turn, and the item gets its board line", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1
      and len(fq_log(10)) == len(before_log) + 1 and "hears of it on his next turn" in fq_log(10)[-1] and "merged" in fq_log(10)[-1], (out, fq_log(10)))
# ---- 6c. a wake that leaves a front agent's item still after an open item is its place in the queue: nothing to do yet, so it rides the next turn and starts none
fresh(); n0 = len(pushes()); it = _service_store._load("a12"); b0 = len(fq_log(12))
wakes_svc.wake_tell(A, [("a12", it, "woke (wake 10-29)", "as its keeper of record", False)]); settle()
check("6c1: a wake that leaves a front agent's item still after an open item starts no turn: nothing pushed, one line held for its next turn", reach(A, n0) == [] and held.count(A) == 1, (pushes()[n0:], held.count(A)))
check("6c2: …the held line says where the item stands, and the item gets its board line", "still after" in held.take(A, "work-osprey-main") and len(fq_log(12)) == b0 + 1 and "hears of it on his next turn" in fq_log(12)[-1], fq_log(12))
fresh(); n0 = len(pushes()); it = _service_store._load("a13")
wakes_svc.wake_tell(A, [("a13", it, "woke (wake 10-29)", "as its keeper of record", False)]); settle()
check("6c3 negative: a wake that puts a front agent's item back in its lane, with nothing in it for him, is a progress notice: no turn, nothing pushed (telling.tell_own_move)", reach(A, n0) == [], (pushes()[n0:], held.count(A)))
held.take(A, "work-osprey-main")
fresh(); n0 = len(pushes()); it_d = {**it, "metadata": {**it["metadata"], "needs": ["decision"]}}
wakes_svc.wake_tell(A, [("a13", it_d, "woke (wake 10-29)", "as its keeper of record", False)]); settle()
check("6c3 negative: …the same wake of an item that waits on his decision asks it to act: pushed as before, nothing held", len(reach(A, n0)) == 1 and held.count(A) == 0, (pushes()[n0:], held.count(A)))
fresh(); n0 = len(pushes()); it = _service_store._load("a12")
wakes_svc.wake_tell(A, [("a12", it, "reminder", "as its keeper of record", True)]); settle()
check("6c4 negative: a reminder to a front agent (an active item it is asked to close or refresh), nothing in it for him, is a progress notice even when the item has an after: nothing pushed", reach(A, n0) == [], (pushes()[n0:], held.count(A)))
held.take(A, "work-osprey-main")
fresh(); n0 = len(pushes()); it_d = {**it, "metadata": {**it["metadata"], "needs": ["decision"]}}
wakes_svc.wake_tell(A, [("a12", it_d, "reminder", "as its keeper of record", True)]); settle()
check("6c4 negative: …with his decision in it the reminder is pushed even when the item has an after", len(reach(A, n0)) == 1 and held.count(A) == 0, (pushes()[n0:], held.count(A)))
fresh(); n0 = len(pushes()); it = _service_store._load("a8")
wakes_svc.wake_tell(X, [("a8", it, "woke (wake 10-29)", "as its keeper of record", False)]); settle()
check("6c5: a background agent is unchanged: its queue-place wake is held as before (queue), no board line", reach(X, n0) == [] and held.count(X) == 1 and len(logged("queue")) >= 1, (pushes()[n0:], held.count(X)))
os.unlink(held.clients_file()); gate_open()
fresh(); n0 = len(pushes()); it = _service_store._load("a12")
wakes_svc.wake_tell(A, [("a12", it, "woke (wake 10-29)", "as its keeper of record", False)]); settle()
check("6c6: a front agent whose hook does not fetch held lines is not given a turn for it either: nothing pushed or held (the board line keeps the news)", reach(A, n0) == [] and held.count(A) == 0, (pushes()[n0:], held.count(A)))
held.mark_client(A, "work-osprey-main")

os.unlink(held.clients_file()); gate_open()
fresh(); n0 = len(pushes()); out = msg("work-osprey-main", "the PR is merged, nothing for you to do", "home-beta", fyi=True); settle()
check("6p: a front agent whose hook does not fetch held lines is not given a turn either: not passed on, nothing pushed or held, the reply says what to do", out.startswith("not passed on") and reach(A, n0) == [] and held.count(A) == 0 and "without fyi" in out, (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg("work-osprey-main", "a10 is merged, nothing for you to do", "home-beta", fyi=True); settle()
check("6p2: …the reply does not say that nothing was written: the item it names carries the words, and the reply says so", "Nothing was sent" not in out and "History" in out and "pane" in out, out)
held.mark_client(A, "work-osprey-main")
fresh(); n0 = len(pushes()); long_ = "Release 4.2 is live. " + "details " * 60 + "END-MARKER"
out = msg("work-osprey-main", long_, "home-beta", fyi=True); settle(); got = held.take(A, "work-osprey-main")
check("6t: an fyi longer than a status line is held whole for a front agent: the reply says nothing about a cut and the held message ends with its last word", out.startswith("held for work-osprey-main's next turn") and "cut" not in out and "message log" not in out and got.rstrip().endswith("END-MARKER") and "Release 4.2" in got and "left out" not in got, (out, got))
check("…and the message log holds the full words", any("END-MARKER" in json.loads(l).get("text", "") for l in _messaging.MSG_LOG.read_text().splitlines()))
fresh(); out = msg("work-osprey-x", long_, "home-beta", fyi=True); settle()
check("6t2: the same for a background agent's fyi: whole, and the reply says nothing about a cut", out.startswith("held for work-osprey-x's next turn") and "cut" not in out and "message log" not in out and held.take(X, "work-osprey-x").rstrip().endswith("END-MARKER"), out)
_cfg.CFG["router"]["hold_notices"] = False
try:
    fresh(); n0 = len(pushes()); out = msg("work-osprey-main", "the PR is merged, nothing for you to do", "home-beta", fyi=True); settle()
    check("6u: with the hold switch off an fyi to a front agent is refused as without the flag, not 'not passed on' for a reason that is false", out.startswith("Refused") and "hook cannot fetch" not in out and reach(A, n0) == [] and held.count(A) == 0, out)
finally:
    _cfg.CFG["router"].pop("hold_notices", None)
fresh(); n0 = len(pushes()); out = _messaging._message("work-osprey-x", "the PR is merged, nothing to do", "home-beta", fyi=True); settle()
check("6q control: an fyi to a background agent is held as before (the reply, the line, no push)", out.startswith("held for work-osprey-x's next turn") and reach(X, n0) == [] and held.count(X) == 1 and held.count(A) == 0, out)
# an unknown name and a retired one: refused as before, nothing held
FJ = T / "fleet/a/sessions.json"; FJ0 = FJ.read_text(); rows_ = json.loads(FJ0)
MJ = T / "fleet/a/machine.json"; MJ0 = MJ.read_text()
rows_["55555555-5555-4555-8555-555555555555"] = {"name": "work-osprey-old", "machine": "a", "url": "", "seen": "x", "gone": datetime.datetime.fromtimestamp(time.time() - 7200, datetime.timezone.utc).isoformat().replace("+00:00", "Z")}
FJ.write_text(json.dumps(rows_)); MJ.write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": datetime.datetime.fromtimestamp(time.time() - 48, datetime.timezone.utc).isoformat().replace("+00:00", "Z")}}))      # its machine is online: a pane gone for two hours is gone
try:
    fresh(); n0 = len(pushes()); out = why(lambda: _messaging._message("work-osprey-old", "the PR is merged", "home-beta", fyi=True))
    check("6r: an fyi to a retired name is refused as before, nothing held or pushed", out.startswith("Refused: 'work-osprey-old' cannot receive this") and pushes()[n0:] == [] and held.count(A) == 0 and held.count(X) == 0, out)
    out = why(lambda: _messaging._message("work-osprey-ghost", "the PR is merged", "home-beta", fyi=True))
    check("6s: an fyi to an unknown name is refused as before", out.startswith("Refused: no session 'work-osprey-ghost'") and pushes()[n0:] == [] and held.count(A) == 0, out)
    out = why(lambda: _messaging._message("work-osprey-old", "the PR is merged", "home-beta", origin=MACH, fyi=True))
    check("6s2: a script's fyi to a retired name is refused as before, nothing held or pushed", out.startswith("Refused: 'work-osprey-old' cannot receive this") and pushes()[n0:] == [] and held.count(A) == 0 and held.count(X) == 0, out)
finally:
    FJ.write_text(FJ0); MJ.write_text(MJ0)
fresh(); n0 = len(pushes()); out = _messaging._message(KEY, "the release is live", "home-beta", fyi=True)
nn = [x for x in routing.read(KEY) if x.get("kind") == "message" and x.get("text", "").endswith("the release is live")]
check("6i: an fyi to a project is recorded with the mark for the router (and is held for the router as any message to a project)", out.startswith("held for the router") and nn and nn[-1].get("hold") == "fyi" and reach(X, n0) == [], (out, nn))
res = act(nn[-1], "work-osprey-x", rule="message-item")
check("6j: the router, passing it to a background agent, holds it (fyi)", res["ruling"] == "held" and held.count(X) == 1 and len(logged("fyi")) >= 1, res)
fresh(); n0 = len(pushes()); c0 = len([x for x in routing.read(KEY) if x.get("label") == "message"]); res = act(nn[-1], "work-osprey-main", rule="message-item")
rr = next(x for x in routing.read(KEY) if x["id"] == nn[-1]["id"])
check("6k: the router, passing an fyi to a FRONT agent, sends it through the front gate: held for its next turn, no turn, ruled held", res["ruling"] == "held" and reach(A, n0) == [] and held.count(A) == 1 and rr.get("ruling") == "held" and "fyi" in str(rr.get("reason")), (res, rr, pushes()[n0:]))
check("6k2: …the held line is the message's own words", "the release is live" in held.take(A, "work-osprey-main"))
check("6k2b: …and the router's own ruling is the one routing-log line for it: the gate writes no second one", len([x for x in routing.read(KEY) if x.get("label") == "message"]) == c0, [x for x in routing.read(KEY) if x.get("label") == "message"][c0:])
os.unlink(held.clients_file()); gate_open()
fresh(); n0 = len(pushes()); nid_f = routing.record(KEY, kind="message", to="", label="message to projects/alpha", who="home-beta", text="the release is live", target="project-wide", pilot=True, live=True, hold="fyi")
res = act(next(x for x in routing.read(KEY) if x["id"] == nid_f), "work-osprey-main", rule="message-item")
check("6k3: …a front agent whose hook does not fetch held lines is not given a turn: nothing is filed for it, so the notice is ruled archived (not held) with the reason, nothing pushed", res["ruling"] == "archived" and reach(A, n0) == [] and held.count(A) == 0 and "front agent" in str(res.get("reason")), (res, pushes()[n0:]))
rr_f = next(x for x in routing.read(KEY) if x["id"] == nid_f); ln_f = {**res, "id": nid_f, "project": KEY, "key": KEY, "ts": time.time()}
rows_f, _q, _pp = _live._digest_items(KEY, time.time(), {nid_f: _live._aliased(ln_f)}, {"sent": {}})
check("6k3b: …and the routing log, the live line, the digest and the get tool say the same word for it: archived, listed by the digest, no next_turn mark", rr_f["ruling"] == "archived" and _live._aliased(ln_f)["ruling"] == "archived" and [r[1]["id"] for r in rows_f] == [nid_f]
      and "ruling: archived" in _wt_get._notice_report(nid_f) and not any("next_turn" in d for d in json.loads("[" + ",".join(routing._file(KEY).read_text().splitlines()) + "]") if d.get("id") == nid_f), (rr_f, rows_f))
held.mark_client(A, "work-osprey-main")
present(True)
fresh(); n0 = len(pushes()); n = rec("[home-beta] the release is live — [for Oliver] pick a or b", hold="fyi"); res = act(n, "work-osprey-main", rule="message-item")
check("6k4 negative: an fyi pass to a front agent that carries Oliver's mark is delivered, marked, as before", res["ruling"] == "passed" and len(reach(A, n0)) == 1 and held.count(A) == 0, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = rec("the release is live", hold="fyi"); res = act(n, "work-osprey-main", for_owner=True)
check("6k5 negative: …and a ruling marked for Oliver, whatever the hold says", res["ruling"] == "passed" and len(reach(A, n0)) == 1 and held.count(A) == 0, (res, pushes()[n0:]))
present(False)
fresh(); n0 = len(pushes()); n = rec("the release is live", hold="closed"); res = act(n, "work-osprey-main", rule="message-item")
check("6k6 negative: a pass to a front agent of a notice with another hold kind than fyi or page-owed (closed) is not held for the front agent: with no need of Oliver it goes to the project's background agent, which holds a closed notice as it does any", res["ruling"] == "held" and res.get("held_for") == "work-osprey-x" and reach(A, n0) == [] and held.count(A) == 0, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = rec("the release is live"); res = act(n, "work-osprey-main", rule="message-item")
check("6k7 negative: a message to a project without fyi, passed to a front agent with no need of Oliver, goes to the background agent, unmarked, not held for the front agent", res["ruling"] == "passed" and reach(A, n0) == [] and len(reach(X, n0)) == 1 and held.count(A) == 0, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = rec("FYI: the release is live, nothing is asked of Oliver"); res = act(n, "work-osprey-main", rule="for-agent", reason="addressed to work-osprey-main on its first line")
check("6k8: a peer's message addressed to a front agent on its first line, that says FYI in its words but was sent without the fyi flag, is not held for the front agent (the sender's flag is what holds a pass, never the text): with no need of Oliver it goes to the background agent", res["ruling"] == "passed" and reach(A, n0) == [] and len(reach(X, n0)) == 1 and held.count(A) == 0, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = rec("FYI: the release is live, nothing is asked of Oliver", hold="fyi"); res = act(n, "work-osprey-main", rule="for-agent", reason="addressed to work-osprey-main on its first line")
check("6k9: …and the same message sent with the flag is held for the next turn, through the same rule", res["ruling"] == "held" and reach(A, n0) == [] and held.count(A) == 1, (res, pushes()[n0:]))
held.take(A, "work-osprey-main")

# ---- 6b. a page-owed notice passed to a front agent goes through the same front gate: held for its next turn, no turn
ANCHOR_TAIL = "no page update is owed by you (home-beta writes it); this notice is for the anchors scoped to a1"      # a1: how the fixture shows item 1
def rec_po(subject="", tail=ANCHOR_TAIL, extra="", stash=True, **kw):
    """A page-owed notice from its real producer, telling.pilot_relay (the anchors notice for a completed item, sent to the router's address): the gist in the routing log, the full words stashed for the router.
    `extra`: words added to the stashed text; `kw`: marks set on the notice (handback, words); `stash=False`: the stashed text is gone."""
    it = _service_store._load("a1")
    if subject: it = {**it, "subject": subject}
    seen = {x["id"] for x in routing.read(KEY)}
    telling.pilot_relay(KEY, "a1", it, "completed (done)", B, "work-osprey", "name", tail=tail); settle()
    n = next(x for x in routing.read(KEY) if x["id"] not in seen)
    if extra: _live.stash(n["id"], _live.stashed(n["id"]) + extra)
    if not stash: (_live.held_dir() / f"{n['id']}.json").unlink(missing_ok=True)
    return {**n, **kw}
def line_of(nid): return next(x for x in routing.read(KEY) if x["id"] == nid)
def last_row(session): return (held._read(held._file(held.key_of(session))) or [{}])[-1]
fresh(); n0 = len(pushes()); q0 = json.dumps(rd(1)["metadata"].get("front_quiet")); n = rec_po(); res = act(n, "work-osprey-main", rule="page-owed", reason="the page update is owed"); rr = line_of(n["id"])
check("6b1b: …and it writes no board line on the item (the owed list is the board's record of an owed page)", json.dumps(rd(1)["metadata"].get("front_quiet")) == q0, (q0, rd(1)["metadata"].get("front_quiet")))
check("6b1: a page-owed notice passed to a front agent (its hook fetches held lines) starts no turn: held for its next turn, ruled held", res["ruling"] == "held" and reach(A, n0) == [] and held.count(A) == 1
      and rr.get("ruling") == "held" and rr.get("reason") == "held: asks nothing (page-owed)" and res.get("hold") == "page-owed" and res.get("held_for") == "work-osprey-main", (res, rr, pushes()[n0:]))
row = last_row(A)
check("6b2: the held line is a page-owed line that names the page, the item, who changed it and what it says is owed, in one line within the cap",
      row.get("kind") == "page-owed" and KEY in row.get("text", "") and "a1" in row.get("text", "") and "home-beta" in row.get("text", "") and row.get("text", "").endswith(ANCHOR_TAIL) and "\n" not in row.get("text", "") and 0 < len(row.get("text", "")) <= held.LINE_MAX, row)
text_ = held.take(A, "work-osprey-main")
check("6b3: …and it is handed over with the agent's next turn, once", "page-owed" in text_ and ANCHOR_TAIL in text_ and held.take(A, "work-osprey-main") == "", text_)
fresh(); n = rec_po(subject="a very long subject " * 15); res = act(n, "work-osprey-main", rule="page-owed"); row = last_row(A)
check("6b4: a long subject is cut, never the part that says what is owed: the line is within the cap, ends with it and still names the page", res["ruling"] == "held" and 0 < len(row.get("text", "")) <= held.LINE_MAX
      and row.get("text", "").endswith(ANCHOR_TAIL) and KEY in row.get("text", "") and "a1" in row.get("text", ""), row)
fresh(); n = rec_po(stash=False); res = act(n, "work-osprey-main", rule="page-owed"); row = last_row(A)
check("6b5: a notice whose stashed words are gone still says what is true of it (the writer owes the page update; the notice is for the anchors scoped to the item), and never that the page update is owed by the agent",
      res["ruling"] == "held" and "the writer owes the page update" in row.get("text", "") and "anchors scoped to a1" in row.get("text", "") and KEY in row.get("text", "") and "owed by you" not in row.get("text", "") and "is owed" not in row.get("text", ""), (res, row))
fresh(); n = rec_po(subject="[hp] Short", stash=False); n["url"] = BOARD + "/items/" + "x" * 120; res = act(n, "work-osprey-main", rule="page-owed"); row = last_row(A)
check("6b5b: when the line does not fit even without a subject, the subject is kept and the link goes (the line stays within the cap and names the page and the item)", res["ruling"] == "held" and len(row.get("text", "")) <= held.LINE_MAX and "[hp] Short" in row.get("text", "") and "https://" not in row.get("text", "") and KEY in row.get("text", "") and "a1" in row.get("text", ""), (res, row))
fresh(); n = rec_po(); c0 = len(routing.read(KEY)); act(n, "work-osprey-main", rule="page-owed")
check("6b6: the router's own ruling is the one routing-log line for it: the gate writes no second one", len(routing.read(KEY)) == c0, routing.read(KEY)[c0:])
fresh(); n0 = len(pushes()); n = rec_po(); act(n, "work-osprey-main", rule="page-owed"); act(n, "work-osprey-main", rule="page-owed")
check("6b7: a pass retried after its ruling failed to write is held once, never twice", held.count(A) == 1 and reach(A, n0) == [], (held.count(A), pushes()[n0:]))
# what still starts a turn (while he is talking with the agent)
present(True)
fresh(); n0 = len(pushes()); n = rec_po(extra=" [for Oliver] pick a or b"); res = act(n, "work-osprey-main", rule="page-owed")
check("6b8 negative: a page-owed notice that carries Oliver's mark still starts a turn, marked, as before", res["ruling"] == "passed" and len(reach(A, n0)) == 1 and held.count(A) == 0, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = rec_po(extra=" needs: decision"); res = act(n, "work-osprey-main", rule="page-owed")
check("6b9 negative: …so does one that says needs: decision", res["ruling"] == "passed" and len(reach(A, n0)) == 1 and held.count(A) == 0, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = rec_po(); res = act(n, "work-osprey-main", rule="page-owed", for_owner=True)
check("6b10 negative: …and a ruling marked for Oliver", res["ruling"] == "passed" and len(reach(A, n0)) == 1 and held.count(A) == 0, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = rec_po(handback=True); res = act(n, "work-osprey-main", rule="page-owed")
check("6b11 negative: …and a hand-back to the same agent", res["ruling"] == "passed" and len(reach(A, n0)) == 1 and held.count(A) == 0, (res, pushes()[n0:]))
fresh(); n0 = len(pushes()); n = rec_po(words="a said entry"); res = act(n, "work-osprey-main", rule="page-owed")
check("6b12 negative: …and a notice with the person's words recorded on it", res["ruling"] == "passed" and len(reach(A, n0)) == 1 and held.count(A) == 0, (res, pushes()[n0:]))
present(False)
fresh(); n0 = len(pushes()); n = rec_po(); res = act(n, "work-osprey-x", rule="page-owed"); row = last_row(X)
check("6b13: a background agent's page-owed notice is held as before (no turn, ruled held) and its line says what is owed", res["ruling"] == "held" and reach(X, n0) == [] and held.count(X) == 1 and ANCHOR_TAIL in row.get("text", ""), (res, row))
fresh(); n0 = len(pushes()); n = rec_po(); res = act(n, "work-osprey-x", rule="page-owed", for_owner=True)
check("6b14 negative: …and its notice with the person's mark is delivered as before", res["ruling"] == "passed" and len(reach(X, n0)) == 1, res)
# the gate declining or failing, no gate wired, the switch off, a hook that cannot fetch: no exemption: the notice asks nothing of the front agent, so it still starts no turn there; it goes to the background agent
_hook0 = _live._HOOKS["front_fyi"]
def _boom(*a, **k): raise RuntimeError("gate down")
try:
    for hook_, name_ in ((lambda *a, **k: ("", ""), "declining"), (_boom, "failing"), (None, "not wired (the CLI alone)")):
        _live._HOOKS["front_fyi"] = hook_
        fresh(); n0 = len(pushes()); n = rec_po(); res = act(n, "work-osprey-main", rule="page-owed")
        check(f"6b15: the gate {name_} changes nothing for the front agent: no turn, nothing held for it; the notice goes to the background agent, held there as any page-owed one", reach(A, n0) == [] and held.count(A) == 0 and (held.count(X) == 1 or len(reach(X, n0)) == 1), (res, pushes()[n0:]))
finally:
    _live._HOOKS["front_fyi"] = _hook0
_cfg.CFG["router"]["hold_notices"] = False
fresh(); n0 = len(pushes()); n = rec_po(); res = act(n, "work-osprey-main", rule="page-owed")
_cfg.CFG["router"].pop("hold_notices")
check("6b16: with [router] hold_notices = false the front agent still gets no turn (nothing here holds, nothing starts one): the notice is delivered to the background agent", res["ruling"] == "passed" and reach(A, n0) == [] and len(reach(X, n0)) == 1 and held.count(A) == 0, (res, pushes()[n0:]))
os.unlink(held.clients_file()); gate_open()
fresh(); n0 = len(pushes()); n = rec_po(); res = act(n, "work-osprey-main", rule="page-owed")
check("6b17: a front agent whose hook does not fetch held lines gets no turn for it either: the notice goes to the background agent (the page's owed list is the record, so nothing is dropped)", reach(A, n0) == [] and held.count(A) == 0 and (held.count(X) == 1 or len(reach(X, n0)) == 1), (res, pushes()[n0:]))
held.mark_client(A, "work-osprey-main")
# the owed list is the page's own record: a held notice neither settles it nor hides it, and a write past the grace still says the page is owed
_owed0 = _web_page_debts._owed_load()
_page = T / "brain/projects/alpha.md"; _page_st = _page.stat(); os.utime(_page, (time.time() - 86400, time.time() - 86400))      # the page is a day old, so a debt charged now is not settled by it
try:
    _web_page_debts._owed_save({}); _web_page_debts._owed_mark(KEY, B, "a1")
    fresh(); n = rec_po(); res = act(n, "work-osprey-main", rule="page-owed"); d_ = _web_page_debts._owed_load()
    check("6b18: the owed list still shows the page after its notice was held for the front agent", res["ruling"] == "held" and KEY in d_ and any(e.get("item") == "a1" for e in d_[KEY].values()), (res, d_))
    check("6b19: …and the line of pages owed that a reply carries still names it", "pages owed" in _web_page_debts._nag(A) and KEY in _web_page_debts._nag(A), _web_page_debts._nag(A))
    _web_page_debts._owed_save({KEY: {o: {**e, "ts": time.time() - 7200} for o, e in d_[KEY].items()}})
    said_ = _real_note(B)
    check("6b20: …and the writer who owes it past the grace has the line that the write went through and the page is still owed, whatever the front agent was told", "This write went through. Still owed by you: " in said_ and KEY in said_, said_)
finally:
    _web_page_debts._owed_save(_owed0); os.utime(_page, ns=(_page_st.st_atime_ns, _page_st.st_mtime_ns))
os.unlink(held.clients_file()); gate_open()
fresh(); out = _messaging._message(KEY, "the release is live", "home-beta"); nn2 = [x for x in routing.read(KEY) if x.get("kind") == "message" and x.get("text", "").endswith("the release is live")][-1]
check("6l: a message to a project without fyi carries no mark", "hold" not in nn2, nn2)

# ---- 6c. follow-ups to the fyi to a front agent
item(20); item(21); item(22); item(23, status="done"); item(24)
held.mark_client(A, "work-osprey-main")
fresh(); n0 = len(pushes()); nlog = len(_messaging.MSG_LOG.read_text().splitlines()); out = msg("work-osprey-main", "the PR is merged, nothing for you to do", "home-beta", origin=MACH, fyi=True); settle()
check("6v: a script's unmarked fyi (origin set) to a front agent starts no turn: nothing is pushed, one line is held, the reply says so", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1, (out, pushes()[n0:], held.count(A)))
got = held.take(A, "work-osprey-main")
check("6v1: …it is handed over with the agent's next turn, once, and the line says a script sent it (not a session, no reply)", "the PR is merged" in got and "home-beta (a script on home-test)" in got and held.take(A, "work-osprey-main") == "", got)
check("6v2: …and the message log records it, as one new line: an fyi held, not delivered", [(json.loads(l).get("fyi"), json.loads(l)["to"], json.loads(l)["from"], "held" in json.loads(l)["outcome"]) for l in _messaging.MSG_LOG.read_text().splitlines()[nlog:]] == [(True, "work-osprey-main", "home-beta", True)])
fresh(); n0 = len(pushes()); r0 = len(routing.read(KEY))
st_, body_ = _rt_client._client_post(MACH, "message", {"to": "work-osprey-main", "text": "the PR is merged, nothing for you to do", "sender": "home-beta", "fyi": True}); settle()
check("6v3: the same fyi through POST /client/message is held for the next turn and starts none; the router is given nothing to rule, and the gate's own log line is the only new one (held once, not twice)", st_ == 200 and str(body_.get("result", "")).startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1 and [(x.get("ruling"), x.get("ruled_by")) for x in routing.read(KEY)[r0:]] == [("held", "stackshot (auto)")], (st_, body_, pushes()[n0:], routing.read(KEY)[r0:]))
st_, body_ = _rt_client._client_post(MACH, "held", {"uuid": A, "name": "work-osprey-main"})
check("6v4: …and the turn-start hook hands it over through POST /client/held, with the script's label", st_ == 200 and "the PR is merged" in body_.get("text", "") and "a script on home-test" in body_.get("text", "") and len(body_.get("ids", [])) == 1, (st_, body_))
held.ack(A, ids=body_.get("ids"))
fresh(); n0 = len(pushes()); b10 = len(fq_log(10)); out = msg("work-osprey-main", "a10 is merged, nothing for you to do", "home-beta", origin=MACH, fyi=True); settle()
check("6v5: a script's fyi that names an open item gives it the board line, like a session's", out.startswith("held for work-osprey-main's next turn") and reach(A, n0) == [] and held.count(A) == 1 and len(fq_log(10)) == b10 + 1 and "merged" in fq_log(10)[-1], (out, fq_log(10)))
present(True)
fresh(); n0 = len(pushes()); out = msg("work-osprey-main", "[for Oliver] a14 pick a or b", "home-beta", origin=MACH, fyi=True); settle(); present(False)
check("6v6 control: a script's MARKED message to a front agent is delivered as before (it asks something): a labeled script turn, nothing held", out.startswith("delivered") and len(reach(A, n0)) == 1 and "a script on home-test" in json.dumps(reach(A, n0)) and "cannot be replied to" in json.dumps(reach(A, n0)) and held.count(A) == 0, (out, pushes()[n0:]))
fresh(); n0 = len(pushes()); out = msg("work-osprey-main", "the PR is merged", "home-beta", origin=MACH); settle()
check("6v7 control: a script's message without fyi and without the mark is still refused, nothing held or pushed", out.startswith("Refused") and "front agent" in out and reach(A, n0) == [] and held.count(A) == 0, out)
fresh(); n0 = len(pushes()); out = msg("work-osprey-main", "it now needs: decision", "home-beta", origin=MACH, fyi=True); settle()
check("6v8 control: a script's fyi that says needs: decision is no fyi: refused without the mark, nothing held", out.startswith("Refused") and reach(A, n0) == [] and held.count(A) == 0, out)
fresh(); n0 = len(pushes()); out = msg("work-osprey-main", "the PR is merged, nothing for you to do", "Oliver", origin=MACH, fyi=True); settle()
check("6v9 control: a message in the person's own name from a script is no fyi: refused without the mark, nothing held", out.startswith("Refused") and reach(A, n0) == [] and held.count(A) == 0, out)
fresh(); n0 = len(pushes()); out = msg("work-osprey-x", "the PR is merged, nothing to do", "home-beta", origin=MACH, fyi=True); settle()
check("6v10 control: a script's fyi to a background agent is held as before", out.startswith("held for work-osprey-x's next turn") and reach(X, n0) == [] and held.count(X) == 1 and held.count(A) == 0, out)
fresh(); n0 = len(pushes()); out = msg("work-osprey-ghost", "the PR is merged", "home-beta", origin=MACH, fyi=True)
check("6v11 control: a script's fyi to an unknown name is refused as before, nothing held or pushed", out.startswith("Refused: no session") and pushes()[n0:] == [] and held.count(A) == 0 and held.count(X) == 0, out)
_cfg.CFG["router"]["hold_notices"] = False
try:
    fresh(); n0 = len(pushes()); out = msg("work-osprey-main", "the PR is merged, nothing for you to do", "home-beta", origin=MACH, fyi=True); settle()
    check("6v12 control: with the hold switch off a script's fyi to a front agent is refused as before, nothing held or pushed", out.startswith("Refused") and reach(A, n0) == [] and held.count(A) == 0, out)
finally:
    _cfg.CFG["router"].pop("hold_notices", None)
os.unlink(held.clients_file()); gate_open()
fresh(); n0 = len(pushes()); out = msg("work-osprey-main", "the PR is merged, nothing for you to do", "home-beta", origin=MACH, fyi=True); settle()
check("6v13: a front agent whose hook does not fetch held lines is not given a turn by a script either, and the script is refused, not told 'not passed on': nothing pushed or held", out.startswith("Refused") and "cannot fetch held lines" in out and "update, complete" not in out and reach(A, n0) == [] and held.count(A) == 0, (out, pushes()[n0:]))
st_, body_ = _rt_client._client_post(MACH, "message", {"to": "work-osprey-main", "text": "the PR is merged, nothing for you to do", "sender": "home-beta", "fyi": True}); settle()
check("6v14: …through POST /client/message the status is 400 (a script reads the status: the client, refusal_report and audit_run count a 200 as sent)", st_ == 400 and "cannot fetch held lines" in str(body_.get("error", "")) and held.count(A) == 0 and reach(A, n0) == [], (st_, body_))
fresh(); n0 = len(pushes()); out = msg("work-osprey-main", "the PR is merged, nothing for you to do", "home-beta", fyi=True); settle()
check("6v15 control: a session's fyi in the same state still gets the reply 'not passed on' (the session path is unchanged)", out.startswith("not passed on") and reach(A, n0) == [] and held.count(A) == 0, out)
held.mark_client(A, "work-osprey-main")
fresh(); n0 = len(pushes()); long_s = "work-osprey-x " + "p" * 280
st_, body_ = _rt_client._client_post(MACH, "message", {"to": "work-osprey-main", "text": "the PR is merged, nothing for you to do", "sender": long_s, "fyi": True}); settle()
got = held.take(A, "work-osprey-main")
check("6v16: a 280-character sender does not push the script label out of the held message", st_ == 200 and "(a script on home-test)" in got and "the PR is merged" in got and "p" * 100 not in got, (st_, body_, got))
fresh(); long_sess = "work-osprey-x " + "s" * 47
check("6v16 length", len(long_sess) == 61)
msg("work-osprey-main", "the PR is merged, nothing for you to do", long_sess, fyi=True); settle(); got = held.take(A, "work-osprey-main")
check("6v18: a SESSION sender of 61 characters is held for a front agent whole, with no script label and no cut (the line is as on main)", f"from {long_sess}: the PR is merged" in got and "script" not in got and "…" not in got, got)
msg("work-osprey-x", "the PR is merged, nothing to do", long_sess, fyi=True); settle(); got = held.take(X, "work-osprey-x")
check("6v19: …and for a background agent", f"from {long_sess}: the PR is merged" in got and "script" not in got and "…" not in got, got)
fresh(); n0 = len(pushes()); out = msg("work-osprey-main", "Release 4.2 is live. " + "details " * 60 + "END-MARKER", "home-beta", origin=MACH, fyi=True); settle()
got = held.take(A, "work-osprey-main")
check("6v17: a script's long fyi is held whole: the reply says nothing about a cut and the turn carries every word, the end marker included", out.startswith("held for work-osprey-main's next turn") and "cut" not in out and "left out" not in got and "END-MARKER" in got and "details " * 60 in got, (out, got))
held.mark_client(A, "work-osprey-main")
fresh(); n0 = len(pushes()); b20, b21 = len(fq_log(20)), len(fq_log(21))
n = rec("a20 and a21 are merged, nothing for you", hold="fyi"); res = act(n, "work-osprey-main", rule="message-item"); settle()
check("6w: a routed fyi that names items in its text, with none on the ruling, gives each open item its board line (as the tool path does) and is held for the next turn",
      res["ruling"] == "held" and held.count(A) == 1 and len(fq_log(20)) == b20 + 1 and len(fq_log(21)) == b21 + 1 and reach(A, n0) == [], (res, fq_log(20), fq_log(21)))
fresh(); n0 = len(pushes()); b20, b22 = len(fq_log(20)), len(fq_log(22))
n = rec("a20 is merged, nothing for you", hold="fyi"); res = act(n, "work-osprey-main", rule="message-item", item="a22"); settle()
check("6w2: …and when the ruling names one item, the items the text names get theirs too", len(fq_log(22)) == b22 + 1 and len(fq_log(20)) == b20 + 1 and held.count(A) == 1, (fq_log(20), fq_log(22)))
os.unlink(held.clients_file()); gate_open()
fresh(); n0 = len(pushes()); b24 = len(fq_log(24))
n = rec("a24 is merged, nothing for you", hold="fyi"); res = act(n, "work-osprey-main", rule="message-item"); settle()
check("6w3: …a front agent whose hook cannot fetch held lines is not given a turn (nothing filed: ruled archived), and the board line is the fallback for the item the text names", res["ruling"] == "archived" and held.count(A) == 0 and reach(A, n0) == [] and len(fq_log(24)) == b24 + 1, (res, fq_log(24)))
held.mark_client(A, "work-osprey-main")
fresh(); b23 = len(fq_log(23)); out = msg("work-osprey-main", "a23 is merged, nothing for you", "home-beta", fyi=True); settle()
check("6x: the reply promises a History line only for an open item it names: a closed item gets none, and the reply does not claim one", len(fq_log(23)) == b23 and "an open item it names gets a History line" in out and "an item it names gets" not in out, (out, fq_log(23)))
os.unlink(held.clients_file()); gate_open()
fresh(); out = msg("work-osprey-main", "a23 is merged, nothing for you", "home-beta", fyi=True); settle()
check("6x2: …the same in the reply of an fyi that was not passed on", out.startswith("not passed on") and "an open item it names has it on its History" in out and "an item it names has it" not in out, out)
held.mark_client(A, "work-osprey-main")
fresh(); n0 = len(pushes()); long_p = "Release 4.2 is live. " + "details " * 60 + "END-MARKER"
out = _messaging._message(KEY, long_p, "home-beta", fyi=True); out_short = _messaging._message(KEY, "the release is live", "home-beta", fyi=True)
check("6y: an fyi to a project longer than a status line is recorded for the router with no word of a cut (the router holds it whole)", out.startswith("held for the router") and "cut" not in out and str(held.LINE_MAX) not in out, out)
check("6y2: …and a short one says the same", out_short.startswith("held for the router") and "cut" not in out_short, out_short)
out = _messaging._message(KEY, long_p, "home-beta")
check("6y3: …a message to a project without fyi is never held, so it says nothing about a cut", out.startswith("held for the router") and "cut" not in out, out)
# the message tool and the router carry a message whole: a 2000-character message of several lines, to a background agent, to a front agent, and through the router's pass of a routed fyi
long_m = "Result of the run:\n" + "\n".join(f"- step {i:03d} " + "r" * 70 for i in range(24)) + "\nEND-OF-REPORT"
check("6y4 fixture: the message is over 1900 characters and 26 lines", len(long_m) > 1900 and long_m.count("\n") == 25, (len(long_m), long_m.count("\n")))
def whole_in(got):
    """Every line of long_m is in the turn, each after the first indented two spaces, and nothing says a cut."""
    return all(f"  - step {i:03d} " + "r" * 70 in got.split("\n") for i in range(24)) and "  END-OF-REPORT" in got.split("\n") and "left out" not in got and "…" not in got
held.mark_client(A, "work-osprey-main")
fresh(); out = msg("work-osprey-x", long_m, "home-beta", fyi=True); settle(); got = held.take(X, "work-osprey-x")
check("6y5: an fyi to a background agent arrives whole: every line, the line breaks kept, nothing cut, and the reply says nothing about a cut", out.startswith("held for work-osprey-x's next turn") and "cut" not in out and whole_in(got), (out, got[-300:]))
fresh(); out = msg("work-osprey-main", long_m, "home-beta", fyi=True); settle(); got = held.take(A, "work-osprey-main")
check("6y6: …an fyi to a front agent too (the front gate): every line, the line breaks kept", out.startswith("held for work-osprey-main's next turn") and "cut" not in out and whole_in(got), (out, got[-300:]))
fresh(); n0 = len(pushes()); n = rec(long_m, hold="fyi"); res = act(n, "work-osprey-x", rule="message-item"); settle(); got = held.take(X, "work-osprey-x")
check("6y7: the router's pass of a routed fyi to a background agent holds it whole", res["ruling"] == "held" and whole_in(got), (res, got[-300:]))
fresh(); n0 = len(pushes()); n = rec(long_m, hold="fyi"); res = act(n, "work-osprey-main", rule="message-item"); settle(); got = held.take(A, "work-osprey-main")
check("6y8: …and to a front agent (the front gate)", res["ruling"] == "held" and whole_in(got), (res, got[-300:]))
huge = "\n".join(f"- row {i:04d} " + "z" * 80 for i in range(120))      # about 11 000 characters: only a pass of the router can carry more than the tool's limit
fresh(); n0 = len(pushes()); n = rec(huge, hold="fyi"); res = act(n, "work-osprey-main", rule="message-item"); settle(); row_ = last_row(A); head_, _, note_ = row_.get("text", "").rpartition("\n")
check("6y9: a pass above the limit is cut at a line boundary and the note counts the characters left out and names the notice and its sender (never cut inside it)",
      res["ruling"] == "held" and len(row_.get("text", "")) <= held.WHOLE_MAX and note_.startswith("… (") and note_.endswith(f"the rest is in notice {n['id']}, from home-beta)") and _live._body(n).startswith(head_)
      and f"… ({len(_live._body(n)) - len(head_)} characters left out;" in note_, (res, note_, len(head_)))
fresh(); out = msg("work-osprey-x", "short fyi", "home-beta", fyi=True); settle()
check("6y10: a short one-line fyi arrives as before, on one line", held.take(X, "work-osprey-x").splitlines()[1].endswith("[stackshot message] from home-beta: short fyi"))
# the call sites that must NOT hold whole (a status notice the server writes stays one line cut at LINE_MAX) and the one that must (a digest's filed line)
present(False)
def one_row(row):
    """A held status notice: one line, no line break, cut at LINE_MAX with its cut mark (the long text and the line breaks of the fixture are folded)."""
    t = row.get("text", "")
    return "\n" not in t and 0 < len(t) <= held.LINE_MAX and t.endswith("…") and "END-OF-REPORT" not in t
_real_verdict = telling.front_verdict; telling.front_verdict = lambda gid, owner, kind: ("fyi", "")      # staged: he is with the agent and it touched the item, so a progress notice rides its next turn
try:
    fresh(); n0 = len(pushes()); telling.tell_woken("a12", A, "[stackshot] a12 progress: " + long_m, tag="owner"); settle(); row_a = last_row(A)
finally:
    telling.front_verdict = _real_verdict
check("6z1: a status notice to a front agent (the front gate's default) is held as one line cut at LINE_MAX, however long and however many lines it has", reach(A, n0) == [] and held.count(A) == 1 and one_row(row_a), (pushes()[n0:], row_a))
fresh(); n0 = len(pushes()); it = _service_store._load("a12"); it_l = {**it, "subject": "Long subject " + "s" * 400 + "\nsecond line"}
wakes_svc.wake_tell(A, [("a12", it_l, "woke (wake 10-29)", "as its keeper of record", False)]); settle(); row_q = last_row(A)
check("6z2: a queue-place wake notice to a front agent stays a status line: one line cut at LINE_MAX, the item's long subject and its line break folded", reach(A, n0) == [] and held.count(A) == 1 and row_q.get("kind") == "queue" and one_row(row_q), (pushes()[n0:], row_q))
fresh(); n0 = len(pushes()); n = rec(long_m, hold="page-owed"); res = act(n, "work-osprey-docs"); row_p = last_row(D)
check("6z3: a page-owed notice passed to a background agent is held as one line cut at LINE_MAX (only an fyi is held whole)", res["ruling"] == "held" and held.count(D) == 1 and row_p.get("kind") == "page-owed" and one_row(row_p), (res, row_p))
fresh(); n0 = len(pushes()); n = rec(long_m, hold="closed"); res = act(n, "work-osprey-main", rule="message-item"); row_c = last_row(X)
check("6z4: the same notice with another hold kind (closed), passed to a front agent that hands it to the project's background agent, is held there as one line cut at LINE_MAX", res["ruling"] == "held" and res.get("held_for") == "work-osprey-x" and held.count(X) == 1 and row_c.get("kind") == "closed" and one_row(row_c), (res, row_c))
fresh(); n0 = len(pushes()); n = rec("a8 is done:\n" + long_m, hold="closed"); res = act(n, "", rule="message-item"); row_g = last_row(X)
check("6z4b: …and when the front agent takes it as the fallback (no target of its own) and hands it on to the background agent whose item it names, it is held there as one line too", res["ruling"] == "held" and res.get("held_for") == "work-osprey-x" and held.count(X) == 1 and row_g.get("kind") == "closed" and one_row(row_g), (res, row_g))
fresh(); n0 = len(pushes()); filed_ = _messaging.digest_fyi("work-osprey-main", [long_m]); settle(); row_d = last_row(A)
check("6z5: a line of a digest filed for a front agent (a human message queued while the pane was away) arrives whole: every line and its line breaks, nothing cut", filed_ == [0] and row_d.get("text") == long_m and whole_in(held.take(A, "work-osprey-main")), (filed_, row_d.get("text", "")[-120:]))
present(True)
# a pass retried after its ruling failed to write holds the line once: the gate's own add carries the notice id
fresh()
telling.front_fyi("work-osprey-main", "the release is live", "", "retry-nid", False); telling.front_fyi("work-osprey-main", "the release is live", "", "retry-nid", False)
check("6z: the front gate holds a notice once however often its pass is retried (the line is keyed by the notice id)", held.count(A) == 1, held.count(A))
telling.front_fyi("work-osprey-main", "the release is live", "", "", False)
check("6z2 control: a line with no notice id is a new line each time", held.count(A) == 2, held.count(A))
fresh(); n0 = len(pushes()); n = rec("the release is live", hold="fyi"); res = act(n, "work-osprey-main", rule="message-item"); res2 = act(n, "work-osprey-main", rule="message-item")
check("6z3: …and a router pass of an fyi to a front agent run twice for one notice holds it once", held.count(A) == 1 and reach(A, n0) == [], (res, res2, held.count(A)))

# ---- 7. the hand-over at a turn start
fresh()
held.add(held.key_of(X), "closed", "board#1 closed by home-beta", sender="home-beta", now=time.time() - 120)
held.add(held.key_of(X), "page-owed", "board#3 page update owed", sender="home-beta", now=time.time() - 60)
n0 = len(pushes()); telling.tell_woken("a1", X, "[stackshot] a1 is yours now", tag="handoff"); settle()
check("7a: a waking notice is pushed as now and takes none of the held lines with it (they wait for the turn start)", len(reach(X, n0)) == 1 and "held for you" not in json.dumps(pushes()[n0:]) and held.count(X) == 2)
st, body_ = _rt_client._client_post(MACH, "held", {"uuid": X, "name": "work-osprey-x"})
txt = body_.get("text", ""); ids7 = body_.get("ids", [])
check("7b: the client endpoint hands them over at the turn start, oldest first, one line each, with the kind, and the ids to acknowledge",
      st == 200 and txt.count("\n- ") == 2 and txt.index("board#1 closed") < txt.index("board#3 page") and " · closed · " in txt and " · page-owed · " in txt and len(ids7) == 2, (st, body_))
st, body_ = _rt_client._client_post(MACH, "held", {"uuid": X, "name": "work-osprey-x"})
check("7c: a second ask inside the lease is not handed the same lines again, and they are not lost yet (still stored until acknowledged)", st == 200 and body_ == {"text": "", "ids": []} and held.count(X) == 2, (body_, held.count(X)))
st, body_ = _rt_client._client_post(MACH, "held", {"uuid": X, "ack": ids7})
check("7c2: the acknowledgement removes exactly those lines", st == 200 and body_ == {"removed": 2} and held.count(X) == 0, (body_, held.count(X)))
st, body_ = _rt_client._client_post(MACH, "held", {"uuid": A, "name": "work-osprey-main"})
check("7d: a front agent's session gets nothing (nothing is ever held for it)", st == 200 and body_ == {"text": "", "ids": []}, body_)
st, body_ = _rt_client._client_post(MACH, "held", {"uuid": "nope", "name": ""})
check("7e: a body without a transcript id is refused", st == 400, (st, body_))
held.add(held.key_of(X), "fyi", "kept across a restart", sender="home-beta", now=time.time())
held = importlib.reload(held)
st, body_ = _rt_client._client_post(MACH, "held", {"uuid": X, "name": "work-osprey-x"})
check("7f: a held line survives a restart of the server (the module reloaded; the files are the state)", "kept across a restart" in body_.get("text", ""), body_)
held.ack(X, ids=body_.get("ids"))
held.add(held.key_of(X), "closed", "via the client", sender="home-beta", now=time.time())
_real_post = client.post
client.post = lambda what, body, timeout=20.0: _rt_client._client_post(MACH, what, body)
try:
    got, gids = client.held_for(X, "work-osprey-x"); again = client.held_for(X, "work-osprey-x"); none = client.held_for("", "")
    acked = client.held_ack(X, gids)
finally:
    client.post = _real_post
check("7g: client.held_for (what the UserPromptSubmit hook prints) reads the endpoint once and answers empty with no session id; held_ack removes what it printed",
      "via the client" in got and len(gids) == 1 and again == ("", []) and none == ("", []) and acked and held.count(X) == 0, (got, gids, again, none, acked))
client.post = lambda what, body, timeout=20.0: (0, "unreachable")
try: down = client.held_for(X, "work-osprey-x"); down_ack = client.held_ack(X, ["abc"])
finally: client.post = _real_post
check("7h: …and empty when the server cannot be reached (a hook never fails a session)", down == ("", []) and down_ack is False)
with open(os.path.join(STACK, "stackshot/projects/pages.py"), encoding="utf-8") as f: nag = f.read().split("def cmd_nag", 1)[1].split("def cmd_check", 1)[0]
check("7i: the UserPromptSubmit hook every client install wires (pages.py nag) asks for the held lines, prints them, then acknowledges the ids", "held_for(sid, name)" in nag and "print(held" in nag and "held_ack(sid, ids)" in nag
      and nag.index("print(held") < nag.index("held_ack("))
check("7i2: …and does not ask when the server was already found unreachable in this run (UNREACHABLE)", "if not UNREACHABLE" in nag)

# at least once: a line the hook never acknowledged is offered again after its lease
fresh(); t1 = time.time() - 1000
held.add(held.key_of(X), "closed", "offered twice", now=t1)
tx1, id1 = held.lease(X, now=t1 + 1)
tx2, id2 = held.lease(X, now=t1 + 2)
tx3, id3 = held.lease(X, now=t1 + 1 + held.LEASE + 1)
check("7j: a leased line is not offered again inside the lease, is offered again once the lease runs out unacknowledged (at least once), and is stored until then",
      "offered twice" in tx1 and tx2 == "" and id2 == [] and "offered twice" in tx3 and id3 == id1 and held.count(X) == 1, (tx1, tx2, tx3, id1, id3))
check("7k: an acknowledgement removes it for good; an unknown id, or one of another session, removes nothing", held.ack(A, ids=id3) == 0 and held.count(X) == 1 and held.ack(X, ids=["nope"]) == 0 and held.ack(X, ids=id3) == 1 and held.count(X) == 0)
fresh()
for i in range(10): held.add(held.key_of(X), "closed", f"m{i}", now=t1 + i)
tx, idsA = held.lease(X, now=t1 + 20)
tx_b, idsB = held.lease(X, now=t1 + 21)
check("7l: the lines past the cap are not leased: the next ask gets them, and a leased line is not counted among the '+N more'", len(idsA) == 8 and "+2 more" in tx and len(idsB) == 2 and "m8" in tx_b and "more" not in tx_b.splitlines()[-1], (tx, tx_b))
held.ack(X, ids=idsA + idsB)
check("7m: take() is lease and acknowledge in one step (each line once)", (held.add(held.key_of(X), "fyi", "once", now=t1) and "once" in held.take(X, now=t1 + 1)) and held.take(X, now=t1 + 2) == "" and held.count(X) == 0)

# the endpoint checks the session as drain does: the machine must hold it, and the name is the server's record
fresh(); held.add(held.key_of(X), "closed", "for the builder", now=time.time()); held.add(held.key_of(D), "closed", "for the page keeper", now=time.time())
st, body_ = _rt_client._client_post(MACH, "held", {"uuid": X, "name": "work-osprey-docs"})
check("7n security: the name in the request is ignored: the session's lines are found by the server's record of it (a forged name draws the page keeper's lines to nobody)",
      st == 200 and "for the builder" in body_["text"] and "for the page keeper" not in body_["text"], body_)
held.ack(X, ids=body_["ids"])
st, body_ = _rt_client._client_post("home-other", "held", {"uuid": D, "name": "work-osprey-docs"})
check("7o security: another machine's token gets nothing for a session the server holds for home-test", st == 200 and body_ == {"text": "", "ids": []} and held.count(D) == 1, (st, body_))
st, body_ = _rt_client._client_post("home-other", "held", {"uuid": D, "ack": []})
st2, body2_ = _rt_client._client_post("home-other", "held", {"uuid": D, "ack": [r["id"] for r in held._read(held._file(held.key_of(D)))]})
check("7p security: …nor can it acknowledge (remove) them", held.count(D) == 1 and body2_ == {"text": "", "ids": []}, (body_, body2_, held.count(D)))
st, body_ = _rt_client._client_post(MACH, "held", {"uuid": "99999999-9999-4999-8999-999999999999", "name": "work-osprey-x"})
check("7q security: a transcript id the server does not hold for the machine gets nothing, and is not registered by the call", body_ == {"text": "", "ids": []} and "99999999-9999-4999-8999-999999999999" not in _clients.sessions_on(MACH), body_)
st, body_ = _rt_client._client_post(MACH, "held", {"uuid": D, "ack": "all"})
check("7r: a malformed ack is refused", st == 400, (st, body_))

# the owner's mark comes from the instance, and a drop leaves a trace
saved_owner = _cfg.CFG.get("instance", {}).get("owner")
_cfg.CFG.setdefault("instance", {})["owner"] = "Alice"
check("7s: the owner's mark is the instance's ([for Alice]), not a fixed name", held.decide("closed", is_background=True, text="[for Alice] look") == "" and held.decide("closed", is_background=True, text="[for Oliver] look") == "closed")
_cfg.CFG["instance"]["owner"] = saved_owner
fresh()
import io, contextlib
err = io.StringIO()
with contextlib.redirect_stderr(err):
    for i in range(held.KEEP_MAX + 3): held.add(held.key_of(X), "closed", f"c{i}", now=time.time())
    held.add(held.key_of(D), "closed", "old", now=time.time() - 8 * 86400)
    held.lease(D, now=time.time())
check("7t: lines dropped by the cap or by age leave a stderr line", "1 notice for" in err.getvalue() and "more than" in err.getvalue() and "dropped unread: older than 7 days" in err.getvalue(), err.getvalue())
fresh()
old = held._file("retired-session"); old.write_text(json.dumps({"id": "z", "ts": time.time() - 30 * 86400, "kind": "closed", "text": "never read"}) + "\n", encoding="utf-8")
os.utime(old, (time.time() - 30 * 86400, time.time() - 30 * 86400))
with contextlib.redirect_stderr(io.StringIO()): held.add(held.key_of(X), "closed", "a new one", now=time.time())
check("7u: a retired session's file (untouched for KEEP_DAYS) is removed when anything is added", not old.exists() and held.count(X) == 1)

# the digest leaves out what is held for an agent
fresh()
nA = rec("[board] board#1 plain held by the router"); routing.rule(nA["id"], "archived", reason="a router archive", by=_live.BY)
nB = rec("[board] board#1 completed (done) — page update", hold="page-owed"); resB = act(nB, "work-osprey-docs")
lnA = {"id": nA["id"], "project": KEY, "key": KEY, "status": "ruled", "ruling": "archived", "ts": time.time()}
lnB = {**resB, "id": nB["id"], "project": KEY, "key": KEY, "ts": time.time()}
rows_, _q, _pp = _live._digest_items(KEY, time.time(), {nA["id"]: lnA, nB["id"]: lnB}, {"sent": {}})
check("7v: the digest lists a notice the router archived for itself and leaves out one held for an agent's next turn (held_for), which would reach the agent twice",
      [r[1]["id"] for r in rows_] == [nA["id"]] and lnB.get("held_for") == "work-osprey-docs", ([r[1]["id"] for r in rows_], lnB))
held.mark_client(A, "work-osprey-main"); fresh()
nF = rec_po(); resF = act(nF, "work-osprey-main", rule="page-owed"); lnF = {**resF, "id": nF["id"], "project": KEY, "key": KEY, "ts": time.time()}
rowsF, _q, _pp = _live._digest_items(KEY, time.time(), {nF["id"]: lnF}, {"sent": {}})
check("7v2: a page-owed notice held for a front agent's next turn is left out of the digest too (held_for), so it is not sent to the agent a second time", resF.get("ruling") == "held" and lnF.get("held_for") == "work-osprey-main" and rowsF == [], (resF, rowsF))
fresh(); nid3 = routing.record(KEY, kind="message", to="", label="message to projects/alpha", who="falcon-audit", text=body, target="project-wide", pilot=True, live=True); _live.stash(nid3, body)
n3 = next(x for x in routing.read(KEY) if x["id"] == nid3)
res3 = _live._act(n3, KEY, KEY, {**ln, "id": nid3, "target": "work-osprey-x", "split": {"work-osprey-x": ["a1"]}}, cx, {})
rows3, _q, _pp = _live._digest_items(KEY, time.time(), {nid3: {**res3, "project": KEY, "key": KEY, "ts": time.time()}}, {"sent": {}})
check("7w: an audit finding is a task: delivered at once, nothing held for the agent (no held_for), and the digest does not list a passed notice", res3.get("held_for") is None and not res3.get("held_for") and res3.get("ruling") == "passed" and held.count(X) == 0 and rows3 == [], (res3, rows3))

fresh()
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
