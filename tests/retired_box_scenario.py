"""Scenario test for a retired box: its letter is in [fleet] retired_letters, so it has no card — fixture data, no live store, no network, no server.

Covers: the Machines panel, `fleet.names()`, `fleet.machines_order()`, the versions read (`machines_state`, versions.json), the board's per-machine facts (so a failed setup on a retired box gives
no alert card) and the sessions tool's Machines list leave out the letters in [fleet] retired_letters (`fleet.drawn_letters`), also a retired letter that has a row in the names table, while
`fleet.letters()` and the readers that find a session or an owner (`fleet.sessions()`, `by_name`) still see every folder; the default (no key, an empty list) draws every folder's letter; the key's
shapes (one string, spaces around a letter, items that are not strings, a value that is not a list, a letter in another case) never raise and retire only what is named; the publisher's letter is
never left out; a change of the setting is read at the next draw. The server side is untouched: `clients.checkin` and `clients.tick` still write a retired box's folder and keep its sessions as
last known (a session gone from the box is marked gone there), and a successor of the same name on another box resolves to the running one.

    tests/run-suite retired_box        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging, shutil
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="retiredboxtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai"), ("fleet_names", f"{tmp}/names.tsv")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^latest_lookups = true', 'latest_lookups = false', toml); assert n == 1                  # never npm or GitHub
toml, n = re.subn(r'(?m)^ssh_hosts = \[\]', 'ssh_hosts = []', toml); assert n == 1
toml += '\n[[machines_panel.packages]]\nname = "claude code"\nowner = ""\ninstalled = "fleet"\nlatest = "github-release:x/y"\n'
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
FLEET = T / "state/clients/fleet"                                    # the one folder the server writes and the readers read
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=str(FLEET))
for d in ("store/a", "state/site", "secrets", "touch"): (T / d).mkdir(parents=True)
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "state/site/versions.latest.json").write_text(json.dumps({"claude code": "1.7.40"}))
NAMES = T / "names.tsv"
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name); print(("ok   " if cond else "FAIL ") + name + ("" if cond or got is None else f": {str(got)[:900]}"))
    if not cond: fails.append(name)

from stackshot.fleet import fleet as flt
from stackshot.fleet import clients
from stackshot.fleet import versions as ver
from stackshot.web.ui import render as ui_render
from stackshot.web import render as txt_render
from stackshot.web.tools import sessions as sess_tool
from stackshot.service import fleet_events
ver._installed_cmd = lambda cmd: "1.7.40"
flt.publisher = lambda: "a"                                          # the box the server runs on: this test's own, whatever the host is called
sess_tool._fleet_names = fleet_events.fleet_names                     # what register() hands the tool
FL = flt._cfg.CFG.setdefault("fleet", {})
def retire(v):
    if v is None: FL.pop("retired_letters", None)
    else: FL["retired_letters"] = v

NOW = 1_800_000_000.0
def put(L, fleet_name, **extra):
    """A machine's folder as the view writes it (machine.json and sessions.json), for the reader checks."""
    (FLEET / L).mkdir(parents=True, exist_ok=True)
    (FLEET / L / "machine.json").write_text(json.dumps({"letter": L, "fleet": fleet_name, "claude": "1.7.40", "online": {"ok": True, "since": "2026-10-20T00:00:00Z"}, **extra}))
    (FLEET / L / "sessions.json").write_text(json.dumps({f"0000000{L}-0000-0000-0000-000000000000": {"name": f"sess-{L}", "seen": "2026-10-20T00:00:00Z", "machine": L, "url": ""}}))
def panel():
    h = ui_render.Board(str(T / "store")).render({"html"})["html"]
    sec = h[h.find('<section id="machines">'):]; return sec[:sec.find("</details>")]
def cards(sec): return re.findall(r'<b class="lbl mh">([^<]*)</b>', sec)

# ---- 1. the readers
for L, nm in (("a", "box-a"), ("b", "box-b"), ("e", "box-e")): put(L, nm)
m = json.loads((FLEET / "e/machine.json").read_text()); m["setup"] = {"at": "2026-10-15T00:00:00Z", "ok": False, "step": "Install Claude Code", "reason": "winget exited"}
(FLEET / "e/machine.json").write_text(json.dumps(m))                 # the retired box's old failure: it must not come back as an alert card
ver.write(force=True)
check("default (no key): every folder is drawn, the failed box's alert on its card", cards(panel()) == ["box-a", "box-b", "box-e"] and flt.drawn_letters() == ["a", "b", "e"], cards(panel()))
retire([])
check("an empty list retires nothing", flt.drawn_letters() == ["a", "b", "e"] and flt.retired_letters() == frozenset())

