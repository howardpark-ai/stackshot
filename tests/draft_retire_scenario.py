"""Scenario test for when an item's draft stops being offered (draft.py, THE STEP IT SERVES) — fixture data, the tools called in-process, no live store, no network, no server socket.

A draft is offered for copying only while a step of the owner's that it could serve is open. Retiring it keeps the text: the item page, the home row, the answer frame and the sent-mail watch take none,
get says it is retired, and the update that retired it says so in its reply.

  1  a step of his dropped or ticked retires it; every view and read; the record; that step open again, or draft=, shows a draft
  2  several steps of his open: it stays until the last closes, and any of them open again shows it
  3  the same write: a reword, a replace, a new draft (the same text too) keep it; a tick with a new step retires it; a reopened step wins over what else that write ticks
  4  a draft stored before any step of his; a your-step withdrawn and replaced; a close and a clear
  5  a decision (Send / Change it / Don't send): shown while asked, kept for sending in get after his answer, a re-ask, a withdrawn ask
  6  his Done and his note on a step
  7  items stored before the record: read as they stand, no write, no notice; the first write stores what was read
  8  the write guard, the ask's reference and the sent-mail watch
  9  after his answer get keeps printing the text until a new draft, a clear or the close: a later comment, a stale pick, another line of his, a Done, a shared step, a late pick, older items
  10 the guards read the draft as the save will leave it: a tick with a paste step in one write; a decision that offers Send over a retired draft

    tests/run-suite draft_retire        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="draftretire-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml = _instance.set_person(toml)
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state","brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
now = time.time(); H = 3600.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-agent", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-agent", "status": "active", "board": [], "board_open": 0}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- Goal: A thing, finished when it works"
AG = "home-agent: build it"
A, B, C = "Oliver: run the first check", "Oliver: confirm the second check", "Oliver: look at the third check"
TEXT = "the first line to copy\n\n  - and a second one"
ASK = "Decide: whether to send the note now · Recommend: send · Stakes: a day either way · By: no date"
ASK2 = "Decide: whether to send the shorter note · Recommend: send · Stakes: a week either way · By: no date"
OPTS = [{"label": "Send", "line": "Send the note as written", "recommended": True}, {"label": "Change it", "line": "Change the wording first", "recommended": False},
        {"label": "Don't send", "line": "Drop the note", "recommended": False}]


def item(i, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": DESC, "status": status, "updated": now - 3 * H, "state_updated": now - 3 * H,
                                                     "confirmed": now - 3 * H, "metadata": {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "next": AG, **meta}}))


git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
mt = lambda i: rd(i)["metadata"]
raw = lambda i: (T / f"store/a/{i}.json").read_text()

from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import draft as D; from stackshot.model import steps as S
from stackshot.web import home; from stackshot.web.ui import render as ui_render; from stackshot.web.ui import answer_frame
from stackshot.service import answer as answer_svc, gates, sent_match, telling, writes
from stackshot.service import asks as asks_svc
from stackshot.service import update as _update_svc
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import get as _wt_get
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
told = []
telling.tell_woken = lambda *a, **k: told.append(a)
upd = lambda i, sender="home-agent", **kw: _update_svc._update(f"a{i}", sender=sender, **kw)
get = lambda i: _wt_get.stackshot_get(f"a{i}")
brief = lambda i: _wt_get._fmt(rd(i) | {"gid": f"a{i}"}, brief=True)
nx = lambda *lines: "\n".join(lines)
RETIRED_REPLY = "this write retired the draft"
STILL_REPLY = "draft stays retired"
BOX = lambda i: {"action": f"/items/a{i}/answer", "token": "TOKEN", "sent": ""}
page = lambda i: ui_render.Board(f"{tmp}/store").item_html(f"a{i}", answer=BOX(i))


def row(i):
    """the item's home row, wherever it is listed ("" when no list has it)"""
    b = ui_render.Board(f"{tmp}/store")
    for where, pairs in b.home_pairs().items():
        for r, m in pairs:
            if r["gid"] == f"a{i}":
                return b.home_row(r, m, where)
    return ""


