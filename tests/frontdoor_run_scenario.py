"""tests/frontdoor_run_scenario.py: the front door in front of two boards, as real processes: the whole path of a call, and every one of them restarted.

Hermetic: nothing but this machine's loopback. Under one scratch folder (tests/_scratch.py: locked while the suite runs, removed when it ends, pass or fail) it makes
  * two boards, `main` and `side`, each its own process (`stackshot/web/server.py`) with its own config, store, port, bearer token, copy of the signing secret and
    sign-in set to google (a made-up client; the board's machine bearer is the credential the front door calls with), each told `[behind_frontdoor]` by its config;
  * one front door (`python -m stackshot.frontdoor`), its config naming both boards, the signing secret and the one members file the boards read too;
  * a third board that has no `[behind_frontdoor]` table and sign-in off, for what must stay as it was.
Every port is a free one chosen at run time on 127.0.0.1, every process has a HOME and a TMPDIR of its own inside the scratch folder, and a child asks the kernel to end it
with this process (so a killed suite leaves none), and is stopped by its PID. The test plays the reverse proxy (it sets the identity header) and the client.

What a round proves (a member is `alice` on both boards, `bob` on `side` only, `carol` on `main` only; the anchors tool records the caller on the board's own store, which the
test reads back):
  * a call through the door as each member reaches the right board, and the board records the person the proxy named (not the caller's own `Authorization`, and not a
    `x-stackshot-identity` header the client sends itself); one board never holds the other's record;
  * the door's refusals (two boards and no `board`, a board that is not the caller's, a caller on no board, no identity header: 401);
  * the board's own check with the door left out: a member the board's members list does not hold is refused by the tool; no signed identity, an identity signed with
    another secret, altered, older than the replay window, dated ahead, or only a bare name, each 403 with the board's sentence; a signed call with no bearer is refused 401
    (the front door's credential is still the board's sign-in); the health route stays open;
  * a member removed from the members file is refused at the next call on both boards, on an open session through the door and on an open session at each board, and let back in
    when put back; the file edited in place, replaced by a rename, or edited to a new text of the same size; a file that is broken or missing lets nobody in (a valid signature
    included).
  The round runs four times: at the start, after the front door is restarted, after `main` is restarted, after `side` is restarted. Each part is stopped by its PID; while it is down
  the other part answers (the door says the board did not answer; a board still takes a signed call with the door gone); `alice` is removed from the file before it starts again
  and put back after (a restart reads the file afresh, never remembers a member); the first call after a start is served, with `/healthz` back to 200 inside a few seconds.
  After the four rounds the signing secret is rotated in the board's files and the door's, one after another with no restart: a call is refused while they differ and served
  when they agree, and an identity signed with the old secret is refused.
The third board (no table) serves an unsigned call, ignores a header that looks like a signed identity, and records no person.

    tests/run-suite frontdoor_run        -> exit 0 / 1"""
import asyncio, itertools, json, os, pathlib, re, secrets, signal, socket, subprocess, sys, time, urllib.error, urllib.request
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch, _instance
from stackshot.core import frontdoor_identity as ident
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError

tmp = _scratch.mkdtemp(prefix="frontdoor-run-"); T = pathlib.Path(tmp)
fails, ran = [], []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""), flush=True)


ALICE, BOB, CAROL, DAVE = "alice@example.test", "bob@example.test", "carol@example.test", "dave@example.test"
MAIN, SIDE = "main", "side"
PROJECT = "projects/alpha"
SECRET = secrets.token_urlsafe(24)                    # the front door's signing secret, copied for each board
OTHER_SECRET = secrets.token_urlsafe(24)
S0 = {ALICE: [MAIN, SIDE], BOB: [SIDE], CAROL: [MAIN]}      # the members file as the run starts every round
NO_IDENTITY = "refused: this board takes calls through its front door only, and this call carries no signed identity."
BAD_IDENTITY = ("refused: the signed identity of this call is not accepted (it is altered, signed with another secret, older than this board's replay window, "
                "or dated ahead of its clock).")
NOT_A_MEMBER = "you are not a member of any board."
CALLER_HEADER = "X-Forwarded-User"


