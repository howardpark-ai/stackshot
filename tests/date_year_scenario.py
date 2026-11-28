"""Scenario test for the year of a date a person reads (stackshot/core/datewords.py and every formatter that asks it): fixture data, no live store, no network.

A date of the current year is written without its year, a date of any other year says it. The current year is the one it is in the instance's timezone. The instance here is Asia/Seoul (UTC+9, ahead of UTC) and the
process runs in UTC, so around the turn of the year the instance's year, UTC's year and the process's own differ for nine hours: the cases sit in late December and early January, on both sides of that window. Covers:

  * the rule (datewords.other_year, day_words, when_words, numeric_day) with the clock pinned on both sides of the instance's midnight, and with a caller's own `today`;
  * the string table's date forms (i18n.fmt_date), in English and in a second language, an epoch drawn in a zone included;
  * the pages: the waiting list and the item page (a wait that ends in March of next year says the year, one that ends in December does not), the due badge, the audit card and the Audits page (the same month
    and day of another year is a date, never a bare clock), and board.md (the due line and the closed line);
  * the other text the owner reads: the board's own date words, the waiting notes, a watcher's date buttons (which still parse as the day they name), a job alert's times and the standby page's notice;
  * the audit card's script (node, when present): the same words as the server's, the year by the instance's timezone.

    tests/run-suite date_year        → exit 0 / 1"""
import datetime, json, logging, os, pathlib, re, shutil, subprocess, sys, time, types

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
os.environ["TZ"] = "UTC"; time.tzset()                # the process's own zone is not the instance's
tmp = _scratch.mkdtemp(prefix="dateyear-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Seoul")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml = _instance.set_person(toml)
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "brain/projects", "secrets", "touch", "locales"): (T / d).mkdir(parents=True)

UTC = datetime.timezone.utc
KST = datetime.timezone(datetime.timedelta(hours=9))
D = datetime.date
at = lambda *a, z=KST: datetime.datetime(*a, tzinfo=z)
NOW = at(2026, 12, 30, 10, 0)                          # the pages' "now" before the turn of the year
LATER = at(2027, 1, 1, 0, 30)                          # half an hour into the new year in Seoul; UTC is still Thu Dec 31st 2026
S1 = "00000000-0000-4000-8000-000000000001"
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({S1: {"name": "team-back", "machine": "a", "seen": NOW.timestamp(), "url": ""}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/hmp": {"title": "Hmp", "name": "Hmp", "org": "home", "tags": [], "type": "project", "session": "team-back", "status": "active",
    "board": [], "board_open": 0, "agents": {"team-back": "builds"}}}}))
(T / "brain/projects/hmp.md").write_text("---\ntitle: Hmp\n---\n\n# Hmp\n")
(T / "store/next-id").write_text("900")


def item(i, subject, status="open", updated=None, **meta):
    updated = updated or (NOW - datetime.timedelta(days=1)).timestamp()
    meta = {"owner": S1, "next": "team-back: do the thing", "project": "projects/hmp", **meta}
    if meta.get("hold") and not meta.get("needs"): meta.setdefault("post_wake_mover", S1)
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": "A fixture item.", "status": status, "updated": updated, "state_updated": updated,
                                                    "confirmed": updated, "metadata": meta}))


def waiting(i, subject, wake):
    item(i, subject, hold=True, wake=wake, wait_basis={"text": "the vendor ships", "wake": wake, "by": "team-back", "at": NOW.timestamp() - 86400}, next="team-back: review")


waiting(20, "[home] waits for March", "2027-03-05")
waiting(21, "[home] waits for next week", "2027-01-08")
item(30, "[home] due next year", due="2027-01-04")
item(31, "[home] due this year", due="2026-12-31")
item(40, "[home] closed in December", status="completed", updated=at(2026, 12, 29, 15, 0).timestamp(), outcome="done", reason="finished")

fails, ran = [], []


def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))


logging.disable(logging.INFO)
from stackshot.core import config as _cfg
from stackshot.core import datewords, readonly
from stackshot.audit import audit as _audit
from stackshot.audit import audit_overview as _ov
from stackshot.service import job_alert
from stackshot.waits import waiting as _waiting
from stackshot.waits import watchers
from stackshot.web import i18n
from stackshot.web import render as text
from stackshot.web.ui import render as pages


