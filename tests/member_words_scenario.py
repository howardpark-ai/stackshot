"""Scenario test for whose word an entry of metadata.answers is on a board of several members (model/member_gates.py `said_by` and `owners`, and every reader of the record) — made-up data, a temp folder,
no live store, no network.

A board of two members (member-a the first, whose records carry no `by`; member-b with the alias MB). Covers, for each reader: another member's record is not taken as the person's answer, approval or note,
the person's own is, and where another member's record is shown it carries their name:

  * `get` (the answers and the words behind a wake) and the item page's heading over those words;
  * the start repair (a hand-off's end, the way back from a stored member mover) and the reason a hand-off record is ended with;
  * the note an update's reply carries, the ask's reminder and ask-time check, the owner's words behind a wake, the approval of a pause and of a platform key, one ask per decision, the For you list,
    the back-fill call, the migration's park quote and outcome words, tools/cap_words.py, the N4 check, the fill-in of past decisions;
  * the answer line a script reads, a second member's same note, the source of the words behind a park, the escalation of an answer nobody acted on;
  * one member: every record counts and every text reads as it did.

    tests/run-suite member_words  → exit 0 / 1"""
import datetime as dt, html, json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="member-words-"); T = pathlib.Path(tmp)
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
BUILD_S = "00000000-0000-4000-8000-000000000001"
FRONT_S = "00000000-0000-4000-8000-000000000002"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({BUILD_S: {"name": "alpha-build", "machine": "a", "seen": now}, FRONT_S: {"name": "alpha-main", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "agents": {"alpha-build": "builds it"}, "back_agents": {"alpha-build": "builds it"}, "status": "active", "board": [], "board_open": 0}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("90"); (T / "store/anchors.json").write_text("{}")
ASK = "Decide: ship ZEBRAWORD on Friday · Recommend: yes · Stakes: low · By: Fri"
ASK_B = "Decide: member-b: pick GIRAFFEWORD · Recommend: yes · Stakes: low · By: Fri"
OPTS = [{"label": "Ship it", "line": "Ship on Friday.", "recommended": True}, {"label": "Park it", "line": "Look again later.", "recommended": False, "wake": "2099-01-01"}]
LATER = (dt.date.today() + dt.timedelta(days=30)).isoformat()


def item(i, status="open", updated=3600, **meta):
    """Write one item as the store holds it (no save of the server's: what a repair or a reader finds)."""
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[work] item a{i}", "description": "- A fixture item.", "status": status,
                                                     "updated": now - updated, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": BUILD_S, "project": "projects/alpha", **meta}}))


def a(ago, text="", kind="comment", by="", via="board", **more):
    """An entry of metadata.answers made `ago` seconds ago; the first member's carries no `by`."""
    return {"ts": now - ago, "kind": kind, "via": via, **({"text": text} if text else {}), **({"by": by} if by else {}), **more}


def b(ago, text="", kind="comment", **more):
    return a(ago, text, kind, by="member-b", **more)


def handed(to, ago=1800):
    return {"to": to, "from": "alpha-main", "at": now - ago, "delivered_at": now - ago + 100, "taken_at": None, "events": []}


git = lambda *x: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *x], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
logging.disable(logging.INFO)
fails, ran = [], []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""), flush=True)


def rd(i): return json.loads((T / f"store/a/{i}.json").read_text(encoding="utf-8"))
def meta(i): return rd(i)["metadata"]


