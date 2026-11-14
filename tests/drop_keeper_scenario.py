"""Scenario test for: the keeper of record is gone, the mover holds every power — fixture data, no live store, no network.

Covers: an item has a mover and nothing else that acts as an owner. The creator stays stored (metadata.owner) and is only a History fact, "created by X" (D1, D3: a background agent may
create; no `then` is stored on a create); an open item with no mover is moved by its project's builder, else its -main agent, never its creator, and the one-time start pass
(`_mover_backfill_pass`) gives such items that mover (its dry run writes nothing, it is idempotent and leaves needs, holds, Oliver's items and closed items alone); a close, a reopen
and every other notice go to the item's mover alone (D2); no tool text, reply, notice, item page or History line says "keeper of record" (D6); a move to another project's agent
keeps the project written (D4: no refiling to the creator's project); an item Oliver moves sits under its `then` agent, else a "no agent" group (D7); `then` defaults to the builder
doing the work (D9); the idle raise and its "Nag again" button (D5) are retired: the idle pass asks the fleet's builder instead, and a raise stored before still answers "Not needed".

    tests/run-suite drop_keeper        → exit 0 / 1"""
import json, os, re, sys, pathlib, tempfile, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="dropkeeper-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts (the stuck check reads them)
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
MAIN, BUILD, REVIEW, BMAIN, OTHER = "sparrow-main", "sparrow-builder", "sparrow-review", "home-beta-main", "home-gamma-main"
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate((MAIN, BUILD, REVIEW, BMAIN, OTHER), 1)}
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": page(title="Alpha", name="Alpha", agents={MAIN: "front", BUILD: "builds it", REVIEW: "reviews it"}, back_agents={BUILD: "builds it", REVIEW: "reviews it"}),
    "projects/beta": page(title="Beta", name="Beta", agents={BMAIN: "front"}),
    "projects/gamma": page(title="Gamma", name="Gamma")}}))
(T / "store/next-id").write_text("20"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))
def rd(g):
    g = str(g); g = g if not g[:1].isdigit() else "a" + g
    return json.loads((T / f"store/{g[0]}/{g[1:]}.json").read_text())
def put(i, status="open", project="projects/alpha", creator=MAIN, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": status,
        "updated": now0 - 60, "state_updated": now0 - 60, "confirmed": now0 - 60, "metadata": {"owner": creator, "project": project, **meta}}))

from stackshot.web import server
from stackshot.service import migrations as migsvc
from stackshot.service import answer as answer_svc
from stackshot.service import item_read as _item_read
from stackshot.service import update as _update_svc
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import text as _wt_text
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
from stackshot.web.ui import render as ui_render
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((tag, gid, owner, note))
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
SID = _web_page_debts._session_id
NOKEEP = lambda s: "keeper of record" not in str(s).lower()

# ---- 1. D1/D3: any session creates; the creator holds nothing; an item with no mover falls to the builder, else the -main agent
r = _wt_create.stackshot_create(subject="[home] made by a background agent", description=DESC, project="projects/alpha", sender=REVIEW, next=f"{REVIEW}: carry on")
g1 = r.split()[1]; m1 = rd(g1)["metadata"]
check("create: a background agent may create an item (D3): no refusal", r.startswith("created") and "Refused" not in r, r)
check("create: the creator is stored (metadata.owner) as a fact, and no mover and no `then` is stored from it (D1)", SID(str(m1.get("owner"))) == SID(REVIEW) and "mover" not in m1 and "then" not in m1, m1)
check("create: the item is moved by the project's builder (a background agent whose mandate builds), never its creator", telling.holder(rd(g1)) == BUILD and telling.holder(rd(g1)) != REVIEW, telling.holder(rd(g1)))
check("create: the reply and get never say 'keeper of record'", NOKEEP(r) and NOKEEP(_wt_get.stackshot_get(g1)), _wt_get.stackshot_get(g1))
r = _wt_create.stackshot_create(subject="[home] made on beta", description=DESC, project="projects/beta", sender=MAIN, next=f"{BMAIN}: carry on")
g2 = r.split()[1]
check("create: a project with no builder falls to its -main agent, not the creator from another project", telling.holder(rd(g2)) == BMAIN and "mover" not in rd(g2)["metadata"], telling.holder(rd(g2)))
_create_decl = _wt_create._CREATE_DESC
check("create tool text: says background agents may create, and no tool text says 'keeper of record'", NOKEEP(_create_decl) and NOKEEP(_wt_update._UPDATE_DESC) and NOKEEP(_wt_text._NEEDS_FORM) and "background agent" in _create_decl.lower(), _create_decl[:300])

