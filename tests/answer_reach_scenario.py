"""Scenario test for: his board answer reaches the item's contact and the front agents he is talking to, as a held line and never a turn of its own, and a session that writes with an older picture of the item is told so.
Fixture data, no live store, no network, no tmux: the push is a fake script that logs what it was given; the front gate and the held store are the real ones.

  1  an answer on an item reaches the item's contact when that session is not in the item's needs: a held line for its next turn (no push, no mark), the same line the sessions in the needs get, handed over once; the sessions in
     the needs are pushed as before; the pending answer lists only the sessions that hold the item, so a contact's write does not settle it
  2  a session that is both in the needs and the contact is told once, by the needs path
  3  a front agent he talked to 10 minutes ago, which the item does not name, gets the held line; the same agent 31 minutes ago does not; the window is the presence window (the one constant); a background agent he wrote to does not
  4  a contact that is a background agent gets the plain push; an item with no contact to name is unchanged; an item with no stored contact reaches its project's -main agent; a front agent whose hook cannot fetch held lines is
     told nothing, as the front gate does for any fyi; a long answer is cut to the store's line limit with the link kept
  5  a comment and a Done on his step reach them too; two answers wait together and are handed over in one turn, oldest first
  6  an update by a session that has not written since his answer carries the line (his words and their time) and still applies; a session that wrote after his answer, an item he never answered and a write with no
     session behind it carry none; a close carries it too
  7  a session the answer was handed to (the told list kept on the answer's own record: a decision, a comment, two sessions writing in turn, after the escalation dropped the pending answer) is not told its own news on its first write; one that was not told is
  8  a front agent is never sent the plain push: when the gate fails, when the role read fails, nobody is told and the contact's History line stays; a front agent that is no contact leaves no History line on the item
  9  the line leans toward silence when the item's history cannot be read in full: more than 60 newer revisions, a store outside git
 10  a contact that is also a front agent he is talking to now is told once
 11  after his answer the project's builder moves an item whose needs name a front agent (the front agent stays in needs and is handed a held line, never a push); a project with no builder, a builder that cannot take the item,
     a stored then that is the front agent, and a comment, keep what they had or follow the same rule

    tests/run-suite answer_reach        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging, subprocess
SCR =os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="answerreach-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai"), ("fleet_names", f"{tmp}/names.tsv")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("state", "store/a", "fleet/a", "brain/projects", "transcripts/-home-x", "cli", "secrets"): (T / d).mkdir(parents=True)
NAMES = ("demo-main", "demo-lead", "demo-side", "demo-builder", "demo-peer", "demo-keeper", "demo-solo")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
def proj(session, agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
# alpha: front demo-main (its -main agent) and demo-lead, background demo-builder (builds); beta: front demo-side; gamma: one background agent and no front agent
ALPHA = {"demo-main": "the front", "demo-lead": "the second front", "demo-builder": "builds, merges and releases the code"}
BETA = {"demo-side": "the front"}
GAMMA = {"demo-peer": "keeps the pages"}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": proj("demo-keeper", ALPHA, {"demo-builder": ALPHA["demo-builder"]}),
    "projects/beta": proj("demo-solo", BETA, {}),
    "projects/gamma": proj("demo-keeper", GAMMA, GAMMA)}}))
for key, name, agents, back in (("alpha", "demo-keeper", ALPHA, ["demo-builder"]), ("beta", "demo-solo", BETA, []), ("gamma", "demo-keeper", GAMMA, ["demo-peer"])):
    front = [k for k in agents if k not in back]
    (T / f"brain/projects/{key}.md").write_text(f"---\ntitle: {key}\ndisplay-name: {name}\nagents:\n" + "".join(f"  {k}: {agents[k]}\n" for k in front)
                                                 + ("  background:\n" + "".join(f"    {k}: {agents[k]}\n" for k in back) if back else "") + f"---\n\n# {key}\n\n## Current state\n\nSTATE-OF-{key.upper()}: open.\n\n<!-- timeline -->\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "--allow-empty", "-m", "fixture")      # the store is under git, as the board's is: a session's earlier writes are read from its revisions
DESC = "- A thing\n- It lives here\n- Done when done"
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True}]
STEP = "run the one line `deploy it` on the box"
def item(i, project="projects/alpha", mover="demo-builder", **meta):
    base = {"owner": U["demo-peer"], "project": project, "next": f"{mover}: do the thing", "mover": mover}
    base.update(meta)
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": "open", "updated": now0 - 7200, "state_updated": now0 - 7200,
                                                      "confirmed": now0 - 7200, "written_by": "demo-lead", "written_by_id": U["demo-lead"], "written_at": now0 - 7200, "metadata": base}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
from stackshot.core import config as _config
from stackshot.service import answer as answer_svc, update as update_svc, telling, handoff as handoff_svc
from stackshot.waits import held
from stackshot.router import routing
from stackshot.service import contacts as contacts_svc, github_events as ghev
from stackshot.web import publish as _web_publish, page_debts as _web_page_debts
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
PUSHLOG = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
THREADS = []
_real_tell = telling.tell_woken
def _tell(gid, who, note, tag="wake", result=None):
    th = _real_tell(gid, who, note, tag)
    if th: THREADS.append(th)
    return th
telling.tell_woken = _tell
def drain():
    while THREADS: THREADS.pop(0).join(30)
def pushes(): return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
handoff_svc.CLI_SESSIONS = T / "cli"
def cli_row(who):
    """The CLI's own registry row of a pane on this box: an interactive pane with its sessionId."""
    (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": U[who], "name": who, "status": "idle", "startedAt": int((now0 - 3600) * 1000),
                                                                  "statusUpdatedAt": int((now0 - 75) * 1000), "updatedAt": int((now0 - 75) * 1000)}))
