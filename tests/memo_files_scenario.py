"""Scenario test for the files on a memo-box note (stackshot/service/memo_files.py, web/routes/memo_files.py, tools/memo_files_clean.py, docs/memo-files.md): fixture items, the HTTP routes through
Starlette's test client, the real `stackshot standby-copy` as a process; no live store, no network.

  1  upload      a file is stored as pending and its record comes back; exactly 10 MB is taken, 10 MB + 1 byte is refused (413) and leaves nothing; an image over 5 MB is refused with "images are limited to 5 MB",
                 a 6 MB file that is no image is taken; an empty file is refused; a file named with a path or a `.tmp` ending is stored under a safe name; the gates are the answer's (token, origin, sign-in, unknown item)
  2  total       every memo file on the server counts together (a file elsewhere that leaves room for 2 MB: 6 MB is refused with 507 and nothing kept, 1 MB fits); the limits are the constants the docs name
  3  send        a note with two files records them on the answer, moves them from pending to the item and names them in the notice and in `get`; a fifth file is refused (400) and nothing is written, the files stay
                 waiting; an id that is not waiting, an id twice and a file of another item are refused; files alone are a comment; a note on a closed item keeps its files
  4  download    the file comes back byte for byte as an attachment, `application/octet-stream`, nosniff, never inline; a file not on the item's answers, another item's id and an unknown item are 404;
                 the machine route takes a client token and refuses one that is wrong
  5  clean       items closed 30 days ago lose their files, an item closed 5 days ago, an open one and one that cannot be read keep them; an upload pending for 24 hours goes, a younger one stays; --dry-run removes nothing;
                 a read-only standby changes nothing; the timer's units and the installer's lines exist
  6  standby     a copy taken while memo files are stored (60 MB) and an upload is still growing: the run succeeds, holds the locks for no longer than a copy of the same box without the files plus a margin,
                 carries the stored files, and leaves the partial upload out

    tests/run-suite memo_files        -> exit 0 / 1"""
import hashlib, json, logging, os, pathlib, re, subprocess, sys, threading, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="memofilestest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
EMAIL = "oliver@example.org"
REPO, STATE, SECRETS, RUN = T / "repo", T / "state", T / "secrets", T / "run"
STORE = REPO / "board-data"
MB = 1 << 20


def write_toml():
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", str(REPO)), ("store", str(STORE)), ("markdown", str(REPO / "board.md")), ("brain", f"{tmp}/brain"), ("state", str(STATE)), ("secrets", str(SECRETS)),
                     ("project_touch", f"{tmp}/touch"), ("rules", str(REPO / "RULES.md")), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml = _instance.set_person(toml)
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                     (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")


write_toml()
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", HOME=str(T / "home"), XDG_RUNTIME_DIR=str(RUN),
                  XDG_CONFIG_HOME=str(T / "home/.config"), XDG_STATE_HOME=str(T / "home/.state"), GIT_CONFIG_GLOBAL=os.devnull, GIT_CEILING_DIRECTORIES=str(T))
for k in ("STACKSHOT_URL", "STACKSHOT_READ_ONLY", "BOARD_MCP_CONFIG"):
    os.environ.pop(k, None)
for d in (REPO, STORE / "a", T / "fleet/a", T / "brain/projects", SECRETS, T / "home"):
    d.mkdir(parents=True, exist_ok=True)
RUN.mkdir(mode=0o700, exist_ok=True)
(REPO / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
OWNER = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now}}))
(STORE / "projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-agent",
                                                                             "agents": {"home-here": "builds it"}, "back_agents": {"home-here": "builds it"}, "status": "active", "board": [], "board_open": 0}}}))
DAY = 86400


def item(i, status="open", age=3600, **meta):
    (STORE / f"a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "A thing. It lives here. Finished when it works.", "status": status,
                                                   "updated": now - age, "state_updated": now - age, "confirmed": now - age,
                                                   "metadata": {"owner": OWNER, "project": "projects/alpha", "next": "the next step", "needs": ["home-agent"], **meta}}))