class clock:
    """The wall clock the rule reads (datewords.time), pinned to one instant for a block and put back."""
    def __init__(self, when, module=datewords): self.when, self.module = when, module
    def __enter__(self):
        self.old = self.module.time
        self.module.time = types.SimpleNamespace(time=lambda: self.when.timestamp())
    def __exit__(self, *exc): self.module.time = self.old


# ---- 1. the rule, with the clock on each side of the instance's midnight
BEFORE = at(2026, 12, 31, 23, 59)                      # Thu Dec 31st 2026 in Seoul
AFTER = at(2027, 1, 1, 0, 0)                           # Fri Jan 1st 2027 in Seoul, Thu Dec 31st 15:00 in UTC
check("setup: the instance's zone is ahead of UTC, and AFTER is still the old year in UTC and in the process's own zone",
      _cfg.tz().utcoffset(AFTER.replace(tzinfo=None)) == datetime.timedelta(hours=9) and datetime.datetime.fromtimestamp(AFTER.timestamp()).year == 2026 == AFTER.astimezone(UTC).year)
with clock(BEFORE):
    got = [datewords.other_year(D(2026, 1, 1)), datewords.other_year(D(2027, 1, 1)), datewords.day_words(D(2026, 12, 31)), datewords.day_words(D(2027, 1, 1)), datewords.numeric_day(D(2027, 1, 4))]
check("one minute before the instance's new year: this year's date has no year, the first day of the next one says it",
      got == [False, True, "Thu Dec 31st", "Fri Jan 1st 2027", "2027-01-04"], got)
with clock(AFTER):
    got = [datewords.other_year(D(2027, 1, 1)), datewords.other_year(D(2026, 12, 31)), datewords.day_words(D(2027, 3, 5)), datewords.day_words(D(2026, 12, 31)), datewords.numeric_day(D(2027, 1, 4)), datewords.numeric_day(D(2026, 12, 31))]
check("at the instance's new year, while UTC is still in the old one: the instance's year is the current one",
      got == [False, True, "Fri Mar 5th", "Thu Dec 31st 2026", "01-04", "2026-12-31"], got)
check("a caller's own today decides, whatever the clock says: the current year as before, a later and an earlier year said, the clock after the year",
      [datewords.when_words(at(2026, 11, 10, 16, 20), D(2026, 1, 1)), datewords.when_words(at(2027, 3, 5, 18, 30), D(2026, 12, 31)), datewords.when_words(at(2025, 3, 5, 18, 30), at(2026, 1, 1, 0, 0)),
       datewords.when_words(at(2027, 3, 5, 18, 30), D(2026, 12, 31), clock=False), datewords.when_words(D(2027, 11, 22), D(2026, 12, 31))]
      == ["Tue Nov 10th 16:20", "Fri Mar 5th 2027 18:30", "Wed Mar 5th 2025 18:30", "Fri Mar 5th 2027", "Mon Nov 22nd 2027"])

# ---- 2. the string table's forms
EPOCH = at(2027, 1, 1, 0, 30).timestamp()              # Thu Dec 31st 2026 15:30 in UTC
with clock(AFTER):
    got = [i18n.fmt_date(EPOCH, "en", tz=KST), i18n.fmt_date(at(2027, 3, 5, 18, 30), "en"), i18n.fmt_date(D(2026, 12, 31), "en"), pages.when_words(at(2026, 12, 31, 9, 0)), text.when_words(at(2026, 12, 31, 9, 0))]
check("fmt_date by the clock: an epoch is read in the zone given, and its year is held against the instance's current one",
      got == ["Fri Jan 1st 00:30", "Fri Mar 5th 18:30", "Thu Dec 31st 2026", "Thu Dec 31st 2026 09:00", "Thu Dec 31st 2026 09:00"], got)
with clock(BEFORE):
    got = [i18n.fmt_date(EPOCH, "en", tz=KST), i18n.fmt_date(EPOCH, "en", clock=False, tz=KST), i18n.fmt_date(D(2026, 12, 31), "en"), text.when_words(D(2027, 3, 5))]
check("…and the same dates a minute earlier", got == ["Fri Jan 1st 2027 00:30", "Fri Jan 1st 2027", "Thu Dec 31st", "Fri Mar 5th 2027"], got)
other = {"date.full": "D<{wd}/{month}/{day}/{hm}>", "date.nohm": "D<{wd}/{month}/{day}>", "date.full_year": "Y<{year}/{wd}/{month}/{day}/{hm}>", "date.nohm_year": "Y<{year}/{wd}/{month}/{day}>",
         "date.day": "{n}", **{f"date.wd.{i}": f"w{i}" for i in range(7)}, **{f"date.mon.{i}": f"m{i}" for i in range(1, 13)}}
