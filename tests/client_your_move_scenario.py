"""Scenario test for `your-move` of the client API: the owner's whole Your move group, which a page that lists it all needs (the brief stops at five lines of it, and `items?key=` is one session's items) — fixture data, no live store, no network.

Covers: the read lists every item of the group, more than five, whichever way the owner is its mover (a decision with its ask, a stored mover, an item no session moves or is named on, an item a session created) and nothing of
the other two lists (an item an agent moves, one that waits on a date or on another item, a held one, a closed one, one in the retired on-hold status); the answer is the home page's own group: the same items in the same order as the
ui renderer's Your move list, and its first five are the brief's five lines; the order is the page's (the longest-his first, items of one age by due date), not newest first; each row's fields (`shown`, `subject`, `url`, `ask`
empty without an open ask, `updated` in epoch seconds with the file's time for an item that stores none, `scope`), a url without the instance's board address; a decision that leaves the group and an item that joins it show at once;
each row's `scope` is the subsection the home page draws that item in, for every way a page gets its scope (its board row's, a sub-page and a hub page included; the key prefix, org, name prefix, tag, record entry and the mark set on
purpose; no project, a bare slug and an unlisted page), on an instance with no [project_scopes] and with a damaged id file, `[scopes]` not read, the id file read once for a read;
an empty group is {"items": [], "group": {...}}; with the queue rule on (which asks for the session roles about each item an agent moves) the roles are built once for a read, and the answer is byte for byte the one without that memo; the group's name (`group`: {"en", "ko"}) is the string table's own Your move heading, as the home page draws it, with no second-language catalog (the English text for both), with an ASCII test locale, with a catalog that lacks the key or refuses its value; over HTTP: no token, a wrong token, the token in the query string, a Basic credential and a live caller's pass are 401, the machine's token is the read's own answer, no-store, answered in a
worker thread, a read-only standby serves it and a write to it is refused; the 404 list and `client.py` name the read.

    tests/run-suite client_your_move        → exit 0 / 1"""
import contextlib, io, json, os, re, sys, pathlib, logging, time, threading
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="clientyourmove-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml, n = re.subn(r'(?m)^session_links = ""', f'session_links = "{tmp}/links"', toml); assert n == 1
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root"]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "links/a", "brain/projects"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
SESS = {"alpha-main": "00000000-0000-4000-8000-000000000001", "alpha-builder": "00000000-0000-4000-8000-000000000002"}
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in SESS.items()}))
(T / "links/a/session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-11-20T00:00:00Z", "sessions": {u: {
    "id": u, "name": n, "aliases": [], "project": "", "state": "live", "created": "2026-11-01T00:00:00Z",
    "transcripts": [{"id": u, "machine": "a", "at": "2026-11-01T00:00:00Z", "why": "start"}]} for n, u in SESS.items()}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "alpha-main", "status": "active", "board": [], "board_open": 0,
    "agents": {"alpha-main": "the main", "alpha-builder": "the builder"}, "back_agents": {"alpha-builder": "the builder"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: alpha-main\nagents:\n  alpha-main: the main\n  background:\n    alpha-builder: the builder\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
now0 = time.time(); DAY = 86400.0
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)

from stackshot.core import config as _cfg
from stackshot.core import instance as _inst
from stackshot.core import passmemo as _passmemo
from stackshot.core import readonly as _ro
from stackshot.core import store as _store
from stackshot.fleet import client
from stackshot.github import ghsync as _gh
from stackshot.projects import projects as _prj
from stackshot.service import caller_pass as _cp
from stackshot.service import client_reads as cr
from stackshot.web import render as _rmod
from stackshot.web import server
from stackshot.web.routes import client_api as _rt_client
from stackshot.web.ui import kit as _kit
from stackshot.web.ui import render as _ui

OWNER = _inst.OWNER
ASK = "Decide: take the cheaper plan? · Recommend: yes · Stakes: low · By: Mon"
def put(i, status="open", subject=None, age=3.0, state_age=None, updated=True, **meta):
    rec = {"id": str(i), "subject": subject or f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": status,
           "state_updated": now0 - (age if state_age is None else state_age) * DAY, "confirmed": now0 - age * DAY,
           "metadata": {"project": meta.pop("project", "projects/alpha"), **meta}}
    if updated: rec["updated"] = now0 - age * DAY
    (T / f"store/a/{i}.json").write_text(json.dumps(rec, ensure_ascii=False))
def drop(i): (T / f"store/a/{i}.json").unlink()
def D(n): return time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY))

