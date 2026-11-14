"""Scenario test for how a wait on a LIST of waits reads on the board (the home page's Waiting row, the item page's wait block, the `model:` line of get) — fixture data, no live store, no network, no server socket.

The list itself (waits/wait_list.py) and its ending are tests/wait_list_scenario.py's. Nothing a caller passes writes a list yet, so the fixtures store the metadata directly. Covered:

  * the Waiting row of a list item: one line per wait with its kind and what it waits on, a box ticked (with the time) once the line has arrived, "all of N" / "any of N", how many have arrived, and the one backstop
    day ("back anyway <day>"), the end slot on the right (until <day>), the who line (who picks it up, and who watches: one watcher per kind of line, an arrived line needs none)
  * the item page's wait block: the same lines with a second line each (what watches it, or in what words and when it arrived, an item line open or closed), the mode in words, the Backstop row, no Watched by row
    and no Chases row (a list is never chased), the Picks it up row
  * every kind of line: time, anchor, item, relay, event; free text (an event, an anchor, the words of an arrival) is escaped in the row and on the page
  * a single wait reads exactly as it did (a row with no list class, the old words, its Watched by and Chases rows), and a stored list that does not hold reads as the date alone
  * every user-visible string comes from the string table: a locale that marks every key marks every word of a list row and of the page block
  * the `model:` line of get: the mode, how many arrived, each line ticked [x] or open [ ], with the time (and the zone's name) and the words of an arrival and the backstop
  * a stored arrival time no date can show (inf, "inf", 1e20, 1e300, year 10000) reads as no arrival on the home page, the item page and get, and no display of a time can raise (a model handed such a time anyway keeps the
    arrival words and drops the time); an item id in a line is clipped; a line that arrived with no recorded words reads "arrived <time>", never "arrived · arrived <time>"

    tests/run-suite wait_list_display        → exit 0 / 1"""
import dataclasses, datetime, html, json, os, re, sys, pathlib, time, logging, zoneinfo
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="waitlistdisplay-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "brain/projects", "locales", "state", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
ZONE = datetime.timezone(datetime.timedelta(hours=4))      # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
NOW = datetime.datetime(2026, 11, 13, 10, 0, tzinfo=ZONE)
now0 = NOW.timestamp(); H, DAY = 3600.0, 86400.0
day = lambda n: (NOW + datetime.timedelta(days=n)).strftime("%Y-%m-%d")
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "seen": now0} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back"}, "back_agents": {"team-back": "the back"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
(T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 56 * DAY, "seen": {}, "reported": []}))
DESC = "- A thing\n- It lives here\n- Done when done"
BACK = "team-back"
def item(i, status="open", subject=None, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": DESC, "status": status, "updated": now0 - 2 * H, "state_updated": now0 - 2 * H, "confirmed": now0 - 2 * H,
                                                     "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing", **meta}}))
Tm = lambda d: {"kind": "time", "until": d}
An = lambda url, ev="PR merged": {"kind": "anchor", "anchor": url, "event": ev}
It = lambda g: {"kind": "item", "after": g}
Re = lambda ev="the lease": {"kind": "relay", "event": ev}
Ev = lambda ev: {"kind": "event", "event": ev}
def arr(line, at, what): return {**line, "arrived": {"at": at, "what": what}}
def lst(i, waits, mode="all", until=None, **extra):
    item(i, wait_kind="list", hold=True, wait_mode=mode, until=until or day(4), waits=waits, post_wake_mover=BACK, needs=[], subject=extra.pop("subject", f"[home] list {i}"), watch={"set_at": now0 - 3600}, **extra)