(T / "locales/ko.json").write_text(json.dumps(other), encoding="utf-8")
_cfg.CFG.setdefault("ui", {})["locale_dir"] = str(T / "locales")
got = [i18n.fmt_date(at(2027, 3, 5, 18, 30), "ko", today=D(2026, 12, 31)), i18n.fmt_date(D(2027, 3, 5), "ko", today=D(2026, 12, 31)),
       i18n.fmt_date(at(2027, 3, 5, 18, 30), "ko", today=D(2027, 1, 1)), i18n.fmt_date(D(2027, 3, 5), "ko", today=D(2027, 1, 1))]
check("a second language writes a date of another year from its own year templates, one of this year from the others",
      got == ["Y<2027/w4/m3/5/18:30>", "Y<2027/w4/m3/5>", "D<w4/m3/5/18:30>", "D<w4/m3/5>"], got)
(T / "locales/ko.json").write_text(json.dumps({k: v for k, v in other.items() if not k.endswith("_year")}), encoding="utf-8")
i18n._WARNED.clear(); i18n._LOADED.clear()
got = i18n.fmt_date(D(2027, 3, 5), "ko", today=D(2026, 12, 31))
check("a language file without the year templates still says the year: the English template, with the language's own words", got == "w4 m3 5 2027", got)
_cfg.CFG["ui"].pop("locale_dir"); i18n._WARNED.clear(); i18n._LOADED.clear()


# ---- 3. the pages
def section(h, sid):
    i = h.find(f'<section id="{sid}">'); return h[i:h.find("</section>", i)] if i >= 0 else ""


def row(h, n):
    m = re.search(rf'id="task-a-{n}".*?</li>', h, re.S)
    return m.group(0) if m else ""


b = pages.Board(str(T / "store"), now=NOW)
home = b.html()
waits = section(home, "waiting-list")
check("the waiting list on Wed Dec 30th 2026: a wait that ends in March 2027 says 2027", "Fri Mar 5th 2027" in row(waits, 20), row(waits, 20))
check("…and one that ends in the first days of 2027 says it too: it is not this year", "Fri Jan 8th 2027" in row(waits, 21), row(waits, 21))
page = b.item_html("a20")
check("the item page of the March wait says the year", "Mar 5th 2027" in page and not re.search(r"Mar 5th(?! 2027)", page), re.findall(r".{60}Mar 5th.{30}", page))
due = lambda b_, n: b_.due_badge(next(r for r in b_.rows if r["gid"] == f"a{n}"))
check("the due badge: next year's day in full, this year's as month and day",
      "(2027-01-04 Mon)" in due(b, 30) and "(12-31 Thu)" in due(b, 31), (due(b, 30), due(b, 31)))
md = text.Board(str(T / "store"), now=NOW).render({"full"})["full"]
md2 = b.markdown()
check("board.md, both writers: the due lines say next year's day in full, the closed line of this year as before",
      all("(2027-01-04 Mon)**" in x and "(12-31 Thu)**" in x and "12-29 15:00" in x and "2026-12-29 15:00" not in x for x in (md, md2)), (re.findall(r".*(?:Due in|15:00).*", md), re.findall(r".*(?:Due in|15:00).*", md2)))

b2 = pages.Board(str(T / "store"), now=LATER)
home2 = b2.html()
waits2 = section(home2, "waiting-list")
check("the same pages half an hour into 2027 in Seoul: March and January of this year have no year",
      "Fri Mar 5th" in row(waits2, 20) and "2027" not in row(waits2, 20) and "Fri Jan 8th" in row(waits2, 21) and "2027" not in row(waits2, 21), (row(waits2, 20), row(waits2, 21)))
check("…the due badge turns over with it", "(01-04 Mon)" in due(b2, 30) and "(2026-12-31 Thu)" in due(b2, 31), (due(b2, 30), due(b2, 31)))
md = text.Board(str(T / "store"), now=LATER).render({"full"})["full"]
md2 = b2.markdown()
check("…and board.md says the year of December's close and of December's due day",
      all("(01-04 Mon)**" in x and "(2026-12-31 Thu)**" in x and "2026-12-29 15:00" in x for x in (md, md2)), (re.findall(r".*(?:Due in|15:00).*", md), re.findall(r".*(?:Due in|15:00).*", md2)))
