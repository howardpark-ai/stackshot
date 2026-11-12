"""Scenario test for the last activity an On agent row shows (ui/render.py act_parts, home_row and item_html; ui/kit.py row; model/last_activity.py age_s and band; web/i18n.py fmt_span) — fixture data, no live store, no network, no server.

An On agent row on the home page shows, in place of the age since the row's state began, the time since the item's last activity (the record `metadata.last_activity`, model/last_activity.py), under the mover a line with a pill and what it was:
"46m" · "quiet" · "Last: CI failed on PR 124 at 11:02". The same age and line stand beside the state on the item page. Covers:

  * the bands: green under 45 minutes, amber from 45 minutes up to and including an hour, red only past an hour (strictly more than 60 minutes), at their boundaries (44m 59s, 45m, 59m 59s, 1h exactly, 1h and a second), as the Python reads them and as the page script redraws them (run under node when it is installed);
  * the age forms: "<1m", "46m", "1h 44m", "2h 42m", "2d 3h", in Python (fmt_span) and in the script, the same for the same seconds;
  * the pill: "active" (green), "quiet" (amber), "idle over 1 h" (red), with the band on the age too;
  * the words: "Last: <what> at <HH:MM>" in the board's zone for each kind of activity the record has (every kind of last_activity.KINDS), the date too when it was not today, the words escaped;
  * the fallback: an item with no record, or a torn one, keeps the old age ("3h ago") and has no activity line; a parked (on hold) item, and rows of the other lists (Your move, Waiting), have none either;
  * the item page shows the line for an item on an agent, and not for an item with no record or one on Your move;
  * the live update does not see the age, the pill or the band as a change of the block (_VOLATILE), and the script keeps them current on a swap;
  * the legacy markdown board (web/render.py) draws no age and no row for On agent, so it is the same with or without the record.

    tests/run-suite on_agent_row        → exit 0 / 1"""
import datetime, json, os, re, shutil, subprocess, sys, pathlib, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="onagentrow-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Seoul")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "brain/projects", "secrets", "touch"): (T / d).mkdir(parents=True)
ZONE = datetime.timezone(datetime.timedelta(hours=9))      # Asia/Seoul: UTC+9, no DST
NOW = datetime.datetime(2026, 11, 12, 11, 48, tzinfo=ZONE); now = NOW.timestamp()
M, H, D = 60.0, 3600.0, 86400.0
S1, S2 = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({S1: {"name": "front-a", "machine": "a", "seen": now, "url": ""}, S2: {"name": "worker-a", "machine": "a", "seen": now, "url": ""}}))
PAGES = {"projects/demo": {"title": "Demo", "name": "Demo", "org": "work", "tags": [], "type": "project", "session": S1, "status": "active", "board": [], "board_open": 0, "agents": {"front-a": "builds"}},
         "projects/quiet": {"title": "Quiet", "name": "Quiet", "org": "work", "tags": [], "type": "project", "session": S1, "status": "active", "board": [], "board_open": 0, "agents": {"front-a": "builds"}}}
(T / "store/projects.json").write_text(json.dumps({"pages": PAGES}))
(T / "brain/projects/demo.md").write_text("---\ntitle: demo\n---\n\n# demo\n")
(T / "brain/projects/quiet.md").write_text("---\ntitle: quiet\n---\n\n# quiet\n")
(T / "store/next-id").write_text("900")
def item(i, subject, act=None, since=3 * H, **meta):
    """An item on worker-a (the mover); `act` is (seconds ago, kind, what) for its last-activity record, or a torn/empty value stored as it is."""
    meta = {"owner": S2, "next": "worker-a: do the thing", "needs": ["worker-a"], "project": "projects/demo", **meta}
    if isinstance(act, tuple): meta["last_activity"] = {"at": now - act[0], "kind": act[1], "what": act[2]}
    elif act is not None: meta["last_activity"] = act
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": "A fixture item.", "status": "open", "updated": now - since, "state_updated": now - since,
                                                    "confirmed": now - since, "metadata": meta}))

