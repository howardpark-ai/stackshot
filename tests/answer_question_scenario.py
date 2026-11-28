"""Scenario test for a question typed in place of an answer (docs/asks-and-answers.md, *A question in place of an answer*) — fixture data, the real answer path, update tool, GitHub comment
hook and answer frame state on a temporary store, no network, no live store.

Covers: the reading of typed words (model/note_read.py is_question: every sentence a question; a yes or a no, an option's name, a statement, a semicolon or a dash keep them a decision); a
question typed on a decision item is recorded as a comment marked `question`, takes no option, ticks no step, leaves his queue for the mover and says what to do on the line to it; the same
decision put back is refused while the description is the one he asked under (nothing written) and accepted at once with the same ask line after a rewrite, in that write or an earlier one; a
pick, and words that say something beside what they ask, still hold the same ask for an hour whatever the description says; a question comment does not lift the hold of a decision before it;
a stale form's question and a GitHub comment are marked; the answer frame shows no older answer after a question.

    tests/run-suite answer_question        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="askquestion-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root"]', toml); assert n == 1      # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1      # the writes here replace next wholesale; the checklist has its own suite
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state", "brain/projects"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "team-back", "home-front")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-front",
                                                                                "status": "active", "board": [], "board_open": 0, "agents": {"home-front": "the front", "team-back": "the back"},
                                                                                "back_agents": {"team-back": "the back"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-front\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
BACK = "team-back"
DESC = "- A thing\n- It lives here\n- Done when done"
DESC2 = "- A thing\n- It lives here\n- Answer to your question: it costs nothing more\n- Done when done"
ASK = "Decide: ship the thing now · Recommend: yes · Stakes: a week of delay · By: no date"
ASK2 = "Decide: ship the thing next week · Recommend: yes · Stakes: two weeks of delay · By: no date"
ASK_O = "Decide: which way to ship · Recommend: Slowly · Stakes: a week of delay · By: no date"
OPTS = [{"label": "Slowly", "line": "one step at a time", "recommended": True}, {"label": "At once", "line": "all of it today"}]


def item(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": "open", "updated": time.time(), "state_updated": time.time() - 7200,
                                                     "confirmed": time.time() - 7200, "metadata": {"owner": U[BACK], "mover": BACK, "project": "projects/alpha", "next": "do the thing", "needs": [], **meta}}))


def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def raw(i): return (T / f"store/a/{i}.json").read_text()
def mt(i): return rd(i)["metadata"]
def last(i): return mt(i)["answers"][-1]
def his(i): return [s.get("status") for s in mt(i).get("steps") or [] if s.get("text") != "do the thing"]      # the states of his steps (the other is the mover's own next)


fails = []; ran = []


def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))


sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server  # noqa: F401  (installs the hooks the services reach the web side through)
from stackshot.web import publish as _web_publish, page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route
from stackshot.service import answer as answer_svc, github_events as ghev_svc, update as update_svc, telling
from stackshot.model import note_read, ask_read
from stackshot.web.ui import render, answer_frame as ui_frame

_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
told = []
telling.tell_woken = lambda gid, sid, note, tag="wake": told.append((gid, sid, note))
telling.front_sender = lambda who: False


def upd(i, **kw): return update_svc._update(f"a{i}", sender=BACK, **kw)


def refused(name, i, f, *want, never=()):
    """refused with the words, and the item's file is byte for byte as it was"""
    was = raw(i)
    try:
        out = f(); check(name, False, out)
    except Exception as e:  # noqa: BLE001
        check(name, all(w in str(e) for w in want) and not any(w in str(e) for w in never), str(e))
    check(name + " (nothing written)", raw(i) == was)


def passes(name, i, **kw):
    """accepted: a refusal is one failed check, not the end of the run"""
    try:
        upd(i, **kw); check(name, True)
    except Exception as e:  # noqa: BLE001
        check(name, False, str(e))


def ask(i, line=ASK, **kw):
    """an item put on his call by a session's write, so the server makes his step"""
    item(i)
    upd(i, needs=["decision"], ask=line, **kw)


# ================================================================ 2. a question in place of his call
ask(1)
check("2: (setup) the write that asks makes his step", his(1) == ["open"], mt(1))
del told[:]
saves, real_save = [], answer_svc._writes.save
def spy(gid, it, **kw):
    saves.append([s_.get("status") for s_ in it["metadata"].get("steps") or [] if s_.get("text") != "do the thing"])      # his steps as the caller hands them to the save
    return real_save(gid, it, **kw)
