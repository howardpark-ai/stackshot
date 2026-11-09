"""Scenario test for the gate that refuses a needs=decision item whose ask names alternatives while it lists no options (server._gate_alternatives,
server._lettered_alternatives) — fixture data, no live store, no network, no server process (the server module is imported and called in-process, on a temporary config).

Without options the item page draws a bare Yes / No for the ask, which is wrong for a pick between alternatives. The gate already read keywords ("which of the two", "pick one",
"Option A") and a list ("x, y or z", "x vs y"); it missed labeled choices in the Decide part: "A or B", "A (full height, as now) or B (starts below the cards)", "A: … or B: …". This covers, on create and on update:

  - refused, nothing written: the exact shape "Decide: which way the side panel's left line runs, A (full height, as now) or B (starts below the cards) · Recommend: A · Stakes: … · By: …",
    "vendor A or B", "A or B for the build", "B or C", "A / B", "A vs B", the colon form, a pair inside a chain ("D or A or B", "C or B or D"); the refusal says to put each alternative in as one option and gives the option form;
  - accepted: the same asks with options listed; a plain yes/no ("Decide: ship it? · Recommend: yes …", "whether to take vendor A"), one letter alone ("plan A"), lowercase "a or b" and the
    article ("a new column or the old one"), "merge now or later" (an "or" between unlabeled words), quoted words ("accept "yes" or "no" in the form field?"), letters out of order ("B or A"), a letter inside a word or a code ("A/B test", "Q3 or B2"),
    an item that needs no decision with the same words;
  - an update that writes such an ask without options is refused and leaves the ask unchanged; with options in the same call it is accepted; clearing the options under such an ask is refused.

    tests/run-suite lettered_alternatives        → exit 0 / 1"""
import os, re, sys, pathlib, logging, json
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="letteredalt-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
NAMES = ("home-kiwi", "home-kiwi-main", "home-kiwi-engineer")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/kiwi.md").write_text("---\ntype: project\ntitle: Kiwi\ndisplay-name: home-kiwi\nagents:\n  home-kiwi-main: talks to the owner\n"
                                           "  background:\n    home-kiwi-engineer: builds and merges\nstatus: active\n---\n\n# x\n", encoding="utf-8")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.web import server
server._publish = lambda: None
DESC = "- Goal: The side panel's left line\n- It lives in the board's stylesheet\n- Done when the line is picked"
ASKB = lambda decide, rec="yes": f"Decide: {decide} · Recommend: {rec} · Stakes: the panel looks different · By: no date"
LABELS = [{"label": "A", "line": "Full height, as now.", "recommended": True}, {"label": "B", "line": "Starts below the cards.", "recommended": False}]
def items():
    return sorted(p_.stem for d in (T / "store").iterdir() if d.is_dir() for p_ in d.glob("*.json") if p_.stem.isdigit() and p_.stem != "1")
def create(**kw):
    a = dict(subject="[home] Pick the side panel line", description=DESC, project="projects/kiwi", sender="home-kiwi-engineer", then="home-kiwi-engineer", needs=["decision"], ask=ASKB("whether to ship"))
    a.update(kw)
    try: return server.stackshot_create(**a), ""
    except server.ToolError as e: return "", str(e)
def gid_of(out):
    m = re.search(r"\b[a-z]\d+\b", out); assert m, out
    return m.group(0)
def stored(gid): return json.loads((T / "store" / gid[0] / f"{gid[1:]}.json").read_text())
def update(gid, **kw):
    try: return server.stackshot_update(item_id=gid, sender="home-kiwi-engineer", **kw), ""
    except server.ToolError as e: return "", str(e)
def says_options(e): return e.startswith("Refused: this needs=decision item names alternatives (") and "lists no options" in e and "Put each alternative in as one option" in e and '"recommended": true' in e and "Yes / No" in e