# the owner's move, nine items (more than the brief's five), each his in another way; the age is how long the item has been his
put(1, subject="[home] a decision with its ask", age=9, needs=["decision"], ask=ASK, then="alpha-builder", owner="alpha-main", options=[{"label": "Approve", "line": "Take it.", "recommended": True}, {"label": "Decline", "line": "Leave it.", "recommended": False}])
put(2, subject="[home] stored mover, no session at all", age=8, mover=OWNER)                                  # nothing names a session: no `items?key=` lists it for anyone
put(3, subject="[home] a decision with no ask line", age=7, needs=["decision"], then="alpha-main")
put(4, subject="[home] stored mover, a session created it", age=6, mover=OWNER, owner="alpha-main", owner_name="alpha-main")
put(5, subject="[home] stored mover, one more", age=5, mover=OWNER)
put(6, subject="[home] stored mover, the same age and a due date", age=4, mover=OWNER, due=D(5))
put(7, subject="[home] stored mover, the same age, undated", age=4, mover=OWNER)
put(8, subject="[home] stored mover, a file that stores no update time", mover=OWNER, updated=False, state_age=1.5)
put(9, subject="[home] the newest of his", age=0.5, mover=OWNER)
put(10, subject="[home] a step of his with a stale ask", age=2, mover=OWNER, ask=ASK)                         # an ask that is no open question (no decision in its needs): the row carries none
# not his
put(20, subject="[home] a session moves it", age=3, mover="alpha-builder")
put(21, subject="[home] waits on a date", age=3, wait_kind="time", wake=D(6), mover="alpha-builder")
put(22, subject="[home] waits on an open item", age=3, mover=OWNER, after=["a9"])
put(23, subject="[home] held", age=3, hold=True, mover="alpha-builder")
put(24, subject="[home] closed", status="completed", age=2, mover=OWNER, outcome="done")
put(25, subject="[home] the retired status", status="on_hold", age=2, mover="alpha-builder")
put(26, subject="[home] a decision a session is named in", age=2, needs=["alpha-builder"], mover="alpha-builder")

def body(): st, ct, b = cr._client_get("your-move", {}); assert st == 200 and ct == "application/json", (st, ct, b[:200]); return json.loads(b)
shown = lambda n: _gh.shown(f"a{n}")
ui_group = lambda: [_gh.shown(r["gid"]) for r, _m in _ui.Board(str(_store.STORE)).home_lists()["your-move"]]
rows = lambda: {x["shown"]: x for x in body()["items"]}

# the group's name: the string table's own words, read through the page's lookup. The repository holds no second-language text, so the second language here is an ASCII test locale in a temporary folder
# (the English text in a marker), written and removed by this suite; with none configured the table's fallback is the English text.
from stackshot.web import i18n as _i18n
LOC = T / "locales"; LOC.mkdir()
MARK = lambda v: f"[x:{v}]"
NAMES_EN = {"en": _i18n.EN["state.you"], "ko": _i18n.EN["state.you"]}
def set_dir(v):
    if v is None: _cfg.CFG.get("ui", {}).pop("locale_dir", None)
    else: _cfg.CFG.setdefault("ui", {})["locale_dir"] = str(v)
def write_ko(d): (LOC / "ko.json").write_text(json.dumps(d), encoding="utf-8")
def drop_ko(): (LOC / "ko.json").unlink(missing_ok=True)
def settle(): _i18n._LOADED.clear(); _i18n._WARNED.clear()
def home_heading(lang):
    """The words the home page draws over its Your move list, in `lang`."""
    with _i18n.use(lang): page = _ui.Board(str(_store.STORE)).html()
    return re.search(r'<section id="your-move">.*?<h2>(.*?) <span class="count">', page, re.S).group(1)

