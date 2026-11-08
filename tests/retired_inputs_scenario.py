"""Scenario test for the retired item-state inputs of update and create (state, clear_state, party, chase, end, proof, chase_note) — fixture data, no live store, no network, no server socket.

An item stores alive or waiting directly now (the item model), so no call sets or clears one of the seven old state words or writes a field a state carried. Covers:

  1  module            retired_inputs: what counts as passed (an empty, false or null value does not), one refusal naming what to pass instead for each input, the state's own word answered by what it said
  2  refused           update and create through the MCP layer: each retired input is refused with that message, several at once in one message, next to otherwise valid arguments, and nothing is written
  3  empty_ok          a client that fills every parameter with its default (state "", clear_state false, chase_note "") is no call to refuse: the write goes through
  4  gone_from_tools   the tools' signatures and schemas list none of the seven, the descriptions teach none of them as an input, and supplies and step are still listed
  5  step_supplies     update(step=...) stores his step (the your-step state) and update(supplies=...) with after the blocked one, each refused without what it needs; a close drops them
  6  stored_stays      an item that stores an old state word, party, chase, end or proof keeps them through an unrelated write; get and the board read the same before and after
  7  unseated_dropped  a write that leaves an item unable to stand in its stored state drops the word with a note (no call can clear one), and keeps party, chase, end and proof
  8  routes            POST /client/state answers 400 with the refusal and writes nothing; client.py post state prints it and exits 1 without contacting the server
  9  no_chase          watchers.add_chase and states.hint are gone; a stored chase still counts (watchers.chased_out)

    tests/run-suite retired_inputs        → exit 0 / 1"""
import asyncio, io, json, os, re, sys, pathlib, time, logging, contextlib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="retiredin-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    import re as _re
    toml, n = _re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x", "secrets"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
