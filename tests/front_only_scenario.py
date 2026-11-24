"""Scenario tests for the front-only test of a project (anchors.front_only), in three parts that each run in a process of their own: fixture data (English stand-in names), no live store, no network, no server socket.

Part `roster` - the front-only test itself (anchors.front_only) and the two server rules that use it:

A project is front-only when it has no builder: no background agent of its hub whose mandate says build, maintain, merge or engineer (anchors.builder_of, the same test as the hand-off machinery's
handoff_builder). No new field: adding a builder to the page's map is all that switches a project over.

  1  pure, on a registry given in hand: a map with a builder is not front-only (one, several); a map without is (one -main only; a -main and a second front agent); a background agent whose
     mandate says nothing about building is no builder, so the project is front-only
  2  pure: a sub-page with no map reads its hub's (hub without a builder: front-only; hub with one: not), a page with a `hub:` line reads that hub, a sub-page with a map of its own reads the builder of
     its hub too (front agents only under a hub that has a builder: not front-only), and a builder on a member page makes the hub's project not front-only
  3  pure: adding a builder flips it (the same registry with one `back_agents` entry added, and back again when it is removed), also for a sub-page that reads the hub's map
  4  pure: an empty or missing page: a key the registry does not hold, an empty key, a registry with no pages, a page with an empty map and a hub without one, an entry with no fields: all front-only
  5  the default registry: with no registry given the test reads the page registry file, and the agents only the project record holds (their page line still owed) are no builder until the
     page lists them, so a background agent made through the New session form leaves the project front-only before its page line lands
  6  agreement with the hand-off test: on every project of that fixture handoff_builder says "no builder" exactly when front_only says True, and the two server rules that use front_only (the answer's
     target and the front agents' hand-over) behave as before for a front-only project and a project with a builder
  7  the shapes that were once told apart, pinned as the one result: a background agent whose mandate does not build, a sub-page with its own front-only map under a hub with a builder, a sub-page whose
     `hub:` line points at a page with no map while its top-level page lists a builder, a front-only hub whose builder sits on a member page, a builder only the project record holds (page line still owed)

Part `ladder` - where the stall ladder ends:

Where the stall ladder ends (service/pane_recovery.py: _recovery_target, _recovery_tell, the `recover` step of handoff.next_step): a front-only project (anchors.front_only: its `agents:` map lists no
`background:` agent, so there is no builder to try) ends at its -main agent, with no owner mark (it is the agent's move), instead of the fleet's builder; a project with a builder is
unchanged. Fixture data (English stand-in names) in a temporary store, the push replaced by a recorder, no network, no model call.

  1  the stall ladder in a front-only project: the cold call off, no builder, so the last rung asks the project's -main agent, once: one message marked `[for <owner>]` on its first line, naming the item and the
     quiet session and asking it to decide; the fleet's builder is told nothing; the History line says who was asked; the item stays with its mover and is not on the owner's list; later passes send nothing
  2  a project with a builder is unchanged: its builder is the first choice, and when the quiet session is that builder itself the last rung still asks the fleet's builder (unmarked, `fleet recovery:`), not the -main agent
  3  a front-only project whose quiet mover is its -main agent itself, and one with no -main agent to name: the fleet's builder is asked, as before
  4  the choice on its own (service/pane_recovery.py: _recovery_target: the recipient, its kind, whether the project is builderless) for each shape, a front-only test that raises keeps the fleet's builder (one line on stderr)
  5  what the request says: the target is computed once per request; the hand-off record (`recovery_by`), its event, `get`'s line, the journal note and the History line name who was actually asked; "what
     the ladder tried" never claims a builder for a front-only project, whether its -main agent or the fleet's builder is asked, in the stall ladder and the hand-off ladder alike; a project with a builder keeps its old words

Part `project` - one walk through a front-only project:

ONE front-only project, walked through the real tool entry points: a project page that lists front agents only (no builder, no background agent) next to a project with a builder, on a
throwaway instance (fixture pages and sessions in a temporary store, the push replaced by a recorder, no network, no model call). Each change made for such a project is walked in order, each with what the
tool returns (accepted, or the exact refusal and the path it names) and, for contrast, the same call on a project that has a builder, where the answer must differ.

  0  one predicate: `anchors.front_only` is exactly "no builder" (`handoff_builder` empty), for a page of front agents only, a page whose only background agent does not build, a sub-page with a front map of its own
     under a hub that has a builder, a builder shared by two pages
  1  `mover=` hand-over (update and create): a peer, a front agent or a background agent of another project hands an item to a live front agent of the project; the target is told by a hand-off notice and the reply
     says so; the refusals (a session no page lists, another project's front agent as target) name the half that failed and `message(to=<page key>)` with the first line `For <peer>,`. With a builder: the builder is
     substituted
  2  `then=` and `post_wake_mover=` take the same exception, tell nobody (the owner's answer or the wake moves the item), refuse the same way; with a builder both are substituted
  3  a step may open with a live peer: accepted on an item another session moves when an open step comes before it; refused as the first open step (with the ways out), for another project's front agent, and in a
     project with a builder; marking the step before it done hands the item to the peer, told once
  4  messages: an unmarked message from a front agent to a peer is refused and names `For <peer>,` to the page key; that form is accepted; a message that says nothing is needed from the owner stays refused
     without the form; a sender that is no front agent is not offered it
  5  `needs=` naming a peer: refused with `mover=<peer>` or its own item with `after=`; with a builder the refusal names the builder
  6  a script's item-open: filed with the project's -main agent as mover and the item says so; a project with a builder files it for the background agent; a sub-page under a hub with a builder is refused
  7  orphan hand-over: an alive item whose mover's session is gone goes to a live front agent, which is told once by the hand-off notice; with a builder the builder takes it and the front agents are not pushed to
  8  hand-back: a write by another session that leaves `needs` naming the front mover alone tells that mover, marked for the owner; with a builder the builder is told and the front mover is not
  9  take clock: a peer hand-off is clocked (one reminder to the new mover after the take minutes, then the project's -main agent is asked), the hander is told nothing at any step; with a builder a hand-off to a
     front agent is never clocked

Everything runs through the tools' own functions (`stackshot_update`, `stackshot_create`, `stackshot_message`, the item-open route, the handover and the passes the server runs on a timer: `handoff_tick`,
`orphan_handover`), on the in-process server module, as the other scenarios do; none reaches a live server or a live board. The hand-back check (8) reports the router as not live, so it pins the decision logic and the direct-push fallback (who is told, and marked for the owner), not the path every deployment takes
through the router; that path is covered in tests/router_live_scenario.py.

    tests/run-suite front_only        -> exit 0 / 1"""
import json, os, re, socket, subprocess, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)

# The three parts set up three different instances (an example config with HOME in the scratch folder; a base config with the owner and the marks changed), and the code under test reads its config
# and keeps module state at import: so each part runs in a process of its own (this file started again with `--part <name>`), exactly as the three suites did, and the parent adds their counts.
PARTS = ("roster", "ladder", "project")

def _setup(prefix, *, example, transcripts, own_owner):
    """The scratch folder and the instance config of a part: every path inside the scratch folder, the fixtures' timezone and prefixes, the transcripts of the part. Returns (tmp, T)."""
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix=prefix); T = pathlib.Path(tmp)
    if example: toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
    else: toml = _instance.apply(_instance.base_toml())
    if not example: toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1)
    assert 'session_links = ""' in toml   # the config names no fleet store of the host
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
    toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = [{", ".join(chr(34) + tmp + "/" + t + chr(34) for t in transcripts)}]', toml); assert n == 1   # never the host's transcripts
    if own_owner:
        toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
        toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    return tmp, T

def _checker(limit):
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:limit]}" if got is not None else ""))
    return check, fails, ran


