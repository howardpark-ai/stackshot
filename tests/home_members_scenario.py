"""Scenario test for the home page per signed-in member (home.py, ui/render.py, web/board_home.py, routes/board_pages.py, app.py) — made-up data, a temp folder, no live store, no network.

One fixture store is drawn for a board of one member and for a board of two (member-a, member-b with the alias MB; scribe-agent acts for member-a, mail-agent for member-b). Covers:

  * one member (the old keys, and one [[members]] entry that also lists agents, with and without a viewer): the counts and the four lists are byte for byte what
    tests/home_members.snapshot.json holds, in English and in a second language. The snapshot was written by this suite with --write from the code BEFORE the home page knew a viewer;
  * two members, drawn for each: Your move holds only what names the viewer (a stored mover, a name or alias that opens a line of next); another member's move is listed first under Waiting,
    oldest first, with the age, "<member> picks it up · on <member>'s move", its question or next step, and no form, draft or command to copy; On agent is the same for both, a session that
    acts as a member saying "acts for <member>" (a hand-off not yet taken and a session named by its id too); an outside wait names the member it is for, in the viewer's color only for the
    viewer; the count cards follow the viewer; nobody, a stranger and a session get the page every member shares;
  * the server: each signed-in member is served their own kept draw, per language, never another's; a drop clears every draw; the render stamp and the background draw are the viewer's; the
    kept draws are bounded, the one used longest ago going first;
  * a wait that ends on a member's move turns to the member who picks it up (the stored mover, else a line of next), not to the first member; with one member nothing more is stored;
  * the config: agents is checked at start and doctor says when several members list none.

    tests/run-suite home_members            -> exit 0 / 1
    tests/run-suite home_members --write    -> write the snapshot again (after a deliberate change of what a board of one member shows)"""
import contextlib, datetime, json, logging, os, pathlib, re, subprocess, sys, threading, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="home-members-"); T = pathlib.Path(tmp)
SNAPSHOT = pathlib.Path(SCR, "home_members.snapshot.json")
WRITE = "--write" in sys.argv[1:]
BOARD = "https://board.example.org"
ADA, BEA = "member-a@example.org", "member-b@example.org"
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
toml = toml.replace('session_view = ""', 'session_view = "https://fleet.example.org/#s={name}"', 1); assert "fleet.example.org" in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{ADA}"]'), (r'(?m)^panel = true', 'panel = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
toml = _instance.set_person(toml, "member-a")
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site","secrets", "touch", "brain/projects", "locales"): (T / d).mkdir(parents=True)

ZONE = datetime.timezone(datetime.timedelta(hours=4))
NOW = datetime.datetime(2031, 3, 12, 10, 0, tzinfo=ZONE)      # far ahead of any real clock: no wait of the fixture ever comes due by the day the suite runs
now = NOW.timestamp()
H, D = 3600.0, 86400.0
day = lambda n: (NOW + datetime.timedelta(days=n)).strftime("%Y-%m-%d")
SESS = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("alpha-main", "alpha-build", "scribe-agent", "mail-agent"), 1)}
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "box-a", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "seen": now, "url": f"https://example.invalid/{n}"} for n, u in SESS.items()}))
AGENTS = {"alpha-main": "the front", "alpha-build": "the builder", "scribe-agent": "writes as member-a", "mail-agent": "sends as member-b"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "work", "tags": [], "type": "project", "session": "alpha-main",
    "status": "active", "board": [], "board_row": False, "updated": 1, "agents": AGENTS, "back_agents": {k: v for k, v in AGENTS.items() if k != "alpha-main"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")


def item(i, subject, age, status="open", **meta):
    meta = {"owner": SESS["alpha-build"], "project": "projects/alpha", **meta}
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[work] {subject}", "description": "- A fixture item.", "status": status, "updated": now - age,
                                                    "state_updated": now - age, "confirmed": now - age, "metadata": meta}))


def ask(q):
    return f"Decide: {q} · Recommend: yes · Stakes: low · By: Fri"


