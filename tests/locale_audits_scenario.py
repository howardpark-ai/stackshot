"""Scenario test for the second language on the pages of stage 3b: the Audits page and the side panel's audit card, the routing page (a project's details), Projects, Closed (the Completed
section's pager and the landed page's script), For you, the sent notices, the said tags and the sessions list (stackshot/web/ui/render.py, with the audit module's English words in
stackshot/audit/audit_overview.py, and the keys in i18n_catalog.py). Fixture data, the pages through Starlette's test client and straight from the builders, no live store, no network.
People and addresses are made up. The repository holds no text in another language, so the second language here is an ASCII TEST locale written into a temporary folder: every value is
the English text wrapped as `[x:...]`, and the date and age forms are ASCII templates. It proves the routing; it says nothing about any real translation.

Covers:
  * the keys: every key these sources ask for by its literal name exists in English; every key the pages build (audit.desc.<group>, audit.pace.<word>, audit.mode.<word>, audit.source.<source>, the
    sent notices', the session flags') exists for each word the audit module and the render tables can give; every new key of this stage is used somewhere (a key nothing asks for is dead text);
  * the audit module's English words (its groups' names and descriptions, the paces, the modes, the card's notes, the sources) equal the catalog's English text, so a word cannot drift from its key;
  * English is unchanged: the pages read the English the catalog holds, with no marker, for a person who never picked a language;
  * the second language: each page's interface words carry the markers and none stays English (every word left outside a marker is a fixture word: a name, a title, an id, a note a session wrote),
    while item text (subjects, descriptions, asks, a quote a person said, a routing note's gist) stays as written; the closed page's script reads its words with SST, holds no English message
    and its relative words come from the age.* keys;
  * this file and the sources hold no Hangul letter.

    tests/run-suite locale_audits        → exit 0 / 1"""
