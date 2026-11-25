"""Scenario test for the Machines panel's rows from the posted machine list (service/machines_panel.py, fleet/caller_keys.py `paired()`, ui/render.py `Board.fleet_list_html` and the panel's machines block): fixture data in a temporary instance,
the board's own renderer, no live store, no network, no server. Names and addresses are made up.

Covers:
  1  `paired()` is the one reader of "a fleet manager is paired": false with nothing, with an approved key and no token, with a token and no key, with a key still waiting for the owner, with a key file or a token file that cannot be read,
     with an approved entry that is no key, and with a token entry that holds no SHA-256; true with an approved key and a token; false again the moment the key is revoked (the files are read at each call);
  2  a board that is not paired draws nothing from the list, whatever file is on disk: its Machines block is byte for byte what it is with no list file at all, and holds no fleet list, no age line and no list text;
  3  a paired board with no list yet says so in one line and draws no card; with a list file that cannot be read (absent, empty, torn, another schema, `machines` that is no list, a folder, a link) it does the same and never raises;
  4  a paired board with a fresh list: a card per machine in the posted order, with name, hostname, letter and roles; the retired flag on the retired one only; the age line ("updated ... ago", the server's clock at the post);
     the names not read as one note (at most 20 named, then how many more); the old package cards untouched (the block minus the fleet list is the unpaired block);
  5  a stale list (older than 15 minutes, 899 s fresh and 901 s stale) is still drawn, with its age in its own words and the stale mark; a very old list reads its age in days;
  6  every stored text is escaped: a `<script>`, a quote, an ampersand and a `javascript:` text in name, hostname, letter, ssh, addresses, sources and not_read draw as text (the fleet list holds only div, b, span and p tags with
     class and title attributes, no link, no `href` or `src`, no event attribute), in the panel block and in the whole page, which holds no script tag more than it does without the list;
  7  a stored file whose fields are of the wrong kind (a hand-edited one) draws without raising;
  8  200 machines (the most a post may hold) draw as 200 cards on the page, which still renders;
  9  `view()` never raises: a store that cannot be read is no view.

    tests/run-suite machines_panel        -> exit 0 / 1"""
import datetime, html.parser, json, os, pathlib, re, sys, time, logging

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="machinespanel-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^latest_lookups = true', 'latest_lookups = false', toml); assert n == 1       # never npm or GitHub
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state", "secrets", "brain/projects", "home", "touch"): (T / d).mkdir(parents=True)
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("1"); (T / "store/anchors.json").write_text("{}")

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.core import config as _cfg
from stackshot.fleet import caller_keys as KEYS
from stackshot.service import machines_list as SVC
from stackshot.service import machines_panel as MP
from stackshot.web.ui import render as ui_render

STATE, SECRETS = T / "state", T / "secrets"; LISTFILE = STATE / "machines-list.json"
KEY = "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"      # 32 bytes in base64url: the public key of a published test vector (a real point of the curve, no weak key)
TOKEN_ENTRY = {"sha256": "ab" * 32, "created": "2026-01-01T00:00:00+00:00"}

def now_dt(): return datetime.datetime.now(_cfg.tz())
def board(): return ui_render.Board(str(T / "store"), now=now_dt())
def block(b=None): return (b or board()).panel_blocks()["machines"]
def page(): return board().render({"html"})["html"]
def mach(name="box-one", **over):
    m = {"name": name, "hostname": name + ".example.net", "letter": "a", "ssh": "user@" + name, "addresses": ["192.0.2.10", "2001:db8::10"], "roles": ["sala-host"], "retired": False, "sources": ["fleet.json"]}
    m.update(over); return m
def clear():
    """No list file: only the list's own path is touched, the rest of the state folder is the board's."""
    if LISTFILE.is_dir() and not LISTFILE.is_symlink():
        [q.unlink() for q in LISTFILE.iterdir()]; LISTFILE.rmdir()
    else: LISTFILE.unlink(missing_ok=True)