def offered(name, i, text=TEXT):
    p, g = page(i), get(i)
    check(f"{name}: offered — the page has the Copy block, get the text, the brief says it is there",
          'class="draft"' in p and "\ndraft:\n" + text + "\n" in "\n" + g + "\n" and "(get shows it)" in brief(i) and not D.retired(rd(i)), (g, mt(i), 'class="draft"' in p))


def gone(name, i, text=TEXT):
    p, g, h, bf = page(i), get(i), row(i), brief(i)
    first = text.split("\n")[0]
    check(f"{name}: no view offers it — no block on the page or the home row, no text in get or the brief", 'class="draft' not in p and 'class="draft' not in h and "\ndraft:\n" not in g and first not in g and first not in bf, (g, h[-300:]))
    check(f"{name}: …and the text is kept on the item, said retired by get", mt(i).get("draft") == text and "draft: retired, its step is closed" in g and "draft: retired" in bf and D.of(rd(i)) == "", (g, mt(i)))


# ================================================================ 1. dropped, ticked, reopened
item(1, next=nx(AG, A), draft=TEXT)
offered("1 an open step of his", 1)
ref0 = ui_render.question_ref(rd(1) | {"gid": "a1"})
was_hist = page(1).count("draft cleared")
out = upd(1, next=AG, dropped=[A])
check("1 drop: the reply says the write retired the draft", RETIRED_REPLY in out and "stays stored" in out, out)
gone("1 drop", 1)
check("1 drop: the record holds the step that closed", mt(1).get("draft_retired") is True and mt(1).get("draft_closed") == [S.owner_key(A)], mt(1))
check("1 drop: no line of History says the text was cleared, and the ask's reference reads the stored text as before", page(1).count("draft cleared") == was_hist and ui_render.question_ref(rd(1) | {"gid": "a1"}) == ref0, None)
out = upd(1, priority="p1")
check("1 drop: a later write keeps it retired and says nothing more", RETIRED_REPLY not in out and STILL_REPLY not in out and "draft: retired" in out, out)
gone("1 later write", 1)
out = upd(1, next=nx(AG, B))
check("1 drop: another step of his does not bring it back, and the reply says to pass draft=", STILL_REPLY in out and "draft=" in out, out)
gone("1 another step", 1)
out = upd(1, next=nx(AG, B, A))
offered("1 the dropped step open again", 1)
check("1 reopen: the retired mark goes, no note", "draft_retired" not in mt(1) and RETIRED_REPLY not in out and STILL_REPLY not in out, (mt(1), out))
item(2, next=nx(AG, A), draft=TEXT)
upd(2, priority="p2")
out = upd(2, next=AG, done=[A])
check("1 tick: a done step retires it too", RETIRED_REPLY in out, out)
gone("1 tick", 2)
out = upd(2, draft=TEXT)
offered("1 tick: draft= with the same text shows it again", 2)
check("1 draft=: the record starts over", mt(2).get("draft_closed") == [] and "draft_retired" not in mt(2), mt(2))
upd(2, priority="p3")
offered("1 …and the next write does not retire it again (nothing of his closed in it)", 2)

# ================================================================ 2. several steps of his
item(3, next=nx(AG, A, B), draft=TEXT)
out = upd(3, next=nx(AG, B), dropped=[A])
offered("2 one of two dropped", 3)
check("2 …no note", RETIRED_REPLY not in out, out)
out = upd(3, next=AG, done=[B])
check("2 the last one closed retires it", RETIRED_REPLY in out, out)
gone("2 both closed", 3)
upd(3, next=nx(AG, A))
offered("2 the one that closed first, open again, shows it (it may be the one the draft served)", 3)
out = upd(3, next=AG, dropped=[A])
check("2 …and closing it again retires it again", RETIRED_REPLY in out, out)
upd(3, next=nx(AG, B))
offered("2 the other one open again shows it too", 3)

