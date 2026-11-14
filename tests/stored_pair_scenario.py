"""Scenario test for the stored pair as the only source of the alive-or-waiting decision (model.view reading `phase` and `waits_on`, nothing else): the lists, the item page, the wire `list`, get's `model:` line, the home
page, every item page, the projects page and board.md show a stamped store byte-for-byte as the fields read it, at the clock now and at six later clocks once the minute sweep has run. Fixture data, no live store written, no
network, no server socket; the clock is held (tools/stamp_phase.frozen) so an edge is crossed by choosing the time.

There is no switch and no fallback to the fields: a stored pair decides, even where the fields say otherwise (until the sweep restamps it, within a minute); only an item that stores no usable pair is shown as the writer
would store it, and counts in model.UNSTAMPED. Everything else (until, event, the basis text, the watched set, the guards, the audit's filing rules) still comes from the fields.

  1  gone                 [model] read_stored, model.read_stored, check_stored, DISAGREEMENTS and STALE_AT_EDGE are gone, the example config has no such key, and /audit/status counts unstamped reads instead
  2  same_output          on a swept store (every pair stamped by one sweep at the clock) every surface (display_of: state word, kind, list word, model line, get, brief; named-in-next lines; the wire fields; the home
                          page, every item page, the projects page, board.md on both renderers; `_world_waits_text`) is byte-equal to the same store read from the fields alone, the watched map and the store bytes are equal
  3  stored_decides       a wrong, stale or half-stored pair: the stored one decides (g43 stored waiting on a plain doing item lists as waiting, g44 stored alive on a relay wait as agents, g50 and g49 likewise), a
                          phase with no waits_on or a value that is no phase is read from the fields and counted, and one sweep restamps every one of them to the fields' reading, after which the surfaces equal the fields'
  4  shifts               +30 min, +1 h, +6 h, the next local midnight, +3 days, +40 days: with a sweep at the clock every surface equals the fields' reading; without one, the pair stored at the clock now still decides
                          (the stale ones are the ones the sweep restamps), and nothing is written by reading; a copy of the live store when PHASE_REPLAY_STORE names one
  5  anchored             an outside item with no wait_kind: the item page's reading of "an anchor is scoped to it" and the server's give the same kind
  6  mutations            the checks above fail for a reader that works the decision out from the fields and ignores the stored pair, and for one that takes the stored waiting without its kind

    tests/run-suite stored_pair        → exit 0 / 1"""
import collections, contextlib, copy, datetime as dt, io, json, logging, os, pathlib, re, shutil, sys, time, zoneinfo
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="storedpair-"); T = pathlib.Path(tmp)


def mk_toml(root):
    t = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), owner=True)
    t = t.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in t
    for key, val in (("repo", root), ("store", f"{root}/store"), ("markdown", f"{root}/board.md"), ("brain", f"{root}/brain"),
                     ("state", f"{root}/state"), ("secrets", f"{root}/secrets"), ("project_touch", f"{root}/touch"), ("rules", f"{root}/RULES.md"), ("timezone", "Asia/Dubai")):
        t, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', t); assert n == 1, key
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^git = true', 'git = false'),
                     (r'(?m)^transcripts = .*$', f'transcripts = ["{root}/no-such-root", "{root}/transcripts"]'), (r"(?m)^require_marks = true", "require_marks = false")):
        t, n = re.subn(pat, rep, t, count=1); assert n == 1, pat
    return t


CONF = T / "stackshot.toml"
CONF.write_text(mk_toml(tmp), encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=str(CONF), STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None); os.environ.pop("STACKSHOT_READ_ONLY", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active", "board": [],
                                                                                "board_open": 0, "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": "https://example.invalid/x/9", "items": ["g52"], "added": 1, "by": "t"}]}))
