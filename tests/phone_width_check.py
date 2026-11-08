"""Phone-width check (a manual check, CONTRIBUTING.md; not in the suite loop: CI's runner has no browser). Renders the
board, a project page and an item page from fixture data (long project, session and machine names, many projects, four
machines, five receivers, long paths, code and links; no live store, no network) and loads each in Chromium:

  - at 360, 390, 412 and 430 px, light and dark, with every details.fold open, the page is exactly the screen's width
    (document scrollWidth == viewport width): nothing scrolls sideways;
  - the Runners column (a machine with six runners): at 360, 412, 1280 and 1440 px, light and dark, one runner per line, top to bottom,
    every list a single column inside the screen, and no sideways scroll;
  - the item page: the state line, then Your step or the ask, then Next, Background, History and Comments in that order, with a long History entry inside the screen;
  - the comment box: on an open item he does not move (doing, waiting on a date, verifying) it takes the answer box's slot, open, under the state line and ahead of Next, at 360, 390 and 430 px and at 1280 px,
    light and dark: whole on the first screen (the text box and Send), inside it, the Comments fold closed with no form; an item he moves has the one answer form and no second comment form;
  - the root element paints each theme's --bg (the overscroll and gesture-bar area on a phone) and its color-scheme
    follows the system, and the theme switch's saved choice over the system;
  - the home lists: at 360, 412 and 1440 px, light and dark, Your move and Queued for release open and On agent and Waiting closed as the page
    loads; with every fold open and every ask form shown each row inside the screen, its top line (number, whole title, age at the right edge) above its mover line, detail block and form, its buttons inside it; the age
    colours apart; the five count cards in the header (title, rendered line, cards, search), 60 px tall on one row, with no sideways scroll;
  - the line above a row's title (home, Closed and a project page): at 360, 412 and 1440 px, light and dark, `project · owner` (the owner alone on a project page) inside its row, above the title line, in the small quiet type,
    wrapping when a long project name and a long owner name meet, never running past the card;
  - the Closed page: at 360 and 412 px, light and dark, each New row the one row: outcome tag, title and relative close time on the top line, the close reason under it and never cut, Clear under the reason (32 px or taller);
    a Clear leaves the row in place, dimmed, with an Undo (a stub answers the page's fetch), Clear all leaves every row with its own Undo;
  - the header of the item page (also with its answer box), a project's page, Projects, Closed, Search and Runners: each starts with home's header, the title, the five count cards and the search box,
    at 360, 390 and 1280 px, light and dark: the page the screen's width with every fold open, one header and one search box, the cards 60 px tall inside the screen and linking home's lists (`/#your-move` ...) and /closed, top to bottom
    title, cards, box, the header sticky when wide (and held at the top on scrolling) and not on a phone. The search box's hint is whole in each: the text, in the box's own font, fits inside the box (the short line, "Search the board", at 480 px and under, the full line above), and the box does not scroll sideways. PHONE_WIDTH_HEADER_SHOTS=<dir> keeps a screenshot of the item page and the Projects page at 390 and 1280 px;
  - the reload button (on every page): on the board, a project page and an item page a round 44 px
    button with Back to top's look, 10 px above it on the same right edge (scrolled or not; on the board also kept through the in-place update,
    off the panel's last card), floating and not in the title bar; the title bar clear of the theme (and panel) button, on the project and item
    pages the back link too; Back to top scrolls to the top; a click on the reload button reloads;
  - the board's summary panel (Machines, Runners, Anchor hub and Audit, all open on every load and on the Anchor hub's card spacing): pinned on load at 800 px and up (a closed
    drawer below it) and kept nowhere; at 360 and 412 px a drawer from the right (button, close button, tap outside, Escape, a tile's link, a #machines
    or #anchorhub link) with no sideways scroll; at 1440, 1280, 1100, 960 and 800 px a peek on the right edge or the title bar's
    button, a pin on a click that keeps the main column's width (920) with nothing
    overlapping, an unpin on the next click; and the panel pinned or open across the page's in-place update (the page is
    served from memory by a routed fake origin: no server). PHONE_WIDTH_SHOTS=<dir> keeps a screenshot of each state;
  - the panel's cards line up, at 360 and 412 px (drawer) and 1440 px (pinned), light and dark: every card's text (Machines, Runners, Anchor hub, Audit labels and the
    Audit now link) starts at the same left x; a machine row that is behind shows `→ <latest>` in the text colour on the row's own line (same top as the machine's name, one line,
    inside the card, no word "update"); and the rows the Audit card's script draws from GET /audit/status are the rows the server drew, for six states of the audit (no run yet,
    last run with findings, with one, with none, running, did not finish) with the button's disabled state alike.

  - the buttons of the board's pages: on the home page, an item page (the decision's answer box, a step with its command and draft, the Watch / Mute / Default control), Closed, Projects, a project, Search and
    Runners (with its Disable / Enable buttons), at 390 px with touch emulation and at 1280 px, light and dark, the summary panel open and closed: every `.b` computes to the secondary look (1 px solid --ibd outline, no fill,
    --fg text, 13 px, 8 px corners, 32 px tall, 44 px on a coarse pointer; a disabled one at 45% opacity, a flat grey one in the dark theme) and the composer's Send, the one `.b.main`, to the main look (a solid --acc fill, --on-acc text, 600 weight, a disabled
    one at 50%); none keeps the old Primary, Standard or Quiet class or fill, none runs past the screen or its card; on hover the outline firms up to --fg and a light fill appears (the main one darkens or lightens its fill;
    pressed .on and .warn buttons keep their own edge colour).
    tests/run-suite phone_width_check     → exit 0 / 1
    (once per machine, the browser itself: uvx playwright@1.63.0 install chromium)"""
import json, os, re, sys, time, pathlib, tempfile, datetime
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="phonewidth-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml, n = re.subn(r"(?m)^repos = \[\]", 'repos = ["repo-a", "repo-b"]', toml, count=1); assert n == 1    # the Runners card is drawn per repo
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1)
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1      # a line of next that opens "Oliver:" is his step (the Your step block draws his lines)
toml = toml.replace('session_view = ""', 'session_view = "https://sala.example.org/#s={name}"', 1); assert "sala.example.org" in toml   # live session names drawn as their sala links
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[home] "]', toml); assert n == 1
toml += '\n[[machines_panel.packages]]\nname = "gbrain"\nowner = ""\ninstalled = "cmd:true"\nmachines = ["a"]\nlatest = "github-release:x/y"\n'
toml, n = re.subn(r'(?m)^(\[audit\]\s*#.*\n)enabled = false', r'\1enabled = true', toml, count=1); assert n == 1    # the Audit section of the panel is drawn
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
for d in ("store/a", "fleet/a", "fleet/b", "fleet/d", "fleet/x", "state/site", "state/anchor-hub", "state/audit", "secrets", "touch", "out/items"): (T / d).mkdir(parents=True)

ZONE = datetime.timezone(datetime.timedelta(hours=4)); now = datetime.datetime.now(ZONE); H = datetime.timedelta(hours=1)      # the instance zone is Asia/Dubai: UTC+4, label +04
def audit_run(rec):
    """Make the audit's one run record (the newest by file name) what rec says; None = no record at all. The state dir is the fixture's."""
    for f in (T / "state/audit").glob("run-*.json"): f.unlink()
    if rec is not None: (T / "state/audit" / f"run-{now.date().isoformat()}.json").write_text(json.dumps(rec))
audit_run({"started": (now - 20 * H).timestamp(), "finished": (now - 20 * H).timestamp() + 1200, "items_read": 9, "findings": [{"id": "a1"}, {"id": "a2"}], "by_category": {"stale": 1, "no-ask": 1}, "by_session": {}})   # the board's Audit card has its three rows
def findings_log(on):
    """The findings log the Audit card and the Audits page count from: a few appearances in the last 24 hours (and one older), or none."""
    f = T / "state/audit/findings-log.jsonl"
    if not on: f.unlink(missing_ok=True); return
    rows = [(1, "silence", f"board#{1}", "stale"), (2, "filing", f"board#{2}", "stuck-elsewhere"), (3, "filing", f"board#{3}", "board checks:why-not-now"), (4, "run", f"board#{4}", "ask-missing"), (30, "run", f"board#{5}", "stuck-elsewhere")]
    f.write_text("".join(json.dumps({"at": (now - r[0] * H).timestamp(), "source": r[1], "id": r[2], "kind": r[3], "agent": "ops-falcon-main", "project": "projects/alpha",
                                     "detail": "waits on something that is closed, so the wait reads as stuck " + "x" * 40}) + "\n" for r in rows), encoding="utf-8")
findings_log(True)
A, X = "22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444"
LONG = "ops-falcon-engineer-background-builder-with-a-long-name"
sess = {"11111111-1111-4111-8111-111111111111": {"name": "ops-falcon", "machine": "a", "url": "https://claude.ai/code/session_s", "seen": "x"},
        A: {"name": "ops-falcon-main", "machine": "a", "url": "https://claude.ai/code/session_a", "seen": "x"},
        X: {"name": "ops-falcon-engineer", "machine": "a", "url": "", "seen": "x"}}
for L, nm, cv in (("a", "box-a", "2.1.140"), ("b", "machine-with-a-very-long-example-hostname-b", "2.1.139"), ("d", "machine-with-a-very-long-example-hostname-d", "2.1.140"), ("x", "machine-with-a-very-long-example-hostname-x", "2.1.120")):
    alert = {"b": {"setup": {"at": "2031-03-01T00:00:00Z", "ok": False, "step": "Install-Module PSWindowsUpdate -Scope AllUsers -Force -AllowClobber", "reason": "x" * 300}},
             "x": {"updates": [{"what": "stackshot-puller-helper-with-a-long-name", "from": "5", "to": "6.0.0-rc.1+build.20310301", "ok": False, "at": 1930089600, "reason": "y" * 300}]}}.get(L, {})   # a failed setup step and update: their cards at the foot of the column
    (T / f"fleet/{L}/machine.json").write_text(json.dumps({"letter": L, "fleet": nm, "claude": cv, **alert}))
    (T / f"fleet/{L}/sessions.json").write_text("{}")
(T / "state/site/versions.json").write_text(json.dumps({"checked": "x", "packages": [
    {"name": "claude code", "installed": "2.1.140", "latest": "2.1.140", "state": "latest",
     "machines": {"a": "2.1.140", "b": "2.1.139", "d": "2.1.140", "x": "2.1.120"}, "machine_state": {"a": "live", "b": "live", "d": "live", "x": "offline 3 d"}},
    {"name": "gbrain", "installed": "1.4.1-home.20310301.longbuildtag", "latest": "1.9.12-build.3", "state": "latest", "hosts": ["a"]}],
    "ssh_hosts": [{"name": "machine-d", "reachable": True, "checked": "2031-03-02 09:00 +04", "packages": {"claude code": "2.1.139", "gbrain": "1.4.0-home.20310301.longbuildtag"}},      # machine cards read over ssh: one behind, and one that does not answer
                  {"name": "machine-with-a-very-long-example-hostname-g", "reachable": False, "checked": "2031-03-02 09:00 +04", "last_ok": "2031-03-01 09:00 +04", "packages": {"gbrain": "1.4.1-home.20310301.longbuildtag"}}]}))
_ck = now.strftime("%Y-%m-%d %H:%M:%S")
(T / "state/anchor-hub/status.json").write_text(json.dumps({"started": _ck, "anchors": {}, "receivers": {
    "slack": {"ok": True, "checked": _ck}, "gworkspace-gmail-and-drive-and-docs": {"ok": True, "checked": _ck},
    "notion": {"ok": False, "error": "token refused by https://api.notion.com/v1/users/me_with_a_long_path_and_no_spaces", "checked": _ck},
    "github": {"ok": True, "checked": _ck}, "linear-receiver-experimental": {"ok": True, "checked": _ck}}}))
LONGP = [("project-with-a-very-long-example-name-01", "session-with-a-long-example-name-01", "work"),
         ("project-with-a-very-long-example-name-02", "session-with-a-long-example-name-02", "work"),
         ("infrastructureandtoolingwithoutanyhyphensatallverylongname", "ops-session-with-a-long-example-name-03", "home"),
         ("project-with-a-very-long-example-name-03", "session-with-a-long-example-name-04", "home"), ("project-with-a-very-long-example-name-04", "session-with-a-long-example-name-05", "home"),
         ("project-with-a-very-long-example-name-05", "session-with-a-long-example-name-06", "home"), ("short-project", "session-with-a-long-example-name-07", "home"), ("project-with-a-very-long-example-name-06", "session-with-a-long-example-name-08", "home")]
page = lambda name, s: {"title": name, "name": name, "org": "home", "tags": [], "type": "project", "session": s, "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": f"https://example.invalid/{name}"}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": {**page("Alpha", "ops-falcon"), "agents": {"ops-falcon-main": "Oliver's point of contact", "ops-falcon-engineer": "builds"}, "back_agents": {"ops-falcon-engineer": "builds"}},
    **{f"projects/{n}": {**page(n, s), "org": org} for n, s, org in LONGP}}}))
def item(i, owner, proj, subj, status="open", desc="A fixture item.", age=3 * H, **md):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subj, "description": desc, "status": status,
        "metadata": {"owner": owner, "project": proj, **md}, "updated": (now - age).timestamp(), "state_updated": (now - age).timestamp()}))
for j, (n, s, org) in enumerate(LONGP):
    sid = f"{j + 50:08d}-5555-4555-8555-555555555555"; sess[sid] = {"name": s, "machine": "a", "url": "https://claude.ai/code/session_" + s, "seen": "x"}
    item(20 + j, sid, f"projects/{n}", f"[home] a long item subject for {n} that goes on for a while", needs=["decision", "external", ""][j % 3], priority="p2", next="do the thing", contact=s)      # a long project name and a long owner on one line
    item(40 + j, sid, f"projects/{n}", f"[home] second item for {n}", priority="p3", contact=LONG if j % 2 else s)      # the owner with a pane (a link) and a name no pane carries (text)
(T / "fleet/a/sessions.json").write_text(json.dumps(sess))
item(1, A, "projects/alpha", f"[home] an item page with long monospace, code and links: {LONG}", needs="decision", priority="p1",
     ask="Decide: whether `~/.local/share/stackshot/a/long/path/that/does/not/break/anywhere/config.toml` moves · Recommend: yes · Stakes: low · By: Fri",
     next="run `uv run --locked tests/pilot_scenario.py --a-very-long-flag-name-that-does-not-wrap=tests/fixtures/a/long/path/x.json`\n"
          "open https://github.com/example-owner/stackshot/pull/7123456789/files#diff-0123456789abcdef0123456789abcdef0123456789abcdef",
     work=[{"id": "w1", "text": f"a step done by {LONG}", "state": "in progress", "agent": LONG, "ts": (now - 2 * H).timestamp()}],
     desc="A long path: `docs/roles/background/a/very/long/path/with/no/spaces/anywhere/in/it.md`. A long link: "
          "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGhIjKlMnOp/edit#heading=h.abcdefghijkl.\n\n"
          "- a list item with `docs/roles/background/a/very/long/path/with/no/spaces/anywhere/in/it.md`\n  - a nested one with **bold** and *italic*\n    - and one deeper: " + LONG + "\n\n"
          "> a quote with a long word: " + LONG + "\n\n"
          "```\nuv run --locked tests/pilot_scenario.py --a-very-long-flag-name-that-does-not-wrap=tests/fixtures/a/long/path/x.json --and-another-one=1\n```")
item(2, X, "projects/alpha", "[home] held for a while", hold=True, priority="p3")
# next as a checklist: two steps done, one dropped, two still open, with long text and a command, to be measured and photographed at phone width
CLX = "ops-falcon-engineer"
item(80, A, "projects/alpha", "[home] a checklist with done, dropped and open steps", age=2 * H, needs=[CLX],
     next=f"{CLX}: draw the checklist on the item page and check it at 360 px with `ul.inext`, a long path ~/.local/share/stackshot/shots/cl-itempage-360-dark.png and a long link https://github.com/example-owner/stackshot/pull/7123456789/files\n"
          "Oliver: look at the page and say whether the dimming reads right",
     steps=[{"text": f"{CLX}: add the steps module and its tests", "status": "done", "by": CLX, "at": (now - 5 * H).timestamp()},
            {"text": "Oliver: run `sala op reauth box-a --from me --words \"go\"`", "status": "done", "by": "Oliver", "at": (now - 3 * H).timestamp()},
            {"text": f"{CLX}: also back-fill the old items from their History", "status": "dropped", "by": CLX, "at": (now - 2 * H).timestamp()},
            {"text": f"{CLX}: draw the checklist on the item page and check it at 360 px with `ul.inext`, a long path ~/.local/share/stackshot/shots/cl-itempage-360-dark.png and a long link https://github.com/example-owner/stackshot/pull/7123456789/files", "status": "open"},
            {"text": "Oliver: look at the page and say whether the dimming reads right", "status": "open"}])
# a your-step item whose Next holds his own lines with commands and the agent's: the Your step block shows his in full with copy boxes, Next stays whole
item(81, A, "projects/alpha", "[home] his Next lines in the Your step block", age=1 * H, state="your-step", needs=[CLX], step="One line in PowerShell on your Windows laptop",
     next=f"{CLX}: put the box in place\n"
          "Oliver: In PowerShell run `ssh -t box-a 'sala op reauth ops-falcon-engineer-background-builder-with-a-long-name --from me --words \"go\"'` and read the answer\n"
          "Oliver: then check the file ~/.local/share/stackshot/shots/cl-yourstep-360-dark.png with `Get-Item $HOME\\Documents\\a\\very\\long\\path\\that\\does\\not\\break\\anywhere\\notes.txt` and paste the size\n"
          f"{CLX}: read what he pasted")
# the home page's lists (part 1): a row of each kind with long text, so every list and every ask form is measured at phone width
M = datetime.timedelta(minutes=1); DAYS = datetime.timedelta(days=1)
# open items he does not move, one per state, for the comment box that takes the answer box's slot: doing, waiting on a date, verifying
item(90, A, "projects/alpha", "[home] a doing item with a title of a reasonable length", age=1 * H, needs=[CLX], next=f"{CLX}: do the work and say when it is done")
item(91, A, "projects/alpha", "[home] a wait on a date", age=1 * H, needs=["external"], wait_kind="time", wake=(now + 8 * DAYS).strftime("%Y-%m-%d"), post_wake_mover=CLX, next=f"{CLX}: check the date")
item(92, A, "projects/alpha", "[home] a verifying item", age=1 * H, state="verifying", proof="the link opens on the phone", end=(now + 3 * DAYS).strftime("%Y-%m-%d"), needs=[CLX], next=f"{CLX}: check the link")
item(60, A, "projects/alpha", "[home] a decision with a long question and options whose labels run long", age=6 * DAYS, needs=["decision"], next="Oliver: answer the ask",      # its mockup link: Mockup ↗ beside the long question
     desc="- The layout is drawn in [the mockup](https://claude.ai/artifact/00000000-0000-4000-8000-000000000052)",
     ask="Decide: whether `~/.local/share/stackshot/a/long/path/that/does/not/break/anywhere/config.toml` moves before the long weekend · Recommend: yes · Stakes: low · By: Fri",
     options=[{"label": "Move it now, before the long weekend", "line": "Move it today.", "recommended": True}, {"label": "Move it Monday morning", "line": "Wait.", "recommended": False},
              {"label": "Leave it where it is for good and close the question", "line": "Leave it.", "recommended": False}, {"label": "Ask the keeper first", "line": "Ask.", "recommended": False}])
item(61, A, "projects/alpha", "[home] a step with a long command", age=3 * DAYS, needs=["decision"],
     next="Oliver: run `uv run --locked tests/pilot_scenario.py --a-very-long-flag-name-that-does-not-wrap=tests/fixtures/a/long/path/x.json` and send me the result")
item(65, A, "projects/alpha", "[home] a step item with a long command", age=2 * DAYS, state="your-step", needs=["ops-falcon-engineer"],
     step="run the one line `uv run --locked tests/pilot_scenario.py --a-very-long-flag-name-that-does-not-wrap=tests/fixtures/a/long/path/x.json` on box-a and say done", next="ops-falcon-engineer: check it")
item(66, A, "projects/alpha", "[home] a step item typed in a pane", age=1 * DAYS, state="your-step", step="! sala op reauth ops-falcon-engineer-background-builder-with-a-long-name --from me --words \"go\"", next="ops-falcon-engineer: check it")
item(67, A, "projects/alpha", "[home] a step item of plain words", age=1 * DAYS, state="your-step", step="Open the side gate and tell the guard the long-named visitor " + LONG + " is on the way, then say done", next="ops-falcon-engineer: check it",
     draft="こんにちは、オリバーです。\n\n  - 第一: 日程はそのままです。 " + LONG + "\n  - 第二: https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGhIjKlMnOp/edit#heading=h.abcdefghijkl\n\nよろしくお願いします。\nThanks, Alex.")   # a draft (draft.py): the block wraps and keeps its lines, the row's "draft" label, with Copy beside it, fits
item(68, A, "projects/alpha", "[home] a numbered step with two ssh commands", age=1 * DAYS, state="your-step", step="In PowerShell, do these in order:\n1. Run `ssh -t box-a 'sala op reauth ops-falcon-engineer-background-builder-with-a-long-name --from me --words \"go\"'` and wait for the line that says queued\n2. Run `ssh -t box-a 'tmux ls'` and read the list\n3. Say done on the item", next="ops-falcon-engineer: check it")   # a numbered step (step_commands.py): one list, a copy block per command
item(69, A, "projects/alpha", "[home] Move the widget to shelf-2 and let it sync by itself when shelf-1 is full", age=4 * H, needs=["decision"], next="Oliver: decide", contact=LONG,       # a long Your move title is cut on the top line while the age stays at the right edge
     ask="Decide: how a returning shelf-1 is kept from syncing beside shelf-2 after a switch · Recommend: Check at boot · Stakes: low · By: Fri",
     options=[{"label": "Check at boot", "line": "Check at boot.", "recommended": True}, {"label": "Block the sync only", "line": "Block it.", "recommended": False}])
item(62, X, "projects/alpha", "[home] handed over to a session with a long name", age=10 * M, needs=["ops-falcon-engineer"], mover="ops-falcon-engineer", next="ops-falcon-engineer: take it",
     handoff={"to": "ops-falcon-engineer", "from": "ops-falcon-main", "at": (now - 10 * M).timestamp(), "delivered_at": (now - 9 * M).timestamp(), "taken_at": None},
     woke={"what": "the wake day came for " + LONG, "to": "ops-falcon-engineer", "at": (now - 10 * M).timestamp()})
item(63, A, "projects/alpha", "[home] a wait on an anchor with a long address", age=2 * DAYS, needs=["external"], wait_kind="anchor", post_wake_mover="ops-falcon-engineer", next="ops-falcon-engineer: deploy it",
     wait_anchor="https://example.invalid/example-owner/stackshot/pull/7123456789/files#diff-0123456789abcdef0123456789abcdef0123456789abcdef", wait_event="the pull request with the very long name " + LONG + " merges",
     wake=(now + 9 * DAYS).strftime("%Y-%m-%d"), chases=[{"at": (now - 60 * M).timestamp(), "by": "x", "note": "mailed"}, {"at": (now - 30 * M).timestamp(), "by": "x", "note": "mailed again"}])
item(64, A, "projects/alpha", "[home] a relay come due", age=20 * M, needs=["decision"], ask="Decide: has the party's reply with a very long name arrived? · Options: arrived / not yet, ask again on <date> / drop", then="ops-falcon-engineer",
     options=[{"label": "arrived", "line": "It came.", "recommended": False}, {"label": "not yet, ask again on <date>", "line": "Give the date in the box.", "recommended": True}, {"label": "drop", "line": "No longer wanted.", "recommended": False}],
     woke={"what": "the ask-by day came", "to": "Oliver", "at": (now - 20 * M).timestamp()}, next="ops-falcon-engineer: read the reply")
# a Waiting row of each wait kind: a time wait with a then-mover that is long, an item wait, a relay, an anchor wait whose anchor is only scoped to the item, one with no anchor anywhere (no watcher), a time wait with no date (no watcher)
item(71, A, "projects/alpha", "[home] a time wait with a long then-mover and a goal that wraps onto a second line at phone width", age=2 * DAYS, hold=True, wake=(now + 3 * DAYS).strftime("%Y-%m-%d"), post_wake_mover=LONG, next=f"{LONG}: take it after the wake")
item(72, A, "projects/alpha", "[home] an item wait", age=2 * DAYS, after=["a2"], post_wake_mover="ops-falcon-engineer", next="ops-falcon-engineer: continue once a2 closes")
item(73, A, "projects/alpha", "[home] a relay", age=2 * DAYS, needs=["external"], wait_kind="relay", wait_event="the reviewer with a rather long name indeed", ask_by=(now + 5 * DAYS).strftime("%Y-%m-%d"), post_wake_mover="ops-falcon-engineer", next="Oliver: nothing yet")
item(74, A, "projects/alpha", "[home] an anchor wait with no anchor recorded", age=2 * DAYS, needs=["external"], wait_kind="anchor", wait_event="the vendor answers", wake=(now + 8 * DAYS).strftime("%Y-%m-%d"), post_wake_mover="ops-falcon-engineer", next="ops-falcon-engineer: look again")
item(75, A, "projects/alpha", "[home] an anchor wait whose anchor is scoped to the item", age=2 * DAYS, needs=["external"], state="outside", party="the vendor", wake=(now + 8 * DAYS).strftime("%Y-%m-%d"), next="ops-falcon-engineer: read the thread when it moves")
item(76, A, "projects/alpha", "[home] a time wait with no date", age=2 * DAYS, hold=True, next="ops-falcon-engineer: someone must look")
item(3, A, "projects/alpha", "[home] done last week", status="completed", outcome="done", reason="shipped", priority="p2")
# a waiting item (the item model's page step 3): a long goal, an anchor wait with a long URL and event, a long post-wake mover, two chases, five next lines (two fold as "+2 more")
item(4, A, "projects/alpha", "[home] waiting on a reply", goal="Get the reply that unblocks " + LONG + " and the tests/fixtures/a/long/path/that/does/not/break/anywhere/x.json", wait_kind="anchor",
     wait_anchor="https://github.com/example-owner/stackshot/pull/7123456789/files#diff-0123456789abcdef0123456789abcdef0123456789abcdef", wait_event="the review of " + LONG + " comes back",
     post_wake_mover=LONG, wake="2099-01-01", priority="p2", party="a reviewer with a rather long name indeed",
     chases=[{"at": now.timestamp() - 3600, "by": LONG, "note": "asked again in " + "a-very-long-unbroken-token-" * 6}, {"at": now.timestamp() - 1800, "by": "ops-falcon", "note": "no reply yet"}],
     next="\n".join(f"{LONG}: step {k} " + "x" * 60 for k in range(1, 6)))
# the Task board table at every width: many ids in each of the three id columns of one project, whose agents carry long names
for k in range(12):
    item(100 + k, X, "projects/alpha", f"[home] on-agent item {k}", priority="p3")
    item(120 + k, X, "projects/alpha", f"[home] your-call item {k}", needs=["decision"], ask="Decide: x · Recommend: yes · Stakes: low · By: Fri", priority="p3")
    item(140 + k, X, "projects/alpha", f"[home] on-others item {k}", needs=["external"], wait_kind="date", wake="2099-01-01", priority="p3")
# a project with verifying items: its open cell carries the verifying count on a second line (hidden on a phone, in the cell's title)
for k in range(3): item(160 + k, X, "projects/project-with-a-very-long-example-name-04", f"[home] verifying item {k}", state="verifying", proof="uptime 200 for 3 days", end="2099-01-01", priority="p3")
# a temporary id (the longest a number gets), a long mover and a due badge on one row: the goal must keep its room (the board item review)
(T / "store/l").mkdir()
(T / "store/l/3.json").write_text(json.dumps({"id": "3", "subject": "[home] a temporary id with a long mover and a due date, and a goal that wraps", "description": "x", "status": "open",
    "metadata": {"owner": f"{2 + 50:08d}-5555-4555-8555-555555555555", "project": "projects/alpha", "next": "do the thing", "due": (now + 5 * DAYS).strftime("%Y-%m-%d")}, "updated": (now - 3 * H).timestamp(), "state_updated": (now - 3 * H).timestamp()}))
(T / "store/next-id").write_text("200")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [
    {"url": "https://x.slack.com/archives/C0000000001", "items": None, "added": 1, "by": "t"},
    {"url": "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789AbCdEfGhIjKlMnOp/edit#gid=0", "items": ["a1"], "added": 1, "by": "t"},
    {"url": "https://github.com/example-owner/stackshot/pull/7123456789/files#diff-0123456789abcdef0123456789abcdef0123456789abcdef", "items": ["a75"], "added": 2, "by": "t"}]}))
sys.path.insert(0, STACK)
from stackshot.router import routing; from stackshot.web import runners          # runners: the snapshot and repo helpers; the pages are drawn by the ui package
from stackshot.web.ui import render, runners as ui_runners, search as ui_search
runners.AUTOSTART = False; runners.reset()      # the Runners section is drawn from a snapshot we hand it (a card per box, no GitHub, no ssh), not "not read yet"
runners._CACHE["snap"] = {"ts": time.time(), "failed": [], "runners": [
    {"box": "box-a", "repo": r, "state": st, "name": f"box-a-{r}-{i}", "kind": "", "reason": "", "job": None}
    for r in runners._repos() for i, st in enumerate(("running", "idle"))] + [
    {"box": "box-b", "repo": r, "state": "idle", "name": f"box-b-{r}", "kind": "", "reason": "", "job": None} for r in runners._repos()] + [
    {"box": "box-c", "repo": r, "state": "offline", "name": f"box-c-{r}", "kind": "fault", "reason": "x", "job": None} for r in runners._repos()] + [
    {"box": "other", "repo": runners._repos()[0], "state": "running", "name": f"other-{i}", "kind": "", "reason": "", "job": None} for i in range(2)]}      # every runner busy reads "full"
from stackshot.core import ghbudget as _gb
_led = runners._cfg.state("github", _gb.LEDGER_NAME); _led.parent.mkdir(parents=True, exist_ok=True)
_led.write_text(json.dumps({_gb.WRITE: [time.time() - 30 * i for i in range(15)], _gb.READ: [time.time() - 10 * i for i in range(204)]}), encoding="utf-8")      # the GitHub calls card: 15 writes, 204 reads in the hour
for j, (lab, who, txt) in enumerate([("Slack #stackshot", "Dana", "can the project page list its items too?"),
        ("GitHub PR #19 https://github.com/example-owner/stackshot/pull/19/files#diff-0123456789abcdef0123456789abcdef", LONG,
         "a notice with a long unbroken token: tests/fixtures/a/very/long/path/name/without/any/space.json")]):
    routing.record("projects/alpha", kind="anchor", to="ops-falcon", label=lab, who=who, text=txt, url="https://example.invalid/n", target="project-wide", pilot=True, ts=time.time() - 600 * (j + 1))
# the Landed list: closes of agents in long-named projects, by sessions with long names, one by the server's own done check, five uncleared and one cleared, some with a long close reason: the header's Landed link and the Landed page are measured
from stackshot.web import landed
for k, (n, by) in enumerate([("project-with-a-very-long-example-name-01", LONG), ("project-with-a-very-long-example-name-02", "ops-falcon-main"), ("infrastructureandtoolingwithoutanyhyphensatallverylongname", ""),
                             ("alpha", LONG), ("alpha", "ops-falcon-engineer"), ("short-project", LONG)]):
    gid = 180 + k; pk = f"projects/{n}"
    item(gid, X, pk, f"[home] landed item {k} with a long subject that wraps at phone width: {LONG} /opt/example/very/long/path/that/does/not/break/anywhere/x.json", status="completed", age=(k + 1) * H, outcome="dropped" if k % 3 == 1 else "done", reason=(f"PR {k} is live and the nightly run is green {LONG} /opt/example/very/long/path/that/does/not/break/anywhere/x.json" if k % 2 == 0 else "done"), contact=LONG if k % 2 == 0 else "ops-falcon-main")      # a long owner name on the Closed page's project line, and a live one
    landed.record(f"a{gid}", (now - (k + 1) * H).timestamp(), "dropped" if k % 3 == 1 else "done", by=by, project=pk)
landed.clear([landed.key(f"a{gid}", (now - 6 * H).timestamp())], now=now.timestamp())      # the last of the six (gid, k=5) is the cleared one
b = render.Board(str(T / "store"), now=now)
OUT = T / "out"
(OUT / "index.html").write_text(b.html(), encoding="utf-8")
(OUT / "project.html").write_text(b.routing_html("projects/alpha"), encoding="utf-8")
(OUT / "items/a1.html").write_text(b.item_html("a1"), encoding="utf-8")
(OUT / "items/a4.html").write_text(b.item_html("a4"), encoding="utf-8")
(OUT / "items/a60.html").write_text(b.item_html("a60", answer={"action": "/items/a60/answer", "token": "T", "sent": ""}), encoding="utf-8")   # the owner's decision item, with its answer box
(OUT / "items/a3.html").write_text(b.item_html("a3"), encoding="utf-8")
(OUT / "items/cl1.html").write_text(b.item_html("a80"), encoding="utf-8")      # next as a checklist: done, dropped and open steps
(OUT / "items/cl2.html").write_text(b.item_html("a81", answer={"action": "/items/a81/answer", "token": "T", "sent": ""}), encoding="utf-8")   # a your-step item with his own Next lines: copy boxes in the Your step block, and Next whole
(OUT / "landed.html").write_text(b.landed_html(), encoding="utf-8")      # the Landed page
for _g, _fn in (("a90", "cb-doing"), ("a91", "cb-waiting"), ("a92", "cb-verifying")):      # the open items he does not move: the comment box in the answer box's slot
    (OUT / f"items/{_fn}.html").write_text(b.item_html(_g, answer={"action": f"/items/{_g}/answer", "token": "T", "sent": ""}), encoding="utf-8")
(OUT / "items/a67.html").write_text(b.item_html("a67", answer={"action": "/items/a67/answer", "token": "T", "sent": ""}), encoding="utf-8")   # a your-step item with a long draft: its block and Copy button
(OUT / "items/a68.html").write_text(b.item_html("a68", answer={"action": "/items/a68/answer", "token": "T", "sent": ""}), encoding="utf-8")   # a numbered your-step item: the list and its two command blocks
# pages whose latest History entry has a long author and a long text, a step item and an ask item
_item_log = b.item_log
b.item_log = lambda r, merge=True: ([{"ts": (now - 7 * H).timestamp(), "kind": "edit", "html": "", "who": LONG, "what": "subject edited: " + LONG + " " + "x" * 30 + " /opt/example/very/long/path/that/does/not/break/anywhere/config.toml " + "y" * 60, "comment": False, "mark": ""}], 0)
(OUT / "items/a69.html").write_text(b.item_html("a68", answer={"action": "/items/a68/answer", "token": "T", "sent": ""}), encoding="utf-8")
b.item_log = lambda r, merge=True: ([{"ts": (now - 2 * H).timestamp(), "kind": "needs", "html": "", "who": LONG, "what": "needs: decision; state: your-call; next and ask edited", "comment": False, "mark": ""}], 0)   # the real clauses, in plain words (itempage.plain_change)
(OUT / "items/a70.html").write_text(b.item_html("a60", answer={"action": "/items/a60/answer", "token": "T", "sent": ""}), encoding="utf-8")
b.item_log = _item_log
# a second render two minutes later with the machines card changed (claude code 2.1.140 → 2.1.141 on a): what the in-place update swaps in
_vj = json.loads((T / "state/site/versions.json").read_text()); _vj["packages"][0]["machines"]["a"] = "2.1.141"; (T / "state/site/versions.json").write_text(json.dumps(_vj))
b2 = render.Board(str(T / "store"), now=now + datetime.timedelta(minutes=2))
(OUT / "index2.html").write_text(b2.html(), encoding="utf-8")
# the Audit card in six states: the page the server draws and the status JSON the page script reads (the script draws the same rows)
from stackshot.audit import audit as _audit; from stackshot.audit import audit_overview as _ov
AUDIT_STATES = {}
(OUT / "audits-findings.html").write_text(render.Board(str(T / "store"), now=now).audits_html(), encoding="utf-8")      # the Audits page with findings and a finished run
_ago = lambda h: (now - h * H).timestamp()
for _nm, _rec in (("none", None),
                  ("findings", {"started": _ago(20), "finished": _ago(20) + 1200, "findings": [{"id": "a1"}, {"id": "a2"}], "by_category": {"stale": 1, "no-ask": 1}}),
                  ("one", {"started": _ago(20), "finished": _ago(20) + 600, "findings": [{"id": "a1"}], "by_category": {"stale": 1}}),
                  ("zero", {"started": _ago(20), "finished": _ago(20) + 600, "findings": []}),
                  ("running", {"started": now.timestamp() - 300, "finished": None, "findings": []}),
                  ("crashed", {"started": _ago(5), "finished": None, "findings": []}),
                  ("crashed-no-start", {"finished": None, "findings": []})):
    audit_run(_rec)
    (OUT / f"audit-{_nm}.html").write_text(render.Board(str(T / "store"), now=now).html(), encoding="utf-8")
    AUDIT_STATES[_nm] = {**_audit.status(now.timestamp()), "card": _ov.card(now.timestamp())}
audit_run(None)
findings_log(False)
(OUT / "audits-empty.html").write_text(render.Board(str(T / "store"), now=now).audits_html(), encoding="utf-8")      # ... and with nothing yet: no run, no findings
from stackshot.web import search
(OUT / "runners.html").write_text(ui_runners.page_html(b, {"errors": {}, **runners._CACHE["snap"]}), encoding="utf-8")   # the Runners page: the same title bar and side panel, from the snapshot handed above
# the Runners column, one runner per line: a machine with six runners (long names)
_six = {"errors": {}, **runners._CACHE["snap"], "runners": [{"box": "box-a", "repo": runners._repos()[0], "state": st, "name": f"box-a-{runners._repos()[0]}-runner-{i}", "kind": "", "reason": "", "job": None}
        for i, st in enumerate(("running", "idle", "idle", "offline", "running", "idle"))] + [x for x in runners._CACHE["snap"]["runners"] if x["box"] != "box-a"]}
