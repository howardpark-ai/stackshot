"""Scenario test for the members file's records: a member may be a list of backends (the older form) or an object with `boards`, `aliases` and `emails`, so a person who signs in with
several addresses, or is stored under a name, is one member of a board behind the front door (`core/frontdoor_files.py`, `core/behind_door.py: people`, `core/members.py`, `web/auth/oauth.py: _who`).

Offline and hermetic, one process: made-up config tables and members files in a scratch folder, no board server, no port.

Covers:
  * `read_member_records`: the list form and the object form; the key of a list is the member's one address as written; the object's `emails` are lower-cased and
    deduplicated and replace the key as the address; an object with no `emails` and an address for a key keeps the key; `aliases` are trimmed, deduplicated and empty ones dropped; a value of any other
    shape is a member of nothing; a `boards` that is no list is no boards; a key that is empty is left out; the older reader `read_members` answers what it always did for the list form and reads the
    object's `boards`; a file that is not JSON or not an object is a FileError;
  * `member_of_address`: found by any listed address in any case; the first member when two list one; "" for an address nobody has, an empty one and a name;
  * no name or address belongs to two members: keys first, then the file's order; what is dropped is told; an `emails` entry with no `@` is not read; the older list form is read as before;
  * names are compared as the board looks them up (white space collapsed, casefolded: two spaces or a sharp s do not make a second name), anything with an `@` by case and surrounding spaces only;
  * a member on no board takes no alias or address from a member who is on one, by its key or by its lists; a blank alias or address, or one that is no text, is told like the other drops;
  * the board's log says each thing dropped from the file, once;
  * `behind_door.people` and `members`: the members of one board in the file's order, with their aliases and addresses; two keys that differ only in case are one member (the first); None for a board that
    does not read its members from a front door; () for a file that cannot be read;
  * `members.build`: a person named by the key with the aliases and addresses the file gives, `person_of_email` finds each address (and not another), `person_of` finds the name and an alias, the older
    address-keyed form builds the person it always built;
  * `oauth._who` on a board behind a door: the signed identity is matched to a member by the key alone, exactly (never an alias, another address or another case): the answer is one of the person's addresses, or the
    signed name for a person with none, and the signed address itself when it is one of the person's addresses, the second included; an alias or address of one member never takes another's call; the
    placeholder is nobody; a request with no identity is refused.

    tests/run-suite frontdoor_members       -> exit 0 / 1"""
import contextlib, io, json, os, sys, tomllib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch

from stackshot.core import behind_door as door, frontdoor_files as files, members as mem

fails, ran = [], []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))


T = _scratch.mkdtemp(prefix="doormembers-")
n_files = [0]