def store(machines, ago_s=30.0, not_read=(), post=True):
    """The list file as a post leaves it, with `received` set `ago_s` seconds back."""
    clear()
    body = {"schema": 1, "written": time.time() - 5, "machines": machines, "not_read": list(not_read)}
    if post:
        st, ans = SVC.post("box-x", body); assert st == 200, (st, ans)
        d = json.loads(LISTFILE.read_text()); d["received"] = time.time() - ago_s; LISTFILE.write_text(json.dumps(d))
    else:
        LISTFILE.write_text(json.dumps({"schema": 1, "written": time.time() - 5, "received": time.time() - ago_s, "posted_by": "box-x", "high": time.time() - 5, **{k: v for k, v in body.items() if k not in ("schema", "written")}}))
def pair():
    fp = None
    st, fp, _e = KEYS.enroll(KEY, "fleet manager", "fleet-tool")
    assert st in ("pending", "approved"), st
    if st == "pending": KEYS.approve(fp[:16])
    (SECRETS / "clients.json").write_text(json.dumps({"box-x": TOKEN_ENTRY}))
    return fp
def unpair(fp):
    KEYS.revoke(fp[:16]); (SECRETS / "clients.json").unlink(missing_ok=True)
def fleet_part(h):
    i = h.find('<p class="mnote fl-age'); j = h.find('<div class="fleetlist">')
    k = min(x for x in (i, j) if x >= 0) if i >= 0 or j >= 0 else -1
    return "" if k < 0 else h[k:h.find('<div class="matrix">')]
def cards(h): return re.findall(r'<div class="pc fl( ret)?"( title="[^"]*")?><b class="lbl fn">([^<]*)</b><span class="lbl st">([^<]*)</span>(?:<span class="val fm">([^<]*)</span>)?</div>', h)

class Tags(html.parser.HTMLParser):
    """Every tag and attribute of a fragment: what a stored text could have started if it had not been escaped."""
    def __init__(self): super().__init__(); self.tags = []; self.attrs = set()
    def handle_starttag(self, tag, attrs): self.tags.append(tag); self.attrs.update(a for a, _v in attrs)
    handle_startendtag = handle_starttag

# ================================================================ 1. paired(): the one reader
baseline_block = block()
check("1 nothing at all: not paired", KEYS.paired() is False)
(SECRETS / "clients.json").write_text(json.dumps({"box-x": TOKEN_ENTRY}))
check("1 a token and no key: not paired", KEYS.paired() is False)
(SECRETS / "clients.json").unlink()
st, fp0, _e = KEYS.enroll(KEY, "fleet manager", "fleet-tool")
check("1 a key still waiting for the owner, no token: not paired", st == "pending" and KEYS.paired() is False, st)
(SECRETS / "clients.json").write_text(json.dumps({"box-x": TOKEN_ENTRY}))
check("1 a key still waiting for the owner, with a token: not paired (a pending key is trusted for nothing)", KEYS.paired() is False)
KEYS.approve(fp0[:16])
check("1 an approved key and a token: paired", KEYS.paired() is True)
(SECRETS / "clients.json").unlink()
check("1 an approved key and no token: not paired", KEYS.paired() is False)
for label, text in (("not JSON", "{nope"), ("a list", "[]"), ("an entry with no hash", json.dumps({"m": {"created": "x"}})), ("a hash of the wrong shape", json.dumps({"m": {"sha256": "zz"}})), ("an entry that is no object", json.dumps({"m": "x"}))):
    (SECRETS / "clients.json").write_text(text)
    check(f"1 a token file that is {label}: not paired, no error", KEYS.paired() is False)
