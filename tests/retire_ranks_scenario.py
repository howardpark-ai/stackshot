"""Scenario test for the retirement of ranks (the per-builder work order) — fixture data, no live store, no network, no server socket.

A rank is only a work order, never a wait: a builder starts every
item handed to it at its next turn, and releases go out in merge-queue order. Covers:

  * update(rank=N) and update(clear_rank=true) are refused with a short reason (never silently ignored) and nothing is written; state=queued is refused too, as a retired input of update (through the MCP layer; retired_inputs_scenario covers the others); the tool
    schema still lists the two parameters, described as retired; create takes no rank; POST /client/rank is gone;
  * get, brief, the client items read and the board's pages (item page, board.md, session-start brief) show no rank and no queue block, also for an item that
    still stores one;
  * an item stored with a rank and the state queued loads cleanly (as doing, an agent wait on the 3-hour rule), and the start-time cleanup clears both once: open
    items only, a History line for each, every clock (updated, state_updated, confirmed) unchanged, a second run changes nothing, a closed item is untouched.
    (That the stall ladder no longer skips such an item is checked in the stall suite.)

    tests/run-suite retire_ranks        → exit 0 / 1"""
import asyncio, contextlib, datetime, importlib.util, io, json, os, re, subprocess, sys, pathlib, tempfile, time, logging, hashlib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="retiretest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-gone": "the third"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other", "home-gone": "the third"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-gone: the third\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, letter="a", subject=None, desc=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": desc or DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su,
                                                              "metadata": {"owner": owner or U["home-front"], "project": "projects/alpha", "next": "do the thing", **meta}}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.waits import waiting as W; from stackshot.web import render; from stackshot.github import ghsync
from stackshot.web.tools import get as _get_tool
from stackshot.service import client_reads as client_reads_svc
from stackshot.model import holders as _holders
from stackshot.service import item_read as _item_read
from stackshot.service import update as _update_svc
from stackshot.model import states as _states
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import brief as _wt_brief
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
ZONE_OFFSET = 4 * 3600      # the pinned instance timezone, Asia/Dubai: UTC+4, no DST
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
BACK, OTHER, GONE = "team-back", "home-other", "home-gone"      # as the update path stores a name the registry does not know
UB, UO = U["team-back"], U["home-other"]
def upd(i, **kw):
    return _update_svc._update(f"a{i}", sender="home-front", **kw)


def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
def snapshot():
    """Commit the store as it is now: the next version of every item, which the History is derived from."""
    git("add", "-A"); git("commit", "-q", "--allow-empty", "-m", "v")
plain = lambda t: re.sub(r"<[^>]+>", " ", t)

# ================================================================ the stored shapes before the cleanup
item(1, needs=[BACK], su=now0 - 3 * DAY, rank=2, state="queued", subject="[home] old fields, both")
item(2, needs=[BACK], su=now0 - 3 * DAY, rank=1, subject="[home] old fields B")
item(3, needs=[OTHER], su=now0 - 3 * DAY, state="queued", subject="[home] old fields C")
item(4, needs=[BACK], su=now0 - 3 * DAY, subject="[home] clean item")
item(5, status="completed", needs=[BACK], su=now0 - 3 * DAY, rank=3, state="queued", outcome="done", subject="[home] closed, keeps its old fields")
item(6, needs=[BACK], su=now0 - 3 * DAY, rank=4, state="doing", expected_by=day(1), subject="[home] old fields D")
git("init", "-q"); snapshot()
before = {i: rd(i) for i in range(1, 7)}
orig_bytes = {i: (T / f"store/a/{i}.json").read_bytes() for i in range(1, 7)}

# ================================================================ loads cleanly
check("load: a stored queued reads as the state shown (doing), not as an unknown value", _states.stored(rd(1)) == "doing" and _states.stored(rd(3)) == "doing"
      and "queued" not in _states.STATES and _states.LEGACY_STATES == {"queued": "doing"}, _states.LEGACY_STATES)
check("load: …it is an agent's state: not held, not after anything", _states.of(rd(1))[0] == "doing" and not _holders._is_held(rd(1)) and not _item_read._after_open(rd(1)["metadata"]), _states.of(rd(1)))
probs = _states.problems(rd(1)["metadata"], _states.stored(rd(1)), datetime.date.today(), check_dates=False)
check("load: …problems() asks nothing of it about a rank", not any("rank" in p for p in probs), probs)
g1 = _get_tool._fmt({**rd(1), "gid": "a1"})
check("load: get of an item that still stores a rank shows no rank line, no queue and no work order", not re.search(r"rank|queue|work order", g1, re.I), g1[-500:])
check("load: …and no `queued` state", "state: queued" not in g1 and "queued" not in g1, g1[-500:])