def refusal(fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        return str(e)
    return ""


from stackshot.web import server
from stackshot.core import config as _cfg
from stackshot.model import ask_leaves as _askl
from stackshot.model import cold_call as _cold
from stackshot.model import member_gates as _mgates
from stackshot.model import migration as _mig
from stackshot.model import next_backfill as _nbf
from stackshot.model import steps as _steps
from stackshot.notify import foryou_rows as _fy
from stackshot.service import answer as answer_svc
from stackshot.service import answer_handover as handover_svc
from stackshot.service import asks as asks_svc
from stackshot.service import caller_pass as caller_svc
from stackshot.service import gates as gates_svc
from stackshot.service import handoff as handoff_svc
from stackshot.service import migrations as mig_svc
from stackshot.service import owner_words as words_svc
from stackshot.service import store as _svcstore
from stackshot.service import telling
from stackshot.service import update as update_svc
from stackshot.tools import cap_words as _capw
from stackshot.tools import next_report as _nrep
from stackshot.waits import handoff as _ho
from stackshot.waits import stall as _stall
from stackshot.web import board_home
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors, get as _wt_get, route as _wt_route
from stackshot.web.auth import signin as _signin

_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
told = []      # (item, the line)
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, note))
telling.tell_kind = lambda kind, gid, owner, note, tag="wake": told.append((gid, note))
telling.tell_own_move = lambda gid, owner, note, **k: told.append((gid, note))
telling.gate_result = lambda: ("", "")
telling.tell_comment = lambda *x, **k: []
ONE = [{"name": "member-a", "emails": [ADA]}]
TWO = [*ONE, {"name": "member-b", "aliases": ["MB"], "emails": [BEA]}]
_cfg.CFG["members"] = TWO

from starlette.testclient import TestClient

COOKIE = _signin._ui_sign(json.dumps({"email": ADA, "exp": time.time() + 3600}))