j = body(); got = [x["shown"] for x in j["items"]]
mine = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
check("the answer is {items: [...], group: {...}}, nothing else", set(j) == {"items", "group"} and isinstance(j["items"], list) and isinstance(j["group"], dict), j.keys())
set_dir(None); settle()
check("group, no second-language catalog: both languages are named, in the table's order, and the second is the table's fallback, the English text (present, never absent)",
      _i18n.available() == ["en"] and list(j["group"]) == list(_i18n.LANGS) == ["en", "ko"] and j["group"] == NAMES_EN and j["group"]["en"] == "Your move", (_i18n.available(), j["group"]))
check("group, the English name is the catalog's state.you and the heading the home page draws, word for word", j["group"]["en"] == _i18n.EN["state.you"] == _kit.title(_kit.YOUR_MOVE, "en") == home_heading("en"), (j["group"], home_heading("en")))
set_dir(LOC); settle(); write_ko({"state.you": MARK(_i18n.EN["state.you"]), "state.agent": MARK(_i18n.EN["state.agent"])})
with contextlib.redirect_stderr(io.StringIO()): jk = body()
check("group, a second language configured: the name in each language, the English one unchanged, the second the catalog's own word",
      _i18n.available() == ["en", "ko"] and jk["group"] == {"en": "Your move", "ko": MARK("Your move")}, (_i18n.available(), jk["group"]))
with contextlib.redirect_stderr(io.StringIO()): hk, he = home_heading("ko"), home_heading("en")
check("group, each name is what the home page draws over the list in that language", (jk["group"]["ko"], jk["group"]["en"]) == (hk, he), (jk["group"], hk, he))
check("group, a second language configured changes nothing else: every other key, each row and the order are as without it", set(jk) == {"items", "group"} and jk["items"] == j["items"] and [list(x) for x in jk["items"]] == [list(x) for x in j["items"]], (jk.keys(),))
check("group, the rows are exactly what the renderer's your_move gives and nothing was added to a row", j["items"] == json.loads(json.dumps(_rmod.your_move(str(_store.STORE)))) and all(list(x) == ["shown", "subject", "url", "ask", "updated", "scope"] for x in j["items"]), (j["items"][:1],))
write_ko({"state.agent": MARK(_i18n.EN["state.agent"])})                                                 # a catalog that lacks the key: the table's fallback for that key, English
settle()
with contextlib.redirect_stderr(io.StringIO()): jm = body()
check("group, a second-language catalog without the key gives the English text for it", _i18n.available() == ["en", "ko"] and jm["group"] == NAMES_EN, (jm["group"],))
write_ko({"state.you": "{nothing}"})                                                                       # a value naming a field the English text lacks is refused: English again
settle()
with contextlib.redirect_stderr(io.StringIO()): jr = body()
check("group, a catalog value the table refuses gives the English text for it", jr["group"] == NAMES_EN, (jr["group"],))
drop_ko(); set_dir(None); settle()
check("group, the catalog gone again: back to the fallback", body()["group"] == NAMES_EN, body()["group"])
check("every item of the group is in it, more than five, and nothing of the other lists", len(got) == 10 and set(got) == {shown(n) for n in mine}, got)
check("an item no session moves or is named on, and one a session only created, are in it", shown(2) in got and shown(5) in got and shown(4) in got
      and not any(cr._client_get("items", {"key": k})[2].count(f'"shown": "{shown(2)}"') for k in ("alpha-main", "alpha-builder", SESS["alpha-main"])), got)
