"""Scenario test for who may answer on a board of several members, only the member an item asks (model/member_gates.py, service/answer.py, service/handoff.py, service/github_events.py,
web/routes/answers.py, ui/render.py, ui/answer_frame.py) — made-up data, a temp folder, the routes through Starlette's test client, no live store, no network.

A board of two members (member-a the first, member-b with the alias MB). Covers:

  * whom an item asks: the member the ask's Decide part opens with, else the stored mover, else a line of next, else the first member; a step is every member's who has a part in it;
  * another member's pick, typed answer, Done and note: kept as their own comment, or nothing written; the ask, the options, the checklist, the state, the mover, the clock and a hand-off stay, no park is set,
    no answer is left pending and the sessions are told of the comment;
  * the member asked answers as before;
  * the item page (a comment box for the others), the tokens of the rows' forms, the answer frame and the notice;
  * each reason a Done on a step is refused, by itself: another member's question, one's own question on a step two members have had, a mail tick on another member's step, no part in the step; the notice a
    member with a part in the step gets while the question stands says what to do;
  * a hand-off to a member is not ended by another member's comment, on the board or on GitHub;
  * a question beside a step, asked of the other member: each member's Home (the asked one's Your move with the cards, the step's owner waiting on that pick, another member with a line on it left on
    Your move with no form), the pages and tokens, the Done held until the pick, and the step finished after it; options with no ask hold another member's Done too; a stored ask with no decision need
    holds nothing;
  * the answer line a script reads: a decision of a member who was not asked, and another member's Done on a shared step, are no decision;
  * the lines the sessions get say "their" beside a member's name (one member: "his"), and an item that cannot be read gives no token;
  * one member: whatever an ask names, the item gets its answer form, a token and an open frame, a pick is a decision, a comment ends the hand-off, and the notice only a board of several members answers
    with is left out.

    tests/run-suite answer_other_person  → exit 0 / 1"""
import html, json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="answer-other-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
PARENT = "https://chat.example.com"
ADA, BEA = "member-a@example.org", "member-b@example.org"
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml = _instance.set_person(toml, "member-a")
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{ADA}"]'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^panel = true', 'panel = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchors", "brain/projects", "secrets", "touch"): (T / d).mkdir(parents=True)
BUILD_S = "00000000-0000-4000-8000-000000000001"
FRONT_S = "00000000-0000-4000-8000-000000000002"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({BUILD_S: {"name": "alpha-build", "machine": "a", "seen": now}, FRONT_S: {"name": "alpha-main", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "agents": {"alpha-build": "builds it"}, "back_agents": {"alpha-build": "builds it"}, "status": "active", "board": [], "board_open": 0}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
ASK = "Decide: ship ZEBRAWORD on Friday · Recommend: yes · Stakes: low · By: Fri"
ASK_B = "Decide: member-b: pick GIRAFFEWORD · Recommend: yes · Stakes: low · By: Fri"
OPTS = [{"label": "Ship it", "line": "Ship on Friday.", "recommended": True}, {"label": "Hold it", "line": "Wait a week.", "recommended": False},
        {"label": "Park it", "line": "Look again later.", "recommended": False, "wake": "2099-01-01"}]


def item(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[work] item a{i}", "description": "- A fixture item.", "status": "open",
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": BUILD_S, "project": "projects/alpha", **meta}}))


def question(i, ask=ASK, options=OPTS, **meta):
    item(i, needs=["decision"], ask=ask, **({"options": options} if options else {}), **meta)


def step(i, who="member-a", **meta):
    item(i, **{"state": "your-step", "step": f"sign WHY{i}", "mover": who, "then": "alpha-build", "next": f"{who}: sign WHY{i}", **meta})


def handed(to):
    return {"to": to, "from": "alpha-main", "at": now - 1800, "delivered_at": now - 1700, "taken_at": None, "events": []}


question(1, mover="member-a", then="alpha-build", draft="ALPHADRAFT to paste.", next="member-a: answer the ask above", handoff=handed("member-a"))
question(2, ask=ASK_B, mover="member-a", then="alpha-build")                  # the Decide part names member-b, whatever the stored mover says
question(3, next="MB: decide it", then="alpha-build")                         # no mover: the member a line of next opens with
question(4, options=None, then="alpha-build")                                 # nobody named: the first member; no stored options, so Yes and No
step(5)
item(6, needs=["alpha-build"], mover="alpha-build", next="alpha-build: build it")      # asks no member
question(7, mover="member-b", then="alpha-build", handoff=handed("member-b"), next="member-b: answer the ask above")
question(8, mover="member-b", then="alpha-build", handoff=handed("member-b"), next="member-b: answer the ask above")
question(9, mover="member-a", then="alpha-build", handoff=handed("member-a"), next="member-a: answer the ask above")
step(10, who="member-b")
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
logging.disable(logging.INFO)
fails, ran = [], []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""), flush=True)


def rd(i): return json.loads((T / f"store/a/{i}.json").read_text(encoding="utf-8"))


from stackshot.web import server, i18n
from stackshot.core import config as _cfg
from stackshot.model import ask_leaves as _askl
from stackshot.model import member_gates as _mgates
from stackshot.model import steps as _steps
from stackshot.service import answer as answer_svc
from stackshot.service import answer_handover as handover_svc
from stackshot.service import github_events as ghev_svc
from stackshot.service import store as _svcstore
from stackshot.service import telling
from stackshot.service import writes as _writes
from stackshot.waits import handoff as _ho
from stackshot.web import answers as _web_answers
from stackshot.web import board_home
from stackshot.web import publish as _web_publish
from stackshot.web.ui import render as ui_render
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route
from stackshot.web.auth import signin as _signin

_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
told = []      # (item, the line)
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, note))
telling.tell_kind = lambda kind, gid, owner, note, tag="wake": told.append((gid, note))
telling.tell_own_move = lambda gid, owner, note, **k: told.append((gid, note))
telling.gate_result = lambda: ("", "")
telling.tell_comment = lambda *a, **k: []
ONE = [{"name": "member-a", "emails": [ADA]}]
TWO = [*ONE, {"name": "member-b", "aliases": ["MB"], "emails": [BEA]}]
_cfg.CFG["members"] = TWO
_cfg.CFG.setdefault("ui", {})["answer_frame_origins"] = [PARENT]

for i in range(1, 11):      # one save of the server's own: each item then holds what any first save puts on it (its member's step on the checklist), so a later save that changes nothing shows as that
    with _writes.ITEM_LOCK:
        _writes.save(f"a{i}", _svcstore._load(f"a{i}"))

from starlette.testclient import TestClient

COOKIE = {e: _signin._ui_sign(json.dumps({"email": e, "exp": time.time() + 3600})) for e in (ADA, BEA)}