# the three rows of the approved mockup, as fixture data (the times are the mockup's)
item(101, "[work] cut the suites per change", (104 * M, "audit", "fix commit on PR 124"), since=8 * H)
item(102, "[work] retire the polling wake", (46 * M, "audit", "fix commit on PR 122"), since=4 * H)
item(103, "[work] install the new release", (162 * M, "step_done", "step 2 done"), since=2 * H)
# the bands at their boundaries
for i, secs in ((111, 44 * M + 59), (112, 45 * M), (113, 59 * M + 59), (114, 60 * M), (115, 61 * M), (116, 30), (117, 60 * M + 1)):
    item(i, f"[work] band {i}", (secs, "ci_result", "CI failed on PR 124"))
# one item for each kind the record has
KINDS = {"step_done": "step 3 done", "step_dropped": "step 1 dropped", "state_change": "state: waiting (time)", "pr_merged": "PR 124 merged", "ci_result": "CI passing again on PR 124",
         "review": "review on PR 124", "comment": "comment on #124", "commit": "commit on PR 124", "update": "moved to the staging tier", "audit": "a commit on PR 124 at the head"}
for n, (kind, what) in enumerate(KINDS.items()):
    item(130 + n, f"[work] kind {kind}", (20 * M, kind, what))
item(150, "[work] older day", (30 * H, "step_done", "step 1 done"))                         # yesterday, 05:48
item(151, "[work] markup in the words", (10 * M, "update", "<b>bold</b> & more"))
item(160, "[work] no record", None, since=3 * H)
item(161, "[work] torn record", {"at": now - 10 * M, "kind": "no_such_kind", "what": "x"}, since=3 * H)
item(162, "[work] torn time", {"at": "soon", "kind": "step_done", "what": "step 1 done"}, since=3 * H)
item(163, "[work] a bool as the time", {"at": True, "kind": "step_done", "what": "step 1 done"}, since=3 * H)
item(164, "[work] a string as the time", {"at": str(int(now - 10 * M)), "kind": "step_done", "what": "step 1 done"}, since=3 * H)
item(165, "[work] a time two hours ahead of the clock", (-2 * H, "step_done", "step 1 done"), since=3 * H)      # later than now + the skew: no record, never "<1m"
item(166, "[work] a time five minutes ahead of the clock", (-5 * M, "step_done", "step 1 done"), since=3 * H)      # inside the skew: just now
item(118, "[work] a fraction of a second past the hour", (3599.5, "ci_result", "CI failed on PR 124"))
item(167, "[work] on a project whose rows have no record", None, since=3 * H, project="projects/quiet")
BIG = (1e12, 2.6e11, 253402300799.0, 253402300800.0, 1e18, 1e300, 10 ** 30)      # finite and positive, and past what the calendar can take (a count of milliseconds, the end of year 9999 and a hair after, absurd ones)
for n, v in enumerate(BIG): item(190 + n, f"[work] out of range {n}", {"at": v, "kind": "step_done", "what": "step 1 done"}, since=3 * H)
item(170, "[work] held with a record", (200 * M, "step_done", "step 1 done"), hold=True, wake=(NOW + datetime.timedelta(days=2)).strftime("%Y-%m-%d"),
     wait_basis={"text": "the vendor ships", "wake": (NOW + datetime.timedelta(days=2)).strftime("%Y-%m-%d"), "by": "worker-a", "at": now - D}, next="worker-a: review")
ASK = "Decide: ship the thing? · Recommend: yes · Stakes: low · By: Fri"
item(180, "[work] your move with a record", (200 * M, "step_done", "step 1 done"), needs=["decision"], ask=ASK, next="Oliver: answer the ask", owner=S1)
item(181, "[work] your move, no record", None, needs=["decision"], ask=ASK, next="Oliver: answer the ask", owner=S1)

fails, ran = [], []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
logging.disable(logging.INFO)
from stackshot.model import last_activity as la
from stackshot.web import i18n, home
from stackshot.web.ui import render

def board():
    b = render.Board(str(T / "store"), now=NOW)
    b.provision = [("home-box", True)]
    b._rel_ids = set()
    return b
b = board()
lists = b.home_lists()
pair = {r["gid"]: (r, m) for ps in lists.values() for r, m in ps}
which_of = {r["gid"]: w for w, ps in lists.items() for r, _m in ps}
def row(i, w=None):
    r, m = pair[f"a{i}"]; return b.home_row(r, m, w or which_of[f"a{i}"], named=True)
class _G:
    """A search result that answers .group() with empty strings when nothing matched, so a missing piece fails its check by name and not the run."""
    def __init__(self, m): self.m = m
    def group(self, n=0): return self.m.group(n) if self.m else ""