(OUT / "runners-six.html").write_text(ui_runners.page_html(b, _six), encoding="utf-8")
RUNNER_LISTS = {"runners page": OUT / "runners-six.html"}
# the pages that start with home's header: the title, the five count cards and the search box
HEADER_PAGES = {"item": b.item_html("a1"), "item (answer box)": b.item_html("a60", answer={"action": "/items/a60/answer", "token": "T", "sent": ""}), "project": b.routing_html("projects/alpha"),
                "Projects": b.projects_html(), "Closed": b.landed_html(), "Search": None, "runners": None, "Audits": (OUT / "audits-findings.html").read_text(encoding="utf-8")}
HEADER_FILES = {}
search.sync(b); (OUT / "results.html").write_text(ui_search.results_html(b, "item"), encoding="utf-8")   # the search's results page: its results are the fixture's items, projects and sessions
HEADER_PAGES["Search"] = ui_search.results_html(b, "item"); HEADER_PAGES["runners"] = ui_runners.page_html(b, _six)
for _nm, _html in HEADER_PAGES.items():
    HEADER_FILES[_nm] = OUT / ("header-page-" + re.sub(r"\W+", "-", _nm).strip("-") + ".html"); HEADER_FILES[_nm].write_text(_html, encoding="utf-8")
PAGES = {"board": OUT / "index.html", "project page": OUT / "project.html", "landed page": OUT / "landed.html", "item page": OUT / "items/a1.html", "results page": OUT / "results.html", "runners page": OUT / "runners.html", "audits page": OUT / "audits-findings.html", "audits page (empty)": OUT / "audits-empty.html", "item page (waiting)": OUT / "items/a4.html", "item page (closed)": OUT / "items/a3.html", "step page (with a draft)": OUT / "items/a67.html", "step page (numbered)": OUT / "items/a68.html", "step page (long history entry)": OUT / "items/a69.html", "ask page (long history entry)": OUT / "items/a70.html", "checklist page": OUT / "items/cl1.html", "step page (his Next lines)": OUT / "items/cl2.html",
         "comment box (doing)": OUT / "items/cb-doing.html", "comment box (waiting)": OUT / "items/cb-waiting.html", "comment box (verifying)": OUT / "items/cb-verifying.html", "comment box (decision)": OUT / "items/a60.html"}


def _rgb(c):
    v = [float(x) for x in re.findall(r"[\d.]+", c)]
    return v[:3], (v[3] if len(v) > 3 else 1.0)
