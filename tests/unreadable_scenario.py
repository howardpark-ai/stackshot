"""Scenario test for anchors the hub cannot read (an anchored mail thread sat in a mailbox the hub had no token for, and nothing told the session) on fixture data — a fake clock, fake sources, no network.

Covers: a refusal is asked for once more a minute later and then reported once, to the project's keeper; a network error is
not a refusal; the tries thin out (60 s doubling to 6 h); the record survives a restart without a second warning; an anchor
that becomes readable is reported once and cleared; the anchors listing and the board mark it; the rulebook's import line.

Receivers that fail at start (the box booted with the network down, and the receivers stayed off until a manual restart):
a receiver whose start fails with a network-type error is retried in the background, with a 5 s backoff doubling to 5 min and
jitter below the cap, until it reports ready, while the others start normally; its hook routes answer 503 with a Retry-After
(404 for an unknown route, and for a receiver that failed for good); each attempt logs one line, the recovery says how many
tries and how many hook requests were refused; a missing credential, a refused token or a start that returns unready is tried
once and kept as before; what counts as a network error; gh's "error connecting" is one, a refused credential is not.

    tests/run-suite unreadable        → exit 0 / 1"""
import json, os, re, sys, pathlib, tempfile, logging, types, datetime
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="unreadtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                 ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1   # the fixtures' subjects
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")   # the session and machine state is a fixture under fleet/
S, A, B = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"
for d in ("store/a", "fleet/a", "state/anchor-hub", "secrets", "touch", "repo"): (T / d).mkdir(parents=True)
(T / "fleet/a/sessions.json").write_text(json.dumps({S: {"name": "work-osprey", "machine": "a", "url": "", "seen": "x"}, A: {"name": "work-osprey-main", "machine": "a", "url": "", "seen": "x"},
                                                      B: {"name": "home-beta", "machine": "a", "url": "", "seen": "x"}}))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
