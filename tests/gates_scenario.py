"""Scenario test for the write gates, in two parts that each run in a process of their own: a scratch store, fixture items, no server socket, no network, no model call.

Part `gates` - the write gates (stackshot/service/gates.py):

The gates are the rules that refuse a create, update or complete, each with the sentence the writer reads. They moved out of server.py into service/gates.py and must behave as they did: the same
refusal text, the same flags read, the same order. The expected values of the cases below were taken from main's own gates (server.py `_gate_*`, run from a checkout of main with
`GATES_MAIN=1 tests/run-suite gates`, which prints what each case gives there), never from this code. This suite holds the new code to them, and checks the shape of the move.

  1  refusals       every gate's refusal text and what it returns when it lets a write through (the cases the table CASES lists, one gate after another)
  2  flags          the per-write flags the gates read on service/writes.py (the server held them on main): a script's question, the terminal prompt's row, the re-bullet route, a session's own write (and each is read when the gate runs)
  3  order          the gates an update and a close call, in the order they run, with each gate replaced by a recorder that calls the real one; and the gates a gate calls
  4  hooks          a gate with no hooks installed is refused; the server's table holds every hook, and a hook that is a function is looked up on the server when the gate runs
  5  shape          gates.py imports no web/ or audit/ module and has no late import; server.py defines none of the moved bodies and re-exports none of the old names; the create and update services
                    call each moved gate on gates.py, and every gate they name exists there

Part `form` - one refusal for the faults of a call (the form gates of an item's text, and the checks beside them): an update or a create with several faults is refused once, with all of them numbered, and one
mistake is one fault in the words it has on main. Fixture data (English stand-in names) in a temporary store, the tools' own functions (`stackshot_update`, `stackshot_create`), no live store, no network, no model call.

  1  an update with several faults in the words of its fields (subject, description, next): one refusal that counts them on its first line, each fault with its own numbered line in the gates' order, nothing stored,
     the refusal counted in the call log under its first fault; the same call with the faults fixed goes through
  2  one fault: refused as it always was (the subject gate's, the goal gate's, the bare address's and the park's own text, no count and no list)
  3  a fault in the words beside a fault of the item as the call would store it (a wait_basis with no date to explain, a step rewritten with words added): both come back; the check that reads the step refused
     beside it is named as not made
  4  a check that reads what another fault leaves out is not made, and the refusal says so (the cap on how far out a wake may be, beside a said with a tag the rule does not know); a said list with two bad entries
     gives each fault its own line, named by its place
  5  a create with several faults: one refusal with each fault's own text and nothing filed; one fault alone keeps its own text, no count; a relay wait that names no day beside the faults in the words
  6  the checks that read what another fault leaves out: a description that is prose (no second refusal for a goal it could not read), an ask that names alternatives and lists no options, alone and beside
     a description with no goal
  7  with the model guards on, one mistake is one fault, in the words it has on main (an unknown mover, an event wait with no phrase or a phrase that is no event, an anchor not on the list, on an update and a
     create); two mistakes list both, each once, and the check that reads a refused fault is named as not made
  8  one mistake is one problem, with the guards off and on, in the words main has for it (a table of calls with one mistake each: dates, wait kinds, after ids, a closed item's steps and waits, a waits list with
     an until, placeholders in next and as an event); two mistakes beside each other (anchors beside a bad event wait, a then over 300 characters beside a waits list with no until, a line of next that names
     no one beside an unknown mover) are two problems

The two parts set up two different instances (the example config with HOME in the scratch folder and the owner Oliver, and the base config with the guards switched on and off in the code under test), and the code under test reads its config and keeps module state at import: so each part runs in a process of its own (this file started again with `--part <name>`), and the parent adds
their counts.

    tests/run-suite gates        -> exit 0 / 1"""
import ast, contextlib, dataclasses, datetime as dt, json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
PARTS = ("gates", "form")


