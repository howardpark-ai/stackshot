"""Scenario test for the one reader of the members (stackshot/core/members.py) — made-up config files, a fresh process for each read, no store, no network.

Covers, for each way a config can name its members:
  * `[[members]]` set: the list is the members (name, aliases, several sign-in addresses for one person); the old keys beside it are not read for a person, and the start says so;
  * only the old keys (`[instance] owner`, `owner_aliases`, `[auth] allowed_emails`): one person, the aliases cleaned (no empty one, no repeat, never the name or `you`), every address that person's;
  * neither: one person called "the owner" with no alias and no address, a line of next opened by the word `the owner:` is no opener, `you:` is, and the start warns;
  * the answers: `person_of` (a name or an alias, any case, white space collapsed), `person_of_email` (the address as written: a different case is another address), `opener_person`,
    `names`, `names_cf`, `emails`, and the thin wrappers config.owner(), owner_aliases(), owner_names(), owner_opener_rx() and model.is_owner() / model_guards.owner_names_cf() that answer through it;
  * an alias written as a mover is the person: the same answer as the name (model.is_owner);
  * a list that is refused (at the start, by a reload that keeps the running config, and by `doctor`): a duplicate name or alias without regard to case, a duplicate address, an entry with no name,
    a value that is no list of tables, and a list of more than one member (this version serves one), and the table's first name `[[people]]` (no longer read);
  * the members are as restart-only as the keys they replace: a reload that changes the list keeps the running one.

    tests/run-suite members_config      -> exit 0 / 1"""
import json, os, pathlib, re, socket, subprocess, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="members-"); T = pathlib.Path(tmp)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

MORE_THAN_ONE = "[[members]] lists more than one member: this version serves one, so keep one entry"
BASE = _instance.base_toml()
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"), ("state", f"{tmp}/state"),
                 ("secrets", f"{tmp}/secrets"), ("session_links", f"{tmp}/sala"), ("project_touch", f"{tmp}/touch")):
    BASE, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', BASE); assert n == 1, key
BASE, n = re.subn(r'(?m)^base_url = "[^"]*"', 'base_url = "http://127.0.0.1:9"', BASE); assert n == 1       # doctor's reachability checks go nowhere
with socket.socket() as _s:
    _s.bind(("127.0.0.1", 0)); FREE_PORT = _s.getsockname()[1]
BASE, n = re.subn(r"(?m)^port = 8020", f"port = {FREE_PORT}", BASE); assert n == 1
(T / "secrets").mkdir(); (T / "secrets/oauth.env").write_text("", encoding="utf-8")        # a server box to doctor: it has an oauth.env (empty)


def toml_list(xs) -> str:
    return json.dumps(list(xs), ensure_ascii=False)


def config(label, owner=None, aliases=None, emails=None, members=()):
    """A config file under the run's folder: the example config with the old keys set as given (None: as the example has them), then one [[members]] table per dict of `members`."""
    text = BASE
    if owner:
        text = _instance.set_person(text, owner)                                   # the one place a suite names the person
    for key, val in (("owner", "" if owner == "" else None), ("owner_aliases", aliases), ("allowed_emails", emails)):
        if val is None:
            continue
        rendered = json.dumps(val, ensure_ascii=False) if isinstance(val, str) else toml_list(val)
        text, n = re.subn(rf"(?m)^{key} = .*$", lambda m: f"{key} = {rendered}", text, count=1); assert n == 1, key
    for p in members:
        text += "\n[[members]]\n" + "".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in p.items())
    path = T / f"{label}.toml"
    path.write_text(text, encoding="utf-8")
    return path


def env_for(path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("STACKSHOT_") and k not in ("BOARD_MCP_CONFIG", "BOARD_MCP_AUTH")}
    env.update(STACKSHOT_CONFIG=str(path), HOME=str(T / "home"), PYTHONDONTWRITEBYTECODE="1", STACKSHOT_PROC_NET=str(T / "procnet-none"))
    return env


def run(path, code, *args):
    return subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, env=env_for(path), cwd=STACK, timeout=120)


