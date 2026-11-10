"""Scenario test for the results page of the board at the root (ui/search.py, search.words / find / snippets in search.py, GET /search in server.py) — fixture store that is a git repo,
the HTTP route through Starlette's test client; no live store, no network.

The page searches by the fleet tool's rule and is drawn as its search page: one newest-first list under When / Kind / State filters, each with the number it adds, and "Show 25 more".

Covers:
  * the matching rule (the fleet tool's): the query is lower-cased and split on white space, "quoted text" is one unit, and every unit must be a case-insensitive substring of the same entry; no
    word or prefix logic ("redesign" finds "redesigned", a Japanese stem finds the word it starts), a quoted phrase must appear contiguously;
  * the marks: every match is marked, in the title and in the excerpt, a phrase as one;
  * the default window: a search started from the box is the last 7 days (older items, History, project pages and sessions stay out), a When chip widens or narrows it (1 h … 3 days, All), the chip wins over
    the form's hidden value, Dates reads From and To in the board's zone, a bad or missing date is said, one too early or too late to show is held to the edge;
  * a query of more than 8 units (a quoted phrase is one) is refused with the fleet tool's sentence instead of searched;
  * the filters and their counts: the Kind and State boxes cut the list, the number beside a box is what ticking it adds with the other filters as they stand, State leaves projects and sessions alone,
    a search that finds nothing says which window or box holds matches;
  * Show 25 more: 25 rows first, the link adds 25 and lands on the first new row, the last page has no link, the cap cuts the list and says so, a bad `n` is the first page;
  * the form: a plain GET at the root whose Enter key searches with the filters as they are, the header's own box is there too and searches in place (every other page's header box opens its results in a new tab), every text is escaped;
  * an index built without FTS5 finds the same.

    tests/run-suite ui_search       → exit 0 / 1"""
import datetime, json, logging, os, pathlib, re, subprocess, sys, time
from urllib.parse import quote

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="searchtest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
EMAIL = "oliver@example.org"
SALA = "https://sala.example.org/#s={name}"

toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
toml = toml.replace('session_view = ""', f'session_view = "{SALA}"', 1); assert "sala.example.org" in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org")
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "secrets", "touch"): (T / d).mkdir(parents=True)
STORE = T / "store"
NOW = time.time()
H, D = 3600.0, 86400.0
iso = lambda t: datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

S1, S2, S3 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({
    S1: {"name": "home-redesign-main", "machine": "a", "url": "", "seen": iso(NOW - 120)},                                          # a live pane, seen two minutes ago
    S2: {"name": "home-redesign-old", "machine": "a", "url": "", "seen": iso(NOW - 30 * D), "gone": iso(NOW - 29 * D)},      # no live pane, last seen long ago
    S3: {"name": "home-x-main", "machine": "a", "url": "", "seen": iso(NOW - 60)}}))


def page_entry(name):
    return {"title": name.title() + " project", "name": name.title(), "org": "home", "tags": [], "type": "project", "session": "home-x-main", "status": "active", "board": [], "board_row": False,
            "updated": 1, "mirror": "https://example.invalid/" + name}
(STORE / "projects.json").write_text(json.dumps({"pages": {"projects/alpha": page_entry("alpha"), "projects/beta": page_entry("beta")}})); (STORE / "next-id").write_text("200"); (STORE / "anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n- the redesign of the narwhal tusk is calibrated\n\n## Timeline\n- started\n")
(T / "brain/projects/beta.md").write_text("---\ntitle: Beta\n---\n# Beta\n\n## Current state\n- the redesign of the ferret is waiting\n\n## Timeline\n- started\n")
os.utime(T / "brain/projects/beta.md", (NOW - 30 * D, NOW - 30 * D))                                                                # a page that last changed a month ago


def item(i, subject, description="A thing. It lives here. Done when done.", age=H, status="open", **md):
    (STORE / f"a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": description, "status": status,
                                                   "metadata": {"owner": S3, "project": "projects/alpha", **md}, "updated": NOW - age}, ensure_ascii=False))