page = lambda name, sess: {"title": name, "name": name, "org": "home", "tags": [], "type": "project", "session": sess, "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": f"https://example.invalid/{name}"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": page("Alpha", "work-osprey"), "projects/beta": page("Beta", "home-beta")}}))
def item(i, proj, owner): (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": owner, "project": proj}, "updated": 1.0}))
item(1, "projects/alpha", A); item(3, "projects/beta", A)                      # beta is no pilot: its anchor reaches the keeper and the item's owner
GM, DR, SL, OK = "https://mail.google.com/mail/u/0/#all/1111111111111111", "https://docs.google.com/document/d/AAAAAAAAAAAAAAAAAAAAAAAAA", "https://x.slack.com/archives/C0000000002", "https://x.slack.com/archives/C0000000001"
(T / "store/anchors.json").write_text(json.dumps({
    "projects/alpha": [{"url": OK, "items": None, "added": 1, "by": "t"}, {"url": GM, "items": ["a1"], "added": 1, "by": "t"}],
    "projects/beta": [{"url": DR, "items": None, "added": 1, "by": "t"}, {"url": SL, "items": None, "added": 1, "by": "t"}]}))
(T / "store/next-id").write_text("10")
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

from stackshot.anchors.anchorhub import core
from stackshot.anchors import anchors as anc; from stackshot.router import routing
T0 = 1790798400.0                      # 2026-10-01 00:00 in the instance timezone (Asia/Dubai, UTC+4: 2026-09-30 20:00 UTC)
clock = types.SimpleNamespace(t=T0)
core.time = types.SimpleNamespace(time=lambda: clock.t, sleep=lambda s: None)
calls = []; state = {"gmail": "refused", "drive": "down", "slack2": "ok"}
def res_gmail(a):
    calls.append(a)
    return {"url": "", "unreadable": "the thread is in none of the mailboxes the hub reads (x@example.com)"} if state["gmail"] == "refused" else {"title": '"Meeting notes"', "url": GM}
def res_drive(a):
    calls.append(a)
    if state["drive"] == "down": return {"url": ""}                                 # the network: neither read nor refused
    return {"url": "", "unreadable": "none of the hub's Google accounts can open it (x@example.com); it has to be shared with one of them"}
def res_slack(a):
    calls.append(a)
    return {"title": "#general" if a.endswith("1") else "#beta", "url": "https://x.slack.com/archives/" + a[6:]}
def new_hub():
    h = core.Hub(); h.resolvers.update({"gmail": res_gmail, "drive": res_drive, "slack": res_slack})
    h.deliver = lambda anchor, session, text: out.append((round(clock.t - T0), session, text)); h.flush_queues = lambda: None
    return h
out = []; hub = new_hub()
def scan(t): clock.t = T0 + t; hub.rescan(); return json.load(open(core.STATUS))["anchors"]
gm, dr = "gmail:1111111111111111", "drive:AAAAAAAAAAAAAAAAAAAAAAAAA"

# ---- 1. the first refusal: recorded, not yet reported
st = scan(0)
check("first refusal: recorded with the reason, no notice yet", st[gm].get("unreadable", {}).get("tries") == 1 and "none of the mailboxes" in st[gm]["unreadable"]["why"] and not out, (st[gm], out))
check("a readable anchor is named and carries no mark", st["slack:C0000000001"]["label"] == "Slack #general" and "unreadable" not in st["slack:C0000000001"])
check("a network error is not a refusal", "unreadable" not in st[dr] and not st[dr].get("title"), st[dr])
n = len(calls); scan(30)
check("not asked again before a minute has passed", calls[n:].count(gm) == 0 and calls[n:].count(dr) == 1, calls[n:])     # the unnamed Drive file is tried each pass, as ever

# ---- 2. still refused a minute later: one notice, recorded for the router to rule (every project is the router's since), delivered to no session
from stackshot.router import router_live as live
st = scan(60)
w = [o for o in out if "Gmail anchor" in o[2]]
log = routing.read("projects/alpha")
check("second refusal: one warning", len(log) == 1 and st[gm]["unreadable"]["tries"] == 2 and st[gm]["unreadable"].get("warned"), (log, st[gm]))
check("…held for the router: nothing is delivered to the project's keeper or to the item's owner", not w and log[0].get("live") is True and not log[0].get("to"), (w, log))
txt0 = live.stashed(log[0]["id"]) or ""
check("…that says why, what follows and what to do (the notice's full text is kept for the router)", "anchor-hub cannot read it: the thread is in none of the mailboxes the hub reads (x@example.com). No notice will come from it" in txt0
      and "remove the anchor and add it again" in txt0 and txt0.startswith("[anchor] Gmail anchor of projects/alpha: ") and f"→ {GM}" in txt0, txt0)
check("…recorded in the routing log with its id and whom the anchor is for", log[0]["who"] == "anchor-hub" and log[0]["anchor"] == gm and log[0]["pilot"] is True and log[0]["id"], log)

# ---- 3. the tries thin out, and nothing is said twice
asked = []
for t in range(90, 8 * 3600, 30):
    n = len(calls); scan(t)
    if gm in calls[n:]: asked.append(t)
check("asked again at doubling intervals: 2, 4, 8 … minutes after the last try", asked[:6] == [180, 420, 900, 1860, 3780, 7620], asked)
check("…never more often than every 6 hours in the end", all(b - a2 <= 21600 for a2, b in zip(asked, asked[1:])) and len(asked) <= 9, asked)
check("one warning in eight hours, not one per try", len(routing.read("projects/alpha")) == 1 and not [o for o in out if "Gmail anchor" in o[2]], (routing.read("projects/alpha"), out))

# ---- 4. a refusal on another project (home-beta's page, which has no agent of its own): held for the router too, not delivered to its keeper
state["drive"] = "refused"; t = 8 * 3600; scan(t); st = scan(t + 60)
d = [o for o in out if "Drive anchor" in o[2]]
lb = routing.read("projects/beta")
check("another project: one warning, held for the router, delivered to nobody (the keeper and the item's owner get nothing)", len(lb) == 1 and not d and lb[0].get("live") is True and lb[0]["anchor"] == dr
      and (live.stashed(lb[0]["id"]) or "").endswith(f"→ {DR}"), (lb, d))

# ---- 5. a restart keeps the record: no second warning, no early try
hub = new_hub(); n = len(calls); n_out = len(out); st = scan(t + 90)
check("after a restart the anchor is still marked and was not warned about again", st[gm].get("unreadable", {}).get("warned") and len(out) == n_out and gm not in calls[n:], (st[gm], out[n_out:], calls[n:]))

# ---- 6. the listing and the board say so
txt = anc.fmt(anc.load()["projects/alpha"], st)
check("anchors listing: the readable one by name, the other marked with the reason", '— Slack #general' in txt and re.search(r"UNREADABLE by anchor-hub since 20\d\d-\d\d-\d\d \d\d:\d\d:\d\d \+04: the thread is in none of the mailboxes", txt), txt)
from stackshot.web.ui import render as ui_render
now = datetime.datetime.fromtimestamp(clock.t, core.ZONE)
try:
    b = ui_render.Board(str(T / "store"), now=now)
    state_, parts = b.watch("projects/alpha"); pagehtml = b.routing_html("projects/alpha")
    check("board: the watch light is red and says why", state_ == "bad" and any("1 unreadable by anchor-hub" in x for x in parts), (state_, parts))
    check("board: the routing page marks the anchor with the reason", '>unreadable</span>' in pagehtml and "none of the mailboxes" in pagehtml, pagehtml[:300])
except Exception as e:
    check("board renders", False, repr(e))

# ---- 7. it becomes readable: said once, mark gone
state["gmail"] = "ok"; n_out = len(out)
for dt in range(0, 7 * 3600, 600): st = scan(t + 120 + dt)
c = [n for n in routing.read("projects/alpha") if n["id"] != log[0]["id"]]
check("readable again: one notice that the warning no longer holds (held for the router), mark cleared, name known", len(c) == 1 and c[0].get("live") is True and 'anchor-hub can read it now (Gmail "Meeting notes")' in (live.stashed(c[0]["id"]) or "")
      and not [o for o in out[n_out:] if "Gmail anchor" in o[2]] and "unreadable" not in st[gm] and st[gm]["label"] == 'Gmail "Meeting notes"', (c, st[gm]))

# ---- 8. an event from an unreadable anchor brings its next try forward
state["drive"] = "refused"; st = json.load(open(core.STATUS))["anchors"]
hub.bindings = core.load_bindings(); hub.event(dr, {"title": '"Deck"', "who": "Dana", "text": 'changed "Deck"', "url": DR, "ts": "1"}, kind="drive")
check("an event from it: asked again at the next pass", hub.status["anchors"][dr]["unreadable"]["next"] == 0, hub.status["anchors"][dr])

# ---- 9. the rulebook's import line (_wt_rules._rules_source)
from stackshot.web import server
from stackshot.core import config as _cfg
from stackshot.web.tools import rules as _wt_rules
R = T / "rules"; R.mkdir()
(R / "A.md").write_text("<!-- header -->\n# Rules\n\n## One\n\n- a rule\n\n@B.md\n@missing.md\nnot an @import.md line\n", encoding="utf-8")
(R / "B.md").write_text("# Agent rules\n\nOne sentence.\n\n<!-- surface: cli -->\n## CLI only\n\n- hidden from Cowork\n\n## Two\n\n- another rule\n- a cli bullet <!-- cli -->\n@C.md\n", encoding="utf-8")
(R / "C.md").write_text("third level text\n", encoding="utf-8")
src = _wt_rules._rules_source(R / "A.md")
check("rules: an import line is replaced by the file next to it", "## Two\n\n- another rule" in src and "@B.md" not in src, src)
check("rules: a missing file leaves its line, other text is untouched, an import inside an imported file is expanded too", "@missing.md\nnot an @import.md line\n" in src and "@C.md" not in src and "- a cli bullet <!-- cli -->\nthird level text\n@missing.md" in src and src.endswith("line\n"), src)
(R / "plain.md").write_text("# Rules\n\n- a rule\n", encoding="utf-8")
check("rules: a file with no import reads back byte for byte", _wt_rules._rules_source(R / "plain.md") == "# Rules\n\n- a rule\n")
_real_cfg_path = _cfg.path; _cfg.path = lambda *k: (R / "A.md") if k == ("paths", "rules") else _real_cfg_path(*k)
cw = _wt_rules._rules_text("cowork"); full = _wt_rules._rules_text("full")
check("rules: the Cowork filter runs on the expanded text", "- another rule" in cw and "hidden from Cowork" not in cw and "a cli bullet" not in cw and "<!-- header -->" not in cw, cw[-400:])
check("rules: profile full is the whole expanded text", "hidden from Cowork" in full and "- another rule" in full and "@B.md" not in full, full)
# nested imports: followed from the importing file's directory, up to _IMPORT_DEPTH_MAX levels, a file already being expanded is not expanded again
def _old_source(p):                                       # the one-level reading the first-level-only case must still match byte for byte
    out = []
    for ln in p.read_text(encoding="utf-8").split("\n"):
        m = _wt_rules._IMPORT.match(ln)
        if m:
            try:
                out.append((p.parent / os.path.expanduser(m.group(1))).read_text(encoding="utf-8").rstrip("\n")); continue
            except Exception:
                pass
        out.append(ln)
    return "\n".join(out)
N = R / "nest"; (N / "sub").mkdir(parents=True)
(N / "demo-rules.md").write_text("# Demo\n\n## Top\n\n- top rule\n\n@demo-two.md\n\n## End\n\n- end rule\n", encoding="utf-8")
(N / "demo-two.md").write_text("## Two\n\n- two rule\n@sub/demo-three.md\n", encoding="utf-8")
(N / "sub" / "demo-three.md").write_text("<!-- host: machines -->\n## Three\n\n- three rule, machines only\n@demo-four.md\n", encoding="utf-8")   # relative to sub/, not to the first file
(N / "sub" / "demo-four.md").write_text("## Four\n\n- four rule\n", encoding="utf-8")
n2 = _wt_rules._rules_source(N / "demo-two.md")
check("rules nested: a two-level chain is fully expanded", "- three rule, machines only" in n2 and "@sub/demo-three.md" not in n2 and "- four rule" in n2 and "@demo-four.md" not in n2, n2)
n3 = _wt_rules._rules_source(N / "demo-rules.md")
check("rules nested: a three-level chain is fully expanded, each path from its importing file's directory, order kept",
      all(x in n3 for x in ("- top rule", "- two rule", "- three rule, machines only", "- four rule", "- end rule")) and not re.search(r"^@", n3, re.M)
      and n3.index("- top rule") < n3.index("- two rule") < n3.index("- three rule") < n3.index("- four rule") < n3.index("- end rule"), n3)
_cfg.path = lambda *k: (N / "demo-rules.md") if k == ("paths", "rules") else _real_cfg_path(*k)
ncw = _wt_rules._rules_text("cowork"); nfull = _wt_rules._rules_text("full")
check("rules nested: a section marker in a nested file filters its section on Cowork, as in a first-level file (the sections around it stay)",
      "## Three" not in ncw and "three rule" not in ncw and "- two rule" in ncw and "## End" in ncw
      and "## Three" in nfull and "<!-- host: machines -->" in nfull, ncw[-300:])
(N / "demo-a.md").write_text("# A\n\n- rule a\n@demo-b.md\n", encoding="utf-8")
(N / "demo-b.md").write_text("- rule b\n@demo-a.md\n@demo-self.md\n", encoding="utf-8")
(N / "demo-self.md").write_text("- rule self\n@demo-self.md\n", encoding="utf-8")
nc = _wt_rules._rules_source(N / "demo-a.md")
check("rules nested: a cycle ends, each file once, the line that would loop stays as a plain line", nc.count("- rule a") == 1 and nc.count("- rule b") == 1 and nc.count("- rule self") == 1
      and nc.count("@demo-a.md") == 1 and nc.count("@demo-self.md") == 1, nc)
(N / "demo-twice.md").write_text("@demo-leaf.md\n@demo-leaf.md\n", encoding="utf-8"); (N / "demo-leaf.md").write_text("- leaf rule\n", encoding="utf-8")
check("rules nested: the same file imported twice (not a cycle) is expanded both times", _wt_rules._rules_source(N / "demo-twice.md").count("- leaf rule") == 2, _wt_rules._rules_source(N / "demo-twice.md"))
D = _wt_rules._IMPORT_DEPTH_MAX
for i in range(D + 3): (N / f"demo-d{i}.md").write_text(f"- level {i}\n" + (f"@demo-d{i + 1}.md\n" if i < D + 2 else ""), encoding="utf-8")
nd = _wt_rules._rules_source(N / "demo-d0.md")
check("rules nested: a chain deeper than the cap stops at the cap without error, the next import line stays",
      isinstance(D, int) and 2 <= D <= 6 and all(f"- level {i}\n" in nd for i in range(D + 1)) and f"- level {D + 1}" not in nd and f"@demo-d{D + 1}.md" in nd, (D, nd))
(N / "demo-m1.md").write_text("- m1\n@demo-m2.md\n", encoding="utf-8"); (N / "demo-m2.md").write_text("- m2\n@demo-gone.md\n- m2 after\n", encoding="utf-8")
nm = _wt_rules._rules_source(N / "demo-m1.md")
check("rules nested: a missing nested file leaves its line, as a missing first-level file does", nm == "- m1\n- m2\n@demo-gone.md\n- m2 after\n", repr(nm))
(N / "demo-flat.md").write_text("# F\n\n- f rule\n@demo-leaf.md\n@demo-gone.md\n\n## G\n", encoding="utf-8")
check("rules nested: a rulebook whose imports import nothing renders byte for byte as the one-level reading did", _wt_rules._rules_source(N / "demo-flat.md") == _old_source(N / "demo-flat.md")
      and _wt_rules._rules_source(R / "plain.md") == _old_source(R / "plain.md"), _wt_rules._rules_source(N / "demo-flat.md"))
# nested imports stay inside the first file's tree (after symlinks), and one render has a budget (files, characters, one file's size)
G = R / "guard"; (G / "tree" / "sub" / "deep").mkdir(parents=True); (G / "outside").mkdir(); (G / "home").mkdir()
(G / "outside" / "demo-secret.md").write_text("SECRET OUTSIDE\n", encoding="utf-8"); (G / "demo-parent.md").write_text("SECRET PARENT\n", encoding="utf-8")
(G / "home" / "demo-home.md").write_text("SECRET HOME\n", encoding="utf-8")
(G / "tree" / "demo-inside.md").write_text("INSIDE OK\n", encoding="utf-8")
def _gsrc(top_lines, **files):                            # a first file importing mid.md, which holds top_lines (depth 2); returns the expanded text
    for n in ("demo-mid.md", "demo-top.md"): (G / "tree" / n).unlink(missing_ok=True)
    (G / "tree" / "demo-mid.md").write_text(top_lines, encoding="utf-8"); (G / "tree" / "demo-top.md").write_text("TOP\n@demo-mid.md\n", encoding="utf-8")
    return _wt_rules._rules_source(G / "tree" / "demo-top.md")
x = _gsrc("@../outside/demo-secret.md\n@../demo-parent.md\n@demo-inside.md\n")
check("rules guard: a nested import with .. out of the tree stays a plain line (one inside the tree still expands)", "SECRET" not in x and "@../outside/demo-secret.md" in x and "@../demo-parent.md" in x and "INSIDE OK" in x, x)
(G / "tree" / "sub" / "demo-b.md").write_text("B\n@deep/demo-c.md\n", encoding="utf-8"); (G / "tree" / "sub" / "demo-sib.md").write_text("SIB OK\n", encoding="utf-8")
(G / "tree" / "sub" / "deep" / "demo-c.md").write_text("C\n@../demo-sib.md\n@../../../outside/demo-secret.md\n", encoding="utf-8")
(G / "tree" / "demo-top.md").write_text("TOP\n@sub/demo-b.md\n", encoding="utf-8")
x = _wt_rules._rules_source(G / "tree" / "demo-top.md")
check("rules guard: a .. that climbs out of the tree only at depth 3 stays plain, one that stays inside expands", "SECRET" not in x and "@../../../outside/demo-secret.md" in x and "SIB OK" in x, x)
x = _gsrc(f"@{G}/outside/demo-secret.md\n@{G}/tree/demo-inside.md\n")
check("rules guard: a nested absolute path stays plain, even one inside the tree", "SECRET" not in x and "INSIDE OK" not in x and f"@{G}/tree/demo-inside.md" in x, x)
_home = os.environ.get("HOME")
try:
    os.environ["HOME"] = str(G / "home")
    x = _gsrc("@~/demo-home.md\n")
    check("rules guard: a nested ~ path stays plain", "SECRET HOME" not in x and "@~/demo-home.md" in x, x)
    (G / "tree" / "demo-top.md").write_text("TOP\n@~/demo-home.md\n", encoding="utf-8")
    check("rules guard: a first-file ~ path still expands, as before", "SECRET HOME" in _wt_rules._rules_source(G / "tree" / "demo-top.md"))
finally:
    if _home is None: os.environ.pop("HOME", None)
    else: os.environ["HOME"] = _home
(G / "tree" / "demo-top.md").write_text("TOP\n@../outside/demo-secret.md\n", encoding="utf-8")
check("rules guard: a first-file .. path still expands, as before", "SECRET OUTSIDE" in _wt_rules._rules_source(G / "tree" / "demo-top.md"))
(G / "tree" / "demo-link-out.md").symlink_to(G / "outside" / "demo-secret.md"); (G / "tree" / "demo-linkdir").symlink_to(G / "outside", target_is_directory=True)
(G / "tree" / "demo-link-in.md").symlink_to(G / "tree" / "demo-inside.md")
x = _gsrc("@demo-link-out.md\n@demo-linkdir/demo-secret.md\n@demo-link-in.md\n")
check("rules guard: a symlinked file or directory pointing outside stays plain, a symlink pointing inside expands", "SECRET" not in x and "@demo-link-out.md" in x and "@demo-linkdir/demo-secret.md" in x and "INSIDE OK" in x, x)
# the budget
F = R / "fan"; F.mkdir()
for lvl in range(1, 5):
    for i in range(20): (F / f"demo-f{lvl}-{i}.md").write_text(f"- f{lvl}-{i}\n" + ("".join(f"@demo-f{lvl + 1}-{j}.md\n" for j in range(20)) if lvl < 4 else ""), encoding="utf-8")
(F / "demo-top.md").write_text("# Fan\n" + "".join(f"@demo-f1-{j}.md\n" for j in range(20)), encoding="utf-8")
_opened = []; _real_open = open
_wt_rules.open = lambda f, *a, **k: (_opened.append(str(f)), _real_open(f, *a, **k))[1]
try:
    fx = _wt_rules._rules_source(F / "demo-top.md")
finally:
    del _wt_rules.open
check("rules budget: a 20-by-20 fan-out at depth 4 reads at most 64 files and returns a bounded text", 20 < len(_opened) <= 64 and len(fx) < _wt_rules._IMPORT_TOTAL_MAX + len((F / "demo-top.md").read_text()), (len(_opened), len(fx)))
check("rules budget: the three limits are named constants", (_wt_rules._IMPORT_FILES_MAX, _wt_rules._IMPORT_TOTAL_MAX, _wt_rules._IMPORT_FILE_MAX) == (64, 512 * 1024, 256 * 1024))
(F / "demo-big.md").write_text("- big\n" + "x" * (_wt_rules._IMPORT_FILE_MAX + 10), encoding="utf-8"); (F / "demo-fits.md").write_text("- fits\n" + "x" * (_wt_rules._IMPORT_FILE_MAX - 10), encoding="utf-8")
(F / "demo-sizes.md").write_text("@demo-big.md\n@demo-fits.md\n", encoding="utf-8")
x = _wt_rules._rules_source(F / "demo-sizes.md")
check("rules budget: a file over the per-file limit stays a plain line, one under it expands", x.startswith("@demo-big.md\n- fits\n") and "- big" not in x, x[:60])
for i in range(10): (F / f"demo-h{i}.md").write_text(f"- h{i}\n" + "y" * 100_000, encoding="utf-8")
(F / "demo-total.md").write_text("".join(f"@demo-h{i}.md\n" for i in range(10)), encoding="utf-8")
x = _wt_rules._rules_source(F / "demo-total.md")
check("rules budget: the characters of imported text in all are bounded, the rest stay plain lines", 3 <= x.count("- h") <= 5 and len(x) < _wt_rules._IMPORT_TOTAL_MAX + 200 and x.count("@demo-h") == 10 - x.count("- h"), (len(x), x.count("- h")))
for lvl in range(1, 5): (F / f"demo-e{lvl}.md").write_text((f"@demo-e{lvl + 1}.md\n@demo-e{lvl + 1}.md\n" if lvl < 4 else "- leaf\n"), encoding="utf-8")
(F / "demo-dia.md").write_text("@demo-e1.md\n@demo-e1.md\n", encoding="utf-8")
x = _wt_rules._rules_source(F / "demo-dia.md")
check("rules budget: a 4-level binary diamond still expands in full", x.count("- leaf") == 16 and "@" not in x, x)
(F / "demo-fence.md").write_text("```\n@demo-leaf-fence.md\n```\n", encoding="utf-8"); (F / "demo-leaf-fence.md").write_text("FENCED IMPORT\n", encoding="utf-8")
(F / "demo-fence-top.md").write_text("@demo-fence.md\n", encoding="utf-8")
check("rules: an import line inside a code fence is expanded like any other (at the first level and nested)", "FENCED IMPORT" in _wt_rules._rules_source(F / "demo-fence.md") and "FENCED IMPORT" in _wt_rules._rules_source(F / "demo-fence-top.md"))
# a rejected file costs one read attempt, once; a sibling directory that shares the rulebook directory's name prefix is outside it; sizes count characters; the exact edges of each limit
import time as _time
def _wr(path, text): path.write_text(text, encoding="utf-8")
def _opens(fn):                                           # (result, the files the render opened)
    got = []; real = open
    _wt_rules.open = lambda f, *a, **k: (got.append(str(f)), real(f, *a, **k))[1]
    try: return fn(), got
    finally: del _wt_rules.open
H = R / "hot"; H.mkdir()
_wr(H / "demo-big.md", "z" * (_wt_rules._IMPORT_FILE_MAX + 1))
for n in ("demo-mid1.md", "demo-mid2.md"): _wr(H / n, "@demo-big.md\n" * (_wt_rules._IMPORT_FILE_MAX // 13) + "@demo-big.md\n"[: _wt_rules._IMPORT_FILE_MAX % 13])
_mid = (H / "demo-mid1.md").read_text(); assert len(_mid) == _wt_rules._IMPORT_FILE_MAX, len(_mid)
_wr(H / "demo-top.md", "@demo-mid1.md\n@demo-mid2.md\n")
_t0 = _time.monotonic(); (hx, hopen) = _opens(lambda: _wt_rules._rules_source(H / "demo-top.md")); _dt = _time.monotonic() - _t0
check("rules budget: lines naming one over-limit file read it once, not once per line (65k such lines finish in seconds, output unchanged)",
      _dt < 3 and len(hopen) <= 4 and hx == _mid.rstrip("\n") + "\n" + _mid.rstrip("\n") + "\n", (_dt, len(hopen)))
for i in range(64):
    os.link(H / "demo-big.md", H / f"demo-bigl{i}.md")
_wr(H / "demo-good.md", "- good rule\n")
_wr(H / "demo-att.md", "".join(f"@demo-bigl{i}.md\n" for i in range(64)) + "@demo-good.md\n")
(ax, aopen) = _opens(lambda: _wt_rules._rules_source(H / "demo-att.md"))
check("rules budget: every read attempt counts toward the file limit, a refused file too (the 65th attempt is not made)", len(aopen) == 64 and "- good rule" not in ax and ax.endswith("@demo-good.md\n"), (len(aopen), ax[-30:]))
# a sibling directory with the same name prefix
PX = R / "prefix"; (PX / "claude").mkdir(parents=True); (PX / "claude-evil").mkdir(); (PX / "claude" / "sub").mkdir()
_wr(PX / "claude-evil" / "demo-x.md", "EVIL SIBLING\n")
(PX / "claude" / "demo-link-evil.md").symlink_to(PX / "claude-evil" / "demo-x.md")
_wr(PX / "claude" / "demo-top.md", "TOP\n@demo-mid.md\n")
_wr(PX / "claude" / "demo-mid.md", "@../claude-evil/demo-x.md\n@sub/../../claude-evil/demo-x.md\n@demo-link-evil.md\n@demo-deep.md\n")
_wr(PX / "claude" / "demo-deep.md", "@sub/../../claude-evil/demo-x.md\n@sub/../demo-ok.md\n"); _wr(PX / "claude" / "demo-ok.md", "STAYS INSIDE\n")
px = _wt_rules._rules_source(PX / "claude" / "demo-top.md")
check("rules guard: a sibling directory sharing the rulebook directory's name prefix is outside it (.., a .. at depth 3, a symlink)", "EVIL" not in px and px.count("claude-evil/demo-x.md") == 3 and "@demo-link-evil.md" in px and "STAYS INSIDE" in px, px)
# characters, not bytes
K = "\ud55c"; assert len(K.encode()) == 3
_wr(H / "demo-kfit.md", K * _wt_rules._IMPORT_FILE_MAX); _wr(H / "demo-kover.md", K * (_wt_rules._IMPORT_FILE_MAX + 1))
_wr(H / "demo-ktop.md", "@demo-kfit.md\n@demo-kover.md\n")
kx = _wt_rules._rules_source(H / "demo-ktop.md")
check("rules budget: the limits count characters, not bytes (a file of 262144 three-byte characters expands, 262145 does not)", kx.startswith(K * 10) and kx.count(K) == _wt_rules._IMPORT_FILE_MAX and kx.endswith("\n@demo-kover.md\n"), (len(kx), kx[-20:]))
# edges: the per-file limit, the total, the count of files
E = R / "edge"; E.mkdir()
def _sized(name, n, tag): _wr(E / name, tag + "x" * (n - len(tag)))
_F, _T = _wt_rules._IMPORT_FILE_MAX, _wt_rules._IMPORT_TOTAL_MAX
_sized("demo-fe.md", _F, "QE"); _sized("demo-fo.md", _F + 1, "QO"); _wr(E / "demo-fu.md", "QU" + "x" * (_F - 3))
_wr(E / "demo-ftop.md", "@demo-fu.md\n@demo-fe.md\n@demo-fo.md\n")
fx = _wt_rules._rules_source(E / "demo-ftop.md")
check("rules budget: per-file edge: one under and exactly at the limit expand, one over does not", fx.startswith("QU") and "\nQE" in fx and "QO" not in fx and fx.endswith("\n@demo-fo.md\n"), (len(fx), fx[-20:]))
_sized("demo-ta.md", _F, "QA"); _sized("demo-tb.md", _F - 1, "QB"); _sized("demo-tc.md", _F, "QC"); _sized("demo-td.md", 1, "Q")
_wr(E / "demo-t1.md", "@demo-ta.md\n@demo-tb.md\n"); _wr(E / "demo-t2.md", "@demo-ta.md\n@demo-tc.md\n"); _wr(E / "demo-t3.md", "@demo-ta.md\n@demo-tc.md\n@demo-td.md\n")
t1, t2, t3 = (_wt_rules._rules_source(E / f"demo-t{i}.md") for i in (1, 2, 3))
check("rules budget: total edge: one character under and exactly at the limit expand, one over does not",
      "QB" in t1 and "@demo-tb.md" not in t1 and "QC" in t2 and "@demo-tc.md" not in t2 and "QC" in t3 and t3.endswith("@demo-td.md\n") and _F * 2 == _T, (len(t1), len(t2), t3[-20:]))
for i in range(65): _wr(E / f"demo-c{i}.md", f"- c{i}\n")
_wr(E / "demo-ctop.md", "".join(f"@demo-c{i}.md\n" for i in range(65)))
cx = _wt_rules._rules_source(E / "demo-ctop.md")
check("rules budget: file-count edge: the 64th file expands, the 65th stays a plain line", "- c63\n" in cx and "- c64" not in cx and cx.endswith("@demo-c64.md\n"), cx[-40:])
# a second person's RULES.md: plain markdown, no surface markers, no import, no header comment: served whole, both profiles
body = "# Our rules\n\n## Board\n\n- one item per deliverable\n- a page per project\n\n## Pages\n\n- edit the file, commit and push\n"
(R / "nomarkers.md").write_text(body, encoding="utf-8")
_cfg.path = lambda *k: (R / "nomarkers.md") if k == ("paths", "rules") else _real_cfg_path(*k)
cw2 = _wt_rules._rules_text("cowork"); full2 = _wt_rules._rules_text("full")
_pre = _wt_rules._cowork_preamble()
check("rules: the Cowork preamble sends a page edit to edit_page, put_page only for a whole rewrite",
      "then `edit_page` with `expected_revision` and `edits: [{old_text, new_text}]`; `put_page` only for a whole rewrite" in _pre
      and "`get_page` then `put_page`" not in _pre, _pre[-1200:])
check("rules: the Cowork preamble names no retired page script and no push override",
      "example-page.sh" not in _pre and "EXAMPLE_PAGE_PUSH" not in _pre, _pre[-1200:])
check("rules: a marker-less file is served whole (cowork: after the preamble)", cw2.startswith(_wt_rules._cowork_preamble()) and cw2.endswith(body.strip() + "\n"), cw2[-300:])
check("rules: a marker-less file under profile full is the file itself", full2 == body, full2)
tool = getattr(_wt_rules.stackshot_rules, "fn", _wt_rules.stackshot_rules)        # the decorated tool's own function
check("rules: the rules tool serves it, both profiles", tool() == cw2 and tool("full") == body, tool()[-200:])
# rulebook parts ([paths] rules_parts): skill files appended after the body, cloud and Cowork get no hooks to load them
check("rules: no parts configured (the default) = nothing appended", _cfg.paths("paths", "rules_parts") == [], _cfg.paths("paths", "rules_parts"))
P1, P2, PM = R / "one" / "SKILL.md", R / "two" / "SKILL.md", R / "gone" / "SKILL.md"
P1.parent.mkdir(); P2.parent.mkdir()
P1.write_text("---\nname: write-well\ndescription: how to write\n---\n\n# Writing\n\n- be plain (2026-10-20, an incident)\n\n<!-- surface: cli -->\n## Hooks only\n\n- hidden from Cowork\n\n## Last\n\n- a visible rule\n- a cli bullet <!-- cli -->\n", encoding="utf-8")
P2.write_text("# No frontmatter\n\n- second part\n", encoding="utf-8")
_parts = [P1]
_real_cfg_paths = _cfg.paths; _cfg.paths = lambda *k: list(_parts) if k == ("paths", "rules_parts") else _real_cfg_paths(*k)
cw3 = _wt_rules._rules_text("cowork"); full3 = _wt_rules._rules_text("full")
check("rules parts: appended after the body under their name, frontmatter gone", cw3.startswith(cw2) and "\n## Part: write-well\n\n# Writing\n" in cw3 and "description: how to write" not in cw3 and "name: write-well" not in cw3, cw3[-500:])
check("rules parts: the dated note is stripped in cowork, kept in full", "(2026-10-20" not in cw3 and "- be plain\n" in cw3 and "- be plain (2026-10-20, an incident)" in full3, cw3[-500:])
check("rules parts: a CLI-only section and bullet are dropped in cowork", "hidden from Cowork" not in cw3 and "a cli bullet" not in cw3 and "- a visible rule" in cw3, cw3[-500:])
check("rules parts: profile full keeps the whole part (markers and all) after the file", full3.startswith(body) and "## Part: write-well" in full3 and "hidden from Cowork" in full3 and "description:" not in full3, full3[-600:])
check("rules parts: the rules tool serves them too", tool() == cw3 and tool("full") == full3)
_parts = [P1, PM]
cw4 = _wt_rules._rules_text("cowork"); full4 = _wt_rules._rules_text("full")
check("rules parts: an unreadable part adds one not-readable line, in both profiles", cw4.count("(rulebook part gone/SKILL.md not readable:") == 1 and full4.count("(rulebook part gone/SKILL.md not readable:") == 1 and "## Part: write-well" in cw4, cw4[-300:])
_parts = [P2, P1]
cw5 = _wt_rules._rules_text("cowork")
check("rules parts: the list order is kept; a part with no frontmatter is named by its folder", cw5.index("## Part: two") < cw5.index("## Part: write-well") and "- second part" in cw5, cw5[-500:])
# the config value is not a list of strings: [] from config.paths, the rulebook is still served
_cfg.paths = _real_cfg_paths; _cfg_get = _cfg.get
for label, val in (("an int", 5), ("a bool", True), ("a dict", {str(P1): 1}), ("a list with non-strings", [5, None, str(P2), ""])):
    _cfg.get = lambda *k, _v=val, **kw: _v if k == ("paths", "rules_parts") else _cfg_get(*k, **kw)
    got = _cfg.paths("paths", "rules_parts")
    cw6 = _wt_rules._rules_text("cowork")
    want = [P2] if label.startswith("a list") else []
    check(f"rules parts: rules_parts as {label} reads as {len(want)} path(s) and the rulebook is served", got == want and cw6.startswith(cw2) and ("not readable" not in cw6) and len(tool("full")) >= len(body), (got, cw6[-200:]))
_cfg.get = _cfg_get
def _boom(*k): raise TypeError("boom")
_cfg.paths = _boom
cw7 = _wt_rules._rules_text("cowork"); full7 = _wt_rules._rules_text("full")
check("rules parts: a failing config read adds one note line, the rulebook is still served", cw7.startswith(cw2) and cw7.count("(rulebook parts not readable: boom)") == 1 and full7.startswith(body) and full7.count("(rulebook parts not readable: boom)") == 1, cw7[-200:])
# a BOM, an empty name, a quoted name
PB, PE, PQ = R / "bom" / "SKILL.md", R / "empty" / "SKILL.md", R / "quoted" / "SKILL.md"
for q in (PB, PE, PQ): q.parent.mkdir()
PB.write_bytes(b"\xef\xbb\xbf---\nname: bommed\n---\n\n- bom body\n")
PE.write_text("---\nname:   \ndescription: x\n---\n\n- empty name body\n", encoding="utf-8")
PQ.write_text("---\nname: \"it's quoted\"\n---\n\n- quoted body\n", encoding="utf-8")
_cfg.paths = lambda *k: [PB, PE, PQ] if k == ("paths", "rules_parts") else _real_cfg_paths(*k)
cw8 = _wt_rules._rules_text("cowork")
check("rules parts: a BOM file's frontmatter is stripped and its name used", "## Part: bommed\n\n- bom body" in cw8 and "---" not in cw8.split("## Part: bommed")[1], cw8[-400:])
check("rules parts: an empty name falls back to the folder name", "## Part: empty\n\n- empty name body" in cw8, cw8[-400:])
check("rules parts: only a matching pair of quotes is stripped", "## Part: it's quoted\n\n- quoted body" in cw8, cw8[-400:])
_cfg.paths = _real_cfg_paths
check("rules parts: a bare string in config counts as a one-item list", _cfg.paths("paths", "rules_parts", ) == [] and _cfg.paths("paths", "rules") == [_real_cfg_path("paths", "rules")])
_cfg.path = _real_cfg_path
# the section marker has two spellings, `<!-- surface: cli -->` and `<!-- host: machines -->`: both drop the next "## " section
_f = lambda t: _wt_rules._cowork_filter(t).rstrip("\n") + "\n"          # the filter joins lines without a final newline: compare with one
_OLD, _NEW = "<!-- surface: cli -->", "<!-- host: machines -->"
for _label, _m in (("the old marker", _OLD), ("the new marker", _NEW)):
    check(f"cowork filter: {_label} drops the next section up to the following heading, the marker line too",
          _f(f"# T\n\n{_m}\n## Hidden\n\n- gone\n\n## Shown\n\n- kept\n") == "# T\n\n## Shown\n\n- kept\n", _f(f"# T\n\n{_m}\n## Hidden\n\n- gone\n\n## Shown\n\n- kept\n"))
    check(f"cowork filter: {_label} with spaces or a tab around the line still counts",
          _f(f"  {_m}\t\n## Hidden\n- gone\n## Shown\n- kept\n") == "## Shown\n- kept\n", _f(f"  {_m}\t\n## Hidden\n- gone\n## Shown\n- kept\n"))
    check(f"cowork filter: text before the marker words on the same line is not {_label}",
          _f(f"see {_m} here\n## Shown\n- kept\n") == f"see {_m} here\n## Shown\n- kept\n", _f(f"see {_m} here\n## Shown\n- kept\n"))
    check(f"cowork filter: text after the marker words on the same line is not {_label}",
          _f(f"{_m} and more\n## Shown\n- kept\n") == f"{_m} and more\n## Shown\n- kept\n", _f(f"{_m} and more\n## Shown\n- kept\n"))
    check(f"cowork filter: {_label} as the last line only vanishes",
          _f(f"## Shown\n- kept\n{_m}") == "## Shown\n- kept\n", _f(f"## Shown\n- kept\n{_m}"))
    check(f"cowork filter: {_label} drops only the section right after it, not a later one",
          _f(f"{_m}\n## A\n- a\n## B\n- b\n## C\n- c\n") == "## B\n- b\n## C\n- c\n", _f(f"{_m}\n## A\n- a\n## B\n- b\n## C\n- c\n"))
check("cowork filter: the markers differ only by spelling: both in one file drop their own sections",
      _f(f"{_OLD}\n## A\n- a\n## B\n- b\n{_NEW}\n## C\n- c\n## D\n- d\n") == "## B\n- b\n## D\n- d\n", _f(f"{_OLD}\n## A\n- a\n## B\n- b\n{_NEW}\n## C\n- c\n## D\n- d\n"))
check("cowork filter: a marker followed directly by another marker still drops one section (the next)",
      _f(f"{_OLD}\n{_NEW}\n## A\n- a\n## B\n- b\n") == "## B\n- b\n" and _f(f"{_NEW}\n{_OLD}\n## A\n- a\n## B\n- b\n") == "## B\n- b\n", _f(f"{_NEW}\n{_OLD}\n## A\n- a\n## B\n- b\n"))
check("cowork filter: a bullet marker `<!-- cli -->` is unchanged: it drops its own line only, next to either section marker",
      _f(f"## A\n- keep\n- drop <!-- cli -->\n{_NEW}\n## B\n- b <!-- cli -->\n## C\n- c\n") == "## A\n- keep\n## C\n- c\n", _f(f"## A\n- keep\n- drop <!-- cli -->\n{_NEW}\n## B\n- b <!-- cli -->\n## C\n- c\n"))
check("cowork filter: other comments and a `<!-- host: other -->` line are not markers",
      _f("<!-- host: other -->\n<!-- note -->\n## Shown\n- kept\n") == "<!-- host: other -->\n<!-- note -->\n## Shown\n- kept\n")
# the same marker inside a rules part (a skill file): frontmatter dropped, the section dropped in cowork, kept in full
PN = R / "newmark" / "SKILL.md"; PN.parent.mkdir()
PN.write_text("---\nname: new-marker\ndescription: x\n---\n\n# Part\n\n- first\n\n<!-- host: machines -->\n## Machines only\n\n- hidden from Cowork\n\n## Last\n\n- a visible rule\n", encoding="utf-8")
_cfg.path = lambda *k: (R / "nomarkers.md") if k == ("paths", "rules") else _real_cfg_path(*k)
_cfg.paths = lambda *k: [PN] if k == ("paths", "rules_parts") else _real_cfg_paths(*k)
cw9 = _wt_rules._rules_text("cowork"); full9 = _wt_rules._rules_text("full")
check("rules parts: a part with the new marker drops that section in cowork, frontmatter gone, the next section kept",
      "## Part: new-marker\n\n# Part\n\n- first" in cw9 and "hidden from Cowork" not in cw9 and "Machines only" not in cw9 and "<!-- host: machines -->" not in cw9
      and "- a visible rule" in cw9 and "description: x" not in cw9, cw9[-400:])
check("rules parts: the same part under profile full keeps the section and the marker, frontmatter gone",
      "hidden from Cowork" in full9 and "<!-- host: machines -->" in full9 and "description:" not in full9, full9[-400:])
# the rulebook body itself, both spellings in one file
(R / "both.md").write_text(f"# Rules\n\n## One\n\n- one\n\n{_OLD}\n## Old only\n\n- old hidden\n\n{_NEW}\n## New only\n\n- new hidden\n\n## Two\n\n- two\n", encoding="utf-8")
_cfg.path = lambda *k: (R / "both.md") if k == ("paths", "rules") else _real_cfg_path(*k)
_cfg.paths = _real_cfg_paths
cw10 = _wt_rules._rules_text("cowork"); full10 = _wt_rules._rules_text("full")
check("rules: a rulebook with both markers drops both sections in cowork and keeps the rest; profile full keeps all",
      "- one" in cw10 and "- two" in cw10 and "old hidden" not in cw10 and "new hidden" not in cw10 and "old hidden" in full10 and "new hidden" in full10, cw10[-300:])
_cfg.path = _real_cfg_path; _cfg.paths = _real_cfg_paths

# ---- 10. a receiver whose start fails on the network is retried; its routes say 503 meanwhile (DNS down at boot)
# The hub's clock is the fake one above; this section needs the real one (the retry thread sleeps, the HTTP server answers).
import time as _real_time, socket, urllib.error, http.client, subprocess, threading
core.time = _real_time
logging.disable(logging.NOTSET)
class Grab(logging.Handler):
    def __init__(self): super().__init__(); self.recs = []
    def emit(self, r): self.recs.append((r.levelname, r.getMessage()))
grab = Grab(); core.log.addHandler(grab); core.log.propagate = False
DNS = urllib.error.URLError(socket.gaierror(-3, "Temporary failure in name resolution"))
TINY = (0.02, 0.08)                                        # s: the backoff in the tests (the flaky receiver gets 0.2 s, so its first state can be read)
n_try = {"flaky": 0, "mis": 0, "nocred": 0, "fine": 0}
def flaky(h):
    n_try["flaky"] += 1
    if n_try["flaky"] <= 2: raise DNS                      # a network-type error, twice
    h.hooks["/hook/flaky"] = lambda hd, body: (200, "ok flaky"); h.status["flaky"] = {"since": "x"}
def misconfigured(h): n_try["mis"] += 1; raise KeyError("SLACK_USER_TOKEN")        # a missing credential: waiting cannot fix it
def no_credentials(h): n_try["nocred"] += 1; core.log.warning("google: no tokens — run anchor-hub-google-auth.py")   # returns, never ready
def fine(h): n_try["fine"] += 1; h.hooks["/hook/fine"] = lambda hd, body: (200, "ok fine"); h.status["fine"] = {"since": "x"}
s = socket.socket(); s.bind(("127.0.0.1", 0)); core.HOOK_PORT = s.getsockname()[1]; s.close()     # never the live hub's port
h10 = core.Hub(); h10.hook_server(); h10.status["receivers"] = {}
th = core.start_receiver(h10, "flaky", flaky, lambda: bool(h10.status.get("flaky")), routes=("/hook/flaky",), backoff=(0.2, 0.4))
core.start_receiver(h10, "mis", misconfigured, lambda: True, routes=("/hook/mis",), backoff=TINY)
core.start_receiver(h10, "nocred", no_credentials, lambda: bool(h10.status.get("nocred")), backoff=TINY)
core.start_receiver(h10, "fine", fine, lambda: bool(h10.status.get("fine")), backoff=TINY)
R10 = h10.status["receivers"]
check("start: the failing receiver is off, marked as being retried, and the start call returned (a thread, not a wait)",
      th is not None and R10["flaky"]["ok"] is False and R10["flaky"].get("retrying") is True and "name resolution" in R10["flaky"]["error"], R10.get("flaky"))
check("start: the others started normally meanwhile", R10["fine"]["ok"] is True and n_try["fine"] == 1 and "/hook/fine" in h10.hooks, R10.get("fine"))
check("start: a missing credential is final, tried once, logged at ERROR, no retry state",
      R10["mis"]["ok"] is False and "retrying" not in R10["mis"] and n_try["mis"] == 1 and any(l == "ERROR" and "receiver mis: FAILED" in m for l, m in grab.recs), (R10["mis"], grab.recs))
check("start: a start that returns without being ready (no tokens) is final too: tried once, `did not report ready`",
      R10["nocred"]["ok"] is False and R10["nocred"]["error"] == "did not report ready" and "retrying" not in R10["nocred"] and n_try["nocred"] == 1, R10["nocred"])
def post(path):
    c = http.client.HTTPConnection("127.0.0.1", core.HOOK_PORT, timeout=5); c.request("POST", path, body=b"{}")
    r = c.getresponse(); out = (r.status, r.getheader("Retry-After"), r.read().decode()); c.close(); return out
# the retry thread may already have finished (tiny backoff), so look at the route before it can: hold it with a slow second receiver
gate = threading.Event(); n_try["slow"] = 0
def slow(h):
    n_try["slow"] += 1
    if not gate.is_set(): raise DNS
    h.hooks["/hook/slow"] = lambda hd, body: (200, "ok slow"); h.status["slow"] = {"since": "x"}
th2 = core.start_receiver(h10, "slow", slow, lambda: bool(h10.status.get("slow")), routes=("/hook/slow",), backoff=(0.05, 0.05))
b1, b2, b3 = post("/hook/slow"), post("/hook/slow"), post("/hook/slow")
check("route: 503 with a Retry-After while the receiver's start is being retried (not 404)", b1[0] == 503 and b1[1] and int(b1[1]) >= 1 and "slow" in b1[2], b1)
check("route: …every request, but one log line for the outage", b2[0] == 503 and b3[0] == 503 and len([1 for l, m in grab.recs if "/hook/slow" in m]) == 1, grab.recs)
check("route: an unknown route is still 404; a permanently failed receiver's route is 404 as before (today's behaviour)",
      post("/hook/nowhere")[0] == 404 and post("/hook/mis")[0] == 404 and post("/hook/mis")[1] is None, (post("/hook/nowhere"), post("/hook/mis")))
gate.set(); th2.join(10)
a1 = post("/hook/slow")
check("route: after the recovery it answers normally", a1[0] == 200 and a1[2] == "ok slow" and "/hook/slow" not in h10.retrying, (a1, h10.retrying))
check("recovery: one INFO line naming the tries and the 503s answered meanwhile",
      [m for l, m in grab.recs if l == "INFO" and "receiver slow: ready after" in m and "3 hook request(s) answered 503" in m], grab.recs)
th.join(10)
R10 = h10.status["receivers"]
check("retry: the flaky receiver, failing twice, ends up ready on the third try; its status carries no retry marks",
      n_try["flaky"] == 3 and R10["flaky"]["ok"] is True and R10["flaky"]["error"] is None and "retrying" not in R10["flaky"] and "/hook/flaky" not in h10.retrying, (n_try, R10["flaky"]))
check("route: …and its route answers 200", post("/hook/flaky")[0] == 200)
fl = [(l, m) for l, m in grab.recs if "receiver flaky" in m]
check("log: one line per attempt (two failures at WARNING, the recovery at INFO), none at ERROR",
      [l for l, m in fl] == ["WARNING", "WARNING", "INFO"] and "try 1" in fl[0][1] and "try 2" in fl[1][1] and "ready after 3 tries" in fl[2][1], fl)
check("the receivers listing says ok for the retried ones and records the permanent failures",
      h10.status["receivers_ok"] is False and R10["fine"]["ok"] and R10["slow"]["ok"] and not R10["mis"]["ok"], h10.status)
check("the others were tried once each: no retry of the permanent failures", (n_try["mis"], n_try["nocred"], n_try["fine"]) == (1, 1, 1), n_try)
# Retry-After: the time left to the next try; while an attempt is running (the next try is due), the current backoff step
h10.retrying["/hook/ra"] = {"receiver": "ra", "next": core.time.time() - 5, "step": 40, "refused": 0}
ra1 = post("/hook/ra")
h10.retrying["/hook/ra"].update(next=core.time.time() + 29.5, step=40)
ra2 = post("/hook/ra")
check("Retry-After: the current backoff step while an attempt is running, else the time left", ra1[0] == 503 and ra1[1] == "40" and ra2[1] == "30", (ra1, ra2))
h10.hook_srv.shutdown()

# the backoff itself: 5 s doubling to 5 min, jittered below the cap — a recording stand-in for the wait, no sleeping
class Rec:
    def __init__(self): self.w = []
    def wait(self, t): self.w.append(t); return False
n_b = {"n": 0}
def down7(h):
    n_b["n"] += 1
    if n_b["n"] <= 8: raise DNS
    h.status["b"] = {"x": 1}
real_uniform = core.random.uniform
for label, uni, want in (("upper", lambda a, b: b, [5, 10, 20, 40, 80, 160, 300, 300]), ("lower", lambda a, b: a, [2.5, 5, 10, 20, 40, 80, 150, 150])):
    n_b["n"] = 0; core.random = types.SimpleNamespace(uniform=uni); rec = Rec(); hb = core.Hub(); hb.status["receivers"] = {}
    tb = core.start_receiver(hb, "b", down7, lambda: bool(hb.status.get("b")), stop=rec); tb.join(10)
    check(f"backoff ({label} jitter): 5 s doubling to the 5 min cap, never above it", rec.w == want and hb.status["receivers"]["b"]["ok"] is True, (rec.w, hb.status["receivers"]["b"]))
core.random = __import__("random")
wb = Rec(); n_b["n"] = 0; hb = core.Hub(); hb.status["receivers"] = {}
tb = core.start_receiver(hb, "b", down7, lambda: bool(hb.status.get("b")), stop=wb); tb.join(10)
check("backoff (real jitter): between half the step and the step, capped at 300 s", all(min(300, 5 * 2 ** i) / 2 <= w <= min(300, 5 * 2 ** i) for i, w in enumerate(wb.w)) and len(wb.w) == 8, wb.w)

# what is a network error and what is not
nm = lambda name, **kw: type(name, (Exception,), {})(**kw)
fake_http = lambda st: type("HttpError", (Exception,), {})("x");
def with_resp(st): e = Exception("x"); e.resp = types.SimpleNamespace(status=st); return e
def slack_e(code, st=200): e = type("SlackApiError", (Exception,), {})("x"); e.response = types.SimpleNamespace(get=lambda k, d=None: code if k == "error" else d, status_code=st); return e
check("transient: DNS, a timeout, a reset, a refused connection, google-auth's TransportError, httplib2's ServerNotFoundError, a 429 and a 503, a Slack rate limit",
      all(core.transient(e) for e in (DNS, TimeoutError(), ConnectionResetError(), ConnectionRefusedError(), nm("TransportError"), nm("ServerNotFoundError"),
                                      with_resp(429), with_resp(503), slack_e("ratelimited", 429), core.Transient("x"),
                                      urllib.error.HTTPError("u", 503, "x", {}, None), urllib.error.HTTPError("u", 429, "x", {}, None))))
check("permanent: a missing file or key, a refused or revoked token (401, 403, invalid_auth, RefreshError), a bug, a Permanent",
      not any(core.transient(e) for e in (FileNotFoundError("t"), PermissionError(), KeyError("K"), with_resp(401), with_resp(403), slack_e("invalid_auth"),
                                          urllib.error.HTTPError("u", 401, "x", {}, None), urllib.error.HTTPError("u", 403, "x", {}, None), urllib.error.HTTPError("u", 404, "x", {}, None),
                                          nm("RefreshError"), ValueError("bad json"), AttributeError("x"), core.Permanent("x"))))

# github: gh's own network message is a Transient (retried); a refused credential keeps today's way (off, a warning, no retry)
from stackshot.anchors.anchorhub import github as ghmod
class Done:
    def __init__(self, rc, err, out=""): self.returncode, self.stderr, self.stdout = rc, err, out
def gh_with(err, rc=1):
    ghmod.subprocess = types.SimpleNamespace(run=lambda *a, **k: Done(rc, err), TimeoutExpired=subprocess.TimeoutExpired)
    hg = core.Hub()
    try: ghmod.run(hg); return None, hg
    except Exception as e: return e, hg
e1, hg1 = gh_with("error connecting to api.github.com\ncheck your internet connection or https://githubstatus.com")
check("github: `error connecting to api.github.com` is a Transient, not `not authenticated`", isinstance(e1, core.Transient) and core.transient(e1) and not hg1.status.get("github"), e1)
e2, hg2 = gh_with("HTTP 401: Bad credentials (https://api.github.com/user)")
check("github: a refused credential returns as before: no exception, no retry, receiver off", e2 is None and not hg2.status.get("github"), (e2, hg2.status))
e3, hg3 = gh_with("To get started with GitHub CLI, please run:  gh auth login")
check("github: not logged in returns as before too", e3 is None and not hg3.status.get("github"), e3)

# slack: a connect() that fails closes its client, so a retry does not leave the first one's threads behind (stand-ins for slack_sdk: no Slack)
class FakeSock:
    made = []
    def __init__(self, app_token=None, web_client=None):
        self.socket_mode_request_listeners = []; self.closed = 0; self.n = len(FakeSock.made); FakeSock.made.append(self)
    def connect(self):
        if self.n == 0: raise DNS
    def close(self): self.closed += 1
    def is_connected(self): return True
class FakeWeb:
    def __init__(self, token=None): pass
    def auth_test(self): return {"user_id": "U1", "url": "https://x.slack.com/"}
for mod, attrs in (("slack_sdk", {"WebClient": FakeWeb}), ("slack_sdk.socket_mode", {"SocketModeClient": FakeSock}),
                   ("slack_sdk.socket_mode.request", {"SocketModeRequest": object}), ("slack_sdk.socket_mode.response", {"SocketModeResponse": object})):
    sys.modules[mod] = types.SimpleNamespace(**attrs)
os.makedirs(os.path.dirname(core.ENVF), exist_ok=True); open(core.ENVF, "w").write("SLACK_USER_TOKEN=not-a-token\nSLACK_APP_TOKEN=not-a-token\n")
from stackshot.anchors.anchorhub import slack as slackmod
hs = core.Hub(); hs.status["receivers"] = {}
ts = core.start_receiver(hs, "slack", slackmod.run, lambda: True, backoff=TINY); ts.join(10)
check("slack: the client whose connect() failed is closed once, the retry builds a new one and connects",
      len(FakeSock.made) == 2 and FakeSock.made[0].closed == 1 and FakeSock.made[1].closed == 0 and hs.status["receivers"]["slack"]["ok"] is True
      and hs.status["slack"]["connected"] is True, (len(FakeSock.made), [c.closed for c in FakeSock.made], hs.status["receivers"].get("slack")))
for mod in ("slack_sdk", "slack_sdk.socket_mode", "slack_sdk.socket_mode.request", "slack_sdk.socket_mode.response"): sys.modules.pop(mod, None)
core.log.removeHandler(grab); core.log.propagate = True; logging.disable(logging.WARNING)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": unreadable scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