AURL, AURL2 = "https://github.com/o/r/pull/5", "https://github.com/o/r/pull/6"
EVIL = "<script>alert(1)</script> & <b>bold</b>"
GOT = now0 - 90 * 60          # the time of an arrival: 08:30, the same day
# the items
item(300, status="completed", subject="[home] a blocker that has closed", outcome="done", reason="finished", needs=[])
item(301, subject="[home] a blocker that is open", mover="team-back", needs=["team-back"])
lst(310, [Re("SK's final ticket and its feedback"), Re("the signing order the team agrees")], mode="all", until=day(4), subject="[home] two pieces of news, both needed")
lst(311, [An(AURL, "GitHub's confirmation posted"), An(AURL2, "the head ref no longer resolves")], mode="any", until=day(2) + "T10:00", subject="[home] two signs, one needed")
lst(312, [arr(Tm(day(3)), GOT, "its date came"), arr(It("a300"), GOT + 600, "the other item closed (done)"), It("a301"), An(AURL, "PR merged"), Ev("recycle testbox"), Re("the lease")], mode="all", until=day(6), subject="[home] six lines of every kind")
lst(313, [Re(EVIL), arr(An('https://x.example/a"><img src=x onerror=alert(1)>', EVIL), GOT, EVIL), Ev(EVIL)], mode="all", subject="[home] free text")
lst(314, [Re("one"), An("github:o/r#7", "a review")], mode="all", until=day(4), subject="[home] a list with an anchor that is no address")
lst(315, [It("a300"), It("a301")], mode="all", subject="[home] two items, one already closed (its arrival not recorded yet)")
item(320, subject="[home] a single time wait", wait_kind="time", hold=True, wake=day(5), needs=[], post_wake_mover=BACK, wait_basis={"text": "the vendor ships on that day", "by": "home-front"})
item(321, subject="[home] a single relay wait", wait_kind="relay", hold=True, ask_by=day(5), wait_event="the lease", party="the landlord", needs=[], post_wake_mover=BACK)
item(322, subject="[home] a single item wait", wait_kind="item", hold=True, after=["a301"], wake=day(7), needs=[], post_wake_mover=BACK)
item(323, subject="[home] a single anchor wait", wait_kind="anchor", hold=True, wait_anchor=AURL, wait_event="PR merged", wake=day(7), needs=[], post_wake_mover=BACK)
lst(330, [Tm(day(3))], mode="all", until=day(4), subject="[home] a list that does not hold")
HOSTILE = {340: float("inf"), 341: "inf", 342: 1e20, 343: 1e300, 344: 253402300800, 345: 10 ** 400}      # a stored arrival time no date can show (the shape reads each as no arrival)
for i_, at_ in HOSTILE.items(): lst(i_, [arr(Re("the lease"), at_, "the lease arrived"), It("a301")], mode="all", subject=f"[home] hostile arrival time {i_}")
lst(346, [arr(Re("the lease"), GOT, "the lease arrived"), It("a301")], mode="all", subject="[home] a real arrival time")
LONG_ID = "a" + "9" * 1_000_000
lst(347, [Re("one"), It(LONG_ID)], mode="all", subject="[home] a line that names an item with a very long id")
lst(348, [arr(Re("the lease"), GOT, ""), arr(An(AURL, "PR merged"), GOT + 60, ""), It("a301")], mode="all", subject="[home] arrivals with no words recorded")
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1200]}" if got is not None else ""))
logging.disable(logging.INFO)
from stackshot.core import config as _cfg
from stackshot.web.ui import render; from stackshot.web import server, i18n; from stackshot.model import model
from stackshot.service import item_read as _item_read
from stackshot.web import publish as _web_publish
_web_publish._publish = lambda: None
b = render.Board(str(T / "store"), now=NOW)
plain = lambda h: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()
def row(g): r = next(x for x in b.rows if x["gid"] == g); return r, b.mod_of(r)
def wait_cell(g): r, m = row(g); return b.home_wait(r, m)
def who_line(g): r, m = row(g); return plain(b.wait_who(r, m))
def end_slot(g): r, m = row(g); return plain(b.wait_end_slot(m, 0))
def page_wait(g): h = b.item_html(g); i = h.find('<section class="iwait">'); return h[i:h.find("</section>", i)] if i >= 0 else ""
def lines_of(h): return re.findall(r'<span class="wll(?: wdone)?">(.*?)</span></span></span>', h, re.S)
def box_on(h): return [c == "wbox on" for c in re.findall(r'<span class="(wbox(?: on)?)"', h)]
W = lambda d: b.day_words(d)
W_ = lambda ts: b.when(ts)