# ---- 2. D1: the start pass
put(1)                                         # alpha, no mover: gets the builder
put(2, project="projects/beta", creator=REVIEW)   # beta, created by alpha's background agent: gets beta's -main agent, never the creator
put(3, project="projects/gamma", creator=BMAIN)    # gamma names no agent
put(4, needs=[REVIEW])                         # names a session in needs: the mover is that session
put(5, hold=True, wake="2099-01-01")           # parked: waits
put(6, needs=["decision"], ask="Decide: a or b · Recommend: a · Stakes: none · By: no date")   # Oliver's call
put(7, mover=REVIEW)                           # a stored mover
put(8, status="completed", outcome="done")      # closed
before = {i: (T / f"store/a/{i}.json").read_bytes() for i in range(1, 9)}
rows = migsvc._mover_backfill_pass(apply=False)
check("start pass, dry run: lists the items that would get a mover (alpha's, beta's, gamma's), and none of the ones that have a mover, wait, are his or are closed",
      {"a1", "a2", "a3"} <= {r["gid"] for r in rows} and not {f"a{i}" for i in range(4, 9)} & {r["gid"] for r in rows}, rows)
check("start pass, dry run: the builder, the -main agent, nobody for gamma; the creator is never the mover", {r["gid"]: r["mover"] for r in rows}["a1"] == BUILD and {r["gid"]: r["mover"] for r in rows}["a2"] == BMAIN
      and all(r["mover"] != r["creator"] for r in rows), rows)
check("start pass, dry run: writes nothing", all((T / f"store/a/{i}.json").read_bytes() == before[i] for i in range(1, 9)))
rows = migsvc._mover_backfill_pass(apply=True)
check("start pass: stores the builder / the -main agent as the mover; the creator never", rd(1)["metadata"].get("mover") == BUILD and rd(2)["metadata"].get("mover") == BMAIN and rd(2)["metadata"].get("owner") == REVIEW, (rd(1)["metadata"], rd(2)["metadata"]))
check("start pass: a project naming no agent leaves the item alone: no mover stored, the item's mover reads empty and is never its creator (BMAIN)", "mover" not in rd(3)["metadata"]
      and {r["gid"]: r["mover"] for r in rows}.get("a3", "") == "" and _item_read._model_of({**rd(3), "gid": "a3"}).mover == "" and telling.holder(rd(3)) == "" and rd(3)["metadata"].get("owner") == BMAIN,
      (rd(3)["metadata"], telling.holder(rd(3)), [r for r in rows if r["gid"] == "a3"]))
check("start pass: needs, a hold, Oliver's call, a stored mover and a closed item are untouched", all((T / f"store/a/{i}.json").read_bytes() == before[i] for i in range(4, 9)))
check("start pass: the clocks stay (a filing edit)", rd(1)["state_updated"] == now0 - 60 and rd(2)["state_updated"] == now0 - 60, (rd(1), rd(2)))
again = migsvc._mover_backfill_pass(apply=True)
check("start pass: idempotent: a second run writes nothing for the ones that got a mover", not [r for r in again if r["gid"] in ("a1", "a2")], again)

# ---- 3. D2: every notice goes to the mover alone
put(10, project="projects/alpha", creator=REVIEW, mover=BUILD)
told.clear()
res = _wt_complete.stackshot_complete("a10", sender=MAIN, outcome="done", reason="it is in", description="- Goal: The work is in place"); time.sleep(0.6)
to_ = [o for t, g, o, n in told if g == "a10"]
check("close: told to the item's mover (the builder) alone, never to its creator", to_ and set(map(SID, to_)) == {SID(BUILD)} and SID(REVIEW) not in map(SID, to_), told)
check("close: no reply and no notice names a keeper of record", NOKEEP(res) and all(NOKEEP(n) for t, g, o, n in told), res)
told.clear()
res = _update_svc._update("a10", status="open", next=f"{BUILD}: look again", sender=MAIN); time.sleep(0.6)
check("reopen: the creator is told nothing, and nothing says 'keeper of record'", SID(REVIEW) not in [SID(o) for t, g, o, n in told] and NOKEEP(res) and all(NOKEEP(n) for t, g, o, n in told), (told, res))

# ---- 4. D4: no refiling to the creator's project; D6: the item page, get and History say 'created by', never 'keeper of record'
put(11, project="projects/alpha", creator=MAIN, mover=MAIN)
res = _update_svc._update("a11", project="projects/beta", sender=MAIN)
check("move to another project: the project written is the project stored, no refile back to the creator's, no note about it", rd(11)["metadata"]["project"] == "projects/beta" and "refiled" not in res and "(note:" not in res and NOKEEP(res), res)
bd = ui_render.Board(str(T / "store"))
row = bd.item("a11")
page_html = bd.item_html("a11")
check("item page and get never say 'keeper of record'", NOKEEP(page_html) and NOKEEP(_wt_get.stackshot_get("a11")))
bd.item_versions = lambda r: [(now0 - 60, json.loads((T / "store/a/11.json").read_text()))]
evs, more = bd.item_events(row)
created = [h for _t, k, h in evs if k == "created"]
check("History: the creation line says 'created by <creator>' and nothing of a keeper of record", created and re.search(r"created by", created[0]) and NOKEEP(created[0]), evs)