OPTS = [{"label": "Ship it", "line": "Ship on Friday.", "recommended": True}, {"label": "Hold it", "line": "Wait a week.", "recommended": False}]
item(1, "ship the thing", 6 * D, needs=["decision"], mover="member-a", ask=ask("ship on Friday?"), options=OPTS, next="member-a: answer the ask above")
item(2, "pick the colour", 3 * D, needs=["decision"], ask=ask("blue or green?"), next="member-a: decide the colour")
item(3, "review the guide", 5 * D, state="your-step", mover="member-b", step="Run `fleet check box-a --now` and say done", next="member-b: read the guide and send notes", draft="Dear reader, the guide is ready.")
item(4, "name the board", 2 * D, needs=["decision"], mover="member-b", ask=ask("what should the board be called?"), options=OPTS, next="member-b: answer the ask above", draft="A second text to paste.")
item(5, "sign the form", 1 * D, needs=["decision"], next="MB: sign it")
item(6, "send the numbers", 4 * D, state="your-step", mover="member-a", step="Run `fleet send box-a --all` and say done", next="member-a: send the numbers", draft="The numbers, ready to paste.")
item(10, "build the page", 7 * D, needs=["alpha-build"], mover="alpha-build", next="alpha-build: build it")
item(11, "write the weekly note", 5 * H, needs=["scribe-agent"], mover="scribe-agent", next="scribe-agent: draft the note")
item(12, "answer the vendor", 4 * H, needs=["mail-agent"], mover="mail-agent", next="mail-agent: reply", handoff={"to": "mail-agent", "from": "alpha-main", "at": now - 4 * H, "delivered_at": now - 3 * H, "taken_at": None})
item(13, "book the room", 3 * H, needs=[SESS["scribe-agent"]], mover=SESS["scribe-agent"], next="scribe-agent: book it")
item(14, "release the fix", 2 * H, needs=["scribe-agent"], mover="scribe-agent", next="scribe-agent: release it")
item(20, "invite on the day", 2 * D, wait_kind="time", until=day(3), mover="alpha-build", next="alpha-build: send the invite")
item(21, "the review result", 9 * D, needs=["external"], wait_kind="relay", wait_event="the review result", ask_by=day(5), mover="member-b", next="alpha-build: check the status")
item(22, "the bank reply", 8 * D, needs=["external"], wait_kind="relay", wait_event="the bank reply", ask_by=day(6), next="member-b: forward it when it comes")
item(23, "the landlord reply", 8 * D, needs=["external"], wait_kind="relay", wait_event="the landlord reply", ask_by=day(7), next="alpha-build: read it")
item(30, "shipped last week", 2 * D, status="completed", outcome="done", reason="it shipped", needs=[])

fails, ran = [], []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""), flush=True)


@contextlib.contextmanager
def group(name):
    """A part of the suite that raises is a failed check of its own name, and the parts after it still run."""
    try:
        yield
    except Exception as e:  # noqa: BLE001
        check(f"{name}: ran to its end", False, f"{type(e).__name__}: {e}")


sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.core import config as _cfg
from stackshot.web import i18n
from stackshot.web.ui import render as r2, releasing

releasing._run = lambda argv: ""                                   # the release queue is the host's systemd units: none are read
r2.Board.queued_release_ids = lambda self: {"a14"}                 # one item stands in the release queue
LOC = T / "locales"
(LOC / "ko.json").write_text(json.dumps({k: f"[x:{v}]" for k, v in i18n.EN.items() if not k.startswith(("date.", "age."))}), encoding="utf-8")      # a second language with no words of one: the English text in a marker
_cfg.CFG.setdefault("ui", {})["locale_dir"] = str(LOC)
LANGS = ("en", "ko")


def blocks(page):
    """The parts of the home page a member's reading can change: the count cards and the four lists."""
    cards = page[page.index('<nav class="hcards"'):]
    cards = cards[:cards.index("</nav>") + len("</nav>")]
    lists = page[page.index('<section id="your-move">'):page.index("</main>")]
    return cards + "\n" + lists