EXACT = "which way the side panel's left line runs, A (full height, as now) or B (starts below the cards)"
REFUSED = {"the exact shape (A (…) or B (…) after a which-way question)": ASKB(EXACT), "vendor A or B": ASKB("vendor A or B"), "A or B for the build": ASKB("A or B for the build"),
           "B or C": ASKB("pick B or C", "B"), "A / B": ASKB("A / B for the header"), "A vs B": ASKB("A vs B for the header"), "the colon form": ASKB("A: a wider column, or B: a narrower one"),
           "a pair in the middle of a chain (D or A or B)": ASKB("D or A or B for the header"), "a pair at the end of a chain (C or B or D)": ASKB("C or B or D for the header", "B"),
           "a nested parenthesis": ASKB("which way: A (full height (as now)) or B (below the cards)")}
ACCEPTED = {"a plain yes/no question": "Decide: ship it? · Recommend: yes · Stakes: a day · By: no date", "whether to": ASKB("whether to take vendor A"), "one letter alone": ASKB("whether plan A goes ahead"),
            "lowercase a or b": ASKB("a or b"), "the article": ASKB("a new column or the old one"), "an or between unlabeled words": ASKB("merge now or later"),
            "letters out of order": ASKB("B or A"), "A/B test": ASKB("ship the A/B test", "yes"), "a code, not a pair": ASKB("Q3 or B2 as the target date"), "a pair of words": ASKB("keep Alpha or Beta"),
            "quoted words (TODO or FIXME)": ASKB('treat "TODO" or "FIXME" comments as failures?', "yes"), "quoted words (yes or no)": ASKB('accept "yes" or "no" in the form field?', "yes"),
            "curly-quoted words": ASKB("keep “Alpha” or “Beta” as the name"), "a chain with no pair in order (D or C or B)": ASKB("D or C or B")}

# ---- 1. create: refused without options, nothing written
for name, a_ in REFUSED.items():
    before = items(); out, e = create(ask=a_)
    check(f"create refused: {name}", says_options(e) and items() == before, e or out)
out, e = create(ask=ASKB(EXACT))
check("…the exact shape's refusal quotes the pair it found and gives the option form", "“A (full height, as now) or B”" in e and "options=[" in e and "exactly one recommended" in e, e)
# ---- 2. create: accepted with options, and the plain asks without
for name, a_ in REFUSED.items():
    out, e = create(ask=a_, options=LABELS)
    check(f"create accepted with options: {name}", "created" in out and not e, e or out)
for name, a_ in ACCEPTED.items():
    out, e = create(ask=a_)
    check(f"create accepted without options: {name}", "created" in out and not e, e or out)
out, e = create(needs=[], ask=None, next="home-kiwi-engineer: carry on", description="- Goal: A or B\n- It lives here\n- Done when picked")
check("create accepted: an item that needs no decision with A or B in its text", "created" in out and not e, e or out)
# ---- 3. update
g = gid_of(create(ask=ASKB("whether to ship"))[0]); ask0 = stored(g)["metadata"]["ask"]
out, e = update(g, ask=ASKB(EXACT))
check("update refused: the exact shape, no options; the ask is unchanged", says_options(e) and stored(g)["metadata"]["ask"] == ask0, e or out)
out, e = update(g, ask=ASKB(EXACT), options=LABELS)
check("update accepted: the same ask with options in the same call", not e and stored(g)["metadata"]["ask"] == ASKB(EXACT) and len(stored(g)["metadata"]["options"]) == 2, e or out)
out, e = update(g, options="none")
check("update refused: clearing the options while the ask names the pair", says_options(e) and len(stored(g)["metadata"]["options"]) == 2, e or out)
out, e = update(g, ask=ASKB("whether to ship it"), options="none")
check("update accepted: a yes/no ask with the options cleared", not e and "options" not in stored(g)["metadata"], e or out)
# ---- 4. the text the tools teach names the new shape
check("the text of options in the ask names labeled choices", "labeled choices in the Decide part" in server._ITEM_FORM, server._ITEM_FORM[-300:])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