answer_svc._writes.save = spy
out = answer_svc._answer("a1", "", "What does it cost?", "answer")
answer_svc._writes.save = real_save
check("2: the answer's own save already drops his step: it is not left to a later one", saves[:1] == [["dropped"]], saves)
rec = last(1)
check("2: the page is told it was a comment", out == "comment", out)
check("2: the record is a comment marked as a question, with his words, the ask and the description's mark", rec["kind"] == "comment" and rec.get("question") is True and rec["text"] == "What does it cost?"
      and rec.get("ask") == ASK and rec.get("description_at") and "choice" not in rec and "options" not in rec, rec)
check("2: it leaves his queue for the mover", "decision" not in mt(1).get("needs", []) and "ask" not in mt(1) and mt(1).get("mover") == BACK, mt(1))
check("2: no step of his reads as done or answered", his(1) == ["dropped"] and "What does it cost" not in json.dumps(mt(1).get("steps") or []), mt(1).get("steps"))
lines = [n for g, s, n in told if g == "a1" and s == U[BACK]]
check("2: the mover is told once that it is a question and what to do", len(lines) == 1 and "asked a question on" in lines[0] and "No decision is taken" in lines[0] and "same ask line is accepted at once" in lines[0]
      and "?." not in lines[0], told)
check("2: …and the answer waits for a write as a decision does", "a1" in json.loads((T / "state/answers.json").read_text()))
refused("2: the decision put back with no answer on the item is refused, saying to answer it there", 1, lambda: upd(1, needs=["decision"], ask=ASK),
        "asked a question", "does not answer yet", "description", "accepted at once", never=("one ask per decision",))
refused("2: …also when the write sends the description as it stands, spacing aside", 1, lambda: upd(1, needs=["decision"], ask=ASK, description=DESC.replace(" ", "  ")), "asked a question")
passes("2: with the answer in the description of the same write the same ask line is accepted at once", 1, needs=["decision"], ask=ASK, description=DESC2)
check("2: …and is his to decide again", mt(1).get("needs") == ["decision"] and mt(1).get("ask") == ASK, mt(1))
check("2: …and his step is open again", his(1).count("open") == 1, mt(1).get("steps"))
check("2: his words stay on the item as he typed them", [a["text"] for a in mt(1)["answers"]] == ["What does it cost?"], mt(1)["answers"])

ask(2)
answer_svc._answer("a2", "", "Why now?", "answer")
upd(2, description=DESC2)
passes("2: an earlier write's rewrite counts as well", 2, needs=["decision"], ask=ASK)

ask(3, ASK_O, options=OPTS)
answer_svc._answer("a3", "", "How long is slowly?", "answer")
check("2: a question on an ask with options takes none and leaves them on the item", [o["label"] for o in mt(3).get("options") or []] == ["Slowly", "At once"] and "choice" not in last(3) and "options" not in last(3), mt(3))
read_history, telling.touched_or_unknown = telling.touched_or_unknown, lambda *a: False      # this store keeps no history: the writer is taken as one that has not written since
note = update_svc._answered_since_note("a3", rd(3), "home-owner")
telling.touched_or_unknown = read_history
check("2: the note to a session that has not written since says he asked a question", "asked a question on" in note, note)
refused("2: …with no ask line in the write at all it is refused too", 3, lambda: upd(3, needs=["decision"]), "asked a question")
passes("2: a changed ask line passes, answered or not", 3, needs=["decision"], ask=ASK2, options=[])

# ================================================================ 3. a decision still holds
for i, what, args in ((10, "typed words that decide", ("", "ship it", "answer")), (11, "a yes with a question added", ("", "yes, but why so late?", "answer")),
                      (12, "a statement beside a question", ("", "Ship it. Who tells them?", "answer")), (13, "a pressed pick with a question as its note", ("Yes", "why so late?", "answer"))):
    ask(i)
    out = answer_svc._answer(f"a{i}", *args)
    check(f"3: {what} is his decision", out == "decision" and last(i)["kind"] == "decision" and "question" not in last(i) and his(i) == ["done"], (out, mt(i)))
    refused(f"3: …and the same ask stays refused after a rewrite ({what})", i, lambda: upd(i, needs=["decision"], ask=ASK, description=DESC2), "one ask per decision")

ask(14, ASK_O, options=OPTS)
out = answer_svc._answer("a14", "", "B: can it start today?", "answer")
check("3: typed words that open with an option's letter are his decision", out == "decision" and "question" not in last(14), (out, last(14)))

