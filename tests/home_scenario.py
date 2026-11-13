"""Scenario test for the home page on the item model (home.py and Board.home_* in ui/render.py; the board item step 3, part 1; the design: gbrain
docs/design, section 8, and its build plan, step 3) — fixture data, no live store, no network, no server.

Every open item is in exactly one of the home page's lists, from model.derive (the stored model fields, else today's fields): Your move (alive, Oliver the mover, oldest first), On agent
(alive, any other mover: oldest first by the age the row shows, the mover's name playing no part; section id agents-at-work), Queued for release (empty here) and Waiting (by end date). Covers:

  * every row, in every list: the title linking the item page with its number, the immediate next step (the first `next` line, its `<mover>: ` prefix stripped), the mover (a session linked to the
    fleet tool while its pane lives, the post-wake mover on Waiting), the age since the state began; an item with no stored model field lands in exactly one list by today's fields;
  * Your move: the age amber past two days and red past five, nothing before; a decision's question with one card per option (none stored: Yes and No; Approve and Decline only as stored options), the
    note box and one Send, drawn disabled for the page script to enable once it has a token; a step's command in a block to copy, a link in it staying inline; a relay come due with its three cards;
  * On agent: "handed to X, not yet taken" on the who line, `woke: <what> → <mover>`, the sort;
  * Waiting: what it waits on (a time with his words or the basis; another item's close; an anchor and its event, or "an anchor (none recorded)"; a party's news with its ask-by day) and the chases, "then" and
    "watched by" (when something watches) on the who line; the next step after the wait; sorted by end date;
  * the five counts at the top; the old state tiles, Need your call (agents), For you, Needs your call, On others and Parked on an outside event gone; the provision line,
    the right-hand panel (Machines, Runners, Anchor hub, Audit, all open), the theme and reload buttons kept.

    tests/run-suite home        → exit 0 / 1"""
import datetime, json, os, re, sys, pathlib, tempfile, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="hometest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
toml = toml.replace('session_view = ""', 'session_view = "https://sala.example.org/#s={name}"', 1); assert "sala.example.org" in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
ZONE_HOURS = 4; ZONE = datetime.timezone(datetime.timedelta(hours=ZONE_HOURS))      # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
NOW = datetime.datetime(2026, 10, 27, 10, 0, tzinfo=ZONE)
now = NOW.timestamp()
H, D = 3600.0, 86400.0
day = lambda n: (NOW + datetime.timedelta(days=n)).strftime("%Y-%m-%d")
SESS = {"front": "00000000-0000-4000-8000-000000000001", "back": "00000000-0000-4000-8000-000000000002", "build": "00000000-0000-4000-8000-000000000003",
        "other": "00000000-0000-4000-8000-000000000004", "gone": "00000000-0000-4000-8000-000000000005"}
NAME = {"front": "home-front", "back": "team-back", "build": "home-build", "other": "home-other", "gone": "home-gone"}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({SESS[k]: {"name": NAME[k], "machine": "a", "seen": now, "url": f"https://claude.ai/code/{k}"} for k in ("front", "back", "build", "other")}))
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-front", "status": "active", "board": [], "board_open": 0,
                       "agents": {"home-front": "the front", "team-back": "the back", "home-build": "the builder", "home-other": "the other"},
                       "back_agents": {"team-back": "the back", "home-build": "the builder", "home-other": "the other"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-front\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-build: the builder\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": "https://github.com/o/r/pull/9", "items": ["a11"], "added": 1, "by": "t"},
                                                                                                                    {"url": "https://github.com/o/r/pull/12", "items": ["a29"], "added": 2, "by": "t"}, {"url": "https://example.invalid/thread/2", "items": ["a29"], "added": 3, "by": "t"},
                                                                                                                    {"url": "https://example.invalid/thread/3", "items": ["a29"], "added": 4, "by": "t"}, {"url": "https://example.invalid/thread/4", "items": ["a29"], "added": 5, "by": "t"},
                                                                                                                    # hand-edited junk the page must step over: a url that is no string, no url, an items that is no list
                                                                                                                    {"url": 123, "items": ["a29"], "added": 6, "by": "t"}, {"url": None, "items": ["a29"]}, {"items": ["a29"]}, {"url": "https://example.invalid/junk", "items": "a29", "added": 7}]}))
_ck = NOW.strftime("%Y-%m-%d %H:%M:%S")
(T / "state/anchor-hub/status.json").write_text(json.dumps({"started": _ck, "anchors": {}, "receivers": {"slack": {"ok": True, "checked": _ck}, "github": {"ok": True, "checked": _ck}}}))
(T / "state/waiting.json").parent.mkdir(parents=True, exist_ok=True)
(T / "state/waiting.json").write_text(json.dumps({"baseline": now - 100 * D, "seen": {}, "reported": []}))


def item(i, subject, status="open", age=3 * H, owner="back", project="projects/alpha", **meta):
    meta = {"owner": SESS[owner], "next": "team-back: do the thing", **meta}
    if meta.get("hold") and not meta.get("needs"): meta.setdefault("post_wake_mover", SESS[owner])      # a parked item is taken, when its wait ends, by its post-wake mover (the creator is no one's mover)
    if project: meta["project"] = project
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": "A fixture item.", "status": status, "updated": now - age, "state_updated": now - age,
                                                    "confirmed": now - age, "metadata": meta}))


ASK = "Decide: ship the thing on Friday? · Recommend: yes · Stakes: low · By: Fri"
OPTS = [{"label": "Ship it", "line": "Ship Friday.", "recommended": True}, {"label": "Hold it", "line": "Wait a week.", "recommended": False}]
# ---- Your move (needs holds decision or the old one-word kind: the owner is the mover) ----
item(1, "[home] ship the thing", age=6 * D, needs=["decision"], ask=ASK, options=OPTS, goal="The thing is shipped to everyone", next="Oliver: answer the ask above", owner="front")      # red
item(2, "[home] run the check", age=3 * D, needs=["decision"], next="Oliver: run `ssh box sala status` and send me the output", owner="front")                                          # amber, a command
item(3, "[home] a yes or no", age=1 * H, needs=["decision"], ask="Decide: use the cheaper plan? · Recommend: no · Stakes: low · By: Mon", next="Oliver: decide", owner="front")   # no colour, no options
item(4, "[home] open the link", age=2.5 * D, needs=["decision"], next="Oliver: open https://example.invalid/portal/setup and finish the form", owner="front")                      # amber, a link
item(5, "[home] has the party answered", age=30 * 60, needs=["decision"], ask="Decide: has Acme's reply arrived? · Options: arrived / not yet, ask again on <date> / drop",
     options=[{"label": "arrived", "line": "It came.", "recommended": False}, {"label": "not yet, ask again on <date>", "line": "Give the date in the box.", "recommended": True},
              {"label": "drop", "line": "No longer wanted.", "recommended": False}], then="team-back", next="team-back: read the reply", owner="front",
     woke={"what": "Acme's reply is due today", "to": "Oliver", "at": now - 30 * 60})                                                                                        # a relay come due
# ---- Agents at work ----
item(10, "[home] built by the back agent", age=1 * D, needs=["team-back"], next="**team-back**: write the code; then run the tests", owner="back")                                  # a plain item: no stored model field
item(11, "[home] handed over, not taken", age=10 * 60, needs=["home-other"], owner="other", mover="home-other", next="home-other: take it",
     handoff={"to": "home-other", "from": "home-front", "at": now - 10 * 60, "delivered_at": now - 9 * 60, "taken_at": None})
item(12, "[home] second job", age=2 * D, needs=["home-build"], owner="build", next="home-build: second job")
item(13, "[home] first job", age=4 * D, needs=["home-build"], owner="build", next="home-build: first job",
     handoff={"to": "home-build", "from": "home-front", "at": now - 4 * D, "taken_at": None})                                                                                           # a hand-off a builder has not taken, however old
item(14, "[home] woke up", age=20 * 60, needs=["team-back"], owner="back", mover="team-back", next="team-back: judge the news", woke={"what": "the wake day came", "to": "team-back", "at": now - 20 * 60})
item(15, "[home] recovery-asked hand-off", age=5 * H, needs=["home-other"], owner="other", mover="home-other", next="home-other: someone take it",
     handoff={"to": "home-other", "from": "home-front", "at": now - 5 * H, "taken_at": None, "recovery_at": now - 4 * H, "recovery_reason": "no builder"})
item(16, "[home] agent with no next", age=1 * H, needs=["team-back"], owner="back", next="")
item(17, "[home] the back agent's older touch", age=2 * D, needs=["team-back"], owner="back", next="team-back: slow job")
item(18, "[home] just confirmed, in its state three days", age=3 * D, needs=["home-build"], owner="build", next="home-build: still on it")
(T / "store/a/18.json").write_text(json.dumps({**json.loads((T / "store/a/18.json").read_text()), "updated": now - 60, "confirmed": now - 60}))      # a bare confirm a minute ago: the state clock stays three days old
# ---- Waiting ----
item(20, "[home] parked on his words", age=1 * D, hold=True, wake=day(3), cap_ok={"wake": day(3), "quote": "park it until Friday", "source": "board", "by": "Oliver"}, next="team-back: pick it up after")
item(21, "[home] blocked on another", age=1 * D, after=["a10"], next="team-back: continue once a10 is done")
item(22, "[home] anchor wait", age=1 * D, needs=["external"], wait_kind="anchor", wait_anchor="https://github.com/o/r/pull/9", wait_event="the PR merges", mover="team-back", wake=day(9), next="team-back: deploy it")
item(23, "[home] party relay", age=2 * D, needs=["external"], wait_kind="relay", wait_event="Acme's reply", ask_by=day(5), mover="team-back",
     chases=[{"at": now - D, "by": "team-back", "note": "mailed"}, {"at": now - 12 * H, "by": "team-back", "note": "mailed again"}], next="Oliver: nothing yet")
item(24, "[home] basis wait", age=2 * D, hold=True, wake=day(1), wait_basis={"text": "the vendor ships on " + day(2), "wake": day(1), "by": "team-back", "at": now - D}, next="team-back: review the release")
item(25, "[home] verifying", age=2 * D, state="verifying", proof="the dashboard shows green", end=day(2), needs=["team-back"], next="team-back: check the dashboard")
item(26, "[home] a wait with no date", age=4 * D, hold=True, next="team-back: someone must look")
# a Waiting row of each wait kind, with and without a watcher and a then-mover; an anchor wait whose anchor is only scoped to the item (anchors.json, no wait_anchor), and one with none at all
item(28, "[home] anchor wait, no anchor recorded", age=1 * D, needs=["external"], wait_kind="anchor", wait_event="the vendor answers", mover="team-back", wake=day(6), next="team-back: look again")
item(29, "[home] anchor wait, anchor scoped to the item", age=1 * D, needs=["external"], state="outside", party="Acme", wake=day(7), next="team-back: read the thread when it moves")
item(44, "[home] item wait with only its backstop date", age=1 * D, wait_kind="item", wake=day(5), mover="team-back", next="team-back: look at it then")
item(43, "[home] time wait, a long then-mover", age=1 * D, hold=True, wake=day(4), post_wake_mover="falcon-engineer-with-a-very-long-name", next="falcon-engineer-with-a-very-long-name: take it")
item(27, "[home] no project item", age=1 * D, project="", needs=["team-back"], owner="back", next="team-back: no project here")
# ---- items that store the model's own fields ----
item(50, "[home] a step with a command", age=1 * D, state="your-step", step="run the one line `sala op reauth box-a --from me --words \"go\"` and say done", needs=["team-back"], owner="front", next="team-back: check it")
item(51, "[home] a step typed in a pane", age=1 * D, state="your-step", step="! sala reauth box-a", needs=["team-back"], owner="front", next="team-back: check it")
item(52, "[home] a step with a link", age=1 * D, state="your-step", step="Sign in at https://example.invalid/login/now and say done", needs=["team-back"], owner="front", next="team-back: check it")
item(55, "[home] a step with two links", age=1 * D, state="your-step", step="Compare https://example.com/p/aaa with https://example.com/p/bbb and say done", needs=["team-back"], owner="front", next="team-back: check it")
item(56, "[home] a step with a command and a link", age=1 * D, state="your-step", step="Open https://example.com/p/aaa then run `sala op reauth box-a` and say done", needs=["team-back"], owner="front", next="team-back: check it")
item(57, "[home] a step with a lone-word backtick", age=1 * D, state="your-step", step="Set the mode to `default` and say done", needs=["team-back"], owner="front", next="team-back: check it")
item(53, "[home] a step of plain words", age=1 * D, state="your-step", step="Call the office and say done", owner="front", next="team-back: check it")
item(54, "[home] a yes or no with its options", age=45 * 60, needs=["decision"], ask="Decide: use the cheaper plan? · Recommend: yes · Stakes: low · By: Mon", next="Oliver: decide", owner="front",
     options=[{"label": "Approve", "line": "Take the cheaper plan.", "recommended": True}, {"label": "Decline", "line": "Keep the current plan.", "recommended": False}])   # Approve and Decline stored by its owner
