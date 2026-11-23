"""Scenario test for [server] box and the publisher key of a server moved to another box — fixture data, no network, no server.

Covers: where a pane hook reads the page registry, a page's time and whether a page exists from. Unset: from the pages checkout when the machine
holds it, else the client API (the rule before the setting existed). `box = false`: the client API even when the checkout is on the disk, and the
local files are never read. `box = true`: the checkout, with the API never asked. A value that is not a boolean reads as unset and `notes` says so.
The SessionStart hook renders no local brief where `box = false`. The publisher key: [fleet] publisher_letter wins for a hostname the names table
does not list, in fleet.publisher() and in what reboot-queue.py reads at its start; a machine first seen takes a letter other than the publisher's,
except the server box's own puller, which takes it (one card for the server on the Machines panel). Every place pages.py asks `reads_local()` is tried
with the checkout on the disk under `box = false` (the API answers, nothing is read from the clone) and under `box = true` / unset (the clone is read).

    tests/run-suite server_box        → exit 0 / 1"""
import contextlib, io, json, os, pathlib, re, subprocess, sys, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="serverboxtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"),
                 ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("fleet_names", f"{tmp}/names.tsv")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
for k in ("STACKSHOT_URL", "STACKSHOT_AUTH"): os.environ.pop(k, None)
for d in ("store", "brain/projects", "fleet", "state", "secrets", "touch"): (T / d).mkdir(parents=True)
ENTRY = {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "sparrow", "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": ""}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/local-only": ENTRY}}))     # what the local files say
(T / "brain/projects/local-only.md").write_text("---\ntitle: Alpha\nname: Alpha\n---\n\n# Alpha\n")
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name); print(("ok   " if cond else "FAIL ") + name + ("" if cond or got is None else f": {str(got)[:900]}"))
    if not cond: fails.append(name)

from stackshot.core import config as cfg
from stackshot.projects import pages as pg
SV = cfg.CFG.setdefault("server", {})
CALLS = []
def fake_api(what, key="", timeout=6.0, **extra):
    CALLS.append(what)
    return {"registry": json.dumps({"pages": {"projects/api-only": ENTRY}}), "page-ts": json.dumps({"ts": 4242})}.get(what)
pg._api = fake_api; pg.LOCAL_ONLY = False
pg.BRAIN = str(T / "brain"); pg.REG = str(T / "store/projects.json")
NOCLONE = str(T / "no-clone")

def reads(box, brain):
    """(registry keys, page_ts of the local page, exists of the api page, the API calls made) under [server] box = box with the pages checkout at brain."""
    SV.pop("box", None)
    if box is not None: SV["box"] = box
    pg.BRAIN = brain; CALLS.clear()
    reg = sorted(pg.load_registry() or {}); ts = pg.page_ts("projects/local-only"); ex = pg.exists("projects/api-only")
    return reg, ts, ex, list(CALLS)

# ---- unset: today's behaviour
reg, ts, ex, calls = reads(None, str(T / "brain"))
check("unset, the checkout on the disk: the registry and the page's time are read from the files, the API is never asked",
      reg == ["projects/local-only"] and ts and ts != 4242 and ex is False and calls == [], (reg, ts, ex, calls))
reg, ts, ex, calls = reads(None, NOCLONE)
check("unset, no checkout: the registry, the page's time and a page's existence come from the API",
      reg == ["projects/api-only"] and ts == 4242 and ex is True and "registry" in calls and "page-ts" in calls, (reg, ts, ex, calls))
# ---- false: the API even with the checkout there
reg, ts, ex, calls = reads(False, str(T / "brain"))
check("box = false with the checkout on the disk: the registry, the page's time and the page's existence come from the API; the files are not read",
      reg == ["projects/api-only"] and ts == 4242 and ex is True and "registry" in calls and "page-ts" in calls, (reg, ts, ex, calls))
reg, ts, ex, calls = reads("false", str(T / "brain"))
check("…the string \"false\" says the same", reg == ["projects/api-only"] and ts == 4242, (reg, ts))
# ---- true: the files
reg, ts, ex, calls = reads(True, str(T / "brain"))
check("box = true: the registry and the page's time are read from the checkout, the API is never asked",
      reg == ["projects/local-only"] and ts and ts != 4242 and ex is False and calls == [], (reg, ts, ex, calls))