check("an agent's item, a wait on a date, a wait on an item, a held item, a closed item and the retired status are not in it", not ({shown(n) for n in (20, 21, 22, 23, 24, 25, 26)} & set(got)), got)
check("the group is the ui renderer's Your move list: the same items in the same order", got == ui_group(), (got, ui_group()))
brief_lines = [l for l in _rmod.render(str(_store.STORE), "brief").splitlines() if l.startswith("  your move: ")]
check("the brief's five lines are the head of the same list", len(brief_lines) == 5 and [l.split()[2] for l in brief_lines] == got[:5] and all(l.startswith(f"  your move: {s} ") for l, s in zip(brief_lines, got)), (brief_lines, got[:5]))
check("the order is the page's, the longest his first, items of one age by due date then id: not newest first", got == [shown(n) for n in (1, 2, 3, 4, 5, 6, 7, 10, 8, 9)], got)
check("…and the two of one age: the dated one before the undated one", got.index(shown(6)) < got.index(shown(7)), got)
check("…so the newest is last", got[-1] == shown(9) and got[0] == shown(1), got)

r = rows()
check("a row has exactly the six fields", all(set(x) == {"shown", "subject", "url", "ask", "updated", "scope"} for x in r.values()), [set(x) for x in r.values()][:2])
check("shown is the id as a person reads it, subject the item's", r[shown(1)]["subject"] == "[home] a decision with its ask" and all(x["shown"] == s for s, x in r.items()), r[shown(1)])
check("ask is the open ask line of a decision, and empty for an item with none or with an ask that is no open question", r[shown(1)]["ask"] == ASK and r[shown(3)]["ask"] == "" and r[shown(2)]["ask"] == "" and r[shown(10)]["ask"] == "", [(k, x["ask"]) for k, x in r.items()])
check("updated is the item's last write in epoch seconds", isinstance(r[shown(1)]["updated"], float) and abs(r[shown(1)]["updated"] - (now0 - 9 * DAY)) < 1, r[shown(1)]["updated"])
check("…and for an old file that stores none, the file's time", isinstance(r[shown(8)]["updated"], float) and abs(r[shown(8)]["updated"] - now0) < 120, r[shown(8)]["updated"])
_was = _inst.BOARD_URL
try:
    _inst.BOARD_URL = "https://board.example.test/"
    check("url is the item's page under the board address", all(rows()[shown(n)]["url"] == f"https://board.example.test/items/{_gh.href_id(f'a{n}')}" for n in mine), [x["url"] for x in rows().values()][:3])
    _inst.BOARD_URL = ""
    check("…and the path alone while the instance has no board address", all(rows()[shown(n)]["url"] == f"/items/{_gh.href_id(f'a{n}')}" for n in mine), [x["url"] for x in rows().values()][:3])
finally: _inst.BOARD_URL = _was

# the group follows the board at each read
put(5, subject="[home] stored mover, one more", age=5, mover="alpha-builder")                                  # handed to a session
put(30, subject="[home] a new decision", age=0.2, needs=["decision"], ask=ASK)
got2 = [x["shown"] for x in body()["items"]]
check("an item handed to a session leaves the group and a new decision joins it, at the next read", shown(5) not in got2 and got2[-1] == shown(30) and len(got2) == 10 and got2 == ui_group(), got2)
for n in (30,): drop(n)
put(5, subject="[home] stored mover, one more", age=5, mover=OWNER)
many = 40
for n in range(100, 100 + many): put(n, subject=f"[home] bulk {n}", age=10 + n / 100, mover=OWNER)
got3 = [x["shown"] for x in body()["items"]]
check("no cap: fifty items are fifty rows, in the page's order", len(got3) == 10 + many and got3 == ui_group(), (len(got3), len(ui_group())))
for n in range(100, 100 + many): drop(n)

# empty
gone = sorted(mine | {22})                                                                                       # item 22 waits on item 9: with 9 closed it is his
saved = {n: (T / f"store/a/{n}.json").read_text() for n in gone}
for n in gone: drop(n)
st, ct, b = cr._client_get("your-move", {})
check("an empty group is 200 {items: [], group: {...}}: the group's name is there with no item", st == 200 and json.loads(b) == {"items": [], "group": NAMES_EN} and ui_group() == [], (st, b))
for n, t in saved.items(): (T / f"store/a/{n}.json").write_text(t)