item(40, "[home] stored mover Oliver", age=4 * D, mover="Oliver", then="team-back", next="Oliver: look at the draft", owner="front")                                                    # alive, the owner the mover, no needs
item(41, "[home] stored time wait", age=1 * D, wait_kind="time", wake=day(2), post_wake_mover="home-other", next="home-other: take it after the wake", owner="front")                    # waiting, the post-wake mover stored
# ---- Completed ----
item(30, "[home] shipped last week", status="completed", age=2 * D, outcome="done", reason="the thing shipped on Friday", needs=[])
item(31, "[home] closed with no outcome", status="completed", age=3 * D, needs=[])
item(33, "[home] " + "a very long title that must wrap onto more lines instead of being cut off at some arbitrary point in the middle of a word " * 2 + 'and "quoted" <i>markup</i> & more', status="completed", age=4 * D, outcome="dropped",
     reason='the close message is long too and says "quoted" things <b>and markup</b> that the page must show whole in the tooltip even though the row cuts it at one line ' * 2, needs=[])      # the board item
item(32, "[home] closed long ago", status="completed", age=20 * D, outcome="done", needs=[])
(T / "store/a/32.json").write_text(json.dumps({**json.loads((T / "store/a/32.json").read_text()), "updated": now - 20 * D}))

fails, ran = [], []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web.ui import render
from stackshot.web import home; from stackshot.model import model; from stackshot.waits import handoff; from stackshot.waits import waiting

b = render.Board(str(T / "store"), now=NOW)
b.provision = [("home-box", True)]
h = b.html()
def section(sid, text=h):
    i = text.find(f'<section id="{sid}">')
    return text[i:text.find("</section>", i)] if i >= 0 else ""
def rows(sec):
    # each row's body without its project line (the line above the title, checked on its own below), so the checks of the row's shape start at the title line
    return [(i, re.sub(r'^<div class="ir-proj">.*?</div>', "", body, count=1)) for i, body in re.findall(r'<li class="irow hrow" id="task-a-(\d+)" data-st="[a-z]+">(.*?)</li>', sec, re.S)]
def row_of(sec, n):
    return dict(rows(sec)).get(str(n), "")
def ids(sec):
    return [i for i, _ in rows(sec)]
YM, AW, WL = section("your-move"), section("agents-at-work"), section("waiting-list")
OPEN = {1, 2, 3, 4, 5, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 40, 41, 43, 44, 50, 51, 52, 53, 54, 55, 56, 57}

# ---- the five counts and the lists ----
import html as _html
CARD = r'<a class="hcard[^"]*" href="([^"]+)"[^>]*><b>(\d+)</b><span>(.*?)(?: <i class="hnew[^"]*">.*?</i>)?</span></a>'
cards_of = lambda nav: [(href, n, _html.unescape(re.sub(r"<[^>]+>", "", lab))) for href, n, lab in re.findall(CARD, nav)]
cn = h[h.find('<nav class="hcards"'):h.find("</nav>", h.find('<nav class="hcards"'))]
ND = len(render.Board(str(T / "store"), now=NOW).done)
check("cards: one card per count, in order Your move, On agent, Queued for release, Waiting, Closed, each the number over its label and a link to its fold or page",
      cards_of(cn) == [("#your-move", str(len(ids(YM))), "Your move"), ("#agents-at-work", str(len(ids(AW))), "On agent"), ("#queued-release", "0", "Queued for release"),
                       ("#waiting-list", str(len(ids(WL))), "Waiting"), ("/closed", str(ND), "Closed")], cn)
check("cards: the Closed card counts the items closed in the last 14 days (the Last 14 days section of the Closed page), with no new badge while no close of an agent is uncleared",
      ND > 0 and '<a class="hcard" href="/closed"' in cn and "hnew" not in cn and '<a class="hcard call" href="#your-move"' in cn and cn.count("<a ") == 5 and "hcount" not in h)
# board.md and the brief count and list by the same three lists as the home page: the same numbers, the same items, from the same store (the root renderer draws the files, the ui one keeps a copy)
from stackshot.web import render as root_render
_card = {lab: int(n) for _h, n, lab in cards_of(cn)}
_want = (_card["Your move"], _card["On agent"] + _card["Queued for release"], _card["Waiting"])      # agents = On agent and Queued for release (an agent's item either way)
_hm = lambda md: re.search(r"_(\d+) open · (\d+) your move · (\d+) on agents · (\d+) waiting · machines:", md)
_bl = lambda br: re.fullmatch(r"Board: (\d+) open \((\d+) your move, (\d+) on agents, (\d+) waiting\), .*", br.splitlines()[0])
_al = lambda br: re.search(r"(?m)^  alive (\d+) \(your move (\d+), agents (\d+)\) · waiting (\d+)$", br)
_sec = lambda md, title: md[md.find(f"\n## {title}\n"):][:md[md.find(f"\n## {title}\n") + 4:].find("\n## ") + 4] if f"\n## {title}\n" in md else ""
_sids = lambda md, title: sorted(re.findall(r'<a id="task-a-(\d+)"></a>', _sec(md, title)), key=int)
for _name, _B in (("root", root_render.Board(str(T / "store"), now=NOW)), ("ui", render.Board(str(T / "store"), now=NOW))):
    _md, _br = _B.markdown(), _B.brief()
    _m, _l, _a = _hm(_md), _bl(_br), _al(_br)
    check(f"counts ({_name} renderer): board.md's head says the home page's numbers: open, your move, on agents, waiting",
          _m and tuple(int(x) for x in _m.groups()) == (sum(_want),) + _want, (_m and _m.group(0), _want, _card))
    check(f"counts ({_name} renderer): the brief's first line and its alive / waiting line say the same numbers",
          _l and tuple(int(x) for x in _l.groups()) == (sum(_want),) + _want and _a and tuple(int(x) for x in _a.groups()) == (_want[0] + _want[1],) + _want[:2] + (_want[2],), (_br.splitlines()[0], _a and _a.group(0)))
    check(f"counts ({_name} renderer): board.md's sections Your move, Waiting and On agents hold the home page's rows, each item once",
          _sids(_md, "Your move") == sorted(ids(YM), key=int) and _sids(_md, "Waiting") == sorted(ids(WL), key=int)
          and _sids(_md, "On agents") == sorted(ids(AW) + ids(section("queued-release")), key=int), (_sids(_md, "Your move"), ids(YM)))
    _seen = _md[:_md.find("## Machines")] + "".join(f"\n## {t}\n" for t in re.findall(r"(?m)^## (.*)$", _md)) + "\n" + "\n".join(l for l in _br.splitlines() if re.match(r"(Board:|  alive|  states:)", l)) + "\n" + "".join(f"\n{l[:14]}" for l in _br.splitlines()) + "\n"
    _hit = re.search(r"need your call|on others|\n## (Needs your call|On others|On agent)\n|\n  states: |\n  (your call|on others): |verifying", _seen)
    check(f"counts ({_name} renderer): none of the old lane words or the seven state words is in the head, the sections' titles or the brief's counting lines", not _hit, _hit and _seen[max(_hit.start() - 80, 0):_hit.end() + 80])
# a Waiting row whose model carries no wait (home.wait_words is "") gets no " · on " in the brief's waiting line
assert home.wait_words(model.Model(model.WAITING)) == "" and home.wait_words(model.Model(model.ALIVE)) == ""
for _name, _cls in (("root", root_render.Board), ("ui", render.Board)):
    _nb = _cls(str(T / "store"), now=NOW)
    _wl0 = [l for l in _nb.brief().splitlines() if l.startswith("  waiting: ")]
    for _r, _m in _nb.home_pairs()[home.WAITING]: _r["_mod"] = model.Model(model.WAITING)       # every waiting row read as waiting with no wait
    _wl = [l for l in _nb.brief().splitlines() if l.startswith("  waiting: ")]
    check(f"waiting line ({_name} renderer): a waiting row with a wait names its kind, one with none carries no ' · on ' suffix at all",
          _wl0 and all(" · on " in l for l in _wl0) and len(_wl) == len(_wl0) and all(" · on" not in l and l.endswith("]") for l in _wl), (_wl0, _wl))
# the Closed card's new badge and the Closed page's New section read one set, the uncleared closes. Mixed data: a done close, a 20-day-old one (past the
# Last 14 days section, still uncleared, so in New), a close with no outcome, an open item's stale record, a cleared one.
from stackshot.web import landed as _ld
try:
    _ld.record("a30", now - 2 * D, "done", by="team-back", project="projects/alpha"); _ld.record("a32", now - 20 * D, "done", by="team-back", project="projects/alpha")
    _ld.record("a31", now - 3 * D, "done", by="team-back", project="projects/alpha"); _ld.record("a1", now - 1 * D, "done", by="team-back", project="projects/alpha")
    _ld.record("a33", now - 4 * D, "done", by="team-back", project="projects/alpha"); _ld.clear([_ld.key("a33", now - 4 * D)], now=now)
    def landed_both():
        bb = render.Board(str(T / "store"), now=NOW); hh = bb.html(); cc = hh[hh.find('<nav class="hcards"'):hh.find("</nav>", hh.find('<nav class="hcards"'))]
        new = re.findall(r'<i class="hnew[^"]*">(\d+)<em> new</em></i>', cc)
        return (int(new[0]) if new else 0), len(re.findall(r'<li class="irow lrow"', bb.landed_html())), cc
    n_card, n_lines, cc = landed_both()
    check("cards: the Closed card's new badge counts exactly the lines of the New section on the Closed page, 2 for mixed data (a close with no outcome, a record of an open item and a cleared one are on neither), not the card's own number",
          n_card == n_lines == 2 and "2 new: closed by an agent, not cleared yet" in cc and cards_of(cc)[-1] == ("/closed", str(ND), "Closed"), (n_card, n_lines, cc))
    _ld.clear([_ld.key("a30", now - 2 * D)], now=now); n_card, n_lines, cc = landed_both()
    check("cards: after one Clear both read 1; after Clear all both read 0 and the badge is gone", n_card == n_lines == 1 and (_ld.clear(None, now=now), landed_both())[1][:2] == (0, 0)
          and "hnew" not in landed_both()[2] and cards_of(landed_both()[2])[-1] == ("/closed", str(ND), "Closed"))