# ================================================================ 3. the same write
item(4, next=nx(AG, A), draft=TEXT)
out = upd(4, reword={A: "Oliver: run the first check on the new box"})
offered("3 reword of his step", 4)
check("3 reword: no note", RETIRED_REPLY not in out, out)
item(5, next=nx(AG, A), draft=TEXT)
out = upd(5, next=nx(AG, C), dropped=[A])
offered("3 his step replaced by another in one write", 5)
check("3 replace: no note", RETIRED_REPLY not in out, out)
out = upd(5, next=AG, dropped=[C])
check("3 …the replacement closed retires it", RETIRED_REPLY in out, out)
upd(5, next=nx(AG, A))
offered("3 …and the step it replaced, open again, shows it", 5)
item(6, next=nx(AG, A), draft=TEXT)
out = upd(6, next=nx(AG, C), done=[A])
check("3 tick with a new step in the same write: retired", RETIRED_REPLY in out, out)
gone("3 tick and add", 6)
item(7, next=nx(AG, A), draft=TEXT)
out = upd(7, next=AG, dropped=[A], draft="a new text")
offered("3 a new draft set in the write that drops the old step", 7, "a new text")
check("3 …no note", RETIRED_REPLY not in out, out)
item(8, next=nx(AG, A), draft=TEXT)
out = upd(8, next=AG, done=[A], draft=TEXT)
offered("3 the same text passed again with the write that ticks", 8)
item(9, next=nx(AG, A, B), draft=TEXT)
out = upd(9, next=nx(AG, C), done=[A], dropped=[B])
offered("3 one ticked, one replaced: kept (whose draft it is cannot be known)", 9)
item(10, next=nx(AG, A), draft=TEXT)
upd(10, next=AG, dropped=[A]); upd(10, next=nx(AG, B))
out = upd(10, next=nx(AG, A), done=[B])
offered("3 a reopened step wins over another the same write ticks", 10)

# ================================================================ 4. before any step; your-step; close and clear
item(11, draft=TEXT)
offered("4 a draft with no step of his", 11)
upd(11, priority="p1")
offered("4 …after a write", 11)
upd(11, next=nx(AG, A))
offered("4 …then its step", 11)
upd(11, next=AG, dropped=[A])
gone("4 …then the step dropped", 11)
POST = "Post the message in the channel"
POST2 = "Paste the message into the tracker"
item(12)
upd(12, step=POST, draft=TEXT)
offered("4 a your-step", 12)
upd(12, step=POST2)
offered("4 step= replaced by another step=", 12)
out = upd(12, step="none", needs="home-agent")
check("4 the step withdrawn retires it", RETIRED_REPLY in out and "state" not in mt(12), (out, mt(12)))
gone("4 withdrawn", 12)
upd(12, step=POST2)
offered("4 the same step= again shows it", 12)
out = upd(12, status="completed", outcome="done", reason="finished", description="- It shipped\n- Closed as done\n- Nothing left")
check("4 a close drops the draft and its record, and the reply says so", not any(k in mt(12) for k in ("draft", "draft_closed", "draft_retired")) and "close drops the item's draft" in out and 'class="draft' not in page(12), (mt(12), out))
upd(1, next=nx(AG, B), dropped=[A])
upd(1, clear_draft=True)
check("4 clear_draft drops the record with the text", not any(k in mt(1) for k in ("draft", "draft_closed", "draft_retired")) and "draft:" not in get(1), mt(1))
out = _wt_create._create(subject="[home] filed with a draft", description=DESC, project="projects/alpha", owner="home-agent", next=nx(AG, A), needs=["home-agent"], draft=TEXT)
gid = re.match(r"created (\w)(\d+)", out)
made = json.loads((T / f"store/{gid[1]}/{gid[2]}.json").read_text())
check("4 a create stores a draft that is offered, its record empty", made["metadata"].get("draft_closed") == [] and D.of(made | {"gid": gid[1] + gid[2]}) == TEXT, made["metadata"])

# ================================================================ 5. a decision
def ask(i, a=ASK, **kw):
    return upd(i, needs="decision", ask=a, options=OPTS, **kw)