# ================================================================ the Waiting row: all of 2, nothing arrived
c310 = wait_cell("a310"); p310 = plain(c310)
check("row (all, nothing arrived): the head says the mode, that nothing has arrived and the backstop day; each wait is one line with its kind and its words, none ticked",
      '<span class="wl">' in c310 and plain(re.search(r'class="wmode">(.*?)</span>', c310).group(1)) == "all of 2" and f"0 arrived · back anyway {W(day(4))}" in p310 and box_on(c310) == [False, False]
      and p310.count("news") == 2 and "SK's final ticket and its feedback" in p310 and "the signing order the team agrees" in p310 and "arrived " not in p310.replace("0 arrived", ""), p310)
check("row: …the lines come in the stored order", p310.index("SK's final ticket") < p310.index("the signing order"), p310)
check("row: …the end slot on the right is the backstop day, as an item or anchor wait's is", end_slot("a310") == f"until {W(day(4))}", end_slot("a310"))
check("row: …the who line: who picks it up and who watches (relay lines: the scheduler)", who_line("a310") == "team-back picks it up · watched by the scheduler", who_line("a310"))
check("row: …no `ask by`, no chases (a list has only its backstop day and is never chased)", "ask by" not in p310 and "chased" not in p310, p310)
# any of 2, a date with a time, anchors
c311 = wait_cell("a311"); p311 = plain(c311)
check("row (any): \"any of 2\", the backstop day with its time, two anchor lines each with the anchor as a link", plain(re.search(r'class="wmode">(.*?)</span>', c311).group(1)) == "any of 2" and f"0 arrived · back anyway {W(day(2) + 'T10:00')}" in p311
      and "10:00" in p311 and c311.count('<a href="https://github.com/o/r/pull/') == 2 and p311.count("anchor") == 2 and "GitHub's confirmation posted" in p311, p311)
check("row: …anchor lines are watched by the anchor module; the end slot carries the time", who_line("a311") == "team-back picks it up · watched by the anchor module" and "10:00" in end_slot("a311"), (who_line("a311"), end_slot("a311")))
# six lines of every kind, two arrived
c312 = wait_cell("a312"); p312 = plain(c312)
check("row (all of 6, two arrived): the head counts them; the arrived lines are ticked and carry the time of their arrival, the other four are open", f"2 arrived · back anyway {W(day(6))}" in p312 and "all of 6" in p312
      and box_on(c312) == [True, True, False, False, False, False] and p312.count("arrived " + W_(GOT)) == 1 and p312.count("arrived ") == 3, (p312, box_on(c312)))
check("row: …each kind says its own words: the date, the close of an item (a link to it), an anchor (its event and a link), a fleet event, news",
      f"the date {W(day(3))}" in p312 and "the close of a300" in p312 and 'href="/items/a300"' in c312 and "PR merged ( r PR #5 )" in p312 and 'href="https://github.com/o/r/pull/5"' in c312 and "recycle" in p312 and "the lease" in p312
      and [x for x in re.findall(r'class="wkind">(.*?)</span>', c312)] == ["date", "item", "item", "anchor", "event", "news"], (p312, re.findall(r'class="wkind">(.*?)</span>', c312)))
check("row: …who watches: the arrived lines need no watcher, the open ones each have theirs, once (the server for an item and an event, the anchor module, the scheduler)", who_line("a312") == "team-back picks it up · watched by the server, the anchor module, the scheduler", who_line("a312"))
check("row: a list with an anchor that is no address still has its watcher (the anchor module)", who_line("a314") == "team-back picks it up · watched by the scheduler, the anchor module", who_line("a314"))