# ================================================================ update refuses rank
refused("update: rank=2 is refused, saying ranks are retired", lambda: _wt_update.stackshot_update("a4", sender="home-front", rank=2), "Refused", "ranks are retired", "starts every item handed to it")
refused("update: clear_rank=true is refused the same way", lambda: _wt_update.stackshot_update("a4", sender="home-front", clear_rank=True), "Refused", "ranks are retired")
refused("update: …also next to arguments that would be fine alone", lambda: _wt_update.stackshot_update("a4", sender="home-front", next="team-back: go", rank=1), "ranks are retired")
check("update: …none of the refusals wrote anything", rd(4) == before[4] and (T / "store/a/4.json").read_bytes() == orig_bytes[4], rd(4))
import inspect
check("update: create takes no rank, and the server's own _update takes none", "rank" not in inspect.signature(_wt_create.stackshot_create.fn if hasattr(_wt_create.stackshot_create, "fn") else _wt_create.stackshot_create).parameters
      and "rank" not in inspect.signature(__import__("stackshot.service.update", fromlist=["update_unlocked"]).update_unlocked).parameters, None)

async def mcp_checks():
    from fastmcp import Client
    async with Client(server.mcp) as c:
        tools = {t.name: t for t in await c.list_tools()}
        props = tools["update"].input_schema["properties"]
        check("mcp: update still lists rank and clear_rank (so a stale caller is told, not ignored), described as retired",
              "etired: refused" in props.get("rank", {}).get("description", "") and "etired: refused" in props.get("clear_rank", {}).get("description", ""), {k: props.get(k) for k in ("rank", "clear_rank")})
        check("mcp: create lists no rank", "rank" not in tools["create"].input_schema["properties"], None)
        try:
            await c.call_tool("update", {"item_id": "a4", "sender": "home-front", "state": "queued"})
            check("mcp: state=queued is refused as a retired input, naming the builder as the way out (nothing is written)", False)
        except Exception as e:
            check("mcp: state=queued is refused as a retired input, naming the builder as the way out (nothing is written)", all(w in str(e) for w in ("Refused", "state is a retired input", "mover=<the builder>")) and (T / "store/a/4.json").read_bytes() == orig_bytes[4], str(e)[:300])
        check("mcp: no tool text still teaches rank=N as a work order", not any("work order" in (t.description or "") or "rank=N" in (t.description or "") for t in tools.values()), None)
asyncio.run(mcp_checks())

from stackshot.fleet import client as _client
from starlette.testclient import TestClient
(T / "secrets").mkdir(exist_ok=True)
tok = open(_client.mint("home-test")).read().strip()
with TestClient(server.mcp.http_app()) as c:
    r = c.post("/client/rank", json={"sender": "home-test", "item": "a4", "rank": 1}, headers={"Authorization": "Bearer " + tok})
    check("http: POST /client/rank is gone: not a 200, and nothing written", r.status_code in (404, 405) and rd(4) == before[4], (r.status_code, r.text[:120]))

# ================================================================ reading shows no rank, before and after the cleanup
from stackshot.web.ui import render as r2
def reads():
    """Every surface that used to show the rank → {name: text}"""
    out = {}
    out["get"] = "\n".join(_get_tool._fmt({**rd(i), "gid": f"a{i}"}) for i in (1, 2, 3, 4, 6))
    out["brief"] = _wt_brief.stackshot_brief()
    out["client"] = json.dumps(json.loads(client_reads_svc._client_items(UB)[2])["items"]) + json.dumps(json.loads(client_reads_svc._client_items(UO)[2])["items"])
    B_ = r2.Board(str(T / "store"))
    out["page"] = "\n".join(B_.item_html(f"a{i}") for i in (1, 2, 3, 4, 6))
    for tag, mod in (("render.py", render), ("ui/render.py", r2)):
        B_ = mod.Board(str(T / "store"))
        out[tag + " md"] = B_.markdown()
        out[tag + " brief"] = B_.brief()
    return out