reg, ts, ex, calls = reads(True, NOCLONE)
check("box = true with no pages checkout there: the registry is still the store's file, never the API's (a page with no file is then asked of the API for its time)",
      reg == ["projects/local-only"] and "registry" not in calls, (reg, calls))

# exists() with box = true and no checkout: the registry answers, as it did before the setting (the store's file, True / False; None when it cannot be read)
SV["box"] = True; pg.BRAIN = NOCLONE
check("box = true, no checkout: a page is found in the registry's file (True) or is not (False), never read off a missing clone",
      pg.exists("projects/local-only") is True and pg.exists("projects/nowhere") is False, (pg.exists("projects/local-only"), pg.exists("projects/nowhere")))
pg.REG = str(T / "store/none.json")
check("box = true, no checkout, no registry to read: exists() cannot tell (None)", pg.exists("projects/local-only") is None, pg.exists("projects/local-only"))
pg.REG = str(T / "store/projects.json"); pg.BRAIN = str(T / "brain"); SV.pop("box", None)

# ---- the reading of the value, and the note
for v, want in ((True, True), (False, False), ("TRUE", True), ("False", False), (" false ", False), ("yes", None), (1, None), ("", None)):
    SV["box"] = v; got = cfg.server_box()
    check(f"server_box() reads {v!r} as {want!r}", got is want, got)
SV["box"] = "maybe"
check("a value that is not a boolean is said by notes() as read as unset", any("[server] box" in n and "unset" in n for n in cfg.notes()), cfg.notes())
SV["box"] = False
check("a boolean is not noted", not any("[server] box" in n for n in cfg.notes()))
SV.pop("box", None)
check("unset is not noted", not any("[server] box" in n for n in cfg.notes()))

# ---- the SessionStart hook renders no local brief where box = false
HOOK = f"{STACK}/client/hooks/session-start.sh"
toml_plain = toml
def hook_with(box):
    body = toml_plain if box is None else re.sub(r'(?m)^\[server\]\n', f'[server]\nbox = {box}\n', toml_plain, count=1)
    p = T / "hook.toml"; p.write_text(body, encoding="utf-8")
    env = {**os.environ, "STACKSHOT_CONFIG": str(p), "STACKSHOT_URL": "http://127.0.0.1:9", "HOME": str(T)}
    return subprocess.run(["bash", HOOK], input="{}", capture_output=True, text=True, env=env, timeout=120).stdout.strip()
out_unset, out_false = hook_with(None), hook_with("false")
check("SessionStart hook, the server away: unset renders the brief from the local store", len(out_unset) > 0, out_unset)
check("…box = false renders nothing of its own", out_false == "", out_false)
for raw in ('"False"', '" false"', '"FALSE "', '" false "'):         # the strings server_box() accepts: the hook reads the same value
    got = hook_with(raw)
    check(f"…box = {raw} (a string) renders nothing of its own, as server_box() reads it as false", got == "", got)
check("…box = true renders the brief, as unset does", len(hook_with("true")) > 0)
check("…a value that is not a boolean reads as unset: the brief is rendered", len(hook_with('"maybe"')) > 0)
r = subprocess.run([sys.executable, f"{STACK}/stackshot/core/config.py", "server-box"], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": str(T / "hook.toml")}, timeout=60)
check("config.py server-box prints the normalized value (empty for a value that is no boolean)", r.stdout.strip() == "" and r.returncode == 0, (r.stdout, r.stderr[-200:]))

# ---- every place pages.py asks reads_local(), with the checkout on the disk
# box = false: the API (or the "no mirror here" answer) and nothing read from the clone. box = true / unset: the clone is read.
import time as _time
SID = "sparrow"; KEY = "projects/local-only"
G = cfg.CFG.setdefault("page_gate", {}); G["keeper_currency"] = "all"
pg.UNREACHABLE.clear()
def run_out(fn, *a, stdin="{}"):
    """(return value, stdout, stderr) of fn(*a) with `stdin` as the hook's input."""
    out, err, was = io.StringIO(), io.StringIO(), sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): rv = fn(*a)
    finally: sys.stdin = was
    return rv, out.getvalue(), err.getvalue()