epoch = at(2026, 12, 29, 15, 0).timestamp()
check("the boards' own date words follow their own now, not the clock: the same instant with and without the year",
      [b.when(epoch), b2.when(epoch), b.day_words(D(2027, 3, 5)), b2.day_words(D(2027, 3, 5))] == ["Tue Dec 29th 15:00", "Tue Dec 29th 2026 15:00", "Fri Mar 5th 2027", "Fri Mar 5th"]
      and [text.Board(str(T / "store"), now=n).when(epoch) for n in (NOW, LATER)] == ["Tue Dec 29th 15:00", "Tue Dec 29th 2026 15:00"], [b.when(epoch), b2.when(epoch)])

# ---- 4. the audit card and the Audits page
now3 = at(2027, 1, 2, 10, 0)
b3 = pages.Board(str(T / "store"), now=now3)
real = (_audit.status, _ov.card, _ov.overview, _ov.day_rows)
STARTS = [(at(2027, 1, 2, 9, 0), "09:00"), (at(2027, 1, 1, 0, 30), "Fri Jan 1st 00:30"), (at(2026, 12, 31, 23, 30), "Thu Dec 31st 2026 23:30"), (at(2026, 1, 2, 9, 0), "Fri Jan 2nd 2026 09:00")]
try:
    _ov.card = lambda *a, **k: {"groups": [], "note": ""}
    for when_, words in STARTS:
        _audit.status = lambda *a, _w=when_, **k: {"enabled": True, "running": True, "running_since": _w.timestamp(), "last": None}
        card = b3.audit_line()
        said = re.search(r'<span class="a-run">([^<]*)</span>', card)
        check(f"the audit card on Sat Jan 2nd 2027: a run since {words} is said that way", bool(said) and said.group(1).rstrip("….").endswith(" " + words), said.group(1) if said else card[:600])
    old = at(2026, 1, 2, 9, 0).timestamp()
    dec = at(2026, 12, 31, 23, 30).timestamp()
    jan = at(2027, 1, 1, 0, 30).timestamp()
    _ov.day_rows = lambda *a, **k: []
    _ov.overview = lambda *a, **k: {"enabled": True, "times": [], "next": jan, "running_since": None, "groups": [], "total": 0, "found": 1, "ten_last": old, "log": True,
        "recent": [{"at": dec, "id": "a20", "kind": "x", "source": "", "agent": "team-back", "detail": "a finding"}],
        "runs": [{"started": jan, "finished": jan + 5, "items": 1, "found": 0, "calls": 0, "error": ""}, {"started": dec, "finished": dec + 5, "items": 1, "found": 0, "calls": 0, "error": ""}]}
    ap = b3.audits_html()
finally:
    _audit.status, _ov.card, _ov.overview, _ov.day_rows = real
check("the Audits page: the next run and a run of this year without the year, a run and a finding of last December with it",
      "Fri Jan 1st 00:30" in ap and "<td>Fri Jan 1st 00:30</td>" in ap and "<td>Thu Dec 31st 2026 23:30</td>" in ap and '<div class="am">Thu Dec 31st 2026 23:30 ' in ap, re.findall(r"<td>[^<]*</td>|.{50}(?:Dec|Jan) .{30}", ap))
check("…and the same month and day of last year is a date with its year, not a bare clock", "Fri Jan 2nd 2026 09:00" in ap, re.findall(r".{60}09:00.{20}", ap))

# ---- 5. the other text the owner reads
with clock(AFTER):
    got = [_waiting.when_words(at(2026, 12, 31, 23, 30).timestamp()), _waiting.when_words(at(2027, 3, 5, 18, 30).timestamp()), watchers.day_words(D(2026, 12, 31)), watchers.day_words(D(2027, 3, 5))]
check("the waiting notes and the watchers' day words by the clock", got == ["Thu Dec 31st 2026 23:30", "Fri Mar 5th 18:30", "Thu Dec 31st 2026", "Fri Mar 5th"], got)
real_now = job_alert._jobalert_now
try:
    job_alert._jobalert_now = lambda: AFTER.astimezone(UTC)
    got = [job_alert._jobalert_when("2026-12-31T14:30:00Z"), job_alert._jobalert_when("2026-12-31T15:30:00Z")]
    job_alert._jobalert_now = lambda: BEFORE.astimezone(UTC)
    got.append(job_alert._jobalert_when("2026-12-31T15:30:00Z"))
