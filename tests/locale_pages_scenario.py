"""Scenario test for the second language on the search page, the CI runners page and the colour tool (stage 4 of the Korean UI: stackshot/web/ui/search.py, ui/runners.py, web/runners.py's
words, ui/colortool.py, and their keys in i18n_catalog.py): fixture data, the pages through Starlette's test client and straight from their builders, a fake GitHub, no live store, no network. People
and addresses are made up. The repository holds no text in another language, so the second language here is an ASCII TEST locale written into a temporary folder: every value is the English text
wrapped as `[x:...]`, and the date and age forms are ASCII templates. It proves the routing; it says nothing about any real translation. (tests/locale_scenario.py is the string table's own suite
and the home page's; this one is the pages that came after it.)

Covers:
  * the keys: every key these four sources ask for by its literal name exists in English; every key they build ("search.when." + k, "runners.st." + word, ...) exists for each value the code can build it from;
    every English value is a plain template; the English constants the code keeps (the search chips, kinds and states, the runners' Disable / Enable words, the colour tool's lines and strip) equal the
    catalog's English text, so a word cannot drift apart from its key;
  * English is unchanged: the search page (results, no hit, a short query, a date window, the unticked kinds) and the runners page and /runners.json for a person who never picked a language carry no marker and no
    script table override; the colour tool's settings are the English ones and its localizing snippet changes nothing while the page carries no table (run in node);
  * the second language: the search page and the runners page (cards, the machines' table, every state word, the Disable / Enable buttons, the as-of line, the placeholder, a GitHub error, the stale line) have
    every interface word in the test locale and none in English (every word left outside a marker is a fixture word: a runner, a branch, a repo, a title, a name), while item titles, project names, session
    names, runner names, branches and the reasons the data module gives stay as they are; the runners page's script reads its words with SST and holds no English message; the colour tool's snippet, run in node
    with a table, puts the test locale's lines and strip words into the settings (escaped), and with no table puts nothing;
  * a duration is routed (dur) while the stored snapshot's text is not (the English-only _dur), so a snapshot built in one request's language never holds another's words;
  * this file and the four sources hold no Hangul letter.

    tests/run-suite locale_pages        → exit 0 / 1"""
import datetime as dt, json, logging, os, pathlib, re, shutil, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="localepages-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
MINA, NOOR = "mina@example.org", "noor@example.org"
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai"),
                 ("fleet_names", f"{tmp}/session-names.tsv"), ("mode_file", f"{tmp}/ci/mode"), ("hold_file", f"{tmp}/ci/hold"), ("gate_file", f"{tmp}/ci/halted")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{MINA}", "{NOOR}"]'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^panel = true', 'panel = false'),
                 (r'(?m)^repos = \[\]', 'repos = ["salamander", "stackshot"]')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "secrets", "touch", "repo", "brain/projects", "locales", "ci"): (T / d).mkdir(parents=True)