REPORT = r"""
import json, sys
from stackshot.core import config, members
from stackshot.model import model, model_guards
probes = json.loads(sys.argv[1]); mails = json.loads(sys.argv[2]); lines = json.loads(sys.argv[3])
def name(p): return p.name if p else None
print(json.dumps({
    "members": [[p.name, list(p.aliases), list(p.emails), p.declared] for p in members.members()],
    "owner": config.owner(), "aliases": config.owner_aliases(), "names": members.names(), "owner_names": config.owner_names(), "cf": sorted(members.names_cf()),
    "guards_cf": sorted(model_guards.owner_names_cf()), "emails": members.emails(), "openers": config.owner_openers(),
    "of": {t: name(members.person_of(t)) for t in probes}, "is_owner": {t: model.is_owner(t) for t in probes},
    "mail": {m: name(members.person_of_email(m)) for m in mails},
    "line": {l: [name(members.opener_person(l)), bool(config.owner_opener_rx().match(l)), bool(config.owner_opener_rx(False).match(l))] for l in lines},
    "notes": config.notes(), "first": members.first().name,
}))
"""


def report(path, probes=(), mails=(), lines=()):
    r = run(path, REPORT, json.dumps(list(probes)), json.dumps(list(mails)), json.dumps(list(lines)))
    if r.returncode != 0:
        return None, r
    return json.loads(r.stdout.strip().splitlines()[-1]), r


PROBES = ["Pat", "pat", "  PAT ", "PJ", "pj", "パット", "Alex", "AE", "you", "You", "the owner", "Lee", "", "Pat Lee"]
MAILS = ["pat@example.com", "pat2@example.com", "PAT@example.com", "Pat@Example.com", "a@example.com", "you@example.com", ""]
LINES = ["Pat: take it", "pj: lowercase alias", "PJ: take it", "パット: 別の行", "Pat to review it", "PJ to review it", "you: take it", "You: take it", "YOU: shouted", "the owner: x",
         "the owner's step", "Alex: take it", "AE: take it", "Lee: take it", "ACME-1: x", "Pat approved it"]
PAT = {"name": "Pat", "aliases": ["PJ", "パット", "pat", "you", " ", "Pat"], "emails": ["pat@example.com", "pat2@example.com"]}

# ---- 1. [[members]] set: the list is the members
d, r = report(config("list", emails=[], members=[PAT]), PROBES, MAILS, LINES)
check("a [[members]] list of one loads", d is not None, r.stderr[-600:])
if d:
    check("the person is the entry: name, the aliases cleaned (no empty, no repeat, never the name as written or `you`; a name in another case stays, as it always did), both addresses, declared",
          d["members"] == [["Pat", ["PJ", "パット", "pat"], ["pat@example.com", "pat2@example.com"], True]], d["members"])
    check("config.owner() is the first person's name, owner_aliases() its aliases, owner_names() the name then the aliases", d["owner"] == "Pat" and d["aliases"] == ["PJ", "パット", "pat"] and d["owner_names"] == ["Pat", "PJ", "パット", "pat"] and d["first"] == "Pat", d)
    check("person_of: the name and an alias in any case and with white space around, nothing else (no `you`, no other name, no empty text, no longer name)",
          d["of"] == {"Pat": "Pat", "pat": "Pat", "  PAT ": "Pat", "PJ": "Pat", "pj": "Pat", "パット": "Pat", "Alex": None, "AE": None, "you": None, "You": None, "the owner": None, "Lee": None, "": None, "Pat Lee": None}, d["of"])
    check("an alias written as a mover is the person, as the name is (model.is_owner)", d["is_owner"] == {t: (v is not None) for t, v in d["of"].items()}, d["is_owner"])
    check("person_of_email: either address of the person, as written (another case is another address), none for a stranger or empty",
          d["mail"] == {"pat@example.com": "Pat", "pat2@example.com": "Pat", "PAT@example.com": None, "Pat@Example.com": None, "a@example.com": None, "you@example.com": None, "": None}, d["mail"])
    check("emails() lists the addresses in the order written", d["emails"] == ["pat@example.com", "pat2@example.com"], d["emails"])
    check("names_cf() and owner_names_cf() hold the casefolded names (the same set)", d["cf"] == sorted(["pat", "pj", "パット"]) and d["guards_cf"] == d["cf"], (d["cf"], d["guards_cf"]))
    check("owner_openers() is the aliases with `you` after the first", d["openers"] == ["PJ", "you", "パット", "pat"], d["openers"])
    L = d["line"]
    check("opener_person: `<name>:`, `<alias>:` (as written) and `<name> to` are the person's; `you:` and `You:` too, and the person is the first", all(L[l][0] == "Pat" for l in ("Pat: take it", "PJ: take it", "パット: 別の行", "Pat to review it", "PJ to review it", "you: take it", "You: take it")), L)
    check("…and no other line is: a lowercase alias, `YOU:`, `the owner:`, the owner's, another name, a ticket, a sentence", all(L[l][0] is None for l in ("pj: lowercase alias", "YOU: shouted", "the owner: x", "the owner's step", "Alex: take it", "AE: take it", "Lee: take it", "ACME-1: x", "Pat approved it")), L)
    check("the opener regex agrees with opener_person (with `to`), and without `to` a `<name> to …` line is not an opener", all(v[1] == (v[0] is not None) for v in L.values()) and L["Pat to review it"][2] is False and L["Pat: take it"][2] is True, L)
    check("with only [[members]] set (the example's placeholder owner and no old address beside it), notes() has no no-owner line and no both-set line", not [n for n in d["notes"] if "[[members]]" in n or "has no owner" in n], d["notes"])