def draw(lang="en", **kw):
    """The home page drawn at the fixture's clock."""
    real = time.time
    time.time = lambda: now
    try:
        with i18n.use(lang):
            return r2.Board(str(T / "store"), now=NOW, **kw).html()
    finally:
        time.time = real


if WRITE:
    SNAPSHOT.write_text(json.dumps({lang: blocks(draw(lang)).split("\n") for lang in LANGS}, indent=0, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"wrote {SNAPSHOT}")
    sys.exit(0)

from stackshot.core import members
from stackshot.model import model
from stackshot.web import board_home, home, server
from stackshot.web import publish as _web_publish
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route
from stackshot.web.auth import signin as _signin
from stackshot.web.routes import board_pages
from stackshot.web import uiprefs
from starlette.testclient import TestClient

_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None


def section(page, sid):
    i = page.index(f'<section id="{sid}">')
    j = page.find('<section id="', i + 10)
    return page[i:j if j > 0 else page.index("</main>")]


def ids(page, sid):
    return [int(x) for x in re.findall(r'<li[^>]*\bid="task-a-(\d+)"', section(page, sid))]


def row(page, i):
    """The one row of item `i` (from its <li> to the next row or the end of its list)."""
    m = re.search(rf'<li[^>]*\bid="task-a-{i}"', page)
    if not m:
        return ""
    rest = page[m.end():]
    ends = [x for x in (rest.find('<li class="irow'), rest.find('<section id="'), rest.find("</main>")) if x >= 0]
    return m.group(0) + rest[:min(ends)]


def who(page, i):
    m = re.search(r'<div class="ir-who">(.*?)</div>', row(page, i), re.S)
    return m.group(1) if m else ""


def plain(h):
    return " ".join(re.sub(r"<[^>]+>", "", h).replace("↗", "").split())


def counts(page):
    return [int(x) for x in re.findall(r'<a class="hcard[^"]*"[^>]*><b>(\d+)</b>', page)]


SNAP = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
ONE = [{"name": "member-a", "emails": [ADA], "agents": ["scribe-agent"]}]
TWO = [{"name": "member-a", "emails": [ADA], "agents": ["scribe-agent"]}, {"name": "member-b", "aliases": ["MB"], "emails": [BEA], "agents": ["Mail-Agent"]}]

# ---- 1. one member: byte for byte what it was
with group("one member"):
    for lang in LANGS:
        want = "\n".join(SNAP[lang])
        got = blocks(draw(lang))
        check(f"one member, old keys, {lang}: the counts and the lists are the snapshot's bytes", got == want, next(((a, b) for a, b in zip(got.split("\n"), SNAP[lang]) if a != b), (len(got), len(want))))
        check(f"one member, old keys, a viewer named, {lang}: the snapshot's bytes", blocks(draw(lang, viewer="member-a")) == want)
    check("the second language's snapshot is that language's", "[x:Your move]" in "\n".join(SNAP["ko"]) and "[x:" not in "\n".join(SNAP["en"]))
    _cfg.CFG["members"] = ONE
    check("the one [[members]] entry is the board's list", [p.name for p in members.members()] == ["member-a"] and members.members()[0].agents == ("scribe-agent",))
    for lang in LANGS:
        want = "\n".join(SNAP[lang])
        check(f"one [[members]] entry with agents, {lang}: the snapshot's bytes", blocks(draw(lang)) == want)
        check(f"one [[members]] entry with agents, a viewer named, {lang}: the snapshot's bytes", blocks(draw(lang, viewer="member-a")) == want)
    check("one member: no viewer is made", model.board_viewer("member-a") == "" and model.wake_member({"mover": "member-a"}, "member-a") == "")

# ---- 2. two members
_cfg.CFG["members"] = TWO
with group("two members, the lists"):
    A, B, S = draw(viewer="member-a"), draw(viewer="member-b"), draw()
    check("A: Your move holds only what names member-a", ids(A, "your-move") == [1, 6, 2], ids(A, "your-move"))
    check("B: Your move holds only what names member-b (a stored mover, an alias opening a line of next)", ids(B, "your-move") == [3, 4, 5], ids(B, "your-move"))
    check("A: member-b's moves lead Waiting, oldest first, then the waits by end date", ids(A, "waiting-list") == [3, 4, 5, 20, 21, 22, 23], ids(A, "waiting-list"))
    check("B: member-a's moves lead Waiting, oldest first, then the waits by end date", ids(B, "waiting-list") == [1, 6, 2, 20, 21, 22, 23], ids(B, "waiting-list"))
    check("the shared page: Your move holds every member's move, oldest first", ids(S, "your-move") == [1, 3, 6, 2, 4, 5], ids(S, "your-move"))
    check("the shared page: Waiting holds the waits alone", ids(S, "waiting-list") == [20, 21, 22, 23], ids(S, "waiting-list"))
    for name, page in (("A", A), ("B", B), ("shared", S)):
        every = [i for sid in ("your-move", "agents-at-work", "queued-release", "waiting-list") for i in ids(page, sid)]
        check(f"{name}: every open item is in exactly one list", sorted(every) == [1, 2, 3, 4, 5, 6, 10, 11, 12, 13, 14, 20, 21, 22, 23], sorted(every))
    check("A: the count cards are member-a's", counts(A)[:4] == [3, 4, 1, 7], counts(A))
    check("B: the count cards are member-b's", counts(B)[:4] == [3, 4, 1, 7], counts(B))
    check("the shared page's count cards count every member's move", counts(S)[:4] == [6, 4, 1, 4], counts(S))
    check("each list's heading counts its rows", all(f'<span class="count">{len(ids(p, sid))}</span>' in section(p, sid) for p in (A, B) for sid in ("your-move", "waiting-list")))

with group("two members, another member's row"):
    check("A: an ask of member-b's reads who picks it up and whose move it is", plain(who(A, 4)) == "member-b picks it up · on member-b's move", who(A, 4))
    check("…the name drawn as the mockup draws it, not in the viewer's color", who(A, 4).startswith('<span class="hwho">member-b</span> picks it up'), who(A, 4))
    check("B: member-a's row names member-a, not the viewer", who(B, 1).startswith('<span class="hwho">member-a</span> picks it up') and plain(who(B, 1)).endswith("on member-a's move"), who(B, 1))
    for i, p in ((3, A), (4, A), (5, A), (1, B), (2, B), (6, B)):
        check(f"another member's row a{i}: no answer form, button, box or token", not any(x in row(p, i) for x in ("<form", "<button", "<textarea", 'name="token"')), row(p, i))
        check(f"another member's row a{i}: the waiting color and the age, no end date", 'data-st="wait"' in row(p, i) and "ir-end" not in row(p, i) and "data-ts=" in row(p, i), row(p, i))
    check("A: another member's ask shows its question", '<span class="hnext hq">what should the board be called?</span>' in row(A, 4), row(A, 4))
    check("A: another member's step shows the next line, its opener left out", '<span class="hnext">read the guide and send notes</span>' in row(A, 3), row(A, 3))
    check("A: …with no command block to copy, no draft and no Done", "fleet check" not in row(A, 3) and "Dear reader" not in row(A, 3) and "A second text" not in row(A, 4), (row(A, 3), row(A, 4)))
    check("B: the same items on their own member's page have their form, step and draft", "<form" in row(B, 4) and "<form" in row(B, 3) and "fleet check box-a --now" in row(B, 3) and "Dear reader" in row(B, 3) and "A second text" in row(B, 4))
    check("a member's own row has its form on Your move", "<form" in row(A, 1) and "picks it up" not in row(A, 1) and "fleet send box-a --all" in row(A, 6) and "The numbers, ready to paste." in row(A, 6))
    check("…and member-b gets member-a's step without its command or draft", "fleet send" not in row(B, 6) and "ready to paste" not in row(B, 6) and '<span class="hnext">send the numbers</span>' in row(B, 6), row(B, 6))
    check("the shared page has no 'on … move' row", "&#x27;s move" not in S and "'s move" not in blocks(S))

with group("two members, On agent and the sessions that act as a member"):
    check("On agent is the same for both members", section(A, "agents-at-work") == section(B, "agents-at-work"), (section(A, "agents-at-work")[:300], section(B, "agents-at-work")[:300]))
    check("Queued for release is the same for both members", section(A, "queued-release") == section(B, "queued-release"))
    check("a session that acts as member-a says so after its name", plain(who(A, 11)) == "scribe-agent · acts for member-a" and '<span class="dim">acts for member-a</span>' in who(A, 11), who(A, 11))
    check("…to the member it acts for as to the other", plain(who(B, 11)) == "scribe-agent · acts for member-a", who(B, 11))
    check("a hand-off not yet taken says it too, the agents name read in any case", plain(who(A, 12)) == "handed to mail-agent, not yet taken · acts for member-b", who(A, 12))
    check("a mover stored as the session's id is matched by its name", plain(who(A, 13)) == "scribe-agent · acts for member-a", who(A, 13))
    check("a Queued for release row says it as well", ids(A, "queued-release") == [14] and "acts for member-a" in who(A, 14), who(A, 14))
    check("every other session is the board's: no 'acts for'", plain(who(A, 10)) == "alpha-build", who(A, 10))
    check("a wait an ordinary session picks up has no 'acts for'", "acts for" not in who(A, 20))
    check("the shared page says no 'acts for'", "acts for" not in S)
    _cfg.CFG["members"] = [{**TWO[0], "agents": [SESS["scribe-agent"]]}, TWO[1]]
    check("agents may name a session by its id", plain(who(draw(viewer="member-b"), 11)) == "scribe-agent · acts for member-a")
    _cfg.CFG["members"] = TWO

with group("two members, outside waits"):
    check("an outside wait stored for member-b is picked up by member-b on member-a's page", who(A, 21).startswith('<span class="hwho">member-b</span> picks it up · watched by'), who(A, 21))
    check("…and in member-b's own color on member-b's page", who(B, 21).startswith('<span class="hwho own">member-b</span> picks it up'), who(B, 21))
    check("an outside wait whose next line names member-b is picked up by member-b", who(A, 22).startswith('<span class="hwho">member-b</span> picks it up'), who(A, 22))
    check("an outside wait that names no member stays the first member's", who(A, 23).startswith('<span class="hwho own">member-a</span>') and who(B, 23).startswith('<span class="hwho">member-a</span>'), (who(A, 23), who(B, 23)))
    check("a wait keeps its end date in the slot", "ir-end" in row(A, 21) and "ir-end" in row(A, 20))

with group("two members, who is a viewer"):
    base = blocks(S)
    for name in ("stranger", "scribe-agent", "", "alpha-build", "the owner"):
        check(f"viewer {name!r} is no member: the page every member shares", blocks(draw(viewer=name)) == base)
    check("a viewer named by an alias or in other case is that member", blocks(draw(viewer="mb")) == blocks(B) and blocks(draw(viewer=" Member-B ")) == blocks(B))
    check("the two members' pages differ from each other and from the shared one", len({blocks(A), blocks(B), base}) == 3)

with group("two members, the second language"):
    KA, KB = draw("ko", viewer="member-a"), draw("ko", viewer="member-b")
    check("the new row words come from the language's table", plain(who(KA, 4)) == "[x:member-b picks it up · on member-b's move]" and "[x:acts for member-a]" in who(KA, 11), (who(KA, 4), who(KA, 11)))
    check("the same lists in the second language", all(ids(KA, s) == ids(A, s) and ids(KB, s) == ids(B, s) for s in ("your-move", "agents-at-work", "queued-release", "waiting-list")))

with group("a project's page keeps the shared reading"):
    b = r2.Board(str(T / "store"), now=NOW)
    lists = b.home_lists()
    check("a Board with no viewer lists every member's move under Your move", [r["gid"] for r, _m in lists[home.YOUR_MOVE]] == ["a1", "a3", "a6", "a2", "a4", "a5"])

with group("the words of the model"):
    check("names_member: a name or an alias of that member only", model.names_member("MB", "member-b") and not model.names_member("member-a", "member-b") and not model.names_member("scribe-agent", "member-a"))
    check("is_owner still means any member", model.is_owner("member-a") and model.is_owner("mb") and not model.is_owner("scribe-agent"))
    alive_b = model.Model(model.ALIVE, mover="member-b")
    check("list_of: no viewer, the viewer, another viewer, a session", [home.list_of(alive_b), home.list_of(alive_b, "member-b"), home.list_of(alive_b, "member-a"), home.list_of(model.Model(model.ALIVE, mover="scribe-agent"), "member-a")]
          == [home.YOUR_MOVE, home.YOUR_MOVE, home.WAITING, home.AGENTS])

# ---- 3. the server: each member's own kept draw
COOKIE = {e: _signin._ui_sign(json.dumps({"email": e, "exp": time.time() + 3600})) for e in (ADA, BEA, "stranger@example.org")}
with group("the server"):
    with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
        def get(path="/", person=ADA):
            c.cookies.clear()
            if person: c.cookies.set(_signin._UI_COOKIE, COOKIE[person])
            return c.get(path, follow_redirects=False)

        board_home._board_home_drop()
        first = get("/", ADA)
        second = get("/", BEA)
        check("the route serves member-a their own home", first.status_code == 200 and ids(first.text, "your-move") == [1, 6, 2], (first.status_code, first.text[:200]))
        check("…then member-b theirs, never member-a's kept draw", second.status_code == 200 and ids(second.text, "your-move") == [3, 4, 5], second.status_code)
        again = get("/", ADA)
        check("…and member-a their kept draw again", ids(again.text, "your-move") == [1, 6, 2] and again.text == first.text)
        slots = board_home._BOARD_HOME_VIEWERS
        check("the draws are kept by language and viewer", set(slots) == {("en", "member-a"), ("en", "member-b")} and ids(slots[("en", "member-a")]["html"], "your-move") == [1, 6, 2]
              and ids(slots[("en", "member-b")]["html"], "your-move") == [3, 4, 5], list(slots))
        held = slots[("en", "member-a")]["html"]
        get("/", ADA)
        check("a second read inside the keep time draws nothing", slots[("en", "member-a")]["html"] is held)
        uiprefs.set_lang(ADA, "ko")
        ko_a, en_b = get("/", ADA).text, get("/", BEA).text
        check("a language switch: member-a reads their own home in it", "[x:Your move]" in ko_a and ids(ko_a, "your-move") == [1, 6, 2] and ("ko", "member-a") in slots, ko_a[:200])
        check("…member-b still reads theirs in English", "[x:" not in blocks(en_b) and ids(en_b, "your-move") == [3, 4, 5])
        uiprefs.set_lang(BEA, "ko")
        ko_b = get("/", BEA).text
        check("…and in the other language member-b's own, not member-a's", "[x:Your move]" in ko_b and ids(ko_b, "your-move") == [3, 4, 5])
        uiprefs.set_lang(ADA, "en"); uiprefs.set_lang(BEA, "en")
        back = get("/", ADA).text
        check("back to English: member-a's English draw", "[x:" not in blocks(back) and ids(back, "your-move") == [1, 6, 2])
        _cfg.CFG["auth"]["ui_open"] = True
        board_home._board_home_drop()
        get("/", ADA)
        nobody = get("/", None)
        check("nobody signed in: the shared page, from its own slot", nobody.status_code == 200 and ids(nobody.text, "your-move") == [1, 3, 6, 2, 4, 5] and ids(board_home._BOARD_HOME["html"], "your-move") == [1, 3, 6, 2, 4, 5], nobody.status_code)
        stranger = get("/", "stranger@example.org")
        check("a signed address no member has: the shared page", stranger.status_code == 200 and ids(stranger.text, "your-move") == [1, 3, 6, 2, 4, 5], stranger.status_code)
        check("…and member-b after it still reads their own", ids(get("/", BEA).text, "your-move") == [3, 4, 5])
        board_home._board_home_drop()
        check("a drop clears every viewer's draw", slots and all(s["at"] == 0.0 for s in slots.values()) and board_home._BOARD_HOME["at"] == 0.0, [(k, s["at"]) for k, s in slots.items()])
        # the render stamp and the background draw are the viewer's own
        def drawn():
            for t in threading.enumerate():
                if t.name == "home-draw":
                    t.join(60)

        slots.clear()
        get("/", ADA)
        drawn()
        go, real_html = threading.Event(), r2.Board.html
        r2.Board.html = lambda self, *a, **k: (go.wait(30), real_html(self, *a, **k))[1]      # a background draw is held until the poll has answered
        try:
            st = get("/render-stamp", BEA)
            check("the render stamp of a member with no draw yet is not another's", st.status_code == 503, (st.status_code, st.text))
        finally:
            go.set(); drawn()
            r2.Board.html = real_html
        got = slots.get(("en", "member-b"), {}).get("html")
        check("…and the draw it started in the background is that member's", bool(got) and ids(got, "your-move") == [3, 4, 5], list(slots))
        if got:
            for who_, stamp in (("member-a", 111), ("member-b", 222)):
                slots[("en", who_)].update(html=f"<p>{who_}</p>", drawn=stamp, at=time.time(), sig=i18n.signature())
            got_ts = [get("/render-stamp", p).json().get("ts") for p in (ADA, BEA)]
            check("the render stamp answers for the viewer's own draw", got_ts == [111, 222], got_ts)

with group("the kept draws are bounded"):
    board_home._BOARD_HOME_VIEWERS.clear()
    top = board_home._VIEWER_SLOTS_MAX
    check("the bound is a small number", 2 <= top <= 64, top)
    for n in range(top):
        board_home._board_home_slot("en", f"p{n}")
    kept = board_home._board_home_slot("en", "p0")      # used again: now the newest
    for n in range(3):
        board_home._board_home_slot("ko", f"q{n}")
    keys = list(board_home._BOARD_HOME_VIEWERS)
    check("the viewers' draws never exceed the bound", len(keys) == top, len(keys))
    check("the one used longest ago goes first, a slot read again stays", ("en", "p0") in keys and not any(("en", f"p{n}") in keys for n in (1, 2, 3)) and ("en", "p4") in keys, keys[:6])
    check("a slot read again is the same slot", board_home._board_home_slot("en", "p0") is kept)
    check("the shared slots are outside the bound", board_home._board_home_slot() is board_home._BOARD_HOME and board_home._board_home_slot("ko") is board_home._BOARD_HOME_OTHER["ko"])
    board_home._BOARD_HOME_VIEWERS.clear()

# ---- 4. a wait that ends on a member's move
with group("a wait that ends"):
    from stackshot.service import watching, telling
    telling.PUSH = [sys.executable, "-c", "pass"]

    def fire(i, cause):
        watching.watch_fire(f"a{i}", cause, time.time(), {})
        return json.loads((T / f"store/a/{i}.json").read_text(encoding="utf-8"))["metadata"]

    past = (datetime.datetime.now(ZONE) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    item(41, "b's outside wait ends", D, needs=["external"], wait_kind="relay", wait_event="the answer", ask_by=past, mover="member-b", next="alpha-build: check it")
    m = fire(41, "relay")
    check("a relay's day turns to the member who picks it up", m.get("needs") == ["decision"] and m.get("mover") == "member-b" and (m.get("woke") or {}).get("to") == "member-b", m)
    page = draw(viewer="member-b"); other = draw(viewer="member-a")
    check("…and is on that member's Your move, not the first member's", 41 in ids(page, "your-move") and 41 in ids(other, "waiting-list") and 41 not in ids(other, "your-move"), (ids(page, "your-move"), ids(other, "your-move")))
    item(42, "a wait a session picks up, b named", D, needs=["external"], wait_kind="relay", wait_event="the answer", ask_by=past, mover="alpha-build", next="MB: forward it")
    m = fire(42, "relay")
    check("a relay a session picks up asks the member its next line names", m.get("mover") == "member-b" and m.get("then") == "alpha-build" and m["woke"]["to"] == "member-b", m)
    item(43, "b picks up a dated wait", D, wait_kind="time", until=past, mover="member-b", next="alpha-build: then this")
    m = fire(43, "time")
    check("a dated wait a member picks up turns to that member", m.get("mover") == "member-b" and m["woke"]["to"] == "member-b", m)
    item(45, "b picks it up, stored under the old key", D, needs=["external"], wait_kind="relay", wait_event="the answer", ask_by=past, post_wake_mover="member-b", next="alpha-build: check it")
    m = fire(45, "relay")
    check("a picker stored under the old key is the member asked", m.get("mover") == "member-b" and m["woke"]["to"] == "member-b" and "post_wake_mover" not in m, m)
    item(46, "a dated wait, its picker under the old key", D, wait_kind="time", until=past, post_wake_mover="member-b", next="alpha-build: then this")
    m = fire(46, "time")
    check("…on a dated wait too", m.get("mover") == "member-b" and m["woke"]["to"] == "member-b" and "post_wake_mover" not in m, m)
    _cfg.CFG["members"] = ONE
    item(44, "one member's outside wait ends", D, needs=["external"], wait_kind="relay", wait_event="the answer", ask_by=past, mover="member-a", next="alpha-build: check it")
    m = fire(44, "relay")
    check("one member: no mover is stored, the item is the member's as before", "mover" not in m and m["needs"] == ["decision"] and m["woke"]["to"] == "member-a", m)
    _cfg.CFG["members"] = TWO

# ---- 5. the config
with group("the config"):
    bad = lambda rows: members.problems({"members": rows})
    check("agents as listed is fine", bad(TWO) == [], bad(TWO))
    check("agents that is no list is told", any("agents is not a list" in x for x in bad([{"name": "member-a", "agents": "scribe-agent"}])), bad([{"name": "member-a", "agents": "scribe-agent"}]))
    check("a session in agents that is no text is told", any("agents item 1 is not text" in x for x in bad([{"name": "member-a", "agents": [3]}])))
    two_say = bad([{"name": "member-a", "agents": ["scribe-agent"]}, {"name": "member-b", "agents": ["Scribe-Agent"]}])
    check("a session acts as one person", len(two_say) == 1 and "already in the agents of entry 1" in two_say[0], two_say)
    named = bad([{"name": "member-a", "agents": ["mb"]}, {"name": "member-b", "aliases": ["MB"]}])
    check("a member's name or alias is no session", len(named) == 1 and "name or an alias of a member" in named[0], named)
    check("a session written twice in one entry is harmless", bad([{"name": "member-a", "agents": ["scribe-agent", "scribe-agent"]}]) == [] and members.build({"members": [{"name": "member-a", "agents": ["x", " X "]}]})[0].agents == ("x",))
    note = lambda rows: [x for x in _cfg.notes({**_cfg.CFG, "members": rows}) if "agents" in x and "[[members]]" in x]
    check("doctor says when several members list no agents", len(note([{"name": "member-a"}, {"name": "member-b"}])) == 1, note([{"name": "member-a"}, {"name": "member-b"}]))
    check("…and not when one lists some, or says none", note(TWO) == [] and note([{"name": "member-a", "agents": []}, {"name": "member-b"}]) == [] and note([{"name": "member-a"}]) == [])

print(f"\nhome_members: {len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else "\nfailed: " + "; ".join(fails)))
sys.exit(1 if fails else 0)
