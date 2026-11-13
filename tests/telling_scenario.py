"""Scenario test for the telling (stackshot/service/telling.py) — a scratch store, fixture items, no server socket, no network, no push, no model call.

The telling is who hears of a write: the notices a create, an update or a close sends to the item's mover, the sessions its needs name, its observers, the project's keeper and the
router, with the reply line the writer reads. It moved out of server.py into service/telling.py and must behave as it did: the same notices to the same sessions in the same order,
the same reply lines. The expected values of the cases below were taken from main's own telling (server.py `_tell_*`, `_holder` and the rest, run from a checkout of main with
`TELLING_MAIN=1 tests/run-suite telling`, which prints what each case gives there), never from this code. This suite holds the new code to them, and checks the shape of the move.

  1  keepers        who a notice goes to: the page's keeper, the stand-in, the builder, a front agent, the holder of an item and the words that say so
  2  notices        every notice a write sends, with each delivery replaced by a recorder (what was sent to whom, in what order) and the reply line the writer gets
  3  hold           the hand-back line held for a few minutes, sent by the minute tick, dropped by a close; a notice held for a background agent's next turn; the failed-delivery record
  4  flags          the per-write flags the telling reads on service/writes.py (a script's terminal-prompt row tells nobody) and the thread-locals the telling keeps itself
  5  hooks          a notice with no hooks installed is refused; the server's table holds every hook, and a hook that is a function is looked up on the server when the notice is told
  6  shape          telling.py imports no web/ or audit/ module and has no late import; server.py defines none of the moved names and re-exports none; the services call the telling on its module;
                    no thread-local is left in web/

    tests/run-suite telling        -> exit 0 / 1"""
import ast, contextlib, dataclasses, datetime as dt, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
MAIN = os.environ.get("TELLING_MAIN") == "1"            # run against a checkout of main, where the telling still sits in server.py as `_tell_*`: print what each case gives there
tmp = _scratch.mkdtemp(prefix="telling-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK)

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml      # never the host's session store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1                 # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                           # an isolated HOME
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state", "transcripts/-home-x"): (T / d).mkdir(parents=True)
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-owner", "home-stew", "marsh-builder", "quill-agent", "home-other", "home-watcher"), 1)}
(T / "store/anchors.json").write_text("{}"); (T / "store/next-id").write_text("900")
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/quill": {"title": "Quill", "name": "Quill", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active",
                                                                               "board": [], "board_open": 0, "agents": {"quill-agent": "the front", "marsh-builder": "the back"}, "back_agents": {"marsh-builder": "the back"}}}}))
(T / "brain/projects/quill.md").write_text("---\ntitle: Quill\ndisplay-name: home-stew\nagents:\n  quill-agent: the front\n  background:\n    marsh-builder: the back\n---\n\n# Quill\n")
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()})); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1500]}" if got is not None else ""))

from fastmcp.exceptions import ToolError
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.github import ghsync as _gh
from stackshot.web import server
if not MAIN: from stackshot.service import telling, writes

MOVED = {      # the telling's name here -> the name it had on server.py (a function that is public here has its old underscore name there)
    "CLOSE_WAS": "_CLOSE_WAS", "FALLBACK_CACHE": "_FALLBACK_CACHE", "FRONT_HINT": "_FRONT_HINT", "FRONT_TAG_KIND": "_FRONT_TAG_KIND",
    "HANDBACK_HOLD_S": "HANDBACK_HOLD_S", "HO_STATE": "_HO_STATE", "MENTIONED": "_MENTIONED", "OWNER_HEARD": "_OWNER_HEARD", "PRESENCE_MINUTES": "PRESENCE_MINUTES",
    "PUSH": "_PUSH", "_FORYOU_FELL": "_FORYOU_FELL", "_FRONT_QUIET": "_FRONT_QUIET", "_HANDBACK_LOCK": "_HANDBACK_LOCK", "_HELD_LINE": "_HELD_LINE",
    "_MENTION_LINES_MAX": "_MENTION_LINES_MAX", "_OWNER_HEARD_WINDOW": "_OWNER_HEARD_WINDOW", "_UNDELIVERED_KEEP": "_UNDELIVERED_KEEP", "_asks_of": "_asks_of",
    "_closed_by": "_closed_by", "_done_close": "_done_close", "_front_board_line": "_front_board_line", "_front_held_log": "_front_held_log",
    "_handback_file": "_handback_file", "_handback_hold": "_handback_hold", "_handback_minutes": "_handback_minutes", "_ho_told": "_ho_told",
    "_hold_project": "_hold_project", "_mentions_ref": "_mentions_ref", "_owner_is_session": "_owner_is_session", "_relay_push": "_relay_push",
    "_stamped_at": "_stamped_at", "auto_mover": "_auto_mover", "close_owner_notice": "_close_owner_notice", "fallback_mover": "_fallback_mover",
    "front_gate": "_front_gate", "front_keeper": "_front_keeper", "front_sender": "_front_sender", "front_verdict": "_front_verdict", "gate_result": "_gate_result",
    "handback_drop": "_handback_drop", "handback_hold_s": "_handback_hold_s", "handback_read": "_handback_read", "handback_send": "_handback_send",
    "handback_tick": "_handback_tick", "handback_write": "_handback_write", "handoff_notify": "_handoff_notify", "held_by": "_held_by", "hold_notice": "_hold_notice",
    "holder": "_holder", "keeper_words": "_keeper_words", "live_pass": "_live_pass", "mentions_reply": "_mentions_reply", "next_head": "_next_head",
    "no_front": "_no_front", "notice_link": "_notice_link", "notice_to": "_notice_to", "owner_reached": "_owner_reached", "page_keeper": "_page_keeper",
    "pilot_charge": "_pilot_charge", "pilot_keeper": "_pilot_keeper", "pilot_relay": "_pilot_relay", "pilot_relay_many": "_pilot_relay_many",
    "presence_here": "_presence_here", "presence_minutes": "_presence_minutes", "project_keeper": "_keeper", "push_noted": "_push_noted", "quiet_line": "_quiet",
    "record_undelivered": "_record_undelivered", "stand_in_keeper": "_stand_in_keeper", "tell_check_closed": "_tell_check_closed",
    "tell_close_mentions": "_tell_close_mentions", "tell_close_owner": "_tell_close_owner", "tell_comment": "_tell_comment", "tell_decided": "_tell_decided",
    "tell_handback": "_tell_handback", "tell_kind": "_tell_kind", "tell_needed": "_tell_needed", "tell_observers": "_tell_observers", "tell_or_hold": "_tell_or_hold",
    "tell_owner": "_tell_owner", "tell_owner_change": "_tell_owner_change", "tell_owner_check_closed": "_tell_owner_check_closed",
    "tell_owner_close": "_tell_owner_close", "tell_owner_on": "_tell_owner_on", "tell_wait_failed": "_tell_wait_failed", "tell_woken": "_tell_woken",
    "then_label": "_then_label", "then_part": "_then_part", "touched": "_touched", "writer_charge": "_writer_charge", "writers_since": "_writers_since",
}

def _own(name): return MOVED.get(name, name) if MAIN else name
class _Owner:
    """The telling by its name here: telling.x in this code, server._x (or the name it had) on main."""
    def __getattr__(self, name): return getattr(server if MAIN else telling, _own(name))
G = _Owner()

@contextlib.contextmanager
def patched(owner, **kv):
    """Names of a module (or of the telling's owner, `G`) replaced for a case, put back after."""
    mod = (server if MAIN else telling) if owner is G else owner
    name = (lambda n: _own(n)) if owner is G else (lambda n: n)
    old = {k: getattr(mod, name(k)) for k in kv}
    for k, v in kv.items(): setattr(mod, name(k), v)
    try: yield
    finally:
        for k, v in old.items(): setattr(mod, name(k), v)
def srv(**kv): return patched(server, **kv)                    # what the hooks look up on the server when a notice is told
FLAGMOD = server if MAIN else writes           # where the per-write flags live: the server on main (`_TERMINAL_ROW`), service/writes.py here (`TERMINAL_ROW`)
def flagname(n): return ("_" + n) if MAIN else n
@contextlib.contextmanager
def terminal_row(on=True):
    o = getattr(FLAGMOD, flagname("TERMINAL_ROW")); old = getattr(o, "on", False); o.on = on
    try: yield
    finally: o.on = old

