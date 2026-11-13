"""Scenario test for the Audits page (GET /audits) and the side panel's audit card, on a temp state dir: no live store, no network, the cue replaced by a recorder.

Covers, from the findings log and the run records the audits already write (audit_overview.py):
  * the page with findings: the paces, the eight groups in order each with its number of audits and its findings in the last 24 hours (the older finding left out), a dash ("not logged") for the two
    groups that keep no findings log, the newest findings first with a link to each item, the runs table, the page's note; text from the log is escaped;
  * the page without findings (a log with nothing in it, no run record): plain empty lines and no error text; the findings log off; the audit off;
  * the card's shortlist in the side panel: the same rows, a dash and never a zero for a group that keeps no log, and the card's name a link to the page;
  * Audit now in both places: two buttons, one script, one POST /audit/now (the same route, the same refusals), the page's disabled while a run is in progress;
  * GET /audit/status carries the card's rows the script draws;
  * signed out: the board's sign-in first, as for every page.

    tests/run-suite audits_page        → exit 0 / 1"""
import html as _html, json, os, pathlib, re, sys, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="audpage-test-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "brain/projects", "state/audit"): (T / d).mkdir(parents=True)
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/anchors.json").write_text("{}"); (T / "store/next-id").write_text("1")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

from stackshot.core import config; from stackshot.audit import audit; from stackshot.audit import audit_overview as ov
config.CFG["audit"]["at"] = "05:00"
D = T / "state/audit"; LOG = D / "findings-log.jsonl"
NOW = time.time()
def row(ago, source, id_, kind, detail="detail", agent="the-agent"): return {"at": NOW - ago, "source": source, "id": id_, "kind": kind, "agent": agent, "project": "projects/x", "detail": detail}
def write_log(rows): LOG.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
def text_of(html):
    """The words of a page: no style, no script, no tags."""
    h = re.sub(r"(?s)<(style|script)[^>]*>.*?</\1>", "", html)
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", h)))
NAMES = ["Silence", "Filing", "Wording", "Dates", "Proof and patterns", "Pages and agents", "Fleet and services", "Text and rules"]

from stackshot.web import server
from stackshot.web.auth import signin as _signin
server._publish = lambda: None
from starlette.testclient import TestClient
posts = []
server._audit.cue = lambda reason: (posts.append(reason), (202, "audit cued to falcon-audit"))[1]

# ---- 1. the catalog and the counts, before any page
check("the catalog: eight groups in the order the page lists them; the two that report to a machine or to CI keep no findings log", [g["name"] for g in ov.GROUPS] == NAMES
      and [g["log"] for g in ov.GROUPS] == [True] * 6 + [False, False])
check("group_of: a finding's kind says its group; `stale` is the dates pass's by its source; a kind no group lists is None",
      ov.group_of("run", "stuck-elsewhere") == "filing" and ov.group_of("filing", "board checks:why-not-now") == "filing" and ov.group_of("run", "next rules:N3") == "wording"
      and ov.group_of("silence", "stale") == "silence" and ov.group_of("dates", "stale") == "dates" and ov.group_of("run", "proof-wait") == "proof" and ov.group_of("run", "older-than-page") == "pages"
      and ov.group_of("run", "no-such-kind") is None)
from stackshot.audit import audit_checks; from stackshot.audit import audit_run
KINDS = set(audit_checks.FIX) | set(audit_checks.CHECKS_CODE) | set(audit_checks.CHECKS_FILING) | set(audit_checks.CHECKS_DATES) | set(audit_run.CHECKS_MODEL) | {"proof-wait"}
check("every finding category the audits can write (the FIX table and the CHECKS_* tables, plus proof-wait) maps to a group, whichever pass wrote it",
      len(KINDS) >= 14 and all(ov.group_of(src, k) is not None for k in KINDS for src in ("run", "silence", "filing", "dates")), sorted(k for k in KINDS if ov.group_of("run", k) is None))
check("a category with a sub-kind (`next rules:N3`, `board checks:why-not-now`) keeps its group", all(ov.group_of("run", f"{k}:x") == ov.group_of("run", k) for k in KINDS if k != "stale"))
def _modes():
    return {k: ov._mode(k) for k in ("hourly_line", "hand_idle", "balance")}