item(20)
ask(20, draft=TEXT)
offered("5 a decision with a draft", 20)
check("5 …the answer frame and the home row show it while asked", 'class="draft' in row(20) and 'class="draft' in answer_frame.item_body(ui_render.Board(f"{tmp}/store"), rd(20) | {"gid": "a20"}, "open", ("q", "form")), row(20)[-400:])
r = answer_svc._answer("a20", "Send", "", "")
g = get(20)
check("5 Send: no page offers it any more", r == "decision" and 'class="draft' not in page(20) and 'class="draft' not in row(20) and D.of(rd(20)) == "", (r, mt(20)))
check("5 Send: get still shows the text, for the session that sends it", "draft: kept for sending (he answered on it" in g and TEXT in g, g)
check("5 Send: the brief says so without the text", "draft: kept for sending" in brief(20) and "the first line" not in brief(20), brief(20))
upd(20, next="home-agent: send the note")
check("5 …and still does after the session's next write", TEXT in get(20) and "draft: kept for sending" in get(20), get(20))
try:
    ask(20, ASK2)
    check("5 another question that offers Send with no draft= is refused", False, mt(20))
except Exception as e:  # noqa: BLE001
    check("5 another question that offers Send with no draft= is refused", "draft=" in str(e) and D.of(rd(20)) == "" and "ask" not in mt(20), (str(e), mt(20)))
ask(20, ASK2, draft="the shorter text")
offered("5 …a re-ask with draft= shows the new text", 20, "the shorter text")
item(21)
ask(21, draft=TEXT)
answer_svc._answer("a21", "Change it", "shorter please", "")
check("5 Change it: kept for the session to rework", "draft: kept for sending" in get(21) and TEXT in get(21), get(21))
gates._DECISION_AGAIN_S = 0                  # the same question may be asked again an hour after his answer; here at once
ask(21)
offered("5 …the same question asked again shows it", 21)
item(22)
ask(22, draft=TEXT)
out = upd(22, clear_ask=True, clear_options=True, needs="home-agent")
check("5 an ask the session withdraws retires it", RETIRED_REPLY in out, out)
gone("5 withdrawn ask", 22)
item(23)
ask(23, draft=TEXT)
out = ask(23, ASK2)
offered("5 a changed question in one write keeps it", 23)
item(24, next=nx(AG, A))
upd(24, needs="decision", ask=ASK, options=OPTS, draft=TEXT)
answer_svc._answer("a24", "Send", "", "")
offered("5 an answer that leaves a step of his open keeps it offered", 24)

# ================================================================ 6. his Done and Send note on a step
item(30)
upd(30, step=POST, draft=TEXT)
r = answer_svc._answer("a30", "", "", "done")
check("6 Done with no other step of his open drops the draft and its record", r == "done" and not any(k in mt(30) for k in ("draft", "draft_closed", "draft_retired")), (r, mt(30)))
item(31, next=nx(AG, B))
upd(31, step=POST, draft=TEXT)
r = answer_svc._answer("a31", "", "", "done")
check("6 Done ticks every open line of his, so the draft goes with them", r == "done" and "draft" not in mt(31), (r, mt(31)))
item(32)
upd(32, step=POST, draft=TEXT)
r = answer_svc._answer("a32", "", "I will do it tomorrow", "note")
check("6 a note that names a later time holds the item and keeps the text", r == "stepreply" and mt(32).get("until"), (r, mt(32)))
gone("6 …not offered while the server's step is off the checklist", 32)
upd(32, step=POST)
offered("6 …and the same step asked again shows it", 32)
item(33, next=nx(AG, B))
upd(33, step=POST, draft=TEXT)
r = answer_svc._answer("a33", "", "the channel says forbidden", "note")
check("6 a note that leaves another line of his open keeps the draft", r == "stepreply" and mt(33).get("draft") == TEXT, (r, mt(33)))
offered("6 …and offers it beside that line", 33)
item(34)
upd(34, step=POST, draft=TEXT)
r = answer_svc._answer("a34", "", "the channel says forbidden", "note")
check("6 a note that leaves nothing of his open drops it", r == "stepreply" and not any(k in mt(34) for k in ("draft", "draft_closed", "draft_retired")), (r, mt(34)))