(SECRETS / "clients.json").write_text(json.dumps({"box-x": TOKEN_ENTRY}))
good_keys = (SECRETS / "keys.json").read_text()
(SECRETS / "keys.json").write_text("{nope")
check("1 a key file that cannot be read: not paired, no error", KEYS.paired() is False)
(SECRETS / "keys.json").write_text(json.dumps({"f" * 64: {"public_key": "not a key", "label": "x", "sender": "x"}}))
check("1 an approved entry that is no key: not paired", KEYS.paired() is False)
(SECRETS / "keys.json").write_text(good_keys)
check("1 the good file again: paired (read at each call)", KEYS.paired() is True)
KEYS.revoke(fp0[:16])
check("1 revoked: not paired at once", KEYS.paired() is False)
(SECRETS / "clients.json").unlink()
check("1 the board is as it was before any pairing", block() == baseline_block)

# ================================================================ 2. not paired: nothing from the list
store([mach("alpha-box"), mach("beta-box", retired=True)], not_read=["unread-file.json"])
unp = block()
for what, mid in (("no key, no token", lambda: None), ("a token only", lambda: (SECRETS / "clients.json").write_text(json.dumps({"box-x": TOKEN_ENTRY}))),):
    mid()
    h = block()
    check(f"2 not paired ({what}) with a good list on disk: the block is the block of a board with no list", h == baseline_block, None)
    check(f"2 not paired ({what}): no fleet list, no age line, no text of the list", 'fleetlist' not in h and 'fl-age' not in h and "alpha-box" not in h and "unread-file" not in h and "machine list" not in h)
(SECRETS / "clients.json").unlink(missing_ok=True)
check("2 a list on disk and not paired: the page holds nothing of it", "alpha-box" not in page() and '<div class="fleetlist">' not in page())
check("2 the view of an unpaired board is None", MP.view(time.time()) is None)

# ================================================================ 3. paired, no list or none readable
clear(); fp = pair()
h = block()
check("3 paired, no list yet: one line says so, no card, no age line", 'no machine list received yet' in h and 'fleetlist' not in h and 'fl-age' not in h and MP.view(time.time()) == {"list": None}, fleet_part(h)[:300])
check("3 paired, no list yet: the old cards are there", 'class="pc mach' in h and ">testbox<" in h)
bad = {"absent": None, "empty": "", "torn": '{"schema": 1, "written": 17', "another schema": json.dumps({"schema": 2, "written": 1.0, "received": 1.0, "posted_by": "x", "machines": [], "not_read": []}),
       "machines no list": json.dumps({"schema": 1, "written": 1.0, "received": 1.0, "posted_by": "x", "machines": "box", "not_read": []}),
       "no received": json.dumps({"schema": 1, "written": 1.0, "posted_by": "x", "machines": [], "not_read": []}), "no object": "[1, 2]"}
for what, text in bad.items():
    clear()
    if text is not None: LISTFILE.write_text(text)
    try: h = block(); err = None
    except Exception as e: h, err = "", e
    check(f"3 paired, a list file that is {what}: no row, the none line, no error", err is None and 'no machine list received yet' in h and 'fleetlist' not in h, err)
clear(); LISTFILE.mkdir()
check("3 paired, a folder at the list's path: no row, no error", 'no machine list received yet' in block() and 'fleetlist' not in block())
clear(); LISTFILE.symlink_to(T / "elsewhere.json"); (T / "elsewhere.json").write_text("{}")
check("3 paired, a link at the list's path: no row, no error", 'no machine list received yet' in block() and 'fleetlist' not in block())
clear()

