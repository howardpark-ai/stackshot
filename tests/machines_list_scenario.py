"""Scenario test for the machine list the fleet manager posts (service/machines_list.py `POST /client/machines`, and the route's size cap in web/routes/client_api.py): the sender posts its list of machines, the server
validates it strictly, keeps the last good one in one file in the state folder and reads it back with `last_machines()`. Fixture data in a temporary state folder, no live store, no network, no model call.

  1  the route's module: a good body is stored and read back (cleaned fields only, who posted it, when it was received); a key the module does not know is ignored and never stored; a list left out is empty and a
     role named twice is kept once; text is cleaned (control and format characters out, white space collapsed); the boundary values (200 machines, an 80-character name, 16 addresses of 64 characters, ...) are accepted
  2  each refused body answers 400 with one line of reason and leaves the last good list byte for byte, with no temporary file left: a body that is no object, a wrong schema, a `written` that is not a time (text, true,
     zero, before 2020, more than five minutes ahead, infinite, a huge integer), `machines` that is no list or holds 201, a machine that is no object, a missing, empty, control-only or 81-character name, a text field of
     the wrong kind or too long, addresses, roles, `retired`, `sources` and `not_read` outside their limits, a lone surrogate
  3  a bad post never replaces the last good one: after a run of refused bodies the same list is read back; a read-only standby copy answers 503 and a file that cannot be written answers 503, both keep it
  4  the write is atomic: the temporary file is made in the same folder, mode 0600, and is renamed over the list; no temporary file is left after a good post, a refused one or a failed write; the list is mode 0600 whatever the
     umask (a new file and a replaced one); a stale temporary file of the writer's own name is swept and nothing else is touched; 8 threads posting at once leave a whole list and no reader meets a torn file
  5  `last_machines()` reads a missing file, an empty one, a torn one, one that is no object, another schema, and one with a field of the wrong kind (`machines`, `received`, `written`, `posted_by`, `not_read`) as None,
     and a folder in place of the file; it never raises
  6  over HTTP: no token 401, a wrong token 401, a machine token stores (200), a refused body 400, a body that is no JSON or no object 400, a body of exactly 1,000,000 bytes is stored, one of 1,000,001 is 413; a
     Content-Length that understates the body, one that is no number and a body with no length (chunked) are each cut off at the cap (413) and the body is never parsed or validated; a declared length over the cap is refused before
     the body is read; the old list stays after every refusal; the unknown-verb answer names `machines`
  7  no secret: the machine token appears in no answer and not in the stored file

    tests/run-suite machines_list       -> exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging, stat as _stat, threading
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
check("1 …a key the module does not know (in a machine, at the top) is ignored and never stored", "secret_extra" not in stored().decode() and "top_extra" not in stored().decode() and set(loaded()) == {"schema", "written", "received", "posted_by", "machines", "not_read"}, loaded())
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
edge = good([mach(f"m{i}") for i in range(200)], written=time.time() + 299)
edge["machines"][0] = mach("n" * 80, hostname="h" * 200, letter="l" * 200, ssh="s" * 200, addresses=["a" * 64] * 16, roles=["sala-host", "stackshot-host", "sala-host", "stackshot-host"], sources=["x" * 200] * 20)
edge["not_read"] = ["f" * 200] * 200
st, out = SVC.post("box-far", edge)
check("1 the boundary values are accepted: 200 machines, an 80-character name, 200-character texts, 16 addresses of 64, 4 roles, 20 sources of 200, 200 not-read names of 200, a time 299 s ahead", (st, out) == (200, {"ok": True, "machines": 200}) and len(SVC.last_machines()[0]["machines"]) == 200, (st, out))
check("1 …a time of Jan 1st 2020 is accepted", SVC.post("box-far", good(written=1577836800))[0] == 200)

# ================================================================ 2. every refusal: 400, one line, the last good list stays
SVC.post("box-far", good([mach("keeper")])); keep = stored()
HUGE = 10 ** 400; SUR = json.loads('"\\ud800"')
bad = {
    "a list": [1, 2], "a string": "x", "null": None,
    "another schema": good(schema=2), "a text schema": good(schema="1"), "a true schema": good(schema=True), "no schema": {"written": time.time(), "machines": []},
    "no time": {"schema": 1, "machines": []}, "a time that is text": good(written="now"), "a true time": good(written=True), "a time of zero": good(written=0), "a time before 2020": good(written=1577836799),
    "a negative time": good(written=-5), "a time ten minutes ahead": good(written=time.time() + 600), "an infinite time": good(written=float("inf")), "a nan time": good(written=float("nan")),
    "a time that is a huge integer": good(written=HUGE), "a time past the bound": good(written=2e12), "a time of 1e400": json.loads('{"schema": 1, "written": 1e400, "machines": []}'),
    "machines left out": {"schema": 1, "written": time.time()}, "machines null": good(machines=None) | {"machines": None}, "machines an object": good(machines={}), "machines a string": good(machines="x"),
    "201 machines": good([mach(f"m{i}") for i in range(201)]), "a machine that is no object": good(["box"]), "a machine that is null": good([None]),
    "no name": good([{"retired": False}]), "a name that is a number": good([mach(5)]), "an empty name": good([mach("")]), "a blank name": good([mach("   ")]), "a control-only name": good([mach("\x00\x07\x1b")]),
    "a name of 81 characters": good([mach("n" * 81)]), "a name that is a list": good([mach(["a"])]),
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

# ================================================================ 6. over HTTP
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
    check("6 no token → 401, nothing stored", r.status_code == 401 and stored() == keep, (r.status_code, r.text[:80]))
    r = post(json=good([mach("x")]), headers={"Authorization": "Bearer " + "x" * 43})
    check("6 a wrong token → 401, nothing stored", r.status_code == 401 and stored() == keep, (r.status_code, r.text[:80]))
    r = post(json=good([mach("web-one"), mach("web-two", retired=True)]), headers=H)
    lst, received = SVC.last_machines()
    check("6 a machine token stores the list and answers 200 {ok, machines}, posted_by is the machine the token proves", r.status_code == 200 and r.json() == {"ok": True, "machines": 2} and lst["posted_by"] == "box-far" and [m["name"] for m in lst["machines"]] == ["web-one", "web-two"], (r.status_code, r.text[:200], lst))
    keep = stored()
    r = post(json=good([mach("n" * 81)]), headers=H)
    check("6 a refused body is 400 with the reason, and the old list stays", r.status_code == 400 and "name" in r.json()["error"] and stored() == keep, (r.status_code, r.text[:200]))
    for label, kw in (("a list", {"json": [1, 2]}), ("a string", {"json": "x"}), ("text that is no JSON", {"content": b"not json", "headers": JH}), ("bytes that are no UTF-8", {"content": b"\xff\xfe{", "headers": JH}), ("an empty body", {"content": b"", "headers": JH}),
                      ("a nesting too deep", {"content": b"[" * 200000, "headers": JH})):
        r = post(**({"headers": H} | kw))
        check(f"6 {label} is 400, never a 500, and the old list stays", r.status_code == 400 and one_line(r.json().get("error")) and stored() == keep, (r.status_code, r.text[:200]))
    r = post(json={"schema": 1}, headers=H)
    check("6 a body with no written or machines is 400, the old list stays", r.status_code == 400 and stored() == keep, (r.status_code, r.text[:200]))
    def sized(n):      # a valid body of exactly n bytes: a good list padded with spaces after the JSON
        b_ = json.dumps(good([mach("padded")])).encode(); assert len(b_) < n; return b_ + b" " * (n - len(b_))
    r = post(content=sized(SVC.MAX_BYTES), headers=JH)
    check("6 a body of exactly 1,000,000 bytes is stored (200)", SVC.MAX_BYTES == 1_000_000 and r.status_code == 200 and SVC.last_machines()[0]["machines"][0]["name"] == "padded", (r.status_code, r.text[:200]))
    SVC.post("box-far", good([mach("keeper")])); keep = stored()
    client_api.json = J; SVC.validate = counting_validate
    try:
        J.sizes.clear(); validated.clear()
        r = post(content=sized(SVC.MAX_BYTES + 1), headers=JH)
        check("6 a body of 1,000,001 bytes is 413 naming the limit, the old list stays, and the body was never parsed or validated", r.status_code == 413 and str(SVC.MAX_BYTES) in r.json()["error"] and one_line(r.json()["error"]) and stored() == keep and not validated and max([0] + J.sizes) < 100000, (r.status_code, r.text[:200], validated, J.sizes))
        J.sizes.clear(); validated.clear()
        r = post(content=sized(SVC.MAX_BYTES + 1), headers=JH | {"Content-Length": "10"})
        check("6 a Content-Length that understates the body (10 for 1,000,001 bytes) does not get it past the cap: 413, old list stays, never parsed", r.status_code == 413 and stored() == keep and not validated and max([0] + J.sizes) < 100000, (r.status_code, r.text[:200], validated, J.sizes))
        J.sizes.clear(); validated.clear()
        r = post(content=b"x" * (3 * SVC.MAX_BYTES), headers=JH | {"Content-Length": "abc"})
        check("6 a Content-Length that is no number does not get a 3 MB body past the cap: 413, old list stays, never parsed", r.status_code == 413 and stored() == keep and not validated and max([0] + J.sizes) < 100000, (r.status_code, r.text[:200], validated, J.sizes))
        J.sizes.clear(); validated.clear()
        r = post(content=(b"x" * 65536 for _ in range(40)), headers=JH)
        check("6 a body with no length (sent in chunks) over the cap is 413, old list stays, never parsed", r.status_code == 413 and stored() == keep and not validated and max([0] + J.sizes) < 100000, (r.status_code, r.text[:200], validated, J.sizes))
        J.sizes.clear(); validated.clear()
        r = post(content=json.dumps(good([mach("small")])).encode(), headers=JH | {"Content-Length": str(10 * SVC.MAX_BYTES)})
        check("6 a declared length over the cap is refused before the body is read (413) even when the body sent is small", r.status_code == 413 and stored() == keep and not validated and max([0] + J.sizes) < 100000, (r.status_code, r.text[:200], validated, J.sizes))
    finally: client_api.json = real_json; SVC.validate = real_validate
    check("6 …and no temporary file is left in the state folder by any of the refusals", not [n for n in leftovers() if n.endswith(".tmp")], leftovers())
    r = post("/client/no-such-verb", json={}, headers=H)
    check("6 the answer to an unknown verb names `machines` among the writes", r.status_code == 404 and "machines" in r.json()["error"], (r.status_code, r.text[:200]))
    r = post(json=good([mach("x")]), headers={"Authorization": "Bearer ssp_" + "a" * 43})
    check("6 a caller's pass (not a machine token) does not open the route: refused, nothing stored", r.status_code in (401, 403) and stored() == keep, (r.status_code, r.text[:120]))

# ================================================================ 7. no secret
check("7 the machine token appears in no answer and not in the stored file", tok not in "\n".join(answers) and tok.encode() not in stored() and tok not in repr(SVC.last_machines()), None)
src = pathlib.Path(STACK, "stackshot", "service", "machines_list.py").read_text(encoding="utf-8")
check("7 the module imports no process, socket or network module", not re.search(r"^\s*(?:import|from)\s+(?:subprocess|socket|urllib|http|requests|paramiko)\b", src, re.M))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
