"""Scenario test for the mailbox scope of a Gmail query anchor — fixture data, a fake Google API, no network, no server socket.

`gmail:q:<query>` reads every mailbox the anchors service reads; `gmail:q@<mailbox>[,<mailbox>]:<query>` reads only the mailboxes named. Covered:

  * the reader (anchorhub/gworkspace.py, run on a fake Google with two mailboxes that both receive the same mail): an anchor scoped to one mailbox hears
    the mail of that mailbox and not the same mail in the other; an unscoped anchor (every anchor stored before the scope existed) hears both; a scope of
    two mailboxes hears both; a stored scope that names a mailbox that is gone reads nothing and does not stop the reader, and one that names a gone
    mailbox beside a live one reads the live one; a mailbox outside GMAIL_ACCOUNTS is no mailbox the anchors service reads.
  * the anchors service reports the mailboxes it reads (status.json google.mailboxes: the label [anchor_hub] gmail_names gives, else the address), and names each Gmail
    query anchor with its mailboxes (`<query> · home, work`); a scope with only gone mailboxes is reported unreadable.
  * the anchors tool: the add reply and the list name the mailboxes each Gmail query anchor reads, before the anchors service has named it; a scope typed in another
    case is stored with the label's spelling and is the same anchor as the one stored; an unknown mailbox, or none after `gmail:q@`, is refused with the
    valid names and nothing is stored; a removal in another spelling finds the entry; with no mailbox known (the anchors service has not reported) a scope is stored as typed.
  * the syntax: the parser of the id, and that an unscoped id keeps its meaning (an "@" in a query is query text); a repeated mailbox name counts once; an empty
    scope reads no mailbox; the address of an account is matched in any case; a space in a scope is refused when the anchor is added.
  * a scope stored as typed (the service had named no mailbox yet) is the same anchor as its canonical spelling: one entry, and a removal finds it in either spelling.
  * with no [anchor_hub] gmail_names an unscoped anchor's title is its query alone (a mailbox with no name is not named in a title).
  * config.notes says an entry of gmail_names the reader skips, two names that differ only in case, and two names for one address.

    tests/run-suite gmail_anchor_mailbox        → exit 0 / 1"""
import json, logging, os, pathlib, queue, re, sys, time, types
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="gmail-mbx-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r'(?m)^gmail_names = \{\}', 'gmail_names = { work = "Ada@Example.test", home = "bo@example.test" }', toml); assert n == 1   # a label, an address in another case
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("ANCHOR_HUB_ALLOW_SELF", None)
for d in ("store/a", "fleet/a", "brain/projects", "transcripts/-scratch-t"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "", "status": "active", "board": [], "board_open": 0}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.CRITICAL)

ADA, BO, CY = "ada@example.test", "bo@example.test", "cy@example.test"      # work, home, and an account that is not in GMAIL_ACCOUNTS
from stackshot.anchors.anchorhub import core, gworkspace as gw
from stackshot.anchors import anchors as anc

# ---- the id syntax (pure)
check("syntax: an unscoped id is a query with no scope, and keeps its text whole (colons and all)",
      anc.gmail_query("gmail:q:from:pat subject:re: x") == (None, "from:pat subject:re: x"), anc.gmail_query("gmail:q:from:pat subject:re: x"))
check("syntax: a scoped id names its mailboxes; the query after it keeps its colons",
      anc.gmail_query("gmail:q@work,home:from:pat") == (["work", "home"], "from:pat"), anc.gmail_query("gmail:q@work,home:from:pat"))
check("syntax: a mailbox written inside the query is query text, not a scope (the reason the marker sits before the colon)",
      anc.gmail_query("gmail:q:work:from:pat") == (None, "work:from:pat"), anc.gmail_query("gmail:q:work:from:pat"))