def age_of(h): return _G(re.search(r'<span class="tip ir-age"[^>]*data-b="(\w+)"[^>]*>([^<]*)</span>', h))
def pill_of(h): return _G(re.search(r'<span class="ir-pill" data-at="\d+" data-b="(\w+)"[^>]*>([^<]*)</span>', h))
def last_of(h): return _G(re.search(r'<span class="ir-lwhat">([^<]*)</span>', h))
def clock(secs_ago): return datetime.datetime.fromtimestamp(now - secs_ago, ZONE).strftime("%H:%M")

check("setup: the fixture rows are On agent, except the held one (Waiting) and the two Your move ones", all(which_of[f"a{i}"] == home.AGENTS for i in (101, 102, 103, 111, 150, 160, 161)) and which_of["a180"] == home.YOUR_MOVE and which_of["a170"] == home.WAITING,
      {k: v for k, v in which_of.items()})

# ---- the bands (the model's own reading, then the page) ----
check("band: 44m 59s is ok, 45m is warn", la.band(44 * M + 59) == la.OK and la.band(45 * M) == la.WARN, (la.band(44 * M + 59), la.band(45 * M)))
check("band: 59m 59s is warn, exactly 1h is still warn, 1h and a second is bad, 61m is bad", la.band(59 * M + 59) == la.WARN and la.band(60 * M) == la.WARN and la.band(60 * M + 1) == la.BAD and la.band(60 * M + 0.001) == la.BAD and la.band(61 * M) == la.BAD,
      [la.band(x) for x in (59 * M + 59, 60 * M, 60 * M + 1, 61 * M)])
check("band: zero is ok and 5 days is bad", la.band(0) == la.OK and la.band(5 * D) == la.BAD)
check("age_s: no record gives None, a record gives the seconds since, one ahead of now gives 0",
      la.age_s({"metadata": {}}, now) is None and la.age_s({"metadata": {"last_activity": {"at": now - 90, "kind": "step_done", "what": "step 1 done"}}}, now) == 90
      and la.age_s({"metadata": {"last_activity": {"at": now + 500, "kind": "step_done", "what": "step 1 done"}}}, now) == 0 and la.age_s(None, now) is None)
check("age_s: a record more than the skew ahead of now is no record (None), never 0; exactly the skew ahead is still just now; read and at say the same",
      la.age_s({"metadata": {"last_activity": {"at": now + 2 * H, "kind": "step_done", "what": "step 1 done"}}}, now) is None and la.age_s({"metadata": {"last_activity": {"at": now + la.SKEW_S, "kind": "step_done", "what": "step 1 done"}}}, now) == 0
      and la.age_s({"metadata": {"last_activity": {"at": now + la.SKEW_S + 1, "kind": "step_done", "what": "step 1 done"}}}, now) is None
      and la.read({"metadata": {"last_activity": {"at": now + 2 * H, "kind": "step_done", "what": "x"}}}, now) is None and la.at({"metadata": {"last_activity": {"at": now + 2 * H, "kind": "step_done", "what": "x"}}}, now) == 0.0)
band_of = {i: age_of(row(i)).group(1) for i in (111, 112, 113, 114, 115, 116, 117)}
check("the page: 44m 59s green, 45m amber, 59m 59s amber, exactly 1h amber, 1h and a second red, 61m red, half a minute green", band_of == {111: "ok", 112: "warn", 113: "warn", 114: "warn", 115: "bad", 116: "ok", 117: "bad"}, band_of)
NOW2 = NOW + datetime.timedelta(milliseconds=200)      # a page clock 0.2 s on: the record 59.5 s short of the hour is 3599.7 s old by the exact numbers (amber), 3600.2 s old by its whole second (red)
b2 = render.Board(str(T / "store"), now=NOW2); b2.provision = [("home-box", True)]; b2._rel_ids = set()
pair2 = {r["gid"]: (r, m) for ps in b2.home_lists().values() for r, m in ps}
row118 = b2.home_row(pair2["a118"][0], pair2["a118"][1], home.AGENTS, named=True)
check("the page: a record 59.5 seconds short of the hour, on a clock 0.2 s on, is banded by the whole second the script reads (data-at), so the server and the script agree (red, not amber)",
      re.search(r'data-at="(\d+)"', row118).group(1) == str(int(now - 3599.5)) and age_of(row118).group(1) == la.band(NOW2.timestamp() - int(now - 3599.5)) == "bad", (re.findall(r'data-at="\d+"', row118), age_of(row118).group(1)))