# ================================================================ 7. stored before the record
def old(i, steps, **meta):
    """an item as an older server stored it: the checklist given, a draft and no record of it"""
    entries = [{"text": t, "status": s, **({} if s == "open" else {"by": "home-agent", "at": now - 2 * H})} for t, s in steps]
    item(i, steps=entries, next=nx(*[t for t, s in steps if s == "open"]), draft=TEXT, **meta)


old(40, [(A, "dropped"), (AG, "open")])
was = raw(40); n_told = len(told)
gone("7 stale: his step dropped, only an agent's open", 40)
check("7 …read at the view: nothing written, nothing told", raw(40) == was and len(told) == n_told and "draft_closed" not in mt(40), mt(40))
old(41, [(A, "done"), (B, "open"), (AG, "open")])
offered("7 an open step of his: shown", 41)
old(42, [("home-agent: set it up", "done"), (AG, "open")])
offered("7 no step of his ever: shown", 42)
old(43, [(A, "done"), (AG, "open")], state="your-step", step=POST, mover="Oliver", then="home-agent")
offered("7 a your-step still standing: shown", 43)
old(44, [(A, "done"), (AG, "open")], needs=["decision"], ask=ASK, options=OPTS)
offered("7 a decision still asked: shown", 44)
old(45, [(AG, "open")])
offered("7 a draft with no checklist of his: shown", 45)
out = upd(40, priority="p1")
check("7 the first write stores what was read and says nothing", mt(40).get("draft_retired") is True and mt(40).get("draft_closed") == [S.owner_key(A)] and RETIRED_REPLY not in out and STILL_REPLY not in out, (mt(40), out))
gone("7 after the first write", 40)
upd(40, next=nx(AG, A))
offered("7 …the step open again shows it", 40)
old(46, [(A, "dropped"), (AG, "open")])
out = upd(46, next=nx(AG, B))
check("7 a first write that adds another step of his does not bring a stale draft back", STILL_REPLY in out and RETIRED_REPLY not in out, out)
gone("7 stale plus a new step", 46)
old(47, [(A, "open"), (AG, "open")])
out = upd(47, next=AG, dropped=[A])
check("7 an older draft whose step this write drops: retired, said", RETIRED_REPLY in out, out)
ARROWED = "Oliver: " + "whether to send the note now" + " → Send"
old(48, [(ARROWED, "done"), (AG, "open")], answers=[{"kind": "decision", "choice": "Send", "ts": now - 2 * H, "ask": ASK, "by": "Oliver"}])
g = get(48)
check("7 an answered decision stored before the record: no page offers it, get keeps it for sending", D.of(rd(48)) == "" and 'class="draft' not in page(48) and "draft: kept for sending" in g and TEXT in g, g)
upd(48, priority="p1")
check("7 …after the first write too", "draft: kept for sending" in get(48) and mt(48).get("draft_retired") is True, mt(48))
ask(48)
offered("7 …and the same question asked again shows it", 48)
item(49, status="completed", draft=TEXT, mover=None, outcome="done", reason="x")
check("7 a closed item offers none", D.of(rd(49)) == "" and 'class="draft' not in page(49), None)

# ================================================================ 8. the guard, the sent-mail watch, the server's own saves
item(50)
upd(50, step=POST, draft=TEXT)
upd(50, step="none", needs="home-agent")
try:
    upd(50, step="Send the note to Kim")
    check("8 guard: a step that names a text is refused on a retired draft", False, mt(50))
except Exception as e:  # noqa: BLE001
    check("8 guard: a step that names a text is refused on a retired draft, saying why", "draft=" in str(e) and "retired" in str(e) and "\n" not in str(e).strip(), str(e))