_saved = dict(config.CFG.get("audit", {}))
try:
    config.CFG["audit"].pop("hourly_line", None); config.CFG["audit"].pop("hand_idle", None); config.CFG["audit"].pop("balance", None)
    m_default = _modes()
    config.CFG["audit"]["hourly_line"] = False; m_noline = _modes()
    config.CFG["audit"]["hourly_line"] = True; config.CFG["audit"]["hand_idle"] = False; m_nohand = _modes()
finally:
    config.CFG["audit"].clear(); config.CFG["audit"].update(_saved)
check("the audit modes: all three are on by default; the idle hand-over reads off without the hourly line it works from (the line off leaves the balancer on), and off when its own switch is off",
      m_default == {"hourly_line": "on", "hand_idle": "on", "balance": "on"} and m_noline == {"hourly_line": "off", "hand_idle": "off", "balance": "on"}
      and m_nohand == {"hourly_line": "on", "hand_idle": "off", "balance": "on"}, (m_default, m_noline, m_nohand))
check("item_path: a numbered id is /items/<n>, a temporary id keeps its prefix, any other shape is no link", ov.item_path(f"board#{12}") == "12" and ov.item_path(f"board-tmp-x#{7}") == "board-tmp-x-7"
      and ov.item_path(f"board-tmp-X#{7}") is None and ov.item_path("elsewhere#3") is None and ov.item_path("12") is None)

# ---- 2. the page with findings
write_log([row(600, "silence", f"board#{11}", "stale"), row(1200, "filing", f"board#{12}", "stuck-elsewhere", "waits on a thing that closed"),
           row(1300, "filing", f"board#{13}", "board checks:why-not-now"), row(1400, "run", f"board#{14}", "ask-missing"), row(1500, "run", f"board#{15}", "next rules:N2"),
           row(1600, "dates", f"board#{16}", "stale"), row(1700, "run", f"board#{17}", "proof-wait"), row(1800, "run", f"board#{18}", "older-than-page"),
           row(1900, "run", f"board-tmp-q#{9}", "stuck-elsewhere", "<script>alert(1)</script> & more"),
           row(90000, "filing", f"board#{19}", "stuck-elsewhere", "older than a day"), {"at": NOW - 60, "source": "run", "id": "", "kind": "stale"}])
(D / "run-2026-02-23.json").write_text(json.dumps({"started": NOW - 5000, "finished": NOW - 4300, "items_read": 41, "findings": [{"id": "a"}, {"id": "b"}], "calls": {"made": 6}}))
check("counts: per group in the last 24 hours, the older finding and the row without an id left out, None for the two groups with no log",
      ov.counts(NOW) == {"silence": 1, "filing": 3, "wording": 2, "dates": 1, "proof": 1, "pages": 1, "fleet": None, "text": None}, ov.counts(NOW))
