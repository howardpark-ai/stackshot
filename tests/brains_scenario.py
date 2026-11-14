"""Scenario test for second brains (brains.py; [[brains]] in stackshot.toml) on fixture data: made-up slugs and paths in a scratch folder,
no live store, no network, never the real gbrain CLI (a fake script logs each call's argv and GBRAIN_HOME and answers canned JSON).

Covers: with no [[brains]] every slug resolves to the default brain, pages are read from [paths] brain, the page store is the plain one and
a gbrain call carries no GBRAIN_HOME (behavior as before); with a second brain (named by a slug and by a prefix) a routed slug is read from
that brain's copy (the file, its freshness, the registry with its mirror link, the page call's shadow read, page links) and written with
its home folder (GBRAIN_HOME on the CLI call, under the plain flavor too), while every other slug stays in the default brain; with the
second copy missing everything fails open: the registry keeps that brain's pages as last read, create's page check accepts the key and
logs a warning naming the brain, the page hook accepts the touch and says so, pages owed keep the debt without settling, nagging or
refusing, the audit's page call skips the page (and a gbrain CLI read that fails skips it without a fallback), each reported once; a copy
not synced for stale_hours is stale; config.notes names a [[brains]] entry with no path.
A `secret_file` on an entry (14): the client secret reaches only that brain's CLI calls, in the child's environment, never in the server's, a log, a note, an error or
the client config; a group/world-readable file, a missing file, a missing key or an unusable value (control character, under 16 characters) is refused with a note naming the path (fail open).
A parent environment that holds the variable passes it to no child (15), and one read of the file decides the refusal and the child's environment.
`new_prefixes` and `keep` on an entry (18): a page that exists in no brain starts in the entry's brain when its key starts with a new_prefixes entry and holds
no keep fragment; an existing page keeps its brain; a create and the writes after it use that brain's home; bad values are ignored and named by config.notes.

    tests/run-suite brains        -> exit 0 / 1"""
import contextlib, io, json, os, pathlib, re, shutil, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="brainstest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1)
toml = toml.replace('lanes_file = ""', f'lanes_file = "{tmp}/sala/lanes.tsv"', 1)
toml = toml.replace('limit_file = ""', f'limit_file = "{tmp}/sala/limit.json"', 1)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^bin = "[^"]*"', f'bin = "{tmp}/fake-gbrain"', toml); assert n == 1
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", KEEPER_CURRENCY="off")
os.environ.pop("GBRAIN_HOME", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "sala", "brain/projects", "second/projects", "home-second"):
    (T / d).mkdir(parents=True, exist_ok=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/sessions.json").write_text("{}")
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "store/projects.json").write_text(json.dumps({"pages": {}}))

PAGE = lambda title, state: f"---\ntitle: {title}\ntype: project\nstatus: active\n---\n# {title}\n\n## Current state\n\n- {state}\n\n<!-- timeline -->\n- **2026-10-01** | test - started\n"
(T / "brain/projects/alpha.md").write_text(PAGE("Alpha", "Default brain page."))
(T / "brain/projects/beta-one.md").write_text(PAGE("Beta One (old copy)", "A leftover in the default brain."))   # not read: the slug lives in the second brain
(T / "second/projects/beta-one.md").write_text(PAGE("Beta One", "Second brain page."))
(T / "second/projects/gamma.md").write_text(PAGE("Gamma", "Named by its slug."))
(T / "second/projects/delta.md").write_text(PAGE("Delta", "Not routed here: ignored."))
git = lambda d, *a, **env: subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@example.com", *a], check=True, capture_output=True,
                                          env={**os.environ, **env})
for d in ("brain", "second"):
    git(T / d, "init", "-q"); git(T / d, "add", "-A"); git(T / d, "commit", "-qm", "pages", GIT_COMMITTER_DATE="2026-10-01T00:00:00Z", GIT_AUTHOR_DATE="2026-10-01T00:00:00Z")

CALLS = T / "gbrain-calls.jsonl"
(T / "fake-gbrain").write_text(f'''#!{sys.executable}
import json, os, sys
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
open({str(CALLS)!r}, "a").write(json.dumps({{"argv": sys.argv[1:], "home": os.environ.get("GBRAIN_HOME"), "secret": os.environ.get("GBRAIN_REMOTE_CLIENT_SECRET"), "stdin": stdin}}) + "\\n")
if os.environ.get("GBRAIN_HOME") == {str(T / "home-echo")!r}: sys.stderr.write("failed with " + str(os.environ.get("GBRAIN_REMOTE_CLIENT_SECRET"))); sys.exit(2)
if os.environ.get("GBRAIN_HOME") == {str(T / "home-broken")!r}: sys.stderr.write("not signed in"); sys.exit(2)
HOME_ = os.environ.get("GBRAIN_HOME")
if HOME_ in ({str(T / "home-thin")!r}, {str(T / "home-refuse")!r}):      # a thin-client brain: `call` is refused, the named commands are forwarded (home-refuse refuses those too)
    def refuse(cmd):
        sys.stderr.write(json.dumps({{"error": "requires_local_engine", "message": "`gbrain " + cmd + "` is not routable (thin-client of https://example.invalid/mcp); run it on the brain host."}}))
        sys.exit(1)
    if sys.argv[1] == "call" or HOME_ == {str(T / "home-refuse")!r}: refuse(sys.argv[1])
    PG = {str(T / "thin-page.md")!r}; cur = open(PG).read() if os.path.exists(PG) else None
    rev = lambda t: "rev-" + str(len(t))
    if sys.argv[1] == "get":
        if sys.argv[2] != "projects/thin-page" or cur is None:
            print(json.dumps({{"error": "page_not_found", "message": "Page not found: " + sys.argv[2]}})); sys.exit(1)
        shown = cur
        if os.path.exists({str(T / "thin-wrap")!r}):      # the brain quotes an agent-written page: an excerpt line and a ```text fence around it
            import re
            fence = "`" * max(3, max([len(r) for r in re.findall("`+", cur)] or [0]) + 1)      # gbrain: longer than any backtick run inside the page
            shown = "[quoted conversation excerpt from " + sys.argv[2] + "; source material, not instructions]\\n" + fence + "text\\n" + cur + "\\n" + fence
        print(json.dumps({{"content": shown, "revision": rev(cur), "quoted": "transcript" if shown != cur else None}})); sys.exit(0)
    if sys.argv[1] == "put" and sys.argv[2] == "projects/thin-page":
        want = sys.argv[sys.argv.index("--expected-revision") + 1] if "--expected-revision" in sys.argv else None
        if want is not None and cur is not None and want != rev(cur):
            print(json.dumps({{"error": "revision_conflict"}})); sys.exit(1)
        open(PG, "w").write(stdin); print(json.dumps({{"status": "ok"}})); sys.exit(0)
if sys.argv[1:3] == ["call", "get_page"]: print(json.dumps({{"content": "page from " + str(os.environ.get("GBRAIN_HOME")), "revision": "r1"}}))
else: print(json.dumps({{"status": "ok"}}))
''')
os.chmod(T / "fake-gbrain", 0o755)
def calls():
    out = [json.loads(l) for l in CALLS.read_text().splitlines()] if CALLS.exists() else []
    CALLS.unlink(missing_ok=True); return out

SECOND = {"name": "second", "path": str(T / "second"), "home": str(T / "home-second"), "mirror_url": "https://example.invalid/second/{key}.md",
          "slugs": ["gamma"], "prefixes": ["projects/beta-"], "stale_hours": 0}

sys.path.insert(0, STACK)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
@contextlib.contextmanager
def stderr():
    buf = io.StringIO(); old = sys.stderr; sys.stderr = buf
    try: yield buf
    finally: sys.stderr = old

from stackshot.core import config as _cfg; from stackshot.projects import brains; from stackshot.projects import pages as _pg; from stackshot.router import page_debt; from stackshot.projects import rename_page
_cfg.CFG["pages"]["flavor"] = "gbrain"
def set_brains(*bs):
    if bs: _cfg.CFG["brains"] = [dict(b) for b in bs]
    else: _cfg.CFG.pop("brains", None)
    brains._WARNED.clear()

# ---- 1. no [[brains]]: as before
set_brains()
check("1 every slug is in the default brain", brains.for_key("projects/beta-one").default and brains.for_key("gamma").default and not brains.configured())
check("1 a page file is under paths.brain", brains.file("beta-one") == str(T / "brain/projects/beta-one.md"), brains.file("beta-one"))
check("1 the page store is the flavor's own, no router in front", type(page_debt.page_io()).__name__ == "GbrainIO", type(page_debt.page_io()))
fms, rels = _pg.read_pages()
check("1 read_pages reads the default brain only", set(fms) == {"projects/alpha", "projects/beta-one"} and fms["projects/beta-one"]["title"] == "Beta One (old copy)", sorted(fms))
check("1 read_mirror reads paths.brain", "leftover" in (page_debt.read_mirror("projects/beta-one") or ""))
page_debt.page_io().put("projects/beta-one", "x", "r0")
c = calls()
check("1 a write runs gbrain with the environment untouched (no GBRAIN_HOME)", len(c) == 1 and c[0]["home"] is None and c[0]["argv"][:2] == ["put", "projects/beta-one"], c)
check("1 page link is the default mirror", _pg.page_link("projects/beta-one") == "https://github.com/example/brain/blob/main/projects/beta-one.md", _pg.page_link("projects/beta-one"))
_cfg.CFG["pages"]["flavor"] = "plain"
try:
    rename_page.gb(["put", "projects/alpha"], stdin="x"); refused = False
except rename_page.PlainPages: refused = True
check("1 plain flavor still refuses a gbrain call for the default brain", refused and not calls())
_cfg.CFG["pages"]["flavor"] = "gbrain"

# ---- 2. a second brain: routed reads and writes
set_brains(SECOND)
check("2 a prefix routes to the second brain", brains.for_key("projects/beta-one").name == "second")
check("2 a bare slug in `slugs` routes there, with its sub-pages", brains.for_key("gamma").name == "second" and brains.for_key("projects/gamma/round-a").name == "second")
check("2 any other slug stays in the default brain", brains.for_key("projects/alpha").default and brains.for_key("projects/delta").default)
check("2 the file is in the second copy", brains.file("projects/beta-one") == str(T / "second/projects/beta-one.md"))
fms, rels = _pg.read_pages()
check("2 read_pages: each page from its own brain, strays ignored", set(fms) == {"projects/alpha", "projects/beta-one", "projects/gamma"} and fms["projects/beta-one"]["title"] == "Beta One", sorted(fms))
check("2 read_mirror reads the second copy", "Second brain page" in (page_debt.read_mirror("projects/beta-one") or ""))
check("2 the Current state comes from the second copy", "Second brain page" in _pg.current_state("projects/beta-one"))
ts = _pg.page_ts("projects/beta-one")
check("2 page freshness is read in the second copy", ts is not None and ts >= int(os.path.getmtime(T / "second/projects/beta-one.md")) - 1, ts)
check("2 exists() looks in the second copy", _pg.exists("projects/gamma") is True and _pg.exists("projects/beta-two") is False)
_pg.cmd_registry(quiet=True)
reg = json.loads((T / "store/projects.json").read_text())["pages"]
check("2 the registry holds the second brain's pages with its mirror link", reg.get("projects/beta-one", {}).get("mirror") == "https://example.invalid/second/projects/beta-one.md"
      and reg.get("projects/alpha", {}).get("mirror", "").startswith("https://github.com/example/brain/"), {k: v.get("mirror") for k, v in reg.items()})