# ================================================================ 4. paired, a fresh list
nr = [f"file-{i}.json" for i in range(25)]
store([mach("alpha-box", hostname="alpha.example.net", letter="a", roles=["sala-host", "stackshot-host"]), mach("beta-box", hostname=None, letter=None, roles=[], retired=True), mach("gamma-box", letter="c", roles=["stackshot-host"])], 30.0, not_read=nr)
h = block(); fl = fleet_part(h); cs = cards(fl)
check("4 a card per machine, in the posted order", [c[2] for c in cs] == ["alpha-box", "beta-box", "gamma-box"], cs)
check("4 name, hostname, letter and roles on the card's line", cs[0][4] == "alpha.example.net · letter a · sala-host, stackshot-host" and cs[2][4] == "gamma-box.example.net · letter c · stackshot-host", cs)
check("4 a machine with no hostname, letter or role has no line", cs[1][4] == "", cs[1])
check("4 the retired flag is on the retired machine only", [bool(c[0]) for c in cs] == [False, True, False] and [c[3] for c in cs] == ["", "retired", ""], cs)
check("4 ssh, addresses and sources are the card's hover text", 'title="ssh: user@alpha-box; addresses: 192.0.2.10, 2001:db8::10; sources: fleet.json"' in fl, fl[:600])
check("4 the age line reads 'updated' and the age, no stale mark", '<p class="mnote fl-age">machine list updated just now</p>' in fl, fl[:200])
check("4 not stale: no stale class", "fl-stale" not in fl and "no newer list" not in fl)
check("4 the names not read, 20 of 25 and how many more", "not read: " + ", ".join(nr[:20]) + " and 5 more" in fl and nr[20] not in fl, fl[-300:])
check("4 the package cards are untouched: the block minus the fleet list is the unpaired block", h.replace(fl, "") == baseline_block, None)
v = MP.view(time.time())
check("4 the view: a list, fresh, 3 machines, roles only the known ones", v["list"] is True and v["stale"] is False and len(v["machines"]) == 3 and v["machines"][0]["roles"] == ["sala-host", "stackshot-host"], v)
check("4 the page holds the block inside the Machines section", "alpha-box" in page().split('<section id="machines">')[1].split("</section>")[0])
store([mach("only-box")], 30.0)
check("4 no note on names not read when none are", "fl-nr" not in block() and "not read:" not in block())

# ================================================================ 5. a stale list
for ago_s, stale, word in ((899, False, "14m ago"), (901, True, "15m ago"), (20 * 60, True, "20m ago"), (3 * 3600, True, "3h ago"), (5 * 86400, True, "5d ago")):
    store([mach("old-box")], float(ago_s)); fl = fleet_part(block())
    check(f"5 a list received {ago_s} s ago is {'stale' if stale else 'fresh'} and says {word}", ("fl-stale" in fl) is stale and f"updated {word}" in fl and "old-box" in fl and ("no newer list has arrived lately" in fl) is stale, fl[:300])

# ================================================================ 6. escaping
EVIL = ['<script>alert(1)</script>', '"><img src=x onerror=alert(1)>', "a&b &amp; &lt;", "it's \"quoted\"", "javascript:alert(1)", "' onmouseover='alert(1)", "</div><p>x"]
def hostile(txt, i): return mach(f"n{i} {txt}", hostname=f"h{i}-{txt}", letter=txt[:6], ssh=txt, addresses=[txt, "192.0.2.1"], sources=[txt])
base_page = page(); base_scripts, base_imgs = base_page.count("<script"), base_page.count("<img")
store([hostile(t, i) for i, t in enumerate(EVIL)], 30.0, not_read=EVIL)
h = block(); fl = fleet_part(h); pg = page()
tg = Tags(); tg.feed(fl)
check("6 the fleet list holds only div, b, span and p tags", set(tg.tags) <= {"div", "b", "span", "p"}, sorted(set(tg.tags)))
check("6 …with class and title attributes only (no href, src or event attribute)", tg.attrs <= {"class", "title"}, sorted(tg.attrs))
check("6 no link is built from a stored text", "<a " not in fl and "href=" not in fl and "<img" not in fl)
check("6 a script or image tag in a text is shown as text", "<script" not in fl and "<img" not in fl and "&lt;script&gt;alert(1)&lt;/script&gt;" in fl and "&lt;img src=x onerror=alert(1)&gt;" in fl, fl[:500])
check("6 an ampersand is escaped, and one already written as an entity is shown as written", "a&amp;b &amp;amp; &amp;lt;" in fl)
check("6 a quote cannot close an attribute: in the title and in the text", '&quot;' in fl and "&#x27;" in fl and "onmouseover='" not in fl and '"quoted"' not in fl, fl[:500])
check("6 javascript: is only text", "javascript:alert(1)" in fl and "javascript:alert(1)" not in re.sub(r'(title="[^"]*"|>[^<]*<)', "", fl))
check("6 the same in not_read", "&lt;script&gt;alert(1)&lt;/script&gt;" in fl.split('fl-nr')[1] and "<script" not in fl.split('fl-nr')[1])
check("6 the whole page holds no script or image tag more than the page without the hostile list", pg.count("<script") == base_scripts and pg.count("<img") == base_imgs, (pg.count("<script"), base_scripts, pg.count("<img"), base_imgs))
check("6 the hostile name is on the page, as text", "&lt;script&gt;alert(1)&lt;/script&gt;" in pg)