# each row's `scope`: the name on the subsection the home page draws that item in. The instance lists the scopes work, home (the default) and ops, and maps the key prefix "ops/" and the tags ops and work.
def drawn():
    """{item: scope} as the home page's HTML draws its Your move list: the subsection each item's link sits in."""
    sec = _ui.Board(str(_store.STORE)).html().split('<section id="your-move">', 1)[1].split('<section id=', 1)[0]
    parts = re.split(r'data-fold="home\.your-move\.([^"]+)"', sec)
    return {s: sc for sc, chunk in zip(parts[1::2], parts[2::2]) for s in (shown(n) for n in (*mine, *CASES, 250)) if f'href="/items/{_gh.href_id(s)}"' in chunk}
def answered(): return {x["shown"]: x["scope"] for x in body()["items"]}
def page(**e): return {"title": "P", "name": "P", "org": "home", "tags": [], "type": "project", "status": "active", "board": [], **e}
reg0 = (T / "store/projects.json").read_text()
reg = json.loads(reg0)
reg["pages"].update({"projects/w": page(org="work"), "projects/w/sub": page(), "projects/w/own": page(board_row=True, org="", tags=["ops"]), "ops/box": page(org="work"), "ops/hubbed": page(hub="projects/w"),
                     "projects/named": page(session="ops-keeper", role="name"), "projects/tagged": page(org="", tags=["ops"]), "projects/recorded": page(org="work", scope="ops"), "projects/marked": page(org="work")})
CASES = {200: ("projects/w", "work", "a page's org"), 201: ("projects/w/sub", "work", "a sub-page with no row of its own follows the row above it, not its own org"),
         202: ("projects/w/own", "ops", "a sub-page that is a row keeps its own: its tag"), 203: ("ops/box", "ops", "the key prefix beats the page's org"),
         204: ("ops/hubbed", "work", "a hub: page follows its hub's row, not its own key prefix"), 205: ("projects/named", "ops", "the prefix of the page's name line"),
         206: ("projects/tagged", "ops", "a tag"), 207: ("projects/recorded", "ops", "the scope the record's entry names"), 208: ("projects/marked", "home", "the mark set on purpose beats the page's org"),
         209: ("", "home", "no project: the default scope"), 210: ("projects/ghost", "home", "a page the registry does not list: the default scope"),
         211: ("ops/ghost", "ops", "an unlisted page, by its key prefix"), 212: ("w", "work", "a bare slug is read as its page")}