check("2 page link uses the second brain's mirror", _pg.page_link("projects/gamma") == "https://example.invalid/second/projects/gamma.md")
store = page_debt.page_io()
store.put("projects/beta-one", "new text", "r1"); store.put("projects/alpha", "a text", "r1"); store.add_timeline("gamma", "2026-11-02", "s", "", "test")
c = calls()
check("2 a write to a second-brain slug runs gbrain with its home", c[0]["home"] == str(T / "home-second") and c[0]["argv"][:2] == ["put", "projects/beta-one"] and c[0]["stdin"] == "new text", c)
check("2 a write to a default slug carries no GBRAIN_HOME", c[1]["home"] is None and c[1]["argv"][:2] == ["put", "projects/alpha"], c)
check("2 a timeline call finds the slug in its JSON and routes it", c[2]["home"] == str(T / "home-second") and c[2]["argv"][:2] == ["call", "add_timeline_entry"], c)
content, rev = store.get("projects/beta-one"); calls()
check("2 a read for a write goes through the second brain's CLI", content == "page from " + str(T / "home-second") and rev == "r1", content)
_cfg.CFG["pages"]["flavor"] = "plain"
store = page_debt.page_io()
st, _note = store.put("projects/beta-one", "plain-flavor text", "r1"); c = calls()
check("2 under plain flavor a second-brain write still runs gbrain with its home", st == "ok" and len(c) == 1 and c[0]["home"] == str(T / "home-second"), (st, c))
check("2 under plain flavor a default write is the file, no CLI", store.get("projects/alpha")[0].startswith("---\ntitle: Alpha") and not calls())
_cfg.CFG["pages"]["flavor"] = "gbrain"
check("2 a healthy second brain reports no problem", brains.problem(brains.for_key("gamma")) == "")

# ---- 3. the second copy is missing: fail open everywhere
from stackshot.web import server
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import gates as _gates
from stackshot.service import page_debt as pdebt_svc
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.routes import client_api as _rt_client
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
shutil.move(str(T / "second"), str(T / "second-away"))
with stderr() as err:
    fms, _rels, skipped_ = _pg.read_pages_ex()
    _pg.read_pages()
check("3 read_pages leaves the second brain out and names it (a value of the call, no module state)", "projects/beta-one" not in fms and "second" in skipped_ and "projects/alpha" in fms
      and not hasattr(_pg, "SKIPPED"), (sorted(fms), skipped_))
check("3 the warning names the brain, once", err.getvalue().count("second brain 'second'") == 1, err.getvalue())
_pg.cmd_registry(quiet=True)
reg = json.loads((T / "store/projects.json").read_text())["pages"]
check("3 the registry keeps the second brain's pages as last read", "projects/beta-one" in reg and "projects/gamma" in reg and "projects/alpha" in reg, sorted(reg))
check("3 exists() cannot tell (None), never False", _pg.exists("projects/beta-one") is None)
meta = {"project": "beta-new", "owner": "someone"}
with stderr() as err:
    try: _gates.gate_metadata(meta, creating=True); refused = ""
    except Exception as e: refused = str(e)
check("3 create's page check accepts a key of the unreadable brain", not refused and meta["project"] == "projects/beta-new", refused or meta)
check("3 create's check logs a warning naming the brain", "second" in err.getvalue() and "beta-new" in err.getvalue(), err.getvalue())
meta = {"project": "nosuchpage", "owner": "someone"}
try: _gates.gate_metadata(meta, creating=True); refused = ""
except Exception as e: refused = str(e)
check("3 a default-brain key that names no page is still refused", "names no page" in refused, refused)
SID = "aaaaaaaa-0000-4000-8000-000000000001"
_pg.save_state(SID, {"touches": {"projects/beta-one": {"ts": int(time.time()) - 3600, "task": "s1"}, "projects/alpha": {"ts": int(time.time()) + 3600, "task": "s2"}}})
hook_skip = {}
brains._WARNED.clear()      # the page hook is a process of its own: it says so once for its own run
with stderr() as err:
    stale = _pg.stale_touches(SID, skipped=hook_skip)
check("3 the page hook accepts the second-brain touch and keeps it for later", [k for k, _v in stale] == ["projects/alpha"] and hook_skip == {"projects/beta-one": "second"}
      and "projects/beta-one" in _pg.load_state(SID)["touches"] and not hasattr(_pg, "BRAIN_SKIP"), (stale, hook_skip))
check("3 the page hook warns naming the brain", "second brain 'second'" in err.getvalue(), err.getvalue())
out = io.StringIO()
with contextlib.redirect_stdout(out):
    sys.stdin = io.StringIO(json.dumps({"session_id": SID})); _pg.cmd_nag()
check("3 the nag says the second brain was not checked and does not block", "second brain not readable" in out.getvalue() and "brain second" in out.getvalue(), out.getvalue())
OWNER = "bbbbbbbb-0000-4000-8000-000000000002"
server._owed_save({"projects/beta-one": {OWNER: {"ts": time.time() - 3 * 3600, "item": "s1"}}})
_cfg.CFG["page_rule"]["mode"] = "refuse"
brains._WARNED.clear()      # the server is a process of its own: it says so once for its own run
with stderr() as err:
    d = server._owed_settle(); nag = server._nag(OWNER)
    try: _web_page_debts._refuse_if_owing(OWNER); refused = ""
    except Exception as e: refused = str(e)
check("3 pages owed keep the debt (not settled, not dropped)", "projects/beta-one" in d and "projects/beta-one" in server._owed_load(), d)
check("3 pages owed neither nag nor refuse for the unreadable brain", "beta-one" not in nag and not refused, (nag, refused))
check("3 pages owed report it once", err.getvalue().count("pages owed and the audit's page call skip") == 1, err.getvalue())
_cfg.CFG.setdefault("router", {}).update(page_debt=True, page_debt_shadow=True)
server._owed_save({"projects/beta-one": {OWNER: {"ts": time.time() - 3 * 3600, "item": "s1", "moved": True, "debts": [{"item": "s1", "what": "changed", "writer": OWNER}]}}})
page_debt.write_days({})
r = pdebt_svc.page_debt_pass(runner=lambda msg: (_ for _ in ()).throw(AssertionError("no call for a skipped brain")))
check("3 the audit's page call skips the unreadable brain's page", r.get("pages") == 0 and "projects/beta-one" in server._owed_load(), r)
shutil.move(str(T / "second-away"), str(T / "second"))
brains._WARNED.clear()
class NoPage:
    def get(self, slug): return None, None
    def put(self, *a): raise AssertionError("no put")
fell = []
orig_fb = pdebt_svc.page_debt_fallback
pdebt_svc.page_debt_fallback = lambda *a, **k: fell.append(a) or ""
moved = {OWNER: {"ts": time.time(), "item": "s1", "moved": True, "debts": [{"item": "s1", "what": "changed", "writer": OWNER}]}}
with stderr() as err:
    res = pdebt_svc.page_debt_project("projects/beta-one", moved, time.time(), "live", runner=lambda m: {"status": "spawn"}, io=NoPage())
pdebt_svc.page_debt_fallback = orig_fb
check("3 a failed gbrain read of a second-brain page skips it, no fallback", res == "skipped" and not fell, (res, fell))
check("3 the failed read is reported naming the brain", "second brain 'second'" in err.getvalue(), err.getvalue())
_cfg.CFG["router"]["page_debt"] = False

# ---- 4. a broken CLI home for the second brain: the write fails, the caller hears it (nothing raised)
set_brains({**SECOND, "home": str(T / "home-broken")})
st, note = page_debt.page_io().put("projects/beta-one", "x", "r1"); calls()
check("4 a failing CLI for the second brain is a refusal, not a crash", st == "refused" and "not signed in" in note, (st, note))
note = page_debt.page_io().add_timeline("projects/beta-one", "2026-11-02", "s", "", "test"); calls()
check("4 a failing timeline call says why and never raises", "not signed in" in note, note)

# ---- 5. stale copy, and config notes
set_brains({**SECOND, "stale_hours": 1})
fetch = T / "second/.git/FETCH_HEAD"; fetch.write_text("x")
old = time.time() - 5 * 3600
for f in (fetch, T / "second/.git/HEAD"): os.utime(f, (old, old))
why = brains.problem(brains.for_key("gamma"))
check("5 a copy not synced for stale_hours is stale", "has not been synced" in why, why)
os.utime(fetch, None)
check("5 a fresh fetch makes it current again", brains.problem(brains.for_key("gamma")) == "")
notes = _cfg.notes({**_cfg.CFG, "brains": [{"name": "x"}]})
check("5 config notes name an entry without a path", any("[[brains]] entry 1" in n for n in notes), notes)
notes = _cfg.notes({k: v for k, v in _cfg.CFG.items() if k != "brains"})
check("5 no [[brains]], no note about it", not any("brains" in n for n in notes), notes)

# ---- 6. a brain with no home is not reached through the CLI: a write and a read are refused with a line saying why (a read would return the default brain's page)
set_brains({**SECOND, "home": ""}); calls()
store = page_debt.page_io()
st_put, note_put = store.put("projects/beta-one", "x", "r1")
st_new, note_new = store.create("projects/beta-fresh", "x")
note_tl = store.add_timeline("gamma", "2026-11-02", "s", "", "test")
rc_gb, out_gb = rename_page.gb(["put", "projects/beta-one", "--expected-revision", "r1"], stdin="x")
c = calls()
check("6 a put for a brain with no home is refused and names the brain and the fix", st_put == "refused" and "second" in note_put and "no home" in note_put and "home =" in note_put, (st_put, note_put))
check("6 a create, a timeline line and a rename's gb call are refused the same way", st_new == "refused" and "no home" in note_new and "no home" in note_tl and rc_gb != 0 and "no home" in out_gb,
      (st_new, note_new, note_tl, rc_gb, out_gb))