finally:
    for _g in ("a30", "a31", "a32", "a33", "a1"): _ld.forget(_g)
check("cards: the header runs title, the rendered line, the cards, the search bar; the lists follow the header",
      h.find("<header") < h.find('<h1 class="site">') < h.find('<p class="rline">') < h.find('<nav class="hcards"') < h.find("</nav>") < h.find('class="sbox"') < h.find("</header>") < h.find('<section id="your-move">') < h.find('<section id="agents-at-work">') < h.find('<section id="queued-release">') < h.find('<section id="waiting-list">'), cn)
check("cards: the old plain count links are gone (nav.hcounts, a.hcount)", 'class="hcounts"' not in h and "a.hcount" not in h and "nav.hcounts" not in h)
check("lists: every open item is in exactly one list", sorted(map(int, ids(YM) + ids(AW) + ids(WL))) == sorted(OPEN) and len(set(ids(YM) + ids(AW) + ids(WL))) == len(OPEN), (ids(YM), ids(AW), ids(WL)))
check("lists: Your move holds the fourteen items the owner moves, Waiting the twelve waits, Agents at work the rest", set(map(int, ids(YM))) == {1, 2, 3, 4, 5, 40, 50, 51, 52, 53, 54, 55, 56, 57} and set(map(int, ids(WL))) == {20, 21, 22, 23, 24, 25, 26, 28, 29, 41, 43, 44}
      and set(map(int, ids(AW))) == {10, 11, 12, 13, 14, 15, 16, 17, 18, 27}, (ids(YM), ids(AW), ids(WL)))
check("lists: a closed item is in none of them", all(f"task-a-{n}" not in YM + AW + WL for n in (30, 31, 32)))
check("lists: the three are folds under their own keys; only Your move is open, Agents at work and Waiting closed", '<section id="your-move"><details class="fold" data-fold="your-move" open><summary><h2>' in h
      and all(f'<section id="{s}"><details class="fold" data-fold="{s}"><summary><h2>' in h for s in ("agents-at-work", "waiting-list")))
_folds = re.findall(r'<details class="fold"[^>]*>', h)
check("folds: in the main column Your move and Queued for release are open (On agent and Waiting closed); the side panel's Machines, Runners, Anchor hub, Audit and Projects are open",
      {re.search(r'data-fold="([^"]+)"', f).group(1) for f in _folds if " open" in f} == {"your-move", "queued-release", "machines", "runners", "anchorhub", "audit-panel", "projects-panel"}
      and {re.search(r'data-fold="([^"]+)"', f).group(1) for f in _folds if " open" not in f} == {"agents-at-work", "waiting-list"}, _folds)
_pf = re.findall(r'<details class="fold"[^>]*>', h[h.find('<aside id="panel"'):h.find("</aside>")])
check("folds: every panel section renders open, whatever the visit before (the markup is the state, no stored key is read for it)",
      len(_pf) == 5 and all(f.endswith(" open>") for f in _pf), _pf)
_hj = h[h.find('<script>(function(){try{["for-you"'):]
_hj = _hj[:_hj.find("</script>")]
import _colors as _C1; _h_full, h = h, _C1.without_colortool(h)      # the color tool's library (shared/colortool.js) watches data-theme with a MutationObserver: the next check reads the page without its script blocks
check("folds: the home page remembers no fold state: its script neither reads nor writes localStorage, has no toggle listener, and removes the old section keys; no pre-paint fold script in the head",
      _hj and "localStorage.getItem" not in _hj and "localStorage.setItem" not in _hj and "'toggle'" not in _hj and "localStorage.removeItem('stackshot.fold.'+k)" in _hj
      and all(f'"{k}"' in _hj for k in ("for-you", "your-move", "agents-at-work", "waiting-list", "by-project", "completed", "machines", "anchorhub"))
      and render._FOLD_HEAD not in h and render._FOLD_JS not in h and "localStorage.setItem('stackshot.fold." not in h and "MutationObserver" not in h[:h.find("</head>")], _hj[:300])
h = _h_full
check("folds: a hash to a section, or to a row inside a closed one, opens it on load and on hashchange",
      "if(el.matches&&el.matches('section')){var s=el.querySelector('details.fold');if(s&&!s.open)s.open=true}" in _hj and "el.closest&&el.closest('details.fold')" in _hj
      and "go(location.hash,false)" in _hj and "addEventListener('hashchange'" in _hj and "addEventListener('load'" in _hj, _hj[:300])
check("folds: once a hash has opened its section (on load, on hashchange, on a card's click) the home script drops the hash from the address, so a reload shows only Your move open; the item and project pages' script keeps the hash",
      "history.replaceState(null,'',location.pathname+location.search)" in _hj and "var go0=go;go=function(h,scroll){go0(h,scroll);if(scroll&&location.hash)" in _hj
      and _hj.find("history.replaceState") > _hj.find("function go(h,scroll)") and _hj.find("history.replaceState") < _hj.find("go(location.hash,false)")
      and "replaceState" not in render._FOLD_JS and "replaceState" not in render._FOLD_HASH and "replaceState" not in render._FOLD_GO, _hj[:700])
check("lists: items that store the model's fields (a mover, a time wait with its mover, who picks it up) land by them", "task-a-40" in YM and f"home-other picks it up" in re.sub(r"<[^>]+>", "", row_of(WL, 41)), row_of(WL, 41))
check("lists: a model-less item (needs a session, no stored mover) is Agents at work with its needs session as the mover, by model.derive", "task-a-10" in AW and "team-back" in row_of(AW, 10))

# ---- every row ----
r1 = row_of(YM, 1)
check("row: the goal (the subject, its tag dropped) links the item page", '<a class="ir-link" href="/items/a1" target="_blank" rel="noopener"><span class="ir-id">a1</span> <span class="hgoal">ship the thing</span></a>' in r1, r1[:300])
# the item's number in the row's first line, as the item page's title shows it, linking the item page
_src = next(r for r in b.rows if r["gid"] == "a1")
_numrow = lambda gid: b.home_row(dict(_src, gid=gid, L=gid[0], id=gid[1:]), b.mod_of(_src), home.YOUR_MOVE)
_n48 = _numrow("g48"); _nl3 = _numrow("l3")
check("row: the item's number opens the top line, linked to the item page, the title after it: an issue-numbered item reads #48 at /items/48",
      re.match(r'<li class="irow hrow" id="task-g-48" data-st="you"><div class="ir-top"><span class="ir-title"><a class="ir-link" href="/items/48" target="_blank" rel="noopener"><span class="ir-id">#48</span> <span class="hgoal">', _n48), _n48[:400])
check("row: an item with no issue number shows what the item page shows: an old id as it is (a1 at /items/a1), a temporary one board-tmp-<machine>#3",
      '<a class="ir-link" href="/items/a1" target="_blank" rel="noopener"><span class="ir-id">a1</span> <span class="hgoal">' in r1
      and re.search(r'<a class="ir-link" href="/items/board-tmp-[a-z0-9-]*3"[^>]*><span class="ir-id">board-tmp-[a-z0-9-]*#3</span> <span class="hgoal">', _nl3) and 'class="ir-id"' in row_of(WL, 20) and 'class="ir-id"' in row_of(AW, 10), (r1[:300], _nl3[:300]))
check("row: the number is the one the item page's title shows, for every row of the three lists", all(
      f'<a class="ir-link" href="/items/a{n}" target="_blank" rel="noopener"><span class="ir-id">a{n}</span>' in body and re.search(rf'<span class="hid">a{n}</span>', b.item_html(f"a{n}")) for n, body in rows(YM) + rows(AW) + rows(WL)))
r10 = row_of(AW, 10)
check("row: the immediate next step is the first next line with its `<mover>:` prefix (and bold marks) stripped", 'class="hnext">write the code' in r10 and "team-back: write" not in r10 and "**" not in r10, r10)
check("row: the mover is a session linked to the fleet tool while its pane lives", '<a class="hwho" href="https://sala.example.org/#s=team-back"' in r10, r10)
check("row: the top line is the number and the goal, linking the item page, and the age; the mover is under it, then the step alone",
      re.fullmatch(r'<div class="ir-top"><span class="ir-title"><a class="ir-link"[^>]*><span class="ir-id">a10</span> <span class="hgoal">[^<]*</span></a></span><span class="tip ir-age" data-ts="\d+"[^>]*>[^<]*</span></div>'
                   r'<div class="ir-who"><a class="hwho" href="[^"]*#s=team-back"[^>]*>team-back</a></div><div class="ir-det"><span class="hnext">write the code[^<]*</span></div>', r10, re.S), r10)
check("row: no gbrain page label or old project class is drawn on any row", "hproj" not in YM + AW + WL and "hwhom" not in YM + AW + WL and "gbrain" not in YM + AW + WL, re.findall(r'class="hproj"', YM + AW + WL)[:2])
# the project's name above the title (the owner's pick on the row format): a small quiet line first in the row, a link to the project's page, on every home row whose item has a project
_raw = lambda sec, n: (re.search(rf'<li class="irow hrow" id="task-a-{n}" data-st="[a-z]+">(.*?)</li>', sec, re.S) or [None, ""])[1]
check("row: a row with a project opens with a project line above the title, a link to the project's page with the project's name",
      _raw(AW, 10).startswith('<div class="ir-proj"><a class="pjl" href="/projects/alpha">home/Alpha</a></div><div class="ir-top">') and _raw(YM, 1).startswith('<div class="ir-proj"><a class="pjl" href="/projects/alpha">home/Alpha</a></div><div class="ir-top">'), (_raw(AW, 10)[:200], _raw(YM, 1)[:200]))
check("row: the project line is on every row of the three lists but item 27's, which has no project and starts at its title line",
      all(b_.startswith('<div class="ir-proj">') for sec_ in (YM, AW, WL) for i_, b_ in re.findall(r'<li class="irow hrow" id="task-a-(\d+)" data-st="[a-z]+">(.*?)</li>', sec_, re.S) if i_ != "27")
      and _raw(WL + AW + YM, 27).startswith('<div class="ir-top">'), [i_ for i_, b_ in re.findall(r'<li class="irow hrow" id="task-a-(\d+)" data-st="[a-z]+">(.*?)</li>', YM + AW + WL, re.S) if not b_.startswith('<div class="ir-proj">')])
check("row: the project line holds the name and nothing else (the age, the who line and the detail are not in it)", all(re.fullmatch(r'<a class="pjl" href="/projects/[a-z]+">[^<]+</a>', m_) for m_ in re.findall(r'<div class="ir-proj">(.*?)</div>', YM + AW + WL)) and 'class="ir-proj"' in YM, None)
# the card's left edge by list: orange Your move, blue On agent, grey Waiting (purple Queued for release is on its own list below)
check("row: the card's edge is the list's color: data-st you on Your move, agent on On agent, wait on Waiting",
      set(re.findall(r'class="irow hrow" id="task-a-\d+" data-st="([a-z]+)"', YM)) == {"you"} and set(re.findall(r'class="irow hrow" id="task-a-\d+" data-st="([a-z]+)"', AW)) == {"agent"}
      and set(re.findall(r'class="irow hrow" id="task-a-\d+" data-st="([a-z]+)"', WL)) == {"wait"}, None)