(T / "store/projects.json").write_text(json.dumps(reg))
pid = _prj.ensure_ids(["projects/marked"])["projects/marked"]
_prj.set_mark(pid, scope="home")
for n, (key, _sc, _why) in CASES.items(): put(n, subject=f"[home] scope case {n}", age=3, mover=OWNER, project=key)
try:
    got_sc, page_sc = answered(), drawn()
    for n, (key, sc, why) in CASES.items():
        check(f"scope, {why} ({key or 'no project'}): {sc}", got_sc.get(shown(n)) == sc, got_sc.get(shown(n)))
    check("scope, the items of a project with a plain org", {got_sc[shown(n)] for n in mine} == {"home"}, got_sc)
    check("scope, every row's is the subsection the home page draws that item in", got_sc == page_sc and len(page_sc) == len(mine) + len(CASES) and set(page_sc.values()) == {"work", "home", "ops"}, (got_sc, page_sc))
    check("scope, the list's own name stays in the top-level group, unchanged by it", body()["group"] == NAMES_EN, body()["group"])
    # the same group on the other reads that list items: a copy of each case moved by a session and observed by another, read through items, involved and item-facts
    for n, (key, _sc, _why) in CASES.items(): put(n + 100, subject=f"[home] scope copy {n}", age=3, mover="alpha-builder", observers=["alpha-main"], project=key)
    try:
        def by_shown(rows_): return {x["shown"]: x["scope"] for x in rows_}
        it_sc = by_shown(json.loads(cr._client_get("items", {"key": "alpha-builder"})[2])["items"])
        inv_sc = by_shown(json.loads(cr._client_get("involved", {"key": "alpha-main"})[2])["items"])
        fa = json.loads(cr._client_get("item-facts", {"key": "alpha-builder", "ids": ",".join(f"a{n + 100}" for n in CASES)})[2])["items"]
        fa_sc = {x["shown"]: x["scope"] for x in fa.values()}
        for name, got_ in (("items", it_sc), ("involved", inv_sc), ("item-facts", fa_sc)):
            for n, (key, sc, why) in CASES.items():
                check(f"scope on {name}, {why} ({key or 'no project'}): {sc}", got_.get(shown(n + 100)) == sc, got_.get(shown(n + 100)))
            check(f"scope on {name}, each case is the group its twin is listed in under Your move", all(got_.get(shown(n + 100)) == got_sc[shown(n)] for n in CASES), got_)
    finally:
        for n in CASES: drop(n + 100)
    was = _cfg.CFG.get("scopes")
    try:
        _cfg.CFG["scopes"] = {"order": ["desk"], "default": "desk", "by_org": {"work": "desk"}, "by_prefix": {"ops/": "desk"}}
        board_md = _rmod.Board(str(_store.STORE))
        check("scope, [scopes] (board.md's own grouping) is not read", answered() == got_sc and {board_md.proj_scope(k) for k in reg["pages"]} == {"desk"}, answered())
    finally: _cfg.CFG["scopes"] = was
    # the id file is read once for a read, not once per item
    reads = []; real_ids = _prj.ids_by_key; real_marks = _prj.marks
    def spy_of(name, real):
        def spy():
            if sys._getframe(1).f_code.co_name in ("scope_ids", "scope_of"): reads.append(name)
            return real()
        return spy
    _prj.ids_by_key, _prj.marks = spy_of("ids", real_ids), spy_of("marks", real_marks)
    try: _rmod.your_move(str(_store.STORE))
    finally: _prj.ids_by_key, _prj.marks = real_ids, real_marks
    check("scope, the id file is read once for a read of the whole group", sorted(reads) == ["ids", "marks"], reads)
    ids_file = pathlib.Path(_prj.record_path()); kept = ids_file.read_text()
    # an agent only the project record holds (made through the form, its page line still owed) moves the page's scope by its name prefix, on the home page, your-move and the other reads alike
    reg_p = json.loads((T / "store/projects.json").read_text()); reg_p["pages"]["projects/pend"] = page(org=""); (T / "store/projects.json").write_text(json.dumps(reg_p))
    try:
        pend_id = _prj.ensure_ids(["projects/pend"])["projects/pend"]
        _prj.add_pending(pend_id, "work-x", {"front": True, "role": "x", "mandate_line": "a thing"})
        put(250, subject="[home] pending case", age=3, mover=OWNER, project="projects/pend"); put(350, subject="[home] pending copy", age=3, mover="alpha-builder", observers=["alpha-main"], project="projects/pend")
        cr._VIEW["v"] = None
        yp = answered()[shown(250)]
        ip = by_shown(json.loads(cr._client_get("items", {"key": "alpha-builder"})[2])["items"])[shown(350)]
        vp = by_shown(json.loads(cr._client_get("involved", {"key": "alpha-main"})[2])["items"])[shown(350)]
        fp = json.loads(cr._client_get("item-facts", {"key": "alpha-builder", "ids": "a350"})[2])["items"]["a350"]["scope"]
        check("scope, a page that only a pending agent places (work-x): your-move says work", yp == "work", yp)
        check("scope, …and items, involved and item-facts say the same as your-move", ip == vp == fp == yp, (yp, ip, vp, fp))
        check("scope, …and the home page draws it in the same subsection", drawn().get(shown(250)) == yp, drawn().get(shown(250)))
    finally:
        for n in (250, 350): drop(n)
        ids_file.write_text(kept); (T / "store/projects.json").write_text(json.dumps(reg))
    # the registry, the id file and the marks are read once per read of items, involved and item-facts, not once per row
    spy = {"ids": 0, "marks": 0, "pending": 0}; real_i, real_m, real_p = _prj.ids_by_key, _prj.marks, _prj.with_pending
    def s_ids(*a, **k): spy["ids"] += 1; return real_i(*a, **k)
    def s_marks(*a, **k): spy["marks"] += 1; return real_m(*a, **k)
    def s_pend(*a, **k): spy["pending"] += 1; return real_p(*a, **k)
    for n, (key, _sc, _why) in CASES.items(): put(n + 100, subject=f"[home] scope copy {n}", age=3, mover="alpha-builder", observers=["alpha-main"], project=key)
    _prj.ids_by_key, _prj.marks, _prj.with_pending = s_ids, s_marks, s_pend
    try:
        def read_items():
            cr._VIEW["v"] = None
            return cr._client_get("items", {"key": "alpha-builder"})
        for what, call in (("items", read_items), ("involved", lambda: cr._client_get("involved", {"key": "alpha-main"})),
                           ("item-facts", lambda: cr._client_get("item-facts", {"key": "alpha-builder", "ids": ",".join(f"a{n + 100}" for n in CASES)}))):
            for k_ in spy: spy[k_] = 0
            st_, _ct, b_ = call()
            check(f"scope, {what}: the id file, the marks and the pending agents are read once for the whole read", st_ == 200 and len(json.loads(b_)["items"]) >= len(CASES) and spy == {"ids": 1, "marks": 1, "pending": 1}, spy)
    finally:
        _prj.ids_by_key, _prj.marks, _prj.with_pending = real_i, real_m, real_p
        for n in CASES: drop(n + 100)
    try:
        ids_file.write_text("{ torn")
        bad_sc, bad_page = answered(), drawn()
        check("scope, a damaged id file: the read still answers, the marked page by its own lines, as the home page draws it", bad_sc == {**got_sc, shown(208): "work"} and bad_sc == bad_page, (bad_sc, bad_page))
    finally: ids_file.write_text(kept)
    was = _cfg.CFG.pop("project_scopes")
    try:
        one_sc, one_page = answered(), drawn()
        check("scope, an instance with no [project_scopes]: every row is in the one default scope, general, as the home page draws it", set(one_sc.values()) == {"general"} and one_sc == one_page, (one_sc, one_page))
    finally: _cfg.CFG["project_scopes"] = was
