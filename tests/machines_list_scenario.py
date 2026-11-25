"""Scenario test for the machine list the fleet manager posts (service/machines_list.py `POST /client/machines`, and the route's size cap in web/routes/client_api.py): the sender posts its list of machines, the server
validates it strictly, keeps the last good one in one file in the state folder and reads it back with `last_machines()`. Fixture data in a temporary state folder, no live store, no network, no model call.

  1  the route's module: a good body is stored and read back (cleaned fields only, who posted it, when it was received); a key the module does not know is ignored and never stored; a list left out is empty and a
     role named twice is kept once; text is cleaned (control and format characters out, white space collapsed); the boundary values (200 machines, an 80-character name, 16 addresses of 64 characters, ...) are accepted
  2  each refused body answers 400 with one line of reason and leaves the last good list byte for byte, with no temporary file left: a body that is no object, a wrong schema, a `written` that is not a time (text, true,
     zero, before 2020, more than a minute ahead, 1.0 or true as the schema, infinite, a huge integer), `machines` that is no list or holds 201, a machine that is no object, a missing, empty, control-only or 81-character name, a text field of
     the wrong kind or too long, addresses, roles, `retired`, `sources` and `not_read` outside their limits, a lone surrogate
  3  a bad post never replaces the last good one: after a run of refused bodies the same list is read back; a read-only standby copy answers 503 and a file that cannot be written answers 503, both keep it
  4  the write is atomic: the temporary file is made in the same folder, mode 0600, and is renamed over the list; no temporary file is left after a good post, a refused one or a failed write; the list is mode 0600 whatever the
     umask (a new file and a replaced one); a stale temporary file of the writer's own name is swept and nothing else is touched; 8 threads posting at once leave a whole list and no reader meets a torn file
  5  `last_machines()` reads a missing file, an empty one, a torn one, one that is no object, another schema, and one with a field of the wrong kind (`machines`, `received`, `written`, `posted_by`, `not_read`) as None,
     and a folder in place of the file; it never raises
  6  a list that arrives late does not replace a newer one: more than 300 s older than the high-water mark (the newest `written` ever accepted, stored as `high`) is kept out (200 {ok, kept: newer}, the file untouched),
     300 s older or the same time or newer replaces; a run of posts each a little older than the last cannot walk the list back (five posts newest first, over the service and over HTTP); a file without `high` counts its
     own `written`; a stored time or mark far ahead of the clock, or an unreadable file, holds nothing out and the next write corrects the mark; the ahead limit is exactly 60 s; a refused body is still 400, old and new
     posts at once leave the newest
  7  names that draw as nothing (combining marks, spaces, and each of U+FFA0, U+115F, U+1160, U+3164 and U+2800 alone, in `name` and `hostname`) are refused with one line (an EMPTY `hostname`, one of spaces or of invisible characters alone is no refusal: it is stored as "", as a retired machine has none; `name` stays required); letters with marks, one symbol or one digit are kept; two machines of one name once cleaned and case-folded are refused
  8  durability: the temporary file is flushed, then renamed, then the folder is flushed; a folder that cannot be flushed is no failure, a file that cannot be flushed is a failed write (503)
  9  `last_machines()` never blocks and never reads without a bound: a pipe at the path (with a timeout), a file over the bound (by its size and by a size that lied), a link and a folder read as None; a file at the bound reads
 10  over HTTP: no token 401, a wrong token 401, a machine token stores (200), a LIVE pass is exactly 403, a refused body 400 with one reason for each of: text that is no JSON, JSON that is no object, a nesting too deep, too many
     digits; a schema that is not the number 1 (1.0, true, text) is refused; no Content-Type is needed; a body of exactly 1,000,000 bytes is stored, one of 1,000,001 is 413; a Content-Length that understates the body, one that is
     no number and a body with no length (chunked) are each cut off at the cap (413) and the body is never parsed or validated; a declared length over the cap is refused before the body is read; a sender that disconnects mid-body
     gets a quiet 400, nothing is parsed or written and the log holds no traceback; the old list stays after every refusal; the unknown-verb answer names `machines`
 11  no secret: the machine token appears in no answer and not in the stored file
 12  the four optional readings of a machine (`online`, `last_seen`, `versions`, `checked`): an old body is stored byte for byte as before and answered as before; the four are stored after `sources` in their order; absent, null and `{}` stay three
     different things; a reading of the wrong type or out of range (each case) never refuses the post: it is dropped from its row (unknown), the rest of the row is kept and the answer names it (`dropped`, at most 20 names then a count); the
     boundaries (16 entries, a key of 64, a value of 200, 0 and 1e12) are accepted and 17 entries are dropped whole; texts are cleaned; a sample body of three machines replayed through the real route and read by the panel's view

    tests/run-suite machines_list       -> exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging, random, stat as _stat, threading
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="machineslist-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state", "secrets", "brain/projects", "home"): (T / d).mkdir(parents=True)
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("1"); (T / "store/anchors.json").write_text("{}")

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:400]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server
from stackshot.web.routes import client_api
from stackshot.service import machines_list as SVC
from stackshot.core import readonly as _ro
from stackshot.fleet import client

STATE = T / "state"; FILE = STATE / "machines-list.json"
def mach(name="box-one", **over):
    n_ = name if isinstance(name, str) else "x"
    m = {"name": name, "hostname": n_ + ".example.net", "letter": "a", "ssh": "user@" + n_, "addresses": ["192.0.2.10", "2001:db8::10"], "roles": ["sala-host"], "retired": False, "sources": ["fleet.json"]}
    m.update(over); return m
def good(machines=None, written=None, **over):
    b = {"schema": 1, "written": time.time() - 30 if written is None else written, "machines": [mach()] if machines is None else machines, "not_read": []}
    b.update(over); return b
def stored(): return FILE.read_bytes() if FILE.exists() else None
def loaded(): return json.loads(FILE.read_text()) if FILE.exists() else None
def leftovers(): return sorted(p.name for p in STATE.iterdir() if p.name != FILE.name)
def one_line(r): return isinstance(r, str) and bool(r) and "\n" not in r

# ================================================================ 1. the route's module: a good body is stored and read back
check("1 no list yet: nothing is stored and `last_machines()` says none", stored() is None and SVC.last_machines() is None)
t0 = time.time()
b = good([mach("box-one"), mach("box-two", hostname=None, letter=None, ssh=None, addresses=[], roles=["sala-host", "stackshot-host"], retired=True, sources=["a.json", "b.json"])], not_read=["broken.json"])
b["machines"][0]["secret_extra"] = "never stored"; b["top_extra"] = {"x": 1}
st, out = SVC.post("box-far", b)
got = SVC.last_machines()
check("1 a good body is stored and answers 200 {ok, machines: N}", (st, out) == (200, {"ok": True, "machines": 2}) and got is not None, (st, out, got))
lst, received = got
check("1 …and read back: the cleaned machines, `written`, `not_read`, who posted it (the machine the token proved) and the received time (the server's clock)",
      lst == {"schema": 1, "written": b["written"], "posted_by": "box-far", "machines": [{k: v for k, v in m.items() if k != "secret_extra"} for m in b["machines"]], "not_read": ["broken.json"]} and t0 <= received <= time.time() + 1, (lst, received))
check("1 …a key the module does not know (in a machine, at the top) is ignored and never stored", "secret_extra" not in stored().decode() and "top_extra" not in stored().decode() and set(loaded()) == {"schema", "written", "received", "posted_by", "high", "machines", "not_read"}, loaded())
check("1 …the file is in the state folder, nothing else is left beside it", FILE.parent == STATE and leftovers() == [], leftovers())
st, out = SVC.post("box-far", {"schema": 1, "written": time.time(), "machines": [{"name": "bare", "retired": False}]})
m0 = SVC.last_machines()[0]["machines"][0]
check("1 a machine with only its name and `retired` is stored with the other fields null or empty", st == 200 and m0 == {"name": "bare", "hostname": None, "letter": None, "ssh": None, "addresses": [], "roles": [], "retired": False, "sources": []} and SVC.last_machines()[0]["not_read"] == [], (st, m0))
SVC.post("box-far", good([mach(roles=["sala-host", "sala-host", "stackshot-host", "sala-host"])]))
check("1 a role named twice is kept once, in order", SVC.last_machines()[0]["machines"][0]["roles"] == ["sala-host", "stackshot-host"])
SVC.post("box-far", good([mach("a\x00b\u200bc  d\n\te\x1b[0m", hostname="  host\x07name \r\n x ", sources=["s\u2028t"], addresses=["198.51.100.7\x00"])], not_read=["f\x00ile\n.json"]))
l1 = SVC.last_machines()[0]
check("1 text is cleaned: control and format characters out, runs of white space one space, the ends trimmed",
      l1["machines"][0]["name"] == "abc d e[0m" and l1["machines"][0]["hostname"] == "hostname x" and l1["machines"][0]["sources"] == ["s t"] and l1["machines"][0]["addresses"] == ["198.51.100.7"] and l1["not_read"] == ["file .json"], l1)
check("1 …a name or text of characters that draw as nothing is empty after cleaning (the name is then refused)", SVC.post("box-far", good([mach("\u3164\u2800\u200b")]))[0] == 400 and SVC.last_machines()[0]["machines"][0]["name"] == "abc d e[0m")
SVC.post("box-far", good([mach("\u00e9\u4e2d\u6587\U0001f600 box")]))
check("1 non-ASCII text is kept whole", SVC.last_machines()[0]["machines"][0]["name"] == "\u00e9\u4e2d\u6587\U0001f600 box")
edge = good([mach(f"m{i}") for i in range(200)], written=time.time() + 59)
edge["machines"][0] = mach("n" * 80, hostname="h" * 200, letter="l" * 200, ssh="s" * 200, addresses=["a" * 64] * 16, roles=["sala-host", "stackshot-host", "sala-host", "stackshot-host"], sources=["x" * 200] * 20)
edge["not_read"] = ["f" * 200] * 200
st, out = SVC.post("box-far", edge)
check("1 the boundary values are accepted: 200 machines, an 80-character name, 200-character texts, 16 addresses of 64, 4 roles, 20 sources of 200, 200 not-read names of 200, a time 59 s ahead", (st, out) == (200, {"ok": True, "machines": 200}) and len(SVC.last_machines()[0]["machines"]) == 200, (st, out))
FILE.unlink()
check("1 …a time of Jan 1st 2020 is accepted and stored", SVC.post("box-far", good(written=1577836800))[0] == 200 and loaded()["written"] == 1577836800)

# ================================================================ 2. every refusal: 400, one line, the last good list stays
SVC.post("box-far", good([mach("keeper")])); keep = stored()
HUGE = 10 ** 400; SUR = json.loads('"\\ud800"')
bad = {
    "a list": [1, 2], "a string": "x", "null": None,
    "another schema": good(schema=2), "a text schema": good(schema="1"), "a true schema": good(schema=True), "no schema": {"written": time.time(), "machines": []},
    "no time": {"schema": 1, "machines": []}, "a time that is text": good(written="now"), "a true time": good(written=True), "a time of zero": good(written=0), "a time before 2020": good(written=1577836799),
    "a negative time": good(written=-5), "a time ten minutes ahead": good(written=time.time() + 600), "a time two minutes ahead": good(written=time.time() + 120), "a time 90 s ahead": good(written=time.time() + 90),
    "a schema of 1.0": good(schema=1.0), "a schema of 1.5": good(schema=1.5), "an infinite time": good(written=float("inf")), "a nan time": good(written=float("nan")),
    "a time that is a huge integer": good(written=HUGE), "a time past the bound": good(written=2e12), "a time of 1e400": json.loads('{"schema": 1, "written": 1e400, "machines": []}'),
    "machines left out": {"schema": 1, "written": time.time()}, "machines null": good(machines=None) | {"machines": None}, "machines an object": good(machines={}), "machines a string": good(machines="x"),
    "201 machines": good([mach(f"m{i}") for i in range(201)]), "a machine that is no object": good(["box"]), "a machine that is null": good([None]),
    "no name": good([{"retired": False}]), "a name that is a number": good([mach(5)]), "an empty name": good([mach("")]), "a blank name": good([mach("   ")]), "a control-only name": good([mach("\x00\x07\x1b")]),
    "a name of 81 characters": good([mach("n" * 81)]),
    "a name of combining marks": good([mach("\u0301\u0302")]), "a name of a mark and spaces": good([mach(" \u0301 \u0300 ")]), "a name of a variation selector": good([mach("\ufe0f")]), "a name of combining marks and invisible characters": good([mach("\u0301\u200b\u3164")]),
    "a hostname of combining marks": good([mach(hostname="\u0301\u0302")]),
    "two machines of one name": good([mach("box"), mach("other"), mach("box")]), "two names that differ in case": good([mach("Box"), mach("bOX")]), "two names that differ in spaces and invisible characters": good([mach("a b"), mach(" a\u200b  b ")]),
    "two names that fold to one": good([mach("Stra\u00dfe"), mach("STRASSE")]), "a name that is a list": good([mach(["a"])]),
    "a hostname of 201": good([mach(hostname="h" * 201)]), "a hostname that is a number": good([mach(hostname=5)]), "a letter of 201": good([mach(letter="l" * 201)]), "a letter that is a list": good([mach(letter=["a"])]),
    "an ssh of 201": good([mach(ssh="s" * 201)]), "an ssh that is true": good([mach(ssh=True)]),
    "addresses a string": good([mach(addresses="192.0.2.1")]), "17 addresses": good([mach(addresses=["198.51.100.7"] * 17)]), "an address of 65": good([mach(addresses=["a" * 65])]), "an address that is a number": good([mach(addresses=[5])]),
    "roles a string": good([mach(roles="sala-host")]), "5 roles": good([mach(roles=["sala-host"] * 5)]), "an unknown role": good([mach(roles=["admin"])]), "a role that is a number": good([mach(roles=[1])]), "a role of another case": good([mach(roles=["Sala-Host"])]),
    "retired left out": good([{k: v for k, v in mach().items() if k != "retired"}]), "retired as text": good([mach(retired="no")]), "retired as 0": good([mach(retired=0)]), "retired null": good([mach(retired=None)]),
    "sources a string": good([mach(sources="x")]), "21 sources": good([mach(sources=["x"] * 21)]), "a source of 201": good([mach(sources=["x" * 201])]), "a source that is a number": good([mach(sources=[3])]),
    "not_read a string": good(not_read="x"), "201 not_read": good(not_read=["x"] * 201), "a not_read of 201": good(not_read=["x" * 201]), "a not_read that is a number": good(not_read=[1]),
    "a lone surrogate in a name": good([mach(SUR)]), "a lone surrogate in a hostname": good([mach(hostname="h" + SUR)]), "a lone surrogate in a source": good([mach(sources=[SUR])]), "a lone surrogate in not_read": good(not_read=[SUR]),
    "a bad machine after good ones": good([mach("ok1"), mach("ok2"), mach("n" * 81)]),
}
res = {k: SVC.post("box-far", v) for k, v in bad.items()}
check("2 each refused body answers 400 with one line of reason (no exception, so no 500)", all(s == 400 and one_line(o.get("error")) for s, o in res.values()), {k: v for k, v in res.items() if v[0] != 400 or not one_line(v[1].get("error"))})
check("2 …and the last good list stays, byte for byte, with no temporary file left", stored() == keep and leftovers() == [] and SVC.last_machines()[0]["machines"][0]["name"] == "keeper", (leftovers(),))
check("2 …a refusal names what is wrong (the field) and holds no part of the body", all(re.search(r"schema|written|machines|name|hostname|letter|ssh|addresses|roles|retired|sources|not_read|JSON object", o["error"]) for _, o in res.values()) and "keeper" not in json.dumps(res), res["an unknown role"])

# ================================================================ 3. a bad post never replaces the last good one; a standby copy and a file that cannot be written
ro = _ro.is_read_only
_ro.is_read_only = lambda: True
try: st, out = SVC.post("box-far", good([mach("x")]))
finally: _ro.is_read_only = ro
check("3 a read-only standby copy answers 503 and stores nothing", st == 503 and stored() == keep, (st, out))
real_replace = os.replace
def boom(*a, **k): raise OSError("disk full")
SVC.os.replace = boom
try: st, out = SVC.post("box-far", good([mach("x")]))
finally: SVC.os.replace = real_replace
check("3 a file that cannot be written answers 503, the last list stays and no temporary file is left", st == 503 and "could not be written" in out["error"] and stored() == keep and leftovers() == [], (st, out, leftovers()))
st, out = SVC.post("box-far", good([mach("fresh")]))
check("3 a good post after the refusals replaces the whole list", st == 200 and [m["name"] for m in SVC.last_machines()[0]["machines"]] == ["fresh"], (st, out))

# ================================================================ 4. the write is atomic, mode 0600
seen_replace = []
def spy(src, dst, *a, **k):
    seen_replace.append((pathlib.Path(src).parent, pathlib.Path(dst), _stat.S_IMODE(os.stat(src).st_mode), json.loads(pathlib.Path(src).read_text())["machines"][0]["name"]))
    return real_replace(src, dst, *a, **k)
SVC.os.replace = spy
try: SVC.post("box-far", good([mach("atomic")]))
finally: SVC.os.replace = real_replace
check("4 the list is written whole to a temporary file in the same folder (mode 0600, complete) and renamed over the old one", len(seen_replace) == 1 and seen_replace[0][0] == STATE and seen_replace[0][1] == FILE and seen_replace[0][2] == 0o600 and seen_replace[0][3] == "atomic", seen_replace)
check("4 …no temporary file is left after a good post", leftovers() == [], leftovers())
FILE.unlink()
oldmask = os.umask(0)
try:
    SVC.post("box-far", good([mach("new")])); new_mode = _stat.S_IMODE(FILE.stat().st_mode)
    SVC.post("box-far", good([mach("replaced")])); replaced_mode = _stat.S_IMODE(FILE.stat().st_mode)
finally: os.umask(oldmask)
check("4 the list is mode 0600 whatever the umask: a new file and a replaced one", new_mode == 0o600 and replaced_mode == 0o600, (oct(new_mode), oct(replaced_mode)))
def _tmp_file(name, age_s, text="x"):
    q = STATE / name; q.write_text(text); os.utime(q, (time.time() - age_s, time.time() - age_s)); return q
stale = _tmp_file(".machines-list.json.111.222.tmp", 2 * 3600); fresh_tmp = _tmp_file(".machines-list.json.333.444.tmp", 600)
others = [_tmp_file(n, 2 * 3600) for n in (".machines-list.json.x.tmp", ".machines-list.json.1.2.tmp.bak", "machines-list.json.1.2.tmp", ".machines-list.json.1.tmp", "machines-list.json.old", ".other.5.6.tmp")]
target = _tmp_file("target-of-link.txt", 2 * 3600, "keep me"); link = STATE / ".machines-list.json.777.888.tmp"; link.symlink_to(target)
os.utime(link, (time.time() - 2 * 3600,) * 2, follow_symlinks=False)
adir = STATE / ".machines-list.json.9.9.tmp"; adir.mkdir(); os.utime(adir, (time.time() - 2 * 3600,) * 2)
SVC.post("box-far", good([mach("swept")]))
check("4 a leftover temporary file of the writer's own name older than an hour is removed by the next write", not stale.exists() and SVC.last_machines()[0]["machines"][0]["name"] == "swept")
check("4 …a recent one, a file of any other name, a link of that name (never followed, never removed) and a folder of that name stay",
      fresh_tmp.exists() and all(q.exists() for q in others) and link.is_symlink() and target.read_text() == "keep me" and adir.is_dir(), [q.name for q in STATE.iterdir()])
for q in (fresh_tmp, target, *others): q.unlink()
link.unlink(); adir.rmdir()
check("4 …and nothing of the test is left in the state folder but the list", leftovers() == [], leftovers())
# many senders at once: every read sees a whole list
ERRS, UNREAD, STOP = [], [], threading.Event()
def _poster(k):
    try:
        for i in range(25):
            st_c, out_c = SVC.post("box-far", good([mach(f"t{k}-{i}")]))
            if st_c != 200: ERRS.append((st_c, out_c))
    except BaseException as e_: ERRS.append(repr(e_))
def _poller():
    while not STOP.is_set():
        if SVC.last_machines() is None: UNREAD.append(time.time())
workers = [threading.Thread(target=_poster, args=(k,)) for k in range(8)]; poller = threading.Thread(target=_poller)
SWITCH = sys.getswitchinterval(); sys.setswitchinterval(1e-5)
try:
    poller.start()
    for w_ in workers: w_.start()
finally:
    for w_ in workers: w_.join()
    STOP.set(); poller.join(); sys.setswitchinterval(SWITCH)
check("4 8 threads posting 25 lists each: no post fails, no reader meets a torn or missing list, the stored list is one whole post and only the list is left in the state folder",
      not ERRS and not UNREAD and len(SVC.last_machines()[0]["machines"]) == 1 and re.fullmatch(r"t\d-\d+", SVC.last_machines()[0]["machines"][0]["name"]) and leftovers() == [], (ERRS[:3], len(UNREAD), leftovers()))

# ================================================================ 5. `last_machines()` never raises
SVC.post("box-far", good([mach("ok")]))
whole = loaded()
def writes(content, binary=False):
    if FILE.is_dir(): FILE.rmdir()
    FILE.unlink(missing_ok=True)
    FILE.write_bytes(content) if binary else FILE.write_text(content)
def reads_none(label, content, binary=False):
    writes(content, binary)
    try: r = SVC.last_machines()
    except BaseException as e_: check(f"5 {label}: reads as None and never raises", False, repr(e_)); return
    check(f"5 {label}: reads as None and never raises", r is None, r)
reads_none("an empty file", "")
reads_none("a torn file", json.dumps(whole)[:40])
reads_none("a file of bytes that are no UTF-8", b"\xff\xfe\x00 {", True)
reads_none("a list instead of an object", "[1,2]")
reads_none("null", "null")
reads_none("a nesting too deep for the parser", "[" * 100000)
for label, patch in (("another schema", {"schema": 2}), ("no schema", {"schema": None}), ("machines no list", {"machines": {}}), ("machines holding a non-object", {"machines": ["x"]}), ("machines missing", {"machines": None}),
                     ("received as text", {"received": "now"}), ("received missing", {"received": None}), ("received infinite", {"received": 1e999}), ("written as text", {"written": "x"}), ("written missing", {"written": None}),
                     ("posted_by missing", {"posted_by": None}), ("posted_by a number", {"posted_by": 5}), ("not_read missing", {"not_read": None}), ("not_read as text", {"not_read": "x"})):
    d = dict(whole); d.update(patch); d = {k: v for k, v in d.items() if v is not None}
    reads_none("a file with " + label, json.dumps(d))
FILE.unlink(); FILE.mkdir()
try: r = SVC.last_machines()
except BaseException as e_: r = repr(e_)
check("5 a folder in place of the file reads as None and never raises", r is None, r)
FILE.rmdir()
check("5 a missing file reads as None", SVC.last_machines() is None)
writes(json.dumps(whole))
check("5 …and the untouched file reads back whole", SVC.last_machines() is not None and SVC.last_machines()[0]["machines"][0]["name"] == "ok")
FILE.unlink()

# ================================================================ 6. a list that arrives late does not replace a newer one
W0 = float(int(time.time())) - 10
def _fresh(written, name="base"):
    FILE.unlink(missing_ok=True); st_, out_ = SVC.post("box-far", good([mach(name)], written=written)); assert st_ == 200, (st_, out_)
_fresh(W0); base = stored()
st, out = SVC.post("box-far", good([mach("late")], written=W0 - 1000))
check("6 a list whose `written` is 1000 s older than the stored one's is kept out: 200 {ok, kept: newer}, the stored file stays byte for byte, no temporary file", (st, out) == (200, {"ok": True, "kept": "newer"}) and stored() == base and leftovers() == [], (st, out, leftovers()))
st, out = SVC.post("box-far", good([mach("edge1")], written=W0 - 301))
check("6 …301 s older is kept out", (st, out) == (200, {"ok": True, "kept": "newer"}) and stored() == base, (st, out))
st, out = SVC.post("box-far", good([mach("edge2")], written=W0 - 300))
check("6 …exactly 300 s older replaces (the stored one must be MORE than 300 s newer)", (st, out) == (200, {"ok": True, "machines": 1}) and SVC.last_machines()[0]["machines"][0]["name"] == "edge2" and SVC.last_machines()[0]["written"] == W0 - 300, (st, out))
_fresh(W0)
st, out = SVC.post("box-far", good([mach("clock-step")], written=W0 - 200))
check("6 …a list 200 s older (a sender whose clock stepped back) replaces, and the stored `written` is then the older one", (st, out) == (200, {"ok": True, "machines": 1}) and SVC.last_machines()[0]["machines"][0]["name"] == "clock-step" and SVC.last_machines()[0]["written"] == W0 - 200, (st, out))
_fresh(W0)
st, out = SVC.post("box-far", good([mach("same")], written=W0))
check("6 …a list of the same `written` replaces", (st, out) == (200, {"ok": True, "machines": 1}) and SVC.last_machines()[0]["machines"][0]["name"] == "same", (st, out))
st, out = SVC.post("box-far", good([mach("newer")], written=W0 + 40))
check("6 …a newer list replaces", (st, out) == (200, {"ok": True, "machines": 1}) and SVC.last_machines()[0]["machines"][0]["name"] == "newer", (st, out))
rec_ = loaded(); rec_["written"] = time.time() + 5000; FILE.write_text(json.dumps(rec_))
st, out = SVC.post("box-far", good([mach("after-clock-fix")], written=time.time() - 30))
check("6 …a stored `written` far ahead of the server's clock (the clock was wrong when it was kept) does not hold later lists out", (st, out) == (200, {"ok": True, "machines": 1}) and SVC.last_machines()[0]["machines"][0]["name"] == "after-clock-fix", (st, out))
FILE.write_text("{torn"); st, out = SVC.post("box-far", good([mach("over-torn")], written=W0 - 5000))
check("6 …a stored file that cannot be read as a list never holds a post out", (st, out) == (200, {"ok": True, "machines": 1}) and SVC.last_machines() is not None, (st, out))

# ---- the high-water mark: a late post is compared with the newest `written` ever accepted, never with the stored list's (which an accepted older-within-300-s post lowers)
KEPT, OKM = (200, {"ok": True, "kept": "newer"}), (200, {"ok": True, "machines": 1})
def _seq(offsets):      # posts in this order, each a list named for its offset: (the answers, the name stored at the end)
    FILE.unlink(missing_ok=True); ans = []
    for off in offsets: ans.append(SVC.post("box-far", good([mach(f"p{off}")], written=W0 + off)))
    return ans, SVC.last_machines()[0]["machines"][0]["name"]
ans_, name_ = _seq([0, -300, -600, -900, -1200])
check("6 five posts, newest first, each 300 s older than the last (W, W-300, W-600, W-900, W-1200): the first two are stored, the other three kept out; the stored list is never more than 300 s older than the newest",
      ans_ == [OKM, OKM, KEPT, KEPT, KEPT] and name_ == "p-300" and SVC.last_machines()[0]["written"] >= W0 - SVC.NEWER_S and loaded()["high"] == W0, (ans_, name_, loaded() and loaded().get("high")))
ans_, name_ = _seq([0, -200, -400, -600, -800, -1000])
check("6 …the same with 200 s steps (each only 200 s older than the one before): the second is stored (200 s), every later one is 400 s or more behind the newest and kept out", ans_ == [OKM, OKM, KEPT, KEPT, KEPT, KEPT] and name_ == "p-200", (ans_, name_))
check("6 …the mark stays at the newest `written` ever accepted when an older post replaces the list (stored `written` W-200, `high` W)", loaded()["written"] == W0 - 200 and loaded()["high"] == W0, loaded() and (loaded()["written"], loaded()["high"], W0))
ans_, name_ = _seq([0, -200, -100, -250, 30, -200])
check("6 …a post newer than the mark raises it (W+30), the next one 200 s older than that replaces; the mark never falls", ans_ == [OKM] * 6 and loaded()["high"] == W0 + 30 and loaded()["written"] == W0 - 200, (ans_, loaded() and loaded().get("high")))
FILE.unlink(missing_ok=True); SVC.post("box-far", good([mach("a")], written=W0)); SVC.post("box-far", good([mach("b")], written=W0 - 100)); kept_file = stored()
st, out = SVC.post("box-far", good([mach("c")], written=W0 - 301))
check("6 …a kept post changes nothing in the file, byte for byte, the mark included", (st, out) == KEPT and stored() == kept_file, (st, out))
rec_ = loaded(); rec_.pop("high"); FILE.write_text(json.dumps(rec_))
st, out = SVC.post("box-far", good([mach("legacy-late")], written=W0 - 100 - 301))
check("6 a stored file without `high` (an earlier version) counts its own `written` as the mark: a post 301 s older than it is kept out", (st, out) == KEPT, (st, out))
st, out = SVC.post("box-far", good([mach("legacy-ok")], written=W0 - 100 - 300))
check("6 …a post exactly 300 s older replaces, and the file then carries `high` (the legacy `written`)", (st, out) == OKM and loaded()["high"] == W0 - 100 and loaded()["written"] == W0 - 400, loaded())
rec_ = loaded(); rec_["high"] = "soon"; FILE.write_text(json.dumps(rec_))
st, out = SVC.post("box-far", good([mach("bad-high")], written=W0 - 5000))
check("6 a `high` that is no number counts as the list's own `written`: the file reads, an old post is kept out", (st, out) == KEPT and SVC.last_machines() is not None, (st, out))
FILE.unlink(missing_ok=True); SVC.post("box-far", good([mach("seed")], written=W0))
rec_ = loaded(); rec_["high"] = W0 - 1000; FILE.write_text(json.dumps(rec_))
st, out = SVC.post("box-far", good([mach("low-high")], written=W0 - 301))
check("6 a `high` lower than the list's own `written` (an edited file) never lowers the mark below `written`: a post 301 s older than the list is kept out", (st, out) == KEPT, (st, out))
for ahead in (100, 301, 600, 5000):
    FILE.unlink(missing_ok=True); SVC.post("box-far", good([mach("seed")], written=W0))
    rec_ = loaded(); rec_["written"] = time.time() + ahead; rec_.pop("high", None); FILE.write_text(json.dumps(rec_))      # a legacy file whose `written` is ahead of the clock
    st, out = SVC.post("box-far", good([mach(f"after-{ahead}")], written=time.time() - 5)); hi_ = loaded()["high"]
    check(f"6 a stored `written` {ahead} s ahead of the server's clock counts as {int(SVC.AHEAD_S)} s ahead: a true post replaces it and the next mark is no further ahead than that", (st, out) == OKM and hi_ <= time.time() + SVC.AHEAD_S + 1, (st, out, hi_ - time.time()))
    FILE.unlink(missing_ok=True); SVC.post("box-far", good([mach("seed")], written=W0))
    rec_ = loaded(); rec_["high"] = time.time() + ahead; FILE.write_text(json.dumps(rec_))      # a `high` ahead of the clock
    st, out = SVC.post("box-far", good([mach(f"high-{ahead}")], written=time.time() - 5))
    check(f"6 …and a `high` {ahead} s ahead of the clock holds nothing out either, and is written back corrected", (st, out) == OKM and loaded()["high"] <= time.time() + SVC.AHEAD_S + 1, (st, out, loaded()["high"] - time.time()))
FILE.unlink(missing_ok=True); t_ = time.time()
st59, o59 = SVC.post("box-far", good([mach("ahead59")], written=t_ + 59)); hi59 = loaded()["high"]
st_n, o_n = SVC.post("box-far", good([mach("then-now")], written=time.time() - 2))
check("6 a `written` 59 s ahead of the clock is stored and becomes the mark; a post of the true time (about 61 s older) still replaces it (60 s is far inside 300)", (st59, o59, st_n, o_n) == (200, {"ok": True, "machines": 1}, 200, {"ok": True, "machines": 1}) and hi59 >= t_ + 58 and loaded()["high"] == hi59, (st59, o59, st_n, o_n))
st61, o61 = SVC.post("box-far", good([mach("ahead61")], written=time.time() + 65))
check("6 …65 s ahead is refused (400): a clock that far ahead never becomes the mark, so it holds nothing out", st61 == 400 and "written" in o61["error"] and loaded()["high"] == hi59, (st61, o61))
lst_, why_ = SVC.validate(good([mach("e")], written=1_800_000_000 + 60), now=1_800_000_000); lst2_, why2_ = SVC.validate(good([mach("e")], written=1_800_000_000 + 60.5), now=1_800_000_000)
check("6 the ahead limit is exactly 60 s: 60 s ahead is read, 60.5 s ahead is refused", lst_ is not None and lst2_ is None and "written" in why2_, (why_, why2_))
_fresh(W0); base = stored()
st, out = SVC.post("box-far", good([mach("n" * 81)], written=W0 - 1000))
check("6 a refused body is still 400 whatever its age (the check for age comes after the validation)", st == 400 and stored() == base, (st, out))
errs_ = []
def _late_poster():
    try:
        for i in range(20):
            s_, o_ = SVC.post("box-far", good([mach(f"l{i}")], written=W0 - 2000 - i))
            if (s_, o_) != (200, {"ok": True, "kept": "newer"}): errs_.append((s_, o_))
    except BaseException as e_: errs_.append(repr(e_))
def _new_poster():
    try:
        for i in range(20):
            s_, o_ = SVC.post("box-far", good([mach(f"n{i}")], written=W0 + 20 + i))
            if s_ != 200: errs_.append((s_, o_))
    except BaseException as e_: errs_.append(repr(e_))
ths = [threading.Thread(target=f_) for f_ in (_late_poster, _new_poster, _late_poster)]
SWITCH = sys.getswitchinterval(); sys.setswitchinterval(1e-5)
try:
    for t_ in ths: t_.start()
finally:
    for t_ in ths: t_.join()
    sys.setswitchinterval(SWITCH)
check("6 old and new lists posted at the same time: the stored list is the newest one, whole, and every old post answered `kept`", not errs_ and SVC.last_machines()[0]["written"] == W0 + 39 and leftovers() == [], (errs_[:3], SVC.last_machines()[0]["written"] - W0))
# the comparison and the replacement are one step: while a newer post is being written, a post that is older than it by more than 300 s waits for it and is then kept out
_fresh(W0 - 290)
a_in_write, release, real_write, res_ = threading.Event(), threading.Event(), SVC._write, {}
def slow_write(rec):
    a_in_write.set(); release.wait(10); return real_write(rec)
SVC._write = slow_write
try:
    ta = threading.Thread(target=lambda: res_.__setitem__("a", SVC.post("box-far", good([mach("newest")], written=W0 + 30))))
    ta.start(); a_in_write.wait(10)
    tb = threading.Thread(target=lambda: res_.__setitem__("b", SVC.post("box-far", good([mach("middle")], written=W0 - 280))))
    tb.start(); time.sleep(0.4); release.set(); ta.join(); tb.join()
finally: SVC._write = real_write
check("6 …the comparison and the replacement are one step: a post that is 310 s older than one being written waits for it and is kept out", res_.get("a") == (200, {"ok": True, "machines": 1}) and res_.get("b") == (200, {"ok": True, "kept": "newer"}) and SVC.last_machines()[0]["machines"][0]["name"] == "newest", (res_, SVC.last_machines()[0]["machines"][0]["name"]))

# ================================================================ 7. names that draw as nothing, and names that repeat
for label, nm in (("a letter and a combining mark", "e\u0301"), ("one punctuation mark", "-"), ("one symbol", "\u2603"), ("one digit", "7"), ("a Hangul syllable", "\ud55c"), ("marks around a letter", "\u0301a\u0301")):
    st, out = SVC.post("box-far", good([mach(nm, hostname=nm)]))
    check(f"7 {label} is a name that draws: stored", st == 200 and SVC.last_machines()[0]["machines"][0]["name"] == nm, (st, out))
st, out = SVC.post("box-far", good([mach("box", hostname=None), mach("Boxes")]))
check("7 two different names are stored", st == 200 and len(SVC.last_machines()[0]["machines"]) == 2, (st, out))
st, out = SVC.post("box-far", good([mach("\u0301\u0302")]))
check("7 a name of combining marks alone is refused with one line that names the field and the reason", st == 400 and one_line(out["error"]) and out["error"].startswith("machines[0].name") and "letter, digit, punctuation mark or symbol" in out["error"], (st, out))
for cp_ in (0xFFA0, 0x115F, 0x1160, 0x3164, 0x2800):
    for field_, kw_ in (("name", {}), ("hostname", {"hostname": chr(cp_)})):
        st, out = SVC.post("box-far", good([mach(chr(cp_) if field_ == "name" else "fine", **kw_)]))
        check(f"7 U+{cp_:04X} alone is no {field_} (it draws as nothing): refused with one line naming machines[0].{field_}", st == 400 and one_line(out["error"]) and out["error"].startswith(f"machines[0].{field_}"), (st, out))
st, out = SVC.post("box-far", good([mach(chr(0xFFA0) + "x" + chr(0x115F) + chr(0x1160))]))
check("7 \u2026and a name with a letter among them is stored with those characters taken out", st == 200 and SVC.last_machines()[0]["machines"][0]["name"] == "x", (st, out))
st, out = SVC.post("box-far", good([mach("ok"), mach("fine", hostname="\u0301")]))
check("7 a hostname of combining marks alone is refused, naming machines[1].hostname", st == 400 and one_line(out["error"]) and out["error"].startswith("machines[1].hostname"), (st, out))
# a retired machine has no hostname and no ssh: the sender posts "" for both, and one empty hostname must not refuse the list
for label, hv in (("an empty string", ""), ("spaces", "   "), ("a tab and a newline", "\t\n"), ("zero-width characters alone", "\u200b\u200d\ufeff"), ("a control character alone", "\x00")):
    st, out = SVC.post("box-far", good([mach("ok"), mach("gone", hostname=hv)]))
    check(f"7 a hostname of {label} is accepted and stored as an empty string", st == 200 and SVC.last_machines()[0]["machines"][1]["hostname"] == "", (st, out))
for label, hv in (("a lone combining mark", "\u0301"), ("a Hangul filler", "\u3164"), ("a filler among zero-width characters", "\u200b\u3164")):
    st, out = SVC.post("box-far", good([mach("ok"), mach("gone", hostname=hv)]))
    check(f"7 a hostname of {label} is still refused, naming machines[1].hostname", st == 400 and one_line(out["error"]) and out["error"].startswith("machines[1].hostname") and "letter, digit, punctuation mark or symbol" in out["error"], (st, out))
st, out = SVC.post("box-far", good([mach("ok"), mach("gone", ssh="", letter="")]))
m1 = (SVC.last_machines() or ({"machines": [{}, {}]},))[0]["machines"][1]
check("7 an empty `ssh` and an empty `letter` are accepted and stored as empty strings", st == 200 and m1.get("ssh") == "" and m1.get("letter") == "", (st, out, m1))
for label, nv in (("an empty name", ""), ("a name of spaces", "   ")):
    st, out = SVC.post("box-far", good([mach("ok"), mach(nv, hostname="")]))
    check(f"7 {label} is still refused with a hostname of \"\" beside it", st == 400 and one_line(out["error"]) and out["error"].startswith("machines[1].name"), (st, out))
five = [mach("m0"), mach("m1"), mach("m2"), mach("m3"), mach("retired-box", hostname="", ssh="", letter=None, addresses=[], roles=[], retired=True, sources=[])]
st, out = SVC.post("box-far", good(five))
lm = SVC.last_machines()
check("7 a retired machine with hostname \"\" and ssh \"\" in a list of five is accepted and read back by last_machines()",
      st == 200 and out == {"ok": True, "machines": 5} and lm is not None and len(lm[0]["machines"]) == 5 and lm[0]["machines"][4]["name"] == "retired-box" and lm[0]["machines"][4]["hostname"] == "" and lm[0]["machines"][4]["ssh"] == "" and lm[0]["machines"][4]["retired"] is True, (st, out, lm))
st, out = SVC.post("box-far", good([mach("ok"), mach("two"), mach("OK")]))
check("7 a repeated name is refused with one line naming both positions", st == 400 and one_line(out["error"]) and "machines[2].name" in out["error"] and "machines[0].name" in out["error"], (st, out))
st, out = SVC.post("box-far", good([mach("x", letter=None, ssh=None, hostname=None), mach("y", letter="\u0301", ssh="\u0301")]))
check("7 `letter` and `ssh` are not held to the rule (only name and hostname are)", st == 200, (st, out))

# ================================================================ 8. durability: the file is flushed before the rename and the folder after it
events = []
real_fsync, real_replace2 = os.fsync, os.replace
sizes_at_fsync = []
def _fs(fd):
    isdir = _stat.S_ISDIR(os.fstat(fd).st_mode); events.append("fsync-dir" if isdir else "fsync-file")
    if not isdir: sizes_at_fsync.append(os.fstat(fd).st_size)      # what the kernel has been handed when the file is flushed: all of it, not what is still in the writer's buffer
    return real_fsync(fd)
def _rp(src, dst, *a, **k):
    events.append("replace"); return real_replace2(src, dst, *a, **k)
SVC.os.fsync, SVC.os.replace = _fs, _rp
try: st, out = SVC.post("box-far", good([mach("durable")]))
finally: SVC.os.fsync, SVC.os.replace = real_fsync, real_replace2
check("8 a good post flushes the temporary file, then renames it, then flushes the folder (in that order, once each)", st == 200 and events == ["fsync-file", "replace", "fsync-dir"], (st, events))
check("8 …and the file is flushed after the whole list was written to it (its buffer emptied first)", sizes_at_fsync == [len(stored())] and len(stored()) > 0, (sizes_at_fsync, len(stored())))
real_open = os.open
def _open_no_dir(pth, flags, *a, **k):
    if flags & os.O_DIRECTORY: raise OSError(13, "cannot open the folder")
    return real_open(pth, flags, *a, **k)
SVC.os.open = _open_no_dir
try: st, out = SVC.post("box-far", good([mach("no-dir-open")]))
finally: SVC.os.open = real_open
check("8 a folder that cannot be opened for flushing is no failure either: 200, the list is in place", st == 200 and SVC.last_machines()[0]["machines"][0]["name"] == "no-dir-open", (st, out))
def _fs_fail(fd):
    if _stat.S_ISDIR(os.fstat(fd).st_mode): raise OSError(22, "not supported")
    return real_fsync(fd)
SVC.os.fsync = _fs_fail
try: st, out = SVC.post("box-far", good([mach("no-dir-sync")]))
finally: SVC.os.fsync = real_fsync
check("8 a folder that cannot be flushed is no failure: the list is in place and the post is 200", st == 200 and SVC.last_machines()[0]["machines"][0]["name"] == "no-dir-sync", (st, out))
def _fs_file_fail(fd):
    if not _stat.S_ISDIR(os.fstat(fd).st_mode): raise OSError(5, "io error")
    return real_fsync(fd)
keep10 = stored(); SVC.os.fsync = _fs_file_fail
try: st, out = SVC.post("box-far", good([mach("file-sync-fails")]))
finally: SVC.os.fsync = real_fsync
check("8 a temporary file that cannot be flushed is a failed write: 503, the last list stays and no temporary file is left", st == 503 and stored() == keep10 and leftovers() == [], (st, out, leftovers()))

# ================================================================ 9. `last_machines()` never blocks and never reads without a bound
SVC.post("box-far", good([mach("fifo-base")])); good_bytes = stored()
def _timed(fn, secs=5.0):
    box = []
    th = threading.Thread(target=lambda: box.append(fn()), daemon=True); th.start(); th.join(secs)
    return (not th.is_alive()), (box[0] if box else None)
def _release_pipe():        # a writer opening the pipe lets a reader stuck in its open() return, so the test can finish
    try: os.close(os.open(FILE, os.O_WRONLY | os.O_NONBLOCK))
    except OSError: pass
FILE.unlink(); os.mkfifo(FILE)
done, r = _timed(SVC.last_machines)
if not done: _release_pipe()
check("9 a pipe at the store's path reads as None at once (no block, with a 5 s limit)", done and r is None, (done, r))
done, r = _timed(lambda: SVC.post("box-far", good([mach("over-fifo")])))
if not done: _release_pipe()
check("9 a post with a pipe at the store's path does not block either (the list replaces the pipe)", done and r is not None and r[0] == 200 and SVC.last_machines() is not None, (done, r))
SVC.post("box-far", good([mach("cap")])); whole = loaded(); head = json.dumps(whole).encode()
def _padded(n): return head + b" " * (n - len(head))
FILE.write_bytes(_padded(SVC.READ_MAX))
check("9 a file of exactly READ_MAX bytes (the body cap and a margin) is still read", SVC.READ_MAX > SVC.MAX_BYTES and SVC.last_machines() is not None, SVC.READ_MAX)
FILE.write_bytes(_padded(SVC.READ_MAX + 1))
check("9 a file one byte over READ_MAX reads as None though its JSON is a whole list", SVC.last_machines() is None)
FILE.write_bytes(_padded(60 * 1024 * 1024))
t_ = time.time(); r = SVC.last_machines()
check("9 a 60 MB file reads as None, without being read in", r is None and time.time() - t_ < 2, time.time() - t_)
reads = []; real_read, real_fstat = os.read, os.fstat
class _Lie:        # a size check that answers "small": the file grew after it, so the read itself must stop at the bound
    st_mode = _stat.S_IFREG | 0o600; st_size = 10
def _spy_read(fd, n): reads.append(n); return real_read(fd, n)
FILE.write_bytes(_padded(SVC.READ_MAX + 5000)); SVC.os.read = _spy_read; SVC.os.fstat = lambda fd: _Lie()
try: r = SVC.last_machines()
finally: SVC.os.read, SVC.os.fstat = real_read, real_fstat
check("9 …a file that grew after the size check is read no further than READ_MAX + 1 bytes in all, and is None", r is None and reads and sum(reads) <= SVC.READ_MAX + 1, (r, len(reads), sum(reads), SVC.READ_MAX))
class _NotRegular:      # a size check that answers "a device, size 0": only a regular file is read
    st_mode = _stat.S_IFCHR | 0o600; st_size = 0
FILE.write_bytes(good_bytes); reads = []; SVC.os.read = _spy_read; SVC.os.fstat = lambda fd: _NotRegular()
try: r = SVC.last_machines()
finally: SVC.os.read, SVC.os.fstat = real_read, real_fstat
check("9 a file that is no regular file (a device, by its mode) is not read: None, and no byte read", r is None and not reads, (r, reads))
FILE.write_bytes(_padded(SVC.READ_MAX + 5000)); reads = []; SVC.os.read = _spy_read
try: r = SVC.last_machines()
finally: SVC.os.read = real_read
check("9 a file whose size is over the bound is not read at all: None, and no byte read", r is None and not reads, (r, reads))
flags_seen = []
def _open_spy(pth, flags, *a, **k):
    if str(pth) == str(FILE): flags_seen.append(flags)
    return real_open(pth, flags, *a, **k)
SVC.os.open = _open_spy
try: SVC.last_machines()
finally: SVC.os.open = real_open
want_flags = os.O_NONBLOCK | os.O_NOFOLLOW | os.O_NOCTTY
check("9 the file is opened without blocking, without following a link and without taking a terminal (O_NONBLOCK, O_NOFOLLOW, O_NOCTTY)", len(flags_seen) == 1 and flags_seen[0] & want_flags == want_flags, flags_seen)
FILE.unlink(); target = T / "link-target.json"; target.write_bytes(good_bytes); FILE.symlink_to(target)
check("9 a link at the store's path is not followed: None", SVC.last_machines() is None)
FILE.unlink(); target.unlink()
FILE.write_bytes(good_bytes)
check("9 …and the whole file reads back", SVC.last_machines() is not None and SVC.last_machines()[0]["machines"][0]["name"] == "fifo-base")
FILE.unlink()

# ================================================================ 10. over HTTP
from starlette.testclient import TestClient
tok = open(client.mint("box-far")).read().strip()
H = {"Authorization": "Bearer " + tok}; JH = H | {"Content-Type": "application/json"}
SVC.post("box-far", good([mach("keeper")])); keep = stored()
app = server.mcp.http_app()
answers = []
class _J:      # what client_api.json is while a post runs: loads counts the size of every text handed to it
    sizes = []
    def loads(self, s, *a, **k): self.sizes.append(len(s)); return json.loads(s, *a, **k)
    def __getattr__(self, n): return getattr(json, n)
J = _J(); real_json, real_validate = client_api.json, SVC.validate; validated = []
def counting_validate(body, *a, **k): validated.append(1); return real_validate(body, *a, **k)
with TestClient(app) as c:
    def post(path="/client/machines", **kw):
        r = c.post(path, **kw); answers.append(r.text); return r
    r = post(json=good([mach("x")]))
    check("10 no token → 401, nothing stored", r.status_code == 401 and stored() == keep, (r.status_code, r.text[:80]))
    r = post(json=good([mach("x")]), headers={"Authorization": "Bearer " + "x" * 43})
    check("10 a wrong token → 401, nothing stored", r.status_code == 401 and stored() == keep, (r.status_code, r.text[:80]))
    r = post(json=good([mach("web-one"), mach("web-two", retired=True)]), headers=H)
    lst, received = SVC.last_machines()
    check("10 a machine token stores the list and answers 200 {ok, machines}, posted_by is the machine the token proves", r.status_code == 200 and r.json() == {"ok": True, "machines": 2} and lst["posted_by"] == "box-far" and [m["name"] for m in lst["machines"]] == ["web-one", "web-two"], (r.status_code, r.text[:200], lst))
    keep = stored()
    r = post(json=good([mach("n" * 81)]), headers=H)
    check("10 a refused body is 400 with the reason, and the old list stays", r.status_code == 400 and "name" in r.json()["error"] and stored() == keep, (r.status_code, r.text[:200]))
    for label, kw in (("a list", {"json": [1, 2]}), ("a string", {"json": "x"}), ("text that is no JSON", {"content": b"not json", "headers": JH}), ("bytes that are no UTF-8", {"content": b"\xff\xfe{", "headers": JH}), ("an empty body", {"content": b"", "headers": JH}),
                      ("a nesting too deep", {"content": b"[" * 200000, "headers": JH})):
        r = post(**({"headers": H} | kw))
        check(f"10 {label} is 400, never a 500, and the old list stays", r.status_code == 400 and one_line(r.json().get("error")) and stored() == keep, (r.status_code, r.text[:200]))
    r = post(json={"schema": 1}, headers=H)
    check("10 a body with no written or machines is 400, the old list stays", r.status_code == 400 and stored() == keep, (r.status_code, r.text[:200]))
    def sized(n):      # a valid body of exactly n bytes: a good list padded with spaces after the JSON
        b_ = json.dumps(good([mach("padded")])).encode(); assert len(b_) < n; return b_ + b" " * (n - len(b_))
    r = post(content=sized(SVC.MAX_BYTES), headers=JH)
    check("10 a body of exactly 1,000,000 bytes is stored (200)", SVC.MAX_BYTES == 1_000_000 and r.status_code == 200 and SVC.last_machines()[0]["machines"][0]["name"] == "padded", (r.status_code, r.text[:200]))
    SVC.post("box-far", good([mach("keeper")])); keep = stored()
    client_api.json = J; SVC.validate = counting_validate
    try:
        J.sizes.clear(); validated.clear()
        r = post(content=sized(SVC.MAX_BYTES + 1), headers=JH)
        check("10 a body of 1,000,001 bytes is 413 naming the limit, the old list stays, and the body was never parsed or validated", r.status_code == 413 and str(SVC.MAX_BYTES) in r.json()["error"] and one_line(r.json()["error"]) and stored() == keep and not validated and max([0] + J.sizes) < 100000, (r.status_code, r.text[:200], validated, J.sizes))
        J.sizes.clear(); validated.clear()
        r = post(content=sized(SVC.MAX_BYTES + 1), headers=JH | {"Content-Length": "10"})
        check("10 a Content-Length that understates the body (10 for 1,000,001 bytes) does not get it past the cap: 413, old list stays, never parsed", r.status_code == 413 and stored() == keep and not validated and max([0] + J.sizes) < 100000, (r.status_code, r.text[:200], validated, J.sizes))
        J.sizes.clear(); validated.clear()
        r = post(content=b"x" * (3 * SVC.MAX_BYTES), headers=JH | {"Content-Length": "abc"})
        check("10 a Content-Length that is no number does not get a 3 MB body past the cap: 413, old list stays, never parsed", r.status_code == 413 and stored() == keep and not validated and max([0] + J.sizes) < 100000, (r.status_code, r.text[:200], validated, J.sizes))
        J.sizes.clear(); validated.clear()
        r = post(content=(b"x" * 65536 for _ in range(40)), headers=JH)
        check("10 a body with no length (sent in chunks) over the cap is 413, old list stays, never parsed", r.status_code == 413 and stored() == keep and not validated and max([0] + J.sizes) < 100000, (r.status_code, r.text[:200], validated, J.sizes))
        J.sizes.clear(); validated.clear()
        r = post(content=json.dumps(good([mach("small")])).encode(), headers=JH | {"Content-Length": str(10 * SVC.MAX_BYTES)})
        check("10 a declared length over the cap is refused before the body is read (413) even when the body sent is small", r.status_code == 413 and stored() == keep and not validated and max([0] + J.sizes) < 100000, (r.status_code, r.text[:200], validated, J.sizes))
    finally: client_api.json = real_json; SVC.validate = real_validate
    check("10 …and no temporary file is left in the state folder by any of the refusals", not [n for n in leftovers() if n.endswith(".tmp")], leftovers())
    r = post("/client/no-such-verb", json={}, headers=H)
    check("10 the answer to an unknown verb names `machines` among the writes", r.status_code == 404 and "machines" in r.json()["error"], (r.status_code, r.text[:200]))
    r = post(json=good([mach("x")]), headers={"Authorization": "Bearer ssp_" + "a" * 43})
    check("10 a caller's pass (not a machine token) does not open the route: refused, nothing stored", r.status_code in (401, 403) and stored() == keep, (r.status_code, r.text[:120]))
    # a live pass (a trade of a caller's own key) opens only the New session form's calls: stubbed the way the pass verification is stubbed elsewhere (a request's bearer is a pass or it is not)
    PASS_TOK = "ssp_" + "L" * 43
    real_pass_machine = client_api._caller_pass.pass_machine
    client_api._caller_pass.pass_machine = lambda auth: "pass:abcd1234abcd1234" if auth == "Bearer " + PASS_TOK else ""
    try:
        keep = stored()
        r = post(json=good([mach("by-pass")]), headers={"Authorization": "Bearer " + PASS_TOK})
        check("10 a LIVE pass does not open /client/machines: exactly 403, nothing stored", r.status_code == 403 and stored() == keep, (r.status_code, r.text[:160]))
        r = post(content=b"x" * 3000, headers={"Authorization": "Bearer " + PASS_TOK})
        check("10 …whatever the body (even one that is no JSON): 403, nothing stored", r.status_code == 403 and stored() == keep, (r.status_code, r.text[:160]))
        r = post("/client/agent-state", json={"schema": 1}, headers={"Authorization": "Bearer " + PASS_TOK})
        check("10 …and the same for the other capped write, /client/agent-state: 403", r.status_code == 403, (r.status_code, r.text[:160]))
        r = post("/client/project-agent", json={}, headers={"Authorization": "Bearer " + PASS_TOK})
        check("10 …while the stub is live: a verb a pass does open is not refused as a pass (so the 403 above is the route's own)", r.status_code not in (401, 403), (r.status_code, r.text[:160]))
    finally: client_api._caller_pass.pass_machine = real_pass_machine
    check("10 the pass verbs do not name machines", "machines" not in client_api._PASS_VERBS and "agent-state" not in client_api._PASS_VERBS)

    # ---- one reason for each kind of unreadable body
    SVC.post("box-far", good([mach("keeper")])); keep = stored()
    OBJ = "the body is a JSON object, not a list, text, number, true, false or null"
    NEST, DIG = client_api._NEST_MAX, client_api._DIGITS_MAX
    def nested(n): return b'{"a":' * (n - 1) + b"{}" + b"}" * (n - 1)      # objects n levels deep: n brackets open at the deepest point
    def reason(**kw):
        r = post(**({"headers": H} | kw)); return r.status_code, (r.json().get("error") if r.headers.get("content-type", "").startswith("application/json") else r.text)
    cases = {
        "text that is no JSON": (dict(content=b"not json", headers=JH), "the body is not valid JSON"),
        "an empty body": (dict(content=b"", headers=JH), "the body is not valid JSON"),
        "a torn object": (dict(content=b'{"schema": 1, "writ', headers=JH), "the body is not valid JSON"),
        "bytes that are no UTF-8": (dict(content=b'{"a": "\xff\xfe"}', headers=JH), "the body is not valid JSON"),
        "a list": (dict(json=[1, 2]), OBJ), "a string": (dict(json="x"), OBJ), "a number": (dict(content=b"5", headers=JH), OBJ), "null": (dict(content=b"null", headers=JH), OBJ), "true": (dict(content=b"true", headers=JH), OBJ),
        "a nesting too deep": (dict(content=b"[" * 200000, headers=JH), "the JSON nests too deeply to read"),
        "an object nested too deep": (dict(content=b'{"a":' * 100000 + b"1" + b"}" * 100000, headers=JH), "the JSON nests too deeply to read"),
        "an object nested one level over the bound": (dict(content=nested(NEST + 1), headers=JH), "the JSON nests too deeply to read"),
        "a list nested one level over the bound": (dict(content=b'{"x":' + b"[" * NEST + b"]" * NEST + b"}", headers=JH), "the JSON nests too deeply to read"),
        "a nesting past the bound that never closes": (dict(content=b'{"a":' * (NEST + 1), headers=JH), "the JSON nests too deeply to read"),
        "an integer of too many digits": (dict(content=b'{"schema": 1, "written": ' + b"1" * 5000 + b', "machines": []}', headers=JH), "a number in the JSON has too many digits"),
        "an integer one digit over the bound": (dict(content=b'{"x": ' + b"1" * (DIG + 1) + b"}", headers=JH), "a number in the JSON has too many digits"),
        "a fraction of too many digits": (dict(content=b'{"x": 0.' + b"1" * 5000 + b"}", headers=JH), "a number in the JSON has too many digits"),
        "a number of too many digits in a list": (dict(content=b'{"x": [' + b"1" * (DIG + 1) + b"]}", headers=JH), "a number in the JSON has too many digits"),
    }
    got_ = {k: reason(**kw) for k, (kw, _) in cases.items()}
    check("10 each unreadable body is 400 with its own one-line reason: invalid JSON, not an object, nested too deep, too many digits", all(got_[k] == (400, want) for k, (_, want) in cases.items()) and stored() == keep, {k: v for k, v in got_.items() if v != (400, cases[k][1])})
    check("10 …four different reasons in all", len({v[1] for v in got_.values()}) == 4 and OBJ == SVC.NOT_OBJECT, {v[1] for v in got_.values()})
    # nesting and digits are judged by a scan of the bytes, so the answer is the same whatever the interpreter's recursion limit, stack or integer-conversion limit
    check("10 the bounds are small and fixed: 64 brackets open at once, 64 digits in a run", (NEST, DIG) == (64, 64))
    r_at = reason(content=nested(NEST), headers=JH)
    check("10 an object nested exactly at the bound is read: it is refused for what it lacks (the schema), not for its depth", r_at[0] == 400 and r_at[1].startswith("schema = 1"), r_at)
    r_dig = reason(content=b'{"x": ' + b"1" * DIG + b"}", headers=JH)
    check("10 a number of exactly the digit bound is read: refused for the missing schema, not for its digits", r_dig[0] == 400 and r_dig[1].startswith("schema = 1"), r_dig)
    class _Counting:      # the parser behind client_api.json: records every call
        calls = []
        def loads(self, s, *a, **k):
            if isinstance(s, bytes): self.calls.append(len(s))      # a body (the token file is read as text)
            return json.loads(s, *a, **k)
        def __getattr__(self, n): return getattr(json, n)
    CJ = _Counting(); client_api.json = CJ
    try:
        for label, kw in (("a nesting one over the bound", nested(NEST + 1)), ("a nesting of 100000", b'{"a":' * 100000 + b"1" + b"}" * 100000), ("a number one digit over the bound", b'{"x": ' + b"1" * (DIG + 1) + b"}")):
            CJ.calls.clear(); rr = reason(content=kw, headers=JH)
            check(f"10 {label}: refused before the parser is called, so no limit of the interpreter decides it", rr[0] == 400 and rr[1] in ("the JSON nests too deeply to read", "a number in the JSON has too many digits") and not CJ.calls, (rr, CJ.calls))
        CJ.calls.clear(); rr = reason(content=nested(NEST), headers=JH)
        check("10 …while a body at the bounds does reach the parser", CJ.calls == [len(nested(NEST))], (rr, CJ.calls))
    finally: client_api.json = real_json
    class _Raises:      # a parser that gives up by its own limits: the same reasons
        def __init__(self, exc): self.exc = exc
        def loads(self, s, *a, **k):
            if isinstance(s, bytes): raise self.exc
            return json.loads(s, *a, **k)
        def __getattr__(self, n): return getattr(json, n)
    for label, exc, want in (("a recursion limit", RecursionError("deep"), "the JSON nests too deeply to read"), ("memory", MemoryError(), "the JSON nests too deeply to read"), ("the integer-digit limit", ValueError("Exceeds the limit (4300 digits) for integer string conversion"), "a number in the JSON has too many digits")):
        client_api.json = _Raises(exc)
        try: rr = reason(content=b'{"schema": 1}', headers=JH)
        finally: client_api.json = real_json
        check(f"10 a parser that stops at {label} gives the same one-line reason", rr == (400, want) and stored() == keep, rr)
    pad = ",".join(["[]"] * 1000)          # many lists that open and close one after the other: the depth is what is open at once
    ok_body = json.dumps(good([mach('"' + "[" * 70, ssh="1" * 70), mach("{" * 70, hostname="[" * 70)]))      # a name that starts with a quote (written as an escaped quote) and holds 70 brackets
    ok_body = ok_body[:-1] + ', "x": [' + pad + '], "y": {"z": ' + "1" * DIG + "}}"
    rr = reason(content=ok_body.encode(), headers=JH)
    check("10 brackets and digits inside strings are not counted (an escaped quote does not end a string), nor are lists that close before the next opens: the body is stored (200)",
          rr[0] == 200 and SVC.last_machines()[0]["machines"][0]["name"] == '"' + "[" * 70 and SVC.last_machines()[0]["machines"][1]["hostname"] == "[" * 70, (rr, SVC.last_machines()))
    SVC.post("box-far", good([mach("keeper")])); keep = stored()
    # ---- an unterminated string is no JSON, and what is inside it is never counted: brackets and digits in it do not give the nesting or digits reason
    for label, body_ in (("100 brackets", b'{"a": "' + b"[" * 100), ("100 digits", b'{"a": "' + b"1" * 100), ("70 braces and a lone backslash at the end", b'{"a": "' + b"{" * 70 + b"\\"), ("escaped quotes only", b'{"a": "' + b'\\"' * 100)):
        check(f"10 an unterminated string holding {label} is `the body is not valid JSON`, never the nesting or digits reason", reason(content=body_, headers=JH) == (400, "the body is not valid JSON") and stored() == keep, reason(content=body_, headers=JH))
    # ---- text that is not UTF-8 is no JSON here: the scan reads bytes, so a body the parser would detect as UTF-16 or UTF-32 must not slip past it
    lst_json = json.dumps(good([mach("wide")], written=time.time() - 3))
    for label, enc in (("UTF-16LE", "utf-16-le"), ("UTF-16BE", "utf-16-be"), ("UTF-16 with a BOM", "utf-16"), ("UTF-32LE", "utf-32-le"), ("UTF-32 with a BOM", "utf-32")):
        rr = reason(content=lst_json.encode(enc), headers=JH)
        check(f"10 a list written as {label} is refused: 400 `the body is not valid JSON`, the old list stays", rr == (400, "the body is not valid JSON") and stored() == keep, rr)
    rr = reason(content=lst_json.encode("utf-8"), headers=JH)
    check("10 …the same list as UTF-8 is stored (200)", rr[0] == 200, rr)
    SVC.post("box-far", good([mach("keeper")])); keep = stored()
    rr = reason(content=b'{"schema": 1,\x00 "machines": []}', headers=JH)
    check("10 a NUL byte in the body is refused as no JSON", rr == (400, "the body is not valid JSON") and stored() == keep, rr)
    rr = reason(content=b"\xef\xbb\xbf" + lst_json.encode("utf-8"), headers=JH)
    check("10 a UTF-8 byte order mark before the list is read as before (200)", rr[0] == 200, rr)
    SVC.post("box-far", good([mach("keeper")])); keep = stored()
    # ---- the scan takes time in proportion to the body, whatever its shape: nothing here may back up and retry (an unterminated string of escaped quotes once cost time that grew with the square of the body)
    SCAN = client_api._too_deep_or_long
    SHAPES_ = {
        "an unterminated string of escaped quotes": lambda n: b'"' + b'\\"' * (n // 2),
        "escaped quotes with no opening quote": lambda n: b'\\"' * (n // 2),
        "an unterminated value of escaped quotes": lambda n: b'{"a":"' + b'\\"' * (n // 2),
        "quotes alone": lambda n: b'"' * n, "backslashes alone": lambda n: b"\\" * n, "quote and bracket pairs": lambda n: b'["' * (n // 2),
        "an unterminated string of brackets": lambda n: b'{"a":"' + b"[" * n, "empty strings": lambda n: b'"" ' * (n // 3),
        "runs of 64 digits": lambda n: (b"1" * 64 + b"a") * (n // 65), "bracket pairs": lambda n: b"[]" * (n // 2), "open brackets": lambda n: b"[" * n,
    }
    def best_(raw, tries=3):
        best = 1e9
        for _ in range(tries):
            t0 = time.perf_counter(); SCAN(raw); best = min(best, time.perf_counter() - t0)
            if best > 0.3: break      # far too slow already: no need to measure it again
        return best
    grow_ = {}
    for nm_, mk_ in SHAPES_.items():
        t1_, t2_ = best_(mk_(20_000)), best_(mk_(80_000)); grow_[nm_] = (round(t1_, 4), round(t2_, 4))
    slow_ = {k: v for k, v in grow_.items() if not v[1] < max(8 * v[0], 0.05)}
    check("10 the scan grows in step with the body: for every shape, 4 times the size takes less than 8 times the time (or under 50 ms)", not slow_, slow_)
    if not slow_:
        big_ = {nm_: round(best_(mk_(1_000_000), 2), 3) for nm_, mk_ in SHAPES_.items()}
        check("10 a body of 1,000,000 bytes of any of these shapes is scanned in under 1 second (about 0.05 s on a quiet machine)", all(v < 1.0 for v in big_.values()), big_)
    else:
        check("10 a body of 1,000,000 bytes of any of these shapes is scanned in under 1 second", False, "not measured: the scan does not grow in step with the body")
    if not slow_:      # (a scan that is not linear would take minutes here)
        t0_ = time.perf_counter(); rr = reason(content=b'"' + b'\\"' * 499_999, headers=JH); took_ = time.perf_counter() - t0_
        check("10 over HTTP a body of 999,999 bytes that is one unterminated string of escaped quotes is answered 400 `not valid JSON` in under 2 seconds", rr == (400, "the body is not valid JSON") and took_ < 2.0, (rr, round(took_, 3)))
    else:
        check("10 over HTTP a body of 999,999 bytes that is one unterminated string of escaped quotes is answered 400 in under 2 seconds", False, "not measured: the scan does not grow in step with the body")
    for label, body_ in (("a backslash and a line feed inside a string (the escape takes any character)", b'{"a": "\\\n' + b"[" * 100 + b'"}'), ("digits on both sides of a string (the string keeps them apart)", b'{"a": ' + b"1" * 40 + b'"x"' + b"1" * 40 + b"}"),
                         ("a byte order mark of UTF-16 and no NUL byte", b"\xff\xfe" + b"[" * 100)):
        rr = reason(content=body_, headers=JH)
        check(f"10 {label}: `the body is not valid JSON`", rr == (400, "the body is not valid JSON"), rr)
    # the scan agrees with a plain loop over the bytes on random bodies made of the characters that matter (strings and escapes, brackets, digits)
    def plain_(raw):
        depth = top = run = 0; in_str = esc = digits = False
        for c in raw:
            if in_str:
                if esc: esc = False
                elif c == 92: esc = True
                elif c == 34: in_str = False
                continue
            if c == 34: in_str = True; run = 0
            elif c in b"[{": depth += 1; top = max(top, depth); run = 0
            elif c in b"]}": depth -= 1; run = 0
            elif 48 <= c <= 57:
                run += 1; digits = digits or run > client_api._DIGITS_MAX
            else: run = 0
        return client_api._NEST_REASON if top > client_api._NEST_MAX else (client_api._DIGITS_REASON if digits else "")
    rnd_ = random.Random(20260601); diffs_ = []
    for _ in range(4000):
        raw_ = "".join(rnd_.choice('"\\[]{}12a \n') * rnd_.choice([1, 1, 2, 5, 30, 70, 90]) for _ in range(rnd_.randint(1, 12))).encode()
        if SCAN(raw_) != plain_(raw_): diffs_.append(raw_[:60])
    check("10 …on 4000 random bodies the scan gives the answer a plain loop over the bytes gives", not diffs_, diffs_[:3])
    for label, txt in (("1.0", b"1.0"), ("true", b"true"), ("1e0", b"1e0"), ('"1"', b'"1"')):
        r = post(content=b'{"schema": ' + txt + b', "written": ' + str(time.time() - 30).encode() + b', "machines": [{"name": "s", "retired": false}]}', headers=JH)
        check(f"10 a schema written as {txt.decode()} is not the JSON number 1: 400 naming schema, the old list stays", r.status_code == 400 and r.json()["error"].startswith("schema = 1") and stored() == keep, (r.status_code, r.text[:160]))
    body_ok = json.dumps(good([mach("no-ctype")])).encode()
    r = post(content=body_ok, headers=H); ok1 = (r.status_code, r.request.headers.get("content-type"))
    r2 = post(content=body_ok, headers=H | {"Content-Type": "text/plain"})
    check("10 no Content-Type is asked for: a body with none, or with text/plain, is stored (200)", ok1[0] == 200 and ok1[1] is None and r2.status_code == 200, (ok1, r2.status_code))
    r = post(content=json.dumps(good([mach("a")], written=time.time() - 10)).encode(), headers=H)
    r_old = post(content=json.dumps(good([mach("b")], written=time.time() - 2000)).encode(), headers=H)
    check("10 over HTTP a list of an older `written` is kept out: 200 {ok, kept: newer}, the stored list stays", r_old.status_code == 200 and r_old.json() == {"ok": True, "kept": "newer"} and SVC.last_machines()[0]["machines"][0]["name"] == "a", (r_old.status_code, r_old.text))
    FILE.unlink(missing_ok=True); Wh = time.time() - 5; outs_ = []
    for off in (0, -300, -600, -900, -1200):
        rr = post(content=json.dumps(good([mach(f"h{off}")], written=Wh + off)).encode(), headers=JH); outs_.append((rr.status_code, rr.json()))
    check("10 over HTTP five posts newest first, each 300 s older than the last: two stored, three kept out; the stored list ends no more than 300 s older than the newest, and the mark is the newest",
          outs_ == [(200, {"ok": True, "machines": 1}), (200, {"ok": True, "machines": 1})] + [(200, {"ok": True, "kept": "newer"})] * 3 and SVC.last_machines()[0]["machines"][0]["name"] == "h-300" and loaded()["high"] == Wh, (outs_, loaded() and loaded().get("high")))

    # ---- a sender that goes away in the middle of its body: nothing parsed, nothing written, no traceback
    import asyncio
    from starlette.requests import Request as _Req
    SVC.post("box-far", good([mach("keeper")])); keep = stored()
    class _Cap(logging.Handler):
        def __init__(self): super().__init__(logging.DEBUG); self.recs = []
        def emit(self, rec): self.recs.append(rec)
    def dropped(what, chunks):
        msgs = [{"type": "http.request", "body": c, "more_body": True} for c in chunks] + [{"type": "http.disconnect"}]
        it = iter(msgs)
        async def receive(): return next(it, {"type": "http.disconnect"})
        scope = {"type": "http", "method": "POST", "path": "/client/" + what, "raw_path": ("/client/" + what).encode(), "headers": [(b"authorization", b"Bearer " + tok.encode()), (b"content-type", b"application/json")],
                 "path_params": {"what": what}, "query_string": b"", "client": ("127.0.0.1", 5000), "server": ("testserver", 80), "scheme": "http", "http_version": "1.1", "root_path": ""}
        cap = _Cap(); root = logging.getLogger(); root.addHandler(cap)
        try:
            try: resp = asyncio.run(client_api.client_write(_Req(scope, receive)))
            except BaseException as e_: return f"raised {e_!r}", cap.recs
        finally: root.removeHandler(cap)
        return resp, cap.recs
    for what, chunks in (("machines", []), ("machines", [b'{"schema": 1, "written": ', b"1700000000"]), ("agent-state", [b'{"schema": 1, "agents":'])):
        validated.clear(); SVC.validate = counting_validate
        try: resp, recs = dropped(what, chunks)
        finally: SVC.validate = real_validate
        check(f"10 a sender gone mid-body ({what}, {len(chunks)} chunks read): the route answers quietly with a 400, nothing is parsed or validated and nothing is written", not isinstance(resp, str) and resp.status_code == 400 and not validated and stored() == keep and not (STATE / "agent-state.json").exists(), (resp, validated))
        check(f"10 …and the log holds no traceback and no error line for it ({what})", not [x for x in recs if x.exc_info or x.levelno >= logging.WARNING], [(x.levelname, x.getMessage()[:80]) for x in recs])

# ================================================================ 12. the four optional readings of a machine: online, last_seen, versions, checked
BASE_KEYS = ["name", "hostname", "letter", "ssh", "addresses", "roles", "retired", "sources"]
def last_row(i=0): return SVC.last_machines()[0]["machines"][i]
def drop_of(row_over, **top):
    """Post one machine with the given extra keys: (status, answer, the stored row)."""
    st, ans = SVC.post("box-far", good([mach("demo-a", **row_over)], **top))
    return st, ans, (last_row() if st == 200 else None)
FILE.unlink(missing_ok=True)
# ---- an old body (no reading key anywhere) is stored exactly as before: the same keys in the same order, the same answer, no `dropped`
W0 = time.time() - 40
old_body = good([mach("demo-a"), mach("demo-b", hostname=None, letter=None, ssh=None, addresses=[], roles=[], retired=True, sources=[])], written=W0, not_read=["x.json"])
st, ans = SVC.post("box-far", old_body); raw_old = stored(); rec_old = loaded()
check("12 an old body (none of the four keys) answers exactly {ok, machines} and has no `dropped`", (st, ans) == (200, {"ok": True, "machines": 2}), (st, ans))
check("12 …its stored rows hold exactly the eight old keys in the old order, nothing else", [list(m) for m in rec_old["machines"]] == [BASE_KEYS, BASE_KEYS] and set(rec_old) == {"schema", "written", "received", "posted_by", "high", "machines", "not_read"}, rec_old)
legacy = json.dumps({"schema": 1, "written": W0, "received": rec_old["received"], "posted_by": "box-far", "high": W0, "machines": [{k: m[k] for k in BASE_KEYS} for m in old_body["machines"]], "not_read": ["x.json"]}, ensure_ascii=False, separators=(",", ":")).encode()
check("12 …and the stored file is byte for byte what the code before these keys wrote", raw_old == legacy, (raw_old[:300], legacy[:300]))
# ---- all four stored, in order, after `sources`
RD = {"online": True, "last_seen": None, "versions": {"cli": "1.2.3", "manager": "a1b2c3d"}, "checked": W0}
st, ans, row = drop_of(dict(RD), written=W0)
check("12 the four readings are stored with the row, after `sources`, in the order online, last_seen, versions, checked, and the answer has no `dropped`", st == 200 and ans == {"ok": True, "machines": 1} and list(row) == BASE_KEYS + ["online", "last_seen", "versions", "checked"] and {k: row[k] for k in RD} == RD, (st, ans, row))
st, ans, row = drop_of({"online": False, "last_seen": 1_700_000_000.5, "versions": {}, "checked": 1_700_000_100})
check("12 offline with a last_seen, versions {} and an integer checked are stored as they are (a float stays a float, {} stays {})", st == 200 and (row["online"], row["last_seen"], row["versions"], row["checked"]) == (False, 1_700_000_000.5, {}, 1_700_000_100), row)
# ---- absent, null and {} are three different stored things
st, ans, row = drop_of({})
check("12 absent keys: not stored at all (unknown)", st == 200 and not (set(row) & set(SVC.READING_KEYS)), row)
st, ans, row = drop_of({"online": None, "last_seen": None, "versions": None, "checked": None})
check("12 null keys: stored as null (unknown), nothing dropped", st == 200 and "dropped" not in ans and (row["online"], row["last_seen"], row["versions"], row["checked"]) == (None, None, None, None), (ans, row))
st, ans, row = drop_of({"versions": {}})
check("12 `versions` of {}: stored as {} (the sender read nothing), not as null", st == 200 and row["versions"] == {} and row["versions"] is not None and "dropped" not in ans, row)
# ---- a bad value never refuses the post: it is dropped from its row (stored as unknown), the rest of the row is kept, the answer names it
HUGE_N = 10 ** 400; SURR = json.loads('"\\ud800"'); V17 = {f"k{i}": "v" for i in range(17)}
bad_reading = {
    "online as text": ("online", "yes"), "online as 1": ("online", 1), "online as 0": ("online", 0), "online as a list": ("online", []), "online as an object": ("online", {}),
    "last_seen as text": ("last_seen", "now"), "last_seen as true": ("last_seen", True), "last_seen negative": ("last_seen", -1), "last_seen nan": ("last_seen", float("nan")), "last_seen inf": ("last_seen", float("inf")),
    "last_seen past 1e12": ("last_seen", 1e12 + 1), "last_seen a huge integer": ("last_seen", HUGE_N), "last_seen a list": ("last_seen", [1]),
    "checked as text": ("checked", "2026-11-25"), "checked as false": ("checked", False), "checked negative": ("checked", -0.5), "checked nan": ("checked", float("nan")), "checked past 1e12": ("checked", 5e12), "checked an object": ("checked", {"a": 1}),
    "versions as text": ("versions", "1.0"), "versions as a list": ("versions", ["a"]), "versions as a number": ("versions", 5), "versions as true": ("versions", True),
    "versions of 17 entries": ("versions", V17), "versions with a number value": ("versions", {"a": 1}), "versions with a null value": ("versions", {"a": None}), "versions with a list value": ("versions", {"a": ["x"]}),
    "versions with a value of 201": ("versions", {"a": "v" * 201}), "versions with a key of 65": ("versions", {"k" * 65: "v"}), "versions with an empty key": ("versions", {"": "v"}), "versions with a key of control characters": ("versions", {"\x00​": "v"}),
    "versions with a key that is no text": ("versions", {5: "v"}), "versions with two keys the same once cleaned": ("versions", {"a b": "1", " a​  b ": "2"}), "versions with a lone surrogate value": ("versions", {"a": SURR}), "versions with a lone surrogate key": ("versions", {SURR: "v"}),
    "versions with one bad entry among good ones": ("versions", {"a": "1", "b": "2", "c": 3}),
}
others = {"online": False, "last_seen": 1_700_000_000, "versions": {"cli": "1.2.3"}, "checked": W0}
res12 = {}
for label, (key, val) in bad_reading.items():
    row_over = {k: v for k, v in others.items() if k != key}; row_over[key] = val
    res12[label] = (key, drop_of(row_over, written=W0))
check("12 a bad value in each reading never refuses the post: 200", all(r[1][0] == 200 for r in res12.values()), {k: v[1][:2] for k, v in res12.items() if v[1][0] != 200})
check("12 …the bad key is not stored (it is unknown), and every other key of the row, old and new, is kept as sent", all(key not in r and {k: r[k] for k in others if k != key} == {k: v for k, v in others.items() if k != key} and [r[k] for k in BASE_KEYS] == [mach("demo-a")[k] for k in BASE_KEYS] for key, (_s, _a, r) in res12.values()), {k: v[1][2] for k, v in res12.items() if v[0] in v[1][2]})
check("12 …and the answer names exactly the dropped reading, once, as machines[i].key", all(a.get("dropped") == [f"machines[0].{key}"] and a["ok"] and a["machines"] == 1 for key, (_s, a, _r) in res12.values()), {k: v[1][1] for k, v in res12.items() if v[1][1].get("dropped") != [f"machines[0].{v[0]}"]})
check("12 …a refusal elsewhere in the entry still refuses the body (a bad `retired` beside good readings is 400, the old list stays)", (lambda s_: s_[0] == 400 and "retired" in s_[1]["error"])(SVC.post("box-far", good([mach("demo-a", retired="no", online=True, checked=W0)]))))
# ---- the boundaries are accepted
KEY64, VAL200 = "k" * 64, "v" * 200
st, ans, row = drop_of({"online": False, "last_seen": 0, "versions": {KEY64: VAL200, **{f"e{i}": "" for i in range(15)}}, "checked": 1e12})
check("12 the boundaries are accepted: 16 entries, a key of 64, a value of 200, an empty value, last_seen 0, checked 1e12", st == 200 and "dropped" not in ans and len(row["versions"]) == 16 and row["versions"][KEY64] == VAL200 and row["last_seen"] == 0 and row["checked"] == 1e12 and row["online"] is False, (ans, row))
st, ans, row = drop_of({"versions": {f"e{i}": "v" for i in range(17)}})
check("12 17 `versions` entries are DROPPED whole (not cut to 16): none stored, one `dropped` name", st == 200 and "versions" not in row and ans["dropped"] == ["machines[0].versions"], (ans, row))
# ---- cleaned like every text
st, ans, row = drop_of({"versions": {"c\x00l​i": "1.\x072\n.3 ", "  two   words ": " a\t b "}})
check("12 `versions` keys and values are cleaned like every text (control characters out, white space one space, trimmed)", st == 200 and row["versions"] == {"cli": "1.2 .3", "two words": "a b"}, row)
# ---- several rows, a bounded `dropped`
rows25 = [mach(f"m{i}", online="yes") for i in range(25)]
st, ans = SVC.post("box-far", good(rows25))
check("12 a body with 25 bad readings in 25 rows is stored whole (200); the answer names 20 of them, then how many more", st == 200 and ans["machines"] == 25 and ans["dropped"] == [f"machines[{i}].online" for i in range(20)] + ["and 5 more"], ans)
check("12 …and no row of it holds the bad `online`", all("online" not in m for m in SVC.last_machines()[0]["machines"]))
st, ans = SVC.post("box-far", good([mach("demo-a", online=7, checked="x"), mach("demo-b", versions=V17)]))
check("12 two rows, three bad readings: named in the body's order", ans.get("dropped") == ["machines[0].online", "machines[0].checked", "machines[1].versions"], ans)
# ---- the validator on its own: `dropped` is not part of what is stored
lst_, why_ = SVC.validate(good([mach("demo-a", online="x")]))
check("12 `validate` names the dropped readings and the stored file never holds `dropped`", why_ == "" and lst_["dropped"] == ["machines[0].online"] and b"dropped" not in stored() and SVC.validate(old_body)[0]["dropped"] == [], lst_)

# ---- a real sample body (three machines: online, offline with a last_seen, unknown and retired) replayed through the real route
from stackshot.service import machines_panel as MP
from stackshot.fleet import caller_keys as _KEYS
FILE.unlink(missing_ok=True)
WS = int(time.time()) - 20
sample = {"schema": 1, "written": WS, "not_read": [], "machines": [
    {"name": "demo-a", "hostname": "demo-a.example.net", "letter": "a", "ssh": None, "addresses": ["192.0.2.10"], "roles": ["sala-host", "stackshot-host"], "retired": False, "sources": ["fleet.json"],
     "online": True, "last_seen": None, "versions": {"cli": "2.1.0", "manager": "9f2c1ab"}, "checked": WS},
    {"name": "demo-b", "hostname": "demo-b.example.net", "letter": "b", "ssh": "user@demo-b", "addresses": ["192.0.2.11"], "roles": ["sala-host"], "retired": False, "sources": ["fleet.json"],
     "online": False, "last_seen": WS - 3600, "versions": {}, "checked": WS},
    {"name": "demo-c", "hostname": "", "letter": None, "ssh": None, "addresses": [], "roles": [], "retired": True, "sources": [],
     "online": None, "last_seen": None, "versions": {}, "checked": WS}]}
with TestClient(app) as c2:
    r = c2.post("/client/machines", content=json.dumps(sample).encode(), headers=JH)
    check("12 the sample body through the real route: 200 {ok, machines: 3}, no `dropped`", r.status_code == 200 and r.json() == {"ok": True, "machines": 3}, (r.status_code, r.text[:300]))
    row3 = SVC.last_machines()[0]["machines"]
    check("12 …stored as sent: the posting machine online with its versions, the other offline with its last_seen and no versions read, the third unknown (null) and retired", [(m["online"], m["last_seen"], m["versions"], m["checked"]) for m in row3] == [(True, None, {"cli": "2.1.0", "manager": "9f2c1ab"}, WS), (False, WS - 3600, {}, WS), (None, None, {}, WS)] and row3[2]["retired"] is True, row3)
    # the same body with a bad reading and an old-style row replayed: still 200, and the answer names the one reading
    sample2 = json.loads(json.dumps(sample)); sample2["machines"][1]["online"] = "off"; sample2["machines"][2] = {k: v for k, v in sample2["machines"][2].items() if k not in SVC.READING_KEYS}
    r2 = c2.post("/client/machines", content=json.dumps(sample2).encode(), headers=JH)
    row3b = SVC.last_machines()[0]["machines"]
    check("12 the sample with a bad `online` and one row without readings: 200, the answer names machines[1].online, the row keeps its other readings, the old-style row has none", r2.status_code == 200 and r2.json() == {"ok": True, "machines": 3, "dropped": ["machines[1].online"]} and "online" not in row3b[1] and row3b[1]["last_seen"] == WS - 3600 and not (set(row3b[2]) & set(SVC.READING_KEYS)), (r2.status_code, r2.text, row3b[1]))
    c2.post("/client/machines", content=json.dumps(sample).encode(), headers=JH)
_real_paired = _KEYS.paired; _KEYS.paired = lambda: True
try: view3 = MP.view(time.time())
finally: _KEYS.paired = _real_paired
rep = [m.get("reported") for m in view3["machines"]]
check("12 …and the panel's view of the sample: fresh readings for each machine, as stored (unknown stays None, {} stays {})",
      [(x["online"], x["last_seen"], x["versions"], x["fresh"]) for x in rep] == [(True, None, {"cli": "2.1.0", "manager": "9f2c1ab"}, True), (False, WS - 3600, {}, True), (None, None, {}, True)], rep)

# ================================================================ 11. no secret
check("11 the machine token appears in no answer and not in the stored file", tok not in "\n".join(answers) and tok.encode() not in stored() and tok not in repr(SVC.last_machines()), None)
src = pathlib.Path(STACK, "stackshot", "service", "machines_list.py").read_text(encoding="utf-8")
check("11 the module imports no process, socket or network module", not re.search(r"^\s*(?:import|from)\s+(?:subprocess|socket|urllib|http|requests|paramiko)\b", src, re.M))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