A = "22222222-2222-4222-8222-222222222222"
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({A: {"name": "alpha-main", "machine": "a", "url": "", "seen": "x"}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": "https://example.invalid/alpha", "agents": {"alpha-main": "builds"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE lantern.\n\n<!-- timeline -->\n- 2026-02-19 | old\n")
now0 = time.time()
TITLE = "Quarterly lantern inventory"
(T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": f"[work] {TITLE}", "description": "- A thing\n- It lives here\n- Finished when it works", "status": "open",
    "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600, "metadata": {"owner": A, "project": "projects/alpha", "next": "the next step"}}))
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.core import config as _cfg
from stackshot.web import i18n, search, server
from stackshot.web import publish as _web_publish
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.auth import signin as _signin
from stackshot.web import runners as R
from stackshot.web.runners import RunnersError
from stackshot.web import search as WS
from stackshot.web.ui import colortool as CT
from stackshot.web.ui import render as r2
from stackshot.web.ui import runners as R2
from stackshot.web.ui import search as US
from starlette.testclient import TestClient
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
EN = i18n.EN
LOC = T / "locales"
MARK = lambda v: f"[x:{v}]"
DATE_AGE = {"date.full": "D<{wd}/{month}/{day}/{hm}>", "date.nohm": "D<{wd}/{month}/{day}>", "date.day": "{n}{ord}",
            "date.ord.1": "o1", "date.ord.2": "o2", "date.ord.3": "o3", "date.ord.n": "on",
            "age.now": "A<now>", "age.min": "A<{n}min>", "age.hour": "A<{n}hr>", "age.day": "A<{n}day>"}
DATE_AGE.update({f"date.wd.{i}": f"w{i}" for i in range(7)}); DATE_AGE.update({f"date.mon.{i}": f"m{i}" for i in range(1, 13)})
def test_locale(**over):
    d = {k: MARK(v) for k, v in EN.items()}; d.update(DATE_AGE); d.update(over); return d
def write_ko(d): (LOC / "ko.json").write_text(json.dumps(d), encoding="utf-8")
def set_dir(v):
    if v is None: _cfg.CFG.get("ui", {}).pop("locale_dir", None)
    else: _cfg.CFG.setdefault("ui", {})["locale_dir"] = str(v)
def reset_warned(): i18n._WARNED.clear(); i18n._LOADED.clear()

# ---- 1. the repository's text: no Hangul in this file or the four sources
HANGUL = re.compile("[%s-%s%s-%s%s-%s]" % tuple(chr(c) for c in (0xAC00, 0xD7A3, 0x3131, 0x318E, 0x1100, 0x11FF)))      # built from code points: this file holds no Hangul itself
SOURCES = ("stackshot/web/ui/search.py", "stackshot/web/ui/runners.py", "stackshot/web/runners.py", "stackshot/web/ui/colortool.py")
SRC = {rel: pathlib.Path(STACK, rel).read_text(encoding="utf-8") for rel in SOURCES}
check("this file and the four sources hold no Hangul letter", not HANGUL.search(pathlib.Path(__file__).read_text(encoding="utf-8")) and not [r for r, s in SRC.items() if HANGUL.search(s)])

# ---- 2. the keys
KEY_CALL = re.compile(r"""(?:\b_t|\b_i18n\.t|\bi18n\.t|\bSST)\(""")
KEY_LIT = re.compile(r"""\s*['"]([a-z0-9_.-]+)['"]""")
KEY_ELSE = re.compile(r"""\belse\s+['"]([a-z0-9_.-]+)['"]""")
def keys_in(text):
    """The keys a source asks for by a literal name: the first argument's literal and each literal after an `else` in that argument (`_t("a" if c else "b", ...)` asks for both)."""
    out = set()
    for m in KEY_CALL.finditer(text):
        lit = KEY_LIT.match(text, m.end())
        if not lit: continue
        out.add(lit.group(1))
        depth, i, q, stop = 1, lit.end(), "", min(len(text), lit.end() + 400)
        while i < stop and depth:
            c = text[i]
            if q:
                if c == "\\": i += 1
                elif c == q: q = ""
            elif c in "'\"": q = c
            elif c in "([{": depth += 1
            elif c in ")]}": depth -= 1
            elif c == "," and depth == 1: break
            i += 1
        out.update(KEY_ELSE.findall(text[lit.end():i]))
    return out
check("the key scan reads both keys of a conditional (the first literal, and the one after else), and only the first argument", keys_in('_t("a.b" if c(x, y) else "c.d", n=1)') == {"a.b", "c.d"}
      and keys_in("_t('a.b', k='x.y' if c else 'z.w')") == {"a.b"} and keys_in("_t(f'a.{n}')") == set() and keys_in("SST('js.a',{b:SST('js.b')})") == {"js.a", "js.b"})
used = set()
for s in SRC.values(): used |= keys_in(s)
used = {k for k in used if not k.endswith((".", "_"))}      # "search.kind." + k is a prefix, checked with DYN below
check("the four sources ask for keys by their literal names (a regex that matches nothing would prove nothing)", len(used) > 60, len(used))
check("every key they ask for by its literal name is in the English catalog", not [k for k in used if k not in EN], [k for k in used if k not in EN])
DYN = {"search.when.": [k for k, _l, _s in US.WHEN] + ["all", "dates"], "search.kind.": list(WS.KINDS), "search.row.": list(WS.KINDS), "search.state.": [k for k, _l in US.STATES],
       "runners.st.": ["running", "idle", "disabled", "offline", "restarting"], "runners.card.": ["runners", "running", "idle", "disabled", "offline"],
       "runners.act.": list(R.SWITCH_ACTIONS), "runners.phase.": ["starting", "finishing"], "js.colors.pv_": list(CT.PV_WORDS)}
missing = [p + k for p, ks in DYN.items() for k in ks if p + k not in EN]
check("every key the code builds (a prefix and a word) exists for each word it can be built with", not missing and all(len(ks) >= 2 for ks in DYN.values()), missing)
check("…and the words of each family are what the code's own lists hold (the chips are 1h 6h 24h 3d 7d, the kinds and rows the four kinds, the states open and closed)",
      [k for k, _l, _s in US.WHEN] == ["1h", "6h", "24h", "3d", "7d"] and list(WS.KINDS) == ["item", "history", "project", "session"] and [k for k, _l in US.STATES] == ["open", "closed"] and list(R.SWITCH_ACTIONS) == ["off", "on"])
check("every English value is a plain template (named fields only)", all(i18n.fields_of(v) is not None for v in EN.values()), [k for k, v in EN.items() if i18n.fields_of(v) is None])
check("the new areas are in the catalog and the docstring lists them", all(any(k.startswith(a) for k in EN) for a in ("search.", "runners.", "js.runners.", "js.colors."))
      and all(a in (i18n.__doc__ or "") + (pathlib.Path(STACK, "stackshot/web/i18n_catalog.py").read_text(encoding="utf-8").split('"""')[1]) for a in ("search.*", "runners.*", "js.colors.*")))
# the English constants the code keeps equal the catalog's English text
check("the search chips, kinds, rows and states: the English constants are the catalog's English text", all(EN["search.when." + k] == lab for k, lab, _s in US.WHEN) and all(EN["search.kind." + k] == WS.TITLES[k] for k in WS.KINDS)
      and all(EN["search.row." + k] == US.ROW_KIND[k] for k in WS.KINDS) and all(EN["search.state." + k] == lab for k, lab in US.STATES), None)
check("the runners' Disable / Enable words are the catalog's English text", all(EN["runners.act." + a] == w for a, w in R.SWITCH_ACTIONS.items()), R.SWITCH_ACTIONS)
check("the colour tool's English lines and strip words are the catalog's English text, and the strip with them is the strip", CT.TEXT["signIn"] == EN["js.colors.signin"] and CT.TEXT["note"] == EN["js.colors.note"]
      and all(CT.PV_WORDS[w] == EN["js.colors.pv_" + w] for w in CT.PV_WORDS) and CT.PREVIEW == CT.PREVIEW_T.format(**{w: EN["js.colors.pv_" + w] for w in CT.PV_WORDS}), (CT.TEXT, CT.PV_WORDS))
check("the colour tool's strip template names exactly the words the catalog has (no field left over, none missing)", set(i18n.fields_of(CT.PREVIEW_T)) == set(CT.PV_WORDS), i18n.fields_of(CT.PREVIEW_T))
check("a duration: routed dur() gives the English words the stored _dur always gave, over a range of spans", all(R.dur(s) == R._dur(s) for s in (0, 1, 59, 60, 61, 119, 120, 3599, 3600, 3661, 7200, 7260, 86399, 90000)), [(s, R.dur(s), R._dur(s)) for s in (59, 60, 3661)])

# ---- 3. the colour tool's snippet, in node
HAVE_NODE = bool(shutil.which("node"))
HARNESS = r"""
const vm = require('vm'); const fs = require('fs');
const [cfgjs, localize, ssi] = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
function run(table) {
  const sb = {SSI: table}; sb.window = sb; sb.SST = function (k) { return (sb.SSI && sb.SSI[k]) || k; };      // in a page the global object is the window, and the head's SST is window.SST
  vm.createContext(sb); vm.runInContext(cfgjs, sb); const c = sb.window.stackshotColors; const before = JSON.stringify([c.text, c.preview]);
  vm.runInContext(localize, sb); return {before, after: JSON.stringify([c.text, c.preview]), text: c.text, preview: c.preview};
}
process.stdout.write(JSON.stringify({empty: run({}), full: run(ssi), none: (function () { const sb = {}; sb.window = sb; vm.createContext(sb); vm.runInContext(cfgjs, sb); const b = JSON.stringify(sb.window.stackshotColors.preview);
  vm.runInContext(localize, sb); return b === JSON.stringify(sb.window.stackshotColors.preview); })()}));
"""
if HAVE_NODE:
    ssi = {"js.colors." + k: MARK(EN["js.colors." + k]) for k in ("signin", "note")}; ssi.update({"js.colors.pv_" + w: MARK(CT.PV_WORDS[w]) for w in CT.PV_WORDS})
    ssi["js.colors.pv_link"] = MARK("A <link> & \"x\"")      # the strip is HTML: a word with markup characters is escaped
    (T / "h.js").write_text(HARNESS, encoding="utf-8"); (T / "in.json").write_text(json.dumps([CT.CFG_JS, CT.LOCALIZE, ssi]), encoding="utf-8")
    nr = subprocess.run(["node", str(T / "h.js"), str(T / "in.json")], capture_output=True, text=True, timeout=60)
    try: res = json.loads(nr.stdout)
    except ValueError: res = None
    check("node ran the colour tool's settings and snippet", res is not None, (nr.stdout[:200], nr.stderr[-500:]))
    if res:
        e, f = res["empty"], res["full"]
        check("a page with an empty table (English): the snippet changes nothing, the settings are the English ones", e["before"] == e["after"] and e["text"]["signIn"] == EN["js.colors.signin"] and e["preview"] == CT.PREVIEW and res["none"], e["after"][:300])
        check("a page with no table at all: the snippet does nothing and raises nothing", res["none"] is True)
        check("a page with the test locale's table: the lines and the strip carry the markers, the example link is kept as it was", f["text"]["signIn"] == MARK(EN["js.colors.signin"]) and f["text"]["note"] == MARK(EN["js.colors.note"])
              and f["text"]["example"] == CT.TEXT["example"] and all(MARK(w) in f["preview"] for w in ("Send", "Cancel", "Undo", "Your move", "recommended")) and "Send</button>" not in f["preview"], f["preview"][:400])
        check("…a word with markup characters is escaped in the strip, and the strip's own markup is untouched", "[x:A &lt;link&gt; &amp; &quot;x&quot;]" in f["preview"] and f["preview"].count("<button") == 4 and f["preview"].count('class="tag t-you"') == 1, f["preview"][-300:])
else:
    print("note: node is not installed; the colour tool's snippet was not run")

# ---- 4. the pages, English and the test locale
COOKIE = {e: _signin._ui_sign(json.dumps({"email": e, "exp": time.time() + 3600})) for e in (MINA, NOOR)}
search.sync(__import__("stackshot.web.render", fromlist=["_"]).Board(str(T / "store")))
def visible(h): return re.sub(r"<script\b.*?</script>|<style\b.*?</style>", "", h, flags=re.S)
def plain(h): return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", visible(h)))
def absent(h, needles): return [n for n in needles if n not in h]
def unmarked(h):
    """The page's visible text with the markup, the markers `[x:...]` (a marker may hold another: innermost first), the ASCII date and age forms taken out: what is left is the words the page did not route."""
    t = re.sub(r"<[^>]*>", " ", visible(h)); t = re.sub(r"&[a-z#0-9]+;", " ", t)
    for _ in range(8): t = re.sub(r"\[x:[^\[\]]*\]", " | ", t)
    return re.sub(r"\s+", " ", re.sub(r"[AD]<[^>]*>", " | ", t))
def words_left(h, allowed): return sorted({w for w in re.findall(r"[A-Za-z][A-Za-z']{2,}", unmarked(h)) if w.lower() not in allowed})
def ctx(h, words, n=45):
    t = unmarked(h); return {w: [t[max(0, m.start() - n):m.end() + n] for m in re.finditer(r"\b" + re.escape(w) + r"\b", t)][:2] for w in words}
# words that stay English on these pages because they are data and not interface: the side panel's organisation names, a machine's name, the product name, the fixture's project page body and the item's own history lines
DATA_WORDS = {"home", "infra", "work", "box", "stackshot", "current", "state", "agent", "created", "mover", "disabled"}      # "disabled" is the side panel machines list, render.py, its own stage

# the runners fixture: a fake GitHub (as tests/runners_scenario.py has it), a fake ssh, a fixed clock
T0 = dt.datetime(2026, 10, 27, 12, 0, 0, tzinfo=dt.timezone.utc).timestamp()
CLOCK = [T0]; R._now = lambda: CLOCK[0]; R2._now = R._now
def iso(t): return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def rn(name, box, online=True, busy=False): return {"id": sum(map(ord, name)), "name": name, "status": "online" if online else "offline", "busy": busy,
                                                     "labels": [{"name": x} for x in ("self-hosted", "Linux", "X64", box, "pool", "light")]}
RUNNERS = {"salamander": [rn("box-a-salamander", "box-a"), rn("box-a-salamander-2", "box-a", busy=True), rn("box-b-salamander", "box-b", online=False), rn("box-c-salamander", "box-c", online=False)],
           "stackshot": [rn("box-a-stackshot", "box-a", online=False), rn("box-a-stackshot-2", "box-a", busy=True), rn("box-c-stackshot", "box-c")]}
RUNS = {"salamander": [{"id": 11, "head_branch": "feature-x", "html_url": "https://github.com/example-owner/salamander/actions/runs/11", "pull_requests": [{"number": 17}], "run_started_at": iso(T0 - 400)}],
        "stackshot": [{"id": 21, "head_branch": "nightly-fix", "html_url": "https://github.com/example-owner/stackshot/actions/runs/21", "pull_requests": [], "run_started_at": iso(T0 - 4000)}]}
JOBS = {11: [{"id": 111, "status": "in_progress", "runner_name": "box-a-salamander-2", "started_at": iso(T0 - 300)}],
        21: [{"id": 211, "status": "in_progress", "runner_name": "box-a-stackshot-2", "started_at": iso(T0 - 3725)}]}
BROKEN = set()
def fake_get(path, timeout=8):
    if re.fullmatch(r"/repos/example-owner/\w+|/repositories/\d+", path): return {"owner": {"login": "example-owner", "type": "User"}}
    m = re.fullmatch(r"/repos/example-owner/(\w+)/actions/runners\?per_page=100&page=(\d+)", path)
    if m:
        if m.group(1) in BROKEN: raise RunnersError(f"GitHub answered 502 for /repos/example-owner/{m.group(1)}/actions/runners")
        return {"total_count": len(RUNNERS[m.group(1)]), "runners": RUNNERS[m.group(1)] if m.group(2) == "1" else []}
    m = re.fullmatch(r"/repos/example-owner/(\w+)/actions/runs\?status=in_progress&per_page=\d+", path)
    if m: return {"workflow_runs": RUNS[m.group(1)]}
    if re.fullmatch(r"/repos/example-owner/(\w+)/actions/runs\?status=queued&per_page=\d+", path): return {"workflow_runs": []}
    m = re.fullmatch(r"/repos/example-owner/(\w+)/actions/runs/(\d+)/jobs\?filter=latest&per_page=100", path)
    if m: return {"jobs": JOBS[int(m.group(2))]}
    raise AssertionError("unexpected GitHub path " + path)
R._get = fake_get
SSH_OUT = {"box-b": "mode file: off\r\nhold file: none\r\n", "box-c": "mode file: on\r\nhold file: salamander\r\n"}
R._ssh = lambda host, timeout, flavor="ps": SSH_OUT[host]
(T / "ci" / "mode").write_text("on\n"); (T / "ci" / "hold").write_text(""); (T / "ci" / "halted").write_text("")
SWITCH = T / "ci" / "pool-mode.sh"; SWITCH.write_text("#!/bin/bash\nexit 0\n")      # never run: only its being a file turns the buttons on
_cfg.CFG["runners"]["switch_script"] = str(SWITCH); R.fleet_boxes = lambda: ["box-a", "box-b", "box-c"]
def aged_snapshot():
    R.reset(); BROKEN.clear(); CLOCK[0] = T0
    snap = R.snapshot()
    for x in snap["runners"]:
        if x["state"] == "offline": x["off_since"] = CLOCK[0] - 600
    return R.snapshot(force=True)
TOKEN = lambda b: "tok-" + b
RUNNER_WORDS = {"box", "salamander", "stackshot", "feature", "nightly", "fix", "example", "owner", "alpha", "main", "pool", "mode", "lantern", "quarterly", "inventory", "thing", "lives", "here", "finished", "works", "next", "step", "state", "projects"}
snap = aged_snapshot()
check("the fixture covers every state the page words: idle, running, offline (a fault), disabled and held", {x["state"] for x in snap["runners"]} == {"idle", "running", "offline"} and any(x.get("disabled") for x in snap["runners"])
      and any(x["kind"] == "fault" for x in snap["runners"]), [(x["name"], x["state"], x["kind"], x.get("disabled")) for x in snap["runners"]])

def runners_table(lang, sn):
    with i18n.use(lang): return R2.table_html(sn, T0, TOKEN)
set_dir(None); reset_warned()
en_tab = runners_table("en", snap)
EN_TAB = ["Runners", "Running", "Idle", "Disabled", "Offline", "Machine", ">Disable<", ">Enable<", " busy", "Updated "]
check("English: the table has the cards, the machines, the state words and both buttons, no marker", not absent(re.sub(r"<[^>]*>", "", en_tab) + en_tab, EN_TAB) and "[x:" not in en_tab, absent(en_tab, EN_TAB))
write_ko(test_locale()); set_dir(LOC); reset_warned()
check("the test locale loaded", i18n.available() == ["en", "ko"], i18n.available())
ko_tab = runners_table("ko", snap)
KO_TAB = [MARK(w) for w in ("Runners", "Running", "Idle", "Disabled", "Offline", "Machine", "Disable", "Enable", "running", "idle", "offline", "disabled", "on")]
check("the test locale: the cards, the table's heads, the machines' state lines, every runner's state word and the buttons are all in markers", not absent(ko_tab, KO_TAB), absent(ko_tab, KO_TAB))
ko_nr = re.sub(r'<span class="rwhy[^"]*">.*?</span>', " ", ko_tab, flags=re.S)
leftover = words_left(ko_nr, RUNNER_WORDS)
check("…no English word left outside a marker (the runner, repo, box and branch names, which stay, are the only words)", leftover == [], (leftover, ctx(ko_nr, leftover)))
reasons = re.findall(r'<span class="rwhy[^"]*">(.*?)</span>', ko_tab, re.S)
check("the reasons the data module gives stay English, in either language (they are compared and cached by code)", reasons and re.sub(r"<[^>]*>", "", ko_tab).count("[x:did not") == 0 and any("did not disable" in x or "held for" in x for x in reasons), reasons[:3])
NAMES = ["box-a-salamander-2", "nightly-fix"]
check("the names stay as they are: runner names, the PR link, the branch link", not absent(ko_tab, NAMES) and "salamander #17" in re.sub(r"<[^>]*>", "", ko_tab) and MARK("box-a") not in ko_tab, absent(ko_tab, NAMES))
check("the time a job has run is the test locale's form (a number and the marked unit), the English form is not there", re.search(r"\[x:\d+m\]|\[x:\d+h \d\dm\]|\[x:\d+s\]", ko_tab) is not None and not re.search(r"\b\d+m\b(?!\])", re.sub(r"\[x:[^\]]*\]", "", ko_tab)), re.findall(r"\[x:[^\]]*\d[^\]]*\]", ko_tab)[:6])
# an unreachable box, one never read, an unreadable GitHub list, the placeholder, a stale snapshot
sn2 = {**snap, "switch": {"box-a": {"ok": False, "why": "unreachable"}, "box-b": {"ok": False, "why": "unread"}, "box-c": {"ok": True, "mode": "off", "since": T0 - 90}}, "errors": {"stackshot": "GitHub answered 502"},
       "failed": ["stackshot"], "stale": True}
k2, e2 = runners_table("ko", sn2), runners_table("en", sn2)
EN2 = ["not reachable", "switch not read", "Disabled", "GitHub error: GitHub answered 502", "not refreshed since"]
check("English: the unreachable machine, the unread switch, the disabled machine with its time, the GitHub error and the stale line", not absent(e2.replace("&#x27;", "'"), EN2) and "[x:" not in e2, absent(e2, EN2))
KO2 = [MARK(EN["runners.m.unreachable"]), MARK(EN["runners.m.unread"]), "[x:GitHub error: GitHub answered 502]", "[x:not refreshed since "]
check("the test locale: the unreachable and unread lines, the GitHub error (its lead-in marked, GitHub's own words inside) and the stale line carry markers", not absent(k2, KO2) and re.search(r"\[x:since \d\d:\d\d\]", k2) is not None, (absent(k2, KO2), re.findall(r"\[x:since[^\]]*\]", k2)))
snp = {"ts": 0, "errors": {}, "failed": [], "runners": [], "switch": {}, "stale": False, "pending": True, "refreshing": True, "age_s": 0}
check("the placeholder before the first read is the test locale's line, and English is English", MARK(EN["runners.pending"]) in runners_table("ko", snp) and EN["runners.pending"] in runners_table("en", snp) and "[x:" not in runners_table("en", snp), runners_table("ko", snp)[:300])
for what, cfg_repos in (("no repos listed", []),):
    saved = list(_cfg.CFG["runners"]["repos"]); _cfg.CFG["runners"]["repos"] = cfg_repos
    try: k3, e3 = runners_table("ko", snap), runners_table("en", snap)
    finally: _cfg.CFG["runners"]["repos"] = saved
    check(f"{what}: the one plain line is the test locale's, and English is English", MARK(EN["runners.not_used"]) in k3 and EN["runners.not_used"] in e3 and "[x:" not in e3, k3[:300])

# the page itself over HTTP, in both languages, and the JSON
def settle(limit=10):
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        with R._LOCK:
            if R._SERVE["thread"] is None and R._CACHE.get("snap") is not None: return True
        time.sleep(0.01)
    return False
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def get(path, who=MINA):
        c.cookies.clear()
        if who: c.cookies.set(_signin._UI_COOKIE, COOKIE[who])
        return c.get(path, follow_redirects=False)
    def post_lang(lang, who=MINA):
        c.cookies.clear(); c.cookies.set(_signin._UI_COOKIE, COOKIE[who])
        return c.post("/prefs/lang", content=json.dumps({"lang": lang}), headers={"Origin": BOARD, "Content-Type": "application/json"}, follow_redirects=False)
    R.reset(); BROKEN.clear(); CLOCK[0] = T0
    # the first request answers from nothing (the placeholder) and kicks the rebuild; the next one has the table
    first_ko = None
    check("the person's choice is saved", post_lang("ko").status_code == 200)
    first_ko = get("/runners", MINA); settle(); page_ko = get("/runners", MINA); page_en = get("/runners", NOOR)
    check("the runners page: 200 for both, <html lang> follows the person", first_ko.status_code == page_ko.status_code == page_en.status_code == 200 and '<html lang="ko">' in page_ko.text and '<html lang="en">' in page_en.text, (page_ko.status_code, page_en.status_code))
    check("the placeholder page (the first request) is in the test locale too", MARK(EN["runners.pending"]) in first_ko.text or MARK(EN["runners.not_used"]) in first_ko.text, visible(first_ko.text)[-400:])
    h_ko, h_en = page_ko.text, page_en.text
    check("English person: no marker, no script table override, the English heading, subtitle, title and words", "[x:" not in h_en and 'id="ssi"' not in h_en and "<h1>CI runners</h1>" in h_en and "<title>" in h_en and ">Disable<" in h_en, re.findall(r"\[x:[^\]]*\]", h_en)[:3])
    check("the test locale: the title, heading and subtitle are in markers and the script table override is there", f"<h1>{MARK('CI runners')}</h1>" in h_ko and 'id="ssi"' in h_ko and re.search(r"<title>\[x:CI runners[^<]*</title>", h_ko) is not None
          and MARK(EN["runners.col.machine"]) in h_ko and f">{MARK('Disable')}<" in h_ko, visible(h_ko)[:900])
    lf = words_left(re.sub(r'<span class="rwhy[^"]*">.*?</span>', " ", visible(h_ko), flags=re.S), RUNNER_WORDS | DATA_WORDS)
    check("…and no English word left outside a marker on the whole page, side panel and header included, bar the fixture names", lf == [], (lf, ctx(h_ko, lf)))
    sc = [s for s in re.findall(r"<script\b[^>]*>(.*?)</script>", h_ko, re.S) if "rn-body" in s]
    check("the page's own script reads its words with SST and holds no English message", len(sc) == 1 and "SST('js.runners.stale_login')" in sc[0] and not [EN[k] for k in EN if k.startswith("js.runners.") and EN[k] in sc[0]] and "SST('js.runners.no_answer')" in sc[0],
          [EN[k] for k in EN if k.startswith("js.runners.") and EN[k] in (sc[0] if sc else "")])
    tab = json.loads(re.search(r"window.SSI=(\{.*?\});</script>", h_ko, re.S).group(1))
    check("the script table the page carries is the test locale's, for these words", all(tab.get(k) == MARK(EN[k]) for k in EN if k.startswith(("js.runners.", "js.colors."))), [k for k in EN if k.startswith(("js.runners.", "js.colors.")) and tab.get(k) != MARK(EN[k])][:4])
    check("the colour tool's head snippet is on the page and it localizes by the table (the strip words are not on the page in English)", "window.stackshotColors=" in h_ko and "js.colors.signin" in h_ko and "SST('js.colors.pv_'+k)" in h_ko, None)
    js_ko, js_en = get("/runners.json", MINA).json(), get("/runners.json", NOOR).json()
    check("/runners.json: the html is in the person's language, the counts and runners are the same data", MARK("Runners") in js_ko["html"] and "[x:" not in js_en["html"] and js_ko["counts"] == js_en["counts"] and js_ko["runners"] == js_en["runners"]
          and "Runners" in js_en["html"], (js_ko["html"][:200], js_en["html"][:200]))
    check("…the reasons in the JSON are English for both (they are data, not interface words)", [x["reason"] for x in js_ko["runners"]] == [x["reason"] for x in js_en["runners"]] and not any("[x:" in x["reason"] for x in js_ko["runners"]))
    # a snapshot built while the request is in one language never holds another's words
    R.reset(); BROKEN.clear()
    with i18n.use("ko"): sn_k = aged_snapshot()
    check("a snapshot read in the test locale holds no marker (the stored text is English whatever the request's language)", "[x:" not in json.dumps(sn_k, default=str), None)
    BROKEN.add("stackshot"); R.reset()
    get("/runners", MINA); settle(); err_ko = get("/runners", MINA).text; err_en = get("/runners", NOOR).text
    BROKEN.clear(); R.reset()
    check("a GitHub error over HTTP: the line is the test locale's with GitHub's own words inside it", "[x:GitHub error: " in plain(err_ko) and "502" in plain(err_ko), re.findall(r"GitHub error[^|]{0,80}", plain(err_ko))[:2])
    check("…and English has the same line, unmarked", "GitHub error: " in plain(err_en) and "502" in plain(err_en) and "[x:" not in err_en, re.findall(r"GitHub error[^|]{0,80}", plain(err_en))[:2])

    # ---- the search page
    set_dir(LOC)
    def sp(q, who=MINA, extra=""): return get("/search?" + (f"q={q}" if q is not None else "") + extra, who)
    ALLK = "&kind=item&kind=history&kind=project&kind=session&state=open&state=closed"      # a form with every box ticked (an f=1 form with none ticked finds nothing)
    SEARCH_WORDS = {"quarterly", "lantern", "inventory", "alpha", "main", "state", "projects", "thing", "lives", "here", "finished", "works", "next", "step", "board", "example", "invalid", "gbrain", "fixture", "old"}
    for tag, q, extra in (("a hit (item, project, session)", "lantern", ""), ("a hit of a project and a session", "alpha", ""), ("no hit", "zzzzqq", ""), ("a one-letter query", "a", ""), ("nothing typed", None, ""),
                          ("the dates window", "lantern", "&f=1&when=dates&from=2020-01-01T00:00&to=2031-01-01T00:00" + ALLK), ("a dates window with no start", "lantern", "&f=1&when=dates" + ALLK),
                          ("a bad date", "lantern", "&f=1&when=dates&from=garbage" + ALLK), ("the last hour", "lantern", "&f=1&when=1h" + ALLK), ("a window of days", "lantern", "&f=1&when=3d" + ALLK),
                          ("only one kind ticked", "alpha", "&f=1&when=all&kind=project&state=open&state=closed"), ("nothing found, other kinds unticked", "alpha", "&f=1&when=all&kind=item&state=open&state=closed"), ("only closed items", "lantern", "&f=1&when=all&kind=item&kind=history&kind=project&kind=session&state=closed")):
        hk, he = sp(q, MINA), sp(q, NOOR)
        ok = hk.status_code == he.status_code == 200
        check(f"search, {tag}: 200 for both", ok, (hk.status_code, he.status_code))
        if not ok: continue
        k, e = hk.text, he.text
        check(f"search, {tag}: English has no marker and no script table override", "[x:" not in e and 'id="ssi"' not in e and "<h1>Search</h1>" in e and '<html lang="en">' in e, re.findall(r"\[x:[^\]]*\]", e)[:3])
        lf = words_left(k, SEARCH_WORDS | DATA_WORDS)
        check(f"search, {tag}: the test locale has the heading and the filters and no English word outside a marker", f"<h1>{MARK('Search')}</h1>" in k and lf == [], (lf, ctx(k, lf)))
    kk, ee = sp("lantern", MINA, "&f=1&when=all" + ALLK).text, sp("lantern", NOOR, "&f=1&when=all" + ALLK).text
    NEED = [MARK(EN[k]) for k in ("search.row.item", "search.group.when", "search.group.kind", "search.group.state", "search.apply", "search.when.24h", "search.kind.session", "search.state.closed", "search.match_many".replace("many", "many"))]
    NEED = [n for n in NEED if "{" not in n]
    check("search, results with the filters open: the row tags, the filter groups, the chips, the kinds, the states and the button are in markers; the item's title stays English", not absent(kk, NEED) and TITLE in plain(kk) and MARK(TITLE) not in kk and "[x:3 matches]" in kk, (absent(kk, NEED), re.findall(r"\[x:\d+ match[^\]]*\]", kk)[:2]))
    check("…and English has the English words, the same title and no marker", not absent(ee, ["Item", "Search filters", "Apply", "24 h"]) and TITLE in plain(ee) and "[x:" not in ee, absent(ee, ["Item", "Apply", "24 h"]))
    ka = sp("alpha", MINA, "&f=1&when=all" + ALLK).text
    NEED = [MARK(EN["search.row.project"]), MARK(EN["search.row.session"])]
    check("search, project and session rows: the tags are in markers and the names stay", not absent(ka, NEED) and "Alpha" in plain(ka) and "alpha-main" in plain(ka), (absent(ka, NEED), re.findall(r"\[x:(?:Item|Project|Session|History)\]", ka), plain(ka)[-900:]))
    check("…a session with no live pane says so in the test locale", MARK(EN["search.no_pane"]) in ka or MARK(EN["search.opens_sala"]) in ka or MARK(EN["search.gbrain_page"]) in ka, re.findall(r"\[x:[^\]]*pane[^\]]*\]", ka)[:2])
    kn, en_ = sp("zzzzqq", MINA).text, sp("zzzzqq", NOOR).text
    check("search, no hit: the line is the test locale's, and English is English", MARK(EN["search.none"]) in kn or "[x: · No matches.]" in kn.replace(MARK(EN["search.none"]), "[x: · No matches.]") and EN["search.none"].strip() in en_ and "[x:" not in en_, re.sub(r"<[^>]*>", " ", kn)[-300:])
    kd = sp("lantern", MINA, "&f=1&when=dates&from=2020-01-01T00:00&to=2031-01-01T00:00" + ALLK).text
    NEED = [MARK(EN["search.from_label"]), MARK(EN["search.to_label"]), MARK(EN["search.when.dates"])]
    check("search, the dates window: the labels and the chip are in markers, and the dates are the test locale's form", not absent(kd, NEED) and re.search(r"D<[^>]*>", kd) is not None, (absent(kd, NEED), re.findall(r"D<[^>]*>", kd)[:2]))
    kb = sp("lantern", MINA, "&f=1&when=dates&from=garbage" + ALLK).text
    check("search, a bad date: the line is the test locale's", MARK(EN["search.bad_date"]) in kb or MARK(EN["search.need_from"]) in kb, re.sub(r"<[^>]*>", " ", kb)[-300:])
    kt = sp("alpha", MINA, "&f=1&when=all&kind=item&state=open&state=closed").text
    check("search, the unticked kinds: the line naming them is built from the test locale's kind words", "[x: Unticked boxes hold more: " in kt and "[x:[x:History] (1)]" in kt and "[x:[x:Projects] (1)]" in kt, plain(kt)[-900:])
    # the header's search box on any page is the home's keys, not this module's
    kh = get("/", MINA).text
    check("the header's search box is in the test locale on the home page too (the keys search.py reuses are the home's)", f'placeholder="{MARK(EN["home.search.hint"])}"' in kh, None)
    check("the English person's pages never see the test locale: a round trip back to English leaves no marker on either page", post_lang("en").status_code == 200 and "[x:" not in sp("lantern", MINA).text and "[x:" not in get("/runners", MINA).text, None)

set_dir(None)
n_bad = len(fails)
print(f"{len(ran) - n_bad}/{len(ran)} checks passed")
sys.exit(1 if n_bad else 0)
