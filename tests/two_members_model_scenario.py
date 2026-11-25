"""Scenario test for the model's reading of a board with more than one member (stage 5, the read side): made-up data, a temp folder, no live store, no network.

A probe process loads a one-member config and then puts a list of two members where `members.members()` reads it
(the cache a changed config rebuilds); everything below it is the code a two-member board runs.

Covers, for two members (Pat with the alias PJ, Sam with the alias SM):
  * the item's member (model.item_person): the member its stored mover names, else the one a line of its next opens with, else the first member; owner_display and norm_who give that member's own name
    (an alias becomes its member's name, never the first member's);
  * the default mover of a decision, a your-call or a your-step is the item's member (model._defaults, waiting.mover_of), and the mover kind stays the generic word;
  * the step the server makes is the item's member's (owner_steps.line_of): a text that opens with a member keeps that member, any other text gets the item's member; two lines are one step only for one member
    (steps.owner_key, owner_steps.same_line), and a line stored with a member's name twice reads it once (steps.collapse_owner);
  * states.next_names_owner names the member a line opens with;
  * with ONE member every one of those answers is what it was: the first member's name.
Also the review lows of the members table: a name's doubled spaces are collapsed once (person_of, opener_person, names and the uniqueness check agree), a value that is no text is told in words (text, number,
table, list), an address written more than twice in one entry is told once, and doctor shows every removed-value line of config.py.

    tests/run-suite two_members_model        -> exit 0 / 1"""
import json, os, pathlib, re, subprocess, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="s5-two-members-"); T = pathlib.Path(tmp)
fails = []; ran = []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))


BASE = _instance.base_toml()
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"), ("state", f"{tmp}/state"),
                 ("secrets", f"{tmp}/secrets"), ("session_links", f"{tmp}/sala"), ("project_touch", f"{tmp}/touch")):
    BASE, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', BASE); assert n == 1, key
CONFIG = T / "stackshot.toml"
CONFIG.write_text(_instance.set_person(BASE, "Pat"), encoding="utf-8")        # one member: Pat; the probe adds the second where the list is read


def run(code, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("STACKSHOT_") and k not in ("BOARD_MCP_CONFIG", "BOARD_MCP_AUTH")}
    env.update(STACKSHOT_CONFIG=str(CONFIG), HOME=str(T / "home"), PYTHONDONTWRITEBYTECODE="1", STACKSHOT_PROC_NET=str(T / "procnet-none"))
    r = subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, env=env, cwd=STACK, timeout=120)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]), r
    except Exception:
        return None, r


