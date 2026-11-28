"""Scenario test for the canvas commands (the `canvas` tool: stackshot/web/tools/canvas.py over stackshot/service/canvas_write.py; docs/canvas.md) — fixture data, no live store, no network.

Covers: writes are off unless [canvas] write is true (add, update and undo are refused, nothing written; history and list still answer); the standby takes no write; add gives the next number
(after the counter and after the highest folder, never twice) and answers the address first; the page is refused unless its first part holds an item link (`href="<board>/items/N"`: the bare
text `board#N`, a link to another board, a link past the first part and a link in a script are all refused), is empty, holds a NUL byte or is over 5 MiB, with nothing written; the item
link names the canvas's item; update keeps the number, saves the page it replaces as a version (id: the time, never twice, newer than the newest), refuses an unknown number, leaves the same page
alone; history lists the versions newest first; undo restores the newest version, saves the page it replaces as one too (so a second undo goes back) and refuses when there is none; list gives
number, size, age, address and title; the page is served with the default link color and the tooltip (and its stored bytes are the page as saved); a notice (not a refusal) on a decision page that is
too long or whose first line has no question or no recommendation, in the save reply and nowhere else; the tool's refusals read as tool refusals; two writers racing get two numbers.

    tests/run-suite canvas_write        -> exit 0 / 1"""
import hashlib, json, os, pathlib, re, sys, threading, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="canvaswrite-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"