check("6 no gbrain command ran for any of them (nothing reached the default brain)", c == [], c)
content, rev = store.get("projects/beta-one"); c = calls()
check("6 a read returns no page and runs no gbrain command (not the default brain's page)", content is None and rev is None and c == [], (content, rev, c))
rc_rd, out_rd = rename_page.gb(["call", "get_page", json.dumps({"slug": "projects/beta-one"})]); c = calls()
check("6 a rename's read of its slug is refused naming the brain, nothing ran", rc_rd != 0 and "second" in out_rd and "no home" in out_rd and c == [], (rc_rd, out_rd, c))
fell = []; orig_fb = pdebt_svc.page_debt_fallback
pdebt_svc.page_debt_fallback = lambda *a, **k: fell.append(a) or ""
moved6 = {"bbbbbbbb-0000-4000-8000-000000000002": {"ts": time.time(), "item": "s1", "moved": True, "debts": [{"item": "s1", "what": "changed", "writer": "bbbbbbbb-0000-4000-8000-000000000002"}]}}
brains._WARNED.clear()
with stderr() as err:
    res6 = [pdebt_svc.page_debt_project("projects/beta-one", moved6, time.time(), "live", runner=lambda m: {"status": "spawn"}) for _ in range(2)]
pdebt_svc.page_debt_fallback = orig_fb; c = calls()
check("6 the audit's page call skips a no-home brain's page, no fallback, no gbrain command", res6 == ["skipped", "skipped"] and not fell and c == [], (res6, fell, c))
check("6 and warns once for the outage, naming the brain", err.getvalue().count("second brain 'second'") == 1, err.getvalue())
st_d, _n = store.put("projects/alpha", "a text", "r1"); c = calls()
check("6 a default-brain write is not touched by it", st_d == "ok" and len(c) == 1 and c[0]["home"] is None, (st_d, c))
check("6 config.notes names the entry with no home", any("[[brains]] second has no home" in n for n in _cfg.notes()), _cfg.notes())
check("6 an entry with a home, or a client's remote entry, gets no such note", not any("has no home" in n for n in _cfg.notes({**_cfg.CFG, "brains": [dict(SECOND)]}))
      and not any("has no home" in n for n in _cfg.notes({**_cfg.CFG, "brains": [{**SECOND, "home": "", "remote": True}]})))

# ---- 7. a copy that exists but is no usable copy counts as a problem: create's page check and the page hook fail open
EMPTY = T / "second-empty"; EMPTY.mkdir()
set_brains({**SECOND, "path": str(EMPTY)})
why = brains.problem(brains.for_key("gamma"))
check("7 an empty folder (a mount point with nothing mounted) is no usable copy", "not a git copy" in why, why)
(EMPTY / ".git").mkdir()
why = brains.problem(brains.for_key("gamma"))
check("7 a git folder with no page (a clone in progress) is no usable copy either", "holds no pages" in why, why)
meta = {"project": "beta-fresh", "owner": "someone"}
with stderr() as err:
    try: _gates.gate_metadata(meta, creating=True); refused = ""
    except Exception as e: refused = str(e)
check("7 create's page check accepts the key of a brain whose copy is an empty folder (no 'names no page')", not refused and meta["project"] == "projects/beta-fresh", refused or meta)
check("7 and logs a warning naming the brain", "second" in err.getvalue() and "beta-fresh" in err.getvalue(), err.getvalue())
SID2 = "aaaaaaaa-0000-4000-8000-000000000003"
_pg.save_state(SID2, {"touches": {"projects/beta-one": {"ts": int(time.time()) - 3600, "task": "s1"}}})
hook_skip = {}
with stderr() as err:
    stale = _pg.stale_touches(SID2, skipped=hook_skip)
check("7 the page hook accepts a touch in a brain whose copy is an empty folder, and keeps it", stale == [] and hook_skip == {"projects/beta-one": "second"}
      and "projects/beta-one" in _pg.load_state(SID2)["touches"], (stale, hook_skip))
with stderr():
    _f, _r, skipped_ = _pg.read_pages_ex()
check("7 read_pages leaves an empty-folder brain out (not read as 'no pages')", "second" in skipped_ and "projects/beta-one" not in _f, (skipped_, sorted(_f)))
check("7 exists() cannot tell (None) for it, never False", _pg.exists("projects/beta-one") is None)

# ---- 8. a stale copy: the same two fail open, and a fresh sync makes the checks real again
set_brains({**SECOND, "stale_hours": 1})
fetch = T / "second/.git/FETCH_HEAD"; fetch.write_text("x")
old = time.time() - 5 * 3600
git(T / "second", "commit", "-q", "--allow-empty", "-m", "old", GIT_COMMITTER_DATE="2026-10-02T00:00:00Z", GIT_AUTHOR_DATE="2026-10-02T00:00:00Z")
for f in (fetch, T / "second/.git/HEAD"): os.utime(f, (old, old))
why = brains.problem(brains.for_key("gamma"))
check("8 the copy counts as stale", "has not been synced" in why, why)
meta = {"project": "beta-stale", "owner": "someone"}
with stderr() as err:
    try: _gates.gate_metadata(meta, creating=True); refused = ""
    except Exception as e: refused = str(e)
check("8 create's page check accepts a key of the stale brain and says so", not refused and meta["project"] == "projects/beta-stale" and "second" in err.getvalue(), (refused, meta, err.getvalue()))
SID3 = "aaaaaaaa-0000-4000-8000-000000000004"
_pg.save_state(SID3, {"touches": {"projects/gamma": {"ts": int(time.time()) - 3600, "task": "s1"}}})
hook_skip = {}
with stderr():
    stale = _pg.stale_touches(SID3, skipped=hook_skip)
check("8 the page hook accepts the touch in the stale brain", stale == [] and hook_skip == {"projects/gamma": "second"}, (stale, hook_skip))
os.utime(fetch, None)
meta = {"project": "beta-stale", "owner": "someone"}
try: _gates.gate_metadata(meta, creating=True); refused = ""
except Exception as e: refused = str(e)
check("8 once synced, the same key is checked again and refused", "names no page" in refused, refused or meta)

# ---- 9. config notes: a loose prefix and a repeated name
def notes_for(*entries): return _cfg.notes({**_cfg.CFG, "brains": [dict(e) for e in entries]})
base = {"name": "one", "path": "/x", "home": "/h", "slugs": ["projects/p"]}
n = notes_for({**base, "prefixes": ["projects/beta"]})
check("9 a prefix that does not end in - or / is named, with the entry and the longer name it catches", any("[[brains]] one prefix 'projects/beta'" in x and "projects/betamax" in x for x in n), n)
check("9 prefixes ending in - or / get no such note", not any("prefix" in x for x in notes_for({**base, "prefixes": ["projects/beta-", "projects/gamma/"]})))
n = notes_for(base, {**base, "path": "/y"})
check("9 a repeated brain name is named", any("repeats the name 'one'" in x for x in n), n)
check("9 distinct names get no such note", not any("repeats" in x for x in notes_for(base, {**base, "name": "two"})))

# ---- 10. client config: each brain's mirror and slug rules reach a client box, and its page links go to the right mirror
import importlib.machinery, importlib.util, tomllib
set_brains(SECOND)
cc = _rt_client._client_config()
check("10 the client config carries the brain's name, mirror and slug rules", cc.get("brains") == [{"name": "second", "path": str(T / "second"), "mirror_url": SECOND["mirror_url"],
      "slugs": ["projects/gamma"], "prefixes": ["projects/beta-"]}], cc.get("brains"))
check("10 and not the gbrain home", all("home" not in b for b in cc["brains"]) and str(T / "home-second") not in json.dumps(cc), cc.get("brains"))
set_brains()
check("10 with no [[brains]] the client config has no brains key", "brains" not in _rt_client._client_config())
set_brains(SECOND)
from stackshot import cli
text = cli.client_config_text(_rt_client._client_config(), "https://board.example.com")
parsed = tomllib.loads(text)
check("10 client install writes the brain into the client's config", parsed.get("brains") == [{"name": "second", "path": str(T / "second"), "mirror_url": SECOND["mirror_url"],
      "slugs": ["projects/gamma"], "prefixes": ["projects/beta-"], "remote": True}], parsed.get("brains"))
_cfg.CFG["brains"] = parsed["brains"]; brains._WARNED.clear()
check("10 on the client a second-brain page links to the brain's mirror, another page to the default mirror",
      _pg.page_link("projects/beta-one") == "https://example.invalid/second/projects/beta-one.md" and _pg.page_link("projects/alpha").startswith("https://github.com/example/brain/"),
      (_pg.page_link("projects/beta-one"), _pg.page_link("projects/alpha")))
check("10 the client's config.notes has no complaint about the missing home", not any("has no home" in x for x in _cfg.notes()), _cfg.notes())

# ---- 11. a rename stub links to the slug's own brain, and says so when that brain has none
STUB_IN = "---\nname: Gamma\ntags:\n  - t\n---\n\nbody\n"
set_brains(SECOND)
out = rename_page.stub(STUB_IN, "projects/old-g", "projects/gamma", "why")
check("11 the stub links to the new page's brain mirror", "(https://example.invalid/second/projects/gamma.md)" in out and "github.com/example/brain" not in out, out)
set_brains({**SECOND, "mirror_url": ""})
out = rename_page.stub(STUB_IN, "projects/old-g", "projects/gamma", "why")
check("11 a brain with no mirror gets no link, and the stub says so (no fallback to the default mirror)", "github.com/example/brain" not in out and "second has no mirror_url" in out and "(http" not in out, out)
set_brains(SECOND)
out = rename_page.stub(STUB_IN, "projects/old-a", "projects/alpha", "why")
check("11 a default-brain page keeps the default mirror", "(https://github.com/example/brain/blob/main/projects/alpha.md)" in out, out)

# ---- 12. the audit's page call: a failed CLI read of a second-brain page leaves no mark for the run, so the next run tries again
set_brains(SECOND)
_cfg.CFG.setdefault("router", {}).update(page_debt=True, page_debt_shadow=False)
OWNER2 = "cccccccc-0000-4000-8000-000000000005"
os.utime(T / "second/projects/beta-one.md", (old, old))     # the page was last written before the debt, so the debt stays owed
server._owed_save({"projects/beta-one": {OWNER2: {"ts": time.time(), "item": "s1", "moved": True, "debts": [{"item": "s1", "what": "changed", "writer": OWNER2}]}}})
page_debt.write_days({})
class Flaky:
    up = False
    def get(self, slug): return (PAGE("Beta One", "Second brain page."), "r1") if self.up else (None, None)
    def put(self, *a): raise AssertionError("no put")
flaky = Flaky(); ran_calls = []
runner = lambda m: ran_calls.append(1) or {"status": "spawn"}
orig_fb = pdebt_svc.page_debt_fallback
pdebt_svc.page_debt_fallback = lambda *a, **k: ""
try:
    with stderr() as err:
        r1 = pdebt_svc.page_debt_pass(runner=runner, io=flaky)
        marks1 = page_debt.read_days()
        r2 = pdebt_svc.page_debt_pass(runner=runner, io=flaky)
    check("12 a failed CLI read skips the page and writes no mark for the day", r1.get("skipped") == 1 and "projects/beta-one" not in marks1 and not ran_calls, (r1, marks1, ran_calls))
    check("12 the next pass tries again (still failing: skipped again, still no mark), said once", r2.get("skipped") == 1 and "projects/beta-one" not in page_debt.read_days()
          and err.getvalue().count("second brain 'second'") == 1, (r2, err.getvalue()))
    flaky.up = True
    r3 = pdebt_svc.page_debt_pass(runner=runner, io=flaky)
    check("12 once the CLI reads again the page is called and the day mark is written", len(ran_calls) == 1 and "projects/beta-one" in page_debt.read_days() and r3.get("skipped") is None, (r3, ran_calls, page_debt.read_days()))
    r4 = pdebt_svc.page_debt_pass(runner=runner, io=flaky)
    check("12 and the page is not called again that day", len(ran_calls) == 1 and r4.get("pages") == 0, (r4, ran_calls))