ask(20)
answer_svc._answer("a20", "", "ship it", "answer")
answer_svc._answer("a20", "", "Who tells them?", "comment")
check("3: (setup) a question typed as a comment is marked and carries no ask", last(20).get("question") is True and "ask" not in last(20), last(20))
refused("3: a question after his decision does not lift its hold before an answer", 20, lambda: upd(20, needs=["decision"], ask=ASK), "asked a question")
refused("3: …nor after one", 20, lambda: upd(20, needs=["decision"], ask=ASK, description=DESC2), "one ask per decision")

ask(21)
answer_svc._answer("a21", "", "Who tells them?", "comment")
check("3: a question typed as a comment while the item is on his call leaves it there", "decision" in mt(21)["needs"] and mt(21)["ask"] == ASK and last(21).get("question") is True, mt(21))

ask(22)
answer_svc._answer("a22", "", "Why now?", "answer")
it = rd(22); it["metadata"]["answers"][-1]["ts"] = time.time() - 3700
(T / "store/a/22.json").write_text(json.dumps(it))
passes("3: an hour after the question the same ask passes, as after any words of his", 22, needs=["decision"], ask=ASK)

# ---- a newer question typed as a comment holds no ask of its own: the ask he was asking about still stands
DESC3 = DESC2.replace("nothing more", "nothing more, and we pay")


def comment_by(way, i, text, n):
    if way == "board":
        answer_svc._answer(f"a{i}", "", text, "comment")
    else:
        ghev_svc._github_comment(f"a{i}", {"id": n, "ts": time.time(), "text": text, "url": f"https://example.test/{n}"})


for i, way in ((23, "board"), (24, "GitHub")):
    ask(i)
    answer_svc._answer(f"a{i}", "", "What does it cost?", "answer")
    comment_by(way, i, "And who pays?", 200 + i)
    check(f"3: (setup, {way}) the later question comment is marked and stores no ask", last(i).get("question") is True and "ask" not in last(i) and len(mt(i)["answers"]) == 2, mt(i)["answers"])
    refused(f"3: a question comment ({way}) after a question in place of his call keeps the ask held", i, lambda: upd(i, needs=["decision"], ask=ASK), "asked a question", "does not answer yet")
    passes(f"3: …and the rewrite lets the same ask line through ({way})", i, needs=["decision"], ask=ASK, description=DESC2)

for i, way in ((25, "board"), (26, "GitHub")):
    ask(i)
    answer_svc._answer(f"a{i}", "", "What does it cost?", "answer")
    upd(i, description=DESC2)
    comment_by(way, i, "And who pays?", 200 + i)
    refused(f"3: an answered question, a rewrite, then a new question ({way}): the ask is still held", i, lambda: upd(i, needs=["decision"], ask=ASK), "asked a question", "does not answer yet")
    refused(f"3: …also when the write sends the description he asked under ({way})", i, lambda: upd(i, needs=["decision"], ask=ASK, description=DESC2), "asked a question")
    passes(f"3: …until the new question is answered on the item too ({way})", i, needs=["decision"], ask=ASK, description=DESC3)

ask(27)
answer_svc._answer("a27", "", "What does it cost?", "answer")
comment_by("board", 27, "And who pays?", 227)
comment_by("GitHub", 27, "And when?", 228)
refused("3: several question comments in a row keep it held", 27, lambda: upd(27, needs=["decision"], ask=ASK), "asked a question")
passes("3: …and a changed ask line still passes", 27, needs=["decision"], ask=ASK2)

# ================================================================ 4. the other ways his words arrive
ask(30)
out = answer_svc._answer("a30", "", "Why that one?", "answer", ref="0" * 12)
check("4: a question from a form that showed an older question is kept as a comment, marked", out == "stalenote" and last(30).get("question") is True and "Why that one?" in last(30)["text"] and "decision" in mt(30)["needs"], (out, last(30)))
ask(31)
ghev_svc._github_comment("a31", {"id": 99, "ts": time.time(), "text": "Why that one?", "url": "https://example.test/c"})
ghev_svc._github_comment("a31", {"id": 100, "ts": time.time(), "text": "go ahead", "url": "https://example.test/d"})
check("4: a GitHub comment that is a question is marked, another is not", [a.get("question") for a in mt(31)["answers"]] == [True, None] and "decision" in mt(31)["needs"], mt(31)["answers"])