finally:
    job_alert._jobalert_now = real_now
check("a job alert's times: the year is held against the alert's own now in the instance's timezone",
      [re.sub(r" [A-Z+0-9]+$", "", x) for x in got] == ["Thu Dec 31st 2026 23:30", "Fri Jan 1st 00:30", "Fri Jan 1st 2027 00:30"], got)
copy = T / "copy"; copy.mkdir()
(copy / ".synced-at").write_text("")
stamp = at(2026, 12, 31, 23, 30).timestamp()
os.utime(copy / ".synced-at", (stamp, stamp)); os.utime(copy, (stamp, stamp))
with clock(AFTER, readonly):
    stale = readonly.banner(copy, KST)
with clock(BEFORE, readonly):
    fresh = readonly.banner(copy, KST)
check("the standby notice: data from last year says which year, data of this year reads as before",
      "Thu Dec 31 2026, 23:30 " in stale and "Thu Dec 31, 23:30 " in fresh, (stale[-200:], fresh[-200:]))

# ---- 6. the audit card's script says what the server says
if shutil.which("node"):
    js = pages._AUDIT_JS
    part = js[js.index("var O={weekday"):js.index("function num(v)")]
    harness = r"""
const head=process.argv[1], part=process.argv[2], lang=JSON.parse(process.argv[3]), now=+process.argv[4], list=JSON.parse(process.argv[5]);
const vm=require('vm');const ctx={window:{},NOWMS:now*1000};vm.createContext(ctx);vm.runInContext(head.replace(/^<script>|<\/script>$/g,''),ctx);
if(lang)ctx.window.SSI=lang;
ctx.LIST=list;
vm.runInContext("Date.now=function(){return NOWMS};var SST=window.SST,Z='Asia/Seoul';"+part+";var out=LIST.map(function(t){return [when(t),clock(t)]});",ctx);
process.stdout.write(JSON.stringify(vm.runInContext('out',ctx)));"""
    times = [w.timestamp() for w, _words in STARTS] + [at(2027, 3, 5, 18, 30).timestamp()]
    (T / "locales/ko.json").write_text(json.dumps(other), encoding="utf-8")
    _cfg.CFG.setdefault("ui", {})["locale_dir"] = str(T / "locales"); i18n._WARNED.clear(); i18n._LOADED.clear()
    for lang in ("en", "ko"):
        for label, now_ in (("before", BEFORE), ("after", AFTER), ("two days in", now3)):
            table = None if lang == "en" else i18n.js_table(lang)
            sp = subprocess.run(["node", "-e", harness, pages._SST_HEAD, part, json.dumps(table), str(now_.timestamp()), json.dumps(times)], capture_output=True, text=True, timeout=30)
            got = json.loads(sp.stdout) if sp.returncode == 0 else sp.stderr[-500:]
            today = now_.date()
            full = [i18n.fmt_date(t, lang, tz=KST, today=today) for t in times]
            short = [f"{datetime.datetime.fromtimestamp(t, KST):%H:%M}" if datetime.datetime.fromtimestamp(t, KST).date() == today else f for t, f in zip(times, full)]
            check(f"the audit card's script ({lang}, {label}): the date and the clock are the server's, year and all", got == [[f, s] for f, s in zip(full, short)], (got, list(zip(full, short))))
    sp = subprocess.run(["node", "-e", harness, pages._SST_HEAD, part, "null", str(AFTER.timestamp()), json.dumps([at(2026, 12, 31, 23, 30).timestamp(), at(2027, 1, 1, 0, 0).timestamp()])], capture_output=True, text=True, timeout=30)
    got = json.loads(sp.stdout) if sp.returncode == 0 else sp.stderr[-500:]
    check("…pinned in English at the instance's new year, while UTC is still in the old one",
          got == [["Thu Dec 31st 2026 23:30", "Thu Dec 31st 2026 23:30"], ["Fri Jan 1st 00:00", "00:00"]], got)
    _cfg.CFG["ui"].pop("locale_dir")
else:
    print("note: node is not installed; the audit card's script was not run")

n_bad = len(fails)
print(f"{len(ran) - n_bad}/{len(ran)} checks passed")
sys.exit(1 if n_bad else 0)