NOW = time.time()
EPOCH = re.compile(r"\b\d{10}(?:\.\d+)?\b")
def scrub(v):
    """A result with its clocks and random ids masked (a time in the fixture's own run is never the same twice), so it compares with what main gave."""
    if isinstance(v, float) and v > 1e9: return "<t>"
    if isinstance(v, str): return re.sub(r"(?<=notice )[0-9a-f]{6}", "<id>", EPOCH.sub("<t>", v))
    if isinstance(v, (list, tuple)): return type(v)(scrub(x) for x in v)
    if isinstance(v, (set, frozenset)): return sorted(scrub(x) for x in v)
    if isinstance(v, dict): return {k: scrub(x) for k, x in v.items()}
    return v

OWNER = "Oliver"; BACK = "marsh-builder"; FRONT = "quill-agent"; KEEP = "home-stew"; OTHER = "home-other"; WATCH = "home-watcher"
PROJECT = "projects/quill"
def item(i="1", status="open", subject=None, description="- A thing", **meta):
    return {"id": i, "gid": f"a{i}", "subject": subject or f"[home] item {i}", "description": description, "status": status, "updated": NOW - 3600, "state_updated": NOW - 3600, "confirmed": NOW - 3600,
            "metadata": {"project": PROJECT, "next": f"{BACK}: do it", **meta}}
def put(i, **kw):
    it = item(str(i), **kw)
    (T / f"store/a/{i}.json").write_text(json.dumps(it), encoding="utf-8")
    return it
NAMED = _gh.shown("a5")                                        # how a close names item 5 in a notice
put(1, mover=BACK); put(2, mover=FRONT); put(3, mover=BACK, needs=[BACK]); put(4, mover=BACK, observers=[WATCH, FRONT])
put(5, status="completed", mover=BACK, outcome="done", reason="shipped")
NAMED10 = _gh.shown("a10")
put(10, mover=BACK, next=f"{BACK}: see {NAMED10}")                   # an open item that names itself
NAMED30 = _gh.shown("a30")                                      # a closed item that ten open items name: the notice lists eight of them and counts the rest
put(30, status="completed", mover=BACK, outcome="done", reason="shipped")
for _n in range(31, 41): put(_n, mover=BACK, next=f"{BACK}: wait for {NAMED30}")
put(6, mover=BACK, next=f"{BACK}: wait for {NAMED} to land"); put(7, mover=FRONT, next=f"{FRONT}: review", description=f"- waits on {NAMED}")
it_back, it_front, it_needs, it_obs = item("1", mover=BACK), item("2", mover=FRONT), item("3", mover=BACK, needs=[BACK]), item("4", mover=BACK, observers=[WATCH, FRONT])
it_owner_then = item("8", mover=OWNER, then=BACK)
it_closed = item("5", status="completed", mover="", outcome="done", reason="shipped")

CALLS = []
def _woken(gid, owner, note, tag="wake", result=None): CALLS.append(("woken", gid, owner, note, tag)); return None
def _kind(kind, *a, **kw): CALLS.append(("kind", kind, *a, kw.get("tag"))); return None
@contextlib.contextmanager
def delivery(gate=("sent", "")):
    """Every delivery replaced by a recorder (CALLS), and the front gate's verdict by `gate`: what was sent and to whom is what the case compares."""
    CALLS.clear()
    with patched(G, tell_woken=_woken, tell_kind=_kind, gate_result=lambda: gate):
        getattr(G, "OWNER_HEARD").clear(); getattr(G, "FALLBACK_CACHE").clear()
        yield
def told(thunk, gate=("sent", "")):
    """What a notice gives: its value and what it sent (each delivery in order), or the error it raised."""
    with delivery(gate):
        try: got = ("ok", scrub(thunk()), scrub(list(CALLS)))
        except Exception as e: got = ("raised", f"{e.__class__.__name__}: {e}")
    return got
def plain(thunk):
    try: return ("ok", scrub(thunk()))
    except Exception as e: return ("raised", f"{e.__class__.__name__}: {e}")