PROBE = r"""
import json, sys
from stackshot.core import members
from stackshot.model import model, owner_steps, states, steps
from stackshot.waits import waiting
two = sys.argv[1] == "two"
if two:
    members._seen = (members._inputs(None), [members.Person("Pat", ("PJ",), ("pat@example.com",)), members.Person("Sam", ("SM",), ("sam@example.com",))])
P = {"mover": "Sam"}
out = {
    "persons": [p.name for p in members.members()],
    "item_person": {
        "none": model.item_person(None).name,
        "mover_alias": model.item_person({"mover": "sm"}).name,
        "mover_session_next_sam": model.item_person({"mover": "home-agent", "next": "home-agent: go\nSM: decide"}).name,
        "next_only": model.item_person({"next": "- Sam: pick one"}).name,
        "next_you": model.item_person({"next": "you: pick one"}).name,
        "nothing": model.item_person({"next": "home-agent: build"}).name,
    },
    "display": [model.owner_display(), model.owner_display(P), model.owner_display({"next": "SM: x"})],
    "norm": [model.norm_who("sm"), model.norm_who("PJ"), model.norm_who("  pat "), model.norm_who("home-agent"), model.norm_who("Sam")],
    "defaults": [list(model._defaults({"needs": ["decision"], "next": "Sam: pick"}, "doing")), list(model._defaults({"needs": ["decision"], "mover": "Sam"}, "doing")),
                 list(model._defaults({}, "your-step")), list(model._defaults({"needs": ["home-agent"], "next": "SM: pick"}, "doing"))],
    "mover_of": [waiting.mover_of({"needs": ["decision"], "mover": "SM"}), waiting.mover_of({"needs": ["decision"], "next": "Sam: pick"}), waiting.mover_of({"needs": ["decision"]})],
    "line_of": [owner_steps.line_of("check it"), owner_steps.line_of("check it", P), owner_steps.line_of("PJ: check it", P), owner_steps.line_of("sm: check it"),
                owner_steps.line_of("you: check it", P)],
    "same": [owner_steps.same_line("Sam: x", "SM: x"), owner_steps.same_line("Pat: x", "Sam: x"), owner_steps.same_line("Pat: x", "PJ: x"), owner_steps.same_line("Sam: Sam: x", "SM: x")],
    "key": [steps.owner_key("SM: do it"), steps.owner_key("Pat: do it"), steps.owner_key("home-agent: do it")],
    "collapse": [steps.collapse_owner("Sam: sm: x"), steps.collapse_owner("Pat: x"), steps.collapse_owner("SM: Sam: x")],
    "names_owner": [states.next_names_owner("SM: go"), states.next_names_owner("PJ: go"), states.next_names_owner("home-agent: go"), states.next_names_owner("Sam to review it")],
}
print(json.dumps(out))
"""
one, r = run(PROBE, "one")
check("the probe runs on a one-member config", one is not None, r.stderr[-600:])
two, r = run(PROBE, "two")
check("the probe runs on a list of two", two is not None, r.stderr[-600:])
if one and two:
    check("the two lists are Pat; Pat and Sam", one["persons"] == ["Pat"] and two["persons"] == ["Pat", "Sam"], (one["persons"], two["persons"]))
    ip = two["item_person"]
    check("item_person: the stored mover's member, an alias too", ip["mover_alias"] == "Sam", ip)
    check("…else the member a line of next opens with, past a session's line and a session mover", ip["mover_session_next_sam"] == "Sam" and ip["next_only"] == "Sam", ip)
    check("…else the first member (no item, `you:`, no member named)", ip["none"] == "Pat" and ip["next_you"] == "Pat" and ip["nothing"] == "Pat", ip)
    check("owner_display is the item's member; with no item the first", two["display"] == ["Pat", "Sam", "Sam"], two["display"])
    check("norm_who: an alias is its own member's name, a session stays as written", two["norm"] == ["Sam", "Pat", "Pat", "home-agent", "Sam"], two["norm"])
    check("the default mover of a decision, a your-step and a decision named by its next is the item's member",
          two["defaults"] == [["Sam", ""], ["Sam", ""], ["Pat", ""], ["home-agent", "home-agent"]], two["defaults"])
    check("mover_of: a decision's mover is the item's member and its kind the generic word",
          two["mover_of"] == [{"kind": "owner", "who": "Sam"}, {"kind": "owner", "who": "Sam"}, {"kind": "owner", "who": "Pat"}], two["mover_of"])
    check("the server's step is the item's member's; a text that opens with a member keeps that member",
          two["line_of"] == ["Pat: check it", "Sam: check it", "Pat: check it", "Sam: check it", "Sam: you: check it"], two["line_of"])
    check("two lines are one step only for one member", two["same"] == [True, False, True, True], two["same"])
    check("owner_key writes the opener as its member's name", two["key"] == ["Sam: do it", "Pat: do it", "home-agent: do it"], two["key"])
    check("collapse_owner keeps the member the line opens with", two["collapse"] == ["Sam: x", "Pat: x", "Sam: x"], two["collapse"])
    check("next_names_owner names the member the line opens with", two["names_owner"] == ["Sam", "Pat", "", "Sam"], two["names_owner"])
    # one member: everything is the first member's, as it was
    check("one member: every answer is the member's name", one["display"] == ["Pat"] * 3 and one["norm"] == ["sm", "PJ", "Pat", "home-agent", "Sam"], (one["display"], one["norm"]))
    check("one member: defaults, mover_of, the server's step and the keys read as before",
          one["defaults"][0] == ["Pat", ""] and one["defaults"][2] == ["Pat", ""] and one["mover_of"][0] == {"kind": "owner", "who": "Pat"}
          and one["line_of"][:2] == ["Pat: check it", "Pat: check it"] and one["key"] == ["SM: do it", "Pat: do it", "home-agent: do it"], one)
    check("one member: an unknown name is no member (`SM:` is a session's name here)", one["names_owner"][:2] == ["", ""], one["names_owner"])