# ---- 2. only the old keys: a list of one
d, r = report(config("old", owner="Alex", aliases=["AE", " ", "Alex", "You", "AE", "オリバー"], emails=["a@example.com", "b@example.com"]), PROBES, MAILS, LINES)
check("the old keys load", d is not None, r.stderr[-600:])
if d:
    check("one person from owner, owner_aliases (cleaned) and allowed_emails (all the addresses are that person's)",
          d["members"] == [["Alex", ["AE", "オリバー"], ["a@example.com", "b@example.com"], True]], d["members"])
    check("the answers are the old keys' answers: owner(), owner_aliases(), the mover, the openers, the sign-in address",
          d["owner"] == "Alex" and d["aliases"] == ["AE", "オリバー"] and d["of"]["Alex"] == "Alex" and d["of"]["AE"] == "Alex" and d["of"]["Pat"] is None and d["mail"]["a@example.com"] == "Alex"
          and d["line"]["Alex: take it"][0] == "Alex" and d["line"]["AE: take it"][0] == "Alex" and d["line"]["you: take it"][0] == "Alex" and d["line"]["Pat: take it"][0] is None, d)
    check("with the old keys only, notes() says nothing of members", not [n for n in d["notes"] if "[[members]]" in n or "has no owner" in n], d["notes"])

# ---- 3. both set: the list wins, the old keys are not read for a person, and the start says so
d, r = report(config("both", owner="Alex", aliases=["AE"], emails=["a@example.com"], members=[PAT]), PROBES, MAILS, LINES)
check("a config with both loads", d is not None, r.stderr[-600:])
if d:
    check("the list is the members: the old owner, alias and address are nobody's", d["owner"] == "Pat" and d["of"]["Alex"] is None and d["of"]["AE"] is None and d["mail"]["a@example.com"] is None and d["mail"]["pat@example.com"] == "Pat", d)
    check("notes() says the old keys are not read for a person", any(n.startswith("[[members]] is set, so [instance] owner") for n in d["notes"]), d["notes"])

# ---- 4. neither: the placeholder
d, r = report(config("none", owner="", aliases=[], emails=[]), PROBES + ["The Owner"], MAILS, LINES)
check("a config that names nobody loads", d is not None, r.stderr[-600:])
if d:
    check("one placeholder person: the name `the owner`, no alias, no address, not declared", d["members"] == [["the owner", [], [], False]], d["members"])
    check("owner() says `the owner`; names() (the free-text matchers) has no name, names_cf() (the stored mover) has it", d["owner"] == "the owner" and d["names"] == [] and d["owner_names"] == [] and d["cf"] == ["the owner"] and d["guards_cf"] == ["the owner"], d)
    check("a mover `the owner` (any case) is the person, as before; nothing else is", d["of"]["the owner"] == "the owner" and d["of"]["Pat"] is None and d["is_owner"]["the owner"] is True and d["is_owner"]["Alex"] is False, d["of"])
    check("`the owner:` and `the owner's` are no opener, `you:` is (the placeholder is the person), and no address signs in", d["line"]["the owner: x"][0] is None and d["line"]["the owner's step"][0] is None and d["line"]["you: take it"][0] == "the owner" and not any(d["mail"].values()), d["line"])
    check("notes() warns that the board names its person by a placeholder", any("has no owner" in n for n in d["notes"]), d["notes"])
