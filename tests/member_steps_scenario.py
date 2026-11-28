"""Scenario test for a your-step more than one member has a part in (model/steps.py, ui/render.py, home.py, service/answer.py, service/answer_handover.py) — made-up data, a temp folder, the routes
through Starlette's test client, no live store, no network.

A board of two members (member-a, member-b), items whose checklist holds an open step of each. Covers:

  * each member's Home and item page draw that member's steps alone (with the lines that name no one), their commands, draft and form; Your move holds the item for every member with an open step
    on it, and for its mover; the server's own line is left out among the viewer's lines only;
  * Done and Send note by the member the step is asked of and by another member: what is ticked (never another member's line), who the mover becomes, that the other's step stays open and
    answerable, the notices, the answer code and its page notice, the line each session is told;
  * a member with no part in the step (on a step one member alone has had, and on one two have had), a question standing on the item, and a mail tick;
  * a bare sub-line a later write added reads as the member's whose line stands above it in next, not in the checklist;
  * a bare line's member is settled when it is written and stays with it whatever later happens to other lines (marked, dropped, reworded, moved, merged, the step reworded, a note, a mail tick), through
    the update tool and the answers; nothing is stored for a board of one member or an item one member alone has had a part in;
  * a project page, drawn for no member: no step and no form for an item two members have had a part in, the item page linked;
  * the line `client.py get answer` prints after one member's answer to a step the item stayed on, and that a later step does not change it;
  * one member: the notice only a board of several members answers with stays out of the home page and the item page, the project page keeps its step form and the answer line is as it was.

    tests/run-suite member_steps  → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="member-steps-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
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
OWNER_S = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER_S: {"name": "alpha-build", "machine": "a", "seen": now}, AGENT: {"name": "alpha-main", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "agents": {"alpha-build": "builds it"}, "back_agents": {"alpha-build": "builds it"}, "status": "active", "board": [], "board_open": 0}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
OPTS = [{"label": "Ship it", "line": "Ship on Friday.", "recommended": True}, {"label": "Hold it", "line": "Wait a week.", "recommended": False}]
ASK = "Decide: ship on Friday · Recommend: yes · Stakes: low · By: Fri"
A_STEP = "sign the ALPHASEVEN form"
B_LINE = "member-b: countersign BRAVOSEVEN with `fleet countersign box-a --now`"
NEXT = f"member-a: {A_STEP}\n{B_LINE}\n  - take the SUBSEVEN card"


def item(i, subject="", status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[work] {subject or f'item a{i}'}", "description": "- A fixture item.", "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER_S, "project": "projects/alpha", **meta}}))


def pair(i, **meta):
    """A your-step asked of member-a with an open step of each member on the checklist; the server's own line is member-a's."""
    item(i, **{"state": "your-step", "step": A_STEP, "mover": "member-a", "then": "alpha-build", "owner_step": f"member-a: {A_STEP}", "next": NEXT, "draft": "ALPHADRAFT to paste.", **meta})


pair(1)                                                                              # drawn per member
pair(2, watch_reason="an old watch")                                                 # Done by member-a, then by member-b
pair(3)                                                                              # Done by member-b first
pair(4)                                                                              # a note of member-a's that does not say done
pair(5)                                                                              # a note of member-a's that says done
pair(6)                                                                              # a note of member-b's that does not say done
pair(7)                                                                              # a note of member-b's that says done
item(8, state="your-step", step=A_STEP, mover="member-a", then="alpha-build", next=f"member-a: {A_STEP}")      # member-b has no part
pair(9, needs=["decision"], ask=ASK, options=OPTS, draft="ALPHADRAFT to paste.")       # a question of member-a's stands beside the step
item(10, state="your-step", step="send the BRAVOTEN mail", mover="member-b", then="alpha-build", next=f"member-b: send the BRAVOTEN mail\nmember-a: file ELEVENA")      # a mail tick on a step asked of member-b
pair(11)                                                                             # a mail tick on member-a's step
item(12, state="your-step", step="sign the form on paper", mover="member-a", then="alpha-build", next="member-b: countersign BRAVOSEVEN")      # member-a has no line of their own
pair(13, project="projects/ghost", then="", needs=[])                                # no session stands to take it, and member-b's step is still open
item(15, state="your-step", step="sign the TWIN form", mover="member-a", then="alpha-build", owner_step="member-a: sign the TWIN form",
     next="member-a: sign the TWIN form\nmember-b: sign the TWIN form")              # both members' lines say the same words
item(16, state="your-step", step="Run `fleet sign ALPHACMD --now` and say done", mover="member-a", then="alpha-build",
     next="member-a: sign the form\nmember-b: countersign BRAVOSIXTEEN")               # the step field's command is member-a's
item(17, state="your-step", step="member-a: sign SEVENTEEN", mover="member-b", then="alpha-build", next="alpha-build: prepare the papers")      # member-b moves it, the step names member-a
item(18, state="your-step", step="sign EIGHTEEN", mover="member-a", then="alpha-build", next="alpha-build: prepare FIRSTAGENT\nmember-a: sign EIGHTEEN")
item(19, state="your-step", step="read the page", mover="member-a", then="alpha-build", next="alpha-build: prepare AGENTNINETEEN\ncheck PLAINNINETEEN")      # no line names a member
item(20, state="your-step", step="sign TWENTYFIELD", mover="member-a", then="alpha-build", next="alpha-build: prepare AGENTTWENTY")      # only the step field says what member-a does
item(23, state="your-step", step="sign the form on paper", mover="member-a", then="alpha-build", next="member-b: countersign BRAVOSEVEN")      # member-a's part is the step field alone
item(24, state="your-step", step="sign the form on paper", mover="member-a", then="alpha-build", steps=[{"text": "member-b: countersign BRAVOSEVEN", "status": "done", "by": "member-b", "at": now - 60}])      # a ticked line of member-b's, and no line of member-a's
pair(21, next=f"{NEXT}\ncheck SHAREDLINE")                                            # a line that names no one stands beside both members' lines
pair(22, next=f"{NEXT}\n- file the BAREBRAVO slip")                                # a bullet that names no one, under member-b's line, is member-b's

def stored(*lines): return [{"text": t, "status": "open", "by": "", "at": 0} for t in lines]


# a later write added the bare sub-line: the checklist holds it last, next holds it under member-a's line
item(30, state="your-step", step="sign THIRTYA", mover="member-a", then="alpha-build", steps=stored("member-a: sign THIRTYA", "member-b: countersign THIRTYB"),
     next="member-a: sign THIRTYA\n- file SUBTHIRTY\nmember-b: countersign THIRTYB")
item(31, state="your-step", step="sign THIRTYONEA", mover="member-a", then="alpha-build", steps=stored("member-a: sign THIRTYONEA", "member-b: countersign THIRTYONEB", "alpha-build: write AGENTLAST"),
     next="member-a: sign THIRTYONEA\n- file SUBTHIRTYONE\nmember-b: countersign THIRTYONEB\nalpha-build: write AGENTLAST")
item(32, state="your-step", step=A_STEP, mover="member-a", then="alpha-build", next=f"member-a: {A_STEP}", needs=["decision"], ask=ASK, options=OPTS)      # a question beside a step one member alone has had
pair(33, needs=["decision"], ask=ASK, options=OPTS)                                   # a question added to a two-member step after its page was drawn
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


from stackshot.web import server
from stackshot.core import config as _cfg
from stackshot.model import states as _states
from stackshot.model import steps as _steps
from stackshot.service import answer as answer_svc
from stackshot.service import answer_handover
from stackshot.service import telling
from stackshot.web import answers as _web_answers
from stackshot.web import board_home
from stackshot.web import publish as _web_publish
from stackshot.web.ui import render as ui_render
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route, update as _wt_update
from stackshot.web.auth import signin as _signin

_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
told = []      # (item, the line, how it was sent)
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, note, "woken"))
telling.tell_kind = lambda kind, gid, owner, note, tag="wake": told.append((gid, note, "turn"))
telling.tell_own_move = lambda gid, owner, note, **k: told.append((gid, note, "own-move"))
telling.gate_result = lambda: ("", "")
telling.tell_comment = lambda *a, **k: []
TWO = [{"name": "member-a", "emails": [ADA]}, {"name": "member-b", "aliases": ["MB"], "emails": [BEA]}]
_cfg.CFG["members"] = TWO

from starlette.testclient import TestClient

COOKIE = {e: _signin._ui_sign(json.dumps({"email": e, "exp": time.time() + 3600})) for e in (ADA, BEA)}


def section(page, sid):
    i = page.index(f'<section id="{sid}">')
    j = page.find('<section id="', i + 10)
    return page[i:j if j > 0 else page.index("</main>")]


def ids(page, sid):
    return [int(x) for x in re.findall(r'<li[^>]*\bid="task-a-(\d+)"', section(page, sid))]


def row(page, i):
    m = re.search(rf'<li[^>]*\bid="task-a-{i}"', page)
    if not m:
        return ""
    rest = page[m.end():]
    ends = [x for x in (rest.find('<li class="irow'), rest.find('<section id="'), rest.find("</main>")) if x >= 0]
    return m.group(0) + rest[:min(ends)]


def block(page):
    """The Your step block of an item page: from its box to the form under it; "" when the page draws none."""
    i = page.find('<div class="iask istep">')
    if i < 0:
        return ""
    j = page.find("<form", i)
    return page[i:j if j > 0 else i + 3000]


def meta(i): return rd(i)["metadata"]
def answer_line(i): return answer_handover._answer_line(rd(i)).split("\t")
def lines(i, status): return [_steps.first_line(x["text"]) for x in _steps.view(meta(i)) if x["status"] == status]
def done(i): return [(_steps.first_line(x["text"]), x["by"]) for x in _steps.view(meta(i)) if x["status"] == _steps.DONE]
def said(i): return [(text, how) for gid, text, how in told if gid == f"a{i}"]
def pending(i): return f"a{i}" in _web_answers._answers_load()
def code(r): return re.search(r"[?&]sent=([a-z]+)", r.headers.get("location", "")).group(1) if "sent=" in r.headers.get("location", "") else f"{r.status_code} {r.text[:200]}"


def mail(i):
    it = rd(i)
    out = answer_svc._answer(f"a{i}", "", "", "done", via="mail", mail={"step": _states.clean(it["metadata"].get("step")), "since": it["state_updated"], "note": "a mail went out"})
    board_home._board_home_drop()
    return out


with TestClient(server.mcp.http_app(), base_url=BOARD, raise_server_exceptions=False) as c:      # a server error is a status the check below names, not the end of the run
    def get(path, person):
        c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE[person])
        return c.get(path, follow_redirects=False).text

    def post(i, person, **data):
        c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE[person])
        return c.post(f"/items/a{i}/answer", data={"token": _web_answers._answer_token(person, f"a{i}"), **data}, headers={"Origin": BOARD}, follow_redirects=False)

    home = lambda person: get("/", person)
    page = lambda i, person: get(f"/items/a{i}", person)

    # ---- 1. what each member is shown
    A, B = home(ADA), home(BEA)
    check("Your move holds a two-member step for the mover and for the other member with an open step", 1 in ids(A, "your-move") and 1 in ids(B, "your-move") and 1 not in ids(B, "waiting-list"),
          (ids(A, "your-move"), ids(B, "your-move")))
    ra, rb = row(A, 1), row(B, 1)
    check("A's row draws member-a's step, its draft and Done, and none of member-b's", "ALPHASEVEN" in ra and "ALPHADRAFT" in ra and 'value="done"' in ra and "BRAVOSEVEN" not in ra and "fleet countersign" not in ra and "SUBSEVEN" not in ra, ra)
    check("B's row draws member-b's step with its command, its sub-line and Done, and none of member-a's", "BRAVOSEVEN" in rb and "fleet countersign box-a --now" in rb and "SUBSEVEN" in rb and 'value="done"' in rb and "ALPHASEVEN" not in rb, rb)
    check("…and not member-a's draft", "ALPHADRAFT" not in rb, rb)
    pa, pb = block(page(1, ADA)), block(page(1, BEA))
    check("A's item page: the Your step block is member-a's step and draft", "ALPHASEVEN" in pa and "ALPHADRAFT" in pa and "BRAVOSEVEN" not in pa and "fleet countersign" not in pa, pa)
    check("B's item page: the Your step block is member-b's step", "BRAVOSEVEN" in pb and "fleet countersign box-a --now" in pb and "SUBSEVEN" in pb and "ALPHASEVEN" not in pb and "ALPHADRAFT" not in pb, pb)
    check("the server's own line is skipped among the viewer's lines only: member-b sees their line though it says the same words", "TWIN" in block(page(15, BEA)) and "TWIN" in row(B, 15) and 'value="done"' in row(B, 15), (block(page(15, BEA)), row(B, 15)))
    check("the step field's command is the member's the step is asked of", "ALPHACMD" in block(page(16, ADA)) and "ALPHACMD" not in block(page(16, BEA)) and "BRAVOSIXTEEN" in block(page(16, BEA)) and "ALPHACMD" not in row(B, 16), (block(page(16, BEA)), row(B, 16)))
    p8 = page(8, BEA)
    check("a member with no part in the step: not their move, no step block, a box to write in", 8 in ids(B, "waiting-list") and 8 not in ids(B, "your-move") and not block(p8) and 'value="done"' not in p8
          and "<textarea" in p8 and 'value="done"' in block(page(8, ADA)) + page(8, ADA), (ids(B, "your-move"), block(p8)))
    check("a mover with no part in a step that names another member: the item is theirs to move, with no Done on it", 17 in ids(B, "your-move") and 'value="done"' not in row(B, 17) and not block(page(17, BEA)), row(B, 17))
    check("member-a's question: member-b's row asks nothing and offers no Done, and shows member-b's own next line", 9 in ids(B, "your-move") and "<form" not in row(B, 9) and "ship on Friday" not in row(B, 9) and "BRAVOSEVEN" in row(B, 9), row(B, 9))
    check("…nor member-a's draft", "ALPHADRAFT" not in row(B, 9), row(B, 9))
    check("…member-a has the question's form, and their own next line's item", "<form" in row(A, 9) and "ship on Friday" in row(A, 9), row(A, 9))
    check("…the item page draws no step block while the question stands", not block(page(9, BEA)) and not block(page(9, ADA)))
    check("…and shows the draft of member-a's step to member-a alone", "ALPHADRAFT" not in page(9, BEA) and "ALPHADRAFT" in page(9, ADA))
    check("another member's row reads the next line of its mover, not the checklist's first", 18 in ids(B, "waiting-list") and "sign EIGHTEEN" in row(B, 18) and "FIRSTAGENT" not in row(B, 18), row(B, 18))
    check("…and a line that names no one when the mover has none", "PLAINNINETEEN" in row(B, 19) and "AGENTNINETEEN" not in row(B, 19), row(B, 19))
    check("…and the mover's step when no line is theirs or no one's, never a session's line", "sign TWENTYFIELD" in row(B, 20) and "AGENTTWENTY" not in row(B, 20), row(B, 20))

    check("a line that names no one is drawn for both members, beside their own alone",
          "SHAREDLINE" in block(page(21, ADA)) and "SHAREDLINE" in block(page(21, BEA)) and "BRAVOSEVEN" not in block(page(21, ADA)) and "ALPHASEVEN" not in block(page(21, BEA)), (block(page(21, ADA)), block(page(21, BEA))))
    r = post(21, BEA, act="done")
    check("…and a member's Done ticks it with their own, never the other member's",
          code(r) == "partdone" and any("SHAREDLINE" in t for t, _ in done(21)) and any("BRAVOSEVEN" in t for t, _ in done(21)) and f"member-a: {A_STEP}" in lines(21, _steps.OPEN), (code(r), done(21), lines(21, _steps.OPEN)))

    check("a bullet that names no one, under a member's line, is that member's", "BAREBRAVO" in block(page(22, BEA)) and "BAREBRAVO" not in block(page(22, ADA)), (block(page(22, ADA)), block(page(22, BEA))))
    r = post(22, ADA, act="done")
    check("…so the other member's Done leaves it open", code(r) == "done" and any("BAREBRAVO" in x for x in lines(22, _steps.OPEN)) and not any("BAREBRAVO" in t for t, _ in done(22)), (code(r), lines(22, _steps.OPEN), done(22)))

    for i, tag, other in ((30, "SUBTHIRTY", "THIRTYB"), (31, "SUBTHIRTYONE", "THIRTYONEB")):
        a_block, b_block = block(page(i, ADA)), block(page(i, BEA))
        check(f"a sub-line a later write added under member-a's line is drawn for member-a alone (a{i})", tag in a_block and tag not in b_block and other in b_block, (a_block, b_block))
        check(f"…and on their own rows (a{i})", tag in row(home(ADA), i) and tag not in row(home(BEA), i), (row(home(ADA), i), row(home(BEA), i)))
        r = post(i, BEA, act="done")
        check(f"…member-b's Done leaves it open (a{i})", code(r) == "partdone" and any(tag in x for x in lines(i, _steps.OPEN)) and not any(tag in t for t, _ in done(i)), (code(r), lines(i, _steps.OPEN), done(i)))
        r = post(i, ADA, act="done")
        check(f"…and member-a's Done ticks it (a{i})", code(r) == "done" and any(tag in t and by == "member-a" for t, by in done(i)), (code(r), done(i)))
    check("…a session's line that stood last stays open through both", any("AGENTLAST" in x for x in lines(31, _steps.OPEN)), lines(31, _steps.OPEN))

    whose = lambda nxt: _steps.member_rows({"next": nxt})[2]
    check("a bare line under a member's line is that member's", whose("member-a: one\n- under") == ["member-a", "member-a"], whose("member-a: one\n- under"))
    check("…under a line that names no one it is no one's, though a member's line stands higher", whose("member-a: one\ncheck the plain one\n- under") == ["member-a", "", ""], whose("member-a: one\ncheck the plain one\n- under"))
    check("…and so under a session's line", whose("member-a: one\nalpha-build: two\n- under") == ["member-a", None, ""], whose("member-a: one\nalpha-build: two\n- under"))
    field = {"state": "your-step", "step": "sign STEPFIELD", "mover": "member-a", "next": "alpha-build: prepare"}
    check("a member's next text is the step field only for the member the step is asked of",
          ui_render.Board.next_of(None, field, "member-a") == "sign STEPFIELD" and ui_render.Board.next_of(None, field, "member-b") == "", (ui_render.Board.next_of(None, field, "member-a"), ui_render.Board.next_of(None, field, "member-b")))
    direct = {"state": "your-step", "step": "sign DIRECTA", "mover": "member-a", "then": "alpha-build", "owner": OWNER_S, "owner_step": "member-a: sign DIRECTA", "step_lines": ["a line"], "draft": "a draft",
              "next": "member-a: sign DIRECTA\nmember-b: countersign DIRECTB"}
    stays = answer_handover._share_step(direct, {"ts": now, "kind": "decision"}, "member-a", True, now)
    check("a step that passes on drops what belonged to it: the server's line record, the step's lines and the draft",
          stays == "member-b" and direct["mover"] == "member-b" and direct["step"] == "countersign DIRECTB" and not [k for k in ("owner_step", "step_lines", "draft") if k in direct], (stays, direct))

    project = get("/projects/alpha", ADA)
    shared_row = row(project, 1)
    check("a project page draws no step, draft or form for a step two members have had a part in", shared_row and "<form" not in shared_row and 'value="done"' not in shared_row
          and not [x for x in ("ALPHASEVEN", "BRAVOSEVEN", "ALPHADRAFT", "fleet countersign") if x in shared_row], shared_row or project[:600])
    check("…its row says why and links the item page", bool(re.search(r'<a href="[^"]*/items/a1">More than one member has a part in this step: open the item for yours\.</a>', shared_row)), shared_row)
    check("…and keeps the step and its Done where one member alone has a part", 'value="done"' in row(project, 8) and "ALPHASEVEN" in row(project, 8), row(project, 8))

    # ---- 2. Done by the member the step is asked of
    before = rd(2)["state_updated"]
    told.clear()
    r = post(2, ADA, act="done", back="/")
    check("Done by member-a from the home page: the step passes on, the answer is a done that names who has it now", code(r) == "done" and "then=member-b" in r.headers["location"], (code(r), r.headers.get("location")))
    m = meta(2)
    check("…member-a's line alone is ticked, by member-a", done(2) == [(f"member-a: {A_STEP}", "member-a")], done(2))
    check("…member-b's step stays open, with its sub-line", any("BRAVOSEVEN" in x for x in lines(2, _steps.OPEN)) and "SUBSEVEN" in m["next"] and "ALPHASEVEN" not in m["next"], m["next"])
    check("…member-b is the mover, the item stays a step that is theirs", m.get("state") == "your-step" and m.get("mover") == "member-b" and m.get("step", "").startswith("countersign BRAVOSEVEN") and m.get("owner_step", "").startswith("member-b: countersign BRAVOSEVEN"), m)
    check("…the draft and the old wake's reason went with member-a's step", "draft" not in m and "watch_reason" not in m, m)
    check("…the then stays for the last Done", m.get("then") == "alpha-build", m)
    got = answer_line(2)
    check("the answer line says who finished which step and whose step the item stayed on", got[:3] == ["decision", "Done", f"member-a, on the step “{A_STEP}” (after this answer the item was still on a step, with member-b)"] and len(got) == 4, got)
    check("…its state clock moved", rd(2)["state_updated"] > before)
    check("…the sessions are told whose step it is now", any(re.search(r"member-a did their step on .*: sign the ALPHASEVEN form\. It goes to member-b for their step now", t) for t, _ in said(2)), said(2))
    check("…a bare Done is a progress notice, not a turn, and nothing is left pending", said(2) and all(how == "own-move" for _, how in said(2)) and not pending(2), (said(2), pending(2)))
    A, B = home(ADA), home(BEA)
    check("…member-b has it on Your move with their command and Done; member-a reads it as member-b's", 2 in ids(B, "your-move") and 'value="done"' in row(B, 2) and "fleet countersign" in row(B, 2)
          and 2 in ids(A, "waiting-list") and 2 not in ids(A, "your-move") and "<form" not in row(A, 2) and "BRAVOSEVEN" in row(A, 2), (ids(A, "your-move"), row(A, 2)))
    told.clear()
    r = post(2, BEA, act="done", back="/")
    m = meta(2)
    check("…then member-b's Done ends the step and hands the item to its then", code(r) == "done" and "then=alpha-build" in r.headers["location"] and m.get("state") != "your-step" and m.get("mover") == "alpha-build" and "step" not in m, (code(r), m))
    check("…each line ticked by its own member", {(t.split(":")[0], by) for t, by in done(2)} == {("member-a", "member-a"), ("member-b", "member-b")} and not [x for x in lines(2, _steps.OPEN) if x.startswith("member-")], (done(2), lines(2, _steps.OPEN)))
    check("…and the session is told it was member-b", any(t.startswith("[stackshot] member-b did their step") for t, _ in said(2)), said(2))

    # ---- 3. Done by another member first
    before = rd(3)["state_updated"]
    told.clear()
    r = post(3, BEA, act="done")
    m = meta(3)
    check("Done by member-b first: their step is ticked and the item stays", code(r) == "partdone", (code(r), r.headers.get("location")))
    check("…member-b's line alone is ticked", [by for _, by in done(3)].count("member-b") == len(done(3)) >= 1 and all(not t.startswith("member-a") for t, _ in done(3)) and f"member-a: {A_STEP}" in lines(3, _steps.OPEN), (done(3), lines(3, _steps.OPEN)))
    check("…the mover, the step, its draft and the server's line are as they were", m.get("state") == "your-step" and m.get("mover") == "member-a" and m.get("step") == A_STEP and m.get("draft") and m.get("owner_step") == f"member-a: {A_STEP}" and rd(3)["state_updated"] == before, m)
    check("…the record names the step member-b did", m["answers"][-1]["by"] == "member-b" and m["answers"][-1]["step"].startswith("countersign BRAVOSEVEN"), m["answers"])
    check("…the sessions are told it stays with member-a", any(re.search(r"member-b did their step on .*: countersign BRAVOSEVEN.*\. The item stays with member-a", t) for t, _ in said(3)), said(3))
    got = answer_line(3)
    check("…and so does the answer line after a Done that left the step, as no decision of the one asked", got[:2] == ["comment", "Done"] and got[2].startswith("member-b, on the step “countersign BRAVOSEVEN")
          and got[2].endswith("” (after this answer the item was still on a step, with member-a)"), got)
    A, B = home(ADA), home(BEA)
    check("…member-a still has it with their Done; member-b reads it as member-a's, with member-a's line", 3 in ids(A, "your-move") and 'value="done"' in row(A, 3) and 3 in ids(B, "waiting-list") and 3 not in ids(B, "your-move") and "<form" not in row(B, 3) and "ALPHASEVEN" in row(B, 3), (ids(B, "your-move"), row(B, 3)))
    shown = get("/items/a3?sent=partdone", BEA)
    check("…the page says only their step is ticked", bool(re.search(r'<p class="isent ok" role="status">[^<]*your step is ticked', shown)), shown[:300])
    check("…and the home page carries that notice for a board of two", "partdone" in re.search(r'<div id="sent-notes"[^>]*>', B).group(0))
    r = post(3, BEA, act="done")
    check("…a second Done of member-b's, from an old page, writes nothing", code(r) == "nostep" and len(meta(3)["answers"]) == 1, (code(r), meta(3)["answers"]))
    r = post(3, BEA, act="note", text="a word from the side")
    m = meta(3)
    check("…and a note of theirs, their own step done, is kept as a comment, member-a's step as it was", code(r) == "comment" and m["answers"][-1]["kind"] == "comment" and m["answers"][-1]["text"] == "a word from the side"
          and m.get("state") == "your-step" and f"member-a: {A_STEP}" in lines(3, _steps.OPEN), (code(r), m))
    r = post(3, ADA, act="done")
    m = meta(3)
    check("…then member-a's Done ends the step and hands the item over", code(r) == "done" and m.get("state") != "your-step" and m.get("mover") == "alpha-build", (code(r), m))
    check("…and the answer line of a finished step is the plain one: who answered, and nothing of a step", answer_line(3)[:3] == ["decision", "Done", ""] and answer_line(3)[4:] == ["member-a"], answer_line(3))

    # ---- 4. notes
    told.clear()
    r = post(4, ADA, act="note", text="what is the form number?")
    m = meta(4)
    check("a note that does not say done ticks and moves nothing", code(r) == "comment" and not done(4) and m.get("state") == "your-step" and m.get("mover") == "member-a" and m.get("step") == A_STEP and m["answers"][-1]["kind"] == "step-reply", (code(r), done(4), m))
    check("…the sessions get the note and it waits for a session's write", any("member-a sent a note on their step" in t and "The item stays with member-a: “what is the form number?”" in t and how == "turn" for t, how in said(4)) and pending(4), (said(4), pending(4)))
    check("…each line says an answer belongs on the item", all(f"form number?”. {telling.ON_ITEM} → " in t for t, _ in said(4)), said(4))
    told.clear()
    r = post(5, ADA, act="note", text="ran it")
    m = meta(5)
    check("a note that says done passes the step on", code(r) == "stepreply" and m.get("mover") == "member-b" and m.get("state") == "your-step", (code(r), m))
    check("…the ticked line shows the words, and member-b's is open", any("ran it" in x["text"] and x["by"] == "member-a" for x in _steps.view(m) if x["status"] == _steps.DONE) and any("BRAVOSEVEN" in x for x in lines(5, _steps.OPEN)), _steps.view(m))
    check("…the line told carries the note", any("It goes to member-b for their step now, with their note: “ran it”" in t for t, _ in said(5)) and pending(5), said(5))
    told.clear()
    r = post(6, BEA, act="note", text="which card?")
    check("a note of member-b's that does not say done: nothing ticked, the item stays with member-a", code(r) == "comment" and not done(6) and meta(6).get("mover") == "member-a"
          and any("member-b sent a note on their step" in t and "countersign BRAVOSEVEN" in t and "stays with member-a" in t for t, _ in said(6)), (code(r), done(6), said(6)))
    r = post(7, BEA, act="note", text="ran it")
    check("…the answer line carries their words after who and which step", answer_line(7)[2].startswith("member-b, on the step “countersign BRAVOSEVEN") and answer_line(7)[2].endswith("with member-a): ran it"), answer_line(7))
    plain = lambda rec: answer_handover._answer_line({"metadata": {"state": "your-step", "step": A_STEP, "answers": [{"ts": now, "via": "board", **rec}]}}).split("\t")[2]
    check("a comment's answer line and one of an answer that names no step are the plain ones",
          plain({"kind": "comment", "step": A_STEP, "text": "a word"}) == "member-a: a word" and plain({"kind": "decision", "choice": "Ship it", "by": "member-b"}) == "", (plain({"kind": "comment", "step": A_STEP, "text": "a word"}), plain({"kind": "decision", "choice": "Ship it"})))
    check("a note of member-b's that says done ticks their step alone", code(r) == "partdone" and done(7) and all(by == "member-b" for _, by in done(7)) and f"member-a: {A_STEP}" in lines(7, _steps.OPEN) and meta(7).get("mover") == "member-a", (code(r), done(7)))

    # ---- 5. who may not finish a step
    was = rd(8)
    r = post(8, BEA, act="done")
    check("a Done that arrives from a member with no part, on a step only one member has had, writes nothing", code(r) == "nostep" and rd(8) == was, (code(r), done(8), meta(8)))
    r = post(23, BEA, act="done")
    check("a Done of member-b's own step beside a part that is the step field alone ticks theirs and leaves the step", code(r) == "partdone" and meta(23).get("state") == "your-step", (code(r), meta(23)))
    r = post(23, BEA, act="done")
    check("…and their second Done writes nothing", code(r) == "nostep" and meta(23).get("state") == "your-step", (code(r), meta(23)))
    was = rd(24)
    r = post(24, BEA, act="done")
    check("a ticked line of one member and a step field asked of another are two parts: the first member's Done writes nothing", code(r) == "nostep" and rd(24) == was, (code(r), meta(24)))
    was = rd(9)
    r = post(9, BEA, act="done")
    check("a Done beside another member's question writes nothing: the question stands", code(r) == "askwaits" and rd(9) == was and "decision" in meta(9)["needs"], (code(r), meta(9)))
    was = rd(33)
    r = post(33, ADA, act="done")
    check("a Done of the member asked, from a page drawn before the question was added, writes nothing on a two-member step: nobody else is handed the question",
          code(r) == "askwaits" and rd(33) == was and meta(33)["mover"] == "member-a", (code(r), meta(33)))
    r = post(33, ADA, act="note", text="ran it")
    m = meta(33)
    check("…and their note is kept as a comment, the step and the question as they were", code(r) == "comment" and m["answers"][-1]["kind"] == "comment" and m["answers"][-1]["text"] == "ran it"
          and m["mover"] == "member-a" and m["step"] == A_STEP and "decision" in m["needs"] and not done(33), (code(r), m))
    r = post(32, ADA, act="done")
    check("beside a question on a step one member alone has had, that member's Done counts as before", code(r) == "done" and meta(32).get("state") != "your-step", (code(r), meta(32)))

    # ---- 6. a mail tick
    was = rd(10)
    out = mail(10)
    check("a mail tick on a step asked of another member is dropped", out == "nostep" and rd(10) == was, (out, meta(10)))
    told.clear()
    out = mail(11)
    m = meta(11)
    check("a mail tick on the first member's step passes it on", out == "done" and m.get("mover") == "member-b" and done(11) == [(f"member-a: {A_STEP}", "member-a")], (out, done(11), m))
    check("…the session is told who sent the mail and whose step it is now", any("saw a mail member-a sent" in t and "It ticked the step. It goes to member-b for their step now" in t for t, _ in said(11)), said(11))

    # ---- 7. the edges
    r = post(12, ADA, act="done")
    check("a Done by the holder of the step field alone passes to the member whose line is open", code(r) == "done" and meta(12).get("mover") == "member-b" and any("BRAVOSEVEN" in x for x in lines(12, _steps.OPEN)), (code(r), meta(12)))
    r = post(13, ADA, act="done")
    check("a step that passes on needs no session to take the item", code(r) == "done" and meta(13).get("mover") == "member-b", (code(r), meta(13)))

    # ---- 7b. a line's member is settled when it is written and stays with the line
    def upd(i, sender="alpha-build", **kw):
        out = _wt_update.stackshot_update(f"a{i}", sender=sender, **kw)
        board_home._board_home_drop()
        return out

    def fresh(i, step="", asked="member-a", next_="alpha-build: prepare", **extra):
        if step:
            extra = {"state": "your-step", "step": step, "mover": asked, "then": "alpha-build", **extra}
        else:
            extra = {"needs": ["alpha-build"], **extra}
        item(i, next=next_, **extra)

    def whose(i):
        cl, _at, who = _steps.member_rows(meta(i))
        return sorted((_steps.first_line(s["text"]), w) for s, w in zip(cl, who) if s["status"] == _steps.OPEN)

    def of_line(i, tag): return [w for line, w in whose(i) if tag in line]
    def inorder(i, words):      # whose each open line that reads `words` is, in the order of next
        cl, where, who = _steps.member_rows(meta(i))
        return [w for _j, w in sorted((j, w) for s, j, w in zip(cl, where, who) if j is not None and _steps.first_line(s["text"]) == words)]
    def at(i, tag): return next(n for n, s in enumerate(_steps.view(meta(i)), 1) if tag in s["text"] and s["status"] == _steps.OPEN)
    def settled(i): return [(_steps.first_line(s["text"]), s["of"]) for s in meta(i).get("steps") or [] if "of" in s]
    def ticked_by(i, tag): return [by for t, by in done(i) if tag in t]
    def bare_of(i, tag): return [w for line, w in whose(i) if tag in line and not line.startswith("member-")]      # without the line the server writes for a step it passes on

    def still_a(i, tag):
        return bare_of(i, tag) == ["member-a"] and set(of_line(i, tag)) == {"member-a"} and tag in block(page(i, ADA)) and tag not in block(page(i, BEA))

    base = lambda i: f"member-b: countersign EX{i}\nmember-a: file EF{i}\n- use PEN{i}"
    for i, label, change in ((50, "marked done", lambda i: upd(i, done=[at(i, f"EF{i}")])),
                             (51, "dropped", lambda i: upd(i, dropped=[at(i, f"EF{i}")])),
                             (52, "reworded", lambda i: upd(i, reword={at(i, f"EF{i}"): f"member-a: file EF{i} today"}))):
        fresh(i, step=f"countersign EX{i}", asked="member-b")
        upd(i, next=base(i))
        check(f"a sub-line is stored as its writer wrote it, under a member's line (a{i})", settled(i) == [(f"use PEN{i}", "member-a")], settled(i))
        change(i)
        check(f"a sub-line stays its member's when the line above it is {label} (a{i})", of_line(i, f"PEN{i}") == ["member-a"], (whose(i), meta(i)["next"]))
        r = post(i, BEA, act="done")
        check(f"…the other member's Done neither ticks it nor takes it, and the step passes to its member (a{i})",
              code(r) == "done" and not ticked_by(i, f"PEN{i}") and meta(i).get("mover") == "member-a" and meta(i).get("state") == "your-step" and still_a(i, f"PEN{i}"), (code(r), whose(i), done(i), meta(i)))
        check(f"…who keeps it on Your move (a{i})", i in ids(home(ADA), "your-move") and i not in ids(home(BEA), "your-move"), (ids(home(ADA), "your-move"), ids(home(BEA), "your-move")))

    fresh(53, step="countersign EX53", asked="member-b", next_="member-b: countersign EX53")
    upd(53, next="member-a: file EF53\n- use PEN53\nmember-b: countersign EX53")
    upd(53, done=[at(53, "EF53")])
    check("a sub-line left first in next stays its member's, not both members'", of_line(53, "PEN53") == ["member-a"] and meta(53)["next"].startswith("- use PEN53") and still_a(53, "PEN53"), (whose(53), meta(53)["next"]))
    r = post(53, BEA, act="done")
    check("…and the other member's Done leaves it open", code(r) == "done" and not ticked_by(53, "PEN53") and still_a(53, "PEN53"), (code(r), done(53), whose(53)))

    fresh(54, step="countersign EX54", asked="member-b")
    upd(54, next=base(54))
    r = post(54, ADA, act="note", text="ran it")
    check("a member's note that says done ticks their line and its sub-line, never another's",
          ticked_by(54, "EF54") == ["member-a"] and ticked_by(54, "PEN54") == ["member-a"] and not ticked_by(54, "EX54") and of_line(54, "EX54") == ["member-b"], (code(r), done(54), whose(54)))

    fresh(55, step="sign WHY55", next_="member-a: sign WHY55", owner_step="member-a: sign WHY55")
    upd(55, next="member-a: sign WHY55\n- use PEN55\nmember-b: countersign EX55")
    upd(55, step="sign WHY55 in blue")
    check("a reworded step moves the server's line to the end and the sub-line stays its member's", meta(55)["next"].rstrip().endswith("member-a: sign WHY55 in blue") and of_line(55, "PEN55") == ["member-a"], (meta(55)["next"], whose(55)))
    r = post(55, BEA, act="done")
    check("…the other member's Done leaves it open", code(r) == "partdone" and not ticked_by(55, "PEN55") and still_a(55, "PEN55"), (code(r), done(55), whose(55)))
    r = post(55, ADA, act="done")
    check("…and its member's Done ticks it", ticked_by(55, "PEN55") == ["member-a"], (code(r), done(55)))

    fresh(56, next_="")
    upd(56, step="sign WHY56", mover="member-a")      # the server writes its own line for the step
    upd(56, sender="alpha-main", next="member-b: countersign EX56")
    upd(56, next="member-a: sign WHY56\n- use PEN56")
    check("a sub-line whose parent line was merged into another writer's is the parent's member's, though it lands under another member's line",
          meta(56)["next"] == "member-a: sign WHY56\nmember-b: countersign EX56\n- use PEN56" and of_line(56, "PEN56") == ["member-a"], (meta(56)["next"], whose(56)))
    upd(56, next="member-a: sign WHY56\n- use PEN56")
    check("…and stays so when its writer writes the same text again", of_line(56, "PEN56") == ["member-a"], whose(56))
    r = post(56, BEA, act="done")
    check("…the other member's Done leaves it open", code(r) == "partdone" and not ticked_by(56, "PEN56") and still_a(56, "PEN56"), (code(r), done(56), whose(56)))

    post(56, ADA, act="done")
    check("…and its own member's Done leaves the ticked line that member's", ticked_by(56, "PEN56").count("member-a") >= 1
          and [w for line, w in settled(56) if "PEN56" in line and not line.startswith("member-")] == ["member-a"], (done(56), settled(56)))

    fresh(57)
    upd(57, next="alpha-build: prepare\nmember-a: file EF57\n- use PEN57")
    check("a line holds its member from its first save, however many members have had a part in the item", settled(57) == [("use PEN57", "member-a")], settled(57))
    upd(57, done=[at(57, "EF57")])
    upd(57, next="alpha-build: prepare\n- use PEN57\nmember-b: countersign EX57")
    check("…so it is still that member's when a second joins, though it stands under a session's line by then", of_line(57, "PEN57") == ["member-a"] and dict(settled(57))["use PEN57"] == "member-a", (whose(57), settled(57)))
    upd(57, step="countersign EX57", mover="member-b")
    r = post(57, BEA, act="done")
    check("…so the second member's Done leaves it open", not ticked_by(57, "PEN57") and still_a(57, "PEN57"), (code(r), done(57), whose(57)))

    fresh(58, step="sign WHY58")
    upd(58, next="member-a: sign WHY58\nmember-b: countersign EX58\n- hold CARD58")
    upd(58, done=[at(58, "EX58")])
    check("a sub-line left under another member's line stays its member's", of_line(58, "CARD58") == ["member-b"] and "CARD58" in block(page(58, BEA)) and "CARD58" not in block(page(58, ADA)), (meta(58)["next"], whose(58)))
    out = mail(58)
    check("…a mail tick does not tick it, and the step passes to its member", out == "done" and not ticked_by(58, "CARD58") and meta(58).get("mover") == "member-b", (out, done(58), meta(58)))

    fresh(59, step="countersign EX59", asked="member-b")
    upd(59, next="member-a: file EF59\n- check it\nmember-b: countersign EX59\n- check it")
    check("two sub-lines that say the same words are each the member's they stand under", inorder(59, "check it") == ["member-a", "member-b"], whose(59))
    upd(59, next="member-b: countersign EX59\n- check it\nmember-a: file EF59\n- check it")
    check("…and still are after their writer swaps the two sections", inorder(59, "check it") == ["member-b", "member-a"], (whose(59), meta(59)["steps"]))
    r = post(59, BEA, act="done")
    check("…a member's Done ticks their own copy and leaves the other's", inorder(59, "check it") == ["member-a"] and ticked_by(59, "check it") == ["member-b"], (code(r), done(59), whose(59)))

    fresh(60)
    upd(60, next="member-a: file EF60\n- check it")
    upd(60, next="member-b: countersign EX60\n- check it\nmember-a: file EF60\n- check it")
    check("a second member's new sub-line with the first's words is the second's, wherever it is written, and the first's stays where it was", inorder(60, "check it") == ["member-b", "member-a"], (whose(60), meta(60)["steps"]))
    upd(60, sender="alpha-main", next="member-a: own SIXTY\n- alone SIXTY")
    check("another session's sub-line under a member's line is that member's", of_line(60, "alone SIXTY") == ["member-a"], (meta(60)["next"], whose(60)))
    upd(60, sender="alpha-main", reword={at(60, "alone SIXTY"): "member-b: take SIXTY"})
    check("a sub-line reworded to name a member is that member's, with nothing stored on it", of_line(60, "take SIXTY") == ["member-b"] and not [x for x in settled(60) if "SIXTY" in x[0]], (whose(60), settled(60)))

    leading = {"next": "member-a: A61\n- alone LEAD\nmember-b: B61", "steps": stored("member-a: A61", "member-b: B61", "- alone LEAD")}
    _steps.settle_members(leading, {"next": "member-a: A61\nmember-b: B61", "steps": stored("member-a: A61", "member-b: B61")}, "- alone LEAD")
    check("a new bare line a write's own text puts above every other line is read from where it stands in next", [s.get("of") for s in leading["steps"]] == [None, None, "member-a"], leading["steps"])

    fresh(61)
    upd(61, next="member-a: file EF61\n- use PEN61")
    upd(61, clear_next=True, next="alpha-build: prepare\nmember-b: countersign EX61\n- use PEN61")
    check("a wipe that lists the words again keeps the line, and its member", of_line(61, "PEN61") == ["member-a"] and settled(61) == [("use PEN61", "member-a")], (whose(61), settled(61)))
    upd(61, dropped=[at(61, "PEN61")])
    upd(61, next="alpha-build: prepare\nmember-b: countersign EX61\n- use PEN61")
    check("a line dropped and written again under another member is a new line, that member's; the dropped one keeps whose it was",
          of_line(61, "PEN61") == ["member-b"] and [w for line, w in settled(61) if line == "use PEN61"] == ["member-a", "member-b"], (whose(61), settled(61), meta(61)["next"]))

    fresh(62, step="sign WHY62", next_="member-b: countersign EX62\nmember-a: sign WHY62\n- use PEN62", owner_step="member-a: sign WHY62")      # stored with no member on its lines
    r = post(62, ADA, act="note", text="ran it")
    check("a note on an item stored before members were: its sub-line is read before the answer takes a line out",
          ticked_by(62, "PEN62") == ["member-a"] and not ticked_by(62, "EX62") and meta(62).get("mover") == "member-b", (code(r), done(62), meta(62)["next"]))

    fresh(63, next_="member-a: file EF63\n- use PEN63\nmember-b: countersign EX63")      # the same, then a session's write
    upd(63, done=[at(63, "EF63")])
    check("a session's write to such an item settles its lines as they stood before it", of_line(63, "PEN63") == ["member-a"] and dict(settled(63)) == {"use PEN63": "member-a"}, (whose(63), settled(63)))

    fresh(64, step="sign WHY64")
    r = post(64, ADA, act="done")
    upd(64, step="sign WHY64 once more", mover="member-a")
    check("an answer that ended its step reads plain when a later step is set", code(r) == "done" and meta(64).get("state") == "your-step" and answer_line(64)[2] == "" and answer_line(64)[4:] == ["member-a"], answer_line(64))

    pair(67)
    post(67, BEA, act="done")
    held = answer_line(67)
    upd(67, step="none")
    upd(67, step="sign WHY67 anew", mover="member-b")
    check("…and one that left a step standing says so of its own time, whatever step is set later",
          meta(67).get("step") == "sign WHY67 anew" and answer_line(67) == held and held[2].endswith("” (after this answer the item was still on a step, with member-a)"), (held, answer_line(67), meta(67).get("step")))

    kept = lambda of: _steps.member_rows({"next": "- under", "steps": [{"text": "- under", "status": "open", "of": of}]})[2]
    check("a stored member reads as stored: nobody's, a member's, and no member's Done for a name that is no member's now",
          (kept(""), kept("MB"), kept("member-c")) == ([""], ["member-b"], [None]), (kept(""), kept("MB"), kept("member-c")))
    other = lambda *lines: _steps.member_rows({"next": "\n".join([*lines, "- under"]), "steps": [*stored(*lines), {**stored("- under")[0], "of": "-"}]})[2][-1]
    check("a line stored as written under someone else's reads as no one's while one member alone has had a part, and as no member's from the second",
          (other("alpha-build: x"), other("member-a: x", "alpha-build: y"), other("member-a: x", "member-b: y", "alpha-build: z")) == ("", "", None),
          (other("alpha-build: x"), other("member-a: x", "alpha-build: y"), other("member-a: x", "member-b: y", "alpha-build: z")))
    asked_only = {"state": "your-step", "step": "sign", "mover": "member-b", "next": "member-a: x\nalpha-build: y\n- under", "steps": [*stored("member-a: x", "alpha-build: y"), {**stored("- under")[0], "of": "-"}]}
    check("…the member a step is asked of counting as one who has had a part", _steps.member_rows(asked_only)[2][-1] is None and _steps.member_rows({**asked_only, "step": ""})[2][-1] == "", _steps.member_rows(asked_only)[2])

    fresh(68, next_="member-a: file EF68\nalpha-build: tidy\n- check SUB68", state="your-step", step="sign WHY68", mover="member-b", then="alpha-build", needs=[])
    upd(68, done=[at(68, "EF68")])      # stored with the step asked of member-b and no line of theirs yet
    check("a bare line left first in next by a mark, stored before members were, keeps the session's line it was written under", dict(settled(68)).get("check SUB68") == "-" and of_line(68, "SUB68") == [None], (settled(68), whose(68)))

    fresh(69)
    upd(69, next="member-a: file EF69\n- check it\nmember-b: countersign EX69")
    upd(69, next="member-a: file EF69\n- check it\nmember-b: countersign EX69\n- check it")
    check("a new sub-line with the words of a stored one is its own writer's member's, and the stored one keeps its own",
          [w for line, w in settled(69) if line == "check it"] == ["member-a", "member-b"], (settled(69), meta(69)["next"]))

    done_line = {"text": "- check it", "status": "done", "by": "member-b", "at": now - 60}
    item(70, next="member-a: file EF70\n- check it", steps=[{**stored("member-b: countersign EX70")[0], "status": "done", "by": "member-b", "at": now - 60}, done_line, *stored("member-a: file EF70", "- check it")])
    upd(70, next="alpha-build: tidy\nmember-a: file EF70\n- check it")
    check("a ticked line and an open one with the same words, stored before members were, each keep their reading", [w for line, w in settled(70) if line == "check it"] == ["member-b", "member-a"], settled(70))

    item(71, next="member-a: file EF71\n- use PEN71\nmember-b: countersign EX71", steps=stored("member-a: file EF71", "member-b: countersign EX71", "- use PEN71"))
    upd(71, done=[at(71, "PEN71")])
    check("a sub-line a write marks on such an item is read as it stood before the mark", dict(settled(71)) == {"use PEN71": "member-a"}, settled(71))

    fresh(73)
    upd(73, next="member-a: file EF73\n- use PENA73\nmember-b: countersign EX73\n- use PENB73")
    upd(73, next="alpha-build: prepare\nmember-b: countersign EX73\n- use PENB73\nmember-a: file EF73\n- use PENA73")
    check("two sub-lines whose writer swaps their sections each stay their member's", dict(settled(73)) == {"use PENA73": "member-a", "use PENB73": "member-b"}, (settled(73), meta(73)["next"]))

    held = [{**x, "of": "member-a"} for x in stored("- one", "- two")]
    of = lambda steps: [x.get("of") for x in steps]
    check("the stored member survives a mark, a wipe, an unlisted line and a reorder of the checklist, and a close",
          (of(_steps.apply(held, None, [0], [1], "s", now)), of(_steps.apply(held, "alpha-build: x", [], [], "s", now, wipe=True))[:2], of(_steps.apply(held, "alpha-build: x", [], [], "s", now, strict=False))[:2],
           of(_steps.apply([held[0], {**held[1], "of": "member-b"}], "- two\n- one", [], [], "s", now)), of(_steps.mark_open(held, "done", "s", now)))
          == (["member-a"] * 2, ["member-a"] * 2, ["member-a"] * 2, ["member-b", "member-a"], ["member-a"] * 2),
          (of(_steps.apply(held, None, [0], [1], "s", now)), of(_steps.apply([held[0], {**held[1], "of": "member-b"}], "- two\n- one", [], [], "s", now))))
    gone = _steps.view_rows({"next": "member-a: here", "steps": [*stored("member-a: here"), {**stored("- gone")[0], "of": "member-b"}]})[0]
    check("…and a view of a line that left next by itself", [(x["status"], x.get("of")) for x in gone] == [("open", None), ("dropped", "member-b")], gone)

    nobodys = {"next": "member-a: AX\n- under", "steps": [*stored("member-a: AX"), {**stored("- under")[0], "of": ""}]}
    ticked = {"next": "member-a: AX\nmember-b: BX", "steps": [*stored("member-a: AX", "member-b: BX"), {"text": "- under", "status": "done", "by": "member-a", "at": now}]}
    _steps.settle_members(ticked, nobodys)
    check("a stored member outlasts a tick that rebuilt the step without it, whoever alone had a part before", ticked["steps"][-1].get("of") == "", ticked["steps"])

    fresh(74)
    upd(74, next="alpha-build: go\nmember-b: countersign EX74\n- check it\nmember-a: file EF74\n- check it")
    check("two new sub-lines that say the same words are each the member's they are written under", inorder(74, "check it") == ["member-b", "member-a"], (whose(74), meta(74)["steps"]))
    check("…and are stored in the order next gives them", [v for line, v in settled(74) if line == "check it"] == ["member-b", "member-a"], meta(74)["steps"])

    fresh(75)
    upd(75, next="alpha-build: prepare\n- check it")
    upd(75, next="alpha-build: go\nmember-b: countersign EX75\n- check it\nalpha-build: prepare\n- check it")
    check("a member's new sub-line with the words of a session's, written above it, takes neither its member nor its place",
          inorder(75, "check it") == ["member-b", ""] and sorted(v for _l, v in settled(75)) == ["-", "member-b"] and [_steps.first_line(x["text"]) for x in meta(75)["steps"]][:2] == ["alpha-build: prepare", "check it"], (whose(75), meta(75)["steps"]))

    # ---- 7c. a second member joining moves no line to a member it was not written under
    ticked_a = lambda text: {"text": text, "status": "done", "by": "member-a", "at": now - 60}
    ticked_s = lambda text: {"text": text, "status": "done", "by": "alpha-build", "at": now - 60}
    def a_did(i):      # the first member alone has had a part: asked once, and done
        fresh(i, step=f"sign WHY{i}", next_=f"member-a: sign WHY{i}", owner_step=f"member-a: sign WHY{i}")
        post(i, ADA, act="done")

    def ask_b(i): upd(i, step=f"countersign EX{i}", mover="member-b", then="alpha-build")

    def nobodys(i, label, read=None):      # the line LOG<i> is no member's, and the second member's Done gives the item back to the builder
        mine = row(home(ADA), i)
        check(f"…it stays no member's when the second member is asked, and gives the first no part ({label})",
              of_line(i, f"LOG{i}") == [read] and f"LOG{i}" not in mine and i not in ids(home(ADA), "your-move") and f"LOG{i}" not in block(page(i, ADA)), (whose(i), meta(i), mine[:600]))
        r = post(i, BEA, act="done")
        check(f"…and the second member's Done returns the item to the builder, with no step made for the first ({label})",
              code(r) == "done" and meta(i).get("state") != "your-step" and meta(i).get("mover") == "alpha-build" and f"member-a: check LOG{i}" not in meta(i).get("next", ""), (code(r), meta(i)))
        if read is None:
            check(f"…and leaves the line under someone else's open for them ({label})", not ticked_by(i, f"LOG{i}") and of_line(i, f"LOG{i}") == [None], (done(i), whose(i)))

    for i, label, first in ((80, "under a session's line", "alpha-build: prepare"), (81, "under an outside party's line", "Acme: send the quote")):
        a_did(i)
        upd(i, next=f"{first}\n- check LOG{i}")
        check(f"a sub-line is stored as written under someone else's from its first save ({label})", settled(i) == [(f"check LOG{i}", "-")], settled(i))
        ask_b(i)
        nobodys(i, label)

    fresh(82, next_="")
    upd(82, next="Acme: send the quote\n- check LOG82")
    upd(82, step="sign WHY82", mover="member-a")
    ask_b(82)
    nobodys(82, "the first member only ever asked through step=")

    a_did(83)
    upd(83, next="alpha-build: prepare\n- check LOG83")
    upd(83, next="alpha-build: prepare\n- check LOG83\nmember-b: countersign EX83")
    check("a second member only named in a line of next moves no session's sub-line", of_line(83, "LOG83") == [None] and 83 not in ids(home(ADA), "your-move"), (whose(83), ids(home(ADA), "your-move")))

    fresh(84)
    upd(84, next="alpha-build: go\nmember-a: file EF84")
    upd(84, next="alpha-build: go\nmember-a: file EF84\nalpha-build: prepare\n- check LOG84")
    ask_b(84)
    mine = row(home(ADA), 84)
    check("with a line of their own open, the first member's row reads it and not the session's sub-line", of_line(84, "LOG84") == [None] and "EF84" in mine and "LOG84" not in mine and "LOG84" not in block(page(84, ADA)), (whose(84), mine[:600]))
    r = post(84, ADA, act="done")
    check("…and their Done ticks their own line and leaves the session's sub-line", ticked_by(84, "EF84") == ["member-a"] and not ticked_by(84, "LOG84"), (code(r), done(84), whose(84)))

    fresh(85)
    upd(85, next="alpha-build: go\nmember-a: file EF85\n- use PEN85\nalpha-build: prepare\n- check LOG85")
    upd(85, next="alpha-build: go\nmember-a: file EF85\n- use PEN85\nalpha-build: prepare\n- check LOG85\nmember-b: countersign EX85\n- take CARD85")
    check("each sub-line is stored as the member's it is written under, a session's as someone else's",
          dict(settled(85)) == {"use PEN85": "member-a", "check LOG85": "-", "take CARD85": "member-b"}, settled(85))

    after_a = [ticked_a("member-a: file EF86"), *stored("alpha-build: prepare")]      # the update tool refuses a next that opens with a bare line: another write path
    above = {"next": "- check LOG86\nalpha-build: prepare", "steps": [*after_a, *stored("- check LOG86")]}
    _steps.settle_members(above, {"next": "alpha-build: prepare", "steps": after_a}, "- check LOG86\nalpha-build: prepare")
    check("a new line a write puts above every other, after a member's finished line, is no member's", above["steps"][-1].get("of") == "", above["steps"])
    plain = {"next": "alpha-build: prepare"}
    _steps.settle_members(plain, {"next": "alpha-build: prepare"}, "alpha-build: prepare")
    check("a save of an item with no unnamed line writes nothing", plain == {"next": "alpha-build: prepare"}, plain)

    fresh(101, step="sign WHY101")
    upd(101, next="member-a: sign WHY101\nalpha-build: prepare\n- check LOG101")
    check("while one member alone has had a part, a session's sub-line stays with that member's step, as on a board of one", of_line(101, "LOG101") == [""] and "LOG101" in block(page(101, ADA)), (whose(101), settled(101)))
    r = post(101, ADA, act="done")
    check("…and their Done ticks it", ticked_by(101, "LOG101") == ["member-a"], (code(r), done(101)))

    # the same joins on items stored before lines held their member: read where they stand
    def older(i, steps, next_): item(i, next=next_, steps=steps, needs=["alpha-build"])

    for i, label, steps, next_ in (
            (87, "older item, under a session's line", [ticked_a("member-a: sign OLD87"), *stored("alpha-build: prepare", "- check LOG87")], "alpha-build: prepare\n- check LOG87"),
            (88, "older item, under an outside party's line", [ticked_a("member-a: sign OLD88"), *stored("Acme: send the quote", "- check LOG88")], "Acme: send the quote\n- check LOG88"),
            (89, "older item, under a session's finished line", [ticked_a("member-a: sign OLD89"), ticked_s("alpha-build: prepare"), *stored("- check LOG89")], "- check LOG89"),
            (94, "older item, above the only member line still open", [ticked_s("alpha-build: prepare"), *stored("member-a: file EF94", "- check LOG94")], "- check LOG94\nmember-a: file EF94")):
        older(i, steps, next_)
        check(f"an unstored line under someone else's reads as no one's while one member alone has had a part ({label})", of_line(i, f"LOG{i}") == [""], whose(i))
        ask_b(i)
        check(f"…and is stored as written under theirs, no member's, once a second is asked ({label})", dict(settled(i)).get(f"check LOG{i}") == "-" and of_line(i, f"LOG{i}") == [None], (settled(i), whose(i)))
        if i != 94:
            nobodys(i, label)

    older(95, [], "- check LOG95\nalpha-build: prepare")
    upd(95, step="sign WHY95", mover="member-a")
    ask_b(95)
    check("an older line with nothing above it anywhere is no member's, whoever alone had been asked", dict(settled(95)).get("check LOG95") == "", (settled(95), meta(95)["steps"]))

    for i, label, steps, next_ in (
            (90, "its finished line", [ticked_a("member-a: file EF90"), *stored("- use PEN90")], "- use PEN90"),
            (91, "its finished line, past a finished sub-line", [ticked_a("member-a: file EF91"), ticked_a("- first"), *stored("- use PEN91")], "- use PEN91"),
            (92, "its open line", stored("member-a: file EF92", "- use PEN92"), "member-a: file EF92\n- use PEN92")):
        older(i, steps, next_)
        check(f"an unstored sub-line reads as the member's it was written under ({label})", bare_of(i, f"PEN{i}") == ["member-a"], whose(i))
        ask_b(i)
        r = post(i, BEA, act="done")
        check(f"…and the second member's Done leaves it open and passes the step to that member ({label})",
              not ticked_by(i, f"PEN{i}") and meta(i).get("mover") == "member-a" and still_a(i, f"PEN{i}"), (code(r), whose(i), done(i), meta(i)))

    older(93, [*stored("alpha-build: prepare"), ticked_a("member-a: file EF93"), *stored("- use PEN93")], "alpha-build: prepare\n- use PEN93")
    ask_b(93)
    check("an older sub-line that stands under a session's line by now is read there, as no member's", dict(settled(93)).get("use PEN93") == "-" and of_line(93, "PEN93") == [None], (settled(93), whose(93)))

    item(98, state="your-step", step="countersign EX98", mover="member-b", then="alpha-build", next="alpha-build: prepare\n- check LOG98\nmember-b: countersign EX98",
         steps=[ticked_a("member-a: sign OLD98"), *stored("alpha-build: prepare", "- check LOG98", "member-b: countersign EX98")])
    nobodys(98, "an older step answered before any other write")

    older(96, [*stored("alpha-build: tidy", "member-a: file EF96"), {**ticked_a("member-b: countersign EX96"), "by": "member-b"}, {**ticked_a("- same words"), "by": "member-b"}, *stored("- same words")],
          "alpha-build: tidy\nmember-a: file EF96\n- same words")
    upd(96, next="alpha-build: go\nmember-a: file EF96\n- same words\nalpha-build: tidy")
    both = sorted((x["status"], x.get("of")) for x in meta(96)["steps"] if x["text"] == "- same words")
    check("an older open line and a finished one with its words each keep their own reading through a reorder", both == [("done", "member-b"), ("open", "member-a")], meta(96)["steps"])

    item(97, status="completed", outcome="done", reason="it shipped", needs=[], steps=[ticked_a("member-a: file EF97"), ticked_a("- use PEN97")])
    r = post(97, ADA, act="comment", text="noted")
    check("a write to a closed item stores nothing on its lines", code(r) == "closednote" and not settled(97), (code(r), meta(97)))

    # a row of another member's move words the question only while the item needs the decision
    for i, needs in ((99, ["alpha-build"]), (100, ["decision"])):
        item(i, needs=needs, mover="member-b", ask=ASK, options=OPTS, next=f"member-b: read EX{i}")
    board_home._board_home_drop()
    drawn = home(ADA)
    check("another member's row words an open question", "ship on Friday" in row(drawn, 100) and "EX100" not in row(drawn, 100), row(drawn, 100)[:600])
    check("…and the next step, not a stored ask, once the decision has left the needs", "EX99" in row(drawn, 99) and "ship on Friday" not in row(drawn, 99), row(drawn, 99)[:600])

    # the question beside a step: another member's is not answered by a Done
    pair_alone = dict(state="your-step", step=A_STEP, mover="member-a", then="alpha-build", next=f"member-a: {A_STEP}", needs=["decision"], ask=ASK, options=OPTS)
    item(65, **pair_alone)
    was = rd(65)
    r = post(65, BEA, act="done")
    check("a Done of another member beside a question on a step one member alone has had writes nothing", code(r) == "nostep" and rd(65) == was, (code(r), meta(65)))

    text_of = lambda m, who: ui_render.Board.next_of(None, m, who)
    mixed = {"steps": stored("member-a: LATER", "check NOBODY", "member-a: EARLIER"), "next": "member-a: EARLIER\nmember-a: LATER\ncheck NOBODY\nalpha-build: AGENT"}
    check("a member's next text is their lines in the order of next, without the lines that name no one", text_of(mixed, "member-a") == "member-a: EARLIER\nmember-a: LATER", text_of(mixed, "member-a"))
    check("…and the lines that name no one for a member with none", text_of(mixed, "member-b") == "check NOBODY", text_of(mixed, "member-b"))

    passing = {"state": "your-step", "step": "sign PASSA", "mover": "member-a", "owner": OWNER_S,
               "steps": [{"text": "member-b: BEFOREB", "status": "done", "by": "member-b", "at": now - 60}, *stored("member-a: sign PASSA", "alpha-build: AGENTFIRST", "member-b: countersign PASSB")],
               "next": "member-a: sign PASSA\nalpha-build: AGENTFIRST\nmember-b: countersign PASSB"}
    stays = answer_handover._share_step(passing, {"ts": now, "kind": "decision"}, "member-a", True, now)
    check("a step passes to the member of the next open member line, not a ticked line or a session's", stays == "member-b" and passing["step"] == "countersign PASSB", (stays, passing.get("step")))

    # ---- 8. one member
    _cfg.CFG["members"] = [TWO[0]]
    fresh(66, step="sign WHY66")
    upd(66, next="member-a: sign WHY66\n- use PEN66\nmember-b: countersign EX66")
    upd(66, done=[at(66, "EX66")])
    check("one member: nothing is stored about whose a line is", "steps" in meta(66) and not settled(66), meta(66).get("steps"))
    board_home._board_home_drop()
    one = home(ADA)
    note = re.search(r'<div id="sent-notes"[^>]*>', one)
    check("one member: the home page's notices are what they were", bool(note) and "partdone" not in note.group(0) and "nostep" in note.group(0), note.group(0)[:200] if note else one[:200])
    typed = get("/items/a1?sent=partdone", ADA)
    check("…a typed ?sent=partdone shows no notice on the item page", "ALPHASEVEN" in typed and not re.search(r'<p class="isent[^"]*" role="status">', typed) and ui_render.Board(str(T / "store")).sent_msg("partdone") == "",
          re.findall(r'<p class="isent.{0,120}', typed))
    check("…the project page keeps the step and its Done", 'value="done"' in row(get("/projects/alpha", ADA), 1), row(get("/projects/alpha", ADA), 1))
    r = post(21, ADA, act="done")
    check("…and a one-member answer records no step the item stayed on", "left_with" not in meta(21)["answers"][-1], meta(21)["answers"][-1])
    _cfg.CFG["members"] = TWO

print(f"\nmember_steps: {len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else "\nfailed: " + "; ".join(fails)))
sys.exit(1 if fails else 0)