def git(*a): subprocess.run(["git", "-C", str(STORE), *a], check=True, capture_output=True)


git("init", "-q"); git("config", "commit.gpgsign", "false")
item(1, "[home] Redesign the quokka page", "an approved redesign flow", age=1 * H)
item(2, "[home] Redesigned parser", "the parser was rewritten", age=2 * H)
item(3, "[home] Notes", "approved the new redesign last week", age=3 * H)
item(4, "[home] Closed redesign work", "closed", age=30 * H, status="completed", outcome="done", reason="the redesign is shipped")
item(5, "[home] Old redesign leftovers", "a month old", age=30 * D)
item(6, "[home] Danger <script>alert(1)</script> redesign", "<img src=x onerror=alert(2)> redesign", age=4 * H)
item(7, "[home] ボード・検索・試験", "日本語・説明です", age=5 * H)
BULK = 60
for k in range(BULK):
    item(10 + k, f"[home] Bulknote {k:02d}", "the needle sits in this one", age=(6 * 60 + k) * 60)                                    # 60 items, a minute apart, newest first by number
git("add", "-A"); git("commit", "-q", "-m", "fixture")

sys.path.insert(0, STACK); logging.disable(logging.CRITICAL)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.web import server; from stackshot.web import render; from stackshot.web import search
from stackshot.web.ui import search as s2
server._publish = lambda: None
from starlette.testclient import TestClient

fresh = lambda: render.Board(str(STORE))
SYNC = search.sync(fresh())
check("the index is built from the fixture: every item, both project pages, the sessions", SYNC["items"] == 7 + BULK and SYNC["pages"] == 2 and SYNC["sessions"] >= 3 and SYNC["left"] == 0, SYNC)

# ---- 1. the rule, on its own
W = search.words
check("words: a bare word is a unit; quotes keep a phrase as one unit; case is folded; punctuation stays in the unit; empty units are dropped",
      W('"Approved Redesign" foo-bar x _ ??') == ["approved redesign", "foo-bar", "x", "_", "??"] and W("Redesign") == ["redesign"] and W("") == [] and W("   ") == [] and W('"  " ab') == ["ab"], W('"Approved Redesign" foo-bar x _ ??'))
check("words: at most MAX_TERMS units; an unclosed quote is read as plain words", len(W(" ".join(f"w{i}" for i in range(20)))) == search.MAX_TERMS and W('"open phrase') == ['"open', "phrase"], W('"open phrase'))
check("long_enough: a query needs a unit of two characters", search.long_enough(W("ab")) and search.long_enough(W('"a b"')) and not search.long_enough(W("a")) and not search.long_enough(W("a b")) and not search.long_enough(W("")))
rx = search.word_rx(W('"approved redesign" quokka'))
check("word_rx: a substring anywhere, a phrase only as written, any case", [m.group(0) for m in rx.finditer("Approved Redesign QUOKKA quokkas approved-redesign approved  redesign")] == ["Approved Redesign", "QUOKKA", "quokka"],
      [m.group(0) for m in rx.finditer("Approved Redesign QUOKKA quokkas approved-redesign approved  redesign")])
FOUND = lambda q: sorted((x["kind"], x["key"]) for x in search.find(W(q)))
check("find: a word finds the longer word that holds it (redesign finds Redesigned), a longer query does not find the shorter text",
      ("item", "a1") in FOUND("redesign") and ("item", "a2") in FOUND("redesign") and ("item", "a3") in FOUND("redesign") and ("item", "a2") in FOUND("redesig") and ("item", "a2") not in FOUND("redesigned!"), FOUND("redesign")[:8])
check("find: a word finds the inside of a longer word too (no word boundary)", ("item", "a2") in FOUND("esigne") and ("item", "a1") not in FOUND("esigne"), FOUND("esigne"))
check("find: search.query still matches the start of a word (a prefix finds a2)", any(x["key"] == "a2" for x in search.query("redesign")["item"]) and any(x["key"] == "a1" for x in search.query("redesig")["item"]))
check("find: nothing for no word, and no FTS syntax is read from the query", FOUND("") == [] and FOUND('"*') == [] and FOUND("NEAR(quokka redesign)") == [] and FOUND("title:quokka") == [] and FOUND("quokka OR needle") == [], FOUND("quokka OR needle"))