def stamp(who, age=60.0):
    """The prompt hook's stamp file for a pane: epoch seconds of his last prompt in it, `age` seconds ago."""
    p = T / "state/prompts" / U[who]; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{time.time() - age:.0f}\n")
def unstamp(who): (T / "state/prompts" / U[who]).unlink(missing_ok=True)
for n in NAMES: cli_row(n)
_config.CFG["model"] = {}
_config.CFG.pop("presence", None)

LOGGED = []
_real_log = telling._front_held_log
telling._front_held_log = lambda gid, who, kind, reason, note, **kw: (LOGGED.append((gid, who)), _real_log(gid, who, kind, reason, note, **kw))[1]
def answer(gid, *a):
    """One answer through the real `_answer` and the real tell_woken (the fake push) and the real front gate → (what happened, {name: [notes pushed to it]}, {name: the text its next turn is handed from the held store})."""
    p0 = len(pushes()); h0 = {n: held.count(U[n]) for n in NAMES}
    out = answer_svc._answer(gid, *a); drain()
    got = {}
    for who, note in pushes()[p0:]:
        got.setdefault(next((n for n, u in U.items() if u == who), who), []).append(note)
    kept = {n: held.take(U[n]) for n in NAMES if held.count(U[n]) > h0[n]}
    return out, got, kept
ASK = "Decide: whether to ship · Recommend: ship · Stakes: a day · By: no date"
FRONTS = ("demo-main", "demo-lead", "demo-side")
for n in FRONTS: held.mark_client(U[n], n)      # the hooks of the front panes fetch held lines (the gate's rollout test)