check("the pill takes the same band as the age", all(pill_of(row(i)).group(1) == band_of[i] for i in band_of))
check("the pill words: green active, amber quiet (exactly an hour too), red idle over 1 h (past it)", [pill_of(row(i)).group(2) for i in (111, 112, 114, 115)] == ["active", "quiet", "quiet", "idle over 1 h"], [pill_of(row(i)).group(2) for i in (111, 112, 114, 115)])
check("the colors are the page's own tokens (no new color): green --t-done, amber --amber, red --red", all(x in render._ui.CSS for x in (".ir-age[data-b=ok],.ir-pill[data-b=ok]{color:var(--t-done)}", "[data-b=warn],.ir-pill[data-b=warn]{color:var(--amber)}", "[data-b=bad],.ir-pill[data-b=bad]{color:var(--red)}")))

# ---- the age forms ----
FORMS = [(0, "<1m"), (59, "<1m"), (60, "1m"), (44 * M, "44m"), (46 * M, "46m"), (59 * M + 59, "59m"), (60 * M, "1h 0m"), (104 * M, "1h 44m"), (162 * M, "2h 42m"), (23 * H + 59 * M, "23h 59m"), (24 * H, "1d 0h"), (51 * H, "2d 3h")]
check("fmt_span: <1m, 46m, 1h 44m, 2h 42m, 2d 3h", all(i18n.fmt_span(s) == w for s, w in FORMS), [(s, i18n.fmt_span(s), w) for s, w in FORMS if i18n.fmt_span(s) != w])
check("the page draws the age in those forms: 1h 44m (red), 46m (amber), 2h 42m (red)", [age_of(row(i)).group(2) for i in (101, 102, 103)] == ["1h 44m", "46m", "2h 42m"], [age_of(row(i)).group(2) for i in (101, 102, 103)])
check("the age is the time since the activity, not since the row's state began (8 hours ago on 101)", "8h ago" not in row(101) and "ir-age" in row(101) and 'data-ts=' not in age_of(row(101)).group(0), row(101)[:600])
check("the age carries the activity's time for the page script and a tooltip with its date and zone",
      f'data-at="{int(now - 104 * M)}"' in row(101) and "last activity Thu Nov 12th 10:04 KST" in row(101), re.findall(r'data-tip="[^"]*"', row(101)))

# ---- the words ----
check("Last: the mockup's three rows read 'fix commit on PR 124 at 10:04', 'fix commit on PR 122 at 11:02', 'step 2 done at 09:06'",
      [last_of(row(i)).group(1) for i in (101, 102, 103)] == ["Last: fix commit on PR 124 at 10:04", "Last: fix commit on PR 122 at 11:02", "Last: step 2 done at 09:06"], [last_of(row(i)).group(1) for i in (101, 102, 103)])
check("the times are in the board's zone (the rows above are KST), not UTC", clock(104 * M) == "10:04" and "at 01:04" not in row(101))
got = {k: (last_of(row(130 + n)).group(1) if last_of(row(130 + n)).m else None) for n, k in enumerate(KINDS)}
check("Last: every kind the record has (la.KINDS) is worded: '<what> at <HH:MM>'", set(KINDS) == set(la.KINDS) and got == {k: f"Last: {w} at {clock(20 * M)}" for k, w in KINDS.items()}, got)
check("Last: the words the server stamps are shown as they are (a state change, a merge, a step, a CI result)", all(w in "".join(row(130 + n) for n in range(len(KINDS))) for w in ("state: waiting (time)", "PR 124 merged", "step 3 done", "CI passing again on PR 124")))
check("Last: an activity of another day carries its date ('Wed Nov 11th 05:48'), one of today only the clock", last_of(row(150)).group(1) == "Last: step 1 done at Wed Nov 11th 05:48" and last_of(row(101)).group(1).endswith(" at 10:04"), last_of(row(150)).group(1))
check("Last: the words are escaped", "&lt;b&gt;bold&lt;/b&gt; &amp; more" in row(151) and "<b>bold</b>" not in row(151), last_of(row(151)).group(1))
check("the activity line is under the mover and above the detail, in a div.ir-actl: pill first, then the words",
      re.search(r'class="ir-who">.*?</div><div class="ir-actl"><span class="ir-pill".*?</span><span class="ir-lwhat">.*?</span></div><div class="ir-det">', row(101)) is not None, row(101))