# ================================================================ the item page
pg310, pg311, pg312 = page_wait("a310"), page_wait("a311"), page_wait("a312")
p_310 = plain(pg310)
check("page (all, nothing arrived): Waits on holds the list: the mode, how many arrived and how it ends, one line per wait with its kind", "all of 2" in p_310 and "0 arrived · it comes back when the last one does" in p_310 and box_on(pg310) == [False, False] and p_310.count("news only") == 2, p_310)
check("page: …Backstop is its own row (the day, and that it is back at the latest whatever has arrived); Picks it up follows; there is no Watched by row and no Chases row", re.findall(r"<dt>(.*?)</dt>", pg310) == ["Waits on", "Backstop", "Picks it up"]
      and f"{b.wait_day(day(4))} · back at the latest, whatever has arrived" in p_310, re.findall(r"<dt>(.*?)</dt>", pg310))
check("page: …each open line says what watches it: news only <owner> relays, watched by the scheduler", p_310.count("news only") == 2 and p_310.count("watched by the scheduler") == 2 and "Chases" not in p_310 and "Watched by" not in p_310, p_310)
p_311 = plain(pg311)
check("page (any): \"any of 2\" and \"the first to arrive brings it back\"; each anchor line shows its anchor in full as a link, watched by the anchor module", "any of 2" in p_311 and "the first to arrive brings it back" in p_311 and "arrived ·" not in p_311
      and pg311.count('<a href="https://github.com/o/r/pull/') == 2 and p_311.count("watched by the anchor module") == 2 and "https://github.com/o/r/pull/5" in p_311 and "https://github.com/o/r/pull/6" in p_311, (pg311.count('<a href="https://github.com/o/r/pull/'), p_311.count("watched by the anchor module"), p_311))
p_312 = plain(pg312)
check("page (all of 6, two arrived): the arrived lines are ticked with the words of their arrival and the time; the open ones say what watches them", "2 arrived · it comes back when the last one does" in p_312 and box_on(pg312) == [True, True, False, False, False, False]
      and f"its date came · arrived {W_(GOT)}" in p_312 and f"the other item closed (done) · arrived {W_(GOT + 600)}" in p_312, p_312)
check("page: …an item line says whether the item is open or closed, a fleet event is watched by the server, an anchor line by the anchor module", "the close of a301 (open) · watched by the server" in p_312 and "watched by the server" in p_312 and "watched by the anchor module" in p_312 and "news only" in p_312, p_312)
check("page: …the sidebar's wait group reads Backstop with the day (the one date of the item)", re.search(r"<dt>Backstop</dt><dd>" + re.escape(b.wait_day(day(6))) + "</dd>", b.item_html("a312")) is not None, None)

p_315 = plain(page_wait("a315"))
check("page: an item line says whether its item is open or closed (an item that closed before the clock's pass marked the line is closed, the other open)", "the close of a300 (closed) · watched by the server" in p_315 and "the close of a301 (open) · watched by the server" in p_315, p_315)

# ================================================================ free text is escaped
c313 = wait_cell("a313"); pg313 = page_wait("a313"); full = c313 + pg313 + b.item_html("a313")
check("escape: the event of a line, the anchor of a line and the words of an arrival are free text: none of them reaches the row or the page as markup", "<script>alert(1)" not in full and "<b>bold</b>" not in full and "<img src=x" not in full and "onerror=alert(1)>" not in full, re.findall(r"<script>alert|<b>bold|<img src=x[^>]*>", full))
check("escape: …they are there as text, once escaped (the row and the page), and the anchor's quote and angle bracket stay inside its href", "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;" in c313 and "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;" in pg313
      and 'href="https://x.example/a&quot;&gt;&lt;img src=x onerror=alert(1)&gt;"' in c313 and 'href="https://x.example/a&quot;&gt;&lt;img src=x onerror=alert(1)&gt;"' in pg313, c313[:900])
c314, pg314 = wait_cell("a314"), page_wait("a314")
check("escape: …an anchor that is not a web address is text, not a link (row and page)", "github:o/r#7" in plain(c314) and 'href="github:' not in c314 + pg314 and "github:o/r#7" in plain(pg314), plain(c314))