def meta(i): return rd(i)["metadata"]
def kept(i): return {k: v for k, v in meta(i).items() if k != "answers"}      # all of the item's record but its answers
def last(i): return (meta(i).get("answers") or [{}])[-1]
def pending(i): return f"a{i}" in _web_answers._answers_load()
def said(i): return [text for gid, text in told if gid == f"a{i}"]
def handoff_open(i): return _ho.pending_his({**rd(i), "gid": f"a{i}"}) is not None
def code(r): return re.search(r"[?&]sent=([a-z]+)", r.headers.get("location", "")).group(1) if "sent=" in r.headers.get("location", "") else f"{r.status_code} {r.text[:200]}"


def only_a_comment(i, was, text, by):
    """The one write another member's words make: a comment of theirs on the record, everything else of the item as it was."""
    rec = last(i)
    got = {k: v for k, v in rec.items() if k in ("kind", "text", "via", "by", "choice", "step")}
    want = {"kind": "comment", "text": text, "via": "board", **({"by": by} if by else {})}
    return (got == want and kept(i) == was["metadata"] and rd(i)["state_updated"] == was["state_updated"] and rd(i)["status"] == "open"
            and len(meta(i)["answers"]) == len(was.get("answers_before", [])) + 1)


def before(i):
    r = rd(i)
    m = dict(r["metadata"])
    answers = m.pop("answers", [])
    return {"metadata": m, "state_updated": r["state_updated"], "answers_before": answers}