check("syntax: a thread id and an empty scope are told apart", anc.gmail_query("gmail:1111111111111111") is None and anc.gmail_query("gmail:q@:x") == ([], "x"))
check("syntax: anchor_id passes a scoped id through unchanged", anc.anchor_id("gmail:q@work:from:pat") == "gmail:q@work:from:pat")
check("syntax: an '@' in an unscoped query is query text, not a scope",
      anc.gmail_query("gmail:q:from:a@b.com") == (None, "from:a@b.com") and anc.gmail_query("gmail:q:(from:a@b.com OR from:c@d.com)") == (None, "(from:a@b.com OR from:c@d.com)")
      and anc.anchor_id("gmail:q:from:a@b.com") == "gmail:q:from:a@b.com", (anc.gmail_query("gmail:q:from:a@b.com"), anc.gmail_query("gmail:q:(from:a@b.com OR from:c@d.com)")))
check("syntax: a space inside a scope makes it no Gmail query id at all", anc.gmail_query("gmail:q@work, home:from:pat") is None and anc.gmail_query("gmail:q@work home:from:pat") is None)
BX = {"home": "bo@example.test", "work": "ada@example.test"}
check("syntax: a mailbox named twice (by label, in another case, or by address) counts once", anc.gmail_resolve(["work", "work", "WORK", "Ada@Example.test"], BX) == (["work"], [])
      and anc.gmail_resolve(["nope", "nope"], BX) == ([], ["nope"]) and anc.gmail_canonical("gmail:q@work,work:x", BX) == "gmail:q@work:x"
      and anc.gmail_title("gmail:q@work,work:from:pat", BX) == "from:pat · work", (anc.gmail_resolve(["work", "work", "WORK"], BX), anc.gmail_title("gmail:q@work,work:from:pat", BX)))
check("syntax: an empty scope reads no mailbox", anc.gmail_mailboxes("gmail:q@:from:pat", BX) == ([], []) and not anc.gmail_reads("gmail:q@:from:pat", "ada@example.test", BX))
check("syntax: an account address in another case than the mailbox list's still matches (either side)",
      anc.gmail_reads("gmail:q@work:x", "ada@example.test", {"work": "Ada@Example.TEST"}) and anc.gmail_reads("gmail:q@work:x", "ADA@EXAMPLE.TEST", BX)
      and anc.gmail_reads("gmail:q:x", "ADA@EXAMPLE.TEST", BX) and not anc.gmail_reads("gmail:q@home:x", "ada@example.test", BX))
check("labels: a configured label names its address (any case), an unconfigured mailbox is named by its address",
      gw.mailbox_labels([ADA, BO, CY]) == {"home": BO, "work": ADA, CY: CY}, gw.mailbox_labels([ADA, BO, CY]))

# ---- the reader, on a fake Google with two accounts that receive the same mail
pathlib.Path(gw.GDIR).mkdir(parents=True, exist_ok=True)
pathlib.Path(core.ADIR).mkdir(parents=True, exist_ok=True)
pathlib.Path(core.ENVF).write_text(f"GMAIL_ACCOUNTS={ADA},{BO}\n")
for em in (ADA, BO, CY): pathlib.Path(gw.GDIR, f"{em}.json").write_text("{}")
class Api:
    def __init__(self, root, path=(), kw=None): self.root, self.path, self.kw = root, path, kw or {}
    def __getattr__(self, name):
        if name == "execute": return lambda: self.root.handle(".".join(self.path), self.kw)
        return lambda *a, **k: Api(self.root, self.path + (name,), k)
class Account:
    """One mailbox of the fake Google: it receives one mail (from Pat, subject Quarterly numbers) the first time its history is read."""
    def __init__(self, email): self.email, self.reads = email, 0
    def service(self, name): return Api(self, (name,))
    def handle(self, key, kw):
        if key == "gmail.users.getProfile": return {"historyId": "h1"}
        if key == "drive.changes.getStartPageToken": return {"startPageToken": "p1"}
        if key == "gmail.users.history.list":
            self.reads += 1
            return {"history": [{"messagesAdded": [{"message": {"id": "m-" + self.email, "threadId": "t-" + self.email}}]}] if self.reads == 1 else [], "historyId": "h2"}
        if key == "gmail.users.messages.get":
            return {"labelIds": ["INBOX"], "snippet": self.email, "internalDate": "1",
                    "payload": {"headers": [{"name": "From", "value": "Pat <pat@example.test>"}, {"name": "Subject", "value": "Quarterly numbers"}]}}
        return {}