# ================================================================ a single wait reads as it did; a list that does not hold is the date alone
S320, S321, S322, S323 = (plain(wait_cell(g)) for g in ("a320", "a321", "a322", "a323"))
check("single: a time wait reads as it did (until the day), no list class", S320 == f"Until {W(day(5))}" and 'class="wl"' not in wait_cell("a320"), S320)
check("single: …a relay wait (the party's news, ask by the day)", S321.startswith("On ") and f"ask by {W(day(5))}" in S321 and "the lease" in S321 and 'class="wl"' not in wait_cell("a321"), S321)
check("single: …an item wait (after the item, back anyway the backstop)", S322 == f"After a301 · back anyway {W(day(7))}", S322)
check("single: …an anchor wait (on the anchor, its event, the backstop)", S323.startswith("On ") and "PR merged" in S323 and f"backstop {W(day(7))}" in S323, S323)
check("single: …their who lines keep the watcher of their kind (scheduler, scheduler, server, anchor module)", [who_line(g) for g in ("a320", "a321", "a322", "a323")]
      == ["team-back picks it up · watched by the scheduler", "team-back picks it up · watched by the scheduler", "team-back picks it up · watched by the server", "team-back picks it up · watched by the anchor module"], [who_line(g) for g in ("a320", "a321", "a322", "a323")])
check("single: …the item page keeps its Watched by row, its Until or Ask by row and (relay, anchor) its Chases row, and no list block", all('class="wl"' not in page_wait(g) for g in ("a320", "a321", "a322", "a323"))
      and re.findall(r"<dt>(.*?)</dt>", page_wait("a321")) == ["Waits on", "Watched by", "Ask by", "Picks it up", "Chases"] and "Watched by" in page_wait("a322") and "Chases" in page_wait("a323"), re.findall(r"<dt>(.*?)</dt>", page_wait("a321")))
c330 = wait_cell("a330")
check("malformed: a stored list that does not hold (one line) is read as the date alone, everywhere: no list class on the row or the page", 'class="wl"' not in c330 and 'class="wl"' not in page_wait("a330") and "list" not in plain(c330).lower(), plain(c330))

# ================================================================ the string table
LOC = T / "locales"
MARK = lambda v: f"[x:{v}]"
DATE_AGE = {"date.full": "D<{wd}/{month}/{day}/{hm}>", "date.nohm": "D<{wd}/{month}/{day}>", "date.day": "{n}{ord}", "date.ord.1": "o1", "date.ord.2": "o2", "date.ord.3": "o3", "date.ord.n": "on",
            "age.now": "A<now>", "age.min": "A<{n}min>", "age.hour": "A<{n}hr>", "age.day": "A<{n}day>"}
DATE_AGE.update({f"date.wd.{i}": f"w{i}" for i in range(7)}); DATE_AGE.update({f"date.mon.{i}": f"m{i}" for i in range(1, 13)})
KEYS = sorted(k for k in i18n.EN if k.startswith("wait.list.") or k in ("wait.what.list", "wait.label.backstop", "home.watched_by", "wait.waits_on", "wait.picks_up", "wait.end.backstop") or k.startswith("home.watcher."))
check("strings: every key of a list's display is in the string table (English), as a plain template", len([k for k in KEYS if k.startswith("wait.list.")]) >= 18 and all(i18n.fields_of(i18n.EN[k]) is not None for k in KEYS), KEYS)
(LOC / "ko.json").write_text(json.dumps({**{k: MARK(v) for k, v in i18n.EN.items()}, **DATE_AGE}), encoding="utf-8")
_cfg.CFG.setdefault("ui", {})["locale_dir"] = str(LOC); i18n._WARNED.clear(); i18n._LOADED.clear()
with i18n.use("ko"):
    bx = render.Board(str(T / "store"), now=NOW); rx, mx = next(x for x in bx.rows if x["gid"] == "a312"), None
    mx = bx.mod_of(rx); cx = bx.home_wait(rx, mx); wx = bx.wait_who(rx, mx); gx = bx.item_html("a312"); gi = gx.find('<section class="iwait">'); px = gx[gi:gx.find("</section>", gi)]
