"""Scenario test for: a board write refused inside a Code Mode script can go unseen (the board item sat 1.5 days), so

  1  the end-of-turn board texts (the early question and the Stop hook's board question, pages.py) name the session's live role beside each item, as the server holds it
     now (the client items read's `roles`): "you are still its mover", "you are its then", "named in its needs", several joined with "; ", an item the session has
     no role on is not listed at all, and a row from a server that sends no roles reads as before;
  2  the server logs why a tool call was refused (_RefusalLog, web/middleware.py): tool, item id, sender and the reason clipped to REFUSAL_LOG_MAX, nothing else from the call, and the
     refusal still reaches the caller unchanged.

Fixture data, no live store, no network, no server socket.    tests/run-suite live_role        → exit 0 / 1"""
import asyncio, contextlib, io, json, os, re, sys, pathlib, time, logging, types
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="liverole-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time(); DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  home-other: the other\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner, mover=None, needs=None, su=None, **extra):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": "open", "updated": su, "state_updated": su, "confirmed": su,
                                                      "metadata": {"owner": U[owner], "project": "projects/alpha", "next": f"step one of a{i}",
                                                                   **({"mover": mover} if mover else {}), **({"needs": needs} if needs else {}), **extra}}))
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server
from stackshot.service import client_reads as client_reads_svc
from stackshot.service import update as _update_svc
from stackshot.web import publish as _web_publish
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web import middleware as _wmw
from stackshot.projects import pages as pg
from fastmcp.exceptions import ToolError
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None

# --- 1: the live roles in the end-of-turn texts ---
item(1, "home-front", mover="home-front")                       # the asking session moves it
item(2, "home-owner", mover="team-back", needs=["team-back"])    # a background agent moves it and is named in its needs
item(3, "home-front", mover="team-back")                        # created by the asking session, moved by a background agent: the creator holds no part
item(4, "home-front", mover="home-front", needs=["team-back"])    # the asking session moves it, and a background agent is named in its needs
item(5, "home-other", mover="home-other")                       # no role for either session
item(8, "home-owner", needs=["team-back"], state="parked", wake=time.strftime("%Y-%m-%d", time.gmtime(now0 + 20 * DAY)), post_wake_mover="team-back")   # waiting: team-back is named in needs and takes it after the wait
item(9, "home-owner", state="parked", wake=time.strftime("%Y-%m-%d", time.gmtime(now0 + 20 * DAY)), post_wake_mover="team-back")   # waiting: team-back takes it after the wait and is named nowhere
item(6, "home-owner", mover="home-front")                       # created by another session, moved by the asking session and named nowhere: a hand-back whose needs were cleared
rows = {x["shown"]: x for x in json.loads(client_reads_svc._client_items(U["home-front"])[2])["items"]}
check("1: the items read lists the items the session moves, and not the ones it only created or another session moves", sorted(rows) == ["a1", "a4", "a6"], sorted(rows))
check("1: …each reads mover, and no item row carries a keeper role any more", all(rows[k]["roles"] == ["mover"] and "role" not in rows[k] for k in rows), {k: (v.get("roles"), v.get("role")) for k, v in rows.items()})
back = {x["shown"]: x for x in json.loads(client_reads_svc._client_items(U["team-back"])[2])["items"]}
check("1: …the background agent reads 'needs' where it is named in needs (with the old role marker kept), 'mover' where it moves the item, and 'then' where it takes the item after a wait (a9, named nowhere)",
      sorted(back) == ["a2", "a3", "a4", "a8", "a9"] and back["a3"]["roles"] == ["mover"] and "role" not in back["a3"] and back["a2"]["roles"] == ["mover", "needs"] and back["a4"]["roles"] == ["needs"]
      and back["a8"]["roles"] == ["then", "needs"] and back["a9"]["roles"] == ["then"] and back["a2"].get("role") == "agent" and back["a4"].get("role") == "agent", {k: (v.get("roles"), v.get("role")) for k, v in back.items()})

pg.owned_items = lambda sid: [dict(r) for r in (rows if sid == "front" else back).values()]
pg.turn_activity = lambda path: {"start": int(time.time()) + 10, "writes": True}
pg.board_mode = lambda: "block"
pg.load_state = lambda sid: {}; pg.save_state = lambda sid, st: None
def early(sid):
    return pg.early_question({"session_id": sid, "tool_name": "mcp__x__update", "tool_response": "updated a1", "transcript_path": "/none"})
q = early("front")
check("1: the early question: the mover reads 'you are still its mover' beside each of its items", all(f'a{n} "[home] item {n}" (you are still its mover)' in q for n in (1, 4, 6)) and "keeper of record" not in q, q)
check("1: …an item the session has no role on is not listed", "item 5" not in q and "item 2" not in q and "item 3" not in q, q)
check("1: …one sentence says what the role means for a hand-back that did not land", "if you handed it on and it still says you are its mover, that write was refused" in q, q)
qb = early("back")
check("1: …a session named in needs reads 'named in its needs' beside every item it is named in; one it moves too reads both; one it takes after the wait reads 'then'", 'a4 "[home] item 4" (named in its needs)' in qb
      and 'a2 "[home] item 2" (you are still its mover; named in its needs)' in qb and 'a8 "[home] item 8" (it comes to you after Oliver (you are its then); named in its needs)' in qb
      and 'a9 "[home] item 9" (it comes to you after Oliver (you are its then))' in qb and 'a3 "[home] item 3" (you are still its mover)' in qb and "item 5" not in qb, qb)