# ================================================================ part roster: the front-only test and the two server rules that use it
def part_roster():
    tmp, T = _setup("front-only-", example=True, transcripts=("transcripts",), own_owner=False)
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", HOME=tmp); os.environ.pop("STACKSHOT_URL", None)
    for d in ("store/a", "fleet/a", "brain/projects"): (T / d).mkdir(parents=True)
    check, fails, ran = _checker(700)
    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    from stackshot.anchors import anchors as A  # noqa: E402

    page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}

    # ---------------------------------------------------------------- 1. the map decides
    REG = {
        "projects/solo": page(agents={"home-solo-main": "front"}),
        "projects/pair": page(agents={"home-pair-main": "front", "home-pair-desk": "front, answers questions"}),
        "projects/built": page(agents={"home-built-main": "front", "home-built-engineer": "builds it"}, back_agents={"home-built-engineer": "builds it"}),
        "projects/crowd": page(agents={"home-crowd-main": "front", "home-crowd-tests": "runs the suites", "home-crowd-engineer": "builds it"},
                               back_agents={"home-crowd-tests": "runs the suites", "home-crowd-engineer": "builds it"}),
        "projects/quiet": page(agents={"home-quiet-main": "front", "home-quiet-watch": "watches the clock"}, back_agents={"home-quiet-watch": "watches the clock"}),
        "projects/backonly": page(agents={"home-backonly-engineer": "builds it"}, back_agents={"home-backonly-engineer": "builds it"}),
    }
    check("1 a map with one background entry is not front-only", A.front_only("projects/built", REG) is False)
    check("1 a map with several background entries is not front-only", A.front_only("projects/crowd", REG) is False)
    check("1 a map of one -main agent only is front-only", A.front_only("projects/solo", REG) is True)
    check("1 a -main agent and a second front agent is front-only", A.front_only("projects/pair", REG) is True)
    check("1 a background agent whose mandate lacks the build words is no builder: front-only", A.front_only("projects/quiet", REG) is True)
    check("1 a map of background agents alone is not front-only", A.front_only("projects/backonly", REG) is False)
    check("1 slashes round the key do not matter", A.front_only("/projects/built/", REG) is False and A.front_only("projects/solo/", REG) is True)

    # ---------------------------------------------------------------- 2. a page with no map reads its hub's
    REG2 = {
        **REG,
        "projects/solo/notes": page(type="note", role="inherited"),                          # a sub-page: no map of its own, no hub line -> the top-level page
        "projects/built/notes": page(type="note", role="inherited"),
        "projects/built/deep/notes": page(type="note", role="inherited"),                    # two levels down: still the top-level page
        "projects/aside": page(hub="projects/built"),                                       # a page with a `hub:` line and no map -> that hub
        "projects/aside2": page(hub="projects/solo"),
        "projects/solo/desk": page(agents={"home-solo-desk": "front"}),                      # a map of its own, front agents only, under a hub of front agents
        "projects/built/desk": page(agents={"home-built-desk": "front"}),                    # a map of its own, front agents only, under a hub that has a builder: its own map decides
        "projects/yard": page(agents={"home-yard-main": "front"}),                           # a hub of front agents only ...
        "projects/yard/crew": page(agents={"home-yard-crew": "builds the crew's work"}, back_agents={"home-yard-crew": "builds the crew's work"}),   # ... with a builder on a member page
    }
    check("2 a sub-page with no map under a hub of front agents is front-only", A.front_only("projects/solo/notes", REG2) is True)
    check("2 a sub-page with no map under a hub that has a background agent is not front-only", A.front_only("projects/built/notes", REG2) is False)
    check("2 the same two levels down", A.front_only("projects/built/deep/notes", REG2) is False)
    check("2 a page with a `hub:` line and no map reads that hub", A.front_only("projects/aside", REG2) is False and A.front_only("projects/aside2", REG2) is True)
    check("2 a sub-page with its own map of front agents reads its hub's builder: not front-only", A.front_only("projects/built/desk", REG2) is False)
    check("2 a sub-page with its own builder is not front-only, and neither is the hub it belongs to although the hub lists front agents only", A.front_only("projects/yard/crew", REG2) is False and A.front_only("projects/yard", REG2) is False)
    TWIN = {"projects/twina": page(agents={"home-twina-main": "front", "home-shared-eng": "builds things"}, back_agents={"home-shared-eng": "builds things"}),
            "projects/twinb": page(agents={"home-twinb-main": "front", "home-shared-eng": "builds things"}, back_agents={"home-shared-eng": "builds things"})}
    check("2 a builder listed on the pages of two hubs counts for both: neither is front-only", A.front_only("projects/twina", TWIN) is False and A.front_only("projects/twinb", TWIN) is False
          and A.builder_of("projects/twina", TWIN) == ["home-shared-eng"] and A.builder_of("projects/twinb", TWIN) == ["home-shared-eng"])
    FRONTSOME = {"projects/probeh": page(agents={"home-probe-main": "front", "home-b1-eng": "builds things"}, back_agents={"home-b1-eng": "builds things"}),
                 "projects/probeg": page(agents={"home-probeg-main": "front", "home-b1-eng": "front, also answers"}),
                 "projects/probek": page(agents={"home-probek-main": "front", "home-b1-eng": "builds things"}, back_agents={"home-b1-eng": "builds things"}),
                 "projects/probek/desk": page(agents={"home-b1-eng": "front on the desk page"})}
    check("2 a name that is background on a hub but front on another hub is no builder of the hub (a front agent gets no hand-off notice); the hub that lists it as front has none either",
          A.front_only("projects/probeh", FRONTSOME) is True and A.builder_of("projects/probeh", FRONTSOME) == [] and A.front_only("projects/probeg", FRONTSOME) is True)
    check("2 a name that is background on a hub's page but front on a sub-page of the same hub is no builder of the hub, nor of the sub-page",
          A.front_only("projects/probek", FRONTSOME) is True and A.builder_of("projects/probek", FRONTSOME) == [] and A.front_only("projects/probek/desk", FRONTSOME) is True)
    check("2 a builder listed on any page of its hub, a sub-page's included, counts for the hub", A.front_only("projects/probem", {"projects/probem": page(agents={"home-probem-main": "front"}), "projects/probem/crew": page(agents={"home-probem-eng": "builds things"}, back_agents={"home-probem-eng": "builds things"})}) is False)
    check("2 slashes round a sub-page key do not matter (a sub-page's own map, its hub's map, its own background agent)",
          A.front_only("/projects/built/desk/", REG2) is False and A.front_only("/projects/built/notes/", REG2) is False and A.front_only("/projects/yard/crew/", REG2) is False
          and A.front_only("//projects/solo/notes//", REG2) is True)

    # ---------------------------------------------------------------- 3. adding a builder flips it
    def with_builder(reg, key, name="home-new-engineer", mandate="takes build work"):
        e = dict(reg[key]); e["agents"] = {**e["agents"], name: mandate}; e["back_agents"] = {**(e.get("back_agents") or {}), name: mandate}
        return {**reg, key: e}
    def without(reg, key, name):
        e = dict(reg[key]); e["agents"] = {k: v for k, v in e["agents"].items() if k != name}; e["back_agents"] = {k: v for k, v in (e.get("back_agents") or {}).items() if k != name}
        if not e["back_agents"]: e.pop("back_agents")
        return {**reg, key: e}
    R3 = with_builder(REG2, "projects/solo")
    check("3 adding a builder to a front-only map switches the project over", A.front_only("projects/solo", REG2) is True and A.front_only("projects/solo", R3) is False)
    check("3 ...and a sub-page that reads the hub's map follows", A.front_only("projects/solo/notes", REG2) is True and A.front_only("projects/solo/notes", R3) is False)
    check("3 ...and so does a sub-page with a map of its own (it reads its hub's builder)", A.front_only("projects/solo/desk", REG2) is True and A.front_only("projects/solo/desk", R3) is False)
    R3b = without(R3, "projects/solo", "home-new-engineer")
    check("3 taking the builder out again switches it back", A.front_only("projects/solo", R3b) is True and A.front_only("projects/solo/notes", R3b) is True)
    R3c = without(REG2, "projects/crowd", "home-crowd-engineer")
    R3d = without(REG2, "projects/crowd", "home-crowd-tests")
    check("3 one of two background agents removed: still not front-only while the builder stays; the builder removed (the other does not build): front-only", A.front_only("projects/crowd", R3d) is False and A.front_only("projects/crowd", R3c) is True)
    check("3 ...both removed: front-only", A.front_only("projects/crowd", without(R3c, "projects/crowd", "home-crowd-tests")) is True)
    check("3 the registry given is not changed", REG2["projects/solo"]["agents"] == {"home-solo-main": "front"} and "back_agents" not in REG2["projects/solo"])

    # ---------------------------------------------------------------- 4. an empty or missing page
    check("4 a key the registry does not hold is front-only", A.front_only("projects/ghost", REG2) is True)
    check("4 a sub-page of a page the registry does not hold is front-only", A.front_only("projects/ghost/notes", REG2) is True)
    check("4 an empty key, a blank key and None are front-only", A.front_only("", REG2) is True and A.front_only("  ", REG2) is True and A.front_only(None, REG2) is True)
    check("4 a registry with no pages is front-only", A.front_only("projects/built", {}) is True)
    check("4 a page with an empty map and a hub without one is front-only", A.front_only("projects/e", {"projects/e": page(agents={}), "projects/hub0": page(agents={"x-main": "front"})}) is True)
    check("4 a page with an empty map reads its hub's", A.front_only("projects/e", {"projects/e": page(agents={}, hub="projects/hub1"), "projects/hub1": page(agents={"x-main": "front", "x-eng": "builds"}, back_agents={"x-eng": "builds"})}) is False)
    check("4 a page entry with no fields at all is front-only", A.front_only("projects/odd", {"projects/odd": {}}) is True)

    # ---------------------------------------------------------------- 5. the default registry: the page registry file, plus the agents only the record holds
    from stackshot.projects import projects as P  # noqa: E402
    PID = P.ensure_ids(["projects/solo"])["projects/solo"]      # the record mints the id
    (T / "store/projects.json").write_text(json.dumps({"pages": {k: v for k, v in REG2.items()}}))
    check("5 with no registry given the test reads the page registry file", A.front_only("projects/solo") is True and A.front_only("projects/built") is False and A.front_only("projects/built/notes") is False)
    (T / "store/project-record.json").write_text(json.dumps({"schema": 1, "ids": {PID: "projects/solo"},
        "pending_agents": {PID: {"home-solo-engineer": {"mandate_line": "takes the build work", "front": False, "role": "engineer"}}}}))
    check("5 a background agent only the project record holds (page line still owed) is no builder until the page lists it: the project stays front-only", A.front_only("projects/solo") is True and A.front_only("projects/solo/notes") is True)
    (T / "store/project-record.json").write_text(json.dumps({"schema": 1, "ids": {PID: "projects/solo"},
        "pending_agents": {PID: {"home-solo-friend": {"mandate_line": "answers questions", "front": True, "role": "front"}}}}))
    check("5 a front agent only the record holds does not", A.front_only("projects/solo") is True)
    (T / "store/project-record.json").write_text("{ not json")
    check("5 a damaged record reads as no pending agent (the page registry alone decides)", A.front_only("projects/solo") is True and A.front_only("projects/built") is False)
    (T / "store/project-record.json").unlink()
    (T / "store/projects.json").write_text("{ not json")
    check("5 a damaged page registry file reads as no pages: front-only", A.front_only("projects/built") is True)
    (T / "store/projects.json").write_text(json.dumps({"pages": {k: v for k, v in REG2.items()}}))

    # ---------------------------------------------------------------- 6. agreement with the older tests, and the two server rules
    from stackshot.web import server  # noqa: E402
    from stackshot.model import holders as _holders  # noqa: E402
    from stackshot.service import item_read as _item_read  # noqa: E402
    from stackshot.web import publish as _web_publish
    from stackshot.service import handoff as handoff_svc
    from stackshot.web.tools import anchors as _wt_anchors
    from stackshot.web.tools import route as _wt_route
    SMAIN, SDESK, DMAIN, DDESK, DBUILD = ("home-sigma-main", "home-sigma-desk", "home-delta-main", "home-delta-desk", "home-delta-builder")
    U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate((SMAIN, SDESK, DMAIN, DDESK, DBUILD), 1)}
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
    SHAPES = {
        "projects/sigma": page(title="Sigma", name="Sigma", agents={SMAIN: "front", SDESK: "front, answers the owner's questions"}),
        "projects/delta": page(title="Delta", name="Delta", agents={DMAIN: "front", DDESK: "front, answers questions", DBUILD: "builds it"}, back_agents={DBUILD: "builds it"}),
        "projects/sigma/sub": page(title="Sigma sub", name="Sigma sub"),
        "projects/delta/sub": page(title="Delta sub", name="Delta sub"),
        "projects/echo": page(title="Echo", name="Echo", agents={"home-echo-main": "front"}),
        "projects/lone": page(title="Lone", name="Lone"),
    }
    (T / "store/projects.json").write_text(json.dumps({"pages": SHAPES}))
    old_no_builder = lambda p: not handoff_svc.handoff_builder(p)      # the hand-off machinery's test
    rows = {p: (A.front_only(p), old_no_builder(p)) for p in SHAPES}
    check("6 on every fixture project front_only agrees with the hand-off builder test", all(a == b for a, b in rows.values()), rows)
    check("6 the fixture holds both kinds of project", {a for a, _ in rows.values()} == {True, False}, rows)

    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    nm = A.names()
    roles = A.session_roles()
    fp = lambda sender, key, project: _holders._front_handover_ok(sender, key, project)
    check("6 front agents of a front-only project may hand an item to each other", fp(SMAIN, SDESK, "projects/sigma") is True and fp(SDESK, SMAIN, "projects/sigma/sub") is True, roles.get(SMAIN))
    check("6 ...not in a project that has a builder", fp(DMAIN, DDESK, "projects/delta") is False and fp(DMAIN, DDESK, "projects/delta/sub") is False)
    check("6 ...a target that is another project's front agent is no target, and a session no page lists is no sender", fp(SMAIN, DDESK, "projects/sigma") is False and fp("home-nobody", SDESK, "projects/sigma") is False)
    check("6 ...but the sender may belong to another project, as a front agent or a background agent, into a front-only project's front agent", fp(DMAIN, SDESK, "projects/sigma") is True and fp(DBUILD, SMAIN, "projects/sigma/sub") is True
          and fp(DBUILD, DDESK, "projects/delta") is False)
    meta = lambda **k: {"owner": SMAIN, "contact": SDESK, "project": "projects/sigma", **k}
    check("6 the answer of a front-only project goes to its contact", _holders._builderless_answer_to(meta(), "projects/sigma") == SDESK, _holders._builderless_answer_to(meta(), "projects/sigma"))
    check("6 ...a project with a builder keeps the old fallback", _holders._builderless_answer_to(meta(project="projects/delta", contact=DDESK), "projects/delta") == "")
    check("6 ...an empty project keeps it too", _holders._builderless_answer_to(meta(), "") == "")

    # ---------------------------------------------------------------- 7. where front_only and the older test differ, pinned as the intended results
    # (a) a background agent whose mandate lacks the build words; (b) a sub-page with a map of front agents under a hub that lists a background agent; (c) a sub-page whose `hub:` line points at a page
    # with no map, while its top-level page lists a background agent; (d) a hub whose own map is front-only, with a background agent on a member page that names it as its hub; (e) a background agent
    # only the project record holds (its page line still owed)
    SHAPES7 = {
        "projects/qa": page(title="Qa", name="Qa", agents={"home-qa-main": "front", "home-qa-watch": "watches the clock"}, back_agents={"home-qa-watch": "watches the clock"}),
        "projects/qb": page(title="Qb", name="Qb", agents={"home-qb-main": "front", "home-qb-eng": "builds it"}, back_agents={"home-qb-eng": "builds it"}),
        "projects/qb/desk": page(title="Qb desk", name="Qb desk", agents={"home-qb-desk": "front"}),
        "projects/qa2": page(title="Qa2", name="Qa2", agents={"home-qa2-main": "front", "home-qa2-eng": "builds it"}, back_agents={"home-qa2-eng": "builds it"}),
        "projects/qa2/s/t": page(title="Qa2 t", name="Qa2 t", hub="projects/qc"),
        "projects/qc": page(title="Qc", name="Qc"),
        "projects/qd": page(title="Qd", name="Qd", agents={"home-qd-main": "front"}),
        "projects/qd-member": page(title="Qd member", name="Qd member", hub="projects/qd", agents={"home-qd-member-main": "front", "home-qd-member-eng": "builds it"}, back_agents={"home-qd-member-eng": "builds it"}),
        "projects/qe": page(title="Qe", name="Qe", agents={"home-qe-main": "front"}),
    }
    (T / "store/projects.json").write_text(json.dumps({"pages": SHAPES7}))
    old7 = {p: old_no_builder(p) for p in SHAPES7}
    new7 = {p: A.front_only(p) for p in SHAPES7}
    check("7a a background agent whose mandate lacks the build words is no builder: front-only, as the hand-off test says", new7["projects/qa"] is True and old7["projects/qa"] is True, (new7, old7))
    check("7b a sub-page with its own map of front agents under a hub that lists a builder: not front-only, as the hand-off test says (the hub's builder)", new7["projects/qb/desk"] is False and old7["projects/qb/desk"] is False and new7["projects/qb"] is False, (new7, old7))
    check("7c a sub-page whose `hub:` line points at a page with no map, under a top-level page that lists a builder: front-only (the hub named is read), as the hand-off test says",
          new7["projects/qa2/s/t"] is True and old7["projects/qa2/s/t"] is True and new7["projects/qc"] is True and new7["projects/qa2"] is False, (new7, old7))
    check("7d a hub with a front-only map and a builder on a member page that names it as its hub: not front-only, as the member is, and as the hand-off test says",
          new7["projects/qd"] is False and old7["projects/qd"] is False and new7["projects/qd-member"] is False, (new7, old7))
    check("7 front_only and the hand-off test agree on every shape", all(new7[p] == old7[p] for p in SHAPES7 if p != "projects/qe"), (new7, old7))
    QE = P.ensure_ids(["projects/qe"])["projects/qe"]
    (T / "store/project-record.json").write_text(json.dumps({"schema": 1, "ids": {QE: "projects/qe"},
        "pending_agents": {QE: {"home-qe-engineer": {"mandate_line": "takes the build work", "front": False, "role": "engineer"}}}}))
    check("7e a builder only the project record holds (page line owed) is no builder yet: front-only, and the hand-off test agrees (both read the page's mandate line)", A.front_only("projects/qe") is True and old_no_builder("projects/qe") is True,
          (A.front_only("projects/qe"), old_no_builder("projects/qe")))

    return ran, fails