# ---- 2. the page
COOKIE = server._ui_sign(json.dumps({"email": EMAIL, "exp": time.time() + 3600}))
LI = re.compile(r'<li class="irow srow"([^>]*)>(.*?)</li>', re.S)
def rows_of(t):
    """[(kind label, link address, title text, the li's attributes, the li's html)] of the list's rows, in order."""
    out = []
    for attrs, body in LI.findall(t):
        kind = re.search(r'<span class="ktag">(\w+)</span>', body).group(1)
        href = re.search(r'class="ir-link" href="([^"]*)"', body)
        title = re.search(r'<span class="hgoal">(.*?)</span>', body, re.S)
        out.append((kind, href.group(1) if href else "", re.sub(r"<[^>]+>", "", title.group(1)) if title else "", attrs, body))
    return out
items_of = lambda t: [h for k, h, *_ in rows_of(t) if k == "Item"]
summary = lambda t: re.sub(r"<[^>]+>", "", re.search(r'<div class="se-summary" role="status">(.*?)</div>', t, re.S).group(1))
def counts(t):
    """{box value: the number beside it} of the Kind and State boxes."""
    return {v: int(n) for v, n in re.findall(r'<input type="checkbox" name="(?:kind|state)" value="(\w+)"[^>]*> [A-Za-z]+ <small>\((\d+)\)</small>', t)}
ticked = lambda t: sorted(v for v, c in re.findall(r'<input type="checkbox" name="(?:kind|state)" value="(\w+)"( checked)?>', t) if c)
chip = lambda t: re.findall(r'<button type="submit" class="se-chip" name="w" value="(\w+)" aria-pressed="true">', t)