def english_left(h):
    """The English words of a list's display that a marked locale must have replaced: text outside the marks, bar the fixtures' own words."""
    t = plain(h)
    while True:                                      # a mark may hold another (a template that carries a marked word): the innermost goes first
        t2 = re.sub(r"\[x:[^\[\]]*\]", " ", t)
        if t2 == t: break
        t = t2
    for fx in ("PR merged", "the next recycle of testbox", "recycle testbox", "the lease", "its date came", "the other item closed (done)", "github.com/o/r/pull/5", "https://github.com/o/r/pull/5", "r PR #5", "list 312", "#300", "#301", "a300", "a301", "team-back", "testbox"):
        t = t.replace(fx, " ")      # the fixtures' own words (an anchor's short label and a fleet event's words are the board's own helpers, not this display's)
    return re.sub(r"[\s·()\d:/.\-–,;✓\[\]]+", " ", re.sub(r"D<[^>]*>|A<[^>]*>|o\d|on\b|w\d|m\d+", " ", t)).strip()
check("strings: every word of a list row comes from the string table (a locale that marks each key marks the head, each kind, the arrival, the watchers)", cx.count("[x:") >= 10 and not english_left(cx), english_left(cx))
check("strings: …and of the item page's block (the mode, the notes, the sub lines, the Backstop row, its words)", px.count("[x:") >= 12 and not english_left(px), english_left(px))
check("strings: …the who line carries the watchers through the table too", "[x:" in wx and not english_left(wx), plain(wx))
_cfg.CFG["ui"].pop("locale_dir", None); i18n._WARNED.clear(); i18n._LOADED.clear()

# ================================================================ the `model:` line of get
def get_line(g): return [l for l in server._model_lines({**json.loads((T / f"store/a/{g[1:]}.json").read_text()), "gid": g}) if l.startswith("model:")][0]
ZLAB = zoneinfo.ZoneInfo("Asia/Dubai").tzname(NOW)      # the zone's own label, as the refusals that give a time name it (the instance zone pinned above)
g312 = get_line("a312")
check("get: the model line says the mode, how many have arrived, each line ticked [x] or open [ ] (an arrival with its words and its time), the backstop and the mover",
      g312.startswith("model: waiting on several things (all of 6, 2 arrived: [x] the date " + day(3) + " (its date came, " + day(0) + " 08:30 " + ZLAB + "); [x] the close of ") and "[ ] the close of" in g312 and "[ ] a notice at " + AURL + " (PR merged)" in g312
      and "[ ] a fleet event (recycle testbox)" in g312 and "[ ] news of the lease; until " + day(6) + ") · mover team-back" in g312, g312)
check("get: …nothing arrived: every line open, 0 arrived", get_line("a310") == f"model: waiting on several things (all of 2, 0 arrived: [ ] news of SK's final ticket and its feedback; [ ] news of the signing order the team agrees; until {day(4)}) · mover team-back", get_line("a310"))
check("get: …a single wait's line is what it was", get_line("a320") == f"model: waiting on a time (wake {day(5)}) · mover team-back", get_line("a320"))
check("get: …the model's words without a time formatter name no time (the brief and other callers)", "(its date came)" in model.words(next(m_ for m_ in [_item_read._model_of({**json.loads((T / "store/a/312.json").read_text()), "gid": "a312"})]), derived=False), None)

