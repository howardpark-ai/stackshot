"""Scenario test for steps (b) to (e) of the client contract (board batch 5) — fixture data, no live store, no network.

Covers: the server's own state of sessions and machines and the fleet-shaped view it materialises (clients.py: a hook's
registration, a puller's check-in, a rename, a machine going offline, the operator session); what makes a machine online
(versions.py); the inbox (inbox.py: lease and confirmation, folding, a line that follows its name, pause, release and hold);
push.py and the reboot queue; the client API's writes over HTTP, the long poll included; the puller end to end against a
fake CLI inbox socket; the hooks' verbs; the pane gate off the server box, the server away included; the board's own sign-in.

    tests/run-suite contract        → exit 0 / 1"""
import contextlib, hashlib, io, json, os, re, socket, subprocess, sys, pathlib, tempfile, logging, threading, time
BID_A = 9158
BID_B = 9159
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="contracttest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("session_links", f"{tmp}/sala"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai"), ("base_url", "https://stackshot.test")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^title = "[^"]*"', 'title = "stackshot: example"', toml, count=1); assert n == 1   # the instance's title: the board's pages carry it as it is
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1   # the fixtures' subjects
toml, n = re.subn(r"(?m)^ui_open = (true|false)", "ui_open = false", toml); assert n == 1
toml, n = re.subn(r"(?m)^allowed_emails = .*$", 'allowed_emails = ["you@example.com"]', toml); assert n == 1   # the address the sign-in checks use
toml, n = re.subn(r'(?m)^mode = "google"', 'mode = "google"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com", STACKSHOT_GOOGLE_CLIENT_SECRET="test-secret")
for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL", "STACKSHOT_AUTH", "BOARD_MCP_AUTH"): os.environ.pop(k, None)
ME = socket.gethostname()
for d in ("store/a", "state/anchor-hub", "state/site", "secrets", "brain/projects", "reg"): (T / d).mkdir(parents=True)
(T / "names.tsv").write_text(f"# hostname\tfleet\tletter\n{ME}\ttestbox\ta\nWIN-BOX\tbox-far\tb\n")
U = lambda n: f"{n:08d}-0000-4000-8000-000000000000"
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "sparrow", "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": ""}}}))
(T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] item 1", "description": "A thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": "sparrow", "project": "projects/alpha"}}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\nname: Alpha\n---\n\n# Alpha\n")   # name: as in its registry entry, so a background publish that rebuilds the registry keeps the title
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')   # versioned at the server's start (render.py ICON_V)
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))
rd = lambda p: json.loads(pathlib.Path(p).read_text())
_hv = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()[:12]   # an icon's URL version, computed here independently of render.py


