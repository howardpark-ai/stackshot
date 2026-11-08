"""Scenario test for a design decision's mockup link (server._gate_mockup and ui/render.mockup_url) — fixture data, no live
store, no network, no server socket.

  1  the write gate: create and update refuse a needs=decision write whose description or next links a claude.ai artifact page while the
     ask does not, and an option (label or line) that holds a markdown link or a bare http(s) URL, saying the link goes in the ask; the refusal names the link and says to put [mockup](url) in the ask's Decide part, and nothing is written; a decision whose ask
     carries the link is accepted, and so is a decision with no artifact link anywhere; an item that is no decision is never judged
  2  the pages (ui/render.py): the home row (Your move) and the item page's Ask block draw
     "Mockup ↗" beside the question, opening the first link (the ask's, then the options', then the description's) in a new tab; an item with no
     artifact link draws none, and neither does a closed item
  3  the tool text: create and update say it in one line
  4  a mockup page of the fleet tool's web UI (https://<host>/mockup/<n>, the host from [client] mockup_hosts, the instance config only) counts like a claude.ai artifact page: the write
     gate, the first-link rule, the home row's and the item page's "Mockup ↗" (a plain link, never an iframe) and the bare link's label; a lookalike host, http://, a host with a port or
     userinfo, a non-numeric id and a link only quoted inside another address are no mockup; a missing, misshaped or empty key means no host and never crashes

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
from stackshot.web import server; from stackshot.web import home
from stackshot.web.ui import render as r2
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
check("1 create: the refusal reads like the others: one sentence of why, then the fix with the ask's form", e.startswith("Refused: this needs=decision item links a mockup") and "Decide: <what to decide> [mockup](<the mockup link>) · Recommend:" in e
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
OPT_WANT = ("Refused", "option 1", "clickable card", "ask's Decide part", "[mockup](<the mockup link>)")
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

# ================================================================ 4. a fleet tool's /mockup/<n> page
from stackshot.web import render as r1
cfgc = server._cfg.CFG.setdefault("client", {}); had_key = "mockup_hosts" in cfgc; was_key = cfgc.get("mockup_hosts")
try:
    HOST = "mockup.example.invalid"
    cfgc.pop("mockup_hosts", None)
    check("4 default: with no key there is no host, and a mockup page is no mockup (the claude.ai form still is)", r1.mockup_hosts() == () and r1.mockup_hit(f"https://{HOST}/mockup/7") == "" and r1.mockup_hit(ART) == ART, r1.mockup_hosts())
    cfgc["mockup_hosts"] = [HOST]
    SALA = f"https://{HOST}/mockup/7"
    DESC_SALA = f"- A new layout for the settings page, drawn at {SALA}\n- Done when the layout is picked"
    ASK_SALA = f"Decide: ship the new settings layout [mockup]({SALA})? · Recommend: yes · Stakes: low · By: Fri"
    refused("4 create: a decision whose description links a /mockup/<n> page and whose ask does not is refused", lambda: mk(description=DESC_SALA), *WANT, SALA, "description")
    refused("4 create: …and one whose next links it", lambda: mk(next=f"Oliver: answer the ask, see {SALA}"), *WANT, "next")
    refused("4 create: …the link at the end of a sentence is named without its dot", lambda: mk(description=f"- A new layout, see {SALA}.\n- Done when picked"), *WANT, f"({SALA}) in its description")
    out = mk(description=DESC_SALA, ask=ASK_SALA)
    gid = (re.match(r"created (\w\d+)", out) or [0, ""])[1]
    check("4 create: a decision whose ask carries the link is accepted", bool(gid) and SALA in rd(gid)["metadata"].get("ask", ""), out[:300])
    out = mk(description=DESC_SALA, ask=f"Decide: ship the new settings layout, see {SALA}, ok? · Recommend: yes · Stakes: low · By: Fri")
    check("4 create: …a bare link in the ask, followed by a comma, is accepted", bool(re.match(r"created \w\d+", out)), out[:300])
    refused("4 create: …a host in upper case is the same host", lambda: mk(description=f"- A new layout, drawn at {SALA.replace(HOST, HOST.upper())}\n- Done"), *WANT, HOST.upper())
    # an id that is not a number, a lookalike host, http, another port, userinfo and a link quoted in another address are no mockup anywhere
    NOT = [f"https://{HOST}.evil.example/mockup/1", f"http://{HOST}/mockup/1", f"https://{HOST}/mockup/abc", f"https://{HOST}/mockup/12x", f"https://{HOST}/mockup/",
           f"https://{HOST}:8443/mockup/1", f"https://{HOST}@evil.example/mockup/1", f"https://evil{HOST}/mockup/1", f"https://{HOST}/mockups/1", f"https://{HOST}/other/mockup/1",
           f"https://evil.example/?u={SALA.replace('https://', 'https%3A//')}", f"https://{HOST}/mockup/1_x", f"https://{HOST}/mockup/1.png",
           f"https://evil.example/?u=https://{HOST}/mockup/1", f"xhttps://{HOST}/mockup/1", f"https://{HOST}/mockup/1/../../terminal", f"https://{HOST}/mockup/1/%2e%2e/terminal",
           f"https://{HOST}/mockup/1/..%2f..%2fterminal", f"https://{HOST}/mockup/1/./x", f"https://evil.example/a/https://{HOST}/mockup/1", f"https://evil.example/a-https://{HOST}/mockup/1",
           f"https://{HOST}/mockup/7/..\\..\\terminal", f"https://{HOST}/mockup/7/..\\x", f"https://{HOST}/mockup/7/\\..\\..\\terminal", f"https://{HOST}/mockup/7/%5c..%5cx",
           f"https://{HOST}/mockup/7\\..\\x", f"https://{HOST}/mockup/7\\.\\x"]
    for u in NOT:
        mk_ok = mk(description=f"- A new layout, drawn at {u}\n- Done when picked", ask=ASK)
        check(f"4 create: {u.replace(HOST, '<host>')} is no mockup (a bare ask is accepted)", bool(re.match(r"created \w\d+", mk_ok)) and r1.mockup_hit(u) == "", (mk_ok[:200], r1.mockup_hit(u)))
    check("4 helper: the first link wins, trailing punctuation goes, a path or query stays", r1.mockup_hit(f"a {SALA}?x=1#top. b {ART}") == SALA + "?x=1#top" and r1.mockup_hit(f"({SALA}) and {ART}") == SALA
          and r1.mockup_hit(f"x {ART}, then {SALA}") == ART and r1.mockup_hit(f"{SALA}/") == SALA and r1.mockup_hit(f"{SALA}/v2.") == SALA + "/v2" and r1.mockup_hit(f"see {SALA}!") == SALA and r1.mockup_hit(None) == "", None)
    check("4 helper: a dot segment in the path is no mockup, a dot in the query or fragment is, and a later real link still counts", r1.mockup_hit(f"{SALA}?x=../y") == SALA + "?x=../y" and r1.mockup_hit(f"{SALA}/v1.2/x#a..b") == SALA + "/v1.2/x#a..b"
          and r1.mockup_hit(f"{SALA}/../../terminal and then {SALA}") == SALA and r1.mockup_hit(f"https://evil.example/?u={SALA} but ({SALA})") == SALA
          and r1.mockup_hit(f"({SALA}) and xhttps://{HOST}/mockup/2") == SALA and r1.mockup_hit(f"ftp:{SALA}") == "", None)
    # the scheme starts the token: only white space, a bracket, a quote or markdown emphasis may precede it (a link after # @ : , = and so on is quoted inside something else)
    check("4 helper: a link after # @ : , ; = | is no mockup, one wrapped in markdown, brackets, quotes or after white space is", all(r1.mockup_hit(f"x{c}{SALA}") == "" for c in "#@:,;=|~!") and r1.mockup_hit(f"a,{SALA}") == "" and r1.mockup_hit(f"a #{SALA}") == ""
          and all(r1.mockup_hit(t) == SALA for t in (f"[mockup]({SALA})", f"<{SALA}>", f'"{SALA}"', f"'{SALA}'", f"`{SALA}`", f"**{SALA}**", f"x\n{SALA}", f"{SALA}.", f"{SALA}, ok", f"[{SALA}]", SALA)), None)
    check("4 helper: a trailing dot segment is refused even though sentence punctuation is dropped", all(r1.mockup_hit(f"{SALA}{t}") == "" for t in ("/..", "/../", "/.", "/../.", "/%2e%2e", "/..?x=1", "/..\\x", "\\..", "/\\..\\..\\terminal", "/%5c..%5cx", "/%5C..", "\\%2e%2e")) and r1.mockup_hit(f"{SALA}/v1.") == SALA + "/v1" and r1.mockup_hit(f"{SALA}\\v1") == SALA + "\\v1" and r1.mockup_hit(f"_{SALA}_") == "", None)
    check("4 helper: a host needs letters or digits in every label: . .. - -a a-. and an empty label are no host", all(not re.fullmatch(r1._HOST_RX, h) for h in (".", "..", "-", "a..b", "-a", "a-", ".a", "a.", "a b", "")) and all(re.fullmatch(r1._HOST_RX, h) for h in (HOST, "a", "a-b.c1", "x.y-z.example")), None)
    item(30, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
    refused_nw("4 update: a description that adds a /mockup/<n> link to a decision with a bare ask is refused", 30, lambda: upd(30, description=DESC_SALA), *WANT, SALA)
    upd(30, description=DESC_SALA, ask=ASK_SALA)
    check("4 update: the same description is accepted with the link in the ask", rd(30)["metadata"]["ask"] == ASK_SALA, rd(30)["metadata"])
    refused_nw("4 update: an option holding a /mockup/<n> link is refused like any link", 30, lambda: upd(30, options=[{"label": "Approve", "line": f"Ship it, see {SALA}", "recommended": True}, OPTS[1]]), *OPT_WANT)
    # the pages
    item(31, needs=["decision"], ask=ASK, desc=DESC_SALA, mover="Oliver", then="team-back")                       # stored before the gate: the description's link
    item(32, needs=["decision"], ask=ASK_SALA, mover="Oliver", then="team-back")                                    # the ask carries it: drawn once as a link, no chip
    item(33, needs=["decision"], ask=f"Decide: ship the layout at {SALA} ? · Recommend: yes · Stakes: low · By: Fri", mover="Oliver", then="team-back")   # a bare link in the ask: labeled
    item(34, needs=["decision"], ask=ASK, desc=f"- see https://{HOST}.evil.example/mockup/1 and http://{HOST}/mockup/1", mover="Oliver", then="team-back")
    item(35, status="completed", needs=["decision"], ask=ASK_SALA, desc=DESC_SALA, outcome="done", reason="picked")
    check("4 pages: mockup_url finds the /mockup/<n> link (ask first), none for lookalikes, none for a closed item", r2.mockup_url(rd(31) | {"gid": "a31"}) == SALA and r2.mockup_url(rd(32) | {"gid": "a32"}) == SALA
          and r2.mockup_url(rd(34) | {"gid": "a34"}) == "" and r2.mockup_url(rd(35) | {"gid": "a35"}) == "", None)
    b2 = r2.Board(f"{tmp}/store")
    ym2 = {r["gid"]: (r, m) for r, m in b2.home_pairs()[home.YOUR_MOVE]}
    row = b2.home_row(*ym2["a31"], home.YOUR_MOVE)
    q = re.search(r'<span class="hnext hq">(.*?)</span></div>', row, re.S)
    check("4 home: row a31 shows Mockup ↗ beside the question, a plain link to the page in a new tab", bool(q) and q.group(1).endswith(LINK(SALA)) and "<iframe" not in row, row[:900])
    row = b2.home_row(*ym2["a32"], home.YOUR_MOVE)
    check("4 home: a question that carries the link itself draws no second one", 'class="mockup"' not in row and row.count(SALA) == 1, row[:900])
    row = b2.home_row(*ym2["a34"], home.YOUR_MOVE)
    check("4 home: a decision linking only lookalikes shows no chip", 'class="mockup"' not in row and "Mockup" not in row, row[:600])
    pg = b2.item_html("a31")
    blk = re.search(r'<div class="iask"><b>Ask</b><dl>(.*?)</dl>', pg, re.S)
    check("4 page: a31's Ask block shows Mockup ↗ once, and the page embeds nothing", bool(blk) and LINK(SALA) in blk.group(1) and pg.count('class="mockup"') == 1 and "<iframe" not in pg, blk.group(1)[:600] if blk else pg[:300])
    pg = b2.item_html("a32")
    check("4 page: a32 draws its own link once, and no chip", pg.count(f'href="{SALA}"') == 1 and 'class="mockup"' not in pg and "<iframe" not in pg, None)
    pg = b2.item_html("a33")
    check("4 page: a bare link in the ask is labeled mockup, not the host", f'href="{SALA}"' in pg and f">{HOST}</a>" not in pg and ">mockup ↗</a>" in pg, re.findall(r"<a [^>]*mockup[^>]*>[^<]*</a>", pg))
    check("4 page: a closed item and a lookalike draw no chip", 'class="mockup"' not in b2.item_html("a35") and 'class="mockup"' not in b2.item_html("a34"), None)
    check("4 label: a lookalike host keeps its host as the label, a claude.ai artifact link its own", r2.link_label(NOT[0]) == f"{HOST}.evil.example" and r2.link_label(ART) == "session" and r2.link_label(SALA) == "mockup"
          and r1.link_label(SALA) == "mockup" and r1.link_label(NOT[10]) != "mockup", None)
    # the host is the instance's alone: a missing, empty or misshaped key means no host and never crashes
    OTHER = "https://other-a.example.invalid/mockup/9"
    cfgc["mockup_hosts"] = ["other-a.example.invalid", "Other-B.Example.Invalid", 5, "bad host/", ""]
    check("4 config: a listed host counts (any case, junk entries dropped) and a host not listed does not", r1.mockup_hosts() == ("other-a.example.invalid", "other-b.example.invalid") and r1.mockup_hit(f"x {OTHER}") == OTHER
          and r1.mockup_hit("https://OTHER-B.example.invalid/mockup/3") == "https://OTHER-B.example.invalid/mockup/3" and r1.mockup_hit(SALA) == "" and r1.mockup_hit(ART) == ART, r1.mockup_hosts())
    refused("4 config: the gate follows the configured host", lambda: mk(description=f"- drawn at {OTHER}\n- Done"), *WANT, OTHER)
    cfgc["mockup_hosts"] = "other-a.example.invalid"
    check("4 config: one name as a string is a list of one", r1.mockup_hosts() == ("other-a.example.invalid",) and r1.mockup_hit(OTHER) == OTHER, r1.mockup_hosts())
    cfgc["mockup_hosts"] = []
    check("4 config: an empty list means no host: the /mockup/<n> rule is off and the rest keeps the claude.ai one", r1.mockup_hit(SALA) == "" and r1.mockup_hit(ART) == ART, None)
    check("4 config: …and the lookbehind and dot-segment rules do not touch the claude.ai form", r1.mockup_hit(f"x https://evil.example/?u={ART}") == ART and r1.mockup_hit(f"{ART}/../x") == ART + "/../x", None)
    out = mk(description=DESC_SALA, ask=ASK)
    check("4 config: …so a bare ask beside a /mockup/<n> description is accepted", bool(re.match(r"created \w\d+", out)), out[:300])
    for bad in ([5], ["x.example:80"], ["."], [".."], ["-"], ["a..b"], [""], "", [None, "bad host/"], ("", ), "a b", 5, {"a": 1}, None, True):
        cfgc["mockup_hosts"] = bad
        check(f"4 config: a value with no usable host ({bad!r}) means no host and does not crash", r1.mockup_hosts() == () and r1.mockup_hit(SALA) == "" and r1.mockup_hit(ART) == ART, r1.mockup_hosts())
    server._cfg.CFG.pop("client", None)
    check("4 config: no [client] section at all means no host", r1.mockup_hosts() == () and r1.mockup_hit(SALA) == "" and r1.mockup_hit(ART) == ART, r1.mockup_hosts())
finally:
    server._cfg.CFG["client"] = cfgc
    if had_key: cfgc["mockup_hosts"] = was_key
    else: cfgc.pop("mockup_hosts", None)

# ================================================================ 3. the tool text
snap = json.loads(pathlib.Path(STACK, "tests/tool_text.snapshot.json").read_text(encoding="utf-8"))["tools"]
for tool in ("create", "update"):
    d = snap[tool]["description"]
    check(f"3 text: {tool} names the /mockup/<n> page beside the claude.ai artifact page", "claude.ai/artifact/… page, or a /mockup/<n> page of the fleet tool's web UI (host set in the instance config)) puts [mockup]" in d, d[:200])
    check(f"3 text: {tool} says a decision's mockup link goes in the ask's Decide part", "puts [mockup](<that link>) in the ask's Decide part too, or the write is refused" in d and "Mockup ↗ beside the question" in d, d[:200])
    check(f"3 text: {tool} says a mockup link goes in the ask only and an option holding a link is refused", "goes in the ask only" in d and "markdown link" in d and "http(s) URL" in d and "is refused" in d, d[:200])
    check(f"3 text: {tool} no longer lets the options carry the mockup link", "description, next or options link a mockup" not in d, d[:200])

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": decision mockup scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