def setbox(box, brain=None):
    SV.pop("box", None)
    if box is not None: SV["box"] = box
    pg.BRAIN = brain or str(T / "brain"); CALLS.clear(); pg.UNREACHABLE.clear(); pg.UNKNOWN.clear()
MODES = (("box = false", False), ("box = true", True), ("unset", None))

# cmd_registry
REG_BASE = (T / "store/projects.json").read_text()
for label, box in MODES:
    (T / "store/projects.json").write_text(REG_BASE); setbox(box)
    rv, _o, err = run_out(pg.cmd_registry, True)
    now = (T / "store/projects.json").read_text()
    if box is False:
        check("cmd_registry, box = false with the checkout on the disk: it builds nothing and says there is no mirror here", rv == 0 and "no brain mirror here" in err and now == REG_BASE, (rv, err[-200:]))
    else:
        check(f"cmd_registry, {label} with the checkout on the disk: it builds the registry from the clone", rv == 0 and "no brain mirror here" not in err and now != REG_BASE, (rv, err[-200:]))
(T / "store/projects.json").write_text(REG_BASE)

# page_ts, and ct_changed_since (the timestamp rule when the page's copy is not read)
for label, box in MODES:
    setbox(box)
    t = pg.page_ts(KEY); ch = pg.ct_changed_since(KEY, 4000)
    if box is False:
        check("page_ts and ct_changed_since, box = false with the checkout on the disk: the API's time, no clone read", t == 4242 and ch is True and CALLS.count("page-ts") == 2, (t, ch, CALLS))
    else:
        check(f"page_ts and ct_changed_since, {label} with the checkout on the disk: the clone is read, the API is not asked", t not in (None, 4242) and CALLS == [], (t, ch, CALLS))
# a second brain whose copy is missing
cfg.CFG["brains"] = [{"name": "second", "path": str(T / "second-missing"), "home": str(T / "second-home"), "prefixes": ["projects/sec-"]}]
SK = "projects/sec-one"
setbox(None); t = pg.page_ts(SK); ch = pg.ct_changed_since(SK, 4000)
check("a second brain whose copy is missing, unset (the main checkout there): its page's time and ct_changed_since ask the API", t == 4242 and ch is True and CALLS.count("page-ts") == 2, (t, ch, CALLS))
setbox(False); t = pg.page_ts(SK)
check("…and box = false asks the API as well", t == 4242 and CALLS == ["page-ts"], (t, CALLS))
setbox(True); t = pg.page_ts(SK); ch = pg.ct_changed_since(SK, 4000)
check("…box = true reads the (missing) copy and finds nothing, the API is not asked for the second brain's page", ch is False and "page-ts" in CALLS and CALLS.count("page-ts") == 1, (t, ch, CALLS))

# stale_touches: both sites
def touch(key, ts):
    pg.save_state(SID, {"touches": {key: {"ts": ts, "task": "g1", "tool": "update"}}})
def stale(key, ts=5000):
    touch(key, ts); sk = {}; out = pg.stale_touches(SID, skipped=sk); return [k for k, _v in out], sk, list(pg.UNKNOWN)
setbox(False); pg.UNREACHABLE.append("server")      # the server cannot be reached, and the page's time is not at hand
fake_down = pg._api; pg._api = lambda what, key="", timeout=6.0, **extra: CALLS.append(what)         # the server does not answer
out, sk, unk = stale(KEY)
check("stale_touches, box = false with the checkout on the disk and the server down: the page is unknown (checked again later), not read from the clone", out == [] and unk == [KEY] and sk == {}, (out, sk, unk, CALLS))
setbox(True); pg.UNREACHABLE.append("server")
out, sk, unk = stale(KEY)
check("stale_touches, box = true with the checkout on the disk: the clone settles it, nothing is unknown", out == [] and unk == [] and CALLS == [], (out, sk, unk, CALLS))
setbox(None); pg.UNREACHABLE.append("server")
out, sk, unk = stale(KEY)
check("stale_touches, unset with the checkout on the disk: the clone settles it, nothing is unknown", out == [] and unk == [] and CALLS == [], (out, sk, unk, CALLS))
pg._api = fake_down
setbox(False)
out, sk, unk = stale(SK, 4000)
check("stale_touches, a second brain whose copy is missing, box = false: the page is not skipped as unreadable (the API answers for it)", sk == {} and out == [] and "page-ts" in CALLS, (out, sk, unk, CALLS))
for label, box in (("box = true", True), ("unset", None)):
    setbox(box); out, sk, unk = stale(SK)
    check(f"stale_touches, a second brain whose copy is missing, {label}: the page is skipped (fail open) and the API is not asked", sk == {SK: "second"} and out == [] and CALLS == [], (out, sk, unk, CALLS))