finally:
    for n in CASES: drop(n)
    (T / "store/projects.json").write_text(reg0)

# the session roles are worked out once for a read: with the queue rule on, the group asks who is a front agent about each item an agent moves
def roles_builds(call):
    """How many times the session roles were built while `call` ran (anchors.session_roles reads the projects waiting for their page once per build)."""
    count = [0]; real = _prj.with_pending
    def counted(*a, **k):
        if sys._getframe(1).f_code.co_name == "session_roles": count[0] += 1
        return real(*a, **k)
    _prj.with_pending = counted
    try: call()
    finally: _prj.with_pending = real
    return count[0]
extra = (40, 41, 42)
for n in extra: put(n, subject=f"[home] one more a session moves, {n}", age=2, mover="alpha-builder")
try:
    _cfg.CFG.setdefault("model", {})["queued_behind"] = True
    outside = roles_builds(cr._client_your_move)
    check("roles: the fixture is live: with the queue rule on, the group outside a pass memo asks for the session roles for each item an agent moves", outside >= len(extra) and not _passmemo.active(), outside)
    once = roles_builds(body)
    check("roles: the session roles are built once for a read", once == 1, once)
    twice = roles_builds(lambda: (body(), body()))
    check("roles: …and once more for the next read: the memo ends with its request", twice == 2 and not _passmemo.active(), twice)
    with_memo, without = cr._client_get("your-move", {}), cr._client_your_move()
    check("roles: …and the answer is byte for byte the answer without the memo", with_memo == without and with_memo[0] == 200 and len(json.loads(with_memo[2])["items"]) == len(mine), (with_memo[2][:200], without[2][:200]))
finally:
    _cfg.CFG.get("model", {}).pop("queued_behind", None)
    for n in extra: drop(n)

# the surface
tok = open(client.mint("box-far")).read().strip(); H = {"Authorization": "Bearer " + tok}
from starlette.testclient import TestClient
seen_threads = []; _real = _rt_client._client_get
def spy(what, params):
    seen_threads.append((what, threading.current_thread().name)); return _real(what, params)