def _png_rgba(b: bytes):
    """A PNG's pixels as rows of (r, g, b, a), for the app icons' checks: 8-bit RGB or RGBA, not interlaced (what resvg
    writes); anything else raises. Pure Python (zlib), so the suite needs no image library."""
    import struct, zlib
    assert b[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    i, idat, hdr = 8, b"", None
    while i < len(b):
        n, typ = struct.unpack(">I4s", b[i:i + 8]); data = b[i + 8:i + 8 + n]; i += 12 + n
        if typ == b"IHDR": hdr = struct.unpack(">IIBBBBB", data)
        elif typ == b"IDAT": idat += data
        elif typ == b"IEND": break
    w, h, depth, ctype, _c, _f, interlace = hdr
    assert depth == 8 and ctype in (2, 6) and interlace == 0, f"unsupported PNG: depth {depth}, colour type {ctype}, interlace {interlace}"
    bpp = 4 if ctype == 6 else 3; stride = w * bpp; raw = zlib.decompress(idat); prev = bytearray(stride); rows = []
    for y in range(h):
        f = raw[y * (stride + 1)]; cur = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):
            a = cur[x - bpp] if x >= bpp else 0; up = prev[x]; c = prev[x - bpp] if x >= bpp else 0
            if f == 1: cur[x] = (cur[x] + a) & 255
            elif f == 2: cur[x] = (cur[x] + up) & 255
            elif f == 3: cur[x] = (cur[x] + (a + up) // 2) & 255
            elif f == 4:
                p = a + up - c; pa, pb, pc = abs(p - a), abs(p - up), abs(p - c)
                cur[x] = (cur[x] + (a if pa <= pb and pa <= pc else up if pb <= pc else c)) & 255
        rows.append([tuple(cur[x:x + bpp]) + ((255,) if bpp == 3 else ()) for x in range(0, stride, bpp)]); prev = cur
    return w, h, rows

# ================================================================= 1. the server's own state and its view (clients.py)
from stackshot.core import config as cfg; from stackshot.fleet import clients as cl; from stackshot.fleet import fleet as fl
V = T / "state/clients/fleet"; T0 = 1790780400.0
check("readers are pointed at the materialised view", str(cfg.fleet_dir()) == str(V), cfg.fleet_dir())
# sala's live heartbeat store ([client] session_links): the one source of a pane's link. Written as sala writes it, a new file put in place; the view takes each row's url by transcript id.
def sala(L, rows):
    d = T / "sala" / L; d.mkdir(parents=True, exist_ok=True); t = d / ".sessions.json.tmp"
    t.write_text(json.dumps({u: {"name": n, "url": url, "machine": L} for u, (n, url) in rows.items()})); os.replace(t, d / "sessions.json")
LINK = "https://term.test/#s=work-x"; SB = {U(1): ("work-x", LINK)}
sala("b", SB)
s = cl.register("box-far", {"uuid": U(1), "name": "work-x", "bridge": "session_abc", "cli": "2.1.0", "status": "idle"}, now=T0)
row = rd(V / "b/sessions.json")[U(1)]
check("a hook's registration is in the view: name, machine, and the link sala writes for its transcript id", (row["name"], row["url"], row["machine"]) == ("work-x", LINK, "b"), row)
cl.register("box-far", {"uuid": U(1), "name": "work-y", "bridge": "session_abc"}, now=T0 + 5)
row = rd(V / "b/sessions.json")[U(1)]
check("a rename is recorded the way sala's heartbeat records it", row["name"] == "work-y" and row["previous_name"] == "work-x" and row.get("renamed_at"), row)
try: cl.register("box-far", {"uuid": "not-a-uuid", "name": "x"}); ok = False
except ValueError: ok = True
check("a record without a transcript id is refused", ok)
check("a machine with hooks only has no online verdict yet", "online" not in rd(V / "b/machine.json"), rd(V / "b/machine.json"))
cl.checkin("box-far", [{"uuid": U(1), "name": "work-y", "bridge": "session_abc"}, {"uuid": U(2), "name": "work-z", "bridge": ""}], {"claude": "2.1.5", "platform": "win32"}, now=T0 + 10)
m = rd(V / "b/machine.json"); rows = rd(V / "b/sessions.json")
check("a puller's check-in: the machine is online, with its CLI version", m["online"]["ok"] is True and m["claude"] == "2.1.5" and m["fleet"] == "box-far" and m["letter"] == "b", m)
check("…and its sessions are the machine's list (a session sala has no row for has an empty link)", set(rows) == {U(1), U(2)} and rows[U(2)]["url"] == "", rows)
mt = [(V / "b" / f).stat().st_mtime_ns for f in ("machine.json", "sessions.json")]
time.sleep(0.02); cl.checkin("box-far", [{"uuid": U(1), "name": "work-y", "bridge": "session_abc"}, {"uuid": U(2), "name": "work-z", "bridge": ""}], {"claude": "2.1.5"}, now=T0 + 60)
check("a check-in that changes no fact rewrites no file (a new mtime would republish the board)", mt == [(V / "b" / f).stat().st_mtime_ns for f in ("machine.json", "sessions.json")])
# ---- a pane being relaunched (a recycle: /exit, resume by transcript id under the CLI's placeholder name, sala's /rename, the bridge)
cl.checkin("box-far", [{"uuid": U(2), "name": "work-z"}], {}, now=T0 + 62)
rows = rd(V / "b/sessions.json")
check("a session the puller stopped reporting stays in the view as last known (name, link, machine), marked gone",
      set(rows) == {U(1), U(2)} and (rows[U(1)]["name"], rows[U(1)]["url"], rows[U(1)]["machine"], rows[U(1)]["gone"]) == ("work-y", LINK, "b", cl._iso(T0 + 62)), rows)
cl.checkin("box-far", [{"uuid": U(1), "name": "home-1f", "name_source": "auto", "bridge": ""}, {"uuid": U(2), "name": "work-z"}], {}, now=T0 + 64)
row = rd(V / "b/sessions.json")[U(1)]
check("…relaunched under the CLI's placeholder name with no bridge yet: the name and link on record stand, gone is cleared, no rename recorded",
      row["name"] == "work-y" and row["url"] == LINK and "gone" not in row and row["previous_name"] == "work-x", row)
cl.checkin("box-far", [{"uuid": U(1), "name": "work-y2", "name_source": "user", "bridge": "session_abc"}, {"uuid": U(2), "name": "work-z"}], {}, now=T0 + 66)
row = rd(V / "b/sessions.json")[U(1)]
check("…a /rename and the bridge are live values again (a user-given name is a rename)", row["name"] == "work-y2" and row["previous_name"] == "work-y" and row["renamed_at"] == cl._iso(T0 + 66) and row["url"] == LINK, row)
cl.checkin("box-far", [{"uuid": U(1), "name": "work-y2", "name_source": "user", "bridge": ""}, {"uuid": U(2), "name": "work-z"}], {}, now=T0 + 68)
check("…a bridge that drops on a live session leaves sala's link in place", rd(V / "b/sessions.json")[U(1)]["url"] == LINK)
cl.checkin("box-far", [{"uuid": U(2), "name": "work-z"}], {}, now=T0 + 70)
check("a session that ended is held, marked gone, at the next check-in", rd(V / "b/sessions.json")[U(1)]["gone"] == cl._iso(T0 + 70))
cl.checkin("box-far", [], {}, partial=True, now=T0 + 80)
check("a partial list (a puller serving only some sessions) removes nothing", set(rd(V / "b/sessions.json")) == {U(1), U(2)})
check("no change while the puller is within its ten minutes and the gone session within its grace", cl.tick(now=T0 + 70 + 599) is False and rd(V / "b/machine.json")["online"]["ok"] is True)
ch = cl.tick(now=T0 + 80 + 601); m = rd(V / "b/machine.json")
check("a puller that stopped: its machine is offline since its last check-in", ch is True and m["online"]["ok"] is False and m["online"]["since"] == cl._iso(T0 + 80), m)
row = rd(V / "b/sessions.json").get(U(1)) or {}
check("past the grace a gone session keeps its identity in the view — name, link, machine, marked gone — and is present within the grace, not past it",
      (row.get("name"), row.get("url"), row.get("machine"), row.get("gone")) == ("work-y2", LINK, "b", cl._iso(T0 + 70)) and not fl.running(row)
      and fl.present(row, now=T0 + 70 + 599) and not fl.present(row, now=T0 + 80 + 601), row)
cl.register("laptop-9", {"uuid": U(3), "name": "home-roaming"}, now=T0 + 100)
L9 = cl.load()["machines"]["laptop-9"]["letter"]
check("a machine the names table does not know takes a free letter (never a, b, c or the ids' letter)", L9 not in ("a", "b", "c", "s") and U(3) in rd(V / L9 / "sessions.json"), L9)
cl.tick(now=T0 + 100 + 13 * 3600)
ss = cl.load()["sessions"]
check("a hook-only session with no sign of life for 12 hours is marked gone, its identity kept (so is one on a machine whose puller stopped)",
      ss[U(3)].get("gone") == cl._iso(T0 + 100 + 13 * 3600) and ss[U(3)]["name"] == "home-roaming" and ss[U(2)].get("gone") and U(3) in rd(V / L9 / "sessions.json"), {u: ss.get(u) for u in (U(2), U(3))})
T1 = T0 + 100 + 13 * 3600 + 10
cl.register("box-far", {"uuid": U(7), "name": "home-2e", "name_source": "collision"}, now=T1)
check("a placeholder is shown while it is the only name known", rd(V / "b/sessions.json")[U(7)]["name"] == "home-2e")
cl.register("box-far", {"uuid": U(7), "name": "work-w", "name_source": "user"}, now=T1 + 1)
row = rd(V / "b/sessions.json")[U(7)]
check("…and a /rename replaces it without recording it as a former name", row["name"] == "work-w" and "previous_name" not in row, row)
cl.register("box-far", {"uuid": U(7), "name": "stackshot-3f", "name_source": "derived"}, now=T1 + 2)
row = rd(V / "b/sessions.json")[U(7)]
check("a 'derived' placeholder (<cwd>-<2 hex>, 2026-10-07) never displaces a name on record", row["name"] == "work-w" and "previous_name" not in row, row)
# ---- the item: "home-b4" arrived for work-sample-bench with a nameSource outside PROVISIONAL; the CLI's placeholder shape <os user>-<2 hex> is refused too
class _Cap(logging.Handler):
    def __init__(s): super().__init__(); s.lines = []
    def emit(s, r): s.lines.append(r.getMessage())
cap = _Cap(); _hs = cl.log.handlers[:]; cl.log.handlers = [cap]; logging.disable(logging.NOTSET)
cl.register("box-far", {"uuid": U(50), "name": "work-sample-bench", "name_source": "user", "user": "home"}, now=T1)
for src in ("", "user"):
    cl.checkin("box-far", [{"uuid": U(50), "name": "home-b4", "name_source": src, "user": "home", "bridge": ""}], {}, partial=True, now=T1 + 1)
    row = rd(V / "b/sessions.json")[U(50)]
    check(f"a placeholder of the shape <user>-<2 hex> with name_source {src!r} does not displace a real name (no previous_name)", row["name"] == "work-sample-bench" and "previous_name" not in row, row)
cl.register("box-far", {"uuid": U(50), "name": "home-b4", "name_source": "", "user": ""}, now=T1 + 1)
row = rd(V / "b/sessions.json")[U(50)]
check("…nor does one from a client that sends no user (the generic shape, name_source not 'user')", row["name"] == "work-sample-bench" and "previous_name" not in row, row)
check("…each refusal is logged once, with the name_source the CLI sent", sum("placeholder refused" in l and "'home-b4'" in l for l in cap.lines) == 1 and any("name_source ''" in l for l in cap.lines), cap.lines)
cl.checkin("box-far", [{"uuid": U(50), "name": "work-sample-bench2", "name_source": "user", "user": "home", "bridge": ""}], {}, partial=True, now=T1 + 2)
row = rd(V / "b/sessions.json")[U(50)]
check("a real rename with name_source 'user' still applies", row["name"] == "work-sample-bench2" and row["previous_name"] == "work-sample-bench" and row["renamed_at"] == cl._iso(T1 + 2), row)
check("…and is logged old → new with its name_source", any(l.startswith("rename: work-sample-bench → work-sample-bench2") and "name_source 'user'" in l for l in cap.lines), cap.lines)
cl.checkin("box-far", [{"uuid": U(51), "name": "home-b4", "name_source": "", "user": "home", "bridge": ""}], {}, partial=True, now=T1 + 3)
cl.checkin("box-far", [{"uuid": U(51), "name": "home-b4", "name_source": "user", "user": "home", "bridge": ""}], {}, partial=True, now=T1 + 4)
check("a new session whose first name is the placeholder keeps it", rd(V / "b/sessions.json")[U(51)]["name"] == "home-b4")
cl.checkin("box-far", [{"uuid": U(51), "name": "example-docs", "name_source": "user", "user": "home", "bridge": ""}], {}, partial=True, now=T1 + 5)
row = rd(V / "b/sessions.json")[U(51)]
check("…until renamed (the placeholder not recorded as a former name)", row["name"] == "example-docs" and "previous_name" not in row, row)
cl.checkin("box-far", [{"uuid": U(52), "name": "work-x9", "name_source": "user", "user": "home", "bridge": ""}], {}, partial=True, now=T1 + 6)
cl.checkin("box-far", [{"uuid": U(52), "name": "home-garden", "name_source": "user", "user": "home", "bridge": ""}], {}, partial=True, now=T1 + 7)
row = rd(V / "b/sessions.json")[U(52)]
check("a real name like home-garden is a rename, not a placeholder", row["name"] == "home-garden" and row["previous_name"] == "work-x9", row)
cl.checkin("box-far", [{"uuid": U(52), "name": "example-docs", "name_source": "", "user": "", "bridge": ""}], {}, partial=True, now=T1 + 8)
row = rd(V / "b/sessions.json")[U(52)]
check("…and so is example-docs, also with no user and no name_source", row["name"] == "example-docs" and row["previous_name"] == "home-garden", row)
check("placeholder(): the CLI's shape for the user, never a real name", cl.placeholder("home-b4", "home") and cl.placeholder("home-1f", "home") and not cl.placeholder("home-garden", "home")
      and not cl.placeholder("example-docs", "home") and not cl.placeholder("work-e2", "home") and not cl.placeholder("home-b4", "", "user") and cl.placeholder("home-b4", "", "")
      and not cl.placeholder("example-docs", "", "") and not cl.placeholder("home-garden", "", ""))
logging.disable(logging.WARNING); cl.log.handlers = _hs
# ---- session links come from sala alone: never built from the bridge, never blanked when the bridge is down
Q = "https://term.test/#s=work-q"
sala("b", {**SB, U(9): ("work-q", Q)})
cl.checkin("box-far", [{"uuid": U(9), "name": "work-q", "bridge": ""}], {}, now=T1 + 2)
check("sala's term link is the session's link with no bridge at all", rd(V / "b/sessions.json")[U(9)]["url"] == Q, rd(V / "b/sessions.json")[U(9)])
cl.checkin("box-far", [{"uuid": U(9), "name": "work-q", "bridge": ""}], {}, now=T1 + 2 + 601)
check("…and stays past the grace with the bridge still down (no blanking)", rd(V / "b/sessions.json")[U(9)]["url"] == Q)
sala("b", {**SB, U(9): ("work-q", "")})
cl.checkin("box-far", [{"uuid": U(9), "name": "work-q", "bridge": "session_q"}], {}, now=T1 + 2 + 602)
check("a sala row with an empty url: no link, and none built from the bridge id", rd(V / "b/sessions.json")[U(9)]["url"] == "", rd(V / "b/sessions.json")[U(9)])
sala("b", SB); cl.tick(now=T1 + 2 + 602)
check("no sala row for the session: no link", rd(V / "b/sessions.json")[U(9)]["url"] == "")
sala("b", {**SB, U(9): ("work-q", Q)}); cl.tick(now=T1 + 2 + 602)
check("a row sala writes later is picked up at the next tick (the store is read again when a file changes)", rd(V / "b/sessions.json")[U(9)]["url"] == Q)
check("…and a read with nothing changed is served from the cache", cl.session_links() is cl.session_links() and cl.session_links().get(U(9)) == Q)
cap2 = _Cap(); cl.log.handlers = [cap2]; logging.disable(logging.NOTSET)
cfg.CFG["client"]["session_links"] = str(T / "no-such-sala")
cl.tick(now=T1 + 2 + 602); cl.tick(now=T1 + 2 + 602); cl.session_links()
check("a missing sala store: every pane is named without a link, nothing raises", all(r["url"] == "" for r in rd(V / "b/sessions.json").values()), rd(V / "b/sessions.json"))
check("…logged once, not on every read", sum("session links:" in l for l in cap2.lines) == 1 and "no-such-sala" in "".join(cap2.lines), cap2.lines)
(T / "bad-sala/b").mkdir(parents=True); (T / "bad-sala/b/sessions.json").write_text("{not json")
cfg.CFG["client"]["session_links"] = str(T / "bad-sala")
cl.tick(now=T1 + 2 + 602); cl.tick(now=T1 + 2 + 602)
check("an unreadable sessions.json: no links from it, logged once", cl.session_links() == {} and sum("unreadable" in l for l in cap2.lines) == 1, cap2.lines)
cfg.CFG["client"]["session_links"] = str(T / "sala")
cl.tick(now=T1 + 2 + 602)
check("…and the links are back once the store is", rd(V / "b/sessions.json")[U(9)]["url"] == Q)
for bad in ("javascript:alert(1)", "data:text/html,x", "term.test/#s=work-q"):
    sala("b", {**SB, U(9): ("work-q", bad)}); cl.tick(now=T1 + 2 + 602)
    check(f"a url that is not http(s) never becomes a link ({bad.split(':')[0]})", rd(V / "b/sessions.json")[U(9)]["url"] == "" and U(9) not in cl.session_links(), rd(V / "b/sessions.json")[U(9)])
sala("b", {**SB, U(9): ("work-q", "javascript:alert(1)")}); cl.tick(now=T1 + 2 + 602); cl.tick(now=T1 + 2 + 602)
check("…a skipped url is logged once, the same way as the other session-link problems", sum("not http(s)" in l for l in cap2.lines) == 1 and any(f"b/{U(9)[:8]}" in l for l in cap2.lines), cap2.lines)
sala("b", {**SB, U(9).upper(): ("work-q", Q)}); cl.tick(now=T1 + 2 + 602)
check("an upper-case transcript id in sala's store still matches the session", rd(V / "b/sessions.json")[U(9)]["url"] == Q, rd(V / "b/sessions.json")[U(9)])
st_ = cl.load(); st_["sessions"][U(9).upper()] = dict(st_["sessions"][U(9)], name="work-q-upper"); v_ = cl._view(st_, T1 + 2 + 602)
check("…and so does an upper-case id in the server's own record", v_["b"][1][U(9).upper()]["url"] == Q, v_["b"][1].get(U(9).upper()))
sala("b", {**SB, U(9): ("work-q", Q)}); cl.tick(now=T1 + 2 + 602)
logging.disable(logging.WARNING); cl.log.handlers = _hs
# ---- identity apart from presence: a gone session's items still name it; the horizon prunes what nothing names
from stackshot.web import render; from stackshot.anchors import anchors; from stackshot.fleet import inbox
from stackshot.web.ui import render as ui_render
(T / "store/a/2.json").write_text(json.dumps({"id": "2", "subject": "[home] item 2", "description": "x", "status": "open", "metadata": {"owner": U(1), "mover": U(1), "project": "projects/alpha"}}))
b = render.Board(str(T / "store")); r2 = next(x for x in b.rows if x["gid"] == "a2")
check("the board draws an item's owner from a gone session's identity: machine/name and link (gone for hours, past the grace)", b.lab(r2) == "b/work-y2" and b.url(r2) == LINK, (b.lab(r2), b.url(r2)))
check("a name only a retired session carries binds nothing new (anchors.canonical passes it through), its id still names it", anchors.canonical("work-w") == "work-w" and anchors.names().get(U(7)) == "work-w", anchors.names().get(U(7)))
T3 = T1 + 2 + 603 + 31 * 86400
cl.tick(now=T3); ss = cl.load()["sessions"]
check("past the horizon a gone session no open item names is forgotten (work-w, home-roaming, work-z); one an open item names is kept (work-y2)",
      U(7) not in ss and U(3) not in ss and U(2) not in ss and U(1) in ss and rd(V / "b/sessions.json")[U(1)]["url"] == LINK, sorted(ss))
cl.register("box-far", {"uuid": U(32), "name": "work-old", "bridge": "session_old"}, now=T3)
cl.checkin("box-far", [{"uuid": U(31), "name": "work-y2", "name_source": "user", "bridge": "session_new"}], {}, now=T3 + 1)   # the retired name reused
NEW = "https://term.test/#s=work-y2"; sala("b", {**SB, U(31): ("work-y2", NEW)}); cl.tick(now=T3 + 1); rows = fl.sessions()
check("a live session reusing a gone session's name wins it: fleet.by_name, the board's name index, anchors.canonical",
      fl.by_name(rows).get("work-y2") == U(31) and render.Board(str(T / "store")).sess["name:work-y2"]["id"] == U(31) and anchors.canonical("work-y2") == U(31), fl.by_name(rows))
check("…the gone session's own items still draw its identity, not the namesake's", render.Board(str(T / "store")).url(r2) == LINK)
iid = inbox.put("work-y2", "to whoever carries the name", "msg"); line = json.load(open(T / "state/inbox/msg" / f"{iid}.json"))
check("…a line addressed by that name records the live session's id", line["uuid"] == U(31), line); inbox.ack([iid])
iid = inbox.put(U(1), "for the retired pane", "hub"); d = inbox.take({U(31): "work-y2"})
check("a line addressed by id to a session gone past the grace follows its name to the live namesake (a retired id strands nothing)", len(d) == 1 and d[0]["session"] == U(31) and d[0]["ids"] == [iid], d); inbox.ack([iid])
from stackshot.web import server
ls = server._sessions_listing("", now=T3 + 2).split("\n"); ly = [l for l in ls if l.startswith("- work-y2 ")]
check("sessions tool: the live namesake plain, the gone owner of an open item kept with its last sign of life",
      len(ly) == 2 and any(l == f"- work-y2 — {NEW} · box-far" for l in ly) and any(re.fullmatch(rf"- work-y2 — {re.escape(LINK)} · box-far · not running \(last seen \d\d-\d\d \d\d:\d\d \+04; kept as the mover of open items\)", l) for l in ly), ly)
check("sessions tool: a session gone for less than the grace is listed as not running now", any(l.startswith("- work-old ") and l.endswith("not running now (relaunching, or retired; shown as last known)") for l in ls), [l for l in ls if "work-old" in l])
ls2 = server._sessions_listing("", now=T3 + 1 + 601).split("\n")
check("sessions tool: past the grace a gone session nobody's item names is left out, the kept owner stays", not any("work-old" in l for l in ls2) and sum("work-y2" in l for l in ls2) == 2 and U(32) in rd(V / "b/sessions.json"), ls2)
# ---- a pane's term link from sala, end to end with its bridge down: the sessions tool, a board row, the item page, a mention;
# a cloud session (cse_…) keeps its claude.ai link from cloud.py
TERM = "https://term.test/#s=work-term"
sala("b", {**SB, U(31): ("work-y2", NEW), U(40): ("work-term", TERM)})
cl.checkin("box-far", [{"uuid": U(40), "name": "work-term", "name_source": "user", "bridge": ""}], {}, partial=True, now=T3 + 2)
(T / "store/a/3.json").write_text(json.dumps({"id": "3", "subject": "[home] item 3", "description": "Ask work-term about it. It lives here. Done when done.", "status": "open", "metadata": {"owner": U(40), "mover": U(40), "project": "projects/alpha"}}))
(T / "store/a/4.json").write_text(json.dumps({"id": "4", "subject": "[home] item 4", "description": "A cloud thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": "cse_01XYZ", "mover": "cse_01XYZ", "project": "projects/alpha"}}))
ls3 = server._sessions_listing("work-term", now=T3 + 3).split("\n")
check("term link: the sessions tool gives sala's url unchanged, with the bridge down", f"- work-term — {TERM} · box-far" in ls3, ls3)
bt = render.Board(str(T / "store")); r3 = next(x for x in bt.rows if x["gid"] == "a3"); r4 = next(x for x in bt.rows if x["gid"] == "a4")
check("term link: board.md's owner link is sala's url", bt.url(r3) == TERM and bt.lab(r3) == "b/work-term", (bt.lab(r3), bt.url(r3)))
# the web pages link a session name to its view in the fleet tool's web UI instead, while it has a live pane: [client] session_view and [fleet] tool_name as an instance sets them
cfg.CFG["client"]["session_view"] = "https://sala.example.org/#s={name}"; cfg.CFG.setdefault("fleet", {})["tool_name"] = "sala"
SV = '<a href="https://sala.example.org/#s=work-term" target="_blank" rel="noopener" title="open this session in sala">work-term'
bt = ui_render.Board(str(T / "store"))      # the item page is drawn by the ui renderer
ip3 = bt.item_html("a3")
check("sala link: the item page's owner, live from its checkin, links to its view in sala", f'{SV} ↗</a>' in ip3 and TERM not in ip3, ip3[ip3.find("iside"):][:600])
check("sala link: an inline mention of the session links to it too", f'Ask {SV}</a> about it' in ip3, ip3[ip3.find('class="desc"'):][:400])
check("a cloud session keeps its claude.ai link in board.md (cloud.py)", bt.url(r4) == "https://claude.ai/code/session_01XYZ", bt.url(r4))
ip4 = bt.item_html("a4"); _own4 = ip4[ip4.find("<dt>Mover</dt>"):ip4.find("</dd>", ip4.find("<dt>Mover</dt>"))]
check("…and on the pages it has no pane, so its name is plain text", "<a " not in _own4 and "claude.ai" not in _own4, _own4)
cfg.CFG["client"]["session_view"] = ""; cfg.CFG["fleet"]["tool_name"] = ""
(T / "store/a/3.json").unlink(); (T / "store/a/4.json").unlink()
cfg.CFG["fleet"]["operator_session"] = "sala-master"
cl.register(ME, {"uuid": U(4), "name": "sala-master", "bridge": "session_op"}, now=T0 + 200)
m = rd(V / "a/machine.json")
check("the operator session is the one config names ([fleet] operator_session), the view the server's own clients alone", m["master"] == "sala-master" and m["master_session"] == U(4)
      and m["source"] == "client" and "fleet_ssh" not in m and set(m) == {"letter", "fleet", "claude", "master", "master_session", "checked", "source"}, m)