# ================================================================ 1. the contact, not in the needs
item(1, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-lead")
out, got, kept = answer("a1", "Ship", "go now", "answer")
check("1 the answer is recorded as a decision", out == "decision" and rd(1)["metadata"]["answers"][-1]["choice"] == "Ship", out)
check("1 the session in the needs hears it, once, as before: a push, unmarked", len(got.get("demo-builder", [])) == 1 and got["demo-builder"][0].startswith("[stackshot] Oliver answered a1 on the board: Ship — go now"), got)
check("1 the contact, not in the needs, is handed it as a held line: no push, so no turn of its own", "demo-lead" not in got and set(got) == {"demo-builder"} and "demo-lead" in kept, (got, kept))
check("1 …the held line is the same line, with his words and the item's link, and carries no mark", got["demo-builder"][0] in kept.get("demo-lead", "") and "[for Oliver]" not in kept.get("demo-lead", ""), kept)
check("1 …it is handed over once: the next turn finds the store empty", held.count(U["demo-lead"]) == 0 and held.take(U["demo-lead"]) == "")
check("1 the project's -main agent, not named by the item and not in conversation, is told nothing", "demo-main" not in kept and "demo-main" not in got, (got, kept))
check("1 the pending answer lists the session that holds the item, not the contact (its write must not settle it)",
      json.loads((T / "state/answers.json").read_text())["a1"]["told"] == [U["demo-builder"]], (T / "state/answers.json").read_text())
check("1 the front gate left its board line on the item, as for any held notice to a front agent", "demo-lead" in json.dumps(rd(1)["metadata"].get("front_quiet")), rd(1)["metadata"].get("front_quiet"))

# ================================================================ 2. both in the needs and the contact: once, by the needs path
item(2, needs=["decision", "demo-builder", "demo-lead"], ask=ASK, options=OPTS, contact="demo-lead")
out, got, kept = answer("a2", "Ship", "", "answer")
check("2 a front agent in the needs and the contact is told once, as a held line (the builder holds the item, so no push starts a turn of its own)", "demo-lead" not in got and kept.get("demo-lead", "").count("answered a2") == 1 and len(got.get("demo-builder", [])) == 1, (got, kept))

# ================================================================ 3. the front agent he is talking to now
item(3, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-lead")
stamp("demo-side", 10 * 60)
out, got, kept = answer("a3", "Ship", "go", "answer")
check("3 a front agent of another project he talked to 10 minutes ago, not on the item, is handed it as a held line, no push", "demo-side" in kept and "demo-side" not in got and got["demo-builder"][0] in kept.get("demo-side", ""), (got, kept))
FQ3 = json.dumps(rd(3)["metadata"].get("front_quiet"))
check("3 only the contact leaves a History line on the item: a front agent of another project he talks to has the routing-log line alone", "demo-lead" in FQ3 and "demo-side" not in FQ3, FQ3)
check("3 …the routing-log line is written for it all the same", ("a3", U["demo-side"]) in LOGGED, LOGGED)
check("3 …and the contact and the session in the needs are told as in 1", "demo-lead" in kept and len(got.get("demo-builder", [])) == 1 and set(got) == {"demo-builder"} and set(kept) == {"demo-lead", "demo-side"}, (got, kept))
item(4, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-lead")
stamp("demo-side", 31 * 60)
out, got, kept = answer("a4", "Ship", "go", "answer")
check("3 the same agent 31 minutes after his last message is not told (the presence window is 30 minutes)", "demo-side" not in kept and "demo-side" not in got and set(kept) == {"demo-lead"}, (got, kept))
item(5, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-lead")
stamp("demo-side", 29 * 60); stamp("demo-peer", 60)     # a background agent he wrote to is no front agent: not reached by the window
_config.CFG["presence"] = {"minutes": 5}
out, got, kept = answer("a5", "Ship", "go", "answer")
check("3 the window is the presence constant: with [presence] minutes = 5 a 29 minute old stamp is out", "demo-side" not in kept and "demo-peer" not in got and "demo-peer" not in kept, (got, kept))
_config.CFG.pop("presence", None)
item(6, needs=["decision"], ask=ASK, options=OPTS, contact="demo-lead")
stamp("demo-side", 20 * 60); stamp("demo-peer", 60)
out, got, kept = answer("a6", "Ship", "go", "answer")
check("3 a background agent he talked to is not told for that (only a front agent is reached by the window)", "demo-peer" not in got and "demo-peer" not in kept and "demo-side" in kept, (got, kept))
unstamp("demo-side"); unstamp("demo-peer")

# ================================================================ 4. a background contact, no contact at all, no stored contact; what the front gate does when it cannot hold
item(7, needs=["decision", "demo-builder"], ask=ASK, options=OPTS)
_real_contact_of = contacts_svc._contact_of
contacts_svc._contact_of = lambda meta: "demo-peer"        # a contact the roles do not list as a front agent: a background agent
out, got, kept = answer("a7", "Ship", "go", "answer")
contacts_svc._contact_of = _real_contact_of
check("4 a contact that is a background agent is told as the sessions in the needs are: the plain push, no mark, no held line", got.get("demo-peer") == got.get("demo-builder") and len(got.get("demo-peer", [])) == 1 and not got["demo-peer"][0].startswith("[for ") and "demo-peer" not in kept, (got, kept))
item(8, project="projects/gamma", mover="demo-peer", needs=["decision", "demo-peer"], ask=ASK, options=OPTS)
out, got, kept = answer("a8", "Ship", "go", "answer")
check("4 a project that lists no front agent and an item with no contact: only the session in the needs is told, as before", set(got) == {"demo-peer"} and len(got["demo-peer"]) == 1 and not kept, (got, kept))
item(9, needs=["decision", "demo-builder"], ask=ASK, options=OPTS)
out, got, kept = answer("a9", "Ship", "go", "answer")
check("4 an item with no stored contact reaches its project's -main agent (the contact as the board reads it), as a held line, once", set(kept) == {"demo-main"} and set(got) == {"demo-builder"}, (got, kept))
item(15, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-lead")
_real_can = held.can_fetch
held.can_fetch = lambda target, now=None: False      # a front pane whose hook does not fetch held lines (a cloud session, an old checkout)
out, got, kept = answer("a15", "Ship", "go", "answer")
held.can_fetch = _real_can
check("4 a front agent whose hook cannot fetch held lines: what the front gate does for any fyi, nobody told (no push, no held line); the board's History line stays",
      "demo-lead" not in got and "demo-lead" not in kept and "demo-lead" in json.dumps(rd(15)["metadata"].get("front_quiet")), (got, kept, rd(15)["metadata"].get("front_quiet")))
item(16, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-lead")
out, got, kept = answer("a16", "Ship", "word " * 120, "answer")
last = (kept.get("demo-lead", "").splitlines() or [""])[-1]
check("4 a long answer: the held line is cut to the store's line limit, his words cut and the item's link kept", len(last.split(" · ", 2)[-1]) <= held.LINE_MAX and last.rstrip().endswith("/items/a16") and "…" in last, last)

# ================================================================ 5. everything `_answer` records, and two answers in one hand-over
item(10, needs=["demo-builder"], contact="demo-lead")
out, got, kept = answer("a10", "", "a question about it", "comment")
check("5 a comment reaches the contact too, as a held line with the comment's own words", out == "comment" and "commented on a10 on the board: a question about it" in kept.get("demo-lead", "") and "demo-lead" not in got and len(got.get("demo-builder", [])) == 1, (got, kept))
item(11, state="your-step", step=STEP, needs=["demo-builder"], contact="demo-lead")
out, got, kept = answer("a11", "", "", "done")
check("5 a Done on his step reaches the contact as a held line saying he did his step", out == "done" and "did his step on a11" in kept.get("demo-lead", "") and "demo-lead" not in got and len(got.get("demo-builder", [])) == 1, (out, got, kept))
check("5 …and the contact is not told it is the item's now", "It's yours now" not in kept.get("demo-lead", ""), kept)
item(17, needs=["demo-builder"], contact="demo-lead"); item(18, needs=["demo-builder"], contact="demo-lead")
answer_svc._answer("a17", "", "first thing", "comment"); answer_svc._answer("a18", "", "second thing", "comment"); drain()
txt = held.take(U["demo-lead"])
check("5 two answers wait together: one hand-over, oldest first, one line each (the store's own form)", txt.startswith("[stackshot] 2 notices held for you") and txt.index("first thing") < txt.index("second thing") and txt.count("\n- ") == 2, txt)

# ================================================================ 6. an update by a session whose picture is older than his answer
def upd(gid, who, **kw):
    return update_svc.update_item(gid, sender=who, **kw)
item(12, needs=["decision", "demo-builder"], ask="Decide: whether to ship · Recommend: ship · Stakes: a day · By: no date", options=OPTS, contact="demo-lead")
answer("a12", "Ship", "go now", "answer")
ts12 = rd(12)["metadata"]["answers"][-1]["ts"]
out = upd("a12", "demo-peer", priority="p3")
LINE = re.compile(r"\(note: Oliver answered a12 on the board at \w{3} \w{3} \d+\w\w \d\d:\d\d [^:]*: Ship — go now\. You have not written to the item since")
check("6 a session that has not written since his answer: the reply carries one line naming the answer, its time and his words", len(LINE.findall(out)) == 1 and out.count("\n(note: Oliver answered") == 1, out)
check("6 …and the update applied", rd(12)["metadata"].get("priority") == "p3" and rd(12)["written_by"] == "demo-peer" and rd(12)["written_at"] > ts12, rd(12))
out = upd("a12", "demo-peer", priority="p2")
check("6 a session that wrote after his answer: no line", "Oliver answered" not in out and rd(12)["metadata"].get("priority") == "p2", out)
item(13, needs=["demo-builder"])
out = upd("a13", "demo-lead", priority="p3")
check("6 an item he never answered: no line", "Oliver answered" not in out and "Oliver commented" not in out and rd(13)["metadata"].get("priority") == "p3", out)
item(14, needs=["demo-builder"], contact="demo-lead")
answer("a14", "", "keep it small", "comment")
out = upd("a14", "demo-peer", priority="p3")
check("6 a comment of his counts too, worded as a comment", "Oliver commented on a14 on the board at" in out and "keep it small" in out, out)
out = upd("a14", "", priority="p2")
check("6 a write with no session behind it (no sender): no line, and it applies", "Oliver commented" not in out and rd(14)["metadata"].get("priority") == "p2", out)
out = upd("a14", "a script on demo-box", priority="p3")
check("6 a script's write: no line", "Oliver commented" not in out, out)

item(23, needs=["demo-builder"], contact="demo-lead", next="")
answer("a23", "", "hold the release", "comment")
out = update_svc.complete_item("a23", outcome="dropped", reason="No longer needed", outcome_text="- gone", sender="demo-peer")
check("6 a close by a session that has not written since his answer carries the line too, and the item closes", "Oliver commented on a23 on the board at" in out and rd(23)["status"] == "completed", out)

# ================================================================ 7. a session the answer was pushed to holds it already
item(20, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-lead")
answer("a20", "Ship", "go now", "answer")
out = upd("a20", "demo-builder", priority="p3")
check("7 the session the answer was pushed to (in the pending answer's told list) gets no line on its first write, and the write applies", "Oliver answered" not in out and rd(20)["metadata"].get("priority") == "p3", out)
item(21, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-lead")
answer("a21", "Ship", "go now", "answer")
out = upd("a21", "demo-peer", priority="p3")
check("7 a session that was not told and has not written since gets the line", "Oliver answered a21 on the board" in out and rd(21)["metadata"].get("priority") == "p3", out)

item(24, needs=["decision", "demo-builder", "demo-peer"], ask=ASK, options=OPTS, contact="demo-main")
answer("a24", "Ship", "go now", "answer")
out_b = upd("a24", "demo-builder", priority="p3")
out_p = upd("a24", "demo-peer", priority="p3")
check("7 two sessions were handed the answer and write in turn: the first write settles the pending answer, and the second still gets no line", "Oliver answered" not in out_b and "Oliver answered" not in out_p and rd(24)["metadata"].get("priority") == "p3", (out_b, out_p))
check("7 the sessions handed the answer are kept on the answer's own record", set(rd(24)["metadata"]["answers"][-1].get("told", [])) == {U["demo-builder"], U["demo-peer"], U["demo-main"]}, rd(24)["metadata"]["answers"][-1])
item(25, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-main")
answer("a25", "Ship", "go now", "answer")
_st = answer_svc._answers()._answers_load(); _st.pop("a25", None); answer_svc._answers()._answers_save(_st)      # the escalation pass drops the pending answer after 30 minutes
out = upd("a25", "demo-builder", priority="p3")
check("7 after the pending answer is gone (escalated), a session that was handed the answer still gets no line on its first write", "Oliver answered" not in out and rd(25)["metadata"].get("priority") == "p3", out)
item(26, needs=["demo-builder"], contact="demo-lead")
answer("a26", "", "keep it small", "comment")
out = upd("a26", "demo-builder", priority="p3")
check("7 a comment has no pending answer: the session it was pushed to still gets no line on its first write", "Oliver commented" not in out and rd(26)["metadata"].get("priority") == "p3", out)
out = upd("a26", "demo-peer", priority="p3")
check("7 …and one it was not pushed to does", "Oliver commented on a26 on the board" in out, out)
item(28, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-lead")
answer("a28", "Ship", "go now", "answer")
out = upd("a28", "demo-lead", priority="p3")
check("7 a contact that was handed the answer as a held line gets no line on its first write either", "Oliver answered" not in out, out)

item(60, needs=["demo-builder"], contact="demo-lead")
ghev._github_comment("a60", {"id": 99, "ts": time.time(), "text": "from github"}); drain()
check("7 his comment on the item's GitHub issue records the sessions it was pushed to, on its own record", U["demo-builder"] in (rd(60)["metadata"]["answers"][-1].get("told") or []) and rd(60)["metadata"]["answers"][-1].get("via") == "github", rd(60)["metadata"].get("answers"))
out = upd("a60", "demo-builder", priority="p3")
check("7 …and the session told of it gets no line on its first write", "commented on" not in out and rd(60)["metadata"].get("priority") == "p3", out)
out = upd("a60", "demo-peer", priority="p2")
check("7 …one that was not told gets the line, and it names GitHub as the place, not the board", "Oliver commented on a60 on GitHub at" in out and "commented on a60 on the board" not in out, out)
item(62, needs=["demo-builder"], contact="demo-lead", answers=[{"ts": now0 - 3000, "kind": "comment", "text": "older", "told": [U["demo-peer"]]}, {"ts": now0 - 1000, "kind": "comment", "text": "newer", "told": [U["demo-builder"]]}])
out = upd("a62", "demo-builder", priority="p3")
check("7 two answers with different told lists: the newest record's list decides (the session told of the newest answer gets no line)", "Oliver commented" not in out and rd(62)["metadata"].get("priority") == "p3", out)
out = upd("a62", "demo-peer", priority="p3")
check("7 …and a session told of the older answer only gets the line, naming the newest", "Oliver commented on a62 on the board at" in out and "newer" in out, out)

# ================================================================ 8. a front agent is never sent the plain push
item(30, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-lead")
_real_can = held.can_fetch
def _raises(target, now=None): raise RuntimeError("the held store is unreadable")
held.can_fetch = _raises                       # a failure inside the front gate: it hands the notice back ("", "")
out, got, kept = answer("a30", "Ship", "go", "answer")
held.can_fetch = _real_can
check("8 the gate fails for the contact: no push to it (no turn), no held line; the session in the needs is told as before", "demo-lead" not in got and "demo-lead" not in kept and len(got.get("demo-builder", [])) == 1, (got, kept))
check("8 …the contact's History line says it was not told, and the routing log has its line", "demo-lead" in json.dumps(rd(30)["metadata"].get("front_quiet")) and ("a30", U["demo-lead"]) in LOGGED, (rd(30)["metadata"].get("front_quiet"), LOGGED))
_proj30 = telling._hold_project(U["demo-lead"], "a30")
_line30 = [x for x in routing.read(_proj30) if x.get("label") == "message a30"] if _proj30 else []
check("8 …and that line says archived, with no next_turn mark and an archived reason: the answer the gate could not file waits for no one's next turn", len(_line30) == 1 and _line30[0]["ruling"] == "archived"
      and str(_line30[0].get("reason", "")).startswith("archived: front agent, the front gate could not file it") and not [d for d in routing._file(_proj30).read_text(encoding="utf-8").splitlines() if '"next_turn"' in d and _line30[0]["id"] in d], (_proj30, _line30))
out = upd("a30", "demo-lead", priority="p3")
check("8 …and a contact the gate could not file is not recorded as told: it gets the line on its first write", "Oliver answered a30 on the board at" in out, out)
item(31, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-lead")
_real_sender, _real_role = telling.front_sender, telling.front_role
telling.front_sender = lambda who: False       # the open read the gate takes when the roles cannot be read: no front agent
telling.front_role = lambda who: None          # and the strict read that says so
out, got, kept = answer("a31", "Ship", "go", "answer")
telling.front_sender, telling.front_role = _real_sender, _real_role
check("8 the roles cannot be read (the contact read falls back to the project's -main agent): that session is taken for a front agent, never pushed to; nobody is told, the History line stays", set(got) == {"demo-builder"} and not kept and "demo-main" in json.dumps(rd(31)["metadata"].get("front_quiet")), (got, kept, rd(31)["metadata"].get("front_quiet")))
_real_roles = telling._anc.session_roles
def _roles_fail(*a, **k): raise RuntimeError("the page list is unreadable")
telling._anc.session_roles = _roles_fail
check("8 the strict role read says None when the roles fail, where the open one says False", telling.front_role("demo-lead") is None and telling.front_sender("demo-lead") is False)
telling._anc.session_roles = _real_roles
check("8 …and a real read says True for a front agent, False for a background one", telling.front_role("demo-lead") is True and telling.front_role("demo-builder") is False)

# ================================================================ 9. the line leans toward silence when the history cannot be read in full
def revise(gid, n, first_writer, rest_writer, base):
    """n revisions of the item committed to the store: the first written by `first_writer`, the others by `rest_writer`, each stamped after the answer."""
    for i in range(n):
        v = rd(gid[1:]); w = first_writer if i == 0 else rest_writer
        v.update(written_by=w, written_by_id=U[w], written_at=base + 1 + i * 0.001, description=DESC + f"\n- revision {i}")
        (T / f"store/a/{gid[1:]}.json").write_text(json.dumps(v)); git("add", "-A"); git("commit", "-q", "-m", f"r{i}")
item(40, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-main")
answer("a40", "Ship", "go now", "answer")
t40 = rd(40)["metadata"]["answers"][-1]["ts"]
revise("a40", 4, "demo-lead", "demo-peer", t40)
out = upd("a40", "demo-lead", priority="p3")
check("9 a session whose write is in the history, a few revisions back: no line (the history is read in full)", "Oliver answered" not in out and rd(40)["metadata"].get("priority") == "p3", out)
item(41, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-main")
answer("a41", "Ship", "go now", "answer")
t41 = rd(41)["metadata"]["answers"][-1]["ts"]
revise("a41", 62, "demo-lead", "demo-peer", t41)
out = upd("a41", "demo-lead", priority="p3")
check("9 more than 60 newer revisions, the sender's own among the oldest: no line (a missing line is better than a wrong one)", "Oliver answered" not in out and rd(41)["metadata"].get("priority") == "p3", out)
item(42, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-main")
answer("a42", "Ship", "go now", "answer")
os.rename(T / "store/.git", T / "store/.git-off")
out = upd("a42", "demo-lead", priority="p3")
os.rename(T / "store/.git-off", T / "store/.git")
check("9 a store outside git has no history to read: no line for a session that never wrote, and the write applies", "Oliver answered" not in out and rd(42)["metadata"].get("priority") == "p3", out)

# ================================================================ 10. the contact that is also a front agent he is talking to now
item(50, needs=["decision", "demo-builder"], ask=ASK, options=OPTS, contact="demo-lead")
stamp("demo-lead", 60)
out, got, kept = answer("a50", "Ship", "go", "answer")
check("10 a contact that is also in conversation is told once: one held line, no push", kept.get("demo-lead", "").count("answered a50") == 1 and "demo-lead" not in got and "notices held" not in kept.get("demo-lead", ""), (got, kept))
unstamp("demo-lead")

# ================================================================ 11. after his answer the builder moves the item, not the front agent in its needs
from stackshot.model import model as _model
from stackshot.service import answer_handover as handover_svc
def names_of(meta): return [next((n for n, u in U.items() if u == x), x) for x in meta.get("needs") or []]
def derived(i): return _model.derive({**rd(i), "id": str(i)})
item(70, mover="Oliver", needs=["decision", "demo-lead"], ask=ASK, options=OPTS)
out, got, kept = answer("a70", "Ship", "", "answer")
meta = rd(70)["metadata"]
check("11 a decision on an item whose needs name a front agent and no then: the builder is the mover and first in needs, then is not stored, the front agent stays named",
      out == "decision" and meta.get("mover") == "demo-builder" and "then" not in meta and names_of(meta) == ["demo-builder", "demo-lead"] and derived(70).mover == "demo-builder" and not derived(70).conflicts, (out, meta, derived(70)))
check("11 ...the builder is pushed it with 'It's yours now'; the front agent is handed a held line and no push", "It's yours now" in " ".join(got.get("demo-builder", [])) and "demo-lead" not in got and "answered a70" in kept.get("demo-lead", ""), (got, kept))
check("11 ...the pending answer lists the builder alone (the front agent's line is held, not a hand-over)", json.loads((T / "state/answers.json").read_text())["a70"]["told"] == [U["demo-builder"]], (T / "state/answers.json").read_text())
check("11 ...the held line starts no turn and carries no mark for him", "[for Oliver]" not in kept.get("demo-lead", ""), kept)
item(71, project="projects/beta", mover="Oliver", needs=["decision", "demo-side"], ask=ASK, options=OPTS)
out, got, kept = answer("a71", "Ship", "", "answer")
meta = rd(71)["metadata"]
check("11 a project with no builder keeps its front agent: the stored mover goes, the front agent moves the item by the model's default, and it is pushed the line as before",
      out == "decision" and "mover" not in meta and "then" not in meta and names_of(meta) == ["demo-side"] and derived(71).mover == "demo-side" and len(got.get("demo-side", [])) == 1 and "demo-side" not in kept, (out, meta, got, kept))
_live = handover_svc._then_live
handover_svc._then_live = lambda then, m: False if then == "demo-builder" else _live(then, m)      # a builder that cannot take the item (retired, unknown)
try:
    item(72, mover="Oliver", needs=["decision", "demo-lead"], ask=ASK, options=OPTS)
    out, got, kept = answer("a72", "Ship", "", "answer")
finally:
    handover_svc._then_live = _live
meta = rd(72)["metadata"]
check("11 a builder that cannot take the item (_then_live says no): as before, the front agent moves it and is pushed the line",
      out == "decision" and "mover" not in meta and names_of(meta) == ["demo-lead"] and derived(72).mover == "demo-lead" and len(got.get("demo-lead", [])) == 1 and "demo-builder" not in got, (out, meta, got, kept))
item(73, mover="Oliver", state="your-step", step=STEP, needs=["demo-lead"])
out, got, kept = answer("a73", "", "", "done")
meta = rd(73)["metadata"]
check("11 a Done on his step whose needs name a front agent: the builder takes the item (mover, first in needs), the front agent stays named",
      out == "done" and meta.get("mover") == "demo-builder" and names_of(meta) == ["demo-builder", "demo-lead"] and "then" not in meta and derived(73).mover == "demo-builder" and not derived(73).conflicts, (out, meta, derived(73)))
check("11 ...the builder is told it is its now; the front agent has a held line and no push", "demo-lead" not in got and "did his step on a73" in kept.get("demo-lead", "") and "It's yours now" in " ".join(got.get("demo-builder", [])), (got, kept))
item(74, project="projects/beta", mover="Oliver", state="your-step", step=STEP, needs=["demo-side"])
out, got, kept = answer("a74", "", "", "done")
meta = rd(74)["metadata"]
check("11 a Done on a project with no builder: the front agent takes the item, as before (no builder is named, and its own-move notice is the front gate's, not a held line of this change)", out == "done" and meta.get("mover") == "demo-side" and "demo-builder" not in names_of(meta) and "demo-builder" not in got, (out, meta, got, kept))
item(75, mover="Oliver", needs=["decision", "demo-lead"], then="demo-lead", ask=ASK, options=OPTS)
out, got, kept = answer("a75", "Ship", "", "answer")
meta = rd(75)["metadata"]
check("11 a then the writer stored is left as written, even when it is the front agent: it moves the item and is pushed the line",
      out == "decision" and meta.get("mover") == "demo-lead" and "demo-builder" not in got and len(got.get("demo-lead", [])) == 1, (out, meta, got, kept))
item(79, mover="Oliver", state="your-step", step=STEP, then="demo-lead", needs=["demo-lead"])
out, got, kept = answer("a79", "", "", "done")
meta = rd(79)["metadata"]
check("11 a Done on an item that stores a front agent as its then leaves it as written: the front agent takes the item and is told, the builder is not named", out == "done" and meta.get("mover") == "demo-lead" and "demo-builder" not in names_of(meta) and "demo-builder" not in got, (out, meta, got, kept))
item(76, mover="Oliver", then="demo-builder", needs=["decision", "demo-lead"], ask=ASK, options=OPTS)      # the then a write stores now (the builder), the front agent beside it in needs
out, got, kept = answer("a76", "", "a thought, no decision yet", "comment")
check("11 a comment (the item stays his): the builder is its then, so the front agent in needs is handed a held line, no push", out == "comment" and "demo-lead" not in got and "commented on a76" in kept.get("demo-lead", "") and len(got.get("demo-builder", [])) == 1, (out, got, kept))
item(77, project="projects/beta", mover="Oliver", needs=["decision", "demo-side"], ask=ASK, options=OPTS)
out, got, kept = answer("a77", "", "a thought, no decision yet", "comment")
check("11 a comment on a project with no builder: the front agent in needs is pushed it, as before", out == "comment" and len(got.get("demo-side", [])) == 1 and "demo-side" not in kept, (out, got, kept))
item(78, project="projects/beta", mover="Oliver", then="demo-solo", needs=["decision", "demo-side"], ask=ASK, options=OPTS)      # another session holds the item (its then), and the front agent is only named in needs
out, got, kept = answer("a78", "", "a thought, no decision yet", "comment")
check("11 …also when another session holds the item: with no builder a front agent in needs is not demoted to a held line, as before", out == "comment" and len(got.get("demo-side", [])) == 1 and "demo-side" not in kept, (out, got, kept))

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: {len(ran)} checks")