accts = {em: Account(em) for em in (ADA, BO, CY)}
def _module(name, **attrs):
    m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m; return m
for _n in ("google", "google.oauth2", "google.auth", "google.auth.transport", "googleapiclient"): _module(_n)      # the Google libraries are not in the suites' environment
_module("google.oauth2.credentials", Credentials=types.SimpleNamespace(from_authorized_user_file=lambda f: types.SimpleNamespace(valid=True, email=os.path.basename(f)[:-5])))
_module("google.auth.transport.requests", Request=object)
_module("googleapiclient.discovery", build=lambda name, version, credentials=None, cache_discovery=False: accts[credentials.email].service(name))
_module("googleapiclient.http", HttpRequest=type("HttpRequest", (), {"execute": lambda self, *a, **k: {}}))
caught = []
gw._gmail_poll = lambda: 10 ** 10
gw.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)), RLock=__import__("threading").RLock)
class FastQ(queue.Queue):
    def get(self, block=True, timeout=None): return super().get(block=False)

UN, W, H, WH = "gmail:q:from:pat", "gmail:q@work:from:pat", "gmail:q@home:from:pat", "gmail:q@home,work:from:pat"
GONE, WGONE = "gmail:q@gone:from:pat", "gmail:q@gone,work:from:pat"
OTHER = "gmail:q@work:from:someone-else"
EMPTY = "gmail:q@:from:pat"                                        # a scope that names no mailbox (nothing can add one now; an older or hand-made store could hold it)
AT, AT2 = "gmail:q:from:pat@example.test", "gmail:q:from:pat@example.test subject:quarterly"      # an "@" in an unscoped query
h = core.Hub(); h.status["receivers"] = {}; h.triggers = FastQ()
h.bindings = {a: {"sess"} for a in (UN, W, H, WH, GONE, WGONE, OTHER, EMPTY, AT, AT2)}
events = []
h.event = lambda anchor, summ, kind="slack": events.append((anchor, summ["text"]))
gw.run(h)
loop = next(t for t in caught if t.__name__ == "loop")
_health = h.health
def _stop_after_health(*a, **k):
    try: return _health(*a, **k)
    finally: h.stopping.set()      # the pass that reads the mailboxes ends with the health report: one pass
h.health = _stop_after_health
for em in (ADA, BO, CY): h.triggers.put(("gmail", em))
loop()
heard = lambda anchor: sorted(t for a, t in events if a == anchor)
check("reader: an anchor scoped to work hears the mail in work and not the same mail in home", heard(W) == [ADA], events)
check("reader: an anchor scoped to home hears the mail in home only", heard(H) == [BO], events)
check("reader: an unscoped anchor (as every anchor stored before the scope existed) hears both mailboxes", heard(UN) == [ADA, BO], events)
check("reader: a scope of two mailboxes hears both", heard(WH) == [ADA, BO], events)
check("reader: a stored scope naming a mailbox that is gone reads nothing, and the reader went on to the others", heard(GONE) == [] and heard(W) == [ADA], events)
check("reader: a gone mailbox beside a live one reads the live one", heard(WGONE) == [ADA], events)
check("reader: a scoped anchor still needs its query to match", heard(OTHER) == [], events)
check("reader: an empty scope reads no mailbox (the reader called with it, not only the add refused)", heard(EMPTY) == [], events)
check("reader: an unscoped query holding an '@' is still unscoped and reads every mailbox", heard(AT) == [ADA, BO] and heard(AT2) == [ADA, BO], events)
HDR = {"from": "Pat <pat@example.test>", "subject": "Quarterly numbers"}
check("reader: query_hits called directly, an empty scope matches nowhere, and the account address is matched in any case",
      gw.query_hits([EMPTY], ADA, HDR, h.status["google"]["mailboxes"]) == [] and gw.query_hits([W], "ADA@Example.Test", HDR, {"work": "Ada@EXAMPLE.test"}) == [W]
      and gw.query_hits([W], BO, HDR, h.status["google"]["mailboxes"]) == [], gw.query_hits([W], "ADA@Example.Test", HDR, {"work": "Ada@EXAMPLE.test"}))