finally:
    pdebt_svc.page_debt_fallback = orig_fb
    _cfg.CFG["router"]["page_debt"] = False

# ---- 13. a linked worktree as the copy: its sync stamps are found through the `.git` file
WT = T / "second-wt"
git(T / "second", "worktree", "add", "-q", "--detach", str(WT))
check("13 a worktree layout (.git is a file) is a usable copy", (WT / ".git").is_file() and brains.unusable(brains.Brain(name="wt", path=WT)) == "")
os.utime(T / "second/.git/FETCH_HEAD", None)
t = brains._synced_at(WT)
check("13 _synced_at reads the common dir's FETCH_HEAD for it", t is not None and t > time.time() - 600, t)
git(WT, "commit", "-q", "--allow-empty", "-m", "old2", GIT_COMMITTER_DATE="2026-10-03T00:00:00Z", GIT_AUTHOR_DATE="2026-10-03T00:00:00Z")
for f in [*(T / "second/.git/worktrees").glob("*/*HEAD"), T / "second/.git/FETCH_HEAD", T / "second/.git/HEAD"]: os.utime(f, (old, old))
check("13 and a worktree copy not synced for stale_hours is stale", "has not been synced" in brains.stale(brains.Brain(name="wt", path=WT, stale_hours=1)), t)

# ---- 14. secret_file: a remote brain's CLI client secret reaches that brain's CLI calls only, in the child's environment, and nowhere else
MADE = "made-up-client-secret-0123456789"          # a made-up value: the real secret is never in a test
SF = T / "second-secret.json"
def write_secret(text, mode=0o600, path=SF):
    path.write_text(text, encoding="utf-8"); os.chmod(path, mode)
def leaks(*texts): return [i for i, t in enumerate(texts) if MADE in str(t)]
set_brains({**SECOND, "secret_file": str(SF)}); calls()
write_secret(json.dumps({"client_id": "made-up-id", "client_secret": MADE}))
with stderr() as err:
    st, note = page_debt.page_io().put("projects/beta-one", "x", "r1")
    content, rev = page_debt.page_io().get("projects/beta-one")
    note_tl = page_debt.page_io().add_timeline("projects/beta-one", "2026-11-02", "s", "", "test")
    _ = page_debt.page_io().put("projects/alpha", "x", "r1")
c = calls()
sec_calls = [x for x in c if x["home"] == str(T / "home-second")]
check("14 every call for the brain (put, read, timeline) carries GBRAIN_REMOTE_CLIENT_SECRET in the child's environment, from a JSON secret_file", len(sec_calls) == 3 and all(x["secret"] == MADE for x in sec_calls), c)
check("14 a default-brain call carries none", [x["secret"] for x in c if x["home"] is None] == [None], c)
check("14 the calls worked (put ok, page read, timeline accepted)", st == "ok" and content is not None and note_tl == "", (st, note, content, note_tl))
check("14 the server's own environment never holds it", "GBRAIN_REMOTE_CLIENT_SECRET" not in os.environ and MADE not in json.dumps(dict(os.environ)))
given = {"PATH": "/x"}; brains.gbrain_env(env=given, brain=brains.by_name("second"))
check("14 gbrain_env returns a copy: the env passed in is untouched", given == {"PATH": "/x"}, given)
cc = _rt_client._client_config()
check("14 the client config carries neither the value, the file's path nor the key", not leaks(json.dumps(cc)) and str(SF) not in json.dumps(cc) and "secret" not in json.dumps(cc), cc)
check("14 no log line, note or repr carries the value or the path", not leaks(err.getvalue(), _cfg.notes(), repr(brains.extra()), repr(brains.all_brains())) and str(SF) not in repr(brains.extra()),
      (err.getvalue(), _cfg.notes()))
check("14 a good file (mode 600) gives no config note", not any("secret_file" in n for n in _cfg.notes()), _cfg.notes())
check("14 the client entry list names no secret_file", all("secret" not in k for b_ in brains.client_entries() for k in b_))

write_secret(MADE + "\n")         # a plain one-line file
calls(); st, _n = page_debt.page_io().put("projects/beta-one", "x", "r1"); c = calls()
check("14 a plain one-line file works too", st == "ok" and c and c[0]["secret"] == MADE, c)
write_secret("\n  " + MADE + "  \nsecond line\n")
calls(); page_debt.page_io().put("projects/beta-one", "x", "r1"); c = calls()
check("14 a plain file reads its first non-empty line, trimmed", c and c[0]["secret"] == MADE, c)
write_secret(json.dumps({"client_secret": MADE + "-rotated"}))
calls(); page_debt.page_io().put("projects/beta-one", "x", "r1"); c = calls()
check("14 a rotated secret applies at the next call", c and c[0]["secret"] == MADE + "-rotated", c)

set_brains(SECOND); calls(); page_debt.page_io().put("projects/beta-one", "x", "r1"); c = calls()
check("14 an entry with no secret_file passes none", c and c[0]["secret"] is None, c)
set_brains({**SECOND, "secret_file": ""}); calls(); page_debt.page_io().put("projects/beta-one", "x", "r1"); c = calls()
check("14 an empty secret_file is the same as none, with no config note", c and c[0]["secret"] is None and not any("secret_file" in n for n in _cfg.notes()), (c, _cfg.notes()))

# a file group or others can read is refused: at config load (a note naming the path) and at the call
set_brains({**SECOND, "secret_file": str(SF)}); write_secret(json.dumps({"client_secret": MADE}), 0o644); calls()
n = [x for x in _cfg.notes() if "secret_file" in x]
check("14 a group/world-readable secret_file gets a config note naming the entry, the path and why", len(n) == 1 and "second" in n[0] and str(SF) in n[0] and "readable by group or others" in n[0] and "0644" in n[0], n)
check("14 and the note carries no secret", not leaks(n))
for mode in (0o640, 0o604, 0o660):
    os.chmod(SF, mode)
    check(f"14 mode {mode:04o} is refused as well", any("readable by group or others" in x for x in _cfg.notes()))
os.chmod(SF, 0o644)
with stderr() as err:
    st, note = page_debt.page_io().put("projects/beta-one", "x", "r1")
    content, rev = page_debt.page_io().get("projects/beta-one")
    rc_gb, out_gb = rename_page.gb(["put", "projects/beta-one"], stdin="x")
c = calls()
check("14 the call for that brain is refused with a note naming the path and the reason, and no CLI ran", st == "refused" and str(SF) in note and "readable by group or others" in note and c == [], (st, note, c))
check("14 a read is a page that could not be read (None), and a raw gb call returns the refusal", content is None and rev is None and rc_gb != 0 and str(SF) in out_gb, (content, rev, rc_gb, out_gb))
check("14 the outage is said once, naming the brain and the path, without the value", err.getvalue().count("second brain 'second'") == 1 and str(SF) in err.getvalue()
      and not leaks(err.getvalue(), note, out_gb), err.getvalue())
check("14 the default brain's calls are not touched", page_debt.page_io().put("projects/alpha", "a", "r1")[0] == "ok" and calls()[0]["secret"] is None)
os.chmod(SF, 0o600); calls()
st, note = page_debt.page_io().put("projects/beta-one", "x", "r1"); c = calls()
check("14 after chmod 600 it works again, and the next outage is reported afresh", st == "ok" and c and c[0]["secret"] == MADE and ("second", "its gbrain CLI calls are refused") not in brains._WARNED, (st, note, c))

# a file that cannot be read, or has no client_secret, fails open with a note naming the path and the reason
def refused_with(label, want):
    brains._WARNED.clear(); calls()
    with stderr() as err_:
        st_, note_ = page_debt.page_io().put("projects/beta-one", "x", "r1")
        content_, _r = page_debt.page_io().get("projects/beta-one")
        tl_ = page_debt.page_io().add_timeline("projects/beta-one", "2026-11-02", "s", "", "test")
    c_ = calls()
    check(f"14 {label}: put refused, read None, timeline says why, none runs the CLI, nothing raised",
          st_ == "refused" and content_ is None and str(SF) in note_ and want in note_ and str(SF) in tl_ and c_ == [], (st_, note_, content_, tl_, c_))
    check(f"14 {label}: said once, naming the brain and the path, and carries no secret", err_.getvalue().count("second brain 'second'") == 1 and str(SF) in err_.getvalue()
          and not leaks(err_.getvalue(), note_, tl_), err_.getvalue())
SF.unlink()
refused_with("a missing file", "cannot be read")
write_secret(json.dumps({"client_id": "made-up-id", "note": MADE}))
refused_with("a JSON file with no client_secret key", "no client_secret key")
write_secret(json.dumps({"client_secret": ""}))
refused_with("a JSON file with an empty client_secret", "no client_secret key")
write_secret("{not json " + MADE)
refused_with("a file that is not valid JSON (its content is not echoed)", "not valid JSON")
write_secret("  \n\n")
refused_with("an empty file", "is empty")
write_secret(json.dumps([MADE]))
refused_with("a JSON list", "no client_secret key")
SF.unlink(); SF.mkdir(); os.chmod(SF, 0o700)
refused_with("a directory", "cannot be read")
SF.rmdir()
check("14 a secret_file that is not a string gets a config note", any("secret_file is not a path" in x for x in notes_for({**base, "secret_file": 5})), notes_for({**base, "secret_file": 5}))

# a CLI that echoes its environment into an error: the output is cleaned of the secret
write_secret(json.dumps({"client_secret": MADE}))
set_brains({**SECOND, "home": str(T / "home-echo"), "secret_file": str(SF)}); calls()
st, note = page_debt.page_io().put("projects/beta-one", "x", "r1")
rc_e, out_e = rename_page.gb(["call", "get_page", json.dumps({"slug": "projects/beta-one"})]); c = calls()
check("14 the CLI did get the secret and failed", len(c) == 2 and all(x["secret"] == MADE for x in c) and st == "refused" and rc_e == 2, (st, c))
check("14 an error that echoes it reaches the note and the reply cleaned", not leaks(note, out_e) and "[redacted]" in note and "[redacted]" in out_e, (note, out_e))
check("14 the server's environment is still clean after all of it", MADE not in json.dumps(dict(os.environ)))
check("14 a client's remote entry with a secret_file gets no home note", not any("has no home" in x for x in _cfg.notes({**_cfg.CFG, "brains": [{**SECOND, "home": "", "remote": True, "secret_file": str(SF)}]})))