WORDS = re.compile(r"rank(?!s after)|work order|queue of |Builder queues|\bqueued\b(?!\s+for release)", re.I)   # the "Queued for release" heading is the release queue, not the state
def seen(txt): return WORDS.findall(plain(txt))
for name, txt in reads().items():
    check(f"read: {name} shows no rank, work order, builder queue or queued state for items that still store them", not seen(txt), [m.group(0) for m in re.finditer(r".{0,40}(?:rank|queued|work order).{0,40}", plain(txt), re.I)][:3])
cl = json.loads(client_reads_svc._client_items(UB)[2])["items"]
check("read: the client items carry no rank key", cl and all("rank" not in x for x in cl), cl[:1])
check("read: render keeps no rank helpers", not any(hasattr(render, n) or hasattr(r2, n) for n in ("rank_of", "builder_of", "queue_key", "queues", "rank_words", "rank_badge")) and not hasattr(server, "_rank_queues"), None)

# ================================================================ the cleanup
dry = server._retire_rank_pass(apply=False)
check("cleanup: a dry run lists the open items that store a rank or a queued state, in id order, and writes nothing",
      [x["item"] for x in dry] == ["a1", "a2", "a3", "a6"] and [x["rank"] for x in dry] == [2, 1, None, 4] and [x["queued"] for x in dry] == [True, False, True, False]
      and all((T / f"store/a/{i}.json").read_bytes() == orig_bytes[i] for i in range(1, 7)), dry)
done = server._retire_rank_pass()
check("cleanup: the pass reports the same four items", [x["item"] for x in done] == ["a1", "a2", "a3", "a6"], done)
for i in (1, 2, 3, 6):
    m = rd(i)["metadata"]
    keep = lambda d: {k: v for k, v in d.items() if k not in ("rank", "state", "phase")}      # the stored phase apart: every save of an open item writes it
    check(f"cleanup: a{i} lost its rank and its queued state, nothing else", "rank" not in m and m.get("state") != "queued" and keep(m) == keep(before[i]["metadata"]), m)
check("cleanup: …and no item got an agent_from stamp (nothing reads one any more)", all("agent_from" not in rd(i)["metadata"] for i in range(1, 7)), [(i, rd(i)["metadata"].get("agent_from")) for i in range(1, 7)])
check("cleanup: …a state doing next to a rank stays doing", rd(6)["metadata"].get("state") == "doing", rd(6)["metadata"])
check("cleanup: …no clock moved: updated, state_updated and confirmed are as they were", all(rd(i)[k] == before[i][k] for i in (1, 2, 3, 6) for k in ("updated", "state_updated", "confirmed")),
      [(i, rd(i)["updated"], before[i]["updated"]) for i in (1, 2, 3, 6)])
check("cleanup: …a clean item and a closed one are not written (the closed one keeps its old fields)", all((T / f"store/a/{i}.json").read_bytes() == orig_bytes[i] for i in (4, 5)) and rd(5)["metadata"].get("rank") == 3, rd(5)["metadata"])
snapshot()
bytes_after = {i: (T / f"store/a/{i}.json").read_bytes() for i in range(1, 7)}
again = server._retire_rank_pass()
check("cleanup: a second run finds nothing and writes nothing (idempotent)", again == [] and all((T / f"store/a/{i}.json").read_bytes() == bytes_after[i] for i in range(1, 7)), again)
check("cleanup: …no mover was settled and no hand-off ended by it", all(rd(i)["metadata"].get("mover") == before[i]["metadata"].get("mover") and rd(i)["metadata"].get("handoff") == before[i]["metadata"].get("handoff") for i in (1, 2, 3, 6)), None)
for tag, mod in (("render.py", render), ("ui/render.py", r2)):
    B_ = mod.Board(str(T / "store"))
    log = plain(" ".join(str(x) for x in B_.item_log(next(r for r in B_.rows if r["gid"] == "a1"))[0]))
    check(f"cleanup: {tag} History says the rank was cleared and the state too", "rank cleared (was 2)" in log and "state cleared" in log, log[:400])
    log2 = plain(" ".join(str(x) for x in B_.item_log(next(r for r in B_.rows if r["gid"] == "a2"))[0]))
    check(f"cleanup: …{tag} a rank alone says just the rank", "rank cleared (was 1)" in log2 and "state cleared" not in log2, log2[:300])
for name, txt in reads().items():
    if "page" in name: continue            # the History on an item page keeps the cleanup's own line ("rank cleared (was N)")
    check(f"after: {name} still shows no rank", not seen(txt), [m.group(0) for m in re.finditer(r".{0,40}(?:rank|queued|work order).{0,40}", plain(txt), re.I)][:3])

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": retire ranks scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