NOWANT = object()
# the cases: (what it checks, a thunk, what main's telling gave). The last value of each is what main's own `_tell_*` returned for the thunk (a run with TELLING_MAIN=1 on a checkout of main prints each WANT line).
CASES = [
    # ---- 1. keepers
    ("page_keeper: a project with front agents answers with its stand-in; a page that is none answers with nothing", lambda: plain(lambda: [G.page_keeper(PROJECT), G.page_keeper("projects/none")]), ('ok', ['quill-agent', ''])),
    ("stand_in_keeper: the builder of a project, nothing for a key that names no page", lambda: plain(lambda: [G.stand_in_keeper(PROJECT), G.stand_in_keeper("projects/none")]), ('ok', ['quill-agent', ''])),
    ("project_keeper: the project's keeper, whoever the mover is; a front mover on a page nothing names falls to its own keeper", lambda: plain(lambda: [G.project_keeper(PROJECT), G.project_keeper(PROJECT, FRONT), G.project_keeper("projects/none", FRONT), G.project_keeper("projects/none", BACK), G.project_keeper("projects/none")]), ('ok', ['quill-agent', 'quill-agent', 'quill-agent', 'marsh-builder', ''])),
    ("fallback_mover: the builder, else the -main agent; nothing for no project; the answer is cached", lambda: plain(lambda: [G.fallback_mover(PROJECT), G.fallback_mover(""), G.fallback_mover(PROJECT), G.fallback_mover("projects/none")]), ('ok', ['quill-agent', '', 'quill-agent', ''])),
    ("pilot_keeper and pilot_charge: the page's keeper and who is charged for a write", lambda: plain(lambda: [G.pilot_keeper(PROJECT), G.pilot_charge(PROJECT, OTHER), G.pilot_charge(PROJECT, KEEP), G.pilot_charge("projects/none", OTHER)]), ('ok', [('home-stew', 'name'), ('00000000-0000-4000-8000-000000000002', 'name'), ('', ''), ('', '')])),
    ("front_keeper: a front agent answers true with its keeper; a background agent false; strict says so for an unknown name too", lambda: plain(lambda: [G.front_keeper(FRONT, PROJECT), G.front_keeper(BACK, PROJECT), G.front_keeper(OTHER, PROJECT), G.front_keeper(FRONT, PROJECT, True), G.front_keeper(OTHER, PROJECT, True), G.front_keeper("", PROJECT)]), ('ok', [(True, ''), (False, ''), (False, ''), (True, ''), (False, ''), (False, '')])),
    ("front_sender, no_front and auto_mover: a front agent is no one a notice is sent to; its builder is", lambda: plain(lambda: [G.front_sender(FRONT), G.front_sender(BACK), G.front_sender(OTHER), G.no_front(FRONT, PROJECT), G.no_front(BACK, PROJECT), G.auto_mover(FRONT, PROJECT), G.auto_mover(BACK, PROJECT)]), ('ok', [True, False, False, '', 'marsh-builder', 'quill-agent', 'marsh-builder'])),
    ("held_by and holder: the mover; the `then` when the mover is the owner; the project's builder when neither; a closed item reads the item as it stood", lambda: plain(lambda: [G.held_by(it_back), G.held_by(it_front), G.held_by(it_owner_then), G.held_by(item("9", mover=OWNER)), G.holder(it_back), G.held_by(it_closed, item("5", mover=FRONT))]), ('ok', [('marsh-builder', 'mover'), ('quill-agent', 'mover'), ('marsh-builder', 'then'), ('quill-agent', 'mover'), 'marsh-builder', ('quill-agent', 'mover')])),
    ("held_by: a closed item with the close in flight on this thread reads what it was before", lambda: plain(lambda: _close_was()), ('ok', [('marsh-builder', 'mover'), 'marsh-builder', ('quill-agent', 'mover'), ('quill-agent', 'mover')])),
    ("quiet_line and then_part: the line that says a front agent is not told, and the `, then X` of a notice", lambda: plain(lambda: [G.quiet_line(it_front), G.quiet_line(it_owner_then, BACK), G.then_label(it_owner_then), G.then_part(it_owner_then), G.then_part(it_back), G.then_part(item("8", mover=BACK, then=OWNER))]), ('ok', ['\n(its mover quill-agent is a front agent: not told; the board shows it)', '\n(its then marsh-builder is a front agent: not told; the board shows it)', 'marsh-builder', ', then marsh-builder', '', ''])),
    ("keeper_words and notice_to and notice_link", lambda: plain(lambda: [G.keeper_words(PROJECT, G.page_keeper(PROJECT)), G.keeper_words(PROJECT, OTHER), G.notice_to(it_back["metadata"]), G.notice_to({"project": PROJECT}), G.notice_link("a1")]), ('ok', ['the keeper of projects/quill', 'the keeper of its page (projects/quill)', [('00000000-0000-4000-8000-000000000003', 'as its mover')], [('00000000-0000-4000-8000-000000000004', 'as its mover')], 'https://stackshot.example.com/items/a1'])),
    ("next_head: the first line the writer wrote when it wrote one, else the head of next", lambda: plain(lambda: [G.next_head({"next": f"{BACK}: a\n{OTHER}: b"}, OTHER), G.next_head({"next": f"{BACK}: a\n{OTHER}: b"}), G.next_head({}, OTHER)]), ('ok', ['marsh-builder: a', 'marsh-builder: a', ''])),
    ("owner_reached: a reply line that says the mover was reached, and the front agent's `not told` line only when the keeper or router has the write", lambda: plain(lambda: [G.owner_reached("\n(its mover x is a front agent: not told; the board shows it)", False), G.owner_reached("\n(its mover x is a front agent: not told; the board shows it)", True),
                                                                                                                                                   G.owner_reached("\n(its mover x has been told)", False), G.owner_reached("nothing", True)]), ('ok', [False, True, True, False])),
    # ---- 2. notices
    ("tell_needed: a session newly named in needs gets one notice, naming the item, the writer and the head of next", lambda: told(lambda: G.tell_needed("a1", it_back, [OTHER], BACK)), ('ok', '\n(home-other has been told the item needs it)', [('woken', 'a1', '00000000-0000-4000-8000-000000000005', "[stackshot] a1 now needs you (named in its needs by marsh-builder): [home] item 1 (projects/quill); next: marsh-builder: do it. Do your part and close it or hand it back (sender='home-other'); Your turn-end board check asks about it until then. → https://stackshot.example.com/items/a1", 'needs')])),
    ("tell_needed: never the writer; a session named twice once; the reply names who was told", lambda: told(lambda: G.tell_needed("a1", it_back, [BACK, OTHER, OTHER, WATCH], BACK)), ('ok', '\n(home-other, home-watcher have been told the item needs them)', [('woken', 'a1', '00000000-0000-4000-8000-000000000005', "[stackshot] a1 now needs you (named in its needs by marsh-builder): [home] item 1 (projects/quill); next: marsh-builder: do it. Do your part and close it or hand it back (sender='home-other'); Your turn-end board check asks about it until then. → https://stackshot.example.com/items/a1", 'needs'), ('woken', 'a1', '00000000-0000-4000-8000-000000000006', "[stackshot] a1 now needs you (named in its needs by marsh-builder): [home] item 1 (projects/quill); next: marsh-builder: do it. Do your part and close it or hand it back (sender='home-watcher'); Your turn-end board check asks about it until then. → https://stackshot.example.com/items/a1", 'needs')])),
    ("tell_needed: the mover that has heard this write is left out, a mover that has not is told and added to heard", lambda: _heard(lambda h: G.tell_needed("a1", it_back, [BACK, OTHER], OTHER, h), [BACK]), ('ok', '', [], ['marsh-builder'])),
    ("tell_needed: a mover that is a front agent is not woken; the reply says so", lambda: told(lambda: G.tell_needed("a2", it_front, [FRONT, OTHER], BACK)), ('ok', '\n(home-other has been told the item needs it)\n(its mover quill-agent is a front agent: not told; the board shows it)', [('woken', 'a2', '00000000-0000-4000-8000-000000000005', "[stackshot] a2 now needs you (named in its needs by marsh-builder): [home] item 2 (projects/quill); next: marsh-builder: do it. Do your part and close it or hand it back (sender='home-other'); Your turn-end board check asks about it until then. → https://stackshot.example.com/items/a2", 'needs')])),
    ("tell_needed: an item whose mover is the owner names its `then`", lambda: told(lambda: G.tell_needed("a8", it_owner_then, [OTHER], BACK)), ('ok', '\n(home-other has been told the item needs it)', [('woken', 'a8', '00000000-0000-4000-8000-000000000005', "[stackshot] a8 now needs you (named in its needs by marsh-builder): [home] item 8 (projects/quill), then marsh-builder; next: marsh-builder: do it. Do your part and close it or hand it back (sender='home-other'); Your turn-end board check asks about it until then. → https://stackshot.example.com/items/a8", 'needs')])),
    ("tell_decided: when the decision leaves needs the sessions still named are told the move is theirs", lambda: told(lambda: G.tell_decided("a3", it_needs, [BACK, OTHER], WATCH)), ('ok', '\n(marsh-builder, home-other have been told the move is theirs now that the decision is in)', [('woken', 'a3', '00000000-0000-4000-8000-000000000003', "[stackshot] a3: Oliver has decided (decision left its needs, by home-watcher), so the move is yours as named in its needs: [home] item 3 (projects/quill); next: marsh-builder: do it. Read its next for his call, do your part and close it or hand it back (sender='marsh-builder'). → https://stackshot.example.com/items/a3", 'needs'), ('woken', 'a3', '00000000-0000-4000-8000-000000000005', "[stackshot] a3: Oliver has decided (decision left its needs, by home-watcher), so the move is yours as named in its needs: [home] item 3 (projects/quill); next: marsh-builder: do it. Read its next for his call, do your part and close it or hand it back (sender='home-other'). → https://stackshot.example.com/items/a3", 'needs')])),
    ("tell_decided: never the writer, nor a mover that has heard; a front agent mover is not woken", lambda: _heard(lambda h: G.tell_decided("a2", it_front, [FRONT, BACK, OTHER], BACK, h), [OTHER]), ('ok', '\n(its mover quill-agent is a front agent: not told; the board shows it)', [], ['home-other'])),
    ("tell_owner: a background mover hears a completion by another session; the writer's reply says so", lambda: told(lambda: G.tell_owner("a1", it_back, "was completed (done)", OTHER)), ('ok', '\n(its mover marsh-builder has been told)', [('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[stackshot] a1 was completed (done) by home-other: [home] item 1 → https://stackshot.example.com/items/a1', 'owner')])),
    ("tell_owner: a dropped item tells it to stop (not held); a move to decision; a reopen", lambda: [told(lambda: G.tell_owner("a1", it_back, w, OTHER, decision=d)) for w, d in (("was dropped", False), ("moved to decision", True), ("was reopened", False))], [('ok', '\n(its mover marsh-builder has been told)', [('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[stackshot] a1 was dropped by home-other: [home] item 1 → https://stackshot.example.com/items/a1', 'owner')]), ('ok', '\n(its mover marsh-builder has been told)', [('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[stackshot] a1 moved to decision by home-other: [home] item 1 → https://stackshot.example.com/items/a1', 'owner')]), ('ok', '\n(its mover marsh-builder has been told)', [('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[stackshot] a1 was reopened by home-other: [home] item 1 → https://stackshot.example.com/items/a1', 'owner')])]),
    ("tell_owner: the mover that wrote it, a project outside the pilot, and no mover tell nobody", lambda: [told(lambda: G.tell_owner("a1", it_back, "was completed (done)", BACK)), told(lambda: G.tell_owner("a1", item("1", mover=BACK, project="projects/none"), "was completed (done)", OTHER)),
                                                                                                           told(lambda: G.tell_owner("a1", item("1", mover=""), "was completed (done)", OTHER))], [('ok', '', []), ('ok', '', []), ('ok', '\n(its mover quill-agent is a front agent: not told; the board shows it)', [])]),
    ("tell_owner: a front agent mover hears nothing itself; its keeper hears a completion, said in the reply (the gate sent it, held it, or filed it)", lambda: [told(lambda: G.tell_owner("a2", it_front, "was completed (done)", OTHER, close=True), gate=g) for g in (("sent", ""), ("held", "no presence"), ("fyi", ""))], [('ok', '\n(its mover quill-agent is a front agent: not told; the board shows it)', []), ('ok', '\n(its mover quill-agent is a front agent: not told; the board shows it)', []), ('ok', '\n(its mover quill-agent is a front agent: not told; the board shows it)', [])]),
    ("tell_owner: a front agent mover and a move to decision: the quiet line, and the mover is added to heard", lambda: _heard(lambda h: G.tell_owner("a2", it_front, "moved to decision", OTHER, decision=True, heard=h), []), ('ok', '\n(its mover quill-agent is a front agent: not told; the board shows it)', [], ['00000000-0000-4000-8000-000000000004'])),
    ("tell_owner: `to` names who the mover was before the write", lambda: told(lambda: G.tell_owner("a1", item("1", mover=OWNER), "was completed (done)", OTHER, to=BACK)), ('ok', '\n(its mover marsh-builder has been told)', [('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[stackshot] a1 was completed (done) by home-other: [home] item 1 → https://stackshot.example.com/items/a1', 'owner')])),
    ("tell_observers: an observer hears a close, a front agent observer through its project's keeper, never the writer or the mover", lambda: told(lambda: G.tell_observers("a4", it_obs, "was completed (done)", OTHER)), ('ok', '\n(observers told: home-watcher, quill-agent for quill-agent)', [('woken', 'a4', '00000000-0000-4000-8000-000000000006', '[stackshot] a4 was completed (done) by home-other: [home] item 4 → https://stackshot.example.com/items/a4 (you observe it)', 'observer'), ('kind', 'close', 'a4', '00000000-0000-4000-8000-000000000004', '[stackshot] a4 (observer quill-agent, a front agent) was completed (done) by home-other: [home] item 4 → https://stackshot.example.com/items/a4 — pass it on only if it needs quill-agent', 'observer')])),
    ("tell_observers: …and a held front notice is not counted as told", lambda: told(lambda: G.tell_observers("a4", it_obs, "was dropped", OTHER), gate=("held", "no presence")), ('ok', '\n(observers told: home-watcher)', [('woken', 'a4', '00000000-0000-4000-8000-000000000006', '[stackshot] a4 was dropped by home-other: [home] item 4 → https://stackshot.example.com/items/a4 (you observe it)', 'observer'), ('kind', 'progress', 'a4', '00000000-0000-4000-8000-000000000004', '[stackshot] a4 (observer quill-agent, a front agent) was dropped by home-other: [home] item 4 → https://stackshot.example.com/items/a4 — pass it on only if it needs quill-agent', 'observer')])),
    ("tell_owner_change: a session mover hears a change of next, needs, check or after; one short line", lambda: [told(lambda: G.tell_owner_change("a1", item("1", mover=BACK, next=f"{OTHER}: new line"), {"next": f"{BACK}: do it"}, OTHER, False, False)),
                                                                                                                told(lambda: G.tell_owner_change("a1", item("1", mover=BACK, needs=[WATCH]), {"needs": []}, OTHER, False, False)),
                                                                                                                told(lambda: G.tell_owner_change("a1", item("1", mover=BACK, after=["a3"]), {"after": None}, OTHER, False, False))], [('ok', '\n(its mover marsh-builder has been told)', [('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[board] a1 [home] item 1: home-other set next: home-other: new line → https://stackshot.example.com/items/a1', 'owner')]), ('ok', '\n(its mover marsh-builder has been told)', [('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[board] a1 [home] item 1: home-other set next: marsh-builder: do it; changed needs: home-watcher → https://stackshot.example.com/items/a1', 'owner')]), ('ok', '\n(its mover marsh-builder has been told)', [('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[board] a1 [home] item 1: home-other set next: marsh-builder: do it; changed after: a3 → https://stackshot.example.com/items/a1', 'owner')])]),
    ("tell_owner_change: a close and a reopen are always sent; the window drops a second change", lambda: _window(), ('ok', ['\n(its mover marsh-builder has been told)', '', '\n(its mover marsh-builder has been told)', '\n(its mover marsh-builder has been told)', [('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[board] a1 [home] item 1: home-other set next: home-other: new line → https://stackshot.example.com/items/a1', 'owner'), ('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[board] a1 [home] item 1: home-other closed it: done → https://stackshot.example.com/items/a1', 'owner'), ('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[board] a1 [home] item 1: home-other reopened it; set next: home-other: new line → https://stackshot.example.com/items/a1', 'owner')]])),
    ("tell_owner_change: nothing when handled, the writer is the mover, the change is no change, or the mover is not a session", lambda: [told(lambda: G.tell_owner_change("a1", it_back, {"next": f"{BACK}: do it"}, OTHER, False, True)), told(lambda: G.tell_owner_change("a1", item("1", mover=BACK, next="x: y"), {"next": "z: q"}, BACK, False, False)),
                                                                                                                          told(lambda: G.tell_owner_change("a1", it_back, {"next": f"{BACK}: do it"}, OTHER, False, False)), told(lambda: G.tell_owner_change("a1", item("1", mover=OWNER, next="x: y"), {"next": "z: q"}, OTHER, False, False))], [('ok', '', []), ('ok', '', []), ('ok', '', []), ('ok', '\n(its mover quill-agent is a front agent: the notice went to projects/quill, where the router rules it)', [])]),
    ("tell_owner_change: a front agent mover is not pushed to; the notice goes to the page key for the router, or the reply says nothing is sent", lambda: [told(lambda: G.tell_owner_change("a2", item("2", mover=FRONT, next=f"{BACK}: new"), {"next": "old"}, BACK, False, False)),
                                                                                                                                                     told(lambda: G.tell_owner_change("a2", item("2", mover=FRONT, next=f"{BACK}: new"), {"next": "old"}, BACK, False, False, relayed=True)),
                                                                                                                                                     told(lambda: G.tell_owner_change("a2", item("2", mover=FRONT, next=f"{BACK}: new", needs=["decision"]), {"next": "old", "needs": []}, BACK, False, False)),
                                                                                                                                                     told(lambda: G.tell_owner_change("a2", item("2", mover=FRONT), {}, KEEP, True, False))], [('ok', '\n(its mover quill-agent is a front agent: the notice went to projects/quill, where the router rules it)', []), ('ok', '', []), ('ok', '\n(its mover quill-agent is a front agent: not told; the board shows it)', []), ('ok', '', [])]),
    ("tell_handback: an item handed back to its front agent mover alone: the builder is told, in the reply, after a hold", lambda: [told(lambda: G.tell_handback("a2", item("2", mover=FRONT, needs=[FRONT]), [BACK, FRONT], BACK)), told(lambda: G.tell_handback("a2", item("2", mover=FRONT, needs=[FRONT]), [BACK, FRONT], OTHER))], [('ok', "\n(its mover quill-agent is a front agent: nobody is told: a front agent is not handed an item on stackshot's own motion, so it stays with them and the board shows it)", []), ('ok', "\n(its mover quill-agent is a front agent: nobody is told: a front agent is not handed an item on stackshot's own motion, so it stays with them and the board shows it)", [])]),
    ("tell_handback: not on a close, not when the mover wrote it, not a decision, not when nothing else was named before, not a background mover", lambda: [told(lambda: G.tell_handback("a2", item("2", status="completed", mover=FRONT, needs=[FRONT]), [BACK, FRONT], OTHER)),
                                                                                                                                                      told(lambda: G.tell_handback("a2", item("2", mover=FRONT, needs=[FRONT]), [BACK, FRONT], FRONT)),
                                                                                                                                                      told(lambda: G.tell_handback("a2", item("2", mover=FRONT, needs=[FRONT, "decision"]), [BACK, FRONT], OTHER)),
                                                                                                                                                      told(lambda: G.tell_handback("a2", item("2", mover=FRONT, needs=[FRONT]), [], OTHER)),
                                                                                                                                                      told(lambda: G.tell_handback("a1", item("1", mover=BACK, needs=[BACK]), [OTHER, BACK], OTHER))], [('ok', '', []), ('ok', '', []), ('ok', '', []), ('ok', '', []), ('ok', '', [])]),
    ("tell_owner_close: a front agent mover is told of a close by another session at once, marked for the owner; not when it wrote it or heard it", lambda: [told(lambda: G.tell_owner_close("a2", item("2", status="completed", mover=FRONT, outcome="done"), OTHER, True, [])),
                                                                                                                                                      told(lambda: G.tell_owner_close("a2", item("2", status="completed", mover=FRONT, outcome="done"), OTHER, True, [], ), gate=("held", "no presence")),
                                                                                                                                                      told(lambda: G.tell_owner_close("a2", item("2", status="completed", mover=FRONT, outcome="done"), OTHER, False, [])),
                                                                                                                                                      told(lambda: G.tell_owner_close("a2", item("2", status="completed", mover=FRONT, outcome="done"), FRONT, True, [])),
                                                                                                                                                      told(lambda: G.tell_owner_close("a2", item("2", status="completed", mover=FRONT, outcome="done"), OTHER, True, [U[FRONT]]))], [('ok', '\n(its mover quill-agent is a front agent: told at once that it was closed)', [('kind', 'close', 'a2', '00000000-0000-4000-8000-000000000004', '[for Oliver] [stackshot] a2 [home] item 2: closed by home-other: done → https://stackshot.example.com/items/a2', 'owner')]), ('ok', '\n(its mover quill-agent is a front agent: not told that it was closed (no presence); the close is on the board)', [('kind', 'close', 'a2', '00000000-0000-4000-8000-000000000004', '[for Oliver] [stackshot] a2 [home] item 2: closed by home-other: done → https://stackshot.example.com/items/a2', 'owner')]), ('ok', '', []), ('ok', '', []), ('ok', '', [])]),
    ("tell_close_owner and close_owner_notice: a close with the owner's words on it is a row, and the old notice when the row failed", lambda: _owner_words_close(), [('ok', '', []), ('ok', '', []), ('ok', True, [('kind', 'close', 'a2', '00000000-0000-4000-8000-000000000004', '[for Oliver] [stackshot] a2 closed by home-other (done): [home] item 2 — shipped → https://stackshot.example.com/items/a2', 'owner')]), ('ok', True, [('kind', 'close', 'a2', '00000000-0000-4000-8000-000000000004', '[for Oliver] [stackshot] a2 closed by a script (done): [home] item 2 — shipped → https://stackshot.example.com/items/a2', 'owner')])]),
    ("tell_owner_check_closed and tell_check_closed: the server's own close on a done check tells the mover once", lambda: [told(lambda: G.tell_check_closed("a1", it_back, "PR 7")), told(lambda: G.tell_check_closed("a2", it_front, "PR 7")), told(lambda: G.tell_check_closed("a9", item("9", mover=OWNER), "PR 7")),
                                                                                                                         told(lambda: G.tell_owner_check_closed("a2", it_front, [])), told(lambda: G.tell_owner_check_closed("a2", it_front, [FRONT]))], [('ok', ['00000000-0000-4000-8000-000000000003'], [('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[stackshot] a1 closed itself: its done check passed (PR 7): [home] item 1 (projects/quill) → https://stackshot.example.com/items/a1', 'check')]), ('ok', ['00000000-0000-4000-8000-000000000004'], [('kind', 'close', 'a2', '00000000-0000-4000-8000-000000000004', "[for Oliver] [stackshot] a2 [home] item 2: closed by stackshot's done check: done → https://stackshot.example.com/items/a2", 'owner')]), ('ok', ['00000000-0000-4000-8000-000000000004'], [('kind', 'close', 'a9', '00000000-0000-4000-8000-000000000004', "[for Oliver] [stackshot] a9 [home] item 9: closed by stackshot's done check: done → https://stackshot.example.com/items/a9", 'owner')]), ('ok', True, [('kind', 'close', 'a2', '00000000-0000-4000-8000-000000000004', "[for Oliver] [stackshot] a2 [home] item 2: closed by stackshot's done check: done → https://stackshot.example.com/items/a2", 'owner')]), ('ok', False, [])]),
    ("tell_close_mentions: a close tells the mover of every open item that names it, one batched notice per mover; mentions_reply says it once", lambda: told(lambda: _mentions()), ('ok', (['00000000-0000-4000-8000-000000000003', '00000000-0000-4000-8000-000000000004'], '\n(2 other open items name a5 in next or description (a6, a7); marsh-builder, quill-agent have been told)', '', ''), [('kind', 'close', 'a6', '00000000-0000-4000-8000-000000000003', '[stackshot] a5 [home] item 5 closed (done: shipped) by home-other. An open item you move names it:\n- a6 [home] item 6 (its next names a5) → https://stackshot.example.com/items/a6\nIf one of them waited on a5, it can go on now: refresh its next and set after= for any wait that is left.', 'close'), ('kind', 'close', 'a7', '00000000-0000-4000-8000-000000000004', '[for Oliver] [stackshot] a5 [home] item 5 closed (done: shipped) by home-other. An open item you move names it:\n- a7 [home] item 7 (its description names a5) → https://stackshot.example.com/items/a7\nIf one of them waited on a5, it can go on now: refresh its next and set after= for any wait that is left.', 'close')])),
    ("tell_close_mentions: the closer and the items in skip are left out; an unknown item tells nobody", lambda: [told(lambda: G.tell_close_mentions("a5", "done", "", BACK)), told(lambda: G.tell_close_mentions("a5", "done", "", OTHER, {"a6"})), told(lambda: G.tell_close_mentions("a999", "done", "", OTHER))], [('ok', ['00000000-0000-4000-8000-000000000004'], [('kind', 'close', 'a7', '00000000-0000-4000-8000-000000000004', '[for Oliver] [stackshot] a5 [home] item 5 closed (done: shipped) by marsh-builder. An open item you move names it:\n- a7 [home] item 7 (its description names a5) → https://stackshot.example.com/items/a7\nIf one of them waited on a5, it can go on now: refresh its next and set after= for any wait that is left.', 'close')]), ('ok', ['00000000-0000-4000-8000-000000000004'], [('kind', 'close', 'a7', '00000000-0000-4000-8000-000000000004', '[for Oliver] [stackshot] a5 [home] item 5 closed (done: shipped) by home-other. An open item you move names it:\n- a7 [home] item 7 (its description names a5) → https://stackshot.example.com/items/a7\nIf one of them waited on a5, it can go on now: refresh its next and set after= for any wait that is left.', 'close')]), ('ok', [], [])]),
    ("tell_wait_failed: the keeper of the item's page hears that a wait can no longer end; not twice, not when nobody keeps it", lambda: [told(lambda: G.tell_wait_failed("a1", it_back, "PR 7 merged", "the pull request was closed")), told(lambda: G.tell_wait_failed("a1", it_back, "PR 7 merged", "closed", [U[BACK]])),
                                                                                                                                      told(lambda: G.tell_wait_failed("a1", item("1", project="projects/none"), "PR 7 merged", "closed"))], [('ok', '00000000-0000-4000-8000-000000000004', [('kind', 'stuck', 'a1', '00000000-0000-4000-8000-000000000004', '[stackshot] a1 "[home] item 1" (projects/quill): its wait (PR 7 merged) can no longer end: the pull request was closed. The item stays open. As the keeper of projects/quill: see that its mover or the session doing the work gives it what it waits on now (a new check, a wake, an item to wait after) or closes it. → https://stackshot.example.com/items/a1', 'wait')]), ('ok', '00000000-0000-4000-8000-000000000004', [('kind', 'stuck', 'a1', '00000000-0000-4000-8000-000000000004', '[stackshot] a1 "[home] item 1" (projects/quill): its wait (PR 7 merged) can no longer end: closed. The item stays open. As the keeper of projects/quill: see that its mover or the session doing the work gives it what it waits on now (a new check, a wake, an item to wait after) or closes it. → https://stackshot.example.com/items/a1', 'wait')]), ('ok', '', [])]),
    ("tell_comment: the owner's comment on GitHub goes to the mover and the sessions in needs, each once, a front agent marked", lambda: [told(lambda: G.tell_comment("a3", it_needs, "looks good")), told(lambda: G.tell_comment("a2", it_front, "ok")), told(lambda: G.tell_comment("a9", item("9", mover=""), "ok"))], [('ok', ['00000000-0000-4000-8000-000000000003'], [('woken', 'a3', '00000000-0000-4000-8000-000000000003', '[stackshot] Oliver commented on a3 on GitHub: looks good → https://stackshot.example.com/items/a3', 'comment')]), ('ok', ['00000000-0000-4000-8000-000000000004'], [('woken', 'a2', '00000000-0000-4000-8000-000000000004', '[for Oliver] [stackshot] Oliver commented on a2 on GitHub: ok → https://stackshot.example.com/items/a2', 'comment')]), ('ok', ['00000000-0000-4000-8000-000000000004'], [('woken', 'a9', '00000000-0000-4000-8000-000000000004', '[for Oliver] [stackshot] Oliver commented on a9 on GitHub: ok → https://stackshot.example.com/items/a9', 'comment')])]),
    ("pilot_relay: the keeper of a page is told what another session changed, or the router is charged; a front agent keeper hears nothing", lambda: [told(lambda: G.pilot_relay(PROJECT, "a1", it_back, "was updated", OTHER, KEEP)), told(lambda: G.pilot_relay(PROJECT, "a1", it_back, "was updated", OTHER, FRONT)),
                                                                                                                                                   told(lambda: G.pilot_relay(PROJECT, "a1", it_back, "was updated", OTHER, BACK, role="agent")), told(lambda: G.pilot_relay(PROJECT, "a1", it_back, "was updated", OTHER, KEEP, tail="the page update is yours as its keeper"))], [('ok', '\n(pilot project: this change is charged to the router, which passes the page update to the agent that keeps the page)', []), ('ok', '', []), ('ok', "\n(pilot project: this change is charged to the agent marsh-builder, who keeps the page and has been told; write your own page or the hub's timeline as usual)", []), ('ok', '\n(pilot project: this change is charged to the router, which passes the page update to the agent that keeps the page)', [])]),
    ("pilot_relay_many and writer_charge: a batch to the keeper, and the line that charges a writer", lambda: [_noid(told(lambda: G.pilot_relay_many(KEEP, [(PROJECT, "a1", it_back, "was updated", OTHER)], head="[board] changes"))), told(lambda: G.writer_charge(PROJECT, "a1", OTHER, KEEP, "was updated", False)),
                                                                                                                      told(lambda: G.writer_charge(PROJECT, "a1", OTHER, KEEP, "was updated", True))], [('ok', ['<id>'], []), ('ok', "\n(pilot project: the page update is yours in this turn: projects/quill, its Current state, since the item's state changed. If it is still missing after 30 min, it moves to the router, which passes the page update to the agent that keeps the page.)", []), ('ok', '\n(pilot project: the page update is yours in this turn: projects/quill, any page write, a timeline line included, since only next or the hold changed. If it is still missing after 30 min, it moves to the router, which passes the page update to the agent that keeps the page.)', [])]),
    ("handoff_notify: nothing recorded for the write, nothing told", lambda: told(lambda: G.handoff_notify("a1", it_back)), ('ok', '', [])),
    # ---- 3. hold
    ("hold_notice: a notice that asks a background agent nothing is held for its next turn; one that asks, a front agent and a kind nobody knows are delivered", lambda: plain(lambda: [G.hold_notice(BACK, "[stackshot] x closed", "closed", gid="a1"), G.hold_notice(BACK, "[stackshot] x needs you", "closed", gid="a1", asks=True),
                                                                                                                                                                  G.hold_notice(FRONT, "[stackshot] x closed", "closed", gid="a2"), G.hold_notice(BACK, "text", "no-such-kind"), G.hold_notice("", "text", "closed"), G.hold_notice(BACK, "text", "")]), ('ok', [False, False, False, False, False, False])),
    ("tell_or_hold: a kind that asks nothing is held for a background agent; the rest is sent", lambda: [told(lambda: G.tell_or_hold("a1", BACK, "[stackshot] closed", "changed")), told(lambda: G.tell_or_hold("a1", BACK, "[stackshot] closed", "")),
                                                                                                         told(lambda: G.tell_or_hold("a2", FRONT, "[stackshot] closed", "changed"))], [('ok', None, [('woken', 'a1', 'marsh-builder', '[stackshot] closed', 'wake')]), ('ok', None, [('woken', 'a1', 'marsh-builder', '[stackshot] closed', 'wake')]), ('ok', None, [('woken', 'a2', 'quill-agent', '[stackshot] closed', 'wake')])]),
    ("hand-back: held, replaced by a second inside the window, kept in the file, dropped by a close, sent by the tick when due", lambda: _handback(), [('ok', "\n(its mover quill-agent is a front agent: nobody is told: a front agent is not handed an item on stackshot's own motion, so it stays with them and the board shows it)", []), {}, ('ok', "\n(its mover quill-agent is a front agent: nobody is told: a front agent is not handed an item on stackshot's own motion, so it stays with them and the board shows it)", []), {}, 0, {}, 0, ('ok', "\n(its mover quill-agent is a front agent: nobody is told: a front agent is not handed an item on stackshot's own motion, so it stays with them and the board shows it)", []), ('ok', ['a2'], []), ('ok', [], []), {}, True]),
    ("record_undelivered: a failed delivery is recorded on the item it was about, the last five kept", lambda: _undelivered(), (['a1'], [('marsh-builder', 'wake', 'why 2'), ('marsh-builder', 'wake', 'why 3'), ('marsh-builder', 'wake', 'why 4'), ('marsh-builder', 'wake', 'why 5'), ('marsh-builder', 'wake', 'why 6')], [])),
    ("handback_hold_s: the window is the configured seconds; unset is 180", lambda: plain(lambda: [G.handback_hold_s(), G.HANDBACK_HOLD_S]), ('ok', [180.0, 180.0])),
    # ---- 7. paths the cases above leave to chance: who is added to heard, the observers, the hand-back tick's drops and tries, a keeper that is the writer
    ("held_by: an open item with a mover and a `then` goes to the mover", lambda: plain(lambda: [G.held_by(item("8", mover=BACK, then=OTHER)), G.holder(item("8", mover=BACK, then=OTHER))]), ('ok', [('marsh-builder', 'mover'), 'marsh-builder'])),
    ("tell_needed: the mover that is told is added to heard (a later notice of the same write leaves it out)", lambda: _heard(lambda h: G.tell_needed("a1", it_back, [BACK, OTHER], WATCH, h), []), ('ok', '\n(marsh-builder, home-other have been told the item needs them)', [('woken', 'a1', '00000000-0000-4000-8000-000000000003', "[stackshot] a1 now needs you (named in its needs by home-watcher): [home] item 1 (projects/quill); next: marsh-builder: do it. Do your part and close it or hand it back (sender='marsh-builder'); Your turn-end board check asks about it until then. → https://stackshot.example.com/items/a1", 'needs'), ('woken', 'a1', '00000000-0000-4000-8000-000000000005', "[stackshot] a1 now needs you (named in its needs by home-watcher): [home] item 1 (projects/quill); next: marsh-builder: do it. Do your part and close it or hand it back (sender='home-other'); Your turn-end board check asks about it until then. → https://stackshot.example.com/items/a1", 'needs')], ['00000000-0000-4000-8000-000000000003'])),
    ("tell_owner: the mover that is told is added to heard", lambda: _heard(lambda h: G.tell_owner("a1", it_back, "was completed (done)", OTHER, heard=h), []), ('ok', '\n(its mover marsh-builder has been told)', [('woken', 'a1', '00000000-0000-4000-8000-000000000003', '[stackshot] a1 was completed (done) by home-other: [home] item 1 → https://stackshot.example.com/items/a1', 'owner')], ['00000000-0000-4000-8000-000000000003'])),
    ("tell_observers: an observer that wrote the change is not told, nor one that is the mover", lambda: [told(lambda: G.tell_observers("a4", it_obs, "was completed (done)", WATCH)),
                                                                                                          told(lambda: G.tell_observers("a4", item("4", mover=BACK, observers=[BACK, WATCH]), "was dropped", OTHER))], [('ok', '\n(observers told: quill-agent for quill-agent)', [('kind', 'close', 'a4', '00000000-0000-4000-8000-000000000004', '[stackshot] a4 (observer quill-agent, a front agent) was completed (done) by home-watcher: [home] item 4 → https://stackshot.example.com/items/a4 — pass it on only if it needs quill-agent', 'observer')]), ('ok', '\n(observers told: home-watcher)', [('woken', 'a4', '00000000-0000-4000-8000-000000000006', '[stackshot] a4 was dropped by home-other: [home] item 4 → https://stackshot.example.com/items/a4 (you observe it)', 'observer')])]),
    ("tell_observers: a front agent observer whose keeper wrote the change is not told through it", lambda: _observer_keeper_wrote(), ('ok', '', [])),
    ("hand-back tick: an item that moved to decision while held is not sent and its line is dropped", lambda: _handback_decision(), [('ok', [], []), {}]),
    ("hand-back tick: a line whose send raises is tried again at the next ticks and given up after three", lambda: _handback_tries(), [('ok', [], []), {'a2|x': {'gid': 'a2', 'oid': '00000000-0000-4000-8000-000000000004', 'olabel': 'quill-agent', 'project': 'projects/quill', 'who': 'marsh-builder', 'subject': 's', 'line': 'L is back with you alone', 'due': '<t>', 'wid': '00000000-0000-4000-8000-000000000003', 'tries': 1}}, ('ok', [], []), {'a2|x': {'gid': 'a2', 'oid': '00000000-0000-4000-8000-000000000004', 'olabel': 'quill-agent', 'project': 'projects/quill', 'who': 'marsh-builder', 'subject': 's', 'line': 'L is back with you alone', 'due': '<t>', 'wid': '00000000-0000-4000-8000-000000000003', 'tries': 2}}, ('ok', [], []), {}]),
    ("handback_send: for a front agent the builder is told, unless it wrote the hand-back or no writer is on file", lambda: _handback_nowriter(), [('ok', False, []), ('ok', False, []), ('ok', True, [('woken', 'a2', 'marsh-builder', "L is back with quill-agent, a front agent, alone — told to you, not to quill-agent: an item is not handed to a front agent on stackshot's own motion", 'owner')])]),
    ("handback_drop: only the lines of the item that closed are dropped", lambda: _handback_other(), [1, ['a1|x']]),
    ("tell_close_mentions: a close that ten open items name lists eight of them and says how many more (the limit of lines a notice carries)", lambda: told(lambda: G.tell_close_mentions("a30", "done", "", OTHER)), ('ok', ['00000000-0000-4000-8000-000000000003'], [('kind', 'close', 'a31,a32,a33,a34,a35,a36,a37,a38,a39,a40', '00000000-0000-4000-8000-000000000003', '[stackshot] a30 [home] item 30 closed (done: shipped) by home-other. 10 open items you move name it:\n- a31 [home] item 31 (its next names a30) → https://stackshot.example.com/items/a31\n- a32 [home] item 32 (its next names a30) → https://stackshot.example.com/items/a32\n- a33 [home] item 33 (its next names a30) → https://stackshot.example.com/items/a33\n- a34 [home] item 34 (its next names a30) → https://stackshot.example.com/items/a34\n- a35 [home] item 35 (its next names a30) → https://stackshot.example.com/items/a35\n- a36 [home] item 36 (its next names a30) → https://stackshot.example.com/items/a36\n- a37 [home] item 37 (its next names a30) → https://stackshot.example.com/items/a37\n- a38 [home] item 38 (its next names a30) → https://stackshot.example.com/items/a38\n- … and 2 more\nIf one of them waited on a30, it can go on now: refresh its next and set after= for any wait that is left.', 'close')])),
    ("tell_close_mentions: an open item that names itself is not told of its own close", lambda: told(lambda: G.tell_close_mentions("a10", "done", "", OTHER)), ('ok', [], [])),
    ("front_keeper: strict answers true for the keeper of the project itself, where the default answers false", lambda: _keeper_is_self(), ('ok', [(False, ''), (True, '')])),
]

