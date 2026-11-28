"""Scenario test for the rule a board's name must pass (stackshot/core/board_names.py): the name is the first part of the board's web address, so it must be a safe
path segment and must not be one the server or the edge already answers. Fixture data, no network, no server process (the real app is built, never started).

Covers: valid() on its own (a reason for a refused name, None for an accepted one); every reserved word refused in lower, capitalized and upper case with the reserved reason;
the slug edges (empty, one letter, 33 characters, a leading digit or hyphen, a dot, a slash, a percent-encoded slash, a backslash, a space inside and trailing, a newline,
non-ASCII look-alikes of ASCII letters, a non-text value) and the 2 and 32 character limits; the names in use and the two new boards accepted; the route table of the real
app, every first path segment of which must be reserved (so a later route cannot silently take a board's name); the front door's config load refusing a backend with a
refused name and saying why; and a board's `[behind_frontdoor] board_name` named in the config notes and leaving the board with no members.

    tests/run-suite board_names        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="boardnames-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "state", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.core import board_names as bn, behind_door
from stackshot.core import frontdoor_config as fc
from stackshot.frontdoor import config as fdconf

# ---- 1. the names in use and the two new boards pass
for ok in ("main", "brain", "side", "team-high", "lab-dev", "ab", "a1", "a" + "b" * 31, "team-forge2", "box-b"):
    check(f"accepted: {ok!r}", bn.valid(ok) is None, bn.valid(ok))

# ---- 2. every reserved word is refused in three cases, with the reserved reason
MUST = ("items canvas mockup login api client files search closed projects runners audits boards static fonts favicon.svg manifest.webmanifest apple-touch-icon.png "
        "for-you landed prefs routing audit frontdoor admin new infra verify hook well-known authorize token register consent auth join mcp healthz ui").split()
check("the reserved set holds every word the plan names", [w for w in MUST if w not in bn.RESERVED] == [], [w for w in MUST if w not in bn.RESERVED])
check("every reserved word is lower case", [w for w in bn.RESERVED if w != w.lower()] == [])
for w in sorted(bn.RESERVED):
    for form in (w, w.capitalize(), w.upper()):
        why = bn.valid(form)
        check(f"reserved {form!r} is refused as reserved", bool(why) and "reserved" in why, why)

# ---- 3. the slug edges
def u(*codes): return "".join(chr(c) for c in codes)
EDGES = {
    "empty": "", "one letter": "a", "33 characters": "a" * 33, "leading digit": "1abc", "leading hyphen": "-abc", "only digits": "12", "dot": "a.b", "slash": "a/b",
    "leading slash": "/ab", "percent-encoded slash": "a%2fb", "percent-encoded slash in upper case": "a%2Fb", "percent sign": "a%b", "backslash": "a" + chr(92) + "b",
    "underscore": "a_b", "inner space": "a b", "trailing space": "ab ", "leading space": " ab", "trailing newline": "ab" + chr(10), "tab": "a" + chr(9) + "b",
    "upper case": "Alpha", "mixed case": "aLpha", "cyrillic a": u(0x430) + "bc", "cyrillic o inside": "d" + u(0x43e) + "me", "fullwidth letters": u(0xff41, 0xff42),
    "dotless i": "m" + u(0x131) + "n", "kelvin sign": "bran" + u(0x212a), "long s": u(0x17f) + "ide", "accented e": "caf" + u(0xe9), "zero width space": "ab" + u(0x200b) + "c",
    "right-to-left mark": "ab" + u(0x200f), "null byte": "ab" + chr(0), "query": "ab?x", "fragment": "ab#x", "colon": "a:b", "at": "a@b", "dot dot": "..",
}
for label, name in EDGES.items():
    why = bn.valid(name)
    check(f"refused: {label}", isinstance(why, str) and bool(why), why)
check("a reason names the rule for a slug fault", "lower-case letters, digits and hyphens" in (bn.valid("1abc") or ""), bn.valid("1abc"))
check("a refused name's reason is one line", all("\n" not in (bn.valid(n) or "") for n in EDGES.values()))
check("a very long name's reason stays short", len(bn.valid("a" * 5000) or "") < 400, len(bn.valid("a" * 5000) or ""))
check("32 characters is accepted, 33 refused", bn.valid("a" * 32) is None and bn.valid("a" * 33) is not None)
check("a name that is not text is refused", all(bn.valid(v) for v in (None, 5, b"main", ["main"], True)), [bn.valid(v) for v in (None, 5, b"main")])
check("a reserved look-alike through case folding is refused (kelvin sign in token)", bn.valid("to" + u(0x212a) + "en") is not None)

# ---- 3b. a configured page directory is a name the page route answers
from stackshot.core import config as _cfg
check("a page directory of [pages] dirs is refused by name", all(bn.valid(d) for d in _cfg.page_dirs()), _cfg.page_dirs())
_cfg.CFG["pages"]["dirs"] = ["projects", "infra", "labs", "deep/er"]
try:
    for d in ("labs", "Labs", "deep", "projects", "infra"):
        why = bn.valid(d)
        check(f"configured page dir {d!r} is refused", bool(why) and "reserved" in why, why)
    check("main and brain still pass beside configured page dirs", bn.valid("main") is None and bn.valid("brain") is None)
finally:
    _cfg.CFG["pages"]["dirs"] = ["projects"]
check("a name that is no longer a page dir passes", bn.valid("labs") is None, bn.valid("labs"))

# ---- 4. the route table of the real app: every first path segment is reserved
from stackshot.web import server
app = server.mcp.http_app()
def first_segment(path):
    seg = path.strip("/").split("/", 1)[0]
    return None if not seg or seg.startswith("{") else seg      # the root, and a path whose first part is a parameter, name no word
def walk(routes, prefix=""):
    for r in routes:
        path = prefix + (getattr(r, "path", "") or "")
        sub = getattr(r, "routes", None)
        if sub is not None: yield from walk(sub, path)
        else: yield path
paths = sorted(set(walk(app.routes)))
segments = {first_segment(p) for p in paths} - {None}
check("the real app's route table was read (it has routes and some first segments)", len(paths) > 20 and len(segments) > 10, (len(paths), len(segments)))
check("the table has the items, canvas and client routes", {"items", "canvas", "client"} <= segments, sorted(segments))
missing = sorted(s for s in segments if s.lower() not in bn.RESERVED)
check("every first path segment of every route is reserved (add it to RESERVED in core/board_names.py)", missing == [], missing)
check("no route's first segment is a valid board name", [s for s in segments if bn.valid(s) is None] == [], [s for s in segments if bn.valid(s) is None])

# ---- 5. the front door's config load refuses a backend with a refused name
def door_cfg(*names):
    secret = T / "ident.key"; secret.write_text("x" * 40 + "\n"); secret.chmod(0o600)
    members = T / "members.json"; members.write_text("{}")
    tok = T / "b.token"; tok.write_text("t" * 40 + "\n"); tok.chmod(0o600)
    return {"frontdoor": {"identity_header": "x-forwarded-user", "identity_secret_file": str(secret), "members_file": str(members),
                          "backends": [{"name": n, "kind": "board", "url": f"http://127.0.0.1:{8010 + i}/mcp", "token_file": str(tok)} for i, n in enumerate(names)]}}
def load_error(*names):
    try: fdconf.load(door_cfg(*names)); return None
    except fdconf.ConfigError as e: return str(e)
check("a front door with the names in use loads", load_error("main", "brain", "team-high", "lab-dev") is None, load_error("main", "brain", "team-high", "lab-dev"))
for bad in ("items", "Canvas", "LOGIN", "1abc", "a", "Main", "a" * 33, "team.one"):
    why = load_error("main", bad)
    check(f"front door load refuses a backend named {bad!r} and says why", bool(why) and repr(bad) in why and bn.valid(bad)[:30] in why, why)

# ---- 6. a board's board_name: the config note names the reason, and the board has no members until it is fixed
def door_settings(name):
    cfg = {"behind_frontdoor": {"identity_secret_file": str(T / "ident.key"), "members_file": str(T / "members.json"), "board_name": name}}
    return behind_door.parse(cfg)
for bad in ("items", "Canvas", "LOGIN"):
    s, notes = door_settings(bad)
    check(f"board_name {bad!r}: a note carries the reason and the board name is unset", any(bn.valid(bad)[:40] in n for n in notes) and s.board == "", (s.board, notes))
for ok in ("main", "team-high", "lab-dev"):
    s, notes = door_settings(ok)
    check(f"board_name {ok!r}: no note, name kept", s.board == ok and not any("board_name" in n for n in notes), (s.board, notes))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