import html as _html, json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="localeaud-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
MINA, NOOR = "mina@example.org", "noor@example.org"
toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{MINA}", "{NOOR}"]'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^panel = true', 'panel = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "state/audit", "secrets", "touch", "repo", "brain/projects", "locales"): (T / d).mkdir(parents=True)
A, X = "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({A: {"name": "alpha-main", "machine": "a", "url": "", "seen": "x"}, X: {"name": "alpha-x", "machine": "a", "url": "", "seen": "x"}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": "https://example.invalid/alpha", "agents": {"alpha-main": "builds", "alpha-ghost": "no session"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE lantern.\n\n<!-- timeline -->\n- 2026-02-19 | old\n")
now0 = time.time()
TITLE = "Quarterly lantern inventory"
SAID_QUOTE = "ship the lantern list as it is"
def item(i, status="open", subject=None, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[work] {TITLE} {i}", "description": "- A thing\n- It lives here\n- Finished when it works", "status": status,
        "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600, "metadata": {"owner": A, "project": "projects/alpha", "next": "the next step", **meta}}))
item(1)
for i in (2, 3, 4): item(i)      # closed by an agent below: the Closed page has three lines
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.core import config as _cfg
from stackshot.audit import audit_overview as ov
from stackshot.router import routing
from stackshot.web import foryou, i18n, landed as ld, server
from stackshot.web.ui import render as r2
from starlette.testclient import TestClient
server._publish = lambda: None
EN = i18n.EN
LOC = T / "locales"
MARK = lambda v: f"[x:{v}]"
DATE_AGE = {"date.full": "D<{wd}/{month}/{day}/{hm}>", "date.nohm": "D<{wd}/{month}/{day}>", "date.day": "{n}{ord}",
            "date.ord.1": "o1", "date.ord.2": "o2", "date.ord.3": "o3", "date.ord.n": "on",
            "age.now": "A<now>", "age.min": "A<{n}min>", "age.hour": "A<{n}hr>", "age.day": "A<{n}day>"}
DATE_AGE.update({f"date.wd.{i}": f"w{i}" for i in range(7)}); DATE_AGE.update({f"date.mon.{i}": f"m{i}" for i in range(1, 13)})
def test_locale(**over):
    d = {k: MARK(v) for k, v in EN.items()}; d.update(DATE_AGE); d.update(over); return d
def set_dir(v):
    if v is None: _cfg.CFG.get("ui", {}).pop("locale_dir", None)
    else: _cfg.CFG.setdefault("ui", {})["locale_dir"] = str(v)

# ---- 1. the repository's text: no Hangul in this file or the sources
HANGUL = re.compile("[%s-%s%s-%s%s-%s]" % tuple(chr(c) for c in (0xAC00, 0xD7A3, 0x3131, 0x318E, 0x1100, 0x11FF)))      # built from code points: this file holds no Hangul itself
SOURCES = ("stackshot/web/ui/render.py", "stackshot/audit/audit_overview.py", "stackshot/web/i18n_catalog.py")
SRC = {rel: pathlib.Path(STACK, rel).read_text(encoding="utf-8") for rel in SOURCES}
check("this file and the sources hold no Hangul letter", not HANGUL.search(pathlib.Path(__file__).read_text(encoding="utf-8")) and not [r for r, s in SRC.items() if HANGUL.search(s)])

# ---- 2. the keys
KEY_USE = re.compile(r"""(?:\b_t|\b_i18n\.t|\bi18n\.t|\bSST)\(\s*['"]([a-z0-9_.-]+)['"]""")
used = {k for k in KEY_USE.findall(SRC["stackshot/web/ui/render.py"]) if not k.endswith((".", "_"))}
check("render.py asks for keys by their literal names (a regex that matches nothing would prove nothing)", len(used) > 150, len(used))
check("every key it asks for by its literal name is in the English catalog", not [k for k in used if k not in EN], [k for k in used if k not in EN])
GROUP_KEYS = [g["key"] for g in ov.GROUPS]
PACES = sorted({a[1] for g in ov.GROUPS for a in g["audits"]})
DYN = {"audit.desc.": GROUP_KEYS, "audit.source.": list(ov.SOURCES), "audit.mode.": ["shadow", "off", "ask_only", "report_only"],
       "audit.pace.": [r2._AUDIT_PACES[w] for w in PACES if w in r2._AUDIT_PACES]}
missing = [p + k for p, ks in DYN.items() for k in ks if p + k not in EN]
check("every key the Audits page builds (a prefix and a word) exists for each word the audit module can give", not missing and all(len(ks) >= 2 for ks in DYN.values()), missing)
check("every pace the audit module lists has a key (a pace with none would stay English in every language)", all(w in r2._AUDIT_PACES for w in PACES) and len(PACES) >= 4, [w for w in PACES if w not in r2._AUDIT_PACES])
check("…and the modes the module's _mode gives (on, off, shadow, ask only, report only): the ones that are shown have a key",
      all(w in r2._AUDIT_MODES for w in ("shadow", "off", "ask only", "report only")), r2._AUDIT_MODES)
check("the sent notices' and the session flags' tables name keys the catalog has", all(x in EN for v in r2.Board._SENT_KEYS.values() for x in v[1:]) and all(x in EN for v in r2._AFLAG.values() for x in v), None)
check("every English value is a plain template (named fields only)", all(i18n.fields_of(v) is not None for v in EN.values()), [k for k, v in EN.items() if i18n.fields_of(v) is None])
NEW = ("page.", "sessions.", "foryou.", "sent.", "said.", "routing.", "closed.", "js.closed.", "projects.", "audit.")
quoted = set(re.findall(r'["\']((?:%s)[a-z0-9_.]+)["\']' % "|".join(re.escape(p) for p in NEW), SRC["stackshot/web/ui/render.py"]))
dyn_used = {p + k for p, ks in DYN.items() for k in ks} | {"audit.pace." + k for k in r2._AUDIT_PACES.values()} | {"audit.mode." + k for k in r2._AUDIT_MODES.values()}
new_keys = [k for k in EN if k.startswith(NEW)]
dead = [k for k in new_keys if k not in used and k not in quoted and k not in dyn_used]
check("every new key of this stage is used by a page (none is dead text)", len(new_keys) >= 150 and not dead, dead)
check("the docstring of the catalog lists the new areas", all(a in SRC["stackshot/web/i18n_catalog.py"].split('"""')[1] for a in ("sessions.*", "foryou.*", "sent.*", "said.*", "routing.*", "closed.*", "projects.*", "audit.*")))

# ---- 3. the audit module's English words are the catalog's English text
check("the groups' names are the panel's group names and their descriptions are audit.desc.<group>", [EN["panel.audit.group." + g["key"]] for g in ov.GROUPS] == [g["name"] for g in ov.GROUPS]
      and [EN["audit.desc." + g["key"]] for g in ov.GROUPS] == [g["desc"] for g in ov.GROUPS], [g["key"] for g in ov.GROUPS])
check("the card's two notes are the panel's note lines", EN["panel.audit.note.unlogged"] == ov.NOTE_UNLOGGED and EN["panel.audit.note.off"] == ov.NOTE_LOG_OFF, (ov.NOTE_UNLOGGED, ov.NOTE_LOG_OFF))
check("the sources are audit.source.<source>", all(EN["audit.source." + k] == v for k, v in ov.SOURCES.items()), ov.SOURCES)
check("the paces and the modes: the English words the module gives are the catalog's English text", set(PACES) <= set(r2._AUDIT_PACES) and EN["audit.mode.shadow"] == "shadow" and EN["audit.mode.off"] == "off"
      and EN["audit.mode.ask_only"] == "ask only" and EN["audit.mode.report_only"] == "report only", PACES)

# ---- 4. the fixture the pages are drawn from
now = time.time()
D = T / "state/audit"
rows_ = [{"at": now - 600, "source": "silence", "id": "a11", "kind": "stale", "agent": "the-agent", "project": "projects/alpha", "detail": "went quiet"},
         {"at": now - 1200, "source": "filing", "id": "a12", "kind": "stuck-elsewhere", "agent": "the-agent", "project": "projects/alpha", "detail": "waits on a thing that closed"},
         {"at": now - 1400, "source": "run", "id": "a14", "kind": "ask-missing", "agent": "the-agent", "project": "projects/alpha", "detail": "the ask is missing"}]
(D / "findings-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows_), encoding="utf-8")
(D / "run-2026-02-23.json").write_text(json.dumps({"started": now - 5000, "finished": now - 4300, "items_read": 41, "findings": [{"id": "a"}, {"id": "b"}], "calls": {"made": 6}}))
(D / "run-2026-02-22.json").write_text(json.dumps({"started": now - 90000, "items_read": 7, "findings": [], "calls": {"made": 1}}))      # never finished
_cfg.CFG["audit"]["at"] = "05:00"
GIST = "Kim wrote about the lantern release"
routing.record("projects/alpha", kind="anchor", to="alpha-main", label="Slack", who="hub", text=GIST, target="for alpha-main", ts=now - 300)
routing.record("projects/alpha", kind="message", to="", label="", who="alpha-x", text="a note with no one to take it", log_only=True, reason="log only: nothing to deliver", ts=now - 200)
NEWD = "- The thing works and is in use"
_cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, "live": True}
server._refuse_if_owing = lambda debtor: None
for i in (2, 3, 4):
    server.stackshot_complete(f"a{i}", outcome="done", reason="the change is live", description=NEWD, sender="alpha-x")
check("the fixture has closes on the Closed list", len(ld.records()) == 3, ld.records())
FY = "the nightly check turned red"
foryou.add(key="t1", kind="check_failed", gid="a1", what=FY, urgent=True, ts=now - 100)
foryou.add(key="t2", kind="closed", gid="a2", what="closed: a thing", ts=now - 50)
SAID_META = {"said": [{"tag": "Acked-by", "quote": SAID_QUOTE, "session": A, "ts": now - 30, "checked": True}, {"tag": "Acked-by", "quote": "an unproved line", "session": "", "ts": now - 20, "checked": False, "why": "no transcript"}]}

COOKIE = {e: server._ui_sign(json.dumps({"email": e, "exp": time.time() + 3600})) for e in (MINA, NOOR)}
def visible(h): return re.sub(r"<script\b.*?</script>|<style\b.*?</style>", "", h, flags=re.S)
def unmarked(h):
    """The page's visible text with the markup, the markers `[x:...]` (a marker may hold another: innermost first) and the ASCII date and age forms taken out: what is left is the words the page did not route."""
    t = _html.unescape(re.sub(r"<[^>]*>", " ", visible(h)))
    for _ in range(8): t = re.sub(r"\[x:[^\[\]]*\]", " | ", t)
    return re.sub(r"\s+", " ", re.sub(r"[AD]<[^>]*>", " | ", t))
def words_left(h, allowed):
    u = unmarked(h); scopes = set(re.findall(r"→ ([a-z]+)", u))      # a project scope's name (the panel's Projects list groups by it) is the instance's own word
    return sorted({w for w in re.findall(r"[A-Za-z][A-Za-z']{2,}", u) if w.lower() not in allowed and w not in scopes})
def ctx(h, words, n=45):
    t = unmarked(h); return {w: [t[max(0, m.start() - n):m.end() + n] for m in re.finditer(r"\b" + re.escape(w) + r"\b", t)][:2] for w in words}
def body(h): return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", visible(h))))
# words that stay English because they are data, not interface: names, titles, notes, ids the fixture holds
DATA = {"alpha", "main", "ghost", "box", "work", "home", "stackshot", "lantern", "quarterly", "inventory", "state", "kim", "wrote", "about", "the", "release", "slack", "hub",
        "went", "quiet", "waits", "thing", "that", "closed", "ask", "missing", "agent", "note", "with", "one", "take", "log", "only", "nothing", "deliver", "nightly", "check", "turned", "red",
        "builds", "stale", "current", "old", "for", "general", "change", "live", "now", "example", "completed", "done", "progress", "board", "front", "https", "items", "org", "session", "was", "by", "is", "its", "pane", "not", "this", "box", "held", "here"}
# the audit module's own audit names and the log's kinds are identifiers, never routed
for _g in ov.GROUPS:
    for _a in _g["audits"]: DATA |= set(re.findall(r"[a-z']{3,}", str(_a[0]).lower()))
for _r in rows_: DATA |= set(re.findall(r"[a-z']{3,}", " ".join(str(v) for v in _r.values()).lower()))

with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def get(path, who=MINA):
        c.cookies.clear()
        if who: c.cookies.set(server._UI_COOKIE, COOKIE[who])
        return c.get(path, follow_redirects=False)
    def post_lang(lang, who=MINA):
        c.cookies.clear(); c.cookies.set(server._UI_COOKIE, COOKIE[who])
        return c.post("/prefs/lang", content=json.dumps({"lang": lang}), headers={"Origin": BOARD, "Content-Type": "application/json"}, follow_redirects=False)
    PAGES = ("/audits", "/projects", "/projects/alpha", "/closed")
    # ---- 5. English, no catalog loaded: every word is the catalog's, no marker
    set_dir(None); i18n._WARNED.clear(); i18n._LOADED.clear()
    en = {p: get(p, NOOR) for p in PAGES}
    check("English: every page answers 200 and holds no marker", all(r.status_code == 200 for r in en.values()) and not [p for p, r in en.items() if "[x:" in r.text], {p: r.status_code for p, r in en.items()})
    ea = body(en["/audits"].text)
    check("English: the Audits page's words are the old words (title, groups, latest findings, runs, the paces and the table's heads)", "Audits" in ea and "Groups open one to see its audits" in ea and "Latest findings" in ea
          and "Every minute" in ea and "Every 10 minutes" in ea and "Started Took Items Findings Calls" in ea and ", and Audit now" in ea and "did not finish" in ea and "1 found" in ea and "Silence" in ea, ea[:900])
    eproj, erout, eclosed = body(en["/projects"].text), body(en["/projects/alpha"].text), body(en["/closed"].text)
    check("English: the routing page's words (Sessions, Anchors, Notices, the table heads, a log-only note)", all(w in erout for w in ("Notices", "Sessions", "Anchors", "when (", "ruling", "reason")) and GIST in erout and "[x:" not in erout, erout[:600])
    check("English: Closed's words (Clear all, Last 14 days) and its script has the table's keys, never an English message of its own",
          "Last 14 days" in eclosed and "Clear all" in eclosed and "SST('js.closed.clear')" in en["/closed"].text and "'Clearing" not in en["/closed"].text and "No notice" not in en["/closed"].text)
    check("English: the Projects page (title, note) reads the old words", "Projects" in eproj and "alpha" in eproj.lower(), eproj[:300])

    # ---- 6. the test locale
    (LOC / "ko.json").write_text(json.dumps(test_locale()), encoding="utf-8"); set_dir(LOC); i18n._WARNED.clear(); i18n._LOADED.clear()
    check("the test locale loaded", i18n.available() == ["en", "ko"], i18n.available())
    check("the person's choice is saved", post_lang("ko").status_code == 200)
    ko = {p: get(p, MINA) for p in PAGES}
    check("the pages answer 200 in the test locale and <html lang> follows the person", all(r.status_code == 200 and '<html lang="ko">' in r.text for r in ko.values()), {p: r.status_code for p, r in ko.items()})
    en2 = {p: get(p, NOOR) for p in PAGES}
    check("a person who never picked a language still reads English, no marker", all("[x:" not in r.text for r in en2.values()))
    for p in PAGES:
        h = ko[p].text
        left = words_left(h, DATA)
        check(f"{p}: every interface word is in the test locale (no English word left outside a marker)", not left, ctx(h, left))
    ka = ko["/audits"].text; kb = body(ka)
    check("Audits: the title, the group and run headings, the paces and the table's heads carry markers", all(MARK(EN[k]) in kb for k in ("audit.title", "audit.groups", "audit.findings", "audit.pace_min", "audit.pace_ten",
          "audit.th_started", "audit.th_took", "audit.th_items", "audit.th_findings", "audit.th_calls")), kb[:700])
    check("Audits: each group's name and description are the test locale's, one for each of the eight groups", all(MARK(g["name"]) in kb and MARK(g["desc"]) in kb for g in ov.GROUPS), kb[:400])
    check("Audits: a pace and a mode word in the group's list are the test locale's, an audit's own name stays as written",
          all(MARK(EN["audit.pace." + r2._AUDIT_PACES[w]]) in kb for w in PACES if w in r2._AUDIT_PACES) and all(MARK(EN["audit.mode." + m]) in kb for m in ("shadow", "off") if m in ea.lower()), kb[-500:])
    check("Audits: a finding's source word and the run that did not finish are the test locale's; the log's own detail stays as written", MARK(EN["audit.source.filing"]) in kb and MARK(EN["audit.run_unfinished"]) in kb
          and "waits on a thing that closed" in kb and "went quiet" in kb, kb[-900:])
    check("Audits: the Audit now button, the page's note and its sub line; the runs hint ends with the button's own label in the test locale", MARK(EN["panel.audit.now"]) in kb and MARK(EN["audit.note_logged"]) in kb
          and ", and " + MARK(EN["panel.audit.now"]) + "]" in kb, kb[-300:])
    kr = ko["/projects/alpha"].text; krb = body(kr)
    check("Routing: its headings and table heads are the test locale's; the notice's gist and the log-only reason stay as written", all(MARK(EN[k]) in krb for k in ("routing.sec_sessions", "routing.sec_notices", "routing.th_source", "routing.th_what"))
          and GIST in krb and "nothing to deliver" in krb, krb[:900])
    kj = body(ko["/projects"].text)
    check("Projects: the title, the note and the heads are the test locale's, the project's own names stay", all(MARK(EN[k]) in kj for k in ("projects.title", "projects.note", "projects.th_project", "projects.th_agents")), kj[:600])
    kc = ko["/closed"].text; kcb = body(kc)
    check("Closed: the headings, the Clear all button and the note are the test locale's, the items' subjects stay", MARK(EN["closed.last14"]) in kcb and MARK(EN["closed.clear_all"]) in kcb and TITLE in kcb, kcb[:600])
    check("Closed: the script reads its words from the table: SST keys, no English message, and the relative words come from age.*",
          all(f"SST('js.closed.{w}')" in kc for w in ("clear", "undo", "not_restored", "clearing")) and "SST('js.closed.aria'" in kc and "SST(n===1?'js.closed.note_one':'js.closed.note_many'" in kc
          and "age.min" in kc and "'Undo'" not in kc and "'Clear'" not in kc and "'just now'" not in kc and "m ago" not in visible(kc).split("<script>")[-1], re.findall(r"SST\([^)]*\)", kc)[:12])
    check("Closed: the page's head hands the script the js.closed.* and age.* tables (SST reads them)", "js.closed.clear" in kc and "age.min" in kc, kc[:300])

    # ---- 7. the builders drawn straight, in the test locale
    bd = r2.Board(f"{tmp}/store")
    with i18n.use("ko"):
        fy = bd.for_you_html(); sent = {k: bd.sent_html({"sent": k}, "alpha-x") for k in bd._SENT}; sess = bd.sessions_html("projects/alpha")
        r = bd.item("a1"); r["metadata"] = {**r["metadata"], **SAID_META}
        s1, s2 = bd.said_tag(r, 1, "Acked-by"), bd.said_tag(r, 2, "Acked-by"); s9 = bd.said_tag(r, 9, "Acked-by")
        bd.COMPLETED_PAGE = 2; comp = bd.completed_html(1); comp2 = bd.completed_html(2); comp_n = r2.Board.completed_html
    fyb, fyl = body(fy), words_left(fy, DATA | {"fy"})
    check("For you: its heading, the urgent mark, the seen buttons and the empty line are the test locale's; the row's own words stay", MARK(EN["watch.for_you"]) in fyb and MARK(EN["foryou.urgent"]) in fyb
          and MARK(EN["foryou.seen_btn"]) in fyb and MARK(EN["foryou.all_seen"]) in fyb and FY in fyb and not fyl, (fyl, ctx(fy, fyl)))
    check("sent notices: every code reads the test locale's text, one marker each, and a name in a notice is the name", all(h.count("[x:") >= 1 for h in sent.values() if h) and "alpha-x" in sent["done"] and len(sent) >= 10,
          {k: v[:80] for k, v in sent.items() if v and "[x:" not in v})
    check("sessions: the group heading, the flag and its hover and the owns line are the test locale's; names stay", MARK(EN["sessions.flag_nosession"]) in body(sess[1]) or MARK(EN["sessions.agents"]) in body(sess[1]) or MARK(EN["sessions.session"]) in body(sess[1]), sess[1][:500])
    check("said tag: the checked and unchecked tags, their detail and the no-record line are the test locale's; the quote he said stays as written", SAID_QUOTE in s1 and MARK(EN["said.checked"]) in body(s1) or MARK(EN["said.checked"]) in s1, s1[:500])
    check("said tag: an unchecked entry reads the test locale's label, its reason is the entry's own", "unproved" in s2 and "no transcript" in s2 and "[x:" in s2, s2[:500])
    check("said tag: an entry that does not exist reads the test locale's no-record line", MARK(EN["said.no_record"]) in body(s9), s9[:300])
    check("Closed's Completed section: the pager and the range line are the test locale's", MARK(EN["closed.newer"]) in body(comp2) and MARK(EN["closed.older"]) in body(comp) and "[x:" in body(comp) and bd.COMPLETED_PAGE == 2, body(comp)[-400:])

    # ---- 8. a translation with a double quote or an angle bracket in a hover text cannot break the attribute that holds it
    from html.parser import HTMLParser
    TIP = 'say "seen" <now> & done'
    (LOC / "ko.json").write_text(json.dumps(test_locale(**{"foryou.seen_tip": TIP})), encoding="utf-8"); i18n._WARNED.clear(); i18n._LOADED.clear()
    class _Titles(HTMLParser):
        def __init__(self): super().__init__(); self.titles = []
        def handle_starttag(self, tag, attrs):
            if tag == "button" and ("class", "b") in attrs: self.titles.append(dict(attrs).get("title"))
    with i18n.use("ko"): fyq = bd.for_you_html()
    pt = _Titles(); pt.feed(fyq)
    check("For you: a seen_tip translation with quotes, brackets and an ampersand stays whole in the button's title attribute", [tt for tt in pt.titles if tt] and all(tt == TIP for tt in pt.titles if tt) and "<now>" not in fyq.split("title=", 1)[1].split(">", 1)[0], (pt.titles, fyq[-300:]))

    # ---- 9. the runs hint names the button from the button's own key: a translation can put it anywhere in the sentence
    (LOC / "ko.json").write_text(json.dumps(test_locale(**{"audit.runs_hint": "<<{button}>> then {times}", "panel.audit.now": "GO-NOW"})), encoding="utf-8"); i18n._WARNED.clear(); i18n._LOADED.clear()
    kh = body(get("/audits", MINA).text)
    check("Audits: the runs hint is the translation's template, its {button} is the button's own label (one source for both)", "<<GO-NOW>> then" in kh and kh.count("GO-NOW") >= 2 and "and Audit now" not in kh, kh[-400:])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