def _lum(c):
    ch = [(x / 255) / 12.92 if x / 255 <= 0.03928 else ((x / 255 + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
def contrast(fg, bg, page):       # a transparent background takes the page's
    (f, _), (g, a), (pg_, _) = _rgb(fg), _rgb(bg), _rgb(page)
    g = g if a > 0.5 else pg_
    hi, lo = sorted((_lum(f), _lum(g)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
BG = {"light": "rgb(250, 250, 248)", "dark": "rgb(22, 22, 23)"}   # each theme's --bg (#fafaf8, #161617)

fails, ran = [], []
def check(name, cond, got=None):
    ran.append(name); print(("ok   " if cond else "FAIL ") + name + ("" if cond or got is None else f": {got}"))
    if not cond: fails.append(name)

OPEN = "() => { document.querySelectorAll('details.fold, .hdraft details').forEach(d => d.open = true); document.querySelectorAll('form.hanswer').forEach(f => f.hidden = false); }"      # every fold open (a row's draft too), every ask form shown (the page script shows them for a signed-in viewer)
WIDE = """() => { const vw = document.documentElement.clientWidth, out = [];
  const clipped = el => { for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) if (getComputedStyle(p).overflowX !== 'visible') return true; return false; };
  for (const el of document.body.querySelectorAll('*')) { const r = el.getBoundingClientRect();
    if (r.width && r.right > vw + 0.5 && !clipped(el)) out.push(el.tagName.toLowerCase() + '.' + [...el.classList].join('.') + ' right=' + Math.round(r.right)); }
  return [document.documentElement.scrollWidth, vw, out.slice(0, 5)]; }"""
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    try: br = p.chromium.launch(args=["--enable-features=OverlayScrollbar"])       # overlay scrollbars, as on a phone: hidden here, and with the flag the stylesheet's scrollbar-gutter reserves nothing (headless Chromium's hidden scrollbars alone still reserve it)
    except Exception as e:
        print(f"no browser: {str(e).splitlines()[0][:200]}\n  install it once: uvx playwright@1.63.0 install chromium"); sys.exit(1)
    for nm, f in PAGES.items():
        for scheme in ("light", "dark"):
            for w in (360, 390, 412, 430):
                ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page()
                pg.goto(f.as_uri()); pg.evaluate(OPEN); pg.wait_for_timeout(50)
                sw, vw, wide = pg.evaluate(WIDE)
                check(f"{nm} {w} {scheme}: the page is the screen's width with every fold open", sw == vw == w, (sw, vw, wide))

                if w == 412:
                    bg, cs = pg.evaluate("[getComputedStyle(document.documentElement).backgroundColor, getComputedStyle(document.documentElement).colorScheme]")
                    check(f"{nm} {scheme}: the root paints the theme's --bg and carries its color-scheme", bg == BG[scheme] and cs == scheme, (bg, cs))
                ctx.close()
        # the switch's saved choice over the system, before the first paint
        for saved, system in (("dark", "light"), ("light", "dark")):
            ctx = br.new_context(viewport={"width": 412, "height": 900}, color_scheme=system)
            ctx.add_init_script(f"try{{localStorage.setItem('stackshot-theme','{saved}')}}catch(e){{}}"); pg = ctx.new_page(); pg.goto(f.as_uri())
            bg, cs = pg.evaluate("[getComputedStyle(document.documentElement).backgroundColor, getComputedStyle(document.documentElement).colorScheme]")
            check(f"{nm}: {saved} chosen on a {system} system → the root paints {saved}", bg == BG[saved] and cs == saved, (bg, cs))
            ctx.close()
    # ---- the search box: on every page, inside the screen at 360 px and wide enough to type in, the theme button clear of it
    for nm, f in PAGES.items():
        if nm == "runners page": continue      # the Runners page has never had the search box (the board item gave it the title bar and panel only)
        for w in (360, 1440):
            ctx = br.new_context(viewport={"width": w, "height": 900}); pg = ctx.new_page(); pg.goto(f.as_uri())
            d = pg.evaluate("() => { const i = document.querySelector('form.sbox input'), t = document.querySelector('#theme'); if (!i) return null; const r = i.getBoundingClientRect(), q = t.getBoundingClientRect(); "
                            "return {n: document.querySelectorAll('form.sbox').length, l: r.left, r: r.right, w: r.width, h: r.height, t: r.top, b: r.bottom, tl: q.left, tr: q.right, tt: q.top, tb: q.bottom}; }")
            check(f"search box {nm} {w}: one box, inside the screen, 200 px or wider, 28 px or taller, clear of the theme button", bool(d) and d["n"] == 1 and d["l"] >= 0 and d["r"] <= w + 0.5 and d["w"] >= 200 and d["h"] >= 28
                  and (d["r"] <= d["tl"] + 0.5 or d["l"] >= d["tr"] - 0.5 or d["b"] <= d["tt"] + 0.5 or d["t"] >= d["tb"] - 0.5), d)
            ctx.close()
    # ---- the item page's Your step block with a draft: "Draft" label with Copy beside it, right under the step's text, above the note box and buttons, in the body font, inside the screen
    DSHOTS = os.environ.get("PHONE_WIDTH_SHOTS", "")
    ITEMDRAFT = """() => { const o = [], d = document.querySelector('.istepbody .draft'), form = document.querySelector('form.ianswer'), vw = innerWidth; if (!d || !form) return ['no draft or no form'];
      const lab = d.querySelector('.dhead .dlab'), btn = d.querySelector('.dhead button.copy'), pre = d.querySelector('pre'), c = pre.querySelector('code'), body = getComputedStyle(document.body).fontFamily;
      const l = lab.getBoundingClientRect(), b = btn.getBoundingClientRect(), r = d.getBoundingClientRect(), sb = document.querySelector('.istepbody'), rg = document.createRange(), f = form.getBoundingClientRect(); rg.setStart(sb, 0); rg.setEndBefore(d); const txt = rg.getBoundingClientRect();
      if (Math.abs((l.top + l.bottom) / 2 - (b.top + b.bottom) / 2) > 8) o.push('Copy is not on the label line'); if (b.left - l.right < 0 || b.left - l.right > 24) o.push('Copy is not just beside the label: ' + Math.round(b.left - l.right));
      if (r.top < txt.bottom - 1) o.push('the draft is not under the step text'); if (r.bottom > f.top + 1) o.push('the draft is not above the note box');
      if (getComputedStyle(c).fontFamily !== body || /mono/i.test(getComputedStyle(c).fontFamily)) o.push('not the body font: ' + getComputedStyle(c).fontFamily);
      if (getComputedStyle(pre).whiteSpace !== 'pre-wrap' || r.left < -0.5 || r.right > vw + 0.5 || pre.scrollWidth > pre.clientWidth + 1) o.push('wrap or fit: ' + getComputedStyle(pre).whiteSpace + ' ' + Math.round(r.right));
      if (d.closest('.cmd') || d.classList.contains('cmd')) o.push('drawn as a command block'); return o; }"""
    for scheme in ("light", "dark"):
        for w in (360, 412):
            ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES["step page (with a draft)"].as_uri()); pg.wait_for_timeout(100)
            idr = pg.evaluate(ITEMDRAFT)
            check(f"step page {w} {scheme}: the draft is under the step's text with Copy beside its label, above the note box and buttons, in the body font, inside the screen", idr == [], idr)
            if DSHOTS and scheme == "light" and w == 412:
                pg.evaluate("document.querySelectorAll('header, .conn, #reload, #totop').forEach(e => e.style.display = 'none')"); pg.wait_for_timeout(50)
                pg.locator(".istep").screenshot(path=os.path.join(DSHOTS, "draft-itempage-yourstep-412-light.png"))
                pg.locator("form.ianswer").scroll_into_view_if_needed(); pg.screenshot(path=os.path.join(DSHOTS, "draft-itempage-412-light.png"), full_page=True)
            ctx.close()
    # a numbered step (step_commands.py): one ordered list, a copy block with its Copy button under each command item, all inside the screen, the commands in the code font
    STEPLIST = """(root) => { const o = [], vw = innerWidth, ol = root.querySelector('ol.stepol'); if (!ol) return ['no list'];
      const lis = [...ol.children]; if (lis.length !== 3) o.push('items: ' + lis.length); if (getComputedStyle(ol).listStyleType !== 'decimal') o.push('not numbered: ' + getComputedStyle(ol).listStyleType);
      const blocks = [...ol.querySelectorAll('.cmd')]; if (blocks.length !== 2) o.push('blocks: ' + blocks.length);
      for (const c of blocks) { const r = c.getBoundingClientRect(), pre = c.querySelector('pre'), b = c.querySelector('button.copy'), br = b.getBoundingClientRect(), code = c.querySelector('code');
        if (r.left < -0.5 || r.right > vw + 0.5) o.push('a block is outside the screen: ' + Math.round(r.left) + '..' + Math.round(r.right));
        if (pre.scrollWidth > pre.clientWidth + 1) o.push('a command scrolls sideways'); if (br.right > r.right + 0.5 || br.left < r.left - 0.5) o.push('Copy is outside its block');
        if (!/D2Coding|mono/i.test(getComputedStyle(code).fontFamily)) o.push('not the code font: ' + getComputedStyle(code).fontFamily); }
      for (let i = 0; i < 2; i++) if (!lis[i].querySelector('.cmd')) o.push('item ' + (i + 1) + ' has no block'); if (lis[2].querySelector('.cmd')) o.push('item 3 has a block');
      const t = ol.getBoundingClientRect(); if (t.left < -0.5 || t.right > vw + 0.5) o.push('the list is outside the screen'); return o; }"""
    for scheme in ("light", "dark"):
        for w in (360, 412):
            ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES["step page (numbered)"].as_uri()); pg.wait_for_timeout(100)
            sl = pg.evaluate("(" + STEPLIST + ")(document.querySelector('.istepbody'))")
            check(f"numbered step page {w} {scheme}: one numbered list of three items, two copy blocks under items 1 and 2 inside the screen with Copy in them, in the code font", sl == [], sl)
            sw, vw, wide = pg.evaluate(WIDE)
            check(f"numbered step page {w} {scheme}: the page is the screen's width", sw == vw == w, (sw, vw, wide))
            if DSHOTS and scheme == "light" and w == 412:
                pg.evaluate("document.querySelectorAll('header, .conn, #reload, #totop').forEach(e => e.style.display = 'none')"); pg.wait_for_timeout(50)
                pg.locator(".istep").screenshot(path=os.path.join(DSHOTS, "step-itempage-yourstep-412-light.png"))
                pg.locator("form.ianswer").scroll_into_view_if_needed(); pg.screenshot(path=os.path.join(DSHOTS, "step-itempage-412-light.png"), full_page=True)
            ctx.close()
    # the item page's order: the state line, Your step or the ask, then Next, Background, History, Comments; a History entry with a long author and a long text stays inside the screen
    BGORDER = """() => { const o = [], hs = [...document.querySelectorAll('main.itempage h2')].map(h => h.textContent.trim().replace(/\\s+\\d+\\+?$/, ''));
      if (document.querySelector('.iwhere, #where')) o.push('Where it stands is on the page'); if (hs.join('|') !== 'Next|Background|History|Comments') o.push('headings: ' + hs.join('|'));
      const q = s => document.querySelector(s), top = e => e ? e.getBoundingClientRect().top + scrollY : -1, first = q('.istep') || q('.iask'), sl = q('.istat');
      const seq = [q('h1'), sl, first, q('#next'), q('#description'), q('#history'), q('#comments')].map(top); for (let i = 1; i < seq.length; i++) if (seq[i] <= seq[i - 1]) o.push('order broken at ' + i + ': ' + seq.join(','));
      return o; }"""
    for scheme in ("light", "dark"):
        for w in (360, 412):
            for nm_, key_ in (("step", "step page (long history entry)"), ("ask", "ask page (long history entry)")):
                ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES[key_].as_uri()); pg.wait_for_timeout(100)
                bo = pg.evaluate(BGORDER)
                check(f"{nm_} page, long history entry {w} {scheme}: no Where it stands; Next, Background, History, Comments in order after the step or the ask", bo == [], bo)
                pg.evaluate(OPEN); pg.wait_for_timeout(50)
                sw, vw, wide = pg.evaluate(WIDE)
                check(f"{nm_} page, long history entry {w} {scheme}: the page is the screen's width", sw == vw == w, (sw, vw, wide))
                if DSHOTS and scheme == "light":
                    pg.evaluate("document.querySelectorAll('header, .conn, #reload, #totop').forEach(e => e.style.display = 'none')"); pg.wait_for_timeout(50)
                    pg.screenshot(path=os.path.join(DSHOTS, f"bg-itempage-{nm_}-{w}-light.png"), full_page=True); pg.screenshot(path=os.path.join(DSHOTS, f"bg-stateline-{nm_}-{w}-light.png"), clip={"x": 0, "y": 0, "width": w, "height": 330})
                ctx.close()
    # ---- the comment box takes the answer box's slot: on an open item he does not move (doing, waiting, verifying) it is drawn open under the state line, ahead of Next and the folds; on one he moves
    # (a decision) there is exactly one form. At 360, 390 and 430 px, light and dark, and 1280 px: the box is on the first screen without scrolling past the state line, whole (its text box and Send),
    # inside the screen, in the item page's one column on a phone and in the main column beside the sidebar when wide; the Comments fold stays closed and holds no form; no sideways scroll
    CBOX = """() => { const o = [], vw = document.documentElement.clientWidth, vh = innerHeight, q = s => document.querySelector(s), fs = [...document.querySelectorAll('form.ianswer')];
      if (fs.length !== 1) return ['forms: ' + fs.length]; const f = fs[0], r = f.getBoundingClientRect(), st = q('.istat'), sb = st.getBoundingClientRect(), ta = f.querySelector('textarea'), bt = f.querySelector('button[name=act]'),
        tb = ta.getBoundingClientRect(), bb = bt.getBoundingClientRect(), cm = q('#comments'), nx = q('#next');
      if (!f.hasAttribute('data-comment-only')) o.push('not the comment form'); if (bt.value !== 'comment') o.push('button: ' + bt.value); if (f.closest('details')) o.push('inside a fold');
      if (!r.height || getComputedStyle(f).display === 'none' || getComputedStyle(f).visibility === 'hidden' || ta.offsetHeight < 30) o.push('the box is not shown: ' + r.height + ' ' + ta.offsetHeight);
      if (scrollY !== 0) o.push('page not at the top: ' + scrollY);
      if (r.top < sb.bottom - 0.5) o.push('the box starts above the end of the state line: ' + Math.round(r.top) + ' < ' + Math.round(sb.bottom)); if (r.top - sb.bottom > 40) o.push('a gap of ' + Math.round(r.top - sb.bottom) + ' px under the state line');
      if (r.top >= vh || tb.bottom > vh + 0.5 || bb.bottom > vh + 0.5) o.push('the box is not whole on the first screen: text box to ' + Math.round(tb.bottom) + ', Send to ' + Math.round(bb.bottom) + ', screen ' + vh);
      if (r.left < -0.5 || r.right > vw + 0.5 || tb.right > vw + 0.5 || bb.right > vw + 0.5) o.push('outside the screen: ' + Math.round(r.left) + '..' + Math.round(r.right));
      if (cm.open || cm.querySelector('form, textarea, button')) o.push('the Comments fold is open or holds the form');
      if (nx.getBoundingClientRect().top < r.bottom - 0.5) o.push('Next starts above the box end');
      if (document.documentElement.scrollWidth !== vw) o.push('sideways scroll: ' + document.documentElement.scrollWidth + ' vs ' + vw); return o; }"""
    for scheme in ("light", "dark"):
        for w, h_ in ((360, 740), (390, 844), (430, 932), (1280, 800)):
            for key_ in ("comment box (doing)", "comment box (waiting)", "comment box (verifying)"):
                ctx = br.new_context(viewport={"width": w, "height": h_}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES[key_].as_uri()); pg.wait_for_timeout(100)
                cb = pg.evaluate(CBOX)
                check(f"{key_} {w} {scheme}: one comment form, open, under the state line and ahead of Next, whole on the first screen, inside it; the Comments fold closed with no form", cb == [], cb)
                if w == 1280:
                    side_ = pg.evaluate("() => { const f = document.querySelector('form.ianswer').getBoundingClientRect(), a = document.querySelector('.iside').getBoundingClientRect(); return [Math.round(f.right), Math.round(a.left)]; }")
                    check(f"{key_} {w} {scheme}: wide, the box is in the main column, left of the sidebar", side_[0] <= side_[1], side_)
                pg.evaluate(OPEN); pg.wait_for_timeout(50)
                sw, vw, wide = pg.evaluate(WIDE)
                check(f"{key_} {w} {scheme}: with every fold open the page is the screen's width", sw == vw == w, (sw, vw, wide))
                if DSHOTS and scheme == "light" and w == 390:
                    pg.evaluate("document.querySelectorAll('header, .conn, #reload, #totop').forEach(e => e.style.display = 'none')"); pg.wait_for_timeout(50)
                    pg.screenshot(path=os.path.join(DSHOTS, f"commentbox-{re.sub(r'[^a-z]+', '-', key_)}-{w}-light.png"))
                ctx.close()
    for scheme in ("light", "dark"):
        for w in (390, 1280):
            ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES["comment box (decision)"].as_uri()); pg.wait_for_timeout(100)
            one = pg.evaluate("() => [document.querySelectorAll('form.ianswer').length, document.querySelectorAll('form.ianswer textarea').length, document.querySelectorAll('form.ianswer[data-comment-only]').length, !!document.querySelector('#comments form, #comments textarea')]")
            check(f"comment box (decision) {w} {scheme}: the item he moves has the one answer form with its one text box, no second comment form, nothing in the Comments fold", one == [1, 1, 0, False], one)
            ctx.close()
    # ---- the home lists: Your move, On agent, Queued for release and Waiting, a row of every kind with long text. Folds as the page loads them (Your move and Queued for release open, On agent and Waiting
    # closed), then everything open and every ask form shown, at 360, 412 and 1440 px, light and dark: each row inside the screen, its top line (number, title, age) above its detail block,
    # the ask form (buttons, box) inside it, the age colours apart, the count links in place ----
    HSHOTS = os.environ.get("PHONE_WIDTH_SHOTS", "")
    if HSHOTS: os.makedirs(HSHOTS, exist_ok=True)
    ROWFIT = """() => { const vw = document.documentElement.clientWidth, out = [];
      for (const li of document.querySelectorAll('li.hrow')) { const r = li.getBoundingClientRect(), cs = getComputedStyle(li), top = li.querySelector('.ir-top'), tb = top.getBoundingClientRect(), ts = getComputedStyle(top), ti = li.querySelector('.ir-title'), tr = ti.getBoundingClientRect(), tis = getComputedStyle(ti),
          ag = li.querySelector('.ir-age'), ab = ag.getBoundingClientRect(), as = getComputedStyle(ag), idn = li.querySelector('.ir-id'), who = li.querySelector('.ir-who'), det = li.querySelector('.ir-det'), act = li.querySelector('.ir-act'), edge = r.right - parseFloat(cs.paddingRight);
        if (r.left < -0.5 || r.right > vw + 0.5 || li.scrollWidth > li.clientWidth + 1) out.push(li.id + ' fit ' + Math.round(r.left) + '..' + Math.round(r.right) + ' ' + li.scrollWidth + '/' + li.clientWidth);
        // one top line: a baseline-aligned flex row with an 8px gap, the title (its number first) taking the room and the age after it at the right edge
        if (ts.display !== 'flex' || ts.alignItems !== 'baseline' || ts.columnGap !== '8px' || ts.flexWrap !== 'nowrap') out.push(li.id + ' the top line is not a one-line baseline flex with an 8px gap: ' + ts.display + ' ' + ts.alignItems + ' ' + ts.columnGap + ' ' + ts.flexWrap);
        if (as.flexShrink !== '0' || as.whiteSpace !== 'nowrap') out.push(li.id + ' the age can shrink or wrap');
        if (ab.width < 10 || Math.abs(ab.right - edge) > 1.5) out.push(li.id + ' the age is not at the right edge: ' + Math.round(ab.right) + ' of ' + Math.round(edge));
        if (tr.right > ab.left + 0.5 || ab.top < tb.top - 1 || ab.bottom > tb.bottom + 1) out.push(li.id + ' the title and the age are not in one row in that order');
        // the title is whole: it wraps inside the room the age leaves, never cut with an ellipsis
        if (tis.textOverflow === 'ellipsis' || tis.overflow === 'hidden' || tis.whiteSpace === 'nowrap' || ti.scrollWidth > ti.clientWidth + 1) out.push(li.id + ' the title is cut or runs on: ' + tis.whiteSpace + ' ' + tis.textOverflow + ' ' + tis.overflow);
        if (!idn || !idn.textContent.trim() || idn.scrollWidth > idn.clientWidth + 1) out.push(li.id + ' the number is missing or cut');
        // under the top line: the mover line, the detail block and the answer form, each inside the row and in that order
        let prev = tb.bottom;
        for (const [nm, e] of [['mover line', who], ['detail block', det], ['answer form', act]]) { if (!e) continue; const b = e.getBoundingClientRect();
          if (b.top < prev - 1) out.push(li.id + ' the ' + nm + ' is not below the line before it'); if (b.left < r.left - 0.5 || b.right > r.right + 0.5) out.push(li.id + ' the ' + nm + ' leaves the row ' + Math.round(b.left) + '..' + Math.round(b.right)); prev = b.bottom; }
        if (det) { const ds = getComputedStyle(det); if (parseFloat(ds.borderLeftWidth) !== 2 || ds.borderLeftStyle !== 'solid' || ds.borderLeftColor === 'rgba(0, 0, 0, 0)') out.push(li.id + ' the detail block has no 2px rule: ' + ds.borderLeftWidth + ' ' + ds.borderLeftStyle + ' ' + ds.borderLeftColor); }
        for (const f of li.querySelectorAll('form.hanswer')) { const q = f.getBoundingClientRect(); for (const e of f.querySelectorAll('button, textarea')) { const b = e.getBoundingClientRect(); if (b.left < q.left - 0.5 || b.right > q.right + 0.5) out.push(li.id + ' ' + e.tagName + ' outside its form ' + Math.round(b.right) + '>' + Math.round(q.right)); }
          if (q.right > r.right + 0.5) out.push(li.id + ' form outside its row'); } }
      return out.slice(0, 6); }"""
    # a Waiting row is the top line, the mover line (then <who>, watched by <what>, below the title), the wait line (what it waits on) and the step after the wait (labelled "after the wait:") under it, none of it beside the title
    WAITFIT = """() => { const out = [], rows = [...document.querySelectorAll('#waiting-list li.hrow')]; if (rows.length < 10) out.push('only ' + rows.length + ' waiting rows'); let thens = 0;
      for (const li of rows) { const id = li.id, r = li.getBoundingClientRect(), q = s => li.querySelector(s), b = e => e.getBoundingClientRect(), top = b(q('.ir-top')), gl = b(q('a.ir-link')), who = q('.ir-who'), wt = q('.hwait'), st = q('.hafter');
        if (gl.width < 100 && gl.height > 30) out.push(id + ' the title is squeezed: ' + Math.round(gl.width) + ' px');
        if (who) { const x = b(who), t = who.textContent; if (/^then /.test(t)) thens++; if (x.top < top.bottom - 1) out.push(id + ' the mover line is not below the top line'); if (x.left < r.left - 0.5 || x.right > r.right + 0.5) out.push(id + ' the mover line leaves the row ' + Math.round(x.left) + '..' + Math.round(x.right));
          if (t.indexOf('watched by') >= 0 && t.indexOf('then') > t.indexOf('watched by')) out.push(id + ' watched by sits before then'); }
        if (wt) { const x = b(wt); if (x.top < (who ? b(who).bottom : top.bottom) - 1) out.push(id + ' the wait line is not below the mover line'); if (x.right > r.right + 0.5) out.push(id + ' the wait line leaves the row'); }
        if (st) { const s = b(st); if (wt && s.top < b(wt).bottom - 1) out.push(id + ' the step after the wait is not below the wait line'); if (!/^after the wait:/.test(st.textContent)) out.push(id + ' the step after the wait is not labelled: ' + st.textContent.slice(0, 30)); if (s.right > r.right + 0.5) out.push(id + ' the step after the wait leaves the row'); } }
      if (thens < 5) out.push('only ' + thens + ' rows name who takes it after the wait');
      return out.slice(0, 8); }"""
    WAITTOP = """() => { const a = document.getElementById('task-a-71'); if (!a) return null; const r = a.getBoundingClientRect(), t = a.querySelector('.ir-top').getBoundingClientRect(), w = a.querySelector('.ir-who').getBoundingClientRect(), d = a.querySelector('.hwait').getBoundingClientRect(), g = a.querySelector('a.ir-link').getBoundingClientRect();
      return {goal: Math.round(g.width), row: Math.round(r.width), whoBelow: w.top >= t.bottom - 1, waitBelow: d.top >= w.bottom - 1, inside: w.right <= r.right + 0.5 && d.right <= r.right + 0.5}; }"""
    TEMPROW = """() => { const li = document.getElementById('task-l-3'); if (!li) return null; const g = li.querySelector('a.ir-link').getBoundingClientRect(), n = li.querySelector('.ir-id'), vw = document.documentElement.clientWidth, a = li.querySelector('.ir-age').getBoundingClientRect();
      return {goal: Math.round(g.width), right: Math.round(g.right), vw: vw, num: n.textContent, ageRight: Math.round(a.right), row: Math.round(li.getBoundingClientRect().right)}; }"""
    COLORS = """() => { const c = s => { const e = document.querySelector(s); return e ? getComputedStyle(e).color : null; };
      return [c('#your-move .ir-age.red'), c('#your-move .ir-age.amber'), c('#your-move li.hrow .ir-age:not(.amber):not(.red)')]; }"""
    DRAFTROW = """() => { const li = document.getElementById('task-a-67'), o = []; if (!li) return ['row missing']; const d = li.querySelector('.hdraft'); if (!d) return ['no draft'];
      const det = d.querySelector('details'), lab = d.querySelector('summary .dlab'), btn = d.querySelector('summary button.copy'), step = li.querySelector('.hnext'), form = li.querySelector('form.hstep');
      if (!lab || !btn) return ['no label or no Copy inside the summary']; if (det.open) o.push('open on load'); if (lab.textContent.trim() !== 'draft') o.push('label reads ' + lab.textContent);
      const l = lab.getBoundingClientRect(), b = btn.getBoundingClientRect(), r = d.getBoundingClientRect(), rg = document.createRange(); rg.setStart(step, 0); rg.setEndBefore(d); const s = rg.getBoundingClientRect();
      if (Math.abs((l.top + l.bottom) / 2 - (b.top + b.bottom) / 2) > 8) o.push('Copy is not on the label line');
      if (b.left - l.right < 0 || b.left - l.right > 24) o.push('Copy is not just beside the label: ' + Math.round(b.left - l.right) + ' px');
      if (b.right > innerWidth - 8) o.push('Copy is at the far right');
      if (r.top < s.bottom - 1) o.push('the draft is not under the step line'); if (!form || r.bottom > form.getBoundingClientRect().top + 1) o.push('the draft is not above the note box and buttons');
      return o; }"""
    DRAFTTEXT = """() => { const li = document.getElementById('task-a-67'), o = [], pre = li.querySelector('.hdraft pre'), c = li.querySelector('.hdraft pre code'), body = getComputedStyle(document.body).fontFamily, vw = innerWidth;
      if (!pre.offsetParent) o.push('the draft is not open'); const cs = getComputedStyle(c), ps = getComputedStyle(pre);
      if (cs.fontFamily !== body || /mono/i.test(cs.fontFamily)) o.push('the draft is not in the body font: ' + cs.fontFamily); if (ps.whiteSpace !== 'pre-wrap' || ps.overflowWrap !== 'anywhere') o.push('wrapping: ' + ps.whiteSpace + ' ' + ps.overflowWrap);
      const r = pre.getBoundingClientRect(); if (r.left < -0.5 || r.right > vw + 0.5 || pre.scrollWidth > pre.clientWidth + 1) o.push('the draft runs off the screen ' + Math.round(r.right) + ' ' + pre.scrollWidth + '/' + pre.clientWidth);
      if (c.textContent.split('\\n').length < 6) o.push('lines lost');
      const k = document.querySelector('li.hrow .cmd pre code'); if (k && !/mono/i.test(getComputedStyle(k).fontFamily)) o.push('a command block is not monospace: ' + getComputedStyle(k).fontFamily);
      return o; }"""
    NEW_WORD_PX = 79          # the card's content width up to which the Closed card's one-digit count reads "5" and not "5 new": the number of the container query in ui/render.py (ui_kit_scenario checks it)
    CARDS_JS = """[...document.querySelectorAll('#counts a.hcard')].map(a => { const r = a.getBoundingClientRect(), bb = a.querySelector('b'), b = bb.getBoundingClientRect(), sp = a.querySelector('span'), spr = sp.getBoundingClientRect(), nw = a.querySelector('i.hnew'),
        nr = nw ? nw.getBoundingClientRect() : null, em = nw ? nw.querySelector('em').getBoundingClientRect() : null, tn = [...sp.childNodes].find(x => x.nodeType === 3), lr = document.createRange(); if (tn) lr.selectNodeContents(tn);
        const label = [...sp.childNodes].filter(x => !(x.nodeType === 1 && x.matches('i.hnew'))).map(x => x.textContent).join('').trim(), cs = nw ? getComputedStyle(nw) : null, cw = r.width - 2 * parseFloat(getComputedStyle(a).borderLeftWidth) - 2 * parseFloat(getComputedStyle(a).paddingLeft);
        return {href: a.getAttribute('href'), n: bb.textContent, label: label, top: Math.round(r.top), w: Math.round(r.width), cw: Math.round(cw * 10) / 10, h: Math.round(r.height), bh: Math.round(b.height), new: nw ? nw.textContent : '', hdr: !!a.closest('header.top'),
                numOnly: !!nw && !bb.querySelector('i') && bb.textContent === a.querySelector('b').textContent, onLabelLine: !!nw && nr.top >= b.bottom - 1 && nr.left >= lr.getBoundingClientRect().right - 0.5 && Math.abs(nr.top - lr.getBoundingClientRect().top) <= 3,
                inside: !!nw && nr.right <= spr.right + 0.5 && nr.right <= r.right - 1 && nr.left >= r.left, cut: !!nw && (sp.scrollWidth > sp.clientWidth + 0.5 || nr.width < 5), word: !!nw && em.width > 1,
                plain: !!nw && cs.borderTopWidth === '0px' && cs.backgroundColor === 'rgba(0, 0, 0, 0)', green: !!nw && cs.color !== getComputedStyle(sp).color}; })"""
    BASE = {"your-move", "queued-release"}      # the main column's sections that render open (Queued for release is empty here); On agent and Waiting render closed
    for scheme in ("light", "dark"):
        for w in (360, 412, 1440):
            tag = f"home lists {w} {scheme}"
            ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES["board"].as_uri()); pg.wait_for_timeout(100)
            fo = pg.evaluate("Object.fromEntries([...document.querySelectorAll('details.fold')].map(d => [d.dataset.fold, d.open]))")
            PANEL4 = {"machines", "runners", "anchorhub", "audit-panel", "projects-panel"}      # the side panel's sections: open on every load
            check(f"{tag}: as the page loads the main column has Your move and Queued for release open (On agent and Waiting closed) and the panel's Machines, Runners, Anchor hub, Audit and Projects are open", {k for k, v in fo.items() if v} == BASE | PANEL4 and {"agents-at-work", "waiting-list"} <= set(fo), fo)
            # nothing is remembered. A fold opened by hand is closed again on the next load; the old stored keys are removed (and have no effect); the item and project pages' keys stay; a hash opens a section or the section of a row.
            if w == 412:
                FOLDS = "Object.fromEntries([...document.querySelectorAll('details.fold')].map(d => [d.dataset.fold, d.open]))"
                KEYS = "Object.keys(localStorage).filter(k => k.startsWith('stackshot.fold.')).sort()"
                pg.evaluate("document.querySelector('#waiting-list summary').click()"); pg.wait_for_timeout(50)
                check(f"{tag}: a section opened by hand is open", pg.evaluate("document.querySelector('#waiting-list details.fold').open"))
                pg.evaluate("() => { localStorage.setItem('stackshot.fold.your-move', '0'); localStorage.setItem('stackshot.fold.waiting-list', '1'); localStorage.setItem('stackshot.fold.completed', '1'); localStorage.setItem('stackshot.fold.machines', '0'); localStorage.setItem('stackshot.fold.anchorhub', '0'); localStorage.setItem('stackshot.fold.item.history', '1') }")
                pg.reload(); pg.wait_for_timeout(150)
                fo2 = pg.evaluate(FOLDS)
                check(f"{tag}: after a reload only Your move and Queued for release are open again in the main column and the panel's sections are open, whatever was stored or opened by hand", {k for k, v in fo2.items() if v} == BASE | PANEL4, fo2)
                check(f"{tag}: the old section keys are gone from storage, the item page's key stays", pg.evaluate(KEYS) == ["stackshot.fold.item.history"], pg.evaluate(KEYS))
                pg.evaluate("document.querySelector('#agents-at-work summary').click()"); pg.wait_for_timeout(50)
                check(f"{tag}: opening a section writes nothing to storage", pg.evaluate(KEYS) == ["stackshot.fold.item.history"], pg.evaluate(KEYS))
                rid = pg.evaluate("(document.querySelector('#agents-at-work li.hrow') || {}).id || ''")
                pg3 = ctx.new_page(); pg3.goto(PAGES["board"].as_uri() + "#waiting-list"); pg3.wait_for_timeout(200)
                fh = pg3.evaluate(FOLDS)
                check(f"{tag}: a link to #waiting-list opens that section on load, the others stay as they were", {k for k, v in fh.items() if v} == BASE | {"waiting-list"} | PANEL4, fh)
                check(f"{tag}: ... and the hash is dropped from the address once it has opened, so a reload shows only the first two open again", pg3.evaluate("location.hash") == "", pg3.evaluate("location.href"))
                pg3.reload(); pg3.wait_for_timeout(200)
                check(f"{tag}: ... the reload of that page has only Your move and Queued for release open in the main column", {k for k, v in pg3.evaluate(FOLDS).items() if v} == BASE | PANEL4, pg3.evaluate(FOLDS))
                pg3.evaluate("location.hash = '#agents-at-work'"); pg3.wait_for_timeout(200)
                check(f"{tag}: changing the hash to #agents-at-work opens that section too", pg3.evaluate("document.querySelector('#agents-at-work details.fold').open"), pg3.evaluate(FOLDS))
                check(f"{tag}: ... and drops that hash too", pg3.evaluate("location.hash") == "", pg3.evaluate("location.href"))
                pg3.close()
                check(f"{tag}: the On agent list has a row to link to", bool(rid), rid)
                pg4 = ctx.new_page(); pg4.goto(PAGES["board"].as_uri() + "#" + rid); pg4.wait_for_timeout(200)
                fr = pg4.evaluate(FOLDS)
                check(f"{tag}: a link to a row inside the closed On agent list opens the section and shows the row", fr.get("agents-at-work") is True and fr.get("waiting-list") is False and pg4.evaluate("(id) => document.getElementById(id).getBoundingClientRect().height > 0", rid), fr)
                pg4.close()
            pg.evaluate("document.querySelectorAll('details.fold').forEach(d => d.open = true)")      # the lists' rows are measured below: every section open (they load closed since)
            _src = PAGES["board"].read_text(encoding="utf-8"); _fm = re.findall(r"<form class=\"hanswer[^>]*>", _src)
            check(f"{tag}: the ask forms are in the page's markup visible from the first paint (none hidden), every button of theirs disabled until a token comes, no token in the markup",
                  len(_fm) >= 5 and not any(" hidden" in x for x in _fm) and all(re.search(r"<button[^>]*>", b) and "disabled" in b for f in re.findall(r"<form class=\"hanswer.*?</form>", _src, re.S) for b in re.findall(r"<button[^>]*>", f))
                  and all('name="token" value=""' in f for f in re.findall(r"<form class=\"hanswer.*?</form>", _src, re.S)), len(_fm))
            check(f"{tag}: the three step rows show the step, a note box and ONE Send (no Done), inside the screen",
                  pg.evaluate("""() => { const vw = document.documentElement.clientWidth, o = []; for (const n of [65, 66, 67]) { const li = document.getElementById('task-a-' + n); if (!li) { o.push(n + ' missing'); continue }
                    const f = li.querySelector('form.hstep'); if (!f) { o.push(n + ' no step form'); continue }
                    f.hidden = false; const bs = [...f.querySelectorAll('button')]; if (bs.map(b => b.textContent).join() !== 'Send') o.push(n + ' buttons ' + bs.map(b => b.textContent));
                    for (const e of [...bs, f.querySelector('textarea'), ...li.querySelectorAll('.cmd pre')]) { const b = e.getBoundingClientRect(); if (b.width === 0 || b.left < -0.5 || b.right > vw + 0.5) o.push(n + ' ' + e.tagName + ' not inside ' + Math.round(b.left) + '..' + Math.round(b.right)); }
                    for (const b of bs) if (b.getBoundingClientRect().height < 30) o.push(n + ' a button is too short'); }
                    return o }""") == [], pg.evaluate("document.getElementById('task-a-65') && document.getElementById('task-a-65').innerText.slice(0, 200)"))
            dl = pg.evaluate(DRAFTROW)
            check(f"{tag}: a row's draft is labelled \"draft\" with Copy just beside the label, under the step line and above the note box and buttons, collapsed as the page loads", dl == [], dl)
            pg.click("#task-a-67 .hdraft button.copy"); pg.wait_for_timeout(50)
            check(f"{tag}: a tap on the row's Copy leaves its draft closed", pg.evaluate("document.querySelector('#task-a-67 .hdraft details').open") is False)
            pg.evaluate(OPEN); pg.wait_for_timeout(50)
            dt = pg.evaluate(DRAFTTEXT)
            check(f"{tag}: an open draft is in the page's own body font (not monospace), keeps its lines, wraps inside the screen; a command block stays monospace", dt == [], dt)
            sl = pg.evaluate("(" + STEPLIST + ")(document.querySelector('#task-a-68 .ir-det'))")
            check(f"{tag}: a numbered step row draws one numbered list with a copy block under each of its two commands, inside the screen, in the code font", sl == [], sl)
            if HSHOTS and (w, scheme) == (360, "light"):
                pg.evaluate("document.querySelectorAll('header, .conn, #reload, #totop').forEach(e => e.style.display = 'none')"); pg.locator("#task-a-68").screenshot(path=os.path.join(HSHOTS, "step-home-yourmove-360-light.png"))
            if HSHOTS and (w, scheme) == (360, "light"):
                pg.evaluate("document.querySelectorAll('header, .conn, #reload, #totop').forEach(e => e.style.display = 'none')"); pg.locator("#task-a-67").screenshot(path=os.path.join(HSHOTS, "draft-home-yourmove-360-light.png"))
            sw, vw, wide = pg.evaluate(WIDE)
            check(f"{tag}: the page is the screen's width with every fold open and every ask form shown", sw == vw == w, (sw, vw, wide))
            rf = pg.evaluate(ROWFIT)
            check(f"{tag}: every row is inside the screen: the top line (number, title, age at the right edge) with the whole title wrapped in the room the age leaves, then the mover line, the detail block, the ask form and buttons inside it", rf == [], rf)
            tg = pg.evaluate(TEMPROW)
            check(f"{tag}: a temporary id keeps the title at least 120 px wide, on screen, with the age inside the row", tg and tg["goal"] >= 120 and tg["num"].startswith("board-tmp-") and tg["right"] <= tg["vw"] and tg["ageRight"] <= tg["row"], tg)
            wf = pg.evaluate(WAITFIT)
            check(f"{tag}: every Waiting row has its mover line (then, watched by) under the title, its wait line under that, the step after the wait last, the title never squeezed", wf == [], wf)
            wl = pg.evaluate(WAITTOP)
            check(f"{tag}: a long then-mover keeps the row inside the screen and the title half the row's width at least, the mover line below the top line, the wait line below it", wl and wl["goal"] >= 0.5 * (wl["row"] - 24) and wl["whoBelow"] and wl["waitBelow"] and wl["inside"], wl)
            wtxt = pg.evaluate("[...document.querySelectorAll('#waiting-list .hwait')].map(e => e.textContent).join(' | ')")
            check(f"{tag}: no Waiting row says \"no anchor stored\"; the anchor wait with none says so truthfully", "no anchor stored" not in wtxt and "an anchor (none recorded)" in wtxt, wtxt[:300])
            n = pg.evaluate("[...document.querySelectorAll('#your-move li.hrow, #agents-at-work li.hrow, #waiting-list li.hrow')].length")
            check(f"{tag}: rows of every list are drawn", n >= 12 and pg.evaluate("['#your-move', '#agents-at-work', '#waiting-list'].every(s => document.querySelectorAll(s + ' li.hrow').length > 0)"), n)
            co = pg.evaluate(COLORS)
            check(f"{tag}: the age is red past five days, amber past two, and plain before, three colours", co[0] and co[1] and co[2] and len(set(co)) == 3, co)
            pg.evaluate("window.scrollTo(0, 0)")      # the header is sticky when wide: its top is then the scroll position
            order = pg.evaluate("['#counts', '#your-move', '#agents-at-work', '#queued-release', '#waiting-list'].map(s => Math.round(document.querySelector(s).getBoundingClientRect().top + scrollY))")
            check(f"{tag}: the count cards, then the four lists, top to bottom", order == sorted(order) and len(set(order)) == 5, order)
            cl = pg.evaluate("[...document.querySelectorAll('#counts a')].map(a => a.getBoundingClientRect().left >= -0.5 && a.getBoundingClientRect().right <= document.documentElement.clientWidth + 0.5 && a.getBoundingClientRect().width > 0)")
            check(f"{tag}: the five count cards (Your move, On agent, Queued for release, Waiting, Closed) are inside the screen, with no sideways scroll", cl == [True] * 5 and pg.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), cl)
            cd = pg.evaluate(CARDS_JS)
            check(f"{tag}: the cards in order, each the number over its label and a link: #your-move, #agents-at-work, #queued-release, #waiting-list, /closed (with its 5 new closes); each 60 px tall, the number on one line",
                  [(c['href'], c['label']) for c in cd] == [('#your-move', 'Your move'), ('#agents-at-work', 'On agent'), ('#queued-release', 'Queued for release'), ('#waiting-list', 'Waiting'), ('/closed', 'Closed')]
                  and cd[4]['new'] == '5 new' and all(c['hdr'] and c['h'] == 60 and c['bh'] <= 32 for c in cd), cd)
            check(f"{tag}: the Closed card's count is green text on the label line, right after the word Closed and under the number (the number line holds the number alone), whole inside the card, never clipped: the digit always shows, and the word 'new' with it where the card's content is over {NEW_WORD_PX} px ({cd[4]['cw']} px here)",
                  cd[4]['numOnly'] and cd[4]['onLabelLine'] and cd[4]['inside'] and not cd[4]['cut'] and cd[4]['plain'] and cd[4]['green'] and cd[4]['word'] == (cd[4]['cw'] > NEW_WORD_PX), cd[4])
            check(f"{tag}: the cards are one width, on one row (two rows of three and two on a phone), and the header holds title, rendered line, cards and search in that order",
                  len({c['w'] for c in cd}) == 1 and len({c['top'] for c in cd}) == (2 if w < 481 else 1) and pg.evaluate("(() => { const t = s => document.querySelector(s).getBoundingClientRect().top; return t('header.top .site') <= t('header.top .rline') && t('header.top .rline') < t('#counts') && t('#counts') < t('header.top .sbox'); })()"), cd)
            pg.click('#counts a[href="#waiting-list"]'); pg.wait_for_timeout(100)
            check(f"{tag}: a count's link goes to its list: the section opens and the hash is dropped from the address", pg.evaluate("document.querySelector('#waiting-list details.fold').open") and pg.evaluate("location.hash") == "")
            if HSHOTS and (w, scheme) in ((360, "light"), (360, "dark"), (412, "light"), (1440, "light")):
                pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(100); pg.screenshot(path=os.path.join(HSHOTS, f"home-{w}-{scheme}.png"), full_page=True)
            if HSHOTS and w in (360, 1440):
                pg.evaluate("document.querySelectorAll('header, .conn, #reload, #totop').forEach(e => e.style.display = 'none')")      # the sticky title bar and the floating buttons would cover the rows in a shot of the list
                pg.locator("#waiting-list").screenshot(path=os.path.join(HSHOTS, f"waiting-{w}-{scheme}.png"))
                pg.locator("#your-move").screenshot(path=os.path.join(HSHOTS, f"yourmove-{w}-{scheme}.png"))
            ctx.close()
    # ---- at a phone width (375 px) every row of the home lists and of the project page has its title the room its age leaves it (the age at the right edge of the top line, the number first in the title; the card's border is no room either) ----
    TITLEFIT = """() => { const out = []; let n = 0;
      for (const li of document.querySelectorAll('li.hrow')) { n++; const ti = li.querySelector('.ir-title'), ag = li.querySelector('.ir-age');
        if (!ti || !ag || !li.querySelector('a.ir-link .ir-id')) { out.push(li.id + ' the top line lacks the number, the title or the age'); continue; }
        const r = li.getBoundingClientRect(), cs = getComputedStyle(li), content = r.width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - parseFloat(cs.borderLeftWidth) - parseFloat(cs.borderRightWidth), tb = ti.getBoundingClientRect(), ab = ag.getBoundingClientRect(), room = content - ab.width - 8;
        if (Math.abs(tb.width - room) > 2) out.push(li.id + ' title ' + Math.round(tb.width) + ' wide of the ' + Math.round(room) + ' px the age leaves'); }
      return {n: n, bad: out.slice(0, 6)}; }"""
    for nm, sel in (("board", None), ("project page", None)):
        for scheme in ("light", "dark"):
            ctx = br.new_context(viewport={"width": 375, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES[nm].as_uri()); pg.wait_for_timeout(100); pg.evaluate(OPEN); pg.wait_for_timeout(50)
            tf = pg.evaluate(TITLEFIT)
            check(f"{nm} 375 {scheme}: every row's title takes the whole room its age leaves on the top line", tf["n"] >= (12 if nm == "board" else 1) and tf["bad"] == [], tf)
            if HSHOTS and nm == "board" and scheme == "light":
                pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(100); pg.screenshot(path=os.path.join(HSHOTS, "home-375-light.png"), full_page=True)
            ctx.close()
    # ---- the line above a row's title names the project and the owner (home, Closed), the owner alone on a project page: at 360, 412 and 1440 px, light and dark, with every fold open, it stays inside its row and above the
    # title line, wraps instead of running past the card (a long project name and a long owner name together), keeps the small quiet type, and an owner is drawn in the line's own muted colour ----
    PROJLINE = """() => { const out = []; let n = 0, owners = 0, both = 0;
      for (const li of document.querySelectorAll('li.irow')) { const pj = li.querySelector('.ir-proj'); if (!pj) continue; n++;
        const r = li.getBoundingClientRect(), b = pj.getBoundingClientRect(), top = li.querySelector('.ir-top').getBoundingClientRect(), cs = getComputedStyle(pj), id = (li.querySelector('.ir-id') || {}).textContent;
        if (b.left < r.left - 0.5 || b.right > r.right + 0.5 || pj.scrollWidth > pj.clientWidth + 1 || li.scrollWidth > li.clientWidth + 1) out.push(id + ' the project line leaves its row ' + Math.round(b.left) + '..' + Math.round(b.right) + ' of ' + Math.round(r.left) + '..' + Math.round(r.right));
        if (b.bottom > top.top + 1) out.push(id + ' the project line is not above the title line: ' + Math.round(b.bottom) + ' > ' + Math.round(top.top));
        if (cs.fontSize !== '12px') out.push(id + ' the project line is ' + cs.fontSize);
        const o = pj.querySelector('.pjo'), p = pj.querySelector('a.pjl');
        if (o) { owners++; if (getComputedStyle(o).color !== cs.color || getComputedStyle(o).fontSize !== '12px') out.push(id + ' the owner is not in the quiet type of its line:' + getComputedStyle(o).color + ' vs ' + cs.color); }
        if (o && p) { both++; if (!pj.textContent.includes(' · ')) out.push(id + ' the project and the owner have no separator'); }
        if (o && !p && pj.textContent.trim() !== o.textContent.trim()) out.push(id + ' the owner is not alone on the line: ' + pj.textContent); }
      return {n: n, owners: owners, both: both, bad: out.slice(0, 6)}; }"""
    for nm, key_ in (("board", "board"), ("project page", "project page"), ("Closed page", "landed page")):
        for w in (360, 412, 1440):
            for scheme in ("light", "dark"):
                ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES[key_].as_uri()); pg.wait_for_timeout(100); pg.evaluate(OPEN); pg.wait_for_timeout(50)
                pl = pg.evaluate(PROJLINE)
                check(f"{nm} {w} {scheme}: the project line (project · owner; the owner alone on a project page) is inside its row, above the title, small and quiet, and wraps rather than runs on",
                      pl["bad"] == [] and pl["owners"] >= (8 if nm == "board" else 2) and (pl["both"] > 0 if nm != "project page" else pl["both"] == 0), pl)
                ctx.close()
    # ---- the Closed page: Clear all at the top above the list; each row of the New section is the one row: the outcome tag and the title (a link) with its relative close time (the exact time in the instance timezone on hover) on the top line, the close reason under it
    # (wrapped, never cut), Clear under the reason (32 px or taller, inside the screen); a row fits at 360 px.
    # Then the Undo state: a Clear leaves the row in place, dimmed, its Clear replaced by an Undo of the same place and size; Clear all leaves every row with its own Undo; an Undo puts the row back. The browser has no server on a file:// page, so the
    # page's fetch is answered by a stub that says {ok, changed: 1}. The row count is the home card's "new" badge. ----
    LANDED = r"""() => { const vw = document.documentElement.clientWidth, out = [], lis = [...document.querySelectorAll('#new li.lrow')];
      const all = document.querySelector('#new form.lmark .b'), grp = document.querySelector('#new details.hscope'), note = document.querySelector('#new p.lnote');
      for (const li of lis) { const b = li.querySelector('form.lclear .b'), why = li.querySelector('.ir-det'), top = li.querySelector('.ir-top'), act = li.querySelector('.ir-act'), sj = li.querySelector('a.ir-link'), ag = li.querySelector('.lago'), lr = li.getBoundingClientRect(), tb = top.getBoundingClientRect();
        const id = li.querySelector('.ir-id').textContent;
        if (!b) { out.push(id + ' has no Clear button'); continue; }
        const r = b.getBoundingClientRect(), q = sj.getBoundingClientRect(), after = why ? why.getBoundingClientRect().bottom : tb.bottom;
        if (!act || !act.contains(b.closest('form'))) out.push(id + ': Clear is not in the row\'s action line');
        if (r.height < 32 || r.left < 0 || r.right > vw + 0.5) out.push(id + ' Clear box ' + Math.round(r.left) + '-' + Math.round(r.right) + ' h' + Math.round(r.height));
        if (r.top < after - 1) out.push(id + ' Clear (' + Math.round(r.top) + ') is not under the reason (' + Math.round(after) + ')');
        if (lr.right > vw + 0.5 || lr.left < -0.5 || li.scrollWidth > li.clientWidth + 1) out.push(id + ' row ' + Math.round(lr.left) + '-' + Math.round(lr.right) + ' sw' + li.scrollWidth + '/' + li.clientWidth);
        if (!ag || !ag.textContent.trim() || !/^(?:\d+[mhd] ago|just now)$/.test(ag.textContent.trim()) || !(ag.getAttribute('data-tip') || '').includes('+04')) out.push(id + ' relative time ' + (ag && ag.textContent) + ' tip ' + (ag && ag.getAttribute('data-tip')));
        else { const a = ag.getBoundingClientRect(); if (a.right > vw + 0.5 || a.height < 12 || a.top > q.bottom || getComputedStyle(ag).color !== getComputedStyle(sj).color) out.push(id + ' time ' + Math.round(a.left) + '-' + Math.round(a.right) + ' colour ' + getComputedStyle(ag).color + '/' + getComputedStyle(sj).color); }
        if (why) { const z = why.getBoundingClientRect(), cs = getComputedStyle(why);
          if (z.top < tb.bottom - 1 || z.right > vw + 0.5 || why.scrollWidth > why.clientWidth + 1 || cs.textOverflow === 'ellipsis' || cs.whiteSpace === 'nowrap' || cs.overflow === 'hidden' || cs.opacity !== '1')
            out.push(id + ' reason top' + Math.round(z.top) + '/' + Math.round(tb.bottom) + ' right' + Math.round(z.right) + ' ' + cs.whiteSpace + ' ' + cs.textOverflow + ' ' + cs.overflow); }
        if (/closed by/i.test(li.textContent)) out.push(id + ' still says who closed it'); }
      const sh = [...document.querySelectorAll('#new details.hscope > summary h3.iscope')];                       // the scope subsections' headings (work, home, ops), each above its rows
      for (const h of sh) { const q = h.getBoundingClientRect(), g = h.closest('details.hscope').querySelector('ul.ir-rows');
        if (q.left < 0 || q.right > vw + 0.5 || q.height < 12 || h.scrollWidth > h.clientWidth + 1) out.push('scope heading ' + h.textContent + ' ' + Math.round(q.left) + '-' + Math.round(q.right) + ' h' + Math.round(q.height));
        if (!g || g.getBoundingClientRect().top < q.bottom - 1) out.push('scope heading ' + h.textContent + ' is not above its rows'); }
      const a = all.getBoundingClientRect();
      return {scopes: sh.map(h => h.textContent.replace(/[0-9]+$/, '').trim()), lines: lis.length, clears: document.querySelectorAll('#new form.lclear').length, why: document.querySelectorAll('#new li.lrow .ir-det').length, allH: Math.round(a.height), allTop: Math.round(a.top), grpTop: Math.round(grp.getBoundingClientRect().top), noteBottom: Math.round(note.getBoundingClientRect().bottom), allRight: Math.round(a.right), sw: document.documentElement.scrollWidth, out: out.slice(0, 6)}; }"""
    UNDO = r"""async () => { const vw = document.documentElement.clientWidth, out = [], lis = [...document.querySelectorAll('#new li.lrow')], res = {}, wait = () => new Promise(r => setTimeout(r, 30));
      const first = lis[0], id0 = first.querySelector('.ir-id').textContent, cb = first.querySelector('form.lclear .b'), r0 = cb.getBoundingClientRect(), t0 = first.getBoundingClientRect().top, counts = () => [...document.querySelectorAll('#new h3.iscope .count')].map(c => c.textContent), counts0 = counts(), note = () => document.querySelector('#new p.lnote').firstChild.nodeValue, note0 = note();
      cb.click(); await wait(); await wait();
      const ub = first.querySelector('form.lundo .b'), r1 = ub && ub.getBoundingClientRect();
      res.cleared = {dim: first.classList.contains('lcleared'), undo: !!ub, noClear: !first.querySelector('form.lclear'), samePlace: !!ub && Math.abs(r1.left - r0.left) < 1 && Math.abs(r1.top - r0.top) < 1 && Math.abs(first.getBoundingClientRect().top - t0) < 1,
        h: ub && Math.round(r1.height), inside: !!ub && r1.right <= vw + 0.5 && r1.left >= 0, opacity: getComputedStyle(first.querySelector('.ir-top')).opacity, label: ub && ub.textContent, aria: ub && ub.getAttribute('aria-label'), lines: document.querySelectorAll('#new li.lrow').length,
        counts: counts(), note: note(), sw: document.documentElement.scrollWidth, first: id0, counts0, note0};
      ub.click(); await wait(); await wait();
      res.undone = {back: !first.classList.contains('lcleared') && !!first.querySelector('form.lclear') && !first.querySelector('form.lundo'), counts: counts(), note: note(), opacity: getComputedStyle(first.querySelector('.ir-top')).opacity};
      document.querySelector('#new form.lmark .b').click(); await wait(); await wait();
      const all = [...document.querySelectorAll('#new li.lrow')], ubs = all.map(l => l.querySelector('form.lundo .b'));
      res.all = {dim: all.every(l => l.classList.contains('lcleared')), undos: ubs.every(b => b), tall: ubs.every(b => b && b.getBoundingClientRect().height >= 32 && b.getBoundingClientRect().right <= vw + 0.5), hidden: document.querySelector('#new form.lmark').hidden, shown: getComputedStyle(document.querySelector('#new form.lmark')).display,
        n: all.length, note: note(), counts: [...document.querySelectorAll('#new .count')].map(c => c.textContent), sw: document.documentElement.scrollWidth};
      ubs[1].click(); await wait(); await wait();
      res.one = {back: !all[1].classList.contains('lcleared') && !!all[1].querySelector('form.lclear'), others: all.filter((l, i) => i !== 1).every(l => l.classList.contains('lcleared')), allShown: getComputedStyle(document.querySelector('#new form.lmark')).display, enabled: !document.querySelector('#new form.lmark .b').disabled, note: note()};
      document.querySelector('#new form.lmark .b').click(); await wait(); await wait();
      res.again = {dim: all.every(l => l.classList.contains('lcleared')), undos: all.every(l => !!l.querySelector('form.lundo')), hidden: document.querySelector('#new form.lmark').hidden, enabled: !document.querySelector('#new form.lmark .b').disabled};
      return res; }"""
    STUB = "window.fetch = (u, o) => Promise.resolve(new Response(JSON.stringify({ok: true, changed: 1}), {status: 200, headers: {'Content-Type': 'application/json'}}));"
    _card = int(re.search(r'href="/closed"[^>]*><b>\d+</b><span>Closed <i class="hnew">(\d+)<em', PAGES["board"].read_text(encoding="utf-8")).group(1))
    for scheme in ("light", "dark"):
        for w in (360, 412):
            ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES["landed page"].as_uri()); pg.wait_for_timeout(100)
            ld_ = pg.evaluate(LANDED)
            check(f"closed page {w} {scheme}: Clear all (32 px or taller, inside the screen) sits above the list; each of the {ld_['lines']} rows has its Clear (32 px or taller, under the reason, inside the screen), the title then its relative time on the top line (the hover names the zone), the reason under it, not cut; no row past the screen; the rows are the home card's {_card} new; the scope subsection headings ({ld_['scopes']}) are inside the screen, each above its rows",
                  ld_["lines"] == ld_["clears"] == _card == 5 and ld_["scopes"] == ["work", "ops"] and ld_["why"] >= 3 and ld_["allH"] >= 32 and ld_["noteBottom"] <= ld_["allTop"] < ld_["grpTop"] and ld_["allRight"] <= w and ld_["sw"] <= w and ld_["out"] == [], ld_)
            ctx.close()
            ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.add_init_script(STUB); pg.goto(PAGES["landed page"].as_uri()); pg.wait_for_timeout(100)
            u_ = pg.evaluate(UNDO); c_, o_, a_ = u_["cleared"], u_["undone"], u_["all"]
            check(f"closed page {w} {scheme}: a Clear leaves the row in place, dimmed, its Clear replaced by an Undo of the same place (32 px or taller, inside the screen, no sideways scroll); no row left the page, the counts follow ({c_['counts0']} to {c_['counts']}), and the Undo puts the row back",
                  c_["dim"] and c_["undo"] and c_["noClear"] and c_["samePlace"] and c_["h"] >= 32 and c_["inside"] and float(c_["opacity"]) < 1 and c_["label"] == "Undo" and c_["aria"] == "Undo " + c_["first"] and c_["lines"] == 5 and c_["sw"] <= w
                  and sum(map(int, c_["counts"])) == sum(map(int, c_["counts0"])) - 1 and c_["note"].startswith("4 closes") and c_["note0"].startswith("5 closes")
                  and o_["back"] and float(o_["opacity"]) == 1 and o_["counts"] == c_["counts0"] and o_["note"].startswith("5 closes"), u_)
            check(f"closed page {w} {scheme}: Clear all leaves every row in place with its own Undo (32 px or taller, inside the screen), hides itself while nothing is left to clear, no sideways scroll; one Undo brings Clear all back, enabled, and the others stay cleared; a second Clear all after it clears the row again",
                  a_["dim"] and a_["undos"] and a_["tall"] and a_["shown"] == "none" and a_["n"] == 5 and a_["note"].startswith("0 closes") and set(a_["counts"]) <= {"0"} and a_["sw"] <= w
                  and u_["one"]["back"] and u_["one"]["others"] and u_["one"]["allShown"] != "none" and u_["one"]["enabled"] and u_["one"]["note"].startswith("1 close ")
                  and u_["again"]["dim"] and u_["again"]["undos"] and u_["again"]["hidden"] and u_["again"]["enabled"], u_)
            ctx.close()
    # ---- the relative words are the server's: the page script's ago() (its own source, run in the page) and render.landed_ago() read the same for a range of ages ----
    ctx = br.new_context(viewport={"width": 390, "height": 900}); pg = ctx.new_page(); pg.goto(PAGES["landed page"].as_uri()); pg.wait_for_timeout(100)
    AGES = (0, 59, 60, 719, 5399, 5400, 10800, 86399, 86400, 169199, 172800, 1728000)
    src_ = re.search(r"function ago\(s\)\{.*\}", render._LANDED_JS).group(0)
    js_ = pg.evaluate("([src, ages]) => { const f = new Function(src + '; return ago')(); return ages.map(a => f(a)) }", [src_, list(AGES)])
    check("the page script's relative words are render.landed_ago's for just now, a minute, 12 min, 89 min, 90 min, 3 h, 23 h, 24 h and 47 h, 2 d and 20 d", js_ == [render.landed_ago(a) for a in AGES] and "24h ago" in js_ and "just now" in js_ and "20d ago" in js_, js_)
    ctx.close()
    # ---- the five count cards stay on ONE row from 481 px up (the pinned panel leaves ~480 px of column at 800), each inside the screen, wrapping only at a phone's width ----
    for w in (481, 600, 800, 950, 1300):
        ctx = br.new_context(viewport={"width": w, "height": 900}); pg = ctx.new_page(); pg.goto(PAGES["board"].as_uri()); pg.wait_for_timeout(150)
        cc = pg.evaluate("[...document.querySelectorAll('#counts a.hcard')].map(a => { const r = a.getBoundingClientRect(); return {top: Math.round(r.top), right: Math.round(r.right), w: Math.round(r.width), over: a.scrollWidth > a.clientWidth + 1}; })")
        check(f"home counts {w}: all five cards on one row, each inside the screen and none cut", len(cc) == 5 and len({c['top'] for c in cc}) == 1 and all(c['right'] <= w and not c['over'] and c['w'] >= 80 for c in cc), cc)
        ctx.close()
    # ---- a card as narrow as 120 px (a narrow column of the cards) shows the Closed card's count in full: "5 new" on the label line, whole, never clipped, the number alone above it ----
    ctx = br.new_context(viewport={"width": 1300, "height": 900}); pg = ctx.new_page(); pg.goto(PAGES["board"].as_uri()); pg.wait_for_timeout(150)
    pg.evaluate("document.querySelector('nav#counts').style.cssText = 'grid-template-columns:repeat(5,120px);width:max-content;max-width:none;gap:6px'"); pg.wait_for_timeout(100)
    c120 = pg.evaluate(CARDS_JS)
    check("120 px cards: five cards of 120 px, 60 px tall; the Closed card reads Closed and, after it on the same line, the green count '5 new' in full inside the card, with the number alone on the line above; the other four labels are unchanged",
          [c['w'] for c in c120] == [120] * 5 and all(c['h'] == 60 for c in c120) and [c['label'] for c in c120] == ['Your move', 'On agent', 'Queued for release', 'Waiting', 'Closed']
          and c120[4]['new'] == '5 new' and c120[4]['word'] and c120[4]['numOnly'] and c120[4]['onLabelLine'] and c120[4]['inside'] and not c120[4]['cut'] and c120[4]['plain'] and c120[4]['green']
          and all(not c['new'] for c in c120[:4]), c120)
    ctx.close()
    # ---- an answer sent from the home page stays on it: the server's redirect brings ?sent=<code>&item=&name= back to the board; the page shows the item page's notice naming the item,
    # then drops the query from the address; the form's `back` is the page's own path and the row's id as the form is sent ----
    for w in (360, 1440):
        ctx = br.new_context(viewport={"width": w, "height": 900}); pg = ctx.new_page(); pg.goto(PAGES["board"].as_uri() + "?sent=decision&item=a87&name=SPOOFED%20TEXT&x=1#your-move"); pg.wait_for_timeout(150)
        note = pg.evaluate("(() => { const n = document.querySelector('p.isent'); const c = document.querySelector('header.top'); return n ? {t: n.textContent, cls: n.className, after: c && c.nextElementSibling === n, role: n.getAttribute('role')} : null })()")
        check(f"home answer {w}: the notice for ?sent= names the item by its id (its row is not on the page), says what the item page says, right after the header; a `name` in the address is never shown", note and note["t"].startswith("a87 — Sent: your answer is on the item") and "SPOOFED" not in note["t"] and note["after"] and note["cls"] == "isent ok" and note["role"] == "status", note)
        pg.evaluate("window.scrollTo(0, 0)")      # the header is sticky when wide: measure from the top
        gp = pg.evaluate("(() => { const n = document.querySelector('p.isent'), h = document.querySelector('header.top'), t = document.querySelector('h2'); return n && h && t ? {gap: Math.round(n.getBoundingClientRect().top - h.getBoundingClientRect().bottom), sec: parseFloat(getComputedStyle(t).marginTop)} : null })()")
        check(f"home answer {w}: the notice has the gap the page puts between sections (an h2's top margin, 32 px) above it, off the header's divider", gp and gp["sec"] == 32 and gp["gap"] == gp["sec"], gp)
        check(f"home answer {w}: ?sent, item and name are dropped from the address, and so is the hash once its section has opened", pg.evaluate("location.search") == "" and pg.evaluate("location.hash") == "", pg.evaluate("window.location.href"))
        sw, vw, wide = pg.evaluate(WIDE)
        check(f"home answer {w}: the notice keeps the page the screen's width", sw == vw == w, (sw, vw, wide))
        bk = pg.evaluate("""(() => { const f = document.querySelector('form.hanswer'); f.hidden = false; f.querySelector('input[name=token]').value = 'T'; const li = f.closest('li[id]'); f.addEventListener('submit', e => e.preventDefault());
            f.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); return {v: f.querySelector('input[name=back]').value, id: li ? li.id : null, p: location.pathname} })()""")
        check(f"home answer {w}: the form's back is the page's own path alone, with no row fragment (the page stays where it is)", bk["id"] and bk["v"] == bk["p"], bk)
        ctx.close()
    # ---- Ctrl+Enter sends: in a home row's answer box it presses the form's main button (Send on a decision, Done on a step); Enter alone does not; an IME composition does not; a disabled button is left alone ----
    ctx = br.new_context(viewport={"width": 390, "height": 900}); pg = ctx.new_page(); pg.goto(PAGES["board"].as_uri()); pg.wait_for_timeout(300)
    pg.evaluate("""() => { window.__sub = []; document.querySelectorAll('form.hanswer').forEach(f => { f.hidden = false; f.querySelector('input[name=token]').value = 'T'; f.querySelectorAll('button').forEach(b => b.disabled = false);
        f.addEventListener('submit', e => { e.preventDefault(); window.__sub.push((f.classList.contains('hstep') ? 'step:' : 'ask:') + (e.submitter ? e.submitter.value : '?')) }) }) }""")
    SUBS = "() => window.__sub.slice()"
    DEC, STEP = "form.hanswer:not(.hstep) textarea", "form.hanswer.hstep textarea"
    check("ctrl+enter home: the board page has a decision box and a step box, and the decision's Send button reads Send, not Send as my answer", pg.locator(DEC).count() > 0 and pg.locator(STEP).count() > 0 and "Send as my answer" not in PAGES["board"].read_text(encoding="utf-8") and pg.locator("form.hanswer:not(.hstep) button[value=answer]").first.text_content() == "Send")
    pg.locator(DEC).first.click(); pg.keyboard.type("one"); pg.keyboard.press("Enter"); pg.keyboard.type("two")
    check("ctrl+enter home: Enter alone makes a new line and sends nothing", pg.locator(DEC).first.input_value() == "one\ntwo" and pg.evaluate(SUBS) == [], (pg.locator(DEC).first.input_value(), pg.evaluate(SUBS)))
    pg.evaluate("""() => { const t = document.querySelector('form.hanswer:not(.hstep) textarea'); window.__ime = [t.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', ctrlKey: true, isComposing: true, bubbles: true, cancelable: true})),
        t.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', ctrlKey: true, keyCode: 229, bubbles: true, cancelable: true}))] }""")
    check("ctrl+enter home: Ctrl+Enter during an IME composition (isComposing, or keyCode 229) sends nothing and is not cancelled", pg.evaluate(SUBS) == [] and pg.evaluate("window.__ime") == [True, True], (pg.evaluate(SUBS), pg.evaluate("window.__ime")))
    pg.keyboard.press("Control+Enter")
    check("ctrl+enter home: Ctrl+Enter in a decision box presses Send (act=answer)", pg.evaluate(SUBS) == ["ask:answer"], pg.evaluate(SUBS))
    pg.keyboard.press("Meta+Enter")
    check("ctrl+enter home: Cmd+Enter does the same", pg.evaluate(SUBS) == ["ask:answer", "ask:answer"], pg.evaluate(SUBS))
    pg.locator(STEP).first.click(); pg.keyboard.press("Control+Enter")
    check("ctrl+enter home: Ctrl+Enter in a step's box presses its one Send", pg.evaluate(SUBS)[-1] == "step:send" and len(pg.evaluate(SUBS)) == 3, pg.evaluate(SUBS))
    pg.evaluate("document.querySelector('form.hanswer.hstep button[value=send]').disabled = true"); pg.keyboard.press("Control+Enter")
    check("ctrl+enter home: a disabled main button is left alone: nothing is sent", len(pg.evaluate(SUBS)) == 3, pg.evaluate(SUBS))
    tt = pg.evaluate("[document.querySelector('form.hanswer:not(.hstep) button[value=answer]').title, document.querySelector('form.hanswer.hstep button[value=send]').title]")
    check("ctrl+enter home: the main buttons carry the key as their hover title", all(x in ("Ctrl+Enter", "\u2318+Enter") for x in tt), tt)
    ctx.close()

    ctx = br.new_context(viewport={"width": 390, "height": 900}); pg = ctx.new_page(); pg.goto(PAGES["board"].as_uri()); pg.wait_for_timeout(100)
    rid = pg.evaluate("document.querySelector('#your-move li.hrow').id"); goal = pg.evaluate("document.querySelector('#your-move li.hrow .hgoal').textContent"); m_ = re.fullmatch(r"task-([a-z])-(\d+)", rid)
    pg.goto(PAGES["board"].as_uri() + f"?sent=comment&item={m_.group(1)}{m_.group(2)}"); pg.wait_for_timeout(100)
    check("home answer: with the item's row on the page the notice names the goal from the row, then its id", pg.evaluate("document.querySelector('p.isent').textContent").startswith(f"{goal} ({m_.group(1)}{m_.group(2)}) — Sent: your comment"), (rid, goal))
    pg.goto(PAGES["board"].as_uri() + "?sent=decision&item=" + "%3Cimg%20src%3Dx%3E"); pg.wait_for_timeout(100)
    pg.goto(PAGES["board"].as_uri() + "?sent=comment&item=12"); pg.wait_for_timeout(100)
    hx = pg.evaluate("document.getElementById('sent-notes').getAttribute('data-hash')")
    check("home answer: an issue-numbered id is written with the board's own prefix (the page's data-hash), the id alone when its row is not on the page", pg.evaluate("document.querySelector('p.isent').textContent").startswith(f"{hx}12 — Sent: your comment"), (hx, pg.evaluate("document.querySelector('p.isent').textContent")))
    pg.goto(PAGES["board"].as_uri() + "?sent=decision&item=" + "%3Cimg%20src%3Dx%3E"); pg.wait_for_timeout(100)
    check("home answer: an item that is not an id's shape is not shown at all", pg.evaluate("document.querySelector('p.isent').textContent").startswith("Sent: your answer") and pg.evaluate("document.querySelector('p.isent img')") is None)
    pg.goto(PAGES["board"].as_uri() + "?sent=nonsense&item=a1")
    check("home answer: an unknown ?sent= code shows no notice", pg.evaluate("document.querySelector('p.isent')") is None)
    ctx.close()
    # ---- the project page's rows are the home page's: the same fit at 360 and 412 px, light and dark, every fold open ----
    for scheme in ("light", "dark"):
        for w in (360, 412):
            tag = f"project page rows {w} {scheme}"
            ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES["project page"].as_uri()); pg.wait_for_timeout(100)
            pg.evaluate(OPEN); pg.wait_for_timeout(50)
            check(f"{tag}: rows are drawn", pg.evaluate("document.querySelectorAll('li.hrow').length") > 0)
            rf = pg.evaluate(ROWFIT)
            check(f"{tag}: every row is inside the screen, the muted line above a full-width goal, the step below", rf == [], rf)
            tg = pg.evaluate(TEMPROW)
            check(f"{tag}: a temporary id keeps the title at least 120 px wide, on screen, with the age inside the row", tg and tg["goal"] >= 120 and tg["num"].startswith("board-tmp-") and tg["right"] <= tg["vw"] and tg["ageRight"] <= tg["row"], tg)
            check(f"{tag}: the page is the screen's width", pg.evaluate(WIDE)[0] == w, pg.evaluate(WIDE))
            ctx.close()
    # ---- a Your move row opens with one top line, the number, the whole title and the age at the right edge; a long title wraps onto a second line while the age stays whole.
    # At 360 and 1300 px, light and dark: no sideways scroll; the long-titled row (task-a-69) wraps at 360 and is one line high at 1300, with its age visible; On agent rows name their mover on the mover line ----
    TOPLINE = """() => { const li = document.getElementById('task-a-69'); if (!li) return null; const t = li.querySelector('.ir-top'), ti = li.querySelector('.ir-title'), g = li.querySelector('a.ir-link'), a = li.querySelector('.ir-age'), n = li.querySelector('.ir-id'), r = li.getBoundingClientRect(), tb = t.getBoundingClientRect(), tr = ti.getBoundingClientRect(), ab = a.getBoundingClientRect(), vw = document.documentElement.clientWidth;
      return {whole: g.textContent.indexOf('shelf-1 is full') > 0 && ti.scrollWidth <= ti.clientWidth + 1 && getComputedStyle(ti).textOverflow !== 'ellipsis', wraps: tr.height > 30, ageShown: ab.width > 20 && ab.right <= r.right + 0.5 && ab.right <= vw + 0.5 && ab.left >= tr.right - 0.5 && a.scrollWidth <= a.clientWidth + 1,
              first: g.firstElementChild === n, sw: document.documentElement.scrollWidth, vw: vw}; }"""
    for scheme in ("light", "dark"):
        for w in (360, 1300):
            tag = f"Your move top line {w} {scheme}"
            ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES["board"].as_uri()); pg.wait_for_timeout(100)
            pg.evaluate(OPEN); pg.wait_for_timeout(50)
            tl = pg.evaluate(TOPLINE)
            check(f"{tag}: the long title is whole (no ellipsis), wrapping onto a second line at 360 px and on one line at 1300, while the age stays whole at the right edge after it, with the number first", tl and tl["whole"] and tl["wraps"] == (w == 360) and tl["ageShown"] and tl["first"], tl)
            check(f"{tag}: the page has no sideways scroll", tl and tl["sw"] == tl["vw"] == w, tl)
            rf = pg.evaluate(ROWFIT)
            check(f"{tag}: every row (the top line of Your move rows included) is inside the screen", rf == [], rf)
            check(f"{tag}: On agent rows name their mover on the mover line", pg.evaluate("[...document.querySelectorAll('#agents-at-work li.hrow .ir-who .hwho')].length") > 0)
            ctx.close()
    # ---- an answer sent from a project page's row comes back to the project page with its notice: the same script and the same element as the home page, the notice right
    # under the header; then ?sent and item are dropped from the address and the hash stays ----
    for w in (360, 1440):
        ctx = br.new_context(viewport={"width": w, "height": 900}); pg = ctx.new_page()
        pg.goto(PAGES["project page"].as_uri() + "?sent=comment&item=a1&x=1#items"); pg.wait_for_timeout(150)
        pn = pg.evaluate("""(() => { const n = document.querySelector('p.isent'), r = document.getElementById('task-a-1'), g = r && r.querySelector('.hgoal');
            return n ? {t: n.textContent, cls: n.className, role: n.getAttribute('role'), after: n.previousElementSibling && n.previousElementSibling.tagName, goal: g ? g.textContent : null} : null })()""")
        check(f"project page answer {w}: the notice for ?sent= names the item by its goal and id and says what the item page says, right under the header",
              pn and pn["goal"] and pn["t"].startswith(f"{pn['goal']} (a1) — Sent: your comment") and pn["cls"] == "isent ok" and pn["role"] == "status" and pn["after"] == "HEADER", pn)
        check(f"project page answer {w}: ?sent and item are dropped from the address, the hash stays", pg.evaluate("location.search") == "" and pg.evaluate("location.hash") == "#items", pg.evaluate("window.location.href"))
        sw, vw, wide = pg.evaluate(WIDE)
        check(f"project page answer {w}: the notice keeps the page the screen's width", sw == vw == w, (sw, vw, wide))
        bk = pg.evaluate("""(() => { const f = document.querySelector('form.hanswer'); if (!f) return null; f.hidden = false; f.querySelector('input[name=token]').value = 'TOK'; const li = f.closest('li[id]'); f.addEventListener('submit', e => e.preventDefault());
            f.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); return {v: f.querySelector('input[name=back]').value, id: li ? li.id : null, p: location.pathname} })()""")
        check(f"project page answer {w}: a row's answer form sends back the project page's own path alone, with no row fragment", bk and bk["id"] and bk["v"] == bk["p"], bk)
        ctx.close()
    ctx = br.new_context(viewport={"width": 390, "height": 900}); pg = ctx.new_page(); pg.goto(PAGES["project page"].as_uri() + "?sent=nonsense&item=a1"); pg.wait_for_timeout(100)
    check("project page answer: an unknown ?sent= code shows no notice", pg.evaluate("document.querySelector('p.isent')") is None)
    ctx.close()
    # ---- the reload button (on every page): the same round 44 px button as Back to
    # top, 10 px above it, on the same right edge, at every width, scrolled or not, with the title bar clear of it; a click reloads the page (a marker set on
    # window is gone) and Back to top scrolls to the top ----
    FAB = "() => { const q = e => { const r = document.querySelector(e).getBoundingClientRect(), s = getComputedStyle(document.querySelector(e)); return {r: [r.left, r.top, r.right, r.bottom], size: [r.width, r.height], bd: s.borderTopWidth, pos: s.position, rad: s.borderRadius, bg: s.backgroundColor, col: s.color, bs: s.boxShadow, z: s.zIndex}; }; return {rl: q('#reload'), tt: q('#totop'), n: document.querySelectorAll('#reload').length, nt: document.querySelectorAll('#totop').length, inhdr: !!document.querySelector('header.top #reload, .topline #reload'), vh: innerHeight}; }"
    TB = "() => { const t = document.querySelector('#theme').getBoundingClientRect(), p = document.querySelector('#panel-open'), pr = p ? p.getBoundingClientRect() : null, h = document.querySelector('header.top .site'), rg = document.createRange(); rg.selectNodeContents(h); return {hr: [...rg.getClientRects()].map(q => [q.left, q.top, q.right, q.bottom]), bx: [[t.left, t.top, t.right, t.bottom]].concat(pr ? [[pr.left, pr.top, pr.right, pr.bottom]] : [])}; }"
    for nm in ("board", "item page", "project page"):
      for scheme in ("light", "dark"):
        for w in (360, 412, 960, 1440):
            tag = f"reload {nm} {w} {scheme}"
            ctx = br.new_context(viewport={"width": w, "height": 800}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES[nm].as_uri()); pg.wait_for_timeout(100)
            for scrolled in (False, True):
                if scrolled: pg.evaluate("window.scrollTo(0, 400)"); pg.wait_for_timeout(100)
                tag2 = tag + (" scrolled" if scrolled else "")
                d = pg.evaluate(FAB); r, tt = d["rl"], d["tt"]
                check(f"{tag2}: one reload button and one Back to top, floating (not in the title bar), a 44 px round button with a 1.5 px border (Chrome snaps it to 1px at 1x), inside the screen", d["n"] == 1 and d["nt"] == 1 and not d["inhdr"] and r["pos"] == "fixed"
                      and r["size"] == [44, 44] and r["bd"] in ("1px", "1.5px") and r["rad"] == tt["rad"] and r["r"][0] >= 0 and r["r"][2] <= w + 0.5 and r["r"][1] >= 0 and r["r"][3] <= d["vh"], d)
                check(f"{tag2}: it has Back to top's look (colours, shadow, stacking)", (r["bg"], r["col"], r["bs"], r["z"]) == (tt["bg"], tt["col"], tt["bs"], tt["z"]), d)
                check(f"{tag2}: it is stacked right above Back to top: same right edge, 10 px between them", abs(r["r"][2] - tt["r"][2]) < 0.5 and abs(r["r"][0] - tt["r"][0]) < 0.5 and abs(tt["r"][1] - r["r"][3] - 10) < 0.5, d)
            pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(100)
            sw, vw, wide = pg.evaluate(WIDE)
            check(f"{tag}: the page is the screen's width", sw == vw == w, (sw, vw, wide))
            th = pg.evaluate(TB)
            hit = [q for q in th["hr"] for bx in th["bx"] if q[0] < bx[2] - 0.5 and q[2] > bx[0] + 0.5 and q[1] < bx[3] - 0.5 and q[3] > bx[1] + 0.5]
            check(f"{tag}: no line of the title (the back link on the project and item pages) runs under the theme or panel button", th["hr"] and not hit, (hit, th["hr"]))
            pg.evaluate("window.scrollTo(0, 400)"); pg.wait_for_timeout(100)
            if pg.evaluate("window.scrollY") > 0:
                pg.click("#totop"); pg.wait_for_timeout(100)
                check(f"{tag}: Back to top scrolls the page to the top", pg.evaluate("window.scrollY") == 0, pg.evaluate("window.scrollY"))
            pg.evaluate("window.__marker = 1")
            check(f"{tag}: the marker is set before the click", pg.evaluate("window.__marker") == 1)
            with pg.expect_navigation(): pg.click("#reload")
            pg.wait_for_timeout(100)
            check(f"{tag}: a click on the floating button reloads the page (the marker set on window is gone)", pg.evaluate("window.__marker") is None and pg.evaluate("!!document.querySelector('#reload')"))
            ctx.close()
    ctx = br.new_context(viewport={"width": 412, "height": 800}); pg = ctx.new_page(); pg.goto(PAGES["board"].as_uri()); pg.focus("#reload")
    check("reload board 412: keyboard focus shows the button's focus ring, and its label and title read Reload / Reload page",
          pg.evaluate("getComputedStyle(document.querySelector('#reload')).outlineStyle") == "solid" and pg.get_attribute("#reload", "aria-label") == "Reload" and pg.get_attribute("#reload", "title") == "Reload page")
    ctx.close()
    # ---- the summary panel (pinned on load at 800 px and up, at 960 before): nothing remembered; a drawer on a phone, peek and pin on a wide screen ----
    SHOTS = os.environ.get("PHONE_WIDTH_SHOTS", "")     # set it to a directory to keep a screenshot of each state
    if SHOTS: os.makedirs(SHOTS, exist_ok=True)
    def shot(pg, name):
        if SHOTS: pg.screenshot(path=os.path.join(SHOTS, name + ".png"))
    BOARD = PAGES["board"].as_uri()
    VIS = "(s) => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(); return getComputedStyle(e).visibility !== 'hidden' && r.width > 0 && r.right > 0 && r.left < document.documentElement.clientWidth; }"
    CLS = "() => [...document.body.classList].filter(c => c.startsWith('panel-'))"
    RECT = "(s) => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }"
    ORDER = "() => ['#machines', '#anchorhub'].map(s => { const e = document.querySelector('#panel ' + s); return e ? Math.round(e.getBoundingClientRect().top + document.querySelector('#panel').scrollTop) : -1; })"
    OPEN4 = "() => ['machines', 'runners', 'anchorhub', 'audit-panel', 'projects-panel'].map(s => document.querySelector('#' + s + ' details.fold').open)"
    SPACING = """() => {
      const g = (e, p) => getComputedStyle(e)[p], pad = e => ['paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'].map(p => g(e, p)).join(' ');
      const L = e => Math.round(e.getBoundingClientRect().left * 10) / 10, q = s => [...document.querySelectorAll('#panel ' + s)];
      const m = q('#machines .pc.mach'), a = q('#anchorhub .pc.rcv'), u = q('#audit-panel .audit'), gh = q('#audit-panel .ghc'), rc = q('#runners .pc.rc'), mrows = q('#machines .mr:not(.offline)');
      return {gap: {machines: g(q('#machines .matrix')[0], 'rowGap'), runners: g(q('#runners .rlist')[0], 'rowGap'), anchorhub: g(q('#anchorhub .matrix')[0], 'rowGap')},
        pad: {machines: pad(m[0]), anchorhub: pad(a[0]), audit: pad(u[0]), ghcalls: pad(gh[0]), runners: pad(rc[0])},
        rowgap: {machines: g(m[0], 'rowGap'), anchorhub: g(a[0], 'rowGap'), audit: g(u[0], 'rowGap'), ghcalls: g(gh[0], 'rowGap')},
        auditgap: Math.round(gh[0].getBoundingClientRect().top - u[0].getBoundingClientRect().bottom),
        flush: m.map(c => [L(c.querySelector('.mh')), L(c.querySelector('.mr .lbl') || c.querySelector('.mh'))]).concat(a.map(c => [L(c.querySelector('b.lbl')), L(c.querySelector('.lbl.st'))])),
        cols: mrows.filter(r => r.querySelector('.val')).map(r => [L(r.querySelector('.lbl')) - L(r.closest('.pc')), L(r.querySelector('.val')) - L(r.closest('.pc')), L(r.querySelector('.st')) - L(r.closest('.pc'))])};
    }"""
    STORE = "() => { let o = []; try { o = o.concat(Object.keys(localStorage), Object.keys(sessionStorage)); } catch (e) {} return [o.filter(k => /panel/i.test(k)), document.cookie]; }"      # nothing about the panel is kept anywhere (the old 'stackshot.panel' key is gone too)
    # every panel card's text starts at the same left edge; the Audit card is label/value rows like Anchor hub's; a machine that is behind shows `→ <latest>` on its own line
    ALIGN = """() => {
      const r = e => e.getBoundingClientRect(), L = e => Math.round(r(e).left * 10) / 10, q = (s, root = document) => [...root.querySelectorAll(s)];
      const M = q('#panel #machines .pc.mach'), R = q('#panel #runners .pc.rc'), A = q('#panel #anchorhub .pc.rcv'), U = q('#panel #audit-panel #audit')[0], G = q('#panel #audit-panel #ghcalls')[0];
      const probe = document.createElement('span'); probe.style.color = 'var(--fg)'; document.body.appendChild(probe); const fgc = getComputedStyle(probe).color; probe.remove();
      const cardLefts = [M, R, A, U ? [U] : [], G ? [G] : []].map(l => l.map(L));
      return {
        cards: cardLefts,
        machines: M.flatMap(c => q('.mh, .mr .lbl', c)).map(L), runners: R.flatMap(c => q('.rn', c)).map(L),
        anchorhub: A.flatMap(c => q(':scope > :nth-child(odd)', c)).map(L),
        audit: U ? q('.lbl:not(.mh)', U).map(L) : [], name: U ? [L(q('.mh', U)[0])] : [], auditLabels: U ? q('.lbl:not(.mh)', U).map(e => e.textContent) : [], auditValues: U ? q('.val', U).map(e => e.textContent) : [],
        button: U ? [L(q('#audit-now', U)[0])] : [], auditName: U ? [q('.mh a.nm', U)[0].textContent, q('.mh a.nm', U)[0].getAttribute('href')] : [],
        nameH: {machines: M.length ? r(q('.mh', M[0])[0]).height : null, anchorhub: A.length ? r(q('b.lbl', A[0])[0]).height : null, audit: U ? r(q('.mh', U)[0]).height : null},
        auditOrder: U ? (() => { const lb = q('.lbl', U), nm = r(q('.mh', U)[0]), bt = r(q('#audit-now', U)[0]), cd = r(U), rg = document.createRange(); rg.selectNodeContents(q('.mh', U)[0].firstChild); const tx = rg.getBoundingClientRect();      // the name row first, the button on it (beside the name, vertically centred), the labels under it one under the other
          return [lb.every((e, i) => !i || r(e).top > r(lb[i - 1]).top), bt.top >= nm.top - 1 && bt.bottom <= nm.bottom + 1, Math.abs((bt.top + bt.bottom) / 2 - (nm.top + nm.bottom) / 2) <= 2, bt.right <= cd.right - 9 && bt.right >= cd.right - 11,
                  r(q('.lbl:not(.mh)', U)[0]).top >= nm.bottom - 1, bt.left > tx.right]; })() : [],
        btn: U ? (() => { const b = q('#audit-now', U)[0], c = getComputedStyle(b), nm = q('.mh', U)[0], a = getComputedStyle(b, '::after'); return {tag: b.tagName, cls: b.className, type: b.type, bw: c.borderTopWidth, pad: c.padding, fs: c.fontSize, fw: c.fontWeight, nfs: getComputedStyle(nm).fontSize, color: c.color, bg: c.backgroundColor, deco: c.textDecorationLine, h: r(b).height, afterH: a.height, afterPos: a.position, afterCoarse: matchMedia('(pointer: coarse)').matches}; })() : null,
        gh: G ? {name: q('.mh', G)[0].textContent, labels: q('.lbl:not(.mh)', G).map(e => e.textContent), values: q('.val', G).map(e => e.textContent), caps: q('.cap', G).map(e => getComputedStyle(e).color), vals: q('.val', G).map(e => getComputedStyle(e).fontVariantNumeric), left: q('.lbl:not(.mh)', G).map(L), after: r(G).top >= r(U).bottom} : null,
        rc: R.map(c => { const n = c.querySelector('.rn'), v = c.querySelector('.rv'), g = c.querySelector('.go'), cs = getComputedStyle(v), rr = r(c);
          return {name: n.textContent, count: v.textContent, cls: v.className, color: cs.color, weight: cs.fontWeight, tab: cs.fontVariantNumeric, h: rr.height, oneLine: Math.abs(r(n).top - r(v).top) < 4 && Math.abs(r(v).top - r(g).top) < 4, goRight: r(g).right <= rr.right - 9, goLast: r(g).left >= r(v).right, nameFlex: r(n).width > r(v).width * 2, href: c.getAttribute('href'), mutedGo: getComputedStyle(g).color, text: c.textContent}; }),
        runnersLink: q('#panel #runners a').filter(a => !a.classList.contains('rc')).length, repoLines: q('#panel #runners .mr').length, looseLine: q('#panel #runners .mnote').filter(e => /github calls/.test(e.textContent)).length,
        arrows: M.flatMap(c => q('.mr.update', c)).map(m => { const st = m.querySelector('.st'), lb = m.querySelector('.lbl'), rs = r(st);
          return {text: st.textContent, dTop: Math.abs(rs.top - r(lb).top), h: rs.height, color: getComputedStyle(st).color, fgc: fgc, right: rs.right, rowRight: r(m).right, clipped: st.scrollWidth > st.clientWidth + 1}; })};
    }"""
    def colour(pg, v):
        """The computed colour of a CSS value (a variable) in the page."""
        return pg.evaluate("(v) => { const e = document.createElement('span'); e.style.color = v; document.body.appendChild(e); const c = getComputedStyle(e).color; e.remove(); return c; }", v)
    def align(pg, tag):
        pg.mouse.move(1, 1); pg.wait_for_timeout(60)      # the pointer off the cards: a hovered Runners card has its arrow in the accent colour
        a = pg.evaluate(ALIGN); ref = (a["anchorhub"] or [None])[0]
        near = lambda xs: len(xs) >= 1 and all(abs(x - ref) <= 0.5 for x in xs)
        check(f"{tag}: every panel card's text starts at the same left edge: Machines, Runners, Anchor hub and Audit labels, the Audit card's name and the GitHub calls card (the Audit now link sits at the right end of the name row)",
              ref is not None and near(a["machines"]) and near(a["runners"]) and near(a["anchorhub"]) and near(a["audit"]) and near(a["name"]) and len({x for c in a["cards"] for x in c}) == 1, a)
        check(f"{tag}: the Audit card is named 'Audits' (a link to the Audits page) with the Audit now link on the name's row, to its right, vertically centred and at the card's right padding; the eight group names start at Anchor hub's left x, one under the other, under the name row, each with its number of audits and its findings in 24 hours (a dash for the two groups that keep no log)",
              a["auditLabels"] == ["Silence", "Filing", "Wording", "Dates", "Proof and patterns", "Pages and agents", "Fleet and services", "Text and rules"] and a["auditValues"][::2] == ["7", "12", "12", "3", "2", "5", "5", "5"]
              and a["auditValues"][1::2] == ["1", "2", "1", "0", "0", "0", "\u2013", "\u2013"] and a["auditName"] == ["Audits \u2197", "/audits"] and ref is not None and near(a["audit"]) and near(a["name"]) and a["auditOrder"] == [True, True, True, True, True, True], a)
        b = a["btn"]
        check(f"{tag}: Audit now reads as a text link, not a button: a <button type=button> with no class, the accent (--acc) as text, no border, no fill, no padding, the card's 12px text at weight 400, no underline at rest, no taller than the name row",
              b["tag"] == "BUTTON" and b["type"] == "button" and b["cls"] == "" and b["color"] == colour(pg, "var(--acc)") and b["bw"] == "0px" and b["bg"] == "rgba(0, 0, 0, 0)" and b["pad"] == "0px"
              and b["fs"] == b["nfs"] == "12px" and b["fw"] == "400" and b["deco"] == "none" and b["h"] <= a["nameH"]["audit"] + 0.5, (b, colour(pg, "var(--acc)")))
        nh = a["nameH"]
        check(f"{tag}: the Audit card's name row is one line, as high as the Machines and Anchor hub name rows (within 1 px)",
              all(v is not None for v in nh.values()) and abs(nh["audit"] - nh["machines"]) <= 1 and abs(nh["audit"] - nh["anchorhub"]) <= 1 and nh["audit"] < 24, nh)
        check(f"{tag}: Audit now's tap area: a hit area laid over the row ({'44px tall on this coarse pointer' if b['afterCoarse'] else 'a few px around the text on a fine pointer'}), the row's own height unchanged",
              b["afterPos"] == "absolute" and ((b["afterH"] == "44px") if b["afterCoarse"] else (b["afterH"] != "auto" and float(b["afterH"][:-2]) >= b["h"])), b)
        g = a["gh"]; cap = colour(pg, "var(--mut)")
        check(f"{tag}: the GitHub calls card follows the audit card in the same section: name 'GitHub calls', rows writes / reads / counted, the cap greyed after each count, tabular numbers, labels at the panel's common left edge",
              g is not None and g["after"] and g["name"] == "GitHub calls" and g["labels"] == ["writes", "reads", "counted"] and g["values"][0] == "15 / 250" and g["values"][1] == "204 / 1,500"
              and re.fullmatch(r"\d\d:\d\d – \d\d:\d\d", g["values"][2]) and g["caps"] == [cap, cap] and all("tabular-nums" in v for v in g["vals"]) and ref is not None and near(g["left"]) and near(a["audit"]), a["gh"])
        rc = a["rc"]; fg, mu, wn = colour(pg, "var(--fg)"), colour(pg, "var(--mut)"), colour(pg, "var(--warn)")
        check(f"{tag}: Runners: no 'Runners page' link and no per-repo lines or loose calls line; each machine is one card on one line linking /runners: name (flexes), count busy/online (tabular), a muted ↗ last, inside the card",
              a["runnersLink"] == 0 and a["repoLines"] == 0 and a["looseLine"] == 0 and [c["name"] for c in rc] == ["box-a", "box-b", "box-c", "other"] and all(c["href"] == "/runners" and c["oneLine"] and c["goRight"] and c["goLast"] and c["nameFlex"] and c["h"] < 40 and "tabular-nums" in c["tab"] and c["text"].endswith("↗") and c["mutedGo"] == mu for c in rc), rc)
        check(f"{tag}: Runners counts: muted at 0 busy, bold in the name's colour while some are busy, bold amber when every runner is busy",
              [(c["count"], c["cls"], c["color"], c["weight"]) for c in rc] == [("2/4", "rv busy", fg, "700"), ("0/2", "rv idle", mu, "400"), ("offline", "rv idle", mu, "400"), ("2/2", "rv full", wn, "700")], rc)
        ar = a["arrows"]
        check(f"{tag}: a machine that is behind shows '→ <latest>' (no word update) in the text colour (--fg, not orange), on the same line as its name row (same top within 3 px), on one line, inside its row, not clipped by the card",
              len(ar) >= 2 and all(x["text"].startswith("→ ") and "update" not in x["text"] and x["dTop"] <= 3 and x["h"] <= 24 and x["color"] == x["fgc"] and x["right"] <= x["rowRight"] + 0.5 and not x["clipped"] for x in ar), ar)
    def closed(pg): return pg.evaluate(CLS) == [] and not pg.evaluate(VIS, "#panel") and pg.get_attribute("#panel-open", "aria-expanded") == "false"
    def in_order(o): return all(x >= 0 for x in o) and o == sorted(o)
    LONGTIP = "invalid_grant: the refresh token was revoked by its owner, so the receiver cannot reach the service " * 2 + "x" * 90
    def tip_check(pg, tag):
        """A tooltip over a time stamp in the panel (.tip:hover::after) stays inside the panel's width: the panel has no horizontal
        overflow while it shows, for the real text and for a long raw error with an unbroken run."""
        pg.evaluate("document.querySelectorAll('#panel details.fold').forEach(d => d.open = true)")      # open them all (they load open) to hover a card's time stamp
        for label, text in (("its own text", None), ("a long raw error", LONGTIP)):
            if text: pg.evaluate("(t) => document.querySelector('#anchorhub .tip').setAttribute('data-tip', t)", text)
            pg.hover("#anchorhub .tip"); pg.wait_for_timeout(100)
            r = pg.evaluate("""(() => { const e = document.querySelector('#anchorhub .tip'), p = document.querySelector('#panel'), c = getComputedStyle(e, '::after');
              return [p.scrollWidth, p.clientWidth, c.content.length > 2, c.whiteSpace, Math.round(parseFloat(c.width))]; })()""")
            check(f"{tag}: a tooltip with {label} wraps inside the panel and adds no horizontal overflow", r[0] <= r[1] and r[2] and r[3] == "normal" and r[4] <= 201, r)
        pg.mouse.move(2, 2)
    for scheme in ("light", "dark"):
        for w in (360, 412):
            tag = f"panel {w} {scheme}"
            ctx = br.new_context(viewport={"width": w, "height": 800}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(BOARD)
            check(f"{tag}: closed on load (no panel class, the panel hidden, the button collapsed)", closed(pg))
            shot(pg, f"phone-{w}-{scheme}-closed")
            first = pg.evaluate("document.querySelector('main#top > section').id")
            check(f"{tag}: the main column starts at Your move (the count cards are in the header above it), with no tiles, Machines or Anchor hub in it",
                  first == "your-move" and pg.evaluate("['#overview', '#machines', '#anchorhub'].every(s => !document.querySelector('main#top ' + s)) && !document.querySelector('#tasks, .overview')") and pg.evaluate("!!document.querySelector('main#top > header.top > nav#counts')"), first)
            pg.click("#panel-open"); pg.wait_for_timeout(300)
            r = pg.evaluate(RECT, "#panel")
            check(f"{tag}: the title bar's button opens the drawer from the right, inside the screen",
                  pg.evaluate(CLS) == ["panel-open"] and pg.evaluate(VIS, "#panel") and r[0] >= 0 and r[2] <= w + 0.5 and r[2] >= w - 1 and pg.get_attribute("#panel-open", "aria-expanded") == "true", r)
            sw, vw, wide = pg.evaluate(WIDE)
            check(f"{tag}: the page is still the screen's width with the drawer open", sw == vw == w, (sw, vw, wide))
            ps, pc = pg.evaluate("(() => { const p = document.querySelector('#panel'); return [p.scrollWidth, p.clientWidth]; })()")
            check(f"{tag}: nothing inside the drawer scrolls sideways", ps <= pc, (ps, pc))
            o = pg.evaluate(ORDER); check(f"{tag}: the drawer holds Machines, Anchor hub, in that order", in_order(o), o)
            shot(pg, f"phone-{w}-{scheme}-drawer")
            align(pg, tag)
            tip_check(pg, tag)
            foc = lambda: pg.evaluate("document.activeElement && document.activeElement.id")
            pg.click("#panel-close"); pg.wait_for_timeout(300); check(f"{tag}: the close button closes it, focus back on the title bar's button", closed(pg) and foc() == "panel-open", foc())
            pg.click("#panel-open"); pg.wait_for_timeout(300); pg.mouse.click(10, 400); pg.wait_for_timeout(300); check(f"{tag}: a tap outside it closes it, focus back on the title bar's button (the tap had left it on the page)", closed(pg) and foc() == "panel-open", foc())
            pg.click("#panel-open"); pg.wait_for_timeout(300); pg.keyboard.press("Escape"); pg.wait_for_timeout(300); check(f"{tag}: Escape closes it, focus back on the title bar's button", closed(pg) and foc() == "panel-open", foc())
            st = pg.evaluate(STORE); check(f"{tag}: no storage or cookie holds the panel", st == [[], ""], st)
            pg2 = ctx.new_page(); pg2.goto(BOARD + "#machines"); pg2.wait_for_timeout(300)
            check(f"{tag}: a link to #machines opens the drawer and the Machines fold", pg2.evaluate(CLS) == ["panel-open"] and pg2.evaluate(VIS, "#panel") and pg2.evaluate("document.querySelector('#machines details.fold').open"), pg2.evaluate(CLS))
            pg2.close()
            pg3 = ctx.new_page(); pg3.goto(BOARD + "#anchorhub"); pg3.wait_for_timeout(300)
            check(f"{tag}: a link to #anchorhub opens the drawer", pg3.evaluate(CLS) == ["panel-open"] and pg3.evaluate(VIS, "#anchorhub"), pg3.evaluate(CLS))
            ctx.close()
    for scheme in ("light", "dark"):
        tag = f"panel 1440 {scheme}"
        ctx = br.new_context(viewport={"width": 1440, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(BOARD); pg.wait_for_timeout(100)
        # pinned on every load
        mp = pg.evaluate(RECT, "main#top"); pp = pg.evaluate(RECT, "#panel"); sw0, vw0, wide0 = pg.evaluate(WIDE)
        check(f"{tag}: pinned on load, the button expanded and offering to hide it", pg.evaluate(CLS) == ["panel-pin"] and pg.evaluate(VIS, "#panel") and pg.get_attribute("#panel-open", "aria-expanded") == "true" and pg.get_attribute("#panel-open", "title") == "Hide summary panel", pg.evaluate(CLS))
        check(f"{tag}: pinned on load, the main column is 920 px, the panel 280 px beside it, the page the screen's width", abs((mp[2] - mp[0]) - 920) < 1 and abs((pp[2] - pp[0]) - 280) < 1 and mp[2] <= pp[0] and sw0 == vw0 == 1440, (mp, pp, sw0, vw0, wide0))
        BT = lambda: [[round(v, 1) for v in pg.evaluate(RECT, q)] for q in ("#panel-open", "#theme")]   # the two buttons' boxes, to compare across the states
        bt0 = BT(); pt0 = pg.evaluate(RECT, "#panel")
        check(f"{tag}: pinned on load, the panel button and the theme button sit at the window's top right (16 px from the right, 12 px from the top), the panel right under them: top 56 px, flush with the right edge",
              abs(bt0[1][2] - (1440 - 16)) < 1 and abs(bt0[1][1] - 12) < 1 and abs(bt0[0][2] - (1440 - 56)) < 1 and abs(bt0[0][1] - 12) < 1 and abs(pt0[1] - 56) < 1 and abs(pt0[2] - 1440) < 1 and max(b[3] for b in bt0) <= pt0[1], (bt0, pt0))
        st = pg.evaluate(STORE); check(f"{tag}: no storage or cookie holds the panel", st == [[], ""], st)
        pg.click("#panel-open"); pg.mouse.move(600, 400); pg.wait_for_timeout(500)
        check(f"{tag}: a click on the button unpins it in this page view", closed(pg))
        m0 = pg.evaluate(RECT, "main#top"); w0 = m0[2] - m0[0]
        check(f"{tag}: the main column is 920 px", abs(w0 - 920) < 1, w0)
        check(f"{tag}: closed, the two buttons are where they were pinned", BT() == bt0, (BT(), bt0))
        hb = pg.evaluate(RECT, "header.top")[3]
        pg.mouse.move(1436, 500); pg.wait_for_timeout(350)       # the strip along the right edge
        r = pg.evaluate(RECT, "#panel"); m1 = pg.evaluate(RECT, "main#top")
        check(f"{tag}: the pointer on the right edge peeks the panel over the page, right under the buttons: 280 px wide, flush right, top 56 px, the same box as pinned", pg.evaluate(CLS) == ["panel-peek"] and pg.evaluate(VIS, "#panel") and abs(r[2] - 1440) < 1 and abs((r[2] - r[0]) - 280) < 1 and abs(r[1] - 56) < 1 and [round(v, 1) for v in r[:3]] == [round(v, 1) for v in pt0[:3]], (r, pt0))
        check(f"{tag}: peeking, the two buttons have not moved", BT() == bt0, (BT(), bt0))
        check(f"{tag}: a peek does not move the page", (m1[0], m1[2]) == (m0[0], m0[2]), (m0, m1))
        shot(pg, f"wide-1440-{scheme}-peek")
        pg.mouse.move(1300, 400); pg.wait_for_timeout(500)
        check(f"{tag}: the pointer on the peeking panel keeps it", pg.evaluate(CLS) == ["panel-peek"], pg.evaluate(CLS))
        pg.mouse.move(600, 400); pg.wait_for_timeout(600)
        check(f"{tag}: leaving it closes the peek", closed(pg))
        pg.hover("#panel-open"); pg.wait_for_timeout(350)
        check(f"{tag}: the pointer on the title bar's button peeks it too", pg.evaluate(CLS) == ["panel-peek"] and pg.get_attribute("#panel-open", "title") == "Pin summary panel" and pg.get_attribute("#panel-open", "aria-label") == "Summary panel", pg.evaluate(CLS))
        pg.click("#panel-open"); pg.wait_for_timeout(300)
        m2 = pg.evaluate(RECT, "main#top"); pr = pg.evaluate(RECT, "#panel"); sw, vw, wide = pg.evaluate(WIDE)
        check(f"{tag}: a click pins it beside the page", pg.evaluate(CLS) == ["panel-pin"] and pg.evaluate(VIS, "#panel") and pg.get_attribute("#panel-open", "title") == "Hide summary panel" and pg.get_attribute("#panel-open", "aria-label") == "Summary panel" and pg.get_attribute("#panel-open", "aria-expanded") == "true", pg.evaluate(CLS))
        check(f"{tag}: pinned, the main column keeps its 920 px", abs((m2[2] - m2[0]) - 920) < 1, m2)
        check(f"{tag}: pinned, the panel is 280 px, right of the main column and inside the screen, nothing overlapping", abs((pr[2] - pr[0]) - 280) < 1 and m2[2] <= pr[0] and pr[2] <= 1440.5 and abs(pr[1] - 56) < 1, (m2, pr))
        check(f"{tag}: pinned again, the two buttons are exactly where they were closed and peeking, above the panel", BT() == bt0 and max(b[3] for b in bt0) <= pr[1] and [round(v, 1) for v in pr[:3]] == [round(v, 1) for v in pt0[:3]], (BT(), bt0, pr))
        check(f"{tag}: pinned, the page is the screen's width", sw == vw == 1440, (sw, vw, wide))
        o = pg.evaluate(ORDER); check(f"{tag}: pinned, Machines, Anchor hub in that order", in_order(o), o)
        check(f"{tag}: pinned, Machines, Runners, Anchor hub, Audit and Projects all load open, with nothing stored", pg.evaluate(OPEN4) == [True] * 5, pg.evaluate(OPEN4))
        sp = pg.evaluate(SPACING)
        check(f"{tag}: the panel's sections share the Anchor hub's card spacing: 8px between cards, 6px 10px inside a card, 2px between a card's lines",
              sp["gap"] == {"machines": "8px", "runners": "8px", "anchorhub": "8px"} and set(sp["pad"].values()) == {"6px 10px 6px 10px"}
              and sp["pad"].keys() >= {"machines", "anchorhub", "audit", "ghcalls", "runners"} and sp["rowgap"] == {"machines": "2px", "anchorhub": "2px", "audit": "2px", "ghcalls": "2px"} and sp["auditgap"] == 8, sp)
        align(pg, tag)
        pg.evaluate("document.querySelector('#panel').scrollTop = 0")
        pg.hover("#audit-now"); pg.wait_for_timeout(100)
        hb = pg.evaluate("() => { const c = getComputedStyle(document.getElementById('audit-now')); return [c.textDecorationLine, c.color]; }")
        check(f"{tag}: hovering Audit now underlines it and keeps the accent", "underline" in hb[0] and hb[1] == colour(pg, "var(--acc)"), hb)
        pg.mouse.move(2, 2); pg.focus("body"); pg.keyboard.press("Tab")
        pg.evaluate("document.getElementById('audit-now').focus()"); pg.wait_for_timeout(50)
        fo = pg.evaluate("() => { const c = getComputedStyle(document.getElementById('audit-now')); return [c.outlineStyle, c.outlineWidth, c.outlineColor, document.getElementById('audit-now').matches(':focus-visible'), c.textDecorationLine]; }")
        check(f"{tag}: Audit now shows a 2px accent outline and an underline when focused by the keyboard", fo[3] and fo[0] == "solid" and fo[1] == "2px" and fo[2] == colour(pg, "var(--acc)") and "underline" in fo[4], fo)
        pg.evaluate("document.activeElement.blur()")
        pg.hover("#runners .pc.rc"); pg.wait_for_timeout(80)
        hr = pg.evaluate("() => { const c = document.querySelector('#runners .pc.rc'); return [getComputedStyle(c).borderTopColor, getComputedStyle(c.querySelector('.go')).color]; }")
        check(f"{tag}: hovering a Runners card turns its border and its ↗ accent", hr == [colour(pg, "var(--acc)")] * 2, hr)
        pg.mouse.move(2, 2)
        pg.evaluate("document.querySelector('#panel').scrollTop = 99999"); pg.wait_for_timeout(50); shot(pg, f"wide-1440-{scheme}-panel-foot"); pg.evaluate("document.querySelector('#panel').scrollTop = 0")      # the Audit card, at the foot of the panel
        check(f"{tag}: a card's name sits flush left with the lines under it, in Machines and in Anchor hub", all(abs(a - b) <= 0.5 for a, b in sp["flush"]) and len(sp["flush"]) >= 5, sp["flush"])
        check(f"{tag}: Machines: every card has the same columns, the package, version and 'latest' values line up from card to card",
              len(sp["cols"]) >= 5 and len({c[0] for c in sp["cols"]}) == 1 and len({c[1] for c in sp["cols"]}) == 1 and len({c[2] for c in sp["cols"]}) == 1, sp["cols"])
        pg.evaluate("document.querySelectorAll('details.fold').forEach(d => d.open = true)"); pg.wait_for_timeout(50)
        shot(pg, f"wide-1440-{scheme}-pinned")
        pg.evaluate("window.scrollTo(0, 700)"); pg.wait_for_timeout(100)
        r = pg.evaluate(RECT, "#panel"); check(f"{tag}: pinned, the panel and the two buttons stay where they are while the page scrolls (top 56 px)", abs(r[1] - 56) <= 1 and BT() == bt0, (r, BT(), bt0))
        pg.evaluate("window.scrollTo(0, 0)")
        tip_check(pg, f"{tag}: pinned")
        st = pg.evaluate(STORE); check(f"{tag}: no storage or cookie holds the panel", st == [[], ""], st)
        pg.click("#panel-open"); pg.mouse.move(600, 400); pg.wait_for_timeout(500)
        m3 = pg.evaluate(RECT, "main#top")
        check(f"{tag}: the next click unpins it and the page is back", closed(pg) and (m3[0], m3[2]) == (m0[0], m0[2]), (m0, m3))
        pg.hover("#panel-open"); pg.click("#panel-open"); pg.wait_for_timeout(200)
        pg.reload(); pg.wait_for_timeout(200); check(f"{tag}: pinned by hand, then a reload: it is pinned (the page's default; nothing is remembered)", pg.evaluate(CLS) == ["panel-pin"] and pg.evaluate(VIS, "#panel"), pg.evaluate(CLS))
        pg.click("#panel-open"); pg.mouse.move(600, 400); pg.wait_for_timeout(300); check(f"{tag}: unpinned by hand, then a reload", closed(pg))
        pg.reload(); pg.wait_for_timeout(200); check(f"{tag}: ... it is pinned again (the page's default; nothing is remembered)", pg.evaluate(CLS) == ["panel-pin"] and pg.evaluate(VIS, "#panel") and pg.evaluate("localStorage.length") == 0, pg.evaluate(CLS))
        pg2 = ctx.new_page(); pg2.goto(BOARD + "#anchorhub"); pg2.wait_for_timeout(300)
        check(f"{tag}: a link to #anchorhub pins the panel and shows it", pg2.evaluate(CLS) == ["panel-pin"] and pg2.evaluate(VIS, "#anchorhub"), pg2.evaluate(CLS))
        ctx.close()
    # the pinned default is in the markup and the CSS, not a late script: with script off (what the first paint sees) the panel is
    # docked beside the page at 1440 and a hidden drawer at 390
    for w, want_vis in ((1440, True), (1100, True), (390, False)):
        ctx = br.new_context(viewport={"width": w, "height": 900}, java_script_enabled=False); pg = ctx.new_page(); pg.goto(BOARD); pg.wait_for_timeout(100)
        pos = pg.evaluate("getComputedStyle(document.querySelector('#layout')).paddingRight")      # pinned, #layout leaves 288 px for the fixed panel
        check(f"panel {w} no script: the first paint is {'pinned (docked, visible)' if want_vis else 'a hidden drawer'}", pg.evaluate(VIS, "#panel") == want_vis and (pos == "288px") == want_vis, (pos, pg.evaluate(VIS, "#panel")))
        ctx.close()
    for w in (1280, 1100, 960, 800):
        tag = f"panel {w} light"
        ctx = br.new_context(viewport={"width": w, "height": 900}); pg = ctx.new_page(); pg.goto(BOARD); pg.wait_for_timeout(100)
        check(f"{tag}: pinned on load, with no click", pg.evaluate(CLS) == ["panel-pin"] and pg.evaluate(VIS, "#panel"), pg.evaluate(CLS))
        m2 = pg.evaluate(RECT, "main#top"); pr = pg.evaluate(RECT, "#panel"); sw, vw, wide = pg.evaluate(WIDE)
        want = min(920, w - 32 - 288)
        check(f"{tag}: pinned, the main column is {want} px (920 when the screen has room)", abs((m2[2] - m2[0]) - want) < 1, m2)
        check(f"{tag}: pinned, nothing overlaps and the page is the screen's width", m2[2] <= pr[0] and pr[2] <= w + 0.5 and sw == vw == w, (m2, pr, sw, vw, wide))

        pg.evaluate("document.querySelectorAll('details.fold').forEach(d => d.open = true); document.querySelector('#panel').scrollTop = 99999"); pg.wait_for_timeout(100)
        tt, la = pg.evaluate(RECT, "#totop"), pg.evaluate(RECT, "#anchorhub")
        check(f"{tag}: pinned, the back-to-top button does not sit on the panel's last card", la[3] <= tt[1] or la[2] <= tt[0] or la[0] >= tt[2], (la, tt))
        rl = pg.evaluate(RECT, "#reload")
        check(f"{tag}: pinned, neither floating button (reload, Back to top) sits on the panel's last card", all(la[3] <= b[1] or la[2] <= b[0] or la[0] >= b[2] for b in (rl, tt)), (la, rl, tt))
        if w == 800:      # at the lowest docking width the main column (480 px) is still usable beside the panel: title bar, search and the item cards inside it, no sideways scroll
            u = pg.evaluate("""() => { const r = s => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right), Math.round(b.width)]; };
              return {main: r('main#top'), search: r('header.top input[type=search], header.top input'), cards: [...document.querySelectorAll('main#top #your-move li, main#top #your-move .card')].slice(0, 6).map(e => Math.round(e.getBoundingClientRect().width)),
                      over: [...document.querySelectorAll('main#top #your-move *')].filter(e => e.getBoundingClientRect().right > document.querySelector('main#top').getBoundingClientRect().right + 0.5).length}; }""")
            check(f"{tag}: pinned at the lowest docking width, the main column is 480 px, the search box is usable (over 300 px) inside it, the item rows are about 480 px wide and nothing in Your move runs past the column",
                  u["main"][2] == 480 and u["search"] is not None and 300 < u["search"][2] <= 480 and u["search"][1] <= u["main"][1] and u["over"] == 0 and all(c >= 440 for c in u["cards"]), u)
            print("     800 px pinned:", u)
        if w in (1100, 800): shot(pg, f"wide-{w}-light-pinned")
        ctx.close()
        ctx = br.new_context(viewport={"width": w - 1, "height": 900}); pg = ctx.new_page(); pg.goto(BOARD)
        if w == 800:
            pg.mouse.move(w - 5, 400); pg.wait_for_timeout(300)
            check(f"panel {w - 1} light: below 800 px there is no peek; the button opens the drawer", pg.evaluate(CLS) == [], pg.evaluate(CLS))
            pg.click("#panel-open"); pg.wait_for_timeout(300); check(f"panel {w - 1} light: the drawer opens", pg.evaluate(CLS) == ["panel-open"], pg.evaluate(CLS)); shot(pg, f"phone-{w - 1}-light-drawer")
        ctx.close()
    # the rows _AUDIT_JS draws from GET /audit/status are the rows the server drew. One page per state of the audit: the first load keeps the server's rows (the status fetch is refused);
    # the second answers the status, the card is emptied and a poll tick makes the script redraw it. Same inner HTML, same classes and titles, same disabled button, nothing hidden.
    AUD = "() => { const e = document.getElementById('audit'); return {txt: e.querySelector('.a-txt').innerHTML, cls: e.className, hidden: e.hidden, dis: document.getElementById('audit-now').disabled, msg: e.querySelector('.a-msg').outerHTML}; }"
    for name, stt in AUDIT_STATES.items():
        got = {}
        for mode in ("server", "script"):
            ctx = br.new_context(viewport={"width": 412, "height": 900})
            ctx.add_init_script("window.fetch = () => Promise.reject(new TypeError('offline'));" if mode == "server" else
                                "window.__AUDIT = " + json.dumps(stt) + "; window.fetch = (u) => String(u).startsWith('/audit/status') ? Promise.resolve(new Response(JSON.stringify(window.__AUDIT), {status: 200, headers: {'Content-Type': 'application/json'}})) : Promise.reject(new TypeError('offline'));")
            pg = ctx.new_page(); pg.goto((OUT / f"audit-{name}.html").as_uri()); pg.wait_for_timeout(250)
            if mode == "script":
                pg.evaluate("document.querySelector('#audit .a-txt').replaceChildren(); document.getElementById('audit-now').disabled = false")
                pg.evaluate("document.dispatchEvent(new Event('stackshot:poll'))"); pg.wait_for_timeout(250)
            got[mode] = pg.evaluate(AUD); ctx.close()
        check(f"audit card ({name}): the rows the script draws from the status are the rows the server drew (inner HTML, classes, titles, the button's disabled state)",
              got["server"] == got["script"] and got["server"]["txt"] != "" and not got["server"]["hidden"] and got["server"]["dis"] == bool(stt.get("running")), got)
    # a long value in the Audit card (a run that did not finish: "<when> did not finish") wraps inside the card at phone width, nothing scrolls sideways
    for scheme in ("light", "dark"):
        for w in (360, 412):
            tag = f"audit card (crashed) {w} {scheme}"
            ctx = br.new_context(viewport={"width": w, "height": 800}, color_scheme=scheme); pg = ctx.new_page(); pg.goto((OUT / "audit-crashed.html").as_uri())
            pg.click("#panel-open"); pg.wait_for_timeout(300)
            v = pg.evaluate("""() => { const r = e => e.getBoundingClientRect(), c = r(document.getElementById('audit')), b = document.querySelector('#audit .a-bad'), p = document.getElementById('panel'), d = document.documentElement;
              const lb = document.querySelector('#audit .lbl'); return {text: b.textContent, right: r(b).right, cardRight: c.right, btnRight: r(document.getElementById('audit-now')).right, wraps: r(b).height > r(lb).height * 1.5, ws: getComputedStyle(b).whiteSpace,
                panel: [p.scrollWidth, p.clientWidth], page: [d.scrollWidth, d.clientWidth]}; }""")
            check(f"{tag}: the long 'did not finish' value wraps inside the Audit card (white-space normal), the card and the drawer have no sideways scroll, the page is the screen's width",
                  v["text"].endswith("did not finish") and v["ws"] == "normal" and v["right"] <= v["cardRight"] + 0.5 and v["btnRight"] <= v["cardRight"] + 0.5 and v["panel"][0] <= v["panel"][1] and v["page"][0] == v["page"][1] == w, v)
            ctx.close()
    # the panel stays pinned or open across the page's in-place update (_LIVE_JS): the second render has the machines card changed
    import urllib.parse
    ts1, ts2 = int(now.timestamp()), int((now + datetime.timedelta(minutes=2)).timestamp())
    h1, h2 = (OUT / "index.html").read_text(encoding="utf-8"), (OUT / "index2.html").read_text(encoding="utf-8")
    for w, mode, want in ((1440, "pinned", ["panel-pin"]), (390, "open", ["panel-open"])):
        tag = f"panel {w} in place"
        ctx = br.new_context(viewport={"width": w, "height": 900}); pg = ctx.new_page(); st = {"stamp": ts1, "n": 0}
        def handler(route, request, st=st):
            u = urllib.parse.urlparse(route.request.url).path
            if u == "/":
                st["n"] += 1; route.fulfill(status=200, content_type="text/html; charset=utf-8", body=h1 if st["n"] == 1 else h2)
            elif u == "/render-stamp": route.fulfill(status=200, content_type="application/json", body=json.dumps({"ts": st["stamp"]}))
            else: route.fulfill(status=404, body="")
        ctx.route(re.compile(r"^http://board\.test/"), handler)
        pg.goto("http://board.test/"); pg.wait_for_timeout(300)
        pg.evaluate("window.__same_page = 1")
        if w < 800: pg.click("#panel-open"); pg.wait_for_timeout(300)          # the drawer opens by a click; the wide panel is pinned on load
        check(f"{tag}: Machines, Runners, Anchor hub, Audit and Projects load open", pg.evaluate(OPEN4) == [True] * 5, pg.evaluate(OPEN4))
        pg.click("#anchorhub summary"); pg.wait_for_timeout(50)      # Anchor hub closed by hand, Machines left open: the swap carries both over as they are on screen
        check(f"{tag}: before the update the panel is {mode}, the old card is drawn and the Anchor hub fold is closed", pg.evaluate(CLS) == want and "2.1.140" in pg.inner_text("#machines") and not pg.evaluate("document.querySelector('#anchorhub details.fold').open"), pg.evaluate(CLS))
        st["stamp"] = ts2; pg.wait_for_timeout(2200); pg.evaluate("window.dispatchEvent(new Event('focus'))")
        try: pg.wait_for_function(f"document.querySelector('meta[name=stackshot-rendered]').content === '{ts2}'", timeout=6000); got = True
        except Exception: got = False
        check(f"{tag}: the page took the newer render in place (not a reload)", got and st["n"] == 2 and pg.evaluate("window.__same_page") == 1, (got, st["n"]))
        check(f"{tag}: the new Machines card is drawn", "2.1.141" in pg.inner_text("#machines"))
        check(f"{tag}: after the update there is still exactly one floating reload button, right above Back to top", pg.evaluate("document.querySelectorAll('#reload').length") == 1 and abs(pg.evaluate(RECT, "#totop")[1] - pg.evaluate(RECT, "#reload")[3] - 10) < 0.5)
        check(f"{tag}: after the update the panel is still {mode}, and the Anchor hub fold (closed by hand) is still closed, Machines, Runners and Audit still open, no stored state read back", pg.evaluate(CLS) == want and pg.evaluate(VIS, "#panel") and pg.evaluate(OPEN4) == [True, True, False, True, True], pg.evaluate(OPEN4))
        ctx.close()
    # ---- the answer forms do not flicker on load: drawn visible from the first paint with their buttons disabled and the link hidden; enabled when /answer-tokens answers;
    # a row that gets no token (an empty answer, an error, a redirect) hides its form (the row's title still links its item page); a step form's buttons are enabled with its token, an answer form's Send waits for a pick or a note. The token request is held by the test and answered after the first paint is measured ----
    gids = sorted(set(re.findall(r'data-gid="([^"]+)"', h1)))
    FM = """() => [...document.querySelectorAll('form.hanswer')].map(f => ({v: f.getBoundingClientRect().height > 0 && getComputedStyle(f).display !== 'none', d: [...f.querySelectorAll('button')].every(b => b.disabled),
        e: [...f.querySelectorAll('button')].every(b => !b.disabled), step: f.classList.contains('hstep'), t: f.querySelector('input[name=token]').value, k: !!f.nextElementSibling && getComputedStyle(f.nextElementSibling).display !== 'none'}))"""
    for w in (360, 1440):
        for mode in ("tokens", "empty", "error", "redirect"):
            tag = f"answer forms {w} {mode}"
            ctx = br.new_context(viewport={"width": w, "height": 900}); pg = ctx.new_page(); held = []
            def hnd(route, request, held=held):
                u = urllib.parse.urlparse(route.request.url).path
                if u == "/": route.fulfill(status=200, content_type="text/html; charset=utf-8", body=h1)
                elif u == "/answer-tokens": held.append(route)
                elif u == "/signin": route.fulfill(status=200, content_type="text/html", body="<p>sign in</p>")
                else: route.fulfill(status=404, body="")
            ctx.route(re.compile(r"^http://board\.test/"), hnd)
            pg.goto("http://board.test/", wait_until="domcontentloaded"); pg.wait_for_timeout(300)
            first = pg.evaluate(FM)
            check(f"{tag}: at the first paint every answer form is visible, its buttons disabled, its link hidden, no token (no other list shows for a frame)",
                  len(first) >= 5 and all(x["v"] and x["d"] and not x["k"] and x["t"] == "" for x in first) and len(held) == 1, (first[:2], len(held)))
            check(f"{tag}: the step rows are drawn at the first paint too", pg.evaluate("[65, 66, 67].every(n => document.querySelector('#task-a-' + n + ' form.hstep'))"))
            for rt in held:
                if mode == "tokens": rt.fulfill(status=200, content_type="application/json", body=json.dumps({g: "TOK-" + g for g in gids}))
                elif mode == "empty": rt.fulfill(status=200, content_type="application/json", body="{}")
                elif mode == "error": rt.fulfill(status=500, body="no")
                else: rt.fulfill(status=302, headers={"Location": "http://board.test/signin"}, body="")
            pg.wait_for_timeout(500)
            later = pg.evaluate(FM)
            if mode == "tokens":
                check(f"{tag}: once the tokens arrive every form carries its token and stays visible; a step form's buttons are enabled, an answer form's Send stays disabled until a pick or a note", all(x["v"] and x["t"].startswith("TOK-") and (x["e"] if x["step"] else x["d"]) for x in later), later[:2])
                clicked = pg.evaluate("""() => { const f = document.querySelector('#task-a-65 form.hstep'); let sent = null; f.addEventListener('submit', e => { e.preventDefault(); sent = Object.fromEntries(new FormData(f, e.submitter)) });
                    f.querySelector('button[value=send]').click(); return sent }""")
                check(f"{tag}: Send on a step row posts act=send with its token and back to the page's own path (no row fragment)", clicked and clicked.get("act") == "send" and clicked.get("token") == "TOK-a65" and clicked.get("back") == "/", clicked)
                pg.evaluate("document.dispatchEvent(new Event('stackshot:swapped'))"); pg.wait_for_timeout(100)
                check(f"{tag}: after an in-place swap the forms still carry their tokens, the step forms enabled", all(x["v"] and x["t"].startswith("TOK-") and (x["e"] or not x["step"]) for x in pg.evaluate(FM)))
            else:
                check(f"{tag}: with no token every form is hidden and carries none", all((not x["v"]) and x["t"] == "" for x in later), later[:2])
            ctx.close()
    # ---- after a Done sent from home (review F2): the redirect lands on the static page, which may still show the old row. The notice names who takes it when that name is
    # any mover name on the page (a loose guard), else the generic line; and the stale row's Send stays disabled, though the token arrives ----
    for w in (360, 1440):
        for label, then_q in (("a name on the page", None), ("a name not on the page", "Mallory%20the%20spoofer")):
            tag = f"home Done {w} {label}"
            ctx = br.new_context(viewport={"width": w, "height": 900}); pg = ctx.new_page()
            def hnd2(route, request):
                u = urllib.parse.urlparse(route.request.url).path
                if u == "/": route.fulfill(status=200, content_type="text/html; charset=utf-8", body=h1)
                elif u == "/answer-tokens": route.fulfill(status=200, content_type="application/json", body=json.dumps({g: "TOK-" + g for g in gids}))
                else: route.fulfill(status=404, body="")
            ctx.route(re.compile(r"^http://board\.test/"), hnd2)
            pg.goto("http://board.test/"); pg.wait_for_timeout(200)
            nm = pg.evaluate("[...document.querySelectorAll('.hwho')].map(x => x.textContent).find(t => t && t.length < 60)")
            pg.goto("http://board.test/?sent=done&item=a65&then=" + (urllib.parse.quote(nm) if then_q is None else then_q)); pg.wait_for_timeout(500)
            note = pg.evaluate("document.querySelector('p.isent') && document.querySelector('p.isent').textContent")
            if then_q is None: check(f"{tag}: the notice names who takes it", note and note.endswith(f"Done: {nm} takes it from here."), (nm, note))
            else: check(f"{tag}: the generic line is shown, the unknown name never", note and "Mallory" not in note and note.endswith("Done: the item goes on to its next mover."), note)
            st = pg.evaluate("(() => { const li = document.getElementById('task-a-65'); const d = li.querySelector('button[value=send]'); return {d: d.disabled, o: [...document.querySelectorAll('#task-a-66 form.hstep button')].every(b => !b.disabled)} })()")
            check(f"{tag}: the stale row's Send stays disabled after the token arrives, nothing else on the page is held back", st["d"] and st["o"], st)
            ctx.close()
    ctx = br.new_context(viewport={"width": 360, "height": 900}, java_script_enabled=False); pg = ctx.new_page(); pg.goto(PAGES["board"].as_uri())
    check("answer forms with scripts off: no form can be sent (every button disabled, no token)", all(x["d"] and x["t"] == "" for x in pg.evaluate(FM)))
    ctx.close()
    # ---- the answer box's bottom-edge handle: at 360 px it is inside the screen, the corner grip is off, and a drag with the mouse makes the box taller ----
    ctx = br.new_context(viewport={"width": 360, "height": 800}); pg = ctx.new_page(); pg.goto(PAGES["board"].as_uri()); pg.evaluate(OPEN); pg.wait_for_timeout(200)
    RS = "form.hanswer .rsz"
    TH = "document.querySelector('form.hanswer textarea').getBoundingClientRect().height"
    check("answer box 360: the textarea has no corner grip (resize none) and the handle is a horizontal separator", pg.evaluate("getComputedStyle(document.querySelector('form.hanswer textarea')).resize") == "none"
          and pg.get_attribute(RS, "role") == "separator" and pg.get_attribute(RS, "aria-orientation") == "horizontal" and pg.get_attribute(RS, "tabindex") == "0")
    pg.evaluate("document.querySelector('form.hanswer .rsz').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(150)
    RCT = "(s) => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }"
    hb, tb = pg.evaluate(RCT, RS), pg.evaluate(RCT, "form.hanswer textarea")
    check("answer box 360: the handle sits inside the screen, along the box's whole bottom edge", hb[0] >= 0 and hb[2] <= 360.5 and hb[1] >= 0 and hb[3] <= 800 and abs(hb[0] - tb[0]) < 1.5 and abs(hb[2] - tb[2]) < 1.5 and hb[3] > tb[3] - 0.5 and hb[1] < tb[3], (hb, tb))
    check("answer box 360: the handle's cursor is row-resize and its hit area is at least 12 px", pg.evaluate("getComputedStyle(document.querySelector('form.hanswer .rsz')).cursor") == "row-resize" and hb[3] - hb[1] >= 12, hb)
    h0 = pg.evaluate(TH); cx, cy = (hb[0] + hb[2]) / 2, (hb[1] + hb[3]) / 2
    pg.mouse.move(cx, cy); pg.mouse.down(); pg.mouse.move(cx, cy + 60, steps=6); pg.mouse.up(); pg.wait_for_timeout(100)
    h1 = pg.evaluate(TH)
    check("answer box 360: dragging the handle down with the mouse makes the box taller by the distance moved", abs(h1 - (h0 + 60)) < 2 and int(pg.get_attribute(RS, "aria-valuenow")) == round(h1), (h0, h1))
    pg.focus(RS); pg.keyboard.press("ArrowUp"); pg.wait_for_timeout(50)
    h2 = pg.evaluate(TH)
    check("answer box 360: Arrow Up on the focused handle makes it 16 px shorter", abs(h2 - (h1 - 16)) < 2, (h1, h2))
    pg.keyboard.press("Home"); pg.wait_for_timeout(50)
    check("answer box 360: Home sets the minimum height (aria-valuemin)", abs(pg.evaluate(TH) - float(pg.get_attribute(RS, "aria-valuemin"))) < 1, (pg.evaluate(TH), pg.get_attribute(RS, "aria-valuemin")))
    pg.keyboard.press("End"); pg.wait_for_timeout(50)
    check("answer box 360: End sets the maximum, 70% of the window", abs(pg.evaluate(TH) - 560) < 2 and pg.get_attribute(RS, "aria-valuemax") == "560", (pg.evaluate(TH), pg.get_attribute(RS, "aria-valuemax")))
    # the in-place swap, for real (_LIVE_JS replaces the Your move block with the newer render's): a handle being dragged or focused, or a box with text in it, holds the swap; once nothing holds it the swap lands and the
    # new box keeps the height the viewer gave it and gets its handle back
    P1, P2 = (OUT / "index.html").read_text(encoding="utf-8"), (OUT / "index2.html").read_text(encoding="utf-8")   # the two renders again (h1 and h2 above are heights by now)
    m3 = re.search(r'<meta name="stackshot-blocks" content="([^"]*)"', P2).group(1); ym = re.search(r"your-move=(\w+)", m3).group(1)
    h3 = P2.replace("your-move=" + ym, "your-move=" + ym[::-1])        # the newer render: the Your move block's fingerprint changed, so the page swaps that block
    assert h3 != P2 and "your-move=" + ym[::-1] in h3
    ctx = br.new_context(viewport={"width": 360, "height": 800}); pg = ctx.new_page(); st = {"stamp": ts1, "n": 0}
    def handler3(route, request):
        u = urllib.parse.urlparse(route.request.url)
        if u.path == "/":
            st["n"] += 1; route.fulfill(status=200, content_type="text/html; charset=utf-8", body=P1 if st["n"] == 1 else h3)
        elif u.path == "/render-stamp": route.fulfill(status=200, content_type="application/json", body=json.dumps({"ts": st["stamp"]}))
        elif u.path == "/answer-tokens": route.fulfill(status=200, content_type="application/json", body=json.dumps({g: "TOK" for g in urllib.parse.parse_qs(u.query)["ids"][0].split(",")}))
        else: route.fulfill(status=404, body="")
    ctx.route(re.compile(r"^http://board\.test/"), handler3)
    pg.goto("http://board.test/"); pg.wait_for_selector("form.hanswer:not([hidden]) .rsz"); pg.wait_for_timeout(300)
    def rendered(): return pg.evaluate("document.querySelector('meta[name=stackshot-rendered]').content")
    def poke(wait=1500):
        pg.wait_for_timeout(2200); pg.evaluate("window.dispatchEvent(new Event('focus'))"); pg.wait_for_timeout(wait)
    pg.evaluate("document.querySelector('form.hanswer').__old = 1; document.querySelector('form.hanswer .rsz').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(150)
    hb = pg.evaluate(RCT, RS); cx, cy = (hb[0] + hb[2]) / 2, (hb[1] + hb[3]) / 2; g0 = pg.evaluate(TH)
    pg.mouse.move(cx, cy); pg.mouse.down(); pg.mouse.move(cx, cy + 40, steps=4)
    st["stamp"] = ts2; poke()
    check("swap 360: a newer render does not land while the handle is being dragged", rendered() == str(ts1) and pg.evaluate("!!document.querySelector('form.hanswer').__old"), rendered())
    pg.mouse.move(cx, cy + 90, steps=4); pg.mouse.up(); pg.wait_for_timeout(100)
    check("swap 360: the drag carried on in the live box through the held swap (taller by the whole 90 px)", abs(pg.evaluate(TH) - (g0 + 90)) < 2, (g0, pg.evaluate(TH)))
    g1 = pg.evaluate(TH); poke()
    check("swap 360: a focused handle holds the swap too (it keeps the keyboard)", rendered() == str(ts1) and pg.evaluate("document.activeElement.classList.contains('rsz')"), rendered())
    pg.fill("form.hanswer textarea", "typed words"); poke()
    check("swap 360: a box with typed text holds the swap, and the text stays", rendered() == str(ts1) and pg.input_value("form.hanswer textarea") == "typed words", rendered())
    pg.fill("form.hanswer textarea", ""); pg.evaluate("document.activeElement.blur()"); poke(100)
    try: pg.wait_for_function(f"document.querySelector('meta[name=stackshot-rendered]').content === '{ts2}'", timeout=6000); landed = True
    except Exception: landed = False
    pg.wait_for_timeout(200)
    check("swap 360: once nothing holds it the swap lands: the form is a new node", landed and not pg.evaluate("!!document.querySelector('form.hanswer').__old"), landed)
    nv = pg.evaluate("(() => { const h = document.querySelector('form.hanswer .rsz'), t = document.querySelector('form.hanswer textarea'); return [Math.round(t.getBoundingClientRect().height), +h.getAttribute('aria-valuenow'), h.parentNode.classList.contains('js'), t.id, h.getAttribute('aria-controls')]; })()")
    check("swap 360: the new box has its handle back, keeps the height the viewer gave it, and the handle's values read it", abs(nv[0] - g1) < 2 and nv[1] == nv[0] and nv[2] and nv[3] and nv[3] == nv[4], (nv, g1))
    pg.evaluate("document.querySelector('form.hanswer .rsz').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(150)
    hb = pg.evaluate(RCT, RS); cx, cy = (hb[0] + hb[2]) / 2, (hb[1] + hb[3]) / 2
    pg.mouse.move(cx, cy); pg.mouse.down(); pg.mouse.move(cx, cy + 30, steps=3); pg.mouse.up(); pg.wait_for_timeout(100)
    check("swap 360: the new handle drags (it was bound by the page's document-level listeners, not by the old node)", abs(pg.evaluate(TH) - (nv[0] + 30)) < 2, (nv, pg.evaluate(TH)))
    ctx.close()
    # a second finger or a second button while a drag is on does not start another; a rotation keeps the box within 70% of the new height
    ctx = br.new_context(viewport={"width": 360, "height": 800}); pg = ctx.new_page(); pg.goto(PAGES["board"].as_uri()); pg.evaluate(OPEN); pg.wait_for_timeout(200)
    pg.evaluate("document.querySelector('form.hanswer .rsz').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(150)
    hb = pg.evaluate(RCT, RS); cx, cy = (hb[0] + hb[2]) / 2, (hb[1] + hb[3]) / 2
    pg.mouse.move(cx, cy); pg.mouse.down()
    pg.evaluate("(() => { const h = document.querySelector('form.hanswer .rsz'); h.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, pointerId: 77, pointerType: 'touch', clientY: 10})); })()")
    pg.mouse.up(); pg.wait_for_timeout(100)
    check("answer box 360: a second pointer going down mid-drag is ignored, and the drag ends clean (no stuck .drag)", pg.evaluate("document.querySelectorAll('.rsz.drag').length") == 0)
    pg.focus(RS); pg.keyboard.press("End"); pg.wait_for_timeout(50); pg.set_viewport_size({"width": 360, "height": 400}); pg.wait_for_timeout(150)
    check("answer box 360: on a resize the box is clamped to the new 70% (280 px) and the handle's values follow", abs(pg.evaluate(TH) - 280) < 2 and pg.get_attribute(RS, "aria-valuemax") == "280" and int(pg.get_attribute(RS, "aria-valuenow")) == round(pg.evaluate(TH)), (pg.evaluate(TH), pg.get_attribute(RS, "aria-valuemax")))
    ctx.close()
    # the item page's answer box: the same handle, dragged
    ctx = br.new_context(viewport={"width": 360, "height": 800}); pg = ctx.new_page(); pg.goto((OUT / "items/a60.html").as_uri()); pg.wait_for_timeout(200)
    IR = "form.ianswer .rsz"; IT = "document.querySelector('form.ianswer textarea').getBoundingClientRect().height"
    check("item page 360: the answer box has no corner grip and its handle is a separator that controls the textarea", pg.evaluate("getComputedStyle(document.querySelector('form.ianswer textarea')).resize") == "none" and pg.get_attribute(IR, "role") == "separator" and pg.get_attribute(IR, "aria-controls") == "atext")
    pg.evaluate("document.querySelector('form.ianswer .rsz').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(150)
    ib = pg.evaluate(RCT, IR); ti = pg.evaluate(RCT, "form.ianswer textarea")
    check("item page 360: the handle sits inside the screen along the box's whole bottom edge", ib[0] >= 0 and ib[2] <= 360.5 and abs(ib[0] - ti[0]) < 1.5 and abs(ib[2] - ti[2]) < 1.5 and ib[1] < ti[3] < ib[3] + 0.5, (ib, ti))
    i0 = pg.evaluate(IT); cx, cy = (ib[0] + ib[2]) / 2, (ib[1] + ib[3]) / 2
    pg.mouse.move(cx, cy); pg.mouse.down(); pg.mouse.move(cx, cy + 50, steps=5); pg.mouse.up(); pg.wait_for_timeout(100)
    check("item page 360: dragging the handle makes the answer box taller by the distance moved", abs(pg.evaluate(IT) - (i0 + 50)) < 2, (i0, pg.evaluate(IT)))
    ctx.close()
    # ---- next as a checklist: the boxes and the text inside the screen, a done step muted, a dropped one struck through, all readable (4.5:1), nothing wider than the screen
    CLJS = """() => { const q = s => document.querySelector(s), rc = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }, cs = e => getComputedStyle(e);
      const done = q('li.cl-done'), drop = q('li.cl-dropped'), open = q('li.cl-open'), ul = q('ul.inext');
      return {n: document.querySelectorAll('ul.inext > li').length, ul: rc(ul), boxes: [...document.querySelectorAll('ul.inext .cb')].map(rc), texts: [...document.querySelectorAll('ul.inext .cl-b')].map(rc),
              doneColor: cs(done.querySelector('.cl-t')).color, dropColor: cs(drop.querySelector('.cl-t')).color, doneBox: [cs(done.querySelector('.cb')).backgroundColor, cs(done.querySelector('.cb')).borderTopColor, cs(done.querySelector('.cb')).color], dropBox: [cs(drop.querySelector('.cb')).backgroundColor, cs(drop.querySelector('.cb')).borderTopColor, cs(drop.querySelector('.cb')).color], dropOpacity: cs(drop).opacity, okWord: cs(done.querySelector('.cl-by b')).color, dropWord: cs(drop.querySelector('.cl-by b')).fontWeight, doneWord: cs(done.querySelector('.cl-by b')).fontWeight, openColor: cs(open.querySelector('.cl-t')).color, dropDeco: cs(drop.querySelector('.cl-t')).textDecorationLine, doneDeco: cs(done.querySelector('.cl-t')).textDecorationLine,
              openDeco: cs(open.querySelector('.cl-t')).textDecorationLine, by: [...document.querySelectorAll('ul.inext .cl-by')].map(e => [e.textContent, cs(e).color, cs(e).fontSize, rc(e)]), page: cs(document.body).backgroundColor,
              inputs: document.querySelectorAll('ul.inext input').length, sr: [...document.querySelectorAll('ul.inext .sr')].map(e => [e.textContent, e.getBoundingClientRect().width, cs(e).position]),
              glyphs: [...document.querySelectorAll('ul.inext .cb')].map(e => [e.textContent, cs(e).borderTopWidth, cs(e).width])}; }"""
    CLSHOTS = os.environ.get("PHONE_WIDTH_SHOTS", "")
    for scheme, w in (("light", 360), ("light", 412), ("dark", 360), ("dark", 412)):
        ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto((OUT / "items/cl1.html").as_uri()); pg.wait_for_timeout(150)
        pg.evaluate(OPEN); pg.wait_for_timeout(50)
        cl = pg.evaluate(CLJS)
        tag = f"checklist {w} {scheme}"
        check(f"{tag}: five steps, a list inside the screen, each box and each text block inside it, the box left of its text", cl["n"] == 5 and cl["ul"][0] >= 0 and cl["ul"][2] <= w + 0.5
              and all(b[0] >= 0 and b[2] <= w + 0.5 for b in cl["boxes"] + cl["texts"]) and all(b[2] <= t[0] + 0.5 for b, t in zip(cl["boxes"], cl["texts"])), cl)
        check(f"{tag}: the boxes are drawn by CSS (a bordered square, a check or a cross in it), the checklist holds no input, and a screen reader hears To do / Done / Dropped",
              cl["inputs"] == 0 and [g[0] for g in cl["glyphs"]] == ["", "", "✓", "✓", "×"] and all(g[1] != "0px" and g[2] in ("17px", "17.0px") for g in cl["glyphs"])
              and [x[0] for x in cl["sr"]] == ["To do: ", "To do: ", "Done: ", "Done: ", "Dropped: "] and all(x[1] <= 2 and x[2] == "absolute" for x in cl["sr"]), cl["glyphs"] + cl["sr"])
        check(f"{tag}: a done step's text is at full strength (the open text's colour), a dropped one is muted and struck through, an open one is neither", cl["doneColor"] == cl["openColor"] and cl["dropColor"] != cl["openColor"] and cl["dropDeco"] == "line-through"
              and cl["doneDeco"] == "none" and cl["openDeco"] == "none", (cl["doneColor"], cl["openColor"], cl["dropDeco"], cl["doneDeco"]))
        check(f"{tag}: the done step's text and its byline stay readable (4.5:1 at least)", contrast(cl["doneColor"], cl["page"], cl["page"]) >= 4.5 and all(contrast(x[1], cl["page"], cl["page"]) >= 4.5 for x in cl["by"][:2]), (cl["doneColor"], cl["by"], cl["page"]))
        check(f"{tag}: a done box is filled with the green token and its tick is the page colour, a dropped box is empty with a grey border and cross, dropped sits at .75, 'done' is green and both verbs bold",
              cl["doneBox"][0] == cl["doneBox"][1] != cl["page"] and cl["doneBox"][2] == cl["page"] and cl["dropBox"][0] in ("rgba(0, 0, 0, 0)", "transparent") and cl["dropBox"][1] == cl["dropBox"][2] and cl["dropOpacity"] == "0.75"
              and cl["okWord"] == cl["doneBox"][1] and cl["dropWord"] == "600" and cl["doneWord"] == "600", cl)
        check(f"{tag}: done and dropped steps each say 'done by' / 'dropped by', who and when, under the text, inside the screen", [x[0].split(" · ")[0] for x in cl["by"]] == ["done by ops-falcon-engineer", "done by Oliver", "dropped by ops-falcon-engineer"] and all(x[3][2] <= w + 0.5 for x in cl["by"]) and all(x[0].count(" · ") == 1 for x in cl["by"]), cl["by"])
        if CLSHOTS and (scheme, w) in (("light", 412), ("dark", 360)):
            os.makedirs(CLSHOTS, exist_ok=True)
            pg.evaluate("document.querySelectorAll('#reload, #totop').forEach(e => e.style.display = 'none')"); pg.locator("details#next").scroll_into_view_if_needed()
            pg.screenshot(path=os.path.join(CLSHOTS, f"cl-itempage-{w}-{scheme}.png"), full_page=True)
        ctx.close()
    # ---- the Your step block holds his own Next lines in full, a Copy button under each command; Next below stays whole
    YSJS = """() => { const q = s => document.querySelector(s), rc = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
      const blk = q('.istep'), sn = q('.istep .istepnext'), nx = [...document.querySelectorAll('ul.inext > li')];
      return {blk: rc(blk), sn: sn && rc(sn), items: sn ? [...sn.querySelectorAll('ol > li')].map(rc) : [], cmds: sn ? [...sn.querySelectorAll('.cmd')].map(e => [rc(e), rc(e.querySelector('button.copy')), e.scrollWidth <= e.clientWidth + 1 || getComputedStyle(e.querySelector('pre')).overflowX]) : [],
              order: sn ? (blk.textContent.indexOf('One line in PowerShell') < blk.textContent.indexOf('In PowerShell run')) : false, text: sn ? sn.textContent : '', next: nx.length, nextText: nx.map(e => e.textContent), scrollW: document.documentElement.scrollWidth}; }"""
    for scheme, w in (("light", 360), ("light", 412), ("dark", 360), ("dark", 412)):
        ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto((OUT / "items/cl2.html").as_uri()); pg.wait_for_timeout(150)
        pg.evaluate(OPEN); pg.wait_for_timeout(50)
        if not pg.query_selector(".istep"): print("DEBUG a81:", pg.inner_text("body")[:1200]); sys.exit(1)
        ys = pg.evaluate(YSJS)
        tag = f"your step {w} {scheme}"
        check(f"{tag}: the step's summary line, then two numbered items of his in full, the agent's lines not among them, each inside the screen", ys["sn"] is not None and ys["order"] and len(ys["items"]) == 2
              and ys["sn"][0] >= 0 and ys["sn"][2] <= w + 0.5 and all(i[0] >= 0 and i[2] <= w + 0.5 for i in ys["items"]) and "put the box in place" not in ys["text"] and "read what he pasted" not in ys["text"]
              and "Oliver:" not in ys["text"], ys)
        check(f"{tag}: each command is a block with a Copy button inside the screen and inside the block, under the line of its item", len(ys["cmds"]) == 2
              and all(c[0][0] >= 0 and c[0][2] <= w + 0.5 and c[1][0] >= c[0][0] - 0.5 and c[1][2] <= c[0][2] + 0.5 and c[1][3] <= c[0][3] + 0.5 for c in ys["cmds"])
              and all(ys["items"][k][1] < ys["cmds"][k][0][1] for k in range(2)), ys["cmds"])
        check(f"{tag}: Next below stays whole (all four steps, his lines with their names), and the page is no wider than the screen", ys["next"] == 4
              and sum("Oliver:" in t for t in ys["nextText"]) == 2 and any("put the box in place" in t for t in ys["nextText"]) and ys["scrollW"] <= w + 1, (ys["next"], ys["scrollW"], ys["nextText"]))
        if CLSHOTS and (scheme, w) in (("light", 412), ("dark", 360)):
            pg.evaluate("document.querySelectorAll('#reload, #totop').forEach(e => e.style.display = 'none')"); pg.locator(".istep").scroll_into_view_if_needed()
            pg.screenshot(path=os.path.join(CLSHOTS, f"cl-yourstep-{w}-{scheme}.png"), full_page=True)
        ctx.close()
    # ---- the home title and the side panel on the item page, the project page, Landed and Search: the title bar is the home h1 (logo and title)
    # as a link to exactly "/", underlined only on hover; the panel stands pinned on the right from 800 px up and is a closed drawer below; the page keeps the screen's width at
    # 360 px and 1300 px in both themes; the item page's Details column moves above the main column while the pinned panel leaves too little room (below _ITEM_PIN_STRIP_PX) ----
    TP = """() => { const a = [...document.querySelectorAll('header.top .site a')], s = document.querySelector('header.top .site'), pn = document.getElementById('panel'), r = pn ? pn.getBoundingClientRect() : null, m = document.querySelector('main'), mr = m.getBoundingClientRect(), cs = a[0] ? getComputedStyle(a[0]) : null, im = a[0] ? a[0].querySelector('img.logo') : null;
      return {hrefs: a.map(x => x.getAttribute('href')), size: s ? getComputedStyle(s).fontSize : '', deco: cs ? cs.textDecorationLine : '', color: cs ? cs.color : '', fg: getComputedStyle(document.body).color, logo: im ? im.getBoundingClientRect().width : 0,
              pin: document.body.classList.contains('panel-pin'), layout: !!document.getElementById('layout'), panel: r ? [r.left, r.width, r.right, r.top] : null, pb: (e => e ? [e.getBoundingClientRect().left, e.getBoundingClientRect().top, e.getBoundingClientRect().right] : null)(document.getElementById('panel-open')), tbtn: (e => e ? [e.getBoundingClientRect().left, e.getBoundingClientRect().top, e.getBoundingClientRect().right] : null)(document.getElementById('theme')), vis: pn ? getComputedStyle(pn).visibility : '', mainRight: mr.right, vw: document.documentElement.clientWidth,
              btn: !!document.getElementById('panel-open'), theme: !!document.getElementById('theme'), cards: document.querySelectorAll('.hcards').length, edge: !!document.getElementById('panel-edge'), scrim: !!document.getElementById('panel-scrim')}; }"""
    DET = """() => { const side = document.querySelector('.iside').getBoundingClientRect(), ms = [...document.querySelectorAll('.imain > *')].map(e => e.getBoundingClientRect()).filter(r => r.height > 0), m = ms[0], below = ms.filter(r => r.top >= side.bottom - 1).length;
      return {below: below, sideTop: side.top, sideLeft: side.left, sideRight: side.right, sideBottom: side.bottom, mainTop: m.top, mainLeft: m.left, mainRight: m.right, pin: document.body.classList.contains('panel-pin'), vw: document.documentElement.clientWidth, sw: document.documentElement.scrollWidth}; }"""
    TPAGES = {"item page": "item page", "project page": "project page", "landed page": "landed page", "results page": "results page", "runners page": "runners page"}
    for nm in TPAGES:
        for scheme in ("light", "dark"):
            for w in (360, 1300):
                tag = f"title+panel {nm} {w} {scheme}"
                ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES[nm].as_uri()); pg.evaluate(OPEN); pg.wait_for_timeout(100)
                sw, vw, wide = pg.evaluate(WIDE)
                check(f"{tag}: no horizontal overflow, with every fold open", sw == vw == w, (sw, vw, wide))
                d = pg.evaluate(TP)
                check(f"{tag}: the title is the home's h1 look (logo and name) as one link whose href is exactly '/', 17 px, in the text colour, not underlined at rest",
                      d["hrefs"] == ["/"] and d["size"] == "17px" and d["logo"] > 10 and d["deco"] == "none" and d["color"] == d["fg"], d)
                check(f"{tag}: the panel button and the theme button are in the title bar, the panel, its edge and scrim and the layout wrapper on the page, and the one row of count cards", d["btn"] and d["theme"] and d["edge"] and d["scrim"] and d["layout"] and d["cards"] == 1 and d["panel"] is not None, d)
                if w == 1300:
                    if nm == "item page":      # the item page's panel starts closed; pin it by a click, the checks below are of the pinned panel
                        check(f"{tag}: the panel starts closed: no panel-pin, hidden, the button offering to show it", not d["pin"] and d["vis"] == "hidden" and pg.get_attribute("#panel-open", "aria-expanded") == "false", d)
                        pg.click("#panel-open"); pg.mouse.move(300, 400); pg.wait_for_timeout(400); d = pg.evaluate(TP)
                    check(f"{tag}: the panel is pinned{' by a click' if nm == 'item page' else ' on load'}: body.panel-pin, visible, 280 px wide, beside the main column and inside the screen",
                          d["pin"] and d["vis"] == "visible" and abs(d["panel"][1] - 280) < 1 and d["panel"][0] >= d["mainRight"] - 0.5 and d["panel"][2] <= d["vw"] + 0.5, d)
                    check(f"{tag}: the panel button and the theme button are fixed at the window's top right (right edges 56 and 16 px in, top 12 px) and the panel starts 56 px from the top, right under them",
                          abs(d["tbtn"][2] - (w - 16)) < 1 and abs(d["pb"][2] - (w - 56)) < 1 and abs(d["pb"][1] - 12) < 1 and abs(d["tbtn"][1] - 12) < 1 and abs(d["panel"][3] - 56) < 1, d)
                    pg.evaluate("window.scrollTo(0, 400)"); pg.wait_for_timeout(100); d2 = pg.evaluate(TP)
                    check(f"{tag}: scrolled, the buttons and the panel have not moved", d2["pb"] == d["pb"] and d2["tbtn"] == d["tbtn"] and d2["panel"][3] == d["panel"][3], (d["pb"], d2["pb"], d["panel"], d2["panel"]))
                    pg.click("#panel-open"); pg.mouse.move(300, 400); pg.wait_for_timeout(400); d3 = pg.evaluate(TP)
                    check(f"{tag}: unpinned, the buttons stay where they were", not d3["pin"] and d3["pb"] == d["pb"] and d3["tbtn"] == d["tbtn"], (d["pb"], d3["pb"], d3["pin"]))
                    pg.hover("#panel-open"); pg.wait_for_timeout(400); d4 = pg.evaluate(TP)
                    check(f"{tag}: peeking, the buttons stay and the panel is the same box as pinned: 280 px wide, flush right, 56 px from the top", d4["pb"] == d["pb"] and d4["tbtn"] == d["tbtn"] and abs(d4["panel"][1] - 280) < 1 and abs(d4["panel"][2] - w) < 1 and abs(d4["panel"][3] - 56) < 1, d4)
                    pg.mouse.move(300, 400); pg.wait_for_timeout(500)
                    if scheme == "light":
                        pg.hover("header.top .site a"); pg.wait_for_timeout(50)
                        check(f"{tag}: the title link is underlined on hover", "underline" in pg.evaluate("getComputedStyle(document.querySelector('header.top .site a')).textDecorationLine"))
                else:
                    check(f"{tag}: below 800 px the panel is a closed drawer (not pinned, hidden)", not d["pin"] and d["vis"] == "hidden", d)
                ctx.close()
    # the item page's Details column against the panel (the panel starts closed there): with it closed the two columns hold down to 768 px; pinned by a click, Details is above the main
    # column (the one-column strip) while the page's room is under _ITEM_PIN_STRIP_PX, beside it at that width and wider
    EDGE = render._ITEM_PIN_STRIP_PX
    for scheme in ("light", "dark"):
        for w, want in ((360, "strip"), (700, "strip"), (767, "strip"), (768, "cols"), (799, "cols"), (800, "strip"), (900, "strip"), (1000, "strip"), (EDGE - 1, "strip"), (EDGE, "cols"), (1200, "cols"), (1300, "cols"), (1920, "cols")):
            ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(PAGES["item page"].as_uri()); pg.evaluate(OPEN); pg.wait_for_timeout(100)
            for state in ("closed", "pinned"):
                if state == "pinned":
                    if w < 800: break           # narrow: the button opens a drawer, nothing is pinned
                    pg.click("#panel-open"); pg.mouse.move(300, 400); pg.wait_for_timeout(300)
                    exp = want
                else: exp = "strip" if w < 768 else "cols"
                tag = f"item page {w} {scheme}: panel {state if w >= 800 else 'a closed drawer'}"
                d = pg.evaluate(DET)
                if exp == "strip": ok = d["below"] > 0 and abs(d["sideLeft"] - d["mainLeft"]) < 1      # one column: Details over the item's body (the title and state line stay above it)
                else: ok = d["sideLeft"] >= d["mainRight"] + 16 and d["sideTop"] < d["mainTop"] + 400
                check(f"{tag}: Details is {'on top, in the one-column strip' if exp == 'strip' else 'in its own column beside the main column'}" + (" (the pinned panel leaves too little room)" if exp == "strip" and w >= 800 else ""), ok and d["sw"] == d["vw"] and d["pin"] == (state == "pinned"), d)
            ctx.close()
    ctx = br.new_context(viewport={"width": 900, "height": 900}); pg = ctx.new_page(); pg.goto(PAGES["item page"].as_uri()); pg.wait_for_timeout(100); d = pg.evaluate(DET)
    check("item page 900: loaded with the panel closed, Details is beside the main column", not d["pin"] and d["sideLeft"] >= d["mainRight"] + 16, d)
    pg.click("#panel-open"); pg.wait_for_timeout(100); d = pg.evaluate(DET)
    check("item page 900: pinning the panel puts Details on top", d["pin"] and d["below"] > 0 and abs(d["sideLeft"] - d["mainLeft"]) < 1, d)
    pg.click("#panel-open"); pg.mouse.move(600, 400); pg.wait_for_timeout(100); d = pg.evaluate(DET)
    check("item page 900: unpinning it gives the room back: Details returns beside the main column", not d["pin"] and d["sideLeft"] >= d["mainRight"] + 16, d)
    ctx.close()
    # ---- the panel's default: every page opens pinned but the item page, which opens closed; a pin or unpin by the button lasts until the reload; nothing is stored ----
    KEYS = "() => { try { return Object.keys(localStorage).filter(k => /panel/i.test(k)); } catch (e) { return ['throws']; } }"
    ISPIN = "() => document.body.classList.contains('panel-pin') && getComputedStyle(document.getElementById('panel')).visibility === 'visible'"
    ISOFF = "() => !document.body.classList.contains('panel-pin') && getComputedStyle(document.getElementById('panel')).visibility === 'hidden'"
    DEFAULT = lambda nm: ISOFF if nm == "item page" else ISPIN
    OTHER = lambda nm: ISPIN if nm == "item page" else ISOFF
    ALLPAGES = ("board", "results page", "runners page", "project page", "landed page", "item page")
    ctx = br.new_context(viewport={"width": 1300, "height": 900}); pg = ctx.new_page()
    for nm in ALLPAGES:
        pg.goto(PAGES[nm].as_uri()); pg.wait_for_timeout(100)
        check(f"panel default: the {nm} opens {'closed' if nm == 'item page' else 'pinned'}, and loading it wrote nothing", pg.evaluate(DEFAULT(nm)) and pg.evaluate(KEYS) == [], (pg.evaluate(CLS), pg.evaluate(KEYS)))
        pg.click("#panel-open"); pg.mouse.move(600, 400); pg.wait_for_timeout(500)
        check(f"panel default: on the {nm} the button flips it, and writes nothing", pg.evaluate(OTHER(nm)) and pg.evaluate(KEYS) == [], (pg.evaluate(CLS), pg.evaluate(KEYS)))
        pg.reload(); pg.wait_for_timeout(100)
        check(f"panel default: the {nm}, flipped by hand, then a reload: back to its default (nothing is remembered)", pg.evaluate(DEFAULT(nm)), pg.evaluate(CLS))
    pg.goto(PAGES["board"].as_uri()); pg.wait_for_timeout(100); pg.click("#panel-open"); pg.mouse.move(600, 400); pg.wait_for_timeout(300)
    for nm in ALLPAGES:
        pg.goto(PAGES[nm].as_uri()); pg.wait_for_timeout(100)
        check(f"panel default: unpinned on the home page, the {nm} still opens at its own default", pg.evaluate(DEFAULT(nm)), pg.evaluate(CLS))
    pg.goto(PAGES["item page"].as_uri()); pg.wait_for_timeout(100); pg.click("#panel-open"); pg.mouse.move(600, 400); pg.wait_for_timeout(300)
    pg.set_viewport_size({"width": 600, "height": 900}); pg.wait_for_timeout(100)
    pg.set_viewport_size({"width": 1300, "height": 900}); pg.wait_for_timeout(100)
    check("panel default: the item page, pinned by hand, crossing 800 px down and back up: it is back at its default, closed", pg.evaluate(ISOFF), pg.evaluate(CLS))
    pg.goto(PAGES["board"].as_uri()); pg.set_viewport_size({"width": 1300, "height": 900}); pg.wait_for_timeout(100); pg.click("#panel-open"); pg.mouse.move(600, 400); pg.wait_for_timeout(500)
    a = pg.evaluate(ISOFF)
    pg.set_viewport_size({"width": 600, "height": 900}); pg.wait_for_timeout(100)
    pg.set_viewport_size({"width": 1300, "height": 900}); pg.wait_for_timeout(100)
    check("panel default: the home page, unpinned by hand, crossing 800 px down and back up: it is back at its default, pinned", a and pg.evaluate(ISPIN), (a, pg.evaluate(CLS)))
    pg.set_viewport_size({"width": 360, "height": 900}); pg.wait_for_timeout(100)
    pg.click("#panel-open"); pg.wait_for_timeout(300)
    check("panel default: on a phone the button opens the drawer and writes nothing", pg.evaluate(CLS) == ["panel-open"] and pg.evaluate(KEYS) == [], (pg.evaluate(CLS), pg.evaluate(KEYS)))
    ctx.close()
    # a key an older build wrote ('stackshot.panel') is ignored, whatever its value
    for val in ("unpinned", "pinned", "sideways"):
        ctx = br.new_context(viewport={"width": 1300, "height": 900}); ctx.add_init_script(f"try{{localStorage.setItem('stackshot.panel','{val}')}}catch(e){{}}")
        pg = ctx.new_page()
        for nm in ("board", "item page"):
            pg.goto(PAGES[nm].as_uri()); pg.wait_for_timeout(100)
            check(f"panel default: an old stored '{val}' is ignored: the {nm} opens at its own default", pg.evaluate(DEFAULT(nm)), pg.evaluate(CLS))
        ctx.close()
    # storage that throws (a private window, blocked site data): every page still renders at its default and the button still works for the page view
    for nm in ALLPAGES:
        ctx = br.new_context(viewport={"width": 1300, "height": 900}); ctx.add_init_script("Object.defineProperty(window, 'localStorage', {get: function(){ throw new Error('storage denied'); }});")
        pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e, errs=errs: errs.append(str(e))); pg.goto(PAGES[nm].as_uri()); pg.evaluate(OPEN); pg.wait_for_timeout(100)
        sw, vw, wide = pg.evaluate(WIDE)
        check(f"panel default, storage throws: the {nm} renders at its default, no script error, no overflow", pg.evaluate(DEFAULT(nm)) and not errs and sw == vw == 1300, (pg.evaluate(CLS), errs, sw, vw))
        pg.click("#panel-open"); pg.mouse.move(600, 400); pg.wait_for_timeout(500)
        a = pg.evaluate(OTHER(nm)); pg.click("#panel-open"); pg.mouse.move(600, 400); pg.wait_for_timeout(300)
        check(f"panel default, storage throws: on the {nm} the button still flips it and back for the page view, no script error", a and pg.evaluate(DEFAULT(nm)) and not errs, (a, errs))
        ctx.close()
    # the home page: the title is one link to "/", so a click there clears any #hash
    ctx = br.new_context(viewport={"width": 1300, "height": 900}); pg = ctx.new_page(); pg.goto(PAGES["board"].as_uri()); pg.wait_for_timeout(100)
    check("board 1300: the h1 (logo and title) is wrapped in one link whose href is exactly '/'", pg.evaluate("[...document.querySelectorAll('header.top .site a')].map(a => a.getAttribute('href'))") == ["/"] and pg.evaluate("getComputedStyle(document.querySelector('header.top .site')).fontSize") == "17px")
    ctx.close()
    # the Runners column: each machine's runners one per line, top to bottom (a single column), at a desktop width and at phone widths, light and dark
    RL = """() => [...document.querySelectorAll('ul.rl')].map(ul => [...ul.children].map(li => { const r = li.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top), Math.round(r.bottom), Math.round(r.right)]; }))"""
    for nm, f in RUNNER_LISTS.items():
        for scheme in ("light", "dark"):
            for w in (360, 412, 1280, 1440):
                ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(f.as_uri()); pg.wait_for_timeout(50)
                lists, (sw, vw, wide) = pg.evaluate(RL), pg.evaluate(WIDE)
                six = next((l for l in lists if len(l) == 6), None)
                check(f"{nm} {w} {scheme}: the six runners of one machine stand one per line, top to bottom (one left edge, each below the one before)",
                      six is not None and len({x[0] for x in six}) == 1 and all(six[i][1] >= six[i - 1][2] - 1 for i in range(1, 6)), lists)
                check(f"{nm} {w} {scheme}: every runner list is a single column, inside the screen", all(len({x[0] for x in l}) == 1 and max(x[3] for x in l) <= w for l in lists if l), lists)
                check(f"{nm} {w} {scheme}: the page is the screen's width (no sideways scroll)", sw == vw == w, (sw, vw, wide))
                ctx.close()
    # ---- the pages' header: every page starts with home's header, the title, the five count cards and the search box, inside the screen at phone widths and wide,
    # the cards 60 px tall and in a row with the list cards linking home's lists, the header sticky when wide and not on a phone. PHONE_WIDTH_HEADER_SHOTS=<dir> keeps a screenshot of the item page and the Projects page.
    HSHOTS = os.environ.get("PHONE_WIDTH_HEADER_SHOTS", "")
    if HSHOTS: os.makedirs(HSHOTS, exist_ok=True)
    HDR = """() => { const q = s => document.querySelector(s), H = q('header.top'), r = e => e.getBoundingClientRect(), vw = document.documentElement.clientWidth;
      const cards = [...document.querySelectorAll('header.top #counts a.hcard')].map(a => { const b = r(a); return {href: a.getAttribute('href'), label: [...a.querySelector('span').childNodes].filter(x => !(x.nodeType === 1 && x.matches('i.hnew'))).map(x => x.textContent).join('').trim(), h: Math.round(b.height), l: b.left, r: b.right, top: Math.round(b.top)}; });
      return {n: document.querySelectorAll('header.top').length, boxes: document.querySelectorAll('form.sbox').length, cards, vw, hdrw: r(H).width, hl: r(H).left, hr: r(H).right,
              site: r(q('header.top .site')).top, counts: r(q('#counts')).top, box: r(q('header.top .sbox')).top, boxb: r(q('header.top .sbox')).bottom, hb: r(H).bottom, pos: getComputedStyle(H).position,
              hdrvar: document.documentElement.style.getPropertyValue('--hdr'), hh: H.offsetHeight, theme: r(q('#theme')), title: r(q('header.top .site a')), over: document.documentElement.scrollWidth - vw}; }"""
    LABELS = ["Your move", "On agent", "Queued for release", "Waiting", "Closed"]
    HINTW = """() => { const i = document.querySelector('header.top form.sbox input'), cs = getComputedStyle(i), c = document.createElement('canvas').getContext('2d');
      c.font = cs.fontStyle + ' ' + cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
      return {hint: i.placeholder, text: c.measureText(i.placeholder).width, cw: i.clientWidth, sw: i.scrollWidth, room: i.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)}; }"""
    for nm, f in HEADER_FILES.items():
        for scheme in ("light", "dark"):
            for w in (360, 390, 1280):
                tag = f"header of the {nm} page {w} {scheme}"
                ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme); pg = ctx.new_page(); pg.goto(f.as_uri()); pg.evaluate(OPEN); pg.wait_for_timeout(80)
                sw, vw, wide = pg.evaluate(WIDE)
                check(f"{tag}: the page is the screen's width with every fold open", sw == vw == w, (sw, vw, wide))
                d = pg.evaluate(HDR)
                labels = [re.sub(r"\s+", " ", c["label"]).strip() for c in d["cards"]]
                check(f"{tag}: one header with the title, five cards (Your move, On agent, Queued for release, Waiting, Closed) and one search box",
                      d["n"] == 1 and d["boxes"] == 1 and [x.replace(" for release", "") for x in labels] == [x.replace(" for release", "") for x in LABELS] and len(d["cards"]) == 5, (d["n"], d["boxes"], labels))
                check(f"{tag}: the list cards go to home's lists, Closed to /closed", [c["href"] for c in d["cards"]] == ["/#your-move", "/#agents-at-work", "/#queued-release", "/#waiting-list", "/closed"], [c["href"] for c in d["cards"]])
                check(f"{tag}: the cards are 60 px tall and inside the header, which is inside the screen", all(c["h"] == 60 and c["l"] >= -0.5 and c["r"] <= w + 0.5 for c in d["cards"]) and d["hl"] >= -0.5 and d["hr"] <= w + 0.5, d["cards"])
                check(f"{tag}: top to bottom the title, the cards, the search box; the title clear of the theme button",
                      d["site"] < d["counts"] < d["box"] and (d["title"]["right"] <= d["theme"]["left"] + 0.5 or d["title"]["bottom"] <= d["theme"]["top"] + 0.5 or d["title"]["left"] >= d["theme"]["right"] - 0.5), d)
                hh = pg.evaluate(HINTW)       # the search hint is whole: its text, in the box's own font, fits the room inside the box's padding (a placeholder is no element, so the box's scrollWidth alone does not show a cut), and the box does not scroll
                check(f"{tag}: the search hint ({hh['hint']!r}) fits inside its box ({hh['text']:.0f} px of {hh['room']:.0f}) and the box does not scroll sideways ({hh['sw']} of {hh['cw']}); the short line on a phone, the full line wide",
                      hh["text"] <= hh["room"] and hh["sw"] <= hh["cw"] and hh["hint"] == ("Search the board" if w <= 480 else "Search items, history, projects, sessions"), hh)
                check(f"{tag}: the header is sticky wide and not on a phone, and --hdr says how tall it is then", (d["pos"] == "sticky" and d["hdrvar"] == f"{d['hh']}px") if w >= 800 else (d["pos"] != "sticky" and d["hdrvar"] == "0px"), (d["pos"], d["hdrvar"], d["hh"]))
                if w == 1280 and scheme == "light" and nm in ("item", "Projects", "Closed", "project"):
                    room = pg.evaluate("document.documentElement.scrollHeight - innerHeight")      # a short page (Projects here) has nothing to scroll
                    if room > 100:
                        pg.evaluate("window.scrollTo(0, Math.min(400, document.documentElement.scrollHeight - innerHeight))"); pg.wait_for_timeout(50)
                        top = pg.evaluate("document.querySelector('header.top').getBoundingClientRect().top")
                        check(f"{tag}: scrolled down, the header stays at the top of the screen", abs(top) < 1 and pg.evaluate("scrollY") > 0, (top, pg.evaluate("scrollY")))
                        pg.evaluate("window.scrollTo(0, 0)")
                if HSHOTS and scheme == "light" and w in (390, 1280) and nm in ("item", "Projects"):
                    pg.screenshot(path=os.path.join(HSHOTS, f"header-{re.sub(chr(32), '-', nm.lower())}-{w}.png"), full_page=True)
                ctx.close()
    # ---- the buttons of the board's pages: one light look (ui/render.py _BTN_CSS) ----
    ui_runners.switch_enabled = lambda: True; ui_runners.switch_boxes = lambda: {"box-a", "box-b", "box-c"}      # the Disable / Enable forms are drawn (a pool-mode.sh is configured on the host); the page is handed its tokens
    _sw = {"box-a": {"ok": True, "mode": "on"}, "box-b": {"ok": True, "mode": "off", "since": time.time() - 600}, "box-c": {"ok": False, "why": "unread"}}
    _WQ = {"action": "/items/a1/watch", "token": "W", "flag": "watch", "watched": True, "why": "you asked"}
    _BA = {"action": "/items/a60/answer", "token": "T", "sent": ""}
    BTN_PAGES = {"home": b.html(), "item (decision)": b.item_html("a60", answer=_BA), "item (comment)": b.item_html("a1", answer={**_BA, "action": "/items/a1/answer"}, watch=_WQ),
                 "item (step)": b.item_html("a81", answer={**_BA, "action": "/items/a81/answer"}), "Closed": b.landed_html(), "Projects": b.projects_html(), "project": b.routing_html("projects/alpha"),
                 "Search": HEADER_PAGES["Search"], "runners": ui_runners.page_html(b, {**_six, "switch": _sw}, token=lambda b: "T")}
    BTN_FILES = {}
    for _nm, _html in BTN_PAGES.items():
        BTN_FILES[_nm] = OUT / ("btn-page-" + re.sub(r"\W+", "-", _nm).strip("-") + ".html"); BTN_FILES[_nm].write_text(_html, encoding="utf-8")
    check("the buttons: every page's hover rule is inside @media(hover:hover) and the .warn edge is kept on hover", all(re.search(r"@media\(hover:hover\)\{\.b:hover:not\(:disabled\)\{[^}]*\}\.b\.warn:hover:not\(:disabled\)\{border-color:var\(--warn\)\}\}", h) and not re.search(r"(?<!\{)\.b:hover:not\(:disabled\)", h) for h in BTN_PAGES.values()))
    check("the buttons: no page carries the Primary, Standard or Quiet button class or rule", all(not re.search(r"\.b\.(?:pri|std|qt|sm|xs)\b|class=\"b (?:pri|std|qt|sm|xs)\b", h) for h in BTN_PAGES.values()))
    BTNS = """() => {
      const cs = getComputedStyle, col = v => { const e = document.createElement('span'); e.style.color = v; document.body.appendChild(e); const c = cs(e).color; e.remove(); return c; };
      const alpha = c => { const m = c.match(/[\\d.]+/g).map(Number); return m.length > 3 ? m[3] : 1; };
      const panel = document.getElementById('panel'), pOpen = !!panel && cs(panel).visibility === 'visible', out = [];
      const lim = e => e.closest('li, section, form, .cmd, .draft, header, #panel, td, th, .conn');
      for (const el of document.querySelectorAll('.b')) {
        if (!el.getClientRects().length) continue;
        const s = cs(el), r = el.getBoundingClientRect(), box = lim(el), br = box ? box.getBoundingClientRect() : null;
        out.push({tag: el.tagName.toLowerCase(), id: el.id, cls: el.className, text: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 20), vis: s.visibility === 'visible', inPanel: !!el.closest('#panel'),
          w: r.width, h: r.height, left: r.left, right: r.right, bw: [s.borderTopWidth, s.borderRightWidth, s.borderBottomWidth, s.borderLeftWidth], bs: [s.borderTopStyle, s.borderRightStyle, s.borderBottomStyle, s.borderLeftStyle],
          bc: s.borderTopColor, bg: s.backgroundColor, bgAlpha: alpha(s.backgroundColor), color: s.color, fs: s.fontSize, fw: s.fontWeight, radius: [s.borderTopLeftRadius, s.borderTopRightRadius, s.borderBottomRightRadius, s.borderBottomLeftRadius],
          minh: s.minHeight, op: s.opacity, dis: el.disabled === true, ico: el.classList.contains('ico'), main: el.classList.contains('main'), on: el.classList.contains('on') || el.classList.contains('warn') || el.id === 'panel-open',
          sw: el.scrollWidth, cw: el.clientWidth, cardL: br ? br.left : null, cardR: br ? br.right : null, old: el.matches('.pri, .std, .qt, .sm, .xs')});
      }
      return {pOpen, vw: document.documentElement.clientWidth, sw: document.documentElement.scrollWidth, coarse: matchMedia('(pointer: coarse)').matches, line: col('var(--line)'), mut: col('var(--mut)'), fg: col('var(--fg)'), ibd: col('var(--ibd)'), accent: col('var(--acc)'), onAcc: col('var(--on-acc)'), btns: out};
    }"""
    seen_btn = {"n": 0, "pages": set(), "states": set(), "labels": set()}
    for nm, f in BTN_FILES.items():
        for scheme in ("light", "dark"):
            for w, touch in ((390, True), (1280, False)):
                ctx = (br.new_context(viewport={"width": w, "height": 844}, color_scheme=scheme, has_touch=True, is_mobile=True, device_scale_factor=2) if touch
                       else br.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme))
                pg = ctx.new_page(); pg.goto(f.as_uri()); pg.evaluate(OPEN); pg.wait_for_timeout(120)
                for step in (0, 1):
                    if step and pg.query_selector("#panel-open"): pg.click("#panel-open"); pg.mouse.move(w // 2, 400); pg.wait_for_timeout(450)
                    d = pg.evaluate(BTNS); st = "open" if d["pOpen"] else "closed"; tag = f"buttons {nm} {w} {scheme} panel {st}"
                    seen_btn["pages"].add(nm); seen_btn["states"].add((w, st)); seen_btn["labels"].update(b["text"] for b in d["btns"])
                    bt = d["btns"]; seen_btn["n"] += len(bt)
                    check(f"{tag}: the page has buttons and the pointer is {'coarse' if touch else 'fine'}", len(bt) >= 1 and d["coarse"] == touch, (len(bt), d["coarse"]))
                    bad = lambda pred: [(b["id"] or b["text"], b["cls"]) for b in bt if not pred(b)]
                    flat = lambda b: scheme == "dark" and b["dis"] and "on" not in b["cls"].split() and "busy" not in b["cls"].split()      # the dark theme draws a disabled button flat: --dis-bg fill, --dis-fg text, full opacity (the pressed and the busy ones keep their own look)
                    check(f"{tag}: every button has a 1 px solid outline on all four sides", not bad(lambda b: b["bw"] == ["1px"] * 4 and b["bs"] == ["solid"] * 4), bad(lambda b: b["bw"] == ["1px"] * 4 and b["bs"] == ["solid"] * 4))
                    check(f"{tag}: the outline is --ibd, 3:1 on the page (a main, pressed, warn or open-panel button keeps its own edge; a disabled one in the dark theme has the flat fill's edge)", not bad(lambda b: b["on"] or b["main"] or flat(b) or b["bc"] == d["ibd"]), bad(lambda b: b["on"] or b["main"] or flat(b) or b["bc"] == d["ibd"]))
                    check(f"{tag}: no fill at rest but the main button's (a pressed button has a light tint, a disabled one in the dark theme the flat grey)", not bad(lambda b: b["on"] or b["main"] or flat(b) or b["bgAlpha"] == 0), [(b["id"] or b["text"], b["bg"]) for b in bt if not (b["on"] or b["main"] or flat(b) or b["bgAlpha"] == 0)])
                    check(f"{tag}: the text is --fg at full strength, the main button's --on-acc on a solid --acc fill (a disabled button in the dark theme is the flat grey text)", not bad(lambda b: b["on"] or flat(b) or (b["color"] == d["onAcc"] and b["bg"] == d["accent"] if b["main"] else b["color"] == d["fg"])), [(b["id"] or b["text"], b["color"], b["bg"], d["fg"]) for b in bt if not (b["on"] or flat(b) or (b["color"] == d["onAcc"] and b["bg"] == d["accent"] if b["main"] else b["color"] == d["fg"]))])
                    check(f"{tag}: 13 px (the title bar's icon buttons draw a glyph, not text), weight 400 (600 on the main one), 8 px corners", not bad(lambda b: (b["ico"] or b["fs"] == "13px") and b["fw"] == ("600" if b["main"] else "400") and b["radius"] == ["8px"] * 4), bad(lambda b: (b["ico"] or b["fs"] == "13px") and b["fw"] == ("600" if b["main"] else "400") and b["radius"] == ["8px"] * 4))
                    floor = 44 if touch else 32
                    check(f"{tag}: at least {floor} px tall{'' if not touch else ' (the tap target)'}, an icon button {floor} px square", not bad(lambda b: b["h"] >= floor - 0.01 and (not b["ico"] or abs(b["w"] - floor) < 0.01 and abs(b["h"] - floor) < 0.01)), [(b["id"] or b["text"], round(b["h"], 1), round(b["w"], 1)) for b in bt if not (b["h"] >= floor - 0.01)])
                    check(f"{tag}: a disabled button is at 45% opacity, the main one at 50% (the pressed one, which is disabled to say \"this is the current choice\", stays whole); in the dark theme it is flat instead: grey fill rgb(42, 42, 44), grey text rgb(163, 162, 157), full opacity",
                          not bad(lambda b: not b["dis"] or (b["op"] == "1" and b["bg"] == "rgb(42, 42, 44)" and b["color"] == "rgb(163, 162, 157)" if flat(b) else b["op"] == ("0.5" if b["main"] else "0.45") or "on" in b["cls"].split())),
                          [(b["id"] or b["text"], b["op"], b["bg"], b["color"]) for b in bt if b["dis"] and not (b["op"] == "1" and b["bg"] == "rgb(42, 42, 44)" and b["color"] == "rgb(163, 162, 157)" if flat(b) else b["op"] == ("0.5" if b["main"] else "0.45") or "on" in b["cls"].split())])
                    check(f"{tag}: no button keeps the old Primary, Standard, Quiet or size class", not bad(lambda b: not b["old"]))
                    fits = lambda b: (not b["vis"]) or (b["inPanel"] and not d["pOpen"]) or (b["right"] <= d["vw"] + 0.5 and b["left"] >= -0.5 and b["sw"] <= b["cw"] + 1 and (b["ico"] or b["cardL"] is None or (b["left"] >= b["cardL"] - 0.5 and b["right"] <= b["cardR"] + 0.5)))
                    check(f"{tag}: no button runs past the screen, its card or its own box", not bad(fits), [(b["id"] or b["text"], round(b["left"]), round(b["right"]), b["cardL"] and round(b["cardL"]), b["cardR"] and round(b["cardR"])) for b in bt if not fits(b)])
                    check(f"{tag}: the page does not scroll sideways", d["sw"] <= d["vw"], (d["sw"], d["vw"]))
                    if step == 0 and not touch:         # hover: the outline firms up to --fg, a light fill appears (the main button: its fill moves toward --fg)
                        picks = pg.evaluate("""() => { const o = []; for (const el of document.querySelectorAll('.b')) { const s = getComputedStyle(el), r = el.getBoundingClientRect(), p = document.getElementById('panel'), inP = !!el.closest('#panel');
                          if (el.disabled || !r.width || s.visibility !== 'visible' || el.classList.contains('main') || el.classList.contains('on') || el.classList.contains('warn') || el.id === 'panel-open' || (inP && getComputedStyle(p).visibility !== 'visible')) continue;
                          el.setAttribute('data-hv', String(o.length)); o.push(el.id || el.textContent.trim().slice(0, 16)); if (o.length >= 4) break; } return o; }""")
                        for k, lab in enumerate(picks):
                            pg.hover(f'[data-hv="{k}"]'); pg.wait_for_timeout(260)
                            h = pg.evaluate(f"""() => {{ const el = document.querySelector('[data-hv="{k}"]'), s = getComputedStyle(el), m = s.backgroundColor.match(/[\\d.]+/g).map(Number); return {{color: s.color, bc: s.borderTopColor, a: m.length > 3 ? m[3] : 1, bw: s.borderTopWidth}}; }}""")
                            check(f"{tag}: hover on {lab!r}: text --fg, outline --fg (still 1 px), a light fill", h["color"] == d["fg"] and h["bc"] == d["fg"] and h["bw"] == "1px" and 0 < h["a"] < 0.2, (h, d["fg"]))
                            pg.mouse.move(1, 1); pg.wait_for_timeout(40)
                        mn = pg.query_selector(".b.main:not(:disabled)")
                        if mn and mn.is_visible():
                            before = pg.evaluate("() => getComputedStyle(document.querySelector('.b.main:not(:disabled)')).backgroundColor")
                            mn.hover(); pg.wait_for_timeout(260)
                            after = pg.evaluate("() => { const s = getComputedStyle(document.querySelector('.b.main:not(:disabled)')); return [s.backgroundColor, s.color]; }")
                            check(f"{tag}: hover on the main Send moves its solid fill off --acc and keeps the --on-acc label", before == d["accent"] and after[0] != d["accent"] and after[1] == d["onAcc"], (before, after, d["accent"]))
                            pg.mouse.move(1, 1); pg.wait_for_timeout(40)
                    if step == 0 and not touch and nm == "home":         # a .warn edge (Reload in the banner) is still the warn colour under the pointer
                        pg.evaluate("() => { const c = document.getElementById('conn'); c.hidden = false; c.querySelectorAll('span').forEach(s => s.style.display = 'inline'); }")
                        pg.hover("#conn-reload"); pg.wait_for_timeout(260)
                        wc = pg.evaluate("() => { const e = document.createElement('span'); e.style.color = 'var(--warn)'; document.body.appendChild(e); const w = getComputedStyle(e).color; e.remove(); const b = getComputedStyle(document.getElementById('conn-reload')); return [b.borderTopColor, w, b.color]; }")
                        check(f"{tag}: hover on Reload keeps its warn edge (text --fg)", wc[0] == wc[1] and wc[2] == d["fg"], (wc, d["fg"]))
                        pg.mouse.move(1, 1)
                    if step == 0 and touch:         # no hover on a touch screen: a tap leaves no fill, no firmer text or outline behind it
                        check(f"{tag}: a touch screen cannot hover", pg.evaluate("matchMedia('(hover: hover)').matches") is False)
                        if pg.query_selector("button.b.copy"):
                            pg.tap("button.b.copy"); pg.wait_for_timeout(300)
                            tp = pg.evaluate("""() => { const el = document.querySelector('button.b.copy'), s = getComputedStyle(el), m = s.backgroundColor.match(/[\\d.]+/g).map(Number); return {a: m.length > 3 ? m[3] : 1, color: s.color, bc: s.borderTopColor}; }""")
                            check(f"{tag}: after a tap on Copy no hover fill is left: no fill, text --fg, outline --ibd", tp["a"] == 0 and tp["color"] == d["fg"] and tp["bc"] == d["ibd"], (tp, d["fg"], d["ibd"]))
                    if HSHOTS and step == 0 and scheme == "light" and nm in ("item (decision)", "runners"):
                        pg.screenshot(path=os.path.join(HSHOTS, f"buttons-{re.sub(chr(32), '-', nm)}-{w}.png"), full_page=True)
                ctx.close()
    check("the buttons: every kind was measured (Audit now is a text link now, checked in the panel alignment block): Send, Copy, Clear, Clear all, Watch, Mute, Default, Disable, Enable, the title bar's icon buttons, in the panel open and closed at both widths",
          {"Send", "Copy", "Clear", "Clear all", "Watch", "Mute", "Default", "Disable", "Enable", "Theme: system", "Search"} <= seen_btn["labels"]
          and {(390, "open"), (390, "closed"), (1280, "open"), (1280, "closed")} <= seen_btn["states"] and len(seen_btn["pages"]) == len(BTN_FILES), (sorted(seen_btn["labels"]), sorted(seen_btn["states"])))
    # ---- the color tool (shared/colortool.js, stackshot's settings in ui/colortool.py): on every page a Colors button (a bare two-color circle split by a diagonal line, no text, no frame) at the very bottom of the side panel, on the dark theme only. At 360, 390 and 412 px (touch)
    # and 800, 1100 and 1440 px it overlaps no other fixed control (the reload and Back to top buttons, the title bar's theme and panel buttons); the panel it opens is fixed in the page body, opens upward from the button, lies above the reload and Back to top
    # buttons, is not clipped by the side panel, stays inside the screen with its own scroll (at 360 px too) and holds the 14 fields (a color input and a hex box each) in boxes whose headings are the side panel's section style in the link color with the fields indented,
    # behind a Fields fold that starts closed, is remembered per browser and grows the panel upward; the presets and the saved combinations sit together in one box at the bottom beside the button (Save on one line), the preview, and Reset,
    # every control inside the panel's width (44 px tall on a touch screen) and Reset reachable by scrolling it; Escape closes it and returns the focus.
    # Then, on the board: a hex edit applies at once, a color input applies, a short hex expands, a bad one is named, a refused value shows "Not applied" and changes nothing, every preset applies (Send, disabled buttons, small labels),
    # the circle follows the look, a reload keeps the look, Reset clears it, nothing but the saved list's own address is ever asked of the network. Then against a routed origin that serves the page and the saved-combinations routes from the real store
    # (colorcombos): the list is read when the panel opens, a save, an apply, a replace under the same name and a delete round-trip, an empty name is not sent, and a refusal (403, 409, 400 with the route's text, 503, offline) shows its
    # message and never loses the applied look. The light theme draws no button and applies nothing; storage that is off says so; a page without scripts has no button; an idle page's Send and disabled buttons compute as on a page without the tool.
    # Last, the same file in a page of another app (other settings: its own key, mount and property names, a function for the shipped values, onApply, isDark, no saved list, no preview, the "warn" gate): applyStored alone draws nothing,
    # init draws the button in that app's mount and the panel in the body, Reset and the original orange theme take off every property including onApply's, a light page draws nothing, "warn" lets a white page stand with notes and keeps it across a reload, and
    # remount moves the button into a new mount while the open panel stays open.
    import urllib.parse
    from stackshot.web import colorcombos as _cc
    import _colors as _C
    CT_FILES = {"board": PAGES["board"], **HEADER_FILES}
    CT_RECT = "(s) => { const e = document.querySelector(s); if (!e) return null; const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden') return null; const r = e.getBoundingClientRect(); return r.width && r.height ? {l: r.left, t: r.top, r: r.right, b: r.bottom} : null; }"
    CT_ALL = "(sel) => [...document.querySelectorAll(sel)].map(e => { const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden') return null; const r = e.getBoundingClientRect(); return r.width && r.height ? {l: r.left, t: r.top, r: r.right, b: r.bottom} : null; }).filter(Boolean)"
    CT_HIT = lambda a, c: bool(a and c and a["l"] < c["r"] - 0.5 and c["l"] < a["r"] - 0.5 and a["t"] < c["b"] - 0.5 and c["t"] < a["b"] - 0.5)
    CT_FIXED = ["#reload", "#totop", "#theme", "#panel-open", "#panel-edge"]
    CT_SHOWN = "() => { const b = document.getElementById('ct-btn'); if (!b) return false; const r = b.getBoundingClientRect(), cs = getComputedStyle(b); return cs.display !== 'none' && r.width > 0 && r.right > 0 && r.left < innerWidth - 4 && r.top < innerHeight; }"
    def ct_show(pg):
        """The button lives in the side panel: where the panel is shut (a phone, or the item page's wide default) open it with the title bar's button, as a person does."""
        for _ in range(2):
            if pg.evaluate(CT_SHOWN): return True
            pg.click("#panel-open"); pg.wait_for_timeout(550)
        return pg.evaluate(CT_SHOWN)
    CT_STATE = """() => { const root = document.documentElement;
      return {bg: getComputedStyle(document.body).backgroundColor, cls: [...root.classList].filter(c => c.startsWith('ct-')).sort(), key: localStorage.getItem('stackshot-color-trial'),
              inline: [...root.style].filter(p => ['--bg','--card','--line','--ifill','--fg','--mut','--ibd','--acc','--call','--t-you','--selbg','--t-you-bg','--orange-text','--orange-solid','--on-solid','--lab-bg','--lab-fg','--lab-bd','--dis-bg','--dis-fg'].includes(p)).sort().join(' ')}; }"""
    CT_PROPS = "(e) => { const s = getComputedStyle(e); return [s.backgroundColor, s.color, s.borderTopColor, s.opacity, s.fontWeight]; }"
    CT_IDLE = """() => { const pick = sel => [...document.querySelectorAll(sel)].find(x => !x.closest('#ct-pop')), out = {};
      for (const [k, sel] of [['send', '.b.main:not(:disabled)'], ['idle', '.b.main:disabled'], ['off', '.b:not(.main):disabled']]) { const e = pick(sel);
        if (e) { const s = getComputedStyle(e); out[k] = [s.backgroundColor, s.color, s.borderTopColor, s.opacity, s.fontWeight, s.borderTopWidth]; } }
      return out; }"""
    CT_SIZES = "() => [...document.querySelectorAll('#ct-pop .ct-pick, #ct-pop .ct-hex, #ct-pop .ct-preset, #ct-pop #ct-save, #ct-pop #ct-reset')].map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; })"
    CT_INSIDE = "() => { const p = document.getElementById('ct-pop').getBoundingClientRect(); return [...document.querySelectorAll('#ct-pop .ct-row, #ct-pop .ct-preset, #ct-pop .ct-save, #ct-pop .ct-prev, #ct-pop #ct-reset')].filter(e => { const r = e.getBoundingClientRect(); return r.right > p.right + 0.5 || r.left < p.left - 0.5; }).length; }"
    CT_SET = "([id, v]) => { const i = document.getElementById(id); i.value = v; i.dispatchEvent(new Event('input', {bubbles: true})); i.dispatchEvent(new Event('change', {bubbles: true})); }"
    CT_Z = "(s) => { const e = document.querySelector(s); if (!e) return null; const z = parseInt(getComputedStyle(e).zIndex, 10); return Number.isNaN(z) ? 0 : z; }"
    def ct_fields(pg, on=True):
        """The panel's Fields fold starts closed: open it (or shut it) with its button, as a person does, before using a field."""
        if (pg.get_attribute("#ct-fold", "aria-expanded") == "true") != on:
            pg.click("#ct-fold"); pg.wait_for_timeout(80)
    CT_FOLDED = """() => { const q = s => document.querySelector(s), r = e => { const b = e.getBoundingClientRect(); return {l: b.left, t: b.top, r: b.right, b: b.bottom}; };
      const sv = q('#ct-save'), nm = q('#ct-name'), rg = document.createRange(); rg.selectNodeContents(sv);
      const lines = new Set([...rg.getClientRects()].map(x => Math.round(x.top))).size, sb = r(sv), nb = r(nm), pop = q('#ct-pop');
      return {fold: q('#ct-fold').getAttribute('aria-expanded'), controls: q('#ct-fold').getAttribute('aria-controls'), fieldsShown: getComputedStyle(q('#ct-fields')).display !== 'none',
              rowsShown: [...document.querySelectorAll('#ct-pop .ct-row')].filter(e => e.getClientRects().length).length, saveText: sv.textContent, saveLines: lines, saveWs: getComputedStyle(sv).whiteSpace, saveOverflow: sv.scrollWidth - sv.clientWidth,
              sameRow: sb.t < nb.b && nb.t < sb.b, saveIn: sb.r <= r(pop).r + 0.5, dock: r(q('#ct-dock')), presets: r(q('#ct-g-presets')), saved: r(q('#ct-g-saved')), lastPreset: r([...document.querySelectorAll('#ct-pop .ct-preset')].pop()),
              inDock: !!q('#ct-dock #ct-g-presets') && !!q('#ct-dock #ct-g-saved') && !!q('#ct-dock .ct-presets') && !!q('#ct-dock #ct-save'), foldBtn: r(q('#ct-fold')), reset: r(q('#ct-reset')), pop: r(pop), sh: pop.scrollHeight, ch: pop.clientHeight, sw: pop.scrollWidth, cw: pop.clientWidth}; }"""
    CT_HEADS = """() => { const probe = document.createElement('span'); probe.style.color = 'var(--fg)'; document.body.appendChild(probe); const fg = getComputedStyle(probe).color;
      probe.style.color = getComputedStyle(document.getElementById('ct-pop')).getPropertyValue('--ct-link').trim(); const link = getComputedStyle(probe).color; probe.remove();
      const shift = [...document.querySelectorAll('#ct-fields .ct-box')].filter(b => b.querySelector('.ct-row')).map(b => b.querySelector('.ct-row').getBoundingClientRect().left - b.querySelector('.ct-gh').getBoundingClientRect().left);
      const h2 = document.querySelector('#panel section h2'), ref = h2 ? (s => [s.fontSize, s.fontWeight, s.letterSpacing, s.textTransform, s.color])(getComputedStyle(h2)) : null;
      return {fg, link, shift, ref, heads: [...document.querySelectorAll('#ct-pop .ct-gh')].map(e => { const s = getComputedStyle(e); return [e.textContent.trim().split(' ').slice(0, 2).join(' '), s.fontSize, s.fontWeight, s.letterSpacing, s.textTransform, s.color, !!e.closest('.ct-box')]; })}; }"""
    CT_DOT = """() => { const btn = document.getElementById('ct-btn'), dot = btn.querySelector('.ct-dot'), probe = document.createElement('span'); document.body.appendChild(probe);
      const rgb = c => { probe.style.color = c; return getComputedStyle(probe).color; }, root = document.documentElement;
      const solid = root.style.getPropertyValue('--orange-solid') ? 'var(--orange-solid)' : 'var(--orange)';
      const out = {a: rgb(btn.style.getPropertyValue('--ct-a')), b: rgb(btn.style.getPropertyValue('--ct-b')), bg: rgb('var(--bg)'), solid: rgb(solid), image: getComputedStyle(dot).backgroundImage, round: getComputedStyle(dot).borderRadius, label: btn.textContent.trim(), nodes: btn.childNodes.length, text: [...btn.childNodes].filter(n => n.nodeType === 3).length, aria: btn.getAttribute('aria-label'), frame: [getComputedStyle(btn).borderTopWidth, getComputedStyle(btn).backgroundColor]};
      probe.remove(); return out; }"""
    ct_seen = {"pages": set()}
    for nm, f in CT_FILES.items():
        for w, h, touch in ((360, 740, True), (390, 800, True), (412, 800, True), (800, 700, False), (1100, 800, False), (1440, 900, False)):
            ctx = br.new_context(viewport={"width": w, "height": h}, color_scheme="dark", has_touch=touch); pg = ctx.new_page(); pg.goto(f.as_uri()); pg.wait_for_timeout(150)
            tag = f"colors {nm} {w}{' touch' if touch else ''}"
            shown = ct_show(pg)
            btn = pg.evaluate(CT_RECT, "#ct-btn"); pan = pg.evaluate(CT_RECT, "#panel")
            check(f"{tag}: one Colors button, drawn by the script in the side panel's mount (#panel-colors) once the panel is shown, inside the screen, collapsed (aria-expanded false) with its panel shut",
                  shown and pg.locator("#ct-btn").count() == 1 and pg.evaluate("document.getElementById('ct-btn').closest('#panel-colors') !== null") and btn is not None and pan is not None and btn["l"] >= pan["l"] - 0.5 and btn["r"] <= pan["r"] + 0.5
                  and btn["l"] >= 0 and btn["r"] <= w and btn["b"] <= h and pg.get_attribute("#ct-btn", "aria-expanded") == "false" and pg.get_attribute("#ct-btn", "aria-controls") == "ct-pop" and pg.evaluate(CT_RECT, "#ct-pop") is None, (btn, pan))
            check(f"{tag}: the button sits at the very bottom of the side panel (its bottom within 24 px of the panel's, whatever the panel's height) and at its left", btn is not None and pan is not None and 0 <= pan["b"] - btn["b"] <= 24 and btn["l"] - pan["l"] <= 24, (btn, pan))
            if touch: check(f"{tag}: a coarse pointer gets a 44 px button", btn and btn["b"] - btn["t"] >= 43.5, btn)
            hit = [s for s in CT_FIXED if CT_HIT(btn, pg.evaluate(CT_RECT, s))]
            check(f"{tag}: the button overlaps none of the reload, Back to top, theme and panel buttons", not hit, hit)
            dot = pg.evaluate(CT_DOT)
            check(f"{tag}: the button is a bare round two-color mark split by a diagonal line, with no text and no frame, named Colors by its aria-label: the upper left half the live page color, the lower right half the live solid fill (rgb {dot['bg']} and {dot['solid']})",
                  dot["label"] == "" and dot["text"] == 0 and dot["nodes"] == 1 and dot["aria"] == "Colors" and dot["frame"][0] == "0px" and dot["frame"][1] == "rgba(0, 0, 0, 0)" and "135deg" in dot["image"] and "90deg" not in dot["image"] and dot["a"] == dot["bg"] and dot["b"] == dot["solid"] and "linear-gradient" in dot["image"] and dot["bg"] in dot["image"] and dot["solid"] in dot["image"] and dot["round"] in ("50%", "9px"), dot)
            pg.click("#ct-btn"); pg.wait_for_timeout(120)
            pop = pg.evaluate(CT_RECT, "#ct-pop"); btn = pg.evaluate(CT_RECT, "#ct-btn"); pan = pg.evaluate(CT_RECT, "#panel")
            check(f"{tag}: a click opens the panel (aria-expanded true) inside the screen, upward from the button (its bottom no lower than the button's top)", pop is not None and pg.get_attribute("#ct-btn", "aria-expanded") == "true"
                  and pop["l"] >= 0 and pop["t"] >= 0 and pop["r"] <= w + 0.5 and pop["b"] <= btn["t"] + 0.5, (pop, btn))
            fd = pg.evaluate(CT_FOLDED)
            check(f"{tag}: the Fields fold is closed at first (the button says so, aria-controls names the fields, none of the 14 rows is drawn) and the panel needs no sideways scroll", fd["fold"] == "false" and fd["controls"] == "ct-fields" and not fd["fieldsShown"] and fd["rowsShown"] == 0 and fd["sw"] <= fd["cw"] + 1 and pg.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"), fd)
            check(f"{tag}: the presets and the saved combinations sit together in one box at the bottom (Presets above Saved combinations, the gap between them 64 px or less), below the fold button, with Reset after them", fd["inDock"] and fd["presets"]["t"] < fd["saved"]["t"] and 0 <= fd["saved"]["t"] - fd["lastPreset"]["b"] <= 64
                  and fd["foldBtn"]["b"] <= fd["dock"]["t"] + 0.5 and fd["dock"]["b"] <= fd["reset"]["t"] + 0.5 and fd["dock"]["t"] >= fd["pop"]["t"] - 0.5 and fd["reset"]["b"] <= fd["pop"]["b"] + 0.5, fd)
            check(f"{tag}: Save is that one word, on one line (nowrap), beside the name box and inside the panel", fd["saveText"] == "Save" and fd["saveLines"] == 1 and fd["saveWs"] == "nowrap" and fd["saveOverflow"] <= 1 and fd["sameRow"] and fd["saveIn"], fd)
            pop_f, fold_f = pg.evaluate(CT_RECT, "#ct-pop"), pg.evaluate(CT_RECT, "#ct-fold")
            pg.click("#ct-fold"); pg.wait_for_timeout(120)
            pop_u, fold_u = pg.evaluate(CT_RECT, "#ct-pop"), pg.evaluate(CT_RECT, "#ct-fold"); btn = pg.evaluate(CT_RECT, "#ct-btn")
            check(f"{tag}: unfolding the fields grows the panel upward, away from the button: its top moves up, its bottom and the fold button stay where they were, and it stays inside the screen", pg.get_attribute("#ct-fold", "aria-expanded") == "true" and pop_u is not None
                  and (pop_u["t"] < pop_f["t"] - 20 or pop_u["t"] <= 9) and abs(pop_u["b"] - pop_f["b"]) <= 1 and abs(fold_u["b"] - fold_f["b"]) <= 1.5 and pop_u["t"] >= -0.5 and pop_u["b"] <= btn["t"] + 0.5 and pg.evaluate(CT_RECT, "#ct-fields") is not None and pg.evaluate(CT_INSIDE) == 0, (pop_f, pop_u, fold_f, fold_u))
            check(f"{tag}: the Preview box is outside the fold (not inside #ct-fields), under the Fields button and above the presets, and is drawn whether the fields are open or folded", pg.evaluate("() => { const pv = document.getElementById('ct-g-preview').closest('.ct-box'), fl = document.getElementById('ct-fields'), fb = document.getElementById('ct-fold'), dk = document.getElementById('ct-dock'); return !fl.contains(pv) && !!(fb.compareDocumentPosition(pv) & Node.DOCUMENT_POSITION_FOLLOWING) && !!(pv.compareDocumentPosition(dk) & Node.DOCUMENT_POSITION_FOLLOWING); }") and pg.evaluate(CT_RECT, "#ct-g-preview") is not None, pg.evaluate(CT_RECT, "#ct-g-preview"))
            check(f"{tag}: the fold is remembered in this browser under the tool's own key plus ':fields' (the look's key is untouched)", pg.evaluate("localStorage.getItem('stackshot-color-trial:fields')") == "1" and pg.evaluate("localStorage.getItem('stackshot-color-trial')") is None)
            geo = pg.evaluate("""() => { const p = document.getElementById('ct-pop'), s = getComputedStyle(p); return {pos: s.position, parent: p.parentElement.tagName, z: parseInt(s.zIndex, 10) || 0, oy: s.overflowY, sh: p.scrollHeight, ch: p.clientHeight}; }""")
            zs = [pg.evaluate(CT_Z, s) for s in ("#reload", "#totop") if pg.evaluate(CT_RECT, s) is not None]
            check(f"{tag}: the panel is fixed in the page body (not inside the side panel), above the reload and Back to top buttons (z-index over theirs) and above the side panel", geo["pos"] == "fixed" and geo["parent"] == "BODY" and zs and all(geo["z"] > z for z in zs) and geo["z"] > (pg.evaluate(CT_Z, "#panel") or 0), (geo, zs))
            if pop is not None and pan is not None:
                over = [s for s in ("#reload", "#totop") if CT_HIT(pop, pg.evaluate(CT_RECT, s))]
                at = pg.evaluate("""(pt) => { const e = document.elementFromPoint(pt[0], pt[1]); return !!(e && e.closest('#ct-pop')); }""", [pop["l"] + 12, pop["t"] + 12])
                top_in = [s for s in over if pg.evaluate("""(s) => { const r = document.querySelector(s).getBoundingClientRect(), p = document.getElementById('ct-pop').getBoundingClientRect(), x = (Math.max(r.left, p.left) + Math.min(r.right, p.right)) / 2, y = (Math.max(r.top, p.top) + Math.min(r.bottom, p.bottom)) / 2; const e = document.elementFromPoint(x, y); return !!(e && e.closest('#ct-pop')); }""", s)]
                check(f"{tag}: the panel is not clipped by the side panel: it is wider than the side panel, its corner is hit by itself, and where it covers the reload or Back to top button it is on top of it", pop["r"] - pop["l"] > pan["r"] - pan["l"] + 20 and at and top_in == over, (pop, pan, over, top_in, at))
            check(f"{tag}: the panel is at most the screen tall (16 px short of it) and scrolls inside itself (overflow auto, more content than fits)", pop is not None and pop["b"] - pop["t"] <= h - 16 + 0.5 and geo["oy"] == "auto" and geo["sh"] > geo["ch"], (pop, geo))
            heads = pg.evaluate(CT_HEADS)
            check(f"{tag}: six boxes (Surfaces, Text, Buttons, Small labels, Preview, and one for Presets with Saved combinations), each heading in the side panel's section size (uppercase, 12 px, weight 600, its letter spacing) but in the link color, not the body text color, and the fields indented under theirs",
                  [x[0].split(" ")[0] for x in heads["heads"]] == ["Surfaces", "Text", "Buttons", "Small", "Preview", "Presets", "Saved"] and all(x[1] == "12px" and x[2] == "600" and x[4] == "uppercase" and x[5] == heads["link"] and x[6] for x in heads["heads"]) and heads["link"] != heads["fg"]
                  and (heads["ref"] is None or all([x[1], x[2], x[3], x[4]] == heads["ref"][:4] for x in heads["heads"])) and pg.locator("#ct-pop .ct-box").count() == 6 and len(heads["shift"]) == 4 and all(d >= 12 for d in heads["shift"]), heads)
            cnt = pg.evaluate("() => [document.querySelectorAll('#ct-pop .ct-row').length, document.querySelectorAll('#ct-pop .ct-pick').length, document.querySelectorAll('#ct-pop .ct-hex').length, document.querySelectorAll('#ct-pop .ct-preset').length]")
            check(f"{tag}: the panel has 14 field rows (14 color inputs, 14 hex boxes and the name box), 5 presets, the preview, Saved combinations and Reset",
                  cnt == [14, 14, 15, 5] and pg.locator("#ct-pop .ct-prev").count() == 1 and pg.locator("#ct-saved #ct-save").count() == 1 and pg.locator("#ct-reset").count() == 1, cnt)
            sizes = pg.evaluate(CT_SIZES)
            check(f"{tag}: every color input, hex box, preset, Save and Reset is drawn" + (", each 44 px or taller on a coarse pointer" if touch else ""), len(sizes) == 14 + 15 + 5 + 2 and all(a > 0 and b > 0 for a, b in sizes) and (not touch or all(b >= 43.5 for a, b in sizes)), sizes)
            fs = pg.evaluate("() => [...document.querySelectorAll('#ct-pop input[type=text]')].map(e => parseFloat(getComputedStyle(e).fontSize))")
            check(f"{tag}: every text input of the panel (the 14 hex boxes and the Name box) computes to a font of 16 px or more, so a phone does not zoom the page when one takes focus", len(fs) == 15 and min(fs) >= 16, fs)
            check(f"{tag}: every row, preset, the preview, the save line and Reset sit inside the panel's width; the panel and the page do not scroll sideways",
                  pg.evaluate(CT_INSIDE) == 0 and pg.evaluate("() => { const p = document.getElementById('ct-pop'); return [p.scrollWidth <= p.clientWidth + 1, document.documentElement.scrollWidth <= document.documentElement.clientWidth]; }") == [True, True], pg.evaluate(CT_INSIDE))
            pg.evaluate("() => { const p = document.getElementById('ct-pop'); p.scrollTop = p.scrollHeight; }"); pg.wait_for_timeout(60)
            rs, pp = pg.evaluate(CT_RECT, "#ct-reset"), pg.evaluate(CT_RECT, "#ct-pop")
            check(f"{tag}: scrolled to its end, the panel shows Reset whole inside it (a tall panel scrolls instead of running off the screen)", rs is not None and rs["t"] >= pp["t"] - 0.5 and rs["b"] <= pp["b"] + 0.5, (rs, pp))
            pg.keyboard.press("Escape"); pg.wait_for_timeout(50)
            check(f"{tag}: Escape closes the panel and the focus goes back to the button", pg.evaluate(CT_RECT, "#ct-pop") is None and pg.get_attribute("#ct-btn", "aria-expanded") == "false"
                  and pg.evaluate("document.activeElement.id") == "ct-btn", pg.evaluate("document.activeElement.id"))
            pg.click("#ct-btn"); pg.wait_for_timeout(80); pg.mouse.click(2, 2) if w >= 800 else pg.touchscreen.tap(2, 2); pg.wait_for_timeout(120)
            check(f"{tag}: a click outside the button and the panel closes the panel", pg.evaluate(CT_RECT, "#ct-pop") is None and pg.get_attribute("#ct-btn", "aria-expanded") == "false", pg.evaluate(CT_RECT, "#ct-pop"))
            ct_seen["pages"].add(nm); ctx.close()
    check("the Colors button was measured on every page type (the board, the item pages, the project page, Projects, Closed, Search, Runners)", ct_seen["pages"] == set(CT_FILES) and len(CT_FILES) >= 8, sorted(ct_seen["pages"]))
    # the keyboard, hex and color inputs, the presets, a reload, nothing sent, Reset
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark"); pg = ctx.new_page(); sent = []
    pg.on("request", lambda rq: sent.append(rq.url) if not rq.url.startswith(("file:", "data:")) and "pretendard" not in rq.url else None)   # the page's own web font from its CDN is not the tool's
    pg.goto(CT_FILES["board"].as_uri()); pg.wait_for_timeout(150); ct_show(pg)
    has_before_init = None
    pg.focus("#ct-btn"); pg.keyboard.press("Shift+Tab"); pg.keyboard.press("Tab")
    ring = pg.evaluate("() => { const s = getComputedStyle(document.activeElement); return [document.activeElement.id, s.outlineStyle, parseFloat(s.outlineWidth)]; }")
    check("colors: the keyboard reaches the button and its focus ring shows (2 px outline)", ring[0] == "ct-btn" and ring[1] != "none" and ring[2] >= 2, ring)
    pg.keyboard.press("Enter"); pg.wait_for_timeout(80)
    check("colors: Enter opens the panel, which starts on the shipped look with every field shipped: the original orange theme is pressed (Sky differs) and the line names it", pg.evaluate(CT_RECT, "#ct-pop") is not None and pg.get_attribute("#ct-btn", "aria-expanded") == "true"
          and pg.inner_text("#ct-cur") == "Now: Original orange theme" and pg.input_value("#ct-h-bg") == "#161617" and pg.input_value("#ct-p-card") == "#1f1f21" and pg.get_attribute('.ct-preset[data-p=live]', "aria-pressed") == "true" and pg.get_attribute('.ct-preset[data-p=sky]', "aria-pressed") == "false"
          and pg.input_value("#ct-h-solid") == "#f0a06a" and pg.input_value("#ct-h-labbg") == "#3a2619" and pg.input_value("#ct-h-labfg") == "#f0a06a" and pg.input_value("#ct-h-onsolid") == "#1f1f21" and pg.input_value("#ct-h-disbg") == "#2a2a2c", pg.inner_text("#ct-cur"))
    fd = pg.evaluate(CT_FOLDED)
    check("colors: Enter opens the panel with the fields folded: the Fields button says closed, the presets and the saved box are in view", fd["fold"] == "false" and not fd["fieldsShown"] and pg.evaluate(CT_RECT, "#ct-g-presets") is not None and pg.evaluate(CT_RECT, "#ct-g-saved") is not None, fd)
    ct_fields(pg)
    pg.click("#ct-l-card")
    check("colors: a row's name is a real label: a click on it puts the focus in that row's hex box; the row's note and the Now line are polite status regions", pg.evaluate("document.activeElement.id") == "ct-h-card"
          and pg.evaluate("() => [...document.querySelectorAll('#ct-pop .ct-note, #ct-cur')].every(e => e.getAttribute('role') === 'status' && e.getAttribute('aria-live') === 'polite')"))
    pg.fill("#ct-h-bg", "#1f1f21"); pg.wait_for_timeout(60); st = pg.evaluate(CT_STATE)
    check("colors: typing six hex digits in a field applies at once (no Enter, no button): the page paints the background, one key stored with that field only, the cards and lines follow it",
          st["bg"] == "rgb(31, 31, 33)" and json.loads(st["key"]) == {"bg": "#1f1f21"} and "--card" in st["inline"].split() and "--line" in st["inline"].split() and pg.inner_text("#ct-s-card") == "follows the others"
          and pg.inner_text("#ct-s-bg") == "" and pg.inner_text("#ct-cur") == "Now: Custom", (st, pg.inner_text("#ct-cur")))
    check("colors: a set page background also moves the small label fill and the disabled pair (they are worked out on it), so those rows say 'follows the others' while the label text and outline stay 'shipped'",
          [pg.inner_text("#ct-s-" + k) for k in ("labbg", "disbg", "disfg", "labfg", "labbd")] == ["follows the others", "follows the others", "follows the others", "shipped", "shipped"], [pg.inner_text("#ct-s-" + k) for k in ("labbg", "disbg", "disfg", "labfg", "labbd")])
    dot2 = pg.evaluate(CT_DOT)
    check("colors: the circle follows the look at once: its left half is the new page color", dot2["a"] == "rgb(31, 31, 33)" and dot2["a"] == dot2["bg"] and dot2["b"] == dot2["solid"], dot2)
    pg.fill("#ct-p-link", "#ffa057"); pg.wait_for_timeout(60); st = pg.evaluate(CT_STATE)
    check("colors: a native color input applies at once: the text orange is set, solid fills are re-pointed (ct-on), the hex box shows the value", "--orange-text" in st["inline"].split() and "ct-on" in st["cls"]
          and json.loads(st["key"]) == {"bg": "#1f1f21", "link": "#ffa057"} and pg.input_value("#ct-h-link") == "#ffa057", st)
    pg.fill("#ct-h-solid", "#fa5"); pg.wait_for_timeout(40)
    check("colors: three hex digits are not applied while typing", "solid" not in json.loads(pg.evaluate(CT_STATE)["key"]))
    pg.press("#ct-h-solid", "Tab"); pg.wait_for_timeout(60); st = pg.evaluate(CT_STATE)
    check("colors: leaving the box expands three digits to six (#fa5 to #ffaa55) and applies them; the label on the fill follows by itself", json.loads(st["key"]).get("solid") == "#ffaa55" and pg.input_value("#ct-h-solid") == "#ffaa55"
          and "--on-solid" in st["inline"].split(), st)
    dot3 = pg.evaluate(CT_DOT)
    check("colors: the circle's right half follows the solid fill (rgb 255, 170, 85)", dot3["b"] == "rgb(255, 170, 85)" and dot3["b"] == dot3["solid"], dot3)
    pg.fill("#ct-h-solid", "zzz"); pg.press("#ct-h-solid", "Tab"); pg.wait_for_timeout(60)
    check("colors: a value that is not hex says how to write it and keeps the last one", pg.inner_text("#ct-n-solid") == "Use six digits like #f0a06a." and pg.input_value("#ct-h-solid") == "#ffaa55" and json.loads(pg.evaluate(CT_STATE)["key"])["solid"] == "#ffaa55", pg.inner_text("#ct-n-solid"))
    before = pg.evaluate(CT_STATE); pg.fill("#ct-h-bg", "#ffffff"); pg.wait_for_timeout(60); after = pg.evaluate(CT_STATE)
    check("colors: a background too light for the body text is refused: the note starts 'Not applied' and names the pair, the page and the stored look stay as they were", after == before and pg.inner_text("#ct-n-bg").startswith("Not applied: body text would read")
          and "11:1 needed" in pg.inner_text("#ct-n-bg"), (pg.inner_text("#ct-n-bg"), before == after))
    pg.fill("#ct-h-bg", "#202022"); pg.wait_for_timeout(60)
    check("colors: a background that passes (#202022) is applied after a refusal and the note goes away", pg.evaluate(CT_STATE)["bg"] == "rgb(32, 32, 34)" and pg.inner_text("#ct-n-bg") == "", pg.inner_text("#ct-n-bg"))
    keep = pg.evaluate(CT_STATE)
    pg.reload(); pg.wait_for_timeout(150); st2 = pg.evaluate(CT_STATE)
    check("colors: a reload keeps the look (applied from the head, before the first paint)", st2 == keep, (st2, keep))
    ct_show(pg); pg.click("#ct-btn")
    check("colors: reopened after a reload, the fields show the stored look", pg.input_value("#ct-h-bg") == "#202022" and pg.input_value("#ct-h-link") == "#ffa057" and pg.input_value("#ct-h-solid") == "#ffaa55" and pg.inner_text("#ct-cur") == "Now: Custom")
    check("colors: the Fields fold stays open after a reload (this browser remembers it) and the open panel is scrolled to its end, the fold button in view",
          pg.get_attribute("#ct-fold", "aria-expanded") == "true" and pg.evaluate(CT_RECT, "#ct-fields") is not None and pg.evaluate(CT_RECT, "#ct-fold") is not None and pg.evaluate("() => { const p = document.getElementById('ct-pop'); return p.scrollTop + p.clientHeight >= p.scrollHeight - 1; }"))
    ct_fields(pg, False); fd = pg.evaluate(CT_FOLDED)
    check("colors: folding the fields hides the 14 rows and forgets the key (the default is folded); the look is unchanged", fd["fold"] == "false" and not fd["fieldsShown"] and fd["rowsShown"] == 0 and pg.evaluate("localStorage.getItem('stackshot-color-trial:fields')") is None and pg.evaluate(CT_STATE) ["key"] is not None, fd)
    pg.keyboard.press("Escape"); pg.click("#ct-btn")
    check("colors: closed and opened again, the fields are still folded", pg.get_attribute("#ct-fold", "aria-expanded") == "false" and pg.evaluate(CT_RECT, "#ct-fields") is None)
    ct_fields(pg)
    pg.click("#ct-reset"); pg.wait_for_timeout(60); st3 = pg.evaluate(CT_STATE)
    check("colors: Reset returns everything to the shipped look: no inline property, no class, no stored key, every hex box shipped", st3["inline"] == "" and st3["cls"] == [] and st3["key"] is None and st3["bg"] == "rgb(22, 22, 23)"
          and pg.input_value("#ct-h-bg") == "#161617" and pg.input_value("#ct-h-solid") == pg.evaluate("window.ColorTool.engine(window.stackshotColors).ship().solid") and pg.inner_text("#ct-cur") == "Now: Original orange theme", st3)
    PRE_SOLID = {"sky": "rgb(42, 111, 208)", "mint": "rgb(24, 128, 93)", "violet": "rgb(122, 82, 224)", "rose": "rgb(214, 51, 108)"}
    PRE_ON = {k: "rgb(255, 255, 255)" for k in PRE_SOLID}
    PRE_LAB = {"sky": "rgb(20, 40, 63)", "mint": "rgb(16, 48, 42)", "violet": "rgb(37, 28, 70)", "rose": "rgb(64, 24, 42)"}
    for pid in ("sky", "mint", "violet", "rose"):
        pg.click(f".ct-preset[data-p={pid}]"); pg.wait_for_timeout(450)      # the buttons' colors fade over a few hundred ms
        sd, dd, lab = (pg.eval_on_selector("#ct-pop .ct-prev .b.main:not(:disabled)", CT_PROPS), pg.eval_on_selector("#ct-pop .ct-prev .b:disabled:not(.main)", CT_PROPS), pg.eval_on_selector("#ct-pop .ct-prev .badge.rec", CT_PROPS))
        st = pg.evaluate(CT_STATE); dotp = pg.evaluate(CT_DOT)
        check(f"colors: the {pid} preset applies at once: pressed, 'Now' names it, the page keeps its neutrals, the solid Send shows its solid and label, the disabled Undo its flat fill and text at full opacity (the stylesheet's dark disabled rule), the small label its fill, the circle's right half its solid",
              pg.get_attribute(f".ct-preset[data-p={pid}]", "aria-pressed") == "true" and pg.locator(".ct-preset[aria-pressed=true]").count() == 1 and pg.inner_text("#ct-cur") == "Now: " + pg.get_attribute(f".ct-preset[data-p={pid}]", "data-n")
              and st["bg"] == "rgb(22, 22, 23)" and sd[0] == PRE_SOLID[pid] and sd[1] == PRE_ON[pid] and dd[0] == "rgb(42, 42, 44)" and dd[1] == "rgb(163, 162, 157)" and dd[3] == "1" and lab[0] == PRE_LAB[pid]
              and "ct-on" in st["cls"] and "ct-dis" not in st["cls"] and "ct-lab" not in st["cls"] and dotp["b"] == PRE_SOLID[pid], (pid, sd, dd, lab, st["cls"], dotp))
    PRE_NAMES = ["Original orange theme", "Sky", "Mint", "Violet", "Rose"]
    check("colors: every preset reads clean, so no button carries the 'pair below their limit' mark: the buttons' names are the presets' names, and no note shows a ratio below a limit",
          [pg.get_attribute(f".ct-preset[data-p={p}]", "aria-label") for p in ("live", "sky", "mint", "violet", "rose")] == PRE_NAMES and pg.locator(".ct-preset").count() == 5 and "Below its limit" not in pg.inner_text("#ct-pop"),
          [pg.get_attribute(f".ct-preset[data-p={p}]", "aria-label") for p in ("live", "sky", "mint", "violet", "rose")])
    pg.click(".ct-preset[data-p=live]"); pg.wait_for_timeout(80); st = pg.evaluate(CT_STATE)
    check("colors: the Original orange theme applies the shipped look: nothing stored, no class, no inline property (the same as Reset: every property the tool set, onApply's too, is taken off)", st["key"] is None and st["cls"] == [] and st["inline"] == "" and pg.inner_text("#ct-cur") == "Now: Original orange theme", st)
    pg.click("#ct-reset")
    saved_note = pg.inner_text("#ct-n-saved")
    check("colors: on a page that is not served by the board (file) the saved list says it is not available and the panel still works", "not available" in saved_note and pg.evaluate(CT_RECT, "#ct-reset") is not None, saved_note)
    check("colors: nothing was asked of the network by any of this but the saved list's address (no request but the page's own files and its web font)", sent == [], sent[:3])
    ctx.close()
    # the saved combinations against a routed origin that serves the page and the routes from the real store
    CT_HTML = CT_FILES["board"].read_text(encoding="utf-8")
    ct_mode = {"m": "ok", "calls": []}
    def ct_json(route, status, d): route.fulfill(status=status, content_type="application/json", body=json.dumps(d))
    def ct_handler(route, request):
        u = urllib.parse.urlparse(request.url).path
        if u == "/": return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=CT_HTML)
        if u not in ("/colors/combos", "/colors/combos/delete"): return route.fulfill(status=404, body="")
        ct_mode["calls"].append((request.method, u))
        m = ct_mode["m"]
        if m == "abort": return route.abort()
        if m == "403": return ct_json(route, 403, {"error": "sign in to the board to use the saved colors"})
        if m == "503": return route.fulfill(status=503, content_type="text/plain", body="down")
        if m == "full" and request.method == "POST": return ct_json(route, 409, {"error": "the list is full, delete one"})
        try:
            if request.method == "GET": d = _cc.payload()
            elif u.endswith("/delete"): d = _cc.payload(_cc.delete(json.loads(request.post_data).get("id")))
            else: b = json.loads(request.post_data); d = _cc.payload(_cc.save(b.get("name"), b.get("values"), "board"))
        except _cc.Invalid as e: return ct_json(route, 400, {"error": str(e), "field": e.field})
        ct_json(route, 200, d)
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark"); ctx.route(re.compile(r"^http://board\.test/"), ct_handler); pg = ctx.new_page()
    pg.goto("http://board.test/"); pg.wait_for_timeout(150); ct_show(pg); pg.click("#ct-btn"); pg.wait_for_timeout(250)
    check("colors: opening the panel reads the saved list once (a GET of the board's own address) and shows the count", ct_mode["calls"] == [("GET", "/colors/combos")] and pg.text_content("#ct-cnt") == "0 of 50 saved" and pg.locator("#ct-list li").count() == 0, (ct_mode["calls"], pg.text_content("#ct-cnt")))
    pg.click(".ct-preset[data-p=rose]"); pg.fill("#ct-name", "Trial A"); pg.click("#ct-save"); pg.wait_for_timeout(250); got = _cc.listing()
    check("colors: Save under a name stores the 14 resolved values on the server (via board) and lists it; the note says Saved", len(got) == 1 and got[0]["name"] == "Trial A" and got[0]["via"] == "board" and len(got[0]["values"]) == 14
          and got[0]["values"]["solid"] == "#d6336c" and got[0]["values"]["bg"] == "#161617" and pg.inner_text("#ct-n-saved") == "Saved Trial A." and pg.locator("#ct-list .ct-use").all_inner_texts() == ["Trial A"] and pg.text_content("#ct-cnt") == "1 of 50 saved", (got, pg.inner_text("#ct-n-saved")))
    first_id = got[0]["id"]; look = pg.evaluate(CT_STATE)
    pg.click("#ct-reset"); pg.wait_for_timeout(60); pg.click("#ct-list .ct-use"); pg.wait_for_timeout(100); st = pg.evaluate(CT_STATE)
    check("colors: a saved combination applies at once (and is the Rose look again: 'Now' says so), the note says Applied; the stored look is the same map the preset made", st == look and pg.inner_text("#ct-n-saved") == "Applied Trial A." and pg.inner_text("#ct-cur") == "Now: Rose", (st, look))
    pg.fill("#ct-name", "trial a"); pg.click("#ct-save"); pg.wait_for_timeout(250); got = _cc.listing()
    check("colors: a save under the same name (case ignored) replaces it in place: still one entry, the same id, the new spelling; the note says Replaced", len(got) == 1 and got[0]["id"] == first_id and got[0]["name"] == "trial a" and pg.inner_text("#ct-n-saved") == "Replaced trial a." and pg.text_content("#ct-cnt") == "1 of 50 saved", got)
    pg.reload(); pg.wait_for_timeout(150); st = pg.evaluate(CT_STATE); ct_show(pg); pg.click("#ct-btn"); pg.wait_for_timeout(250)
    check("colors: after a reload the applied look is kept (this browser) and the saved list is read again from the server", st == look and pg.locator("#ct-list .ct-use").all_inner_texts() == ["trial a"], st)
    n0 = len(ct_mode["calls"]); pg.fill("#ct-name", "   "); pg.click("#ct-save")
    check("colors: an empty name is not sent: the note asks for one", pg.inner_text("#ct-n-saved") == "Give it a name first." and len(ct_mode["calls"]) == n0, pg.inner_text("#ct-n-saved"))
    pg.click("#ct-list .ct-del"); pg.wait_for_timeout(60)
    check("colors: Delete asks once more (the button reads 'Delete?') and nothing is deleted by the first tap", pg.inner_text("#ct-list .ct-del") == "Delete?" and len(_cc.listing()) == 1 and len(ct_mode["calls"]) == n0)
    pg.click("#ct-list .ct-del"); pg.wait_for_timeout(250)
    check("colors: the second tap deletes it on the server and the list; the note says Deleted; the applied look is untouched", _cc.listing() == [] and pg.locator("#ct-list li").count() == 0 and pg.inner_text("#ct-n-saved") == "Deleted." and pg.text_content("#ct-cnt") == "0 of 50 saved" and pg.evaluate(CT_STATE) == look)
    # refusals: the route's own text is shown, and the applied look is never lost
    try: _cc.validate("x" * 41, {k: "#161617" for k in _cc.KEYS}); bad_text = None
    except _cc.Invalid as e: bad_text = str(e)
    for label, mode, name, want in (("403 (not signed in)", "403", "Refused", "sign in to the board to use the saved colors"), ("409 (the list is full)", "full", "Refused", "the list is full, delete one"),
                                    ("400 (a name over 40 characters, the route's text)", "ok", "x" * 41, bad_text), ("503 (the file cannot be read)", "503", "Refused", "Saved combinations are not available right now."),
                                    ("a network that is down", "abort", "Refused", "offline")):
        ct_mode["m"] = mode; keep = pg.evaluate(CT_STATE); pg.evaluate("([id, v]) => { document.getElementById(id).value = v; }", ["ct-name", name]); pg.click("#ct-save"); pg.wait_for_timeout(250); note = pg.inner_text("#ct-n-saved")
        check(f"colors: a save refused by {label} shows the message ({want!r}) and the applied look and stored key are as they were", want is not None and want in note and pg.evaluate(CT_STATE) == keep and _cc.listing() == [], (note, want))
    ct_mode["m"] = "403"; pg.click("#ct-reset"); pg.click("#ct-btn"); pg.click("#ct-btn"); pg.wait_for_timeout(250)
    check("colors: a list that cannot be read (403 on opening) says so in the panel; the rest of the panel works", "sign in to the board" in pg.inner_text("#ct-n-saved") and pg.text_content("#ct-cnt") == "" and pg.evaluate(CT_RECT, "#ct-reset") is not None, pg.inner_text("#ct-n-saved"))
    ct_mode["m"] = "ok"; ctx.close()
    # a touch screen: a saved row's two buttons are 44 px tall and inside the panel
    ctx = br.new_context(viewport={"width": 360, "height": 740}, color_scheme="dark", has_touch=True); ctx.route(re.compile(r"^http://board\.test/"), ct_handler); pg = ctx.new_page()
    pg.goto("http://board.test/"); pg.wait_for_timeout(150); ct_show(pg); pg.tap("#ct-btn"); pg.wait_for_timeout(150); pg.fill("#ct-name", "A name that is long enough to run past the end of one line of the panel"); pg.tap("#ct-save"); pg.wait_for_timeout(300)
    rows = pg.evaluate("() => { const p = document.getElementById('ct-pop').getBoundingClientRect(); return [...document.querySelectorAll('#ct-list .ct-use, #ct-list .ct-del')].map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.height), r.right <= p.right + 0.5 && r.left >= p.left - 0.5]; }); }")
    check("colors: on a 360 px touch screen a saved row's apply and Delete buttons are 44 px or taller and inside the panel, a long name cut on its button and not overflowing", len(rows) == 2 and all(a >= 43.5 and b for a, b in rows), rows)
    # a saved-list answer that arrives late: the panel is scrolled to its end again only if it was at its end when the answer came (held answers, so the timing is ours)
    pg.tap("#ct-fold"); pg.wait_for_timeout(100)
    CT_END = "() => { const p = document.getElementById('ct-pop'); return [p.scrollTop, p.scrollTop + p.clientHeight >= p.scrollHeight - 1, p.scrollHeight > p.clientHeight]; }"
    ct_ans = lambda names: "() => { window.__held.shift()(new Response(" + json.dumps(json.dumps({"combos": [{"id": "h%d" % i, "name": n, "values": {}} for i, n in enumerate(names)], "max": 50})) + ", {status: 200})); }"
    pg.evaluate("() => { window.__fetch0 = window.fetch; window.__held = []; window.fetch = () => new Promise(res => window.__held.push(res)); }")
    pg.tap("#ct-btn"); pg.wait_for_timeout(60); pg.tap("#ct-btn"); pg.wait_for_timeout(100)
    pg.evaluate("() => { document.getElementById('ct-pop').scrollTop = 0; }"); before = pg.evaluate(CT_END)
    pg.evaluate(ct_ans(["Held"])); pg.wait_for_timeout(100); after = pg.evaluate(CT_END)
    check("colors: a saved list that answers after the person scrolled the panel up does not snap it back to the end (the panel is long here: fields open at 360 px)", before[2] and before[0] == 0 and after[0] == 0 and not after[1] and pg.locator("#ct-list .ct-use").all_inner_texts() == ["Held"], (before, after))
    pg.evaluate("() => { const p = document.getElementById('ct-pop'); p.scrollTop = p.scrollHeight; }"); pg.fill("#ct-name", "Held"); pg.tap("#ct-save"); pg.wait_for_timeout(60)
    pg.evaluate("() => { const p = document.getElementById('ct-pop'); p.scrollTop = p.scrollHeight; }")
    pg.evaluate(ct_ans(["Held", "Second", "Third"])); pg.wait_for_timeout(100); after = pg.evaluate(CT_END)
    check("colors: a save that answers while the panel is at its end, and adds rows, keeps the panel at its end (the last row and the note are in view)", after[1] and pg.locator("#ct-list .ct-use").count() == 3 and pg.inner_text("#ct-n-saved") == "Replaced Held.", (after, pg.inner_text("#ct-n-saved")))
    pg.evaluate("() => { window.fetch = window.__fetch0; }"); ct_fields(pg, False)
    # a saved combination whose background the gate refuses (a white page): tapped, the sentence appears in the saved note beside the list (not only in the presets note at the top), stays, and the look is unchanged
    ship = pg.evaluate("window.ColorTool.engine(window.stackshotColors).ship()"); _cc.save("White page", {**{k: v for k, v in ship.items() if k != "ifill"}, "bg": "#ffffff"}, "board")
    pg.tap("#ct-btn"); pg.wait_for_timeout(100); pg.tap("#ct-btn"); pg.wait_for_timeout(300)
    pg.evaluate("() => { const p = document.getElementById('ct-pop'); p.scrollTop = p.scrollHeight; }"); keep = pg.evaluate(CT_STATE)
    pg.locator("#ct-list .ct-use", has_text="White page").tap(); pg.wait_for_timeout(300); note = pg.inner_text("#ct-n-saved"); nr, pr_ = pg.evaluate(CT_RECT, "#ct-n-saved"), pg.evaluate(CT_RECT, "#ct-pop")
    check("colors: a saved combination the gate refuses (a white page) says 'Not applied' with the combination's name and the ratio in the saved note, in view inside the panel, and the applied look is unchanged",
          note.startswith("White page: Not applied: body text would read") and "11:1 needed" in note and nr is not None and nr["t"] >= pr_["t"] - 0.5 and nr["b"] <= pr_["b"] + 0.5 and pg.evaluate(CT_STATE) == keep, (note, nr, pr_))
    pg.wait_for_timeout(700)
    check("colors: that note is not blanked a moment later", pg.inner_text("#ct-n-saved") == note and pg.get_attribute("#ct-n-saved", "role") == "status" and pg.get_attribute("#ct-n-saved", "aria-live") == "polite", pg.inner_text("#ct-n-saved"))
    dels = pg.locator("#ct-list .ct-del")
    dels.nth(0).tap(); pg.wait_for_timeout(60); dels.nth(1).tap(); pg.wait_for_timeout(60)
    check("colors: arming Delete on a second row puts the first row's button back to 'Delete' (only one row reads 'Delete?'), and nothing is deleted", dels.all_inner_texts() == ["Delete", "Delete?"] and len(_cc.listing()) == 2, dels.all_inner_texts())
    for it in _cc.listing(): _cc.delete(it["id"])
    check("colors: the test store is empty again", _cc.listing() == [])
    ctx.close()
    # the light theme, a stored look in the dark one, the theme switch
    SEED = json.dumps({"bg": "#1f1f21", "link": "#ffa057", "solid": "#bd561d", "labbg": "#462100", "disbg": "#2a2a2c", "disfg": "#a3a29d"})
    for scheme in ("light", "dark"):
        ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme=scheme)
        ctx.add_init_script("try{localStorage.setItem('stackshot-color-trial', JSON.stringify(" + SEED + "))}catch(e){}")
        pg = ctx.new_page(); pg.goto(CT_FILES["board"].as_uri()); pg.wait_for_timeout(150); s = pg.evaluate(CT_STATE)
        if scheme == "light":
            check("colors: in the light theme nothing is drawn (no button, no panel in the page at all) and the saved dark look applies nothing (no inline property, no class, the shipped page color)", pg.locator("#ct-btn").count() == 0 and pg.locator("#ct-pop").count() == 0 and s["inline"] == "" and s["cls"] == [] and s["bg"] == "rgb(250, 250, 248)", s)
        else:
            ct_show(pg)
            check("colors: the same stored look in the dark theme is applied on the first load, with its class (ct-on; the labels and the disabled buttons are drawn by the stylesheet from the tokens the look sets), and the button is drawn", pg.evaluate(CT_RECT, "#ct-btn") is not None and s["bg"] == "rgb(31, 31, 33)" and "ct-on" in s["cls"] and "ct-lab" not in s["cls"] and "ct-dis" not in s["cls"], s)
            check("colors: the html class ct-lab (small labels) adds no bold weight to the page: the root's font weight is the normal one (the panel's row label class is another name)", pg.evaluate("getComputedStyle(document.documentElement).fontWeight") == "400", pg.evaluate("getComputedStyle(document.documentElement).fontWeight"))
            pg.evaluate("document.documentElement.setAttribute('data-theme', 'light')"); pg.wait_for_timeout(80); s = pg.evaluate(CT_STATE)
            check("colors: the theme switch to light removes the override and hides the button at once", pg.evaluate(CT_RECT, "#ct-btn") is None and s["inline"] == "" and s["cls"] == [], s)
            pg.evaluate("document.documentElement.setAttribute('data-theme', 'dark')"); pg.wait_for_timeout(80)
            check("colors: back to the dark theme the stored look is applied again and the button is back", pg.evaluate(CT_STATE)["bg"] == "rgb(31, 31, 33)" and pg.evaluate(CT_RECT, "#ct-btn") is not None)
        ctx.close()
    # a stored look from the first version ({text}) is read as the text orange; a stored value that fails the gate is not applied and is cleared at load, the fields beside it kept
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark")
    ctx.add_init_script("try{if(!sessionStorage.getItem('ct-seeded')){sessionStorage.setItem('ct-seeded','1');localStorage.setItem('stackshot-color-trial', JSON.stringify({bg:'#ffffff',text:'#ffa057'}))}}catch(e){}")
    pg = ctx.new_page(); pg.goto(CT_FILES["board"].as_uri()); pg.wait_for_timeout(150); st = pg.evaluate(CT_STATE)
    check("colors: a stored #ffffff background (a hand-stored value) is not applied and is cleared at load; the first version's {text} beside it is read as the text orange, kept and applied", st["bg"] == "rgb(22, 22, 23)" and json.loads(st["key"]) == {"link": "#ffa057"}
          and "--orange-text" in st["inline"].split() and "--bg" not in st["inline"].split(), st)
    ctx.close()
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark")
    ctx.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('storage is off'); }});")
    pg = ctx.new_page(); pg.goto(CT_FILES["board"].as_uri()); pg.wait_for_timeout(150); ct_show(pg); pg.click("#ct-btn"); ct_fields(pg)
    check("colors: with storage off the panel has no note until a pick", pg.inner_text("#ct-n-store") == "" and not pg.is_visible("#ct-n-store"), pg.inner_text("#ct-n-store"))
    pg.fill("#ct-h-link", "#ffa057"); pg.wait_for_timeout(60)
    check("colors: with storage off a pick says in one line that it cannot be kept, instead of doing nothing without a word", "does not allow saving" in pg.inner_text("#ct-n-store") and pg.is_visible("#ct-n-store"), pg.inner_text("#ct-n-store"))
    pg.click("#ct-reset"); pg.wait_for_timeout(60)
    check("colors: Reset clears that note", pg.inner_text("#ct-n-store") == "", pg.inner_text("#ct-n-store"))
    ctx.close()
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark", java_script_enabled=False); pg = ctx.new_page(); pg.goto(CT_FILES["board"].as_uri()); pg.wait_for_timeout(150)
    check("colors: with JavaScript off no Colors button is drawn (the page carries no markup of the tool: the script draws it)", not pg.is_visible("#ct-btn") and pg.locator("#ct-btn").count() == 0 and pg.locator("#ct-pop").count() == 0, pg.is_visible("#ct-btn"))
    ctx.close()
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark"); pg = ctx.new_page(); pg.goto(CT_FILES["board"].as_uri()); pg.wait_for_timeout(150); ct_show(pg)
    check("colors: with JavaScript on the button is drawn", pg.is_visible("#ct-btn"))
    ctx.close()
    # an idle page: with nothing stored the Send and the disabled buttons compute as on a page without the tool (its script blocks cut out); with the disabled pair stored, every disabled button outside the panel is restyled
    stripped = T / "colors-stripped.html"; stripped.write_text(_C.without_colortool(CT_FILES["item (answer box)"].read_text(encoding="utf-8")), encoding="utf-8")
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark"); pg = ctx.new_page()
    pg.goto(CT_FILES["item (answer box)"].as_uri()); pg.wait_for_timeout(150); live = pg.evaluate(CT_IDLE); has_ct = pg.evaluate("[...document.documentElement.classList].some(c => c.startsWith('ct-'))")
    pg.goto(stripped.as_uri()); pg.wait_for_timeout(150); plain = pg.evaluate(CT_IDLE); gone = pg.locator("#ct-btn").count()
    check("colors: with nothing stored the page's Send, idle Send and disabled buttons compute exactly as on the same page without the tool (background, text, outline, opacity, weight, outline width)", live == plain and gone == 0 and not has_ct and "idle" in plain, (live, plain))
    ctx.close()
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark")
    ctx.add_init_script("try{localStorage.setItem('stackshot-color-trial', JSON.stringify({disbg:'#303034',disfg:'#c0bfba'}))}catch(e){}")
    pg = ctx.new_page(); pg.goto(CT_FILES["item (answer box)"].as_uri()); pg.wait_for_timeout(150); dis = pg.evaluate(CT_IDLE)
    check("colors: with the disabled pair stored, the idle Send and every disabled button outside the panel take the flat fill and text at full opacity",
          all(dis[k][0] == "rgb(48, 48, 52)" and dis[k][1] == "rgb(192, 191, 186)" and dis[k][3] == "1" for k in dis if k != "send") and "idle" in dis, dis)
    ctx.close()
    # applyStored alone draws nothing and init draws the button (the same file, stackshot's pages): a page that only applies the stored look in its head has no button and no panel
    head_only = T / "colors-head-only.html"; head_only.write_text(CT_FILES["board"].read_text(encoding="utf-8").replace("ColorTool.init(window.stackshotColors);", ""), encoding="utf-8")
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark")
    ctx.add_init_script("try{localStorage.setItem('stackshot-color-trial', JSON.stringify({bg:'#1f1f21',solid:'#bd561d'}))}catch(e){}")
    pg = ctx.new_page(); pg.goto(head_only.as_uri()); pg.wait_for_timeout(150); s = pg.evaluate(CT_STATE)
    check("colors: applyStored alone applies the stored look from the head (the page paints it, the classes are on) and draws nothing: no button, no panel, nothing in the mount", s["bg"] == "rgb(31, 31, 33)" and "ct-on" in s["cls"]
          and pg.locator("#ct-btn").count() == 0 and pg.locator("#ct-pop").count() == 0 and pg.inner_text("#panel-colors") == "" and pg.locator("#panel-colors > *").count() == 0, (s, pg.locator("#ct-btn").count()))
    ctx.close()

    # ---- the same file in a page of another app: other settings, its own mount and property names, no saved list, no preview
    CT_LIB = (pathlib.Path(STACK) / "shared" / "colortool.js").read_text(encoding="utf-8")
    FAKE_CFG = """window.fakeApp = {storageKey: 'fake-app-look', mount: '#slot',
      shipped: function () { var cs = getComputedStyle(document.documentElement); function g(n) { return cs.getPropertyValue(n).trim(); }
        return {bg: g('--bg'), card: g('--card'), line: g('--line'), fg: g('--fg'), mut: g('--mut'), link: g('--accent'), ibd: g('--ibd'), solid: g('--cta'), onsolid: '#ffffff', labbg: '#173046', labfg: g('--accent'), labbd: g('--accent'), disbg: '#2a3a4a', disfg: '#9fb0c0', ifill: g('--ifill')}; },
      vars: {bg: ['--bg'], card: ['--card'], line: ['--line'], fg: ['--fg'], mut: ['--mut'], ibd: ['--ibd'], link: ['--accent'], solid: ['--cta']},
      onApply: function (r, s, set, add) { if (s.bg) set('--ifill', r.ifill); if (s.solid) { set('--cta-text', r.onsolid); add('fake-solid'); } window.fakeApplies = (window.fakeApplies || 0) + 1; },
      isDark: function () { return !window.fakeLightApp; }, GATE};"""
    FAKE_PAGE = """<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>:root{--bg:#101820;--card:#18222c;--line:#2a3642;--fg:#e8eef4;--mut:#9fb0c0;--ibd:#7f90a0;--ifill:#22303c;--accent:#4aa3ff;--cta:#2f7fd6}
body{margin:0;background:var(--bg);color:var(--fg);font:14px system-ui}main{padding:16px;max-width:520px}aside{position:fixed;right:0;top:0;bottom:0;width:240px;overflow-y:auto;background:var(--card);box-sizing:border-box;padding:16px}
#slot{position:sticky;bottom:0;padding:10px 0;background:var(--card)}.cta{background:var(--cta);color:var(--cta-text,#fff);padding:6px 12px;border:0;border-radius:6px}
.pvb{font:italic 17px serif;color:#ff00aa;padding:4px 10px}</style>
<script>%(lib)s</script><script>%(pre)s%(cfg)s ColorTool.applyStored(window.fakeApp);</script></head>
<body><main><h1>Another app</h1><p>Some text.</p><button class="cta">Go</button></main><aside><div style="height:1200px">side content</div><div id="slot"></div></aside>%(init)s</body></html>"""
    def fake_file(name, gate="", pre="", init=True, extra=""):
        f = T / name; f.write_text(FAKE_PAGE % {"lib": CT_LIB, "pre": pre, "cfg": FAKE_CFG.replace("GATE", (("gate: '%s'" % gate) if gate else "x: 0") + (", " + extra if extra else "")), "init": "<script>ColorTool.init(window.fakeApp);</script>" if init else ""}, encoding="utf-8"); return f
    FS = """() => { const r = document.documentElement; return {bg: getComputedStyle(document.body).backgroundColor, inline: [...r.style].sort().join(' '), cls: [...r.classList].sort().join(' '), key: localStorage.getItem('fake-app-look'), other: localStorage.getItem('stackshot-color-trial')}; }"""
    FSEED = json.dumps({"bg": "#0b1218", "solid": "#d9722e"})
    f_head = fake_file("fake-head-only.html", init=False); f_full = fake_file("fake-full.html"); f_warn = fake_file("fake-warn.html", gate="warn")
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark"); ctx.add_init_script("try{localStorage.setItem('fake-app-look', JSON.stringify(" + FSEED + "))}catch(e){}")
    pg = ctx.new_page(); pg.goto(f_head.as_uri()); pg.wait_for_timeout(150); s = pg.evaluate(FS)
    check("another app: applyStored alone applies the stored look from the head under the app's own properties and class, and draws nothing (no button, no panel, an empty mount)", s["bg"] == "rgb(11, 18, 24)" and "--cta" in s["inline"].split() and "--cta-text" in s["inline"].split() and s["cls"] == "fake-solid"
          and pg.locator("#ct-btn").count() == 0 and pg.locator("#ct-pop").count() == 0 and pg.locator("#slot > *").count() == 0 and s["other"] is None, s)
    pg.goto(f_full.as_uri()); pg.wait_for_timeout(150); s = pg.evaluate(FS)
    check("another app: init draws the button in the app's own mount (#slot) and the panel in the body; the tool keeps to the app's key (the stackshot key is not touched); no Saved box and no Preview box when the settings give no api and no preview",
          pg.evaluate("document.getElementById('ct-btn').parentElement.parentElement.id") == "slot" and pg.evaluate("document.getElementById('ct-pop').parentElement.tagName") == "BODY" and pg.locator("#ct-saved").count() == 0 and pg.locator("#ct-pop .ct-prev").count() == 0
          and pg.locator("#ct-pop .ct-box").count() == 5 and pg.locator("#ct-pop .ct-row").count() == 14 and s["other"] is None and json.loads(s["key"]) == {"bg": "#0b1218", "solid": "#d9722e"}, s)
    pg.click("#ct-btn"); pg.wait_for_timeout(120); pop = pg.evaluate(CT_RECT, "#ct-pop"); btn = pg.evaluate(CT_RECT, "#ct-btn")
    check("another app: the panel opens upward from the app's button, fixed in the body, inside the screen; the circle shows the app's live page color and solid fill", pop is not None and btn is not None and pop["b"] <= btn["t"] + 0.5 and pop["t"] >= 0 and pop["r"] <= 1100
          and pg.evaluate("getComputedStyle(document.getElementById('ct-pop')).position") == "fixed" and pg.evaluate(CT_DOT)["a"] == "rgb(11, 18, 24)" and pg.evaluate(CT_DOT)["b"] == "rgb(217, 114, 46)", (pop, btn, pg.evaluate(CT_DOT)))
    check("another app: the Fields fold starts closed here too and is kept under that app's own key plus ':fields' (the stackshot key is not written)", pg.get_attribute("#ct-fold", "aria-expanded") == "false" and pg.evaluate(CT_RECT, "#ct-fields") is None)
    ct_fields(pg)
    check("another app: unfolded, the fold is kept under its own key", pg.evaluate("localStorage.getItem('fake-app-look:fields')") == "1" and pg.evaluate("localStorage.getItem('stackshot-color-trial:fields')") is None)
    pg.click("#ct-reset"); pg.wait_for_timeout(80); s = pg.evaluate(FS)
    check("another app: Reset takes off every inline property the tool and the app's onApply set (the extras and the class too) and clears the key; the app's page is back to its own colors", s["inline"] == "" and s["cls"] == "" and s["key"] is None and s["bg"] == "rgb(16, 24, 32)", s)
    pg.fill("#ct-h-solid", "#d9722e"); pg.wait_for_timeout(60); s = pg.evaluate(FS)
    check("another app: a new pick sets the app's properties again", "--cta" in s["inline"].split() and "--cta-text" in s["inline"].split() and s["cls"] == "fake-solid", s)
    pg.click(".ct-preset[data-p=live]"); pg.wait_for_timeout(60); s = pg.evaluate(FS)
    check("another app: the original orange theme (stored = nothing) takes off the same properties, the extras included, and runs onApply once more", s["inline"] == "" and s["cls"] == "" and s["key"] is None and pg.evaluate("window.fakeApplies") >= 4, (s, pg.evaluate("window.fakeApplies")))
    pg.fill("#ct-h-bg", "#ffffff"); pg.wait_for_timeout(60); s = pg.evaluate(FS)
    check("another app on the default gate: a white page is turned down with the 'Not applied' note and nothing changes", s["key"] is None and s["bg"] == "rgb(16, 24, 32)" and pg.inner_text("#ct-n-bg").startswith("Not applied: body text would read"), (s, pg.inner_text("#ct-n-bg")))
    ctx.close()
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark"); pg = ctx.new_page(); pg.goto(f_warn.as_uri()); pg.wait_for_timeout(150); pg.click("#ct-btn"); pg.wait_for_timeout(100); ct_fields(pg)
    pg.fill("#ct-h-bg", "#ffffff"); pg.wait_for_timeout(80); s = pg.evaluate(FS); note = pg.inner_text("#ct-n-fg")
    check("another app on the warn gate: a white page is applied and stored, nothing says 'Not applied', and the row of the body text carries the ratio as a note", s["bg"] == "rgb(255, 255, 255)" and json.loads(s["key"]) == {"bg": "#ffffff"} and not pg.inner_text("#ct-n-bg").startswith("Not applied")
          and re.search(r"Below its limit: \d+\.\d\d:1 body text on the page \(below 11:1\)", note) is not None, (s, note))
    pg.reload(); pg.wait_for_timeout(150); s2 = pg.evaluate(FS)
    check("another app on the warn gate: a reload keeps the white page and does not clear it from storage", s2["bg"] == "rgb(255, 255, 255)" and json.loads(s2["key"]) == {"bg": "#ffffff"}, s2)
    ctx.close()
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark"); ctx.add_init_script("try{localStorage.setItem('fake-app-look', JSON.stringify(" + FSEED + "))}catch(e){}")
    f_light = fake_file("fake-light.html", pre="window.fakeLightApp = true;")
    pg = ctx.new_page(); pg.goto(f_light.as_uri()); pg.wait_for_timeout(150); s = pg.evaluate(FS)
    check("another app whose isDark() is false (a page marked dark): nothing is drawn and nothing is applied, the stored look stays in storage", pg.locator("#ct-btn").count() == 0 and pg.locator("#ct-pop").count() == 0 and s["inline"] == "" and s["cls"] == "" and s["key"] is not None and s["bg"] == "rgb(16, 24, 32)", s)
    ctx.close()
    # remount: the app re-renders its mount; the button follows and the open panel stays open; at 360 px the panel still fits the screen with its own scroll
    ctx = br.new_context(viewport={"width": 360, "height": 640}, color_scheme="dark", has_touch=True); pg = ctx.new_page(); pg.goto(f_full.as_uri()); pg.wait_for_timeout(150); pg.tap("#ct-btn"); pg.wait_for_timeout(150); pg.tap("#ct-fold"); pg.wait_for_timeout(120)
    pop = pg.evaluate(CT_RECT, "#ct-pop"); geo = pg.evaluate("() => { const p = document.getElementById('ct-pop'); return [p.scrollHeight, p.clientHeight, getComputedStyle(p).overflowY]; }")
    check("another app at 360 px: the panel is inside the 360 by 640 screen, at most 624 px tall, and scrolls inside itself", pop is not None and pop["l"] >= 0 and pop["r"] <= 360.5 and pop["t"] >= 0 and pop["b"] - pop["t"] <= 624.5 and geo[0] > geo[1] and geo[2] == "auto", (pop, geo))
    pg.evaluate("() => { const old = document.getElementById('slot'), n = old.cloneNode(false); n.innerHTML = ''; n.id = 'slot2'; n.style.cssText = 'position:sticky;bottom:0;padding:10px 0;background:var(--card)'; old.replaceWith(n); }")
    gone_btn = pg.locator("#ct-btn").count()
    pg.evaluate("ColorTool.remount(document.getElementById('slot2'))"); pg.wait_for_timeout(120)
    pop2 = pg.evaluate(CT_RECT, "#ct-pop"); btn2 = pg.evaluate(CT_RECT, "#ct-btn")
    check("another app: remount moves the button into the new mount element; the panel stays open (aria-expanded true, its fields and state kept) and is placed above the button again",
          gone_btn == 0 and pg.evaluate("document.getElementById('ct-btn').parentElement.parentElement.id") == "slot2" and pg.get_attribute("#ct-btn", "aria-expanded") == "true" and pop2 is not None and btn2 is not None and pop2["b"] <= btn2["t"] + 0.5
          and pg.locator("#ct-pop").count() == 1 and pg.locator("#ct-btn").count() == 1, (gone_btn, pop2, btn2))
    ctx.close()
    # a click on a preset's dots applies the preset and keeps the panel open (the dots are built once; a rebuilt dot would be gone from the page before the outside-click test looks at it)
    from stackshot.web.ui import colortool as _ctm
    for w, h, touch in ((1100, 800, False), (390, 800, True)):
        ctx = br.new_context(viewport={"width": w, "height": h}, color_scheme="dark", has_touch=touch); pg = ctx.new_page(); pg.goto(CT_FILES["board"].as_uri()); pg.wait_for_timeout(150); ct_show(pg)
        pg.click("#ct-btn"); pg.wait_for_timeout(100)
        ids = pg.evaluate("window.__dots = [...document.querySelectorAll('.ct-preset[data-p=rose] .ct-dots i')]; window.__dots.length")
        for j in (0, 3):
            box = pg.locator(".ct-preset[data-p=rose] .ct-dots i").nth(j)
            (box.tap if touch else box.click)(); pg.wait_for_timeout(450)
            check(f"colors {w}{' touch' if touch else ''}: a click on dot {j + 1} of a preset applies the preset (pressed, its solid fill on the page) and the panel stays open", pg.evaluate(CT_RECT, "#ct-pop") is not None and pg.get_attribute("#ct-btn", "aria-expanded") == "true"
                  and pg.get_attribute(".ct-preset[data-p=rose]", "aria-pressed") == "true" and json.loads(pg.evaluate(CT_STATE)["key"]).get("solid") == "#d6336c", (pg.get_attribute("#ct-btn", "aria-expanded"), pg.evaluate(CT_STATE)["key"]))
        check(f"colors {w}{' touch' if touch else ''}: the dots are the same four elements after the apply (built once, only their color changes)", ids == 4 and pg.evaluate("window.__dots.every(e => e.isConnected)"), ids)
        pg.click(".ct-preset[data-p=live]"); pg.wait_for_timeout(100)
        pg.mouse.click(2, 2) if not touch else pg.touchscreen.tap(2, 2); pg.wait_for_timeout(150)
        check(f"colors {w}{' touch' if touch else ''}: a click outside still closes the panel", pg.evaluate(CT_RECT, "#ct-pop") is None and pg.get_attribute("#ct-btn", "aria-expanded") == "false")
        ctx.close()
    # the panel's own buttons and boxes keep the panel's font and color, and a preview the app brings is its own: a button in the preview strip is styled by the app's stylesheet alone
    f_prev = fake_file("fake-preview.html", extra="preview: '<button type=\"button\" class=\"pvb\" tabindex=\"-1\">Go</button>', text: {note: 'A note of the other app.', example: '#112233', signIn: 'Please sign in.'}")
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark"); pg = ctx.new_page(); pg.goto(f_prev.as_uri()); pg.wait_for_timeout(150); pg.click("#ct-btn"); pg.wait_for_timeout(100); ct_fields(pg)
    pv = pg.eval_on_selector("#ct-pop .ct-prev .pvb", "e => { const s = getComputedStyle(e); return [s.fontStyle, s.color, s.fontFamily.split(',')[0].trim()]; }")
    rs = pg.eval_on_selector("#ct-reset", "e => { const s = getComputedStyle(e); return [s.fontStyle, s.color]; }")
    check("another app: a button in the preview strip keeps the app's own font and color (the panel's button rule does not reach the preview)", pv[0] == "italic" and pv[1] == "rgb(255, 0, 170)" and "serif" in pv[2].lower(), pv)
    check("another app: the panel's own buttons still take the panel's font and the body text color", rs == ["normal", "rgb(232, 238, 244)"], rs)
    pg.fill("#ct-h-bg", "zzz"); pg.press("#ct-h-bg", "Tab"); pg.wait_for_timeout(60)
    check("another app: cfg.text replaces the note at the end of the panel and the example in the six-digits hint", pg.inner_text(".ct-small") == "A note of the other app." and pg.inner_text("#ct-n-bg") == "Use six digits like #112233.", (pg.inner_text(".ct-small"), pg.inner_text("#ct-n-bg")))
    ctx.close()
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark"); pg = ctx.new_page(); pg.goto(f_full.as_uri()); pg.wait_for_timeout(150); pg.click("#ct-btn"); pg.wait_for_timeout(100); ct_fields(pg)
    pg.fill("#ct-h-bg", "zzz"); pg.press("#ct-h-bg", "Tab"); pg.wait_for_timeout(60)
    check("another app without cfg.text: the neutral note and the neutral example hex", pg.inner_text(".ct-small") == "Dark theme only. The look you apply is kept in this browser." and pg.inner_text("#ct-n-bg") == "Use six digits like #4a90d9.", (pg.inner_text(".ct-small"), pg.inner_text("#ct-n-bg")))
    ctx.close()
    ctx = br.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark"); pg = ctx.new_page(); pg.goto(CT_FILES["board"].as_uri()); pg.wait_for_timeout(150); ct_show(pg); pg.click("#ct-btn"); pg.wait_for_timeout(100)
    check("stackshot: the note at the end of the panel is stackshot's own wording (passed in cfg.text), unchanged", pg.inner_text(".ct-small") == _ctm.TEXT["note"] and "fleet tool" in pg.inner_text(".ct-small"), pg.inner_text(".ct-small"))
    ctx.close()
    br.close()
print(f"ok: phone width check, {len(ran)} checks" if not fails else f"{len(fails)} check(s) failed"); sys.exit(1 if fails else 0)