def _observer_keeper_wrote():
    with patched(G, page_keeper=lambda project, *a, **k: KEEP):
        return told(lambda: G.tell_observers("a4", item("4", mover=BACK, observers=[FRONT]), "was completed (done)", KEEP))
def _rec(gid, oid, label, who, wid=None):
    r = {"gid": gid, "oid": oid, "olabel": label, "project": PROJECT, "who": who, "subject": "s", "line": "L is back with you alone", "due": NOW - 5}
    if wid: r["wid"] = wid
    return r
def _handback_decision():
    G.handback_write({"a2|x": _rec("a2", U[FRONT], FRONT, BACK, U[BACK])})
    put(2, mover=FRONT, needs=[FRONT, "decision"])
    try: out = [told(lambda: G.handback_tick(NOW)), G.handback_read()]
    finally: put(2, mover=FRONT); G.handback_write({})
    return scrub(out)
def _handback_tries():
    def boom(rec): raise RuntimeError("no delivery")
    out = []
    put(2, mover=FRONT, needs=[FRONT]); G.handback_write({"a2|x": _rec("a2", U[FRONT], FRONT, BACK, U[BACK])})
    try:
        with patched(G, handback_send=boom):
            for _ in range(3): out.append(told(lambda: G.handback_tick(NOW))); out.append(G.handback_read())
    finally: put(2, mover=FRONT); G.handback_write({})
    return scrub(out)