check("1: …the sentence about a refused hand-back comes only where a listed row says 'still its mover'", pg.still_mover_note([back["a4"], back["a8"], back["a9"]]) == "" and pg.still_mover_note([rows["a6"]]) != "" and "was refused" in pg.still_mover_note([back["a3"]]), None)
ba = pg.board_ask(["a write"], list(rows.values()))
check("1: the Stop hook's question lists the same set with the same roles before the next step", 'a1 "[home] item 1" (you are still its mover; next: step one of a1)' in ba
      and 'a6 "[home] item 6" (you are still its mover; next: step one of a6)' in ba and "item 5" not in ba and "was refused" in ba and "keeper of record" not in ba, ba)
bab = pg.board_ask(["a write"], [back["a4"], back["a8"]])
check("1: …an item that names the session in its needs keeps its own wording and says it once", 'a4 "[home] item 4" (next: step one of a4; it names you in its needs: ' in bab
      and 'a8 "[home] item 8" (it comes to you after Oliver (you are its then); next: step one of a8; it names you in its needs: ' in bab and bab.count("named in its needs") == 0, bab)
legacy = [{k: v for k, v in rows["a1"].items() if k != "roles"}]
# a closed item is never listed
item(7, "home-owner", mover="home-front")
d7 = json.loads((T / "store/a/7.json").read_text()); d7["status"] = "completed"; (T / "store/a/7.json").write_text(json.dumps(d7))
check("1: …a closed item the session moved is not listed", "a7" not in {x["shown"] for x in json.loads(client_reads_svc._client_items(U["home-front"])[2])["items"]}, None)
check("1: a row from a server that sends no roles reads as it did", 'a1 "[home] item 1" (next: step one of a1)' in pg.board_ask(["a write"], legacy) and pg.role_note(legacy[0]) == "", pg.board_ask(["a write"], legacy))

# --- 2: the server logs why a call was refused ---
def run_mw(name, args, call):
    """→ (what the middleware raised or returned, what it wrote to stderr)"""
    async def nxt(ctx): return call()
    ctx = types.SimpleNamespace(message=types.SimpleNamespace(name=name, arguments=args))
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        try: out = asyncio.run(_wmw._RefusalLog().on_call_tool(ctx, nxt))
        except ToolError as e: out = e
    return out, buf.getvalue()
def refuse_update():
    return _update_svc._update("a1", sender="home-front", description="no bullet here")      # a real refusal of the server's own
out, err = run_mw("update", {"item_id": "a1", "sender": "home-front", "description": "no bullet here"}, refuse_update)
check("2: a refused update logs one line: tool, item, sender and the server's own reason", isinstance(out, ToolError) and err.count("\n") == 1
      and err.startswith("refused: update item=a1 sender=home-front: Refused: description line is not a `- ` bullet"), (out, err))
check("2: …and the refusal reaches the caller with its own text", isinstance(out, ToolError) and "description line is not a `- ` bullet" in str(out), str(out))
long = "Refused: " + "word " * 200
out, err = run_mw("complete", {"item_id": "a2", "sender": "home-front", "outcome": "SECRET-OUTCOME-VALUE", "reason": "SECRET-REASON-VALUE"}, lambda: (_ for _ in ()).throw(ToolError(long)))
reason = err.split("sender=home-front: ", 1)[1].rstrip("\n") if "sender=home-front: " in err else ""
check("2: a long reason is clipped to REFUSAL_LOG_MAX characters", _wmw.REFUSAL_LOG_MAX == 300 and 0 < len(reason) <= _wmw.REFUSAL_LOG_MAX and reason.endswith("…"), (len(err), err[-80:]))
check("2: …only tool, item, sender and reason are logged: no other argument of the call", "SECRET" not in err and "outcome" not in err and err.startswith("refused: complete item=a2 sender=home-front: "), err)
out, err = run_mw("confirm", {}, lambda: (_ for _ in ()).throw(ToolError("Refused: sender is required\nsecond line")))
check("2: a call with no item or sender logs dashes, and a multi-line reason folds to one line", err == "refused: confirm item=- sender=-: Refused: sender is required second line\n", err)
out, err = run_mw("update", {"item_id": "a1", "sender": "home-front"}, lambda: "updated a1")
check("2: a call that succeeds logs nothing and returns its result", out == "updated a1" and err == "", (out, err))
out, err = run_mw("update", None, lambda: (_ for _ in ()).throw(ToolError("Refused: x")))
check("2: …and a call with no arguments object does not break the log", isinstance(out, ToolError) and err == "refused: update item=- sender=-: Refused: x\n", (out, err))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
