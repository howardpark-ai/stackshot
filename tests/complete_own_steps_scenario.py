"""Scenario test for "a session's close ticks only its own open steps" (the complete tool, and update with status=completed) — fixture data, no live store, no network, no server socket.

Before, a close marked every step still open, another session's included: a builder that closed its item after its own step silently ticked a step that another session still owed. Now:
  1  an item with an open step of the sender and an open step of another session: the complete tool and the update tool refuse the close, name the other session's step in plain words and say what to do; nothing is written (the item
     stays open, both steps stay open); the refusal holds for every outcome, and for the steps a legacy item stored with no writer (the creator's)
  2  the close goes through, ticking only the sender's own steps, when no other session's step is open (the other's step is already marked, or the call marks it itself: done=[n] / dropped=[n] with the close), and an owner's step
     in the list never holds it up (a close settles it, as before)
  3  the server's own closes (a done check, a watcher's drop, a script's close) are unchanged: they settle every open step
  4  the text agents learn it from (complete and update) says a close ticks only the sender's own steps

    tests/run-suite complete_own_steps        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="ownsteps-"); T = pathlib.Path(tmp)      # removed (and flock-held while the suite runs) by _scratch, pass or fail
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time(); DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
def proj(session, agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": proj("home-stew", {"home-front": "the front", "team-back": "the back"}, {"team-back": "the back"})}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
OUT = "- The thing works now\n- It lives here\n- Finished when it ships"
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.model import steps as S; from stackshot.model import nextlines as NL
OWNER = server.OWNER
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda gid, owner, note, tag="wake", result=None: None
server._tell_check_closed = lambda gid, item, label: []

MINE, THEIRS = "home-front: build it", "team-back: verify the deploy"
def item(i, lines=(MINE, THEIRS), writers=None, status="open", **meta):
    """An item of the front agent with the given next lines; `writers` (default: the front agent for a home-front line, the back agent for the others) are the sessions whose writes put the lines in next, None for a legacy item with no record."""
    text = "\n".join(lines)
    ws = writers or [U["home-front"] if ln.startswith("home-front:") else U["team-back"] for ln in lines]
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": text, "needs": ["team-back"]}
    if writers != "legacy": base["next_by"] = [[w, NL.key_of(ln)] for ln, w in zip(lines, ws)]
    base.update(meta)
    su = now0 - 10 * DAY
    (T / f"store/g/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                      "updated": su, "state_updated": su, "confirmed": su, "metadata": base}))
def rd(i): return json.loads((T / f"store/g/{i}.json").read_text())
def raw(i): return (T / f"store/g/{i}.json").read_text()
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1500]}" if got is not None else ""))
def sts(i): return [(x["status"], x.get("by") or "") for x in rd(i)["metadata"].get("steps") or []]
def kinds(i): return [k for k, _ in sts(i)]
def ref(i): return "board" + "#" + str(i)      # the tools take the item as board#N: built here, so the text carries no literal id shape
def complete(i, who="home-front", outcome="done", sup=""):
    return server.stackshot_complete(ref(i), outcome=outcome, reason="it ended", outcome_text=OUT, superseded_by=sup, sender=who)
def close_update(i, who="home-front", outcome="done", **kw):
    return server.stackshot_update(ref(i), status="completed", outcome=outcome, reason="it ended", outcome_text=OUT, sender=who, **kw)
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except server.ToolError as e:
        check(name, all(w in str(e) for w in want), str(e))
        return str(e)
    return ""

# ================================================================ 1. another session's open step holds the close back
item(1)
before = raw(1)
msg = refused("complete by the sender: refused, the other session's step is named, with who owes it", lambda: complete(1), "Refused", "team-back: verify the deploy", "owed by team-back", "stays open")
check("…the sender's own step is not named as the one in the way", "build it" not in msg, msg)
check("…the refusal says nothing is ticked and what to do: wait for that session, mark your own steps, or mark the step in the closing call", "nothing is ticked" in msg and "done=[n]" in msg and "dropped=[2]" in msg, msg)
check("…and wrote nothing: the item is open, the file is as it was", raw(1) == before and rd(1)["status"] == "open" and "steps" not in rd(1)["metadata"], rd(1))
item(2)
refused("update with status=completed: the same refusal", lambda: close_update(2), "team-back: verify the deploy", "stays open")
check("…and it wrote nothing", raw(2) == (T / "store/g/2.json").read_text() and rd(2)["status"] == "open", rd(2))
for n, oc in ((3, "dropped"), (4, "superseded")):
    item(n)
    refused(f"outcome {oc}: refused too", lambda: complete(n, outcome=oc, sup=ref(1) if oc == "superseded" else ""), "team-back: verify the deploy")
    check(f"…{oc}: the item is still open with both steps open", rd(n)["status"] == "open" and rd(n)["metadata"]["next"] == f"{MINE}\n{THEIRS}", rd(n))
item(5, lines=(THEIRS,))
refused("the sender has no step of its own and another's is open: refused", lambda: complete(5), "team-back: verify the deploy")
item(6, lines=(MINE, "team-back: verify the deploy", "home-stew: watch the release"), writers=[U["home-front"], U["team-back"], U["home-stew"]])
msg6 = refused("two other sessions' steps: both are named", lambda: complete(6), "mark those steps", "owed by team-back", "owed by home-stew", "verify the deploy", "home-stew: watch the release", "dropped=[2, 3]")
item(7, lines=(MINE, "home-stew: a line from before the record"), writers="legacy")
check("a legacy item (no writer record): its lines are the creator's, so the creator closes it as before", "completed" in complete(7) and kinds(7) == ["done", "done"] and rd(7)["status"] == "completed", sts(7))
item(8, lines=(MINE, "home-stew: a line from before the record"), writers="legacy")
refused("…and another session that is not the creator is refused for them", lambda: complete(8, who="team-back"), "Refused", "stays open")
item(9, lines=(MINE, THEIRS), writers=["home-front", "team-back"])      # the record stores a pane's name instead of the id
msg9 = refused("writers stored as names are told apart too", lambda: complete(9), "team-back: verify the deploy")
check("…and the sender's own step, stored under its pane name, is still its own (not named)", "build it" not in msg9, msg9)

# a step that opens with the sender's name is the sender's own, whoever wrote the line (a front agent writes `team-back: build it`, the builder closes)
item(30, lines=("team-back: build the thing",), writers=[U["home-front"]])
complete(30, who="team-back")
check("a step that opens with the closer's name, written by the creator, is the closer's own: the builder closes, the step is done by it", rd(30)["status"] == "completed" and sts(30) == [("done", "team-back")], sts(30))
item(31, lines=("team-back: build the thing",), writers=[U["home-front"]])
complete(31, who="home-front")
check("…and the creator that wrote it closes too (its writer)", rd(31)["status"] == "completed" and kinds(31) == ["done"], sts(31))
item(32, lines=("team-back: build the thing", "home-stew: watch the release"), writers=[U["home-front"], U["home-front"]])
msg32 = refused("a line the creator wrote that opens with a third session's name is that session's: the builder's close is refused for it alone", lambda: complete(32, who="team-back"), "owed by home-stew")
check("…and the builder's own step is not named", "build the thing" not in msg32 and "owed by team-back" not in msg32, msg32)
item(33, lines=("team-back: build the thing",), writers=[U["home-front"]])
close_update(33, who="team-back")
check("update with status=completed by the named session closes it as well", rd(33)["status"] == "completed", rd(33))
item(34, lines=(MINE, "the next step"), writers=[U["home-front"], U["team-back"]])
complete(34)
check("a line that names nobody owes nothing to anyone: it never holds a close up, and the close ticks it", rd(34)["status"] == "completed" and kinds(34) == ["done", "done"], sts(34))
item(35, lines=("team-back: build the thing",), writers=[U["home-front"]])
refused("another session than the one the step names is refused (the front agent's main, home-stew)", lambda: complete(35, who="home-stew"), "owed by team-back")

item(36, lines=("team-back: verify the deploy",), writers=["home-front"])      # written by the closer (stored under its pane name) for another session: its own by writer
complete(36)
check("a step the closer wrote for another session is the closer's own (writer stored as a pane name)", rd(36)["status"] == "completed" and kinds(36) == ["done"], sts(36))

# the owner's step in any form the model reads as his (config.owner_opener_rx: his name, an alias, a non-Latin alias, `you:`, `<owner> to …`) never holds a close up; a step of another session still does
from stackshot.core import config as _cfg
ALIASES = _cfg.owner_aliases()
check("the instance has a Latin and a non-Latin alias for the owner (the forms below are read from it, never typed here)", len(ALIASES) >= 2 and ALIASES[0].isascii() and not ALIASES[1].isascii(), ALIASES)
for k, owner_line in enumerate((f"{ALIASES[0]}: approve the deploy", f"{ALIASES[1]}: approve the deploy", "you: approve the deploy", f"{OWNER} to run: the deploy script", f"{ALIASES[0]} to review: the deploy"), start=40):
    item(k, lines=(MINE, owner_line), writers=[U["home-front"], U["team-back"]])
    complete(k)
    check(f"an owner's step opened as `{owner_line.split(':')[0]}:` by another session is the owner's, not another session's: the close goes through and ticks it", rd(k)["status"] == "completed" and kinds(k) == ["done", "done"], (owner_line, sts(k)))
item(46, lines=(MINE, "you: approve the deploy", THEIRS), writers=[U["home-front"], U["team-back"], U["team-back"]])
msg46 = refused("control: an owner's step and another session's step: the close is refused for the other session's step alone", lambda: complete(46), "owed by team-back", "verify the deploy")
check("…and the owner's step is not named in the refusal", "approve the deploy" not in msg46 and "owed by you" not in msg46, msg46)

# ================================================================ 2. what closes
item(10, lines=(MINE, "home-front: test it"))
out10 = complete(10)
check("only the sender's own steps are open: the close ticks them, by the sender", rd(10)["status"] == "completed" and kinds(10) == ["done", "done"] and {b for _, b in sts(10)} == {"home-front"} and "next" not in rd(10)["metadata"], (sts(10), out10[:200]))
item(11, steps=[{"text": THEIRS, "status": "done", "by": "team-back", "at": now0 - 100}], lines=(MINE,))
complete(11)
check("a step of another session that it marked itself earlier is left as it is (by, at): the close ticks only the sender's", rd(11)["status"] == "completed" and [(k, b) for k, b in sts(11)] == [("done", "team-back"), ("done", "home-front")] and rd(11)["metadata"]["steps"][0]["at"] == now0 - 100, sts(11))
item(12)
close_update(12, dropped=[2])
check("the closing call marks the other's step itself (dropped=[2]): the close goes through, that step is dropped, the sender's own is done, both by the sender", rd(12)["status"] == "completed" and kinds(12) == ["done", "dropped"] and {b for _, b in sts(12)} == {"home-front"}, sts(12))
item(13)
close_update(13, done=["team-back: verify the deploy"])
check("done=[text] on the other's step with the close: it is done, by the sender", rd(13)["status"] == "completed" and kinds(13) == ["done", "done"], sts(13))
item(14)
close_update(14, outcome="dropped", dropped=[2])
check("outcome dropped with the other's step marked: own and marked steps are dropped", rd(14)["status"] == "completed" and kinds(14) == ["dropped", "dropped"], sts(14))
item(15, lines=(MINE, f"{OWNER}: read it", ), writers=[U["home-front"], U["team-back"]])
complete(15)
check(f"an owner's step ({OWNER}'s) never holds the close up: it is settled by the close, as before", rd(15)["status"] == "completed" and kinds(15) == ["done", "done"], sts(15))
item(16)
out16 = server.stackshot_update(ref(16), sender="home-front", done=[1])
check("marking your own step with update leaves the item open and the other's step open (the way the refusal points to)", rd(16)["status"] == "open" and rd(16)["metadata"]["next"] == THEIRS and kinds(16) == ["done", "open"], (sts(16), rd(16)["metadata"]))
complete(16, who="team-back")
check("…then the other session closes it: its own step is ticked, by it", rd(16)["status"] == "completed" and kinds(16) == ["done", "done"] and sts(16)[1][1] == "team-back", sts(16))
item(17)
check("a close the closer does not mark, with a step of its own and the other's marked in the same call by name: goes through", "completed" in close_update(17, dropped=[THEIRS]), None)

# ================================================================ 3. the server's own closes
item(20); item(21); item(22)
server._check_close("g20", rd(20), "a done check", time.time())
check("a done check's close settles every open step, by the server (unchanged)", kinds(20) == ["done", "done"] and {b for _, b in sts(20)} == {server.NAME} and rd(20)["metadata"]["outcome"] == "done", sts(20))
it21 = rd(21); server._watch_close(it21, "dropped on his answer", time.time())
check("a watcher ask's drop settles every open step, by the server (unchanged)", [x["status"] for x in it21["metadata"]["steps"]] == ["dropped", "dropped"], it21["metadata"])
server._update(ref(22), status="completed", outcome="done", reason="it ended", outcome_text=OUT, sender="a script on testbox")
check("a script's close (no session's tool call) settles every open step (unchanged)", rd(22)["status"] == "completed" and kinds(22) == ["done", "done"], sts(22))

# ================================================================ 4. the text
import asyncio
desc_ = {t.name: t.description for t in asyncio.run(server.mcp.list_tools())}
for n in ("complete", "update"):
    check(f"text: {n} says a close ticks only the closer's own steps and leaves another session's open", "ticks only the steps that are still open and are yours" in desc_[n] and "another session" in desc_[n] and "marks every step" not in desc_[n], desc_[n][:300])
check("text: the rule a refused close appends says it too", "ticks only the steps that are still open and are yours" in server._CLOSE_REFUSAL and "marks every step" not in server._CLOSE_REFUSAL, None)
check("text: complete tells where to mark another session's step (update, done or dropped with the close)", "mark it in the closing call with update" in desc_["complete"] and "dropped=[n]" in desc_["complete"], None)

print(("ok" if not fails else "FAILED") + f": complete own steps scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