check("row: the age is a stamp the page script keeps current (data-ts), since the state began", re.search(r'<span class="tip ir-age" data-ts="%d"' % int(now - D), r10), r10)
check("row: an item with no next line says so", "no next step on the item" in row_of(AW, 16))
# a Your move row has no who line, since there it is always him; Agents at work and Waiting rows name the mover (or the post-wake mover) on theirs
check("row: a Your move row has no who line (the woke note under it keeps its own mover); Agents at work and Waiting rows all have one", all('class="ir-who"' not in b_ for _i, b_ in rows(YM)) and "sala.example.org/#s=Oliver" not in YM
      and all('class="ir-who"' in b_ for _i, b_ in rows(AW) + rows(WL)), YM[:300])
check("row: Agents at work rows still name the mover on their who line", 'class="hwho' in row_of(AW, 10).split('class="ir-det"')[0] and 'class="hwho' in row_of(AW, 11).split('class="ir-det"')[0], [row_of(AW, 10).split('class="ir-det"')[0], row_of(AW, 11).split('class="ir-det"')[0]])
check("row: a mover with no live pane is plain text", b.home_mover("home-gone") == "home-gone" or ("home-gone" in b.home_mover("home-gone") and "<a " not in b.home_mover("home-gone")), b.home_mover("home-gone"))
check("row: an Agents at work or Waiting row is the top line (number, goal, age), then the who line, then the detail, in that order, and no action area", all(re.fullmatch(r'<div class="ir-top">.*?</div><div class="ir-who">.*?</div><div class="ir-det">.*</div>', body, re.S) and 'class="ir-act"' not in body for _i, body in rows(AW) + rows(WL)))
# a Your move row is one top line, the number, the title, the age, in that order; the step and the notes under it in the detail
_YTOP = re.compile(r'<li class="irow hrow" id="task-a-\d+" data-st="you"><div class="ir-top"><span class="ir-title"><a class="ir-link" href="[^"]*" target="_blank" rel="noopener"><span class="ir-id">[^<]*</span> <span class="hgoal">([^<]*)</span></a></span>'
                   r'<span class="tip ir-age( amber| red)?" data-ts="\d+"[^>]*>[^<]*</span></div><div class="ir-det">.*', re.S)
check("Your move rows: one top line in the order #id, title, age; the age keeps its amber and red classes; nothing but the detail between that line and the end of the guide",
      rows(YM) and all(_YTOP.fullmatch('<li class="irow hrow" id="task-a-%s" data-st="you">' % i_ + b_) and b_.count('class="ir-top"') == 1 and 'class="ir-who"' not in b_ for i_, b_ in rows(YM)),
      [i_ for i_, b_ in rows(YM) if not _YTOP.fullmatch('<li class="irow hrow" id="task-a-%s" data-st="you">' % i_ + b_)])
_ytop = re.search(r'<div class="ir-top">.*?</span></div>', row_of(YM, 1), re.S).group(0)
check("Your move rows: the top line holds the number, the title and the age in that order and nothing else, and the age of row 1 (past five days) is red", re.findall(r'class="(ir-id|hgoal|tip ir-age[^"]*)"', _ytop) == ["ir-id", "hgoal", "tip ir-age red"], _ytop)
# the board item review: a subject with & < > " is escaped in the link text
_r1, _m1 = next((r_, m_) for r_, m_ in b.home_pairs()[home.YOUR_MOVE] if str(r_["gid"]) == "a1")
_yx = b.home_row({**_r1, "subject": '[home] R&D <b>"q"</b> > 1'}, _m1, home.YOUR_MOVE)
check("Your move rows: a subject with & < > \" is escaped in the link text",
      '<span class="hgoal">R&amp;D &lt;b&gt;&quot;q&quot;&lt;/b&gt; &gt; 1</span>' in _yx and "<b>" not in _yx and "R&D" not in _yx, _yx[:500])
_css0 = h[h.find("<style"):h.find("</style>")]
# ---- Your move: ages ----
cls = lambda n: re.search(r'<span class="tip ir-age( amber| red)?"', row_of(YM, n)).group(1)
check("Your move: red past five days, amber past two, nothing before", (cls(1), cls(2), cls(4), cls(3)) == (" red", " amber", " amber", None), (cls(1), cls(2), cls(4), cls(3)))
check("Your move: oldest first", ids(YM) == ["1", "40", "2", "4", "50", "51", "52", "53", "55", "56", "57", "3", "54", "5"], ids(YM))
check("Your move: no colour on Agents at work or Waiting rows, whatever the age", "ir-age amber" not in AW + WL and "ir-age red" not in AW + WL and re.search(r'class="tip ir-age"', row_of(AW, 12)))
check("home.age_class: the edges (exactly two and five days are not past them)", (home.age_class(2 * D), home.age_class(2 * D + 1), home.age_class(5 * D), home.age_class(5 * D + 1)) == ("", "amber", "amber", "red"))

# ---- Your move: the ask forms ----
check("ask: a decision shows its question in place of the next step, and the mover", 'class="hnext hq">ship the thing on Friday?' in r1 and "answer the ask above" not in r1, r1)
form = lambda r: re.search(r'<form class="hanswer".*?</form>', r, re.S).group(0)
f1 = form(r1)
_CARD = r'<label class="acard"><input type="radio" name="choice" value="([^"]+)"><span class="adot" aria-hidden="true"></span><span class="abody"><span class="alab">(?:<span class="akey">[A-Z]</span>)?([^<]*)</span>( <span class="badge rec">recommended</span>)?<span class="adesc">([^<]*)</span></span></label>'
check("ask: one card per option, the recommended one first and marked, each with its line, in the item page's markup (radio name=choice)",
      [(v, rec != "", d) for v, _l, rec, d in re.findall(_CARD, f1)] == [("Ship it", True, "Ship Friday."), ("Hold it", False, "Wait a week.")], f1)
check("ask: the cards, the note box and Send, posting to the item's answer route; the form is drawn from the first paint (not hidden), its Send disabled, with no token (the script fills it and enables Send), and the item page is linked by the row's title",
      '<form class="hanswer" data-cards method="post" action="/items/a1/answer" data-gid="a1"><input type="hidden" name="token" value="">' in f1 and '<textarea id="atext-a1" name="text"' in f1 and 'name="act" value="answer" disabled>Send</button>' in f1 and "Send as my answer" not in f1
      and " hidden" not in f1.split(">", 1)[0] and f1.count("<button") == 1 and f1.count(" disabled>") == 1
      and '<a class="ir-link" href="/items/a1"' in r1 and "token\" value=\"\"" in f1, f1)
f3 = form(row_of(YM, 3))
check("ask: an ask with no options has no Approve and no Decline; it gets Yes (recommended, first) and No, and the box with one Send, which posts act=answer",
      "Approve" not in f3 and "Decline" not in f3 and "Done" not in f3 and "Send as my answer" not in f3
      and [(v, rec != "", d) for v, _l, rec, d in re.findall(_CARD, f3)] == [("Yes", True, "Answer yes."), ("No", False, "Answer no.")]
      and re.findall(r'<button [^>]*name="act" value="([^"]+)" disabled>([^<]*)</button>', f3) == [("answer", "Send")], f3)
f54 = form(row_of(YM, 54))
check("ask: Approve and Decline stored as the item's options give exactly those two cards, the recommended one first",
      re.findall(r'name="choice" value="([^"]+)"', f54) == ["Approve", "Decline"] and re.findall(r'<button [^>]*name="act" value="([^"]+)" disabled>([^<]*)</button>', f54) == [("answer", "Send")] and "Send as my answer" not in f54 and "Done" not in f54, f54)
check("ask: no Yes or No on a row with stored options (the owner's own or Approve and Decline)",
      all('value="Yes"' not in x and 'value="No"' not in x for x in (f1, f54)), (f1, f54))
check("ask: the box has no corner grip (resize:none) and a bottom-edge handle after it: a horizontal separator you can focus, with its script and style on the page",
      re.search(r'<div class="abox"><textarea id="atext-a1" name="text".*?</textarea><div class="rsz" role="separator" aria-orientation="horizontal" tabindex="0" aria-controls="atext-a1" aria-label="Resize the answer box"></div></div>', f1, re.S) is not None
      and "resize:none}form.hanswer textarea:focus-visible" in b._css() and "resize:vertical" not in b._css() and ".rsz{" in b._css() and "cursor:row-resize" in b._css()
      and "@media(pointer:coarse){.rsz{display:none}.abox" in b._css() and "setPointerCapture" in h and "'ArrowDown'" in h and "stackshot:swapped',init" in h, f1)
check("in place: a handle that has the focus, or is being dragged, holds the swap like a box with text (busy() tests .rsz and .rsz.drag), so the drag never lands on a detached box",
      "a.matches('.rsz')" in render._LIVE_JS and "document.querySelector('.rsz.drag')" in render._LIVE_JS, render._LIVE_JS[render._LIVE_JS.find("function busy"):][:400])
# the scripts parse (a string match cannot tell): node's syntax check, where the box has node (the CI runner has no DOM library to run them in; the behaviour is tests/phone_width_check.py's, in a browser)
import shutil, subprocess
if shutil.which("node"):
    for _n, _js in (("_ABOX_JS", render._ABOX_JS), ("_LIVE_JS", render._LIVE_JS)):
        _f = T / f"resize-{_n}.js"; _f.write_text(_js, encoding="utf-8")
        _p = subprocess.run(["node", "--check", str(_f)], capture_output=True, text=True)
        check(f"{_n} is valid JavaScript (node --check)", _p.returncode == 0, _p.stderr[:400])
r5 = row_of(YM, 5)
f5 = form(r5)
check("ask: a relay come due shows its three cards in the stored order, lettered A, B, C, the not-yet one marked recommended, its question as the line", re.findall(r'name="choice" value="([^"]+)"', f5) == ["A · arrived", "B · not yet, ask again on &lt;date&gt;", "C · drop"] and re.findall(r'<span class="akey">([A-Z])</span>[^<]*</span> <span class="badge rec">', f5) == ["B"]
      and "has Acme's reply arrived?" in r5.split("hanswer")[0] and "Options" not in r5.split("hanswer")[0], r5)
r2 = row_of(YM, 2)
check("ask: a step shows its command in one block with a copy button, and the line says so", '<div class="cmd"><pre><code>ssh box sala status</code></pre><button type="button" class="b copy"' in r2 and "the command below" in r2 and "hanswer" not in r2, r2)
r4 = row_of(YM, 4)
check("ask: a step with a link and no command shows the link inline, in no code block", 'href="https://example.invalid/portal/setup"' in r4 and '<div class="cmd">' not in r4 and "<pre>" not in r4, r4)
check("ask: Agents at work and Waiting rows carry no form", "hanswer" not in AW + WL and "<textarea" not in AW + WL)
check("ask: nothing on the lists pushes or sends: the only forms are the Your move answer forms (the owner submits them), no script sits in a row", all(f.startswith('<form class="hanswer') for f in re.findall(r"<form[^>]*>", YM + AW + WL)) and "<script" not in YM + AW + WL)
check("ask: the page script asks for tokens by GET and shows only the forms it gets one for", "fetch('/answer-tokens?ids='" in h and "f.hidden=false" in h and "stackshot:swapped" in h and "button.copy" in h)

# ---- Agents at work ----
check("Agents at work: oldest first by the age the row shows (the mover's name does not sort; a bare confirm does not move a row; items of one age keep the board's id order)",
      ids(AW) == ["13", "18", "12", "17", "10", "27", "15", "16", "14", "11"], ids(AW))
_ages = [home.since(r, m, render.same_ref) for r, m in b.home_pairs()[home.AGENTS]]
check("Agents at work: the order is exactly the order of the times the rows are drawn from (home.since), never going up", _ages == sorted(_ages) and _ages[0] == now - 4 * D, _ages)
check("Agents at work: the item just confirmed (its `updated` a minute ago, its state three days old) sits by its state's age, behind the four-day row and ahead of the two-day ones",
      ids(AW).index("13") < ids(AW).index("18") < ids(AW).index("12"), ids(AW))