upd(50, step="Send the note to Kim", draft="for Kim")
offered("8 guard: …with draft= it stands", 50, "for Kim")
old(54, [(A, "dropped"), (AG, "open")])
try:
    upd(54, step="Send the note to Kim")
    check("8 guard: a stale draft stored before the record does not pass a new step that names a text", False, mt(54))
except Exception as e:  # noqa: BLE001
    check("8 guard: a stale draft stored before the record does not pass a new step that names a text", "retired" in str(e), str(e))
MAIL = "Send Kim the note by email: https://docs.google.com/document/d/1/edit"
item(51)
upd(51, step=MAIL, draft="zebracrossing words for kim@example.invalid")
view = lambda i: next((v for v in sent_match._views() if v["gid"] == f"a{i}"), None)
msg = lambda i: sent_match.build_message(rd(i), {"to": [("Kim", "kim@example.invalid")], "cc": [], "subject": "s", "snip": "t"})
check("8 sent-mail watch: an offered draft is read, its addresses too", "zebracrossing" in msg(51) and "kim@example.invalid" in view(51)["addrs"], (view(51), msg(51)))
upd(51, step="none", needs="home-agent")
MAIL2 = "Email Kim the summary: https://docs.google.com/document/d/2/edit"
upd(51, step=MAIL2)
check("8 sent-mail watch: a retired one is not", D.retired(rd(51)) and "<draft>(none)</draft>" in msg(51) and view(51) is not None and "kim@example.invalid" not in view(51)["addrs"], (view(51), msg(51), mt(51)))


def closed_by_server(i):
    """a save of the server's own that drops his step, with no update call"""
    it = rd(i)
    it["metadata"]["steps"] = [{**s, "status": "dropped", "by": "home-agent", "at": now} if s["text"] == A else s for s in it["metadata"]["steps"]]
    it["metadata"]["next"] = AG
    writes.save(f"a{i}", it)


old(52, [(A, "open"), (AG, "open")])
closed_by_server(52)
gone("8 a save of the server's own that closes his step retires it", 52)
old(53, [(A, "open"), (AG, "open")])
writes.save("a53", rd(53))
offered("8 …and one that closes nothing keeps it", 53)

# ================================================================ 9. an answered text is not lost before it is sent
def refused(name, i, call, *words):
    """the write is refused, says each of `words`, and stores nothing"""
    was = raw(i)
    try:
        out = call()
    except Exception as e:  # noqa: BLE001
        check(name, all(w in str(e) for w in words) and raw(i) == was, str(e))
    else:
        check(name, False, out)


def sending(name, i):
    g = get(i)
    check(f"{name}: get still prints the approved text, no page offers it", "draft: kept for sending" in g and TEXT in g and "draft: kept for sending" in brief(i) and D.of(rd(i)) == ""
          and 'class="draft' not in page(i) and 'class="draft' not in row(i), (g, mt(i)))


def sent(i, choice="Send", **kw):
    item(i, **kw)
    ask(i, draft=TEXT)
    answer_svc._answer(f"a{i}", choice, "", "")


