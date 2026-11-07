#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["fastmcp>=4.0,<5", "httpx", "markdown-it-py>=4,<5"]
#
# [tool.uv]
# exclude-newer = "2026-10-03T04:00:00Z"
# ///
"""Scenario test for a design decision's mockup link (server._gate_mockup and ui/render.mockup_url) — fixture data, no live
store, no network, no server socket.

  1  the write gate: create and update refuse a needs=decision write whose description or next links a claude.ai artifact page while the
     ask does not, and an option (label or line) that holds a markdown link or a bare http(s) URL, saying the link goes in the ask; the refusal names the link and says to put [mockup](url) in the ask's Decide part, and nothing is written; a decision whose ask
     carries the link is accepted, and so is a decision with no artifact link anywhere; an item that is no decision is never judged
  2  the pages (ui/render.py): the home row (Your move) and the item page's Ask block draw
     "Mockup ↗" beside the question, opening the first link (the ask's, then the options', then the description's) in a new tab; an item with no
     artifact link draws none, and neither does a closed item
  3  the tool text: create and update say it in one line

    uv run tests/decision_mockup_scenario.py        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="mockup-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
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
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
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

ART = "https://claude.ai/artifact/00000000-0000-4000-8000-000000000053"         # a made-up artifact id
ART2 = "https://claude.ai/code/artifact/00000000-0000-4000-8000-000000000054"
DESC = "- A new layout for the settings page\n- Done when the layout is picked"
DESC_ART = f"- A new layout for the settings page, drawn in [the mockup]({ART})\n- Done when the layout is picked"
ASK = "Decide: ship the new settings layout? · Recommend: yes · Stakes: low · By: Fri"
ASK_ART = f"Decide: ship the new settings layout [mockup]({ART})? · Recommend: yes · Stakes: low · By: Fri"
ASK_REC = f"Decide: ship the new settings layout? · Recommend: yes, see [mockup]({ART}) · Stakes: low · By: Fri"       # the link in a part the home row does not show
OPTS = [{"label": "Approve", "line": "Ship the new layout.", "recommended": True}, {"label": "Decline", "line": "Keep the old one.", "recommended": False}]
OPTS_ART = [{"label": "Approve", "line": f"Ship the layout in {ART2}.", "recommended": True}, {"label": "Decline", "line": "Keep the old one.", "recommended": False}]


def item(i, status="open", desc=None, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] settings layout {i}", "description": desc or DESC, "status": status, "updated": now0 - 3 * H,
                                                      "state_updated": now0 - 3 * H, "confirmed": now0 - 3 * H,
                                                      "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "Oliver: answer the ask", **meta}}))
def rd(i): return json.loads((T / (f"store/{i[0]}/{i[1:]}.json" if isinstance(i, str) else f"store/a/{i}.json")).read_text())
raw = lambda i: (T / f"store/a/{i}.json").read_text()
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
def refused_nw(name, i, f, *want):
    was = raw(i); refused(name, f, *want); check(name + " (nothing written)", raw(i) == was, None)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
import server, home
from ui import render as r2
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda *a, **k: None
upd = lambda i, sender="home-front", **kw: server._update(f"a{i}", sender=sender, **kw)
mk = lambda **kw: server._create(**{"subject": "[home] pick the settings layout", "description": DESC, "project": "projects/alpha", "owner": "home-front",
                                    "next": "Oliver: answer the ask", "needs": ["decision"], "ask": ASK, **kw})
WANT = ("Refused", "mockup", "[mockup](", "Decide part")

# ================================================================ 1. the write gate
refused("1 create: a decision whose description links a mockup and whose ask does not is refused", lambda: mk(description=DESC_ART), *WANT, ART, "description")
refused("1 create: …and one whose next links it", lambda: mk(next=f"Oliver: answer the ask, see {ART}"), *WANT, "next")
e = ""
try: mk(description=DESC_ART)
except Exception as ex: e = str(ex)
check("1 create: the refusal reads like the others: one sentence of why, then the fix with the ask's form", e.startswith("Refused: this needs=decision item links a mockup") and "Decide: <what to decide> [mockup](<the artifact link>) · Recommend:" in e
      and "Oliver opens the design from the question he answers" in e, e)
out = mk(description=DESC_ART, ask=ASK_ART)
gid = (re.match(r"created (\w\d+)", out) or [0, ""])[1]
check("1 create: a decision whose ask carries the link is accepted", bool(gid) and ART in rd(gid)["metadata"].get("ask", ""), out[:300])
out = mk(options=OPTS)
gid2 = (re.match(r"created (\w\d+)", out) or [0, ""])[1]
check("1 create: a decision with no artifact link anywhere is accepted", bool(gid2), out[:300])
out = server._create(subject="[home] build the settings layout", description=DESC_ART, project="projects/alpha", owner="home-front", next="team-back: build it", needs=["team-back"])
check("1 create: an item that is no decision may link a mockup anywhere", bool(re.match(r"created \w\d+", out)), out[:300])

item(1, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
refused_nw("1 update: a description that adds a mockup link to a decision with a bare ask is refused", 1, lambda: upd(1, description=DESC_ART), *WANT, ART)
refused_nw("1 update: …a next that adds one", 1, lambda: upd(1, next=f"Oliver: answer the ask, see {ART}"), *WANT)
item(2, needs=["team-back"], desc=DESC_ART, next="team-back: build it")
refused_nw("1 update: …a move to needs=decision of an item whose description links one, with a bare ask", 2, lambda: upd(2, needs=["decision"], ask=ASK, mover="Oliver", then="team-back"), *WANT)
upd(1, description=DESC_ART, ask=ASK_ART)
check("1 update: the same description is accepted with the link in the ask", ART in rd(1)["description"] and rd(1)["metadata"]["ask"] == ASK_ART, rd(1)["metadata"])
item(3, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
upd(3, description="- A new layout for the settings page\n- Done when a layout is picked", options=OPTS)
check("1 update: a decision with no artifact link anywhere is accepted", rd(3)["metadata"].get("options") == OPTS, rd(3)["metadata"])
item(4, needs=["team-back"], next="team-back: build it")
upd(4, description=DESC_ART)
check("1 update: an item that is no decision may link one", ART in rd(4)["description"], rd(4))

# ---- an option is a clickable card: no link in it, the mockup link goes in the ask
def opts_with(label=None, line=None):
    return [{"label": label or "Approve", "line": line or "Ship the new layout.", "recommended": True}, {"label": "Decline", "line": "Keep the old one.", "recommended": False}]
OPT_WANT = ("Refused", "option 1", "clickable card", "ask's Decide part", "[mockup](<the artifact link>)")
refused("1 create: an option line with a markdown link is refused, naming the option and saying the link goes in the ask", lambda: mk(options=opts_with(line=f"Ship the layout drawn in [mockup]({ART2}).")), *OPT_WANT, "(Approve)", "[mockup](")
refused("1 create: …a bare URL in the line", lambda: mk(options=opts_with(line=f"Ship the layout drawn at {ART2}")), *OPT_WANT, ART2)
refused("1 create: …a bare http URL in the label", lambda: mk(options=opts_with(label="See http://example.test/x")), *OPT_WANT, "http://example.test/x")
refused("1 create: …a link in the second option names that option", lambda: mk(options=[OPTS[0], {"label": "Decline", "line": "Keep it, see [old](https://example.test/old).", "recommended": False}]), "Refused", "option 2", "(Decline)")
refused("1 create: …a link in an option is refused when the ask carries the mockup link too", lambda: mk(ask=ASK_ART, options=OPTS_ART), *OPT_WANT)
out = mk(options=opts_with(line="Ship the new layout as drawn in the mockup of the ask."))
check("1 create: a clean option is accepted", bool(re.match(r"created \w\d+", out)), out[:300])
out = mk(ask=ASK_ART, options=OPTS)
check("1 create: an ask with the mockup link and clean options is accepted", bool(re.match(r"created \w\d+", out)), out[:300])
item(5, needs=["decision"], ask=ASK_ART, mover="Oliver", then="team-back")
refused_nw("1 update: an option line with a markdown link is refused", 5, lambda: upd(5, options=opts_with(line=f"Ship it, see [mockup]({ART2}).")), *OPT_WANT)
refused_nw("1 update: …a bare URL in an option", 5, lambda: upd(5, options=OPTS_ART), *OPT_WANT, ART2)
upd(5, options=OPTS)
check("1 update: clean options on an ask that carries the link are accepted", rd(5)["metadata"].get("options") == OPTS and ART in rd(5)["metadata"]["ask"], rd(5)["metadata"])

# ================================================================ 2. the pages
item(10, needs=["decision"], ask=ASK_ART, options=OPTS_ART, desc=DESC_ART, mover="Oliver", then="team-back")      # the ask's link wins, and it is drawn already: no chip beside it
item(11, needs=["decision"], ask=ASK, options=OPTS_ART, desc=DESC_ART, mover="Oliver", then="team-back")          # stored before the gate: the options' link, then the description's
item(12, needs=["decision"], ask=ASK, desc=DESC_ART, mover="Oliver", then="team-back")
item(13, needs=["decision"], ask=ASK, options=OPTS, mover="Oliver", then="team-back")                             # no link anywhere
item(15, needs=["decision"], ask=ASK_REC, desc=DESC_ART, mover="Oliver", then="team-back")                          # the ask's link sits in Recommend: the home row shows only Decide
item(14, status="completed", needs=["decision"], ask=ASK_ART, desc=DESC_ART, outcome="done", reason="picked")
LINK = lambda u: f'<a class="mockup" href="{u}" target="_blank" rel="noopener" title="open the mockup this decision is about">Mockup ↗</a>'
check("2 pages: the first link is the ask's, then the options', then the description's", r2.mockup_url(rd(10) | {"gid": "a10"}) == ART and r2.mockup_url(rd(11) | {"gid": "a11"}) == ART2
      and r2.mockup_url(rd(12) | {"gid": "a12"}) == ART and r2.mockup_url(rd(15) | {"gid": "a15"}) == ART and r2.mockup_url(rd(13) | {"gid": "a13"}) == "" and r2.mockup_url(rd(14) | {"gid": "a14"}) == "", None)
b = r2.Board(f"{tmp}/store")
ym = {r["gid"]: (r, m) for r, m in b.home_pairs()[home.YOUR_MOVE]}
for i, u in ((11, ART2), (12, ART), (15, ART)):
    row = b.home_row(*ym[f"a{i}"], home.YOUR_MOVE)
    q = re.search(r'<span class="hnext hq">(.*?)</span></div>', row, re.S)
    check(f"2 home: row a{i} shows Mockup ↗ beside the question, opening {u.rsplit('/', 2)[-2]} in a new tab", bool(q) and q.group(1).endswith(LINK(u)) and "ship the new settings layout" in q.group(1), row[:900])
row = b.home_row(*ym["a10"], home.YOUR_MOVE)
q = re.search(r'<span class="hnext hq">(.*?)</span></div>', row, re.S)
check(f"2 home: a question that carries the link itself draws no second one beside it", bool(q) and 'class="mockup"' not in row and q.group(1).count(ART) == 1 and "ship the new settings layout" in q.group(1), row[:900])
row = b.home_row(*ym["a13"], home.YOUR_MOVE)
check(f"2 home: a decision with no artifact link shows none", "hnext hq" in row and 'class="mockup"' not in row and "Mockup" not in row, row[:600])
for i, u in ((11, ART2), (12, ART), (15, None)):
    pg = b.item_html(f"a{i}")
    blk = re.search(r'<div class="iask"><b>Ask</b><dl>(.*?)</dl>', pg, re.S)
    if u is None:       # the item whose ask carries the link in its Recommend part, drawn once, and no chip
        check(f"2 page: a{i}'s Ask block carries the ask's own link once and no chip", bool(blk) and blk.group(1).count(ART) == 1 and 'class="mockup"' not in pg, blk.group(1)[:600] if blk else pg[:300])
        continue
    check(f"2 page: a{i}'s Ask block shows Mockup ↗ in its Decide part", bool(blk) and re.search(r"<dt>Decide</dt><dd>[^<]*.*?" + re.escape(LINK(u)) + "</dd><dt>Recommend</dt>", blk.group(1), re.S) is not None,
          blk.group(1)[:600] if blk else pg[:300])
    check(f"2 page: …once", pg.count('class="mockup"') == 1, pg.count('class="mockup"'))
blk = re.search(r'<div class="iask"><b>Ask</b><dl>(.*?)</dl>', b.item_html("a10"), re.S)
check(f"2 page: a question that carries the link itself draws no chip beside it", bool(blk) and 'class="mockup"' not in b.item_html("a10") and blk.group(1).count(ART) == 1, blk.group(1)[:600] if blk else None)
pg = b.item_html("a13")
check(f"2 page: a decision with no artifact link draws none", '<div class="iask"><b>Ask</b>' in pg and 'class="mockup"' not in pg, None)
check(f"2 page: a closed item draws none", 'class="mockup"' not in b.item_html("a14"), None)
css = b._css()
check(f"2 style: the link keeps its two words together and the question still wraps (no overflow at a phone's width)", "a.mockup{white-space:nowrap" in css and ".hnext,.hwait{display:block;min-width:0;overflow-wrap:anywhere" in css, None)

# ================================================================ 3. the tool text
snap = json.loads(pathlib.Path(STACK, "tests/tool_text.snapshot.json").read_text(encoding="utf-8"))["tools"]
for tool in ("create", "update"):
    d = snap[tool]["description"]
    check(f"3 text: {tool} says a decision's mockup link goes in the ask's Decide part", "puts [mockup](<that link>) in the ask's Decide part too, or the write is refused" in d and "Mockup ↗ beside the question" in d, d[:200])
    check(f"3 text: {tool} says a mockup link goes in the ask only and an option holding a link is refused", "goes in the ask only" in d and "markdown link" in d and "http(s) URL" in d and "is refused" in d, d[:200])
    check(f"3 text: {tool} no longer lets the options carry the mockup link", "description, next or options link a mockup" not in d, d[:200])

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": decision mockup scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