item(1); item(2); item(3)                                                   # open: the notes
item(4, status="completed", outcome="done", reason="it worked", age=2 * DAY)   # closed: a late note keeps its files
item(5, status="completed", outcome="done", reason="done", age=40 * DAY)       # closed 40 days ago: its files go
item(6, status="completed", outcome="done", reason="done", age=5 * DAY)        # closed 5 days ago: they stay
item(7, age=60 * DAY)                                                          # open and old: they stay
(STORE / "a/8.json").write_text("{ not json")                                  # cannot be read: they stay
(STORE / "next-id").write_text("20"); (STORE / "anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
g_ = lambda cwd, *a: subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
g_(REPO, "init", "-q"); g_(REPO, "add", "-A"); g_(REPO, "commit", "-q", "-m", "first")
g_(STORE, "init", "-q"); g_(STORE, "add", "-A"); g_(STORE, "commit", "-q", "-m", "fixture")
logging.disable(logging.INFO)
fails = []; ran = []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""), flush=True)


def rd(i): return json.loads((STORE / f"a/{i}.json").read_text())


from stackshot.web import server
from stackshot.github import ghsync as G
from stackshot.service import memo_files as memo
from stackshot.service import store as _service_store
from stackshot.service import telling
from stackshot.web import answers as _web_answers
from stackshot.web import publish as _web_publish
from stackshot.web.auth import signin as _signin
from stackshot.web.tools import get as _wt_get
from stackshot.tools import memo_files_clean as clean
from starlette.testclient import TestClient

_web_publish._publish = lambda: None
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, owner, note, tag))
COOKIE = _signin._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
tok = lambda g: _web_answers._answer_token(EMAIL, g)
SAME = {"Origin": BOARD}
MEMO = STATE / "memo-files"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 8
CLIENT_TOKEN = "t" * 40
SECRETS.joinpath("clients.json").write_text(json.dumps({"box-a": {"sha256": hashlib.sha256(CLIENT_TOKEN.encode()).hexdigest(), "created": "2026-01-01"}}))


def pending(g):
    d = MEMO / "pending" / g
    return sorted(os.listdir(d)) if d.is_dir() else []


check("the limits are the ones the docs name", (memo.MAX_FILE, memo.MAX_IMAGE, memo.MAX_FILES, memo.MAX_TOTAL) == (10 * MB, 5 * MB, 4, 100 * MB))

