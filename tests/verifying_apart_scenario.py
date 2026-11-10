"""Scenario test for the verifying items in the board's totals — fixture data, the renderer only, no live store, no
network, no server socket.

An open item in the verifying state (stored: states.py never derives it) is work that is done and being checked, not work still to do: the item model reads it as waiting
on its end date. So board.md's head and the brief count it with the waiting ("7 open · 1 your move · 1 on agents · 5 waiting") and say nothing of verifying, and the project
table's open count holds every open item. The web board's home lists and the project page's Items count keep their verifying words.

Covers the brief line, the board.md header and its project table, the web board's home lists, and the project page's Items count.

    tests/run-suite verifying_apart        → exit 0 / 1"""
import json, os, re, sys, pathlib, tempfile, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="verifytest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
for d in ("fleet/a", "state/site", "state/anchor-hub", "secrets", "touch", "brain/projects"): (T / d).mkdir(parents=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
A = "22222222-2222-4222-8222-222222222222"
(T / "fleet/a/sessions.json").write_text(json.dumps({A: {"name": "home-agent", "machine": "a", "url": "", "seen": "x"}}))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
page = {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-agent", "status": "active", "board": [], "board_row": False, "updated": 1,
        "mirror": "https://example.invalid/alpha"}
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import render
from stackshot.web.ui import render as ui_render
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

def store(name, items):
    """A store dir holding the items {id: metadata + (status)}; returns its path."""
    S = T / name; (S / "a").mkdir(parents=True)
    (S / "projects.json").write_text(json.dumps({"pages": {"projects/alpha": page}})); (S / "anchors.json").write_text("{}"); (S / "next-id").write_text("100")
    for i, (md, status) in items.items():
        (S / f"a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.", "status": status,
                                                    "metadata": {"owner": A, "project": "projects/alpha", **md}, "updated": 1.0e9 + i}))
    return str(S)
VER = {"state": "verifying", "proof": "uptime 200 for 3 days", "end": "2026-10-30"}
D = "open"
# the fixture: 7 open items, 3 of them verifying (one of each: on agent, on hold, and one whose needs says decision; the model reads all three as waiting)
ITEMS = {
    1: ({"needs": "decision"}, D),                       # your call
    2: ({"needs": "external"}, D),                       # on others
    3: ({}, D),                                          # on agent
    4: ({**VER}, D),                                     # verifying, on agent
    5: ({**VER, "hold": True, "wake": "2026-11-20"}, D), # verifying, on hold
    6: ({**VER, "needs": "decision"}, D),                # verifying, but its needs said decision: out of your call
    7: ({"hold": True, "wake": "2026-11-20"}, D),        # on hold, not verifying
    8: ({}, "completed"),                                # a closed item: in neither count
}
wp = store("with", ITEMS)
b = render.Board(wp)
ub = ui_render.Board(wp)      # the page drawing is the ui renderer's; the totals, brief and board.md are the root Board's
# nothing about columns or grouping changed: the verifying items sit where they sat
cols = {"call": {r["gid"] for r in b.n_call}, "relay": {r["gid"] for r in b.n_relay}, "agent": {r["gid"] for r in b.agent}, "held": {r["gid"] for r in b.held}}
check("columns unchanged: the verifying items still sit where their fields put them", cols == {"call": {"a1", "a6"}, "relay": {"a2"}, "agent": {"a3", "a4"}, "held": {"a5", "a7"}}, cols)
check("is_verifying: exactly the three stored verifying items", sorted(r["gid"] for r in b.rows if render.is_verifying(r)) == ["a4", "a5", "a6"])
t = b.phase_counts()
check("counts: every open item is counted, the three verifying ones among the waiting", t == {"open": 7, "your_move": 1, "agents": 1, "alive": 2, "waiting": 5}, t)
check("counts: the parts add up to open", t["your_move"] + t["agents"] + t["waiting"] == t["open"] and t["alive"] == t["your_move"] + t["agents"], t)

# the brief line
first = b.brief().splitlines()[0]
check("brief: 7 open (1 your move, 1 on agents, 5 waiting)", first.startswith("Board: 7 open (1 your move, 1 on agents, 5 waiting), "), first)
check("brief: no verifying text on the line, and the states line is the alive / waiting one",
      "verifying" not in first and "  alive 2 (your move 1, agents 1) · waiting 5" in b.brief().splitlines() and not [l for l in b.brief().splitlines() if l.startswith("  states:")], first)