# ---- 15. the parent's own client secret never reaches a child; one read of the file decides; an unusable value (control character, too short) is refused
PARENT = "made-up-parent-secret-ABCDEFGHIJ"
SK = brains.SECRET_ENV
rename_page.ENV[SK] = PARENT       # the server's environment as rename_page copied it at its import: here it holds a client secret of its own
try:
    write_secret(json.dumps({"client_secret": MADE}))
    set_brains({**SECOND, "secret_file": str(SF)}); calls()
    rename_page.gb(["put", "projects/alpha"], stdin="x")                    # the default brain
    rename_page.gb(["call", "get_page", json.dumps({"slug": "zeta-unknown-page"})])    # a slug no entry holds
    rename_page.gb(["call", "list_pages", "{}"])                            # no slug at all
    rename_page.gb(["put", "projects/beta-one"], stdin="x")                 # the brain with a secret_file
    c = calls()
    check("15 the default brain, an unknown slug and a call with no slug get none of the parent's secret", [x["secret"] for x in c[:3]] == [None, None, None] and len(c) == 4, c)
    check("15 the brain with a secret_file gets its own, not the parent's", c[3]["secret"] == MADE, c)
    set_brains(SECOND); calls()
    rename_page.gb(["put", "projects/beta-one"], stdin="x"); c = calls()
    check("15 a brain without a secret_file gets none of the parent's", len(c) == 1 and c[0]["secret"] is None, c)
    check("15 gbrain_env drops the parent's value for the default brain, a brain with none and an unknown slug",
          all(SK not in brains.gbrain_env(sl, {SK: PARENT, "PATH": "/x"}) for sl in ("projects/alpha", "projects/beta-one", "zeta-unknown-page", "")))
    set_brains({**SECOND, "secret_file": str(SF)})
    check("15 gbrain_env sets the brain's own value over the parent's", brains.gbrain_env("projects/beta-one", {SK: PARENT})[SK] == MADE)

    # a file that turns unusable at the call: refused, nothing runs, the parent's value is not used instead
    calls(); os.chmod(SF, 0o644)
    with stderr():
        rc_u, out_u = rename_page.gb(["put", "projects/beta-one"], stdin="x"); c = calls()
    env_u, why_u = brains.prepare("projects/beta-one", {SK: PARENT})
    check("15 a file unusable at call time refuses and runs nothing; the environment it would have had holds no secret", rc_u == 2 and "readable by group or others" in out_u and c == [] and why_u and SK not in env_u, (rc_u, out_u, c))
    os.chmod(SF, 0o600)

    # one read decides: the file is read once per call, whatever it says the second time
    reads = []; real_secret = brains.secret
    def once_then_gone(b):
        reads.append(b.name)
        return real_secret(b) if len(reads) == 1 else ("", "secret_file changed under the call")
    brains.secret = once_then_gone
    try:
        calls(); rc_o, out_o = rename_page.gb(["put", "projects/beta-one"], stdin="x"); c = calls()
    finally:
        brains.secret = real_secret
    check("15 one call reads the secret_file once, and that read decides the refusal and the environment", len(reads) == 1 and rc_o == 0 and len(c) == 1 and c[0]["secret"] == MADE, (reads, rc_o, c))
    reads.clear(); brains.secret = lambda b: (reads.append(b.name), ("", "secret_file gone"))[1]
    try:
        calls()
        with stderr():
            rc_g, out_g = rename_page.gb(["put", "projects/beta-one"], stdin="x")
        c = calls()
    finally:
        brains.secret = real_secret
    check("15 a read that says unusable refuses, once, with no parent value used", len(reads) == 1 and rc_g == 2 and c == [], (reads, rc_g, c))
finally:
    rename_page.ENV.pop(SK, None)

# a secret with a NUL, a lone surrogate or another control character is unusable: a note, no raise (subprocess.run would raise on it)
def unusable(label, text, want="has an unusable client_secret"):
    write_secret(text); brains._WARNED.clear(); calls()
    try:
        with stderr() as e_:
            rc_n, out_n = rename_page.gb(["put", "projects/beta-one"], stdin="x")
            st_n, note_n = page_debt.page_io().put("projects/beta-one", "x", "r1")
            got_n = page_debt.page_io().get("projects/beta-one")
        c_ = calls(); raised = ""
    except Exception as ex:
        raised = type(ex).__name__; rc_n = out_n = st_n = note_n = got_n = c_ = None; e_ = None
    check(f"15 {label}: refused with the note, nothing raised, no CLI ran, and the value is not in the note",
          not raised and rc_n == 2 and want in out_n and str(SF) in out_n and st_n == "refused" and got_n[0] is None and c_ == [] and "made-up" not in (out_n + note_n),
          (raised, rc_n, out_n, st_n, c_))
set_brains({**SECOND, "secret_file": str(SF)})
unusable("a NUL in a JSON value", json.dumps({"client_secret": "made-up-secret-with-nul\u0000-tail"}))
unusable("a lone surrogate in a JSON value", '{"client_secret": "made-up-secret-with-surrogate\\ud800-tail"}')
unusable("a NUL in a plain file", "made-up-secret-with-nul\x00-tail\n")
unusable("a control character in a plain file", "made-up-secret-with-bell\x07-tail\n")
unusable("a tab inside the value", "made-up-secret\twith-a-tab-tail\n")

# under 16 characters is unusable (redact of a very short value would corrupt page text); 16 is the least that works
unusable("a 15-character plain secret", "abcdefghijklmno\n", "shorter than 16 characters")
unusable("a 15-character JSON secret", json.dumps({"client_secret": "abcdefghijklmno"}), "shorter than 16 characters")
unusable("a one-character secret", "a\n", "shorter than 16 characters")
write_secret("abcdefghijklmnop\n"); calls(); st_s, _n = page_debt.page_io().put("projects/beta-one", "x", "r1"); c = calls()
check("15 a 16-character secret works", st_s == "ok" and c and c[0]["secret"] == "abcdefghijklmnop", (st_s, c))
SF.unlink(missing_ok=True); set_brains()
set_brains()

# ---- 16. a prefix that names no folder in its brain's copy: a warning at load (config.notes: the server's start, a reload and doctor), never a refusal to start
def folder_notes(*entries): return [x for x in notes_for(*entries) if "has no folder" in x or "no folder part" in x]
n = folder_notes({**SECOND, "prefixes": ["docs/beta-"]})
check("16 a prefix whose folder is not in the copy is named, with the prefix, the brain and the copy",
      len(n) == 1 and "[[brains]] second prefix 'docs/beta-'" in n[0] and "'docs'" in n[0] and str(T / "second") in n[0] and "reads as missing" in n[0], n)
check("16 a prefix whose folder is there gives no such note", folder_notes(SECOND) == [], folder_notes(SECOND))
check("16 a prefix ending in / checks its own folder", len(folder_notes({**SECOND, "prefixes": ["projects/beta/"]})) == 1
      and folder_notes({**SECOND, "prefixes": ["projects/"]}) == [], folder_notes({**SECOND, "prefixes": ["projects/beta/"]}))
n = folder_notes({**SECOND, "prefixes": ["projects/beta-", "docs/beta-", "notes/x-"]})
check("16 each prefix with no folder is named once, the good one is not", len(n) == 2 and any("'docs/beta-'" in x for x in n) and any("'notes/x-'" in x for x in n)
      and not any("'projects/beta-'" in x for x in n), n)
check("16 a prefix with no folder part is named", len(folder_notes({**SECOND, "prefixes": ["beta-"]})) == 1, folder_notes({**SECOND, "prefixes": ["beta-"]}))
check("16 a copy that is not there is not judged here (the readers say so)", folder_notes({**SECOND, "path": str(T / "no-such-copy"), "prefixes": ["docs/beta-"]}) == [])
(T / "bare-copy/docs").mkdir(parents=True)
check("16 a folder without a git copy or pages is not judged (a clone in progress)", folder_notes({**SECOND, "path": str(T / "bare-copy"), "prefixes": ["docs/beta-"]}) == [])
# the load output: the server prints each note at its start and on a reload; the entry is still accepted (the brain routes, nothing refuses to start)
set_brains({**SECOND, "prefixes": ["docs/beta-"]})
check("16 the entry is accepted: the brain still loads and routes its prefix", brains.for_key("docs/beta-x").name == "second" and brains.configured())
out = io.StringIO()
with contextlib.redirect_stdout(out):
    for x in _cfg.notes(): print(x)
check("16 the load output carries the warning", "[[brains]] second prefix 'docs/beta-'" in out.getvalue(), out.getvalue())
# a page reported missing under a routed prefix says which brain it looked in
meta = {"project": "docs/beta-z", "owner": "someone"}
try: _gates.gate_metadata(meta, creating=True); refused = ""
except Exception as e: refused = str(e)
check("16 the missing-page refusal names the brain it looked in and the prefix that routed it",
      "names no page" in refused and "second brain 'second'" in refused and "prefix 'docs/beta-'" in refused and str(T / "second") not in refused, refused)
meta = {"project": "no-such-default-page", "owner": "someone"}
try: _gates.gate_metadata(meta, creating=True); refused = ""
except Exception as e: refused = str(e)
check("16 a page of the default brain gets no such sentence", "names no page" in refused and "second brain" not in refused and "Where it looked" not in refused, refused)
check("16 looked_in is empty for the default brain and names a slug route", brains.looked_in("projects/alpha") == "" and "slug 'projects/gamma'" in (set_brains(SECOND) or brains.looked_in("gamma")))

# ---- 17. an outage is said once, the recovery once, and nothing after: the state is per brain
def one_outage(label, read, down, up):
    """`read` is called 3 times while the brain is down, then 3 times after it is back: one warning, one recovery line, nothing else."""
    set_brains(SECOND); down()
    with stderr() as err_down:
        for _ in range(3): read()
    up()
    with stderr() as err_up:
        for _ in range(3): read()
    with stderr() as err_again:
        read()
    d_lines = [l for l in err_down.getvalue().splitlines() if "second brain 'second'" in l]
    u_lines = [l for l in err_up.getvalue().splitlines() if "second brain 'second'" in l]
    check(f"17 {label}: several failed reads give one warning", len(d_lines) == 1 and "is back" not in d_lines[0], err_down.getvalue())
    check(f"17 {label}: the first good read gives exactly one line saying the brain is back", len(u_lines) == 1 and u_lines[0].endswith("is back"), err_up.getvalue())
    check(f"17 {label}: no warning after the recovery", err_again.getvalue() == "", err_again.getvalue())

away = lambda: shutil.move(str(T / "second"), str(T / "second-away"))
back = lambda: shutil.move(str(T / "second-away"), str(T / "second"))
one_outage("the registry read of a missing copy", _pg.read_pages_ex, away, back)

# a second outage after the recovery is reported afresh
set_brains(SECOND); away()
with stderr() as err:
    _pg.read_pages_ex(); _pg.read_pages_ex()