DESC = "- A thing\n- It lives here\n- Done when done"
BACK = "team-back"; OWN = "Oliver"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.core import config; from stackshot.model import model as _model; from stackshot.tools import stamp_phase as SP; from stackshot.web import render as root_render
from stackshot.anchors import anchors as _anc
from stackshot.service import store as _service_store
from stackshot.waits import watchers as _watch
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import brief as _wt_brief
from stackshot.service import telling
from stackshot.core import store as _core_store
from stackshot.web.ui import render as ui_render
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
telling.front_sender = lambda who: False
(T / "state/waiting.json").write_text(json.dumps({"baseline": time.time() - 100 * 86400, "seen": {}, "reported": []}))
MODEL_CFG = dict(guards=True, watchers=True, pause=False, one_mover=True, handoff=True, switchover=False)
config.CFG.setdefault("model", {}).update(MODEL_CFG)
ZONE = zoneinfo.ZoneInfo("Asia/Dubai"); H = 3600.0; DAY = 86400.0
T0 = float(int(time.time() // 60 * 60))
local = lambda ep: dt.datetime.fromtimestamp(ep, ZONE).strftime("%Y-%m-%dT%H:%M")
day_of = lambda ep: dt.datetime.fromtimestamp(ep, ZONE).date()
midnight = lambda d: dt.datetime(d.year, d.month, d.day, tzinfo=ZONE).timestamp()
frozen = SP.frozen


@contextlib.contextmanager
def reading(stored):
    """True: the readers as they are (the stored pair decides). False: every reader works the decision out from the fields alone, as the board did before the pair was stored (model.view patched to the writer's reading)."""
    real = _model.view
    if not stored:
        _model.view = lambda item, mod, now=None, after_open=None, check=True: _model._shown(item, mod, now, after_open)
    try:
        yield
    finally:
        _model.view = real

def put(i, status="open", **meta):
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing"}; base.update(meta)
    su = T0 - 10 * DAY
    (T / f"store/g/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": su, "state_updated": su, "confirmed": su, "metadata": base}, ensure_ascii=False, indent=1))
def raw(i): return json.loads((T / f"store/g/{i}.json").read_text())

# ---- the fixture: every kind of wait and of alive, the three ways a doing item reads as waiting (each with an edge), stamped by one sweep; then items an older writer or a stale value left
D3 = day_of(T0) + dt.timedelta(days=3); MID3 = midnight(D3)
BASIS = {"text": "the subscription renews on 2099-01-20", "wake": local(T0 + 3 * H), "by": BACK, "at": T0}
NEXT_FAR = "team-back: check the build later and report back to the owner"
put(1, needs=[BACK], state="doing", hold=True, wake=local(T0 + 3 * H))                                                  # held, a wake: alive again an hour-ish before it
put(2, needs=[BACK], state="doing", wake=local(T0 + 3 * H), wait_basis=BASIS, next=NEXT_FAR)                            # a wait_basis wake
put(3, needs=[BACK], state="doing", wake=local(MID3 + 12 * H), next=f"team-back: after {D3.isoformat()} run the check")  # a dated step: alive at ZONE midnight of the day
put(4, needs=[BACK], state="doing", hold=True, wake=local(T0 + 90 * DAY))                                                # held far out
put(10, needs=[BACK], state="doing"); put(11, needs=["decision", BACK], state="your-call", ask="Decide: ship it · Recommend: ship it · Stakes: a week · By: no date")
put(12, needs=[BACK], state="parked", hold=True, wake=local(T0 + 20 * DAY), cap_ok={"wake": local(T0 + 20 * DAY), "by": "the owner", "quote": "park it until then"})
put(13, needs=[BACK], wait_kind="relay", wait_event="Acme's reply", ask_by=day_of(T0 + 9 * DAY).isoformat())
put(14, needs=[BACK], state="verifying", proof="the run lands", end=day_of(T0 + 30 * DAY).isoformat())
put(15, needs=["external"], state="outside", party="Acme legal", chase=day_of(T0 + 5 * DAY).isoformat())             # a relay
put(16, needs=["external"], state="outside", party="Acme legal", chase=day_of(T0 + 5 * DAY).isoformat(), wait_anchor="https://example.invalid/x/1")   # an anchor
put(17, needs=[BACK], state="your-step", step="Run the thing once", mover=OWN, next=f"{OWN}: run the thing once")
put(18, needs=[BACK], wait_kind="item", after=["g30"]); put(19, needs=[BACK], wait_kind="anchor", wait_anchor="https://example.invalid/x/2", wait_event="a reply", ask_by=day_of(T0 + 9 * DAY).isoformat())
put(20, needs=[BACK], wait_kind="event", wait_event="recycle", ask_by=day_of(T0 + 9 * DAY).isoformat()); put(21, needs=[BACK], wait_kind="time", wake=local(T0 + 9 * DAY))
put(22, needs=[BACK], state="doing", wake=local(T0 + 1800))                                                              # a near wake: a reminder, alive
put(30, needs=[BACK], state="doing"); put(31, needs=[BACK], after=["g30"])                                             # blocked by the view alone: no stored state, an open after link
put(32, needs=[BACK], state="doing", next="team-back: wait for board#1, then board#10 and board#31 and board#99 and board#40")      # the lines `named in next:` shows
put(52, needs=["external"], state="outside", party="Acme legal", chase=day_of(T0 + 5 * DAY).isoformat())              # an anchor is scoped to it in anchors.json: an anchor wait with no wait_anchor
put(40, status="completed", needs=[BACK], state="doing", outcome="done"); put(41, status="completed", needs=[BACK], state="doing", outcome="done", phase="waiting", waits_on="time")
with contextlib.redirect_stderr(io.StringIO()), frozen(T0):
    server._phase_sweep()