check("the title, the id and the mover stay: the row is still the one row", 'class="ir-link"' in row(101) and 'class="ir-who"' in row(101) and "worker-a" in row(101))

# ---- the fallback ----
for i, why in ((160, "no record"), (161, "a record of an unknown kind"), (162, "a record with no time"), (163, "a record whose time is a bool"), (164, "a record whose time is a string"), (165, "a record two hours ahead of the clock")):
    h_ = row(i)
    check(f"{why}: the old age ('3h ago', counted from the state's start, ticked by data-ts), no pill, no activity line",
          "3h ago" in h_ and 'data-ts="' in h_ and "ir-actl" not in h_ and "ir-pill" not in h_ and "data-at" not in h_ and "Last:" not in h_, h_[:500])
check("a record five minutes ahead of the clock (inside the skew) reads as just now, not as no record", "&lt;1m" in age_of(row(166)).group(2) and "ir-actl" in row(166) and age_of(row(166)).group(1) == "ok", row(166)[:400])
check("…and the item page of the one two hours ahead draws no line either", 'class="ir-actl"' not in b.item_html("a165") and 'class="ir-actl"' not in b.item_html("a163") and 'class="ir-actl"' not in b.item_html("a164") and 'class="ir-actl"' in b.item_html("a166"))
for n, v in enumerate(BIG):
    h_ = row(190 + n)
    check(f"an `at` of {v!r} (past the calendar) is a torn record: the row is drawn with the old age and no line, nothing raises", "3h ago" in h_ and "ir-actl" not in h_ and "data-at" not in h_, h_[:300])
h_all = b.html()
check("…the home page and each such item's page are drawn whole", all('id="task-a-%d"' % (190 + n) in h_all for n in range(len(BIG))) and all("3h" in b.item_html(f"a{190 + n}") and 'class="ir-actl"' not in b.item_html(f"a{190 + n}") for n in range(len(BIG))))
check("…the record refuses them at the source (read gives None) and the latest time kept is still readable",
      all(la.read({"metadata": {"last_activity": {"at": v, "kind": "step_done", "what": "x"}}}) is None for v in BIG) and la.read({"metadata": {"last_activity": {"at": la.MAX_AT, "kind": "step_done", "what": "x"}}}) is not None)
_read = render._lastact.read
render._lastact.read = lambda it, now=None: {"at": 253402300800.0, "kind": "step_done", "what": "x"}      # a record that got past the source: the row still does not raise
try:
    try: guarded = b.act_parts(pair["a101"][0]); rowh = row(101); iph = b.item_html("a101")
    except Exception as e_: guarded, rowh, iph = f"raised {e_!r}", "", ""
finally: render._lastact.read = _read
check("…and a time that got past the source is caught in the row too: no activity, the old age", guarded is None and "ir-actl" not in rowh and "8h ago" in rowh and 'class="ir-actl"' not in iph)
check("a held item with a record (it is in Waiting) is drawn with no activity line, and act_parts gives it nothing whatever the list",
      'class="ir-actl"' not in row(170) and "data-at" not in row(170) and b.act_parts(pair["a170"][0]) is None and b.act_parts(pair["a101"][0]) is not None, row(170)[:400])
pj_demo, pj_quiet = b.routing_html("projects/demo"), b.routing_html("projects/quiet")
check("the project page keeps its On agent rows current with the same script (it draws data-at, so it carries lact), and a project page whose rows have no record carries no script for it",
      'data-at="' in pj_demo and "function lact()" in pj_demo.split("</main>")[0] and "ir-actl" in pj_demo and 'data-at="' not in pj_quiet and "function lact()" not in pj_quiet and "a167" in pj_quiet, (len(pj_demo), len(pj_quiet)))
check("a Your move row with a record has none either: the nag there is its own age", 'class="ir-actl"' not in row(180) and "data-at" not in row(180) and "data-ts=" in row(180))
check("a row of the same list with a record and one without sit together, each drawn its own way", "ir-pill" in row(101) and "ir-pill" not in row(160))