# ================================================================ part ladder: where the stall ladder ends
def part_ladder():
    tmp, T = _setup("stalltest-", example=False, transcripts=("no-such-root", "transcripts"), own_owner=True)
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    for d in ("store/a", "fleet/a", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
    check, fails, ran = _checker(97)
    NAMES = ("home-front", "team-back", "home-docs", "home-peer", "home-peer2", "home-peer3", "home-send", "home-beta-front", "home-stew", "home-beta-stew", "home-fleet")
    U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
    now0 = time.time()
    ZONE_OFFSET = 4 * 3600                                                                  # the instance zone is Asia/Dubai: UTC+4, no daylight saving
    ZONE_ABBR = "+04"                                                                       # its strftime %Z abbreviation
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
    def proj(session, agents, back):
        return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
    # alpha: front home-front; background home-docs (listed first) and team-back (builds); beta: a front agent and no background agent (nobody to build)
    ALPHA = {"home-front": "the front", "home-docs": "keeps the pages", "team-back": "builds, merges and releases the code"}
    (T / "store/projects.json").write_text(json.dumps({"pages": {
        "projects/alpha": proj("home-stew", ALPHA, {k: ALPHA[k] for k in ("home-docs", "team-back")}),
        "projects/beta": proj("home-beta-stew", {"home-beta-front": "the front"}, {})}}))
    for key, name, agents in (("alpha", "home-stew", ALPHA), ("beta", "home-beta-stew", {"home-beta-front": "the front"})):
        back = [k for k in agents if k in ("home-docs", "team-back")]
        front = [k for k in agents if k not in back]
        (T / f"brain/projects/{key}.md").write_text(f"---\ntitle: {key}\ndisplay-name: {name}\nagents:\n" + "".join(f"  {k}: {agents[k]}\n" for k in front)
                                                     + ("  background:\n" + "".join(f"    {k}: {agents[k]}\n" for k in back) if back else "") + f"---\n\n# {key}\n\n## Current state\n\nSTATE-OF-{key.upper()}: the vendor call is open.\n\n<!-- timeline -->\n")
    (T / "store/next-id").write_text("97"); (T / "store/anchors.json").write_text("{}")
    DESC = "- A thing\n- It lives here\n- Done when done"
    B = now0 - 900.0          # the base of the item clocks: items last written then, and the first step is due 10 minutes after the pane went idle at B + 60
    def item(i, project="projects/alpha", mover="home-peer", status="open", updated=None, **meta):
        up = B if updated is None else updated
        base = {"owner": U["home-front"], "project": project, "next": f"{mover}: do the thing"}
        if mover: base["mover"] = mover
        base.update(meta)
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                           "updated": up, "state_updated": up, "confirmed": up, "metadata": base}))
    def close(*ids):
        for i in ids:
            d = rd(i); d["status"] = "completed"; (T / f"store/a/{i}.json").write_text(json.dumps(d))
    def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
    def mt(i): return rd(i)["metadata"]
    def ho(i): return mt(i).get("handoff") or {}
    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.waits import handoff as H; from stackshot.waits import stall as S
    from stackshot.service import pane_recovery as _pane_recovery
    from stackshot.core import instance as _core_instance
    from stackshot.anchors import anchors as _anc
    from stackshot.core import config as _cfg
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    from stackshot.service import handoff as handoff_svc
    from stackshot.service import handoff_cold as hcold_svc
    from stackshot.service import stall as stall_svc, stall_tick as stalltick_svc
    from stackshot.web.tools import get as _wt_get
    from stackshot.service import telling
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    # the record follows the mover (handoff.stale): checked after every save of the run, the stall pass's moves and raises included
    _real_save = writes.save
    INV_BAD = []; INV_SAVES = [0]
    NOTES = []
    def _save_inv(gid, item, *a, **kw):
        NOTES.append((gid, kw.get("note", "")))
        out = _real_save(gid, item, *a, **kw)
        INV_SAVES[0] += 1
        if H.stale(item, H.mover_of(item, lambda it: handoff_svc.ho_derive({**it, "gid": gid})), handoff_svc.ho_same): INV_BAD.append((gid, (item.get("metadata") or {}).get("handoff"), kw.get("note", "")))
        return out
    writes.save = _save_inv
    _web_page_debts._owing_note = lambda debtor: ""
    PUSHLOG = T / "push.log"
    (T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
    telling.PUSH = [sys.executable, str(T / "fakepush.py")]
    THREADS = []
    _real_tell = telling.tell_woken
    TOLD = []      # every notice the server tells, as [session id, text], pushed or not: a request to a -main agent is a progress notice (telling.tell_own_move), held while Oliver is away, so its checks read this
    def _tell(gid, owner, note, tag="wake"):
        TOLD.append([owner, note])
        th = _real_tell(gid, owner, note, tag)
        if th: THREADS.append(th)
        return th
    telling.tell_woken = _tell
    def drain():
        while THREADS: THREADS.pop(0).join(30)
        while hcold_svc.HO_COLD_THREADS: hcold_svc.HO_COLD_THREADS.pop(0).join(30)
        while THREADS: THREADS.pop(0).join(30)
    def pushes(): return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
    def pushes_to(who, gid=None): return [p for p in pushes() if p[0] == U[who] and (gid is None or gid in p[1])]
    def set_cfg(**kw): _cfg.CFG["model"] = dict(kw)
    def set_stall(**kw):
        """The [stall] section as given. A pause (enabled = false, a paused_until) names the item as its pause_item unless the call says otherwise: an item that carries Oliver's own answer,
        dated far ahead so it counts at any clock below; section 18 tests the refusals with answers of its own."""
        if (kw.get("enabled") is False or kw.get("paused_until")) and "pause_item" not in kw: kw["pause_item"] = "a97"
        _cfg.CFG["stall"] = dict(kw)
    set_cfg(); set_stall()
    _cfg.CFG.setdefault("fleet", {})["operator_session"] = "home-fleet"      # the fleet's builder: the ladders' last rung asks it, once per episode, to recover a quiet session
    def recovery_pushes(gid): return [p for p in pushes_to("home-fleet", gid) if "fleet recovery:" in p[1]]
    def told_to(who, gid=None): return [p for p in TOLD if p[0] == U[who] and (gid is None or gid in p[1])]
    def main_recovery_pushes(gid): return [p for p in told_to("home-beta-front", gid) if "has gone quiet" in p[1]]      # a project with no background agent (beta) ends at its -main agent, with no owner mark
    item(97, status="completed", answers=[{"ts": 9e9, "kind": "comment", "text": "Pause it for now.", "via": "board"}])      # Oliver's answer, the pause_item of every pause below
    stall_svc.stall_since(B)          # the pass first ran at B (before every clock below); test 12 starts from no file at all
    COLD_MSGS = []
    def cold(answer, status="ok"):
        def run(msg):
            COLD_MSGS.append(msg)
            return {"status": status, "text": json.dumps(answer) if isinstance(answer, dict) else str(answer), "duration_s": 0.1, "usage": {}, "note": "stub"}
        hcold_svc.COLD_RUNNER = run
    hcold_svc.COLD_RUNNER = lambda msg: {"status": "spawn", "note": "no call expected"}
    cold("no json at all here")            # a cold call that gives nothing
    def cli_row(who, status, at):
        """The CLI's own registry row of a pane on this box: an interactive pane, status busy | idle and when it changed (ms)."""
        (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": U[who], "name": who, "status": status, "statusUpdatedAt": int(at * 1000), "updatedAt": int(at * 1000)}))
    def no_row(who): (T / f"cli/{os.getpid()}-{who}.json").unlink(missing_ok=True)
    handoff_svc.CLI_SESSIONS = T / "cli"
    OWN = _core_instance.OWNER
    FUT = time.strftime("%Y-%m-%d", time.gmtime(now0 + 5 * 86400 + ZONE_OFFSET))
    ASK = "Decide: ship the thing now · Recommend: ship it · Stakes: a week of delay · By: no date"
    MIN = 60.0
    def stk(at):
        """One stall pass at `at` (the 20-second gate reset), the threads it started finished → the items it acted on."""
        stall_svc.STALL_LAST[0] = 0.0
        out = stalltick_svc.stall_tick(at); drain()
        return out
    def log_of(i): return S.log_of(mt(i))
    IDLE0 = B + 60.0                       # the pane went idle then: the first step is due at T1
    T1 = IDLE0 + 10 * MIN + 1.0
    T2 = T1 + 10 * MIN + 1.0

    set_cfg(cold_call=False)
    FLEET_ONLY = lambda gid: [p for p in pushes_to("home-fleet", gid)]
    MAIN_ONLY = lambda gid: told_to("home-beta-front", gid)

    # ================================================================ 1. a front-only project ends at its -main agent
    item(1, project="projects/beta", mover="home-peer3"); cli_row("home-peer3", "idle", IDLE0)
    check("1 step 1 (the notice again) sends nothing to -main or the fleet's builder", "a1" in stk(T1) and not MAIN_ONLY("a1") and not FLEET_ONLY("a1"), pushes())
    done = stk(T2)
    mp = MAIN_ONLY("a1")
    check("1 nobody can take it (no builder in the project, cold call off): the record carries the request and the mover is unchanged", "a1" in done and bool(ho(1).get("recovery_at")) and mt(1).get("mover") == "home-peer3", (done, ho(1)))
    check("1 …ONE message went to the project's -main agent, with no owner mark, naming the item and the quiet session, asking it to decide, owing no reply",
          len(mp) == 1 and mp[0][1].startswith("[stackshot] a1 ") and f"[for {OWN}]" not in mp[0][1] and "home-peer3" in mp[0][1] and "decide" in mp[0][1] and "no builder" in mp[0][1] and "no reply is owed" in mp[0][1], mp)
    check("1 …the fleet's builder was told nothing, and the quiet session got only the notice of step 1", not FLEET_ONLY("a1") and len(pushes_to("home-peer3", "a1")) == 1, pushes())
    check("1 …the History line says the -main agent was asked, and what was tried without a builder", "home-peer3 is quiet" in log_of(1)[-1]["text"] and "the message to home-beta-front starts no turn of its own" in log_of(1)[-1]["text"]
          and "project's builder" not in log_of(1)[-1]["text"], log_of(1))
    check("1 …the item is not on the owner's list, and later passes send nothing more", "decision" not in (mt(1).get("needs") or []) and not mt(1).get("ask") and stk(T2 + 21) == [] and stk(T2 + 5 * 3600) == [] and len(MAIN_ONLY("a1")) == 1, (mt(1), pushes()))
    close(1)

    # ================================================================ 2. a project with a builder is unchanged
    item(2, mover="home-peer"); cli_row("home-peer", "idle", IDLE0)
    stk(T1); stk(T2)
    check("2 a project with a builder: the builder takes the item (the first choice, as before), and neither the -main agent nor the fleet's builder is asked", mt(2).get("mover") == "team-back" and ho(2).get("to") == "team-back"
          and not ho(2).get("recovery_at") and not pushes_to("home-front", "a2") and not FLEET_ONLY("a2"), (mt(2), ho(2), pushes()))
    close(2)
    item(3, mover="team-back"); cli_row("team-back", "idle", IDLE0)
    stk(T1); stk(T2)
    rp = FLEET_ONLY("a3")
    check("2 …and when the quiet session is the builder itself, the last rung asks the fleet's builder, unmarked, in the old wording; the project's -main agent is told nothing",
          len(rp) == 1 and rp[0][1].startswith("[stackshot] fleet recovery: a3 ") and not rp[0][1].startswith("[for") and "usual path" in rp[0][1] and not pushes_to("home-front", "a3") and bool(ho(3).get("recovery_at")), (rp, ho(3), pushes_to("home-front", "a3")))
    check("2 …the History line names the fleet's builder", "home-fleet was asked to recover it" in log_of(3)[-1]["text"], log_of(3))
    close(3)

    # ================================================================ 3. the -main agent is itself the quiet one; no -main agent to name
    item(4, project="projects/beta", mover="home-beta-front"); cli_row("home-beta-front", "idle", IDLE0)
    stk(T1); stk(T2)
    check("3 a front-only project whose quiet mover is its -main agent: nobody is above it in the project, so the fleet's builder is asked (unmarked), and the -main agent is told nothing",
          len(FLEET_ONLY("a4")) == 1 and FLEET_ONLY("a4")[0][1].startswith("[stackshot] fleet recovery: a4 ") and not MAIN_ONLY("a4") and bool(ho(4).get("recovery_at")), (pushes_to("home-fleet", "a4"), MAIN_ONLY("a4"), ho(4)))
    close(4)

    CALLS = []
    _real_tgt = _pane_recovery._recovery_target
    def _counting(project, quiet):
        out = _real_tgt(project, quiet); CALLS.append((project, quiet, out)); return out
    def rec(to, frm="home-send", **kw):
        """A hand-off record made by the machinery an hour ago (delivered, not taken), for an item that is written to disk with it."""
        return H.new_record(to, U[to], frm, now0 - 3600, **{"delivered_at": now0 - 3500, **kw})
    # ================================================================ 5. what the request says: who was actually asked, what was tried, computed once
    def ev_texts(i): return [e["text"] for e in ho(i).get("events", [])]
    def msgs(gid, who): return [p[1] for p in told_to(who, gid)]
    # (a) the -main agent was asked: every line that names the recipient says so, not the fleet's builder
    item(10, project="projects/beta", mover="home-peer3"); cli_row("home-peer3", "idle", IDLE0)
    CALLS.clear(); _pane_recovery._recovery_target = _counting
    stk(T1); stk(T2)
    _pane_recovery._recovery_target = _real_tgt
    check("5 the target is computed once per request (the record, the wording of `tried` and the send follow the one answer)", len([c for c in CALLS if c[0] == "projects/beta" and c[1] == "home-peer3"]) == 1 and len(CALLS) == 1, CALLS)
    check("5 …the hand-off record says who was asked, and its event line names the -main agent, not the fleet's builder", ho(10).get("recovery_by") == "the project's -main agent"
          and any("the project's -main agent was asked" in t for t in ev_texts(10)) and not any("fleet's builder" in t for t in ev_texts(10)), (ho(10), ev_texts(10)))
    check("5 …`get` reads it the same way (the hand-off line)", any("the project's -main agent was asked to recover it" in l for l in H.words({**rd(10), "gid": "a10"}, T2, None, lambda x: x)) and not any("fleet" in l for l in H.words({**rd(10), "gid": "a10"}, T2, None, lambda x: x)), H.words({**rd(10), "gid": "a10"}, T2, None, lambda x: x))
    check("5 …the journal note of the History write names the -main agent", any(g == "a10" and "the project's -main agent was told" in n for g, n in NOTES) and not any(g == "a10" and "fleet" in n and "recovery" not in n for g, n in NOTES), [n for g, n in NOTES if g == "a10"])
    check("5 …and what was tried says there was no builder (a stall record: the notice again and a fresh session's call)", any("What the ladder tried: the stall pass sent the notice again and asked a fresh session who takes it." in t for t in msgs("a10", "home-beta-front"))
          and not any("project's builder" in t for t in msgs("a10", "home-beta-front")), msgs("a10", "home-beta-front"))
    _it10 = rd(10); H.touch(_it10, "home-peer3", U["home-peer3"], T2 + 60, handoff_svc.ho_same)
    check("5 …the mover writing ends the request and the record forgets who was asked", not (_it10["metadata"]["handoff"].get("recovery_at") or _it10["metadata"]["handoff"].get("recovery_by")), _it10["metadata"]["handoff"])
    close(10)

    # (b) a front-only project whose quiet mover is its -main agent: the fleet's builder is asked, and no builder was tried (there is none)
    item(11, project="projects/beta", mover="home-beta-front"); cli_row("home-beta-front", "idle", IDLE0)
    stk(T1); stk(T2)
    check("5 a quiet -main agent: the fleet's builder is asked, the record and the History line say so", ho(11).get("recovery_by") == "the fleet's builder" and any("the fleet's builder was asked" in t for t in ev_texts(11)) and bool(ho(11).get("recovery_at")), (ho(11), ev_texts(11)))
    check("5 …and the request does not say the project's builder was tried: the project has none", len(FLEET_ONLY("a11")) == 1 and "What the ladder tried: the stall pass sent the notice again and asked a fresh session who takes it." in FLEET_ONLY("a11")[0][1]
          and "project's builder" not in FLEET_ONLY("a11")[0][1] and not any("project's builder" in x["text"] for x in log_of(11)), (FLEET_ONLY("a11"), log_of(11)))
    close(11)

    # (c) the hand-off ladder (a record that is no stall record): the same, in the hand-off ladder's words
    item(12, project="projects/beta", mover="home-beta-front", handoff=rec("home-beta-front"))
    hcold_svc.handoff_recover("a12", "home-beta-front did not take it"); drain()
    check("5 the hand-off ladder, a quiet -main agent: the fleet's builder is asked and what was tried leaves out the project's builder", len(FLEET_ONLY("a12")) == 1 and "What the ladder tried: the hand-off ladder tried a fresh session's call and the sender." in FLEET_ONLY("a12")[0][1]
          and "project's builder" not in FLEET_ONLY("a12")[0][1], FLEET_ONLY("a12"))
    close(12)
    item(13, project="projects/beta", mover="home-peer3", handoff=rec("home-peer3"))
    hcold_svc.handoff_recover("a13", "home-peer3 did not take it"); drain()
    check("5 the hand-off ladder, a quiet session of a front-only project: its -main agent is asked, in its words, and what was tried leaves out the project's builder", len(MAIN_ONLY("a13")) == 1 and "the hand-off ladder tried a fresh session's call and the sender." in MAIN_ONLY("a13")[0][1]
          and "project's builder" not in MAIN_ONLY("a13")[0][1] and ho(13).get("recovery_by") == "the project's -main agent", (MAIN_ONLY("a13"), ho(13)))
    close(13)

    # (d) a project with a builder keeps the old words everywhere
    item(14, mover="team-back"); cli_row("team-back", "idle", IDLE0)
    stk(T1); stk(T2)
    check("5 a project with a builder: the fleet's builder, `recovery_by` the same, and what was tried still names the project's builder", ho(14).get("recovery_by") == "the fleet's builder" and len(FLEET_ONLY("a14")) == 1
          and "asked a fresh session who takes it and tried the project's builder." in FLEET_ONLY("a14")[0][1], (ho(14), FLEET_ONLY("a14")))
    close(14)

    # (e) the text a session reads in `get`'s description (the stall form) names the -main agent as well as the fleet's builder
    check("5 the served stall form says where a recovery message goes: a front-only project's -main agent, else the fleet's builder (it said the fleet's builder only)",
          "the project's -main agent when the project has no builder, to the fleet's builder otherwise" in _wt_get._STALL_FORM and "the fleet's builder is sent one message" not in _wt_get._STALL_FORM, _wt_get._STALL_FORM[:200])

    # ================================================================ 4. the choice on its own
    tgt = _pane_recovery._recovery_target
    check("4 a front-only project with a -main agent -> (that agent, main)", tgt("projects/beta", "home-peer3") == ("home-beta-front", "main", True), tgt("projects/beta", "home-peer3"))
    check("4 …the quiet session is that agent (by name or by id) -> the fleet's builder", tgt("projects/beta", "home-beta-front") == ("home-fleet", "fleet", True) and tgt("projects/beta", U["home-beta-front"]) == ("home-fleet", "fleet", True), (tgt("projects/beta", "home-beta-front"), tgt("projects/beta", U["home-beta-front"])))
    check("4 a project with a builder -> the fleet's builder, whoever is quiet", tgt("projects/alpha", "home-peer") == ("home-fleet", "fleet", False) and tgt("projects/alpha", "team-back") == ("home-fleet", "fleet", False), tgt("projects/alpha", "home-peer"))
    check("4 a project nobody lists (front-only, no -main agent to name: builderless) and an empty project (no read made: not builderless) -> the fleet's builder", tgt("projects/nowhere", "home-peer") == ("home-fleet", "fleet", True) and tgt("", "home-peer") == ("home-fleet", "fleet", False), (tgt("projects/nowhere", "home-peer"), tgt("", "home-peer")))
    _real_fo = _anc.front_only
    _anc.front_only = lambda *a, **k: 1 / 0
    import io, contextlib
    with contextlib.redirect_stderr(io.StringIO()) as eb: boom = tgt("projects/beta", "home-peer3")
    _anc.front_only = _real_fo
    check("4 a front-only test that raises keeps the fleet's builder and says so on stderr", boom == ("home-fleet", "fleet", False) and "front-only test of projects/beta failed" in eb.getvalue(), (boom, eb.getvalue()))

    return ran, fails


# ================================================================ part project: one walk through a front-only project
def part_project():
    tmp, T = _setup("foproject-", example=False, transcripts=("no-such-root", "transcripts"), own_owner=True)
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
    for d in ("store/a", "fleet/a", "brain/projects/bd", "transcripts/-home-x", "cli", "state"): (T / d).mkdir(parents=True)
    check, fails, ran = _checker(1800)

    # The pages. fo: the front-only project (three front agents, -main first). bd: a project with a builder. nb: its one background agent only watches (no builder, so front-only too).
    # bd/side: a sub-page with a front map of its own under bd. tw1 and tw2: two pages that list the same builder.
    FM, FD, FS = "home-fo-main", "home-fo-desk", "home-fo-side"
    BM, BD, BB, BS = "home-bd-main", "home-bd-desk", "home-bd-builder", "home-bd-side"
    NM, ND, NW = "home-nb-main", "home-nb-desk", "home-nb-watch"
    T1M, T1D, T2M, T2D, SHARED = "home-t1-main", "home-t1-desk", "home-t2-main", "home-t2-desk", "home-shared-builder"
    LONER = "home-loner"
    NAMES = (FM, FD, FS, BM, BD, BB, BS, NM, ND, NW, T1M, T1D, T2M, T2D, SHARED, LONER)
    U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
    now0 = time.time()
    DEAD_ISO = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now0 - 3 * 3600))      # gone three hours: past [client] dead_after_minutes
    def heartbeat(*gone):
        (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
        (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", **({"gone": DEAD_ISO} if n in gone else {})} for n, u in U.items()}))
    heartbeat()
    BUILDS, WATCHES = "builds, merges and releases the code", "watches the clock"
    PAGES = {"projects/fo": ({FM: "the front", FD: "answers questions", FS: "answers other questions"}, {}),
             "projects/bd": ({BM: "the front", BD: "answers questions", BB: BUILDS}, {BB: BUILDS}),
             "projects/bd/side": ({BS: "front for the side page"}, {}),
             "projects/nb": ({NM: "the front", ND: "answers questions", NW: WATCHES}, {NW: WATCHES}),
             "projects/t1": ({T1M: "the front", T1D: "answers questions", SHARED: BUILDS}, {SHARED: BUILDS}),
             "projects/t2": ({T2M: "the front", T2D: "answers questions", SHARED: BUILDS}, {SHARED: BUILDS})}
    def proj(agents, back):
        return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
    (T / "store/projects.json").write_text(json.dumps({"pages": {k: proj(a, b) for k, (a, b) in PAGES.items()}}))
    for key, (agents, back) in PAGES.items():
        path = T / f"brain/{key}.md"; path.parent.mkdir(parents=True, exist_ok=True)
        front = [k for k in agents if k not in back]
        path.write_text(f"---\ntitle: {key}\ndisplay-name: {key.replace('/', '-')}\nagents:\n" + "".join(f"  {k}: {agents[k]}\n" for k in front)
                        + ("  background:\n" + "".join(f"    {k}: {agents[k]}\n" for k in back) if back else "") + f"---\n\n# {key}\n\n## Current state\n\nSTATE-OF-{key.upper()}: the vendor call is open.\n\n<!-- timeline -->\n")
    (T / "store/next-id").write_text("200"); (T / "store/anchors.json").write_text("{}")
    DESC = "- Goal: A thing\n- It lives here\n- Done when done"
    B = now0 - 900.0
    def put(i, project="projects/fo", mover=FM, status="open", updated=None, **meta):
        up = B if updated is None else updated
        base = {"owner": U[FM], "project": project, "next": f"{mover}: do the thing"}
        if mover: base["mover"] = mover
        base.update(meta)
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                           "updated": up, "state_updated": up, "confirmed": up, "metadata": base}))
    def sid(i):
        """the store id of an item named as the board shows it (`a12`, `12`, `s201`)"""
        g = str(i); g = _model_ids._norm_id(g) if not g.isdigit() else f"a{g}"
        return f"store/{g[0]}/{g[1:]}.json"
    def rd(i): return json.loads((T / sid(i)).read_text())
    def mt(i): return rd(i)["metadata"]
    def close(*ids):
        for i in ids:
            d = rd(i); d["status"] = "completed"; (T / sid(i)).write_text(json.dumps(d))
    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
    from stackshot.web.tools import update as _wt_update, create as _wt_create, message as _wt_message
    from stackshot.web.routes import client_api as _rt_client
    from stackshot.fleet import client as _client
    from stackshot.waits import handoff as H
    from stackshot.service import handoff as handoff_svc, telling
    from stackshot.core import instance as _core_instance, config as _cfg
    from stackshot.router import routing as _routing, router as _router
    from stackshot.anchors import anchors as _anc
    from stackshot.web import publish as _web_publish, page_debts as _web_page_debts
    from stackshot.model import ids as _model_ids
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    _web_page_debts._owing_note = lambda debtor: ""
    OWN = _core_instance.OWNER
    # every push to a session the server would make goes to a recorder: [session id, text]
    PUSHLOG = T / "push.log"
    (T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
    telling.PUSH = [sys.executable, str(T / "fakepush.py")]
    THREADS = []
    _real_tell = telling.tell_woken
    TOLD = []      # every notice the server tells, as [session id, text], pushed or not: a request to a -main agent is a progress notice (telling.tell_own_move), held while nobody is there, so its checks read this
    def _tell(gid, owner, note, tag="wake", **kw):
        TOLD.append([owner, note])
        th = _real_tell(gid, owner, note, tag, **kw)
        if th: THREADS.append(th)
        return th
    telling.tell_woken = _tell
    def drain():
        from stackshot.service import handoff_cold as hcold_svc
        while THREADS: THREADS.pop(0).join(30)
        while hcold_svc.HO_COLD_THREADS: hcold_svc.HO_COLD_THREADS.pop(0).join(30)
        while THREADS: THREADS.pop(0).join(30)
    def pushes(): return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
    def pushes_to(who, gid=None): return [p for p in pushes() if p[0] == U[who] and (gid is None or gid in p[1])]
    def texts(who, gid=None): return [p[1] for p in pushes_to(who, gid)]
    _cfg.CFG["model"] = {}; _cfg.CFG["stall"] = {}
    from stackshot.service import handoff_cold as _hc
    _hc.COLD_RUNNER = lambda msg: {"status": "spawn", "note": "no call expected"}
    _cfg.CFG["model"] = {"cold_call": False}
    def cli_row(who, status, at):
        (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": U[who], "name": who, "status": status, "statusUpdatedAt": int(at * 1000), "updatedAt": int(at * 1000)}))
    handoff_svc.CLI_SESSIONS = T / "cli"
    for w in (FM, FD, FS, BM, BD, BB, NM, ND): cli_row(w, "busy", now0)
    WAKE = time.strftime("%Y-%m-%d", time.gmtime(now0 + 5 * 86400))
    ASK = "Decide: a or b - Recommend: a - Stakes: none - By: no date"
    def call(fn):
        """the tool's reply, or the refusal's text when it refuses"""
        try: return fn()
        except Exception as e: return str(e)    # noqa: BLE001
    def refusal(fn):
        try: return fn() and ""
        except Exception as e: return str(e)    # noqa: BLE001
    def held(i): return telling.holder({**rd(i), "gid": _model_ids._norm_id(str(i)) if not str(i).isdigit() else f"a{i}"})
    def upd(i, sender, **kw): return _wt_update.stackshot_update(item_id=f"a{i}", sender=sender, **kw)
    def FOR(peer, page): return f'message(to=\'{page}\') with the first line "For {peer}, ..."'
    HANDOFF = lambda who, gid: [t for t in texts(who, gid) if "handed to you by" in t]

    # ---- 0. one predicate
    from stackshot.service import handoff as _h
    KEYS = ("projects/fo", "projects/bd", "projects/bd/side", "projects/nb", "projects/t1", "projects/t2", "projects/ghost", "")
    check("0.1 front_only is exactly 'no builder' (handoff_builder empty) on every page of the fixture", all(_anc.front_only(k) == (not _h.handoff_builder(k)) for k in KEYS), [(k, _anc.front_only(k), _h.handoff_builder(k)) for k in KEYS])
    check("0.2 a page of front agents only is front-only; a page that lists a builder is not", _anc.front_only("projects/fo") is True and _anc.front_only("projects/bd") is False, None)
    check("0.3 a page whose only background agent does not build is front-only", _anc.front_only("projects/nb") is True and _h.handoff_builder("projects/nb") == [], _h.handoff_builder("projects/nb"))
    check("0.4 a sub-page with a front map of its own under a hub that has a builder is not front-only (it reads its hub's builder)", _anc.front_only("projects/bd/side") is False and _h.handoff_builder("projects/bd/side") == [BB], _h.handoff_builder("projects/bd/side"))
    check("0.5 a builder listed on two pages is the builder of both", _anc.front_only("projects/t1") is False and _anc.front_only("projects/t2") is False and _h.handoff_builder("projects/t2") == [SHARED], None)


    # ---- 1. mover= hand-over
    NOBUILD = "has no builder to hand it to, so the item stays with its current mover"
    put(1, mover=FM)
    r = call(lambda: upd(1, FM, mover=FD, next=f"{FD}: take it from here")); drain()
    check("1.1 a peer's mover= to another front agent of the front-only project is accepted: the mover changes, the reply says there is no builder and that the target is told", "Refused" not in r and held(1) == FD and mt(1).get("mover") == FD
          and f"projects/fo has no builder, so mover={FD} stays as sent" in r and f"{FD} has been told it is handed a1" in r, r)
    check("1.2 …the target is told once by a hand-off notice that names the hander, and the hand-off is recorded", len(HANDOFF(FD, "a1")) == 1 and f"handed to you by {FM}" in HANDOFF(FD, "a1")[0] and mt(1)["handoff"]["to"] == FD and mt(1)["handoff"]["from"] == FM, (texts(FD), mt(1).get("handoff")))
    check("1.3 …nothing is substituted: no server_fixed mark for the front-mover rule", "front_mover" not in json.dumps(mt(1).get("server_fixed") or ""), mt(1).get("server_fixed"))
    put(2, mover=FM)
    r = call(lambda: upd(2, BB, mover=FD, next=f"{FD}: take it from here", check="item_closed a1")); drain()
    check("1.4 the sender need not belong to the project: a background agent of another project hands it over too, and the target is told", "Refused" not in r and held(2) == FD and len(HANDOFF(FD, "a2")) == 1, (r, texts(FD, "a2")))
    r = call(lambda: _wt_create.stackshot_create(subject="[home] handed on create", description=DESC, project="projects/fo", sender=BB, mover=FD, next=f"{FD}: take it", check="item_closed a1")); drain()
    gid = r.split()[1]
    check("1.5 a create hands it over the same way", r.startswith("created") and held(gid) == FD and any("handed to you by" in t for t in texts(FD, gid)) and "Refused" not in r, r)
    put(3, mover=FM)
    r = call(lambda: upd(3, LONER, mover=FD, next=f"{FD}: take it"))
    check("1.6 a session no page lists is refused, naming that half and the path to the peer: the page key with `For <peer>,` on its first line; the item stays", r.startswith("Refused:") and NOBUILD in r and "this call was refused because home-loner is not a session any project page lists." in r
          and f"To ask {FD} for a check or an answer, {FOR(FD, 'projects/fo')}." in r and held(3) == FM, r)
    put(4, mover=FM)
    r = call(lambda: upd(4, BB, mover=BM, next=f"{BM}: take it", check="item_closed a1"))
    check("1.7 another project's front agent as the target is refused, naming that half, and the path names that agent's own page", r.startswith("Refused:") and NOBUILD in r and f"this call was refused because {BM} is not a live front agent of projects/fo." in r
          and f"To ask {BM} for a check or an answer, {FOR(BM, 'projects/bd')}." in r and held(4) == FM, r)
    put(5, project="projects/bd", mover=BB)
    r = call(lambda: upd(5, BM, mover=BD, next=f"{BB}: take it"))
    check("1.8 contrast, a project with a builder: the same hand-over to a front agent is replaced by the builder, and the reply says so and names the `For <peer>,` path", f"mover={BB}, the project's builder, was used instead" in r and held(5) == BB and mt(5).get("mover") == BB
          and f'message(to=\'projects/bd\') with the first line "For {BD}, ..."' in r and "front_mover" in json.dumps(mt(5).get("server_fixed") or ""), (r, mt(5).get("server_fixed")))
    put(6, project="projects/nb", mover=NM)
    r = call(lambda: upd(6, NM, mover=ND, next=f"{ND}: take it")); drain()
    check("1.9 a project whose only background agent does not build is front-only: the hand-over passes and the peer is told", "Refused" not in r and held(6) == ND and len(HANDOFF(ND, "a6")) == 1, r)
    put(7, project="projects/bd/side", mover=BB)
    r = call(lambda: upd(7, BS, mover=BM, next=f"{BB}: take it"))
    check("1.10 a sub-page with a front map of its own under a builder's hub takes the builder's path: the front agent is replaced by the builder", f"mover={BB}, the project's builder, was used instead" in r and held(7) == BB, r)
    close(1, 2, 3, 4, 5, 6, 7, gid)

    # ---- 2. then= and post_wake_mover= take the same exception
    put(10, mover=OWN, needs=["decision"], ask=ASK, then=FM, state="your-call")
    drain(); pn = len(pushes())
    r = call(lambda: upd(10, BB, then=FD)); drain()
    check("2.1 then=<front agent> from a listed session of another project is accepted in the front-only project, and nobody is told by this write (the owner's answer moves the item)", "Refused" not in r and mt(10).get("then") == FD
          and f"projects/fo has no builder, so then={FD} is not replaced by one" in r and len(pushes()) == pn and "handoff" not in mt(10), (r, pushes()[pn:]))
    put(11, mover=OWN, needs=["decision"], ask=ASK, then=FM, state="your-call")
    r = call(lambda: upd(11, LONER, then=FD))
    check("2.2 …from a session no page lists it is refused as mover= is, naming the half and the `For <peer>,` path; then is unchanged", r.startswith("Refused:") and NOBUILD in r and "this call was refused because home-loner is not a session any project page lists." in r
          and f"To ask {FD} for a check or an answer, {FOR(FD, 'projects/fo')}." in r and mt(11).get("then") == FM, r)
    put(12, mover=FM, state="your-step", step="run it", hold=True, wake=WAKE, wait_kind="time", post_wake_mover=FM, next=f"{OWN}: run it")
    drain(); pn = len(pushes())
    r = call(lambda: upd(12, BB, post_wake_mover=FD, wait_basis=f"the vendor's reply is due {WAKE}")); drain()
    check("2.3 post_wake_mover=<front agent> is accepted the same way (stored as the mover that picks it up when the wait ends), with no hand-off notice", "Refused" not in r and mt(12).get("mover") == FD and f"post_wake_mover={FD} is not replaced by one" in r
          and not HANDOFF(FD, "a12") and len(pushes()) == pn, (r, mt(12).get("mover"), pushes()[pn:]))
    put(13, mover=FM, state="your-step", step="run it", hold=True, wake=WAKE, wait_kind="time", post_wake_mover=FM, next=f"{OWN}: run it")
    r = call(lambda: upd(13, LONER, post_wake_mover=FD, wait_basis=f"the vendor's reply is due {WAKE}"))
    check("2.4 …and refused from a session no page lists, as mover= is, the item untouched", r.startswith("Refused:") and "post_wake_mover=" + FD in r and "this call was refused because home-loner is not a session any project page lists." in r and mt(13).get("post_wake_mover") == FM, r)
    put(14, project="projects/bd", mover=OWN, needs=["decision"], ask=ASK, then=BB, state="your-call")
    r = call(lambda: upd(14, BM, then=BD))
    check("2.5 contrast, a project with a builder: then=<front agent> is replaced by the builder", f"then={BB}, the project's builder, was used instead" in r and mt(14).get("then") == BB, r)
    put(15, project="projects/bd", mover=BM, state="your-step", step="run it", hold=True, wake=WAKE, wait_kind="time", post_wake_mover=BM, next=f"{OWN}: run it")
    r = call(lambda: upd(15, BM, post_wake_mover=BD, wait_basis=f"the vendor's reply is due {WAKE}"))
    check("2.6 …and post_wake_mover=<front agent> likewise", f"post_wake_mover={BB}, the project's builder, was used instead" in r and mt(15).get("mover") == BB, (r, mt(15).get("mover")))
    close(10, 11, 12, 13, 14, 15)

    # ---- 3. a step may open with a live peer
    SP = "Put an open step before it"
    put(20, mover=FM, owner=U[FM], needs=[], next=f"{FM}: draft it")
    r = refusal(lambda: upd(20, FS, next=f"{FM}: draft it\n{FD}: check it"))
    check("3.1 in the front-only project a step opening with a live front peer passes on an item another session moves, with an open step before it", r == "" and mt(20)["next"].splitlines()[-1] == f"{FD}: check it" and held(20) == FM, (r, mt(20).get("next")))
    drain(); pn = len(pushes())
    out = call(lambda: upd(20, FM, done=[1])); drain()
    check("3.2 marking the step before it done hands the item to the peer: the reply says so, the mover changes and the peer is told once, by the hand-off notice", f"the next step is {FD}'s" in out and held(20) == FD and mt(20).get("mover") == FD
          and len(pushes()) == pn + 1 and len(pushes_to(FD, "a20")) == 1 and "is yours" in texts(FD, "a20")[-1] and f"{FD}: check it" in texts(FD, "a20")[-1], (out[-400:], pushes()[pn:]))
    put(21, mover=FM, owner=U[FM], needs=[], next=f"{FM}: draft it")
    before = (T / sid(21)).read_bytes()
    r = call(lambda: upd(21, FM, reword={"1": f"{FD}: draft it"}))
    check("3.3 a peer's step as the FIRST open step is refused (nothing would move the item to it): the refusal names the ways out (mover=<peer>, or `For <peer>,` to the page key); the item is untouched", r.startswith("Refused:") and SP in r and f"mover={FD}" in r
          and f'starts "For {FD},"' in r and (T / sid(21)).read_bytes() == before, r)
    put(22, mover=FM, owner=U[FM], needs=[], next=f"{FM}: draft it")
    r = call(lambda: upd(22, FM, next=f"{FM}: draft it\n{BM}: check it"))
    check("3.4 another project's front agent as the opener is refused, and the tail names what works: mover=<it> (between front agents of one project that has no builder) or `For <it>,` to the page key", r.startswith("Refused:")
          and f'the step "{BM}: check it" opens with {BM}' in r and f"mover={BM} (only between front agents of one project that has no builder)" in r and f'a message to projects/bd whose first line starts "For {BM},"' in r and mt(22)["next"] == f"{FM}: draft it", r)
    put(23, project="projects/bd", mover=BB, owner=U[BM], needs=[], next=f"{BB}: draft it")
    r = call(lambda: upd(23, BM, next=f"{BB}: draft it\n{BD}: check it"))
    check("3.5 contrast, a project with a builder: a front agent's step on an item another session moves is refused, and the tail says to give the step to the builder", r.startswith("Refused:") and f'the step "{BD}: check it" opens with {BD}' in r and f'Give the step to {BB} (open it with "{BB}:")' in r
          and "mover=" not in r and mt(23)["next"] == f"{BB}: draft it", r)
    close(20, 21, 22, 23)

    # ---- 4. messages between front agents
    MARK = f"[for {OWN}]"
    r = call(lambda: _wt_message.stackshot_message(to=FD, text="Can you check the vendor call before noon?", sender=FM))
    check("4.1 an unmarked message from a front agent to a peer in a project with no background agent starts no turn: it is held for the peer's next turn, and where its hook cannot fetch held lines the sender is told it was not passed on", r.startswith("not passed on") and f"{FD} is a front agent" in r and "could not be held" in r, r)
    r = call(lambda: _wt_message.stackshot_message(to="projects/fo", text=f"For {FD}, can you check the vendor call before noon?", sender=FM))
    m42 = re.match(r"held for the router \u2014 the router rules notice (\w+) within about 60 s and passes it to the agent of projects/fo it fits", r)
    rec42 = next((n for n in _routing.read("projects/fo") if m42 and n.get("id") == m42.group(1)), {})
    first42 = (rec42.get("text") or "").splitlines()[0] if rec42.get("text") else ""
    tgt42 = _router._FOR_AGENT.match(first42)
    check("4.2 …and that form is accepted: held for the router, which rules the notice and passes it to the agent of the page it fits; the recorded notice is addressed to the project page and its first line names the peer, which the router's for-agent rule reads as that front agent", bool(m42) and rec42.get("label") == "message to projects/fo"
          and first42.startswith(f"For {FD},") and bool(tgt42) and tgt42.group(1) == FD and _anc.session_roles()[FD]["role"] == "front" and _anc.session_roles()[FD]["project"] == "projects/fo", (r, rec42))
    r = call(lambda: _wt_message.stackshot_message(to=FD, text=f"{MARK} nothing is needed from you, this is only an FYI", sender=FM))
    check("4.3 a marked message that says nothing is needed from the owner is a note: held for the next turn (here not passed on, its hook cannot fetch held lines), and does not offer the `For <peer>,` form (it would route around the gate)", r.startswith("not passed on") and f"{FD} is a front agent" in r and "For " + FD not in r, r)
    r = call(lambda: _wt_message.stackshot_message(to=FM, text="Can you check the vendor call before noon?", sender=BB))
    check("4.4 contrast: a sender that is no front agent (another project's builder) gets the same answer, and is not offered the `For <peer>,` form", r.startswith("not passed on") and f"{FM} is a front agent" in r and "For " + FM not in r, r)
    r = call(lambda: _wt_message.stackshot_message(to=BD, text="Can you check the vendor call before noon?", sender=BM))
    check("4.5 contrast, a project with a builder: a front agent's unmarked message to its peer is the channel between front agents, not a message for the builder: held for the peer's next turn (here not passed on, its hook cannot fetch held lines), never refused to the builder", r.startswith("not passed on") and f"{BD} is a front agent" in r and f"message(to='{BB}'" not in r, r)

    # ---- 5. needs= naming a peer
    put(30, mover=FM)
    r = call(lambda: upd(30, FM, needs=[FD]))
    check("5.1 needs=[<peer>] is refused with the two ways that work: mover=<peer> (it is told) or the peer's own item linked with after=; it no longer points at an empty list of background agents", r.startswith("Refused:") and f"{FD} is a front agent of projects/fo" in r
          and f"set mover={FD} (it is told)" in r and "after=[" in r and "no background agent named" not in r and mt(30).get("needs") in (None, []), (r, mt(30).get("needs")))
    put(31, project="projects/bd", mover=BB)
    r = call(lambda: upd(31, BB, needs=[BD]))
    check("5.2 contrast, a project with a builder: the refusal names the builder (and the peer's own item with after=), not mover=<peer>", r.startswith("Refused:") and f"For projects/bd: {BB}" in r and "after=[" in r and "set mover=" not in r, r)
    close(30, 31)

    # ---- 6. a script's item-open
    me = socket.gethostname(); _client.mint(me)
    def io_(project, mover, marker, **kw):
        b = {"marker": marker, "project": project, "subject": "Deep-scan the suites", "mover": mover, "step": f"{mover}: deep-scan the suites, report", "description": ["- A scan is due", "- It is the first step"], "sender": "scan-job"}
        b.update(kw)
        return _rt_client._client_post(me, "item-open", b)
    def store_files(): return sorted(f for f in (T / "store").glob("*/*.json") if f.stem.isdigit())
    def store_ids(): return [f"{f.parent.name}{f.stem}" for f in store_files()]
    def close_all():
        for f in store_files():
            d = json.loads(f.read_text())
            if d.get("status") == "open": d["status"] = "completed"; f.write_text(json.dumps(d))
    close_all()
    n0 = len(store_ids())
    st, out = io_("projects/fo", "home-fo-builder", "scan:fo")
    fit = rd(out["item"]) if st == 200 else {"metadata": {}, "description": ""}; fm = fit["metadata"]
    check("6.1 a script's item-open for the front-only project (the page lists no background agent) is filed, not refused: the mover is the project's -main agent, the reply says fallback", st == 200 and out["mover"] == FM and out["owner"] == FM and out["fallback"] is True and out["repeat"] is False
          and len(store_ids()) == n0 + 1, (st, out))
    check("6.2 …the item is held by the -main agent, names no one in needs, the step keeps its words under the -main agent's name, and the description says why", held(out["item"]) == FM and not fm.get("needs") and fm.get("item_open_fallback") is True
          and fm.get("next", "").strip() == f"{FM}: deep-scan the suites, report" and fit["description"].splitlines()[-2:] == [f"- projects/fo lists no background agent, so this is with {FM}, its front agent", "- Opened by scan-job (a script on a client machine)"], (fm, fit["description"]))
    st, again = io_("projects/fo", "home-fo-builder", "scan:fo")
    check("6.3 a repeat call answers the open item (repeat, fallback) and files nothing", st == 200 and again["item"] == out["item"] and again["repeat"] is True and again["fallback"] is True and len(store_ids()) == n0 + 1, (st, again))
    st, e = io_("projects/fo", "x", "scan:fo2", description=[f"- line {i}" for i in range(7)])
    check("6.4 the extra line leaves one fewer for the caller: seven lines are refused, never cut", st == 400 and "lists no background agent" in e["error"] and len(store_ids()) == n0 + 1, (st, e))
    st, ok_ = io_("projects/bd", BB, "scan:bd")
    check("6.5 contrast, a project with a builder: the named background agent is the mover, needs name it, no fallback", st == 200 and ok_["mover"] == BB and ok_["fallback"] is False and [telling._session_label(x) for x in rd(ok_["item"])["metadata"].get("needs") or []] == [BB]
          and "item_open_fallback" not in rd(ok_["item"])["metadata"], (st, ok_))
    st, e = io_("projects/bd", BM, "scan:bd2", step=f"{BM}: scan")
    check("6.6 …and a front agent as the mover is refused, the page's background agent named", st == 400 and "not a background agent" in e["error"] and BB in e["error"], (st, e))
    for who in (BS, BB):
        st, e = io_("projects/bd/side", who, "scan:side", step=f"{who}: scan")
        check(f"6.7 a sub-page of front agents under a hub with a builder is no front-only project: mover {who} is refused, the page lists none, nothing filed", st == 400 and "not a background agent listed on projects/bd/side" in e["error"] and e["error"].endswith("the page lists none") and "fallback" not in e, (st, e))
    close_all()

    # ---- 7. orphan hand-over
    _cfg.CFG.setdefault("audit", {})["orphan_handover"] = "apply"
    put(40, mover=FM)
    put(41, project="projects/bd", mover=BB)
    for i in range(100, 130): put(i, mover=FD, project="projects/fo")      # a board of live movers around the two orphans (the pass reads more than a few gone sessions as a partial view of the fleet)
    heartbeat(FM, BB)
    drain(); pn = len(pushes())
    got = handoff_svc.orphan_handover(apply=True, now=now0); drain()
    from stackshot.waits import stall as ST
    rows = {m["id"]: m for m in got["moved"]}
    check("7.1 the pass moves both alive items whose mover's session is gone, each to the closest live agent of its project", got["applied"] and sorted(rows) == ["a40", "a41"] and rows["a40"]["to"] == FD and rows["a41"]["to"] == BM and mt(40).get("mover") == FD and mt(41).get("mover") == BM, got)
    check("7.2 the front-only project's new holder is told once, by the hand-off notice, and its History line says it is told", len(pushes_to(FD, "a40")) == 1 and "it came to you" in texts(FD, "a40")[0] and "is sent the one hand-off notice" in ST.log_of(mt(40))[0]["text"]
          and "no notice is sent" not in ST.log_of(mt(40))[0]["text"], (texts(FD, "a40"), ST.log_of(mt(40))))
    check("7.3 contrast, a project with a builder: its front agent that takes an item is sent nothing, and its History line says so", not pushes_to(BM) and "no notice is sent" in ST.log_of(mt(41))[0]["text"] and "sent the one hand-off notice" not in ST.log_of(mt(41))[0]["text"], (pushes_to(BM), ST.log_of(mt(41))))
    close_all(); heartbeat()

    # ---- 8. a hand-back to a front mover
    _cfg.CFG["board"] = {"handback_hold_seconds": 0}
    from stackshot.service import telling as _tl
    _real_live = _tl._router_live.is_live
    _tl._router_live.is_live = lambda project: False      # the router is not live for the project: the line is pushed at once, marked
    try:
        put(50, mover=FD, needs=[FM, FD], writer=FM)
        drain(); pn = len(pushes())
        r = call(lambda: upd(50, FM, needs=[FD])); drain()
        got = [x for x in pushes()[pn:] if x[0] == U[FD]]
        # the router is reported not live above: this pins the direct-push fallback and the decision (who is told); the router path is covered in router_live_scenario
        check("8.1 (direct-push fallback; the router path is in router_live_scenario) a write by another session that leaves needs naming the front mover alone tells that mover once, marked for the owner (the presence gate does not hold it), with the writer and the next line; the reply says so", len(got) == 1 and len(pushes()) == pn + 1
              and got[0][1].startswith(f"{MARK} [stackshot] a50 is back with you alone (handed back by {FM})") and f"next: {FD}: do the thing" in got[0][1] and f"{FD} is a front agent: told it is back with them alone" in r, (r[-300:], pushes()[pn:]))
        put(51, project="projects/bd", mover=BD, needs=[BB, BD], writer=BB)
        drain(); pn = len(pushes())
        r = call(lambda: upd(51, BM, needs=[BD])); drain()
        new = pushes()[pn:]
        check("8.2 contrast, a project with a builder: the builder is told the item is back with the front agent, and the front mover itself is not pushed to", not [x for x in new if x[0] == U[BD]] and len([x for x in new if x[0] in (U[BB], BB)]) == 1
              and f"is back with {BD}, a front agent, alone" in new[-1][1] and f"its builder {BB} is told it is back with them alone, not them" in r, (r[-300:], new))
    finally:
        _tl._router_live.is_live = _real_live

    # ---- 9. the take clock on a peer hand-off
    MIN = 60.0
    def tick(at, *ids): return handoff_svc.handoff_tick(now=at, only=[f"a{i}" for i in ids])
    def ho(i): return mt(i).get("handoff") or {}
    def main_asked(gid): return [p for p in TOLD if p[0] == U[FM] and gid in p[1] and "has gone quiet" in p[1]]
    close_all()
    put(60, mover=FS)
    upd(60, FS, mover=FD, next=f"{FD}: do the thing"); drain()
    d = float(ho(60)["delivered_at"])
    cli_row(FD, "idle", d + 60)      # its turn has ended: with the ladder off the -main agent is asked only of a pane that is not running a turn
    check("9.1 the hand-off is recorded for the new mover and its notice reached it once", ho(60).get("to") == FD and ho(60).get("from") == FS and len(HANDOFF(FD, "a60")) == 1, (ho(60), pushes()))
    check("9.2 before the take minutes the pass does nothing", tick(d + 5 * MIN, 60) == [] and len(texts(FD, "a60")) == 1, texts(FD, "a60"))
    done = tick(d + 11 * MIN, 60); drain()
    check("9.3 after the take minutes the new mover is reminded once, and only it; the hander and the -main agent are told nothing", done == ["a60"] and len(texts(FD, "a60")) == 2 and texts(FD, "a60")[1].startswith("[stackshot] reminder: a60 ")
          and bool(ho(60).get("reminded_at")) and not pushes_to(FS) and not pushes_to(FM, "a60"), (done, ho(60), pushes()))
    d2 = float(ho(60)["delivered_at"])
    done = tick(d2 + 22 * MIN, 60); drain()
    ask = main_asked("a60")
    check("9.4 after another take minutes the last rung asks the project's -main agent once, with no owner mark, naming the item and the quiet mover; the item stays with its mover and the hander is still told nothing", done == ["a60"] and len(ask) == 1
          and ask[0][1].startswith("[stackshot] a60 ") and MARK not in ask[0][1] and FD in ask[0][1] and mt(60).get("mover") == FD and not pushes_to(FS), (done, ask, pushes()))
    check("9.5 …later passes send nothing more", tick(d2 + 5 * 3600, 60) == [] and len(main_asked("a60")) == 1, pushes())
    # contrast: a project with a builder keeps a front agent's hand-off exempt (a front-to-front record the hand-over rule would refuse there, written as the machinery would have)
    put(61, project="projects/bd", mover=BD, handoff=H.new_record(BD, U[BD], BM, now0 - 3600, **{"delivered_at": now0 - 3500}))
    view = {**rd(61), "gid": "a61"}
    pn = len(pushes())
    check("9.6 contrast, a project with a builder: a hand-off to a front agent is exempt and is never clocked, however late", handoff_svc.handoff_exempt(view, BD) and not handoff_svc.handoff_peer(view, BD) and tick(time.time() + 86400, 61) == [] and len(pushes()) == pn, (ho(61), pushes()[pn:]))
    close_all()

    return ran, fails


MARK = "@@front_only part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"roster": part_roster, "ladder": part_ladder, "project": part_project}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        os._exit(0)      # as the project walk always ended: nothing a thread of the part left behind holds the process (tests/_scratch.py removes the scratch folder first)
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
    print(f"ok: front_only scenario, {total} checks")