check("Agents at work: the mover does not sort: one agent's rows are not grouped (team-back, home-other, team-back, home-other down the list)",
      (lambda mv: any(mv[k] != mv[k + 1] and mv[k] in mv[k + 2:] for k in range(len(mv) - 2)))([m.mover for _r, m in b.home_pairs()[home.AGENTS]]), [(r["gid"], m.mover) for r, m in b.home_pairs()[home.AGENTS]])
r11 = row_of(AW, 11)
check("Agents at work: a hand-off not yet taken shows 'handed to X, not yet taken' on its who line", '<div class="ir-who"><span class="attn">handed to <a class="hwho"' in r11 and "not yet taken</span>" in r11, r11)
check("Agents at work: an old hand-off the builder has not taken shows 'not yet taken' like any other (no rank queue exempts it)", "not yet taken</span>" in row_of(AW, 13), row_of(AW, 13))
check("Agents at work: a hand-off whose recovery was asked of the fleet's builder shows no stuck line (the state is retired); the row is the item's own", "stuck" not in row_of(AW, 15) and "nobody can take it" not in row_of(AW, 15) and "recovery-asked hand-off" in row_of(AW, 15))
check("Agents at work: woke shows 'woke: <what> → <mover>' until its mover writes", '<div class="hnote">woke: the wake day came → <a class="hwho"' in row_of(AW, 14), row_of(AW, 14))
check("Your move: a relay's woke line shows with Oliver as the mover", '<div class="hnote">woke: Acme&#x27;s reply is due today → <span class="hwho own">Oliver</span></div>' in r5, r5)

# ---- Waiting ----
w = lambda n: row_of(WL, n)
# a Waiting row: the top line (number, title, the end date), the who line ("then <who>", "watched by <what>" when something does watch, "set by <who>" when the wait was set by someone), and the detail: what it waits on with the backstop,
# then the next step after the wait on its own span
WROW = re.compile(r'<div class="ir-top">.*?</div><div class="ir-who">(.*?)</div><div class="ir-det"><span class="hwait">(.*?)</span>(<span class="hnext hafter">.*?</span>)?</div>$', re.S)
plain = lambda x: _html.unescape(re.sub(r"<[^>]+>", "", x))
parts = lambda n: (lambda m: {"ok": bool(m), "who": m.group(1) if m else "", "wait": m.group(2) if m else "", "step": (m.group(3) or "") if m else "", "age": (re.search(r'<span class="tip ir-age[^"]*"[^>]*>([^<]*)</span>', w(n)) or [0, ""])[1]})(WROW.search(w(n)))
txt = lambda n: plain(parts(n)["wait"]) if parts(n)["ok"] else "NO ROW %s: %s" % (n, w(n)[:300])
rt = lambda n: plain(parts(n)["who"]) if parts(n)["ok"] else "NO ROW %s" % n
check("Waiting rows: every row is the top line (number, title, end date), the who line, the wait (what it waits on), the next step after the wait",
      all(parts(int(i))["ok"] for i in ids(WL)) and all(w(int(i)).count('class="ir-top"') == 1 and w(int(i)).count('class="ir-who"') == 1 and w(int(i)).count('class="hwait"') == 1 and w(int(i)).count('class="hnext hafter"') == 1 for i in ids(WL)), [i for i in ids(WL) if not parts(int(i))["ok"]])
check("Waiting rows: 'picks it up' and 'watched by' are on the who line, not in the wait; the wait text itself says what it waits on (and the backstop), not who",
      all(re.search(r" (picks|to pick) it up", rt(int(i))) for i in ids(WL)) and all("watched by" not in txt(int(i)) and "picks it up" not in txt(int(i)) and "hwho" not in parts(int(i))["wait"] for i in ids(WL))
      and all(re.match(r"(Until |On |After |With no date)", txt(int(i))) for i in ids(WL)), [(i, rt(int(i)), txt(int(i))) for i in ids(WL)][:3])
check("Waiting rows: the who line is in the order picks it up, watched by, set by; the top line carries the end date and no mover of its own",
      all(re.fullmatch(r'.*? (picks|to pick) it up( · watched by [^·]*)?( · set by [^·]*)?', rt(int(i))) for i in ids(WL))
      and all(re.fullmatch(r'(until .*|no end date)', parts(int(i))["age"]) and "hwho" not in w(int(i)).split('class="ir-who"')[0] for i in ids(WL)), [(parts(int(i))["age"], rt(int(i))) for i in ids(WL)][:2])
check("Waiting rows: the lines come in order in the markup, the top line, the who line, the wait, the step last", all(w(int(i)).find('class="ir-top"') < w(int(i)).find('class="ir-who"') < w(int(i)).find('class="hwait"') < w(int(i)).find('class="hnext hafter"') for i in ids(WL)))
check("Waiting: a time wait names the date and his words; then who picks it up and the scheduler watching follow it",
      txt(20) == f"Until {b.day_words(day(3))}: “park it until Friday”" and re.sub(r"\s+", " ", rt(20)).startswith("team-back picks it up · watched by the scheduler"), (txt(20), rt(20)))
check("Waiting: a wait on a real-world date names its basis (the facts of the old 'Parked on an outside event' block)", f"Until {b.day_words(day(1))}: the vendor ships on {day(2)}" in txt(24), txt(24))
check("Waiting: a verifying item waits on its end date with the proof named", f"Until {b.day_words(day(2))}: proof: the dashboard shows green" in txt(25), txt(25))
check("Waiting: another item's close names it, the server watches", 'After <a href="/items/a10"' in w(21) and "watched by the server" in rt(21), (w(21), rt(21)))
check("Waiting: an anchor wait names the anchor and the event and the backstop, the anchor module watches, the step after the wait on its own span", 'On <a href="https://github.com/o/r/pull/9"' in w(22) and ": the PR merges" in txt(22) and f"· backstop {b.day_words(day(9))}" in txt(22)
      and "watched by the anchor module" in rt(22) and parts(22)["step"].startswith('<span class="hnext hafter"><span class="dim">after the wait:</span> deploy it'), (w(22), rt(22)))
check("Waiting: a relay names the party's news and the ask-by day, the scheduler watches", f"On Acme's reply, ask by {b.day_words(day(5))}" in txt(23) and "watched by the scheduler" in rt(23), (txt(23), rt(23)))
check("Waiting: the one who picks it up is linked while its pane lives, before the watcher", parts(22)["who"].startswith('<a class="hwho" href="https://sala.example.org/#s=team-back"') and " picks it up" in parts(22)["who"], parts(22)["who"])
check("Waiting: a long then-mover is whole (it wraps on its line, never cut off)", "falcon-engineer-with-a-very-long-name picks it up" in re.sub(r"\s+", " ", rt(43)), rt(43))
check("Waiting: the chases count shows when there are any, and only then, at the end of the wait", txt(23).endswith("chased 2×") and "chased" not in txt(22) and "chased" not in rt(23), (txt(23), rt(23)))
check("Waiting: a wait with no date says so and nothing watches it, so the who line has no 'watched by'", "With no date set" in txt(26) and "watched by" not in rt(26) and " picks it up" in rt(26), (txt(26), rt(26)))
check("Waiting: sorted by end date, the soonest first (a time, a relay's ask-by day, a backstop, then the dateless)", ids(WL) == ["24", "25", "41", "20", "43", "23", "44", "28", "29", "22", "21", "26"], ids(WL))
check("Waiting: the next step is the last span of the detail, after the wait", '<span class="hnext hafter"><span class="dim">after the wait:</span> pick it up after</span>' in w(20), w(20))
check("Waiting: the end date shows in the age's place (no colour), the age since the wait began is its hover, and no ask form", 'data-tip="waiting since' in w(20) and "ir-age amber" not in WL and "ir-age red" not in WL and "hanswer" not in WL)
check("Waiting: the wait carries the post-wake mover on the who line only: no other mover on the wait or the step", '<span class="hnext">' not in WL and all('class="hwho' not in parts(int(i))["wait"] and 'class="hwho' not in parts(int(i))["step"] for i in ids(WL))
      and all(parts(int(i))["who"].count('class="hwho') <= 1 for i in ids(WL)))
# the anchor bug: an anchor wait whose anchor is scoped to the item in the project's anchors, not stored as wait_anchor, showed "no anchor stored"
check("Waiting: an anchor wait whose anchor is scoped to the item (no wait_anchor stored) names that anchor, as many as are scoped, with its event", '<a href="https://github.com/o/r/pull/12"' in w(29) and '<a href="https://example.invalid/thread/2"' in w(29)
      and "none recorded" not in w(29) and "no anchor stored" not in w(29) and txt(29).startswith("On ") and "watched by the anchor module" in rt(29), (w(29), rt(29)))
check("Waiting: an anchor wait with no anchor anywhere says so truthfully, keeps the event and the backstop, and has no watcher", txt(28) == f"On an anchor (none recorded): the vendor answers · backstop {b.day_words(day(6))}" and "no anchor stored" not in WL
      and "watched by" not in rt(28) and "team-back picks it up" in rt(28), (txt(28), rt(28)))
check("Waiting: the page steps over a hand-edited anchors file: an entry whose url is no string or whose items is no list names nothing; the Waiting row still draws, with the real anchors", "123" not in w(29).replace("123456789", "") and "junk" not in w(29)
      and b.scoped_urls("a29") == ["https://github.com/o/r/pull/12", "https://example.invalid/thread/2", "https://example.invalid/thread/3", "https://example.invalid/thread/4"], b.scoped_urls("a29"))
_b2 = render.Board(str(T / "store"), now=NOW); _b2.anchors = {**_b2.anchors, "projects/alpha": _b2.anchors["projects/alpha"] + [{"url": "https://example.invalid/odd-added", "items": ["a44"], "added": "yesterday"}, {"url": "https://example.invalid/first", "items": ["a44"], "added": 1}]}
_b2._scoped = None
check("Waiting: an `added` that is no number sorts as the oldest instead of failing the page; every Waiting row of the board still draws", _b2.scoped_urls("a44") == ["https://example.invalid/odd-added", "https://example.invalid/first"]
      and all(_b2.home_row(r, m, home.WAITING) for r, m in _b2.home_pairs()[home.WAITING]), _b2.scoped_urls("a44"))
# the long list and the shared labels (the board item review): a row shows three anchors then "+N more"; labels that repeat are numbered in the order shown; the item page lists them all
check("Waiting: three scoped anchors show in the wait and the rest as '+1 more'; two with the same label are numbered", re.findall(r'<a href="([^"]+)"[^>]*>([^<]*)</a>', parts(29)["wait"])
      == [("https://github.com/o/r/pull/12", "r PR #12"), ("https://example.invalid/thread/2", "example.invalid (1)"), ("https://example.invalid/thread/3", "example.invalid (2)")] and '<span class="dim">+1 more</span>' in parts(29)["wait"], parts(29)["wait"])
check("Waiting: the item page names all four scoped anchors, in full", all(f'href="{u}"' in b.item_html("a29") for u in b.scoped_urls("a29")))
# an item wait with only its backstop date (the board item review): the scheduler watches it (watchers.can_end), line two says no item is recorded and keeps the date
check("Waiting: an item wait with no item but a backstop date is watched by the scheduler; the wait says so in the anchor wording and keeps the date", txt(44) == f"On an item (none recorded) · back anyway {b.day_words(day(5))}"
      and "watched by the scheduler" in rt(44) and "no item stored" not in WL, (txt(44), rt(44)))
