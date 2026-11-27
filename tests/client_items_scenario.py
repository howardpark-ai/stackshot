"""Scenario test for `items?key=<session>` of the client API: every live session asks for its list about once a minute, and one answer used to scan the whole board — fixture data, no live store, no network.

Covers: a board of 150 open items and a closed history in 6 projects and 24 sessions (Korean text; closed, held, parked, after, needs and default-mover items) read for every session through the old per-read path and the
shared view, which return the same text for every key (a name, a transcript id, an alias, a cse_ id, an unknown one); 24 reads do one scan (item files opened, one pass) and 24 more open nothing; readers that arrive together
share one scan; every kind of write between two reads shows in the next read (an item changed in place at the same size, replaced, held, woken, closed, added, removed; the project registry, a session's name, the session
registry, anchors, the config object), a clock past the view's age rebuilds, a file written in the last 200 ms is never kept (a store, fleet or registry file), the answers kept per view are bounded, and the route runs the read off the event loop.
Also: a registry write inside the registry's own one-second look is read as the per-read path reads it, then at the next look; a store reached through a symlinked item file and a symlinked letter folder is stamped by its target; a write
that lands during a scan is seen at the next read; readers of one view build each row once; a session that is a mover only by an alias; and the answers that move with the clock alone (a wait basis, a hold's wake, a dated wait,
the day's end, a session leaving the fleet's grace, a registry file that stops being stood in for, a mover's second item quiet for an hour) are the per-read path's a few seconds past the moment they change; the first four also half a minute and hours past it.
The clock the reads go through stands still until the suite moves it, and the mtime of a file that counts as just written is set against that clock: no answer depends on how fast the run is.

    tests/run-suite client_items        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging, time, threading, datetime as dt, collections
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="clientitems-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml, n = re.subn(r'(?m)^session_links = ""', f'session_links = "{tmp}/links"', toml); assert n == 1      # a session registry beside the fleet tool's store, as the live instance has
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^queued_behind = false", "queued_behind = true", toml); assert n == 1      # the live instance reads the queue: a mover busy on another item
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "links/a", "brain/projects"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
PROJECTS = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
SESS = {}                                                   # name -> transcript id: per project a main, a builder and two more agents
for pi, pn in enumerate(PROJECTS):
    for ri, role in enumerate(("main", "builder", "front", "other")):
        SESS[f"{pn}-{role}"] = f"{pi:04d}0000-{ri:04d}-4000-8000-000000000001"
NAMES = list(SESS)
def write_sessions(newbie=False):
    rows = {u: {"name": n, "machine": "a"} for n, u in SESS.items()}
    if newbie: rows["77770000-0000-4000-8000-000000000001"] = {"name": "newbie-1", "machine": "a"}
    for n in range(40): rows[f"9999{n:04d}-0000-4000-8000-000000000001"] = {"name": f"gone-{n}", "machine": "a", "gone": "2026-01-01T00:00:00Z"}
    (T / "fleet/a/sessions.json").write_text(json.dumps(rows))
def write_registry(alias=None):
    (T / "links/a/session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-11-20T00:00:00Z", "sessions": {u: {
        "id": u, "name": n, "aliases": ([alias[1]] if alias and alias[0] == n else []), "project": "", "state": "live", "created": "2026-11-01T00:00:00Z",
        "transcripts": [{"id": u, "machine": "a", "at": "2026-11-01T00:00:00Z", "why": "start"}]} for n, u in SESS.items()}}))
def page(pn, **over):
    return {"title": pn.title(), "name": pn.title(), "org": "home", "tags": [], "type": "project", "session": f"{pn}-main", "status": "active", "board": [], "board_open": 0,
            "agents": {f"{pn}-main": "the main", f"{pn}-builder": "the builder", f"{pn}-front": "a front", f"{pn}-other": "another"}, "back_agents": {f"{pn}-builder": "the builder"}, **over}
def write_pages(**over):
    pages = {f"projects/{pn}": page(pn, **over.get(pn, {})) for pn in PROJECTS}
    for n in range(40): pages[f"projects/extra{n}"] = page(f"extra{n}", summary="s" * 400)
    (T / "store/projects.json").write_text(json.dumps({"pages": pages}))
write_sessions(); write_registry(); write_pages()
for pn in PROJECTS: (T / f"brain/projects/{pn}.md").write_text(f"---\ntitle: {pn.title()}\ndisplay-name: {pn}-main\nagents:\n  {pn}-main: the main\n  {pn}-front: a front\n  {pn}-other: another\n  background:\n    {pn}-builder: the builder\n---\n\n# {pn.title()}\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
now0 = time.time(); DAY = 86400.0
def D(n): return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=n)).strftime("%Y-%m-%d")
def put(i, status="open", subject=None, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": status,
        "updated": now0 - 3 * DAY, "state_updated": now0 - 3 * DAY, "confirmed": now0 - 3 * DAY, "metadata": {"project": meta.pop("project", "projects/alpha"), **meta}}, ensure_ascii=False))
KO = ("\ud55c\uae00 \uc81c\ubaa9 \ud56d\ubaa9", "\uc774\uc5b4\uc11c \uc791\uc5c5: \ub2e4\uc74c \ub2e8\uacc4\ub294 \uac80\ud1a0", "\ubcf4\ub958\ub41c \uc77c\uc815", "\uacb0\uc815\uc774 \ud544\uc694\ud55c \uc548\uac74")
N_OPEN = 150
for i in range(1, N_OPEN + 1):
    pn = PROJECTS[i % len(PROJECTS)]; prj = f"projects/{pn}"
    a, b = NAMES[(i * 7) % len(NAMES)], NAMES[(i * 11 + 3) % len(NAMES)]
    owner = [SESS[a], a, "cse_e1"][i % 3]; ko = KO[i % len(KO)]; kind = i % 12
    base = dict(project=prj, owner=owner, owner_name=a, next=f"{a}: {ko} {i}")
    if kind == 0: put(i, subject=f"[home] {ko} {i}", project=prj, owner=owner, owner_name=a)                           # no stored mover: the project's default
    elif kind == 1: put(i, subject=f"[home] {ko} {i}", **base, needs=["decision"], then=a)                              # the decision is the person's, and a session takes it after the answer
    elif kind == 2: put(i, subject=f"[home] {ko} {i}", **base, hold=True, mover=a)                                      # held
    elif kind == 3: put(i, subject=f"[home] {ko} {i}", **base, wait_kind="time", wake=D(2 + i % 5), then=b, post_wake_mover=b)       # parked to a date
    elif kind == 4: put(i, **base, mover=a, after=[f"a{i - 1}"])                                                        # after an open item
    elif kind == 5: put(i, **base, mover=a, after=[f"a{i - 5}"])                                                        # after an item that is open too
    elif kind == 6: put(i, status="completed", **base, mover=a)                                                         # closed
    elif kind == 7: put(i, status="on_hold", **base, mover=a)                                                           # the retired status
    elif kind == 8: put(i, subject=f"[home] {ko} {i}", project=prj, owner=owner, owner_name=a)
    elif kind == 9: put(i, **base, needs=[a, b], mover=a)                                                               # two sessions in its needs
    elif kind == 10: put(i, **base, mover=b, then=a)
    else: put(i, **base, needs=["external"], mover=a)
N_FILES = N_OPEN
for j in range(80):                                                                                                      # the closed history
    N_FILES += 1; put(N_OPEN + 1 + j, status="completed", subject=f"[home] \uc885\ub8cc\ub41c \ud56d\ubaa9 {j}", project=f"projects/{PROJECTS[j % 6]}", owner=NAMES[j % 24], next="x" * 200)
(T / "store/next-id").write_text("1000")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
_ticks = [0]
def age(path):
    """A file as an old one: its mtime some seconds back (a distinct time each call), so the view built from it is one that may be kept."""
    _ticks[0] += 1; t = time.time_ns() - 8_000_000_000 - _ticks[0] * 1_000_000
    os.utime(path, ns=(t, t))
def age_all():
    for root in (T / "store", T / "fleet", T / "links"):
        for p in root.rglob("*.json"): age(p)
age_all()

from stackshot.web import server
from stackshot.service import client_reads as cr
from stackshot.service import update as _update_svc
from stackshot.service import wakes as wakes_svc
from stackshot.web import publish as _web_publish
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.core import config as _cfg
from stackshot.core import store as _store
from stackshot.fleet import client
from stackshot.fleet import sessions_registry as _sr
from stackshot.fleet import liveness as _lvt
from stackshot.service import audit_ticks as _aud
from stackshot.web.routes import client_api as _rt_client
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None

# the per-read path as it was: one scan of the whole board for each asking session (the text of the function before the shared view)
OLD_SRC = '''
def old_items(key):
    k = str(key or "").strip()
    if not k or len(k) > 200 or any(c in k for c in "\\r\\n\\t"):
        return 400, "text/plain", "key = the asking session: its transcript uuid, cse_ id or pane name"
    nm = _anc.names()
    me = {k, _anc.canonical(k, nm)}
    me |= {nm.get(x, "") for x in list(me)}
    me.discard("")
    out = []
    now = time.time()
    ctx = _agents._WaitCtx(now)
    for gid, p in _item_files():
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:
            continue
        if not isinstance(it, dict):
            continue
        _legacy_hold(it); _legacy_needs(it); _ip.read_through(it)
        if it.get("status") != "open":
            continue
        m = it.get("metadata") or {}
        linked = any({ag, _anc.canonical(ag, nm)} & me for ag in _needs_sessions(m))
        mv_, alive_ = _item_mover_model(dict(it, gid=gid))
        is_mover = bool(alive_ and mv_ and not _model.is_owner(mv_) and ({mv_, _anc.canonical(mv_, nm)} & me))
        th_ = _then_label_raw(dict(it, gid=gid))
        is_then = bool(th_ and ({th_, _anc.canonical(th_, nm)} & me))
        if not (is_mover or is_then or linked):
            continue
        try:
            su = float(it.get("state_updated") or 0) or None
        except (TypeError, ValueError):
            su = None
        try:
            up = float(it.get("updated") or 0) or None
        except (TypeError, ValueError):
            up = None
        st_, st_derived = _states.of(it, lambda i_: _item_read._after_open(i_.get("metadata") or {}))
        roles = ([_ROLE_MOVER] if is_mover else []) + ([_ROLE_THEN] if is_then else []) + ([_ROLE_NEEDS] if linked else [])
        out.append({"gid": gid, "shown": _gh.shown(gid), "subject": str(it.get("subject") or ""), "needs": _hooks().shown_needs(_needs_of(m)),
                    **({"state": st_, "state_fields": _states.carry_of(it)} if not st_derived else {}),
                    "contact": _contacts._contact_label(dict(it, gid=gid)),
                    "next": str(m.get("next") or ""), "state_updated": su, "confirmed": _hooks().rmod_confirmed_at(it, p),
                    "updated": up, "held": _item_read._is_parked(it) or bool(_item_read._after_open(m)) or _basis_wait_of(dict(it, gid=gid)), "list": _item_list(dict(it, gid=gid)), **_wait_fields(gid, it, ctx),
                    "scope": _anc.item_scope(m),
                    "roles": roles, **({"role": "agent"} if linked else {})})
    return 200, "application/json", json.dumps({"items": out}, ensure_ascii=False)
'''
_ns = dict(vars(cr)); exec(compile(OLD_SRC, "<the per-read path>", "exec"), _ns); old_items = _ns["old_items"]
def reset(): cr._VIEW["v"] = None
def get_all(keys): return {k: cr._client_items(k) for k in keys}
def old_all(keys): return {k: old_items(k) for k in keys}
NEWBIE = "newbie-1"; NEWBIE_ID = "77770000-0000-4000-8000-000000000001"            # a session the heartbeat will know and the registry never does
put(903, subject="[home] \uc0c8 \uc138\uc158\uc758 \ud56d\ubaa9", project="projects/alpha", owner=NEWBIE, owner_name=NEWBIE, mover=NEWBIE, next=f"{NEWBIE}: go"); age(T / "store/a/903.json")
for i, pn in ((904, "alpha"), (905, "beta"), (906, "gamma"), (907, "delta")): put(i, subject=f"[home] \ud3c9\ubc94\ud55c \ud56d\ubaa9 {i}", project=f"projects/{pn}", owner=f"{pn}-main", owner_name=f"{pn}-main", mover=f"{pn}-front", next=f"{pn}-front: go"); age(T / f"store/a/{i}.json")
put(908, subject="[home] \ubcc4\uba85\uc73c\ub85c \ubd88\ub9ac\ub294 \uc138\uc158\uc758 \ud56d\ubaa9", project="projects/alpha", owner="alpha-main", owner_name="alpha-main", mover="alpha-old", next="alpha-old: go"); age(T / "store/a/908.json")      # its mover is a name that is an alias of alpha-main only once the registry says so
KEYS = NAMES + [SESS[n] for n in NAMES[::5]] + ["cse_e1", "nobody-at-all", "alpha-old", NEWBIE, NEWBIE_ID]

opens = []; counting = [False]
def _hook(ev, args):
    if counting[0] and ev == "open" and isinstance(args[0], (str, bytes)):
        p = os.fsdecode(args[0])
        if re.search(r"/store/[a-z]/\d+\.json$", p): opens.append(p)
sys.addaudithook(_hook)
def count(fn):
    opens.clear(); counting[0] = True
    try: r = fn()
    finally: counting[0] = False
    return r, len(opens)

# ---- the clock: from here to the route's checks `time.time`, `time.time_ns` and `time.monotonic` stand still until the suite moves them, so a view's age, a file's age and the moments a date comes are what a check
# says they are, however long the reads take (a traced run is several times slower than a plain one)
_real_clocks = time.time, time.time_ns, time.monotonic
CLOCK = {"wall_ns": time.time_ns(), "mono": time.monotonic()}
def at_clock(t): CLOCK["wall_ns"] = int(t * 1e9)                                  # the wall clock alone jumps to `t`
def pass_time(s): CLOCK["wall_ns"] += int(s * 1e9); CLOCK["mono"] += s            # `s` seconds pass on both clocks
time.time, time.time_ns, time.monotonic = (lambda: CLOCK["wall_ns"] / 1e9), (lambda: CLOCK["wall_ns"]), (lambda: CLOCK["mono"])
JUST_NOW_NS = 199_000_000                                                         # the age of a file "just written": inside the 200 ms in which a view built from it is not kept
def just_written(path):
    """Give a file the mtime of a write `JUST_NOW_NS` before the clock; returns that mtime."""
    t = time.time_ns() - JUST_NOW_NS; os.utime(path, ns=(t, t)); return t
def newest(): return cr._board_stamp()[1]                                          # the newest mtime of what the view stands on
age_all(); _sr.reset(); _aud._QUEUE_CACHE.update(at=0.0, map={})                   # nothing the start wrote, or read by the real clock, counts as fresh

# ---- 1. the same answers as the per-read path, for every key
reset()
new1, n_cold = count(lambda: get_all(KEYS)); old1 = old_all(KEYS)
check("the shared view returns the per-read path's text for every key: 24 session names, 5 transcript ids, a cse_ id, an unknown name and an alias that is not one yet", new1 == old1, [k for k in KEYS if new1[k] != old1[k]])
rows = {k: json.loads(v[2])["items"] for k, v in new1.items()}
allrows = [r for v in rows.values() for r in v]
check("the board is a varied one: most sessions list something, Korean subjects, held and not held", sum(bool(rows[n]) for n in NAMES) >= 18 and any("\ud55c\uae00" in r["subject"] for r in allrows) and {r["held"] for r in allrows} == {True, False},
      (sum(bool(rows[n]) for n in NAMES), {r["held"] for r in allrows}))
check("…the three lists, each role, an item named in needs and one a person moves", {r["list"] for r in allrows} == {"your-move", "agents", "waiting"} and {x for r in allrows for x in r["roles"]} == {"mover", "then", "needs"}
      and any(r.get("role") == "agent" for r in allrows) and any(r["mover"]["kind"] != "session" for r in allrows), (collections.Counter(r["list"] for r in allrows), collections.Counter(x for r in allrows for x in r["roles"]), {r["mover"]["kind"] for r in allrows}))
check("the rows are the items of one board: a closed item and a held-by-status item are never a key's row except as held, and the closed one not at all", not any(r["gid"] in ("a6", "a18") for r in allrows) and not any(r["subject"].startswith("[home] \uc885\ub8cc") for r in allrows))
check("an unknown key and a bad key: the empty list, 400", json.loads(new1["nobody-at-all"][2]) == {"items": []} and cr._client_items("")[0] == 400 and cr._client_items("a\nb")[0] == 400 and cr._client_items("x" * 201)[0] == 400)

# ---- 2. one scan for the reads of a minute
reset()
_, n_a = count(lambda: get_all(NAMES))
check(f"24 reads of one board open each item file about once, not once per read: {n_a} opens for {N_FILES} files", n_a <= 3 * N_FILES, n_a)
pass_time(20)                                  # 20 s of the view's 30 pass: it is served at that age, not at the age it was built
_, n_b = count(lambda: get_all(NAMES))
check("…and 24 more reads of the unchanged board open no item file", n_b == 0, n_b)
check("…the answers of the second round are the first round's", get_all(NAMES) == {k: new1[k] for k in NAMES})
reset()
_, n_old = count(lambda: old_all(NAMES))
check("the per-read path opens every item file at each read (what the view saves)", n_old >= 24 * N_FILES, n_old)

# ---- 3. readers that arrive together share one scan
reset(); res = {}; errs = []
def reader(k):
    try: res[k] = cr._client_items(k)
    except Exception as e: errs.append(repr(e))
ths = [threading.Thread(target=reader, args=(k,)) for k in NAMES]
def burst():
    for t in ths: t.start()
    for t in ths: t.join()
_, n_c = count(burst)
check(f"24 readers at once against a cold view: one scan ({n_c} opens), no error, each the answer the sequential read gave", n_c <= 3 * N_FILES and not errs and res == {k: new1[k] for k in NAMES}, (n_c, errs[:2]))

# ---- 4. every kind of write between two reads shows in the next read
def settle():
    age_all(); _sr.reset(); reset(); get_all(NAMES)           # the board as a view that may be kept, and kept (the registry looks at its directory again: the files above have new times)
def item_path(i): return T / f"store/a/{i}.json"
def jload(i): return json.loads(item_path(i).read_text(encoding="utf-8"))
def stale_case(name, write, *, same=False, expect_change=True):
    settle()
    before = get_all(KEYS)
    _, n_hit = count(lambda: get_all(KEYS))
    write()
    after, n_after = count(lambda: get_all(KEYS))
    oracle = old_all(KEYS)
    check(f"after {name}: the next read is the per-read path's, for every key", after == oracle, [k for k in KEYS if after[k] != oracle[k]][:3])
    if expect_change:
        check(f"after {name}: it is not the answer before (the write was seen)", after != before, None)
    check(f"before {name}: the reads were served from the kept view (no file opened)", n_hit == 0, n_hit)
    return before, after
i_front = 904
def w_same_size():
    d = jload(i_front); d["metadata"]["mover"] = d["metadata"]["mover"].replace("-front", "-other"); item_path(i_front).write_text(json.dumps(d, ensure_ascii=False)); age(item_path(i_front))
_sz = item_path(i_front).stat().st_size
b_, a_ = stale_case("an item changed in place to another mover, same size (only its mtime moved)", w_same_size)
check("…the file's size is what it was: the stamp tells by the mtime", item_path(i_front).stat().st_size == _sz, (_sz, item_path(i_front).stat().st_size))
def w_size_only():            # another size, the mtime put back to what it was: only the size tells
    m = item_path(906).stat().st_mtime_ns; sz = item_path(906).stat().st_size; d = jload(906); d["metadata"]["mover"] = "gamma-builder"; item_path(906).write_text(json.dumps(d, ensure_ascii=False)); os.utime(item_path(906), ns=(m, m))
    st = item_path(906).stat(); assert st.st_mtime_ns == m and st.st_size != sz, (st.st_mtime_ns == m, st.st_size, sz)
stale_case("an item rewritten at another size with its mtime put back (only the size moved)", w_size_only)
def w_inode_only():           # the same size and the same mtime in a new file moved over the old one: only the inode tells
    m = item_path(907).stat().st_mtime_ns; sz = item_path(907).stat().st_size; ino = item_path(907).stat().st_ino
    d = jload(907); d["metadata"]["mover"] = "delta-other"; tmp = T / "store/a/.swap"; tmp.write_text(json.dumps(d, ensure_ascii=False)); os.utime(tmp, ns=(m, m)); os.replace(tmp, item_path(907))
    st = item_path(907).stat(); assert st.st_mtime_ns == m and st.st_size == sz and st.st_ino != ino, (st.st_mtime_ns == m, st.st_size == sz, st.st_ino != ino)
stale_case("an item replaced by a new file of the same size and mtime (only the inode moved)", w_inode_only)
def w_replace():
    d = jload(i_front); d["metadata"]["mover"] = "beta-main"; d["metadata"]["next"] = "beta-main: \uc0c8\ub85c\uc6b4 \ub2e8\uacc4 " * 3; _store._write_item(item_path(i_front), d); age(item_path(i_front))
stale_case("an item replaced by a new file (another mover, a longer next)", w_replace)
held_i = next(i for i in range(1, N_OPEN + 1) if i % 12 == 10)
def w_hold():
    mover = jload(held_i)["metadata"]["mover"]
    _update_svc._update(f"a{held_i}", hold=True, recycle=True, sender=mover); age(item_path(held_i))
stale_case("a hold set through the update", w_hold)
wake_i = 901
def put_wake(): put(wake_i, subject="[home] \uae68\uc6b8 \ud56d\ubaa9", project="projects/alpha", owner="alpha-main", owner_name="alpha-main", mover="alpha-main", hold=True, wake=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).strftime("%Y-%m-%d"), next="alpha-main: wake"); age(item_path(wake_i))
put_wake()
def w_wake(): wakes_svc.wake_pass(); age(item_path(wake_i))
held_before = {r["gid"]: r["held"] for r in json.loads(cr._client_items("alpha-main")[2])["items"]}
b_, a_ = stale_case("the wake pass released a hold whose date had come", w_wake)
held_after = {r["gid"]: r["held"] for r in json.loads(a_["alpha-main"][2])["items"]}
check("…the woken item was held before and is not now", held_before.get(f"a{wake_i}") is True and held_after.get(f"a{wake_i}") is False, (held_before.get(f"a{wake_i}"), held_after.get(f"a{wake_i}")))
close_i = next(i for i in range(1, N_OPEN + 1) if i % 12 == 10 and i != held_i)
def w_close():
    d = jload(close_i); d["status"] = "completed"; _store._write_item(item_path(close_i), d); age(item_path(close_i))
stale_case("an item closed", w_close)
def w_new():
    put(902, subject="[home] \uc0c8 \ud56d\ubaa9", project="projects/beta", owner="beta-main", owner_name="beta-main", mover="beta-main", next="beta-main: new"); age(item_path(902))
stale_case("an item added", w_new)
def w_remove():
    item_path(902).unlink()
stale_case("an item file removed", w_remove)
def w_page():
    write_pages(alpha={"back_agents": {"alpha-other": "the other"}}); age(T / "store/projects.json")
stale_case("the project registry changed (the builder of a project is another session, so the default mover of its items)", w_page)
def w_names():
    write_sessions(newbie=True); age(T / "fleet/a/sessions.json")
b_, a_ = stale_case("a session came up in the fleet's sessions file (its name now resolves)", w_names)
check("…the session asks for the item that names it", json.loads(b_[NEWBIE_ID][2])["items"] == [] and [r["gid"] for r in json.loads(a_[NEWBIE_ID][2])["items"]] == ["a903"], (b_[NEWBIE_ID][2][:100], a_[NEWBIE_ID][2][:100]))
write_sessions(); age(T / "fleet/a/sessions.json")
def w_registry():
    write_registry(alias=("alpha-main", "alpha-old")); age(T / "links/a/session-registry.json"); _sr.reset()      # the registry's own look at its directory is trusted for a second
b_, a_ = stale_case("the session registry gave a session an alias", w_registry)
check("…the alias asks for the session's list", json.loads(a_["alpha-old"][2])["items"] == json.loads(a_["alpha-main"][2])["items"] and json.loads(a_["alpha-old"][2])["items"] != [], a_["alpha-old"][2][:200])
def gids(r, k): return [x["gid"] for x in json.loads(r[k][2])["items"]]
check("…and an item whose mover is stored under the alias is the session's own from then on (the mover's identity is the registry's, not the raw name)", "a908" in gids(a_, "alpha-main") and "a908" not in gids(b_, "alpha-main"), (gids(b_, "alpha-main")[-3:], gids(a_, "alpha-main")[-3:]))
write_registry(); age(T / "links/a/session-registry.json"); _sr.reset()
def w_anchor():
    (T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": "https://github.com/example-org/stackshot/pull/9", "items": ["a12", "a24", "a36"], "added": time.time(), "by": "alpha-main"}]})); age(T / "store/anchors.json")
stale_case("the anchors changed (an item now waits on one)", w_anchor, expect_change=False)
(T / "store/anchors.json").write_text("{}"); age(T / "store/anchors.json")
def w_cfg():
    c = dict(_cfg.CFG); c["items_api"] = {**(c.get("items_api") or {}), "owner_mover_kind": "owner"}; _cfg.CFG = c
_cfg_was = _cfg.CFG
stale_case("the config was reloaded (the word a person's move carries)", w_cfg)
_cfg.CFG = _cfg_was
settle()
v0 = cr._VIEW["v"]; v0.at -= cr._VIEW_TTL + 1
_, n_ttl = count(lambda: get_all(NAMES))
check("a view older than its age bound is built again, though no file moved", v0 is not None and n_ttl > 0, n_ttl)
settle(); cr._VIEW["v"].at += 3600
_, n_fut = count(lambda: get_all(NAMES))
check("…and a view stamped in the future (a clock that went back) is built again", n_fut > 0, n_fut)

# ---- 5. a file written a moment ago is never kept
reset()
i5 = 905; d = jload(i5); mv = d["metadata"]["mover"]
swap = lambda m: m.replace("-front", "-other") if m.endswith("-front") else m.replace("-other", "-front")
item_path(i5).write_text(json.dumps(d, ensure_ascii=False)); t0 = just_written(item_path(i5)); ino0 = item_path(i5).stat().st_ino
fresh5 = newest() == t0
r1 = get_all(KEYS[:1] + ["beta-front", "beta-other"])      # inside the window
d["metadata"]["mover"] = swap(mv); item_path(i5).write_text(json.dumps(d, ensure_ascii=False)); os.utime(item_path(i5), ns=(t0, t0))      # the same size, the same inode and the same mtime as at the read before
st5 = item_path(i5).stat()
r2 = get_all(KEYS[:1] + ["beta-front", "beta-other"])
check("a file read within 200 ms of its write is rewritten at the same size, inode and mtime: the next read sees it (a view built from a fresh file is not kept)",
      fresh5 and st5.st_mtime_ns == t0 and st5.st_ino == ino0 and r2 == old_all(KEYS[:1] + ["beta-front", "beta-other"]) and r1 != r2, (fresh5, st5.st_mtime_ns == t0, r1 != r2, mv, swap(mv)))
check("…while a view of files older than that is kept", (settle(), pass_time(1), count(lambda: get_all(NAMES))[1])[2] == 0)

# ---- 5b. a registry write inside the registry's own look at its directory
reg_f = T / "links/a/session-registry.json"
TRIO = ["alpha-main", "alpha-old", "beta-main"]
def write_inside_window():
    """The alias written while the session registry still trusts its last look at its directory (a second), and read 0.35 s later without a reset: (that read, the per-read path's, whether both were inside the second, when the registry last looked)."""
    settle(); _sr.reset(); _sr.load(); t0 = time.monotonic()
    write_registry(alias=("alpha-main", "alpha-old")); age(reg_f)
    pass_time(0.35)
    got = get_all(TRIO); orc = old_all(TRIO)
    return got, orc, t0, time.monotonic() - t0 < 0.9
got_in, orc_in, t_look, inside = write_inside_window()
check("a registry write inside the registry's own one-second look: the read 0.35 s later is the per-read path's (the alias not seen yet, by either), not the view of a registry newer than the lookups read", inside and got_in == orc_in and "a908" not in gids(got_in, "alpha-main"), (inside, [k for k in TRIO if got_in[k] != orc_in[k]][:3]))
pass_time(1.1 - (time.monotonic() - t_look))
got_out = get_all(KEYS); orc_out = old_all(KEYS)
check("…and at the registry's next look the next read is the per-read path's with the write seen (the alias is the session's, its item is listed), not the view of the old registry kept to its age bound", got_out == orc_out and got_out[TRIO[0]] != got_in[TRIO[0]] and "a908" in gids(got_out, "alpha-main") and gids(got_out, "alpha-old") == gids(got_out, "alpha-main"), ([k for k in KEYS if got_out[k] != orc_out[k]][:3], got_out[TRIO[0]] == got_in[TRIO[0]]))
write_registry(); age(reg_f); _sr.reset(); settle()

# ---- 5c. a fleet file or a registry file written a moment ago is never kept either
settle(); _sr.reset(); t_ = just_written(reg_f); cr._client_items("alpha-main")      # one read, inside the window
check("a view built while a session registry file is a moment old is not kept", newest() == t_ and cr._VIEW["v"] is None, (newest(), t_, cr._VIEW["v"]))
settle(); t_ = just_written(T / "fleet/a/machine.json"); cr._client_items("alpha-main")
check("…nor while a fleet file is", newest() == t_ and cr._VIEW["v"] is None, (newest(), t_, cr._VIEW["v"]))
settle(); fl = T / "fleet/a/sessions.json"
write_sessions(newbie=True); just_written(fl); st_a = fl.stat(); reset()
fresh_fl = newest() == st_a.st_mtime_ns
r_a = get_all([NEWBIE_ID, "alpha-main"])      # inside the window of the fleet file's write
d_ = json.loads(fl.read_text()); d_[NEWBIE_ID]["name"] = "newbie-2"; fl.write_text(json.dumps(d_)); os.utime(fl, ns=(st_a.st_mtime_ns, st_a.st_mtime_ns))      # a session renamed in place: the same size, inode and mtime
st_b = fl.stat()
r_b = get_all([NEWBIE_ID, "alpha-main"])
check("a fleet file rewritten in place at the same size, inode and mtime within 200 ms of the read before: the next read sees it", fresh_fl and (st_b.st_mtime_ns, st_b.st_ino, st_b.st_size) == (st_a.st_mtime_ns, st_a.st_ino, st_a.st_size) and r_b == old_all([NEWBIE_ID, "alpha-main"]) and r_a != r_b, (r_a[NEWBIE_ID][2][:80], r_b[NEWBIE_ID][2][:80]))
write_sessions(); age(fl)

# ---- 5d. a store reached through links: an item file that is a symlink, and a letter folder that is
import shutil
(T / "real").mkdir(); (T / "realb").mkdir()
def put_to(path, i, **meta):
    put(i, **meta); src = T / f"store/a/{i}.json"; path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8"); src.unlink(); age(path)
put_to(T / "real/950.json", 950, project="projects/alpha", owner="alpha-main", owner_name="alpha-main", mover="alpha-front", next="alpha-front: go")
os.symlink("../../real/950.json", T / "store/a/950.json")
put_to(T / "realb/960.json", 960, project="projects/beta", owner="beta-main", owner_name="beta-main", mover="beta-front", next="beta-front: go")
os.symlink("../realb", T / "store/b")
def rewrite_to(path, mover):
    d = json.loads(path.read_text(encoding="utf-8")); d["metadata"]["mover"] = mover; _store._write_item(path, d); age(path)
try:
    settle(); lnk0 = get_all(KEYS)
    check("a store with a symlinked item file and a symlinked letter folder: both items are read, as the per-read path reads them", gids(lnk0, "alpha-front").count("a950") == 1 and gids(lnk0, "beta-front").count("b960") == 1 and lnk0 == old_all(KEYS), (gids(lnk0, "alpha-front")[-2:], gids(lnk0, "beta-front")[-2:]))
    rewrite_to(T / "real/950.json", "alpha-other"); lnk1 = get_all(KEYS)
    check("…a symlinked item file whose target is rewritten reads as the target: the next read is the per-read path's with the change seen", lnk1 == old_all(KEYS) and lnk1 != lnk0 and "a950" in gids(lnk1, "alpha-other"), (gids(lnk1, "alpha-other")[-2:]))
    settle(); lnk2 = get_all(KEYS)
    rewrite_to(T / "realb/960.json", "beta-other"); lnk3 = get_all(KEYS)
    check("…and an item file inside a symlinked letter folder rewritten: the next read is the per-read path's with the change seen", lnk3 == old_all(KEYS) and lnk3 != lnk2 and "b960" in gids(lnk3, "beta-other"), (gids(lnk3, "beta-other")[-2:]))
finally:
    os.unlink(T / "store/a/950.json"); os.unlink(T / "store/b"); shutil.rmtree(T / "real"); shutil.rmtree(T / "realb")
settle()

# ---- 5e. readers of one view at once build each row once
settle(); v_ = cr._VIEW["v"]; v_.rows.clear(); v_.bodies.clear()      # a kept view with no row built yet
built = []; _real_row = cr._item_row
def slow_row(*a, **k):
    built.append(a[0]); time.sleep(0.003); return _real_row(*a, **k)
res2 = {}; errs2 = []
def reader2(k):
    try: res2[k] = cr._client_items(k)
    except Exception as e: errs2.append(repr(e))
cr._item_row = slow_row
try:
    ths2 = [threading.Thread(target=reader2, args=(k,)) for k in NAMES for _ in range(2)]
    for t in ths2: t.start()
    for t in ths2: t.join()
finally: cr._item_row = _real_row
check("48 readers of one kept view at once (two per key): each item's row is built once, not once per reader that reaches it, and each answer is the per-read path's", not errs2 and built and len(built) == len(set(built)) and res2 == old_all(NAMES), (len(built), len(set(built)), errs2[:2]))

# ---- 5f. a write that lands during a scan is seen at the next read
settle(); reset()
_real_tl = cr._then_label_raw; injected = []
def tl_inject(item):
    if item.get("gid") == "a907" and not injected:      # an item late in the scan: an earlier item's file is rewritten after the scan has read it
        injected.append(1); d = jload(904); d["metadata"]["mover"] = "gamma-other"; _store._write_item(item_path(904), d); age(item_path(904))
    return _real_tl(item)
cr._then_label_raw = tl_inject
try: r_during = {k: cr._client_items(k) for k in ("beta-main",)}      # the one read that builds the view
finally: cr._then_label_raw = _real_tl
r_next = get_all(KEYS)
check("a file rewritten after the scan read it (an old mtime, a new inode): the view built from that scan is not the board of after the write; the next read is the per-read path's, with the write seen", injected and r_next == old_all(KEYS) and "a904" in gids(r_during, "beta-main") and "a904" in gids(r_next, "gamma-other") and "a904" not in gids(r_next, "beta-main"), (bool(injected), gids(r_during, "beta-main")[-3:], gids(r_next, "gamma-other")[-3:]))
settle()

# ---- 6. the views are bounded in what they keep
settle()
big = {f"key-{n}": cr._client_items(f"key-{n}") for n in range(cr._VIEW_KEYS_MAX + 100)}
check("the answers one view keeps are bounded; a key beyond the bound is answered, not kept", len(cr._VIEW["v"].bodies) <= cr._VIEW_KEYS_MAX and all(v == (200, "application/json", '{"items": []}') for v in big.values()), len(cr._VIEW["v"].bodies))
check("one view is kept, not one per stamp", cr._VIEW["v"] is not None and len(cr._VIEW) == 1)

# ---- 6b. the answers that move with the clock alone: a wait whose end passes, a hold's or a dated wait's wake coming within the hour, a dated step read against today, a session leaving the fleet's grace, a mover's quiet hour
BASE = time.time()
tz_ = _cfg.tz()
def Wm(ep): return dt.datetime.fromtimestamp(ep, tz_).strftime("%Y-%m-%dT%H:%M")
def day_of(ep): return dt.datetime.fromtimestamp(ep, tz_).date()
def midnight_after(ep): return dt.datetime.combine(day_of(ep) + dt.timedelta(days=1), dt.time(), tz_).timestamp()
B = (int(BASE) // 60 + 11) * 60                         # a minute about ten minutes ahead: the end of a wait below (the clock moves there), on a day with hours to spare before its midnight
while not 1 <= dt.datetime.fromtimestamp(B, tz_).hour < 20: B += 3600
C, G, M = B + 1200, B + 2400, midnight_after(B)         # the moments a hold's wake comes within the hour, a session leaves the grace, and the day ends
GHOST_ID = "88880000-0000-4000-8000-000000000001"
def dep(i, **kw): put(i, project=kw.pop("project", "projects/zeta"), owner="zeta-main", owner_name="zeta-main", **kw); age(item_path(i))
dep(930, subject="[home] clock one", mover="zeta-main", wake=Wm(B), wait_basis={"text": "a vendor's reply", "by": "zeta-main", "at": 0, "wake": Wm(B)}, next="zeta-main: carry on")        # a doing item whose wake states its reason: a wait until the wake
dep(931, subject="[home] clock two", mover="zeta-front", hold=True, state="doing", wake=Wm(C + 3600), next="zeta-front: carry on")                                                      # on hold with a wake an hour past C: a wait until it is within the hour of it
dep(932, subject="[home] clock three", mover="zeta-builder", until=Wm(B), next="zeta-builder: later")                                                                                    # a stored until: a wait on its own, no row says its date
dep(933, subject="[home] clock four", mover="zeta-other", wake=Wm(C + 3600), next=f"zeta-other: after {day_of(B) + dt.timedelta(days=2)}")                                              # every open step dated for a later day, the wake an hour past C
dep(934, subject="[home] clock five", mover="beta-front", wait_kind="relay", ask_by=str(day_of(B)), next="beta-front: ask")                                                              # a relay with its ask-by day
dep(935, subject="[home] clock six", mover="epsilon-other", wake=Wm(M + 12 * 3600), next=f"epsilon-other: after {day_of(B) + dt.timedelta(days=1)}")                                     # dated for the next day: a wait until that day starts
dep(936, subject="[home] clock seven", mover=GHOST_ID, next="ghost-1: go")                                                                                                                # a mover stored as the id of a session that is gone and leaves the grace at G
d_ = json.loads((T / "fleet/a/sessions.json").read_text()); d_[GHOST_ID] = {"name": "ghost-1", "machine": "a", "gone": dt.datetime.fromtimestamp(G - _lvt.grace(), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
(T / "fleet/a/sessions.json").write_text(json.dumps(d_)); age(T / "fleet/a/sessions.json")
X = B + 600                                                              # the moment the queue map is read, below
def dep_q(i, at): dep(i, project="projects/beta", subject=f"[home] clock queue {i}", mover="qbot-1", next="qbot-1: carry on", last_activity={"at": at, "kind": "step_done", "what": "step 1 done"})
dep_q(940, X + 25 - 3600); dep_q(941, X - 600)                           # one mover, two items: the first has been quiet for an hour 25 s after X (then it is queued behind the second), the second was active ten minutes before X
DK = KEYS + ["ghost-1", GHOST_ID, "qbot-1", "zeta-main", "zeta-front", "zeta-other", "zeta-builder", "beta-front", "epsilon-other"]
def clock_case(name, edge, pasts=(16, 31, 7200), lead=5):
    for past in pasts:
        at_clock(edge - lead); settle(); get_all(DK); before = old_all(DK)       # the view is built a few seconds before the moment
        at_clock(edge + past)
        got = get_all(DK); orc = old_all(DK)
        check(f"{name}: the clock {past} s past the moment, the read is the per-read path's for every key", got == orc, [k for k in DK if got[k] != orc[k]][:4])
        if past == pasts[0]: check(f"…and the moment is a real one ({name}): some answer is not what it was before it", orc != before, None)
try:
    clock_case("a wait whose reason is stated, at the wake", B)
    clock_case("a hold's and a dated wait's wake coming within the hour", C)
    clock_case("a session leaving the fleet's grace", G)
    for i in range(930, 935): item_path(i).unlink()      # every date of today ends at this moment too (the end of the day is the due instant of each): the day's end is checked on the dated step of the next day alone
    was = {i: item_path(i).read_text(encoding="utf-8") for i in (15, 75, 135)}      # so are the fixture's items that wake tomorrow: moved out for this case, put back after
    for i, t_ in was.items():
        d_ = json.loads(t_); d_["metadata"]["wake"] = str(day_of(B) + dt.timedelta(days=40)); _store._write_item(item_path(i), d_); age(item_path(i))
    try: clock_case("the end of the day", M)
    finally:
        for i, t_ in was.items(): item_path(i).write_text(t_, encoding="utf-8"); age(item_path(i))
    at_clock(X); _aud._QUEUE_CACHE.update(at=0.0, map={}); cr._hooks().queue_map()      # the queue map as it is read at X: nothing queued, kept by its own cache for 30 s
    at_clock(X + 20); settle(); get_all(DK); before_q = old_all(DK)                       # the view is built from that map
    at_clock(X + 35)                                                                       # the map's cache is 35 s old and read again, the view 15 s old: the mover's first item has been quiet for an hour
    got_q = get_all(DK); orc_q = old_all(DK)
    check("a mover's second item quiet for an hour while the view is young: the read is the per-read path's for every key (the queue map the rows read is the map now)", got_q == orc_q, [k for k in DK if got_q[k] != orc_q[k]][:4])
    check("…and the moment is a real one: the item is listed as waiting now, as it was on agent before", orc_q != before_q and any(r["list"] == "waiting" for r in json.loads(orc_q["qbot-1"][2])["items"]), None)
finally:
    at_clock(BASE); _aud._QUEUE_CACHE.update(at=0.0, map={})
for i in (935, 936, 940, 941): item_path(i).unlink()
write_sessions(); age(T / "fleet/a/sessions.json"); settle()

# a registry file that stops reading (torn, mid-rewrite) is stood in for from its last good read for half an hour from its first failed read, then dropped: the view's own bound is that moment
write_registry(alias=("alpha-main", "alpha-old")); age(reg_f); settle()
reg_f.write_text("{torn"); age(reg_f); settle()                  # the first failed read: the alias is still the registry's
stood_in = "a908" in gids(get_all(["alpha-main"]), "alpha-main")
pass_time(1780); settle(); get_all(DK); before_t = old_all(DK)       # the view is built 20 s before the registry stops standing in for the file
pass_time(23)
got_t = get_all(DK); orc_t = old_all(DK)
check("a registry file that does not read: 23 s after a view was built, the registry has stopped standing in for its last good read, and the read is the per-read path's for every key", stood_in and got_t == orc_t, (stood_in, [k for k in DK if got_t[k] != orc_t[k]][:4]))
check("…and the moment is a real one: the alias is the session's before it, not after", "a908" in gids(before_t, "alpha-main") and "a908" not in gids(orc_t, "alpha-main"), (gids(before_t, "alpha-main")[-2:], gids(orc_t, "alpha-main")[-2:]))
write_registry(); age(reg_f); _sr.reset(); settle()
time.time, time.time_ns, time.monotonic = _real_clocks      # the event loop below needs clocks that run

# ---- 7. the route runs the read off the event loop
from starlette.testclient import TestClient
tok = open(client.mint("box-far")).read().strip(); H = {"Authorization": "Bearer " + tok}
seen_threads = []; _real = _rt_client._client_get
def spy(what, params):
    seen_threads.append((what, threading.current_thread().name)); return _real(what, params)
_rt_client._client_get = spy
app = server.mcp.http_app()
try:
    settle()
    with TestClient(app) as c:
        r = c.get("/client/items", params={"key": "alpha-main"}, headers=H)
        r2 = c.get("/client/registry", headers=H)
finally: _rt_client._client_get = _real
check("the route answers items with the same text as the read", r.status_code == 200 and r.text == cr._client_items("alpha-main")[2] and r.headers["cache-control"] == "no-store", r.text[:200])
check("…and runs it in a worker thread, so the pages keep answering during a scan", ("items", ) == tuple(w for w, t in seen_threads if "worker" in t.lower() and w == "items") and r2.status_code == 200, seen_threads)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": client items scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