# ---- the home page as a whole ----
h = h_all
agents = h[h.find('<section id="agents-at-work">'):h.find("</section>", h.find('<section id="agents-at-work">'))]
check("the home page's On agent list holds the activity lines of the 24 rows with a record that reads (the held row, the torn ones and the one far ahead of the clock have none)", agents.count('class="ir-actl"') == 24, agents.count('class="ir-actl"'))
check("the home page's script redraws them: the script has the lact function, and a swap calls it, in its own listener, so the receivers script keeps its shape", "function lact()" in h and "document.addEventListener('stackshot:swapped',lact)" in h and "tick();rcv()});})();" in h)
check("the Your move list has no activity line at all", 'class="ir-actl"' not in h[h.find('<section id="your-move">'):h.find("</section>", h.find('<section id="your-move">'))])

# ---- the live update ----
def vol(html):
    for rx, rp in render._VOLATILE: html = rx.sub(rp, html)
    return html
later = render.Board(str(T / "store"), now=NOW + datetime.timedelta(minutes=17)); later.provision = [("home-box", True)]; later._rel_ids = set()
lh = later.html()
la_, lb_ = (x[x.find('<section id="agents-at-work">'):x.find("</section>", x.find('<section id="agents-at-work">'))] for x in (h, lh))
check("two renders of the same board 17 minutes apart differ in the age, the pill and the band, and have the same fingerprint once those are taken out", la_ != lb_ and vol(la_) == vol(lb_), [a for a, c in zip(vol(la_).split("<li"), vol(lb_).split("<li")) if a != c][:1])
check("a new activity is still a change: another time or other words give another fingerprint",
      vol(re.sub(r'data-at="\d+"', 'data-at="1"', la_, count=1)) != vol(la_) and vol(la_.replace("step 2 done", "step 3 done")) != vol(la_))

# ---- the item page ----
ip = b.item_html("a101")
check("the item page shows the same line beside the state: a label, the age, the pill, the words", re.search(r'<div class="istat"><p class="istate">.*?</p><div class="ir-actl"><span class="ir-lbl">Last activity</span><span class="tip ir-age"[^>]*>1h 44m</span><span class="ir-pill"[^>]*>idle over 1 h</span><span class="ir-lwhat">Last: fix commit on PR 124 at 10:04</span></div></div>', ip) is not None, ip[ip.find('class="istat"'):][:700])
check("the item page keeps the age current with the same script", "function lact()" in ip.split("</main>")[0])
check("the item page of an item with no record has no line and no script for it", 'class="ir-actl"' not in b.item_html("a160") and "function lact()" not in b.item_html("a160"))
check("the item page of a Your move item has no line", 'class="ir-actl"' not in b.item_html("a180") and "function lact()" not in b.item_html("a180"))
check("the item page of a held item has no line", 'class="ir-actl"' not in b.item_html("a170"))
check("the item page's band follows the age: 46m is amber, quiet", re.search(r'data-b="warn"[^>]*>46m</span><span class="ir-pill"[^>]*data-b="warn">quiet', b.item_html("a102")) is not None or ("quiet" in b.item_html("a102") and 'data-b="warn"' in b.item_html("a102")))