# ---- the review lows of the members table
LOWS = r"""
import json
from stackshot.core import members
from stackshot import cli
def probe(listed):
    cfg = {"members": listed}
    return {"problems": members.problems(cfg), "built": [[p.name, list(p.aliases)] for p in members.build(cfg)]}
spaced = [{"name": "Pat   Lee", "aliases": ["P  J"]}]
members._seen = (members._inputs(None), members.build({"members": spaced}))
out = {
    "spaced": probe(spaced),
    "person_of": [members.person_of("Pat Lee").name if members.person_of("Pat Lee") else None, members.person_of("pat    lee").name if members.person_of("pat    lee") else None,
                  members.person_of("p j").name if members.person_of("p j") else None],
    "opener": [members.opener_person("Pat Lee: go").name if members.opener_person("Pat Lee: go") else None, members.opener_person("P J: go").name if members.opener_person("P J: go") else None],
    "names": members.names(), "cf": sorted(members.names_cf()),
    "clash": probe([{"name": "Pat  Lee"}, {"name": "pat lee"}])["problems"],
    "words": [probe([{"name": 5}])["problems"], probe([{"name": "Pat", "aliases": [{}]}])["problems"], probe([{"name": "Pat", "emails": "a@example.com"}])["problems"],
              probe([{"name": "Pat", "aliases": [1.5]}])["problems"], probe([{"name": "Pat", "emails": [True]}])["problems"]],
    "thrice": probe([{"name": "Pat", "emails": ["x@example.com", "x@example.com", "x@example.com", "y@example.com"]}])["problems"],
    "removed": [cli.config_refusals_only(e) for e in (
        ['[a] b = "x" in /f.toml: removed; "y" is the one value left (what) — set b = "y" or drop the line'],
        ['[a] b = "x" in /f.toml: removed; "y" is the one value left (what) — set b = "y" or drop the line', '[c] d = "x" in /f.toml: removed; "z" is the one value left (what) — set d = "z" or drop the line'],
        ['[a] b = "x" in /f.toml: removed; "y" is the one value left (what) — set b = "y" or drop the line', '[[members]] entry 1 has no name'],
        ['[a] b = "x" in /f.toml: removed; "y" is the one value left (what) — set b = "y" or drop the line', 'KeyError: "x"'], ["Traceback (most recent call last):"], [])],
}
print(json.dumps(out))
"""
low, r = run(LOWS)
check("the lows probe runs", low is not None, r.stderr[-600:])
if low:
    check("a name and an alias with doubled spaces are collapsed once, in build", low["spaced"]["built"] == [["Pat Lee", ["P J"]]], low["spaced"])
    check("person_of, opener_person, names and names_cf agree on the collapsed words", low["person_of"] == ["Pat Lee"] * 2 + ["Pat Lee"] and low["opener"] == ["Pat Lee", "Pat Lee"]
          and low["names"] == ["Pat Lee", "P J"] and low["cf"] == ["p j", "pat lee"], low)
    check("two names that differ only in spacing or case clash", any("already the name or an alias of entry 1" in l and "pat lee" in l for l in low["clash"]), low["clash"])
    words = [w[0] for w in low["words"]]
    check("a value that is no text is told in words, not Python type names", all(not re.search(r"\((int|float|bool|dict|list|str)\)", w) for w in words) and "(a number)" in words[0] and "(a table)" in words[1]
          and "(a list)" not in words[1] and "(a list)" not in words[2] and "(a number)" in words[3] and "(true or false)" in words[4], words)
    check("…and an emails that is a string says it is no list and is text", "emails is not a list (text)" in words[2], words[2])
    check("an address written three times in one entry is told once, as `in its emails`", low["thrice"] == ['[[members]] entry 1: the address "x@example.com" is written twice in its emails (keep it once)'], low["thrice"])
    check("doctor shows every line when each is a removed-value line or a [[members]] one, and the last line otherwise",
          low["removed"] == [True, True, True, False, False, False], low["removed"])