_r44 = next(r for r in b.rows if r["gid"] == "a44")
_nb = model.Model(model.WAITING, wait=model.Wait(kind="item", kind_explicit=True, mover="team-back"))
check("Waiting: an item wait with neither an item nor a backstop date has no watcher and says no item is recorded", "watched by" not in plain(b.wait_who(_r44, _nb)) and "On an item (none recorded)" in plain(b.home_wait(_r44, _nb)), plain(b.home_wait(_r44, _nb)))
# a hand-edited anchors file (the board item review): a page's value that is no list, an entry that is no dict, an items that is a number, an `added` that is no time, a url that is no string: the home page,
# the project page and the item pages all render, with the real anchors still named and the junk named nowhere
_b3 = render.Board(str(T / "store"), now=NOW)
_good = _b3.anchors["projects/alpha"]
_b3.anchors = {"projects/alpha": _good + ["junk", 7, None, {"url": "https://example.invalid/items-int", "items": 5, "added": "yesterday"}, {"url": ["x"], "items": ["a29"]}, {"url": "https://example.invalid/added-junk", "items": ["a44"], "added": "not a time"},
                                            {"url": "https://example.invalid/added-huge", "items": ["a44"], "added": 1e300}],
               "projects/beta": "junk", "projects/gamma": {"url": "x"}, "projects/delta": None}
_b3._scoped = None
try:
    _h3, _pp3, _i3 = _b3.html(), _b3.routing_html("projects/alpha"), [_b3.item_html(g) for g in ("a28", "a29", "a44", "a22")]; _err3 = ""
except Exception as _e3: _h3 = _pp3 = _i3 = ""; _err3 = f"{type(_e3).__name__}: {_e3}"
check("junk anchors file: the home page, the project page and the item pages (an anchor wait, a scoped one, an item wait) all render", _err3 == "" and 'id="waiting-list"' in _h3 and 'id="task-a-29"' in _pp3 and all("<h1" in x for x in _i3), _err3)
check("junk anchors file: the real anchors are still named and the junk is scoped to nothing", 'href="https://github.com/o/r/pull/12"' in _h3 and "items-int" not in "".join(u for g in ("a28", "a29", "a44") for u in _b3.scoped_urls(g)) and _b3.scoped_urls("a44") == ["https://example.invalid/added-junk", "https://example.invalid/added-huge"]
      and _b3.scoped_urls("a29")[0] == "https://github.com/o/r/pull/12", (_b3.scoped_urls("a44"), _b3.scoped_urls("a29")))
check("junk anchors file: a page whose value is no list holds no anchors, and the watch light counts only the readable entries", _b3.anchor_entries("projects/beta") == [] and _b3.anchor_entries("projects/gamma") == [] and _b3.anchor_entries("projects/delta") == []
      and len(_b3.anchor_entries("projects/alpha")) == len([e for e in _good if isinstance(e, dict) and isinstance(e.get("url"), str) and e["url"]]) + 3, [len(_b3.anchor_entries(k)) for k in ("projects/alpha", "projects/beta")])
_i44 = b.item_html("a44")
check("Waiting: the item page says 'an item (none recorded)' for an item wait with no item, as the row does", "an item (none recorded)" in _i44 and "no item stored" not in _i44, "")
_ip28 = b.item_html("a28"); _ip29 = b.item_html("a29")
check("Waiting: the item page says the same: no 'no anchor stored' for an anchor scoped to the item or for none", "no anchor stored" not in _ip28 + _ip29 and "none recorded" in _ip28 and "https://github.com/o/r/pull/12" in _ip29, "")

# ---- what is gone, what stays ----
gone = {"state tiles": 'class="overview"', "the tiles' links": 'class="stat', "Need your call (agents)": "Need your call (agents)", "its queue": 'class="q-line"', "For you": 'id="for-you"',
        "Needs your call": 'id="needs-your-call"', "On others": 'id="waiting-on-others"', "On agent": 'id="on-agent"', "Parked on an outside event": 'id="outside-event"',
        "the Tasks section of the panel": 'id="tasks"', "the old waiting block": '<section id="waiting">'}
for k, v in gone.items(): check(f"gone: {k}", v not in h, h[h.find(v) - 40:h.find(v) + 120])
check("gone: no section titled On others or Needs your call", not re.search(r"<h2>(On others|Needs your call)", h))
check("gone: the rows For you recorded stay recorded (foryou.py is untouched: its module and routes still answer)", hasattr(render, "_fy") and hasattr(render.Board, "for_you_html"))
panel = h[h.find('<aside id="panel"'):h.find("</aside>")]
check("stays: the right-hand panel holds Machines, Runners, Anchor hub, Audit and Projects, and nothing else", re.findall(r'<section id="([a-z-]+)">', panel) == ["machines", "runners", "anchorhub", "audit-panel", "projects-panel"] and "<h2 class=\"hdr\">Projects</h2>" in panel and "<h2 class=\"hdr\">Audit</h2>" in panel and "<h2 class=\"hdr\">Machines</h2>" in panel and "<h2 class=\"hdr\">Anchor hub</h2>" in panel
      and h.find('<section id="machines">') > h.find("</main>"), panel[:300])
check("stays: the audit line (now in the panel), the provision line, the theme button, the reload button, Back to top", 'id="audit"' in panel and 'id="provision"' in h and "Provision needed for" in h and 'id="theme"' in h and 'id="reload"' in h and 'id="totop"' in h)
check("stays: the provision line sits under the counts, above the lists; the audit line is no longer in the main column", h.find('<nav class="hcards"') < h.find('id="status"') < h.find('id="provision"') < h.find('<section id="your-move">')
      and 'id="audit"' not in h[:h.find("</main>")] and 'id="audit-now"' not in h[:h.find("</main>")] and h.find('<aside id="panel"') < h.find('id="audit"') < h.find("</aside>"))
check("gone: the Task board and Completed folds are not on the home page (the Projects page and the Closed page list them)", 'id="by-project"' not in h and 'id="completed"' not in h and "Completed (last 14 days)" not in h)
_hc_ = render.Board(str(T / "store"), now=NOW)._css()
_ul = lambda sid: re.search(r'<ul class="([^"]*)">', section(sid)).group(1)
check("the three lists are the one row list (ir-rows)", _ul("your-move") == "ir-rows" and _ul("agents-at-work") == "ir-rows" and _ul("waiting-list") == "ir-rows", [_ul(s) for s in ("your-move", "agents-at-work", "waiting-list")])
check("the count cards stay on one row down to the phone breakpoint (five columns that shrink: minmax(0, ...), never auto-fit), wrapping only at 480 px and under; the Sent notice under the header has the sections' 32 px gap above it",
      "nav.hcards{display:grid;grid-template-columns:repeat(5,minmax(0,148px))" in _hc_ and "@media(max-width:600px){nav.hcards{grid-template-columns:repeat(5,minmax(0,1fr))" in _hc_
      and "@media(max-width:480px){nav.hcards{grid-template-columns:repeat(auto-fit,minmax(96px,1fr))}}" in _hc_ and "minmax(104px,148px)" not in _hc_
      and "header.top+.isent{margin-top:32px}" in _hc_ and re.search(r"\}h2\{[^}]*margin:32px 0 12px", _hc_), None)
# ---- the blocks the in-place update swaps ----
bl = re.search(r'name="stackshot-blocks" content="([^"]*)"', h).group(1)
check("blocks: the live set is counts, status, the four lists, machines, runners, anchorhub, audit-panel, projects-panel (in page order)", [x.split("=")[0] for x in bl.split()] == ["counts", "status", "your-move", "agents-at-work", "queued-release", "waiting-list", "machines", "runners", "anchorhub", "audit-panel", "projects-panel"], bl)
check("blocks: every block id is on the page exactly once", all(h.count(f'id="{k}"') == 1 for k in ("counts", "status", "your-move", "agents-at-work", "queued-release", "waiting-list", "machines", "runners", "anchorhub", "audit-panel", "projects-panel")))

# ---- an empty board ----
for p in (T / "store/a").glob("*.json"): p.unlink()
b0 = render.Board(str(T / "store"), now=NOW); h0 = b0.html()
check("empty board: the four lists draw their own empty lines, and the counts say zero", "nothing waits on you" in h0 and "no agent has an open item" in h0 and "no release is queued" in h0 and "nothing is waiting" in h0
      and cards_of(h0[h0.find('<nav class="hcards"'):h0.find("</nav>")]) == [("#your-move", "0", "Your move"), ("#agents-at-work", "0", "On agent"), ("#queued-release", "0", "Queued for release"), ("#waiting-list", "0", "Waiting"), ("/closed", "0", "Closed")])

# ---- the side panel's Projects section: one card per scope, counted from the same list the Projects page draws ----
def proj_cards(bd):
    sec = re.search(r'<section id="projects-panel">.*?</section>', bd.panel_blocks()["projects-panel"], re.S)
    return re.findall(r'<a class="pc rc" href="([^"]+)"([^>]*)><b class="rn">([^<]*)</b><span class="rv">([^<]*)</span>', sec.group(0) if sec else "")
SCOPE_ORDER = list(b0.scopes)
per_scope = lambda bd: {s: sum(1 for k in bd.project_keys() if bd.proj_scope(k) == s) for s in SCOPE_ORDER}
txt = lambda n: f"{n} project{'' if n == 1 else 's'}"
check("projects section: a card per scope in the board's order, its count of the projects the Projects page lists, each linking /projects#grp-<name>",
      [(h, s, v) for h, _t, s, v in proj_cards(b0)] == [(f"/projects#grp-{s}", s, txt(per_scope(b0)[s])) for s in SCOPE_ORDER] and len(SCOPE_ORDER) >= 2 and sum(per_scope(b0).values()) == len(b0.project_keys()) > 0, proj_cards(b0))
b0.proj, b0.group = {}, {}      # a board with no project at all
check("projects section, a board with no project: a card per scope, each 0 projects, each still linking /projects#grp-<name>; the Projects page has no scope group (no grp-… id)",
      [(h, s, v) for h, _t, s, v in proj_cards(b0)] == [(f"/projects#grp-{s}", s, "0 projects") for s in SCOPE_ORDER] and 'id="grp-' not in b0.projects_html(), proj_cards(b0))
def reg(bd, key, title, org, status="active", tags=()):
    bd.proj[key] = {"title": title, "name": title, "org": org, "tags": list(tags), "type": "project", "status": status, "updated": 1, "agents": {}}; bd.group[key] = [key]
reg(b0, "projects/p-one", "P One", "work"); reg(b0, "projects/p-two", "P Two", "work", status="archived"); reg(b0, "projects/p-three", "P Three", "nobody", tags=["infra"])
pcs = proj_cards(b0); pg0 = b0.projects_html()
check("projects section: a scope's count is every registered project of that scope, archived included (the card's hover text says how many are active and archived); one project is '1 project'",
      [(s, v) for _h, _t, s, v in pcs] == [(s, {"work": "2 projects", "infra": "1 project"}.get(s, "0 projects")) for s in SCOPE_ORDER] and 'title="1 active, 1 archived"' in "".join(t for _h, t, s, _v in pcs if s == "work")
      and all('title=' not in t for _h, t, s, _v in pcs if s != "work"), pcs)
check("…and the Projects page carries the id each of those cards links to: once per scope that has projects, on the scope's first group, none for an empty scope",
      re.findall(r'<tr class="scope" id="(grp-[a-z0-9-]+)"', pg0) == [f"grp-{s}" for s in SCOPE_ORDER if s in ("work", "infra")] and pg0.count('id="grp-') == 2 and pg0.count('class="scope"') == 3, re.findall(r'<tr class="scope"[^>]*>', pg0))