check("reader: a mailbox outside GMAIL_ACCOUNTS is read by nobody (its account was never polled for mail)", accts[CY].reads == 0 and all(t != CY for _a, t in events), (accts[CY].reads, events))

check("status: the anchors service reports the mailboxes it reads, by label", h.status["google"].get("mailboxes") == {"home": BO, "work": ADA}, h.status.get("google"))
res = h.resolvers["gmail"]
check("title: an unscoped anchor is named with every mailbox", res(UN)["title"] == "from:pat · home, work", res(UN))
check("title: a scoped anchor is named with its mailbox", res(W)["title"] == "from:pat · work", res(W))
check("title: a scope of two names both, in the order written", res(WH)["title"] == "from:pat · home, work", res(WH))
gone = res(GONE)
check("title: a scope with only a gone mailbox is unreadable, and says which mailboxes exist", "unreadable" in gone and "home, work" in gone["unreadable"] and "gone (no such mailbox)" in gone["title"], gone)
check("title: a gone mailbox beside a live one is marked, and the anchor stays readable", "unreadable" not in res(WGONE) and res(WGONE)["title"] == "from:pat · work, gone (no such mailbox)", res(WGONE))
h.write_status()
_names = core._cfg.CFG["anchor_hub"]["gmail_names"]
try:
    core._cfg.CFG["anchor_hub"]["gmail_names"] = {}
    r0 = res(UN)
    check("title: with no names configured an unscoped anchor's title is its query alone (no address in it)", r0 == {"title": "from:pat", "url": ""}, r0)
    core._cfg.CFG["anchor_hub"]["gmail_names"] = {"work": ADA}
    check("title: with one mailbox named and one not, an unscoped anchor is still named by its query alone", res(UN)["title"] == "from:pat" and res(W)["title"] == "from:pat · work", (res(UN), res(W)))
finally:
    core._cfg.CFG["anchor_hub"]["gmail_names"] = _names
check("title: with every mailbox named an unscoped anchor names them all", res(UN)["title"] == "from:pat · home, work", res(UN))
check("title: no names, a pure call: unscoped is the query, scoped by an address keeps the address it was written with",
      anc.gmail_title(UN, {ADA: ADA, BO: BO}) == "from:pat" and anc.gmail_title(f"gmail:q@{ADA}:from:pat", {ADA: ADA, BO: BO}) == f"from:pat · {ADA}", anc.gmail_title(UN, {ADA: ADA, BO: BO}))

# ---- the anchors tool
from stackshot.web import server
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
def anchors(**kw): return server._anchors("projects/alpha", who="tester", **kw)
def stored(): return [e["url"] for e in json.loads((T / "store/anchors.json").read_text()).get("projects/alpha", [])]
def refuse(name, f, *want):
    try: out = f(); check(name, False, out)
    except Exception as e: check(name, all(w in str(e) for w in want), str(e))
