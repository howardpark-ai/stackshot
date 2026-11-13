"""Scenario test for next by writer (Tue Oct 27th 2026) — fixture data, no live store, no network, no server socket.

An item's `next` used to be one list that every update(next=...) replaced, so two sessions with lines on one item wiped each other's. Now every line
remembers its writer (the session whose update wrote it, kept in metadata.next_by beside the unchanged metadata.next text; nextlines.py):

  * update(next=…) replaces only the sender's own lines, in the place of the first of them (at the end when it had none); other writers' lines stay
  * next="none" removes only the sender's lines; an empty next is "not passed"; clear_next=true wipes every line, and with next given sets the sender's after
  * a line stored before this change has no writer and is the keeper of record's (resolved when read, written on the next save that touches next)
  * a line that names another session, written by me, is mine: the writer is the sender, not the name the line starts with
  * create's lines are the creator's (the keeper of record's); a close clears next and the writers; a reopen's next is the reopener's
  * get shows the lines exactly as before, no writer; a text with one writer is stored verbatim
  * the pieces of nextlines.py: split (a fenced block and indented lines stay with their line), carry (the migration's write), lift_first (the ask lifted out of next)

    tests/run-suite next_writer        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="nextwritertest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about whose lines are in next, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
MAIN, GEN, ENG = "falcon-main", "heron-engineer", "falcon-engineer"
NAMES = (MAIN, GEN, ENG)
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/example.md").write_text("---\ntype: project\ntitle: Stackshot\ndisplay-name: falcon\nagents:\n  falcon-main: builds it\n---\n\n# x\n", encoding="utf-8")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import nextlines as NL; from stackshot.model import ids as _model_ids
from stackshot.service import handoff as handoff_svc
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
server._cfg.CFG.setdefault("model", {})["guards"] = False      # fixture sessions the guards would judge; the write guards have their own suite
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
STK = "projects/example"
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
def create(next, sender=MAIN, **kw):
    r = _wt_create.stackshot_create(subject="[home] a thing", description=DESC, project=STK, sender=sender, next=next, **kw)
    return _model_ids._norm_id(r.split()[1])
def upd(gid, sender, **kw): return server._update(gid, sender=sender, **kw)
def rd(gid): return json.loads(server._path(gid).read_text())
def nx(gid): return rd(gid)["metadata"].get("next")
def who(gid):
    m = rd(gid)["metadata"]
    names = {u: n for n, u in U.items()}
    return [names.get(w, w) for w in NL.writers_of(m, m.get("owner") or "")]
def lines(gid): return (nx(gid) or "").splitlines()
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except server.ToolError as e:
        check(name, all(w in str(e) for w in want), str(e))

# ================================================================ create: the lines are the creator's
K1 = f"{MAIN}: decide the shape"
g = create(K1)
check("create: next is stored as given", nx(g) == K1, nx(g))
check("create: the writer is the creator, the keeper of record", who(g) == [MAIN], who(g))
check("create: the pair holds the canonical id, not the name", rd(g)["metadata"]["next_by"][0][0] == U[MAIN], rd(g)["metadata"].get("next_by"))
refused("create with no next is refused for a session (N6)", lambda: create(""), "has no open step in next")
g_none = _model_ids._norm_id(_wt_create._create(subject="[home] a thing", description=DESC, project=STK, owner=MAIN).split()[1])     # the server's own write is not judged
check("create with no next stores neither next nor next_by", "next" not in rd(g_none)["metadata"] and "next_by" not in rd(g_none)["metadata"], rd(g_none)["metadata"])

# ================================================================ two senders each keep their lines
A1, B1 = f"{GEN}: build batch 2", f"{ENG}: release it"
upd(g, GEN, next=A1)
check("a second sender's next is added after the keeper's line, not instead of it", lines(g) == [K1, A1], nx(g))
upd(g, ENG, next=B1)
check("a third sender's line is added too: each keeps theirs", lines(g) == [K1, A1, B1], nx(g))
check("…and the writers are the three senders", who(g) == [MAIN, GEN, ENG], who(g))

# ================================================================ a sender replacing its own lines keeps order and position
A1b, A1c = f"{GEN}: build batch 2, part a", f"{GEN}: build batch 2, part b"
upd(g, GEN, next=f"{A1b}\n{A1c}")
check("replacing my lines puts the new ones where mine stood, the others untouched", lines(g) == [K1, A1b, A1c, B1], nx(g))
K1b = f"{MAIN}: decided"
upd(g, MAIN, next=K1b)
check("the keeper replacing its line keeps the first place", lines(g) == [K1b, A1b, A1c, B1], nx(g))
upd(g, ENG, next=f"{ENG}: release it now")
check("the last writer replacing its line keeps the last place", lines(g)[-1] == f"{ENG}: release it now" and len(lines(g)) == 4, nx(g))
upd(g, GEN, next=f"{GEN}: one line")
check("two of my lines replaced by one: it takes the place of the first", lines(g) == [K1b, f"{GEN}: one line", f"{ENG}: release it now"], nx(g))
check("…and the writers follow the lines", who(g) == [MAIN, GEN, ENG], who(g))

# ================================================================ an empty next removes nothing; "none" removes only the sender's lines
before = nx(g)
upd(g, GEN, description="- Goal: A thing\n- It lives here\n- Done when different")
check("an empty next is next not passed: an update of the description leaves every line", nx(g) == before, nx(g))
upd(g, GEN, next="none")
check('next="none" removes only the sender\'s lines', lines(g) == [K1b, f"{ENG}: release it now"], nx(g))
check("…and their writers", who(g) == [MAIN, ENG], who(g))
upd(g, GEN, next="none")
check('next="none" from a sender with no lines changes nothing', lines(g) == [K1b, f"{ENG}: release it now"], nx(g))
upd(g, ENG, next="clear")
check('next="clear" is the same as "none"', lines(g) == [K1b], nx(g))
upd(g, MAIN, next="-")
check('removing the last line leaves no next and no next_by', "next" not in rd(g)["metadata"] and "next_by" not in rd(g)["metadata"], rd(g)["metadata"])

# ================================================================ clear_next wipes all
g2 = create(K1)
upd(g2, GEN, next=A1); upd(g2, ENG, next=B1)
check("fixture: three writers", lines(g2) == [K1, A1, B1], nx(g2))
upd(g2, ENG, clear_next=True)
check("clear_next wipes every line, whoever wrote it", "next" not in rd(g2)["metadata"] and "next_by" not in rd(g2)["metadata"], rd(g2)["metadata"])

# ================================================================ clear_next with next: clear first, then the sender's lines
upd(g2, MAIN, next=K1)
upd(g2, GEN, next=A1)
upd(g2, ENG, clear_next=True, next=B1)
check("clear_next with next: everything is wiped, then the sender's lines are set", lines(g2) == [B1], nx(g2))
check("…and they are the sender's", who(g2) == [ENG], who(g2))
upd(g2, GEN, next=A1)
check("…and the next sender adds beside them", lines(g2) == [B1, A1], nx(g2))

# ================================================================ legacy lines with no writer belong to the keeper
LEG1, LEG2 = f"{MAIN}: old one", f"{GEN}: old two (the keeper wrote this line naming {GEN})"
nowt = time.time() - 86400
leg = {"id": "40", "subject": "[home] old", "description": DESC, "status": "open", "updated": nowt, "state_updated": nowt, "confirmed": nowt,
       "metadata": {"owner": U[MAIN], "project": STK, "next": f"{LEG1}\n{LEG2}"}}
def legacy():
    (T / "store/a/40.json").write_text(json.dumps(leg))
legacy()
gl = "a40"
check("legacy: lines with no pair read as the keeper's", who(gl) == [MAIN, MAIN], who(gl))
upd(gl, GEN, next=A1)
check("legacy: another session's next leaves the legacy lines alone", lines(gl) == [LEG1, LEG2, A1], nx(gl))
check("legacy: …and the save writes the writer of every line (the keeper's, then the sender's)", who(gl) == [MAIN, MAIN, GEN] and len(rd(gl)["metadata"]["next_by"]) == 3, rd(gl)["metadata"].get("next_by"))
upd(gl, GEN, next=f"{GEN}: again")
check("legacy: a line that names me but was written by the keeper is not mine to replace", lines(gl) == [LEG1, LEG2, f"{GEN}: again"], nx(gl))
upd(gl, MAIN, next=f"{MAIN}: new one")
check("legacy: the keeper replaces its legacy lines (as one block) and the other sender's stay", lines(gl) == [f"{MAIN}: new one", f"{GEN}: again"], nx(gl))
legacy()
upd(gl, MAIN, next="none")
check('legacy: the keeper\'s next="none" removes its legacy lines', "next" not in rd(gl)["metadata"], rd(gl)["metadata"])
legacy()
upd(gl, ENG, clear_next=True)
check("legacy: clear_next from any sender wipes legacy lines too", "next" not in rd(gl)["metadata"], rd(gl)["metadata"])
legacy()
upd(gl, ENG, next=B1)
upd(gl, ENG, next="none")
check("legacy: a sender who only added a line and removes it leaves the legacy lines as they were", lines(gl) == [LEG1, LEG2], nx(gl))

# ================================================================ a line naming another session, written by me, is mine
g4 = create(K1)
upd(g4, GEN, next=f"{MAIN}: please review (this line is the engineer's)")
check("a line that names the keeper, written by the engineer, is the engineer's", who(g4) == [MAIN, GEN], who(g4))
upd(g4, MAIN, next=f"{MAIN}: second line of mine")
check("…so the keeper's replacement leaves it", lines(g4) == [f"{MAIN}: second line of mine", f"{MAIN}: please review (this line is the engineer's)"], nx(g4))
upd(g4, GEN, next=f"{GEN}: done reviewing")
check("…and the engineer's replacement takes it", lines(g4) == [f"{MAIN}: second line of mine", f"{GEN}: done reviewing"], nx(g4))
upd(g4, U[GEN], next=f"{GEN}: by id")
check("the sender by transcript id is the same writer as by name", lines(g4) == [f"{MAIN}: second line of mine", f"{GEN}: by id"], nx(g4))

# ================================================================ a write with no sender is the keeper's
g5 = create(K1)
upd(g5, GEN, next=A1)
server._update(g5, next=f"{MAIN}: server-side")
check("a write that names no sender is the keeper of record's: it replaces the keeper's line", lines(g5) == [f"{MAIN}: server-side", A1], nx(g5))

# ================================================================ close and reopen
g6 = create(K1)
upd(g6, GEN, next=A1)
upd(g6, GEN, status="completed", outcome="done", reason="finished", description="- Goal: A thing\n- Done")
m6 = rd(g6)["metadata"]
check("a close (update) clears next and the writers", "next" not in m6 and "next_by" not in m6, m6)
upd(g6, ENG, status="open", next=B1)
check("reopen: the new next is the reopener's", lines(g6) == [B1] and who(g6) == [ENG], (nx(g6), who(g6)))
_wt_complete.stackshot_complete(g6, outcome="done", reason="finished", description="- Goal: A thing\n- Done a second time", sender=ENG)
check("the complete tool clears them too", "next_by" not in rd(g6)["metadata"] and "next" not in rd(g6)["metadata"], rd(g6)["metadata"])

# ================================================================ get is unchanged
g7 = create(K1)
upd(g7, GEN, next=A1)
got = _wt_get.stackshot_get(g7)
check("get shows the lines as one list, as before", f"next:\n{K1}\n{A1}" in got, got[-400:])
check("…with no writer shown: the text after `next:` is the lines and nothing else", "next_by" not in got and got.split("next:\n", 1)[1].strip() == f"{K1}\n{A1}" and U[GEN] not in got, got[-400:])
g8 = create("  - home-x: indented bullet\n\n  - home-y: another\n")
check("a text with one writer is stored exactly as written (blank lines, indents, trailing newline)", nx(g8) == "  - home-x: indented bullet\n\n  - home-y: another\n", repr(nx(g8)))
upd(g8, MAIN, next="  - home-z: replaced\n")
check("…and a replacement by that writer too", nx(g8) == "  - home-z: replaced\n", repr(nx(g8)))

# the form gates still judge what is written
refused("a next line over the limit is still refused", lambda: upd(g7, GEN, next=f"{GEN}: " + "word " * 80), "a line of next is")
check("…and the refused write changed nothing", lines(g7) == [K1, A1], nx(g7))

# ================================================================ the pieces of nextlines
fence = f"{GEN}: run this\n```\nline one\n\nline two\n```\nnext line\n{ENG}: x\n  indented under x\n(a server note)"
check("split: a fenced block (a blank line inside it too) stays with its line; a top-level line starts a new one; indented and note lines stay",
      NL.split(fence) == [f"{GEN}: run this\n```\nline one\n\nline two\n```", "next line", f"{ENG}: x\n  indented under x\n(a server note)"], NL.split(fence))
check("split: empty and blank texts have no lines", NL.split("") == [] and NL.split(" \n\n") == [] and NL.split(None) == [])
eq = lambda x, y: x == y
m = {"owner": "K"}
NL.write(m, "a: 1\nb: 2", "w1", "K", eq)
NL.write(m, "c: 3", "w2", "K", eq)
NL.write(m, "a: 1 edited", "w1", "K", eq)
check("write: three writes, two writers: each writer's lines are replaced in their place", m["next"] == "a: 1 edited\nc: 3" and NL.writers_of(m, "K") == ["w1", "w2"], m)
m = {"owner": "K"}
NL.write(m, "same: line", "w1", "K", eq)
merged = NL.write(m, "same: line", "w2", "K", eq)
check("write: a line another writer's open line already reads is not added a second time: it stays the first writer's, and the write says so", NL.writers_of(m, "K") == ["w1"] and m["next"] == "same: line" and merged == [("same: line", "w1")], (m, merged))
merged = NL.write(m, "- **same: line**\nw2: more", "w2", "K", eq)
check("write: …a list marker, bold marks and spacing do not make another line; the sender's other lines are added", m["next"] == "same: line\nw2: more" and NL.writers_of(m, "K") == ["w1", "w2"] and len(merged) == 1, (m, merged))
NL.write(m, "same: line\nsame: line", "w1", "K", eq)
check("write: a writer's own copies of a line stay its own, as many as it writes (no collapse)", m["next"].count("same: line") == 2 and NL.writers_of(m, "K").count("w1") == 2, m)
m2 = {"owner": "K", "next": "x: 1\ny: 2\nz: 3", "next_by": [["w1", NL.key_of("x: 1")], ["w2", NL.key_of("y: 2")], ["w3", NL.key_of("z: 3")]]}
m2["next"] = "x: 1\nz: 3"          # a write that takes a line out without knowing writers (the ask lifted out of next)
check("resolve: a line is found by its text, so taking one out leaves the others' writers right", NL.writers_of(m2, "K") == ["w1", "w3"], NL.writers_of(m2, "K"))
old = {"owner": "K", "next": "x: 1\ny: 2", "next_by": [["w1", NL.key_of("x: 1")], ["w2", NL.key_of("y: 2")]]}
new = {"owner": "K", "next": "w1: x: 1\nw2: y: 2", "next_by": old["next_by"]}      # the migration named the lines
NL.carry(old, new, "K")
check("carry: lines renamed by a write that knows no writers keep theirs by position", NL.writers_of(new, "K") == ["w1", "w2"] and new["next_by"][0][1] == NL.key_of("w1: x: 1"), new)
new2 = {"owner": "K", "next": "only one"}
NL.carry(old, new2, "K")
check("carry: a different count falls back to the keeper", NL.writers_of(new2, "K") == ["K"], new2)

ASK = "Decide: a thing · Recommend: yes · Stakes: none · By: no date"
# the ask lifted out of next (a client with no ask parameter): only within the sender's own lines, with the lines under it, the others' writers right
mk = {"owner": "K", "needs": ["decision"]}
NL.write(mk, ASK, "w1", "K", eq)
NL.write(mk, "w2: do it", "w2", "K", eq)
server._lift_ask(mk, refresh=True)
check("_lift_ask (no writer): the ask line leaves next, the line after it stays with its writer", mk.get("ask", "").startswith("Decide:") and mk["next"] == "w2: do it" and NL.writers_of(mk, "K") == ["w2"] and len(mk["next_by"]) == 1, mk)
mk = {"owner": "K", "needs": ["decision"]}
NL.write(mk, ASK, "K", "K", eq)
NL.write(mk, "w2: do it", "w2", "K", eq)
out = server._lift_ask(mk, refresh=True, writer="w2", keeper="K")
check("_lift_ask: another writer's ask-shaped head is not the sender's line: nothing is lifted", out == "" and "ask" not in mk and mk["next"] == f"{ASK}\nw2: do it", (out, mk))
mk = {"owner": "K", "needs": ["decision"]}
NL.write(mk, "K: first", "K", "K", eq)
NL.write(mk, f"{ASK}\n  and a detail under it\nw2: do it", "w2", "K", eq)
NL.write(mk, "w3: last", "w3", "K", eq)
out = server._lift_ask(mk, refresh=True, writer="w2", keeper="K")
check("_lift_ask: the sender's own ask line is lifted from the middle of next, its indented line with it", mk.get("ask") == ASK and "and a detail" not in mk["next"], (out, mk))
check("…the sender's next line stays, and the others' writers are right", mk["next"] == "K: first\nw2: do it\nw3: last" and NL.writers_of(mk, "K") == ["K", "w2", "w3"], mk)
mk = {"owner": "K", "needs": ["decision"]}
NL.write(mk, ASK, "w1", "K", eq)
NL.write(mk, ASK, "w2", "K", eq)
server._lift_ask(mk, refresh=True, writer="w2", keeper="K")
check("_lift_ask: two identical lines of two writers: the pair of the line taken out goes, the other's stays", mk.get("next") == ASK and NL.writers_of(mk, "K") == ["w1"], mk)

# a first line that would glue onto another writer's entry is refused, and nothing is stored
GL = "  waiting until Friday for X"
before = (nx(g4), rd(g4)["metadata"].get("next_by"))
refused("glue: an indented first line after another session's line is refused", lambda: upd(g4, ENG, next=f"{GL}\n{ENG}: step"), "next must start with a line naming who takes the step")
refused("glue: …so is a parenthesised one", lambda: upd(g4, ENG, next="(a note)\nx: y"), "next must start with a line naming")
refused("glue: …and a fenced one", lambda: upd(g4, ENG, next="```\nrm -rf x\n```"), "next must start with a line naming")
check("glue: …and nothing was stored", (nx(g4), rd(g4)["metadata"].get("next_by")) == before, (nx(g4), before))
server._cfg.CFG["model"]["guards"] = True
refused("glue: with the guards on, the wait-word line cannot slip past them behind another writer's entry", lambda: upd(g4, ENG, next=f"{GL}\n{ENG}: step"), "next must start with a line naming")
server._cfg.CFG["model"]["guards"] = False
upd(g_none, ENG, next=f"{GL}\n{ENG}: step")
check("glue: the same text is fine when nothing stands above it (it is the first entry)", nx(g_none) == f"{GL}\n{ENG}: step", nx(g_none))
mg = {"owner": "K"}
NL.write(mg, "a: 1", "w1", "K", eq)
try:
    NL.write(mg, "```\nfoo\n```", "w2", "K", eq); ok_ = False
except NL.NextFormError:
    ok_ = True
check("write: lines that would not read back as the same lines raise before anything is stored", ok_ and mg["next"] == "a: 1" and NL.writers_of(mg, "K") == ["w1"], mg)

# server-written lines (the cold call, a script) are the keeper's, which a session can replace
gc = create(K1)
upd(gc, GEN, next=A1)
upd(gc, server._ho.COLD, next=f"{server.OWNER}: answer the ask on the item", clear_next=True)
check("cold call: its line is stored with the keeper as the writer, not 'cold-call'", who(gc) == [MAIN] and nx(gc) == f"{server.OWNER}: answer the ask on the item", (nx(gc), who(gc), rd(gc)["metadata"].get("next_by")))
upd(gc, MAIN, next=f"{MAIN}: his answer is in, carry on")
check("cold call: …so the keeper's next replaces it and it does not outlive his answer", lines(gc) == [f"{MAIN}: his answer is in, carry on"], nx(gc))
upd(gc, GEN, next=A1)
upd(gc, "a script on testbox", next=f"{MAIN}: from a script")
check("a script's line is the keeper's too", who(gc) == [MAIN, GEN] and lines(gc)[0] == f"{MAIN}: from a script", (nx(gc), who(gc)))

# a line with no writer at write time: the keeper's when there is one, else any sender's to replace
me = {"owner": "K", "next": "x: 1", "next_by": [["", NL.key_of("x: 1")]]}
NL.write(me, "w1: mine", "w1", "K", eq)
check("empty writer with a keeper: the line goes to the keeper, and another sender leaves it", NL.writers_of(me, "K") == ["K", "w1"] and me["next"] == "x: 1\nw1: mine", me)
me = {"owner": "", "next": "x: 1"}
NL.write(me, "w1: mine", "w1", "", eq)
check("empty writer and no keeper: any sender's write replaces it", me["next"] == "w1: mine" and NL.writers_of(me, "") == ["w1"], me)

# the owner-change notice: the line set, or that lines were removed, never someone else's head line
told = []
_tw = telling.tell_woken
telling.tell_woken = lambda gid, to, line, tag="wake": told.append((to, line))
gn = create(f"{ENG}: keeper line", sender=GEN)
upd(gn, GEN, mover=ENG)      # the notice goes to the item's mover alone
upd(gn, MAIN, next=f"{MAIN}: my line")
check("notice: a session setting a line is reported with that line, not the head of the list", any(f"set next: {MAIN}: my line" in l for _, l in told), told)
told.clear(); telling.OWNER_HEARD.clear()      # one notice per item per window
upd(gn, MAIN, next="none")
check("notice: removing its own lines says so and quotes no one's line", any("removed their next lines" in l for _, l in told) and not any("set next:" in l for _, l in told), told)
told.clear(); telling.OWNER_HEARD.clear()      # one notice per item per window
upd(gn, MAIN, next=f"{ENG}: keeper line")
check("notice: setting a line identical to another session's says nothing about next", not any("set next:" in l for _, l in told), told)
telling.tell_woken = _tw

# the migration's own write: a nameless line given a name keeps its writer
gm = _model_ids._norm_id(_wt_create._create(subject="[home] a thing", description=DESC, project=STK, owner=MAIN, next="nameless line").split()[1])     # a line stored before N1: only the server's own write can make one now
upd(gm, GEN, next=f"{GEN}: second")
it = server._load(gm)
res = server._migrate_one({"item": gm, "set": {"next": f"{MAIN}: nameless line\n{GEN}: second"}, "drop": [], "expect": it["updated"], "expect_sig": server._migrate_sig(gm, it), "kind": "named"})
check("migration: the apply goes through", res.get("action") == "set", res)
check("migration: the lines it named keep their writers", lines(gm) == [f"{MAIN}: nameless line", f"{GEN}: second"] and who(gm) == [MAIN, GEN], (nx(gm), who(gm)))

# the write guards on next's text judge the lines the write set, not lines another session wrote
server._cfg.CFG["model"]["guards"] = True
nowt = time.time() - 86400
(T / "store/a/41.json").write_text(json.dumps({"id": "41", "subject": "[home] old", "description": DESC, "status": "open", "updated": nowt, "state_updated": nowt, "confirmed": nowt,
                                              "metadata": {"owner": U[MAIN], "project": STK, "next": "do the thing (an unnamed line stored before the guard)"}}))
upd("a41", GEN, next=f"{MAIN}: a named line by the engineer")
check("guards: a session's valid line is not refused for the keeper's old nameless line beside it", lines("a41") == ["do the thing (an unnamed line stored before the guard)", f"{MAIN}: a named line by the engineer"], nx("a41"))
refused("guards: …but a nameless line of the sender's own is still refused", lambda: _wt_update.stackshot_update("a41", sender=GEN, next="a nameless line of mine"), "names no one")
check("…and the refused write changed nothing", len(lines("a41")) == 2 and who("a41") == [MAIN, GEN], (nx("a41"), who("a41")))
server._cfg.CFG["model"]["guards"] = False

# a notice quotes the line the writer wrote, not the head of lines others wrote
mn = {"owner": U[MAIN], "next": f"{MAIN}: head line"}
NL.write(mn, f"{GEN}: the engineer's line", U[GEN], U[MAIN], handoff_svc.ho_same)
check("next_head: the writer's own first line when it wrote one", telling.next_head(mn, GEN) == f"{GEN}: the engineer's line", telling.next_head(mn, GEN))
check("next_head: the head of the list for a session with no line, or none named", telling.next_head(mn, ENG) == f"{MAIN}: head line" and telling.next_head(mn, "") == f"{MAIN}: head line")

# ================================================================ the tool text says it
tools = {t.name: t for t in __import__("asyncio").run(server.mcp.list_tools())}
TOOLS = {n: t.description or "" for n, t in tools.items()}
check("update: the description says next replaces only your own lines and clear_next wipes all", "next replaces only your own lines" in TOOLS["update"] and "clear_next=true wipes every line" in TOOLS["update"], TOOLS["update"][:200])
check("update: clear_next is a parameter", "clear_next" in tools["update"].parameters["properties"], list(tools["update"].parameters["properties"])[-5:])
check("create: the description says each line remembers its writer", "remembers the session whose write put it there" in TOOLS["create"])
check("the connector's instructions say an update replaces only your own lines", "replaces only your own lines of next" in server.mcp.instructions)
check("no tool text still says next replaces the list", not any(re.search(r"next[^.]{0,40}replaces the (whole )?list", t) for t in TOOLS.values()) and "next replaces the whole" not in server.mcp.instructions)

print(("ok" if not fails else "FAILED") + f": next_writer scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