# items nobody stamped, and values that are wrong or half there: the fields must win
put(42, needs=[BACK], state="doing", hold=True, wake=local(T0 + 5 * DAY))                                                # never stamped, a view-only wait
put(43, needs=[BACK], state="doing", phase="waiting", waits_on="time")                                                 # stored waiting, the fields alive
put(44, needs=[BACK], wait_kind="relay", wait_event="Acme", ask_by=day_of(T0 + 9 * DAY).isoformat(), phase="alive")    # stored alive, the fields waiting
put(45, needs=[BACK], wait_kind="relay", wait_event="Acme", ask_by=day_of(T0 + 9 * DAY).isoformat(), phase="waiting")  # a phase with no waits_on
put(46, needs=[BACK], wait_kind="relay", wait_event="Acme", ask_by=day_of(T0 + 9 * DAY).isoformat(), phase="waiting", waits_on="time")      # the wrong kind
put(47, needs=[BACK], state="doing", phase="sleeping", waits_on="soon")                                                # values that are not a phase
put(48, needs=[BACK], state="doing", hold=True, wake=local(T0 + 5 * DAY), phase="alive")                                 # stored alive, the fields now make it a held wait
put(49, needs=["decision", BACK], state="your-call", ask="Decide: ship it · Recommend: ship it · Stakes: a week · By: no date", phase="waiting", waits_on="time")   # a non-doing item stored waiting
put(50, needs=[BACK], state="doing", phase="waiting", waits_on="item")                                                 # an `after` item that has closed: stored waiting on an item, the fields alive
STORE = T / "store"


# ---- the surfaces: everything a reader of the model shows, keyed by what it is
def surfaces(store, t, on):
    """The output of every reader of model.view for the store at `store`, the clock held at `t`, the decision read from the stored pair (`on`) or from the fields alone: {surface: text}."""
    out = {}
    with frozen(t), reading(on):
        items = SP.load_dir(store); opens = sorted((g for g, it in items.items() if it.get("status") == "open"), key=SP.num)
        ctx = server._WaitCtx(t)
        for g in opens:
            it = items[g]; probe = dict(it, gid=g)
            out[f"display {g}"] = json.dumps(SP.display_of(server, it, g, stored=on), sort_keys=True, ensure_ascii=False)
            out[f"named {g}"] = "\n".join(server._next_names_lines(probe))
            out[f"wire {g}"] = json.dumps([server._item_list(probe), server._basis_wait_of(probe), server._wait_fields(g, it, ctx)], sort_keys=True, default=str)
        for k in ("team-back", "home-front", "home-other", "home-owner", OWN):
            out[f"items? {k}"] = server._client_items(k)[2]
        out["world"] = _wt_brief._world_waits_text()
        now = dt.datetime.fromtimestamp(t, ZONE)
        ub = ui_render.Board(str(store), now=now)
        out["home"] = ub.html(); out["projects"] = ub.projects_html(); out["board.md"] = ub.markdown()
        out["kinds"] = json.dumps({r["gid"]: ub.state_kind(r) for r in ub.rows if r.get("status") == "open"}, sort_keys=True, default=str)
        for g in opens:
            out[f"page {g}"] = ub.item_html(g)
        out["old board.md"] = root_render.Board(str(store), now=now).markdown()
    return out