# ================================================================ 4b. the words other lines use for a question
ask(32)
answer_svc._answer("a32", "", "Why now?", "answer")
ask(33)
answer_svc._answer("a33", "", "ship it", "answer")
del told[:]
answer_svc._answer_tick(time.time() + 1801)
for i, want, never in ((32, "asked a question on", "answered"), (33, "answered", "asked a question")):
    lines = [n for g, s, n in told if g == f"a{i}"]
    check(f"4b: the line to the keeper on an unacted item says what he did ({i})", len(lines) == 1 and want in lines[0].split(" on the board at ")[0] and never not in lines[0].split(" on the board at ")[0], lines)

WATCHED = "Decide: has the lease arrived? " + chr(0xB7) + " Options: arrived / drop"      # a watcher's ask: no Recommend part
item(34, needs=["decision"], ask=WATCHED, watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the lease", "post_wake_mover": BACK}})
answer_svc._answer("a34", "", "Which lease is this?", "answer")
woke = str((mt(34).get("woke") or {}).get("what") or "")
check("4b: a question on a watcher ask is not called an answer on the item", "asked a question" in woke and "Which lease is this?" in woke and "answered" not in woke, mt(34).get("woke"))
item(35, needs=["decision"], ask=WATCHED, watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the lease", "post_wake_mover": BACK}})
answer_svc._answer("a35", "", "not yet, try next week", "answer")
check("4b: …and words that decide still read as one", "answered in words" in str((mt(35).get("woke") or {}).get("what") or ""), mt(35).get("woke"))

# ================================================================ 5. the answer frame
ask(40)
answer_svc._answer("a40", "", "ship it", "answer")
passes("5: (setup) a changed ask line is put to him", 40, needs=["decision"], ask=ASK2)
drawn = time.time() - 1
answer_svc._answer("a40", "", "Why next week?", "answer")
board = render.Board(str(T / "store"))
state = lambda was, since: ui_frame.state_of(board, board.item("a40"), "t", was, since)
check("5: after a question the frame that drew it shows closed", state("ref", drawn)[0] == "closed", state("ref", drawn))
check("5: …and a first load shows no older answer as its answer", state("", None)[0] == "closed", state("", None))

# ================================================================ 6. the reading
reads = lambda t, *names: note_read.is_question(t, ask_read.recommend_stance, names)
WIDE = chr(0xFF1F)
QUESTIONS = ["Why that one?", "What does it cost? And who pays?", "Why that one?\nWhen?", "(is it safe?)", "Is that so" + WIDE, "Why" + WIDE + "When" + WIDE, "Is version 3.5 meant?"]
DECIDED = ["", "ship it", "Ship it. Why was it late?", "Why was it late? Ship it", "yes, but why that one?", "No, why would we?", "I wonder; is it safe?", "ship it - can you do it today?",
           "ship it " + chr(0x2014) + " today?", "ship it " + chr(0x2013) + " today?", "why that one", "ship it" + chr(0x3002) + "why" + WIDE]
ELL = chr(0x2026)
YES_KO, WHEN_KO = "\uc88b\uc544", "\uc5b8\uc81c \uc2dc\uc791\ud574?"      # Korean "good" and "when does it start?"
DECIDED += ["ship it" + ELL + " why?", "ship it" + ELL + "why?", "ship it...why?", "Ship it.Who tells them?", YES_KO + "." + WHEN_KO, YES_KO + ELL + WHEN_KO]
QUESTIONS += ["Why" + ELL + "?", "Is it safe...?", "Is server.py ready?", "Is example.com up?", "Is README.MD there?", WHEN_KO]
check("6: words that are nothing but questions read as a question", [t for t in QUESTIONS if not reads(t)] == [], [t for t in QUESTIONS if not reads(t)])
check("6: …a statement beside the question, a yes or a no, a semicolon or a dash keeps them a decision", [t for t in DECIDED if reads(t)] == [], [t for t in DECIDED if reads(t)])
NAMED = ["B, but why so late?", "Slowly: can it start today?", "option A) when?"]
check("6: …and so does an option's name or letter set off in front", [t for t in NAMED if reads(t, "Slowly", "At once", "A", "B")] == [], [t for t in NAMED if reads(t, "Slowly", "At once", "A", "B")])
check("6: an option's name inside a question is no pick", reads("Slowly means how many days?", "Slowly", "At once"))

print(("ok" if not fails else "FAILED") + f": answer question scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