with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def up(g, name, data, headers=None, cookie=COOKIE, token=True):
        c.cookies.clear()
        if cookie: c.cookies.set(_signin._UI_COOKIE, cookie)
        h = {**SAME, **({"X-Answer-Token": tok(g)} if token else {}), **(headers or {})}
        return c.post(f"/items/{g}/files", params={"name": name}, content=data, headers=h)

    def send(g, **form):
        c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE)
        return c.post(f"/items/{g}/answer", data={"token": tok(g), **form}, headers={**SAME, "Accept": "application/json"}, follow_redirects=False)

    def fetch(path, auth=None, cookie=COOKIE):
        c.cookies.clear()
        if cookie: c.cookies.set(_signin._UI_COOKIE, cookie)
        return c.get(path, headers={"Authorization": f"Bearer {auth}"} if auth else {})

    # ---- 1. upload
    r = up("a1", "notes.txt", b"hello memo")
    j = r.json() if r.status_code == 201 else {}
    check("an upload is stored as pending and its record comes back", r.status_code == 201 and j.get("name") == "notes.txt" and j.get("size") == 10 and j.get("type") == "file" and memo.valid_id(j.get("id")), (r.status_code, r.text[:200]))
    check("it waits under pending/<item>/<id>/<name>, mode private, nothing under the item yet", (MEMO / "pending/a1" / j.get("id", "x") / "notes.txt").read_bytes() == b"hello memo" and not (MEMO / "a1").exists())
    big = up("a1", "ten.bin", b"x" * (10 * MB))
    check("exactly 10 MB is taken", big.status_code == 201 and big.json()["size"] == 10 * MB, (big.status_code, big.text[:200]))
    before = pending("a1")
    over = up("a1", "ten-and-one.bin", b"x" * (10 * MB + 1))
    check("10 MB + 1 byte is refused (413) with the sentence, and nothing is left", over.status_code == 413 and "files are limited to 10 MB" in over.text and pending("a1") == before, (over.status_code, over.text[:200], pending("a1")))
    img = up("a1", "photo.png", PNG + b"x" * (5 * MB - len(PNG) + 1))
    check("an image over 5 MB is refused: images are limited to 5 MB", img.status_code == 413 and "images are limited to 5 MB" in img.text and pending("a1") == before, (img.status_code, img.text[:200]))
    img6 = up("a1", "photo.jpg", b"\xff\xd8\xff\xe0" + b"x" * (6 * MB))
    check("an image of 6 MB (between 5 and 10) is refused the same way", img6.status_code == 413 and "images are limited to 5 MB" in img6.text and pending("a1") == before, (img6.status_code, img6.text[:200]))
    img4 = up("a1", "ok.png", PNG + b"x" * (4 * MB))
    check("a 4 MB image is taken and named an image", img4.status_code == 201 and img4.json()["type"] == "image", (img4.status_code, img4.text[:200]))
    f6 = up("a1", "six.bin", b"x" * (6 * MB))
    check("a 6 MB file that is no image is taken", f6.status_code == 201, (f6.status_code, f6.text[:200]))
    check("a file that is renamed .png but is no image is no image (its first bytes decide)", up("a2", "fake.png", b"not a png at all, just text").json()["type"] == "file")
    check("an empty file is refused (400)", up("a2", "empty", b"").status_code == 400)
    odd = up("a2", "../../etc/pass wd.tmp", b"abc").json()
    check("a name with a path or a .tmp ending is stored under a safe name", odd.get("name") == "pass wd.tmp.bin" and (MEMO / "pending/a2" / odd["id"] / "pass wd.tmp.bin").is_file(), odd)
    check("the name's length is bounded", len(up("a2", "a" * 400 + ".txt", b"abc").json()["name"]) <= memo.NAME_CHARS)
    check("refused 403: not signed in, no token, another item's token, another origin; unknown item 404",
          [up("a1", "x", b"abc", cookie=None).status_code, up("a1", "x", b"abc", token=False).status_code, up("a1", "x", b"abc", headers={"X-Answer-Token": tok("a2")}).status_code,
           up("a1", "x", b"abc", headers={"Origin": "https://evil.example.net"}).status_code, up("a99", "x", b"abc").status_code] == [403, 403, 403, 403, 404])
    check("a refused upload left nothing but the files that were taken", pending("a1") == sorted([j["id"], big.json()["id"], img4.json()["id"], f6.json()["id"]]), pending("a1"))

    # ---- 2. the total
    bigfile = MEMO / "a99" / ("f" * 32) / "old.bin"; bigfile.parent.mkdir(parents=True); fd = os.open(bigfile, os.O_WRONLY | os.O_CREAT); os.ftruncate(fd, memo.MAX_TOTAL - memo.total_bytes() - 2 * MB); os.close(fd)      # sparse: counts, takes no disk
    used = memo.total_bytes()
    full = up("a3", "six.bin", b"x" * (6 * MB))
    check("the 100 MB counts every memo file on the server together: 6 MB more is refused (507) and nothing is kept", full.status_code == 507 and "100 MB" in full.text and pending("a3") == [], (full.status_code, full.text[:200], pending("a3"), used))
    check("a file that still fits is taken, and the total never passes the limit", up("a3", "small.txt", b"x" * MB).status_code == 201 and memo.total_bytes() <= memo.MAX_TOTAL)
    bigfile.unlink()
    for p in (MEMO / "pending/a3").iterdir(): __import__("shutil").rmtree(p)

    # ---- 3. send
    ids = [j["id"], f6.json()["id"]]
    told.clear()
    r = send("a1", act="comment", text="see the files", files=",".join(ids))
    a = rd(1)["metadata"]["answers"][-1]
    check("a note with two files is sent: they are on the answer record", r.status_code == 200 and r.json().get("sent") == "comment" and [f["id"] for f in a.get("files", [])] == ids
          and [f["name"] for f in a["files"]] == ["notes.txt", "six.bin"] and a["files"][0]["size"] == 10, (r.status_code, r.text[:200], a))
    check("they moved from pending to the item", all((MEMO / "a1" / i).is_dir() for i in ids) and not any(i in pending("a1") for i in ids) and (MEMO / "a1" / ids[0] / "notes.txt").read_bytes() == b"hello memo")
    check("the notice line names them", any("[files: notes.txt (10 B), six.bin (6.0 MB)]" in n for _g, _o, n, _t in told), told)
    it = _service_store._load("a1"); it["gid"] = "a1"
    shown = _wt_get._fmt(it)
    check("`get` shows them on the answer line and as a files: block with each address",
          "[files: notes.txt (10 B), six.bin (6.0 MB)]" in shown and "files:\n- notes.txt (10 B) " in shown and f"/client/items/{G.href_id('a1')}/files/{ids[0]}/notes.txt" in shown, shown[-900:])
    left = pending("a1")
    five = [big.json()["id"], img4.json()["id"], odd["id"], ids[0], ids[1]]
    before = rd(1)
    r5 = send("a1", act="comment", text="five", files=",".join(five))
    check("a fifth file is refused (400): nothing written, the files stay waiting", r5.status_code == 400 and "at most 4 files" in r5.text and rd(1) == before and pending("a1") == left, (r5.status_code, r5.text[:200]))
    four = [big.json()["id"], img4.json()["id"]]
    check("an id twice, an id that is waiting on another item, one that was sent already and one that is no id are refused, nothing written",
          [send("a1", act="comment", text="x", files=f).status_code for f in (f"{four[0]},{four[0]}", odd["id"], ids[0], "../../x")] == [400] * 4 and rd(1) == before and pending("a1") == left)
    ok4 = send("a1", act="comment", text="four", files=",".join(four + [j2 := up("a1", "z1", b"1").json()["id"], up("a1", "z2", b"2").json()["id"]]))
    check("four files are taken", ok4.status_code == 200 and len(rd(1)["metadata"]["answers"][-1]["files"]) == 4, (ok4.status_code, ok4.text[:200]))
    only = up("a2", "only.txt", b"just a file").json()
    ro = send("a2", act="comment", text="", files=only["id"])
    check("files alone are a comment", ro.status_code == 200 and ro.json().get("sent") == "comment" and rd(2)["metadata"]["answers"][-1].get("files", [{}])[0].get("name") == "only.txt" and "text" not in rd(2)["metadata"]["answers"][-1], (ro.status_code, ro.text[:200]))
    check("no words and no files is still nothing", send("a2", act="comment", text="").json().get("sent") == "empty")
    c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE)
    c4 = c.post("/items/a4/files", params={"name": "late.txt"}, content=b"after the close", headers={**SAME, "X-Answer-Token": tok("a4")})
    rc = send("a4", act="comment", text="a late note", files=c4.json()["id"])
    check("a note on a closed item is kept as his comment with its files", rc.json().get("sent") == "closednote" and rd(4)["metadata"]["answers"][-1].get("files", [{}])[0].get("name") == "late.txt" and (MEMO / "a4" / c4.json()["id"] / "late.txt").is_file(), (rc.text[:200], rd(4)["metadata"]["answers"][-1:]))

    # ---- 4. download
    pdf = up("a1", "x.pdf", b"%PDF-1.4 <script>alert(1)</script>").json()
    path = f"/items/a1/files/{ids[0]}/notes.txt"
    d = fetch(path)
    check("the file comes back byte for byte as an attachment, octet-stream, nosniff, sandboxed",
          d.status_code == 200 and d.content == b"hello memo" and d.headers["content-type"].startswith("application/octet-stream") and d.headers["content-disposition"].startswith("attachment")
          and d.headers["x-content-type-options"] == "nosniff" and "sandbox" in d.headers["content-security-policy"], (d.status_code, dict(d.headers)))
    check("an unknown id, a file that is pending (not on an answer) and another item's file are 404",
          [fetch(f"/items/a1/files/{'0' * 32}/x").status_code, fetch(f"/items/a1/files/{pdf['id']}/x").status_code, fetch(f"/items/a2/files/{ids[0]}/notes.txt").status_code,
           fetch(f"/items/a99/files/{ids[0]}/x").status_code, fetch(f"/items/a1/files/not-an-id/x").status_code] == [404] * 5, [fetch(f"/items/a1/files/{'0' * 32}/x").status_code, fetch(f"/items/a1/files/{pdf['id']}/x").status_code, fetch(f"/items/a2/files/{ids[0]}/notes.txt").status_code, fetch(f"/items/a99/files/{ids[0]}/x").status_code, fetch("/items/a1/files/not-an-id/x").status_code])
    m = fetch(f"/client/items/a1/files/{ids[0]}/notes.txt", auth=CLIENT_TOKEN, cookie=None)
    check("the machine route sends the file for a client token", m.status_code == 200 and m.content == b"hello memo" and m.headers["content-disposition"].startswith("attachment"), (m.status_code, m.text[:100]))
    check("and refuses no token or a wrong one (401), an unknown file (404)", [fetch(f"/client/items/a1/files/{ids[0]}/notes.txt", cookie=None).status_code, fetch(f"/client/items/a1/files/{ids[0]}/notes.txt", auth="w" * 40, cookie=None).status_code,
          fetch(f"/client/items/a1/files/{'0' * 32}/x", auth=CLIENT_TOKEN, cookie=None).status_code] == [401, 401, 404])

    # ---- 4b. the fixes of the review round
    shutil_ = __import__("shutil")
    item(12); item(13); item(14); item(15); item(16)
    # a re-keyed item (a temporary id replaced by its final one): files stored under the old id stay downloadable
    G.record_issue("a12", 12, STORE, was="l5")
    old_fid = "e" * 32
    (MEMO / "l5" / old_fid).mkdir(parents=True); (MEMO / "l5" / old_fid / "kept.txt").write_bytes(b"stored before the re-key")
    it12 = rd(12); it12["metadata"]["answers"] = [{"ts": now, "kind": "comment", "text": "n", "files": [{"id": old_fid, "name": "kept.txt", "size": 24, "type": "file"}]}]; (STORE / "a/12.json").write_text(json.dumps(it12))
    dk = fetch(f"/items/a12/files/{old_fid}/kept.txt"); dm = fetch(f"/client/items/a12/files/{old_fid}/kept.txt", auth=CLIENT_TOKEN, cookie=None)
    check("a file stored under an item's old id (re-keyed since) is still downloaded, by the page and by a machine", dk.status_code == 200 and dk.content == b"stored before the re-key" and dm.status_code == 200, (dk.status_code, dm.status_code))
    shutil_.rmtree(MEMO / "l5")
    # the cap of 8 waiting uploads holds when 32 arrive together (a pause after the count makes the old check-then-create overshoot every time)
    real_listdir = os.listdir
    def slow_listdir(p="."):
        r = real_listdir(p)
        if "pending" in str(p): time.sleep(0.03)
        return r
    made, refused, lock_ = [], [], threading.Lock()
    def one():
        try:
            u = memo.Upload("a13", "c.txt", 3)
            with lock_: made.append(u)
        except memo.Refused as e:
            with lock_: refused.append(e.status)
    os.listdir = slow_listdir
    try:
        ths = [threading.Thread(target=one) for _ in range(32)]
        for t_ in ths: t_.start()
        for t_ in ths: t_.join()
    finally:
        os.listdir = real_listdir
    check("32 uploads at once on one item: no more than 8 wait, the rest are refused (400)", len(made) == memo.PENDING_PER_ITEM and refused == [400] * 24 and len(pending("a13")) == 8, (len(made), sorted(set(refused)), len(pending("a13"))))
    for u in made: u.abort()
    check("the claim folder is gone when the uploads are", not any((MEMO / ".claims").iterdir() if (MEMO / ".claims").is_dir() else ()) and pending("a13") == [], pending("a13"))
    # another upload's partial file is not stored: it does not take the room of a whole file
    pf = MEMO / "pending" / "a14" / ("9" * 32) / memo.PARTIAL; pf.parent.mkdir(parents=True)
    fd = os.open(pf, os.O_WRONLY | os.O_CREAT); os.ftruncate(fd, memo.MAX_TOTAL - MB); os.close(fd)      # sparse: a partial upload of 99 MB, still growing
    r2 = up("a3", "two.bin", b"x" * (2 * MB))
    check("another upload's partial file is not counted as stored: 2 MB is taken while a 99 MB partial is on the way", r2.status_code == 201, (r2.status_code, r2.text[:200]))
    shutil_.rmtree(MEMO / "pending" / "a14"); shutil_.rmtree(MEMO / "pending" / "a3", ignore_errors=True)
    # only one send takes a pending id: two notes naming it together, one is recorded and the other is refused (400)
    # (the pause lets both sends read the pending file before either moves it; the old check, made before the item lock, passed both)
    pid = up("a15", "shared.txt", b"one file").json()["id"]
    real_records, gate, outs = memo.records, threading.Barrier(2), []
    def paused(gid, ids):
        r = real_records(gid, ids)
        try: gate.wait(timeout=1.5)
        except threading.BrokenBarrierError: pass
        return r
    def sender():
        try: outs.append(("ok", _answer_service("a15", "", "same file", "comment", "board", None, "", "", [pid])))
        except memo.Refused as e: outs.append(("refused", e.status))
    from stackshot.service.answer import _answer as _answer_service
    memo.records = paused
    try:
        ths = [threading.Thread(target=sender) for _ in range(2)]
        for t_ in ths: t_.start()
        for t_ in ths: t_.join()
    finally:
        memo.records = real_records
    got = [f for a_ in rd(15)["metadata"].get("answers", []) for f in a_.get("files", [])]
    check("two notes that name the same pending file at once: one takes it, the other is refused (400), the file is recorded once", sorted(o[0] for o in outs) == ["ok", "refused"] and [o[1] for o in outs if o[0] == "refused"] == [400] and len(got) == 1, (outs, got))
    # the upload path gets the inside-the-store check of the read path: a symlinked pending folder is refused
    out_dir = T / "outside"; out_dir.mkdir(); (MEMO / "pending").mkdir(exist_ok=True); os.symlink(out_dir, MEMO / "pending" / "a16")
    sl = up("a16", "x.txt", b"abc")
    check("an upload into a symlinked pending folder is refused and writes nothing outside the store", sl.status_code == 400 and os.listdir(out_dir) == [], (sl.status_code, sl.text[:200], os.listdir(out_dir)))
    os.unlink(MEMO / "pending" / "a16")
    # a token with a character that is not ASCII is refused like a wrong one, never a 500
    def status_of(call):
        try: return call().status_code
        except Exception as e: return e.__class__.__name__
    odd_tok = [status_of(lambda: up("a1", "x", b"abc", headers={"X-Answer-Token": "t\u00f6k\u00e9n".encode("utf-8")})), status_of(lambda: send("a1", act="comment", text="x", token="t\u00f6k\u00e9n"))]
    check("a non-ASCII token is refused (403) on the upload and on the answer, not a 500", odd_tok == [403, 403], odd_tok)
    # a name keeps the documented 120 characters with the .bin included
    check("a name that gets .bin after it is still at most 120 characters (and 240 bytes)",
          all(len(n) <= memo.NAME_CHARS and len(n.encode()) <= memo.NAME_BYTES and n.endswith(".tmp.bin") for n in (memo.safe_name("a" * 400 + ".tmp"), memo.safe_name("\u00e9" * 400 + ".tmp"), memo.safe_name("b" * 118 + ".tmp"))), [len(memo.safe_name("a" * 400 + ".tmp"))])
    check("a name of 120 characters that needs nothing is kept whole", memo.safe_name("c" * 116 + ".txt") == "c" * 116 + ".txt")
    # a files-only note on a closed item is refused and its files stay pending
    cl = up("a4", "closed.txt", b"x").json()
    rcl = send("a4", act="comment", text="", files=cl["id"])
    check("a files-only note on a closed item is refused (nothing recorded) and its files stay pending", rcl.json().get("sent") == "closed" and cl["id"] in pending("a4") and not any(cl["id"] == f.get("id") for a_ in rd(4)["metadata"]["answers"] for f in a_.get("files", [])), (rcl.text[:200], pending("a4")))
    shutil_.rmtree(MEMO / "pending" / "a4", ignore_errors=True)