cfg.CFG["fleet"].pop("operator_session")

# ================================================================= 2. what makes a machine online (versions.py)
from stackshot.fleet import versions as ver
cl.checkin("box-far", [{"uuid": U(5), "name": "work-new"}], {"claude": "2.2.0"})          # online now, by the real clock
_, st = ver.machines_state()
check("the publisher box is live, a box whose puller checked in is live", st.get("a") == "live" and st.get("b") == "live", st)
d = rd(V / "b/machine.json"); d["online"] = {"ok": False, "since": "2026-10-02T03:00:00Z"}; (V / "b/machine.json").write_text(json.dumps(d))
_, st = ver.machines_state(); check("a box whose puller stopped is offline since its last check-in, in the instance timezone", st["b"] == "offline since 10-02 07:00 +04", st)
d.pop("online"); d["checked"] = "2026-10-02T05:00:00Z"; (V / "b/machine.json").write_text(json.dumps(d))
_, st = ver.machines_state(); check("a box with no puller on record is offline since it was last seen (no ssh probe any more)", st["b"] == "offline since 10-02 09:00 +04", st)
cl.tick()

# ================================================================= 3. the inbox (inbox.py)
from stackshot.fleet import inbox
cl.checkin("box-far", [{"uuid": U(5), "name": "work-new"}], {})
i1 = inbox.put("work-new", "first line", "msg")
it = rd(T / f"state/inbox/msg/{i1}.json")
check("a line put by name remembers the session it meant", it["to"] == "work-new" and it["uuid"] == U(5) and it["name"] == "work-new", it)
d = inbox.take({U(5): "work-new"})
check("a puller is handed the line for its live session", len(d) == 1 and d[0]["session"] == U(5) and d[0]["text"] == "first line" and d[0]["ids"] == [i1] and d[0]["src"] == "msg", d)
check("a handed-out line is leased: not offered twice", inbox.take({U(5): "work-new"}) == [] and inbox.exists(i1))
check("…offered again when the lease runs out unconfirmed", len(inbox.take({U(5): "work-new"}, now=time.time() + inbox.LEASE + 1)) == 1)
check("a confirmed line is gone", inbox.ack([i1]) == 1 and not inbox.exists(i1) and inbox.waiting() == {})
i2, i3, i4 = inbox.put(U(5), "anchor one", "hub"), inbox.put(U(5), "anchor two", "hub"), inbox.put("work-new", "a message", "msg")
d = {x["src"]: x for x in inbox.take({U(5): "work-new"})}
check("several waiting lines of one kind arrive as one turn, kinds apart", d["hub"]["text"] == "[anchor] 2 queued while you were away:\nanchor one\nanchor two" and d["hub"]["ids"] == [i2, i3] and d["msg"]["text"] == "a message", d)
inbox.ack([i4], failed=[i2, i3])
check("a failed delivery is offered again shortly, not at once", inbox.take({U(5): "work-new"}) == [] and len(inbox.take({U(5): "work-new"}, now=time.time() + inbox.RETRY + 1)) == 1)
inbox.ack([i2, i3])
check("nothing is handed to a machine that does not host the session", inbox.put("work-new", "x", "msg") and inbox.take({U(7): "someone-else"}) == [])
inbox.ack([k for k in os.listdir(T / "state/inbox/msg") if k.endswith(".json") and not k.startswith(".")] and [f[:-5] for f in os.listdir(T / "state/inbox/msg") if f.endswith(".json")])
# a pane retired and spawned again under the same name
i5 = inbox.put(U(5), "for the old pane", "hub")
check("a line by id is not handed to a namesake while its own session still exists somewhere", inbox.take({U(6): "work-new"}, known={U(5), U(6)}) == [])
d = inbox.take({U(6): "work-new"}, known={U(6)})
check("…and follows the name once that session is gone everywhere (no line strands under a retired id)", len(d) == 1 and d[0]["session"] == U(6) and d[0]["ids"] == [i5], d)
inbox.ack([i5])
# pause, release, hold
F = T / "state/anchor-hub"
i6 = inbox.put("work-new", "held back", "hub"); (F / "paused-hub.json").write_text("{}")
check("a paused source hands nothing out", inbox.take({U(5): "work-new"}) == [] and inbox.waiting("hub") == {"work-new": 1})
i7 = inbox.put("work-new", "a message meanwhile", "msg")
check("…the other source is not paused by it", [x["ids"] for x in inbox.take({U(5): "work-new"})] == [[i7]]); inbox.ack([i7])
(F / "release-hub.txt").write_text("work-new\n")
check("a key a resume released is served although the source is still paused", [x["ids"] for x in inbox.take({U(5): "work-new"})] == [[i6]]); inbox.ack([], failed=[i6])
(F / "release-hub.txt").unlink(); (F / "paused-hub.json").unlink(); (F / "held-hub.txt").write_text(U(5) + "\n")
check("a held key keeps its lines after the pause is lifted", inbox.take({U(5): "work-new"}, now=time.time() + 60) == [])
(F / "held-hub.txt").write_text(""); inbox.ack([i6])

# ================================================================= 4. push.py and the reboot queue in inbox mode
env = {**os.environ, "PUSH_INBOX_WAIT": "0.4"}
r = subprocess.run([sys.executable, f"{STACK}/stackshot/fleet/push.py", "work-new", "pushed line"], capture_output=True, text=True, env={**env, "ANCHOR_PUSH_SOURCE": "msg"})
check("push.py in inbox mode: the line waits in the inbox, the answer says so", r.returncode == 1 and r.stdout.strip() == "inbox → work-new" and inbox.waiting("msg") == {"work-new": 1}, (r.returncode, r.stdout, r.stderr[-300:]))
def confirm_soon(delay=0.3, live=None, within=10):
    # polls like a puller until it has confirmed a line: one take after a fixed sleep raced the push.py child's
    # start-up, which under coverage and strace (main's measured run) outlasts the sleep (CI run 9000002)
    def run():
        time.sleep(delay); end = time.time() + within
        while time.time() < end:
            d = inbox.take(live or {U(5): "work-new"})
            if d: inbox.ack([i for x in d for i in x["ids"]]); return
            time.sleep(0.05)
    th = threading.Thread(target=run); th.start(); return th
th = confirm_soon(0.1); th.join()
th = confirm_soon(0.4)
r = subprocess.run([sys.executable, f"{STACK}/stackshot/fleet/push.py", "work-new", "confirmed line"], capture_output=True, text=True, env={**env, "PUSH_INBOX_WAIT": "5"}); th.join()
check("…and when the machine confirms within seconds, the answer is still 'delivered'", r.returncode == 0 and r.stdout.strip() == "delivered → work-new" and inbox.waiting() == {}, (r.returncode, r.stdout))
from stackshot.fleet import push
d = rd(V / "b/machine.json")
check("a pane on a machine whose puller checks in is served from the inbox, by name or by id", push.inbox_serves("work-new") and push.inbox_serves(U(5)))
d2 = dict(d); d2["online"] = {"ok": False, "since": "2026-10-02T03:00:00Z"}; (V / "b/machine.json").write_text(json.dumps(d2))
cl.register(ME, {"uuid": U(40), "name": "local-pane"})          # a pane on the server box itself, whose puller is not checking in
check("…a pane on another machine whose puller stopped still waits in the inbox (the ssh path is gone); a pane on this box with no puller checking in, or one nobody lists, takes the local path",
      push.inbox_serves("work-new") and not push.inbox_serves("local-pane") and not push.inbox_serves(U(40)) and not push.inbox_serves("ghost-pane"), rd(V / "a/machine.json"))
(V / "b/machine.json").write_text(json.dumps(d))
(F / "paused-msg.json").write_text("{}")
r = subprocess.run([sys.executable, f"{STACK}/stackshot/fleet/push.py", U(5), "during a pause"], capture_output=True, text=True, env={**env, "ANCHOR_PUSH_SOURCE": "msg"})
r2 = subprocess.run([sys.executable, f"{STACK}/stackshot/fleet/push.py", "ghost-pane", "for nobody listed"], capture_output=True, text=True, env={**env, "ANCHOR_PUSH_SOURCE": "msg"})
check("push.py while paused: queued, with the pause named", r.returncode == 1 and r.stdout.startswith("queued (paused for a reboot)") and r2.stdout.startswith("queued (paused"), r.stdout)
RQ = f"{STACK}/reboot-hooks/reboot-queue.py"
r = subprocess.run([sys.executable, RQ, "count", "--source", "msg"], capture_output=True, text=True, env=env)
check("reboot queue count: what waits in the inbox counts as queued", json.loads(r.stdout) == {"items": 2, "sessions": 2}, r.stdout + r.stderr[-200:])
(T / "listed.txt").write_text(U(5) + "\n")
th = confirm_soon(1.0)
r = subprocess.run([sys.executable, RQ, "resume", "--source", "msg", "--sessions", str(T / "listed.txt"), "--wait", "8"], capture_output=True, text=True, env=env); th.join()
q = json.loads(r.stdout or "{}")
check("reboot queue resume: the verified session's line is released and confirmed, the other key is held", r.returncode == 0 and (q.get("delivered"), q.get("held"), q.get("held_sessions"), q.get("waiting")) == (1, 1, ["ghost-pane"], 0), r.stdout + r.stderr[-300:])
check("…the release list is gone and the hold is on file for after the pause", not (F / "release-msg.txt").exists() and (F / "held-msg.txt").read_text() == "ghost-pane\n")
(F / "paused-msg.json").unlink(); (F / "held-msg.txt").write_text(""); inbox.ack([f[:-5] for f in os.listdir(T / "state/inbox/msg") if f.endswith(".json")])