check("…the scope names in the cards are the ones the page's group rows print (work twice: its active group and its archived one)", sorted(re.findall(r'<span class="sc">([^<]+)</span>', pg0)) == ["infra", "work", "work"], re.findall(r'<span class="sc">([^<]+)</span>', pg0))
b0.scopes = []
check("projects section, no scopes at all: the section is drawn with a one-line note, no card", 'class="mnote">no projects yet</p>' in b0.panel_blocks()["projects-panel"] and not proj_cards(b0))
b0.scopes = ["work", "Home Lab", "a/b", ""]
check("projects section: the scope anchor is a stable slug (lower case, dashes), whatever the name", [b0.scope_anchor(x) for x in b0.scopes] == ["grp-work", "grp-home-lab", "grp-a-b", "grp-x"])
b0.scopes = ["work", "Home Lab", "home-lab", "a/b", "HOME LAB", "", "日本語", "home-lab-2"]
_an = [b0.scope_anchor(x) for x in b0.scopes]
check("projects section: scopes whose names come to the same slug get distinct anchors: the first keeps the slug, a later one gets -2, -3…, never an id another scope has; the same on every draw",
      _an == ["grp-work", "grp-home-lab", "grp-home-lab-2", "grp-a-b", "grp-home-lab-3", "grp-x", "grp-x-2", "grp-home-lab-2-2"] and len(set(_an)) == len(_an)
      and _an == [b0.scope_anchor(x) for x in b0.scopes] and list(b0.scope_anchors()) == b0.scopes, _an)
b0.scopes = ["Home Lab", "home-lab"]; _sc0 = b0._sc; b0._sc = ("Home Lab", {"home lab": "Home Lab", "home-lab": "home-lab"}, {}, {})      # the org decides the scope
reg(b0, "projects/p-hl1", "HL One", "Home Lab"); reg(b0, "projects/p-hl2", "HL Two", "home-lab")
_cards, _pg = proj_cards(b0), b0.projects_html()
_hrefs = [h.split("#", 1)[1] for h, _t, _s, _v in _cards]
check("…two scopes with equal slugs: their cards link to two different fragments, and the Projects page carries an id for each (both targets exist, once)",
      len(_cards) == 2 and _hrefs == ["grp-home-lab", "grp-home-lab-2"] and all(_pg.count(f'id="{x}"') == 1 for x in _hrefs)
      and re.findall(r'<tr class="scope" id="(grp-[a-z0-9-]+)"><th colspan="2"><span class="sc">([^<]+)</span>', _pg) == [("grp-home-lab", "Home Lab"), ("grp-home-lab-2", "home-lab")], (_cards, re.findall(r'<tr class="scope"[^>]*>', _pg)))
check("…and a second draw gives the same anchors", [h for h, _t, _s, _v in proj_cards(b0)] == [h for h, _t, _s, _v in _cards] and b0.projects_html() == _pg)
b0._sc = _sc0

# ---- the pure half ----
check("home.first_next: marker, bold marks and the name opener are stripped; a fenced block and a server note are no line", home.first_next("- **team-back**: do `x y` first\nhome-front: second", ("team-back",)) == ("team-back", "do `x y` first")
      and home.first_next("(a server note)\nOliver: the real one") == ("Oliver", "the real one") and home.first_next("") == ("", "") and home.first_next("no opener at all") == ("", "no opener at all"))
check("home.first_next: only a mover's prefix is stripped — Oliver, a hyphenated session name, a name the caller knows; any other prefix stays in the step",
      home.first_next("Check the result: it works") == ("", "Check the result: it works") and home.first_next("Step 1: run the thing") == ("", "Step 1: run the thing")
      and home.first_next("Note: be careful") == ("", "Note: be careful") and home.first_next("- **Note**: bold and marked") == ("", "Note: bold and marked")
      and home.first_next("falcon-engineer: take it", ("falcon-engineer",)) == ("falcon-engineer", "take it") and home.first_next("falcon-engineer: take it") == ("", "falcon-engineer: take it")
      and home.first_next("oliver: run it") == ("oliver", "run it")
      and all(home.first_next(f"{x}: do it") == ("", f"{x}: do it") for x in ("follow-up", "re-run", "e-mail", "x-ray", "Follow-Up"))
      and home.first_next("Priya: ping her", ("Priya",)) == ("Priya", "ping her") and home.first_next("Priya: ping her") == ("", "Priya: ping her"),
      [home.first_next(x) for x in ("Check the result: it works", "Step 1: run the thing", "Note: be careful", "falcon-engineer: take it", "oliver: run it", "follow-up: do it", "re-run: do it", "e-mail: do it", "x-ray: do it")])
# a next line that opens with the mover's display name is stripped when the stored mover is a session id, and the post-wake mover's and the fleet's names too; a hyphenated word that names nobody stays
_r10 = next(r for r in b.rows if r["gid"] == "a10")
_kn = b.known_movers(_r10, model.Model(model.ALIVE, mover=SESS["back"]))
check("home.known_movers: the stored id and the name the board gives it, the owner's display name and the fleet's session names",
      SESS["back"] in _kn and NAME["back"] in _kn and all(NAME[k] in _kn for k in ("front", "build", "other")) and "Oliver" not in _kn[:0], _kn)
_rr = {**_r10, "metadata": {**_r10["metadata"], "next": "team-back: write the code", "mover": SESS["back"]}}
_rt = _html.unescape(re.sub(r"<[^>]+>", "", b.home_row(_rr, model.Model(model.ALIVE, mover=SESS["back"]), home.AGENTS)))
_rr2 = {**_rr, "metadata": {**_rr["metadata"], "next": "follow-up: write the code"}}
_rt2 = _html.unescape(re.sub(r"<[^>]+>", "", b.home_row(_rr2, model.Model(model.ALIVE, mover=SESS["back"]), home.AGENTS)))
check("row: a next line opening with the mover's display name is stripped when the stored mover is a session id; a hyphenated word that names nobody stays",
      "write the code" in _rt and "team-back: write" not in _rt and "follow-up: write the code" in _rt2, (_rt, _rt2))
_wl_all = " | ".join(rt(int(i)) for i in ids(WL))
_r41 = next(r for r in b.rows if r["gid"] == "a41")
_nw = re.sub(r"<[^>]+>", "", b.wait_who(_r41, model.Model(model.WAITING, wait=model.Wait(kind="time", kind_explicit=True, until=day(2), mover=""))))
check("Waiting: a wait with nobody to pick it up reads 'nobody set to pick it up', never 'no mover'; the rows of the fixture, which all have one, say neither", "nobody set to pick it up" in _nw and "no mover" not in _nw + _wl_all, (_nw, _wl_all[:300]))
# the board item: the row's form says which page it is on and the page shows the answer's notice when the server brings it back
# ---- the step rows: the step itself in place of the first next line, an optional note box with TWO buttons (Done, Send note), only on a your-step item
S = {n: row_of(YM, n) for n in (50, 51, 52, 53, 55, 56, 57)}
sform = lambda r: (re.search(r'<form class="hanswer hstep".*?</form>', r, re.S) or [""])[0]
check("step rows: a your-step item with no ask is on Your move, and its row shows the step on line two, never the first next line ('check it' is the agent's)",
      all(f"task-a-{n}" in YM for n in S) and all("team-back: check it" not in S[n] and "check it" not in S[n].split('class="hask"')[0] for n in S), S[50][:500])
check("step rows: a command in the step is one code block with a copy button and the line says 'the command below', the command as the item wrote it",
      '<div class="cmd"><pre><code>sala op reauth box-a --from me --words &quot;go&quot;</code></pre><button type="button" class="b copy"' in S[50] and "the command below" in S[50].split('class="hask"')[0], S[50])
check("step rows: a `! ...` line stays verbatim whole in one code block, with no text line around it", '<pre><code>! sala reauth box-a</code></pre>' in S[51] and S[51].count('<div class="cmd">') == 1 and '<span class="hnext"><div class="cmd">' in S[51], S[51])
_links = lambda h: re.findall(r'<a href="(https://example\.com/p/[a-z]+)" target="_blank" rel="noopener">', h)
check("step rows: with no command a link stays in the sentence as a link that opens in a new tab, in no code block", 'href="https://example.invalid/login/now" target="_blank" rel="noopener"' in S[52] and "Sign in at" in S[52] and "<pre>" not in S[52] and 'class="cmd"' not in S[52], S[52])
check("step rows: a step with two links and no command draws both as links and no Copy box", _links(S[55]) == ["https://example.com/p/aaa", "https://example.com/p/bbb"] and "<pre>" not in S[55] and 'class="b copy"' not in S[55] and "and say done" in S[55], S[55])
check("step rows: a step with a command and a link boxes the command only, the link stays inline", S[56].count('<div class="cmd">') == 1 and '<pre><code>sala op reauth box-a</code></pre>' in S[56] and "aaa</code>" not in S[56]
      and _links(S[56].split('<div class="cmd">')[0]) == ["https://example.com/p/aaa"] and "the command below" in S[56], S[56])
check("step rows: a lone-word backtick stays inline, no Copy box", "<code>default</code>" in S[57] and "<pre>" not in S[57] and 'class="b copy"' not in S[57], S[57])
check("step rows: plain words show as they read with no block", "Call the office and say done" in S[53] and "<pre>" not in S[53], S[53])
check("step rows: the form has an optional note box and TWO buttons, Done (the main one) and Send note (needs text), both disabled until the token, no comment button, the old one-Send label gone, the token empty and `back` empty, nothing hidden",
      all(sform(S[n]).count("<button") == 2 and sform(S[n]).count('class="b main" name="act" value="done" disabled>Done</button>') == 1 and sform(S[n]).count('class="b" name="act" value="note" data-needs-text disabled>Send note</button>') == 1
          and 'value="send"' not in sform(S[n]) and 'value="comment"' not in sform(S[n]) and "data-step" in sform(S[n]).split(">", 1)[0]
          and 'placeholder="Note (optional)"' in sform(S[n]) and 'aria-label="Note for the next owner (optional)"' in sform(S[n])
          and "Send with an empty box finishes the step" not in sform(S[n]) and "A note, or nothing to finish the step" not in sform(S[n])
          and ('<div class="abox"><textarea id="astep-a%d" name="text"' % n) in sform(S[n]) and 'aria-controls="astep-a%d"' % n in sform(S[n]) and 'name="token" value=""' in sform(S[n]) and 'name="back" value=""' in sform(S[n]) and 'action="/items/a%d/answer"' % n in sform(S[n])
          and " hidden" not in sform(S[n]).split(">", 1)[0] for n in S), sform(S[50]))
check("step rows: the item page is linked by the row's title for the viewer who gets no form", all(f'<a class="ir-link" href="/items/a{n}"' in S[n] for n in S))
check("step rows: a decision row keeps today's shape (options, Send; no Done, no step form), and rows that are not step items carry no step form or Done",
      "hstep" not in r1 and 'value="done"' not in r1 and "hstep" not in row_of(YM, 2) and "hstep" not in row_of(YM, 40) and "hstep" not in AW + WL and 'value="done"' not in AW + WL)
check("step rows: the page script treats a step form like the others: its token fills in, its buttons enable, a viewer with none keeps the link", "button[disabled]" in h and "giveup" in h)
_forms = re.findall(r'<form class="hanswer".*?</form>', h, re.S)
check("home answer: every answer form carries a hidden `back` field, empty in the markup (the script fills it with the page's own path and the row's anchor as the form is sent)",
      _forms and all(f.count('<input type="hidden" name="back" value="">') == 1 and 'action="/items/' in f for f in _forms), len(_forms))