# ---- 5. clean
def aged(path, t):
    for dirpath, dirs, files in os.walk(path, topdown=False):
        for n in (*files, *dirs): os.utime(os.path.join(dirpath, n), (t, t), follow_symlinks=False)
    os.utime(path, (t, t), follow_symlinks=False)


def stored(g, name="f.txt", age=0):
    d = MEMO / g / ("a" * 31 + str(len(os.listdir(MEMO / g)) if (MEMO / g).is_dir() else 0)); d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(b"x" * 100); aged(MEMO / g, time.time() - age); return d


for g, age in (("a5", 45 * DAY), ("a6", 45 * DAY), ("a7", 45 * DAY), ("a8", 45 * DAY)): stored(g, age=age)
fresh = stored("a9", age=0); (STORE / "a/9.json").write_text(json.dumps({"id": "9", "subject": "[home] a9", "status": "completed", "updated": now - 40 * DAY, "state_updated": now - 40 * DAY, "metadata": {}}))
old_p = MEMO / "pending/a1/" / ("b" * 32); old_p.mkdir(parents=True); (old_p / "x.txt").write_text("x"); aged(old_p, time.time() - 25 * 3600)
new_p = MEMO / "pending/a1/" / ("c" * 32); new_p.mkdir(parents=True); (new_p / "x.txt").write_text("x")
check("closed_at: an open item, an unreadable one and an unknown one are 0; a closed one is its state stamp", clean.closed_at("a1") == 0 and clean.closed_at("a8") == 0 and clean.closed_at("a77") == 0 and abs(clean.closed_at("a5") - (now - 40 * DAY)) < 1)
os.environ["STACKSHOT_READ_ONLY"] = "1"; ro = clean.main([]); os.environ.pop("STACKSHOT_READ_ONLY")
check("a read-only standby changes nothing (exit 0, said so)", ro == 0 and (MEMO / "a5").is_dir())
(STORE / ".synced-at").write_text(""); ro2 = clean.main([]); (STORE / ".synced-at").unlink()
check("a store with the copy job's marker is a standby too", ro2 == 0 and (MEMO / "a5").is_dir())
check("--dry-run removes nothing", clean.main(["--dry-run"]) == 0 and (MEMO / "a5").is_dir() and old_p.is_dir())
check("a bad argument is a usage error (2)", clean.main(["--now"]) == 2)
rc = clean.main([])
check("the pass removes the files of an item closed 40 days ago and an upload pending 25 hours", rc == 0 and not (MEMO / "a5").exists() and not old_p.exists(), os.listdir(MEMO))
check("it keeps an item closed 5 days ago, an open one, one it cannot read and an upload pending an hour, and the files of an item closed long ago but stored just now",
      (MEMO / "a6").is_dir() and (MEMO / "a7").is_dir() and (MEMO / "a8").is_dir() and new_p.is_dir() and (MEMO / "a9").is_dir())