# ---- the page script, run against the same numbers ----
node = shutil.which("node")
if node:
    stub = ("var out=[];var W=%s;window={};document={querySelectorAll:function(){return els},addEventListener:function(){}};global.window=window;global.document=document;var T=%s;SST=window.SST=function(k,f){var s=T[k];return f?s.replace(/\\{(\\w+)\\}/g,function(m,x){return f[x]}):s};"
            "function mk(at,pill){var a={};return {classList:{contains:function(c){return pill&&c==='ir-pill'}},getAttribute:function(k){return k==='data-at'?String(at):W[k]},setAttribute:function(k,v){a[k]=v},get textContent(){return this._t},set textContent(v){this._t=v},attr:a}}"
            "var els=[];setInterval=function(){};Date.now=function(){return %d};"
            "[%s].forEach(function(s){var age=mk(%d-s,false),pill=mk(%d-s,true);els=[age,pill];%s;out.push([s,age._t,age.attr['data-b'],pill._t,pill.attr['data-b']])});console.log(JSON.stringify(out))")
    secs = [s for s, _w in FORMS] + [44 * M + 59, 45 * M, 59 * M + 59, 60 * M, 61 * M, 60 * M + 1]
    js = stub % (json.dumps(dict(re.findall(r'(data-w-\w+)="([^"]*)"', row(101)))), json.dumps(i18n.js_table("en")), int(now * 1000), ",".join(str(int(s)) for s in secs), int(now), int(now), render._LACT_JS)
    p = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=60)
    try: out = json.loads(p.stdout)
    except Exception: out = None
    check("the page script runs under node", p.returncode == 0 and out is not None, (p.stderr or p.stdout)[-600:])
    if out:
        check("the page script draws the same age text as fmt_span for the same seconds", all(a == i18n.fmt_span(s) for s, a, _b, _p, _pb in out), [(s, a, i18n.fmt_span(s)) for s, a, _b, _p, _pb in out if a != i18n.fmt_span(s)])
        check("the page script: exactly an hour is amber and an hour and a second red, as la.band reads them", {s: b_ for s, _a, b_, _pt, _pb in out if s in (60 * M, 60 * M + 1)} == {60 * M: "warn", 60 * M + 1: "bad"}, out)
        check("the page script takes the same band as la.band, on the age and on the pill, and the pill's words", all(b_ == la.band(s) == pb and pt == {la.OK: "active", la.WARN: "quiet", la.BAD: "idle over 1 h"}[b_] for s, _a, b_, pt, pb in out), [o for o in out if o[2] != la.band(o[0])])
    # a page clock half a second on from the hour: the record's whole second (data-at) is 3600.2 s old: red, as the server banded it
    js2 = stub % (json.dumps(dict(re.findall(r'(data-w-\w+)="([^"]*)"', row(101)))), json.dumps(i18n.js_table("en")), int((now + 0.2) * 1000), "3600", int(now), int(now), render._LACT_JS)
    p2 = subprocess.run([node, "-e", js2], capture_output=True, text=True, timeout=60)
    try: out2 = json.loads(p2.stdout)
    except Exception: out2 = None
    check("the page script, on a clock 0.2 s past the whole hour, takes red, as the server did for the same record (the two read the same whole seconds)", out2 and out2[0][2] == "bad", (p2.stderr or p2.stdout)[-400:])
    # an element dated more than the skew ahead of the page's clock is left as the server drew it (never rewritten to "<1m"); one inside the skew is just now
    js3 = stub % (json.dumps(dict(re.findall(r'(data-w-\w+)="([^"]*)"', row(101)))), json.dumps(i18n.js_table("en")), int(now * 1000), "-7200,-300", int(now), int(now), render._LACT_JS)
    js3 = js3.replace("els=[age,pill];", "age._t=pill._t='kept';els=[age,pill];")
    p3 = subprocess.run([node, "-e", js3], capture_output=True, text=True, timeout=60)
    try: out3 = json.loads(p3.stdout)
    except Exception: out3 = None
    check("the page script leaves an element dated 2 h ahead of its clock as the server drew it (no '<1m', no band), and reads one 5 minutes ahead as just now",
          out3 and out3[0][1] == "kept" and out3[0][2] is None and out3[0][3] == "kept" and out3[1][1] == "<1m" and out3[1][2] == "ok", (out3, (p3.stderr or "")[-300:]))
else:
    print("note: node is not installed; the script's checks were skipped")
check("the script's thresholds are the model's (45 and 60 minutes, in seconds: past 60 is red, from 45 amber), not copies that can drift", "s>3600?'bad':s>=2700?'warn'" in render._LACT_JS and la.BAND_WARN_S == 45 * 60 and la.BAND_BAD_S == 60 * 60 and f"-{int(la.SKEW_S)})return" in render._LACT_JS)
check("the age forms the script says are in the string table every page carries (age.*); the pill's words are on the pill (data-w-*), so no page without a pill carries the word 'idle'",
      all(k in i18n.js_table("en") for k in ("age.span_now", "age.span_min", "age.span_hour", "age.span_day")) and not any("idle" in v for v in i18n.js_table("en").values()) and 'data-w-ok="active" data-w-warn="quiet" data-w-bad="idle over 1 h"' in row(101))

# ---- the legacy markdown board draws no row ----
from stackshot.web import render as legacy
def md():
    return legacy.Board(str(T / "store")).markdown()
with_rec = md()
for i in (101, 102, 103): p_ = T / f"store/a/{i}.json"; d_ = json.loads(p_.read_text()); d_["metadata"].pop("last_activity"); p_.write_text(json.dumps(d_))
check("web/render.py (board.md) draws no age and no row for On agent: the same text with and without the record, and no activity words", with_rec == md() and "Last:" not in with_rec and "idle over" not in with_rec)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