cfg.CFG.pop("brains", None)
pg.save_state(SID, {"touches": {}})

# describe: the nag's wording is true both where the clone is read and where it is not
v = {"ts": 1_700_000_000, "tool": "update"}
setbox(False); txt_false = pg.describe(KEY, v)
check("describe, box = false with a clone on the disk: it says the machine does not read pages from a checkout, and never that it has none", "does not read pages from" in txt_false and "none of" not in txt_false, txt_false)
for label, box in (("box = true", True), ("unset", None)):
    setbox(box); txt = pg.describe(KEY, v)
    check(f"describe, {label} with the checkout on the disk: it names the file in the checkout", "does not read pages from" not in txt and "commit and push)" in txt and f"{KEY}.md" in txt, txt)
setbox(None, NOCLONE); txt = pg.describe(KEY, v)
check("describe, unset with no checkout: the same wording as box = false", "does not read pages from" in txt, txt)

# cmd_keeper and cmd_nag: the keeper's pages are shown from the clone only where it is read
SHOWN = pathlib.Path(pg.shown_path(SID))
for label, box in MODES:
    setbox(box); SHOWN.unlink(missing_ok=True)
    rv, o, _e = run_out(pg.cmd_keeper, stdin=json.dumps({"session_id": SID}))
    st_k = SHOWN.read_text().split()[0] if SHOWN.exists() else ""
    if box is False:
        check("cmd_keeper, box = false with the checkout on the disk: the keeper gets nothing from the clone, the session is marked pending", rv == 0 and o == "" and st_k == "pending", (o[:200], st_k, CALLS))
    else:
        check(f"cmd_keeper, {label} with the checkout on the disk: the keeper gets its page's Current state from the clone", rv == 0 and "[project-page]" in o and "# Alpha" in o and st_k == "shown", (o[:300], st_k))
    setbox(box); SHOWN.write_text("pending 1\n"); pg.UNREACHABLE.append("server")           # a prompt of a session whose start found no page: the nag looks again
    rv, o, _e = run_out(pg.cmd_nag, stdin=json.dumps({"session_id": SID}))
    if box is False:
        check("cmd_nag, box = false with the checkout on the disk: a pending keeper is not given pages from the clone", rv == 0 and "[project-page] You" not in o and SHOWN.read_text().startswith("pending"), (o[:200], SHOWN.read_text()))
    else:
        check(f"cmd_nag, {label} with the checkout on the disk: a pending keeper is given its pages from the clone", rv == 0 and "[project-page] You" in o and SHOWN.read_text().startswith("shown"), (o[:200], SHOWN.read_text()))
SHOWN.unlink(missing_ok=True); pg.UNREACHABLE.clear()

# agent-listed
for label, box in MODES:
    setbox(box); rv, o, _e = run_out(pg.main, ["pages.py", "agent-listed", "nobody-here"])
    if box is False:
        check("agent-listed, box = false with the checkout on the disk: it cannot tell (exit 2), the clone is not read", rv == 2 and "no brain mirror on this machine" in o, (rv, o))
    else:
        check(f"agent-listed, {label} with the checkout on the disk: the project record and the clone answer", rv in (0, 3) and "no brain mirror on this machine" not in o, (rv, o))
setbox(None)