def write(obj):
    n_files[0] += 1
    p = os.path.join(T, f"members{n_files[0]}.json")
    with open(p, "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))
    return p


M = files.Member
FILE = {
    "alice@example.test": ["main", "side"],
    "bob": ["side"],
    "Pat": {"boards": ["main"], "aliases": ["PJ", " PJ ", "", "H"], "emails": ["Pat@Example.Test", "pat@example.test", "pat2@example.test"]},
    "dave@example.test": {"boards": ["main", 5, " "], "aliases": "no"},
    "eve@example.test": "main",
    "frank@example.test": {"boards": "main"},
    "": ["main"],
}
p = write(FILE)
recs = files.read_member_records(p)
check("records: an address key with a list is that one address", recs["alice@example.test"] == M(("main", "side"), (), ("alice@example.test",)), recs.get("alice@example.test"))
check("records: a key with a list is the address as written, whether or not it looks like one (the older form reads as before)", recs["bob"] == M(("side",), (), ("bob",)), recs.get("bob"))
check("records: an object gives its boards, its aliases (trimmed, deduplicated, no empty one) and its addresses (lower case, deduplicated), replacing the key as the address",
      recs["Pat"] == M(("main",), ("PJ", "H"), ("pat@example.test", "pat2@example.test")), recs.get("Pat"))
check("records: an object with an address key and no emails keeps the key as its address; a boards list drops what is no name; aliases that are no list are none",
      recs["dave@example.test"] == M(("main",), (), ("dave@example.test",)), recs.get("dave@example.test"))
check("records: a value that is neither a list nor an object is a member of nothing; so is a boards that is no list", recs["eve@example.test"].boards == () and recs["frank@example.test"].boards == (), recs)
check("records: an empty key is left out", "" not in recs and list(recs) == ["alice@example.test", "bob", "Pat", "dave@example.test", "eve@example.test", "frank@example.test"], list(recs))
check("records: the older reader answers the list form as it did and reads an object's boards",
      files.read_members(p) == {"alice@example.test": ["main", "side"], "bob": ["side"], "Pat": ["main"], "dave@example.test": ["main"], "eve@example.test": [], "frank@example.test": []}, files.read_members(p))
for label, text in (("not JSON", "{nope"), ("a list", "[1]"), ("a string", '"x"')):
    try:
        files.read_member_records(write(text)); ok = False
    except files.FileError:
        ok = True
    check(f"records: a file that is {label} is a FileError", ok)

# ---- member_of_address
check("address: any listed address finds the member, in any case", files.member_of_address(recs, "PAT2@example.test") == "Pat" and files.member_of_address(recs, " pat@example.test ") == "Pat")
check("address: an address key finds itself", files.member_of_address(recs, "Alice@Example.Test") == "alice@example.test")
check("address: nobody's address, an empty one, a name and an address that was replaced by emails are no member",
      files.member_of_address(recs, "nobody@example.test") == "" and files.member_of_address(recs, "") == "" and files.member_of_address(recs, "bob") == "" and files.member_of_address(recs, "Pat") == "")
twice = {"a@x.test": M(("main",), (), ("shared@x.test",)), "b@x.test": M(("main",), (), ("shared@x.test",))}
check("address: two members that list one address, the first in the file's order is it", files.member_of_address(twice, "shared@x.test") == "a@x.test")

# ---- no name or address belongs to two members
def read(obj):
    said = []
    return files.read_member_records(write(obj), said), said
r, said = read({"alice": {"boards": ["main"], "aliases": ["Bob", "AL"], "emails": ["a@x.test"]}, "bob": {"boards": ["main"], "emails": ["b@x.test"]}})
check("unique: an alias that is another member's key (in any case) is dropped and told", r["alice"].aliases == ("AL",) and r["bob"].emails == ("b@x.test",) and any("alias" in n and "'bob'" in n for n in said), (r, said))
r, said = read({"ann": {"boards": ["main"], "emails": ["bo@x.test", "ann@x.test"]}, "bo@x.test": ["main"]})
check("unique: an address that is another member's key is dropped from the first, even though the key comes later", r["ann"].emails == ("ann@x.test",) and r["bo@x.test"].emails == ("bo@x.test",) and files.member_of_address(r, "bo@x.test") == "bo@x.test" and len(said) == 1, (r, said))
r, said = read({"ann": {"boards": ["main"], "emails": ["bo", "ann@x.test"]}, "bo": ["main"]})
check("unique: an entry of emails with no @ is not read, and told", r["ann"].emails == ("ann@x.test",) and any("no @" in n for n in said), (r, said))
r, said = read({"ann": {"boards": ["side"], "aliases": ["Boss"], "emails": ["shared@x.test"]}, "cat": {"boards": ["main"], "aliases": ["boss", "kitty"], "emails": ["Shared@x.test", "cat@x.test"]}})
check("unique: an alias and an address an earlier member has (on any board) are dropped from the later one, in any case", r["cat"].aliases == ("kitty",) and r["cat"].emails == ("cat@x.test",) and r["ann"].emails == ("shared@x.test",) and len(said) == 2, (r, said))
r, said = read({"Pat": {"boards": ["main"], "emails": ["p1@x.test"]}, "pat": {"boards": ["main"], "emails": ["p2@x.test"]}})
check("unique: of two keys that differ only in case only the first is a member, so the second's address finds nobody", list(r) == ["Pat"] and files.member_of_address(r, "p2@x.test") == "" and len(said) == 1, (r, said))
r, said = read({"zed@x.test": {"boards": ["main"], "emails": ["other@x.test"]}})
check("unique: an object with emails and an address for a key is only the listed addresses", r["zed@x.test"].emails == ("other@x.test",) and files.member_of_address(r, "zed@x.test") == "", r)
r, said = read({"Alice@X.test": ["main"]})
check("older form: a mixed-case address key keeps the address as written, and a sign-in service finds it in any case", r["Alice@X.test"].emails == ("Alice@X.test",) and files.member_of_address(r, "alice@x.test") == "Alice@X.test" and said == [], (r, said))
check("unique: the older reader still lists every key as the file has it", files.read_members(write({"Pat": ["a"], "pat": ["b"]})) == {"Pat": ["a"], "pat": ["b"]})

# ---- names are compared as the board looks them up; anything with an @ by case and surrounding spaces only
SHARP, SS = "Stra" + chr(223) + "e", "STRASSE"
for label, alias, key in (("two spaces", "Bob  Lee", "Bob Lee"), ("a tab and another case", "bob\tLEE", "Bob Lee"), ("a sharp s spelled ss", SS, SHARP), ("two spaces in the key", "Bob Lee", "Bob  Lee")):
    r, said = read({"ann": {"boards": ["main"], "aliases": [alias, "Annie"], "emails": ["a@x.test"]}, key: {"boards": ["main"], "emails": ["b@x.test"]}})
    check(f"fold: an alias that is another member's key but for {label} is dropped and told", r["ann"].aliases == ("Annie",) and len(said) == 1 and "an alias of 'ann'" in said[0], (r, said))
r, said = read({"ann": {"boards": ["main"], "aliases": ["Jo Ann"]}, "cat": {"boards": ["main"], "aliases": ["jo   ann", "kitty"]}})
check("fold: an alias an earlier member has but for its spacing is dropped from the later one", r["ann"].aliases == ("Jo Ann",) and r["cat"].aliases == ("kitty",) and len(said) == 1, (r, said))
for label, first, second in (("repeated spaces and case", "Bob Lee", "bob  lee"), ("a sharp s spelled ss", SHARP, SS), ("surrounding spaces", "Bob Lee", " Bob Lee "),
                             ("surrounding spaces and case on an address", "a@x.test", " A@X.test ")):
    r, said = read({first: ["main"], second: ["side"]})
    check(f"fold: two keys that differ only in {label} are one member, the first, with its boards alone", list(r) == [first] and r[first].boards == ("main",) and len(said) == 1 and "only the first is a member" in said[0], (r, said))
street = "stra" + chr(223) + "e@x.test"
r, said = read({street: ["main"], "strasse@x.test": ["main"]})
check("fold: two address keys that only casefold would join are two members", list(r) == [street, "strasse@x.test"] and said == [], (r, said))
r, said = read({"ann": {"boards": ["main"], "aliases": [street], "emails": [street]}, "bo": {"boards": ["main"], "aliases": ["strasse@x.test"], "emails": ["strasse@x.test"]}})
check("fold: two addresses that only casefold would join stay each member's own, as aliases too", r["ann"].emails == (street,) and r["bo"].emails == ("strasse@x.test",) and r["bo"].aliases == ("strasse@x.test",) and said == [], (r, said))

# ---- a member on no board takes nothing from a member who is on one
r, said = read({"gone": {"boards": [], "aliases": ["Boss", "old"], "emails": ["shared@x.test", "gone@x.test"]}, "ann": {"boards": ["main"], "aliases": ["boss"], "emails": ["Shared@x.test"]}})
check("no board: an earlier entry on no board takes no alias or address from a member who is on one, and is told",
      r["ann"] == M(("main",), ("boss",), ("shared@x.test",)) and r["gone"] == M((), ("old",), ("gone@x.test",)) and len(said) == 2 and all("of 'gone' is already 'ann'" in n for n in said), (r, said))
check("no board: the file's order is kept, and the address finds the member who is on a board, its own address the other",
      list(r) == ["gone", "ann"] and files.member_of_address(r, "shared@x.test") == "ann" and files.member_of_address(r, "gone@x.test") == "gone", r)
r, said = read({"shared@x.test": [], "Boss": "main", "ann": {"boards": ["main"], "aliases": ["boss"], "emails": ["shared@x.test"]}})
check("no board: nor by its key (an empty list's address, a name of a value that is no list)",
      r["ann"] == M(("main",), ("boss",), ("shared@x.test",)) and r["shared@x.test"].emails == () and r["Boss"].emails == () and files.member_of_address(r, "shared@x.test") == "ann" and len(said) == 2, (r, said))
r, said = read({"gone": {"aliases": ["ann"], "emails": ["bo@x.test"]}, "ann": ["main"], "bo@x.test": ["main"]})
check("no board: a key of a member who is on a board stays that member's, as ever", r["gone"] == M((), (), ()) and r["ann"].boards == ("main",) and r["bo@x.test"].emails == ("bo@x.test",) and len(said) == 2, (r, said))
r, said = read({"g1": {"aliases": ["g2", "spare"], "emails": ["s@x.test"]}, "g2": {"emails": ["s@x.test"]}})
check("no board: among the entries on no board the rule is the old one: keys first, then the file's order", r["g1"] == M((), ("spare",), ("s@x.test",)) and r["g2"] == M((), (), ()) and len(said) == 2, (r, said))
r, said = read({"pat": [], "Pat": ["main"]})
check("no board: of two keys that are one name the first is the member, also when it is the one on no board", list(r) == ["pat"] and r["pat"].boards == () and len(said) == 1, (r, said))

# ---- a blank alias or address, or one that is no text, is told
r, said = read({"ann": {"boards": ["main"], "aliases": ["", "  ", 5, None, "AA"], "emails": [7, " ", {"x": 1}, "a@x.test"]}})
check("dropped: blank and non-text aliases and addresses are not read", r["ann"] == M(("main",), ("AA",), ("a@x.test",)), r)
check("dropped: and each is a note that says which and why", sorted(said) == sorted(
      ["members_file: an alias of 'ann' is blank, so it is not read"] * 2 + ["members_file: an alias of 'ann' is not text, so it is not read"] * 2
      + ["members_file: an entry of the emails of 'ann' is not text, so it is not read"] * 2 + ["members_file: an entry of the emails of 'ann' is blank, so it is not read"]), said)
r, said = read({"ann": {"boards": ["main"], "aliases": ["AA", " AA "], "emails": ["a@x.test", "A@x.test"]}, "bo": {"boards": ["main"]}})
check("dropped: a repeat inside one entry, and lists that are not there, are nothing to tell", said == [], said)

# ---- behind_door.people / members
cfgd = tomllib.loads
def table(path, board="main", extra=""):
    return cfgd(f'[behind_frontdoor]\nmembers_file = "{path}"\nboard_name = "{board}"\n{extra}')
people = door.people(table(p))
check("people: the board's members in the file's order, each with aliases and addresses",
      people == (("alice@example.test", (), ("alice@example.test",)), ("Pat", ("PJ", "H"), ("pat@example.test", "pat2@example.test")), ("dave@example.test", (), ("dave@example.test",))), people)
check("people: members() is the names of people()", door.members(table(p)) == tuple(n for n, _a, _e in people))
check("people: another board reads the same file for itself", [n for n, _a, _e in door.people(table(p, "side"))] == ["alice@example.test", "bob"])
check("people: a board that does not read its members from a front door is None", door.people(cfgd("[auth]\nmode = 'off'\n")) is None and door.members(cfgd("[auth]\nmode = 'off'\n")) is None)
check("people: a file that cannot be read lists nobody", door.people(table(os.path.join(T, "none.json"))) == ())
p_case = write({"Alice@x.test": ["main"], "alice@x.test": ["main"], "zed": ["main"]})
check("people: two keys that differ only in case are one member, the first", [n for n, _a, _e in door.people(table(p_case))] == ["Alice@x.test", "zed"])

# ---- the board's log says what was dropped
p_log = write({"ann": {"boards": ["main"], "aliases": ["Cat", ""], "emails": ["a@x.test", "nope"]}, "cat": ["main"], "CAT": ["side"]})
door._told.clear()
err = io.StringIO()
with contextlib.redirect_stderr(err):
    door.people(table(p_log)); door._cache.clear(); door.people(table(p_log))
lines = err.getvalue().splitlines()
wanted = ("members_file lists 'CAT' and 'cat'", "an alias of 'ann' is blank", "an entry of the emails of 'ann' has no @", "an alias of 'ann' is already 'cat'")
check("log: the board's log says each thing dropped from the members file, once however often the file is read",
      len(lines) == len(wanted) and all(l.startswith("board behind a front door: members_file") for l in lines) and all(sum(w in l for l in lines) == 1 for w in wanted), lines)

# ---- members.build
built = mem.build(table(p))
by_name = {x.name: x for x in built}
how = by_name["Pat"]
check("build: a person is named by the key, with the aliases and addresses the file gives", (how.name, how.aliases, how.emails) == ("Pat", ("PJ", "H"), ("pat@example.test", "pat2@example.test")), how)
check("build: the older address-keyed form builds the person it always built", (by_name["alice@example.test"].name, by_name["alice@example.test"].emails, by_name["alice@example.test"].aliases) == ("alice@example.test", ("alice@example.test",), ()))
saved_members = mem.members
mem.members = lambda: built
try:
    check("build: person_of_email finds each of a person's addresses, and not another", mem.person_of_email("pat@example.test") is how and mem.person_of_email("pat2@example.test") is how and mem.person_of_email("pat3@example.test") is None)
    check("build: person_of finds the name and an alias, in any case", mem.person_of("pat") is how and mem.person_of("pj") is how and mem.person_of(" H ") is how and mem.person_of("zzz") is None)
    check("build: signed_in names the person for any of their addresses", mem.signed_in("pat2@example.test") is how)
    folded = mem.build(table(write({"ann": {"boards": ["main"], "aliases": ["Bob  Lee", SS]}, "Bob Lee": ["main"], SHARP: ["main"]})))
    mem.members = lambda: folded
    check("build: a name looked up on the board is the member whose key it is, never an earlier member's spelling of it", [getattr(mem.person_of(w), "name", None) for w in ("bob lee", "Bob  Lee", SS, SHARP)] == ["Bob Lee", "Bob Lee", SHARP, SHARP], folded)
    mem.members = lambda: built

    # ---- oauth._who on a board behind a door
    import fastmcp.server.dependencies as deps
    from fastmcp.exceptions import ToolError
    from stackshot.web.auth import oauth
    saved_dep, saved_settings = deps.get_http_request, oauth._door.settings
    oauth._door.settings = lambda cfg=None: saved_settings(cfg) if cfg else door.Settings(identity=True)      # the running board checks identities; a made-up table is read as written
    class Req:
        def __init__(self, who): self.scope = {door.SCOPE_KEY: who} if who is not None else {}
    def who_of(identity):
        deps.get_http_request = lambda: Req(identity)
        try:
            return oauth._who()
        except ToolError as e:
            return f"ERR {e}"
    try:
        check("who: a member's name is answered with one of the person's addresses (the first, when it was not an address)", who_of("Pat") == "pat@example.test", who_of("Pat"))
        check("who: an address that is not a key is refused (the door signs the key)", who_of("pat2@example.test").startswith("ERR Refused: "), who_of("pat2@example.test"))
        check("who: an address key is answered as it is", who_of("alice@example.test") == "alice@example.test")
        check("who: a name that is nobody's is refused with the sentence", who_of("Mallory").startswith("ERR Refused: Mallory is not allowed on this board"), who_of("Mallory"))
        check("who: an address that is nobody's is refused", who_of("mallory@example.test").startswith("ERR Refused: "), who_of("mallory@example.test"))
        check("who: a request with no identity is refused with the door's sentence", who_of(None) == f"ERR {door.NO_IDENTITY}", who_of(None))
        check("who: an alias is refused: the signed identity is the key, never another name", who_of("PJ").startswith("ERR Refused: "), who_of("PJ"))
        check("who: another case of a key is refused, as the door itself would", who_of("pat").startswith("ERR Refused: "), who_of("pat"))
        # the reviewer's cases: an alias or address of one member never takes another's signed identity
        for label, obj, signed, want in (
                ("an alias equal to another's key", {"alice": {"boards": ["main"], "aliases": ["bob"], "emails": ["a@x.test"]}, "bob": {"boards": ["main"], "emails": ["b@x.test"]}}, "bob", "b@x.test"),
                ("an address equal to another's key", {"ann": {"boards": ["main"], "emails": ["bo@x.test"]}, "bo@x.test": ["main"]}, "bo@x.test", "bo@x.test"),
                ("an emails entry equal to another's key", {"ann": {"boards": ["main"], "emails": ["bo"]}, "bo": ["main"]}, "bo", "bo")):
            these = mem.build(table(write(obj)))
            mem.members = lambda these=these: these
            check(f"who: {label} does not take the call", who_of(signed) == want, (who_of(signed), these))
        second = mem.build(table(write({"b@x.test": {"boards": ["main"], "emails": ["a@x.test", "b@x.test"]}})))
        mem.members = lambda: second
        check("who: a signed address key listed second in its own emails is answered as signed, not as the first address", who_of("b@x.test") == "b@x.test", (who_of("b@x.test"), second))
        mem.members = lambda: built
        p_none = mem.build(table(write({"nobody": {"boards": ["main"]}})))
        mem.members = lambda: p_none
        check("who: a member with a name and no address is answered with the signed name", who_of("nobody") == "nobody", who_of("nobody"))
        mem.members = lambda: mem.build(table(os.path.join(T, "gone.json")))
        check("who: the placeholder of an unreadable file is nobody, even for its own name", who_of(mem.PLACEHOLDER).startswith("ERR Refused: "), who_of(mem.PLACEHOLDER))
        mem.members = lambda: built
    finally:
        deps.get_http_request, oauth._door.settings = saved_dep, saved_settings
finally:
    mem.members = saved_members

if fails:
    print(f"\n{len(fails)} failures in {len(ran)} checks"); sys.exit(1)
print(f"ok: front door members scenario, {len(ran)} checks")