check("tool: the anchors service's mailboxes reach the server through the status file", server._gmail_boxes() == {"home": BO, "work": ADA}, server._gmail_boxes())
out = anchors(add=["gmail:q:from:pat"])
check("tool: an unscoped add is stored as typed; the reply and the list name every mailbox", stored() == ["gmail:q:from:pat"] and "Gmail from:pat · home, work" in out and "reads the mailboxes: home, work" in out, out)
out = anchors(add=["gmail:q@WORK:from:pat"])
check("tool: a scope typed in another case is stored with the label's spelling; the line names that mailbox", stored() == ["gmail:q:from:pat", "gmail:q@work:from:pat"] and "Gmail from:pat · work\n" in out + "\n", out)
anchors(add=["gmail:q@work:from:pat"])
check("tool: the same scope again is the same anchor", stored() == ["gmail:q:from:pat", "gmail:q@work:from:pat"], stored())
anchors(add=["gmail:q@Bo@Example.test,work:from:amy#mention=sam"])
check("tool: an address names a mailbox as well as its label; a #mention fragment stays", "gmail:q@home,work:from:amy#mention=sam" in stored(), stored())
before = stored()
refuse("tool: an unknown mailbox is refused with the valid names", lambda: anchors(add=["gmail:q@nope:from:pat"]), "'nope'", "home, work")
refuse("tool: a scope naming no mailbox is refused", lambda: anchors(add=["gmail:q@:from:pat"]), "names no mailbox", "home, work")
refuse("tool: one unknown mailbox among known ones refuses the whole add", lambda: anchors(add=["gmail:q@work,nope:from:pat"]), "'nope'")
refuse("tool: a space after a comma in a scope is refused, naming the rule", lambda: anchors(add=["gmail:q@work, home:from:pat"]), "commas with no spaces")
refuse("tool: a space inside a scope is refused", lambda: anchors(add=["gmail:q@work home:from:pat"]), "commas with no spaces")
check("tool: a refused add stores nothing", stored() == before, stored())
anchors(remove=["gmail:q@work, home:from:pat"])
check("tool: a removal of such a spelling is not refused and removes nothing else", stored() == before, stored())
out = anchors()
check("tool: the list names the mailboxes of each Gmail query anchor (the anchors service's own label for it is not needed)",
      "Gmail from:pat · home, work" in out and "Gmail from:pat · work\n" in out + "\n" and "Gmail from:amy · home, work" in out, out)
anchors(remove=["gmail:q@WORK:from:pat"])
check("tool: a removal in another spelling finds the entry", "gmail:q@work:from:pat" not in stored() and "gmail:q:from:pat" in stored(), stored())
# a stored scope whose mailbox is gone is shown, never a crash
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": GONE, "items": None, "added": 1, "by": "t"}]}))
out = anchors()
check("tool: the list shows a stored scope naming a vanished mailbox as such", "gone (no such mailbox)" in out, out)
# the anchors service has not reported a mailbox: a scope cannot be checked, so it is stored as typed
saved_status = pathlib.Path(core.STATUS).read_text()
os.remove(core.STATUS)
(T / "store/anchors.json").write_text("{}")
out = anchors(add=["gmail:q@Whatever:from:pat"])
check("tool: with no mailbox known a scope is stored as typed (the anchors service reports one it cannot read)", "gmail:q@Whatever:from:pat" in stored() and server._gmail_boxes() == {}, (stored(), out))
refuse("tool: with no mailbox known a space in a scope is still refused", lambda: anchors(add=["gmail:q@work, home:from:pat"]), "commas with no spaces")
anchors(add=["gmail:q@WORK:from:pat", "gmail:q:from:pat"])
check("tool: a scope typed with its own case is stored as typed while no mailbox is known", stored() == ["gmail:q@Whatever:from:pat", "gmail:q@WORK:from:pat", "gmail:q:from:pat"], stored())
# the service now reports its mailboxes: the entry stored as typed and the canonical spelling are one anchor
pathlib.Path(core.STATUS).write_text(saved_status)
check("tool: the mailboxes are known again", server._gmail_boxes() == {"home": BO, "work": ADA}, server._gmail_boxes())
anchors(add=["gmail:q@work:from:pat"])
check("tool: adding the canonical spelling of a scope stored as typed makes no second entry", stored().count("gmail:q@WORK:from:pat") == 1 and "gmail:q@work:from:pat" not in stored() and len(stored()) == 3, stored())
anchors(add=["gmail:q@Work:from:pat"], items=None)
check("tool: …nor does a third spelling", len(stored()) == 3, stored())
anchors(remove=["gmail:q@WORK:from:pat"])
check("tool: the spelling as stored can be removed once the mailboxes are known", "gmail:q@WORK:from:pat" not in stored() and len(stored()) == 2, stored())
anchors(add=["gmail:q@WORK:from:pat#mention=sam"])
anchors(remove=["gmail:q@work:from:pat#mention=sam"])
check("tool: the canonical spelling removes the entry stored as typed (a #mention fragment kept)", not any("mention=sam" in u for u in stored()) and len(stored()) == 2, stored())
(T / "store/anchors.json").write_text("{}")
os.remove(core.STATUS); anchors(add=["gmail:q@WORK:from:pat"]); pathlib.Path(core.STATUS).write_text(saved_status)
anchors(remove=["gmail:q@work:from:pat"])
check("tool: the canonical spelling removes an entry stored as typed", stored() == [], stored())
os.remove(core.STATUS); anchors(add=["gmail:q@work:from:pat"]); pathlib.Path(core.STATUS).write_text(saved_status)
anchors(remove=["gmail:q@WORK:from:pat"])
check("tool: …and the typed spelling removes an entry stored in the canonical one", stored() == [], stored())
# with no names configured the list line of an unscoped anchor does not name the mailboxes by address
pathlib.Path(core.STATUS).write_text(json.dumps({"google": {"accounts": [ADA, BO], "mailboxes": {ADA: ADA, BO: BO}}}))
out = anchors(add=["gmail:q:from:pat"])
check("tool: with no mailbox named the list line of an unscoped anchor carries no address", "Gmail from:pat\n" in out + "\n" and ".test ·" not in out.split("reads the mailboxes")[0], out)
pathlib.Path(core.STATUS).write_text(saved_status)

