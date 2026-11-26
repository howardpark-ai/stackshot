"""Scenario test for a board behind the front door (stage 2 of the front door): the board checks the signed identity of a call, and reads its members from the front door's members file.

Offline and hermetic: made-up config files, the real board server (`stackshot.web.server`) on 127.0.0.1 in this process, no store beyond one fixture item, no network. Two parts, each in a
process of its own (the board reads its config and keeps module state at import): the board behind a front door (`on`) and a board with no `[behind_frontdoor]` table (`off`).

Part `on` covers:
  * the settings (`core/behind_door.py`): an absent table is all off; every key read; a wrong value is told in the config notes and never read as "off" (a board told to check identities
    that cannot read its secret refuses every call; one told to read its members that cannot has nobody); `[[members]]` is not read while the front door's list is the source;
  * the check of one signed identity (`check`): accepted inside the replay window; refused with no identity, an altered one, one signed with another secret, one older than the window, one dated
    ahead of the clock, a secret that is missing, group-readable or too short; a custom window; a rotated secret applies at once; no refusal text holds a secret or says which part was wrong;
  * the members read from the front door's file: only the members listed for this board's name, in the file's order; the placeholder (which no address matches) when the file lists nobody,
    cannot be read, is no JSON object or the board has no name; a change applies to the next call, also a rewrite of the same size inside the clock's tick and a removal from a file old enough to be cached; two identities that differ only in case are one member (its sign-in address is the lower-case one: the sign-in service lower-cases every address); the file's format
    (member -> boards) read for this board, and the old `[[members]]` list set aside;
  * the guard (`web/door_guard.py`) as an ASGI wrapper: the MCP path is guarded with and without a trailing slash and every method, another path and a lifespan are not, the verified identity is put
    on the scope and a client-written header of any name cannot put one there, a refusal is HTTP 403 with the sentence and the wrapped app is never reached;
  * the real board over HTTP: an unsigned call, a call signed with another secret, an altered identity, an expired one and one dated ahead are refused 403 with the sentence and reach no tool;
    a signed call lists the tools and reads an item; an identity the board's members do not list is refused by the tool (`Refused: ... is not allowed on this board`); a member added or removed
    in the file is let in or out on the open session's next call; the open routes (`/healthz`) are as they were; a request that never passed the guard has no identity (`_who` refuses it, a good-looking signed header on it included, and an identity the members do not list);
    a signature cut short and an empty identity under a valid signature are refused at the check, the guard and the wire;
  * the front door's own transport (`frontdoor/backend.py`) against the real board: what the front door sends is accepted, and another secret is not;
  * the sign-in's start (`_auth`): a board that reads its members from a front door starts with nobody listed yet; any other board with no address to name stops as it always did;
  * the old names (`frontdoor/identity.py`, `frontdoor/config.py`) are the shared code.

Part `off` covers a board with no table: its `/mcp` is not wrapped, an unsigned call and one with a signed header are served as before, `_who` asks nothing of a request, `[[members]]` is the
list, and the config notes say nothing about a front door.

    tests/run-suite frontdoor_board        -> exit 0 / 1"""
import os, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
PARTS = ("on", "off")


def setup(part):
    """The instance of a part: a config file, the store fixture and the environment, as client_scenario makes them; → (T, the secret writer, the paths)."""
    import json, pathlib, re
    sys.path.insert(0, SCR); sys.path.insert(0, STACK)
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix="doorboard-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1

    def secret(name, value, mode=0o600):
        p = T / name
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w") as f:
            f.write(value + "\n")
        os.chmod(p, mode)
        return str(p)
    paths = {"secret": secret("door.key", "door-secret-0123456789abcdef"), "members": str(T / "members.json")}
    if part == "on":
        (T / "members.json").write_text(json.dumps({"alice@example.test": ["main", "side"], "bob@example.test": ["side"], "carol@example.test": ["main"]}))
        toml += (f'\n[behind_frontdoor]\nidentity_secret_file = "{paths["secret"]}"\nidentity_max_age_seconds = 120\n'
                 f'members_file = "{paths["members"]}"\nboard_name = "main"\n')
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    for d in ("store/a", "fleet/a", "state", "brain/projects"): (T / d).mkdir(parents=True)
    (T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "sparrow", "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": ""}}}))
    (T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] door fixture item", "description": "A thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": "sparrow", "project": "projects/alpha"}}))
    (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
    return T, secret, paths


class Fixture:
    """The checks of one part and a stand-in listener for the board's HTTP app."""
    def __init__(self):
        self.fails, self.ran = [], []

    def check(self, name, cond, got=None):
        self.ran.append(name)
        if not cond:
            self.fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))


def auth_start(oauth):
    """What the board's sign-in does at its start with auth set to google and a fake client: "started", or the name of the error it stops with (the environment is put back)."""
    keys = ("STACKSHOT_AUTH", "STACKSHOT_GOOGLE_CLIENT_ID", "STACKSHOT_GOOGLE_CLIENT_SECRET")
    old = {k: os.environ.get(k) for k in keys}
    try:
        os.environ.update(STACKSHOT_AUTH="google", STACKSHOT_GOOGLE_CLIENT_ID="client.example.test", STACKSHOT_GOOGLE_CLIENT_SECRET="not-a-real-secret-0123456789")
        try:
            oauth._auth(); return "started"
        except BaseException as e:
            return type(e).__name__
    finally:
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