LATER = "Oliver: open the settings page"
sent(60)
answer_svc._answer("a60", "", "one more thought", "comment")
sending("9 a comment after Send", 60)
sent(61)
r = answer_svc._answer("a61", "Change it", "on second thought", "")
check("9 a second pick on the answered question is kept as a comment", r == "stalenote" and mt(61)["answers"][-1]["kind"] == "comment", (r, mt(61)))
sending("9 a stale second pick", 61)
sent(62)
upd(62, next=nx(AG, LATER))
upd(62, next=AG, dropped=[LATER])
sending("9 another line of his added and dropped", 62)
sent(63, next=nx(AG, A))
offered("9 Send with another line of his open", 63)
upd(63, next=AG, dropped=[A])
sending("9 …that line dropped later", 63)
sent(64)
upd(64, step="Open the settings page and switch it on")
r = answer_svc._answer("a64", "", "", "done")
check("9 Done on a later step of his", r == "done" and mt(64).get("draft") == TEXT, (r, mt(64)))
sending("9 …after that Done", 64)
item(65, draft=TEXT, draft_closed=[S.owner_key(A)], draft_retired=True, ask_left={"at": now, "ask": ASK, "how": "word", "why": "no answer", "by": "", "draft": TEXT})
r = answer_svc._answer("a65", "Send", "", "")
check("9 a pick on an ask the server took off is kept as a comment", mt(65)["answers"][-1]["kind"] == "comment", (r, mt(65)))
sending("9 …and its text stays readable", 65)
sent(66)
upd(66, draft="the paste text", step=POST)
check("9 a new draft= is a new text: the answered mark goes", "draft_answered" not in mt(66), mt(66))
answer_svc._answer("a66", "", "", "done")
check("9 …and his Done on its step drops it as before", "draft" not in mt(66) and "draft:" not in get(66), mt(66))
sent(67)
upd(67, clear_draft=True)
check("9 clear_draft, once it is sent, drops the text and the whole record", not any(k.startswith("draft") for k in mt(67)) and "draft:" not in get(67), mt(67))
sent(68)
upd(68, status="completed", outcome="done", reason="finished", description="- It shipped\n- Closed as done\n- Nothing left")
check("9 a close drops it too", not any(k.startswith("draft") for k in mt(68)), mt(68))
item(69, next=nx(AG, A), draft=TEXT)
upd(69, needs="decision", ask=ASK, options=OPTS)
upd(69, clear_ask=True, clear_options=True, needs="home-agent", next=AG, dropped=[A])
check("9 a decision withdrawn unanswered marks nothing", "draft_answered" not in mt(69) and "draft: retired" in get(69), (mt(69), get(69)))

item(90, next=nx(AG, A), draft=TEXT)
ask(90)
asks_svc._ask_leave("a90", "the ask is wrong", "", ASK)
r = answer_svc._answer("a90", "Send", "", "")
check("9 a late pick on a withdrawn Send ask is a comment", mt(90)["answers"][-1]["kind"] == "comment", (r, mt(90)))
upd(90, next=AG, dropped=[A])
sending("9 a late Send pick, the other line of his closed after it: kept for sending like a pick made in time", 90)
item(91, next=nx(AG, A), draft=TEXT)
upd(91, next=AG, dropped=[A])
upd(91, needs="decision", ask=ASK2, options=[{"label": "Keep it", "line": "Keep the note", "recommended": True}, {"label": "Drop it", "line": "Drop the note", "recommended": False}])
asks_svc._ask_leave("a91", "the ask is wrong", "", ASK2)
r = answer_svc._answer("a91", "Keep it", "", "")
check("9 a late pick on an unrelated ask over a retired draft is a comment", mt(91)["answers"][-1]["kind"] == "comment", (r, mt(91)))
gone("9 …and does not mark the draft answered: it stays retired", 91)
check("9 …no answered mark", "draft_answered" not in mt(91), mt(91))
item(92, next=nx(AG, A), draft=TEXT)
upd(92, next=AG, dropped=[A])
with writes.cold_write():
    ask(92)
check("10 the server's own cold-call question that offers Send over a retired draft is not refused", mt(92).get("ask") == ASK, mt(92))

item(75)
upd(75, step="Open the settings page and switch it on")
upd(75, needs="decision", ask=ASK, options=OPTS, draft=TEXT)
answer_svc._answer("a75", "Send", "", "")
upd(75, step="none", needs="home-agent", next="home-agent: send the note")
sending("9 Send picked beside a step of his that names no text, the step then withdrawn", 75)
item(76)
upd(76, step=POST, draft=TEXT)
upd(76, needs="decision", ask=ASK, options=[{"label": "Keep", "line": "Keep the channel", "recommended": True}, {"label": "Drop", "line": "Leave the channel", "recommended": False}])
answer_svc._answer("a76", "Keep", "", "")
check("9 an answer beside a step, about no text, marks nothing", "draft_answered" not in mt(76), mt(76))

