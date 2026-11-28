"""Scenario test for notices on a board of several members: each notice reaches the member it is for.

Covers: a due-date row of an item a second member moves is stored with that member's name (the first member's rows carry no name, so a
board of one writes the rows it always wrote) and is posted once, through that member's own `slack_command` (a member with none falls
back to the shared `[for_you] slack_command`), never through another member's; a second pass posts nothing again; the member a row is for
(a decision: the member it asks; else the item's mover; else the session a member's `agents` lists; else the item's member); the mark
of a notice (`[for <name>]`) is the member's, the held-wait reader knows every member's mark; a GitHub login belongs to one member (a
duplicate in any letter case, or a second member writing the first member's `[github] owner_login`, is a problem with a line of its own).

    tests/run-suite notices_members        → exit 0 / 1"""
import datetime as dt, json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="noticesmembers-"); T = pathlib.Path(tmp)
REC = T / "recorded.jsonl"
for name in ("oliver", "dana", "shared"):
    (T / f"rec-{name}.py").write_text(f"import sys, json\nopen({str(REC)!r}, 'a').write(json.dumps({{'via': {name!r}, 'text': sys.stdin.read()}}) + '\\n')\n")
toml = _instance.set_person(_instance.apply(_instance.base_toml()))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^ui_open = true', 'ui_open = false'),
                 (r'(?m)^slack_command = ""', f'slack_command = "{sys.executable} {T}/rec-shared.py"'),
                 (r"(?m)^require_marks = true", "require_marks = false")):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
MEMBERS = (f'\n[[members]]\nname = "Oliver"\nslack_command = "{sys.executable} {T}/rec-oliver.py"\n'
           f'\n[[members]]\nname = "Dana"\ngithub = "Dana-GH"\nagents = ["dana-main"]\nslack_command = "{sys.executable} {T}/rec-dana.py"\n'
           '\n[[members]]\nname = "Eli"\n')
(T / "stackshot.toml").write_text(toml + MEMBERS, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state", "secrets", "touch", "repo", "brain/projects"): (T / d).mkdir(parents=True)
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text("{}")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []
def check(name, cond, got=None):
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
now0 = time.time()
DESC = "- A thing\n- It lives here\n- Finished when it works"
SAID = [{"tag": "Acked-by", "quote": "go ahead", "msg": "m1", "session": "s1", "ts": 1.0, "checked": True}]
ASK = "Decide: whether to ship · Recommend: yes · Stakes: none either way · By: no date"
ZONE = dt.timezone(dt.timedelta(hours=4))
def due(days=0): return (dt.datetime.fromtimestamp(now0, ZONE) + dt.timedelta(days=days)).strftime("%Y-%m-%d")
def item(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": "open", "updated": now0 - 3600,
                                                       "state_updated": now0 - 3600, "confirmed": now0 - 3600, "metadata": {"said": SAID, **meta}}))
item(1, owner="Oliver", mover="Oliver", due=due(), needs=["decision"], ask=ASK)
item(2, owner="Dana", mover="Dana", due=due(), needs=["decision"], ask=ASK, ask_by="Dana")
item(3, owner="Eli", mover="Eli", due=due(), needs=["decision"], ask=ASK, ask_by="Eli")
item(4, owner="Dana", mover="dana-main")
item(5, owner="Oliver", mover="Oliver")

from stackshot.web import server    # noqa: F401  (its import installs the For you hooks)
from stackshot.core import members as M
from stackshot.service import foryou as fy, foryou_events as fyev, foryou_slack as fyslack, telling
from stackshot.waits import held, waiting
from stackshot.service.store import _load

check("three members are built", [p.name for p in M.members()] == ["Oliver", "Dana", "Eli"], [p.name for p in M.members()])
check("a member's github login and slack command are read", M.person_of("Dana").github == "Dana-GH" and M.person_of("Dana").slack_command.endswith("rec-dana.py"))
check("a login finds its member in any letter case", M.person_of_login("dana-gh").name == "Dana" and M.person_of_login("nobody") is None)
check("a mark is [for <name>]", M.for_mark(M.person_of("Dana")) == "[for Dana]" and M.mark_in("x\n[for Dana] hi") == "[for Dana]" and M.mark_in("hi") == "")
check("a session in `agents` is its member's", M.agent_member("dana-main").name == "Dana" and M.agent_member("osprey") is None)

check("item_member: the mover's member", fyev.item_member(_load("a2")).name == "Dana", fyev.item_member(_load("a2")).name)
check("item_member: a decision asks its member", fyev.item_member(_load("a3"), "decision").name == "Eli")
check("item_member: a session's member (`agents`)", fyev.item_member(_load("a4")).name == "Dana")
check("a first member's row is stored without a name", fyev._row_member(_load("a5"), "due") == "" and fyev._row_member(_load("a2"), "due") == "Dana")
check("a notice's mark is the member's", telling._mark_of(_load("a2")) == "[for Dana]" and telling._mark_of(_load("a5")) == "[for Oliver]", (telling._mark_of(_load("a2")), telling._mark_of(_load("a5"))))

end = waiting.due_epoch(due())
fyev._FORYOU_LAST[0] = 0.0
made = fyev._foryou_tick(end - 10 * 3600); fyslack._foryou_slack_wait()
rec = [json.loads(l) for l in REC.read_text().splitlines()] if REC.exists() else []
rows = [r for r in fy.rows() if r.get("kind") == "due"]
check("each due row is posted once, through its member's command (an Eli row falls back to the shared one)", sorted(r["via"] for r in rec) == ["dana", "oliver", "shared"], ([r["via"] for r in rec], made))
check("a row of the first member carries no member; the others do", len(rows) == 3 and all(("member" in r) == (r["gid"] != "a1") for r in rows), rows)
fyev._FORYOU_LAST[0] = 0.0; fyev._foryou_tick(end - 10 * 3600 + 3600); fyslack._foryou_slack_wait()
check("a second pass posts nothing again", len(REC.read_text().splitlines()) == len(rec), len(REC.read_text().splitlines()))

check("held reads every member's mark", all(held._owner_mark().search(f"{m} please") for m in ("[for Oliver]", "[for Dana]", "[for Eli]")) and not held._owner_mark().search("please"))

for label, members, want in (("duplicate login", [{"name": "A", "github": "X"}, {"name": "B", "github": "x"}], "already entry 1"),
                             ("login not text", [{"name": "A", "github": 5}], "github is not text")):
    got = M.problems({"members": members}); check(f"problems: {label}", any(want in p for p in got), got)
got = M.problems({"members": [{"name": "A"}, {"name": "B", "github": "Owner-Login"}], "github": {"owner_login": "owner-login"}})
check("a second member cannot write the first member's [github] owner_login", len(got) == 1 and "owner_login" in got[0], got)
check("one member: a login is no problem", M.problems({"members": [{"name": "A", "github": "x"}]}) == [])

print(("FAIL " + ", ".join(fails)) if fails else "ok notices_members"); sys.exit(1 if fails else 0)