def differ(a, b, skip=()): return sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k) and not any(k.endswith(" " + s) for s in skip))
def hashes(store): return {str(p): p.read_bytes() for p in pathlib.Path(store).rglob("*.json")}
def counts(store, t, on):
    with frozen(t), reading(on):
        items = SP.load_dir(store)
        c = collections.Counter(); w = {}
        for g, it in items.items():
            if it.get("status") != "open": continue
            m = _model.view(dict(it, gid=g), server._model_of(dict(it, gid=g)), after_open=lambda i_: server._after_open(i_.get("metadata") or {}), check=False)
            c[_model.shown_pair(m)] += 1; w[g] = bool(_watch.watches(it))
        return dict(c), w
def with_store(src, fn):
    """fn(path) on a private copy of `src`, the server pointed at it and removed after, whatever happens."""
    R_ = pathlib.Path(_scratch.mkdtemp(prefix="storedpair-copy-")); real, anc = _core_store.STORE, _anc.FILE
    try:
        shutil.copytree(src, R_ / "store", ignore=shutil.ignore_patterns(".git", "*.tmp", ".*"))
        _core_store.STORE = R_ / "store"; _anc.FILE = R_ / "store/anchors.json"
        return fn(R_ / "store")
    finally:
        _core_store.STORE, _anc.FILE = real, anc
        shutil.rmtree(R_, ignore_errors=True)
def counters(): return _model.UNSTAMPED["count"]
def quietly(fn, *a):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn(*a)


# ---- 1. no switch, no counters of the old reading
src_toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
check("1 [model] read_stored, read_stored(), _read_stored, check_stored, DISAGREEMENTS and STALE_AT_EDGE are gone from model.py", not any(hasattr(_model, n) for n in ("read_stored", "_read_stored", "check_stored", "DISAGREEMENTS", "STALE_AT_EDGE", "stored_wait_kind")), None)
check("1 …the example config has no read_stored key", "read_stored" not in src_toml, None)
st = server._phase_sweep_status()
check("1 …/audit/status phase_sweep counts unstamped reads and no longer the display's disagreements or stale-at-edge reads", "unstamped_reads" in st and "model_disagreements" not in st and "stale_at_edge" not in st, sorted(st))


# ---- 2. a swept store: the stored pair and the fields give the same output on every surface
def swept_at(src, t, fn):
    """A private copy of `src` swept at the clock t, then fn(store, done, derived, items, opens) where derived = {gid: the pair the fields give at t}."""
    def go(store):
        with contextlib.redirect_stderr(io.StringIO()), frozen(t): done = server._phase_sweep()
        items = SP.load_dir(store); opens = [g for g, it in items.items() if it.get("status") == "open"]
        with frozen(t): derived = {g: server._stamp_values(g, items[g]) for g in opens}
        return fn(store, done, derived, items, opens)
    return with_store(src, go)
def stored_equals_derived(items, derived, opens): return all((items[g]["metadata"].get("phase") or "", items[g]["metadata"].get("waits_on") or "") == derived[g] for g in opens)
def both(store, t):
    """(the surfaces read from the stored pair, the surfaces read from the fields alone, the unstamped reads the first counted)."""
    u0 = counters(); a = quietly(surfaces, store, t, True); u1 = counters(); b = quietly(surfaces, store, t, False)
    return a, b, u1 - u0
def at_now(store, done, derived, items, opens):
    a, b, unstamped = both(store, T0)
    return a, b, unstamped, done, stored_equals_derived(items, derived, opens)
SA, SB, unst, done, ok = swept_at(STORE, T0, at_now)
check("2 after a sweep at the clock now every open item stores the pair the fields give now (the wrong ones g43 to g50 included)", ok and {"g43", "g44", "g45", "g46", "g47", "g48", "g49", "g50"} <= set(done), done)
check(f"2 {len(SA)} surfaces over {len([k for k in SA if k.startswith('display ')])} open items: the stored pair and the fields alone are byte-equal on every one", not differ(SA, SB), differ(SA, SB)[:6])
check("2 …and reading a swept store counts no unstamped read", unst == 0, unst)
def counts_swept(src, t, on): return swept_at(src, t, lambda store, *_r: counts(store, t, on))
(cc0, ww0), (cc1, ww1) = counts_swept(STORE, T0, False), counts_swept(STORE, T0, True)
check("2 …the counts by (phase, kind) and the watched map are equal", cc0 == cc1 and ww0 == ww1 and len(cc1) >= 4, (cc0, cc1))
H0 = hashes(STORE)
quietly(surfaces, STORE, T0, True)
check("2 …reading writes nothing (store bytes equal)", hashes(STORE) == H0, None)