d, r = report(config("placeholder-word", aliases=[]), ["the owner", "Pat"], ["you@example.com"], ["the owner: x", "you: x"])
check("the example's own `owner = \"the owner\"` is the placeholder too, and its address signs in", d is not None and d["owner"] == "the owner" and d["of"]["the owner"] == "the owner" and d["line"]["the owner: x"][0] is None
      and d["mail"]["you@example.com"] == "the owner", (d, r.stderr[-400:]))

# ---- 5. several addresses and one person across both shapes
d, _ = report(config("many-mail", members=[{"name": "Pat", "emails": [f"p{i}@example.com" for i in range(5)]}]), [], [f"p{i}@example.com" for i in range(5)] + ["p5@example.com"])
check("five addresses are one person's; a sixth is nobody's", d is not None and all(d["mail"][f"p{i}@example.com"] == "Pat" for i in range(5)) and d["mail"]["p5@example.com"] is None and len(d["emails"]) == 5, d and d["mail"])
d, _ = report(config("no-mail", members=[{"name": "Pat"}]))
check("a person with no alias and no address is valid: nobody signs in as them", d is not None and d["members"] == [["Pat", [], [], True]] and d["emails"] == [], d and d["members"])

# ---- 6. what is refused, at the start
def refused(label, members, expect, **old):
    path = config(label, members=members, **old)
    r = run(path, "import stackshot.core.config")
    last = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ""
    check(f"start refuses {label}: it ends, and says why", r.returncode != 0 and all(e in r.stderr for e in expect), (r.returncode, r.stderr[-600:]))
    return path, r, last

two = [PAT, {"name": "Lee", "aliases": ["LL"], "emails": ["lee@example.com"]}]
p_more, r, last = refused("more-than-one", two, [MORE_THAN_ONE])
check("…the refusal is the one line, last, without a traceback", last == MORE_THAN_ONE and "Traceback" not in r.stderr, r.stderr[-400:])
refused("dup-name", [{"name": "Pat"}, {"name": "pat"}], ['"pat" is already the name or an alias of entry 1', MORE_THAN_ONE])
refused("dup-alias", [{"name": "Pat", "aliases": ["PJ"]}, {"name": "Lee", "aliases": ["pj"]}], ['entry 2: "pj" is already the name or an alias of entry 1'])
refused("alias-is-name", [{"name": "Pat", "aliases": ["LEE"]}, {"name": "Lee"}], ['entry 2: "Lee" is already the name or an alias of entry 1'])
refused("dup-address", [{"name": "Pat", "emails": ["x@example.com"]}, {"name": "Lee", "emails": ["x@example.com"]}], ['entry 2: the address "x@example.com" is already entry 1\'s'])
refused("no-name", [{"aliases": ["PJ"]}], ["[[members]] entry 1 has no name"])
refused("blank-name", [{"name": "  "}], ["[[members]] entry 1 has no name"])
path = T / "not-tables.toml"; path.write_text('members = ["Pat"]\n' + BASE, encoding="utf-8")
r = run(path, "import stackshot.core.config")
check("start refuses a `members` that is no list of tables", r.returncode != 0 and "[[members]] is not a list of tables" in r.stderr, r.stderr[-400:])
# the table's first name is no longer read: a config that still has it is refused, and the line says what to do
path = T / "old-table.toml"; path.write_text('[[people]]\nname = "Pat"\n' + BASE, encoding="utf-8")
r = run(path, "import stackshot.core.config")
check("start refuses a config that still has [[people]], and says it is now [[members]]", r.returncode != 0 and "[[people]] is now [[members]]" in r.stderr, r.stderr[-400:])
d, r = report(config("empty-list", owner="Alex", emails=["a@example.com"]))
check("no [[members]] table at all is the old keys, not a refusal", d is not None and d["owner"] == "Alex", r.stderr[-300:])