# ---- the write side: the tools in-process, on a real list of two members and on a list of one
WRITE = r"""
import json, logging, os, pathlib, re, subprocess, sys, time
tmp, label = sys.argv[1], sys.argv[2]
T = pathlib.Path(tmp)
now = time.time()
for d in ("store/a", "fleet/a", "state", "brain/projects", "secrets"): (T / d).mkdir(parents=True, exist_ok=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({"00000000-0000-4000-8000-000000000002": {"name": "home-agent", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-agent", "status": "active", "board": [], "board_open": 0}}}))
for i in range(1, 12):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "- Goal: A thing, finished when it works", "status": "open", "updated": now - 3600,
        "state_updated": now - 3600, "confirmed": now - 3600, "metadata": {"owner": "00000000-0000-4000-8000-000000000001", "project": "projects/alpha", "needs": ["home-agent"], "next": "home-agent: build it"}}))
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
sh = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
sh("init", "-q"); sh("add", "-A"); sh("commit", "-q", "-m", "fixture")
sys.path.insert(0, os.getcwd()); logging.disable(logging.INFO)
from fastmcp.exceptions import ToolError
from stackshot.core import members
from stackshot.web import publish as _web_publish, page_debts as _web_page_debts, server
from stackshot.web.tools import anchors as _wa, route as _wr, update as _wu, create as _wc, text as _text
from stackshot.service import telling
_web_publish._publish = _wa._publish = _wr._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda *a, **k: None
ASK = "Decide: whether to ship it now · Recommend: ship · Stakes: a day either way · By: no date"
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True}]
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def call(f, *a, **k):
    try:
        f(*a, **k); return "ok"
    except ToolError as e:
        return "refused: " + str(e)
def upd(i, **k): return call(_wu.stackshot_update, f"a{i}", sender="home-agent", **k)
DESC = "- Goal: A thing, finished when it works"
out = {"persons": [p.name for p in members.members()]}
out["decision_no_member"] = upd(1, needs="decision", ask=ASK, options=OPTS)
out["decision_member"] = upd(2, needs="decision", ask=ASK, options=OPTS, mover="SM")
out["steps_2"] = rd(2)["metadata"].get("next", "").splitlines()
out["mover_2"] = rd(2)["metadata"].get("mover")
out["you_line"] = upd(3, next="home-agent: build it\nyou: look at the result")
out["step_no_member"] = upd(4, step="check that the box answers and say so")
out["step_member"] = upd(5, step="Sam: check that the box answers and say so")
out["step_5_next"] = rd(5)["metadata"].get("next", "")
out["ask_beside_other_step"] = upd(6, step="Pat: check that the box answers and say so", needs="decision", ask=ASK, options=OPTS, mover="Sam")
out["ask_beside_same_step"] = upd(7, step="Sam: check that the box answers and say so", needs="decision", ask=ASK, options=OPTS, mover="Sam")
out["plain"] = upd(8, next="home-agent: build it, then test it")
out["create_no_member"] = call(_wc.stackshot_create, subject="[home] decide the thing", description=DESC, project="projects/alpha", needs="decision", ask=ASK, options=OPTS, next="home-agent: build it", sender="home-agent")
out["create_member"] = call(_wc.stackshot_create, subject="[home] decide the thing", description=DESC, project="projects/alpha", needs="decision", ask=ASK, options=OPTS, next="home-agent: build it", mover="Sam", sender="home-agent")
for k, who in (("sender_first", "Pat"), ("sender_second", "Sam"), ("sender_alias", "sm"), ("sender_session", "home-agent")):
    out[k] = call(_wu.stackshot_update, "a9", sender=who, next="home-agent: build it, again")
out["note_text"] = _text._MEMBERS_NOTE
out["in_tool_text"] = "several members" in " ".join(str(getattr(t, "description", "")) for t in server.mcp._tool_manager._tools.values()) if hasattr(server.mcp, "_tool_manager") else None
print(json.dumps(out))
"""