def run(c, shared):
    """Every reader once; `shared`: the board has two members, so only the person's own record counts. With one member every record counts, one stamped with a name that is no member's too."""
    n = "two" if shared else "one member"

    def two(name, cond_shared, cond_one, got=None):
        check(f"{n}: {name}", cond_shared if shared else cond_one, got)

    # ---- the rule itself
    theirs, mine = b(10, "x"), a(10, "x")
    two("a record is the word of who made it", _mgates.said_by(theirs, "member-b") and not _mgates.said_by(theirs, "member-a") and _mgates.owners(mine) and not _mgates.owners(theirs) and _mgates.said_by(a(1, by="MB"), "member-b"),
        _mgates.said_by(theirs, "member-a") and _mgates.owners(theirs))

    # ---- get and the item page
    item(1, mover="member-a", needs=["alpha-build"], answers=[a(300, "ADAWORD"), b(200, "BEASTEP", "step-reply"), b(100, "BEAPICK", "decision")])
    item(2, until=LATER, needs=[], mover="alpha-build", cap_ok={"wake": LATER, "by": "a board note", "quote": "TRIPWORD", "source": "member-b's note on their step"})
    got = _wt_get.stackshot_get("a1")
    lines = re.findall(r"(?m)^- .*(?:ADAWORD|BEASTEP|BEAPICK).*$", got)
    two("get heads the answers with nobody's name", "\nanswers on the board:\n" in got and "member-a's answers on the board" not in got, "member-a's answers on the board:\n" in got, got)
    two("get names who recorded each line", len(lines) == 3 and "member-a, comment: ADAWORD" in lines[0] and "member-b, note on their step: BEASTEP" in lines[1] and "member-b, answer: BEAPICK" in lines[2],
        len(lines) == 3 and not any("member-b, " in x or "member-a, " in x for x in lines) and "note on his step: BEASTEP" in lines[1], lines)
    got = _wt_get.stackshot_get("a2")
    two("get claims the words behind a wake for nobody", f"\nwords behind the wake {LATER}" in got and "member-a's words behind" not in got, f"member-a's words behind the wake {LATER}" in got, got)
    c.cookies.set(_signin._UI_COOKIE, COOKIE)
    item(3, state="parked", until=LATER, mover="alpha-build", wait_basis=f"the trip ends {LATER}", cap_ok={"wake": LATER, "by": "a board note", "quote": "TRIPWORD", "source": "member-b's note on their step"})
    board_home._board_home_drop()
    for i in (2, 3):
        page = html.unescape(c.get(f"/items/a{i}").text)
        two(f"item a{i}'s page heads those words for nobody", "<dt>Words behind the date</dt>" in page and "<dt>His words</dt>" not in page, "<dt>His words</dt>" in page and "Words behind the date" not in page, re.findall(r"<dt>[^<]*</dt><dd>TRIPWORD", page))

    # ---- the start repair: a hand-off's end and the way back from a member stored as mover
    x = "member-b" if shared else "member-a"      # the member the items are with: with one member that is the owner, and a record stamped member-b is a name that is no member's
    ask_x = ASK_B if shared else ASK
    to_b = dict(needs=["decision"], ask=ask_x, options=OPTS, mover=x, then="alpha-build", handoff=handed(x))
    item(10, **to_b, answers=[a(900, "from the first member"), a(800, "from github", via="github", comment_id=1, url="https://example.test/1")])
    item(11, **to_b, answers=[a(900, "from the first member"), b(700, "from the member handed to"), a(600, "again")])
    item(12, needs=["alpha-build"], mover="alpha-build", handoff=handed(x), answers=[a(900, "from the first member")])
    back = dict(needs=["alpha-build"], mover=x, then="alpha-build", next="alpha-build: build it")
    item(13, **back, handoff=handed(x), answers=[a(900, "the first member's")])
    item(14, **back, handoff=handed(x), answers=[b(900, "their own")])
    item(15, updated=600, **back, handoff=handed("member-a"), answers=[b(1200, "before the item was last written")])
    item(16, updated=600, **back, handoff=handed("member-a"), answers=[b(300, "after it")])
    item(17, updated=600, **back, answers=[a(300, "the first member's")])
    item(18, updated=600, **back, answers=[b(300, "their own")])
    mig_svc.migrate_owner_mover()
    h = lambda i: meta(i).get("handoff") or {}
    ended = lambda i: bool(h(i).get("taken_at"))
    why = lambda i: json.dumps(h(i), ensure_ascii=False)
    two("repair: another member's comment, on the board or GitHub, ends no hand-off", not ended(10), ended(10) and "member-a's answer was already on the item" in why(10), h(10))
    two("repair: the answer of the member handed to ends it, at its own time, under their name", ended(11) and abs(h(11)["taken_at"] - (now - 700)) < 1 and "member-b's answer was already on the item" in why(11),
        ended(11) and abs(h(11)["taken_at"] - (now - 900)) < 1 and "member-a's answer was already on the item" in why(11), h(11))
    two("repair: a hand-off the item left names the member it went to", "it is no longer member-b's to move" in why(12), "member-a's answer was already on the item" in why(12), h(12))
    back_ = lambda i: meta(i).get("mover") == "alpha-build"
    two("repair: another member's answer is no proof the member stored as mover let the item go", not back_(13) and not back_(17), back_(13) and back_(17), (meta(13), meta(17)))
    check(f"{n}: repair: that member's own answer is", back_(14) and back_(18), (meta(14), meta(18)))
    two("repair: a hand-off to someone else does not date the way back", not back_(15), back_(15), meta(15))
    check(f"{n}: repair: an answer after the item's last write does", back_(16), meta(16))

    # ---- the reason a save ends a hand-off record with
    item(20, **to_b)
    it = rd(20)
    done = handoff_svc.handoff_his_over("a20", it, ("member-b", "board"))
    two("a board answer of the member handed to is recorded under their name", done and "member-b answered on the board" in json.dumps(it["metadata"]["handoff"]), done and "member-a answered on the board" in json.dumps(it["metadata"]["handoff"]), it["metadata"].get("handoff"))
    item(21, needs=["alpha-build"], mover="alpha-build", handoff=handed(x))
    it = rd(21)
    done = handoff_svc.handoff_his_over("a21", it, None)
    two("…and an item that left them is no longer theirs to move", done and "it is no longer member-b's to move" in json.dumps(it["metadata"]["handoff"], ensure_ascii=False),
        done and "it is no longer member-a's to move" in json.dumps(it["metadata"]["handoff"], ensure_ascii=False), it["metadata"].get("handoff"))

    # ---- the note an update's reply carries
    item(25, needs=["alpha-build"], mover="member-a", answers=[a(500, "earlier", "decision"), b(60, "LATEWORD")])
    note = update_svc._answered_since_note("a25", rd(25), "alpha-build")
    two("the reply note names who recorded the latest answer", "(note: member-b commented on" in note and "since that," in note and "his answer" not in note, "(note: member-a commented on" in note and "since his answer," in note, note)

    # ---- the ask's reminder and its check: the asked member's notes
    item(30, needs=["decision"], ask=ASK, options=OPTS, mover="member-b", answers=[a(100, "ADANOTE"), b(90, "BEANOTE")])
    pre = gates_svc.ask_pre("a30")
    remind = asks_svc._ask_after_write(pre, "alpha-build", "", False, [])
    two("the reminder quotes the asked member's notes and names them", "for member-b;" in remind and "member-b's notes since the ask: " in remind and "BEANOTE" in remind and "ADANOTE" not in remind,
        "for member-a;" in remind and "His notes since the ask: " in remind and "BEANOTE" in remind and "ADANOTE" in remind, remind)
    asked = asks_svc._ask_after_write(pre, "alpha-build", ASK, False, [])
    two("the ask-time check does too", "(check: member-b has written" in asked and "BEANOTE" in asked and "ADANOTE" not in asked, "(check: member-a has written" in asked and "ADANOTE" in asked, asked)
    item(31, needs=["decision"], ask=ASK, options=OPTS, mover="member-b", answers=[a(100, "ADANOTE")])
    asked = asks_svc._ask_after_write(gates_svc.ask_pre("a31"), "alpha-build", ASK, False, [])
    two("…and says nothing when only another member wrote", asked == "", "ADANOTE" in asked, asked)
    two("notes_since reads one member's", [x["text"] for x in _askl.notes_since(meta(30), 0, "member-a")] == ["ADANOTE"], len(_askl.notes_since(meta(30), 0, "member-a")) == 2)

    # ---- the owner's words
    item(35, until=LATER, mover="alpha-build", answers=[b(200, f"park this until {LATER}")])
    got = words_svc._owner_quote_on(rd(35), [], 14)
    two("another member's words are not the owner's behind a wake", got == ("", "", ""), got[0] == "a board answer", got)
    item(36, until=LATER, mover="alpha-build", answers=[a(300, f"park it until {LATER}"), b(200, f"park this until {LATER}")])
    got = words_svc._owner_quote_on(rd(36), [], 14)
    two("the owner's are", got[1].startswith("park it until") and got[2].startswith("member-a's comment"), got[1].startswith("park this until"), got)
    bad = refusal(lambda: words_svc._cap_words_entry("a35", {"ts": meta(35)["answers"][0]["ts"]}, rd(35)))
    two("the words job refuses another member's entry", "that entry is member-b's, not member-a's own words" in bad, bad == "", bad)
    check(f"{n}: …and takes the owner's", words_svc._cap_words_entry("a36", {"ts": meta(36)["answers"][0]["ts"]}, rd(36))[1]["text"].startswith("park it"))

    # ---- a pause, a platform key
    pause = lambda rec: _stall.authorize("a1", [rec], now)
    two("another member approves no pause", "carries no answer of member-a's" in pause(b(60, "pause it")), pause(b(60, "pause it")) == "", pause(b(60, "pause it")))
    check(f"{n}: the owner does", pause(a(60, "pause it")) == "", pause(a(60, "pause it")))
    key = {"metadata": {"answers": [a(300, kind="decision", choice="Reject"), b(100, kind="decision", choice="Approve")]}}
    got = caller_svc._decision_of(key)
    two("another member's decision approves no key", got and got[0] == "reject", got and got[0] == "approve", got)
    two("…and decides nothing alone", caller_svc._decision_of({"metadata": {"answers": [b(100, kind="decision", choice="Approve")]}}) is None, caller_svc._decision_of({"metadata": {"answers": [b(100, kind="decision", choice="Approve")]}}) is not None)

    # ---- one ask per decision
    def again(i, mover, rec):
        item(i, needs=["alpha-build"], mover="alpha-build", answers=[rec])
        m = {**meta(i), "needs": ["decision"], "ask": ASK, "mover": mover}
        return refusal(lambda: gates_svc.gate_decision_again(rd(i), m, ["alpha-build"], ASK, f"a{i}"))
    got = again(40, "member-a", b(300, "a side word"))
    two("another member's comment keeps no ask from being put", got == "", "member-a answered" in got, got)
    check(f"{n}: the asked member's answer does", "Refused: member-a answered" in again(41, "member-a", a(300, "yes")), again(41, "member-a", a(300, "yes")))
    got = again(42, "member-b", b(300, "yes"))
    two("…under the name of the member asked", "Refused: member-b answered" in got, "Refused: member-a answered" in got, got)
    two("…and says their beside that name", "back on their call" in got and "they are not asked again" in got and "Act on their answer" in got and " his " not in got,
        "back on his call" in got and "he is not asked again" in got and "Act on his answer" in got, got)

    # ---- For you, the back-fill call, the migration, the tools
    closed = lambda rec: {"status": "completed", "metadata": {"answers": [rec]}}
    two("For you is the owner's list", _fy.watched("", closed(b(60, "x")))[0] is False, _fy.watched("", closed(b(60, "x"))) == (True, "he answered on it"), _fy.watched("", closed(b(60, "x"))))
    check(f"{n}: …where their answer counts", _fy.watched("", closed(a(60, "x"))) == (True, "he answered on it"))
    both = {"status": "completed", "subject": "s", "metadata": {"answers": [a(300, "ADADONE"), b(200, "BEADONE shipped")]}}
    sent = json.loads(re.search(r"<item>\n(.*)\n</item>", _cold.build_backfill_message("a1", both, {}, []), re.S).group(1))["owner_answers"]
    two("the back-fill call gets the owner's answers", sent == ["ADADONE"], sent == ["ADADONE", "BEADONE shipped"], sent)
    two("…and so does the record's outcome text", "ADADONE" in _mig.record_text(both) and _mig.outcome_words(both) == [], "shipped" in _mig.outcome_words(both), _mig.record_text(both))
    item(45, until=LATER, mover="alpha-build", answers=[a(3000, f"park it until {LATER}"), b(2000, f"park this until {LATER}")], hold_set={"at": now - 3600, "by": "alpha-build"})
    got = _mig.park_quote(rd(45), now)
    two("the migration's park quote is the owner's", got and got["text"].startswith("park it"), got and got["text"].startswith("park this"), got)
    two("cap_words marks only the owner's entry as his", _capw.attributed(a(60, "park it")) and not _capw.attributed(b(60, "park it")), _capw.attributed(b(60, "park it")))
    load = _capw.load
    _capw.load = lambda number: {"status": "completed", "subject": "s", "metadata": {"answers": [b(60, "park it")]}}
    try:
        shown = "\n".join(_capw.plan_a(1, "", now)["lines"])
    finally:
        _capw.load = load
    two("…and names whose another is", "member-b's, not his" in shown, "member-b's" not in shown and "HIS" in shown, shown)
    ticked = {"status": "open", "metadata": {"owner": BUILD_S, "steps": _steps.stored([{"text": "member-b: sign QUILL", "status": _steps.DONE, "by": "alpha-build", "at": now - 10}])}}
    n4 = lambda rec: [r for r in _nrep.check_item({**ticked, "metadata": {**ticked["metadata"], "answers": [rec]}}) if r[0] == "N4"]
    two("N4: another member's words show no tick of this member's step", len(n4(a(60, "ok"))) == 1, n4(a(60, "ok")) == [], n4(a(60, "ok")))
    check(f"{n}: N4: the step's member's own do", n4(b(60, "ok")) == [], n4(b(60, "ok")))
    past = {"owner": BUILD_S, "mover": "member-a", "answers": [b(300, kind="decision", choice="Ship it", ask=ASK)]}
    _nbf.apply(past, _nbf.plan(past))
    ticks = [(t["by"], t["text"]) for t in _steps.view(past) if t["status"] == _steps.DONE]
    two("a past decision filled in is marked done by who decided, under their name", len(ticks) == 1 and ticks[0][0] == "member-b" and ticks[0][1].startswith("member-b: "),
        len(ticks) == 1 and ticks[0][0] == "member-a" and ticks[0][1].startswith("member-a: "), ticks)
    done_a = _steps.stored([{"text": "member-a: ship ZEBRAWORD on Friday → Ship it", "status": _steps.DONE, "by": "member-a", "at": now - 300}])
    past = {"owner": BUILD_S, "mover": "member-a", "steps": done_a, "answers": [b(300, kind="decision", choice="Ship it", ask=ASK)]}
    add, have = _nbf.audit(past)
    two("…and another member's done step is no record of this decision", len(add) == 1 and have == [], add == [] and len(have) == 1, (add, have))

    # ---- the answer line, a second member's same note
    line = lambda rec: handover_svc._answer_line({"metadata": {"answers": [rec]}}).split("\t")
    two("the answer line names who answered, after the words of a decision", line(b(60, "ok", "decision", choice="Ship it"))[:3] == ["decision", "Ship it", "ok"] and line(b(60, "ok", "decision", choice="Ship it"))[4:] == ["member-b"] and line(a(60, kind="decision", choice="Ship it"))[4:] == ["member-a"],
        line(b(60, "ok", "decision", choice="Ship it"))[2] == "ok" and line(a(60, kind="decision", choice="Ship it"))[2] == "", line(b(60, "ok", "decision", choice="Ship it")))
    item(50, status="completed")
    codes = [answer_svc._answer("a50", "", "SAMEWORDS", "comment", by=who) for who in ("member-a", "member-b", "member-b")]
    got = [(x.get("by", "member-a"), x["text"]) for x in meta(50).get("answers", [])]
    two("the same note from two members is kept twice, a repeat of one once", codes == ["closednote"] * 3 and got == [("member-a", "SAMEWORDS"), ("member-b", "SAMEWORDS")], codes == ["closednote"] * 3 and len(got) == 1, (codes, got))

    # ---- the words behind a park and the escalation name who answered
    item(55, state="your-step", step=f"{x}: sign HERON", mover=x, then="alpha-build", next="alpha-build: carry on")      # once the note is in, the item names no member: its person is then the first
    code = answer_svc._answer("a55", "", "I will do it next week", "note", by="member-b")
    src = str((meta(55).get("cap_ok") or {}).get("source"))
    two("a park from a step note names whose note", src.startswith("member-b's note on their step, "), src.startswith("member-a's note on his step, "), (code, src, meta(55)))
    item(56, needs=["decision"], ask=ask_x, options=OPTS, mover="member-a", then="alpha-build")      # the member asked is not the stored mover
    code = answer_svc._answer("a56", "Park it", "", "answer", by="member-b")
    src = str((meta(56).get("cap_ok") or {}).get("source"))
    two("a park from a pick names who picked", src.startswith("member-b's answer on the board, "), src.startswith("member-a's answer on the board, "), (code, src))
    item(57, needs=["decision"], ask=ask_x, options=OPTS, mover=x, then="alpha-build")
    answer_svc._answer("a57", "Ship it", "", "answer", by="member-b")
    told.clear()
    answer_svc._answer_tick(time.time() + 86400)
    got = " ".join(t for g, t in told if g == "a57")
    two("the escalation names who answered", "member-b answered" in got and "see that the answer is acted on" in got, "member-a answered" in got and "see that his answer is acted on" in got, got)


with TestClient(server.mcp.http_app(), base_url=BOARD, raise_server_exceptions=False) as c:
    run(c, True)
    _cfg.CFG["members"] = ONE
    board_home._board_home_drop()
    check("a board of one member is not one of several", not _mgates.many())
    run(c, False)

print(("ok" if not fails else "FAILED") + f": member words scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