_rt_client._client_get = spy
app = server.mcp.http_app()
try:
    with TestClient(app) as c:
        r0 = c.get("/client/your-move")
        r1 = c.get("/client/your-move", headers={"Authorization": "Bearer " + "x" * 43})
        r2 = c.get("/client/your-move", params={"token": tok})
        r3 = c.get("/client/your-move", headers={"Authorization": "Basic " + tok})
        r4 = c.get("/client/your-move", headers={"Authorization": tok})
        ok = c.get("/client/your-move", headers=H)
        wh = c.get("/client/whoami", headers=H)
        # a live pass of an approved key: it opens the New session form's calls and nothing else of /client
        PASS = _cp.PASS_PREFIX + "p" * 43
        import hashlib
        _cp._PASSES[hashlib.sha256(PASS.encode()).hexdigest()] = {"fp": "f" * 64, "sender": "alpha", "exp": time.time() + 600}
        _lookup = _cp._keys.lookup_approved; _cp._keys.lookup_approved = lambda fp: {"sender": "alpha"}
        try:
            live = _cp.pass_machine("Bearer " + PASS)
            rp = c.get("/client/your-move", headers={"Authorization": "Bearer " + PASS})
        finally: _cp._keys.lookup_approved = _lookup; _cp._PASSES.clear()
        # the 404 list
        nf = c.get("/client/nothing-here", headers=H)
        # a read-only standby serves it, and refuses a write
        _ro._reload_for_test(True)
        try:
            sb = c.get("/client/your-move", headers=H)
            wr = c.post("/client/for-you/seen", json={"id": "all", "sender": "x"}, headers=H)
        finally: _ro._reload_for_test(False)
finally: _rt_client._client_get = _real
check("http: no token → 401, a wrong token → 401, the token in the query string → 401, a Basic credential → 401, a bare Authorization value → 401",
      [x.status_code for x in (r0, r1, r2, r3, r4)] == [401] * 5 and not any("subject" in x.text for x in (r0, r1, r2, r3, r4)), [x.status_code for x in (r0, r1, r2, r3, r4)])
check("http: a live pass of an approved key is 401 (it opens the form's calls only)", live.startswith(_cp.MACHINE_PREFIX) and rp.status_code == 401 and "subject" not in rp.text, (live, rp.status_code, rp.text[:100]))
check("http: the machine's token gets the read's own answer, no-store, JSON", ok.status_code == 200 and ok.json() == body() and ok.json()["group"] == NAMES_EN and ok.headers["cache-control"] == "no-store" and ok.headers["content-type"].startswith("application/json"), (ok.status_code, ok.text[:150]))
check("http: it is answered in a worker thread, not on the event loop (it renders the board)", [w for w, t in seen_threads if w == "your-move"] and all("worker" in t.lower() or "anyio" in t.lower() for w, t in seen_threads if w == "your-move") and wh.status_code == 200, seen_threads)
check("http: the 404 list of reads names it", nf.status_code == 404 and "your-move" in nf.text, nf.text[:200])
check("a read-only standby copy serves it, as it serves the other reads, and a write is still refused", sb.status_code == 200 and sb.json() == body() and wr.status_code == 503 and "read-only standby" in wr.text, (sb.status_code, wr.status_code, wr.text[:120]))
usage = open(client.__file__, encoding="utf-8").read().split('"""', 2)[1]
check("client.py knows the read and its usage text names it and its fields", "your-move" in client.READS and "client.py get your-move" in usage and all(w in usage.split("client.py get your-move", 1)[1].split("client.py post project-agent", 1)[0] for w in ("shown", "subject", "url", "ask", "updated", "scope", "[project_scopes] order", "no cap",'"group": {"en"', "heading the home page draws over the list in each language", "no catalog on the install has the English text")), usage[:100])
_get = client.get
client.get = lambda what, key="", timeout=10.0, **k: (200, json.dumps({"items": []}) if what == "your-move" else "x")
try:
    import io, contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out): rc = client.main(["client.py", "get", "your-move"])
finally: client.get = _get
check("client.py get your-move prints the server's JSON and exits 0", rc == 0 and json.loads(out.getvalue()) =={"items": []}, (rc, out.getvalue()))

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": client your-move scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