# ---- 3. the stored pair decides, even where the fields disagree; a missing or half-stored pair is read from the fields and counted; one sweep restamps them all
def one_read(g, stored, t=T0):
    """(list word, unstamped reads counted, the shown (phase, kind)) for one read of item g at clock t, the decision from the stored pair (stored) or the fields alone."""
    with frozen(t), reading(stored):
        u0 = counters(); it = _service_store._load(g); w = quietly(server._item_list, it); u1 = counters()
        m = _model.view(dict(it, gid=g), server._model_of(dict(it, gid=g)), t, lambda i_: server._after_open(i_.get("metadata") or {}), check=True)
    return w, u1 - u0, _model.shown_pair(m)
W = {g: (one_read(g, True), one_read(g, False)) for g in ("g43", "g44", "g45", "g46", "g47", "g48", "g49", "g50")}
for g, what, stored_word, field_word in (("g43", "a plain doing item stored waiting on a time", "waiting", "agents"), ("g44", "a relay wait stored alive", "agents", "waiting"),
                                         ("g48", "a held doing item stored alive", "agents", "waiting"), ("g49", "an item of his stored waiting on a time", "waiting", None),
                                         ("g50", "a doing item stored waiting on an item whose links have closed", "waiting", "agents")):
    (ws, us, ps), (wf, uf, pf) = W[g]
    check(f"3 {what} ({g}): the stored pair decides ({stored_word}), the fields alone give another reading, and nothing is counted", ws == stored_word and (field_word is None or wf == field_word) and us == 0 and ps != pf, W[g])
(ws, us, ps), (wf, uf, pf) = W["g46"]
check("3 a relay wait stored with the wrong kind (g46, waits_on time): the stored kind is the one shown", ps == ("waiting", "time") and pf == ("waiting", "relay") and us == 0, W["g46"])
for g, what in (("g45", "a phase waiting with no waits_on"), ("g47", "values that are not a phase")):
    (ws, us, ps), (wf, uf, pf) = W[g]
    check(f"3 {what} ({g}) is read as the writer would store it and counted as an unstamped read", ws == wf and ps == pf and us == 1, W[g])
ws, us, ps = one_read("g42", True)
check("3 an item never stamped (g42, held with a far wake) is read as the writer would store it, waiting on a time, and counted", ps == ("waiting", "time") and us == 1, (ws, us, ps))
def restamp(store, done, derived, items, opens):
    a, b, unstamped = both(store, T0)
    return done, stored_equals_derived(items, derived, opens), differ(a, b), unstamped
done3, ok3, bad3, unst3 = swept_at(STORE, T0, restamp)
check("3 one sweep restamps all of them to the fields' reading: the surfaces equal the fields' and no read is unstamped", ok3 and not bad3 and unst3 == 0 and {"g42", "g43", "g44", "g45", "g46", "g47", "g48", "g49", "g50"} <= set(done3), (done3, bad3[:4], unst3))


def anchored_pair(store, t):
    with frozen(t):
        ub = ui_render.Board(str(store), now=dt.datetime.fromtimestamp(t, ZONE)); items = SP.load_dir(store); rows = []
        for g, it in sorted(items.items()):
            if it.get("status") != "open" or (it.get("metadata") or {}).get("wait_kind") or (it.get("metadata") or {}).get("state") != "outside": continue
            r = next(r for r in ub.rows if r["gid"] == g)
            rows.append((g, ub.mod_of(r).wait.kind, server._model_of(dict(it, gid=g)).wait.kind, _model.stored_waits_on(it)))
        return rows