# ---- the item: every drop names its sender on a short first line
check("label: a `from:` line on top; no sender (a line stored before senders were kept), the text as it was",
      inbox.label("release-job.py", "[stackshot] x") == "from: release-job.py\n[stackshot] x" and inbox.label("", "y") == "y")
_FBL = T / "state/anchor-hub/push-fallback.jsonl"; _fb0 = len(_FBL.read_text().splitlines()) if _FBL.exists() else 0
r = subprocess.run([sys.executable, f"{STACK}/stackshot/fleet/push.py", "--from", "ops-x", "work-new", "a named line"], capture_output=True, text=True, env={**env, "ANCHOR_PUSH_SOURCE": "msg"})
r2 = subprocess.run([sys.executable, f"{STACK}/stackshot/fleet/push.py", "work-new", "an env-named line"], capture_output=True, text=True, env={**env, "ANCHOR_PUSH_SOURCE": "msg", "PUSH_FROM": "ops-env"})
r3 = subprocess.run([sys.executable, f"{STACK}/stackshot/fleet/push.py", "work-new", "an unnamed line"], capture_output=True, text=True, env={**env, "ANCHOR_PUSH_SOURCE": "msg"})
d = inbox.take({U(5): "work-new"}); txt = d[0]["text"] if d else ""; inbox.ack([i for x in d for i in x["ids"]])
check("push.py --from, $PUSH_FROM and the fallback: each queued item keeps its own sender in the batch",
      r.returncode == r2.returncode == r3.returncode == 1 and txt.startswith("[stackshot] 3 queued while you were away:\n")
      and "\nfrom: ops-x\na named line" in txt and "\nfrom: ops-env\nan env-named line" in txt
      and "\nfrom: contract_scenario.py\nan unnamed line" in txt, (txt, r3.stderr[-300:]))
_fb = [json.loads(ln) for ln in _FBL.read_text().splitlines()[_fb0:]] if _FBL.exists() else []
check("the fallback is recorded (to, source, the caller found); a named drop is not", [(e["to"], e["src"], e["caller"]) for e in _fb] == [("work-new", "msg", "contract_scenario.py")], _fb)
subprocess.run([sys.executable, f"{STACK}/stackshot/fleet/push.py", "--from", "ops-x", "work-new", "[anchor] Slack: one line"], capture_output=True, text=True, env=env)
d = inbox.take({U(5): "work-new"}); inbox.ack([i for x in d for i in x["ids"]])
check("a single line opens with its sender, the tag within the first line after it", d and d[0]["text"] == "from: ops-x\n[anchor] Slack: one line", d)
check("caller(): the script's name past the interpreter (python3 /…/release-job.py → release-job.py)",
      push.caller(os.getpid()) == "contract_scenario.py" and push.caller(999999999) == "an unnamed script", push.caller(os.getpid()))
q = T / "state/anchor-hub/queue-msg"; q.mkdir(parents=True, exist_ok=True)
(q / "ghost-q.jsonl").write_text(json.dumps({"t": 1, "text": "old line", }) + "\n" + json.dumps({"t": 2, "text": "new line", "from": "ops-y"}) + "\n")
sent = []; _send, _resolve = push.send, push.resolve
push.send = lambda sock, text: sent.append(text) or True; push.resolve = lambda name: "/tmp/sock"
_src, _q = push.SRC, push.Q; push.SRC, push.Q = "msg", str(q)
check("the local queue's flush: each item with its sender (a line stored before senders were kept, as it was)",
      push.flush("ghost-q") == 0 and sent == ["[stackshot] 2 queued while you were away:\nold line\nfrom: ops-y\nnew line"], sent)
sent.clear()
check("a socket drop opens with the sender", push.deliver("local-pane", "hello", "ops-z") == 0 and sent == ["from: ops-z\nhello"], sent)
from stackshot.core import config as _cfgm
_cfgm.CFG.setdefault("anchor_hub", {})["require_sender"] = True
check("[anchor_hub] require_sender: a drop without a sender is refused (exit 2), with one it goes",
      push.deliver("local-pane", "no name", "") == 2 and push.deliver("local-pane", "named", "ops-z") == 0)
_cfgm.CFG["anchor_hub"]["require_sender"] = False
push.send, push.resolve, push.SRC, push.Q = _send, _resolve, _src, _q