# ---- 7. a reload keeps the running config on a refusal, and the list is restart-only
RELOAD = r"""
import json, pathlib, sys
from stackshot.core import config, members
path = pathlib.Path(sys.argv[1]); good = path.read_text(encoding="utf-8"); out = {}
out["before"] = members.first().name
path.write_text(sys.argv[2] and pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"), encoding="utf-8")
out["refused"] = config.reload(); out["after_refused"] = [p.name for p in members.members()]
path.write_text(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"), encoding="utf-8")
out["changed"] = config.reload(); out["after_changed"] = [p.name for p in members.members()]; out["pending"] = list(config.PENDING)
print(json.dumps(out))
"""
good = config("reload-good", members=[PAT]); other = config("reload-other", members=[{"name": "Sam", "emails": ["sam@example.com"]}])
r = run(good, RELOAD, str(good), str(p_more), str(other))
try:
    out = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    out = None
check("a reload to a list of two is refused (None) and the running members stay", out is not None and out["before"] == "Pat" and out["refused"] is None and out["after_refused"] == ["Pat"], (out, r.stderr[-500:]))
check("a reload to another single person is no live change: the running person stays and the change waits for a restart", out is not None and out["after_changed"] == ["Pat"] and "members" in out["pending"], out)

# ---- 8. doctor says the same, and counts the addresses of a list
HOME = T / "home"; HOME.mkdir(exist_ok=True)
r = subprocess.run([os.path.join(STACK, "bin", "stackshot"), "doctor", "--no-systemd"], capture_output=True, text=True, env=env_for(p_more), cwd=STACK, stdin=subprocess.DEVNULL, timeout=300)
check("doctor on a list of two: exit 1, the config line is missing and carries the refusal", r.returncode == 1 and re.search(r"missing\s+config .*loads through config\.py", r.stdout) is not None and MORE_THAN_ONE in r.stdout, r.stdout[-700:] + r.stderr[-300:])
r = subprocess.run([os.path.join(STACK, "bin", "stackshot"), "doctor", "--no-systemd"], capture_output=True, text=True, env=env_for(config("doctor-ok", members=[PAT])), cwd=STACK, stdin=subprocess.DEVNULL, timeout=300)
check("doctor counts the sign-in addresses of a [[members]] list (two)", re.search(r"ok\s+auth\.allowed_emails: 2 address\(es\)", r.stdout) is not None, r.stdout[-900:] + r.stderr[-300:])
r = subprocess.run([os.path.join(STACK, "bin", "stackshot"), "doctor", "--no-systemd"], capture_output=True, text=True, env=env_for(config("doctor-old", owner="Alex", emails=["a@example.com"])), cwd=STACK, stdin=subprocess.DEVNULL, timeout=300)
check("…and of the old key (one), in the words it always had", re.search(r"ok\s+auth\.allowed_emails: 1 address\(es\)", r.stdout) is not None, r.stdout[-900:] + r.stderr[-300:])

# ---- 9. no other module reads the three keys for a person
leaks = []
for p in sorted(pathlib.Path(STACK, "stackshot").rglob("*.py")):
    rel = p.relative_to(STACK).as_posix()
    if rel in ("stackshot/core/members.py", "stackshot/core/config.py", "stackshot/cli.py"):         # the reader, the config's own key tables and notes, and the setup command that writes the keys
        continue
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(r"""\(\s*["']instance["']\s*,\s*["']owner(_aliases)?["']|\(\s*["']auth["']\s*,\s*["']allowed_emails["']|\[["']allowed_emails["']\]|\[["']owner_aliases["']\]""", line):
            leaks.append(f"{rel}:{i}")
check("no module but members.py (and config.py's own tables, cli.py's setup) reads [instance] owner, owner_aliases or [auth] allowed_emails", not leaks, leaks)

print(f"{len(ran) - len(fails)} of {len(ran)} checks passed")
sys.exit(1 if fails else 0)