# ---- 5. D7: an item Oliver moves sits under its `then` agent, else a 'no agent' group
put(12, needs=["decision"], ask="Decide: a or b · Recommend: a · Stakes: none · By: no date", then=BUILD)
put(13, needs=["decision"], ask="Decide: a or b · Recommend: a · Stakes: none · By: no date")
bd = ui_render.Board(str(T / "store"))
check("board: Oliver's item sits under its `then` agent", bd.lab(bd.item("a12")) == f"a/{BUILD}", bd.lab(bd.item("a12")))
check("board: Oliver's item with no `then` sits in the 'no agent' group, not under its creator", bd.lab(bd.item("a13")) == ui_render.Board.NO_AGENT == "no agent", bd.lab(bd.item("a13")))

# ---- 6. D9: `then` defaults to the builder doing the work
ASK = "Decide: pick a vendor · Recommend: yes · Stakes: B costs a month · By: no date"
put(14, project="projects/alpha", creator=MAIN, needs=[REVIEW])
res = _update_svc._update("a14", needs=["decision"], ask=ASK, sender=REVIEW)
check("D9: a background mover that hands the item to Oliver becomes its `then`", rd(14)["metadata"].get("then") == REVIEW and "then" in res, (rd(14)["metadata"], res[-300:]))
put(15, project="projects/alpha", creator=MAIN, mover=MAIN, next=f"{BUILD}: building the fix\nOliver: pick the vendor")
res = _update_svc._update("a15", needs=["decision"], ask=ASK, sender=MAIN)
check("D9: a front agent relaying an item whose next names the builder as building gets the builder as `then`, not itself", rd(15)["metadata"].get("then") == BUILD, (rd(15)["metadata"], res[-300:]))
r = _wt_create.stackshot_create(subject="[home] builder's own decision", description=DESC, project="projects/alpha", sender=BUILD, needs=["decision"], ask=ASK)
g9 = r.split()[1]
check("D9: a decision item the builder creates has the builder as its own `then`", rd(g9)["metadata"].get("then") == BUILD, (rd(g9)["metadata"], r[-300:]))

# ---- 7. D5 (retired): the idle raise and its "Nag again" button are gone; a raise stored before keeps its "Not needed" answer, an ordinary answer to the mover
check("button: no \"Nag again\" constant or idle options are left in the server: the idle pass raises no question to Oliver", not hasattr(server, "IDLE_RETRY_LABEL") and not hasattr(server, "_idle_options"), None)
since = time.time() - 600
STORED = [{"label": "Park until a day", "line": "On hold with a wake.", "recommended": True, "wake": "2099-01-01"}, {"label": "Not needed", "line": "It is no longer wanted: the item's mover closes it.", "recommended": False}]
(T / "store/a/16.json").write_text(json.dumps({"id": "16", "subject": "[home] idle one", "description": DESC, "status": "open", "updated": since, "state_updated": since, "confirmed": since,
    "metadata": {"owner": MAIN, "project": "projects/alpha", "mover": BUILD, "needs": ["decision"], "options": STORED, "idle": {"poked": since, "to": BUILD, "raised": since + 300},
                 "ask": "Decide: what to do with a16, idle on agent since earlier · Recommend: Park until a day · Stakes: the builder was asked and did not move it · By: no date"}}))
told.clear()
res = answer_svc._answer("a16", "Not needed", "", "")
check("Not needed: an ordinary answer to the mover, nothing is poked", res == "decision" and not [x for x in told if x[0] == "idle" and x[1] == "a16"], told)

# ---- 8. nothing left says 'keeper of record'
src = "".join(pathlib.Path(STACK, f).read_text(encoding="utf-8") for f in ("stackshot/web/server.py", "stackshot/web/wiring.py", "stackshot/web/render.py", "stackshot/web/ui/render.py", "stackshot/model/model.py", "stackshot/waits/waiting.py", "stackshot/router/router.py", "stackshot/router/router_live.py", "stackshot/anchors/anchors.py", "stackshot/github/ghsync.py", "stackshot/projects/pages.py", "stackshot/fleet/client.py", "stackshot/web/itempage.py", "stackshot/model/nextlines.py", "stackshot/model/steps.py"))
check("no code or tool text says 'keeper of record' (the retired term lives in tests/retired_terms.toml and the history SEED of whatschanged.py only)", "keeper of record" not in src.lower(), None)

print(f"{'ok' if not fails else 'FAILED'}: drop_keeper scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