# ------------------------------------------------------------------------------------------------ files and processes
def write_secret(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value + "\n")
    os.chmod(path, 0o600)
    return str(path)


def free_ports(n):
    """n distinct free ports on 127.0.0.1, all held together until every one is chosen."""
    socks = [socket.socket() for _ in range(n)]
    try:
        for s in socks:
            s.bind(("127.0.0.1", 0))
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


def port_free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def raw(url, headers=None, method="POST", body=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'):
    """(status, text) of one plain request; 0 and the error's name when nothing answers."""
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(headers or {})}
    req = urllib.request.Request(url, data=body if method == "POST" else None, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(4000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(4000).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, type(e).__name__


def _die_with_parent():
    """Runs in the child before its program starts: the kernel ends the child (SIGTERM) when this process ends, killed or not."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)       # PR_SET_PDEATHSIG
    except Exception:       # noqa: BLE001  (a platform without it: the suite's `finally` stops every child itself)
        pass


class Proc:
    """One server process: start it, wait until it answers, stop it by its PID."""
    def __init__(self, name, argv, env, cwd, port, up_status):
        self.name, self.argv, self.env, self.cwd, self.port, self.up = name, argv, env, str(cwd), port, up_status
        self.err_path = T / f"{name}.err"; self.p = None

    def start(self, timeout=150):
        with open(self.err_path, "ab") as err:
            self.p = subprocess.Popen(self.argv, env=self.env, cwd=self.cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err, preexec_fn=_die_with_parent)
        end = time.time() + timeout
        while time.time() < end:
            if self.p.poll() is not None:
                return False
            if raw(f"http://127.0.0.1:{self.port}/healthz", method="GET")[0] in self.up:
                return True
            time.sleep(0.3)
        return False

    def stop(self):
        """Ends the process by its PID (SIGTERM, then SIGKILL after 25 s); → its exit code, or None when it was not running."""
        if self.p is None or self.p.poll() is not None:
            return None
        self.p.terminate()
        try:
            self.p.wait(25)
        except subprocess.TimeoutExpired:
            self.p.kill(); self.p.wait(15)
        return self.p.returncode

    def running(self):
        return self.p is not None and self.p.poll() is None

    def tail(self):
        try:
            return self.err_path.read_text(errors="replace")[-700:]
        except OSError:
            return ""


def clean_env():
    """The environment of a child: this one without anything of a stackshot instance or of the user's directories."""
    return {k: v for k, v in os.environ.items() if not k.startswith(("STACKSHOT_", "BOARD_MCP_", "XDG_")) or k == "STACKSHOT_XLOCK_STRICT"}


MEMBERS = T / "door" / "members.json"


def write_members(d, how="inplace"):
    text = json.dumps(d)
    if how == "replace":        # a rename over the file: a new inode, as an editor that saves by renaming makes
        new = MEMBERS.with_name("members.json.new"); new.write_text(text); os.replace(new, MEMBERS)
    else:
        MEMBERS.write_text(text)


def build_board(label, port, behind_name, bearer):
    """One board's instance on a folder of its own; → (the Proc, its root). `behind_name` None: no [behind_frontdoor] table and sign-in off."""
    root = T / label
    for d in ("store/a", "state", "secrets", "touch", "brain/projects", "fleet/a", "home", "tmp"):
        (root / d).mkdir(parents=True)
    toml = _instance.base_toml()
    toml = re.sub(r'(?m)^process = "inline"', 'process = "unit"', toml, count=1)         # the server starts no runner thread (the suites that run the runner say so themselves)
    toml = re.sub(r'(?m)^session_links = ".*"', 'session_links = ""', toml, count=1)
    assert 'session_links = ""' in toml
    for key, val in (("repo", root), ("store", root / "store"), ("markdown", root / "board.md"), ("brain", root / "brain"), ("state", root / "state"), ("secrets", root / "secrets"),
                     ("project_touch", root / "touch"), ("fleet_names", root / "names.tsv"), ("rules", root / "RULES.md"), ("claude_credentials", root / "none.json")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, rep in ((r'(?m)^timezone = "[^"]*"', 'timezone = "Asia/Dubai"'), (r"(?m)^git = true", "git = false"), (r"(?m)^latest_lookups = true", "latest_lookups = false"),
                     (r"(?m)^port = 8020", f"port = {port}"), (r"(?m)^every_minutes = 10", "every_minutes = 1440"), (r"(?m)^panel = true", "panel = false")):
        toml, n = re.subn(pat, rep, toml, count=1); assert n == 1, pat
    if behind_name:
        write_secret(root / "identity.key", SECRET)
        toml += (f'\n[behind_frontdoor]\nidentity_secret_file = "{root}/identity.key"\nmembers_file = "{MEMBERS}"\nboard_name = "{behind_name}"\n')
    (root / "stackshot.toml").write_text(toml, encoding="utf-8")
    (root / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    (root / "fleet/a/sessions.json").write_text("{}"); (root / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (root / "store/next-id").write_text("10"); (root / "store/anchors.json").write_text("{}")
    (root / "store/projects.json").write_text(json.dumps({"pages": {PROJECT: {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "sparrow",
                                                                                "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": ""}}}))
    (root / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
    env = {**clean_env(), "HOME": str(root / "home"), "TMPDIR": str(root / "tmp"), "STACKSHOT_CONFIG": str(root / "stackshot.toml"), "STACKSHOT_FLEET_DIR": str(root / "fleet"),
           "STACKSHOT_AUTH": "google" if behind_name else "off"}
    if behind_name:
        env.update(STACKSHOT_GOOGLE_CLIENT_ID="client.example.test", STACKSHOT_GOOGLE_CLIENT_SECRET="not-a-real-secret-" + secrets.token_hex(8), STACKSHOT_PORTAL_TOKEN=bearer)
    return Proc(label, [sys.executable, os.path.join(STACK, "stackshot/web/server.py")], env, root, port, (200,)), root


# ------------------------------------------------------------------------------------------------ calls
async def _quiet(message):
    """The log lines a front door sends its client (a board that is down is one) are not this suite's output."""


def client(url, headers):
    return Client(StreamableHttpTransport(url, headers=headers), log_handler=_quiet)


async def _call(url, headers, tool, args):
    try:
        async with client(url, headers) as c:
            r = await c.call_tool(tool, args)
            return "ok", (r.content[0].text if r.content else "")
    except ToolError as e:
        return "refused", str(e)
    except Exception as e:      # noqa: BLE001  (a transport that is refused or does not answer)
        return "error", f"{type(e).__name__}: {str(e)[:200]}"


def call(url, headers, tool="anchors", args=None):
    return asyncio.run(_call(url, headers, tool, args if args is not None else {"project": PROJECT}))


def signed(who, secret=None, now=None):
    return ident.sign((secret or SECRET).encode(), who, now=now)


URL, BEARER, ROOT = {}, {}, {}


def door_headers(who, extra=None):
    """What the reverse proxy sends: the caller's identity in its header, and the caller's own credential (which stops at the front door)."""
    return {CALLER_HEADER: who, "Authorization": "Bearer CALLER-" + secrets.token_hex(12), **(extra or {})}


def door_call(who, board=None, add=None, extra=None):
    args = {"project": PROJECT, **({"board": board} if board else {}), **({"add": [add]} if add else {})}
    return call(URL["door"], door_headers(who, extra), "anchors", args)


def board_headers(board, who, secret=None, bearer=True, now=None):
    return {**({"Authorization": "Bearer " + BEARER[board]} if bearer else {}), ident.HEADER: signed(who, secret, now)}


def board_call(board, who, add=None, **kw):
    return call(URL[board], board_headers(board, who, **kw), "anchors", {"project": PROJECT, **({"add": [add]} if add else {})})


def recorded(board):
    """{url: who} of the anchors a board's store holds for the project: what the board itself wrote."""
    d = json.loads((ROOT[board] / "store/anchors.json").read_text())
    return {e["url"]: e.get("by") for e in d.get(PROJECT, [])}


COUNTER = itertools.count(1)
WANT = {MAIN: {}, SIDE: {}}      # what each board's record must hold, grown by every successful add and checked at the end of every round


def new_url():
    return f"https://github.com/example-owner/example-repo/pull/{next(COUNTER)}"


def add_through_door(who, board=None, extra=None):
    """An anchor added through the door as `who`; the board it must land on is `board`, or the caller's only one."""
    u = new_url()
    kind, text = door_call(who, board, add=u, extra=extra)
    return u, kind, text


def healthz_ok(door_url, seconds=15):
    """/healthz of the front door, asked until it is 200 (its health answer is kept a few seconds) or the time is out; → (status, JSON text)."""
    end = time.time() + seconds
    while True:
        st, body = raw(door_url + "/healthz", method="GET")
        if st == 200 or time.time() > end:
            return st, body
        time.sleep(0.5)


# ------------------------------------------------------------------------------------------------ the checks of one round
def one_round(label):
    boards = (MAIN, SIDE)
    write_members(S0); time.sleep(2.3)      # the file is older than the boards' racy window: what they read now is kept from their cache, so a change below must be seen by its stamp
    # ---- the door's own edge
    st, body = raw(URL["door"], method="POST")
    check(f"[{label}] door: a call with no identity header is refused 401, before any board", st == 401 and "no identity" in body, (st, body))
    st, body = healthz_ok(f"http://127.0.0.1:{DOOR_PORT}")
    check(f"[{label}] door: /healthz is 200 and names both boards up", st == 200 and all(json.loads(body)["backends"][b]["ok"] for b in boards), (st, body))
    kind, text = door_call(DAVE)
    check(f"[{label}] door: a caller on no board is told so", kind == "refused" and NOT_A_MEMBER in text, (kind, text))
    # ---- who is who, through the door
    for who, board, where in ((ALICE, MAIN, MAIN), (ALICE, SIDE, SIDE), (BOB, None, SIDE), (CAROL, None, MAIN)):
        u, kind, text = add_through_door(who, board)
        check(f"[{label}] door: {who} adds an anchor on {where}{' (named)' if board else ' (her only board)' if who == CAROL else ' (his only board)'}", kind == "ok", (kind, text))
        if kind == "ok":
            WANT[where][u] = who
    kind, text = door_call(ALICE)
    check(f"[{label}] door: a caller on two boards who names none is told which", kind == "refused" and "board required: you are on 2 boards (main, side)" in text, (kind, text))
    u = new_url(); kind, text = door_call(BOB, MAIN, add=u)
    check(f"[{label}] door: a board that is not the caller's is refused and nothing is written", kind == "refused" and "board 'main' is not one of your boards. You are on: side." in text and u not in recorded(MAIN), (kind, text))
    u, kind, text = add_through_door(BOB, SIDE, extra={ident.HEADER: signed(ALICE)})
    check(f"[{label}] door: an identity header the client sends itself is not taken for the caller: the board records the proxy's caller", kind == "ok" and recorded(SIDE).get(u) == BOB, (kind, text, recorded(SIDE).get(u)))
    if kind == "ok":
        WANT[SIDE][u] = BOB
    for board in boards:
        kind, text = door_call(ALICE, board)
        listed = {ln.split()[1] for ln in text.splitlines() if ln.startswith("- ")}
        check(f"[{label}] door: the anchors tool lists {board}'s own record, and none of the other board's", kind == "ok" and listed == set(WANT[board]), (kind, listed, WANT[board]))
    for board in boards:
        got = recorded(board)
        check(f"[{label}] {board}: its record holds each person the proxy named, for exactly the anchors made on it", got == WANT[board], (got, WANT[board]))
    # ---- the board's own check, the door left out
    kind, text = board_call(MAIN, ALICE)
    check(f"[{label}] main: a signed member with the board's bearer is served", kind == "ok", (kind, text))
    kind, text = board_call(SIDE, ALICE)
    check(f"[{label}] side: a signed member with the board's bearer is served", kind == "ok", (kind, text))
    for board, who in ((MAIN, BOB), (SIDE, CAROL), (MAIN, DAVE), (SIDE, DAVE)):
        u = new_url(); kind, text = board_call(board, who, add=u)
        check(f"[{label}] {board}: {who}, signed but not on this board's list, is refused by the tool with the board's sentence and nothing is written",
              kind == "refused" and f"Refused: {who} is not allowed on this board" in text and u not in recorded(board), (kind, text))
    for board in boards:
        good = board_headers(board, ALICE)
        st, body = raw(URL[board], good)
        check(f"[{label}] {board}: a signed call with the bearer is let through to the MCP endpoint", st == 200 and "serverInfo" in body, (st, body[:200]))
        v = good[ident.HEADER]; p = v.split(".")
        forged = {
            "no identity header": {k: x for k, x in good.items() if k != ident.HEADER},
            "an identity signed with another secret": board_headers(board, ALICE, secret=OTHER_SECRET),
            "another name under the old signature": {**good, ident.HEADER: ".".join([p[0], ident._b64(BOB.encode()), p[2], p[3]])},
            "a signature cut short": {**good, ident.HEADER: v[:-1]},
            "an identity signed 400 s ago": board_headers(board, ALICE, now=time.time() - 400),
            "an identity dated 300 s ahead": board_headers(board, ALICE, now=time.time() + 300),
            "a bare name that was never signed": {**good, ident.HEADER: ALICE},
        }
        for what, hdr in forged.items():
            st, body = raw(URL[board], hdr)
            want = NO_IDENTITY if what == "no identity header" else BAD_IDENTITY
            check(f"[{label}] {board}: {what} is refused 403 with the board's sentence", (st, body) == (403, want), (st, body))
        st, body = raw(URL[board], {}, method="GET")
        check(f"[{label}] {board}: an unsigned GET of the MCP endpoint is refused 403 too", (st, body) == (403, NO_IDENTITY), (st, body))
        st, body = raw(URL[board], board_headers(board, ALICE, bearer=False))
        check(f"[{label}] {board}: a signed call with no bearer is refused 401: the front door's credential is still the board's sign-in", st == 401, (st, body[:200]))
        wrong = {**board_headers(board, ALICE), "Authorization": "Bearer " + secrets.token_urlsafe(30)}
        st, body = raw(URL[board], wrong)
        check(f"[{label}] {board}: a signed call with a bearer that is not the board's is refused 401", st == 401, (st, body[:200]))
        st, body = raw(URL[board].rsplit("/", 1)[0] + "/healthz", method="GET")
        check(f"[{label}] {board}: the health route is open", st == 200, (st, body[:100]))
    # ---- a member removed and put back, on open sessions
    how = ("inplace", "replace", "rename")[ROUND_NO[0] % 3]; ROUND_NO[0] += 1
    asyncio.run(removal_flow(label, how))
    # ---- a members file that is broken or missing
    members_down(label)
    write_members(S0)
    for board in boards:
        got = recorded(board)
        check(f"[{label}] {board}: after the round its record is still exactly what was made on it (nothing from a refused call)", got == WANT[board], (got, WANT[board]))


ROUND_NO = [0]


def without_alice(how):
    """The members file with alice gone: deleted from it in place, from a replacement file, or (the same size) her key spelled differently."""
    d = {k: v for k, v in S0.items() if k != ALICE}
    if how == "rename":
        d = {("alicf@example.test" if k == ALICE else k): v for k, v in S0.items()}
        assert len(json.dumps(d)) == len(json.dumps(S0))
    write_members(d, "replace" if how == "replace" else "inplace")


async def removal_flow(label, how):
    async def go(c, **extra):
        try:
            r = await c.call_tool("anchors", {"project": PROJECT, **extra})
            return "ok", r.content[0].text if r.content else ""
        except ToolError as e:
            return "refused", str(e)
        except Exception as e:      # noqa: BLE001
            return "error", f"{type(e).__name__}: {str(e)[:200]}"
    async with client(URL["door"], door_headers(ALICE)) as dc, client(URL[MAIN], board_headers(MAIN, ALICE)) as cm, client(URL[SIDE], board_headers(SIDE, ALICE)) as cs:
        async def probe():
            return {"door main": await go(dc, board=MAIN), "door side": await go(dc, board=SIDE), "main": await go(cm), "side": await go(cs)}
        before = await probe()
        check(f"[{label}] open sessions: alice is served through the door and at each board", all(k == "ok" for k, _ in before.values()), before)
        without_alice(how)
        after = await probe()
        check(f"[{label}] open sessions ({how}): alice removed from the members file is refused at the next call on both boards through the door",
              all(after[k][0] == "refused" and NOT_A_MEMBER in after[k][1] for k in ("door main", "door side")), after)
        check(f"[{label}] open sessions ({how}): ... and at each board itself, with the board's sentence",
              all(after[k][0] == "refused" and f"Refused: {ALICE} is not allowed on this board" in after[k][1] for k in ("main", "side")), after)
        kind, text = await _call(URL["door"], door_headers(ALICE), "anchors", {"project": PROJECT, "board": MAIN})
        check(f"[{label}] a new session of alice's through the door is refused while she is removed", kind == "refused" and NOT_A_MEMBER in text, (kind, text))
        kind, text = await _call(URL["door"], door_headers(BOB), "anchors", {"project": PROJECT})
        kind2, text2 = await _call(URL["door"], door_headers(CAROL), "anchors", {"project": PROJECT})
        check(f"[{label}] the others of the file are not affected by it", kind == "ok" and kind2 == "ok", (kind, text, kind2, text2))
        write_members(S0, "replace" if how == "replace" else "inplace")
        back = await probe()
        check(f"[{label}] open sessions ({how}): alice put back is let in at the next call on both boards, through the door and at each board", all(k == "ok" for k, _ in back.values()), back)


def members_down(label):
    for what, make, undo in (("is broken", lambda: MEMBERS.write_text("{broken"), None),
                             ("is missing", lambda: MEMBERS.rename(MEMBERS.with_name("members.moved")), lambda: MEMBERS.with_name("members.moved").rename(MEMBERS))):
        make()
        try:
            kind, text = door_call(ALICE, MAIN)
            check(f"[{label}] a members file that {what}: the door lets nobody in", kind == "refused" and NOT_A_MEMBER in text, (kind, text))
            for board in (MAIN, SIDE):
                kind, text = board_call(board, ALICE)
                check(f"[{label}] a members file that {what}: {board} lets nobody in, a valid signature included", kind == "refused" and "is not allowed on this board" in text, (kind, text))
        finally:
            if undo:
                undo()
            write_members(S0)


# ------------------------------------------------------------------------------------------------ restarts
def board_down_up(label, proc, name):
    """Stop a board by its PID with alice removed, say what a call does while it is down, start it again and check the first calls after."""
    other = SIDE if name == MAIN else MAIN
    code = proc.stop()
    check(f"[{label}] {name}: stopped by its PID, and its port is free", code is not None and port_free(proc.port), (code, proc.tail()))
    kind, text = door_call(ALICE, name)
    check(f"[{label}] {name} down: a call through the door says the board did not answer", kind == "refused" and f"board '{name}' did not answer" in text, (kind, text))
    kind, text = door_call(ALICE, other)
    check(f"[{label}] {name} down: the other board answers through the door", kind == "ok", (kind, text))
    st, _ = raw(URL["door"].rsplit("/", 1)[0] + "/healthz", method="GET")
    check(f"[{label}] {name} down: /healthz of the door is 503", st == 503, st)
    without_alice("inplace")        # the removal is in force when the board starts: it must read the file afresh, never remember her
    check(f"[{label}] {name}: starts again on its port", proc.start(), proc.tail())
    kind, text = board_call(name, ALICE)
    check(f"[{label}] {name} restarted with alice removed: the board refuses her at its first call", kind == "refused" and f"Refused: {ALICE} is not allowed on this board" in text, (kind, text))
    kind, text = door_call(ALICE, other)
    check(f"[{label}] {name} restarted with alice removed: the door refuses her", kind == "refused" and NOT_A_MEMBER in text, (kind, text))
    kind, text = door_call(BOB if name == SIDE else CAROL)
    check(f"[{label}] {name} restarted: a member that stayed is served at the first call through the door", kind == "ok", (kind, text))
    write_members(S0)
    kind, text = door_call(ALICE, name)
    check(f"[{label}] {name} restarted: alice put back is served at the first call, with no stale answer of the board's being down", kind == "ok", (kind, text))
    st, body = healthz_ok(URL["door"].rsplit("/", 1)[0])
    check(f"[{label}] {name} restarted: /healthz of the door is back to 200 inside a few seconds", st == 200, (st, body))


def door_down_up(label, proc):
    code = proc.stop()
    check(f"[{label}] door: stopped by its PID, and its port is free", code is not None and port_free(proc.port), (code, proc.tail()))
    st, _ = raw(URL["door"], door_headers(ALICE))
    check(f"[{label}] door down: nothing answers on its port", st == 0, st)
    kind, text = board_call(MAIN, ALICE)
    kind2, text2 = board_call(SIDE, ALICE)
    check(f"[{label}] door down: each board still takes a call signed for it", kind == "ok" and kind2 == "ok", (kind, text, kind2, text2))
    without_alice("inplace")
    check(f"[{label}] door: starts again on its port", proc.start(), proc.tail())
    kind, text = door_call(ALICE, MAIN)
    check(f"[{label}] door restarted with alice removed: she is refused at its first call", kind == "refused" and NOT_A_MEMBER in text, (kind, text))
    kind, text = door_call(BOB)
    check(f"[{label}] door restarted: a member that stayed is served at the first call", kind == "ok", (kind, text))
    write_members(S0)
    kind, text = door_call(ALICE, MAIN)
    check(f"[{label}] door restarted: alice put back is served at the first call", kind == "ok", (kind, text))


def rotate_secret():
    """The signing secret changed in the three files that hold it, one after another, with no restart: each read is at the next call."""
    global SECRET
    old, new = SECRET, secrets.token_urlsafe(24)
    for b in (MAIN, SIDE):
        write_secret(ROOT[b] / "identity.key", new)
    kind, text = door_call(ALICE, MAIN)
    check("rotation: the boards hold the new secret and the door the old: the board refuses the door and the door says the board did not answer", kind == "refused" and "board 'main' did not answer" in text, (kind, text))
    write_secret(T / "door/identity.key", new)
    SECRET = new
    for b in (MAIN, SIDE):
        kind, text = door_call(ALICE, b)
        check(f"rotation: the door holds the new secret too: a call through it reaches {b} with no restart", kind == "ok", (kind, text))
        st, body = raw(URL[b], board_headers(b, ALICE, secret=old))
        check(f"rotation: {b} refuses an identity signed with the old secret", (st, body) == (403, BAD_IDENTITY), (st, body))
        st, body = raw(URL[b], board_headers(b, ALICE))
        check(f"rotation: {b} accepts one signed with the new secret", st == 200, (st, body[:100]))


# ------------------------------------------------------------------------------------------------ the run
DOOR_PORT = 0
PROCS = []


def main():
    global DOOR_PORT
    door_port, main_port, side_port, plain_port = free_ports(4)
    DOOR_PORT = door_port
    check("setup: four distinct free loopback ports, none a well-known one of an instance", len({door_port, main_port, side_port, plain_port}) == 4 and all(p > 1024 and p not in (8010, 8020) for p in (door_port, main_port, side_port, plain_port)))
    (T / "door").mkdir(); write_members(S0)
    bearers = {MAIN: secrets.token_urlsafe(36), SIDE: secrets.token_urlsafe(36)}
    BEARER.update(bearers)
    pm, ROOT[MAIN] = build_board(MAIN, main_port, MAIN, bearers[MAIN])
    ps, ROOT[SIDE] = build_board(SIDE, side_port, SIDE, bearers[SIDE])
    pp, ROOT["plain"] = build_board("plain", plain_port, None, "")
    URL.update({MAIN: f"http://127.0.0.1:{main_port}/mcp", SIDE: f"http://127.0.0.1:{side_port}/mcp", "plain": f"http://127.0.0.1:{plain_port}/mcp", "door": f"http://127.0.0.1:{door_port}/mcp"})
    # the front door: its own config, secret and bearers, the one members file
    write_secret(T / "door/identity.key", SECRET)
    rows = ""
    for n in (MAIN, SIDE):
        rows += f'\n[[frontdoor.backends]]\nname = "{n}"\nurl = "{URL[n]}"\ntoken_file = "{write_secret(T / "door" / (n + ".token"), bearers[n])}"\n'
    (T / "door/stackshot.toml").write_text(f'[frontdoor]\nlisten_port = {door_port}\nidentity_header = "{CALLER_HEADER}"\nidentity_secret_file = "{T}/door/identity.key"\n'
                                           f'members_file = "{MEMBERS}"\n{rows}')
    for d in ("home", "tmp"):
        (T / "door" / d).mkdir()
    door = Proc("door", [sys.executable, "-m", "stackshot.frontdoor"], {**clean_env(), "PYTHONPATH": STACK, "HOME": str(T / "door/home"), "TMPDIR": str(T / "door/tmp"),
                                                                       "STACKSHOT_CONFIG": str(T / "door/stackshot.toml")}, T / "door", door_port, (200, 503))
    PROCS.extend([door, pm, ps, pp])
    try:
        for p in (pm, ps, pp):
            check(f"setup: {p.name} board starts on its own port", p.start(), p.tail())
        check("setup: the front door starts on its own port", door.start(), door.tail())
        if fails:
            return
        r = subprocess.run([sys.executable, "-m", "stackshot.frontdoor", "--check"], env=door.env, cwd=str(T / "door"), capture_output=True, text=True, timeout=120)
        check("setup: the front door's own check names both boards", r.returncode == 0 and "board main" in r.stdout and "board side" in r.stdout, (r.returncode, r.stdout[-300:], r.stderr[-300:]))
        one_round("start")
        door_down_up("door restart", door); one_round("after the door restart")
        board_down_up("main restart", pm, MAIN); one_round("after the main restart")
        board_down_up("side restart", ps, SIDE); one_round("after the side restart")
        rotate_secret()
        # a board with no [behind_frontdoor] table is as it was
        st, body = raw(URL["plain"])
        check("plain board (no table): an unsigned call is served as before", st == 200 and "serverInfo" in body, (st, body[:200]))
        st, body = raw(URL["plain"], {ident.HEADER: "v1.not-a-signature"})
        check("plain board: a header of the signed identity's name is ignored, never refused", st == 200 and "serverInfo" in body, (st, body[:200]))
        u = new_url()
        kind, text = call(URL["plain"], {ident.HEADER: signed(ALICE)}, "anchors", {"project": PROJECT, "add": [u]})
        check("plain board: a tool call with no sign-in is served, and a signed header of the door changes nothing", kind == "ok" and recorded_plain().get(u) == "", (kind, text, recorded_plain()))
        check("plain board: its log says nothing of a front door", "front door" not in pp.tail(), pp.tail())
        # the end state: every board's record kept through every restart
        for board in (MAIN, SIDE):
            check(f"end: {board}'s record still holds every anchor of the run, each by the person who made it", recorded(board) == WANT[board] and len(WANT[board]) >= 4 * 2, (recorded(board), WANT[board]))
        check("end: nothing the run did made a process stop by itself", all(p.running() for p in PROCS), [(p.name, p.p.poll(), p.tail()) for p in PROCS if not p.running()])
    finally:
        for p in PROCS:
            p.stop()
    check("end: every process has ended and every port is free", all(not p.running() and port_free(p.port) for p in PROCS), [p.port for p in PROCS if not port_free(p.port)])


def recorded_plain():
    d = json.loads((ROOT["plain"] / "store/anchors.json").read_text())
    return {e["url"]: e.get("by") for e in d.get(PROJECT, [])}


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:      # noqa: BLE001  (a crash is a failed run that says where, never a silent exit)
        import traceback; traceback.print_exc()
        fails.append(f"the run stopped with {type(e).__name__}")
        for p in PROCS:
            p.stop()
            print(f"--- {p.name} stderr tail ---\n{p.tail()}", flush=True)
    if fails and not os.environ.get("KEEP_SCRATCH"):
        for p in PROCS:
            if p.tail().strip():
                print(f"--- {p.name} stderr tail ---\n{p.tail()}", flush=True)
    print(("ok" if not fails else "FAILED") + f": front door run scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""), flush=True)
    sys.exit(1 if fails else 0)
