"""Scenario test for inviting a person to a board behind a front door (core/invites.py, web/tools/invite.py, web/routes/join.py, and what the sign-in paths ask of a
registration; docs/front-door.md, *Inviting a person*). Offline and hermetic: fixture files in a scratch folder, example.com addresses, no Google, no network but
loopback ports.

The chain under test is the one a deploy runs, in this process: a real board (Google sign-in with a made-up client; only the check of a Google token is a table), the real
sign-in service asking it, and the real front door in front of it, which this test calls with the header the proxy would copy from the sign-in service's answer.

Covers:
  * the settings: off with no [invites] table or no admin, off naming what is missing otherwise, the setup link and the connector address, the note about the machine token;
  * the tool: admins only (a member who is no admin, a stranger, a machine token on a direct connection are refused); register writes one members entry and keeps the rest
    of the file, its mode and a link to it; the reply carries the link and the mail and asks for a draft; again changes nothing; an entry written by hand is never changed;
    a file that would lose part of itself, grow too large or cannot be read is not written; remove, and what its reply says; two changes at once both land;
  * the sign-in: an invited address that Google does not report as verified, or a second Google account, is refused by the token check, the sign-in service passes it on,
    and the front door says why with the address; the first verified sign-in records the account; removal refuses the next request with the token already used; the same
    on a direct connection and on the board's own web sign-in (its session too); a member written by hand signs in as before;
  * the setup page: open without sign-in, the same for everyone, no member and no address on it, escaped, bounded;
  * the redirect URIs: the apps' own are taken, look-alikes are not;
  * a board with no [invites]: no tool, no page, no extra redirect URI, nothing added to the instructions.

What each of these callers then reads and writes, tool by tool, is tests/invites_access_scenario.py.

    tests/run-suite invites         -> exit 0 / 1"""
import asyncio, base64, contextlib, hashlib, json, logging, os, pathlib, re, socket, stat, subprocess, sys, threading, time, tomllib
from dataclasses import replace
from urllib.parse import quote

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch, _instance