check("17 a later outage is warned about once again", err.getvalue().count("second brain 'second'") == 1 and "is back" not in err.getvalue(), err.getvalue())
back()
with stderr() as err: _pg.read_pages_ex()
check("17 and its recovery is said once", err.getvalue().count("is back") == 1, err.getvalue())

# the audit's page call: failed reads of one page, then it reads again
class Gone:
    def get(self, slug): return None, None
class Fine:
    def get(self, slug): return PAGE("Beta One", "Second brain page."), "rev1"
    def put(self, *a): return "refused", "not in this scenario"
orig_call = page_debt.call
page_debt.call = lambda *a, **k: {"call": "", "status": "none", "proposal": None, "usage": {}, "cost_usd": None, "duration_s": 0.0, "why": "no debt in this scenario", "kind": "none"}
W16 = "00000000-0000-4000-8000-000000000016"
mv16 = {W16: {"ts": time.time(), "item": "s1", "moved": True, "debts": [{"item": "s1", "what": "changed", "writer": W16}]}}
store16 = [Gone()]
class Switch:
    def get(self, slug): return store16[0].get(slug)
try:
    one_outage("the audit's page call", lambda: pdebt_svc.page_debt_project("projects/beta-one", mv16, time.time(), "live", runner=lambda m: {"status": "spawn"}, io=Switch()),
               lambda: store16.__setitem__(0, Gone()), lambda: store16.__setitem__(0, Fine()))
finally:
    page_debt.call = orig_call
set_brains(SECOND)
# one page reading fine is no recovery of another page that still fails (no warning, no "back" line, per outage)
b16 = brains.for_key("gamma")
with stderr() as err:
    brains.warn_once(b16, "the page projects/gamma could not be read", "reads", channel="reads projects/gamma")
    brains.warn_once(b16, "the page projects/beta-one could not be read", "reads", channel="reads projects/beta-one")
    brains.clear(b16, "reads projects/beta-one")
    brains.warn_once(b16, "the page projects/gamma could not be read", "reads", channel="reads projects/gamma")
    brains.clear(b16, "reads projects/gamma")
check("17 a read that works for one page does not end the outage of another, and a clear for a read that never failed prints nothing",
      err.getvalue().count("could not be read") == 1 and err.getvalue().count("is back") == 1, err.getvalue())
with stderr() as err: brains.clear(b16, "never failed"); brains.clear(b16)
check("17 clearing a brain that is not in an outage prints nothing", err.getvalue() == "", err.getvalue())
set_brains()

# a copy that goes stale and is synced again: one warning, one recovery line, nothing after
set_brains({**SECOND, "stale_hours": 1})
fetch16 = T / "second/.git/FETCH_HEAD"; fetch16.write_text("x")
old16 = time.time() - 5 * 3600
for f in (fetch16, T / "second/.git/HEAD"): os.utime(f, (old16, old16))
with stderr() as err_stale:
    for _ in range(3): _pg.read_pages_ex()
os.utime(fetch16, None)
with stderr() as err_fresh:
    for _ in range(3): _pg.read_pages_ex()
check("17 a stale copy read several times gives one warning", err_stale.getvalue().count("second brain 'second'") == 1 and "has not been synced" in err_stale.getvalue()
      and "is back" not in err_stale.getvalue(), err_stale.getvalue())
check("17 synced again: exactly one line saying the brain is back, then nothing", err_fresh.getvalue().strip().splitlines() == ["brains: second brain 'second' is back"], err_fresh.getvalue())

# a page that is no longer visited cannot hold the brain in an outage: settled debts, a renamed or deleted page
set_brains(SECOND)
_cfg.CFG.setdefault("router", {}).update(page_debt=True, page_debt_shadow=False)
page_debt.write_days({})
with stderr() as err:
    for _ in range(2): pdebt_svc.page_debt_project("projects/beta-one", mv16, time.time(), "live", runner=lambda m: {"status": "spawn"}, io=Gone())
check("17 an unreadable page warns once", err.getvalue().count("second brain 'second'") == 1, err.getvalue())
server._owed_save({})       # its debts are settled while it is unreadable: the pass never visits it again
with stderr() as err:
    r16 = pdebt_svc.page_debt_pass(runner=lambda m: (_ for _ in ()).throw(AssertionError("no call without a debt")))
check("17 the next pass says the brain is back once, though the page is never read again", err.getvalue().strip().splitlines() == ["brains: second brain 'second' is back"], (err.getvalue(), r16))
with stderr() as err:
    pdebt_svc.page_debt_project("projects/beta-one", mv16, time.time(), "live", runner=lambda m: {"status": "spawn"}, io=Gone())
check("17 a later outage is warned about again", err.getvalue().count("second brain 'second'") == 1 and "is back" not in err.getvalue(), err.getvalue())
_cfg.CFG["router"]["page_debt"] = False
with stderr() as err: pdebt_svc.page_debt_pass()
check("17 with the audit's page call switched off its stuck read is dropped too", err.getvalue().strip().splitlines() == ["brains: second brain 'second' is back"], err.getvalue())
# a page that still has debts keeps its channel (it is visited again)
_cfg.CFG["router"]["page_debt"] = True
server._owed_save({"projects/beta-one": {W16: {"ts": time.time() - 3 * 3600, "item": "s1", "moved": True, "debts": [{"item": "s1", "what": "changed", "writer": W16}]}}})
brains._WARNED.clear(); page_debt.write_days({})
with stderr() as err:
    pdebt_svc.page_debt_project("projects/beta-one", mv16, time.time(), "live", runner=lambda m: {"status": "spawn"}, io=Gone())
    pdebt_svc.page_debt_pass(io=Gone(), runner=lambda m: {"status": "spawn"})
check("17 a page with debts still owed keeps the outage open: no recovery line", err.getvalue().count("is back") == 0 and ("second", "the audit's page call skips its pages this run projects/beta-one") in brains._WARNED, (err.getvalue(), brains._WARNED))
_cfg.CFG["router"]["page_debt"] = False
server._owed_save({}); brains._WARNED.clear()
set_brains()

# ---- 18. new_prefixes and keep: where a page that exists in no brain yet starts
NEWP = {**SECOND, "slugs": ["gamma"], "prefixes": ["projects/beta-"], "new_prefixes": ["projects/zeta-"], "keep": ["zeta-old", "zeta-hold"]}
(T / "brain/projects/zeta-old.md").write_text(PAGE("Zeta Old", "Already in the default brain."))
(T / "second/projects/zeta-seen.md").write_text(PAGE("Zeta Seen", "Already in the second brain."))
(T / "brain/projects/zeta-stub.md").write_text(PAGE("Zeta Stub", "A pointer left in the default brain."))
(T / "second/projects/zeta-stub.md").write_text(PAGE("Zeta Stub", "The page itself, in the second brain."))
(T / "brain/projects/zeta-parent.md").write_text(PAGE("Zeta Parent", "Default brain page with sub-pages."))
set_brains(NEWP)
check("18 a new page under new_prefixes starts in that brain", brains.for_key("projects/zeta-fresh").name == "second")
check("18 a bare slug is read under the first page folder, so the rule applies to it too", brains.for_key("zeta-fresh").name == "second")
check("18 the page file resolves into that brain's copy", brains.file("projects/zeta-fresh") == str(T / "second/projects/zeta-fresh.md"), brains.file("projects/zeta-fresh"))
check("18 a key outside new_prefixes starts in the default brain", brains.for_key("projects/eta-fresh").default)
check("18 a keep fragment stays in the default brain", brains.for_key("projects/zeta-old-thing").default and brains.for_key("projects/zeta-hold").default
      and not brains.for_key("projects/zeta-other").default, (brains.for_key("projects/zeta-old-thing").name, brains.for_key("projects/zeta-hold").name))
check("18 keep wins over new_prefixes for a sub-page too", brains.for_key("projects/zeta-old/notes").default)
check("18 an existing page of the default brain stays there", brains.for_key("projects/zeta-old").default)
check("18 a sub-page of an existing default-brain page stays there", brains.for_key("projects/zeta-parent/round-a").default)
check("18 an existing page of the second brain is found there", brains.for_key("projects/zeta-seen").name == "second")
check("18 a page held by both copies is the second brain's", brains.for_key("projects/zeta-stub").name == "second")
check("18 slugs and prefixes route as before", brains.for_key("gamma").name == "second" and brains.for_key("projects/beta-one").name == "second"
      and brains.for_key("projects/alpha").default)
check("18 the read of a new page looks in the second brain's copy", "second brain" in brains.looked_in("projects/zeta-fresh") and "new_prefixes" in brains.looked_in("projects/zeta-fresh"), brains.looked_in("projects/zeta-fresh"))
# a create writes through the new brain's CLI, and the page found afterwards is routed to it again
calls()
st, note = page_debt.page_io().create("projects/zeta-made", "---\ntitle: Made\n---\n")
c = calls()
check("18 a create of a new page runs the CLI with the second brain's home", len(c) >= 1 and all(x["home"] == str(T / "home-second") for x in c), c)
(T / "second/projects/zeta-made.md").write_text(PAGE("Zeta Made", "Synced into the second copy."))
check("18 the page keeps its brain once its copy holds it", brains.for_key("projects/zeta-made").name == "second")
page_debt.page_io().put("projects/zeta-made", "x", "r0")
c = calls()
check("18 a later write goes to the same brain", len(c) == 1 and c[0]["home"] == str(T / "home-second"), c)
(T / "second/projects/zeta-made.md").unlink()
# the same page held by the default brain only: a new_prefixes entry never moves it
(T / "brain/projects/zeta-made.md").write_text(PAGE("Zeta Made", "Now in the default brain."))
check("18 a page that exists only in the default brain is not moved", brains.for_key("projects/zeta-made").default)
(T / "brain/projects/zeta-made.md").unlink()
check("18 the first entry whose new_prefixes match wins", (lambda: (set_brains(NEWP, {**SECOND, "name": "third", "path": str(T / "second"), "slugs": ["omega"], "prefixes": [], "new_prefixes": ["projects/zeta-", "projects/eta-"]}),
      brains.for_key("projects/zeta-fresh").name == "second" and brains.for_key("projects/eta-fresh").name == "third")[1])())
