"""Scenario test for who an answer, a tick and a kept note are recorded under (stage 3 of the several-people plan): fixture data, the answer route through
Starlette's test client, no live store, no network.

A board with one person is unchanged: an answer, a tick and a note record no `by`, the revision's author is that person, and History shows that person. With a second
person on the list, the route passes the signed-in person to the answer path, and then
  - the answer record carries `by` (its name), written only when the person is not the first: a record with none reads as the first person's;
  - the tick of his step (the Done, the server's own step ticked by his note, his decision) and the checklist line it ticks carry that person as `by`;
  - a note kept on a closed item, or on a question that changed, carries `by`, and the save's author (the item's written_by) is that person;
  - a mail tick is the server's own: no `by`, the author stays the server;
  - a GitHub comment carries no `by` (the one login the reader follows is the first person's): History shows the first person;
  - History and the decision rows read `by`, else the first person.

    tests/run-suite answer_author  → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="answerauthor-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
EMAIL, EMAIL2 = "oliver@example.org", "pat@example.org"


def write_toml():
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml = _instance.set_person(toml)
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                     (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                     (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false'),
                     (r'(?m)^sync = false', 'sync = true'), (r'(?m)^issues_repo = ""', 'issues_repo = "o/r"'),
                     (r'(?m)^api_url = "[^"]*"', 'api_url = "http://127.0.0.1:9"'), (r'(?m)^token_file = ""', f'token_file = "{tmp}/github.token"')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")


write_toml()
(T / "github.token").write_text("test-token\n")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchors","brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER_S = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER_S: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-agent", "agents": {"home-here": "builds it"}, "back_agents": {"home-here": "builds it"}, "status": "active", "board": [], "board_open": 0}}}))
DESC = "A thing. It lives here. Finished when it works."
ASK = "Decide: whether to ship · Recommend: yes · Stakes: none either way · By: no date"
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True},
        {"label": "Drop", "line": "Drop the feature", "recommended": False}]
STEP = "run the one line to reauth the box"
STEP4 = "Run the 8 run deletions yourself: my delete call is refused by the permission layer"


def item(i, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": DESC, "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER_S, "project": "projects/alpha", "next": "the next step", **meta}}))


item(1, needs=["decision", "home-agent"], ask=ASK, options=OPTS)           # a decision, picked by the second person
item(2, needs=["decision"], ask=ASK, options=OPTS)                         # the same, picked by the first person
item(3, state="your-step", step=STEP, needs=["home-agent"])                # a Done by the second person
item(4, needs=["home-agent"], next="home-agent: confirm the runs are gone")      # a step the server makes for him, ticked by a note
item(5, status="completed", outcome="done", reason="it worked")           # a note on a closed item
item(6, needs=["home-agent"])                                              # a pick on a question that changed, with a note
item(7, needs=["home-agent"])                                              # a comment
item(8, state="your-step", step=STEP, needs=["home-agent"])                # a mail tick
item(9, needs=["decision"], ask=ASK, options=OPTS)                         # a direct caller that names no person
item(10, needs=["home-agent"])                                             # a GitHub comment
item(11, needs=["home-agent"])                                             # History: records with and without `by`
item(12, needs=["home-agent"])                                             # History: GitHub comments with and without `by`
(T / "store/next-id").write_text("20"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
def snap(msg): git("add", "-A"); git("commit", "-q", "--allow-empty", "-m", msg)
logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def wr(i, d): (T / f"store/a/{i}.json").write_text(json.dumps(d))
STORE = T / "store"

from stackshot.web import server
from stackshot.core import people as _people
from stackshot.core.instance import NAME
from stackshot.service import answer as answer_svc
from stackshot.service import github_events as ghev_svc
from stackshot.service import telling
from stackshot.service import store as _service_store
from stackshot.model import owner_steps as _hs
from stackshot.web import answers as _web_answers
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route, update as _wt_update
from stackshot.web.auth import signin as _signin
from stackshot.web.ui import render as ui_render
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, owner, note, tag))
telling.tell_comment = lambda *a, **k: []

OLIVER = _people.first()
PAT = _people.Person("Pat", (), (EMAIL2,))
check("the fixture: one person, Oliver, and the list is read through the one reader", [p.name for p in _people.people()] == ["Oliver"] and OLIVER.name == "Oliver")
# the pure helpers, with one person
check("one person: stamp writes nothing, recorded_by reads the first person, signed_in is the first person for any address",
      _people.stamp({"a": 1}, "Oliver") == {"a": 1} and _people.recorded_by({"a": 1}) == "Oliver" and _people.recorded_by({"by": "  Pat  x "}) == "Pat x"
      and _people.signed_in("anyone@example.org").name == "Oliver" and _people.signed_in(EMAIL).name == "Oliver" and _people.recorded_by(None) == "Oliver")

# a second person, for the rest of the run (the config takes one person; the list is what every module asks)
_people.people = lambda: [OLIVER, PAT]
check("two persons: stamp writes the second person only, recorded_by reads `by` else the first, signed_in picks by address and falls back to the first",
      _people.stamp({}, "Pat") == {"by": "Pat"} and _people.stamp({}, "Oliver") == {} and _people.stamp({}, "") == {} and _people.recorded_by({"by": "Pat"}) == "Pat"
      and _people.recorded_by({}) == "Oliver" and _people.signed_in(EMAIL2).name == "Pat" and _people.signed_in(EMAIL).name == "Oliver" and _people.signed_in("x@example.org").name == "Oliver")

from starlette.testclient import TestClient
COOKIE1 = _signin._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
COOKIE2 = _signin._ui_sign(json.dumps({"email": EMAIL2, "exp": time.time() + 3600}))
tok = lambda g, email=EMAIL: _web_answers._answer_token(email, g)
SAME = {"Origin": BOARD}
steps_of = lambda i: _hs._steps.view(rd(i)["metadata"], keeper=_service_store._load(f"a{i}").get("metadata", {}).get("owner") or "")
done_by = lambda i: [(x["status"], x["by"]) for x in steps_of(i) if x["status"] == "done"]

with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def post(i, data, cookie, email):
        c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, cookie)
        return c.post(f"/items/a{i}/answer", data={"token": tok(f"a{i}", email), **data}, headers=SAME, follow_redirects=False)
    pat = lambda i, data: post(i, data, COOKIE2, EMAIL2)
    oli = lambda i, data: post(i, data, COOKIE1, EMAIL)

    # ---- 1. a decision
    r1 = pat(1, {"choice": "Ship", "text": "go"}); a1 = rd(1)
    check("a decision picked by the second person: recorded with `by`, the record otherwise as ever",
          r1.status_code == 303 and r1.headers["location"] == "/items/a1?sent=decision" and [(a["kind"], a["choice"], a["text"], a["via"], a.get("by")) for a in a1["metadata"]["answers"]] == [("decision", "Ship", "go", "board", "Pat")],
          (r1.headers.get("location"), a1["metadata"].get("answers")))
    check("…the save's author is that person, and the step line his answer ticked is ticked by him", a1["written_by"] == "Pat" and done_by(1) and all(b == "Pat" for _s, b in done_by(1)), (a1.get("written_by"), done_by(1)))
    r2 = oli(2, {"choice": "Ship", "text": "go"}); a2 = rd(2)
    check("the same pick by the first person: no `by` on the record (a board with one person is written as it always was), the author and the tick are him",
          r2.headers["location"] == "/items/a2?sent=decision" and all("by" not in a for a in a2["metadata"]["answers"]) and a2["written_by"] == "Oliver" and done_by(2) and all(b == "Oliver" for _s, b in done_by(2)),
          (a2["metadata"].get("answers"), a2.get("written_by"), done_by(2)))
    check("…and the two records differ in the one key `by` and the text of the tick's author",
          {k: v for k, v in a1["metadata"]["answers"][0].items() if k not in ("ts", "by", "told")} == {k: v for k, v in a2["metadata"]["answers"][0].items() if k not in ("ts", "by", "told")},
          (a1["metadata"]["answers"][0], a2["metadata"]["answers"][0]))

    # ---- 2. a Done, and a note on his step
    r3 = pat(3, {"act": "done", "text": "ran it, it said ok"}); a3 = rd(3)
    check("a Done by the second person: the answer has `by`, the checklist line it checked is done by him, the author is him, the item went on to its then-mover",
          r3.headers["location"].startswith("/items/a3?sent=donenote") and [(a["kind"], a["choice"], a.get("by")) for a in a3["metadata"]["answers"]] == [("decision", "Done", "Pat")]
          and done_by(3) == [("done", "Pat")] and a3["written_by"] == "Pat" and "step" not in a3["metadata"], (r3.headers.get("location"), a3["metadata"], done_by(3)))
    _wt_update.stackshot_update("a4", sender="home-agent", step=STEP4, mover="Oliver", next="home-agent: confirm the runs are gone\nOliver: `for id in 1 2; do echo $id; done`")
    check("setup: the server made his step on item 4 (owner_step)", rd(4)["metadata"].get("owner_step") == f"Oliver: {STEP4}", rd(4)["metadata"].get("owner_step"))
    r4 = pat(4, {"act": "note", "text": "tried it, it says forbidden"}); a4 = rd(4)
    mine = [(x["status"], x["by"]) for x in steps_of(4) if x["text"].startswith(f"Oliver: {STEP4}")]
    check("a note on his step by the second person: the answer has `by` (kind step-reply), the server's step is ticked by him, the author is him",
          r4.headers["location"].startswith("/items/a4?sent=stepreply") and [(a["kind"], a.get("by")) for a in a4["metadata"]["answers"]] == [("step-reply", "Pat")] and mine == [("done", "Pat")]
          and a4["written_by"] == "Pat", (r4.headers.get("location"), a4["metadata"].get("answers"), mine))

    # ---- 3. a kept note: a closed item, a question that changed, a comment
    r5 = pat(5, {"act": "comment", "text": "late"}); a5 = rd(5)
    check("a note on a closed item by the second person is kept as his comment with `by`, the author is him, the item stays closed",
          r5.headers["location"] == "/items/a5?sent=closednote" and a5["status"] == "completed" and [(a["kind"], a["text"], a.get("by")) for a in a5["metadata"]["answers"]] == [("comment", "late", "Pat")]
          and a5["written_by"] == "Pat", (r5.headers.get("location"), a5["metadata"].get("answers"), a5.get("written_by")))
    r5b = oli(5, {"act": "comment", "text": "later still"}); a5b = rd(5)
    check("…and the first person's note on it has none, the author is him", r5b.headers["location"] == "/items/a5?sent=closednote" and [a.get("by") for a in a5b["metadata"]["answers"]] == ["Pat", None]
          and a5b["written_by"] == "Oliver", (a5b["metadata"].get("answers"), a5b.get("written_by")))
    r6 = pat(6, {"choice": "Ship", "text": "my words", "act": "answer"}); a6 = rd(6)
    check("a pick on a question that changed, with a note: the note is kept as his comment with `by`, the author is him",
          r6.headers["location"] == "/items/a6?sent=stalenote" and [(a["kind"], a["text"].endswith("my words"), a.get("by")) for a in a6["metadata"]["answers"]] == [("comment", True, "Pat")] and a6["written_by"] == "Pat",
          (r6.headers.get("location"), a6["metadata"].get("answers"), a6.get("written_by")))
    r7 = pat(7, {"act": "comment", "text": "a thought"}); a7 = rd(7)
    check("a comment by the second person: `by` on the record, the author is him; the item's needs stay",
          r7.headers["location"] == "/items/a7?sent=comment" and [(a["kind"], a.get("by")) for a in a7["metadata"]["answers"]] == [("comment", "Pat")] and a7["written_by"] == "Pat" and a7["metadata"]["needs"] == ["home-agent"],
          (r7.headers.get("location"), a7["metadata"]))

    # ---- 4. what is not a person's answer: a mail tick, a direct caller, a GitHub comment
    clock = float(rd(8)["state_updated"])
    r8 = answer_svc._answer("a8", "", "", "done", via="mail", mail={"step": STEP, "since": clock, "note": "a mail he sent fits it"}, by="Pat"); a8 = rd(8)
    check("a mail tick is the server's own: no `by` even when a person is named, the author stays the server, the checklist line is ticked by the first person as ever",
          r8 == "done" and [(a["via"], a.get("choice")) for a in a8["metadata"]["answers"]] == [("mail", "Done")] and all("by" not in a for a in a8["metadata"]["answers"]) and a8["written_by"] == NAME,
          (r8, a8["metadata"].get("answers"), a8.get("written_by")))
    r9 = answer_svc._answer("a9", "Ship", "", "answer"); a9 = rd(9)
    check("a caller that names no person records the first person: no `by`, the author and the tick are him",
          r9 == "decision" and all("by" not in a for a in a9["metadata"]["answers"]) and a9["written_by"] == "Oliver" and done_by(9) and all(b == "Oliver" for _s, b in done_by(9)), (r9, a9["metadata"].get("answers"), done_by(9)))
    check("a GitHub comment records no `by` while one login is followed (the first person's)",
          ghev_svc._github_comment("a10", {"id": 555, "ts": time.time(), "text": "from github", "url": "https://example.test/c"}) is True
          and [(a["via"], a.get("by")) for a in rd(10)["metadata"]["answers"]] == [("github", None)], rd(10)["metadata"].get("answers"))

    # ---- 5. History and the decision rows read `by`, else the first person
    d11, d12 = rd(11), rd(12)
    d11["metadata"]["answers"] = [{"ts": now - 50, "kind": "decision", "choice": "Ship", "choice_line": "Ship it now as it is", "via": "board"},
                                  {"ts": now - 40, "kind": "decision", "choice": "Wait", "choice_line": "Wait for the next release", "via": "board", "by": "Pat"},
                                  {"ts": now - 30, "kind": "comment", "text": "old words", "via": "board"}, {"ts": now - 20, "kind": "comment", "text": "pat words", "via": "board", "by": "Pat"}]
    d12["metadata"]["answers"] = [{"ts": now - 50, "kind": "comment", "text": "gh one", "via": "github", "url": "https://example.test/1", "comment_id": 1},
                                  {"ts": now - 40, "kind": "comment", "text": "gh two", "via": "github", "url": "https://example.test/2", "comment_id": 2, "by": "Pat"}]
    for i_, d_ in ((11, d11), (12, d12)):
        wr(i_, d_); snap(f"history {i_}")
    snap("answers")
    B = ui_render.Board(str(STORE))
    rows = B.decision_rows(rd(11), [])
    check("the decision rows name the person who decided: `by`, else the first person", [(r["text"], r["by"]) for r in rows] == [("Oliver: picked Ship (Ship it now as it is)", "Oliver"), ("Pat: picked Wait (Wait for the next release)", "Pat")], rows)
    h11 = B.item_html("a11")
    check("History: a board answer and a comment show their person, a record with no `by` shows the first person",
          "Oliver (board): <b>Ship</b>" in h11 and "Pat (board): <b>Wait</b>" in h11 and "Oliver (board): old words" in h11 and "Pat (board): pat words" in h11, re.findall(r'<li class="ev ev-answer">.*?</li>', h11))
    h12 = B.item_html("a12")
    check("History: a GitHub comment shows the first person when it has no `by`, the person when it has one", "Oliver commented" in h12 and "Pat commented" in h12,
          re.findall(r'commented[^<]{0,40}', h12))
    h1 = B.item_html("a1"); h2 = B.item_html("a2")
    check("History of the answers made above: the second person's pick shows Pat, the first person's shows Oliver, each under its author",
          "Pat (board): <b>Ship</b>" in h1 and "Oliver (board): <b>Ship</b>" in h2 and "<b>Pat</b>" in h1 and "<b>Pat</b>" not in h2, (re.findall(r'<li class="ev ev-answer">.*?</li>', h1), re.findall(r'<li class="ev ev-answer">.*?</li>', h2)))

print(("ok" if not fails else "FAILED") + f": answer author scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