# ---- the publisher key of a server moved to a box the names table does not list
from stackshot.fleet import fleet as flt, clients
FL = cfg.CFG.setdefault("fleet", {})
(T / "names.tsv").write_text("# os hostname\tfleet name\tletter\nbox-a\tbox-a\ta\nbox-e\tbox-e\te\n", encoding="utf-8")
own_was = flt.own_hostname; flt.own_hostname = lambda: "Newbox.example.net"
FL.pop("publisher_letter", None)
check("publisher: unset on a hostname the names table does not list, the key is the lower-cased hostname", flt.publisher() == "newbox", flt.publisher())
FL["publisher_letter"] = "g"
check("publisher: [fleet] publisher_letter names it outright for the same unlisted hostname", flt.publisher() == "g", flt.publisher())
(T / "names.tsv").unlink()
check("…and with no names table at all", flt.publisher() == "g", flt.publisher())
(T / "names.tsv").write_text("# os hostname\tfleet name\tletter\nbox-a\tbox-a\ta\nbox-e\tbox-e\te\n", encoding="utf-8")
RQ = f"{STACK}/reboot-hooks/reboot-queue.py"
PROBE = ("import importlib.util, sys; sys.argv = ['reboot-queue.py']; "
         "from stackshot.fleet import fleet; fleet.own_hostname = lambda: 'Newbox.example.net'; "
         f"s = importlib.util.spec_from_file_location('rq', {RQ!r}); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.PUB)")
def rq_pub(letter):
    body = toml_plain if letter is None else re.sub(r'(?m)^\[fleet\]\n', f'[fleet]\npublisher_letter = "{letter}"\n', toml_plain, count=1)
    assert letter is None or f'publisher_letter = "{letter}"' in body
    p = T / "rq.toml"; p.write_text(body, encoding="utf-8")
    r = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, cwd=STACK, env={**os.environ, "STACKSHOT_CONFIG": str(p), "PYTHONPATH": STACK}, timeout=120)
    return r.stdout.strip(), r.stderr[-300:]
check("reboot-queue.py: its publisher key is the setting for an unlisted hostname", rq_pub("g")[0] == "g", rq_pub("g"))
check("…and the lower-cased hostname when the setting is unset", rq_pub(None)[0] == "newbox", rq_pub(None))
flt.own_hostname = own_was

# the server box's own puller takes the publisher's letter, whichever registers first: one card for the server, and another letter for any other machine
(T / "names.tsv").write_text("# os hostname\tfleet name\tletter\nbox-a\tbox-a\ta\nbox-e\tbox-e\te\n", encoding="utf-8")
flt.own_hostname = lambda: "Newbox.example.net"; FL["publisher_letter"] = "g"
for first, second in (("Newbox.example.net", "stranger-box"), ("stranger-box", "Newbox.example.net")):
    st = {"machines": {}}; clients._machine(st, first); clients._machine(st, second)
    letters = {k: v["letter"] for k, v in st["machines"].items()}; panel = {v["letter"]: v["fleet"] for v in st["machines"].values()}
    cards = flt.machines_order(panel, [])
    check(f"new server box (publisher_letter set, no names row), {first.split('.')[0]} registers first: the server has the publisher's letter, the other machine another",
          letters["Newbox.example.net"] == "g" and letters["stranger-box"] not in ("g", "a", "e", "c") and flt.publisher() == "g", letters)
    check("…and the Machines panel shows one card for the server and one for the other machine", cards == ["Newbox.example.net", "stranger-box"], cards)
st = {"machines": {"holder": {"letter": "g", "fleet": "holder", "first": "x"}}}
check("the publisher's letter is not taken from a machine that already holds it", clients._machine(st, "Newbox.example.net")["letter"] != "g")
FL.pop("publisher_letter")
st = {"machines": {}}
check("without publisher_letter the server box's puller takes the first free letter, as any machine does", clients._machine(st, "Newbox.example.net")["letter"] == "b")
flt.own_hostname = own_was

# a machine first seen by the server takes no letter the publisher holds
FL["publisher_letter"] = "b"
m = clients._machine({"machines": {}}, "stranger-box")
check("a machine the names table does not list takes the first free letter, never the publisher's", m["letter"] not in ("a", "e", "b", "c") and m["letter"] == "d", m)
FL.pop("publisher_letter")
m = clients._machine({"machines": {}}, "stranger-box")
check("…which is b when the publisher does not hold it", m["letter"] == "b", m)

print(f"\n{len(ran) - len(fails)}/{len(ran)} passed")
sys.exit(1 if fails else 0)
