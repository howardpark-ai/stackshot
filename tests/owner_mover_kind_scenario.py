"""Scenario test for the items API's owner mover kind and the owner names the code reads: made-up data, temp folders, no live store, no network.

The code reads the owner names only (`decision` in needs, `owner_step`, `for_owner`, `[waiting] cap_needs_owner`); a person-named form of them is not read. A fixture store written in the owner names
holds ten items; the made-up owner is Oliver, so the legacy word the items API emits for the owner's move is oliver.

Covers: the item pages of the fixture store are real ones (the ask, the owner as mover, the buttons); the items API's mover.kind is the legacy word by default and "owner" with the switch
[items_api] owner_mover_kind (any other value reads as the default, the value is read without regard to case); an instance that names no owner gets the neutral word, and a two-word name its first word;
the code's own kind for the owner is the neutral word; a person-named needs value is not the owner's; a person-named [waiting] cap key is not read.

    tests/run-suite owner_mover_kind        → exit 0 / 1"""
import json, os, re, socket, sys, pathlib, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="ownerkind-"); T = pathlib.Path(tmp)
NAME = "oliver"                                                                             # the made-up owner's first name, as a person-named form spells it


def free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


PORT, HUB_PORT = free_port(), free_port()
base =_instance.apply(_instance.base_toml(), owner=True)
base = base.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in base
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    base, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', base); assert n == 1, key
base, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', base); assert n == 1
base, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', base); assert n == 1
assert re.search(r"(?m)^owner = \"Oliver\"", base), "the example instance names its owner Oliver"
base, n = re.subn(r"(?m)^port = 8020$", f"port = {PORT}", base); assert n == 1                 # a port nothing listens on
base, n = re.subn(r"(?m)^hook_port = 8010$", f"hook_port = {HUB_PORT}", base); assert n == 1   # the hub's port, free as well (a real hub may listen on the example's)
base, n = re.subn(r"(?m)^cap_needs_owner = true( *#.*)?$", "cap_needs_oliver = false   # a legacy key an older config may carry; the code does not read it", base); assert n == 1
(T / "stackshot.toml").write_text(base, encoding="utf-8")
CONFIG = T / "stackshot.toml"
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=str(CONFIG), STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/example-hub", "brain/projects", "secrets", "transcripts/-home-x", "backups"): (T / d).mkdir(parents=True)
HERE = "00000000-0000-4000-8000-000000000001"
now = time.time(); H = 3600.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({HERE: {"name": "home-here", "machine": "a", "seen": now}}))
PROJECTS = {"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-here", "status": "active", "board": [], "board_open": 0}}}
(T / "store/projects.json").write_text(json.dumps(PROJECTS)); (T / "store/next-id").write_text("500"); (T / "store/anchors.json").write_text("{}")
ASK = "Decide: whether to ship · Recommend: ship · Stakes: none either way · By: no date"
OPTS = [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}]
SU = now - 3 * H - 600
jd = lambda o: json.dumps(o, ensure_ascii=False, indent=1)               # the layout of an item file
jl = lambda o: json.dumps(o, ensure_ascii=False)                         # the layout of a log line
PROSE = f"- the router wrote for_{NAME} and {NAME}_step into old records, and ask_{NAME} was a cold-call action"



def item(i, subject, status="open", **meta):
    """One stored item, written in the owner names."""
    return {"id": str(i), "subject": subject, "description": "A thing. It lives here.", "status": status, "updated": SU, "state_updated": SU, "confirmed": SU, "metadata": {"owner": HERE, "project": "projects/alpha", **meta}}


STEP = "Oliver: decide whether to ship"
FIXTURE = [
    item(1, "[home] ask item", needs=["decision"], ask=ASK, options=OPTS, mover="Oliver", owner_step=STEP, steps=[{"text": STEP, "status": "open", "by": "owner_steps", "at": SU}]),
    item(2, "[home] needs as a string", needs="decision", ask=ASK, options=OPTS, mover="Oliver"),
    item(3, "[home] mixed case and external", needs=["decision", "external"], mover="Oliver", ask=ASK),
    item(4, "[home] a step key", mover="Oliver", next="Oliver: new", owner_step="Oliver: new"),
    item(5, "[home] decision and a session", needs=["decision", "team-other"], ask=ASK, mover="Oliver"),
    item(6, "[home] prose only", mover="team-other", next="team-other: x", note=PROSE),
    item(7, "[home] a closed item", status="completed", needs=["decision"], outcome="done", reason="shipped as asked"),
    item(8, "[home] clean", mover="team-other", next="team-other: x"),
    item(9, "[home] the owner as mover", mover="Oliver", next="Oliver: look"),
    item(10, "[home] the owner as then", mover="team-other", then="Oliver", post_wake_mover="Oliver", next="team-other: x"),
]
for it in FIXTURE:
    (T / "store" / "a" / f"{it['id']}.json").write_text(jd(it), encoding="utf-8")


fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1200]}" if got is not None else ""))


try:
    logging.disable(logging.INFO)
    sys.path.insert(0, STACK)
    from stackshot.web.ui import render as ui_render
    from stackshot.core import config as _cfg
    BOX = {"action": "/items/a1/answer", "token": "TOKEN", "sent": ""}
    bd = ui_render.Board(f"{tmp}/store")
    page1 = bd.item_html("a1", answer=BOX)
    check("the fixture store renders real item pages: the ask, the owner as mover (Your move) and the buttons", "Your move · since" in re.sub(r"<[^>]+>", "", page1) and "Ship it now" in page1 and ASK.split(" · ")[0].replace("Decide: ", "") in page1, page1[:300])
    from stackshot.web import server
    from stackshot.service import agents as _agents
    mv_of =lambda i: server._wait_fields(f"a{i}", json.loads((T / f"store/a/{i}.json").read_text(encoding="utf-8")), _agents._WaitCtx(time.time())).get("mover", {})


    # ---- 8. mover.kind in the items API
    check("mover.kind: by default the owner's move is named by the legacy word (the owner's first name in lower case)", mv_of(1) == {"kind": NAME, "who": "Oliver"} and _cfg.owner_mover_kind() == NAME, mv_of(1))
    check("…a session's and an outside party's kinds are unchanged", mv_of(8).get("kind") == "session" and mv_of(3).get("kind") == NAME, (mv_of(8), mv_of(3)))
    def set_kind(value: str) -> None:
        txt, n = re.subn(r'(?m)^owner_mover_kind = "[^"]*"', f'owner_mover_kind = "{value}"', base); assert n == 1
        CONFIG.write_text(txt, encoding="utf-8"); _cfg.reload()
    set_kind("owner")
    check("the switch [items_api] owner_mover_kind = \"owner\" emits the neutral word", mv_of(1) == {"kind": "owner", "who": "Oliver"} and mv_of(8).get("kind") == "session", mv_of(1))
    set_kind("legacy")
    check("…\"legacy\" is the default word", mv_of(1).get("kind") == NAME, mv_of(1))
    set_kind("something else")
    check("…any other value reads as the default", mv_of(1).get("kind") == NAME, mv_of(1))
    set_kind("OWNER")
    check("…the value is read without regard to case", mv_of(1).get("kind") == "owner", mv_of(1))
    set_kind("legacy")
    running = _cfg.CFG["instance"]["owner"]
    try:
        _cfg.CFG["instance"]["owner"] = "the owner"                                   # [instance] owner is read at start, so the running value is swapped here
        placeholder = _cfg.owner_mover_kind()
        _cfg.CFG["instance"]["owner"] = "Maria Lopez"
        two_words = _cfg.owner_mover_kind()
    finally:
        _cfg.CFG["instance"]["owner"] = running
    check("an instance that names no owner gets the neutral word by default, and a two-word name its first word", placeholder == "owner" and two_words == "maria", (placeholder, two_words))
    from stackshot.waits import waiting as _w
    check("the code's own kind for the owner is the neutral word", _w.mover_of({"needs": ["decision"], "project": "projects/alpha"})["kind"] == "owner", None)
    check("a person-named needs value is not the owner's (the code reads decision only)", _w.mover_of({"needs": [NAME], "project": "projects/alpha"})["kind"] == "session", None)
    CONFIG.write_text(base, encoding="utf-8"); _cfg.reload()
    check("a person-named [waiting] cap key is not read (the default stands)", _w.cap_needs_owner() is True, None)
except Exception:
    import traceback; traceback.print_exc(); fails.append("scenario raised")
finally:
    print(("ok" if not fails else "FAILED") + f": owner mover kind scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