def write_side(label, members_toml):
    d = T / label; d.mkdir()
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1)
    for key, val in (("repo", d), ("store", f"{d}/store"), ("markdown", f"{d}/board.md"), ("brain", f"{d}/brain"), ("state", f"{d}/state"), ("secrets", f"{d}/secrets"), ("project_touch", f"{d}/touch"),
                     ("rules", f"{d}/RULES.md")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml = _instance.set_person(toml, "Pat")
    board = "https://board.example.org"
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{board}"'), (r'(?m)^base_url = "[^"]*"', f'base_url = "{board}"'),
                     (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^sync = false', 'sync = true'), (r'(?m)^issues_repo = ""', 'issues_repo = "o/r"'),
                     (r'(?m)^api_url = "[^"]*"', 'api_url = "http://127.0.0.1:9"'), (r'(?m)^token_file = ""', f'token_file = "{d}/github.token"')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (d / "github.token").write_text("test-token\n")
    (d / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    (d / "stackshot.toml").write_text(toml.rstrip("\n") + "\n" + members_toml, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("STACKSHOT_") and k not in ("BOARD_MCP_CONFIG", "BOARD_MCP_AUTH")}
    env.update(STACKSHOT_CONFIG=str(d / "stackshot.toml"), STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{d}/fleet", HOME=str(d / "home"), PYTHONDONTWRITEBYTECODE="1", STACKSHOT_PROC_NET=str(d / "procnet-none"))
    r = subprocess.run([sys.executable, "-c", WRITE, str(d), label], capture_output=True, text=True, env=env, cwd=STACK, timeout=600)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]), r
    except Exception:
        return None, r


TWO = '\n[[members]]\nname = "Pat"\naliases = ["PJ"]\nemails = ["pat@example.com"]\n\n[[members]]\nname = "Sam"\naliases = ["SM"]\nemails = ["sam@example.com"]\n'
ONE = '\n[[members]]\nname = "Pat"\naliases = ["PJ"]\nemails = ["pat@example.com"]\n'
w2, r = write_side("two", TWO)
check("a config of two members starts, and the tools run on it", w2 is not None and w2["persons"] == ["Pat", "Sam"], (r.stderr[-900:], r.stdout[-300:]))
w1, r = write_side("one", ONE)
check("a config of one member runs the same calls", w1 is not None and w1["persons"] == ["Pat"], (r.stderr[-900:], r.stdout[-300:]))
if w2 and w1:
    R = lambda v: v.startswith("refused: ")
    check("two members: a decision that names no member is refused, naming the members", R(w2["decision_no_member"]) and "Pat, Sam" in w2["decision_no_member"] and "names none" in w2["decision_no_member"], w2["decision_no_member"])
    check("two members: a decision with `mover=` an alias goes through, stored as the member's name, with the member's own step",
          w2["decision_member"] == "ok" and w2["mover_2"] == "Sam" and any(l.startswith("Sam: ") for l in w2["steps_2"]) and not any(l.startswith("Pat: ") for l in w2["steps_2"]), w2)
    check("two members: a `you:` line is refused and says it names no member", R(w2["you_line"]) and "names no member" in w2["you_line"] and "Pat, Sam" in w2["you_line"], w2["you_line"])
    check("two members: a step that opens with no member is refused; one that opens with a member is taken and is that member's",
          R(w2["step_no_member"]) and w2["step_member"] == "ok" and "Sam: check that the box answers" in w2["step_5_next"], (w2["step_no_member"], w2["step_member"], w2["step_5_next"]))
    check("two members: an ask beside a step of another member is refused; beside a step of the same member it goes through",
          R(w2["ask_beside_other_step"]) and "different members" in w2["ask_beside_other_step"] and w2["ask_beside_same_step"] == "ok", (w2["ask_beside_other_step"], w2["ask_beside_same_step"]))
    check("two members: a create for a decision is held to the same: refused with no member, taken with one", R(w2["create_no_member"]) and w2["create_member"] == "ok", (w2["create_no_member"], w2["create_member"]))
    check("two members: a write that leaves nobody waiting is not held", w2["plain"] == "ok", w2["plain"])
    check("two members: no session may send as either member (an alias stays a free sender name, as it was); a session may", R(w2["sender_first"]) and R(w2["sender_second"]) and w2["sender_alias"] == "ok" and "Sam" in w2["sender_second"]
          and w2["sender_session"] == "ok", (w2["sender_first"], w2["sender_second"], w2["sender_alias"], w2["sender_session"]))
    check("two members: the tool text lists the members", "several members (Pat, Sam)" in w2["note_text"] and "mover=<member>" in w2["note_text"], w2["note_text"])
    check("one member: a decision, a step and a `you:` line need no name and are taken as ever",
          w1["decision_no_member"] == "ok" and w1["step_no_member"] == "ok" and w1["you_line"] == "ok" and w1["create_no_member"] == "ok", w1)
    check("one member: no session may send as the member, and the tool text says nothing of members", R(w1["sender_first"]) and w1["sender_session"] == "ok" and w1["note_text"] == "", (w1["sender_first"], w1["note_text"]))


print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