def _handback_nowriter():
    out = []
    G.handback_write({})
    with srv(_handoff_builder=lambda project: [BACK]):      # the fixture's page names no builder: say it names this one
        for wid in (None, U[BACK], U[OTHER]): out.append(told(lambda: G.handback_send(_rec("a2", U[FRONT], FRONT, BACK, wid))))
    G.handback_write({})
    return scrub(out)
def _handback_other():
    G.handback_write({"a1|x": _rec("a1", U[BACK], BACK, OTHER, U[OTHER]), "a2|x": _rec("a2", U[FRONT], FRONT, BACK, U[BACK])})
    with delivery(): out = [G.handback_drop("a2", "closed"), sorted(G.handback_read())]
    G.handback_write({})
    return scrub(out)
def _keeper_is_self():
    with patched(_anc, name_line=lambda *a, **k: FRONT):
        return plain(lambda: [G.front_keeper(FRONT, PROJECT), G.front_keeper(FRONT, PROJECT, True)])
def _noid(got):
    """A result whose list holds a random six-character notice id: the id masked, the rest as it was."""
    return (got[0], ["<id>" if re.fullmatch(r"[0-9a-f]{6}", x) else x for x in got[1]], *got[2:]) if got[0] == "ok" else got
def _close_was():
    G.CLOSE_WAS.item = item("5", mover=BACK); r = [G.held_by(it_closed), G.holder(it_closed), G.held_by(item("6", status="completed", mover=""))]
    G.CLOSE_WAS.item = None; return r + [G.held_by(it_closed)]