retire(["e"])
ver.write(force=True); sec = panel()
check("a retired box has no card, though its folder is there", cards(sec) == ["box-a", "box-b"] and "box-e" not in sec and "Install Claude Code" not in sec, cards(sec))
check("fleet.names(): the retired box's folder names nothing", flt.names() == {"a": "box-a", "b": "box-b"}, flt.names())
check("fleet.machines_order(): the retired box is not in the order", flt.machines_order() == ["box-a", "box-b"], flt.machines_order())
check("fleet.drawn_letters() leaves the retired letter out; fleet.letters() still lists the folder", flt.drawn_letters() == ["a", "b"] and flt.letters() == ["a", "b", "e"], (flt.drawn_letters(), flt.letters()))
ms, st = ver.machines_state()
check("the versions read gives the retired box no version and no state", sorted(ms) == ["a", "b"] and sorted(st) == ["a", "b"], (ms, st))
doc = json.loads((T / "state/site/versions.json").read_text()); pk = next(p for p in doc["packages"] if isinstance(p.get("machines"), dict))
check("versions.json carries no machine for the retired box", sorted(pk["machines"]) == ["a", "b"] and sorted(pk["machine_state"]) == ["a", "b"], pk)
check("the board's per-machine facts leave the retired box out (no alert card)", sorted(ui_render.Board(str(T / "store")).mfacts) == ["a", "b"] and sorted(txt_render.Board(str(T / "store")).mfacts) == ["a", "b"])
listing = sess_tool._sessions_listing("").split("Sessions (")[0]               # the Machines lines (a session of the retired box is still listed under Sessions: its identity is kept)
check("the sessions tool lists the drawn machines only", "- box-a:" in listing and "- box-b:" in listing and "box-e" not in listing, listing)
check("what finds sessions still reads every folder: the retired box's session is in fleet.sessions() and its name resolves",
      "0000000e-0000-0000-0000-000000000000" in flt.sessions() and flt.by_name().get("sess-e") == "0000000e-0000-0000-0000-000000000000", sorted(flt.sessions()))

NAMES.write_text("box-a-os\tbox-a\ta\nbox-b-os\tbox-b\tb\nbox-e-os\tbox-e\te\nbox-q-os\tbox-q\tq\n", encoding="utf-8")      # the retired boxes still have their rows in the names table (q has no folder)
check("a retired letter that has a row in the names table is not named either (with a folder, or with none)", flt.names() == {"a": "box-a", "b": "box-b", "q": "box-q"} and cards(panel()) == ["box-a", "box-b", "box-q"], (flt.names(), cards(panel())))
retire(["e", "q"])
check("…a retired letter with a row and no folder", flt.names() == {"a": "box-a", "b": "box-b"} and cards(panel()) == ["box-a", "box-b"], (flt.names(), cards(panel())))
retire(["e"]); NAMES.unlink()

# ---- 2. the shapes of the key
for label, v, want in (("one string", "e", ["a", "b"]), ("spaces around a letter", [" e "], ["a", "b"]), ("items that are not strings, an empty one", [1, None, "", "  ", "e", ["b"]], ["a", "b"]),
                       ("a value that is not a list", {"e": 1}, ["a", "b", "e"]), ("a number", 5, ["a", "b", "e"]), ("a letter in another case", ["E"], ["a", "b", "e"]),
                       ("two letters", ["b", "e"], ["a"]), ("a letter no folder has", ["z"], ["a", "b", "e"]), ("key absent", None, ["a", "b", "e"])):
    retire(v)
    try: got = flt.drawn_letters()
    except Exception as ex: got = repr(ex)
    check(f"the key as {label}: never raises, retires only what is named", got == want, got)
retire(["b", "e"]); check("a change of the setting is read at the next draw", flt.drawn_letters() == ["a"] and flt.names() == {"a": "box-a"}, (flt.drawn_letters(), flt.names()))

# ---- 3. the publisher is never left out
retire(["a", "e"])
check("a retired letter that is the publisher's own is still drawn", flt.drawn_letters() == ["a", "b"] and sorted(flt.names()) == ["a", "b"], (flt.drawn_letters(), flt.names()))
flt.publisher = lambda: "e"
check("…whichever letter the publisher is", flt.drawn_letters() == ["b", "e"], flt.drawn_letters())
flt.publisher = lambda: "a"

# ---- 4. the server writes a retired box's folder as before
for L in ("a", "b", "e"): shutil.rmtree(FLEET / L)
retire(["e"])
SA, SB = "00000001-0000-4000-8000-000000000001", "00000002-0000-4000-8000-000000000002"
NAMES.write_text("box-a-os\tbox-a\ta\nbox-b-os\tbox-b\tb\nbox-e-os\tbox-e\te\n", encoding="utf-8")
clients.checkin("box-a-os", [], {"claude": "1.7.40"}, now=NOW)
clients.checkin("box-e-os", [{"uuid": SA, "name": "twin"}], {"claude": "1.7.40"}, now=NOW)
check("a retired letter's folder is written by a check-in", (FLEET / "e/machine.json").is_file() and SA in json.loads((FLEET / "e/sessions.json").read_text()), sorted(p.name for p in FLEET.iterdir()))
clients.checkin("box-e-os", [], {"claude": "1.7.41"}, now=NOW + 30)
row = json.loads((FLEET / "e/sessions.json").read_text())[SA]
check("a session gone from the retired box is marked gone in its folder, not held as running", row.get("gone") and json.loads((FLEET / "e/machine.json").read_text())["claude"] == "1.7.41", row)
clients.checkin("box-a-os", [{"uuid": SB, "name": "twin"}], {"claude": "1.7.40"}, now=NOW + 60)
check("a successor of the same name on a drawn box resolves to the running session", flt.by_name().get("twin") == SB and not flt.running(flt.sessions()[SA]) and flt.running(flt.sessions()[SB]), flt.by_name())
check("the retired box is still not drawn, though the server keeps writing it", flt.drawn_letters() == ["a"] and flt.letters() == ["a", "e"], (flt.drawn_letters(), flt.letters()))
clients.tick(NOW + 90)
check("the tick keeps writing it too", (FLEET / "e/machine.json").is_file())

print(f"\n{len(ran) - len(fails)}/{len(ran)} passed")
sys.exit(1 if fails else 0)
