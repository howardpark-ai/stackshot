"""Scenario test for the saved color combinations of the shared color tool (colorcombos.py, the routes block in server.py) — fixture data, the HTTP routes through
Starlette's test client, no live store, no network. People, machines and addresses are made up.

Covers:
  * the store: the 14 keys; validate (a name of 0, 1, 40 and 41 characters, a control, format or line-separator character by Unicode category (a tab, a C1 control, U+2028, a bidi override, a zero-width space) while Japanese and accented names pass, NFC and strip, a duplicate when case is ignored; a value that is `#abc`, `#GGGGGG`,
    six digits without `#`, an alpha form, a functional notation or a named color, 13 and 15 keys, an extra key, capitals lowercased); a save under an existing name replaces it, keeps its id and
    place; delete (an id that is not on the list is no error and writes nothing); the cap of 50 (a new name is refused, a replacement is not); the write is fsynced before os.replace
    and a failed os.replace leaves the old file and no temporary file; a file that does not parse, is not an object or is not text is moved aside to `.bad-<epoch>` and the list
    starts empty (when it cannot be moved aside it stays and is the unreadable case: OSError, the routes' 503, never an empty list a save would write over); an entry that is not a whole combination is left out; a file that cannot be read (a directory in its place, mode 000 when not root) raises OSError and is left as
    it is, for a read, a save and a delete; two threads saving at once lose nothing;
  * the board's routes (GET /colors/combos, POST /colors/combos, POST /colors/combos/delete): 403 without the cookie, with another address's cookie or an expired one (a read too),
    403 from a foreign origin, with no origin or "null", the Referer taken when there is no Origin, 415, 413 (judged from Content-Length before the body is read, and as a body with
    none arrives), 400 for a length that is no number, a body that is not JSON or not an object, and a bad name, value, key or id (`field` names the failing one), 409 when the list is
    full, 503 when the file cannot be read (nothing changed); an answer is `{"combos": [...], "max": 50}` and `no-store`, an error `{"error", "field"}` and `no-store`; `via` is "board";
    a post does not drop the kept home page (/colors/ is not in _UI_WRITES) while a post to /prefs/ does;
  * the machine routes (GET and POST /client/colors/combos, POST /client/colors/combos/delete): 401 without a token or with an unknown one (plain text, as the other /client routes),
    403 for a machine that is not in form_machines (a read too), a write needs `sender` the web form's label that is also in form_senders (400 when it is missing or not one line, 403 for another
    label, another case, or a label not in form_senders), the body's gates (415, 413, 400), the same answers as the board's routes, `via` is the web form's label; the board's cookie does not open
    them and a machine token does not open the board's routes;
  * the same list through both: a combination saved by one path is read by the other, and a save under the same name from the other path replaces it in place;
  * the routes: the six paths are registered once each with the methods meant, and the two-segment `/client/colors/combos` paths are not taken by the single-segment `/client/{what}`
    routes (nor the other way round); a standby copy (STACKSHOT_READ_ONLY, a process of its own) answers every post 503 with the standby sentence, writes nothing, and still reads.

    tests/run-suite color_combos        → exit 0 / 1"""
import asyncio, hashlib, json, logging, os, pathlib, re, shutil, subprocess, sys, threading, time, unicodedata

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
BOARD = "https://board.example.org"
MINA, EVE = "mina@example.org", "eve@example.org"
HOST = "web-box"; OTHER = "other-box"
TOK = {HOST: "w" * 43, OTHER: "o" * 43}


