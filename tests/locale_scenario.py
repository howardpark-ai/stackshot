"""Scenario test for the pages' string table and the second language (stackshot/web/i18n.py, i18n_catalog.py, uiprefs.py lang, the /prefs/lang route in server.py, ui/render.py apply_lang and the
side panel's switch): fixture data, the routes through Starlette's test client, no live store, no network. People and addresses are made up. The repository holds no text in another language, so the
second language here is an ASCII TEST locale written into a temporary folder: every value is the English text wrapped as `[x:...]`, and the date and age forms are ASCII templates that cannot be
mistaken for English. It proves the mechanism; it says nothing about any real translation.

Covers:
  * t(): English for a language with no catalog, for a missing key (the key itself), for a missing field (the template unfilled); the test locale's text when it has the key; the fallbacks when the folder
    is not configured, is missing, has no file, a file that is not JSON, or one that is not an object; a key the catalog does not have is ignored and counted; a value naming a field the English text does not
    have, a value that is not text, a format spec, a positional field and an unbalanced brace each fall back to the English text for that key; a value that leaves a field out is kept; a `_note` key is ignored;
    one warning line per file and reason, never one per call; a file changed on disk is read again;
  * fmt_date and fmt_age: English output equals the helpers they replaced (compared on a range of days, hours and spans), and in the test locale come out of the catalog's templates;
  * the catalog: every key a page, a script or a helper asks for exists in English, every English value is a plain template, and no source file of the repository holds a Hangul letter;
  * uiprefs: the language of a person who never picked one is English, a round trip, English stored as no key, other settings kept beside it, an unknown stored value reads as English, a bad value is refused;
  * the route (POST /prefs/lang): refused without sign-in, from a foreign origin, without a JSON content type, with a bad value, with no value; a good body is stored; GET is 405;
  * the switch: drawn at the side panel's foot only when a second language has loaded (none with no folder), as real buttons with the pressed one marked, for English and the other language alike;
  * the pages: <html lang> follows the person's language; the home page and the side panel (title, buttons, headings, state words, count cards, ages, the fixed buttons, the script words) are in the test
    locale for a person who picked it and in English for everyone else, with the item titles and the other item text in English; the home keeps one draw per language and a drop clears them all; the
    render-stamp answers for the person's own draw; a person whose language has no catalog reads English;
  * English is unchanged: with no locale folder a page has no marker and no switch.

    tests/run-suite locale        → exit 0 / 1"""