tmp = _scratch.mkdtemp(prefix="invitestest-"); T = pathlib.Path(tmp)
PORTAL = "portal-token-for-this-test-" + "0" * 16
for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL", "STACKSHOT_AUTH", "BOARD_MCP_AUTH"): os.environ.pop(k, None)
os.environ.update(STACKSHOT_GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com", STACKSHOT_GOOGLE_CLIENT_SECRET="test-secret", STACKSHOT_PORTAL_TOKEN=PORTAL)


def private(name, value):
    p = T / name
    p.write_text(value + "\n", encoding="utf-8"); p.chmod(0o600)
    return str(p)


IDENTITY = private("identity.key", "identity-secret-for-this-test-01")
VERIFY = private("verify.key", "verify-secret-for-this-test-0002")
BEARER = private("bearer.token", PORTAL)
(T / "real").mkdir()
REAL_MEMBERS = T / "real/members.json"
MEMBERS = T / "members.json"                       # a link: a change has to keep it one
MEMBERS.symlink_to(REAL_MEMBERS)
BASE_MEMBERS = {"alice": {"boards": ["main"], "emails": ["alice@example.com"], "aliases": ["Al"]},
                "bob": {"boards": ["main"], "emails": ["bob@example.com"]},
                "carol@example.com": ["side"]}


def reset_members(extra=None):
    REAL_MEMBERS.write_text(json.dumps({**BASE_MEMBERS, **(extra or {})}), encoding="utf-8")
    REAL_MEMBERS.chmod(0o640)


def members():
    return json.loads(REAL_MEMBERS.read_text(encoding="utf-8"))


reset_members()
BASE_URL = "https://stackshot.test"
BEHIND = (f'\n[behind_frontdoor]\nidentity_secret_file = "{IDENTITY}"\nverify_secret_file = "{VERIFY}"\nmembers_file = "{MEMBERS}"\nboard_name = "main"\n')


def write_config(name, tail):
    toml = _instance.apply(_instance.base_toml())
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("session_links", f"{tmp}/sala"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai"), ("base_url", BASE_URL)):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
    toml, n = re.subn(r"(?m)^ui_open = (true|false)", "ui_open = false", toml); assert n == 1
    toml, n = re.subn(r'(?m)^mode = "google"', 'mode = "google"', toml); assert n == 1
    (T / name).write_text(toml + tail, encoding="utf-8")
    return str(T / name)


ON = write_config("stackshot.toml", BEHIND + '\n[invites]\nadmins = ["alice"]\n')
OFF = write_config("off.toml", BEHIND)
os.environ["STACKSHOT_CONFIG"] = ON
for d in ("store/a", "state/site", "secrets", "brain/projects"): (T / d).mkdir(parents=True)
(T / "names.tsv").write_text("# hostname\tfleet\tletter\n")
(T / "store/projects.json").write_text(json.dumps({"pages": {}}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
logging.disable(logging.WARNING)

fails, ran = [], []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""), flush=True)


def raised(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except Exception as e:      # noqa: BLE001
        return e
    return None


import httpx, uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
import fastmcp.server.dependencies as deps
from fastmcp.server.auth import AccessToken
from starlette.requests import Request
from starlette.testclient import TestClient

from stackshot.web import server
from stackshot.core import config as _cfg, frontdoor_config as fc, frontdoor_identity as ident, frontdoor_signin_config as sc, invites, members as _members, readonly as _ro
from stackshot.frontdoor import app as door_app, provider as fdprov, signin
from stackshot.service.caller_pass import RateLimit
from stackshot.web import publish as _web_publish, middleware as _middleware
from stackshot.web.auth import oauth as _oauth, signin as _signin
from stackshot.web.routes import join as _join
from stackshot.web.tools import invite as _tool, anchors as _wt_anchors, route as _wt_route
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None

LINK = BASE_URL + "/join"
S = invites.settings()


# ================================================================ 1. the settings
def part_settings():
    cfgd = tomllib.loads
    check("settings: the running config is on, with the link and the connector address", S.on and S.admins == ("alice",) and S.link == LINK and S.mcp_url == BASE_URL + "/mcp"
          and S.board == "main" and S.members_file == str(MEMBERS) and invites.notes() == [], (S, invites.notes()))
    check("settings: no table is off, unwanted and says nothing", invites.parse(cfgd('[auth]\nmode = "google"\n')) == (invites.Settings(), []) and not invites.wanted(cfgd("")))
    full = {"auth": {"mode": "google", "base_url": "https://b.example.com/"}, "behind_frontdoor": {"members_file": "/m", "board_name": "main", "verify_secret_file": "/v"},
            "invites": {"admins": [" alice ", "alice", "", 3, "dan"]}}
    s, n = invites.parse(full)
    check("settings: everything there is on, admins trimmed and once each", s.on and s.admins == ("alice", "dan") and s.link == "https://b.example.com/join" and s.mcp_url == "https://b.example.com/mcp" and n == [], (s, n))
    s, n = invites.parse({**full, "invites": {"admins": ["alice"], "mcp_url": "https://door.example.com/mcp"}})
    check("settings: mcp_url is the connector address, the link stays the board's", s.mcp_url == "https://door.example.com/mcp" and s.link == "https://b.example.com/join", s)
    for label, change, word in (
            ("no admins", {"invites": {}}, "admins"),
            ("admins that are no list", {"invites": {"admins": "alice"}}, "admins"),
            ("sign-in off", {"auth": {"mode": "off", "base_url": "https://b.example.com"}}, 'mode = "google"'),
            ("a base_url that is not https", {"auth": {"mode": "google", "base_url": "http://b.example.com"}}, "base_url"),
            ("no members_file", {"behind_frontdoor": {"board_name": "main", "verify_secret_file": "/v"}}, "members_file"),
            ("no board_name", {"behind_frontdoor": {"members_file": "/m", "verify_secret_file": "/v"}}, "board_name"),
            ("no token check", {"behind_frontdoor": {"members_file": "/m", "board_name": "main"}}, "verify_secret_file"),
            ("an mcp_url that is no https address", {"invites": {"admins": ["alice"], "mcp_url": 'https://x.example.com/"; rm'}}, "mcp_url"),
            ("a table that is no table", {"invites": 3}, "not a table")):
        s, n = invites.parse({**full, **change})
        check(f"settings: {label} is off and the note says so", s == invites.Settings() and len(n) == 1 and word in n[0], (s, n))
    os.environ["STACKSHOT_AUTH"] = "off"
    try:
        check("settings: STACKSHOT_AUTH=off wins over the config's google: off", not invites.parse(full)[0].on)
    finally:
        del os.environ["STACKSHOT_AUTH"]
    s, n = invites.parse({**full, "frontdoor_signin": {"accept_portal_token": True}})
    check("settings: with accept_portal_token on, a note says the machine token then invites as its member", s.on and len(n) == 1 and "machine token" in n[0], (s, n))
    check("settings: the config notes carry them, and [invites] needs a restart", any("[invites] is off" in x for x in _cfg.notes({**full, "invites": {}})) and "invites" in _cfg.RESTART_ONLY)
    good = {"New@Example.com": "new@example.com", " a.b+c@sub.example.org ": "a.b+c@sub.example.org", "o'neil@example.com": "o'neil@example.com"}
    check("address: a plain address is kept in lower case", all(invites.address_of(k) == v for k, v in good.items()), [invites.address_of(k) for k in good])
    bad = ["", None, "name", "a@b", "a b@example.com", "a@example.com, b@example.com", "<a@example.com>", "a@example.com\nb", '"a"@example.com', "a@exa_mple.com", "a@@example.com",
           "x" * 65 + "@example.com", chr(0x212A) + "@example.com", "a@example." + "c" * 300]
    check("address: anything else is no address", all(invites.address_of(b) == "" for b in bad), [b for b in bad if invites.address_of(b)])


# ================================================================ 2. the members file
def part_file():
    reset_members()
    changed, joined = invites.register("new@example.com", "alice", S)
    got = members()
    check("register: one entry, on this board, marked with who and when, no account yet", changed and not joined and got["new@example.com"]["boards"] == ["main"] and got["new@example.com"]["emails"] == ["new@example.com"]
          and got["new@example.com"]["invited"]["by"] == "alice" and got["new@example.com"]["invited"]["google_sub"] == "" and re.match(r"\d{4}-\d\d-\d\dT", got["new@example.com"]["invited"]["at"]), got.get("new@example.com"))
    check("register: the other entries are as they were", {k: got[k] for k in BASE_MEMBERS} == BASE_MEMBERS, got)
    check("register: the file keeps its mode, and the link to it stays a link", stat.S_IMODE(os.stat(REAL_MEMBERS).st_mode) == 0o640 and MEMBERS.is_symlink(), oct(os.stat(REAL_MEMBERS).st_mode))
    check("register: no part file is left", not [p for p in (T / "real").iterdir() if p.name.startswith(".members-")], list((T / "real").iterdir()))
    before = os.stat(REAL_MEMBERS).st_ino
    check("register again: nothing changes, nothing is written", invites.register("new@example.com", "alice", S) == (False, False) and os.stat(REAL_MEMBERS).st_ino == before)
    for label, address in (("a key written by hand", "carol@example.com"), ("an address of a hand entry", "alice@example.com")):
        e = raised(invites.register, address, "alice", S)
        check(f"register: {label} is refused and the file is untouched", isinstance(e, invites.InviteError) and "not registered this way" in str(e) and os.stat(REAL_MEMBERS).st_ino == before, e)
    reset_members({"dan": {"boards": ["side"], "emails": ["dan@example.com"], "aliases": ["dee@example.com"]}})
    check("register: an alias of a hand entry is refused too", isinstance(raised(invites.register, "dee@example.com", "alice", S), invites.InviteError))
    other = replace(S, board="side")
    reset_members()
    invites.register("new@example.com", "alice", S)
    check("register: an invited entry of another board gets this one added", invites.register("new@example.com", "alice", other) == (True, False) and members()["new@example.com"]["boards"] == ["main", "side"], members())
    left, listed = invites.remove("new@example.com", S)
    check("remove: this board is taken from the entry, which stays for the other", left == ("side",) and not listed and members()["new@example.com"]["boards"] == ["side"], (left, listed, members()))
    check("remove: not registered on this board is said", "not registered on board main" in str(raised(invites.remove, "new@example.com", S)))
    left, listed = invites.remove("new@example.com", other)
    check("remove: the last board deletes the entry", left == () and "new@example.com" not in members(), members())
    check("remove: an address that is nowhere is not registered", "is not registered" in str(raised(invites.remove, "new@example.com", S)))
    check("remove: a hand entry is not removed", "by hand" in str(raised(invites.remove, "bob@example.com", S)) and "bob" in members())
    inv = {"boards": ["main"], "emails": ["x@example.com"], "invited": {"by": "alice", "at": "", "google_sub": ""}}
    reset_members({"x@example.com": inv, "xx": {"boards": ["main"], "emails": ["x@example.com"]}})
    check("remove: an address a hand entry lists too says so", invites.remove("x@example.com", S) == ((), True) and "xx" in members() and "x@example.com" not in members(), members())
    reset_members({"alice2": {**inv}})
    check("remove: an admin's own entry is not removed", "admin" in str(raised(invites.remove, "x@example.com", replace(S, admins=("alice2",)))) and "alice2" in members())

    # a person removed and invited again: the new registration is the new person's own
    reset_members()
    invites.register("new@example.com", "alice", S); invites.register("new@example.com", "alice", other)
    invites.admit("new@example.com", "111", True)
    invites.remove("new@example.com", S)
    ino = os.stat(REAL_MEMBERS).st_ino
    e = raised(invites.register, "new@example.com", "alice", S)
    check("re-invite: a board taken off an entry that keeps the earlier account is refused with the way out", isinstance(e, invites.InviteError) and "remove new@example.com from every board first" in str(e)
          and members()["new@example.com"]["boards"] == ["side"] and os.stat(REAL_MEMBERS).st_ino == ino, (e, members()))
    check("re-invite: the earlier account is not given the board again, and keeps the other", invites.admit("new@example.com", "111", True) == "" and members()["new@example.com"]["boards"] == ["side"])
    invites.remove("new@example.com", other)
    check("re-invite: removed from every board, the entry is gone and a new registration has no account", invites.register("new@example.com", "alice", S) == (True, False)
          and members()["new@example.com"]["invited"]["google_sub"] == "", members())
    check("re-invite: the new person's sign-in is the one recorded, and the earlier account is then refused", invites.admit("new@example.com", "222", True) == ""
          and members()["new@example.com"]["invited"]["google_sub"] == "222" and invites.admit("new@example.com", "111", True) == "other_account")
    # the last board: the entry is gone from every board, and the earlier account's connector is still signed in
    reset_members()
    invites.register("new@example.com", "alice", S); invites.admit("new@example.com", "111", True)
    invites.remove("new@example.com", S)
    check("re-invite: the last board taken off keeps no board and no recorded account, only the earlier account's id to refuse",
          members().get("new@example.com", {}).get("boards") == [] and members()["new@example.com"]["invited"].get("google_sub") == "" and members()["new@example.com"]["invited"].get("former_subs") == ["111"], members())
    check("re-invite: before a new registration the earlier account records nothing", invites.admit("new@example.com", "111", True) == "" and not members().get("new@example.com", {}).get("invited", {}).get("google_sub"))
    check("re-invite: the address is registered again with no account", invites.register("new@example.com", "alice", S) == (True, False) and members()["new@example.com"]["boards"] == ["main"])
    check("re-invite: the earlier account's still-connected app cannot record itself first", invites.admit("new@example.com", "111", True) == "other_account"
          and not members()["new@example.com"]["invited"]["google_sub"] and not invites.session_holds("new@example.com", "111"), members())
    check("re-invite: the new person's sign-in is then the one recorded", invites.admit("new@example.com", "222", True) == "" and members()["new@example.com"]["invited"]["google_sub"] == "222"
          and invites.admit("new@example.com", "111", True) == "other_account")
    reset_members()
    invites.register("new@example.com", "alice", S); invites.register("new@example.com", "alice", other)
    invites.remove("new@example.com", S)
    check("re-invite: an entry whose account was never recorded takes the board again", invites.register("new@example.com", "alice", S) == (True, False)
          and members()["new@example.com"]["boards"] == ["side", "main"], members())
    reset_members()
    invites.register("new@example.com", "alice", S); invites.admit("new@example.com", "111", True)
    check("re-invite: a person who joined on one board is added to another as before", invites.register("new@example.com", "alice", other) == (True, True))

    for label, text, word in (("a name written twice", '{"a@example.com": ["main"], "a@example.com": ["side"]}', "twice"),
                              ("a name written twice inside an entry", '{"a": {"boards": ["main"], "boards": ["side"]}}', "twice"),
                              ("a file that is not JSON", '{"a": ', "not valid JSON"),
                              ("a file that is a list", "[1]", "not a JSON object")):
        REAL_MEMBERS.write_text(text)
        e = raised(invites.register, "new@example.com", "alice", S)
        check(f"file: {label} is refused and not written", isinstance(e, invites.InviteError) and word in str(e) and REAL_MEMBERS.read_text() == text, (e, REAL_MEMBERS.read_text()[:80]))
    big = json.dumps({f"m{i}": {"boards": ["main"], "aliases": ["a" * 200]} for i in range(265)}, separators=(",", ":"))
    assert 60000 < len(big) < 65536, len(big)
    REAL_MEMBERS.write_text(big)
    e = raised(invites.register, "new@example.com", "alice", S)
    check("file: a change that would make it larger than any reader takes is refused", isinstance(e, invites.InviteError) and "would grow past" in str(e) and REAL_MEMBERS.read_text() == big, e)
    REAL_MEMBERS.unlink()
    check("file: a missing one is refused, not made", isinstance(raised(invites.register, "new@example.com", "alice", S), invites.InviteError) and not REAL_MEMBERS.exists())
    reset_members()
    real_ro = _ro.is_read_only
    _ro.is_read_only = lambda: True
    try:
        check("file: the read-only standby changes nothing", isinstance(raised(invites.register, "new@example.com", "alice", S), invites.InviteError) and "new@example.com" not in members())
    finally:
        _ro.is_read_only = real_ro
    check("standby: the invite tool is one the standby refuses", "invite" in _middleware._RO_WRITE_TOOLS)

    # two changes at once both land
    done = []
    def reg(i):
        done.append(raised(invites.register, f"p{i}@example.com", "alice", S))
    ts = [threading.Thread(target=reg, args=(i,)) for i in range(12)]
    for t in ts: t.start()
    for t in ts: t.join()
    check("file: twelve changes at once all land", done == [None] * 12 and sum(k.startswith("p") for k in members()) == 12, (done, sorted(members())))
    import fcntl
    fd = os.open(str(REAL_MEMBERS) + ".lock", os.O_RDWR)
    wait, invites.LOCK_SECONDS = invites.LOCK_SECONDS, 0.2
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        e = raised(invites.register, "late@example.com", "alice", S)
        check("file: a change waits for the lock only so long", isinstance(e, invites.InviteError) and "someone else" in str(e) and "late@example.com" not in members(), e)
    finally:
        invites.LOCK_SECONDS = wait; os.close(fd)


# ================================================================ 3. what a registration asks of a sign-in
def part_admit():
    reset_members()
    invites.register("new@example.com", "alice", S)
    pin = lambda: members()["new@example.com"]["invited"]["google_sub"]
    for label, verified in (("false", False), ("the text false", "false"), ("missing", None), ("1", 1), ("yes", "yes")):
        check(f"admit: verified {label} is refused and records nothing", invites.admit("new@example.com", "111", verified) == "unverified" and pin() == "", pin())
    check("admit: no account id is refused and records nothing", invites.admit("new@example.com", "", True) == "unreadable" and invites.admit("new@example.com", 111, True) == "unreadable" and pin() == "")
    real_ro = _ro.is_read_only
    _ro.is_read_only = lambda: True
    try:
        check("admit: a first sign-in that cannot be recorded is not let in", invites.admit("new@example.com", "111", True) == "unrecorded" and pin() == "")
    finally:
        _ro.is_read_only = real_ro
    check("admit: the first verified sign-in records the account, Google's text true included", invites.admit(" New@Example.com ", "111", "true") == "" and pin() == "111", pin())
    ino = os.stat(REAL_MEMBERS).st_ino
    check("admit: the same account is let in, with nothing written", invites.admit("new@example.com", "111", True) == "" and os.stat(REAL_MEMBERS).st_ino == ino)
    check("admit: another account of the same address is refused", invites.admit("new@example.com", "222", True) == "other_account" and pin() == "111")
    check("admit: once recorded, an unverified sign-in is still refused", invites.admit("new@example.com", "111", False) == "unverified")
    check("admit: a member written by hand is asked nothing", invites.admit("bob@example.com", "", False) == "" and invites.admit("nobody@example.com", "", None) == "")
    got = members(); got["new@example.com"]["invited"] = "yes"; REAL_MEMBERS.write_text(json.dumps(got))
    check("admit: an `invited` that cannot be read refuses", invites.admit("new@example.com", "111", True) == "unreadable")
    got["new@example.com"]["invited"] = {"google_sub": 5}; REAL_MEMBERS.write_text(json.dumps(got))
    check("admit: ... and so does a recorded account that is no text", invites.admit("new@example.com", "111", True) == "unreadable")
    two = {"boards": ["main"], "emails": ["new@example.com"], "invited": {"google_sub": "111"}}
    reset_members({"new@example.com": two, "again": {**two, "invited": {"google_sub": "222"}}})
    check("admit: of two registrations of one address, each recorded account has to be the one", invites.admit("new@example.com", "111", True) == "other_account")
    REAL_MEMBERS.write_text("{")
    check("admit: a members file that cannot be read refuses", invites.admit("bob@example.com", "1", True) == "unreadable" and not invites.session_holds("bob@example.com", ""))
    saved = _cfg.CFG["behind_frontdoor"]
    _cfg.CFG["behind_frontdoor"] = {"identity_secret_file": IDENTITY}
    try:
        check("admit: a board that reads no members file asks nothing", invites.admit("new@example.com", "", False) == "" and invites.session_holds("new@example.com", "") and invites.session_account("new@example.com", "111") == "")
    finally:
        _cfg.CFG["behind_frontdoor"] = saved
    reset_members({"new@example.com": two})
    check("session: an invited address keeps its account, others none", invites.session_account("new@example.com", "111") == "111" and invites.session_account("bob@example.com", "9") == "")
    check("session: it holds for that account only, and a hand entry's holds with none", invites.session_holds("new@example.com", "111") and not invites.session_holds("new@example.com", "")
          and not invites.session_holds("new@example.com", "222") and invites.session_holds("bob@example.com", ""))
    reset_members()
    invites.register("new@example.com", "alice", S)
    check("session: with no account id it does not hold on an invitation nobody has joined", not invites.session_holds("new@example.com", ""))

    # something else writes the record between the first read and the lock: what is read under the lock decides
    for label, written, why in (("another account", "222", "other_account"), ("an unreadable record", 5, "unreadable")):
        reset_members()
        invites.register("new@example.com", "alice", S)
        locked = invites._locked

        @contextlib.contextmanager
        def raced(real, written=written, locked=locked):
            got = members(); got["new@example.com"]["invited"]["google_sub"] = written; REAL_MEMBERS.write_text(json.dumps(got))
            with locked(real):
                yield
        invites._locked = raced
        try:
            said = invites.admit("new@example.com", "111", True)
        finally:
            invites._locked = locked
        check(f"admit: {label} recorded between the read and the lock is refused, and stands", said == why and pin() == written, (said, pin()))


# ================================================================ 4. the chain: board, sign-in service, front door
GOOGLE = {}                                                                   # token -> the claims Google's check would give
_real_verify = server.mcp.auth.verify_token


async def _verify(token):
    if token in GOOGLE:
        return AccessToken(token=token, client_id="c", scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"], expires_at=None, claims=dict(GOOGLE[token]))
    return await _real_verify(token)


server.mcp.auth.verify_token = _verify


def google(name, email, sub, verified="true"):
    t = f"google-{name}"
    GOOGLE[t] = {"email": email, "sub": sub, "email_verified": verified}
    return t


@contextlib.contextmanager
def serving(app):
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on", timeout_graceful_shutdown=3))
    th = threading.Thread(target=lambda: srv.run(sockets=[sock]), daemon=True); th.start()
    try:
        for _ in range(200):
            if srv.started: break
            time.sleep(0.05)
        assert srv.started, "a server did not start"
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.should_exit = True; th.join(15); sock.close()


def part_chain():
    reset_members()
    with serving(server.mcp.http_app()) as board:
        door_settings, problems = fc.parse({"frontdoor": {"identity_header": "x-verified-user", "identity_secret_file": IDENTITY, "members_file": str(MEMBERS),
                                                          "backends": [{"name": "main", "kind": "board", "url": board + "/mcp", "health_url": board + "/healthz", "token_file": BEARER}]}})
        assert not problems, problems
        front, _door_rt = door_app.build(door_settings)
        base = {"board_verify_url": board + "/frontdoor/verify", "verify_secret_file": VERIFY, "members_file": str(MEMBERS), "timeout_seconds": 20.0, "cache_seconds": 60.0}
        sapp, svc = signin.build(replace(sc.parse({})[0], present=True, port=1, **base))
        with serving(front.http_app()) as door, serving(sapp) as signer:

            def verify(token):
                return httpx.get(signer + "/verify", headers={"authorization": "Bearer " + token}, timeout=30)

            def through(identity, fn, mode="legacy"):
                async def run():
                    async with Client(StreamableHttpTransport(door + "/mcp", headers={"x-verified-user": identity}), mode=mode) as c:
                        return await fn(c)
                try:
                    return asyncio.run(run()), ""
                except Exception as e:      # noqa: BLE001
                    return None, str(e)

            def invite(identity, address, **kw):
                async def call(c):
                    return (await c.call_tool("invite", {"address": address, **kw})).content[0].text
                return through(identity, call)

            async def listing(c):
                return sorted(t.name for t in await c.list_tools())

            alice = google("alice", "alice@example.com", "900")
            r = verify(alice)
            check("chain: a member written by hand signs in as before", r.status_code == 200 and r.headers.get("x-verified-user") == "alice", (r.status_code, dict(r.headers)))
            names, e = through("alice", listing)
            check("tool: the admin's list has invite", names and "invite" in names, (names, e))

            out, e = invite("bob", "new@example.com")
            check("tool: a member who is no admin is refused, and nothing is registered", _tool.NOT_ADMIN in e and "new@example.com" not in members(), (out, e))
            out, e = invite("alice", "two@example.com, three@example.com")
            check("tool: what is no single address is refused", _tool.BAD_ADDRESS in e and set(members()) == set(BASE_MEMBERS), (out, e))
            out, e = invite("alice", "New@Example.com")
            check("tool: the admin registers an address", not e and out.startswith("Registered new@example.com on board main.") and members()["new@example.com"]["invited"]["by"] == "alice", (out, e))
            out = out or ""
            check("tool: the reply holds the setup link and the invite mail with the link and the address", f"setup link: {LINK}" in out and "subject: " in out and f"Open {LINK} and add" in out
                  and "I sign in with Google as new@example.com." in out, out)
            check("tool: ... asks for a draft the admin sends, and says the board sent nothing", "as a draft to new@example.com" in out and "do not send it" in out and "The board sent nothing." in out
                  and "copy" in out and 'invite(address="new@example.com", remove=true)' in out, out)
            check("tool: the reply holds no secret", PORTAL not in out and "secret" not in out.lower(), out)
            out, e = invite("alice", "new@example.com")
            check("tool: again says it is registered and gives the same link", not e and "is already registered on board main (has not signed in yet)" in out and LINK in out, (out, e))
            out, e = invite("alice", "bob@example.com")
            check("tool: a hand entry is refused in words", out is None and "Refused: bob@example.com is already written in the members file" in e, (out, e))

            # unverified: refused in words, with the address
            unv = google("unv", "new@example.com", "111", "false")
            direct = httpx.get(board + "/frontdoor/verify", headers={"authorization": "Bearer " + unv, "x-stackshot-verify": ident.sign(pathlib.Path(VERIFY).read_text().strip().encode(), "token-check")}, timeout=30)
            check("verify: an unverified invited address is 403 not_admitted with the reason and the address", direct.status_code == 403
                  and direct.json() == {"error": "not_admitted", "why": "unverified", "email": "new@example.com"} and direct.headers.get("cache-control") == "no-store", (direct.status_code, direct.text))
            real_barred = _oauth._barred

            def broken(claims):
                raise RuntimeError("the check failed")
            _oauth._barred = broken
            try:
                down = httpx.get(board + "/frontdoor/verify", headers={"authorization": "Bearer " + alice, "x-stackshot-verify": ident.sign(pathlib.Path(VERIFY).read_text().strip().encode(), "token-check")}, timeout=30)
            finally:
                _oauth._barred = real_barred
            check("verify: a registration check that fails is 503, never a 200", down.status_code == 503 and down.json() == {"error": "unavailable"}, (down.status_code, down.text))
            r = verify(unv)
            barred = r.headers.get("x-verified-user", "")
            check("sign-in service: passes it on as an identity that carries the refusal", r.status_code == 200 and ident.barred_of(barred) == ("unverified", "new@example.com"), (r.status_code, barred))
            names, e = through(barred, listing)
            check("front door: says why, with the address", names is None and "new@example.com signed in and is not let in. Google does not report this address as verified." in e, (names, e))
            _n, e = through(barred, listing, mode="auto")
            check("front door: ... to a client of the stateless protocol too", _n is None and "new@example.com signed in and is not let in." in e, (_n, e))
            _o, e = through(barred, lambda c: c.call_tool("brief", {}))
            check("front door: a call is refused the same way", "is not let in" in e, e)
            check("sign-in service: a refusal is not cached", not svc.cache or all("new@example.com" != v[1] for v in svc.cache.values()), dict(svc.cache))
            check("verify: nothing was recorded", members()["new@example.com"]["invited"]["google_sub"] == "")

            # the first join
            first = google("first", "new@example.com", "111")
            r = verify(first)
            who = r.headers.get("x-verified-user", "")
            check("join: the verified sign-in of the registered address is let in", r.status_code == 200 and who == "new@example.com", (r.status_code, who))
            check("join: ... and its Google account is recorded", members()["new@example.com"]["invited"]["google_sub"] == "111", members()["new@example.com"])
            async def first_look(c):
                return c.initialize_result.instructions, await listing(c), (await c.call_tool("brief", {})).content[0].text
            got, e = through(who, first_look)
            check("join: the newcomer reads the board", got and "brief" in got[1] and got[2], (got and got[2][:200], e))
            check("join: the instructions say how to walk a newcomer through the first use", got and "A person who has just joined this board" in got[0] and "call brief" in got[0], got and got[0][-900:])
            check("join: no board or page was made for the newcomer", sorted(p.name for p in (T / "store/a").iterdir()) == [] and not list((T / "brain/projects").iterdir()))
            _o, e = invite(who, "friend@example.com")
            check("tool: the newcomer is no admin", _tool.NOT_ADMIN in e and "friend@example.com" not in members(), e)
            out, e = invite("alice", "new@example.com")
            check("tool: again after the join says so", not e and "(has signed in)" in out, (out, e))

            second = google("second", "new@example.com", "222")
            r = verify(second)
            check("account: another Google account of the address is refused", ident.barred_of(r.headers.get("x-verified-user")) == ("other_account", "new@example.com"), dict(r.headers))
            _n, e = through(r.headers.get("x-verified-user", "x"), listing)
            check("front door: says the address first joined with another account", "first joined with another Google account" in e, e)
            check("account: the recorded one stands", members()["new@example.com"]["invited"]["google_sub"] == "111")

            _n, e = through("stranger@example.com", listing)
            check("front door: an address that is not registered is told which address signed in", "you are not a member of any board. The address that signed in: stranger@example.com." in e, e)

            # removal blocks the next request of a token already in use (the sign-in service still caches its address)
            out, e = invite("alice", "new@example.com", remove=True)
            check("remove: the reply says what stops and that machine tokens are revoked separately", not e and out.startswith("Removed the registration of new@example.com from board main.")
                  and "From its next request on, that address gets no list, read or call of this board through a connector" in out and "Machine tokens and enrolled keys are not part of a registration: revoke separately" in out and members()["new@example.com"]["boards"] == [], (out, e))
            r = verify(first)
            who = r.headers.get("x-verified-user", "")
            _n, e = through(who or "x", listing)
            check("remove: the next request with the token issued before is refused at the front door", r.status_code == 200 and _n is None and "not a member of any board" in e, (r.status_code, who, e))
            _o, e = through("new@example.com", lambda c: c.call_tool("brief", {}))
            check("remove: ... a call too", "not a member of any board" in e, e)
            invite("alice", "new@example.com")
            check("again: a new registration records the account anew", members()["new@example.com"]["invited"]["google_sub"] == "")


# ================================================================ 5. a direct connection, and the board's own web sign-in
def part_direct():
    reset_members()
    invites.register("new@example.com", "alice", S)
    saved, saved_get = _cfg.CFG["behind_frontdoor"], deps.get_access_token
    _cfg.CFG["behind_frontdoor"] = {k: v for k, v in saved.items() if k != "identity_secret_file"}
    from types import SimpleNamespace
    claims = {}
    deps.get_access_token = lambda: SimpleNamespace(claims=dict(claims))
    try:
        claims.update(email="new@example.com", sub="111", email_verified="false")
        e = raised(_oauth._who)
        check("direct: an unverified invited address is refused with the address and the reason", e is not None and "Refused: new@example.com is not let in. Google does not report" in str(e), e)
        claims.update(email_verified="true")
        check("direct: the verified one is let in and recorded", _oauth._who() == "new@example.com" and members()["new@example.com"]["invited"]["google_sub"] == "111")
        claims.update(sub="222")
        check("direct: another account is refused", "another Google account" in str(raised(_oauth._who)))
        claims.clear(); claims.update(email="new@example.com", via="portal")
        e = raised(_oauth._who)
        check("direct: the machine token is no Google sign-in, so no registration refuses it", e is None, e)
        claims.clear(); claims.update(email="alice@example.com", via="portal")
        e = raised(_tool.stackshot_invite, "m@example.com")
        check("direct: a machine token invites nobody", e is not None and str(e) == _tool.MACHINE and "m@example.com" not in members(), e)
        claims.clear(); claims.update(email="alice@example.com", sub="900", email_verified="true")
        out = _tool.stackshot_invite("m@example.com")
        check("direct: the admin's own Google sign-in invites", out.startswith("Registered m@example.com") and "m@example.com" in members(), out)
        claims.clear(); claims.update(email="bob@example.com", sub="901", email_verified="true")
        check("direct: another member does not", str(raised(_tool.stackshot_invite, "n@example.com")) == _tool.NOT_ADMIN and "n@example.com" not in members())
        invites.remove("new@example.com", S)
        claims.clear(); claims.update(email="new@example.com", sub="111", email_verified="true")
        check("direct: a removed address is refused at its next call", "is not allowed on this board" in str(raised(_oauth._who)))
        claims.clear(); claims.update(email="alice@example.com", sub="900", email_verified="true")
        out = _tool.stackshot_invite("new@example.com")
        check("direct: a registration that keeps an earlier account says so and names the way to let it in again", out.startswith("Registered new@example.com on board main.\nNote: an earlier Google account of new@example.com was kept")
              and "is refused on this registration" in out and 'remove this registration (invite(address="new@example.com", remove=true)) and then invite again' in out, out)
        check("direct: a registration with no earlier account carries no such note", "earlier Google account" not in _tool.stackshot_invite("fresh@example.com"))
    finally:
        _cfg.CFG["behind_frontdoor"], deps.get_access_token = saved, saved_get

    # the board's own web sign-in
    reset_members()
    invites.register("new@example.com", "alice", S)
    real_http, real_cid = _signin._ui_http, _signin._ui_client_id
    token = [""]
    _signin._ui_http = lambda *a, **k: (200, {"access_token": token[0]})
    _signin._ui_client_id = lambda: "board-client"
    try:
        with TestClient(server.mcp.http_app()) as c:
            def callback(t):
                token[0] = t
                flow = _signin._ui_sign(json.dumps({"state": "s1", "verifier": "v" * 50, "next": "/", "exp": _signin._ui_now() + 600}))
                c.cookies.clear()
                r = c.get("/ui/callback?code=abc&state=s1", cookies={"stackshot_ui_flow": flow}, follow_redirects=False)
                sess = cookie_of(r)
                c.cookies.clear()
                return r, sess
            nav = {"Sec-Fetch-Mode": "navigate"}
            see = lambda sess: c.get("/", cookies={"stackshot_ui": sess}, headers=nav, follow_redirects=False)
            cookie_of = lambda r: next((v.split(";")[0].split("=", 1)[1].strip('"') for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("stackshot_ui=")), "")
            r, sess = callback(google("ui-unv", "new@example.com", "111", "false"))
            check("web: an unverified invited address gets no session and is told why", r.status_code == 403 and not sess and r.text.startswith("new@example.com is not let in. Google does not report"), (r.status_code, r.text))
            r, sess = callback(google("ui-ok", "new@example.com", "111"))
            check("web: the verified one gets a session", r.status_code == 302 and sess and see(sess).status_code == 200, (r.status_code, r.text))
            data = json.loads(_signin._ui_unsign(sess) or "{}")
            check("web: ... which holds the account's id", data.get("sub") == "111", sorted(data))
            r2, sess2 = callback(google("ui-two", "new@example.com", "222"))
            check("web: another account gets none", r2.status_code == 403 and not sess2 and "another Google account" in r2.text, (r2.status_code, r2.text))
            r3, hand = callback(google("ui-bob", "bob@example.com", "901", "false"))
            check("web: a member written by hand signs in as before, with no account id kept", r3.status_code == 302 and "sub" not in json.loads(_signin._ui_unsign(hand)) and see(hand).status_code == 200, (r3.status_code, r3.text))
            old = _signin._ui_sign(json.dumps({"email": "new@example.com", "sub": "111", "exp": _signin._ui_now() + 86400 * _signin._ui_days() - _signin._UI_RENEW_AFTER - 60}))
            c.cookies.clear()
            r5 = see(old)
            renewed = cookie_of(r5)
            c.cookies.clear()
            kept = json.loads(_signin._ui_unsign(renewed) or "{}")
            check("web: a renewed session keeps the account's id, and holds", r5.status_code == 200 and kept.get("sub") == "111" and see(renewed).status_code == 200, (r5.status_code, sorted(kept)))
            got = members(); got["bob"]["invited"] = {"by": "alice", "at": "", "google_sub": ""}; REAL_MEMBERS.write_text(json.dumps(got))
            c.cookies.clear()
            check("web: a session with no account id ends where its address is now an invitation nobody has joined", see(hand).status_code == 302, see(hand).status_code)
            invites.remove("new@example.com", S)
            check("web: removal ends the session at its next request", see(sess).status_code == 302 and see(sess).headers["location"].startswith("/ui/login"), see(sess).status_code)
            invites.register("new@example.com", "alice", S)
            check("web: a new registration does not revive the old session before that account signs in", see(sess).status_code == 302, see(sess).status_code)
            invites.admit("new@example.com", "333", True)
            check("web: ... nor after another account has joined", see(sess).status_code == 302, see(sess).status_code)
            r4, _s = callback("no-such-token")
            check("web: a token that does not hold gets no session", r4.status_code == 403, r4.status_code)
    finally:
        _signin._ui_http, _signin._ui_client_id = real_http, real_cid


# ================================================================ 6. the setup page and the redirect URIs
def part_open():
    reset_members()
    invites.register("new@example.com", "alice", S)
    with TestClient(server.mcp.http_app()) as c:
        r = c.get("/join", follow_redirects=False)
        body = r.text
        check("page: open with no sign-in, the connector address and the steps on it", r.status_code == 200 and "text/html" in r.headers["content-type"] and BASE_URL + "/mcp" in body
              and f"claude mcp add --transport http board {BASE_URL}/mcp" in body and all(x in body for x in ("claude.ai", "Claude Code", "ChatGPT", "Cursor", "mcpServers", "brief tool")), (r.status_code, body[:300]))
        low = body.lower()
        secrets_held = [pathlib.Path(p).read_text().strip() for p in (IDENTITY, VERIFY, BEARER)] + [PORTAL, "test-secret", "test-client-id"]
        check("page: no member, no address, no board name and no secret", not any(x.lower() in low for x in ("alice", "bob", "carol", "new@example.com", "@example.com", str(MEMBERS)))
              and "main" not in re.sub(r"<style>.*?</style>", "", low) and not any(x in body for x in secrets_held), body)
        for q in ("?email=new@example.com", "?email=nobody@example.com", "?next=//evil.example&x=<script>alert(1)</script>"):
            check(f"page: the same whatever is asked ({q[:20]})", c.get("/join" + q).text == body)
        h = r.headers
        check("page: framed by nobody, loads nothing, cached nowhere", h.get("cache-control") == "no-store" and "default-src 'none'" in h.get("content-security-policy", "") and "frame-ancestors 'none'" in h["content-security-policy"]
              and h.get("x-content-type-options") == "nosniff" and h.get("referrer-policy") == "no-referrer" and "<script" not in low and "DENY" in h.get("x-frame-options", ""), dict(h))
        check("page: nothing is written by a read of it", c.post("/join").status_code in (404, 405))
        hostile = _join.page('https://x.example.com/"><script>alert(1)</script>&')
        check("page: what goes on it is escaped", "<script>" not in hostile and "&lt;script&gt;alert(1)&lt;/script&gt;&amp;" in hostile, hostile[:400])
        per, ceiling = _join.PER_SOURCE, _join.CEILING
        _join.PER_SOURCE, _join.CEILING = RateLimit(2, 60), RateLimit(600, 60)
        try:
            got = [c.get("/join") for _ in range(4)]
            check("page: one source is bounded, with Retry-After", [x.status_code for x in got] == [200, 200, 429, 429] and int(got[2].headers["retry-after"]) >= 1 and "mcp" not in got[2].text, [x.status_code for x in got])
            _join.PER_SOURCE, _join.CEILING = RateLimit(100, 60), RateLimit(1, 60)
            got = [c.get("/join") for _ in range(3)]
            check("page: so are all sources together", [x.status_code for x in got] == [200, 429, 429], [x.status_code for x in got])

            def read(address):
                return asyncio.run(_join.join(Request({"type": "http", "method": "GET", "path": "/join", "query_string": b"", "headers": [], "client": (address, 1)}))).status_code
            _join.PER_SOURCE, _join.CEILING = RateLimit(1, 60), RateLimit(600, 60)
            got = [read(a) for a in ("2001:db8:1:2::1", "2001:db8:1:2:ffff::9", "2001:db8:1:3::1", "203.0.113.7", "::ffff:203.0.113.7", "203.0.113.8")]
            check("page: a source is an IPv6 /64, and an IPv4-mapped address the IPv4 one", got == [200, 429, 200, 200, 429, 200], got)
            _join.PER_SOURCE = RateLimit(1, 60)
            with serving(server.mcp.http_app()) as board:
                got = [httpx.get(board + "/join", headers={"x-forwarded-for": a}, timeout=30).status_code for a in ("203.0.113.20", "203.0.113.20", "203.0.113.21", "2001:db8:9::1", "2001:db8:9::2")]
            check("page: behind a proxy on the loopback address the source is the client it names", got == [200, 429, 200, 200, 429], got)
        finally:
            _join.PER_SOURCE, _join.CEILING = per, ceiling

        def asks(uri):
            """Whether the sign-in takes `uri` from a client that registered itself with it."""
            reg = c.post("/register", json={"client_name": "t", "redirect_uris": [uri], "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], "token_endpoint_auth_method": "none"})
            if reg.status_code not in (200, 201):
                return False
            ch = base64.urlsafe_b64encode(hashlib.sha256(b"v" * 50).digest()).decode().rstrip("=")
            a = c.get("/authorize", params={"response_type": "code", "client_id": reg.json()["client_id"], "redirect_uri": uri, "code_challenge": ch, "code_challenge_method": "S256", "state": "x"}, follow_redirects=False)
            return a.status_code in (302, 303) and "/consent" in a.headers.get("location", "")
        taken = ["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback", "https://chatgpt.com/connector_platform_oauth_redirect",
                 "http://localhost:53117/callback", "http://127.0.0.1:40000/callback", "http://localhost:8787/callback", "https://www.cursor.com/agents/mcp/oauth/callback"]
        for uri in taken:
            check(f"redirect: taken: {uri}", asks(uri))
        for uri in ("https://chatgpt.com/connector_platform_oauth_redirect?x=1", "https://chatgpt.com/connector_platform_oauth_redirect;x=1", "https://chatgpt.com/connector_platform_oauth_redirect#x",
                    "https://chatgpt.com:443/connector_platform_oauth_redirect", "https://CHATGPT.com/connector_platform_oauth_redirect", "https://claude.ai/api/mcp/auth_callback?x=1"):
            check(f"redirect: the library takes this too, as the docs say: {uri}", asks(uri))
        for uri in ("https://chatgpt.com:8443/connector_platform_oauth_redirect", "https://evil.example/callback", "https://chatgpt.com/connector_platform_oauth_redirect/x", "https://chatgpt.com/connector/oauth/abc", "https://chatgpt.com.evil.example/connector_platform_oauth_redirect",
                    "http://chatgpt.com/connector_platform_oauth_redirect", "http://localhost:53117/other", "http://localhost:53117/callback/x", "http://localhost.evil.example/callback",
                    "https://cursor.com/agents/mcp/oauth/callback", "https://www.cursor.com/agents/mcp/oauth/callbackx", "cursor://anysphere.cursor-mcp/oauth/callback", "http://203.0.113.5:8787/callback"):
            check(f"redirect: refused: {uri}", not asks(uri))
    check("redirect: no host of the list is a wildcard", all("*" not in u for u in invites.APP_REDIRECT_URIS), invites.APP_REDIRECT_URIS)


# ================================================================ 7. a board with no [invites]
PROBE = r'''
import asyncio, json, logging
logging.disable(logging.WARNING)
from starlette.testclient import TestClient
from stackshot.web import server
from stackshot.core import config as c
from stackshot.web.auth import oauth
with TestClient(server.mcp.http_app()) as t:
    r = t.get("/join", follow_redirects=False)
    routes = [getattr(x, "path", "") for x in t.app.routes]
print(json.dumps({"tools": [x.name for x in asyncio.run(server.mcp.list_tools(run_middleware=False))], "instructions": server.mcp.instructions, "status": r.status_code, "body": r.text[:300], "uris": oauth._redirect_uris(),
                  "configured": c.CFG["auth"]["allowed_client_redirect_uris"], "routes": routes}))
'''


def part_off():
    r = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=180, cwd=STACK, env={**os.environ, "STACKSHOT_CONFIG": OFF, "PYTHONPATH": STACK})
    if r.returncode:
        return check("off: the board starts", False, r.stderr[-800:])
    d = json.loads(r.stdout.strip().splitlines()[-1])
    check("off: no invite tool", "invite" not in d["tools"] and "brief" in d["tools"], d["tools"])
    check("off: nothing about newcomers in the instructions", "just joined" not in d["instructions"] and "invite tool" not in d["instructions"], d["instructions"][-400:])
    check("off: no setup page, and no route for one", d["status"] != 200 and "/{name:path}" in d["routes"] and "/join" not in d["routes"], (d["status"], d["body"], d["routes"]))
    check("off: the redirect URIs are the configured ones and the board's own callback", d["uris"] == d["configured"] + [BASE_URL + "/ui/callback"], d["uris"])


# the front door's words, with no invitation at all
def part_words():
    check("words: a name that is no address is told what it was always told", fdprov.not_a_member("carol") == fdprov.NOT_A_MEMBER and fdprov.not_a_member(None) == fdprov.NOT_A_MEMBER)
    REAL_MEMBERS.write_text(json.dumps({"carol@example.com": ["side"]}))
    real_who = _oauth._who
    _oauth._who = lambda: _members.PLACEHOLDER
    try:
        e = raised(_tool._admin, replace(S, admins=(_members.PLACEHOLDER,)))
    finally:
        _oauth._who = real_who
    check("tool: the placeholder of a board that lists nobody is no admin, whatever admins names", e is not None and str(e) == _tool.NOT_ADMIN, e)
    check("words: a reason this version does not know is still a refusal", ident.barred_of("!refused:newer:a@example.com") == ("unreadable", "a@example.com") and ident.barred_of("alice") is None and ident.barred_of(None) is None)
    reset_members({"!refused:unverified:z@example.com": ["main"]})
    s, _p = fc.parse({"frontdoor": {"identity_header": "x-verified-user", "identity_secret_file": IDENTITY, "members_file": str(MEMBERS),
                                    "backends": [{"name": "main", "kind": "board", "url": "http://127.0.0.1:9/mcp", "health_url": "http://127.0.0.1:9/healthz", "token_file": BEARER}]}})
    d = fdprov.Door(s)
    check("words: a refused identity is a member of nothing, whatever the file lists", d.backends_of("!refused:unverified:z@example.com") == [] and d.backends_of("alice") == ["main"])


# the sign-in service and a 403 that is no registration's refusal
def part_service():
    s = replace(sc.parse({})[0], present=True, port=1, board_verify_url="http://board.invalid/frontdoor/verify", verify_secret_file=VERIFY, members_file=str(MEMBERS))
    answers = [None]

    class Fake(signin.Service):
        async def _get(self, headers):
            return answers[0]
    svc = Fake(s, client=object())
    ask = lambda status, body: (answers.__setitem__(0, (status, "", body if isinstance(body, bytes) else json.dumps(body).encode())), asyncio.run(svc.ask("k" * 32, "tok")))[1]
    ok = {"error": "not_admitted", "why": "unverified", "email": "A@Example.com"}
    check("service: a registration's refusal is read as one", ask(403, ok) == ("barred", ident.barred("unverified", "a@example.com")), ask(403, ok))
    for label, status, body in (("another error word", 403, {**ok, "error": "no"}), ("a reason it does not know", 403, {**ok, "why": "x"}), ("a reason that is no text", 403, {**ok, "why": ["unverified"]}),
                                ("no address", 403, {k: v for k, v in ok.items() if k != "email"}), ("an address with a line break", 403, {**ok, "email": "a@example.com\nx: y"}),
                                ("plain text", 403, b"refused: the signed header"), ("a list", 403, [1]), ("a 500 that says so", 500, ok)):
        got = ask(status, body)
        check(f"service: {label} is an outage, never let in", got[0] == "down", got)
    check("service: a 200 with the refusal's words is no sign-in either", ask(200, ok)[0] == "down", ask(200, ok))


try:
    for part in (part_settings, part_file, part_admit, part_words, part_service, part_chain, part_direct, part_open, part_off):
        try:
            part()
        except Exception:      # noqa: BLE001
            import traceback
            check(f"{part.__name__} ran to its end", False, traceback.format_exc()[-1500:])
finally:
    server.mcp.auth.verify_token = _real_verify

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