ZONE_HOURS = 4      # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, letter="a", subject=None, desc=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": desc or DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su,
                                                              "metadata": {"owner": owner or U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing", **meta}}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def raw(i): return (T / f"store/a/{i}.json").read_bytes()
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.core import retired_inputs as RI; from stackshot.model import states; from stackshot.waits import watchers; from stackshot.fleet import client as _client
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda gid, owner, note, tag="wake": None
(T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
BACK, OTHER = "team-back", "home-other"
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
OWN = server.OWNER

from fastmcp import Client
async def _call(name, args):
    async with Client(server.mcp) as c:
        r = await c.session.call_tool(name, args)
        return bool(r.is_error), "".join(getattr(x, "text", "") for x in r.content)
def call(name, **args): return asyncio.run(_call(name, args))
def upd(i, **kw): return call("update", item_id=f"a{i}", sender="home-front", **kw)
def refused(name, res, *want):
    err, text = res
    check(name, err and "Refused" in text and all(w in text for w in want), text)

# ================================================================ 1 module
check("module: an empty, false or null value is not passed", RI.passed({"state": "", "clear_state": False, "chase": None, "party": "  ", "proof": [], "end": {}}) == [], RI.passed({"state": ""}))
check("module: a value is passed, in the refusal's order", RI.passed({"proof": "x", "state": "doing", "clear_state": True, "end": "2030-01-01"}) == ["state", "clear_state", "end", "proof"], RI.passed({"proof": "x", "state": "doing"}))
check("module: not a dict is nothing to refuse", RI.passed(None) == [] and RI.refusal("x") == "" and RI.refusal({"next": "a"}) == "", None)
WORD = {"doing": "mover=", "your-call": "needs=[\"decision\"]", "your-step": "step=", "outside": "wait_kind=\"relay\"", "blocked": "after=[", "parked": "hold=true", "verifying": "wait_basis=", "queued": "mover=<the builder>", "none": "clear_wait=true"}
for w, want in WORD.items():
    msg = RI.refusal({"state": w}, OWN)
    check(f"module: state={w} names its replacement ({want})", msg.startswith("Refused: state is a retired input") and want in msg and "Nothing was written" in msg, msg)
for f in ("clear_state", "chase", "chase_note", "party", "end", "proof"):
    msg = RI.refusal({f: "x" if f != "clear_state" else True}, OWN)
    check(f"module: {f} is named and answered", f.split("_")[0] in msg.split(":")[1] and "Instead:" in msg, msg)
many = RI.refusal({"state": "outside", "party": "Acme", "chase": "2030-01-01"}, OWN)
check("module: several inputs are one message listing each", many.startswith("Refused: state, chase, party are retired inputs") or "retired inputs" in many and many.count("\n") == 0, many)
check("module: {owner} in a replacement is the instance's owner, never a placeholder", "{owner}" not in RI.refusal({"state": "your-step"}, OWN) and OWN in RI.refusal({"state": "your-step"}, OWN), RI.refusal({"state": "your-step"}, OWN))

# ================================================================ 2 refused
item(1, needs=[BACK], mover=BACK)
item(2, needs=[BACK], mover=BACK)
b1 = raw(1)
CASES = (("state", {"state": "doing"}), ("state your-call", {"state": "your-call", "needs": ["decision"], "ask": "Decide: x · Recommend: y · Stakes: z · By: now"}),
         ("clear_state", {"clear_state": True}), ("chase", {"chase": day(3)}), ("chase_note", {"chase_note": "asked again"}), ("party", {"party": "Acme"}),
         ("end", {"end": day(3)}), ("proof", {"proof": "the dashboard is green"}))
for name, args in CASES:
    res = upd(1, **args)
    keys = [k for k in args if k in RI.RETIRED]
    refused(f"update: {name} is refused as retired, naming {keys[0]}", res, "retired input", keys[0], "Instead:")
check("update: …none of the refusals wrote anything", raw(1) == b1, None)
refused("update: several retired inputs are one refusal", upd(1, state="outside", party="Acme", chase=day(3)), "state, chase, party are retired inputs")
refused("update: …also next to arguments that would be fine alone", upd(1, priority="p2", next="team-back: carry on", state="doing"), "retired input", "state")
check("update: …and the priority and next were not written either", raw(1) == b1, None)
refused("update: a refusal names where the item model is", upd(1, state="parked"), "docs/design", "hold=true")
err, text = call("create", subject="[home] new thing", description=DESC, project="projects/alpha", sender="home-front", mover=BACK, next="team-back: go", state="doing")
refused("create: state is refused the same way", (err, text), "retired input", "state")
check("create: …and nothing was made", not (T / "store/a/900.json").exists() and not any(p.name not in ("1.json", "2.json") for p in (T / "store/a").iterdir()), sorted(p.name for p in (T / "store/a").iterdir()))

# ================================================================ 3 empty_ok
err, text = upd(2, priority="p2", state="", clear_state=False, chase_note="", party="", chase="", end="", proof="")
check("empty_ok: a call that sends every retired input empty goes through", not err and mt(2).get("priority") in ("p2", None) and "etired" not in text, text)
check("empty_ok: …and is stored without a state word", "state" not in mt(2), mt(2))

# ================================================================ 4 gone_from_tools
import inspect
fn = lambda t: getattr(t, "fn", t)
GONE = RI.RETIRED
for tool in (server.stackshot_update, server.stackshot_create):
    params = inspect.signature(fn(tool)).parameters
    check(f"gone: {fn(tool).__name__} takes none of the retired inputs", not [k for k in GONE if k in params], [k for k in GONE if k in params])
params = inspect.signature(server._update_unlocked).parameters
check("gone: the server's own _update_unlocked takes none", not [k for k in GONE if k in params], [k for k in GONE if k in params])
check("gone: supplies and step stay", "supplies" in inspect.signature(fn(server.stackshot_update)).parameters and "step" in inspect.signature(fn(server.stackshot_update)).parameters, None)
async def schemas():
    async with Client(server.mcp) as c:
        return {t.name: t for t in await c.list_tools()}
tools = asyncio.run(schemas())
for name in ("update", "create"):
    props = tools[name].input_schema["properties"]
    check(f"gone: {name}'s schema lists none of the seven", not [k for k in GONE if k in props], [k for k in GONE if k in props])
check("gone: …and update's schema keeps supplies and step", "supplies" in tools["update"].input_schema["properties"] and "step" in tools["update"].input_schema["properties"], None)
for name in ("update", "create", "get", "brief", "complete"):
    d = tools[name].description
    bad = re.findall(r"(?:state=(?:doing|your-call|your-step|outside|blocked|parked|verifying|<one)|clear_state=true|chase_note=<|party=<|chase=YYYY|proof=<|end=YYYY)", d)
    check(f"gone: the {name} description teaches none of them as an input", not bad, bad)
check("gone: update's description says they are refused, and what to use", "a call that passes state, clear_state, party, chase, end, proof or chase_note is refused with what to pass instead" in tools["update"].description, None)

# ================================================================ 5 step_supplies
item(10, needs=[BACK], mover=BACK, next="team-back: build it")
err, text = upd(10, step="Click the link and say done", mover=OWN, next=f"{OWN}: click the link")
check("step: update(step=…) with his mover and a step line is stored as his step", not err and mt(10).get("step") == "Click the link and say done" and mt(10).get("state") == "your-step", (text, mt(10)))
err, text = upd(10, step="Click it `rm -rf x` now")
check("step: a step that carries a command is refused", err and "Refused" in text and "command" in text.lower(), text)
item(11, needs=[BACK], mover=BACK, next="team-back: wait for it")
item(12, needs=[BACK], mover=BACK)
err, text = upd(11, supplies="the build artifact")
check("supplies: without an after item it is refused with what to add", err and "Refused" in text and "after" in text, text)
err, text = upd(11, after=["a12"], supplies="the build artifact", ask_by=day(5))
check("supplies: with an after item it is stored (the blocked state)", not err and mt(11).get("supplies") == "the build artifact" and mt(11).get("state") == "blocked", (text, mt(11)))
err, text = upd(10, status="completed", outcome="done", reason="finished", outcome_text="- done")
check("step: a close drops the stored step and its state", not err and "step" not in mt(10) and "state" not in mt(10), (text, mt(10)))
check("step: …(supplies the same on a close)", not upd(11, status="completed", outcome="done", reason="finished", outcome_text="- done")[0] and "supplies" not in mt(11) and "state" not in mt(11), mt(11))
item(13, needs=[BACK], mover=BACK, next="team-back: build it")
upd(13, step="Click the link and say done", mover=OWN, next=f"{OWN}: click the link")
err, text = upd(13, step="none")
check("withdraw: step=\"none\" drops his step and the your-step state, says so, and the mover is no longer him", not err and "step" not in mt(13) and "state" not in mt(13) and "step withdrawn" in text and mt(13).get("mover") != OWN, (text, mt(13)))
check("withdraw: …and his open step line leaves the checklist", not any(ln.startswith(f"{OWN}:") for ln in str(mt(13).get("next") or "").splitlines()) or "dropped" in json.dumps(mt(13).get("steps")), mt(13))
refused("withdraw: step=\"none\" on an item that stores no step is refused", upd(13, step="none"), "stores none")
refused("withdraw: step=\"none\" with supplies is refused (one of them)", upd(13, step="none", supplies="x", after=["a12"]), "pass one of them")
item(14, state="doing", needs=[BACK], mover=BACK)
err, text = upd(14, after=["a12"], supplies="the build artifact", ask_by=day(5))
check("supplies: on an item stored in doing it swaps the item to blocked", not err and mt(14).get("state") == "blocked" and "doing → blocked" in text, (text, mt(14)))
item(15, state="verifying", party="Acme", chase=day(3), chases=[{"at": 1, "by": "x", "note": "a"}], end=day(4), proof="the dashboard is green", wake=day(4), wait_basis="the check ends " + day(4))
err, text = upd(15, status="completed", outcome="done", reason="finished", outcome_text="- done")
check("close: a close drops party, chase, chases, end, proof and the state word", not err and not any(k in mt(15) for k in ("party", "chase", "chases", "end", "proof", "state")), (text, mt(15)))

# ================================================================ 6 stored_stays
item(20, needs=[BACK, "external"], mover=BACK, state="outside", party="Acme legal", chase=day(4), next="team-back: wait for Acme")
item(21, needs=[BACK], mover=BACK, state="verifying", proof="the dashboard is green", end=day(6), next="team-back: watch it")
item(22, needs=[BACK], mover=BACK, state="doing", next="team-back: build it")
item(23, needs=[BACK], mover=BACK, party="CI", chase=day(2), next="team-back: watch the PR")
before = {i: (server._fmt({**rd(i), "gid": f"a{i}"}), server._item_list({**rd(i), "gid": f"a{i}"})) for i in (20, 21, 22, 23)}
for i in (20, 21, 22, 23):
    m0 = dict(mt(i))
    err, text = upd(i, priority="p2")
    m1 = mt(i)
    keep = {k: m0[k] for k in ("state", "party", "chase", "end", "proof") if k in m0}
    check(f"stored: a{i} keeps {sorted(keep) or 'its fields'} through a priority write", not err and all(m1.get(k) == v for k, v in keep.items()), (text, {k: m1.get(k) for k in keep}))
    after = (server._fmt({**rd(i), "gid": f"a{i}"}), server._item_list({**rd(i), "gid": f"a{i}"}))
    pick = lambda t: [l for l in t.splitlines() if re.match(r"(model|state|wait|party|chase|mover|needs)", l)]
    check(f"stored: a{i} reads the same in get and the list after the write", pick(before[i][0]) == pick(after[0]) and before[i][1] == after[1], (pick(before[i][0]), pick(after[0])))
check("stored: the readers still take the fields (a stored outside item reads as a wait on the party)", states.stored({**rd(20)}) == "outside" and "Acme legal" in server._fmt({**rd(20), "gid": "a20"}), None)

# ================================================================ 7 unseated_dropped
err, text = upd(22, clear_needs=True, mover=OTHER, next=f"{OTHER}: take over")
check("unseated: a write that leaves a stored doing item with no session in needs drops the word and says so", not err and "state" not in mt(22) and "stored state doing dropped" in text, (text, mt(22)))
err, text = upd(21, clear_needs=True, mover=OTHER, next=f"{OTHER}: take over")
m = mt(21)
check("unseated: …a stored verifying item loses the word too, but keeps its proof and end (the readers take them)", not err and "state" not in m and m.get("proof") == "the dashboard is green" and m.get("end") == day(6), (text[:80], m))
item(24, needs=[BACK], mover=BACK, state="doing", next="team-back: build it")
err, text = upd(24, priority="p3")
check("unseated: a write that touches nothing the state stands on leaves it", not err and mt(24).get("state") == "doing", (text, mt(24)))

# ================================================================ 8 routes
from starlette.testclient import TestClient
tok = open(_client.mint("home-test")).read().strip()
item(30, needs=[BACK], mover=BACK)
b30 = raw(30)
with TestClient(server.mcp.http_app()) as c:
    r = c.post("/client/state", json={"sender": "home-test", "item": "a30", "state": "doing"}, headers={"Authorization": "Bearer " + tok})
    check("route: POST /client/state answers 400 with the refusal and the way out", r.status_code == 400 and "retired" in r.text and "mover=" in r.text, (r.status_code, r.text[:300]))
    r = c.post("/client/state", json={"sender": "home-test", "item": "a30", "clear_state": True}, headers={"Authorization": "Bearer " + tok})
    check("route: …clear_state and park_wake the same", r.status_code == 400 and "retired" in r.text, (r.status_code, r.text[:200]))
check("route: …nothing was written", raw(30) == b30, None)
err_buf = io.StringIO()
with contextlib.redirect_stderr(err_buf):
    rc = _client.state_set(["--item", "board#30", "--state", "doing", "--sender", "home-test"])
check("route: client.py post state prints the refusal, exits 1 and reached no server", rc == 1 and "retired" in err_buf.getvalue() and "update" in err_buf.getvalue(), err_buf.getvalue())
check("route: …and its usage text no longer lists --state", "--state <doing" not in _client._usage_text() if hasattr(_client, "_usage_text") else "--state <doing" not in (_client.__doc__ or ""), None)

# ================================================================ 9 no_chase
check("no_chase: watchers.add_chase and states.hint are gone", not hasattr(watchers, "add_chase") and not hasattr(states, "hint"), None)
check("no_chase: a chase an older write stored still counts (two of them, on a relay wait)", watchers.chased_out({"wait_kind": "relay", "chases": [{"at": 1, "by": "x", "note": "a"}, {"at": 2, "by": "x", "note": "b"}]})
      and not watchers.chased_out({"wait_kind": "relay", "chases": [{"at": 1, "by": "x", "note": "a"}]}), None)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": retired inputs scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