# ================================================================ a stored arrival time no date can show; an arrival with no words
check("zone: the arrival time of get's model line names the zone, the way the refusals that give a time do (the label is the instance zone's, and not empty)", bool(ZLAB) and ZLAB == _cfg.tz_abbr(NOW) and f"08:30 {ZLAB})" in g312, (ZLAB, g312))
home_html, why_home = None, ""
try: home_html = b.html()
except Exception as ex_: why_home = f"{ex_.__class__.__name__}: {ex_}"
check("hostile: a list whose stored arrival time no date can show (inf, \"inf\", 1e20, 1e300, year 10000, a huge integer) does not take the home page down: every one of them is drawn", home_html is not None
      and all(f"hostile arrival time {i_}" in home_html for i_ in HOSTILE) and "a real arrival time" in home_html, why_home)
for i_, at_ in HOSTILE.items():
    g_ = f"a{i_}"; tag = f"hostile arrival time ({at_!r:.12})"
    try: c_, p_ = wait_cell(g_), page_wait(g_); why_ = ""
    except Exception as ex_: c_ = p_ = ""; why_ = f"{ex_.__class__.__name__}: {ex_}"
    check(f"{tag}: the home row and the item page draw it, and it reads as not arrived (open, no time, no words), 0 arrived", bool(c_) and bool(p_) and box_on(c_) == [False, False] and box_on(p_) == [False, False]
          and "0 arrived" in plain(c_) and "the lease arrived" not in plain(c_ + p_) and "arrived · arrived" not in plain(p_), why_ or plain(c_))
    gl = get_line(g_)
    check(f"{tag}: get keeps its model line, with the line open and no time", gl == f"model: waiting on several things (all of 2, 0 arrived: [ ] news of the lease; [ ] the close of a301; until {day(4)}) · mover team-back", gl)
c346, p346, g346 = wait_cell("a346"), plain(page_wait("a346")), get_line("a346")
check("hostile: …a real arrival time on the same shape is drawn: ticked, with its time on the row, its words and time on the page, its words, time and zone in get", box_on(c346) == [True, False] and f"arrived {W_(GOT)}" in plain(c346)
      and f"the lease arrived · arrived {W_(GOT)}" in p346 and f"[x] news of the lease (the lease arrived, {day(0)} 08:30 {ZLAB})" in g346, (plain(c346), p346, g346))
# a model handed a time no date can show anyway (the shape keeps it out; the three places that say a time never raise on one)
r312, m312 = row("a312")      # its first two lines have arrived (the date line and the item line)
NOT_A_DATE = (float("inf"), 1e20, 1e300, 253402300800.0)
for at_ in NOT_A_DATE:
    bad = dataclasses.replace(m312, waits=tuple(dataclasses.replace(ln, arrived_at=at_) if ln.arrived else ln for ln in m312.waits))
    try: hr_, hp_ = b.wait_list_html(r312, bad, page=False), b.wait_list_html(r312, bad, page=True); why_ = ""
    except Exception as ex_: hr_ = hp_ = ""; why_ = f"{ex_.__class__.__name__}: {ex_}"
    try: wd_ = model.words(bad, when=server._arrival_when); why_w = ""
    except Exception as ex_: wd_ = ""; why_w = f"{ex_.__class__.__name__}: {ex_}"
    check(f"hostile model ({at_!r}): the row and the page of a model handed it draw, ticked and keeping the arrival words with no time; get's words keep the words with no empty bracket",
          bool(hr_) and bool(hp_) and box_on(hr_)[:2] == [True, True] and "its date came" in plain(hp_) and "arrived · arrived" not in plain(hp_) and "arrived arrived" not in plain(hp_) and "arrived" in plain(hr_)
          and "(its date came)" in wd_ and "()" not in wd_, why_ or why_w or (plain(hp_), wd_))
    bare = dataclasses.replace(m312, waits=tuple(dataclasses.replace(ln, arrived_at=at_, arrived_what="") if ln.arrived else ln for ln in m312.waits))
    try: wb_ = model.words(bare, when=server._arrival_when); hb_ = b.wait_list_html(r312, bare, page=True)
    except Exception as ex_: wb_ = hb_ = f"{ex_.__class__.__name__}: {ex_}"
    check(f"hostile model ({at_!r}): an arrival with no words and no time to say reads as ticked alone: get's words carry no empty bracket, the page says \"arrived\" once", "[x] the date " in wb_ and "[x] the close of a300;" in wb_ and "()" not in wb_ and "( )" not in wb_
          and plain(hb_).count("arrived arrived") == 0 and "arrived · arrived" not in plain(hb_), (wb_, plain(hb_)[:300]))
