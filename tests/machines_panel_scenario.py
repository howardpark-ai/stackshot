"""Scenario test for the Machines panel and the machine list a fleet manager posts (service/machines_panel.py, fleet/caller_keys.py `paired()`, ui/render.py `Board.fleet_list_notes` and the panel's machines block): fixture data in a
temporary instance, the board's own renderer, no live store, no network, no server. Names and addresses are made up.

Covers:
  1  `paired()` is the one reader of "a fleet manager is paired": false with nothing, with an approved key and no token, with a token and no key, with a key still waiting for the owner, with a key file or a token file that cannot be read,
     with an approved entry that is no key, and with a token entry that holds no SHA-256; true with an approved key and a token; false again the moment the key is revoked (the files are read at each call);
  2  a board that is not paired draws nothing from the list, whatever file is on disk: its Machines block is byte for byte what it is with no list file at all, and holds nothing of the list;
  3  a paired board with no list yet says so in one line and keeps the machine cards as an unpaired board draws them; with a list file that cannot be read (absent, empty, torn, another schema, `machines` that is no list, a folder, a link)
     it does the same and never raises;
  4  a paired board with a fresh list: the list chooses the cards and their order, one card per listed machine, joined to the machine's own readings by name (or by hostname), the versions inside that card; a machine with no letter in the
     list is still joined; no retired machine has a card; a card repeats no hostname, has no letter or role line and no hover text; a listed machine nothing has read has its name and one `offline` line; a fleet machine the list does
     not name has no card; a failure of a machine with no card keeps its own alert card; a failure line stays inside its machine's card; an ssh host is joined by name; the names not read are one note under the cards (20 named, then
     how many more); no age line while the list is fresh;
  5  a stale list (older than 15 minutes, 899 s fresh and 901 s stale) is still drawn, with one amber line of its age in its own words; a very old list reads its age in days;
  6  every stored text is escaped: a `<script>`, a quote, an ampersand and a `javascript:` text in a name, a hostname and `not_read` draw as text and add no tag, no attribute and no link to the panel, in the block and in the whole page;
  7  a stored file whose fields are of the wrong kind (a hand-edited one) draws without raising; a machine with no name draws no card;
  8  200 machines (the most a post may hold) draw as 200 cards on the page, which still renders;
  9  `view()` never raises: a store that cannot be read is no view;
  10 a revoked pairing returns the board to its unpaired state at once;
  11 the sender's four optional readings (`online`, `last_seen`, `versions`, `checked`): the view gives a machine a `reported` object only when its entry has one of them (an old list is viewed as before), unknown is None and
     never "no" (`{}` is "read nothing"), a reading is fresh for 900 s counted from the list's age plus how much older `checked` is than `written` and unknown past it, a stored reading of the wrong type is unknown, `fallback`
     takes the board's own reading field by field and the sender's only where there is none and it is fresh, and the Machines block and the page are byte for byte the same whatever the readings hold.

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
for d in ("store/a", "fleet/a", "fleet/b", "fleet/c", "state/site", "secrets", "brain/projects", "home", "touch"): (T / d).mkdir(parents=True)
for L, nm, cv in (("a", "testbox", "1.0.0"), ("b", "box-b", "0.9.0"), ("c", "box-c", "1.0.0")):
    (T / f"fleet/{L}/sessions.json").write_text("{}"); (T / f"fleet/{L}/machine.json").write_text(json.dumps({"letter": L, "fleet": nm, "claude": cv}))
VERS = {"packages": [{"name": "claude code", "installed": "1.0.0", "latest": "1.0.0", "state": "latest", "machines": {"a": "1.0.0", "b": "0.9.0", "c": "1.0.0"}, "machine_state": {}}], "ssh_hosts": []}
def write_versions(ssh=()): (T / "state/site/versions.json").write_text(json.dumps({**VERS, "ssh_hosts": list(ssh)}))
write_versions()
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
NOLIST = "no machine list received yet"
def machs(h): return re.findall(r'<div class="pc mach[^"]*"[^>]*><b class="lbl mh">([^<]*)</b>', h)
def cols(h): return h.split('<div class="mcol">')[1:]
def card(h, name):
    """The column of machine `name` (one card, or the alert cards of the last column), as HTML ('' when there is none)."""
    return next((c for c in cols(h) if f'<b class="lbl mh">{name}</b>' in c), "")
def notes(h): return re.findall(r'<p class="mnote[^"]*">[^<]*</p>', h)

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
for what, mid in (("no key, no token", lambda: None), ("a token only", lambda: (SECRETS / "clients.json").write_text(json.dumps({"box-x": TOKEN_ENTRY}))),):
    mid()
    h = block()
    check(f"2 not paired ({what}) with a good list on disk: the block is the block of a board with no list", h == baseline_block, None)
    check(f"2 not paired ({what}): no text of the list", "alpha-box" not in h and "beta-box" not in h and "unread-file" not in h and "machine list" not in h)
(SECRETS / "clients.json").unlink(missing_ok=True)
check("2 a list on disk and not paired: the page holds nothing of it", "alpha-box" not in page() and "unread-file" not in page())
check("2 the view of an unpaired board is None", MP.view(time.time()) is None)

# ================================================================ 3. paired, no list or none readable
clear(); fp = pair()
NOLINE = f'<p class="mnote">{NOLIST}</p>\n'
h = block()
check("3 paired, no list yet: one line says so, and the cards are the unpaired board's", NOLINE in h and h.replace(NOLINE, "") == baseline_block and MP.view(time.time()) == {"list": None}, notes(h))
check("3 paired, no list yet: the old machine cards are there, with their versions", machs(h) == machs(baseline_block) and len(machs(h)) >= 3 and "testbox" in machs(h) and 'class="mr ' in h, machs(h))
bad = {"absent": None, "empty": "", "torn": '{"schema": 1, "written": 17', "another schema": json.dumps({"schema": 2, "written": 1.0, "received": 1.0, "posted_by": "x", "machines": [], "not_read": []}),
       "machines no list": json.dumps({"schema": 1, "written": 1.0, "received": 1.0, "posted_by": "x", "machines": "box", "not_read": []}),
       "no received": json.dumps({"schema": 1, "written": 1.0, "posted_by": "x", "machines": [], "not_read": []}), "no object": "[1, 2]"}
for what, text in bad.items():
    clear()
    if text is not None: LISTFILE.write_text(text)
    try: h = block(); err = None
    except Exception as e: h, err = "", e
    check(f"3 paired, a list file that is {what}: the none line, the old cards, no error", err is None and NOLINE in h and h.replace(NOLINE, "") == baseline_block, err)
clear(); LISTFILE.mkdir()
check("3 paired, a folder at the list's path: the none line, the old cards, no error", block().replace(NOLINE, "") == baseline_block and NOLINE in block())
clear(); LISTFILE.symlink_to(T / "elsewhere.json"); (T / "elsewhere.json").write_text("{}")
check("3 paired, a link at the list's path: the none line, the old cards, no error", block().replace(NOLINE, "") == baseline_block and NOLINE in block())
clear()

# ================================================================ 4. paired, a fresh list: the list chooses the cards
nr = [f"file-{i}.json" for i in range(25)]
store([mach("box-c"), mach("box-b", letter=None), mach("old-box", hostname="old-box.example.net", retired=True), mach("testbox", roles=["sala-host", "stackshot-host"]), mach("lone-box", hostname=None, letter=None, roles=[])], 30.0, not_read=nr)
h = block()
check("4 one card per live machine, in the list's order, the retired one has none", machs(h) == ["box-c", "box-b", "testbox", "lone-box"], machs(h))
check("4 each machine's name is on the panel once", all(h.count(f'<b class="lbl mh">{n}</b>') == 1 for n in ("box-c", "box-b", "testbox", "lone-box")) and "old-box" not in h, machs(h))
check("4 a card repeats no hostname and has no letter or role line", "example.net" not in h and "sala-host" not in h and "stackshot-host" not in h and "letter" not in h and " · " not in h and "retired" not in h, None)
check("4 a machine card has no hover text", all(a.strip() == "" for a in re.findall(r'<div class="pc mach[^"]*"([^>]*)>', h)) and len(machs(h)) == 4, None)
check("4 the versions are inside the machine's own card: a package row, the state word", 'class="mr latest"' in card(h, "testbox") and 'class="mr update"' in card(h, "box-b") and "claude code" in card(h, "box-c") and "1.0.0" in card(h, "testbox") and "0.9.0" in card(h, "box-b"), card(h, "box-b"))
check("4 a machine with no letter in the list is joined all the same", 'class="mr update"' in card(h, "box-b"))
lone = card(h, "lone-box")
check("4 a listed machine nothing has read: its name and one offline line", lone.count('class="mr ') == 1 and 'class="mr offline"' in lone and "claude code" not in lone and 'class="pc mach"' in lone, lone)
check("4 a fresh list draws no age line", "fl-age" not in h and "fl-stale" not in h and "updated" not in h and "no newer list" not in h)
check("4 the names not read, 20 of 25 and how many more, under the cards", len(notes(h)) == 1 and "not read: " + ", ".join(nr[:20]) + " and 5 more" in h and nr[20] not in h and h.index("fl-nr") > h.rindex('class="mcol"'), notes(h))
v = MP.view(time.time())
check("4 the view: a list, fresh, the machines with name, hostname and the retired flag", v["list"] is True and v["stale"] is False and len(v["machines"]) == 5 and v["machines"][2] == {"name": "old-box", "hostname": "old-box.example.net", "retired": True}, v)
check("4 the page holds the cards inside the Machines section", "box-c" in page().split('<section id="machines">')[1].split("</section>")[0])
store([mach("testbox")], 30.0)
h = block()
check("4 a fleet machine the list does not name has no card", machs(h) == ["testbox"] and "box-b" not in h and "box-c" not in h, machs(h))
check("4 no note on names not read when none are", "fl-nr" not in h and "not read:" not in h and notes(h) == [])
store([mach("BOX-B"), mach("elsewhere", hostname="box-c"), mach("other-name", hostname="box-b")], 30.0)
h = block()
check("4 a name joins whatever its case; the hostname joins when the name does not; a reading is drawn once", machs(h) == ["box-b", "box-c", "other-name"] and 'class="mr offline"' in card(h, "other-name") and 'class="mr update"' in card(h, "box-b"), machs(h))
# an ssh host (one that is no fleet machine) is joined by name, whatever the case, or by hostname; its reading is drawn once; one the list does not name has no card
def host(name, ver, ok=True): return {"name": name, "reachable": ok, "checked": "2026-11-25T00:00:00Z", "packages": {"claude code": ver}}
write_versions([host("spare-box", "7.7.7"), host("Mixed-Host", "6.6.6")])
store([mach("spare-box"), mach("testbox")], 30.0)
h = block()
check("4 an ssh host named by the list has its one card, with its own versions", machs(h) == ["spare-box", "testbox"] and "7.7.7" in card(h, "spare-box") and 'class="mr offline"' not in card(h, "spare-box") and h.count("7.7.7") == 1, card(h, "spare-box"))
check("4 …and the other host, which the list does not name, has none", "6.6.6" not in h and "Mixed-Host" not in h)
store([mach("mixed-host"), mach("testbox")], 30.0)
h = block()
check("4 an ssh host is joined whatever the case of its name", machs(h) == ["Mixed-Host", "testbox"] and "6.6.6" in card(h, "Mixed-Host") and h.count("6.6.6") == 1, machs(h))
store([mach("elsewhere", hostname="MIXED-host")], 30.0)
h = block()
check("4 an ssh host is joined by the hostname when the name finds none, whatever the case", machs(h) == ["Mixed-Host"] and "6.6.6" in h, machs(h))
store([mach("spare-box"), mach("other", hostname="spare-box"), mach("SPARE-BOX")], 30.0, post=False)      # a hand-edited file: a post refuses a name twice
h = block()
check("4 an ssh host's reading is drawn once: a second entry that names it by hostname, or by name in another case, gets no copy", machs(h) == ["spare-box", "other"] and h.count("7.7.7") == 1 and 'class="mr offline"' in card(h, "other"), machs(h))
store([mach("elsewhere", hostname="spare-box"), mach("spare-box")], 30.0)
h = block()
check("4 …in the other order: the entry that names the host has its card; the one whose hostname is that name gets the offline line, not the host's card", machs(h) == ["elsewhere", "spare-box"] and "7.7.7" in card(h, "spare-box") and 'class="mr offline"' in card(h, "elsewhere"), machs(h))
check("4 …and its version is on the panel once", h.count("7.7.7") == 1, h.count("7.7.7"))
store([mach("testbox")], 30.0)
check("4 an ssh host the list does not name has no card", machs(block()) == ["testbox"])
clear()
check("4 paired with no list: the ssh hosts' cards are there as before", "spare-box" in machs(block()) and "Mixed-Host" in machs(block()))
# an ssh host that is also a fleet machine is that machine's one card: a name, a hostname or a second entry never draws it again
write_versions([host("box-b", "8.8.8")])
check("4 (setup) the fleet machine box-b and an ssh host of that name are one card with no list", machs(block()).count("box-b") == 1, machs(block()))
for what, lst, want in (("the name, then another entry whose hostname is the same", [mach("box-b"), mach("zzz", hostname="box-b")], ["box-b", "zzz"]),
                        ("the same name twice", [mach("box-b"), mach("box-b")], ["box-b"]),
                        ("the same name in another case", [mach("box-b"), mach("BOX-B")], ["box-b"]),
                        ("the other entry first, the name second", [mach("zzz", hostname="box-b"), mach("box-b")], ["zzz", "box-b"]),
                        ("two entries whose hostname is that name, neither named so", [mach("aaa", hostname="box-b"), mach("bbb", hostname="box-b")], ["box-b", "bbb"]),
                        ("the name twice around another", [mach("box-b"), mach("testbox"), mach("box-b", hostname="box-b")], ["box-b", "testbox"])):
    store(lst, 30.0, post=False); h = block()
    check(f"4 a fleet machine with an ssh host of its name, listed as {what}: one card titled box-b", machs(h) == want and h.count('<b class="lbl mh">box-b</b>') == 1, machs(h))
# the merged card keeps the ssh host's live package rows (its own version text), in the list path too
store([mach("box-b")], 30.0, post=False); h = block()
check("4 a fleet machine merged with an ssh host of its name shows the host's versions on its one card", machs(h) == ["box-b"] and "8.8.8" in card(h, "box-b") and h.count("8.8.8") == 1, card(h, "box-b"))
# a plain ssh host (no fleet machine) read by two entries' hostname is drawn once, for the first
write_versions([host("spare-box", "7.7.7")])
store([mach("aaa", hostname="spare-box"), mach("bbb", hostname="Spare-Box")], 30.0, post=False); h = block()
check("4 two entries whose hostname is one ssh host: the first has its card, the second an offline line, its versions once", machs(h) == ["spare-box", "bbb"] and h.count("7.7.7") == 1 and 'class="mr offline"' in card(h, "bbb"), machs(h))
# the merge finds the ssh host whatever the case of its name, and draws it once
write_versions([host("Box-B", "8.8.8")])
for what, lst, want in (("the name, then an entry whose hostname is the host's name in its own case", [mach("box-b"), mach("zzz", hostname="Box-B")], ["box-b", "zzz"]),
                        ("an entry whose hostname is the host's name first", [mach("zzz", hostname="Box-B"), mach("box-b")], ["zzz", "box-b"]),
                        ("the name alone", [mach("box-b")], ["box-b"])):
    store(lst, 30.0, post=False); h = block()
    check(f"4 a fleet machine with an ssh host of its name in another case, listed as {what}: the host's versions once, no second card of it", machs(h) == want and h.count("8.8.8") == 1 and "8.8.8" in card(h, "box-b") and "Box-B" not in machs(h), machs(h))
write_versions()
# the hostname only joins when the name found nothing, and never takes a machine another entry names: every listed entry ends with exactly one card, in list order
for what, lst, want in (("a hostname that is another entry's name, that entry later", [mach("aaa", hostname="box-b"), mach("box-b")], ["aaa", "box-b"]),
                        ("…and that entry first", [mach("box-b"), mach("aaa", hostname="box-b")], ["box-b", "aaa"]),
                        ("two entries with the same hostname, no entry of that name", [mach("aaa", hostname="box-b"), mach("bbb", hostname="box-b")], ["box-b", "bbb"]),
                        ("…the other way round", [mach("bbb", hostname="box-b"), mach("aaa", hostname="box-b")], ["box-b", "aaa"])):
    store(lst, 30.0, post=False); h = block()
    check(f"4 {what}: exactly the listed cards, {want}", machs(h) == want and len(machs(h)) == len(lst), machs(h))
store([mach("aaa", hostname="box-b"), mach("box-b")], 30.0, post=False); h = block()
check("4 …the entry that names box-b has box-b's own card, the other an offline line", 'class="mr update"' in card(h, "box-b") and 'class="mr offline"' in card(h, "aaa") and 'class="mr update"' not in card(h, "aaa"), h)
store([mach("box-b"), mach("aaa", hostname="box-b")], 30.0, post=False); h = block()
check("4 …and the same in the other order", 'class="mr update"' in card(h, "box-b") and 'class="mr offline"' in card(h, "aaa"), h)
store([mach("aaa", hostname="box-b"), mach("bbb", hostname="box-b")], 30.0, post=False); h = block()
check("4 two entries on one hostname: the first has the machine's card, the second an offline line", 'class="mr update"' in card(h, "box-b") and 'class="mr offline"' in card(h, "bbb"), h)
# a hand-edited list may carry spaces round a hostname: it still joins
store([mach("elsewhere", hostname="  BOX-B \t")], 30.0, post=False); h = block()
check("4 a hostname with white space round it still joins its card", machs(h) == ["box-b"] and 'class="mr update"' in card(h, "box-b"), machs(h))
# a failure: inside its machine's card while the machine is listed, a separate alert card when it has none
mj = (T / "fleet/c/machine.json").read_text()
(T / "fleet/c/machine.json").write_text(json.dumps({**json.loads(mj), "setup": {"at": "2026-10-15T00:00:00Z", "ok": False, "step": "Install Claude Code", "reason": "install exited"}}))
store([mach("testbox"), mach("box-c")], 30.0); h = block()
check("4 a failure of a listed machine is a line inside its card, no separate alert card", 'class="pc mach bad"' in card(h, "box-c") and card(h, "box-c").count('<div class="mf"') == 1 and "pc alert" not in h and "Install Claude Code" in card(h, "box-c"), card(h, "box-c"))
store([mach("testbox"), mach("box-c", retired=True)], 30.0); h = block()
check("4 a failure of a machine the list leaves without a card keeps its own alert card", machs(h) == ["testbox"] and h.count("pc alert bad") == 1 and "Install Claude Code" in h, h[-600:])
store([mach("testbox")], 30.0); h = block()
check("4 …and so for a fleet machine the list does not name", h.count("pc alert bad") == 1)
write_versions([host("c", "5.5.5")])      # an ssh host named like the fleet machine's letter: the letters and the host names are two sets, so it does not hide that machine's alert
store([mach("testbox"), mach("c")], 30.0); h = block()
check("4 an ssh host named `c`, listed, has its card and does not hide the alert of the unlisted fleet machine c", machs(h) == ["testbox", "c"] and "5.5.5" in card(h, "c") and h.count("pc alert bad") == 1 and "Install Claude Code" in h, machs(h))
write_versions()
(T / "fleet/c/machine.json").write_text(mj)

# ================================================================ 5. a stale list
for ago_s, stale, word in ((899, False, "14m ago"), (901, True, "15m ago"), (20 * 60, True, "20m ago"), (3 * 3600, True, "3h ago"), (5 * 86400, True, "5d ago")):
    store([mach("testbox")], float(ago_s)); h = block(); ns = notes(h)
    check(f"5 a list received {ago_s} s ago is {'stale' if stale else 'fresh'}: " + ("one amber line of its age" if stale else "no line"),
          (len(ns) == 1 and "fl-stale" in ns[0] and f"updated {word}" in ns[0] and "no newer list has arrived lately" in ns[0]) if stale else ns == [], ns)
    check("5 …the list is still drawn", machs(h) == ["testbox"], machs(h))
store([mach("testbox")], 3600.0, not_read=["x.json"]); h = block(); ns = notes(h)
check("5 a stale list with names not read: the age line above the cards, then the note under them", len(ns) == 2 and "fl-stale" in ns[0] and "not read: x.json" in ns[1] and h.index("fl-stale") < h.index('class="matrix"') < h.index("fl-nr"), ns)

# ================================================================ 6. escaping
EVIL = ['<script>alert(1)</script>', '"><img src=x onerror=alert(1)>', "a&b &amp; &lt;", "it's \"quoted\"", "javascript:alert(1)", "' onmouseover='alert(1)", "</div><p>x"]
base_page = page(); base_scripts, base_imgs, base_links = base_page.count("<script"), base_page.count("<img"), base_page.count("<a ")
bt = Tags(); bt.feed(baseline_block)
store([mach(f"n{i} {t}", hostname=f"h{i}-{t}") for i, t in enumerate(EVIL)], 30.0, not_read=EVIL)
h = block(); pg = page()
tg = Tags(); tg.feed(h)
check("6 the panel gains no tag but the notes' p", set(tg.tags) <= set(bt.tags) | {"p"}, sorted(set(tg.tags) - set(bt.tags)))
check("6 …and no attribute but class", tg.attrs <= bt.attrs | {"class"}, sorted(tg.attrs - bt.attrs))
check("6 no link is built from a stored text", h.count("<a ") == baseline_block.count("<a ") and "href=" not in h and "<img" not in h)
check("6 a script or image tag in a text is shown as text", "<script" not in h and "<img" not in h and "&lt;script&gt;alert(1)&lt;/script&gt;" in h and "&lt;img src=x onerror=alert(1)&gt;" in h, h[:500])
check("6 an ampersand is escaped, and one already written as an entity is shown as written", "a&amp;b &amp;amp; &amp;lt;" in h)
check("6 a quote cannot close an attribute", "&quot;" in h and "onmouseover='" not in h and '"quoted"' not in h, h[:500])
check("6 javascript: is only text", "javascript:alert(1)" in h and "javascript:alert(1)" not in re.sub(r'(title="[^"]*"|>[^<]*<)', "", h))
check("6 the same in not_read", "&lt;script&gt;alert(1)&lt;/script&gt;" in h.split('fl-nr')[1] and "<script" not in h.split('fl-nr')[1])
check("6 a hostname that joins nothing is not drawn", "h0-" not in h and "h3-" not in h)
check("6 the whole page holds no script, image or link tag more than the page without the hostile list", pg.count("<script") == base_scripts and pg.count("<img") == base_imgs and pg.count("<a ") == base_links, (pg.count("<script"), base_scripts, pg.count("<img"), base_imgs))

# ================================================================ 7. a hand-edited file
store([{"name": 7, "hostname": ["x"], "letter": {"a": 1}, "ssh": 5, "addresses": "192.0.2.1", "roles": "sala-host", "retired": "yes", "sources": [1, None, "ok.json"]},
       {"name": "fine-box", "retired": True}, {"name": "box-b", "retired": "yes"}, {"name": "testbox"}], 30.0, post=False)
try: h = block(); err = None
except Exception as e: h, err = "", e
check("7 fields of the wrong kind draw without an error", err is None, err)
check("7 a machine with no text for a name has no card; `retired` counts only when it is true", machs(h) == ["box-b", "testbox"] and "fine-box" not in h, machs(h))
store(["not an object"], 30.0, post=False)
check("7 a machine that is no object reads the whole file as none", NOLIST in block())
LISTFILE.write_text(json.dumps({"schema": 1, "written": 1.0, "received": 1.0, "posted_by": "x", "machines": [], "not_read": "abc"}))
check("7 `not_read` that is no list reads the whole file as none (the stored reader's rule)", NOLIST in block())

# a name is drawn once, whatever its case (the first entry wins); a name that is blank is no name
store([mach("box-b"), mach("box-b")], 30.0, post=False); h = block()
check("7 a name listed twice has one card, the machine's own", machs(h) == ["box-b"] and 'class="mr update"' in card(h, "box-b"), machs(h))
store([mach("box-b"), mach("BOX-B"), mach("testbox")], 30.0, post=False); h = block()
check("7 a name listed twice in another case has one card, the first entry's", machs(h) == ["box-b", "testbox"], machs(h))
store([mach("ghost"), mach("GHOST", hostname="box-c")], 30.0, post=False); h = block()
check("7 two entries of a name nothing has read: one offline card, the first entry's name, and the second's hostname joins nothing", machs(h) == ["ghost"] and 'class="mr offline"' in card(h, "ghost") and "box-c" not in h, machs(h))
for blank in (" ", "   ", "\t", " "):
    store([mach(blank, hostname="ws.example.net"), mach("testbox")], 30.0, post=False); h = block()
    check(f"7 a name that is blank ({blank!r}) is no name: no card, not even by its hostname", machs(h) == ["testbox"] and "ws.example.net" not in h, machs(h))
store([mach(" box-b "), mach("testbox")], 30.0, post=False); h = block()
check("7 a name with white space round it is its name", machs(h) == ["box-b", "testbox"], machs(h))

# ================================================================ 8. 200 machines
store([mach(f"unit-{i:03d}", hostname=f"host-{i:03d}.example.net") for i in range(200)], 30.0)
pg = page()
check("8 200 machines draw as 200 cards and the page renders", len(machs(block())) == 200 and "</html>" in pg and "unit-199" in pg, len(machs(block())))

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
store([mach("testbox")], 30.0)
check("10 paired: the list chooses the cards", machs(block()) == ["testbox"])
unpair(fp)
check("10 the key revoked and the token gone: the board is as before any pairing", block() == baseline_block and machs(block()) != ["testbox"])

# ================================================================ 11. the sender's optional readings (online, last_seen, versions, checked): in the view, never on a card
fp = pair()
RW = float(int(time.time()) - 30)       # a `written` and `received` fixed for this section, so every age below is exact: the view is asked for its answer at RW + the age
def put(machines, written=RW, received=RW):
    clear()
    LISTFILE.write_text(json.dumps({"schema": 1, "written": written, "received": received, "posted_by": "box-x", "high": written, "machines": machines, "not_read": []}))
def rep_of(m_over, at=RW + 30, **put_kw):
    """The `reported` object the view gives machine demo-a, asked at time `at`."""
    put([{**mach("demo-a"), **m_over}], **put_kw)
    return MP.view(at)["machines"][0].get("reported")
READ = {"online": True, "last_seen": None, "versions": {"cli": "1.2.3"}, "checked": RW}
# ---- an old body: the view and the page are byte for byte what they were
put([mach("testbox"), mach("demo-b"), mach("lone-box", hostname=None, letter=None)])
old_view = MP.view(RW + 30); old_html = block(); old_page = page()
check("11 a list with none of the four keys: the view's machines are exactly name, hostname and retired (no `reported`)", all(set(m) == {"name", "hostname", "retired"} for m in old_view["machines"]) and len(old_view["machines"]) == 3, old_view)
# ---- fresh readings
r = rep_of(READ)
check("11 a fresh entry: `reported` has online, last_seen, versions as stored, checked and fresh", r == {"online": True, "last_seen": None, "versions": {"cli": "1.2.3"}, "checked": RW, "fresh": True}, r)
check("11 the other keys of the machine are unchanged beside it", MP.view(RW + 30)["machines"][0] == {"name": "demo-a", "hostname": "demo-a.example.net", "retired": False, "reported": r})
r = rep_of({"online": False, "last_seen": RW - 600, "versions": {}, "checked": RW})
check("11 offline with a last_seen: shown as stored, and `versions` of {} stays {} (the sender read nothing)", r["online"] is False and r["last_seen"] == RW - 600 and r["versions"] == {} and r["versions"] is not None and r["fresh"] is True, r)
# ---- unknown is not no: absent, null, {}
r = rep_of({"checked": RW})
check("11 only `checked`: online, last_seen and versions are all None (unknown), never False or {}", r == {"online": None, "last_seen": None, "versions": None, "checked": RW, "fresh": True}, r)
r = rep_of({"online": None, "last_seen": None, "versions": None, "checked": RW})
check("11 nulls are unknown, the same as absent", r == {"online": None, "last_seen": None, "versions": None, "checked": RW, "fresh": True}, r)
# ---- the 900-second rule: the list's age on the server's clock plus how much older `checked` is than `written`
check("11 the reading is fresh at exactly 900 s of age and stale at 900.5 s (checked = written, the list received at its written time)", rep_of(READ, RW + 900)["fresh"] is True and rep_of(READ, RW + 900.5)["fresh"] is False, None)
check("11 a `checked` older than the post's `written` adds its gap to the age: 880 s older and the list 20 s old is 900 (fresh), 21 s old is stale", rep_of({**READ, "checked": RW - 880}, RW + 20)["fresh"] is True and rep_of({**READ, "checked": RW - 880}, RW + 21)["fresh"] is False, None)
check("11 …the gap alone can make it stale: 901 s older than `written` and the list just received", rep_of({**READ, "checked": RW - 901}, RW)["fresh"] is False and rep_of({**READ, "checked": RW - 900}, RW)["fresh"] is True, None)
check("11 a `checked` after `written` counts no negative gap: it is as fresh as the list", rep_of({**READ, "checked": RW + 500}, RW + 900)["fresh"] is True and rep_of({**READ, "checked": RW + 500}, RW + 901)["fresh"] is False, None)
check("11 a list received long ago has no fresh reading, whatever its `checked`: the age of the list counts", rep_of(READ, RW + 5000)["fresh"] is False, None)
r = rep_of(READ, RW + 5000)
check("11 a stale reading is viewed as unknown: online, last_seen and versions None, `checked` kept for display, `fresh` false (never a fact)", r == {"online": None, "last_seen": None, "versions": None, "checked": RW, "fresh": False}, r)
r = rep_of({"online": True, "versions": {"cli": "1"}, "last_seen": 5})
check("11 no `checked`: never fresh, whatever else is there (an unknown age is no fresh reading)", r["fresh"] is False and r["online"] is None and r["versions"] is None and r["checked"] is None, r)
# ---- a hand-edited file: a reading of the wrong type is unknown, nothing raises
for label, over in (("online as text", {"online": "yes"}), ("online as 1", {"online": 1}), ("last_seen as text", {"last_seen": "x"}), ("last_seen negative", {"last_seen": -5}), ("last_seen true", {"last_seen": True}),
                    ("versions as a list", {"versions": ["a"]}), ("versions with a number value", {"versions": {"a": 1}}), ("versions of 17", {"versions": {f"k{i}": "v" for i in range(17)}}), ("checked as text", {"checked": "now"}), ("checked true", {"checked": True})):
    try: r = rep_of({**READ, **over})
    except Exception as e: r = e
    key = next(iter(over))
    ok = isinstance(r, dict) and r[key] is None and r["fresh"] is (key != "checked")      # the bad field is unknown; the rest still count (only a bad `checked` makes the reading not fresh)
    check(f"11 a stored reading of the wrong type ({label}) is unknown in the view and raises nothing", ok, r)
# ---- the field-by-field fallback
FRESH = {"online": True, "last_seen": RW, "versions": {"cli": "1.2.3"}, "checked": RW, "fresh": True}
STALE = {"online": None, "last_seen": None, "versions": None, "checked": RW, "fresh": False}
fb = MP.fallback({"online": False, "last_seen": 5.0, "versions": {"cli": "0.9"}}, FRESH)
check("11 every own reading present: all three are the board's own, the sender's is not used (False counts as a reading)", fb == {"online": {"value": False, "source": "own"}, "last_seen": {"value": 5.0, "source": "own"}, "versions": {"value": {"cli": "0.9"}, "source": "own"}}, fb)
fb = MP.fallback({"online": None, "last_seen": None, "versions": None}, FRESH)
check("11 no own reading and a fresh sender's: all three are the sender's", fb == {"online": {"value": True, "source": "list"}, "last_seen": {"value": RW, "source": "list"}, "versions": {"value": {"cli": "1.2.3"}, "source": "list"}}, fb)
fb = MP.fallback({"online": None, "last_seen": None, "versions": None}, STALE)
check("11 no own reading and a stale sender's: unknown for all three, never the sender's", all(v == {"value": None, "source": None} for v in fb.values()) and set(fb) == {"online", "last_seen", "versions"}, fb)
fb = MP.fallback({"online": None}, {**FRESH, "fresh": False})
check("11 a `reported` that says it is not fresh is never used, even if it holds values (the flag decides, not the values)", all(v == {"value": None, "source": None} for v in fb.values()), fb)
fb = MP.fallback({"online": None}, {**FRESH, "fresh": 1})
check("11 …and only a `fresh` of exactly true counts", all(v == {"value": None, "source": None} for v in fb.values()), fb)
fb = MP.fallback({"online": False}, FRESH)
check("11 field by field: an own `online` stays while last_seen and versions come from the fresh sender's", (fb["online"], fb["last_seen"]["source"], fb["versions"]["source"]) == ({"value": False, "source": "own"}, "list", "list"), fb)
fb = MP.fallback({"versions": {"cli": "0.9"}}, FRESH)
check("11 …and an own `versions` stays while online and last_seen come from the sender's", (fb["versions"]["source"], fb["online"]["source"], fb["last_seen"]["source"]) == ("own", "list", "list"), fb)
fb = MP.fallback({"last_seen": 7.0, "versions": {}}, {**FRESH, "versions": None})
check("11 an own `{}` is a reading (it is kept); a sender's unknown field is unknown, not borrowed: last_seen own, versions own {}, online from the sender", (fb["last_seen"], fb["versions"], fb["online"]) == ({"value": 7.0, "source": "own"}, {"value": {}, "source": "own"}, {"value": True, "source": "list"}), fb)
check("11 no own readings at all (None) and no `reported` (None): unknown for all three", all(v == {"value": None, "source": None} for v in MP.fallback(None, None).values()))
# ---- the page: nothing is drawn from the readings, byte for byte, whatever they hold
def with_readings(over): return [{**m, **over(i)} for i, m in enumerate([mach("testbox"), mach("demo-b"), mach("lone-box", hostname=None, letter=None)])]
for label, over in (("fresh readings on every machine", lambda i: {"online": i != 1, "last_seen": None if i != 1 else RW - 99, "versions": {"cli": "9.9.9"} if i == 0 else {}, "checked": RW}),
                    ("stale readings", lambda i: {"online": False, "last_seen": 1, "versions": {"cli": "0.0.1"}, "checked": RW - 5000}),
                    ("null readings", lambda i: {"online": None, "last_seen": None, "versions": None, "checked": None}),
                    ("every machine told online with versions by the sender, those with a reading of their own and those with none", lambda i: {"online": True, "last_seen": None, "versions": {"cli": "1.0.0"}, "checked": RW})):
    put(with_readings(over)); h2 = block(); p2 = page()
    check(f"11 {label}: the Machines block and the page are byte for byte those of the same list without them (nothing is drawn from the readings)", h2 == old_html and p2 == old_page and "9.9.9" not in p2 and "0.0.1" not in p2, [i for i, (a, b) in enumerate(zip(h2, old_html)) if a != b][:1])
put([mach("lone-box", hostname=None, letter=None, online=True, last_seen=None, versions={"cli": "9.9.9"}, checked=RW)]); h2 = block()
put([mach("lone-box", hostname=None, letter=None)]); h3 = block()
check("11 a listed machine nothing has read still draws its one offline line when the sender says it is online", h2 == h3 and 'class="mr offline"' in h2 and "9.9.9" not in h2, h2)
unpair(fp)
check("11 unpaired again: the view is None whatever the readings", MP.view(RW + 30) is None)
check("11 the page's renderer reads nothing of `reported` or `fallback` yet", not re.search(r"""["']reported["']|_mpanel\.fallback""", pathlib.Path(STACK, "stackshot", "web", "ui", "render.py").read_text(encoding="utf-8")))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