# ================================================================ 7. a hand-edited file
store([{"name": 7, "hostname": ["x"], "letter": {"a": 1}, "ssh": 5, "addresses": "192.0.2.1", "roles": "sala-host", "retired": "yes", "sources": [1, None, "ok.json"]},
       {"name": "fine-box", "roles": ["nonsense", "sala-host"], "retired": True}], 30.0, post=False)
try: h = block(); err = None
except Exception as e: h, err = "", e
cs = cards(fleet_part(h))
check("7 fields of the wrong kind draw without an error", err is None and len(cs) == 2, err)
check("7 a field that is no text is left out; `retired` is true only when it is true; an unknown role is left out", cs and cs[0][2] == "" and not cs[0][0] and cs[1][2] == "fine-box" and cs[1][0] and cs[1][4] == "sala-host", cs)
check("7 the one text in a list of mixed kinds is kept", 'sources: ok.json' in fleet_part(h))
store(["not an object"], 30.0, post=False)
check("7 a machine that is no object reads the whole file as none", 'no machine list received yet' in block())
LISTFILE.write_text(json.dumps({"schema": 1, "written": 1.0, "received": 1.0, "posted_by": "x", "machines": [], "not_read": "abc"}))
check("7 `not_read` that is no list reads the whole file as none (the stored reader's rule)", 'no machine list received yet' in block())

# ================================================================ 8. 200 machines
store([mach(f"box-{i:03d}", hostname=f"host-{i:03d}.example.net") for i in range(200)], 30.0)
pg = page()
check("8 200 machines draw as 200 cards and the page renders", len(re.findall(r'<div class="pc fl[ "]', pg)) == 200 and "</html>" in pg and "box-199" in pg, len(re.findall(r'<div class="pc fl[ "]', pg)))

# ================================================================ 9. view() never raises
real = SVC.last_machines
def boom(): raise OSError("no")
SVC.last_machines = boom
try: r = MP.view(time.time())
finally: SVC.last_machines = real
check("9 a store that cannot be read is no view and no error", r is None, r)
real_paired = KEYS.paired
KEYS.paired = boom
try: r = MP.view(time.time())
finally: KEYS.paired = real_paired
check("9 a pairing check that fails is no view and no error", r is None, r)
src = pathlib.Path(STACK, "stackshot", "service", "machines_panel.py").read_text(encoding="utf-8")
check("9 the module imports no process, socket or network module", not re.search(r"^\s*(?:import|from)\s+(?:subprocess|socket|urllib|http|requests|paramiko)\b", src, re.M))

# ================================================================ 10. revoked: the list goes at once
store([mach("again-box")], 30.0)
check("10 paired: the list is drawn", "again-box" in block())
unpair(fp)
check("10 the key revoked and the token gone: the board is as before any pairing", block() == baseline_block and "again-box" not in page())

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