# ---- 4. time travel: the same store at six later clocks
nxt_mid = midnight(day_of(T0 + 60) + dt.timedelta(days=1)) + 60
SHIFTS = (("+30 min", T0 + 1800), ("+1 h", T0 + H), ("+6 h", T0 + 6 * H), ("next ZONE midnight", nxt_mid), ("+3 days", T0 + 3 * DAY), ("+40 days", T0 + 40 * DAY))
def shift_proof(label, src, shifts):
    """Each clock: with a sweep at the clock the stored pair and the fields give the same output on every surface and every pair stored is the one the fields give; without a sweep reading writes nothing."""
    for name, t in shifts:
        def go(store, done, derived, items, opens, t=t):
            a, b, unstamped = both(store, t)
            return done, stored_equals_derived(items, derived, opens), differ(a, b), unstamped
        done_, ok_, bad_, unst_ = swept_at(src, t, go)
        check(f"4 {label} {name}, swept: every open item stores the pair the fields give at that clock, and the stored pair and the fields are byte-equal on every surface ({len(done_)} restamped)", ok_ and not bad_ and unst_ == 0, (ok_, bad_[:5], unst_))
        def nosweep(store, t=t):
            h0 = hashes(store); quietly(surfaces, store, t, True)
            return hashes(store) == h0
        check(f"4 {label} {name}, no sweep: reading the stored pairs writes nothing", with_store(src, nosweep), None)
shift_proof("fixture", STORE, SHIFTS)
# a pair the clock has outdated decides until the sweep restamps it (at most a minute): g1 is held with a wake 3 h out, stamped waiting; 6 h on the fields say alive
w_old, _u, p_old = one_read("g1", True, T0 + 6 * H); w_fld, _u2, p_fld = one_read("g1", False, T0 + 6 * H)
check("4 a dated wait the clock has outdated (g1, six hours on) lists as waiting on its stored pair until the sweep, and as the fields give it (agents) after it", w_old == "waiting" and p_old == ("waiting", "time") and w_fld == "agents" and p_fld == ("alive", ""), (w_old, p_old, w_fld, p_fld))
def after_sweep(store, done, derived, items, opens):
    with frozen(T0 + 6 * H): return quietly(server._item_list, _service_store._load("g1")), "g1" in done
check("4 …and one sweep at that clock stamps it alive", swept_at(STORE, T0 + 6 * H, after_sweep) == ("agents", True), None)
src = pathlib.Path(os.environ.get("PHASE_REPLAY_STORE") or "/nonexistent").expanduser()
if src.is_dir() and any(q.is_dir() and len(q.name) == 1 for q in src.iterdir()):
    shift_proof("live copy", src, tuple((n, time.time() + (t - T0)) for n, t in SHIFTS[:3]) + tuple((n, t - T0 + time.time()) for n, t in SHIFTS[3:]))
    live_items = SP.load_dir(src); n_open = sum(1 for it in live_items.values() if it.get("status") == "open")
    print(f"live copy: {n_open} open items read at six later clocks, swept, the stored pair against the fields")
else:
    print("replay: skipped (PHASE_REPLAY_STORE names no store here)")

# ---- 5. anchored: the item page's reading and the server's agree, for each outside item with no wait_kind
rows = anchored_pair(STORE, T0)
check("5 each outside item with no wait_kind is read as the same kind by the home page, the server and the stored pair (g52 an anchor, the others relays)",
      rows and all(a == b == c for _g, a, b, c in rows) and dict((g, a) for g, a, *_ in rows).get("g52") == "anchor", rows)

# ---- 6. mutations: the checks above must fail for a reader that is wrong
real_view = _model.view
def fields_reader(item, mod, now=None, after_open=None, check=True):
    """A reader that works the decision out from the fields and ignores the stored pair (the old reading)."""
    return _model._shown(item, mod, now, after_open)
def kindless(item, mod, now=None, after_open=None, check=True):
    """A reader that takes the stored waiting but the fields' kind."""
    out = real_view(item, mod, now, after_open, check)
    if check and out.state == _model.WAITING and out.wait is not None:
        f = _model._shown(item, mod, now, after_open)
        if f.state == _model.WAITING and f.wait is not None:
            return f
    return out
_model.view = fields_reader
try:
    wm = {g: one_read(g, True)[0] for g in ("g43", "g44", "g48", "g50")}
finally:
    _model.view = real_view
check("6 mutation: a reader that works the decision out from the fields is caught (g43, g44, g48 and g50 list as the fields give them)", wm == {"g43": "agents", "g44": "waiting", "g48": "waiting", "g50": "agents"} and wm != {g: W[g][0][0] for g in wm}, wm)
_model.view = kindless
try:
    pk = one_read("g46", True)[2]
finally:
    _model.view = real_view
check("6 mutation: a reader that takes the stored waiting but the fields' kind is caught (g46 shows relay, not time)", pk == ("waiting", "relay") and one_read("g46", True)[2] == ("waiting", "time"), pk)

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: stored_pair scenario, {len(ran)} checks")