def serve(app):
    """The ASGI app on 127.0.0.1:<ephemeral port>, in its own thread; → (server, thread, port). stop(...) ends it."""
    import socket, threading, time, uvicorn
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on", timeout_graceful_shutdown=3))
    th = threading.Thread(target=lambda: srv.run(sockets=[sock]), daemon=True); th.start()
    for _ in range(200):
        if srv.started: return srv, th, sock, port
        time.sleep(0.05)
    raise RuntimeError("the board did not start")


def stop(srv, th, sock):
    srv.should_exit = True; th.join(15)
    try: sock.close()
    except OSError: pass


def post(url, headers=None, body=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}', method="POST"):
    """(status, text) of one raw request; a refusal's body is read."""
    import urllib.error, urllib.request
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(headers or {})}
    req = urllib.request.Request(url, data=body if method == "POST" else None, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000).decode("utf-8", "replace")


# ================================================================ part on: the board behind a front door
def part_on():
    import asyncio, json, pathlib, stat, time, tomllib
    T, secret, paths = setup("on")
    F = Fixture(); check = F.check
    import logging; logging.disable(logging.INFO)
    from stackshot.core import behind_door as door, config as cfgmod, frontdoor_files as ffiles, frontdoor_identity as ident, members as mem
    from stackshot.web import door_guard as guard
    from stackshot.web import server
    from stackshot.web.auth import oauth
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    from fastmcp.exceptions import ToolError
    SECRET, OTHER = "door-secret-0123456789abcdef", "another-secret-0123456789abc"
    sig = lambda who, secret_=SECRET, now=None: ident.sign(secret_.encode(), who, now=now)
    ALICE, BOB, CAROL, DAVE = "alice@example.test", "bob@example.test", "carol@example.test", "dave@example.test"
    cfgd = lambda text: tomllib.loads(text)
    def raises_value(fn, *a):
        try: fn(*a); return False
        except ValueError: return True

    # ---- 1. the settings
    off, notes_off = door.parse(cfgd("[auth]\nmode = 'off'\n"))
    check("settings: no [behind_frontdoor] table is all off, with nothing to tell", off == door.Settings() and not off.identity and not off.members and notes_off == [], (off, notes_off))
    full, n_full = door.parse(cfgd('[behind_frontdoor]\nidentity_secret_file = "/k"\nidentity_max_age_seconds = 90\nmembers_file = "/m"\nboard_name = "main"\n'))
    check("settings: every key is read", full == door.Settings(True, "/k", 90.0, True, "/m", "main") and n_full == [], (full, n_full))
    only_id, n_id = door.parse(cfgd('[behind_frontdoor]\nidentity_secret_file = "/k"\n'))
    check("settings: the identity check alone leaves the members to the board's own list, and the replay window is five minutes", only_id.identity and not only_id.members and only_id.max_age == 300.0 and n_id == [], (only_id, n_id))
    only_mem, n_mem = door.parse(cfgd('[behind_frontdoor]\nmembers_file = "/m"\nboard_name = "main"\n'))
    check("settings: the members alone check no identity", not only_mem.identity and only_mem.members, only_mem)
    bad_id, n_bad_id = door.parse(cfgd("[behind_frontdoor]\nidentity_secret_file = 5\n"))
    check("settings: an identity_secret_file that is no path still means check (never off), and the notes say the board accepts no call", bad_id.identity and bad_id.secret_file == "" and any("accepts no call" in n for n in n_bad_id), (bad_id, n_bad_id))
    bad_all, n_bad_all = door.parse(cfgd("behind_frontdoor = 3\n"))
    check("settings: a table that is no table checks and has no members, and the notes say so", bad_all.identity and bad_all.members and any("is not a table" in n for n in n_bad_all), (bad_all, n_bad_all))
    for v in ("0", "-5", "7200", "true", "'x'"):
        s_, n_ = door.parse(cfgd(f"[behind_frontdoor]\nidentity_secret_file = '/k'\nidentity_max_age_seconds = {v}\n"))
        check(f"settings: a replay window of {v} reads as five minutes and is told", s_.max_age == 300.0 and any("identity_max_age_seconds" in n for n in n_), (s_, n_))
    s_, n_ = door.parse(cfgd('[behind_frontdoor]\nmembers_file = "/m"\n'))
    check("settings: members_file with no board_name has nobody and says so", s_.members and any("board_name is missing" in n for n in n_), n_)
    s_, n_ = door.parse(cfgd('[behind_frontdoor]\nmembers_file = "/m"\nboard_name = "no good"\n'))
    check("settings: a board_name that is no backend name has nobody and says so", any("board_name" in n and "no good" in n for n in n_), n_)
    s_, n_ = door.parse(cfgd('[behind_frontdoor]\nmembers_file = ""\nboard_name = "main"\n'))
    check("settings: a members_file that is no path has nobody and says so", s_.members and any("members_file is not a path" in n for n in n_), n_)
    s_, n_ = door.parse(cfgd('[behind_frontdoor]\nboard_name = "main"\n'))
    check("settings: a board_name with no members_file is told", any("used only with members_file" in n for n in n_), n_)
    s_, n_ = door.parse(cfgd('[behind_frontdoor]\nmembers_file = "/m"\nboard_name = "main"\n[[members]]\nname = "Pat"\nemails = ["pat@example.test"]\n'))
    check("settings: [[members]] beside the front door's list is told as not read", any("[[members]] is not read" in n for n in n_), n_)
    pub = T / "pub.key"; pub.write_text("a-group-readable-secret-0123456789\n"); os.chmod(pub, 0o644)
    n_pub = door.notes(cfgd(f'[behind_frontdoor]\nidentity_secret_file = "{pub}"\n'))
    check("notes: a secret file group or others can read is told, without its content", any("readable by group or others" in n for n in n_pub) and not any("group-readable-secret" in n for n in n_pub), n_pub)
    check("the config notes carry the [behind_frontdoor] lines, and drop the owner placeholder lines for a board whose members are the front door's",
          cfgmod.behind_door_notes(cfgd("behind_frontdoor = 3\n")) == door.notes(cfgd("behind_frontdoor = 3\n")) and
          not [n for n in cfgmod.notes(cfgd('[behind_frontdoor]\nmembers_file = "/m"\nboard_name = "main"\n')) if "has no owner" in n],
          [n for n in cfgmod.notes(cfgd('[behind_frontdoor]\nmembers_file = "/m"\nboard_name = "main"\n')) if "owner" in n])
    check("the running config: no note about this board's front door when it is set right", not [n for n in cfgmod.notes() if "behind_frontdoor" in n], [n for n in cfgmod.notes() if "behind_frontdoor" in n])
    check("the table is restart-only", "behind_frontdoor" in cfgmod.RESTART_ONLY)

    # ---- 2. the check of one signed identity
    NOW = 1_800_000_000.0
    c_ok = door.check(sig(ALICE, now=NOW), now=NOW + 10)
    check("check: a fresh signed identity is accepted and names the caller", c_ok.who == ALICE and c_ok.refusal == "", c_ok)
    check("check: no header is refused with the sentence for it", door.check(None) == door.Check(refusal=door.NO_IDENTITY) and door.check("") == door.Check(refusal=door.NO_IDENTITY) and door.check("   ") == door.Check(refusal=door.NO_IDENTITY))
    check("check: a value that is no signed identity is refused", door.check("alice@example.test").refusal == door.BAD_IDENTITY and door.check("v1.x.y.z").refusal == door.BAD_IDENTITY)
    check("check: an identity signed with another secret is refused", door.check(sig(ALICE, OTHER, now=NOW), now=NOW).refusal == door.BAD_IDENTITY)
    v = sig(ALICE, now=NOW); parts = v.split("."); forged = ".".join([parts[0], ident._b64(BOB.encode()), parts[2], parts[3]])
    check("check: an altered identity (another name with the old signature) is refused", door.check(forged, now=NOW).refusal == door.BAD_IDENTITY)
    forged_t = ".".join([parts[0], parts[1], str(int(NOW) + 1000), parts[3]])
    check("check: an altered time (a later one with the old signature) is refused", door.check(forged_t, now=NOW + 1000).refusal == door.BAD_IDENTITY)
    for cut in (1, 16, 63, 64):
        check(f"check: a signature cut short by {cut} character{'s' if cut > 1 else ''} is refused (a prefix of the right hash is not the hash)", door.check(v[:-cut], now=NOW).refusal == door.BAD_IDENTITY, (cut, door.check(v[:-cut], now=NOW)))
    check("check: a value whose signature is missing is refused", door.check(".".join(parts[:3]) + ".", now=NOW).refusal == door.BAD_IDENTITY and door.check(".".join(parts[:3]), now=NOW).refusal == door.BAD_IDENTITY)
    body_e = f"v1.{ident._b64(b'')}.{int(NOW)}"; empty_id = f"{body_e}.{ident._mac(SECRET.encode(), body_e)}"
    check("check: an empty identity under a valid signature (hand-built, the signer refuses to make one) is refused, never accepted as nobody", door.check(empty_id, now=NOW) == door.Check(refusal=door.BAD_IDENTITY), door.check(empty_id, now=NOW))
    check("check: the signer itself will not sign an empty or blank identity", all(raises_value(ident.sign, SECRET.encode(), w) for w in ("", "   ")))
    check("check: the replay window is the board's own (120 s here): 100 s old is accepted", door.check(sig(ALICE, now=NOW), now=NOW + 100).who == ALICE)
    check("check: ... 121 s old is refused, the five-minute default would have accepted it", door.check(sig(ALICE, now=NOW), now=NOW + 121).refusal == door.BAD_IDENTITY)
    check("check: a time 20 s ahead of the board's clock is accepted (two clocks), 31 s ahead is refused", door.check(sig(ALICE, now=NOW + 20), now=NOW).who == ALICE and door.check(sig(ALICE, now=NOW + 31), now=NOW).refusal == door.BAD_IDENTITY)
    check("check: every refusal sentence names no secret and does not say which part was wrong", all(SECRET not in t and OTHER not in t for t in (door.NO_IDENTITY, door.BAD_IDENTITY, door.NO_SECRET)) and door.BAD_IDENTITY == door.check(forged, now=NOW).refusal == door.check(sig(ALICE, OTHER, now=NOW), now=NOW).refusal)
    os.chmod(paths["secret"], 0o644)
    r_mode = door.check(sig(ALICE))
    check("check: a secret file group or others can read is not used: every call is refused, with the sentence for it", r_mode == door.Check(refusal=door.NO_SECRET), r_mode)
    os.chmod(paths["secret"], 0o600)
    check("check: and fixing the mode is read at the next call", door.check(sig(ALICE)).who == ALICE)
    os.rename(paths["secret"], paths["secret"] + ".gone")
    check("check: a missing secret file refuses every call", door.check(sig(ALICE)) == door.Check(refusal=door.NO_SECRET))
    os.rename(paths["secret"] + ".gone", paths["secret"])
    pathlib.Path(paths["secret"]).write_text("short\n")
    check("check: a secret that is too short is not used", door.check(sig(ALICE)) == door.Check(refusal=door.NO_SECRET))
    pathlib.Path(paths["secret"]).write_text(OTHER + "\n")
    check("check: a rotated secret applies at the next call: the old one is refused, the new one accepted", door.check(sig(ALICE)).refusal == door.BAD_IDENTITY and door.check(sig(ALICE, OTHER)).who == ALICE)
    pathlib.Path(paths["secret"]).write_text(SECRET + "\n"); os.chmod(paths["secret"], 0o600)
    check("check: a secret file's path is not told to the caller", all(str(T) not in t for t in (door.NO_IDENTITY, door.BAD_IDENTITY, door.NO_SECRET)))

    # ---- 3. the members the board reads from the front door
    mfile = pathlib.Path(paths["members"])
    def listed(cfg_text=None): return door.members(cfgd(cfg_text) if cfg_text else None)
    check("members: the board's own name picks its members out of the front door's file, in the file's order", listed() == (ALICE, CAROL), listed())
    check("members: the list of the board is the front door's: names and sign-in addresses are the identities", [(p.name, p.emails) for p in mem.members()] == [(ALICE, (ALICE,)), (CAROL, (CAROL,))], mem.members())
    check("members: person_of_email finds a listed member and nobody else", mem.person_of_email(ALICE) and mem.person_of_email(CAROL) and mem.person_of_email(BOB) is None and mem.person_of_email(DAVE) is None and mem.person_of_email("") is None)
    check("members: first() is the file's first member, emails() every address", mem.first().name == ALICE and mem.emails() == [ALICE, CAROL])
    other_board = f'[behind_frontdoor]\nmembers_file = "{paths["members"]}"\nboard_name = "side"\n'
    check("members: another board's name reads the same file for itself (member -> boards, read for one board)", listed(other_board) == (ALICE, BOB), listed(other_board))
    check("members: a backend name the file does not know has no members", listed(other_board.replace('"side"', '"nope"')) == ())
    check("members: the old list is set aside (a board with [[members]] and the front door's list has the door's)",
          [p.name for p in mem.build(cfgd(other_board + '[[members]]\nname = "Pat"\nemails = ["pat@example.test"]\n'))] == [ALICE, BOB])
    check("members: a board with no members_file keeps its own list exactly (the old keys here)",
          [(p.name, p.emails) for p in mem.build(cfgd('[instance]\nowner = "Pat"\n[auth]\nallowed_emails = ["pat@example.test"]\n[behind_frontdoor]\nidentity_secret_file = "/k"\n'))] == [("Pat", ("pat@example.test",))])
    mfile.write_text(json.dumps({"alice@example.test": ["main"], "bob@example.test": ["main"], "carol@example.test": []}))
    check("members: a change of the file applies to the next call", mem.person_of_email(BOB) is not None and mem.person_of_email(CAROL) is None and mem.emails() == [ALICE, BOB], mem.emails())
    A, B = '{"aaa@example.test": ["main"]}', '{"bbb@example.test": ["main"]}'
    mfile.write_text(A); first = mem.emails(); mfile.write_text(B); second = mem.emails(); mfile.write_text(A); third = mem.emails()
    check("members: a rewrite of the same size right after a read (inside the clock's tick) is read, too", (first, second, third) == (["aaa@example.test"], ["bbb@example.test"], ["aaa@example.test"]), (first, second, third))
    # the same two reads with a stamp the file system cannot tell apart (what a rewrite inside the clock's tick looks like): a file written a moment ago is read again, an old one is kept from the cache
    class _Stat:
        def __init__(self, age): self.st_mtime = time.time() - age; self.st_mtime_ns = int(self.st_mtime * 1e9); self.st_ctime_ns = self.st_mtime_ns; self.st_size = len(A); self.st_ino = 1
    class _OsWith:
        def __init__(self, age): self.fixed = _Stat(age)
        def stat(self, p): return self.fixed
        def __getattr__(self, n): return getattr(os, n)
    real_os = door.os
    try:
        for age, want in ((0.1, ["bbb@example.test"]), (500.0, ["aaa@example.test"])):
            door._cache.clear(); door.os = _OsWith(age)
            mfile.write_text(A); door.members(); mfile.write_text(B)
            got = list(door.members() or ())
            check(f"members: with an unchanged stamp, a file {'written 0.1 s ago is read again' if age < 1 else 'written 500 s ago is kept from the cache'}", got == want, (age, got))
    finally:
        door.os = real_os; door._cache.clear()
    # a file older than the racy window when it is read is kept in the cache while its stamp is the same, and a change after it is read at the next call: a member removed with the same size and
    # the same modified time put back is told by the change time alone
    old_t = time.time() - 600
    def aged(text): mfile.write_text(text); os.utime(mfile, (old_t, old_t))
    S1 = json.dumps({"alice@example.test": ["main"], "bob@example.test": ["main"]}); S2 = json.dumps({"alice@example.test": ["main"], "bob@example.test": ["side"]}); assert len(S1) == len(S2)
    door._cache.clear(); aged(S1)
    r1 = list(door.members() or ()); kept = [c[1] for c in door._cache.values()]
    check("members: a file older than the racy window is read, and kept in the cache", r1 == [ALICE, BOB] and kept == [True], (r1, kept))
    time.sleep(0.05); aged(S2)
    r2 = list(door.members() or ())
    check("members: a member removed from a file the cache holds (same size, same modified time) is gone at the next call, never listed from the cache", r2 == [ALICE], r2)
    time.sleep(0.05); aged(S1); r3 = list(door.members() or ())
    check("members: and added back, the member is there at the next call", r3 == [ALICE, BOB], r3)
    door._cache.clear()
    for label, body in (("an empty file", ""), ("a file that is no JSON", "{not json"), ("a JSON list", '["alice@example.test"]'), ("a file that lists nobody for the board", '{"alice@example.test": ["side"]}')):
        mfile.write_text(body)
        check(f"members: {label} leaves nobody (the placeholder, which no address matches), never everybody",
              mem.person_of_email(ALICE) is None and mem.person_of_email(BOB) is None and mem.members()[0].placeholder and mem.emails() == [], (mem.members(), body))
    mfile.write_text(json.dumps({"alice@example.test": "main", "bob@example.test": ["main", 5, None]}))
    check("members: a member whose value is no list is on nothing; non-text entries of a list are dropped", mem.emails() == [BOB], mem.emails())
    mfile.rename(T / "members.moved")
    check("members: a missing file leaves nobody", mem.person_of_email(ALICE) is None and mem.members()[0].placeholder)
    (T / "members.moved").rename(mfile)
    mfile.write_text("{}")
    check("sign-in start: a board that reads its members from a front door starts with auth on although the file lists nobody yet (the portal identity is empty then)", auth_start(oauth) == "started", auth_start(oauth))
    mfile.write_text(json.dumps({"alice@example.test": ["main", "side"], "bob@example.test": ["side"], "carol@example.test": ["main"]}))
    check("members: the file back as it was, the board's members are back", mem.emails() == [ALICE, CAROL])
    mfile.write_text(json.dumps({"x" * 70000: ["main"]}))
    check("members: a file over 64 KiB is not used (nobody)", mem.person_of_email(ALICE) is None)
    mfile.write_text(json.dumps({"alice@example.test": ["main", "side"], "bob@example.test": ["side"], "carol@example.test": ["main"]}))
    check("members: the identity matches as written (another case is another address, as a sign-in always was)", mem.person_of_email("ALICE@example.test") is None)
    mfile.write_text(json.dumps({"Alice@example.test": ["main"], "alice@example.test": ["main"], "carol@example.test": ["main"]}))
    check("members: two identities that differ only in case are one member, the first listed (names are unique without regard to case, and a name is looked up without it): never two people",
          listed() == ("Alice@example.test", CAROL) and mem.emails() == ["alice@example.test", CAROL] and mem.person_of("alice@example.test") is mem.person_of("Alice@example.test") and mem.person_of_email("alice@example.test") is mem.person_of("Alice@example.test"),
          (listed(), mem.emails()))
    mfile.write_text(json.dumps({"alice@example.test": ["main"], "Alice@example.test": ["main"], "carol@example.test": ["main"]}))
    check("members: ... and the first of the file is the one kept, whichever case it is in", listed() == (ALICE, CAROL) and mem.person_of_email("Alice@example.test") is None, listed())
    mfile.write_text(json.dumps({"alice@example.test": ["main", "side"], "bob@example.test": ["side"], "carol@example.test": ["main"]}))

    # ---- 4. the guard as an ASGI wrapper
    seen = []
    async def stub(scope, receive, send):
        seen.append(dict(scope))
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 204, "headers": []}); await send({"type": "http.response.body", "body": b""})
    def call(g, path, headers=(), method="GET", typ="http"):
        sent = []
        async def send(m): sent.append(m)
        async def recv(): return {"type": "http.request", "body": b""}
        scope = {"type": typ, "path": path, "method": method, "headers": [(k.encode(), v.encode()) for k, v in headers]}
        asyncio.run(g(scope, recv, send)); return scope, sent
    def empty_id_now():
        b = f"v1.{ident._b64(b'')}.{int(time.time())}"
        return f"{b}.{ident._mac(SECRET.encode(), b)}"
    G = guard.DoorGuard(stub, "/mcp")
    good = sig(ALICE)
    n0 = len(seen)
    sc, sent = call(G, "/mcp", [(ident.HEADER, good)], "POST")
    check("guard: a signed call to the MCP path reaches the app with the verified identity on its scope", len(seen) == n0 + 1 and sc.get(door.SCOPE_KEY) == ALICE and door.caller_of(sc) == ALICE and sent[0]["status"] == 204, (sc, sent))
    n1 = len(seen)
    sc, sent = call(G, "/mcp", [], "POST")
    check("guard: an unsigned call is refused 403 with the sentence, as plain text, and the app is not reached", len(seen) == n1 and sent[0]["status"] == 403 and sent[1]["body"].decode() == door.NO_IDENTITY
          and dict(sent[0]["headers"])[b"content-type"].startswith(b"text/plain") and dict(sent[0]["headers"])[b"content-length"] == str(len(door.NO_IDENTITY)).encode() and door.caller_of(sc) == "", (sent, len(seen), n1))
    for label, value in (("a signature cut short", good[:-1]), ("an empty identity under a valid signature", empty_id_now())):
        sc, sent = call(G, "/mcp", [(ident.HEADER, value)], "POST")
        check(f"guard: {label} is refused 403 and the app is not reached", len(seen) == n1 and sent[0]["status"] == 403 and sent[1]["body"].decode() == door.BAD_IDENTITY and door.caller_of(sc) == "", (label, sent))
    sc, sent = call(G, "/mcp", [(ident.HEADER, sig(ALICE, OTHER))], "POST")
    check("guard: a call signed with another secret is refused 403 with the other sentence", len(seen) == n1 and sent[0]["status"] == 403 and sent[1]["body"].decode() == door.BAD_IDENTITY)
    for m in ("GET", "DELETE", "OPTIONS", "HEAD"):
        sc, sent = call(G, "/mcp", [], m)
        check(f"guard: a {m} to the MCP path with no identity is refused, too", sent[0]["status"] == 403 and len(seen) == n1, (m, sent))
    sc, sent = call(G, "/mcp/", [], "POST")
    check("guard: the path with a trailing slash is guarded", sent[0]["status"] == 403 and len(seen) == n1)
    sc, sent = call(G, "/healthz", [], "GET")
    check("guard: another path is not guarded (the health route, the pages, the client API are as they were)", sent[0]["status"] == 204 and len(seen) == n1 + 1 and door.caller_of(sc) == "")
    sc, sent = call(G, "/mcpx", [], "GET"); sc2, sent2 = call(G, "/x/mcp", [], "GET")
    check("guard: a path that only looks like it is not guarded", sent[0]["status"] == 204 and sent2[0]["status"] == 204)
    n2 = len(seen); sc, sent = call(G, "", [], "GET", typ="lifespan")
    check("guard: a lifespan scope passes", len(seen) == n2 + 1 and not sent)
    sc, sent = call(G, "/mcp", [(door.SCOPE_KEY, ALICE), ("x-stackshot-door-identity", ALICE), (ident.HEADER, "v1.forged")], "POST")
    check("guard: a client cannot write the verified identity by a header of the scope key's name or any other", sent[0]["status"] == 403 and door.caller_of(sc) == "")
    check("guard: the wrapper hands the app's own attributes on", guard.DoorGuard(type("A", (), {"state": 7})(), "/mcp").state == 7)
    check("door.caller_of reads only a text identity off a scope", door.caller_of({door.SCOPE_KEY: 5}) == "" and door.caller_of({}) == "" and door.caller_of(None) == "")

    # ---- 5. the real board over HTTP
    app = server.mcp.http_app()
    check("the board's HTTP app is wrapped by the guard (an identity_secret_file is set)", any(isinstance(a, guard.DoorGuard) for a in _chain(app)))
    srv, th, sock, port = serve(app)
    URL = f"http://127.0.0.1:{port}/mcp"; BASE = f"http://127.0.0.1:{port}"
    try:
        def tools_and_item(headers):
            async def run():
                async with Client(StreamableHttpTransport(URL, headers=headers)) as c:
                    names = sorted(t.name for t in await c.list_tools())
                    got = await c.call_tool("get", {"item_id": "a1"})
                    return names, got.content[0].text
            return asyncio.run(run())
        def raises(fn, *a):
            try: fn(*a); return None
            except BaseException as e: return e
        st, body = post(URL)
        check("board: an unsigned call is refused 403 with the sentence", (st, body) == (403, door.NO_IDENTITY), (st, body))
        st, body = post(URL, method="GET")
        check("board: an unsigned GET of the endpoint is refused, too", st == 403 and body == door.NO_IDENTITY, (st, body))
        st, body = post(URL, {ident.HEADER: sig(ALICE, OTHER)})
        check("board: a call signed with another secret is refused 403, and the sentence tells neither secret", st == 403 and body == door.BAD_IDENTITY and SECRET not in body and OTHER not in body, (st, body))
        v = sig(ALICE); p = v.split(".")
        st, body = post(URL, {ident.HEADER: ".".join([p[0], ident._b64(BOB.encode()), p[2], p[3]])})
        check("board: an altered identity is refused 403", (st, body) == (403, door.BAD_IDENTITY), (st, body))
        st, body = post(URL, {ident.HEADER: v[:-1]})
        check("board: a signature cut short by one character is refused 403", (st, body) == (403, door.BAD_IDENTITY), (st, body))
        st, body = post(URL, {ident.HEADER: empty_id_now()})
        check("board: an empty identity under a valid signature is refused 403", (st, body) == (403, door.BAD_IDENTITY), (st, body))
        st, body = post(URL, {ident.HEADER: sig(ALICE, now=time.time() - 400)})
        check("board: an identity signed 400 s ago is refused 403 (replay window 120 s)", (st, body) == (403, door.BAD_IDENTITY), (st, body))
        st, body = post(URL, {ident.HEADER: sig(ALICE, now=time.time() + 300)})
        check("board: an identity dated 300 s ahead is refused 403", (st, body) == (403, door.BAD_IDENTITY), (st, body))
        st, body = post(URL, {ident.HEADER: sig(ALICE, now=time.time() - 100)})
        check("board: an identity signed 100 s ago is inside the window and is let through to the MCP endpoint", st == 200 and "serverInfo" in body, (st, body[:200]))
        st, body = post(BASE + "/healthz", method="GET")
        check("board: the health route is open and unchanged", st == 200, (st, body[:80]))
        e = raises(tools_and_item, {})
        check("board: a client with no identity cannot connect", e is not None, e)
        e = raises(tools_and_item, {ident.HEADER: sig(ALICE, OTHER)})
        check("board: a client signed with another secret cannot connect", e is not None, e)
        names, text = tools_and_item({ident.HEADER: sig(ALICE)})
        check("board: a signed call by a member lists the tools and reads an item", {"get", "brief", "create", "update"} <= set(names) and "door fixture item" in text, (names, text[:200]))
        e = raises(tools_and_item, {ident.HEADER: sig(BOB)})
        check("board: a signed call by someone this board does not list is refused by the tool with the board's own sentence", isinstance(e, ToolError) and f"Refused: {BOB} is not allowed on this board" in str(e), repr(e))
        e = raises(tools_and_item, {ident.HEADER: sig(DAVE)})
        check("board: ... and so is one the front door's file does not list at all", isinstance(e, ToolError) and f"Refused: {DAVE} is not allowed on this board" in str(e), repr(e))

        async def session_calls(who_headers, edits):
            """One open session; between its calls `edits` change the members file; → the outcome of each call."""
            out = []
            async with Client(StreamableHttpTransport(URL, headers=who_headers)) as c:
                for edit in edits:
                    if edit: edit()
                    try: out.append((await c.call_tool("get", {"item_id": "a1"})).content[0].text[:20])
                    except ToolError as e: out.append("refused:" + str(e)[:60])
            return out
        def write(d): return lambda: mfile.write_text(json.dumps(d))
        res = asyncio.run(session_calls({ident.HEADER: sig(BOB)}, [None, write({"alice@example.test": ["main"], "bob@example.test": ["main"]}), write({"alice@example.test": ["main"]})]))
        check("board: on an open session a member added to the file is let in at the next call and one removed is let out", res[0].startswith("refused:") and not res[1].startswith("refused:") and res[2].startswith("refused:"), res)
        mfile.write_text("{broken")
        res = asyncio.run(session_calls({ident.HEADER: sig(ALICE)}, [None]))
        check("board: with the members file unreadable nobody is let in, a valid signature included", res[0].startswith("refused:"), res)
        mfile.write_text(json.dumps({"alice@example.test": ["main", "side"], "bob@example.test": ["side"], "carol@example.test": ["main"]}))
        res = asyncio.run(session_calls({ident.HEADER: sig(ALICE)}, [None]))
        check("board: and with the file back the member is let in again", not res[0].startswith("refused:"), res)

        # the identity a tool sees is the verified one, and a request that did not pass the guard has none
        e = raises(oauth._who)
        check("_who: outside any request there is no identity, and the board behind a door refuses it", isinstance(e, ToolError) and door.NO_IDENTITY in str(e), repr(e))

        # a request the guard did not pass has no verified identity, and a header that looks like a good signed one does not stand in for it
        import fastmcp.server.dependencies as fdeps
        class _Req:
            def __init__(self, scope, headers): self.scope, self.headers = scope, headers
        real_get = fdeps.get_http_request
        try:
            fdeps.get_http_request = lambda: _Req({}, {ident.HEADER: sig(ALICE), door.SCOPE_KEY: ALICE})
            e = raises(oauth._who)
            check("_who: a request with a good-looking signed header and no identity on its scope (the guard did not verify it) is refused, the header is never read", isinstance(e, ToolError) and door.NO_IDENTITY in str(e), repr(e))
            fdeps.get_http_request = lambda: _Req({door.SCOPE_KEY: ALICE}, {})
            check("_who: the identity the guard put on the scope is the caller, with no header at all", oauth._who() == ALICE)
            fdeps.get_http_request = lambda: _Req({door.SCOPE_KEY: DAVE}, {})
            e = raises(oauth._who)
            check("_who: a verified identity the board's members do not list is refused", isinstance(e, ToolError) and f"Refused: {DAVE} is not allowed on this board" in str(e), repr(e))
        finally:
            fdeps.get_http_request = real_get

        # ---- 6. the front door's own transport against the real board
        from stackshot.core import frontdoor_config as fc
        from stackshot.frontdoor import backend as fdback
        bearer = secret("board.token", "BOARDTOKEN-0123456789abcdef")
        def door_settings(secret_path):
            cfg = {"frontdoor": {"identity_header": "x-forwarded-user", "identity_secret_file": secret_path, "members_file": paths["members"],
                                 "backends": [{"name": "main", "kind": "board", "url": URL, "health_url": BASE + "/healthz", "token_file": bearer}]}}
            s_, problems = fc.parse(cfg); assert not problems, problems
            return s_
        async def through_door(settings_, caller):
            async with fdback.Backends(settings_).client("main", caller) as c:
                tools = sorted(t.name for t in await c.list_tools())
                got = await c.call_tool("get", {"item_id": "a1"})
                return tools, got.content[0].text
        tools_d, text_d = asyncio.run(through_door(door_settings(paths["secret"]), ALICE))
        check("front door: what the front door's transport sends (its signed identity, its bearer) is accepted by the board and the call is the member's", "get" in tools_d and "door fixture item" in text_d, (tools_d, text_d[:120]))
        e = raises(lambda: asyncio.run(through_door(door_settings(secret("wrong.key", OTHER)), ALICE)))
        check("front door: a front door that signs with another secret is refused by the board", e is not None, e)
        e = raises(lambda: asyncio.run(through_door(door_settings(paths["secret"]), BOB)))
        check("front door: a caller the front door signs for but the board does not list is refused by the board's tool", isinstance(e, ToolError) and "is not allowed on this board" in str(e), repr(e))
    finally:
        stop(srv, th, sock)

    # ---- 7. the shared code and the old names
    from stackshot.frontdoor import config as fdconf, identity as fdident
    check("old names: frontdoor/identity.py and frontdoor/config.py are the shared code", fdident.verify is ident.verify and fdident.sign is ident.sign and fdident.HEADER == ident.HEADER
          and fdconf.read_secret is ffiles.read_secret and fdconf.read_members is ffiles.read_members and fdconf.FileError is ffiles.FileError)
    return F.ran, F.fails