def fixture(root, states=True):
    """The config and the store the server needs, under `root` (the same folder for the standby child)."""
    toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", root), ("store", f"{root}/store"), ("markdown", f"{root}/board.md"), ("brain", f"{root}/brain"),
                     ("state", f"{root}/state"), ("secrets", f"{root}/secrets"), ("project_touch", f"{root}/touch"), ("rules", f"{root}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                     (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                     (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{MINA}"]'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^panel = true', 'panel = false')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    pathlib.Path(root, "stackshot.toml").write_text(toml, encoding="utf-8")
    pathlib.Path(root, "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=f"{root}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{root}/fleet"); os.environ.pop("STACKSHOT_URL", None)


if len(sys.argv) > 2 and sys.argv[1] == "--standby-child":
    # A standby copy (STACKSHOT_READ_ONLY=1) in a process of its own over the folder the parent made. Prints one JSON line of what each request got.
    root = sys.argv[2]
    os.environ["STACKSHOT_READ_ONLY"] = "1"
    os.environ.update(STACKSHOT_CONFIG=f"{root}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{root}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    sys.path.insert(0, STACK); logging.disable(logging.CRITICAL)
    from stackshot.web import server
    from stackshot.core import config as _cfg
    from stackshot.web import app as _wapp
    from stackshot.web.auth import signin as _signin
    from stackshot.web.colorcombos import WEB_LABEL as WL
    from starlette.testclient import TestClient
    _cfg.CFG["project_agent"] = {"form_senders": [WL], "form_machines": [HOST]}
    cookie = _signin._ui_sign(json.dumps({"email": MINA, "exp": time.time() + 3600}))
    VALS = json.loads(sys.argv[3])
    out = {}
    with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
        c.cookies.set(_signin._UI_COOKIE, cookie)
        JH = {"Origin": BOARD, "Content-Type": "application/json"}
        MH = {"Authorization": "Bearer " + TOK[HOST], "Content-Type": "application/json"}
        def row(r): return [r.status_code, r.text[:200], r.headers.get("cache-control")]
        out["get"] = row(c.get("/colors/combos"))
        out["post"] = row(c.post("/colors/combos", content=json.dumps({"name": "x", "values": VALS}), headers=JH))
        out["delete"] = row(c.post("/colors/combos/delete", content=json.dumps({"id": "00000000"}), headers=JH))
        c.cookies.clear()
        out["mget"] = row(c.get("/client/colors/combos", headers=MH))
        out["mpost"] = row(c.post("/client/colors/combos", content=json.dumps({"name": "x", "values": VALS, "sender": WL}), headers=MH))
        out["mdelete"] = row(c.post("/client/colors/combos/delete", content=json.dumps({"id": "00000000", "sender": WL}), headers=MH))
        out["mpost_notoken"] = row(c.post("/client/colors/combos", content=b"{}", headers={"Content-Type": "application/json"}))
    print(json.dumps(out))
    sys.exit(0)

import _scratch
tmp = _scratch.mkdtemp(prefix="colorcombos-"); T = pathlib.Path(tmp)
fixture(tmp)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text("{}")
(T / "store/projects.json").write_text(json.dumps({"pages": {}}))
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
(T / "secrets/clients.json").write_text(json.dumps({m: {"sha256": hashlib.sha256(t.encode()).hexdigest(), "created": "2026-01-01T00:00:00+04:00"} for m, t in TOK.items()}))
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.CRITICAL)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.web import colorcombos as cc
WL = cc.WEB_LABEL         # the label the web form sends: the code's own constant, so this file names none of its own
from stackshot.web import server
from stackshot.core import config as _cfg
from stackshot.web import app as _wapp
from stackshot.web.routes import ui_api as _rt_ui
from stackshot.web.auth import signin as _signin
from starlette.requests import Request
from starlette.testclient import TestClient
FILE = cc.path()
KEYS = ["bg", "card", "fg", "mut", "line", "ibd", "link", "solid", "onsolid", "labbg", "labfg", "labbd", "disbg", "disfg"]
def vals(seed=0):
    return {k: "#{:02x}{:02x}{:02x}".format((i * 17 + seed) % 256, (i * 29 + seed * 3) % 256, (i * 43 + seed * 5) % 256) for i, k in enumerate(KEYS)}
V = vals()
def reset():
    """No file, no temporary file, no directory in its place."""
    if FILE.is_dir(): shutil.rmtree(FILE)
    for f in FILE.parent.glob("color-combos.json*"): f.unlink()
    for f in FILE.parent.glob(".color-combos.json.*"): f.unlink()
def bad_files(): return sorted(FILE.parent.glob("color-combos.json.bad-*"))
def tmp_files(): return sorted(FILE.parent.glob(".color-combos.json.*.tmp"))
def inv(name, values=V):
    try: cc.validate(name, values)
    except cc.Invalid as e: return e.field
    return "ACCEPTED"
def inv_vals(values): return inv("ok", values)

try:
    # ---- 1. the store
    check("the 14 keys, in the order of the design, each once", list(cc.KEYS) == KEYS and len(set(cc.KEYS)) == 14, cc.KEYS)
    check("limits: 50 combinations, 40 characters, 4 KB; the vias are board and the web label", (cc.MAX_COMBOS, cc.NAME_MAX, cc.BODY_MAX) == (50, 40, 4096) and cc.VIAS == ("board", WL))
    check("no file yet: the list is empty, the payload says max 50 and nothing is created", cc.listing() == [] and cc.payload() == {"combos": [], "max": 50} and not FILE.exists())
    n_, v_ = cc.validate("  Dusk  ", {**V, "bg": "#ABCDEF"})
    check("validate: a name is stripped, capitals in a color are lowercased, a good pair is returned whole", n_ == "Dusk" and v_["bg"] == "#abcdef" and list(v_) == KEYS and all(v_[k] == V[k] for k in KEYS[1:]), (n_, v_))
    decomposed = "Café"
    check("validate: a name is NFC (a letter and its accent become one character)", cc.validate(decomposed, V)[0] == "Café" and len(cc.validate(decomposed, V)[0]) == 4)
    check("validate: 40 characters pass, 41 do not; the count is of the NFC form (40 letters with accents, written as 80 code points, pass)",
          inv("a" * 40) == "ACCEPTED" and inv("a" * 41) == "name" and inv("é" * 40) == "ACCEPTED" and inv("é" * 41) == "name")
    check("validate: an empty or blank name is refused (field name)", inv("") == "name" and inv("   ") == "name" and inv("\t\n") == "name")
    check("validate: a control character inside a name (tab, newline, NUL, DEL, ESC) is refused; a name that is not text is refused",
          all(inv(f"a{c}b") == "name" for c in ("\t", "\n", "\x00", "\x7f", "\x1b")) and all(inv(x) == "name" for x in (5, None, ["a"], {"a": 1}, True)))
    # refused by Unicode category (Cc controls incl. C1, Cf format characters incl. zero-width and bidi, Zl, Zp), written as escapes so this file holds none of them
    invisible = {"C1 control": "\x85", "C1 control (padding)": "\x80", "line separator": "\u2028", "paragraph separator": "\u2029", "bidi override": "\u202e", "bidi isolate": "\u2066",
                 "zero-width space": "\u200b", "zero-width joiner": "\u200d", "soft hyphen": "\u00ad", "byte order mark": "\ufeff"}
    got_inv = {k: inv(f"a{c}b") for k, c in invisible.items()}
    check("validate: a C1 control, U+2028 / U+2029, a bidi override or isolate, a zero-width space or joiner, a soft hyphen and a byte order mark inside a name are refused (field name)", set(got_inv.values()) == {"name"}, got_inv)
    check("validate: the same characters alone, or at the end of a name, are refused too (a zero-width space is not stripped as white space)", all(inv(c) == "name" for c in invisible.values()) and inv("ab\u200b") == "name" and inv("\u202eab") == "name")
    check("validate: ordinary Japanese, accented and mixed-script names are still accepted", all(inv(x) == "ACCEPTED" for x in ("暗い夜", "ひらがな 02", "café", "Zoë Müller", "Ñandú", "Ночь", "夜 02", "e\u0301 (combining accent)", "naïve-1")))
    check("validate: Unicode text of other scripts is a name", all(inv(x) == "ACCEPTED" for x in ("暗い夜", "Ночь", "夜 02", "a b-c_d.e")))
    bad_values = {"#abc": "#abc", "#GGGGGG": "#GGGGGG", "no hash": "ec8a47", "five": "#a2345", "seven": "#a234567", "alpha": "#a2345678", "rgb": "rgb(1, 2, 3)", "name": "red",
                  "hsl": "hsl(0 0% 0%)", "space": "#a2345 ", "newline": "#a23456\n", "empty": "", "number": 5, "none": None, "list": ["#a23456"], "bool": True}
    got = {k: inv_vals({**V, "link": v}) for k, v in bad_values.items()}
    check("validate: a value that is not exactly #rrggbb is refused, and field names that key (#abc, #GGGGGG, no #, 5 and 7 and 8 digits, rgb(), a name, a space or newline after, not text)",
          set(got.values()) == {"link"}, got)
    k13 = {k: v for k, v in V.items() if k != "disfg"}; k15 = {**V, "extra": "#0a0a0a"}
    check("validate: 13 keys (the missing one is named), 15 keys (the extra one is named), a wrong key in place of one", inv_vals(k13) == "disfg" and inv_vals(k15) == "extra"
          and inv_vals({**{k: v for k, v in V.items() if k != "bg"}, "Bg": "#0a0a0a"}) == "Bg", (inv_vals(k13), inv_vals(k15)))
    check("validate: values that are not an object, or empty, are refused (field values or the first missing key)", inv_vals(None) == "values" and inv_vals([]) == "values" and inv_vals("x") == "values" and inv_vals({}) == "bg")
    check("validate: the name is judged before the values", inv("", {"bad": 1}) == "name")

    # save, replace, delete
    t0 = int(time.time())
    L = cc.save("Dusk", V, "board")
    check("save: a new name is kept (id of 8 hex, via, time, the values whole) and the whole list is answered", len(L) == 1 and re.fullmatch(r"[0-9a-f]{8}", L[0]["id"]) and L[0]["name"] == "Dusk"
          and L[0]["values"] == V and L[0]["via"] == "board" and t0 <= L[0]["saved"] <= int(time.time()) + 1 and set(L[0]) == {"id", "name", "values", "saved", "via"}, L)
    check("…the file is JSON {combos: [...]} that parses and holds the same, no temporary file is left", json.loads(FILE.read_text()) == {"combos": L} and cc.listing() == L and not tmp_files())
    id1 = L[0]["id"]
    L = cc.save("Dawn", vals(1), WL); L = cc.save("Noon", vals(2), "board")
    check("save: oldest first, one list for everybody", [c["name"] for c in L] == ["Dusk", "Dawn", "Noon"] and L[1]["via"] == WL and len({c["id"] for c in L}) == 3)
    L = cc.save("  dAWn ", vals(9), "board")
    check("save: the same name with other case and spaces replaces that combination in its place, keeps its id, takes the new values, via and spelling",
          [c["name"] for c in L] == ["Dusk", "dAWn", "Noon"] and L[1]["values"] == vals(9) and L[1]["via"] == "board" and len(L) == 3 and L[0]["id"] == id1, L)
    L = cc.save("é", vals(3), "board"); L = cc.save("é", vals(4), "board")
    check("save: a name and its decomposed spelling are one name (NFC first)", [c["name"] for c in L].count("é") == 1 and len(L) == 4, [c["name"] for c in L])
    try: cc.save("x", V, "someone"); bad_via = False
    except ValueError: bad_via = True
    check("save: a via that is neither board nor the web label is refused", bad_via)
    snap = FILE.read_text()
    try: cc.save("Bad", {**V, "bg": "nope"}, "board"); refused = False
    except cc.Invalid as e: refused = e.field == "bg"
    check("save: a refused save changes nothing", refused and FILE.read_text() == snap)
    did = L[2]["id"]
    L = cc.delete(did)
    check("delete: the combination goes, the others stay in order, the file is the new list", [c["name"] for c in L] == ["Dusk", "dAWn", "é"] and json.loads(FILE.read_text()) == {"combos": L} and not tmp_files())
    snap, st = FILE.read_text(), FILE.stat().st_mtime_ns
    L2 = cc.delete(did); L3 = cc.delete("ffffffff"); L4 = cc.delete("not-an-id")
    check("delete: an id that is not on the list (already gone, never there, not even shaped like one) is no error: the list as it is, nothing written", L2 == L3 == L4 == L and FILE.read_text() == snap and FILE.stat().st_mtime_ns == st)
    bad_ids = []
    for x in (None, 5, "", "x" * 65, ["a"]):
        try: cc.delete(x); bad_ids.append(x)
        except cc.Invalid as e:
            if e.field != "id": bad_ids.append(x)
    check("delete: an id that is not a text of 1 to 64 characters is refused (field id)", not bad_ids, bad_ids)

    # the cap
    reset()
    for i in range(50): cc.save(f"combo {i:02d}", vals(i), "board")
    full = cc.listing()
    check("cap: 50 combinations fit", len(full) == 50 and [c["name"] for c in full][0] == "combo 00")
    try: cc.save("one more", V, "board"); refused = None
    except cc.Full as e: refused = str(e)
    check("cap: a 51st new name is refused with 'the list is full, delete one' and nothing changes", refused == "the list is full, delete one" and cc.listing() == full)
    L = cc.save("COMBO 07", V, WL)
    check("cap: a save under an existing name still works when the list is full (it replaces)", len(L) == 50 and L[7]["values"] == V and L[7]["id"] == full[7]["id"])
    cc.delete(full[0]["id"]); L = cc.save("one more", V, "board")
    check("cap: a delete makes room", len(L) == 50 and L[-1]["name"] == "one more")

    # the write: fsync before replace; a failed replace leaves the old file and no temporary file
    reset(); cc.save("Base", V, "board"); kept = FILE.read_text()
    events = []; real_fsync, real_replace = os.fsync, os.replace
    def spy_fsync(fd): events.append("fsync"); return real_fsync(fd)
    def spy_replace(a, b): events.append("replace"); return real_replace(a, b)
    os.fsync, os.replace = spy_fsync, spy_replace
    try: cc.save("Second", vals(5), "board")
    finally: os.fsync, os.replace = real_fsync, real_replace
    check("a save fsyncs the temporary file before os.replace puts it in place", events == ["fsync", "replace"], events)
    kept = FILE.read_text()
    def failing_replace(a, b): raise OSError(28, "No space left on device")
    os.replace = failing_replace
    try:
        try: cc.save("Third", vals(6), "board"); raised = False
        except OSError: raised = True
        try: cc.delete(json.loads(kept)["combos"][0]["id"]); raised_del = False
        except OSError: raised_del = True
    finally: os.replace = real_replace
    check("a failed os.replace (save and delete): OSError, the old file as it was, no temporary file left, nothing moved aside", raised and raised_del and FILE.read_text() == kept and not tmp_files() and not bad_files(), (raised, raised_del, tmp_files()))
    def failing_fsync(fd): raise OSError(5, "I/O error")
    os.fsync = failing_fsync
    try:
        try: cc.save("Fourth", vals(7), "board"); raised = False
        except OSError: raised = True
    finally: os.fsync = real_fsync
    check("a failed fsync: OSError, the old file as it was, no temporary file left", raised and FILE.read_text() == kept and not tmp_files())

    # a file that is not good
    reset(); FILE.write_text("{not json", encoding="utf-8")
    check("a file that does not parse: an empty list, the file moved aside to .bad-<epoch>", cc.listing() == [] and not FILE.exists() and len(bad_files()) == 1)
    FILE.write_text("[1, 2]", encoding="utf-8")
    check("a file that is not an object: moved aside too", cc.listing() == [] and len(bad_files()) == 2)
    FILE.write_bytes(b"\xff\xfe\x00 not text")
    check("a file that is not text: moved aside too", cc.listing() == [] and len(bad_files()) == 3)
    FILE.write_text("{not json", encoding="utf-8"); L = cc.save("After", V, "board")
    check("a save over a file that did not parse starts a new list and keeps the old file aside", [c["name"] for c in L] == ["After"] and json.loads(FILE.read_text())["combos"][0]["name"] == "After" and len(bad_files()) == 4)
    good = {"id": "0a0a0a0a", "name": "Whole", "values": V, "saved": 100, "via": "board"}
    FILE.write_text(json.dumps({"combos": [good, {**good, "id": "0b0b0b0b"}, {**good, "id": "0c0c0c0c", "name": "whole"}, {**good, "id": "0a0a0a0a", "name": "Same id"},
                                          {**good, "id": "bad", "name": "Short id"}, {**good, "id": "0d0d0d0d", "name": "No via", "via": "x"}, {**good, "id": "0e0e0e0e", "name": "Bad value", "values": {**V, "bg": "red"}},
                                          {**good, "id": "0f0f0f0f", "name": "Few", "values": {"bg": "#0a0a0a"}}, "text", None, {**good, "id": "1a1a1a1a", "name": "Second", "saved": 7.9}]}), encoding="utf-8")
    check("an entry that is not a whole combination (bad id, via, value, keys, a second entry of the same id or the same name) is left out when read; a whole one stays",
          [c["name"] for c in cc.listing()] == ["Whole", "Second"] and cc.listing()[1]["saved"] == 7, cc.listing())

    # a file that cannot be read: raised, untouched
    reset(); cc.save("Keep", V, "board"); kept = FILE.read_text()
    real_read = pathlib.Path.read_text
    def denied(self, *a, **k):
        if self.name == "color-combos.json": raise PermissionError(13, "Permission denied")
        return real_read(self, *a, **k)
    pathlib.Path.read_text = denied
    try:
        res = []
        for fn in (lambda: cc.listing(), lambda: cc.save("New", V, "board"), lambda: cc.delete("00000000")):
            try: fn(); res.append(False)
            except OSError: res.append(True)
    finally: pathlib.Path.read_text = real_read
    check("an unreadable file (permission denied): a read, a save and a delete all raise OSError; the file is as it was, not moved aside, no temporary file", all(res) and FILE.read_text() == kept and not bad_files() and not tmp_files(), res)
    if os.geteuid() != 0:
        os.chmod(FILE, 0)
        try:
            res = []
            for fn in (lambda: cc.listing(), lambda: cc.save("New", V, "board"), lambda: cc.delete("00000000")):
                try: fn(); res.append(False)
                except OSError: res.append(True)
        finally: os.chmod(FILE, 0o600)
        check("…the same with the file at mode 000", all(res) and FILE.read_text() == kept and not bad_files() and not tmp_files(), res)
    reset(); FILE.mkdir()
    res = []
    for fn in (lambda: cc.listing(), lambda: cc.save("New", V, "board"), lambda: cc.delete("00000000")):
        try: fn(); res.append(False)
        except OSError: res.append(True)
    check("…and with a directory in the file's place: OSError each time, the directory still there and empty, no temporary file", all(res) and FILE.is_dir() and not list(FILE.iterdir()) and not tmp_files() and not bad_files(), res)
    reset()

    # a corrupt file that cannot be moved aside: not read as empty (a save would write over it), the unreadable case
    reset(); FILE.write_text("{not json", encoding="utf-8"); corrupt = FILE.read_text()
    real_replace_ = os.replace
    def no_aside(a, b, *x, **k):
        if ".bad-" in str(b): raise PermissionError(13, "Permission denied")
        return real_replace_(a, b, *x, **k)
    os.replace = no_aside
    try:
        res = []
        for fn in (lambda: cc.listing(), lambda: cc.save("New", V, "board"), lambda: cc.delete("00000000")):
            try: fn(); res.append(False)
            except OSError: res.append(True)
    finally: os.replace = real_replace_
    check("a corrupt file that cannot be moved aside: a read, a save and a delete raise OSError; the corrupt file is as it was (not replaced by a list), nothing moved aside, no temporary file",
          all(res) and FILE.read_text() == corrupt and not bad_files() and not tmp_files(), res)
    check("…and once it can be moved aside again it is: kept as .bad-<epoch>, the list empty", cc.listing() == [] and not FILE.exists() and len(bad_files()) == 1)
    reset()

    # two threads at once
    errs = []
    def worker(tag):
        try:
            for i in range(15): cc.save(f"{tag} {i:02d}", vals(i), "board")
        except BaseException as e: errs.append(repr(e))
    ths = [threading.Thread(target=worker, args=(t,)) for t in ("alpha", "bravo")]
    [t.start() for t in ths]; [t.join(60) for t in ths]
    L = cc.listing()
    check("two threads saving at once lose nothing: 30 combinations, 30 different ids and names, the file parses, no temporary file", not errs and len(L) == 30 and len({c["id"] for c in L}) == 30
          and {c["name"] for c in L} == {f"{t} {i:02d}" for t in ("alpha", "bravo") for i in range(15)} and not tmp_files(), (errs, len(L)))
    errs = []
    ids = [c["id"] for c in L]
    def deleter(chunk):
        try:
            for i in chunk: cc.delete(i)
        except BaseException as e: errs.append(repr(e))
    ths = [threading.Thread(target=deleter, args=(ids[i::2],)) for i in range(2)]
    [t.start() for t in ths]; [t.join(60) for t in ths]
    check("two threads deleting at once lose nothing either: the list is empty", not errs and cc.listing() == [], errs)
    reset()

    # ---- 2. the routes
    COOKIE = {e: _signin._ui_sign(json.dumps({"email": e, "exp": time.time() + 3600})) for e in (MINA, EVE)}
    EXPIRED = _signin._ui_sign(json.dumps({"email": MINA, "exp": time.time() - 10}))
    JSON_H = {"Origin": BOARD, "Content-Type": "application/json"}
    _cfg.CFG["project_agent"] = {"form_senders": [WL, "other-web"], "form_machines": [HOST]}
    MH = {"Authorization": "Bearer " + TOK[HOST], "Content-Type": "application/json"}
    OH = {"Authorization": "Bearer " + TOK[OTHER], "Content-Type": "application/json"}
    drops = []
    real_drop = _wapp._board_home_drop
    _wapp._board_home_drop = lambda *a, **k: drops.append(1)
    with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
        def who(w):
            c.cookies.clear()
            if w: c.cookies.set(_signin._UI_COOKIE, w if w == EXPIRED else COOKIE[w])
        def bget(w=MINA, path="/colors/combos"):
            who(w); return c.get(path, follow_redirects=False)
        def bpost(body, w=MINA, headers=JSON_H, raw=None, path="/colors/combos"):
            who(w); return c.post(path, content=raw if raw is not None else json.dumps(body), headers=headers, follow_redirects=False)
        def mget(headers=MH, path="/client/colors/combos"):
            c.cookies.clear(); return c.get(path, headers=headers)
        def mpost(body, headers=MH, raw=None, path="/client/colors/combos"):
            c.cookies.clear(); return c.post(path, content=raw if raw is not None else json.dumps(body), headers=headers)
        def js(r):
            try: return r.json()
            except Exception: return None
        def is_err(r, status, field=None, text=None):
            j = js(r)
            return (r.status_code == status and isinstance(j, dict) and set(j) == {"error", "field"} and isinstance(j["error"], str) and j["error"] and j["field"] == field
                    and (text is None or text in j["error"]) and r.headers.get("cache-control") == "no-store")
        def listing_of(r): return (js(r) or {}).get("combos")
        S = {"name": "Dusk", "values": V}

        # the routes table
        app = c.app
        def first_full(path, method):
            for r in app.routes:
                m, _ = r.matches({"type": "http", "path": path, "method": method})
                if m.name == "FULL": return r.path
            return None
        PATHS = [("GET", "/colors/combos"), ("POST", "/colors/combos"), ("POST", "/colors/combos/delete"),
                 ("GET", "/client/colors/combos"), ("POST", "/client/colors/combos"), ("POST", "/client/colors/combos/delete")]
        check("the six routes are each registered once, with the method meant, and match their own path first",
              all(first_full(p, m) == p for m, p in PATHS) and all(sum(1 for r in app.routes if r.path == p and m in r.methods) == 1 for m, p in PATHS), {p: first_full(p, m) for m, p in PATHS})
        check("the single-segment /client/{what} routes (GET and POST) do not match the two-segment paths, and still match one segment",
              all(not r.matches({"type": "http", "path": p, "method": m})[0].name == "FULL" for r in app.routes if r.path == "/client/{what}" for m, p in PATHS if p.startswith("/client/"))
              and any(r.matches({"type": "http", "path": "/client/whoami", "method": "GET"})[0].name == "FULL" for r in app.routes if r.path == "/client/{what}")
              and any(r.matches({"type": "http", "path": "/client/poll", "method": "POST"})[0].name == "FULL" for r in app.routes if r.path == "/client/{what}"))
        check("the paths are not under /prefs/ and not in _UI_WRITES (a post does not drop the kept home page)", not any(p.startswith(_wapp._UI_WRITES) for _, p in PATHS))

        # -- the board: who may
        r = bget(None)
        check("board GET: no cookie is 403 with a plain sentence, an error object and no-store", is_err(r, 403, text="sign in"), (r.status_code, r.text))
        check("board GET: another address's cookie (not allowed) and an expired cookie are 403 too", is_err(bget(EVE), 403) and is_err(bget(EXPIRED), 403))
        r = bget()
        check("board GET: signed in, an empty list {combos: [], max: 50}, JSON, no-store", r.status_code == 200 and js(r) == {"combos": [], "max": 50} and r.headers.get("cache-control") == "no-store"
              and r.headers["content-type"].startswith("application/json"), (r.status_code, r.text, r.headers))
        check("board GET: HEAD is not a write, PUT and DELETE are not served (405)", c.put("/colors/combos").status_code in (404, 405) and c.delete("/colors/combos").status_code in (404, 405)
              and c.get("/colors/combos/delete").status_code in (404, 405))
        post_cases = [("no cookie", bpost(S, None)), ("another address", bpost(S, EVE)), ("expired", bpost(S, EXPIRED))]
        check("board POST: no cookie, another address, an expired cookie: 403 (sign in), nothing saved", all(is_err(r, 403, text="sign in") for _, r in post_cases) and not FILE.exists(), [(n, r.status_code) for n, r in post_cases])
        foreign = [("foreign origin", {"Origin": "https://evil.example", "Content-Type": "application/json"}), ("null origin", {"Origin": "null", "Content-Type": "application/json"}),
                   ("no origin, no referer", {"Content-Type": "application/json"}), ("foreign referer", {"Referer": "https://evil.example/x", "Content-Type": "application/json"}),
                   ("a look-alike origin", {"Origin": BOARD + ".evil.example", "Content-Type": "application/json"})]
        res = [(n, bpost(S, headers=h)) for n, h in foreign]
        check("board POST: a foreign origin, 'null', no Origin and no Referer, a foreign Referer, a look-alike address: 403, nothing saved", all(is_err(r, 403, text="board's own page") for _, r in res) and not FILE.exists(),
              [(n, r.status_code, r.text[:80]) for n, r in res])
        r = bpost(S, headers={"Referer": BOARD + "/items/a1", "Content-Type": "application/json"})
        check("board POST: a Referer from the board's own page is taken when the browser sent no Origin", r.status_code == 200 and listing_of(r)[0]["name"] == "Dusk", (r.status_code, r.text[:200]))
        bpost({"id": listing_of(r)[0]["id"]}, path="/colors/combos/delete"); reset()
        res = [bpost(S, headers={"Origin": BOARD, "Content-Type": ct}) for ct in ("text/plain", "application/x-www-form-urlencoded", "")]
        check("board POST: a body that is not declared JSON is 415", all(is_err(r, 415) for r in res) and not FILE.exists(), [r.status_code for r in res])
        r = bpost(None, raw=b"{not json"); r2 = bpost(None, raw=b"[1]"); r3 = bpost(None, raw=b'"text"'); r4 = bpost(None, raw=b"\xff\xfe"); r5 = bpost(None, raw=b"")
        check("board POST: a body that is not JSON, not an object (list, text), not UTF-8, or empty is 400", all(is_err(x, 400) for x in (r, r2, r3, r4, r5)), [x.status_code for x in (r, r2, r3, r4, r5)])

        # -- the size, before the body is read and as it arrives
        def raw_call(fn, path, length, chunks, headers):
            hs = [(b"host", b"board.example.org"), (b"content-type", b"application/json"), *[(k.lower().encode(), v.encode()) for k, v in headers.items()]]
            if length is not None: hs.append((b"content-length", str(length).encode()))
            scope = {"type": "http", "method": "POST", "path": path, "raw_path": path.encode(), "query_string": b"", "headers": hs, "scheme": "https", "root_path": "",
                     "server": ("board.example.org", 443), "client": ("203.0.113.9", 5000), "http_version": "1.1", "root_path": ""}
            reads = []
            async def receive():
                k = len(reads); reads.append(k)
                if k < len(chunks): return {"type": "http.request", "body": chunks[k], "more_body": k < len(chunks) - 1}
                return {"type": "http.disconnect"}
            return asyncio.run(fn(Request(scope, receive))), len(reads)
        cookie_h = {"Origin": BOARD, "Cookie": f"{_signin._UI_COOKIE}={COOKIE[MINA]}"}
        mach_h = {"Authorization": "Bearer " + TOK[HOST]}
        for label, fn, path, hd, extra in (("board", _rt_ui.colors_combos_save, "/colors/combos", cookie_h, {}), ("board delete", _rt_ui.colors_combos_delete, "/colors/combos/delete", cookie_h, {}),
                                           ("machine", _rt_ui.client_colors_combos_save, "/client/colors/combos", mach_h, {"sender": WL}),
                                           ("machine delete", _rt_ui.client_colors_combos_delete, "/client/colors/combos/delete", mach_h, {"sender": WL})):
            resp, nread = raw_call(fn, path, 10_000_000, [b"x" * 100], hd); body = json.loads(resp.body)
            check(f"{label}: a Content-Length over 4 KB is 413 before any of the body is read", resp.status_code == 413 and nread == 0 and set(body) == {"error", "field"} and body["field"] is None, (resp.status_code, nread, body))
            resp, nread = raw_call(fn, path, "12abc", [b"{}"], hd)
            check(f"{label}: a Content-Length that is not a number is 400 before the body is read", resp.status_code == 400 and nread == 0, (resp.status_code, nread))
            resp, nread = raw_call(fn, path, None, [b"x" * 3000, b"x" * 3000, b"x" * 3000], hd)
            check(f"{label}: a body with no Content-Length is cut off as it passes 4 KB (413), the rest not read", resp.status_code == 413 and nread == 2, (resp.status_code, nread))
        reset()
        resp, nread = raw_call(_rt_ui.colors_combos_save, "/colors/combos", None, [json.dumps(S)[:30].encode(), json.dumps(S)[30:].encode()], cookie_h)
        check("board POST: a small chunked body is read whole and saved", resp.status_code == 200 and json.loads(resp.body)["combos"][0]["name"] == "Dusk", resp.body[:200])
        big = json.dumps({"name": "Big", "values": V, "pad": "x" * 4100})
        r = bpost(None, raw=big)
        check("board POST: a body of over 4 KB through the client is 413 and not saved", is_err(r, 413) and [c_["name"] for c_ in cc.listing()] == ["Dusk"], (r.status_code, r.text[:100]))
        reset()

        # -- the board: what is in the body
        r = bpost({"values": V})
        check("board POST: no name is 400, field name", is_err(r, 400, "name"), r.text)
        r = bpost({"name": "A"})
        check("board POST: no values is 400, field values", is_err(r, 400, "values"), r.text)
        res = {n: bpost({"name": nm, "values": V}) for n, nm in (("empty", ""), ("blank", "   "), ("long", "x" * 41), ("tab", "a\tb"), ("nul", "a\u0000b"), ("number", 5))}
        check("board POST: a name that is empty, blank, 41 characters, has a tab or a NUL, or is not text is 400, field name", all(is_err(r, 400, "name") for r in res.values()), {k: (r.status_code, r.text[:80]) for k, r in res.items()})
        bad = {"#abc": "#abc", "#GGGGGG": "#GGGGGG", "no hash": "ec8a47", "rgb": "rgb(1,2,3)", "name": "red", "alpha": "#a2345678", "number": 5, "null": None}
        res = {n: bpost({"name": "A", "values": {**V, "solid": v}}) for n, v in bad.items()}
        check("board POST: a value that is not #rrggbb is 400 and field names the key (solid)", all(is_err(r, 400, "solid") for r in res.values()), {k: (r.status_code, r.text[:80]) for k, r in res.items()})
        r13 = bpost({"name": "A", "values": {k: v for k, v in V.items() if k != "labbd"}}); r15 = bpost({"name": "A", "values": {**V, "zzz": "#0a0a0a"}})
        r_list = bpost({"name": "A", "values": ["#0a0a0a"] * 14}); r_none = bpost({"name": "A", "values": None})
        check("board POST: 13 keys is 400 naming the missing key, 15 naming the extra one, values that are not an object 400 field values", is_err(r13, 400, "labbd") and is_err(r15, 400, "zzz")
              and is_err(r_list, 400, "values") and is_err(r_none, 400, "values"), (r13.text[:100], r15.text[:100]))
        check("board POST: after all that refusals nothing was written", not FILE.exists() and not tmp_files() and not drops)
        long_key = bpost({"name": "A", "values": {**V, "k" * 100: "#0a0a0a"}})
        check("board POST: a long unknown key is named, cut to 40 characters", is_err(long_key, 400, "k" * 40), long_key.text[:200])

        # -- the board: a good save, replace, delete
        r = bpost({"name": " Dusk ", "values": {**V, "bg": "#ABCDEF"}})
        j = js(r)
        check("board POST: a good save answers 200 with the whole list {combos, max}, the name stripped, the color lowercased, via board, no-store", r.status_code == 200 and j["max"] == 50 and len(j["combos"]) == 1
              and j["combos"][0]["name"] == "Dusk" and j["combos"][0]["values"]["bg"] == "#abcdef" and j["combos"][0]["via"] == "board" and r.headers.get("cache-control") == "no-store"
              and set(j["combos"][0]) == {"id", "name", "values", "saved", "via"}, r.text[:300])
        bid = j["combos"][0]["id"]
        check("board POST: it did not drop the kept home page (the home is not redrawn for a color list)", not drops, drops)
        pr = bpost({"order": ["runners"]}, path="/prefs/panel-order")
        check("…while a post to /prefs/ does (the control of that check)", pr.status_code == 200 and drops == [1], (pr.status_code, drops))
        bpost({"reset": True}, path="/prefs/panel-order"); drops.clear()
        r = bpost({"name": "dUSK", "values": vals(4)})
        j = js(r)
        check("board POST: the same name in other case replaces it: one entry, same id, new values", r.status_code == 200 and len(j["combos"]) == 1 and j["combos"][0]["id"] == bid and j["combos"][0]["values"] == vals(4)
              and j["combos"][0]["name"] == "dUSK", r.text[:300])
        r = bget()
        check("board GET: the list is what was saved", listing_of(r) == j["combos"] and len(listing_of(r)) == 1)
        bpost({"name": "Second", "values": vals(5)})
        r = bpost({"id": "ffffffff"}, path="/colors/combos/delete")
        check("board delete: an id that is not on the list is 200 with the list as it is", r.status_code == 200 and len(listing_of(r)) == 2)
        r = bpost({}, path="/colors/combos/delete"); r2 = bpost({"id": 5}, path="/colors/combos/delete"); r3 = bpost({"id": ""}, path="/colors/combos/delete")
        check("board delete: no id, an id that is not text, an empty id: 400, field id", all(is_err(x, 400, "id") for x in (r, r2, r3)), [x.text[:80] for x in (r, r2, r3)])
        r = bpost({"id": bid}, path="/colors/combos/delete")
        check("board delete: the combination goes (200, the list without it)", r.status_code == 200 and [x["name"] for x in listing_of(r)] == ["Second"], r.text[:200])
        check("board delete: no cookie 403, foreign origin 403, text/plain 415", is_err(bpost({"id": bid}, None, path="/colors/combos/delete"), 403) and is_err(bpost({"id": bid}, headers={"Origin": "https://evil.example", "Content-Type": "application/json"}, path="/colors/combos/delete"), 403)
              and is_err(bpost({"id": bid}, headers={"Origin": BOARD, "Content-Type": "text/plain"}, path="/colors/combos/delete"), 415))
        reset()

        # -- full and unreadable
        for i in range(50): cc.save(f"combo {i:02d}", vals(i), "board")
        full = cc.listing()
        r = bpost({"name": "one more", "values": V})
        check("board POST: a new name when 50 are saved is 409 'the list is full, delete one', nothing changed", is_err(r, 409, None, "the list is full, delete one") and cc.listing() == full, r.text[:200])
        r = bpost({"name": "COMBO 03", "values": V})
        check("board POST: a replacement when 50 are saved is fine", r.status_code == 200 and len(listing_of(r)) == 50 and listing_of(r)[3]["values"] == V)
        r = mpost({"name": "one more", "values": V, "sender": WL})
        check("machine POST: a new name when 50 are saved is 409 too, with the same sentence", is_err(r, 409, None, "the list is full, delete one"), r.text[:200])
        reset()
        FILE.mkdir()
        res = [bget(), bpost(S), bpost({"id": "00000000"}, path="/colors/combos/delete"), mget(), mpost({**S, "sender": WL}), mpost({"id": "00000000", "sender": WL}, path="/client/colors/combos/delete")]
        check("an unreadable file (a directory in its place): all six routes answer 503 'could not be read or saved', field null, no-store; nothing is changed", all(is_err(r, 503, None, "could not be read or saved") for r in res)
              and FILE.is_dir() and not list(FILE.iterdir()) and not tmp_files(), [(r.status_code, r.text[:100]) for r in res])
        reset()
        FILE.write_text("{not json", encoding="utf-8"); corrupt_r = FILE.read_text()
        real_replace_r = os.replace
        def no_aside_r(a, b, *x, **k):
            if ".bad-" in str(b): raise PermissionError(13, "Permission denied")
            return real_replace_r(a, b, *x, **k)
        os.replace = no_aside_r
        try: res = [bget(), bpost(S), bpost({"id": "00000000"}, path="/colors/combos/delete"), mget(), mpost({**S, "sender": WL}), mpost({"id": "00000000", "sender": WL}, path="/client/colors/combos/delete")]
        finally: os.replace = real_replace_r
        check("a corrupt file that cannot be moved aside: all six routes answer 503 'could not be read or saved', not an empty list; the file is as it was, nothing moved aside",
              all(is_err(r, 503, None, "could not be read or saved") for r in res) and FILE.read_text() == corrupt_r and not bad_files() and not tmp_files(), [(r.status_code, r.text[:100]) for r in res])
        reset()
        r = bpost({"name": "a" + "\u202e" + "b", "values": V}); r2 = mpost({**S, "sender": WL, "name": "a\u200bb"}); r3 = bpost({"name": "a\x85b", "values": V})
        check("board and machine POST: a name with a bidi override, a zero-width space or a C1 control is 400 field name, nothing saved", is_err(r, 400, "name") and is_err(r2, 400, "name") and is_err(r3, 400, "name") and not FILE.exists() and not tmp_files(), (r.text, r2.text))
        r = bpost({"name": "日本語 café", "values": V})
        check("board POST: a Japanese and accented name is saved", r.status_code == 200 and listing_of(r)[0]["name"] == "日本語 café", r.text[:200])
        reset()

        # -- the machine routes: who may
        r = mget({})
        check("machine GET: no token is 401, the plain text of the other /client routes", r.status_code == 401 and r.text.startswith("unauthorized: a machine token is required") and "json" not in r.headers["content-type"], (r.status_code, r.text, r.headers["content-type"]))
        res = [mget({"Authorization": "Bearer " + "x" * 43}), mget({"Authorization": "Bearer short"}), mget({"Authorization": "Basic " + TOK[HOST]}), mget({"Authorization": TOK[HOST]})]
        check("machine GET: an unknown token, a short one, another scheme, a bare token: 401", all(r.status_code == 401 for r in res), [r.status_code for r in res])
        c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE[MINA])
        check("machine GET: the board's cookie alone does not open the machine route (401)", c.get("/client/colors/combos").status_code == 401)
        r = mget(OH)
        check("machine GET: a valid token of a machine that is not in form_machines is 403 (a read too), an error object", is_err(r, 403, None, "form_machines"), (r.status_code, r.text))
        r = mget()
        check("machine GET: the right machine reads {combos: [], max: 50}, JSON, no-store", r.status_code == 200 and js(r) == {"combos": [], "max": 50} and r.headers.get("cache-control") == "no-store", (r.status_code, r.text))
        _cfg.CFG["project_agent"] = {"form_senders": [WL], "form_machines": []}
        check("machine GET: with form_machines empty nobody reads", is_err(mget(), 403))
        _cfg.CFG["project_agent"] = {"form_senders": [WL, "other-web"], "form_machines": [HOST]}
        MS = {**S, "sender": WL}
        res = [mpost(MS, {"Content-Type": "application/json"}), mpost(MS, {"Authorization": "Bearer " + "x" * 43, "Content-Type": "application/json"}),
               mpost({"id": "00000000", "sender": WL}, {"Content-Type": "application/json"}, path="/client/colors/combos/delete")]
        check("machine POST and delete: no token, an unknown token: 401; nothing saved", all(r.status_code == 401 for r in res) and not FILE.exists(), [r.status_code for r in res])
        r = mpost(MS, OH)
        check("machine POST: a valid token of a machine not in form_machines is 403 with a good sender, nothing saved", is_err(r, 403, None, "form_machines") and not FILE.exists(), (r.status_code, r.text))
        check("machine POST: a token that is not the board's: the board's own routes refuse it (403, there is no cookie)", is_err(bpost(S, None, headers={**MH, "Origin": BOARD}), 403) and is_err(bget(None), 403))
        r = mpost(S)
        check("machine POST: no sender is 400, field sender", is_err(r, 400, "sender"), r.text)
        res = [mpost({**S, "sender": s}) for s in (5, "", "   ", "a\nb", "x" * 81, None, [WL])]
        check("machine POST: a sender that is not text, blank, more than one line, over 80 characters is 400, field sender", all(is_err(r, 400, "sender") for r in res), [(r.status_code, r.text[:80]) for r in res])
        res = [mpost({**S, "sender": s}) for s in ("other-web", WL.upper(), WL.split("-")[0], "board", "osprey-x")]
        check("machine POST: another label (even one in form_senders), another case, a label not in form_senders: 403, field sender, nothing saved", all(is_err(r, 403, "sender", WL) for r in res) and not FILE.exists(), [(r.status_code, r.text[:80]) for r in res])
        _cfg.CFG["project_agent"] = {"form_senders": ["other-web"], "form_machines": [HOST]}
        r = mpost(MS); r2 = mpost({"id": "00000000", "sender": WL}, path="/client/colors/combos/delete")
        check("machine POST: the web label that is not in form_senders is 403 (a label alone is not enough), delete too", is_err(r, 403, "sender") and is_err(r2, 403, "sender") and not FILE.exists())
        _cfg.CFG["project_agent"] = {"form_senders": WL, "form_machines": HOST}
        check("machine POST: a bare string in the config counts as one name (as for the For you writes)", mpost(MS).status_code == 200)
        reset()
        _cfg.CFG["project_agent"] = {"form_senders": [WL, "other-web"], "form_machines": [HOST]}
        res = [mpost(MS, {"Authorization": "Bearer " + TOK[HOST], "Content-Type": ct}) for ct in ("text/plain", "")]
        check("machine POST: a body not declared JSON is 415", all(is_err(r, 415) for r in res) and not FILE.exists())
        res = [mpost(None, raw=b"{no"), mpost(None, raw=b"[1]"), mpost(None, raw=b"")]
        check("machine POST: a body that is not JSON or not an object is 400", all(is_err(r, 400) for r in res))
        r = mpost({**MS, "values": {**V, "disbg": "#12"}})
        check("machine POST: a bad value is 400 and field names the key", is_err(r, 400, "disbg"), r.text)
        r = mpost({**MS, "name": ""}); r2 = mpost({**MS, "values": {k: v for k, v in V.items() if k != "fg"}})
        check("machine POST: a bad name 400 field name, a missing key 400 naming it", is_err(r, 400, "name") and is_err(r2, 400, "fg"))
        check("machine POST: nothing of the refusals was saved", not FILE.exists() and not tmp_files())

        # -- the machine routes: a good call
        r = mpost(MS)
        j = js(r)
        check("machine POST: 200 {combos, max}, the combination kept with via the web label, no board cookie or origin needed, no-store", r.status_code == 200 and j["max"] == 50 and len(j["combos"]) == 1
              and j["combos"][0]["via"] == WL and j["combos"][0]["name"] == "Dusk" and j["combos"][0]["values"] == V and r.headers.get("cache-control") == "no-store", r.text[:300])
        mid = j["combos"][0]["id"]
        check("machine POST: the sender is not stored apart from via, and a post here does not drop the home", set(j["combos"][0]) == {"id", "name", "values", "saved", "via"} and not drops)
        r = mpost({**MS, "name": "dusk", "values": vals(8), "extra": "ignored"})
        check("machine POST: the same name replaces it, the same id, an extra key in the body is ignored", r.status_code == 200 and len(listing_of(r)) == 1 and listing_of(r)[0]["id"] == mid and listing_of(r)[0]["values"] == vals(8), r.text[:200])
        r = mget()
        check("machine GET: reads the same list", listing_of(r) == cc.listing() and len(listing_of(r)) == 1)

        # -- the same list through both paths
        r = bget()
        check("both paths: a combination the machine saved is read by the board's page, with via the web label", listing_of(r) == listing_of(mget()) and listing_of(r)[0]["via"] == WL and listing_of(r)[0]["id"] == mid)
        r = bpost({"name": "Board made", "values": vals(11)})
        check("both paths: a combination the board's page saved is read by the machine, with via 'board'", [x["via"] for x in listing_of(mget())] == [WL, "board"] and listing_of(mget()) == listing_of(r))
        r = bpost({"name": "DUSK", "values": vals(12)})
        check("both paths: a save from the board under a name the machine saved replaces it in place (same id), via becomes 'board'", [(x["name"], x["via"]) for x in listing_of(r)] == [("DUSK", "board"), ("Board made", "board")] and listing_of(r)[0]["id"] == mid)
        bid2 = listing_of(r)[1]["id"]
        r = mpost({"id": bid2, "sender": WL}, path="/client/colors/combos/delete")
        check("both paths: the machine deletes what the board saved; the board sees it gone", r.status_code == 200 and [x["name"] for x in listing_of(r)] == ["DUSK"] and [x["name"] for x in listing_of(bget())] == ["DUSK"])
        r = mpost({"id": "ffffffff", "sender": WL}, path="/client/colors/combos/delete")
        check("machine delete: an id not on the list is 200 with the list as it is", r.status_code == 200 and len(listing_of(r)) == 1)
        res = [mpost({"sender": WL}, path="/client/colors/combos/delete"), mpost({"id": 7, "sender": WL}, path="/client/colors/combos/delete")]
        check("machine delete: no id, or an id that is not text: 400, field id", all(is_err(r, 400, "id") for r in res))
        res = [mpost({"id": mid, "sender": "other-web"}, path="/client/colors/combos/delete"), mpost({"id": mid}, path="/client/colors/combos/delete"), mpost({"id": mid, "sender": WL}, OH, path="/client/colors/combos/delete")]
        check("machine delete: another label 403, no sender 400, another machine 403; the combination stays", [r.status_code for r in res] == [403, 400, 403] and len(cc.listing()) == 1)
        r = mpost({"id": mid, "sender": WL}, path="/client/colors/combos/delete")
        check("machine delete: the right call removes it, the list is empty", r.status_code == 200 and listing_of(r) == [] and cc.listing() == [])
        check("the machine and board routes' answers have the same shape: {combos, max}", js(mget()).keys() == js(bget()).keys() == {"combos", "max"})
    _wapp._board_home_drop = real_drop
    reset()

    # ---- 3. a standby copy, in a process of its own
    reset(); env = {k: v for k, v in os.environ.items() if k not in ("STACKSHOT_URL",)}
    env.update(HOME=tmp, PYTHONDONTWRITEBYTECODE="1", STACKSHOT_READ_ONLY="1")
    errf = open(T / "standby.err", "w")
    try:
        cp = subprocess.run([sys.executable, os.path.abspath(__file__), "--standby-child", tmp, json.dumps(V)], env=env, cwd=tmp, stdout=subprocess.PIPE, stderr=errf, text=True, timeout=240)
    finally: errf.close()
    try: sb = json.loads(cp.stdout.strip().splitlines()[-1])
    except Exception: sb = None
    check("a standby copy runs in a process of its own (exit 0, one JSON line)", cp.returncode == 0 and sb is not None, (cp.returncode, (T / "standby.err").read_text()[-600:]))
    if sb:
        REFUSAL = "stackshot here is a read-only standby copy (STACKSHOT_READ_ONLY); writes go to the live board."
        check("standby: the board's save and delete are 503 with the standby sentence, no-store", all(sb[k][0] == 503 and REFUSAL in sb[k][1] and sb[k][2] == "no-store" for k in ("post", "delete")), (sb["post"], sb["delete"]))
        check("standby: the machine's save and delete are 503 with the same sentence, whatever the body (even with no token: the standby refuses before it looks)", all(sb[k][0] == 503 and REFUSAL in sb[k][1] for k in ("mpost", "mdelete", "mpost_notoken")),
              (sb["mpost"], sb["mdelete"], sb["mpost_notoken"]))
        check("standby: reads still work (200, an empty list) by the board's cookie and by the machine token", sb["get"][0] == 200 and json.loads(sb["get"][1]) == {"combos": [], "max": 50} and sb["get"][2] == "no-store"
              and sb["mget"][0] == 200 and json.loads(sb["mget"][1]) == {"combos": [], "max": 50}, (sb["get"], sb["mget"]))
        check("standby: nothing was written (no file, no temporary file, nothing moved aside)", not FILE.exists() and not tmp_files() and not bad_files())
finally:
    try: _wapp._board_home_drop = real_drop
    except NameError: pass
    try: reset()
    except Exception: pass
    os.environ.pop("STACKSHOT_READ_ONLY", None)

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