def write_toml():
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml = _instance.set_person(toml)
    for pat, rep in ((r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")


write_toml()
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/g", "fleet/a", "state", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "agents": {}, "back_agents": {}, "status": "active", "board": [], "board_open": 0}}}))
for n, needs in ((7, ["decision"]), (9, [])):
    (T / f"store/g/{n}.json").write_text(json.dumps({"id": str(n), "subject": f"[home] item {n}", "description": "A thing. It lives here. Finished when it works.", "status": "open",
                                                    "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                    "metadata": {"owner": OWNER, "project": "projects/alpha", "next": "the next step", "needs": needs}}))

from fastmcp.exceptions import ToolError
from stackshot.web import server
from stackshot.web.tools import canvas as TOOL
from stackshot.service import canvas as _canvas, canvas_write as _w
from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro

FAILS = []
STORE = T / "state/canvas"


def check(name, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + name + ("" if ok else f"  :: {str(detail)[:700]}"), flush=True)
    if not ok:
        FAILS.append(name)


def files():
    return {str(p.relative_to(T)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(STORE.rglob("*")) if p.is_file() and not p.name.endswith(".lock")} if STORE.exists() else {}


def call(**kw):
    kw.setdefault("sender", "my-x")
    return TOOL.stackshot_canvas(**kw)


def refused(name, want, **kw):
    before = files()
    try:
        out = call(**kw)
        check(name, False, f"answered: {out[:200]}")
    except ToolError as e:
        check(name, str(e).startswith("Refused") and all(w in str(e) for w in want), str(e))
    check(f"{name}: nothing written", files() == before, sorted(set(files()) ^ set(before)))


def rec(n):
    return json.loads((STORE / str(n) / "canvas.json").read_text(encoding="utf-8"))


def link(n):
    return f'<a href="{BOARD}/items/{n}">board#{n}</a>'


def page(n=9, body="<p>Hello</p>"):
    return f"<!doctype html><html><head><meta charset=utf-8><title>t</title></head><body>{link(n)}{body}</body></html>"


# ---------------------------------------------------------------- 1. off by default
check("write: off by default", _w.write_on() is False)
refused("write: add is refused while writes are off", ("[canvas] write",), action="add", page=page())
refused("write: update is refused while writes are off", ("[canvas] write",), action="update", number=1, page=page())
refused("write: undo is refused while writes are off", ("[canvas] write",), action="undo", number=1)
check("write: list answers while writes are off", "no canvases" in call(action="list"), call(action="list"))
for value in ("true", 1, "yes"):
    _cfg.CFG.setdefault("canvas", {})["write"] = value
    refused(f"write: [canvas] write = {value!r} is not true", ("[canvas] write",), action="add", page=page())
_cfg.CFG["canvas"]["write"] = True

# ---------------------------------------------------------------- 2. add
out = call(action="add", page=page(9), title="  First   page ")
lines = out.split("\n")
check("add: the first line is the address, nothing else on it", lines[0] == f"{BOARD}/canvas/1", out)
check("add: the reply says what happened", "result: added" in lines, out)
r = rec(1)
check("add: the record holds the title cleaned, the item the link names, one current page, no versions", r["title"] == "First page" and r["item"] == "g9" and r["current"] and r["versions"] == [] and r["current"]["session"] == "my-x", r)
data = page(9).encode()
check("add: the stored bytes are the page, under their hash", (STORE / "1" / (hashlib.sha256(data).hexdigest() + ".html")).read_bytes() == data)
check("add: the counter is the number", (STORE / "counter").read_text().strip() == "1")
check("add: the next one is 2", call(action="add", page=page(9, "<p>two</p>")).split("\n")[0].endswith("/canvas/2"))
(STORE / "counter").write_text("40\n")
check("add: a number comes after the counter", call(action="add", page=page(9, "<p>c</p>")).split("\n")[0].endswith("/canvas/41"))
(STORE / "90").mkdir()
check("add: a number comes after the highest folder", call(action="add", page=page(9, "<p>d</p>")).split("\n")[0].endswith("/canvas/91"))
(STORE / "90").rmdir()

# ---------------------------------------------------------------- 3. the item link
LINK_REFUSAL = ("item link", "href=")
refused("link: a page with no link is refused", LINK_REFUSAL, action="add", page="<p>nothing</p>")
refused("link: the bare text board#N does not pass", LINK_REFUSAL, action="add", page="<p>" + "board" + "#9 is the item</p>")
refused("link: a link to another board does not pass", LINK_REFUSAL, action="add", page='<a href="https://other.example.org/' + 'items' + '/9">x</a>')
refused("link: a link to a canvas does not pass", LINK_REFUSAL, action="add", page=f'<a href="{BOARD}/canvas/9">x</a>')
refused("link: a link past the first part does not pass", LINK_REFUSAL, action="add", page="<p>" + "word " * 1200 + f"</p>{link(9)}")
refused("link: a link in a script does not pass", LINK_REFUSAL, action="add", page=f"<script>var s='{link(9)}'</script><p>x</p>")
refused("link: update checks it too", LINK_REFUSAL, action="update", number=1, page="<p>no link</p>")
try:
    call(action="add", page="<p>x</p>")
except ToolError as e:
    check("link: the refusal shows the link to write, with this board's address", f'href="{BOARD}/items/N"' in str(e) and "board#N" in str(e), str(e))

# ---------------------------------------------------------------- 4. what a page may be
refused("page: empty", ("empty",), action="add", page="")
refused("page: blank", ("empty",), action="add", page="  \n ")
refused("page: a NUL byte", ("NUL",), action="add", page=page() + "\0")
refused("page: over 5 MiB", ("5242880",), action="add", page=page() + "a" * (5 * 1024 * 1024))
refused("page: not UTF-8 text (a lone surrogate)", ("UTF-8",), action="add", page=page() + "\ud800")
refused("add: a title over 200 characters", ("200",), action="add", page=page(), title="t" * 201)
refused("add: an unknown action", ("action",), action="frob", page=page())
refused("add: a number with add", ("number",), action="add", number=3, page=page())
refused("add: no page", ("empty", "page="), action="add")

# ---------------------------------------------------------------- 5. update and its versions
ids_before = rec(1)["versions"]
out = call(action="update", number=1, page=page(9, "<p>v2</p>"))
r = rec(1)
check("update: same number, same address on the first line", out.split("\n")[0] == f"{BOARD}/canvas/1" and "result: replaced" in out, out)
check("update: the page it replaces is a version", len(r["versions"]) == 1 and r["versions"][0]["sha256"] == hashlib.sha256(data).hexdigest() and re.fullmatch(_canvas.VERSION_ID, r["versions"][0]["id"]), r)
check("update: the current page is the new one", r["current"]["sha256"] == hashlib.sha256(page(9, "<p>v2</p>").encode()).hexdigest())
check("update: the replaced bytes are still on disk", (STORE / "1" / (hashlib.sha256(data).hexdigest() + ".html")).is_file())
check("update: the title is kept", r["title"] == "First page")
out = call(action="update", number=1, page=page(9, "<p>v2</p>"))
check("update: the same page again changes nothing", "result: unchanged" in out and len(rec(1)["versions"]) == 1, out)
call(action="update", number=1, page=page(9, "<p>v3</p>"))
call(action="update", number=1, page=page(9, "<p>v4</p>"))
ids = [v["id"] for v in rec(1)["versions"]]
check("update: every version has its own id, in time order", len(ids) == 3 and ids == sorted(set(ids)), ids)
refused("update: an unknown number", ("no canvas 99", "add"), action="update", number=99, page=page())
refused("update: no number", ("number",), action="update", page=page())
refused("update: a number of no digits", ("number",), action="update", number=-3, page=page())
call(action="update", number=1, page=page(9, "<p>v5</p>"), title="Renamed")
check("update: a title given replaces the old one", rec(1)["title"] == "Renamed")
call(action="update", number=1, page=page(7, "<p>v6</p>"))
check("update: the item follows the link of the new page", rec(1)["item"] == "g7", rec(1))

# a clock that stands still or goes back never gives a version id twice
real_time = time.time
try:
    top = max(v["id"] for v in rec(1)["versions"])
    t_top = _canvas.version_time(top).timestamp()
    time.time = lambda: t_top - 5
    call(action="update", number=1, page=page(9, "<p>v7</p>"))
    ids = [v["id"] for v in rec(1)["versions"]]
    check("update: the clock gone back still gives a new id, newer than the newest", len(ids) == len(set(ids)) and max(ids) > top, ids)
finally:
    time.time = real_time

# ---------------------------------------------------------------- 6. history and undo
out = call(action="history", number=1)
rows = [x for x in out.split("\n") if x]
check("history: one line per version, newest first, each with its id and size", len(rows) == len(rec(1)["versions"]) and rows == sorted(rows, reverse=True) and all(re.match(_canvas.VERSION_ID[:8], x) for x in rows), out)
check("history: a canvas with none says so", "no earlier version" in call(action="history", number=2), call(action="history", number=2))
refused("history: an unknown number", ("no canvas 99",), action="history", number=99)
before_cur, before_versions = rec(1)["current"], list(rec(1)["versions"])
newest = max(before_versions, key=lambda v: v["id"])
out = call(action="undo", number=1)
r = rec(1)
check("undo: the newest version is the page again", r["current"]["sha256"] == newest["sha256"] and out.split("\n")[0] == f"{BOARD}/canvas/1" and "restored" in out, (out, r["current"]))
check("undo: it is out of the versions and the page it replaced is one", all(v["id"] != newest["id"] for v in r["versions"]) and any(v["sha256"] == before_cur["sha256"] for v in r["versions"]) and len(r["versions"]) == len(before_versions), r["versions"])
call(action="undo", number=1)
check("undo: a second undo goes back to where it was", rec(1)["current"]["sha256"] == before_cur["sha256"], rec(1)["current"])
refused("undo: a canvas with no version", ("no earlier version",), action="undo", number=2)
refused("undo: an unknown number", ("no canvas 99",), action="undo", number=99)
(STORE / "2" / "canvas.json").write_text("{nope")
refused("undo: an unreadable record is refused and left alone", ("not a canvas record",), action="update", number=2, page=page())
(STORE / "2" / "canvas.json").unlink()

# ---------------------------------------------------------------- 7. list
out = call(action="list")
rows = [x for x in out.split("\n") if x]
check("list: a line per canvas with number, size, age, address and title", rows[0].startswith("1 ") and f"{BOARD}/canvas/1" in rows[0] and "Renamed" in rows[0] and re.search(r" \d+ bytes ", rows[0]) and re.search(r" (\d+[smhd]|now) ", rows[0]), out)
check("list: numbers in order", [int(x.split()[0]) for x in rows] == sorted(int(x.split()[0]) for x in rows) and len(rows) >= 3, out)

# ---------------------------------------------------------------- 8. what a reader gets: stored as written, served with the defaults
from starlette.testclient import TestClient
from stackshot.web.auth import signin as _signin
_signin._auth_mode = lambda: "off"
tipped = page(9, "<p>An <span data-tip='what it means'>idea</span> and <a href='#a'>a link</a></p>")
n_tip = int(call(action="add", page=tipped).split("\n")[0].rsplit("/", 1)[1])
with TestClient(server.mcp.http_app(), base_url=BOARD, raise_server_exceptions=False) as c:
    stored = c.get(f"/canvas/{n_tip}/raw").text
check("serve: the tooltip and the default link color come with the served page", "data-canvas-tip" in stored and "data-canvas-link" in stored and "'what it means'" in stored, stored[:300])
check("serve: what was saved is still on disk as it was written", (STORE / str(n_tip) / (hashlib.sha256(tipped.encode()).hexdigest() + ".html")).read_bytes() == tipped.encode())

# ---------------------------------------------------------------- 9. notices
big = page(7, "<h1>Ship it? I recommend yes.</h1>" + "<p>" + "word " * 400 + "</p>")
out = call(action="add", page=big)
check("notice: a decision page over a screen is saved and told", out.split("\n")[0].startswith(BOARD) and "result: added" in out and any(x.startswith("notice:") and "longer than one screen" in x for x in out.split("\n")), out)
out = call(action="add", page=page(7, "<h1>Ship it</h1><p>Short.</p>"))
check("notice: a first line with no question and no recommendation is saved and told", out.count("notice:") == 1 and "no question" in out and "no recommendation" in out, out)
out = call(action="add", page=page(7, "<h1>Ship it? I recommend yes.</h1><p>Short.</p>"))
check("notice: a good decision page gets none", "notice" not in out, out)
out = call(action="add", page=page(9, "<h1>Ship it</h1>" + "<p>" + "word " * 400 + "</p>"))
check("notice: a page of an item that is no decision gets none", "notice" not in out, out)
out = call(action="add", page=f'{link(404)}<h1>Ship it</h1>')
check("notice: a page of an item the board does not have is saved, no notice", out.split("\n")[0].startswith(BOARD) and "notice" not in out, out)
check("notice: history and list carry none", "notice" not in call(action="list") and "notice" not in call(action="history", number=1))

# ---------------------------------------------------------------- 10. the standby, and two writers
_ro._RO = True
try:
    before = files()
    for kw in (dict(action="add", page=page()), dict(action="update", number=1, page=page(9, "<p>sb</p>")), dict(action="undo", number=1)):
        try:
            call(**kw)
            check(f"standby: {kw['action']} is refused", False)
        except Exception as e:
            check(f"standby: {kw['action']} is refused", True)
    check("standby: nothing written", files() == before)
    check("standby: list still answers", "canvas/1" in call(action="list"))
finally:
    _ro._RO = False

got, errs = [], []
def worker(i):
    try:
        got.append(call(action="add", page=page(9, f"<p>race {i}</p>"), sender=f"w{i}").split("\n")[0])
    except Exception as e:      # noqa: BLE001
        errs.append(repr(e))
ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
for t in ts: t.start()
for t in ts: t.join()
check("race: eight writers get eight different numbers", not errs and len(set(got)) == 8, (got, errs))

print(f"\n{len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
