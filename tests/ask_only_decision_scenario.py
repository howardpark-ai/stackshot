"""Scenario test for the `update` write that sets only an ask and its options on an item that is not yet on the owner's call — fixture data, no live store, no network, no server socket.

  1  an ask with options and no `needs` on an open item the session holds: the write is accepted, the server adds the decision need, the mover becomes the owner (the path
     needs=decision with an ask takes), the question is on the owner's move, and the reply says what the server did
  2  options alone beside a stored ask add the need too; with no ask anywhere they add none
  3  the same write on a parked item (a wait is set): the ask and its options are stored, the wait is untouched, no decision need is added, and the reply says he does not have the
     question and that it does not reach his move while the item is parked (unpark with clear_wait=true and needs=decision in one write, which this suite runs)
  4  what is left alone: an item already on his call, a write with no ask, a write that gives its own needs or state (needs, status, step); status=open beside an ask, and an item
     whose needs name a session, still gain the need (the session stays)
  5  an ask with a Recommend that is no yes or no and no options is refused, and the refusal says the ask needs options (or a yes/no Recommend)

    uv run tests/ask_only_decision_scenario.py        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="askform-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite's writes replace next wholesale; the checklist has its own suite
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-stew")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time(); H = 3600.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "seen": now0} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active",
                                                                                "board": [], "board_open": 0, "agents": {"home-front": "the front", "team-back": "the back"}, "back_agents": {"team-back": "the back"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
(T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * 86400, "seen": {}, "reported": []}))

DESC = "- A decision on the home-brain work\n- Done when decided"
LINK = "https://example.test/projects/home-brain/design"
MD = f"[design]({LINK})"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def item(i, status="open", desc=None, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] home-brain work {i}", "description": desc or DESC, "status": status, "updated": now0 - 3 * H,
                                                      "state_updated": now0 - 3 * H, "confirmed": now0 - 3 * H,
                                                      "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "Oliver: answer the ask", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
raw = lambda i: (T / f"store/a/{i}.json").read_text()
nfiles = lambda: len(list((T / "store/a").glob("*.json")))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.web import home
from stackshot.service import update as _update_svc
from stackshot.core import config as _cfg
from stackshot.core import call_log as _cl
from stackshot.model import decision_gates as _dg
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import create as _wt_create
from stackshot.service import telling
from stackshot.web import render as _rmod
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda *a, **k: None
upd = lambda i, sender="home-front", **kw: _update_svc._update(f"a{i}", sender=sender, **kw)
ask_of = lambda decide, rec="approve", stakes="a day either way": f"Decide: {decide} · Recommend: {rec} · Stakes: {stakes} · By: no date"



OPTS = [{"label": "Fast rollout", "line": "Roll out in one week.", "recommended": True}, {"label": "Slow rollout", "line": "Roll out over a month.", "recommended": False}]
ASK = ask_of("ship the fix", rec="Fast rollout")
meta = lambda i: rd(i)["metadata"]
needs_of = lambda i: [str(x).lower() for x in meta(i).get("needs") or []]

# ================================================================ 1. an ask with options, written alone
item(1, next="home-front: write the draft", mover="home-front")
out = upd(1, ask=ASK, options=OPTS)
check("1 the write is accepted", out.startswith("updated a1"), out)
check("1 the decision need is added", needs_of(1) == ["decision"], meta(1).get("needs"))
check("1 the ask and the options are stored", meta(1).get("ask") == ASK and [o["label"] for o in meta(1).get("options") or []] == ["Fast rollout", "Slow rollout"], meta(1))
check("1 the mover is the owner, the session takes it back after his answer", meta(1).get("mover") == "Oliver" and meta(1).get("then") == "home-front", meta(1))
check("1 the owner has a step of his own", "Oliver:" in str(meta(1).get("next") or ""), meta(1).get("next"))
check("1 the reply says what the server did", "added the decision need" in out and "the question is on his move now" in out, out)

# the same item through the older form, needs=decision beside the ask: the two end alike
item(2, next="home-front: write the draft", mover="home-front")
upd(2, needs=["decision"], ask=ASK, options=OPTS)
same = lambda k: meta(1).get(k) == meta(2).get(k)
check("1 the alone form and the needs form leave the same needs, mover, then and options", all(same(k) for k in ("needs", "mover", "then", "options", "ask")), (meta(1), meta(2)))

# ================================================================ 2. options alone beside an ask the item already holds
item(3, next="home-front: write the draft", mover="home-front", ask=ASK)
out = upd(3, options=OPTS)
check("2 options alone beside a stored ask add the decision need", needs_of(3) == ["decision"] and meta(3).get("mover") == "Oliver", meta(3))
check("2 …and the reply says so", "added the decision need" in out, out)
item(4, next="home-front: write the draft", mover="home-front")
out = upd(4, options=OPTS)
check("2 options with no ask anywhere add no decision need", "decision" not in needs_of(4), meta(4))

# ================================================================ 3. a parked item keeps its wait
item(5, next="home-front: wait for the run", mover="home-front", hold=True, wake="2099-01-01", wait_kind="time")
before = {k: meta(5).get(k) for k in ("wake", "hold", "wait_kind", "until", "mover")}
out = upd(5, ask=ASK, options=OPTS)
after = {k: meta(5).get(k) for k in before}
check("3 the ask and the options are stored on a parked item", meta(5).get("ask") == ASK and bool(meta(5).get("options")), meta(5))
check("3 no decision need is added", "decision" not in needs_of(5), meta(5).get("needs"))
check("3 the wait and the mover are untouched", before == after, (before, after))
check("3 the reply says the question is not with him and does not reach his move while parked", "does not have the question" in out and "while it is parked" in out and "clear_wait=true (and clear_hold=true if it holds) and needs=decision" in out, out)
check("3 …and does not claim the decision need", "added the decision need" not in out, out)
out = upd(5, clear_wait=True, clear_hold=True, needs=["decision"])
check("3 unparking with clear_wait=true and needs=decision, as the reply says, puts the stored ask on his move", needs_of(5) == ["decision"] and meta(5).get("mover") == "Oliver" and meta(5).get("ask") == ASK, (meta(5), out))

# ================================================================ 4. what is left alone
item(6, next="home-front: write the draft", mover="home-front", needs=["decision"], ask=ASK, options=OPTS)
out = upd(6, ask=ask_of("ship the fix today", rec="Fast rollout"))
check("4 an item already on his call gets no second need and no note", needs_of(6) == ["decision"] and "added the decision need" not in out, (meta(6).get("needs"), out))
item(7, next="home-front: write the draft", mover="home-front")
out = upd(7, priority="p3")
check("4 a write with no ask adds no decision need", "decision" not in needs_of(7) and "added the decision need" not in out, out)
item(8, next="home-front: write the draft", mover="home-front", needs=["team-back"])
upd(8, needs=["team-back"], ask=ASK, options=OPTS)
check("4 a write that gives its own needs is taken as given", "decision" not in needs_of(8), meta(8).get("needs"))

item(9, next="home-front: write the draft", mover="home-front", needs=["team-back"])
out = upd(9, ask=ASK, options=OPTS)
check("4 an item whose needs name a session gains the decision need and keeps the session", needs_of(9) == ["decision", "team-back"], (meta(9).get("needs"), out))
item(10, next="home-front: write the draft", mover="home-front")
out = upd(10, status="open", ask=ASK, options=OPTS)
check("4 status=open beside an ask changes no state, so the need is added", needs_of(10) == ["decision"] and "added the decision need" in out, (meta(10).get("needs"), out))
item(11, next="home-front: write the draft", mover="home-front")
out = upd(11, mover="home-front", ask=ASK, options=OPTS)
check("4 a call that states a state of its own (mover) is taken as given: no need added", "decision" not in needs_of(11) and "added the decision need" not in out, (meta(11).get("needs"), out))

# ================================================================ 5. an ask the page cannot draw
item(12, next="home-front: write the draft", mover="home-front")
refused("5 a Recommend that is no yes or no with no options is refused, and the refusal says the ask needs options", lambda: upd(12, ask=ask_of("pick a lane", rec="the east lane")), "Refused: this ask lists no options", "yes or no")
check("5 …and nothing was added", "decision" not in needs_of(12) and not meta(12).get("ask"), meta(12))

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": ask-only decision scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