# ================================================================= 5. the client API's writes, over HTTP
from stackshot.fleet import client; from stackshot.web import server
server._publish = lambda: None
tok_b = open(client.mint("box-far")).read().strip(); tok_me = open(client.mint(ME)).read().strip()
from starlette.testclient import TestClient
app = server.mcp.http_app()
HB = {"Authorization": "Bearer " + tok_b}
with TestClient(app) as c:
    r = c.post("/client/register", json={"uuid": U(10), "name": "x"}); check("http: a write without a token → 401", r.status_code == 401, r.status_code)
    r = c.post("/client/register", json={"uuid": U(10), "name": "work-http", "bridge": "session_h", "machine": "a"}, headers=HB)
    check("http: register → the session is the token's machine's, whatever the body claims", r.status_code == 200 and r.json() == {"ok": True, "name": "work-http", "machine": "b"} and U(10) in rd(V / "b/sessions.json"), r.text)
    r = c.post("/client/register", json={"name": "no id"}, headers=HB); check("http: a registration without an id → 400", r.status_code == 400, r.text)
    r = c.post("/client/seen", json={"uuid": U(10)}, headers=HB); r2 = c.post("/client/seen", json={"uuid": U(77)}, headers=HB)
    check("http: seen for a known session, and for an unknown one", r.json() == {"ok": True} and r2.json() == {"ok": False}, (r.text, r2.text))
    r = c.post("/client/nothing", json={}, headers=HB); check("http: an unknown write → 404", r.status_code == 404, r.status_code)
    r = c.post("/client/poll", content=b"[1]", headers=HB); check("http: a body that is not an object → 400", r.status_code == 400, r.status_code)
    inbox.put("work-http", "over http", "msg")
    r = c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http", "bridge": "session_h"}], "facts": {"claude": "2.3.0"}, "wait": 0}, headers=HB)
    d = r.json()["deliveries"]
    rows = rd(V / "b/sessions.json")
    check("http: poll hands out what waits and marks the machine's check-in (its list is the machine's live sessions; the rest are held, marked gone)",
          r.status_code == 200 and len(d) == 1 and d[0]["text"] == "over http" and rd(V / "b/machine.json")["claude"] == "2.3.0"
          and {u for u, v in rows.items() if "gone" not in v} == {U(10)} and all("gone" in v for u, v in rows.items() if u != U(10)), (r.text, rows))
    r = c.post("/client/ack", json={"delivered": d[0]["ids"], "failed": []}, headers=HB); check("http: ack removes it", r.json() == {"removed": 1} and inbox.waiting() == {}, r.text)
    threading.Thread(target=lambda: (time.sleep(1.2), inbox.put(U(10), "arrived during the poll", "hub"))).start()
    t0 = time.time(); r = c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "wait": 15}, headers=HB); took = time.time() - t0
    d = r.json()["deliveries"]
    check("http: a long poll is held open and answers as soon as a line arrives", 1.0 < took < 6 and len(d) == 1 and d[0]["text"] == "arrived during the poll", (took, r.text))
    c.post("/client/ack", json={"delivered": d[0]["ids"]}, headers=HB)
    t0 = time.time(); r = c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "wait": 2}, headers=HB)
    check("http: …and comes back empty when nothing arrives", 1.8 < time.time() - t0 < 5 and r.json()["deliveries"] == [], r.text)
    HM = {"Authorization": "Bearer " + tok_me}
    inbox.put(U(10), "for the session on box-far only", "msg")
    r = c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "wait": 0}, headers=HM)
    check("http: another machine cannot claim a session that is live elsewhere: it is handed nothing, the session stays where it is",
          r.status_code == 200 and r.json()["deliveries"] == [] and cl.load()["sessions"][U(10)]["machine"] == "b" and inbox.waiting("msg") == {U(10): 1}, r.text)
    r = c.post("/client/register", json={"uuid": U(10), "name": "stolen"}, headers=HM); check("http: …nor register it", r.status_code == 400 and cl.load()["sessions"][U(10)]["name"] == "work-http", r.text)
    r = c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "wait": 0}, headers=HB); c.post("/client/ack", json={"delivered": [i for x in r.json()["deliveries"] for i in x["ids"]]}, headers=HB)
    inbox.put("work-drain", "for a session with no puller", "msg")
    r = c.post("/client/drain", json={"uuid": U(11), "name": "work-drain"}, headers=HB)
    check("http: drain (no puller): the session's own hook is handed its lines, and it is registered by it", r.status_code == 200 and r.json()["deliveries"][0]["text"] == "for a session with no puller" and U(11) in cl.load()["sessions"], r.text)
    c.post("/client/ack", json={"delivered": r.json()["deliveries"][0]["ids"]}, headers=HB)

    # ============================================================= 6. the puller, end to end, against a fake CLI inbox
    import urllib.request, urllib.error; from stackshot.fleet import puller
    class _Resp:
        def __init__(s, r): s.status = r.status_code; s._b = r.content
        def read(s): return s._b
        def __enter__(s): return s
        def __exit__(s, *a): return False
    def fake_urlopen(req, timeout=0):
        path = req.full_url.replace(client.server_url(), "")
        r = c.post(path, content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(path, headers=dict(req.header_items()))
        if r.status_code >= 400: raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
        return _Resp(r)
    client.urllib.request.urlopen = fake_urlopen
    got = []; sock_path = str(T / "cli.sock")
    if len(sock_path.encode()) > 100:                  # a unix socket path holds 107 bytes: a deep $TMPDIR (a CI runner's temp folder) puts the socket in a short folder under the system temp root, removed and locked like the rest
        sock_path = os.path.join(_scratch.mkdtemp(prefix="cs-", short=True), "cli.sock")
    srv = socket.socket(socket.AF_UNIX); srv.bind(sock_path); srv.listen(5)
    def listen():
        while True:
            try: conn, _ = srv.accept()
            except OSError: return
            buf = b""
            while True:
                b = conn.recv(65536)
                if not b: break
                buf += b
            conn.close(); got.extend(json.loads(l) for l in buf.decode().splitlines() if l.strip())
    threading.Thread(target=listen, daemon=True).start()
    REG = str(T / "reg")
    (T / "reg/1.json").write_text(json.dumps({"pid": os.getpid(), "sessionId": U(20), "name": "home-local", "version": "2.9.9", "status": "idle", "bridgeSessionId": "session_local",
                                              "messagingSocketPath": sock_path, "updatedAt": 5}))
    (T / "reg/2.json").write_text(json.dumps({"pid": 999999, "sessionId": U(21), "name": "home-dead", "messagingSocketPath": sock_path, "updatedAt": 5}))
    puller._VER.update(at=time.time(), v="2.9.9", sig=puller._cli_sig())
    check("the puller reports only sessions whose process runs", [x["name"] for x in puller.report(puller.sessions(REG))] == ["home-local"], puller.report(puller.sessions(REG)))
    inbox.put("home-local", "hello from the server", "msg"); inbox.put("home-local", "an anchor notice", "hub")
    rc = puller.once(REG, None, 0); time.sleep(0.3)
    check("puller: fetched, written to the session's inbox socket as user turns, confirmed", rc == 0 and sorted(x["message"]["content"] for x in got) == ["an anchor notice", "hello from the server"]
          and all(x["type"] == "user" and x["message"]["role"] == "user" for x in got) and inbox.waiting() == {}, (rc, got, inbox.waiting()))
    row = rd(V / "a/sessions.json").get(U(20)) or {}; m = rd(V / "a/machine.json")
    check("puller: its poll registered the session (name; no link built from its bridge, sala has no row for it) and made the machine online with its CLI version", row.get("name") == "home-local" and row.get("url") == ""
          and m["online"]["ok"] is True and m["claude"] == "2.9.9", (row, m))
    os.remove(sock_path); srv.close(); inbox.put("home-local", "cannot be delivered", "msg")
    rc = puller.once(REG, None, 0)
    check("puller: a line it could not deliver is reported failed and stays in the inbox", rc == 1 and inbox.waiting("msg") == {"home-local": 1}, (rc, inbox.waiting()))
    check("puller --only: nothing else is served, and the server is told the list is partial", puller.sessions(REG, ["someone"]) == [] and puller.once(REG, ["someone"], 0) == 0 and U(20) in rd(V / "a/sessions.json"))
    inbox.ack([f[:-5] for f in os.listdir(T / "state/inbox/msg") if f.endswith(".json")])
    client.urllib.request.urlopen = lambda req, timeout=0: (_ for _ in ()).throw(OSError("connection refused"))
    check("puller: an unreachable server is exit 2, nothing lost", puller.once(REG, None, 0) == 2)
    client.urllib.request.urlopen = fake_urlopen

    # ============================================================= 7. the hooks' verbs (client.py register · seen · drain)
    os.environ["STACKSHOT_CLI_REGISTRY"] = REG
    (T / "reg/3.json").write_text(json.dumps({"pid": os.getpid(), "sessionId": U(30), "name": "home-hooked", "version": "2.9.9", "status": "busy", "bridgeSessionId": "session_hook", "messagingSocketPath": "x", "updatedAt": 9}))
    def run_hook(verb, payload):
        old_in, old_out = sys.stdin, sys.stdout; sys.stdin = io.StringIO(json.dumps(payload)); sys.stdout = buf = io.StringIO()
        try: rc = client.main(["client.py", verb])
        finally: sys.stdin, sys.stdout = old_in, old_out
        return rc, buf.getvalue()
    rc, out = run_hook("register", {"session_id": U(30), "hook_event_name": "SessionStart"})
    row = cl.load()["sessions"].get(U(30)) or {}
    check("hook register: the session is on record with what the CLI's registry says of it, silently", rc == 0 and out == "" and row.get("name") == "home-hooked" and "url" not in row and row.get("via") == "hook", (rc, out, row))
    before = row.get("seen"); time.sleep(1.1); rc, out = run_hook("seen", {"session_id": U(30)})
    check("hook seen: a sign of life", rc == 0 and cl.load()["sessions"][U(30)]["seen"] > before)
    inbox.put("home-hooked", "waiting for the next prompt", "msg")
    rc, out = run_hook("drain", {"session_id": U(30)})
    check("hook drain: what waits is printed for the session and confirmed", rc == 0 and out.strip() == "waiting for the next prompt" and inbox.waiting() == {}, (rc, out, inbox.waiting()))
    rc, out = run_hook("drain", {"session_id": U(30)}); check("hook drain: silent when nothing waits", rc == 0 and out == "")
    client.urllib.request.urlopen = lambda req, timeout=0: (_ for _ in ()).throw(OSError("connection refused"))
    rc, out = run_hook("register", {"session_id": U(30)}); rc2, out2 = run_hook("drain", {"session_id": U(30)}); rc3, _ = run_hook("seen", {})
    check("the hook verbs never fail a hook: server away, or no session id → exit 0 and silence", (rc, out, rc2, out2, rc3) == (0, "", 0, "", 0), (rc, out, rc2, out2, rc3))
    client.urllib.request.urlopen = fake_urlopen

    # ============================================================= 7a. a setup run's result and update attempts on the Machines panel
    # (the Windows PCs run provisioning themselves, and a failed setup step must show on the PC's card)
    MNAME = {"a": "testbox", "b": "box-far"}
    def mcol(L):                     # machine L's column of the Machines panel (its card with the name inside, and its alert cards), as rendered
        h = ui_render.Board(str(T / "store")).html()
        sec = h[h.find('<section id="machines">'):]; sec = sec[:sec.find("</section>")]
        cols = sec.split('<div class="mcol">')[1:]
        return next((c for c in cols if f'<b class="lbl mh">{MNAME[L]}</b>' in c), "")
    check("setup: a machine that never reported shows no alert and no setup note", 'class="mf"' not in mcol("b") and "set up" not in mcol("b"), mcol("b"))
    r = c.post("/client/setup-result", json={"ok": False, "step": "x"}); check("setup: without a token → 401", r.status_code == 401, r.status_code)
    r = c.post("/client/setup-result", json={"ok": "no", "step": "x"}, headers=HB); check("setup: ok must be a boolean → 400", r.status_code == 400 and "ok" in r.json()["error"], r.text)
    r = c.post("/client/setup-result", json={"ok": False, "reason": "it broke"}, headers=HB); check("setup: a failed run with no step → 400, nothing recorded", r.status_code == 400 and "step" in r.json()["error"] and "setup" not in rd(V / "b/machine.json"), r.text)
    r = c.post("/client/setup-result", json={"ok": False, "step": "Install  Claude\nCode", "reason": "winget exited 0x8A15000F <no package>", "machine": "a"}, headers=HB)
    sb = rd(V / "b/machine.json").get("setup") or {}
    check("setup: a failed run is kept for the token's machine (not the body's), whitespace collapsed, stamped by the server",
          r.status_code == 200 and r.json()["machine"] == "box-far" and sb.get("ok") is False and sb.get("step") == "Install Claude Code"
          and sb.get("reason") == "winget exited 0x8A15000F <no package>" and sb.get("at", "").endswith("Z") and "setup" not in rd(V / "a/machine.json"), (r.text, sb))
    col = mcol("b")
    check("setup: the failed run shows on the machine's column — the state word and the step inline, the reason in the tooltip (escaped)",
          '<div class="pc mach bad">' in col and '<span class="lbl bad">setup failed ✗</span> <span class="val">step Install Claude Code</span>' in col
          and "setup failed at step Install Claude Code just now" in col and "winget exited 0x8A15000F &lt;no package&gt;" in col and "<no package>" not in col, col)
    check("setup: …only on that machine's column", 'class="mf"' not in mcol("a"), mcol("a"))
    r = c.post("/client/setup-result", json={"ok": True, "step": "ignored", "reason": ""}, headers=HB)
    sb = rd(V / "b/machine.json").get("setup") or {}; col = mcol("b")
    check("setup: an ok run replaces the failure, keeps no step", r.status_code == 200 and sb.get("ok") is True and sb.get("step") == "", sb)
    check("setup: …and the card is quiet: no alert, no 'set up' note, no hover text on the heading", 'class="mf"' not in col and "failed" not in col
          and "set up" not in col and re.search(r'<b class="lbl mh">box-far</b>', col) is not None, col)
    # client.py setup-result: the provisioning script's contract (this box's token, machine a)
    def run_setup(*args):
        old = sys.stdout; sys.stdout = buf = io.StringIO()
        try: rc = client.main(["client.py", "setup-result", *args])
        finally: sys.stdout = old
        return rc, buf.getvalue()
    for bad in ((), ("--ok", "--failed"), ("--failed",), ("--failed", "--step", " "), ("--failed", "--step"), ("--ok", "extra")):
        rc, out = run_setup(*bad); check(f"client.py setup-result {' '.join(bad) or '(no flag)'}: usage, exit 1, nothing sent", rc == 1 and "usage" in out and "setup" not in rd(V / "a/machine.json"), (rc, out))
    rc, out = run_setup("--failed", "--step", "Enable OpenSSH", "--reason", "Add-WindowsCapability: access denied")
    sa = rd(V / "a/machine.json").get("setup") or {}
    check("client.py setup-result --failed: recorded for this machine, one line, exit 0", rc == 0 and out.strip() == f"stackshot: setup result recorded for {ME}: failed at Enable OpenSSH"
          and sa.get("ok") is False and sa.get("step") == "Enable OpenSSH" and sa.get("reason") == "Add-WindowsCapability: access denied", (rc, out, sa))
    check("client.py setup-result: the failure is on this machine's column", "Enable OpenSSH" in mcol("a") and "failed ✗" in mcol("a"), mcol("a"))
    rc, out = run_setup("--ok"); check("client.py setup-result --ok: recorded, exit 0, the column quiet again", rc == 0 and out.strip().endswith(": ok") and 'class="mf"' not in mcol("a"), (rc, out))
    client.urllib.request.urlopen = lambda req, timeout=0: (_ for _ in ()).throw(OSError("connection refused"))
    rc, out = run_setup("--ok"); check("client.py setup-result: the server away → exit 1 and says so", rc == 1 and "not recorded [0]" in out, (rc, out))
    client.urllib.request.urlopen = fake_urlopen
    # update attempts in the poll's facts (optional; the helper's PR sends them)
    UPD = [{"what": "stackshot puller", "from": "5", "to": "6", "ok": False, "at": "2026-10-15T00:00:00Z", "reason": "git pull: could not resolve host"},
           {"what": "claude code", "from": "2.1.1", "to": "2.1.2", "ok": False, "at": 1790780400}, {"what": "claude code", "from": "2.1.1", "to": "2.1.2", "ok": True, "at": 1790780460},
           {"what": "no verdict", "to": "1"}, "junk", {"ok": False}]
    r = c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "facts": {"updates": UPD}, "wait": 0}, headers=HB)
    ub = rd(V / "b/machine.json").get("updates") or []; col = mcol("b")
    check("updates: the poll's list is kept, cleaned (entries without a what dropped, ok only when a boolean)", r.status_code == 200 and [u["what"] for u in ub] == ["stackshot puller", "claude code", "claude code", "no verdict"]
          and ub[3]["ok"] is None and ub[1]["at"] == 1790780400, ub)
    check("updates: the latest failed attempt per package shows on the machine's column, the reason and time in the tooltip; a retried-ok one and one with no verdict do not",
          col.count('class="mf"') == 1 and '<span class="lbl bad">update failed ✗</span> <span class="val">stackshot puller 6</span>' in col
          and "stackshot puller update 5 → 6 failed" in col and "(10-15 04:00 +04): git pull: could not resolve host" in col and "claude code 2.1.2" not in col and "no verdict" not in col, col)
    c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "facts": {"claude": "2.3.0"}, "wait": 0}, headers=HB)
    check("updates: a poll without the key leaves the last list", len(rd(V / "b/machine.json").get("updates") or []) == 4)
    c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "facts": {"updates": []}, "wait": 0}, headers=HB)
    check("updates: an empty list clears it, and the column with it", "updates" not in rd(V / "b/machine.json") and 'class="mf"' not in mcol("b"), rd(V / "b/machine.json"))
    # the box's own checkout is judged by where it is (its reported commit against the server's), not by its last attempt: the card clears itself
    SC1, SC2 = "c" * 40, "d" * 40
    CKF = [{"what": "stackshot checkout", "from": SC1[:12], "to": SC2[:12], "ok": False, "at": "2026-11-06T00:00:00Z", "reason": "the server's commit is not on origin"}]
    real_sc = ui_render.server_commit
    try:
        ui_render.server_commit = lambda: SC2
        c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "facts": {"stackshot": SC1, "updates": CKF}, "wait": 0}, headers=HB)
        check("checkout card: the box reports a commit other than the server's and its last attempt failed: red, with the reason in the tooltip",
              rd(V / "b/machine.json").get("stackshot") == SC1 and 'stackshot checkout ' + SC2[:12] in mcol("b") and "failed ✗" in mcol("b") and "is not on origin" in mcol("b"), mcol("b"))
        c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "facts": {"stackshot": SC2}, "wait": 0}, headers=HB)
        check("checkout card: the box reports the server's commit: green by itself, with the failed attempt still on record (no new attempt, no hand step)",
              rd(V / "b/machine.json").get("stackshot") == SC2 and (rd(V / "b/machine.json").get("updates") or [{}])[-1].get("ok") is False and 'class="mf"' not in mcol("b") and "failed" not in mcol("b"), mcol("b"))
        ui_render.server_commit = lambda: SC1
        check("checkout card: the server moves on: the same failed attempt is red again until the box catches up", 'stackshot checkout ' + SC2[:12] in mcol("b") and "failed ✗" in mcol("b"), mcol("b"))
        ui_render.server_commit = lambda: ""
        check("checkout card: the server's commit unknown: the last attempt decides, as before", "failed ✗" in mcol("b"), mcol("b"))
        c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "facts": {"stackshot": SC2, "updates": CKF + [{"what": "stackshot puller", "from": "5", "to": "6", "ok": False, "at": "2026-11-06T00:00:00Z", "reason": "x"}]}, "wait": 0}, headers=HB)
        ui_render.server_commit = lambda: SC2
        check("checkout card: only the checkout is judged by commit: another package's failed attempt stays red", 'class="mf"' in mcol("b") and "stackshot puller 6" in mcol("b") and 'stackshot checkout' not in mcol("b"), mcol("b"))
        # the commit matches but the new code did not load: the puller records "reload failed" with `to` = the commit it is running now, and that stays red
        RLF = [{"what": "stackshot checkout", "from": SC1[:12], "to": SC2[:12], "ok": False, "at": "2026-11-06T00:00:00Z", "reason": "reload failed: the new code did not start"}]
        c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "facts": {"stackshot": SC2, "updates": RLF}, "wait": 0}, headers=HB)
        check("checkout card: a reload failure of the box's current commit stays red although the box is at the server's commit",
              'stackshot checkout ' + SC2[:12] in mcol("b") and "failed ✗" in mcol("b") and "reload failed" in mcol("b"), mcol("b"))
        c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "facts": {"stackshot": SC2, "updates": [dict(RLF[0], to=SC1[:12])]}, "wait": 0}, headers=HB)
        check("checkout card: a reload failure of an older commit than the box's current one clears with the match", 'class="mf"' not in mcol("b") and "failed" not in mcol("b"), mcol("b"))
        c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "facts": {"stackshot": SC2, "updates": [dict(RLF[0], reason="the server's commit is not on origin")]}, "wait": 0}, headers=HB)
        check("checkout card: a reload-less failure at the same commit (it names the commit as its target) clears with the match", 'class="mf"' not in mcol("b"), mcol("b"))
    finally:
        ui_render.server_commit = real_sc
    c.post("/client/poll", json={"sessions": [{"uuid": U(10), "name": "work-http"}], "facts": {"updates": []}, "wait": 0}, headers=HB)
    m = rd(V / "b/machine.json"); m["updates"] = "not a list"; m["setup"] = ["nor this"]; (V / "b/machine.json").write_text(json.dumps(m))
    check("updates and setup: a malformed view draws no alert and does not break the board", 'class="mf"' not in mcol("b") and ">box-far</b>" in mcol("b"), mcol("b"))
    cl.tick()

    # ============================================================= 7b. the pane gate reads through the client API
    from stackshot.projects import pages as pg
    real_brain, real_reg = pg.BRAIN, pg.REG
    real_local = pg.LOCAL_ONLY; pg.LOCAL_ONLY = False   # this block plays a client machine; the server process itself never calls its own API (pages.LOCAL_ONLY)
    # client and server share one `pages` module in this process: the server's own answer is pinned to the real brain first
    real_ts = server._page_ts; server._page_ts = lambda key: os.path.getmtime(T / "brain" / (key + ".md")) if (T / "brain" / (key + ".md")).exists() else 0.0
    pg.BRAIN = str(T / "no-brain-here"); pg.REG = str(T / "no-checkout/projects.json")
    reg = pg.load_registry()
    check("pane gate off the server box: the page registry comes from the server, with no checkout on the machine", reg is not None and "projects/alpha" in reg, reg)
    check("pane gate off the server box: a page's freshness comes from the server (no GitHub call)", pg.page_ts("projects/alpha") == int(os.path.getmtime(T / "brain/projects/alpha.md")), pg.page_ts("projects/alpha"))
    check("pane gate off the server box: a key the registry does not hold names no page", pg.exists("projects/alpha") is True and pg.exists("projects/nope") is False)
    # the server away: no checkout and no GitHub to fall back on — the gate says so and does not block
    sid = U(77); st = pg.load_state(sid); st["touches"] = {"projects/alpha": {"ts": int(time.time()), "task": "s1"}}; pg.save_state(sid, st)
    client.urllib.request.urlopen = lambda req, timeout=0: (_ for _ in ()).throw(OSError("connection refused"))
    pg.REG = real_reg; pg.UNREACHABLE.clear()
    check("pane gate, the server away: no registry and no page time (the store's file next to the code is not read), and the server is remembered as unreachable",
          pg.load_registry() is None and pg.page_ts("projects/alpha") is None and pg.exists("projects/alpha") is None and "registry" in pg.UNREACHABLE, pg.UNREACHABLE)
    stale = pg.stale_touches(sid)
    check("…a touched page is then neither stale nor settled: not blocked on, kept for the next prompt", stale == [] and pg.UNKNOWN == ["projects/alpha"]
          and "projects/alpha" in pg.load_state(sid).get("touches", {}), (stale, pg.UNKNOWN))
    real_stdin = sys.stdin; out = io.StringIO(); err = io.StringIO()
    sys.stdin = io.StringIO(json.dumps({"session_id": sid}))
    with contextlib.redirect_stdout(out): rc_nag = pg.cmd_nag()
    sys.stdin = io.StringIO(json.dumps({"session_id": sid}))
    with contextlib.redirect_stderr(err): rc_check = pg.cmd_check()
    sys.stdin = real_stdin; said = out.getvalue()
    check("…the nag says so in one line (server unreachable, the page, the server), and the stop hook does not block (exit 0, nothing on stderr)",
          rc_nag == 0 and said.count("\n") == 1 and said.startswith("[project-page] server unreachable: the page gate could not check projects/alpha from this machine (the server at ")
          and said.rstrip().endswith("did not answer); it checks again at the next prompt and does not block on it.") and rc_check == 0 and err.getvalue() == "", (rc_nag, said, rc_check, err.getvalue()))
    client.urllib.request.urlopen = fake_urlopen; pg.UNREACHABLE.clear()
    stale = pg.stale_touches(sid)
    check("…and settles through the server once it answers again", stale == [] and pg.UNKNOWN == [] and not pg.load_state(sid).get("touches"), (stale, pg.UNKNOWN))

    # every project page is the router's, so a pane owes nothing for a write on it unless [pilot] writer_owes_page is on: the "(no project)"
    # cases below are about a pane that does owe, so the switch is on for them
    _writer_owes = server._cfg.CFG.setdefault("pilot", {}).get("writer_owes_page"); server._cfg.CFG["pilot"]["writer_owes_page"] = True
    # a portal write whose script returns a trimmed reply (no `project:` line): the item's project is asked of the server by the
    # call's item_id (item-facts), so the touch is not stuck under "(no project)"; when the server cannot be asked, the touch falls
    # back to "(no project)" with the item id on it, and a later write of the same item that carries the project settles it
    TRIM = json.dumps({"result": "ok, next set"})
    sid = U(78); pg.save_state(sid, {"touches": {}})
    pg._touch_mcp_record({"session_id": sid, "tool_response": TRIM}, {"item_id": "a1", "next": "x"}, "update")
    t_ = pg.load_state(sid).get("touches", {})
    check("no project: a trimmed portal reply is resolved by the server lookup (item-facts by the call's item_id)",
          list(t_) == ["projects/alpha"] and t_["projects/alpha"]["task"] == "a1", t_)
    st_, _, body_ = server._client_get("item-facts", {"key": sid, "ids": "a1"})
    check("no project: item-facts carries the item's project", st_ == 200 and json.loads(body_)["items"]["a1"]["project"] == "projects/alpha", body_)
    sid = U(79); pg.save_state(sid, {"touches": {}})
    pg._touch_mcp_record({"session_id": sid, "tool_response": TRIM}, {"item_id": "a9", "next": "x"}, "update")
    check("no project: an item the server does not know stays under (no project)", pg.load_state(sid).get("touches", {}).get("(no project)", {}).get("task") == "a9", pg.load_state(sid))
    client.urllib.request.urlopen = lambda req, timeout=0: (_ for _ in ()).throw(OSError("connection refused"))
    pg._touch_mcp_record({"session_id": sid, "tool_response": TRIM}, {"item_id": "a1", "next": "x"}, "update")
    client.urllib.request.urlopen = fake_urlopen; pg.UNREACHABLE.clear()
    t_ = pg.load_state(sid).get("touches", {})
    check("no project: the lookup failing falls back to (no project), the item id on the touch", t_.get("(no project)", {}).get("task") == "a1", t_)
    client.urllib.request.urlopen = lambda req, timeout=0: (_ for _ in ()).throw(OSError("connection refused"))
    check("…and the nag says it while the server cannot be asked", any(k == "(no project)" for k, _ in pg.stale_touches(sid)))
    client.urllib.request.urlopen = fake_urlopen; pg.UNREACHABLE.clear()
    sid2 = U(85); st2 = pg.load_state(sid); st2["touches"]["(no project)"]["ts"] += 3600; pg.save_state(sid2, st2)   # written after the page's last edit
    stale2 = pg.stale_touches(sid2); t2 = pg.load_state(sid2).get("touches", {})
    check("…and the debt moves by itself to the item's project once the server answers that it carries one (a1 does), keeping its ts and task",
          [k for k, _ in stale2] == ["projects/alpha"] and list(t2) == ["projects/alpha"] and t2["projects/alpha"]["task"] == "a1"
          and t2["projects/alpha"]["ts"] == st2["touches"]["(no project)"]["ts"], (stale2, t2))
    pg._touch_mcp_record({"session_id": sid, "tool_response": "updated a1.\na1 [open] [home] item 1\nproject: projects/alpha\n"}, {"item_id": "a1", "next": "y"}, "update")
    t_ = pg.load_state(sid).get("touches", {})
    check("no project: a later direct write of the same item that carries the project settles it", "(no project)" not in t_ and t_.get("projects/alpha", {}).get("task") == "a1", t_)
    out = io.StringIO(); sys.stdin = io.StringIO(json.dumps({"session_id": sid}))
    with contextlib.redirect_stdout(out): pg.cmd_nag()
    sys.stdin = real_stdin
    check("…so the nag no longer says `carries no metadata.project`", "metadata.project" not in out.getvalue(), out.getvalue())
    # the "(no project)" debt of an item that carries a project: the server shows an
    # issue-numbered item as board#N, so a reply of a portal script that computes its item_id names it only in that form; a script may
    # pass the bare number; a write the server refused is no change; a debt that names no item cannot be looked at or settled
    (T / "store/g").mkdir(exist_ok=True)
    (T / "store/g/9158.json").write_text(json.dumps({"id": "9158", "subject": "[home] item 9158", "description": "x", "status": "open", "metadata": {"owner": "sparrow", "project": "projects/alpha"}}))
    (T / "store/g/9159.json").write_text(json.dumps({"id": "9159", "subject": "[home] item 9159", "description": "x", "status": "open", "metadata": {"owner": "sparrow"}}))
    REPLY57_TEXT = f"updated [board#{BID_A}](https://x/items/{BID_A}).\n[board#{BID_A}](https://x/items/{BID_A}) [open] [home] item {BID_A}\nowner: sparrow\nproject: projects/alpha\n"
    REPLY57 = json.dumps([{"result": REPLY57_TEXT}])
    sid = U(80); pg.save_state(sid, {"touches": {}})
    pg._touch_mcp_record({"session_id": sid, "tool_response": REPLY57}, {"item_id": True, "wake": "x"}, "update")     # a script's computed item_id (never a str)
    t_ = pg.load_state(sid).get("touches", {})
    check("no project: a reply naming the item as board#<a> gives the debt its project and its item, no (no project) key",
          list(t_) == ["projects/alpha"] and t_["projects/alpha"]["task"] == "g9158", t_)
    sid = U(81); pg.save_state(sid, {"touches": {}})
    pg._touch_mcp_record({"session_id": sid, "tool_response": TRIM}, {"item_id": "9158", "next": "x"}, "update")           # a bare issue number
    t_ = pg.load_state(sid).get("touches", {})
    check("no project: a bare issue number is resolved to the item and its stored project is read", list(t_) == ["projects/alpha"] and t_["projects/alpha"]["task"] == "g9158", t_)
    sid = U(82); pg.save_state(sid, {"touches": {}})
    REF = "Refused: metadata.wake must be YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04)"
    REFUSED_ALL = json.dumps([{"type": "text", "text": json.dumps([[{"type": "text", "text": REF}], [{"type": "text", "text": REF}]])}])   # as the portal returned it: an array of refused results
    pg._touch_mcp_record({"session_id": sid, "tool_response": REFUSED_ALL}, {"item_id": "9158", "wake": "x"}, "update")     # the item is known: only the refusal keeps the debt away
    check("no project: a portal script whose every write was refused owes nothing, though its item (9158, which has a project) is known", not pg.load_state(sid).get("touches"), pg.load_state(sid))
    MIXED = json.dumps([{"type": "text", "text": json.dumps([[{"type": "text", "text": REF}], {"result": REPLY57_TEXT}])}])
    pg.save_state(sid, {"touches": {}})
    pg._touch_mcp_record({"session_id": sid, "tool_response": MIXED}, {"item_id": "9158", "wake": "x"}, "update")
    t_ = pg.load_state(sid).get("touches", {})
    check("no project: a script that wrote one item and was refused on another still records its debt", list(t_) == ["projects/alpha"] and t_["projects/alpha"]["task"] == "g9158", t_)
    pg.save_state(sid, {"touches": {}})
    pg._touch_mcp_record({"session_id": sid, "tool_response": json.dumps([{"type": "text", "text": json.dumps([{"summary": "ok, set"}, REF])}])}, {"item_id": "9158", "wake": "x"}, "update")
    check("no project: a trimmed summary that mixes ok and Refused counts as written", list(pg.load_state(sid).get("touches", {})) == ["projects/alpha"], pg.load_state(sid))
    pg.save_state(sid, {"touches": {}})
    _gh = pg._ghsync(); (T / "store/l").mkdir(exist_ok=True)
    (T / "store/l/3.json").write_text(json.dumps({"id": "3", "subject": "[home] item tmp", "description": "x", "status": "open", "metadata": {"owner": "sparrow", "project": "projects/alpha"}}))
    TMP = _gh.local_prefix() + "#3"
    pg._touch_mcp_record({"session_id": sid, "tool_response": f"created [{TMP}](https://x/items/{TMP}).\n[{TMP}](https://x/items/{TMP}) [open] [home] item tmp\n"}, {"subject": "x"}, "create")
    t_ = pg.load_state(sid).get("touches", {})
    check("no project: a temporary id (board-tmp-<machine>#3) in a reply resolves to its item and project", list(t_) == ["projects/alpha"] and t_["projects/alpha"]["task"] == "l3", t_)
    sid = U(83); pg.save_state(sid, {"touches": {}})
    pg._touch_mcp_record({"session_id": sid, "tool_response": TRIM}, {"item_id": True, "next": "x"}, "update")
    check("no project: a trimmed reply with no item to ask about records no debt it could never settle", not pg.load_state(sid).get("touches"), pg.load_state(sid))
    sid = U(84); pg.save_state(sid, {"touches": {}})
    pg._touch_mcp_record({"session_id": sid, "tool_response": f"updated [board#{BID_B}](https://x/items/{BID_B}).\n[board#{BID_B}](https://x/items/{BID_B}) [open] [home] item {BID_B}\nowner: sparrow\n"}, {"item_id": True, "next": "x"}, "update")
    t_ = pg.load_state(sid).get("touches", {})
    check("no project: an item that really carries none is a (no project) debt, with its item", list(t_) == ["(no project)"] and t_["(no project)"]["task"] == "g9159", t_)
    stale_ = pg.stale_touches(sid)
    check("…and it keeps nagging when read again, naming the item as board#<a>",
          [k for k, _ in stale_] == ["(no project)"] and f"board item board#{BID_B} changed at" in pg.describe(*stale_[0]) and "carries no `metadata.project`" in pg.describe(*stale_[0]), stale_)
    now_ = int(time.time())
    pg.save_state(sid, {"touches": {"(no project)": {"ts": now_ + 3600, "task": "9158", "tool": "update"}}})                       # an older hook's debt: bare number, item has a project
    stale_ = pg.stale_touches(sid); t_ = pg.load_state(sid).get("touches", {})
    check("no project: a stale debt for an item that carries a project moves to that project when read (no clear needed), bare number and all",
          [k for k, _ in stale_] == ["projects/alpha"] and list(t_) == ["projects/alpha"] and t_["projects/alpha"]["task"] == "9158" and t_["projects/alpha"]["ts"] == now_ + 3600, (stale_, t_))
    pg.save_state(sid, {"touches": {"(no project)": {"ts": 1, "task": "9158", "tool": "update"}}})
    check("…and one older than the project page's last edit settles at once (the page was edited since)", pg.stale_touches(sid) == [] and not pg.load_state(sid).get("touches"), pg.load_state(sid))
    pg.save_state(sid, {"touches": {"(no project)": {"ts": now_, "task": "g999", "tool": "update"}}})
    check("…so is one for an item that no longer exists", pg.stale_touches(sid) == [] and not pg.load_state(sid).get("touches"), pg.load_state(sid))
    pg.save_state(sid, {"touches": {"(no project)": {"ts": now_, "task": "", "tool": "update"}}})
    check("…and one that names no item at all", pg.stale_touches(sid) == [] and not pg.load_state(sid).get("touches"), pg.load_state(sid))
    pg.save_state(sid, {"touches": {"(no project)": {"ts": now_, "task": "9158", "tool": "update"}, "projects/alpha": {"ts": now_, "task": "a1", "tool": "update"}}})
    client.urllib.request.urlopen = lambda req, timeout=0: (_ for _ in ()).throw(OSError("connection refused"))
    pg.UNREACHABLE.clear(); kept_ = [k for k, _ in pg.stale_touches(sid)]
    client.urllib.request.urlopen = fake_urlopen; pg.UNREACHABLE.clear()
    check("…while the server cannot be asked nothing is dropped", "(no project)" in kept_ and "(no project)" in pg.load_state(sid).get("touches", {}), (kept_, pg.load_state(sid)))
    pg.save_state(sid, {"touches": {"(no project)": {"ts": int(time.time()), "task": "a9"}}})
    out = io.StringIO(); real_csid = os.environ.get("CLAUDE_CODE_SESSION_ID"); os.environ["CLAUDE_CODE_SESSION_ID"] = sid   # the caller is the session that owes it
    with contextlib.redirect_stdout(out): rc_ = pg.main(["pages.py", "clear", "(no project)"])
    if real_csid is None: os.environ.pop("CLAUDE_CODE_SESSION_ID")
    else: os.environ["CLAUDE_CODE_SESSION_ID"] = real_csid
    check("no project: `clear \"(no project)\"` clears the literal key (no norm())", rc_ == 0 and not pg.load_state(sid).get("touches")
          and out.getvalue().startswith("cleared (no project) for you, ") and ": 1 session state(s)" in out.getvalue(), (out.getvalue(), pg.load_state(sid)))
    pg.BRAIN = real_brain; server._page_ts = real_ts; pg.LOCAL_ONLY = real_local
    server._cfg.CFG["pilot"]["writer_owes_page"] = _writer_owes

    # ============================================================= 8. the board's own sign-in
    check("the cookie signature holds, and a tampered cookie is nothing", server._ui_unsign(server._ui_sign("payload")) == "payload" and server._ui_unsign((lambda v: v[:-1] + ("0" if v[-1] != "0" else "1"))(server._ui_sign("payload"))) == "" and server._ui_unsign("") == "")
    check("the signing key is private", oct(os.stat(T / "secrets/ui-session.key").st_mode & 0o777) == "0o600")
    r = c.get("/", follow_redirects=False)
    check("ui_open false: the board asks for a sign-in", r.status_code == 302 and r.headers["location"] == "/ui/login?next=%2F", (r.status_code, r.headers.get("location")))
    r = c.get("/projects/alpha", follow_redirects=False); r2 = c.get("/board.md", follow_redirects=False)
    check("…so do a project's details page (/<page key>) and the files next to the board", r.status_code == 302 and r.headers["location"] == "/ui/login?next=%2Fprojects%2Falpha" and r2.status_code == 302, (r.status_code, r.headers.get("location")))
    # the details page's old address (/routing/<key>.html) and /<key>.html are permanent redirects to /<key>,
    # answered before the sign-in (they serve nothing), so a signed-out browser lands on the sign-in with next = the new address
    olds = {u: c.get(u, follow_redirects=False) for u in ("/routing/projects/alpha.html", "/routing/projects/alpha", "/routing/projects/alpha.html?x=1", "/projects/alpha.html", "/projects/alpha/")}
    check("old and .html addresses: 301 to /<key>, query dropped", all(r.status_code == 301 and r.headers["location"] == "/projects/alpha" for r in olds.values()), {u: (r.status_code, r.headers.get("location")) for u, r in olds.items()})
    r1 = c.get("/routing/projects/alpha.html", follow_redirects=False); r2 = c.get(r1.headers.get("location", "/x"), follow_redirects=False)
    check("…and a signed-out request to the old address ends at the sign-in with next = the new address", (r1.status_code, r2.status_code) == (301, 302)
          and r2.headers["location"] == "/ui/login?next=%2Fprojects%2Falpha", [(r.status_code, r.headers.get("location")) for r in (r1, r2)])
    r = c.get("/items/a1", follow_redirects=False)
    check("an item's page (/items/<gid>) asks for a sign-in, with next = the item page", r.status_code == 302 and r.headers["location"] == "/ui/login?next=%2Fitems%2Fa1", (r.status_code, r.headers.get("location")))
    its = {u: c.get(u, follow_redirects=False) for u in ("/items/a1.html", "/items/a1/", "/items/a1.html?x=1")}
    check("…and /items/<gid>.html and /items/<gid>/ are 301 to /items/<gid>, before the sign-in", all(r.status_code == 301 and r.headers["location"] == "/items/a1" for r in its.values()),
          {u: (r.status_code, r.headers.get("location")) for u, r in its.items()})
    bad = {u: c.get(u, follow_redirects=False).status_code for u in ("/routing/nope/alpha.html", "/routing/projects", "/routing/projects/a..b.html", "/routing/")}
    check("an old address that is not a page key: 404, no redirect", set(bad.values()) == {404}, bad)
    check("…but not the health check, the client API or the MCP endpoint's own answer", c.get("/healthz").status_code == 200 and c.get("/client/whoami", headers=HB).status_code == 200 and c.get("/mcp", follow_redirects=False).status_code in (401, 405, 406, 400))
    def ui_http(method, path, data, form=False):
        r = c.post(path, data=data) if form else c.post(path, json=data)
        try: return r.status_code, r.json()
        except Exception: return r.status_code, {}
    server._ui_http = ui_http
    r = c.get("/ui/login?next=/projects/alpha", follow_redirects=False)
    loc = r.headers.get("location", "")
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(loc).query)
    check("sign-in start: the board registers as a client of its own sign-in service and sends the browser to its /authorize, with PKCE", r.status_code == 302 and loc.startswith("https://stackshot.test/authorize?")
          and q.get("client_id") and q.get("code_challenge_method") == ["S256"] and q.get("redirect_uri") == ["https://stackshot.test/ui/callback"] and len(q.get("state", [""])[0]) > 10, (r.status_code, loc, r.text[:200]))
    flow_cookie = next((v.split(";")[0].split("=", 1)[1] for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("stackshot_ui_flow=")), "")
    r2 = c.get("/authorize?" + urlparse(loc).query, follow_redirects=False)
    check("…and that /authorize accepts the board's client and callback (it goes on towards consent or Google)", r2.status_code in (200, 302, 303) and "invalid" not in r2.text.lower()[:300]
          and (r2.status_code == 200 or any(x in r2.headers.get("location", "") for x in ("accounts.google.com", "/consent"))), (r2.status_code, r2.headers.get("location", "")[:120], r2.text[:200]))
    r = c.get("/ui/login?next=//evil.example", follow_redirects=False)
    fc2 = next((v.split(";")[0].split("=", 1)[1] for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("stackshot_ui_flow=")), "")
    check("an off-site `next` is not followed", json.loads(server._ui_unsign(fc2))["next"] == "/")
    state = q["state"][0]
    server._ui_exchange = lambda code, verifier: "stranger@example.com"
    r = c.get(f"/ui/callback?code=abc&state={state}", cookies={"stackshot_ui_flow": flow_cookie}, follow_redirects=False)
    check("sign-in end: an address that is not allowed gets no session", r.status_code == 403 and "set-cookie" not in {k for k, _ in r.headers.multi_items() if _.startswith("stackshot_ui=")}, (r.status_code, r.text))
    r = c.get("/ui/callback?code=abc&state=wrong", cookies={"stackshot_ui_flow": flow_cookie}, follow_redirects=False); r2 = c.get(f"/ui/callback?code=abc&state={state}", follow_redirects=False)
    check("sign-in end: a callback that does not belong to a sign-in started here is refused", r.status_code == 400 and r2.status_code == 400)
    seen_args = []
    server._ui_exchange = lambda code, verifier: (seen_args.append((code, verifier)), "you@example.com")[1]
    r = c.get(f"/ui/callback?code=abc&state={state}", cookies={"stackshot_ui_flow": flow_cookie}, follow_redirects=False)
    sess = next((v.split(";")[0].split("=", 1)[1] for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("stackshot_ui=")), "")
    attrs = next((v.lower() for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("stackshot_ui=")), "")
    check("sign-in end: an allowed address gets a signed session cookie and is sent on to where it was going", r.status_code == 302 and r.headers["location"] == "/projects/alpha" and sess
          and seen_args[0][0] == "abc" and len(seen_args[0][1]) > 40 and "httponly" in attrs and "secure" in attrs and "samesite=lax" in attrs, (r.status_code, r.headers.get("location"), attrs))
    r = c.get("/", cookies={"stackshot_ui": sess}, follow_redirects=False)
    check("with that cookie the board is served", r.status_code == 200 and "<html" in r.text.lower(), (r.status_code, r.text[:80]))   # the home is drawn per request
    r = c.get("/projects/alpha", cookies={"stackshot_ui": sess}, follow_redirects=False)
    check("…and so is a project's details page at /<page key>, uncached", r.status_code == 200 and "<title>home/Alpha</title>" in r.text and r.headers.get("cache-control") == "no-store", (r.status_code, r.text[:120]))
    r1 = c.get("/routing/projects/alpha.html", cookies={"stackshot_ui": sess}, follow_redirects=False); r = c.get(r1.headers.get("location", "/x"), cookies={"stackshot_ui": sess}, follow_redirects=False)
    check("…the old address lands on it too", r1.status_code == 301 and r.status_code == 200 and "<title>home/Alpha</title>" in r.text, (r1.status_code, r1.headers.get("location"), r.status_code))
    nf = {u: c.get(u, cookies={"stackshot_ui": sess}, follow_redirects=False).status_code for u in ("/projects/nope", "/ops/nope", "/routing/projects/nope.html", "/nope/alpha", "/favicon.svg/x", "/healthz/x")}
    check("…an unknown project is 404 (its old address after the redirect), and so is a path that is not a page key", nf == {"/projects/nope": 404, "/ops/nope": 404, "/routing/projects/nope.html": 301, "/nope/alpha": 404, "/favicon.svg/x": 404, "/healthz/x": 404}, nf)
    r = c.get("/items/a1", cookies={"stackshot_ui": sess}, follow_redirects=False)
    check("signed in, an item's page is served, uncached", r.status_code == 200 and '<h1><span class="hid">a1</span> item 1</h1>' in r.text and r.headers.get("cache-control") == "no-store", (r.status_code, r.headers.get("cache-control"), r.text[r.text.find("<h1"):][:200]))
    nfi = {u: c.get(u, cookies={"stackshot_ui": sess}, follow_redirects=False).status_code for u in ("/items/a99", "/items/z1", "/items/A1", "/items/1", "/items/", "/items/a1/x")}
    check("…an id the store does not hold is 404, and so is a path that is not an item id", set(nfi.values()) == {404}, nfi)
    check("…and a project's details page still renders beside it", c.get("/projects/alpha", cookies={"stackshot_ui": sess}, follow_redirects=False).status_code == 200)
    # the site title (title bar and tab) is the instance's title as it is
    _site = lambda t: re.findall(r'<(?:h1|p) class="site"><a [^>]*>(?:<img [^>]*>)?([^<]*)</a>', t)
    _tab = lambda t: re.findall(r"<title>([^<]*)</title>", t)
    _pages = {u: c.get(u, cookies={"stackshot_ui": sess}, follow_redirects=False) for u in ("/", "/items/a1", "/projects/alpha", "/closed", "/search?q=item")}
    check("titles: the board keeps the instance's title as it is in every title bar and tab",
          all(x.status_code == 200 for x in _pages.values())
          and all("stackshot: example" in _site(_pages[u].text) for u in ("/", "/closed", "/search?q=item")), {u: (x.status_code, _site(x.text), _tab(x.text)) for u, x in _pages.items()})
    _bt = server._rmod.Board(str(server._store.STORE)); _md = _bt.markdown()
    check("titles: Board.title is the plain instance title, and the markdown render (board.md) heads with it", _bt.title == "stackshot: example" and _md.startswith("# stackshot: example\n"), (_bt.title, _md[:60]))
    check("…and the files next to the board are served as before", c.get("/healthz").text == "ok" and c.get("/board.md", cookies={"stackshot_ui": sess}, follow_redirects=False).status_code in (200, 503)
          and c.get("/nothing.txt", cookies={"stackshot_ui": sess}, follow_redirects=False).status_code == 404)
    # the board's HTML is drawn per request and never cached
    r, r2 = c.get("/", cookies={"stackshot_ui": sess}, follow_redirects=False), c.get("/index.html", cookies={"stackshot_ui": sess}, follow_redirects=False)
    check("index: / and /index.html are drawn per request, with Cache-Control: no-store", all(x.status_code == 200 and "<html" in x.text.lower() and x.headers.get("cache-control") == "no-store" for x in (r, r2)),
          [(x.status_code, dict(x.headers)) for x in (r, r2)])
    r = c.get("/render-stamp", follow_redirects=False)
    check("render-stamp: behind the board's sign-in like the board", r.status_code == 302 and r.headers["location"] == "/ui/login?next=%2Frender-stamp", (r.status_code, r.headers.get("location")))
    r = c.get("/manifest.webmanifest", follow_redirects=False)
    try: mf = r.json()
    except Exception: mf = {}
    check("the web app manifest is served signed out, like the favicon it names (the page links it with use-credentials for the edge)",
          r.status_code == 200 and r.headers.get("content-type", "").split(";")[0] == "application/manifest+json"
          and {k: mf.get(k) for k in ("name", "short_name", "start_url", "scope", "display")} == {"name": "stackshot", "short_name": "stackshot", "start_url": "/", "scope": "/", "display": "standalone"}
          and (mf.get("icons") or [None])[0] == {"src": f"/favicon.svg?v={_hv(T / 'state/site/favicon.svg')}", "type": "image/svg+xml", "sizes": "any", "purpose": "any"}
          and re.fullmatch(r"#[0-9a-f]{6}", str(mf.get("theme_color", ""))), (r.status_code, r.headers.get("content-type"), mf))
    check("…and is itself served no-cache, so a new icon version reaches the installer at its next fetch", r.headers.get("cache-control") == "no-cache", r.headers.get("cache-control"))
    check("…its background_color (the splash screen) is the icons' full-bleed tile colour #1f1f21", mf.get("background_color") == "#1f1f21", mf.get("background_color"))
    want ={"/icon-192.png": (192, "any"), "/icon-512.png": (512, "any"), "/icon-maskable-512.png": (512, "maskable"), "/apple-touch-icon.png": (180, "any")}
    ver = {s: _hv(pathlib.Path(STACK, "icons", s[1:])) for s in want}     # the first 12 hex of the SHA-256 of each committed file's bytes
    got = {i.get("src"): (i.get("type"), i.get("sizes"), i.get("purpose")) for i in mf.get("icons", [])[1:]}
    check("…and lists the PNG icons after the SVG: sizes and purpose (one maskable), each src versioned by its bytes (?v=, the file name kept)",
          got == {f"{s}?v={ver[s]}": ("image/png", f"{px}x{px}", p) for s, (px, p) in want.items()}, got)
    for src, (px, purpose) in want.items():
        r = c.get(src, follow_redirects=False); b = r.content
        rv = c.get(f"{src}?v={ver[src]}", follow_redirects=False); rs = c.get(f"{src}?v=000000000000", follow_redirects=False)
        check(f"{src}: the unversioned URL is served as before, no Cache-Control of its own (the edge's default applies)",
              r.status_code == 200 and "cache-control" not in r.headers and r.headers.get("etag") and r.headers.get("last-modified"), dict(r.headers))
        check(f"{src}?v=<its version>: the same bytes, signed out, kept a year and never revalidated (immutable)",
              rv.status_code == 200 and rv.content == b and rv.headers.get("cache-control") == "public, max-age=31536000, immutable", (rv.status_code, dict(rv.headers)))
        check(f"{src}?v=<a stale version>: the current bytes, with the unversioned URL's headers, never immutable",
              rs.status_code == 200 and rs.content == b and "cache-control" not in rs.headers, (rs.status_code, dict(rs.headers)))
        dims = (int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")) if b[:8] == b"\x89PNG\r\n\x1a\n" and b[12:16] == b"IHDR" else None
        check(f"{src}: served signed out, image/png, {px}x{px} by its PNG header", r.status_code == 200 and r.headers.get("content-type", "").split(";")[0] == "image/png" and dims == (px, px),
              (r.status_code, r.headers.get("content-type"), dims))
        try: w, h, px_rows = _png_rgba(b)
        except Exception as e: w, h, px_rows = 0, 0, []; err = repr(e)
        else: err = None
        tile = (0x1f, 0x1f, 0x21, 255)
        corners = [px_rows[y][x] for y in (0, h - 1) for x in (0, w - 1)] if px_rows else []
        check(f"{src}: full bleed, every pixel opaque and the four corners the tile colour #1f1f21",
              err is None and all(p[3] == 255 for row in px_rows for p in row) and corners == [tile] * 4, (err, corners))
        if purpose == "maskable":                                    # the check inside the 80% safe circle: nothing but the tile outside it
            r2 = (0.4 * w) ** 2
            out = [(x, y) for y, row in enumerate(px_rows) for x, p in enumerate(row) if (x + 0.5 - w / 2) ** 2 + (y + 0.5 - h / 2) ** 2 > r2 and p != tile]
            check(f"{src}: only the tile colour outside the central 80% safe circle", px_rows != [] and not out, out[:5])
    # the code font (D2Coding, OFL): served by the server from the checkout's fonts/, signed out, WOFF2, versioned by ?v= like the icons
    fp = pathlib.Path(STACK, "fonts", "D2Coding-Regular.woff2"); fb = fp.read_bytes(); fv0 = _hv(fp); fu = "/fonts/D2Coding-Regular.woff2"
    r = c.get(fu, follow_redirects=False); rv = c.get(f"{fu}?v={fv0}", follow_redirects=False); rs = c.get(f"{fu}?v=000000000000", follow_redirects=False)
    check("/fonts/D2Coding-Regular.woff2: served signed out, font/woff2, the committed bytes (a WOFF2 by its signature), no Cache-Control on the unversioned URL",
          r.status_code == 200 and r.headers.get("content-type", "").split(";")[0] == "font/woff2" and r.content == fb and fb[:4] == b"wOF2" and "cache-control" not in r.headers,
          (r.status_code, dict(r.headers)))
    check("…?v=<its version>: kept a year and never revalidated (immutable); a stale version is not",
          rv.status_code == 200 and rv.content == fb and rv.headers.get("cache-control") == "public, max-age=31536000, immutable"
          and rv.headers.get("content-type", "").split(";")[0] == "font/woff2" and rs.status_code == 200 and "cache-control" not in rs.headers, (dict(rv.headers), dict(rs.headers)))
    check("…and the pages' stylesheet names exactly that URL, versioned by the file's bytes", f"{fu}?v={fv0}" == server._rmod.font_href(), (server._rmod.font_href(), fv0))
    check("…a name next to it is 404 (no directory listing, no other file under /fonts/)", all(c.get(u, follow_redirects=False).status_code in (404, 302) for u in ("/fonts/", "/fonts/OFL.txt", "/fonts/../server.py", "/fonts/README.md")))
    check("…and /manifest.webmanifest/x is not it", c.get("/manifest.webmanifest/x", cookies={"stackshot_ui": sess}, follow_redirects=False).status_code == 404)
    fav = T / "state/site/favicon.svg"; fv = _hv(fav)
    r, rv = c.get("/favicon.svg", follow_redirects=False), c.get(f"/favicon.svg?v={fv}", follow_redirects=False)
    check("/favicon.svg: unversioned as before (signed out, image/svg+xml, no Cache-Control); ?v=<its version> immutable",
          r.status_code == rv.status_code == 200 and r.headers.get("content-type", "").split(";")[0] == "image/svg+xml" and "cache-control" not in r.headers
          and rv.content == fav.read_bytes() and rv.headers.get("cache-control") == "public, max-age=31536000, immutable", (dict(r.headers), dict(rv.headers)))
    fav.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"/>')         # redrawn on disk without a restart
    r = c.get(f"/favicon.svg?v={fv}", follow_redirects=False)
    check("…a file redrawn after the start: its old version no longer matches the bytes sent, so it is not immutable",
          r.status_code == 200 and r.content == fav.read_bytes() and "cache-control" not in r.headers and _hv(fav) != fv, dict(r.headers))
    r = c.get(f"/favicon.svg?v={_hv(fav)}", follow_redirects=False)
    check("…and the new bytes' version is", r.headers.get("cache-control") == "public, max-age=31536000, immutable", dict(r.headers))
    forged = sess[:-1] + ("0" if sess[-1] != "0" else "1")          # one hex digit of the signature changed, whatever it was
    r = c.get("/", cookies={"stackshot_ui": forged}, follow_redirects=False)
    exp = server._ui_sign(json.dumps({"email": "you@example.com", "exp": time.time() - 5})); r2 = c.get("/", cookies={"stackshot_ui": exp}, follow_redirects=False)
    gone = server._ui_sign(json.dumps({"email": "left@example.com", "exp": time.time() + 999})); r3 = c.get("/", cookies={"stackshot_ui": gone}, follow_redirects=False)
    check("a forged, an expired and a no-longer-allowed cookie all go back to the sign-in", (r.status_code, r2.status_code, r3.status_code) == (302, 302, 302))
    server._cfg.CFG["auth"]["ui_open"] = True                       # read at each request: no restart
    check("ui_open true (today's setting): the board is served without a sign-in, as before", c.get("/", follow_redirects=False).status_code == 200 and c.get("/ui/login", follow_redirects=False).headers["location"] == "/")
    server._cfg.CFG["auth"]["ui_open"] = False

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": contract scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
os._exit(1 if fails else 0)