with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def get(path):
        c.cookies.clear(); c.cookies.set(server._UI_COOKIE, COOKIE)
        return c.get(path, follow_redirects=False)
    def page(q, extra="", full=True):
        """The results page for q; `full` asks for every row (n=200) so a check can look at all of a search, not its first 25."""
        r = get(f"/search?q={quote(q)}{extra}{'&n=200' if full and 'n=' not in extra else ''}")
        assert r.status_code == 200, (q, extra, r.status_code)
        return r.text

    # ---- 2a. matching over HTTP
    t = page("redesign", "&w=all")

    check("redesign (All): found in a subject, a description, a closed item's text and as the start of 'Redesigned'", sorted(items_of(t)) == ["/items/a1", "/items/a2", "/items/a3", "/items/a4", "/items/a5", "/items/a6"], items_of(t))
    check("redesig (a part of a word) finds the same items", sorted(items_of(page("redesig", "&w=all"))) == sorted(items_of(t)))
    check("a part from the middle of a word finds it too", items_of(page("quokk", "&w=all")) == ["/items/a1"] and items_of(page("esigned par", "&w=all")) == ["/items/a2"], items_of(page("esigned par", "&w=all")))
    check("a longer text than the entry's does not match (redesigned is in a2 only)", items_of(page("redesigned", "&w=all")) == ["/items/a2"], items_of(page("redesigned", "&w=all")))
    check("a case does not matter", sorted(items_of(page("REDESIGN", "&w=all"))) == sorted(items_of(t)))
    check('phrase: "approved redesign" finds the entry that has the two words together (a1), not the one that has them apart (a3)', items_of(page('"approved redesign"', "&w=all")) == ["/items/a1"], items_of(page('"approved redesign"', "&w=all")))
    check("phrase: a partial phrase is a substring too", items_of(page('"proved redes"', "&w=all")) == ["/items/a1"], items_of(page('"proved redes"', "&w=all")))
    check("...the same words without quotes are two units: both entries", sorted(items_of(page("approved redesign", "&w=all"))) == ["/items/a1", "/items/a3"], items_of(page("approved redesign", "&w=all")))
    check('phrase: the words in the other order are not the phrase', rows_of(page('"redesign approved"', "&w=all")) == [])
    check("phrase: words with something between them are not the phrase", rows_of(page('"approved flow"', "&w=all")) == [] and items_of(page("approved flow", "&w=all")) == ["/items/a1"], items_of(page("approved flow", "&w=all")))
    check("every word must be in the same entry: two words of two different items find nothing; two words of one find it", rows_of(page("quokka parser", "&w=all")) == [] and items_of(page("quokka flow", "&w=all")) == ["/items/a1"], items_of(page("quokka flow", "&w=all")))
    check("an id is a word: a1 finds item a1", items_of(page("a1", "&w=all"))[:1] == ["/items/a1"], items_of(page("a1", "&w=all")))
    check("Japanese: ボード finds the word that starts with it, 日本 finds 日本語, and two words of one entry find it", items_of(page("日本語", "&w=all")) == ["/items/a7"] and items_of(page("日本", "&w=all")) == ["/items/a7"]
          and items_of(page("ボード", "&w=all")) == ["/items/a7"] and items_of(page("ボード 検索", "&w=all")) == ["/items/a7"] and rows_of(page("ボード quokka", "&w=all")) == [], items_of(page("ボード", "&w=all")))

    # ---- 2b. the marks
    r1 = next(r for r in rows_of(t) if r[1] == "/items/a1")
    check("marks: the match is marked in the title (and only the match)", "<mark>Redesign</mark> the quokka page" in r1[4], r1[4][:400])
    tp = page('"approved redesign"', "&w=all")
    check("marks: a phrase is marked as one in the excerpt", "<mark>approved redesign</mark>" in tp, rows_of(tp)[0][4][-300:])
    r2 = next(r for r in rows_of(page("parser", "&w=all")) if r[1] == "/items/a2")
    check("marks: the typed text is marked inside a longer word, 'Redesign' in 'Redesigned', and 'parser' in the text", "<mark>parser</mark>" in r2[4] and "<mark>Redesign</mark>ed parser" in next(r for r in rows_of(page("redesign", "&w=all")) if r[1] == "/items/a2")[4], r2[4][:300])

    # ---- 2c. the window
    td = page("redesign")
    kinds7 = [(k, h) for k, h, *_ in rows_of(td)]
    check("default window: a search started from the box is the last 7 days, said in the summary and by the pressed chip", "last 7 days" in summary(td) and chip(td) == ["7d"], (summary(td), chip(td)))
    check("default window: the month-old item, its History, the month-old project page and session are out", ("Item", "/items/a5") not in kinds7 and ("Project", "/projects/beta") not in kinds7
          and not any(h.endswith("a5") for k, h in kinds7 if k == "History") and not any("old" in n for _k, _h, n, *_ in rows_of(td)), kinds7)
    check("default window: today's item, project page and session are in", ("Item", "/items/a1") in kinds7 and ("Project", "/projects/alpha") in kinds7 and any(k == "Session" for k, _h in kinds7), kinds7)
    ta = page("redesign", "&w=all")
    check("All: the month-old item, project page and session come in, the summary says all time", ("Item", "/items/a5") in [(k, h) for k, h, *_ in rows_of(ta)] and ("Project", "/projects/beta") in [(k, h) for k, h, *_ in rows_of(ta)]
          and any("home-redesign-old" in n for _k, _h, n, *_ in rows_of(ta)) and "all time" in summary(ta) and chip(ta) == ["all"], summary(ta))
    t24 = page("redesign", "&w=24h")
    check("24 h: the item changed 30 hours ago is out, the item of an hour ago is in", "/items/a4" not in items_of(t24) and "/items/a1" in items_of(t24) and "last 24 h" in summary(t24), items_of(t24))
    t3 = page("redesign", "&w=3d")
    check("3 days: the item of 30 hours ago is in, the month-old one is out", "/items/a4" in items_of(t3) and "/items/a5" not in items_of(t3) and "last 3 days" in summary(t3))
    t1 = page("redesign", "&w=1h")
    check("1 h: only what changed in the last hour (the item of 1 h is just outside)", "/items/a2" not in items_of(t1) and "/items/a3" not in items_of(t1) and "last 1 h" in summary(t1), items_of(t1))
    check("a chip wins over the form's hidden value", chip(page("redesign", "&when=24h&w=all")) == ["all"] and chip(page("redesign", "&when=24h")) == ["24h"] and chip(page("redesign", "&when=bogus")) == ["7d"])
    zone_hours = 4; zone = datetime.timezone(datetime.timedelta(hours=zone_hours))      # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
    pick = lambda t_: datetime.datetime.fromtimestamp(t_, zone).strftime("%Y-%m-%dT%H:%M")
    td_ = page("redesign", f"&when=dates&from={quote(pick(NOW - 40 * H))}&to={quote(pick(NOW - 10 * H))}")
    check("Dates: From and To are read in the board's zone; the item of 30 hours ago is in, the item of 1 hour ago is out", items_of(td_) == ["/items/a4"] and chip(td_) == ["dates"] and "<b>Dates</b>" in td_ and f'name="from" value="{pick(NOW - 40 * H)}"' in td_, (items_of(td_), summary(td_)))
    check("Dates: From alone is open-ended", "/items/a1" in items_of(page("redesign", f"&when=dates&from={quote(pick(NOW - 40 * H))}")))
    check("Dates: no From is said, with no search run; text that is no date is said", "Pick a From date" in summary(page("redesign", "&when=dates")) and rows_of(page("redesign", "&when=dates")) == []
          and "not one a search can use" in summary(page("redesign", "&when=dates&from=yesterday")))
    tfar = [page("redesign", "&when=dates&from=" + quote(v)) for v in ("0001-01-01T00:00", "0001-01-01T00:00+14:00", "9999-12-31T23:59", "9999-12-31T23:59-12:00")]
    check("Dates: a date too early or too late to show is held to the edge and the page still answers", all("<b>Dates</b>" in t_ and "matches for" in summary(t_) for t_ in tfar)
          and "from 1970-01-02" in summary(tfar[0]) and "/items/a1" in items_of(tfar[0]) and "/items/a1" not in items_of(tfar[2]), [summary(t_) for t_ in tfar])
    tto = page("redesign", f"&when=dates&from={quote(pick(NOW - 40 * H))}&to=" + quote("0001-01-01T00:00+14:00"))
    check("Dates: a To too early to show is held to the edge too", "matches" in summary(tto) or "No matches" in summary(tto), summary(tto))

    # ---- 2d. the filters and their counts
    c0 = counts(td)
    check("counts: Kind and State numbers are the 7 days' matches, each box with its own number", set(c0) == {"item", "history", "project", "session", "open", "closed"} and c0["project"] == 1 and c0["session"] == 1 and ticked(td) == ["closed", "history", "item", "open", "project", "session"], c0)
    n_rows = {k: sum(1 for kk, *_ in rows_of(td) if kk == k) for k in ("Item", "History", "Project", "Session")}
    check("counts: the rows are as many as the Kind boxes add up to, kind by kind", n_rows == {"Item": c0["item"], "History": c0["history"], "Project": c0["project"], "Session": c0["session"]} and sum(n_rows.values()) == len(rows_of(td)), (n_rows, c0))
    check("counts: the State boxes count the items and their History (open + closed = items + History)", c0["open"] + c0["closed"] == c0["item"] + c0["history"] and c0["closed"] >= 2, c0)
    check("summary: the match count is the rows' count, times are in the board's zone", summary(td).startswith(f"{len(rows_of(td))} matches for “redesign” · newest first · last 7 days · times in +{zone_hours:02d}"), summary(td))
    tk = page("redesign", "&f=1&kind=item&kind=project&state=open&state=closed")
    check("Kind: unticking History and Sessions leaves only items and projects; the unticked box still says what it holds", {k for k, *_ in rows_of(tk)} == {"Item", "Project"} and ticked(tk) == ["closed", "item", "open", "project"] and counts(tk)["history"] == c0["history"], (ticked(tk), counts(tk)))
    ts_ = page("redesign", "&f=1&kind=item&kind=history&kind=project&kind=session&state=closed")
    cs = counts(ts_)
    check("State: only Closed leaves the closed items and their History, and projects and sessions (they have no state)", {k for k, *_ in rows_of(ts_)} == {"Item", "History", "Project", "Session"} and all("a4" in h or k in ("Project", "Session") for k, h, *_ in rows_of(ts_)), [(k, h) for k, h, *_ in rows_of(ts_)])
    check("State: the Kind numbers follow the State boxes (the open items drop out of Items), the State numbers do not follow their own boxes", cs["item"] == 1 and cs["project"] == c0["project"] and cs["session"] == c0["session"] and cs["open"] == c0["open"] and cs["closed"] == c0["closed"], (cs, c0))
    tn = page("redesign", "&f=1&state=open&state=closed")
    check("every Kind box unticked: nothing listed, and the page says which boxes hold matches", rows_of(tn) == [] and "Unticked boxes hold more: Items (" in summary(tn) and ticked(tn) == ["closed", "open"], summary(tn))
    tz_ = page("ferret", "&w=1h")
    check("a match outside the window is said: ferret is on a page that changed a month ago", "No matches." in summary(tz_) and "1 match is outside this window: choose All" in summary(tz_), summary(tz_))
    check("short and empty queries: the note says how many characters, no rows, no error", "Type at least 2 characters" in page("a") and "Type at least 2 characters" in get("/search").text and rows_of(page("a")) == [])

    nine = " ".join(f"word{i}" for i in range(9)); eight = " ".join(f"word{i}" for i in range(8))
    t9 = page(nine)
    check("more than 8 units: the page says the limit instead of searching, as the fleet tool does", summary(t9) == "A search is at most 8 words; put a phrase in quotes to keep it as one." and rows_of(t9) == [], summary(t9))
    t8 = page(eight + " extra"); tq = page(" ".join(f"w{i}x" for i in range(7)) + ' "a b c d e f"')
    check("8 units are searched; a quoted phrase counts as one unit", "at most 8 words" not in summary(page(eight)) and "at most 8 words" not in summary(tq) and "at most 8 words" in summary(t8), (summary(page(eight)), summary(tq), summary(t8)))

    # ---- 2e. Show 25 more
    tn1 = page("needle", full=False)
    rows1 = rows_of(tn1)
    more1 = re.search(r'<a class="se-more" id="se-more" href="([^"]*)">([^<]*)</a>', tn1)
    check("Show more: 25 rows first, newest first, and a link that says how many it adds", len(rows1) == 25 and more1 and more1.group(2) == "Show 25 more" and f"{BULK} matches" in summary(tn1)
          and [h for _k, h, *_ in rows1] == [f"/items/a{10 + k}" for k in range(25)], (len(rows1), more1 and more1.group(2), summary(tn1)))
    check("Show more: the link keeps the search (query, window, boxes) and asks for 50, landing on the first new row", more1 and "n=50" in more1.group(1) and "q=needle" in more1.group(1) and "when=7d" in more1.group(1) and more1.group(1).endswith("#se-new")
          and more1.group(1).count("kind=") == 4 and more1.group(1).count("state=") == 2, more1 and more1.group(1))
    check("Show more: the first page has no landing row", "se-new" not in "".join(a for _k, _h, _t, a, _b in rows1))
    r_more = get(more1.group(1).replace("&amp;", "&").split("#")[0])
    rows2 = rows_of(r_more.text); more2 = re.search(r'<a class="se-more" id="se-more" href="([^"]*)">([^<]*)</a>', r_more.text)
    check("Show more: the second page has 50 rows, the same first 25, and the 26th row is the landing row", len(rows2) == 50 and [r[1] for r in rows2[:25]] == [r[1] for r in rows1] and 'id="se-new"' in rows2[25][3]
          and sum('id="se-new"' in r[3] for r in rows2) == 1 and more2 and more2.group(2) == "Show 10 more", (len(rows2), more2 and more2.group(2)))
    r_last = get(more2.group(1).replace("&amp;", "&").split("#")[0]); rows3 = rows_of(r_last.text)
    check("Show more: the last page has all 60 rows and no link", len(rows3) == BULK and 'class="se-more"' not in r_last.text and f"{BULK} matches" in summary(r_last.text), len(rows3))
    check("Show more: n is clamped (junk or too small is the first page)", len(rows_of(page("needle", "&n=junk", full=False))) == 25 and len(rows_of(page("needle", "&n=3", full=False))) == 25 and len(rows_of(page("needle", "&n=-40", full=False))) == 25)
    cap0 = s2.CAP; s2.CAP = 40
    try:
        tc = page("needle", "&n=75")
        check("the cap: the list is cut there and the summary says so (a number of matches over it is still told)", len(rows_of(tc)) == 40 and f"{BULK} matches" in summary(tc) and "cut at 40" in summary(tc) and 'class="se-more"' not in tc, (len(rows_of(tc)), summary(tc)))
        tc2 = page("needle", full=False); mc = re.search(r'<a class="se-more" id="se-more" href="[^"]*">([^<]*)</a>', tc2)
        check("the cap: Show more offers only what is left under it", len(rows_of(tc2)) == 25 and mc and mc.group(1) == "Show 15 more", mc and mc.group(1))
    finally:
        s2.CAP = cap0

    # ---- 2f. the rows
    pj = next(r for r in rows_of(ta) if r[0] == "Project" and r[1] == "/projects/alpha")
    check("project row: a link at the root with the page key, when it changed, the gbrain page, the excerpt marked", 'href="/projects/alpha"' in pj[4] and "page changed" in pj[4] and 'href="https://example.invalid/alpha"' in pj[4] and "<mark>redesign</mark> of the narwhal" in pj[4], pj[4][:500])
    sl = next(r for r in rows_of(ta) if r[2] == "home-redesign-main")
    sg = next(r for r in rows_of(ta) if r[2] == "home-redesign-old")
    check("session row: a live pane links to sala by name; a session with no live pane is plain text and says so", f'href="{SALA.format(name="home-redesign-main")}"' in sl[4] and "opens in sala" in sl[4] and "<a " not in sg[4] and "no live pane" in sg[4], (sl[4][:300], sg[4][:300]))
    hist = next(r for r in rows_of(ta) if r[0] == "History")
    check("history row: the item's link, its state tag, the kind of change and the entry's text", hist[1].startswith("/items/a") and 'class="tag t-' in hist[4] and "History · created" in hist[4], hist[4][:400])
    it4 = next(r for r in rows_of(ta) if r[1] == "/items/a4" and r[0] == "Item")
    check("item row: the closed item carries the Done tag", '<span class="tag t-done">Done</span>' in it4[4], it4[4][:300])
    ages = [int(m) for m in re.findall(r'data-ts="(\d+)"', "".join(r[4] for r in rows_of(ta)))]
    check("the list is newest first (the rows' times never go up)", ages == sorted(ages, reverse=True) and len(ages) == len(rows_of(ta)), ages[:6])
    first_title = [r[2] for r in rows_of(page("needle"))][:2]

    # ---- 2g. the form and the page
    check("the form: a plain GET to /search at the root, the header's box is the other form",
          t.count('action="/search"') == 2 and 'method="get"' in t and 'id="se-form"' in t, re.findall(r'<form[^>]*>', t))
    form = re.search(r'<form class="se-controls".*?</form>', t, re.S).group(0)
    hbox = re.search(r'<header class="top">.*?<form class="sbox"([^>]*)>', t, re.S).group(1)
    check("new tab: the Search page's own header box and its filter form search in place (no target on either), so tabs do not pile up", "target=" not in hbox and "rel=" not in hbox and "target=" not in re.match(r"<form[^>]*>", form).group(0), (hbox, form[:120]))
    check("new tab: the box another page's header draws opens its results in a new tab (target=_blank, rel=noopener), unless asked to search in place; the query is kept either way",
          all(a in s2.box("x") for a in (' target="_blank" rel="noopener"', 'action="/search"', 'method="get"', 'value="x"')) and "target=" not in s2.box("x", in_place=True) and 'value="x"' in s2.box("x", in_place=True))
    check("the form: the first submit button is the invisible one with no name, so Enter in the box keeps the filters; every chip is a named submit button", re.search(r"<button", form).group(0) and form.index('class="sr"') < form.index('class="se-chip"')
          and re.search(r'<button type="submit" class="sr" tabindex="-1" aria-hidden="true">Search</button>', form) and len(re.findall(r'class="se-chip" name="w"', form)) == 7 and '<input type="hidden" name="f" value="1">' in form, form[:400])
    check("the form: the box holds the query; a change to a box or date submits it (one script, none for the rows)", 'name="q" value="redesign"' in form and "requestSubmit" in t and "<noscript>" in form and t.count("se-form") >= 2)
    check("the page: titled with the query, the board's header, the h1, the side panel", "<title>redesign · Search · " in t and '<header class="top">' in t and "<h1>Search</h1>" in t and '<aside id="panel"' in t)
    xs = page("alert", "&w=all")
    check("escaping: an item's markup is text (script tag and img in the subject and description)", "<script>alert(1)</script>" not in xs and "<img src=x" not in xs and "&lt;script&gt;" in xs and all("alert(" not in s_ for s_ in re.findall(r"<script[^>]*>(.*?)</script>", xs, re.S)), xs[xs.find("se-hits"):][:500])
    evil = '"><script>alert(9)</script><b>'
    xe = page(evil, "&w=all")
    check("escaping: the query is escaped in the box, the title and the summary", "<script>alert(9)</script>" not in xe and "&quot;&gt;&lt;script&gt;" in xe and "<b>" not in xe.split("<main")[1].split("</form>")[1][:300], xe[xe.find("<title>"):][:160])
    xd = page("redesign", "&when=dates&from=" + quote('"><img src=x>'))
    check("escaping: a date that is text is said, never drawn as markup", "<img src=x>" not in xd, xd[xd.find('name="from"'):][:120])
    r_anon_ok = get("/search?q=redesign&n=50&w=all&f=1&kind=item&state=open")
    check("any mix of parameters answers 200, as HTML, never cached", r_anon_ok.status_code == 200 and r_anon_ok.headers["content-type"].startswith("text/html") and r_anon_ok.headers.get("cache-control") == "no-store")

    # ---- 3. an index built without FTS5 finds the same
    ref = {q: sorted((x["kind"], x["key"], x["sub"]) for x in search.find(W(q))) for q in ("redesign", '"approved redesign"', "redesig", "quokka flow", "needle", "日本語", "ferret", "home-redesign-old")}
    search.reset(); (T / "state/search/index.db").unlink(); search._FTS = False
    try:
        search.sync(fresh())
        got = {q: sorted((x["kind"], x["key"], x["sub"]) for x in search.find(W(q))) for q in ref}
        check("fallback: the same rows for a word, a phrase, part of a word, two words, Japanese, a project page and a session name", got == ref, {q: (len(got[q]), len(ref[q])) for q in ref if got[q] != ref[q]})
        tf = page("redesign", "&w=all")
        check("fallback: the page lists the same items, marks the match in the title, and marks the excerpt", sorted(items_of(tf)) == sorted(items_of(ta)) and "<mark>Redesign</mark> the quokka page" in tf
              and "<mark>approved redesign</mark>" in page('"approved redesign"', "&w=all"), items_of(tf))
    finally:
        search.reset(); search._FTS = True; (T / "state/search/index.db").unlink(missing_ok=True)
        search.sync(fresh())

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