item(6, status="completed", outcome="done", reason="done", age=31 * DAY); aged(MEMO / "a6", time.time() - 45 * DAY)
check("an item closed 31 days ago loses its files at the next pass", clean.main([]) == 0 and not (MEMO / "a6").exists())
gone = pathlib.Path(tmp) / "gone-folder"
check("newest() of a folder that is gone is not an error: no age test passes it", memo.newest(gone) == float("inf"))
stored("a10", age=45 * DAY)
def closed_then_gone(g):      # the folder is removed between the sweep's listing and its measuring
    if g != "a10": return 0
    shutil.rmtree(MEMO / g, ignore_errors=True)
    return now - 40 * DAY
shutil = __import__("shutil")
try: swept = memo.sweep(closed_then_gone)
except Exception as e: swept = e
check("a folder that vanishes while the sweep measures it is skipped, the sweep goes on", isinstance(swept, dict), swept)
check("the program is listed under `stackshot`", subprocess.run([sys.executable, "-m", "stackshot", "memo-files-clean", "--bogus"], cwd=STACK, capture_output=True).returncode == 2)
svc, tim = (pathlib.Path(STACK) / "units" / f"stackshot-memo-files-clean.{k}.in" for k in ("service", "timer"))
check("the timer's units: the service runs the program, the timer is daily and persistent",
      "stackshot memo-files-clean" in svc.read_text() and "OnCalendar=" in tim.read_text() and "Persistent=true" in tim.read_text() and "Unit=stackshot-memo-files-clean.service" in tim.read_text())