# ---- config.notes: gmail_names entries the reader skips
nt = lambda gn: _cfg_notes({"anchor_hub": {"gmail_names": gn}})
from stackshot.core import config as _cfgmod
def _cfg_notes(c): return [n for n in _cfgmod.gmail_names_notes(c)]
check("notes: no gmail_names, or a good one, says nothing", _cfg_notes({}) == [] and nt({}) == [] and nt({"work": "ada@example.test", "home-2": "bo@example.test"}) == [], nt({"work": "ada@example.test"}))
check("notes: an invalid email address is named", len(nt({"work": "not-an-address"})) == 1 and "not-an-address" in nt({"work": "not-an-address"})[0], nt({"work": "not-an-address"}))
check("notes: a name with a space, an '@' or a comma is named", all(len(nt({k: "ada@example.test"})) == 1 for k in ("my work", "ada@x", "a,b", "a:b", "")), [nt({k: "ada@example.test"}) for k in ("my work", "ada@x", "a,b")])
check("notes: two names that differ only in case are named once", len(nt({"Work": "ada@example.test", "work": "bo@example.test"})) == 1 and "only in case" in nt({"Work": "ada@example.test", "work": "bo@example.test"})[0], nt({"Work": "ada@example.test", "work": "bo@example.test"}))
check("notes: two names for one address are named once", len(nt({"a": "ada@example.test", "b": "ADA@example.test"})) == 1, nt({"a": "ada@example.test", "b": "ADA@example.test"}))
check("notes: a gmail_names that is no table is named", len(nt("work")) == 1)
check("notes: config.notes carries them, one line each, and the real config has none",
      sum("gmail_names" in n for n in _cfgmod.notes({"anchor_hub": {"gmail_names": {"my work": "x", "w": "ada@example.test"}}})) == 1 and not [n for n in _cfgmod.notes() if "gmail_names" in n], _cfgmod.notes())

# ---- the tool text teaches the syntax
desc = server._ANCHORS_DESC
check("text: the tool description teaches the scope and says the list names the mailboxes", "gmail:q@<mailbox>:<query>" in desc and "every mailbox" in desc and "mailboxes each Gmail anchor reads" in desc, desc[:300])
check("text: the shapes a refusal lists include the scoped form", "gmail:q@<mailbox>:<query>" in server._ANCHOR_SHAPES, server._ANCHOR_SHAPES)

print(f"{len(ran)} checks, {len(fails)} failed")
sys.exit(1 if fails else 0)