# ================================================================ part gates: the write gates (service/gates.py)
def part_gates():
    import _scratch, _instance
    MAIN = os.environ.get("GATES_MAIN") == "1"            # run against a checkout of main, where the gates still sit in server.py as `_gate_*`: print what each case gives there
    tmp = _scratch.mkdtemp(prefix="gates-"); T = pathlib.Path(tmp)
    sys.path.insert(0, STACK)

    toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml      # never the host's session store
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                     ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml = _instance.set_person(toml)
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
    toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1                 # never the host's transcripts
    toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    (T / "home/.claude/sessions").mkdir(parents=True)                                           # an isolated HOME
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    for d in ("store/a", "brain/projects", "fleet/a", "state", "transcripts/-home-x"): (T / d).mkdir(parents=True)
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-owner", "home-stew", "marsh-builder", "quill-agent", "home-other"), 1)}
    (T / "store/anchors.json").write_text("{}"); (T / "store/next-id").write_text("900")
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/quill": {"title": "Quill", "name": "Quill", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active",
                                                                                   "board": [], "board_open": 0, "agents": {"quill-agent": "the front", "marsh-builder": "builds the back"}, "back_agents": {"marsh-builder": "builds the back"}},
                                                                          "projects/ember": {"title": "Ember", "name": "Ember", "org": "home", "tags": [], "type": "project", "session": "ember-stew", "status": "active", "board": [], "board_open": 0,
                                                                                             "agents": {"ember-main": "the front", "ember-desk": "the second front"}},
                                                                          "projects/hush": {"title": "Hush", "name": "Hush", "org": "home", "tags": [], "type": "project", "session": "hush-stew", "status": "active", "board": [], "board_open": 0,
                                                                                            "agents": {"hush-main": "the front", "hush-watch": "watches the clock"}, "back_agents": {"hush-watch": "watches the clock"}},
                                                                          "projects/ember/keep": {"title": "Ember keep", "name": "Ember keep", "org": "home", "tags": [], "type": "project", "role": "agent", "session": "ember-keeper", "status": "active", "board": [], "board_open": 0},
                                                                          "projects/ember/side": {"title": "Ember side", "name": "Ember side", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0,
                                                                                                  "agents": {"side-desk": "front for the side page"}}}}))
    (T / "brain/projects/quill.md").write_text("---\ntitle: Quill\ndisplay-name: home-stew\nagents:\n  quill-agent: the front\n  background:\n    marsh-builder: builds the back\n---\n\n# Quill\n")
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()})); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1500]}" if got is not None else ""))

    from fastmcp.exceptions import ToolError
    from stackshot.core import config as _cfg
    from stackshot.model import draft as _draft, faults as _faults, model_guards as _mg, step_commands as _sc
    from stackshot.waits import self_wait as _selfwait
    from stackshot.web import server
    from stackshot.web import publish as _web_publish
    from stackshot.service import handoff as handoff_svc
    from stackshot.web.tools import text as _wt_text
    from stackshot.web.tools import update as _wt_update
    if not MAIN: from stackshot.service import gates, telling, writes

    # the gate under test by its name here: gates.gate_x in this code, server._gate_x on main (a function that was public in service/gates.py has its old underscore name there)
    PUBLIC = ("fix_front_mover", "until_in", "ask_pre")
    def _own(name): return ("_" + name if name.startswith("gate_") or name in PUBLIC else name) if MAIN else name
    class _Owner:
        def __getattr__(self, name): return getattr(server if MAIN else gates, _own(name))
    G = _Owner()
    GATES = ("fix_front_mover", "gate_front_step", "gate_needs_session", "gate_needs", "gate_observers", "gate_work_writer", "gate_draft_args", "gate_draft", "gate_step", "gate_state_args",
             "gate_model_args", "gate_ask_on_wait", "gate_model", "gate_owner_step", "gate_decision_again", "gate_repark", "gate_clock_renewal", "gate_after", "gate_sender_watch", "gate_self_wait", "gate_busy_hold",
             "ask_pre", "gate_contact", "gate_handoff", "until_in", "gate_close", "gate_said", "gate_cap", "gate_wait_basis", "gate_step_gap")      # every gate that moved (the helpers and constants beside them stay private)

    @contextlib.contextmanager
    def patched(owner, **kv):
        """Names of a module (or of the gates' owner, `G`) replaced for a case, put back after."""
        mod = (server if MAIN else gates) if owner is G else owner
        name = (lambda n: _own(n)) if owner is G else (lambda n: n)
        old = {k: getattr(mod, name(k)) for k in kv}
        for k, v in kv.items(): setattr(mod, name(k), v)
        try: yield
        finally:
            for k, v in old.items(): setattr(mod, name(k), v)
    from stackshot.service import item_read as _item_read
    from stackshot.model import holders as _holders
    from stackshot.service import mover_steps as _mover_steps
    from stackshot.service import owner_words as _owner_words
    _SRV_MOVED = {"_model_guards_on": _item_read, "_role_of": _holders, "_eff_state": _mover_steps}                    # the hook names that left the server: their owner modules
    @contextlib.contextmanager
    def srv(**kv):                    # what the hooks look up on the server (or on the owner of a moved name) when a gate runs
        with contextlib.ExitStack() as st:
            for k, v in kv.items(): st.enter_context(patched(_SRV_MOVED[k], **{k: v}))
            yield
    FLAGMOD = server if MAIN else writes           # where the per-write flags live: the server on main (`_QUESTION`), service/writes.py here (`QUESTION`)
    def flagname(n): return ("_" + n) if MAIN else n
    def tel(**kv): return patched(server if MAIN else telling, **{("_" + k) if MAIN else k: v for k, v in kv.items()})      # the telling's functions: `_tell_woken` on the server on main, `tell_woken` on service/telling.py here
    @contextlib.contextmanager
    def flags(**on):
        """The per-write thread-local flags (`question`, `reformat`, `terminal_row`, `session_next`: service/writes.py), on for a case."""
        objs = {k: getattr(FLAGMOD, flagname(k.upper())) for k in ("question", "reformat", "terminal_row", "session_next")}
        old = {k: getattr(o, "on", False) for k, o in objs.items()}
        for k, o in objs.items(): o.on = bool(on.get(k, False))
        try: yield
        finally:
            for k, o in objs.items(): o.on = old[k]

    NOW = time.time()
    DAYS = lambda n: (dt.datetime.fromtimestamp(NOW, dt.timezone(dt.timedelta(hours=4))) + dt.timedelta(days=n)).strftime("%Y-%m-%d")
    EPOCH = re.compile(r"\b\d{10}(?:\.\d+)?\b")
    DAYMAP = {DAYS(k): f"<D{k:+d}>" for k in range(-3, 70)}                    # a date the fixture made from today's (a refusal names it)
    DAYRE = re.compile("|".join(re.escape(d) for d in DAYMAP))
    def scrub(v):
        """A result with its clocks masked (a time in the fixture's own run is never the same twice, nor is today's date or the days from it), so it compares with what main gave."""
        if isinstance(v, float) and v > 1e9: return "<t>"
        if isinstance(v, str):
            v = DAYRE.sub(lambda m: DAYMAP[m.group(0)], EPOCH.sub("<t>", v))
            return re.sub(r"\d+ min ago \([^)]*\)", "<ago>", re.sub(r"\b\d+ days out", "<n> days out", v))
        if isinstance(v, (list, tuple)): return type(v)(scrub(x) for x in v)
        if isinstance(v, (set, frozenset)): return sorted(scrub(x) for x in v)
        if isinstance(v, dict): return {k: scrub(x) for k, x in v.items()}
        return v
    def outcome(thunk):
        """What a case gives: ("refused", the text) for a ToolError, ("ok", the value) for a return, ("raised", the error) for anything else."""
        try: return ("ok", scrub(thunk()))
        except ToolError as e: return ("refused", scrub(str(e)))
        except Exception as e: return ("raised", f"{e.__class__.__name__}: {e}")

    OWNER = "Oliver"; BACK = "marsh-builder"; FRONT = "quill-agent"; KEEP = "home-stew"; OTHER = "home-other"
    PROJECT = "projects/quill"
    EMBER = "projects/ember"; EMAIN = "ember-main"; EDESK = "ember-desk"      # a front-only project: two front agents, no background agent
    def item(i="1", status="open", subject=None, description="- A thing", **meta):
        return {"id": i, "gid": f"a{i}", "subject": subject or f"[home] item {i}", "description": description, "status": status, "updated": NOW - 3600, "state_updated": NOW - 3600, "confirmed": NOW - 3600,
                "metadata": {"project": PROJECT, "next": f"{BACK}: do it", **meta}}
    def put(i, **kw):
        it = item(str(i), **kw)
        (T / f"store/a/{i}.json").write_text(json.dumps(it), encoding="utf-8")
        return it
    put(1, mover=BACK); put(2, mover=BACK, after=["a1"]); put(3, status="completed", mover=BACK, outcome="done"); put(4, mover=BACK, answers=[{"text": "go", "ts": NOW - 120, "ask": "Which one?"}])
    FUT = DAYS(3)
    STEP = lambda text, status="open": {"text": text, "status": status}
    BAD_STEP = "Oliver: " + "x" * 400                                                              # a step over the line limit

    # the cases: (what it checks, a thunk, what main's gate gave). The last value of each is what main's own `_gate_*` returned for the thunk (a run with GATES_MAIN=1 on a checkout of main prints each WANT line), with its clocks masked (`scrub`).
    CASES = [
        # ---- the checks before the lock
        ("fix_front_mover: a front agent set as mover by another session becomes the project's builder", lambda: G.fix_front_mover("mover", FRONT, OTHER, PROJECT, "", {}), ('ok', ('marsh-builder', "\n(fixed: mover=quill-agent is a user-facing agent of projects/quill and gets no hand-off notice from another session, so mover=marsh-builder, the project's builder, was used instead. If quill-agent really is who should take it, send mover=quill-agent again: the server then keeps it as sent; for a check or an answer only quill-agent can give, message(to='projects/quill') with the first line \"For quill-agent, ...\")", [('front_mover', 'mover=quill-agent|00000000-0000-4000-8000-000000000005|<t>', 'mover quill-agent → marsh-builder: quill-agent is a user-facing agent and gets no hand-off notice from another session; sending mover=quill-agent again keeps it as sent')]))),
        ("fix_front_mover: the builder itself is no case", lambda: G.fix_front_mover("mover", BACK, OTHER, PROJECT, "", {}), ('ok', ('marsh-builder', '', []))),
        ("fix_front_mover: the owner is no case, nor a value that clears the field", lambda: [G.fix_front_mover("mover", OWNER, OTHER, PROJECT, "", {}), G.fix_front_mover("then", "none", OTHER, PROJECT, "", {})], ('ok', [('Oliver', '', []), ('none', '', [])])),
        ("fix_front_mover: the front agent naming itself is no case", lambda: G.fix_front_mover("mover", FRONT, FRONT, PROJECT, "", {}), ('ok', ('quill-agent', '', []))),
        ("fix_front_mover: the value the item stores already is no case", lambda: G.fix_front_mover("post_wake_mover", FRONT, OTHER, PROJECT, FRONT, {}), ('ok', ('quill-agent', '', []))),
        ("fix_front_mover: a project with no builder refuses (the refusal's text)", lambda: str(G._front_mover_refusal("mover", (FRONT, PROJECT, [], KEEP), PROJECT)), ('ok', 'Refused: mover=quill-agent names quill-agent, a front agent of projects/quill, for an item of projects/quill, and home-stew has no builder to hand it to, so the item stays with its current mover. A live session some project page lists may name a live front agent of projects/quill in mover= (told by a hand-off notice), then= or post_wake_mover= (told by the owner\'s answer or the wake); this call was refused because the call names no sender. To ask quill-agent for a check or an answer, message(to=\'projects/quill\') with the first line "For quill-agent, ...".')),
        ("fix_front_mover: …and names the builder when there is one", lambda: str(G._front_mover_refusal("then", (FRONT, PROJECT, [BACK], KEEP), PROJECT)), ('ok', "Refused: quill-agent is a user-facing agent of projects/quill, and then=quill-agent from another session hands it an item it gets no notice of (the server sends a front agent no hand-off notice, so the item would sit handed and not taken). Hand build work to the project's builder, marsh-builder (then=marsh-builder); for a check or an answer only quill-agent can give, message(to='projects/quill') with the first line \"For quill-agent, ...\".")),
        ("fix_front_mover: a project with a builder substitutes it for then and post_wake_mover too", lambda: [G.fix_front_mover(f, FRONT, OTHER, PROJECT, "", {})[0] for f in ("then", "post_wake_mover")], ('ok', ['marsh-builder', 'marsh-builder'])),
        ("fix_front_mover: a front-only project lets a listed session name its front agent in mover, then and post_wake_mover (the note says who is told)", lambda: [G.fix_front_mover(f, EDESK, EMAIN, EMBER, "", {}) for f in ("mover", "then", "post_wake_mover")], ('ok', [('ember-desk', '\n(note: projects/ember has no builder, so mover=ember-desk stays as sent; ember-desk is a front agent of the project and is told it is handed the item)', []), ('ember-desk', '\n(note: projects/ember has no builder, so then=ember-desk is not replaced by one; ember-desk is a front agent of the project, and if the item keeps it, the owner\'s answer or the wake hands it the item and tells it)', []), ('ember-desk', '\n(note: projects/ember has no builder, so post_wake_mover=ember-desk is not replaced by one; ember-desk is a front agent of the project, and if the item keeps it, the owner\'s answer or the wake hands it the item and tells it)', [])])),
        ("fix_front_mover: …from a session no page lists, the refusal names the rule, the failed half and the For <peer> path, in then as in mover", lambda: [str(outcome(lambda: G.fix_front_mover(f, EDESK, OTHER, EMBER, "", {}))[1]) for f in ("mover", "then")], ('ok', ['Refused: mover=ember-desk names ember-desk, a front agent of projects/ember, for an item of projects/ember, and projects/ember has no builder to hand it to, so the item stays with its current mover. A live session some project page lists may name a live front agent of projects/ember in mover= (told by a hand-off notice), then= or post_wake_mover= (told by the owner\'s answer or the wake); this call was refused because home-other is not a session any project page lists. To ask ember-desk for a check or an answer, message(to=\'projects/ember\') with the first line "For ember-desk, ...".', 'Refused: then=ember-desk names ember-desk, a front agent of projects/ember, for an item of projects/ember, and projects/ember has no builder to hand it to, so the item stays with its current mover. A live session some project page lists may name a live front agent of projects/ember in mover= (told by a hand-off notice), then= or post_wake_mover= (told by the owner\'s answer or the wake); this call was refused because home-other is not a session any project page lists. To ask ember-desk for a check or an answer, message(to=\'projects/ember\') with the first line "For ember-desk, ...".'])),
        ("fix_front_mover: a sub-page with a map of its own, in a hub with no builder, is front-only too: the peer passes", lambda: G.fix_front_mover("mover", "side-desk", EMAIN, "projects/ember/side", "", {})[0], ('ok', 'side-desk')),
        ("fix_front_mover: …a peer listed only on a sub-page gets no For <peer> advice (the router reads the top-level page's agents), the rule and the failed half are still named", lambda: str(outcome(lambda: G.fix_front_mover("mover", "side-desk", OTHER, "projects/ember/side", "", {}))[1]), ('ok', "Refused: mover=side-desk names side-desk, a front agent of projects/ember/side, for an item of projects/ember/side, and projects/ember has no builder to hand it to, so the item stays with its current mover. A live session some project page lists may name a live front agent of projects/ember/side in mover= (told by a hand-off notice), then= or post_wake_mover= (told by the owner's answer or the wake); this call was refused because home-other is not a session any project page lists.")),
        ("fix_front_mover: …a peer on the top-level page is named with the top-level key", lambda: _for_peer_rows(), ('ok', ['message(to=\'projects/ember\') with the first line "For ember-desk, ..."', 'message(to=\'projects/ember\') with the first line "For ember-desk, ..."', ''])),
        ("fix_front_mover: a failing roles read lets the write through", lambda: _roles_fail(), ('ok', ('quill-agent', '', []))),
        ("until_in: no until and no old date passes the old parameters on", lambda: G.until_in("a1", "open", "", "", "", False, ""), ('ok', ('', '', False, [], ''))),
        ("until_in: an old wake is read as the date and named", lambda: G.until_in("a1", "open", "", FUT, "", False, ""), ('ok', ('<D+3>', '', False, ['wake'], '<D+3>'))),
        ("until_in: an until becomes the wake, as a wait on the date alone", lambda: G.until_in("a1", "open", FUT, "", "", False, ""), ('ok', ('<D+3>', '', True, [], ''))),
        ("until_in: an until on a relay's wait is the ask-by", lambda: G.until_in("a1", "open", FUT, "", "", False, "relay"), ('ok', ('', '<D+3>', True, [], ''))),
        ("until_in: an until with a hold names hold among the old parameters", lambda: G.until_in("a1", "open", FUT, "", "", True, ""), ('ok', ('<D+3>', '', True, ['hold'], ''))),
        ("until_in: an until that is no date is refused", lambda: G.until_in("a1", "open", "next week", "", "", False, ""), ('refused', "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04), a real date (got 'next week')")),
        ("until_in: an until in the past is refused", lambda: G.until_in("a1", "open", DAYS(-2), "", "", False, ""), ('refused', 'Refused: until must be in the future (+04)')),
        ("until_in: until=none drops the date", lambda: G.until_in("a1", "open", "none", "", "", False, ""), ('ok', ('none', '', True, [], ''))),
        ("ask_pre: an item that is no item gives {}", lambda: G.ask_pre("a99999"), ('ok', {})),
        ("ask_pre: an item gives what the ask looks back at and every text it holds", lambda: {k: (v if k != "look" else type(v).__name__) for k, v in G.ask_pre("a4").items()}, ('ok', {'gid': 'a4', 'ask': '', 'rec': {}, 'look': 'float', 'old': '[home] item 4\n- A thing\nmarsh-builder: do it'})),
        ("gate_self_wait: a wake on an item the sender moves, with no blocker named, is refused", lambda: G.gate_self_wait("a1", BACK, wake=FUT), ('refused', 'Refused: a wait on your own item needs its reason: this write sets an until date <D+3>, and a wait that names no blocker is how ready work sits idle until its date. Pass wait_reason=<what the step waits on that is not available now, at least 15 characters> with the same call (a reply, a build or test still running, a window the work needs, a resource that is down). If nothing blocks the step, do it now and write the next step instead of waiting. To wait, send the same call again: until="<D+3>", wait_reason="<what the step waits on that is not available now>". A wait that stands on a date outside the work is a park instead: until="YYYY-MM-DD", wait_kind="time" and wait_basis="<what happens> YYYY-MM-DD" (a park of the wait cap\'s days or less needs his recorded words: within them a wait_reason on a bare until is the way).')),
        ("gate_self_wait: the guard off passes the write", lambda: _with(_cfg, "wait_guard_on", lambda: False, lambda: G.gate_self_wait("a1", BACK, wake=FUT)), ('ok', None)),
        ("gate_self_wait: a sender that is the owner passes", lambda: G.gate_self_wait("a1", OWNER, wake=FUT), ('ok', None)),
        ("gate_self_wait: a wake the item's mover sets, on a guard that says no, is refused", lambda: _self_wait_case(), ('ok', (('refused', 'Refused: the step can be done now'), [{'subject': '[home] item 1', 'waits': ['an until date <D+3>'], 'step': 'marsh-builder: do it', 'reason': 'x', 'now': '<now>', 'call': 'until="<D+3>"'}]))),
        ("gate_self_wait: …and the owner of the write reads the stored item, not the call", lambda: _self_wait_case(creating=True), ('ok', (('ok', None), []))),
        # ---- needs, observers, contact
        ("gate_needs_session: a user-facing agent is refused (its part is its own item)", lambda: G.gate_needs_session(FRONT, PROJECT, BACK), ('refused', "Refused: quill-agent is a user-facing agent of projects/quill, and needs names a background agent of any project, or this project's keeper; a user-facing agent's part is its own item, linked with after=[quill-agent's item]. For projects/quill: marsh-builder")),
        ("gate_needs_session: in a front-only project a same-project front agent is refused with the working path (mover=, or its own item with after=)", lambda: G.gate_needs_session(EDESK, EMBER, ""), ('refused', "Refused: ember-desk is a front agent of projects/ember, and needs names a background agent or this project's keeper, which projects/ember lacks. To hand ember-desk the item set mover=ember-desk (it is told); for its part of a plan open its own item and link it with after=[ember-desk's item].")),
        ("gate_needs_session: …a front agent of another project keeps the old text", lambda: G.gate_needs_session(EDESK, PROJECT, ""), ('refused', "Refused: ember-desk is a user-facing agent of projects/ember, and needs names a background agent of any project, or this project's keeper; a user-facing agent's part is its own item, linked with after=[ember-desk's item]. For projects/quill: marsh-builder")),
        ("gate_needs_session: …a sub-page's own keeper is named, not reported as lacking", lambda: G.gate_needs_session(EDESK, "projects/ember/keep", ""), ('refused', "Refused: ember-desk is a front agent of projects/ember, and needs names a background agent or this project's keeper (ember-keeper). To hand ember-desk the item set mover=ember-desk (it is told); for its part of a plan open its own item and link it with after=[ember-desk's item].")),
        ("gate_needs_session: a session no page names is refused", lambda: G.gate_needs_session("nobody-here", PROJECT, BACK), ('refused', "Refused: nobody-here is not a background agent of any project, nor this project's keeper; needs names one of those (for projects/quill: marsh-builder), decision, or external")),
        ("gate_needs_session: the item's mover passes, and so does a background agent", lambda: [G.gate_needs_session(BACK, PROJECT, BACK), G.gate_needs_session(BACK, PROJECT, "")], ('ok', ['marsh-builder', 'marsh-builder'])),
        ("gate_needs_session: the page's retired name-line session is refused, naming the keeper", lambda: G.gate_needs_session(KEEP, PROJECT, BACK), ('refused', "Refused: home-stew is the retired name-line session of projects/quill (its notices go to the project's keeper), and needs names a session that can act. For projects/quill: marsh-builder")),
        ("gate_needs: not a list is refused", lambda: G.gate_needs({"a": 1}, PROJECT, BACK), ('refused', 'Refused: needs is a list of decision, external and session names (or one comma-separated string)')),
        ("gate_needs: a string splits at commas; kinds come first in their order", lambda: G.gate_needs(f"external, {BACK}, decision", PROJECT, ""), ('ok', ['decision', 'external', 'marsh-builder'])),
        ("gate_needs: a name that is no session is refused", lambda: G.gate_needs(["decision", "nobody-here"], PROJECT, BACK), ('refused', "Refused: nobody-here is not a background agent of any project, nor this project's keeper; needs names one of those (for projects/quill: marsh-builder), decision, or external")),
        ("gate_observers: not a list is refused", lambda: G.gate_observers(7), ('refused', 'Refused: observers is a list of session names (or one comma-separated string)')),
        ("gate_observers: a name no session answers to is refused", lambda: G.gate_observers("nobody-here"), ('refused', "Refused: observer 'nobody-here' names no session: a pane's name, a transcript id, a cse_… id, or a session a project page lists")),
        ("gate_observers: a known session is stored once", lambda: G.gate_observers([BACK, BACK, ""]), ('ok', ['marsh-builder'])),
        ("gate_contact: a background agent is refused with the project's front agents", lambda: G.gate_contact(BACK, PROJECT), ('refused', "Refused: contact=marsh-builder is not a front agent (a user-facing agent) of projects/quill. A contact is the front agent the item's person talks to about it; projects/quill's are: quill-agent (the front). Leave contact out and it is quill-agent.")),
        ("gate_contact: the owner himself is refused", lambda: G.gate_contact(OWNER, PROJECT), ('refused', "Refused: contact=Oliver is not a front agent (a user-facing agent) of projects/quill. A contact is the front agent the item's person talks to about it; projects/quill's are: quill-agent (the front). Leave contact out and it is quill-agent.")),
        ("gate_contact: a front agent of the project passes", lambda: G.gate_contact(FRONT, PROJECT), ('ok', 'quill-agent')),
        ("gate_work_writer: a session that neither moves the item nor is named in needs is refused", lambda: G.gate_work_writer("a1", OTHER, BACK, {"needs": []}), ('refused', "Refused: the status of a step on a1 is written by its mover (marsh-builder) or a session named in its needs (none named); home-other is neither. Have its mover name you in needs (needs=[…, 'home-other']), or pass the step to it.")),
        ("gate_work_writer: the mover passes, and so does a session named in needs, and a writer finishing its own line", lambda: [G.gate_work_writer("a1", BACK, BACK, {}), G.gate_work_writer("a1", OTHER, BACK, {"needs": [OTHER]}), G.gate_work_writer("a1", OTHER, BACK, {}, True)], ('ok', [None, None, None])),
        # ---- the form of an argument
        ("gate_draft_args: not a string is refused", lambda: G.gate_draft_args(5, False), ('refused', 'Refused: draft is a string, the text exactly as Oliver is to paste it')),
        ("gate_draft_args: a clear with a new text is refused", lambda: G.gate_draft_args("text", True), ('refused', 'Refused: clear_draft drops the draft; it does not go with a new one')),
        ("gate_draft_args: a text over the limit is refused", lambda: G.gate_draft_args("x" * (_draft.MAX + 1), False), ('refused', 'Refused: draft is at most 20000 characters (got 20001); a longer text goes in a document, and the step links it')),
        ("gate_draft_args: none clears; a text is kept with its line breaks made \\n", lambda: [G.gate_draft_args("none", False), G.gate_draft_args("\r\nline one\r\nline two\r\n", False), G.gate_draft_args("", False)], ('ok', [('', True), ('line one\nline two', False), ('', False)])),
        ("gate_state_args: step and supplies together are refused", lambda: G.gate_state_args({"step": "do it", "supplies": "a2"}), ('refused', 'Refused: step is a step for the person it names and supplies says what another item gives this one (a wait on that item): pass one of them')),
        ("gate_state_args: step=none with supplies is refused", lambda: G.gate_state_args({"step": "none", "supplies": "a2"}), ('refused', 'Refused: step="none" withdraws the step and supplies sets a wait on another item: pass one of them')),
        ("gate_state_args: a step over the limit is refused", lambda: G.gate_state_args({"step": BAD_STEP}), ('refused', 'Refused: step at most 300 characters on one line (408 now); it is a summary, and what the owner runs goes in lines of next that start with his name')),
        ("gate_state_args: a supplies line too long is refused", lambda: G.gate_state_args({"supplies": "x" * 600}), ('refused', 'Refused: supplies is one line of at most 300 characters — got 600')),
        ("gate_state_args: the state a call's fields set, and the withdrawal", lambda: [G.gate_state_args({"step": " Oliver:  paste it "}), G.gate_state_args({"supplies": "a2"}), G.gate_state_args({"step": "none"}), G.gate_state_args({})], ('ok', [('your-step', {'step': 'Oliver: paste it'}, False), ('blocked', {'supplies': 'a2'}, False), ('', {}, True), ('', {}, False)])),
        ("gate_model_args: a clear with the value it drops is refused", lambda: G.gate_model_args({"mover": BACK}, {"mover": True}), ('refused', 'Refused: clear_mover drops mover; it does not go with a new mover')),
        ("gate_model_args: the wait group's clear with a new wait_kind is refused", lambda: G.gate_model_args({"wait_kind": "time"}, {"wait": True}), ('refused', 'Refused: clear_wait drops wait_kind, wait_anchor, wait_event, ask_by, post_wake_mover; it does not go with a new wait_kind. The new wait_kind takes the place of the stored kind: send this call again without clear_wait')),
        ("gate_model_args: …a stored anchor and event the call gives no value for are named, with how to drop them", lambda: G.gate_model_args({"wait_kind": "time"}, {"wait": True}, {"wait_kind": "anchor", "wait_anchor": "https://example.com/pull/3", "wait_event": "a merge"}), ('refused', 'Refused: clear_wait drops wait_kind, wait_anchor, wait_event, ask_by, post_wake_mover; it does not go with a new wait_kind. The new wait_kind takes the place of the stored kind: send this call again without clear_wait, and for wait_anchor and wait_event, which the item stores and would keep beside the new kind, send the new wait\'s own value or wait_anchor="none" and wait_event="none" to drop them')),
        ("gate_model_args: …a field the call sets or drops itself is not named", lambda: G.gate_model_args({"wait_kind": "relay", "wait_event": "a reply", "wait_anchor": "none"}, {"wait": True}, {"wait_anchor": "https://example.com/pull/3", "wait_event": "a merge"}), ('refused', 'Refused: clear_wait drops wait_kind, wait_anchor, wait_event, ask_by, post_wake_mover; it does not go with a new wait_kind, wait_event. The new wait_kind takes the place of the stored kind: send this call again without clear_wait')),
        ("gate_model_args: a form the model refuses (wait_kind) is refused with the model's words", lambda: G.gate_model_args({"wait_kind": "sometime"}, {}), ('refused', "Refused: wait_kind is one of time | anchor | item | relay | event (got 'sometime')")),
        ("gate_model_args: the fields set are cleaned, a clear drops, none drops", lambda: G.gate_model_args({"mover": f"  {BACK} ", "wait_kind": "TIME", "then": "none"}, {"goal": True}), ('ok', ({'mover': 'marsh-builder', 'wait_kind': 'time'}, ['goal', 'then']))),
        # ---- the item a write leaves
        ("gate_draft: a draft problem refuses with the item's id", lambda: _with(_draft, "problem", lambda it, saved=None: "the step names a text to post and the item has no draft", lambda: G.gate_draft(item(), "a1")), ('refused', 'Refused: a1: the step names a text to post and the item has no draft.')),
        ("gate_draft: …and with no id says no id", lambda: _with(_draft, "problem", lambda it, saved=None: "WHY", lambda: G.gate_draft(item())), ('refused', 'Refused: WHY.')),
        ("gate_draft: a closed item passes; so does a write with the guards off", lambda: _with(_draft, "problem", lambda it, saved=None: "WHY", lambda: [G.gate_draft(item(status="completed"), "a1"), _guards_off(lambda: G.gate_draft(item(), "a1"))]), ('ok', [None, ('ok', None)])),
        ("gate_step: a step problem refuses", lambda: _with(_sc, "problem", lambda it, prior, step_set: "the step holds a command", lambda: G.gate_step(item(), "a1")), ('refused', 'Refused: a1: the step holds a command.')),
        ("gate_step: …and is handed the prior description and whether the step was set", lambda: _seen_step(), ('ok', [('the earlier description', True)])),
        ("gate_step: a closed item passes; so does a write with the guards off", lambda: _with(_sc, "problem", lambda it, prior, step_set: "WHY", lambda: [G.gate_step(item(status="completed"), "a1"), _guards_off(lambda: G.gate_step(item(), "a1"))]), ('ok', [None, ('ok', None)])),
        ("gate_ask_on_wait: asking the owner on an item that waits is refused", lambda: G.gate_ask_on_wait("a1", item(), {"wait_kind": "time", "needs": ["decision"], "wake": FUT}, [], False), ('refused', 'Refused: a1 still waits on a time; pass clear_wait=true with this update to drop the wait and ask Oliver, or keep the wait and do not ask Oliver.')),
        ("gate_ask_on_wait: …and names the event the wait stands on", lambda: G.gate_ask_on_wait("a1", item(), {"wait_kind": "event", "wait_event": "pr_merged quill/widgets#5", "needs": ["decision"]}, [], False), ('refused', 'Refused: a1 still waits on a fleet event (pr_merged quill/widgets#5); pass clear_wait=true with this update to drop the wait and ask Oliver, or keep the wait and do not ask Oliver.')),
        ("gate_ask_on_wait: a close, a decision already asked, no wait, a closed item and the guards off all pass", lambda: [
            G.gate_ask_on_wait("a1", item(), {"wait_kind": "time", "needs": ["decision"]}, [], True), G.gate_ask_on_wait("a1", item(), {"wait_kind": "time", "needs": ["decision"]}, ["decision"], False),
            G.gate_ask_on_wait("a1", item(), {"needs": ["decision"]}, [], False), G.gate_ask_on_wait("a1", item(status="completed"), {"wait_kind": "time", "needs": ["decision"]}, [], False),
            _guards_off(lambda: G.gate_ask_on_wait("a1", item(), {"wait_kind": "time", "needs": ["decision"]}, [], False))], ('ok', [None, None, None, None, ('ok', None)])),
        ("gate_owner_step: the owner's step under an agent's state is refused (an update)", lambda: _owner_step(), ('refused', "Refused: the first line of next is Oliver's step ('Oliver: paste it') but the item's state is doing, an agent's, so his step would sit hidden under it (a1). Pass step=<his step in one line>, or needs=decision with an ask; or open next with the agent who takes the step. Nothing was written. The item model: docs/design.")),
        ("gate_owner_step: …and a create says there is no state or step parameter", lambda: _owner_step(create=True), ('refused', "Refused: the first line of next is Oliver's step ('Oliver: paste it') but the item's state is doing, an agent's, so his step would sit hidden under it (a1). Set needs=decision with an ask (a create stores no state or step), or open next with the agent who takes the step. Nothing was written. The item model: docs/design.")),
        ("gate_owner_step: a state that is the owner's, or a first line that is an agent's, passes", lambda: [_owner_step(state="your-step"), _owner_step(next=f"{BACK}: go on")], ('ok', [None, None])),
        ("gate_decision_again: a decision put back within an hour of the owner's answer, with the same ask, is refused", lambda: G.gate_decision_again(_it4(), {"needs": ["decision"], "ask": "Which one?"}, [], "Which one?", "a4"), ('refused', 'Refused: Oliver answered a4 <ago>, and this write puts it back on his call with the same ask line: one ask per decision, and he is not asked again within 60 minutes of his answer. Act on his answer (write the next step), or, if a new question is open, pass the new ask line in this same write (ask=…): a question that has changed is a new ask')),
        ("gate_decision_again: a new ask line, a decision already asked, or an answer older than an hour passes", lambda: [
            G.gate_decision_again(_it4(), {"needs": ["decision"], "ask": "A different question?"}, [], "Which one?", "a4"), G.gate_decision_again(_it4(), {"needs": ["decision"], "ask": "Which one?"}, ["decision"], "Which one?", "a4"),
            G.gate_decision_again(_it4(ts=NOW - 7200), {"needs": ["decision"], "ask": "Which one?"}, [], "Which one?", "a4")], ('ok', [None, None, None])),
        ("gate_repark: the third move of a parked item's wake with nothing else changed is refused", lambda: _repark(2), ('ok', (('refused', 'Refused: a1 was re-parked 2 times in a row with nothing else changed, and this is the third move of its wake (<D+2> → <D+5>). A wait that keeps moving is not a wait: bring it to Oliver instead with needs=decision and an ask (keep it parked, drop it, or change the plan), or change something real on the item first (only a change to hold, wake, needs, after or the wait resets the count: an edit of next, the description or the basis text does not). When Oliver has just said to park it again, his words lift this: pass said=[…] with them, or ask him to answer on the item'), 2))),
        ("gate_repark: the first move counts, a change of substance resets", lambda: [_repark(0), _repark(1, mover=OTHER)], ('ok', [(('ok', None), 1), (('ok', None), None)])),
        ("gate_clock_renewal: a wake pushed out with nothing changed is refused", lambda: _clock(), ('ok', (('refused', 'Refused: a1 would have its clock pushed out (wake <D+2> → <D+9>) with its reason and its open steps exactly as they were: moving a date forward is not progress, and an item that keeps being re-dated is how work sits unseen. Change something real in the same write: mark a step done or dropped (done=[…], dropped=[…]), write the next step, or state the new reason (a new description). If the item now waits, say what on: park it (until=YYYY-MM-DD with wait_kind="time" and wait_basis=<what the date is, with its date>), or, for something that happens in the fleet, use the event-wait form (wait_kind="event", wait_event=<the event>, until=<the backstop day>, mover=<who takes it when it happens>). A wait_reason does not count (it is not stored). The item model: docs/design'), []))),
        ("gate_clock_renewal: …on a parked item, an item on the owner's call and an event wait, the way out differs", lambda: [_clock(hold=True), _clock(needs=["decision"]), _clock(wait_kind="event", wait_event="pr_merged quill/widgets#5")], ('ok', [(('refused', 'Refused: a1 would have its clock pushed out (wake <D+2> → <D+9>) with its reason and its open steps exactly as they were: moving a date forward is not progress, and an item that keeps being re-dated is how work sits unseen. Change something real in the same write: a new wait_basis (what the wait now rests on, with its date), or mark a step done or dropped (done=[…], dropped=[…]), write the next step, or state the new reason (a new description). If it waits on something that happens in the fleet, use the event-wait form (wait_kind="event", wait_event=<the event>, until=<the backstop day>, mover=<who takes it when it happens>) instead. A wait_reason does not count (it is not stored). The item model: docs/design'), []), (('refused', "Refused: a1 would have its clock pushed out (wake <D+2> → <D+9>) with its reason and its open steps exactly as they were: moving a date forward is not progress, and an item that keeps being re-dated is how work sits unseen. Change something real in the same write: mark a step done or dropped (done=[…], dropped=[…]), write the next step, or state the new reason (a new description). An item on Oliver's decision cannot be held, so the date stays as it is until a step or the reason changes. A wait_reason does not count (it is not stored). The item model: docs/design"), []), (('refused', 'Refused: a1 would have its clock pushed out (wake <D+2> → <D+9>) with its reason and its open steps exactly as they were: moving a date forward is not progress, and an item that keeps being re-dated is how work sits unseen. Change something real in the same write: mark a step done or dropped (done=[…], dropped=[…]), write the next step, or state the new reason (a new description), or change what the wait stands on (a different wait_event or wait_anchor, or after=[…] naming another item). The event-wait form is already in use, so a later until alone is only a later date. A wait_reason does not count (it is not stored). The item model: docs/design'), [])])),
        ("gate_clock_renewal: a new description, a step done, a pull-in or a first date passes", lambda: [_clock(description="a new reason"), _clock(steps_new=[STEP("marsh-builder: do it", "done")]), _clock(new=DAYS(1)), _clock(old="")], ('ok', [(('ok', None), []), (('ok', None), []), (('ok', None), []), (('ok', None), [])])),
        ("gate_after: not a list is refused", lambda: G.gate_after({"a": 1}, "a1"), ('refused', 'Refused: after is a list of item ids (or one comma-separated string)')),
        ("gate_after: an item that does not exist, itself, a closed one and a loop are refused", lambda: [outcome(lambda: G.gate_after(["a999"], "a1")), outcome(lambda: G.gate_after(["a1"], "a1")), outcome(lambda: G.gate_after(["a3"], "a1")), outcome(lambda: G.gate_after(["a2"], "a1"))], ('ok', [('refused', 'Refused: after names a999, which does not exist'), ('refused', 'Refused: a1 cannot wait on itself'), ('refused', 'Refused: a3 is already completed (done); after names open items that must close first'), ('refused', 'Refused: a loop: a2 itself waits on a1 (after), so a1 cannot wait on a2')])),
        ("gate_after: an open item passes, once, from a string too", lambda: [G.gate_after(["a2", "a2"], "a4"), G.gate_after("a2, a1", "a4")], ('ok', [['a2'], ['a2', 'a1']])),
        ("gate_sender_watch: a front agent's own wake on an item another session moves is refused", lambda: _watch(), ('ok', ('refused', "Refused: a front agent does not watch handed-off work itself (no wake or poll it sets): the result lands through stackshot when the mover closes the item or hands it back to you. a1 is moved by marsh-builder, so your date is refused: marsh-builder's close or hand-back reaches you through stackshot (a done `check` is allowed, and so is a park: until with wait_kind=\"time\" and wait_basis; within the wait cap's days it needs his recorded words). The date you may set is until on a wait, which the server watches. If no push exists, pass watch_reason=<why no push reaches you> with the same call: it is recorded on the item and the call goes through."))),
        ("gate_sender_watch: a watch_reason too short is refused; a real one is recorded", lambda: [_watch(watch_reason="no push"), _watch(watch_reason="nothing pushes the result to me here")], ('ok', [('refused', "Refused: watch_reason 'no push' is too short to name why no push exists (at least 15 characters)"), ('ok', 'nothing pushes the result to me here')])),
        ("gate_sender_watch: a sender that is no front agent, or an item no one else moves, passes", lambda: [_watch(front=False), _watch(others=[])], ('ok', [('ok', ''), ('ok', '')])),
        ("gate_handoff: a hand-off to a session with no pane is refused, naming the builder that has one", lambda: _handoff(), ('ok', ('refused', 'Refused: a1 cannot be handed to marsh-builder: the pane is closed, so the hand-off would never be read. The project has no background agent with a pane either: hand it to a session that has one, or put the call to Oliver (needs=decision with its ask).'))),
        ("gate_handoff: …and says so when no background agent has a pane either", lambda: _handoff(live=[]), ('ok', ('refused', 'Refused: a1 cannot be handed to marsh-builder: the pane is closed, so the hand-off would never be read. The project has no background agent with a pane either: hand it to a session that has one, or put the call to Oliver (needs=decision with its ask).'))),
        ("gate_handoff: a script's write, a hand-off the write did not name and a session with a pane pass", lambda: [_handoff(writer="a script (a script on testbox)"), _handoff(why=""), _handoff(named=False)], ('ok', [('ok', None), ('ok', None), ('ok', None)])),
        ("gate_cap: a wake past the cap with no words behind it is refused", lambda: G.gate_cap(item(), [], "wake", "2099-01-01", NOW + 90 * 86400), ('refused', 'Refused: a wait runs at most 7 days from the item\'s last move ([waiting] cap_days), and this wake (2099-01-01) is <n> days out. A longer one needs Oliver\'s words behind it: ask Oliver to answer on the item (his answer there counts until the item moves again); or, when his words are in your own transcript on this box, pass said=[{tag: Acked-by, quote: his sentence verbatim, msg: the uuid of his message}] (checked against the transcript, a message from the last 7 days); or, when the item waits for a date outside the board (a vendor\'s reply date, a release freeze), pass wait_basis="<what happens> YYYY-MM-DD" with it; or set a wake within 7 days and set it again then.')),
        ("gate_cap: within the cap, or with a basis, or with the cap off, it passes", lambda: [G.gate_cap(item(), [], "wake", FUT, NOW + 86400), G.gate_cap(item(), [], "wake", "x", NOW + 90 * 86400, "a vendor date 2099-01-01"),
                                                                                           _cap_off(lambda: G.gate_cap(item(), [], "wake", "x", NOW + 90 * 86400))], ('ok', ['', 'a real-world date', ('ok', '')])),
        ("gate_wait_basis: a completed item, no wake, a wake within the cap, a wake too far out, a text too short and a text with no date are refused", lambda: [
            outcome(lambda: G.gate_wait_basis(item(status="completed"), "The vendor visits 2099-03-10 14:00", "2099-03-10")), outcome(lambda: G.gate_wait_basis(item(), "The vendor visits 2099-03-10", "")),
            outcome(lambda: G.gate_wait_basis(item(), "The vendor visits tomorrow too", FUT)), outcome(lambda: G.gate_wait_basis(item(), "The vendor visits 2099-03-10", "2099-12-31")),
            outcome(lambda: G.gate_wait_basis(item(), "too short", DAYS(60), True)), outcome(lambda: G.gate_wait_basis(item(), "The vendor visits at some point", DAYS(60), True))], ('ok', [('refused', "Refused: a completed item waits for nothing; wait_basis goes with an open item's wake"), ('refused', "Refused: wait_basis explains the wake of a time wait (a park's or a verifying item's), or a wake past the cap, by the real-world date it waits for, and this item has no wake date. A park with no date is refused too: give the date (until=YYYY-MM-DD with wait_kind=\"time\", the date the outside event or Oliver's words give) and the basis with it"), ('refused', 'Refused: wait_basis is not needed: this wake (<D+3>) is <n> days out, within the 7 days a wait may run ([waiting] cap_days). It is for the wake of a time wait (a park, or a verifying item), which carries a reason at any length, and for a wake past the cap; a date alone within the cap is a wait on its own and needs none'), ('refused', 'Refused: wait_basis stands for a wake at most 365 days from now, and this wake (2099-12-31) is <n> days out. A wait that long is not a basis for the cap but a date to set again nearer the time'), ('refused', 'Refused: wait_basis is one line of 12 to 300 characters, what the wait stands on and its date ("The API token expires 2099-09-19") — got 9'), ('refused', 'Refused: wait_basis must name the real-world date the wait stands on as a real YYYY-MM-DD, from the wake or ask-by day (<D+60>) to 30 days after it: it names no date as YYYY-MM-DD. "The vendor visits Tue 2099-03-10 14:00" on a wake of 2099-03-10 is a basis; a date years off, or one that is not on the calendar, is a way around the rule. The forms it takes are "<what happens> YYYY-MM-DD" and, for a window the work itself needs, "<what the window collects> ends YYYY-MM-DD". Send the same call again with wait_basis="The vendor visits at some point <D+60>", the date being the day the wait ends')])),
        ("gate_wait_basis: a text too short on a wake too far out is refused for the wake first", lambda: outcome(lambda: G.gate_wait_basis(item(), "short", "2099-12-31", True)), ('ok', ('refused', 'Refused: wait_basis stands for a wake at most 365 days from now, and this wake (2099-12-31) is <n> days out. A wait that long is not a basis for the cap but a date to set again nearer the time'))),
        ("gate_wait_basis: a held wake (a hold, a verifying item) takes a basis at any length, cleaned", lambda: _basis_ok(), ('ok', ('ok', 'The vendor visits <D+60> 14:00'))),
        ("gate_cap: a wake past the cap on an item the owner has answered, with no basis", lambda: G.gate_cap(_it4(), [], "wake", "2099-01-01", NOW + 90 * 86400), ('ok', 'a board answer')),
        ("gate_cap: …and with a basis too", lambda: G.gate_cap(_it4(), [], "wake", "2099-01-01", NOW + 90 * 86400, "a vendor date 2099-01-01"), ('ok', 'a board answer')),
        # ---- the close and the words
        ("gate_close: nothing given names every field that is missing, with the accepted form", lambda: G.gate_close("a1", item(), "", "", "", ""), ('refused', 'Refused: closing a1 needs outcome, reason, outcome_text; accepted form: complete(item_id="a1", sender="my-x", outcome="done", reason="<one line: the end state and why it closes>", outcome_text="- <how it ended>"); outcome is done | dropped | superseded, and superseded takes superseded_by="board#M" too. If this tool shows no outcome, reason, outcome_text or superseded_by parameter, this session\'s cached tool list predates them: claude.ai refreshes it on its own within about a day, and a relaunch does not. Meanwhile close through the MCP Portal: portal_codemode_execute with codemode.stackshot_complete({item_id, outcome, reason, outcome_text, superseded_by}).')),
        ("gate_close: superseded with no replacing item names it", lambda: G.gate_close("a1", item(), "superseded", "done", "", "- text"), ('refused', 'Refused: closing a1 needs superseded_by; accepted form: complete(item_id="a1", sender="my-x", outcome="done", reason="<one line: the end state and why it closes>", outcome_text="- <how it ended>"); outcome is done | dropped | superseded, and superseded takes superseded_by="board#M" too.')),
        ("gate_close: unrecorded is only the migration's", lambda: G.gate_close("a1", item(), "unrecorded", "done", "", "- text"), ('refused', 'Refused: outcome unrecorded means the item closed before the model with no outcome in its record; only the migration writes it. A close says how it ended: done | dropped | superseded')),
        ("gate_close: an outcome that is none of the outcomes is refused", lambda: G.gate_close("a1", item(), "gone", "done", "", "- text"), ('refused', "Refused: outcome must be one of done | dropped | superseded — got 'gone'")),
        ("gate_close: a reason of two lines is refused", lambda: G.gate_close("a1", item(), "done", "one\ntwo", "", "- text"), ('refused', 'Refused: reason is one line: the end state reached and why the item closed')),
        ("gate_close: a reason over the instance's limit is refused", lambda: G.gate_close("a1", item(), "done", "x" * 4000, "", "- text"), ('refused', "Refused: the reason is 4000 characters and the limit is 120. Shorten it to the end state reached and why the item closed; the detail goes in the outcome_text bullets (and the project page's timeline).")),
        ("gate_close: a reason of two lines and over the limit is refused for both, its lines first", lambda: G.gate_close("a1", item(), "done", "x" * 200 + "\ny", "", "- text"), ('refused', _faults.combine(['Refused: reason is one line: the end state reached and why the item closed', f'Refused: the reason is 202 characters and the limit is 120. Shorten it to the end state reached and why the item closed; the detail goes in the outcome_text bullets (and the project page\'s timeline).']))),
        ("gate_close: an outcome that is unrecorded with nothing else given is refused for both, the missing fields first", lambda: G.gate_close("a1", item(), "unrecorded", "", "", ""), ('refused', _faults.combine(['Refused: closing a1 needs reason, outcome_text; accepted form: complete(item_id="a1", sender="my-x", outcome="done", reason="<one line: the end state and why it closes>", outcome_text="- <how it ended>"); outcome is done | dropped | superseded, and superseded takes superseded_by="board#M" too.', 'Refused: outcome unrecorded means the item closed before the model with no outcome in its record; only the migration writes it. A close says how it ended: done | dropped | superseded']))),
        ("gate_close: an outcome_text that fails the description's checks is refused with them", lambda: G.gate_close("a1", item(), "done", "the end state", "", "no bullet here"), ('refused', 'Refused: outcome_text line is not a `- ` bullet: "no bullet here"; write short `- ` bullets, one fact each (at most 8 lines of 120 characters; parallel bullets such as batches, steps or parts go under one parent bullet, indented two spaces); details go on the project page')),
        ("gate_close: superseded_by goes with superseded only; not to itself; the item must exist", lambda: [
            outcome(lambda: G.gate_close("a1", item(), "done", "the end state", "a2", "- the result")), outcome(lambda: G.gate_close("a1", item(), "superseded", "the end state", "a1", "- the result")),
            outcome(lambda: G.gate_close("a1", item(), "superseded", "the end state", "a999", "- the result"))], ('ok', [('refused', 'Refused: superseded_by goes with outcome=superseded, not done'), ('refused', 'Refused: a1 cannot be superseded by itself'), ('refused', 'Refused: superseded_by names a999, which does not exist; name the item that replaces a1')])),
        ("gate_close: a good close gives the replacing item's id, or none", lambda: [G.gate_close("a1", item(), "superseded", "the end state", "a2", "- the result"), G.gate_close("a1", item(), "done", "the end state", "", "- the result")], ('ok', ['a2', ''])),
        ("gate_said: a spec that opens like JSON and does not parse is refused", lambda: G.gate_said("[not a list of entries", BACK, OTHER), ('refused', 'Refused: said: not valid JSON (it starts \'[not a list of entries\'); pass a list of objects, said=[{tag: Acked-by | Suggested-by | Reported-by, quote: his sentences cut verbatim, msg: the uuid of his message, session: where he said it (optional)}], or, to prove he did his steps from a message he sent while the session worked (a queued_command attachment entry, origin human), {kind: acted, quote: a piece of its text verbatim, msg: the uuid of the attachment entry, session (optional)}. As JSON, with its keys and values in double quotes: said=[{"tag": "Acked-by", "quote": "<his sentences, cut verbatim>", "msg": "00000000-0000-4000-8000-000000000000"}] (the zero uuid stands for the uuid of his message)')),
        ("gate_said: nothing passed gives []", lambda: [G.gate_said(None, BACK, OTHER), G.gate_said([], BACK, OTHER), G.gate_said("  ", BACK, OTHER)], ('ok', [[], [], []])),
        ("gate_said: a message that is not in the session's transcript is refused with the entry and the test", lambda: _said([{"tag": "Acked-by", "quote": "go ahead", "msg": "bbbbbbbb-bbbb-4bbb-8bbb-000000000000", "session": SAID_SESSION}]), ('ok', ('refused', "Refused: said[0] (Acked-by): no message bbbbbbbb-bbbb-4bbb-8bbb-000000000000 in the transcript of 11111111-2222-4333-8444-555555555555; msg is the `uuid` field of his message's transcript entry, and session is the session he said it in (the front session when his words reached you relayed)"))),
        ("gate_said: a message of his own passes, checked; a quote that is not in it is refused", lambda: [_said([{"tag": "Acked-by", "quote": "go ahead", "msg": M1, "session": SAID_SESSION}]), _said([{"tag": "Acked-by", "quote": "not what he wrote", "msg": M1, "session": SAID_SESSION}])], ('ok', [('ok', [{'tag': 'Acked-by', 'quote': 'go ahead', 'session': '11111111-2222-4333-8444-555555555555', 'msg': 'aaaaaaaa-aaaa-4aaa-8aaa-000000000001', 'ts': '<t>', 'checked': True, 'prompt_source': '', 'by': 'home-other'}]), ('refused', 'Refused: said[0] (Acked-by): the quote is not in the message (whitespace aside, the quote is cut verbatim from his words) (message aaaaaaaa-aaaa-4aaa-8aaa-000000000001 in the transcript of 11111111-2222-4333-8444-555555555555)')])),
        ("gate_said: a message that is no message of his (a tool's result) is refused", lambda: _said([{"tag": "Acked-by", "quote": "go ahead", "msg": M2, "session": SAID_SESSION}]), ('ok', ('refused', "Refused: said[0] (Acked-by): message aaaaaaaa-aaaa-4aaa-8aaa-000000000002 in the transcript of 11111111-2222-4333-8444-555555555555 is not Oliver's own: it is a tool result"))),
        ("gate_said: a session whose transcript this box has not is stored unchecked", lambda: _said([{"tag": "Acked-by", "quote": "go ahead", "msg": M1, "session": "00000000-0000-4000-8000-0000000000ff"}]), ('ok', ('ok', [{'tag': 'Acked-by', 'quote': 'go ahead', 'session': '00000000-0000-4000-8000-0000000000ff', 'msg': 'aaaaaaaa-aaaa-4aaa-8aaa-000000000001', 'ts': 0.0, 'checked': False, 'prompt_source': '', 'by': 'home-other', 'why': 'no transcript for this session on this box'}]))),
        ("gate_front_step: a new step that opens with a front agent, on an item another session moves, is refused: give it to the mover", lambda: G.gate_front_step("a1", item(mover=BACK), [], [STEP(f"{FRONT}: check it")], OTHER), ('refused', 'Refused: the step "quill-agent: check it" opens with quill-agent, a user-facing agent of projects/quill: it gets no work notice and its own wakes are refused, so nothing would wake it for the step, and marsh-builder moves a1. Give the step to marsh-builder (open it with "marsh-builder:"), or ask quill-agent with a message to projects/quill whose first line starts "For quill-agent,".')),
        ("gate_front_step: …and the mover writing it is told to keep the step, hand the item over or ask through the page", lambda: G.gate_front_step("a1", item(mover=BACK), [], [STEP(f"{FRONT}: check it")], BACK), ('refused', 'Refused: the step "quill-agent: check it" opens with quill-agent, a user-facing agent of projects/quill: it gets no work notice and its own wakes are refused, so nothing would wake it for the step, and marsh-builder moves a1. Keep the step with marsh-builder, hand quill-agent the item with mover=quill-agent (only between front agents of one project that has no builder), or ask quill-agent with a message to projects/quill whose first line starts "For quill-agent,".')),
        ("gate_front_step: …and a create (no id) says the item", lambda: G.gate_front_step("", item(mover=BACK), [], [STEP(f"{FRONT}: check it")], OTHER), ('refused', 'Refused: the step "quill-agent: check it" opens with quill-agent, a user-facing agent of projects/quill: it gets no work notice and its own wakes are refused, so nothing would wake it for the step, and marsh-builder moves the item. Give the step to marsh-builder (open it with "marsh-builder:"), or ask quill-agent with a message to projects/quill whose first line starts "For quill-agent,".')),
        ("gate_front_step: a step held before, one a background agent or the owner opens, a closed item, an item the owner moves and an item no session moves (its page names a keeper that is retired, no builder) pass", lambda: [
            G.gate_front_step("a1", item(mover=BACK), [STEP(f"{FRONT}: check it")], [STEP(f"{FRONT}: check it")], OTHER), G.gate_front_step("a1", item(mover=BACK), [], [STEP(f"{BACK}: check it")], OTHER),
            G.gate_front_step("a1", item(mover=BACK), [], [STEP(f"{OWNER}: check it")], OTHER), G.gate_front_step("a1", item(status="completed", mover=BACK), [], [STEP(f"{FRONT}: check it")], OTHER),
            outcome(lambda: G.gate_front_step("a1", item(mover=OWNER), [], [STEP(f"{FRONT}: check it")], OTHER)), outcome(lambda: G.gate_front_step("a1", item(project="projects/hush", next="hush-watch: do it"), [], [STEP("hush-main: check it")], OTHER))], ('ok', [None, None, None, None, ('ok', None), ('ok', None)])),
        ("gate_step_gap: a session's step that delivers a pull request with another session's step after it is refused", lambda: _gap(), ('ok', ('refused', 'Refused: step 2 (marsh-builder: release PR #12 and tell the keeper) delivers #12 and another session\'s step follows: split it so `release PR #12` is a step of its own (it ticks itself), or, if the PR landing finishes the step, add step_proof=[{"step": 2, "proof": "pr_released #12"}] (another repository\'s PR: pr_merged <owner>/<repo>#<n>)'))),
        ("gate_step_gap: …unless it carries its proof, and a write that is no session's passes", lambda: [_gap(proof=True), _gap(session=False)], ('ok', [('refused', 'Refused: step 2 (marsh-builder: release PR #12 and tell the keeper) delivers #12 and another session\'s step follows: split it so `release PR #12` is a step of its own (it ticks itself), or, if the PR landing finishes the step, add step_proof=[{"step": 2, "proof": "pr_released #12"}] (another repository\'s PR: pr_merged <owner>/<repo>#<n>)'), ('ok', None)])),
    ]

    def _with(mod, name, fn, thunk):
        old = getattr(mod, name); setattr(mod, name, fn)
        try: return thunk()
        finally: setattr(mod, name, old)
    @contextlib.contextmanager
    def _off():
        with srv(_model_guards_on=lambda: False): yield
    def _guards_off(thunk):
        with _off(): return outcome(thunk)
    def _cap_off(thunk):
        old = _cfg.CFG.get("waiting"); _cfg.CFG["waiting"] = {**(old or {}), "cap_needs_owner": False}
        try: return outcome(thunk)
        finally:
            if old is None: _cfg.CFG.pop("waiting", None)
            else: _cfg.CFG["waiting"] = old
    def _self_wait_case(creating=False):
        seen = []
        def gate(**kw): seen.append(scrub(kw)); return "the step can be done now"
        with patched(_cfg, wait_guard_on=lambda: True), patched(_selfwait, gate=gate):
            if creating: out = outcome(lambda: G.gate_self_wait("", BACK, mover=BACK, wake=FUT, wait_reason="x", creating={"subject": "[home] a new item", "project": PROJECT}))
            else: out = outcome(lambda: G.gate_self_wait("a1", BACK, wake=FUT, wait_reason="x"))
        return out, [{k: (v if k != "now" else "<now>") for k, v in s.items()} for s in seen]
    def _seen_step():
        seen = []
        def prob(it, prior, step_set): seen.append((prior, step_set)); return ""
        with patched(_sc, problem=prob): G.gate_step(item(), "a1", "the earlier description", True)
        return seen
    def _owner_step(create=False, state="doing", next=f"{OWNER}: paste it"):
        with srv(_eff_state=lambda it: state): return G.gate_owner_step(item(next=next), "a1", create=create, sender=BACK)
    def _it4(ts=None):
        it = item(mover=BACK); it["metadata"]["answers"] = [{"text": "go", "ts": ts if ts is not None else NOW - 120, "ask": "Which one?"}]
        return it
    def _repark(n, **change):
        was = item(**{"hold": True, "wake": DAYS(2), "repark": n, "mover": BACK}); now = item(**{"hold": True, "wake": DAYS(5), "repark": n, "mover": BACK, **change}); meta = dict(now["metadata"])
        with srv(_eff_state=lambda it: "parked"):
            out = outcome(lambda: G.gate_repark(was, {**now, "metadata": meta}, meta, "a1", []))
        return out, meta.get("repark")
    def _clock(old=None, new=None, hold=False, needs=None, description="", steps_new=None, wait_kind="", wait_event=""):
        base = {"mover": BACK, "wake": DAYS(2) if old is None else old}
        if hold: base["hold"] = True
        if needs: base["needs"] = needs
        if wait_kind: base.update(wait_kind=wait_kind, wait_event=wait_event)
        was = item(**base); meta = {**base, "wake": DAYS(9) if new is None else new}
        steps = [STEP("marsh-builder: do it")]
        with srv(_eff_state=lambda it: "parked" if hold else "doing"):
            return outcome(lambda: G.gate_clock_renewal(was, meta, "a1", steps, steps_new if steps_new is not None else steps, description or "- A thing", [], BACK)), sorted(k for k in meta if k.startswith("clock"))
    def _watch(front=True, others=("marsh-builder",), watch_reason=""):
        with tel(front_sender=lambda s: front), patched(G, _watch_others=lambda it, s, handed: list(others)):
            return outcome(lambda: G.gate_sender_watch("a1", item(mover=BACK), FRONT, handed=[BACK], watch_reason=watch_reason))
    def _handoff(writer=OTHER, why="the pane is closed", live=(BACK,), named=True):
        after = item(mover=BACK if named else OWNER); before = item(mover=KEEP)
        with patched(handoff_svc, handoff_on=lambda: True, handoff_pane=lambda to: why if to == U["marsh-builder"] or to == BACK else "", handoff_background=lambda p: list(live)):
            return outcome(lambda: G.gate_handoff("a1", before, after, writer))
    def _for_peer_rows():
        """the advice for a peer on the top-level page: from the top-level key, also for an item filed under a sub-page"""
        return [G._for_peer("ember-desk", "projects/ember"), G._for_peer("ember-desk", "projects/ember/side"), G._for_peer("side-desk", "projects/ember/side")]
    def _roles_fail():
        with srv(_role_of=lambda *a, **k: 1 / 0): return G.fix_front_mover("mover", FRONT, OTHER, PROJECT, "", {})
    def _basis_ok():
        return outcome(lambda: G.gate_wait_basis(item(), f"  The vendor   visits {DAYS(60)} 14:00 ", DAYS(60), True))
    SAID_SESSION = "11111111-2222-4333-8444-555555555555"
    M1, M2 = "aaaaaaaa-aaaa-4aaa-8aaa-000000000001", "aaaaaaaa-aaaa-4aaa-8aaa-000000000002"
    (T / f"transcripts/-home-x/{SAID_SESSION}.jsonl").write_text("\n".join(json.dumps(e) for e in (
        {"type": "user", "uuid": M1, "timestamp": "2099-01-01T00:00:00.000Z", "origin": {"kind": "human"}, "message": {"role": "user", "content": "go ahead and do it"}},
        {"type": "user", "uuid": M2, "timestamp": "2099-01-01T00:00:01.000Z", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "go ahead"}]}})) + "\n", encoding="utf-8")
    def _said(specs): return outcome(lambda: G.gate_said(specs, BACK, OTHER))
    def _gap(proof=False, session=True):
        old = [STEP("marsh-builder: write it")]
        new = old + [STEP("marsh-builder: release PR #12 and tell the keeper"), STEP("quill-agent: check it")]
        meta = {"step_proof": {}} if not proof else {"step_proof": {"2": "pr_merged #12"}}
        with flags(session_next=session): return outcome(lambda: G.gate_step_gap(meta, new, old))

    # the order the gates run in for a write: each gate replaced by a recorder that calls the real one, an update run through the tool's own function
    recorded = []
    def wrap(name, fn):
        def run(*a, **k):
            recorded.append(re.sub(r"^_", "", name))
            return fn(*a, **k)
        return run
    def recording(thunk):
        recorded.clear()
        real = {n: getattr(G, n) for n in GATES}
        with patched(G, **{n: wrap(n, real[n]) for n in GATES}): out = outcome(thunk)
        return out, list(recorded)
    UPDATES = (("an update that asks the owner while the item waits", dict(sender=BACK, next=f"{BACK}: do it", needs=["decision"], ask="Decide: which one to ship · Recommend: the small one · Stakes: a day · By: tomorrow", wake=FUT, hold=True, wait_reason="the vendor visits on the date"), "1"),
               ("an update that parks the item with a wake, a hold and the wait's reason", dict(sender=BACK, next=f"{BACK}: do it", wake=FUT, hold=True, wait_reason="the vendor visits on the date"), "4"),
               ("an update that moves the mover, sets an until and watches", dict(sender=OTHER, mover=BACK, next=f"{BACK}: do it", until=FUT), "5"),
               ("an update that closes the item", dict(sender=BACK, status="completed", outcome="done", reason="the end state", outcome_text="- the result"), "6"))
    def update_order(kw, n):
        put(int(n), mover=BACK)
        with patched(_web_publish, _publish=lambda *a, **k: None), tel(tell_woken=lambda *a, **k: None):
            return recording(lambda: _wt_update.stackshot_update(f"a{n}", **kw))
    # the label -> the gates in the order they run (GATES_MAIN=1 prints each ORDER line); a gate that refuses does not stop the ones after it: the write's form and state gates all run, and the refusal holds every fault
    ORDER_WANT = {
        'an update that asks the owner while the item waits':
            ["until_in", "gate_self_wait", "gate_busy_hold", "ask_pre", "gate_needs", "gate_state_args", "gate_draft_args", "gate_model_args", "gate_said", "gate_cap", "gate_ask_on_wait", "gate_step_gap", "gate_sender_watch", "gate_decision_again", "gate_clock_renewal", "gate_repark", "gate_model", "gate_owner_step", "gate_handoff", "gate_front_step"],
        "an update that parks the item with a wake, a hold and the wait's reason":
            ["until_in", "gate_self_wait", "gate_busy_hold", "ask_pre", "gate_state_args", "gate_draft_args", "gate_model_args", "gate_said", "gate_cap", "gate_ask_on_wait", "gate_step_gap", "gate_sender_watch", "gate_decision_again", "gate_clock_renewal", "gate_repark", "gate_model", "gate_owner_step", "gate_handoff", "gate_front_step"],
        'an update that moves the mover, sets an until and watches':
            ["fix_front_mover", "fix_front_mover", "fix_front_mover", "until_in", "gate_self_wait", "gate_busy_hold", "ask_pre", "gate_state_args", "gate_draft_args", "gate_model_args", "gate_said", "gate_cap", "gate_ask_on_wait", "gate_step_gap", "gate_sender_watch", "gate_decision_again", "gate_clock_renewal", "gate_repark", "gate_model", "gate_owner_step", "gate_draft", "gate_step", "gate_handoff", "gate_front_step"],
        'an update that closes the item':
            ["until_in", "gate_self_wait", "gate_busy_hold", "ask_pre", "gate_state_args", "gate_draft_args", "gate_model_args", "gate_said", "gate_close", "gate_ask_on_wait"],
    }

    # ---------------------------------------------------------------- what a main run prints
    def run_cases():
        return [(label, outcome(thunk)) for label, thunk, _want in CASES]
    if MAIN:
        for label, got in run_cases(): print("CASE\t" + label); print("WANT\t" + repr(got))
        for label, kw, n in UPDATES:
            out, order = update_order(kw, n)
            print("ORDER\t" + label + "\t" + json.dumps(order)); print("RESULT\t" + repr(out)[:300])
        _scratch.cleanup() if hasattr(_scratch, "cleanup") else None
        sys.exit(0)

    # ---------------------------------------------------------------- 1. refusals
    for label, thunk, want in CASES:
        got = outcome(thunk)
        check(f"1 {label}", got == want, f"\n  got  {got!r}\n  want {want!r}")

    # ---------------------------------------------------------------- 2. flags
    PROBS = lambda *keys: ([_mg.Problem(k, f"the {k} guard says no") for k in keys], [])
    def model_with(probs_keys, **kw):
        with patched(_mg, check=lambda *a, **k: PROBS(*probs_keys)), flags(**kw): return outcome(lambda: G.gate_model(item(), None, "a1"))
    check("2 gate_model with no flag: every problem is refused, in one sentence each", model_with(("alarm", "description", "next_defers", "owner_mover")) == ("refused", "Refused: 3 problems. (1) the alarm guard says no (2) the next_defers guard says no (3) the owner_mover guard says no"), model_with(("alarm", "description", "next_defers", "owner_mover")))
    check("2 a script's question is judged on neither alarm words, the description nor next_defers", model_with(("alarm", "description", "next_defers", "mover"), question=True) == ("refused", "Refused: the mover guard says no"), model_with(("alarm", "description", "next_defers", "mover"), question=True))
    check("2 the terminal prompt's row is judged on neither next_defers nor owner_mover", model_with(("next_defers", "owner_mover", "mover"), terminal_row=True) == ("refused", "Refused: the mover guard says no"), model_with(("next_defers", "owner_mover", "mover"), terminal_row=True))
    check("2 the re-bullet route is judged on no owner_mover", model_with(("owner_mover", "mover"), reformat=True) == ("refused", "Refused: the mover guard says no") and model_with(("owner_mover",), reformat=True) == ("ok", ""), model_with(("owner_mover", "mover"), reformat=True))
    check("2 a write with no flag is judged on owner_mover too", model_with(("owner_mover",)) == ("refused", "Refused: the owner_mover guard says no"), model_with(("owner_mover",)))
    with patched(_mg, check=lambda *a, **k: PROBS("description")):
        got = [outcome(lambda: G.gate_model(item(), None, "a1")), outcome(lambda: G.gate_model(item(), None, "a1", desc_set=False))]
    check("2 a description problem is the reply's note in note mode, never a refusal; a write that sets no description is not judged on it", got == [("ok", "\n(note: the description guard says no)"), ("ok", "")], got)
    with patched(_mg, check=lambda *a, **k: 1 / 0):
        got = [outcome(lambda: G.gate_model(item(), None, "a1")), outcome(lambda: G.gate_model(item(), None, "a1", strict=True))]
    check("2 a failing check lets the write through; with strict (the migration) it is refused", got == [("ok", ""), ("refused", "Refused: the guards could not judge this write (ZeroDivisionError); the migration makes none that they have not judged")], got)
    check("2 a closed item, and a write with the guards off, are never judged", [outcome(lambda: G.gate_model(item(status="completed"), None, "a1")), _guards_off(lambda: G.gate_model(item(), None, "a1"))] == [("ok", ""), ("ok", "")])
    check("2 gate_step_gap reads the session's-own-write flag when it runs: off, no judgement; on, the gap is refused", [_gap(session=False)[0], _gap(session=True)[0]] == ["ok", "refused"], [_gap(session=False), _gap(session=True)])
    class Spy:
        """A flag object that counts its reads."""
        def __init__(self): self.reads = 0; self._on = False
        @property
        def on(self): self.reads += 1; return self._on
        @on.setter
        def on(self, v): self._on = v
    spy = Spy()
    with patched(FLAGMOD, **{flagname("SESSION_NEXT"): spy}):
        _gap()
    check("2 …and reads the flag on its module when the gate runs, not when the module was imported", spy.reads >= 1, spy.reads)
    real_q = getattr(FLAGMOD, flagname("QUESTION"))
    with patched(_mg, check=lambda *a, **k: PROBS("alarm", "mover")):
        setattr(FLAGMOD, flagname("QUESTION"), type("F", (), {"on": True})())
        try: got = outcome(lambda: G.gate_model(item(), None, "a1"))
        finally: setattr(FLAGMOD, flagname("QUESTION"), real_q)
    check("2 a flag object swapped out on its module is the one the gate reads (the name is looked up when it runs)", got == ("refused", "Refused: the mover guard says no"), got)

    # ---------------------------------------------------------------- 3. order
    # a gate that calls another gate calls it on its own module (the order inside a gate)
    check("3 gate_needs asks gate_needs_session for each name that is no kind, in order", recording(lambda: G.gate_needs([BACK, "decision", KEEP], PROJECT, ""))[1] == ["gate_needs", "gate_needs_session", "gate_needs_session"], recording(lambda: G.gate_needs([BACK, "decision", KEEP], PROJECT, "")))
    check("3 each of the gates is a function of the module, and a recorder replaces and restores it", all(callable(getattr(G, n)) for n in GATES) and recording(lambda: None)[1] == [], GATES)
    for label, kw, n in UPDATES:
        out, order = update_order(kw, n)
        check(f"3 {label}: it ran through the gates (a refusal is the gate's, a pass is the write's)", bool(order) and out[0] in ("ok", "refused"), (out, order))
        check(f"3 {label}: the gates run in the order main ran them", order == ORDER_WANT[label], f"\n  got  {order}\n  want {ORDER_WANT[label]}")
    # ---------------------------------------------------------------- 4. hooks
    saved = gates._hooks_
    gates._hooks_ = None
    try:
        got = [outcome(lambda: gates.gate_close("a1", item(), "done", "r", "", "- t")), outcome(lambda: gates.gate_after([], "a1")), outcome(lambda: gates.gate_cap(item(), [], "wake", "x", NOW + 86400))]
    finally: gates._hooks_ = saved
    check("4 a gate that needs the hooks and finds none is refused with a message that names the install", all(g[0] == "raised" and "no hooks installed" in g[1] for g in got), got)
    fields = [f.name for f in dataclasses.fields(gates.Hooks)]
    check("4 the table the server installed has every hook of the dataclass", gates._hooks_ is not None and [f for f in fields if not hasattr(gates._hooks_, f)] == [] and len(fields) >= 37, fields)
    try: gates.Hooks(**{f: None for f in fields[:-1]}); built = True
    except TypeError: built = False
    check("4 a table with a hook missing cannot be built", not built)
    _first = gates._hooks_
    try:
        _other = dataclasses.replace(_first, relaunch="a later table")
        gates.install(_other)
        replaced = gates._hooks_ is _other and gates._hooks().relaunch == "a later table"
    finally: gates.install(_first)
    check("4 install replaces the table (the last one installed is the one the gates read), and the first can be put back", replaced and gates._hooks_ is _first, replaced)
    with srv(_model_guards_on=lambda: False):
        check("4 a hook that is a function is looked up on the server when the gate runs: a patched _model_guards_on reaches gate_draft", gates._hooks().model_guards_on() is False)
    check("4 the hand-off functions the gates use are the hand-off module's own, not hooks (a patched one is set on service/handoff.py)", not hasattr(gates._hooks(), "handoff_pane") and not hasattr(gates._hooks(), "ho_same") and gates._handoff is handoff_svc)
    check("4 a value hook is the server's own value (the sentence a refused close ends with, the close rule, the outcomes)", gates._hooks().relaunch == _owner_words._RELAUNCH and gates._hooks().close_refusal == _wt_text._CLOSE_REFUSAL and gates._hooks().outcomes == _owner_words.OUTCOMES)

    # ---------------------------------------------------------------- 5. shape
    GATES_SRC = pathlib.Path(STACK, "stackshot/service/gates.py").read_text(encoding="utf-8")
    tree = ast.parse(GATES_SRC)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom): imported += [f"{node.module}.{a.name}" if node.module else a.name for a in node.names] + [node.module or ""]
    check("5 gates.py imports no web module and no audit module (the layers: service sits under web and imports no audit/)", not [m for m in imported if m.startswith(("stackshot.web", "stackshot.audit"))], [m for m in imported if m.startswith(("stackshot.web", "stackshot.audit"))])
    nested = [n for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(fn) if isinstance(n, (ast.Import, ast.ImportFrom))]
    check("5 …and no function of it imports anything when it runs (every import is at the top)", not nested, [ast.dump(n)[:80] for n in nested])
    SERVER_SRC = pathlib.Path(STACK, "stackshot/web/server.py").read_text(encoding="utf-8")
    stree = ast.parse(SERVER_SRC)
    defined = {n.name for n in stree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))} | {t.id for n in stree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    moved_defs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name not in ("install", "_hooks")} | {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name) and t.id != "_hooks_"}
    old_names = {("_" + n if n.startswith("gate_") or n in PUBLIC else n) for n in moved_defs}
    check("5 server.py defines none of the bodies and constants that moved", not (defined & old_names), sorted(defined & old_names))
    rebound = [a.asname or a.name for n in ast.walk(stree) if isinstance(n, ast.ImportFrom) and n.module == "stackshot.service.gates" for a in n.names]
    check("5 …and re-exports none of them under an old name (no `from stackshot.service.gates import`, no alias assigned)", not rebound and not [n for n in old_names if re.search(rf"^{re.escape(n)}\s*=\s*_?gates\.", SERVER_SRC, re.M)], rebound)
    check("5 …and each GATES name exists in gates.py as a function", all(isinstance(getattr(gates, n), type(check)) for n in GATES) and set(GATES) <= moved_defs, sorted(set(GATES) - moved_defs))
    called = set()
    for f in ("stackshot/service/update.py", "stackshot/service/create.py", "stackshot/web/server.py", "stackshot/web/wiring.py", "stackshot/web/tools/create.py", "stackshot/web/tools/update.py"):
        for node in ast.walk(ast.parse(pathlib.Path(STACK, f).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "_gates": called.add(node.attr)
    missing = sorted(n for n in called if not hasattr(gates, n))
    check("5 every name the server, the tool modules and the two services take from `_gates` exists on it", not missing and {"gate_cap", "gate_model", "gate_after", "gate_close", "fix_front_mover", "until_in", "ask_pre"} <= called, (missing, sorted(called)))
    hook_gates = []
    for f in ("stackshot/service/update.py", "stackshot/service/create.py"):
        for node in ast.walk(ast.parse(pathlib.Path(STACK, f).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr.startswith("gate_") and isinstance(node.value, ast.Name) and node.value.id in ("h", "hk"): hook_gates.append(f"{f}:{node.attr}")
    stayed = {"gate_ask", "gate_options"}
    check("5 the two services reach through their hooks only the gates that stayed on the server (the ask's and the options' checks); the field and decision rules are model/'s, called on their modules", all(x.split(":", 1)[1] in stayed for x in hook_gates), [x for x in hook_gates if x.split(":", 1)[1] not in stayed])

    return ran, fails


# ================================================================ part form: one refusal for the faults of a call
def part_form():
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix="formgatestest-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    for d in ("store/a", "fleet/a", "state/s1", "brain/projects", "brain/infra"): (T / d).mkdir(parents=True)
    NAMES = ("falcon-main", "home-other")
    U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
    (T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
    def page(rel, front):
        q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
    page("projects/example.md", "type: project\ntitle: Stackshot\ndisplay-name: falcon\nagents:\n  falcon-main: builds it\nstatus: active")
    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

    from stackshot.projects import pages as p
    p.cmd_registry(quiet=True)
    from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
    from stackshot.service import update as _update_svc
    from stackshot.service import store as _service_store
    from stackshot.service import gates as G
    from stackshot.core import config as _cfg
    from stackshot.core import call_log as CL
    from stackshot.tools import refusal_report as RR
    from stackshot.web import middleware as _wmw
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    from stackshot.model import ids as _model_ids
    from stackshot.model import bullet_text as BT
    from stackshot.model import field_gates as _fg
    from stackshot.model import steps as S
    from stackshot.model import work as WK
    from stackshot.waits import waiting as W
    from stackshot.waits import wait_list_write as _wlw
    from stackshot.web.tools import create as _wt_create
    from stackshot.web.tools import update as _wt_update
    from fastmcp.exceptions import ToolError
    _cfg.CFG.setdefault("model", {})["guards"] = False      # fixture owners the fleet does not know; the write guards have their own suite
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    _web_page_debts._owing_note = lambda debtor: ""

    MAIN = "falcon-main"; OTHER = "home-other"; STK = "projects/example"
    DESC = "- Goal: A thing\n- It lives here\n- Done when done"
    SUBJ_MAX = int(_cfg.CFG["subject"]["max_length"]); assert SUBJ_MAX == 80, SUBJ_MAX
    NOW = time.time()
    def item(i, next_="falcon-main: build it\nfalcon-main: test it", subject="[home] a thing", desc=DESC, **meta):
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": desc, "status": "open", "updated": NOW - 3600, "state_updated": NOW - 3600, "confirmed": NOW - 3600,
                                                         "metadata": {"owner": U[MAIN], "project": STK, "needs": [MAIN], "next": next_, **meta}}))
    def digits(i): return re.sub(r"\D", "", str(i))
    def rd(i):
        """a seeded item by its number, or a created one by the gid its reply names"""
        if i == "" or i is None:
            return {"subject": "", "description": "", "metadata": {}}          # a refused create has no gid: the check that reads it then fails with its message, no crash
        return _service_store._load(i) if isinstance(i, str) and not i.isdigit() else json.loads((T / f"store/a/{i}.json").read_text())
    def mt(i): return rd(i)["metadata"]
    def fx(fn):
        """(the result or the ToolError, [(kind, note)] the call made)"""
        tok = CL.begin()
        try: res = fn()
        except ToolError as e: res = e
        finally: made = CL.end(tok)
        return res, made
    kinds = lambda made: [k for k, _ in made]
    def upd(i, **kw): return fx(lambda: _wt_update.stackshot_update(f"a{i}", sender=kw.pop("sender", MAIN), **kw))          # a session's write
    def script(i, **kw): return fx(lambda: _update_svc._update(f"a{i}", sender=MAIN, **kw))                                  # a script's write (not the tool's own call)
    def create(subject="[home] a thing", desc=DESC, **kw):
        kw.setdefault("next", f"{MAIN}: carry on")
        return fx(lambda: _wt_create.stackshot_create(subject=subject, description=desc, project=STK, owner=MAIN, **kw))
    def gid_of(res): return _model_ids._norm_id(res.split()[1]) if isinstance(res, str) else ""
    def subj(g): return rd(g)["subject"] if g else ""          # a refused create has no gid: the check then fails with its message, no crash
    def num(g): return re.sub(r"\D", "", g)

    URL = "https://example.com/a/b?c=1"
    def local_day(n): return (dt.datetime.now(_cfg.tz()) + dt.timedelta(days=n)).strftime("%Y-%m-%d")
    def msg(res): return str(res) if isinstance(res, ToolError) else ""
    def show(label, res): print(f"--- {label}\n{msg(res) or res}")
    HEAD = "Refused: {n} problems in this call; fix all of them and send the call once more.\n"
    def parts(res):
        """the numbered faults of a combined refusal, in order, and the line of checks not made ('' when none)"""
        t = msg(res)
        body, _, skipped = t.partition("\nNot checked yet")
        got = re.split(r"\n\((\d+)\) ", body)
        return [got[k + 1] for k in range(1, len(got), 2)], ("Not checked yet" + skipped if skipped else "")
    def unchanged(i, before):
        return rd(i)["subject"] == before["subject"] and rd(i)["description"] == before["description"] and rd(i)["metadata"].get("next") == before["metadata"].get("next") and not rd(i)["metadata"].get("hold")
    NOGOAL = "- no goal here\n- another"

    # ================================================================ 1. an update with several faults in the words of its fields: one refusal
    item(1)
    was = rd(1)
    res, made = upd(1, subject="no prefix at all", description=NOGOAL, next=f"falcon-main: read {URL}\nfalcon-main: test it")
    fl, skipped = parts(res)
    check("1 three faults in the words (subject, description, next): one refusal that counts them on its first line", msg(res).startswith(HEAD.format(n=3) + "(1) "), msg(res)[:200])
    check("1 …each fault has its own numbered line, in the gates' order, with the text its gate gives it alone", len(fl) == 3 and "bare URL" in fl[0] and fl[1].startswith("subject must start with one of") and fl[2].startswith("the description must open with its goal"), fl)
    check("1 …the corrected description the goal gate shows is there once, with its example", msg(res).count("- Goal: no goal here\n- another") == 1 and skipped == "", msg(res)[:500])
    check("1 …nothing was stored and no fix was counted for the refused call", unchanged(1, was) and kinds(made) == [], (rd(1), made))
    check("1 …and the refusal is counted in the call log under its first fault, as that fault alone is", CL.kind_of(msg(res)) == CL.kind_of("Refused: " + fl[0]) != CL.kind_of(HEAD.format(n=3)), (CL.kind_of(msg(res)), CL.kind_of("Refused: " + fl[0])))
    res, made = upd(1, subject="[home] a prefixed subject", description=DESC, next=f"falcon-main: read [the page]({URL})\nfalcon-main: test it")
    check("1 …the same call with the three faults fixed goes through", not isinstance(res, ToolError), res)

    # ================================================================ 2. one fault: refused as it always was
    item(2)
    was = rd(2)
    res, made = upd(2, subject="no prefix at all")
    check("2 a subject with no prefix alone: the refusal is the subject gate's own text, with no count and no list", msg(res) == "Refused: " + _fg.subject_faults("no prefix at all")[0].removeprefix("Refused: ") and "problems in this call" not in msg(res), msg(res))
    res, made = upd(2, description=NOGOAL)
    check("2 a description with no goal alone: the goal gate's own text", msg(res).startswith("Refused: the description must open with its goal") and "problems in this call" not in msg(res) and "Not checked" not in msg(res), msg(res)[:200])
    res, made = upd(2, next=f"falcon-main: read {URL}")
    check("2 a bare address in next alone: the gate's own text", msg(res).startswith("Refused: next has a bare URL") and "problems in this call" not in msg(res), msg(res)[:200])
    res, made = upd(2, hold=True)
    check("2 a park with nothing it waits for, alone: not refused, the server stores its default day and the item is waiting", not isinstance(res, ToolError) and rd(2)["metadata"].get("until_server") and rd(2)["metadata"].get("until"), (msg(res)[:200], rd(2)["metadata"]))

    # ================================================================ 3. a fault in the words beside a fault of the item as the call would store it
    item(3)
    was = rd(3)
    res, made = upd(3, description=NOGOAL, wait_basis="the vendor ships on 2026-12-01")
    fl, skipped = parts(res)
    check("3 a description with no goal beside a wait_basis with no date to explain: both come back, one refusal", msg(res).startswith(HEAD.format(n=2)) and len(fl) == 2 and fl[0].startswith("the description must open with its goal") and "wait_basis" in fl[1], msg(res)[:300])
    check("3 …nothing was stored", unchanged(3, was), rd(3))
    item(4)
    res, made = upd(4, subject="no prefix at all", next="falcon-main: build it (in progress)\nfalcon-main: test it")
    fl, skipped = parts(res)
    check("3 a subject with no prefix beside a step rewritten with words added: both come back", msg(res).startswith(HEAD.format(n=2)) and fl[0].startswith("subject must start") and "with words added" in fl[1], msg(res)[:400])
    check("3 …the unmarked-step check reads the step refused beside it, so it is named as not made, not told as a third fault", len(fl) == 2 and "Not checked yet" in skipped and "none of your open steps unmarked" in skipped, (fl, skipped))
    res, made = upd(4, subject="no prefix at all", next="falcon-main: build it\nfalcon-main: test it")
    check("3 …and the same call with the step as it was: only the subject, alone, as it always was", msg(res).startswith("Refused: subject must start") and "problems in this call" not in msg(res), msg(res)[:200])

    # ================================================================ 4. a check that reads what another fault leaves out is not made, and the refusal says so
    item(5)
    was = rd(5)
    res, made = upd(5, said='[{"tag": "Nope", "quote": "x"}]', description=NOGOAL, hold=True, wake=local_day(400), wait_basis="a long wait")
    fl, skipped = parts(res)
    check("4 a said with a tag the rule does not know, a description with no goal and a wake past the cap: three faults in one refusal", msg(res).startswith(HEAD.format(n=3)) and fl[0].startswith("said[0]: tag must be one of") and fl[1].startswith("the description must open with its goal") and fl[2].startswith("wait_basis stands for a wake at most"), msg(res)[:500])
    check("4 …the cap on how far out a wake may be reads the said and the wait_basis, so it is named as not made, with the checks of the item as it would be stored", skipped.startswith("Not checked yet, because they read what the faults above leave out: the cap on how far out a wake may be") and "the wait's reason and end" in skipped and skipped.endswith("once these are fixed."), skipped)
    check("4 …nothing was stored", unchanged(5, was), rd(5))
    res, made = upd(5, said='[{"tag": "Nope", "quote": "z", "msg": "w"}, {"tag": "Also", "quote": "q"}]')
    fl, skipped = parts(res)
    check("4 a said list with two bad entries: each fault is its own line, named by its place", msg(res).startswith(HEAD.format(n=2)) and fl[0].startswith("said[0]:") and fl[1].startswith("said[1]:"), msg(res)[:500])

    # ================================================================ 5. a create with several faults
    res, made = create(subject="[home] x", desc=NOGOAL, next=f"falcon-main: read {URL}")
    fl, skipped = parts(res)
    check("5 a create with a description with no goal and a bare address in next: one refusal with both, each with its own text", msg(res).startswith(HEAD.format(n=2)) and fl[0].startswith("the description must open with its goal") and fl[1].startswith("next has a bare URL"), msg(res)[:400])
    check("5 …nothing was filed", not any(x.name.endswith(".json") and json.loads(x.read_text()).get("subject") == "[home] x" for x in (T / "store/a").glob("*.json")), None)
    res, made = create(subject="[home] x", desc=NOGOAL)
    check("5 a create with one fault: the goal gate's own text, no count", msg(res).startswith("Refused: the description must open with its goal") and "problems in this call" not in msg(res), msg(res)[:200])
    res, made = create(subject="[home] x", desc=NOGOAL, next=f"falcon-main: read {URL}", wait_kind="relay", wait_event="the vendor's reply", needs=["external"])
    fl, skipped = parts(res)
    check("5 a create with a relay wait that names no day, beside the two faults in its words: the words' faults come back, and so does the wait's", msg(res).startswith("Refused: ") and "the description must open with its goal" in msg(res) and "next has a bare URL" in msg(res), msg(res)[:600])

    # ================================================================ 6. the checks that read what another fault leaves out
    item(6)
    was = rd(6)
    res, made = upd(6, description="A prose line, not a bullet.")
    check("6 a description that is prose, alone: the form gate's own refusal, and no second one for a goal it could not read", msg(res).startswith("Refused: description line is not a `- ` bullet") and "problems in this call" not in msg(res) and "goal" not in msg(res).split("\n")[0], msg(res)[:300])
    res, made = upd(6, description="A prose line, not a bullet.", subject="no prefix at all")
    fl, skipped = parts(res)
    check("6 …beside a subject with no prefix: two faults, and the goal check is named as not made, since it reads the first bullet the form fault leaves unread", len(fl) == 2 and fl[0].startswith("subject must start") and fl[1].startswith("description line is not a `- ` bullet") and "the check that the description opens with its goal" in skipped, (fl, skipped))
    item(7, "falcon-main: build it", desc=DESC)
    ASKO = "Decide: which of the two vendors · Recommend: Vendor A · Stakes: a month · By: no date"
    res, made = create(subject="[home] x", desc=DESC, needs=["decision"], ask=ASKO, next="")
    check("6 an ask that names alternatives and lists no options, alone: one fault, as before, with none of the other checks of the decision beside it", "names alternatives" in msg(res) and "problems in this call" not in msg(res) and msg(res).startswith("Refused: this needs=decision item names alternatives"), msg(res)[:300])
    res, made = create(subject="[home] x", desc=NOGOAL, needs=["decision"], ask=ASKO, next=f"falcon-main: carry on")
    fl, skipped = parts(res)
    check("6 …beside a description with no goal: the description's fault and the first of the decision's, the rest of the decision's checks named as not made", len(fl) == 2 and fl[0].startswith("the description must open with its goal") and fl[1].startswith("this needs=decision item names alternatives") and "the other checks of the decision's wording and options" in skipped, (fl, skipped))


    # ================================================================ 7. with the model guards on, one mistake is one fault, in the words it has on main
    # The guards judge the mover and the event wait beside the gates that refuse the same mistake first; a call with one mistake is refused with that mistake's text alone, as on main
    # (the strings below are main's own refusals for these calls, taken from main), and a call with two mistakes lists both.
    _cfg.CFG["model"]["guards"] = True
    MAIN_TEXT = {
        "upd mover": "Refused: @ID@ is alive and its mover, home-nobody, is no session the registry or the fleet knows. An alive item's mover is the owner, a live session or the project's background agent: set mover=<that name> (or name the session in needs), or, when nothing can move it now, put it in a wait.",
        "create mover": "Refused: this item is alive and its mover, home-nobody, is no session the registry or the fleet knows. An alive item's mover is the owner, a live session or the project's background agent: set mover=<that name> (or name the session in needs), or, when nothing can move it now, put it in a wait.",
        "upd evt none": "Refused: an event wait names its event in wait_event: pr_released <owner/repo#n> | pr_merged <owner/repo#n> | recycle [<machine>] | fleet_op <verb | any | many> [<machine>] | job_run <name> | box_online <machine>",
        "upd evt bad": "Refused: wait_event 'whenever it feels right' is not an event the server watches. Pass one of: pr_released <owner/repo#n> | pr_merged <owner/repo#n> | recycle [<machine>] | fleet_op <verb | any | many> [<machine>] | job_run <name> | box_online <machine>",
        "create evt none": "Refused: an event wait names its event in wait_event: pr_released <owner/repo#n> | pr_merged <owner/repo#n> | recycle [<machine>] | fleet_op <verb | any | many> [<machine>] | job_run <name> | box_online <machine>",
        "create evt bad": "Refused: wait_event 'whenever it feels right' is not an event the server watches. Pass one of: pr_released <owner/repo#n> | pr_merged <owner/repo#n> | recycle [<machine>] | fleet_op <verb | any | many> [<machine>] | job_run <name> | box_online <machine>",
        "upd anchor": "Refused: wait_anchor https://github.com/o/r/pull/9 is not on projects/example's anchors list, so nothing watches it and the wait would end only at its backstop. Add the anchor first: anchors(project=\"projects/example\", add=[\"https://github.com/o/r/pull/9\"], items=[\"@ID@\"]), then set the wait again",
        "create anchor": "Refused: wait_anchor https://github.com/o/r/pull/9 is not on projects/example's anchors list, so nothing watches it and the wait would end only at its backstop. Add the anchor first: add it project-wide first: anchors(project=\"projects/example\", add=[\"https://github.com/o/r/pull/9\"]); or create the item without the wait, then anchors(project=\"projects/example\", add=[\"https://github.com/o/r/pull/9\"], items=[<its id>]), then set the wait",
    }
    def same(name, res, key, i):
        want = MAIN_TEXT[key].replace("@ID@", f"a{i}")
        check(f"7 {name}: one problem, with the text it has on main", msg(res) == want and "problems in this call" not in msg(res), (msg(res)[:600], want[:300]))
    item(30); item(31)
    FILED = lambda: len(list((T / "store/a").glob("*.json")))
    filed_before = FILED()
    BAD_EVENT = "whenever it feels right"; ANCHOR = "https://github.com/o/r/pull/9"
    was = rd(30)
    res, made = upd(30, mover="home-nobody")
    same("an unknown mover on an update", res, "upd mover", 30)
    check("7 …nothing was stored", unchanged(30, was) and mt(30).get("mover") is None, mt(30))
    res, made = create(mover="home-nobody")
    same("an unknown mover on a create (the front agent's step and the hand-off say it again, and are not kept as faults)", res, "create mover", "")
    res, made = upd(31, hold=True, wait_kind="event", ask_by=local_day(5))
    same("an event wait with no phrase, on an update", res, "upd evt none", 31)
    res, made = upd(31, hold=True, wait_kind="event", wait_event=BAD_EVENT, ask_by=local_day(5))
    same("an event wait with a phrase that is no event, on an update", res, "upd evt bad", 31)
    res, made = create(wait_kind="event", ask_by=local_day(5))
    same("an event wait with no phrase, on a create", res, "create evt none", "")
    res, made = create(wait_kind="event", wait_event=BAD_EVENT, ask_by=local_day(5))
    same("an event wait with a phrase that is no event, on a create", res, "create evt bad", "")
    res, made = upd(31, hold=True, wait_kind="anchor", wait_anchor=ANCHOR, wait_event="merged", ask_by=local_day(5))
    same("an anchor wait with an anchor that is not on the list, on an update", res, "upd anchor", 31)
    res, made = create(wait_kind="anchor", wait_anchor=ANCHOR, wait_event="merged", ask_by=local_day(5))
    same("an anchor wait with an anchor that is not on the list, on a create", res, "create anchor", "")
    check("7 …none of these stored an item or a wait", mt(31).get("wait_kind") is None and FILED() == filed_before, (mt(31), FILED(), filed_before))
    # two mistakes are two faults, each once
    res, made = upd(30, mover="home-nobody", subject="no prefix at all")
    fl, skipped = parts(res)
    check("7 an unknown mover beside a subject with no prefix: two faults, the subject's and the mover's, each once", msg(res).startswith(HEAD.format(n=2)) and len(fl) == 2 and fl[0].startswith("subject must start") and fl[1].startswith("a30 is alive and its mover, home-nobody, is no session"), msg(res)[:700])
    check("7 …the hand-off check reads the mover refused beside it, so it is named as not made, not told as a third fault", "the check that the mover has a pane" in skipped and not any("no pane of it is in the heartbeat" in f for f in fl), (fl, skipped))
    res, made = create(mover="home-nobody", desc=NOGOAL)
    fl, skipped = parts(res)
    check("7 …on a create: the description's fault and the mover's, and neither the front agent's step nor the hand-off as a fault of its own", len(fl) == 2 and fl[0].startswith("the description must open with its goal") and fl[1].startswith("this item is alive and its mover, home-nobody") and "the check of a step that opens with a front agent" in skipped, (fl, skipped))
    res, made = create(desc=NOGOAL, wait_kind="event", wait_event=BAD_EVENT, ask_by=local_day(5))
    fl, skipped = parts(res)
    check("7 a phrase that is no event beside a description with no goal: two faults, and the guards' own line on the phrase is not a third", len(fl) == 2 and fl[0].startswith("the description must open with its goal") and fl[1].startswith("wait_event 'whenever it feels right' is not an event"), (fl, skipped))
    res, made = upd(31, hold=True, wait_kind="anchor", wait_anchor=ANCHOR, ask_by=local_day(5))
    fl, skipped = parts(res)
    check("7 an anchor wait that names no event beside an anchor that is not on the list: two mistakes, both come back", len(fl) == 2 and "and the event it expects" in fl[0] and fl[1].startswith("wait_anchor https://github.com/o/r/pull/9 is not on projects/example's anchors list"), (fl, skipped))
    _cfg.CFG["model"]["guards"] = False

    # ================================================================ 8. one mistake is one problem, with the guards off and on, in the words main has for it
    URL_A = "https://github.com/o/r/pull/9"
    def item_nosteps(i): item(i, next_="")      # an item with no open step: the next step a write gives it is its first
    PLACEHOLDERS = [("tbd", "tbd"), ("TBD", "TBD"), ("a question mark", "?"), ("dots", "..."), ("to be decided", "to be decided")]
    ASK8 = "Decide: ship it now · Recommend: yes · Stakes: a week of delay · By: no date"
    OPTS8 = [{"label": "yes", "line": "ship it now", "recommended": True}, {"label": "no", "line": "wait a week", "recommended": False}]
    LIST2 = [{"kind": "relay", "event": "the lease"}, {"kind": "relay", "event": "the vendor"}]
    LONG8 = "x" * 301
    LIST_T8 = [{"kind": "time", "until": local_day(3)}, {"kind": "relay", "event": "the vendor"}]
    def item_closed(i):      # a completed item: its checklist is the record
        item(i); d = rd(i); d["status"] = "completed"; (T / f"store/a/{i}.json").write_text(json.dumps(d))
    # every call below has ONE mistake: main refuses it with one problem, and so does this change, in main's own words (guards off and on)
    CASES8 = [
        ("update, a relay wait with an ask_by that is no date", lambda: upd(40, hold=True, wait_kind="relay", wait_event="the vendor", ask_by="garbage")),
        ("update, an event wait with an ask_by that is no date", lambda: upd(40, hold=True, wait_kind="event", wait_event="recycle", ask_by="garbage")),
        ("update, an anchor wait with an ask_by that is no date", lambda: upd(40, hold=True, wait_kind="anchor", wait_anchor=URL_A, wait_event="merged", ask_by="garbage")),
        ("update, a wait_kind that is none", lambda: upd(40, hold=True, wait_kind="bogus")),
        ("update, a line of next that names no one", lambda: upd(40, next="do the thing")),
        ("create, a relay wait with an ask_by that is no date", lambda: create(wait_kind="relay", wait_event="the vendor", ask_by="garbage")),
        ("create, an event wait with an ask_by that is no date", lambda: create(wait_kind="event", wait_event="recycle", ask_by="garbage")),
        ("create, an anchor wait with an ask_by that is no date", lambda: create(wait_kind="anchor", wait_anchor=URL_A, wait_event="merged", ask_by="garbage")),
        ("create, a relay wait with an until that is no date", lambda: create(wait_kind="relay", wait_event="the vendor", until="garbage")),
        ("create, a wait_kind that is none", lambda: create(wait_kind="bogus")),
        ("create, a line of next that names no one", lambda: create(next="do the thing")),
        ("create, an after id that is none", lambda: create(after=["nonsense"])),
        ("create, an unknown mover beside an item wait with an after id that is none", lambda: create(mover="home-nobody", wait_kind="item", after=["nonsense"])),
        ("create, a waits list with an until that is no date", lambda: create(waits=LIST2, until="garbage")),
        ("create, a waits list with an until that is in the past", lambda: create(waits=LIST2, until=local_day(-3))),
        ("update, a step marked done on a closed item", lambda: upd(47, done=[1])),
        ("update, a step marked dropped on a closed item", lambda: upd(47, dropped=[1])),
        ("update, a step reworded on a closed item", lambda: upd(47, reword={1: "falcon-main: build it another way"})),
        ("update, a step marked done beside a new next on a closed item", lambda: upd(47, next="falcon-main: build it again", done=[1])),
        ("update, a wait_basis on a hold with no wake", lambda: upd(40, hold=True, wait_basis="the vendor ships when the part is in")),      # a basis that names no date: one that names a date ahead ends the park on it (close_wait_defaults F5)
        ("update, a hold with a wake on a closed item", lambda: upd(47, hold=True, wake=local_day(5))),
        ("create, a then over 300 characters beside a waits list with a valid until", lambda: create(waits=LIST2, until=local_day(5), then=LONG8)),
        ("create, a goal over 300 characters beside a waits list with a valid until", lambda: create(waits=LIST2, until=local_day(5), goal=LONG8)),
        ("create, a mover over 300 characters beside a waits list with a valid until", lambda: create(waits=LIST2, until=local_day(5), mover=LONG8)),
        ("create, a post_wake_mover over 300 characters beside a waits list with a valid until", lambda: create(waits=LIST2, until=local_day(5), post_wake_mover=LONG8)),
        ("create, a mover and a post_wake_mover that differ beside a waits list with a valid until", lambda: create(waits=LIST2, until=local_day(5), mover=MAIN, post_wake_mover=OTHER)),
        ("create, a then over 300 characters beside a waits list with a time line and a valid until", lambda: create(waits=LIST_T8, until=local_day(5), then=LONG8)),
        ("create, a waits list with a time line and an until that is no date", lambda: create(waits=LIST_T8, until="garbage")),
        ("create, a waits list with a time line and an until that is in the past", lambda: create(waits=LIST_T8, until=local_day(-3))),
        ("update, a waits list with an until on a closed item", lambda: upd(47, waits=LIST2, until=local_day(5))),
        ("update, a waits list on a closed item", lambda: upd(47, waits=LIST2)),
        ("update, a clear of waits beside an until on a closed item", lambda: upd(47, waits=[], until=local_day(5))),
        ("update, an until on a closed item", lambda: upd(47, until=local_day(5))),
        ("update, a clear_hold beside a waits list with an until", lambda: upd(40, waits=LIST2, until=local_day(5), clear_hold=True)),
        ("update, a clear_hold beside a waits list with an until on a held item", lambda: (item(48, hold=True, wake=local_day(4)), upd(48, waits=LIST2, until=local_day(5), clear_hold=True))[1]),
    ]
    CASES8_ON = [      # the guards judge the mover: they are on
        ("update, an unknown mover on a relay wait", lambda: upd(40, hold=True, mover="home-nobody", wait_kind="relay", wait_event="the vendor", ask_by=local_day(5))),
        ("update, an unknown mover and the first step of an item opening with a front agent", lambda: upd(46, mover="home-nobody", next="falcon-main: carry on")),
        ("create, an unknown mover on a relay wait, the step opening with a front agent", lambda: create(mover="home-nobody", wait_kind="relay", wait_event="the vendor", ask_by=local_day(5))),
        ("create, an unknown mover on an event wait, the step opening with a front agent", lambda: create(mover="home-nobody", wait_kind="event", wait_event="recycle", ask_by=local_day(5))),
        ("create, a next of none", lambda: create(next="none")),
        ("create, a next of None beside the owner as mover", lambda: create(next="None", mover=MAIN)),
        ("create, a session as mover of a decision, the step opening with a front agent", lambda: create(mover=OTHER, needs=["decision"], ask=ASK8, options=OPTS8)),
    ] + [
        (f"{verb}, a line of next that is {tag} and names no one", fn) for tag, ph in PLACEHOLDERS for verb, fn in (
            ("create", lambda ph=ph: create(next=ph)), ("update", lambda ph=ph: upd(40, next=ph)))
    ] + [
        (f"{verb}, an event wait whose event is {tag}", fn) for tag, ph in PLACEHOLDERS for verb, fn in (
            ("create", lambda ph=ph: create(wait_kind="event", wait_event=ph, ask_by=local_day(5))),
            ("update", lambda ph=ph: upd(40, hold=True, wait_kind="event", wait_event=ph, ask_by=local_day(5))))
    ]
    MAIN8 = {      # main's own refusal for each call, by label and guards (taken from main)
        "update, a relay wait with an ask_by that is no date|False": "Refused: ask_by is YYYY-MM-DD, a real date (got 'garbage')",
        "update, an event wait with an ask_by that is no date|False": "Refused: ask_by is YYYY-MM-DD, a real date (got 'garbage')",
        "update, an anchor wait with an ask_by that is no date|False": "Refused: metadata.wake must be YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04) \u2014 got 'garbage'",
        "update, a wait_kind that is none|False": "Refused: wait_kind is one of time | anchor | item | relay | event (got 'bogus')",
        "update, a line of next that names no one|False": "Refused: a line of next names no one: \"do the thing\". One step is one action with one named actor: open the line with who takes it: `<session>:`, `the owner:` or the outside party's name. A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next",
        "create, a relay wait with an ask_by that is no date|False": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got 'garbage')",
        "create, an event wait with an ask_by that is no date|False": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got 'garbage')",
        "create, an anchor wait with an ask_by that is no date|False": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got 'garbage')",
        "create, a relay wait with an until that is no date|False": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04), a real date (got 'garbage')",
        "create, a wait_kind that is none|False": "Refused: wait_kind is one of time | anchor | item | relay | event (got 'bogus')",
        "create, a line of next that names no one|False": "Refused: a line of next names no one: \"do the thing\". One step is one action with one named actor: open the line with who takes it: `<session>:`, `the owner:` or the outside party's name. A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next",
        "create, an after id that is none|False": "bad item id 'nonsense' \u2014 ids read board#<n> (a temporary one board-tmp-local#<n>), or <letter><n> for an older item",
        "create, an unknown mover beside an item wait with an after id that is none|False": "bad item id 'nonsense' \u2014 ids read board#<n> (a temporary one board-tmp-local#<n>), or <letter><n> for an older item",
        "update, a relay wait with an ask_by that is no date|True": "Refused: ask_by is YYYY-MM-DD, a real date (got 'garbage')",
        "update, an event wait with an ask_by that is no date|True": "Refused: ask_by is YYYY-MM-DD, a real date (got 'garbage')",
        "update, an anchor wait with an ask_by that is no date|True": "Refused: metadata.wake must be YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04) \u2014 got 'garbage'",
        "update, a wait_kind that is none|True": "Refused: wait_kind is one of time | anchor | item | relay | event (got 'bogus')",
        "update, a line of next that names no one|True": "Refused: a line of next names no one: \"do the thing\". One step is one action with one named actor: open the line with who takes it: `<session>:`, `the owner:` or the outside party's name. A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next",
        "create, a relay wait with an ask_by that is no date|True": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got 'garbage')",
        "create, an event wait with an ask_by that is no date|True": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got 'garbage')",
        "create, an anchor wait with an ask_by that is no date|True": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got 'garbage')",
        "create, a relay wait with an until that is no date|True": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04), a real date (got 'garbage')",
        "create, a wait_kind that is none|True": "Refused: wait_kind is one of time | anchor | item | relay | event (got 'bogus')",
        "create, a line of next that names no one|True": "Refused: a line of next names no one: \"do the thing\". One step is one action with one named actor: open the line with who takes it: `<session>:`, `the owner:` or the outside party's name. A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next",
        "create, an after id that is none|True": "bad item id 'nonsense' \u2014 ids read board#<n> (a temporary one board-tmp-local#<n>), or <letter><n> for an older item",
        "create, an unknown mover beside an item wait with an after id that is none|True": "bad item id 'nonsense' \u2014 ids read board#<n> (a temporary one board-tmp-local#<n>), or <letter><n> for an older item",
        "update, an unknown mover on a relay wait|True": "Refused: a40's wait: the mover who takes it then, home-nobody, is no session the registry or the fleet knows. Set mover=<the owner, a live session or the project's background agent> (when it is unset, the first session in needs, else the project's builder or -main agent, takes it). If the item should not wait, drop the wait with update clear_wait=true (wait_kind, wait_anchor, wait_event and until go together).",
        "update, an unknown mover and the first step of an item opening with a front agent|True": "Refused: a46 is alive and its mover, home-nobody, is no session the registry or the fleet knows. An alive item's mover is the owner, a live session or the project's background agent: set mover=<that name> (or name the session in needs), or, when nothing can move it now, put it in a wait.",
        "create, an unknown mover on a relay wait, the step opening with a front agent|True": "Refused: this item's wait: the mover who takes it then, home-nobody, is no session the registry or the fleet knows. Set mover=<the owner, a live session or the project's background agent> (when it is unset, the first session in needs, else the project's builder or -main agent, takes it). If the item should not wait, drop the wait with update clear_wait=true (wait_kind, wait_anchor, wait_event and until go together).",
        "create, an unknown mover on an event wait, the step opening with a front agent|True": "Refused: this item's wait: the mover who takes it then, home-nobody, is no session the registry or the fleet knows. Set mover=<the owner, a live session or the project's background agent> (when it is unset, the first session in needs, else the project's builder or -main agent, takes it). If the item should not wait, drop the wait with update clear_wait=true (wait_kind, wait_anchor, wait_event and until go together).",
    }
    MAIN8.update({      # the same, for the calls with ONE mistake that were refused twice or three times (taken from main)
        "create, a waits list with an until that is no date|False": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04), a real date (got 'garbage')",
        "create, a waits list with an until that is in the past|False": "Refused: until must be in the future (+04)",
        "update, a step marked done on a closed item|False": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
        "update, a step marked dropped on a closed item|False": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
        "update, a step reworded on a closed item|False": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
        "update, a step marked done beside a new next on a closed item|False": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
        "update, a wait_basis on a hold with no wake|False": "Refused: wait_basis explains the wake of a time wait (a park's or a verifying item's), or a wake past the cap, by the real-world date it waits for, and this item has no wake date. A park with no date is refused too: give the date (until=YYYY-MM-DD with wait_kind=\"time\", the date the outside event or the owner's words give) and the basis with it",
        "update, a hold with a wake on a closed item|False": "Refused: a completed item cannot be parked; set it open first",
        "create, a waits list with an until that is no date|True": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04), a real date (got 'garbage')",
        "create, a waits list with an until that is in the past|True": "Refused: until must be in the future (+04)",
        "update, a step marked done on a closed item|True": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
        "update, a step marked dropped on a closed item|True": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
        "update, a step reworded on a closed item|True": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
        "update, a step marked done beside a new next on a closed item|True": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
        "update, a wait_basis on a hold with no wake|True": "Refused: wait_basis explains the wake of a time wait (a park's or a verifying item's), or a wake past the cap, by the real-world date it waits for, and this item has no wake date. A park with no date is refused too: give the date (until=YYYY-MM-DD with wait_kind=\"time\", the date the outside event or the owner's words give) and the basis with it",
        "update, a hold with a wake on a closed item|True": "Refused: a completed item cannot be parked; set it open first",
        "create, a next of none|True": "Refused: next line 'none' does not say who takes it: start every line with `<name>: ` where name is the owner, a session, the project's background agent or the outside party who takes the step (for example `the owner: run \u2026`, `<session>: \u2026` or `Kim: \u2026`); a name in the line's body is not enough. Put file names, commands and code in backticks.",
        "create, a next of None beside the owner as mover|True": "Refused: next line 'None' does not say who takes it: start every line with `<name>: ` where name is the owner, a session, the project's background agent or the outside party who takes the step (for example `the owner: run \u2026`, `<session>: \u2026` or `Kim: \u2026`); a name in the line's body is not enough. Put file names, commands and code in backticks.",
        "create, a session as mover of a decision, the step opening with a front agent|True": "Refused: this item has mover=home-other on an item whose state is your-call, which is the owner's move. An item that is the owner's makes him the mover: leave mover out, or set mover=the owner, and name home-other in then=home-other (his answer or Done hands the item to them). To give the item to home-other now, take decision out of needs and name a session as mover instead.",
    })
    _LONG300 = "Refused: {} is one line of at most 300 characters (got 301)"
    _MOVER_DIFF = "Refused: mover and post_wake_mover differ (mover=falcon-main, post_wake_mover=home-other); post_wake_mover is the old name of mover, the one who moves the item (on a waiting item, the one who takes it when the wait ends): pass mover=<who> alone"
    _CLOSED_WAITS = "Refused: a completed item waits on nothing; waits goes with an open item"
    for _g in (False, True):      # the calls with ONE mistake that a waits list beside a date or a closed item made two problems (taken from main)
        for _lab, _txt in (
            ("create, a then over 300 characters beside a waits list with a valid until", _LONG300.format("then")),
            ("create, a goal over 300 characters beside a waits list with a valid until", _LONG300.format("goal")),
            ("create, a mover over 300 characters beside a waits list with a valid until", _LONG300.format("mover")),
            ("create, a post_wake_mover over 300 characters beside a waits list with a valid until", _LONG300.format("post_wake_mover")),
            ("create, a mover and a post_wake_mover that differ beside a waits list with a valid until", _MOVER_DIFF),
            ("create, a then over 300 characters beside a waits list with a time line and a valid until", _LONG300.format("then")),
            ("create, a waits list with a time line and an until that is no date", "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04), a real date (got 'garbage')"),
            ("create, a waits list with a time line and an until that is in the past", "Refused: until must be in the future (+04)"),
            ("update, a waits list with an until on a closed item", _CLOSED_WAITS),
            ("update, a waits list on a closed item", _CLOSED_WAITS),
            ("update, a clear of waits beside an until on a closed item", "Refused: a completed item takes no wake; set it open first"),
            ("update, an until on a closed item", "Refused: a completed item takes no wake; set it open first")):
            MAIN8[f"{_lab}|{_g}"] = _txt
        for _lab in ("update, a clear_hold beside a waits list with an until", "update, a clear_hold beside a waits list with an until on a held item"):      # main's one refusal for a list beside clear_hold (the until beside it is the list's backstop day, no wake)
            MAIN8[f"{_lab}|{_g}"] = ("Refused: waits is a wait on a list and does not go with clear_hold: put each thing waited on in a line of waits and the backstop day in until ("
                                     + _wlw.FORM + "); clear_wait=true ends a wait on its own")
    NEXT_TAIL = ". One step is one action with one named actor: open the line with who takes it: `<session>:`, `the owner:` or the outside party's name. A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next"
    EVENT_TAIL = " is not an event the server watches. Pass one of: pr_released <owner/repo#n> | pr_merged <owner/repo#n> | recycle [<machine>] | fleet_op <verb | any | many> [<machine>] | job_run <name> | box_online <machine>"
    for _tag, _ph in PLACEHOLDERS:      # a placeholder in next, and as an event: main says the one mistake once (guards on)
        for _v in ("create", "update"):
            MAIN8[f"{_v}, a line of next that is {_tag} and names no one|True"] = 'Refused: a line of next names no one: "' + _ph + '"' + NEXT_TAIL
            MAIN8[f"{_v}, an event wait whose event is {_tag}|True"] = "Refused: wait_event '" + _ph + "'" + EVENT_TAIL
    for g, cl in ((False, CASES8), (True, CASES8 + CASES8_ON)):
        _cfg.CFG["model"]["guards"] = g
        for lab, fn in cl:
            item(40); item_nosteps(46); item_closed(47)
            res, made = fn()
            check(f"8 {lab} (guards {'on' if g else 'off'}): one problem, main's text", msg(res) == MAIN8[f"{lab}|{g}"] and "problems in this call" not in msg(res), (msg(res)[:500], MAIN8[f"{lab}|{g}"][:300]))
    for g in (False, True):      # a create with anchors (which belong to the project) beside a bad event wait: two mistakes, two problems (the anchors' fault does not end the checks of the wait)
        _cfg.CFG["model"]["guards"] = g
        for lab, ev, want in (("an event that is none", "bogus", "wait_event 'bogus' is not an event the server watches"), ("no event", "", "an event wait names its event in wait_event")):
            res, made = create(anchors=[URL_A], wait_kind="event", wait_event=ev, ask_by=local_day(5))
            fl, skipped = parts(res)
            check(f"8 a create with anchors beside {lab} (guards {'on' if g else 'off'}): two mistakes, two problems", msg(res).startswith(HEAD.format(n=2)) and len(fl) == 2 and fl[0].startswith("anchors belong to the project") and fl[1].startswith(want), msg(res)[:600])
    for g in (False, True):      # a refused argument of the model beside a waits list with no until: two mistakes, two problems (the list still needs its backstop day)
        _cfg.CFG["model"]["guards"] = g
        res, made = create(waits=LIST2, then=LONG8)
        fl, skipped = parts(res)
        check(f"8 a create with a then over 300 characters beside a waits list with no until (guards {'on' if g else 'off'}): two mistakes, two problems", msg(res).startswith(HEAD.format(n=2)) and len(fl) == 2 and fl[0].startswith("then is one line of at most 300") and fl[1].startswith("a list needs its backstop day"), msg(res)[:600])
    _cfg.CFG["model"]["guards"] = True
    item(40)
    res, made = upd(40, next="do the thing", mover="home-nobody")
    fl, skipped = parts(res)
    check("8 a line of next that names no one beside an unknown mover: two mistakes, two problems, each once", msg(res).startswith(HEAD.format(n=2)) and len(fl) == 2 and fl[0].startswith("a line of next names no one") and fl[1].startswith("a40 is alive and its mover, home-nobody"), msg(res)[:600])
    res, made = create(next="do the thing", mover="home-nobody")
    fl, skipped = parts(res)
    check("8 …on a create", msg(res).startswith(HEAD.format(n=2)) and len(fl) == 2 and fl[0].startswith("a line of next names no one") and fl[1].startswith("this item is alive and its mover, home-nobody"), msg(res)[:600])
    _cfg.CFG["model"]["guards"] = False

    sys.stdout.flush()
    return ran, fails


MARK = "@@gates part"
if __name__ == "__main__":
    if os.environ.get("GATES_MAIN") == "1": part_gates()      # a run against a checkout of main prints what each case gives there and exits (see part gates)
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"gates": part_gates, "form": part_form}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        os._exit(0)      # as the form suite always ended: nothing a thread of the part left behind holds the process (tests/_scratch.py removes the scratch folder first)
    total = bad = 0
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], stdout=subprocess.PIPE, text=True)
        seen = [l for l in r.stdout.splitlines() if l.startswith(MARK + " ")]
        print("\n".join(l for l in r.stdout.splitlines() if not l.startswith(MARK + " ")))
        if r.returncode != 0 or len(seen) != 1:
            print(f"FAIL part {name} did not end cleanly (exit {r.returncode})"); bad += 1; continue
        _, _, _, n, f = seen[0].split(); total += int(n); bad += int(f)
        print(f"part {name}: {int(n) - int(f)}/{n} checks passed")
    if bad:
        print(f"\n{bad} failures in {total} checks"); sys.exit(1)
    print(f"ok: gates scenario, {total} checks")
