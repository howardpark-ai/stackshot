"""Scenario test for "fewer front-agent wakes" (a front agent is woken by a message only when it has something to do or to tell him) — fixture data, no live store, no network, no server.

Covers the three fixes and their negatives:
  1. A background agent's message to a front agent that names a board item and only reports is written onto the item (the server's History
     note) and delivered to nobody; the reply names the item. A message that asks (a question mark, needs: decision, an ask or decision word, a
     step only the reader can take, an opening instruction) still reaches the front agent; so does one that names no item, one from a session
     that is not a background agent, and one to a background agent. The same holds for a `For <front agent>, …` message to a project. The
     decision itself (reports.asks) is checked on a table of texts, among them messages of many shapes.
  2. A CI or PR notice on a pull request whose head branch starts with a background agent's name and a slash goes to that builder (router rule
     anchor-builder), not to the item's front keeper; a branch of anyone else, a notice with no head, and a notice that names Oliver route as
     before; an identical repeat is dropped. anchor-hub puts the head and the commit author on the event, and the routing log keeps them.
     A CI or check-run result on any pull request (anchor-ci: a CI result goes only to the engineer and never produces a front turn),
     whoever's branch it is, goes to the project's builder; the replayed notice ci_up (an upstream PR, the item's anchor) is the case. The marker is the
     event type anchor-hub puts on the event and the routing log keeps (`etype`), else the sender `CI`; a person's notice, a project with no builder, a
     notice that names Oliver and a builder's own branch (anchor-builder) route as they did.
  2b. Build-side news on a GitHub anchor scoped to an item whose keeper of record is a front agent (a push, a review, a comment by someone else, a merge; anchor-item,
     the board item) goes to the item's mover when that is a
     background agent, else a background agent its needs or first next line name, else the project's builder; it stays with the keeper when Oliver wrote it, when it
     says it is for him, when the item waits on his decision or he moves it, when the project has no builder, and when the anchor is no GitHub one. The builder's own
     `[board]` notices about such an item are told to no front agent (item_route, checked below).
  3. A hand-back to a front agent keeper is held; a close of the item inside the window drops it, so the keeper hears only the close; with no
     close the line is sent when the window ends (and survives a restart: it is a file); a second hand-back replaces the first; an item that
     moved on is not announced; 0 seconds sends at once.

    tests/run-suite fewer_wakes        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, threading, time, types
BID_A = 9162
BID_B = 9163

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="fewwakes-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
toml = _instance.apply(_instance.base_toml(), login=True, keywords=True)
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
S, A, X, B, Y = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
                 "44444444-4444-4444-8444-444444444444", "55555555-5555-4555-8555-555555555555")
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for u, n in
                                                      ((S, "osprey"), (A, "osprey-main"), (X, "osprey-x"), (B, "home-beta"), (Y, "osprey-front2"))}))
AGENTS = {"osprey-main": "Oliver's point of contact", "osprey-front2": "talks to Oliver about the second thing", "osprey-x": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {
    "title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "osprey", "status": "active", "board": [], "board_row": False,
    "updated": 1, "mirror": "https://example.invalid/alpha", "agents": AGENTS, "back_agents": {"osprey-x": AGENTS["osprey-x"]}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
DESC = "- A thing\n- It lives here\n- Finished when it works"
now0 = time.time()
def item(i, owner=A, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600,
                                                       "metadata": {"owner": owner, **({} if {"needs", "hold", "after"} & set(meta) else {"mover": owner}), "project": "projects/alpha", "next": "the next step", **meta}}))
# 1-9: the message gate · 20-29: the hand-back hold · 40: the pull request's item
for i in range(1, 6): item(i)
item(6, owner=Y)
for i in range(20, 31): item(i, needs=["osprey-x"], then="osprey-main")
item(40)
item(41, mover="Oliver", then="osprey-main"); item(42, mover="osprey-x"); item(43, mover="osprey-front2")      # 41: his to move · 42: the builder moves it · 43: a front agent moves it
item(7, needs=["decision"], then="osprey-main"); item(8, needs=["osprey-main"])      # an item that waits on his decision; one that names the front agent in its needs
(T / "store/next-id").write_text("100")
PR = "https://github.com/example-owner/stackshot/pull/4"
R_BASE = "https://github.com/example-owner/stackshot/pull/"
UPSTREAM = "https://github.com/example-upstream/tool/pull/11"        # an upstream pull request of someone else's branch, scoped to the same item
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": PR, "items": ["a40"]}, {"url": UPSTREAM, "items": ["a40"]}, {"url": R_BASE + "12", "items": ["a7"]}, {"url": R_BASE + "13", "items": ["a41"]},
                                                                 {"url": R_BASE + "14", "items": ["a42"]}, {"url": R_BASE + "16", "items": ["a43"]}]}))
push_log = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(push_log)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
def pushes(): return [json.loads(l) for l in push_log.read_text().splitlines()] if push_log.exists() else []
def settle(until=30):
    end = time.time() + until
    while time.time() < end and any(t is not threading.main_thread() and t.is_alive() for t in threading.enumerate()):
        time.sleep(0.02)
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())

from stackshot.core import config as _cfg; from stackshot.router import routing; from stackshot.waits import reports
from stackshot.router import router as _router
from stackshot.web import server
from stackshot.anchors import anchors as _anc_y
from fastmcp.exceptions import ToolError
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import update as _wt_update
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import text as _wt_text
from stackshot.service import telling
from stackshot.service import writes
from stackshot.anchors.anchorhub import core
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None; telling.PUSH = [sys.executable, str(T / "fakepush.py")]
_web_page_debts._refuse_if_owing = lambda debtor: None
PRESENT = [True]    # a front agent Oliver is typing to now: the gate sends its close line (the held case is in front_quiet_scenario)
_real_verdict = telling.front_verdict
telling.front_verdict = lambda gid, owner, kind: ("send", "") if PRESENT[0] else _real_verdict(gid, owner, kind)
def cfg(live=True): _cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, **({"live": True} if live else {})}
cfg(True)
saved = []                                                  # every writes.save with a note: the item's History line the report becomes
_real_save = writes.save
def _spy_save(gid, item_, writer="", note="", author=None, mirror=True, **kw):
    if note: saved.append((gid, note))
    return _real_save(gid, item_, writer=writer, note=note, author=author, mirror=mirror, **kw)
writes.save = _spy_save
def to(name, since): return [x for x in pushes()[since:] if x[0] == name]
def why(fn):
    try: fn(); return ""
    except ToolError as e: return str(e)
MK = _wt_text._FOR_OWNER

# ---- 0. reports.report_doubt: only what clearly reads as a status report is held back; everything else is delivered
FRONT = ("osprey-main", "osprey-front2")
DELIVERED = [          # every shape the review named, and the earlier asks: none may be taken for a report
    "[for Oliver] Take a1", "Take the old name off projects/example-brain's agents.", "a1 is merged; awaits your merge", "ready for Oliver's review", "requires Oliver's go",
    "a1 approves the change", "approved and merged", "実装が終わり、確認が必要です", "配布の前に決定が必要です", "検討をお願いします", "ご意見をお願いします", "see https://x.example/y? for the log",
    "https://x.example/page?", "deploy broke the site; rolled back", "the deploy cost $40 and is live", "the suites failed on 010cc0d", "an error in the log; fixed in 010cc0d and live", "blocked on the runner; PR 18 is up",
    "is it live?", "needs: decision", "PR 18 is live. Please look at the page.", "can you look at the vendor thread", "Decide: ship or hold", "your call", "go ahead with the release",
    "Options: A, B, C", "I recommend A", "Oliver should try a copy on box-c", "only Oliver can run this", "You, as a front agent, can run: python3 client.py x", "log in on box-c first",
    "PR 18 is live. Merge it", "merged. The footer line stays.", "merged and the keeper has it", "merged; osprey-main has it", "merged, and I will deploy later", "merged, then deployed",
    "merged; `see the long note here and decide`", "merged\n```\ncode\n```", "PR 18 is live, the suites pass.\nWhat now",
    # reports of other shapes: each carries a plan, a wait or a need, or says something that is no status shape, so none is taken for one
    "the first batch is pushed. Two builds overlap on main: one from the earlier release, still running, plus a rerun. No test changed. A second batch follows once the first one ends.",
    "that's the order already. The two spare workers are being set up now. One of them is offline because its machine counts as in use.",
    "labels it is. PR 19 is being re-cut; osprey-x is asked to add a label to the workers first. I release after their confirmation.",
    "PR 21 is queued to release the moment PR 19's release ends. PR 19's suites job is still running. I will report here when 21 is live.",
    "the second pass is done in staging: the remaining lines are back on the page. The tree is ready for the rebuild; nothing is uploaded.",
    "the step is merged; \"pending\" only means not applied yet. In order now: PR 22 is releasing; then I apply the hook if it passes; then the last row (needs the other side).",
    "the server has no call that drops a pending agent, so the fix starts there. I asked projects/example for one; I build the client side once they name it.",
]
HELD = [               # a plain status report, every sentence one of the shapes
    "PR 23 is live.", "a1 merged and deployed.", "PR #18 is up; the suites pass.", "fixed in 010cc0d. Suites are green.", "Recorded on the item. No change to the unit.", "released; closed.",
    "[for Oliver] done: the unit is live and the suites pass", "For osprey-main, a1: merged, deployed, green.", "`a1` is merged", "opened PR #18", "merged in 010cc0d\nlive since 15:10", "No change. Unchanged since a1.",
]
check("reports: every shape of ask, trouble, waiting, naming and plan is delivered", [t for t in DELIVERED if reports.is_report(t, FRONT)] == [], [(t, reports.report_doubt(t, FRONT)) for t in DELIVERED if reports.is_report(t, FRONT)])
check("reports: a plain status report is held back", [t for t in HELD if not reports.is_report(t, FRONT)] == [], [(t, reports.report_doubt(t, FRONT)) for t in HELD if not reports.is_report(t, FRONT)])
check("reports: the reason names what stopped it", reports.report_doubt("is it live?") == "a question mark" and reports.report_doubt("live; ask Oliver") .startswith("a word of trouble")
      and reports.report_doubt("The footer line stays.").startswith("a sentence that is no status shape") and reports.report_doubt("live, see `a long prose span here now ok`") == "a code span with prose"
      and reports.report_doubt("merged, osprey-main knows", FRONT) == "the name osprey-main" and reports.report_doubt("") == "nothing said", reports.report_doubt("live; ask Oliver"))

# ---- 1. the message tool
roles = _anc_y.session_roles()
check("fixture: osprey-main and osprey-front2 are front agents, osprey-x a background one", roles["osprey-main"]["role"] == "front" and roles["osprey-front2"]["role"] == "front" and roles["osprey-x"]["role"] == "back", {k: v["role"] for k, v in roles.items()})
p0, s0 = len(pushes()), len(saved)
rep = server._message("osprey-main", f"{MK} a1: PR 18 is live and the suites pass. The step is merged.", "osprey-x"); settle()
check("1a: a builder's marked message that only reports on an item is not delivered: the reply says so and names the item and the writer", rep.startswith("Not delivered: written onto")
      and "written onto a1 as a History line from osprey-x, because osprey-main is a front agent" in rep and "send it again saying what" in rep, rep)
check("…it is on the item as the server's note (History), without the mark, naming sender and receiver; nothing was pushed", len([x for x in saved[s0:] if "reported to" in x[1]]) == 1 and saved[-1][0] == "a1"
      and saved[-1][1] == "osprey-x reported to osprey-main (not sent to it: a plain status report): a1: PR 18 is live and the suites pass. The step is merged." and len(pushes()) == p0, (saved[s0:], pushes()[p0:]))
check("…the item itself is unchanged (a filing note: no clock moves, no field; the stored phase every save of an open item writes apart)", {k: v for k, v in rd(1)["metadata"].items() if k != "phase"} == {"owner": A, "mover": A, "project": "projects/alpha", "next": "the next step"} and rd(1)["updated"] == now0 - 3600, rd(1))
msgs = [json.loads(l) for l in server.MSG_LOG.read_text().splitlines()]
check("…the messages log says written onto the item, not delivered", msgs and msgs[-1]["from"] == "osprey-x" and msgs[-1]["outcome"] == "written onto a1, not delivered", msgs[-1:])
rep = server._message(A, f"{MK} a1 and a2: both merged", "osprey-x"); settle()
check("1b: …by the front agent's transcript id too, and two items get a line each", rep.startswith("Not delivered") and "a1, a2" in rep and [g for g, _ in saved[s0 + 1:]] == ["a1", "a2"], (rep, saved[s0 + 1:]))
check("1c: a builder's sender given as its transcript id is a builder too", server._message("osprey-main", f"{MK} a3: merged", X).startswith("Not delivered"))
p0, s0 = len(pushes()), len(saved)
NEG = (("a question mark", f"{MK} a1: PR 18 is live. Merge it?"), ("a question mark ending a URL", f"{MK} a1: merged, log at https://x.example/log?"),
       ("needs: decision", f"{MK} a1: needs: decision on the wording"), ("an opening instruction", f"{MK} Take a1"),
       ("an ask word", f"{MK} a1: PR 18 is live. Please look at the page."), ("awaiting a merge", f"{MK} a1: PR 18 awaits your merge"),
       ("a request for review", f"{MK} a1: ready for Oliver's review"), ("a decision word", f"{MK} a1: two options for the page; I recommend A"),
       ("a step only he can take", f"{MK} a1: you need to log in on box-c, then it runs"), ("a fact without an ask word", f"{MK} a1: the deploy broke the site; rolled back"),
       ("a Japanese ask", f"{MK} a1: 承認をお願いします"), ("a Japanese need", f"{MK} a1: 実装が終わり、確認が必要です"),
       ("a plan", f"{MK} a1: merged. I deploy after the suites pass."), ("a prose sentence that is no status shape", f"{MK} a1: the footer line stays."),
       ("a fenced block", f"{MK} a1: merged\n```\nsudo systemctl restart x\n```"))
for name, text in NEG:
    rep = server._message("osprey-main", text, "osprey-x"); settle()
    check(f"1d negative: a builder's message with {name} still reaches the front agent", rep.startswith("delivered"), (rep, text))
check(f"…all {len(NEG)} were pushed to osprey-main and none was written onto the item", len(to("osprey-main", p0)) == len(NEG) and not [x for x in saved[s0:] if "reported to" in x[1]], (len(to("osprey-main", p0)), saved[s0:]))
p0, s0 = len(pushes()), len(saved)
rep = server._message("osprey-main", f"{MK} a7: PR 18 is live", "osprey-x"); settle()
check("1d2 negative: a plain report on an item that waits on his decision (needs: decision) is delivered", rep.startswith("delivered") and len(to("osprey-main", p0)) == 1 and not [x for x in saved[s0:] if "reported to" in x[1]], (rep, saved[s0:]))
rep = server._message("osprey-main", f"{MK} a8: PR 18 is live", "osprey-x"); settle()
check("…and one on an item whose needs name the front agent is delivered", rep.startswith("delivered") and len(to("osprey-main", p0)) == 2 and not [x for x in saved[s0:] if "reported to" in x[1]], (rep, saved[s0:]))
rep = server._message("osprey-front2", f"{MK} a8: PR 18 is live", "osprey-x"); settle()
check("…but a8 names osprey-main alone, so the same report to the other front agent is held", rep.startswith("Not delivered") and saved[-1][0] == "a8", (rep, saved[-1:]))
rep = server._message("osprey-main", f"{MK} a1 and a7: PR 18 is live", "osprey-x"); settle()
check("…a report naming two items is delivered when either waits on him", rep.startswith("delivered"), rep)
p0, s0 = len(pushes()), len(saved)
rep = server._message("osprey-main", f"{MK} the build is live, the suites pass", "osprey-x"); settle()
check("1e negative: a report that names no item is delivered (nowhere to put it)", rep.startswith("delivered") and len(to("osprey-main", p0)) == 1 and not [x for x in saved[s0:] if "reported to" in x[1]], (rep, saved[s0:]))
rep = server._message("osprey-main", f"{MK} `a1` is live", "osprey-x"); settle()
check("…an id in backticks names nothing (the cited-for-context form): delivered", rep.startswith("delivered"), rep)
rep = server._message("osprey-main", f"{MK} a1, a2, a3 and a4 are all merged", "osprey-x"); settle()
check("…a report naming four items is delivered (it is not about one thing)", rep.startswith("delivered") and not [x for x in saved[s0:] if "reported to" in x[1]], (rep, saved[s0:]))
rep = server._message("osprey-main", f"{MK} board#{BID_A} is merged", "osprey-x"); settle()
check("…an id that names no item names nothing: delivered", rep.startswith("delivered"), rep)
p0, s0 = len(pushes()), len(saved)
rep = server._message("osprey-main", f"{MK} a1 is merged", "home-beta"); settle()
check("1f negative: the same report from a session that is no background agent is delivered as before", rep.startswith("delivered") and not [x for x in saved[s0:] if "reported to" in x[1]], rep)
rep = server._message("osprey-main", f"{MK} a1 is merged", "osprey-front2"); settle()
check("…and from another front agent", rep.startswith("delivered") and not [x for x in saved[s0:] if "reported to" in x[1]], rep)
rep = server._message("osprey-x", "a1 is merged, the suites pass", "home-beta"); settle()
check("…a message to a background agent is never held back", rep.startswith("delivered") and not [x for x in saved[s0:] if "reported to" in x[1]], rep)
rep = server._message("osprey-main", f"{MK} a1 is live", "nightly-job", origin="testbox"); settle()
check("…a script's message (origin) is not a builder's", rep.startswith("delivered") and not [x for x in saved[s0:] if "reported to" in x[1]], rep)
check("1g: an unmarked message is still refused first, and 'no action needed' is still refused, builder or not",
      why(lambda: server._message("osprey-main", "a1 is merged", "osprey-x")).startswith("Refused: osprey-main is a front agent")
      and "says nothing is needed from him ('no action needed')" in why(lambda: server._message("osprey-main", f"{MK} a1 is merged, no action needed", "osprey-x")))
# a message to a project that opens "For <front agent>"
p0, s0 = len(pushes()), len(saved); n0 = len(routing.read("projects/alpha"))
rep = server._message("projects/alpha", "For osprey-main, a2: PR 24 is live, the suites pass.", "osprey-x"); settle()
check("1h: a builder's 'For <front agent>' report to the project is written onto the item, not recorded for the router", rep.startswith("Not delivered: written onto")
      and saved[s0:] and saved[-1][0] == "a2" and len(routing.read("projects/alpha")) == n0 and not to("osprey-main", p0), (rep, saved[s0:], len(routing.read("projects/alpha")) - n0))
msgs = [json.loads(l) for l in server.MSG_LOG.read_text().splitlines()]
check("…the log names the project it was addressed to", msgs[-1]["to"] == "projects/alpha" and msgs[-1]["outcome"] == "written onto a2, not delivered", msgs[-1])
s0 = len(saved)
rep = server._message("projects/alpha", "For osprey-main, a2: PR 24 is live. Can you merge it?", "osprey-x")
check("1i negative: the same with a question is held for the router, as before", rep.startswith("held for the router") and not [x for x in saved[s0:] if "reported to" in x[1]], rep)
rep = server._message("projects/alpha", "For osprey-x, a2: PR 24 is live", "home-beta")
check("…one to a background agent, or from a non-builder, is held for the router, as before", rep.startswith("held for the router") and not [x for x in saved[s0:] if "reported to" in x[1]], rep)
rep = server._message("projects/alpha", "a2: PR 24 is live", "osprey-x")
check("…a project message that is not addressed to a front agent is the router's, as before", rep.startswith("held for the router") and not [x for x in saved[s0:] if "reported to" in x[1]], rep)

# ---- 2. anchor notices on a builder's pull request
cx = _router.Context()
KEY = "projects/alpha"; ANCHOR = "github:example-owner/stackshot#4"
def notice(nid, head="", text="failed on 010ec0d: 1 of 5 checks — suites", who="CI", ts=1000.0, **kw):
    n = {"id": nid, "ts": ts, "kind": "anchor", "label": f'GitHub stackshot#4 "board#{BID_B}: a thing"', "who": who, "text": text, "url": PR + "/checks", "target": "for osprey-main",
         "anchor": ANCHOR, "pilot": True, "live": True, **kw}
    if head: n["head"] = head
    return n
ln = _router.code_rule(KEY, notice("n1"), KEY, cx, [])
check("2a: a CI notice on the PR scoped to board#<a>'s anchor passes to the builder (anchor-ci), with the item, not to the item's keeper", ln and ln["rule"] == "anchor-ci" and ln["ruling"] == "passed"
      and ln["target"] == "osprey-x" and ln["item"] == "a40" and not ln["for_owner"], ln)
ln = _router.code_rule(KEY, notice("n1a", who="kim", text="commented: why this?", etype="comment"), KEY, cx, [])
check("2a2: a person's notice on the same anchor is build-side news: anchor-item passes it to the builder, who moves the item, with the item", ln and ln["rule"] == "anchor-item"
      and ln["target"] == "osprey-x" and ln["item"] == "a40" and not ln["for_owner"], ln)
ln = _router.code_rule(KEY, notice("n1b", who="example-owner", text="commented: why this?"), KEY, cx, [])
check("2a3: …but Oliver's own notice (his login as the sender) stays with the item's keeper", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
ln = _router.code_rule(KEY, notice("n2", head="osprey-x/fewer-front-wakes"), KEY, cx, [])
check("2b: a notice whose PR head branch is the builder's (<builder>/<topic>) passes to the builder, with the branch in the reason", ln and ln["rule"] == "anchor-builder" and ln["ruling"] == "passed"
      and ln["target"] == "osprey-x" and ln["item"] == "a40" and not ln["for_owner"] and "osprey-x/fewer-front-wakes" in ln["reason"], ln)
for what, head in (("a person's branch", "oliver/topic"), ("a front agent's branch", "osprey-main/topic"), ("the main branch", "main"), ("a subagent's worktree branch", "worktree-agent-ab12cd"),
                   ("no slash", "osprey-x"), ("the builder's name as a longer word", "osprey-xray/topic")):
    ln = _router.code_rule(KEY, notice("n3", head=head, who="example-owner", text="commented: why this?"), KEY, cx, [])
    check(f"2c negative: {what} ({head}) is not anchor-builder's: Oliver's own notice on it goes to the item's keeper", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
    ln = _router.code_rule(KEY, notice("n3c", head=head), KEY, cx, [])
    check("…a CI notice on it is not anchor-builder's, but anchor-ci passes it to the builder", ln and ln["rule"] == "anchor-ci" and ln["target"] == "osprey-x", ln)
ln = _router.code_rule(KEY, notice("n4", head="osprey-x/topic", text="[for Oliver] he commented: do it this way"), KEY, cx, [])
check("2d negative: a notice that is itself for Oliver keeps today's route", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
prior = notice("n5", head="osprey-x/topic", ts=900.0)
ln = _router.code_rule(KEY, notice("n6", head="osprey-x/topic", ts=1000.0), KEY, cx, [prior])
check("2e: an identical notice within the hour is a repeat, dropped (not passed twice to the builder)", ln and ln["rule"] == "repeat" and ln["ruling"] == "dropped", ln)
ln = _router.code_rule(KEY, notice("n7", head="osprey-x/topic", who="osprey-x"), KEY, cx, [])
check("2f: a notice the builder wrote itself is not passed back to it (the sender-is-target test)", ln and ln["rule"] != "anchor-builder", ln)
ln = _router.code_rule(KEY, notice("n8", head="osprey-x/topic", anchor="github:example-owner/stackshot#999", target="project-wide"), KEY, cx, [])
check("2g: a PR the project watches without an item scope goes to the builder too", ln and ln["rule"] == "anchor-builder" and ln["target"] == "osprey-x" and ln["item"] == "", ln)
# 2j-2u: anchor-ci. A replayed notice: a CI failure on an upstream pull request (someone else's branch), the anchor scoped to the item
nt_ci = notice("ci_up", head="fix/sample-marker-cap", text="failed on 010fc0d: 1 of 44 checks — contributor-check", anchor="github:example-upstream/tool#11",
              label='GitHub tool#11 "fix(parser): the sample step ignores a marker"', author="example-owner")
nt_ci["url"] = UPSTREAM + "/checks"
ln = _router.code_rule(KEY, nt_ci, KEY, cx, [])
check("2j: notice ci_up (CI on an upstream PR, a branch that is no builder's) goes to the builder by anchor-ci, with the item, and is not for Oliver",
      ln and (ln["rule"], ln["ruling"], ln["target"], ln["item"], ln["for_owner"]) == ("anchor-ci", "passed", "osprey-x", "a40", False), ln)
ln = _router.code_rule(KEY, {**nt_ci, "id": "j2", "text": "passing again on 010fc0d (44 checks)"}, KEY, cx, [])
check("2k: a passed CI notice goes to the builder too, with the item id when the anchor is scoped to exactly one item", ln and (ln["rule"], ln["target"], ln["item"]) == ("anchor-ci", "osprey-x", "a40"), ln)
ln = _router.code_rule(KEY, notice("j3", head="x/y", anchor="github:example-upstream/tool#9999", target="project-wide"), KEY, cx, [])
check("2l: a CI notice on an anchor with no item scope goes to the builder with no item", ln and (ln["rule"], ln["target"], ln["item"]) == ("anchor-ci", "osprey-x", ""), ln)
for what, extra in (("an etype ci_failed", {"etype": "ci_failed"}), ("an etype ci_passed", {"etype": "ci_passed"}), ("an etype ci_activity (GitHub's own CI thread)", {"etype": "ci_activity"}), ("no etype, the sender CI", {})):
    ln = _router.code_rule(KEY, notice("j4", **extra), KEY, cx, [])
    check(f"2m: the marker: {what} → anchor-ci", ln and ln["rule"] == "anchor-ci" and ln["target"] == "osprey-x", ln)
ln = _router.code_rule(KEY, notice("j5", etype="comment"), KEY, cx, [])
check("2n negative: a comment by a user whose login is CI is a person's notice: not anchor-ci's but anchor-item's (build-side, to the builder)", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-x", ln)
for what, extra in (("a CI result with a comment joined to it", {"etype": "ci_failed+comment", "who": "kim, CI"}), ("a CI result joined to an unclassified event", {"etype": "ci_failed+other"})):
    ln = _router.code_rule(KEY, notice("j5b", **extra), KEY, cx, [])
    check(f"2n negative: {what} is neither anchor-ci's nor on the build-side whitelist: it stays with the item's keeper", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
ln = _router.code_rule(KEY, notice("j6", who="kim", text="failed on 010ec0d: 1 of 5 checks — suites", etype="comment"), KEY, cx, [])
check("2o negative: a notice from a person, not CI, on the same anchor goes by anchor-item", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-x", ln)
ln = _router.code_rule(KEY, notice("j7", head="osprey-x/topic"), KEY, cx, [])
check("2p: a CI notice on the builder's own branch is still anchor-builder's (it runs first)", ln and ln["rule"] == "anchor-builder" and ln["target"] == "osprey-x", ln)
for what, text in (("[for Oliver]", "[for Oliver] failed on 010ec0d: 1 of 5 checks"), ("needs: decision", "failed on 010ec0d — needs: decision")):
    ln = _router.code_rule(KEY, notice("j8", text=text), KEY, cx, [])
    check(f"2q negative: a CI notice that carries {what} keeps today's route (anchor-item)", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
ln = _router.code_rule(KEY, notice("j9", ts=1000.0), KEY, cx, [notice("j9p", ts=900.0)])
check("2r: an identical CI notice within the hour is dropped, not passed twice to the builder", ln and ln["rule"] == "repeat" and ln["ruling"] == "dropped", ln)
ln = _router.code_rule(KEY, notice("j10", ts=1000.0 + 7200), KEY, cx, [notice("j10p", ts=1000.0)])
check("…an hour later it is not a repeat", ln and ln["rule"] == "anchor-ci", ln)
ln = _router.code_rule(KEY, notice("j10c", ts=1000.0), KEY, cx, [notice("j10a", ts=900.0), notice("j10b", ts=950.0, text="passing again on 010fc0d (44 checks)")])
check("2r2: a failure after a pass is not a repeat of the failure before it (only the latest earlier CI notice on the anchor counts): passed to the builder", ln and ln["rule"] == "anchor-ci" and ln["target"] == "osprey-x", ln)
ln = _router.code_rule(KEY, notice("j10e", ts=1000.0), KEY, cx, [notice("j10d", ts=950.0), notice("j10x", ts=980.0, text="somebody's comment", who="kim", etype="comment")])
check("…a person's notice between two identical CI notices does not break the repeat", ln and ln["rule"] == "repeat" and ln["ruling"] == "dropped", ln)
# CI on an item that waits on his decision still goes to the builder (CI goes only to the engineer)
ln = _router.code_rule(KEY, notice("j10f", anchor="github:example-owner/stackshot#12", url=R_BASE + "12/checks"), KEY, cx, [])
check("2r3: a CI notice on an anchor scoped to an item that waits on his decision (a7) still goes to the builder", ln and (ln["rule"], ln["target"], ln["item"]) == ("anchor-ci", "osprey-x", "a7"), ln)
cx_nb = _router.Context(); cx_nb.reg[KEY] = {**cx_nb.reg[KEY], "agents": {k: v for k, v in AGENTS.items() if k != "osprey-x"}, "back_agents": {}}
ln = _router.code_rule(KEY, notice("j11"), KEY, cx_nb, [])
check("2s negative: a project with no builder routes a CI notice as before (anchor-item)", cx_nb.builder(KEY) == "" and ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", (cx_nb.builder(KEY), ln))
cx_hub = _router.Context(); cx_hub.reg["ops/comp"] = {"title": "Comp", "name": "Comp", "type": "project", "hub": KEY}
ln = _router.code_rule("ops/comp", notice("j12", anchor="github:example-owner/comp#1", target="project-wide"), "ops/comp", cx_hub, [])
check("2t: a component page with no agents of its own (a `hub:` line) has its hub's builder", ln and (ln["rule"], ln["target"]) == ("anchor-ci", "osprey-x"), ln)
# 2v-2z: build-side news on an item scoped anchor whose keeper is a front agent (anchor-item)
def bs(nid, anchor, **kw): return notice(nid, who=kw.pop("who", "kim"), target=kw.pop("target", "for osprey-main"), text=kw.pop("text", "commented: why this?"), anchor=anchor, url=R_BASE + "x", etype=kw.pop("etype", "comment"), **kw)
for what, anc_, item_, want_t in (("an item with no mover stored", "github:example-owner/stackshot#4", "a40", "osprey-x"), ("an item the builder moves (its mover is stored)", "github:example-owner/stackshot#14", "a42", "osprey-x"),
                                  ("an item a front agent moves: the builder, not that front agent", "github:example-owner/stackshot#16", "a43", "osprey-x")):
    ln = _router.code_rule(KEY, bs("n1", anc_, target="for " + {"a42": "osprey-x", "a43": "osprey-front2"}.get(item_, "osprey-main")), KEY, cx, [])
    check(f"2v: a comment by someone else on {what} goes to {want_t}, with {item_}", ln and (ln["rule"], ln["ruling"], ln["target"], ln["item"]) == ("anchor-item", "passed", want_t, item_), ln)
for what, text, et in (("a merge", "merged it", "pr_merged"), ("a review", "approved", "review"), ("a review comment", "nit on line 3", "review_comment"), ("a push", "pushed 2 commits", "pr_synchronize"),
                       ("an issue closed", "closed it", "issue_closed"), ("a merge with a comment", "merged it, thanks", "pr_merged+comment")):
    ln = _router.code_rule(KEY, bs("n2", "github:example-owner/stackshot#4", text=text, etype=et), KEY, cx, [])
    check(f"2w: {what} ({et}) on an item's anchor goes to the builder", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-x", ln)
check("2w2: a release on a repository's @releases anchor is the builder's too (the whitelist's anchor form)", _router.build_side_target(cx.index["a40"], bs("n3", "github:example-upstream/tool@releases", etype="", text="released 1.2"), KEY, cx) == "osprey-x")
# the BLOCKER: the whitelist. @notifications reasons and anything unclassified (etype empty), a mixed or unclassified burst, a CI type: not build-side news, the keeper keeps it
for what, who_ in (("review requested", "review requested"), ("mentioned you", "mentioned you"), ("assigned to you", "assigned to you"), ("a security alert", "security alert"),
                   ("an invitation", "invitation"), ("on your thread", "on your thread"), ("an update", "update")):
    ln = _router.code_rule(KEY, bs("v2n", "github:example-owner/stackshot#4", who=who_, etype="", text=f"({who_}) PullRequest \"a thing\""), KEY, cx, [])
    check(f"2w3 negative: {what} (etype empty, not a release anchor) stays with the item's keeper", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
for what, et in (("an unclassified burst (other)", "other"), ("a comment folded with an unclassified event", "comment+other"), ("a CI type", "ci_failed"), ("an unknown type", "star")):
    check(f"2w4 negative: {what} ({et}) is not build-side news", _router.build_side_target(cx.index["a40"], bs("v2x", "github:example-owner/stackshot#4", etype=et, who="kim"), KEY, cx) == "")
ln = _router.code_rule(KEY, bs("v3", "github:example-owner/stackshot#12"), KEY, cx, [])
check("2x negative: an item that waits on his decision (needs: decision): the keeper of record keeps the notice", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main" and ln["item"] == "a7", ln)
ln = _router.code_rule(KEY, bs("v4", "github:example-owner/stackshot#13"), KEY, cx, [])
check("…an item that is his to move (mover Oliver) too", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main" and ln["item"] == "a41", ln)
ln = _router.code_rule(KEY, bs("v5", "github:example-owner/stackshot#4", text="[for Oliver] can you look at this?"), KEY, cx, [])
check("…a notice that says it is for Oliver too", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
ln = _router.code_rule(KEY, bs("v6", "github:example-owner/stackshot#4", text="needs: decision on the wording"), KEY, cx, [])
check("…and one with needs: decision", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
for what, text in (("an @-mention of his login", "@example-owner can you look?"), ("an @-mention of him", "@Oliver can you look?"), ("his name", "Oliver, is this what you meant?"), ("AE", "AE asked for this"),
                   ("a decision word (a weak signal)", "this is the decision we took"), ("a Japanese decision word", "決定をお願いします")):
    ln = _router.code_rule(KEY, bs("v6b", "github:example-owner/stackshot#4", text=text), KEY, cx, [])
    check(f"2x2 negative: a comment that names him ({what}) stays with the keeper", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
ln = _router.code_rule(KEY, bs("v6c", "github:example-owner/stackshot#4", text="why this?", who="kim, example-owner"), KEY, cx, [])
check("2x3 negative: a burst whose senders (comma-joined) include Oliver stays with the keeper", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
ln = _router.code_rule(KEY, bs("v6d", "github:example-owner/stackshot#4", text="why this?", who="kim, lee"), KEY, cx, [])
check("…and a burst of other people goes to the builder", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-x", ln)
had_gh = "github" in _cfg.CFG; had_ol = had_gh and "owner_login" in _cfg.CFG["github"]; was_ol = _cfg.CFG["github"].get("owner_login") if had_gh else None
try:
    plain = _router._is_owner_name("Example-Owner") and not _router._is_owner_name("kim") and not _router._is_owner_name("")
    _cfg.CFG.setdefault("github", {})["owner_login"] = "Boss-Login"
    both = _router._is_owner_name("boss-login") and not _router._is_owner_name("kim")
finally:
    if not had_gh: _cfg.CFG.pop("github", None)
    elif had_ol: _cfg.CFG["github"]["owner_login"] = was_ol
    else: _cfg.CFG["github"].pop("owner_login", None)
check("2x4: the owner's logins are [github] owner_login (or the token's login this process read), and no login is built into the code, so a false keep beats a false divert", plain and both, (plain, both))
check("…and the test left the config as it found it", ("github" in _cfg.CFG) == had_gh and (not had_gh or _cfg.CFG["github"].get("owner_login") == was_ol))
ln = _router.code_rule(KEY, bs("v7", "github:example-owner/stackshot#4", who="osprey-x"), KEY, cx, [])
check("2y negative: a notice the builder wrote itself is not passed back to it (the sender-is-target test): the keeper's route as before", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
ln = _router.code_rule(KEY, bs("v8", "github:example-owner/stackshot#4", ts=1000.0), KEY, cx, [bs("v8p", "github:example-owner/stackshot#4", ts=900.0)])
check("2z: an identical build-side notice within the hour is dropped, not passed twice", ln and ln["rule"] == "repeat" and ln["ruling"] == "dropped", ln)
ln = _router.code_rule(KEY, bs("v9", "github:example-owner/stackshot#4"), KEY, cx_nb, [])
check("2z2 negative: a project with no builder passes it to the item's keeper as today", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
check("2z3 negative: an anchor that is not GitHub's (a Slack message is a person's, maybe Oliver's) stays with the keeper", _router.build_side_target(cx.index["a40"], bs("v10", "slack:C0000000001"), KEY, cx) == "")
check("…and a GitHub one is the builder's", _router.build_side_target(cx.index["a40"], bs("v11", "github:example-owner/stackshot#4"), KEY, cx) == "osprey-x")
# 2y: an anchor held by ANOTHER project's page (a keeper there) and scoped to one open item of this project, whose mover is this project's front agent: the notice's target
# (anchors.routes) must not name that mover, or anchor-item would read it against the holding page's roster, find no builder there and pass the notice to the front agent unmarked
from stackshot.anchors import anchors as _anc_y
_reg0, _anc0 = (T / "store/projects.json").read_text(), (T / "store/anchors.json").read_text()
try:
    _pj = json.loads(_reg0); _pj["pages"]["projects/other"] = {**_pj["pages"]["projects/alpha"], "title": "Other", "name": "Other", "session": "work-other", "agents": {}, "back_agents": {}}
    (T / "store/projects.json").write_text(json.dumps(_pj))
    OTHER_URL = R_BASE + "25"
    (T / "store/anchors.json").write_text(json.dumps({**json.loads(_anc0), "projects/other": [{"url": OTHER_URL, "items": ["a40"], "added": 1}]}))
    cx_o = _router.Context()
    _rt = _anc_y.routes().get(_anc_y.anchor_id(OTHER_URL)) or []
    check("2y: the route of an anchor held by another project's page, scoped to alpha's a40 (moved by alpha's front agent): the keeper of that page, a project-wide target",
          len(_rt) == 1 and _rt[0]["session"] == "work-other" and _rt[0]["project"] == "projects/other" and _rt[0]["target"] == "project-wide", _rt)
    n_o = notice("y1", who="kim", text="commented: why this?", etype="comment", anchor=_anc_y.anchor_id(OTHER_URL), url=OTHER_URL, target=_rt[0]["target"] if _rt else "", label="GitHub stackshot#25")
    ln = _router.code_rule("projects/other", n_o, "projects/other", cx_o, [])
    check("…and the router does not pass that notice to alpha's front agent (not anchor-item's, not to osprey-main): it takes the path a project-wide anchor's notice takes",
          ln is None or (ln["rule"] != "anchor-item" and ln["target"] != "osprey-main"), ln)
    ln = _router.code_rule("projects/other", {**n_o, "id": "y2", "target": "for osprey-main"}, "projects/other", cx_o, [])
    check("…whereas the target the earlier code wrote ('for osprey-main') did reach anchor-item and the front agent (the guard this test stands for)", ln and ln["rule"] == "anchor-item" and ln["target"] == "osprey-main", ln)
finally:
    (T / "store/projects.json").write_text(_reg0); (T / "store/anchors.json").write_text(_anc0)

# the builder's own board notices about an item whose keeper of record is a front agent (telling.tell_owner_change records them as a message to the project): no front turn
instance =str(_cfg.get("instance", "name") or "stackshot")
def board_msg(nid, writer, what): return {"id": nid, "ts": 1000.0, "kind": "message", "label": "message to projects/alpha", "who": instance, "to": "", "target": "project-wide", "pilot": True, "live": True,
                                         "text": f"[board] a40 [home] item 40: {writer} {what} (keeper of record osprey-main may need to act) → https://board.example.org/items/a40"}
ln = _router.code_rule(KEY, board_msg("b1", "osprey-x", "set next: PR 26 is up"), KEY, cx, [])
check("2zz: the builder's own update of a front agent's item (a `[board]` notice) is merged: it is the writer, the notice goes to nobody", ln and ln["rule"] == "message-item" and ln["ruling"] == "merged" and not ln["target"], ln)
ln = _router.code_rule(KEY, board_msg("b2", "home-beta", "set next: look at PR 26"), KEY, cx, [])
check("…a notice from another session about the item goes to the builder, not to the front agent", ln and ln["rule"] == "message-item" and ln["ruling"] == "passed" and ln["target"] == "osprey-x", ln)
cx_nbb = _router.Context(); cx_nbb.reg[KEY] = {**cx_nbb.reg[KEY], "agents": {**AGENTS, "osprey-x": "keeps the page"}}      # a background agent that is no builder
ln = _router.code_rule(KEY, board_msg("b3", "osprey-x", "set next: [for Oliver] PR 26 is up, merge it?"), KEY, cx_nbb, [])
check("…with no builder (a background agent that does not build), only a notice that is for Oliver reaches the front agent; a plain one is merged", ln and ln["ruling"] == "passed" and ln["for_owner"] and ln["target"] == "osprey-main", ln)
ln = _router.code_rule(KEY, board_msg("b4", "osprey-x", "set next: PR 26 is up"), KEY, cx_nbb, [])
check("…(no builder, a plain notice, no front turn)", ln and ln["ruling"] in ("merged", "held") and not ln["target"], ln)
# the receiver puts head and author on the event; the hub's send records them in the routing log
ghr = __import__("stackshot.anchors.anchorhub.github", fromlist=["_"])
G = {}; caught = []
def _gh(args, capture_output=True, text=True, timeout=30):
    a = [x for x in args[2:] if x != "-i"]; path = a[0]; cond = "-i" in args
    if path not in G: return types.SimpleNamespace(returncode=1, stdout="", stderr="gh: Not Found (HTTP 404)")
    body = json.dumps(G[path])
    return types.SimpleNamespace(returncode=0, stdout=("HTTP/2.0 200 OK\netag: \"x\"\n\n" + body) if cond else body, stderr="")
class _Stop(Exception): pass
def _no_sleep(s): raise _Stop()
_sub, _thr, _tim = ghr.subprocess, ghr.threading, ghr.time
ghr.subprocess = types.SimpleNamespace(run=_gh)
ghr.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)))
ghr.time = types.SimpleNamespace(time=time.time, sleep=_no_sleep)
R = "/repos/example-owner/stackshot"
hub = core.Hub(); hub.write_status = lambda: None; evs = []; hub.emit = lambda ev: evs.append(ev); hub.bindings = {ANCHOR: {S}}
G.update({"/user": {"login": "example-owner"},
          f"{R}/pulls/4": {"head": {"sha": "a" * 40, "ref": "osprey-x/fewer-front-wakes"}, "user": {"login": "example-owner"}, "base": {"repo": {"id": 7}}},
          f"{R}/commits/{'a' * 40}/check-runs?per_page=100": {"check_runs": [{"name": "suites", "status": "completed", "conclusion": "success"}]},
          f"{R}/issues/4": {"state": "open", "comments": 0, "updated_at": "2026-10-28T00:00:00Z", "title": f"board#{BID_B}: a thing", "html_url": PR, "pull_request": {"merged_at": None}}})
def one_pass():
    try: caught[0]()
    except _Stop: pass
try:
    ghr.run(hub); one_pass()
    G[f"{R}/pulls/4"] = {"head": {"sha": "b" * 40, "ref": "osprey-x/fewer-front-wakes"}, "user": {"login": "example-owner"}}
    G[f"{R}/commits/{'b' * 40}/check-runs?per_page=100"] = {"check_runs": [{"name": "suites", "status": "completed", "conclusion": "failure"}]}
    G[f"{R}/issues/4"] = {**G[f"{R}/issues/4"], "comments": 1, "updated_at": "2026-10-28T01:00:00Z"}
    G[f"{R}/issues/4/comments?since=2026-10-28T00:00:00Z&per_page=20"] = [{"user": {"login": "kim"}, "body": "why this?", "html_url": PR + "#c1", "created_at": "2026-10-28T01:00:00Z"}]
    one_pass()
finally:
    ghr.subprocess, ghr.threading, ghr.time = _sub, _thr, _tim
check("2h: the receiver's CI failure and comment events carry the PR's head branch and author", sorted((e.etype, e.head, e.author) for e in evs)
      == [("ci_failed", "osprey-x/fewer-front-wakes", "example-owner"), ("comment", "osprey-x/fewer-front-wakes", "example-owner")], [(e.etype, e.head, e.author) for e in evs])
core._ROUTES = {ANCHOR: [{"project": KEY, "session": S, "target": "for osprey-main", "pilot": True, "filter": ""}]}
hub2 = core.Hub(); hub2.write_status = lambda: None; hub2.deliver = lambda anchor, session, text: None; hub2.holds = lambda project, session: True
n0 = len(routing.read(KEY)); hub2.send(ANCHOR, S, "[anchor] x", evs[0], "failed"); rows_ = routing.read(KEY)[n0:]
check("2i: the hub's routing record keeps the head and the commit author, so the router can read them", len(rows_) == 1 and rows_[0].get("head") == "osprey-x/fewer-front-wakes" and rows_[0].get("author") == "example-owner", rows_)
check("…and the event's type (etype), which anchor-ci reads", evs[0].etype in ("ci_failed", "comment") and rows_[0].get("etype") == evs[0].etype, (rows_, evs[0].etype))
ev2 = core.Event(anchor=ANCHOR, kind="github-state", title="t", who="CI", text="x", url=PR)
n0 = len(routing.read(KEY)); hub2.send(ANCHOR, S, "[anchor] y", ev2, "x"); rows_ = routing.read(KEY)[n0:]
check("…an event with no head records none (a Slack or Drive notice, an older receiver)", len(rows_) == 1 and "head" not in rows_[0] and "author" not in rows_[0] and "etype" not in rows_[0], rows_)
check("…the routing record built by the router's rule carries the notice through (end to end: the recorded row, ruled)",
      (lambda r: r and r["rule"] == "anchor-builder" and r["target"] == "osprey-x")(_router.code_rule(KEY, {**routing.read(KEY)[n0 - 1], "kind": "anchor"}, KEY, cx, [])), routing.read(KEY)[n0 - 1:])

# the hub's follow-up for a burst keeps what the router decides by: the types of the whole burst, its senders, and an earlier text that names Oliver
hub3 = core.Hub(); hub3.write_status = lambda: None; hub3.deliver = lambda anchor, session, text: None; hub3.holds = lambda project, session: True; hub3.bindings = {ANCHOR: {S}}
def gev(who, text, etype): return core.Event(anchor=ANCHOR, kind="github", title="stackshot#4", who=who, text=text, url=PR, etype=etype, head="fix/x", author="example-owner")
def burst(*evs_):
    hub3.pending.clear(); n0_ = len(routing.read(KEY))
    for e_ in evs_: hub3.emit(e_)
    for p_ in hub3.pending.values(): p_["first"] -= 100000
    hub3.tick()
    return routing.read(KEY)[n0_:]
rows_ = burst(gev("kim", "first", "pr_synchronize"), gev("lee", "why this?", "comment"), gev("CI", "failed on abc1234: 1 of 5 checks — suites", "ci_failed"))
check("2i2: a comment, then a CI result, then the tick: the follow-up is one notice whose event type is the burst's, comment+ci_failed, and whose senders are both",
      len(rows_) == 2 and rows_[1].get("etype") == "comment+ci_failed" and rows_[1].get("who") == "lee, CI" and rows_[1]["text"].startswith("2 more, the last: failed on"), rows_)
n_ = {**rows_[1], "kind": "anchor"}
check("…the router does not read it as a CI notice (so anchor-ci does not take it) and it is not on the build-side whitelist: the item's keeper has it", not _router.is_ci_notice(n_) and not _router.is_build_news(n_)
      and (lambda r: r and r["rule"] == "anchor-item" and r["target"] == "osprey-main")(_router.code_rule(KEY, n_, KEY, cx, [])), n_)
rows_ = burst(gev("kim", "first", "pr_synchronize"), gev("lee", "@example-owner can you look?", "comment"), gev("CI", "failed on abc1234: 1 of 5 checks — suites", "ci_failed"))
check("2i3: a burst whose earlier text names Oliver carries that text in the recorded gist, so the router checks the combined text", len(rows_) == 2 and rows_[1]["text"].startswith("2 more, earlier: @example-owner can you look? | the last: failed on")
      and rows_[1].get("etype") == "comment+ci_failed+other" and not _router.is_build_news({**rows_[1], "kind": "anchor"}), rows_)
rows_ = burst(gev("kim", "first", "pr_synchronize"), gev("CI", "failed on abc1234: 1 of 5 checks — suites", "ci_failed"), gev("CI", "failed on def5678: 1 of 5 checks — suites", "ci_failed"))
check("…a burst of CI results alone keeps etype ci_failed and sender CI (anchor-ci's)", len(rows_) == 2 and rows_[1].get("etype") == "ci_failed" and rows_[1].get("who") == "CI" and _router.is_ci_notice({**rows_[1], "kind": "anchor"}), rows_)
rows_ = burst(gev("kim", "first", "pr_synchronize"), gev("lee", "ok", ""), gev("CI", "failed on abc1234", "ci_failed"))
check("…an event with no type reads `other` in the burst's types", len(rows_) == 2 and rows_[1].get("etype") == "other+ci_failed", rows_)

# ---- 3. the hand-back, held for a close to cancel it
HELDF = T / "state/handback-held.json"
def held(): return json.loads(HELDF.read_text()) if HELDF.exists() else {}
def hb_notes(gid, since=0): return [x for x in (settle() or pushes()[since:]) if x[0] in (X, "osprey-x") and "a front agent, alone" in x[1] and re.search(rf"\b{gid}\b", x[1])]      # a front agent keeper is not handed the item: its builder is told
def hb_pushes(gid, since): return [x for x in to(A, since) if "back with you alone" in x[1] and re.search(rf"\b{gid}\b", x[1])]
_cfg.CFG.setdefault("board", {}).pop("handback_hold_seconds", None)
check("3a: the hold defaults to 180 seconds and is set by [board] handback_hold_seconds", telling.handback_hold_s() == 180.0, telling.handback_hold_s())
p0, n0 = len(pushes()), len(pushes()); t0 = time.time()
out = server._update("a20", needs=["osprey-main"], next="osprey-main: over to you", sender="osprey-front2"); settle()
check("3b: another front agent hands the item back to the front agent keeper alone: nothing is pushed yet (not to the keeper, not to the builder), the line is held, and the reply says the builder is told, not the keeper",
      not hb_notes("a20", n0) and not hb_pushes("a20", p0) and len(held()) == 1 and "in 3 minutes unless you close a20 first" in out and "its builder osprey-x is told it is back with them alone, not them" in out, (held(), out))
p0, n0 = len(pushes()), len(pushes())
out_b = server._update("a30", needs=["osprey-main"], next="osprey-main: builder's own", sender="osprey-x"); settle()
check("3b negative: the builder's own hand-back to the front agent keeper tells nobody and holds nothing: the board shows it",
      not hb_notes("a30", n0) and not hb_pushes("a30", p0) and len(held()) == 1 and "nobody is told" in out_b, (held(), out_b))
p0, n0 = len(pushes()), len(pushes())
h = [v for v in held().values() if v["gid"] == "a20"][0]
check("…the held line is the one the keeper would have heard, due 180 seconds on", h["gid"] == "a20" and h["oid"] == A and h["line"].startswith("[stackshot] a20 is back with you alone (handed back by osprey-front2): [home] item 20; next: ")
      and h["line"].endswith("/items/a20") and abs(h["due"] - (t0 + 180)) < 30, h)
check("3c: the tick before the window ends sends nothing", telling.handback_tick(now=t0 + 60) == [] and len(held()) == 1 and not hb_notes("a20", n0))
out = _wt_update.stackshot_update("a20", status="completed", outcome="done", reason="PR 26 is live", description="- The thing works and is in use", sender="osprey-x", done=[2]); settle()      # the hand-back line names the front agent: the builder's close marks it itself (done=[2]), as a close no longer settles another session's step
check("3d: the builder closes the item inside the window: the held hand-back is dropped, and the keeper gets only the close line (one marked message)",
      held() == {} and not hb_notes("a20", n0) and not hb_pushes("a20", p0) and len(to(A, p0)) == 1 and "closed by osprey-x: done (PR 26 is live)" in to(A, p0)[0][1] and to(A, p0)[0][1].startswith(MK + " "), (held(), to(A, p0)))
check("…and the tick after the window sends nothing more", telling.handback_tick(now=t0 + 400) == [] and not hb_notes("a20", n0) and len(to(A, p0)) == 1)
# no close: delivered when the window ends
p0, n0 = len(pushes()), len(pushes()); t1 = time.time()
server._update("a21", needs=["osprey-main"], next="osprey-main: review the PR", sender="osprey-front2"); settle()
check("3e negative: a hand-back with no close in the window is delivered when it ends, to the builder (not the keeper), reworded, once",
      telling.handback_tick(now=t1 + 100) == [] and telling.handback_tick(now=t1 + 181) == ["a21"] and len(hb_notes("a21", n0)) == 1 and held() == {}
      and hb_notes("a21", n0)[0][1].startswith("[stackshot] a21 is back with osprey-main, a front agent, alone (handed back by osprey-front2)") and "told to you, not to osprey-main" in hb_notes("a21", n0)[0][1]
      and not hb_pushes("a21", p0) and telling.handback_tick(now=t1 + 999) == [], (held(), hb_notes("a21", n0), to(A, p0)))
# a restart loses nothing: the held line is a file
server._update("a23", needs=["osprey-main"], next="osprey-main: first", sender="osprey-front2"); settle()
f1 = held(); k = list(f1)[0]
server._update("a23", needs=["osprey-x"], next="osprey-x: more work", sender="osprey-main"); settle()
server._update("a23", needs=["osprey-main"], next="osprey-main: second", sender="osprey-front2"); settle()
f2 = held()
check("3f: a second hand-back of the same item inside the window is the same held line, with the first due time (one line for the item)",
      list(f2) == [k] and f2[k]["due"] == f1[k]["due"], (f1, f2))
n0 = len(pushes()); telling.handback_tick(now=f2[k]["due"] + 1)
check("…and one line is delivered for the two", len(hb_notes("a23", n0)) == 1, hb_notes("a23", n0))
n0 = len(pushes())
server._update("a24", needs=["osprey-main"], next="osprey-main: look", sender="osprey-front2"); settle()
server._update("a24", needs=["osprey-main", "osprey-x"], next="osprey-x: more", sender="osprey-main"); settle()
telling.handback_tick(now=time.time() + 999)
check("3g negative: an item that moved on while the line was held (the builder is named again) is not announced as back with the keeper", not hb_notes("a24", n0) and held() == {}, (hb_notes("a24", n0), held()))
n0 = len(pushes())
server._update("a25", needs=["osprey-main"], next="osprey-main: look", sender="osprey-front2"); settle()
server._update("a25", needs=["decision"], ask="Decide: whether to ship · Recommend: yes · Stakes: none · By: no date", sender="osprey-x"); settle()
telling.handback_tick(now=time.time() + 999)
check("…nor one that now waits on his decision", not hb_notes("a25", n0) and held() == {}, (hb_notes("a25", n0), held()))
# 0 = no hold
_cfg.CFG["board"]["handback_hold_seconds"] = 0; n0 = len(pushes())
out = server._update("a26", needs=["osprey-main"], next="osprey-main: look", sender="osprey-front2"); settle()
check("3h: handback_hold_seconds = 0 tells the builder at once, as before the hold", len(hb_notes("a26", n0)) == 1 and held() == {} and "is told it is back with them alone, not them: a front agent is not handed an item on stackshot's own motion" in out and "unless you close" not in out, (out, hb_notes("a26", n0)))
_cfg.CFG["board"].pop("handback_hold_seconds", None)
# the close of a different item leaves the held line alone
n0 = len(pushes()); t3 = time.time()
server._update("a27", needs=["osprey-main"], next="osprey-main: look", sender="osprey-front2"); settle()
_wt_complete.stackshot_complete("a28", outcome="done", reason="done", description="- done", sender="osprey-x"); settle()
check("3i negative: closing another item does not drop it", len(held()) == 1 and telling.handback_tick(now=t3 + 181) == ["a27"] and len(hb_notes("a27", n0)) == 1, (held(), hb_notes("a27", n0)))
# a reopened item is open again: a new hand-back is held again
server._update("a20", status="open", next="osprey-x: more", needs=["osprey-x"], then="osprey-main", sender="osprey-main"); settle()
p0 = len(pushes()); server._update("a20", needs=["osprey-main"], next="osprey-main: look again", sender="osprey-front2"); settle()
check("…a reopened item's new hand-back is held like any other", len(held()) == 1, held())

# the held line is never lost: a write that fails sends at once; a tick sends first and removes after (at least once)
n0 = len(pushes()); k0 = len(held()); _real_w = telling.handback_write
telling.handback_write = lambda d: False
try:
    out = server._update("a29", needs=["osprey-main"], next="osprey-main: look", sender="osprey-front2"); settle()
finally:
    telling.handback_write = _real_w
check("3j negative: when the held line cannot be written it is sent at once, never lost (the reply does not promise a window)",
      len(hb_notes("a29", n0)) == 1 and len(held()) == k0 and "unless you close" not in out and "told it is back with them alone" in out, (out, hb_notes("a29", n0), held()))
def rehold(gid):          # the item goes to the builder and comes back: a fresh held line
    server._update(gid, needs=["osprey-x"], next="osprey-x: more work", sender="osprey-main"); settle()
    server._update(gid, needs=["osprey-main"], next="osprey-main: look", sender="osprey-front2"); settle()
n0 = len(pushes()); _real_send = telling.handback_send; calls = []
def _send_fails(rec): calls.append(rec["gid"]); raise OSError("router log full")
telling.handback_send = _send_fails
try:
    sent = telling.handback_tick(now=time.time() + 999)
finally:
    telling.handback_send = _real_send
left = held()
check("3k negative: a send that fails keeps the line (with its try count) for the next tick, and sends nothing", sent == [] and calls == ["a20"] and len(left) == 1 and list(left.values())[0].get("tries") == 1 and not hb_notes("a20", n0), (sent, calls, left))
check("…the next tick sends it and removes it", telling.handback_tick(now=time.time() + 999) == ["a20"] and len(hb_notes("a20", n0)) == 1 and held() == {}, (held(), hb_notes("a20", n0)))
rehold("a21"); n0 = len(pushes()); telling.handback_write = lambda d: False
try:
    first = telling.handback_tick(now=time.time() + 999)
finally:
    telling.handback_write = _real_w
check("3l: the tick sends first and removes after: when the removal fails the line was sent and stays, so the next tick sends it again (at least once, never zero)",
      first == ["a21"] and len(hb_notes("a21", n0)) == 1 and len(held()) == 1, (first, hb_notes("a21", n0), held()))
check("…and the next tick sends it again and clears the file", telling.handback_tick(now=time.time() + 999) == ["a21"] and len(hb_notes("a21", n0)) == 2 and held() == {}, (hb_notes("a21", n0), held()))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