with TestClient(server.mcp.http_app()) as c:
    r = c.get("/audits")
    h = r.text; w = text_of(h)
    check("GET /audits: 200 as HTML, not cached", r.status_code == 200 and r.headers["content-type"].startswith("text/html") and r.headers.get("cache-control") == "no-store", (r.status_code, r.headers))
    check("the page: the title, an h1 'Audits' and the three paces", "<title>Audits ·" in h and h.count("<h1>Audits</h1>") == 1
          and all(x in w for x in ("Every minute", "Every 10 minutes", "05:00")), w[:400])
    check("the groups: eight folds in the catalog's order, each with its number of audits", re.findall(r'<details class="audg"><summary><span class="agn"><b>([^<]+)</b>', h) == NAMES
          and re.findall(r'<span class="anum">(\d+) audits</span>', h) == [str(len(g["audits"])) for g in ov.GROUPS] and "53 audits in 8 groups." in w, re.findall(r'<span class="anum">(\d+) audits', h))
    nums = re.findall(r'<span class="anum(?: hit)?">((?:\d+ found)|not logged|log off)</span>', h)
    check("the groups' findings in 24 hours from the log: 1, 3, 2, 1, 1, 1, and 'not logged' (never a zero) for the two that keep no log", nums == ["1 found", "3 found", "2 found", "1 found", "1 found", "1 found", "not logged", "not logged"], nums)
    check("a group with findings is marked (hit), a group without a log is not", h.count('<span class="anum hit">') == 6 and "0 found" not in h)
    fe = re.findall(r'<div class="af">(.*?)</div></div>', h)
    check("the latest findings: the ten newest of the last 24 hours (nine here, the older one left out), newest first, each item linked to its page",
          len(fe) == 9 and 'href="/items/11"' in fe[0] and 'href="/items/12"' in fe[1] and "waits on a thing that closed" in fe[1] and "older than a day" not in h
          and 'href="/items/board-tmp-q-9"' in h, [x[:80] for x in fe])
    check("the findings' words from the log are escaped, not run", "<script>alert(1)</script>" not in h and "&lt;script&gt;alert(1)&lt;/script&gt; &amp; more" in h)
    check("the findings line says how many in the last 24 hours and the pass that made each", "9 in the last 24 hours" in w and all(x in w for x in (" · silence · ", " · filing · ", " · dates · ", " · daily run · ")))
    check("a finding's link text is the item's id as the log writes it", re.findall(r'<div class="af"><a href="/items/[^"]+">([^<]+)</a>', h)[:2] == [f"board#{11}", f"board#{12}"]
          and f'href="/items/board-tmp-q-9">board-tmp-q#{9}</a>' in h, re.findall(r'<div class="af"><a[^>]*>([^<]+)</a>', h))
    check("the runs: the record's start, its length, items read, findings and calls", re.search(r"<tr><td>[^<]+</td><td>700 s</td><td>41</td><td>2</td><td>6</td></tr>", h) is not None
          and "No audit has run yet." not in h, re.findall(r"<tr>.*?</tr>", h)[:3])
    check("the page's note says what a dash means", 'shows a dash on the card and "not logged" here, not a zero' in w)
    check("no error text on the page", not re.search(r"Traceback|[Ee]rror|[Ee]xception|undefined|\bNone\b|\bNaN\b", w), w)

    # ---- 3. the card
    cd = h[h.find('<div id="audit"'):]; cd = cd[:cd.find("</div>") + 6]
    check("the card: its name is a link to the Audits page, the Audit now text link beside it", '<b class="lbl mh"><a class="nm" href="/audits">Audits ↗</a><button type="button" id="audit-now">Audit now</button></b>' in cd, cd[:300])
    rows = re.findall(r'<span class="lbl">([^<]+)</span><span class="val a-n">(\d+)</span><span class="val a-n( hit)?">([^<]+)</span>', cd)
    check("the card's shortlist: each group with its number of audits and its findings in 24 hours, the same numbers as the page",
          [(a, int(b), d) for a, b, _, d in rows] == [(g["name"], len(g["audits"]), n) for g, n in zip(ov.GROUPS, ["1", "3", "2", "1", "1", "1", "–", "–"])], rows)
    check("the card: a dash, never a zero, for Fleet and services and Text and rules; a group with findings is marked (hit); the note says what the dash means",
          [d for *_, d in rows][-2:] == ["–", "–"] and sum(1 for x in rows if x[2]) == 6 and '<span class="a-cn">– keeps no findings log</span>' in cd and ">0</span><span" not in cd.replace('class="val a-n">0', ""), cd)
    check("the card's header cells name its columns", '<span class="a-h">audits</span><span class="a-h">found, 24 h</span>' in cd)
    check("the card and the status endpoint say the same: GET /audit/status has the card's rows",
          c.get("/audit/status").json()["card"] == {"groups": [{"name": g["name"], "audits": len(g["audits"]), "found": n} for g, n in zip(ov.GROUPS, [1, 3, 2, 1, 1, 1, None, None])], "note": "– keeps no findings log"})

    # ---- 4. Audit now in both places
    check("Audit now twice: the card's text link and the page's button, each a real button; the page's has the .b look and a message line of its own",
          h.count('id="audit-now"') == 1 and h.count('id="audit-now-page"') == 1 and '<button type="button" class="b" id="audit-now-page">Audit now</button>' in h
          and 'id="audit-page-msg"' in h and h.count(">Audit now</button>") == 2)
    aj = re.search(r"<script>(\(function\(\)\{var E=document\.getElementById\('audit'\).*?)</script>", h, re.S)
    check("one script drives both: it finds both buttons and both message lines, and has the one cue that POSTs /audit/now (no other route)",
          aj is not None and aj.group(1).count("fetch('/audit/now'") == 1 and "document.getElementById('audit-now-page')" in aj.group(1) and "document.getElementById('audit-page-msg')" in aj.group(1)
          and "B.forEach(function(b){b.addEventListener('click',function(){if(!b.disabled)cue()})})" in aj.group(1) and "/audit/start" not in aj.group(1), aj and aj.group(1)[:200])
    r1 = c.post("/audit/now")
    check("the buttons' one route: POST /audit/now cues the audit with the same answer, as the card's always did", r1.status_code == 202 and r1.text == "audit cued to falcon-audit" and posts == ["button"], (r1.status_code, r1.text, posts))
    (D / "run-2026-02-24.json").write_text(json.dumps({"started": time.time() - 60, "finished": None, "findings": []}))
    hr = c.get("/audits").text
    check("a run in progress: both buttons are disabled (the card's and the page's), the card says since when", '<button type="button" class="b" id="audit-now-page" disabled>' in hr
          and 'id="audit-now" disabled>' in hr and "Audit running since" in hr, re.findall(r'<button[^>]*audit-now[^>]*>', hr))
    (D / "run-2026-02-24.json").unlink()

    # ---- 5. the page without findings
    write_log([]); (D / "run-2026-02-23.json").unlink()
    r = c.get("/audits"); h = r.text; w = text_of(h)
    check("without findings: 200, 'No findings in the last 24 hours.' and 'No audit has run yet.' as plain lines, every logged group at 0 found, the two others still 'not logged'",
          r.status_code == 200 and "No findings in the last 24 hours." in w and "No audit has run yet." in w
          and re.findall(r'<span class="anum(?: hit)?">((?:\d+ found)|not logged|log off)</span>', h) == ["0 found"] * 6 + ["not logged"] * 2, w[:600])
    check("without findings: no error text, no finding rows, no table", not re.search(r"Traceback|[Ee]rror|[Ee]xception|undefined|\bNone\b|\bNaN\b", w) and 'class="af"' not in h and "<table>" not in h, w)
    check("without findings: the card shows zeros for the logged groups and dashes for the others", re.findall(r'<span class="val a-n">([^<]+)</span><span class="val a-n">([^<]+)</span>', h)[:1] == [("9", "0")]
          and h.count('<span class="val a-n">–</span>') == 2)
    LOG.unlink()
    r = c.get("/audits")
    check("no findings log file at all: the same page, still no error", r.status_code == 200 and "No findings in the last 24 hours." in r.text and "Traceback" not in r.text)

    # ---- 5b. a damaged log: the good lines still count, nothing fails
    good = [row(600, "silence", f"board#{21}", "stale"), row(700, "filing", f"board#{22}", "stuck-elsewhere", "kept")]
    LOG.write_bytes(("".join(json.dumps(x) + "\n" for x in good) + "\n" + "this is text, not JSON\n" + "[1, 2, 3]\n").encode("utf-8")
                    + b"\n" + json.dumps(row(800, "dates", f"board#{23}", "stale")).encode("utf-8") + b'\n{"at": 1, "x": "\xe2\x82')
    dmg = {"silence": 1, "filing": 1, "wording": 0, "dates": 1, "proof": 0, "pages": 0, "fleet": None, "text": None}
    check("a damaged log (a blank line, a line that is not JSON, one that is JSON but no finding, a last line torn mid-character): the good lines still count", ov.counts(NOW) == dmg, ov.counts(NOW))
    check("read_findings and audit_run.read_log skip the damaged lines and keep the good ones",
          [x["id"] for x in ov.read_findings(NOW - 86400)] == [f"board#{21}", f"board#{22}", f"board#{23}"] and len(audit_run.read_log(NOW - 86400)) == 3, [x["id"] for x in ov.read_findings(NOW - 86400)])
    r = c.get("/audits"); h = r.text
    check("a damaged log: GET /audits is 200 with the good findings listed, newest first, and no error text",
          r.status_code == 200 and re.findall(r'<div class="af"><a href="/items/\d+">([^<]+)</a>', h) == [f"board#{21}", f"board#{22}", f"board#{23}"] and not re.search(r"Traceback|[Ee]rror|[Ee]xception", text_of(h)), (r.status_code, h[-300:]))
    r = c.get("/audit/status")
    check("a damaged log: GET /audit/status is 200 and the card counts the good lines", r.status_code == 200 and [g["found"] for g in r.json()["card"]["groups"]] == [1, 1, 0, 1, 0, 0, None, None], (r.status_code, r.text[:300]))
    LOG.unlink()

    # ---- 5c. the page only reads: a state folder with no audit folder stays without one
    import shutil
    shutil.rmtree(D)
    r = c.get("/audits")
    check("a fresh state directory: GET /audits renders (no audits yet) and makes no audit folder", r.status_code == 200 and "No findings in the last 24 hours." in r.text and not D.exists(), (r.status_code, D.exists()))
    ov.read_findings(NOW - 86400); ov.counts(NOW); ov.card(NOW); ov.overview(NOW); audit.runs(); audit.running(NOW); audit.status(NOW)
    check("reading the findings log, the run records and the status with no audit folder makes none", not D.exists(), D.exists())
    D.mkdir()

    # ---- 5d. what the page does with odd data: escaping, the row cap, the day's bounds, one read, a time no date holds, a line separator in a finding
    write_log([row(100 + i, "run", f"board#{40 + i}", "ask-missing", f"finding {i}", agent=("<b>bold</b>" if i == 0 else "an-agent")) for i in range(12)]
              + [row(-3600, "filing", f"board#{60}", "stuck-elsewhere", "from the future")])
    check("until bounds the day: a row after `until` (a clock ahead of this one) is neither counted nor listed", ov.counts(NOW)["filing"] == 0 and ov.counts(NOW)["wording"] == 12
          and all(x["detail"] != "from the future" for x in ov.read_findings(NOW - 86400, NOW)) and any(x["detail"] == "from the future" for x in ov.read_findings(NOW - 86400)),
          (ov.counts(NOW), len(ov.read_findings(NOW - 86400, NOW))))
    reads = []; real_read = ov.read_findings
    ov.read_findings = lambda *a, **k: (reads.append(a), real_read(*a, **k))[1]
    try:
        r = c.get("/audits"); h = r.text; w = text_of(h)
    finally:
        ov.read_findings = real_read
    check("the page lists at most ten findings and says how many there were in all", r.status_code == 200 and h.count('class="af"') == 10 and "12 in the last 24 hours" in w and "from the future" not in h, (h.count('class="af"'), w[:300]))
    check("the findings log is read once for the page, the groups' counts and the side panel's card", len(reads) == 1, len(reads))
    cd = h[h.find('<div id="audit"'):]; cd = cd[:cd.find("</div>") + 6]
    check("the card and the page's groups say the same number from that one read", '<span class="lbl">Wording</span><span class="val a-n">12</span><span class="val a-n hit">12</span>' in cd
          and re.findall(r'<span class="anum(?: hit)?">(\d+ found)</span>', h)[2] == "12 found", cd[:600])
    check("an agent name from the log is escaped on the page, never run as markup", "<b>bold</b>" not in h and "&lt;b&gt;bold&lt;/b&gt;" in h, [x[:100] for x in re.findall(r'<div class="am">.*?</div>', h)][:2])
    check("item_path takes ASCII digits only and a whole id: no other script's digits, no newline after the number, no trailing or doubled dash in a temporary prefix",
          ov.item_path("board#\u0661\u0662") is None and ov.item_path(f"board#{12}\n") is None and ov.item_path(f"board-tmp-x-#{7}") is None and ov.item_path(f"board-tmp-x--y#{7}") is None
          and ov.item_path(f"board-tmp-x-y#{7}") == "board-tmp-x-y-7", (ov.item_path("board#\u0661\u0662"), ov.item_path(f"board-tmp-x-#{7}")))
    check("the Audit now button on the page is really hidden when the script hides it (the .b look sets display, so the hidden attribute needs its own rule)", "#audit-now-page[hidden]{display:none}" in h)
    check("a group's summary has a disclosure marker that turns when it opens", "details.audg .agn b::before{content:'▸'" in h and "details.audg[open] .agn b::before{transform:rotate(90deg)}" in h)
    LOG.write_bytes((json.dumps(row(60, "filing", f"board#{71}", "stuck-elsewhere", "one\u2028two\u0085three\u2029four"), ensure_ascii=False) + "\n"
                     + json.dumps(row(70, "run", f"board#{72}", "ask-missing", "next"), ensure_ascii=False) + "\n").encode("utf-8"))
    check("a line separator inside a finding (U+2028, U+0085, U+2029) does not split its row: the overview, audit_run.read_log and prune_log read it whole",
          ov.counts(NOW)["filing"] == 1 and ov.counts(NOW)["wording"] == 1 and len(audit_run.read_log(NOW - 86400)) == 2, (ov.counts(NOW), len(audit_run.read_log(NOW - 86400))))
    audit_run.prune_log(NOW)
    check("pruning the log keeps both rows and the text of the one with the separators", [x["detail"] for x in audit_run.read_log(NOW - 86400)] == ["one\u2028two\u0085three\u2029four", "next"] and len(ov.read_findings(NOW - 86400)) == 2,
          [x["detail"] for x in audit_run.read_log(NOW - 86400)])
    LOG.unlink()
    # the paces' last-run words: the clock for today, the date and clock for another day; a time no date can hold is a dash and the page still renders
    real_runner = server._runner_status
    try:
        server._runner_status = lambda: {"ticks": [{"name": "filing_tick", "last_run": time.time() - 5}]}
        today = text_of(c.get("/audits").text)
        server._runner_status = lambda: {"ticks": [{"name": "filing_tick", "last_run": time.time() - 3 * 86400}]}
        old = text_of(c.get("/audits").text)
        server._runner_status = lambda: {"ticks": [{"name": "filing_tick", "last_run": 1e300}]}
        (D / "run-2026-02-25.json").write_text('{"started": 1e300, "finished": 1e300, "items_read": 3, "findings": []}')
        far = c.get("/audits")
    finally:
        server._runner_status = real_runner
    check("the ten-minute pace says its last run as the clock today", re.search(r"last \d\d:\d\d: filing, dates, audit lines", today) is not None, re.findall(r"Every 10 minutes.{0,60}", today))
    check("... and with its date for a run of another day", re.search(r"last [A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2}(?:st|nd|rd|th) \d\d:\d\d: filing, dates, audit lines", old) is not None, re.findall(r"Every 10 minutes.{0,60}", old))
    check("a time no date can hold (1e300 in the runner's record and in a run record): the page answers 200 and draws a dash", far.status_code == 200 and "last –: filing, dates, audit lines" in text_of(far.text), (far.status_code, far.text[:200]))
    (D / "run-2026-02-25.json").unlink()

    # ---- 6. the findings log off
    config.CFG["audit"]["pattern_review"] = "off"
    r = c.get("/audits"); h = r.text; w = text_of(h)
    check("the findings log off: every group says so, the feed says findings are not listed, the card's note says the log is off, no count anywhere",
          r.status_code == 200 and re.findall(r'<span class="anum">((?:\d+ found)|not logged|log off)</span>', h) == ["log off"] * 6 + ["not logged"] * 2
          and "The findings log is off, so findings are not listed here." in w and "– the findings log is off" in h and "found</span>" not in h.replace("found, 24 h", ""), w[:600])
    config.CFG["audit"]["pattern_review"] = "shadow"

    # ---- 7. the audit off
    config.CFG["audit"]["enabled"] = False
    r = c.get("/audits"); h = r.text; w = text_of(h)
    check("the audit off: the page says so, has no Audit now button, and the card is hidden",
          r.status_code == 200 and "The audit is off" in w and 'id="audit-now-page"' not in h and '<div id="audit" class="pc audit"' in h and re.search(r'<div id="audit"[^>]*\bhidden>', h) is not None, w[:300])
    config.CFG["audit"]["enabled"] = True

    # ---- 8. signed out
    real_mode = _signin._auth_mode; _signin._auth_mode = (lambda: "google"); server._cfg.CFG["auth"]["ui_open"] = False
    try:
        r = c.get("/audits", follow_redirects=False)
        check("signed out: GET /audits asks for the board's sign-in first, as every page does, and shows no audit", r.status_code == 302 and r.headers["location"] == "/ui/login?next=%2Faudits" and "Audits" not in r.text, (r.status_code, r.headers.get("location")))
        r = c.post("/audits", follow_redirects=False)
        check("the page takes GET only", r.status_code == 405, r.status_code)
    finally:
        _signin._auth_mode = real_mode; server._cfg.CFG["auth"]["ui_open"] = True

_scratch.cleanup()
if fails: print(f"FAILED: audits page scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1)
print(f"ok: audits page scenario, {len(ran)} checks")