def _heard(thunk_h, heard):
    h = list(heard); got = told(lambda: thunk_h(h)); return got + (h,) if got[0] == "ok" else got
def _window():
    out = []
    mine = item("1", mover=BACK, next=f"{OTHER}: new line"); before = {"next": f"{BACK}: do it"}
    with delivery():
        out.append(G.tell_owner_change("a1", mine, before, OTHER, False, False)); out.append(G.tell_owner_change("a1", mine, before, OTHER, False, False))
        out.append(G.tell_owner_change("a1", mine, before, OTHER, True, False)); out.append(G.tell_owner_change("a1", mine, before, OTHER, False, False, reopening=True))
        out.append(scrub(list(CALLS)))
    return ("ok", scrub(out))
def _owner_words_close():
    words = item("2", status="completed", mover=FRONT, outcome="done", reason="shipped", owner_words=[{"text": "ship it", "ts": NOW - 60}])
    return [told(lambda: G.tell_close_owner("a2", item("2", status="completed", mover=FRONT, outcome="done"), FRONT, PROJECT, OTHER)), told(lambda: G.tell_close_owner("a2", words, FRONT, PROJECT, OTHER)),
            told(lambda: G.close_owner_notice("a2", words, FRONT, PROJECT, OTHER, "", "words")), told(lambda: G.close_owner_notice("a2", words, FRONT, PROJECT, OTHER, "a script", "words"), gate=("held", "x"))]