import contextlib, datetime, io, json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="locale-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
MINA, NOOR = "mina@example.org", "noor@example.org"
toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{MINA}", "{NOOR}"]'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^panel = true', 'panel = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "secrets", "touch", "repo", "brain/projects", "locales"): (T / d).mkdir(parents=True)
A = "22222222-2222-4222-8222-222222222222"
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({A: {"name": "alpha-main", "machine": "a", "url": "", "seen": "x"}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": "https://example.invalid/alpha", "agents": {"alpha-main": "builds"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE.\n\n<!-- timeline -->\n- 2026-02-19 | old\n")
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
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.core import config as _cfg
from stackshot.web import i18n, i18n_catalog, search
from stackshot.web import uiprefs as up
from stackshot.web import server
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.auth import signin as _signin
from stackshot.web import board_home as _web_board_home
from stackshot.web.ui import render as r2
from starlette.testclient import TestClient
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
EN = i18n.EN
LOC = T / "locales"

# ---- the ASCII test locale: English text wrapped in a marker, and ASCII date and age forms
MARK = lambda v: f"[x:{v}]"
DATE_AGE = {"date.full": "D<{wd}/{month}/{day}/{hm}>", "date.nohm": "D<{wd}/{month}/{day}>", "date.day": "{n}{ord}",
            "date.ord.1": "o1", "date.ord.2": "o2", "date.ord.3": "o3", "date.ord.n": "on",
            "age.now": "A<now>", "age.min": "A<{n}min>", "age.hour": "A<{n}hr>", "age.day": "A<{n}day>"}
DATE_AGE.update({f"date.wd.{i}": f"w{i}" for i in range(7)}); DATE_AGE.update({f"date.mon.{i}": f"m{i}" for i in range(1, 13)})
def test_locale(**over):
    d = {k: MARK(v) for k, v in EN.items()}; d.update(DATE_AGE); d.update(over); return d
def write_ko(d, text=None):
    (LOC / "ko.json").write_text(text if text is not None else json.dumps(d), encoding="utf-8")
def set_dir(v):
    if v is None: _cfg.CFG.get("ui", {}).pop("locale_dir", None)
    else: _cfg.CFG.setdefault("ui", {})["locale_dir"] = str(v)
def quiet_err():
    """Run a block with the log line (stderr) captured: (the buffer)."""
    return contextlib.redirect_stderr(io.StringIO())
def reset_warned():
    i18n._WARNED.clear(); i18n._LOADED.clear()

# ---- 1. t(): English, and the fallbacks
set_dir(None); reset_warned()
check("English: a key gives its catalog text, with the fields filled", i18n.t("home.send", "en") == "Send" and i18n.t("panel.moved", "en", label="Runners", pos=2, n=5) == "Runners moved to position 2 of 5")
check("English is the default language of a request", i18n.current() == "en" and i18n.t("home.send") == "Send")
check("no folder configured: only English is available and another language reads as English", i18n.available() == ["en"] and i18n.t("home.send", "ko") == "Send" and i18n.norm("ko") == "en")
check("a key the catalog does not have is returned as it is (a typo shows)", i18n.t("home.no_such_key") == "home.no_such_key")
check("a template whose field is not given is returned unfilled, never an error", i18n.t("home.handed") == EN["home.handed"] and i18n.t("home.handed", who="alpha-main") == "handed to alpha-main, not yet taken")
check("every English value is a plain template (named fields only)", all(i18n.fields_of(v) is not None for v in EN.values()), [k for k, v in EN.items() if i18n.fields_of(v) is None])
check("the catalog is the module's catalog and every key is lower-case dotted", set(i18n_catalog.CATALOG) <= set(EN) and all(re.fullmatch(r"[a-z0-9_.-]+", k) for k in EN))
NOKO = LOC / "nope"
set_dir(NOKO)
with quiet_err() as err:
    got = (i18n.available(), i18n.t("home.send", "ko"), i18n.t("home.send", "ko"), i18n.t("panel.title", "ko"))
check("a folder that does not exist: English, one warning line however many calls", got == (["en"], "Send", "Send", "Summary") and err.getvalue().count("\n") == 1 and "not found" in err.getvalue(), (got, err.getvalue()))
set_dir(LOC)
with quiet_err() as err:
    got = (i18n.available(), i18n.t("home.send", "ko"))
check("a folder with no file: English and one warning", got == (["en"], "Send") and err.getvalue().count("\n") == 1 and "ko.json" in err.getvalue(), (got, err.getvalue()))
write_ko(None, "{not json"); reset_warned()
with quiet_err() as err:
    got = (i18n.available(), i18n.t("home.send", "ko"))
check("a file that is not JSON: English and one warning", got == (["en"], "Send") and err.getvalue().count("\n") == 1 and "cannot be read" in err.getvalue(), (got, err.getvalue()))
write_ko(None, "[1, 2]"); reset_warned()
with quiet_err() as err:
    got = (i18n.available(), i18n.t("home.send", "ko"))
check("a file that is not an object: English and one warning", got == (["en"], "Send") and err.getvalue().count("\n") == 1 and "not a JSON object" in err.getvalue(), (got, err.getvalue()))
write_ko(None, b"\xff\xfe\x00bad".decode("latin-1")); (LOC / "ko.json").write_bytes(b"\xff\xfe\x00bad"); reset_warned()
with quiet_err() as err:
    got = (i18n.available(), i18n.t("home.send", "ko"))
check("a file that is not UTF-8 text: English and one warning, no error", got == (["en"], "Send") and err.getvalue().count("\n") == 1, (got, err.getvalue()))

# a file saved with a byte-order mark (some editors write one) loads like any other
write_ko(None); (LOC / "ko.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(test_locale()).encode("utf-8")); reset_warned()
with quiet_err() as err:
    got = (i18n.available(), i18n.t("home.send", "ko"))
check("a file with a byte-order mark loads", got == (["en", "ko"], MARK("Send")) and err.getvalue() == "", (got, err.getvalue()))
# a value that cannot be written out as UTF-8 (a lone surrogate, which JSON's \\ud83d escape gives) is refused to English; the rest of the file stays
write_ko(test_locale(**{"home.send": "\ud83d", "home.picks_up": "ok \ude00 half"})); reset_warned()
with quiet_err() as err:
    got = (i18n.available(), i18n.t("home.send", "ko"), i18n.t("home.picks_up", "ko"), i18n.t("panel.title", "ko"))
check("a lone-surrogate value is refused (English for that key), the other keys load, and what t() gives can be encoded", got == (["en", "ko"], "Send", "{who} picks it up", MARK("Summary")) and "refused" in err.getvalue()
      and all(s.encode("utf-8") for s in got[1:]), (got, err.getvalue()))
check("validate: a lone surrogate counts as refused", i18n.validate({"home.send": "\ud83d"})[1]["refused"] == 1 and "home.send" not in i18n.validate({"home.send": "\ud83d"})[0])
# a file with nothing usable in it is not a language: no switch, no html lang change
for what, body in (("an empty object", {}), ("only keys the catalog does not have", {"no.such.a": "x", "no.such.b": "y"}), ("only refused values", {"home.send": 7, "home.picks_up": "{oops"})):
    write_ko(body); reset_warned()
    with quiet_err() as err:
        got = (i18n.available(), i18n.t("home.send", "ko"), i18n.norm("ko"), i18n.js_table("ko") == i18n.js_table("en"))
    check(f"a file with {what}: not loaded (English only, no language offered), one warning that says so", got == (["en"], "Send", "en", True) and err.getvalue().count("\n") == 1 and "no usable key" in err.getvalue(), (got, err.getvalue()))
    with quiet_err() as err2:
        i18n.available(); i18n.available()
    check(f"…and the file is not read or warned about again while it stays as it is ({what})", err2.getvalue() == "")

# the loader's validation
raw = {"home.send": MARK("Send"), "home.no_such_key": "x", "home.handed": "H {nope}", "panel.title": 7, "home.options": "O {n:>5}", "home.copy_the": "C {}", "home.unknown": "U {oops",
       "js.sent_done": MARK("sent"), "home.picks_up": "picks", "_note": "for the file's writer"}
strs, counts = i18n.validate(raw)
check("validate: a known key with plain text is kept; a field-less text for a template with fields is kept", strs.get("home.send") == MARK("Send") and strs.get("home.picks_up") == "picks" and strs.get("js.sent_done") == MARK("sent"), strs)
check("validate: an unknown key is ignored and counted, a `_` key is ignored and not counted", "home.no_such_key" not in strs and counts["unknown"] == 1, counts)
check("validate: an extra field, a non-text value, a format spec, a positional field and an unbalanced brace are refused", all(k not in strs for k in ("home.handed", "panel.title", "home.options", "home.copy_the", "home.unknown")) and counts["refused"] == 5, (strs, counts))
check("validate: missing counts the English keys the file does not give", counts["missing"] == len(EN) - len(strs), counts)
write_ko(raw); reset_warned()
with quiet_err() as err:
    got = (i18n.available(), i18n.t("home.send", "ko"), i18n.t("home.handed", "ko", who="w"), i18n.t("panel.title", "ko"), i18n.t("home.options", "ko"), i18n.t("home.picks_up", "ko", who="z"))
check("a loaded file: its text where it has the key, English where it has not or refused the value (one warning for the file)",
      got == (["en", "ko"], MARK("Send"), "handed to w, not yet taken", "Summary", "Options", "picks") and err.getvalue().count("\n") == 1 and "refused" in err.getvalue(), (got, err.getvalue()))
w1 = err.getvalue()
with quiet_err() as err2:
    for _ in range(5): i18n.t("home.send", "ko")
check("…and no further warning on later calls", err2.getvalue() == "" and w1.count("\n") == 1, err2.getvalue())
write_ko(test_locale(**{"home.send": MARK("Send again, a longer text so the size differs")}))
check("a file changed on disk is read again", i18n.t("home.send", "ko") == MARK("Send again, a longer text so the size differs"))
write_ko(test_locale()); reset_warned()
check("the test locale loads whole: every key present, nothing refused", i18n.validate(json.loads((LOC / "ko.json").read_text()))[1] == {"unknown": 0, "refused": 0, "missing": 0} and i18n.available() == ["en", "ko"])
with i18n.use("ko"):
    inside = [i18n.current(), i18n.t("home.send")]
check("the language of a request: use() sets it for a block and puts it back; t() follows it", i18n.current() == "en" and i18n.t("home.send") == "Send" and inside == ["ko", MARK("Send")], inside)

# ---- 2. dates and ages: English as before, the test locale from the catalog's templates
def old_when(t, clock=True):
    if not isinstance(t, datetime.datetime): clock = False
    d = t.day
    return f"{t:%a %b} {d}{'th' if 11 <= d % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')}" + (f" {t:%H:%M}" if clock else "")
def old_dur(s):
    m_ = max(int(s), 0) // 60
    return f"{m_}m" if m_ < 60 else f"{m_ // 60}h" if m_ < 48 * 60 else f"{m_ // 1440}d"
old_ago = lambda s: "just now" if s < 60 else old_dur(s) + " ago"
UTC = datetime.timezone.utc; DXB = datetime.timezone(datetime.timedelta(hours=4))
days = [datetime.datetime(2026, 11, d, h, m, tzinfo=z) for d in (1, 2, 3, 4, 10, 11, 12, 13, 14, 21, 22, 23, 24, 30) for h, m, z in ((0, 0, UTC), (16, 20, DXB), (23, 59, UTC))]
check("fmt_date: English equals the form it replaced, with and without a clock, on every ordinal case", all(i18n.fmt_date(t, "en") == old_when(t) and i18n.fmt_date(t, "en", clock=False) == old_when(t, False) and r2.when_words(t) == old_when(t)
      for t in days) and r2.when_words(datetime.date(2026, 11, 3)) == old_when(datetime.date(2026, 11, 3)) == "Tue Nov 3rd", [t for t in days if r2.when_words(t) != old_when(t)][:2])
check("fmt_date: English is 'Tue Nov 10th 16:20' for an epoch in a zone", i18n.fmt_date(datetime.datetime(2026, 11, 10, 16, 20, tzinfo=UTC).timestamp(), "en", tz=UTC) == "Tue Nov 10th 16:20")
check("fmt_date: the test locale writes its own forms from the catalog (weekday, month, ordinal, layout)",
      i18n.fmt_date(datetime.datetime(2026, 11, 10, 16, 20, tzinfo=UTC), "ko") == "D<w1/m11/10on/16:20>" and i18n.fmt_date(datetime.datetime(2026, 11, 3, 9, 5, tzinfo=UTC), "ko", clock=False) == "D<w1/m11/3o3>"
      and i18n.fmt_date(datetime.date(2026, 11, 22), "ko") == "D<w6/m11/22o2>" and i18n.fmt_date(datetime.datetime(2026, 11, 11, 1, 0, tzinfo=UTC), "ko").startswith("D<w2/m11/11on/"))
spans = [0, 1, 59, 59.9, 60, 61, 119, 3599, 3600, 7200, 86399, 86400, 47 * 3600, 48 * 3600 - 1, 48 * 3600, 5 * 86400, 400 * 86400, -5]
check("fmt_age: English equals the helpers it replaced, over spans from 'just now' to days", all(i18n.fmt_age(s, "en") == old_ago(s) and r2.ago(s) == old_ago(s) for s in spans), [s for s in spans if r2.ago(s) != old_ago(s)])
check("fmt_age: the quiet form is '>' and the age, never 'just now'", all(i18n.fmt_age(s, "en", quiet=True) == ">" + old_dur(s) + " ago" for s in spans), [(s, i18n.fmt_age(s, "en", quiet=True)) for s in spans[:4]])
check("fmt_age: the test locale writes its own forms", [i18n.fmt_age(s, "ko") for s in (5, 60, 3600, 47 * 3600, 48 * 3600)] == ["A<now>", "A<1min>", "A<1hr>", "A<47hr>", "A<2day>"] and i18n.fmt_age(3 * 3600, "ko", quiet=True) == ">A<3hr>")
with i18n.use("ko"):
    check("the helpers follow the request's language", r2.ago(120) == "A<2min>" and r2.when_words(days[0]).startswith("D<w") and i18n.fmt_age(120) == "A<2min>")
check("…and are English again outside it", r2.ago(120) == "2m ago")

# the page scripts' twin of fmt_age and their SST lookup (node, when present): the same words in the same language as the helper
import shutil
if shutil.which("node"):
    harness = r"""
const head=process.argv[1], fa=process.argv[2], lang=JSON.parse(process.argv[3]);
const window={};  // the page head's script defines window.SSD / window.SST; the override the server puts in is window.SSI
const vm=require('vm');const ctx={window};vm.createContext(ctx);vm.runInContext(head.replace(/^<script>|<\/script>$/g,''),ctx);
if(lang)ctx.window.SSI=lang;
vm.runInContext('var SST=window.SST;'+fa+';var out=[];[0,5,59,60,61,3599,3600,7200,86399,86400,47*3600,48*3600,5*86400].forEach(function(s){out.push([fa(s),fa(s,true)])});'
  +'out.push(SST("js.sent_done",{who:"w"}),SST("no.such.key"),SST("js.copied"));',ctx);
process.stdout.write(JSON.stringify(vm.runInContext('out',ctx)));"""
    spans_js = [0, 5, 59, 60, 61, 3599, 3600, 7200, 86399, 86400, 47 * 3600, 48 * 3600, 5 * 86400]
    write_ko(test_locale()); reset_warned(); set_dir(LOC)
    for lg, table in (("en", None), ("ko", i18n.js_table("ko"))):
        sp = subprocess.run(["node", "-e", harness, r2._SST_HEAD, r2._AGE_FN, json.dumps(table)], capture_output=True, text=True, timeout=30)
        ok = sp.returncode == 0
        got = json.loads(sp.stdout) if ok else sp.stderr[-300:]
        want = [[i18n.fmt_age(s, lg), i18n.fmt_age(s, lg, quiet=True)] for s in spans_js]
        check(f"the page script's age function says what fmt_age says ({lg}), over the same spans, with and without the quiet mark", ok and got[:len(want)] == want, (got if not ok else [g for g, w in zip(got, want) if g != w][:2]))
        check(f"the page script's word lookup fills a field, returns an unknown key as it is, and follows the language ({lg})", ok and got[-3:] == [i18n.t("js.sent_done", lg, who="w"), "no.such.key", i18n.t("js.copied", lg)], got[-3:] if ok else got)
    set_dir(None)
else:
    print("note: node is not installed; the page scripts' age function was not run")

# ---- 3. the repository holds no Hangul, and every key a source asks for exists
HANGUL = re.compile("[%s-%s%s-%s%s-%s]" % tuple(chr(c) for c in (0xAC00, 0xD7A3, 0x3131, 0x318E, 0x1100, 0x11FF)))      # built from code points: this file holds no Hangul itself
bad = []
for p in pathlib.Path(STACK).rglob("*"):
    if p.is_file() and ".git" not in p.parts and p.suffix in {".py", ".md", ".toml", ".json", ".txt", ".yml", ".yaml", ".sh", ".html", ".js", ".css", ".svg"}:
        try: text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError): continue
        if HANGUL.search(text): bad.append(str(p.relative_to(STACK)))
check("no file of the repository holds a Hangul letter", not bad, bad[:5])
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
for rel in ("stackshot/web/ui/render.py", "stackshot/web/ui/kit.py", "stackshot/web/home.py", "stackshot/web/i18n.py", "stackshot/web/uiprefs.py", "stackshot/web/itempage.py"):
    used |= keys_in(pathlib.Path(STACK, rel).read_text(encoding="utf-8"))
check("every key a page or a script asks for by its literal name is in the English catalog", not [k for k in used if k not in EN and not any(e.startswith(k) for e in EN)], [k for k in used if k not in EN and not any(e.startswith(k) for e in EN)])
check("the state words and the panel sections the pages build a key for are all there", all(f"state.{k}" in EN for k in ("you", "agent", "release", "wait", "done", "dropped", "superseded", "closed"))
      and all(f"panel.sec.{s}" in EN for s in up.PANEL_SECTIONS) and all(f"panel.move.{a}" in EN for a in r2._PANEL_MOVES) and all(f"panel.lang.{c}" in EN for c in i18n.LANGS)
      and all(f"date.wd.{i}" in EN for i in range(7)) and all(f"date.mon.{i}" in EN for i in range(1, 13)))
check("the English state words are the ones the pages always said", r2._ui.WORDS == {"you": "Your move", "agent": "On agent", "release": "Queued for release", "wait": "Waiting", "done": "Done", "dropped": "Dropped", "superseded": "Superseded", "closed": "Closed"})

# ---- 4. uiprefs: the person's language
UI = up.path()
check("a person who never picked a language reads English, and so does nobody signed in", up.lang_of(MINA) == "en" and up.lang_of("") == "en" and not UI.exists())
check("set_lang stores a code of i18n.LANGS and reads back", up.set_lang(MINA, "ko") == "ko" and up.lang_of(MINA) == "ko" and json.loads(UI.read_text())["users"] == {MINA: {"lang": "ko"}}, UI.read_text())
check("…one person's language is not another's", up.lang_of(NOOR) == "en")
up.set_panel_open(MINA, False); up.set_panel_order(MINA, ["audit-panel", "machines"])
check("the language and the other settings keep each other", up.lang_of(MINA) == "ko" and up.panel_open(MINA) is False and up.panel_order(MINA)[0] == "audit-panel")
up.set_lang(MINA, "en")
check("English is stored as no key, and the other settings stay", "lang" not in json.loads(UI.read_text())["users"][MINA] and up.lang_of(MINA) == "en" and up.panel_open(MINA) is False)
up.set_panel_open(MINA, True); up.reset_panel_order(MINA)
check("a person left with no setting has no entry", json.loads(UI.read_text()) == {"users": {}}, UI.read_text())
before = UI.read_text()
refused = []
for bad_v in ("fr", "", "EN", None, 3, ["ko"], {"lang": "ko"}):
    try: up.set_lang(MINA, bad_v); refused.append(False)
    except ValueError: refused.append(True)
check("a value that is not one of i18n.LANGS is refused and nothing is written", all(refused) and UI.read_text() == before and not list(UI.parent.glob("*.tmp")), refused)
UI.write_text(json.dumps({"users": {MINA: {"lang": "fr"}, NOOR: {"lang": 7}}}), encoding="utf-8")
check("a stored value this version does not know reads as English", up.lang_of(MINA) == "en" and up.lang_of(NOOR) == "en")
real_read = pathlib.Path.read_text
def denied_read(self, *a, **k):
    if self == UI: raise PermissionError(13, "Permission denied")
    return real_read(self, *a, **k)
pathlib.Path.read_text = denied_read
try:
    try: up.set_lang(MINA, "ko"); raised = False
    except OSError: raised = True
    unread = up.lang_of(MINA)
finally: pathlib.Path.read_text = real_read
check("an unreadable settings file: a save raises, a read gives English", raised and unread == "en")
UI.unlink()

# ---- 5. the route, the switch and the pages
COOKIE = {e: _signin._ui_sign(json.dumps({"email": e, "exp": time.time() + 3600})) for e in (MINA, NOOR)}
SAME = {"Origin": BOARD}
JSON_H = {**SAME, "Content-Type": "application/json"}
search.sync(__import__("stackshot.web.render", fromlist=["_"]).Board(str(T / "store")))
def visible(h):
    """The page without its scripts and styles."""
    return re.sub(r"<script\b.*?</script>|<style\b.*?</style>", "", h, flags=re.S)
def lang_toggle(h):
    m = re.search(r'<div id="panel-lang".*?</div>', h, re.S); return m.group(0) if m else ""
with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def get(path, who=MINA):
        c.cookies.clear()
        if who: c.cookies.set(_signin._UI_COOKIE, COOKIE[who])
        return c.get(path, follow_redirects=False)
    def post(body, who=MINA, headers=JSON_H, raw=None, path="/prefs/lang"):
        c.cookies.clear()
        if who: c.cookies.set(_signin._UI_COOKIE, COOKIE[who])
        return c.post(path, content=raw if raw is not None else json.dumps(body), headers=headers, follow_redirects=False)

    # -- no folder configured: the pages are English, with no marker and no switch
    set_dir(None); reset_warned(); _web_board_home._board_home_drop()
    for who in (MINA, NOOR, None):
        h = get("/", who)
        check(f"no locale folder ({who or 'visitor'}): the home is English, <html lang=\"en\">, no marker, no switch, no script table override",
              h.status_code in (200, 302) and (h.status_code == 302 or ('<html lang="en">' in h.text and "[x:" not in h.text and 'id="panel-lang"' not in h.text and 'id="ssi"' not in h.text)), (who, h.status_code))
    # -- the route
    r = post({"lang": "ko"}, who=None)
    check("save: refused without sign-in (403)", r.status_code == 403, (r.status_code, r.text))
    r = post({"lang": "ko"}, headers={"Origin": "https://elsewhere.example.net", "Content-Type": "application/json"})
    check("save: refused from a foreign origin (403)", r.status_code == 403, (r.status_code, r.text))
    r = post(None, headers={**SAME, "Content-Type": "text/plain"}, raw='{"lang": "ko"}')
    check("save: refused without a JSON content type (415)", r.status_code == 415, (r.status_code, r.text))
    for body, why in (({"lang": "fr"}, "a code outside i18n.LANGS"), ({"lang": ""}, "an empty code"), ({"lang": 1}, "a number"), ({"language": "ko"}, "no `lang`"), (["ko"], "a list"), ({"lang": ["ko"]}, "a list value")):
        r = post(body)
        check(f"save: {why} is refused (400) with the usual 'send ...' text and nothing is stored", r.status_code == 400 and r.text.startswith("send ") and '{"lang": "ko"}' in r.text and not UI.exists(), (r.status_code, r.text))
    r = post(None, raw="{not json")
    check("save: a body that is not JSON is 400", r.status_code == 400, (r.status_code, r.text))
    check("save: a GET does not save (the route takes POST only)", get("/prefs/lang").status_code in (404, 405) and not UI.exists())
    r = post({"lang": "ko"})
    check("save: a good body answers the code and stores it for that person only", r.status_code == 200 and r.json() == {"lang": "ko"} and up.lang_of(MINA) == "ko" and up.lang_of(NOOR) == "en"
          and json.loads(UI.read_text())["users"] == {MINA: {"lang": "ko"}}, (r.status_code, r.text, UI.read_text()))
    check("…with the answer not cached", "no-store" in r.headers.get("cache-control", ""))
    r = post({"lang": "en"})
    check("save: English removes the key", r.status_code == 200 and r.json() == {"lang": "en"} and up.lang_of(MINA) == "en" and json.loads(UI.read_text()) == {"users": {}}, UI.read_text())
    # a saved language with no catalog behind it reads English and the page is not an error
    post({"lang": "ko"})
    h = get("/")
    check("a person who picked a language that has no catalog (no folder) gets the English page", h.status_code == 200 and '<html lang="en">' in h.text and "[x:" not in h.text and 'id="panel-lang"' not in h.text)
    post({"lang": "en"})

    # -- the test locale loaded: the switch, the language of the pages
    write_ko(test_locale()); set_dir(LOC); reset_warned(); _web_board_home._board_home_drop()
    en_home = get("/", NOOR).text
    check("English person, locale loaded: <html lang=\"en\">, the home in English with no marker, the switch drawn with EN pressed", '<html lang="en">' in en_home and "[x:" not in en_home and 'id="ssi"' not in en_home
          and 'data-lang="en"' in lang_toggle(en_home) and re.search(r'data-lang="en"[^>]*aria-pressed="true"', lang_toggle(en_home)) and re.search(r'data-lang="ko"[^>]*aria-pressed="false"', lang_toggle(en_home)), lang_toggle(en_home))
    check("the switch: a group labeled Language, two real buttons (focusable, in the tab order), each with a title, laid at the panel's foot after the sections",
          'role="group" aria-label="Language"' in lang_toggle(en_home) and len(re.findall(r'<button type="button" class="b plg"', lang_toggle(en_home))) == 2 and "tabindex" not in lang_toggle(en_home)
          and 'title="English"' in lang_toggle(en_home) and 'title="Korean"' in lang_toggle(en_home) and en_home.index("<!--ps:projects-panel-->") < en_home.index('id="panel-lang"') < en_home.index("</aside>"), lang_toggle(en_home))
    check("…and styled with the page's buttons (the b class), pressed in the accent", ".b" in en_home and "#panel-lang .plg[aria-pressed=true]" in en_home)
    check("the switch saves through /prefs/lang and reloads (its script, once)", en_home.count("fetch('/prefs/lang'") == 1 and "location.reload()" in en_home and "JSON.stringify({lang:b.getAttribute('data-lang')})" in en_home)
    for pth in ("/", "/items/a1", "/projects/alpha", "/closed", "/runners"):
        v, s_ = get(pth, None), get(pth, NOOR)
        check(f"signed out ({pth}), a catalog loaded: English page and no language switch; a signed-in person gets the switch", v.status_code == 200 and 'id="panel-lang"' not in v.text and '<html lang="en">' in v.text
              and s_.status_code == 200 and 'id="panel-lang"' in s_.text, (v.status_code, 'id="panel-lang"' in v.text, s_.status_code, 'id="panel-lang"' in s_.text))
    check("the switch taken out leaves the rest of the page as it was; a page with none comes back as it was",
          r2.strip_lang_toggle(en_home) == en_home.replace("\n" + lang_toggle(en_home), "", 1) and 'id="panel-lang"' not in r2.strip_lang_toggle(en_home) and r2.strip_lang_toggle("<p>x</p>") == "<p>x</p>")
    r = post({"lang": "ko"})
    ko_home = get("/", MINA).text
    check("a person who picked it: <html lang=\"ko\"> and the script words put over the English ones", '<html lang="ko">' in ko_home and 'id="ssi"' in ko_home and "window.SSI=" in ko_home and MARK("Copied") in ko_home)
    check("…with the switch drawn and KO pressed", re.search(r'data-lang="ko"[^>]*aria-pressed="true"', lang_toggle(ko_home)) and re.search(r'data-lang="en"[^>]*aria-pressed="false"', lang_toggle(ko_home)), lang_toggle(ko_home))
    kv = visible(ko_home)
    check("the side panel's chrome is in the test locale (title, buttons, section names, move menu, the language group)", all(MARK(s) in ko_home for s in (
        "Summary", "Summary panel", "Hide summary panel", "Close summary panel", "Move section", "Move up", "Move to bottom", "Machines", "Runners", "Audit", "Projects", "Language")), [s for s in ("Summary", "Machines", "Language") if MARK(s) not in ko_home])
    check("the home's headings, count cards and state words are in the test locale", all(MARK(s) in kv for s in ("Your move", "On agent", "Queued for release", "Waiting", "Closed", "Counts")), [s for s in ("Your move", "On agent", "Waiting", "Closed") if MARK(s) not in kv])
    check("the home's empty lists and its connection notice are in the test locale", MARK("nothing waits on you") in kv or MARK("no agent has an open item") in kv, kv[:200])
    check("the fixed buttons every page carries are in the test locale", f'aria-label="{MARK("Reload")}" title="{MARK("Reload page")}"' in ko_home and f'aria-label="{MARK("Back to top")}"' in ko_home and 'aria-label="Reload"' not in ko_home)
    check("the rendered line and the ages are in the test locale (the age template, the 'rendered' word)", re.search(r"A<(now|\d+min|\d+hr|\d+day)>", kv) is not None and re.search(r'<p class="rline"><span class="rw">\[x:rendered </span><span id="rendered"[^>]*>.*?</span></span><span class="rw">\]</span></p>', kv, re.S) and " ago<" not in kv, re.findall(r"A<[^>]*>|\d+[mhd] ago|just now", kv)[:6])
    check("the item's title and the rest of the item's text stay English", TITLE in kv and MARK(TITLE) not in ko_home and "the next step" in kv and "[x:the next step]" not in ko_home)
    check("the search box in the header is in the test locale (placeholder, label, button) and English for the English person", f'placeholder="{MARK("Search items, history, projects, sessions")}"' in ko_home and f'aria-label="{MARK("Search the board")}"' in ko_home
          and f'aria-label="{MARK("Search")}" title="{MARK("Search")}"' in ko_home and 'placeholder="Search items, history, projects, sessions"' in en_home and 'aria-label="Search" title="Search"' in en_home)
    check("the theme button's label is in the test locale, and the script words carry it", f'aria-label="{MARK("Theme: system")}"' in ko_home and MARK("Theme: dark") in ko_home)
    en_vis = visible(en_home)
    check("the same page for an English person has the same English words where the other has the markers", all(s in en_vis for s in ("Your move", "On agent", "Waiting", "Closed")) and "A<" not in en_vis and re.search(r"\b(just now|\d+[mhd] ago)\b", en_vis))
    check("English output is what it was: the panel's English constants appear as they always did", r2._PANEL_BTN in en_home and "Hide summary panel" in en_home and '<span class="ptitle">Summary</span>' in en_home and 'aria-label="Reload" title="Reload page"' in en_home)
    # other pages: the panel follows the person's language, the item text does not
    item_ko = get("/items/a1", MINA).text; item_en = get("/items/a1", NOOR).text
    check("an item page: <html lang> follows the person and the side panel is in their language, the item text stays English",
          '<html lang="ko">' in item_ko and MARK("Summary") in item_ko and TITLE in item_ko and MARK(TITLE) not in item_ko and '<html lang="en">' in item_en and "[x:" not in item_en and TITLE in item_en)
    proj_ko = get("/projects/alpha", MINA).text
    check("a project page: the same, and nothing breaks on a page that is not converted yet", '<html lang="ko">' in proj_ko and MARK("Summary") in proj_ko and "Alpha" in proj_ko, (proj_ko.count("ALPHA"), proj_ko[:200]))
    # the kept draws
    _web_board_home._board_home_drop(); get("/", NOOR); get("/", MINA)
    kept_en, kept_ko = _web_board_home._BOARD_HOME["html"], _web_board_home._BOARD_HOME_OTHER.get("ko", {}).get("html")
    check("the home keeps one draw per language: English in the English slot, the test locale in its own", kept_en and "[x:" not in kept_en and kept_ko and MARK("Your move") in kept_ko and kept_ko != kept_en)
    check("…the kept English draw is what the English person is served", "[x:" not in kept_en and re.search(r"Your move", kept_en) is not None and get("/", NOOR).text == kept_en, None)
    _web_board_home._board_home_drop()
    check("a drop clears every language's draw", _web_board_home._BOARD_HOME["at"] == 0.0 and all(s["at"] == 0.0 for s in _web_board_home._BOARD_HOME_OTHER.values()))
    st_en = get("/render-stamp", NOOR); st_ko = get("/render-stamp", MINA)
    check("the render stamp answers for the person's own draw (JSON, a ts)", st_en.status_code in (200, 503) and st_ko.status_code in (200, 503) and (st_ko.status_code == 503 or isinstance(st_ko.json().get("ts"), int)), (st_en.status_code, st_ko.text))
    r = post({"lang": "en"})
    back = get("/", MINA).text
    check("a round trip: back to English, <html lang=\"en\">, no marker, the switch still drawn", '<html lang="en">' in back and "[x:" not in back and 'id="panel-lang"' in back and 'id="ssi"' not in back)
    get("/", NOOR); held_at = _web_board_home._BOARD_HOME["at"]; held_html = _web_board_home._BOARD_HOME["html"]
    post({"lang": "ko"}); post({"lang": "en"})
    check("a save of the language leaves the kept draws alone (a toggle is not a write to the board)", held_at > 0 and _web_board_home._BOARD_HOME["at"] == held_at and _web_board_home._BOARD_HOME["html"] is held_html)
    # the file goes away: the switch goes with it, the person's choice stays stored and reads English
    post({"lang": "ko"}); (LOC / "ko.json").unlink(); reset_warned()
    with quiet_err():
        gone = get("/", MINA).text
    check("the catalog gone: the person reads English, no switch, no error, and their choice is still stored", gone and '<html lang="en">' in gone and "[x:" not in gone and 'id="panel-lang"' not in gone and up.lang_of(MINA) == "ko")
    write_ko(test_locale()); reset_warned()
    check("…and the catalog back: the choice shows again with no new save", '<html lang="ko">' in get("/", MINA).text)
    write_ko({"no.such.key": "x"}); reset_warned()
    with quiet_err():
        unusable = get("/", MINA).text
    check("a file with no usable key: the person with that choice reads English, <html lang=\"en\">, no switch, no script table override", '<html lang="en">' in unusable and 'id="panel-lang"' not in unusable and 'id="ssi"' not in unusable and "[x:" not in unusable)
    write_ko(test_locale()); reset_warned()
    # a value in the file that is wrong for the page: that string is English, the rest still the test locale
    write_ko(test_locale(**{"panel.title": "Summary {oops}", "home.counts": MARK("Counts")})); reset_warned()
    with quiet_err():
        part = get("/", MINA).text
    check("one refused value in the file: that string is English and the rest of the page is still in the test locale", '<span class="ptitle">Summary</span>' in part and MARK("Summary panel") in part and MARK("Your move") in visible(part))
    post({"lang": "en"})

# ---- 6. apply_lang on its own
page = '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>x</title></head><body><button aria-label="Reload" title="Reload page">r</button></body></html>'
write_ko(test_locale()); reset_warned()
out = r2.apply_lang(page, "ko")
check("apply_lang: <html lang>, the script table ahead of the page's own scripts and the fixed buttons", '<html lang="ko">' in out and '<meta charset="utf-8"><script id="ssi">window.SSI=' in out and f'aria-label="{MARK("Reload")}"' in out)
check("apply_lang: English comes back as it was, and a page already done is not done twice", r2.apply_lang(page, "en") == page and r2.apply_lang(out, "ko") == out)
check("apply_lang: the script table holds the keys the scripts ask for, in the language", json.loads(re.search(r"window.SSI=(\{.*?\});</script>", out, re.S).group(1))["js.copied"] == MARK("Copied"))
check("the English table in every page head is the catalog's own (a script never carries a copy of a word)", r2._SST_HEAD.count("window.SSD=") == 1 and json.dumps(i18n.js_table("en")).replace("</", "<\\/") in r2._SST_HEAD)

# ---- 7. ui.render imported for the first time while a request's language is not English: its module-level words are the English ones
IMPORT_PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from stackshot.core import config as C
if sys.argv[3] != "en": C.CFG.setdefault("ui", {})["locale_dir"] = sys.argv[2]
from stackshot.web import i18n
if sys.argv[3] != "en": assert i18n.available() == ["en", sys.argv[3]]; i18n.set_current(sys.argv[3])
from stackshot.web.ui import render as r
print(json.dumps({k: v for k, v in vars(r).items() if not k.startswith("__") and isinstance(v, (str, dict, list, tuple)) and k != "_ui"}, sort_keys=True, default=repr))
"""
write_ko(test_locale()); reset_warned()
runs = {}
for lg in ("en", "ko"):
    sp = subprocess.run([sys.executable, "-c", IMPORT_PROBE, STACK, str(LOC), lg], capture_output=True, text=True, timeout=120, cwd=STACK)
    runs[lg] = json.loads(sp.stdout) if sp.returncode == 0 and sp.stdout.strip() else sp.stderr[-400:]
ok_runs = all(isinstance(v, dict) for v in runs.values())
check("ui.render imported first under a non-English request language: every module-level value is what an English import gives", ok_runs and runs["ko"] == runs["en"], runs if not ok_runs else [k for k in runs["en"] if runs["en"][k] != runs["ko"].get(k)][:5])
_ko = runs["ko"] if ok_runs else {}
_lane_words = {k: r2._ui.WORDS.get(v) for k, v in _ko.get("_LANE_KINDS", {}).items()}      # the lists' words per lane and state, from the module's own tables
_state_words = {k: r2._ui.WORDS.get(v) for k, v in _ko.get("_STATE_KINDS", {}).items()}
check("…in particular the lists' state and lane words are the English ones, and no marker of the test language anywhere in the module", ok_runs and _state_words.get("doing") == "On agent" and _lane_words.get("call") == "Your move" and "[x:" not in json.dumps(_ko), _state_words)

# ---- 8. the item page: every interface word of it reads through the string table (stage 2)
# item-page fixture begin
IPX = pathlib.Path(tmp)
B_ = "B2222222-2222-4222-8222-222222222222".lower()
(IPX / "fleet/a/sessions.json").write_text(json.dumps({A: {"name": "alpha-main", "machine": "a", "url": "", "seen": "x"}, B_: {"name": "alpha-helper", "machine": "a", "url": "", "seen": "x"}}))
_pj = json.loads((IPX / "store/projects.json").read_text())
_pj["pages"]["projects/beta"] = {"title": "Beta", "name": "Beta", "org": "work", "tags": [], "type": "project", "session": "alpha-main", "status": "active", "board": [], "board_row": False, "updated": 1,
                                 "mirror": "https://example.invalid/beta", "agents": {"alpha-main": "builds"}}
(IPX / "store/projects.json").write_text(json.dumps(_pj))
HR = 3600.0; DY = 86400.0
def ix(i, subject, status="open", su=None, written_by="alpha-main", **meta):
    su = now0 - 3 * HR if su is None else su
    d = {"id": str(i), "subject": f"[work] {subject}", "description": "- a made-up thing\n- it lives in a drawer", "status": status, "updated": su, "state_updated": su, "confirmed": su,
         "metadata": {"owner": A, "project": "projects/alpha", **meta}}
    if written_by: d["written_by"] = written_by
    (IPX / f"store/a/{i}.json").write_text(json.dumps(d))
def ic(i, meta=None, drop=(), **top):          # a later revision of an item, committed to the store's git
    p = IPX / f"store/a/{i}.json"; d = json.loads(p.read_text()); d.update(top); d["metadata"].update(meta or {})
    for k_ in drop: d["metadata"].pop(k_, None)
    p.write_text(json.dumps(d)); git("add", "-A"); git("commit", "-q", "-m", f"ipx {i}")
OWN = "the owner"
ASKX = "Decide: whether to buy it · Recommend: buy · Stakes: none either way · By: no date"
OPX = [{"label": "Buy", "line": "Buy it now", "recommended": True}, {"label": "Skip", "line": "Skip it", "recommended": False}]
ST = lambda t_, s_="open", by="", at=0, **k_: {"text": t_, "status": s_, "by": by, "at": at, **k_}
# 201: one item that has been through most of what the History can say
S1, S2, S3, S4, S5 = "alpha-main: oil the hinges", "alpha-main: sand the rails", "alpha-main: paint the frame", "alpha-main: hang the sign", "alpha-main: wipe the glass"
NX = lambda *x: "\n".join(x)
ix(201, "Shelf audit", mover="alpha-main", next=NX(S1, S2, S3, S4, S5), su=now0 - 40 * HR)
git("add", "-A"); git("commit", "-q", "-m", "ipx base")
ic(201, {"steps": [ST(S1, "done", "alpha-main", now0 - 30 * HR)], "next": NX(S2, S3, S4, S5)}, updated=now0 - 30 * HR)
ic(201, {"steps": [ST(S1, "done", "alpha-main", now0 - 30 * HR), ST(S2, "dropped", "alpha-main", now0 - 29 * HR)], "next": NX(S3, S4, S5)}, updated=now0 - 29 * HR)
TG = lambda t_, s_="in progress", ts=0: {"text": t_, "state": s_, "ts": ts}
BASE = [ST(S1, "done", "alpha-main", now0 - 30 * HR), ST(S2, "dropped", "alpha-main", now0 - 29 * HR)]
ic(201, {"steps": BASE + [ST(S3, tag=TG("first coat on", ts=now0 - 28 * HR)), ST(S4, tag=TG("sign cut", "assigned", now0 - 28 * HR))]}, updated=now0 - 28 * HR)
ic(201, {"steps": BASE + [ST(S3, tag=TG("second coat on", ts=now0 - 27 * HR)), ST(S4, tag=TG("sign cut", "assigned", now0 - 28 * HR))]}, updated=now0 - 27 * HR)
ic(201, {"steps": BASE + [ST(S3, "done", "alpha-main", now0 - 26 * HR, tag=TG("second coat on", ts=now0 - 27 * HR)), ST(S4, tag=TG("sign cut", "assigned", now0 - 28 * HR))], "next": NX(S4, S5)}, updated=now0 - 26 * HR)
ic(201, {"steps": BASE + [ST(S3, "done", "alpha-main", now0 - 26 * HR), ST(S4), ST(S5, tag=TG("glass cloth found", ts=now0 - 25 * HR))]}, updated=now0 - 25 * HR)
ic(201, {"priority": "p1", "due": "2099-03-01", "rank": "3"}, updated=now0 - 24 * HR)
ic(201, {"due": "2099-04-01", "draft": "a first draft of the sign text", "rank": "2"}, updated=now0 - 23 * HR)
ic(201, {"due": "", "draft": "a second draft of the sign text", "project": "projects/beta"}, drop=("rank",), updated=now0 - 22 * HR, subject="[work] Shelf audit, renamed")
ic(201, {"draft": "", "state": "verifying", "proof": "the sign hangs straight", "end": "2099-06-01"}, updated=now0 - 21 * HR)
ic(201, {"state": "doing", "priority": "p2"}, drop=("proof", "end"), updated=now0 - 20 * HR)
ic(201, {"state": "your-call"}, updated=now0 - 19 * HR)
ic(201, {}, drop=("state",), updated=now0 - 18 * HR)
ic(201, {"next": NX(S4, S5, "alpha-main: sweep the floor"), "ask": "", "steps": BASE + [ST(S3, "done", "alpha-main", now0 - 26 * HR), ST(S4), ST(S5, tag=TG("glass cloth found", ts=now0 - 25 * HR))]}, updated=now0 - 17 * HR,
   description="- a made-up thing\n- it lives in a drawer\n- a third fact")
# 202: a decision asked and answered by a pick; 203 the same answered with a note only; 204 a closed one with its outcome
ix(202, "Lamp purchase", mover=OWN, needs=["decision"], ask=ASKX, options=OPX, next=f"{OWN}: decide", su=now0 - 20 * HR); git("add", "-A"); git("commit", "-q", "-m", "ipx 202")
ic(202, {"needs": [], "ask": "", "options": [], "mover": "alpha-main", "next": "alpha-main: order the lamp", "answers": [{"ts": now0 - 19 * HR, "kind": "decision", "choice": "Buy", "letter": "A", "text": "yes, from the usual shop", "via": "", "options": OPX}]}, written_by=OWN, updated=now0 - 19 * HR)
ix(203, "Cable choice", mover=OWN, needs=["decision"], ask=ASKX, options=OPX, next=f"{OWN}: decide", su=now0 - 20 * HR); git("add", "-A"); git("commit", "-q", "-m", "ipx 203")
ic(203, {"needs": [], "mover": "alpha-main", "next": "alpha-main: look again", "answers": [{"ts": now0 - 19 * HR, "kind": "decision", "text": "neither, look again", "via": "", "options": OPX}, {"ts": now0 - 18 * HR, "kind": "comment", "text": "a later note"},
   {"ts": now0 - 17 * HR, "kind": "step-reply", "text": "a note on the step"}]}, written_by=OWN, updated=now0 - 17 * HR)
ic(203, {"needs": ["alpha-helper"], "next": "alpha-helper: check it"}, written_by="alpha-main", updated=now0 - 16 * HR)
ic(203, {"needs": []}, written_by="alpha-main", updated=now0 - 15 * HR)
ic(203, {"answers": [{"ts": now0 - 19 * HR, "kind": "decision", "text": "neither, look again", "via": "", "options": OPX}, {"ts": now0 - 18 * HR, "kind": "comment", "text": "a later note"},
   {"ts": now0 - 17 * HR, "kind": "step-reply", "text": "a note on the step"},
   {"ts": now0 - 14 * HR, "kind": "comment", "text": "written on the issue", "via": "github", "url": "https://github.com/o/r/issues/5#issuecomment-9", "comment_id": 9}]}, written_by="alpha-main", updated=now0 - 14 * HR)
ic(203, {"answers": [{"ts": now0 - 19 * HR, "kind": "decision", "text": "neither, look again", "via": "", "options": OPX}, {"ts": now0 - 18 * HR, "kind": "comment", "text": "a later note"},
   {"ts": now0 - 17 * HR, "kind": "step-reply", "text": "a note on the step"},
   {"ts": now0 - 14 * HR, "kind": "comment", "text": "written on the issue", "via": "github", "url": "https://github.com/o/r/issues/5#issuecomment-9", "comment_id": 9},
   {"ts": now0 - 13 * HR, "kind": "comment", "text": "written on the issue, no link", "via": "github"}]}, written_by="alpha-main", updated=now0 - 13 * HR)
ic(203, {}, written_by="alpha-main", updated=now0 - 13 * HR, confirmed=now0 - 12 * HR)          # a confirm with nothing else changed
# 204: on hold with a wake, the wake moved, released; closed with an outcome; reopened; closed superseded
ix(204, "Drawer clean-out", mover="alpha-main", next="alpha-main: empty it", su=now0 - 50 * HR); git("add", "-A"); git("commit", "-q", "-m", "ipx 204")
ic(204, {"hold": True, "wake": "2099-02-01"}, updated=now0 - 49 * HR)
ic(204, {"wake": "2099-02-15T10:00"}, updated=now0 - 48 * HR)
ic(204, {"wake": ""}, updated=now0 - 47 * HR)
ic(204, {"wake": "2099-02-20"}, updated=now0 - 46 * HR)
ic(204, {"hold": False, "wake": ""}, updated=now0 - 45 * HR)
ic(204, {"hold": True}, updated=now0 - 44 * HR)
ic(204, {"hold": False}, updated=now0 - 43 * HR)
ic(204, {"wake": "2099-03-05"}, updated=now0 - 42 * HR)
ic(204, {"wake": "2099-03-09"}, updated=now0 - 41 * HR)
ic(204, {"wake": ""}, updated=now0 - 40 * HR)
ic(204, {"after": ["a201"]}, updated=now0 - 39 * HR)
ic(204, {"after": []}, updated=now0 - 38 * HR)
ic(204, {"outcome": "done", "reason": "the drawer is empty", "superseded_by": ""}, status="completed", updated=now0 - 37 * HR, written_by="alpha-main")
ic(204, {}, drop=("outcome", "reason"), status="open", updated=now0 - 36 * HR)
ic(204, {"outcome": "dropped", "reason": "not needed any more"}, status="completed", updated=now0 - 35 * HR, written_by="alpha-helper")
ic(204, {}, drop=("outcome", "reason"), status="open", updated=now0 - 34 * HR - 1800)
ic(204, {"outcome": "superseded", "superseded_by": "a201", "reason": ""}, status="completed", updated=now0 - 34 * HR, written_by="alpha-main")
# 205: handovers
ix(205, "Cupboard move", mover="alpha-main", next="alpha-main: first part\nalpha-helper: second part", su=now0 - 12 * HR); git("add", "-A"); git("commit", "-q", "-m", "ipx 205")
ic(205, {"mover": "alpha-helper", "needs": ["alpha-helper"], "handover": {"step": "aaaaaaaaaaaa", "kind": "moved", "to": "alpha-helper", "at": now0 - 11 * HR}}, written_by="", updated=now0 - 11 * HR)
ic(205, {"mover": "alpha-main", "needs": ["alpha-main"], "next": "alpha-main: third part", "handover": {"step": "bbbbbbbbbbbb", "kind": "fallback", "to": "alpha-gone", "at": now0 - 10 * HR, "why": "no pane of it is in the heartbeat"}}, written_by="", updated=now0 - 10 * HR)
ic(205, {"mover": "alpha-helper", "needs": ["alpha-helper"], "next": "alpha-helper: fourth part"}, written_by="alpha-main", updated=now0 - 9 * HR)
ic(205, {"needs": []}, written_by="alpha-main", updated=now0 - 8 * HR)
# waits of each kind, a chase, his words, the recycle badge, an observer, a stale confirm, an after
ix(210, "Time wait", wait_kind="time", wake="2099-01-01", post_wake_mover="alpha-helper", next="alpha-helper: check the date", wait_basis={"text": "the shop's holiday", "wake": "2099-01-01"},
   cap_ok={"wake": "2099-01-01", "quote": "wait until the new year", "source": "chat", "by": OWN}, recycle=True, observers=["alpha-helper"], due="2099-01-05", confirmed=now0 - 90 * DY, su=now0 - 90 * DY)
ix(211, "Item wait", wait_kind="item", after=["a201", "a210"], post_wake_mover="alpha-helper", next="alpha-helper: go on")
ix(212, "Item wait, no ids", wait_kind="item", after=[], post_wake_mover="alpha-helper", next="alpha-helper: go on")
ix(213, "Anchor wait", wait_kind="anchor", wait_anchor="https://github.com/o/r/pull/9", wait_event="the review lands", post_wake_mover="alpha-helper", wake="2099-02-01",
   chases=[{"at": now0 - 2 * HR, "by": "alpha-main", "note": "asked in the thread"}, {"at": now0 - HR, "by": "alpha-main", "note": "pinged the reviewer"}], next="alpha-main: wait for it")
ix(214, "Anchor wait, no event", wait_kind="anchor", wait_anchor="", post_wake_mover="alpha-helper", next="alpha-main: wait for it")
ix(215, "Relay wait", wait_kind="relay", wait_event="the contract", party="Acme", ask_by="2099-03-01", post_wake_mover="alpha-helper", next="alpha-helper: read it")
ix(216, "Relay wait, no event", wait_kind="relay", party="Acme", ask_by="2099-03-01", post_wake_mover="alpha-helper", next="alpha-helper: read it")
ix(217, "Relay wait, nobody", wait_kind="relay", ask_by="2099-03-01", post_wake_mover="alpha-helper", next="alpha-helper: read it")
ix(218, "Event wait", wait_kind="event", wait_event="a box comes up", post_wake_mover="alpha-helper", wake="2099-02-01", next="alpha-helper: use it")
ix(219, "Event wait, plain", wait_kind="event", post_wake_mover="alpha-helper", wake="2099-02-01", next="alpha-helper: use it")
ix(220, "Anchor wait, plain", wait_kind="anchor", wait_anchor="https://github.com/o/r/pull/9", post_wake_mover="alpha-helper", wake="2099-02-01", next="alpha-helper: use it")
ix(221, "Time wait, no words", wait_kind="time", wake="2099-01-01", post_wake_mover="alpha-helper", next="alpha-helper: check the date")
# links, a closed one, a reminder, a long checklist with decided rows
# a coding-session link, put together from parts so that no literal of this file has the shape of one
SESSLINK = "/".join(["https:", "", "claude" + ".ai", "code", "_".join(["sess" + "ion", "abc"])])
ix(230, "Links", mover="alpha-main", next="alpha-main: see https://docs.google.com/document/d/abc/edit and https://docs.google.com/spreadsheets/d/abc/edit and https://docs.google.com/presentation/d/abc/edit "
   "and https://docs.google.com/forms/d/abc and https://github.com/o/r/releases and " + SESSLINK + " and https://example.com/mockups/m1.html and https://github.com/o/r/blob/main/a/b.md and https://github.com/o/r/pull/3 and https://github.com/o/r/issues/4")
ix(231, "Reminder", mover="alpha-main", wake="2099-02-01", next="alpha-main: later")
ix(232, "Closed, no outcome", status="completed", su=now0 - 2 * DY, mover=None, outcome="unrecorded")
ix(233, "Closed, done", status="completed", su=now0 - 2 * DY, mover=None, outcome="done", reason="finished as asked", outcome_text="- it finished\n- nothing is left", steps=[ST("alpha-main: one", "done", "alpha-main", now0 - 3 * DY), ST("alpha-main: two", "dropped", "alpha-main", now0 - 3 * DY),
   ST("alpha-main: three", "done", "alpha-main", now0 - 3 * DY), ST("alpha-main: four", "done", "alpha-main", now0 - 3 * DY)])
ix(234, "Closed, all done", status="completed", su=now0 - 2 * DY, mover=None, outcome="done", reason="finished", outcome_text="- it finished", steps=[ST("alpha-main: one", "done", "alpha-main", now0 - 3 * DY), ST("alpha-main: two", "done", "alpha-main", now0 - 3 * DY)])
ix(235, "Decision rows", mover=OWN, needs=["decision"], ask=ASKX, options=OPX, next=f"{OWN}: decide\nalpha-main: after", su=now0 - 5 * HR,
   steps=[ST("alpha-main: one", "done", "alpha-main", now0 - 3 * HR), ST("alpha-main: two", "dropped", "alpha-main", now0 - 3 * HR), ST("alpha-main: three", "done", "alpha-main", now0 - 3 * HR)],
   answers=[{"ts": now0 - 4 * HR, "kind": "decision", "choice": "Buy", "letter": "A", "text": "", "via": "", "options": OPX}])
ix(236, "Misshaped ask", mover=OWN, needs=["decision"], ask="whether to buy the lamp", next=f"{OWN}: decide")
ix(237, "Project missing", mover="alpha-main", project="projects/nowhere", next="alpha-main: x")
ix(238, "Handed to a session", mover="alpha-helper", next="alpha-helper: x", handoff={"to": "alpha-helper", "from": "alpha-main", "at": now0 - 600, "delivered_at": now0 - 590, "taken_at": None})
ix(239, "Handed to the owner", mover=OWN, next=f"{OWN}: do it", handoff={"to": OWN, "from": "alpha-main", "at": now0 - 600, "delivered_at": None, "taken_at": None, "no_clock": True})
ix(240, "Your step", mover=OWN, state="your-step", step="open the drawer and say done", next="alpha-main: check it")
ix(241, "Open question", mover=OWN, needs=["decision"], ask=ASKX, next=f"{OWN}: decide")
ix(242, "Verifying", state="verifying", proof="the drawer opens", end="2099-01-01", needs=["alpha-helper"], mover="alpha-helper", next="alpha-helper: check it")
ix(243, "Observers", mover="alpha-main", observers=["alpha-helper"], next="alpha-main: x", after=["a201", "a210"])
ix(244, "Stale", mover="alpha-main", next="alpha-main: x", confirmed=now0 - 90 * DY, su=now0 - 90 * DY, due="2099-01-05")
# more cases: no creator, a broken option list, a then, a wait after a closed item, an item with all steps done, one with a long History, an item whose project and hold change, anchors
ix(245, "No creator", written_by="", owner="", mover="alpha-main", next="alpha-main: x"); git("add", "-A"); git("commit", "-q", "-m", "ipx 245")
ic(245, {"owner": A}, updated=now0 - 2 * HR)
ix(246, "Broken options", mover=OWN, needs=["decision"], ask=ASKX, options=[{"bogus": 1}], next=f"{OWN}: decide")
ix(247, "A then", mover=OWN, then="alpha-helper", needs=["decision"], ask=ASKX, options=OPX, next=f"{OWN}: decide\nalpha-helper: after")
ix(248, "Wait after a closed one", wait_kind="item", after=["a232", "a201"], post_wake_mover="alpha-helper", next="alpha-helper: go on")
ix(249, "All steps done", mover="alpha-main", next="", steps=[ST("alpha-main: one", "done", "alpha-main", now0 - 3 * HR), ST("alpha-main: two", "done", "alpha-main", now0 - 3 * HR), ST("alpha-main: three", "done", "alpha-main", now0 - 3 * HR)])
ix(250, "Project, hold and handover", mover="alpha-main", next="alpha-main: x"); git("add", "-A"); git("commit", "-q", "-m", "ipx 250")
ic(250, {"project": ""}, updated=now0 - 9 * HR)
ic(250, {"project": "projects/alpha", "hold": True, "needs": ["alpha-helper"]}, updated=now0 - 8 * HR)
ic(250, {"hold": False, "needs": []}, updated=now0 - 7 * HR)
ic(250, {"mover": "", "handover": {"step": "cccccccccccc", "kind": "moved", "to": "alpha-helper", "at": now0 - 6 * HR}}, updated=now0 - 6 * HR)
ic(250, {"mover": "", "handover": {"step": "dddddddddddd", "kind": "fallback", "to": "alpha-gone", "at": now0 - 5 * HR}}, updated=now0 - 5 * HR)
ic(250, {"needs": ["decision"], "ask": ASKX}, updated=now0 - int(4.8 * HR))          # the lane moves to his call: "asked"
ic(250, {"needs": [], "ask": ""}, updated=now0 - int(4.6 * HR))                      # and back to the agent: "back_to_work"
ic(250, {"state": "your-step"}, updated=now0 - int(4.4 * HR))
ic(250, {"needs": ["decision"], "ask": ASKX}, updated=now0 - int(4.2 * HR))          # his call while the state is a step of his: "gave_step"
ix(253, "Handovers from and to a wait", mover="alpha-main", next="alpha-main: x"); git("add", "-A"); git("commit", "-q", "-m", "ipx 253")
ic(253, {"wait_kind": "time", "wake": "2099-01-01", "post_wake_mover": "alpha-helper", "next": "alpha-helper: later", "handover": {"step": "eeeeeeeeeeee", "kind": "moved", "to": "alpha-helper", "at": now0 - 4 * HR}}, updated=now0 - 4 * HR)
ic(253, {"mover": "alpha-main", "next": "alpha-main: again", "handover": {"step": "ffffffffffff", "kind": "moved", "to": "alpha-main", "at": now0 - 3 * HR}}, drop=("wait_kind", "wake", "post_wake_mover"), updated=now0 - 3 * HR)
ic(253, {"mover": "no one", "handover": {"step": "gggggggggggg", "kind": "fallback", "to": "alpha-gone", "at": now0 - 2 * HR}}, updated=now0 - 2 * HR)
ix(254, "Born on hold", mover="alpha-main", hold=True, wake="2099-02-01", next="alpha-main: x")
ix(255, "No description, no steps", mover="alpha-main")
_d255 = json.loads((IPX / "store/a/255.json").read_text()); _d255["description"] = ""; (IPX / "store/a/255.json").write_text(json.dumps(_d255))
ix(256, "Owner unnamed", written_by="", owner="", mover="alpha-main", next="alpha-main: x")
ix(257, "Stale question", mover=OWN, needs=["decision"], ask=ASKX, options=OPX, next=f"{OWN}: decide", su=now0 - 90 * DY)
ix(258, "Closed without a word", mover="alpha-main", next="alpha-main: x", su=now0 - 5 * HR); git("add", "-A"); git("commit", "-q", "-m", "ipx 258")
ic(258, {"outcome": "unrecorded"}, status="completed", updated=now0 - 4 * HR, written_by="alpha-main")
# 259: names and values that carry markup, where the History puts a person's or session's own text into a template (the rank that was cleared, who closed it, the GitHub comment's text)
ESC_RANK, ESC_BY, ESC_GH = "<u>3</u>", "<s>closer</s>", '<i>hi</i> & "q"'
ix(259, "Escapes", mover="alpha-main", next="alpha-main: x", su=now0 - 6 * HR); git("add", "-A"); git("commit", "-q", "-m", "ipx 259")
ic(259, {"rank": ESC_RANK}, updated=now0 - 5 * HR)
ic(259, {}, drop=("rank",), updated=now0 - 4 * HR)
ic(259, {"next": ""}, updated=now0 - int(3.5 * HR))
ic(259, {"outcome": "done"}, status="completed", updated=now0 - 3 * HR, written_by=ESC_BY)
ic(259, {"answers": [{"ts": now0 - 2 * HR, "kind": "comment", "text": ESC_GH, "via": "github", "url": "https://github.com/o/r/issues/5#issuecomment-8", "comment_id": 8}]}, written_by=ESC_BY, updated=now0 - 2 * HR)
# 260: a wait on a list of waits (every kind of line, one already arrived), so the list's own words show on a page
ix(260, "A list of waits", hold=True, wait_kind="list", wait_mode="all", until="2099-01-05", post_wake_mover="alpha-main", next="alpha-main: go on", watch={"set_at": now0 - 2 * HR},
   waits=[{"kind": "time", "until": "2099-01-03", "arrived": {"at": now0 - HR, "what": "its date came"}}, {"kind": "anchor", "anchor": "https://github.com/o/r/pull/9", "event": "PR merged"}, {"kind": "item", "after": "a201"},
          {"kind": "relay", "event": "the lease"}, {"kind": "event", "event": "the box restarts"}])
ix(261, "A list of waits, either", hold=True, wait_kind="list", wait_mode="any", until="2099-01-05", post_wake_mover="alpha-main", next="alpha-main: go on", watch={"set_at": now0 - 2 * HR},
   waits=[{"kind": "relay", "event": "the lease"}, {"kind": "anchor", "anchor": "https://github.com/o/r/pull/9", "event": "PR merged", "arrived": {"at": now0 - HR, "what": "PR merged"}}])
ix(251, "A long History", mover="alpha-main", next="alpha-main: x", priority="p2"); git("add", "-A"); git("commit", "-q", "-m", "ipx 251")
for n_ in range(56): ic(251, {"priority": "p1" if n_ % 2 == 0 else "p3"}, updated=now0 - (100 - n_) * 60)
(IPX / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": "https://github.com/o/r/pull/9", "items": ["a201"], "added": 1, "by": "t"}], "projects/beta": [{"url": "https://github.com/o/r/pull/10", "items": ["a201"], "added": 1, "by": "t"}]}))
git("add", "-A"); git("commit", "-q", "-m", "ipx all")
IPX_IDS = [201, 202, 203, 204, 205, 210, 211, 212, 213, 214, 215, 216, 217, 218, 219, 220, 221, 230, 231, 232, 233, 234, 235, 236, 237, 238, 239, 240, 241, 242, 243, 244, 245, 246, 247, 248, 249, 250, 251, 253, 254, 255, 256, 257, 258, 259, 260, 261]
IPX_BOX = {"action": "/items/a1/answer", "token": "TOKEN", "sent": ""}
IPX_WATCH = {"action": "/items/a1/watch", "token": "TOKEN", "flag": "", "watched": True, "why": "it is yours"}
def ipx_pages():
    """Every fixture item page, plain and with the answer box and the watch control, in the language now current; {(id, variant): html}."""
    bd_ = r2.Board(f"{tmp}/store"); out = {}
    for i in IPX_IDS:
        for k_, kw in (("plain", {}), ("box", {"answer": IPX_BOX, "watch": IPX_WATCH}), ("mute", {"watch": {**IPX_WATCH, "flag": "mute"}}), ("off", {"watch": {**IPX_WATCH, "flag": "", "watched": False, "why": ""}}), ("on", {"watch": {**IPX_WATCH, "flag": "watch"}})):
            out[(i, k_)] = bd_.item_html(f"a{i}", **kw)
        out[(i, "contact")] = bd_.item_html(f"a{i}", contact="alpha-main")
    _iu = r2.issue_url
    r2.issue_url = lambda gid, store: "https://github.com/o/r/issues/5"          # the GitHub issue link of the sidebar
    try:
        for i in (201, 210, 235): out[(i, "gh")] = bd_.item_html(f"a{i}")
    finally: r2.issue_url = _iu
    bd_.item_log = lambda r, merge=True: ([], 0)          # an item whose store has no version of it yet: no History
    out[(201, "nolog")] = bd_.item_html("a201")
    bq_ = r2.Board(f"{tmp}/store"); bq_.queue_map = lambda: {"a201": "a202"}          # an item queued behind its mover's other item (`[model] queued_behind`; the queue is the board's own, given here)
    out[(201, "queued")] = bq_.item_html("a201")
    return out
# item-page fixture end
import html

# -- the same pages, in English (no language folder) and in the test locale (every string of the item page's areas wrapped in a marker)
set_dir(None); reset_warned()
ipx_en = ipx_pages()
write_ko(test_locale()); set_dir(LOC); reset_warned()
with i18n.use("ko"):
    ipx_ko = ipx_pages()
IPX_NEW = sorted(k for k in EN if re.match(r"^(item|wait|answer|watch|more|link)\.", k))
IPX_KO_ALL = "\n".join(ipx_ko.values()); IPX_KO_U = html.unescape(IPX_KO_ALL)
check("the item page has strings in the table (the areas item, wait, answer, watch, more and link)", len(IPX_NEW) > 150, len(IPX_NEW))
check("every fixture page rendered in both languages", len(ipx_en) == len(ipx_ko) == len(IPX_IDS) * 6 + 5 and all("<html" in h for h in ipx_en.values()), (len(ipx_en), len(ipx_ko)))
check("the item pages in English carry no marker and keep <html lang=\"en\"> (apply_lang rewrites it per person)", all("[x:" not in h and '<html lang="en">' in h for h in ipx_en.values()),
      [k for k, h in ipx_en.items() if "[x:" in h][:5])
check("a queued item's page says why it waits, in English and marked in the test locale", "its mover is working on that item first" in ipx_en[(201, "queued")] and MARK(EN["wait.queued_note"]) in ipx_ko[(201, "queued")] and 'href="/items/a202"' in ipx_en[(201, "queued")], re.findall(r"Waits on.{0,300}", ipx_en[(201, "queued")])[:1])
check("the item pages in the test locale carry markers", all("[x:" in h for h in ipx_ko.values()), [k for k, h in ipx_ko.items() if "[x:" not in h][:5])

def _ipx_pat(v):
    """A catalog text as a regex over the marked page: its fixed pieces in order, a field standing for anything (a marker nested inside it included)."""
    return re.compile(r"\[x:" + ".{0,600}?".join(re.escape(x) for x in re.split(r"\{[^}]*\}", v)) + r"\]", re.S)
# keys no item-page render reaches (the home page or a direct call uses them): the direct calls below mark them
IPX_DIRECT = {
              "link.mockup", "more.age_hour", "more.age_min", "wait.what.an_item", "wait.what.anchor_event", "wait.what.close_of", "wait.what.queued", "wait.what.news_from", "wait.what.outside_news",
              "item.cloud", "item.due_overdue", "item.due_today", "item.when.poll", "item.when.quiet", "item.when.unreadable", "item.when.unreadable_tip", "item.work",
              "link.mockup_chip", "link.mockup_tip", "link.session_in", "link.session_view", "wait.more", "wait.what.list", "wait.list.arrived", "wait.list.row_head"}
check("every name in the direct-call list is a key of the table's item-page areas (a stale name cannot hide in it)", IPX_DIRECT <= set(IPX_NEW), sorted(IPX_DIRECT - set(IPX_NEW)))
seen = {k for k in IPX_NEW if _ipx_pat(EN[k]).search(IPX_KO_ALL) or _ipx_pat(EN[k]).search(IPX_KO_U)}
check("every string of the item page's areas shows in the test locale on some fixture page, but the ones the direct calls below cover", set(IPX_NEW) - seen <= IPX_DIRECT, sorted(set(IPX_NEW) - seen - IPX_DIRECT))

# no English leftover of a routed string: strip the markers (nested ones with them), then no piece of a routed text stands in the visible words, unless the fixture's own item text says it
def _ipx_vis(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", h, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", h))
def _ipx_strip(v):
    out = []; depth = 0; i = 0
    while i < len(v):
        if depth == 0 and v.startswith("[x:", i): depth = 1; i += 3; out.append(" "); continue
        if depth:
            if v[i] == "[": depth += 1
            elif v[i] == "]": depth -= 1
            i += 1; continue
        out.append(v[i]); i += 1
    return "".join(out)
IPX_ITEM_TEXT = "\n".join(p.read_text(encoding="utf-8") for p in sorted((T / "store/a").glob("*.json"))).replace("\\n", "\n")
IPX_ITEM_TEXT += "\nthe news"          # the word of a relay line's kind label: watchers.subject_of's own fallback, not routed
IPX_ITEM_TEXT += "\n" + ASKX + "\n" + "\n".join(json.dumps(o) for o in OPX)
leaks = {}
for name, h in ipx_ko.items():
    v = _ipx_strip(_ipx_vis(re.sub(r'<span class="cl-t">.*?</span>', " ", h, flags=re.S)))          # a checklist row's text is the item's (a decided step is stored as "<owner>: picked A · Buy")
    for k in IPX_NEW:
        for chunk in re.split(r"\{[^}]*\}", EN[k]):
            c = chunk.strip(" .,:;()·—-")
            if len(c) >= 4 and c not in IPX_ITEM_TEXT and re.search(r"(?<![\w])" + re.escape(c) + r"(?![\w])", v): leaks.setdefault(k, set()).add((name, c))
check("in the test locale no routed text stays English on the item pages (after the markers are taken out, the words of the table are gone)", not leaks, {k: sorted(s)[:2] for k, s in sorted(leaks.items())[:6]})
check("…the item's own text stays English there (the subject, the description, the steps, the ask, the options)", all(s in ipx_ko[(201, "plain")] for s in ("Shelf audit, renamed", "oil the hinges", "a third fact")) and "[x:Shelf audit" not in IPX_KO_ALL
      and "[x:oil the hinges" not in IPX_KO_ALL and all(s in ipx_ko[(202, "box")] for s in ("whether to buy it", "Buy it now")) and "[x:Buy it now" not in IPX_KO_ALL)
check("the History's completed line says its outcome from the table (done, dropped, superseded, and the unrecorded one); the English page keeps the plain word", all(MARK(EN["item.outcome_word." + w]) in ipx_ko[(204, "plain")] for w in ("done", "dropped", "superseded"))
      and MARK(EN["item.outcome_word.unrecorded"]) in ipx_ko[(258, "plain")] and "<b>closed (no outcome recorded)</b>" in ipx_en[(258, "plain")] and "<b>dropped</b>" in ipx_en[(204, "plain")])
check("…and the English pages say what they always said (the words the table holds, in the place of the markers)", all(s in ipx_en[(201, "plain")] for s in ("History", "<b>done</b> by alpha-main")) and "Waiting" in ipx_en[(210, "plain")])

# markup in a person's or session's own words, put by the History into a template (the rank that was cleared, who closed it, a GitHub comment's text) reaches the page escaped, in both languages
def _m(key, **f): return MARK(EN[key].format(**f))
def _nojs(h): return re.sub(r"<(script|style)[^>]*>.*?</\1>", "", h, flags=re.S)
ESCP = ("&lt;u&gt;3&lt;/u&gt;", "&lt;s&gt;closer&lt;/s&gt;", "&lt;i&gt;hi&lt;/i&gt; &amp; &quot;q&quot;")
for lang_, pg_ in (("English", ipx_en), ("the test locale", ipx_ko)):
    b_ = _nojs(pg_[(259, "plain")])
    check(f"markup in a cleared rank, in the name of whoever closed an item and in a GitHub comment's text reaches the History escaped ({lang_})",
          all(x in b_ for x in ESCP) and not any(x in b_ for x in ("<u>3</u>", "<s>closer</s>", "<i>hi</i>")), [x for x in ESCP if x not in b_])
check("…the rank's line reads from its own template in both languages (the escaped rank in 'was …')", "rank cleared (was &lt;u&gt;3&lt;/u&gt;)" in ipx_en[(259, "plain")]
      and _m("item.log.rank_cleared", old="&lt;u&gt;3&lt;/u&gt;") in ipx_ko[(259, "plain")])
check("a cleared next reads 'next cleared' in English and from its two templates (the field name inside the line) in the test locale",
      "next cleared" in html.unescape(ipx_en[(259, "plain")]) and _m("item.log.field_cleared", field=_m("item.log.field.next")) in ipx_ko[(259, "plain")])

# the due line's three kinds say what happened: set, moved and cleared each carry the right date, in English and in the test locale
_en201, _ko201 = html.unescape(ipx_en[(201, "plain")]), ipx_ko[(201, "plain")]
check("the History's due lines in English: set to the first date, moved from the first to the second, cleared with the second as the old one", all(x in _en201 for x in ("due set to <b>Sun Mar 1st</b>", "due moved: Sun Mar 1st → <b>Wed Apr 1st</b>", "due cleared (was Wed Apr 1st)")))
_ds, _dm, _dc = (re.search(p_, _ko201) for p_ in (r"\[x:due set to <b>(?P<w>[^<]*)</b>\]", r"\[x:due moved: (?P<a>.*?) → <b>(?P<b>[^<]*)</b>\]", r"\[x:due cleared \(was (?P<w>[^)]*)\)\]"))
check("…and in the test locale each kind reads from its own key with the same dates (set's new = moved's old, moved's new = cleared's old)", bool(_ds and _dm and _dc) and _ds["w"] == _dm["a"] and _dm["b"] == _dc["w"] and _ds["w"] != _dm["b"], (_ds, _dm, _dc))

# the English-only values of the item page's areas, in both languages: the English page says the table's words, the test locale's page marks them
_en_all = html.unescape(_nojs("\n".join(ipx_en.values())))
def _en_pat(v): return re.compile(".{0,600}?".join(re.escape(x) for x in re.split(r"\{[^}]*\}", v)), re.S)
LOW_B = sorted(k for k in IPX_NEW if (k.startswith(("link.google_", "item.log.", "wait.what.")) or k in ("item.earlier_steps", "item.no_open_steps", "item.github_issue", "item.github_issue_tip", "wait.chase_note", "watch.not_watched")) and k not in IPX_DIRECT)
check("the English-only values (the Google links, the earlier and open steps, the GitHub issue, the History's lines, the wait's words and chase note, the watch's) are listed", len(LOW_B) >= 40, len(LOW_B))
check("…each reads as the table's words on some English fixture page", all(_en_pat(EN[k]).search(_en_all) for k in LOW_B), [k for k in LOW_B if not _en_pat(EN[k]).search(_en_all)])
check("…and each is marked on some page in the test locale", all(k in seen for k in LOW_B), [k for k in LOW_B if k not in seen])

# the GitHub link's title: a plain apostrophe in English (and in the test locale), a value's double quote still escaped (see QKEYS below)
check("the GitHub issue link's title shows a plain apostrophe, not &#x27;, in English and in the test locale", 'title="open this item\'s GitHub issue"' in ipx_en[(201, "gh")] and "item&#x27;s GitHub" not in ipx_en[(201, "gh")]
      and f'title="{MARK(EN["item.github_issue_tip"])}"' in ipx_ko[(201, "gh")], re.findall(r'title="[^"]*GitHub[^"]*"', ipx_en[(201, "gh")]))

# the strings only a direct call reaches
from stackshot.web import itempage as ipg
from stackshot.model import model as _mm
cl_ = _cfg.CFG.setdefault("client", {}); had_hosts = "mockup_hosts" in cl_; cfg_old = cl_.get("mockup_hosts")
with i18n.use("ko"):
    W = lambda kind, **k: _mm.Wait(kind=kind, kind_explicit=True, **k)
    d_wait = [ipg.wait_what(W("item", after=("a1", "a2"))), ipg.wait_what(W("item")), ipg.wait_what(W("item", after=("a1",), queued=True)), ipg.wait_what(W("anchor")), ipg.wait_what(W("anchor", event="the review lands")), ipg.wait_what(W("event")),
              ipg.wait_what(W("relay", event="the contract"), party="Acme"), ipg.wait_what(W("relay"), party="Acme"), ipg.wait_what(W("relay")), ipg.wait_what(W("relay", event="the contract from Acme"), party="Acme"),
              ipg.wait_what(W("time")), ipg.wait_what(W("time"), words="the shop's holiday"), ipg.wait_what(W("list"), mode="all of 3")]
    d_end = [ipg.wait_end_label(W("time")), ipg.wait_end_label(W("relay")), ipg.wait_end_label(W("anchor")), ipg.wait_end_label(W("item", until="2099-01-01"))]
    d_age = [r2.age_words(600), r2.age_words(3 * 3600), r2.age_words(3 * 86400)]
    d_tip = [r2.stale_tip({"_age": 3 * 3600, "metadata": {"needs": ["decision"]}}), r2.stale_tip({"_age": 3 * 3600, "metadata": {}})]
    try:
        cl_["mockup_hosts"] = ["mockup.example"]
        d_link = [r2.link_label("https://mockup.example/mockup/7"), r2.link_label("https://github.com/o/r/releases"), r2.link_label(SESSLINK)]
    finally:
        if had_hosts: cl_["mockup_hosts"] = cfg_old
        else: cl_.pop("mockup_hosts", None)
check("wait_what in the test locale: every kind, with and without its parts", d_wait == [_m("wait.what.close_of", items="a1, a2"), _m("wait.what.close_of", items=_m("wait.what.an_item")), _m("wait.what.queued", items="a1"), _m("wait.what.anchor_event"), "the review lands", _m("wait.what.fleet_event"),
      _m("wait.what.event_from", event="the contract", party="Acme"), _m("wait.what.news_from", party="Acme"), _m("wait.what.outside_news"), "the contract from Acme", _m("wait.a_date"), "the shop's holiday", _m("wait.what.list", mode="all of 3")], d_wait)
check("wait_end_label in the test locale", d_end == [_m("wait.end.until"), _m("wait.end.ask_by"), _m("wait.end.backstop"), _m("wait.end.until")], d_end)
check("age_words and stale_tip in the test locale", d_age == [_m("more.age_min", n=10), _m("more.age_hour", n=3), _m("more.age_day", n=3)]
      and d_tip == [_m("more.stale_tip_call", age=_m("more.age_hour", n=3)), _m("more.stale_tip", age=_m("more.age_hour", n=3))], (d_age, d_tip))
check("link_label in the test locale: a mockup page, a releases page and a session link read from the table", d_link == [_m("link.mockup"), _m("link.releases", repo="r"), _m("link.session")], d_link)
check("…and the config the test touched is put back", cl_.get("mockup_hosts") == cfg_old and ("mockup_hosts" in cl_) == had_hosts)

# the shared helpers of the sidebar and the rows, called direct: no fixture page reaches every branch of them
bdx = r2.Board(f"{tmp}/store"); DT = datetime.timedelta
fl_ = _cfg.CFG.setdefault("fleet", {}); had_tool = "tool_name" in fl_; tool_old = fl_.get("tool_name"); since_old = bdx.anchor_since
def _wd(d): return f"{d:%m-%d} {i18n.t(f'date.wd.{d.weekday()}', 'ko')}"
def _dueof(days): return {"gid": "a1", "metadata": {"due": (bdx.now.date() + DT(days=days)).isoformat()}}
with i18n.use("ko"):
    d_due = [bdx.due_badge(_dueof(0)), bdx.due_badge(_dueof(-3)), bdx.due_badge(_dueof(5)), bdx.due_badge({"gid": "a1", "metadata": {}})]
    bdx._sess_obj = lambda r: {"name": "cloud-x", "machine": "c"}; d_mc = bdx.mover_row({"gid": "a1", "metadata": {}})
    bdx._sess_obj = lambda r: None; d_mn = bdx.mover_row({"gid": "a1", "metadata": {}})
    del bdx._sess_obj
    d_work = bdx.work_html({"gid": "a1", "metadata": {"work": [{"text": "oil the hinges", "agent": "alpha-main", "state": "defined", "ts": 0}]}})
    bdx.anchor_since = None
    d_wn = [bdx._when({"unreadable": {"since": "2026-01-01 00:00", "why": "refused"}}), bdx._when({}), bdx._when({"mode": "poll"})]
    bdx.anchor_since = since_old
    d_stamp = bdx.stamp(bdx.now - DT(hours=3), quiet=True)
    bdx.sess_href = lambda n: "https://fleet.example/v/" + n
    try:
        fl_["tool_name"] = "Fleety"; d_s1 = bdx.sess_html("alpha-main")
        fl_["tool_name"] = ""; d_s2 = bdx.sess_html("alpha-main")
        cl_["mockup_hosts"] = ["mockup.example"]
        d_mk = r2.mockup_link({"gid": "a1", "status": "open", "metadata": {"needs": ["decision"], "ask": "pick one, see https://mockup.example/mockup/7"}})
    finally:
        del bdx.sess_href
        if had_tool: fl_["tool_name"] = tool_old
        else: fl_.pop("tool_name", None)
        if had_hosts: cl_["mockup_hosts"] = cfg_old
        else: cl_.pop("mockup_hosts", None)
    bdx.scoped_urls = lambda gid: [f"https://example.com/{i}" for i in range(5)]
    d_wa = [bdx.wait_anchor_html({"gid": "a1", "metadata": {}}, W("anchor")), bdx.wait_anchor_html({"gid": "a1", "metadata": {}}, W("anchor"), full=True)]
    bdx.scoped_urls = lambda gid: []; d_wa.append(bdx.wait_anchor_html({"gid": "a1", "metadata": {}}, W("anchor")))
    del bdx.scoped_urls
    d_sent = {k_: bdx.sent_msg(k_) for k_ in bdx._SENT}; d_home = json.loads(html.unescape(re.search(r'data-notes="([^"]*)"', bdx.sent_notes_html()).group(1)))
    d_sent_by = (bdx.sent_msg("done", "alpha-main"), bdx.sent_msg("stepreply", "alpha-main"), bdx.sent_msg("nope"), bdx.sent_msg("donenote", "alpha-main"))
_d0, _d3, _d5 = bdx.now.date(), bdx.now.date() - DT(days=3), bdx.now.date() + DT(days=5)
check("due_badge in the test locale: today, overdue and ahead each read from their own template, the weekday from the table; no date, no badge",
      d_due == [r2.badge(_m("item.due_today", n=0, md=_wd(_d0)), "due"), r2.badge(_m("item.due_overdue", n=3, md=_wd(_d3)), "due"), r2.badge(_m("item.due_in", n=5, md=_wd(_d5)), "due"), ""], d_due)
check("mover_row in the test locale: a cloud session names 'cloud' and an item under no session says 'no agent', each from the table",
      f'<span class="dim">· {MARK(EN["item.cloud"])}</span>' in d_mc[1] and "cloud-x" in d_mc[1] and MARK(EN["item.no_agent"]) in d_mn[1] and "cloud-x" not in d_mn[1], (d_mc, d_mn))
check("work_html in the test locale: the legacy Work field's name from the table, the line's own text as written", f'<dt>{MARK(EN["item.work"])} <span class="count">1</span></dt>' in d_work and "oil the hinges" in d_work, d_work)
check("_when in the test locale: an unreadable anchor (its tip with the reason), a quiet one and a polled one read from the table",
      d_wn[0] == f'<span class="aflag" title="{html.escape(_m("item.when.unreadable_tip", since="2026-01-01 00:00", tz=_cfg.tz_abbr(), why="refused"), quote=True)}">{_m("item.when.unreadable")}</span>'
      and d_wn[1] == _m("item.when.quiet") and d_wn[2] == _m("item.when.quiet") + _m("item.when.poll"), d_wn)
_t3 = bdx.now - DT(hours=3)
check("stamp in the test locale: a stamp that only marks the start of a silence says 'no change since <time>' in its tip", f'data-tip="{html.escape(_m("item.when.no_change_since", when=f"{_t3:%Y-%m-%d %H:%M} {_cfg.tz_abbr(_t3)}"), quote=True)}"' in d_stamp, d_stamp)
check("sess_html in the test locale: the link's title names the fleet tool when one is set, else says 'this session's view'",
      f'title="{MARK("open this session in Fleety")}"' in d_s1 and f'title="{r2.esc_dq(_m("link.session_view"))}"' in d_s2 and "&#x27;" not in d_s2, (d_s1, d_s2))      # the apostrophe is written as one, the form esc_dq gives a plain-English attribute
check("…and the fleet and client config the test touched is put back", fl_.get("tool_name") == tool_old and ("tool_name" in fl_) == had_tool and cl_.get("mockup_hosts") == cfg_old)
check("mockup_link in the test locale: the chip and its tip read from the table", f'title="{MARK(EN["link.mockup_tip"])}"' in d_mk and f'>{MARK(EN["link.mockup_chip"])}</a>' in d_mk, d_mk)
check("wait_anchor_html in the test locale: more than three anchors say '+N more' (not when all are listed), none recorded says so",
      _m("wait.more", n=2) in d_wa[0] and _m("wait.more", n=2) not in d_wa[1] and _m("wait.anchor_none") in d_wa[2] and _m("wait.anchor_none") not in d_wa[0], d_wa)
_S = r2.Board._SENT; _K = {k_: v_[1] for k_, v_ in r2.Board._SENT_KEYS.items()}; _KH = {k_: v_[2] for k_, v_ in r2.Board._SENT_KEYS.items() if len(v_) > 2}
e_sent = {k_: bdx.sent_msg(k_) for k_ in _S}; e_by = (bdx.sent_msg("done", "alpha-main"), bdx.sent_msg("stepreply", "alpha-main"), bdx.sent_msg("nope"), bdx.sent_msg("donenote", "alpha-main"))
check("sent_msg in English is _SENT's item-page wording, code by code; who takes it names them; a code that is none is empty",
      e_sent == {k_: v_[1] for k_, v_ in _S.items()} and e_by == ("Done: alpha-main takes it from here.", "Sent: alpha-main has your note and decides whether the step is done.", "", "Done: alpha-main takes it from here, and your note went along."), (e_sent, e_by))
check("sent_msg in the test locale: every code reads from its own key, who takes it is named in the table's wording, and every code has a key",
      set(_K) == set(_S) and d_sent == {k_: MARK(EN[_K[k_]]) for k_ in _S}
      and d_sent_by == (_m("js.sent_done", who="alpha-main"), _m("sent.stepreply_by", who="alpha-main"), "", _m("js.sent_done_note", who="alpha-main")), (d_sent, d_sent_by))
check("the home page's notices (sent_notes_html) in the test locale: every code with the home page's own key reads from it, the rest from the item page's, each with its class",
      d_home == {k_: [r2.Board._SENT_KEYS[k_][0], MARK(EN[_KH.get(k_, _K[k_])])] for k_ in _S}, d_home)
# the English wording of eight keys no other test pins, through the real render path with representative fields (the test locale's checks above prove only that each key is read, not what it says)
_wd_en = lambda d: f"{d:%m-%d} {d:%a}"
bdx._sess_obj = lambda r: {"name": "cloud-x", "machine": "c"}; en_mc = bdx.mover_row({"gid": "a1", "metadata": {}}); del bdx._sess_obj
bdx.anchor_since = None; en_poll = bdx._when({"mode": "poll"}); bdx.anchor_since = since_old
bdx.scoped_urls = lambda gid: [f"https://example.com/{i}" for i in range(5)]
en_more = bdx.wait_anchor_html({"gid": "a1", "metadata": {}}, W("anchor")); en_more_full = bdx.wait_anchor_html({"gid": "a1", "metadata": {}}, W("anchor"), full=True)
bdx.scoped_urls = lambda gid: []; en_none = bdx.wait_anchor_html({"gid": "a1", "metadata": {}}, W("anchor")); del bdx.scoped_urls
en_work = bdx.work_html({"gid": "a1", "metadata": {"work": [{"text": "oil the hinges", "agent": "alpha-main", "state": "defined", "ts": 0}]}})
check("English wording, pinned: due today and due in N days (the date with its weekday)", bdx.due_badge(_dueof(0)) == r2.badge(f"Due today ({_wd_en(_d0)})", "due") and bdx.due_badge(_dueof(5)) == r2.badge(f"Due in 5 d ({_wd_en(_d5)})", "due"), (bdx.due_badge(_dueof(0)), bdx.due_badge(_dueof(5))))
check("English wording, pinned: a cloud session's row says 'cloud', the legacy Work field is named 'Work', a polled anchor says ' · poll'",
      '<span class="dim">· cloud</span>' in en_mc[1] and '<dt>Work <span class="count">1</span></dt>' in en_work and en_poll == "quiet · poll", (en_mc, en_work, en_poll))
_a = lambda i, label: f'<a href="https://example.com/{i}" target="_blank" rel="noopener">{label}</a>'
check("English wording, pinned: five anchors say '+2 more' after the first three (the whole fragment), all five listed say no more, none recorded says exactly 'an anchor (none recorded)'",
      en_more == ", ".join(_a(i, f"example.com ({i + 1})") for i in range(3)) + ' <span class="dim">+2 more</span>'
      and en_more_full == ", ".join(_a(i, f"https://example.com/{i}") for i in range(5)) and en_none == "an anchor (none recorded)", (en_more, en_more_full, en_none))
check("English wording, pinned: the answer script's 'Nothing sent: {why}' (the table every page head carries, and the script asking for it)",
      '"js.answer.nothing_sent": "Nothing sent: {why}"' in r2._SST_HEAD and "SST('js.answer.nothing_sent'" in r2._ANSWER_JS)
d_en = {"wait": ipg.wait_what(W("item", after=("a1",))), "age": r2.age_words(600), "tip": r2.stale_tip({"_age": 3 * 3600, "metadata": {"needs": ["decision"]}})}
check("the same calls in English give the words they always gave", d_en == {"wait": "the close of a1", "age": "10 min", "tip": "ask last confirmed 3 h ago — may be out of date"} and EN["more.age_min"] == "{n} min", d_en)
# the temporary probe page /probe/sala-link: its words in English, pinned, and the page drawn from them (no session_view is set in this fixture, so it says so and draws no link)
en_probe = bdx.probe_html()
check("English wording, pinned: the probe page's heading, instruction and no-address line, and the labels of the variants A to F",
      EN["probe.title"] == "Opening a session link" and EN["probe.note"] == "Open this page in the stackshot app on Android and tap each link in turn; tell the agent which opened the sala app."
      and [EN[f"probe.{x}.label"] for x in "abcdef"] == ["A. Plain link, new tab", "B. Plain link, same tab", "C. Android intent link, new tab", "D. Android intent link, same tab", "E. Android intent link with view action", "F. Script buttons"]
      and "<h1>Opening a session link</h1>" in en_probe and "No session view address is set under [client] session_view, so there is nothing to test." in en_probe, en_probe[-600:])

# the "rendered ... ago" line is one template: English keeps its words and its order, a language can put the age anywhere, and the words around it are what the narrow page leaves off
_rl = lambda: r2._rendered_line("<b>S</b>", tip="T"); _st = r2._stale_s()
rl_en = _rl()
write_ko(test_locale(**{"home.rendered_line": "{age} was drawn"})); set_dir(LOC); reset_warned()
with i18n.use("ko"): rl_ko = _rl()
write_ko(test_locale(**{"home.rendered_line": "{age}"})); set_dir(LOC); reset_warned()
with i18n.use("ko"): rl_bare = _rl()
write_ko(test_locale(**{"home.rendered_line": "{age} was drawn, {age}"})); set_dir(LOC); reset_warned()
with i18n.use("ko"): rl_twice = _rl()
write_ko(test_locale(**{"home.rendered_line": "drawn lately"})); set_dir(LOC); reset_warned()
with i18n.use("ko"): rl_none = _rl()
write_ko(test_locale()); set_dir(LOC); reset_warned()
check("the rendered line in English: 'rendered' before the age, byte for byte what it always was",
      rl_en == f'<p class="rline"><span class="rw">rendered </span><span id="rendered" data-stale="{_st}" title="T"><b>S</b></span></p>', rl_en)
check("…a template that puts the age first puts it first, the age's span intact and its words after it", rl_ko == f'<p class="rline"><span id="rendered" data-stale="{_st}" title="T"><b>S</b></span><span class="rw"> was drawn</span></p>', rl_ko)
check("…a template of the age alone draws no words around it", rl_bare == f'<p class="rline"><span id="rendered" data-stale="{_st}" title="T"><b>S</b></span></p>', rl_bare)
_span = f'<span id="rendered" data-stale="{_st}" title="T"><b>S</b></span>'
check("…REGRESSION: a template with the age twice draws the age's span once, at the first place; the second place is empty and no marker leaks into its words (the old code let the marker into the second span)",
      rl_twice == f'<p class="rline">{_span}<span class="rw"> was drawn, </span></p>' and rl_twice.count('id="rendered"') == 1, rl_twice)
check("…characterization (the old code gave the same): a template with no age at all draws the age's span once, words first and the span after (it carries the stale colour, the title and the tick)",
      rl_none == f'<p class="rline"><span class="rw">drawn lately</span>{_span}</p>', rl_none)
check("…and the age is never a word of any translation (the template's own marker stays out of the page)", "\x00" not in rl_en + rl_ko + rl_bare + rl_twice + rl_none)

# every key the stage added to the table is asked for somewhere (a literal key in the source, or a dict of keys the source reads): none is dead
_all_keys = list(EN); _block = _all_keys[_all_keys.index("item.unknown") + 1:]
_src_all = "\n".join(pathlib.Path(STACK, rel).read_text(encoding="utf-8") for rel in ("stackshot/web/ui/render.py", "stackshot/web/ui/kit.py", "stackshot/web/home.py", "stackshot/web/itempage.py"))
_unused = [k for k in _block if k not in used and not re.search(r"""['"]""" + re.escape(k) + r"""['"]""", _src_all)]
_STAGE_PREFIXES = ("item.log.", "item.when.", "js.answer.", "home.rendered_line", "home.command", "link.mockup_", "link.session_", "item.due_", "item.no_agent", "item.cloud", "item.work", "wait.")      # the groups that stage added: each one must still be found after item.unknown, so the scan cannot go quiet by finding no block
_missing_prefix = [pf for pf in _STAGE_PREFIXES if not any(k.startswith(pf) for k in _block)]
check("every key the string table gained after item.unknown is asked for by the source", not _missing_prefix and not _unused, (_missing_prefix, _unused))

# a translated value goes into an attribute escaped: a value with a double quote (and a tag in it) must not break the attribute or open an element
from html.parser import HTMLParser
class _Attrs(HTMLParser):
    def __init__(self): super().__init__(); self.found = []; self.ids = []
    def handle_starttag(self, tag, attrs):
        for k_, v_ in attrs:
            if k_ == "id" and v_ == "inj": self.ids.append(tag)
        self.found.append((tag, dict(attrs)))
QKEYS = {"item.earlier_steps": "ul", "item.next_steps": "ul", "item.github_issue_tip": "a", "item.details": "aside"}
QATTR = {"item.earlier_steps": "aria-label", "item.next_steps": "aria-label", "item.github_issue_tip": "title", "item.details": "aria-label"}
QV = {k_: MARK(EN[k_]) + chr(0xD55C) + '" x="y"><i id="inj">' for k_ in QKEYS}          # built at run time: a Hangul letter, a double quote, a tag
write_ko(test_locale(**QV)); set_dir(LOC); reset_warned()
with i18n.use("ko"):
    bq_ = r2.Board(f"{tmp}/store"); _iu = r2.issue_url
    r2.issue_url = lambda gid, store: "https://github.com/o/r/issues/5"
    try: q_pages = {i: bq_.item_html(f"a{i}") for i in (201, 235)}
    finally: r2.issue_url = _iu
for k_, tag_ in QKEYS.items():
    pg_ = _Attrs(); [pg_.feed(h_) for h_ in q_pages.values()]
    hits_ = [a for t_, a in pg_.found if t_ == tag_ and a.get(QATTR[k_]) == QV[k_]]
    check(f"a value with a double quote in {k_} stays inside its {QATTR[k_]}= attribute on the item page (escaped, whole)", len(hits_) >= 1, [a.get(QATTR[k_]) for t_, a in pg_.found if t_ == tag_ and QATTR[k_] in a][:3])
pg_ = _Attrs(); [pg_.feed(h_) for h_ in q_pages.values()]
check("…and no element the value tried to open is on the page, nor its raw text in any attribute position", not pg_.ids and all('"><i id="inj">' not in h_ for h_ in q_pages.values()), pg_.ids)
write_ko(test_locale()); reset_warned()

# ---- the step form's four strings: in the English catalog, and read through the string table (a locale file that overrides them changes the page; the values here are plain ASCII stand-ins, the real Korean lives in the private locale file)
STEP_KEYS = ("home.step_note", "home.step_note_aria", "home.step_done", "home.step_send_note", "home.step_send_note_hint")
STEP_OVR = {"home.step_note": "Xnote", "home.step_note_aria": "Xnote-label", "home.step_done": "Xdone", "home.step_send_note": "Xsend-note", "home.step_send_note_hint": "Xhint"}
check("the step form's five strings are in the English catalog: the optional note box (placeholder and label), the two buttons and the hint on a greyed Send note", all(k_ in EN for k_ in STEP_KEYS) and [EN[k_] for k_ in STEP_KEYS] == ["Note (optional)", "Note for the next mover (optional)", "Done", "Send note", "Write a note to send it"], [EN.get(k_) for k_ in STEP_KEYS])
write_ko(test_locale(**STEP_OVR)); set_dir(LOC); reset_warned()
with i18n.use("ko"):
    ko_step_pg = r2.Board(f"{tmp}/store").item_html("a240", answer=IPX_BOX)
check("a locale file's values for them reach the item page of a step item: the note box (placeholder and label), Done (the main button) and Send note, and none of the English labels",
      'placeholder="Xnote"' in ko_step_pg and ">Xnote-label</label>" in ko_step_pg and 'name="act" value="done">Xdone</button>' in ko_step_pg and 'title="Xhint" data-hint="Xhint" data-needs-text>Xsend-note</button>' in ko_step_pg
      and ">Done</button>" not in ko_step_pg and "Send note" not in ko_step_pg and "Note (optional)" not in ko_step_pg and "Write a note to send it" not in ko_step_pg, ko_step_pg[ko_step_pg.find('class="iask istep"'):][:900])
write_ko(test_locale()); reset_warned()

set_dir(None)
n_bad = len(fails)
print(f"{len(ran) - n_bad}/{len(ran)} checks passed")
sys.exit(1 if n_bad else 0)
