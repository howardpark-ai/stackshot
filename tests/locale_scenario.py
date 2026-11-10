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
from stackshot.web import i18n, i18n_catalog, search, shared
from stackshot.web import uiprefs as up
from stackshot.web import server
from stackshot.web.ui import render as r2
from starlette.testclient import TestClient
server._publish = lambda: None
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
KEY_USE = re.compile(r"""(?:\b_t|\b_i18n\.t|\bi18n\.t|\bSST)\(\s*['"]([a-z0-9_.-]+)['"]""")
used = set()
for rel in ("stackshot/web/ui/render.py", "stackshot/web/ui/kit.py", "stackshot/web/home.py", "stackshot/web/i18n.py", "stackshot/web/uiprefs.py"):
    used |= set(KEY_USE.findall(pathlib.Path(STACK, rel).read_text(encoding="utf-8")))
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
COOKIE = {e: server._ui_sign(json.dumps({"email": e, "exp": time.time() + 3600})) for e in (MINA, NOOR)}
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
        if who: c.cookies.set(server._UI_COOKIE, COOKIE[who])
        return c.get(path, follow_redirects=False)
    def post(body, who=MINA, headers=JSON_H, raw=None, path="/prefs/lang"):
        c.cookies.clear()
        if who: c.cookies.set(server._UI_COOKIE, COOKIE[who])
        return c.post(path, content=raw if raw is not None else json.dumps(body), headers=headers, follow_redirects=False)

    # -- no folder configured: the pages are English, with no marker and no switch
    set_dir(None); reset_warned(); shared._board_home_drop()
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
    write_ko(test_locale()); set_dir(LOC); reset_warned(); shared._board_home_drop()
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
    check("the rendered line and the ages are in the test locale (the age template, the 'rendered' word)", re.search(r"A<(now|\d+min|\d+hr|\d+day)>", kv) is not None and MARK("rendered") in kv and " ago<" not in kv, re.findall(r"A<[^>]*>|\d+[mhd] ago|just now", kv)[:6])
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
    shared._board_home_drop(); get("/", NOOR); get("/", MINA)
    kept_en, kept_ko = server._BOARD_HOME["html"], shared._BOARD_HOME_OTHER.get("ko", {}).get("html")
    check("the home keeps one draw per language: English in the English slot, the test locale in its own", kept_en and "[x:" not in kept_en and kept_ko and MARK("Your move") in kept_ko and kept_ko != kept_en)
    check("…the kept English draw is what the English person is served", "[x:" not in kept_en and re.search(r"Your move", kept_en) is not None and get("/", NOOR).text == kept_en, None)
    shared._board_home_drop()
    check("a drop clears every language's draw", server._BOARD_HOME["at"] == 0.0 and all(s["at"] == 0.0 for s in shared._BOARD_HOME_OTHER.values()))
    st_en = get("/render-stamp", NOOR); st_ko = get("/render-stamp", MINA)
    check("the render stamp answers for the person's own draw (JSON, a ts)", st_en.status_code in (200, 503) and st_ko.status_code in (200, 503) and (st_ko.status_code == 503 or isinstance(st_ko.json().get("ts"), int)), (st_en.status_code, st_ko.text))
    r = post({"lang": "en"})
    back = get("/", MINA).text
    check("a round trip: back to English, <html lang=\"en\">, no marker, the switch still drawn", '<html lang="en">' in back and "[x:" not in back and 'id="panel-lang"' in back and 'id="ssi"' not in back)
    get("/", NOOR); held_at = server._BOARD_HOME["at"]; held_html = server._BOARD_HOME["html"]
    post({"lang": "ko"}); post({"lang": "en"})
    check("a save of the language leaves the kept draws alone (a toggle is not a write to the board)", held_at > 0 and server._BOARD_HOME["at"] == held_at and server._BOARD_HOME["html"] is held_html)
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
check("…in particular the lists' state and lane words, and no marker of the test language anywhere in the module", ok_runs and runs["ko"].get("STATE_WORDS", {}).get("doing") == "On agent" and runs["ko"].get("LANE_WORDS", {}).get("call") == "Your move" and "[x:" not in json.dumps(runs["ko"]), ok_runs and runs["ko"].get("STATE_WORDS"))

set_dir(None)
n_bad = len(fails)
print(f"{len(ran) - n_bad}/{len(ran)} checks passed")
sys.exit(1 if n_bad else 0)