PICKED = [{"kind": "decision", "choice": "Send", "ts": now - 2 * H, "ask": ASK, "by": "Oliver"}]
old(90, [(ARROWED, "done"), (AG, "open")], answers=PICKED + [{"kind": "comment", "text": "and thanks", "ts": now - H, "by": "Oliver"}])
sending("9 stored before the record, a comment after Send", 90)
upd(90, next=nx(AG, LATER))
upd(90, next=AG, dropped=[LATER])
sending("9 …and another line of his added and dropped", 90)
old(91, [(ARROWED, "done"), (B, "dropped"), (AG, "open")], answers=PICKED)
sending("9 stored before the record, a line of his closed after Send", 91)

from stackshot.service import answer_handover as HO
real = (HO._check_his_step, HO._steps.member_for, HO._steps.member_rows)
HO._check_his_step = lambda *a, **k: None
HO._steps.member_for = lambda text, meta=None: "Oliver"
HO._steps.member_rows = lambda meta: ([{"text": "Kim: do the rest", "status": "open"}], [0], ["Kim"])
try:
    for mark in (True, False):
        shared = {"owner": OWNER, "state": "your-step", "step": "Do your part", "draft": TEXT, "draft_closed": [], **({"draft_answered": True} if mark else {})}
        HO._share_step(shared, {"kind": "decision"}, "Oliver", True, now)
        check("9 a shared step passing on " + ("keeps an answered text" if mark else "takes its own draft with it"), ("draft" in shared) is mark, shared)
finally:
    HO._check_his_step, HO._steps.member_for, HO._steps.member_rows = real

# ================================================================ 10. the guards read the draft as the save leaves it
item(70, next=nx(AG, A), draft=TEXT)
refused("10 a tick and a paste step in one write, no draft=: refused as in two writes", 70, lambda: upd(70, done=[A], step=POST2), "retired", "draft=")
item(74, next=nx(AG, A), draft=TEXT)
upd(74, done=[A], step=POST2, draft="for the tracker")
offered("10 …with draft= it stands", 74, "for the tracker")
old(71, [(A, "open"), (AG, "open")])
refused("10 the same on a draft stored before the record", 71, lambda: upd(71, done=[A], step=POST2), "retired")
item(72, next=nx(AG, A), draft=TEXT)
upd(72, dropped=[A], step=POST2)
offered("10 a line replaced by a paste step in one write keeps the box", 72)
item(73, next=nx(AG, A), draft=TEXT)
upd(73, done=[A], step="Paste the note from https://docs.google.com/document/d/3/edit into the tracker")
check("10 a tick with a paste step that links the document passes", D.retired(rd(73)), mt(73))
KEEP = [{"label": "Keep it", "line": "Keep the note", "recommended": True}, {"label": "Drop it", "line": "Drop the note", "recommended": False}]
sent(80, "Change it")
refused("10 a reworded decision that offers Send after his answer, no draft=: refused", 80, lambda: ask(80, ASK2), "draft=", "retired", "clear_draft")
ask(80, ASK2, draft="the reworked text")
offered("10 …with draft= the new text is shown", 80, "the reworked text")
sent(81, "Change it")
ask(81, ASK2, clear_draft=True)
check("10 …clear_draft passes for a question about no text", "draft" not in mt(81) and mt(81).get("ask") == ASK2, mt(81))
sent(82)
upd(82, needs="decision", ask=ASK2, options=KEEP)
check("10 options that offer no text pass, and the answered text stays readable", mt(82).get("ask") == ASK2 and TEXT in get(82), (mt(82), get(82)))
refused("10 options reworded to offer Send on that question: refused", 82, lambda: upd(82, options=OPTS), "draft=")
item(83, next=nx(AG, A), draft=TEXT)
refused("10 a tick and a Send decision in one write, no draft=: refused", 83, lambda: ask(83, done=[A]), "draft=")
item(84, next=nx(AG, A), draft=TEXT)
upd(84, next=AG, dropped=[A])
refused("10 a Send decision after the line was dropped: refused", 84, lambda: ask(84), "draft=")

print(("ok" if not fails else "FAILED") + f": draft retire scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