inst = (pathlib.Path(STACK) / "install.sh").read_text()
check("install.sh installs the pair on a box that is not a standby and removes it from one",
      "stackshot-memo-files-clean.timer" in inst and "MEMO=1; [ \"${STACKSHOT_READ_ONLY:-}\" = 1 ] && MEMO=0" in inst and 'enable --now --quiet stackshot-memo-files-clean.timer' in inst)

# ---- 6. standby
shutil = __import__("shutil")
for p in list(MEMO.iterdir()): shutil.rmtree(p)


def copy(out):
    stop, growing = threading.Event(), MEMO / "pending/a1/" / ("d" * 32) / "upload.tmp"
    growing.parent.mkdir(parents=True, exist_ok=True); growing.write_bytes(b"")
    def grow():
        with open(growing, "ab") as f:
            while not stop.is_set(): f.write(b"y" * 1000); f.flush(); time.sleep(0.005)
    th = threading.Thread(target=grow); th.start()
    try:
        p = subprocess.run([sys.executable, "-m", "stackshot", "standby-copy", "--out", str(out)], cwd=STACK, capture_output=True, text=True, timeout=300)
    finally:
        stop.set(); th.join()
    m = re.search(r"locks held (\d+) ms", p.stderr)
    return p.returncode, int(m.group(1)) if m else None, p.stderr


rc0, ms0, err0 = copy(T / "copy0")
check("(setup) a copy of the box without memo files succeeds and reports its lock time", rc0 == 0 and ms0 is not None, err0[-400:])
for n in range(3):
    d = MEMO / "a1" / (f"{n:032x}"); d.mkdir(parents=True); (d / "big.bin").write_bytes(os.urandom(1 << 20) * 20)
rc1, ms1, err1 = copy(T / "copy1")
check("a copy with 60 MB of stored memo files and an upload still growing succeeds", rc1 == 0 and ms1 is not None, err1[-600:])
check("it holds the locks no longer than the copy without them plus a margin of two seconds", ms0 is not None and ms1 is not None and ms1 <= ms0 + 2000, (ms0, ms1))
check("the copy carries the stored files and leaves the partial upload out", all((T / "copy1/state/memo-files/a1" / f"{n:032x}" / "big.bin").stat().st_size == 20 * MB for n in range(3))
      and not list((T / "copy1/state").rglob("upload.tmp")), [str(p) for p in (T / "copy1/state").rglob("upload.tmp")])
shutil.rmtree(MEMO, ignore_errors=True)

print(("ok" if not fails else "FAILED") + f": memo files scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