_hj = render._HOME_JS
check("home answer: the script sets back to location.pathname alone when the form is sent: no row fragment (it scrolled home to the item's new place)", "f.matches('form.hanswer')" in _hj and "input[name=back]" in _hj and "b.value=location.pathname;" in _hj
      and "'#'+li.id" not in _hj and "li.id" not in _hj and "closest&&f.closest('li[id]')" not in _hj, _hj)
# the answer form's double-send guard, run in node over a stub (no browser): a second submit of the same form inside 8 seconds is cancelled, one after it goes through, a form with no token is cancelled,
# and a form that is not an answer form is left alone. The handler is cut out of the page script by its own first and last text, so the check fails if the guard is taken out.
_h0 = _hj.find("document.addEventListener('submit',function(ev){var f=ev.target;if(!f||!f.matches||!f.matches('form.hanswer'))")
_h1 = _hj.find("},true);", _h0) + len("},true);") if _h0 >= 0 else -1
check("home answer: the submit handler is found in the page script", _h0 >= 0 and _h1 > _h0, _h0)
if _h0 >= 0 and shutil.which("node"):
    _guard_js = r"""
const src = require('fs').readFileSync(0, 'utf8'); let now = 1000000; const out = []; let handler = null;
const ctx = {SK: 'sk', JSON, Math, Date: {now: () => now}, window: {scrollY: 0}, location: {pathname: '/'}, sessionStorage: {setItem() {}},
  document: {addEventListener: (t, fn) => { if (t === 'submit') handler = fn }}};
require('vm').runInNewContext(src, ctx);
function form(token, answer) { const back = {value: ''};
  return {matches: sel => answer && sel === 'form.hanswer', querySelector: sel => sel === 'input[name=token]' ? (token ? {value: token} : {value: ''}) : sel === 'input[name=back]' ? back : null}; }
function send(f) { let stopped = false; handler({target: f, preventDefault: () => { stopped = true }}); return stopped; }
const f = form('t', true);
out.push(send(f)); now += 3000; out.push(send(f)); now += 4000; out.push(send(f)); now += 1000; out.push(send(f));
out.push(send(form('', true))); out.push(send(form('t', false)));
const g = form('t', true); out.push(send(g)); out.push(send(form('t', true)));
console.log(JSON.stringify(out));
"""
    _gr = subprocess.run(["node", "-e", _guard_js], input=_hj[_h0:_h1], capture_output=True, text=True, timeout=30)
    _go = json.loads(_gr.stdout) if _gr.returncode == 0 and _gr.stdout.strip() else []
    check("home answer: a second submit of the same answer form within 8 seconds is cancelled; one after the window goes through, and each form has its own window",
          _go[:4] == [False, True, True, False], (_go, _gr.stderr[:300]))
    check("home answer: a form with no token is cancelled, a form that is not an answer form is left alone, another answer form is not held by the first one's window",
          _go[4:] == [True, False, False, False], (_go, _gr.stderr[:300]))
check("home answer: the page stays where it was sent from: scrollY saved in sessionStorage as the form is sent, restored once on the page the ?sent= answer lands on, only when fresh (under 15 s), the same path and without a hash, the notice's height added, the notice kept in view",
      "sessionStorage.setItem(SK,JSON.stringify({y:Math.round(window.scrollY||0),t:Date.now(),p:location.pathname}))" in _hj and "sessionStorage.removeItem(SK)" in _hj and "window.scrollTo(0,Y)" in _hj
      and "S.p===location.pathname" in _hj and "!location.hash" in _hj and "Date.now()-S.t<15000" in _hj and "document.documentElement.scrollHeight-h0" in _hj and "position:sticky" in _hj and "addEventListener('load'" in _hj
      and "role" in _hj and _hj.index("sessionStorage.removeItem(SK)") < _hj.index("window.scrollTo(0,Y)") and h.count("<script>" + _hj + "</script>") == 1, _hj)
check("home answer: the label prefix for an issue-numbered id is the board's own naming, not a literal in the script", f'<div id="sent-notes" hidden data-hash="{render.shown("g1")[:-1]}" data-notes=' in h and "board#" not in _hj and "data-hash" in _hj)
_sk = render._SENDKEY_JS
check("ctrl+enter: the home page carries the key script once, before nothing else needs it: a delegated keydown on the document, for the answer and comment boxes, Ctrl or Cmd, never during an IME composition, a disabled button is left alone",
      h.count(_sk) == 1 and "document.addEventListener('keydown'" in _sk and "e.ctrlKey||e.metaKey" in _sk and "e.key!=='Enter'" in _sk and "e.isComposing" in _sk and "e.keyCode===229" in _sk
      and "form.ianswer textarea,form.hanswer textarea" in _sk and "if(!b||b.disabled)return" in _sk and "requestSubmit(b)" in _sk and "button[name=act][value=done]" not in _sk and "f.querySelector('button[name=act]')" in _sk, _sk)
_nt = re.search(r'<div id="sent-notes" hidden data-hash="[^"]*" data-notes="([^"]*)">', h)
_notes = json.loads(_html.unescape(_nt.group(1))) if _nt else {}
check("home answer: the page carries the item page's own notices (one text per ?sent= code, the same as the item page shows), and the script shows one naming the item, then drops ?sent from the address",
      set(_notes) == set(render.Board._SENT) and _notes["decision"][1] == render.Board._SENT["decision"][1] and "q.get('sent')" in _hj and "q.get('item')" in _hj and "q.get('name')" not in _hj and "get('name')" not in _hj
      and _notes["stale"][1] != render.Board._SENT["stale"][1] and "Read it again below" not in _notes["stale"][1] and "open the item to read it again" in _notes["stale"][1]
      and _notes["askedback"][1] != render.Board._SENT["askedback"][1] and "pick one" not in _notes["askedback"][1] and "open the item to pick a day" in _notes["askedback"][1]
      and render.Board(str(T / "store")).sent_html({"sent": "stale"}).count("Read it again below") == 1
      and "p.className='isent '+m[0]" in _hj and "textContent" in _hj and "history.replaceState(null,'',location.pathname+location.hash)" in _hj and "innerHTML" not in _hj, _notes.keys())
check("the home page's notices say the agent on it has been told, never its owner",
      "the agent on it has been told" in _notes["decision"][1] and "the agent on it has been told" in _notes["comment"][1] and all("owner" not in v[1] for v in _notes.values()), _notes)
check("the home page carries the notice of a note sent on a step (stepreply), and the script names who takes it and spends both of the row's buttons after a Done or a note",
      "stepreply" in _notes and "decides whether the step is done" in _notes["stepreply"][1] and "k==='stepreply'" in _hj and "form.hstep button[name=act]" in _hj and "form.hstep button[value=send]" not in _hj, _notes.get("stepreply"))
_cj = render._CARDS_JS
check("the page scripts handle the step form's two buttons: the card script enables a data-needs-text button (Send note) only while the box holds text and leaves Done alone, a step form is watched on typing, and the home script runs it for every form after the token enables the buttons",
      "form[data-step]" in _cj and "button[data-needs-text]:not([data-spent])" in _cj and "t.value.trim()!==''" in _cj and "form[data-cards] textarea,form[data-step] textarea" in _cj
      and "if(window.ssCards)ssCards.sync(f)" in _hj and "hstep')) ssCards" not in _hj and ".hstep')&&" not in _hj.replace(" ", ""), (_cj[:600], _hj[:600]))
_lj = render._LIVE_JS
check("in place: a decision box with text in it holds the swap — busy() also tests every form.hanswer textarea and text input for a typed value, not only the focused element",
      "form.hanswer textarea" in _lj and "form.hanswer input[type=text]" in _lj and "if(l[i].value)return true" in _lj and "||s||typed())" in _lj, _lj[_lj.find("function typed"):][:400])
check("home.copyables: a command leaves the line (several are numbered), a link stays in the text and is no block, a plain step has none",
      home.copyables("run `a b` then `c d`") == ("run command 1 below then command 2 below", ["a b", "c d"]) and home.copyables("open https://x.example/a?b=1.") == ("open https://x.example/a?b=1.", [])
      and home.copyables("do `one` thing") == ("do `one` thing", []) and home.copyables("[the page](https://x.example/p) now") == ("[the page](https://x.example/p) now", [])
      and home.copyables("see https://x.example/a then run `a b`") == ("see https://x.example/a then run the command below", ["a b"]))
check("home.list_of: waiting, the owner's alive, an agent's alive, dead", (home.list_of(model.Model(model.WAITING)), home.list_of(model.Model(model.ALIVE, mover=model.owner_display())), home.list_of(model.Model(model.ALIVE, mover="x")), home.list_of(model.Model(model.DEAD)))
      == ("waiting", "your-move", "agents", ""))
check("home.watched_by: the scheduler, the anchor module, the server", [home.watched_by(k) for k in ("time", "relay", "anchor", "item")] == ["the scheduler", "the scheduler", "the anchor module", "the server"])

check("title: the home h1 is wrapped in a link to / so a click there clears any #hash", re.findall(r'<h1 class="site"><a href="([^"]*)"><img class="logo"', h) == ["/"], h[h.find("<h1"):h.find("<h1") + 200])
check("panel: home draws the panel from the shared panel_blocks builder, once, with the same five blocks", h.count('<aside id="panel"') == 1 and all(f'id="{k}"' in h for k in ("machines", "runners", "anchorhub", "audit-panel", "projects-panel")) and list(b.panel_blocks()) == ["machines", "runners", "anchorhub", "audit-panel", "projects-panel"], list(b.panel_blocks()))

# ---- three UI defects (a stray store letter on closed rows, "handed to" overflow, amber contrast) ----
_d30 = next(r for r in b.done if r["gid"] == "a30")
_md30 = next(l for l in b.markdown().splitlines() if "shipped last week" in l)
check("a closed item with no session has no label (not the store letter), in board.md", b.lab(_d30) == "" and b.lab(_d30) != _d30["L"] and "· `" not in _md30, _md30)
check("an open item with a session keeps its label, an open item with none sits under 'no agent'", b.lab(next(r for r in b.rows if r["gid"] == "a10")) != "" and b.lab(next(r for r in b.rows if r["gid"] == "a40")) != "")
def _lum(hx):
    hx = "#" + "".join(ch * 2 for ch in hx[1:]) if len(hx) == 4 else hx
    c = [int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
def _ratio(a, bg): x, y = sorted((_lum(a), _lum(bg)), reverse=True); return (x + .05) / (y + .05)
_light = re.search(r":root\{--bg:(#[0-9a-f]{3,6});[^}]*--card:(#[0-9a-f]{3,6});[^}]*--warn:(#[0-9a-f]{3,6});", _css0)
_dark = re.search(r":root\[data-theme=dark\]\{--bg:(#[0-9a-f]{3,6});[^}]*--card:(#[0-9a-f]{3,6});[^}]*--warn:(#[0-9a-f]{3,6});", _css0)
check("the amber (--warn, the 'Your move' age) is 4.5:1 or more as small text (WCAG 1.4.3) on the page and the card, in light and in dark",
      bool(_light and _dark) and all(_ratio(_light.group(3), _light.group(g)) >= 4.5 for g in (1, 2)) and all(_ratio(_dark.group(3), _dark.group(g)) >= 4.5 for g in (1, 2)),
      (_light and [_ratio(_light.group(3), _light.group(g)) for g in (1, 2)], _dark and [_ratio(_dark.group(3), _dark.group(g)) for g in (1, 2)]))

print(f"ok: home scenario, {len(ran)} checks" if not fails else f"{len(fails)} check(s) failed"); sys.exit(1 if fails else 0)