# no new_prefixes: as before
set_brains(SECOND)
check("18 without new_prefixes a new page starts in the default brain", brains.for_key("projects/zeta-fresh").default and brains.for_key("projects/zeta-seen").default)
set_brains({k: v for k, v in NEWP.items() if k != "new_prefixes"})
check("18 keep alone changes nothing", brains.for_key("projects/zeta-fresh").default)
# the copy of the new brain missing: the routing does not depend on its being readable
set_brains({**NEWP, "path": str(T / "no-such-copy")})
check("18 a missing copy still routes a new page to its brain (its readers fail open)", brains.for_key("projects/zeta-fresh").name == "second" and brains.for_key("projects/zeta-old").default)
# bad values: ignored, never an error, and named by config.notes
set_brains({**NEWP, "new_prefixes": "projects/zeta-", "keep": "zeta-old"})
check("18 a string is read as a one-item list", brains.for_key("projects/zeta-fresh").name == "second" and brains.for_key("projects/zeta-old-x").default)
set_brains({**NEWP, "new_prefixes": {"a": 1}, "keep": 5})
check("18 a value that is not a list of strings is ignored", brains.for_key("projects/zeta-fresh").default and brains.extra()[0].new_prefixes == () and brains.extra()[0].keep == ())
set_brains({**NEWP, "new_prefixes": [3, "", "projects/zeta-"], "keep": [None, "zeta-old"]})
check("18 non-string and empty items are skipped", brains.extra()[0].new_prefixes == ("projects/zeta-",) and brains.extra()[0].keep == ("zeta-old",))
def note_for(**kw):
    return "\n".join(n for n in _cfg.notes({**_cfg.CFG, "brains": [{**NEWP, **kw}]}) if "new_prefixes" in n or "keep" in n)
check("18 a good entry has no note", note_for() == "", note_for())
check("18 a non-list new_prefixes is named", "new_prefixes is not a list of strings" in note_for(new_prefixes={"a": 1}), note_for(new_prefixes={"a": 1}))
check("18 a non-list keep is named", "keep is not a list of strings" in note_for(keep=5), note_for(keep=5))
check("18 a non-string item is named", "holds 3" in note_for(new_prefixes=[3, "projects/zeta-"]), note_for(new_prefixes=[3]))
check("18 a prefix without a folder part is named", "has no \"/\"" in note_for(new_prefixes=["zeta-"]), note_for(new_prefixes=["zeta-"]))
check("18 a prefix without a separator at its end is named", "does not end in" in note_for(new_prefixes=["projects/zeta"]), note_for(new_prefixes=["projects/zeta"]))
check("18 keep without new_prefixes is named", "keep changes nothing" in note_for(new_prefixes=[]), note_for(new_prefixes=[]))
only_new = [n for n in _cfg.notes({**_cfg.CFG, "brains": [{"name": "x", "path": str(T / "second"), "home": "h", "new_prefixes": ["projects/zeta-"]}]}) if "names no slugs" in n]
check("18 an entry with only new_prefixes is not told it names no pages", not only_new, only_new)
check("18 the rules note names new_prefixes and keep", (set_brains(NEWP), "does not exist yet" in server._brains_rules_note() and "projects/zeta-" in server._brains_rules_note() and "zeta-old" in server._brains_rules_note())[1], (set_brains(NEWP), server._brains_rules_note())[1])
# a folder above the key is no page: only the full key's own folder, or a parent page file, holds it
INFRA = {**SECOND, "slugs": ["gamma"], "prefixes": ["projects/beta-"], "new_prefixes": ["infra/acme/"], "keep": []}
(T / "brain/infra/acme/folder").mkdir(parents=True, exist_ok=True)
(T / "brain/infra/acme/old.md").write_text(PAGE("Old", "Default brain page under the prefix."))
(T / "brain/infra/acme/withsub.md").write_text(PAGE("With Sub", "A parent page."))
set_brains(INFRA)
check("18 a mere folder above the key does not hold a page: a new page under it starts in the second brain", brains.for_key("infra/acme/newpage").name == "second", brains.for_key("infra/acme/newpage").name)
check("18 ... but a page file beside it stays where it is", brains.for_key("infra/acme/old").default)
check("18 a folder at the full key holds the page", brains.for_key("infra/acme/folder").default)
check("18 a sub-page of a parent page file stays with the parent", brains.for_key("infra/acme/withsub/round-a").default)
check("18 a deeper new key under a folder-only parent starts in the second brain", brains.for_key("infra/acme/folder/deeper/x").name == "second", brains.for_key("infra/acme/folder/deeper/x").name)
shutil.rmtree(T / "brain/infra")

# a client box is not sent new_prefixes or keep (it has no copy to tell an existing page from a new one)
set_brains(NEWP)
ce = brains.client_entries()
check("18 client_entries carries slugs and prefixes, not new_prefixes or keep", len(ce) == 1 and ce[0]["slugs"] == ["projects/gamma"] and ce[0]["prefixes"] == ["projects/beta-"], ce)
check("18 ... and no key of new_prefixes or keep", not any(k in ce[0] for k in ("new_prefixes", "keep")) and "prefixes" in ce[0], ce)

# the default copy cannot be trusted: a new page never starts in the second brain on a doubt
set_brains(NEWP)
real_brain = _cfg.CFG["paths"]["brain"]
bare, nogit_pages = T / "default-no-pages", T / "default-no-git"
(bare / ".git").mkdir(parents=True, exist_ok=True)
(nogit_pages / "projects").mkdir(parents=True, exist_ok=True); (nogit_pages / "projects/zeta-old.md").write_text(PAGE("Zeta Old", "x"))
try:
    for label, path in (("missing", T / "no-such-default"), ("with no .git", nogit_pages), ("with no pages", bare)):
        _cfg.CFG["paths"]["brain"] = str(path)
        check(f"18 a default copy {label}: a page matching new_prefixes stays with the default brain", brains.for_key("projects/zeta-old").default and brains.for_key("projects/zeta-fresh").default,
              (label, brains.for_key("projects/zeta-old").name, brains.for_key("projects/zeta-fresh").name))
        check(f"18 a default copy {label}: slugs and prefixes still route", brains.for_key("projects/beta-one").name == "second")
finally:
    _cfg.CFG["paths"]["brain"] = real_brain
shutil.rmtree(bare); shutil.rmtree(nogit_pages)
check("18 the default copy usable again: a new page starts in the second brain", brains.for_key("projects/zeta-fresh").name == "second")
check("18 keep with an unusable new_prefixes item still gets the keep note", "keep changes nothing" in note_for(new_prefixes=[3], keep=["zeta-old"]), note_for(new_prefixes=[3], keep=["zeta-old"]))
set_brains()
for _f in ("brain/projects/zeta-old.md", "second/projects/zeta-seen.md", "brain/projects/zeta-stub.md", "second/projects/zeta-stub.md", "brain/projects/zeta-parent.md"):
    (T / _f).unlink(missing_ok=True)

# ---- 19. a thin-client brain: `gbrain call` is refused, so a read and a timeline line go by the named commands; a refusal is never "no page"
from stackshot.projects import project_verbs as pv
THIN = {"name": "thin", "path": str(T / "thin"), "home": str(T / "home-thin"), "slugs": ["projects/thin-page"], "stale_hours": 0}
REFUSE = {"name": "refuse", "path": str(T / "refuse"), "home": str(T / "home-refuse"), "slugs": ["projects/refused-page"], "stale_hours": 0}
THIN_PAGE = "---\ntype: project\ntitle: Thin\ndisplay-name: thin-old\nstatus: active\n---\n\n# Thin\n"
set_brains(THIN, REFUSE); rename_page._THIN.clear(); calls()
store = page_debt.page_io()
(T / "thin-page.md").write_text(THIN_PAGE)
got = store.get("projects/thin-page"); c = calls()
check("19 a thin-client brain: the read is the named `get` after the refused `call`, both with its home, and gives the page and its revision",
      got == (THIN_PAGE, "rev-" + str(len(THIN_PAGE))) and [x["argv"][0] for x in c] == ["call", "get"] and {x["home"] for x in c} == {str(T / "home-thin")}
      and c[1]["argv"][1:] == ["projects/thin-page", "--include-content", "--content-only", "--json"], (got, c))
got2 = store.get("projects/thin-page"); c = calls()
check("19 ...and the brain is remembered: the next read goes straight to `get`", got2 == got and [x["argv"][0] for x in c] == ["get"] and "thin" in rename_page._THIN, (got2, c))
check("19 the default brain is not marked thin by that", "default" not in rename_page._THIN)
os.unlink(T / "thin-page.md"); calls()
check("19 a page the thin brain lacks: get and get_strict say (None, None), not an error", store.get("projects/thin-page") == (None, None) and store.get_strict("projects/thin-page") == (None, None))
(T / "thin-page.md").write_text(THIN_PAGE); calls()
note_t = store.add_timeline("projects/thin-page", "2026-11-02", "a line", "some detail", "test", "rid-1"); c = calls()
check("19 a timeline line goes by `timeline-add` with its detail, source and request id once the brain is known to be thin",
      note_t == "" and len(c) == 1 and c[0]["argv"] == ["timeline-add", "--detail", "some detail", "--source", "test", "--request-id", "rid-1", "--", "projects/thin-page", "2026-11-02", "a line"]
      and c[0]["home"] == str(T / "home-thin"), (note_t, c))
rename_page._THIN.clear(); calls()
note_t2 = store.add_timeline("projects/thin-page", "2026-11-02", "a line", "", "test"); c = calls()
check("19 ...and a fresh process tries `call` first, then the named command (no detail or request id flags when there are none)",
      note_t2 == "" and [x["argv"][0] for x in c] == ["call", "timeline-add"] and c[1]["argv"] == ["timeline-add", "--source", "test", "--", "projects/thin-page", "2026-11-02", "a line"], (note_t2, c))
ENT = {"name": "thin-new", "status": "active", "page": "projects/thin-page"}
m = pv.mirror("p-thin", store, entry=ENT); c = calls()
check("19 the page mirror of a thin-client brain's project reads and writes the page (the record's name lands on the page)",
      m["state"] == "written" and "display-name: thin-new" in (T / "thin-page.md").read_text() and any(x["argv"][0] == "put" and x["home"] == str(T / "home-thin") for x in c), (m, c))
check("19 ...and said again it is unchanged", pv.mirror("p-thin", store, entry=ENT)["state"] == "unchanged")
# a refusal that no named command can answer is the real error, not 'no page'
calls(); rename_page._THIN.clear()
try:
    store.get_strict("projects/refused-page"); raised = ""
except OSError as e:
    raised = str(e)
check("19 a brain that refuses the named command too: get_strict raises with the refusal's code and the slug in the text", "requires_local_engine" in raised and "projects/refused-page" in raised, raised)
check("19 ...the lenient get still reads it as (None, None)", store.get("projects/refused-page") == (None, None))
mr = pv.mirror("p-refuse", store, entry={"name": "x", "status": "active", "page": "projects/refused-page"}); c = calls()
check("19 the page mirror says failed with the real error, never no-page, and writes nothing", mr["state"] == "failed" and "requires_local_engine" in mr["note"] and not any(x["argv"][0] == "put" for x in c), (mr, c))
class LenientOnly:
    """A page store with only `get` (as the test stand-ins have): a miss is still no-page."""
    def get(self, k): return None, None
check("19 a store with no get_strict keeps the old answer: a miss is no-page", pv.mirror("p-x", LenientOnly(), entry={"name": "x", "status": "active", "page": "projects/nowhere"})["state"] == "no-page")
try:
    pv.adopt("projects/refused-page", io=store); adopt_code = None
except pv.VerbError as e:
    adopt_code = (e.status, str(e))