def _mentions():
    G.MENTIONED.got = None
    r = G.tell_close_mentions("a5", "done", "shipped", OTHER); line = G.mentions_reply("a5"); again = G.mentions_reply("a5")
    return (r, line, again, G.mentions_reply("a6"))
def _handback():
    out = []
    G.handback_write({}); rec = lambda t: [told(lambda: G.tell_handback("a2", item("2", mover=FRONT, needs=[FRONT], next=f"{BACK}: {t}"), [BACK, FRONT], BACK)), G.handback_read()]
    out += rec("first"); out += rec("second")
    with delivery():
        out.append(G.handback_drop("a2", "closed")); out.append(G.handback_read()); out.append(G.handback_drop("a2"))
    with patched(G, handback_hold_s=lambda: 0.0):
        out.append(told(lambda: G.tell_handback("a2", item("2", mover=FRONT, needs=[FRONT]), [BACK, FRONT], OTHER)))
    G.handback_write({}); G.handback_write({"a2|x": {"gid": "a2", "oid": U[FRONT], "olabel": FRONT, "project": PROJECT, "who": BACK, "wid": U[BACK], "subject": "s", "line": "L", "due": NOW - 5}})
    put(2, mover=FRONT, needs=[FRONT])
    out.append(told(lambda: G.handback_tick(NOW)))
    G.handback_write({"a1|x": {"gid": "a1", "oid": U[BACK], "olabel": BACK, "project": PROJECT, "who": OTHER, "wid": U[OTHER], "subject": "s", "line": "L", "due": NOW - 5}})
    out.append(told(lambda: G.handback_tick(NOW)))
    out.append(G.handback_read()); out.append(G.handback_hold_s() > 0)
    G.handback_write({})
    return scrub(out)
def _undelivered():
    out = []
    with delivery():
        for i in range(7): out.append(G.record_undelivered("a1", BACK, "wake", f"why {i}"))
    meta = json.loads((T / "store/a/1.json").read_text(encoding="utf-8")).get("metadata", {})
    return scrub((out[-1], [(r.get("to"), r.get("tag"), r.get("why")) for r in meta.get("undelivered", [])], G.record_undelivered("nonsense", BACK, "wake", "x")))