check("hostile: the time of an arrival is empty (never an error) for a time no date can show, in the server's `model:` line, and the zone follows a real one", all(server._arrival_when(x) == "" for x in (float("inf"), 1e20, 1e300, 253402300800.0, float("nan")))
      and server._arrival_when(GOT) == f"{day(0)} 08:30 {ZLAB}" and b.arrival_when(float("inf")) == "" and b.arrival_when(GOT) == W_(GOT), (server._arrival_when(float("inf")), server._arrival_when(GOT)))
# the brief's model line (short) carries the arrival time of a line as get's does: the same time formatter
sh312 = server._model_lines({**json.loads((T / "store/a/312.json").read_text()), "gid": "a312"}, short=True)
check("brief: the short model line of a list with arrived lines carries the time of each arrival and the zone's name, as get's line does (one line, no conflicts)",
      len(sh312) == 1 and f"(its date came, {day(0)} 08:30 {ZLAB})" in sh312[0] and sh312[0].startswith("model: waiting on several things (all of 6, 2 arrived: "), sh312)
# the time and its zone's name come from one source, read at the call (the instance zone can change under a running server, ZONE is fixed at import)
_tz0 = _cfg.CFG["instance"]["timezone"]
try:
    _cfg.CFG["instance"]["timezone"] = "Asia/Tokyo"
    at_tokyo = server._arrival_when(GOT)
finally:
    _cfg.CFG["instance"]["timezone"] = _tz0
tk = datetime.datetime.fromtimestamp(GOT, zoneinfo.ZoneInfo("Asia/Tokyo"))
check("zone: the arrival time is drawn in the zone the instance has at the call, with that zone's own name (never the clock of one zone with the name of another)", at_tokyo == f"{tk:%Y-%m-%d %H:%M} JST" and server._arrival_when(GOT) == f"{day(0)} 08:30 {ZLAB}", (at_tokyo, server._arrival_when(GOT)))
# an item id of a megabyte in a line is clipped everywhere it is drawn
c347, p347, h347, g347 = wait_cell("a347"), page_wait("a347"), b.item_html("a347"), get_line("a347")
check("clip: a line that names an item with a one-megabyte id is drawn with the id clipped (the home cell, the item page, get's model line), never the megabyte", len(c347) < 4000 and len(p347) < 8000 and len(h347) < len(b.item_html("a310")) + 5000 and len(g347) < 2000
      and LONG_ID[:300] in c347 and LONG_ID[:301] not in c347 and LONG_ID[:301] not in h347 and LONG_ID[:301] not in g347, (len(c347), len(p347), len(h347), len(g347)))
# an arrival with no words recorded
p348, c348, g348 = plain(page_wait("a348")), plain(wait_cell("a348")), get_line("a348")
check("words: a line that arrived with no recorded words reads as the time alone on the item page (\"arrived <time>\", the word once), the anchor line keeps its address before it", f"arrived {W_(GOT)}" in p348 and "arrived · arrived" not in p348 and "arrived arrived" not in p348
      and p348.count("arrived " + W_(GOT)) == 1 and f"{AURL} · arrived {W_(GOT + 60)}" in p348 and "arrived · arrived" not in c348, p348)
check("words: …and a line that arrived with words keeps them: \"<words> · arrived <time>\"", f"the lease arrived · arrived {W_(GOT)}" in p346, p346)
check("words: …in get's model line the time alone stands in the bracket, with the zone", f"[x] news of the lease ({day(0)} 08:30 {ZLAB})" in g348 and "()" not in g348, g348)

print(("ok" if not fails else "FAILED") + f": wait list display scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