with TestClient(server.mcp.http_app(), base_url=BOARD, raise_server_exceptions=False) as c:
    def get(path, email):
        c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE[email])
        return c.get(path, follow_redirects=False)

    def post(i, email, **data):
        c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE[email])
        return c.post(f"/items/a{i}/answer", data={"token": _web_answers._answer_token(email, f"a{i}"), **data}, headers={"Origin": BOARD}, follow_redirects=False)

    def page(i, email): return get(f"/items/a{i}", email).text

    def form_of(i, email):
        p = page(i, email)
        found = re.findall(r'<form class="ianswer"[^>]*>.*?</form>', p, re.S)
        return "".join(found)

    def tokens(email, *items): return sorted(get("/answer-tokens?ids=" + ",".join(f"a{i}" for i in items), email).json())

    def frame(i, email):
        r = get(f"/items/a{i}/answer-frame", email)
        state = re.search(r'data-state="([^"]*)"', r.text)
        return (state.group(1) if state else f"{r.status_code}"), r.text

    # ---- 1. whom an item asks
    asked = {i: _mgates.asked_member(meta(i)) for i in (1, 2, 3, 4)}
    check("a question is asked of the member its Decide part opens with, else of the item's member", asked == {1: "member-a", 2: "member-b", 3: "member-b", 4: "member-a"}, asked)
    may = {i: [m for m in ("member-a", "member-b") if _mgates.may_answer(meta(i), m)] for i in (1, 2, 3, 4, 5, 10)}
    check("…and only that member may answer it; a step is its member's", may == {1: ["member-a"], 2: ["member-b"], 3: ["member-b"], 4: ["member-a"], 5: ["member-a"], 10: ["member-b"]}, may)

    # ---- 2. the item page, the row tokens and the frame, before anyone answers
    for i, mine, other in ((1, ADA, BEA), (2, BEA, ADA), (3, BEA, ADA), (4, ADA, BEA)):
        a, b = form_of(i, mine), form_of(i, other)
        check(f"item {i}'s page draws the answer cards for the member asked", 'name="choice"' in a and 'value="answer"' in a, a[:600])
        check(f"item {i}'s page draws the other member a comment box and nothing that answers", 'value="comment"' in b and 'name="choice"' not in b and 'value="answer"' not in b and 'value="done"' not in b, b[:600])
    seen = page(1, BEA)
    check("the other member still reads the question and its options", "ZEBRAWORD" in seen and "Ship on Friday." in seen and 'class="iopts"' in seen, seen[-3000:])
    a, b = form_of(5, ADA), form_of(5, BEA)
    check("a step's Done and Send note are drawn for its member alone, the other has a comment box", 'value="done"' in a and 'value="note"' in a and 'value="done"' not in b and 'value="note"' not in b and 'value="comment"' in b, (a[:400], b[:400]))
    check("the tokens for the rows' forms are given for what asks the signed-in member", tokens(ADA, 1, 2, 3, 4, 5, 10) == ["a1", "a4", "a5"] and tokens(BEA, 1, 2, 3, 4, 5, 10) == ["a10", "a2", "a3"], (tokens(ADA, 1, 2, 3, 4, 5, 10), tokens(BEA, 1, 2, 3, 4, 5, 10)))
    for i, mine, other in ((1, ADA, BEA), (2, BEA, ADA)):
        sm, tm = frame(i, mine)
        so, to = frame(i, other)
        check(f"item {i}'s answer frame is open for the member asked", sm == "open" and 'name="choice"' in tm and _web_answers._answer_token(mine, f"a{i}") in tm, (sm, tm[-1500:]))
        check(f"item {i}'s answer frame is closed to the other member: no token, nothing to pick", so == "closed" and 'name="choice"' not in to and _web_answers._answer_token(other, f"a{i}") not in to, (so, to[-1500:]))
    msgs = json.loads(html.unescape(re.search(r'data-msgs="([^"]*)"', frame(1, ADA)[1]).group(1)))
    check("the frame knows the notice", msgs.get("notyours") == ["warn", i18n.EN["sent.notyours_home"]], msgs.get("notyours"))
    board_home._board_home_drop()
    item_page = html.unescape(get("/items/a1?sent=notyours", BEA).text)
    check("the item page words the notice", i18n.EN["sent.notyours"] in item_page and i18n.EN["sent.notyours"] not in html.unescape(page(1, BEA)), item_page[:1500])
    home_page = html.unescape(get("/?sent=notyours", BEA).text)
    check("…and the home page its own wording", i18n.EN["sent.notyours_home"] in home_page, home_page[:1500])

    # ---- 3. another member on a question: a pick, a typed answer, a Done, a note
    told.clear()
    was = rd(1)
    r = post(1, BEA, choice="Ship it", act="answer")
    check("another member's pick with no note writes nothing", code(r) == "notyours" and rd(1) == was, (code(r), meta(1)))
    r = post(1, BEA, choice="Park it", act="answer")
    check("…nor does a card that carries a wake", code(r) == "notyours" and rd(1) == was, (code(r), meta(1)))
    r = post(1, BEA, act="done")
    check("…a Done on a question that is no step writes nothing", code(r) == "nostep" and rd(1) == was, (code(r), meta(1)))
    out = answer_svc._answer("a1", "Ship it", "", "answer", by="MB")
    check("…and the answer path refuses it whoever calls, an alias read as its member", out == "notyours" and rd(1) == was, (out, meta(1)))
    check("…nobody is told and nothing is pending", not said(1) and not pending(1), (said(1), pending(1)))
    snap = before(1)
    r = post(1, BEA, choice="Park it", text="I would wait", act="answer")
    check("another member's pick with a note is kept as their comment, the card named in front of it; nothing else of the item changes", code(r) == "comment" and only_a_comment(1, snap, "(pressed: Park it) I would wait", "member-b"), (code(r), last(1), kept(1), snap["metadata"]))
    check("…no park, no pending answer, and the sessions are told of a comment", "until" not in meta(1) and not pending(1) and any("member-b commented on" in t and "I would wait" in t for t in said(1)), (meta(1).get("until"), pending(1), said(1)))
    check("…the hand-off to the member asked stays open", handoff_open(1), meta(1).get("handoff"))
    for label, data, words in (("typed answer", {"act": "answer", "text": "my two cents"}, "my two cents"), ("comment", {"act": "comment", "text": "a plain word"}, "a plain word"),
                               ("note", {"act": "note", "text": "a side note"}, "a side note")):
        snap = before(1)
        r = post(1, BEA, **data)
        check(f"another member's {label} is a comment of theirs and answers nothing", code(r) == "comment" and only_a_comment(1, snap, words, "member-b") and not pending(1) and handoff_open(1), (code(r), last(1), meta(1)))
    for i, other, by, opt in ((2, ADA, "", "Hold it"), (3, ADA, "", "Hold it"), (4, BEA, "member-b", "Yes")):
        was = rd(i)
        r = post(i, other, choice=opt, act="answer")
        check(f"item {i}: a pick by the member not asked writes nothing", code(r) == "notyours" and rd(i) == was, (code(r), meta(i)))
        snap = before(i)
        r = post(i, other, choice=opt, text="from the side", act="answer")
        check(f"item {i}: …and with a note it is their comment", code(r) == "comment" and only_a_comment(i, snap, f"(pressed: {opt}) from the side", by) and not pending(i), (code(r), last(i), meta(i)))

    # ---- 4. the member asked answers as before
    r = post(1, ADA, choice="Ship it", act="answer")
    m = meta(1)
    check("the member asked picks: a decision, the question off the item, the item handed on, the answer pending", code(r) == "decision" and "ask" not in m and "options" not in m and "decision" not in (m.get("needs") or []) and m.get("mover") == "alpha-build"
          and last(1)["kind"] == "decision" and last(1)["choice"] == "Ship it" and "by" not in last(1) and pending(1) and not handoff_open(1), (code(r), m, pending(1)))
    for i, label in ((2, "Ship it"), (3, "Ship it")):
        r = post(i, BEA, choice=label, act="answer")
        check(f"item {i}: the second member, asked, picks: a decision under their name", code(r) == "decision" and "ask" not in meta(i) and last(i).get("by") == "member-b" and last(i)["kind"] == "decision" and pending(i), (code(r), meta(i)))
    r = post(4, ADA, choice="Yes", act="answer")
    check("item 4: the first member, asked, picks Yes", code(r) == "decision" and "ask" not in meta(4) and last(4)["choice"] == "Yes", (code(r), meta(4)))

    # ---- 5. a step
    was = rd(5)
    r = post(5, BEA, act="done")
    check("a Done by a member with no part in the step writes nothing", code(r) == "nostep" and rd(5) == was, (code(r), meta(5)))
    snap = before(5)
    r = post(5, BEA, act="note", text="ran it")
    check("…their note, even one that says done, is a comment: the step stands", code(r) == "comment" and only_a_comment(5, snap, "ran it", "member-b") and not pending(5), (code(r), last(5), meta(5)))
    r = post(5, ADA, act="done")
    check("…and the step's member finishes it", code(r) == "done" and meta(5).get("state") != "your-step" and meta(5).get("mover") == "alpha-build", (code(r), meta(5)))

    # ---- 6. an item that asks no member takes anyone's comment
    r = post(6, BEA, act="comment", text="looks right")
    check("a comment on an item on an agent is a comment, as ever", code(r) == "comment" and last(6).get("by") == "member-b" and meta(6).get("mover") == "alpha-build", (code(r), meta(6)))

    # ---- 7. a hand-off to a member and another member's comment
    check("setup: the hand-offs to a member are open", handoff_open(7) and handoff_open(8) and handoff_open(9), [meta(i).get("handoff") for i in (7, 8, 9)])
    post(7, ADA, act="comment", text="a word from member-a")
    check("the first member's comment on the board leaves a hand-off to the second member open", last(7)["text"] == "a word from member-a" and handoff_open(7), meta(7).get("handoff"))
    post(7, BEA, act="comment", text="a word from member-b")
    check("…and the comment of the member it was handed to ends it", not handoff_open(7), meta(7).get("handoff"))
    comment = lambda n: {"id": n, "ts": time.time(), "text": "from github", "url": f"https://example.test/{n}"}
    check("the first member's comment on GitHub leaves a hand-off to the second member open", ghev_svc._github_comment("a8", comment(1)) is True and last(8)["via"] == "github" and handoff_open(8), meta(8).get("handoff"))
    check("…and ends one to the first member", ghev_svc._github_comment("a9", comment(2)) is True and last(9)["via"] == "github" and not handoff_open(9), meta(9).get("handoff"))

    # ---- 7b. what asks whom, case by case (no store: the item's record alone)
    both_ = ("member-a", "member-b")
    asks = lambda m: [who for who in both_ if _mgates.may_answer(m, who)]
    on_step = lambda who, **m: {"state": "your-step", "step": f"{who}: sign IBIS", "next": f"{who}: sign IBIS", **m}
    cases = (("options alone beside a step are a question, the item's member's", on_step("member-b", mover="member-a", needs=["decision"], options=OPTS), ["member-a"]),
             ("an ask alone beside a step is a question, its member's", on_step("member-a", mover="member-a", needs=["decision"], ask=ASK_B), ["member-b"]),
             ("a decision need beside a step with neither is the step", on_step("member-b", mover="member-a", needs=["decision"]), ["member-b"]),
             ("with no decision need the step asks, whatever else is stored", on_step("member-b", mover="member-a", needs=[], ask=ASK, options=OPTS), ["member-b"]),
             ("a step two members have an open line on asks both", {**on_step("member-a", mover="member-a"), "next": "member-a: sign IBIS\nmember-b: file IBIS"}, ["member-a", "member-b"]),
             ("an item that asks neither is its stored mover's", {"needs": ["alpha-build"], "mover": "member-b"}, ["member-b"]),
             ("…else the member its next names", {"needs": ["alpha-build"], "next": "member-b: look"}, ["member-b"]),
             ("…else the first member's", {"needs": ["alpha-build"]}, ["member-a"]),
             ("a step line left on an item in no step asks nobody by itself", {"state": "parked", "step": "member-a: sign IBIS", "mover": "member-b"}, ["member-b"]))
    for name, m, want in cases:
        check(name, asks(m) == want, asks(m))

    # ---- 7c. a Done on a step: each reason it is refused, alone
    def beside(i, step_, next_, mover="member-a", **m):
        item(i, state="your-step", step=step_, next=next_, mover=mover, then="alpha-build", **m)

    q = dict(needs=["decision"], ask=ASK, options=OPTS)
    beside(11, "member-b: sign QUILL", "member-b: sign QUILL", **q)                                   # member-a's question on a step member-b alone has had
    beside(12, "member-a: sign HERON", "member-a: sign HERON\nmember-b: file HERON", **q)              # member-a's own question on a step both have had
    beside(13, "member-b: sign OWL", "member-b: sign OWL\nmember-a: file OWL", mover="member-b")       # a mail tick, which is the first member's, on the second member's step
    beside(14, "member-a: sign CRANE", "member-a: sign CRANE", **q)                                   # member-b has no part in it
    check("setup: one member alone has had the first and the last of these steps, two the others", [_steps.several_hold(meta(i)) for i in (11, 12, 13, 14)] == [False, True, True, False], [_steps.several_hold(meta(i)) for i in (11, 12, 13, 14)])
    told.clear()
    for i, email, what in ((11, BEA, "another member's question holds back the Done of the member whose step it is"), (12, ADA, "one's own question on a step two have had holds back the Done")):
        was = rd(i)
        r = post(i, email, act="done")
        check(f"{what}: nothing written, and the notice is the one that says why", code(r) == "askwaits" and rd(i) == was and not pending(i) and not said(i), (code(r), meta(i)))
    was = rd(14)
    r = post(14, BEA, act="done")
    check("a member with no part in the step is told there is no step for them, question or not", code(r) == "nostep" and rd(14) == was, (code(r), meta(14)))
    was = rd(13)
    out = answer_svc._answer("a13", "", "", "done", via="mail", mail={"step": "member-b: sign OWL", "since": was["state_updated"], "note": "A sent mail fits the step."})
    check("a mail tick on another member's step is dropped, though the first member has a line on it", out == "nostep" and rd(13) == was, (out, meta(13)))
    for path, words in (("/items/a11?sent=askwaits", i18n.EN["sent.askwaits"]), ("/?sent=askwaits", i18n.EN["sent.askwaits_home"])):
        text = html.unescape(get(path, BEA).text)
        check(f"{path} draws the notice", words in text, text[:1500])
    msgs = json.loads(html.unescape(re.search(r'data-msgs="([^"]*)"', frame(5, ADA)[1]).group(1)))
    check("the frame knows that notice too", msgs.get("askwaits") == ["warn", i18n.EN["sent.askwaits_home"]], msgs.get("askwaits"))
    snap = before(11)
    r = post(11, BEA, act="done", text="mine is signed")
    check("…and a note sent with that Done is kept as their comment", code(r) == "comment" and last(11)["kind"] == "comment" and last(11).get("by") == "member-b"
          and all(meta(11).get(k) == v for k, v in snap["metadata"].items()), (code(r), meta(11)))

    # ---- 7d. a question beside a step, asked of the other member
    def section(text, sid):
        i = text.index(f'<section id="{sid}">')
        j = text.find('<section id="', i + 10)
        return text[i:j if j > 0 else text.index("</main>")]

    def home_row(i, email):
        """(the list the item's row stands in on that member's Home, the row's who line as text, the row's markup)."""
        board_home._board_home_drop()
        text = get("/", email).text
        for sid in ("your-move", "agents-at-work", "queued-release", "waiting-list"):
            part = section(text, sid)
            m = re.search(rf'<li[^>]*\bid="task-a-{i}"', part)
            if not m:
                continue
            rest = part[m.end():]
            cut = rest.find('<li class="irow')
            markup = m.group(0) + (rest[:cut] if cut >= 0 else rest)
            line = re.search(r'<div class="ir-who">(.*?)</div>', markup, re.S)
            return sid, " ".join(html.unescape(re.sub(r"<[^>]+>", "", line.group(1) if line else "")).replace("\u2197", "").split()), markup
        return "", "", ""

    def settle(*ids_):
        for i in ids_:
            with _writes.ITEM_LOCK:
                _writes.save(f"a{i}", _svcstore._load(f"a{i}"))

    def held(i, mover="member-a", ask=ASK_B, nxt="", **m):
        item(i, **{"state": "your-step", "step": f"{mover}: sign IBIS{i}", "mover": mover, "next": nxt or f"{mover}: sign IBIS{i}", "needs": ["decision"], "options": OPTS, **({"ask": ask} if ask else {}), **m})

    held(31)                                                                                          # member-b's question beside member-a's step
    held(32, ask="", nxt="member-a: sign IBIS32\nmember-b: file IBIS32")                              # options with no ask, on a step both have
    held(33, mover="member-b", nxt="member-b: sign IBIS33\nmember-a: file IBIS33")                    # asked of the step's own member, the other has a line
    held(34, mover="member-b")                                                                        # …and the other has none
    question(35, ask=ASK_B, mover="member-a", then="alpha-build", next="member-a: gather the numbers")  # asked of the second member, no step
    held(36, needs=[])                                                                                # an ask still stored, no decision need
    settle(31, 32, 33, 34, 35, 36)
    try:
        _mgates.gate_members(meta(31))
        accepted = True
    except Exception as e:  # noqa: BLE001
        accepted = str(e)
    check("a write may leave a question for one member beside the other's step", accepted is True, accepted)

    where, line, mark = home_row(31, BEA)
    check("the member asked has the item in Your move with the question's cards, though another member moves it", where == "your-move" and 'name="choice"' in mark and 'value="answer"' in mark and "GIRAFFEWORD" in mark and 'value="done"' not in mark and "waiting on" not in line, (where, line, mark))
    where, line, mark = home_row(31, ADA)
    check("the step's owner sees it under Waiting, waiting on that member's pick, with nothing to press", where == "waiting-list" and line == "waiting on member-b's pick" and "<form" not in mark and "GIRAFFEWORD" in mark, (where, line, mark))
    check("the row's token and the pick are the asked member's alone", tokens(BEA, 31) == ["a31"] and tokens(ADA, 31) == [], (tokens(BEA, 31), tokens(ADA, 31)))
    a, b = form_of(31, BEA), form_of(31, ADA)
    check("…as on the item's page, where the owner of the step has a comment box", 'name="choice"' in a and 'name="choice"' not in b and 'value="done"' not in b and 'value="comment"' in b, (a[:500], b[:500]))
    check("…and in the answer frame", frame(31, BEA)[0] == "open" and frame(31, ADA)[0] == "closed", (frame(31, BEA)[0], frame(31, ADA)[0]))
    was = rd(31)
    r = post(31, ADA, act="done")
    check("a Done on that step waits for the pick", code(r) == "askwaits" and rd(31) == was, (code(r), meta(31)))
    r = post(31, BEA, choice="Ship it", act="answer")
    m = meta(31)
    check("the member asked picks: the question goes, the step stays", code(r) == "decision" and "ask" not in m and "options" not in m and m.get("state") == "your-step" and m.get("step") == "member-a: sign IBIS31", (code(r), m))
    where, line, mark = home_row(31, ADA)
    check("…and the step's owner has it back in Your move with Done", where == "your-move" and 'value="done"' in mark, (where, line, mark))
    where, line, mark = home_row(31, BEA)
    check("…while the other member sees whose move it is, as for any item", where == "waiting-list" and line == "member-a picks it up · on member-a's move", (where, line, mark))
    r = post(31, ADA, act="done")
    check("…and their Done is taken", code(r) == "done" and meta(31).get("state") != "your-step", (code(r), meta(31)))

    where, line, mark = home_row(32, ADA)
    check("options with no ask are the item's member's question: theirs in Your move, their part of the step with the cards and no Done", where == "your-move" and "sign IBIS32" in mark and "file IBIS32" not in mark and 'name="choice"' in mark and 'value="answer"' in mark and 'value="done"' not in mark, (where, line, mark))
    check("…with the row's token and the pick theirs alone", tokens(ADA, 32) == ["a32"] and tokens(BEA, 32) == [], (tokens(ADA, 32), tokens(BEA, 32)))
    where, line, mark = home_row(32, BEA)
    check("…and the other member with a line on the step keeps it on Your move, their own line and nothing to press", where == "your-move" and "file IBIS32" in mark and "<form" not in mark, (where, line, mark))
    b = form_of(32, BEA)
    check("…whose page offers a comment box, as the server takes it", 'value="done"' not in b and 'value="comment"' in b, b[:500])
    was = rd(32)
    r = post(32, BEA, act="done")
    check("…their Done writes nothing while the options stand", code(r) == "askwaits" and rd(32) == was, (code(r), meta(32)))
    r = post(32, ADA, act="done")
    check("…nor does a Done of the member asked, which would pass the question on with the step", code(r) == "askwaits" and rd(32) == was and _mgates.asked_member(meta(32)) == "member-a", (code(r), meta(32)))
    r = post(32, ADA, act="note", text="done")
    check("…and their note that says done is kept as a comment: the question is still theirs", code(r) == "comment" and only_a_comment(32, was, "done", "") and _mgates.asked_member(meta(32)) == "member-a" and not pending(32), (code(r), meta(32)))
    r = post(32, BEA, choice="Ship it", act="answer")
    check("…so the other member's pick is still not taken", code(r) == "notyours" and "options" in meta(32), (code(r), meta(32)))
    r = post(32, ADA, choice="Ship it", act="answer")
    m = meta(32)
    check("…and the member asked picks: the question goes, the step stays with them", code(r) == "decision" and "options" not in m and "decision" not in str(m.get("needs")) and m.get("state") == "your-step" and m.get("step") == "member-a: sign IBIS32", (code(r), m))
    r = post(32, ADA, act="done")
    check("…after which their Done passes the step on", code(r) == "done" and meta(32).get("mover") == "member-b" and meta(32).get("state") == "your-step", (code(r), meta(32)))

    question(46, ask="", mover="member-b", then="alpha-build", next="member-b: weigh IBIS46", draft="IBISDRAFT46")      # options with no ask and no step, asked of the second member
    held(47, ask="", nxt="member-a: sign IBIS47\nmember-b: file IBIS47", draft="IBISDRAFT47")                          # …and beside a step both have, with a draft
    held(48, ask="", mover="member-b")                                                                                 # …and beside a step one member alone has
    settle(46, 47, 48)
    where, line, mark = home_row(46, BEA)
    check("options with no ask and no step: the member asked has the cards under their next step, the draft once", where == "your-move" and "weigh IBIS46" in mark and 'name="choice"' in mark and 'value="answer"' in mark and mark.count("IBISDRAFT46") == 1, (where, line, mark))
    where, line, mark = home_row(46, ADA)
    check("…and the other member nothing to press", where == "waiting-list" and "<form" not in mark, (where, line, mark))
    where, line, mark = home_row(47, ADA)
    check("…beside a step, the draft stands once, in the asked member's step", where == "your-move" and 'name="choice"' in mark and mark.count("IBISDRAFT47") == 1, (where, line, mark))
    where, line, mark = home_row(48, BEA)
    check("…also on a step one member alone has: the cards, no step form", where == "your-move" and "sign IBIS48" in mark and 'name="choice"' in mark and 'value="done"' not in mark, (where, line, mark))
    r = post(48, BEA, act="done")
    check("…whose Done, from a page drawn before, ends the item's step as before: it passes to no other member", code(r) == "done" and meta(48).get("state") != "your-step", (code(r), meta(48)))
    held(50, ask="", mover="member-b", options="not a list of options")
    settle(50)
    where, line, mark = home_row(50, BEA)
    check("stored options that break the shape draw no cards, and leave the step its buttons", where == "your-move" and 'value="done"' in mark and 'name="choice"' not in mark, (where, line, mark))

    item(49, state="your-step", step="member-a: sign IBIS49", mover="member-a", then="alpha-build", next="member-a: sign IBIS49\nmember-b: file IBIS49\nmember-b: send IBIS49")
    settle(49)
    waiting = lambda: _web_answers._answers_load().get("a49") or {}
    post(49, BEA, act="note", text="first part word")
    check("another member's part waits for a session like any answer when none waits yet", waiting().get("by") == "member-b" and "first part word" in str(waiting().get("words")), waiting())
    post(49, BEA, act="note", text="second part word")
    check("…and their next one takes its place", waiting().get("by") == "member-b" and "second part word" in str(waiting().get("words")), waiting())
    post(49, ADA, act="note", text="which pen word")
    check("…as the answer of the member asked does", waiting().get("by") == "member-a" and "which pen word" in str(waiting().get("words")), waiting())
    held_back = waiting()
    r = post(49, BEA, act="done", text="filed word")
    check("another member's Done takes the place of no answer that still waits", code(r) == "partdone" and waiting() == held_back, (code(r), waiting()))

    where, line, mark = home_row(33, ADA)
    check("a member with a line on a step whose member is asked keeps that line on Your move, nothing to press", where == "your-move" and "file IBIS33" in mark and "<form" not in mark, (where, line, mark))
    where, line, mark = home_row(33, BEA)
    check("…which is in that member's Your move", where == "your-move" and 'name="choice"' in mark, (where, line, mark))
    where, line, mark = home_row(34, ADA)
    check("a member with no part reads whose move it is", where == "waiting-list" and line == "member-b picks it up · on member-b's move", (where, line, mark))
    where, line, mark = home_row(35, BEA)
    check("a question with no step, asked of a member who does not move the item, is in their Your move with the cards", where == "your-move" and 'name="choice"' in mark, (where, line, mark))
    where, line, mark = home_row(35, ADA)
    check("…and stays on the mover's Your move, their own next line and no cards", where == "your-move" and "gather the numbers" in mark and 'name="choice"' not in mark, (where, line, mark))
    where, line, mark = home_row(36, ADA)
    check("an ask left with no decision need holds nothing: the step is its owner's", where == "your-move" and 'value="done"' in mark, (where, line, mark))
    where, line, mark = home_row(36, BEA)
    check("…and asks nobody else", where == "waiting-list" and line == "member-a picks it up · on member-a's move", (where, line, mark))
    r = post(36, ADA, act="done")
    check("…and the Done is taken", code(r) == "done" and meta(36).get("state") != "your-step", (code(r), meta(36)))

    question(38, options=None, ask=ASK_B, mover="member-a", then="alpha-build", next="member-a: gather the totals")      # a question to write an answer to: no options
    settle(38)
    where, line, mark = home_row(38, BEA)
    check("a question with no options is a question: in the asked member's Your move", where == "your-move" and "<form" in mark, (where, line, mark))
    beside_q = {"state": "your-step", "step": "member-a: sign IBIS31", "mover": "member-a", "needs": ["decision"], "ask": ASK_B}
    check("the step is held for the member asked, and waits for the step's member alone", _mgates.held_for(beside_q) == "member-b" and [_mgates.step_waits(beside_q, w) for w in ("member-a", "member-b")] == [True, False],
          (_mgates.held_for(beside_q), [_mgates.step_waits(beside_q, w) for w in ("member-a", "member-b")]))
    own = {**beside_q, "step": "member-b: sign IBIS31", "mover": "member-b"}
    check("…never for the member asked, whose own step stands beside their question", not _mgates.step_waits(own, "member-b"))
    bare = {"state": "your-step", "step": "member-a: sign IBIS31", "mover": "member-a", "needs": ["decision"], "next": "member-a: sign IBIS31\nmember-b: file IBIS31"}
    check("a decision need with neither ask nor options is no question: nobody's pick is waited for, and the step's members answer the step", _mgates.pick_of(bare) == "" and _mgates.held_for(bare) == "" and _mgates.may_answer(bare, "member-b") and _mgates.may_answer(bare, "member-a"), (_mgates.pick_of(bare), _mgates.may_answer(bare, "member-b")))
    check("…and with an option stored, or an ask, the question is the asked member's alone", _mgates.pick_of({**bare, "options": OPTS}) == "member-a" and not _mgates.may_answer({**bare, "ask": ASK}, "member-b"), (_mgates.pick_of({**bare, "options": OPTS}),))
    stale = {**beside_q, "state": "your-call"}
    check("an item that is no step holds none, whatever step text it still stores", _mgates.held_for(stale) == "" and not _mgates.step_waits(stale, "member-a") and _mgates.pick_of(stale) == "member-b", (_mgates.held_for(stale), _mgates.pick_of(stale)))

    # ---- the line `client.py get answer` prints, read by the parked-question reader of the fleet's supervisor (contrib/question-board.py answer), when a checkout of it is at hand
    SALA = pathlib.Path(os.environ.get("SALAMANDER_DIR") or os.path.expanduser("~/salamander"))
    READER = SALA / "contrib/question-board.py"
    SALA_STATE = T / "sala-state"
    PERM = [{"label": "Yes", "line": "Allow this exact call.", "recommended": False}, {"label": "No", "line": "Deny it.", "recommended": True}]
    QCALLS = {"one": {"tool": "AskUserQuestion", "tool_input": {"questions": [{"question": "Which?", "header": "Pick", "multiSelect": False, "options": [{"label": "Ship it", "description": "a"}, {"label": "Hold it", "description": "b"}]}]}},
              "two": {"tool": "AskUserQuestion", "tool_input": {"questions": [{"question": "Which plan?", "header": "Plan", "multiSelect": False, "options": [{"label": "Plan A", "description": "a"}, {"label": "Plan B", "description": "b"}]},
                                                                                {"question": "Which colour?", "header": "Colour", "multiSelect": False, "options": [{"label": "Red", "description": "a"}, {"label": "Blue", "description": "b"}]}]}},
              "perm": {"tool": "Bash", "tool_input": {"command": "ls"}}}
    for qid, call in QCALLS.items():
        (SALA_STATE / "questions" / qid).mkdir(parents=True, exist_ok=True)
        (SALA_STATE / "questions" / qid / "record.json").write_text(json.dumps({"qid": qid, **call, "state": "parked", "item": "", "filed": ""}))
    FAKE = T / "fake-client"
    FAKE.write_text('#!/bin/sh\ncat "$0.line"\n'); FAKE.chmod(0o755)

    def reader_takes(qid, line):
        """The words question-board.py answer hands to the parked call for this line (None when it refuses): the client it runs prints the line."""
        pathlib.Path(f"{FAKE}.line").write_text(line + "\n")
        env = {**os.environ, "SALA_STACKSHOT_CLIENT": str(FAKE), "SALA_STATE_DIR": str(SALA_STATE), "SALA_QUESTION_ID": qid, "SALA_QUESTION_ITEM": "item-1"}
        r = subprocess.run([sys.executable, "-I", "-S", str(READER), "answer"], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        return r.stdout.strip() if r.returncode == 0 else None

    def table(tag, base, email, mover):
        """The rows a parked question is answered by, each through the item's answer route as the member asked: the line a script gets is a decision whose label and words are the member's own, and the reader takes it."""
        rows = [("a picked option", "one", OPTS[:2], dict(choice="Hold it"), "Hold it"),
                ("a picked option with a note", "one", OPTS[:2], dict(choice="Hold it", text="go slow"), "Hold it"),
                ("a picked Yes on a permission question", "perm", PERM, dict(choice="Yes"), "Yes"),
                ("a typed option label", "one", None, dict(text="Hold it"), "Hold it"),
                ("a typed number", "one", None, dict(text="2"), "2"),
                ("typed answers to a two-question call", "two", None, dict(text="1: Plan B\n2: Blue"), "1: Plan B\n2: Blue"),
                ("a typed yes", "perm", None, dict(text="yes"), "yes")]
        for n, (what, qid, opts, data, want) in enumerate(rows):
            i = base + n
            question(i, ask="Decide: Which? · Recommend: none · Stakes: low · By: Fri", options=opts, mover=mover, then="alpha-build")
            r = post(i, email, act="answer", **data)
            line = handover_svc._answer_line(rd(i)); f = line.split("\t")
            check(f"{tag}: {what} is a decision, the label and the words are the member's own", code(r) == "decision" and f[0] == "decision" and f[1] == data.get("choice", "") and f[2] == data.get("text", "").replace("\n", " / "), (code(r), line))
            if READER.is_file():
                got = reader_takes(qid, line)
                check(f"{tag}: the parked-question reader takes {what}", got is not None and want in got, (line, got))

    # ---- 7e. the answer line a script reads
    kind = lambda m: handover_svc._answer_line({"metadata": m}).split("\t")[0]
    text_of = lambda i: handover_svc._answer_line(rd(i)).split("\t")[2]
    item(37, state="your-step", step="member-a: sign IBIS37", mover="member-a", then="alpha-build", next="member-a: sign IBIS37\nmember-b: file IBIS37")
    settle(37)
    r = post(37, BEA, act="done")
    check("another member's Done on a shared step is no decision to a script", code(r) == "partdone" and kind(meta(37)) == "comment" and text_of(37).startswith("member-b, on the step"), (code(r), handover_svc._answer_line(rd(37))))
    r = post(37, ADA, act="done")
    check("…the Done of the member the step is asked of is", code(r) == "done" and kind(meta(37)) == "decision", (code(r), handover_svc._answer_line(rd(37))))
    rec = lambda by, ts, **k: {"ts": ts, "kind": "decision", "choice": "Ship it", "via": "board", **({"by": by} if by else {}), **k}
    mine, theirs = rec("", 100.0, ask=ASK), rec("member-b", 200.0, ask="Decide: member-a: pick · Recommend: yes · Stakes: low · By: Fri")
    check("a decision on a question that names another member is no decision", kind({"answers": [theirs]}) == "comment", handover_svc._answer_line({"metadata": {"answers": [theirs]}}))
    got = handover_svc._answer_line({"metadata": {"answers": [mine, theirs]}})
    check("…and does not take the place of the one that is", got.startswith("decision\t") and "member-b" not in got, got)
    check("the named member's own decision counts, and one on a question that names nobody", kind({"answers": [rec("member-b", 1.0, ask=ASK_B)]}) == "decision" and kind({"answers": [rec("member-b", 1.0, ask=ASK)]}) == "decision")
    check("…so does a first member's, written under no name, on a question that names them", kind({"answers": [rec("", 1.0, ask="Decide: member-a: pick · Recommend: yes · Stakes: low · By: Fri")]}) == "decision")

    # ---- 7e2. whom a question names is read one way, by the member asked and by the record of the answer
    for n, (what, ask_text, mover) in enumerate((("`<name> to …`", "Decide: member-b to own the vendor call? · Recommend: Ship it · Stakes: low · By: Fri", "member-a"),
                                                 ("an alias", "Decide: MB to own the vendor call? · Recommend: Ship it · Stakes: low · By: Fri", "member-a"),
                                                 ("`you:`, which names nobody", "Decide: you: pick it · Recommend: Ship it · Stakes: low · By: Fri", "member-b"),
                                                 ("a name before a colon", "Decide: member-b: pick it · Recommend: Ship it · Stakes: low · By: Fri", "member-a"))):
        i = 60 + n
        question(i, ask=ask_text, options=OPTS[:2], mover=mover, then="alpha-build")
        m_ = meta(i); m_["answers"] = [{"ts": now - 500, "kind": "decision", "choice": "Hold it", "via": "board", "by": "member-a", "ask": "Decide: older · Recommend: Hold it · Stakes: low · By: Mon"}]
        (T / f"store/a/{i}.json").write_text(json.dumps({**rd(i), "metadata": m_}))
        r = post(i, ADA, choice="Ship it", act="answer")
        check(f"{what}: the member not asked is refused", code(r) == "notyours", code(r))
        r = post(i, BEA, choice="Ship it", act="answer")
        line = handover_svc._answer_line(rd(i))
        check(f"{what}: the member asked answers it, and the line is that decision, not the earlier one", code(r) == "decision" and line.split("\t")[:3] == ["decision", "Ship it", ""], (code(r), line))
        r = post(i, BEA, choice="Ship it", act="answer")
        check(f"{what}: the question is answered once", code(r) == "stale", code(r))
    # the home row of the member asked draws the answer form for either opener, with no stored options
    for n, (what, ask_text) in enumerate((("`<name>:`", "Decide: member-b: own the vendor call? · Recommend: Ship it · Stakes: low · By: Fri"),
                                          ("`<name> to …`", "Decide: member-b to own the vendor call? · Recommend: Ship it · Stakes: low · By: Fri"),
                                          ("an alias", "Decide: MB to own the vendor call? · Recommend: Ship it · Stakes: low · By: Fri"))):
        i = 80 + n
        question(i, ask=ask_text, options=None, mover="member-a", then="alpha-build", next="member-a: gather the numbers")
        settle(i)
        where, line, mark = home_row(i, BEA)
        check(f"{what}, no stored options: the member asked has it in Your move with the answer form", where == "your-move" and 'name="choice"' in mark and 'name="text"' in mark and "hanswer" in mark, (where, line, mark))
        where, line, mark = home_row(i, ADA)
        check(f"{what}, no stored options: the mover has no answer form for it", 'name="choice"' not in mark and "hanswer" not in mark, (where, line, mark))
    check("one rule names the member a Decide part asks", [getattr(_mgates.named_in(d), "name", None) for d in ("member-b to own it?", "MB: pick", "you: pick", "whether member-b owns it", "Member-B: pick")] == ["member-b", "member-b", None, None, "member-b"])
    table("two members", 100, BEA, "member-b")

    # ---- 7e3. an answer already waiting at deploy time, stored with no `by`, is no sender's: another member's Done on a shared step leaves its words
    for i, by in ((70, None), (71, "member-b")):
        item(i, state="your-step", step=f"member-a: sign IBIS{i}", mover="member-a", then="alpha-build", next=f"member-a: sign IBIS{i}\nmember-b: file IBIS{i}")
        settle(i)
        st = _web_answers._answers_load()
        st[f"a{i}"] = {"ts": now - 10, "owner": "", "project": "projects/alpha", "told": [], "words": "OLDWORDS", **({"by": by} if by else {})}
        _web_answers._answers_save(st)
        r = post(i, BEA, act="done", text="mine is filed")
        words = _web_answers._answers_load().get(f"a{i}", {}).get("words", "")
        check(f"a waiting answer stored {'with no `by`' if not by else 'by the sender'}: another member's Done {'leaves its words' if not by else 'replaces them with the sender'}", code(r) == "partdone" and (words == "OLDWORDS") == (by is None), (code(r), words))

    # ---- 7f. the lines the sessions get, beside a member's name
    def heard(i): return " | ".join(said(i))
    item(41, state="your-step", step="member-b: sign IBIS41", mover="member-b", then="alpha-build", next="member-b: sign IBIS41")
    item(42, state="your-step", step="member-b: sign IBIS42", mover="member-b", then="alpha-build", next="member-b: sign IBIS42")
    item(43, state="your-step", step="member-a: send IBIS43", mover="member-a", then="alpha-build", next="member-a: send IBIS43")
    item(44, state="your-step", step="member-b: sign IBIS44", mover="member-b", then="alpha-build", next="member-b: sign IBIS44")
    item(45, needs=["alpha-build"], mover="alpha-build", next="alpha-build: build it", **{_askl.LEFT: {"ask": ASK_B}})
    settle(41, 42, 43, 44, 45)
    told.clear()
    post(41, BEA, act="done", text="signed")
    check("a Done: their step, with their note", "member-b did their step" in heard(41) and "with their note" in heard(41) and " his " not in heard(41), heard(41))
    post(42, BEA, act="note", text="which pen should it be?")
    check("a note: their step and note, and what they will do", all(w in heard(42) for w in ("sent a note on their step", "with their note", "if it says they will do the step", "leave their step open")) and " his " not in heard(42), heard(42))
    answer_svc._answer("a43", "", "", "done", via="mail", mail={"step": "member-a: send IBIS43", "since": rd(43)["state_updated"], "note": "A sent mail fits the step."})
    check("a mail tick: their step", "fits their step" in heard(43), heard(43))
    post(44, BEA, act="note", text="done")
    check("a note read as done: their step was ticked", "ticked their step" in heard(44) + str(last(44).get("applied")), (heard(44), last(44)))
    post(45, BEA, choice="Ship it", act="answer")
    check("a late pick: the ask taken off their move", "took off their move" in str(last(45).get("text")), last(45))

    # ---- 7g. an item that cannot be read gives no token
    (T / "store/a/39.json").write_text("{")
    try:
        check("an item that cannot be read gives no member its row's token", tokens(ADA, 39) == [] and tokens(BEA, 39) == [], (tokens(ADA, 39), tokens(BEA, 39)))
    finally:
        (T / "store/a/39.json").unlink()

    # ---- 8. one member: nothing here applies
    _cfg.CFG["members"] = ONE
    board_home._board_home_drop()
    check("a board of one member is not one of several", not _mgates.many())
    check("one member: no item waits for a member's pick, and no step is held", _mgates.pick_of(beside_q) == "" and _mgates.held_for(beside_q) == "" and not _mgates.step_waits(beside_q, "member-a"), (_mgates.pick_of(beside_q), _mgates.held_for(beside_q)))
    question(21, ask=ASK_B, mover="member-a", then="alpha-build")          # the ask names somebody who is no member of this board
    question(22, next="Acme: send the quote", then="alpha-build")
    step(23)
    question(24, mover="member-a", then="alpha-build", handoff=handed("member-a"), next="member-a: answer the ask above")
    question(25, mover="member-a", then="alpha-build", handoff=handed("member-a"), next="member-a: answer the ask above")
    question(26, ask=ASK_B, then="alpha-build")
    held(28, ask="")                                                       # options with no ask beside a step
    settle(28)
    where, line, mark = home_row(28, ADA)
    check("one member: options with no ask beside a step draw the step's buttons on Home, as before", where == "your-move" and 'value="done"' in mark and 'name="choice"' not in mark, (where, line, mark))
    check("one member: any item may be answered", all(_mgates.may_answer(meta(i), "member-a") and _mgates.may_answer(meta(i), "somebody-else") for i in (21, 22, 23)))
    for i in (21, 22):
        f = form_of(i, ADA)
        check(f"one member: item {i}'s page draws the answer cards, whatever it names", 'name="choice"' in f and 'value="answer"' in f, f[:600])
        s, text = frame(i, ADA)
        check(f"one member: item {i}'s answer frame is open", s == "open" and 'name="choice"' in text, (s, text[-1200:]))
    f = form_of(23, ADA)
    check("one member: the step has its Done and Send note", 'value="done"' in f and 'value="note"' in f, f[:600])
    check("one member: a token for every item asked about", tokens(ADA, 21, 22, 23, 24) == ["a21", "a22", "a23", "a24"], tokens(ADA, 21, 22, 23, 24))
    msgs = json.loads(html.unescape(re.search(r'data-msgs="([^"]*)"', frame(21, ADA)[1]).group(1)))
    check("one member: the frame's notices are the ones every board has", set(msgs) == set(ui_render.Board._SENT_KEYS), sorted(msgs))
    for path in ("/items/a21?sent=notyours", "/?sent=notyours", "/items/a21?sent=askwaits", "/?sent=askwaits"):
        text = html.unescape(get(path, ADA).text)
        check(f"one member: {path} draws no notice of a board of several members", not any(i18n.EN[k] in text for k in ("sent.notyours", "sent.notyours_home", "sent.askwaits", "sent.askwaits_home")), text[:1500])
    r = post(21, ADA, choice="Ship it", act="answer")
    check("one member: a pick is a decision, recorded under no name", code(r) == "decision" and "ask" not in meta(21) and "by" not in last(21) and pending(21), (code(r), meta(21)))
    out = answer_svc._answer("a26", "Ship it", "", "answer", by="somebody-else")
    check("one member: the answer path asks no name of its caller, as before", out == "decision" and "ask" not in meta(26), (out, meta(26)))
    told.clear()
    r = post(23, ADA, act="done")
    check("one member: a Done ends the step", code(r) == "done" and meta(23).get("mover") == "alpha-build", (code(r), meta(23)))
    check("one member: the lines the sessions get read as before", "did his step" in " | ".join(said(23)), said(23))
    held(27, ask=ASK, mover="member-a")
    settle(27)
    where, line, mark = home_row(27, ADA)
    check("one member: a question beside a step is on Your move with its cards, as before", where == "your-move" and 'name="choice"' in mark and "waiting on" not in line, (where, line, mark))
    r = post(27, ADA, act="done")
    check("one member: a Done beside the question is taken, as before", code(r) == "done", (code(r), meta(27)))
    old = {"answers": [rec("somebody-else", 1.0, ask="Decide: member-b: pick · Recommend: yes · Stakes: low · By: Fri", asked="member-b")]}
    check("one member: every decision is a decision to a script", kind(old) == "decision", handover_svc._answer_line({"metadata": old}))
    post(24, ADA, act="comment", text="noted")
    check("one member: a comment on the board ends the hand-off", not handoff_open(24), meta(24).get("handoff"))
    ghev_svc._github_comment("a25", comment(3))
    check("one member: a comment on GitHub ends the hand-off", not handoff_open(25), meta(25).get("handoff"))
    table("one member", 120, ADA, "member-a")

print(("ok" if not fails else "FAILED") + f": answer other person scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