# ---------------------------------------------------------------- what a main run prints
def run_cases():
    res = []
    for label, thunk, _want in CASES:
        try: res.append((label, scrub(thunk())))
        except Exception as e: res.append((label, ("raised", f"{e.__class__.__name__}: {e}")))
    return res
if MAIN:
    for label, got in run_cases(): print("CASE\t" + label); print("WANT\t" + repr(got))
    _scratch.cleanup() if hasattr(_scratch, "cleanup") else None
    sys.exit(0)

# ---------------------------------------------------------------- 1-3. keepers, notices, hold
for (label, got), (_l, _t, want) in zip(run_cases(), CASES):
    check(f"{label}", got == want, f"\n  got  {got!r}\n  want {want!r}")

# ---------------------------------------------------------------- 4. flags
with terminal_row(True):
    quiet = [told(lambda: G.tell_owner("a1", it_back, "was completed (done)", OTHER)), told(lambda: G.tell_observers("a4", it_obs, "was dropped", OTHER)), told(lambda: G.tell_owner_change("a1", item("1", mover=BACK, next="x: y"), {"next": "z: q"}, OTHER, False, False)),
             told(lambda: G.tell_owner_close("a2", item("2", status="completed", mover=FRONT), OTHER, True, []))]
check("4 a terminal-prompt row (a script's notification of its own) tells nobody: four notices, no delivery, an empty reply", all(q[0] == "ok" and q[1] == "" and q[2] == [] for q in quiet), quiet)
with terminal_row(False):
    loud = told(lambda: G.tell_owner("a1", it_back, "was completed (done)", OTHER))
check("4 …and is read when the notice is told: with the row off the same notice is sent", loud[0] == "ok" and loud[2] != [], loud)
check("4 the telling's own thread-locals are on service/telling.py (the close in flight, the kind the sender gives the gate, what a close mentioned, a write's hand-offs)",
      all(isinstance(getattr(telling, n), __import__("threading").local) for n in ("CLOSE_WAS", "FRONT_HINT", "MENTIONED", "HO_STATE")))
check("4 the flags the services and gates read are on service/writes.py", all(isinstance(getattr(writes, n), __import__("threading").local) for n in ("SESSION_NEXT", "TERMINAL_ROW", "QUESTION", "REFORMAT")))

# ---------------------------------------------------------------- 5. hooks
saved = telling._hooks_
telling._hooks_ = None
try:
    got = [plain(lambda: telling.tell_needed("a1", it_back, [OTHER], BACK)), plain(lambda: telling.tell_check_closed("a1", it_back, "x")), plain(lambda: telling.hold_notice(BACK, "t", "closed"))]
finally: telling._hooks_ = saved
check("5 a notice that needs the hooks and finds none says so, and names the install (a telling that was never installed is a start-up fault, never a notice that goes missing)", all(g[0] == "raised" and "no hooks installed" in g[1] for g in got), got)
fields = [f.name for f in dataclasses.fields(telling.Hooks)]
check("5 the table the server installed has every hook of the dataclass", telling._hooks_ is not None and [f for f in fields if not hasattr(telling._hooks_, f)] == [] and len(fields) >= 20, fields)
try: telling.Hooks(**{f: None for f in fields[:-1]}); built = True
except TypeError: built = False
check("5 a table with a hook missing cannot be built", not built)
_first = telling._hooks_
try:
    _other = dataclasses.replace(_first, zone=lambda: "a later table")
    telling.install(_other)
    replaced = telling._hooks_ is _other and telling._hooks().zone() == "a later table"
finally: telling.install(_first)
check("5 install replaces the table (the last one installed is the one the telling reads), and the first can be put back", replaced and telling._hooks_ is _first, replaced)
with srv(_session_id=lambda who: "id-of-" + str(who)):
    sent = told(lambda: telling.tell_needed("a1", it_back, [OTHER], BACK))
check("5 a hook that is a function is looked up on the server when the notice is told: a patched _session_id reaches tell_needed", sent[0] == "ok" and sent[2] and sent[2][0][2] == "id-of-" + OTHER, sent)
with srv(_model_of=lambda it: type("M", (), {"state": "none", "wait": None, "mover": "", "then": ""})()):
    held = plain(lambda: telling.held_by(item("1", mover=BACK)))
check("5 …and _model_of reaches held_by through model_of (the model is the server's to read)", held[0] == "ok" and held[1][0] == BACK, held)
check("5 a value hook is the server's own value (the time zone, the For you list's failed set)", telling._hooks().zone() is server.ZONE and telling._hooks().foryou_failed() is server._FORYOU_FAILED)

# ---------------------------------------------------------------- 6. shape
TELLING_SRC = pathlib.Path(STACK, "stackshot/service/telling.py").read_text(encoding="utf-8")
tree = ast.parse(TELLING_SRC)
imported = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import): imported += [a.name for a in node.names]
    elif isinstance(node, ast.ImportFrom): imported += [f"{node.module}.{a.name}" if node.module else a.name for a in node.names] + [node.module or ""]
check("6 telling.py imports no web module and no audit module (the layers: service sits under web and imports no audit/)", not [m for m in imported if m.startswith(("stackshot.web", "stackshot.audit"))], [m for m in imported if m.startswith(("stackshot.web", "stackshot.audit"))])
nested = [n for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(fn) if isinstance(n, (ast.Import, ast.ImportFrom))]
check("6 …and no function of it imports anything when it runs (every import is at the top)", not nested, [ast.dump(n)[:80] for n in nested])
SERVER_SRC = pathlib.Path(STACK, "stackshot/web/server.py").read_text(encoding="utf-8")
stree = ast.parse(SERVER_SRC)
defined = {n.name for n in stree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))} | {t.id for n in stree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)} | {n.target.id for n in stree.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
moved_defs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name not in ("install", "_hooks")} | {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name) and t.id != "_hooks_"} | {n.target.id for n in tree.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id != "_hooks_"}
check("6 every name that moved is in the table of this suite (MOVED), so the checks below see all of them", {n for n in moved_defs if n != "_FOR_OWNER"} == set(MOVED), sorted(({n for n in moved_defs if n != "_FOR_OWNER"} ^ set(MOVED))))
old_names = set(MOVED.values())
check("6 server.py defines none of the bodies and constants that moved", not (defined & old_names), sorted(defined & old_names))
rebound = [a.asname or a.name for n in ast.walk(stree) if isinstance(n, ast.ImportFrom) and n.module == "stackshot.service.telling" for a in n.names]
check("6 …and re-exports none of them under an old name (no `from stackshot.service.telling import`, no alias assigned)", not rebound and not [n for n in old_names if re.search(rf"^{re.escape(n)}\s*=\s*_?telling\.", SERVER_SRC, re.M)], rebound)
called = set()
for f in ("stackshot/service/update.py", "stackshot/service/create.py", "stackshot/service/gates.py", "stackshot/web/server.py"):
    for node in ast.walk(ast.parse(pathlib.Path(STACK, f).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "_telling": called.add(node.attr)
missing = sorted(n for n in called if not hasattr(telling, n))
check("6 every name the server and the three services take from `_telling` exists on it", not missing and {"tell_owner", "tell_needed", "tell_woken", "holder", "handoff_notify", "tell_close_mentions"} <= called, (missing, sorted(called)))
hooked = []
for f in ("stackshot/service/update.py", "stackshot/service/create.py", "stackshot/service/gates.py"):
    for node in ast.walk(ast.parse(pathlib.Path(STACK, f).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute) and node.attr in set(MOVED) | {n.lstrip("_") for n in MOVED} and isinstance(node.value, ast.Name) and node.value.id in ("h", "hk"): hooked.append(f"{f}:{node.attr}")
check("6 the services reach no telling function through a hook of their own (they call the module)", not hooked, hooked)
threadlocals = [f"{p.name}:{n.lineno}" for p in sorted(pathlib.Path(STACK, "stackshot/web").glob("*.py")) for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "local" and isinstance(n.func.value, ast.Name) and n.func.value.id == "threading"]
check("6 no thread-local is left in web/ (the per-write flags are on service/writes.py and service/telling.py)", not threadlocals, threadlocals)

# ---------------------------------------------------------------- end
print(f"telling scenario: {len(ran) - len(fails)}/{len(ran)} checks")
_scratch.cleanup() if hasattr(_scratch, "cleanup") else None
if fails:
    print("FAILED:", *fails, sep="\n  "); sys.exit(1)
print(f"ok: telling scenario, {len(ran)} checks")