def _chain(app):
    """The wrappers of an ASGI app: each `.app` inward."""
    out = []
    while app is not None and len(out) < 10:
        out.append(app); app = app.__dict__.get("app") if hasattr(app, "__dict__") else None
    return out


# ================================================================ part off: a board with no [behind_frontdoor] table
def part_off():
    import asyncio, time
    T, secret, paths = setup("off")
    F = Fixture(); check = F.check
    import logging; logging.disable(logging.INFO)
    from stackshot.core import behind_door as door, config as cfgmod, frontdoor_identity as ident, members as mem
    from stackshot.web import door_guard as guard, server
    from stackshot.web.auth import oauth
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    check("off: the settings are all off", door.settings() == door.Settings() and door.members() is None)
    check("off: the config notes say nothing about a front door", not [n for n in cfgmod.notes() if "front door" in n or "behind_frontdoor" in n], [n for n in cfgmod.notes() if "front door" in n])
    app = server.mcp.http_app()
    check("off: the board's HTTP app is not wrapped by the guard", not any(isinstance(a, guard.DoorGuard) for a in _chain(app)), [type(a).__name__ for a in _chain(app)])
    own = mem.build({"instance": {"owner": "Pat Example"}, "auth": {"allowed_emails": ["pat@example.test"]}, "behind_frontdoor_unused": {}})
    check("off: the members are the board's own, as before: the example config's placeholder, and the owner keys still make the one person", mem.first().placeholder and [(p.name, p.emails) for p in own] == [("Pat Example", ("pat@example.test",))], (mem.members(), own))
    try: who_off = oauth._who()
    except BaseException as e: who_off = repr(e)
    check("off: _who asks nothing of a request (auth is off in this test): no identity, no refusal", who_off == "", who_off)
    check("off: a board with sign-in on and an address to name starts", auth_start(oauth) == "started", auth_start(oauth))
    kept_mail = cfgmod.CFG["auth"]["allowed_emails"]; cfgmod.CFG["auth"]["allowed_emails"] = []
    try: nobody, stop_at = mem.emails(), auth_start(oauth)
    finally: cfgmod.CFG["auth"]["allowed_emails"] = kept_mail
    check("off: a board with no table and no address to name still stops at its sign-in start with the IndexError it always did (that line is as it was for a board with no [behind_frontdoor])", nobody == [] and stop_at == "IndexError", (nobody, stop_at))
    srv, th, sock, port = serve(app)
    URL = f"http://127.0.0.1:{port}/mcp"
    try:
        st, body = post(URL)
        check("off: an unsigned call to /mcp is served as before", st == 200 and "serverInfo" in body, (st, body[:150]))
        st, body = post(URL, {ident.HEADER: "v1.not-a-signature"})
        check("off: a header of the signed identity's name is ignored, never refused", st == 200 and "serverInfo" in body, (st, body[:150]))
        async def run():
            async with Client(StreamableHttpTransport(URL)) as c:
                return (await c.call_tool("get", {"item_id": "a1"})).content[0].text
        check("off: a tool call with no identity reads an item, as before", "door fixture item" in asyncio.run(run()))
    finally:
        stop(srv, th, sock)
    return F.ran, F.fails


MARK = "@@frontdoor_board part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"on": part_on, "off": part_off}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        os._exit(0)      # nothing a thread of the part left behind holds the process (tests/_scratch.py removes the scratch folder first)
    total = bad = 0
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], stdout=subprocess.PIPE, text=True)
        seen = [l for l in r.stdout.splitlines() if l.startswith(MARK + " ")]
        print("\n".join(l for l in r.stdout.splitlines() if not l.startswith(MARK + " ")))
        if r.returncode != 0 or len(seen) != 1:
            print(f"FAIL part {name} did not end cleanly (exit {r.returncode})"); bad += 1; continue
        _, _, _, n, f = seen[0].split(); total += int(n); bad += int(f)
        print(f"part {name}: {int(n) - int(f)}/{n} checks passed")
    if bad:
        print(f"\n{bad} failures in {total} checks"); sys.exit(1)
    print(f"ok: front door board scenario, {total} checks")