# board.md
md = b.markdown(); mh = next(l for l in md.splitlines() if " open" in l and "rendered by stackshot" in l)
check("board.md header: open, then your move, on agents, waiting", mh.startswith("_7 open · 1 your move · 1 on agents · 5 waiting ·") and "verifying" not in mh, mh)
mrow = next(l for l in md.splitlines() if l.startswith("| Alpha") or "Alpha" in l.split("|")[1:2].__str__() and l.startswith("|"))
check("board.md project table: every open item in the open count, no verifying text", re.search(r"\| 7 \|", mrow) is not None and "verifying" not in mrow, mrow)

# the web board
h = ub.html()
_sec = lambda html, sid: html[html.find(f'<section id="{sid}">'):html.find("</section>", html.find(f'<section id="{sid}">'))]
_hw, _hm = _sec(h, "waiting-list"), _sec(h, "your-move")
check("web home: no state tiles; the three verifying items are rows of Waiting, each naming its proof, and none is a row of Your move (a6's needs said decision)",
      'class="stat' not in h and all(f'id="task-a-{i}"' in _hw for i in (4, 5, 6)) and _hw.count("proof: uptime 200 for 3 days") == 3 and 'id="task-a-6"' not in _hm and 'id="task-a-1"' in _hm, _hw[:900])
check("web board: the sections still list the verifying items where they sit (grouping unchanged)",
      all(f'id="task-a-{i}"' in h for i in (1, 2, 3, 4, 5, 6, 7)))
ph = ub.routing_html("projects/alpha")
check("project page: the Items count is 4, with 3 verifying beside it", re.search(r'<h2>Items <span class="count">4</span> <span class="count dim">· 3 verifying</span>', ph) is not None,
      ph[ph.find("<h2>Items"):][:300])
check("project page: the groups still hold every open item (7 rows)", len(re.findall(r'id="task-a-\d+"', ph[ph.find("<h2>Items"):])) >= 7)

# none verifying: the same words, with no verifying text at all
zp = store("without", {i: ITEMS[i] for i in (1, 2, 3, 7, 8)})
z = render.Board(zp)
uz = ui_render.Board(zp)
tz = z.phase_counts(); fz = z.brief().splitlines()[0]
check("zero verifying: counts", (tz["open"], tz["your_move"], tz["agents"], tz["waiting"]) == (4, 1, 1, 2), tz)
check("zero verifying: the brief line has no verifying text", fz.startswith("Board: 4 open (1 your move, 1 on agents, 2 waiting), ") and "verifying" not in fz, fz)
mz = z.markdown(); mzh = next(l for l in mz.splitlines() if " open" in l and "rendered by stackshot" in l)
check("zero verifying: board.md header has no verifying text", mzh.startswith("_4 open · 1 your move · 1 on agents · 2 waiting") and "verifying" not in mzh, mzh)
check("zero verifying: board.md project table has no verifying text", not [l for l in mz.splitlines() if l.startswith("|") and "verifying" in l])
hz = uz.html()
check("zero verifying: no verifying text on the home page, and no proof in the Waiting list", ">verifying</span>" not in hz and "proof:" not in _sec(hz, "waiting-list") and 'id="task-a-1"' in _sec(hz, "your-move"), _sec(hz, "waiting-list")[:500])
pz = uz.routing_html("projects/alpha")
check("zero verifying: the project page's Items count has no verifying text", re.search(r'<h2>Items <span class="count">4</span>', pz) is not None and "verifying</span>" not in pz[pz.find("<h2>Items"):][:300], pz[pz.find("<h2>Items"):][:300])

# only verifying items open: open is 0 and the verifying count still shows
o = render.Board(store("only", {4: ITEMS[4], 5: ITEMS[5]}))
fo = o.brief().splitlines()[0]
check("only verifying open: 2 open, both waiting", fo.startswith("Board: 2 open (0 your move, 0 on agents, 2 waiting), "), fo)

print(f"ok: verifying-apart scenario, {len(ran)} checks" if not fails else f"{len(fails)} check(s) failed"); sys.stdout.flush(); os._exit(1 if fails else 0)