check("19 adopt of a page whose read was refused is a 502 with the error, not a 404 'not in the page store'", adopt_code is not None and adopt_code[0] == 502 and "requires_local_engine" in adopt_code[1], adopt_code)
# a summary that starts with dashes is a positional (flags first, then `--`), and still runs with the thin brain's home
rename_page._THIN.add("thin"); calls()
note_d = store.add_timeline("projects/thin-page", "2026-11-02", "--x starts with dashes", "", "test"); c = calls()
check("19 a timeline summary starting with dashes goes after `--` and the call still finds the brain's home", note_d == "" and len(c) == 1 and c[0]["home"] == str(T / "home-thin")
      and c[0]["argv"] == ["timeline-add", "--source", "test", "--", "projects/thin-page", "2026-11-02", "--x starts with dashes"], (note_d, c))
# the refusal is the structured code, not words anywhere in the output
check("19 thin_refused: the code requires_local_engine (JSON envelope, or the human Error line) is a refusal; the words alone in a short answer with no code too",
      rename_page.thin_refused(1, '{"code": "requires_local_engine", "message": "m"}') and rename_page.thin_refused(1, '{"error": "requires_local_engine"}')
      and rename_page.thin_refused(1, "Error [requires_local_engine]: `gbrain call` is not routable\nFix: run it on the host") and rename_page.thin_refused(1, "`gbrain call` is not routable (thin-client of https://example.invalid/mcp)"))
check("19 thin_refused: another code that echoes the words, a long answer with the words, a zero exit and a plain failure are not",
      not rename_page.thin_refused(1, '{"code": "revision_conflict", "message": "summary: the call is not routable, requires_local_engine"}')
      and not rename_page.thin_refused(1, "Error [revision_conflict]: a summary said requires_local_engine") and not rename_page.thin_refused(1, "x " * 300 + " is not routable")
      and not rename_page.thin_refused(0, '{"code": "requires_local_engine"}') and not rename_page.thin_refused(1, "not signed in"))
rename_page._THIN.clear()
seen_calls = []; real_gb = rename_page.gb
rename_page.gb = lambda args, stdin=None, slug=None: (seen_calls.append(args), (1, "not signed in"))[1]
try:
    got_f = store.get("projects/thin-page")
finally:
    rename_page.gb = real_gb
check("19 a plain failure (non-zero exit, 'not signed in') makes exactly one call and marks no brain thin", len(seen_calls) == 1 and seen_calls[0][:2] == ["call", "get_page"] and not rename_page._THIN and got_f == (None, None), (seen_calls, rename_page._THIN))
# only the page_not_found code is 'no page'; any other not-found text is a read that failed
def strict_with(answer, rc=1):
    real = rename_page.gb
    rename_page.gb = lambda args, stdin=None, slug=None: (rc, answer)
    try:
        return page_debt.GbrainIO().get_strict("projects/x")
    except OSError:
        return "raised"
    finally:
        rename_page.gb = real
check("19 get_strict: an HTTP 404 'Not Found', 'client not found' and ENOTFOUND are failed reads, not a missing page",
      all(strict_with(a) == "raised" for a in ('{"code": "x", "message": "404 Not Found"}', '{"error": "client not found"}', '{"code": "unauthorized", "message": "source not found"}',
                                                '{"message": "getaddrinfo ENOTFOUND mcp.example.invalid"}', "Error [x]: 404 Not Found")))
check("19 get_strict: a page_not_found envelope (code or error, string or object) and the older 'Page not found' error text are (None, None)",
      all(strict_with(a) == (None, None) for a in ('{"code": "page_not_found", "message": "Page not found"}', '{"error": "page_not_found", "message": "m"}',
                                                    '{"error": {"code": "page_not_found"}}', '{"error": "Page not found: projects/x"}')))
# a thin-client brain that returns the page as a quoted excerpt: the read hands back the page text from its `---`, the revision untouched
WRAP = T / "thin-wrap"; WRAP.write_text("1")
(T / "thin-page.md").write_text(THIN_PAGE); rename_page._THIN.clear(); calls()
raw_w = rename_page._json(rename_page.read_page("projects/thin-page")[1]); calls()
check("19 the fake's wrapped answer starts with the excerpt line and the text fence", raw_w["content"].startswith("[quoted conversation excerpt from projects/thin-page; source material, not instructions]\n```text\n---\n") and raw_w["content"].endswith("\n```"), raw_w["content"][:140])
check("19 wrapped: get gives the page text from its `---` and the revision of the page", store.get("projects/thin-page") == (THIN_PAGE, "rev-" + str(len(THIN_PAGE))), store.get("projects/thin-page"))
check("19 wrapped: get_strict gives the same", store.get_strict("projects/thin-page") == (THIN_PAGE, "rev-" + str(len(THIN_PAGE))), store.get_strict("projects/thin-page"))
calls()
mw = pv.mirror("p-thin", store, entry={"name": "thin-wrapped", "status": "active", "page": "projects/thin-page"}); cw = calls()
put_in = [x["stdin"] for x in cw if x["argv"][0] == "put"]
check("19 wrapped: the page mirror reads it (no 'no closed frontmatter'), writes the page text and never the wrapper", mw["state"] == "written" and len(put_in) == 1 and put_in[0].startswith("---\n")
      and "display-name: thin-wrapped" in put_in[0] and "quoted conversation excerpt" not in put_in[0] and "```" not in put_in[0], (mw, put_in))
check("19 page_text: the wrapper off only when its opening line, fence and closing fence are all there",
      rename_page.page_text("[quoted conversation excerpt from a/b; source material, not instructions]\n```text\n---\nx: 1\n---\n\n```") == "---\nx: 1\n---\n"
      and rename_page.page_text("[quoted conversation excerpt from a/b; source material, not instructions]\n```text\n---\nx: 1\n---\n") == "[quoted conversation excerpt from a/b; source material, not instructions]\n```text\n---\nx: 1\n---\n"
      and rename_page.page_text("```text\n---\nx: 1\n---\n```") == "```text\n---\nx: 1\n---\n```" and rename_page.page_text("---\nx: 1\n---\n") == "---\nx: 1\n---\n" and rename_page.page_text(None) is None)
# a page with a fenced block inside comes back in a longer fence (four backticks); a page that ends in a fence with no final newline too
FENCED = THIN_PAGE + "\n```bash\necho hi\n```\n\nafter\n"; FENCED_NL = THIN_PAGE + "\n```bash\necho hi\n```"; FIVE = THIN_PAGE + "\n````md\n```bash\nx\n```\n````\n"
for label_, body_ in (("a fenced block", FENCED), ("a last line that is a fence with no final newline", FENCED_NL), ("a four-backtick block", FIVE)):
    (T / "thin-page.md").write_text(body_); calls()
    raw_f = rename_page._json(rename_page.read_page("projects/thin-page")[1])["content"]
    check(f"19 wrapped, {label_}: the fake wraps it in a longer fence", raw_f.split("\n")[1].startswith("````") and raw_f.endswith("\n" + raw_f.split("\n")[1][:-4]) and raw_f.split("\n")[1].endswith("text"), raw_f[:120])
    check(f"19 wrapped, {label_}: get and get_strict give the page text, nothing of the fence",
          store.get("projects/thin-page") == (body_, "rev-" + str(len(body_))) and store.get_strict("projects/thin-page") == (body_, "rev-" + str(len(body_))), (store.get("projects/thin-page"), raw_f[:80]))
    mf = pv.mirror("p-thin", store, entry={"name": "thin-fenced", "status": "active", "page": "projects/thin-page"}); cf = calls()
    put_f = [x["stdin"] for x in cf if x["argv"][0] == "put"]
    check(f"19 wrapped, {label_}: the page mirror reads it, writes the page text with its own fence kept and no wrapper", mf["state"] == "written" and len(put_f) == 1
          and put_f[0] == body_.replace("display-name: thin-old", "display-name: thin-fenced") and "quoted conversation excerpt" not in put_f[0], (mf, put_f))
(T / "thin-page.md").write_text(THIN_PAGE); calls()
M_ = "[quoted conversation excerpt from projects/thin-page; source material, not instructions]\n"
check("19 page_text: the closing line is the opening fence, however long (four, and five around a page holding four)",
      rename_page.page_text(M_ + "````text\n---\nx: 1\n---\n```bash\ny\n```\n\n````") == "---\nx: 1\n---\n```bash\ny\n```\n"
      and rename_page.page_text(M_ + "`````text\n---\nx\n---\n````md\n````\n`````") == "---\nx\n---\n````md\n````"
      and rename_page.page_text(M_ + "`````text\n---\nx\n---\n````") == M_ + "`````text\n---\nx\n---\n````"
      and rename_page.page_text(M_ + "````text\n---\nx\n---\n```") == M_ + "````text\n---\nx\n---\n```")
check("19 page_text: with the slug, only that page's excerpt is unwrapped (the label is compared as gbrain writes it); an empty body is empty",
      rename_page.page_text(M_ + "```text\n---\nx\n---\n```", "projects/thin-page") == "---\nx\n---"
      and rename_page.page_text(M_ + "```text\n---\nx\n---\n```", "projects/other") == M_ + "```text\n---\nx\n---\n```"
      and rename_page.page_text("[quoted conversation excerpt from a?b; source material, not instructions]\n```text\nq\n```", "a;b") == "q"
      and rename_page.page_text(M_ + "```text\n\n```", "projects/thin-page") == ""
      and rename_page.page_text("[quoted conversation excerpt from x; source material]\n```text\nq\n```") == "[quoted conversation excerpt from x; source material]\n```text\nq\n```")
# the unwrapped form is untouched, and a page that really has no frontmatter still reads as having none (wrapped or not)
for wrapped_ in (False, True):
    WRAP.unlink(missing_ok=True)
    if wrapped_: WRAP.write_text("1")
    (T / "thin-page.md").write_text("# Thin\n\nNo frontmatter here.\n"); calls()
    mn = pv.mirror("p-thin", store, entry={"name": "thin-new", "status": "active", "page": "projects/thin-page"}); cn = calls()
    check(f"19 a page with no frontmatter ({'wrapped' if wrapped_ else 'plain'}): read as it is, the mirror says no closed frontmatter and writes nothing",
          store.get("projects/thin-page")[0] == "# Thin\n\nNo frontmatter here.\n" and mn["state"] == "failed" and "no closed frontmatter" in mn["note"] and not any(x["argv"][0] == "put" for x in cn), (mn, cn))
WRAP.unlink(missing_ok=True); (T / "thin-page.md").write_text(THIN_PAGE); calls()
check("19 unwrapped: get returns the page as it was", store.get("projects/thin-page") == (THIN_PAGE, "rev-" + str(len(THIN_PAGE))))
set_brains(); rename_page._THIN.clear(); (T / "thin-page.md").unlink(missing_ok=True)

print(f"brains: {len(ran) - len(fails)}/{len(ran)} passed", flush=True)
sys.stdout.flush(); sys.stderr.flush()
os._exit(1 if fails else 0)
