"""Scenario test for the digest a pane is handed when it comes back ("N queued while you were away", inbox.take and push.flush): a front agent's turn starts only for what is the person's, so the digest goes through
front_turn.warranted (messaging.digest_fyi). Fixture data, no live store, no network, never a real pane.

Fixture: projects/alpha (a front agent, home-front, and a builder, team-back); items 30 (the builder's) and 31 (home-front is in its `tell_him`: he asked it to tell him about it); home-lone, a front agent whose hook
cannot fetch held lines.

  1  no line carries his mark and he is away: no delivery, the lines are removed from the inbox and filed as fyi lines (one each), the board line is written on the item a line names
  2  the same without the server's hook (`digest` not given): one delivery, "N queued while you were away", the lines stay leased: nothing changes for a caller that has no hook
  3  a line carries his mark: a turn while he is talking with that agent now, an fyi while he is not
  4  no line carries his mark and he is there: still an fyi (presence alone is not a need); a line about an item he asked the agent to tell him about is a turn, there or not
  5  what is never filed: the digest of a background agent, of a front agent whose hook cannot fetch held lines, a single line, a hook that fails: handed out as before, no line lost
  6  push.flush takes the same hook: filed lines are dropped from the queue and no send is made; a digest that is a turn is sent as before (not live here: exit 3, the queue kept)
  7  the server's two paths into inbox.take (the drain and the poll) give it the hook

    tests/run-suite front_digest        -> exit 0 / 1"""
import json, os, re, sys, time, pathlib, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="frontdigest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), gbrain=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
toml = toml.replace('lanes_file = ""', f'lanes_file = "{tmp}/sala/lanes.tsv"', 1); assert f'lanes_file = "{tmp}/sala/lanes.tsv"' in toml
toml = toml.replace('limit_file = ""', f'limit_file = "{tmp}/sala/limit.json"', 1); assert f'limit_file = "{tmp}/sala/limit.json"' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                 ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", HOME=str(T / "home")); os.environ.pop("STACKSHOT_URL", None)
F, B, L = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333")
UID = {"home-front": F, "team-back": B, "home-lone": L}
for d in ("store/a", "fleet/a", "state/s1", "state/site", "secrets", "touch", "repo", "sala", "brain/projects", "cli", "home"): (T / d).mkdir(parents=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in UID.items()}))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
AGENTS = {"home-front": "Oliver's point of contact", "home-lone": "a second point of contact", "team-back": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {
    "title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-front", "status": "active", "board": [], "board_row": False, "updated": 1,
    "mirror": "https://example.invalid/alpha", "agents": AGENTS, "back_agents": {"team-back": AGENTS["team-back"]}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nThe vendor call is open.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
def item(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.", "status": "open",
                                                      "metadata": {"owner": F, "mover": "team-back", "project": "projects/alpha", **meta}, "updated": 1.0, "state_updated": 1.0}))
item(30); item(31, tell_him=["home-front"])
(T / "store/next-id").write_text("50"); (T / "store/anchors.json").write_text("{}")
shown = lambda n: f"a{n}"      # an item as a notice names it: the store's own id (the fixture's items are a30 and a31)

sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.core import config as _cfg; from stackshot.waits import held; from stackshot.fleet import inbox, push
from stackshot.web import server
from stackshot.service import messaging as _messaging
from stackshot.service import telling
from stackshot.service import front_turn
from stackshot.service import handoff as handoff_svc
held.mark_client("home-front"); held.mark_client("team-back")      # the rollout gate: their hooks fetch held lines (home-lone's does not)
handoff_svc.CLI_SESSIONS = T / "cli"
STARTED = time.time() - 3600.0
def cli_row(who):
    (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": UID[who], "name": who, "status": "idle", "startedAt": int(STARTED * 1000)}))
def stamp(who, age=60.0):
    p = T / "state/prompts" / UID[who]; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(f"{time.time() - age:.0f}\n")
def unstamp(who): (T / "state/prompts" / UID[who]).unlink(missing_ok=True)
for w in UID: cli_row(w)
MARK = "[for Oliver]"
HOOK = _messaging.digest_fyi


def reset():
    """Nothing left of an earlier case: the inbox, the leases, the held lines (the clients file stays), the presence stamps, the queue."""
    for src in inbox.SOURCES:
        for p in (inbox.DIR / src).glob("*.json"): p.unlink()
    (inbox.DIR / "leases.json").unlink(missing_ok=True)
    for p in held.dir_().glob("*"):
        if p.name != "clients.json": p.unlink()
    for w in UID: unstamp(w)
    for p in pathlib.Path(push.Q).glob("*"): p.unlink()
def put(who, *texts):
    return [inbox.put(UID[who], t, "msg", sender="home-peer") for t in texts]
def take(who, digest=HOOK):
    return inbox.take({UID[who]: who}, known={UID[who]}, only_src="msg", digest=digest)
def held_text(who="home-front"):
    out = []
    for p in held.dir_().glob("*"):
        if p.name != "clients.json" and p.is_file(): out.append(p.read_text(encoding="utf-8"))
    return "\n".join(out)
def quiet_log(i): return [x.get("text", "") for x in (json.loads((T / f"store/a/{i}.json").read_text())["metadata"].get("front_quiet") or {}).get("log", [])]

check("0 the fixture: home-front is a front agent, team-back is not; nobody is talking with home-front", telling.front_sender("home-front") and not telling.front_sender("team-back") and not front_turn.present("home-front"))
check("0 …home-front's hook fetches held lines, home-lone's does not", held.can_fetch("home-front") and not held.can_fetch("home-lone"))

PLAIN = [f"{shown(30)}: the build finished, nothing to do", f"a notice about nothing at all", f"{shown(30)}: the release went out"]
# ---- 1. no line is his, he is away
reset(); ids = put("home-front", *PLAIN)
tk = take("home-front")
check("1 no line carries his mark and he is away: no delivery", tk == [], tk)
check("1 …the lines are gone from the inbox (not leased, not waiting)", inbox.waiting() == {} and not (inbox.DIR / "leases.json").exists() or not json.loads((inbox.DIR / "leases.json").read_text() or "{}"), (inbox.waiting(), inbox._leases()))
ht = held_text()
check("1 …each line is filed as an fyi for the agent's next turn", held.count("home-front") == 3 and "the build finished" in ht and "the release went out" in ht and "a notice about nothing at all" in ht, (held.count("home-front"), ht))
check("1 …and the item a line names has its board line", any("hears of it on his next turn" in x and "the build finished" in x for x in quiet_log(30)), quiet_log(30))
check("1 a second poll finds nothing to hand out (the lines are not offered again)", take("home-front") == [], inbox.waiting())

# ---- 2. no hook given: as before
reset(); ids = put("home-front", *PLAIN)
tk = take("home-front", digest=None)
check("2 without the server's hook: one delivery of the whole digest, as it always was", len(tk) == 1 and tk[0]["text"].startswith("[stackshot] 3 queued while you were away:\n") and tk[0]["ids"] == ids and held.count("home-front") == 0, tk)

# ---- 3. a line carries his mark
reset(); stamp("home-front"); put("home-front", PLAIN[0], f"{MARK} {shown(30)}: sign the form")
tk = take("home-front")
check("3 a line carries his mark and he is talking with that agent now: a turn, the whole digest, nothing filed", len(tk) == 1 and tk[0]["text"].count("queued while you were away") == 1 and MARK in tk[0]["text"] and held.count("home-front") == 0, (tk, held.count("home-front")))
reset(); put("home-front", PLAIN[0], f"{MARK} {shown(30)}: sign the form")
tk = take("home-front")
check("3 …the same digest while he is away: no turn, both lines filed as fyi lines (the marked one too), none lost", tk == [] and held.count("home-front") == 2 and "sign the form" in held_text() and inbox.waiting() == {}, (tk, held.count("home-front"), inbox.waiting()))
reset(); put("home-front", PLAIN[0], f"{shown(30)}: it needs: decision before Friday")
check("3 a line that says needs: decision counts as his mark: a turn while he is there", (stamp("home-front"), len(take("home-front")) == 1)[1] and held.count("home-front") == 0)

# ---- 4. presence alone is no need; his ask is a turn
reset(); stamp("home-front"); put("home-front", *PLAIN)
tk = take("home-front")
check("4 no line is marked and he is there: still no turn, the lines are filed", tk == [] and held.count("home-front") == 3, (tk, held.count("home-front")))
reset(); put("home-front", PLAIN[0], f"{shown(31)}: the vendor wrote back")
tk = take("home-front")
check("4 a line names an item he asked this agent to tell him about (tell_him), and he is away: a turn", len(tk) == 1 and held.count("home-front") == 0 and shown(31) in tk[0]["text"], (tk, held.count("home-front")))
reset(); put("home-front", PLAIN[0], f"{shown(30)}: the vendor wrote back")
check("4 …an item he asked about no one: filed", take("home-front") == [] and held.count("home-front") == 2)

# ---- 5. what is never filed
reset(); put("team-back", *PLAIN)
tk = take("team-back")
check("5 a background agent's digest is handed out as before (the rule is for a front agent's turn)", len(tk) == 1 and tk[0]["text"].count("queued while you were away") == 1 and held.count("team-back") == 0, (tk, held.count("team-back")))
reset(); put("home-lone", *PLAIN)
tk = take("home-lone")
check("5 a front agent whose hook cannot fetch held lines gets the digest as a turn: nothing would carry the lines, none is lost", len(tk) == 1 and held.count("home-lone") == 0 and len(tk[0]["ids"]) == 3, (tk, held.count("home-lone")))
reset(); put("home-front", PLAIN[0])
tk = take("home-front")
check("5 a single line is no digest: handed out as it always was", len(tk) == 1 and tk[0]["text"].startswith("from: home-peer") and held.count("home-front") == 0, tk)
def broken(name, lines): raise RuntimeError("the hook failed")
reset(); ids = put("home-front", *PLAIN)
tk = take("home-front", digest=broken)
check("5 a hook that fails hands the digest out as before: nothing lost", len(tk) == 1 and tk[0]["ids"] == ids and held.count("home-front") == 0, tk)
reset(); put("home-front", *PLAIN)
tk = take("home-front", digest=lambda name, lines: False)
check("5 a hook that says no hands the digest out", len(tk) == 1 and len(tk[0]["ids"]) == 3, tk)

# ---- 6. push.flush takes the same hook
def queue(name, *texts):
    pathlib.Path(push.Q).mkdir(parents=True, exist_ok=True)
    with open(pathlib.Path(push.Q) / f"{name}.jsonl", "a", encoding="utf-8") as f:
        for t in texts: f.write(json.dumps({"t": time.time(), "text": t, "from": "home-peer"}) + "\n")
qf = lambda name: pathlib.Path(push.Q) / f"{name}.jsonl"
reset(); queue("home-front", *PLAIN)
rc = push.flush("home-front", digest=HOOK)
check("6 push.flush: the queued lines of no concern to him are filed as fyi lines, the queue is removed and nothing is sent", rc == 0 and not qf("home-front").exists() and held.count("home-front") == 3, (rc, held.count("home-front")))
reset(); queue("home-front", *PLAIN)
rc = push.flush("home-front")
check("6 …without the hook it tries to send the digest, as it always did (no pane here: exit 3, the queue is kept)", rc == 3 and qf("home-front").exists() and held.count("home-front") == 0, rc)
reset(); queue("home-front", PLAIN[0], f"{MARK} {shown(30)}: sign the form"); stamp("home-front")
rc = push.flush("home-front", digest=HOOK)
check("6 …a digest that is a turn (marked, and he is there) is sent: not filed, exit 3 here, the queue is kept", rc == 3 and qf("home-front").exists() and held.count("home-front") == 0, rc)

# ---- 7. the server's two delivery paths give the hook
import inspect
from stackshot.web.routes import client_api
check("7 the puller's drain and its poll both give inbox.take the server's hook", inspect.getsource(client_api).count("digest=_messaging.digest_fyi") == 2)

reset()
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
